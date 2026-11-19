import copy, os, subprocess, sys
import xml.etree.ElementTree as ET
# uso: python3 mutate_check.py <pasta com Screen1.bky e Screen1.scm>
import tempfile  # noqa: E402
SP = tempfile.mkdtemp(prefix='conto_mutate_check_')   # pasta temporaria para os blocos com defeito plantado
SRC = sys.argv[1].rstrip('/') + '/'
os.makedirs(SP + '/mut', exist_ok=True)
NS = '{https://developers.google.com/blockly/xml}'
ET.register_namespace('', NS[1:-1])
scm = SRC + 'Screen1.scm'
base = ET.parse(SRC + 'Screen1.bky')
# o verificador que esta AO LADO deste script (a versao certa para esta geracao do projeto), nunca outra pasta
BKYCHECK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bkycheck.py')


def checar(bky):
    r = subprocess.run([sys.executable, '-I', BKYCHECK, bky, scm], capture_output=True, text=True)
    erros = [l for l in r.stdout.splitlines() if l.startswith('  - ')]
    return r.returncode, erros, r


# controle: os arquivos ORIGINAIS precisam passar limpos, senao qualquer "deteccao" abaixo seria falsa
_rc, _erros, _r = checar(SRC + 'Screen1.bky')
print('controle (arquivos originais): %d erros, exit=%d' % (len(_erros), _rc))
if _rc != 0 or _erros:
    print('*** o verificador acusa erro no original; o autoteste nao vale ***')
    for l in _erros[:5]:
        print('   ', l[:160])
    sys.exit(2)

def tg(e): return e.tag.split('}')[-1]
def blocks(root, typ=None, **fieldeq):
    out = []
    for b in root.iter(NS + 'block'):
        if typ and b.get('type') != typ: continue
        ok = True
        for k, v in fieldeq.items():
            f = [c for c in b if tg(c) == 'field' and c.get('name') == k]
            if not f or f[0].text != v: ok = False
        if ok: out.append(b)
    return out
def value(b, name):
    for c in b:
        if tg(c) == 'value' and c.get('name') == name: return c
def run(mut, label, esperado=None):
    """Planta o defeito e exige: exit != 0, pelo menos um erro e (se 'esperado' for dado) uma mensagem que o cite."""
    root = copy.deepcopy(base).getroot()
    mut(root)
    p = SP + '/mut/m.bky'
    ET.ElementTree(root).write(p, encoding='utf-8')
    rc, erros, r = checar(p)
    caught = rc != 0 and bool(erros)
    if caught and esperado:
        caught = any(all(k.lower() in l.lower() for k in esperado) for l in erros)
    first = [l for l in erros if not esperado or all(k.lower() in l.lower() for k in esperado)][:1] or erros[:1]
    print(('DETECTADO  ' if caught else '*** NAO DETECTADO ***  ') + label + (' -> ' + first[0].strip()[:150] if first else ''))
    return caught

R = []
def m_localvar(root):
    b = blocks(root, 'lexical_variable_get', VAR='acumulado')[0]; b.find(NS + 'field').text = 'acumuladoX'
R.append(run(m_localvar, 'variavel local inexistente', ['acumuladoX']))
def m_globalvar(root):
    b = blocks(root, 'lexical_variable_get', VAR='global lancamentos')[0]; b.find(NS + 'field').text = 'global lancamentosX'
R.append(run(m_globalvar, 'variavel global inexistente', ['lancamentosX']))
def m_empty(root):
    b = blocks(root, 'lexical_variable_set', VAR='global gravacaoOk')[0]
    v = value(b, 'VALUE'); [v.remove(x) for x in list(v)]
R.append(run(m_empty, 'soquete vazio (set gravacaoOk)', ['soquete', 'VALUE']))
def m_arity(root):
    b = blocks(root, 'procedures_callnoreturn', PROCNAME='registrar')[0]
    mu = [c for c in b if tg(c) == 'mutation'][0]; [mu.remove(x) for x in list(mu)]
    v = value(b, 'ARG0'); b.remove(v)
