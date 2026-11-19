#!/usr/bin/env python3
"""
Gera o projeto do Contô v2.0.1 (Screen1.bky + Screen1.scm + assets + project.properties + .aia).
O arquivo reune, em secoes, os blocos de cada versao (v1.6 em diante); as secoes mais novas substituem
os procedimentos que mudaram.

Uso:  python3 gen_conto.py <pasta_original_extraida> <pasta_saida_projeto> <arquivo.aia_saida> <pasta_assets>

Os blocos sao montados por uma pequena DSL (funcoes que devolvem elementos XML do Blockly),
nos mesmos formatos que o App Inventor grava (conferidos contra appinventor-sources).
Blocos que NAO mudaram (navegacao entre abas e AfterPicking do historico) sao copiados do original.
"""
import copy
import os
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET

import tema as T
import gen_scm

# =========================================================================== DSL
def M(**attrs):
    return ET.Element('mutation', {k: str(v) for k, v in attrs.items()})


def B(btype, fields=(), values=(), stmts=(), mut=None):
    el = ET.Element('block', {'type': btype})
    if mut is not None:
        el.append(mut)
    for n, v in fields:
        f = ET.SubElement(el, 'field', {'name': n})
        if v != '':
            f.text = v
    for n, c in values:
        v = ET.SubElement(el, 'value', {'name': n})
        v.append(c)
    for n, c in stmts:
        if c is not None:
            s = ET.SubElement(el, 'statement', {'name': n})
            s.append(c)
    return el


def seq(*items):
    flat = []
    for it in items:
        if it is None:
            continue
        if isinstance(it, (list, tuple)):
            flat.extend(x for x in it if x is not None)
        else:
            flat.append(it)
    for a, b in zip(flat, flat[1:]):
        nx = ET.SubElement(a, 'next')
        nx.append(b)
    return flat[0] if flat else None


# ---- literais e variaveis
def num(n):
    return B('math_number', fields=[('NUM', str(n))])


def txt(s):
    return B('text', fields=[('TEXT', s)])


def boolean(v):
    return B('logic_boolean', fields=[('BOOL', 'TRUE' if v else 'FALSE')])


def gget(name):
    return B('lexical_variable_get', fields=[('VAR', 'global ' + name)])


def lget(name):
    return B('lexical_variable_get', fields=[('VAR', name)])


def evparam(name):
    mut = ET.Element('mutation')
    ET.SubElement(mut, 'eventparam', {'name': name})
    return B('lexical_variable_get', fields=[('VAR', name)], mut=mut)


def gset(name, val):
    return B('lexical_variable_set', fields=[('VAR', 'global ' + name)], values=[('VALUE', val)])


def lset(name, val):
    return B('lexical_variable_set', fields=[('VAR', name)], values=[('VALUE', val)])


def mklist(*xs):
    return B('lists_create_with', mut=M(items=len(xs)), values=[('ADD%d' % i, x) for i, x in enumerate(xs)])


# ---- texto
def join(*xs):
    return B('text_join', mut=M(items=len(xs)), values=[('ADD%d' % i, x) for i, x in enumerate(xs)])


def tlen(x):
    return B('text_length', values=[('VALUE', x)])


def tempty(x):
    return B('text_isEmpty', values=[('VALUE', x)])


def ttrim(x):
    return B('text_trim', values=[('TEXT', x)])


def tcontains(text, piece):
    return B('text_contains', mut=M(mode='CONTAINS'), fields=[('OP', 'CONTAINS')],
             values=[('TEXT', text), ('PIECE', piece)])


def segment(t, start, length):
    return B('text_segment', values=[('TEXT', t), ('START', start), ('LENGTH', length)])


# ---- matematica e logica
def madd(*xs):
    return B('math_add', mut=M(items=len(xs)), values=[('NUM%d' % i, x) for i, x in enumerate(xs)])


def mmul(*xs):
    return B('math_multiply', mut=M(items=len(xs)), values=[('NUM%d' % i, x) for i, x in enumerate(xs)])


def msub(a, b):
    return B('math_subtract', values=[('A', a), ('B', b)])


def mdiv(a, b):
    return B('math_division', values=[('A', a), ('B', b)])


def _divop(op, a, b):
    return B('math_divide', fields=[('OP', op)], values=[('DIVIDEND', a), ('DIVISOR', b)])


def modulo(a, b):
    return _divop('MODULO', a, b)


def remainder(a, b):
    return _divop('REMAINDER', a, b)


def quotient(a, b):
    return _divop('QUOTIENT', a, b)


def mabs(x):
    return B('math_abs', fields=[('OP', 'ABS')], values=[('NUM', x)])


def mround(x):
    return B('math_round', fields=[('OP', 'ROUND')], values=[('NUM', x)])


def isnum(x):
    return B('math_is_a_number', fields=[('OP', 'NUMBER')], values=[('NUM', x)])


def cmp(op, a, b):
    return B('math_compare', fields=[('OP', op)], values=[('A', a), ('B', b)])


def eq(a, b):
    return B('logic_compare', fields=[('OP', 'EQ')], values=[('A', a), ('B', b)])


def AND(a, b):
    return B('logic_operation', mut=M(items=2), fields=[('OP', 'AND')], values=[('A', a), ('B', b)])


def OR(a, b):
    return B('logic_operation', mut=M(items=2), fields=[('OP', 'OR')], values=[('A', a), ('B', b)])


def NOT(x):
    return B('logic_negate', values=[('BOOL', x)])


# ---- listas
def litem(lst, i):
    return B('lists_select_item', values=[('LIST', lst), ('NUM', num(i) if isinstance(i, int) else i)])


def llen(lst):
    return B('lists_length', values=[('LIST', lst)])


def lis(x):
    return B('lists_is_list', values=[('ITEM', x)])


def ladd(lst, item):
    return B('lists_add_items', mut=M(items=1), values=[('LIST', lst), ('ITEM0', item)])


def linsert(lst, idx, item):
    return B('lists_insert_item', values=[('LIST', lst), ('INDEX', idx), ('ITEM', item)])


def lremove(lst, idx):
    return B('lists_remove_item', values=[('LIST', lst), ('INDEX', idx)])


# ---- controle
def IF(cond, then, els=None):
    mut = M(**{'else': 1}) if els is not None else None
    stmts = [('DO0', seq(then))]
    if els is not None:
        stmts.append(('ELSE', seq(els)))
    return B('controls_if', mut=mut, values=[('IF0', cond)], stmts=stmts)


def IFELIF(branches, els=None):
    attrs = {}
    if len(branches) > 1:
        attrs['elseif'] = len(branches) - 1
    if els is not None:
        attrs['else'] = 1
    values, stmts = [], []
    for i, (cond, body) in enumerate(branches):
        values.append(('IF%d' % i, cond))
        stmts.append(('DO%d' % i, seq(body)))
    if els is not None:
        stmts.append(('ELSE', seq(els)))
    return B('controls_if', mut=M(**attrs) if attrs else None, values=values, stmts=stmts)


def FOR(var, start, end, step, body):
    return B('controls_forRange', fields=[('VAR', var)],
             values=[('START', start), ('END', end), ('STEP', step)], stmts=[('DO', seq(body))])


def FOREACH(var, lst, body):
    return B('controls_forEach', fields=[('VAR', var)], values=[('LIST', lst)], stmts=[('DO', seq(body))])


def CHOOSE(test, a, b):
    return B('controls_choose', values=[('TEST', test), ('THENRETURN', a), ('ELSERETURN', b)])


def DO_RETURN(stmts, value):
    return B('controls_do_then_return', values=[('VALUE', value)], stmts=[('STM', seq(stmts))])


def _local_mut(names):
    mut = ET.Element('mutation')
    for n in names:
        ET.SubElement(mut, 'localname', {'name': n})
    return mut


def LOCALS_EXPR(decls, body):
    names = [n for n, _ in decls]
    return B('local_declaration_expression', mut=_local_mut(names),
             fields=[('VAR%d' % i, n) for i, n in enumerate(names)],
             values=[('DECL%d' % i, v) for i, (_, v) in enumerate(decls)] + [('RETURN', body)])


def LOCALS_STMT(decls, body):
    names = [n for n, _ in decls]
    return B('local_declaration_statement', mut=_local_mut(names),
             fields=[('VAR%d' % i, n) for i, n in enumerate(names)],
             values=[('DECL%d' % i, v) for i, (_, v) in enumerate(decls)],
             stmts=[('STACK', seq(body))])


# ---- componentes
def cget(inst, ctype, prop):
    return B('component_set_get', fields=[('COMPONENT_SELECTOR', inst), ('PROP', prop)],
             mut=M(component_type=ctype, set_or_get='get', property_name=prop, is_generic='false', instance_name=inst))


def cset(inst, ctype, prop, val):
    return B('component_set_get', fields=[('COMPONENT_SELECTOR', inst), ('PROP', prop)],
             values=[('VALUE', val)],
             mut=M(component_type=ctype, set_or_get='set', property_name=prop, is_generic='false', instance_name=inst))


def cmeth(inst, ctype, meth, *args):
    return B('component_method', fields=[('COMPONENT_SELECTOR', inst)],
             values=[('ARG%d' % i, a) for i, a in enumerate(args)],
             mut=M(component_type=ctype, method_name=meth, is_generic='false', instance_name=inst))


def cevent(inst, ctype, event, body):
    return B('component_event', fields=[('COMPONENT_SELECTOR', inst)], stmts=[('DO', seq(body))],
             mut=M(component_type=ctype, is_generic='false', instance_name=inst, event_name=event))


def alert(msg):
    return cmeth('Notifier1', 'Notifier', 'ShowAlert', msg)


def dialog_erro(msg):
    return cmeth('Notifier1', 'Notifier', 'ShowMessageDialog', msg, txt('Contô'), txt('OK'))


# ---- procedimentos
SIG = {}


def _proc_mut(params, name=None):
    attrs = {'name': name} if name else {}
    mut = ET.Element('mutation', attrs)
    for p in params:
        ET.SubElement(mut, 'arg', {'name': p})
    return mut


def defnoreturn(name, params, body):
    SIG[name] = params
    return B('procedures_defnoreturn', mut=_proc_mut(params),
             fields=[('NAME', name)] + [('VAR%d' % i, p) for i, p in enumerate(params)],
             stmts=[('STACK', seq(body))])


def defreturn(name, params, ret):
    SIG[name] = params
    return B('procedures_defreturn', mut=_proc_mut(params),
             fields=[('NAME', name)] + [('VAR%d' % i, p) for i, p in enumerate(params)],
             values=[('RETURN', ret)])


def call_stmt(name, *args):
    assert len(args) == len(SIG[name]), name
    return B('procedures_callnoreturn', mut=_proc_mut(SIG[name], name), fields=[('PROCNAME', name)],
             values=[('ARG%d' % i, a) for i, a in enumerate(args)])


def call_expr(name, *args):
    assert len(args) == len(SIG[name]), name
    return B('procedures_callreturn', mut=_proc_mut(SIG[name], name), fields=[('PROCNAME', name)],
             values=[('ARG%d' % i, a) for i, a in enumerate(args)])


def gdecl(name, val):
    return B('global_declaration', fields=[('NAME', name)], values=[('VALUE', val)])


# =========================================================================== PROGRAMA
# Assinaturas (precisam existir antes de montar as chamadas)
SIG.update({
    'formatarMoeda': ['valor'],
    'paraCentavos': ['texto'],
    'mostrarAba': ['aba'],
    'gravarDados': [],
    'carregarDados': [],
    'atualizarTudo': [],
    'atualizarHistorico': [],
    'atualizarGrafico': [],
    'formatarPercentual': ['p10'],
    'registrar': ['tipo'],
    'abrirPicker': ['tipo'],
    'fecharPicker': [],
    'atualizarCampos': [],
    'limparErros': [],
    'mostrarAviso': ['ok', 'msg'],
    'abreviar': ['texto'],
    'atualizarResumo': [],
    # v1.6
    'definirTema': [],
    'aplicarTema': [],
    'pintarTema1': [], 'pintarTema2': [], 'pintarTema3': [],
    'pintarAbas': [],
    'pintarEstados': [],
    'trocarTema': ['escuro'],
    'guardarPref': ['chave', 'valor'],
    'carregarPreferencias': [],
    'indiceCategoria': ['nome'],
    'larguraBarra': ['valor', 'maior'],
    'atualizarCategorias': [],
    'primeiroNome': ['texto'],
    'mostrarPerfil': [],
    'abrirPerfil': [],
    'mostrarMsgPerfil': ['ok', 'msg'],
})


REG = 'lancamentos'      # nome do global com a lista de lancamentos

COR_ENTRADA = T.hexrgb(T.GREEN)
COR_DESPESA = T.hexrgb(T.RED)
COR_ABA_ATIVA = (255, 255, 255)


def gcor(nome):
    """Cor do tema atual (global 'cor<Nome>', definida por definirTema)."""
    assert nome in T.CORES, nome
    return gget('cor' + nome)


def gimg(nome):
    """Nome do arquivo de imagem do tema atual (global 'img<Nome>')."""
    assert nome in T.IMAGENS, nome
    return gget('img' + nome)


def get_db(chave_global, default):
    return cmeth('TinyDB1', 'TinyDB', 'GetValue', gget(chave_global), default)


def p_formatarMoeda():
    """Centavos (inteiro) -> 'R$ 1.234,56'. Sem format-as-decimal, sem regex, sem locale."""
    def absv():
        return mabs(lget('valor'))
    corpo = LOCALS_EXPR(
        [('digitos', txt('')), ('acumulado', txt(''))],
        DO_RETURN(
            [
                lset('digitos', join(txt(''), quotient(absv(), num(100)))),
                FOR('i', num(1), tlen(lget('digitos')), num(1), [
                    IF(AND(cmp('GT', lget('i'), num(1)),
                           cmp('EQ', modulo(madd(msub(tlen(lget('digitos')), lget('i')), num(1)), num(3)), num(0))),
                       [lset('acumulado', join(lget('acumulado'), txt('.')))]),
                    lset('acumulado', join(lget('acumulado'), segment(lget('digitos'), lget('i'), num(1)))),
                ]),
            ],
            join(CHOOSE(cmp('LT', lget('valor'), num(0)), txt('-R$ '), txt('R$ ')),
                 lget('acumulado'),
                 txt(','),
                 CHOOSE(cmp('LT', remainder(absv(), num(100)), num(10)), txt('0'), txt('')),
                 remainder(absv(), num(100)))))
    return defreturn('formatarMoeda', ['valor'], corpo)


def p_paraCentavos():
    """Texto digitado no padrao brasileiro -> centavos (inteiro exato) ou -1 se invalido."""
    L = lget

    def invalido():
        return lset('valido', boolean(False))

    laco = LOCALS_STMT(
        [('c', segment(L('t'), L('i'), num(1)))],
        IFELIF(
            [
                (tcontains(txt('0123456789'), L('c')),
                 IF(L('virgula'),
                    [lset('decimais', join(L('decimais'), L('c')))],
                    [lset('inteiro', join(L('inteiro'), L('c'))),
                     lset('grupo', madd(L('grupo'), num(1)))])),
                (eq(L('c'), txt(',')),
                 IF(L('virgula'),
                    [invalido()],
                    [lset('virgula', boolean(True)),
                     IF(AND(cmp('GT', L('pontos'), num(0)), cmp('NEQ', L('grupo'), num(3))), [invalido()])])),
                (eq(L('c'), txt('.')),
                 IF(L('virgula'),
                    [invalido()],
                    [IF(cmp('EQ', L('pontos'), num(0)),
                        [lset('primeiro', L('grupo'))],
                        [IF(cmp('NEQ', L('grupo'), num(3)), [invalido()])]),
                     lset('pontos', madd(L('pontos'), num(1))),
                     lset('grupo', num(0))])),
            ],
            els=[invalido()]))

    pos = [
        # separadores de milhar / ponto decimal
        IF(AND(L('valido'), cmp('GT', L('pontos'), num(0))), [
            IF(L('virgula'),
               [IF(OR(cmp('LT', L('primeiro'), num(1)), cmp('GT', L('primeiro'), num(3))), [invalido()])],
               [IF(AND(AND(cmp('EQ', L('pontos'), num(1)), cmp('GTE', L('grupo'), num(1))),
                       cmp('LTE', L('grupo'), num(2))),
                   # "25.90": ponto com 1-2 digitos depois = ponto decimal
                   [lset('decimais', segment(L('inteiro'), madd(msub(tlen(L('inteiro')), L('grupo')), num(1)), L('grupo'))),
                    lset('inteiro', segment(L('inteiro'), num(1), msub(tlen(L('inteiro')), L('grupo'))))],
                   # "1.250" / "12.345.678": pontos sao milhares
                   [IF(OR(OR(cmp('NEQ', L('grupo'), num(3)), cmp('LT', L('primeiro'), num(1))),
                          cmp('GT', L('primeiro'), num(3))),
                       [invalido()])])]),
        ]),
        # tamanho maximo e vazio
        IF(AND(L('valido'),
               OR(OR(cmp('GT', tlen(L('inteiro')), num(9)), cmp('GT', tlen(L('decimais')), num(2))),
                  AND(tempty(L('inteiro')), tempty(L('decimais'))))),
           [invalido()]),
    ]

    valor = CHOOSE(
        L('valido'),
        madd(mmul(CHOOSE(tempty(L('inteiro')), num(0), L('inteiro')), num(100)),
             segment(join(L('decimais'), txt('00')), num(1), num(2))),
        num(-1))

    corpo = LOCALS_EXPR(
        [('t', ttrim(lget('texto'))), ('inteiro', txt('')), ('decimais', txt('')),
         ('virgula', boolean(False)), ('pontos', num(0)), ('grupo', num(0)),
         ('primeiro', num(0)), ('valido', boolean(True))],
        DO_RETURN([FOR('i', num(1), tlen(L('t')), num(1), [laco])] + pos, valor))
    return defreturn('paraCentavos', ['texto'], corpo)


def rgb(r, g, b):
    return B('color_make_color', values=[('COLORLIST', mklist(num(r), num(g), num(b)))])


def _pilula(inst, ligado):
    """Botao em pilula: imagem esmeralda + texto branco quando ligado; transparente + texto suave quando nao."""
    return [cset(inst, 'Button', 'Image', CHOOSE(ligado(), txt(T.IMG_ABA_ON), txt(T.IMG_ABA_OFF))),
            cset(inst, 'Button', 'TextColor', CHOOSE(ligado(), rgb(*COR_ABA_ATIVA), gcor('Suave')))]


def p_formatarPercentual():
    """Decimos de por cento (inteiro, ex.: 257) -> '25,7%'. So aritmetica de inteiros."""
    return defreturn('formatarPercentual', ['p10'],
                     join(quotient(lget('p10'), num(10)), txt(','), remainder(lget('p10'), num(10)), txt('%')))


def rgbh(h):
    return rgb(*T.hexrgb(h))


def p_limparErros():
    return defnoreturn('limparErros', [], [
        cset('LblErroValor', 'Label', 'Visible', boolean(False)),
        cset('LblErroCat', 'Label', 'Visible', boolean(False)),
        cset('LblErroPag', 'Label', 'Visible', boolean(False)),
        cset('HzCampoValor', 'HorizontalArrangement', 'Image', gimg('Campo')),
        cset('HzCampoCat', 'HorizontalArrangement', 'Image', gimg('CampoSel')),
        cset('HzCampoPag', 'HorizontalArrangement', 'Image', gimg('CampoSel')),
        cset('BoxAviso', 'VerticalArrangement', 'Visible', boolean(False)),
        cset('ClockAviso', 'Clock', 'TimerEnabled', boolean(False)),
    ])


def p_atualizarCampos():
    def par(sel, icone, btn, img, vazio):
        return [
            cset(btn, 'Button', 'Text', CHOOSE(tempty(gget(sel)), txt(vazio), gget(sel))),
            cset(btn, 'Button', 'TextColor', CHOOSE(tempty(gget(sel)), gcor('Dica'), gcor('Texto'))),
            cset(img, 'Image', 'Picture', CHOOSE(tempty(gget(icone)), gimg('Vazio'), gget(icone))),
        ]
    return defnoreturn('atualizarCampos', [],
                       par('categoriaSel', 'categoriaIcone', 'BtnCategoria', 'ImgCatIcone', 'Selecione uma categoria')
                       + par('pagamentoSel', 'pagamentoIcone', 'BtnPagamento', 'ImgPagIcone', 'Selecione uma forma'))


def p_fecharPicker():
    return defnoreturn('fecharPicker', [], [
        cset('PnlPicker', 'VerticalArrangement', 'Visible', boolean(False)),
        cset('PnlLancar', 'VerticalArrangement', 'Visible', boolean(True)),
    ])


def p_abreviar():
    t = lambda: lget('texto')
    return defreturn('abreviar', ['texto'],
                     CHOOSE(cmp('GT', tlen(t()), num(18)), join(segment(t(), num(1), num(17)), txt('\u2026')), t()))


def e_picker():
    idx = lambda: cget('ListaOpcoes', 'ListView', 'SelectionIndex')
    return cevent('ListaOpcoes', 'ListView', 'AfterPicking', [
        IF(eq(gget('pickerTipo'), txt('cat')),
           [gset('categoriaSel', litem(gget('listaCats'), idx())),
            gset('categoriaIcone', litem(gget('listaCatIcones'), idx())),
            cset('LblErroCat', 'Label', 'Visible', boolean(False)),
            cset('HzCampoCat', 'HorizontalArrangement', 'Image', gimg('CampoSel'))],
           [gset('pagamentoSel', litem(gget('listaPags'), idx())),
            gset('pagamentoIcone', litem(gget('listaPagIcones'), idx())),
            cset('LblErroPag', 'Label', 'Visible', boolean(False)),
            cset('HzCampoPag', 'HorizontalArrangement', 'Image', gimg('CampoSel'))]),
        call_stmt('fecharPicker'),
        call_stmt('atualizarCampos'),
    ])


def e_abre(inst, ctype, tipo):
    return cevent(inst, ctype, 'Click', [call_stmt('abrirPicker', txt(tipo))])


def e_voltar():
    return cevent('BtnPickerVoltar', 'Button', 'Click', [call_stmt('fecharPicker')])


def e_verHist():
    return cevent('BtnVerHist', 'Button', 'Click', [call_stmt('mostrarAba', num(2))])


def e_valorMudou():
    return cevent('TxtValor', 'TextBox', 'TextChanged', [
        cset('LblErroValor', 'Label', 'Visible', boolean(False)),
        cset('HzCampoValor', 'HorizontalArrangement', 'Image', gimg('Campo')),
    ])


def e_timerAviso():
    return cevent('ClockAviso', 'Clock', 'Timer', [
        cset('ClockAviso', 'Clock', 'TimerEnabled', boolean(False)),
        cset('BoxAviso', 'VerticalArrangement', 'Visible', boolean(False)),
    ])


def e_btn(inst, tipo):
    return cevent(inst, 'Button', 'Click', [call_stmt('registrar', txt(tipo))])


def e_btnLimpar():
    return cevent('BtnLimpar', 'Button', 'Click', [
        cmeth('Notifier1', 'Notifier', 'ShowChooseDialog', txt('Apagar todos os lançamentos?'), txt('Contô'),
              txt('Apagar tudo'), txt('Cancelar'), boolean(False)),
    ])


# =========================================================================== v1.6: tema claro / escuro
def p_definirTema():
    """Escolhe a paleta: cada global 'cor<Nome>' / 'img<Nome>' recebe o valor do tema claro ou do escuro."""
    def ramo(k):   # 0 = claro, 1 = escuro
        return [gset('cor' + n, rgbh(T.CORES[n][k])) for n in T.CORES] + \
               [gset('img' + n, txt(T.IMAGENS[n][k])) for n in T.IMAGENS]
    return defnoreturn('definirTema', [], [IF(gget('temaEscuro'), ramo(1), ramo(0))])


def setters_tema():
    """Um 'set' por propriedade registrada com ficha no gen_scm (TEMA_REG), usando o global do tema atual."""
    gen_scm.arvore()
    return [cset(nome, tipo, prop, gget(('cor' if ficha.tipo == 'cor' else 'img') + ficha.nome))
            for nome, tipo, prop, ficha in gen_scm.TEMA_REG]


def p_pintarTemas():
    """Os 'set' sao repartidos em tres procedimentos so para as pilhas de blocos nao ficarem enormes no editor."""
    st = setters_tema()
    n = (len(st) + 2) // 3
    return [defnoreturn('pintarTema%d' % (k + 1), [], st[k * n:(k + 1) * n]) for k in range(3)]


def p_aplicarTema():
    return defnoreturn('aplicarTema', [], [
        call_stmt('definirTema'),
        call_stmt('pintarTema1'),
        call_stmt('pintarTema2'),
        call_stmt('pintarTema3'),
        call_stmt('pintarEstados'),
    ])


def p_guardarPref():
    """Guarda uma preferencia (tema, nome, foto) e CONFERE lendo de volta: prefOk = o que voltou e o que foi guardado."""
    return defnoreturn('guardarPref', ['chave', 'valor'], [
        cmeth('TinyDB1', 'TinyDB', 'StoreValue', lget('chave'), lget('valor')),
        gset('prefOk', eq(cmeth('TinyDB1', 'TinyDB', 'GetValue', lget('chave'), txt('')), lget('valor'))),
    ])


def erro_pref(msg):
    return IF(NOT(gget('prefOk')), [dialog_erro(txt(msg))])


def p_trocarTema():
    return defnoreturn('trocarTema', ['escuro'], [
        IF(NOT(eq(lget('escuro'), gget('temaEscuro'))), [
            gset('temaEscuro', lget('escuro')),
            call_stmt('aplicarTema'),
            call_stmt('guardarPref', txt('tema'), CHOOSE(lget('escuro'), txt('escuro'), txt('claro'))),
            erro_pref('Erro: não foi possível guardar o tema escolhido neste aparelho.'),
        ]),
    ])


# =========================================================================== v1.6: gastos por categoria
N_CAT = len(T.CATEGORIAS)


def p_indiceCategoria():
    """Posicao da categoria na lista (1..8). Categoria desconhecida (dado antigo) conta como a ultima, 'Outros'."""
    return defreturn('indiceCategoria', ['nome'], LOCALS_EXPR(
        [('achado', num(N_CAT))],
        DO_RETURN([FOR('i', num(1), llen(gget('listaCats')), num(1), [
            IF(eq(litem(gget('listaCats'), lget('i')), lget('nome')), [lset('achado', lget('i'))]),
        ])], lget('achado'))))


def p_larguraBarra():
    """Largura da barra em % da largura da tela: a maior categoria ocupa BARRA_MAX; nenhuma fica menor que 1."""
    x = lambda: mround(mdiv(mmul(lget('valor'), num(T.BARRA_MAX)), lget('maior')))
    return defreturn('larguraBarra', ['valor', 'maior'],
                     CHOOSE(cmp('LTE', lget('maior'), num(0)), num(1),
                            CHOOSE(cmp('LT', x(), num(1)), num(1), x())))


# =========================================================================== v1.6: perfil (nome + foto)
def p_primeiroNome():
    """Primeira palavra do nome (ate o primeiro espaco)."""
    L = lget
    return defreturn('primeiroNome', ['texto'], LOCALS_EXPR(
        [('t', ttrim(lget('texto'))), ('fim', num(0))],
        DO_RETURN([FOR('i', num(1), tlen(L('t')), num(1), [
            IF(AND(cmp('EQ', L('fim'), num(0)), eq(segment(L('t'), L('i'), num(1)), txt(' '))), [lset('fim', L('i'))]),
        ])], CHOOSE(cmp('EQ', L('fim'), num(0)), L('t'), segment(L('t'), num(1), msub(L('fim'), num(1)))))))


def blocos_foto(spr, lado):
    """Mostra a foto do perfil no sprite 'spr' de um avatar de 'lado' dp: tamanho que cobre o circulo sem deformar
    (lado menor = lado do avatar) e centralizada no Canvas de 3 x lado. Sem foto (ou foto que nao abre): sprite escondido."""
    C = 3 * lado
    L = lget
    S = lambda p: cget(spr, 'ImageSprite', p)
    prop = lambda a, b: mround(mdiv(mmul(num(lado), a), b))                     # lado maior, na proporcao da foto
    lim = lambda mk: CHOOSE(cmp('GT', mk(), num(C - 2)), num(C - 2), mk())       # nunca maior que o Canvas
    larga = lambda: cmp('GTE', L('wn'), L('hn'))
    return [
        cset(spr, 'ImageSprite', 'Visible', boolean(False)),
        IF(NOT(tempty(gget('perfilFoto'))), [
            # -1 = tamanho automatico: assim Width/Height devolvem o tamanho natural da imagem (ImageSprite.Width())
            cset(spr, 'ImageSprite', 'Width', num(-1)),
            cset(spr, 'ImageSprite', 'Height', num(-1)),
            cset(spr, 'ImageSprite', 'Picture', gget('perfilFoto')),
            LOCALS_STMT([('wn', S('Width')), ('hn', S('Height'))], [
                IF(AND(cmp('GT', L('wn'), num(0)), cmp('GT', L('hn'), num(0))), [
                    LOCALS_STMT([('w', CHOOSE(larga(), lim(lambda: prop(L('wn'), L('hn'))), num(lado))),
                                 ('h', CHOOSE(larga(), num(lado), lim(lambda: prop(L('hn'), L('wn')))))], [
                        cset(spr, 'ImageSprite', 'Width', L('w')),
                        cset(spr, 'ImageSprite', 'Height', L('h')),
                        cset(spr, 'ImageSprite', 'X', mdiv(msub(num(C), L('w')), num(2))),
                        cset(spr, 'ImageSprite', 'Y', mdiv(msub(num(C), L('h')), num(2))),
                        cset(spr, 'ImageSprite', 'Visible', boolean(True)),
                    ]),
                ]),
            ]),
        ]),
    ]


def p_mostrarPerfil():
    """Saudacao e foto no cabecalho + foto no cartao do perfil."""
    return defnoreturn('mostrarPerfil', [],
                       [cset('LblSaudacao', 'Label', 'Text',
                             CHOOSE(tempty(gget('perfilNome')), txt(''),
                                    join(txt('Olá, '), call_expr('abreviar', call_expr('primeiroNome', gget('perfilNome'))))))]
                       + blocos_foto('SprFotoTopo', T.AVATAR_TOPO)
                       + blocos_foto('SprFotoPerfil', T.AVATAR)
                       + [cset('BtnRemoverFoto', 'Button', 'Visible', NOT(tempty(gget('perfilFoto'))))])


def p_mostrarMsgPerfil():
    return defnoreturn('mostrarMsgPerfil', ['ok', 'msg'], [
        cset('LblPerfilMsg', 'Label', 'Text', lget('msg')),
        cset('LblPerfilMsg', 'Label', 'TextColor', CHOOSE(lget('ok'), gcor('AvisoOk'), gcor('Perigo'))),
        cset('LblPerfilMsg', 'Label', 'Visible', boolean(True)),
    ])


def e_salvarPerfil():
    nome = lambda: ttrim(cget('TxtNome', 'TextBox', 'Text'))
    return cevent('BtnSalvarPerfil', 'Button', 'Click', [
        cmeth('TxtNome', 'TextBox', 'HideKeyboard'),
        call_stmt('guardarPref', txt('perfil_nome'), nome()),
        IF(gget('prefOk'),
           [gset('perfilNome', nome()),
            cset('TxtNome', 'TextBox', 'Text', gget('perfilNome')),
            call_stmt('mostrarPerfil'),
            call_stmt('mostrarMsgPerfil', boolean(True), txt('Perfil salvo!'))],
           [call_stmt('mostrarMsgPerfil', boolean(False), txt('Não foi possível salvar. Tente de novo.'))]),
    ])


def e_eventos_v16():
    return [
        cevent('ImgTema', 'Image', 'Click', [call_stmt('trocarTema', NOT(gget('temaEscuro')))]),
        cevent('BtnTemaClaro', 'Button', 'Click', [call_stmt('trocarTema', boolean(False))]),
        cevent('BtnTemaEscuro', 'Button', 'Click', [call_stmt('trocarTema', boolean(True))]),
        cevent('CanvasTopo', 'Canvas', 'Touched', [call_stmt('abrirPerfil')]),
        cevent('CanvasPerfil', 'Canvas', 'Touched', [
            cmeth('Notifier1', 'Notifier', 'ShowChooseDialog', txt('Tire uma foto agora com a câmera ou escolha uma da galeria.'),
                  txt('Foto do perfil'), txt('Tirar foto'), txt('Escolher da galeria'), boolean(True))]),
        e_fotoEscolhida(),
        e_removerFoto(),
        e_salvarPerfil(),
        cevent('BtnPerfilVoltar', 'Button', 'Click', [call_stmt('mostrarAba', gget('abaVolta'))]),
        cevent('TxtNome', 'TextBox', 'TextChanged', [cset('LblPerfilMsg', 'Label', 'Visible', boolean(False))]),
    ]


# =========================================================================== v1.7
# -*- coding: utf-8 -*-
# Blocos da v1.7, logo antes de GLOBAIS:
# usa a DSL acima (B, M, num, txt, IF, FOR, ...) e SUBSTITUI as versoes v1.6 dos procedimentos que mudaram.
#
# Regra da DSL: um bloco (Element) so pode ter UM pai. Por isso toda expressao usada mais de uma vez e escrita como
# lambda (cada chamada cria blocos novos). build_bky confere isso (nenhum Element aparece duas vezes na arvore).

