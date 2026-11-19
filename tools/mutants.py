#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Teste DOS TESTES: injeta defeitos de proposito no app (um por vez) e confere se a bateria percebe.
Se algum "mutante" sobreviver (bateria toda verde), a bateria nao enxerga aquele tipo de defeito.
"""
import copy
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_conto as G   # noqa: E402  (so para montar blocos novos)

SP = os.environ.get('SP') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # pasta de trabalho
AIA = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', 'Conto.aia')
SRC = os.path.join(SP, 'mut_src18')                # copia estavel do pacote entregue
MUT = os.path.join(SP, 'mut_app18')
NSU = 'https://developers.google.com/blockly/xml'
NS = '{%s}' % NSU
ET.register_namespace('', NSU)
CONTO = os.path.join('src', 'appinventor', 'ai_conto', 'Conto')


def tg(e):
    return e.tag.split('}')[-1]


def field(b, name):
    for c in b:
        if tg(c) == 'field' and c.get('name') == name:
            return c
    return None


def val(b, name):
    for c in b:
        if tg(c) == 'value' and c.get('name') == name:
            return c
    return None


def top(root, typ, name=None, inst=None, ev=None):
    for b in root:
        if tg(b) != 'block' or b.get('type') != typ:
            continue
        if name is not None and field(b, 'NAME') is not None and field(b, 'NAME').text == name:
            return b
        if inst is not None:
            m = [c for c in b if tg(c) == 'mutation'][0]
            if m.get('instance_name') == inst and m.get('event_name') == ev:
                return b
    raise KeyError((typ, name, inst, ev))


def parent_map(root):
    return {c: p for p in root.iter() for c in p}


def splice_out(root, blk):
    """Remove uma instrucao da cadeia (liga o bloco anterior ao proximo)."""
    pm = parent_map(root)
    holder = pm[blk]                      # <statement> ou <next>
    nxt = [c for c in blk if tg(c) == 'next']
    nxt_block = nxt[0][0] if nxt else None
    holder.remove(blk)
    if nxt_block is not None:
        holder.append(nxt_block)
    elif tg(holder) == 'next':
        pm[holder].remove(holder)


def find(root_, pred):
    for b in root_.iter(NS + 'block'):
        if pred(b):
            return b
    raise KeyError('bloco nao encontrado')


def call(root_, name):
    return find(root_, lambda b: b.get('type') == 'procedures_callnoreturn' and field(b, 'PROCNAME').text == name)


def dsl(block_el):
    """Converte bloco criado pela DSL do gerador para elementos no namespace do Blockly."""
    s = ET.tostring(block_el, encoding='unicode')
    return ET.fromstring('<xml xmlns="%s">%s</xml>' % (NSU, s))[0]


MUTANTES = []


def ramo_registrar(root, var):
    '''v1.8: o LOCAL do registrar que declara `var`: 'repOk' = ramo de CRIAR um lancamento; 'novaData' = ramo de EDITAR.'''
    p = top(root, 'procedures_defnoreturn', 'registrar')
    r = [b for b in p.iter(NS + 'block') if b.get('type') == 'local_declaration_statement'
         and any(tg(f) == 'field' and (f.get('name') or '').startswith('VAR') and f.text == var for f in b)]
    assert len(r) == 1, len(r)
    return r[0]


def mutante(rotulo, esperado):
    def deco(fn):
        MUTANTES.append((rotulo, esperado, fn))
        return fn
    return deco


# ------------------------------------------------------------------ mutantes no leitor de valores
@mutante('paraCentavos: multiplica por 10 em vez de 100', ['T03'])
def m1(root):
    p = top(root, 'procedures_defreturn', 'paraCentavos')
    for mul in p.iter(NS + 'block'):
        if mul.get('type') == 'math_multiply':
            for n in mul.iter(NS + 'block'):
                if n.get('type') == 'math_number' and field(n, 'NUM').text == '100':
                    field(n, 'NUM').text = '10'
                    return
    raise KeyError


@mutante('paraCentavos: aceita ".500" (grupo de milhar sem digito antes)', ['T12'])
def m2(root):
    p = top(root, 'procedures_defreturn', 'paraCentavos')
    # troca a primeira comparacao "primeiro < 1" no ramo sem virgula por "primeiro < 0"
    cnt = 0
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'math_compare' and field(b, 'OP').text == 'LT':
            a = val(b, 'A')[0]
            bb = val(b, 'B')[0]
            if a.get('type') == 'lexical_variable_get' and field(a, 'VAR').text == 'primeiro' \
                    and bb.get('type') == 'math_number' and field(bb, 'NUM').text == '1':
                cnt += 1
                if cnt == 2:                 # a segunda ocorrencia e a do ramo sem virgula
                    field(bb, 'NUM').text = '0'
                    return
    raise KeyError(cnt)


@mutante('paraCentavos: limite de digitos inteiros 9 -> 10', ['T03', 'T12', 'T17'])
def m3(root):
    p = top(root, 'procedures_defreturn', 'paraCentavos')
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'math_compare' and field(b, 'OP').text == 'GT':
            bb = val(b, 'B')[0]
            if bb.get('type') == 'math_number' and field(bb, 'NUM').text == '9':
                field(bb, 'NUM').text = '10'
                return
    raise KeyError


# ------------------------------------------------------------------ mutantes no formatador
@mutante('formatarMoeda: sem o zero dos centavos (R$ 0,5 em vez de R$ 0,05)', ['T03', 'T13'])
def m4(root):
    p = top(root, 'procedures_defreturn', 'formatarMoeda')
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'controls_choose':
            t = val(b, 'THENRETURN')[0]
            if t.get('type') == 'text' and field(t, 'TEXT').text == '0':
                field(t, 'TEXT').text = ''
                return
    raise KeyError


@mutante('formatarMoeda: troca "." por "," nos milhares', ['T03', 'T13'])
def m5(root):
    p = top(root, 'procedures_defreturn', 'formatarMoeda')
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'text' and field(b, 'TEXT').text == '.':
            field(b, 'TEXT').text = ','
            return
    raise KeyError


# ------------------------------------------------------------------ mutantes em gravar / registrar
@mutante('registrar: esquece de chamar gravarDados', ['T08', 'T10'])
def m6(root):
    # v1.8: mira o ramo de CRIAR (o 1o gravarDados do registrar e o do editar desde que a edicao entrou)
    splice_out(root, call(ramo_registrar(root, 'repOk'), 'gravarDados'))


@mutante('registrar: guarda pagamento no lugar da categoria (troca os dois)', ['T05'])
def m7(root):
    p = ramo_registrar(root, 'repOk')          # v1.8: o lancamento NOVO (o 1o da procedure e o do editar)
    lc = find(p, lambda b: b.get('type') == 'lists_create_with' and val(b, 'ADD5') is not None)
    a4, a5 = val(lc, 'ADD4'), val(lc, 'ADD5')
    x, y = a4[0], a5[0]
    a4.remove(x)
    a5.remove(y)
    a4.append(y)
    a5.append(x)


@mutante('gravarDados: sempre diz que gravou (falso sucesso)', ['T10'])
def m8(root):
    p = top(root, 'procedures_defnoreturn', 'gravarDados')
    st = find(p, lambda b: b.get('type') == 'lexical_variable_set' and field(b, 'VAR').text == 'global gravacaoOk')
    v = val(st, 'VALUE')
    for x in list(v):
        v.remove(x)
    v.append(dsl(G.boolean(True)))


@mutante('registrar: nao desfaz o registro quando a gravacao falha', ['T10'])
def m9(root):
    # v1.8: o desfazer do ramo de CRIAR e "lancamentos = antes" (o 1o "remover item" agora e o do editar com outra data)
    st = sets_var(ramo_registrar(root, 'repOk'), 'global lancamentos')
    assert len(st) == 1
    splice_out(root, st[0])


@mutante('registrar: deixa de exigir a categoria (some a validacao)', ['T01', 'T02', 'T11', 'T29'])
def m10(root):
    p = top(root, 'procedures_defnoreturn', 'registrar')
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'controls_if' and any(x.get('type') == 'text' and field(x, 'TEXT').text == 'Escolha uma categoria.' for x in b.iter(NS + 'block')):
            splice_out(root, b)
            return
    raise KeyError


@mutante('BtnEntrada.Click: zera a categoria antes de registrar (bug original voltando)', ['T05', 'T01', 'T15'])
def m11(root):
    h = top(root, 'component_event', inst='BtnEntrada', ev='Click')
    stm = [c for c in h if tg(c) == 'statement'][0]
    first = stm[0]
    novo = dsl(G.gset('categoriaSel', G.txt('')))
    stm.remove(first)
    stm.append(novo)
    nx = ET.SubElement(novo, NS + 'next')
    nx.append(first)


# ------------------------------------------------------------------ mutantes em calculos / carga / historico
@mutante('atualizarTudo: receitas contadas como despesas', ['T07', 'T04', 'T05'])
def m12(root):
    p = top(root, 'procedures_defnoreturn', 'atualizarTudo')
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'text' and field(b, 'TEXT').text == 'Entrada':
            field(b, 'TEXT').text = 'EntradaX'
            return
    raise KeyError


@mutante('Screen1.Initialize: nao carrega os dados salvos', ['T08', 'T09'])
def m13(root):
    h = top(root, 'component_event', inst='Screen1', ev='Initialize')
    splice_out(root, call(h, 'carregarDados'))


@mutante('atualizarHistorico: volta a juntar categoria e pagamento com "|"', ['T06', 'T15'])
def m14(root):
    p = top(root, 'procedures_defnoreturn', 'atualizarHistorico')
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'text' and field(b, 'TEXT').text == '\\nPagamento: ':
            field(b, 'TEXT').text = ' | '
            return
    raise KeyError


@mutante('migracao: chave antiga errada', ['T09'])
def m15(root):
    g = top(root, 'global_declaration', 'chaveAntiga')
    t = val(g, 'VALUE')[0]
    field(t, 'TEXT').text = 'transacoesX'


@mutante('Excluir: remove o indice errado (+1)', ['T06', 'T08', 'T10'])
def m16(root):
    h = top(root, 'component_event', inst='Notifier1', ev='AfterChoosing')
    rem = find(h, lambda b: b.get('type') == 'lists_remove_item')
    idx = val(rem, 'INDEX')
    old = idx[0]
    idx.remove(old)
    soma = dsl(G.madd(G.num(0), G.num(0)))
    # troca o segundo zero por 1 e o primeiro pelo indice original
    v0, v1 = val(soma, 'NUM0'), val(soma, 'NUM1')
    for x in list(v0):
        v0.remove(x)
    for x in list(v1):
        v1.remove(x)
    v0.append(old)
    v1.append(dsl(G.num(1)))
    idx.append(soma)



# ------------------------------------------------------------------ v1.4: grafico colorido, legenda, porcentagem
def proc(root, nome):
    return top(root, 'procedures_defnoreturn', nome)


def comp_set(root_, inst, prop):
    return find(root_, lambda b: b.get('type') == 'component_set_get' and
                [c for c in b if tg(c) == 'mutation'][0].get('instance_name') == inst and
                [c for c in b if tg(c) == 'mutation'][0].get('property_name') == prop)


def replace_value(vblk, novo):
    for x in list(vblk):
        vblk.remove(x)
    vblk.append(novo)


@mutante('grafico: cores trocadas (Entradas vermelho, Despesas verde)', ['T21', 'T27'])
def g1(root):
    p = proc(root, 'atualizarGrafico')
    cores = [b for b in p.iter(NS + 'block') if b.get('type') == 'color_make_color']
    assert len(cores) == 2
    for a, b in zip(cores[0].iter(NS + 'block'), cores[1].iter(NS + 'block')):
        if a.get('type') == 'math_number':
            fa, fb = field(a, 'NUM'), field(b, 'NUM')
            fa.text, fb.text = fb.text, fa.text


@mutante('grafico: envia lista de cores VAZIA quando nao ha lancamentos (sem o "se tem cor")', ['T21', 'T14'])
def g2(root):
    p = proc(root, 'atualizarGrafico')
    guard = find(p, lambda b: b.get('type') == 'controls_if' and
                 any(x.get('type') == 'component_set_get' and
                     [c for c in x if tg(c) == 'mutation'][0].get('property_name') == 'Colors' for x in b.iter(NS + 'block')))
    replace_value(val(guard, 'IF0'), dsl(G.boolean(True)))


@mutante('grafico: fatia Entradas sempre criada (mesmo com total zero)', ['T21', 'T14'])
def g3(root):
    p = proc(root, 'atualizarGrafico')
    ifs = [b for b in p.iter(NS + 'block') if b.get('type') == 'controls_if']
    replace_value(val(ifs[0], 'IF0'), dsl(G.boolean(True)))


@mutante('grafico: fatia Despesas usa o total de ENTRADAS', ['T21'])
def g4(root):
    p = proc(root, 'atualizarGrafico')
    add = [b for b in p.iter(NS + 'block') if b.get('type') == 'component_method' and
           [c for c in b if tg(c) == 'mutation'][0].get('method_name') == 'AddEntry'][1]
    for v in add.iter(NS + 'block'):
        if v.get('type') == 'lexical_variable_get':
            field(v, 'VAR').text = 'global totalEntradas'
            return
    raise KeyError


@mutante('porcentagem: Despesas mostra a mesma % das Entradas (complemento esquecido)', ['T21'])
def g5(root):
    p = proc(root, 'atualizarGrafico')
    st = comp_set(p, 'LblLegDespPct', 'Text')
    call_ = val(st, 'VALUE')[0]
    arg = val(call_, 'ARG0')
    sub = arg[0]
    assert sub.get('type') == 'math_subtract'
    replace_value(arg, val(sub, 'B')[0])


def _round_para(root, rotulo, op):
    """Troca o OP do bloco 'arredondar' que calcula a porcentagem do rotulo dado (dentro de atualizarGrafico)."""
    p = proc(root, 'atualizarGrafico')
    st = comp_set(p, rotulo, 'Text')
    for b in st.iter(NS + 'block'):
        if b.get('type') == 'math_round':
            assert field(b, 'OP').text == 'ROUND'
            field(b, 'OP').text = op
            return
    raise KeyError(rotulo)


@mutante('porcentagem das Entradas: arredonda para baixo (FLOOR) em vez de arredondar', ['T21'])
def g6(root):
    _round_para(root, 'LblLegEntPct', 'FLOOR')


@mutante('porcentagem das Despesas (complemento): arredonda para baixo (FLOOR) em vez de arredondar', ['T21'])
def g6b(root):
    _round_para(root, 'LblLegDespPct', 'FLOOR')


@mutante('porcentagem das Entradas: arredonda sempre para cima (CEILING)', ['T21'])
def g6c(root):
    _round_para(root, 'LblLegEntPct', 'CEILING')


@mutante('formatarPercentual: ponto no lugar da virgula (33.3%)', ['T21', 'T26'])
def g7(root):
    p = top(root, 'procedures_defreturn', 'formatarPercentual')
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'text' and field(b, 'TEXT').text == ',':
            field(b, 'TEXT').text = '.'
            return
    raise KeyError


@mutante('grafico: pizza visivel mesmo sem lancamentos (>= em vez de >)', ['T21', 'T14'])
def g8(root):
    p = proc(root, 'atualizarGrafico')
    st = comp_set(p, 'Chart1', 'Visible')
    cmp_ = val(st, 'VALUE')[0]
    field(cmp_, 'OP').text = 'GTE'


@mutante('legenda: valor das Entradas mostra o total de despesas', ['T21'])
def g9(root):
    p = proc(root, 'atualizarGrafico')
    st = comp_set(p, 'LblLegEntValor', 'Text')
    for v in st.iter(NS + 'block'):
        if v.get('type') == 'lexical_variable_get':
            field(v, 'VAR').text = 'global totalDespesas'
            return
    raise KeyError


@mutante('historico: icones trocados (entrada com seta de despesa)', ['T22'])
def h1(root):
    p = proc(root, 'atualizarHistorico')
    ts = [b for b in p.iter(NS + 'block') if b.get('type') == 'text' and field(b, 'TEXT').text in ('seta_entrada.png', 'seta_despesa.png')]
    assert len(ts) == 2
    a, b = field(ts[0], 'TEXT'), field(ts[1], 'TEXT')
    a.text, b.text = b.text, a.text


@mutante('historico: sinais trocados (+ nas despesas, - nas entradas)', ['T22', 'T06'])
def h2(root):
    p = proc(root, 'atualizarHistorico')
    ts = [b for b in p.iter(NS + 'block') if b.get('type') == 'text' and field(b, 'TEXT').text in ('+ ', '− ')]
    assert len(ts) == 2
    a, b = field(ts[0], 'TEXT'), field(ts[1], 'TEXT')
    a.text, b.text = b.text, a.text


@mutante('abas: aba ativa (Lancar) continua com a imagem de inativa', ['T23'])
def a1(root):
    p = proc(root, 'pintarAbas')
    st = comp_set(p, 'BtnNavLancar', 'Image')
    ch = val(st, 'VALUE')[0]
    t, e = val(ch, 'THENRETURN')[0], val(ch, 'ELSERETURN')[0]
    field(t, 'TEXT').text, field(e, 'TEXT').text = field(e, 'TEXT').text, field(t, 'TEXT').text


@mutante('abas: texto da aba ativa (Historico) nao fica branco', ['T23'])
def a2(root):
    p = proc(root, 'pintarAbas')
    st = comp_set(p, 'BtnNavHistorico', 'TextColor')
    ch = val(st, 'VALUE')[0]
    cor_ativa = val(ch, 'THENRETURN')[0]
    nums = [b for b in cor_ativa.iter(NS + 'block') if b.get('type') == 'math_number']
    for n, v in zip(nums, ('86', '104', '98')):
        field(n, 'NUM').text = v


@mutante('dialogo de apagar tudo volta a "TODOS" em maiuscula', ['T08', 'T24', 'T00'])
def d1(root):
    h = top(root, 'component_event', inst='BtnLimpar', ev='Click')
    for b in h.iter(NS + 'block'):
        if b.get('type') == 'text' and field(b, 'TEXT').text == 'Apagar todos os lançamentos?':
            field(b, 'TEXT').text = 'Apagar TODOS os lançamentos?'
            return
    raise KeyError


@mutante('cabecalho: "Entradas" mostra o total de despesas', ['T04', 'T07'])
def c1(root):
    p = proc(root, 'atualizarTudo')
    st = comp_set(p, 'LblEntradas', 'Text')
    for v in st.iter(NS + 'block'):
        if v.get('type') == 'lexical_variable_get':
            field(v, 'VAR').text = 'global totalDespesas'
            return
    raise KeyError


@mutante('registrar: mensagem de sucesso errada para entrada', ['T05', 'T04'])
def r1(root):
    p = proc(root, 'registrar')
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'text' and field(b, 'TEXT').text == 'Entrada registrada!':
            field(b, 'TEXT').text = 'Despesa registrada!'
            return
    raise KeyError


@mutante('registrar: nao limpa o campo de valor depois de salvar', ['T04'])
def r2(root):
    # v1.8: quem limpa o campo e o limparFormulario (o 1o TxtValor.Text do registrar e a LEITURA da validacao)
    st = [b for b in sets(proc(root, 'limparFormulario'), 'TxtValor', 'Text')
          if [c for c in b if tg(c) == 'mutation'][0].get('set_or_get') == 'set']
    assert len(st) == 1
    splice_out(root, st[0])


@mutante('migracao: converte reais em centavos multiplicando por 10', ['T09'])
def r3(root):
    p = proc(root, 'carregarDados')
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'math_multiply':
            for n in b.iter(NS + 'block'):
                if n.get('type') == 'math_number' and field(n, 'NUM').text == '100':
                    field(n, 'NUM').text = '10'
                    return
    raise KeyError


# ------------------------------------------------------------------ mutantes na TELA (.scm / imagens): pacote inteiro remontado
import json  # noqa: E402
import zipfile  # noqa: E402


# ------------------------------------------------------------------ v1.5: icones, erros inline, faixa de aviso, resumo do grafico
def glob(root, nome):
    return find(root, lambda b: b.get('type') == 'global_declaration' and field(b, 'NAME').text == nome)


def sets(p, inst, prop):
    return [b for b in p.iter(NS + 'block') if b.get('type') == 'component_set_get' and
            [c for c in b if tg(c) == 'mutation'][0].get('instance_name') == inst and
            [c for c in b if tg(c) == 'mutation'][0].get('property_name') == prop]


def textos(p, t):
    return [b for b in p.iter(NS + 'block') if b.get('type') == 'text' and field(b, 'TEXT').text == t]


@mutante('lista de categorias: lista de pagamento no lugar de uma categoria (Lazer -> Pix)', ['T00', 'T01', 'T28'])
def n0(root):
    field(textos(glob(root, 'listaCats'), 'Lazer')[0], 'TEXT').text = 'Pix'


@mutante('icones das categorias: Alimentacao e Transporte com icones trocados', ['T28'])
def n1(root):
    t = [b for b in glob(root, 'listaCatIcones').iter(NS + 'block') if b.get('type') == 'text']
    a, b = field(t[0], 'TEXT'), field(t[1], 'TEXT')
    a.text, b.text = b.text, a.text


@mutante('lista de pagamento usa os icones das categorias', ['T28'])
def n2(root):
    p = proc(root, 'abrirPicker')
    n = 0
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'lexical_variable_get' and field(b, 'VAR').text == 'global listaPagIcones':
            field(b, 'VAR').text = 'global listaCatIcones'
            n += 1
    assert n


@mutante('escolher forma de pagamento grava na CATEGORIA (os dois se misturam)', ['T02', 'T28'])
def n3(root):
    h = top(root, 'component_event', inst='ListaOpcoes', ev='AfterPicking')
    for b in h.iter(NS + 'block'):
        if b.get('type') == 'lexical_variable_set' and field(b, 'VAR').text == 'global pagamentoSel':
            field(b, 'VAR').text = 'global categoriaSel'
            return
    raise KeyError


@mutante('valor invalido: a frase de erro nao aparece sob o campo (Visible nunca vira TRUE)', ['T29', 'T03'])
def n4(root):
    p = proc(root, 'registrar')
    splice_out(root, sets(p, 'LblErroValor', 'Visible')[1])


@mutante('TxtValor.TextChanged removido: o erro do valor nunca some ao digitar', ['T29'])
def n5(root):
    root.remove(top(root, 'component_event', inst='TxtValor', ev='TextChanged'))


@mutante('mostrarAviso: faixa de ERRO tambem some sozinha (timer sempre ligado)', ['T30'])
def n6(root):
    p = proc(root, 'mostrarAviso')
    replace_value(val(sets(p, 'ClockAviso', 'TimerEnabled')[0], 'VALUE'), dsl(G.boolean(True)))


@mutante('mostrarAviso: imagens verde/vermelha da faixa trocadas', ['T30'])
def n7(root):
    p = proc(root, 'mostrarAviso')
    a = [b for b in p.iter(NS + 'block') if b.get('type') == 'lexical_variable_get' and field(b, 'VAR').text == 'global imgAvisoOk'][0]
    b = [b for b in p.iter(NS + 'block') if b.get('type') == 'lexical_variable_get' and field(b, 'VAR').text == 'global imgAvisoErro'][0]
    field(a, 'VAR').text, field(b, 'VAR').text = 'global imgAvisoErro', 'global imgAvisoOk'


@mutante('resumo do grafico mostra 5 lancamentos por tipo em vez de 3', ['T31'])
def n8(root):
    p = proc(root, 'atualizarResumo')
    n = 0
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'math_compare' and field(b, 'OP').text == 'LT':
            bb = val(b, 'B')[0]
            if bb.get('type') == 'math_number' and field(bb, 'NUM').text == '3':
                field(bb, 'NUM').text = '5'
                n += 1
    assert n == 2


@mutante('resumo do grafico: entradas sem o sinal + (aparece "- ")', ['T31'])
def n9(root):
    field(textos(proc(root, 'atualizarResumo'), '+ ')[0], 'TEXT').text = '- '


@mutante('abrirPicker nao esconde o formulario (lista fica empilhada com ele)', ['T01', 'T28'])
def n10(root):
    splice_out(root, sets(proc(root, 'abrirPicker'), 'PnlLancar', 'Visible')[0])


@mutante('limparErros nao esconde a faixa de aviso anterior', ['T30'])
def n11(root):
    splice_out(root, sets(proc(root, 'limparErros'), 'BoxAviso', 'Visible')[0])


@mutante('registrar: apos salvar o icone da categoria nao volta ao neutro', ['T28'])
def n12(root):
    # v1.7: quem limpa o formulario depois de salvar e limparFormulario
    p = proc(root, 'limparFormulario')
    st = [b for b in p.iter(NS + 'block') if b.get('type') == 'lexical_variable_set' and field(b, 'VAR').text == 'global categoriaIcone'][0]
    splice_out(root, st)


@mutante('abreviar: corta em 10 caracteres em vez de 17', ['T31'])
def n13(root):
    p = top(root, 'procedures_defreturn', 'abreviar')
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'math_number' and field(b, 'NUM').text == '17':
            field(b, 'NUM').text = '10'
            return
    raise KeyError


@mutante('mensagens de erro de categoria e pagamento trocadas entre si', ['T29', 'T11', 'T01', 'T02'])
def n14(root):
    p = proc(root, 'registrar')
    a, b = textos(p, 'Escolha uma categoria.')[0], textos(p, 'Escolha a forma de pagamento.')[0]
    field(a, 'TEXT').text, field(b, 'TEXT').text = 'Escolha a forma de pagamento.', 'Escolha uma categoria.'


@mutante('mostrarAba nao fecha a lista de opcoes ao trocar de aba', ['T28'])
def n15(root):
    splice_out(root, sets(proc(root, 'mostrarAba'), 'PnlPicker', 'Visible')[0])


@mutante('"Ver historico completo" abre o grafico em vez do historico', ['T31'])
def n16(root):
    h = top(root, 'component_event', inst='BtnVerHist', ev='Click')
    for b in h.iter(NS + 'block'):
        if b.get('type') == 'math_number' and field(b, 'NUM').text == '2':
            field(b, 'NUM').text = '3'
            return
    raise KeyError


@mutante('ClockAviso.Timer nao esconde a faixa (so desliga o timer)', ['T30'])
def n17(root):
    h = top(root, 'component_event', inst='ClockAviso', ev='Timer')
    splice_out(root, sets(h, 'BoxAviso', 'Visible')[0])


@mutante('falha de gravacao: mostra faixa VERDE de sucesso (falso salvo)', ['T10', 'T30'])
def n18(root):
    p = ramo_registrar(root, 'repOk')          # v1.8: a falha ao salvar um lancamento NOVO (a do editar tem mutante proprio)
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'procedures_callnoreturn' and field(b, 'PROCNAME').text == 'mostrarAviso':
            v = val(b, 'ARG0')[0]
            if v.get('type') == 'logic_boolean' and field(v, 'BOOL').text == 'FALSE':
                field(v, 'BOOL').text = 'TRUE'
                return
    raise KeyError



# ------------------------------------------------------------------ v1.6: grafico por categoria, tema, perfil
def defret(root, nome):
    return top(root, 'procedures_defreturn', nome)


def call_of(p, nome):
    return [b for b in p.iter(NS + 'block') if b.get('type') in ('procedures_callnoreturn', 'procedures_callreturn') and field(b, 'PROCNAME').text == nome]


def nums(p, valor):
    return [b for b in p.iter(NS + 'block') if b.get('type') == 'math_number' and field(b, 'NUM').text == str(valor)]


def gets(p, var):
    return [b for b in p.iter(NS + 'block') if b.get('type') == 'lexical_variable_get' and field(b, 'VAR').text == var]


@mutante('categorias: ENTRADAS tambem contadas como gasto (some o "nao e Entrada")', ['T32'])
def q0(root):
    p = proc(root, 'atualizarCategorias')
    neg = [b for b in p.iter(NS + 'block') if b.get('type') == 'logic_negate'][0]
    inner = val(neg, 'BOOL')[0]
    pm = parent_map(root)
    holder = pm[neg]
    holder.remove(neg)
    holder.append(inner)


@mutante('categorias: ordena da MENOR para a maior', ['T32'])
def q1(root):
    p = proc(root, 'atualizarCategorias')
    n = 0
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'math_compare' and field(b, 'OP').text == 'GT':
            a = val(b, 'A')[0]
            bb = val(b, 'B')[0]
            if a.get('type') == 'lexical_variable_get' and field(a, 'VAR').text == 't' and bb.get('type') == 'lexical_variable_get' and field(bb, 'VAR').text == 'melhorVal':
                field(b, 'OP').text = 'LT'
                n += 1
    assert n == 1, n


@mutante('categorias: porcentagem calculada com x100 em vez de x1000 (10x menor)', ['T32'])
def q2(root):
    p = proc(root, 'pintarLinhaCat')         # v1.7: a linha da categoria e um procedimento so
    ns = nums(p, 1000)
    assert len(ns) == 1, len(ns)
    for b in ns:
        field(b, 'NUM').text = '100'


@mutante('larguraBarra: a maior barra ocupa 100% em vez de 72%', ['T32'])
def q3(root):
    p = defret(root, 'larguraBarra')
    ns = nums(p, G.T.BARRA_MAX)
    assert len(ns) == 2, len(ns)          # a expressao aparece duas vezes (teste e resultado do CHOOSE)
    for b in ns:
        field(b, 'NUM').text = '100'


@mutante('larguraBarra: sem a largura minima de 1% (gasto minusculo fica sem barra)', ['T32'])
def q4(root):
    p = defret(root, 'larguraBarra')
    # CHOOSE(x < 1, 1, x) -> troca o "1" devolvido por 0
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'controls_choose':
            th = val(b, 'THENRETURN')[0]
            if th.get('type') == 'math_number' and field(th, 'NUM').text == '1':
                te = val(b, 'TEST')[0]
                if te.get('type') == 'math_compare' and field(te, 'OP').text == 'LT':
                    field(th, 'NUM').text = '0'
                    return
    raise KeyError


@mutante('indiceCategoria: categoria desconhecida cai em Alimentacao (1) em vez de Outros (8)', ['T32'])
def q5(root):
    p = defret(root, 'indiceCategoria')
    ns = nums(p, 8)
    assert len(ns) == 1
    field(ns[0], 'NUM').text = '1'


@mutante('categorias: icones das FORMAS DE PAGAMENTO nas linhas de categoria', ['T32'])
def q6(root):
    p = proc(root, 'pintarLinhaCat')
    g = gets(p, 'global listaCatIcones')
    assert len(g) == 1
    for b in g:
        field(b, 'VAR').text = 'global listaPagIcones'


@mutante('categorias: linhas que sobram nao sao escondidas (categorias sem gasto continuam na tela)', ['T32'])
def q7(root):
    p = proc(root, 'atualizarCategorias')
    n = 0
    for b in p.iter(NS + 'block'):
        if b.get('type') == 'controls_if' and [c for c in b if tg(c) == 'mutation' and c.get('else') == '1']:
            els = [c for c in b if tg(c) == 'statement' and c.get('name') == 'ELSE']
            if not els:
                continue
            st = els[0][0]
            m = [c for c in st if tg(c) == 'mutation'][0] if st.get('type') == 'component_set_get' else None
            if m is not None and m.get('is_generic') == 'true' and m.get('property_name') == 'Visible':
                v = val(st, 'VALUE')[0]
                field(v, 'BOOL').text = 'TRUE'
                n += 1
    assert n == 1, n


@mutante('categorias: barra proporcional ao TOTAL e nao a maior categoria (a maior nunca chega a 72%)', ['T32'])
def q8(root):
    p = proc(root, 'atualizarCategorias')
    c_ = call_of(p, 'pintarLinhaCat')
    assert len(c_) == 1
    replace_value(val(c_[0], 'ARG5'), dsl(G.lget('total')))     # 'maior' = total de despesas


@mutante('atualizarGrafico nao atualiza o grafico por categoria', ['T32'])
def q9(root):
    p = proc(root, 'atualizarGrafico')
    splice_out(root, call_of(p, 'atualizarCategorias')[0])


@mutante('definirTema: no escuro, a cor de TEXTO continua a do tema claro (texto some no fundo escuro)', ['T33'])
def q10(root):
    p = proc(root, 'definirTema')
    sets_ = [b for b in p.iter(NS + 'block') if b.get('type') == 'lexical_variable_set' and field(b, 'VAR').text == 'global corTexto']
    assert len(sets_) == 2
    # o primeiro "set" esta no ramo escuro (IF temaEscuro -> ramo(1))
    replace_value(val(sets_[0], 'VALUE'), dsl(G.rgbh(G.T.INK)))


@mutante('definirTema: no escuro, o FUNDO da tela continua claro', ['T33'])
def q11(root):
    p = proc(root, 'definirTema')
    sets_ = [b for b in p.iter(NS + 'block') if b.get('type') == 'lexical_variable_set' and field(b, 'VAR').text == 'global corFundo']
    assert len(sets_) == 2
    replace_value(val(sets_[0], 'VALUE'), dsl(G.rgbh(G.T.BG)))


@mutante('trocarTema: nao guarda a escolha (volta ao claro ao reabrir)', ['T33'])
def q12(root):
    p = proc(root, 'trocarTema')
    splice_out(root, call_of(p, 'guardarPref')[0])


@mutante('carregarPreferencias: le "claro" como escuro (app abre escuro para quem nunca escolheu)', ['T33', 'T35'])
def q13(root):
    p = proc(root, 'carregarPreferencias')
    t = [b for b in p.iter(NS + 'block') if b.get('type') == 'text' and field(b, 'TEXT').text == 'escuro'][0]
    field(t, 'TEXT').text = 'claro'


@mutante('aplicarTema: esquece de repintar o 2o terco dos componentes', ['T33'])
def q14(root):
    p = proc(root, 'aplicarTema')
    splice_out(root, call_of(p, 'pintarTema2')[0])


@mutante('aplicarTema: esquece de repintar o 3o terco dos componentes', ['T33'])
def q15(root):
    p = proc(root, 'aplicarTema')
    splice_out(root, call_of(p, 'pintarTema3')[0])


@mutante('pintarEstados: campo com erro perde a borda vermelha ao trocar de tema', ['T33'])
def q16(root):
    p = proc(root, 'pintarEstados')
    st = sets(p, 'HzCampoValor', 'Image')      # v1.8: ha outro campo com borda de erro (valor da meta); mira o TxtValor
    assert len(st) == 1
    g = gets(val(st[0], 'VALUE'), 'global imgCampoErro')   # so o valor (o bloco carrega os seguintes em <next>)
    assert len(g) == 1
    field(g[0], 'VAR').text = 'global imgCampo'


@mutante('ImgTema.Click: passa o tema atual (o botao do cabecalho nao troca nada)', ['T33'])
def q17(root):
    h = top(root, 'component_event', inst='ImgTema', ev='Click')
    neg = [b for b in h.iter(NS + 'block') if b.get('type') == 'logic_negate'][0]
    inner = val(neg, 'BOOL')[0]
    pm = parent_map(root)
    holder = pm[neg]
    holder.remove(neg)
    holder.append(inner)


@mutante('pintarAbas: opcao "Escuro" destacada quando o tema e claro (e vice-versa)', ['T33'])
def q18(root):
    p = proc(root, 'pintarAbas')
    # BtnTemaClaro usa NOT(temaEscuro); BtnTemaEscuro usa temaEscuro -> troca as duas imagens
    sets_ = [b for b in p.iter(NS + 'block') if b.get('type') == 'component_set_get' and
             [c for c in b if tg(c) == 'mutation'][0].get('instance_name') in ('BtnTemaClaro', 'BtnTemaEscuro') and
             [c for c in b if tg(c) == 'mutation'][0].get('property_name') == 'Image']
    assert len(sets_) == 2
    m0 = [c for c in sets_[0] if tg(c) == 'mutation'][0]
    m1 = [c for c in sets_[1] if tg(c) == 'mutation'][0]
    m0.set('instance_name', 'BtnTemaEscuro'); m1.set('instance_name', 'BtnTemaClaro')
    field(sets_[0], 'COMPONENT_SELECTOR').text = 'BtnTemaEscuro'
    field(sets_[1], 'COMPONENT_SELECTOR').text = 'BtnTemaClaro'


@mutante('guardarPref: sempre diz que guardou (prefOk nunca e falso)', ['T33', 'T34'])
def q19(root):
    p = proc(root, 'guardarPref')
    st = [b for b in p.iter(NS + 'block') if b.get('type') == 'lexical_variable_set' and field(b, 'VAR').text == 'global prefOk'][0]
    replace_value(val(st, 'VALUE'), dsl(G.boolean(True)))


@mutante('mostrarPerfil: saudacao com o nome inteiro em vez do primeiro nome', ['T34'])
def q20(root):
    p = proc(root, 'mostrarPerfil')
    c = call_of(p, 'primeiroNome')[0]
    pm = parent_map(root)
    holder = pm[c]
    holder.remove(c)
    holder.append(dsl(G.gget('perfilNome')))


@mutante('mostrarPerfil: foto do perfil encostada na esquerda (X = 0) em vez de centralizada', ['T34'])
def q21(root):
    p = proc(root, 'mostrarPerfil')
    sets_ = [b for b in p.iter(NS + 'block') if b.get('type') == 'component_set_get' and
             [c for c in b if tg(c) == 'mutation'][0].get('instance_name') == 'SprFotoPerfil' and
             [c for c in b if tg(c) == 'mutation'][0].get('property_name') == 'X']
    assert len(sets_) == 1
    replace_value(val(sets_[0], 'VALUE'), dsl(G.num(0)))


@mutante('mostrarPerfil: foto deformada (altura = largura do avatar, sem respeitar a proporcao)', ['T34'])
def q22(root):
    p = proc(root, 'mostrarPerfil')
    sets_ = [b for b in p.iter(NS + 'block') if b.get('type') == 'component_set_get' and
             [c for c in b if tg(c) == 'mutation'][0].get('set_or_get') == 'set' and
             [c for c in b if tg(c) == 'mutation'][0].get('instance_name') == 'SprFotoPerfil' and
             [c for c in b if tg(c) == 'mutation'][0].get('property_name') == 'Height']
    assert len(sets_) == 2, len(sets_)            # Height(-1) e Height(h)
    alvo = [b for b in sets_ if val(b, 'VALUE')[0].get('type') == 'lexical_variable_get'][0]
    replace_value(val(alvo, 'VALUE'), dsl(G.lget('w')))


@mutante('mostrarPerfil: sprite visivel mesmo quando a foto nao abre (divisao por zero)', ['T34'])
def q23(root):
    p = proc(root, 'mostrarPerfil')
    n = 0
    for b in list(p.iter(NS + 'block')):
        if b.get('type') == 'logic_operation' and field(b, 'OP').text == 'AND':
            a = val(b, 'A')[0]
            if a.get('type') == 'math_compare' and val(a, 'A')[0].get('type') == 'lexical_variable_get' and field(val(a, 'A')[0], 'VAR').text == 'wn':
                pm = parent_map(root)
                holder = pm[b]
                holder.remove(b)
                holder.append(dsl(G.boolean(True)))
                n += 1
    assert n == 2, n


@mutante('BtnSalvarPerfil: da o nome como salvo mesmo quando a gravacao falha', ['T34'])
def q24(root):
    h = top(root, 'component_event', inst='BtnSalvarPerfil', ev='Click')
    g = gets(h, 'global prefOk')
    assert len(g) == 1
    pm = parent_map(root)
    holder = pm[g[0]]
    holder.remove(g[0])
    holder.append(dsl(G.boolean(True)))


@mutante('PickerFoto.AfterPicking: nao guarda a foto (some ao reabrir)', ['T34'])
def q25(root):
    h = top(root, 'component_event', inst='PickerFoto', ev='AfterPicking')
    splice_out(root, call_of(h, 'guardarPref')[0])


@mutante('BtnRemoverFoto: so esconde a foto, nao apaga o caminho guardado', ['T34'])
def q26(root):
    # v1.8.1: quem remove e o "Remover foto" da janela de confirmacao (ramo de Notifier1.AfterChoosing)
    h = top(root, 'component_event', inst='Notifier1', ev='AfterChoosing')
    ramo = [x for x in h.iter(NS + 'block') if x.get('type') == 'controls_if' and filho(x, 'IF0') is not None
            and any(y.get('type') == 'text' and (field(y, 'TEXT').text or '') == 'Remover foto' for y in filho(x, 'IF0').iter(NS + 'block'))]
    assert len(ramo) == 1, len(ramo)
    st = [x for x in ramo[0].iter(NS + 'block') if x.get('type') == 'lexical_variable_set' and field(x, 'VAR').text == 'global perfilFoto']
    assert len(st) == 1, len(st)
    splice_out(root, st[0])


@mutante('mostrarAba: o perfil aparece junto com a aba Grafico (condicao aba = 3)', ['T34', 'T14'])
def q27(root):
    p = proc(root, 'mostrarAba')
    st = [b for b in p.iter(NS + 'block') if b.get('type') == 'component_set_get' and
          [c for c in b if tg(c) == 'mutation'][0].get('instance_name') == 'PnlPerfil'][0]
    cond = val(st, 'VALUE')[0]
    nb = val(cond, 'B')[0]
    assert field(nb, 'NUM').text == '4'
    field(nb, 'NUM').text = '3'


@mutante('abrirPerfil: nao lembra de que aba veio (Voltar sempre cai em Lancar)', ['T34'])
def q28(root):
    p = proc(root, 'abrirPerfil')
    st = [b for b in p.iter(NS + 'block') if b.get('type') == 'lexical_variable_set' and field(b, 'VAR').text == 'global abaVolta'][0]
    splice_out(root, st)


@mutante('primeiroNome: devolve o primeiro nome COM o espaco', ['T34'])
def q29(root):
    p = defret(root, 'primeiroNome')
    sub = [b for b in p.iter(NS + 'block') if b.get('type') == 'math_subtract'][0]
    pm = parent_map(root)
    holder = pm[sub]
    holder.remove(sub)
    holder.append(dsl(G.lget('fim')))


@mutante('Screen1.Initialize: nao mostra o perfil ao abrir (saudacao e foto so depois de salvar)', ['T34'])
def q30(root):
    h = top(root, 'component_event', inst='Screen1', ev='Initialize')
    splice_out(root, call_of(h, 'mostrarPerfil')[0])


@mutante('TxtNome.TextChanged removido: "Perfil salvo!" nunca some ao editar', ['T34'])
def q31(root):
    root.remove(top(root, 'component_event', inst='TxtNome', ev='TextChanged'))


@mutante('CanvasPerfil.Touched: tocar no avatar grande nao abre a galeria', ['T34'])
def q32(root):
    root.remove(top(root, 'component_event', inst='CanvasPerfil', ev='Touched'))


@mutante('mostrarPerfil: "Remover foto" sempre visivel (mesmo sem foto)', ['T34'])
def q33(root):
    p = proc(root, 'mostrarPerfil')
    st = [b for b in p.iter(NS + 'block') if b.get('type') == 'component_set_get' and
          [c for c in b if tg(c) == 'mutation'][0].get('instance_name') == 'BtnRemoverFoto'][0]
    replace_value(val(st, 'VALUE'), dsl(G.boolean(True)))


TELA = []


def tela(rotulo, esperado):
    def deco(fn):
        TELA.append((rotulo, esperado, fn))
        return fn
    return deco


def scm_nodes(d):
    out = {}

    def rec(n):
        out[n['$Name']] = n
        for c in n.get('$Components', []):
            rec(c)
    rec(d['Properties'])
    return out


@tela('TxtValor: teclado so numerico (impede a virgula)', ['T00'])
def s1(d, pkg):
    scm_nodes(d)['TxtValor']['NumbersOnly'] = 'True'


@tela('TinyDB: Namespace diferente (os dados salvos "sumiriam" na atualizacao)', ['T00'])
def s2(d, pkg):
    scm_nodes(d)['TinyDB1']['Namespace'] = 'Conto2'


@tela('Chart1 deixa de ser pizza (Type 4 -> 0)', ['T00'])
def s4(d, pkg):
    scm_nodes(d)['Chart1']['Type'] = '0'


@tela('ListaHistorico: FontSize volta a ser TextSize (propriedade inexistente, o defeito real da v1.3)', ['T25'])
def s5(d, pkg):
    n = scm_nodes(d)['ListaHistorico']
    n['TextSize'] = n.pop('FontSize')


@tela('Imagem do cabecalho aponta para arquivo que nao existe', ['T25'])
def s6(d, pkg):
    scm_nodes(d)['CardSaldo']['Image'] = 'fundo_topo_x.png'


@tela('Dica dos campos clara demais (contraste ~2:1)', ['T27'])
def s7(d, pkg):
    scm_nodes(d)['TxtDescricao']['HintColor'] = '&HFFB8C4BF'


@tela('Numeros pequenos dentro das fatias voltam a aparecer (DataLabelColor branco)', ['T27'])
def s8(d, pkg):
    scm_nodes(d)['ChartData2D1']['DataLabelColor'] = '&HFFFFFFFF'


@tela('Ponto da legenda de Entradas fica vermelho', ['T27'])
def s9(d, pkg):
    scm_nodes(d)['ImgLegEnt']['Picture'] = 'ponto_vermelho.png'


@tela('Componente usado pelos blocos renomeado na tela (LblSaldo -> LblSaldoX)', ['T00', 'T25'])
def s10(d, pkg):
    scm_nodes(d)['LblSaldo']['$Name'] = 'LblSaldoX'


@tela('Texto "Saldo atual" do cabecalho com texto claro demais sobre o verde (contraste)', ['T27'])
def s11(d, pkg):
    scm_nodes(d)['LblCapDespesas']['TextColor'] = '&HFF7FB5A6'


@tela('Seta de despesa pintada de verde (icone nao bate com a cor do grafico)', ['T27'])
def s12(d, pkg):
    from PIL import Image
    p = os.path.join(pkg, 'assets', 'seta_despesa.png')
    shutil.copy(os.path.join(pkg, 'assets', 'seta_entrada.png'), p)



@tela('Icone de Moradia vira copia do icone de Lazer (imagem repetida)', ['T28'])
def s13(d, pkg):
    shutil.copy(os.path.join(pkg, 'assets', 'ic_cat_lazer.png'), os.path.join(pkg, 'assets', 'ic_cat_moradia.png'))


@tela('Frase de erro do valor clara demais (contraste baixo)', ['T27'])
def s14(d, pkg):
    scm_nodes(d)['LblErroValor']['TextColor'] = '&HFFE79DA0'


@tela('Lista de opcoes volta a altura "preencher" (colapsa dentro do painel automatico)', ['T28'])
def s15(d, pkg):
    scm_nodes(d)['ListaOpcoes']['Height'] = '-2'


@tela('Lista de opcoes com layout so de texto (sem os icones)', ['T28'])
def s16(d, pkg):
    scm_nodes(d)['ListaOpcoes']['ListViewLayout'] = '0'


@tela('Faixa de aviso: tempo de 30 s em vez de 3 s', ['T30'])
def s17(d, pkg):
    scm_nodes(d)['ClockAviso']['TimerInterval'] = '30000'



@tela('Cartao das linhas do historico ja nasce escuro no tema claro', ['T33'])
def s18(d, pkg):
    scm_nodes(d)['ListaHistorico']['ElementColor'] = '&HFF17221F'


@tela('Moldura redonda do perfil ATRAS da foto (Z trocado): a foto sai quadrada', ['T34'])
def s19(d, pkg):
    scm_nodes(d)['SprMascaraPerfil']['Z'] = '0'


@tela('Canvas do avatar do perfil com o tamanho do avatar (a foto e empurrada para o canto)', ['T34'])
def s20(d, pkg):
    scm_nodes(d)['CanvasPerfil']['Width'] = '96'
    scm_nodes(d)['CanvasPerfil']['Height'] = '96'


@tela('Moldura do avatar do cabecalho na cor do cartao branco (quadrado branco em volta da foto)', ['T34'])
def s21(d, pkg):
    shutil.copy(os.path.join(pkg, 'assets', 'mascara_cartao.png'), os.path.join(pkg, 'assets', 'mascara_topo.png'))


@tela('Avatar padrao escuro identico ao claro', ['T33'])
def s22(d, pkg):
    shutil.copy(os.path.join(pkg, 'assets', 'avatar_padrao.png'), os.path.join(pkg, 'assets', 'avatar_padrao_d.png'))


@tela('Painel do perfil visivel desde o inicio', ['T34'])
def s23(d, pkg):
    scm_nodes(d)['PnlPerfil']['Visible'] = 'True'


@tela('Porcentagem das categorias clara demais (contraste baixo no grafico)', ['T27'])
def s24(d, pkg):
    for i in range(1, 9):
        scm_nodes(d)['LblCatPct%d' % i]['TextColor'] = '&HFFC9D6D0'


@tela('Largura da foto do perfil em porcentagem (o editor nao aceita para ImageSprite)', ['T25'])
def s25(d, pkg):
    scm_nodes(d)['SprFotoPerfil']['Width'] = '-1050'


@tela('Trilho das barras ja nasce escuro no tema claro', ['T33'])
def s26(d, pkg):
    scm_nodes(d)['HzCatTrilho1']['BackgroundColor'] = '&HFF2A3834'


@tela('Botao do tema no cabecalho sem o toque (Clickable falso)', ['T33'])
def s27(d, pkg):
    scm_nodes(d)['ImgTema']['Clickable'] = 'False'



# ------------------------------------------------------------------ v1.7
def procr(root, nome):
    for t in ('procedures_defnoreturn', 'procedures_defreturn'):
        try:
            return top(root, t, nome)
        except KeyError:
            pass
    raise KeyError(nome)


def evento(root, inst, ev):
    return top(root, 'component_event', inst=inst, ev=ev)


def blocos(p, tipo, pred=lambda b: True):
    return [b for b in p.iter(NS + 'block') if b.get('type') == tipo and pred(b)]


def filho(b, nome):
    v = val(b, nome)
    return v[0] if v is not None and len(v) else None


def eh_get(b, var):
    return b is not None and b.get('type') == 'lexical_variable_get' and field(b, 'VAR').text == var


def eh_num(b, n):
    return b is not None and b.get('type') == 'math_number' and field(b, 'NUM').text == str(n)


def textos(p, t):
    return blocos(p, 'text', lambda b: (field(b, 'TEXT').text or '') == t)


def sets_var(p, var):
    return blocos(p, 'lexical_variable_set', lambda b: field(b, 'VAR').text == var)


def trocar_bloco(root, velho, novo):
    replace_value(parent_map(root)[velho], dsl(novo))


def ancestral(root, b, tipo):
    pm = parent_map(root)
    x = pm[b]
    while not (tg(x) == 'block' and x.get('type') == tipo):
        x = pm[x]
    return x


def setters_de(p, inst):
    return [b for b in blocos(p, 'component_set_get') if [m for m in b if tg(m) == 'mutation'][0].get('instance_name') == inst]


# ---- periodo
@mutante('v1.7 chaveMes: mes sem o "-1" (todo lancamento cai no mes seguinte)', ['T36'])
def v1(root):
    p = procr(root, 'chaveMes')
    subs = [b for b in blocos(p, 'math_subtract') if eh_num(filho(b, 'B'), 1)]
    assert len(subs) == 1, len(subs)
    field(filho(subs[0], 'B'), 'NUM').text = '0'


@mutante('v1.7 noPeriodo: o modo Mes passa a mostrar tudo', ['T36'])
def v2(root):
    t = textos(procr(root, 'noPeriodo'), 'tudo')
    assert len(t) == 1
    field(t[0], 'TEXT').text = 'mes'


@mutante('v1.7 setas: seta para tras aparece tambem no mes mais antigo', ['T36'])
def v3(root):
    p = procr(root, 'atualizarPeriodoUI')
    cs = [b for b in blocos(p, 'math_compare') if field(b, 'OP').text == 'GT' and eh_get(filho(b, 'B'), 'global chaveMin')]
    assert len(cs) == 1
    field(cs[0], 'OP').text = 'GTE'


@mutante('v1.7 setas: nada impede passar do mes atual', ['T36'])
def v4(root):
    p = procr(root, 'mudarPeriodo')
    cs = [b for b in blocos(p, 'math_compare') if field(b, 'OP').text == 'LTE' and eh_get(filho(b, 'B'), 'global chaveHoje')]
    assert len(cs) == 1
    replace_value(val(cs[0], 'B'), dsl(G.num(999999)))


@mutante('v1.7 Mes -> Ano esquece o mes que se estava vendo (sempre o ano atual)', ['T36'])
def v5(root):
    t = textos(procr(root, 'definirModo'), 'mes')
    assert len(t) == 2
    field(t[1], 'TEXT').text = 'xxx'


@mutante('v1.7 quadradinhos do topo seguem o periodo escolhido (e nao o mes atual)', ['T36'])
def v6(root):
    p = procr(root, 'atualizarTudo')
    cs = [b for b in blocos(p, 'logic_compare') if eh_get(filho(b, 'A'), 'k') and eh_get(filho(b, 'B'), 'global chaveHoje')]
    assert len(cs) == 1
    field(filho(cs[0], 'B'), 'VAR').text = 'global periodoChave'


@mutante('v1.7 barra de periodo aparece em todas as abas', ['T36'])
def v7(root):
    st = comp_set(procr(root, 'mostrarAba'), 'PnlPeriodo', 'Visible')
    replace_value(val(st, 'VALUE'), dsl(G.boolean(True)))


@mutante('v1.7 mes mais antigo comeca em 0 (a seta para tras nunca some)', ['T36'])
def v8(root):
    st = sets_var(procr(root, 'indexarChaves'), 'global chaveMin')
    assert len(st) == 2
    replace_value(val(st[0], 'VALUE'), dsl(G.num(0)))


@mutante('v1.7 tocar de novo em "Mes" nao volta para o mes atual', ['T36'])
def v9(root):
    p = procr(root, 'definirModo')
    ch = [b for b in blocos(p, 'controls_choose') if eh_get(filho(b, 'ELSERETURN'), 'global chaveHoje')]
    assert len(ch) == 1
    field(filho(ch[0], 'ELSERETURN'), 'VAR').text = 'global periodoChave'


@mutante('v1.7 ultimos lancamentos do grafico ignoram o periodo', ['T36'])
def v10(root):
    p = procr(root, 'atualizarResumo')
    ifs = [b for b in blocos(p, 'controls_if') if filho(b, 'IF0').get('type') == 'procedures_callreturn'
           and field(filho(b, 'IF0'), 'PROCNAME').text == 'noPeriodo']
    assert len(ifs) == 1
    replace_value(val(ifs[0], 'IF0'), dsl(G.boolean(True)))


# ---- busca
@mutante('v1.7 busca diferencia acento ("saude" nao acha "Saude")', ['T37'])
def v11(root):
    f = blocos(procr(root, 'semAcento'), 'controls_forRange')
    assert len(f) == 1
    splice_out(root, f[0])


@mutante('v1.7 busca: a linha tocada abre o lancamento errado (posicao da lista filtrada)', ['T37'])
def v12(root):
    adds = [b for b in blocos(procr(root, 'atualizarHistorico'), 'lists_add_items') if eh_get(filho(b, 'LIST'), 'global mapaHist')]
    assert len(adds) == 1
    replace_value(val(adds[0], 'ITEM0'), dsl(G.llen(G.gget('linhas'))))


@mutante('v1.7 dialogo: "<" da descricao nao e escapado (parte do texto some)', ['T37'])
def v13(root):
    t = textos(procr(root, 'html'), '&lt;')
    assert len(t) == 1
    field(t[0], 'TEXT').text = '<'


@mutante('v1.7 dialogo: "&" da descricao nao e escapado', ['T37'])
def v13b(root):
    t = textos(procr(root, 'html'), '&amp;')
    assert len(t) == 1
    field(t[0], 'TEXT').text = '&'


@mutante('v1.7 busca: botao de limpar sempre visivel', ['T37'])
def v14(root):
    st = comp_set(procr(root, 'atualizarHistorico'), 'BtnLimparBusca', 'Visible')
    replace_value(val(st, 'VALUE'), dsl(G.boolean(True)))


# ---- editar
@mutante('v1.7 editar: a data do lancamento vira a de hoje', ['T38'])
def v15(root):
    p = procr(root, 'registrar')
    st = sets_var(p, 'novaData')               # v1.8: a data do editado e calculada uma vez em novaData
    assert len(st) == 1
    replace_value(val(st[0], 'VALUE'), dsl(G.cmeth('Clock1', 'Clock', 'FormatDate', G.cmeth('Clock1', 'Clock', 'Now'), G.txt('dd/MM/yyyy HH:mm'))))


@mutante('v1.7 editar: cria um lancamento novo em vez de trocar o antigo', ['T38'])
def v16(root):
    r = blocos(procr(root, 'registrar'), 'lists_replace_item')
    assert len(r) == 1                         # v1.8: o desfazer volta a copia da lista; so a troca do editado sobrou
    r[0].set('type', 'lists_insert_item')
    val(r[0], 'NUM').set('name', 'INDEX')


@mutante('v1.7 editar: nao confere o conteudo gravado (falha de gravacao vira falso "atualizado")', ['T38'])
def v17(root):
    p = procr(root, 'registrar')
    sts = [b for b in sets_var(p, 'global gravacaoOk') if filho(b, 'VALUE').get('type') == 'procedures_callreturn'
           and field(filho(b, 'VALUE'), 'PROCNAME').text == 'listaIgual']   # v1.8: lista inteira (a data pode mudar a posicao)
    assert len(sts) == 1
    splice_out(root, sts[0])


@mutante('v1.7 excluir durante a edicao: a posicao do lancamento em edicao nao anda', ['T38'])
def v18(root):
    sts = [b for b in sets_var(evento(root, 'Notifier1', 'AfterChoosing'), 'global editIndice') if filho(b, 'VALUE').get('type') == 'math_subtract']
    assert len(sts) == 1
    splice_out(root, sts[0])


@mutante('v1.7 editar: valor aparece com "R$" no campo (salvar da erro)', ['T38'])
def v19(root):
    c = call_of(procr(root, 'iniciarEdicao'), 'valorSemRs')
    assert len(c) == 1
    field(c[0], 'PROCNAME').text = 'formatarMoeda'
    [m for m in c[0] if tg(m) == 'mutation'][0].set('name', 'formatarMoeda')


@mutante('v1.7 editar: "repetir todo mes" continua aparecendo durante a edicao', ['T38'])
def v20(root):
    st = comp_set(procr(root, 'atualizarFormEdicao'), 'HzRepetir', 'Visible')
    replace_value(val(st, 'VALUE'), dsl(G.boolean(True)))


@mutante('v1.7 cancelar edicao nao limpa o formulario', ['T38'])
def v21(root):
    c = call_of(procr(root, 'cancelarEdicao'), 'limparFormulario')
    assert len(c) == 1
    splice_out(root, c[0])


# ---- repetir todo mes
@mutante('v1.7 repetir: dia 31 nao vira o ultimo dia do mes (data 31/02)', ['T39'])
def v22(root):
    st = sets_var(procr(root, 'gerarRecorrentes'), 'd')
    assert len(st) == 1
    replace_value(val(st[0], 'VALUE'), dsl(G.litem(G.lget('rec'), 6)))


@mutante('v1.7 repetir: so lanca no dia seguinte ao combinado', ['T39'])
def v23(root):
    cs = [b for b in blocos(procr(root, 'gerarRecorrentes'), 'math_compare') if field(b, 'OP').text == 'GTE'
          and eh_get(filho(b, 'A'), 'global diaHoje')]
    assert len(cs) == 1
    field(cs[0], 'OP').text = 'GT'


@mutante('v1.7 repetir: nao anota o ultimo mes lancado (duplica a cada abertura)', ['T39'])
def v24(root):
    r = blocos(procr(root, 'gerarRecorrentes'), 'lists_replace_item')
    assert len(r) == 1
    splice_out(root, r[0])


@mutante('v1.7 repetir: busca so 12 meses para tras em vez de 24', ['T39'])
def v25(root):
    n = nums(procr(root, 'gerarRecorrentes'), 24)
    assert len(n) == 2, len(n)          # 'piso' aparece duas vezes no "maior entre inicio e piso"
    for b in n:
        field(b, 'NUM').text = '12'


@mutante('v1.7 repetir: lancamento gerado entra no topo (fora da ordem de data)', ['T39'])
def v26(root):
    w = blocos(procr(root, 'inserirOrdenado'), 'controls_while')
    assert len(w) == 1
    replace_value(val(w[0], 'TEST'), dsl(G.boolean(False)))


@mutante('v1.7 diasNoMes: fevereiro sempre com 28 (ano bissexto errado)', ['T39'])
def v27(root):
    n = nums(procr(root, 'diasNoMes'), 29)
    assert len(n) == 1
    field(n[0], 'NUM').text = '28'


@mutante('v1.7 repeticoes estranhas no armazenamento nao sao filtradas', ['T39'])
def v28(root):
    fe = blocos(procr(root, 'carregarPreferencias'), 'controls_forEach')
    assert len(fe) == 1
    ifs = [b for b in fe[0].iter(NS + 'block') if b.get('type') == 'controls_if']
    replace_value(val(ifs[0], 'IF0'), dsl(G.boolean(True)))


@mutante('v1.7 aviso longo some em 3 s (deveria ficar 5 s)', ['T39'])
def v29(root):
    n = nums(procr(root, 'mostrarAviso'), 5000)
    assert len(n) == 1
    field(n[0], 'NUM').text = '3000'


@mutante('v1.7 "repetir" continua marcado depois de salvar', ['T39'])
def v30(root):
    st = sets_var(procr(root, 'limparFormulario'), 'global repetirSel')
    assert len(st) == 1
    splice_out(root, st[0])


@mutante('v1.7 lista de repeticoes baixa demais (corta linhas)', ['T39'])
def v31(root):
    n = nums(procr(root, 'atualizarRecorrentes'), 70)
    assert len(n) == 1
    field(n[0], 'NUM').text = '50'


# ---- limites
@mutante('v1.7 limite: aviso de "ja usou" so a partir de 90%', ['T40'])
def v32(root):
    n = nums(procr(root, 'avisoLimite'), 80)
    assert len(n) == 1
    field(n[0], 'NUM').text = '90'


@mutante('v1.7 limite: barra amarela so a partir de 85%', ['T40'])
def v33(root):
    n = nums(procr(root, 'pintarLinhaCat'), 80)
    assert n
    for b in n:
        field(b, 'NUM').text = '85'


@mutante('v1.7 limite: gastar exatamente o limite ja conta como "passou"', ['T40'])
def v34(root):
    cs = [b for b in blocos(procr(root, 'pintarLinhaCat'), 'math_compare') if field(b, 'OP').text == 'GT'
          and eh_get(filho(b, 'A'), 'valor') and eh_get(filho(b, 'B'), 'lim')]
    assert cs
    for b in cs:
        field(b, 'OP').text = 'GTE'


@mutante('v1.7 limite: aplicado tambem no modo Ano', ['T40'])
def v35(root):
    ch = [b for b in blocos(procr(root, 'atualizarCategorias'), 'controls_choose')
          if filho(b, 'THENRETURN').get('type') == 'lists_select_item' and eh_get(filho(filho(b, 'THENRETURN'), 'LIST'), 'global orcamentos')]
    assert ch
    for b in ch:
        replace_value(val(b, 'TEST'), dsl(G.boolean(True)))


@mutante('v1.7 limite: valor invalido aceito calado', ['T40'])
def v36(root):
    ifs = [b for b in blocos(evento(root, 'BtnSalvarOrc', 'Click'), 'controls_if') if filho(b, 'IF0').get('type') == 'math_compare'
           and field(filho(b, 'IF0'), 'OP').text == 'GTE']
    assert len(ifs) == 1
    replace_value(val(ifs[0], 'IF0'), dsl(G.boolean(True)))


@mutante('v1.7 limite: "Voltar"/"Salvar" nao lembra de onde veio', ['T40'])
def v37(root):
    ifs = blocos(procr(root, 'abrirLimites'), 'controls_if')
    assert len(ifs) == 1
    splice_out(root, ifs[0])


@mutante('v1.7 limite: aviso tambem ao editar despesa de outro mes', ['T40'])
def v38(root):
    ch = [b for b in blocos(procr(root, 'registrar'), 'controls_choose') if filho(b, 'THENRETURN').get('type') == 'procedures_callreturn'
          and field(filho(b, 'THENRETURN'), 'PROCNAME').text == 'avisoLimite']
    assert len(ch) == 2
    for b in ch:
        replace_value(val(b, 'TEST'), dsl(G.eq(G.lget('tipo'), G.txt('Despesa'))))


@mutante('v1.7 limites guardados com valor quebrado nao sao filtrados (erro ao abrir)', ['T40'])
def v39(root):
    fr = blocos(procr(root, 'carregarPreferencias'), 'controls_forRange')
    assert len(fr) == 1
    ifs = [b for b in fr[0].iter(NS + 'block') if b.get('type') == 'controls_if']
    replace_value(val(ifs[0], 'IF0'), dsl(G.cmp('GT', G.litem(G.lget('o'), G.lget('i')), G.num(0))))


# ---- evolucao
@mutante('v1.7 evolucao: cor da comparacao invertida (gastar menos fica vermelho)', ['T41'])
def v40(root):
    ch = [b for b in blocos(procr(root, 'comparar'), 'controls_choose') if eh_get(filho(b, 'TEST'), 'menosEhBom')]
    assert ch
    for b in ch:
        replace_value(val(b, 'TEST'), dsl(G.NOT(G.lget('menosEhBom'))))


@mutante('v1.7 evolucao: porcentagem calculada sobre o mes atual (e nao sobre o anterior)', ['T41'])
def v41(root):
    d = [b for b in blocos(procr(root, 'comparar'), 'math_division') if eh_get(filho(b, 'B'), 'anterior')]
    assert len(d) == 1
    field(filho(d[0], 'B'), 'VAR').text = 'atual'


@mutante('v1.7 evolucao: lancamento sem data fica fora do saldo acumulado', ['T41'])
def v42(root):
    p = procr(root, 'atualizarEvolucao')
    ifs = [b for b in blocos(p, 'controls_if') if [s for s in b if tg(s) == 'statement' and s.get('name') == 'DO0'
                                                   and s[0].get('type') == 'lexical_variable_set' and field(s[0], 'VAR').text == 'accAntes']]
    assert len(ifs) == 1
    replace_value(val(ifs[0], 'IF0'), dsl(G.AND(G.cmp('GTE', G.lget('k'), G.num(0)),
                                                 G.cmp('LT', G.lget('k'), G.mmul(G.gget('evoAno'), G.num(12))))))


@mutante('v1.7 evolucao: barras do mes a mes estouram a area (escala 112 em vez de 104)', ['T41'])
def v43(root):
    n = nums(procr(root, 'atualizarEvolucao'), 104)
    assert n
    for b in n:
        field(b, 'NUM').text = '112'


@mutante('v1.7 evolucao: barra minima de 2 dp some (valores pequenos invisiveis)', ['T41'])
def v44(root):
    cs = [b for b in blocos(procr(root, 'atualizarEvolucao'), 'math_compare') if field(b, 'OP').text == 'LT' and eh_num(filho(b, 'B'), 2)]
    assert cs
    for b in cs:
        field(filho(b, 'B'), 'NUM').text = '0'


@mutante('v1.7 evolucao: "ha um ano" mostra 11 meses atras', ['T41'])
def v45(root):
    subs = [b for b in blocos(procr(root, 'evoResumoMes'), 'math_subtract') if eh_get(filho(b, 'A'), 'global chaveHoje')
            and eh_num(filho(b, 'B'), 12)]
    assert len(subs) == 1
    field(filho(subs[0], 'B'), 'NUM').text = '11'


@mutante('v1.7 evolucao: tocar num mes abre o mes seguinte', ['T41'])
def v46(root):
    n = nums(evento(root, 'BtnMes11', 'Click'), 10)
    assert len(n) == 1
    field(n[0], 'NUM').text = '11'


@mutante('v1.7 evolucao: anos do mais antigo para o mais novo', ['T41'])
def v47(root):
    fr = [b for b in blocos(procr(root, 'atualizarEvolucao'), 'controls_forRange') if field(b, 'VAR').text == 'y']
    assert len(fr) == 1
    a, z = val(fr[0], 'START'), val(fr[0], 'END')
    ia, iz = a[0], z[0]
    a.remove(ia)
    z.remove(iz)
    a.append(iz)
    z.append(ia)
    passo = filho(fr[0], 'STEP')
    assert eh_num(passo, -1)
    field(passo, 'NUM').text = '1'


@mutante('v1.7 evolucao: seta do ano passa do ano mais antigo', ['T41'])
def v48(root):
    ifs = blocos(evento(root, 'BtnEvoAnoAnt', 'Click'), 'controls_if')
    assert len(ifs) == 1
    replace_value(val(ifs[0], 'IF0'), dsl(G.boolean(True)))


# ---- planilha, backup e restauracao
@mutante('v1.7 planilha: "=..." vira formula (sem apostrofo)', ['T42'])
def v49(root):
    ifs = blocos(procr(root, 'campoCsv'), 'controls_if')
    assert len(ifs) == 1
    splice_out(root, ifs[0])


@mutante('v1.7 planilha: aspas dentro do texto nao sao dobradas', ['T42'])
def v50(root):
    t = textos(procr(root, 'campoCsv'), '""')
    assert len(t) == 1
    field(t[0], 'TEXT').text = '"'


@mutante('v1.7 planilha: despesa sem o sinal de menos', ['T42'])
def v51(root):
    t = textos(procr(root, 'valorCsv'), '-')
    assert len(t) == 1
    field(t[0], 'TEXT').text = ''


@mutante('v1.7 planilha sem BOM (Excel mostra acentos quebrados)', ['T42'])
def v52(root):
    t = [b for b in blocos(evento(root, 'BtnExportar', 'Click'), 'text') if (field(b, 'TEXT').text or '').startswith('﻿')]
    assert len(t) == 1
    field(t[0], 'TEXT').text = field(t[0], 'TEXT').text[1:]


@mutante('v1.7 restaurar: aceita qualquer arquivo como backup', ['T42'])
def v53(root):
    ifs = [b for b in blocos(procr(root, 'lerBackup'), 'controls_if') if filho(b, 'IF0').get('type') == 'logic_negate']
    assert len(ifs) == 1
    replace_value(val(ifs[0], 'IF0'), dsl(G.boolean(False)))


@mutante('v1.7 restaurar: nao tira o BOM do comeco do arquivo', ['T42'])
def v54(root):
    t = [b for b in blocos(procr(root, 'lerBackup'), 'text') if field(b, 'TEXT').text == '﻿']
    assert len(t) == 1
    splice_out(root, ancestral(root, t[0], 'controls_if'))


@mutante('v1.7 restaurar: valor negativo aceito', ['T42'])
def v55(root):
    cs = [b for b in blocos(procr(root, 'lerBackup'), 'math_compare') if field(b, 'OP').text == 'GT' and eh_num(filho(b, 'B'), 0)]
    assert cs
    for b in cs:
        field(filho(b, 'B'), 'NUM').text = '-1000000'


@mutante('v1.7 restaurar: nao refaz o cache de meses (mesmo numero de lancamentos, outras datas)', ['T42'])
def v56(root):
    st = sets_var(procr(root, 'aplicarBackup'), 'global chavesReg')
    assert len(st) == 2
    splice_out(root, st[0])


@mutante('v1.7 restaurar: falha ao gravar nao desfaz (backup fica so na memoria)', ['T42'])
def v57(root):
    st = [b for b in sets_var(procr(root, 'aplicarBackup'), 'global lancamentos') if eh_get(filho(b, 'VALUE'), 'antigos')]
    assert len(st) == 1
    splice_out(root, st[0])


@mutante('v1.7 restaurar: nao confere o conteudo gravado (mesmo tamanho = "ok")', ['T42'])
def v58(root):
    sts = [b for b in sets_var(procr(root, 'aplicarBackup'), 'global gravacaoOk') if filho(b, 'VALUE').get('type') == 'procedures_callreturn']
    assert len(sts) == 1
    splice_out(root, sts[0])


@mutante('v1.7 cancelar a restauracao nao avisa nem limpa', ['T42'])
def v59(root):
    p = evento(root, 'Notifier1', 'AfterChoosing')
    ifs = [b for b in blocos(p, 'controls_if') if any(x.get('type') == 'text' and field(x, 'TEXT').text == 'Cancelar'
                                                      for x in filho(b, 'IF0').iter(NS + 'block'))
           and gets(filho(b, 'IF0'), 'global backupPendente')]    # v1.8: o outro "Cancelar" e o da importacao
    assert len(ifs) == 1
    splice_out(root, ifs[0])


@mutante('v1.7 erro de arquivo vira aviso generico (nada no cartao)', ['T42'])
def v60(root):
    ifs = blocos(evento(root, 'Screen1', 'ErrorOccurred'), 'controls_if')
    assert len(ifs) == 1
    replace_value(val(ifs[0], 'IF0'), dsl(G.boolean(False)))


@mutante('v1.7 arquivo salvo mas o compartilhamento nao abre', ['T42'])
def v61(root):
    m = [b for b in blocos(evento(root, 'File1', 'AfterFileSaved'), 'component_method')
         if [c for c in b if tg(c) == 'mutation'][0].get('method_name') == 'ShareFile']   # v1.8: ha StoreValue/SystemTime antes
    assert len(m) == 1
    splice_out(root, m[0])


# ---- tema e estrutura
@mutante('v1.7 trocar o tema desmarca o "repetir" na tela (marcado so na memoria)', ['T43'])
def v62(root):
    c = call_of(procr(root, 'pintarEstados'), 'atualizarFormEdicao')
    assert len(c) == 1
    splice_out(root, c[0])


@mutante('v1.7 lista de opcoes com a altura fixa antiga (categorias cortadas)', ['T43'])
def v63(root):
    splice_out(root, comp_set(procr(root, 'abrirPicker'), 'ListaOpcoes', 'Height'))


@mutante('v1.7 aba Evolucao nunca fica destacada', ['T43'])
def v64(root):
    sts = setters_de(procr(root, 'pintarAbas'), 'BtnNavEvolucao')
    assert len(sts) == 2
    for s_ in sts:
        splice_out(root, s_)


@mutante('v1.7 atualizarTudo sem refazer o cache de meses', ['T44'])
def v65(root):
    ifs = [b for b in blocos(procr(root, 'atualizarTudo'), 'controls_if') if filho(b, 'IF0').get('type') == 'math_compare'
           and field(filho(b, 'IF0'), 'OP').text == 'NEQ']
    assert len(ifs) == 1
    splice_out(root, ifs[0])


@mutante('v1.7 gravarDados: deixa de conferir o tamanho lido de volta', ['T10', 'T42'])
def v66(root):
    st = sets_var(procr(root, 'gravarDados'), 'global gravacaoOk')
    assert len(st) == 1
    replace_value(val(st[0], 'VALUE'), dsl(G.boolean(True)))


@mutante('v1.7 campoIgual: deixa de aceitar "true" gravado que volta como verdadeiro (descricao "true" nao salva na edicao)', ['T45'])
def v67(root):
    p = procr(root, 'campoIgual')
    ors = [b for b in blocos(p, 'logic_operation') if field(b, 'OP').text == 'OR']
    replace_value(val(ors[0], 'B'), dsl(G.boolean(False)))


# ---- restauracao de arquivo cortado ou alterado (conferencias acrescentadas no fim da v1.7)
def _ifelif_backup(root):
    ifs = [b for b in blocos(procr(root, 'lerBackup'), 'controls_if')
           if filho(b, 'IF0').get('type') == 'logic_negate' and filho(b, 'IF1') is not None]
    assert len(ifs) == 1
    return ifs[0]


@mutante('v1.7 restaurar: sem conferir as aspas (arquivo cortado para o app com erro tecnico)', ['T42'])
def v68(root):
    replace_value(val(_ifelif_backup(root), 'IF1'), dsl(G.boolean(False)))


@mutante('v1.7 restaurar: so confere a aspa do fim (sem a contagem par de aspas)', ['T42'])
def v69(root):
    neg = filho(_ifelif_backup(root), 'IF1')
    e = filho(neg, 'BOOL')
    assert e.get('type') == 'logic_operation' and field(e, 'OP').text == 'AND'
    replace_value(val(neg, 'BOOL'), copy.deepcopy(filho(e, 'B')))


@mutante('v1.7 restaurar: so conta as aspas (sem conferir a aspa do fim)', ['T42'])
def v70(root):
    neg = filho(_ifelif_backup(root), 'IF1')
    e = filho(neg, 'BOOL')
    assert e.get('type') == 'logic_operation' and field(e, 'OP').text == 'AND'
    replace_value(val(neg, 'BOOL'), copy.deepcopy(filho(e, 'A')))


def _tem_texto(b, t):
    # so o proprio bloco e o que esta dentro dele (sem seguir o <next>, que sao as instrucoes seguintes)
    blocos_dele = [b] + [x for c in b if tg(c) != 'next' for x in c.iter(NS + 'block')]
    return any(x.get('type') == 'text' and field(x, 'TEXT').text == t for x in blocos_dele)


@mutante('v1.7 restaurar: sem a conferencia "Fim" (arquivo cortado entre linhas restaurado pela metade)', ['T42'])
def v71(root):
    ifs = [b for b in blocos(procr(root, 'lerBackup'), 'controls_if') if _tem_texto(filho(b, 'IF0'), 'Fim')]
    assert len(ifs) == 1
    replace_value(val(ifs[0], 'IF0'), dsl(G.boolean(True)))


@mutante('v1.7 restaurar: confere a linha "Fim" mas nao o numero de lancamentos', ['T42'])
def v72(root):
    cs = [b for b in blocos(procr(root, 'lerBackup'), 'logic_compare') if eh_get(filho(b, 'B'), 'nL')]
    assert len(cs) == 1
    trocar_bloco(root, cs[0], G.boolean(True))


@mutante('v1.7 backup sem a linha de conferencia "Fim" (o proprio backup nao restaura)', ['T42'])
def v73(root):
    adds = [b for b in blocos(evento(root, 'BtnBackup', 'Click'), 'lists_add_items') if _tem_texto(b, 'Fim')]
    assert len(adds) == 1
    splice_out(root, adds[0])


@mutante('v1.7 restaurar: nao tira espacos/quebras do fim (backup com linha em branco a mais recusado)', ['T42'])
def v74(root):
    sts = [b for b in sets_var(procr(root, 'lerBackup'), 't') if filho(b, 'VALUE').get('type') == 'text_trim']
    assert len(sts) == 1
    splice_out(root, sts[0])


@mutante('v1.7 restaurar: a conferencia so conta os lancamentos validos (backup com linha ruim recusado)', ['T42'])
def v75(root):
    # o "+1" da contagem passa a exigir tambem a validade do lancamento (tipo, valor inteiro positivo, 7 campos)
    p = procr(root, 'lerBackup')
    ifs = [b for b in blocos(p, 'controls_if') if any(eh_get(x, 'nL') for x in b.iter(NS + 'block'))
           and filho(b, 'IF1') is None and _tem_texto(filho(b, 'IF0'), 'L')]
    assert len(ifs) == 1, len(ifs)
    cadeia = [b for b in blocos(p, 'controls_if') if filho(b, 'IF1') is not None and filho(b, 'IF0').get('type') == 'logic_operation']
    valido = [b for b in cadeia if _tem_texto(filho(b, 'IF0'), 'L')]
    assert len(valido) == 1
    replace_value(val(ifs[0], 'IF0'), copy.deepcopy(filho(valido[0], 'IF0')))


# ---- tela (.scm / imagens) da v1.7
@tela('v1.7 arquivos fora da pasta do app (escopo Shared pede permissao)', ['T42'])
def s28(d, pkg):
    scm_nodes(d)['Screen1']['DefaultFileScope'] = 'Shared'


@tela('v1.7 File com escopo Legacy', ['T42'])
def s29(d, pkg):
    scm_nodes(d)['File1']['DefaultScope'] = 'Legacy'


@tela('v1.7 Restaurar escolhe PASTA em vez de arquivo', ['T42'])
def s30(d, pkg):
    scm_nodes(d)['PickerRestaurar']['Action'] = 'Pick Directory'


@tela('v1.7 caixa "repetir" sem o toque (Clickable falso)', ['T39'])
def s31(d, pkg):
    scm_nodes(d)['ImgRepetir']['Clickable'] = 'False'


@tela('v1.7 caixa marcada igual a desmarcada (imagem)', ['T43'])
def s32(d, pkg):
    shutil.copy(os.path.join(pkg, 'assets', 'ic_check_off.png'), os.path.join(pkg, 'assets', 'ic_check_on.png'))


@tela('v1.7 campo de limite com erro igual ao normal (imagem)', ['T43'])
def s33(d, pkg):
    shutil.copy(os.path.join(pkg, 'assets', 'campo_curto.png'), os.path.join(pkg, 'assets', 'campo_curto_erro.png'))


@tela('v1.7 texto das repeticoes claro demais (some no cartao)', ['T43'])
def s34(d, pkg):
    scm_nodes(d)['ListaRecorrentes']['TextColor'] = '&HFFE8EEEB'


@tela('v1.7 aba Evolucao escondida', ['T41'])
def s35(d, pkg):
    scm_nodes(d)['BtnNavEvolucao']['Visible'] = 'False'


@tela('v1.7 botao Restaurar backup escondido', ['T42'])
def s36(d, pkg):
    scm_nodes(d)['PickerRestaurar']['Visible'] = 'False'


@tela('v1.7 "R$" dos limites claro demais', ['T27'])
def s37(d, pkg):
    for i in range(1, 9):
        scm_nodes(d)['LblOrcRs%d' % i]['TextColor'] = '&HFFB9D9D0'


@tela('v1.7 lista de anos com 1 linha so (some entradas/despesas)', ['T43'])
def s38(d, pkg):
    scm_nodes(d)['ListaAnos']['ListViewLayout'] = '0'


@tela('v1.7 barras do mes a mes penduradas no topo', ['T41'])
def s39(d, pkg):
    for i in range(1, 13):
        scm_nodes(d)['HzBarMes%d' % i]['AlignVertical'] = '1'


@tela('v1.7 repeticoes sem a cor da 2a linha (cor padrao)', ['T43'])
def s40(d, pkg):
    scm_nodes(d)['ListaRecorrentes'].pop('TextColorDetail', None)



# >>> mutantes novos da v1.8 (mutantes_novos18.py)
# ============================================================================= v1.8 (colado aqui antes de run_tela)
# Cada mutante planta UM defeito plausivel numa parte nova (importar extrato, data, meta, backup/lembrete, tema) e diz
# quais testes deveriam pegar. Os localizadores falham (AssertionError) se a estrutura nao for exatamente a esperada,
# para nenhum mutante cair, calado, num lugar diferente do rotulo (conferido com onde_muda.py).


def mt(b):
    return [c for c in b if tg(c) == 'mutation'][0]


def proprios(b):
    """Blocos de b (inclusive) SEM seguir a cadeia <next> do proprio b (o .iter() do ElementTree seguiria)."""
    yield b
    for c in b:
        if tg(c) != 'next':
            for d in c.iter(NS + 'block'):
                yield d


def stmt(b, nome):
    for c in b:
        if tg(c) == 'statement' and c.get('name') == nome:
            return c
    return None


def defr(root, nome):
    return top(root, 'procedures_defreturn', nome)


def setters(p, inst, prop):
    return [b for b in blocos(p, 'component_set_get') if mt(b).get('set_or_get') == 'set'
            and mt(b).get('instance_name') == inst and mt(b).get('property_name') == prop]


def metodos(p, inst, meth):
    return [b for b in blocos(p, 'component_method') if mt(b).get('instance_name') == inst and mt(b).get('method_name') == meth]


def tem_texto(b, t):
    return any(x.get('type') == 'text' and (field(x, 'TEXT').text or '') == t for x in proprios(b))


def tem_get(b, var):
    return any(eh_get(x, var) for x in proprios(b))


def ifs(p, pred=lambda b: True):
    return [b for b in blocos(p, 'controls_if') if pred(b)]


def nums_em(p, valor):
    """Numeros iguais a `valor` dentro de p (sem seguir o <next> de p, se p for uma instrucao)."""
    return [b for b in proprios(p) if b.get('type') == 'math_number' and field(b, 'NUM').text == str(valor)]


def cadeia(st):
    """Instrucoes DIRETAMENTE dentro de um <statement> (seguindo <next>), sem entrar nos blocos aninhados."""
    out = []
    b = st[0] if st is not None and len(st) else None
    while b is not None:
        out.append(b)
        nx = [c for c in b if tg(c) == 'next']
        b = nx[0][0] if nx and len(nx[0]) else None
    return out


def define_direto(b, corpo, var):
    """O corpo (DOk/ELSE) de b tem, diretamente, um "set var"."""
    return any(x.get('type') == 'lexical_variable_set' and field(x, 'VAR').text == var for x in cadeia(stmt(b, corpo)))


def ramos_if(b):
    """[(nome do teste, nome do corpo)] de um controls_if: IF0/DO0, IF1/DO1, ..."""
    n = int(mt(b).get('elseif') or 0) if [c for c in b if tg(c) == 'mutation'] else 0
    return [('IF%d' % k, 'DO%d' % k) for k in range(n + 1)]


def ramo_com_texto(b, t):
    """Nome do teste (IFk) cujo CORPO (DOk) tem o texto t."""
    r = [i for i, d in ramos_if(b) if stmt(b, d) is not None and any(
        x.get('type') == 'text' and (field(x, 'TEXT').text or '') == t for x in stmt(b, d).iter(NS + 'block'))]
    assert len(r) == 1, r
    return r[0]


def teste_com_texto(b, t):
    """Nome do teste (IFk) cujo PROPRIO teste tem o texto t."""
    r = [i for i, d in ramos_if(b) if val(b, i) is not None and tem_texto(filho(b, i), t)]
    assert len(r) == 1, r
    return r[0]


def falso(vblk):
    replace_value(vblk, dsl(G.boolean(False)))


def verdadeiro(vblk):
    replace_value(vblk, dsl(G.boolean(True)))


def so1(lista):
    """Exatamente um bloco achado (o "um" do runner de mutacao ja usa esse nome)."""
    assert len(lista) == 1, len(lista)
    return lista[0]


# ---- editar (o que os mutantes antigos M06/M07/M09/M55 testavam sem querer: a v1.6 pos o editar antes do criar)
@mutante('v1.8 editar: esquece de gravar (gravarDados do ramo de editar)', ['T38'])
def x1(root):
    splice_out(root, call(ramo_registrar(root, 'novaData'), 'gravarDados'))


@mutante('v1.8 editar: categoria e pagamento trocados ao salvar a edicao', ['T38'])
def x2(root):
    lc = filho(so1(sets_var(ramo_registrar(root, 'novaData'), 'novo')), 'VALUE')
    assert lc.get('type') == 'lists_create_with'
    a4, a5 = val(lc, 'ADD4'), val(lc, 'ADD5')
    x, y = a4[0], a5[0]
    a4.remove(x)
    a5.remove(y)
    a4.append(y)
    a5.append(x)


@mutante('v1.8 editar: falha ao gravar nao desfaz (a edicao fica so na memoria)', ['T38'])
def x3(root):
    splice_out(root, so1(sets_var(ramo_registrar(root, 'novaData'), 'global lancamentos')))


@mutante('v1.8 editar: falha ao gravar mostra a faixa VERDE (falso "atualizado")', ['T38'])
def x4(root):
    c = [b for b in call_of(ramo_registrar(root, 'novaData'), 'mostrarAviso')
         if filho(b, 'ARG0').get('type') == 'logic_boolean' and field(filho(b, 'ARG0'), 'BOOL').text == 'FALSE']
    field(filho(so1(c), 'ARG0'), 'BOOL').text = 'TRUE'


@mutante('v1.8 editar com outra data: o lancamento antigo continua na lista (duplica)', ['T48'])
def x5(root):
    splice_out(root, so1(blocos(ramo_registrar(root, 'novaData'), 'lists_remove_item')))


@mutante('v1.8 editar com outra data: entra no topo (fora da ordem de data)', ['T48'])
def x6(root):
    falso(val(so1(blocos(ramo_registrar(root, 'novaData'), 'controls_while')), 'TEST'))


@mutante('v1.8 editar com outra data: perde a hora original (vira 12:00)', ['T48'])
def x7(root):
    ch = [b for b in blocos(ramo_registrar(root, 'novaData'), 'controls_choose')
          if filho(b, 'ELSERETURN') is not None and filho(b, 'ELSERETURN').get('type') == 'text'
          and field(filho(b, 'ELSERETURN'), 'TEXT').text == ' 12:00']
    replace_value(val(so1(ch), 'THENRETURN'), dsl(G.txt(' 12:00')))


# ---- importar extrato: leitura do arquivo
@mutante('v1.8 importar: cabecalho com BOM (planilha do Excel) nao e reconhecido', ['T46'])
def x8(root):
    field(so1(textos(defr(root, 'normCab'), '﻿')), 'TEXT').text = '~'


@mutante('v1.8 importar: aspas dobradas ("") dentro de um campo viram fim das aspas', ['T47'])
def x9(root):
    p = defr(root, 'dividirLinha')
    b = so1(ifs(p, lambda b: stmt(b, 'DO0') is not None and any(eh_get(x, 'i') or (x.get('type') == 'lexical_variable_set'
                                                                                   and field(x, 'VAR').text == 'i')
                                                                 for x in stmt(b, 'DO0').iter(NS + 'block'))
               and len(ramos_if(b)) == 1))
    falso(val(b, 'IF0'))


@mutante('v1.8 importar: separador dentro de aspas divide o campo ("Amazon, Marketplace")', ['T46', 'T47'])
def x10(root):
    b = so1(ifs(defr(root, 'dividirLinha'), lambda b: len(ramos_if(b)) == 4))
    assert eh_get(filho(b, 'IF1'), 'dentro')
    falso(val(b, 'IF1'))


@mutante('v1.8 importar: ano com 2 digitos vira 19xx (01/09/26 -> 1926)', ['T46', 'T47'])
def x11(root):
    field(so1(nums_em(defr(root, 'lerData'), 2000)), 'NUM').text = '1900'


@mutante('v1.8 importar: data aaaa-mm-dd lida como dd-mm-aaaa (fatura do Nubank recusada)', ['T46', 'T47'])
def x12(root):
    # o "se o 1o pedaco tem 4 digitos (ano na frente)": len(partes[1]) == 4
    b = so1(ifs(defr(root, 'lerData'), lambda b: filho(b, 'IF0') is not None
               and filho(b, 'IF0').get('type') in ('logic_compare', 'math_compare') and eh_num(filho(filho(b, 'IF0'), 'B'), 4)
               and filho(filho(b, 'IF0'), 'A').get('type') == 'text_length'))
    falso(val(b, 'IF0'))


@mutante('v1.8 importar: aceita 31/02 (nao confere quantos dias o mes tem)', ['T46', 'T47'])
def x13(root):
    trocar_bloco(root, so1(call_of(defr(root, 'lerData'), 'diasNoMes')), G.num(31))


@mutante('v1.8 importar: hora do extrato ignorada (tudo as 12:00)', ['T47'])
def x14(root):
    st = [b for b in sets_var(defr(root, 'lerData'), 'hora') if filho(b, 'VALUE').get('type') == 'text_segment']
    replace_value(val(so1(st), 'VALUE'), dsl(G.txt('12:00')))


@mutante('v1.8 importar: "D" no fim do valor nao vira despesa (99,90 D)', ['T46'])
def x15(root):
    b = so1(ifs(defr(root, 'lerValor'), lambda b: val(b, 'IF0') is not None and tem_texto(filho(b, 'IF0'), 'D')))
    splice_out(root, so1(sets_var(stmt(b, 'DO0'), 'neg')))


@mutante('v1.8 importar: valor entre parenteses nao vira despesa ((199,90))', ['T46'])
def x16(root):
    b = so1(ifs(defr(root, 'lerValor'), lambda b: val(b, 'IF0') is not None and tem_texto(filho(b, 'IF0'), '(')))
    splice_out(root, so1([s for s in sets_var(stmt(b, 'DO0'), 'neg')]))


@mutante('v1.8 importar: "1.234,56" lido no formato americano (vira R$ 1,23)', ['T46', 'T47'])
def x17(root):
    b = so1(ifs(defr(root, 'lerValor'), lambda b: filho(b, 'IF0') is not None and filho(b, 'IF0').get('type') == 'text_contains'
               and any(x.get('type') == 'text_split' for x in proprios(filho(b, 'IF0')))))
    verdadeiro(val(b, 'IF0'))


@mutante('v1.8 importar: "1.500" (milhar sem centavos) lido como R$ 1,50', ['T46'])
def x18(root):
    alvo = [b for b in proprios(defr(root, 'lerValor')) if b.get('type') in ('logic_compare', 'math_compare') and eh_num(filho(b, 'B'), 3)
            and filho(b, 'A') is not None and filho(b, 'A').get('type') == 'text_length'
            and filho(filho(b, 'A'), 'VALUE').get('type') == 'lists_select_item']
    field(filho(so1(alvo), 'B'), 'NUM').text = '4'


@mutante('v1.8 importar: menos no fim do valor ignorado ("35,00-" recusado)', ['T46'])
def x19(root):
    b = so1(ifs(defr(root, 'lerValor'), lambda b: len(ramos_if(b)) == 3 and tem_texto(filho(b, 'IF0'), '-')
               and tem_texto(filho(b, 'IF1'), '-')))
    splice_out(root, so1(sets_var(stmt(b, 'DO1'), 'neg')))


# ---- importar: categoria e forma de pagamento
@mutante('v1.8 importar: categoria procurada sem tirar acento/maiuscula (SUPERMERCADO nao vira Alimentacao)', ['T46', 'T47'])
def x20(root):
    trocar_bloco(root, so1(call_of(defr(root, 'adivinharCategoria'), 'semAcento')), G.lget('descricao'))


@mutante('v1.8 importar: categoria desconhecida vira Compras (em vez de Outros)', ['T46', 'T47'])
def x21(root):
    field(so1(textos(defr(root, 'adivinharCategoria'), 'Outros')), 'TEXT').text = 'Compras'


@mutante('v1.8 importar: Pix nao reconhecido (vira transferencia)', ['T46', 'T47'])
def x22(root):
    field(so1(textos(defr(root, 'adivinharPagamento'), 'pix')), 'TEXT').text = 'pix-nao'


@mutante('v1.8 importar: fatura do cartao nao marca "Cartao de credito"', ['T46', 'T47'])
def x23(root):
    ch = [b for b in blocos(defr(root, 'adivinharPagamento'), 'controls_choose') if eh_get(filho(b, 'TEST'), 'cartao')]
    falso(val(so1(ch), 'TEST'))


@mutante('v1.8 importar: coluna "Categoria" da planilha ignorada', ['T47'])
def x23b(root):
    st = [b for b in sets_var(proc(root, 'lerExtrato'), 'cat') if filho(b, 'VALUE').get('type') == 'controls_choose'
          and call_of(filho(b, 'VALUE'), 'acharNaLista')]
    replace_value(val(so1(st), 'VALUE'), dsl(G.txt('')))


@mutante('v1.8 importar: coluna "Tipo" ignorada (o sinal decide; valores sem sinal viram entrada)', ['T47'])
def x23c(root):
    b = so1(ifs(proc(root, 'lerExtrato'), lambda b: len(ramos_if(b)) == 1 and filho(b, 'IF0').get('type') == 'math_compare'
               and eh_get(filho(filho(b, 'IF0'), 'A'), 'iTipo')))
    falso(val(b, 'IF0'))


# ---- importar: cabecalho, separador, cartao
@mutante('v1.8 importar: cabecalho procurado so na 1a linha (extrato com linhas antes do cabecalho nao abre)', ['T46', 'T47'])
def x24(root):
    f = [b for b in blocos(proc(root, 'lerExtrato'), 'controls_forRange') if nums_em(filho(b, 'END'), 20)]
    replace_value(val(so1(f), 'END'), dsl(G.num(1)))


@mutante('v1.8 importar: separador sempre virgula (arquivo com ";" nao abre)', ['T46', 'T47'])
def x25(root):
    replace_value(val(so1(sets_var(proc(root, 'lerExtrato'), 'sep')), 'VALUE'), dsl(G.txt(',')))


@mutante('v1.8 importar: fatura invertida (compra no cartao vira entrada)', ['T46', 'T47'])
def x26(root):
    b = so1(ifs(proc(root, 'lerExtrato'), lambda b: filho(b, 'IF0') is not None and filho(b, 'IF0').get('type') == 'math_compare'
               and field(filho(b, 'IF0'), 'OP').text == 'GT' and eh_get(filho(filho(b, 'IF0'), 'A'), 'v')
               and eh_num(filho(filho(b, 'IF0'), 'B'), 0)))
    st = so1(sets_var(stmt(b, 'DO0'), 'tipo'))
    field(filho(st, 'VALUE'), 'TEXT').text = 'Entrada'


@mutante('v1.8 importar: pagamento da fatura importado como entrada', ['T46', 'T47'])
def x27(root):
    b = so1(ifs(proc(root, 'lerExtrato'), lambda b: filho(b, 'IF0') is not None and tem_texto(filho(b, 'IF0'), 'estorno')))
    verdadeiro(val(b, 'IF0'))


# ---- importar: repetidos, datas futuras, linhas de informacao, limite da descricao
def _if_repetido(root):
    return so1(ifs(proc(root, 'lerExtrato'), lambda b: define_direto(b, 'DO0', 'repetidos')))


@mutante('v1.8 importar: repetidos nao reconhecidos (importa de novo o que ja esta no app)', ['T46', 'T47'])
def x28(root):
    falso(val(_if_repetido(root), 'IF0'))


@mutante('v1.8 importar: chave do repetido sem a descricao (outra compra no mesmo dia e valor fica de fora)', ['T46'])
def x29(root):
    cs = [b for b in call_of(proc(root, 'lerExtrato'), 'semAcento')
          if filho(b, 'ARG0').get('type') == 'lists_select_item' and eh_num(filho(filho(b, 'ARG0'), 'NUM'), 2)]
    assert len(cs) == 2, len(cs)
    for b in cs:
        trocar_bloco(root, b, G.txt(''))


@mutante('v1.8 importar: repetido nao e "gasto" (3 iguais no arquivo e 1 no app: nenhum entra)', ['T46'])
def x30(root):
    splice_out(root, so1([x for x in cadeia(stmt(_if_repetido(root), 'DO0')) if x.get('type') == 'lexical_variable_set'
                          and field(x, 'VAR').text == 'pool']))


def _if_linha(root):
    return so1(ifs(proc(root, 'lerExtrato'), lambda b: len(ramos_if(b)) >= 4 and any(
        tem_texto(filho(b, i), 'yyyyMMdd') for i, _ in ramos_if(b) if val(b, i) is not None)))


@mutante('v1.8 importar: datas depois de hoje (agendamentos) entram', ['T46', 'T47'])
def x31(root):
    b = _if_linha(root)
    falso(val(b, teste_com_texto(b, 'yyyyMMdd')))


@mutante('v1.8 importar: linhas de "saldo do dia" contadas como nao entendidas', ['T46', 'T47'])
def x32(root):
    falso(val(_if_linha(root), 'IF0'))


@mutante('v1.8 importar: descricao sem o limite de 200 caracteres', ['T46'])
def x33(root):
    ns = nums_em(proc(root, 'lerExtrato'), 200)
    assert len(ns) == 2, len(ns)
    for n in ns:
        field(n, 'NUM').text = '2000'


@mutante('v1.8 importar: arquivo em ordem crescente nao e invertido (no mesmo dia fica a ordem do arquivo)', ['T47'])
def x34(root):
    f = [b for b in blocos(proc(root, 'lerExtrato'), 'controls_forRange') if eh_num(filho(b, 'STEP'), -1)]
    b = ancestral(root, so1(f), 'controls_if')
    falso(val(b, 'IF0'))


@mutante('v1.8 importar: lancamentos do arquivo nao sao ordenados por data', ['T47'])
def x35(root):
    falso(val(so1(blocos(proc(root, 'lerExtrato'), 'controls_while')), 'TEST'))


@mutante('v1.8 importar: no empate de data o importado entra antes do que ja estava no app', ['T47'])
def x36(root):
    c = [b for b in blocos(defr(root, 'misturar'), 'math_compare') if field(b, 'OP').text == 'GTE']
    field(so1(c), 'OP').text = 'GT'


# ---- importar: aplicar, cancelar, modo de leitura
@mutante('v1.8 importar: falha ao gravar nao desfaz (importados so na memoria)', ['T47'])
def x37(root):
    st = [b for b in sets_var(proc(root, 'aplicarImportacao'), 'global lancamentos') if eh_get(filho(b, 'VALUE'), 'antigos')]
    splice_out(root, so1(st))


@mutante('v1.8 importar: mensagem conta os lancamentos que ja estavam (e nao os importados)', ['T47'])
def x38(root):
    d = so1(blocos(proc(root, 'aplicarImportacao'), 'local_declaration_statement'))
    nomes = [f.text for f in d if tg(f) == 'field' and (f.get('name') or '').startswith('VAR')]
    replace_value(val(d, 'DECL%d' % nomes.index('n')), dsl(G.llen(G.gget('lancamentos'))))


@mutante('v1.8 importar: cancelar nao avisa nem limpa o pendente', ['T47'])
def x39(root):
    b = so1(ifs(evento(root, 'Notifier1', 'AfterChoosing'), lambda b: tem_texto(filho(b, 'IF0'), 'Cancelar')
               and tem_get(filho(b, 'IF0'), 'global importPendente')))
    splice_out(root, b)


@mutante('v1.8 importar: arquivo do extrato lido como backup (o modo de leitura e ignorado)', ['T46', 'T47'])
def x40(root):
    falso(val(so1(ifs(evento(root, 'File1', 'GotText'))), 'IF0'))


@mutante('v1.8 importar: escolher o extrato nao liga o modo "extrato" (lido como backup)', ['T46', 'T47'])
def x41(root):
    splice_out(root, so1(sets_var(evento(root, 'PickerImportar', 'AfterPicking'), 'global modoLeitura')))


@mutante('v1.8 restaurar: escolher o backup nao volta o modo para "backup" (depois de importar, vira extrato)', ['T50'])
def x42(root):
    splice_out(root, so1(sets_var(evento(root, 'PickerRestaurar', 'AfterPicking'), 'global modoLeitura')))


@mutante('v1.8 importar: confirmacao sempre no plural ("Eles serao somados" para 1 lancamento)', ['T46'])
def x95(root):
    ch = [b for b in blocos(proc(root, 'lerExtrato'), 'controls_choose') if filho(b, 'THENRETURN') is not None
          and filho(b, 'THENRETURN').get('type') == 'text' and field(filho(b, 'THENRETURN'), 'TEXT').text.startswith('<br><br>Ele será somado')]
    falso(val(so1(ch), 'TEST'))


@mutante('v1.8 importar: confirmacao diz que a categoria veio da descricao mesmo quando veio do arquivo', ['T46', 'T47'])
def x96(root):
    ch = [b for b in blocos(proc(root, 'lerExtrato'), 'controls_choose') if filho(b, 'TEST').get('type') == 'math_compare'
          and eh_get(filho(filho(b, 'TEST'), 'A'), 'iCat') and filho(b, 'THENRETURN').get('type') == 'controls_choose']
    falso(val(so1(ch), 'TEST'))


# ---- data do lancamento
@mutante('v1.8 data: aceita data depois de hoje', ['T48'])
def x45(root):
    falso(val(so1(ifs(evento(root, 'PickerData', 'AfterDateSet'), lambda b: len(ramos_if(b)) == 1 and stmt(b, 'ELSE') is not None)), 'IF0'))


@mutante('v1.8 data: "Ontem" calculado como amanha', ['T48'])
def x46(root):
    m = so1(metodos(proc(root, 'atualizarCampoData'), 'Clock1', 'AddDays'))
    replace_value(val(m, 'ARG1'), dsl(G.num(1)))


def _data_do_novo(root):
    return so1([b for b in blocos(ramo_registrar(root, 'repOk'), 'controls_choose')
               if filho(b, 'TEST').get('type') == 'text_isEmpty' and eh_get(filho(filho(b, 'TEST'), 'VALUE'), 'global dataSel')])


@mutante('v1.8 data: lancamento novo ignora a data escolhida (sempre agora)', ['T48'])
def x47(root):
    verdadeiro(val(_data_do_novo(root), 'TEST'))


@mutante('v1.8 data: data escolhida grava 12:00 em vez da hora de agora', ['T48'])
def x48(root):
    m = [b for b in proprios(filho(_data_do_novo(root), 'ELSERETURN')) if b.get('type') == 'component_method'
         and mt(b).get('method_name') == 'FormatDate']
    trocar_bloco(root, so1(m), G.txt('12:00'))


@mutante('v1.8 data: lancamento novo sempre no topo (fora da ordem de data)', ['T48'])
def x49(root):
    falso(val(so1(blocos(ramo_registrar(root, 'repOk'), 'controls_while')), 'TEST'))


@mutante('v1.8 data: depois de lancar a data nao volta para hoje', ['T48'])
def x50(root):
    splice_out(root, so1(sets_var(proc(root, 'limparFormulario'), 'global dataSel')))


@mutante('v1.8 editar: o campo de data nao mostra a data do lancamento', ['T48'])
def x51(root):
    b = so1(ifs(proc(root, 'iniciarEdicao'), lambda b: any(x.get('type') == 'component_method' and mt(x).get('method_name') == 'SetDateToDisplay'
                                                          for x in cadeia(stmt(b, 'DO0')))))
    falso(val(b, 'IF0'))


@mutante('v1.8 repetir desde um mes passado: os meses seguintes nao sao lancados', ['T48'])
def x52(root):
    splice_out(root, so1(call_of(ramo_registrar(root, 'repOk'), 'gerarRecorrentes')))


@mutante('v1.8 repetir: guarda o dia de hoje, nao o dia do lancamento', ['T48'])
def x53(root):
    add = so1([b for b in blocos(ramo_registrar(root, 'repOk'), 'lists_add_items') if eh_get(filho(b, 'LIST'), 'global recorrentes')])
    lc = filho(add, 'ITEM0')
    assert lc.get('type') == 'lists_create_with'
    replace_value(val(lc, 'ADD5'), dsl(G.gget('diaHoje')))


@mutante('v1.8 tema: campo de data com aviso perde a borda vermelha ao trocar o tema', ['T48'])
def x54(root):
    st = so1(setters(proc(root, 'pintarEstados'), 'HzCampoData', 'Image'))
    field(so1([b for b in proprios(filho(st, 'VALUE')) if eh_get(b, 'global imgCampoSelErro')]), 'VAR').text = 'global imgCampoSel'


# ---- meta de economia
@mutante('v1.8 meta: porcentagem arredondada (99,6% ja mostra 100%)', ['T49'])
def x55(root):
    fl = [b for b in blocos(proc(root, 'atualizarMeta'), 'math_round') if field(b, 'OP').text == 'FLOOR']
    assert len(fl) >= 1
    for b in fl:
        field(b, 'OP').text = 'ROUND'


@mutante('v1.8 meta: sem o teto de 100% (barra passa do cartao)', ['T49'])
def x56(root):
    st = so1(sets_var(proc(root, 'atualizarMeta'), 'pct'))
    ch = filho(st, 'VALUE')
    assert ch.get('type') == 'controls_choose'
    replace_value(val(st, 'VALUE'), copy.deepcopy(filho(ch, 'ELSERETURN')))


@mutante('v1.8 meta: progresso ignora o ponto de partida (conta o saldo todo)', ['T49'])
def x57(root):
    alvo = [b for b in blocos(proc(root, 'atualizarMeta'), 'lists_select_item') if eh_get(filho(b, 'LIST'), 'global meta')
            and eh_num(filho(b, 'NUM'), 5)]
    assert len(alvo) >= 3
    for b in alvo:
        trocar_bloco(root, b, G.num(0))


def _setter_faltam(root):
    return so1([b for b in setters(proc(root, 'atualizarMeta'), 'LblMetaPrazo', 'Text') if tem_texto(b, 'Faltam ')])


@mutante('v1.8 meta: "guarde cerca de" arredonda para baixo', ['T49'])
def x58(root):
    field(so1([b for b in proprios(_setter_faltam(root)) if b.get('type') == 'math_round' and field(b, 'OP').text == 'CEILING']), 'OP').text = 'FLOOR'


@mutante('v1.8 meta: meses que faltam sem contar o mes atual', ['T49'])
def x59(root):
    ad = [b for b in proprios(_setter_faltam(root)) if b.get('type') == 'math_add' and eh_num(filho(b, 'NUM1'), 1)
          and filho(b, 'NUM0').get('type') == 'math_subtract']
    field(filho(so1(ad), 'NUM1'), 'NUM').text = '0'


@mutante('v1.8 meta: ritmo com a media de 2 meses (em vez de 3)', ['T49'])
def x60(root):
    st = so1(sets_var(proc(root, 'atualizarMeta'), 'media'))
    dv = so1([b for b in proprios(st) if b.get('type') == 'math_division' and eh_num(filho(b, 'B'), 3)])
    field(filho(dv, 'B'), 'NUM').text = '2'


@mutante('v1.8 meta: cor do ritmo invertida (chegar antes do prazo fica amarelo)', ['T49'])
def x61(root):
    st = so1([b for b in setters(proc(root, 'atualizarMeta'), 'LblMetaRitmo', 'TextColor') if filho(b, 'VALUE').get('type') == 'controls_choose'])
    ch = filho(st, 'VALUE')
    a, b = val(ch, 'THENRETURN'), val(ch, 'ELSERETURN')
    x, y = a[0], b[0]
    a.remove(x)
    b.remove(y)
    a.append(y)
    b.append(x)


@mutante('v1.8 meta: juntar exatamente o valor nao conta como alcancada', ['T49'])
def x62(root):
    c = [b for b in blocos(proc(root, 'atualizarMeta'), 'math_compare') if field(b, 'OP').text == 'GTE']
    field(so1(c), 'OP').text = 'GT'


@mutante('v1.8 meta: prazo sugerido de 6 meses (em vez de 12)', ['T49'])
def x63(root):
    field(so1(nums_em(proc(root, 'abrirMeta'), 12)), 'NUM').text = '6'


@mutante('v1.8 meta: meta nova ja vem com "incluir meu saldo atual" marcado', ['T49'])
def x64(root):
    verdadeiro(val(so1(sets_var(proc(root, 'abrirMeta'), 'global metaSaldoSel')), 'VALUE'))


def _if_valida_meta(root):
    return so1(ifs(evento(root, 'BtnSalvarMeta', 'Click'), lambda b: len(ramos_if(b)) == 3))


@mutante('v1.8 meta: aceita valor zero', ['T49'])
def x65(root):
    b = _if_valida_meta(root)
    falso(val(b, ramo_com_texto(b, 'Digite um valor maior que zero.')))


@mutante('v1.8 meta: nome sem o limite de 40 caracteres', ['T49'])
def x66(root):
    ns = nums_em(evento(root, 'BtnSalvarMeta', 'Click'), 40)
    assert len(ns) == 2, len(ns)
    for n in ns:
        field(n, 'NUM').text = '400'


@mutante('v1.8 meta: nao confere a gravacao (falso "salva")', ['T49'])
def x67(root):
    b = so1(ifs(evento(root, 'BtnSalvarMeta', 'Click'), lambda b: filho(b, 'IF0').get('type') == 'procedures_callreturn'
               and field(filho(b, 'IF0'), 'PROCNAME').text == 'registroIgual'))
    verdadeiro(val(b, 'IF0'))


@mutante('v1.8 meta: editar zera o progresso (ponto de partida recalculado)', ['T49'])
def x68(root):
    ch = [b for b in blocos(evento(root, 'BtnSalvarMeta', 'Click'), 'controls_choose') if eh_get(filho(b, 'ELSERETURN'), 'global saldoTotal')]
    trocar_bloco(root, so1(ch), G.gget('saldoTotal'))


@mutante('v1.8 meta: prazo pode voltar para antes deste mes', ['T49'])
def x69(root):
    replace_value(val(so1(sets_var(evento(root, 'BtnPrazoAnt', 'Click'), 'global metaPrazoEdit')), 'VALUE'),
                  dsl(G.msub(G.gget('metaPrazoEdit'), G.num(1))))


@mutante('v1.8 meta: prazo sem o limite de 10 anos', ['T49'])
def x70(root):
    replace_value(val(so1(sets_var(evento(root, 'BtnPrazoProx', 'Click'), 'global metaPrazoEdit')), 'VALUE'),
                  dsl(G.madd(G.gget('metaPrazoEdit'), G.num(1))))


@mutante('v1.8 meta: seta de voltar o prazo nunca desliga', ['T49'])
def x71(root):
    verdadeiro(val(so1(setters(proc(root, 'pintarMetaEdit'), 'BtnPrazoAnt', 'Enabled')), 'VALUE'))


@mutante('v1.8 meta: remover nao confere a gravacao (falso "removida")', ['T49'])
def x72(root):
    b = so1(ifs(evento(root, 'Notifier1', 'AfterChoosing'), lambda b: stmt(b, 'ELSE') is not None and any(
        x.get('type') == 'text' and field(x, 'TEXT').text == 'Erro: não foi possível remover a meta neste aparelho.'
        for x in stmt(b, 'ELSE').iter(NS + 'block'))))
    verdadeiro(val(b, 'IF0'))


@mutante('v1.8 meta: meta estragada no aparelho nao e ignorada', ['T49'])
def x73(root):
    st = so1([b for b in sets_var(proc(root, 'carregarPreferencias'), 'global meta') if filho(b, 'VALUE').get('type') == 'lists_create_with'
              and val(filho(b, 'VALUE'), 'ADD0') is not None])
    verdadeiro(val(ancestral(root, st, 'controls_if'), 'IF0'))


@mutante('v1.8 meta: cartao pequeno aparece no Lancar mesmo sem meta', ['T49'])
def x74(root):
    verdadeiro(val(so1(setters(proc(root, 'atualizarMeta'), 'PnlMetaMini', 'Visible')), 'VALUE'))


@mutante('v1.8 meta: barra do cartao pequeno na escala da grande (passa da borda)', ['T49'])
def x75(root):
    field(so1(nums_em(so1(setters(proc(root, 'atualizarMeta'), 'BarMetaMini', 'WidthPercent')), 50)), 'NUM').text = '86'


@mutante('v1.8 meta: "Ver" do cartao pequeno abre o Lancar (em vez da Evolucao)', ['T49'])
def x76(root):
    c = so1(call_of(evento(root, 'BtnMetaMini', 'Click'), 'mostrarAba'))
    field(filho(c, 'ARG0'), 'NUM').text = '1'


@mutante('v1.8 tema: valor da meta com aviso perde a borda vermelha ao trocar o tema', ['T49'])
def x77(root):
    st = so1(setters(proc(root, 'pintarEstados'), 'HzCampoMetaValor', 'Image'))
    field(so1([b for b in proprios(filho(st, 'VALUE')) if eh_get(b, 'global imgCampoErro')]), 'VAR').text = 'global imgCampo'


@mutante('v1.8 tela: a tela da meta aparece junto com a Evolucao', ['T49', 'T51'])
def x78(root):
    field(so1(nums_em(so1(setters(proc(root, 'mostrarAba'), 'PnlMeta', 'Visible')), 7)), 'NUM').text = '5'


# ---- backup: data do ultimo, lembrete, meta no arquivo
@mutante('v1.8 backup: "hoje/ontem" contados em periodos de 24 h (backup as 23h aparece como "hoje" no dia seguinte)', ['T50'])
def x79(root):
    velho = G.quotient(G.mmax(lambda: G.num(0), lambda: G.msub(G.cmeth('Clock1', 'Clock', 'SystemTime'), G.lget('ms'))), G.num(86400000))
    replace_value(val(defr(root, 'diasDesde'), 'RETURN'), dsl(velho))


@mutante('v1.8 backup: alerta a partir de 20 dias (em vez de 30)', ['T50'])
def x80(root):
    ns = nums_em(proc(root, 'atualizarInfoBackup'), 30)
    assert len(ns) == 2, len(ns)
    for n in ns:
        field(n, 'NUM').text = '20'


def _if_lembrete(root):
    return so1(ifs(evento(root, 'Screen1', 'Initialize'), lambda b: tem_get(filho(b, 'IF0'), 'global lembreteBackup')))


@mutante('v1.8 lembrete: aparece mesmo com menos de 10 lancamentos', ['T50'])
def x81(root):
    field(so1(nums_em(filho(_if_lembrete(root), 'IF0'), 10)), 'NUM').text = '0'


@mutante('v1.8 lembrete: repete a cada abertura (sem esperar 7 dias)', ['T50'])
def x82(root):
    field(so1(nums_em(filho(_if_lembrete(root), 'IF0'), 7)), 'NUM').text = '0'


@mutante('v1.8 lembrete: nao guarda quando lembrou (repete ao reabrir)', ['T50'])
def x83(root):
    splice_out(root, so1(metodos(stmt(_if_lembrete(root), 'DO0'), 'TinyDB1', 'StoreValue')))


@mutante('v1.8 backup: exportar a planilha conta como backup', ['T50'])
def x84(root):
    verdadeiro(val(so1(ifs(evento(root, 'File1', 'AfterFileSaved'))), 'IF0'))


@mutante('v1.8 backup: nao guarda a data do backup (sempre "ainda nao fez backup")', ['T50'])
def x85(root):
    splice_out(root, so1(metodos(evento(root, 'File1', 'AfterFileSaved'), 'TinyDB1', 'StoreValue')))


@mutante('v1.8 backup: a meta fica fora do arquivo (sem a linha M)', ['T50'])
def x86(root):
    b = so1(ifs(evento(root, 'BtnBackup', 'Click'), lambda b: stmt(b, 'DO0') is not None and any(
        x.get('type') == 'text' and field(x, 'TEXT').text == 'M' for x in stmt(b, 'DO0').iter(NS + 'block'))))
    splice_out(root, b)


def _if_linhas_backup(root):
    return so1(ifs(proc(root, 'lerBackup'), lambda b: len(ramos_if(b)) >= 6))


@mutante('v1.8 restaurar: linha M ignorada (a meta nao volta)', ['T50'])
def x87(root):
    b = _if_linhas_backup(root)
    falso(val(b, teste_com_texto(b, 'M')))


@mutante('v1.8 restaurar: a meta do aparelho fica como estava (nem volta a do backup, nem some com backup da v1.7)', ['T50'])
def x88(root):
    m = [b for b in metodos(proc(root, 'aplicarBackup'), 'TinyDB1', 'StoreValue') if tem_texto(b, 'meta')]
    splice_out(root, so1(m))


@mutante('v1.8 restaurar: linha M com valores invalidos aceita', ['T50'])
def x89(root):
    b = _if_linhas_backup(root)
    i = teste_com_texto(b, 'M')
    e = filho(b, i)
    assert e.get('type') == 'logic_operation' and field(e, 'OP').text == 'AND'
    replace_value(val(b, i), copy.deepcopy(filho(e, 'A')))


@mutante('v1.8 Seus dados: abrir a tela nao atualiza a informacao do backup', ['T50'])
def x90(root):
    splice_out(root, so1(call_of(proc(root, 'mostrarAba'), 'atualizarInfoBackup')))


@mutante('v1.8 tema: icone de importar nao troca no escuro', ['T51'])
def x91(root):
    field(so1(textos(proc(root, 'definirTema'), 'ic_importar_d.png')), 'TEXT').text = 'ic_importar.png'


# ---- erros de componente
def _if_erros(root):
    return so1(ifs(evento(root, 'Screen1', 'ErrorOccurred'), lambda b: len(ramos_if(b)) == 3))


@mutante('v1.8 cancelar o seletor de arquivos vira aviso de erro (4501 tratado como falha)', ['T46', 'T50'])
def x92(root):
    b = _if_erros(root)
    assert nums_em(filho(b, 'IF0'), 4501)
    falso(val(b, 'IF0'))


@mutante('v1.8 editar lancamento com data impossivel mostra aviso tecnico do calendario', ['T48'])
def x93(root):
    b = _if_erros(root)
    assert any(x.get('type') == 'component_component_block' and mt(x).get('instance_name') == 'PickerData' for x in proprios(filho(b, 'IF1')))
    falso(val(b, 'IF1'))


@mutante('v1.8 app aberto de um dia para o outro: o Lancar continua dizendo "Hoje" com a data de ontem', ['T48'])
def x94(root):
    p = proc(root, 'mostrarAba')
    b = so1([x for x in cadeia(stmt(p, 'STACK')) if x.get('type') == 'controls_if'
             and any(y.get('type') == 'procedures_callnoreturn' and field(y, 'PROCNAME').text == 'atualizarCampoData' for y in proprios(x))])
    splice_out(root, b)


# ---- tela (.scm e imagens) da v1.8
@tela('v1.8 campo de data como botao comum (sem calendario)', ['T25'])
def y1(d, pkg):
    scm_nodes(d)['PickerData']['$Type'] = 'Button'


@tela('v1.8 icone de importar apagado do pacote', ['T25', 'T51'])
def y2(d, pkg):
    os.remove(os.path.join(pkg, 'assets', 'ic_importar.png'))


@tela('v1.8 informacao do ultimo backup apagada da tela', ['T25'])
def y3(d, pkg):
    pai = [n for n in scm_nodes(d).values() if any(c['$Name'] == 'LblBackupInfo' for c in n.get('$Components', []))][0]
    pai['$Components'] = [c for c in pai['$Components'] if c['$Name'] != 'LblBackupInfo']


@tela('v1.8 "Importar extrato" escolhe pasta em vez de arquivo', ['T51'])
def y4(d, pkg):
    scm_nodes(d)['PickerImportar']['Action'] = 'Pick Directory'


@tela('v1.8 campo de data sem a moldura (imagem do campo)', ['T51'])
def y5(d, pkg):
    scm_nodes(d)['HzCampoData'].pop('Image', None)


@tela('v1.8 cartao pequeno da meta com a imagem do cartao grande', ['T51'])
def y6(d, pkg):
    scm_nodes(d)['PnlMetaMini']['Image'] = 'cartao_lancar.png'


# =========================================================================== v1.8.1: "tem certeza?" e botoes no Android
def _ramo_choice(root, t):
    """O "se" de Notifier1.AfterChoosing cujo TESTE fala da resposta t (ex.: 'Sim, excluir')."""
    h = evento(root, 'Notifier1', 'AfterChoosing')
    return so1([x for x in cadeia(stmt(h, 'DO')) if x.get('type') == 'controls_if' and filho(x, 'IF0') is not None
                and tem_texto(filho(x, 'IF0'), t)])


def _troca_filhos(ch, a, b):
    va, vb = val(ch, a), val(ch, b)
    xa, xb = list(va), list(vb)
    for x in xa:
        va.remove(x)
    for x in xb:
        vb.remove(x)
    for x in xb:
        va.append(x)
    for x in xa:
        vb.append(x)


@mutante('v1.8.1 excluir apaga direto, sem perguntar', ['T53'])
def z1(root):
    b = _ramo_choice(root, 'Sim, excluir')
    field(so1(textos(filho(b, 'IF0'), 'Sim, excluir')), 'TEXT').text = 'Excluir'


@mutante('v1.8.1 confirmacao de excluir com o botao "Sim" (a resposta nao bate: nunca exclui)', ['T53', 'T06'])
def z2(root):
    field(so1(textos(proc(root, 'confirmarExclusao'), 'Sim, excluir')), 'TEXT').text = 'Sim'


@mutante('v1.8.1 editar grava sem perguntar', ['T53'])
def z3(root):
    b = so1(ifs(proc(root, 'registrar'), lambda x: eh_get(filho(x, 'IF0'), 'global edicaoConfirmada')))
    verdadeiro(val(b, 'IF0'))


@mutante('v1.8.1 "Voltar" grava a edicao e "Salvar" nao', ['T53'])
def z4(root):
    b = _ramo_choice(root, 'Salvar')
    field(so1(textos(filho(b, 'IF0'), 'Salvar')), 'TEXT').text = 'Voltar'


@mutante('v1.8.1 a confirmacao da edicao nao volta a "falso" (a edicao seguinte grava sem perguntar)', ['T53'])
def z5(root):
    alvos = [b for p in (evento(root, 'Notifier1', 'AfterChoosing'), proc(root, 'registrar'))
             for b in sets_var(p, 'global edicaoConfirmada')
             if filho(b, 'VALUE') is not None and filho(b, 'VALUE').get('type') == 'logic_boolean'
             and field(filho(b, 'VALUE'), 'BOOL').text == 'FALSE']
    assert len(alvos) == 2, len(alvos)
    for b in alvos:
        splice_out(root, b)


@mutante('v1.8.1 "Salvar" fora de uma edicao cria lancamento com o que estiver no formulario', ['T53'])
def z6(root):
    b = _ramo_choice(root, 'Salvar')
    cond = filho(b, 'IF0')
    assert cond.get('type') == 'logic_operation' and tem_texto(filho(cond, 'A'), 'Salvar')
    replace_value(val(b, 'IF0'), copy.deepcopy(filho(cond, 'A')))


@mutante('v1.8.1 remover foto: "Cancelar" e que remove', ['T53'])
def z7(root):
    b = _ramo_choice(root, 'Remover foto')
    field(so1(textos(filho(b, 'IF0'), 'Remover foto')), 'TEXT').text = 'Cancelar'


@mutante('v1.8.1 remover foto apaga direto, sem perguntar', ['T53'])
def z8(root):
    h = evento(root, 'BtnRemoverFoto', 'Click')
    m = so1(metodos(h, 'Notifier1', 'ShowChooseDialog'))
    st = stmt(h, 'DO')
    i = list(st).index(m)
    st.remove(m)
    st.insert(i, dsl(G.seq([G.gset('perfilFoto', G.txt('')), G.call_stmt('mostrarPerfil'),
                            G.call_stmt('guardarPref', G.txt('perfil_foto'), G.txt(''))])))


@mutante('v1.8.1 confirmacao de excluir mostra o lancamento de baixo (indice + 1)', ['T53'])
def z9(root):
    p = proc(root, 'confirmarExclusao')
    m = so1(metodos(p, 'Notifier1', 'ShowChooseDialog'))
    gets = [x for x in proprios(filho(m, 'ARG0')) if eh_get(x, 'global indiceSel')]
    assert len(gets) >= 4, len(gets)
    for g in gets:
        trocar_bloco(root, g, G.madd(G.gget('indiceSel'), G.num(1)))


@mutante('v1.8.1 confirmacao da edicao mostra a data antiga mesmo com outra data escolhida', ['T53'])
def z10(root):
    m = so1(metodos(proc(root, 'confirmarEdicao'), 'Notifier1', 'ShowChooseDialog'))
    ch = so1([x for x in proprios(filho(m, 'ARG0')) if x.get('type') == 'controls_choose' and eh_get(filho(x, 'ELSERETURN'), 'global dataSel')])
    replace_value(val(ch, 'ELSERETURN'), copy.deepcopy(filho(ch, 'THENRETURN')))


@mutante('v1.8.1 editar para HOJE volta a manter a data antiga (o defeito achado na v1.8)', ['T53'])
def z11(root):
    h = evento(root, 'PickerData', 'AfterDateSet')
    b = so1([x for x in ifs(h) if filho(x, 'IF0') is not None and filho(x, 'IF0').get('type') == 'logic_operation'
             and tem_get(filho(x, 'IF0'), 'global editIndice')])
    cond = filho(b, 'IF0')
    replace_value(val(b, 'IF0'), copy.deepcopy(filho(cond, 'A')))


@mutante('v1.8.1 setas do periodo com a imagem do tema claro no escuro', ['T52'])
def z12(root):
    s_ = so1(setters(proc(root, 'atualizarPeriodoUI'), 'BtnPerAnt', 'Image'))
    trocar_bloco(root, so1([x for x in proprios(s_) if eh_get(x, 'global imgSetaEsq')]), G.txt('seta_esq.png'))


@mutante('v1.8.1 seta para frente aparece no mes atual e some nos meses passados (imagens trocadas)', ['T36', 'T52'])
def z13(root):
    s_ = so1(setters(proc(root, 'atualizarPeriodoUI'), 'BtnPerProx', 'Image'))
    ch = filho(s_, 'VALUE')
    assert ch.get('type') == 'controls_choose'
    _troca_filhos(ch, 'THENRETURN', 'ELSERETURN')


@mutante('v1.8.1 seta do ano para frente nunca some', ['T41', 'T52'])
def z14(root):
    s_ = so1(setters(proc(root, 'atualizarEvolucao'), 'BtnEvoAnoProx', 'Image'))
    verdadeiro(val(filho(s_, 'VALUE'), 'TEST'))


@mutante('v1.8.1 inicial do mes atual sem destaque', ['T41', 'T52'])
def z15(root):
    field(so1(textos(proc(root, 'atualizarEvolucao'), '_a')), 'TEXT').text = '_n'


@mutante('v1.8.1 iniciais dos meses com a imagem clara no tema escuro', ['T52'])
def z16(root):
    field(so1(textos(proc(root, 'atualizarEvolucao'), '_d')), 'TEXT').text = ''


@mutante('v1.8.1 iniciais fora de ordem (marco e abril trocados)', ['T41', 'T52'])
def z17(root):
    g = top(root, 'global_declaration', 'letrasMes')
    t = so1(textos(g, 'j|f|m|a|m|j|j|a|s|o|n|d'))
    field(t, 'TEXT').text = 'j|f|a|m|m|j|j|a|s|o|n|d'


@mutante('v1.8.1 seta de voltar o prazo da meta nunca some (so desliga)', ['T52'])
def z18(root):
    s_ = so1(setters(proc(root, 'pintarMetaEdit'), 'BtnPrazoAnt', 'Image'))
    verdadeiro(val(filho(s_, 'VALUE'), 'TEST'))


@mutante('v1.8.1 setas do prazo nao acompanham o tema escuro', ['T52'])
def z19(root):
    s_ = so1(setters(proc(root, 'pintarMetaEdit'), 'BtnPrazoProx', 'Image'))
    trocar_bloco(root, so1([x for x in proprios(s_) if eh_get(x, 'global imgSetaDir')]), G.txt('seta_dir.png'))


@mutante('v1.8.1 tela da meta nasce sem prazo (trocar o tema e voltar muda a seta do prazo)', ['T33'])
def z20(root):
    h = evento(root, 'Screen1', 'Initialize')
    splice_out(root, so1([x for x in cadeia(stmt(h, 'DO')) if x.get('type') == 'lexical_variable_set'
                          and field(x, 'VAR').text == 'global metaPrazoEdit']))


# ---- tela (.scm e imagens) da v1.8.1
def _png_rgb_branco(pkg, nome):
    from PIL import Image as _I
    p = os.path.join(pkg, 'assets', nome)
    im = _I.open(p).convert('RGBA')
    fundo = _I.new('RGBA', im.size, (255, 255, 255, 255))
    _I.alpha_composite(fundo, im).convert('RGB').save(p)


@tela('v1.8.1 iniciais dos meses voltam a ser texto em botao pequeno (como na v1.8)', ['T52', 'T54'])
def w1(d, pkg):
    nos = scm_nodes(d)
    for i, letra in enumerate('JFMAMJJASOND', 1):
        b = nos['BtnMes%d' % i]
        b.pop('Image', None)
        b.update({'Text': letra, 'BackgroundColor': '&H00FFFFFF', 'FontSize': '12.5'})


@tela('v1.8.1 botao de texto transparente sem forma (no Android vira quadrado vazio)', ['T52', 'T54'])
def w2(d, pkg):
    assert scm_nodes(d)['BtnVerHist'].pop('Shape') == '1'


@tela('v1.8.1 "Remover foto" volta a 40 dp (texto cortado no pe)', ['T54'])
def w3(d, pkg):
    scm_nodes(d)['BtnRemoverFoto']['Height'] = '40'


@tela('v1.8.1 nomes das abas voltam a 13 sp (Historico e Evolucao quebram em 2 linhas numa tela de 360 dp)', ['T54'])
def w4(d, pkg):
    for n in ('BtnNavLancar', 'BtnNavHistorico', 'BtnNavGrafico', 'BtnNavEvolucao'):
        scm_nodes(d)[n]['FontSize'] = '13'


@tela('v1.8.1 pilulas voltam a 40 dp (texto cortado com a fonte do sistema em 115%)', ['T54'])
def w5(d, pkg):
    nos = scm_nodes(d)
    for n in ('BtnNavLancar', 'BtnNavHistorico', 'BtnNavGrafico', 'BtnNavEvolucao', 'BtnModoMes', 'BtnModoAno', 'BtnModoTudo',
              'BtnTemaClaro', 'BtnTemaEscuro', 'PickerFoto'):
        nos[n]['Height'] = '40'


@tela('v1.8.1 seta para tras desenhada para a direita (arquivo trocado)', ['T52'])
def w6(d, pkg):
    shutil.copyfile(os.path.join(pkg, 'assets', 'seta_dir.png'), os.path.join(pkg, 'assets', 'seta_esq.png'))


@tela('v1.8.1 a imagem da inicial M mostra um N', ['T52'])
def w7(d, pkg):
    shutil.copyfile(os.path.join(pkg, 'assets', 'mes_n_n.png'), os.path.join(pkg, 'assets', 'mes_m_n.png'))


@tela('v1.8.1 seta sem transparencia (no aparelho: um quadrado branco em volta)', ['T52'])
def w8(d, pkg):
    _png_rgb_branco(pkg, 'seta_esq.png')


@tela('v1.8.1 seta do tema escuro com a cor do claro', ['T52', 'T33'])
def w9(d, pkg):
    shutil.copyfile(os.path.join(pkg, 'assets', 'seta_dir.png'), os.path.join(pkg, 'assets', 'seta_dir_d.png'))


@tela('v1.8.1 botao da seta mais estreito que a figura (seta achatada)', ['T52'])
def w10(d, pkg):
    scm_nodes(d)['BtnPerAnt']['Width'] = '40'


@tela('v1.8.1 imagem "sem seta" deixa de ser transparente', ['T52'])
def w11(d, pkg):
    from PIL import Image as _I
    _I.new('RGBA', (8, 8), (14, 124, 102, 255)).save(os.path.join(pkg, 'assets', 'aba_inativa.png'))


@tela('v1.8.1 "x" da busca volta a ser texto em botao transparente', ['T52'])
def w12(d, pkg):
    b = scm_nodes(d)['BtnLimparBusca']
    b.pop('Image', None)
    b.update({'Text': '×', 'BackgroundColor': '&H00FFFFFF', 'FontSize': '20'})
# <<< fim dos mutantes novos da v1.8


# >>> mutantes novos da v1.9 (mutantes_novos19.py)
# ============================================================================= v1.9 (colado aqui depois dos da v1.8)
# 1) APOSENTA os mutantes de partes que SAIRAM do app a pedido do usuario (pizza "Entradas x Despesas" e a legenda
#    dela, "Ultimos lancamentos", "Saldo acumulado", "ha um ano" e "Ano a ano"): nao existe mais o que mutar.
# 2) REFAZ o alvo dos que miravam blocos que mudaram de lugar (a foto agora e guardada em usarFoto; o tratador de
#    erros ganhou o ramo da camera; a barra vermelha "% das despesas" saiu; o botao de texto transparente que
#    sobrou e o atalho da Evolucao) -- mesmo tipo de defeito, no lugar novo.
# 3) Mutantes NOVOS: rosca (desenho, relogio, cores, vao), lista de categorias, Evolucao enxuta e camera.
# Os localizadores falham (AssertionError) se a estrutura nao for exatamente a esperada.

APOSENTADOS19 = {
    'grafico: cores trocadas (Entradas vermelho, Despesas verde)',
    'grafico: envia lista de cores VAZIA quando nao ha lancamentos (sem o "se tem cor")',
    'grafico: fatia Entradas sempre criada (mesmo com total zero)',
    'grafico: fatia Despesas usa o total de ENTRADAS',
    'porcentagem: Despesas mostra a mesma % das Entradas (complemento esquecido)',
    'porcentagem das Entradas: arredonda para baixo (FLOOR) em vez de arredondar',
    'porcentagem das Despesas (complemento): arredonda para baixo (FLOOR) em vez de arredondar',
    'porcentagem das Entradas: arredonda sempre para cima (CEILING)',
    'grafico: pizza visivel mesmo sem lancamentos (>= em vez de >)',
    'resumo do grafico mostra 5 lancamentos por tipo em vez de 3',
    'resumo do grafico: entradas sem o sinal + (aparece "- ")',
    '"Ver historico completo" abre o grafico em vez do historico',
    'v1.7 ultimos lancamentos do grafico ignoram o periodo',
    'v1.7 evolucao: lancamento sem data fica fora do saldo acumulado',
    'v1.7 evolucao: "ha um ano" mostra 11 meses atras',
    'v1.7 evolucao: anos do mais antigo para o mais novo',
    'Chart1 deixa de ser pizza (Type 4 -> 0)',
    'Numeros pequenos dentro das fatias voltam a aparecer (DataLabelColor branco)',
    'Ponto da legenda de Entradas fica vermelho',
    'v1.7 lista de anos com 1 linha so (some entradas/despesas)',
}
_antes19 = len(MUTANTES) + len(TELA)
MUTANTES[:] = [m for m in MUTANTES if m[0] not in APOSENTADOS19]
TELA[:] = [m for m in TELA if m[0] not in APOSENTADOS19]
assert _antes19 - len(MUTANTES) - len(TELA) == len(APOSENTADOS19), 'algum rotulo aposentado nao existe'


def _refazer(lista, rotulo, novo_rotulo, esperado, fn):
    idx = [i for i, m in enumerate(lista) if m[0] == rotulo]
    assert len(idx) == 1, rotulo
    lista[idx[0]] = (novo_rotulo, esperado, fn)


def _if_erros(root):
    """v1.9: o tratador de erros tem 4 ramos (4501, calendario, arquivos e CAMERA) + o "senao"."""
    return so1(ifs(evento(root, 'Screen1', 'ErrorOccurred'), lambda b: len(ramos_if(b)) == 4))


def _gen(p, tipo, prop):
    """Setters genericos ("set Tipo.Prop of component") dentro de p."""
    return [b for b in blocos(p, 'component_set_get') if mt(b).get('is_generic') == 'true' and mt(b).get('set_or_get') == 'set'
            and mt(b).get('component_type') == tipo and mt(b).get('property_name') == prop]


def _ramo(b, nome):
    """Instrucoes diretamente no corpo nome (DO0 / ELSE) de um "se"."""
    return cadeia(stmt(b, nome))


# ---------------------------------------------------------------- 2) alvos refeitos
def r62(root):
    # bolinha da lista: o ramo do tema escuro pega a lista do claro
    p = proc(root, 'pintarLinhaCat')
    g = so1(gets(p, 'global pontosCatEscuro'))
    field(g, 'VAR').text = 'global pontosCatClaro'


_refazer(MUTANTES, 'categorias: icones das FORMAS DE PAGAMENTO nas linhas de categoria',
         'v1.9 lista: no tema escuro as bolinhas continuam as do claro', ['T21'], r62)


def r64(root):
    # sem limite: a barra (trilho) aparece mesmo assim
    p = proc(root, 'pintarLinhaCat')
    se = so1(ifs(p, lambda b: len(ramos_if(b)) == 1 and stmt(b, 'ELSE') is not None))
    vis = so1([x for x in _ramo(se, 'ELSE') if x in _gen(p, 'HorizontalArrangement', 'Visible')])
    verdadeiro(val(vis, 'VALUE'))


_refazer(MUTANTES, 'categorias: barra proporcional ao TOTAL e nao a maior categoria (a maior nunca chega a 72%)',
         'v1.9 lista: categoria SEM limite tambem mostra a barra', ['T32', 'T21'], r64)


def r81(root):
    splice_out(root, so1(call_of(proc(root, 'usarFoto'), 'guardarPref')))


_refazer(MUTANTES, 'PickerFoto.AfterPicking: nao guarda a foto (some ao reabrir)',
         'v1.9 usarFoto: nao guarda a foto (da galeria ou da camera; some ao reabrir)', ['T34', 'T56'], r81)
_refazer(MUTANTES, 'CanvasPerfil.Touched: tocar no avatar grande nao abre a galeria',
         'CanvasPerfil.Touched removido: tocar no avatar grande nao oferece camera nem galeria', ['T34', 'T56'],
         [m for m in MUTANTES if m[0] == 'CanvasPerfil.Touched: tocar no avatar grande nao abre a galeria'][0][2])
_refazer(MUTANTES, 'v1.7 evolucao: tocar num mes abre o mes seguinte',
         'v1.7 evolucao: tocar num mes escolhe o mes seguinte', ['T41'],
         [m for m in MUTANTES if m[0] == 'v1.7 evolucao: tocar num mes abre o mes seguinte'][0][2])


def w2b(d, pkg):
    assert scm_nodes(d)['BtnEvoVerMes'].pop('Shape') == '1'


_refazer(TELA, 'v1.8.1 botao de texto transparente sem forma (no Android vira quadrado vazio)',
         'v1.8.1 botao de texto transparente sem forma (no Android vira quadrado vazio; agora o atalho da Evolucao)',
         ['T52', 'T54'], w2b)


# ---------------------------------------------------------------- 3a) rosca: desenho e relogio
@mutante('v1.9 rosca: desenhada na hora, sem esperar a tela medir o Canvas (sai esticada no aparelho)', ['T21'])
def z1(root):
    c = so1(call_of(proc(root, 'montarRosca'), 'pedirRosca'))
    field(c, 'PROCNAME').text = 'desenharRosca'
    mt(c).set('name', 'desenharRosca')


@mutante('v1.9 rosca: o relogio desenha mesmo com o Canvas sem tamanho (Width >= 0)', ['T21'])
def z2(root):
    se = so1(ifs(evento(root, 'ClockRosca', 'Timer'), lambda b: stmt(b, 'ELSE') is not None))
    t = filho(se, 'IF0')
    assert t.get('type') == 'math_compare' and field(t, 'OP').text == 'GT'
    field(t, 'OP').text = 'GTE'


@mutante('v1.9 rosca: o relogio nunca desiste (sem o limite de 50 tentativas: gasta bateria)', ['T21'])
def z3(root):
    ev = evento(root, 'ClockRosca', 'Timer')
    splice_out(root, so1(ifs(ev, lambda b: nums_em(b, 50) and stmt(b, 'ELSE') is None)))


@mutante('v1.9 rosca: o relogio nao desliga depois de desenhar (redesenha sem parar)', ['T21'])
def z4(root):
    ev = evento(root, 'ClockRosca', 'Timer')
    se = so1(ifs(ev, lambda b: stmt(b, 'ELSE') is not None))
    splice_out(root, so1([x for x in _ramo(se, 'DO0') if x.get('type') == 'component_set_get']))


@mutante('v1.9 rosca: nao apaga o desenho anterior (Clear removido: fatias velhas ficam)', ['T21'])
def z5(root):
    splice_out(root, so1(metodos(proc(root, 'desenharRosca'), 'CanvasRosca', 'Clear')))


@mutante('v1.9 rosca: fatias comecam as 3 horas (0 grau) em vez do alto', ['T21'])
def z6(root):
    field(so1(nums_em(proc(root, 'desenharRosca'), -90)), 'NUM').text = '0'


@mutante('v1.9 rosca: desenhada no sentido anti-horario (varredura negativa)', ['T21'])
def z7(root):
    arcos = metodos(proc(root, 'desenharRosca'), 'CanvasRosca', 'DrawArc')
    d = so1([a for a in arcos if filho(a, 'ARG5').get('type') == 'math_subtract'])
    s = filho(d, 'ARG5')
    a, b = val(s, 'A'), val(s, 'B')
    x, y = a[0], b[0]
    a.remove(x); b.remove(y); a.append(y); b.append(x)


@mutante('v1.9 rosca: sem o vao entre as fatias', ['T21'])
def z8(root):
    st = so1(sets_var(proc(root, 'desenharRosca'), 'vao'))
    replace_value(val(st, 'VALUE'), dsl(G.num(0)))


@mutante('v1.9 rosca: vao de 20 graus (fatias pequenas somem)', ['T21'])
def z9(root):
    st = so1(sets_var(proc(root, 'desenharRosca'), 'vao'))
    for n in nums_em(st, 2):
        field(n, 'NUM').text = '20'


@mutante('v1.9 rosca: fatias calculadas sobre 180 graus (meia rosca)', ['T21'])
def z10(root):
    st = so1(sets_var(proc(root, 'desenharRosca'), 'varre'))
    field(so1(nums_em(st, 360)), 'NUM').text = '180'


@mutante('v1.9 rosca: arco preenchido (o furo some)', ['T21'])
def z11(root):
    for a in metodos(proc(root, 'desenharRosca'), 'CanvasRosca', 'DrawArc'):
        verdadeiro(val(a, 'ARG7'))


@mutante('v1.9 rosca: arco com centro (vira fatia de pizza)', ['T21'])
def z12(root):
    for a in metodos(proc(root, 'desenharRosca'), 'CanvasRosca', 'DrawArc'):
        verdadeiro(val(a, 'ARG6'))


@mutante('v1.9 rosca: caixa do arco encostada na borda (metade do anel cortada)', ['T21'])
def z13(root):
    for a in metodos(proc(root, 'desenharRosca'), 'CanvasRosca', 'DrawArc'):
        for arg in ('ARG0', 'ARG1'):
            assert eh_num(filho(a, arg), 13)
            field(filho(a, arg), 'NUM').text = '0'


@mutante('v1.9 rosca vazia: nada desenhado (sem o anel cinza)', ['T21', 'T14'])
def z14(root):
    p = proc(root, 'desenharRosca')
    se = so1(ifs(p, lambda b: stmt(b, 'ELSE') is not None and blocos(b, 'controls_forRange')))
    splice_out(root, so1([x for x in _ramo(se, 'DO0') if x.get('type') == 'component_method']))


@mutante('v1.9 rosca vazia: anel na cor do cartao (invisivel)', ['T21', 'T14'])
def z15(root):
    g = so1(gets(proc(root, 'desenharRosca'), 'global corTrilho'))
    field(g, 'VAR').text = 'global corCartao'


@mutante('v1.9 pedirRosca nao liga o relogio (a rosca nunca e desenhada)', ['T21'])
def z16(root):
    falso(val(so1(setters(proc(root, 'pedirRosca'), 'ClockRosca', 'TimerEnabled')), 'VALUE'))


# ---------------------------------------------------------------- 3b) rosca: fatias e cores
@mutante('v1.9 rosca: cores do tema claro tambem no escuro', ['T21'])
def z17(root):
    g = so1(gets(proc(root, 'montarRosca'), 'global coresCatEscuro'))
    field(g, 'VAR').text = 'global coresCatClaro'


@mutante('v1.9 rosca: cores de Alimentacao e Transporte trocadas (tema claro)', ['T21'])
def z18(root):
    gd = top(root, 'global_declaration', 'coresCatClaro')
    lst = filho(gd, 'VALUE')
    a, b = val(lst, 'ADD0'), val(lst, 'ADD1')
    x, y = a[0], b[0]
    a.remove(x); b.remove(y); a.append(y); b.append(x)


@mutante('v1.9 rosca: categoria so com limite (sem gasto) vira fatia', ['T31'])
def z19(root):
    se = so1(ifs(proc(root, 'montarRosca')))
    t = filho(se, 'IF0')
    assert t.get('type') == 'math_compare' and field(t, 'OP').text == 'GT'
    field(t, 'OP').text = 'GTE'


@mutante('v1.9 cartao: aviso de vazio aparece junto com a rosca', ['T21', 'T32'])
def z20(root):
    verdadeiro(val(so1(setters(proc(root, 'montarRosca'), 'LblVazioGraf', 'Visible')), 'VALUE'))


@mutante('v1.9 cartao: frase de vazio sempre "Sem dados ainda" (ignora o periodo)', ['T21'])
def z21(root):
    st = so1(setters(proc(root, 'montarRosca'), 'LblVazioGraf', 'Text'))
    replace_value(val(st, 'VALUE'), dsl(G.txt('Sem dados ainda. Registre uma entrada ou despesa.')))


# ---------------------------------------------------------------- 3c) lista de categorias
@mutante('v1.9 lista: bolinha da linha r e nao da categoria c (cores trocadas entre linhas)', ['T21', 'T32'])
def z22(root):
    p = proc(root, 'pintarLinhaCat')
    st = so1(_gen(p, 'Image', 'Picture'))
    sel = filho(st, 'VALUE')
    assert sel.get('type') == 'lists_select_item' and eh_get(filho(sel, 'NUM'), 'c')
    field(filho(sel, 'NUM'), 'VAR').text = 'r'


@mutante('v1.9 lista: categoria COM limite esconde a barra do limite', ['T31', 'T40'])
def z23(root):
    p = proc(root, 'pintarLinhaCat')
    se = so1(ifs(p, lambda b: len(ramos_if(b)) == 1 and stmt(b, 'ELSE') is not None))
    vis = so1([x for x in _ramo(se, 'DO0') if x in _gen(p, 'HorizontalArrangement', 'Visible')])
    falso(val(vis, 'VALUE'))


# ---------------------------------------------------------------- 3d) Evolucao enxuta
@mutante('v1.9 evolucao: tocar num mes que ainda vem tambem escolhe (mes vazio do futuro)', ['T41'])
def z24(root):
    verdadeiro(val(so1(ifs(proc(root, 'escolherMesEvo'))), 'IF0'))


@mutante('v1.9 evolucao: a seta do ano nao leva o mes escolhido junto', ['T41'])
def z25(root):
    for ev in ('BtnEvoAnoAnt', 'BtnEvoAnoProx'):
        splice_out(root, so1(sets_var(evento(root, ev, 'Click'), 'global evoMesSel')))


@mutante('v1.9 evolucao: seta para frente leva a um mes que ainda nao chegou (sem o "ate hoje")', ['T41'])
def z26(root):
    st = so1(sets_var(evento(root, 'BtnEvoAnoProx', 'Click'), 'global evoMesSel'))
    ch = filho(st, 'VALUE')
    assert ch.get('type') == 'controls_choose'
    replace_value(val(st, 'VALUE'), copy.deepcopy(filho(ch, 'ELSERETURN')))


@mutante('v1.9 evolucao: compara com o mes passado de HOJE e nao com o anterior ao escolhido', ['T41'])
def z27(root):
    p = proc(root, 'atualizarEvolucao')
    alvo = [b for b in blocos(p, 'math_subtract') if eh_get(filho(b, 'A'), 'global evoMesSel') and eh_num(filho(b, 'B'), 1)]
    g = filho(so1(alvo), 'A')
    field(g, 'VAR').text = 'global chaveHoje'


@mutante('v1.9 evolucao: inicial destacada e sempre a do mes atual (nao a do escolhido)', ['T41', 'T52'])
def z28(root):
    p = proc(root, 'atualizarEvolucao')
    alvo = [b for b in blocos(p, 'logic_compare') if eh_get(filho(b, 'B'), 'global evoMesSel') and filho(b, 'A').get('type') == 'math_add']
    field(filho(so1(alvo), 'B'), 'VAR').text = 'global chaveHoje'


@mutante('v1.9 evolucao: mes sem lancamento continua mostrando Despesas/Entradas zeradas', ['T41'])
def z29(root):
    for s_ in setters(proc(root, 'evoResumoMes'), 'PnlEvoDesp', 'Visible') + setters(proc(root, 'evoResumoMes'), 'PnlEvoEnt', 'Visible'):
        verdadeiro(val(s_, 'VALUE'))


@mutante('v1.9 evolucao: o atalho abre o mes ATUAL no Grafico (e nao o escolhido)', ['T41'])
def z30(root):
    c = so1(call_of(evento(root, 'BtnEvoVerMes', 'Click'), 'abrirMes'))
    field(filho(c, 'ARG0'), 'VAR').text = 'global chaveHoje'


@mutante('v1.9 evolucao: titulo do resumo sempre com o ano atual', ['T41'])
def z31(root):
    st = so1(setters(proc(root, 'evoResumoMes'), 'LblTituloEvo', 'Text'))
    q = so1(blocos(st, 'math_divide', lambda b: field(b, 'OP').text == 'QUOTIENT'))
    g = so1([x for x in proprios(q) if eh_get(x, 'global evoMesSel')])
    field(g, 'VAR').text = 'global chaveHoje'


# ---------------------------------------------------------------- 3e) camera
@mutante('v1.9 camera: "Tirar foto" abre a galeria', ['T56'])
def z32(root):
    m = so1(metodos(evento(root, 'BtnTirarFoto', 'Click'), 'CameraFoto', 'TakePicture'))
    mt(m).set('component_type', 'ImagePicker')
    mt(m).set('instance_name', 'PickerFoto')
    mt(m).set('method_name', 'Open')
    field(m, 'COMPONENT_SELECTOR').text = 'PickerFoto'


@mutante('v1.9 camera: a foto tirada nao vira a foto do perfil', ['T56'])
def z33(root):
    splice_out(root, so1(call_of(evento(root, 'CameraFoto', 'AfterPicture'), 'usarFoto')))


@mutante('v1.9 camera: permissao negada vira aviso preto do App Inventor', ['T56'])
def z34(root):
    b = _if_erros(root)
    assert any(x.get('type') == 'component_component_block' and mt(x).get('instance_name') == 'CameraFoto' for x in proprios(filho(b, 'IF3')))
    falso(val(b, 'IF3'))


@mutante('v1.9 camera: qualquer erro da camera diz "sem permissao"', ['T56'])
def z35(root):
    b = _if_erros(root)
    ch = so1(blocos(stmt(b, 'DO3'), 'controls_choose'))
    verdadeiro(val(ch, 'TEST'))


@mutante('v1.9 camera: na janela da foto, "Escolher da galeria" abre a camera', ['T56', 'T34'])
def z36(root):
    ev = evento(root, 'Notifier1', 'AfterChoosing')
    se = so1(ifs(ev, lambda b: tem_texto(filho(b, 'IF0'), 'Escolher da galeria')))
    m = so1(metodos(se, 'PickerFoto', 'Open'))
    mt(m).set('component_type', 'Camera')
    mt(m).set('instance_name', 'CameraFoto')
    mt(m).set('method_name', 'TakePicture')
    field(m, 'COMPONENT_SELECTOR').text = 'CameraFoto'


@mutante('v1.9 camera: janela da foto sem "Cancelar"', ['T56', 'T34'])
def z37(root):
    m = so1(metodos(evento(root, 'CanvasPerfil', 'Touched'), 'Notifier1', 'ShowChooseDialog'))
    falso(val(m, 'ARG4'))


@mutante('v1.9 camera: mensagem de erro antiga continua depois da foto nova', ['T56'])
def z38(root):
    splice_out(root, so1(setters(proc(root, 'usarFoto'), 'LblPerfilMsg', 'Visible')))


# ---------------------------------------------------------------- 3f) tela e imagens
@tela('v1.9 rosca com fundo branco (no tema escuro, um quadrado branco em volta)', ['T21'])
def z39(d, pkg):
    no = scm_nodes(d)['CanvasRosca']
    assert no['BackgroundColor'] == '&H00FFFFFF'
    no['BackgroundColor'] = '&HFFFFFFFF'


@tela('v1.9 rosca com traco fino (LineWidth 2: so um fio)', ['T21'])
def z40(d, pkg):
    no = scm_nodes(d)['CanvasRosca']
    assert no['LineWidth'] == '26'
    no['LineWidth'] = '2'


@tela('v1.9 ClockRosca ligado desde o inicio do desenho da tela', ['T21'])
def z41(d, pkg):
    no = scm_nodes(d)['ClockRosca']
    assert no['TimerEnabled'] == 'False'
    no['TimerEnabled'] = 'True'


@tela('v1.9 bolinha de Moradia com a cor de Alimentacao (imagem trocada)', ['T21', 'T27'])
def z42(d, pkg):
    a = os.path.join(pkg, 'assets')
    shutil.copyfile(os.path.join(a, 'ponto_cat1.png'), os.path.join(a, 'ponto_cat3.png'))


@tela('v1.9 "Escolher da galeria" do tema escuro igual ao do claro (contorno claro no fundo escuro)', ['T33'])
def z43(d, pkg):
    a = os.path.join(pkg, 'assets')
    shutil.copyfile(os.path.join(a, 'pilula_contorno.png'), os.path.join(a, 'pilula_contorno_d.png'))


@tela('v1.9 componente da camera apagado da tela', ['T00', 'T25', 'T56'])
def z44(d, pkg):
    def rec(n):
        n['$Components'] = [c for c in n.get('$Components', []) if c['$Name'] != 'CameraFoto']
        for c in n['$Components']:
            rec(c)
    antes = len(scm_nodes(d))
    rec(d['Properties'])
    assert len(scm_nodes(d)) == antes - 1


@tela('v1.9 rosca maior que o espaco (Canvas de 200 dp)', ['T21'])
def z45(d, pkg):
    no = scm_nodes(d)['CanvasRosca']
    no['Width'] = no['Height'] = '200'
# <<< fim dos mutantes novos da v1.9


# >>> mutantes novos da v2.0 (mutantes_novos20.py)
# ============================================================================= v2.0 (colado aqui depois dos da v1.9)
# Mutantes NOVOS da v2.0: interpretar a mensagem do banco, lista das notificacoes, lancar / ignorar, "Lancar todos",
# colar mensagem, chave curta e o extrato que pula o que ja veio pela notificacao; na tela: a extensao e os textos.
# Cada um e um defeito plausivel de programacao. Os localizadores falham (AssertionError) se a estrutura nao for
# exatamente a esperada -- um mutante que nao acha o alvo e um ERRO-MUTANTE, nao "detectado".


# ---------------------------------------------------------------- 0) alvo refeito: carregarPreferencias ganhou o laco das chaves
def r105(root):
    # mesmo defeito do v1.7: o filtro do laco das repeticoes guardadas deixa passar tudo (o laco novo das chaves
    # das notificacoes, sobre a local 'cn', fica de fora)
    fe = [b for b in blocos(procr(root, 'carregarPreferencias'), 'controls_forEach')
          if not (filho(b, 'LIST') is not None and filho(b, 'LIST').get('type') == 'lexical_variable_get'
                  and field(filho(b, 'LIST'), 'VAR').text == 'cn')]
    assert len(fe) == 1, len(fe)
    se = [b for b in fe[0].iter(NS + 'block') if b.get('type') == 'controls_if']
    replace_value(val(se[0], 'IF0'), dsl(G.boolean(True)))


_refazer(MUTANTES, 'v1.7 repeticoes estranhas no armazenamento nao sao filtradas',
         'v1.7 repeticoes estranhas no armazenamento nao sao filtradas', ['T39'], r105)


def _decl_valor(p, var):
    """<value> com o valor inicial da variavel local `var` (local_declaration_*)."""
    achados = []
    for b in p.iter(NS + 'block'):
        if b.get('type') in ('local_declaration_expression', 'local_declaration_statement'):
            for f in b:
                if tg(f) == 'field' and (f.get('name') or '').startswith('VAR') and f.text == var:
                    achados.append(val(b, 'DECL' + f.get('name')[3:]))
    return so1(achados)


def _foreach_de(p, glob_nome):
    """'para cada item em <global glob_nome>' dentro de p."""
    return so1([b for b in blocos(p, 'controls_forEach') if filho(b, 'LIST') is not None
                and filho(b, 'LIST').get('type') == 'lexical_variable_get' and field(filho(b, 'LIST'), 'VAR').text == glob_nome])


def _set_local(p, var, pred=lambda b: True):
    return [b for b in blocos(p, 'lexical_variable_set') if field(b, 'VAR').text == var and pred(b)]


def _metodo(p, inst, metodo):
    return [b for b in blocos(p, 'component_method') if mt(b).get('instance_name') == inst and mt(b).get('method_name') == metodo]


def _trocar_bloco(root, velho, novo):
    pm = parent_map(root)
    replace_value(pm[velho], dsl(novo))


def _tem(b, tipo, pred=lambda x: True):
    return any(x.get('type') == tipo and pred(x) for x in b.iter(NS + 'block'))


# ---------------------------------------------------------------- 1) interpretar a mensagem do banco
@mutante('v2.0 valor: nao pula o espaco depois do R$ ("R$ 45,90" fica sem valor)', ['T59', 'T60'])
def n201(root):
    field(so1(textos(defret(root, 'interpretarMensagem'), ' -+')), 'TEXT').text = '-+'


@mutante('v2.0 estorno nao reconhecido (procura as palavras de despesa no lugar)', ['T59'])
def n202(root):
    field(so1(gets(defret(root, 'interpretarMensagem'), 'global palavrasEstorno')), 'VAR').text = 'global palavrasDespesa'


@mutante('v2.0 sem pista no texto: vira ENTRADA (deveria ser despesa, a pessoa confere)', ['T59'])
def n203(root):
    v = _decl_valor(defret(root, 'interpretarMensagem'), 'tipo')
    assert v[0].get('type') == 'text' and field(v[0], 'TEXT').text == 'Despesa'
    field(v[0], 'TEXT').text = 'Entrada'


@mutante('v2.0 nome sem limite de tamanho (40 -> 400 letras)', ['T59'])
def n204(root):
    p = defret(root, 'interpretarMensagem')
    ns = [b for b in blocos(p, 'math_number') if field(b, 'NUM').text == '40']
    assert len(ns) == 2, len(ns)
    for b in ns:
        field(b, 'NUM').text = '400'


@mutante('v2.0 "sua conta" / "seu cartao" aceitos como nome', ['T59'])
def n205(root):
    p = defret(root, 'interpretarMensagem')
    splice_out(root, _foreach_de(p, 'global naoNome'))


@mutante('v2.0 nome nao e cortado no fim ("POSTO SHELL para o cartao final 1234...")', ['T59', 'T60'])
def n206(root):
    p = defret(root, 'interpretarMensagem')
    splice_out(root, _foreach_de(p, 'global fimNome'))


@mutante('v2.0 ponto final fica no nome ("POSTO SHELL.")', ['T59', 'T60'])
def n207(root):
    p = defret(root, 'interpretarMensagem')
    w = so1([b for b in blocos(p, 'controls_while')
             if filho(b, 'TEST') is not None and _tem(filho(b, 'TEST'), 'text', lambda x: field(x, 'TEXT').text == '.,;:!-')])
    splice_out(root, w)


@mutante('v2.0 Pix sem "Pix de"/"Pix para" (so o nome da pessoa)', ['T59', 'T60'])
def n208(root):
    field(so1(textos(defret(root, 'interpretarMensagem'), 'Pix ')), 'TEXT').text = ''


@mutante('v2.0 sinal de menos depois do R$ nao e pulado ("R$ -30,00" fica sem valor)', ['T59'])
def n209(root):
    # (o mutante planejado antes -- tirar o "valor absoluto" -- era EQUIVALENTE: o sinal ja e pulado antes de ler o
    #  numero, entao o valor nunca chega negativo; a rodada mostrou isso e ele foi trocado por este)
    field(so1(textos(defret(root, 'interpretarMensagem'), ' -+')), 'TEXT').text = ' +'


@mutante('v2.0 valor zero aceito ("R$ 0,00" vira lancamento)', ['T59'])
def n210(root):
    p = defret(root, 'interpretarMensagem')
    neg = so1([b for b in blocos(p, 'logic_negate') if _tem(b, 'lexical_variable_get', lambda x: field(x, 'VAR').text == 'v')])
    _trocar_bloco(root, neg, G.boolean(True))


# ---------------------------------------------------------------- 2) lista das notificacoes
@mutante('v2.0 lista com a mais ANTIGA primeiro', ['T60'])
def n211(root):
    p = proc(root, 'lerNotificacoes')
    ins = so1(blocos(p, 'lists_insert_item'))
    replace_value(val(ins, 'INDEX'), dsl(G.madd(G.llen(G.gget('notifItens')), G.num(1))))


@mutante('v2.0 nunca marca "ja existe um igual"', ['T60'])
def n212(root):
    field(so1(textos(proc(root, 'lerNotificacoes'), 'repetido')), 'TEXT').text = 'ok'


@mutante('v2.0 compra no cartao sugerida como outra forma de pagamento', ['T60'])
def n213(root):
    c_ = so1(call_of(proc(root, 'lerNotificacoes'), 'adivinharPagamento'))
    falso(val(c_, 'ARG1'))


@mutante('v2.0 data da notificacao no formato errado (mes/dia)', ['T60'])
def n214(root):
    ts = textos(proc(root, 'lerNotificacoes'), 'dd/MM/yyyy HH:mm')
    assert len(ts) == 3, len(ts)
    for t in ts:
        field(t, 'TEXT').text = 'MM/dd/yyyy HH:mm'


@mutante('v2.0 "Lançar os N" conta tambem as que nao foram entendidas', ['T60'])
def n215(root):
    field(so1(textos(proc(root, 'atualizarNotif'), 'ok')), 'TEXT').text = 'nao'


@mutante('v2.0 faixa no Lancar aparece mesmo sem notificacoes', ['T60'])
def n216(root):
    verdadeiro(val(so1(sets(proc(root, 'atualizarNotif'), 'HzAvisoNotif', 'Visible')), 'VALUE'))


@mutante('v2.0 acesso desligado mostrado em verde', ['T60'])
def n217(root):
    s_ = so1(sets(proc(root, 'atualizarNotif'), 'LblNotifStatus', 'TextColor'))
    field(so1(gets(s_, 'global corPerigo')), 'VAR').text = 'global corBom'


# ---------------------------------------------------------------- 3) lancar / ignorar
@mutante('v2.0 lancar das notificacoes nao grava no aparelho', ['T60'])
def n218(root):
    splice_out(root, so1(call_of(proc(root, 'lancarNotif'), 'gravarDados')))


@mutante('v2.0 falha ao gravar: nao desfaz (o lancamento fica so na memoria)', ['T60'])
def n219(root):
    splice_out(root, so1(_set_local(proc(root, 'lancarNotif'), 'global lancamentos')))


@mutante('v2.0 chaves das notificacoes nao sao guardadas (o extrato lanca de novo)', ['T60', 'T61'])
def n220(root):
    splice_out(root, so1(call_of(proc(root, 'lancarNotif'), 'guardarPref')))


@mutante('v2.0 lancada continua na lista', ['T60'])
def n221(root):
    splice_out(root, so1(call_of(proc(root, 'lancarNotif'), 'removerNotif')))


@mutante('v2.0 guarda so a ultima chave (limite 500 -> 1)', ['T60', 'T61'])
def n222(root):
    field(so1(nums_em(proc(root, 'lancarNotif'), 500)), 'NUM').text = '1'


@mutante('v2.0 tirar da lista nao apaga da extensao (volta ao atualizar)', ['T60'])
def n223(root):
    splice_out(root, so1(_metodo(proc(root, 'removerNotif'), 'LeitorNotificacoes1', 'Remover')))


@mutante('v2.0 "Ignorar" LANCA a notificacao', ['T60'])
def n224(root):
    e = evento(root, 'Notifier1', 'AfterChoosing')
    se = so1(ifs(e, lambda b: filho(b, 'IF0') is not None and _tem(filho(b, 'IF0'), 'text', lambda x: field(x, 'TEXT').text == 'Ignorar')))
    c_ = so1([x for x in cadeia(stmt(se, 'DO0')) if x.get('type') == 'procedures_callnoreturn'])
    assert field(c_, 'PROCNAME').text == 'removerNotif'
    field(c_, 'PROCNAME').text = 'lancarNotif'
    mt(c_).set('name', 'lancarNotif')


@mutante('v2.0 "Lançar mesmo assim" nao faz nada', ['T60'])
def n225(root):
    e = evento(root, 'Notifier1', 'AfterChoosing')
    field(so1(textos(e, 'Lançar mesmo assim')), 'TEXT').text = 'Lançar de novo'


@mutante('v2.0 "Lançar todos" lanca tambem as repetidas e as nao entendidas', ['T60'])
def n226(root):
    e = evento(root, 'Notifier1', 'AfterChoosing')
    se = so1(ifs(e, lambda b: filho(b, 'IF0') is not None and _tem(filho(b, 'IF0'), 'text', lambda x: field(x, 'TEXT').text == 'Lançar todos')))
    dentro = so1(ifs(se, lambda b: filho(b, 'IF0') is not None and _tem(filho(b, 'IF0'), 'text', lambda x: field(x, 'TEXT').text == 'ok')))
    verdadeiro(val(dentro, 'IF0'))


@mutante('v2.0 lista nao atualiza quando chega notificacao com o app aberto', ['T60'])
def n227(root):
    splice_out(root, so1(call_of(evento(root, 'LeitorNotificacoes1', 'NotificacaoRecebida'), 'lerNotificacoes')))


@mutante('v2.0 ao abrir o app nao le as notificacoes guardadas (sem aviso no Lancar)', ['T60'])
def n228(root):
    splice_out(root, so1(call_of(evento(root, 'Screen1', 'Initialize'), 'lerNotificacoes')))


@mutante('v2.0 troca de tema nao repinta o estado do acesso', ['T33'])
def n229(root):
    splice_out(root, so1(call_of(proc(root, 'pintarEstados'), 'atualizarNotif')))


@mutante('v2.0 chaves das notificacoes nao sao lidas ao abrir', ['T60', 'T61'])
def n230(root):
    field(so1(textos(proc(root, 'carregarPreferencias'), 'chaves_notif')), 'TEXT').text = 'chaves_notif2'


# ---------------------------------------------------------------- 4) colar mensagem
@mutante('v2.0 colar: categoria sugerida nao e escolhida', ['T60'])
def n231(root):
    splice_out(root, so1(_set_local(evento(root, 'BtnInterpretar', 'Click'), 'global categoriaSel')))


@mutante('v2.0 colar: sem valor nao avisa nada', ['T60'])
def n232(root):
    e = evento(root, 'BtnInterpretar', 'Click')
    s_ = so1([b for b in sets(e, 'LblErroColar', 'Visible')
              if filho(b, 'VALUE').get('type') == 'logic_boolean' and field(filho(b, 'VALUE'), 'BOOL').text == 'TRUE'])
    falso(val(s_, 'VALUE'))


@mutante('v2.0 colar: a mensagem continua no campo depois de preencher', ['T60'])
def n233(root):
    e = evento(root, 'BtnInterpretar', 'Click')
    splice_out(root, so1([b for b in sets(e, 'TxtColar', 'Text') if mt(b).get('set_or_get') == 'set']))


# ---------------------------------------------------------------- 5) chave curta e extrato
@mutante('v2.0 chave curta com a DESCRICAO no lugar do valor', ['T60', 'T61'])
def n234(root):
    p = defret(root, 'chaveCurta')
    sel = so1([b for b in blocos(p, 'lists_select_item') if filho(b, 'NUM') is not None and filho(b, 'NUM').get('type') == 'math_number'
               and field(filho(b, 'NUM'), 'NUM').text == '3'])
    field(filho(sel, 'NUM'), 'NUM').text = '2'


@mutante('v2.0 extrato: QUALQUER lancamento do mesmo dia/tipo/valor vira "ja veio da notificacao"', ['T61'])
def n235(root):
    p = proc(root, 'lerExtrato')
    se = so1(ifs(p, lambda b: filho(b, 'IF0') is not None and gets(filho(b, 'IF0'), 'global chavesNotif')))
    verdadeiro(val(se, 'IF0'))


@mutante('v2.0 extrato: ignora o que veio das notificacoes (duplica)', ['T61'])
def n236(root):
    p = proc(root, 'lerExtrato')
    se = so1(ifs(p, lambda b: filho(b, 'IF0') is not None and gets(filho(b, 'IF0'), 'global chavesNotif')))
    falso(val(se, 'IF0'))


@mutante('v2.0 extrato: uma notificacao "cobre" varias linhas iguais (nao e consumida)', ['T61'])
def n237(root):
    p = proc(root, 'lerExtrato')
    s_ = so1(_set_local(p, 'poolN', lambda b: _tem(filho(b, 'VALUE'), 'text_segment')))
    splice_out(root, s_)


# ---------------------------------------------------------------- 6) tela, extensao e textos
@tela('v2.0 componente LeitorNotificacoes1 apagado da tela', ['T25', 'T58', 'T60'])
def z201(d, pkg):
    def rec(n):
        n['$Components'] = [c for c in n.get('$Components', []) if c['$Name'] != 'LeitorNotificacoes1']
        for c in n['$Components']:
            rec(c)
    antes = len(scm_nodes(d))
    rec(d['Properties'])
    assert len(scm_nodes(d)) == antes - 1


@tela('v2.0 pacote sem o codigo Android da extensao (classes.jar)', ['T25', 'T58'])
def z202(d, pkg):
    f = os.path.join(pkg, 'assets', 'external_comps', 'com.conto.notificacoes', 'classes.jar')
    assert os.path.isfile(f)
    os.remove(f)


@tela('v2.0 extensao no pacote com "so com valor" desligado por padrao', ['T58'])
def z203(d, pkg):
    f = os.path.join(pkg, 'assets', 'external_comps', 'com.conto.notificacoes', 'components.json')
    t = open(f, encoding='utf-8').read()
    velho = '"defaultValue": "True",\n   "name": "ApenasComValor",'
    assert t.count(velho) == 1, 'ApenasComValor'
    open(f, 'w', encoding='utf-8').write(t.replace(velho, velho.replace('True', 'False')))


@tela('v2.0 dica do campo de colar volta para a cor fraca (contraste < 4,5:1)', ['T27'])
def z204(d, pkg):
    no = scm_nodes(d)['TxtColar']
    import tema as _T
    assert no['HintColor'] == _T.aia(_T.CORES['Suave'][0]), no['HintColor']
    no['HintColor'] = _T.aia(_T.CORES['Dica'][0])


@tela('v2.0 linha "Notificações do banco" com outro texto no perfil', ['T60'])
def z205(d, pkg):
    no = scm_nodes(d)['BtnNotificacoes']
    assert no['Text'] == 'Notificações do banco'
    no['Text'] = 'Lançamentos das notificações'


@mutante('v2.0 dica do campo de colar pintada com a cor fraca pelo tema (contraste < 4,5:1)', ['T27'])
def n241(root):
    # (o S64 muda so o valor do designer, que o tema sobrescreve ao abrir; este muda o que o tema pinta)
    achados = []
    for k in (1, 2, 3):
        p = proc(root, 'pintarTema%d' % k)
        achados += [b for b in blocos(p, 'component_set_get') if mt(b).get('instance_name') == 'TxtColar'
                    and mt(b).get('property_name') == 'HintColor' and mt(b).get('set_or_get') == 'set']
    s_ = so1(achados)
    field(so1(gets(s_, 'global corSuave')), 'VAR').text = 'global corDica'


# ---------------------------------------------------------------- 7) v2.0.1: leitor religado, nome de quem enviou, diagnostico
@mutante('v2.0.1 "Atualizar" nao religa o leitor', ['T62'])
def n251(root):
    e = evento(root, 'BtnNotifAtualizar', 'Click')
    splice_out(root, so1(_metodo(e, 'LeitorNotificacoes1', 'Reconectar')))


@mutante('v2.0.1 ao abrir o app o leitor nao e religado', ['T62'])
def n252(root):
    e = evento(root, 'Screen1', 'Initialize')
    splice_out(root, so1(_metodo(e, 'LeitorNotificacoes1', 'Reconectar')))


@mutante('v2.0.1 "Fulano enviou um Pix para voce": o nome de quem enviou e ignorado', ['T59', 'T62'])
def n253(root):
    p = defret(root, 'interpretarMensagem')
    se = so1(ifs(p, lambda b: filho(b, 'IF0') is not None and _tem(filho(b, 'IF0'), 'text', lambda x: field(x, 'TEXT').text == 'para voce')))
    splice_out(root, se)


@mutante('v2.0.1 nome de quem enviou pega o titulo junto ("Pix recebido. Ana Souza")', ['T59'])
def n254(root):
    p = defret(root, 'interpretarMensagem')
    s_ = so1(_set_local(p, 'nome', lambda b: _tem(filho(b, 'VALUE'), 'text_split')))
    splice_out(root, s_)


@mutante('v2.0.1 "visualizar o pagamento" volta a ser aceito como nome', ['T59'])
def n255(root):
    g = glob(root, 'naoNome')
    t = so1([b for b in g.iter(NS + 'block') if b.get('type') == 'text' and 'visualizar ' in (field(b, 'TEXT').text or '')])
    field(t, 'TEXT').text = field(t, 'TEXT').text.replace('visualizar |', '')


@mutante('v2.0.1 diagnostico aparece mesmo sem o acesso liberado', ['T62'])
def n256(root):
    verdadeiro(val(so1(sets(proc(root, 'atualizarNotif'), 'LblNotifDiag', 'Visible')), 'VALUE'))


@tela('v2.0.1 linha do diagnostico apagada da tela', ['T25', 'T62'])
def z251(d, pkg):
    def rec(n):
        n['$Components'] = [c for c in n.get('$Components', []) if c['$Name'] != 'LblNotifDiag']
        for c in n['$Components']:
            rec(c)
    antes = len(scm_nodes(d))
    rec(d['Properties'])
    assert len(scm_nodes(d)) == antes - 1
# <<< fim dos mutantes novos da v2.0


def run_tela(i, rotulo, esperado, fn, completo=False):
    dst = os.path.join(MUT, 's%02d' % i)
    shutil.rmtree(dst, ignore_errors=True)
    pkg = os.path.join(dst, 'pkg')
    shutil.copytree(SRC, pkg)
    scm = os.path.join(pkg, CONTO, 'Screen1.scm')
    t = open(scm, encoding='utf-8').read()
    d = json.loads(t[t.index('{'): t.rindex('}') + 1])
    fn(d, pkg)
    open(scm, 'w', encoding='utf-8', newline='').write('#|\n$JSON\n' + json.dumps(d, ensure_ascii=False, separators=(',', ':')) + '\n|#')
    aia = os.path.join(dst, 'mut.aia')
    with zipfile.ZipFile(AIA) as zin, zipfile.ZipFile(aia, 'w', zipfile.ZIP_DEFLATED) as zout:
        for n in zin.namelist():
            caminho = os.path.join(pkg, n)
            if os.path.exists(caminho):          # v1.8: um mutante pode APAGAR um arquivo do pacote
                zout.write(caminho, n)
    env = dict(os.environ)
    env.pop('ONLY', None)
    env.pop('SKIP', None)
    if completo:
        # (v1.8.1: o T54 tambem desenha previas -- uns 2 min -- e so entra quando o mutante mira ele)
        env.update({'SKIP': ','.join(['T07', 'T12', 'T13'] + [t for t in ('T27', 'T54', 'T57') if t not in esperado])})
    else:
        env.update({'ONLY': ','.join(esperado)})
    env.update({'FUZZ_RANDOM': '1500', 'REPORT': os.path.join(dst, 'rel.txt'),
                'WORK_DIR': os.path.join(dst, 'work'), 'PREVIEW_DIR': os.path.join(dst, 'prev'), 'SP': SP})
    env.pop('NEW_DIR', None)
    r = subprocess.run([sys.executable, '-W', 'ignore', '-I', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_conto.py'), aia],
                       capture_output=True, text=True, env=env, timeout=TEMPO_MAX)
    falhos = re.findall(r'^\[FALHOU\] (T\d+)', r.stdout, re.M)
    return falhos, r

def run_mutant(i, rotulo, esperado, fn, completo=False):
    dst = os.path.join(MUT, 'm%02d' % i)
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(os.path.join(SRC, 'src'), os.path.join(dst, 'src'))
    bky = os.path.join(dst, CONTO, 'Screen1.bky')
    tree = ET.parse(bky)
    fn(tree.getroot())
    tree.write(bky, encoding='utf-8')
    env = dict(os.environ)
    env.pop('ONLY', None)
    env.pop('SKIP', None)
    if completo:      # confirmacao: bateria completa (menos as previas, que nao leem blocos: T27, T54 e T57)
        # (v2.0: o T57 mede a altura das abas nas previas do T27; sem elas ele falhava SEMPRE, por fora do mutante)
        env.update({'SKIP': 'T27,T54,T57'})
    else:             # 1a passada: so os testes que o mutante mira
        env.update({'ONLY': ','.join(esperado)})
    env.update({'NEW_DIR': os.path.join(dst, CONTO), 'FUZZ_RANDOM': '1500',
                'REPORT': os.path.join(dst, 'rel.txt'), 'WORK_DIR': os.path.join(dst, 'work'), 'SP': SP})
    r = subprocess.run([sys.executable, '-W', 'ignore', '-I', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_conto.py'), AIA],
                       capture_output=True, text=True, env=env, timeout=TEMPO_MAX)
    falhos = re.findall(r'^\[FALHOU\] (T\d+)', r.stdout, re.M)
    return falhos, r


# uma bateria (mesmo a completa) leva menos de 5 min; mais que isso = o app ou o teste travou (laco sem fim)
TEMPO_MAX = int(os.environ.get('TEMPO_MAX', '900'))


def um(tarefa):
    """Roda um mutante (bloco ou tela) e devolve a linha de resultado."""
    tipo, i, rotulo, esperado, fn = tarefa
    nome = '%s%02d' % (tipo, i)
    try:
        falhos, r = (run_mutant if tipo == 'M' else run_tela)(i, rotulo, esperado, fn)
        if not falhos and r.returncode == 0:
            # sobreviveu com a bateria reduzida: confirma com a bateria COMPLETA antes de dizer que sobreviveu
            falhos, r = (run_mutant if tipo == 'M' else run_tela)(i, rotulo, esperado, fn, completo=True)
    except subprocess.TimeoutExpired:           # travou: NAO conta como detectado (precisa ser investigado)
        return nome, 'TRAVOU', rotulo, []
    except Exception as e:                      # defeito no proprio script de mutacao
        return nome, 'ERRO-MUTANTE', '%s: %r' % (rotulo, e), []
    if falhos:
        return nome, 'detectado', rotulo, falhos
    if r.returncode != 0:                       # a bateria quebrou sem apontar teste -> nao conta como detectado
        return nome, 'ERRO-EXECUCAO', rotulo + ' :: ' + (r.stderr or r.stdout)[-300:], []
    return nome, 'SOBREVIVEU!', rotulo, []


def main():
    from concurrent.futures import ThreadPoolExecutor
    shutil.rmtree(SRC, ignore_errors=True)
    with zipfile.ZipFile(AIA) as z:
        z.extractall(SRC)
    os.makedirs(MUT, exist_ok=True)
    tarefas = [('M', i, r_, e_, f_) for i, (r_, e_, f_) in enumerate(MUTANTES, 1)] + \
              [('S', i, r_, e_, f_) for i, (r_, e_, f_) in enumerate(TELA, 1)]
    if os.environ.get('MUTANTES_SO'):                      # reexecucao so de alguns (ex.: MUTANTES_SO=M33,M50)
        so = set(os.environ['MUTANTES_SO'].split(','))
        tarefas = [t for t in tarefas if '%s%02d' % (t[0], t[1]) in so]
    linhas = []
    with ThreadPoolExecutor(max_workers=int(os.environ.get('JOBS', '2'))) as ex:
        for nome, estado, rotulo, falhos in ex.map(um, tarefas):
            linhas.append('%s  %-13s %s  -> falharam: %s' % (nome, estado, rotulo, ','.join(falhos) or '(nenhum)'))
            print(linhas[-1], flush=True)
    boas = sum(1 for l in linhas if ' detectado ' in l)
    print()
    print('mutantes detectados pela bateria: %d/%d  (blocos: %d, tela/imagens: %d)' % (boas, len(linhas), len(MUTANTES), len(TELA)))
    open(os.path.join(MUT, 'resumo.txt'), 'w', encoding='utf-8').write('\n'.join(linhas) + '\n')
    sys.exit(0 if boas == len(linhas) else 1)


if __name__ == '__main__':
    main()