R.append(run(m_arity, 'chamada de registrar() sem argumento', ['argumentos', 'parametros']))
def m_type(root):
    seg = blocks(root, 'text_segment')[0]
    v = value(seg, 'LENGTH'); [v.remove(x) for x in list(v)]
    nb = ET.SubElement(v, NS + 'block', {'type': 'logic_boolean', 'id': 'zz1'})
    f = ET.SubElement(nb, NS + 'field', {'name': 'BOOL'}); f.text = 'TRUE'
R.append(run(m_type, 'tipo incompativel (boolean em soquete numerico)', ['incompativel']))
def m_dupid(root):
    bs = list(root.iter(NS + 'block')); bs[5].set('id', bs[0].get('id'))
R.append(run(m_dupid, 'id duplicado', ['duplicad']))
def m_input_name(root):
    seg = blocks(root, 'text_segment')[0]; value(seg, 'START').set('name', 'STAT')
R.append(run(m_input_name, 'nome de entrada errado (START->STAT)', ['STAT']))
def m_prop(root):
    b = blocks(root, 'component_set_get')[0]
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if x.get('type') == 'component_set_get' and mu and mu[0].get('property_name') == 'SelectionIndex':
            mu[0].set('property_name', 'SelectIndex'); break
    else:
        raise SystemExit('mutante nao aplicavel: SelectionIndex')
R.append(run(m_prop, 'propriedade inexistente', ['COMPONENT_SELECTOR/PROP']))
def m_comp(root):
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if mu and mu[0].get('instance_name') == 'BtnCategoria':
            mu[0].set('instance_name', 'BtnCategoriaX'); break
    else:
        raise SystemExit('mutante nao aplicavel: BtnCategoria')
R.append(run(m_comp, 'componente inexistente', ['BtnCategoriaX']))
def m_dupevent(root):
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if x.get('type') == 'component_event' and mu and mu[0].get('instance_name') == 'BtnDespesa':
            mu[0].set('instance_name', 'BtnEntrada'); x.find(NS + 'field').text = 'BtnEntrada'; break
R.append(run(m_dupevent, 'evento duplicado (BtnEntrada.Click 2x)', ['evento duplicado', 'BtnEntrada.Click']))
def m_proc(root):
    b = blocks(root, 'procedures_callnoreturn', PROCNAME='gravarDados')[0]
    b.find(NS + 'field').text = 'gravarDadosX'
R.append(run(m_proc, 'procedimento inexistente', ['gravarDadosX']))
def m_stmt_as_value(root):
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if x.get('type') == 'component_method' and mu and mu[0].get('method_name') == 'StoreValue':
            mu[0].set('method_name', 'GetValue'); break
    else:
        raise SystemExit('mutante nao aplicavel: StoreValue')
R.append(run(m_stmt_as_value, 'metodo que devolve valor usado como instrucao', ['valor usado como instrucao']))
def m_items(root):
    j = blocks(root, 'text_join')[0]; mu = [c for c in j if tg(c) == 'mutation'][0]
    mu.set('items', str(int(mu.get('items')) + 1))
R.append(run(m_items, 'mutacao items maior que as entradas', ['text_join', 'soquete']))
def m_loopvar(root):
    f = blocks(root, 'controls_forRange', VAR='i')[0]; f.find(NS + 'field').text = 'j'
R.append(run(m_loopvar, 'variavel de laco renomeada (usos ficam sem escopo)', ['fora de escopo', "'i'"]))
def m_local_leak(root):
    # troca o escopo: usa a local "c" do laco fora dele (em paraCentavos, no RETURN) via nome inexistente fora do laco
    ret = [b for b in blocks(root, 'procedures_defreturn', NAME='paraCentavos')][0]
    # procura um lexical_variable_get de 'inteiro' dentro do valor final e renomeia para 'c'
    cnt = 0
    for x in ret.iter(NS + 'block'):
        if x.get('type') == 'controls_choose':
            for g in x.iter(NS + 'block'):
                if g.get('type') == 'lexical_variable_get' and g.find(NS + 'field').text == 'inteiro':
                    g.find(NS + 'field').text = 'c'; cnt = 1; break
        if cnt: break