# =========================================================================== v1.7: DSL nova
def comp_ref(nome, ctype):
    """Bloco 'componente' (component_component_block): o proprio componente como valor."""
    return B('component_component_block', fields=[('COMPONENT_SELECTOR', nome)],
             mut=M(component_type=ctype, instance_name=nome))


def gcset(ctype, prop, compexpr, val):
    """'set <Tipo>.<Prop> of component ... to ...' (bloco generico, is_generic=true)."""
    return B('component_set_get', fields=[('PROP', prop)], values=[('COMPONENT', compexpr), ('VALUE', val)],
             mut=M(component_type=ctype, set_or_get='set', property_name=prop, is_generic='true'))


def gcget(ctype, prop, compexpr):
    return B('component_set_get', fields=[('PROP', prop)], values=[('COMPONENT', compexpr)],
             mut=M(component_type=ctype, set_or_get='get', property_name=prop, is_generic='true'))


def downcase(x):
    return B('text_changeCase', fields=[('OP', 'DOWNCASE')], values=[('TEXT', x)])


def treplace(t, seg, rep):
    return B('text_replace_all', values=[('TEXT', t), ('SEGMENT', seg), ('REPLACEMENT', rep)])


def lreplace(lst, i, item):
    return B('lists_replace_item', values=[('LIST', lst), ('NUM', num(i) if isinstance(i, int) else i), ('ITEM', item)])


def lpos(item, lst):
    return B('lists_position_in', values=[('ITEM', item), ('LIST', lst)])


def to_csv(lst):
    return B('lists_to_csv_table', values=[('LIST', lst)])


def from_csv(t):
    return B('lists_from_csv_table', values=[('TEXT', t)])


def ljoin(sep, lst):
    return B('lists_join_with_separator', values=[('SEPARATOR', sep), ('LIST', lst)])


def WHILE(cond, body):
    return B('controls_while', values=[('TEST', cond)], stmts=[('DO', seq(body))])


def agora():
    return cmeth('Clock1', 'Clock', 'Now')


def neq(a, b):
    return NOT(eq(a, b))


def fmt(v):
    return call_expr('formatarMoeda', v)


def mmax(a_fn, b_fn):
    """maior entre dois valores (a_fn/b_fn devolvem blocos novos a cada chamada)."""
    return CHOOSE(cmp('GT', a_fn(), b_fn()), a_fn(), b_fn())


def mmin(a_fn, b_fn):
    return CHOOSE(cmp('LT', a_fn(), b_fn()), a_fn(), b_fn())


def AND3(a, b, c):
    return AND(a, AND(b, c))


def OR3(a, b, c):
    return OR(a, OR(b, c))


def chave_reg(i_fn):
    """Mes (ano*12+mes-1) do lancamento na posicao i, lido do cache 'chavesReg' (ver indexarChaves)."""
    return litem(gget('chavesReg'), i_fn())


def garantir_chaves():
    """Rede de seguranca: se o cache nao tem um mes por lancamento, refaz antes de usar."""
    return IF(cmp('NEQ', llen(gget('chavesReg')), llen(gget(REG))), [call_stmt('indexarChaves')])


def invalidar_chaves():
    return gset('chavesReg', mklist())


EVO_UTIL = 104          # altura maxima (dp) de uma barra "mes a mes" (a area tem 112)
ACUM_UTIL = 80          # altura maxima (dp) de uma barra do saldo acumulado (a area tem 84)
ALT_LINHA_LISTA = 70    # altura (dp) reservada por linha nas listas de 2 linhas (anos, recorrentes)
ALT_LINHA_OPCAO = 62    # altura (dp) reservada por linha na lista de opcoes (icone + nome)
ACENTOS = 'áàâãéêíóôõúüç'
SEM_ACENTO = 'aaaaeeiooouuc'
assert len(ACENTOS) == len(SEM_ACENTO)
MAX_MESES_ATRAS = 24    # lancamentos que se repetem: no maximo 24 meses para tras de uma vez

SIG.update({
    'chaveMes': ['data'],
    'chaveData': ['data'],
    'nomeMes': ['chave'],
    'pad2': ['n'],
    'diasNoMes': ['chave'],
    'noPeriodo': ['chave'],
    'descPeriodo': [],
    'semAcento': ['texto'],
    'valorSemRs': ['valor'],
    'html': ['texto'],
    'comSinal': ['valor'],
    'atualizarHoje': [],
    'indexarChaves': [],
    'atualizarPeriodoUI': [],
    'definirModo': ['modo'],
    'mudarPeriodo': ['passo'],
    'abrirMes': ['chave'],
    'abrirAno': ['ano'],
    'iniciarEdicao': ['indice'],
    'cancelarEdicao': [],
    'limparFormulario': [],
    'atualizarFormEdicao': [],
    'avisoLimite': ['categoria'],
    'gastoNoMes': ['categoria', 'chave'],
    'inserirOrdenado': ['registro'],
    'gerarRecorrentes': [],
    'atualizarRecorrentes': [],
    'comparar': ['rotulo', 'atual', 'anterior', 'temAnterior', 'menosEhBom', 'nomeAnterior'],
    'atualizarEvolucao': [],
    'evoResumoMes': ['eA', 'dA', 'eP', 'dP', 'eAP', 'dAP', 'temAtual', 'temAnt', 'temAP'],
    'abrirLimites': [],
    'esconderTecladoOrc': [],
    'campoCsv': ['valor'],
    'valorCsv': ['item'],
    'mostrarMsgDados': ['ok', 'msg'],
    'lerBackup': ['texto'],
    'aplicarBackup': [],
    'carregarListas': [],
    'campoIgual': ['x', 'y'],
    'registroIgual': ['a', 'b'],
    'listaIgual': ['a', 'b'],
    'pintarLinhaCat': ['r', 'c', 'valor', 'lim', 'total', 'maior'],
})

LISTAS_COMP = [
    # (global, tipo, nomes): listas de componentes para os blocos genericos ("set Label.Height of component")
    ('compBarE', 'Label', ['LblBarE%d' % i for i in range(1, 13)]),
    ('compBarD', 'Label', ['LblBarD%d' % i for i in range(1, 13)]),
    ('compBtnMes', 'Button', ['BtnMes%d' % i for i in range(1, 13)]),
    ('compBarA', 'Label', ['LblBarA%d' % i for i in range(1, 13)]),
    ('compAcumMes', 'Label', ['LblAcumMes%d' % i for i in range(1, 13)]),
    ('compTxtOrc', 'TextBox', ['TxtOrc%d' % i for i in range(1, N_CAT + 1)]),
    ('compHzOrc', 'HorizontalArrangement', ['HzCampoOrc%d' % i for i in range(1, N_CAT + 1)]),
    ('compPnlCat', 'VerticalArrangement', ['PnlCat%d' % i for i in range(1, N_CAT + 1)]),
    ('compImgCat', 'Image', ['ImgCat%d' % i for i in range(1, N_CAT + 1)]),
    ('compCatNome', 'Label', ['LblCatNome%d' % i for i in range(1, N_CAT + 1)]),
    ('compCatValor', 'Label', ['LblCatValor%d' % i for i in range(1, N_CAT + 1)]),
    ('compCatBarra', 'Label', ['LblCatBarra%d' % i for i in range(1, N_CAT + 1)]),
    ('compCatPct', 'Label', ['LblCatPct%d' % i for i in range(1, N_CAT + 1)]),
]

GLOBAIS_V17 = [
    ('periodoModo', lambda: txt('mes')),
    ('periodoChave', lambda: num(0)),
    ('chaveHoje', lambda: num(0)),
    ('diaHoje', lambda: num(1)),
    ('chaveMin', lambda: num(0)),
    ('chavesReg', lambda: mklist()),
    ('lidoDados', lambda: mklist()),
    ('saldoTotal', lambda: num(0)),
    ('evoAno', lambda: num(0)),
    ('mapaHist', lambda: mklist()),
    ('editIndice', lambda: num(0)),
    ('repetirSel', lambda: boolean(False)),
    ('orcamentos', lambda: mklist(*[num(0) for _ in range(N_CAT)])),
    ('recorrentes', lambda: mklist()),
    ('recSel', lambda: num(0)),
    ('anosLista', lambda: mklist()),
    ('abaVoltaOrc', lambda: num(3)),
    ('backupPendente', lambda: mklist()),
    ('listaMeses', lambda: mklist(*[txt(m) for m in T.MESES])),
    ('listaMesesTitulo', lambda: mklist(*[txt(m[0].upper() + m[1:]) for m in T.MESES])),
    ('listaMesesCurtos', lambda: mklist(*[txt(m) for m in T.MESES_CURTOS])),
] + [(g, (lambda: mklist())) for g, _, _ in LISTAS_COMP]


# =========================================================================== datas e periodo
def p_chaveMes():
    """'dd/MM/aaaa HH:mm' -> ano*12 + (mes-1). Texto fora do formato -> -1 (aparece so em 'Tudo')."""
    t = lambda: lget('t')
    ok = AND(cmp('GTE', tlen(t()), num(10)),
             AND3(eq(segment(t(), num(3), num(1)), txt('/')), eq(segment(t(), num(6), num(1)), txt('/')),
                  AND(isnum(segment(t(), num(4), num(2))), isnum(segment(t(), num(7), num(4))))))
    mes = lambda: segment(t(), num(4), num(2))
    return defreturn('chaveMes', ['data'], LOCALS_EXPR([('t', join(txt(''), lget('data')))],
        CHOOSE(ok, CHOOSE(AND(cmp('GTE', mes(), num(1)), cmp('LTE', mes(), num(12))),
                          madd(mmul(segment(t(), num(7), num(4)), num(12)), msub(mes(), num(1))), num(-1)),
               num(-1))))


def p_chaveData():
    """'dd/MM/aaaa HH:mm' -> aaaaMMddHHmm (numero para ordenar). Fora do formato -> 0 (o mais antigo)."""
    t = lambda: lget('t')
    seg = lambda a, n: segment(t(), num(a), num(n))
    ok = AND(cmp('GTE', tlen(t()), num(16)),
             AND3(isnum(seg(1, 2)), AND(isnum(seg(4, 2)), isnum(seg(7, 4))), AND(isnum(seg(12, 2)), isnum(seg(15, 2)))))
    return defreturn('chaveData', ['data'], LOCALS_EXPR([('t', join(txt(''), lget('data')))],
        CHOOSE(ok, madd(mmul(seg(7, 4), num(100000000)), mmul(seg(4, 2), num(1000000)), mmul(seg(1, 2), num(10000)),
                        mmul(seg(12, 2), num(100)), seg(15, 2)), num(0))))


def p_nomeMes():
    k = lambda: lget('chave')
    return defreturn('nomeMes', ['chave'],
                     join(litem(gget('listaMeses'), madd(remainder(k(), num(12)), num(1))), txt(' de '), quotient(k(), num(12))))


def p_pad2():
    return defreturn('pad2', ['n'], CHOOSE(cmp('LT', lget('n'), num(10)), join(txt('0'), lget('n')), join(txt(''), lget('n'))))


def p_diasNoMes():
    k = lambda: lget('chave')
    m = lambda: madd(remainder(k(), num(12)), num(1))
    y = lambda: quotient(k(), num(12))
    bissexto = OR(AND(eq(remainder(y(), num(4)), num(0)), neq(remainder(y(), num(100)), num(0))),
                  eq(remainder(y(), num(400)), num(0)))
    trinta = OR(OR(eq(m(), num(4)), eq(m(), num(6))), OR(eq(m(), num(9)), eq(m(), num(11))))
    return defreturn('diasNoMes', ['chave'],
                     CHOOSE(eq(m(), num(2)), CHOOSE(bissexto, num(29), num(28)), CHOOSE(trinta, num(30), num(31))))


def p_noPeriodo():
    k = lambda: lget('chave')
    modo = lambda v: eq(gget('periodoModo'), txt(v))
    return defreturn('noPeriodo', ['chave'],
                     CHOOSE(modo('tudo'), boolean(True),
                            CHOOSE(modo('mes'), eq(k(), gget('periodoChave')),
                                   AND(cmp('GTE', k(), num(0)), eq(quotient(k(), num(12)), gget('periodoChave'))))))


def p_descPeriodo():
    modo = lambda v: eq(gget('periodoModo'), txt(v))
    return defreturn('descPeriodo', [],
                     CHOOSE(modo('mes'), call_expr('nomeMes', gget('periodoChave')),
                            CHOOSE(modo('ano'), join(txt(''), gget('periodoChave')), txt('todo o período'))))


def p_semAcento():
    """minusculas e sem acento (busca: 'saude' encontra 'Saúde')."""
    return defreturn('semAcento', ['texto'], LOCALS_EXPR([('r', downcase(join(txt(''), lget('texto'))))],
        DO_RETURN([FOR('i', num(1), num(len(ACENTOS)), num(1), [
            lset('r', treplace(lget('r'), segment(txt(ACENTOS), lget('i'), num(1)), segment(txt(SEM_ACENTO), lget('i'), num(1)))),
        ])], lget('r'))))


def p_html():
    """Texto digitado pela pessoa dentro da mensagem de um dialogo do Notifier: a mensagem passa por Html.fromHtml
    (Notifier.stringToHTML), entao '&', '<' e '>' sao escapados."""
    return defreturn('html', ['texto'], treplace(treplace(treplace(join(txt(''), lget('texto')), txt('&'), txt('&amp;')),
                                                          txt('<'), txt('&lt;')), txt('>'), txt('&gt;')))


def p_valorSemRs():
    return defreturn('valorSemRs', ['valor'], treplace(fmt(lget('valor')), txt('R$ '), txt('')))


def p_comSinal():
    """+ R$ 1,00 / − R$ 1,00 (zero sem sinal)."""
    v = lambda: lget('valor')
    return defreturn('comSinal', ['valor'],
                     CHOOSE(cmp('GT', v(), num(0)), join(txt('+ '), fmt(v())),
                            CHOOSE(cmp('LT', v(), num(0)), join(txt('− '), fmt(mabs(v()))), fmt(num(0)))))


def p_atualizarHoje():
    return defnoreturn('atualizarHoje', [], [
        gset('chaveHoje', madd(mmul(cmeth('Clock1', 'Clock', 'Year', agora()), num(12)),
                               msub(cmeth('Clock1', 'Clock', 'Month', agora()), num(1)))),
        gset('diaHoje', cmeth('Clock1', 'Clock', 'DayOfMonth', agora())),
    ])


def p_indexarChaves():
    """Cache: o mes de cada lancamento (mesma posicao da lista) e o mes mais antigo com lancamento.
    Ler a data de cada lancamento e o passo mais caro; com o cache, trocar de periodo nao rele milhares de datas."""
    return defnoreturn('indexarChaves', [], [
        gset('chavesReg', mklist()),
        gset('chaveMin', gget('chaveHoje')),
        FOREACH('item', gget(REG), [
            LOCALS_STMT([('k', call_expr('chaveMes', litem(lget('item'), 4)))], [
                ladd(gget('chavesReg'), lget('k')),
                IF(AND(cmp('GTE', lget('k'), num(0)), cmp('LT', lget('k'), gget('chaveMin'))), [gset('chaveMin', lget('k'))]),
            ]),
        ]),
    ])


def p_atualizarTudo():
    """Saldo (tudo), entradas/despesas do MES ATUAL no cabecalho, totais do PERIODO escolhido para Historico/Grafico."""
    item = lambda i: litem(lget('item'), i)
    ent = lambda: eq(item(1), txt('Entrada'))
    mes_curto = lambda: litem(gget('listaMesesCurtos'), madd(remainder(gget('chaveHoje'), num(12)), num(1)))
    return defnoreturn('atualizarTudo', [], [
        call_stmt('atualizarHoje'),
        garantir_chaves(),
        gset('saldoTotal', num(0)),
        gset('totalEntradas', num(0)),
        gset('totalDespesas', num(0)),
        LOCALS_STMT([('entMes', num(0)), ('despMes', num(0)), ('item', mklist()), ('k', num(0))], [
            FOR('i', num(1), llen(gget(REG)), num(1), [
                lset('item', litem(gget(REG), lget('i'))),
                lset('k', chave_reg(lambda: lget('i'))),
                gset('saldoTotal', CHOOSE(ent(), madd(gget('saldoTotal'), item(3)), msub(gget('saldoTotal'), item(3)))),
                IF(eq(lget('k'), gget('chaveHoje')),
                   [IF(ent(), [lset('entMes', madd(lget('entMes'), item(3)))], [lset('despMes', madd(lget('despMes'), item(3)))])]),
                IF(call_expr('noPeriodo', lget('k')),
                   [IF(ent(), [gset('totalEntradas', madd(gget('totalEntradas'), item(3)))],
                       [gset('totalDespesas', madd(gget('totalDespesas'), item(3)))])]),
            ]),
            cset('LblSaldo', 'Label', 'Text', fmt(gget('saldoTotal'))),
            cset('LblEntradas', 'Label', 'Text', fmt(lget('entMes'))),
            cset('LblDespesas', 'Label', 'Text', fmt(lget('despMes'))),
            cset('LblCapEntradas', 'Label', 'Text', join(txt('Entradas em '), mes_curto())),
            cset('LblCapDespesas', 'Label', 'Text', join(txt('Despesas em '), mes_curto())),
        ]),
        call_stmt('atualizarPeriodoUI'),
        call_stmt('atualizarHistorico'),
        call_stmt('atualizarGrafico'),
        IF(eq(gget('abaAtual'), num(5)), [call_stmt('atualizarEvolucao')]),
        call_stmt('atualizarMeta'),
    ])


def p_atualizarPeriodoUI():
    modo = lambda v: eq(gget('periodoModo'), txt(v))
    anoMin = lambda: quotient(gget('chaveMin'), num(12))
    anoHoje = lambda: quotient(gget('chaveHoje'), num(12))
    anterior = OR(AND(modo('mes'), cmp('GT', gget('periodoChave'), gget('chaveMin'))),
                  AND(modo('ano'), cmp('GT', gget('periodoChave'), anoMin())))
    proximo = OR(AND(modo('mes'), cmp('LT', gget('periodoChave'), gget('chaveHoje'))),
                 AND(modo('ano'), cmp('LT', gget('periodoChave'), anoHoje())))
    return defnoreturn('atualizarPeriodoUI', [], [
        cset('LblPeriodo', 'Label', 'Text',
             CHOOSE(modo('mes'), join(litem(gget('listaMesesTitulo'), madd(remainder(gget('periodoChave'), num(12)), num(1))),
                                      txt(' de '), quotient(gget('periodoChave'), num(12))),
                    CHOOSE(modo('ano'), join(txt('Ano de '), gget('periodoChave')), txt('Todos os lançamentos')))),
        # a seta (imagem) some -- vira a imagem transparente -- quando nao ha para onde ir; o botao continua no lugar.
        # v1.8.1: era o texto "‹"/"›", que no Android sumia atras da margem interna do botao
        cset('BtnPerAnt', 'Button', 'Image', CHOOSE(anterior, gimg('SetaEsq'), gimg('Nada'))),
        cset('BtnPerProx', 'Button', 'Image', CHOOSE(proximo, gimg('SetaDir'), gimg('Nada'))),
    ])


def p_definirModo():
    """Mes / Ano / Tudo. Mantem o contexto: de 'mes de marco/2025' para Ano mostra 2025; de 'ano 2025' para Mes mostra
    dezembro/2025 (no ano atual, o mes atual). Tocar de novo no modo ja escolhido volta para hoje."""
    m = lambda v: eq(lget('modo'), txt(v))
    antes = lambda v: eq(gget('periodoModo'), txt(v))
    anoHoje = lambda: quotient(gget('chaveHoje'), num(12))
    novo = CHOOSE(m('mes'),
                  CHOOSE(AND(antes('ano'), cmp('NEQ', gget('periodoChave'), anoHoje())),
                         madd(mmul(gget('periodoChave'), num(12)), num(11)), gget('chaveHoje')),
                  CHOOSE(m('ano'), CHOOSE(antes('mes'), quotient(gget('periodoChave'), num(12)), anoHoje()), num(0)))
    return defnoreturn('definirModo', ['modo'], [
        LOCALS_STMT([('novo', novo)], [
            gset('periodoModo', lget('modo')),
            gset('periodoChave', lget('novo')),
        ]),
        call_stmt('pintarAbas'),
        call_stmt('atualizarTudo'),
    ])


def p_mudarPeriodo():
    """Setas do periodo: anda um mes (ou ano) e nunca sai do intervalo [mais antigo com lancamento, hoje]."""
    modo = lambda v: eq(gget('periodoModo'), txt(v))
    novo = lambda: madd(gget('periodoChave'), lget('passo'))
    pode = lambda minimo, maximo: OR(AND(cmp('GT', lget('passo'), num(0)), cmp('LTE', novo(), maximo())),
                                     AND(cmp('LT', lget('passo'), num(0)), cmp('GTE', novo(), minimo())))
    return defnoreturn('mudarPeriodo', ['passo'], [
        IF(AND(modo('mes'), pode(lambda: gget('chaveMin'), lambda: gget('chaveHoje'))), [gset('periodoChave', novo())]),
        IF(AND(modo('ano'), pode(lambda: quotient(gget('chaveMin'), num(12)), lambda: quotient(gget('chaveHoje'), num(12)))),
           [gset('periodoChave', novo())]),
        call_stmt('atualizarTudo'),
    ])


def p_abrirMes():
    return defnoreturn('abrirMes', ['chave'], [
        IF(cmp('LTE', lget('chave'), gget('chaveHoje')), [
            gset('periodoModo', txt('mes')),
            gset('periodoChave', lget('chave')),
            call_stmt('atualizarTudo'),
            call_stmt('mostrarAba', num(3)),
        ]),
    ])


def p_abrirAno():
    return defnoreturn('abrirAno', ['ano'], [
        gset('periodoModo', txt('ano')),
        gset('periodoChave', lget('ano')),
        call_stmt('atualizarTudo'),
        call_stmt('mostrarAba', num(3)),
    ])


# =========================================================================== abas
def p_pintarAbas():
    """Destaca a aba ativa, o modo de periodo ativo e a opcao de tema ativa (cores do tema atual)."""
    corpo = []
    for inst, n in (('BtnNavLancar', 1), ('BtnNavHistorico', 2), ('BtnNavGrafico', 3), ('BtnNavEvolucao', 5)):
        corpo += _pilula(inst, lambda n=n: cmp('EQ', gget('abaAtual'), num(n)))
    for inst, modo in (('BtnModoMes', 'mes'), ('BtnModoAno', 'ano'), ('BtnModoTudo', 'tudo')):
        corpo += _pilula(inst, lambda modo=modo: eq(gget('periodoModo'), txt(modo)))
    corpo += _pilula('BtnTemaClaro', lambda: NOT(gget('temaEscuro')))
    corpo += _pilula('BtnTemaEscuro', lambda: gget('temaEscuro'))
    return defnoreturn('pintarAbas', [], corpo)


def p_abrirPerfil():
    return defnoreturn('abrirPerfil', [], [
        IF(cmp('NEQ', gget('abaAtual'), num(4)), [gset('abaVolta', gget('abaAtual'))]),
        cmeth('TxtDescricao', 'TextBox', 'HideKeyboard'),
        cmeth('TxtValor', 'TextBox', 'HideKeyboard'),
        cset('TxtNome', 'TextBox', 'Text', gget('perfilNome')),
        cset('LblPerfilMsg', 'Label', 'Visible', boolean(False)),
        cset('LblDadosMsg', 'Label', 'Visible', boolean(False)),
        call_stmt('mostrarAba', num(4)),
    ])


# =========================================================================== historico (periodo + busca + editar)
def p_atualizarHistorico():
    """Linhas do periodo escolhido que combinam com a busca; mapaHist guarda a posicao de cada linha na lista."""
    item = lambda i: litem(lget('item'), i)
    entrada = lambda: eq(item(1), txt('Entrada'))
    termo = lambda: lget('termo')
    busca = lambda: ttrim(cget('TxtBusca', 'TextBox', 'Text'))
    linha = cmeth(
        'ListaHistorico', 'ListView', 'CreateElement',
        join(CHOOSE(entrada(), txt('+ '), txt('− ')), fmt(item(3))),
        join(item(2), txt('  •  '), item(4),
             txt('\\nCategoria: '), item(5),
             txt('\\nPagamento: '), item(6)),
        CHOOSE(entrada(), txt(T.IMG_SETA_ENT), txt(T.IMG_SETA_DESP)))
    combina = AND(call_expr('noPeriodo', chave_reg(lambda: lget('i'))),
                  OR(tempty(termo()),
                     tcontains(call_expr('semAcento', join(item(2), txt(' '), item(5), txt(' '), item(6))), termo())))
    n = lambda: llen(gget('linhas'))
    return defnoreturn('atualizarHistorico', [], [
        garantir_chaves(),
        gset('linhas', mklist()),
        gset('mapaHist', mklist()),
        LOCALS_STMT([('termo', call_expr('semAcento', busca())),
                     ('somaE', num(0)), ('somaD', num(0)), ('item', mklist())], [
            FOR('i', num(1), llen(gget(REG)), num(1), [
                lset('item', litem(gget(REG), lget('i'))),
                IF(combina, [
                    ladd(gget('linhas'), linha),
                    ladd(gget('mapaHist'), lget('i')),
                    IF(entrada(), [lset('somaE', madd(lget('somaE'), item(3)))], [lset('somaD', madd(lget('somaD'), item(3)))]),
                ]),
            ]),
            cset('ListaHistorico', 'ListView', 'Elements', gget('linhas')),
            cset('LblVazio', 'Label', 'Visible', eq(n(), num(0))),
            cset('LblVazio', 'Label', 'Text',
                 CHOOSE(eq(llen(gget(REG)), num(0)), txt('Nenhum lançamento ainda. Comece pela aba Lançar!'),
                        CHOOSE(NOT(tempty(termo())),
                               join(txt('Nada encontrado para “'), busca(), txt('” em '), call_expr('descPeriodo'), txt('.')),
                               join(txt('Nenhum lançamento em '), call_expr('descPeriodo'), txt('.'))))),
            cset('LblResumoHist', 'Label', 'Text',
                 CHOOSE(eq(n(), num(0)), txt(''),
                        join(n(), CHOOSE(eq(n(), num(1)), txt(' lançamento'), txt(' lançamentos')),
                             txt('  •  + '), fmt(lget('somaE')), txt('  •  − '), fmt(lget('somaD'))))),
            cset('LblResumoHist', 'Label', 'Visible', cmp('GT', n(), num(0))),
            cset('BtnLimparBusca', 'Button', 'Visible', NOT(tempty(cget('TxtBusca', 'TextBox', 'Text')))),
        ]),
    ])


def e_historicoToque():
    idx = lambda: cget('ListaHistorico', 'ListView', 'SelectionIndex')
    item = lambda i: litem(litem(gget(REG), gget('indiceSel')), i)
    return cevent('ListaHistorico', 'ListView', 'AfterPicking', [
        IF(AND(cmp('GTE', idx(), num(1)), cmp('LTE', idx(), llen(gget('mapaHist')))), [
            gset('indiceSel', litem(gget('mapaHist'), idx())),
            cmeth('Notifier1', 'Notifier', 'ShowChooseDialog',
                  # a mensagem do dialogo passa por Html.fromHtml: quebra de linha e <br> e o texto digitado e escapado
                  join(call_expr('html', item(2)), txt('<br>'), CHOOSE(eq(item(1), txt('Entrada')), txt('+ '), txt('− ')),
                       fmt(item(3)), txt(' • '), item(4)),
                  txt('O que você quer fazer?'), txt('Editar'), txt('Excluir'), boolean(True)),
        ]),
    ])


def p_cancelarEdicao():
    return defnoreturn('cancelarEdicao', [], [
        gset('editIndice', num(0)),
        call_stmt('limparErros'),
        call_stmt('limparFormulario'),
        call_stmt('atualizarFormEdicao'),
    ])


def p_atualizarFormEdicao():
    ed = lambda: AND(cmp('GT', gget('editIndice'), num(0)), cmp('LTE', gget('editIndice'), llen(gget(REG))))
    return defnoreturn('atualizarFormEdicao', [], [
        cset('LblTituloLancar', 'Label', 'Text', CHOOSE(ed(), txt('Editar lançamento'), txt('Novo lançamento'))),
        cset('LblSubLancar', 'Label', 'Text',
             CHOOSE(ed(), join(txt('Lançado em '), litem(litem(gget(REG), gget('editIndice')), 4),
                               txt('. Mude o que quiser e toque em Salvar.')),
                    txt('Registre uma entrada ou uma despesa.'))),
        cset('BtnEntrada', 'Button', 'Text', CHOOSE(ed(), txt('Salvar entrada'), txt('+ Entrada'))),
        cset('BtnDespesa', 'Button', 'Text', CHOOSE(ed(), txt('Salvar despesa'), txt('− Despesa'))),
        cset('BtnCancelarEdicao', 'Button', 'Visible', ed()),
        cset('HzRepetir', 'HorizontalArrangement', 'Visible', NOT(ed())),
        cset('ImgRepetir', 'Image', 'Picture', CHOOSE(gget('repetirSel'), gimg('CheckOn'), gimg('CheckOff'))),
    ])


def p_registrar():
    """Valida; em modo edicao substitui o lancamento (mesma data), senao cria um novo no topo. Grava e confere;
    se a gravacao falhar desfaz na memoria e avisa em vermelho (nunca finge sucesso)."""
    desc = lambda: ttrim(cget('TxtDescricao', 'TextBox', 'Text'))
    valor_txt = lambda: ttrim(cget('TxtValor', 'TextBox', 'Text'))
    tipo = lambda: lget('tipo')

    def erro(lbl, hz, img, msg):
        return [cset(lbl, 'Label', 'Text', txt(msg)), cset(lbl, 'Label', 'Visible', boolean(True)),
                cset(hz, 'HorizontalArrangement', 'Image', gimg(img)), gset('temErro', boolean(True))]
    erro_valor = lambda msg: erro('LblErroValor', 'HzCampoValor', 'CampoErro', msg)
    desc_final = lambda: CHOOSE(tempty(desc()), txt('Sem descrição'), desc())
    editando = AND(cmp('GT', gget('editIndice'), num(0)), cmp('LTE', gget('editIndice'), llen(gget(REG))))
    aviso_limite = lambda data_fn: CHOOSE(AND(eq(tipo(), txt('Despesa')), eq(call_expr('chaveMes', data_fn()), gget('chaveHoje'))),
                                          call_expr('avisoLimite', gget('categoriaSel')), txt(''))
    depois_ok = lambda: [call_stmt('limparFormulario'), call_stmt('atualizarFormEdicao')]

    data_ant = lambda: join(txt(''), litem(lget('antigo'), 4))
    editar = LOCALS_STMT([('antigo', litem(gget(REG), gget('editIndice'))), ('msg', txt('')), ('pos', num(1)), ('novo', mklist()),
                          ('antes', B('lists_copy', values=[('LIST', gget(REG))])), ('novaData', txt(''))], [
        lset('novaData', CHOOSE(tempty(gget('dataSel')), data_ant(),
                                join(gget('dataSel'), CHOOSE(cmp('GTE', tlen(data_ant()), num(16)), segment(data_ant(), num(11), num(6)),
                                                             txt(' 12:00'))))),
        lset('novo', mklist(tipo(), desc_final(), gget('valorCentavos'), lget('novaData'), gget('categoriaSel'), gget('pagamentoSel'))),
        IFELIF([(eq(lget('novaData'), data_ant()), [lreplace(gget(REG), gget('editIndice'), lget('novo'))])],
               els=[lremove(gget(REG), gget('editIndice'))] + inserir_em_ordem(lambda: lget('novo'))),
        invalidar_chaves(),
        call_stmt('gravarDados'),
        # editar nao muda o tamanho da lista: confere a lista inteira lida de volta (o lancamento pode ter mudado de lugar)
        IF(gget('gravacaoOk'), [gset('gravacaoOk', call_expr('listaIgual', gget('lidoDados'), gget(REG)))]),
        IF(gget('gravacaoOk'),
           [gset('editIndice', num(0)),
            call_stmt('atualizarTudo'),
            lset('msg', join(txt('Lançamento atualizado!'), aviso_limite(lambda: lget('novaData')))),
            ] + depois_ok() + [
            call_stmt('mostrarAviso', boolean(True), lget('msg'))],
           [gset(REG, lget('antes')),
            invalidar_chaves(),
            call_stmt('atualizarTudo'),
            call_stmt('mostrarAviso', boolean(False), txt('Não foi possível gravar. A alteração não foi salva.'))]),
    ])

    # v1.8: repete no dia e a partir do mes do PROPRIO lancamento (a data pode ter sido escolhida)
    rec_novo = mklist(tipo(), litem(lget('novo'), 2), gget('valorCentavos'), gget('categoriaSel'), gget('pagamentoSel'),
                      madd(num(0), segment(litem(lget('novo'), 4), num(1), num(2))), call_expr('chaveMes', litem(lget('novo'), 4)))
    data_nova = lambda: CHOOSE(tempty(gget('dataSel')), cmeth('Clock1', 'Clock', 'FormatDate', agora(), txt('dd/MM/yyyy HH:mm')),
                               join(gget('dataSel'), txt(' '), cmeth('Clock1', 'Clock', 'FormatDate', agora(), txt('HH:mm'))))

    criar = LOCALS_STMT([('novo', mklist(tipo(), desc_final(), gget('valorCentavos'), data_nova(),
                                         gget('categoriaSel'), gget('pagamentoSel'))),
                         ('msg', txt('')), ('repOk', boolean(True)), ('pos', num(1)), ('n0', num(0)),
                         ('antes', B('lists_copy', values=[('LIST', gget(REG))]))], [
        ] + inserir_em_ordem(lambda: lget('novo')) + [
        invalidar_chaves(),
        call_stmt('gravarDados'),
        IF(gget('gravacaoOk'),
           [lset('msg', CHOOSE(eq(tipo(), txt('Entrada')), txt('Entrada registrada!'), txt('Despesa registrada!'))),
            IF(gget('repetirSel'), [
                ladd(gget('recorrentes'), rec_novo),
                call_stmt('guardarPref', txt('recorrentes'), gget('recorrentes')),
                IF(gget('prefOk'),
                   [lset('msg', join(lget('msg'), txt(' Vai se repetir todo dia '),
                                     madd(num(0), segment(litem(lget('novo'), 4), num(1), num(2))), txt('.')))],
                   [lremove(gget('recorrentes'), llen(gget('recorrentes'))),
                    lset('repOk', boolean(False)),
                    lset('msg', join(lget('msg'), txt(' Mas não foi possível guardar a repetição mensal.')))]),
                # v1.8: lancamento de um mes passado que se repete -> ja lanca os meses seguintes ate hoje
                IF(AND(lget('repOk'), cmp('LT', call_expr('chaveMes', litem(lget('novo'), 4)), gget('chaveHoje'))), [
                    lset('n0', llen(gget(REG))),
                    call_stmt('gerarRecorrentes'),
                    IF(cmp('GT', llen(gget(REG)), lget('n0')),
                       [lset('msg', join(lget('msg'), txt(' Os meses seguintes, até hoje, também foram lançados.')))]),
                ]),
            ]),
            call_stmt('atualizarTudo'),
            lset('msg', join(lget('msg'), aviso_limite(lambda: litem(lget('novo'), 4)))),
            ] + depois_ok() + [
            call_stmt('atualizarRecorrentes'),
            call_stmt('mostrarAviso', lget('repOk'), lget('msg'))],
           [gset(REG, lget('antes')),
            invalidar_chaves(),
            call_stmt('atualizarTudo'),
            call_stmt('mostrarAviso', boolean(False), txt('Não foi possível gravar. Este lançamento não foi salvo.'))]),
    ])

    return defnoreturn('registrar', ['tipo'], [
        call_stmt('atualizarHoje'),
        call_stmt('limparErros'),
        gset('temErro', boolean(False)),
        IF(tempty(gget('categoriaSel')), erro('LblErroCat', 'HzCampoCat', 'CampoSelErro', 'Escolha uma categoria.')),
        IF(tempty(gget('pagamentoSel')), erro('LblErroPag', 'HzCampoPag', 'CampoSelErro', 'Escolha a forma de pagamento.')),
        IFELIF([(tempty(valor_txt()), erro_valor('Informe o valor.'))],
               els=[gset('valorCentavos', call_expr('paraCentavos', cget('TxtValor', 'TextBox', 'Text'))),
                    IFELIF([(cmp('LT', gget('valorCentavos'), num(0)),
                             erro_valor('Valor inválido. Use vírgula nos centavos: 25,90 ou 1.250,99.')),
                            (cmp('EQ', gget('valorCentavos'), num(0)),
                             erro_valor('Digite um valor maior que zero.'))])]),
        # v1.8.1: a edicao so grava depois do "Salvar" da janela "Salvar alterações?" (Notifier1.AfterChoosing)
        IF(NOT(gget('temErro')), [IF(editando, [IF(gget('edicaoConfirmada'), [gset('edicaoConfirmada', boolean(False)), editar],
                                                   [gset('tipoEdicaoPendente', tipo()), call_stmt('confirmarEdicao')])],
                                     [criar])]),
    ])


