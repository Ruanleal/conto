#!/usr/bin/env python3
"""Verificador independente do .scm (tela) e dos nomes usados nos blocos, contra o CODIGO-FONTE OFICIAL do App Inventor.

Para cada componente do Screen1.scm confere:
  - o tipo existe;
  - cada propriedade e uma propriedade de designer REAL daquele tipo (inclusive herdada) -- pegaria, por exemplo, o
    antigo "TextSize" do ListView, que o servidor ignora em silencio (o nome certo e "FontSize");
  - o valor tem o formato certo (cor &HAARRGGBB, inteiro, decimal, True/False, comprimento);
  - arquivos de imagem/fonte citados existem em assets/;
  - nomes de componentes sao unicos.
Para os blocos confere que toda propriedade (get/set), metodo e evento usado EXISTE na classe Java do componente.

Uso: python3 scm_check.py <Screen1.scm> <Screen1.bky> <pasta_assets> <pasta_runtime_java>
Saida: lista de erros; codigo de saida 0 se nao houver nenhum.
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

META = {'$Name', '$Type', '$Version', 'Uuid'}


# ----------------------------------------------------------------------------- leitor de Java (anotacoes)
def skip_balanced(src, i):
    """src[i] == '(' -> indice logo apos o ')' correspondente (ignora parenteses dentro de strings)."""
    depth, n, in_str = 0, len(src), False
    while i < n:
        c = src[i]
        if in_str:
            if c == '\\':
                i += 1
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return n


ANN = re.compile(r'@(DesignerProperty|SimpleProperty|SimpleFunction|SimpleEvent|DesignerComponent|SimpleObject|UsesLibraries|UsesPermissions|IsColor|Deprecated|Override|SuppressWarnings|UsesActivities|UsesAssets|UsesNativeLibraries|UsesBroadcastReceivers|UsesServices|UsesContentProviders|UsesQueries|UsesAssets|PropertyCategory|DesignerPropertyEditor|SimpleBroadcastReceiver)\b')
DECL = re.compile(r'\s*(?:public|protected|private)?\s*(?:static\s+)?(?:final\s+)?(?:abstract\s+)?(?:synchronized\s+)?([\w<>\[\],.? ]+?)\s+(\w+)\s*\(')


class JavaClass(object):
    def __init__(self, name):
        self.name = name
        self.parent = None
        self.designer = {}    # nome -> (editorType, defaultValue)
        self.simple_props = set()
        self.functions = set()
        self.events = set()


CLS = re.compile(r'^[ \t]*(?:(?:public|protected|private|abstract|final|static)\s+)*class\s+(\w+)(?:\s*<[^{]*?>)?(?:\s+extends\s+([\w.]+))?', re.M)


def parse_java(path):
    src = open(path, encoding='utf-8', errors='replace').read()
    stem = os.path.basename(path)[:-5]
    # a declaracao da classe (nao uma palavra "class" dentro de comentario): so linhas que COMECAM com os modificadores
    decl = next((m for m in CLS.finditer(src) if m.group(1) == stem), None)
    if not decl:
        return None
    cls = JavaClass(stem)
    if decl.group(2):
        cls.parent = decl.group(2).split('.')[-1]
    i = 0
    while True:
        a = ANN.search(src, i)
        if not a:
            break
        # junta todas as anotacoes consecutivas e le a declaracao que vem depois
        j = a.start()
        anns = []
        while True:
            am = ANN.match(src, j)
            if not am:
                break
            name = am.group(1)
            k = am.end()
            while k < len(src) and src[k] in ' \t\r\n':
                k += 1
            args = ''
            if k < len(src) and src[k] == '(':
                e = skip_balanced(src, k)
                args = src[k + 1:e - 1]
                k = e
            anns.append((name, args))
            while k < len(src) and src[k] in ' \t\r\n':
                k += 1
            j = k
        d = DECL.match(src, j)
        if d and anns:
            tipo, nome = d.group(1).strip(), d.group(2)
            for name, args in anns:
                if name == 'DesignerProperty':
                    et = re.search(r'editorType\s*=\s*([\w.]+)', args)
                    dv = re.search(r'defaultValue\s*=\s*(.+?)(?:,\s*\w+\s*=|$)', args, re.S)
                    ea = re.search(r'editorArgs\s*=\s*\{([^}]*)\}', args)
                    escolhas = tuple(re.findall(r'"((?:[^"\\]|\\.)*)"', ea.group(1))) if ea else ()
                    cls.designer[nome] = (et.group(1).split('.')[-1] if et else None, dv.group(1).strip() if dv else None, escolhas)
                elif name == 'SimpleProperty':
                    cls.simple_props.add(nome)
                elif name == 'SimpleFunction':
                    cls.functions.add(nome)
                elif name == 'SimpleEvent':
                    cls.events.add(nome)
        i = max(j, a.end())
    return cls


def load_runtime(runtime_dir):
    classes = {}
    for root, _, files in os.walk(runtime_dir):
        for fn in files:
            if fn.endswith('.java'):
                c = parse_java(os.path.join(root, fn))
                if c and fn[:-5] == c.name:
                    classes[c.name] = c
    return classes


EDITOR_EXT = {'boolean': 'PROPERTY_TYPE_BOOLEAN', 'textArea': 'PROPERTY_TYPE_TEXTAREA', 'string': 'PROPERTY_TYPE_STRING',
              'text': 'PROPERTY_TYPE_TEXT', 'integer': 'PROPERTY_TYPE_INTEGER', 'non_negative_integer': 'PROPERTY_TYPE_NON_NEGATIVE_INTEGER',
              'float': 'PROPERTY_TYPE_FLOAT', 'non_negative_float': 'PROPERTY_TYPE_NON_NEGATIVE_FLOAT', 'color': 'PROPERTY_TYPE_COLOR',
              'asset': 'PROPERTY_TYPE_ASSET'}


def carregar_extensoes(classes, assets_dir, info, errors):
    """v2.0: componentes de EXTENSAO (.aix) nao estao no codigo do App Inventor: o proprio projeto traz a descricao de
    cada um em assets/external_comps/<pacote>/components.json (gerada pelo processador de anotacoes do App Inventor ao
    compilar a extensao). E essa descricao que o editor usa; aqui ela vira uma 'classe' como as do codigo-fonte."""
    base = os.path.join(assets_dir, 'external_comps')
    if not os.path.isdir(base):
        return
    for pacote in sorted(os.listdir(base)):
        cj = os.path.join(base, pacote, 'components.json')
        if not os.path.isfile(cj):
            errors.append('extensao %s sem components.json' % pacote)
            continue
        for d in json.load(open(cj, encoding='utf-8')):
            if d.get('external') != 'true':
                errors.append('extensao %s: %s nao esta marcado como externo' % (pacote, d.get('name')))
            for f in ('classes.jar', 'files/AndroidRuntime.jar', 'files/component_build_infos.json'):
                if not os.path.isfile(os.path.join(base, pacote, f)):
                    errors.append('extensao %s: falta %s' % (pacote, f))
            cls = JavaClass(d['name'])
            cls.parent = 'AndroidNonvisibleComponent' if d.get('nonVisible') == 'true' else 'AndroidViewComponent'
            for pr in d.get('properties', []):
                et = EDITOR_EXT.get(pr['editorType'])
                if et is None:
                    errors.append('extensao %s: editor de propriedade desconhecido: %s' % (pacote, pr['editorType']))
                cls.designer[pr['name']] = (et, pr.get('defaultValue'), ())
            cls.simple_props = {pr['name'] for pr in d.get('blockProperties', [])}
            cls.functions = {m['name'] for m in d.get('methods', [])}
            cls.events = {e['name'] for e in d.get('events', [])}
            if d['name'] in classes:
                errors.append('extensao %s: o nome %s ja e de um componente do App Inventor' % (pacote, d['name']))
            classes[d['name']] = cls
            info.append('extensao %s: componente %s (%d propriedades, %d metodos, %d eventos)' % (
                pacote, d['name'], len(cls.simple_props), len(cls.functions), len(cls.events)))


def hierarchy(classes, name):
    out, seen = [], set()
    while name and name in classes and name not in seen:
        seen.add(name)
        out.append(classes[name])
        name = classes[name].parent
    return out


# ----------------------------------------------------------------------------- validacao de valores
COLOR = re.compile(r'&H[0-9A-Fa-f]{8}$')
INT = re.compile(r'-?\d+$')
FLOAT = re.compile(r'-?\d+(\.\d+)?$')


def length_ok(v):
    return bool(INT.match(v)) and (int(v) in (-1, -2) or int(v) >= 0 or int(v) <= -1001 and int(v) >= -1100)


def check_value(editor, value, assets, where, errors, escolhas=()):
    """Confere o formato do valor segundo o tipo de editor do designer."""
    if editor is None:
        return
    if editor == 'PROPERTY_TYPE_CHOICES' and escolhas and value not in escolhas:      # v1.7 (ex.: FilePicker.Action)
        errors.append('%s: valor %r fora das opcoes do designer %r' % (where, value, list(escolhas)))
        return
    if editor in ('PROPERTY_TYPE_BOOLEAN', 'PROPERTY_TYPE_VISIBILITY'):
        if value not in ('True', 'False'):
            errors.append('%s: valor %r nao e True/False' % (where, value))
    elif editor == 'PROPERTY_TYPE_SIZING':
        if value not in ('Fixed', 'Responsive'):
            errors.append('%s: valor %r nao e Fixed/Responsive' % (where, value))
    elif editor == 'PROPERTY_TYPE_FILESCOPE':         # v1.7: enum FileScope (components/common/FileScope.java)
        if value not in ('App', 'Asset', 'Cache', 'Legacy', 'Private', 'Shared'):
            errors.append('%s: valor %r nao e um FileScope' % (where, value))
    elif editor == 'PROPERTY_TYPE_FILE_ACTION':       # v1.7: enum FileAction (components/common/FileAction.java)
        if value not in ('Pick Existing File', 'Pick New File', 'Pick Directory'):
            errors.append('%s: valor %r nao e um FileAction' % (where, value))
    elif editor in ('PROPERTY_TYPE_INTEGER', 'PROPERTY_TYPE_NON_NEGATIVE_INTEGER', 'PROPERTY_TYPE_SENSOR_DIST_INTERVAL',
                    'PROPERTY_TYPE_SENSOR_TIME_INTERVAL', 'PROPERTY_TYPE_CHART_PIE_RADIUS', 'PROPERTY_TYPE_CHART_TYPE',
                    'PROPERTY_TYPE_CHART_POINT_SHAPE', 'PROPERTY_TYPE_CHART_LINE_TYPE', 'PROPERTY_TYPE_CHART_VALUE_TYPE',
                    'PROPERTY_TYPE_LISTVIEW_LAYOUT', 'PROPERTY_TYPE_TEXTALIGNMENT',
                    'PROPERTY_TYPE_HORIZONTAL_ALIGNMENT', 'PROPERTY_TYPE_VERTICAL_ALIGNMENT',
                    'PROPERTY_TYPE_BUTTON_SHAPE'):
        if not INT.match(value):
            errors.append('%s: valor %r nao e inteiro' % (where, value))
        elif editor == 'PROPERTY_TYPE_NON_NEGATIVE_INTEGER' and int(value) < 0:
            errors.append('%s: valor %r deveria ser >= 0' % (where, value))
    elif editor in ('PROPERTY_TYPE_FLOAT', 'PROPERTY_TYPE_NON_NEGATIVE_FLOAT'):
        if not FLOAT.match(value):
            errors.append('%s: valor %r nao e numero' % (where, value))
        elif editor == 'PROPERTY_TYPE_NON_NEGATIVE_FLOAT' and float(value) < 0:
            errors.append('%s: valor %r deveria ser >= 0' % (where, value))
    elif editor == 'PROPERTY_TYPE_COLOR':
        if not COLOR.match(value):
            errors.append('%s: valor %r nao e cor &HAARRGGBB' % (where, value))
    elif editor in ('PROPERTY_TYPE_LENGTH',):
        if not length_ok(value):
            errors.append('%s: comprimento %r invalido (-1, -2, N>=0 ou -1001..-1100)' % (where, value))
    elif editor in ('PROPERTY_TYPE_ASSET',):
        if value and value not in assets:
            errors.append('%s: arquivo %r nao existe em assets/' % (where, value))
    elif editor in ('PROPERTY_TYPE_TYPEFACE',):
        if value not in ('0', '1', '2', '3') and value not in assets:
            errors.append('%s: fonte %r nao existe em assets/' % (where, value))


# ----------------------------------------------------------------------------- principal
def tag(e):
    return e.tag.split('}')[-1]


def main(scm_path, bky_path, assets_dir, runtime_dir):
    errors, info = [], []
    classes = load_runtime(runtime_dir)
    info.append('classes Java lidas: %d' % len(classes))
    carregar_extensoes(classes, assets_dir, info, errors)
    assets = set(os.listdir(assets_dir)) if os.path.isdir(assets_dir) else set()
    txt = open(scm_path, encoding='utf-8').read()
    data = json.loads(txt[txt.index('{'): txt.rindex('}') + 1])

    comps = {}        # nome -> tipo
    uuids = set()
    n_props = 0

    def visit(node, is_form=False):
        nonlocal n_props
        nome, tipo = node['$Name'], node['$Type']
        if nome in comps:
            errors.append('componente duplicado: ' + nome)
        comps[nome] = tipo
        u = node.get('Uuid')
        if u in uuids and u != '0':
            errors.append('Uuid repetido em %s: %s' % (nome, u))
        uuids.add(u)
        chain = hierarchy(classes, tipo)
        if not chain:
            errors.append('%s: tipo %s nao existe no codigo-fonte do App Inventor' % (nome, tipo))
        else:
            props = {}
            for c in chain:
                for k, v in c.designer.items():
                    props.setdefault(k, v)
            if any(c.name == 'AndroidViewComponent' for c in chain):
                # MockVisibleComponent.addWidthHeightProperties / Column / Row (definidas no editor, nao no runtime)
                props.setdefault('Width', ('PROPERTY_TYPE_LENGTH', None))
                props.setdefault('Height', ('PROPERTY_TYPE_LENGTH', None))
                props.setdefault('Column', ('PROPERTY_TYPE_INTEGER', None))
                props.setdefault('Row', ('PROPERTY_TYPE_INTEGER', None))
            if tipo == 'ImageSprite':
                # MockImageSprite.addWidthHeightProperties (editor): Width/Height existem para o ImageSprite,
                # com editor de comprimento SEM porcentagem (YoungAndroidLengthPropertyEditor(false))
                props.setdefault('Width', ('PROPERTY_TYPE_LENGTH', None))
                props.setdefault('Height', ('PROPERTY_TYPE_LENGTH', None))
                for k in ('Width', 'Height'):
                    if k in node and int(float(node[k])) <= -1000:
                        errors.append('%s (ImageSprite): %s em porcentagem nao e aceito pelo editor' % (nome, k))
            for k, v in node.items():
                if k in META or k == '$Components':
                    continue
                n_props += 1
                if not isinstance(v, str):
                    errors.append('%s.%s: valor nao e texto no .scm' % (nome, k))
                    continue
                if k not in props:
                    errors.append('%s (%s): propriedade de designer INEXISTENTE: %s' % (nome, tipo, k))
                    continue
                check_value(props[k][0], v, assets, '%s.%s' % (nome, k), errors, props[k][2] if len(props[k]) > 2 else ())
        for ch in node.get('$Components', []):
            visit(ch)

    visit(data['Properties'], True)
    info.append('componentes no .scm: %d; propriedades conferidas: %d' % (len(comps), n_props))

    # ---- blocos: propriedades, metodos e eventos precisam existir na classe Java do componente
    root = ET.parse(bky_path).getroot()
    usados = {'prop': set(), 'metodo': set(), 'evento': set(), 'generico': set(), 'componente': set()}
    for b in root.iter():
        if tag(b) != 'block':
            continue
        t = b.get('type')
        if t not in ('component_set_get', 'component_method', 'component_event', 'component_component_block'):
            continue
        m = next((c for c in b if tag(c) == 'mutation'), None)
        if m is None:
            errors.append('bloco %s sem mutacao' % t)
            continue
        inst, ctype = m.get('instance_name'), m.get('component_type')
        if m.get('is_generic') == 'true':
            # v1.7: bloco generico ("set Label.Height of component"): nao tem instancia; o TIPO precisa existir no
            # projeto e a propriedade precisa existir na classe Java desse tipo
            usados['generico'].add((ctype, m.get('property_name') or m.get('method_name')))
            if ctype not in set(comps.values()):
                errors.append('bloco generico de tipo sem nenhum componente no .scm: %s' % ctype)
                continue
            chain = hierarchy(classes, ctype)
            allp = set().union(*[c.simple_props | set(c.designer) for c in chain]) if chain else set()
            if t != 'component_set_get' or m.get('property_name') not in allp:
                errors.append('bloco generico usa %s.%s, que NAO e propriedade do componente' % (ctype, m.get('property_name')))
            continue
        if t == 'component_component_block':
            usados['componente'].add(inst)
            if inst not in comps or comps[inst] != ctype:
                errors.append('bloco componente %s (%s) nao bate com o .scm' % (inst, ctype))
            continue
        if inst not in comps:
            errors.append('bloco usa componente que nao existe no .scm: %s' % inst)
            continue
        if comps[inst] != ctype:
            errors.append('bloco diz %s e do tipo %s mas no .scm e %s' % (inst, ctype, comps[inst]))
            continue
        chain = hierarchy(classes, ctype)
        allp = set().union(*[c.simple_props | set(c.designer) for c in chain]) if chain else set()
        allf = set().union(*[c.functions for c in chain]) if chain else set()
        alle = set().union(*[c.events for c in chain]) if chain else set()
        if t == 'component_set_get':
            p = m.get('property_name')
            usados['prop'].add((ctype, p))
            if p not in allp:
                errors.append('bloco usa %s.%s, que NAO e propriedade do componente' % (ctype, p))
        elif t == 'component_method':
            f = m.get('method_name')
            usados['metodo'].add((ctype, f))
            if f not in allf:
                errors.append('bloco usa %s.%s(), que NAO e metodo do componente' % (ctype, f))
        else:
            e = m.get('event_name')
            usados['evento'].add((ctype, e))
            if e not in alle:
                errors.append('bloco usa evento %s.%s, que NAO existe' % (ctype, e))
    info.append('blocos: %d propriedades, %d metodos, %d eventos distintos conferidos; %d propriedades em blocos '
                'genericos; %d componentes usados como valor' % (
        len(usados['prop']), len(usados['metodo']), len(usados['evento']), len(usados['generico']), len(usados['componente'])))
    return errors, info


if __name__ == '__main__':
    errs, info = main(*sys.argv[1:5])
    for i in info:
        print(i)
    for e in errs:
        print('ERRO:', e)
    print('VERIFICACAO DO .SCM E DOS NOMES: ' + ('OK (0 erros)' if not errs else 'FALHOU (%d erros)' % len(errs)))
    sys.exit(1 if errs else 0)