R.append(run(m_local_leak, "uso de local do laco ('c') fora do laco", ['fora de escopo', "'c'"]))
def m_stray(root):
    nb = ET.SubElement(root, NS + 'block', {'type': 'math_number', 'id': 'zz2', 'x': '0', 'y': '0'})
    f = ET.SubElement(nb, NS + 'field', {'name': 'NUM'}); f.text = '1'
R.append(run(m_stray, 'bloco solto no topo', ['solto']))
def m_unknown(root):
    b = blocks(root, 'math_abs')[0]; b.set('type', 'math_absx')
R.append(run(m_unknown, 'tipo de bloco desconhecido', ['math_absx']))

# ---------------------------------------------------------------- v1.4: defeitos nos blocos novos (grafico colorido, legenda, cartoes)
# v1.9: o grafico de pizza (Chart1, propriedade Colors) saiu; os defeitos equivalentes vao para a rosca (Canvas)
def m_colors_type(root):
    # PaintColor (cor = numero) recebe uma LISTA vazia no lugar da cor
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if x.get('type') == 'component_set_get' and mu and mu[0].get('property_name') == 'PaintColor':
            v = value(x, 'VALUE'); [v.remove(y) for y in list(v)]
            nb = ET.SubElement(v, NS + 'block', {'type': 'lists_create_with', 'id': 'zz3'})
            ET.SubElement(nb, NS + 'mutation', {'items': '0'})
            return
    raise SystemExit('mutante nao aplicavel: PaintColor')
R.append(run(m_colors_type, 'Canvas.PaintColor recebe lista em vez de cor', ['incompativel', 'list']))
def m_visible_type(root):
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if x.get('type') == 'component_set_get' and mu and mu[0].get('property_name') == 'Visible' and mu[0].get('instance_name') == 'LblVazioGraf':
            v = value(x, 'VALUE'); [v.remove(y) for y in list(v)]
            nb = ET.SubElement(v, NS + 'block', {'type': 'math_number', 'id': 'zz4'})
            f = ET.SubElement(nb, NS + 'field', {'name': 'NUM'}); f.text = '1'
            return
    raise SystemExit('mutante nao aplicavel: LblVazioGraf.Visible')
R.append(run(m_visible_type, 'LblVazioGraf.Visible recebe numero em vez de booleano', ['incompativel', 'boolean']))
def _drawarc(root):
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if x.get('type') == 'component_method' and mu and mu[0].get('method_name') == 'DrawArc':
            return x
    raise SystemExit('mutante nao aplicavel: DrawArc')
def m_drawarc_arity(root):
    x = _drawarc(root); v = value(x, 'ARG7'); x.remove(v)
R.append(run(m_drawarc_arity, 'Canvas.DrawArc sem o ultimo argumento (preencher)', ['component_method', 'ARG7']))
def m_drawarc_bool(root):
    # o 7o argumento (useCenter, booleano) recebe um NUMERO
    x = _drawarc(root); v = value(x, 'ARG6'); [v.remove(y) for y in list(v)]
    nb = ET.SubElement(v, NS + 'block', {'type': 'math_number', 'id': 'zz8'})
    f = ET.SubElement(nb, NS + 'field', {'name': 'NUM'}); f.text = '0'
R.append(run(m_drawarc_bool, 'Canvas.DrawArc com numero no lugar do booleano', ['incompativel', 'ARG6']))
def m_canvas_width_stmt(root):
    # o 'CanvasRosca.Width' do ClockRosca.Timer passa a pedir uma propriedade que o Canvas nao tem
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if x.get('type') == 'component_set_get' and mu and mu[0].get('property_name') == 'Width' and mu[0].get('instance_name') == 'CanvasRosca':
            mu[0].set('property_name', 'Largura'); [c for c in x if tg(c) == 'field'][-1].text = 'Largura'
            return
    raise SystemExit('mutante nao aplicavel: CanvasRosca.Width')