# =========================================================================== orcamento (limites por categoria)
def p_gastoNoMes():
    item = lambda i: litem(litem(gget(REG), lget('i')), i)
    return defreturn('gastoNoMes', ['categoria', 'chave'], LOCALS_EXPR([('soma', num(0))], DO_RETURN([
        garantir_chaves(),
        FOR('i', num(1), llen(gget(REG)), num(1), [
            IF(AND(eq(chave_reg(lambda: lget('i')), lget('chave')),
                   AND(neq(item(1), txt('Entrada')), eq(item(5), lget('categoria')))),
               [lset('soma', madd(lget('soma'), item(3)))]),
        ]),
    ], lget('soma'))))


def p_avisoLimite():
    """Frase extra para a faixa de sucesso quando a despesa encosta (>= 80%) ou passa do limite do mes."""
    lim = lambda: lget('lim')
    g = lambda: lget('gasto')
    return defreturn('avisoLimite', ['categoria'], LOCALS_EXPR(
        [('pos', lpos(lget('categoria'), gget('listaCats'))), ('lim', num(0)), ('gasto', num(0))],
        DO_RETURN([
            IF(cmp('GT', lget('pos'), num(0)), [
                lset('lim', litem(gget('orcamentos'), lget('pos'))),
                IF(cmp('GT', lim(), num(0)), [lset('gasto', call_expr('gastoNoMes', lget('categoria'), gget('chaveHoje')))]),
            ]),
        ], CHOOSE(cmp('LTE', lim(), num(0)), txt(''),
                  CHOOSE(cmp('GT', g(), lim()), join(txt(' '), lget('categoria'), txt(' passou do limite do mês.')),
                         CHOOSE(cmp('GTE', mmul(g(), num(100)), mmul(lim(), num(80))),
                                join(txt(' '), lget('categoria'), txt(' já usou '), mround(mdiv(mmul(g(), num(100)), lim())),
                                     txt('% do limite do mês.')),
                                txt('')))))))


def p_esconderTecladoOrc():
    return defnoreturn('esconderTecladoOrc', [], [cmeth('TxtOrc%d' % i, 'TextBox', 'HideKeyboard') for i in range(1, N_CAT + 1)])


def p_abrirLimites():
    c = lambda: litem(gget('compTxtOrc'), lget('i'))
    v = lambda: litem(gget('orcamentos'), lget('i'))
    return defnoreturn('abrirLimites', [], [
        IF(cmp('NEQ', gget('abaAtual'), num(6)), [gset('abaVoltaOrc', gget('abaAtual'))]),
        FOR('i', num(1), num(N_CAT), num(1), [
            gcset('TextBox', 'Text', c(), CHOOSE(cmp('GT', v(), num(0)), call_expr('valorSemRs', v()), txt(''))),
            gcset('HorizontalArrangement', 'Image', litem(gget('compHzOrc'), lget('i')), gimg('CampoCurto')),
        ]),
        cset('LblErroOrc', 'Label', 'Visible', boolean(False)),
        call_stmt('mostrarAba', num(6)),
    ])


def e_salvarLimites():
    texto = lambda: ttrim(gcget('TextBox', 'Text', litem(gget('compTxtOrc'), lget('i'))))
    hz = lambda: litem(gget('compHzOrc'), lget('i'))
    return cevent('BtnSalvarOrc', 'Button', 'Click', [
        call_stmt('esconderTecladoOrc'),
        LOCALS_STMT([('novos', mklist()), ('erroCat', txt('')), ('v', num(0))], [
            FOR('i', num(1), num(N_CAT), num(1), [
                IF(tempty(texto()),
                   [ladd(lget('novos'), num(0)), gcset('HorizontalArrangement', 'Image', hz(), gimg('CampoCurto'))],
                   [lset('v', call_expr('paraCentavos', texto())),
                    IF(cmp('GTE', lget('v'), num(0)),
                       [ladd(lget('novos'), lget('v')), gcset('HorizontalArrangement', 'Image', hz(), gimg('CampoCurto'))],
                       [ladd(lget('novos'), num(0)), gcset('HorizontalArrangement', 'Image', hz(), gimg('CampoCurtoErro')),
                        IF(tempty(lget('erroCat')), [lset('erroCat', litem(gget('listaCats'), lget('i')))])])]),
            ]),
            IF(NOT(tempty(lget('erroCat'))),
               [cset('LblErroOrc', 'Label', 'Text', join(txt('Valor inválido em '), lget('erroCat'),
                                                         txt('. Use vírgula nos centavos: 800,00.'))),
                cset('LblErroOrc', 'Label', 'Visible', boolean(True))],
               [call_stmt('guardarPref', txt('orcamentos'), lget('novos')),
                IF(gget('prefOk'),
                   [gset('orcamentos', lget('novos')),
                    cset('LblErroOrc', 'Label', 'Visible', boolean(False)),
                    call_stmt('mostrarAba', gget('abaVoltaOrc')),
                    call_stmt('atualizarTudo'),
                    IF(eq(gget('abaAtual'), num(4)), [call_stmt('mostrarMsgDados', boolean(True), txt('Limites salvos!'))])],
                   [cset('LblErroOrc', 'Label', 'Text', txt('Não foi possível salvar os limites. Tente de novo.')),
                    cset('LblErroOrc', 'Label', 'Visible', boolean(True))])]),
        ]),
    ])


# =========================================================================== grafico (periodo) e categorias (periodo + limites)
def p_atualizarResumo():
    """Ultimos 3 lancamentos de cada tipo DO PERIODO (descricao | valor com sinal), abaixo da legenda do grafico."""
    item = lambda i: litem(lget('item'), i)
    sep = lambda acc: CHOOSE(tempty(lget(acc)), txt(''), txt('\\n'))

    def add(cnt, nomes, vals, sinal):
        return IF(cmp('LT', lget(cnt), num(3)), [
            lset(cnt, madd(lget(cnt), num(1))),
            lset(nomes, join(lget(nomes), sep(nomes), call_expr('abreviar', item(2)))),
            lset(vals, join(lget(vals), sep(vals), txt(sinal), fmt(item(3)))),
        ])
    return defnoreturn('atualizarResumo', [], [
        garantir_chaves(),
        LOCALS_STMT([('nE', num(0)), ('nD', num(0)), ('nomesE', txt('')), ('valE', txt('')),
                     ('nomesD', txt('')), ('valD', txt('')), ('item', mklist())], [
            FOR('i', num(1), llen(gget(REG)), num(1), [
                IF(call_expr('noPeriodo', chave_reg(lambda: lget('i'))), [
                    lset('item', litem(gget(REG), lget('i'))),
                    IF(eq(item(1), txt('Entrada')),
                       [add('nE', 'nomesE', 'valE', '+ ')],
                       [add('nD', 'nomesD', 'valD', '− ')]),
                ]),
            ]),
            cset('LblResEntNomes', 'Label', 'Text', lget('nomesE')),
            cset('LblResEntValores', 'Label', 'Text', lget('valE')),
            cset('LblResDespNomes', 'Label', 'Text', lget('nomesD')),
            cset('LblResDespValores', 'Label', 'Text', lget('valD')),
            cset('PnlResEnt', 'VerticalArrangement', 'Visible', cmp('GT', lget('nE'), num(0))),
            cset('PnlResDesp', 'VerticalArrangement', 'Visible', cmp('GT', lget('nD'), num(0))),
            cset('PnlResumo', 'VerticalArrangement', 'Visible', cmp('GT', madd(lget('nE'), lget('nD')), num(0))),
        ]),
    ])


# =========================================================================== recorrentes
def p_inserirOrdenado():
    """Insere mantendo a lista do mais novo para o mais antigo: anda do topo ate o primeiro lancamento mais antigo
    (os gerados sao recentes, entao o laco para logo)."""
    return defnoreturn('inserirOrdenado', ['registro'], [
        LOCALS_STMT([('cd', call_expr('chaveData', litem(lget('registro'), 4))), ('pos', num(1))], [
            WHILE(AND(cmp('LTE', lget('pos'), llen(gget(REG))),
                      cmp('GTE', call_expr('chaveData', litem(litem(gget(REG), lget('pos')), 4)), lget('cd'))),
                  [lset('pos', madd(lget('pos'), num(1)))]),
            IF(cmp('GT', lget('pos'), llen(gget(REG))), [ladd(gget(REG), lget('registro'))],
               [linsert(gget(REG), lget('pos'), lget('registro'))]),
        ]),
    ])


def p_gerarRecorrentes():
    """Ao abrir o app: cria os lancamentos que se repetem cujo dia ja chegou (no maximo 24 meses para tras).
    Dia 31 em mes de 30 dias (ou fevereiro) vira o ultimo dia do mes. Se nao conseguir gravar, desfaz tudo e avisa."""
    rec = lambda i: litem(lget('rec'), i)
    inicio = lambda: madd(rec(7), num(1))
    piso = lambda: msub(gget('chaveHoje'), num(MAX_MESES_ATRAS))
    dia = lambda: mmin(lambda: rec(6), lambda: call_expr('diasNoMes', lget('k')))
    data = lambda: join(call_expr('pad2', lget('d')), txt('/'), call_expr('pad2', madd(remainder(lget('k'), num(12)), num(1))),
                        txt('/'), quotient(lget('k'), num(12)), txt(' 08:00'))
    falhou = lambda: [
        # volta ao que esta guardado no aparelho (lancamentos de antes e repeticoes como estavam)
        gset(REG, lget('antes')),
        call_stmt('gravarDados'),
        call_stmt('carregarDados'),
        call_stmt('carregarPreferencias'),
        dialog_erro(txt('Erro: não foi possível adicionar os lançamentos que se repetem. Tente abrir o app de novo.')),
    ]
    return defnoreturn('gerarRecorrentes', [], [
        IF(cmp('GT', llen(gget('recorrentes')), num(0)), [
            LOCALS_STMT([('novos', num(0)), ('parar', boolean(False)), ('d', num(1)), ('rec', mklist()),
                         ('antes', B('lists_copy', values=[('LIST', gget(REG))]))], [
                FOR('r', num(1), llen(gget('recorrentes')), num(1), [
                    lset('rec', litem(gget('recorrentes'), lget('r'))),
                    lset('parar', boolean(False)),
                    FOR('k', CHOOSE(cmp('GT', inicio(), piso()), inicio(), piso()), gget('chaveHoje'), num(1), [
                        IF(NOT(lget('parar')), [
                            lset('d', dia()),
                            IF(OR(cmp('LT', lget('k'), gget('chaveHoje')), cmp('GTE', gget('diaHoje'), lget('d'))),
                               [call_stmt('inserirOrdenado', mklist(rec(1), rec(2), rec(3), data(), rec(4), rec(5))),
                                lreplace(lget('rec'), 7, lget('k')),
                                lset('novos', madd(lget('novos'), num(1)))],
                               [lset('parar', boolean(True))]),
                        ]),
                    ]),
                ]),
                IF(cmp('GT', lget('novos'), num(0)), [
                    invalidar_chaves(),
                    call_stmt('gravarDados'),
                    IF(gget('gravacaoOk'), [
                        call_stmt('guardarPref', txt('recorrentes'), gget('recorrentes')),
                        IF(gget('prefOk'),
                           [call_stmt('mostrarAviso', boolean(True),
                                      join(lget('novos'), CHOOSE(eq(lget('novos'), num(1)),
                                                                 txt(' lançamento que se repete foi adicionado.'),
                                                                 txt(' lançamentos que se repetem foram adicionados.'))))],
                           falhou()),
                    ], falhou()),
                ]),
            ]),
        ]),
    ])


def p_atualizarRecorrentes():
    rec = lambda i: litem(lget('rec'), i)
    n = lambda: llen(gget('recorrentes'))
    return defnoreturn('atualizarRecorrentes', [], [
        gset('linhas', mklist()),
        FOREACH('rec', gget('recorrentes'), [
            ladd(gget('linhas'), cmeth('ListaRecorrentes', 'ListView', 'CreateElement',
                                       join(rec(2), txt('  •  '), CHOOSE(eq(rec(1), txt('Entrada')), txt('+ '), txt('− ')), fmt(rec(3))),
                                       join(txt('Todo dia '), rec(6), txt('  •  '), rec(4), txt('  •  '), rec(5)), txt(''))),
        ]),
        cset('ListaRecorrentes', 'ListView', 'Elements', gget('linhas')),
        cset('ListaRecorrentes', 'ListView', 'Height', mmul(mmax(lambda: n(), lambda: num(1)), num(ALT_LINHA_LISTA))),
        cset('ListaRecorrentes', 'ListView', 'Visible', cmp('GT', n(), num(0))),
        cset('LblSemRec', 'Label', 'Visible', eq(n(), num(0))),
    ])


def e_recorrenteToque():
    idx = lambda: cget('ListaRecorrentes', 'ListView', 'SelectionIndex')
    return cevent('ListaRecorrentes', 'ListView', 'AfterPicking', [
        IF(AND(cmp('GTE', idx(), num(1)), cmp('LTE', idx(), llen(gget('recorrentes')))), [
            gset('recSel', idx()),
            cmeth('Notifier1', 'Notifier', 'ShowChooseDialog',
                  join(txt('Parar de repetir “'), call_expr('html', litem(litem(gget('recorrentes'), idx()), 2)),
                       txt('”? O que já foi lançado continua no histórico.')),
                  txt('Contô'), txt('Parar de repetir'), txt('Manter'), boolean(False)),
        ]),
    ])


# =========================================================================== escolhas dos dialogos
def e_afterChoosing():
    """Editar / Excluir / Apagar tudo / Parar de repetir / Restaurar. Se gravar falhar, desfaz e avisa."""
    escolha = lambda v: eq(evparam('choice'), txt(v))
    erro = lambda: dialog_erro(txt('Erro: não foi possível gravar a exclusão. Nada foi alterado.'))
    sel = lambda: gget('indiceSel')
    return cevent('Notifier1', 'Notifier', 'AfterChoosing', [
        IF(escolha('Editar'), [call_stmt('iniciarEdicao', sel())]),
        # v1.8.1: "Excluir" so pergunta (quem exclui e "Sim, excluir"); "Salvar" grava a edicao que esperava resposta
        IF(escolha('Excluir'), [call_stmt('confirmarExclusao')]),
        # (so vale com uma edicao em andamento: um "Salvar" fora de hora nao cria lancamento a partir do formulario)
        IF(AND(escolha('Salvar'), cmp('GT', gget('editIndice'), num(0))),
           [gset('edicaoConfirmada', boolean(True)), call_stmt('registrar', gget('tipoEdicaoPendente')),
            gset('edicaoConfirmada', boolean(False))]),
        IF(escolha('Remover foto'), [
            gset('perfilFoto', txt('')),
            call_stmt('mostrarPerfil'),
            call_stmt('guardarPref', txt('perfil_foto'), txt('')),
            erro_pref('Erro: não foi possível guardar a alteração neste aparelho.'),
        ]),
        IF(escolha('Sim, excluir'), [
            IF(AND(cmp('GTE', sel(), num(1)), cmp('LTE', sel(), llen(gget(REG)))), [
                LOCALS_STMT([('removido', litem(gget(REG), sel()))], [
                    lremove(gget(REG), sel()),
                    invalidar_chaves(),
                    call_stmt('gravarDados'),
                    IF(NOT(gget('gravacaoOk')), [linsert(gget(REG), sel(), lget('removido')), invalidar_chaves()]),
                    # se estava editando: o proprio lancamento sumiu -> sai da edicao; um de cima sumiu -> posicao anda 1
                    IF(AND(gget('gravacaoOk'), cmp('GT', gget('editIndice'), num(0))), [
                        IFELIF([(cmp('EQ', sel(), gget('editIndice')), [call_stmt('cancelarEdicao')]),
                                (cmp('LT', sel(), gget('editIndice')),
                                 [gset('editIndice', msub(gget('editIndice'), num(1))), call_stmt('atualizarFormEdicao')])]),
                    ]),
                    call_stmt('atualizarTudo'),
                    IF(NOT(gget('gravacaoOk')), [erro()]),
                ]),
            ]),
        ]),
        IF(escolha('Apagar tudo'), [
            LOCALS_STMT([('copia', gget(REG))], [
                gset(REG, mklist()),
                invalidar_chaves(),
                call_stmt('gravarDados'),
                IF(NOT(gget('gravacaoOk')), [gset(REG, lget('copia')), invalidar_chaves()]),
                IF(AND(gget('gravacaoOk'), cmp('GT', gget('editIndice'), num(0))), [call_stmt('cancelarEdicao')]),
                call_stmt('atualizarTudo'),
                IF(NOT(gget('gravacaoOk')), [erro()]),
            ]),
        ]),
        *escolhas_notif(),
        IF(escolha('Parar de repetir'), [
            IF(AND(cmp('GTE', gget('recSel'), num(1)), cmp('LTE', gget('recSel'), llen(gget('recorrentes')))), [
                LOCALS_STMT([('removido', litem(gget('recorrentes'), gget('recSel')))], [
                    lremove(gget('recorrentes'), gget('recSel')),
                    call_stmt('guardarPref', txt('recorrentes'), gget('recorrentes')),
                    IF(NOT(gget('prefOk')),
                       [linsert(gget('recorrentes'), gget('recSel'), lget('removido')),
                        dialog_erro(txt('Erro: não foi possível guardar a alteração neste aparelho.'))]),
                    call_stmt('atualizarRecorrentes'),
                ]),
            ]),
        ]),
        IF(escolha('Restaurar'), [call_stmt('aplicarBackup')]),
        IF(escolha('Importar'), [call_stmt('aplicarImportacao')]),
        # v1.9: janela da foto do perfil (tocar na foto)
        IF(escolha('Tirar foto'), [cmeth('CameraFoto', 'Camera', 'TakePicture')]),
        IF(escolha('Escolher da galeria'), [cmeth('PickerFoto', 'ImagePicker', 'Open')]),
        IF(AND(escolha('Cancelar'), cmp('GT', llen(gget('importPendente')), num(0))), [
            gset('importPendente', mklist()),
            call_stmt('mostrarMsgDados', boolean(True), txt('Importação cancelada. Nada mudou.')),
        ]),
        IF(escolha('Remover meta'), [
            cmeth('TinyDB1', 'TinyDB', 'StoreValue', txt('meta'), mklist()),
            IF(eq(llen(cmeth('TinyDB1', 'TinyDB', 'GetValue', txt('meta'), txt(''))), num(0)),
               [gset('meta', mklist()), call_stmt('atualizarMeta'), call_stmt('mostrarAba', num(5))],
               [dialog_erro(txt('Erro: não foi possível remover a meta neste aparelho.'))]),
        ]),
        IF(AND(escolha('Cancelar'), cmp('GT', llen(gget('backupPendente')), num(0))), [
            gset('backupPendente', mklist()),
            call_stmt('mostrarMsgDados', boolean(True), txt('Restauração cancelada. Nada mudou.')),
        ]),
    ])


# =========================================================================== evolucao
def p_comparar():
    """Frase de comparacao com o mes anterior, com cor: verde quando melhorou, vermelha quando piorou."""
    L = lget
    rot = lambda: L('rotulo')
    pct = lambda: call_expr('formatarPercentual', mround(mdiv(mmul(mabs(msub(L('atual'), L('anterior'))), num(1000)), L('anterior'))))
    melhorou = lambda: CHOOSE(L('menosEhBom'), cmp('LT', L('atual'), L('anterior')), cmp('GT', L('atual'), L('anterior')))
    return defnoreturn('comparar', ['rotulo', 'atual', 'anterior', 'temAnterior', 'menosEhBom', 'nomeAnterior'], [
        IFELIF([
            (NOT(L('temAnterior')),
             [gcset('Label', 'Text', rot(), join(txt('Sem lançamentos em '), L('nomeAnterior'), txt(' para comparar.'))),
              gcset('Label', 'TextColor', rot(), gcor('Suave'))]),
            (eq(L('atual'), L('anterior')),
             [gcset('Label', 'Text', rot(), join(txt('Igual a '), L('nomeAnterior'), txt('.'))),
              gcset('Label', 'TextColor', rot(), gcor('Suave'))]),
            (eq(L('anterior'), num(0)),
             [gcset('Label', 'Text', rot(), join(txt('Em '), L('nomeAnterior'), txt(' foi R$ 0,00.'))),
              gcset('Label', 'TextColor', rot(), CHOOSE(melhorou(), gcor('Bom'), gcor('Perigo')))]),
        ], els=[
            gcset('Label', 'Text', rot(),
                  join(pct(), CHOOSE(cmp('LT', L('atual'), L('anterior')), txt(' a menos que em '), txt(' a mais que em ')),
                       L('nomeAnterior'), txt(' ('), fmt(L('anterior')), txt(').'))),
            gcset('Label', 'TextColor', rot(), CHOOSE(melhorou(), gcor('Bom'), gcor('Perigo'))),
        ]),
    ])


# =========================================================================== exportar, backup, restaurar
def p_campoCsv():
    """Campo da planilha (separador ';'): aspas quando precisa; '=', '+', '-', '@' no inicio ganham apostrofo (nao viram formula)."""
    t = lambda: lget('t')
    precisa = OR3(tcontains(t(), txt(';')), tcontains(t(), txt('"')), tcontains(t(), txt('\\n')))
    formula = AND(NOT(tempty(t())), cmp('GT', lpos(segment(t(), num(1), num(1)), mklist(txt('='), txt('+'), txt('-'), txt('@'))), num(0)))
    return defreturn('campoCsv', ['valor'], LOCALS_EXPR([('t', join(txt(''), lget('valor')))], DO_RETURN([
        IF(formula, [lset('t', join(txt("'"), t()))]),
    ], CHOOSE(precisa, join(txt('"'), treplace(t(), txt('"'), txt('""')), txt('"')), t()))))


def p_valorCsv():
    item = lambda i: litem(lget('item'), i)
    return defreturn('valorCsv', ['item'],
                     join(CHOOSE(eq(item(1), txt('Entrada')), txt(''), txt('-')), quotient(item(3), num(100)), txt(','),
                          call_expr('pad2', remainder(item(3), num(100)))))


def p_mostrarMsgDados():
    return defnoreturn('mostrarMsgDados', ['ok', 'msg'], [
        cset('LblDadosMsg', 'Label', 'Text', lget('msg')),
        cset('LblDadosMsg', 'Label', 'TextColor', CHOOSE(lget('ok'), gcor('AvisoOk'), gcor('Perigo'))),
        cset('LblDadosMsg', 'Label', 'Visible', boolean(True)),
    ])


def hoje_arquivo():
    return cmeth('Clock1', 'Clock', 'FormatDate', agora(), txt('yyyy-MM-dd'))


def e_exportar():
    item = lambda i: litem(lget('item'), i)
    c = lambda i: call_expr('campoCsv', item(i))
    return cevent('BtnExportar', 'Button', 'Click', [
        IF(eq(llen(gget(REG)), num(0)),
           [call_stmt('mostrarMsgDados', boolean(False), txt('Ainda não há lançamentos para exportar.'))],
           [LOCALS_STMT([('linhasCsv', mklist(txt('﻿Data;Tipo;Descrição;Categoria;Pagamento;Valor (R$)')))], [
               FOREACH('item', gget(REG), [
                   ladd(lget('linhasCsv'), join(c(4), txt(';'), c(1), txt(';'), c(2), txt(';'), c(5), txt(';'), c(6), txt(';'),
                                                call_expr('valorCsv', lget('item')))),
               ]),
               call_stmt('mostrarMsgDados', boolean(True), txt('Preparando a planilha…')),
               cmeth('File1', 'File', 'SaveFile', ljoin(txt('\\r\\n'), lget('linhasCsv')),
                     join(txt('Conto_planilha_'), hoje_arquivo(), txt('.csv'))),
           ])]),
    ])


def e_backup():
    item = lambda i: litem(lget('item'), i)
    orc = lambda i: litem(gget('orcamentos'), i)
    rec = lambda i: litem(lget('rec'), i)
    return cevent('BtnBackup', 'Button', 'Click', [
        LOCALS_STMT([('tabela', mklist(mklist(txt('Conto-backup'), txt('1'),
                                              cmeth('Clock1', 'Clock', 'FormatDate', agora(), txt('dd/MM/yyyy HH:mm')))))], [
            FOREACH('item', gget(REG), [
                ladd(lget('tabela'), mklist(txt('L'), item(1), item(2), item(3), item(4), item(5), item(6))),
            ]),
            ladd(lget('tabela'), mklist(txt('O'), *[orc(i) for i in range(1, N_CAT + 1)])),
            FOREACH('rec', gget('recorrentes'), [
                ladd(lget('tabela'), mklist(txt('R'), rec(1), rec(2), rec(3), rec(4), rec(5), rec(6), rec(7))),
            ]),
            ladd(lget('tabela'), mklist(txt('P'), gget('perfilNome'))),
            ladd(lget('tabela'), mklist(txt('T'), CHOOSE(gget('temaEscuro'), txt('escuro'), txt('claro')))),
            # v1.8: meta de economia (se houver)
            IF(eq(llen(gget('meta')), num(5)), [ladd(lget('tabela'), mklist(txt('M'), litem(gget('meta'), 1), litem(gget('meta'), 2),
                                                                              litem(gget('meta'), 3), litem(gget('meta'), 4),
                                                                              litem(gget('meta'), 5)))]),
            # ultima linha = conferencia: um arquivo cortado (ou com lancamentos apagados a mao) nao e restaurado pela metade
            ladd(lget('tabela'), mklist(txt('Fim'), llen(gget(REG)))),
            call_stmt('mostrarMsgDados', boolean(True), txt('Preparando o backup…')),
            cmeth('File1', 'File', 'SaveFile', to_csv(lget('tabela')), join(txt('Conto_backup_'), hoje_arquivo(), txt('.txt'))),
        ]),
    ])


def p_lerBackup():
    """Confere o arquivo e prepara os dados; nada muda ate a pessoa confirmar em 'Restaurar'."""
    L = lget
    row = lambda i: litem(L('row'), i)
    tam = lambda: llen(L('row'))
    tag = lambda v: AND(cmp('GTE', tam(), num(1)), eq(row(1), txt(v)))
    inteiro_pos = lambda x_fn: AND3(isnum(x_fn()), cmp('GT', x_fn(), num(0)), eq(mround(x_fn()), x_fn()))
    tipo_ok = lambda: OR(eq(row(2), txt('Entrada')), eq(row(2), txt('Despesa')))
    reg_ok = AND3(tag('L'), cmp('GTE', tam(), num(7)), AND(tipo_ok(), inteiro_pos(lambda: row(4))))
    rec_ok = AND3(tag('R'), cmp('GTE', tam(), num(8)),
                  AND3(tipo_ok(), inteiro_pos(lambda: row(4)),
                       AND3(inteiro_pos(lambda: row(7)), cmp('LTE', row(7), num(31)), AND(isnum(row(8)), cmp('GTE', row(8), num(0))))))
    texto = lambda: L('t')
    cabecalho_ok = AND(cmp('GTE', tlen(texto()), num(14)), eq(segment(texto(), num(1), num(14)), txt('"Conto-backup"')))
    # O backup tem TODOS os campos entre aspas (aspas de dentro dobradas): um arquivo inteiro tem um numero PAR de aspas
    # e termina numa aspa (depois de tirar espacos/quebras do fim). Arquivo cortado no meio de um campo (ou com uma aspa
    # apagada) faria o "lista de tabela CSV" parar o app com um erro tecnico; aqui vira um aviso e nada muda.
    n_aspas = lambda: msub(tlen(texto()), tlen(treplace(texto(), txt('"'), txt(''))))
    inteiro_ok = AND(eq(modulo(n_aspas(), num(2)), num(0)), eq(segment(texto(), tlen(texto()), num(1)), txt('"')))
    return defnoreturn('lerBackup', ['texto'], [
        gset('backupPendente', mklist()),
        LOCALS_STMT([('t', join(txt(''), L('texto')))], [
        # arquivo que passou por outro app pode ganhar um BOM (U+FEFF) no inicio: tira antes de conferir
        IF(AND(cmp('GTE', tlen(texto()), num(1)), eq(segment(texto(), num(1), num(1)), txt('﻿'))),
           [lset('t', segment(texto(), num(2), msub(tlen(texto()), num(1))))]),
        # espacos e quebras de linha a mais nas pontas (algum app pode acrescentar) nao fazem parte do backup
        lset('t', ttrim(texto())),
        IFELIF([
            (NOT(cabecalho_ok), [call_stmt('mostrarMsgDados', boolean(False), txt('Este arquivo não é um backup do Contô.'))]),
            (NOT(inteiro_ok), [call_stmt('mostrarMsgDados', boolean(False),
                                         txt('Este backup está incompleto ou foi alterado. Nada mudou.'))]),
           ], els=[LOCALS_STMT([('tabela', from_csv(texto())), ('regs', mklist()), ('orcs', mklist()), ('recs', mklist()),
                         ('nome', gget('perfilNome')), ('tema', CHOOSE(gget('temaEscuro'), txt('escuro'), txt('claro'))),
                         ('quando', txt('')), ('row', mklist()), ('nL', num(0)), ('metaB', mklist())], [
               IF(cmp('GTE', llen(litem(L('tabela'), 1)), num(3)), [lset('quando', litem(litem(L('tabela'), 1), 3))]),
               FOR('i', num(2), llen(L('tabela')), num(1), [
                   lset('row', litem(L('tabela'), L('i'))),
                   IF(tag('L'), [lset('nL', madd(L('nL'), num(1)))]),
                   IFELIF([
                       (reg_ok, [ladd(L('regs'), mklist(row(2), row(3), madd(num(0), row(4)), row(5), row(6), row(7)))]),
                       (AND(tag('O'), cmp('GTE', tam(), num(N_CAT + 1))),
                        [lset('orcs', mklist()),
                         FOR('j', num(2), num(N_CAT + 1), num(1), [
                             ladd(L('orcs'), CHOOSE(inteiro_pos(lambda: row(L('j'))), madd(num(0), row(L('j'))), num(0))),
                         ])]),
                       (rec_ok, [ladd(L('recs'), mklist(row(2), row(3), madd(num(0), row(4)), row(5), row(6),
                                                        madd(num(0), row(7)), madd(num(0), row(8))))]),
                       (AND(tag('P'), cmp('GTE', tam(), num(2))), [lset('nome', row(2))]),
                       (AND(tag('T'), cmp('GTE', tam(), num(2))), [lset('tema', row(2))]),
                       (AND3(tag('M'), cmp('GTE', tam(), num(6)),
                             AND3(inteiro_pos(lambda: row(3)), AND(isnum(row(4)), cmp('GTE', row(4), num(0))),
                                  AND3(isnum(row(5)), cmp('GTE', row(5), num(0)), AND(isnum(row(6)), eq(mround(row(6)), row(6)))))),
                        [lset('metaB', mklist(join(txt(''), row(2)), madd(num(0), row(3)), madd(num(0), row(4)), madd(num(0), row(5)),
                                              madd(num(0), row(6))))]),
                   ]),
               ]),
               # a ultima linha tem de ser a conferencia "Fim" com o numero de linhas de lancamento do arquivo
               lset('row', litem(L('tabela'), llen(L('tabela')))),
               IF(AND3(tag('Fim'), cmp('GTE', tam(), num(2)), eq(row(2), L('nL'))), [
                   IF(eq(llen(L('orcs')), num(0)), [lset('orcs', mklist(*[num(0) for _ in range(N_CAT)]))]),
                   gset('backupPendente', mklist(L('regs'), L('orcs'), L('recs'), L('nome'), eq(L('tema'), txt('escuro')), L('metaB'))),
                   cmeth('Notifier1', 'Notifier', 'ShowChooseDialog',
                         join(txt('Backup de '), call_expr('html', L('quando')), txt(' com '), llen(L('regs')),
                              CHOOSE(eq(llen(L('regs')), num(1)), txt(' lançamento.'), txt(' lançamentos.')),
                              txt('<br><br>Restaurar vai substituir os lançamentos que estão no app agora ('), llen(gget(REG)),
                              txt('), além dos limites e do que se repete.')),
                         txt('Restaurar backup?'), txt('Restaurar'), txt('Cancelar'), boolean(False)),
               ], [call_stmt('mostrarMsgDados', boolean(False), txt('Este backup está incompleto ou foi alterado. Nada mudou.'))]),
           ])]),
        ]),
    ])


