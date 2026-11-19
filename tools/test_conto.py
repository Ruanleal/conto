#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bateria de testes do Contô (v2.0.1).

Executa os blocos REAIS do arquivo .aia entregue (Screen1.bky + Screen1.scm) no simulador ai_sim.py,
simulando o que a pessoa faz no aparelho: digitar, escolher nos menus, tocar nos botoes, fechar e reabrir.

  Uso:  SP=<pasta de trabalho> python3 -I tools/test_conto.py [app/Conto.aia]
  Env:  NEW_DIR=<pasta com Screen1.bky/.scm>  (para testar uma variante, ex.: mutantes)
        FUZZ_RANDOM=<n>  quantidade de textos aleatorios do fuzz do parser

Limite honesto: o simulador reproduz o comportamento lido no codigo-fonte do App Inventor; NAO e um
Android real. O roteiro de conferencia no aparelho esta no relatorio final.
"""
import datetime
import io
import json
import os
import random
import re
import shutil
import sys
import time
import traceback
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_sim import App, java_trim, YailRuntimeError, tabela_de_csv, csv_de_tabela, coerce_to_string, html_exibido   # noqa: E402

SP = os.environ['SP']
AIA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', 'Conto.aia')
WORK = os.environ.get('WORK_DIR') or os.path.join(SP, 'testwork')
OLD_DIR = os.path.join(SP, 'aia_original', 'src', 'appinventor', 'ai_conto', 'Conto') + os.sep
REPORT = os.environ.get('REPORT', os.path.join(SP, 'final201', 'bateria.txt'))
FUZZ_RANDOM = int(os.environ.get('FUZZ_RANDOM', '30000'))

CATS = ['Alimentação', 'Transporte', 'Moradia', 'Saúde', 'Lazer', 'Compras', 'Educação', 'Outros']
PAYS = ['Dinheiro', 'Pix', 'Cartão de crédito', 'Cartão de débito', 'Transferência bancária']
PH_CAT = 'Selecione uma categoria'
PH_PAG = 'Selecione uma forma'

# ----------------------------------------------------------------------------- preparo do pacote
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
if os.environ.get('NEW_DIR'):
    NEW_DIR = os.environ['NEW_DIR'].rstrip('/') + os.sep
    AIA_NOTE = 'variante em ' + NEW_DIR
else:
    ex = os.path.join(WORK, 'aia_new')
    with zipfile.ZipFile(AIA) as z:
        z.extractall(ex)
    NEW_DIR = os.path.join(ex, 'src', 'appinventor', 'ai_conto', 'Conto') + os.sep
    AIA_NOTE = AIA
NEW_BKY, NEW_SCM = NEW_DIR + 'Screen1.bky', NEW_DIR + 'Screen1.scm'
OLD_BKY, OLD_SCM = OLD_DIR + 'Screen1.bky', OLD_DIR + 'Screen1.scm'

ALL_APPS = []


class _SoErros(object):
    '''O que o T20 confere de cada app aberto: a lista de erros de execucao (o mesmo objeto do app).'''
    __slots__ = ('runtime_errors',)

    def __init__(self, app):
        self.runtime_errors = app.runtime_errors


# ----------------------------------------------------------------------------- mini framework
class Ctx(object):
    def __init__(self, tid, title):
        self.tid, self.title = tid, title
        self.n = 0
        self.fails = []
        self.notes = []

    def ok(self, cond, msg):
        self.n += 1
        if not cond:
            self.fails.append(msg)

    def eq(self, got, want, msg):
        self.n += 1
        if got != want:
            self.fails.append('%s: obtido=%r esperado=%r' % (msg, got, want))

    def note(self, line):
        self.notes.append(line)

    def clean(self, app, where=''):
        self.n += 1
        if app.runtime_errors:
            self.fails.append('erros de execucao %s: %s' % (where, app.runtime_errors))


TESTS = []


def test(tid, title):
    def deco(fn):
        TESTS.append((tid, title, fn))
        return fn
    return deco


def fresh(name):
    d = os.path.join(WORK, 'db_' + name)
    shutil.rmtree(d, ignore_errors=True)
    return d


def open_app(db, old=False, now=None):
    app = App(OLD_BKY if old else NEW_BKY, OLD_SCM if old else NEW_SCM, db, now=now)
    ALL_APPS.append((_SoErros(app), old))
    return app


def preencher(app, desc, valor, cat, pag):
    app.type_text('TxtDescricao', desc)
    app.type_text('TxtValor', valor)
    if cat is not None:
        app.select('SpnCategoria', cat)
    if pag is not None:
        app.select('SpnPagamento', pag)


def lancar(app, tipo, desc, valor, cat=None, pag=None):
    """O que a pessoa faz: vai para a aba Lancar (se nao estiver nela), digita, escolhe os dois menus e toca no botao.
    Devolve os avisos novos."""
    if 'PnlLancar' in app.comps and not app.shown('PnlLancar'):
        if 'BtnPerfilVoltar' in app.comps and app.shown('BtnPerfilVoltar'):
            app.click('BtnPerfilVoltar')
        if not app.shown('PnlLancar'):
            app.click('BtnNavLancar')
    preencher(app, desc, valor, cat, pag)
    antes = len(app.alerts)
    app.click('BtnEntrada' if tipo == 'Entrada' else 'BtnDespesa')
    return app.alerts[antes:]


def hist(app):
    """Texto de cada linha do historico: titulo + quebra + detalhe (como a pessoa le)."""
    out = []
    for el in app.comp('ListaHistorico').elements:
        out.append(str(el['Text1']) + '\n' + str(el['Text2']) if isinstance(el, dict) else el)
    return out


def db_raw(db):
    p = os.path.join(db, 'Conto.json')
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}


def db_lancamentos(db):
    raw = db_raw(db).get('lancamentos')
    return json.loads(raw) if raw else None


def ref_brl(c):
    neg = c < 0
    reais, cent = divmod(abs(c), 100)
    return ('-R$ ' if neg else 'R$ ') + format(reais, ',').replace(',', '.') + ',' + '%02d' % cent


def ref_parse(s):
    """Gramatica de referencia (independente do app): padrao brasileiro, centavos exatos ou -1."""
    t = java_trim(s)
    INT = r'(?:[0-9]{1,3}(?:\.[0-9]{3})+|[0-9]+)'
    m = re.fullmatch(r'(' + INT + r')?,([0-9]{0,2})', t)
    if m:
        ip, dp = (m.group(1) or ''), m.group(2)
    elif re.fullmatch(INT, t):
        ip, dp = t, ''
    else:
        m3 = re.fullmatch(r'([0-9]*)\.([0-9]{1,2})', t)
        if not m3:
            return -1
        ip, dp = m3.group(1), m3.group(2)
    ip = ip.replace('.', '')
    if len(ip) > 9 or (ip == '' and dp == ''):
        return -1
    return int(ip or '0') * 100 + int((dp + '00')[:2])


def tipo_br(cent, estilo='pt'):
    reais, c = divmod(cent, 100)
    if estilo == 'pt':
        return format(reais, ',').replace(',', '.') + ',' + '%02d' % c
    if estilo == 'semgrupo':
        return str(reais) + ',' + '%02d' % c
    return str(reais) + ',' + '%02d' % c


# ============================================================================= T00 pacote
def canon(el):
    """Forma canonica de um bloco (sem ids e posicoes) para comparar com o original."""
    parts = [el.tag.split('}')[-1]]
    for k in sorted(el.attrib):
        if k not in ('id', 'x', 'y'):
            parts.append('%s=%s' % (k, el.attrib[k]))
    parts.append((el.text or '').strip())
    for ch in el:
        parts.append(canon(ch))
    return '(' + '|'.join(parts) + ')'


def top_blocks(path):
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    out = {}
    for b in root:
        if b.tag.split('}')[-1] != 'block':
            continue
        t = b.get('type')
        if t in ('procedures_defnoreturn', 'procedures_defreturn', 'global_declaration'):
            key = (t, [c.text for c in b if c.tag.split('}')[-1] == 'field' and c.get('name') == 'NAME'][0])
        else:
            m = [c for c in b if c.tag.split('}')[-1] == 'mutation'][0]
            key = (t, m.get('instance_name'), m.get('event_name'))
        out[key] = canon(b)
    return out


def comp_types(scm_path):
    t = open(scm_path, encoding='utf-8').read()
    d = json.loads(t[t.index('{'): t.rindex('}') + 1])
    out = {}

    def rec(n):
        out[n['$Name']] = (n['$Type'], {k: v for k, v in n.items() if not k.startswith('$') and k != 'Uuid'})
        for ch in n.get('$Components', []):
            rec(ch)
    rec(d['Properties'])
    return out


def used_instances(bky_path):
    import xml.etree.ElementTree as ET
    root = ET.parse(bky_path).getroot()
    return {m.get('instance_name'): m.get('component_type') for m in root.iter()
            if m.tag.split('}')[-1] == 'mutation' and m.get('instance_name')}


def read_props(text):
    return dict(l.split('=', 1) for l in text.splitlines() if '=' in l)


@test('T00', 'Pacote .aia: integridade, arquivos e o que NAO deveria mudar')
def t00(c):
    with zipfile.ZipFile(AIA) as z:
        c.ok(z.testzip() is None, 'zip sem erro de CRC')
        names = z.namelist()
        c.eq(names[:3], ['youngandroidproject/project.properties',
                         'src/appinventor/ai_conto/Conto/Screen1.scm',
                         'src/appinventor/ai_conto/Conto/Screen1.bky'], 'tres primeiros arquivos (mesma estrutura do original)')
        c.ok(all(n.startswith('assets/') and not n.endswith('/') for n in names[3:]), 'o restante do pacote e so assets/')
        c.eq(len(set(names)), len(names), 'nenhuma entrada duplicada no zip')
        props_txt = z.read('youngandroidproject/project.properties').decode('utf-8')
        assets = {n[len('assets/'):]: z.read(n) for n in names[3:]}
    newp = read_props(props_txt)
    oldp = read_props(open(os.path.join(SP, 'aia_original', 'youngandroidproject', 'project.properties'), encoding='utf-8').read())
    c.eq(newp.get('versioncode'), '13', 'versioncode 13 (sobe sobre o 12 da v2.0)')
    c.eq(newp.get('versionname'), '2.0.1', 'versionname 2.0.1')
    mudaram = sorted(k for k in set(oldp) | set(newp) if oldp.get(k) != newp.get(k))
    c.eq(mudaram, sorted(['versioncode', 'versionname', 'color.primary', 'color.primary.dark', 'color.accent']),
         'project.properties: so versao e cores mudaram (mesmo pacote, mesmo nome, mesmo armazenamento)')
    for must in ('Manrope-Medium.ttf', 'Manrope-SemiBold.ttf', 'Manrope-Bold.ttf', 'Manrope-ExtraBold.ttf', 'Manrope-OFL.txt', 'icone.png'):
        c.ok(must in assets, 'asset presente: ' + must)
    c.ok(sum(len(v) for v in assets.values()) < 6 * 1024 * 1024, 'assets somam menos de 6 MB (%d bytes)' % sum(len(v) for v in assets.values()))
    # tela: tudo que os blocos ORIGINAIS usavam continua existindo com o mesmo tipo; dados e identidade preservados
    ns, os_ = comp_types(NEW_SCM), comp_types(OLD_SCM)
    for nome, tipo in sorted(used_instances(OLD_BKY).items()):
        if nome in ('Chart1', 'ChartData2D1'):
            # v1.9 (pedido do usuario): a pizza "Entradas x Despesas" virou a rosca de gastos por categoria, desenhada
            # num Canvas (o grafico de pizza do App Inventor pinta o furo da rosca sempre de branco)
            c.ok(nome not in ns and ns['CanvasRosca'][0] == 'Canvas',
                 'v1.9: %s (%s) foi trocado de proposito pela rosca desenhada no CanvasRosca' % (nome, tipo))
            continue
        if nome in ('SpnCategoria', 'SpnPagamento'):
            # v1.5 (pedido do usuario): o menu nativo vira campo + lista com icones; o substituto precisa existir
            sub = 'BtnCategoria' if nome == 'SpnCategoria' else 'BtnPagamento'
            c.ok(nome not in ns and ns[sub][0] == 'Button', 'v1.5: %s (Spinner) foi trocado de proposito por %s (campo que abre a lista com icones)' % (nome, sub))
            continue
        c.ok(nome in ns and ns[nome][0] == tipo, 'componente usado pelos blocos continua na tela com o mesmo tipo: %s (%s)' % (nome, tipo))
    c.eq(ns['TinyDB1'][1].get('Namespace'), os_['TinyDB1'][1].get('Namespace'), 'TinyDB: mesmo Namespace (os dados antigos continuam sendo lidos)')
    c.eq(ns['Screen1'][1].get('AppName'), os_['Screen1'][1].get('AppName'), 'mesmo nome do app')
    c.eq(ns['TxtValor'][1].get('NumbersOnly'), 'False', 'campo de valor com teclado de texto (aceita virgula)')
    c.eq((ns['CanvasRosca'][0], ns['ClockRosca'][0], ns['CameraFoto'][0]), ('Canvas', 'Clock', 'Camera'),
         'v1.9: rosca num Canvas, o relogio que espera a tela medir o Canvas e a camera do perfil')
    ap0 = open_app(fresh('t00_listas'))
    c.eq(list(ap0.g['listaCats']), CATS, 'lista de categorias (exata, na ordem pedida na v1.3)')
    c.eq(list(ap0.g['listaPags']), PAYS, 'lista de formas de pagamento (exata, na ordem pedida na v1.3)')
    # blocos: o que ja funcionava continua identico ao original; a unica diferenca de BtnLimpar e TODOS -> todos
    nb, ob = top_blocks(NEW_BKY), top_blocks(OLD_BKY)
    for key in [('component_event', 'BtnNavLancar', 'Click'), ('component_event', 'BtnNavHistorico', 'Click'),
                ('component_event', 'BtnNavGrafico', 'Click')]:
        c.ok(key in nb and key in ob and nb[key] == ob[key], 'bloco inalterado vs. original: %s' % (key,))
    # v1.7 (pedido: editar lancamento): tocar numa linha do historico abre Editar / Excluir em vez de so Excluir
    key = ('component_event', 'ListaHistorico', 'AfterPicking')
    c.ok(key in nb and key in ob and nb[key] != ob[key] and 'Editar' in nb[key] and 'Excluir' in nb[key],
         'v1.7: ListaHistorico.AfterPicking mudou de proposito (oferece Editar e Excluir)')
    key = ('component_event', 'BtnLimpar', 'Click')
    c.ok(key in nb and key in ob and nb[key].replace('Apagar todos os', 'Apagar TODOS os') == ob[key],
         'BtnLimpar.Click: a unica diferenca para o original e "TODOS" -> "todos"')
    c.eq(sorted(k for k in ob if k not in nb),
         [('global_declaration', 'categoriasAtuais'), ('global_declaration', 'transacoes'), ('global_declaration', 'valorTexto')],
         'do original so saem as 3 variaveis obsoletas da v1.3 (lista de categorias trocada em tempo de execucao, lista antiga e texto auxiliar); todo procedimento e evento continua')
    c.note('Blocos identicos ao original: 3 botoes de navegacao; BtnLimpar.Click so muda "TODOS" -> "todos"; '
           'ListaHistorico.AfterPicking mudou de proposito na v1.7 (Editar / Excluir)')
    c.note('Pacote: %d arquivos, assets somam %d KB' % (len(names), sum(len(v) for v in assets.values()) // 1024))


# ============================================================================= T01 / T02
@test('T01', 'Selecionar CATEGORIA de forma independente da forma de pagamento (lista com ícones)')
def t01(c):
    app = open_app(fresh('t01'))
    c.eq(app.text('BtnCategoria'), PH_CAT, 'campo categoria comeca com o texto de orientacao')
    c.eq(app.text('BtnPagamento'), PH_PAG, 'campo pagamento comeca com o texto de orientacao')
    app.click('BtnCategoria')
    ops = [e['Text1'] for e in app.comp('ListaOpcoes').elements]
    c.eq(ops, CATS, 'itens da lista de Categoria (exatos, na ordem pedida)')
    c.ok(not (set(ops) & set(PAYS)), 'nenhuma forma de pagamento aparece na lista Categoria')
    c.eq(app.comp('PnlPicker').visible, True, 'lista aberta')
    c.eq(app.comp('PnlLancar').visible, False, 'formulario escondido enquanto a lista esta aberta')
    app.click('BtnPickerVoltar')
    c.eq(app.comp('PnlPicker').visible, False, 'Voltar fecha a lista')
    c.eq(app.comp('PnlLancar').visible, True, 'Voltar mostra o formulario de novo')
    for nome in CATS:
        app.select('SpnCategoria', nome)
        c.eq(app.g['categoriaSel'], nome, 'categoria escolhida')
        c.eq(app.text('BtnCategoria'), nome, 'campo mostra a categoria escolhida')
        c.eq(app.g['pagamentoSel'], '', 'pagamento nao e afetado ao escolher categoria ' + nome)
        c.eq(app.text('BtnPagamento'), PH_PAG, 'campo pagamento segue com a orientacao ao escolher ' + nome)
        c.eq(app.comp('PnlLancar').visible, True, 'formulario volta apos escolher ' + nome)
    app.select('SpnCategoria', 'Lazer')
    for botao in ('BtnEntrada', 'BtnDespesa', 'BtnEntrada'):
        app.type_text('TxtValor', '10,00')
        app.click(botao)
        c.eq(app.g['categoriaSel'], 'Lazer', 'categoria preservada apos %s sem forma de pagamento' % botao)
        c.eq(app.last_alert(), 'Escolha a forma de pagamento.', 'aviso correto (falta o pagamento)')
    c.eq(len(app.g['lancamentos']), 0, 'nada foi gravado sem a forma de pagamento')
    c.clean(app)
    c.note('Categorias na lista: ' + ', '.join(ops))


@test('T02', 'Selecionar FORMA DE PAGAMENTO de forma independente da categoria (lista com ícones)')
def t02(c):
    app = open_app(fresh('t02'))
    app.click('BtnPagamento')
    ops = [e['Text1'] for e in app.comp('ListaOpcoes').elements]
    c.eq(ops, PAYS, 'itens da lista Forma de pagamento (exatos, na ordem pedida)')
    c.ok(not (set(ops) & set(CATS)), 'nenhuma categoria aparece na lista Forma de pagamento')
    app.click('BtnPickerVoltar')
    for nome in PAYS:
        app.select('SpnPagamento', nome)
        c.eq(app.g['pagamentoSel'], nome, 'pagamento escolhido')
        c.eq(app.text('BtnPagamento'), nome, 'campo mostra o pagamento escolhido')
        c.eq(app.g['categoriaSel'], '', 'categoria nao e afetada ao escolher pagamento ' + nome)
        c.eq(app.text('BtnCategoria'), PH_CAT, 'campo categoria segue com a orientacao ao escolher ' + nome)
    app.select('SpnPagamento', 'Pix')
    for botao in ('BtnDespesa', 'BtnEntrada'):
        app.type_text('TxtValor', '10,00')
        app.click(botao)
        c.eq(app.g['pagamentoSel'], 'Pix', 'pagamento preservado apos %s sem categoria' % botao)
        c.eq(app.last_alert(), 'Escolha uma categoria.', 'aviso correto (falta a categoria)')
    c.eq(len(app.g['lancamentos']), 0, 'nada foi gravado sem a categoria')
    c.clean(app)
    c.note('Formas de pagamento na lista: ' + ', '.join(ops))


# ============================================================================= T03 valores
@test('T03', 'Digitar valores com virgula e centavos (15,90 / 25,50 / 125,75 / 1.250,99)')
def t03(c):
    casos = [('15,90', 1590, 'R$ 15,90'), ('25,50', 2550, 'R$ 25,50'),
             ('125,75', 12575, 'R$ 125,75'), ('1.250,99', 125099, 'R$ 1.250,99')]
    for i, (digitado, cent, exibido) in enumerate(casos):
        db = fresh('t03_%d' % i)
        app = open_app(db)
        avisos = lancar(app, 'Despesa', 'Teste', digitado, 'Alimentação', 'Dinheiro')
        c.eq(avisos, ['Despesa registrada!'], 'aviso ao salvar "%s"' % digitado)
        c.eq(app.g['lancamentos'][0][2], cent, 'valor guardado (centavos) para "%s"' % digitado)
        c.ok(type(app.g['lancamentos'][0][2]) is int, 'valor guardado e inteiro exato (nao float/texto) para "%s"' % digitado)
        c.eq(app.text('LblDespesas'), exibido, 'rotulo Despesas para "%s"' % digitado)
        c.eq(app.text('LblSaldo'), '-' + exibido, 'saldo (so uma despesa) para "%s"' % digitado)
        c.ok(hist(app)[0].startswith('\u2212 ' + exibido + '\n'), 'historico mostra %s' % exibido)
        guardado = db_lancamentos(db)
        c.eq(guardado[0][2], cent, 'valor no armazenamento permanente para "%s"' % digitado)
        c.clean(app, digitado)
        c.note('digitado %-9s -> guardado %7d centavos -> exibido %s' % (digitado, cent, exibido))

    # outras formas aceitas (padrao brasileiro e variacoes comuns)
    aceitos = [('15', 1500), ('15,9', 1590), ('15,', 1500), ('0,05', 5), (',50', 50), ('0,5', 50),
               ('1.250', 125000), ('12.345.678,90', 1234567890), ('  15,90  ', 1590), ('1250,99', 125099),
               ('999.999.999,99', 99999999999), ('15.90', 1590), ('1.5', 150), ('007,10', 710)]
    app = open_app(fresh('t03_ok'))
    for txt, cent in aceitos:
        c.eq(app.call_by_name('paraCentavos', txt), cent, 'aceita %r' % txt)
    # rejeitados: o app avisa e NAO grava
    rejeitados = ['', '   ', 'abc', '15,9,0', '1,250.99', '1.2.3', '--5', '-5', '15,999', 'R$ 15,90', '1 250,99',
                  '1..250,00', '1.250,9.9', '1250,99,', ',', '.', '1.234.5', '12.34,56', '1.000.000.000,00',
                  '1234.567', '15,90a', 'a15,90', '١٢,٣٤']
    for txt in rejeitados:
        c.eq(app.call_by_name('paraCentavos', txt), -1, 'rejeita %r' % txt)
    app2 = open_app(fresh('t03_rej'))
    for txt in ['abc', '15,9,0', '1,250.99', '15,999']:
        avisos = lancar(app2, 'Despesa', 'x', txt, 'Lazer', 'Pix')
        c.eq(avisos, ['Valor inválido. Use vírgula nos centavos: 25,90 ou 1.250,99.'], 'aviso para %r' % txt)
        c.eq(app2.text('TxtValor'), txt, 'o texto digitado e mantido para a pessoa corrigir (%r)' % txt)
        c.eq(len(app2.g['lancamentos']), 0, 'nada gravado com valor invalido %r' % txt)
    for txt in ['0', '0,00', ',00', '000']:
        avisos = lancar(app2, 'Despesa', 'x', txt, 'Lazer', 'Pix')
        c.eq(avisos, ['Digite um valor maior que zero.'], 'aviso para zero %r' % txt)
        c.eq(len(app2.g['lancamentos']), 0, 'nada gravado com valor zero %r' % txt)
    c.eq(lancar(app2, 'Despesa', 'x', '', 'Lazer', 'Pix'), ['Informe o valor.'], 'campo valor vazio pede o valor')
    c.clean(app)
    c.clean(app2)


# ============================================================================= T04 / T05
@test('T04', 'Salvar uma DESPESA (fluxo completo, ponta a ponta)')
def t04(c):
    db = fresh('t04')
    app = open_app(db)
    avisos = lancar(app, 'Despesa', 'Mercado', '125,75', 'Alimentação', 'Cartão de débito')
    c.eq(avisos, ['Despesa registrada!'], 'aviso de sucesso (so depois de gravar de verdade)')
    c.eq(app.g['lancamentos'], [['Despesa', 'Mercado', 12575, '11/11/2026 20:55', 'Alimentação', 'Cartão de débito']],
         'registro em memoria (tipo, descricao, centavos, data, categoria, pagamento)')
    c.eq(db_lancamentos(db), [['Despesa', 'Mercado', 12575, '11/11/2026 20:55', 'Alimentação', 'Cartão de débito']],
         'registro no armazenamento permanente')
    c.eq(app.text('TxtDescricao'), '', 'campo descricao limpo apos salvar')
    c.eq(app.text('TxtValor'), '', 'campo valor limpo apos salvar')
    c.eq(app.text('BtnCategoria'), PH_CAT, 'campo categoria volta para a orientacao')
    c.eq(app.text('BtnPagamento'), PH_PAG, 'campo pagamento volta para a orientacao')
    c.eq((app.g['categoriaSel'], app.g['pagamentoSel']), ('', ''), 'selecoes zeradas')
    c.eq(app.text('LblSaldo'), '-R$ 125,75', 'saldo')
    c.eq(app.text('LblEntradas'), 'R$ 0,00', 'entradas')
    c.eq(app.text('LblDespesas'), 'R$ 125,75', 'despesas')
    c.clean(app)
    # sem descricao: usa "Sem descrição"
    avisos = lancar(app, 'Despesa', '   ', '10,00', 'Outros', 'Pix')
    c.eq(avisos, ['Despesa registrada!'], 'despesa sem descricao tambem salva')
    c.eq(app.g['lancamentos'][0][1], 'Sem descrição', 'descricao vazia vira "Sem descrição"')
    c.eq(len(db_lancamentos(db)), 2, 'duas despesas no armazenamento')
    c.clean(app)


@test('T05', 'Salvar uma RECEITA (incluindo trocar de Entrada para Despesa varias vezes)')
def t05(c):
    db = fresh('t05')
    app = open_app(db)
    avisos = lancar(app, 'Entrada', 'Salário', '3.000,00', 'Outros', 'Transferência bancária')
    c.eq(avisos, ['Entrada registrada!'], 'receita salva ja na PRIMEIRA vez (antes exigia tocar 2x)')
    c.eq(app.g['lancamentos'][0], ['Entrada', 'Salário', 300000, '11/11/2026 20:55', 'Outros', 'Transferência bancária'], 'registro da receita')
    c.eq(app.text('LblSaldo'), 'R$ 3.000,00', 'saldo positivo')
    c.eq(app.text('LblEntradas'), 'R$ 3.000,00', 'entradas')
    c.ok(hist(app)[0].startswith('+ R$ 3.000,00\n'), 'historico marca receita com +')
    # alterna Entrada / Despesa e percorre TODAS as categorias e TODOS os pagamentos
    esperado = [['Entrada', 'Salário', 300000, '11/11/2026 20:55', 'Outros', 'Transferência bancária']]
    for i in range(16):
        tipo = 'Entrada' if i % 2 == 0 else 'Despesa'
        cat, pag = CATS[i % len(CATS)], PAYS[i % len(PAYS)]
        cent = 100 * (i + 1) + (i * 7) % 100
        avisos = lancar(app, tipo, 'item %d' % i, tipo_br(cent), cat, pag)
        c.eq(avisos, ['Entrada registrada!' if tipo == 'Entrada' else 'Despesa registrada!'], 'passo %d (%s) salvou' % (i, tipo))
        esperado.insert(0, [tipo, 'item %d' % i, cent, '11/11/2026 20:55', cat, pag])
    c.eq(app.g['lancamentos'], esperado, 'todos os 17 registros, com a categoria e o pagamento EXATOS de cada um')
    for r in app.g['lancamentos']:
        c.ok(r[4] in CATS and r[5] in PAYS, 'categoria e pagamento guardados em campos separados e validos: %r' % (r[4:],))
    c.eq(db_lancamentos(db), esperado, 'armazenamento permanente identico ao da memoria')
    c.clean(app)


# ============================================================================= T06 historico
@test('T06', 'Registros aparecem no HISTÓRICO (formato, ordem, excluir)')
def t06(c):
    db = fresh('t06')
    now = datetime.datetime(2026, 11, 11, 9, 5)
    app = open_app(db, now=now)
    c.eq(app.comp('LblVazio').visible, True, 'mensagem de historico vazio aparece no inicio')
    c.eq(hist(app), [], 'historico vazio no inicio')
    seq = [('Despesa', 'Padaria', '8,40', 'Alimentação', 'Dinheiro'),
           ('Entrada', 'Freela', '1.200,00', 'Outros', 'Pix'),
           ('Despesa', 'Ônibus', '4,60', 'Transporte', 'Cartão de crédito')]
    for i, (t, d, v, ca, pa) in enumerate(seq):
        app.now = datetime.datetime(2026, 11, 11, 9, 5 + i)
        lancar(app, t, d, v, ca, pa)
    c.eq(app.comp('LblVazio').visible, False, 'mensagem de vazio some depois do primeiro registro')
    esperado = ['\u2212 R$ 4,60\nÔnibus  •  11/11/2026 09:07\nCategoria: Transporte\nPagamento: Cartão de crédito',
                '+ R$ 1.200,00\nFreela  •  11/11/2026 09:06\nCategoria: Outros\nPagamento: Pix',
                '\u2212 R$ 8,40\nPadaria  •  11/11/2026 09:05\nCategoria: Alimentação\nPagamento: Dinheiro']
    c.eq(hist(app), esperado, 'linhas do historico (mais novo primeiro, categoria e pagamento em linhas separadas)')
    for linha in hist(app):
        c.ok(' | ' not in linha, 'categoria e pagamento nao ficam mais na mesma linha separados por "|"')
    for linha in esperado:
        c.note(linha.replace('\n', '  //  '))
    # tocar num item e CANCELAR (v1.7: o dialogo mostra o lancamento tocado e oferece Editar / Excluir / Cancelar)
    app.pick_history_row(2)
    p = app.comp('Notifier1').pending
    c.eq((p['texto'], p['title'], p['buttons']), ('Freela\n+ R$ 1.200,00 • 11/11/2026 09:06', 'O que você quer fazer?',
                                                  ['Editar', 'Excluir', 'Cancelar']), 'dialogo mostra o lancamento tocado')
    app.answer_dialog('Cancelar')
    c.eq(hist(app), esperado, 'cancelar nao altera nada')
    # tocar no item do meio e EXCLUIR
    app.pick_history_row(2)
    app.answer_dialog('Excluir')
    c.eq(hist(app), [esperado[0], esperado[2]], 'excluiu exatamente o item tocado')
    c.eq(app.text('LblEntradas'), 'R$ 0,00', 'totais recalculados apos excluir')
    c.eq(app.text('LblDespesas'), 'R$ 13,00', 'totais recalculados apos excluir (4,60 + 8,40)')
    c.eq(len(db_lancamentos(db)), 2, 'exclusao gravada no armazenamento')
    c.clean(app)


# ============================================================================= T07 calculos
@test('T07', 'Valores contados corretamente nos CÁLCULOS (saldo, entradas, despesas, gráfico)')
def t07(c):
    app = open_app(fresh('t07'))
    for t, v in [('Entrada', '1.250,99'), ('Entrada', '3.000,00'), ('Despesa', '15,90'), ('Despesa', '25,50'),
                 ('Despesa', '125,75')]:
        lancar(app, t, t, v, 'Outros', 'Pix')
    c.eq(app.text('LblEntradas'), 'R$ 4.250,99', 'total de entradas = 1250,99 + 3000,00')
    c.eq(app.text('LblDespesas'), 'R$ 167,15', 'total de despesas = 15,90 + 25,50 + 125,75')
    c.eq(app.text('LblSaldo'), 'R$ 4.083,84', 'saldo = 4250,99 - 167,15')
    app.click('BtnNavGrafico')
    c.eq((app.text('LblLegDespValor'), app.text('LblLegEntValor'), app.text('LblLegSaldoValor')),
         ('R$ 167,15', 'R$ 4.250,99', '+ R$ 4.083,84'), 'grafico: total de gastos, entradas e saldo do mes')
    c.eq([l[:3] for l in linhas_cat17(app)], [('Outros', 'R$ 167,15', '100,0% das despesas')], 'grafico: a unica categoria')
    c.ok(arcos_iguais(rosca_vista(app)[0], r_rosca([0] * 7 + [16715], False)), 'rosca: anel inteiro na cor de Outros')
    c.eq(app.comp('LblVazioGraf').visible, False, 'aviso de grafico vazio some')
    # aleatorio: 250 lancamentos, comparado com aritmetica inteira de referencia
    rng = random.Random(20261111)
    app = open_app(fresh('t07_rnd'))
    ent = des = 0
    for i in range(250):
        tipo = rng.choice(['Entrada', 'Despesa'])
        cent = rng.choice([rng.randint(1, 99), rng.randint(100, 99999), rng.randint(100000, 10 ** 9)])
        estilo = rng.choice(['pt', 'semgrupo'])
        avisos = lancar(app, tipo, 'r%d' % i, tipo_br(cent, estilo), rng.choice(CATS), rng.choice(PAYS))
        if avisos != [('Entrada' if tipo == 'Entrada' else 'Despesa') + ' registrada!']:
            c.ok(False, 'lancamento aleatorio %d recusado: %r (%s)' % (i, avisos, tipo_br(cent, estilo)))
        if tipo == 'Entrada':
            ent += cent
        else:
            des += cent
    c.eq(app.text('LblEntradas'), ref_brl(ent), '250 lancamentos: entradas')
    c.eq(app.text('LblDespesas'), ref_brl(des), '250 lancamentos: despesas')
    c.eq(app.text('LblSaldo'), ref_brl(ent - des), '250 lancamentos: saldo')
    c.eq(len(hist(app)), 250, '250 linhas no historico')
    c.note('250 lancamentos aleatorios: entradas %s, despesas %s, saldo %s (conferidos com aritmetica inteira)' %
           (ref_brl(ent), ref_brl(des), ref_brl(ent - des)))
    c.clean(app)


# ============================================================================= T08 persistencia
@test('T08', 'Registros PERSISTEM depois de fechar e reabrir o aplicativo')
def t08(c):
    db = fresh('t08')
    a1 = open_app(db)
    lancar(a1, 'Despesa', 'Mercado', '1.250,99', 'Alimentação', 'Cartão de crédito')
    lancar(a1, 'Entrada', 'Salário', '4.000,00', 'Outros', 'Transferência bancária')
    visto = (hist(a1), a1.text('LblSaldo'), a1.text('LblEntradas'), a1.text('LblDespesas'))
    c.eq(visto[1], 'R$ 2.749,01', 'saldo antes de fechar')
    # "fechar" = descartar a execucao; "reabrir" = nova execucao com o MESMO armazenamento
    a2 = open_app(db)
    c.eq(hist(a2), visto[0], 'historico identico apos reabrir')
    c.eq((a2.text('LblSaldo'), a2.text('LblEntradas'), a2.text('LblDespesas')), visto[1:], 'saldo/entradas/despesas apos reabrir')
    c.eq(a2.comp('LblVazio').visible, False, 'mensagem de vazio continua escondida')
    # continua gravando por cima do que ja existe
    lancar(a2, 'Despesa', 'Café', '7,50', 'Alimentação', 'Dinheiro')
    a3 = open_app(db)
    c.eq(len(a3.g['lancamentos']), 3, 'tres registros apos terceira abertura')
    c.eq(a3.text('LblDespesas'), 'R$ 1.258,49', 'despesas somadas apos reabrir (1250,99 + 7,50)')
    # excluir, reabrir
    a3.pick_history_row(1)
    a3.answer_dialog('Excluir')
    a4 = open_app(db)
    c.eq(len(a4.g['lancamentos']), 2, 'exclusao tambem persiste')
    c.eq(a4.text('LblDespesas'), 'R$ 1.250,99', 'despesas apos excluir e reabrir')
    # apagar tudo, reabrir
    a4.click('BtnNavHistorico')   # a pessoa vai ao historico, onde fica o botao
    a4.click('BtnLimpar')
    c.eq(a4.comp('Notifier1').pending['message'], 'Apagar todos os lançamentos?', 'confirmacao de apagar tudo')
    a4.answer_dialog('Apagar tudo')
    a5 = open_app(db)
    c.eq(a5.g['lancamentos'], [], 'apagar tudo persiste')
    c.eq(hist(a5), [], 'historico vazio')
    c.eq(a5.text('LblSaldo'), 'R$ 0,00', 'saldo zerado')
    c.eq(a5.comp('LblVazio').visible, True, 'mensagem de vazio volta')
    # dados no armazenamento em disco (o que o aparelho guarda)
    c.eq(db_lancamentos(db), [], 'armazenamento em disco contem lista vazia')
    for a in (a1, a2, a3, a4, a5):
        c.clean(a)
    c.note('conteudo gravado depois do 2o lancamento (a1): ver T04/T05; 5 aberturas seguidas conferidas')


# ============================================================================= T09 migracao
@test('T09', 'Dados criados pela versão ANTERIOR (v1.2) continuam aparecendo (migração)')
def t09(c):
    db = fresh('t09')
    # 1) usa o app ANTIGO de verdade para criar dados no formato antigo
    old = open_app(db, old=True)
    lancar(old, 'Despesa', 'Mercado', '15,90', 'Alimentação', 'Dinheiro')
    lancar(old, 'Despesa', 'Uber', '25,5', 'Transporte', 'Pix')
    lancar(old, 'Despesa', 'Aluguel', '1250,00', 'Moradia', 'Transferência bancária')
    # receita no app antigo so entrava na 2a tentativa (primeiro toque trocava a lista)
    old.select('SpnPagamento', 'Pix')
    old.type_text('TxtValor', '3000,00')
    old.select('SpnCategoria', 'Lazer')
    old.click('BtnEntrada')               # 1o toque: troca a lista e zera a categoria
    old.select('SpnCategoria', 'Salário')
    old.select('SpnPagamento', 'Pix')
    old.type_text('TxtDescricao', 'Pagamento')
    old.type_text('TxtValor', '3000,00')
    old.click('BtnEntrada')               # 2o toque: agora salva
    antigo = db_raw(db)['transacoes']
    c.ok(old.g['transacoes'] and len(old.g['transacoes']) == 4, 'o app antigo criou 4 registros (dados reais da v1.2)')
    c.note('formato antigo no disco: ' + antigo[:150] + '...')
    # registro ainda mais antigo (4 campos, valor numerico) injetado a mao
    dados = json.loads(antigo)
    dados.append(['Despesa', 'Registro muito antigo', 10.5, '01/01/2026 08:00'])
    dados.append(['Despesa', 'Lixo sem valor', 'abc', '01/01/2026 08:00', 'Lazer', 'Pix'])
    dados.append('isto nao e um registro')
    raw = db_raw(db)
    raw['transacoes'] = json.dumps(dados, ensure_ascii=False, separators=(',', ':'))
    json.dump(raw, open(os.path.join(db, 'Conto.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    # 2) abre o app NOVO sobre o mesmo armazenamento
    app = open_app(db)
    lst = app.g['lancamentos']
    c.eq([(r[0], r[1], r[2], r[4], r[5]) for r in lst],
         [('Entrada', 'Pagamento', 300000, 'Salário', 'Pix'),
          ('Despesa', 'Aluguel', 125000, 'Moradia', 'Transferência bancária'),
          ('Despesa', 'Uber', 2550, 'Transporte', 'Pix'),
          ('Despesa', 'Mercado', 1590, 'Alimentação', 'Dinheiro'),
          ('Despesa', 'Registro muito antigo', 1050, 'Não informado', 'Não informado'),
          ('Despesa', 'Lixo sem valor', 0, 'Lazer', 'Pix')],
         'registros migrados (valores antigos em reais viram centavos exatos)')
    c.ok(all(type(r[2]) is int for r in lst), 'todos os valores migrados sao inteiros')
    # v1.7: o saldo do topo e de TODOS os lancamentos; os dois quadradinhos sao do MES ATUAL (novembro/2026)
    c.eq(app.text('LblSaldo'), 'R$ 1.698,10', 'saldo com todos os migrados: 3.000,00 - (15,90+25,50+1250,00+10,50+0,00)')
    c.eq(app.text('LblEntradas'), 'R$ 3.000,00', 'entradas migradas (novembro)')
    c.eq(app.text('LblDespesas'), 'R$ 1.291,40', 'despesas de novembro: 15,90+25,50+1250,00 (os dois de 01/01/2026 ficam em janeiro)')
    c.eq(app.text('LblCapDespesas'), 'Despesas em nov', 'o rotulo diz de que mes e o valor')
    app.click('BtnNavHistorico')
    app.click('BtnModoTudo')
    c.eq(len(app.comp('ListaHistorico').elements), 6, 'em Tudo, os 6 migrados aparecem no historico')
    app.click('BtnModoMes')
    c.eq(len(app.comp('ListaHistorico').elements), 4, 'em novembro/2026, 4 (os 2 de 01/01/2026 ficam em janeiro)')
    for _ in range(10):
        app.click('BtnPerAnt')
    c.eq((app.text('LblPeriodo'), len(app.comp('ListaHistorico').elements)), ('Janeiro de 2026', 2),
         'voltando 10 meses: janeiro/2026 com os 2 registros antigos')
    c.eq(seta(app, 'BtnPerAnt'), '', 'janeiro/2026 e o mes mais antigo com lancamento: a seta para tras some')
    c.ok('transacoes' in db_raw(db), 'dados antigos NAO foram apagados (chave "transacoes" permanece)')
    c.eq(len(db_lancamentos(db)), 6, 'migracao gravada na chave nova')
    # 3) reabrir nao duplica
    app2 = open_app(db)
    c.eq(len(app2.g['lancamentos']), 6, 'segunda abertura nao duplica os dados migrados')
    # 4) lancar depois da migracao convive com os migrados
    lancar(app2, 'Despesa', 'Novo', '1.000,01', 'Lazer', 'Pix')
    app3 = open_app(db)
    c.eq(len(app3.g['lancamentos']), 7, 'novo registro soma aos migrados e persiste')
    c.eq(app3.g['lancamentos'][0][2], 100001, 'novo registro em centavos')
    for a in (old, app, app2, app3):
        c.clean(a)


# ============================================================================= T10 falhas de gravacao
@test('T10', 'Falha de gravação NUNCA vira falso "salvo" (aviso de erro + desfaz)')
def t10(c):
    db = fresh('t10')
    app = open_app(db)
    banco = app.comp('TinyDB1')
    banco.drop_writes = True                                # o aparelho "engole" a gravacao
    avisos = lancar(app, 'Despesa', 'Mercado', '10,00', 'Alimentação', 'Pix')
    c.ok(not any('registrada' in a for a in avisos), 'nao mostra "registrada!" quando NAO gravou: %r' % (avisos,))
    c.eq(app.text('LblAviso'), 'Não foi possível gravar. Este lançamento não foi salvo.', 'faixa de erro explica que o lançamento não foi salvo')
    c.eq(app.comp('BoxAviso').visible, True, 'faixa de erro visivel')
    app.fire_timer('ClockAviso')
    c.eq(app.comp('BoxAviso').visible, True, 'faixa de ERRO nao some sozinha (so a de sucesso some)')
    c.eq(app.g['lancamentos'], [], 'lancamento desfeito na memoria (nada de registro fantasma)')
    c.eq(hist(app), [], 'historico nao mostra registro que nao foi salvo')
    c.eq(app.text('LblDespesas'), 'R$ 0,00', 'totais nao incluem registro nao salvo')
    c.eq(app.text('TxtValor'), '10,00', 'campos preservados para tentar de novo')
    c.eq((app.g['categoriaSel'], app.text('BtnCategoria')), ('Alimentação', 'Alimentação'), 'categoria preservada para tentar de novo')
    # volta a funcionar -> tenta de novo sem redigitar
    banco.drop_writes = False
    app.click('BtnDespesa')
    c.eq(app.last_alert(), 'Despesa registrada!', 'sucesso ao tentar de novo')
    c.eq(len(db_lancamentos(db)), 1, 'agora gravado de verdade')
    # excluir com falha
    lancar(app, 'Entrada', 'Salário', '100,00', 'Outros', 'Pix')
    estado = (list(app.g['lancamentos']), hist(app))
    banco.drop_writes = True
    app.pick_history_row(1)
    app.answer_dialog('Excluir')
    c.eq(app.g['lancamentos'], estado[0], 'exclusao que falhou foi desfeita na memoria (mesma ordem)')
    c.eq(hist(app), estado[1], 'historico igual ao de antes')
    c.ok('Nada foi alterado' in app.message_dialogs[-1]['message'], 'caixa de erro na exclusao')
    # apagar tudo com falha
    n_dialogs = len(app.message_dialogs)
    app.click('BtnNavHistorico')   # a pessoa vai ao historico, onde fica o botao
    app.click('BtnLimpar')
    app.answer_dialog('Apagar tudo')
    c.eq(app.g['lancamentos'], estado[0], '"Apagar tudo" que falhou foi desfeito')
    c.eq(len(app.message_dialogs), n_dialogs + 1, 'caixa de erro em "Apagar tudo"')
    banco.drop_writes = False
    app2 = open_app(db)
    c.eq(app2.g['lancamentos'], estado[0], 'depois de reabrir, os dados continuam integros')
    c.clean(app)
    c.clean(app2)


# ============================================================================= T11 validacoes
@test('T11', 'Validações: avisos corretos e nada gravado')
def t11(c):
    app = open_app(fresh('t11'))
    c.eq(lancar(app, 'Despesa', 'x', '10,00', None, None), ['Escolha uma categoria.', 'Escolha a forma de pagamento.'], 'sem categoria nem pagamento (os dois erros aparecem juntos)')
    c.eq(lancar(app, 'Entrada', 'x', '10,00', None, None), ['Escolha uma categoria.', 'Escolha a forma de pagamento.'], 'sem categoria (receita)')
    c.eq(lancar(app, 'Despesa', 'x', '10,00', 'Lazer', None), ['Escolha a forma de pagamento.'], 'sem pagamento')
    c.eq(len(app.g['lancamentos']), 0, 'nada gravado nas tentativas invalidas')
    c.eq(app.comp('Notifier1').pending, None, 'nenhum dialogo aberto')
    c.eq(app.message_dialogs, [], 'nenhuma caixa de erro (nao ha falha de armazenamento)')
    c.clean(app)


# ============================================================================= T12 fuzz parser
@test('T12', 'Fuzz do leitor de valores (paraCentavos) contra gramática de referência independente')
def t12(c):
    app = open_app(fresh('t12'))
    rng = random.Random(7)
    textos = set()
    # a) exaustivo: todos os textos ate 6 caracteres no alfabeto {0,1,virgula,ponto,espaco}
    alfa = ['0', '1', ',', '.', ' ']
    from itertools import product
    for n in range(0, 7):
        for tup in product(alfa, repeat=n):
            textos.add(''.join(tup))
    # b) exaustivo: todos ate 4 caracteres no alfabeto completo
    alfa2 = list('0123456789,. a-')
    for n in range(0, 5):
        for tup in product(alfa2, repeat=n):
            textos.add(''.join(tup))
    n_exaustivo = len(textos)
    # c) aleatorios + numeros bem formados + mutacoes de 1 caractere
    bons = []
    for _ in range(FUZZ_RANDOM // 3):
        cent = rng.choice([rng.randint(0, 99), rng.randint(0, 99999), rng.randint(0, 10 ** 11 - 1)])
        reais, cc = divmod(cent, 100)
        estilo = rng.choice(['pt', 'sem', 'int', 'ponto', 'sepmilhar'])
        if estilo == 'pt':
            s = format(reais, ',').replace(',', '.') + ',' + '%02d' % cc
        elif estilo == 'sem':
            s = str(reais) + ',' + '%02d' % cc
        elif estilo == 'int':
            s = str(reais)
        elif estilo == 'ponto':
            s = str(reais) + '.' + '%02d' % cc
        else:
            s = format(reais, ',').replace(',', '.')
        bons.append(s)
        textos.add(s)
    for _ in range(FUZZ_RANDOM // 3):
        s = rng.choice(bons)
        op = rng.choice(['ins', 'del', 'rep'])
        pos = rng.randint(0, len(s))
        ch = rng.choice(',. 0123456789a-')
        if op == 'ins':
            s = s[:pos] + ch + s[pos:]
        elif op == 'del' and s:
            pos = min(pos, len(s) - 1)
            s = s[:pos] + s[pos + 1:]
        elif s:
            pos = min(pos, len(s) - 1)
            s = s[:pos] + ch + s[pos + 1:]
        textos.add(s)
    for _ in range(FUZZ_RANDOM // 3):
        L = rng.randint(0, 14)
        textos.add(''.join(rng.choice('0123456789' * 3 + ',.,. ' + 'aR$-\t') for _ in range(L)))
    divergencias, erros = [], []
    validos = 0
    t0 = time.time()
    for s in sorted(textos):
        try:
            got = app.call_by_name('paraCentavos', s)
        except Exception as e:     # qualquer excecao e defeito: o leitor nunca pode quebrar
            erros.append((s, repr(e)))
            continue
        want = ref_parse(s)
        if want >= 0:
            validos += 1
        if got != want or type(got) is not int:
            divergencias.append((s, got, want))
    c.n += len(textos)
    c.ok(not erros, 'o leitor nunca gera erro de execucao; primeiros: %r' % (erros[:5],))
    c.ok(not divergencias, 'resultado igual ao da referencia em todos os textos; primeiros desvios: %r' % (divergencias[:8],))
    c.note('%d textos testados (%d exaustivos), %d validos e %d invalidos, %.1fs' %
           (len(textos), n_exaustivo, validos, len(textos) - validos, time.time() - t0))
    c.ok(validos > 5000, 'o fuzz exercitou muitos casos validos (%d)' % validos)


# ============================================================================= T13 formatacao
@test('T13', 'Formatação em reais (formatarMoeda) e ida-e-volta com o leitor')
def t13(c):
    app = open_app(fresh('t13'))
    fixos = [0, 1, 5, 9, 10, 99, 100, 101, 999, 1000, 12345, 99999, 100000, 123456, 999999, 1000000, 100000000,
             123456789, 99999999999, 10 ** 12, 10 ** 15 + 7, -1, -5, -100, -12575, -125099, -99999999999]
    for v in fixos:
        c.eq(app.call_by_name('formatarMoeda', v), ref_brl(v), 'formatarMoeda(%d)' % v)
    c.eq(app.call_by_name('formatarMoeda', 125099), 'R$ 1.250,99', 'exemplo do pedido')
    c.eq(app.call_by_name('formatarMoeda', 0), 'R$ 0,00', 'zero')
    c.eq(app.call_by_name('formatarMoeda', 5), 'R$ 0,05', 'centavos com zero a esquerda')
    rng = random.Random(99)
    for _ in range(4000):
        v = rng.choice([rng.randint(0, 999), rng.randint(0, 10 ** 6), rng.randint(0, 10 ** 11 - 1), -rng.randint(1, 10 ** 8)])
        got = app.call_by_name('formatarMoeda', v)
        c.eq(got, ref_brl(v), 'formatarMoeda(%d)' % v)
        if v >= 0:
            back = app.call_by_name('paraCentavos', got.replace('R$ ', ''))
            c.eq(back, v, 'ida-e-volta %d -> %r' % (v, got))
    c.note('formatarMoeda conferido em %d valores fixos e 4000 aleatorios; ida-e-volta (formatar -> ler) sem perdas' % len(fixos))
    c.clean(app)


# ============================================================================= T14 navegacao e grafico
@test('T14', 'Estado inicial, abas e gráfico continuam funcionando')
def t14(c):
    app = open_app(fresh('t14'))
    c.eq(app.text('LblSaldo'), 'R$ 0,00', 'saldo inicial')
    c.eq(app.text('LblEntradas'), 'R$ 0,00', 'entradas iniciais')
    c.eq(app.text('LblDespesas'), 'R$ 0,00', 'despesas iniciais')
    pl, ph, pg = (app.comp(n) for n in ('PnlLancar', 'PnlHistorico', 'PnlGrafico'))
    c.eq((pl.visible, ph.visible, pg.visible), (True, False, False), 'aba Lançar visivel no inicio')
    app.click('BtnNavHistorico')
    c.eq((pl.visible, ph.visible, pg.visible), (False, True, False), 'aba Histórico')
    app.click('BtnNavGrafico')
    c.eq((pl.visible, ph.visible, pg.visible), (False, False, True), 'aba Gráfico')
    c.eq(app.comp('LblVazioGraf').visible, True, 'aviso de grafico vazio')
    c.ok(arcos_iguais(rosca_vista(app)[0], r_rosca([0] * 8, False)), 'grafico vazio: anel cinza')
    app.click('BtnNavLancar')
    lancar(app, 'Despesa', 'x', '30,00', 'Lazer', 'Pix')
    app.click('BtnNavGrafico')
    c.ok(arcos_iguais(rosca_vista(app)[0], r_rosca([0, 0, 0, 0, 3000, 0, 0, 0], False)), 'grafico so com Lazer: anel inteiro roxo')
    c.eq(app.comp('LblVazioGraf').visible, False, 'aviso de grafico vazio some')
    c.clean(app)


# ============================================================================= T15 antes x depois
@test('T15', 'ANTES x DEPOIS: os mesmos roteiros no app antigo (v1.2) e no novo (v1.4)')
def t15(c):
    for rotulo, old in (('v1.2 (antigo)', True), ('v1.4 (novo)', False)):
        # S1 receita
        app = open_app(fresh('t15_s1_%d' % old), old=old)
        lista = 'transacoes' if old else 'lancamentos'
        av = lancar(app, 'Entrada', 'Salário', '100,00', 'Alimentação', 'Dinheiro')
        s1 = len(app.g[lista]) == 1
        # S2 1.250,99
        app = open_app(fresh('t15_s2_%d' % old), old=old)
        av2 = lancar(app, 'Despesa', 'Mercado', '1.250,99', 'Alimentação', 'Dinheiro')
        s2 = len(app.g[lista]) == 1
        # S3 15,90 com virgula na tela
        app = open_app(fresh('t15_s3_%d' % old), old=old)
        lancar(app, 'Despesa', 'Padaria', '15,90', 'Alimentação', 'Dinheiro')
        s3_label = app.text('LblDespesas')
        s3_hist = hist(app)[0] if hist(app) else ''
        # S5 alternar Despesa -> Entrada -> Despesa com o que o menu oferece
        app = open_app(fresh('t15_s5_%d' % old), old=old)
        salvos = 0
        for tipo in ('Despesa', 'Entrada', 'Despesa', 'Entrada', 'Despesa'):
            if old:
                cat = app.comp('SpnCategoria').items[1]
                pag = app.comp('SpnPagamento').items[2]
            else:
                cat, pag = CATS[0], PAYS[1]
            lancar(app, tipo, 't', '10,00', cat, pag)
            salvos = len(app.g[lista])
        c.note('%-14s | receita(Alimentação) salvou=%s %r | "1.250,99" salvou=%s %r' % (rotulo, s1, av, s2, av2))
        c.note('%-14s | "15,90" -> %r | historico: %s' % (rotulo, s3_label, s3_hist.replace('\n', ' // ')))
        c.note('%-14s | 5 toques alternando Despesa/Entrada/..., salvos=%d de 5' % (rotulo, salvos))
        if old:
            c.eq(s1, False, 'ANTIGO: receita nao salva (defeito reproduzido)')
            c.eq(av, ['Selecione uma categoria antes de salvar.'], 'ANTIGO: aviso enganoso de categoria')
            c.eq(s2, False, 'ANTIGO: "1.250,99" recusado (defeito reproduzido)')
            c.eq(s3_label, 'Despesas: R$ 15.90', 'ANTIGO: ponto no lugar da virgula (defeito reproduzido)')
            c.ok('Categoria: Alimentação | Dinheiro' in s3_hist, 'ANTIGO: categoria e pagamento misturados na mesma linha')
            c.ok(salvos < 5, 'ANTIGO: alternar Despesa/Entrada perde lancamentos (salvos=%d de 5)' % salvos)
        else:
            c.eq(s1, True, 'NOVO: receita salva')
            c.eq(av, ['Entrada registrada!'], 'NOVO: aviso verdadeiro')
            c.eq(s2, True, 'NOVO: "1.250,99" aceito')
            c.eq(s3_label, 'R$ 15,90', 'NOVO: virgula na tela')
            c.ok('Categoria: Alimentação\nPagamento: Dinheiro' in s3_hist, 'NOVO: categoria e pagamento em linhas separadas')
            c.eq(salvos, 5, 'NOVO: todos os 5 toques salvaram')


# ============================================================================= T16 revisao geral
@test('T16', 'Revisão geral: casos de borda que também poderiam quebrar')
def t16(c):
    db = fresh('t16')
    app = open_app(db)
    lancar(app, 'Despesa', 'a', '1,00', 'Lazer', 'Pix')
    lancar(app, 'Despesa', 'b', '2,00', 'Lazer', 'Pix')
    antes = (list(app.g['lancamentos']), hist(app))
    # indice de exclusao invalido (antes: derrubava o app com erro de lista)
    for ruim in (0, 99, -3):
        app.g['indiceSel'] = ruim
        app.fire('Notifier1', 'AfterChoosing', 'Excluir')
        c.eq(app.g['lancamentos'], antes[0], 'indice invalido %d nao remove nem quebra' % ruim)
    # respostas desconhecidas / cancelar
    app.fire('Notifier1', 'AfterChoosing', 'Cancelar')
    c.eq(app.g['lancamentos'], antes[0], 'Cancelar nao altera')
    app.click('BtnNavHistorico')   # a pessoa vai ao historico, onde fica o botao
    app.click('BtnLimpar')
    app.answer_dialog('Cancelar')
    c.eq(app.g['lancamentos'], antes[0], 'Cancelar em "Apagar tudo" nao altera')
    # duplo toque rapido em "- Despesa": o 2o toque ja encontra os menus zerados e NAO duplica
    app.click('BtnNavLancar')
    preencher(app, 'dup', '5,00', 'Saúde', 'Dinheiro')
    app.click('BtnDespesa')
    app.click('BtnDespesa')
    c.eq(len([r for r in app.g['lancamentos'] if r[1] == 'dup']), 1, 'toque duplo nao duplica o lancamento')
    # descricoes dificeis
    dificeis = ['Café "especial"', "C:\\temp\\x", 'linha1\nlinha2', 'ação — ünïcödé ✓ 😀', '123', '007', 'null', '[1,2]',
                '{"a":1}', 'a,b;c', "it's", '  espaços  ', 'x' * 300]
    for d in dificeis:
        avisos = lancar(app, 'Despesa', d, '1,00', 'Outros', 'Pix')
        c.eq(avisos, ['Despesa registrada!'], 'descricao dificil salva: %r' % d[:30])
    a2 = open_app(db)
    gravadas = [r[1] for r in a2.g['lancamentos']][:len(dificeis)][::-1]
    esperado = [d.strip() for d in dificeis]
    c.eq(gravadas, esperado, 'descricoes dificeis voltam identicas depois de reabrir')
    # curiosidade conhecida do App Inventor: "true"/"false" voltam como booleano, mas continuam aparecendo certo
    lancar(a2, 'Despesa', 'true', '1,00', 'Outros', 'Pix')
    lancar(a2, 'Despesa', 'false', '1,00', 'Outros', 'Pix')
    a3 = open_app(db)
    c.ok(a3.g['lancamentos'][0][1] in ('false', False) and a3.g['lancamentos'][1][1] in ('true', True),
         'descricoes "true"/"false" sobrevivem')
    c.ok(hist(a3)[0].split('\n')[1].startswith('false') and hist(a3)[1].split('\n')[1].startswith('true'),
         'e continuam aparecendo corretamente no historico')
    a3.click('BtnNavHistorico')
    lancar(a3, 'Despesa', 'depois', '1,00', 'Outros', 'Pix')
    a4 = open_app(db)
    # 2 (a, b) + 1 (dup) + 13 (descricoes dificeis) + 2 (true/false) + 1 (depois)
    c.eq(len(a4.g['lancamentos']), 19, 'contagem total apos varias aberturas')
    for a in (app, a2, a3, a4):
        c.clean(a)


# ============================================================================= T17 extremos
@test('T17', 'Valores extremos')
def t17(c):
    app = open_app(fresh('t17'))
    c.eq(lancar(app, 'Entrada', 'max', '999.999.999,99', 'Outros', 'Pix'), ['Entrada registrada!'], 'maior valor aceito')
    c.eq(lancar(app, 'Entrada', 'max2', '999.999.999,99', 'Outros', 'Pix'), ['Entrada registrada!'], 'segundo maior valor')
    c.eq(app.text('LblEntradas'), 'R$ 1.999.999.999,98', 'soma acima de 1 bilhao formatada')
    c.eq(lancar(app, 'Entrada', 'estourou', '1.000.000.000,00', 'Outros', 'Pix'),
         ['Valor inválido. Use vírgula nos centavos: 25,90 ou 1.250,99.'], 'valor de 10 digitos e recusado com aviso')
    c.eq(lancar(app, 'Despesa', 'min', '0,01', 'Outros', 'Pix'), ['Despesa registrada!'], 'um centavo')
    c.eq(app.text('LblDespesas'), 'R$ 0,01', 'um centavo exibido')
    c.eq(app.text('LblSaldo'), 'R$ 1.999.999.999,97', 'saldo')
    c.clean(app)


# ============================================================================= T20 erros de execucao
@test('T20', 'Nenhum erro de execução em NENHUM dos aplicativos abertos durante a bateria')
def t20(c):
    novos = [a for a, old in ALL_APPS if not old]
    c.ok(len(novos) >= 30, 'foram abertas %d execucoes do app NOVO durante os testes' % len(novos))
    ruins = [(i, a.runtime_errors) for i, a in enumerate(novos) if a.runtime_errors]
    c.ok(not ruins, 'erros de execucao encontrados: %r' % (ruins[:5],))
    c.note('%d execucoes do app novo, %d erros de execucao' % (len(novos), len(ruins)))


# ============================================================================= v1.4: auxiliares dos testes novos
def java_color(r, g, b):
    """Cor ARGB opaca como inteiro de 32 bits COM sinal (o que o Java guarda)."""
    v = (255 << 24) | (r << 16) | (g << 8) | b
    return v - (1 << 32) if v > 0x7FFFFFFF else v


VERDE = java_color(31, 160, 106)       # #1FA06A  entradas
VERMELHO = java_color(229, 72, 77)     # #E5484D  despesas
BRANCO = java_color(255, 255, 255)
CINZA_ABA = java_color(86, 104, 98)    # #566862  texto da aba inativa
CINZA_ABA_RGB = (86, 104, 98)
MENOS = '−'                       # sinal de menos tipografico usado no historico


def cor_java(valor):
    """Como ChartDataBase.Colors() converte cada item: Long.parseLong e, se > Integer.MAX_VALUE, soma 2*Integer.MIN_VALUE."""
    v = int(str(valor))
    if v > 0x7FFFFFFF:
        v += 2 * -0x80000000
    return v


def cores_fatias(app):
    return [None if x is None else cor_java(x) for x in app.comp('ChartData2D1').slice_colors()]


def ref_p10(e, d):
    """Referencia independente: divisao em ponto flutuante e round do Scheme (metade para o par)."""
    t = e + d
    return int(round(e * 1000 / t)) if t > 0 else 0


def ref_pct(p10):
    return '%d,%d%%' % divmod(p10, 10)


def hist_rows(app):
    return list(app.comp('ListaHistorico').elements)


def pacote_assets():
    with zipfile.ZipFile(AIA) as z:
        return {n[len('assets/'):]: z.read(n) for n in z.namelist() if n.startswith('assets/')}


# ============================================================================= T21 grafico
@test('T21', 'GRÁFICO: rosca de gastos por categoria (cada categoria com a sua cor), total, entradas e saldo; desenhada só depois de a tela medir o Canvas')
def t21(c):
    from PIL import Image
    pal = paleta()
    nos = scm_nos()
    cv, ck = nos['CanvasRosca'], nos['ClockRosca']
    c.eq((cv.get('$Type'), cv.get('Width'), cv.get('Height'), cv.get('BackgroundColor'), cv.get('LineWidth')),
         ('Canvas', '132', '132', '&H00FFFFFF', '26'),
         'Canvas da rosca: 132 x 132 dp, fundo transparente (o furo mostra o cartao, nos dois temas), traco de 26 dp')
    c.eq((ROSCA_CAIXA[0] * 2, 132 - ROSCA_CAIXA[2], ROSCA_CAIXA[2] - ROSCA_CAIXA[0]), (26, 13, 106),
         'caixa do arco = meia espessura para dentro: o anel encosta na borda do Canvas e o furo tem 40 dp de raio')
    c.eq((ck.get('$Type'), ck.get('TimerEnabled'), ck.get('TimerInterval'), ck.get('TimerAlwaysFires')), ('Clock', 'False', '40', 'False'),
         'ClockRosca: desligado ate pedirem o desenho, 40 ms, parado com o app em segundo plano')
    c.ok('Chart1' not in nos and 'ChartData2D1' not in nos, 'a pizza (Chart1/ChartData2D1) saiu da tela')
    # a) app novo: o pedido de desenho existe, mas o Canvas (aba escondida) nunca foi medido -> desiste sem desenhar
    app = open_app(fresh('t21_a'))
    c.eq(app.comp('ClockRosca').get_prop('TimerEnabled'), True, 'ao abrir o app, o desenho da rosca e pedido')
    n = app.esperar_rosca()
    c.eq((n, app.comp('ClockRosca').get_prop('TimerEnabled'), app.comp('CanvasRosca').ops), (50, False, []),
         'com a aba Grafico escondida, o Canvas tem largura 0: 50 tentativas (2 s), o relogio desliga e nada e desenhado')
    app.click('BtnNavGrafico')
    c.eq(app.comp('CanvasRosca').ops, [], 'no toque na aba nada e desenhado ainda (a tela so mede o Canvas depois do evento)')
    arcos, ticks, prob = rosca_vista(app)
    c.eq(prob, [], 'sem lancamentos: anel sem problemas')
    c.ok(ticks >= 1, 'desenhada pelo relogio, depois de a tela medir o Canvas (%d tique)' % ticks)
    c.ok(arcos_iguais(arcos, r_rosca([0] * 8, False)), 'sem lancamentos: anel inteiro cinza (trilho): %r' % (arcos,))
    c.eq((app.shown('LblVazioGraf'), app.text('LblVazioGraf'), app.text('LblLegDespValor'), linhas_cat17(app)),
         (True, 'Sem dados ainda. Registre uma entrada ou despesa.', 'R$ 0,00', []), 'sem lancamentos: aviso, total zero e nenhuma categoria')
    c.clean(app, 'vazio')
    # b) cenarios com o resultado escrito a mao: (nome, lancamentos, total, entradas, saldo, linhas, arcos)
    #    arcos: (inicio, varredura, categoria) -- conta feita a mao, ver o comentario de cada um
    A, Tr, Mo, Sa, La, Co, Ed, Ou = range(8)
    cenarios = [
        ('uma categoria', [('Despesa', '30,00', 'Alimentação')], 'R$ 30,00', 'R$ 0,00', MENOS + ' R$ 30,00',
         [('Alimentação', 'R$ 30,00', '100,0%')], [(-90, 360, A)]),
        # 1350 / 1600 = 84,375% -> 303,75 graus; vao de 2 graus: -89 + 301,75; Alimentacao: 56,25 - 2 a partir de 213,75 + 1
        ('duas categorias e uma entrada', [('Despesa', '1.350,00', 'Moradia'), ('Despesa', '250,00', 'Alimentação'),
                                           ('Entrada', '4.800,00', 'Outros')],
         'R$ 1.600,00', 'R$ 4.800,00', '+ R$ 3.200,00',
         [('Moradia', 'R$ 1.350,00', '84,4%'), ('Alimentação', 'R$ 250,00', '15,6%')], [(-89, 301.75, Mo), (214.75, 54.25, A)]),
        ('empate: ordem da lista', [('Despesa', '50,00', 'Transporte'), ('Despesa', '50,00', 'Alimentação')],
         'R$ 100,00', 'R$ 0,00', MENOS + ' R$ 100,00',
         [('Alimentação', 'R$ 50,00', '50,0%'), ('Transporte', 'R$ 50,00', '50,0%')], [(-89, 178, A), (91, 178, Tr)]),
        # 15/16 = 93,75% -> 937,5 decimos: metade para o par = 938; 1/16 = 62,5 -> 62. Fatias 337,5 e 22,5 graus
        ('arredondamento (metade para o par)', [('Despesa', '0,01', 'Alimentação'), ('Despesa', '0,15', 'Transporte')],
         'R$ 0,16', 'R$ 0,00', MENOS + ' R$ 0,16',
         [('Transporte', 'R$ 0,15', '93,8%'), ('Alimentação', 'R$ 0,01', '6,2%')], [(-89, 335.5, Tr), (248.5, 20.5, A)]),
        # 1 centavo em 1.000.000: fatia de 0,00036 grau; vao = fatia / 3 (0,00012), o resto (0,00024) ainda e desenhado
        ('fatia minuscula', [('Despesa', '9.999,99', 'Moradia'), ('Despesa', '0,01', 'Lazer')],
         'R$ 10.000,00', 'R$ 0,00', MENOS + ' R$ 10.000,00',
         [('Moradia', 'R$ 9.999,99', '100,0%'), ('Lazer', 'R$ 0,01', '0,0%')], [(-89, 357.99964, Mo), (269.9997, 0.00024, La)]),
        ('so entradas', [('Entrada', '50,00', 'Outros')], 'R$ 0,00', 'R$ 50,00', '+ R$ 50,00', [], None),
        # 800, 700, ..., 100 reais = 3.600: fatias de 80, 70, ..., 10 graus, todas com vao de 2
        ('as 8 categorias', [('Despesa', '%d,00' % (800 - 100 * i), CATS[i]) for i in range(8)],
         'R$ 3.600,00', 'R$ 0,00', MENOS + ' R$ 3.600,00',
         [(CATS[0], 'R$ 800,00', '22,2%'), (CATS[1], 'R$ 700,00', '19,4%'), (CATS[2], 'R$ 600,00', '16,7%'),
          (CATS[3], 'R$ 500,00', '13,9%'), (CATS[4], 'R$ 400,00', '11,1%'), (CATS[5], 'R$ 300,00', '8,3%'),
          (CATS[6], 'R$ 200,00', '5,6%'), (CATS[7], 'R$ 100,00', '2,8%')],
         [(-89, 78, A), (-9, 68, Tr), (61, 58, Mo), (121, 48, Sa), (171, 38, La), (211, 28, Co), (241, 18, Ed), (261, 8, Ou)]),
    ]
    for i, (nome, ops, total, ent, saldo, linhas, arcos_m) in enumerate(cenarios):
        db = fresh('t21_b%d' % i)
        app = open_app(db)
        for t, v, cat in ops:
            c.eq(lancar(app, t, nome, v, cat, 'Pix'), [t + ' registrada!'], '%s: lancou %s %s' % (nome, t, v))
        app.click('BtnNavGrafico')
        for a in (app, None):
            if a is None:                                   # reabrir o app: tudo igual
                a = open_app(db)
                a.click('BtnNavGrafico')
                quando = ' (reaberto)'
            else:
                quando = ''
            arcos, _, prob = rosca_vista(a)
            c.eq(prob, [], '%s%s: anel sem problemas' % (nome, quando))
            esp = ([(0.0, 360.0, hexcor(pal.CORES['Trilho'][0]))] if arcos_m is None else
                   [(float(x), float(y), hexcor(pal.CORES_CAT[k][0])) for x, y, k in arcos_m])
            c.ok(arcos_iguais(arcos, esp), '%s%s: arcos (inicio, varredura, cor) = %r, esperado %r' % (nome, quando, fmt_arcos(arcos), fmt_arcos(esp)))
            c.eq((a.text('LblLegDespValor'), a.text('LblLegEntValor'), a.text('LblLegSaldoValor')), (total, ent, saldo),
                 '%s%s: total de gastos, entradas e saldo' % (nome, quando))
            c.eq([(l[0], l[1], l[2], l[6], l[7]) for l in linhas_cat17(a)],
                 [(n_, v_, p_ + ' das despesas', ponto_ref(a, n_), False) for n_, v_, p_ in linhas],
                 '%s%s: lista (nome, valor, %%, bolinha da cor da fatia; sem barra porque nao ha limite)' % (nome, quando))
            c.eq(a.shown('LblVazioGraf'), not linhas, '%s%s: aviso de vazio so sem despesa' % (nome, quando))
            if not linhas:
                c.eq(a.text('LblVazioGraf'), 'Nenhuma despesa em novembro de 2026.', '%s: frase de mes sem despesa' % nome)
            c.clean(a, nome + quando)
        c.note('%-36s total %s  fatias %s' % (nome, total, [CATS[k] for _, _, k in (arcos_m or [])]))
    # c) tema escuro: cores e bolinhas do escuro; e de volta ao claro
    app = open_app(fresh('t21_c'))
    for t, v, cat in cenarios[1][1]:
        lancar(app, t, 'x', v, cat, 'Pix')
    app.click('BtnNavGrafico')
    tot = [25000, 0, 135000, 0, 0, 0, 0, 0]
    for escuro in (True, False, True):
        app.click('ImgTema')
        c.eq(bool(app.g['temaEscuro']), escuro, 'tema trocado')
        arcos, _, prob = rosca_vista(app)
        c.eq(prob, [], 'rosca redesenhada ao trocar o tema (escuro=%s)' % escuro)
        c.ok(arcos_iguais(arcos, r_rosca(tot, escuro)), 'cores das fatias do tema %s: %r' % ('escuro' if escuro else 'claro', fmt_arcos(arcos)))
        c.eq([l[6] for l in linhas_cat17(app)], [pal.img_ponto_cat(3, escuro), pal.img_ponto_cat(1, escuro)],
             'bolinhas do tema %s' % ('escuro' if escuro else 'claro'))
    # a escolha do tema fica salva: reabrir no escuro ja desenha com as cores do escuro
    a2 = open_app(app.db_dir)
    a2.click('BtnNavGrafico')
    c.ok(arcos_iguais(rosca_vista(a2)[0], r_rosca(tot, True)), 'reaberto no escuro: cores do escuro')
    c.clean(app, 'tema')
    # d) a cor de cada fatia e a cor da bolinha da mesma categoria (pixel do centro da imagem do pacote)
    assets = pacote_assets()
    for k, (cl, es) in enumerate(pal.CORES_CAT):
        for esc, h in ((False, cl), (True, es)):
            im = Image.open(io.BytesIO(assets[pal.img_ponto_cat(k + 1, esc)])).convert('RGBA')
            px = im.getpixel((im.width // 2, im.height // 2))
            c.eq('&HFF%02X%02X%02X' % px[:3], hexcor(h), 'bolinha de %s (%s) tem a cor da fatia' % (CATS[k], 'escuro' if esc else 'claro'))
    for k in (0, 1):
        cores = [x[k] for x in pal.CORES_CAT]
        c.eq(len(set(cores)), 8, '8 cores diferentes (%s)' % ('escuro' if k else 'claro'))
        fundo = (pal.CARD, pal.D_CARD)[k]
        piores = min(pal.contraste(x, fundo) for x in cores)
        c.ok(piores >= 3.0, 'toda fatia se destaca do cartao (contraste >= 3:1 para graficos, WCAG 1.4.11): menor %.2f (%s)' % (
            piores, 'escuro' if k else 'claro'))
    # e) a aba ja foi vista (Canvas medido): um lancamento feito no Lancar redesenha a rosca na hora, sem esticar
    app = open_app(fresh('t21_e'))
    app.click('BtnNavGrafico')
    rosca_vista(app)
    lancar(app, 'Despesa', 'Mercado', '80,00', 'Alimentação', 'Pix')
    c.eq(app.shown('PnlGrafico'), False, 'de volta ao Lancar')
    arcos, ticks, prob = rosca_vista(app)
    c.ok(prob == [] and ticks == 1, 'com a aba escondida, o Canvas ja medido e redesenhado no 1o tique: %r' % (prob,))
    c.ok(arcos_iguais(arcos, r_rosca([8000, 0, 0, 0, 0, 0, 0, 0], False)), 'a rosca ja mostra o lancamento novo')
    app.click('BtnNavGrafico')
    c.ok(arcos_iguais(rosca_vista(app)[0], r_rosca([8000, 0, 0, 0, 0, 0, 0, 0], False)), 'e continua certa ao voltar para a aba')
    # f) excluir e "Apagar tudo"
    lancar(app, 'Despesa', 'Uber', '20,00', 'Transporte', 'Pix')
    app.click('BtnNavHistorico')
    app.pick_history_row([i for i, l in enumerate(app.g['lancamentos']) if l[1] == 'Uber'][0] + 1)
    app.answer_dialog('Excluir')             # a janela "Excluir lancamento?" e respondida com "Sim, excluir" (v1.8.1)
    app.click('BtnNavGrafico')
    c.ok(arcos_iguais(rosca_vista(app)[0], r_rosca([8000, 0, 0, 0, 0, 0, 0, 0], False)), 'excluir o Uber tira a fatia do Transporte')
    app.click('BtnNavHistorico')
    app.click('BtnLimpar')
    app.answer_dialog('Apagar tudo')
    app.click('BtnNavGrafico')
    c.ok(arcos_iguais(rosca_vista(app)[0], r_rosca([0] * 8, False)), 'apos "Apagar tudo": anel cinza de novo')
    c.eq((app.shown('LblVazioGraf'), linhas_cat17(app)), (True, []), 'apos "Apagar tudo": aviso e nenhuma categoria')
    c.clean(app, 'excluir/apagar')
    # g) aleatorio: 150 meses contra a referencia, nos dois temas; propriedades que valem para qualquer rosca
    rnd = random.Random(19)
    app = open_app(fresh('t21_r'))
    app.click('BtnNavGrafico')
    for k in range(150):
        if k == 75:
            app.click('ImgTema')
        regs = [[rnd.choice(['Entrada', 'Despesa', 'Despesa']), 'd',
                 rnd.choice([rnd.randint(1, 99), rnd.randint(100, 99999), rnd.randint(100000, 10 ** 8)]),
                 '%02d/11/2026 %02d:%02d' % (rnd.randint(1, 11), rnd.randint(0, 23), rnd.randint(0, 59)),
                 rnd.choice(CATS + ['Categoria antiga']), rnd.choice(PAYS)] for _ in range(rnd.randint(0, 14))]
        injetar(app, regs)
        app.call_by_name('atualizarTudo')
        tot = r_totais_cat(regs, lambda x: x == CHAVE_HOJE)
        arcos, _, prob = rosca_vista(app)
        esc = bool(app.g['temaEscuro'])
        c.eq(prob, [], 'aleatorio %d: anel sem problemas' % k)
        c.ok(arcos_iguais(arcos, r_rosca(tot, esc), 1e-6), 'aleatorio %d: arcos = referencia' % k)
        if sum(tot) > 0:
            # propriedades conferidas so nos arcos do app (sem a formula do vao): partindo do alto, cada categoria tem
            # uma faixa de 360 * gasto / total graus; o arco dela fica CENTRADO na faixa e deixa no maximo 2 graus de vao
            cats = sorted([i for i in range(8) if tot[i] > 0], key=lambda i: (-tot[i], i))
            c.eq(len(arcos), len(cats), 'aleatorio %d: um arco por categoria com gasto' % k)
            faixa_ini, ok_meio, ok_vao = -90.0, True, True
            for (ini, varre, _), i in zip(arcos, cats):
                faixa = tot[i] * 360.0 / sum(tot)
                ok_meio = ok_meio and abs((ini + varre / 2) - (faixa_ini + faixa / 2)) < 1e-6
                ok_vao = ok_vao and (0 <= faixa - varre <= 2.0 + 1e-9) and (len(cats) > 1 or faixa - varre == 0)
                faixa_ini += faixa
            c.ok(ok_meio, 'aleatorio %d: cada arco centrado na faixa da sua categoria (faixas proporcionais ao gasto)' % k)
            c.ok(ok_vao, 'aleatorio %d: vao de 0 a 2 graus (nenhum com uma fatia so)' % k)
            c.ok(abs(faixa_ini - 270.0) < 1e-6, 'aleatorio %d: as faixas fecham a volta inteira' % k)
        c.eq(app.text('LblLegDespValor'), ref_brl(sum(tot)), 'aleatorio %d: total de gastos' % k)
        c.eq(linhas_cat17(app), esperado_cat(app, r_categorias(regs, lambda x: x == CHAVE_HOJE)), 'aleatorio %d: lista' % k)
    c.clean(app, 'aleatorio')
    c.note('150 meses aleatorios (75 no tema claro, 75 no escuro) conferidos contra a referencia; cores conferidas no pixel das bolinhas')


# ============================================================================= T22 historico
@test('T22', 'HISTÓRICO: cada linha tem ícone e sinal do tipo (verde = entrada, vermelho = despesa), sempre alinhados')
def t22(c):
    db = fresh('t22')
    app = open_app(db, now=datetime.datetime(2026, 11, 11, 9, 5))
    seq = [('Entrada', 'Salário', '3.000,00'), ('Despesa', 'Mercado', '125,75'), ('Despesa', 'Ônibus', '4,60'),
           ('Entrada', 'Freela', '1.200,00'), ('Despesa', 'Padaria', '8,40')]
    for i, (t, d, v) in enumerate(seq):
        app.now = datetime.datetime(2026, 11, 11, 9, 5 + i)
        lancar(app, t, d, v, 'Alimentação', 'Pix')
    rows = hist_rows(app)
    c.eq(len(rows), 5, 'cinco linhas no historico')
    esperado = [(MENOS + ' R$ 8,40', 'seta_despesa.png'), ('+ R$ 1.200,00', 'seta_entrada.png'),
                (MENOS + ' R$ 4,60', 'seta_despesa.png'), (MENOS + ' R$ 125,75', 'seta_despesa.png'),
                ('+ R$ 3.000,00', 'seta_entrada.png')]
    for r, (txt, img) in zip(rows, esperado):
        c.ok(isinstance(r, dict) and set(r) == {'Text1', 'Text2', 'Image'}, 'linha com titulo, detalhe e imagem: %r' % (r,))
        c.eq((r['Text1'], r['Image']), (txt, img), 'titulo e icone da linha')
    assets = pacote_assets()

    def confere_alinhamento(rows, rotulo):
        for k, (r, reg) in enumerate(zip(rows, app.g['lancamentos']), 1):
            entrada = reg[0] == 'Entrada'
            c.eq(r['Image'], 'seta_entrada.png' if entrada else 'seta_despesa.png', '%s: icone da linha %d bate com o tipo %s' % (rotulo, k, reg[0]))
            c.eq(r['Text1'][:2], '+ ' if entrada else MENOS + ' ', '%s: sinal da linha %d' % (rotulo, k))
            c.ok(r['Image'] in assets, '%s: imagem %s existe no pacote' % (rotulo, r['Image']))
            linhas = r['Text2'].split('\n')
            c.eq(len(linhas), 3, '%s: detalhe da linha %d tem 3 linhas' % (rotulo, k))
            c.ok(linhas[1].startswith('Categoria: ') and linhas[2].startswith('Pagamento: '), '%s: categoria e pagamento em linhas separadas' % rotulo)
    confere_alinhamento(rows, 'inicial')
    # excluir a 2a linha (a entrada Freela): os icones continuam alinhados com os tipos
    app.pick_history_row(2)
    app.answer_dialog('Excluir')
    rows = hist_rows(app)
    c.eq(len(rows), 4, 'quatro linhas depois de excluir')
    confere_alinhamento(rows, 'depois de excluir')
    # reabrir
    a2 = open_app(db)
    app = a2
    confere_alinhamento(hist_rows(a2), 'depois de reabrir')
    c.clean(a2)


# ============================================================================= T23 abas
@test('T23', 'ABAS: a aba ativa troca de imagem e de cor do texto; só uma ativa por vez')
def t23(c):
    app = open_app(fresh('t23'))
    nav = ['BtnNavLancar', 'BtnNavHistorico', 'BtnNavGrafico']
    assets = pacote_assets()

    def estado():
        return [(app.comp(n).props.get('Image'), cor_java(app.comp(n).props.get('TextColor'))) for n in nav]
    ATIVA, INATIVA = ('aba_ativa.png', BRANCO), ('aba_inativa.png', CINZA_ABA)
    c.eq(estado(), [ATIVA, INATIVA, INATIVA], 'ao abrir o app: so "Lançar" esta ativa')
    painel = ['PnlLancar', 'PnlHistorico', 'PnlGrafico']
    for ordem in ([1, 2, 0], [2, 1, 0], [0, 2, 1], [1, 1, 1], [2, 2, 0, 0]):
        for i in ordem:
            app.click(nav[i])
            c.eq(estado(), [ATIVA if k == i else INATIVA for k in range(3)], 'aba %s ativa: imagens e cores' % nav[i])
            c.eq([app.comp(p).visible for p in painel], [k == i for k in range(3)], 'aba %s ativa: so o painel dela aparece' % nav[i])
    for img in ('aba_ativa.png', 'aba_inativa.png'):
        c.ok(img in assets, 'imagem %s existe no pacote' % img)
    # reabrir: volta para Lancar
    app2 = open_app(fresh('t23b'))
    c.eq([app2.comp(p).visible for p in painel], [True, False, False], 'app reaberto comeca em "Lançar"')
    c.clean(app)
    c.clean(app2)


# ============================================================================= T24 textos
@test('T24', 'TEXTOS: nenhuma palavra em CAIXA ALTA gritante na interface (ex.: "TODOS" do diálogo de apagar)')
def t24(c):
    import xml.etree.ElementTree as ET
    textos = []
    for b in ET.parse(NEW_BKY).getroot().iter():
        if b.tag.split('}')[-1] == 'block' and b.get('type') == 'text':
            for f in b:
                if f.tag.split('}')[-1] == 'field' and f.get('name') == 'TEXT':
                    textos.append(('bloco', f.text or ''))
    t = open(NEW_SCM, encoding='utf-8').read()
    data = json.loads(t[t.index('{'): t.rindex('}') + 1])

    def rec(n):
        for k in ('Text', 'Hint', 'Title', 'Prompt', 'AppName'):
            if k in n:
                textos.append((n['$Name'] + '.' + k, n[k]))
        if 'ElementsFromString' in n:
            for item in n['ElementsFromString'].split(','):
                textos.append((n['$Name'] + '.item', item))
        for ch in n.get('$Components', []):
            rec(ch)
    rec(data['Properties'])
    c.ok(len(textos) > 60, 'foram examinados %d textos da interface' % len(textos))
    caixa_alta = re.compile(r'(?<![A-Za-zÀ-ÿ])[A-ZÀ-Ý]{3,}(?![A-Za-zÀ-ÿ])')
    padrao_data = re.compile(r'[dMyHhms/:. ]+')
    SIGLAS = {'CSV'}
    gritando = [(o, s) for o, s in textos if not padrao_data.fullmatch(s) and set(caixa_alta.findall(s)) - SIGLAS]
    c.ok(not gritando, 'textos com palavra toda em maiuscula: %r' % (gritando[:6],))
    c.ok(not any('TODOS' in s for _, s in textos), 'a palavra "TODOS" nao aparece em nenhum texto')
    c.ok(any(s == 'Apagar todos os lançamentos?' for _, s in textos), 'o texto do dialogo e "Apagar todos os lançamentos?"')
    for _, s in textos:
        c.ok(not re.search('[\u00c3\u00c2][\u0080-\u00bf]|\u00c3[\u00a9\u00a3\u00a7\u00a1\u00b3\u00aa\u00ba]|\u00e2\u20ac', s), 'sem texto corrompido (mojibake): %r' % s[:30])
    # os tres dialogos, exatamente
    app = open_app(fresh('t24'))
    app.click('BtnNavHistorico')   # a pessoa vai ao historico, onde fica o botao
    app.click('BtnLimpar')
    p = app.comp('Notifier1').pending
    c.eq((p['message'], p['title'], p['buttons'], p['cancelable']),
         ('Apagar todos os lançamentos?', 'Contô', ['Apagar tudo', 'Cancelar'], False), 'dialogo de apagar tudo')
    app.answer_dialog('Cancelar')
    lancar(app, 'Despesa', 'x', '1,00', 'Lazer', 'Pix')
    app.click('BtnNavHistorico')
    app.pick_history_row(1)
    p = app.comp('Notifier1').pending
    c.eq((p['texto'], p['title'], p['buttons'], p['cancelable']),
         ('x\n− R$ 1,00 • 11/11/2026 20:55', 'O que você quer fazer?', ['Editar', 'Excluir', 'Cancelar'], True),
         'dialogo de uma linha do historico (v1.7: Editar / Excluir / Cancelar)')
    c.ok(not caixa_alta.search(p['texto'] + p['title'] + ''.join(p['buttons'])), 'dialogo sem palavra em caixa alta')
    c.clean(app)


# ============================================================================= T25 contrato da tela
@test('T25', 'TELA: cada propriedade do .scm e cada propriedade/método/evento usado nos blocos existe no código oficial do App Inventor')
def t25(c):
    import scm_check
    rt = os.environ.get('RT_DIR', os.path.join(SP, 'ai2src', 'repo', 'appinventor', 'components', 'src', 'com',
                                               'google', 'appinventor', 'components', 'runtime'))
    c.ok(os.path.isdir(rt), 'codigo-fonte oficial do runtime disponivel em %s' % rt)
    assets_dir = os.path.join(WORK, 'assets_check')
    shutil.rmtree(assets_dir, ignore_errors=True)
    os.makedirs(assets_dir)
    for nome, dados in pacote_assets().items():
        os.makedirs(os.path.dirname(os.path.join(assets_dir, nome)), exist_ok=True)
        open(os.path.join(assets_dir, nome), 'wb').write(dados)
    erros, info = scm_check.main(NEW_SCM, NEW_BKY, assets_dir, rt)
    for i in info:
        c.note(i)
    c.n += 1
    if erros:
        c.fails.append('%d erros de contrato; primeiros: %r' % (len(erros), erros[:6]))


# ============================================================================= T26 porcentagem
@test('T26', 'Formatação de porcentagem (formatarPercentual) exaustiva de 0,0% a 100,0%')
def t26(c):
    app = open_app(fresh('t26'))
    for p10 in range(0, 1001):
        c.eq(app.call_by_name('formatarPercentual', p10), ref_pct(p10), 'formatarPercentual(%d)' % p10)
    c.eq(app.call_by_name('formatarPercentual', 0), '0,0%', 'zero')
    c.eq(app.call_by_name('formatarPercentual', 5), '0,5%', 'meio por cento')
    c.eq(app.call_by_name('formatarPercentual', 333), '33,3%', 'um terco')
    c.eq(app.call_by_name('formatarPercentual', 1000), '100,0%', 'cem por cento')
    c.clean(app)
    c.note('1001 valores (0 a 1000 decimos de por cento) conferidos')


# ============================================================================= T27 identidade visual dos ativos
@test('T27', 'VISUAL: cores iguais no gráfico, na legenda e nos ícones; contraste de TODOS os textos (medido nas prévias renderizadas)')
def t27(c):
    from PIL import Image
    assets = pacote_assets()

    def abrir(nome):
        return Image.open(io.BytesIO(assets[nome])).convert('RGBA')
    verde, verm = (31, 160, 106), (229, 72, 77)

    def perto(a, b, tol):
        return all(abs(x - y) <= tol for x, y in zip(a[:3], b[:3]))
    # (1) a mesma cor em tres lugares: fatia da pizza (lista de cores dos blocos), ponto da legenda e seta do historico
    for nome, esperado in (('ponto_verde.png', verde), ('ponto_vermelho.png', verm)):
        im = abrir(nome)
        px = im.getpixel((im.width // 2, im.height // 2))
        c.ok(px[3] == 255 and perto(px, esperado, 2), 'centro de %s tem a cor da fatia %r (obtido %r)' % (nome, esperado, px))
    for nome, esperado in (('seta_entrada.png', verde), ('seta_despesa.png', verm)):
        im = abrir(nome)
        pix = [p for p in im.getdata() if p[3] > 250]
        c.ok(len(pix) > 100, '%s tem pixels opacos' % nome)
        pix.sort(key=lambda p: max(p[:3]) - min(p[:3]), reverse=True)
        top = pix[:max(20, len(pix) // 10)]
        media = tuple(sum(p[i] for p in top) / len(top) for i in range(3))
        c.ok(perto(media, esperado, 14), 'a seta de %s e %r (media dos pixels mais saturados %r)' % (nome, esperado, tuple(round(x) for x in media)))
    t = open(NEW_SCM, encoding='utf-8').read()
    data = json.loads(t[t.index('{'): t.rindex('}') + 1])
    por_nome = {}

    def idx(n):
        por_nome[n['$Name']] = n
        for ch in n.get('$Components', []):
            idx(ch)
    idx(data['Properties'])
    c.eq((por_nome['ImgLegEvoE'].get('Picture'), por_nome['ImgLegEvoD'].get('Picture')), ('ponto_verde.png', 'ponto_vermelho.png'),
         'legenda do Mes a mes: ponto verde = entradas, vermelho = despesas')
    # v1.9: a bolinha de cada categoria tem a cor da fatia da rosca (centro da imagem), nos dois temas, e e redonda
    for i_, (cl_, es_) in enumerate(paleta().CORES_CAT, 1):
        for esc_, h_ in ((False, cl_), (True, es_)):
            nome_ = paleta().img_ponto_cat(i_, esc_)
            im_ = abrir(nome_)
            px_ = im_.getpixel((im_.width // 2, im_.height // 2))
            c.ok(px_[3] == 255 and perto(px_, tuple(int(h_[k:k + 2], 16) for k in (1, 3, 5)), 2),
                 'centro de %s tem a cor da fatia %s (obtido %r)' % (nome_, h_, px_))
            c.eq(im_.getpixel((0, 0))[3], 0, '%s: canto transparente (bolinha redonda)' % nome_)
    for nome, dados in assets.items():
        if nome.endswith('.png'):
            Image.open(io.BytesIO(dados)).verify()
            c.ok(True, '%s e um PNG valido' % nome)
    c.ok(abrir('icone.png').size == (512, 512), 'icone do app 512x512')

    # (2) contraste (WCAG AA = 4,5:1) -- funcoes
    def lum(rgb):
        def ch(v):
            v = v / 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = rgb[:3]
        return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)

    def contraste(a, b):
        la, lb = sorted((lum(a), lum(b)), reverse=True)
        return (la + 0.05) / (lb + 0.05)

    def cor(h):
        return (int(h[4:6], 16), int(h[6:8], 16), int(h[8:10], 16))

    def sobre_imagem(nome_img, texto):
        """Pior caso do texto sobre uma imagem (botao/aba): pixel opaco mais claro (texto claro) ou mais escuro (texto escuro) da area central."""
        im = abrir(nome_img)
        w, h = im.size
        pix = [im.getpixel((x, y)) for x in range(int(w * .15), int(w * .85), 3) for y in range(int(h * .25), int(h * .75), 2)]
        pix = [p for p in pix if p[3] > 250]
        pior = max(pix, key=lum) if lum(texto) > 0.4 else min(pix, key=lum)
        return contraste(texto, pior)
    # (2a) texto dos botoes e abas sobre as imagens que os fundamentam
    for botao, img in (('BtnEntrada', 'btn_entrada.png'), ('BtnDespesa', 'btn_despesa.png'), ('BtnLimpar', 'btn_perigo.png'),
                       ('BtnNavLancar', 'aba_ativa.png')):
        n = por_nome[botao]
        txt = cor(n.get('TextColor', '&HFFFFFFFF'))
        if botao == 'BtnNavLancar':
            txt = (255, 255, 255)     # o texto da aba ativa vira branco em tempo de execucao (mostrarAba)
        r = sobre_imagem(n.get('Image', img) if botao != 'BtnNavLancar' else img, txt)
        c.ok(r >= 4.5, '%s: texto sobre %s tem contraste %.2f:1 (>= 4,5)' % (botao, img, r))
    r = sobre_imagem('abas_fundo.png', CINZA_ABA_RGB)
    c.ok(r >= 4.5, 'texto das abas inativas sobre o fundo das abas: %.2f:1 (>= 4,5)' % r)
    # (2b) texto do historico (lista) sobre o cartao branco
    lv = por_nome['ListaHistorico']
    for chave in ('TextColor', 'TextColorDetail'):
        r = contraste(cor(lv[chave]), cor(lv['ElementColor']))
        c.ok(r >= 4.5, 'historico: %s sobre o cartao = %.2f:1 (>= 4,5)' % (chave, r))
    # (2c) todos os Label/TextBox: medido nas previas renderizadas a partir do estado real do app
    import medir_contraste
    import preview_sim
    saida = os.environ.get('PREVIEW_DIR') or os.path.join(SP, 'render', 'final')
    os.makedirs(saida, exist_ok=True)
    preview_sim.main(AIA, saida, rects=True)
    scm_extraido = os.path.join(saida, '_pacote', 'src', 'appinventor', 'ai_conto', 'Conto', 'Screen1.scm')
    total = 0
    CENAS = ('lancar_vazio', 'lancar_preenchido', 'lancar_erros', 'lancar_aviso_ok', 'lancar_edicao', 'historico', 'historico_busca',
             'historico_vazio', 'historico_tudo', 'grafico', 'grafico_ano', 'grafico_vazio', 'seletor_categoria', 'limites', 'limites_erro',
             'evolucao', 'evolucao_vazio', 'perfil', 'perfil_vazio', 'perfil_exportou',
             'lancar_preenchido_escuro', 'lancar_erros_escuro', 'lancar_aviso_ok_escuro', 'lancar_edicao_escuro', 'historico_escuro',
             'historico_busca_escuro', 'grafico_escuro', 'seletor_categoria_escuro', 'limites_escuro', 'limites_erro_escuro',
             'evolucao_escuro', 'perfil_escuro',
             'lancar_meta', 'meta_editar', 'evolucao_meta', 'perfil_importou',
             'lancar_meta_escuro', 'meta_editar_escuro', 'evolucao_meta_escuro', 'evolucao_outubro',
             'notificacoes', 'notificacoes_sem_acesso', 'notificacoes_colar_erro', 'lancar_colado', 'lancar_notif',
             'notificacoes_escuro', 'notificacoes_sem_acesso_escuro', 'notificacoes_colar_erro_escuro',
             'lancar_colado_escuro', 'lancar_notif_escuro')
    piores = []
    for aba in CENAS:
        medidos = medir_contraste.medir(saida, scm_extraido, aba)
        total += len(medidos)
        ruins = [m for m in medidos if m[2] < 4.5]
        c.ok(len(medidos) >= 8, 'previa %s: %d textos medidos' % (aba, len(medidos)))
        c.ok(not ruins, 'previa %s: textos com contraste < 4,5:1: %r' % (aba, ruins))
        if medidos:
            piores.append((aba,) + min(medidos, key=lambda m: m[2]))
    c.note('contraste medido em %d textos nas %d previas (%d no tema escuro); imagens em %s' % (total, len(CENAS), sum('escuro' in x for x in CENAS), saida))
    c.note('pior contraste por cena: ' + '; '.join('%s %s %.2f' % (p[0], p[1], p[3]) for p in piores))
    c.note('menor contraste medido na previa do Lancar: %s' % (sorted(medir_contraste.medir(saida, scm_extraido, 'lancar_vazio'), key=lambda m: m[2])[0],))


# ============================================================================= T28-T31 (v1.5)
ICONES_CAT = {'Alimentação': 'ic_cat_alimentacao.png', 'Transporte': 'ic_cat_transporte.png', 'Moradia': 'ic_cat_moradia.png',
              'Saúde': 'ic_cat_saude.png', 'Lazer': 'ic_cat_lazer.png', 'Compras': 'ic_cat_compras.png',
              'Educação': 'ic_cat_educacao.png', 'Outros': 'ic_cat_outros.png'}
ICONES_PAG = {'Dinheiro': 'ic_pag_dinheiro.png', 'Pix': 'ic_pag_pix.png', 'Cartão de crédito': 'ic_pag_credito.png',
              'Cartão de débito': 'ic_pag_debito.png', 'Transferência bancária': 'ic_pag_transferencia.png'}


@test('T28', 'ÍCONES: cada categoria e cada forma de pagamento tem seu ícone (lista e campo), sem misturar as duas')
def t28(c):
    assets = pacote_assets()
    app = open_app(fresh('t28'))
    c.eq(app.comp('ImgCatIcone').props.get('Picture'), 'ic_vazio.png', 'campo categoria vazio mostra icone neutro')
    c.eq(app.comp('ImgPagIcone').props.get('Picture'), 'ic_vazio.png', 'campo pagamento vazio mostra icone neutro')
    for tipo, btn, nomes, icones, campo in (('cat', 'BtnCategoria', CATS, ICONES_CAT, 'ImgCatIcone'),
                                             ('pag', 'BtnPagamento', PAYS, ICONES_PAG, 'ImgPagIcone')):
        app.click(btn)
        els = app.comp('ListaOpcoes').elements
        c.eq([e['Text1'] for e in els], nomes, 'nomes na lista (%s)' % tipo)
        c.eq([e['Image'] for e in els], [icones[n] for n in nomes], 'icone de cada linha, na ordem (%s)' % tipo)
        for e in els:
            c.ok(e['Image'] in assets, 'arquivo de icone existe no pacote: %s' % e['Image'])
        c.eq(len(set(e['Image'] for e in els)), len(els), 'nenhum icone repetido na lista (%s)' % tipo)
        app.click('BtnPickerVoltar')
        for nome in nomes:
            app.click(btn)
            app.pick_option(nome)
            c.eq(app.comp(campo).props.get('Picture'), icones[nome], 'campo mostra o icone de %s' % nome)
    # categoria e pagamento nao se misturam: o icone de um nao muda quando se escolhe o outro
    app.click('BtnCategoria'); app.pick_option('Moradia')
    app.click('BtnPagamento'); app.pick_option('Pix')
    c.eq((app.comp('ImgCatIcone').props.get('Picture'), app.comp('ImgPagIcone').props.get('Picture')), ('ic_cat_moradia.png', 'ic_pag_pix.png'),
         'casa na categoria e Pix no pagamento, juntos')
    app.click('BtnCategoria'); app.pick_option('Lazer')
    c.eq(app.comp('ImgPagIcone').props.get('Picture'), 'ic_pag_pix.png', 'trocar a categoria nao mexe no icone do pagamento')
    # tocar no icone tambem abre a lista certa
    app.click('ImgPagIcone')
    c.eq(app.comp('LblPickerTitulo').props.get('Text'), 'Escolha a forma de pagamento', 'tocar no icone do pagamento abre a lista de pagamentos')
    app.click('BtnPickerVoltar')
    app.click('ImgCatIcone')
    c.eq(app.comp('LblPickerTitulo').props.get('Text'), 'Escolha uma categoria', 'tocar no icone da categoria abre a lista de categorias')
    app.click('BtnNavHistorico')
    c.eq((app.comp('PnlPicker').visible, app.comp('PnlHistorico').visible), (False, True), 'trocar de aba fecha a lista')
    # depois de salvar, os dois icones voltam ao neutro
    app.click('BtnNavLancar')
    lancar(app, 'Despesa', 'x', '5,00', 'Moradia', 'Pix')
    c.eq((app.comp('ImgCatIcone').props.get('Picture'), app.comp('ImgPagIcone').props.get('Picture')), ('ic_vazio.png', 'ic_vazio.png'),
         'icones voltam ao neutro depois de salvar')
    # imagens dos icones: PNG valido, quadrado e nao vazio
    from PIL import Image
    for nome in list(ICONES_CAT.values()) + list(ICONES_PAG.values()) + ['ic_vazio.png']:
        im = Image.open(io.BytesIO(assets[nome])).convert('RGBA')
        c.ok(im.width == im.height and sum(1 for p in im.getdata() if p[3] > 200) > 0.5 * im.width * im.height * 0.5, '%s: quadrado e com conteudo' % nome)
    # icones realmente diferentes entre si (imagens distintas, nao so nomes distintos)
    import hashlib
    hs = {nome: hashlib.md5(assets[nome]).hexdigest() for nome in list(ICONES_CAT.values()) + list(ICONES_PAG.values()) + ['ic_vazio.png']}
    c.eq(len(set(hs.values())), len(hs), 'as %d imagens de icone sao todas diferentes entre si' % len(hs))
    # lista de opcoes: layout com imagem e altura fixa (altura "preencher" colapsa dentro de painel de altura automatica)
    tt = open(NEW_SCM, encoding='utf-8').read()
    nos = {}
    def _idx(n):
        nos[n['$Name']] = n
        for ch in n.get('$Components', []):
            _idx(ch)
    _idx(json.loads(tt[tt.index('{'): tt.rindex('}') + 1])['Properties'])
    c.eq(nos['ListaOpcoes'].get('ListViewLayout'), '3', 'lista de opcoes usa o layout "imagem + texto" (3)')
    c.ok(int(nos['ListaOpcoes'].get('Height', '-1')) > 0, 'lista de opcoes tem altura fixa em dp (%s), nao "preencher"' % nos['ListaOpcoes'].get('Height'))
    c.clean(app)


@test('T29', 'ERROS: aparecem em vermelho sob o próprio campo (nada de aviso preto no meio da tela) e somem ao corrigir')
def t29(c):
    app = open_app(fresh('t29'))
    c.eq(app.alerts, [], 'sem avisos no inicio')
    # tudo vazio: os tres erros juntos, cada um no seu campo
    app.click('BtnDespesa')
    c.eq(app.alerts, ['Escolha uma categoria.', 'Escolha a forma de pagamento.', 'Informe o valor.'], 'tres erros, um sob cada campo')
    for lbl, txt, hz, img in (('LblErroCat', 'Escolha uma categoria.', 'HzCampoCat', 'campo_select_erro.png'),
                              ('LblErroPag', 'Escolha a forma de pagamento.', 'HzCampoPag', 'campo_select_erro.png'),
                              ('LblErroValor', 'Informe o valor.', 'HzCampoValor', 'campo_erro.png')):
        c.eq((app.comp(lbl).props.get('Text'), app.comp(lbl).visible), (txt, True), '%s visivel com o texto certo' % lbl)
        c.eq(app.comp(hz).props.get('Image'), img, '%s com borda vermelha' % hz)
    c.eq(app.comp('BoxAviso').visible, False, 'nenhuma faixa de aviso no erro de preenchimento')
    c.eq(app.message_dialogs, [], 'nenhuma caixa/toast preto: erros de preenchimento nao usam o Notifier')
    c.eq(app.comp('Notifier1').pending, None, 'nenhum dialogo aberto')
    # corrigir cada campo apaga so o erro dele
    app.click('BtnCategoria'); app.pick_option('Lazer')
    c.eq((app.comp('LblErroCat').visible, app.comp('HzCampoCat').props.get('Image')), (False, 'campo_select.png'), 'escolher categoria apaga o erro dela')
    c.eq((app.comp('LblErroPag').visible, app.comp('LblErroValor').visible), (True, True), 'erros dos outros campos continuam')
    app.click('BtnPagamento'); app.pick_option('Pix')
    c.eq((app.comp('LblErroPag').visible, app.comp('HzCampoPag').props.get('Image')), (False, 'campo_select.png'), 'escolher pagamento apaga o erro dele')
    c.eq(app.comp('LblErroValor').visible, True, 'erro do valor continua ate digitar')
    app.type_text('TxtValor', '1')
    c.eq((app.comp('LblErroValor').visible, app.comp('HzCampoValor').props.get('Image')), (False, 'campo.png'), 'digitar apaga o erro do valor')
    # valor invalido e valor zero
    for txt, esperado in (('jsjsjsbs', 'Valor inválido. Use vírgula nos centavos: 25,90 ou 1.250,99.'), ('0,00', 'Digite um valor maior que zero.'),
                          ('15,999', 'Valor inválido. Use vírgula nos centavos: 25,90 ou 1.250,99.')):
        app.type_text('TxtValor', txt)
        antes = len(app.alerts)
        app.click('BtnDespesa')
        c.eq(app.alerts[antes:], [esperado], 'mensagem para %r' % txt)
        c.eq((app.comp('LblErroValor').visible, app.comp('HzCampoValor').props.get('Image')), (True, 'campo_erro.png'), 'erro sob o campo valor para %r' % txt)
        c.eq((app.comp('LblErroCat').visible, app.comp('LblErroPag').visible), (False, False), 'categoria e pagamento escolhidos: sem erro neles')
        c.eq(app.text('TxtValor'), txt, 'texto digitado mantido para corrigir')
    c.eq(len(app.g['lancamentos']), 0, 'nada gravado em nenhum erro')
    # o erro some por completo ao salvar com sucesso
    app.type_text('TxtValor', '12,34')
    app.click('BtnDespesa')
    c.eq((app.comp('LblErroValor').visible, app.comp('LblErroCat').visible, app.comp('LblErroPag').visible), (False, False, False), 'sem erros apos salvar')
    c.eq(len(app.g['lancamentos']), 1, 'e salvou')
    c.clean(app)


@test('T30', 'AVISO DE SUCESSO: faixa verde em cima do formulário, some sozinha em 3 s; aviso de falha fica até a próxima ação')
def t30(c):
    app = open_app(fresh('t30'))
    c.eq(app.comp('BoxAviso').visible, False, 'faixa escondida no inicio')
    c.eq(str(app.comp('ClockAviso').props.get('TimerEnabled')), 'False', 'timer parado no inicio')
    c.eq(str(app.comp('ClockAviso').props.get('TimerInterval')), '3000', 'timer de 3 segundos')
    av = lancar(app, 'Entrada', 'Salário', '10,00', 'Outros', 'Pix')
    c.eq(av, ['Entrada registrada!'], 'texto de sucesso (Entrada)')
    c.eq((app.comp('BoxAviso').visible, app.comp('PnlAviso').props.get('Image')), (True, 'aviso_ok.png'), 'faixa verde visivel')
    c.eq(app.comp('ClockAviso').props.get('TimerEnabled'), True, 'timer ligado para esconder a faixa')
    app.fire_timer('ClockAviso')
    c.eq((app.comp('BoxAviso').visible, app.comp('ClockAviso').props.get('TimerEnabled')), (False, False), 'apos 3 s: faixa some e timer desliga')
    av = lancar(app, 'Despesa', 'Café', '3,50', 'Alimentação', 'Dinheiro')
    c.eq(av, ['Despesa registrada!'], 'texto de sucesso (Despesa)')
    # nova tentativa com erro esconde a faixa de sucesso anterior
    app.type_text('TxtValor', 'abc')
    app.click('BtnCategoria'); app.pick_option('Lazer'); app.click('BtnPagamento'); app.pick_option('Pix')
    app.click('BtnDespesa')
    c.eq(app.comp('BoxAviso').visible, False, 'erro de preenchimento esconde a faixa de sucesso anterior')
    c.eq(app.comp('ClockAviso').props.get('TimerEnabled'), False, 'timer desligado quando a faixa e escondida')
    # falha de gravacao: faixa vermelha, permanece, e a proxima tentativa a esconde
    app.comp('TinyDB1').drop_writes = True
    app.type_text('TxtValor', '9,00')
    app.click('BtnDespesa')
    c.eq((app.comp('BoxAviso').visible, app.comp('PnlAviso').props.get('Image')), (True, 'aviso_erro.png'), 'faixa vermelha na falha de gravacao')
    c.eq(app.comp('ClockAviso').props.get('TimerEnabled'), False, 'faixa de erro nao tem timer (fica ate a proxima acao)')
    c.eq(len(app.g['lancamentos']), 2, 'lancamento nao salvo foi desfeito')
    app.comp('TinyDB1').drop_writes = False
    app.click('BtnDespesa')
    c.eq(app.last_alert(), 'Despesa registrada!', 'tentar de novo funciona')
    c.eq(app.comp('PnlAviso').props.get('Image'), 'aviso_ok.png', 'faixa volta a ser verde')
    c.eq(len(app.g['lancamentos']), 3, 'tres lancamentos salvos no total')
    c.clean(app)


@test('T31', 'GRÁFICO EM UM CARTÃO SÓ (pedido do usuário): título com "Limites", total e rosca, entradas e saldo, lista das categorias; "Últimos lançamentos" saiu')
def t31(c):
    nos = scm_nos()
    filhos = lambda n: [ch['$Name'] for ch in nos[n].get('$Components', [])]
    c.eq([n for n in filhos('PnlGrafico') if not n.startswith('Esp')], ['CartaoGrafico'], 'a aba Grafico tem um cartao so')
    c.eq([n for n in filhos('ColGrafico') if not n.startswith('Esp')], ['HzTituloGraf', 'LblSubGraf', 'HzRosca', 'LblVazioGraf', 'PnlCats'],
         'ordem no cartao: titulo (com Limites), subtitulo, total/entradas/saldo ao lado da rosca, aviso de vazio, lista')
    c.eq(filhos('HzTituloGraf'), ['LblTituloGraf', 'BtnLimites'], '"Limites" no titulo do cartao')
    c.eq([n for n in filhos('HzRosca') if not n.startswith('Esp')], ['ColTotGraf', 'CanvasRosca'], 'rosca a direita do total')
    c.eq([n for n in filhos('ColTotGraf') if not n.startswith('Esp')],
         ['LblLegDespValor', 'LblLegEntNome', 'LblLegEntValor', 'LblLegSaldoNome', 'LblLegSaldoValor'], 'total, entradas e saldo')
    c.eq(filhos('PnlCats'), ['PnlCat%d' % i for i in range(1, 9)], '8 linhas de categoria (uma por categoria)')
    c.eq((nos['ImgCat1'].get('Width'), nos['ImgCat1'].get('Height'), nos['HzCatTrilho1'].get('Visible')), ('10', '10', 'False'),
         'cada linha: bolinha de 10 dp; a barra do limite nasce escondida')
    for n in ('CartaoCategorias', 'PnlResumo', 'BtnVerHist', 'LblResEntNomes', 'LblResDespNomes', 'LblTituloCat', 'LblSubCat',
              'LblVazioCat', 'Chart1', 'ChartData2D1', 'PnlLegenda'):
        c.ok(n not in nos, '%s nao existe mais' % n)
    c.eq((nos['LblTituloGraf'].get('Text'), nos['BtnLimites'].get('Text')), ('Gastos por categoria', 'Limites'), 'textos do titulo')
    # funcionamento: "Limites" abre a tela de limites e volta para o Grafico
    app = open_app(fresh('t31'))
    lancar(app, 'Despesa', 'Mercado', '120,00', 'Alimentação', 'Pix')
    lancar(app, 'Entrada', 'Salário', '1.000,00', 'Outros', 'Pix')
    app.click('BtnNavGrafico')
    c.eq((app.text('LblSubGraf'), app.text('LblLegDespValor'), app.text('LblLegEntNome'), app.text('LblLegEntValor'),
          app.text('LblLegSaldoNome'), app.text('LblLegSaldoValor')),
         ('Total de gastos em novembro de 2026', 'R$ 120,00', 'Entradas', 'R$ 1.000,00', 'Saldo do mês', '+ R$ 880,00'), 'textos do cartao')
    c.eq(norm(app.comp('LblLegSaldoValor').props['TextColor']), cor_ficha(app, 'Bom'), 'saldo positivo em verde')
    app.click('BtnLimites')
    c.eq((app.g['abaAtual'], app.shown('PnlOrcamento')), (6, True), '"Limites" abre a tela de limites')
    digitar(app, 'TxtOrc1', '150,00')
    app.click('BtnSalvarOrc')
    c.eq(app.g['abaAtual'], 3, 'salvar volta ao Grafico')
    c.eq(linhas_cat17(app)[0][:5], ('Alimentação', 'R$ 120,00', '80% de R$ 150,00  ' + PONTO + '  sobram R$ 30,00',
                                    cor_ficha(app, 'BarraAlerta'), 58),
         'com limite: barra (80% = amarela, 58% da tela) e o texto do limite na propria linha')
    c.eq(linhas_cat17(app)[0][6:], (ponto_ref(app, 'Alimentação'), True), 'bolinha da categoria e a barra visivel')
    # categoria com limite e SEM gasto: aparece na lista (0% do limite), mas nao vira fatia da rosca
    app.click('BtnLimites')
    digitar(app, 'TxtOrc7', '200,00')
    app.click('BtnSalvarOrc')
    c.eq([l[0] for l in linhas_cat17(app)], ['Alimentação', 'Educação'], 'Educacao (limite, sem gasto) aparece depois de Alimentacao')
    c.eq(linhas_cat17(app)[1][2], '0% de R$ 200,00  ' + PONTO + '  sobram R$ 200,00', 'linha de Educacao: 0% do limite')
    arcos, _, prob = rosca_vista(app)
    c.ok(prob == [] and arcos_iguais(arcos, r_rosca([12000, 0, 0, 0, 0, 0, 0, 0], False)),
         'a rosca so tem as categorias COM gasto: um anel inteiro de Alimentacao (%r)' % (fmt_arcos(arcos),))
    # saldo negativo em vermelho; Ano e Tudo mudam os nomes do saldo
    lancar(app, 'Despesa', 'Aluguel', '2.000,00', 'Moradia', 'Pix')
    app.click('BtnNavGrafico')
    c.eq((app.text('LblLegSaldoValor'), norm(app.comp('LblLegSaldoValor').props['TextColor'])),
         (MENOS + ' R$ 1.120,00', cor_ficha(app, 'Perigo')), 'saldo negativo em vermelho')
    app.click('BtnModoAno')
    c.eq((app.text('LblSubGraf'), app.text('LblLegSaldoNome')), ('Total de gastos em 2026', 'Saldo do ano'), 'modo Ano')
    app.click('BtnModoTudo')
    c.eq((app.text('LblSubGraf'), app.text('LblLegSaldoNome')), ('Total de gastos em todo o período', 'Saldo total'), 'modo Tudo')
    c.clean(app)


# ============================================================================= T32-T35 (v1.6)
FOTOS = os.path.join(SP, 'fotos_teste')
COR = {}      # nome -> (claro, escuro) em &HAARRGGBB, lido do tema.py do gerador (so para os NOMES; os valores sao conferidos na tela)


def cents(txt):
    return ref_parse(txt)


def cor_scm(h):
    return (int(h[4:6], 16), int(h[6:8], 16), int(h[8:10], 16))


def argb(n):
    """int com sinal (como os blocos guardam) -> '&HAARRGGBB'."""
    return '&H%08X' % (n & 0xFFFFFFFF)


def norm(v):
    """Valor de propriedade de cor em forma comparavel: '&HAARRGGBB' tanto para o texto do .scm quanto para o
    numero que os blocos deixam (make-color devolve um inteiro positivo)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return '&H%08X' % (int(v) & 0xFFFFFFFF)
    if isinstance(v, str) and v.startswith('&H'):
        return v.upper()
    return v


def db_val(db, chave):
    raw = db_raw(db).get(chave)
    return None if raw is None else json.loads(raw)


def injetar(app, registros):
    """Troca a lista de lancamentos direto na memoria (preparo de cenario). Como todo bloco do app que troca a lista,
    zera o cache de meses (chavesReg), que e refeito no proximo uso."""
    app.g['lancamentos'] = registros
    app.g['chavesReg'] = []


def despesas_por_categoria(app):
    """Referencia independente: soma das despesas por categoria a partir dos lancamentos gravados, ordenada
    da maior para a menor (empate: ordem da lista de categorias)."""
    tot = {}
    for l in app.g['lancamentos']:
        if l[0] != 'Entrada':
            cat = l[4] if l[4] in CATS else 'Outros'
            tot[cat] = tot.get(cat, 0) + int(l[2])
    return sorted(((v, CATS.index(k), k) for k, v in tot.items() if v > 0), key=lambda t: (-t[0], t[1]))


def linhas_categoria(app):
    out = []
    for i in range(1, 9):
        if app.comp('PnlCat%d' % i).visible:
            out.append((app.text('LblCatNome%d' % i), app.text('LblCatValor%d' % i), app.text('LblCatPct%d' % i),
                        app.comp('ImgCat%d' % i).props.get('Picture'), app.comp('LblCatBarra%d' % i).props.get('Width')))
    return out


@test('T32', 'GRÁFICO POR CATEGORIA: lista do cartão (da maior para a menor), com a bolinha da cor da fatia, valor e % das despesas')
def t32(c):
    app = open_app(fresh('t32'))
    app.click('BtnNavGrafico')
    c.eq((app.shown('LblVazioGraf'), app.comp('PnlCats').visible), (True, False), 'sem despesas: aviso e nenhuma linha')
    lancar(app, 'Entrada', 'Salário', '3.000,00', 'Outros', 'Pix')
    app.click('BtnNavGrafico')
    c.eq((app.shown('LblVazioGraf'), app.comp('PnlCats').visible), (True, False), 'so entradas: continua sem linhas (entradas nao sao gastos)')
    lancar(app, 'Despesa', 'Mercado', '250,00', 'Alimentação', 'Pix')
    lancar(app, 'Despesa', 'Uber', '40,00', 'Transporte', 'Pix')
    lancar(app, 'Despesa', 'Padaria', '60,50', 'Alimentação', 'Dinheiro')
    lancar(app, 'Despesa', 'Aluguel', '1.200,00', 'Moradia', 'Pix')
    lancar(app, 'Despesa', 'Cinema', '40,00', 'Lazer', 'Pix')          # empate com Transporte -> ordem da lista (Transporte antes)
    app.click('BtnNavGrafico')
    c.eq((app.shown('LblVazioGraf'), app.comp('PnlCats').visible), (False, True), 'com despesas: linhas visiveis, aviso escondido')
    # 1.590,50 no total (conferido a mao: 120000/159050 = 75,45%, 31050/159050 = 19,52%, 4000/159050 = 2,51%)
    got = [(l[0], l[1], l[2], l[6], l[7]) for l in linhas_cat17(app)]
    esperado = [('Moradia', 'R$ 1.200,00', '75,4% das despesas', 'ponto_cat3.png', False),
                ('Alimentação', 'R$ 310,50', '19,5% das despesas', 'ponto_cat1.png', False),
                ('Transporte', 'R$ 40,00', '2,5% das despesas', 'ponto_cat2.png', False),
                ('Lazer', 'R$ 40,00', '2,5% das despesas', 'ponto_cat5.png', False)]
    c.eq(got, esperado, 'linhas: nome, valor, %, bolinha da cor da categoria; sem limite, sem barra')
    c.eq(sum(cents(g[1][3:]) for g in got), 159050, 'a soma das linhas = total de despesas')
    c.eq(app.text('LblLegDespValor'), 'R$ 1.590,50', 'o total no alto do cartao = soma das linhas')
    c.eq({l[5] for l in linhas_cat17(app)}, {cor_ficha(app, 'Suave')}, 'texto das linhas sem limite na cor suave')
    # gasto minusculo aparece por ultimo, com 0,0%
    lancar(app, 'Despesa', 'Bala', '0,10', 'Compras', 'Dinheiro')
    app.click('BtnNavGrafico')
    c.eq(linhas_cat17(app)[-1][:3], ('Compras', 'R$ 0,10', '0,0% das despesas'), 'gasto minusculo por ultimo, 0,0%')
    # todas as 8 categorias: 8 bolinhas diferentes, cada uma a da sua categoria
    for cat in CATS:
        lancar(app, 'Despesa', 'x', '10,00', cat, 'Pix')
    app.click('BtnNavGrafico')
    got = linhas_cat17(app)
    ref = despesas_por_categoria(app)
    c.eq([g[0] for g in got], [k for _, _, k in ref], 'ordem das 8 categorias igual a referencia independente')
    c.eq([cents(g[1][3:]) for g in got], [v for v, _, _ in ref], 'valores das 8 categorias iguais a referencia')
    c.eq([g[6] for g in got], ['ponto_cat%d.png' % (CATS.index(g[0]) + 1) for g in got], 'a bolinha de cada linha e a da categoria')
    c.eq(len({g[6] for g in got}), 8, '8 bolinhas distintas')
    # excluir um lancamento recalcula; apagar tudo esvazia
    app.click('BtnNavHistorico')
    idx = [i for i, l in enumerate(app.g['lancamentos']) if l[1] == 'Aluguel'][0] + 1
    app.pick_history_row(idx)
    app.answer_dialog('Excluir')             # a janela "Excluir lancamento?" e respondida com "Sim, excluir" (v1.8.1)
    app.click('BtnNavGrafico')
    got = linhas_cat17(app)
    c.eq([g[0] for g in got], [k for _, _, k in despesas_por_categoria(app)], 'ordem recalculada apos excluir')
    c.ok(got[0][0] != 'Moradia', 'sem o aluguel, Moradia deixa de ser a maior')
    app.click('BtnNavHistorico')
    app.click('BtnLimpar')
    app.answer_dialog('Apagar tudo')
    app.click('BtnNavGrafico')
    c.eq((app.shown('LblVazioGraf'), app.comp('PnlCats').visible, sum(1 for i in range(1, 9) if app.comp('PnlCat%d' % i).visible)),
         (True, False, 0), 'apos apagar tudo: volta ao estado vazio')
    # categoria desconhecida (dado antigo) cai em "Outros"
    injetar(app, [['Despesa', 'velho', 500, '05/11/2026 10:00', 'Categoria que nao existe', 'Pix']])
    app.call_by_name('atualizarGrafico')
    c.eq([(g[0], g[1], g[6]) for g in linhas_cat17(app)], [('Outros', 'R$ 5,00', 'ponto_cat8.png')], 'categoria desconhecida conta em Outros')
    c.clean(app)
    # aleatorio: 300 cenarios contra a referencia independente
    rnd = random.Random(32)
    app2 = open_app(fresh('t32_rnd'))
    for k in range(300):
        regs = [[rnd.choice(['Entrada', 'Despesa', 'Despesa']), 'd', rnd.randint(1, 500000),
                 '%02d/11/2026 %02d:%02d' % (rnd.randint(1, 11), rnd.randint(0, 23), rnd.randint(0, 59)), rnd.choice(CATS),
                 rnd.choice(PAYS)] for _ in range(rnd.randint(0, 12))]
        injetar(app2, regs)
        app2.call_by_name('atualizarGrafico')
        ref = despesas_por_categoria(app2)
        got = linhas_cat17(app2)
        c.eq([(g[0], cents(g[1][3:]), g[6], g[7]) for g in got],
             [(kk, v, 'ponto_cat%d.png' % (CATS.index(kk) + 1), False) for v, _, kk in ref], 'cenario aleatorio %d: ordem, valores e bolinhas' % k)
        if ref:
            tot = sum(v for v, _, _ in ref)
            for g, (v, _, _) in zip(got, ref):
                c.eq(g[2], ref_pct(int(round(v * 1000.0 / tot + 1e-9))) + ' das despesas', 'porcentagem (%d)' % k)
        else:
            c.eq((app2.comp('LblVazioGraf').visible, app2.comp('PnlCats').visible), (True, False), 'cenario %d vazio' % k)
    c.clean(app2)
    c.note('300 cenarios aleatorios conferidos contra uma referencia escrita a parte')


def paleta():
    """Nomes das fichas e valores claro/escuro, lidos do gerador (tema.py) -- os valores sao conferidos na tela."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # tema.py da MESMA versao (v1.7)
    import tema
    return tema


def props_tema(app):
    """Foto das propriedades que o tema troca, para comparar o estado claro x escuro."""
    out = {}
    for nome, comp in app.comps.items():
        for p, v in comp.props.items():
            if p.endswith('Color') or p in ('Image', 'Picture', 'TextColorDetail'):
                out['%s.%s' % (nome, p)] = norm(v)
    return out


@test('T33', 'TEMA: claro e escuro trocam TODAS as cores e imagens, a escolha fica salva, e o visual de cada estado acompanha')
def t33(c):
    T = paleta()
    db = fresh('t33')
    app = open_app(db)
    c.eq(app.g['temaEscuro'], False, 'comeca no tema claro')
    c.eq(app.comp('ImgTema').props['Picture'], 'ic_lua.png', 'botao do cabecalho mostra a lua (toque = escurecer)')
    claro = props_tema(app)
    # cada ficha de cor/imagem do gerador aparece em pelo menos um componente no valor do tema claro
    # v1.7: Bom, Alerta e as cores das barras de limite so aparecem com dados (saldo positivo, limite perto/estourado):
    # conferidas nos dois temas em T40 (limites) e T41 (evolucao)
    DINAMICAS = ('Bom', 'BarraOk', 'BarraAlerta', 'Alerta')
    for nome, (cl, es) in T.CORES.items():
        if nome in DINAMICAS:
            continue
        usado = [k for k, v in claro.items() if v == T.aia(cl)]
        c.ok(usado, 'cor %s (%s) esta em uso no tema claro' % (nome, cl))
    # trocar para o escuro pelo botao do cabecalho
    app.click('ImgTema')
    c.eq(app.g['temaEscuro'], True, 'toque na lua: tema escuro')
    c.eq(app.comp('ImgTema').props['Picture'], 'ic_sol.png', 'botao vira o sol (toque = clarear)')
    escuro = props_tema(app)
    mudaram = [k for k in claro if claro[k] != escuro.get(k)]
    c.ok(len(mudaram) >= 80, '%d propriedades de cor/imagem mudaram ao escurecer (>= 80)' % len(mudaram))
    # nenhuma cor do tema claro sobrou em texto/fundo de componente visivel (exceto as cores de marca fixas)
    fixas = {T.aia(x) for x in ('#FFFFFF', T.HDR_CAP, T.HDR_LIGHT, T.GREEN, T.RED, T.EMERALD, T.MUTED, T.AVISO_OK_TXT, T.DANGER_TXT, T.HINT)}
    sobras = []
    for nome, (cl, es) in T.CORES.items():
        if nome in ('Fundo', 'Cartao', 'Selecao', 'Trilho'):
            cont = [k for k, v in escuro.items() if v == T.aia(cl) and k.split('.')[1] in ('BackgroundColor', 'ElementColor', 'SelectionColor')]
            sobras += cont
    c.eq(sobras, [], 'fundos/cartoes do tema claro nao sobram em nenhum fundo no escuro')
    for k, v in escuro.items():
        comp, prop = k.split('.')
        if prop in ('TextColor', 'HintColor', 'TextColorDetail') and app.comps[comp].ctype in ('Label', 'TextBox', 'Button', 'ListView'):
            c.ok(v not in (T.aia(T.INK), T.aia(T.MUTED), T.aia(T.HINT)) or comp in ('BtnTemaClaro', 'BtnNavHistorico', 'BtnNavGrafico'),
                 'texto de %s (%s) nao fica numa cor do tema claro (sumiria no fundo escuro)' % (comp, v))
    # pontos de conferencia explicitos (claro -> escuro)
    def ver(comp, prop, claro_, escuro_, msg):
        c.eq((claro.get('%s.%s' % (comp, prop)), escuro.get('%s.%s' % (comp, prop))), (norm(claro_), norm(escuro_)), msg)

    def ci(h):
        return h
    ver('Screen1', 'BackgroundColor', ci(T.aia(T.BG)), ci(T.aia(T.D_BG)), 'fundo da tela')
    ver('LblTituloLancar', 'TextColor', ci(T.aia(T.INK)), ci(T.aia(T.D_INK)), 'titulo do cartao')
    ver('LblSubLancar', 'TextColor', ci(T.aia(T.MUTED)), ci(T.aia(T.D_MUTED)), 'subtitulo')
    ver('TxtValor', 'HintColor', ci(T.aia(T.HINT)), ci(T.aia(T.D_HINT)), 'dica dos campos')
    ver('CartaoLancar', 'Image', 'cartao_lancar.png', 'cartao_lancar_d.png', 'imagem do cartao de lancar')
    ver('CartaoGrafico', 'Image', 'cartao_grafico.png', 'cartao_grafico_d.png', 'imagem do cartao do grafico')
    ver('CartaoEvoMeses', 'Image', 'cartao_grafico.png', 'cartao_grafico_d.png', 'imagem do cartao Mes a mes')
    ver('PickerFoto', 'Image', 'pilula_contorno.png', 'pilula_contorno_d.png', 'botao "Escolher da galeria"')
    ver('CartaoPerfil', 'Image', 'cartao_lancar.png', 'cartao_lancar_d.png', 'imagem do cartao do perfil')
    ver('HzCampoDesc', 'Image', 'campo.png', 'campo_d.png', 'campo de texto')
    ver('HzCampoCat', 'Image', 'campo_select.png', 'campo_select_d.png', 'campo de escolha')
    ver('HzNav', 'Image', 'abas_fundo.png', 'abas_fundo_d.png', 'fundo das abas')
    ver('BtnLimpar', 'Image', 'btn_perigo.png', 'btn_perigo_d.png', 'botao apagar tudo')
    ver('ListaHistorico', 'ElementColor', ci(T.aia(T.CARD)), ci(T.aia(T.D_CARD)), 'cartao das linhas do historico')
    ver('ListaHistorico', 'TextColor', ci(T.aia(T.INK)), ci(T.aia(T.D_INK)), 'texto do historico')
    ver('ListaOpcoes', 'BackgroundColor', ci(T.aia(T.BG)), ci(T.aia(T.D_BG)), 'fundo da lista de opcoes')
    ver('LblCatNome1', 'TextColor', ci(T.aia(T.INK)), ci(T.aia(T.D_INK)), 'nome da categoria na lista do grafico')
    ver('ImgCatIcone', 'Picture', 'ic_vazio.png', 'ic_vazio_d.png', 'icone neutro do campo vazio')
    ver('HzCatTrilho1', 'BackgroundColor', ci(T.aia(T.TRILHO)), ci(T.aia(T.D_TRILHO)), 'trilho das barras')
    c.eq((app.comp('BtnTemaEscuro').props['Image'], app.comp('BtnTemaClaro').props['Image']), ('aba_ativa.png', 'aba_inativa.png'), 'opcao Escuro destacada no perfil')
    # a escolha fica salva: fechar e reabrir
    c.eq(db_val(db, 'tema'), 'escuro', 'TinyDB guarda "escuro"')
    app2 = open_app(db)
    c.eq(app2.g['temaEscuro'], True, 'reabrindo: continua escuro')
    c.eq(props_tema(app2), escuro, 'reabrindo: exatamente as mesmas cores/imagens do escuro (nenhuma propriedade esquecida)')
    c.eq(app2.comp('ImgTema').props['Picture'], 'ic_sol.png', 'reabrindo: botao mostra o sol')
    # voltar ao claro pelo perfil
    app2.touch('CanvasTopo')
    app2.click('BtnTemaClaro')
    c.eq(app2.g['temaEscuro'], False, 'opcao Claro no perfil: tema claro')
    volta = props_tema(app2)
    difs = [k for k in claro if claro[k] != volta.get(k) and not k.startswith(('BtnNav', 'BtnTema', 'PnlAviso', 'LblAviso'))]
    c.eq(difs, [], 'voltar ao claro restaura exatamente o visual inicial (fora as abas, que dependem da aba aberta)')
    c.eq(db_val(db, 'tema'), 'claro', 'TinyDB guarda "claro"')
    c.eq(open_app(db).g['temaEscuro'], False, 'reabrindo: claro')
    # trocar de tema com erros na tela e com a faixa de aviso: o estado e repintado na nova paleta
    app3 = open_app(fresh('t33_estados'))
    app3.click('BtnDespesa')                      # 3 erros
    app3.click('ImgTema')
    c.eq(app3.comp('HzCampoValor').props['Image'], 'campo_erro_d.png', 'campo com erro continua com borda de erro, na versao escura')
    c.eq(app3.comp('HzCampoCat').props['Image'], 'campo_select_erro_d.png', 'campo de escolha com erro, versao escura')
    c.eq(norm(app3.comp('LblErroValor').props['TextColor']), T.aia(T.D_DANGER_TXT), 'frase de erro na cor de erro do escuro')
    c.eq(app3.comp('LblErroValor').visible, True, 'erro continua visivel apos trocar o tema')
    lancar(app3, 'Entrada', 'x', '1,00', 'Lazer', 'Pix')
    c.eq(app3.comp('PnlAviso').props['Image'], 'aviso_ok_d.png', 'faixa de sucesso na versao escura')
    app3.click('ImgTema')
    c.eq(app3.comp('PnlAviso').props['Image'], 'aviso_ok.png', 'trocar o tema com a faixa aberta: faixa repintada na versao clara')
    c.eq(app3.comp('BoxAviso').visible, True, 'a faixa continua visivel')
    app3.comp('TinyDB1').drop_writes = True
    app3.click('BtnDespesa')
    app3.type_text('TxtValor', '2,00'); escolher = app3.select
    escolher('SpnCategoria', 'Lazer'); escolher('SpnPagamento', 'Pix')
    app3.click('BtnDespesa')
    app3.click('ImgTema')
    c.eq(app3.comp('PnlAviso').props['Image'], 'aviso_erro_d.png', 'faixa de ERRO (falha de gravacao) repintada na versao escura')
    app3.comp('TinyDB1').drop_writes = False
    # falha ao guardar a preferencia: o tema muda na tela, mas a pessoa e avisada
    app4 = open_app(fresh('t33_falha'))
    app4.comp('TinyDB1').drop_writes = True
    app4.click('ImgTema')
    c.eq(app4.g['temaEscuro'], True, 'o tema muda mesmo sem conseguir guardar')
    c.eq(len(app4.message_dialogs), 1, 'avisa que nao conseguiu guardar o tema')
    c.ok('tema' in app4.message_dialogs[0]['message'], 'mensagem fala do tema: %r' % app4.message_dialogs[0]['message'])
    for a in (app, app2, app3, app4):
        c.clean(a)
    # as imagens escuras existem e sao diferentes das claras
    assets = pacote_assets()
    for nome, (cl, es) in T.IMAGENS.items():
        c.ok(cl in assets and es in assets, 'imagens %s / %s existem no pacote' % (cl, es))
        if nome == 'Nada':
            from PIL import Image as _Im
            c.ok(cl == es and max(_Im.open(io.BytesIO(assets[cl])).convert('RGBA').getchannel('A').getdata()) == 0,
                 '"sem seta" (%s): a mesma imagem 100%% transparente nos dois temas' % cl)
            continue
        c.ok(assets[cl] != assets[es], 'versao escura de %s e diferente da clara' % cl)
    # contraste das cores do tema escuro (pares usados na tela), WCAG >= 4,5
    pares = [(T.D_INK, T.D_CARD), (T.D_MUTED, T.D_CARD), (T.D_HINT, T.D_FIELD), (T.D_EMERALD, T.D_CARD), (T.D_INK, T.D_BG), (T.D_MUTED, T.D_BG),
             (T.D_DANGER_TXT, T.D_CARD), (T.D_DANGER_TXT, T.D_DANGER_BG), (T.D_AVISO_OK_TXT, T.D_AVISO_OK_BG), (T.D_INK, T.D_FIELD),
             (T.D_INK, T.D_SELECTION), (T.D_MUTED, T.D_FIELD)]
    for a, b in pares:
        c.ok(T.contraste(a, b) >= 4.5, 'contraste %s sobre %s = %.2f (>= 4,5)' % (a, b, T.contraste(a, b)))
    c.note('%d propriedades de cor/imagem trocam entre os temas' % len(mudaram))


def caixa(app, spr):
    return app.comp(spr).caixa()


@test('T34', 'PERFIL: nome e foto salvos no aparelho; foto redonda, centralizada e sem deformar; saudação no topo')
def t34(c):
    from PIL import Image
    db = fresh('t34')
    app = open_app(db)
    c.eq(app.comp('PnlPerfil').visible, False, 'perfil comeca escondido')
    tt = open(NEW_SCM, encoding='utf-8').read()
    nos = {}

    def _idx(n):
        nos[n['$Name']] = n
        for ch in n.get('$Components', []):
            _idx(ch)
    _idx(json.loads(tt[tt.index('{'): tt.rindex('}') + 1])['Properties'])
    c.eq(nos['PnlPerfil'].get('Visible'), 'False', 'no desenho da tela o perfil ja nasce escondido (nao pisca antes do Initialize)')
    c.eq(nos['PnlPicker'].get('Visible'), 'False', 'no desenho da tela o seletor ja nasce escondido')
    c.eq(nos['ImgTema'].get('Clickable'), 'True', 'o botao de tema do cabecalho e clicavel')
    c.eq((nos['ImgCatIcone'].get('Clickable'), nos['ImgPagIcone'].get('Clickable')), ('True', 'True'), 'os icones dos campos sao clicaveis')
    c.eq(app.text('LblSaudacao'), '', 'sem nome: sem saudacao')
    c.eq(app.comp('SprFotoTopo').visible, False, 'sem foto: sprite da foto escondido (avatar padrao aparece)')
    c.eq(app.comp('SprFotoPerfil').visible, False, 'sem foto: sprite do perfil escondido')
    c.eq(app.comp('BtnRemoverFoto').visible, False, 'sem foto: "Remover foto" escondido')
    # abrir o perfil tocando no avatar do cabecalho, de cada aba
    for aba, btn in ((2, 'BtnNavHistorico'), (3, 'BtnNavGrafico'), (1, 'BtnNavLancar')):
        app.click(btn)
        app.touch('CanvasTopo')
        c.eq((app.comp('PnlPerfil').visible, app.g['abaAtual'], app.g['abaVolta']), (True, 4, aba), 'avatar abre o perfil e lembra a aba %d' % aba)
        c.eq((app.comp('PnlLancar').visible, app.comp('PnlHistorico').visible, app.comp('PnlGrafico').visible, app.comp('PnlPicker').visible),
             (False, False, False, False), 'no perfil, os outros paineis ficam escondidos')
        app.click('BtnPerfilVoltar')
        c.eq((app.comp('PnlPerfil').visible, app.g['abaAtual']), (False, aba), 'Voltar retorna a aba %d' % aba)
    # nome
    app.touch('CanvasTopo')
    app.type_text('TxtNome', '  Marina Costa  ')
    app.click('BtnSalvarPerfil')
    c.eq(app.g['perfilNome'], 'Marina Costa', 'nome salvo sem espacos sobrando')
    c.eq(app.text('TxtNome'), 'Marina Costa', 'campo mostra o nome limpo')
    c.eq(app.text('LblSaudacao'), 'Olá, Marina', 'saudacao com o primeiro nome')
    c.eq((app.text('LblPerfilMsg'), app.comp('LblPerfilMsg').visible), ('Perfil salvo!', True), 'confirmacao "Perfil salvo!"')
    c.eq(db_val(db, 'perfil_nome'), 'Marina Costa', 'TinyDB guarda o nome')
    app.type_text('TxtNome', 'Marina')
    c.eq(app.comp('LblPerfilMsg').visible, False, 'digitar de novo esconde a confirmacao')
    app.type_text('TxtNome', 'Maria Eduarda Aparecida Silva')
    app.click('BtnSalvarPerfil')
    c.eq(app.text('LblSaudacao'), 'Olá, Maria', 'primeiro nome de um nome composto')
    app.type_text('TxtNome', 'Anna-Luísa')
    app.click('BtnSalvarPerfil')
    c.eq(app.text('LblSaudacao'), 'Olá, Anna-Luísa', 'nome sem espaco fica inteiro')
    app.type_text('TxtNome', 'Wolfeschlegelsteinhausenbergerdorff Jr')
    app.click('BtnSalvarPerfil')
    c.eq(app.text('LblSaudacao'), 'Olá, Wolfeschlegelstei…', 'primeiro nome comprido e abreviado (17 letras + …)')
    app.type_text('TxtNome', '')
    app.click('BtnSalvarPerfil')
    c.eq((app.g['perfilNome'], app.text('LblSaudacao')), ('', ''), 'nome vazio: sem saudacao')
    app.type_text('TxtNome', 'Marina Costa')
    app.click('BtnSalvarPerfil')
    # foto: retrato (900x1200), paisagem (1600x900) e quadrada (800x800)
    casos = (('retrato.jpg', 900, 1200), ('paisagem.jpg', 1600, 900), ('quadrada.png', 800, 800))
    for arq, w0, h0 in casos:
        caminho = os.path.join(FOTOS, arq)
        c.ok(os.path.exists(caminho), 'foto de teste existe: ' + arq)
        app.pick_image(caminho)
        c.eq(app.g['perfilFoto'], caminho, 'caminho da foto guardado (%s)' % arq)
        c.eq(db_val(db, 'perfil_foto'), caminho, 'TinyDB guarda o caminho (%s)' % arq)
        c.eq(app.comp('BtnRemoverFoto').visible, True, '"Remover foto" aparece (%s)' % arq)
        for spr, lado in (('SprFotoPerfil', 96), ('SprFotoTopo', 40)):
            s = app.comp(spr)
            C = 3 * lado
            x, y, w, h = s.caixa()
            c.eq(s.visible, True, '%s visivel (%s)' % (spr, arq))
            c.eq(s.picture, caminho, '%s mostra a foto escolhida' % spr)
            c.eq(min(w, h), lado, '%s: o lado menor da foto = lado do avatar (cobre o circulo) (%s)' % (spr, arq))
            c.ok(abs(w / h - w0 / float(h0)) < 0.03, '%s: proporcao preservada (%.3f vs %.3f) (%s)' % (spr, w / h, w0 / float(h0), arq))
            c.ok(abs((x + w / 2) - C / 2) <= 0.5 and abs((y + h / 2) - C / 2) <= 0.5, '%s: foto centralizada no Canvas (%s)' % (spr, arq))
            c.ok(x >= 0 and y >= 0 and x + w <= C and y + h <= C, '%s: foto inteira dentro do Canvas (nao e empurrada) (%s)' % (spr, arq))
            m = app.comp(spr.replace('Foto', 'Mascara'))
            mx, my, mw, mh = m.caixa()
            c.eq((mx, my, mw, mh), (float(lado - 2), float(lado - 2), float(lado + 4), float(lado + 4)), '%s: moldura centrada e 2 dp maior que o avatar' % spr)
            c.ok(float(m.props.get('Z', 1)) > float(s.props.get('Z', 1)), '%s: moldura por cima da foto' % spr)
            c.ok(int(w) == w and int(h) == h, '%s: tamanhos inteiros (parametros int do App Inventor)' % spr)
        # a parte visivel (miolo lado x lado) e o CENTRO da foto: as marcas dos cantos ficam fora do circulo
        im = Image.open(caminho).convert('RGB')
        s = app.comp('SprFotoPerfil'); x, y, w, h = s.caixa()
        esc = im.width / w
        vis = im.crop((int((96 - x) * esc), int((96 - y) * esc), int((192 - x) * esc), int((192 - y) * esc)))
        cx, cy = vis.width // 2, vis.height // 2
        c.ok(vis.getpixel((cx, cy))[0] > 200 and abs(vis.getpixel((cx, cy))[1] - 188) < 40, 'o centro do circulo mostra o rosto (%s)' % arq)
        c.ok(abs(vis.width - vis.height) <= 2, 'a area visivel e quadrada (%s: %dx%d)' % (arq, vis.width, vis.height))
        # pontos logo por dentro do circulo, nas diagonais: nenhuma marca colorida dos cantos da foto entra no circulo
        r = min(vis.width, vis.height) / 2.0 - 3
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            px = (int(cx + sx * r * 0.7071), int(cy + sy * r * 0.7071))
            p = vis.getpixel(px)
            marca = (p[0] > 230 and p[1] < 90) or (p[1] > 180 and p[0] < 90 and p[2] < 120) or (p[2] > 230 and p[0] < 110) or (p[0] > 230 and p[1] > 190 and p[2] < 100)
            c.ok(not marca, 'as marcas dos cantos da foto ficam fora do circulo visivel (%s %r %r)' % (arq, px, p))
    # a mascara do cabecalho tem exatamente a cor do cabecalho atras dela
    assets = pacote_assets()
    t = open(NEW_SCM, encoding='utf-8').read()
    c.ok(b'mascara_topo.png' in t.encode('utf-8'), 'moldura do cabecalho no .scm')
    masc = Image.open(io.BytesIO(assets['mascara_topo.png'])).convert('RGBA')
    c.ok(masc.getpixel((masc.width // 2, masc.height // 2))[3] == 0, 'moldura: furo transparente no centro')
    c.ok(masc.getpixel((2, 2))[3] == 255, 'moldura: canto opaco')
    # a cor opaca da moldura do cabecalho = cor do cabecalho no ponto onde o avatar fica (senao apareceria um quadrado)
    T = paleta()
    topo = Image.open(io.BytesIO(assets[T.IMG_TOPO])).convert('RGB')
    fx, fy = T.SIZES['avatar_fx'], T.SIZES['avatar_fy']
    ref = topo.crop((int(topo.width * fx) - 6, int(topo.height * fy) - 6, int(topo.width * fx) + 6, int(topo.height * fy) + 6)).resize((1, 1), Image.BOX).getpixel((0, 0))
    canto = masc.getpixel((2, 2))
    c.ok(all(abs(a - b) <= 10 for a, b in zip(canto[:3], ref)), 'moldura do cabecalho na cor do cabecalho (%r vs %r)' % (canto[:3], ref))
    masc2 = Image.open(io.BytesIO(assets['mascara_cartao.png'])).convert('RGBA')
    c.eq(masc2.getpixel((2, 2))[:3], (255, 255, 255), 'moldura do cartao do perfil e branca (cor do cartao)')
    masc3 = Image.open(io.BytesIO(assets['mascara_cartao_d.png'])).convert('RGBA')
    c.ok(all(abs(a - b) <= 2 for a, b in zip(masc3.getpixel((2, 2))[:3], T.hexrgb(T.D_CARD))), 'moldura escura na cor do cartao escuro')
    for nome in ('mascara_cartao.png', 'mascara_cartao_d.png', 'avatar_padrao.png', 'avatar_padrao_d.png', 'avatar_topo.png', 'ic_lua.png', 'ic_sol.png'):
        c.ok(nome in assets, 'asset do perfil presente: ' + nome)
    # fechar e reabrir: nome e foto voltam
    app2 = open_app(db)
    c.eq((app2.g['perfilNome'], app2.text('LblSaudacao')), ('Marina Costa', 'Olá, Marina'), 'reabrindo: saudacao volta')
    c.eq((app2.comp('SprFotoTopo').visible, app2.comp('SprFotoTopo').picture), (True, os.path.join(FOTOS, 'quadrada.png')), 'reabrindo: foto no cabecalho')
    c.eq(caixa(app2, 'SprFotoPerfil'), caixa(app, 'SprFotoPerfil'), 'reabrindo: mesma geometria da foto')
    # foto que sumiu do aparelho: volta ao avatar padrao sem erro
    app2.g['perfilFoto'] = os.path.join(FOTOS, 'nao_existe.jpg')
    app2.call_by_name('mostrarPerfil')
    c.eq((app2.comp('SprFotoTopo').visible, app2.comp('SprFotoPerfil').visible), (False, False), 'foto inexistente: avatar padrao, sem erro')
    c.eq(app2.runtime_errors, [], 'nenhum erro de execucao com foto inexistente')
    # remover foto
    app2.g['perfilFoto'] = os.path.join(FOTOS, 'retrato.jpg'); app2.call_by_name('mostrarPerfil')
    app2.touch('CanvasTopo')
    app2.click('BtnRemoverFoto')
    c.eq((app2.g['perfilFoto'], app2.comp('SprFotoTopo').visible, app2.comp('BtnRemoverFoto').visible), ('', False, False), 'remover foto: volta ao avatar padrao')
    c.eq(db_val(db, 'perfil_foto'), '', 'TinyDB: foto removida')
    c.eq(open_app(db).comp('SprFotoTopo').visible, False, 'reabrindo apos remover: sem foto')
    # v1.9: tocar no avatar grande pergunta de onde vem a foto (camera ou galeria); "Escolher da galeria" abre a galeria
    app2.touch('CanvasPerfil')
    c.eq(app2.dialogs[-1]['buttons'], ['Tirar foto', 'Escolher da galeria', 'Cancelar'], 'toque no avatar grande: camera ou galeria')
    app2.answer_dialog('Escolher da galeria')
    c.eq(app2.galeria_aberta, ['PickerFoto'], '"Escolher da galeria" abre a galeria')
    c.eq(app2.g['perfilFoto'], '', 'cancelar a galeria: nada muda')
    # falha ao gravar o nome: avisa e NAO diz "salvo"
    app3 = open_app(fresh('t34_falha'))
    app3.touch('CanvasTopo')
    app3.comp('TinyDB1').drop_writes = True
    app3.type_text('TxtNome', 'Marina')
    app3.click('BtnSalvarPerfil')
    c.eq(app3.g['perfilNome'], '', 'falha de gravacao: nome nao e dado como salvo')
    c.eq(app3.text('LblPerfilMsg'), 'Não foi possível salvar. Tente de novo.', 'mensagem de falha')
    c.eq(app3.text('LblSaudacao'), '', 'sem saudacao enquanto nao salvar')
    app3.comp('TinyDB1').drop_writes = False
    app3.click('BtnSalvarPerfil')
    c.eq((app3.g['perfilNome'], app3.text('LblPerfilMsg')), ('Marina', 'Perfil salvo!'), 'tentar de novo salva')
    # perfil nao interfere nos lancamentos nem no historico (Voltar primeiro: no perfil o formulario esta escondido)
    app3.click('BtnPerfilVoltar')
    lancar(app3, 'Despesa', 'x', '1,00', 'Lazer', 'Pix')
    c.eq(len(app3.g['lancamentos']), 1, 'lancamento normal com perfil salvo')
    for a in (app, app2, app3):
        c.clean(a)


@test('T35', 'DADOS ANTIGOS: quem já tinha lançamentos (v1.2/v1.5) abre a nova versão no tema claro, sem perfil e com tudo no lugar')
def t35(c):
    T = paleta()
    db = fresh('t35')
    old = open_app(db, old=True)
    old.type_text('TxtDescricao', 'Antigo'); old.type_text('TxtValor', '12,34')
    old.select('SpnCategoria', old.comp('SpnCategoria').items[1]); old.select('SpnPagamento', old.comp('SpnPagamento').items[1])
    old.click('BtnDespesa')
    raw = db_raw(db)
    c.ok('tema' not in raw and 'perfil_nome' not in raw and 'perfil_foto' not in raw, 'o app antigo nao tem chaves de tema/perfil')
    app = open_app(db)
    c.eq(app.g['temaEscuro'], False, 'sem preferencia guardada: tema claro')
    c.eq(norm(app.comps['Screen1'].props['BackgroundColor']), T.aia(T.BG), 'fundo claro')
    c.eq((app.g['perfilNome'], app.g['perfilFoto'], app.text('LblSaudacao')), ('', '', ''), 'sem perfil')
    c.eq(len(app.g['lancamentos']), 1, 'lancamento antigo migrado')
    app.click('BtnNavGrafico')
    c.eq(len(linhas_categoria(app)), 1, 'grafico por categoria mostra o lancamento antigo')
    # chaves novas nao mexem nas antigas (a migracao dos lancamentos ja aconteceu ao abrir, como na v1.3+)
    raw = db_raw(db)
    c.eq(json.loads(raw['lancamentos']), app.g['lancamentos'], 'lancamentos migrados gravados')
    app.click('ImgTema')
    app.touch('CanvasTopo'); app.type_text('TxtNome', 'Marina'); app.click('BtnSalvarPerfil')
    raw2 = db_raw(db)
    c.eq(raw2.get('lancamentos'), raw.get('lancamentos'), 'gravar tema e perfil nao altera os lancamentos gravados')
    c.eq(sorted(k for k in raw2 if k not in raw), ['perfil_nome', 'tema'], 'so as chaves novas foram acrescentadas')
    # valores estranhos guardados nao quebram a abertura
    for tema in ('', 'ESCURO', 'xyz', 123):
        d = fresh('t35_%s' % str(tema).lower())
        a0 = open_app(d)
        a0.comp('TinyDB1').call('StoreValue', ['tema', tema])
        a0.comp('TinyDB1').call('StoreValue', ['perfil_nome', 42])
        a0.comp('TinyDB1').call('StoreValue', ['perfil_foto', ''])
        a1 = open_app(d)
        c.eq(a1.g['temaEscuro'], False, 'valor estranho de tema (%r) cai no claro' % (tema,))
        c.eq(a1.text('LblSaudacao'), 'Olá, 42', 'nome guardado como numero vira texto')
        c.eq(a1.runtime_errors, [], 'sem erro de execucao com preferencias estranhas (%r)' % (tema,))
    c.clean(app)


# ============================================================================= execucao
# ============================================================================= T36-T44 (v1.7)
# Testes da v1.7. Usam os utilitarios acima (open_app, fresh,
# ref_brl, ref_pct, norm, db_val, CATS, PAYS, paleta...). As referencias abaixo sao independentes dos blocos: calculam
# o esperado direto dos lancamentos, em Python.
AGORA17 = datetime.datetime(2026, 11, 12, 21, 0)
CHAVE_HOJE = 2026 * 12 + 10
MESES17 = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro',
           'novembro', 'dezembro']
CURTOS17 = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
DESCS17 = ['Mercado', 'Farmácia', 'Uber', 'Salário', 'Aluguel', 'Café', 'Pão de queijo', 'Ônibus', 'Saúde & bem-estar',
           'Conta de luz', 'Presente', 'Freela', 'Academia', 'Cinema']
MENOS = '−'
PONTO = '•'


def sem_acento17(t):
    """Referencia da busca: minusculas e sem os acentos do portugues."""
    t = t.lower()
    for a, b in zip('áàâãéêíóôõúüç', 'aaaaeeiooouuc'):
        t = t.replace(a, b)
    return t


def semear(db, regs, recorrentes=None, orcamentos=None, extra=None):
    """Grava o armazenamento (mesmo JSON do TinyDB) ANTES de abrir o app: como quem ja usa o app ha tempos."""
    shutil.rmtree(db, ignore_errors=True)
    os.makedirs(db, exist_ok=True)
    dados = {'lancamentos': json.dumps(regs, ensure_ascii=False)}
    if recorrentes is not None:
        dados['recorrentes'] = json.dumps(recorrentes, ensure_ascii=False)
    if orcamentos is not None:
        dados['orcamentos'] = json.dumps(orcamentos)
    dados.update(extra or {})
    json.dump(dados, open(os.path.join(db, 'Conto.json'), 'w', encoding='utf-8'), ensure_ascii=False)


def r_chave(data):
    """Referencia: 'dd/MM/aaaa HH:mm' -> ano*12 + mes - 1; fora do formato -> -1."""
    t = str(data)
    if len(t) < 10 or t[2] != '/' or t[5] != '/' or not t[3:5].isdigit() or not t[6:10].isdigit():
        return -1
    m = int(t[3:5])
    return int(t[6:10]) * 12 + m - 1 if 1 <= m <= 12 else -1


def r_ordem(data):
    t = str(data)
    try:
        return int(t[6:10] + t[3:5] + t[0:2] + t[11:13] + t[14:16])
    except ValueError:
        return 0


def r_nome_mes(k):
    return '%s de %d' % (MESES17[k % 12], k // 12)


def r_titulo_mes(k):
    return '%s de %d' % (MESES17[k % 12][0].upper() + MESES17[k % 12][1:], k // 12)


def r_sinal(v):
    return '+ ' + ref_brl(v) if v > 0 else (MENOS + ' ' + ref_brl(-v) if v < 0 else 'R$ 0,00')


def r_linha_hist(r):
    return (('+ ' if r[0] == 'Entrada' else MENOS + ' ') + ref_brl(r[2]),
            '%s  %s  %s\nCategoria: %s\nPagamento: %s' % (r[1], PONTO, r[3], r[4], r[5]))


def linhas_hist(app):
    return [(e['Text1'], e['Text2']) for e in app.comp('ListaHistorico').elements]


def r_resumo_hist(regs):
    if not regs:
        return ''
    e = sum(r[2] for r in regs if r[0] == 'Entrada')
    d = sum(r[2] for r in regs if r[0] != 'Entrada')
    return '%d %s  %s  + %s  %s  %s %s' % (len(regs), 'lançamento' if len(regs) == 1 else 'lançamentos', PONTO, ref_brl(e),
                                         PONTO, MENOS, ref_brl(d))


def gerar_regs(rnd, n, k_min, k_max, invalidos=0):
    regs = []
    for _ in range(n):
        k = rnd.randint(k_min, k_max)
        ano, mes = divmod(k, 12)
        dia = rnd.randint(1, 12 if k == CHAVE_HOJE else 28)
        data = '%02d/%02d/%04d %02d:%02d' % (dia, mes + 1, ano, rnd.randint(0, 20), rnd.randint(0, 59))
        regs.append([rnd.choice(['Entrada', 'Despesa', 'Despesa']), rnd.choice(DESCS17), rnd.randint(1, 900000), data,
                     rnd.choice(CATS), rnd.choice(PAYS)])
    for _ in range(invalidos):
        regs.append([rnd.choice(['Entrada', 'Despesa']), 'Registro antigo', rnd.randint(1, 5000),
                     rnd.choice(['', 'sem data', '99/99/9999 00:00', '2026-11-01 10:00']), rnd.choice(CATS), rnd.choice(PAYS)])
    regs.sort(key=lambda r: r_ordem(r[3]), reverse=True)
    return regs


def r_categorias(regs, pred, limites=None):
    """Referencia do cartao 'Gastos por categoria' para os lancamentos que passam em pred(chave do mes):
    [(nome, valor, texto do %, cor da barra(nome da ficha ou 'RED'), largura %, cor do texto)]"""
    tot = [0] * 8
    for r in regs:
        if r[0] != 'Entrada' and pred(r_chave(r[3])):
            tot[CATS.index(r[4]) if r[4] in CATS else 7] += r[2]
    lim = limites or [0] * 8
    cand = [i for i in range(8) if tot[i] > 0 or lim[i] > 0]
    ordem = sorted(cand, key=lambda i: (-tot[i], i))
    total = sum(tot)
    out = []
    for i in ordem:
        v, l = tot[i], lim[i]
        if l > 0:
            passou, alerta = v > l, v * 100 >= l * 80
            largura = 72 if v >= l else max(1, int(round(v * 72.0 / l)))
            texto = ('Passou %s do limite (%s)' % (ref_brl(v - l), ref_brl(l)) if passou else
                     '%d%% de %s  %s  sobram %s' % (int(round(v * 100.0 / l)), ref_brl(l), PONTO, ref_brl(l - v)))
            out.append((CATS[i], ref_brl(v), texto, 'BarraEstouro' if passou else ('BarraAlerta' if alerta else 'BarraOk'), largura,
                        'Perigo' if passou else ('Alerta' if alerta else 'Suave')))
        else:
            maior = tot[ordem[0]]
            largura = max(1, int(round(v * 72.0 / maior))) if maior > 0 else 1
            out.append((CATS[i], ref_brl(v), ref_pct(ref_p10(v, total - v)) + ' das despesas', 'RED', largura, 'Suave'))
    return out


def linhas_cat17(app):
    """v1.9: cada linha da lista do cartao "Gastos por categoria", de cima para baixo: nome, valor, texto de baixo,
    cor da barra do limite (None = sem barra), largura da barra (% da tela; None = sem barra), cor do texto,
    bolinha (imagem) e se a barra aparece."""
    out = []
    for i in range(1, 9):
        if app.comp('PnlCat%d' % i).visible:
            trilho = app.comp('HzCatTrilho%d' % i).visible
            barra = app.comp('LblCatBarra%d' % i).props
            out.append((app.text('LblCatNome%d' % i), app.text('LblCatValor%d' % i), app.text('LblCatPct%d' % i),
                        norm(barra.get('BackgroundColor')) if trilho else None,
                        -(int(barra.get('Width')) + 1000) if trilho else None,
                        norm(app.comp('LblCatPct%d' % i).props.get('TextColor')),
                        app.comp('ImgCat%d' % i).props.get('Picture'), trilho))
    return out


def cor_ficha(app, nome):
    """Cor que o app esta usando para a ficha (global cor<Nome>, trocada pelo tema)."""
    return 'RED' if nome == 'RED' else norm(app.g['cor' + nome])


def esperado_cat(app, ref):
    """r_categorias -> o que a linha deve mostrar no tema atual. v1.9: sem limite, so o texto (sem barra); com limite,
    a barra do limite. A bolinha tem a cor da fatia da categoria."""
    out = []
    for n, v, t, barra, w, ct in ref:
        com_barra = barra != 'RED'
        out.append((n, v, t, cor_ficha(app, barra) if com_barra else None, w if com_barra else None, cor_ficha(app, ct),
                    ponto_ref(app, n), com_barra))
    return out


def scm_nos():
    t = open(NEW_SCM, encoding='utf-8').read()
    d = json.loads(t[t.index('{'): t.rindex('}') + 1])
    nos = {}

    def idx(n):
        nos[n['$Name']] = n
        for ch in n.get('$Components', []):
            idx(ch)
    idx(d['Properties'])
    return nos


def tocar_lista(app, lista, i):
    assert app.shown(lista), '%s nao esta visivel' % lista
    assert 1 <= i <= len(app.comp(lista).elements), 'linha %d nao existe em %s' % (i, lista)
    app.comps[lista].user_pick(i)


def digitar(app, nome, texto):
    assert app.shown(nome), '%s nao esta visivel: a pessoa nao consegue digitar nele' % nome
    app.type_text(nome, texto)


def ir_para_mes(app, k):
    """Como a pessoa: modo Mes e setas ate o mes k. Se a seta parar antes de chegar (defeito no app), o teste FALHA
    em vez de ficar tocando para sempre (antes era um laco sem limite: um defeito assim travava o teste)."""
    if app.g['periodoModo'] != 'mes':
        app.click('BtnModoMes')
    for _ in range(1000):
        antes = app.g['periodoChave']
        if antes == k:
            return
        app.click('BtnPerAnt' if antes > k else 'BtnPerProx')
        if app.g['periodoChave'] == antes:
            raise AssertionError('as setas param em %r e nao chegam ao mes %r' % (antes, k))
    raise AssertionError('as setas nao chegam ao mes %r' % (k,))


def lancar17(app, tipo, desc, valor, cat, pag, repetir=False):
    if not app.shown('PnlLancar'):
        if app.shown('BtnPerfilVoltar'):
            app.click('BtnPerfilVoltar')
        if not app.shown('PnlLancar'):
            app.click('BtnNavLancar')
    digitar(app, 'TxtDescricao', desc)
    digitar(app, 'TxtValor', valor)
    app.click('BtnCategoria')
    app.pick_option(cat)
    app.click('BtnPagamento')
    app.pick_option(pag)
    if repetir:
        app.click('BtnRepetir')
    app.click('BtnEntrada' if tipo == 'Entrada' else 'BtnDespesa')
    return app.text('LblAviso')


@test('T36', 'PERÍODO: Mês / Ano / Tudo com setas no Histórico e no Gráfico; o topo mostra saldo total e o mês atual')
def t36(c):
    rnd = random.Random(36)
    db = os.path.join(WORK, 'db_t36')
    regs = gerar_regs(rnd, 170, CHAVE_HOJE - 27, CHAVE_HOJE, invalidos=4)
    semear(db, regs)
    app = open_app(db, now=AGORA17)
    validos = [r_chave(r[3]) for r in regs if r_chave(r[3]) >= 0]
    kmin = min(validos)
    # ---- topo: saldo de tudo; quadradinhos do mes atual
    saldo = sum(r[2] if r[0] == 'Entrada' else -r[2] for r in regs)
    c.eq(app.text('LblSaldo'), ref_brl(saldo), 'saldo do topo = todos os lancamentos (inclusive os sem data valida)')
    e_mes = sum(r[2] for r in regs if r[0] == 'Entrada' and r_chave(r[3]) == CHAVE_HOJE)
    d_mes = sum(r[2] for r in regs if r[0] != 'Entrada' and r_chave(r[3]) == CHAVE_HOJE)
    c.eq((app.text('LblEntradas'), app.text('LblDespesas')), (ref_brl(e_mes), ref_brl(d_mes)), 'quadradinhos = novembro/2026')
    c.eq((app.text('LblCapEntradas'), app.text('LblCapDespesas')), ('Entradas em nov', 'Despesas em nov'), 'rotulos dizem o mes')
    # ---- historico: abre no mes atual; percorre todos os meses com a seta
    c.eq(app.g['periodoModo'], 'mes', 'abre no modo Mes')
    app.click('BtnNavHistorico')
    c.ok(app.shown('PnlPeriodo') and app.shown('BtnModoMes'), 'barra de periodo aparece no Historico')
    k = CHAVE_HOJE
    while True:
        do_mes = [r for r in regs if r_chave(r[3]) == k]
        c.eq(linhas_hist(app), [r_linha_hist(r) for r in do_mes], 'historico de %s: linhas e ordem' % r_nome_mes(k))
        c.eq(app.text('LblPeriodo'), r_titulo_mes(k), 'titulo do periodo (%d)' % k)
        c.eq(app.text('LblResumoHist'), r_resumo_hist(do_mes), 'resumo do historico de %s' % r_nome_mes(k))
        c.eq(app.comp('LblVazio').visible, not do_mes, 'frase de vazio so sem lancamento (%s)' % r_nome_mes(k))
        if not do_mes:
            c.eq(app.text('LblVazio'), 'Nenhum lançamento em %s.' % r_nome_mes(k), 'frase de mes vazio')
        c.eq(seta(app, 'BtnPerAnt'), '‹' if k > kmin else '', 'seta para tras (%s)' % r_nome_mes(k))
        c.eq(seta(app, 'BtnPerProx'), '›' if k < CHAVE_HOJE else '', 'seta para frente (%s)' % r_nome_mes(k))
        if k == kmin:
            break
        app.click('BtnPerAnt')
        k -= 1
    app.click('BtnPerAnt')
    c.eq(app.g['periodoChave'], kmin, 'no mes mais antigo a seta para tras nao anda')
    for _ in range(CHAVE_HOJE - kmin):
        app.click('BtnPerProx')
    app.click('BtnPerProx')
    c.eq(app.g['periodoChave'], CHAVE_HOJE, 'a seta para frente para no mes atual')
    # ---- grafico: legenda, saldo do periodo e categorias em alguns meses
    app.click('BtnNavGrafico')
    c.ok(app.shown('PnlPeriodo'), 'barra de periodo aparece no Grafico')
    for k in sorted(set([CHAVE_HOJE, kmin, CHAVE_HOJE - 12] + rnd.sample(range(kmin, CHAVE_HOJE), 6)), reverse=True):
        ir_para_mes(app, k)
        sel = [r for r in regs if r_chave(r[3]) == k]
        e = sum(r[2] for r in sel if r[0] == 'Entrada')
        d = sum(r[2] for r in sel if r[0] != 'Entrada')
        c.eq((app.text('LblLegEntValor'), app.text('LblLegDespValor'), app.text('LblLegSaldoNome'), app.text('LblLegSaldoValor')),
             (ref_brl(e), ref_brl(d), 'Saldo do mês', r_sinal(e - d)), 'legenda de %s' % r_nome_mes(k))
        c.eq(norm(app.comp('LblLegSaldoValor').props['TextColor']),
             cor_ficha(app, 'Bom' if e > d else ('Perigo' if e < d else 'Texto')), 'cor do saldo de %s' % r_nome_mes(k))
        c.eq(app.text('LblSubGraf'), 'Total de gastos em %s' % r_nome_mes(k), 'subtitulo do grafico')
        c.eq(linhas_cat17(app), esperado_cat(app, r_categorias(regs, lambda x, k=k: x == k)), 'categorias de %s' % r_nome_mes(k))
        c.ok(arcos_iguais(rosca_vista(app)[0], r_rosca(r_totais_cat(regs, lambda x, k=k: x == k), bool(app.g['temaEscuro']))),
             'rosca de %s igual a referencia' % r_nome_mes(k))
        c.eq((app.text('LblEntradas'), app.text('LblDespesas')), (ref_brl(e_mes), ref_brl(d_mes)),
             'olhando %s, os quadradinhos do topo continuam sendo de novembro/2026' % r_nome_mes(k))
        c.ok('PnlResumo' not in app.comps, '"Ultimos lancamentos" saiu do Grafico (pedido do usuario: esta no Historico)')
    # ---- modo Ano: cada ano, do atual ao mais antigo (a partir do mes atual; de outro mes o Ano mostra o ano DAQUELE mes)
    ir_para_mes(app, CHAVE_HOJE)
    app.click('BtnModoAno')
    c.eq((app.g['periodoModo'], app.g['periodoChave']), ('ano', 2026), 'Ano a partir do mes atual = 2026')
    for ano in range(2026, kmin // 12 - 1, -1):
        sel = [r for r in regs if r_chave(r[3]) >= 0 and r_chave(r[3]) // 12 == ano]
        e = sum(r[2] for r in sel if r[0] == 'Entrada')
        d = sum(r[2] for r in sel if r[0] != 'Entrada')
        c.eq((app.text('LblPeriodo'), app.text('LblLegSaldoNome'), app.text('LblLegEntValor'), app.text('LblLegDespValor')),
             ('Ano de %d' % ano, 'Saldo do ano', ref_brl(e), ref_brl(d)), 'grafico do ano %d' % ano)
        c.eq(linhas_cat17(app), esperado_cat(app, r_categorias(regs, lambda x, a=ano: x >= 0 and x // 12 == a)), 'categorias de %d' % ano)
        c.ok(arcos_iguais(rosca_vista(app)[0], r_rosca(r_totais_cat(regs, lambda x, a=ano: x >= 0 and x // 12 == a), False)),
             'rosca de %d igual a referencia' % ano)
        c.eq(seta(app, 'BtnPerAnt'), '‹' if ano > kmin // 12 else '', 'seta do ano para tras (%d)' % ano)
        app.click('BtnPerAnt')
    c.eq(app.g['periodoChave'], kmin // 12, 'o ano nao passa do mais antigo')
    app.click('BtnNavHistorico')
    ano = kmin // 12
    sel = [r for r in regs if r_chave(r[3]) >= 0 and r_chave(r[3]) // 12 == ano]
    c.eq(linhas_hist(app), [r_linha_hist(r) for r in sel], 'historico do ano %d' % ano)
    # ---- Tudo: todos (inclusive sem data valida), sem setas
    app.click('BtnModoTudo')
    c.eq(linhas_hist(app), [r_linha_hist(r) for r in regs], 'Tudo: todos os lancamentos, na ordem da lista')
    c.eq((app.text('LblPeriodo'), seta(app, 'BtnPerAnt'), seta(app, 'BtnPerProx')), ('Todos os lançamentos', '', ''), 'Tudo: sem setas')
    app.click('BtnPerAnt')
    c.eq((app.g['periodoModo'], app.g['periodoChave']), ('tudo', 0), 'setas nao fazem nada em Tudo')
    app.click('BtnNavGrafico')
    e = sum(r[2] for r in regs if r[0] == 'Entrada')
    d = sum(r[2] for r in regs if r[0] != 'Entrada')
    c.eq((app.text('LblLegSaldoNome'), app.text('LblLegSaldoValor')), ('Saldo total', r_sinal(e - d)), 'Tudo: saldo total')
    c.eq(app.text('LblSubGraf'), 'Total de gastos em todo o período', 'subtitulo em Tudo')
    c.ok(arcos_iguais(rosca_vista(app)[0], r_rosca(r_totais_cat(regs, lambda x: True), False)), 'rosca de Tudo igual a referencia')
    c.eq(linhas_cat17(app), esperado_cat(app, r_categorias(regs, lambda x: True)), 'categorias em Tudo')
    sem_data = [r for r in regs if r_chave(r[3]) < 0]
    c.ok(len(sem_data) == 4, 'cenario tem 4 lancamentos sem data valida (so aparecem em Tudo)')
    # ---- troca de modo mantem o contexto; tocar de novo no modo volta para hoje
    app.click('BtnModoMes')
    c.eq(app.g['periodoChave'], CHAVE_HOJE, 'de Tudo para Mes: mes atual')
    ir_para_mes(app, CHAVE_HOJE - 20)                   # marco/2025
    app.click('BtnModoAno')
    c.eq(app.g['periodoChave'], (CHAVE_HOJE - 20) // 12, 'de marco/2025 para Ano: 2025')
    app.click('BtnModoMes')
    c.eq(app.text('LblPeriodo'), 'Dezembro de 2025', 'de Ano 2025 para Mes: dezembro de 2025')
    app.click('BtnModoMes')
    c.eq(app.text('LblPeriodo'), 'Novembro de 2026', 'tocar em Mes de novo: volta para o mes atual')
    app.click('BtnModoAno')
    app.click('BtnModoMes')
    c.eq(app.g['periodoChave'], CHAVE_HOJE, 'Ano atual para Mes: mes atual')
    # pilulas do modo
    for modo, btn in (('mes', 'BtnModoMes'), ('ano', 'BtnModoAno'), ('tudo', 'BtnModoTudo')):
        app.click(btn)
        ativos = [b for b in ('BtnModoMes', 'BtnModoAno', 'BtnModoTudo') if app.comp(b).props.get('Image') == 'aba_ativa.png']
        c.eq(ativos, [btn], 'so a pilula %s fica destacada' % modo)
    # ---- a barra de periodo so aparece no Historico e no Grafico
    for aba, vis in (('BtnNavLancar', False), ('BtnNavHistorico', True), ('BtnNavGrafico', True), ('BtnNavEvolucao', False)):
        app.click(aba)
        c.eq(app.shown('PnlPeriodo'), vis, 'barra de periodo na aba %s: %s' % (aba, vis))
    # ---- periodo fora do intervalo depois de apagar os mais antigos: a seta leva de volta (nao trava)
    db2 = os.path.join(WORK, 'db_t36b')
    semear(db2, [['Despesa', 'Novo', 1000, '05/11/2026 10:00', 'Lazer', 'Pix'],
                 ['Despesa', 'Velho', 2000, '10/01/2026 10:00', 'Lazer', 'Pix']])
    a2 = open_app(db2, now=AGORA17)
    a2.click('BtnNavHistorico')
    ir_para_mes(a2, 2026 * 12)
    c.eq(a2.text('LblPeriodo'), 'Janeiro de 2026', 'janeiro/2026 tem o registro antigo')
    tocar_lista(a2, 'ListaHistorico', 1)
    a2.answer_dialog('Excluir')
    c.eq((a2.g['chaveMin'], seta(a2, 'BtnPerAnt'), seta(a2, 'BtnPerProx')), (CHAVE_HOJE, '', '›'),
         'apagado o unico de janeiro: nada antes; seta para frente continua')
    a2.click('BtnPerProx')
    c.eq(a2.text('LblPeriodo'), 'Fevereiro de 2026', 'a seta para frente anda mesmo estando antes do mais antigo')
    c.eq(app.runtime_errors + a2.runtime_errors, [], 'nenhum erro de execucao')


@test('T37', 'BUSCA no histórico: descrição, categoria ou pagamento, sem diferença de maiúscula/acento, dentro do período')
def t37(c):
    rnd = random.Random(37)
    db = os.path.join(WORK, 'db_t37')
    regs = gerar_regs(rnd, 120, CHAVE_HOJE - 14, CHAVE_HOJE)
    regs.insert(0, ['Despesa', 'Café <b>da manhã</b> & pão', 1290, '12/11/2026 08:00', 'Alimentação', 'Dinheiro'])
    semear(db, regs)
    app = open_app(db, now=AGORA17)
    app.click('BtnNavHistorico')
    c.eq(app.comp('BtnLimparBusca').visible, False, 'sem busca: botao de limpar escondido')

    def ref(termo, pred):
        q = sem_acento17(termo.strip())
        return [r for r in regs if pred(r_chave(r[3])) and (not q or q in sem_acento17('%s %s %s' % (r[1], r[4], r[5])))]
    termos = ['mercado', 'MERCADO', 'farmacia', 'FARMÁCIA', 'saude', 'Saúde', 'pix', 'cartão de cr', 'CARTAO', 'onibus',
              'transferência', 'educacao', 'lazer', '  uber  ', 'xyzw', 'ã', 'r', '&', '<b>']
    for modo in ('mes', 'ano', 'tudo'):
        app.click({'mes': 'BtnModoMes', 'ano': 'BtnModoAno', 'tudo': 'BtnModoTudo'}[modo])
        pred = {'mes': lambda k: k == CHAVE_HOJE, 'ano': lambda k: k >= 0 and k // 12 == 2026, 'tudo': lambda k: True}[modo]
        desc = {'mes': 'novembro de 2026', 'ano': '2026', 'tudo': 'todo o período'}[modo]
        for termo in termos:
            digitar(app, 'TxtBusca', termo)
            esperado = ref(termo, pred)
            c.eq(linhas_hist(app), [r_linha_hist(r) for r in esperado], 'busca %r em %s' % (termo, modo))
            c.eq(app.text('LblResumoHist'), r_resumo_hist(esperado), 'resumo da busca %r (%s)' % (termo, modo))
            c.eq(app.comp('BtnLimparBusca').visible, True, 'com texto na busca o botao de limpar aparece')
            if not esperado:
                c.eq(app.text('LblVazio'), 'Nada encontrado para “%s” em %s.' % (termo.strip(), desc), 'frase de busca sem resultado')
    # tocar numa linha filtrada abre O lancamento certo (posicao na lista completa)
    app.click('BtnModoTudo')
    digitar(app, 'TxtBusca', 'farmacia')
    alvo = ref('farmacia', lambda k: True)
    c.ok(len(alvo) >= 3, 'ha varias farmacias para escolher (%d)' % len(alvo))
    tocar_lista(app, 'ListaHistorico', 3)
    r = alvo[2]
    p = app.comp('Notifier1').pending
    c.eq(p['texto'], '%s\n%s %s %s %s' % (r[1], '+' if r[0] == 'Entrada' else MENOS, ref_brl(r[2]), PONTO, r[3]),
         'dialogo mostra o 3o resultado da busca (nao o 3o da lista toda)')
    app.answer_dialog('Excluir')
    c.ok(r not in app.g['lancamentos'] and len(app.g['lancamentos']) == len(regs) - 1, 'Excluir apagou exatamente aquele')
    c.eq(db_lancamentos(db), app.g['lancamentos'], 'exclusao gravada')
    c.eq(linhas_hist(app), [r_linha_hist(x) for x in alvo if x is not r], 'a busca continua aplicada depois de excluir')
    # texto com < & > aparece literal no dialogo (a mensagem do dialogo e HTML)
    digitar(app, 'TxtBusca', '<b>')
    tocar_lista(app, 'ListaHistorico', 1)
    p = app.comp('Notifier1').pending
    c.eq(p['texto'].split('\n')[0], 'Café <b>da manhã</b> & pão', 'descricao com < & > aparece igualzinha no dialogo')
    c.ok('&lt;b&gt;' in p['message'] and '&amp;' in p['message'], 'na mensagem HTML os caracteres vao escapados')
    app.answer_dialog('Cancelar')
    # limpar
    app.click('BtnLimparBusca')
    c.eq((app.text('TxtBusca'), app.comp('BtnLimparBusca').visible), ('', False), 'limpar: campo vazio e botao some')
    c.eq(len(linhas_hist(app)), len(app.g['lancamentos']), 'sem busca: todos de novo (Tudo)')
    c.eq(app.runtime_errors, [], 'nenhum erro de execucao')


@test('T38', 'EDITAR lançamento: muda tipo, descrição, valor, categoria e pagamento sem mudar a data; cancelar; falhas')
def t38(c):
    db = os.path.join(WORK, 'db_t38')
    regs = [['Despesa', 'Mercado', 25090, '12/11/2026 08:00', 'Alimentação', 'Cartão de crédito'],
            ['Entrada', 'Sem descrição', 150000, '10/11/2026 09:00', 'Outros', 'Pix'],
            ['Despesa', 'Conta antiga', 9900, '15/09/2026 10:00', 'Não informado', 'Não informado'],
            ['Despesa', 'Uber', 3640, '01/09/2026 23:00', 'Transporte', 'Pix']]
    semear(db, regs)
    app = open_app(db, now=AGORA17)
    app.click('BtnNavHistorico')
    app.click('BtnModoTudo')
    tocar_lista(app, 'ListaHistorico', 1)
    p = app.comp('Notifier1').pending
    c.eq((p['title'], p['buttons'], p['cancelable']), ('O que você quer fazer?', ['Editar', 'Excluir', 'Cancelar'], True), 'dialogo')
    app.answer_dialog('Editar')
    c.eq(app.g['abaAtual'], 1, 'Editar leva para a aba Lancar')
    c.eq((app.text('LblTituloLancar'), app.text('LblSubLancar')),
         ('Editar lançamento', 'Lançado em 12/11/2026 08:00. Mude o que quiser e toque em Salvar.'), 'titulo e subtitulo de edicao')
    c.eq((app.text('TxtDescricao'), app.text('TxtValor'), app.text('BtnCategoria'), app.text('BtnPagamento')),
         ('Mercado', '250,90', 'Alimentação', 'Cartão de crédito'), 'formulario preenchido com o lancamento')
    c.eq((app.comp('ImgCatIcone').props['Picture'], app.comp('ImgPagIcone').props['Picture']),
         ('ic_cat_alimentacao.png', 'ic_pag_credito.png'), 'icones da categoria e do pagamento')
    c.eq((app.text('BtnEntrada'), app.text('BtnDespesa'), app.comp('BtnCancelarEdicao').visible, app.comp('HzRepetir').visible),
         ('Salvar entrada', 'Salvar despesa', True, False), 'botoes de salvar, cancelar visivel, "repetir" escondido')
    # erro de validacao continua na edicao e nao muda nada
    digitar(app, 'TxtValor', '')
    app.click('BtnDespesa')
    c.eq((app.comp('LblErroValor').visible, app.g['editIndice'], app.g['lancamentos'][0]), (True, 1, regs[0]), 'valor vazio: erro, nada muda')
    # salvar como ENTRADA com outros valores
    digitar(app, 'TxtDescricao', 'Mercado (reembolsado)')
    digitar(app, 'TxtValor', '1.250,99')
    app.click('BtnCategoria')
    app.pick_option('Outros')
    app.click('BtnPagamento')
    app.pick_option('Pix')
    app.click('BtnEntrada')
    novo = ['Entrada', 'Mercado (reembolsado)', 125099, '12/11/2026 08:00', 'Outros', 'Pix']
    c.eq(app.g['lancamentos'][0], novo, 'lancamento trocado no mesmo lugar, com a MESMA data')
    c.eq(len(app.g['lancamentos']), 4, 'nenhum lancamento novo')
    c.eq(db_lancamentos(db), app.g['lancamentos'], 'gravado')
    c.eq(app.text('LblAviso'), 'Lançamento atualizado!', 'aviso de sucesso')
    c.eq((app.text('LblTituloLancar'), app.text('BtnEntrada'), app.comp('BtnCancelarEdicao').visible, app.text('TxtDescricao')),
         ('Novo lançamento', '+ Entrada', False, ''), 'formulario volta ao normal e limpo')
    c.eq(app.text('LblEntradas'), ref_brl(150000 + 125099), 'quadradinho de entradas do mes atualizado')
    # "Sem descricao" vira campo vazio; salvar vazio mantem "Sem descricao"
    app.click('BtnNavHistorico')
    tocar_lista(app, 'ListaHistorico', 2)
    app.answer_dialog('Editar')
    c.eq(app.text('TxtDescricao'), '', '"Sem descrição" aparece como campo vazio')
    app.click('BtnEntrada')
    c.eq(app.g['lancamentos'][1], regs[1], 'salvar sem mudar: igual (Sem descrição)')
    # categoria "Nao informado" (dado migrado) e mantida
    app.click('BtnNavHistorico')
    tocar_lista(app, 'ListaHistorico', 3)
    app.answer_dialog('Editar')
    c.eq((app.text('BtnCategoria'), app.comp('ImgCatIcone').props['Picture']), ('Não informado', 'ic_vazio.png'), 'migrado')
    digitar(app, 'TxtValor', '100,00')
    app.click('BtnDespesa')
    c.eq(app.g['lancamentos'][2], ['Despesa', 'Conta antiga', 10000, '15/09/2026 10:00', 'Não informado', 'Não informado'],
         'editar migrado mantem categoria/pagamento antigos')
    # cancelar
    app.click('BtnNavHistorico')
    tocar_lista(app, 'ListaHistorico', 4)
    app.answer_dialog('Editar')
    digitar(app, 'TxtValor', '999,99')
    app.click('BtnCancelarEdicao')
    c.eq((app.g['editIndice'], app.text('TxtValor'), app.text('LblTituloLancar'), app.g['lancamentos'][3]),
         (0, '', 'Novo lançamento', regs[3]), 'cancelar: nada muda e o formulario limpa')
    # falha de gravacao durante a edicao: desfaz e continua editando
    antes = [list(x) for x in app.g['lancamentos']]
    app.click('BtnNavHistorico')
    tocar_lista(app, 'ListaHistorico', 4)
    app.answer_dialog('Editar')
    digitar(app, 'TxtValor', '77,00')
    app.comp('TinyDB1').drop_writes = True
    app.click('BtnDespesa')
    app.comp('TinyDB1').drop_writes = False
    c.eq(app.g['lancamentos'], antes, 'gravacao falhou: lista volta ao que era')
    c.eq(db_lancamentos(db), antes, 'armazenamento intacto')
    c.eq((app.text('LblAviso'), app.g['avisoOk']), ('Não foi possível gravar. A alteração não foi salva.', False), 'aviso vermelho')
    c.eq((app.g['editIndice'], app.text('LblTituloLancar')), (4, 'Editar lançamento'), 'continua editando para tentar de novo')
    app.click('BtnDespesa')
    c.eq(app.g['lancamentos'][3][2], 7700, 'na segunda tentativa grava')
    # excluir enquanto edita
    app.click('BtnNavHistorico')
    tocar_lista(app, 'ListaHistorico', 3)
    app.answer_dialog('Editar')                                     # editando o 3o (Conta antiga)
    app.click('BtnNavHistorico')
    tocar_lista(app, 'ListaHistorico', 1)
    app.answer_dialog('Excluir')                                    # apaga um de cima
    c.eq((app.g['editIndice'], app.text('LblSubLancar')), (2, 'Lançado em 15/09/2026 10:00. Mude o que quiser e toque em Salvar.'),
         'apagou um de cima: a edicao continua no MESMO lancamento (posicao anda 1)')
    tocar_lista(app, 'ListaHistorico', 3)
    app.answer_dialog('Excluir')                                    # apaga um de baixo
    c.eq(app.g['editIndice'], 2, 'apagou um de baixo: nada muda')
    tocar_lista(app, 'ListaHistorico', 2)
    app.answer_dialog('Excluir')                                    # apaga o proprio
    c.eq((app.g['editIndice'], app.text('LblTituloLancar'), app.comp('BtnCancelarEdicao').visible), (0, 'Novo lançamento', False),
         'apagou o que estava editando: sai da edicao')
    tocar_lista(app, 'ListaHistorico', 1)
    app.answer_dialog('Editar')
    app.click('BtnNavHistorico')
    app.click('BtnLimpar')
    app.answer_dialog('Apagar tudo')
    c.eq((app.g['editIndice'], app.g['lancamentos']), (0, []), 'Apagar tudo durante a edicao: sai da edicao')
    c.eq(app.runtime_errors, [], 'nenhum erro de execucao')


@test('T39', 'REPETIR TODO MÊS: lançados sozinhos no dia certo (31 vira o último dia), sem duplicar, parar de repetir, falhas')
def t39(c):
    db = os.path.join(WORK, 'db_t39')
    shutil.rmtree(db, ignore_errors=True)
    app = open_app(db, now=datetime.datetime(2026, 1, 31, 9, 0))
    c.eq((app.comp('HzRepetir').visible, app.comp('ImgRepetir').props['Picture']), (True, 'ic_check_off.png'), 'caixa desmarcada')
    app.click('ImgRepetir')
    c.eq((app.g['repetirSel'], app.comp('ImgRepetir').props['Picture']), (True, 'ic_check_on.png'), 'toque na caixa marca')
    app.click('BtnRepetir')
    c.eq(app.g['repetirSel'], False, 'toque no texto desmarca')
    aviso = lancar17(app, 'Despesa', 'Aluguel', '1.200,00', 'Moradia', 'Pix', repetir=True)
    c.eq(aviso, 'Despesa registrada! Vai se repetir todo dia 31.', 'aviso diz o dia')
    c.eq(app.g['recorrentes'], [['Despesa', 'Aluguel', 120000, 'Moradia', 'Pix', 31, 2026 * 12]], 'repeticao guardada (dia 31, ja lancado em jan)')
    c.eq(db_val(db, 'recorrentes'), app.g['recorrentes'], 'repeticao gravada')
    c.eq((app.g['repetirSel'], app.comp('ImgRepetir').props['Picture']), (False, 'ic_check_off.png'), 'caixa desmarca depois de salvar')
    lancar17(app, 'Entrada', 'Salário', '5.000,00', 'Outros', 'Transferência bancária', repetir=True)
    c.eq(len(app.g['recorrentes']), 2, 'duas repeticoes')
    c.eq(app.comp('ClockAviso').props['TimerInterval'], 5000, 'frase longa: o aviso fica 5 s')
    # perfil lista as repeticoes
    app.touch('CanvasTopo')
    els = app.comp('ListaRecorrentes').elements
    c.eq([(e['Text1'], e['Text2']) for e in els],
         [('Aluguel  %s  %s R$ 1.200,00' % (PONTO, MENOS), 'Todo dia 31  %s  Moradia  %s  Pix' % (PONTO, PONTO)),
          ('Salário  %s  + R$ 5.000,00' % PONTO, 'Todo dia 31  %s  Outros  %s  Transferência bancária' % (PONTO, PONTO))],
         'lista do perfil')
    c.eq((app.comp('ListaRecorrentes').props['Height'], app.comp('LblSemRec').visible), (140, False), 'altura = 2 linhas')

    def reabrir(quando):
        a = open_app(db, now=quando)
        return a
    # fevereiro: dia 31 vira 28; antes do dia nada; no dia lanca 1 vez so
    a = reabrir(datetime.datetime(2026, 2, 27, 10, 0))
    c.eq(len(a.g['lancamentos']), 2, '27/02: ainda nao chegou o "dia 31" de fevereiro (28)')
    a = reabrir(datetime.datetime(2026, 2, 28, 7, 0))
    c.eq(sorted(r[3] for r in a.g['lancamentos'][:2]), ['28/02/2026 08:00', '28/02/2026 08:00'], '28/02: lancados no ultimo dia do mes')
    c.eq(a.text('LblAviso'), '2 lançamentos que se repetem foram adicionados.', 'aviso de quantos foram adicionados')
    c.eq(a.g['recorrentes'][0][6], 2026 * 12 + 1, 'ultima vez = fevereiro')
    a = reabrir(datetime.datetime(2026, 2, 28, 22, 0))
    c.eq(len(a.g['lancamentos']), 4, 'reabrir no mesmo dia nao duplica')
    # abril (30 dias) e catch-up de varios meses; ordem por data
    a = reabrir(datetime.datetime(2026, 5, 2, 10, 0))
    datas = [r[3] for r in a.g['lancamentos']]
    c.eq(sorted(set(d for d in datas if d.endswith('08:00'))), ['28/02/2026 08:00', '30/04/2026 08:00', '31/03/2026 08:00'],
         'marco (31) e abril (30) lancados; maio (31) ainda nao')
    c.eq(datas, sorted(datas, key=r_ordem, reverse=True), 'a lista continua do mais novo para o mais antigo')
    c.eq(len(a.g['lancamentos']), 8, '2 por mes de fev a abr + os 2 originais')
    # ano bissexto
    db2 = os.path.join(WORK, 'db_t39b')
    semear(db2, [], recorrentes=[['Despesa', 'Academia', 9990, 'Saúde', 'Pix', 30, 2028 * 12]])
    a2 = open_app(db2, now=datetime.datetime(2028, 2, 29, 12, 0))
    c.eq([r[3] for r in a2.g['lancamentos']], ['29/02/2028 08:00'], '2028 e bissexto: dia 30 vira 29/02')
    # limite de 24 meses de uma vez
    db3 = os.path.join(WORK, 'db_t39c')
    semear(db3, [], recorrentes=[['Entrada', 'Mesada', 10000, 'Outros', 'Pix', 1, 2020 * 12]])
    a3 = open_app(db3, now=AGORA17)
    c.eq(len(a3.g['lancamentos']), 25, 'muito tempo sem abrir: no maximo 24 meses para tras + o mes atual')
    c.eq(a3.g['lancamentos'][-1][3], '01/11/2024 08:00', 'o mais antigo gerado e de 24 meses atras')
    # parar de repetir
    a = reabrir(datetime.datetime(2026, 5, 2, 11, 0))
    a.touch('CanvasTopo')
    tocar_lista(a, 'ListaRecorrentes', 1)
    p = a.comp('Notifier1').pending
    c.eq((p['texto'], p['buttons'], p['cancelable']),
         ('Parar de repetir “Aluguel”? O que já foi lançado continua no histórico.', ['Parar de repetir', 'Manter'], False), 'dialogo')
    a.answer_dialog('Manter')
    c.eq(len(a.g['recorrentes']), 2, 'Manter: nada muda')
    tocar_lista(a, 'ListaRecorrentes', 1)
    a.answer_dialog('Parar de repetir')
    c.eq([r[1] for r in a.g['recorrentes']], ['Salário'], 'Aluguel parou de repetir')
    c.eq(db_val(db, 'recorrentes'), a.g['recorrentes'], 'gravado')
    c.eq(sum(1 for r in a.g['lancamentos'] if r[1] == 'Aluguel'), 4, 'os alugueis ja lancados continuam')
    a = reabrir(datetime.datetime(2026, 6, 30, 10, 0))
    c.eq([r[1] for r in a.g['lancamentos'][:2]], ['Salário', 'Salário'], 'maio e junho: so o salario')
    # falha de gravacao ao gerar: nada muda, aviso, e na proxima abertura gera certinho
    antes_l, antes_r = db_lancamentos(db), db_val(db, 'recorrentes')
    a = App(NEW_BKY, NEW_SCM, db, now=datetime.datetime(2026, 7, 31, 10, 0), run_initialize=False)
    ALL_APPS.append((_SoErros(a), False))
    a.comp('TinyDB1').drop_writes = True
    a.fire('Screen1', 'Initialize')
    a.comp('TinyDB1').drop_writes = False
    c.eq((db_lancamentos(db), db_val(db, 'recorrentes')), (antes_l, antes_r), 'falha: armazenamento intacto')
    c.eq(a.g['lancamentos'], antes_l, 'falha: na memoria tambem volta ao que era')
    c.ok(a.message_dialogs and 'não foi possível adicionar os lançamentos que se repetem' in a.message_dialogs[-1]['message'],
         'aviso de erro (nada de falso sucesso)')
    a = reabrir(datetime.datetime(2026, 7, 31, 11, 0))
    c.eq(sum(1 for r in a.g['lancamentos'] if r[3] == '31/07/2026 08:00'), 1, 'na proxima abertura: julho lancado uma vez')
    # falha ao guardar a repeticao ao registrar: o lancamento fica, a repeticao nao, aviso honesto (vermelho)
    db4 = os.path.join(WORK, 'db_t39d')
    shutil.rmtree(db4, ignore_errors=True)
    a4 = open_app(db4, now=AGORA17)
    orig = a4.comps['TinyDB1'].call

    def falha_so_recorrentes(method, args, orig=orig, comp=a4.comps['TinyDB1']):
        if method == 'StoreValue' and coerce_to_string(args[0]) == 'recorrentes':
            comp.drop_writes = True
            try:
                return orig(method, args)
            finally:
                comp.drop_writes = False
        return orig(method, args)
    a4.comps['TinyDB1'].call = falha_so_recorrentes
    aviso = lancar17(a4, 'Despesa', 'Internet', '99,90', 'Moradia', 'Pix', repetir=True)
    c.eq(aviso, 'Despesa registrada! Mas não foi possível guardar a repetição mensal.', 'aviso honesto')
    c.eq((a4.g['avisoOk'], a4.g['recorrentes'], len(db_lancamentos(db4))), (False, [], 1), 'faixa vermelha; lancamento salvo; sem repeticao')
    # repeticoes estranhas no armazenamento sao ignoradas (o app abre normal)
    db5 = os.path.join(WORK, 'db_t39e')
    semear(db5, [], extra={'recorrentes': json.dumps([['Despesa', 'ok', 100, 'Lazer', 'Pix', 5, CHAVE_HOJE], 'lixo', [1, 2],
                                                      ['Despesa', 'sem numero', 'abc', 'Lazer', 'Pix', 5, CHAVE_HOJE],
                                                      ['Despesa', 'quebrado', 2.5, 'Lazer', 'Pix', 5, CHAVE_HOJE],
                                                      ['Despesa', 'dia 0', 100, 'Lazer', 'Pix', 0, CHAVE_HOJE],
                                                      ['Despesa', 'dia 32', 100, 'Lazer', 'Pix', 32, CHAVE_HOJE],
                                                      ['Saque', 'tipo', 100, 'Lazer', 'Pix', 5, CHAVE_HOJE],
                                                      ['Entrada', 'mes quebrado', 100, 'Lazer', 'Pix', 5, 3.5]])})
    a5 = open_app(db5, now=AGORA17)
    c.eq([r[1] for r in a5.g['recorrentes']], ['ok'], 'so a repeticao valida e carregada')
    semear(db5, [], extra={'recorrentes': json.dumps('texto')})
    a5 = open_app(db5, now=AGORA17)
    c.eq(a5.g['recorrentes'], [], 'valor que nem e lista: ignorado')
    a5.touch('CanvasTopo')
    c.eq((a5.comp('ListaRecorrentes').visible, a5.comp('LblSemRec').visible), (False, True), 'sem repeticoes: frase no lugar da lista')
    erros = sum((x.runtime_errors for x in (app, a, a2, a3, a4, a5)), [])
    c.eq(erros, [], 'nenhum erro de execucao')


@test('T40', 'LIMITES por categoria: tela de limites, validação, cores (verde / amarela 80% / vermelha), aviso ao lançar, temas')
def t40(c):
    db = os.path.join(WORK, 'db_t40')
    regs = [['Despesa', 'Mercado', 96000, '10/11/2026 10:00', 'Alimentação', 'Pix'],
            ['Despesa', 'Show', 34000, '08/11/2026 21:00', 'Lazer', 'Cartão de crédito'],
            ['Despesa', 'Uber', 4000, '07/11/2026 08:00', 'Transporte', 'Pix'],
            ['Despesa', 'Farmácia', 5000, '05/11/2026 11:00', 'Saúde', 'Pix'],
            ['Despesa', 'Mercado', 150000, '10/10/2026 10:00', 'Alimentação', 'Pix'],
            ['Entrada', 'Salário', 500000, '05/11/2026 08:00', 'Outros', 'Pix']]
    semear(db, regs)
    app = open_app(db, now=AGORA17)
    c.eq(app.g['orcamentos'], [0] * 8, 'sem limites no comeco')
    app.click('BtnNavGrafico')
    c.eq((app.shown('BtnLimites'), app.text('BtnLimites')), (True, 'Limites'), '"Limites" no titulo do cartao "Gastos por categoria"')
    app.click('BtnLimites')
    c.eq((app.g['abaAtual'], app.shown('PnlOrcamento'), app.shown('PnlPeriodo')), (6, True, False), 'tela de limites')
    c.eq([app.text('TxtOrc%d' % i) for i in range(1, 9)], [''] * 8, 'campos vazios = sem limite')
    # valor invalido: campo vermelho, frase com a categoria, nada salvo
    digitar(app, 'TxtOrc1', '1.200,00')
    digitar(app, 'TxtOrc2', '50')
    digitar(app, 'TxtOrc5', '300')
    digitar(app, 'TxtOrc6', 'muito')
    digitar(app, 'TxtOrc8', '1,2,3')
    app.click('BtnSalvarOrc')
    c.eq((app.comp('LblErroOrc').visible, app.text('LblErroOrc')),
         (True, 'Valor inválido em Compras. Use vírgula nos centavos: 800,00.'), 'frase cita a 1a categoria com erro')
    c.eq([app.comp('HzCampoOrc%d' % i).props['Image'] for i in range(1, 9)],
         ['campo_curto.png'] * 5 + ['campo_curto_erro.png', 'campo_curto.png', 'campo_curto_erro.png'], 'so os campos errados ficam vermelhos')
    c.eq((app.g['orcamentos'], db_val(db, 'orcamentos'), app.g['abaAtual']), ([0] * 8, None, 6), 'nada salvo; continua na tela')
    digitar(app, 'TxtOrc6', '')
    digitar(app, 'TxtOrc8', '0')
    app.click('BtnSalvarOrc')
    lim = [120000, 5000, 0, 0, 30000, 0, 0, 0]
    c.eq((app.g['orcamentos'], db_val(db, 'orcamentos'), app.g['abaAtual']), (lim, lim, 3), 'salvo (0 = sem limite) e volta ao Grafico')
    # cartao de categorias com limites (mes atual)
    ref = r_categorias(regs, lambda k: k == CHAVE_HOJE, lim)
    c.eq(linhas_cat17(app), esperado_cat(app, ref), 'linhas com limite: %, sobra, cores e largura')
    textos = {n: t for n, _, t, _, _, _ in ref}
    c.eq((textos['Alimentação'], textos['Lazer'], textos['Transporte'], textos['Saúde']),
         ('80% de R$ 1.200,00  ' + PONTO + '  sobram R$ 240,00', 'Passou R$ 40,00 do limite (R$ 300,00)',
          '80% de R$ 50,00  ' + PONTO + '  sobram R$ 10,00', '3,6% das despesas'), 'frases conferidas a mao (5.000 de 139.000 = 3,6%)')
    barras = {n: b for n, _, _, b, _, _ in ref}
    c.eq((barras['Alimentação'], barras['Lazer'], barras['Saúde']), ('BarraAlerta', 'BarraEstouro', 'RED'), 'amarela (80%), vermelha, sem limite')
    # categoria com limite e sem gasto aparece (0%)
    app.click('BtnLimites')
    c.eq([app.text('TxtOrc%d' % i) for i in (1, 2, 5, 7)], ['1.200,00', '50,00', '300,00', ''], 'campos mostram os limites salvos')
    digitar(app, 'TxtOrc7', '200,00')
    app.click('BtnSalvarOrc')
    lim[6] = 20000
    c.eq(linhas_cat17(app), esperado_cat(app, r_categorias(regs, lambda k: k == CHAVE_HOJE, lim)), 'Educacao com limite e sem gasto: 0%')
    c.ok(any(l[0] == 'Educação' and l[2] == '0% de R$ 200,00  ' + PONTO + '  sobram R$ 200,00' for l in linhas_cat17(app)), 'linha 0%')
    # outro mes (outubro): limites valem para qualquer mes
    ir_para_mes(app, CHAVE_HOJE - 1)
    c.eq(linhas_cat17(app), esperado_cat(app, r_categorias(regs, lambda k: k == CHAVE_HOJE - 1, lim)), 'outubro: Alimentacao passou')
    # Ano / Tudo: sem limites (como na v1.6)
    app.click('BtnModoAno')
    c.eq(linhas_cat17(app), esperado_cat(app, r_categorias(regs, lambda k: k // 12 == 2026)), 'Ano: sem limites')
    c.eq(app.text('LblSubGraf'), 'Total de gastos em 2026', 'subtitulo do ano')
    app.click('BtnModoMes')
    # aviso ao lancar perto/acima do limite
    aviso = lancar17(app, 'Despesa', 'Padaria', '10,00', 'Transporte', 'Pix')
    c.eq(aviso, 'Despesa registrada! Transporte já usou 100% do limite do mês.', 'exatamente no limite: 100% (ainda nao passou)')
    # o cartao do grafico tambem: exatamente no limite = 100%, sobram R$ 0,00 e barra amarela (ainda nao "passou")
    app.click('BtnNavGrafico')
    agora = regs + [['Despesa', 'Padaria', 1000, '12/11/2026 21:00', 'Transporte', 'Pix']]
    c.eq(linhas_cat17(app), esperado_cat(app, r_categorias(agora, lambda k: k == CHAVE_HOJE, lim)),
         'grafico com Transporte exatamente no limite')
    c.ok(any(l[0] == 'Transporte' and l[2] == '100% de R$ 50,00  ' + PONTO + '  sobram R$ 0,00' and l[3] == cor_ficha(app, 'BarraAlerta')
             for l in linhas_cat17(app)), 'exatamente no limite: "100% de R$ 50,00 - sobram R$ 0,00", barra amarela (conferido a mao)')
    aviso = lancar17(app, 'Despesa', 'Ônibus', '0,01', 'Transporte', 'Pix')
    c.eq(aviso, 'Despesa registrada! Transporte passou do limite do mês.', 'um centavo acima: passou do limite')
    aviso = lancar17(app, 'Despesa', 'Feira', '100,00', 'Alimentação', 'Pix')
    c.eq(aviso, 'Despesa registrada! Alimentação já usou 88% do limite do mês.', '88% do limite')
    aviso = lancar17(app, 'Despesa', 'Livro', '10,00', 'Educação', 'Pix')
    c.eq(aviso, 'Despesa registrada!', 'abaixo de 80%: sem frase extra')
    aviso = lancar17(app, 'Entrada', 'Venda', '10,00', 'Lazer', 'Pix')
    c.eq(aviso, 'Entrada registrada!', 'entrada nao fala de limite')
    app.click('BtnNavHistorico')
    app.click('BtnModoTudo')
    pos = [i for i, r in enumerate(app.g['lancamentos'], 1) if r[3] == '10/10/2026 10:00'][0]
    tocar_lista(app, 'ListaHistorico', pos)
    app.answer_dialog('Editar')
    app.click('BtnDespesa')
    c.eq(app.text('LblAviso'), 'Lançamento atualizado!', 'editar despesa de OUTUBRO nao fala do limite de novembro')
    app.click('BtnNavHistorico')
    app.click('BtnModoMes')
    pos = [i for i, r in enumerate(app.g['lancamentos'], 1) if r[1] == 'Show'][0]
    tocar_lista(app, 'ListaHistorico', pos)
    app.answer_dialog('Editar')
    app.click('BtnDespesa')
    c.eq(app.text('LblAviso'), 'Lançamento atualizado! Lazer passou do limite do mês.', 'editar despesa deste mes acima do limite: avisa')
    # temas: as cores das barras e textos acompanham
    T = paleta()
    for escuro in (False, True):
        if escuro:
            app.click('ImgTema')
        app.click('BtnNavGrafico')
        regs_agora = app.g['lancamentos']
        ref = r_categorias(regs_agora, lambda k: k == CHAVE_HOJE, lim)
        c.eq(linhas_cat17(app), esperado_cat(app, ref), 'cartao com limites no tema %s' % ('escuro' if escuro else 'claro'))
        for ficha in ('BarraOk', 'BarraAlerta', 'BarraEstouro', 'Alerta', 'Perigo', 'Suave'):
            c.eq(cor_ficha(app, ficha), norm(T.aia(T.CORES[ficha][1 if escuro else 0])), 'ficha %s no tema %s' % (ficha, escuro))
        usadas = {norm(app.comp('LblCatBarra%d' % i).props['BackgroundColor']) for i in range(1, 9) if app.comp('PnlCat%d' % i).visible}
        c.ok({cor_ficha(app, 'BarraOk'), cor_ficha(app, 'BarraAlerta'), cor_ficha(app, 'BarraEstouro')} <= usadas,
             'as tres cores de barra aparecem (tema %s)' % ('escuro' if escuro else 'claro'))
    # abrir pelo Perfil e voltar para o Perfil
    app.touch('CanvasTopo')
    app.click('BtnLimites2')
    digitar(app, 'TxtOrc2', '')
    app.click('BtnSalvarOrc')
    c.eq((app.g['abaAtual'], app.text('LblDadosMsg'), app.comp('LblDadosMsg').visible), (4, 'Limites salvos!', True), 'volta ao Perfil')
    app.click('BtnLimites2')
    app.click('BtnOrcVoltar')
    c.eq(app.g['abaAtual'], 4, 'Voltar dos limites leva ao Perfil')
    # falha ao gravar limites
    app.click('BtnLimites2')
    digitar(app, 'TxtOrc3', '900')
    app.comp('TinyDB1').drop_writes = True
    app.click('BtnSalvarOrc')
    app.comp('TinyDB1').drop_writes = False
    c.eq((app.text('LblErroOrc'), app.g['orcamentos'][2], app.g['abaAtual']),
         ('Não foi possível salvar os limites. Tente de novo.', 0, 6), 'falha: aviso, nada muda, continua na tela')
    # persistencia e valor estranho no armazenamento
    a2 = open_app(db, now=AGORA17)
    c.eq(a2.g['orcamentos'], [120000, 0, 0, 0, 30000, 0, 20000, 0], 'limites continuam ao reabrir')
    semear(os.path.join(WORK, 'db_t40b'), [], extra={'orcamentos': json.dumps([1, 2, 3])})
    a3 = open_app(os.path.join(WORK, 'db_t40b'), now=AGORA17)
    c.eq(a3.g['orcamentos'], [0] * 8, 'limites com formato estranho: ignorados')
    semear(os.path.join(WORK, 'db_t40c'), [], extra={'orcamentos': json.dumps([100, 'x', -5, 0, 2.5, 0, 0, 7])})
    a4 = open_app(os.path.join(WORK, 'db_t40c'), now=AGORA17)
    c.eq(a4.g['orcamentos'], [100, 0, 0, 0, 0, 0, 0, 7], 'valor nao numerico, negativo ou quebrado (2,5 centavos) vira "sem limite"')
    c.eq(app.runtime_errors + a2.runtime_errors + a3.runtime_errors + a4.runtime_errors, [], 'nenhum erro de execucao')


def r_evolucao(regs, ano, sel=CHAVE_HOJE, hoje=CHAVE_HOJE):
    """v1.9: referencia independente da aba Evolucao: mes a mes do ano e o resumo do MES ESCOLHIDO (sel), comparado
    com o mes anterior a ele."""
    def soma(pred, tipo):
        return sum(r[2] for r in regs if r[0] == tipo and pred(r_chave(r[3])))
    tem = lambda k: any(r_chave(r[3]) == k for r in regs)
    out = {}
    eA, dA = soma(lambda k: k == sel, 'Entrada'), soma(lambda k: k == sel, 'Despesa')
    eP, dP = soma(lambda k: k == sel - 1, 'Entrada'), soma(lambda k: k == sel - 1, 'Despesa')
    nm, np_ = MESES17[sel % 12], MESES17[(sel - 1) % 12]
    sA = eA - dA
    out['titulo'] = r_titulo_mes(sel)
    if not tem(sel):
        out['frase'] = (('Ainda não há lançamentos em %s.' if sel == hoje else 'Nenhum lançamento em %s.') % nm, 'Suave')
    elif sA > 0:
        out['frase'] = ('Você guardou %s em %s.' % (ref_brl(sA), nm), 'Bom')
    elif sA < 0:
        out['frase'] = ('Você gastou %s a mais do que ganhou em %s.' % (ref_brl(-sA), nm), 'Perigo')
    else:
        out['frase'] = ('Você gastou exatamente o que ganhou em %s.' % nm, 'Texto')
    out['visiveis'] = (tem(sel), tem(sel), tem(sel))           # linhas Despesas e Entradas e o atalho para o Grafico
    out['valores'] = (ref_brl(dA), ref_brl(eA))

    def comp(atual, ant, menos_bom):
        if not tem(sel - 1):
            return ('Sem lançamentos em %s para comparar.' % np_, 'Suave')
        if atual == ant:
            return ('Igual a %s.' % np_, 'Suave')
        melhorou = atual < ant if menos_bom else atual > ant
        if ant == 0:
            return ('Em %s foi R$ 0,00.' % np_, 'Bom' if melhorou else 'Perigo')
        p10 = int(round(abs(atual - ant) * 1000.0 / ant))
        return ('%s %s %s (%s).' % (ref_pct(p10), 'a menos que em' if atual < ant else 'a mais que em', np_, ref_brl(ant)),
                'Bom' if melhorou else 'Perigo')
    out['comp_desp'] = comp(dA, dP, True)
    out['comp_ent'] = comp(eA, eP, False)
    mesE = [soma(lambda k, m=m: k == ano * 12 + m, 'Entrada') for m in range(12)]
    mesD = [soma(lambda k, m=m: k == ano * 12 + m, 'Despesa') for m in range(12)]
    maior = max(mesE + mesD)

    def alt(v, mx, util):
        return 0 if v <= 0 or mx <= 0 else max(2, int(round(v * float(util) / mx)))
    out['barrasE'] = [alt(v, maior, 104) for v in mesE]
    out['barrasD'] = [alt(v, maior, 104) for v in mesD]
    ano_hoje, mes_hoje = hoje // 12, hoje % 12 + 1
    out['cor_meses'] = ['Marca' if ano * 12 + m - 1 == sel else ('Dica' if (ano == ano_hoje and m > mes_hoje) else 'Suave')
                        for m in range(1, 13)]
    com = sum(1 for m in range(12) if tem(ano * 12 + m))
    totE, totD = sum(mesE), sum(mesD)
    if com == 0:
        out['ano_nomes'], out['ano_valores'] = ('Sem lançamentos em %d.' % ano, '')
    else:
        out['ano_nomes'] = 'Entradas no ano\nDespesas no ano\nSaldo do ano'
        out['ano_valores'] = '\n'.join([ref_brl(totE), ref_brl(totD), r_sinal(totE - totD)])
    return out


def tela_evolucao(app):
    g = lambda n: app.text(n)
    cor = lambda n: norm(app.comp(n).props.get('TextColor'))
    return {'titulo': g('LblTituloEvo'), 'frase': (g('LblEvoFrase'), cor('LblEvoFrase')),
            'visiveis': (app.comp('PnlEvoDesp').visible, app.comp('PnlEvoEnt').visible, app.comp('BtnEvoVerMes').visible),
            'valores': (g('LblEvoDespValor'), g('LblEvoEntValor')),
            'comp_desp': (g('LblEvoDespComp'), cor('LblEvoDespComp')), 'comp_ent': (g('LblEvoEntComp'), cor('LblEvoEntComp')),
            'barrasE': [int(app.comp('LblBarE%d' % m).props['Height']) for m in range(1, 13)],
            'barrasD': [int(app.comp('LblBarD%d' % m).props['Height']) for m in range(1, 13)],
            'cor_meses': [(app.text('BtnMes%d' % m), app.comp('BtnMes%d' % m).props.get('Image', '')) for m in range(1, 13)],
            'ano_nomes': g('LblEvoAnoNomes'), 'ano_valores': g('LblEvoAnoValores')}


def ref_na_tela(app, ref):
    """Troca os nomes de ficha da referencia pelas cores (e imagens das iniciais) que o app usa no tema atual."""
    f = lambda n: cor_ficha(app, n)
    r = dict(ref)
    r['frase'] = (ref['frase'][0], f(ref['frase'][1]))
    if ref['visiveis'][0]:
        r['comp_desp'] = (ref['comp_desp'][0], f(ref['comp_desp'][1]))
        r['comp_ent'] = (ref['comp_ent'][0], f(ref['comp_ent'][1]))
    r['cor_meses'] = [('', img_mes_ref(app, m, x)) for m, x in enumerate(ref['cor_meses'], 1)]
    return r


@test('T41', 'EVOLUÇÃO (pedido do usuário: aba mais enxuta): meta + "Mês a mês" com o resumo do mês tocado, comparado com o mês anterior (referência independente)')
def t41(c):
    nos = scm_nos()
    filhos = lambda n: [ch['$Name'] for ch in nos[n].get('$Components', [])]
    c.eq([n for n in filhos('PnlEvolucao') if not n.startswith('Esp')], ['CartaoMeta', 'CartaoEvoMeses'], 'a aba tem 2 cartoes: meta e Mes a mes')
    for n in ('CartaoEvoMes', 'CartaoEvoAcum', 'CartaoEvoAnos', 'ListaAnos', 'LblAcumFim', 'LblBarA1', 'LblEvoSaldoValor', 'LblEvoAnoPassado'):
        c.ok(n not in nos, '%s nao existe mais (saldo acumulado, ano a ano e linhas que sairam)' % n)
    c.eq([n for n in filhos('ColEvoMeses') if not n.startswith('Esp')],
         ['HzEvoAno', 'LblSubMeses', 'HzMeses', 'HzLegEvo', 'LblTituloEvo', 'LblEvoFrase', 'PnlEvoDesp', 'PnlEvoEnt', 'BtnEvoVerMes',
          'HzEvoDiv', 'HzEvoAnoRes'], 'ordem: ano e setas, barras, legenda, resumo do mes escolhido, atalho, totais do ano')
    c.eq(nos['LblSubMeses'].get('Text'), 'Toque em um mês para ver o resumo dele.', 'dica do toque')
    c.eq([str(nos['HzBarMes%d' % i].get('AlignVertical')) for i in range(1, 13)], ['3'] * 12, 'as barras crescem de baixo para cima')
    c.eq([(nos['LblBar%s%d' % (t, i)].get('HasMargins'), str(nos['LblBar%s%d' % (t, i)].get('Height'))) for t in 'ED' for i in range(1, 13)],
         [('False', '0')] * 24, 'barras sem margem e com altura zero ate os blocos calcularem')
    # 1) cenario montado a mao (valores conferidos de cabeca)
    db = os.path.join(WORK, 'db_t41')
    regs = [['Entrada', 'Salário', 500000, '05/11/2026 08:00', 'Outros', 'Pix'],
            ['Despesa', 'Aluguel', 150000, '10/11/2026 09:00', 'Moradia', 'Pix'],
            ['Entrada', 'Salário', 500000, '05/10/2026 08:00', 'Outros', 'Pix'],
            ['Despesa', 'Aluguel', 150000, '10/10/2026 09:00', 'Moradia', 'Pix'],
            ['Despesa', 'Mercado', 50000, '15/10/2026 18:00', 'Alimentação', 'Pix'],
            ['Entrada', 'Salário', 400000, '05/11/2025 08:00', 'Outros', 'Pix'],
            ['Despesa', 'Tudo', 450000, '20/11/2025 08:00', 'Compras', 'Pix'],
            ['Entrada', 'Herança sem data', 100000, 'sem data', 'Outros', 'Pix']]
    semear(db, regs)
    app = open_app(db, now=AGORA17)
    app.click('BtnNavEvolucao')
    c.eq((app.g['abaAtual'], app.shown('PnlEvolucao'), app.g['evoMesSel']), (5, True, CHAVE_HOJE), 'aba Evolucao, com o mes atual escolhido')
    t = tela_evolucao(app)
    c.eq(t['titulo'], 'Novembro de 2026', 'titulo do resumo = o mes escolhido')
    c.eq(t['frase'], ('Você guardou R$ 3.500,00 em novembro.', cor_ficha(app, 'Bom')), 'frase do mes (verde)')
    c.eq(t['valores'], ('R$ 1.500,00', 'R$ 5.000,00'), 'despesas e entradas do mes')
    c.eq(t['comp_desp'], ('25,0% a menos que em outubro (R$ 2.000,00).', cor_ficha(app, 'Bom')), 'gastou menos = verde')
    c.eq(t['comp_ent'], ('Igual a outubro.', cor_ficha(app, 'Suave')), 'entradas iguais')
    c.eq((t['ano_nomes'], t['ano_valores']), ('Entradas no ano\nDespesas no ano\nSaldo do ano',
                                              'R$ 10.000,00\nR$ 3.500,00\n+ R$ 6.500,00'), 'totais de 2026 (sem data nao entra)')
    c.eq(t, ref_na_tela(app, r_evolucao(regs, 2026)), 'tudo igual a referencia (2026, novembro)')
    # 2) tocar em outro mes: o resumo passa a ser dele (e a inicial dele fica destacada)
    app.click('BtnMes10')
    c.eq((app.g['abaAtual'], app.g['evoMesSel']), (5, CHAVE_HOJE - 1), 'tocar em O: continua na Evolucao, outubro escolhido')
    t = tela_evolucao(app)
    c.eq((t['titulo'], t['frase'][0], t['valores'], t['comp_desp'][0]),
         ('Outubro de 2026', 'Você guardou R$ 3.000,00 em outubro.', ('R$ 2.000,00', 'R$ 5.000,00'),
          'Sem lançamentos em setembro para comparar.'), 'resumo de outubro (conferido a mao)')
    c.eq(t, ref_na_tela(app, r_evolucao(regs, 2026, CHAVE_HOJE - 1)), 'outubro igual a referencia')
    c.eq([x[1] for x in t['cor_meses']][9:11], [img_mes_ref(app, 10, 'Marca'), img_mes_ref(app, 11, 'Suave')],
         'O destacado; N volta ao normal')
    app.click('BtnMes12')
    c.eq(app.g['evoMesSel'], CHAVE_HOJE - 1, 'mes que ainda vem (dez/2026): o toque nao muda nada')
    app.click('BtnMes3')
    t = tela_evolucao_cmp(app)
    c.eq((t['frase'], t['visiveis']), (('Nenhum lançamento em março.', cor_ficha(app, 'Suave')), (False, False, False)),
         'mes passado sem lancamento: so a frase (linhas e atalho somem)')
    c.eq(t, ref_cmp(app, r_evolucao(regs, 2026, 2026 * 12 + 2)), 'marco igual a referencia')
    # 3) setas do ano levam o mes escolhido junto (mesmo mes, sem passar de hoje)
    app.click('BtnMes11')
    c.eq((seta(app, 'BtnEvoAnoAnt'), seta(app, 'BtnEvoAnoProx')), ('‹', ''), 'setas do ano')
    app.click('BtnEvoAnoAnt')
    c.eq((app.g['evoAno'], app.g['evoMesSel']), (2025, 2025 * 12 + 10), '2025: novembro de 2025 escolhido')
    t = tela_evolucao(app)
    c.eq((t['titulo'], t['frase']), ('Novembro de 2025', ('Você gastou R$ 500,00 a mais do que ganhou em novembro.', cor_ficha(app, 'Perigo'))),
         'novembro de 2025: gastou mais do que ganhou (vermelho)')
    c.eq(t, ref_na_tela(app, r_evolucao(regs, 2025, 2025 * 12 + 10)), '2025 igual a referencia')
    c.eq((app.text('LblEvoAno'), seta(app, 'BtnEvoAnoAnt'), seta(app, 'BtnEvoAnoProx')), ('2025', '', '›'), '2025 e o mais antigo')
    app.click('BtnEvoAnoAnt')
    c.eq(app.g['evoAno'], 2025, 'nao passa do ano mais antigo')
    # 4) atalho: "Ver gastos por categoria deste mes" abre o Grafico daquele mes
    app.click('BtnEvoVerMes')
    c.eq((app.g['abaAtual'], app.g['periodoModo'], app.text('LblPeriodo'), app.text('LblLegDespValor')),
         (3, 'mes', 'Novembro de 2025', 'R$ 4.500,00'), 'o atalho abre novembro/2025 no Grafico')
    app.click('BtnNavEvolucao')
    c.eq((app.g['evoAno'], app.g['evoMesSel']), (2025, 2025 * 12 + 10), 'voltar a Evolucao: continua em novembro de 2025')
    app.click('BtnEvoAnoProx')
    c.eq((app.g['evoAno'], app.g['evoMesSel']), (2026, CHAVE_HOJE), 'de volta a 2026: novembro de 2026')
    app.click('BtnMes10')
    app.click('BtnEvoAnoAnt')
    app.click('BtnEvoAnoProx')
    c.eq(app.g['evoMesSel'], CHAVE_HOJE - 1, 'outubro vai e volta como outubro')
    app.click('BtnEvoAnoAnt')
    app.click('BtnMes12')
    c.eq(app.g['evoMesSel'], 2025 * 12 + 11, 'em 2025, dezembro pode ser escolhido')
    app.click('BtnEvoAnoProx')
    c.eq((app.g['evoAno'], app.g['evoMesSel'], tela_evolucao(app)['titulo']), (2026, CHAVE_HOJE, 'Novembro de 2026'),
         'dezembro de 2025 -> seta para 2026: dezembro de 2026 ainda nao chegou, fica novembro de 2026')
    c.clean(app)
    # 5) frases de todos os casos
    casos = [
        ([], 'Ainda não há lançamentos em novembro.', None),
        ([['Despesa', 'x', 100, '01/11/2026 10:00', 'Lazer', 'Pix']], 'Você gastou R$ 1,00 a mais do que ganhou em novembro.', None),
        ([['Despesa', 'x', 100, '01/11/2026 10:00', 'Lazer', 'Pix'], ['Entrada', 'y', 100, '02/11/2026 10:00', 'Outros', 'Pix']],
         'Você gastou exatamente o que ganhou em novembro.', None),
        ([['Despesa', 'x', 30000, '01/11/2026 10:00', 'Lazer', 'Pix'], ['Despesa', 'z', 10000, '01/10/2026 10:00', 'Lazer', 'Pix']],
         None, '200,0% a mais que em outubro (R$ 100,00).'),
        ([['Despesa', 'x', 30000, '01/11/2026 10:00', 'Lazer', 'Pix'], ['Entrada', 'z', 10000, '01/10/2026 10:00', 'Lazer', 'Pix']],
         None, 'Em outubro foi R$ 0,00.'),
    ]
    for i, (rr, frase, comp_d) in enumerate(casos):
        d = os.path.join(WORK, 'db_t41_%d' % i)
        semear(d, rr)
        a = open_app(d, now=AGORA17)
        a.click('BtnNavEvolucao')
        t = tela_evolucao_cmp(a)
        c.eq(t, ref_cmp(a, r_evolucao(rr, 2026)), 'caso %d igual a referencia' % i)
        if frase:
            c.eq(t['frase'][0], frase, 'frase do caso %d' % i)
        if comp_d:
            c.eq(t['comp_desp'][0], comp_d, 'comparacao do caso %d' % i)
        if not rr:
            c.eq((t['visiveis'], t['ano_nomes'], t['ano_valores']), ((False, False, False), 'Sem lançamentos em 2026.', ''),
                 'sem dados: frases de vazio, sem linhas')
        c.clean(a, 'caso %d' % i)
    # 6) aleatorio: 40 historicos de ate 3 anos, nos dois temas, todos os anos e um mes tocado em cada ano
    rnd = random.Random(41)
    for n in range(40):
        rr = gerar_regs(rnd, rnd.randint(0, 90), CHAVE_HOJE - rnd.randint(0, 35), CHAVE_HOJE, invalidos=rnd.randint(0, 2))
        d = os.path.join(WORK, 'db_t41_r')
        semear(d, rr, extra={'tema': json.dumps('escuro')} if n % 2 else None)
        a = open_app(d, now=AGORA17)
        a.click('BtnNavEvolucao')
        validos = [r_chave(r[3]) for r in rr if r_chave(r[3]) >= 0]
        ano_min = min(validos) // 12 if validos else 2026
        sel = CHAVE_HOJE
        for ano in range(2026, ano_min - 1, -1):
            c.eq(tela_evolucao_cmp(a), ref_cmp(a, r_evolucao(rr, ano, sel)), 'historico aleatorio %d, ano %d, mes %d' % (n, ano, sel % 12 + 1))
            m = rnd.randint(1, 12)
            a.click('BtnMes%d' % m)
            if ano * 12 + m - 1 <= CHAVE_HOJE:
                sel = ano * 12 + m - 1
            c.eq(tela_evolucao_cmp(a), ref_cmp(a, r_evolucao(rr, ano, sel)), 'historico aleatorio %d, ano %d, depois de tocar no mes %d' % (n, ano, m))
            a.click('BtnEvoAnoAnt')
            if ano > ano_min:
                sel = (ano - 1) * 12 + sel % 12
        c.clean(a, 'historico aleatorio %d' % n)


def ler_csv_ponto_virgula(texto):
    import csv as _csv
    return list(_csv.reader(io.StringIO(texto.lstrip('﻿'), newline=''), delimiter=';'))


@test('T42', 'DADOS: exportar planilha (CSV), backup e restauração (ida e volta), arquivos estranhos, cancelar e falhas')
def t42(c):
    nos = scm_nos()
    c.eq((nos['Screen1'].get('DefaultFileScope'), nos['File1'].get('$Type'), nos['File1'].get('DefaultScope'), nos['Sharing1'].get('$Type')),
         ('App', 'File', 'App', 'Sharing'), 'arquivos na pasta do proprio app (sem pedir permissao) e compartilhamento')
    c.eq((nos['PickerRestaurar'].get('$Type'), nos['PickerRestaurar'].get('Action', 'Pick Existing File'),
          nos['PickerRestaurar'].get('MimeType', '*/*')), ('FilePicker', 'Pick Existing File', '*/*'),
         'Restaurar backup abre o seletor de documentos do Android (qualquer arquivo)')
    db = os.path.join(WORK, 'db_t42')
    shutil.rmtree(db, ignore_errors=True)
    app = open_app(db, now=AGORA17)
    app.touch('CanvasTopo')
    c.ok(app.shown('BtnExportar') and app.shown('BtnBackup') and app.shown('PickerRestaurar'), 'botoes do cartao Seus dados')
    app.click('BtnExportar')
    c.eq((app.text('LblDadosMsg'), norm(app.comp('LblDadosMsg').props['TextColor']), app.arquivos),
         ('Ainda não há lançamentos para exportar.', cor_ficha(app, 'Perigo'), {}), 'sem dados: aviso e nenhum arquivo')
    # dados com caracteres que exigem cuidado na planilha
    regs = [['Despesa', 'Feira; frutas e "verduras"', 125099, '12/11/2026 08:00', 'Alimentação', 'Pix'],
            ['Entrada', '=1+1', 50, '11/11/2026 09:00', 'Outros', 'Dinheiro'],
            ['Despesa', '-desconto', 7, '10/11/2026 10:00', 'Compras', 'Cartão de crédito'],
            ['Entrada', 'Salário', 500000, '05/11/2026 08:00', 'Outros', 'Transferência bancária'],
            ['Despesa', 'Sem descrição', 100, '01/01/2026 10:00', 'Não informado', 'Não informado']]
    semear(db, regs, recorrentes=[['Despesa', 'Aluguel', 135000, 'Moradia', 'Pix', 10, CHAVE_HOJE]],
           orcamentos=[100000, 0, 0, 0, 30000, 0, 0, 0], extra={'perfil_nome': json.dumps('Marina Costa'), 'tema': json.dumps('escuro')})
    app = open_app(db, now=AGORA17)
    app.touch('CanvasTopo')
    app.click('BtnExportar')
    nome = 'Conto_planilha_2026-11-12.csv'
    c.eq(sorted(app.arquivos), [nome], 'arquivo da planilha com a data no nome')
    txt_csv = app.arquivos[nome]
    c.ok(txt_csv.startswith('﻿'), 'comeca com BOM (o Excel reconhece os acentos)')
    c.ok('\r\n' in txt_csv and '\n' not in txt_csv.replace('\r\n', ''), 'linhas separadas por CRLF')
    linhas = ler_csv_ponto_virgula(txt_csv)
    esperado = [['Data', 'Tipo', 'Descrição', 'Categoria', 'Pagamento', 'Valor (R$)']]
    for r in regs:
        desc = ("'" + r[1]) if r[1][:1] in '=+-@' else r[1]
        val = ('' if r[0] == 'Entrada' else '-') + '%d,%02d' % divmod(r[2], 100)
        esperado.append([r[3], r[0], desc, r[4], r[5], val])
    c.eq(linhas, esperado, 'planilha lida por um leitor de CSV (;) = lancamentos; formula vira texto; valor com sinal')
    c.eq(app.compartilhados[-1]['arquivo'], nome, 'abre o compartilhamento do Android com a planilha')
    c.eq(app.compartilhados[-1]['tipo'], 'text/comma-separated-values', 'tipo do arquivo')
    c.eq((app.text('LblDadosMsg'), norm(app.comp('LblDadosMsg').props['TextColor'])),
         ('Pronto! Escolha onde salvar ou para quem enviar o arquivo.', cor_ficha(app, 'AvisoOk')), 'mensagem depois de salvar')
    # backup
    app.click('BtnBackup')
    nb = 'Conto_backup_2026-11-12.txt'
    c.ok(nb in app.arquivos and app.compartilhados[-1]['arquivo'] == nb, 'backup salvo e compartilhado')
    tabela = tabela_de_csv(app.arquivos[nb])
    c.eq(tabela[0], ['Conto-backup', '1', '12/11/2026 21:00'], 'cabecalho do backup')
    c.eq(tabela[-1], ['Fim', '5'], 'ultima linha do backup: conferencia com o numero de lancamentos')
    c.eq([t for t in tabela if t[0] == 'L'], [['L'] + [str(x) for x in r] for r in regs], 'lancamentos no backup')
    c.eq([t for t in tabela if t[0] in 'ORPT'],
         [['O', '100000', '0', '0', '0', '30000', '0', '0', '0'], ['R', 'Despesa', 'Aluguel', '135000', 'Moradia', 'Pix', '10', str(CHAVE_HOJE)],
          ['P', 'Marina Costa'], ['T', 'escuro']], 'limites, repeticoes, nome e tema no backup')
    # restaurar em outro aparelho (app novo)
    db2 = os.path.join(WORK, 'db_t42b')
    semear(db2, [['Despesa', 'Coisa do celular novo', 999, '12/11/2026 10:00', 'Lazer', 'Pix']])
    b = open_app(db2, now=AGORA17)
    b.touch('CanvasTopo')
    b.pick_file('content://com.android.providers.downloads.documents/document/42', app.arquivos[nb])
    p = b.comp('Notifier1').pending
    c.eq((p['title'], p['buttons'], p['cancelable']), ('Restaurar backup?', ['Restaurar', 'Cancelar'], False), 'confirmacao')
    c.eq(p['texto'], 'Backup de 12/11/2026 21:00 com 5 lançamentos.\n\nRestaurar vai substituir os lançamentos que estão no app '
                     'agora (1), além dos limites e do que se repete.', 'mensagem da confirmacao')
    c.eq(b.g['lancamentos'][0][1], 'Coisa do celular novo', 'antes de confirmar nada muda')
    b.answer_dialog('Restaurar')
    c.eq(b.g['lancamentos'], regs, 'lancamentos restaurados (iguais, mesma ordem, valores numericos)')
    c.eq((db_lancamentos(db2), db_val(db2, 'orcamentos'), db_val(db2, 'recorrentes'), db_val(db2, 'perfil_nome'), db_val(db2, 'tema')),
         (regs, [100000, 0, 0, 0, 30000, 0, 0, 0], [['Despesa', 'Aluguel', 135000, 'Moradia', 'Pix', 10, CHAVE_HOJE]], 'Marina Costa', 'escuro'),
         'tudo gravado no aparelho novo')
    c.eq((b.g['temaEscuro'], b.text('LblSaudacao'), b.text('LblDadosMsg')), (True, 'Olá, Marina', 'Backup restaurado: 5 lançamentos.'),
         'tema, nome e mensagem')
    c.eq(linhas_hist(b) if b.shown('PnlHistorico') else None, None, 'continua no Perfil')
    b.click('BtnPerfilVoltar')
    b.click('BtnNavHistorico')
    c.eq(linhas_hist(b), [r_linha_hist(r) for r in regs if r_chave(r[3]) == CHAVE_HOJE], 'historico do mes depois de restaurar')
    # mesmo numero de lancamentos com outras datas (o cache de meses tem que ser refeito)
    outro = [['Despesa', 'Outro %d' % i, 100 + i, '0%d/03/2025 10:00' % (i + 1), 'Lazer', 'Pix'] for i in range(5)]
    tab2 = [['Conto-backup', '1', '01/04/2025 10:00']] + [['L'] + r for r in outro] + [['Fim', '5']]
    b.touch('CanvasTopo')
    b.pick_file('content://x/2', csv_de_tabela(tab2))
    b.answer_dialog('Restaurar')
    b.click('BtnPerfilVoltar')
    b.click('BtnNavHistorico')
    c.eq((linhas_hist(b), b.text('LblVazio')), ([], 'Nenhum lançamento em novembro de 2026.'), 'mesmo tamanho, outras datas: novembro vazio')
    ir_para_mes(b, 2025 * 12 + 2)
    c.eq(len(linhas_hist(b)), 5, 'os 5 aparecem em marco/2025')
    c.eq((db_val(db2, 'orcamentos'), db_val(db2, 'recorrentes')), ([0] * 8, []), 'backup sem limites/repeticoes: zera os dois')
    # cancelar
    b.touch('CanvasTopo')
    b.pick_file('content://x/3', app.arquivos[nb])
    b.answer_dialog('Cancelar')
    c.eq((b.g['lancamentos'], b.text('LblDadosMsg'), b.g['backupPendente']), (outro, 'Restauração cancelada. Nada mudou.', []), 'cancelar')
    # arquivo que nao e backup (a propria planilha, texto qualquer, vazio)
    for i, conteudo in enumerate([txt_csv, 'oi', '', '"Conto-backup']):
        b.pick_file('content://x/n%d' % i, conteudo)
        c.eq((b.text('LblDadosMsg'), b.comp('Notifier1').pending, b.g['lancamentos']),
             ('Este arquivo não é um backup do Contô.', None, outro), 'arquivo %d nao e backup: nada muda' % i)
    # backup CORTADO em cada posicao (arquivo incompleto): nunca para o app com erro tecnico e nunca restaura pela metade;
    # so o arquivo inteiro (ou sem a quebra de linha final) abre a confirmacao
    bk = app.arquivos[nb]
    INCOMPLETO = 'Este backup está incompleto ou foi alterado. Nada mudou.'
    erros_antes = len(b.runtime_errors)
    resultados = []
    for n in range(14, len(bk) + 1):
        b.pick_file('content://x/corte%d' % n, bk[:n])
        pend = b.comp('Notifier1').pending
        resultados.append((n, 'confirmacao' if pend else b.text('LblDadosMsg'), b.g['backupPendente'] != []))
        if pend:
            b.answer_dialog('Cancelar')
    esperado_cortes = [(n, 'confirmacao' if n >= len(bk) - 2 else INCOMPLETO, n >= len(bk) - 2) for n in range(14, len(bk) + 1)]
    c.eq(resultados, esperado_cortes, 'backup cortado em cada uma das %d posicoes: aviso de incompleto (so o inteiro abre)' % len(resultados))
    c.eq((b.runtime_errors[erros_antes:], b.g['lancamentos']), ([], outro), 'nenhum erro tecnico e nada mudou com os arquivos cortados')
    # alterado a mao: aspa apagada, lancamento apagado (a conferencia nao bate), texto colado no fim, linha a mais no fim
    linhas_bk = bk.split('\r\n')
    sem_aspa = bk.replace('"Aluguel"', '"Aluguel', 1)
    sem_linha = '\r\n'.join(l for l in linhas_bk if not l.startswith('"L","Entrada"'))
    c.ok(sem_linha != bk and bk.count('"Aluguel"') == 1, 'arquivos alterados de teste montados')
    for rot, conteudo in (('aspa apagada', sem_aspa), ('lancamento apagado', sem_linha), ('texto colado no fim', bk.rstrip('\r\n') + 'x'),
                          ('linha a mais no fim', bk + '"L","Despesa","extra","1","01/01/2026 10:00","Lazer","Pix"\r\n')):
        b.pick_file('content://x/alt', conteudo)
        c.eq((b.text('LblDadosMsg'), b.comp('Notifier1').pending, b.g['lancamentos'], b.runtime_errors[erros_antes:]),
             (INCOMPLETO, None, outro, []), 'backup alterado (%s): aviso e nada muda' % rot)
    # espacos/quebras de linha a mais no fim e quebras de linha so com \n (File.ReadFrom normaliza) continuam valendo
    for rot, conteudo in (('linhas em branco no fim', bk + '\r\n\r\n  '), ('quebras so com \\n', bk.replace('\r\n', '\n'))):
        b.pick_file('content://x/ok', conteudo)
        p2 = b.comp('Notifier1').pending
        c.eq(p2 and p2['texto'].split('\n')[0], 'Backup de 12/11/2026 21:00 com 5 lançamentos.', 'backup com %s: abre a confirmacao' % rot)
        b.answer_dialog('Cancelar')
    # BOM no comeco (arquivo que passou por outro app) e linhas invalidas ignoradas
    tab3 = [['Conto-backup', '1', '02/02/2026 10:00'], ['L', 'Despesa', 'ok', '150', '01/02/2026 10:00', 'Lazer', 'Pix'],
            ['L', 'Saque', 'tipo errado', '1', '01/02/2026 10:00', 'Lazer', 'Pix'], ['L', 'Despesa', 'negativo', '-5', 'x', 'Lazer', 'Pix'],
            ['L', 'Despesa', 'quebrado', '1.5', 'x', 'Lazer', 'Pix'], ['L', 'Despesa', 'curto'], ['Z', 'qualquer'],
            ['R', 'Despesa', 'dia ruim', '100', 'Lazer', 'Pix', '40', '1'], ['O', '5', 'x', '-1', '0', '0', '0', '0', '2'],
            ['Fim', '5']]     # a conferencia conta as 5 linhas "L" do arquivo (validas ou nao)
    b.pick_file('content://x/bom', '﻿' + csv_de_tabela(tab3))
    c.eq(b.comp('Notifier1').pending['texto'].split('\n')[0], 'Backup de 02/02/2026 10:00 com 1 lançamento.', 'BOM aceito; 1 linha valida')
    b.answer_dialog('Restaurar')
    c.eq((b.g['lancamentos'], b.g['recorrentes'], b.g['orcamentos']),
         ([['Despesa', 'ok', 150, '01/02/2026 10:00', 'Lazer', 'Pix']], [], [5, 0, 0, 0, 0, 0, 0, 2]), 'so o que e valido')
    # falha de gravacao ao restaurar: nada muda
    antes = [list(x) for x in b.g['lancamentos']]
    b.pick_file('content://x/f', app.arquivos[nb])
    b.comp('TinyDB1').drop_writes = True
    b.answer_dialog('Restaurar')
    b.comp('TinyDB1').drop_writes = False
    c.eq((b.g['lancamentos'], db_lancamentos(db2), b.text('LblDadosMsg')),
         (antes, antes, 'Não foi possível restaurar: o aparelho não deixou gravar. Nada mudou.'), 'falha ao restaurar: nada muda')
    # falha com o MESMO numero de lancamentos (so o conteudo mostra que nao gravou)
    um = [['Conto-backup', '1', '03/03/2026 10:00'], ['L', 'Entrada', 'Outro', '777', '03/03/2026 10:00', 'Outros', 'Pix'], ['Fim', '1']]
    c.eq(len(b.g['lancamentos']), 1, 'o app tem 1 lancamento e o backup tambem')
    b.pick_file('content://x/f1', csv_de_tabela(um))
    b.comp('TinyDB1').drop_writes = True
    b.answer_dialog('Restaurar')
    b.comp('TinyDB1').drop_writes = False
    c.eq((b.g['lancamentos'], db_lancamentos(db2), b.text('LblDadosMsg')),
         (antes, antes, 'Não foi possível restaurar: o aparelho não deixou gravar. Nada mudou.'), 'mesmo tamanho: a falha tambem e percebida')
    # erros de arquivo (ErrorOccurred) e de outro componente
    b.comp('File1').falhar = 'ler'
    b.pick_file('content://x/erro', 'qualquer')
    b.comp('File1').falhar = None
    c.eq((b.text('LblDadosMsg'), norm(b.comp('LblDadosMsg').props['TextColor'])),
         ('Não foi possível concluir com este arquivo. Tente de novo.', cor_ficha(b, 'Perigo')), 'falha de leitura: aviso no cartao')
    b.comp('File1').falhar = 'gravar'
    b.click('BtnExportar')
    b.comp('File1').falhar = None
    c.eq(b.text('LblDadosMsg'), 'Não foi possível concluir com este arquivo. Tente de novo.', 'falha ao salvar a planilha: aviso')
    n_alertas = len(b.alerts)
    b.erro_componente(b.comp('TinyDB1'), 'GetValue', 9999, 'algo deu errado')
    c.eq(b.alerts[n_alertas:], ['algo deu errado'], 'erro de outro componente: aviso padrao com a mensagem')
    # o tema escuro ao abrir o Perfil esconde mensagem antiga; trocar o tema tambem
    b.click('BtnPerfilVoltar')
    b.touch('CanvasTopo')
    c.eq(b.comp('LblDadosMsg').visible, False, 'abrir o Perfil esconde a mensagem antiga')
    c.eq(app.runtime_errors + b.runtime_errors, [], 'nenhum erro de execucao')


@test('T43', 'TEMA e telas novas: pílulas e abas, lista de opções do tamanho certo, "repetir" e cores calculadas sobrevivem à troca de tema')
def t43(c):
    T = paleta()
    db = os.path.join(WORK, 'db_t43')
    regs = gerar_regs(random.Random(43), 60, CHAVE_HOJE - 13, CHAVE_HOJE)
    semear(db, regs, orcamentos=[50000, 1000, 0, 0, 20000, 0, 0, 0])
    app = open_app(db, now=AGORA17)
    from PIL import Image
    nos = scm_nos()
    c.eq([str(nos[n].get('ListViewLayout')) for n in ('ListaOpcoes', 'ListaHistorico', 'ListaRecorrentes')], ['3', '4', '1'],
         'listas: icone+nome (opcoes), icone+2 textos (historico), 2 textos (repeticoes); a lista "Ano a ano" saiu na v1.9')

    def lum(rgb):
        def ch(v):
            v = v / 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])

    def contraste(a, b):
        la, lb = sorted((lum(a), lum(b)), reverse=True)
        return (la + 0.05) / (lb + 0.05)

    def rgb(v):
        h = norm(v)
        return (int(h[4:6], 16), int(h[6:8], 16), int(h[8:10], 16))
    for escuro in (False, True):
        if app.g['temaEscuro'] != escuro:
            app.click('ImgTema')
        for lista in ('ListaHistorico', 'ListaRecorrentes', 'ListaOpcoes'):
            pr = app.comp(lista).props
            fundo = pr.get('ElementColor', pr.get('BackgroundColor'))
            # a lista de opcoes (layout 3: icone + nome) nao tem 2a linha; as outras precisam da cor da 2a linha
            # (sem ela o App Inventor usa a cor padrao, que sumiria no cartao)
            chaves = ('TextColor',) if lista == 'ListaOpcoes' else ('TextColor', 'TextColorDetail')
            for chave in chaves:
                c.ok(chave in pr, '%s tem %s definida (tema %s)' % (lista, chave, 'escuro' if escuro else 'claro'))
                if chave not in pr:
                    continue
                r_ = contraste(rgb(pr[chave]), rgb(fundo))
                c.ok(r_ >= 4.5, '%s: %s sobre o cartao da lista = %.2f:1 no tema %s (>= 4,5)' % (lista, chave, r_, 'escuro' if escuro else 'claro'))
    if app.g['temaEscuro']:
        app.click('ImgTema')
    assets = pacote_assets()
    for a_, b_ in (('ic_check_on', 'ic_check_off'), ('campo_curto', 'campo_curto_erro'), ('ic_busca', 'ic_check_off')):
        for suf in ('', '_d'):
            ia = Image.open(io.BytesIO(assets[a_ + suf + '.png'])).convert('RGBA')
            ib = Image.open(io.BytesIO(assets[b_ + suf + '.png'])).convert('RGBA')
            c.ok(ia.size != ib.size or list(ia.getdata()) != list(ib.getdata()), 'imagens %s%s e %s%s sao diferentes' % (a_, suf, b_, suf))
    # lista de opcoes: altura acompanha o numero de opcoes
    app.click('BtnCategoria')
    c.eq(app.comp('ListaOpcoes').props['Height'], 8 * 62 + 8, '8 categorias: lista de 504 dp (nenhuma escondida)')
    app.pick_option('Lazer')
    app.click('BtnPagamento')
    c.eq(app.comp('ListaOpcoes').props['Height'], 5 * 62 + 8, '5 formas de pagamento: 318 dp')
    app.pick_option('Pix')
    # aba Evolucao destacada como as outras
    for aba, n in (('BtnNavEvolucao', 5), ('BtnNavGrafico', 3), ('BtnNavHistorico', 2), ('BtnNavLancar', 1)):
        app.click(aba)
        ativas = [b for b in ('BtnNavLancar', 'BtnNavHistorico', 'BtnNavGrafico', 'BtnNavEvolucao')
                  if app.comp(b).props.get('Image') == 'aba_ativa.png']
        c.eq((app.g['abaAtual'], ativas), (n, [aba]), 'aba %s destacada sozinha' % aba)
    # "repetir" marcado sobrevive a troca de tema
    app.click('BtnRepetir')
    app.click('ImgTema')
    c.eq((app.g['repetirSel'], app.comp('ImgRepetir').props['Picture']), (True, 'ic_check_on_d.png'), 'marcado continua marcado no escuro')
    app.click('BtnRepetir')
    c.eq(app.comp('ImgRepetir').props['Picture'], 'ic_check_off_d.png', 'desmarcado no escuro')
    # trocar o tema com a Evolucao e o Grafico abertos: cores calculadas sao refeitas no tema novo
    for aba in ('BtnNavEvolucao', 'BtnNavGrafico'):
        app.click(aba)
        app.click('ImgTema')
        escuro = app.g['temaEscuro']
        if aba == 'BtnNavEvolucao':
            c.eq(tela_evolucao(app), ref_na_tela(app, r_evolucao(regs, 2026)), 'Evolucao certa depois de trocar o tema (escuro=%s)' % escuro)
        else:
            c.eq(linhas_cat17(app), esperado_cat(app, r_categorias(regs, lambda k: k == CHAVE_HOJE, [50000, 1000, 0, 0, 20000, 0, 0, 0])),
                 'categorias certas depois de trocar o tema (escuro=%s)' % escuro)
        for ficha in ('Bom', 'Perigo', 'Suave', 'Marca', 'Dica', 'Alerta'):
            c.eq(cor_ficha(app, ficha), norm(T.aia(T.CORES[ficha][1 if escuro else 0])), 'ficha %s (escuro=%s)' % (ficha, escuro))
    # mensagem do cartao de dados some ao trocar o tema; campos de limite voltam ao normal
    app.touch('CanvasTopo')
    app.click('BtnExportar')
    c.eq(app.comp('LblDadosMsg').visible, True, 'mensagem aparece')
    app.click('BtnTemaEscuro' if not app.g['temaEscuro'] else 'BtnTemaClaro')
    c.eq(app.comp('LblDadosMsg').visible, False, 'trocar o tema esconde a mensagem')
    app.click('BtnLimites2')
    digitar(app, 'TxtOrc1', 'abc')
    app.click('BtnSalvarOrc')
    c.eq(app.comp('LblErroOrc').visible, True, 'erro no limite')
    app.click('ImgTema')
    c.eq((app.comp('LblErroOrc').visible, app.comp('HzCampoOrc1').props['Image'][:11]), (False, 'campo_curto'), 'trocar o tema limpa o erro')
    c.eq(app.runtime_errors, [], 'nenhum erro de execucao')


@test('T44', 'ESTRUTURA e CONSISTÊNCIA: tamanho de cada bloco compilado, cache de meses sempre certo numa sequência aleatória de ações')
def t44(c):
    import xml.etree.ElementTree as ET
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import tamanho_metodos
    r = ET.parse(NEW_BKY).getroot()
    metodos = []
    for b in r:
        if b.tag.endswith('block'):
            tamanho_metodos.medir(b, tamanho_metodos.nome(b), metodos)
    maior = max(metodos)
    c.ok(maior[0] <= 441, 'maior metodo compilado: %s com %d blocos (v1.6 tinha 441; limite da JVM e 64 KB por metodo)' % (maior[1], maior[0]))
    c.note('maior metodo: %s = %d blocos; total %d blocos em %d metodos' % (maior[1], maior[0], sum(1 for _ in r.iter(
        '{https://developers.google.com/blockly/xml}block')), len(metodos)))
    # sequencia aleatoria de acoes: depois de cada uma, o cache de meses e o historico batem com a referencia
    rnd = random.Random(44)
    db = os.path.join(WORK, 'db_t44')
    semear(db, gerar_regs(rnd, 30, CHAVE_HOJE - 6, CHAVE_HOJE))
    app = open_app(db, now=AGORA17)
    backups = []
    for passo in range(220):
        acao = rnd.choice(['lancar', 'lancar', 'excluir', 'editar', 'mes', 'modo', 'busca', 'backup', 'restaurar', 'reabrir', 'apagar'])
        try:
            if acao == 'lancar':
                lancar17(app, rnd.choice(['Entrada', 'Despesa']), rnd.choice(DESCS17), '%d,%02d' % (rnd.randint(1, 999), rnd.randint(0, 99)),
                         rnd.choice(CATS), rnd.choice(PAYS))
            elif acao in ('excluir', 'editar'):
                app.click('BtnNavHistorico')
                n = len(app.comp('ListaHistorico').elements)
                if n:
                    tocar_lista(app, 'ListaHistorico', rnd.randint(1, n))
                    app.answer_dialog('Excluir' if acao == 'excluir' else 'Editar')
                    if acao == 'editar':
                        digitar(app, 'TxtValor', '%d,00' % rnd.randint(1, 500))
                        app.click(rnd.choice(['BtnEntrada', 'BtnDespesa']))
            elif acao == 'mes':
                app.click('BtnNavHistorico')
                app.click(rnd.choice(['BtnPerAnt', 'BtnPerProx']))
            elif acao == 'modo':
                app.click('BtnNavGrafico')
                app.click(rnd.choice(['BtnModoMes', 'BtnModoAno', 'BtnModoTudo']))
            elif acao == 'busca':
                app.click('BtnNavHistorico')
                digitar(app, 'TxtBusca', rnd.choice(['', '', 'pix', 'mercado', 'saude']))
            elif acao == 'backup':
                app.touch('CanvasTopo')
                app.click('BtnBackup')
                backups.append(app.arquivos['Conto_backup_2026-11-12.txt'])
            elif acao == 'restaurar' and backups:
                app.touch('CanvasTopo')
                app.pick_file('content://b/%d' % passo, rnd.choice(backups))
                app.answer_dialog('Restaurar')
            elif acao == 'reabrir':
                app = open_app(db, now=AGORA17)
            elif acao == 'apagar' and rnd.random() < 0.3:
                app.click('BtnNavHistorico')
                app.click('BtnLimpar')
                app.answer_dialog('Apagar tudo')
        except AssertionError as e:
            c.ok(False, 'passo %d (%s): %s' % (passo, acao, e))
            continue
        app.call_by_name('atualizarTudo')
        regs = app.g['lancamentos']
        c.eq(app.g['chavesReg'], [r_chave(r[3]) for r in regs], 'passo %d (%s): cache de meses = datas dos lancamentos' % (passo, acao))
        c.eq(db_lancamentos(db), regs, 'passo %d (%s): memoria = armazenamento' % (passo, acao))
        modo, k = app.g['periodoModo'], app.g['periodoChave']
        pred = {'mes': lambda x: x == k, 'ano': lambda x: x >= 0 and x // 12 == k, 'tudo': lambda x: True}[modo]
        q = sem_acento17(app.text('TxtBusca').strip())
        esperado = [r for r in regs if pred(r_chave(r[3])) and (not q or q in sem_acento17('%s %s %s' % (r[1], r[4], r[5])))]
        c.eq(linhas_hist(app), [r_linha_hist(r) for r in esperado], 'passo %d (%s): historico do periodo/busca' % (passo, acao))
        saldo = sum(r[2] if r[0] == 'Entrada' else -r[2] for r in regs)
        c.eq(app.text('LblSaldo'), ref_brl(saldo), 'passo %d (%s): saldo' % (passo, acao))
    c.eq(app.runtime_errors, [], 'nenhum erro de execucao')


@test('T45', 'TEXTO "true"/"false": o TinyDB devolve como verdadeiro/falso; editar e restaurar continuam salvando (sem falso erro)')
def t45(c):
    db = os.path.join(WORK, 'db_t45')
    semear(db, [['Despesa', 'Café', 500, '12/11/2026 08:00', 'Alimentação', 'Pix'],
                ['Entrada', 'Venda', 1000, '11/11/2026 08:00', 'Outros', 'Pix']])
    app = open_app(db, now=AGORA17)
    for i, desc in enumerate(['True', 'false', 'TRUE', 'falsete', 'true ']):
        app.click('BtnNavHistorico')
        tocar_lista(app, 'ListaHistorico', 1)
        app.answer_dialog('Editar')
        digitar(app, 'TxtDescricao', desc)
        app.click('BtnDespesa')
        c.eq((app.text('LblAviso'), app.g['avisoOk']), ('Lançamento atualizado!', True), 'editar para %r salva (sem falso erro)' % desc)
        c.eq(db_lancamentos(db)[0][1], desc.strip(), 'gravado como texto %r' % desc.strip())
    # ao reabrir, o TinyDB do App Inventor devolve "true"/"false" (qualquer maiuscula) como verdadeiro/falso
    a2 = open_app(db, now=AGORA17)
    c.eq(a2.g['lancamentos'][0][1], True, 'ao reabrir: "true" volta como verdadeiro (comportamento do TinyDB)')
    a2.click('BtnNavHistorico')
    c.eq(linhas_hist(a2)[0][1].split('  ')[0], 'true', 'e aparece como "true" no historico')
    tocar_lista(a2, 'ListaHistorico', 1)
    a2.answer_dialog('Editar')
    digitar(a2, 'TxtValor', '6,00')
    a2.click('BtnDespesa')
    c.eq((a2.text('LblAviso'), a2.g['lancamentos'][0][2]), ('Lançamento atualizado!', 600), 'editar um lancamento cuja descricao voltou como verdadeiro')
    # restaurar backup com descricoes "false"/"True"
    tab = [['Conto-backup', '1', '01/11/2026 10:00'], ['L', 'Despesa', 'false', '100', '05/11/2026 10:00', 'Lazer', 'Pix'],
           ['L', 'Entrada', 'True', '200', '04/11/2026 10:00', 'Outros', 'Pix'], ['Fim', '2']]
    a2.touch('CanvasTopo')
    a2.pick_file('content://t/1', csv_de_tabela(tab))
    a2.answer_dialog('Restaurar')
    c.eq((a2.text('LblDadosMsg'), [r[1] for r in a2.g['lancamentos']]), ('Backup restaurado: 2 lançamentos.', ['false', 'True']),
         'restaurar backup com "false"/"True" funciona')
    c.eq(a2.runtime_errors + app.runtime_errors, [], 'nenhum erro de execucao')


# T20 ("nenhum erro de execucao em nenhum app aberto") passa a rodar POR ULTIMO: assim cobre tambem os apps abertos
# pelos testes da v1.5 em diante (antes ficava no meio da lista e so via os apps dos testes anteriores a ele)
_i20 = [i for i, t in enumerate(TESTS) if t[0] == 'T20'][0]
TESTS.append(TESTS.pop(_i20))
# ============================================================================= fim T36-T44


# ============================================================================= T46-T54 (v1.8 e v1.8.1)
# Colado aqui (antes de main). As referencias abaixo sao escritas a parte dos
# blocos, direto da regra combinada (em Python), e comparadas com o que o app faz na tela.

# ----------------------------------------------------------------------------- v1.8.1: "tem certeza?"
# Excluir um lancamento, salvar uma edicao e remover a foto agora abrem uma janela de confirmacao. Os testes antigos
# (escritos antes dela) respondem essa janela como a pessoa que quer MESMO fazer aquilo -- assim continuam conferindo a
# exclusao/edicao/remocao em si. O T53 desliga isso e confere as duas respostas (confirmar e desistir) e o texto.
import ai_sim as _ai_sim181  # noqa: E402
CONFIRMACOES181 = {'Excluir lançamento?': 'Sim, excluir', 'Salvar alterações?': 'Salvar', 'Remover foto?': 'Remover foto'}
CONFIRMAR_SOZINHO = [True]
CONFIRMADAS181 = []          # titulo de cada janela respondida sozinha (o relatorio diz quantas)
_notifier_call0 = _ai_sim181.Notifier.call


def _notifier_call181(self, method, args):
    r = _notifier_call0(self, method, args)
    p = self.pending
    if method == 'ShowChooseDialog' and CONFIRMAR_SOZINHO[0] and p is not None and p['title'] in CONFIRMACOES181:
        def responder(p=p, n=self):
            if n.pending is p:              # a janela continua aberta: a pessoa toca no botao de confirmar
                CONFIRMADAS181.append(p['title'])
                n.user_choose(CONFIRMACOES181[p['title']])
        self.app.depois(responder)          # depois que o evento atual termina, como um toque de verdade
    return r


_ai_sim181.Notifier.call = _notifier_call181


def seta(app, nome):
    """v1.8.1: a seta e a IMAGEM do botao (o texto '‹'/'›' sumia atras da margem interna do botao no Android).
    Devolve o que a pessoa ve: '‹', '›' ou '' (sem seta = imagem transparente). Imagem do tema errado, texto no botao
    ou imagem desconhecida aparecem no resultado (e a conferencia falha)."""
    b = app.comp(nome)
    texto, img = b.props.get('Text', ''), b.props.get('Image', '') or ''
    if texto != '':
        return 'texto %r' % texto
    im = paleta().IMAGENS
    esc = 1 if app.g.get('temaEscuro') else 0
    return {im['SetaEsq'][esc]: '‹', im['SetaDir'][esc]: '›', im['Nada'][esc]: ''}.get(img, 'imagem %r' % img)


def img_mes_ref(app, m, ficha):
    """Imagem da inicial do mes m que a pessoa deve ver: a ficha da referencia (Marca = mes atual, Dica = ainda vem,
    Suave = os outros) no tema atual. Que a imagem mostra mesmo a letra certa, na cor certa, o T52 confere desenhando."""
    pal = paleta()
    estado = {v: k for k, v in pal.ESTADOS_MES.items()}[ficha]
    return pal.img_mes(pal.LETRAS_MES[m - 1], estado, bool(app.g.get('temaEscuro')))


AGORA18 = datetime.datetime(2026, 11, 12, 21, 0)
HOJE18 = 20261112
NOMES_DESC18 = ['descricao', 'description', 'title', 'titulo', 'historico', 'memo', 'detalhes', 'estabelecimento', 'lancamento']
PALAVRAS18 = [
    ('Compras', ['mercado livre', 'mercadolivre', 'mercadopago', 'mercado pago', 'amazon', 'shopee', 'shein', 'aliexpress',
                 'magalu', 'magazine luiza', 'americanas', 'casas bahia', 'renner', 'riachuelo', 'c&a', 'zara', 'centauro',
                 'netshoes', 'kabum', 'leroy', 'ikea', 'shopping', 'boticario', 'natura', 'sephora', 'havan', ' loja ']),
    ('Alimentação', ['supermerc', 'mercado', 'ifood', 'rappi', 'restaurante', 'padaria', 'panificadora', 'lanch', 'pizza',
                     'burger', 'mcdonald', 'acougue', 'hortifruti', 'sacolao', ' cafe ', 'cafeteria', 'atacad', 'assai',
                     'carrefour', 'pao de acucar', 'ze delivery', 'doceria', 'sorvete', 'emporio', ' feira ']),
    ('Transporte', ['uber', ' 99 ', '99app', '99pop', 'cabify', 'posto', 'combust', 'gasolina', 'etanol', 'shell',
                    'ipiranga', 'petrobras', 'estacion', 'estapar', 'pedagio', 'sem parar', 'conectcar', 'veloe', 'metro',
                    'onibus', 'bilhete unico', 'cptm', 'oficina', 'mecanic', 'ipva', 'detran']),
    ('Moradia', ['aluguel', 'condominio', 'iptu', 'energia', 'enel', 'cemig', 'copel', 'eletropaulo', 'equatorial',
                 'neoenergia', 'celesc', 'sabesp', 'copasa', 'sanepar', 'cedae', 'comgas', 'internet', ' vivo ', ' claro ',
                 ' tim ', 'net servicos', 'imobiliaria', 'quintoandar', 'quinto andar']),
    ('Saúde', ['farmacia', 'drogaria', 'drogasil', 'droga raia', 'pacheco', 'pague menos', 'panvel', 'hospital', 'clinica',
               'medic', 'laborat', 'unimed', 'amil', 'hapvida', 'sulamerica', 'odonto', 'dentist', 'psicolog', 'fisioter',
               'academia', 'smart fit', 'smartfit', 'gympass', 'wellhub', 'totalpass']),
    ('Lazer', ['netflix', 'spotify', 'disney', 'hbo', 'prime video', 'globoplay', 'youtube', 'deezer', 'cinema', 'cinemark',
               'ingresso', 'sympla', 'teatro', 'viagem', 'hotel', 'airbnb', 'booking', 'decolar', 'latam', 'steam',
               'playstation', 'xbox', 'nintendo', ' bar ', 'boteco', 'cervej', 'balada']),
    ('Educação', ['escola', 'colegio', 'faculdade', 'universidade', 'curso', 'udemy', 'alura', 'coursera', 'duolingo',
                  'livraria', 'livro', 'mensalidade', 'papelaria', 'ensino']),
]
NUM_RE18 = re.compile(r'[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$')


def r_jsplit(t, at):
    """String.split(Pattern.quote(at)) com limite 0 (vazios do fim somem)."""
    if at not in t:
        return [t]
    p = t.split(at)
    while p and p[-1] == '':
        p.pop()
    return p


def r_ehnum(t):
    return isinstance(t, (int, float)) or bool(NUM_RE18.match(java_trim(str(t)))) and java_trim(str(t)) == str(t)


def r_campos(linha, sep):
    if '"' not in linha:
        return r_jsplit(linha, sep)
    out, atual, dentro, i = [], '', False, 0
    while i < len(linha):
        c = linha[i]
        if dentro and c == '"':
            if i + 1 < len(linha) and linha[i + 1] == '"':
                atual += '"'
                i += 1
            else:
                dentro = False
        elif dentro:
            atual += c
        elif c == '"':
            dentro = True
        elif c == sep:
            out.append(atual)
            atual = ''
        else:
            atual += c
        i += 1
    out.append(atual)
    return out


def r_norm(t):
    return sem_acento17(java_trim(str(t).replace('﻿', '').replace('"', '')))


def r_dias(m, a):
    return [31, 29 if (a % 4 == 0 and a % 100 != 0) or a % 400 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]


def r_ler_data(texto):
    t = java_trim(str(texto).replace('"', ''))
    hora = '12:00'
    if len(t) >= 11 and t[10] == 'T':
        t = t[:10] + ' ' + t[11:]
    if ' ' in t:
        partes = r_jsplit(t, ' ')
        if len(partes) >= 2:
            hora = java_trim(partes[1])
        if len(hora) >= 5 and hora[2] == ':' and r_ehnum(hora[0:2]) and r_ehnum(hora[3:5]):
            hora = hora[:5]
        else:
            hora = '12:00'
        t = partes[0] if partes else ''
    p = r_jsplit(t.replace('-', '/').replace('.', '/'), '/')
    if len(p) != 3 or not all(r_ehnum(x) and float(x) == round(float(x)) for x in p):
        return ''
    if len(p[0]) == 4:
        a, m, d = (int(float(x)) for x in p)
    else:
        d, m, a = (int(float(x)) for x in p)
    if a < 100:
        a += 2000
    if 1900 <= a <= 2200 and 1 <= m <= 12 and 1 <= d <= r_dias(m, a):
        return '%02d/%02d/%d %s' % (d, m, a, hora)
    return ''


def r_ler_valor(texto):
    t = java_trim(str(texto).replace('"', '').replace('R$', '').replace(' ', '').replace(' ', ''))
    neg = False
    if len(t) >= 2:
        if t[-1] in 'Dd':
            neg, t = True, java_trim(t[:-1])
        elif t[-1] in 'Cc':
            t = java_trim(t[:-1])
    if len(t) >= 3 and t[0] == '(' and t[-1] == ')':
        neg = True
        t = java_trim(java_trim(t[1:])[:-1])
    if len(t) >= 2:
        if t[0] == '-':
            neg, t = not neg, java_trim(t[1:])
        elif t[-1] == '-':
            neg, t = not neg, java_trim(t[:-1])
        elif t[0] == '+':
            t = java_trim(t[1:])
    if ',' in t and '.' in t:
        t = t.replace(',', '') if '.' in r_jsplit(t, ',')[-1] else t.replace('.', '').replace(',', '.')
    elif ',' in t:
        t = t.replace(',', '') if t.count(',') > 1 else t.replace(',', '.')
    elif '.' in t:
        if t.count('.') > 1 or len(r_jsplit(t, '.')[-1]) == 3:
            t = t.replace('.', '')
    if t == '' or not r_ehnum(t):
        return ''
    v = int(round(float(t) * 100))
    return -v if neg else v


def r_categoria(desc):
    d = ' ' + sem_acento17(desc) + ' '
    for cat, ws in PALAVRAS18:
        for w in ws:
            if w in d:
                return cat
    return 'Outros'


def r_pagamento(desc, cartao):
    d = ' ' + sem_acento17(desc) + ' '
    if cartao:
        return 'Cartão de crédito'
    if 'pix' in d:
        return 'Pix'
    if 'debito' in d or 'compra cartao' in d:
        return 'Cartão de débito'
    if 'cartao' in d and 'credito' in d:
        return 'Cartão de crédito'
    if 'saque' in d:
        return 'Dinheiro'
    return 'Transferência bancária'


def r_na_lista(t, lista):
    alvo = r_norm(t)
    for x in lista:
        if sem_acento17(x) == alvo:
            return x
    return ''


def r_chave_imp(r):
    return '%s|%s|%s|%s' % (str(r[3])[:10], r[0], coerce_to_string(r[2]), sem_acento17(str(r[1])))


def r_chave_curta(r):
    """v2.0: dia|tipo|valor (o mesmo gasto pela notificacao e pelo extrato, com descricoes diferentes)."""
    return '%s|%s|%s' % (r[3][:10], r[0], r[2])


def r_extrato(texto, regs, chaves_notif=()):
    """Referencia da importacao: devolve None (sem cabecalho) ou dict com novos (em ordem), repetidos, ruins...
    v2.0: depois da chave completa, um lancamento do app que veio da NOTIFICACAO (chave curta em chaves_notif) tambem
    "gasta" uma linha do extrato com o mesmo dia, tipo e valor (contada em 'notif')."""
    t = texto.replace('\r\n', '\n').replace('\r', '\n')
    linhas = r_jsplit(t, '\n')
    h, col, sep = 0, None, ','
    for n in range(1, min(len(linhas), 20) + 1):
        if h:
            break
        linha = linhas[n - 1]
        sep = ';' if linha.count(';') > 0 and linha.count(';') >= linha.count(',') else ('\t' if linha.count('\t') > linha.count(',') else ',')
        cs = r_campos(linha, sep)
        c = dict(data=0, valor=0, cred=0, deb=0, tipo=0, cat=0, pag=0, desc=0)
        rdesc, title = 99, False
        for k, cel in enumerate(cs, 1):
            nc = r_norm(cel)
            regras = [('data', nc.startswith('data') or nc in ('date', 'dt')),
                      ('valor', (nc.startswith('valor') or nc in ('amount', 'value', 'quantia')) and 'saldo' not in nc),
                      ('cred', nc.startswith('credito') or nc.startswith('entrada') or nc == 'credit'),
                      ('deb', nc.startswith('debito') or nc.startswith('saida') or nc == 'debit'),
                      ('tipo', nc == 'tipo' or nc.startswith('tipo ')),
                      ('cat', nc in ('categoria', 'category')),
                      ('pag', nc == 'pagamento' or nc.startswith('forma de pagamento'))]
            for nome, ok in regras:
                if c[nome] == 0 and ok:
                    c[nome] = k
                    break
            if nc == 'title':
                title = True
            for r, nm in enumerate(NOMES_DESC18, 1):
                if r < rdesc and (nc == nm or nc.startswith(nm)):
                    rdesc, c['desc'] = r, k
        if c['data'] and (c['valor'] or c['cred'] or c['deb']):
            h, col = n, c
            sep_h = sep
            tem_cat = c['cat'] > 0
            cartao = title and c['valor'] > 0 and c['tipo'] == 0
    if not h:
        return None
    sep = sep_h
    pool = '\n' + ''.join(r_chave_imp(r) + '\n' for r in regs)
    pool_n = [r_chave_curta(r) for r in regs if r_chave_curta(r) in chaves_notif]
    res = dict(novos=[], repetidos=0, ruins=0, primeira=0, futuros=0, fatura=0, tem_cat=tem_cat, notif=0)
    for n in range(h + 1, len(linhas) + 1):
        linha = linhas[n - 1]
        if java_trim(linha.replace(';', '').replace(',', '').replace('\t', '')) == '':
            continue
        cs = r_campos(linha, sep)
        cel = lambda i: java_trim(cs[i - 1]) if 0 < i <= len(cs) else ''
        data = r_ler_data(cel(col['data']))
        v = ''
        if col['valor']:
            v = r_ler_valor(cel(col['valor']))
        else:
            if cel(col['cred']) != '':
                v = r_ler_valor(cel(col['cred']))
                if v != '':
                    v = abs(v)
            if (v == '' or v == 0) and cel(col['deb']) != '':
                v = r_ler_valor(cel(col['deb']))
                if v != '':
                    v = -abs(v)
        if data != '' and cel(col['valor']) == '' and cel(col['cred']) == '' and cel(col['deb']) == '':
            continue
        if data == '' or v == '' or v == 0:
            res['ruins'] += 1
            res['primeira'] = res['primeira'] or n
            continue
        if int(data[6:10] + data[3:5] + data[0:2]) > HOJE18:
            res['futuros'] += 1
            continue
        desc = java_trim(cel(col['desc']))
        if len(desc) >= 2 and desc[0] == "'" and desc[1] in '=+-@':
            desc = desc[1:]
        desc = desc or 'Sem descrição'
        desc = desc[:200]
        tipo = ''
        if col['tipo']:
            nc = r_norm(cel(col['tipo']))
            if nc.startswith(('entrada', 'credito', 'receita')) or nc == 'c':
                tipo = 'Entrada'
            elif nc.startswith(('despesa', 'saida', 'debito')) or nc == 'd':
                tipo = 'Despesa'
        if not tipo:
            if cartao:
                tipo = 'Despesa' if v > 0 else ('Entrada' if 'estorno' in sem_acento17(desc) else '')
            else:
                tipo = 'Despesa' if v < 0 else 'Entrada'
        if not tipo:
            res['fatura'] += 1
            continue
        cat = r_na_lista(cel(col['cat']), CATS) if col['cat'] else ''
        cat = cat or ('Outros' if tipo == 'Entrada' else r_categoria(desc))
        pag = r_na_lista(cel(col['pag']), PAYS) if col['pag'] else ''
        pag = pag or r_pagamento(desc, cartao)
        reg = [tipo, desc, abs(v), data, cat, pag]
        ch = '\n' + r_chave_imp(reg) + '\n'
        p = pool.find(ch)
        if p >= 0:
            res['repetidos'] += 1
            pool = pool[:p + 1] + pool[p + len(ch):]
        elif r_chave_curta(reg) in pool_n:
            res['notif'] += 1
            pool_n.remove(r_chave_curta(reg))
        else:
            res['novos'].append(reg)
    novos = res['novos']
    if len(novos) >= 2 and r_ordem(novos[0][3]) < r_ordem(novos[-1][3]):
        novos = novos[::-1]
    res['novos'] = sorted(novos, key=lambda r: -r_ordem(r[3]))
    return res


def r_misturar(a, b):
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        if r_ordem(a[i][3]) >= r_ordem(b[j][3]):
            out.append(a[i])
            i += 1
        else:
            out.append(b[j])
            j += 1
    return out + a[i:] + b[j:]


def r_pl(n, um, varios):
    return '%d%s' % (n, um if n == 1 else varios)


def r_dialogo_import(res):
    nv = res['novos']
    ent = sum(1 for r in nv if r[0] == 'Entrada')
    d_ini, d_fim = nv[-1][3][:10], nv[0][3][:10]
    datas = ('em ' + d_fim) if d_ini == d_fim else 'de %s a %s' % (d_ini, d_fim)
    t = 'Encontrei %s, %s: %s e %s' % (r_pl(len(nv), ' lançamento novo', ' lançamentos novos'), datas,
                                       r_pl(ent, ' entrada', ' entradas'), r_pl(len(nv) - ent, ' despesa.', ' despesas.'))
    if res['repetidos']:
        t += '\n' + r_pl(res['repetidos'], ' já estava no app e será pulado.', ' já estavam no app e serão pulados.')
    if res.get('notif'):
        t += '\n' + r_pl(res['notif'], ' já foi lançado pela notificação do banco e será pulado.',
                         ' já foram lançados pelas notificações do banco e serão pulados.')
    if res['futuros']:
        t += '\n' + r_pl(res['futuros'], ' agendado para depois de hoje fica de fora.', ' agendados para depois de hoje ficam de fora.')
    if res['fatura']:
        t += '\n' + r_pl(res['fatura'], ' pagamento da fatura fica de fora (não é gasto novo).',
                         ' pagamentos da fatura ficam de fora (não são gastos novos).')
    if res['ruins']:
        t += '\n' + r_pl(res['ruins'], ' linha não foi entendida e fica de fora', ' linhas não foram entendidas e ficam de fora') + \
             (' (linha %d).' if res['ruins'] == 1 else ' (a primeira: linha %d).') % res['primeira']
    um = len(nv) == 1
    t += '\n\n' + ('Ele será somado aos que você já tem. ' if um else 'Eles serão somados aos que você já tem. ')
    if res['tem_cat']:
        t += ('A categoria veio do arquivo (ou da descrição, se faltava); dá para corrigir no Histórico.' if um else
              'As categorias vieram do arquivo (ou da descrição, quando faltavam); dá para corrigir no Histórico.')
    else:
        t += ('A categoria foi escolhida pela descrição; dá para corrigir no Histórico.' if um else
              'A categoria de cada um foi escolhida pela descrição; dá para corrigir no Histórico.')
    return html_exibido(t.replace('\n', '<br>'))


def r_msg_sem_novos(res):
    t = 'Não encontrei lançamentos novos neste arquivo.'
    if res['repetidos']:
        t += ' ' + r_pl(res['repetidos'], ' já estava no app.', ' já estavam no app.')
    if res.get('notif'):
        t += ' ' + r_pl(res['notif'], ' já veio pela notificação do banco.', ' já vieram pelas notificações do banco.')
    if res['ruins']:
        t += ' ' + r_pl(res['ruins'], ' linha não foi entendida.', ' linhas não foram entendidas.')
    return t


MSG_SEM_CAB = ('Não reconheci este arquivo. Ele precisa ser uma planilha CSV com colunas de data e valor '
               '(no Excel: Salvar como → CSV).')


def ir_perfil18(app):
    if not app.shown('PickerImportar'):
        app.touch('CanvasTopo')


def importar18(app, conteudo, nome='extrato.csv'):
    """Como a pessoa: abre o perfil, toca em 'Importar extrato do banco' e escolhe o arquivo."""
    ir_perfil18(app)
    app.pick_file('content://docs/' + nome, conteudo, picker='PickerImportar')
    return app.comp('Notifier1').pending


def conferir_importacao(c, app, conteudo, rot, responder='Importar'):
    """Compara dialogo/mensagem e a lista final do app com a referencia."""
    antes = [list(r) for r in app.g['lancamentos']]
    ref = r_extrato(conteudo, antes, list(app.g.get('chavesNotif') or []))
    p = importar18(app, conteudo)
    if ref is None:
        c.eq((p, app.text('LblDadosMsg'), app.g['lancamentos']), (None, MSG_SEM_CAB, antes), rot + ': arquivo sem colunas de data/valor')
        return ref
    if not ref['novos']:
        c.eq((p, app.text('LblDadosMsg'), app.g['lancamentos']), (None, r_msg_sem_novos(ref), antes), rot + ': nada novo')
        return ref
    c.ok(p is not None and p['title'] == 'Importar extrato?' and p['buttons'][:2] == ['Importar', 'Cancelar'],
         rot + ': abre a confirmacao "Importar extrato?"')
    if p is None:
        return ref
    c.eq(p['texto'], r_dialogo_import(ref), rot + ': texto da confirmacao')
    c.eq(app.g['lancamentos'], antes, rot + ': nada muda antes de confirmar')
    app.answer_dialog(responder)
    if responder == 'Importar':
        c.eq(app.g['lancamentos'], r_misturar(antes, ref['novos']), rot + ': lista final (somados, em ordem de data)')
        n = len(ref['novos'])
        c.eq(app.text('LblDadosMsg'), '%s Confira as categorias no Histórico (toque em um lançamento para editar).'
             % r_pl(n, ' lançamento importado.', ' lançamentos importados.'), rot + ': mensagem de sucesso')
    else:
        c.eq((app.g['lancamentos'], app.text('LblDadosMsg')), (antes, 'Importação cancelada. Nada mudou.'), rot + ': cancelar')
    return ref


EXTRATOS18 = {
    'nubank_cartao': 'date,title,amount\n2026-11-03,Ifood *Restaurante,45.90\n2026-11-04,Uber *Trip,23.10\n'
                     '2026-11-05,Pagamento recebido,-500.00\n2026-11-06,"Amazon, Marketplace",129.99\n2026-11-07,Estorno Uber,-23.10\n',
    'nubank_conta': 'Data,Valor,Identificador,Descrição\n01/11/2026,5000.00,abc-1,Transferência recebida - Empresa X\n'
                    '02/11/2026,-120.50,abc-2,Transferência enviada pelo Pix - Fulano\n03/11/2026,-89.90,abc-3,Compra no débito - Drogaria Sao Paulo\n',
    'itau': 'Extrato conta corrente\nAgência 1234 Conta 5678\n\nData;Lançamento;Ag./Origem;Valor (R$);Saldo (R$)\n'
            '05/11/2026;PIX TRANSF JOAO;;-1.250,00;\n06/11/2026;SALARIO;;4.800,00;\n07/11/2026;SUPERMERCADO EXTRA;;-312,45;\n'
            '07/11/2026;SALDO DO DIA;;;3.000,00\n',
    'bb_debito_credito': '"Data","Histórico","Débito","Crédito"\r\n"10/11/2026","Posto Ipiranga","150,00",""\r\n'
                         '"11/11/2026","Pix recebido","0,00","300,00"\r\n"11/11/2026","Tarifa","abc",""\r\n',
    'conto_planilha': '﻿Data;Tipo;Descrição;Categoria;Pagamento;Valor (R$)\r\n12/11/2026 08:10;Despesa;Padaria;Alimentação;Dinheiro;-43,20\r\n'
                      "11/11/2026 20:55;Entrada;Salário;Outros;Transferência bancária;3.000,00\r\n10/11/2026 09:00;Despesa;'=SOMA(1);Outros;Pix;-1,00\r\n",
    'tsv_iso': 'Date\tDescription\tAmount\n2026-10-30T14:22:00\tNetflix.com\t-55,90\n2026-10-31\tSalary\t+7.000,00\n',
    'formatos_valor': 'data;descricao;valor\n1/9/26;Curso Alura;(199,90)\n02/09/2026;Academia Smart Fit;99,90 D\n'
                      '03.09.2026;Reembolso;1,234.56\n04/09/2026;Mercado Livre compra;1.500\n05/09/2026;Aluguel apto;-2.000,00-\n'
                      '31/02/2026;Data impossivel;-10,00\n13/12/2026;Agendado;-50,00\n',
    'repetidos_no_arquivo': 'Data;Descrição;Valor\n12/11/2026;Café;-6,50\n12/11/2026;Café;-6,50\n12/11/2026;Café;-6,50\n',
    'sem_cabecalho': 'oi;tudo bem\n1;2;3\n',
    'xlsx': 'PK\x03\x04\x14\x00\x06\x00\x08\x00garbage',
    'vazio': '',
}


@test('T46', 'IMPORTAR EXTRATO: formatos de bancos e planilhas (colunas pelo nome, datas, valores, cartao, credito/debito)')
def t46(c):
    db = os.path.join(WORK, 'db_t46')
    for nome, conteudo in EXTRATOS18.items():
        semear(db, [['Despesa', 'Café', 650, '12/11/2026 07:30', 'Alimentação', 'Pix']] if nome == 'repetidos_no_arquivo' else [])
        app = open_app(db, now=AGORA18)
        conferir_importacao(c, app, conteudo, nome)
        c.eq(app.runtime_errors, [], nome + ': nenhum erro de execucao')
    # conferencias feitas a mao (independentes da referencia) em casos-chave
    semear(db, [])
    app = open_app(db, now=AGORA18)
    importar18(app, EXTRATOS18['nubank_cartao'])
    app.answer_dialog('Importar')
    c.eq(app.g['lancamentos'], [['Entrada', 'Estorno Uber', 2310, '07/11/2026 12:00', 'Outros', 'Cartão de crédito'],
                                ['Despesa', 'Amazon, Marketplace', 12999, '06/11/2026 12:00', 'Compras', 'Cartão de crédito'],
                                ['Despesa', 'Uber *Trip', 2310, '04/11/2026 12:00', 'Transporte', 'Cartão de crédito'],
                                ['Despesa', 'Ifood *Restaurante', 4590, '03/11/2026 12:00', 'Alimentação', 'Cartão de crédito']],
         'fatura Nubank (conferida a mao): compra = despesa, estorno = entrada, pagamento da fatura fica de fora')
    semear(db, [])
    app = open_app(db, now=AGORA18)
    p = importar18(app, EXTRATOS18['formatos_valor'])
    app.answer_dialog('Importar')
    c.eq(sorted((r[1], r[0], r[2], r[3], r[4]) for r in app.g['lancamentos']),
         sorted([('Curso Alura', 'Despesa', 19990, '01/09/2026 12:00', 'Educação'),
                 ('Academia Smart Fit', 'Despesa', 9990, '02/09/2026 12:00', 'Saúde'),
                 ('Reembolso', 'Entrada', 123456, '03/09/2026 12:00', 'Outros'),
                 ('Mercado Livre compra', 'Entrada', 150000, '04/09/2026 12:00', 'Outros')]),
         'formatos de valor (conferidos a mao): (199,90) e "D" = despesa; 1,234.56; 1.500')
    c.ok('2 linhas não foram entendidas e ficam de fora (a primeira: linha 6).' in p['texto'] and
         '1 agendado para depois de hoje fica de fora.' in p['texto'],
         'valor com dois sinais ("-2.000,00-") e data impossivel (31/02) ficam de fora; data futura avisada')
    # a mesma planilha de novo: nada novo; arquivo com 3 cafes iguais e 1 ja no app -> entram 2
    semear(db, [['Despesa', 'Café', 650, '12/11/2026 07:30', 'Alimentação', 'Pix']])
    app = open_app(db, now=AGORA18)
    importar18(app, EXTRATOS18['repetidos_no_arquivo'])
    app.answer_dialog('Importar')
    c.eq(len(app.g['lancamentos']), 3, '3 cafes iguais no arquivo, 1 ja no app: ficam 3 no total (nao duplica nem perde)')
    importar18(app, EXTRATOS18['repetidos_no_arquivo'])
    c.eq((app.comp('Notifier1').pending, app.text('LblDadosMsg'), len(app.g['lancamentos'])),
         (None, 'Não encontrei lançamentos novos neste arquivo. 3 já estavam no app.', 3), 'importar de novo nao duplica nada')
    c.eq(app.runtime_errors, [], 'nenhum erro de execucao')
    # "repetido" = mesma data, tipo, valor E descricao (sem diferenca de maiuscula/acento): outra descricao no mesmo dia
    # e valor e um lancamento NOVO; "UBER" = "Uber" e "CAFE" = "Café" (conferido a mao)
    semear(db, [['Despesa', 'Uber', 1500, '01/11/2026 08:00', 'Transporte', 'Pix'],
                ['Despesa', 'Café', 650, '02/11/2026 07:30', 'Alimentação', 'Pix']])
    app = open_app(db, now=AGORA18)
    importar18(app, 'Data;Descrição;Valor\n01/11/2026;99 Pop;-15,00\n01/11/2026;UBER;-15,00\n02/11/2026;CAFE;-6,50\n')
    app.answer_dialog('Importar')
    c.eq(sorted(r[1] for r in app.g['lancamentos']), ['99 Pop', 'Café', 'Uber'],
         'mesmo dia e valor com outra descricao entra; UBER = Uber e CAFE = Café ficam de fora (repetidos)')
    # mesma data e hora (12:00) que um lancamento que ja estava: o que ja estava fica em cima (conferido a mao)
    semear(db, [['Despesa', 'Almoço', 3000, '05/11/2026 12:00', 'Alimentação', 'Pix'],
                ['Despesa', 'Padaria', 900, '04/11/2026 08:00', 'Alimentação', 'Pix']])
    app = open_app(db, now=AGORA18)
    importar18(app, 'Data;Descrição;Valor\n06/11/2026;Livro;-50,00\n05/11/2026;Cinema;-40,00\n')
    app.answer_dialog('Importar')
    c.eq([r[1] for r in app.g['lancamentos']], ['Livro', 'Almoço', 'Cinema', 'Padaria'],
         'empate de data e hora: o lancamento que ja estava fica antes do importado')
    # descricao enorme: ficam os 200 primeiros caracteres; "35,00-" (menos no fim) = despesa (conferido a mao)
    semear(db, [])
    app = open_app(db, now=AGORA18)
    longa = 'Compra parcelada ' + 'x' * 240
    importar18(app, 'Data;Descrição;Valor\n05/11/2026;%s;-10,00\n06/11/2026;Tarifa pacote;35,00-\n' % longa)
    app.answer_dialog('Importar')
    c.eq(app.g['lancamentos'], [['Despesa', 'Tarifa pacote', 3500, '06/11/2026 12:00', 'Outros', 'Transferência bancária'],
                                ['Despesa', longa[:200], 1000, '05/11/2026 12:00', 'Outros', 'Transferência bancária']],
         'descricao com mais de 200 caracteres guarda as 200 primeiras; "35,00-" vira despesa de R$ 35,00')
    c.eq(app.runtime_errors, [], 'nenhum erro de execucao (casos a mao)')
    # textos da confirmacao no singular e de onde veio a categoria (conferidos a mao)
    for conteudo, esperado in (
            ('Data;Descrição;Valor\n10/11/2026;Cinema;-40,00\nxx/11/2026;Ruim;-5,00\n',
             'Encontrei 1 lançamento novo, em 10/11/2026: 0 entradas e 1 despesa.<br>1 linha não foi entendida e fica de fora '
             '(linha 3).<br><br>Ele será somado aos que você já tem. A categoria foi escolhida pela descrição; dá para corrigir no Histórico.'),
            ('Data;Descrição;Categoria;Valor\n10/11/2026;Cinema;Lazer;-40,00\n',
             'Encontrei 1 lançamento novo, em 10/11/2026: 0 entradas e 1 despesa.<br><br>Ele será somado aos que você já tem. '
             'A categoria veio do arquivo (ou da descrição, se faltava); dá para corrigir no Histórico.')):
        semear(db, [])
        app = open_app(db, now=AGORA18)
        p = importar18(app, conteudo)
        c.eq(p and p['texto'], html_exibido(esperado), 'texto da confirmacao (singular): %r' % conteudo[:40])
    # abrir o seletor e voltar sem escolher (o Android devolve o erro 4501 do FilePicker): nada de aviso, nada muda
    semear(db, [['Despesa', 'Uber', 1500, '01/11/2026 08:00', 'Transporte', 'Pix']])
    app = open_app(db, now=AGORA18)
    ir_perfil18(app)
    msg0, n0 = app.text('LblDadosMsg'), len(app.alerts)
    app.cancel_pick('PickerImportar')
    c.eq((app.alerts[n0:], app.text('LblDadosMsg'), app.comp('Notifier1').pending, len(app.g['lancamentos'])), ([], msg0, None, 1),
         'cancelar o seletor do extrato: nenhum aviso (nem "No URI returned to FilePicker"), nada muda')


def gerar_extrato(rnd, regs_app):
    """Extrato aleatorio no estilo de varios bancos (separador, nomes de coluna, datas, valores, preambulo, aspas)."""
    sep = rnd.choice([';', ',', '\t'])
    estilo = rnd.choice(['valor', 'credeb', 'tipo', 'cartao'])
    ndata = rnd.choice(['Data', 'DATA', 'Data Lançamento', 'date', 'Dt'])
    ndesc = rnd.choice(['Descrição', 'Histórico', 'Lançamento', 'Detalhes', 'Estabelecimento', 'Memo', 'title' if estilo == 'cartao' else 'Descricao'])
    if estilo == 'cartao':
        cab = ['date', 'title', 'amount']
    elif estilo == 'credeb':
        cab = [ndata, ndesc, rnd.choice(['Débito', 'Saída', 'Debito (R$)']), rnd.choice(['Crédito', 'Entrada', 'Credito (R$)'])]
    elif estilo == 'tipo':
        cab = [ndata, rnd.choice(['Tipo', 'Tipo de transação']), ndesc, rnd.choice(['Valor', 'Valor (R$)', 'amount']), 'Categoria']
    else:
        cab = [ndata, ndesc, rnd.choice(['Valor', 'Valor (R$)', 'Amount', 'Quantia']), rnd.choice(['Saldo', 'Saldo (R$)'])]
    linhas = []
    for _ in range(rnd.randint(0, 3)):
        linhas.append(rnd.choice(['Extrato de conta', 'Agência: 0001', '', 'Período: 01/09/2026 a 30/11/2026', 'Banco X S.A.']))
    q = lambda x: ('"%s"' % x.replace('"', '""')) if (sep in x or '"' in x or rnd.random() < 0.15) else x
    linhas.append(sep.join(q(x) for x in cab))
    descs = ['Mercado Extra', 'UBER *TRIP', 'Pix enviado Maria', 'Netflix', 'Farmácia Pague Menos', 'Salário', 'Aluguel',
             'Padaria Pão Quente', 'Posto Shell', 'Restaurante, bar e cia', 'Compra "especial"', 'Estorno', 'Livraria Cultura',
             'Transferência TED', 'Saque 24h', 'Academia', 'Ifood', 'Pagamento de fatura', 'Amazon', '']
    usados = []
    for _ in range(rnd.randint(0, 25)):
        k = rnd.random()
        if k < 0.1 and regs_app:                 # um lancamento que ja esta no app (repetido)
            r = rnd.choice(regs_app)
            d = r[3][:10]
            desc, cent = r[1], r[2] if r[0] == 'Entrada' else -r[2]
        else:
            dia = datetime.date(2026, 11, 12) - datetime.timedelta(days=rnd.randint(-15, 400))
            d = dia.strftime('%d/%m/%Y')
            desc = rnd.choice(descs)
            cent = rnd.choice([-1, -1, -1, 1]) * rnd.randint(1, 900000)
        if usados and rnd.random() < 0.1:
            d, desc, cent = rnd.choice(usados)    # linha repetida dentro do proprio arquivo
        usados.append((d, desc, cent))
        dd, mm, aa = d[:2], d[3:5], d[6:10]
        fdata = rnd.choice(['{d}/{m}/{a}', '{a}-{m}-{d}', '{d}.{m}.{a}', '{d}/{m}/{a2}', '{di}/{mi}/{a}', '{a}-{m}-{d}T10:15:00',
                            '{d}/{m}/{a} 14:35'])
        sdata = fdata.format(d=dd, m=mm, a=aa, a2=aa[2:], di=str(int(dd)), mi=str(int(mm)))
        if rnd.random() < 0.04:
            sdata = rnd.choice(['', 'ontem', '32/01/2026', '2026/13/01'])
        reais = '%d,%02d' % (abs(cent) // 100, abs(cent) % 100)
        fmt = rnd.choice(['br', 'br_mil', 'us', 'r$'])
        if fmt == 'br_mil' and abs(cent) >= 100000:
            inteiro = '{:,}'.format(abs(cent) // 100).replace(',', '.')
            reais = '%s,%02d' % (inteiro, abs(cent) % 100)
        elif fmt == 'us':
            reais = '%d.%02d' % (abs(cent) // 100, abs(cent) % 100)
        elif fmt == 'r$':
            reais = 'R$ ' + reais
        if rnd.random() < 0.03:
            reais = rnd.choice(['', 'abc', '--', '0,00'])
        if estilo == 'cartao':
            row = [d[6:10] + '-' + d[3:5] + '-' + d[:2], desc, ('-' if cent > 0 else '') + reais.replace(',', '.') if fmt != 'us' else ('-' if cent > 0 else '') + reais]
        elif estilo == 'credeb':
            row = [sdata, desc, reais if cent < 0 else '', reais if cent > 0 else '']
        elif estilo == 'tipo':
            row = [sdata, rnd.choice(['Despesa', 'Saída', 'D']) if cent < 0 else rnd.choice(['Entrada', 'Crédito', 'C']), desc,
                   reais, rnd.choice(['Saúde', 'saude', 'Lazer', 'Xyz', ''])]
        else:
            row = [sdata, desc, ('-' if cent < 0 else '') + reais, rnd.choice(['', '1.000,00'])]
        linhas.append(sep.join(q(x) for x in row))
        if rnd.random() < 0.05:
            linhas.append(sep.join([sdata, 'SALDO DO DIA', '', '']) if estilo != 'cartao' else '')
    fim = rnd.choice(['\n', '\r\n', '\r'])
    return fim.join(linhas) + (fim if rnd.random() < 0.7 else '')


@test('T47', 'IMPORTAR EXTRATO: 120 extratos aleatorios x referencia; repetidos, cancelar e falha ao gravar')
def t47(c):
    rnd = random.Random(47)
    db = os.path.join(WORK, 'db_t47')
    for k in range(120):
        regs = gerar_regs(rnd, rnd.randint(0, 25), CHAVE_HOJE - 14, CHAVE_HOJE)
        semear(db, regs)
        app = open_app(db, now=AGORA18)
        conteudo = gerar_extrato(rnd, [r for r in app.g['lancamentos'] if r_chave(r[3]) >= 0])
        conferir_importacao(c, app, conteudo, 'extrato aleatorio %d' % k, responder=rnd.choice(['Importar', 'Importar', 'Cancelar']))
        c.eq(app.runtime_errors, [], 'extrato aleatorio %d: nenhum erro de execucao' % k)
        # reabrir: o que foi importado ficou gravado
        b = open_app(db, now=AGORA18)
        c.eq(b.g['lancamentos'], app.g['lancamentos'], 'extrato aleatorio %d: gravado (reabrir mostra o mesmo)' % k)
    # falha ao gravar: nada muda e avisa
    semear(db, [['Despesa', 'Antigo', 100, '01/10/2026 10:00', 'Outros', 'Pix']])
    app = open_app(db, now=AGORA18)
    p = importar18(app, EXTRATOS18['itau'])
    app.comp('TinyDB1').drop_writes = True
    app.answer_dialog('Importar')
    c.eq((app.g['lancamentos'], app.text('LblDadosMsg')),
         ([['Despesa', 'Antigo', 100, '01/10/2026 10:00', 'Outros', 'Pix']],
          'Não foi possível importar: o aparelho não deixou gravar. Nada mudou.'), 'falha ao gravar: desfaz e avisa em vermelho')
    c.eq(app.runtime_errors, [], 'nenhum erro de execucao')


# ----------------------------------------------------------------------------- data do lancamento
def lancar18(app, tipo, desc, valor, cat, pag, data=None, repetir=False):
    if not app.shown('PnlLancar'):
        if app.shown('BtnPerfilVoltar'):
            app.click('BtnPerfilVoltar')
        if not app.shown('PnlLancar'):
            app.click('BtnNavLancar')
    if data is not None:
        app.pick_date('PickerData', *data)
    return lancar17(app, tipo, desc, valor, cat, pag, repetir=repetir)


@test('T48', 'DATA DO LANCAMENTO: hoje/ontem/outro dia, nunca depois de hoje, ordem certa, editar a data, repetir desde um mes passado')
def t48(c):
    db = os.path.join(WORK, 'db_t48')
    semear(db, [['Despesa', 'Mercado', 15000, '10/11/2026 09:00', 'Alimentação', 'Pix'],
                ['Despesa', 'Antigo', 1000, '01/09/2026 08:00', 'Outros', 'Pix']])
    app = open_app(db, now=AGORA18)
    c.eq(app.text('PickerData'), 'Hoje, 12/11/2026', 'campo de data comeca em "Hoje"')
    app.pick_date('PickerData', 2026, 11, 11)
    c.eq(app.text('PickerData'), 'Ontem, 11/11/2026', 'ontem')
    app.pick_date('PickerData', 2026, 11, 13)
    c.eq((app.shown('LblErroData'), app.text('LblErroData'), app.text('PickerData')),
         (True, 'A data não pode ser depois de hoje.', 'Ontem, 11/11/2026'), 'depois de hoje: aviso sob o campo e a data nao muda')
    # trocar o tema com o aviso aberto: a borda vermelha do campo de data acompanha (escuro e de volta ao claro)
    for escuro in (True, False):
        app.click('ImgTema')
        c.eq((app.comp('HzCampoData').props.get('Image'), app.shown('LblErroData')),
             (paleta().IMAGENS['CampoSelErro'][1 if escuro else 0], True), 'data com aviso ao trocar o tema (%s)' % ('escuro' if escuro else 'claro'))
    av = lancar17(app, 'Despesa', 'Padaria', '12,00', 'Alimentação', 'Dinheiro')
    c.eq(app.g['lancamentos'][0], ['Despesa', 'Padaria', 1200, '11/11/2026 21:00', 'Alimentação', 'Dinheiro'],
         'lancado em ontem, com a hora de agora')
    c.eq((app.text('PickerData'), app.shown('LblErroData')), ('Hoje, 12/11/2026', False), 'depois de lancar: volta para hoje')
    # app que fica aberto ate o dia seguinte: ao voltar para o Lancar, "Hoje" e o calendario acompanham o dia novo
    app.now = AGORA18 + datetime.timedelta(hours=12)
    app.click('BtnNavHistorico')
    app.click('BtnNavLancar')
    pk = app.comp('PickerData')
    c.eq((app.text('PickerData'), (pk.ano, pk.mes, pk.dia)), ('Hoje, 13/11/2026', (2026, 11, 13)), 'dia seguinte com o app aberto: "Hoje, 13/11/2026"')
    app.now = AGORA18
    app.click('BtnNavHistorico')
    app.click('BtnNavLancar')
    av = lancar18(app, 'Despesa', 'Livro', '50,00', 'Educação', 'Pix', data=(2026, 10, 5))
    c.eq([r[1] for r in app.g['lancamentos']], ['Padaria', 'Mercado', 'Livro', 'Antigo'], 'lancamento de outubro entra no lugar certo (ordem de data)')
    c.eq(app.g['lancamentos'][2][3], '05/10/2026 21:00', 'data escolhida + hora de agora')
    c.eq(app.runtime_errors, [], 'nenhum erro')
    # editar: a data aparece no campo; trocar a data move o lancamento; sem trocar, a data (e hora) ficam
    app.click('BtnNavHistorico')
    app.click('BtnModoTudo')
    idx = [r[1] for r in app.g['lancamentos']].index('Mercado') + 1
    app.call_by_name('iniciarEdicao', idx)
    c.eq(app.text('PickerData'), '10/11/2026', 'editar: o campo mostra a data do lancamento')
    app.type_text('TxtValor', '160,00')
    app.click('BtnDespesa')
    c.eq([r for r in app.g['lancamentos'] if r[1] == 'Mercado'], [['Despesa', 'Mercado', 16000, '10/11/2026 09:00', 'Alimentação', 'Pix']],
         'editar sem trocar a data: data e hora originais')
    idx = [r[1] for r in app.g['lancamentos']].index('Mercado') + 1
    app.call_by_name('iniciarEdicao', idx)
    app.pick_date('PickerData', 2026, 8, 20)
    app.click('BtnDespesa')
    c.eq([r[1] for r in app.g['lancamentos']], ['Padaria', 'Livro', 'Antigo', 'Mercado'], 'editar a data: o lancamento muda de lugar')
    c.eq(app.g['lancamentos'][3][3], '20/08/2026 09:00', 'nova data com a hora original')
    b = open_app(db, now=AGORA18)
    c.eq(b.g['lancamentos'], app.g['lancamentos'], 'gravado (reabrir)')
    # cache de meses acompanha a mudanca de data (filtro do mes de agosto mostra o Mercado)
    b.click('BtnNavHistorico')
    ir_para_mes(b, 2026 * 12 + 7)
    c.eq(len(b.g['mapaHist']), 1, 'agosto: 1 lancamento no historico (o Mercado)')
    # repetir desde um mes passado: ja lanca os meses seguintes ate hoje
    semear(db, [])
    app = open_app(db, now=AGORA18)
    av = lancar18(app, 'Despesa', 'Aluguel', '1.500,00', 'Moradia', 'Pix', data=(2026, 9, 10), repetir=True)
    c.eq(sorted(r[3] for r in app.g['lancamentos']), ['10/09/2026 21:00', '10/10/2026 08:00', '10/11/2026 08:00'],
         'repetir desde setembro: outubro e novembro ja lancados')
    c.eq(av, 'Despesa registrada! Vai se repetir todo dia 10. Os meses seguintes, até hoje, também foram lançados.', 'aviso')
    c.eq(app.g['recorrentes'][0][5:], [10, 2026 * 12 + 10], 'repeticao guarda o dia e o ultimo mes lancado')
    b = open_app(db, now=AGORA18)
    c.eq(len(b.g['lancamentos']), 3, 'reabrir nao duplica')
    # falha ao gravar com data escolhida: volta exatamente como estava
    app = open_app(db, now=AGORA18)
    antes = [list(r) for r in app.g['lancamentos']]
    app.comp('TinyDB1').drop_writes = True
    av = lancar18(app, 'Despesa', 'X', '1,00', 'Outros', 'Pix', data=(2026, 9, 1))
    c.eq((app.g['lancamentos'], av), (antes, 'Não foi possível gravar. Este lançamento não foi salvo.'), 'falha: nada muda')
    # data impossivel guardada (so com um backup editado a mao): editar nao mostra aviso tecnico e mantem a data
    semear(db, [['Despesa', 'Estranho', 500, '31/02/2026 10:00', 'Outros', 'Pix']])
    e = open_app(db, now=AGORA18)
    n0 = len(e.alerts)
    e.call_by_name('iniciarEdicao', 1)
    c.eq((e.alerts[n0:], e.text('PickerData')), ([], '31/02/2026'), 'editar lancamento com data impossivel: sem aviso tecnico')
    e.type_text('TxtValor', '6,00')
    e.click('BtnDespesa')
    c.eq((e.g['lancamentos'], e.alerts[n0:]), ([['Despesa', 'Estranho', 600, '31/02/2026 10:00', 'Outros', 'Pix']], ['Lançamento atualizado!']),
         'salvar a edicao mantem a data como estava (so a faixa verde, nenhum aviso tecnico)')
    c.eq(e.runtime_errors, [], 'data impossivel: nenhum erro de execucao')
    c.eq(app.runtime_errors + b.runtime_errors, [], 'nenhum erro de execucao')


# ----------------------------------------------------------------------------- meta de economia
def r_meta_textos(meta, regs, chave_hoje=CHAVE_HOJE):
    """Referencia do cartao da meta."""
    nome, alvo, prazo, inicio, inicial = meta
    saldo = sum(r[2] if r[0] == 'Entrada' else -r[2] for r in regs)
    guardado = saldo - inicial
    pct = max(0, min(100, (guardado * 100) // alvo))
    out = {'nome': nome, 'guardado': '%s de %s' % (ref_brl(max(0, guardado)), ref_brl(alvo)), 'pct': '%d%%' % pct,
           'mini': '%s  %s  %d%%' % (nome, PONTO, pct)}
    faltam = alvo - guardado
    if guardado >= alvo:
        out['prazo'] = 'Meta alcançada! Você juntou %s.' % ref_brl(guardado)
        out['ritmo'] = ('Parabéns! Toque em Editar para escolher a próxima meta.', 'Bom')
    elif prazo < chave_hoje:
        out['prazo'] = 'O prazo (%s) já passou. Faltaram %s.' % (r_nome_mes(prazo), ref_brl(faltam))
        out['ritmo'] = ('Toque em Editar para escolher um novo prazo.', 'Suave')
    else:
        meses = prazo - chave_hoje + 1
        out['prazo'] = 'Faltam %s até %s: guarde cerca de %s por mês.' % (ref_brl(faltam), r_nome_mes(prazo), ref_brl(-(-faltam // meses)))
        sm = lambda k: sum(r[2] if r[0] == 'Entrada' else -r[2] for r in regs if r_chave(r[3]) == k)
        media = int(round((sm(chave_hoje - 1) + sm(chave_hoje - 2) + sm(chave_hoje - 3)) / 3.0))
        if media > 0:
            chegada = chave_hoje + (-(-faltam // media)) - 1
            out['ritmo'] = ('No ritmo dos últimos 3 meses (%s por mês), você chega lá em %s.' % (ref_brl(media), r_nome_mes(chegada)),
                            'Bom' if chegada <= prazo else 'Alerta')
        elif media < 0:
            out['ritmo'] = ('Nos últimos 3 meses saiu mais do que entrou: nesse ritmo a meta não avança.', 'Alerta')
        else:
            out['ritmo'] = ('Ainda não dá para calcular seu ritmo: faltam lançamentos dos últimos meses.', 'Suave')
    return out, pct


def conferir_meta(c, app, meta, rot):
    ref, pct = r_meta_textos(meta, app.g['lancamentos'])
    cor = norm(app.comp('LblMetaRitmo').props.get('TextColor'))
    nome_cor = ([k for k in ('Bom', 'Alerta', 'Suave') if cor == cor_ficha(app, k)] + [cor])[0]
    got = {'nome': app.text('LblMetaNome'), 'guardado': app.text('LblMetaGuardado'), 'pct': app.text('LblMetaPct'),
           'mini': app.text('LblMetaMini'), 'prazo': app.text('LblMetaPrazo'), 'ritmo': (app.text('LblMetaRitmo'), nome_cor)}
    c.eq(got, ref, rot + ': textos e cor do cartao da meta')
    w = app.comp('BarMeta').props.get('Width')
    larg = -int(w) - 1000 if isinstance(w, int) and w <= -1000 else None
    c.eq((app.comp('BarMeta').visible, larg if pct > 0 else None), (pct > 0, int(round(pct * 86 / 100.0)) if pct > 0 else None),
         rot + ': barra da meta (%d%% de 86%% da tela)' % pct)
    w2 = app.comp('BarMetaMini').props.get('Width')
    larg2 = -int(w2) - 1000 if isinstance(w2, int) and w2 <= -1000 else None
    c.eq((app.text('LblMetaMiniSub'), app.comp('BarMetaMini').visible, larg2 if pct > 0 else None),
         (ref['guardado'], pct > 0, int(round(pct * 50 / 100.0)) if pct > 0 else None), rot + ': cartao pequeno do Lancar (texto e barra)')


@test('T49', 'META DE ECONOMIA: criar (validacao, prazo, saldo atual), progresso e ritmo x referencia, cartao no Lancar, editar, remover')
def t49(c):
    db = os.path.join(WORK, 'db_t49')
    rnd = random.Random(49)
    regs = gerar_regs(rnd, 60, CHAVE_HOJE - 8, CHAVE_HOJE)
    semear(db, regs)
    app = open_app(db, now=AGORA18)
    c.eq((app.shown('PnlMetaMini'), app.g['meta']), (False, []), 'sem meta: nada no Lancar')
    app.click('BtnNavEvolucao')
    c.eq((app.shown('BtnCriarMeta'), app.shown('PnlMetaAtiva'), app.shown('BtnMetaEditar')), (True, False, False), 'sem meta: botao Criar meta')
    app.click('BtnCriarMeta')
    c.eq((app.g['abaAtual'], app.shown('PnlMeta'), app.text('LblMetaPrazoEdit'), app.shown('BtnRemoverMeta')),
         (7, True, 'novembro de 2027', False), 'tela da meta: prazo sugerido = daqui a 12 meses')
    for txt_, msg in (('', 'Informe quanto você quer juntar.'), ('abc', 'Valor inválido. Use vírgula nos centavos: 5.000,00.'),
                      ('0', 'Digite um valor maior que zero.')):
        app.type_text('TxtMetaValor', txt_)
        app.click('BtnSalvarMeta')
        c.eq((app.shown('LblErroMetaValor'), app.text('LblErroMetaValor'), app.g['meta']), (True, msg, []), 'validacao: %r' % txt_)
    for escuro in (True, False):
        app.click('ImgTema')
        c.eq((app.comp('HzCampoMetaValor').props.get('Image'), app.shown('LblErroMetaValor'), app.shown('PnlMeta')),
             (paleta().IMAGENS['CampoErro'][1 if escuro else 0], True, True),
             'valor da meta com aviso ao trocar o tema (%s): borda vermelha continua' % ('escuro' if escuro else 'claro'))
    for _ in range(200):
        app.click('BtnPrazoAnt')
    c.eq((app.g['metaPrazoEdit'], app.comp('BtnPrazoAnt').props.get('Enabled')), (CHAVE_HOJE, False), 'prazo nao vai antes deste mes')
    app.fire('BtnPrazoAnt', 'Click')
    c.eq(app.g['metaPrazoEdit'], CHAVE_HOJE, 'toque a mais em "<" neste mes (segunda protecao): continua neste mes')
    for _ in range(200):
        app.click('BtnPrazoProx')
    c.eq((app.g['metaPrazoEdit'], app.text('LblMetaPrazoEdit'), app.comp('BtnPrazoProx').props.get('Enabled'),
          app.comp('BtnPrazoAnt').props.get('Enabled')), (CHAVE_HOJE + 120, 'novembro de 2036', False, True),
         'prazo vai no maximo 10 anos para frente (seta desliga no limite)')
    # segunda protecao: mesmo que o toque chegasse com o botao desligado (no celular nao chega), o prazo nao passa
    # dos limites (o simulador dispara o evento direto, sem passar pela checagem do botao)
    app.fire('BtnPrazoProx', 'Click')
    c.eq(app.g['metaPrazoEdit'], CHAVE_HOJE + 120, 'toque a mais em ">" no limite de 10 anos: continua no limite')
    for _ in range(117):
        app.click('BtnPrazoAnt')
    app.type_text('TxtMetaNome', '  Viagem  ')
    app.type_text('TxtMetaValor', '5.000,00')
    saldo = sum(r[2] if r[0] == 'Entrada' else -r[2] for r in app.g['lancamentos'])
    app.click('BtnSalvarMeta')
    c.eq(app.g['meta'], ['Viagem', 500000, CHAVE_HOJE + 3, CHAVE_HOJE, saldo], 'meta salva: conta a partir do saldo de hoje')
    c.eq((app.g['abaAtual'], app.shown('PnlMetaAtiva'), app.shown('BtnCriarMeta')), (5, True, False), 'volta para a Evolucao com o cartao')
    conferir_meta(c, app, app.g['meta'], 'recem-criada')
    lancar17(app, 'Entrada', 'Freela', '1.200,00', 'Outros', 'Pix')
    c.eq((app.shown('PnlMetaMini'), app.text('LblMetaMiniSub')), (True, 'R$ 1.200,00 de R$ 5.000,00'), 'cartao pequeno no Lancar')
    app.click('BtnMetaMini')
    c.eq(app.g['abaAtual'], 5, 'tocar em Ver abre a Evolucao')
    conferir_meta(c, app, app.g['meta'], 'depois de uma entrada')
    # editar so o nome (caixa desmarcada): o ponto de partida continua o da criacao (o progresso nao zera)
    c.ok(saldo != 0, 'cenario com saldo diferente de zero (senao a conferencia abaixo nao distinguiria nada)')
    app.click('BtnMetaEditar')
    c.eq((app.text('TxtMetaNome'), app.text('TxtMetaValor'), app.shown('BtnRemoverMeta'), app.comp('ImgMetaSaldo').props.get('Picture')),
         ('Viagem', '5.000,00', True, paleta().IMAGENS['CheckOff'][0]), 'editar: campos preenchidos e caixa desmarcada')
    app.type_text('TxtMetaNome', '')
    app.click('BtnSalvarMeta')
    c.eq(app.g['meta'], ['Minha meta', 500000, CHAVE_HOJE + 3, CHAVE_HOJE, saldo], 'nome vazio vira "Minha meta"; ponto de partida mantido')
    longo = 'Viagem para o Nordeste com a familia toda em julho'
    app.click('BtnMetaEditar')
    app.type_text('TxtMetaNome', longo)
    app.click('BtnSalvarMeta')
    c.eq(app.g['meta'], [longo[:40], 500000, CHAVE_HOJE + 3, CHAVE_HOJE, saldo], 'nome com mais de 40 caracteres: ficam os 40 primeiros')
    app.click('BtnMetaEditar')
    app.type_text('TxtMetaNome', 'Viagem')
    app.click('BtnSalvarMeta')
    # editar: contar o saldo que ja tem
    app.click('BtnMetaEditar')
    c.eq((app.text('TxtMetaNome'), app.text('TxtMetaValor'), app.shown('BtnRemoverMeta')), ('Viagem', '5.000,00', True), 'editar: campos preenchidos')
    app.click('BtnMetaSaldo')
    app.click('BtnSalvarMeta')
    c.eq(app.g['meta'][3:], [CHAVE_HOJE, 0], 'contar o saldo atual: ponto de partida 0 (mantem o inicio)')
    conferir_meta(c, app, app.g['meta'], 'contando o saldo todo')
    b = open_app(db, now=AGORA18)
    c.eq(b.g['meta'], app.g['meta'], 'meta gravada (reabrir)')
    # cenarios aleatorios do cartao (ritmo, prazo passado, alcancada) x referencia
    for k in range(40):
        regs = gerar_regs(rnd, rnd.randint(0, 50), CHAVE_HOJE - 6, CHAVE_HOJE)
        meta = ['Meta %d' % k, rnd.choice([1, 100, 50000, 300000, 2000000]), CHAVE_HOJE + rnd.randint(-3, 24),
                CHAVE_HOJE - rnd.randint(0, 5), rnd.choice([0, 0, rnd.randint(-500000, 500000)])]
        semear(db, regs, extra={'meta': json.dumps(meta)})
        a = open_app(db, now=AGORA18)
        a.click('BtnNavEvolucao')
        conferir_meta(c, a, meta, 'meta aleatoria %d' % k)
        c.eq(a.runtime_errors, [], 'meta aleatoria %d: nenhum erro' % k)
    # exatamente o valor da meta = alcancada (conferido a mao: entrou R$ 500,00 e a meta e de R$ 500,00, contando do zero)
    semear(db, [['Entrada', 'Venda', 50000, '05/11/2026 10:00', 'Outros', 'Pix']],
           extra={'meta': json.dumps(['Exata', 50000, CHAVE_HOJE + 2, CHAVE_HOJE, 0])})
    a = open_app(db, now=AGORA18)
    a.click('BtnNavEvolucao')
    c.eq((a.text('LblMetaPct'), a.text('LblMetaPrazo'), a.text('LblMetaRitmo')),
         ('100%', 'Meta alcançada! Você juntou R$ 500,00.', 'Parabéns! Toque em Editar para escolher a próxima meta.'),
         'exatamente o valor da meta conta como alcancada')
    # guardado invalido no aparelho e ignorado
    for ruim in (['x', 'abc', 1, 1, 0], ['x', 0, 1, 1, 0], ['x', 100], 'oi', ['x', 2.5, 1, 1, 0]):
        semear(db, [], extra={'meta': json.dumps(ruim)})
        a = open_app(db, now=AGORA18)
        c.eq((a.g['meta'], a.runtime_errors), ([], []), 'meta invalida guardada e ignorada: %r' % (ruim,))
    # remover
    semear(db, [], extra={'meta': json.dumps(['Carro', 100000, CHAVE_HOJE + 5, CHAVE_HOJE, 0])})
    a = open_app(db, now=AGORA18)
    a.click('BtnNavEvolucao')
    a.click('BtnMetaEditar')
    a.click('BtnRemoverMeta')
    p = a.comp('Notifier1').pending
    c.eq((p['title'], p['texto'], p['buttons'][:2]), ('Remover meta?', 'A meta “Carro” será removida. Seus lançamentos não mudam.',
                                                       ['Remover meta', 'Cancelar']), 'confirmacao de remover')
    a.answer_dialog('Remover meta')
    c.eq((a.g['meta'], a.g['abaAtual'], a.shown('BtnCriarMeta')), ([], 5, True), 'meta removida')
    c.eq(open_app(db, now=AGORA18).g['meta'], [], 'remocao gravada')
    # falha ao remover: avisa e a meta continua (nada de falso "removida")
    semear(db, [], extra={'meta': json.dumps(['Carro', 100000, CHAVE_HOJE + 5, CHAVE_HOJE, 0])})
    f = open_app(db, now=AGORA18)
    f.click('BtnNavEvolucao')
    f.click('BtnMetaEditar')
    f.click('BtnRemoverMeta')
    f.comp('TinyDB1').drop_writes = True
    f.answer_dialog('Remover meta')
    c.eq((f.g['meta'], [m['texto'] for m in f.message_dialogs]),
         (['Carro', 100000, CHAVE_HOJE + 5, CHAVE_HOJE, 0], ['Erro: não foi possível remover a meta neste aparelho.']),
         'falha ao remover: avisa e a meta continua')
    c.eq(f.runtime_errors, [], 'falha ao remover: nenhum erro de execucao')
    # falha ao gravar a meta: avisa e nao muda
    a.click('BtnCriarMeta')
    a.type_text('TxtMetaValor', '100,00')
    a.comp('TinyDB1').drop_writes = True
    a.click('BtnSalvarMeta')
    c.eq((a.g['meta'], a.text('LblErroMetaValor'), a.g['abaAtual']), ([], 'Não foi possível salvar a meta neste aparelho. Tente de novo.', 7),
         'falha ao gravar: avisa e continua na tela da meta')
    c.eq(app.runtime_errors + a.runtime_errors, [], 'nenhum erro de execucao')


# ----------------------------------------------------------------------------- backup: meta, lembrete, info
@test('T50', 'BACKUP v1.8: meta vai e volta no backup, backup da v1.7 (sem meta) continua valendo, informacao e lembrete')
def t50(c):
    db = os.path.join(WORK, 'db_t50')
    rnd = random.Random(50)
    regs = gerar_regs(rnd, 12, CHAVE_HOJE - 3, CHAVE_HOJE)
    meta = ['Reserva', 300000, CHAVE_HOJE + 6, CHAVE_HOJE - 1, 12345]
    # com menos de 10 lancamentos o lembrete nao aparece (quem esta comecando nao e incomodado)
    db9 = os.path.join(WORK, 'db_t50_nove')
    semear(db9, regs[:9])
    n9 = open_app(db9, now=AGORA18)
    c.eq(n9.shown('BoxAviso'), False, '9 lancamentos e nunca fez backup: sem lembrete')
    semear(db9, regs[:10])
    n10 = open_app(db9, now=AGORA18)
    c.eq(n10.shown('BoxAviso'), True, '10 lancamentos e nunca fez backup: lembrete')
    semear(db, regs, extra={'meta': json.dumps(meta)})
    app = open_app(db, now=AGORA18)
    # 12 lancamentos e nunca fez backup: lembrete ao abrir (uma vez por semana)
    c.eq((app.shown('BoxAviso'), app.text('LblAviso')),
         (True, 'Dica: faça um backup dos seus lançamentos. Toque no ícone do perfil, no topo, e depois em “Fazer backup”.'), 'lembrete ao abrir')
    b = open_app(db, now=AGORA18 + datetime.timedelta(days=3))
    c.eq(b.shown('BoxAviso'), False, 'lembrete nao repete antes de 7 dias')
    b = open_app(db, now=AGORA18 + datetime.timedelta(days=7))
    c.eq(b.shown('BoxAviso'), True, 'lembrete volta depois de 7 dias')
    app.touch('CanvasTopo')
    c.eq(app.text('LblBackupInfo'), 'Você ainda não fez backup.', 'info sem backup')
    app.click('BtnExportar')
    c.eq((app.text('LblBackupInfo'), db_val(db, 'ultimo_backup')), ('Você ainda não fez backup.', None),
         'exportar a planilha NAO conta como backup')
    app.click('BtnBackup')
    nb = [n for n in app.arquivos if n.startswith('Conto_backup_')][-1]
    tabela = tabela_de_csv(app.arquivos[nb])
    c.eq([r for r in tabela if r[0] == 'M'], [['M', 'Reserva', '300000', str(CHAVE_HOJE + 6), str(CHAVE_HOJE - 1), '12345']], 'linha M no backup')
    c.eq(tabela[-1], ['Fim', '12'], 'conferencia continua sendo a ultima linha')
    c.eq(app.text('LblBackupInfo'), 'Último backup: hoje.', 'info: hoje')
    # app que fica aberto: dois dias depois, abrir "Seus dados" mostra a informacao atualizada
    app.now = AGORA18 + datetime.timedelta(days=2)
    app.click('BtnPerfilVoltar')
    app.touch('CanvasTopo')
    c.eq(app.text('LblBackupInfo'), 'Último backup: há 2 dias.', 'app aberto por 2 dias: a informacao se atualiza ao abrir Seus dados')
    app.now = AGORA18
    for dias, texto, cor in ((1, 'Último backup: ontem.', 'Suave'), (12, 'Último backup: há 12 dias.', 'Suave'),
                             (31, 'Último backup: há 31 dias. Que tal fazer um agora?', 'Alerta')):
        a = open_app(db, now=AGORA18 + datetime.timedelta(days=dias))
        c.eq((a.shown('BoxAviso'), a.text('LblAviso') if a.shown('BoxAviso') else ''),
             (True, 'Faz mais de 30 dias do último backup. Toque no ícone do perfil, no topo, e depois em “Fazer backup”.') if dias > 30 else (False, ''),
             'lembrete ao abrir depois de %d dias do backup' % dias)
        a.touch('CanvasTopo')
        c.eq((a.text('LblBackupInfo'), norm(a.comp('LblBackupInfo').props.get('TextColor')) == cor_ficha(a, cor)), (texto, True),
             'info depois de %d dias' % dias)
    a = open_app(db, now=AGORA18 + datetime.timedelta(days=33))
    c.eq(a.shown('BoxAviso'), False, 'lembrete de 30 dias nao repete na mesma semana')
    # "hoje"/"ontem"/"ha N dias" sao dias de CALENDARIO, nao periodos de 24 h (backup feito as 21:00 de 12/11)
    db2 = os.path.join(WORK, 'db_t50_calendario')
    semear(db2, regs)
    k = open_app(db2, now=AGORA18)
    k.touch('CanvasTopo')
    k.click('BtnBackup')
    for quando, texto, lembra in ((datetime.datetime(2026, 11, 12, 23, 59), 'Último backup: hoje.', False),
                                  (datetime.datetime(2026, 11, 13, 8, 0), 'Último backup: ontem.', False),       # 11 h depois
                                  (datetime.datetime(2026, 11, 14, 7, 0), 'Último backup: há 2 dias.', False),   # 34 h depois
                                  (datetime.datetime(2026, 12, 12, 8, 0), 'Último backup: há 30 dias.', False),
                                  (datetime.datetime(2026, 12, 13, 8, 0), 'Último backup: há 31 dias. Que tal fazer um agora?', True)):
        a = open_app(db2, now=quando)
        c.eq(a.shown('BoxAviso'), lembra, 'lembrete ao abrir em %s' % quando.strftime('%d/%m %H:%M'))
        a.touch('CanvasTopo')
        c.eq(a.text('LblBackupInfo'), texto, 'dias de calendario em %s' % quando.strftime('%d/%m %H:%M'))
    # virada de ano: backup 31/12 as 23:00, visto 01/01 as 07:00 = ontem
    k = open_app(db2, now=datetime.datetime(2026, 12, 31, 23, 0))
    k.touch('CanvasTopo')
    k.click('BtnBackup')
    a = open_app(db2, now=datetime.datetime(2027, 1, 1, 7, 0))
    a.touch('CanvasTopo')
    c.eq(a.text('LblBackupInfo'), 'Último backup: ontem.', 'virada de ano: ontem')
    # restaurar: a meta volta
    semear(db, [])
    r = open_app(db, now=AGORA18)
    r.touch('CanvasTopo')
    # antes, no mesmo app aberto, a pessoa comeca a importar um extrato e cancela: o backup continua sendo lido como backup
    importar18(r, EXTRATOS18['itau'])
    r.answer_dialog('Cancelar')
    r.pick_file('content://x/bk', app.arquivos[nb])
    r.answer_dialog('Restaurar')
    c.eq((r.g['meta'], len(r.g['lancamentos'])), (meta, 12), 'restaurar traz a meta')
    c.eq(open_app(db, now=AGORA18).g['meta'], meta, 'meta restaurada gravada')
    # backup feito na v1.7 (sem linha M): restaura e fica sem meta (restaurar substitui tudo)
    v17 = csv_de_tabela([['Conto-backup', '1', '01/10/2026 10:00'], ['L', 'Entrada', 'X', '100', '01/10/2026 10:00', 'Outros', 'Pix'],
                         ['O', '0', '0', '0', '0', '0', '0', '0', '0'], ['P', 'Ana'], ['T', 'claro'], ['Fim', '1']])
    r.pick_file('content://x/bk17', v17)
    p = r.comp('Notifier1').pending
    c.ok(p is not None and p['title'] == 'Restaurar backup?', 'backup da v1.7 abre a confirmacao')
    r.answer_dialog('Restaurar')
    c.eq((r.g['meta'], r.g['lancamentos']), ([], [['Entrada', 'X', 100, '01/10/2026 10:00', 'Outros', 'Pix']]), 'backup da v1.7: sem meta')
    # meta estragada no arquivo e ignorada
    ruim = csv_de_tabela([['Conto-backup', '1', '01/10/2026 10:00'], ['M', 'Z', 'abc', '1', '1', '0'], ['Fim', '0']])
    r.pick_file('content://x/bkm', ruim)
    r.answer_dialog('Restaurar')
    c.eq(r.g['meta'], [], 'linha M invalida e ignorada')
    # cancelar os seletores (Voltar sem escolher arquivo): nenhum aviso e a mensagem que estava continua
    msg0, n0 = r.text('LblDadosMsg'), len(r.alerts)
    r.cancel_pick('PickerRestaurar')
    r.cancel_pick('PickerImportar')
    c.eq((r.alerts[n0:], r.text('LblDadosMsg')), ([], msg0), 'cancelar o seletor do backup ou do extrato: nada de aviso nem de "nao foi possivel"')
    c.eq(app.runtime_errors + r.runtime_errors + a.runtime_errors + b.runtime_errors, [], 'nenhum erro de execucao')


@test('T51', 'TELA v1.8: Seus dados com icones, campo de data, meta; tudo acompanha o tema claro/escuro')
def t51(c):
    db = os.path.join(WORK, 'db_t51')
    semear(db, [], extra={'meta': json.dumps(['Casa', 100000, CHAVE_HOJE + 2, CHAVE_HOJE, 0])})
    app = open_app(db, now=AGORA18)
    linhas = [('Lim', 'BtnLimites2', 'Limites por categoria', 'IcLimites'), ('Imp', 'PickerImportar', 'Importar extrato do banco', 'IcImportar'),
              ('Exp', 'BtnExportar', 'Exportar planilha', 'IcPlanilha'), ('Bkp', 'BtnBackup', 'Fazer backup', 'IcBackup'),
              ('Res', 'PickerRestaurar', 'Restaurar backup', 'IcRestaurar')]
    for escuro in (False, True):
        if escuro:
            app.click('ImgTema')
        imgs = {k: v[1 if escuro else 0] for k, v in paleta().IMAGENS.items()}
        app.touch('CanvasTopo')
        for pref, btn, texto, ic in linhas:
            c.eq((app.shown(btn), app.text(btn), app.comp('ImgDados' + pref).props.get('Picture'),
                  app.comp('ImgSeta' + pref).props.get('Picture'), app.comp('HzDados' + pref).props.get('Image')),
                 (True, texto, imgs[ic], imgs['IcSeta'], imgs['Abas']), 'linha %s (%s)' % (texto, 'escuro' if escuro else 'claro'))
        app.click('BtnPerfilVoltar')
        app.click('BtnNavLancar')
        c.eq((app.shown('PickerData'), app.comp('ImgData').props.get('Picture'), app.comp('HzCampoData').props.get('Image'),
              app.shown('PnlMetaMini'), app.comp('PnlMetaMini').props.get('Image'), app.comp('ImgMetaMini').props.get('Picture')),
             (True, imgs['IcCalendario'], imgs['CampoSel'], True, imgs['CartaoMini'], imgs['IcAlvo']),
             'Lancar: campo de data e cartao da meta (%s)' % ('escuro' if escuro else 'claro'))
        app.click('BtnNavEvolucao')
        c.eq((app.comp('ImgTituloMeta').props.get('Picture'), app.shown('PnlMetaAtiva')), (imgs['IcAlvo'], True), 'Evolucao: cartao da meta')
        app.click('BtnMetaEditar')
        c.eq((app.shown('PnlMeta'), app.shown('PnlLancar'), app.shown('PnlEvolucao'), app.shown('PnlPeriodo'),
              app.comp('ImgMetaSaldo').props.get('Picture')),
             (True, False, False, False, imgs['CheckOn']), 'tela da meta sozinha; caixa marcada (meta conta o saldo todo)')
        app.click('BtnMetaVoltar')
        app.click('BtnNavLancar')
    nos = scm_nos()
    c.eq((nos['PickerImportar'].get('$Type'), nos['PickerImportar'].get('Action', 'Pick Existing File'),
          nos['PickerImportar'].get('MimeType', '*/*')), ('FilePicker', 'Pick Existing File', '*/*'),
         'Importar extrato: seletor de documentos do Android, qualquer tipo de arquivo (cada banco manda o CSV com um tipo)')
    c.eq(app.runtime_errors, [], 'nenhum erro de execucao')


# ============================================================================= v1.8.1: botoes no Android
BOTOES181 = ('Button', 'DatePicker', 'FilePicker', 'ImagePicker', 'ListPicker', 'TimePicker')
ICONES181 = (['BtnPerAnt', 'BtnPerProx', 'BtnEvoAnoAnt', 'BtnEvoAnoProx', 'BtnPrazoAnt', 'BtnPrazoProx', 'BtnLimparBusca']
             + ['BtnMes%d' % i for i in range(1, 13)])
INICIAIS181 = 'JFMAMJJASOND'      # janeiro..dezembro (escrito aqui, sem olhar o gerador)


def moldura181(tipo, img, forma, fundo):
    """Botao que o Android desenha como um QUADRADO VAZIO com sombra (ButtonBase.java): forma padrao (0), fundo
    "nenhum" (&H00FFFFFF) e sem imagem -- o fundo do tema volta com a cor apagada, mas o contorno/sombra continua."""
    return (tipo in BOTOES181 and not img and str('0' if forma is None else forma) == '0'
            and norm(fundo) == '&H00FFFFFF')


def lum181(rgb):
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])


def contraste181(a, b):
    la, lb = sorted((lum181(a), lum181(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def rgb181(cor):
    h = norm(cor)
    return (int(h[4:6], 16), int(h[6:8], 16), int(h[8:10], 16))


def png181(assets, nome):
    from PIL import Image
    return Image.open(io.BytesIO(assets[nome]))


def mascara181(im, lim=128):
    """Mascara (0/255) do desenho recortada no que tem tinta e centrada num quadrado de 48 px (a proporcao da letra
    se mantem). Devolve (mascara, caixa da tinta na imagem original)."""
    from PIL import Image
    a = im if im.mode == 'L' else im.convert('RGBA').getchannel('A')
    b = a.point(lambda v: 255 if v >= lim else 0)
    bb = b.getbbox()
    if not bb:
        return None, None
    rec = b.crop(bb)
    lado = max(rec.size)
    q = Image.new('L', (lado, lado), 0)
    q.paste(rec, ((lado - rec.width) // 2, (lado - rec.height) // 2))
    return q.resize((48, 48), Image.LANCZOS).point(lambda v: 255 if v >= 128 else 0), bb


def iou181(m1, m2):
    p1, p2 = list(m1.getdata()), list(m2.getdata())
    inter = sum(1 for x, y in zip(p1, p2) if x and y)
    uni = sum(1 for x, y in zip(p1, p2) if x or y)
    return inter / float(uni) if uni else 0.0


def tinta181(im):
    """Cor media dos pixels totalmente opacos (o miolo do traco, sem a borda suavizada) e quantos sao."""
    px = [p for p in im.convert('RGBA').getdata() if p[3] >= 250]
    if not px:
        return None, 0
    return tuple(sum(p[i] for p in px) / float(len(px)) for i in range(3)), len(px)


def perto181(a, b, tol=3):
    return a is not None and all(abs(x - y) <= tol for x, y in zip(a, b))


@test('T52', 'BOTÕES NO ANDROID: nenhum botão vira quadrado vazio; setas, × e iniciais dos meses são imagens (desenho, tema e estado certos)')
def t52(c):
    from PIL import Image, ImageDraw, ImageFont
    assets = pacote_assets()
    pal = paleta()
    nos = scm_nos()
    # ---- (1) designer: nenhum botao que o Android desenharia como quadrado vazio; botoes de icone sem texto
    botoes = {n: no for n, no in nos.items() if no.get('$Type') in BOTOES181}
    c.ok(len(botoes) >= 50, '%d botoes (Button e seletores) no designer' % len(botoes))
    c.eq(sorted(n for n, no in botoes.items() if moldura181(no['$Type'], no.get('Image'), no.get('Shape'), no.get('BackgroundColor'))), [],
         'nenhum botao de forma padrao + fundo "nenhum" + sem imagem (no Android: quadrado vazio com sombra)')
    for n in ICONES181:
        no = nos[n]
        img = no.get('Image', '')
        c.eq((no.get('Text', ''), img in assets), ('', True), '%s: sem texto e com imagem que existe no pacote (%s)' % (n, img))
        if img in assets:
            im = png181(assets, img)
            w, h = float(no['Width']), float(no['Height'])
            c.ok(abs(im.width / float(im.height) - w / h) < 0.02,
                 '%s: a figura (%dx%d px) tem o formato do botao (%gx%g dp); o Android estica a imagem ate o botao' % (n, im.width, im.height, w, h))
    c.eq([l.upper() for l in pal.LETRAS_MES], list(INICIAIS181), 'as 12 iniciais (J F M A M J J A S O N D) na ordem dos meses')
    # ---- (2) app rodando: o que a pessoa ve em cada tela, nos dois temas
    db = os.path.join(WORK, 'db_t52')
    rnd = random.Random(52)
    regs = gerar_regs(rnd, 60, CHAVE_HOJE - 16, CHAVE_HOJE)
    semear(db, regs)
    app = open_app(db, now=AGORA18)
    kmin = min(r_chave(r[3]) for r in regs if r_chave(r[3]) >= 0)
    ano_hoje, mes_hoje = CHAVE_HOJE // 12, CHAVE_HOJE % 12 + 1
    c.ok(kmin // 12 < ano_hoje - 1 + 1 and kmin < CHAVE_HOJE - 12, 'cenario com mais de um ano de lancamentos (%d meses)' % (CHAVE_HOJE - kmin))
    vistos = set()
    situacoes = []

    def sem_quadrado(onde):
        ruins = []
        for n, comp in app.comps.items():
            if comp.ctype in BOTOES181 and app.shown(n):
                img = comp.props.get('Image', '') or ''
                vistos.add(n)
                if moldura181(comp.ctype, img, comp.props.get('Shape'), comp.props.get('BackgroundColor')):
                    ruins.append(n)
                elif img and img not in assets:
                    ruins.append('%s (imagem %s nao existe no pacote)' % (n, img))
        situacoes.append(onde)
        c.eq(ruins, [], 'botoes visiveis em %s: nenhum quadrado vazio e toda imagem existe' % onde)

    def iniciais():
        return [(app.text('BtnMes%d' % m), app.comp('BtnMes%d' % m).props.get('Image')) for m in range(1, 13)]

    def iniciais_ref(ano):
        # v1.9: destacada = a do mes escolhido (comeca no mes atual; a seta do ano leva o mesmo mes para o outro ano)
        return [('', img_mes_ref(app, m, 'Marca' if m == mes_hoje else
                                     ('Dica' if (ano == ano_hoje and m > mes_hoje) else 'Suave'))) for m in range(1, 13)]
    cores, fundos = {}, {}
    for escuro in (False, True):
        tema = 'escuro' if escuro else 'claro'
        app.click('BtnNavLancar')
        if escuro:
            app.click('ImgTema')
        c.eq(bool(app.g['temaEscuro']), escuro, 'tema %s' % tema)
        cores[escuro] = {f: rgb181(app.g['cor' + f]) for f in ('Marca', 'Dica', 'Suave')}
        sem_quadrado('Lancar (%s)' % tema)
        # Historico: setas do periodo
        app.click('BtnNavHistorico')
        app.click('BtnModoMes')
        c.eq((seta(app, 'BtnPerAnt'), seta(app, 'BtnPerProx')), ('‹', ''), 'Historico no mes atual: so a seta para tras (%s)' % tema)
        sem_quadrado('Historico (%s)' % tema)
        app.click('BtnPerAnt')
        c.eq((seta(app, 'BtnPerAnt'), seta(app, 'BtnPerProx')), ('‹', '›'), 'um mes antes: as duas setas (%s)' % tema)
        ir_para_mes(app, kmin)
        c.eq((seta(app, 'BtnPerAnt'), seta(app, 'BtnPerProx')), ('', '›'), 'mes mais antigo: so a seta para frente (%s)' % tema)
        app.click('BtnModoAno')                 # o Ano comeca no ano do mes que estava aberto (o mais antigo)
        c.eq((app.g['periodoChave'], seta(app, 'BtnPerAnt'), seta(app, 'BtnPerProx')), (kmin // 12, '', '›'),
             'Ano mais antigo: so a seta para frente (%s)' % tema)
        for _ in range(ano_hoje - kmin // 12):
            app.click('BtnPerProx')
        c.eq((app.g['periodoChave'], seta(app, 'BtnPerAnt'), seta(app, 'BtnPerProx')), (ano_hoje, '‹', ''),
             'Ano de %d: so a seta para tras (%s)' % (ano_hoje, tema))
        app.click('BtnModoTudo')
        c.eq((seta(app, 'BtnPerAnt'), seta(app, 'BtnPerProx')), ('', ''), 'Tudo: sem setas (%s)' % tema)
        sem_quadrado('Historico em Tudo (%s)' % tema)
        app.click('BtnModoMes')
        digitar(app, 'TxtBusca', 'a')
        c.eq((app.shown('BtnLimparBusca'), app.text('BtnLimparBusca'), app.comp('BtnLimparBusca').props.get('Image')),
             (True, '', pal.IMAGENS['Fechar'][1 if escuro else 0]), '"x" da busca: imagem do tema, sem texto (%s)' % tema)
        sem_quadrado('Historico com busca (%s)' % tema)
        app.click('BtnLimparBusca')
        # Grafico: as mesmas setas
        app.click('BtnNavGrafico')
        c.eq((seta(app, 'BtnPerAnt'), seta(app, 'BtnPerProx')), ('‹', ''), 'Grafico no mes atual (%s)' % tema)
        sem_quadrado('Grafico (%s)' % tema)
        # Evolucao: iniciais dos meses e setas do ano
        app.click('BtnNavEvolucao')
        fundos[escuro] = app.comp('CartaoEvoMeses').props.get('Image')
        c.eq(iniciais(), iniciais_ref(ano_hoje), 'Mes a mes de %d: mes atual destacado, meses que ainda vem mais claros (%s)' % (ano_hoje, tema))
        c.eq((seta(app, 'BtnEvoAnoAnt'), seta(app, 'BtnEvoAnoProx')), ('‹', ''), 'setas do ano em %d (%s)' % (ano_hoje, tema))
        sem_quadrado('Evolucao (%s)' % tema)
        app.click('BtnEvoAnoAnt')
        c.eq(iniciais(), iniciais_ref(ano_hoje - 1), 'Mes a mes de %d: o mesmo mes, no ano anterior, destacado (%s)' % (ano_hoje - 1, tema))
        c.eq((seta(app, 'BtnEvoAnoAnt'), seta(app, 'BtnEvoAnoProx')), ('‹' if kmin // 12 < ano_hoje - 1 else '', '›'),
             'setas do ano em %d (%s)' % (ano_hoje - 1, tema))
        app.click('BtnEvoAnoProx')
        # meta: setas do prazo
        app.click('BtnCriarMeta')
        c.eq((seta(app, 'BtnPrazoAnt'), seta(app, 'BtnPrazoProx')), ('‹', '›'), 'prazo sugerido (12 meses): as duas setas (%s)' % tema)
        for _ in range(13):
            app.click('BtnPrazoAnt')
        c.eq((seta(app, 'BtnPrazoAnt'), seta(app, 'BtnPrazoProx')), ('', '›'), 'prazo neste mes: sem seta para tras (%s)' % tema)
        for _ in range(130):
            app.click('BtnPrazoProx')
        c.eq((seta(app, 'BtnPrazoAnt'), seta(app, 'BtnPrazoProx')), ('‹', ''), 'prazo no limite de 10 anos: sem seta para frente (%s)' % tema)
        sem_quadrado('Meta (%s)' % tema)
        app.click('BtnMetaVoltar')
        app.touch('CanvasTopo')
        sem_quadrado('Perfil (%s)' % tema)
        app.click('BtnPerfilVoltar')
    # trocar o tema com a tela aberta: as imagens trocam na hora (aqui o tema volta para o claro e depois para o escuro)
    app.click('BtnNavEvolucao')
    app.click('ImgTema')
    c.eq((bool(app.g['temaEscuro']), iniciais(), seta(app, 'BtnEvoAnoAnt')), (False, iniciais_ref(ano_hoje), '‹'),
         'trocar o tema com a Evolucao aberta: iniciais e seta trocam na hora')
    app.click('BtnNavHistorico')
    app.click('ImgTema')
    c.eq((bool(app.g['temaEscuro']), seta(app, 'BtnPerAnt'), seta(app, 'BtnPerProx')), (True, '‹', ''),
         'trocar o tema com o Historico aberto: setas trocam na hora')
    app.click('BtnNavEvolucao')
    app.click('BtnCriarMeta')
    app.click('ImgTema')
    c.eq((bool(app.g['temaEscuro']), seta(app, 'BtnPrazoAnt'), seta(app, 'BtnPrazoProx')), (False, '‹', '›'),
         'trocar o tema com a tela da meta aberta: setas do prazo trocam na hora')
    app.click('BtnMetaVoltar')
    c.ok(set(ICONES181) <= vistos, 'todos os botoes de icone foram vistos na tela (%d botoes diferentes conferidos)' % len(vistos))
    # ---- (3) as imagens: fundo transparente (sem sombra no Android), desenho certo, cor do tema, contraste
    fonte = ImageFont.truetype(io.BytesIO(assets[pal.F_BOLD]), 220)
    modelos = {}
    for L in sorted(set(INICIAIS181)):
        tela = Image.new('L', (480, 480), 0)
        ImageDraw.Draw(tela).text((240, 240), L, font=fonte, fill=255, anchor='mm')
        modelos[L] = mascara181(tela)[0]

    def transparente_em_volta(im):
        im = im.convert('RGBA')
        w, h = im.size
        return all(im.getpixel(p)[3] == 0 for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)))
    contrastes_letra, contrastes_fig = [], []
    nada = pal.IMAGENS['Nada'][0]
    c.eq((pal.IMAGENS['Nada'][1], png181(assets, nada).mode, max(png181(assets, nada).convert('RGBA').getchannel('A').getdata())),
         (nada, 'RGBA', 0), 'imagem "sem seta" (%s) totalmente transparente nos dois temas' % nada)
    for esc in (False, True):
        tema = 'escuro' if esc else 'claro'
        card = png181(assets, fundos[esc]).convert('RGB')
        cor_card = card.getpixel((card.width // 2, card.height // 2))
        for letra in sorted(set(pal.LETRAS_MES)):
            for estado, ficha in sorted(pal.ESTADOS_MES.items()):
                nome = pal.img_mes(letra, estado, esc)
                im = png181(assets, nome)
                m, bb = mascara181(im)
                notas = sorted(((iou181(m, mod), L) for L, mod in modelos.items()), reverse=True)
                tinta, n = tinta181(im)
                c.ok(im.mode == 'RGBA' and transparente_em_volta(im), '%s: PNG com transparencia em volta' % nome)
                c.ok(notas[0][1] == letra.upper() and notas[0][0] >= 0.80,
                     '%s mostra a letra %s (parecido %.2f; a seguinte, %s, %.2f)' % (nome, letra.upper(), notas[0][0], notas[1][1], notas[1][0]))
                alt = (bb[3] - bb[1]) / float(im.height)
                cy = (bb[1] + bb[3]) / 2.0 / im.height
                c.ok(0.30 <= alt <= 0.75 and abs(cy - 0.5) <= 0.06, '%s: letra com %.0f%% da altura, centrada (%.2f)' % (nome, alt * 100, cy))
                c.ok(perto181(tinta, cores[esc][ficha]), '%s: cor %s = ficha %s do tema %s %s' % (
                    nome, tuple(round(x) for x in tinta) if tinta else None, ficha, tema, cores[esc][ficha]))
                k = contraste181(cores[esc][ficha], cor_card)
                contrastes_letra.append((k, nome))
                c.ok(k >= 4.5, '%s: contraste %.2f:1 sobre o cartao (>= 4,5)' % (nome, k))
        esq, dir_, fechar = (png181(assets, pal.IMAGENS[k][1 if esc else 0]) for k in ('SetaEsq', 'SetaDir', 'Fechar'))
        for nome_k, im in (('SetaEsq', esq), ('SetaDir', dir_), ('Fechar', fechar)):
            c.ok(im.mode == 'RGBA' and transparente_em_volta(im), '%s (%s): PNG com transparencia em volta' % (nome_k, tema))
        c.ok(iou181(mascara181(esq)[0], mascara181(dir_.transpose(Image.FLIP_LEFT_RIGHT))[0]) >= 0.9,
             'seta para frente = espelho da seta para tras (%s)' % tema)
        a = esq.convert('RGBA').getchannel('A')
        cols = [x for x in range(a.width) if any(a.getpixel((x, y)) >= 128 for y in range(a.height))]
        faixa = lambda x: [y for y in range(a.height) if a.getpixel((x, y)) >= 128]
        ponta, bracos = faixa(cols[0] + 1), faixa(cols[-1] - 1)
        c.ok(max(ponta) - min(ponta) < (max(bracos) - min(bracos)) / 3.0,
             'a seta para tras aponta para a esquerda (ponta %d px de altura, bracos %d px) (%s)' % (max(ponta) - min(ponta), max(bracos) - min(bracos), tema))
        mx = mascara181(fechar)[0]
        c.ok(iou181(mx, mx.transpose(Image.FLIP_LEFT_RIGHT)) >= 0.9 and iou181(mx, mx.transpose(Image.FLIP_TOP_BOTTOM)) >= 0.9 and
             fechar.convert('RGBA').getpixel((fechar.width // 2, fechar.height // 2))[3] == 255, '"x" simetrico, com o cruzamento no centro (%s)' % tema)
        for nome_k, im, ficha in (('SetaEsq', esq, 'Marca'), ('SetaDir', dir_, 'Marca'), ('Fechar', fechar, 'Suave')):
            tinta, n = tinta181(im)
            c.ok(perto181(tinta, cores[esc][ficha]) and n > 50, '%s: cor da ficha %s do tema %s (%s)' % (nome_k, ficha, tema, tinta))
            k = contraste181(cores[esc][ficha], cor_card)
            contrastes_fig.append((k, '%s (%s)' % (nome_k, tema)))
            c.ok(k >= 3.0, '%s: contraste %.2f:1 sobre o cartao (>= 3, figura) (%s)' % (nome_k, k, tema))
    c.note('%d botoes no designer, nenhum que o Android desenhe como quadrado vazio; na tela, %d botoes diferentes vistos em '
           '%d situacoes (Lancar, Historico, busca, Grafico, Evolucao, meta, perfil), nos dois temas' % (len(botoes), len(vistos), len(situacoes)))
    c.note('desenho conferido: %d imagens de iniciais (letra certa, centrada, cor do estado e do tema), setas e "x" dos dois temas; '
           'menor contraste das iniciais %.2f:1 (%s); das setas e do "x" %.2f:1 (%s)' % (
               len(contrastes_letra), min(contrastes_letra)[0], min(contrastes_letra)[1], min(contrastes_fig)[0], min(contrastes_fig)[1]))
    c.eq(app.runtime_errors, [], 'nenhum erro de execucao')


@test('T53', 'TEM CERTEZA?: excluir, salvar edição e remover foto perguntam antes; Cancelar/Voltar não muda nada; lançar novo não pergunta')
def t53(c):
    CONFIRMAR_SOZINHO[0] = False      # aqui quem responde a janela e o teste
    try:
        _t53(c)
    finally:
        CONFIRMAR_SOZINHO[0] = True
    c.note('nos outros testes, %d janelas de confirmacao foram respondidas com o "sim" (%s)' % (
        len(CONFIRMADAS181), ', '.join('%s %d' % (t, CONFIRMADAS181.count(t)) for t in sorted(set(CONFIRMADAS181)))))


def _t53(c):
    db = os.path.join(WORK, 'db_t53')
    regs = [['Despesa', 'Mercado <Extra> & cia', 25090, '12/11/2026 08:00', 'Alimentação', 'Cartão de crédito'],
            ['Entrada', 'Salário', 500000, '05/11/2026 09:00', 'Outros', 'Pix'],
            ['Despesa', 'Conta antiga', 9900, '15/09/2026 10:00', 'Moradia', 'Pix'],
            ['Despesa', 'Uber', 3640, '01/09/2026 23:00', 'Transporte', 'Pix']]
    semear(db, regs)
    app = open_app(db, now=AGORA18)
    pend = lambda: app.comp('Notifier1').pending
    janela = lambda: (lambda p: (p['title'], p['buttons'], p['cancelable']) if p else None)(pend())
    app.click('BtnNavHistorico')
    app.click('BtnModoTudo')
    # ---- excluir: pergunta antes; "Cancelar" nao muda nada
    tocar_lista(app, 'ListaHistorico', 1)
    app.answer_dialog('Excluir')
    c.eq(janela(), ('Excluir lançamento?', ['Sim, excluir', 'Cancelar'], False),
         '"Excluir" abre a confirmacao (2 botoes; tocar fora da janela nao fecha)')
    c.eq(pend()['texto'], '“Mercado <Extra> & cia”\n− R$ 250,90 • 12/11/2026\n\nIsso não pode ser desfeito.',
         'a confirmacao diz qual lancamento vai sair (o texto digitado aparece como foi digitado)')
    c.eq((app.g['lancamentos'], db_lancamentos(db)), (regs, regs), 'so de abrir a confirmacao nada muda (memoria e armazenamento)')
    n_al, n_md = len(app.alerts), len(app.message_dialogs)
    app.answer_dialog('Cancelar')
    c.eq((pend(), app.g['lancamentos'], db_lancamentos(db), len(hist(app)), app.alerts[n_al:], app.message_dialogs[n_md:]),
         (None, regs, regs, 4, [], []), '"Cancelar": nada muda e nada de aviso')
    # ---- "Sim, excluir" apaga exatamente o tocado
    tocar_lista(app, 'ListaHistorico', 2)
    app.answer_dialog('Excluir')
    c.eq(pend()['texto'].split('\n')[:2], ['“Salário”', '+ R$ 5.000,00 • 05/11/2026'], 'confirmacao de uma entrada (sinal +)')
    app.answer_dialog('Sim, excluir')
    sobra = [regs[0], regs[2], regs[3]]
    c.eq((pend(), app.g['lancamentos'], db_lancamentos(db), len(hist(app))), (None, sobra, sobra, 3),
         '"Sim, excluir": sai exatamente o lancamento tocado, gravado no armazenamento')
    # resposta com indice invalido (seguranca): nada muda, nada quebra
    for ruim in (0, 99, -3):
        app.g['indiceSel'] = ruim
        app.fire('Notifier1', 'AfterChoosing', 'Sim, excluir')
        app.fire('Notifier1', 'AfterChoosing', 'Excluir')
        c.eq((app.g['lancamentos'], pend()), (sobra, None), 'indice invalido %d: nem exclui nem abre janela' % ruim)
    # ---- editar: "Salvar" pergunta; "Voltar" continua editando sem gravar
    tocar_lista(app, 'ListaHistorico', 1)
    app.answer_dialog('Editar')
    digitar(app, 'TxtValor', '99,99')
    app.click('BtnCategoria')
    app.pick_option('Lazer')
    app.click('BtnDespesa')
    c.eq(janela(), ('Salvar alterações?', ['Salvar', 'Voltar'], False), 'salvar a edicao abre a confirmacao')
    c.eq(pend()['texto'], '“Mercado <Extra> & cia”\n− R$ 99,99 • Lazer\nCartão de crédito • 12/11/2026',
         'a confirmacao mostra como o lancamento vai ficar (descricao, valor, categoria, pagamento e data)')
    c.eq((app.g['lancamentos'], db_lancamentos(db), app.g['editIndice']), (sobra, sobra, 1), 'antes da resposta nada foi gravado')
    app.answer_dialog('Voltar')
    c.eq((pend(), app.g['lancamentos'], db_lancamentos(db), app.g['editIndice'], app.text('TxtValor'), app.text('BtnCategoria'),
          app.text('LblTituloLancar')), (None, sobra, sobra, 1, '99,99', 'Lazer', 'Editar lançamento'),
         '"Voltar": nada gravado; continua editando com o que foi digitado')
    app.click('BtnDespesa')
    app.answer_dialog('Salvar')
    novo = ['Despesa', 'Mercado <Extra> & cia', 9999, '12/11/2026 08:00', 'Lazer', 'Cartão de crédito']
    c.eq((pend(), app.g['lancamentos'][0], db_lancamentos(db)[0], app.text('LblAviso'), app.g['editIndice'], app.g['edicaoConfirmada'],
          app.text('LblTituloLancar')), (None, novo, novo, 'Lançamento atualizado!', 0, False, 'Novo lançamento'),
         '"Salvar": grava a edicao, avisa e sai da edicao')
    # trocar o tipo e a data na edicao: a janela mostra o novo tipo e a nova data
    app.click('BtnNavHistorico')
    tocar_lista(app, 'ListaHistorico', 2)                      # Conta antiga (15/09)
    app.answer_dialog('Editar')
    app.pick_date('PickerData', 2026, 10, 3)
    app.click('BtnEntrada')
    c.eq(pend()['texto'], '“Conta antiga”\n+ R$ 99,00 • Moradia\nPix • 03/10/2026', 'confirmacao com o tipo e a data novos')
    app.answer_dialog('Salvar')
    c.ok(['Entrada', 'Conta antiga', 9900, '03/10/2026 10:00', 'Moradia', 'Pix'] in app.g['lancamentos'],
         'salvo como entrada em 03/10/2026 (a hora do lancamento se mantem)')
    # v1.8.1 (achado pela confirmacao): editar um lancamento de outro dia e escolher HOJE no calendario muda a data
    app.click('BtnNavHistorico')
    i_uber = [i for i, r in enumerate(app.g['lancamentos'], 1) if r[1] == 'Uber'][0]
    app.click('BtnModoTudo')
    tocar_lista(app, 'ListaHistorico', app.g['mapaHist'].index(i_uber) + 1)
    app.answer_dialog('Editar')
    app.pick_date('PickerData', 2026, 11, 12)
    c.eq(app.text('PickerData'), 'Hoje, 12/11/2026', 'campo de data mostra hoje')
    app.click('BtnDespesa')
    c.eq(pend()['texto'].split('\n')[-1], 'Pix • 12/11/2026', 'a confirmacao mostra a data escolhida (hoje)')
    app.answer_dialog('Salvar')
    c.eq(app.g['lancamentos'][0], ['Despesa', 'Uber', 3640, '12/11/2026 23:00', 'Transporte', 'Pix'],
         'editar para HOJE: a data muda (antes da v1.8.1 continuava 01/09/2026) e o lancamento vai para o topo')
    c.eq(db_lancamentos(db), app.g['lancamentos'], 'gravado')
    # erro de validacao na edicao: nem chega a perguntar
    app.click('BtnNavHistorico')
    tocar_lista(app, 'ListaHistorico', 1)
    app.answer_dialog('Editar')
    antes = [list(r) for r in app.g['lancamentos']]
    digitar(app, 'TxtValor', '')
    app.click('BtnDespesa')
    c.eq((pend(), app.comp('LblErroValor').visible, app.g['lancamentos']), (None, True, antes), 'valor vazio na edicao: erro no campo, sem janela')
    app.click('BtnCancelarEdicao')
    # um "Salvar" fora de uma edicao (seguranca) nao cria lancamento com o que estiver no formulario
    preencher(app, 'fantasma', '1,00', 'Lazer', 'Pix')
    app.g['tipoEdicaoPendente'] = 'Despesa'
    app.fire('Notifier1', 'AfterChoosing', 'Salvar')
    c.eq((app.g['lancamentos'], app.g['edicaoConfirmada']), (antes, False), '"Salvar" sem edicao em andamento: nada acontece')
    # lancar um NOVO lancamento nao pergunta (so a edicao pergunta)
    aviso = lancar17(app, 'Despesa', 'Padaria', '8,50', 'Alimentação', 'Dinheiro')
    c.eq((pend(), [r for r in app.g['lancamentos'] if r[1] == 'Padaria'], aviso, len(app.g['lancamentos'])),
         (None, [['Despesa', 'Padaria', 850, '12/11/2026 21:00', 'Alimentação', 'Dinheiro']], 'Despesa registrada!', len(antes) + 1),
         'lancamento novo: grava direto, sem janela')
    # ---- remover foto: pergunta antes
    app.touch('CanvasTopo')
    app.pick_image(os.path.join(FOTOS, 'retrato.jpg'))
    foto = app.g['perfilFoto']
    c.ok(foto.endswith('retrato.jpg') and app.shown('BtnRemoverFoto') and db_val(db, 'perfil_foto') == foto, 'foto escolhida e guardada')
    app.click('BtnRemoverFoto')
    c.eq(janela(), ('Remover foto?', ['Remover foto', 'Cancelar'], False), '"Remover foto" abre a confirmacao')
    c.eq(pend()['texto'], 'A foto sai do seu perfil no Contô. Nenhuma foto é apagada do celular.', 'texto da confirmacao')
    c.eq((app.g['perfilFoto'], db_val(db, 'perfil_foto')), (foto, foto), 'so de abrir a confirmacao a foto continua')
    app.answer_dialog('Cancelar')
    c.eq((pend(), app.g['perfilFoto'], app.comp('SprFotoTopo').visible, db_val(db, 'perfil_foto')), (None, foto, True, foto), '"Cancelar": a foto fica')
    app.click('BtnRemoverFoto')
    app.answer_dialog('Remover foto')
    c.eq((pend(), app.g['perfilFoto'], app.comp('SprFotoTopo').visible, app.comp('BtnRemoverFoto').visible, db_val(db, 'perfil_foto')),
         (None, '', False, False, ''), '"Remover foto": volta ao avatar padrao e grava')
    c.eq(app.runtime_errors, [], 'nenhum erro de execucao')


@test('T54', 'TEXTO DOS BOTÕES CABE no Android (margem interna do tema): prévias em 360, 393 e 600 dp, fonte 100% e 115%')
def t54(c):
    import preview_sim
    import render_scm
    saida = os.environ.get('PREVIEW_DIR') or os.path.join(SP, 'render', 'final')
    os.makedirs(saida, exist_ok=True)
    # as previas do T27 servem se forem DESTE pacote (mesmo .scm, mesmos blocos); senao desenha de novo
    reaproveita = False
    try:
        with zipfile.ZipFile(AIA) as z:
            base_z = [n for n in z.namelist() if n.endswith('Screen1.scm')][0][:-len('Screen1.scm')]
            reaproveita = os.path.exists(os.path.join(saida, 'botoes.json')) and all(
                open(os.path.join(saida, '_pacote', base_z + n), 'rb').read() == z.read(base_z + n) for n in ('Screen1.scm', 'Screen1.bky'))
    except (OSError, IndexError):
        reaproveita = False
    if not reaproveita:
        preview_sim.main(AIA, saida, rects=True)
    c.note('previas %s em %s' % ('do T27 reaproveitadas' if reaproveita else 'desenhadas agora', saida))
    base = json.load(open(os.path.join(saida, 'botoes.json'), encoding='utf-8'))
    estados = json.load(open(os.path.join(saida, 'estados.json'), encoding='utf-8'))
    cenas = sorted(n for n in estados if 'escuro' not in n)     # o tema escuro tem a mesma geometria e os mesmos textos

    def problemas(por_cena):
        out = []
        for cena, bs in sorted(por_cena.items()):
            for nome, m in sorted(bs.items()):
                if m['moldura']:
                    out.append('%s em %s: quadrado vazio' % (nome, cena))
                if m['texto_txt'] and m['texto'][1] > m['caixa'][1] + 0.25:
                    out.append('%s em %s: %r cortado (%.1f dp a mais que a caixa; %d linhas)' % (
                        nome, cena, m['texto_txt'], m['texto'][1] - m['caixa'][1], m['linhas']))
        return out

    def folga(por_cena):
        f = [(m['caixa'][1] - m['texto'][1], nome) for bs in por_cena.values() for nome, m in bs.items() if m['texto_txt']]
        return min(f) if f else (None, None)
    n_bot = sum(len(bs) for bs in base.values())
    c.ok(len(base) >= 35 and n_bot >= 300, '%d previas com %d botoes medidos' % (len(base), n_bot))
    c.eq(problemas(base), [], 'previas em 393 dp, fonte 100%: nenhum texto de botao cortado, nenhum quadrado vazio')
    duas = sorted(set('%s %r' % (n, m['texto_txt']) for bs in base.values() for n, m in bs.items() if m['linhas'] > 1))
    c.eq(duas, [], 'em 393 dp com fonte 100% todo texto de botao fica numa linha so')
    exigidas = [(360, 1.0), (600, 1.0), (393, 1.15), (600, 1.15)]
    so_nota = [(360, 1.15), (393, 1.3), (600, 1.3)]
    var = preview_sim.redesenhar(saida, cenas, exigidas + so_nota)
    f0 = folga(base)
    c.note('393 dp, fonte 100%%: menor sobra vertical %.1f dp (%s)' % f0)
    for larg, esc in exigidas:
        ch = '%d_%.2f' % (larg, esc)
        c.eq(problemas(var[ch]), [], 'previas em %d dp com fonte %d%%: nenhum texto de botao cortado' % (larg, round(esc * 100)))
        c.note('%d dp, fonte %d%%: menor sobra vertical %.1f dp (%s)' % ((larg, round(esc * 100)) + folga(var[ch])))
    for larg, esc in so_nota:
        p = problemas(var['%d_%.2f' % (larg, esc)])
        quais = sorted(set(x.split(' em ')[0] for x in p))
        c.note('LIMITE (so registro) %d dp com fonte %d%%: %s' % (larg, round(esc * 100), ', '.join(quais) if quais else 'nada cortado'))
    # autoteste: o mesmo renderizador PEGA o defeito das fotos da v1.8 (iniciais e setas como texto em botao pequeno)
    e = estados['evolucao']
    st = dict(e['state'])
    for m, letra in enumerate(INICIAIS181, 1):
        st.update({'BtnMes%d.Text' % m: letra, 'BtnMes%d.Image' % m: '', 'BtnMes%d.BackgroundColor' % m: '&H00FFFFFF',
                   'BtnMes%d.Shape' % m: '0', 'BtnMes%d.FontSize' % m: '12.5'})
    st.update({'BtnEvoAnoAnt.Text': '‹', 'BtnEvoAnoAnt.Image': '', 'BtnEvoAnoAnt.BackgroundColor': '&H00FFFFFF', 'BtnEvoAnoAnt.Shape': '0',
               'BtnEvoAnoAnt.FontSize': '22', 'BtnEvoAnoAnt.Width': '40', 'BtnEvoAnoAnt.Height': '40'})
    pk = os.path.join(saida, '_pacote', 'src', 'appinventor', 'ai_conto', 'Conto', 'Screen1.scm')
    _, bt = render_scm.render(pk, os.path.join(saida, '_pacote', 'assets'), os.path.join(saida, 'autoteste_v18.png'), tab=e['tab'],
                              state=st, full_height=True, report_botoes=True)
    pegos = sorted(set(x.split(' em ')[0] for x in problemas({'autoteste': bt})))
    c.eq(pegos, sorted(['BtnMes%d' % m for m in range(1, 13)] + ['BtnEvoAnoAnt']),
         'autoteste: com as iniciais e a seta como TEXTO (como na v1.8) o renderizador acusa quadrado vazio e texto cortado nos 13 botoes')
# ============================================================================= fim T46-T54


# T20 ("nenhum erro de execucao em nenhum app aberto") continua sendo o ULTIMO (cobre tambem os testes da v1.8 e v1.8.1)
_i20b = [i for i, t in enumerate(TESTS) if t[0] == 'T20'][0]
TESTS.append(TESTS.pop(_i20b))


# ============================================================================= v1.9 (testes_novos19.py)
# Colado aqui. Uma funcao com o MESMO nome de uma funcao da bateria a substitui
# no lugar (a v1.9 mudou o Grafico, a Evolucao e a foto do perfil: os testes T21, T31, T32 e T41 e os ajudantes da
# lista de categorias e da Evolucao foram reescritos); as outras entram antes de main(). As referencias calculam o
# esperado direto dos lancamentos, em Python, sem olhar os blocos.

ROSCA_CAIXA = (13, 13, 119, 119)       # oval do traco: meia espessura (26 / 2) para dentro da borda do Canvas de 132 dp


def hexcor(h):
    """'#2F6FDB' -> '&HFF2F6FDB' (a forma de norm)."""
    return '&HFF' + h.lstrip('#').upper()


def r_totais_cat(regs, pred):
    """Gasto (centavos) de cada categoria, na ordem da lista, dos lancamentos cujo mes passa em pred(chave);
    categoria desconhecida (dado antigo) conta como Outros."""
    tot = [0] * 8
    for r in regs:
        if r[0] != 'Entrada' and pred(r_chave(r[3])):
            tot[CATS.index(r[4]) if r[4] in CATS else 7] += r[2]
    return tot


def r_rosca(tot, escuro):
    """Referencia da rosca: arcos [(inicio, varredura, cor)] em graus, como o Canvas do Android desenha (0 = 3 horas,
    sentido do relogio). As fatias saem do alto (-90), da maior categoria para a menor (empate: ordem da lista); cada
    fatia ocupa 360 * gasto / total graus, dos quais min(2, fatia / 3) ficam de vao (metade antes, metade depois),
    sem vao quando ha uma fatia so; cor FIXA da categoria no tema. Sem despesa: anel inteiro na cor do trilho."""
    pal = paleta()
    k = 1 if escuro else 0
    total = sum(tot)
    if total <= 0:
        return [(0.0, 360.0, hexcor(pal.CORES['Trilho'][k]))]
    cats = sorted([i for i in range(8) if tot[i] > 0], key=lambda i: (-tot[i], i))
    out, ini = [], -90.0
    for i in cats:
        fatia = tot[i] * 360.0 / total
        vao = min(2.0, fatia / 3.0) if len(cats) > 1 else 0.0
        out.append((ini + vao / 2, fatia - vao, hexcor(pal.CORES_CAT[i][k])))
        ini += fatia
    return out


def rosca_vista(app):
    """O que a rosca mostra DEPOIS de o ClockRosca desenhar (o tempo passa ate o relogio desligar sozinho).
    Devolve (arcos, ticks, problemas); problemas = tudo o que foge do anel prometido: arco fora da caixa, espessura,
    preenchimento, desenho feito antes de a tela medir o Canvas (sai esticado) ou relogio que nao desliga."""
    ticks = app.esperar_rosca()
    prob = []
    if ticks < 0:
        prob.append('o ClockRosca nunca desliga')
    if app.comp('ClockRosca').get_prop('TimerEnabled'):
        prob.append('o ClockRosca continua ligado')
    arcos = []
    for op in app.comp('CanvasRosca').ops:
        if op.get('tipo') != 'arco':
            prob.append('desenho que nao e arco: %r' % (op,))
            continue
        if tuple(op['caixa']) != ROSCA_CAIXA:
            prob.append('arco na caixa %r' % (op['caixa'],))
        if op['largura'] != 26.0:
            prob.append('espessura %r' % op['largura'])
        if op['centro'] or op['preencher'] or op['apaga']:
            prob.append('arco com centro, preenchido ou apagando')
        if op['esticado']:
            prob.append('arco desenhado antes de a tela medir o Canvas (sai esticado no aparelho)')
        arcos.append((op['ini'], op['varre'], '&H%08X' % op['cor']))
    return arcos, ticks, prob


def arcos_iguais(a, b, tol=1e-6):
    return len(a) == len(b) and all(abs(x[0] - y[0]) <= tol and abs(x[1] - y[1]) <= tol and x[2] == y[2] for x, y in zip(a, b))


def fmt_arcos(arcos):
    return [('%.5f' % a, '%.5f' % b, cor) for a, b, cor in arcos]


def ponto_ref(app, nome_cat):
    """Bolinha (imagem) da categoria no tema atual do app."""
    return paleta().img_ponto_cat(CATS.index(nome_cat) + 1, bool(app.g.get('temaEscuro')))






# ============================================================================= T21 rosca


# ============================================================================= T31 um cartao so


# ============================================================================= T32 lista de categorias


# ============================================================================= T41 Evolucao enxuta






def tela_evolucao_cmp(app):
    """Como tela_evolucao, mas sem as comparacoes quando as linhas estao escondidas (mes sem lancamento: o que esta
    nelas nao aparece para a pessoa)."""
    t = tela_evolucao(app)
    if not t['visiveis'][0]:
        t['comp_desp'] = t['comp_ent'] = None
    return t


def ref_cmp(app, ref):
    r = ref_na_tela(app, ref)
    if not ref['visiveis'][0]:
        r['comp_desp'] = r['comp_ent'] = None
    return r




# ============================================================================= T56 camera
@test('T56', 'FOTO PELA CÂMERA (pedido do usuário): "Tirar foto" e "Escolher da galeria"; tocar na foto oferece as duas; permissão negada e falhas viram mensagem no cartão')
def t56(c):
    pal = paleta()
    nos = scm_nos()
    filhos = lambda n: [ch['$Name'] for ch in nos[n].get('$Components', [])]
    c.eq((nos['CameraFoto'].get('$Type'), sorted(k for k in nos['CameraFoto'] if not k.startswith('$'))), ('Camera', ['Uuid']),
         'componente Camera (nao visivel), sem propriedades de designer')
    c.eq([n for n in filhos('ColFoto') if not n.startswith('Esp')], ['BtnTirarFoto', 'PickerFoto', 'BtnRemoverFoto'],
         'ao lado da foto: Tirar foto, Escolher da galeria e Remover foto')
    c.eq((nos['BtnTirarFoto'].get('Text'), nos['BtnTirarFoto'].get('Image'), nos['PickerFoto'].get('Text'), nos['PickerFoto'].get('Image')),
         ('Tirar foto', 'aba_ativa.png', 'Escolher da galeria', 'pilula_contorno.png'),
         '"Tirar foto" em destaque; "Escolher da galeria" em pilula com contorno')
    db = fresh('t56')
    app = open_app(db)
    app.touch('CanvasTopo')
    cam = app.comp('CameraFoto')
    foto = 'file://' + os.path.join(FOTOS, 'retrato.jpg')
    # 1) tirar foto: a camera abre; a foto tirada vira a foto do perfil, guardada no aparelho
    app.click('BtnTirarFoto')
    c.eq((cam.aberta, cam.aberturas), (True, 1), '"Tirar foto" abre a camera do celular')
    app.camera_tirar(foto)
    c.eq((app.g['perfilFoto'], db_val(db, 'perfil_foto')), (foto, foto), 'a foto tirada vira a foto do perfil e fica guardada')
    for spr, lado in (('SprFotoPerfil', 96), ('SprFotoTopo', 40)):
        s = app.comp(spr)
        x, y, w, h = s.caixa()
        C = 3 * lado
        c.eq((s.visible, s.picture, min(w, h)), (True, foto, lado), '%s mostra a foto da camera cobrindo o circulo' % spr)
        c.ok(abs(w / h - 900 / 1200.0) < 0.03 and abs((x + w / 2) - C / 2) <= 0.5 and abs((y + h / 2) - C / 2) <= 0.5,
             '%s: sem deformar e centralizada' % spr)
    c.eq((app.comp('BtnRemoverFoto').visible, app.comp('LblPerfilMsg').visible), (True, False), '"Remover foto" aparece; nenhuma mensagem')
    a2 = open_app(db)
    c.eq((a2.g['perfilFoto'], a2.comp('SprFotoTopo').visible), (foto, True), 'reabrindo: a foto da camera continua')
    # 2) tocar na foto: escolher entre camera e galeria (e Cancelar)
    app.touch('CanvasPerfil')
    d = app.dialogs[-1]
    c.eq((d['title'], d['buttons'], d['texto']),
         ('Foto do perfil', ['Tirar foto', 'Escolher da galeria', 'Cancelar'], 'Tire uma foto agora com a câmera ou escolha uma da galeria.'),
         'tocar na foto: janela "Foto do perfil" com as duas opcoes e Cancelar')
    app.answer_dialog('Tirar foto')
    c.eq(cam.aberta, True, '"Tirar foto" da janela abre a camera')
    app.camera_voltar()
    c.eq((app.g['perfilFoto'], app.comp('LblPerfilMsg').visible), (foto, False), 'voltar da camera sem tirar: nada muda, sem mensagem')
    app.touch('CanvasPerfil')
    app.answer_dialog('Escolher da galeria')
    c.eq((app.galeria_aberta, cam.aberta), (['PickerFoto'], False), '"Escolher da galeria" abre a galeria (e nao a camera)')
    app.touch('CanvasPerfil')
    app.answer_dialog('Cancelar')
    c.eq((app.galeria_aberta, cam.aberta, app.g['perfilFoto']), (['PickerFoto'], False, foto), 'Cancelar nao abre nada e nao muda a foto')
    # 3) permissao negada e camera sem foto: mensagem no cartao (vermelha), nada de aviso preto, foto mantida
    alertas = len(app.alerts)
    app.click('BtnTirarFoto')
    app.camera_negar()
    c.eq((app.comp('LblPerfilMsg').visible, app.text('LblPerfilMsg'), norm(app.comp('LblPerfilMsg').props['TextColor'])),
         (True, 'Sem permissão para usar a câmera. Você pode liberar a câmera para o Contô nas configurações do celular ou escolher uma foto da galeria.',
          cor_ficha(app, 'Perigo')), 'permissao negada: frase explicando, em vermelho, no cartao do perfil')
    c.eq((len(app.alerts), app.g['perfilFoto'], app.erros_componente[-1][2]), (alertas, foto, 908),
         'nenhum aviso preto do App Inventor (erro 908 tratado); a foto continua')
    app.click('BtnTirarFoto')
    app.camera_sem_foto()
    c.eq((app.text('LblPerfilMsg'), len(app.alerts), app.erros_componente[-1][2]),
         ('Não foi possível usar a foto da câmera. Tente de novo ou escolha uma foto da galeria.', alertas, 201),
         'camera sem foto (erro 201): frase no cartao, sem aviso preto')
    foto2 = 'file://' + os.path.join(FOTOS, 'paisagem.jpg')
    app.click('BtnTirarFoto')
    app.camera_tirar(foto2)
    c.eq((app.g['perfilFoto'], app.comp('LblPerfilMsg').visible), (foto2, False), 'a proxima foto tirada esconde a mensagem de erro')
    s = app.comp('SprFotoPerfil')
    x, y, w, h = s.caixa()
    c.ok(min(w, h) == 96 and abs(w / h - 1600 / 900.0) < 0.03, 'foto deitada (paisagem) cobre o circulo sem deformar')
    # 4) falha ao guardar no aparelho: avisa (nao finge que guardou)
    app.comp('TinyDB1').drop_writes = True
    app.click('BtnTirarFoto')
    app.camera_tirar(foto)
    c.eq(app.message_dialogs[-1]['message'], 'Erro: não foi possível guardar a foto neste aparelho.', 'falha ao guardar: aviso de erro')
    app.comp('TinyDB1').drop_writes = False
    # 5) remover a foto (da camera) pergunta antes e nao apaga nada do celular
    app.click('BtnRemoverFoto')              # a janela "Remover foto?" e respondida com "Remover foto" (v1.8.1)
    c.eq((app.dialogs[-1]['title'], app.dialogs[-1]['texto']),
         ('Remover foto?', 'A foto sai do seu perfil no Contô. Nenhuma foto é apagada do celular.'), 'texto da confirmacao')
    c.eq((app.g['perfilFoto'], app.comp('SprFotoTopo').visible, os.path.exists(os.path.join(FOTOS, 'retrato.jpg'))), ('', False, True),
         'removida do perfil; o arquivo continua no celular')
    # 6) tema escuro: "Escolher da galeria" acompanha (pilula e texto do escuro)
    app.click('BtnTemaEscuro')
    c.eq((app.comp('PickerFoto').props.get('Image'), norm(app.comp('PickerFoto').props.get('TextColor'))),
         (pal.IMAGENS['PilulaSec'][1], norm(pal.aia(pal.D_INK))), '"Escolher da galeria" no tema escuro')
    app.click('BtnTemaClaro')
    c.eq((app.comp('PickerFoto').props.get('Image'), norm(app.comp('PickerFoto').props.get('TextColor'))),
         (pal.IMAGENS['PilulaSec'][0], norm(pal.aia(pal.INK))), '... e de volta ao claro')
    c.clean(app)
    c.clean(a2)


# ============================================================================= T57 abas enxutas
@test('T57', 'ABAS ENXUTAS (pedido do usuário): Gráfico com 1 cartão e Evolução com 2; altura das abas medida nas prévias, v1.8.1 x v1.9')
def t57(c):
    nos = scm_nos()
    cartoes = lambda p: [ch['$Name'] for ch in nos[p].get('$Components', []) if ch['$Name'].startswith('Cartao')]
    c.eq(cartoes('PnlGrafico'), ['CartaoGrafico'], 'Grafico: 1 cartao (eram 3)')
    c.eq(cartoes('PnlEvolucao'), ['CartaoMeta', 'CartaoEvoMeses'], 'Evolucao: 2 cartoes (eram 5)')
    c.eq(cartoes('PnlPerfil'), ['CartaoPerfil', 'CartaoRecorrentes', 'CartaoDados'], 'Perfil: os mesmos 3 cartoes (escolha do usuario)')
    saida = os.environ.get('PREVIEW_DIR') or os.path.join(SP, 'render', 'final')
    agora = json.load(open(os.path.join(saida, 'rects.json')))
    antes = json.load(open(os.path.join(SP, 'final181', 'previas', 'rects.json')))
    TELA = 873.0                 # altura util da tela de referencia (dp) das previas
    for cena, painel, max_telas in (('grafico', 'PnlGrafico', 1.5), ('evolucao_meta', 'PnlEvolucao', 1.5), ('perfil', 'PnlPerfil', 2.1)):
        x, y, w, h = agora[cena][painel]
        xa, ya, wa, ha = antes[cena][painel]
        fim, fim_a = (y + h) / TELA, (ya + ha) / TELA
        c.ok(fim <= max_telas, '%s: a aba termina em %.1f telas (limite %.1f)' % (cena, fim, max_telas))
        if painel != 'PnlPerfil':
            c.ok(h <= 0.6 * ha, '%s: a aba ficou pelo menos 40%% mais curta (%.0f dp -> %.0f dp)' % (cena, ha, h))
        c.note('%-14s v1.8.1: %4.0f dp (%.1f telas)  ->  v1.9: %4.0f dp (%.1f telas)' % (cena, ha, fim_a, h, fim))


# T20 ("nenhum erro de execucao em nenhum app aberto") continua sendo o ULTIMO (cobre tambem os testes da v1.9)
_i20c = [i for i, t in enumerate(TESTS) if t[0] == 'T20'][0]
TESTS.append(TESTS.pop(_i20c))


# ============================================================================= v2.0: notificacoes do banco
# Testes da v2.0 (colados aqui, antes de main()).
#  T58 extensao LeitorNotificacoes: o .aix dentro do pacote, as regras em Java rodando de verdade (JVM) e o simulador
#      comparado com elas;
#  T59 interpretar mensagens do banco (texto -> tipo, valor, descricao), com resultado escrito a mao e referencia;
#  T60 notificacoes no app: acesso, lista, lancar/ignorar, repetidos, lancar todos, colar mensagem, reabrir, falhas;
#  T61 duplicidade na importacao de extrato (pedido do usuario), inclusive com o que veio das notificacoes.
import subprocess as _sp20

EXT20 = os.path.join(SP, 'ext')
JSON_JAR20 = os.path.join(SP, 'ai2src', 'repo', 'appinventor', 'lib', 'json', 'json.jar')
AGORA20 = datetime.datetime(2026, 11, 16, 20, 0)
AGORA61 = datetime.datetime(2026, 11, 12, 20, 0)      # o "hoje" das referencias do extrato (HOJE18)


def ms20(dt):
    return int((dt - datetime.datetime(1970, 1, 1)).total_seconds() * 1000)


def abrir20(db):
    return open_app(db, now=AGORA20)


def notif_estado(db):
    try:
        return json.load(open(os.path.join(db, 'conto_notificacoes.json'), encoding='utf-8'))
    except Exception:
        return None


def ir_notif(app):
    """Como a pessoa: abre o perfil (icone do topo) e toca em 'Lancamentos das notificacoes'."""
    if not app.shown('BtnNotificacoes'):
        app.touch('CanvasTopo')
    app.click('BtnNotificacoes')


# --------------------------------------------------------------------- referencia do interpretador (escrita a parte)
R_ESTORNO = ['estorn', 'cancelad', 'reembols', 'devolvid', 'devolucao']
R_DESPESA = ['compra', 'pagamento de', 'pagamento realizado', 'pagamento efetuado', 'pagamento aprovado', 'pix enviado',
             'voce enviou', 'voce pagou', 'transferencia enviada', 'transferencia realizada', 'transferencia efetuada',
             'saque', 'debito automatico', 'debitad', 'fatura paga']
R_ENTRADA = ['recebeu', 'recebido', 'recebida', 'recebimento', 'cashback', 'deposito', 'depositad', 'creditad',
             'credito em conta', 'salario', 'rendimento', 'caiu na sua conta', 'chegou um pix', 'entrou na sua conta']


def r_valor_msg(t):
    """Valor em centavos logo depois de R$ (ou BRL), ou None. Quebras de linha e espaco duro contam como espaco."""
    n = sem_acento17(t.replace('\r', ' ').replace('\n', ' ').replace('\u00a0', ' ').strip())
    for marca in ('r$', 'brl'):
        p = n.find(marca)
        if p >= 0:
            break
    else:
        return None
    i = p + len(marca)
    while i < len(n) and n[i] in ' -+':
        i += 1
    j = i
    while j < len(n) and n[j] in '0123456789.,':
        j += 1
    num_ = n[i:j].rstrip('.,')
    if not num_:
        return None
    v = r_ler_valor(num_)
    return None if v == '' or v == 0 else abs(v)


def r_tipo_msg(t):
    n = sem_acento17(t)
    if any(w in n for w in R_ESTORNO):
        return 'Entrada'
    if any(w in n for w in R_DESPESA):
        return 'Despesa'
    if any(w in n for w in R_ENTRADA):
        return 'Entrada'
    return 'Despesa'


def interpretar(app, texto):
    """Chama o procedimento dos blocos (como o app faz) e devolve a lista que ele devolveu."""
    return app.call_by_name('interpretarMensagem', texto)


# ============================================================================= T58
@test('T58', 'EXTENSÃO "Leitor de Notificações": o .aix vai dentro do projeto, as regras em Java rodam de verdade e o simulador faz igual')
def t58(c):
    # o que vai DENTRO do .aia testado (lido do proprio pacote)
    import io as _io
    import zipfile as _zf
    ext = {n[len('external_comps/com.conto.notificacoes/'):]: b for n, b in pacote_assets().items()
           if n.startswith('external_comps/com.conto.notificacoes/')}
    for f in ('components.json', 'component.json', 'classes.jar', 'extension.properties', 'files/AndroidRuntime.jar',
              'files/component_build_infos.json', 'files/component_build_info.json'):
        c.ok(f in ext, 'pacote traz assets/external_comps/com.conto.notificacoes/' + f)
    d = json.loads(ext['components.json'].decode('utf-8'))
    c.eq(len(d), 1, 'uma extensao, um componente')
    d = d[0]
    c.eq((d['name'], d['type'], d['external'], d['nonVisible'], d['androidMinSdk'], d['version']),
         ('LeitorNotificacoes', 'com.conto.notificacoes.LeitorNotificacoes', 'true', 'true', '21', '1'),
         'componente externo, nao visivel, Android 5.0+ (EXTRA_BIG_TEXT)')
    c.eq(sorted(m['name'] for m in d['methods']),
         ['AbrirConfiguracaoDeAcesso', 'AbrirInformacoesDoApp', 'AcessoLiberado', 'Diagnostico', 'LeitorConectado',
          'LimparTudo', 'NomeDoApp', 'Pendentes', 'QuantidadePendente', 'Reconectar', 'Remover'],
         'metodos da extensao (v2.0.1: Reconectar, LeitorConectado, Diagnostico)')
    c.eq(d.get('versionName'), '1.1', 'extensao 1.1')
    c.eq({e['name']: [p['name'] for p in e['params']] for e in d['events']},
         {'Erro': ['mensagem'], 'NotificacaoRecebida': ['id', 'app', 'nomeDoApp', 'titulo', 'texto']}, 'eventos e parametros')
    c.eq(sorted((p['name'], p['editorType'], p['defaultValue']) for p in d['properties']),
         [('ApenasComValor', 'boolean', 'True'), ('AppsIgnorados', 'textArea',
           'com.whatsapp,com.whatsapp.w4b,org.telegram.messenger,com.instagram.android,com.facebook.orca,com.facebook.katana,'
           'com.google.android.gm,com.microsoft.office.outlook,com.discord,com.snapchat.android,com.twitter.android,'
           'com.zhiliaoapp.musically,com.linkedin.android'), ('AppsMonitorados', 'textArea', '')],
         'propriedades de designer: so com valor (R$); apps de conversa/e-mail ignorados; demais apps todos')
    bi = json.loads(ext['files/component_build_infos.json'].decode('utf-8'))[0]
    srv = bi['services'][0]
    c.ok('android:name="com.conto.notificacoes.ServicoNotificacoes"' in srv
         and 'android:permission="android.permission.BIND_NOTIFICATION_LISTENER_SERVICE"' in srv
         and 'android:exported="true"' in srv
         and '<action android:name="android.service.notification.NotificationListenerService"/>' in srv,
         'manifesto: servico com a permissao BIND_NOTIFICATION_LISTENER_SERVICE e o intent-filter do NotificationListenerService')
    c.eq(bi['permissions'], [], 'nenhuma permissao "perigosa" pedida (o acesso e liberado pela pessoa nas configuracoes)')
    with _zf.ZipFile(_io.BytesIO(ext['files/AndroidRuntime.jar'])) as z:
        cls = sorted(n for n in z.namelist() if n.endswith('.class'))
    c.eq(cls, ['com/conto/notificacoes/Armazem.class', 'com/conto/notificacoes/LeitorNotificacoes$1.class',
               'com/conto/notificacoes/LeitorNotificacoes.class', 'com/conto/notificacoes/Regras.class',
               'com/conto/notificacoes/ServicoNotificacoes.class'], 'classes compiladas da extensao')
    with _zf.ZipFile(_io.BytesIO(ext['classes.jar'])) as z:
        dex = z.read('classes.dex')
    c.ok(dex[:4] == b'dex\n' and all(n.encode() in dex for n in ('Lcom/conto/notificacoes/Regras;',
                                                                  'Lcom/conto/notificacoes/ServicoNotificacoes;',
                                                                  'Lcom/conto/notificacoes/LeitorNotificacoes;')),
         'classes.jar = dex do Android (d8) com as classes da extensao')
    # o .scm usa a extensao como componente; o .aix gerado agora e o mesmo que esta no pacote
    nos = scm_nos()
    c.eq((nos['LeitorNotificacoes1']['$Type'], nos['LeitorNotificacoes1']['$Version']), ('LeitorNotificacoes', '1'),
         'LeitorNotificacoes1 na tela, versao 1')
    for f in ('components.json', 'classes.jar', 'files/AndroidRuntime.jar'):
        c.ok(ext[f] == open(os.path.join(EXT20, 'extcomp', 'com.conto.notificacoes', f), 'rb').read(),
             'o pacote leva a extensao compilada agora (%s, byte a byte)' % f)
    # as regras em Java (Regras.java, o mesmo arquivo da extensao) rodando na JVM
    tb = os.path.join(WORK, 't58_bin')
    shutil.rmtree(tb, ignore_errors=True)
    os.makedirs(tb)
    r = _sp20.run(['javac', '-nowarn', '-encoding', 'UTF-8', '-d', tb, '-cp', JSON_JAR20,
                   os.path.join(EXT20, 'src', 'com', 'conto', 'notificacoes', 'Regras.java'),
                   os.path.join(EXT20, 'teste', 'com', 'conto', 'notificacoes', 'TesteRegras.java')], capture_output=True, text=True)
    c.eq(r.returncode, 0, 'TesteRegras.java compila com o Regras.java da extensao')
    # casos aleatorios: o Java decide (guardar? id?) e o simulador tem de decidir igual
    rnd = random.Random(58)
    apps = ['com.nu.production', 'com.itau', 'com.whatsapp', 'com.google.android.apps.messaging', 'br.com.intermedium']
    titulos = ['Compra aprovada', 'Pix recebido', 'Nubank', '', 'Código', 'Ação']
    textos = ['Compra de R$ 45,90 em MERCADO', 'Você recebeu R$ 10,00', 'Use 123 para entrar', 'BRL 5.00 at STORE',
              'te devo 10 reais', 'surreais', 'R$ 1.000,00 é seu limite', 'Pagamento de R$ 99,99 — ação €', 'ação: R$ 1,00 😀']
    casos = []
    t0 = ms20(AGORA20)
    for i in range(600):
        if casos and rnd.random() < 0.25:        # v2.0.1: a MESMA notificacao relida da barra (leitor religado)
            a_, ti_, tx_, q_, _ = rnd.choice(casos)
            casos.append((a_, ti_, tx_, q_, rnd.choice('01')))
        else:
            casos.append((rnd.choice(apps), rnd.choice(titulos), rnd.choice(textos),
                          t0 + rnd.choice([0, 1, 2, 5, 9, 10, 11, 30]) * 60000 + i, rnd.choice('001')))
    arq = os.path.join(WORK, 't58_casos.tsv')
    with open(arq, 'w', encoding='utf-8') as f:
        for a, ti, tx, q, tratar in casos:
            f.write('%s\t%s\t%s\t%d\t%s\n' % (a, ti, tx, q, tratar))
    saida = os.path.join(WORK, 't58_saida.tsv')
    r = _sp20.run(['java', '-cp', tb + os.pathsep + JSON_JAR20, 'com.conto.notificacoes.TesteRegras', arq, saida],
                  capture_output=True, text=True)
    linhas_java = [l for l in r.stdout.splitlines() if l.startswith('TESTE DAS REGRAS')]
    c.eq((r.returncode, linhas_java[-1:] and linhas_java[-1].endswith(' 0 falhas')), (0, True),
         'regras da extensao na JVM: ' + (linhas_java[-1] if linhas_java else r.stderr[-200:]))
    java = [l.split('\t') for l in open(saida, encoding='utf-8').read().splitlines()]
    from ai_sim import LeitorNotificacoes as _LN
    lista, vistos = [], []
    sim = []
    for a, ti, tx, q, tratar in casos:
        motivo = _LN.filtro(a, 'appinventor.ai_conto.Conto', '', _LN.IGNORADOS, False, ti, tx, True)
        idn = None
        if motivo is None:
            motivo, idn = _LN.guardar_se_nova(lista, vistos, a, ti, tx, q)
        if idn is not None and tratar == '1':
            lista = [o for o in lista if o['id'] != idn]
        sim.append([motivo, idn or 'null'])
    dif = [(i, casos[i], java[i], sim[i]) for i in range(len(casos)) if java[i] != sim[i]]
    c.eq((len(java), dif[:3]), (len(casos), []),
         '%d notificacoes (com releituras da barra): o simulador decide o motivo e o id IGUAL ao Java' % len(casos))
    motivos = sorted(set(m for m, _ in sim))
    c.ok({'guardada', 'já guardada antes', 'repetida', 'app ignorado', 'sem valor em R$'} <= set(motivos),
         'os casos passam por todos os motivos: %s' % motivos)
    c.note('%d notificacoes aleatorias decididas igual pelo Regras.java (JVM) e pelo simulador (%d guardadas; motivos: %s)'
           % (len(casos), sum(1 for s_ in sim if s_[1] != 'null'), ', '.join(motivos)))


# ============================================================================= T59
CASOS59 = [
    # (titulo, texto, esperado [tipo, valor, descricao])
    ('Compra aprovada', 'Compra de R$ 45,90 APROVADA em MERCADO EXTRA para o cartão com final 1234.', ['Despesa', 4590, 'MERCADO EXTRA']),
    ('Itaú', 'Compra aprovada no seu cartão final 1234 de R$ 120,00 em 16/11 às 14:32 em POSTO SHELL.', ['Despesa', 12000, 'POSTO SHELL']),
    ('Pix recebido', 'Você recebeu um Pix de R$ 1.500,00 de JOÃO DA SILVA.', ['Entrada', 150000, 'Pix de JOÃO DA SILVA']),
    ('Pix enviado', 'Pix enviado: R$ 50,00 para Maria Souza.', ['Despesa', 5000, 'Pix para Maria Souza']),
    ('Estorno', 'Estorno de R$ 30,00 da compra em LOJA X.', ['Entrada', 3000, 'Estorno LOJA X']),
    ('Nubank', 'Pagamento de R$ 23,40 realizado. UBER DO BRASIL', ['Despesa', 2340, 'Pagamento']),
    ('Transferência', 'Transferência recebida de R$ 2.000,00 de EMPRESA LTDA', ['Entrada', 200000, 'EMPRESA LTDA']),
    ('Boleto', 'Você pagou um boleto de R$ 150,00 para ENEL DISTRIBUICAO.', ['Despesa', 15000, 'ENEL DISTRIBUICAO']),
    ('Saque', 'Saque de R$ 200,00 realizado no Banco24Horas', ['Despesa', 20000, 'Banco24Horas']),
    ('Débito', 'Compra no débito de R$ 12,50 em PADARIA PAO QUENTE - 16/11 08:10', ['Despesa', 1250, 'PADARIA PAO QUENTE']),
    ('Conta', 'Você recebeu R$ 10.', ['Entrada', 1000, 'Entrada']),
    ('', 'Compra internacional BRL 25.00 at STORE', ['Despesa', 2500, 'Compra']),
    ('', 'Seu salário de R$ 12.345.678,90 caiu na sua conta', ['Entrada', 1234567890, 'Entrada']),
    ('Compra', 'R$45,90 em\nFARMACIA POPULAR\nCartão final 9', ['Despesa', 4590, 'FARMACIA POPULAR']),
    ('Estorno', 'Valor de R$ -30,00 estornado em AMAZON', ['Entrada', 3000, 'Estorno AMAZON']),
    ('Compra', 'Compra de R$ 99,90 em 3 vezes na LOJA Y', ['Despesa', 9990, 'LOJA Y']),
    ('Pix', 'Pix de R$ 5,00 recebido de Ana', ['Entrada', 500, 'Pix de Ana']),
    ('Cashback', 'Você ganhou R$ 3,21 de cashback!', ['Entrada', 321, 'cashback']),
    # v2.0.1: os casos relatados no celular (PicPay e Nubank) e variacoes
    ('Carla Beatriz Moura Pinto enviou um Pix para você', 'Você recebeu R$ 0,01. Toque para visualizar o pagamento.',
     ['Entrada', 1, 'Pix de Carla Beatriz Moura Pinto']),
    ('Carla Beatriz Moura Pinto enviou um Pix para você', 'R$ 0,01 • Toque para visualizar o pagamento',
     ['Entrada', 1, 'Pix de Carla Beatriz Moura Pinto']),
    ('Pix recebido', 'Ana Souza te enviou R$ 5,00. Toque para ver.', ['Entrada', 500, 'Pix de Ana Souza']),
    ('Transferência recebida', 'Você recebeu uma transferência de R$ 67,84 de ENJOEI SA.', ['Entrada', 6784, 'ENJOEI SA']),
    ('Pix enviado', 'Você enviou um Pix de R$ 50,00 para Maria Souza. Toque para ver o comprovante.',
     ['Despesa', 5000, 'Pix para Maria Souza']),
    ('PicPay', 'Recebemos parte da sua parcela de R$ 120,00. Toque para ver detalhes.', ['Despesa', 12000, 'Parcela']),
    ('Fatura paga', 'Pagamento de fatura de R$ 350,00 realizado.', ['Despesa', 35000, 'Fatura']),
    ('Pix', 'R$ 10,00 para visualizar o pagamento', ['Despesa', 1000, 'Pix']),
    ('Nubank', 'Compra de R$ 15,00 aprovada no seu cartão em PADARIA', ['Despesa', 1500, 'PADARIA']),
    ('Inter', 'Pix de R$ 80,00 caiu na sua conta corrente', ['Entrada', 8000, 'Pix']),
    # nome comprido: corta em 40 letras (sem espaco no fim)
    ('Compra', 'Compra de R$ 10,00 em SUPERMERCADO DO BAIRRO NOVO HORIZONTE LTDA FILIAL SAO PAULO',
     ['Despesa', 1000, 'SUPERMERCADO DO BAIRRO NOVO HORIZONTE LT']),
    ('Compra', 'Compra de R$ 10,00 em SUPERMERCADO DO BAIRRO NOVO HORIZONTE E FILHOS',
     ['Despesa', 1000, 'SUPERMERCADO DO BAIRRO NOVO HORIZONTE E']),
    ('Seu código', 'Use 123456 para entrar', []),
    ('Zero', 'Compra de R$ 0,00 em TESTE', []),
    ('', 'R$ sem número', []),
    ('', '', []),
]


@test('T59', 'INTERPRETAR MENSAGEM DO BANCO: valor depois de R$, gasto ou entrada e o nome de quem recebeu/pagou (casos escritos à mão + referência)')
def t59(c):
    db = fresh('t59')
    app = abrir20(db)
    for ti, tx, esp in CASOS59:
        got = interpretar(app, ti + '. ' + tx if ti else tx)
        c.eq(got, esp, 'mensagem %r' % (tx[:60]))
    # categoria e pagamento sugeridos pelo app para as do banco (mesmas regras do extrato)
    cat = lambda d: app.call_by_name('adivinharCategoria', d)
    c.eq([cat('MERCADO EXTRA'), cat('POSTO SHELL'), cat('ENEL DISTRIBUICAO'), cat('PADARIA PAO QUENTE')],
         ['Alimentação', 'Transporte', 'Moradia', 'Alimentação'], 'categoria pelo nome (mesmas palavras do extrato)')
    # robustez: textos aleatorios nunca param o app; quando acha valor, bate com a referencia (valor e tipo)
    rnd = random.Random(59)
    pedacos = ['Compra', 'compra aprovada', 'Pix', 'recebido', 'enviado', 'R$', 'R$ ', 'BRL', '45,90', '1.234,56', '0,01',
               '1,234.56', '12', 'em', 'para', 'de', 'no', 'MERCADO', 'João', 'às 14:32', '16/11', '.', ',', '-', '  ',
               'estorno', 'cartão final 1234', 'saldo', '\n', 'ção', '€', '😀', '"', "'", 'R$-', '9.', ',5']
    achou = 0
    for k in range(400):
        t = ''.join(rnd.choice(pedacos) + rnd.choice(['', ' ']) for _ in range(rnd.randint(0, 14)))
        if k % 2 == 0:          # metade com um valor de verdade no meio (o caso que importa)
            q = rnd.randint(0, len(t))
            v_ = '%d,%02d' % (rnd.randint(0, 99999), rnd.randint(0, 99))
            t = t[:q] + rnd.choice(['R$ ', 'R$', 'BRL ', 'R$ -']) + v_ + rnd.choice(['', ' ', '. ', '\n']) + t[q:]
        antes = len(app.runtime_errors)
        try:
            got = interpretar(app, t)
        except Exception as e:          # erro do App Inventor = falha
            got = ('ERRO', str(e)[:80])
        if len(app.runtime_errors) != antes or (isinstance(got, tuple)):
            c.ok(False, 'texto %r parou o app: %r' % (t, got))
            continue
        v = r_valor_msg(t)
        if v is None:
            c.eq(got, [], 'sem valor em R$ entendivel -> nada: %r' % t)
        else:
            achou += 1
            c.eq(got[:2], [r_tipo_msg(t), v], 'tipo e valor x referencia: %r' % t)
            d = got[2]
            c.ok(isinstance(d, str) and d.strip() == d and 0 < len(d) <= 50 and not d[:1].isdigit()
                 and not sem_acento17(d).lower().startswith(('sua ', 'seu ', 'conta ', 'cartao ', 'voce ')),
                 'descricao curta, sem espaco nas pontas e sem comecar por numero: %r -> %r' % (t, d))
    c.note('400 textos aleatorios: nenhum parou o app; %d com valor conferidos contra a referencia' % achou)
    c.clean(app)


# ============================================================================= T60
NOTIFS60 = [
    ('com.nu.production', 'Compra aprovada', 'Compra de R$ 45,90 APROVADA em MERCADO EXTRA para o cartão com final 1234.'),
    ('com.itau', 'Itaú', 'Compra aprovada no seu cartão final 1234 de R$ 120,00 em 16/11 às 14:32 em POSTO SHELL.'),
    ('com.nu.production', 'Pix recebido', 'Você recebeu um Pix de R$ 1.500,00 de JOÃO DA SILVA.'),
    ('com.whatsapp', 'Ana', 'te mando os R$ 10 amanhã'),
    ('com.nu.production', 'Seu código', 'Use 123456 para entrar'),
    ('br.com.intermedium', 'Inter', 'Saldo atualizado: R$ disponível'),
]


@test('T60', 'NOTIFICAÇÕES DO BANCO NO APP (pedido do usuário): acesso, lista para conferir, lançar / ignorar, repetidos, lançar todos, colar mensagem')
def t60(c):
    nos = scm_nos()
    filhos = lambda n: [ch['$Name'] for ch in nos[n].get('$Components', [])]
    c.ok('HzDadosNot' in filhos('ColDados') and nos['BtnNotificacoes']['Text'] == 'Notificações do banco',
         '"Seus dados" tem a linha "Notificações do banco"')
    c.eq(nos['ImgDadosNot']['Picture'], 'ic_sino.png', 'icone do sino na linha')
    pal = paleta()
    db = fresh('t60')
    app = abrir20(db)
    c.eq((app.shown('HzAvisoNotif'), app.g['notifItens']), (False, []), 'sem notificacoes: nenhum aviso no Lancar')
    # 1) sem o acesso liberado: o painel explica e leva as configuracoes
    ir_notif(app)
    lt = app.comp('LeitorNotificacoes1')
    c.eq((app.shown('PnlNotif'), app.text('LblNotifStatus'), app.shown('BtnNotifAcesso'), app.shown('BtnNotifInfoApp'),
          app.shown('LblNotifVazio')), (True, 'Acesso às notificações: desligado', True, True, True),
         'acesso desligado: diz isso, mostra "Liberar acesso", "Abrir informações do app" e "Nenhuma notificação nova"')
    c.eq(norm(app.comp('LblNotifStatus').props['TextColor']), cor_ficha(app, 'Perigo'), 'status desligado em vermelho')
    app.click('BtnNotifAcesso')
    app.click('BtnNotifInfoApp')
    c.eq((lt.aberturas_config, lt.aberturas_info), (1, 1), 'os botoes abrem as telas do Android (acesso e informacoes do app)')
    c.eq(app.chegar_notificacao(*NOTIFS60[0]), None, 'sem acesso o Android nao entrega nada ao app')
    app._leitor().limpar_barra()     # a pessoa limpa a barra (o caso "ainda estava na barra" esta no T62)
    # 2) liberado: chegam notificacoes com o app FECHADO (outro dia); ao abrir, aviso no Lancar
    app.liberar_acesso_notificacoes()
    app.click('BtnNotifAtualizar')
    c.eq((app.text('LblNotifStatus'), app.shown('PnlNotifAcesso'), norm(app.comp('LblNotifStatus').props['TextColor'])),
         ('Acesso às notificações: liberado', False, cor_ficha(app, 'Bom')), '"Atualizar" depois de liberar: status verde, sem os botoes')
    c.clean(app)
    fechado = abrir20(db)          # so para entregar as notificacoes "com o app fechado" (o servico guarda)
    t0 = ms20(datetime.datetime(2026, 11, 15, 12, 0))
    ids = [fechado._leitor().chegou(a, ti, tx, t0 + i * 60000) for i, (a, ti, tx) in enumerate(NOTIFS60)]
    c.eq([i is not None for i in ids], [True, True, True, False, False, True],
         'guardadas: as 3 do banco e a do Inter com "R$"; WhatsApp (ignorado) e codigo sem valor ficam de fora')
    a2 = abrir20(db)
    c.eq((a2.shown('HzAvisoNotif'), a2.text('BtnAvisoNotif')), (True, '4 notificações para conferir'),
         'ao abrir: aviso no Lancar com quantos esperam conferencia')
    a2.click('BtnAvisoNotif')
    c.eq(a2.shown('PnlNotif'), True, 'tocar no aviso abre "Notificações do banco"')
    itens = [it[1:9] for it in a2.g['notifItens']]
    c.eq(itens, [
        ['', 0, '', '15/11/2026 12:05', '', '', 'Inter', 'nao'],
        ['Entrada', 150000, 'Pix de JOÃO DA SILVA', '15/11/2026 12:02', 'Outros', 'Pix', 'Nubank', 'ok'],
        ['Despesa', 12000, 'POSTO SHELL', '15/11/2026 12:01', 'Transporte', 'Cartão de crédito', 'Itaú', 'ok'],
        ['Despesa', 4590, 'MERCADO EXTRA', '15/11/2026 12:00', 'Alimentação', 'Cartão de crédito', 'Nubank', 'ok'],
    ], 'lista (a mais nova primeiro): tipo, valor, nome, data da notificacao, categoria, pagamento, banco e situacao')
    c.eq(len(a2.comp('ListaNotif').elements), 4, '4 linhas na lista')
    c.eq((a2.text('BtnNotifLancarTodos'), a2.shown('BtnNotifLancarTodos'), a2.shown('BtnNotifIgnorarTodos')),
         ('Lançar os 3', True, True), '"Lançar os 3" (o que nao foi entendido fica de fora) e "Ignorar todas"')
    # 3) tocar numa: confirma e lanca (com a data da notificacao); a notificacao sai da lista
    tocar_lista(a2, 'ListaNotif', 4)
    dlg = a2.dialogs[-1]
    c.eq((dlg['title'], dlg['buttons']), ('Notificação: Nubank', ['Lançar', 'Ignorar', 'Cancelar']), 'toque: janela com Lançar / Ignorar / Cancelar')
    c.eq(dlg['texto'], 'Despesa de R$ 45,90\nMERCADO EXTRA\nAlimentação • Cartão de crédito\n15/11/2026 12:00\n\nLançar?',
         'a janela mostra o que vai ser lancado')
    n0 = len(a2.g['lancamentos'])
    a2.answer_dialog('Cancelar')
    c.eq((len(a2.g['lancamentos']), len(a2.g['notifItens'])), (n0, 4), 'Cancelar nao muda nada')
    tocar_lista(a2, 'ListaNotif', 4)
    a2.answer_dialog('Lançar')
    c.eq(a2.g['lancamentos'][0], ['Despesa', 'MERCADO EXTRA', 4590, '15/11/2026 12:00', 'Alimentação', 'Cartão de crédito'],
         'lancado com os dados da notificacao (dia e hora dela, nao o de agora)')
    c.eq((len(a2.g['notifItens']), a2.text('LblNotifMsg'), a2.g['chavesNotif']),
         (3, '1 lançamento adicionado. Ele já aparece no Histórico.', ['15/11/2026|Despesa|4590']),
         'saiu da lista; aviso verde; a chave (dia|tipo|valor) fica guardada para o extrato')
    c.eq((db_val(db, 'chaves_notif'), len(notif_estado(db)['pendentes'])), (['15/11/2026|Despesa|4590'], 3),
         'gravado no aparelho e apagado da extensao')
    # 4) a mesma compra chega de novo (outro app avisa a mesma coisa): fica como "ja existe um igual"
    a2.chegar_notificacao('com.google.android.apps.messaging', 'SMS', 'NUBANK: Compra R$ 45,90 MERCADO EXTRA', t0 + 30 * 60000)
    it = a2.g['notifItens'][0]
    c.eq((it[1], it[2], it[8]), ('Despesa', 4590, 'repetido'), 'mesma compra (dia, tipo, valor) por SMS: marcada como repetida')
    c.eq((len(a2.g['notifItens']), len(a2.comp('ListaNotif').elements)), (4, 4),
         'com o app aberto a lista atualiza sozinha (NotificacaoRecebida)')
    tocar_lista(a2, 'ListaNotif', 1)
    c.eq(a2.dialogs[-1]['buttons'], ['Lançar mesmo assim', 'Ignorar', 'Cancelar'], 'repetida: pergunta "Lançar mesmo assim"')
    c.ok('Já existe um lançamento neste dia com o mesmo tipo e valor' in a2.dialogs[-1]['texto'], 'e explica por que')
    a2.answer_dialog('Ignorar')
    c.eq((len(a2.g['lancamentos']), len(a2.g['notifItens'])), (n0 + 1, 3), 'Ignorar: some da lista sem lancar')
    # 5) a que nao foi entendida so pode ser ignorada (ou mantida)
    tocar_lista(a2, 'ListaNotif', 1)
    c.eq((a2.dialogs[-1]['buttons'], a2.dialogs[-1]['texto'].startswith('Não encontrei um valor em R$ nesta notificação:')),
         (['Ignorar', 'Manter'], True), 'sem valor: "Ignorar" ou "Manter", com o texto da notificacao')
    a2.answer_dialog('Manter')
    c.eq(len(a2.g['notifItens']), 3, 'Manter: continua na lista')
    # 6) lancar todos: pergunta antes; lanca so as prontas
    a2.click('BtnNotifLancarTodos')
    c.eq((a2.dialogs[-1]['title'], a2.dialogs[-1]['buttons']), ('Lançar todos?', ['Lançar todos', 'Cancelar']), 'lancar todos pergunta antes')
    a2.answer_dialog('Cancelar')
    c.eq(len(a2.g['lancamentos']), n0 + 1, 'Cancelar: nada lancado')
    a2.click('BtnNotifLancarTodos')
    a2.answer_dialog('Lançar todos')
    c.eq(sorted(r[1] for r in a2.g['lancamentos'][:3]), ['MERCADO EXTRA', 'POSTO SHELL', 'Pix de JOÃO DA SILVA'], 'as 2 prontas entraram')
    c.eq(([it[8] for it in a2.g['notifItens']], a2.text('LblNotifMsg')),
         (['nao'], '2 lançamentos adicionados. Eles já aparecem no Histórico.'), 'so a nao entendida ficou; aviso com a quantidade')
    c.eq(sorted(a2.g['chavesNotif']), ['15/11/2026|Despesa|12000', '15/11/2026|Despesa|4590', '15/11/2026|Entrada|150000'],
         'chaves das 3 lancadas pelas notificacoes')
    # 7) ignorar todas
    a2.click('BtnNotifIgnorarTodos')
    c.eq(a2.dialogs[-1]['title'], 'Ignorar todas?', 'ignorar todas pergunta antes')
    a2.answer_dialog('Ignorar todas')
    c.eq((a2.g['notifItens'], notif_estado(db)['pendentes'], a2.shown('HzAvisoNotif'), a2.shown('LblNotifVazio')),
         ([], [], False, True), 'lista vazia, extensao vazia, sem aviso no Lancar')
    # 8) reabrir: o que foi lancado continua; as chaves tambem
    a3 = abrir20(db)
    c.eq((len(a3.g['lancamentos']), sorted(a3.g['chavesNotif'])), (n0 + 3, sorted(a2.g['chavesNotif'])), 'reabrindo: tudo continua')
    # 9) falha ao gravar: nada e lancado e a notificacao continua na lista
    a3.chegar_notificacao('com.nu.production', 'Compra aprovada', 'Compra de R$ 7,00 em CAFE', ms20(AGORA20))
    a3.click('BtnAvisoNotif')
    a3.comp('TinyDB1').drop_writes = True
    tocar_lista(a3, 'ListaNotif', 1)
    a3.answer_dialog('Lançar')
    a3.comp('TinyDB1').drop_writes = False
    c.eq((len(a3.g['lancamentos']), len(a3.g['notifItens']), a3.message_dialogs[-1]['message']),
         (n0 + 3, 1, 'Erro: não foi possível gravar. Nada foi lançado.'), 'falha ao gravar: desfaz, avisa e a notificacao continua')
    # 9b) gravando de novo, entra; o mesmo cafe avisado de novo (outro app) e lancado assim mesmo ("Lancar mesmo assim")
    tocar_lista(a3, 'ListaNotif', 1)
    a3.answer_dialog('Lançar')
    c.eq((len(a3.g['lancamentos']), a3.g['notifItens'], a3.g['lancamentos'][0][1]), (n0 + 4, [], 'CAFE'), 'gravando, o cafe entrou')
    a3.chegar_notificacao('com.google.android.apps.messaging', 'SMS', 'Compra de R$ 7,00 em CAFE', ms20(AGORA20) + 120000)
    c.eq([it[8] for it in a3.g['notifItens']], ['repetido'], 'o mesmo cafe de novo: marcado como repetido')
    tocar_lista(a3, 'ListaNotif', 1)
    a3.answer_dialog('Lançar mesmo assim')
    c.eq((len(a3.g['lancamentos']), [r[1] for r in a3.g['lancamentos'][:2]], a3.g['notifItens'],
          a3.g['chavesNotif'].count('16/11/2026|Despesa|700')),
         (n0 + 5, ['CAFE', 'CAFE'], [], 2), '"Lançar mesmo assim": entra o segundo cafe (dois cafes de verdade), com a chave de cada um')
    # 10) colar uma mensagem: preenche o Lancar para conferir
    ir_notif(a3)
    a3.click('BtnInterpretar')
    c.eq((a3.shown('LblErroColar'), a3.text('LblErroColar')), (True, 'Cole a mensagem do banco no campo acima.'), 'campo vazio: pede para colar')
    a3.type_text('TxtColar', 'Bom dia! Sua fatura vence amanhã.')
    a3.click('BtnInterpretar')
    c.eq(a3.text('LblErroColar'), 'Não encontrei um valor em R$ nesta mensagem. Confira se ela tem o valor (ex.: R$ 45,90).',
         'sem valor: explica')
    a3.type_text('TxtColar', 'Pix enviado: R$ 50,00 para Maria Souza.')
    a3.click('BtnInterpretar')
    c.eq((a3.shown('PnlLancar'), a3.text('TxtDescricao'), a3.text('TxtValor'), a3.g['categoriaSel'], a3.g['pagamentoSel'],
          a3.shown('LblErroColar'), a3.text('TxtColar')),
         (True, 'Pix para Maria Souza', '50,00', 'Outros', 'Pix', False, ''), 'preencheu o Lancar (descricao, valor, categoria, pagamento)')
    c.eq(a3.text('LblAviso'), 'Entendi uma despesa de R$ 50,00. Confira os campos e toque em “− Despesa”.', 'diz o que entendeu e o que tocar')
    c.eq((a3.text('BtnCategoria'), a3.text('BtnPagamento'), a3.comp('ImgPagIcone').props.get('Picture') not in ('', None)),
         ('Outros', 'Pix', True), 'campos de categoria e pagamento mostram o que foi escolhido (com icone)')
    n1 = len(a3.g['lancamentos'])
    a3.click('BtnDespesa')
    c.eq([r[:3] for r in a3.g['lancamentos'] if r[1] == 'Pix para Maria Souza'], [['Despesa', 'Pix para Maria Souza', 5000]],
         'a pessoa confere e salva como despesa (um lancamento, na posicao da data)')
    c.eq(len(a3.g['lancamentos']), n1 + 1, 'um lancamento novo')
    # 11) tema escuro: o painel acompanha
    a3.touch('CanvasTopo')
    a3.click('BtnTemaEscuro')
    a3.click('BtnNotificacoes')
    c.eq((a3.g['temaEscuro'], a3.shown('PnlNotif')), (True, True), 'tema escuro, painel das notificacoes aberto')
    for comp_, prop, ficha in (('LblTituloNotif', 'TextColor', 'Texto'), ('LblSubNotif', 'TextColor', 'Suave'),
                               ('ListaNotif', 'TextColor', 'Texto'), ('TxtColar', 'BackgroundColor', 'Fundo')):
        c.eq(norm(a3.comp(comp_).props[prop]), norm(pal.aia(getattr(pal, {'Texto': 'D_INK', 'Suave': 'D_MUTED', 'Fundo': 'D_BG'}[ficha]))),
             '%s.%s no tema escuro' % (comp_, prop))
    for x in (app, fechado, a2, a3):
        c.clean(x)


# ============================================================================= T61
@test('T61', 'DUPLICIDADE NA IMPORTAÇÃO DE EXTRATO (pedido do usuário): mesmo arquivo 2x, extratos que se sobrepõem, gastos iguais de verdade e o que veio das notificações')
def t61(c):
    cab = 'Data;Descrição;Valor\n'
    out = cab + '01/10/2026;SALARIO EMPRESA X;5.000,00\n03/10/2026;SUPERMERCADO BOM;-312,45\n05/10/2026;UBER TRIP;-23,10\n' \
                '10/10/2026;FARMACIA SAO JOAO;-58,70\n12/10/2026;NETFLIX;-55,90\n'
    out2 = cab + '10/10/2026;FARMACIA SAO JOAO;-58,70\n12/10/2026;NETFLIX;-55,90\n15/10/2026;POSTO SHELL;-150,00\n' \
                 '20/10/2026;PIX RECEBIDO FULANO;300,00\n'
    db = fresh('t61')
    app = open_app(db, now=AGORA61)
    # 1) mesmo arquivo duas vezes: na segunda, nada entra
    conferir_importacao(c, app, out, 'outubro (1a vez)')
    c.eq(len(app.g['lancamentos']), 5, '5 lancamentos importados')
    ref = conferir_importacao(c, app, out, 'outubro (2a vez)')
    c.eq((len(app.g['lancamentos']), ref['repetidos'], ref['novos']), (5, 5, []),
         'mesmo arquivo de novo: os 5 "ja estavam no app"; nenhum duplicado')
    c.eq(app.text('LblDadosMsg'), 'Não encontrei lançamentos novos neste arquivo. 5 já estavam no app.', 'e o app diz isso')
    # 2) extratos que se sobrepoem (1 a 12 e 10 a 20): so entra o que e novo
    ref = conferir_importacao(c, app, out2, 'sobreposto')
    c.eq((ref['repetidos'], [r[1] for r in ref['novos']]), (2, ['PIX RECEBIDO FULANO', 'POSTO SHELL']),
         'sobreposicao: 2 pulados (farmacia e Netflix), 2 novos')
    c.eq(len(app.g['lancamentos']), 7, 'total 7, sem duplicados')
    # 3) gastos iguais de verdade (3 cafes no mesmo dia): os 3 entram; reimportar nao duplica nenhum
    cafes = cab + '13/10/2026;CAFE;-6,50\n13/10/2026;CAFE;-6,50\n13/10/2026;CAFE;-6,50\n'
    ref = conferir_importacao(c, app, cafes, '3 cafes iguais')
    c.eq(len(ref['novos']), 3, '3 cafes iguais no mesmo dia sao 3 gastos (entram os 3)')
    ref = conferir_importacao(c, app, cafes, '3 cafes de novo')
    c.eq((ref['repetidos'], len(app.g['lancamentos'])), (3, 10), 'de novo: os 3 ja estavam; continua 10')
    cafes4 = cafes + '13/10/2026;CAFE;-6,50\n'
    ref = conferir_importacao(c, app, cafes4, '4 cafes (1 a mais)')
    c.eq((ref['repetidos'], len(ref['novos'])), (3, 1), 'extrato com 4 cafes: 3 ja estavam, 1 novo')
    # 4) o mesmo gasto ja lancado pela NOTIFICACAO (descricao diferente): o extrato nao lanca de novo
    app.liberar_acesso_notificacoes()
    app.chegar_notificacao('com.nu.production', 'Compra aprovada', 'Compra de R$ 89,90 em DROGASIL para o cartão com final 1',
                           ms20(datetime.datetime(2026, 11, 11, 18, 30)))
    app.chegar_notificacao('com.nu.production', 'Pix recebido', 'Você recebeu um Pix de R$ 250,00 de Carlos.',
                           ms20(datetime.datetime(2026, 11, 11, 19, 0)))
    ir_notif(app)
    app.click('BtnNotifLancarTodos')
    app.answer_dialog('Lançar todos')
    c.eq(sorted(app.g['chavesNotif']), ['11/11/2026|Despesa|8990', '11/11/2026|Entrada|25000'], 'as 2 notificacoes lancadas')
    nov = cab + '11/11/2026;DROGASIL LOJA 123 SAO PAULO BR;-89,90\n11/11/2026;PIX RECEBIDO - CARLOS A SOUZA;250,00\n' \
                '11/11/2026;PADARIA;-12,00\n'
    ref = conferir_importacao(c, app, nov, 'extrato com o que veio das notificacoes')
    c.eq((ref['notif'], [r[1] for r in ref['novos']]), (2, ['PADARIA']),
         'os 2 que vieram das notificacoes sao pulados (mesmo dia, tipo e valor); so a padaria entra')
    ref = conferir_importacao(c, app, nov, 'mesmo extrato de novo')
    c.eq((ref['notif'], ref['repetidos'], ref['novos']), (2, 1, []), 'de novo: nada entra (2 pelas notificacoes, 1 ja estava)')
    # 5) dois gastos iguais no dia, so um avisado por notificacao: o outro entra
    app.chegar_notificacao('com.nu.production', 'Compra aprovada', 'Compra de R$ 5,00 em CAFE',
                           ms20(datetime.datetime(2026, 11, 10, 9, 0)))
    ir_notif(app)
    app.click('BtnNotifLancarTodos')
    app.answer_dialog('Lançar todos')
    dois = cab + '10/11/2026;CAFE DA ESQUINA;-5,00\n10/11/2026;CAFE DA ESQUINA;-5,00\n'
    ref = conferir_importacao(c, app, dois, '2 cafes, 1 avisado')
    c.eq((ref['notif'], len(ref['novos'])), (1, 1), '2 cafes iguais e so 1 veio da notificacao: 1 pulado, 1 entra')
    # 6) apagar o lancamento que veio da notificacao: o extrato volta a trazer aquele gasto
    app.click('BtnNavHistorico')
    vis = [r for r in app.g['lancamentos'] if r[3][3:10] == '11/2026']
    k = next(k for k, r in enumerate(vis) if r[1] == 'DROGASIL') + 1
    tocar_lista(app, 'ListaHistorico', k)
    app.answer_dialog('Excluir')             # a janela "Excluir lançamento?" e respondida com "Sim, excluir" (v1.8.1)
    c.eq([r[1] for r in app.g['lancamentos'] if r[1] == 'DROGASIL'], [], 'o lancamento DROGASIL (da notificacao) foi excluido')
    ref = conferir_importacao(c, app, nov, 'depois de excluir o da notificacao')
    c.eq([r[1] for r in ref['novos']], ['DROGASIL LOJA 123 SAO PAULO BR'], 'excluido no app: o extrato traz de novo (nao fica sem)')
    # 7) aleatorio: 80 historias (notificacoes lancadas + extratos com sobreposicao e repeticoes) x referencia
    rnd = random.Random(61)
    for k in range(80):
        dbk = fresh('t61_%d' % k)
        ak = open_app(dbk, now=AGORA61)
        ak.liberar_acesso_notificacoes()
        dias = ['%02d/11/2026' % d for d in range(1, 12)]
        valores = ['-5,00', '-12,30', '-89,90', '250,00', '-1.000,00']
        for _ in range(rnd.randint(0, 4)):
            d = rnd.choice(dias)
            v = rnd.choice(valores)
            txt_ = ('Você recebeu um Pix de R$ %s de Ana.' % v) if not v.startswith('-') else ('Compra de R$ %s em LOJA' % v[1:])
            ak.chegar_notificacao('com.nu.production', 'Banco', txt_,
                                  ms20(datetime.datetime(2026, 11, int(d[:2]), rnd.randint(8, 20), rnd.randint(0, 59))))
        if ak.g['notifItens'] or True:
            ir_notif(ak)
            if any(it[9] == 'ok' for it in ak.g['notifItens']):
                ak.click('BtnNotifLancarTodos')
                ak.answer_dialog('Lançar todos')
        for _ in range(rnd.randint(1, 3)):
            linhas = [cab.rstrip('\n')]
            for _ in range(rnd.randint(1, 8)):
                linhas.append('%s;%s;%s' % (rnd.choice(dias), rnd.choice(['LOJA', 'LOJA XPTO SA', 'PIX ANA', 'CAFE']), rnd.choice(valores)))
            conferir_importacao(c, ak, '\n'.join(linhas) + '\n', 'aleatorio %d' % k)
        c.clean(ak)
    c.note('80 historias aleatorias (notificacoes lancadas + extratos sobrepostos/repetidos) conferidas contra a referencia')
    c.clean(app)


# ============================================================================= T62 (v2.0.1)
@test('T62', 'LEITOR PARADO PELO ANDROID (relatado no Xiaomi): o app religa o leitor, relê a barra sem repetir o que já foi tratado e mostra o diagnóstico')
def t62(c):
    db = fresh('t62')
    app = abrir20(db)
    lt = app._leitor()
    c.eq((getattr(lt, 'reconexoes', 0), app.shown('HzAvisoNotif')), (1, False),
         'ao abrir, o app pede para religar o leitor (sem acesso liberado, a extensao nao faz nada)')
    ir_notif(app)
    c.eq((app.shown('LblNotifDiag'), app.text('LblNotifStatus')), (False, 'Acesso às notificações: desligado'),
         'sem acesso: sem a linha de diagnostico')
    app.liberar_acesso_notificacoes()
    app.click('BtnNotifAtualizar')
    c.eq((app.shown('LblNotifDiag'), app.text('LblNotifDiag')), (True, 'Leitor ligado • 0 notificações vistas'),
         'acesso liberado: "Leitor ligado" e quantas o leitor ja viu')
    t0 = ms20(datetime.datetime(2026, 11, 16, 14, 0))
    # 1) o primeiro teste do celular: PicPay chega com o app aberto, aparece e e lancado
    picpay = ('com.picpay', 'Carla Beatriz Moura Pinto enviou um Pix para você', 'Você recebeu R$ 0,01. Toque para visualizar o pagamento.')
    c.ok(app.chegar_notificacao(*picpay, quando_ms=t0) is not None, 'PicPay guardada')
    c.eq([it[1:4] for it in app.g['notifItens']], [['Entrada', 1, 'Pix de Carla Beatriz Moura Pinto']],
         'na lista: entrada de R$ 0,01, "Pix de" quem enviou (nao "Pix para visualizar o pagamento")')
    tocar_lista(app, 'ListaNotif', 1)
    app.answer_dialog('Lançar')
    c.eq((app.g['lancamentos'][0][1], app.g['notifItens']), ('Pix de Carla Beatriz Moura Pinto', []), 'lancada')
    # 2) o Android para o leitor (app no fundo): a do Nubank fica so na barra
    lt.desconectar()
    nubank = ('com.nu.production', 'Transferência recebida', 'Você recebeu uma transferência de R$ 67,84 de ENJOEI SA.')
    c.eq(app.chegar_notificacao(*nubank, quando_ms=t0 + 3600000), None, 'leitor parado: nada e guardado (o caso relatado)')
    ir_notif(app)
    c.eq((app.g['notifItens'], app.text('LblNotifDiag').startswith('Leitor parado pelo Android: toque em Atualizar para religar')),
         ([], True), 'o painel diz que o leitor esta parado e o que fazer')
    # 3) "Atualizar": religa, rele a barra; a do Nubank aparece; a do PicPay (ja lancada) NAO volta
    n_lanc = len(app.g['lancamentos'])
    app.click('BtnNotifAtualizar')
    c.eq([it[1:4] for it in app.g['notifItens']], [['Entrada', 6784, 'ENJOEI SA']],
         'religado: a do Nubank (ainda na barra) aparece; a do PicPay, ja lancada, nao volta')
    c.eq((len(app.g['lancamentos']), app.text('LblNotifDiag')),
         (n_lanc, 'Leitor ligado • 3 notificações vistas • última: Nubank às 16/11 15:00 (guardada)'),
         'nada lancado sozinho; diagnostico com a ultima lida')
    # 4) parado de novo, chega a fatura, a pessoa fecha o app e abre depois: ao abrir, o app religa e ela aparece
    lt.desconectar()
    fatura = ('com.nu.production', 'Fatura paga', 'Pagamento de fatura de R$ 350,00 realizado.')
    app.chegar_notificacao(*fatura, quando_ms=t0 + 7200000)
    c.clean(app)
    a2 = abrir20(db)
    c.eq((sorted(it[3] for it in a2.g['notifItens']), a2.shown('HzAvisoNotif'), a2.text('BtnAvisoNotif')),
         (['ENJOEI SA', 'Fatura'], True, '2 notificações para conferir'),
         'ao abrir o app, o leitor e religado e a fatura (que estava na barra) entra na lista')
    # 5) religar de novo (Atualizar) com tudo ja lido nao duplica
    ir_notif(a2)
    a2.click('BtnNotifAtualizar')
    a2.click('BtnNotifAtualizar')
    c.eq(len(a2.g['notifItens']), 2, 'religar varias vezes nao duplica nada')
    # 6) se a pessoa limpou a barra com o leitor parado, aquela notificacao se perde (limite do Android)
    a2._leitor().desconectar()
    a2.chegar_notificacao('com.nu.production', 'Compra aprovada', 'Compra de R$ 9,90 em CAFE', quando_ms=t0 + 9000000)
    a2._leitor().limpar_barra()
    a2.click('BtnNotifAtualizar')
    c.eq(len(a2.g['notifItens']), 2, 'barra limpa com o leitor parado: a notificacao nao chega (o relatorio avisa)')
    # 7) chegou ANTES de liberar o acesso e ainda esta na barra: ao liberar e tocar em Atualizar, entra
    db3 = fresh('t62b')
    a3 = abrir20(db3)
    c.eq(a3.chegar_notificacao(*nubank, quando_ms=t0), None, 'sem acesso: nada guardado')
    a3.liberar_acesso_notificacoes()
    ir_notif(a3)
    a3.click('BtnNotifAtualizar')
    c.eq([it[3] for it in a3.g['notifItens']], ['ENJOEI SA'],
         'liberou o acesso e tocou em Atualizar: a que estava na barra entra na lista')
    for x in (app, a2, a3):
        c.clean(x)


def main():
    out = io.StringIO()

    def say(s=''):
        print(s)
        out.write(s + '\n')

    say('BATERIA DE TESTES - Conto v2.0.1   (%s)' % datetime.datetime.now().strftime('%d/%m/%Y %H:%M'))
    say('Pacote testado: %s' % AIA_NOTE)
    say('Motor: simulador ai_sim.py executando os blocos reais (nao e um Android real)')
    say('-' * 100)
    resumo = []
    skip = set(x for x in os.environ.get('SKIP', '').split(',') if x)
    only = set(x for x in os.environ.get('ONLY', '').split(',') if x)
    for tid, titulo, fn in TESTS:
        if tid in skip or (only and tid not in only):
            continue
        ctx = Ctx(tid, titulo)
        t0 = time.time()
        try:
            fn(ctx)
        except Exception:
            ctx.fails.append('EXCECAO NO TESTE: ' + traceback.format_exc(limit=4))
        ok = (not ctx.fails) and ctx.n > 0
        resumo.append((tid, titulo, ok, ctx.n, len(ctx.fails)))
        say('[%s] %s  %s   (%d verificacoes, %.1fs)' % ('PASSOU' if ok else 'FALHOU', tid, titulo, ctx.n, time.time() - t0))
        for n in ctx.notes:
            say('        . ' + n)
        for f in ctx.fails[:12]:
            say('        X ' + f)
        if len(ctx.fails) > 12:
            say('        X ... e mais %d falhas' % (len(ctx.fails) - 12))
    say('-' * 100)
    tot = sum(r[3] for r in resumo)
    falhos = [r for r in resumo if not r[2]]
    say('RESULTADO: %d/%d testes passaram; %d verificacoes executadas.' % (len(resumo) - len(falhos), len(resumo), tot))
    if falhos:
        say('FALHARAM: ' + ', '.join(r[0] for r in falhos))
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    open(REPORT, 'w', encoding='utf-8').write(out.getvalue())
    sys.exit(1 if falhos else 0)


if __name__ == '__main__':
    main()