R.append(run(m_canvas_width_stmt, 'CanvasRosca.Width trocado por propriedade inexistente (Largura)', ['Largura']))
def m_pct_arity(root):
    b = blocks(root, 'procedures_callreturn', PROCNAME='formatarPercentual')[0]
    v = value(b, 'ARG0'); b.remove(v)
R.append(run(m_pct_arity, 'formatarPercentual chamado sem argumento', ['procedures_callreturn', 'ARG0']))
def m_create_empty(root):
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if x.get('type') == 'component_method' and mu and mu[0].get('method_name') == 'CreateElement':
            v = value(x, 'ARG2'); [v.remove(y) for y in list(v)]
            return
    raise SystemExit('mutante nao aplicavel: CreateElement')
R.append(run(m_create_empty, 'CreateElement com a imagem (3o argumento) vazia', ['component_method', 'ARG2']))
def m_image_type(root):
    # Button.Image recebe um INSTANTE (Clock1.Now) no lugar de texto -- incompativel (boolean->texto seria aceito pelo App Inventor)
    now = None
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if x.get('type') == 'component_method' and mu and mu[0].get('method_name') == 'Now':
            now = copy.deepcopy(x); break
    if now is None:
        raise SystemExit('mutante nao aplicavel: Clock1.Now')
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if x.get('type') == 'component_set_get' and mu and mu[0].get('property_name') == 'Image':
            v = value(x, 'VALUE'); [v.remove(y) for y in list(v)]
            now.set('id', 'zz5'); v.append(now)
            return
    raise SystemExit('mutante nao aplicavel: Button.Image')
R.append(run(m_image_type, 'Button.Image recebe instante (Clock.Now) em vez de texto', ['incompativel']))
def m_color_make_arity(root):
    b = blocks(root, 'color_make_color')[0]
    v = value(b, 'COLORLIST'); [v.remove(y) for y in list(v)]
R.append(run(m_color_make_arity, 'color_make_color sem a lista RGB', ['COLORLIST']))

# ---- v1.7: blocos genericos, componente como valor e blocos novos
def _generico(root, prop):
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if x.get('type') == 'component_set_get' and mu and mu[0].get('is_generic') == 'true' and mu[0].get('property_name') == prop:
            return x, mu[0]
    raise SystemExit('mutante nao aplicavel: generico ' + prop)
def m_gen_tipo(root):
    # "set Label.Height of component" recebendo um BOTAO (bloco componente BtnEntrada)
    x, mu = _generico(root, 'Height')
    v = value(x, 'COMPONENT'); [v.remove(y) for y in list(v)]
    nb = ET.SubElement(v, NS + 'block', {'type': 'component_component_block', 'id': 'zz6'})
    ET.SubElement(nb, NS + 'mutation', {'component_type': 'Button', 'instance_name': 'BtnEntrada'})
    f = ET.SubElement(nb, NS + 'field', {'name': 'COMPONENT_SELECTOR'}); f.text = 'BtnEntrada'
R.append(run(m_gen_tipo, 'generico de Label recebendo um Button', ['incompativel', 'COMPONENT']))
def m_gen_prop(root):
    x, mu = _generico(root, 'Height')
    mu.set('property_name', 'Altura'); [c for c in x if tg(c) == 'field'][0].text = 'Altura'
R.append(run(m_gen_prop, 'generico com propriedade inexistente (Label.Altura)', ['Altura']))
def m_gen_instance(root):
    x, mu = _generico(root, 'Height')
    mu.set('instance_name', 'LblBarE1')