def p_aplicarBackup():
    b = lambda i: litem(gget('backupPendente'), i)
    return defnoreturn('aplicarBackup', [], [
        IF(eq(llen(gget('backupPendente')), num(6)), [
            LOCALS_STMT([('antigos', gget(REG)), ('falhou', boolean(False))], [
                gset(REG, b(1)),
                invalidar_chaves(),
                call_stmt('gravarDados'),
                # o backup pode ter o mesmo numero de lancamentos que o app: confere o conteudo inteiro
                IF(gget('gravacaoOk'), [gset('gravacaoOk', call_expr('listaIgual', gget('lidoDados'), gget(REG)))]),
                IF(NOT(gget('gravacaoOk')),
                   [gset(REG, lget('antigos')),
                    invalidar_chaves(),
                    call_stmt('mostrarMsgDados', boolean(False), txt('Não foi possível restaurar: o aparelho não deixou gravar. Nada mudou.'))],
                   [call_stmt('guardarPref', txt('orcamentos'), b(2)),
                    IF(gget('prefOk'), [gset('orcamentos', b(2))], [lset('falhou', boolean(True))]),
                    call_stmt('guardarPref', txt('recorrentes'), b(3)),
                    IF(gget('prefOk'), [gset('recorrentes', b(3))], [lset('falhou', boolean(True))]),
                    call_stmt('guardarPref', txt('perfil_nome'), join(txt(''), b(4))),
                    IF(gget('prefOk'), [gset('perfilNome', join(txt(''), b(4)))], [lset('falhou', boolean(True))]),
                    call_stmt('trocarTema', b(5)),
                    # v1.8: meta do backup (backup sem meta = sem meta, como o resto: restaurar substitui tudo)
                    cmeth('TinyDB1', 'TinyDB', 'StoreValue', txt('meta'), b(6)),
                    IF(call_expr('registroIgual', cmeth('TinyDB1', 'TinyDB', 'GetValue', txt('meta'), txt('')), b(6)),
                       [gset('meta', b(6))], [lset('falhou', boolean(True))]),
                    gset('editIndice', num(0)),
                    call_stmt('limparFormulario'),
                    call_stmt('atualizarFormEdicao'),
                    gset('periodoModo', txt('mes')),
                    gset('periodoChave', gget('chaveHoje')),
                    gset('evoAno', quotient(gget('chaveHoje'), num(12))),
                    call_stmt('pintarAbas'),
                    call_stmt('atualizarTudo'),
                    call_stmt('mostrarPerfil'),
                    call_stmt('atualizarRecorrentes'),
                    cset('TxtNome', 'TextBox', 'Text', gget('perfilNome')),
                    call_stmt('mostrarMsgDados', NOT(lget('falhou')),
                              CHOOSE(lget('falhou'),
                                     join(txt('Lançamentos restaurados ('), llen(gget(REG)), txt('), mas alguns ajustes não foram salvos.')),
                                     join(txt('Backup restaurado: '), llen(gget(REG)),
                                          CHOOSE(eq(llen(gget(REG)), num(1)), txt(' lançamento.'), txt(' lançamentos.')))))]),
            ]),
        ]),
        gset('backupPendente', mklist()),
    ])


# =========================================================================== v1.6 que mudaram na v1.7
def p_gravarDados():
    """Grava e CONFERE lendo de volta (o tamanho, como na v1.6: incluir e excluir mudam o tamanho). v1.7: guarda o que
    voltou em lidoDados, para editar e restaurar (que podem manter o tamanho) conferirem tambem o conteudo."""
    return defnoreturn('gravarDados', [], [
        cmeth('TinyDB1', 'TinyDB', 'StoreValue', gget('chaveDados'), gget(REG)),
        gset('lidoDados', get_db('chaveDados', mklist())),
        gset('gravacaoOk', cmp('EQ', llen(gget('lidoDados')), llen(gget(REG)))),
    ])


def p_campoIgual():
    """Um campo gravado (x) e o da memoria (y) sao o mesmo? O TinyDB devolve os textos "true"/"false" (qualquer
    maiuscula) como verdadeiro/falso (JsonUtil.convertJsonItem): so esse caso e comparado sem diferenciar maiuscula."""
    tx = lambda: downcase(join(txt(''), lget('x')))
    ty = lambda: downcase(join(txt(''), lget('y')))
    return defreturn('campoIgual', ['x', 'y'],
                     OR(eq(lget('x'), lget('y')), AND(OR(eq(tx(), txt('true')), eq(tx(), txt('false'))), eq(tx(), ty()))))


def p_registroIgual():
    a = lambda: lget('a')
    b = lambda: lget('b')
    return defreturn('registroIgual', ['a', 'b'], LOCALS_EXPR(
        [('ok', AND(lis(a()), AND(lis(b()), cmp('EQ', llen(a()), llen(b())))))],
        DO_RETURN([IF(lget('ok'), [FOR('i', num(1), llen(a()), num(1), [
            IF(NOT(call_expr('campoIgual', litem(a(), lget('i')), litem(b(), lget('i')))), [lset('ok', boolean(False))]),
        ])])], lget('ok'))))


def p_listaIgual():
    """Lista gravada x lista da memoria, lancamento por lancamento (usado ao restaurar um backup)."""
    a = lambda: lget('a')
    b = lambda: lget('b')
    return defreturn('listaIgual', ['a', 'b'], LOCALS_EXPR(
        [('ok', AND(lis(a()), cmp('EQ', llen(a()), llen(b()))))],
        DO_RETURN([IF(lget('ok'), [FOR('i', num(1), llen(a()), num(1), [
            IF(NOT(call_expr('registroIgual', litem(a(), lget('i')), litem(b(), lget('i')))), [lset('ok', boolean(False))]),
        ])])], lget('ok'))))


def p_mostrarAviso():
    """Faixa colorida no topo da aba Lancar (verde = ok, some sozinha; vermelha = erro, fica ate a proxima acao).
    v1.7: frase longa fica 5 s em vez de 3 s."""
    return defnoreturn('mostrarAviso', ['ok', 'msg'], [
        gset('avisoOk', lget('ok')),
        cset('PnlAviso', 'HorizontalArrangement', 'Image', CHOOSE(lget('ok'), gimg('AvisoOk'), gimg('AvisoErro'))),
        cset('LblAviso', 'Label', 'TextColor', CHOOSE(lget('ok'), gcor('AvisoOk'), gcor('Perigo'))),
        cset('LblAviso', 'Label', 'Text', lget('msg')),
        cset('BoxAviso', 'VerticalArrangement', 'Visible', boolean(True)),
        cset('ClockAviso', 'Clock', 'TimerInterval', CHOOSE(cmp('GT', tlen(lget('msg')), num(45)), num(5000), num(3000))),
        cset('ClockAviso', 'Clock', 'TimerEnabled', lget('ok')),
    ])


def p_abrirPicker():
    eh_cat = lambda: eq(lget('tipo'), txt('cat'))
    nomes = lambda: CHOOSE(eh_cat(), gget('listaCats'), gget('listaPags'))
    icones = lambda: CHOOSE(eh_cat(), gget('listaCatIcones'), gget('listaPagIcones'))
    return defnoreturn('abrirPicker', ['tipo'], [
        gset('pickerTipo', lget('tipo')),
        cmeth('TxtDescricao', 'TextBox', 'HideKeyboard'),
        cmeth('TxtValor', 'TextBox', 'HideKeyboard'),
        gset('linhas', mklist()),
        FOR('i', num(1), llen(nomes()), num(1), [
            ladd(gget('linhas'), cmeth('ListaOpcoes', 'ListView', 'CreateElement',
                                       litem(nomes(), lget('i')), txt(''), litem(icones(), lget('i')))),
        ]),
        cset('ListaOpcoes', 'ListView', 'Elements', gget('linhas')),
        # v1.7: a lista cresce com o numero de opcoes (8 categorias nao ficam mais cortadas)
        cset('ListaOpcoes', 'ListView', 'Height', madd(mmul(llen(gget('linhas')), num(ALT_LINHA_OPCAO)), num(8))),
        cset('LblPickerTitulo', 'Label', 'Text', CHOOSE(eh_cat(), txt('Escolha uma categoria'), txt('Escolha a forma de pagamento'))),
        cset('PnlLancar', 'VerticalArrangement', 'Visible', boolean(False)),
        cset('PnlPicker', 'VerticalArrangement', 'Visible', boolean(True)),
    ])


def p_pintarEstados():
    """Partes que dependem do momento (campo com erro, faixa de aviso, campos de escolha, abas, marca de 'repetir',
    cores calculadas dos graficos) no tema atual."""
    vis = lambda lbl: cget(lbl, 'Label', 'Visible')
    return defnoreturn('pintarEstados', [], [
        cset('HzCampoValor', 'HorizontalArrangement', 'Image', CHOOSE(vis('LblErroValor'), gimg('CampoErro'), gimg('Campo'))),
        cset('HzCampoCat', 'HorizontalArrangement', 'Image', CHOOSE(vis('LblErroCat'), gimg('CampoSelErro'), gimg('CampoSel'))),
        cset('HzCampoPag', 'HorizontalArrangement', 'Image', CHOOSE(vis('LblErroPag'), gimg('CampoSelErro'), gimg('CampoSel'))),
        cset('HzCampoData', 'HorizontalArrangement', 'Image', CHOOSE(vis('LblErroData'), gimg('CampoSelErro'), gimg('CampoSel'))),
        cset('HzCampoMetaValor', 'HorizontalArrangement', 'Image', CHOOSE(vis('LblErroMetaValor'), gimg('CampoErro'), gimg('Campo'))),
        call_stmt('pintarMetaEdit'),
        call_stmt('atualizarInfoBackup'),
        cset('PnlAviso', 'HorizontalArrangement', 'Image', CHOOSE(gget('avisoOk'), gimg('AvisoOk'), gimg('AvisoErro'))),
        cset('LblAviso', 'Label', 'TextColor', CHOOSE(gget('avisoOk'), gcor('AvisoOk'), gcor('Perigo'))),
        cset('LblPerfilMsg', 'Label', 'Visible', boolean(False)),
        cset('LblDadosMsg', 'Label', 'Visible', boolean(False)),
        cset('LblErroOrc', 'Label', 'Visible', boolean(False)),
        call_stmt('atualizarCampos'),
        call_stmt('atualizarFormEdicao'),
        call_stmt('pintarAbas'),
        call_stmt('atualizarTudo'),
        cset('LblNotifMsg', 'Label', 'Visible', boolean(False)),
        call_stmt('atualizarNotif'),
    ])


def p_carregarDados():
    """Carrega os lancamentos; na primeira execucao migra os dados da versao anterior (chave 'transacoes')."""
    def item(i):
        return litem(lget('item'), i)
    migrar = FOREACH('item', get_db('chaveAntiga', mklist()), [
        IF(AND(lis(lget('item')), cmp('GTE', llen(lget('item')), num(4))), [
            ladd(gget(REG), mklist(
                item(1),                                     # tipo
                item(2),                                     # descricao
                CHOOSE(isnum(item(3)), mround(mmul(item(3), num(100))), num(0)),   # reais -> centavos
                item(4),                                     # data
                CHOOSE(cmp('GT', llen(lget('item')), num(5)), item(5), txt('Não informado')),
                CHOOSE(cmp('GT', llen(lget('item')), num(5)), item(6), txt('Não informado')))),
        ]),
    ])
    return defnoreturn('carregarDados', [], [
        gset(REG, get_db('chaveDados', txt(''))),
        invalidar_chaves(),
        IF(NOT(lis(gget(REG))), [
            gset(REG, mklist()),
            IF(lis(get_db('chaveAntiga', txt(''))), [migrar]),
            call_stmt('gravarDados'),
            IF(NOT(gget('gravacaoOk')),
               [dialog_erro(txt('Erro: não foi possível acessar o armazenamento do aparelho.'))]),
        ]),
    ])


def p_carregarPreferencias():
    """Tema, nome, foto (v1.6) + limites por categoria e lancamentos que se repetem (v1.7), conferindo o formato:
    algo estranho guardado no aparelho e ignorado em vez de travar o app."""
    ler = lambda chave, padrao: cmeth('TinyDB1', 'TinyDB', 'GetValue', txt(chave), txt(padrao))
    o = lambda: lget('o')
    r = lambda i: litem(lget('r'), i)
    # numero inteiro (centavos, dia, mes): um valor quebrado faria formatarMoeda (quociente) dar erro ao abrir o app
    inteiro = lambda x_fn: AND(isnum(x_fn()), eq(mround(x_fn()), x_fn()))
    rec_valido = AND3(lis(lget('r')), cmp('GTE', llen(lget('r')), num(7)),
                      AND3(OR(eq(r(1), txt('Entrada')), eq(r(1), txt('Despesa'))),
                           AND(inteiro(lambda: r(3)), cmp('GT', r(3), num(0))),
                           AND3(inteiro(lambda: r(6)), AND(cmp('GTE', r(6), num(1)), cmp('LTE', r(6), num(31))),
                                AND(inteiro(lambda: r(7)), cmp('GTE', r(7), num(0))))))
    return defnoreturn('carregarPreferencias', [], [
        gset('temaEscuro', eq(ler('tema', 'claro'), txt('escuro'))),
        gset('perfilNome', join(txt(''), ler('perfil_nome', ''))),
        gset('perfilFoto', join(txt(''), ler('perfil_foto', ''))),
        LOCALS_STMT([('o', ler('orcamentos', ''))], [
            gset('orcamentos', mklist(*[num(0) for _ in range(N_CAT)])),
            IF(AND(lis(o()), eq(llen(o()), num(N_CAT))), [
                FOR('i', num(1), num(N_CAT), num(1), [
                    IF(AND(inteiro(lambda: litem(o(), lget('i'))), cmp('GT', litem(o(), lget('i')), num(0))),
                       [lreplace(gget('orcamentos'), lget('i'), litem(o(), lget('i')))]),
                ]),
            ]),
        ]),
        # v1.8: meta = [nome, alvo, prazo, inicio, saldoInicial]; quando foi o ultimo backup e o ultimo lembrete
        LOCALS_STMT([('m', ler('meta', ''))], [
            gset('meta', mklist()),
            IF(AND(lis(lget('m')), eq(llen(lget('m')), num(5))), [
                IF(AND3(AND(inteiro(lambda: litem(lget('m'), 2)), cmp('GT', litem(lget('m'), 2), num(0))),
                        AND(inteiro(lambda: litem(lget('m'), 3)), cmp('GTE', litem(lget('m'), 3), num(0))),
                        AND(inteiro(lambda: litem(lget('m'), 4)), inteiro(lambda: litem(lget('m'), 5)))),
                   [gset('meta', mklist(join(txt(''), litem(lget('m'), 1)), litem(lget('m'), 2), litem(lget('m'), 3),
                                        litem(lget('m'), 4), litem(lget('m'), 5)))]),
            ]),
        ]),
        gset('ultimoBackup', CHOOSE(isnum(ler('ultimo_backup', '0')), ler('ultimo_backup', '0'), num(0))),
        gset('lembreteBackup', CHOOSE(isnum(ler('lembrete_backup', '0')), ler('lembrete_backup', '0'), num(0))),
        LOCALS_STMT([('cn', ler('chaves_notif', ''))], [                       # v2.0
            gset('chavesNotif', mklist()),
            IF(lis(lget('cn')), [FOREACH('c', lget('cn'), [ladd(gget('chavesNotif'), join(txt(''), lget('c')))])]),
        ]),
        LOCALS_STMT([('lido', ler('recorrentes', ''))], [
            gset('recorrentes', mklist()),
            IF(lis(lget('lido')), [
                FOREACH('r', lget('lido'), [IF(rec_valido, [ladd(gget('recorrentes'), lget('r'))])]),
            ]),
        ]),
    ])


def p_carregarListas():
    return defnoreturn('carregarListas', [],
                       [gset(g, mklist(*[comp_ref(n, ctype) for n in nomes])) for g, ctype, nomes in LISTAS_COMP])


def e_initialize():
    return cevent('Screen1', 'Form', 'Initialize', [
        call_stmt('carregarListas'),
        call_stmt('atualizarHoje'),
        gset('periodoChave', gget('chaveHoje')),
        gset('evoAno', quotient(gget('chaveHoje'), num(12))),
        gset('evoMesSel', gget('chaveHoje')),
        gset('metaPrazoEdit', madd(gget('chaveHoje'), num(12))),
        call_stmt('carregarDados'),
        call_stmt('carregarPreferencias'),
        # o desenho da tela ja nasce no tema claro; so repinta ao abrir se a pessoa escolheu o escuro
        IF(gget('temaEscuro'), [call_stmt('aplicarTema')]),
        call_stmt('gerarRecorrentes'),
        call_stmt('atualizarCampos'),
        call_stmt('atualizarFormEdicao'),
        call_stmt('mostrarAba', num(1)),
        call_stmt('atualizarTudo'),
        call_stmt('mostrarPerfil'),
        call_stmt('atualizarRecorrentes'),
        # v1.8
        call_stmt('atualizarCampoData'),
        call_stmt('atualizarMeta'),
        call_stmt('atualizarInfoBackup'),
        call_stmt('lerNotificacoes'),                                           # v2.0
        cmeth('LeitorNotificacoes1', 'LeitorNotificacoes', 'Reconectar'),        # v2.0.1: religa o leitor e rele a barra
        # lembrete de backup: com 10+ lancamentos, sem backup ha mais de 30 dias (ou nunca), no maximo 1 vez por semana,
        # e so se nao houver outro aviso na tela (ex.: repeticoes lancadas agora)
        IF(AND3(cmp('GTE', llen(gget(REG)), num(10)),
                OR(cmp('LTE', gget('ultimoBackup'), num(0)), cmp('GT', call_expr('diasDesde', gget('ultimoBackup')), num(30))),
                AND(OR(cmp('LTE', gget('lembreteBackup'), num(0)), cmp('GTE', call_expr('diasDesde', gget('lembreteBackup')), num(7))),
                    NOT(cget('BoxAviso', 'VerticalArrangement', 'Visible')))), [
            call_stmt('mostrarAviso', boolean(True),
                      CHOOSE(cmp('LTE', gget('ultimoBackup'), num(0)),
                             txt('Dica: faça um backup dos seus lançamentos. Toque no ícone do perfil, no topo, e depois em “Fazer backup”.'),
                             txt('Faz mais de 30 dias do último backup. Toque no ícone do perfil, no topo, e depois em “Fazer backup”.'))),
            LOCALS_STMT([('agora', agora_ms())], [
                cmeth('TinyDB1', 'TinyDB', 'StoreValue', txt('lembrete_backup'), lget('agora')),
                gset('lembreteBackup', lget('agora')),
            ]),
        ]),
    ])


# =========================================================================== eventos v1.7 (diversos)
def e_eventos_v17():
    return [
        cevent('BtnModoMes', 'Button', 'Click', [call_stmt('definirModo', txt('mes'))]),
        cevent('BtnModoAno', 'Button', 'Click', [call_stmt('definirModo', txt('ano'))]),
        cevent('BtnModoTudo', 'Button', 'Click', [call_stmt('definirModo', txt('tudo'))]),
        cevent('BtnPerAnt', 'Button', 'Click', [call_stmt('mudarPeriodo', num(-1))]),
        cevent('BtnPerProx', 'Button', 'Click', [call_stmt('mudarPeriodo', num(1))]),
        cevent('TxtBusca', 'TextBox', 'TextChanged', [call_stmt('atualizarHistorico')]),
        cevent('BtnLimparBusca', 'Button', 'Click', [cset('TxtBusca', 'TextBox', 'Text', txt('')),
                                                       cmeth('TxtBusca', 'TextBox', 'HideKeyboard'),
                                                       call_stmt('atualizarHistorico')]),
        e_historicoToque(),
        cevent('BtnCancelarEdicao', 'Button', 'Click', [call_stmt('cancelarEdicao')]),
        cevent('ImgRepetir', 'Image', 'Click', [gset('repetirSel', NOT(gget('repetirSel'))), call_stmt('atualizarFormEdicao')]),
        cevent('BtnRepetir', 'Button', 'Click', [gset('repetirSel', NOT(gget('repetirSel'))), call_stmt('atualizarFormEdicao')]),
        cevent('BtnLimites', 'Button', 'Click', [call_stmt('abrirLimites')]),
        cevent('BtnLimites2', 'Button', 'Click', [call_stmt('abrirLimites')]),
        cevent('BtnOrcVoltar', 'Button', 'Click', [call_stmt('esconderTecladoOrc'), call_stmt('mostrarAba', gget('abaVoltaOrc'))]),
        e_salvarLimites(),
        e_recorrenteToque(),
        e_exportar(),
        e_backup(),
        e_arquivoSalvo(),
        e_restaurarEscolhido(),
        e_erroOcorreu(),
    ] + e_eventos_evolucao()


PROCS_V17 = [
    'p_chaveMes', 'p_chaveData', 'p_nomeMes', 'p_pad2', 'p_diasNoMes', 'p_noPeriodo', 'p_descPeriodo', 'p_semAcento',
    'p_valorSemRs', 'p_comSinal', 'p_atualizarHoje', 'p_indexarChaves', 'p_atualizarPeriodoUI', 'p_definirModo',
    'p_mudarPeriodo', 'p_abrirMes', 'p_limparFormulario', 'p_iniciarEdicao', 'p_cancelarEdicao',
    'p_atualizarFormEdicao', 'p_gastoNoMes', 'p_avisoLimite', 'p_esconderTecladoOrc', 'p_abrirLimites',
    'p_inserirOrdenado', 'p_gerarRecorrentes', 'p_atualizarRecorrentes', 'p_comparar', 'p_atualizarEvolucao',
    'p_campoCsv', 'p_valorCsv', 'p_mostrarMsgDados', 'p_lerBackup', 'p_aplicarBackup', 'p_carregarListas',
    'p_pintarLinhaCat', 'p_evoResumoMes', 'p_html', 'p_campoIgual', 'p_registroIgual', 'p_listaIgual',
]


# =========================================================================== v1.8
# -*- coding: utf-8 -*-
# Blocos da v1.8 (importar extrato, data do lancamento, meta de economia, lembrete de backup).
# Colado dentro deste gerador, logo antes de GLOBAIS. Usa a DSL da v1.6/v1.7 e SUBSTITUI
# as versoes anteriores das funcoes de mesmo nome. Regra da DSL: um bloco so pode ter UM pai (expressao repetida = lambda).

# =========================================================================== v1.8: DSL nova
def tstarts(t, piece):
    """'starts at' do App Inventor: posicao (1..) do pedaco no texto, 0 se nao tem (indexOf + 1)."""
    return B('text_starts_at', values=[('TEXT', t), ('PIECE', piece)])


def tsplit(t, at):
    """'split' (modo SPLIT): String.split(Pattern.quote(at)) -> vazios do FIM somem."""
    return B('text_split', fields=[('OP', 'SPLIT')], values=[('TEXT', t), ('AT', at)], mut=M(mode='SPLIT'))


def mceil(x):
    return B('math_round', fields=[('OP', 'CEILING')], values=[('NUM', x)])


def agora_ms():
    return cmeth('Clock1', 'Clock', 'SystemTime')


def hoje_txt():
    return cmeth('Clock1', 'Clock', 'FormatDate', agora(), txt('dd/MM/yyyy'))


NOMES_DESC = ['descricao', 'description', 'title', 'titulo', 'historico', 'memo', 'detalhes', 'estabelecimento',
              'lancamento']
MAX_DESC_IMPORT = 200       # descricao importada e cortada aqui (um texto enorme impediria restaurar o backup)
DIA_MS = 86400000

# palavras (minusculas, sem acento) -> categoria; a ordem importa (Compras antes de Alimentacao: "mercado livre")
PALAVRAS_CAT = [
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
for _c, _ws in PALAVRAS_CAT:
    assert _c in [c[0] for c in T.CATEGORIAS], _c
    for _w in _ws:
        assert _w == _w.lower() and not any(ch in _w for ch in ACENTOS) and '|' not in _w, _w

SIG.update({
    'normCab': ['texto'],
    'dividirLinha': ['linha', 'sep'],
    'lerData': ['texto'],
    'lerValor': ['texto'],
    'adivinharCategoria': ['descricao'],
    'adivinharPagamento': ['descricao', 'cartao'],
    'acharNaLista': ['texto', 'lista'],
    'lerExtrato': ['texto'],
    'aplicarImportacao': [],
    'misturar': ['a', 'b'],
    'atualizarCampoData': [],
    'saldoDoMes': ['chave'],
    'atualizarMeta': [],
    'abrirMeta': [],
    'pintarMetaEdit': [],
    'atualizarInfoBackup': [],
    'diasDesde': ['ms'],
    'confirmarExclusao': [],      # v1.8.1
    'confirmarEdicao': [],
    'montarRosca': ['totais', 'ordem'],     # v1.9
    'pedirRosca': [],
    'desenharRosca': [],
    'pintarLinhaCat': ['r', 'c', 'valor', 'lim', 'total'],     # v1.9: sem a barra vermelha, 'maior' nao e mais usado
    'evoResumoMes': ['eA', 'dA', 'eP', 'dP', 'temSel', 'temAnt'],
    'escolherMesEvo': ['chave'],
    'usarFoto': ['caminho'],
    'abrirNotif': [],
})

# v1.9 (pedido do usuario: abas mais enxutas): "Saldo acumulado" e "Ano a ano" sairam da Evolucao -> as listas das barras
# do saldo acumulado deixam de existir; a barra de cada categoria so aparece quando ha limite (lista dos trilhos)
_FORA_V19 = ('compBarA', 'compAcumMes', 'anosLista')
LISTAS_COMP[:] = [x for x in LISTAS_COMP if x[0] not in _FORA_V19]
GLOBAIS_V17[:] = [x for x in GLOBAIS_V17 if x[0] not in _FORA_V19]
LISTAS_COMP.append(('compCatTrilho', 'HorizontalArrangement', ['HzCatTrilho%d' % i for i in range(1, N_CAT + 1)]))

GLOBAIS_V18 = [
    ('modoLeitura', lambda: txt('backup')),
    ('importPendente', lambda: mklist()),
    ('dataSel', lambda: txt('')),
    ('meta', lambda: mklist()),
    ('metaPrazoEdit', lambda: num(0)),
    ('metaSaldoSel', lambda: boolean(False)),
    ('ultimoBackup', lambda: num(0)),
    ('lembreteBackup', lambda: num(0)),
    ('nomesDesc', lambda: tsplit(txt('|'.join(NOMES_DESC)), txt('|'))),
    # cada categoria: [nome, "palavra|palavra|..."] (um texto so: o 'split' acontece na hora de procurar)
    ('palavrasCat', lambda: mklist(*[mklist(txt(c), txt('|'.join(ws))) for c, ws in PALAVRAS_CAT])),
    # v1.8.1: "tem certeza?" ao salvar uma edicao (o tipo escolhido espera a resposta) e as iniciais dos meses (imagens)
    ('edicaoConfirmada', lambda: boolean(False)),
    ('tipoEdicaoPendente', lambda: txt('')),
    ('letrasMes', lambda: tsplit(txt('|'.join(T.LETRAS_MES)), txt('|'))),
    # v1.9: fatias da rosca (valor em centavos e cor), montadas por montarRosca e desenhadas por desenharRosca
    ('roscaValores', lambda: mklist()),
    ('roscaCores', lambda: mklist()),
    ('tentativasRosca', lambda: num(0)),
    # v1.9: cor fixa de cada categoria (1..8), nos dois temas: a fatia da rosca e a bolinha da linha da categoria
    ('coresCatClaro', lambda: mklist(*[rgbh(cl) for cl, _ in T.CORES_CAT])),
    ('coresCatEscuro', lambda: mklist(*[rgbh(es) for _, es in T.CORES_CAT])),
    ('pontosCatClaro', lambda: mklist(*[txt(T.img_ponto_cat(i)) for i in range(1, T.N_CORES_CAT + 1)])),
    ('pontosCatEscuro', lambda: mklist(*[txt(T.img_ponto_cat(i, True)) for i in range(1, T.N_CORES_CAT + 1)])),
    # v1.9: mes escolhido na aba Evolucao (ano*12 + mes-1; comeca no mes atual)
    ('evoMesSel', lambda: num(0)),
    ('compCatTrilho', lambda: mklist()),          # preenchida no Initialize (carregarListas)
]


# =========================================================================== importar extrato: pecas
def p_normCab():
    """Cabecalho/campo para comparar: sem BOM, sem aspas, sem espacos nas pontas, minusculas e sem acento."""
    return defreturn('normCab', ['texto'],
                     call_expr('semAcento', ttrim(treplace(treplace(join(txt(''), lget('texto')), txt('﻿'), txt('')),
                                                           txt('"'), txt('')))))


def p_dividirLinha():
    """Divide uma linha CSV pelo separador. Sem aspas: 'split' (rapido). Com aspas: letra a letra, respeitando
    campos entre aspas e aspas dobradas (""). Nunca para o app com erro (o bloco 'lista de linha CSV' pararia)."""
    L = lget
    c = lambda: L('c')
    return defreturn('dividirLinha', ['linha', 'sep'], LOCALS_EXPR(
        [('campos', mklist()), ('atual', txt('')), ('dentro', boolean(False)), ('i', num(1)), ('c', txt(''))],
        DO_RETURN([
            IF(NOT(tcontains(L('linha'), txt('"'))),
               [lset('campos', tsplit(L('linha'), L('sep')))],
               [WHILE(cmp('LTE', L('i'), tlen(L('linha'))), [
                   lset('c', segment(L('linha'), L('i'), num(1))),
                   IFELIF([
                       (AND(L('dentro'), eq(c(), txt('"'))),
                        [IF(AND(cmp('LT', L('i'), tlen(L('linha'))), eq(segment(L('linha'), madd(L('i'), num(1)), num(1)), txt('"'))),
                            [lset('atual', join(L('atual'), txt('"'))), lset('i', madd(L('i'), num(1)))],
                            [lset('dentro', boolean(False))])]),
                       (L('dentro'), [lset('atual', join(L('atual'), c()))]),
                       (eq(c(), txt('"')), [lset('dentro', boolean(True))]),
                       (eq(c(), L('sep')), [ladd(L('campos'), L('atual')), lset('atual', txt(''))]),
                   ], els=[lset('atual', join(L('atual'), c()))]),
                   lset('i', madd(L('i'), num(1))),
               ]),
                ladd(L('campos'), L('atual'))]),
        ], L('campos'))))


def p_lerData():
    """Data de extrato -> 'dd/MM/aaaa HH:mm' (hora 12:00 se o arquivo nao tem); '' se nao entender.
    Aceita dd/mm/aaaa, dd/mm/aa, aaaa-mm-dd (e com '-' ou '.'), dia e mes com 1 algarismo e hora depois da data."""
    L = lget
    p = lambda i: litem(L('partes'), i)
    num_ok = lambda x_fn: AND(isnum(x_fn()), eq(mround(x_fn()), x_fn()))
    hora_ok = AND3(cmp('GTE', tlen(L('hora')), num(5)), eq(segment(L('hora'), num(3), num(1)), txt(':')),
                   AND(isnum(segment(L('hora'), num(1), num(2))), isnum(segment(L('hora'), num(4), num(2)))))
    return defreturn('lerData', ['texto'], LOCALS_EXPR(
        [('t', ttrim(treplace(join(txt(''), L('texto')), txt('"'), txt('')))), ('hora', txt('12:00')), ('partes', mklist()),
         ('d', num(0)), ('m', num(0)), ('a', num(0)), ('res', txt(''))],
        DO_RETURN([
            # "2026-11-13T10:00:00" -> data e hora separadas por espaco
            IF(AND(cmp('GTE', tlen(L('t')), num(11)), eq(segment(L('t'), num(11), num(1)), txt('T'))),
               [lset('t', join(segment(L('t'), num(1), num(10)), txt(' '), segment(L('t'), num(12), msub(tlen(L('t')), num(11)))))]),
            IF(tcontains(L('t'), txt(' ')), [
                lset('partes', tsplit(L('t'), txt(' '))),
                IF(cmp('GTE', llen(L('partes')), num(2)), [lset('hora', ttrim(litem(L('partes'), 2)))]),
                IF(NOT(hora_ok), [lset('hora', txt('12:00'))], [lset('hora', segment(L('hora'), num(1), num(5)))]),
                lset('t', CHOOSE(cmp('GTE', llen(L('partes')), num(1)), litem(L('partes'), 1), txt(''))),
            ]),
            lset('partes', tsplit(treplace(treplace(L('t'), txt('-'), txt('/')), txt('.'), txt('/')), txt('/'))),
            IF(AND(eq(llen(L('partes')), num(3)),
                   AND3(num_ok(lambda: p(1)), num_ok(lambda: p(2)), num_ok(lambda: p(3)))), [
                IF(eq(tlen(p(1)), num(4)),
                   [lset('a', p(1)), lset('m', p(2)), lset('d', p(3))],
                   [lset('d', p(1)), lset('m', p(2)), lset('a', p(3))]),
                IF(cmp('LT', L('a'), num(100)), [lset('a', madd(L('a'), num(2000)))]),
                IF(AND3(AND(cmp('GTE', L('a'), num(1900)), cmp('LTE', L('a'), num(2200))),
                        AND(cmp('GTE', L('m'), num(1)), cmp('LTE', L('m'), num(12))),
                        AND(cmp('GTE', L('d'), num(1)),
                            cmp('LTE', L('d'), call_expr('diasNoMes', madd(mmul(L('a'), num(12)), msub(L('m'), num(1))))))), [
                    lset('res', join(call_expr('pad2', madd(num(0), L('d'))), txt('/'), call_expr('pad2', madd(num(0), L('m'))),
                                     txt('/'), madd(num(0), L('a')), txt(' '), L('hora'))),
                ]),
            ]),
        ], L('res'))))


def p_lerValor():
    """Valor de extrato -> centavos COM SINAL (inteiro); '' se nao entender. Aceita 'R$', espacos, 1.234,56 / 1234.56 /
    1,234.56, sinal - no comeco ou no fim, (12,00) e 'D'/'C' no fim (debito/credito)."""
    L = lget
    t = lambda: L('t')
    ultimo = lambda: segment(t(), tlen(t()), num(1))
    tira_fim = lambda: lset('t', ttrim(segment(t(), num(1), msub(tlen(t()), num(1)))))
    tira_ini = lambda: lset('t', ttrim(segment(t(), num(2), msub(tlen(t()), num(1)))))
    conta = lambda ch: msub(tlen(t()), tlen(treplace(t(), txt(ch), txt(''))))
    partes_virg = lambda: tsplit(t(), txt(','))
    return defreturn('lerValor', ['texto'], LOCALS_EXPR(
        [('t', ttrim(treplace(treplace(treplace(treplace(join(txt(''), L('texto')), txt('"'), txt('')), txt('R$'), txt('')),
                                       txt(' '), txt('')), txt(' '), txt('')))),
         ('neg', boolean(False)), ('res', txt(''))],
        DO_RETURN([
            IF(cmp('GTE', tlen(t()), num(2)), [
                IFELIF([(OR(eq(ultimo(), txt('D')), eq(ultimo(), txt('d'))), [lset('neg', boolean(True)), tira_fim()]),
                        (OR(eq(ultimo(), txt('C')), eq(ultimo(), txt('c'))), [tira_fim()])]),
            ]),
            IF(AND3(cmp('GTE', tlen(t()), num(3)), eq(segment(t(), num(1), num(1)), txt('(')), eq(ultimo(), txt(')'))),
               [lset('neg', boolean(True)), tira_ini(), tira_fim()]),
            IF(cmp('GTE', tlen(t()), num(2)), [
                IFELIF([(eq(segment(t(), num(1), num(1)), txt('-')), [lset('neg', NOT(L('neg'))), tira_ini()]),
                        (eq(ultimo(), txt('-')), [lset('neg', NOT(L('neg'))), tira_fim()]),
                        (eq(segment(t(), num(1), num(1)), txt('+')), [tira_ini()])]),
            ]),
            IFELIF([
                # os dois: o que vem por ultimo e o separador dos centavos
                (AND(tcontains(t(), txt(',')), tcontains(t(), txt('.'))),
                 [IF(tcontains(litem(partes_virg(), llen(partes_virg())), txt('.')),
                     [lset('t', treplace(t(), txt(','), txt('')))],
                     [lset('t', treplace(treplace(t(), txt('.'), txt('')), txt(','), txt('.')))])]),
                (tcontains(t(), txt(',')),
                 [IF(cmp('GT', conta(','), num(1)), [lset('t', treplace(t(), txt(','), txt('')))],
                     [lset('t', treplace(t(), txt(','), txt('.')))])]),
                (tcontains(t(), txt('.')),
                 [IF(OR(cmp('GT', conta('.'), num(1)),
                        eq(tlen(litem(tsplit(t(), txt('.')), llen(tsplit(t(), txt('.'))))), num(3))),
                     [lset('t', treplace(t(), txt('.'), txt('')))])]),
            ]),
            IF(AND(NOT(tempty(t())), isnum(t())), [
                lset('res', mround(mmul(t(), num(100)))),
                IF(L('neg'), [lset('res', msub(num(0), L('res')))]),
            ]),
        ], L('res'))))


def p_adivinharCategoria():
    """Categoria pela descricao (palavras conhecidas); 'Outros' se nenhuma combinar."""
    L = lget
    return defreturn('adivinharCategoria', ['descricao'], LOCALS_EXPR(
        [('d', join(txt(' '), call_expr('semAcento', L('descricao')), txt(' '))), ('res', txt(''))],
        DO_RETURN([
            FOREACH('par', gget('palavrasCat'), [
                IF(tempty(L('res')), [
                    FOREACH('palavra', tsplit(litem(L('par'), 2), txt('|')), [
                        IF(AND(tempty(L('res')), tcontains(L('d'), L('palavra'))), [lset('res', litem(L('par'), 1))]),
                    ]),
                ]),
            ]),
        ], CHOOSE(tempty(L('res')), txt('Outros'), L('res')))))


def p_adivinharPagamento():
    L = lget
    tem = lambda w: tcontains(L('d'), txt(w))
    return defreturn('adivinharPagamento', ['descricao', 'cartao'], LOCALS_EXPR(
        [('d', join(txt(' '), call_expr('semAcento', L('descricao')), txt(' ')))],
        CHOOSE(L('cartao'), txt('Cartão de crédito'),
               CHOOSE(tem('pix'), txt('Pix'),
                      CHOOSE(OR(tem('debito'), tem('compra cartao')), txt('Cartão de débito'),
                             CHOOSE(AND(tem('cartao'), tem('credito')), txt('Cartão de crédito'),
                                    CHOOSE(tem('saque'), txt('Dinheiro'), txt('Transferência bancária'))))))))


def p_acharNaLista():
    """Item da lista que e igual ao texto sem diferenca de maiuscula/acento; '' se nenhum."""
    L = lget
    return defreturn('acharNaLista', ['texto', 'lista'], LOCALS_EXPR(
        [('alvo', call_expr('normCab', L('texto'))), ('res', txt(''))],
        DO_RETURN([
            FOREACH('item', L('lista'), [
                IF(AND(tempty(L('res')), eq(call_expr('semAcento', L('item')), L('alvo'))), [lset('res', L('item'))]),
            ]),
        ], L('res'))))


def p_misturar():
    """Junta duas listas de lancamentos ja em ordem (mais novo primeiro) numa so, em ordem; empate: a de 'a' primeiro."""
    L = lget
    ca = lambda: call_expr('chaveData', litem(litem(L('a'), L('i')), 4))
    cb = lambda: call_expr('chaveData', litem(litem(L('b'), L('j')), 4))
    return defreturn('misturar', ['a', 'b'], LOCALS_EXPR(
        [('res', mklist()), ('i', num(1)), ('j', num(1))],
        DO_RETURN([
            WHILE(AND(cmp('LTE', L('i'), llen(L('a'))), cmp('LTE', L('j'), llen(L('b')))), [
                IF(cmp('GTE', ca(), cb()),
                   [ladd(L('res'), litem(L('a'), L('i'))), lset('i', madd(L('i'), num(1)))],
                   [ladd(L('res'), litem(L('b'), L('j'))), lset('j', madd(L('j'), num(1)))]),
            ]),
            WHILE(cmp('LTE', L('i'), llen(L('a'))), [ladd(L('res'), litem(L('a'), L('i'))), lset('i', madd(L('i'), num(1)))]),
            WHILE(cmp('LTE', L('j'), llen(L('b'))), [ladd(L('res'), litem(L('b'), L('j'))), lset('j', madd(L('j'), num(1)))]),
        ], L('res'))))


# =========================================================================== importar extrato: leitura


def p_lerExtrato():
    """Le um extrato CSV de banco/planilha: acha o cabecalho (data + valor ou credito/debito), le cada linha, deixa de
    fora o que ja esta no app e mostra quantos vai importar. Nada muda ate a pessoa tocar em 'Importar'."""
    L = lget
    cel = lambda i_fn: CHOOSE(AND(cmp('GT', i_fn(), num(0)), cmp('LTE', i_fn(), llen(L('cs')))),
                              ttrim(litem(L('cs'), i_fn())), txt(''))
    nc = lambda: L('nc')
    comeca = lambda w: eq(tstarts(nc(), txt(w)), num(1))
    conta = lambda ch: msub(tlen(L('linha')), tlen(treplace(L('linha'), txt(ch), txt(''))))
    hoje_num = lambda: madd(num(0), cmeth('Clock1', 'Clock', 'FormatDate', agora(), txt('yyyyMMdd')))
    data_num = lambda: madd(mmul(segment(L('data'), num(7), num(4)), num(10000)), mmul(segment(L('data'), num(4), num(2)), num(100)),
                            segment(L('data'), num(1), num(2)))
    chave_rec = lambda r_fn: join(segment(litem(r_fn(), 4), num(1), num(10)), txt('|'), litem(r_fn(), 1), txt('|'),
                                   litem(r_fn(), 3), txt('|'), call_expr('semAcento', litem(r_fn(), 2)))
    plural = lambda n_fn, um, varios: CHOOSE(eq(n_fn(), num(1)), txt(um), txt(varios))

    acha_colunas = [
        lset('iData', num(0)), lset('iDesc', num(0)), lset('rDesc', num(99)), lset('iValor', num(0)), lset('iCred', num(0)),
        lset('iDeb', num(0)), lset('iTipo', num(0)), lset('iCat', num(0)), lset('iPag', num(0)), lset('temTitle', boolean(False)),
        FOR('k', num(1), llen(L('cs')), num(1), [
            lset('nc', call_expr('normCab', litem(L('cs'), L('k')))),
            IFELIF([
                (AND(eq(L('iData'), num(0)), OR3(comeca('data'), eq(nc(), txt('date')), eq(nc(), txt('dt')))),
                 [lset('iData', L('k'))]),
                (AND(eq(L('iValor'), num(0)), AND(OR3(comeca('valor'), eq(nc(), txt('amount')), OR(eq(nc(), txt('value')), eq(nc(), txt('quantia')))),
                                                  NOT(tcontains(nc(), txt('saldo'))))),
                 [lset('iValor', L('k'))]),
                (AND(eq(L('iCred'), num(0)), OR3(comeca('credito'), comeca('entrada'), eq(nc(), txt('credit')))),
                 [lset('iCred', L('k'))]),
                (AND(eq(L('iDeb'), num(0)), OR3(comeca('debito'), comeca('saida'), eq(nc(), txt('debit')))),
                 [lset('iDeb', L('k'))]),
                (AND(eq(L('iTipo'), num(0)), OR(eq(nc(), txt('tipo')), comeca('tipo '))), [lset('iTipo', L('k'))]),
                (AND(eq(L('iCat'), num(0)), OR(eq(nc(), txt('categoria')), eq(nc(), txt('category')))), [lset('iCat', L('k'))]),
                (AND(eq(L('iPag'), num(0)), OR(eq(nc(), txt('pagamento')), comeca('forma de pagamento'))), [lset('iPag', L('k'))]),
            ]),
            IF(eq(nc(), txt('title')), [lset('temTitle', boolean(True))]),
            # descricao: o nome mais provavel ganha (descricao > title > historico > ... > lancamento)
            FOR('r', num(1), num(len(NOMES_DESC)), num(1), [
                IF(AND(cmp('LT', L('r'), L('rDesc')),
                       OR(eq(nc(), litem(gget('nomesDesc'), L('r'))), eq(tstarts(nc(), litem(gget('nomesDesc'), L('r'))), num(1)))),
                   [lset('rDesc', L('r')), lset('iDesc', L('k'))]),
            ]),
        ]),
    ]

    le_linha = [
        lset('cs', call_expr('dividirLinha', L('linha'), L('sep'))),
        lset('data', call_expr('lerData', cel(lambda: L('iData')))),
        lset('v', txt('')),
        IFELIF([(cmp('GT', L('iValor'), num(0)), [lset('v', call_expr('lerValor', cel(lambda: L('iValor'))))])],
               # credito/debito em colunas separadas: o valor de credito vale positivo e o de debito negativo
               # (o que nao for numero fica '' e a linha conta como "nao entendida")
               els=[IF(NOT(tempty(cel(lambda: L('iCred')))), [
                        lset('v', call_expr('lerValor', cel(lambda: L('iCred')))),
                        IF(isnum(L('v')), [lset('v', mabs(L('v')))])]),
                    IF(AND(OR(tempty(L('v')), eq(L('v'), num(0))), NOT(tempty(cel(lambda: L('iDeb'))))), [
                        lset('v', call_expr('lerValor', cel(lambda: L('iDeb')))),
                        IF(isnum(L('v')), [lset('v', msub(num(0), mabs(L('v'))))])])]),
        IFELIF([
            # linha de informacao (ex.: "SALDO DO DIA" sem valor na coluna de valor): fica de fora sem contar como erro
            (AND(NOT(tempty(L('data'))), AND3(tempty(cel(lambda: L('iValor'))), tempty(cel(lambda: L('iCred'))),
                                              tempty(cel(lambda: L('iDeb'))))), []),
            (OR(tempty(L('data')), tempty(L('v'))),
             [lset('ruins', madd(L('ruins'), num(1))),
              IF(eq(L('primeiraRuim'), num(0)), [lset('primeiraRuim', L('n'))])]),
            (eq(L('v'), num(0)), [lset('ruins', madd(L('ruins'), num(1))),
                                  IF(eq(L('primeiraRuim'), num(0)), [lset('primeiraRuim', L('n'))])]),
            (cmp('GT', data_num(), hoje_num()), [lset('futuros', madd(L('futuros'), num(1)))]),
        ], els=[
            lset('desc', ttrim(cel(lambda: L('iDesc')))),
            # a planilha do proprio Conto protege "=..." com um apostrofo: tira
            IF(AND(cmp('GTE', tlen(L('desc')), num(2)), eq(segment(L('desc'), num(1), num(1)), txt("'"))),
               [IF(tcontains(txt('=+-@'), segment(L('desc'), num(2), num(1))),
                   [lset('desc', segment(L('desc'), num(2), msub(tlen(L('desc')), num(1))))])]),
            IF(tempty(L('desc')), [lset('desc', txt('Sem descrição'))]),
            IF(cmp('GT', tlen(L('desc')), num(MAX_DESC_IMPORT)), [lset('desc', segment(L('desc'), num(1), num(MAX_DESC_IMPORT)))]),
            # tipo: coluna "tipo" se houver; senao o sinal (fatura de cartao: positivo = compra)
            lset('tipo', txt('')),
            IF(cmp('GT', L('iTipo'), num(0)), [
                lset('nc', call_expr('normCab', cel(lambda: L('iTipo')))),
                IFELIF([(OR3(comeca('entrada'), comeca('credito'), OR(comeca('receita'), eq(nc(), txt('c')))), [lset('tipo', txt('Entrada'))]),
                        (OR3(comeca('despesa'), comeca('saida'), OR(comeca('debito'), eq(nc(), txt('d')))), [lset('tipo', txt('Despesa'))])]),
            ]),
            IF(tempty(L('tipo')), [
                IFELIF([(L('cartao'),
                         [IF(cmp('GT', L('v'), num(0)), [lset('tipo', txt('Despesa'))],
                             [IF(tcontains(call_expr('semAcento', L('desc')), txt('estorno')), [lset('tipo', txt('Entrada'))])])])],
                       els=[lset('tipo', CHOOSE(cmp('LT', L('v'), num(0)), txt('Despesa'), txt('Entrada')))]),
            ]),
            IFELIF([(tempty(L('tipo')), [lset('pagFatura', madd(L('pagFatura'), num(1)))])], els=[
                lset('cat', CHOOSE(cmp('GT', L('iCat'), num(0)), call_expr('acharNaLista', cel(lambda: L('iCat')), gget('listaCats')), txt(''))),
                IF(tempty(L('cat')), [lset('cat', CHOOSE(eq(L('tipo'), txt('Entrada')), txt('Outros'),
                                                         call_expr('adivinharCategoria', L('desc'))))]),
                lset('pag', CHOOSE(cmp('GT', L('iPag'), num(0)), call_expr('acharNaLista', cel(lambda: L('iPag')), gget('listaPags')), txt(''))),
                IF(tempty(L('pag')), [lset('pag', call_expr('adivinharPagamento', L('desc'), L('cartao')))]),
                lset('reg', mklist(L('tipo'), L('desc'), mabs(L('v')), L('data'), L('cat'), L('pag'))),
                # ja esta no app? (mesma data, tipo, valor e descricao) -> pula, e "gasta" aquele do app
                lset('ch', join(txt('\\n'), chave_rec(lambda: L('reg')), txt('\\n'))),
                lset('pos', tstarts(L('pool'), L('ch'))),
                IFELIF([(cmp('GT', L('pos'), num(0)),
                         [lset('repetidos', madd(L('repetidos'), num(1))),
                          lset('pool', join(segment(L('pool'), num(1), L('pos')),
                                            CHOOSE(cmp('GT', tlen(L('pool')), msub(madd(L('pos'), tlen(L('ch'))), num(1))),
                                                   segment(L('pool'), madd(L('pos'), tlen(L('ch'))),
                                                           msub(tlen(L('pool')), msub(madd(L('pos'), tlen(L('ch'))), num(1)))),
                                                   txt(''))))])],
                       els=[
                    # v2.0: o mesmo gasto ja lancado pela NOTIFICACAO (descricao diferente: dia, tipo e valor iguais)
                    lset('ch', join(txt('\\n'), call_expr('chaveCurta', L('reg')), txt('\\n'))),
                    lset('pos', tstarts(L('poolN'), L('ch'))),
                    IFELIF([(cmp('GT', L('pos'), num(0)),
                             [lset('daNotif', madd(L('daNotif'), num(1))),
                              lset('poolN', join(segment(L('poolN'), num(1), L('pos')),
                                                 segment(L('poolN'), madd(L('pos'), tlen(L('ch'))),
                                                         madd(msub(tlen(L('poolN')), madd(L('pos'), tlen(L('ch')))), num(1)))))])],
                           els=[ladd(L('novos'), L('reg'))]),
                ]),
            ]),
        ]),
    ]

    # os novos em ordem (mais novo primeiro): extrato costuma vir em ordem (crescente ou decrescente)
    ordenar = [
        IF(AND(cmp('GTE', llen(L('novos')), num(2)),
               cmp('LT', call_expr('chaveData', litem(litem(L('novos'), 1), 4)),
                   call_expr('chaveData', litem(litem(L('novos'), llen(L('novos'))), 4)))), [
            lset('inv', mklist()),
            FOR('k', llen(L('novos')), num(1), num(-1), [ladd(L('inv'), litem(L('novos'), L('k')))]),
            lset('novos', L('inv')),
        ]),
        lset('inv', mklist()),
        FOREACH('r', L('novos'), [
            lset('cd', call_expr('chaveData', litem(L('r'), 4))),
            lset('pos', llen(L('inv'))),
            WHILE(AND(cmp('GTE', L('pos'), num(1)), cmp('LT', call_expr('chaveData', litem(litem(L('inv'), L('pos')), 4)), L('cd'))),
                  [lset('pos', msub(L('pos'), num(1)))]),
            IF(cmp('GTE', L('pos'), llen(L('inv'))), [ladd(L('inv'), L('r'))], [linsert(L('inv'), madd(L('pos'), num(1)), L('r'))]),
        ]),
        lset('novos', L('inv')),
    ]

    resumo_ruins = lambda: CHOOSE(cmp('GT', L('ruins'), num(0)),
                                  join(txt('<br>'), L('ruins'), plural(lambda: L('ruins'), ' linha não foi entendida e fica de fora',
                                                                        ' linhas não foram entendidas e ficam de fora'),
                                       CHOOSE(eq(L('ruins'), num(1)), txt(' (linha '), txt(' (a primeira: linha ')),
                                       L('primeiraRuim'), txt(').')), txt(''))
    resumo_outros = lambda: join(
        CHOOSE(cmp('GT', L('repetidos'), num(0)),
               join(txt('<br>'), L('repetidos'), plural(lambda: L('repetidos'), ' já estava no app e será pulado.', ' já estavam no app e serão pulados.')),
               txt('')),
        CHOOSE(cmp('GT', L('daNotif'), num(0)),
               join(txt('<br>'), L('daNotif'), plural(lambda: L('daNotif'), ' já foi lançado pela notificação do banco e será pulado.',
                                                       ' já foram lançados pelas notificações do banco e serão pulados.')),
               txt('')),
        CHOOSE(cmp('GT', L('futuros'), num(0)),
               join(txt('<br>'), L('futuros'), plural(lambda: L('futuros'), ' agendado para depois de hoje fica de fora.',
                                                       ' agendados para depois de hoje ficam de fora.')), txt('')),
        CHOOSE(cmp('GT', L('pagFatura'), num(0)),
               join(txt('<br>'), L('pagFatura'), plural(lambda: L('pagFatura'), ' pagamento da fatura fica de fora (não é gasto novo).',
                                                         ' pagamentos da fatura ficam de fora (não são gastos novos).')), txt('')),
        resumo_ruins())
    n_ent = lambda: L('nEnt')
    n_desp = lambda: msub(llen(L('novos')), L('nEnt'))
    d_ini = lambda: segment(litem(litem(L('novos'), llen(L('novos'))), 4), num(1), num(10))
    d_fim = lambda: segment(litem(litem(L('novos'), 1), 4), num(1), num(10))
    datas_txt = lambda: CHOOSE(eq(d_ini(), d_fim()), join(txt('em '), d_fim()), join(txt('de '), d_ini(), txt(' a '), d_fim()))

    variaveis = [('t', join(txt(''), L('texto'))), ('linhas', mklist()), ('linha', txt('')), ('sep', txt(',')), ('cs', mklist()),
                 ('nc', txt('')), ('h', num(0)), ('iData', num(0)), ('iDesc', num(0)), ('rDesc', num(99)),
                 ('iValor', num(0)), ('iCred', num(0)), ('iDeb', num(0)), ('iTipo', num(0)), ('iCat', num(0)), ('iPag', num(0)),
                 ('temTitle', boolean(False)), ('cartao', boolean(False)),
                 ('data', txt('')), ('v', txt('')), ('desc', txt('')), ('tipo', txt('')), ('cat', txt('')), ('pag', txt('')),
                 ('reg', mklist()), ('ch', txt('')), ('pos', num(0)), ('pool', txt('\\n')), ('novos', mklist()), ('inv', mklist()),
                 ('cd', num(0)), ('ruins', num(0)), ('primeiraRuim', num(0)), ('repetidos', num(0)), ('futuros', num(0)),
                 ('pagFatura', num(0)), ('nEnt', num(0)), ('poolN', txt('\\n')), ('daNotif', num(0))]
    return defnoreturn('lerExtrato', ['texto'], [
        gset('importPendente', mklist()),
        LOCALS_STMT(variaveis, [
            lset('t', treplace(treplace(L('t'), txt('\\r\\n'), txt('\\n')), txt('\\r'), txt('\\n'))),
            lset('linhas', tsplit(L('t'), txt('\\n'))),
            # cabecalho: uma das 20 primeiras linhas com data e valor (ou credito/debito)
            FOR('n', num(1), mmin(lambda: llen(L('linhas')), lambda: num(20)), num(1), [
                IF(eq(L('h'), num(0)), [
                    lset('linha', litem(L('linhas'), L('n'))),
                    lset('sep', CHOOSE(AND(cmp('GT', conta(';'), num(0)), cmp('GTE', conta(';'), conta(','))), txt(';'),
                                       CHOOSE(cmp('GT', conta('\\t'), conta(',')), txt('\\t'), txt(',')))),
                    lset('cs', call_expr('dividirLinha', L('linha'), L('sep'))),
                ] + acha_colunas + [
                    IF(AND(cmp('GT', L('iData'), num(0)), OR3(cmp('GT', L('iValor'), num(0)), cmp('GT', L('iCred'), num(0)),
                                                              cmp('GT', L('iDeb'), num(0)))),
                       [lset('h', L('n'))]),
                ]),
            ]),
            IFELIF([(eq(L('h'), num(0)),
                     [call_stmt('mostrarMsgDados', boolean(False),
                                txt('Não reconheci este arquivo. Ele precisa ser uma planilha CSV com colunas de data e valor '
                                    '(no Excel: Salvar como → CSV).'))])], els=[
                # fatura de cartao no estilo Nubank (date, title, amount): positivo = compra
                lset('cartao', AND3(L('temTitle'), cmp('GT', L('iValor'), num(0)), eq(L('iTipo'), num(0)))),
                # o que ja esta no app, uma chave por lancamento: "\n chave \n chave \n ..."
                FOREACH('r', gget(REG), [lset('pool', join(L('pool'), chave_rec(lambda: L('r')), txt('\\n')))]),
                # v2.0: os lancamentos que vieram das notificacoes (e ainda estao no app), pela chave curta
                FOREACH('r', gget(REG), [
                    IF(cmp('GT', lpos(call_expr('chaveCurta', L('r')), gget('chavesNotif')), num(0)),
                       [lset('poolN', join(L('poolN'), call_expr('chaveCurta', L('r')), txt('\\n')))]),
                ]),
                FOR('n', madd(L('h'), num(1)), llen(L('linhas')), num(1), [
                    lset('linha', litem(L('linhas'), L('n'))),
                    # linha vazia (ou so separadores) e ignorada sem contar como erro
                    IF(NOT(tempty(ttrim(treplace(treplace(treplace(L('linha'), txt(';'), txt('')), txt(','), txt('')),
                                                 txt('\\t'), txt(''))))), le_linha),
                ]),
            ] + ordenar + [
                FOREACH('r', L('novos'), [IF(eq(litem(L('r'), 1), txt('Entrada')), [lset('nEnt', madd(L('nEnt'), num(1)))])]),
                IFELIF([(eq(llen(L('novos')), num(0)),
                         [call_stmt('mostrarMsgDados', boolean(False),
                                    join(txt('Não encontrei lançamentos novos neste arquivo.'),
                                         CHOOSE(cmp('GT', L('repetidos'), num(0)),
                                                join(txt(' '), L('repetidos'), plural(lambda: L('repetidos'), ' já estava no app.', ' já estavam no app.')),
                                                txt('')),
                                         CHOOSE(cmp('GT', L('daNotif'), num(0)),
                                                join(txt(' '), L('daNotif'), plural(lambda: L('daNotif'), ' já veio pela notificação do banco.',
                                                                                     ' já vieram pelas notificações do banco.')),
                                                txt('')),
                                         CHOOSE(cmp('GT', L('ruins'), num(0)),
                                                join(txt(' '), L('ruins'), plural(lambda: L('ruins'), ' linha não foi entendida.', ' linhas não foram entendidas.')),
                                                txt(''))))])], els=[
                    gset('importPendente', L('novos')),
                    cmeth('Notifier1', 'Notifier', 'ShowChooseDialog',
                          join(txt('Encontrei '), llen(L('novos')), plural(lambda: llen(L('novos')), ' lançamento novo', ' lançamentos novos'),
                               txt(', '), datas_txt(), txt(': '), n_ent(), plural(n_ent, ' entrada', ' entradas'), txt(' e '),
                               n_desp(), plural(n_desp, ' despesa.', ' despesas.'), resumo_outros(),
                               # uma frase certa para 1 ou varios, e que diz de onde veio a categoria (coluna do arquivo ou descricao)
                               CHOOSE(eq(llen(L('novos')), num(1)), txt('<br><br>Ele será somado aos que você já tem. '),
                                      txt('<br><br>Eles serão somados aos que você já tem. ')),
                               CHOOSE(cmp('GT', L('iCat'), num(0)),
                                      CHOOSE(eq(llen(L('novos')), num(1)),
                                             txt('A categoria veio do arquivo (ou da descrição, se faltava); dá para corrigir no Histórico.'),
                                             txt('As categorias vieram do arquivo (ou da descrição, quando faltavam); dá para corrigir no Histórico.')),
                                      CHOOSE(eq(llen(L('novos')), num(1)),
                                             txt('A categoria foi escolhida pela descrição; dá para corrigir no Histórico.'),
                                             txt('A categoria de cada um foi escolhida pela descrição; dá para corrigir no Histórico.')))),
                          txt('Importar extrato?'), txt('Importar'), txt('Cancelar'), boolean(False)),
                ]),
            ]),
        ]),
    ])


def p_aplicarImportacao():
    return defnoreturn('aplicarImportacao', [], [
        IF(cmp('GT', llen(gget('importPendente')), num(0)), [
            LOCALS_STMT([('antigos', gget(REG)), ('n', llen(gget('importPendente')))], [
                gset(REG, call_expr('misturar', gget(REG), gget('importPendente'))),
                invalidar_chaves(),
                call_stmt('gravarDados'),
                IF(NOT(gget('gravacaoOk')),
                   [gset(REG, lget('antigos')),
                    invalidar_chaves(),
                    call_stmt('atualizarTudo'),
                    call_stmt('mostrarMsgDados', boolean(False), txt('Não foi possível importar: o aparelho não deixou gravar. Nada mudou.'))],
                   [call_stmt('atualizarTudo'),
                    call_stmt('mostrarMsgDados', boolean(True),
                              join(lget('n'), CHOOSE(eq(lget('n'), num(1)), txt(' lançamento importado.'), txt(' lançamentos importados.')),
                                   txt(' Confira as categorias no Histórico (toque em um lançamento para editar).')))]),
            ]),
        ]),
        gset('importPendente', mklist()),
    ])


def e_importarEscolhido():
    sel = lambda: cget('PickerImportar', 'FilePicker', 'Selection')
    return cevent('PickerImportar', 'FilePicker', 'AfterPicking', [
        IF(NOT(tempty(sel())), [
            gset('modoLeitura', txt('extrato')),
            call_stmt('mostrarMsgDados', boolean(True), txt('Lendo o extrato…')),
            cmeth('File1', 'File', 'ReadFrom', sel()),
        ]),
    ])


def e_restaurarEscolhido():
    sel = lambda: cget('PickerRestaurar', 'FilePicker', 'Selection')
    return cevent('PickerRestaurar', 'FilePicker', 'AfterPicking', [
        IF(NOT(tempty(sel())), [
            gset('modoLeitura', txt('backup')),
            call_stmt('mostrarMsgDados', boolean(True), txt('Lendo o backup…')),
            cmeth('File1', 'File', 'ReadFrom', sel()),
        ]),
    ])


def e_textoLido():
    return cevent('File1', 'File', 'GotText', [
        IF(eq(gget('modoLeitura'), txt('extrato')), [call_stmt('lerExtrato', evparam('text'))],
           [call_stmt('lerBackup', evparam('text'))]),
    ])


# =========================================================================== data do lancamento
def inserir_em_ordem(reg_fn):
    """Coloca o lancamento antes do primeiro que nao e mais novo que ele (empate: o novo fica em cima, como antes).
    Usa a variavel local 'pos'."""
    cd = lambda: call_expr('chaveData', litem(reg_fn(), 4))
    return [lset('pos', num(1)),
            WHILE(AND(cmp('LTE', lget('pos'), llen(gget(REG))),
                      cmp('GT', call_expr('chaveData', litem(litem(gget(REG), lget('pos')), 4)), cd())),
                  [lset('pos', madd(lget('pos'), num(1)))]),
            IF(cmp('GT', lget('pos'), llen(gget(REG))), [ladd(gget(REG), reg_fn())], [linsert(gget(REG), lget('pos'), reg_fn())])]


def p_atualizarCampoData():
    """'Hoje, 13/11/2026' / 'Ontem, 12/11/2026' / '05/11/2026' no campo de data."""
    ontem = lambda: cmeth('Clock1', 'Clock', 'FormatDate', cmeth('Clock1', 'Clock', 'AddDays', agora(), num(-1)), txt('dd/MM/yyyy'))
    return defnoreturn('atualizarCampoData', [], [
        cset('PickerData', 'DatePicker', 'Text',
             CHOOSE(OR(tempty(gget('dataSel')), eq(gget('dataSel'), hoje_txt())), join(txt('Hoje, '), hoje_txt()),
                    CHOOSE(eq(gget('dataSel'), ontem()), join(txt('Ontem, '), gget('dataSel')), gget('dataSel')))),
    ])


def e_dataEscolhida():
    """A pessoa escolheu um dia no calendario. Depois de hoje nao vale (aviso embaixo do campo)."""
    y = lambda: cget('PickerData', 'DatePicker', 'Year')
    m = lambda: cget('PickerData', 'DatePicker', 'Month')
    d = lambda: cget('PickerData', 'DatePicker', 'Day')
    hoje_num = lambda: madd(num(0), cmeth('Clock1', 'Clock', 'FormatDate', agora(), txt('yyyyMMdd')))
    return cevent('PickerData', 'DatePicker', 'AfterDateSet', [
        IF(cmp('GT', madd(mmul(y(), num(10000)), mmul(m(), num(100)), d()), hoje_num()),
           [cset('LblErroData', 'Label', 'Text', txt('A data não pode ser depois de hoje.')),
            cset('LblErroData', 'Label', 'Visible', boolean(True)),
            cset('HzCampoData', 'HorizontalArrangement', 'Image', gimg('CampoSelErro'))],
           [cset('LblErroData', 'Label', 'Visible', boolean(False)),
            cset('HzCampoData', 'HorizontalArrangement', 'Image', gimg('CampoSel')),
            gset('dataSel', join(call_expr('pad2', d()), txt('/'), call_expr('pad2', m()), txt('/'), y())),
            # "hoje" num lancamento NOVO vira '' (= a hora de agora). v1.8.1: numa EDICAO '' quer dizer "manter a data
            # antiga" -- escolher hoje para um lancamento de outro dia nao mudava a data (o campo dizia "Hoje" e o
            # lancamento continuava no dia antigo). Na edicao a data escolhida fica como foi escolhida.
            IF(AND(eq(gget('dataSel'), hoje_txt()), NOT(cmp('GT', gget('editIndice'), num(0)))), [gset('dataSel', txt(''))]),
            call_stmt('atualizarCampoData')]),
    ])


def p_limparFormulario():
    return defnoreturn('limparFormulario', [], [
        cset('TxtDescricao', 'TextBox', 'Text', txt('')),
        cset('TxtValor', 'TextBox', 'Text', txt('')),
        gset('categoriaSel', txt('')),
        gset('pagamentoSel', txt('')),
        gset('categoriaIcone', txt('')),
        gset('pagamentoIcone', txt('')),
        gset('repetirSel', boolean(False)),
        # v1.8: data volta para "hoje" (e o calendario abre em hoje)
        gset('dataSel', txt('')),
        cmeth('PickerData', 'DatePicker', 'SetDateToDisplay',
              cmeth('Clock1', 'Clock', 'Year', agora()), cmeth('Clock1', 'Clock', 'Month', agora()),
              cmeth('Clock1', 'Clock', 'DayOfMonth', agora())),
        cset('LblErroData', 'Label', 'Visible', boolean(False)),
        cset('HzCampoData', 'HorizontalArrangement', 'Image', gimg('CampoSel')),
        call_stmt('atualizarCampoData'),
        call_stmt('atualizarCampos'),
    ])


def p_iniciarEdicao():
    item = lambda i: litem(litem(gget(REG), lget('indice')), i)
    data = lambda: join(txt(''), item(4))
    return defnoreturn('iniciarEdicao', ['indice'], [
        IF(AND(cmp('GTE', lget('indice'), num(1)), cmp('LTE', lget('indice'), llen(gget(REG)))), [
            gset('editIndice', lget('indice')),
            call_stmt('limparErros'),
            cset('TxtDescricao', 'TextBox', 'Text', CHOOSE(eq(item(2), txt('Sem descrição')), txt(''), join(txt(''), item(2)))),
            cset('TxtValor', 'TextBox', 'Text', call_expr('valorSemRs', item(3))),
            gset('categoriaSel', join(txt(''), item(5))),
            gset('pagamentoSel', join(txt(''), item(6))),
            LOCALS_STMT([('pc', lpos(item(5), gget('listaCats'))), ('pp', lpos(item(6), gget('listaPags')))], [
                gset('categoriaIcone', CHOOSE(cmp('GT', lget('pc'), num(0)), litem(gget('listaCatIcones'), lget('pc')), txt(''))),
                gset('pagamentoIcone', CHOOSE(cmp('GT', lget('pp'), num(0)), litem(gget('listaPagIcones'), lget('pp')), txt(''))),
            ]),
            gset('repetirSel', boolean(False)),
            # v1.8: a data do lancamento aparece no campo (e pode ser mudada)
            gset('dataSel', txt('')),
            IF(cmp('GT', call_expr('chaveData', data()), num(0)), [
                gset('dataSel', segment(data(), num(1), num(10))),
                cmeth('PickerData', 'DatePicker', 'SetDateToDisplay', madd(num(0), segment(data(), num(7), num(4))),
                      madd(num(0), segment(data(), num(4), num(2))), madd(num(0), segment(data(), num(1), num(2)))),
            ]),
            IF(eq(gget('dataSel'), hoje_txt()), [gset('dataSel', txt(''))]),
            cset('LblErroData', 'Label', 'Visible', boolean(False)),
            cset('HzCampoData', 'HorizontalArrangement', 'Image', gimg('CampoSel')),
            call_stmt('atualizarCampoData'),
            call_stmt('atualizarCampos'),
            call_stmt('atualizarFormEdicao'),
            call_stmt('mostrarAba', num(1)),
        ]),
    ])


# =========================================================================== meta de economia
def p_saldoDoMes():
    item = lambda i: litem(litem(gget(REG), lget('i')), i)
    return defreturn('saldoDoMes', ['chave'], LOCALS_EXPR([('soma', num(0))], DO_RETURN([
        garantir_chaves(),
        FOR('i', num(1), llen(gget(REG)), num(1), [
            IF(eq(chave_reg(lambda: lget('i')), lget('chave')),
               [lset('soma', CHOOSE(eq(item(1), txt('Entrada')), madd(lget('soma'), item(3)), msub(lget('soma'), item(3))))]),
        ]),
    ], lget('soma'))))


def p_atualizarMeta():
    """Cartao 'Sua meta' (Evolucao) e cartao pequeno (Lancar). meta = [nome, alvo, prazo, inicio, saldoInicial]."""
    L = lget
    mt = lambda i: litem(gget('meta'), i)
    tem = lambda: eq(llen(gget('meta')), num(5))
    guardado = lambda: msub(gget('saldoTotal'), mt(5))
    pct100 = lambda: L('pct')
    faltam = lambda: msub(mt(2), guardado())
    meses_rest = lambda: madd(msub(mt(3), gget('chaveHoje')), num(1))
    return defnoreturn('atualizarMeta', [], [
        cset('PnlMetaAtiva', 'VerticalArrangement', 'Visible', tem()),
        cset('BtnMetaEditar', 'Button', 'Visible', tem()),
        cset('BtnCriarMeta', 'Button', 'Visible', NOT(tem())),
        cset('LblSubMeta', 'Label', 'Visible', NOT(tem())),
        cset('PnlMetaMini', 'HorizontalArrangement', 'Visible', tem()),
        IF(tem(), [LOCALS_STMT([('pct', num(0)), ('media', num(0)), ('chegada', num(0))], [
            # porcentagem guardada (0..100, inteira, para baixo: 99,6% ainda nao e 100%)
            lset('pct', mmin(lambda: num(100), lambda: mmax(lambda: num(0), lambda: B('math_round', fields=[('OP', 'FLOOR')],
                                                                                         values=[('NUM', mdiv(mmul(guardado(), num(100)), mt(2)))])))),
            cset('LblMetaNome', 'Label', 'Text', mt(1)),
            cset('LblMetaGuardado', 'Label', 'Text', join(fmt(mmax(lambda: num(0), guardado)), txt(' de '), fmt(mt(2)))),
            cset('LblMetaPct', 'Label', 'Text', join(pct100(), txt('%'))),
            cset('BarMeta', 'Label', 'Visible', cmp('GT', pct100(), num(0))),
            IF(cmp('GT', pct100(), num(0)), [cset('BarMeta', 'Label', 'WidthPercent', mround(mdiv(mmul(pct100(), num(86)), num(100))))]),
            cset('LblMetaMini', 'Label', 'Text', join(mt(1), txt('  •  '), pct100(), txt('%'))),
            cset('LblMetaMiniSub', 'Label', 'Text', join(fmt(mmax(lambda: num(0), guardado)), txt(' de '), fmt(mt(2)))),
            cset('BarMetaMini', 'Label', 'Visible', cmp('GT', pct100(), num(0))),
            IF(cmp('GT', pct100(), num(0)), [cset('BarMetaMini', 'Label', 'WidthPercent', mround(mdiv(mmul(pct100(), num(50)), num(100))))]),
            cset('LblMetaRitmo', 'Label', 'TextColor', gcor('Suave')),
            IFELIF([
                (cmp('GTE', guardado(), mt(2)),
                 [cset('LblMetaPrazo', 'Label', 'Text', join(txt('Meta alcançada! Você juntou '), fmt(guardado()), txt('.'))),
                  cset('LblMetaRitmo', 'Label', 'Text', txt('Parabéns! Toque em Editar para escolher a próxima meta.')),
                  cset('LblMetaRitmo', 'Label', 'TextColor', gcor('Bom'))]),
                (cmp('LT', mt(3), gget('chaveHoje')),
                 [cset('LblMetaPrazo', 'Label', 'Text', join(txt('O prazo ('), call_expr('nomeMes', mt(3)), txt(') já passou. Faltaram '),
                                                              fmt(faltam()), txt('.'))),
                  cset('LblMetaRitmo', 'Label', 'Text', txt('Toque em Editar para escolher um novo prazo.'))]),
            ], els=[
                cset('LblMetaPrazo', 'Label', 'Text',
                     join(txt('Faltam '), fmt(faltam()), txt(' até '), call_expr('nomeMes', mt(3)), txt(': guarde cerca de '),
                          fmt(mceil(mdiv(faltam(), meses_rest()))), txt(' por mês.'))),
                # ritmo: media do saldo dos 3 meses completos anteriores
                lset('media', mround(mdiv(madd(call_expr('saldoDoMes', msub(gget('chaveHoje'), num(1))),
                                               call_expr('saldoDoMes', msub(gget('chaveHoje'), num(2))),
                                               call_expr('saldoDoMes', msub(gget('chaveHoje'), num(3)))), num(3)))),
                IFELIF([
                    (cmp('GT', L('media'), num(0)),
                     [lset('chegada', msub(madd(gget('chaveHoje'), mceil(mdiv(faltam(), L('media')))), num(1))),
                      cset('LblMetaRitmo', 'Label', 'Text',
                           join(txt('No ritmo dos últimos 3 meses ('), fmt(L('media')), txt(' por mês), você chega lá em '),
                                call_expr('nomeMes', L('chegada')), txt('.'))),
                      cset('LblMetaRitmo', 'Label', 'TextColor', CHOOSE(cmp('LTE', L('chegada'), mt(3)), gcor('Bom'), gcor('Alerta')))]),
                    (cmp('LT', L('media'), num(0)),
                     [cset('LblMetaRitmo', 'Label', 'Text', txt('Nos últimos 3 meses saiu mais do que entrou: nesse ritmo a meta não avança.')),
                      cset('LblMetaRitmo', 'Label', 'TextColor', gcor('Alerta'))]),
                ], els=[cset('LblMetaRitmo', 'Label', 'Text', txt('Ainda não dá para calcular seu ritmo: faltam lançamentos dos últimos meses.'))]),
            ]),
        ])]),
    ])


def p_pintarMetaEdit():
    return defnoreturn('pintarMetaEdit', [], [
        cset('LblMetaPrazoEdit', 'Label', 'Text', call_expr('nomeMes', gget('metaPrazoEdit'))),
        cset('ImgMetaSaldo', 'Image', 'Picture', CHOOSE(gget('metaSaldoSel'), gimg('CheckOn'), gimg('CheckOff'))),
        cset('BtnMetaSaldo', 'Button', 'Text', join(txt('Incluir meu saldo atual ('), fmt(gget('saldoTotal')), txt(')'))),
        cset('BtnPrazoAnt', 'Button', 'Enabled', cmp('GT', gget('metaPrazoEdit'), gget('chaveHoje'))),
        cset('BtnPrazoProx', 'Button', 'Enabled', cmp('LT', gget('metaPrazoEdit'), madd(gget('chaveHoje'), num(120)))),
        # v1.8.1: a seta e imagem; no limite ela some (imagem transparente), como as setas do periodo
        cset('BtnPrazoAnt', 'Button', 'Image', CHOOSE(cmp('GT', gget('metaPrazoEdit'), gget('chaveHoje')), gimg('SetaEsq'), gimg('Nada'))),
        cset('BtnPrazoProx', 'Button', 'Image', CHOOSE(cmp('LT', gget('metaPrazoEdit'), madd(gget('chaveHoje'), num(120))),
                                                       gimg('SetaDir'), gimg('Nada'))),
    ])


def p_abrirMeta():
    mt = lambda i: litem(gget('meta'), i)
    tem = lambda: eq(llen(gget('meta')), num(5))
    return defnoreturn('abrirMeta', [], [
        cset('TxtMetaNome', 'TextBox', 'Text', CHOOSE(tem(), mt(1), txt(''))),
        cset('TxtMetaValor', 'TextBox', 'Text', CHOOSE(tem(), call_expr('valorSemRs', mt(2)), txt(''))),
        gset('metaPrazoEdit', CHOOSE(tem(), mmax(lambda: mt(3), lambda: gget('chaveHoje')), madd(gget('chaveHoje'), num(12)))),
        gset('metaSaldoSel', AND(tem(), eq(mt(5), num(0)))),
        cset('LblErroMetaValor', 'Label', 'Visible', boolean(False)),
        cset('HzCampoMetaValor', 'HorizontalArrangement', 'Image', gimg('Campo')),
        cset('BtnRemoverMeta', 'Button', 'Visible', tem()),
        cset('LblTituloMetaEdit', 'Label', 'Text', CHOOSE(tem(), txt('Editar meta'), txt('Nova meta de economia'))),
        call_stmt('pintarMetaEdit'),
        call_stmt('mostrarAba', num(7)),
    ])


def e_salvarMeta():
    mt = lambda i: litem(gget('meta'), i)
    tem = lambda: eq(llen(gget('meta')), num(5))
    valor_txt = lambda: ttrim(cget('TxtMetaValor', 'TextBox', 'Text'))
    nome = lambda: ttrim(cget('TxtMetaNome', 'TextBox', 'Text'))
    erro = lambda msg: [cset('LblErroMetaValor', 'Label', 'Text', txt(msg)), cset('LblErroMetaValor', 'Label', 'Visible', boolean(True)),
                        cset('HzCampoMetaValor', 'HorizontalArrangement', 'Image', gimg('CampoErro'))]
    return cevent('BtnSalvarMeta', 'Button', 'Click', [
        cmeth('TxtMetaNome', 'TextBox', 'HideKeyboard'),
        cmeth('TxtMetaValor', 'TextBox', 'HideKeyboard'),
        cset('LblErroMetaValor', 'Label', 'Visible', boolean(False)),
        cset('HzCampoMetaValor', 'HorizontalArrangement', 'Image', gimg('Campo')),
        LOCALS_STMT([('v', call_expr('paraCentavos', valor_txt())), ('nova', mklist())], [
            IFELIF([
                (tempty(valor_txt()), erro('Informe quanto você quer juntar.')),
                (cmp('LT', lget('v'), num(0)), erro('Valor inválido. Use vírgula nos centavos: 5.000,00.')),
                (eq(lget('v'), num(0)), erro('Digite um valor maior que zero.')),
            ], els=[
                lset('nova', mklist(
                    CHOOSE(tempty(nome()), txt('Minha meta'),
                           CHOOSE(cmp('GT', tlen(nome()), num(40)), segment(nome(), num(1), num(40)), nome())),
                    lget('v'),
                    gget('metaPrazoEdit'),
                    CHOOSE(tem(), mt(4), gget('chaveHoje')),
                    # 0 = conta tudo o que ja tem; senao conta a partir do saldo de hoje (editar mantem o ponto de partida)
                    CHOOSE(gget('metaSaldoSel'), num(0),
                           CHOOSE(AND(tem(), neq(mt(5), num(0))), mt(5), gget('saldoTotal'))))),
                cmeth('TinyDB1', 'TinyDB', 'StoreValue', txt('meta'), lget('nova')),
                IF(call_expr('registroIgual', cmeth('TinyDB1', 'TinyDB', 'GetValue', txt('meta'), txt('')), lget('nova')),
                   [gset('meta', lget('nova')),
                    call_stmt('atualizarMeta'),
                    call_stmt('mostrarAba', num(5))],
                   erro('Não foi possível salvar a meta neste aparelho. Tente de novo.')),
            ]),
        ]),
    ])


def e_eventos_meta():
    voltar = [cmeth('TxtMetaNome', 'TextBox', 'HideKeyboard'), cmeth('TxtMetaValor', 'TextBox', 'HideKeyboard'),
              call_stmt('mostrarAba', num(5))]
    alternar = lambda: [gset('metaSaldoSel', NOT(gget('metaSaldoSel'))), call_stmt('pintarMetaEdit')]
    return [
        cevent('BtnCriarMeta', 'Button', 'Click', [call_stmt('abrirMeta')]),
        cevent('BtnMetaEditar', 'Button', 'Click', [call_stmt('abrirMeta')]),
        cevent('BtnMetaMini', 'Button', 'Click', [call_stmt('mostrarAba', num(5))]),
        cevent('BtnMetaVoltar', 'Button', 'Click', voltar),
        cevent('BtnPrazoAnt', 'Button', 'Click',
               [gset('metaPrazoEdit', mmax(lambda: gget('chaveHoje'), lambda: msub(gget('metaPrazoEdit'), num(1)))),
                call_stmt('pintarMetaEdit')]),
        cevent('BtnPrazoProx', 'Button', 'Click',
               [gset('metaPrazoEdit', mmin(lambda: madd(gget('chaveHoje'), num(120)), lambda: madd(gget('metaPrazoEdit'), num(1)))),
                call_stmt('pintarMetaEdit')]),
        cevent('ImgMetaSaldo', 'Image', 'Click', alternar()),
        cevent('BtnMetaSaldo', 'Button', 'Click', alternar()),
        e_salvarMeta(),
        cevent('BtnRemoverMeta', 'Button', 'Click', [
            cmeth('Notifier1', 'Notifier', 'ShowChooseDialog',
                  join(txt('A meta “'), call_expr('html', litem(gget('meta'), 1)), txt('” será removida. Seus lançamentos não mudam.')),
                  txt('Remover meta?'), txt('Remover meta'), txt('Cancelar'), boolean(False)),
        ]),
    ]


# =========================================================================== lembrete de backup
def p_diasDesde():
    """Dias de CALENDARIO entre o instante guardado (ms desde 1970) e hoje. Compara o meio-dia LOCAL de cada um dos
    dois dias (Clock.MakeInstantFromParts usa o fuso do aparelho): backup ontem as 23h, visto hoje as 8h = 1 dia
    ("ontem"), e nao 0 como daria contar periodos de 24 h. Um horario de verao so desloca 1 h e o arredondamento
    absorve. Instante no futuro (relogio mexido) = 0."""
    def meio_dia(inst_fn):
        return cmeth('Clock1', 'Clock', 'GetMillis',
                     cmeth('Clock1', 'Clock', 'MakeInstantFromParts',
                           cmeth('Clock1', 'Clock', 'Year', inst_fn()), cmeth('Clock1', 'Clock', 'Month', inst_fn()),
                           cmeth('Clock1', 'Clock', 'DayOfMonth', inst_fn()), num(12), num(0), num(0)))
    hoje = lambda: cmeth('Clock1', 'Clock', 'Now')
    entao = lambda: cmeth('Clock1', 'Clock', 'MakeInstantFromMillis', lget('ms'))
    return defreturn('diasDesde', ['ms'], LOCALS_EXPR(
        [('d', mround(mdiv(msub(meio_dia(hoje), meio_dia(entao)), num(DIA_MS))))],
        CHOOSE(cmp('LT', lget('d'), num(0)), num(0), lget('d'))))


def p_atualizarInfoBackup():
    dias = lambda: call_expr('diasDesde', gget('ultimoBackup'))
    return defnoreturn('atualizarInfoBackup', [], [
        cset('LblBackupInfo', 'Label', 'TextColor', gcor('Suave')),
        IFELIF([
            (cmp('LTE', gget('ultimoBackup'), num(0)), [cset('LblBackupInfo', 'Label', 'Text', txt('Você ainda não fez backup.'))]),
            (eq(dias(), num(0)), [cset('LblBackupInfo', 'Label', 'Text', txt('Último backup: hoje.'))]),
            (eq(dias(), num(1)), [cset('LblBackupInfo', 'Label', 'Text', txt('Último backup: ontem.'))]),
        ], els=[cset('LblBackupInfo', 'Label', 'Text', join(txt('Último backup: há '), dias(), txt(' dias.'),
                                                             CHOOSE(cmp('GT', dias(), num(30)), txt(' Que tal fazer um agora?'), txt('')))),
                IF(cmp('GT', dias(), num(30)), [cset('LblBackupInfo', 'Label', 'TextColor', gcor('Alerta'))])]),
    ])


def e_erroOcorreu():
    """Erros dos componentes (Screen1.ErrorOccurred). v1.8:
    - 4501 (FilePicker.resultReturned sem Intent): e o que o Android devolve quando a pessoa CANCELA o seletor de
      arquivos (Voltar). Nao e erro: nada a avisar. Na v1.7 o "Restaurar backup" cancelado dizia "Nao foi possivel
      concluir com este arquivo" e, com o seletor novo do extrato fora da lista, o App Inventor mostraria
      "No URI returned to FilePicker" num aviso preto.
    - o seletor do extrato conta como erro de arquivo (aviso no cartao, como os outros).
    - PickerData (SetDateToDisplay com data impossivel, so possivel com um backup editado a mao): o calendario so
      deixa de pre-selecionar o dia; nada de aviso tecnico."""
    c = lambda: evparam('component')
    nosso = OR(OR3(eq(c(), comp_ref('File1', 'File')), eq(c(), comp_ref('Sharing1', 'Sharing')),
                   eq(c(), comp_ref('PickerRestaurar', 'FilePicker'))),
               eq(c(), comp_ref('PickerImportar', 'FilePicker')))
    return cevent('Screen1', 'Form', 'ErrorOccurred', [
        IFELIF([
            (eq(evparam('errorNumber'), num(4501)), []),
            (eq(c(), comp_ref('PickerData', 'DatePicker')), []),
            (nosso, [call_stmt('mostrarMsgDados', boolean(False), txt('Não foi possível concluir com este arquivo. Tente de novo.'))]),
            # v1.9: camera -- 908 = permissao negada (Form.PermissionDenied sem manipulador vira ErrorOccurred 908);
            # 201 = a camera nao devolveu foto; 704/705 = armazenamento indisponivel. Nada de aviso tecnico.
            (eq(c(), comp_ref('CameraFoto', 'Camera')),
             [call_stmt('mostrarMsgPerfil', boolean(False),
                        CHOOSE(eq(evparam('errorNumber'), num(908)),
                               txt('Sem permissão para usar a câmera. Você pode liberar a câmera para o Contô nas configurações do celular ou escolher uma foto da galeria.'),
                               txt('Não foi possível usar a foto da câmera. Tente de novo ou escolha uma foto da galeria.')))]),
        ], els=[cmeth('Notifier1', 'Notifier', 'ShowAlert', evparam('message'))]),
    ])


def e_arquivoSalvo():
    eh_backup = lambda: tcontains(evparam('fileName'), txt('Conto_backup_'))
    return cevent('File1', 'File', 'AfterFileSaved', [
        call_stmt('mostrarMsgDados', boolean(True), txt('Pronto! Escolha onde salvar ou para quem enviar o arquivo.')),
        # v1.8: guarda quando foi o ultimo backup (para o lembrete)
        IF(eh_backup(), [
            LOCALS_STMT([('agora', agora_ms())], [
                cmeth('TinyDB1', 'TinyDB', 'StoreValue', txt('ultimo_backup'), lget('agora')),
                gset('ultimoBackup', lget('agora')),
                call_stmt('atualizarInfoBackup'),
            ]),
        ]),
        cmeth('Sharing1', 'Sharing', 'ShareFile', evparam('fileName')),
    ])


def p_mostrarAba():
    """1 Lancar, 2 Historico, 3 Grafico, 4 Perfil, 5 Evolucao, 6 Limites, 7 Meta, 8 Notificacoes do banco (v2.0).
    Periodo so no Historico e no Grafico."""
    ativa = lambda n: cmp('EQ', lget('aba'), num(n))
    return defnoreturn('mostrarAba', ['aba'], [
        gset('abaAtual', lget('aba')),
        cmeth('TxtBusca', 'TextBox', 'HideKeyboard'),
        cset('PnlLancar', 'VerticalArrangement', 'Visible', ativa(1)),
        cset('PnlPicker', 'VerticalArrangement', 'Visible', boolean(False)),
        cset('PnlHistorico', 'VerticalArrangement', 'Visible', ativa(2)),
        cset('PnlGrafico', 'VerticalArrangement', 'Visible', ativa(3)),
        cset('PnlPerfil', 'VerticalArrangement', 'Visible', ativa(4)),
        cset('PnlEvolucao', 'VerticalArrangement', 'Visible', ativa(5)),
        cset('PnlOrcamento', 'VerticalArrangement', 'Visible', ativa(6)),
        cset('PnlMeta', 'VerticalArrangement', 'Visible', ativa(7)),
        cset('PnlNotif', 'VerticalArrangement', 'Visible', ativa(8)),      # v2.0
        cset('PnlPeriodo', 'VerticalArrangement', 'Visible', OR(ativa(2), ativa(3))),
        call_stmt('pintarAbas'),
        IF(ativa(3), [call_stmt('atualizarGrafico')]),
        IF(ativa(4), [call_stmt('atualizarRecorrentes'), call_stmt('atualizarInfoBackup')]),
        IF(ativa(5), [call_stmt('atualizarEvolucao'), call_stmt('atualizarMeta')]),
        # v1.8: o app pode ficar aberto de um dia para o outro (o App Inventor nao avisa quando ele volta); ao voltar
        # para o Lancar, "Hoje" e o calendario acompanham a data de agora (se nenhuma data foi escolhida)
        IF(ativa(1), [IF(tempty(gget('dataSel')), [
            cmeth('PickerData', 'DatePicker', 'SetDateToDisplay',
                  cmeth('Clock1', 'Clock', 'Year', agora()), cmeth('Clock1', 'Clock', 'Month', agora()),
                  cmeth('Clock1', 'Clock', 'DayOfMonth', agora()))]),
            call_stmt('atualizarCampoData')]),
    ])


# =========================================================================== v1.8.1: "tem certeza?"
def _data_curta(x):
    """dd/mm/aaaa de um 'dd/MM/yyyy HH:mm' (texto menor que 10 fica inteiro: segmento fora do texto seria erro)."""
    t = lambda: join(txt(''), x())
    return CHOOSE(cmp('GTE', tlen(t()), num(10)), segment(t(), num(1), num(10)), t())


def p_confirmarExclusao():
    """Antes de excluir: mostra o lancamento e so exclui no "Sim, excluir" (um toque sem querer nao apaga nada)."""
    sel = lambda: gget('indiceSel')
    item = lambda i: litem(litem(gget('lancamentos'), sel()), i)
    return defnoreturn('confirmarExclusao', [], [
        IF(AND(cmp('GTE', sel(), num(1)), cmp('LTE', sel(), llen(gget('lancamentos')))), [
            cmeth('Notifier1', 'Notifier', 'ShowChooseDialog',
                  join(txt('“'), call_expr('html', item(2)), txt('”<br>'), CHOOSE(eq(item(1), txt('Entrada')), txt('+ '), txt('− ')),
                       fmt(item(3)), txt(' • '), _data_curta(lambda: item(4)), txt('<br><br>Isso não pode ser desfeito.')),
                  txt('Excluir lançamento?'), txt('Sim, excluir'), txt('Cancelar'), boolean(False)),
        ]),
    ])


def p_confirmarEdicao():
    """Antes de gravar uma edicao: mostra como o lancamento vai ficar; "Salvar" grava, "Voltar" continua editando."""
    desc = lambda: CHOOSE(tempty(ttrim(cget('TxtDescricao', 'TextBox', 'Text'))), txt('Sem descrição'),
                          ttrim(cget('TxtDescricao', 'TextBox', 'Text')))
    ant4 = lambda: litem(litem(gget('lancamentos'), gget('editIndice')), 4)
    return defnoreturn('confirmarEdicao', [], [
        cmeth('Notifier1', 'Notifier', 'ShowChooseDialog',
              join(txt('“'), call_expr('html', desc()), txt('”<br>'),
                   CHOOSE(eq(gget('tipoEdicaoPendente'), txt('Entrada')), txt('+ '), txt('− ')), fmt(gget('valorCentavos')),
                   txt(' • '), gget('categoriaSel'), txt('<br>'), gget('pagamentoSel'), txt(' • '),
                   CHOOSE(tempty(gget('dataSel')), _data_curta(ant4), gget('dataSel'))),
              txt('Salvar alterações?'), txt('Salvar'), txt('Voltar'), boolean(False)),
    ])


def e_removerFoto():
    """v1.8.1: remover a foto pergunta antes (quem remove e o "Remover foto" da janela, em Notifier1.AfterChoosing)."""
    return cevent('BtnRemoverFoto', 'Button', 'Click', [
        cmeth('Notifier1', 'Notifier', 'ShowChooseDialog',
              txt('A foto sai do seu perfil no Contô. Nenhuma foto é apagada do celular.'),
              txt('Remover foto?'), txt('Remover foto'), txt('Cancelar'), boolean(False)),
    ])


def e_eventos_v18():
    return ([e_importarEscolhido(), e_textoLido(), e_dataEscolhida()] + e_eventos_meta() + [e_timerRosca()] + e_eventos_foto()
            + e_eventos_notif())


# =========================================================================== v1.9: rosca "Gastos por categoria"
ROSCA_A = T.ROSCA_ANEL // 2                  # o traco do arco fica centrado na linha da oval: recua meia espessura
ROSCA_B = T.ROSCA_LADO - T.ROSCA_ANEL // 2


def p_atualizarGrafico():
    """v1.9: cartao "Gastos por categoria" do PERIODO: total de despesas, entradas e saldo. A rosca e a lista das
    categorias sao montadas em atualizarCategorias, que ja soma e ordena as categorias. ("Ultimos lancamentos" saiu
    da aba a pedido do usuario: os lancamentos estao no Historico.)"""
    modo = lambda v: eq(gget('periodoModo'), txt(v))
    s = lambda: lget('s')
    return defnoreturn('atualizarGrafico', [], [
        cset('LblSubGraf', 'Label', 'Text', join(txt('Total de gastos em '), call_expr('descPeriodo'))),
        cset('LblLegDespValor', 'Label', 'Text', fmt(gget('totalDespesas'))),
        cset('LblLegEntValor', 'Label', 'Text', fmt(gget('totalEntradas'))),
        LOCALS_STMT([('s', msub(gget('totalEntradas'), gget('totalDespesas')))], [
            cset('LblLegSaldoNome', 'Label', 'Text',
                 CHOOSE(modo('mes'), txt('Saldo do mês'), CHOOSE(modo('ano'), txt('Saldo do ano'), txt('Saldo total')))),
            cset('LblLegSaldoValor', 'Label', 'Text', call_expr('comSinal', s())),
            cset('LblLegSaldoValor', 'Label', 'TextColor',
                 CHOOSE(cmp('GT', s(), num(0)), gcor('Bom'), CHOOSE(cmp('LT', s(), num(0)), gcor('Perigo'), gcor('Texto')))),
        ]),
        call_stmt('atualizarCategorias'),
    ])


def p_pintarLinhaCat():
    """v1.9: uma linha da lista do cartao "Gastos por categoria" (r = linha 1..8 na tela, c = categoria): bolinha na
    cor da fatia da categoria (tema atual), nome e valor. Com limite (lim > 0): barra = parte do limite ja usada (verde;
    amarela a partir de 80%; vermelha se passou) e o texto do limite. Sem limite: so a porcentagem das despesas (a rosca
    ja mostra o tamanho de cada categoria; a barra vermelha da v1.6 saiu)."""
    L = lget
    comp = lambda lista: litem(gget(lista), L('r'))
    valor = lambda: L('valor')
    lim = lambda: L('lim')
    pct_lim = lambda: mround(mdiv(mmul(valor(), num(100)), lim()))
    passou = lambda: cmp('GT', valor(), lim())
    alerta = lambda: cmp('GTE', mmul(valor(), num(100)), mmul(lim(), num(80)))
    pontos = lambda: CHOOSE(gget('temaEscuro'), gget('pontosCatEscuro'), gget('pontosCatClaro'))
    com_limite = [
        gcset('HorizontalArrangement', 'Visible', comp('compCatTrilho'), boolean(True)),
        gcset('Label', 'WidthPercent', comp('compCatBarra'),
              CHOOSE(cmp('GTE', valor(), lim()), num(T.BARRA_MAX), call_expr('larguraBarra', valor(), lim()))),
        gcset('Label', 'BackgroundColor', comp('compCatBarra'),
              CHOOSE(passou(), gcor('BarraEstouro'), CHOOSE(alerta(), gcor('BarraAlerta'), gcor('BarraOk')))),
        gcset('Label', 'TextColor', comp('compCatPct'), CHOOSE(passou(), gcor('Perigo'), CHOOSE(alerta(), gcor('Alerta'), gcor('Suave')))),
        gcset('Label', 'Text', comp('compCatPct'),
              CHOOSE(passou(), join(txt('Passou '), fmt(msub(valor(), lim())), txt(' do limite ('), fmt(lim()), txt(')')),
                     join(pct_lim(), txt('% de '), fmt(lim()), txt('  •  sobram '), fmt(msub(lim(), valor()))))),
    ]
    sem_limite = [
        gcset('HorizontalArrangement', 'Visible', comp('compCatTrilho'), boolean(False)),
        gcset('Label', 'TextColor', comp('compCatPct'), gcor('Suave')),
        gcset('Label', 'Text', comp('compCatPct'),
              join(call_expr('formatarPercentual', CHOOSE(cmp('GT', L('total'), num(0)),
                                                           mround(mdiv(mmul(valor(), num(1000)), L('total'))), num(0))),
                   txt(' das despesas'))),
    ]
    return defnoreturn('pintarLinhaCat', ['r', 'c', 'valor', 'lim', 'total'], [
        gcset('Image', 'Picture', comp('compImgCat'), litem(pontos(), L('c'))),
        gcset('Label', 'Text', comp('compCatNome'), litem(gget('listaCats'), L('c'))),
        gcset('Label', 'Text', comp('compCatValor'), fmt(valor())),
        IF(cmp('GT', lim(), num(0)), com_limite, sem_limite),
        gcset('VerticalArrangement', 'Visible', comp('compPnlCat'), boolean(True)),
    ])


def p_atualizarCategorias():
    """Despesas do periodo por categoria, da maior para a menor (empate: ordem da lista). No modo Mes as categorias com
    limite aparecem mesmo sem gasto (a linha mostra quanto do limite ja foi usado). Cada linha: pintarLinhaCat; no fim,
    as fatias da rosca (montarRosca). v1.9: a lista e a legenda da rosca, no mesmo cartao."""
    L = lget
    item = lambda i: litem(L('item'), i)
    somas = ['s%d' % i for i in range(1, N_CAT + 1)]
    mes = lambda: eq(gget('periodoModo'), txt('mes'))
    acumular = FOR('i', num(1), llen(gget(REG)), num(1), [
        IF(call_expr('noPeriodo', chave_reg(lambda: L('i'))), [
            lset('item', litem(gget(REG), L('i'))),
            IF(neq(item(1), txt('Entrada')), [
                LOCALS_STMT([('k', call_expr('indiceCategoria', item(5)))], [
                    IFELIF([(cmp('EQ', L('k'), num(i + 1)), [lset(somas[i], madd(L(somas[i]), item(3)))]) for i in range(N_CAT)]),
                ]),
            ]),
        ]),
    ])
    lim_de = lambda idx_fn: CHOOSE(mes(), litem(gget('orcamentos'), idx_fn()), num(0))
    candidato = lambda: OR(cmp('GT', L('t'), num(0)), cmp('GT', lim_de(lambda: L('i')), num(0)))
    ordenar = FOR('k', num(1), num(N_CAT), num(1), [
        lset('melhor', num(0)),
        lset('melhorVal', num(-1)),
        FOR('i', num(1), num(N_CAT), num(1), [
            LOCALS_STMT([('t', litem(L('totais'), L('i')))], [
                IF(AND(candidato(),
                       OR(cmp('LT', L('t'), L('antVal')),
                          AND(cmp('EQ', L('t'), L('antVal')), cmp('GT', L('i'), L('antIdx'))))), [
                    IF(cmp('GT', L('t'), L('melhorVal')), [lset('melhor', L('i')), lset('melhorVal', L('t'))]),
                ]),
            ]),
        ]),
        IF(cmp('GT', L('melhor'), num(0)), [
            ladd(L('ordem'), L('melhor')),
            lset('antVal', L('melhorVal')),
            lset('antIdx', L('melhor')),
        ]),
    ])
    c = lambda: litem(L('ordem'), L('r'))
    linhas = FOR('r', num(1), num(N_CAT), num(1), [
        IF(cmp('GTE', llen(L('ordem')), L('r')),
           [call_stmt('pintarLinhaCat', L('r'), c(), litem(L('totais'), c()), lim_de(c), L('total'))],
           [gcset('VerticalArrangement', 'Visible', litem(gget('compPnlCat'), L('r')), boolean(False))]),
    ])
    corpo = [
        garantir_chaves(),
        acumular,
        lset('totais', mklist(*[L(n) for n in somas])),
        lset('total', madd(*[L(n) for n in somas])),
        lset('antVal', madd(L('total'), num(1))),
        ordenar,
        cset('PnlCats', 'VerticalArrangement', 'Visible', cmp('GT', llen(L('ordem')), num(0))),
        linhas,
        call_stmt('montarRosca', L('totais'), L('ordem')),
    ]
    decl = [(n, num(0)) for n in somas] + [('totais', mklist()), ('total', num(0)), ('ordem', mklist()),
                                           ('antVal', num(0)), ('antIdx', num(0)), ('melhor', num(0)), ('melhorVal', num(0)),
                                           ('item', mklist())]
    return defnoreturn('atualizarCategorias', [], [LOCALS_STMT(decl, corpo)])


def p_montarRosca():
    """v1.9: fatias da rosca = as categorias com gasto no periodo, na ordem que atualizarCategorias calculou (da maior
    para a menor; empate na ordem da lista), cada uma na cor FIXA da categoria (coresCatClaro/Escuro pelo tema atual).
    A troca de tema refaz tudo (pintarEstados -> atualizarTudo), entao as cores acompanham o tema. Sem despesas no
    periodo: aviso no lugar da lista e a rosca vira um anel cinza. O desenho e pedido ao ClockRosca."""
    L = lget
    cores = lambda: CHOOSE(gget('temaEscuro'), gget('coresCatEscuro'), gget('coresCatClaro'))
    return defnoreturn('montarRosca', ['totais', 'ordem'], [
        gset('roscaValores', mklist()),
        gset('roscaCores', mklist()),
        FOREACH('c', L('ordem'), [
            IF(cmp('GT', litem(L('totais'), L('c')), num(0)), [
                ladd(gget('roscaValores'), litem(L('totais'), L('c'))),
                ladd(gget('roscaCores'), litem(cores(), L('c'))),
            ]),
        ]),
        cset('LblVazioGraf', 'Label', 'Visible', eq(llen(gget('roscaValores')), num(0))),
        cset('LblVazioGraf', 'Label', 'Text',
             CHOOSE(eq(llen(gget(REG)), num(0)), txt('Sem dados ainda. Registre uma entrada ou despesa.'),
                    join(txt('Nenhuma despesa em '), call_expr('descPeriodo'), txt('.')))),
        call_stmt('pedirRosca'),
    ])


def p_pedirRosca():
    """v1.9: o Canvas do App Inventor nasce com um desenho de 32 x 48 px e so ganha o tamanho de verdade quando a
    tela e desenhada (CanvasView.onSizeChanged), DEPOIS do evento que mostrou a aba; o que foi desenhado antes e
    esticado junto. Por isso a rosca e desenhada um instante depois, pelo ClockRosca."""
    return defnoreturn('pedirRosca', [], [
        gset('tentativasRosca', num(0)),
        cset('ClockRosca', 'Clock', 'TimerEnabled', boolean(True)),
    ])


def e_timerRosca():
    """Desenha quando o Canvas ja tem largura (Width > 0 = ja foi medido na tela); tenta por ate 2 s."""
    return cevent('ClockRosca', 'Clock', 'Timer', [
        IF(cmp('GT', cget('CanvasRosca', 'Canvas', 'Width'), num(0)),
           [cset('ClockRosca', 'Clock', 'TimerEnabled', boolean(False)),
            call_stmt('desenharRosca')],
           [gset('tentativasRosca', madd(gget('tentativasRosca'), num(1))),
            IF(cmp('GTE', gget('tentativasRosca'), num(50)), [cset('ClockRosca', 'Clock', 'TimerEnabled', boolean(False))])]),
    ])


def p_desenharRosca():
    """v1.9: apaga e desenha o anel. Cada fatia e um arco (DrawArc sem centro e sem preenchimento: so o traco, com a
    espessura do LineWidth) que comeca no alto (-90 graus) e segue no sentido do relogio, do maior para o menor; entre
    as fatias fica um vao de ate 2 graus (transparente: aparece o cartao). Sem despesas: anel inteiro na cor do trilho."""
    L = lget
    arco = lambda ini, varre: cmeth('CanvasRosca', 'Canvas', 'DrawArc', num(ROSCA_A), num(ROSCA_A), num(ROSCA_B), num(ROSCA_B),
                                    ini, varre, boolean(False), boolean(False))
    n = lambda: llen(gget('roscaValores'))
    return defnoreturn('desenharRosca', [], [
        cmeth('CanvasRosca', 'Canvas', 'Clear'),
        LOCALS_STMT([('total', num(0)), ('ini', num(-90)), ('varre', num(0)), ('vao', num(0))], [
            FOREACH('v', gget('roscaValores'), [lset('total', madd(L('total'), L('v')))]),
            IF(cmp('LTE', L('total'), num(0)),
               [cset('CanvasRosca', 'Canvas', 'PaintColor', gcor('Trilho')),
                arco(num(0), num(360))],
               [FOR('i', num(1), n(), num(1), [
                   lset('varre', mdiv(mmul(litem(gget('roscaValores'), L('i')), num(360)), L('total'))),
                   lset('vao', CHOOSE(cmp('GT', n(), num(1)), mmin(lambda: num(2), lambda: mdiv(L('varre'), num(3))), num(0))),
                   cset('CanvasRosca', 'Canvas', 'PaintColor', litem(gget('roscaCores'), L('i'))),
                   arco(madd(L('ini'), mdiv(L('vao'), num(2))), msub(L('varre'), L('vao'))),
                   lset('ini', madd(L('ini'), L('varre'))),
               ])]),
        ]),
    ])


# =========================================================================== v1.9: aba Evolucao mais enxuta
def p_evoResumoMes():
    """v1.9: resumo do MES ESCOLHIDO (evoMesSel), dentro do cartao "Mes a mes": frase do saldo, despesas e entradas
    comparadas com o mes anterior. Mes sem lancamento: so a frase (as linhas e o atalho para o Grafico somem)."""
    L = lget
    sel = lambda: gget('evoMesSel')
    nome_mes = lambda k_fn: litem(gget('listaMeses'), madd(remainder(k_fn(), num(12)), num(1)))
    anterior = lambda: msub(gget('evoMesSel'), num(1))
    cor_saldo = lambda s_fn: CHOOSE(cmp('GT', s_fn(), num(0)), gcor('Bom'), CHOOSE(cmp('LT', s_fn(), num(0)), gcor('Perigo'), gcor('Texto')))
    sA = lambda: msub(L('eA'), L('dA'))
    return defnoreturn('evoResumoMes', ['eA', 'dA', 'eP', 'dP', 'temSel', 'temAnt'], [
        cset('LblTituloEvo', 'Label', 'Text',
             join(litem(gget('listaMesesTitulo'), madd(remainder(sel(), num(12)), num(1))), txt(' de '), quotient(sel(), num(12)))),
        cset('LblEvoFrase', 'Label', 'Text',
             CHOOSE(NOT(L('temSel')),
                    CHOOSE(eq(sel(), gget('chaveHoje')), join(txt('Ainda não há lançamentos em '), nome_mes(sel), txt('.')),
                           join(txt('Nenhum lançamento em '), nome_mes(sel), txt('.'))),
                    CHOOSE(cmp('GT', sA(), num(0)),
                           join(txt('Você guardou '), fmt(sA()), txt(' em '), nome_mes(sel), txt('.')),
                           CHOOSE(cmp('LT', sA(), num(0)),
                                  join(txt('Você gastou '), fmt(mabs(sA())), txt(' a mais do que ganhou em '), nome_mes(sel), txt('.')),
                                  join(txt('Você gastou exatamente o que ganhou em '), nome_mes(sel), txt('.')))))),
        cset('LblEvoFrase', 'Label', 'TextColor', CHOOSE(NOT(L('temSel')), gcor('Suave'), cor_saldo(sA))),
        cset('PnlEvoDesp', 'VerticalArrangement', 'Visible', L('temSel')),
        cset('PnlEvoEnt', 'VerticalArrangement', 'Visible', L('temSel')),
        cset('BtnEvoVerMes', 'Button', 'Visible', L('temSel')),
        cset('LblEvoDespValor', 'Label', 'Text', fmt(L('dA'))),
        cset('LblEvoEntValor', 'Label', 'Text', fmt(L('eA'))),
        call_stmt('comparar', comp_ref('LblEvoDespComp', 'Label'), L('dA'), L('dP'), L('temAnt'), boolean(True), nome_mes(anterior)),
        call_stmt('comparar', comp_ref('LblEvoEntComp', 'Label'), L('eA'), L('eP'), L('temAnt'), boolean(False), nome_mes(anterior)),
    ])


def p_atualizarEvolucao():
    """v1.9: aba Evolucao, numa so passada pelos lancamentos: mes a mes do ano escolhido (barras e totais do ano) e o
    resumo do MES ESCOLHIDO (evoMesSel), comparado com o mes anterior. (Saldo acumulado e ano a ano sairam a pedido do
    usuario; as setas do ano continuam levando aos anos anteriores.)"""
    L = lget
    item = lambda i: litem(L('item'), i)
    ent = lambda: eq(item(1), txt('Entrada'))
    v = lambda: item(3)
    ano_hoje = lambda: quotient(gget('chaveHoje'), num(12))
    mes_hoje = lambda: madd(remainder(gget('chaveHoje'), num(12)), num(1))
    base = lambda: mmul(gget('evoAno'), num(12))
    sel = lambda: gget('evoMesSel')
    soma_lista = lambda lst, i_fn, val_fn: lreplace(L(lst), i_fn(), madd(litem(L(lst), i_fn()), val_fn()))
    um_registro = [
        lset('item', litem(gget(REG), L('i'))),
        lset('k', chave_reg(lambda: L('i'))),
        IF(cmp('GTE', L('k'), num(0)), [
            # mes escolhido e o anterior a ele
            IF(eq(L('k'), sel()), [lset('temSel', boolean(True)),
                                    IF(ent(), [lset('eA', madd(L('eA'), v()))], [lset('dA', madd(L('dA'), v()))])]),
            IF(eq(L('k'), msub(sel(), num(1))), [lset('temAnt', boolean(True)),
                                                  IF(ent(), [lset('eP', madd(L('eP'), v()))], [lset('dP', madd(L('dP'), v()))])]),
            # ano escolhido: mes a mes
            IF(AND(cmp('GTE', L('k'), base()), cmp('LT', L('k'), madd(base(), num(12)))), [
                lset('m', madd(msub(L('k'), base()), num(1))),
                IF(ent(), [soma_lista('mesE', lambda: L('m'), v)], [soma_lista('mesD', lambda: L('m'), v)]),
                lreplace(L('mesTem'), L('m'), boolean(True)),
            ]),
        ]),
    ]

    def altura(val_fn, maior_fn, util):
        x = lambda: mround(mdiv(mmul(val_fn(), num(util)), maior_fn()))
        return CHOOSE(OR(cmp('LTE', val_fn(), num(0)), cmp('LTE', maior_fn(), num(0))), num(0),
                      CHOOSE(cmp('LT', x(), num(2)), num(2), x()))

    futuro = lambda: AND(eq(gget('evoAno'), ano_hoje()), cmp('GT', L('m'), mes_hoje()))
    escolhido = lambda: eq(madd(base(), msub(L('m'), num(1))), sel())
    cartao = [
        cset('LblEvoAno', 'Label', 'Text', join(txt(''), gget('evoAno'))),
        cset('BtnEvoAnoAnt', 'Button', 'Image', CHOOSE(cmp('GT', gget('evoAno'), quotient(gget('chaveMin'), num(12))),
                                                       gimg('SetaEsq'), gimg('Nada'))),
        cset('BtnEvoAnoProx', 'Button', 'Image', CHOOSE(cmp('LT', gget('evoAno'), ano_hoje()), gimg('SetaDir'), gimg('Nada'))),
        FOR('m', num(1), num(12), num(1), [
            IF(cmp('GT', litem(L('mesE'), L('m')), L('maior')), [lset('maior', litem(L('mesE'), L('m')))]),
            IF(cmp('GT', litem(L('mesD'), L('m')), L('maior')), [lset('maior', litem(L('mesD'), L('m')))]),
            IF(litem(L('mesTem'), L('m')), [lset('mesesCom', madd(L('mesesCom'), num(1)))]),
            lset('totE', madd(L('totE'), litem(L('mesE'), L('m')))),
            lset('totD', madd(L('totD'), litem(L('mesD'), L('m')))),
        ]),
        FOR('m', num(1), num(12), num(1), [
            gcset('Label', 'Height', litem(gget('compBarE'), L('m')),
                  altura(lambda: litem(L('mesE'), L('m')), lambda: L('maior'), EVO_UTIL)),
            gcset('Label', 'Height', litem(gget('compBarD'), L('m')),
                  altura(lambda: litem(L('mesD'), L('m')), lambda: L('maior'), EVO_UTIL)),
            # a inicial do mes e uma imagem: mes_<letra>_<a = escolhido | f = ainda vem | n = os outros>[_d].png
            gcset('Button', 'Image', litem(gget('compBtnMes'), L('m')),
                  join(txt('mes_'), litem(gget('letrasMes'), L('m')),
                       CHOOSE(escolhido(), txt('_a'), CHOOSE(futuro(), txt('_f'), txt('_n'))),
                       CHOOSE(gget('temaEscuro'), txt('_d'), txt('')), txt('.png'))),
        ]),
        cset('LblEvoAnoNomes', 'Label', 'Text',
             CHOOSE(eq(L('mesesCom'), num(0)), join(txt('Sem lançamentos em '), gget('evoAno'), txt('.')),
                    txt('Entradas no ano\\nDespesas no ano\\nSaldo do ano'))),
        cset('LblEvoAnoValores', 'Label', 'Text',
             CHOOSE(eq(L('mesesCom'), num(0)), txt(''),
                    join(fmt(L('totE')), txt('\\n'), fmt(L('totD')), txt('\\n'), call_expr('comSinal', msub(L('totE'), L('totD')))))),
    ]
    zeros = lambda: mklist(*[num(0) for _ in range(12)])
    decl = [('eA', num(0)), ('dA', num(0)), ('eP', num(0)), ('dP', num(0)),
            ('temSel', boolean(False)), ('temAnt', boolean(False)),
            ('mesE', zeros()), ('mesD', zeros()), ('mesTem', mklist(*[boolean(False) for _ in range(12)])),
            ('maior', num(0)), ('mesesCom', num(0)), ('totE', num(0)), ('totD', num(0)),
            ('item', mklist()), ('k', num(0)), ('m', num(0))]
    return defnoreturn('atualizarEvolucao', [], [
        garantir_chaves(),
        LOCALS_STMT(decl, [FOR('i', num(1), llen(gget(REG)), num(1), um_registro),
                           call_stmt('evoResumoMes', *[L(n) for n in ('eA', 'dA', 'eP', 'dP', 'temSel', 'temAnt')])]
                    + cartao),
    ])


def p_escolherMesEvo():
    """v1.9: toque numa inicial do "Mes a mes": o resumo passa a ser daquele mes (mes que ainda vem: nada muda)."""
    return defnoreturn('escolherMesEvo', ['chave'], [
        IF(cmp('LTE', lget('chave'), gget('chaveHoje')), [
            gset('evoMesSel', lget('chave')),
            call_stmt('atualizarEvolucao'),
        ]),
    ])


def e_eventos_evolucao():
    """v1.9: setas do ano (o mes escolhido vai junto: mesmo mes no outro ano, sem passar de hoje), toque num mes
    (resumo daquele mes) e o atalho para o Grafico do mes escolhido. A lista "Ano a ano" saiu."""
    ano_min = lambda: quotient(gget('chaveMin'), num(12))
    ano_hoje = lambda: quotient(gget('chaveHoje'), num(12))
    mudar_ano = lambda delta: [
        gset('evoAno', madd(gget('evoAno'), num(delta))),
        gset('evoMesSel', mmin(lambda: gget('chaveHoje'),
                               lambda: madd(mmul(gget('evoAno'), num(12)), remainder(gget('evoMesSel'), num(12))))),
        call_stmt('atualizarEvolucao'),
    ]
    eventos = [
        cevent('BtnNavEvolucao', 'Button', 'Click', [call_stmt('mostrarAba', num(5))]),
        cevent('BtnEvoAnoAnt', 'Button', 'Click', [IF(cmp('GT', gget('evoAno'), ano_min()), mudar_ano(-1))]),
        cevent('BtnEvoAnoProx', 'Button', 'Click', [IF(cmp('LT', gget('evoAno'), ano_hoje()), mudar_ano(1))]),
        cevent('BtnEvoVerMes', 'Button', 'Click', [call_stmt('abrirMes', gget('evoMesSel'))]),
    ]
    for i in range(1, 13):
        eventos.append(cevent('BtnMes%d' % i, 'Button', 'Click',
                              [call_stmt('escolherMesEvo', madd(mmul(gget('evoAno'), num(12)), num(i - 1)))]))
    return eventos


# =========================================================================== v1.9: foto do perfil pela camera
def p_usarFoto():
    """A foto escolhida na galeria (PickerFoto) ou tirada agora (CameraFoto) vira a foto do perfil e fica guardada."""
    return defnoreturn('usarFoto', ['caminho'], [
        IF(NOT(tempty(lget('caminho'))), [
            cset('LblPerfilMsg', 'Label', 'Visible', boolean(False)),
            gset('perfilFoto', lget('caminho')),
            call_stmt('mostrarPerfil'),
            call_stmt('guardarPref', txt('perfil_foto'), gget('perfilFoto')),
            erro_pref('Erro: não foi possível guardar a foto neste aparelho.'),
        ]),
    ])


def e_fotoEscolhida():
    return cevent('PickerFoto', 'ImagePicker', 'AfterPicking',
                  [call_stmt('usarFoto', cget('PickerFoto', 'ImagePicker', 'Selection'))])


def e_eventos_foto():
    """'Tirar foto' abre a camera do celular (na 1a vez o Android pede a permissao); a foto tirada chega em
    AfterPicture. Erros da camera (permissao negada, camera sem foto) viram mensagem no cartao (Screen1.ErrorOccurred)."""
    return [
        cevent('BtnTirarFoto', 'Button', 'Click', [cmeth('CameraFoto', 'Camera', 'TakePicture')]),
        cevent('CameraFoto', 'Camera', 'AfterPicture', [call_stmt('usarFoto', evparam('image'))]),
    ]


# =========================================================================== v2.0: lancamentos das notificacoes do banco
# Pedido do usuario: "o app interpretar as notificacoes do banco e passar pro app sobre gastos ou entrada". A extensao
# LeitorNotificacoes (com.conto.notificacoes.aix) guarda as notificacoes com valor em R$ mesmo com o app fechado; aqui
# elas viram lancamentos SUGERIDOS: nada entra sem a pessoa confirmar. O mesmo interpretador serve para "Colar mensagem".
NOTIF_ESTORNO = ['estorn', 'cancelad', 'reembols', 'devolvid', 'devolucao']
NOTIF_DESPESA = ['compra', 'pagamento de', 'pagamento realizado', 'pagamento efetuado', 'pagamento aprovado', 'pix enviado',
                 'voce enviou', 'voce pagou', 'transferencia enviada', 'transferencia realizada', 'transferencia efetuada',
                 'saque', 'debito automatico', 'debitad', 'fatura paga']
NOTIF_ENTRADA = ['recebeu', 'recebido', 'recebida', 'recebimento', 'cashback', 'deposito', 'depositad', 'creditad',
                 'credito em conta', 'salario', 'rendimento', 'caiu na sua conta', 'chegou um pix', 'entrou na sua conta',
                 'para voce', 'te enviou']             # v2.0.1: "Fulano enviou um Pix para voce" (PicPay)
# onde comeca o nome de quem recebeu/pagou, depois do valor (em ordem de preferencia)
NOTIF_MARCAS = [' em ', ' para ', ' de ', ' no ', ' na ']
# onde o nome termina (o primeiro que aparecer)
NOTIF_FIM = ['. ', ', ', '; ', ' - ', ' as ', ' no dia ', ' em ', ' para o cartao', ' no cartao', ' com o cartao', ' com final',
             ' cartao final', ' final ', ' foi ', ' aprovad', ' realizad', ' efetuad', ' via ', ' pelo ', ' pela ', ' saldo ',
             ' toque', ' clique', ' acesse', ' confira', ' veja']   # v2.0.1: "... Toque para visualizar o pagamento"
NOTIF_MAX_DESC = 40
# o que vem depois de 'na'/'no'/'em' mas nao e nome de loja nem de pessoa ('caiu na sua conta', 'no seu cartao')
NOTIF_NAO_NOME = ['sua ', 'seu ', 'conta ', 'cartao ', 'voce ',
                  # v2.0.1: o fim das notificacoes ("Toque para visualizar o pagamento") nao e nome
                  'visualizar ', 'ver ', 'conferir ', 'detalhes ', 'mais detalhes', 'acessar ', 'abrir ', 'o pagamento ',
                  'a transferencia ', 'o pix ', 'toque ']
NOTIF_MAX_CHAVES = 500
for _w in NOTIF_ESTORNO + NOTIF_DESPESA + NOTIF_ENTRADA + NOTIF_MARCAS + NOTIF_FIM:
    assert _w == _w.lower() and not any(ch in _w for ch in ACENTOS) and '|' not in _w, _w

SIG.update({
    'interpretarMensagem': ['texto'],
    'temAlguma': ['texto', 'palavras'],
    'lerNotificacoes': [],
    'atualizarNotif': [],
    'lancarNotif': ['quais'],
    'removerNotif': ['quais'],
    'chaveCurta': ['reg'],
})
GLOBAIS_V18 += [
    ('notifItens', lambda: mklist()),        # [id, tipo, valor, desc, data, cat, pag, banco, situacao, texto]
    ('notifSel', lambda: num(0)),
    ('chavesNotif', lambda: mklist()),       # "dd/mm/aaaa|tipo|valor" dos lancamentos que vieram das notificacoes
    ('palavrasEstorno', lambda: tsplit(txt('|'.join(NOTIF_ESTORNO)), txt('|'))),
    ('palavrasDespesa', lambda: tsplit(txt('|'.join(NOTIF_DESPESA)), txt('|'))),
    ('palavrasEntrada', lambda: tsplit(txt('|'.join(NOTIF_ENTRADA)), txt('|'))),
    ('marcasNome', lambda: tsplit(txt('|'.join(NOTIF_MARCAS)), txt('|'))),
    ('fimNome', lambda: tsplit(txt('|'.join(NOTIF_FIM)), txt('|'))),
    ('naoNome', lambda: tsplit(txt('|'.join(NOTIF_NAO_NOME)), txt('|'))),
]


def p_temAlguma():
    """Verdadeiro se o texto (ja sem acento e em minusculas) contem alguma das palavras."""
    return defreturn('temAlguma', ['texto', 'palavras'], LOCALS_EXPR(
        [('achou', boolean(False))],
        DO_RETURN([FOREACH('w', lget('palavras'), [IF(tcontains(lget('texto'), lget('w')), [lset('achou', boolean(True))])])],
                  lget('achou'))))


def p_chaveCurta():
    """'dd/mm/aaaa|tipo|valor' de um lancamento: o mesmo gasto pode vir da notificacao e do extrato com descricoes
    diferentes (ex.: 'MERCADO X' e 'MERCADO X LTDA SAO PAULO'); dia, tipo e valor iguais e que contam."""
    return defreturn('chaveCurta', ['reg'], join(_data_curta(lambda: litem(lget('reg'), 4)), txt('|'), litem(lget('reg'), 1),
                                                 txt('|'), litem(lget('reg'), 3)))


def p_interpretarMensagem():
    """Texto de uma notificacao/mensagem do banco -> [tipo, valor em centavos, descricao]; lista vazia se nao achar um
    valor em R$. Tipo: estorno/cancelamento = Entrada; compra, pagamento, Pix enviado... = Despesa; recebeu, deposito...
    = Entrada; sem pista = Despesa (a pessoa confere antes de lancar). Descricao: o nome depois do valor ('em MERCADO X',
    'para Maria', 'de Joao'), sem a parte do cartao e da hora; sem nome, uma palavra pelo tipo (Pix, Boleto...)."""
    L = lget
    n = lambda: L('n')
    ch_n = lambda: segment(n(), L('i'), num(1))
    tem = lambda w: tcontains(n(), txt(w))
    resto_n = lambda: L('rn')
    return defreturn('interpretarMensagem', ['texto'], LOCALS_EXPR(
        [('t', ttrim(treplace(treplace(treplace(join(txt(''), L('texto')), txt('\\r'), txt(' ')), txt('\\n'), txt(' ')),
                              txt(' '), txt(' ')))),
         ('n', txt('')), ('pos', num(0)), ('i', num(0)), ('numero', txt('')), ('v', txt('')), ('tipo', txt('Despesa')),
         ('rt', txt('')), ('rn', txt('')), ('nome', txt('')), ('marca', txt('')), ('k', num(0)), ('fim', num(0)),
         ('p', num(0)), ('tentativas', num(0)), ('estorno', boolean(False)), ('res', mklist())],
        DO_RETURN([
            lset('n', call_expr('semAcento', L('t'))),
            # o valor: logo depois de "R$" (ou "BRL"), pulando espacos e um sinal
            lset('pos', tstarts(n(), txt('r$'))),
            lset('i', madd(L('pos'), num(2))),
            IF(eq(L('pos'), num(0)), [lset('pos', tstarts(n(), txt('brl'))), lset('i', madd(L('pos'), num(3)))]),
            IF(cmp('GT', L('pos'), num(0)), [
                WHILE(AND(cmp('LTE', L('i'), tlen(n())), tcontains(txt(' -+'), ch_n())), [lset('i', madd(L('i'), num(1)))]),
                WHILE(AND(cmp('LTE', L('i'), tlen(n())), tcontains(txt('0123456789.,'), ch_n())),
                      [lset('numero', join(L('numero'), ch_n())), lset('i', madd(L('i'), num(1)))]),
                # "R$ 45,90." -> o ponto final da frase nao e do numero
                WHILE(AND(cmp('GT', tlen(L('numero')), num(0)), tcontains(txt('.,'), segment(L('numero'), tlen(L('numero')), num(1)))),
                      [lset('numero', segment(L('numero'), num(1), msub(tlen(L('numero')), num(1))))]),
                IF(cmp('GT', tlen(L('numero')), num(0)), [lset('v', call_expr('lerValor', L('numero')))]),
            ]),
            IF(AND(isnum(L('v')), NOT(eq(L('v'), num(0)))), [
                lset('v', mabs(L('v'))),
                IFELIF([(call_expr('temAlguma', n(), gget('palavrasEstorno')), [lset('tipo', txt('Entrada')), lset('estorno', boolean(True))]),
                        (call_expr('temAlguma', n(), gget('palavrasDespesa')), [lset('tipo', txt('Despesa'))]),
                        (call_expr('temAlguma', n(), gget('palavrasEntrada')), [lset('tipo', txt('Entrada'))])]),
                # v2.0.1: "Fulano enviou um Pix para voce" / "Fulano te enviou R$ 10" (PicPay): o nome vem ANTES de
                # "enviou", no comeco (no titulo da notificacao), na mesma frase
                lset('p', tstarts(n(), txt(' te enviou '))),
                IF(eq(L('p'), num(0)), [lset('p', tstarts(n(), txt(' enviou ')))]),
                IF(AND(cmp('GT', L('p'), num(1)), OR(tem('para voce'), tem(' te enviou '))), [
                    # so a frase em que esta o "enviou" (o titulo pode vir antes: "Pix recebido. Ana te enviou...")
                    lset('nome', segment(L('t'), num(1), msub(L('p'), num(1)))),
                    lset('nome', ttrim(litem(tsplit(L('nome'), txt('. ')), llen(tsplit(L('nome'), txt('. ')))))),
                    IF(OR(eq(tstarts(join(call_expr('semAcento', L('nome')), txt(' ')), txt('voce ')), num(1)),
                          tcontains(txt('0123456789'), segment(L('nome'), num(1), num(1)))),
                       [lset('nome', txt(''))], [lset('marca', txt('de'))]),
                ]),
                # o nome: depois do valor, a primeira marca (em ordem de preferencia) seguida de algo que nao e numero
                IF(cmp('LTE', L('i'), tlen(n())), [
                    lset('rt', join(txt(' '), segment(L('t'), L('i'), madd(msub(tlen(L('t')), L('i')), num(1))), txt(' '))),
                    lset('rn', join(txt(' '), segment(n(), L('i'), madd(msub(tlen(n()), L('i')), num(1))), txt(' '))),
                ]),
                FOREACH('m', gget('marcasNome'), [
                    IF(tempty(L('nome')), [
                        lset('k', num(1)), lset('tentativas', num(0)),
                        WHILE(AND(tempty(L('nome')), cmp('LT', L('tentativas'), num(5))), [
                            lset('tentativas', madd(L('tentativas'), num(1))),
                            lset('p', tstarts(segment(resto_n(), L('k'), madd(msub(tlen(resto_n()), L('k')), num(1))), L('m'))),
                            IFELIF([(eq(L('p'), num(0)), [lset('tentativas', num(99))])], els=[
                                lset('p', madd(L('k'), msub(L('p'), num(1)), tlen(L('m')))),      # primeira letra do nome
                                lset('k', L('p')),
                                lset('nome', segment(L('rt'), L('p'), madd(msub(tlen(L('rt')), L('p')), num(1)))),
                                # corta no primeiro fim de nome
                                lset('fim', madd(tlen(L('nome')), num(1))),
                                FOREACH('f', gget('fimNome'), [
                                    LOCALS_STMT([('q', tstarts(call_expr('semAcento', L('nome')), L('f')))], [
                                        IF(AND(cmp('GT', lget('q'), num(1)), cmp('LT', lget('q'), L('fim'))), [lset('fim', lget('q'))]),
                                    ]),
                                ]),
                                lset('nome', ttrim(segment(L('nome'), num(1), msub(L('fim'), num(1))))),
                                WHILE(AND(cmp('GT', tlen(L('nome')), num(0)),
                                          tcontains(txt('.,;:!-'), segment(L('nome'), tlen(L('nome')), num(1)))),
                                      [lset('nome', ttrim(segment(L('nome'), num(1), msub(tlen(L('nome')), num(1)))))]),
                                # 'sua conta', 'seu cartao'...: nao e nome
                                FOREACH('w', gget('naoNome'), [
                                    IF(eq(tstarts(join(call_expr('semAcento', L('nome')), txt(' ')), L('w')), num(1)),
                                       [lset('nome', txt(''))]),
                                ]),
                                # data, hora ou numero de cartao no lugar do nome: procura a proxima
                                IF(OR(tempty(L('nome')), tcontains(txt('0123456789'), segment(L('nome'), num(1), num(1)))),
                                   [lset('nome', txt(''))], [lset('marca', ttrim(L('m')))]),
                            ]),
                        ]),
                    ]),
                ]),
                IF(cmp('GT', tlen(L('nome')), num(NOTIF_MAX_DESC)), [lset('nome', ttrim(segment(L('nome'), num(1), num(NOTIF_MAX_DESC))))]),
                IF(L('estorno'), [lset('nome', CHOOSE(tempty(L('nome')), txt('Estorno'), join(txt('Estorno '), L('nome'))))]),
                IFELIF([
                    (tempty(L('nome')),
                     [lset('nome', CHOOSE(tem('pix'), txt('Pix'), CHOOSE(tem('boleto'), txt('Boleto'),
                              CHOOSE(tem('transfer'), txt('Transferência'), CHOOSE(tem('saque'), txt('Saque'),
                                     CHOOSE(eq(L('tipo'), txt('Entrada')), txt('Entrada'),
                                            CHOOSE(tem('fatura'), txt('Fatura'), CHOOSE(tem('parcela'), txt('Parcela'),
                                                   CHOOSE(tem('pagamento'), txt('Pagamento'), txt('Compra'))))))))))]),
                    (AND(tem('pix'), OR(eq(L('marca'), txt('para')), eq(L('marca'), txt('de')))),
                     [lset('nome', join(txt('Pix '), L('marca'), txt(' '), L('nome')))]),
                ]),
                lset('res', mklist(L('tipo'), L('v'), L('nome'))),
            ]),
        ], L('res'))))


def _item(i):
    return lambda: litem(lget('it'), i)


def p_lerNotificacoes():
    """Le o que a extensao guardou e monta notifItens (a mais nova primeiro). Situacao: 'ok' (pronta para lancar),
    'repetido' (ja existe um lancamento no mesmo dia, do mesmo tipo e valor) ou 'nao' (sem valor em R$ entendivel)."""
    L = lget
    pend = lambda i: litem(L('pn'), i)
    data_ms = lambda: cmeth('Clock1', 'Clock', 'FormatDate', cmeth('Clock1', 'Clock', 'MakeInstantFromMillis', pend(6)),
                            txt('dd/MM/yyyy HH:mm'))
    return defnoreturn('lerNotificacoes', [], [
        gset('notifItens', mklist()),
        LOCALS_STMT([('curtas', mklist()), ('r', mklist()), ('reg', mklist()), ('sit', txt('')), ('n', txt(''))], [
            FOREACH('x', gget(REG), [ladd(L('curtas'), call_expr('chaveCurta', L('x')))]),
            FOREACH('pn', cmeth('LeitorNotificacoes1', 'LeitorNotificacoes', 'Pendentes'), [
                IF(AND(lis(L('pn')), cmp('GTE', llen(L('pn')), num(6))), [
                    lset('r', call_expr('interpretarMensagem', join(pend(4), txt('. '), pend(5)))),
                    lset('n', call_expr('semAcento', join(pend(4), txt(' '), pend(5)))),
                    IFELIF([(eq(llen(L('r')), num(0)),
                             [lset('reg', mklist(txt(''), txt(''), num(0), CHOOSE(isnum(pend(6)), data_ms(), txt('')), txt(''), txt(''))),
                              lset('sit', txt('nao'))])], els=[
                        lset('reg', mklist(litem(L('r'), 1), litem(L('r'), 3), litem(L('r'), 2),
                                           CHOOSE(isnum(pend(6)), data_ms(),
                                                  cmeth('Clock1', 'Clock', 'FormatDate', agora(), txt('dd/MM/yyyy HH:mm'))),
                                           CHOOSE(eq(litem(L('r'), 1), txt('Entrada')), txt('Outros'),
                                                  call_expr('adivinharCategoria', litem(L('r'), 3))),
                                           call_expr('adivinharPagamento', L('n'),
                                                     AND3(tcontains(L('n'), txt('cartao')), NOT(tcontains(L('n'), txt('debito'))),
                                                          NOT(tcontains(L('n'), txt('pix'))))))),
                        lset('sit', CHOOSE(cmp('GT', lpos(call_expr('chaveCurta', L('reg')), L('curtas')), num(0)),
                                           txt('repetido'), txt('ok'))),
                    ]),
                    linsert(gget('notifItens'), num(1),
                            mklist(pend(1), litem(L('reg'), 1), litem(L('reg'), 3), litem(L('reg'), 2), litem(L('reg'), 4),
                                   litem(L('reg'), 5), litem(L('reg'), 6), pend(3), L('sit'), join(pend(4), txt(' — '), pend(5)))),
                ]),
            ]),
        ]),
        call_stmt('atualizarNotif'),
    ])


def p_atualizarNotif():
    L = lget
    it = _item
    n = lambda: llen(gget('notifItens'))
    acesso = lambda: cmeth('LeitorNotificacoes1', 'LeitorNotificacoes', 'AcessoLiberado')
    return defnoreturn('atualizarNotif', [], [
        LOCALS_STMT([('linhasN', mklist()), ('nOk', num(0)), ('ok', boolean(False))], [
            lset('ok', acesso()),
            FOREACH('it', gget('notifItens'), [
                IF(eq(it(9)(), txt('ok')), [lset('nOk', madd(L('nOk'), num(1)))]),
                ladd(L('linhasN'), cmeth('ListaNotif', 'ListView', 'CreateElement',
                     CHOOSE(eq(it(9)(), txt('nao')), txt('Não entendi o valor'),
                            join(CHOOSE(eq(it(2)(), txt('Entrada')), txt('+ '), txt('− ')), fmt(it(3)()), txt('  •  '), it(4)())),
                     CHOOSE(eq(it(9)(), txt('nao')), call_expr('abreviar', it(10)()),
                            join(it(8)(), txt('  •  '), segment(it(5)(), num(1), num(5)), segment(it(5)(), num(11), num(6)),
                                 CHOOSE(eq(it(9)(), txt('repetido')), txt('  •  Já existe um igual'), join(txt('  •  '), it(6)())))),
                     txt(''))),
            ]),
            cset('ListaNotif', 'ListView', 'Elements', L('linhasN')),
            cset('ListaNotif', 'ListView', 'Height', mmul(mmax(lambda: n(), lambda: num(1)), num(ALT_LINHA_LISTA))),
            cset('ListaNotif', 'ListView', 'Visible', cmp('GT', n(), num(0))),
            cset('LblNotifVazio', 'Label', 'Visible', eq(n(), num(0))),
            cset('LblNotifStatus', 'Label', 'Text', CHOOSE(L('ok'), txt('Acesso às notificações: liberado'),
                                                            txt('Acesso às notificações: desligado'))),
            cset('LblNotifStatus', 'Label', 'TextColor', CHOOSE(L('ok'), gcor('Bom'), gcor('Perigo'))),
            # v2.0.1: o que o leitor viu por ultimo (para saber se o Android esta entregando as notificacoes)
            cset('LblNotifDiag', 'Label', 'Text', cmeth('LeitorNotificacoes1', 'LeitorNotificacoes', 'Diagnostico')),
            cset('LblNotifDiag', 'Label', 'Visible', L('ok')),
            cset('PnlNotifAcesso', 'VerticalArrangement', 'Visible', NOT(L('ok'))),
            cset('BtnNotifLancarTodos', 'Button', 'Text',
                 CHOOSE(eq(L('nOk'), num(1)), txt('Lançar 1 lançamento'), join(txt('Lançar os '), L('nOk')))),
            cset('BtnNotifLancarTodos', 'Button', 'Visible', cmp('GT', L('nOk'), num(0))),
            cset('BtnNotifIgnorarTodos', 'Button', 'Visible', cmp('GT', n(), num(0))),
            # aviso no Lancar
            cset('HzAvisoNotif', 'HorizontalArrangement', 'Visible', cmp('GT', n(), num(0))),
            cset('BtnAvisoNotif', 'Button', 'Text',
                 CHOOSE(eq(n(), num(1)), txt('1 notificação para conferir'),
                        join(n(), txt(' notificações para conferir')))),
        ]),
    ])


def p_removerNotif():
    """Apaga da extensao as notificacoes da lista 'quais' (posicoes em notifItens) e le de novo."""
    return defnoreturn('removerNotif', ['quais'], [
        FOREACH('q', lget('quais'), [
            cmeth('LeitorNotificacoes1', 'LeitorNotificacoes', 'Remover', litem(litem(gget('notifItens'), lget('q')), 1)),
        ]),
        call_stmt('lerNotificacoes'),
    ])


def p_lancarNotif():
    """Lanca os itens 'quais' (posicoes em notifItens) de uma vez. Gravou: guarda a chave curta de cada um (para o
    extrato nao lancar de novo o mesmo gasto), apaga as notificacoes e avisa. Nao gravou: desfaz e avisa."""
    L = lget
    it = _item
    return defnoreturn('lancarNotif', ['quais'], [
        LOCALS_STMT([('antes', B('lists_copy', values=[('LIST', gget(REG))])), ('pos', num(1)), ('novo', mklist()),
                     ('it', mklist()), ('n', num(0))], [
            FOREACH('q', L('quais'), [
                lset('it', litem(gget('notifItens'), L('q'))),
                lset('novo', mklist(it(2)(), it(4)(), it(3)(), it(5)(), it(6)(), it(7)())),
            ] + inserir_em_ordem(lambda: L('novo')) + [
                lset('n', madd(L('n'), num(1))),
            ]),
            IF(cmp('GT', L('n'), num(0)), [
                invalidar_chaves(),
                call_stmt('gravarDados'),
                IFELIF([(NOT(gget('gravacaoOk')),
                         [gset(REG, L('antes')), invalidar_chaves(), call_stmt('atualizarTudo'),
                          dialog_erro(txt('Erro: não foi possível gravar. Nada foi lançado.'))])], els=[
                    FOREACH('q', L('quais'), [
                        lset('it', litem(gget('notifItens'), L('q'))),
                        ladd(gget('chavesNotif'), call_expr('chaveCurta', mklist(it(2)(), it(4)(), it(3)(), it(5)()))),
                    ]),
                    WHILE(cmp('GT', llen(gget('chavesNotif')), num(NOTIF_MAX_CHAVES)), [lremove(gget('chavesNotif'), num(1))]),
                    call_stmt('guardarPref', txt('chaves_notif'), gget('chavesNotif')),
                    call_stmt('atualizarTudo'),
                    call_stmt('removerNotif', L('quais')),
                    cset('LblNotifMsg', 'Label', 'Text',
                         CHOOSE(eq(L('n'), num(1)), txt('1 lançamento adicionado. Ele já aparece no Histórico.'),
                                join(L('n'), txt(' lançamentos adicionados. Eles já aparecem no Histórico.')))),
                    cset('LblNotifMsg', 'Label', 'TextColor', gcor('AvisoOk')),
                    cset('LblNotifMsg', 'Label', 'Visible', boolean(True)),
                ]),
            ]),
        ]),
    ])


def notif_dialogo():
    """Toque num item da lista: mostra o que vai ser lancado e pergunta."""
    L = lget
    sel = lambda: litem(gget('notifItens'), gget('notifSel'))
    s = lambda i: litem(sel(), i)
    idx = lambda: cget('ListaNotif', 'ListView', 'SelectionIndex')
    detalhe = lambda: join(CHOOSE(eq(s(2), txt('Entrada')), txt('Entrada'), txt('Despesa')), txt(' de '), fmt(s(3)),
                           txt('<br>'), call_expr('html', s(4)), txt('<br>'), s(6), txt(' • '), s(7), txt('<br>'), s(5))
    return cevent('ListaNotif', 'ListView', 'AfterPicking', [
        IF(AND(cmp('GTE', idx(), num(1)), cmp('LTE', idx(), llen(gget('notifItens')))), [
            gset('notifSel', idx()),
            IFELIF([
                (eq(s(9), txt('ok')),
                 [cmeth('Notifier1', 'Notifier', 'ShowChooseDialog', join(detalhe(), txt('<br><br>Lançar?')),
                        join(txt('Notificação: '), call_expr('html', s(8))), txt('Lançar'), txt('Ignorar'), boolean(True))]),
                (eq(s(9), txt('repetido')),
                 [cmeth('Notifier1', 'Notifier', 'ShowChooseDialog',
                        join(detalhe(), txt('<br><br>Já existe um lançamento neste dia com o mesmo tipo e valor (pode ter vindo do extrato '
                                            'ou ter sido lançado à mão). Lançar mesmo assim?')),
                        join(txt('Notificação: '), call_expr('html', s(8))), txt('Lançar mesmo assim'), txt('Ignorar'), boolean(True))]),
            ], els=[cmeth('Notifier1', 'Notifier', 'ShowChooseDialog',
                          join(txt('Não encontrei um valor em R$ nesta notificação:<br>'), call_expr('html', s(10))),
                          join(txt('Notificação: '), call_expr('html', s(8))), txt('Ignorar'), txt('Manter'), boolean(False))]),
        ]),
    ])


def p_abrirNotif():
    return defnoreturn('abrirNotif', [], [
        cset('LblNotifMsg', 'Label', 'Visible', boolean(False)),
        cset('LblErroColar', 'Label', 'Visible', boolean(False)),
        call_stmt('mostrarAba', num(8)),
        call_stmt('lerNotificacoes'),
    ])


def e_eventos_notif():
    L = lget
    r = lambda i: litem(L('r'), i)
    oks = lambda: L('oks')
    return [
        notif_dialogo(),
        cevent('BtnNotificacoes', 'Button', 'Click', [call_stmt('abrirNotif')]),
        cevent('BtnAvisoNotif', 'Button', 'Click', [call_stmt('abrirNotif')]),
        cevent('BtnNotifVoltar', 'Button', 'Click', [call_stmt('mostrarAba', num(4))]),
        cevent('BtnNotifAtualizar', 'Button', 'Click', [cset('LblNotifMsg', 'Label', 'Visible', boolean(False)),
                                                        # v2.0.1: religa o leitor (alguns celulares o desligam) e rele a barra
                                                        cmeth('LeitorNotificacoes1', 'LeitorNotificacoes', 'Reconectar'),
                                                        call_stmt('lerNotificacoes')]),
        cevent('BtnNotifAcesso', 'Button', 'Click', [cmeth('LeitorNotificacoes1', 'LeitorNotificacoes', 'AbrirConfiguracaoDeAcesso')]),
        cevent('BtnNotifInfoApp', 'Button', 'Click', [cmeth('LeitorNotificacoes1', 'LeitorNotificacoes', 'AbrirInformacoesDoApp')]),
        # chegou uma notificacao com o app aberto: atualiza a lista e o aviso do Lancar
        cevent('LeitorNotificacoes1', 'LeitorNotificacoes', 'NotificacaoRecebida', [call_stmt('lerNotificacoes')]),
        cevent('LeitorNotificacoes1', 'LeitorNotificacoes', 'Erro', [
            cset('LblNotifMsg', 'Label', 'Text', evparam('mensagem')),
            cset('LblNotifMsg', 'Label', 'TextColor', gcor('Perigo')),
            cset('LblNotifMsg', 'Label', 'Visible', boolean(True)),
        ]),
        cevent('BtnNotifLancarTodos', 'Button', 'Click', [
            LOCALS_STMT([('oks', num(0))], [
                FOREACH('it', gget('notifItens'), [IF(eq(litem(L('it'), 9), txt('ok')), [lset('oks', madd(oks(), num(1)))])]),
                IF(cmp('GT', oks(), num(0)), [
                    cmeth('Notifier1', 'Notifier', 'ShowChooseDialog',
                          join(CHOOSE(eq(oks(), num(1)), txt('1 lançamento das notificações vai para o seu Histórico.'),
                                      join(oks(), txt(' lançamentos das notificações vão para o seu Histórico.'))),
                               txt(' Os que parecem repetidos e os que não entendi continuam na lista.')),
                          txt('Lançar todos?'), txt('Lançar todos'), txt('Cancelar'), boolean(False)),
                ]),
            ]),
        ]),
        cevent('BtnNotifIgnorarTodos', 'Button', 'Click', [
            cmeth('Notifier1', 'Notifier', 'ShowChooseDialog',
                  txt('As notificações saem desta lista e nada é lançado. Isso não apaga nada do seu Histórico.'),
                  txt('Ignorar todas?'), txt('Ignorar todas'), txt('Cancelar'), boolean(False)),
        ]),
        # colar a mensagem do banco: preenche o formulario do Lancar para a pessoa conferir e salvar
        cevent('BtnInterpretar', 'Button', 'Click', [
            cmeth('TxtColar', 'TextBox', 'HideKeyboard'),
            LOCALS_STMT([('r', call_expr('interpretarMensagem', cget('TxtColar', 'TextBox', 'Text'))), ('cat', txt('')),
                         ('pag', txt(''))], [
                IFELIF([(eq(llen(L('r')), num(0)),
                         [cset('LblErroColar', 'Label', 'Text',
                               CHOOSE(tempty(ttrim(cget('TxtColar', 'TextBox', 'Text'))), txt('Cole a mensagem do banco no campo acima.'),
                                      txt('Não encontrei um valor em R$ nesta mensagem. Confira se ela tem o valor (ex.: R$ 45,90).'))),
                          cset('LblErroColar', 'Label', 'Visible', boolean(True))])], els=[
                    cset('LblErroColar', 'Label', 'Visible', boolean(False)),
                    lset('cat', CHOOSE(eq(r(1), txt('Entrada')), txt('Outros'), call_expr('adivinharCategoria', r(3)))),
                    lset('pag', call_expr('adivinharPagamento', call_expr('semAcento', cget('TxtColar', 'TextBox', 'Text')),
                                          AND3(tcontains(call_expr('semAcento', cget('TxtColar', 'TextBox', 'Text')), txt('cartao')),
                                               NOT(tcontains(call_expr('semAcento', cget('TxtColar', 'TextBox', 'Text')), txt('debito'))),
                                               NOT(tcontains(call_expr('semAcento', cget('TxtColar', 'TextBox', 'Text')), txt('pix')))))),
                    call_stmt('limparErros'),
                    cset('TxtDescricao', 'TextBox', 'Text', r(3)),
                    cset('TxtValor', 'TextBox', 'Text', call_expr('valorSemRs', r(2))),
                    gset('categoriaSel', L('cat')),
                    gset('categoriaIcone', litem(gget('listaCatIcones'), call_expr('indiceCategoria', L('cat')))),
                    gset('pagamentoSel', L('pag')),
                    gset('pagamentoIcone', CHOOSE(cmp('GT', lpos(L('pag'), gget('listaPags')), num(0)),
                                                  litem(gget('listaPagIcones'), lpos(L('pag'), gget('listaPags'))), txt(''))),
                    call_stmt('atualizarCampos'),
                    cset('TxtColar', 'TextBox', 'Text', txt('')),
                    call_stmt('mostrarAba', num(1)),
                    call_stmt('mostrarAviso', boolean(True),
                              join(txt('Entendi '), CHOOSE(eq(r(1), txt('Entrada')), txt('uma entrada'), txt('uma despesa')),
                                   txt(' de '), fmt(r(2)), txt('. Confira os campos e toque em '),
                                   CHOOSE(eq(r(1), txt('Entrada')), txt('“+ Entrada”.'), txt('“− Despesa”.')))),
                ]),
            ]),
        ]),
    ]


def escolhas_notif():
    """Ramos do Notifier1.AfterChoosing para as notificacoes (entram no e_afterChoosing)."""
    sel = lambda: gget('notifSel')
    valido = lambda: AND(cmp('GTE', sel(), num(1)), cmp('LTE', sel(), llen(gget('notifItens'))))
    escolha = lambda v: eq(evparam('choice'), txt(v))
    return [
        IF(AND(OR(escolha('Lançar'), escolha('Lançar mesmo assim')), valido()), [call_stmt('lancarNotif', mklist(sel()))]),
        IF(AND(escolha('Ignorar'), valido()), [call_stmt('removerNotif', mklist(sel()))]),
        IF(escolha('Lançar todos'), [
            LOCALS_STMT([('quais', mklist())], [
                FOR('q', num(1), llen(gget('notifItens')), num(1), [
                    IF(eq(litem(litem(gget('notifItens'), lget('q')), 9), txt('ok')), [ladd(lget('quais'), lget('q'))]),
                ]),
                call_stmt('lancarNotif', lget('quais')),
            ]),
        ]),
        IF(escolha('Ignorar todas'), [
            LOCALS_STMT([('quais', mklist())], [
                FOR('q', num(1), llen(gget('notifItens')), num(1), [ladd(lget('quais'), lget('q'))]),
                call_stmt('removerNotif', lget('quais')),
            ]),
        ]),
    ]


PROCS_V18 = [
    'p_normCab', 'p_dividirLinha', 'p_lerData', 'p_lerValor', 'p_adivinharCategoria', 'p_adivinharPagamento',
    'p_acharNaLista', 'p_misturar', 'p_lerExtrato', 'p_aplicarImportacao', 'p_atualizarCampoData', 'p_saldoDoMes',
    'p_atualizarMeta', 'p_pintarMetaEdit', 'p_abrirMeta', 'p_diasDesde', 'p_atualizarInfoBackup',
    'p_confirmarExclusao', 'p_confirmarEdicao',
    'p_montarRosca', 'p_pedirRosca', 'p_desenharRosca',      # v1.9
    'p_escolherMesEvo', 'p_usarFoto',
    'p_temAlguma', 'p_chaveCurta', 'p_interpretarMensagem', 'p_lerNotificacoes', 'p_atualizarNotif',     # v2.0
    'p_removerNotif', 'p_lancarNotif', 'p_abrirNotif',
]


GLOBAIS = [
    (REG, lambda: mklist()),
    ('totalEntradas', lambda: num(0)),
    ('totalDespesas', lambda: num(0)),
    ('linhas', lambda: mklist()),
    ('indiceSel', lambda: num(0)),
    ('valorCentavos', lambda: num(0)),
    ('gravacaoOk', lambda: boolean(True)),
    ('chaveDados', lambda: txt('lancamentos')),
    ('chaveAntiga', lambda: txt('transacoes')),
    ('categoriaSel', lambda: txt('')),
    ('pagamentoSel', lambda: txt('')),
    ('categoriaIcone', lambda: txt('')),
    ('pagamentoIcone', lambda: txt('')),
    ('pickerTipo', lambda: txt('')),
    ('temErro', lambda: boolean(False)),
    ('listaCats', lambda: mklist(*[txt(c[0]) for c in T.CATEGORIAS])),
    ('listaCatIcones', lambda: mklist(*[txt(c[1]) for c in T.CATEGORIAS])),
    ('listaPags', lambda: mklist(*[txt(c[0]) for c in T.PAGAMENTOS])),
    ('listaPagIcones', lambda: mklist(*[txt(c[1]) for c in T.PAGAMENTOS])),
    # v1.6
    ('temaEscuro', lambda: boolean(False)),
    ('abaAtual', lambda: num(1)),
    ('abaVolta', lambda: num(1)),
    ('avisoOk', lambda: boolean(True)),
    ('prefOk', lambda: boolean(True)),
    ('perfilNome', lambda: txt('')),
    ('perfilFoto', lambda: txt('')),
] + GLOBAIS_V17 + GLOBAIS_V18 + [('cor' + n, (lambda n=n: rgbh(T.CORES[n][0]))) for n in T.CORES] \
  + [('img' + n, (lambda n=n: txt(T.IMAGENS[n][0]))) for n in T.IMAGENS]


# =========================================================================== montagem
def subtree_size(el):
    return sum(1 for _ in el.iter('block'))


def build_bky(orig_bky_path):
    orig = ET.parse(orig_bky_path).getroot()

    def copy_orig(bid):
        for b in orig:
            if b.tag.split('}')[-1] == 'block' and b.get('id') == bid:
                c = copy.deepcopy(b)
                for k in ('x', 'y'):
                    c.attrib.pop(k, None)
                # O arquivo original e lido com namespace (xmlns padrao). Se os elementos copiados
                # mantivessem o namespace, o ElementTree os gravaria como <ns0:block>, e o Blockly do
                # App Inventor (que compara nodeName == 'block') nao os reconheceria.
                for e in c.iter():
                    e.tag = e.tag.split('}')[-1]
                return c
        raise KeyError(bid)

    root = ET.Element('xml', {'xmlns': 'https://developers.google.com/blockly/xml'})

    left = [gdecl(n, f()) for n, f in GLOBAIS]
    left += [
        p_formatarMoeda(),
        p_formatarPercentual(),
        p_paraCentavos(),
        p_mostrarAba(),
        p_gravarDados(),
        p_carregarDados(),
        p_atualizarTudo(),
        p_atualizarHistorico(),
        p_atualizarGrafico(),
        p_registrar(),
        p_limparErros(),
        p_mostrarAviso(),
        p_atualizarCampos(),
        p_abrirPicker(),
        p_fecharPicker(),
        p_abreviar(),
        # v1.6
        p_indiceCategoria(),
        p_larguraBarra(),
        p_atualizarCategorias(),
        p_pintarAbas(),
        p_definirTema(),
    ] + p_pintarTemas() + [
        p_pintarEstados(),
        p_aplicarTema(),
        p_guardarPref(),
        p_trocarTema(),
        p_carregarPreferencias(),
        p_primeiroNome(),
        p_mostrarPerfil(),
        p_mostrarMsgPerfil(),
        p_abrirPerfil(),
    ] + [globals()[nome]() for nome in PROCS_V17] + [globals()[nome]() for nome in PROCS_V18]
    right = [
        e_initialize(),
        e_btn('BtnEntrada', 'Entrada'),
        e_btn('BtnDespesa', 'Despesa'),
        copy_orig('b293'),          # BtnNavLancar.Click
        copy_orig('b296'),          # BtnNavHistorico.Click
        copy_orig('b299'),          # BtnNavGrafico.Click
        # v1.7: ListaHistorico.AfterPicking agora abre Editar / Excluir (e_historicoToque, em e_eventos_v17)
        e_btnLimpar(),
        e_afterChoosing(),
        e_picker(),
        e_abre('BtnCategoria', 'Button', 'cat'),
        e_abre('ImgCatIcone', 'Image', 'cat'),
        e_abre('BtnPagamento', 'Button', 'pag'),
        e_abre('ImgPagIcone', 'Image', 'pag'),
        e_voltar(),
        e_valorMudou(),
        e_timerAviso(),
    ] + e_eventos_v16() + e_eventos_v17() + e_eventos_v18()

    def place(blocks, x):
        y = 20
        for b in blocks:
            b.set('x', str(x))
            b.set('y', str(y))
            root.append(b)
            y += 40 + 34 * subtree_size(b)

    place(left, 20)
    place(right, 1600)

    vistos = set()
    for e in root.iter():
        assert id(e) not in vistos, 'bloco usado em dois lugares: %s' % ET.tostring(e, encoding='unicode')[:200]
        vistos.add(id(e))
    nomes_proc = [b.find('field').text for b in root if b.get('type', '').startswith('procedures_def')]
    assert len(nomes_proc) == len(set(nomes_proc)), 'procedimento repetido'
    eventos = [(b.find('mutation').get('instance_name'), b.find('mutation').get('event_name'))
               for b in root if b.get('type') == 'component_event']
    assert len(eventos) == len(set(eventos)), 'evento repetido'
    n = 0
    for b in root.iter('block'):
        n += 1
        b.set('id', 'b%d' % n)

    ET.SubElement(root, 'yacodeblocks', {'ya-version': '237', 'language-version': '39'})
    return root


def write_xml(root, path):
    s = ET.tostring(root, encoding='unicode')
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(s)


def write_scm(dst):
    open(dst, 'w', encoding='utf-8', newline='').write(gen_scm.scm_text())


def patch_properties(src, dst):
    s = open(src, encoding='utf-8').read()
    assert 'versioncode=3' in s and 'versionname=1.2' in s
    s = s.replace('versioncode=3', 'versioncode=13').replace('versionname=1.2', 'versionname=2.0.1')
    # as cores do projeto acompanham as do formulario (o App Inventor as le dos dois lugares)
    for chave, cor in (('color.primary', T.EMERALD), ('color.primary.dark', T.EMERALD_DARK), ('color.accent', T.EMERALD)):
        s, n = re.subn(r'(?m)^' + re.escape(chave) + r'=.*$', chave + '=' + T.aia(cor), s)
        assert n == 1, chave
    open(dst, 'w', encoding='utf-8', newline='').write(s)


def main(orig_dir, out_dir, aia_path, assets_dir):
    src_dir = os.path.join(orig_dir, 'src', 'appinventor', 'ai_conto', 'Conto')
    out_src = os.path.join(out_dir, 'src', 'appinventor', 'ai_conto', 'Conto')
    out_yp = os.path.join(out_dir, 'youngandroidproject')
    out_assets = os.path.join(out_dir, 'assets')
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_src)
    os.makedirs(out_yp)
    os.makedirs(out_assets)

    root = build_bky(os.path.join(src_dir, 'Screen1.bky'))
    write_xml(root, os.path.join(out_src, 'Screen1.bky'))
    write_scm(os.path.join(out_src, 'Screen1.scm'))
    patch_properties(os.path.join(orig_dir, 'youngandroidproject', 'project.properties'),
                     os.path.join(out_yp, 'project.properties'))
    for fn in sorted(os.listdir(assets_dir)):
        if os.path.isfile(os.path.join(assets_dir, fn)):
            shutil.copyfile(os.path.join(assets_dir, fn), os.path.join(out_assets, fn))
    ext_src = os.environ.get('EXT_DIR') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ext', 'extcomp')
    ext_files = []
    for raiz, _, nomes in os.walk(ext_src):
        for fn in sorted(nomes):
            orig = os.path.join(raiz, fn)
            rel = os.path.relpath(orig, ext_src).replace(os.sep, '/')
            dest = os.path.join(out_assets, 'external_comps', rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(orig, dest)
            ext_files.append('assets/external_comps/' + rel)
    assert any(f.endswith('com.conto.notificacoes/classes.jar') for f in ext_files), 'extensao nao encontrada em ' + ext_src

    # mesmo desenho de zip do App Inventor: properties, tela (.scm/.bky), assets/
    order = ['youngandroidproject/project.properties',
             'src/appinventor/ai_conto/Conto/Screen1.scm',
             'src/appinventor/ai_conto/Conto/Screen1.bky'] + ['assets/' + fn for fn in sorted(os.listdir(out_assets))
                                                               if os.path.isfile(os.path.join(out_assets, fn))] + sorted(ext_files)
    if os.path.exists(aia_path):
        os.remove(aia_path)
    with zipfile.ZipFile(aia_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in order:
            z.write(os.path.join(out_dir, rel), rel)
    print('OK:', aia_path, '(%d arquivos)' % len(order))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