R.append(run(m_gen_instance, 'generico com instance_name (mistura de generico com especifico)', ['generico']))
def m_compblock(root):
    b = blocks(root, 'component_component_block')[0]
    [c for c in b if tg(c) == 'mutation'][0].set('instance_name', 'LblBarZ9'); [c for c in b if tg(c) == 'field'][0].text = 'LblBarZ9'
R.append(run(m_compblock, 'bloco componente de um componente que nao existe', ['LblBarZ9']))
def m_case_op(root):
    b = blocks(root, 'text_changeCase')[0]
    [c for c in b if tg(c) == 'field'][0].text = 'LOWER'
R.append(run(m_case_op, 'text_changeCase com OP invalido', ['OP']))
def m_replace_num(root):
    b = blocks(root, 'lists_replace_item')[0]
    v = value(b, 'NUM'); [v.remove(y) for y in list(v)]
R.append(run(m_replace_num, 'substituir item da lista sem o indice', ['NUM']))
def m_while_test(root):
    b = blocks(root, 'controls_while')[0]
    v = value(b, 'TEST'); [v.remove(y) for y in list(v)]
    nb = ET.SubElement(v, NS + 'block', {'type': 'math_number', 'id': 'zz7'})
    f = ET.SubElement(nb, NS + 'field', {'name': 'NUM'}); f.text = '1'
R.append(run(m_while_test, 'enquanto com teste numerico', ['incompativel', 'TEST']))
def m_file_arity(root):
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if x.get('type') == 'component_method' and mu and mu[0].get('method_name') == 'SaveFile':
            v = value(x, 'ARG1'); x.remove(v); return
    raise SystemExit('mutante nao aplicavel: SaveFile')
R.append(run(m_file_arity, 'File.SaveFile sem o nome do arquivo', ['component_method', 'ARG1']))
def m_event_param(root):
    for x in root.iter(NS + 'block'):
        if x.get('type') == 'lexical_variable_get' and [c for c in x if tg(c) == 'field'][0].text == 'fileName':
            [c for c in x if tg(c) == 'field'][0].text = 'arquivo'
            mu = [c for c in x if tg(c) == 'mutation']
            for m in mu:
                for e in m:
                    e.set('name', 'arquivo')
            return
    raise SystemExit('mutante nao aplicavel: fileName')
R.append(run(m_event_param, 'parametro de evento inexistente (AfterFileSaved.arquivo)', ['arquivo']))
# ---- v2.0: a extensao LeitorNotificacoes (descricao lida do components.json do proprio pacote)
def _ext(root, metodo):
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if x.get('type') == 'component_method' and mu and mu[0].get('component_type') == 'LeitorNotificacoes' \
                and mu[0].get('method_name') == metodo:
            return x
    raise SystemExit('mutante nao aplicavel: LeitorNotificacoes.' + metodo)
def m_ext_metodo(root):
    x = _ext(root, 'Pendentes'); mu = [c for c in x if tg(c) == 'mutation'][0]; mu.set('method_name', 'Pendente')
R.append(run(m_ext_metodo, 'LeitorNotificacoes.Pendentes trocado por metodo inexistente (Pendente)', ['Pendente']))
def m_ext_aridade(root):
    x = _ext(root, 'Remover'); v = value(x, 'ARG0'); x.remove(v)
R.append(run(m_ext_aridade, 'LeitorNotificacoes.Remover sem o id', ['component_method', 'ARG0']))
def m_ext_evento(root):
    for x in root.iter(NS + 'block'):
        mu = [c for c in x if tg(c) == 'mutation']
        if x.get('type') == 'component_event' and mu and mu[0].get('instance_name') == 'LeitorNotificacoes1' \
                and mu[0].get('event_name') == 'Erro':
            mu[0].set('event_name', 'Falha'); return
    raise SystemExit('mutante nao aplicavel: LeitorNotificacoes1.Erro')
R.append(run(m_ext_evento, 'evento inexistente da extensao (LeitorNotificacoes1.Falha)', ['Falha']))
print()
print('mutacoes detectadas: %d/%d' % (sum(R), len(R)))
sys.exit(0 if all(R) else 1)
