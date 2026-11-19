#!/usr/bin/env python3
"""
Verificador ESTATICO independente do Screen1.bky (nao usa nada do gerador).

Confere, contra as definicoes de bloco lidas no codigo-fonte oficial do App Inventor:
  1. XML bem formado, namespace unico, ids unicos, nenhum prefixo ns0:
  2. cada bloco usa so campos / entradas / mutacoes que a definicao oficial tem
  3. nenhum soquete obrigatorio vazio; contagem da mutacao == entradas presentes
  4. compatibilidade de tipos em cada conexao (regras YailTypeToBlocklyType do Blockly do App Inventor)
  5. escopo lexico: toda variavel lida/gravada existe (global, parametro, local, laco, parametro de evento)
  6. procedimentos: chamada com o nome/aridade certos; defreturn so em expressao, defnoreturn so em instrucao
  7. componentes: instancia existe no .scm, tipo bate, propriedade/metodo existe (tabela conferida no fonte Java)
  8. eventos: sem duplicatas; evento existe para o tipo do componente
Uso: python3 -I bkycheck.py <Screen1.bky> <Screen1.scm>
"""
import json
import os
import re
import sys
import collections
import xml.etree.ElementTree as ET

NS = '{https://developers.google.com/blockly/xml}'

# ----------------------------------------------------------------------------- tipos / conexoes
OUT = {'number': {'N', 'S', 'K'}, 'text': {'N', 'S', 'K'}, 'boolean': {'B', 'S'}, 'list': {'A', 'S'},
       'instant': {'I'}, 'any': None, 'none': None}
INP = {'number': {'N'}, 'text': {'S'}, 'boolean': {'B'}, 'list': {'A'}, 'instant': {'I'}, 'any': None}


def _out(t):
    # v1.7: bloco 'componente' (component_component_block): setOutput(true, [typeName, "COMPONENT", "Key"])
    if t.startswith('component:'):
        return {t[10:], 'COMPONENT', 'Key'}
    return OUT[t]


def _inp(t):
    # v1.7: entrada COMPONENT dos blocos genericos: appendValueInput("COMPONENT").setCheck(this.typeName)
    if t.startswith('component:'):
        return {t[10:]}
    return INP[t]


def compatible(out_t, in_t):
    o, i = _out(out_t), _inp(in_t)
    return o is None or i is None or bool(o & i)


# ----------------------------------------------------------------------------- esquema dos blocos
# out: tipo de saida (None = bloco de instrucao); fields; ins: entradas de valor {nome: tipo};
# stmts: entradas de instrucao; dyn: geradores de entradas dinamicas a partir da mutacao
def S(out=None, fields=(), ins=None, stmts=(), stmt_block=False, dyn=None):
    return dict(out=out, fields=set(fields), ins=dict(ins or {}), stmts=set(stmts), stmt_block=stmt_block, dyn=dyn)


def dyn_items(prefix, typ, attr='items'):
    def f(mut):
        n = int(mut.get(attr, '0')) if mut is not None else 0
        return {'%s%d' % (prefix, i): typ for i in range(n)}
    return f


def dyn_logic(mut):
    n = int(mut.get('items', '2')) if mut is not None else 2
    d = {}
    for i in range(n):
        d['A' if i == 0 else 'B' if i == 1 else 'BOOL%d' % i] = 'boolean'
    return d


def dyn_if(mut):
    ne = int(mut.get('elseif', '0')) if mut is not None else 0
    d = {'IF%d' % i: 'boolean' for i in range(ne + 1)}
    return d


def dyn_if_stmts(mut):
    ne = int(mut.get('elseif', '0')) if mut is not None else 0
    has_else = mut is not None and mut.get('else', '0') == '1'
    s = {'DO%d' % i for i in range(ne + 1)}
    if has_else:
        s.add('ELSE')
    return s


def dyn_locals(mut):
    n = len([c for c in (mut if mut is not None else []) if c.tag.split('}')[-1] == 'localname'])
    return {'DECL%d' % i: 'any' for i in range(n)}


def dyn_proc_args(mut):
    n = len([c for c in (mut if mut is not None else []) if c.tag.split('}')[-1] == 'arg'])
    return {'ARG%d' % i: 'any' for i in range(n)}


SCHEMA = {
    'text': S('text', ['TEXT']),
    'math_number': S('number', ['NUM']),
    'logic_boolean': S('boolean', ['BOOL']),
    'lexical_variable_get': S('any', ['VAR']),
    'lexical_variable_set': S(None, ['VAR'], {'VALUE': 'any'}, stmt_block=True),
    'global_declaration': S(None, ['NAME'], {'VALUE': 'any'}),
    'lists_create_with': S('list', [], {}, dyn=dyn_items('ADD', 'any')),
    'text_join': S('text', [], {}, dyn=dyn_items('ADD', 'any')),
    'text_length': S('number', [], {'VALUE': 'text'}),
    'text_isEmpty': S('boolean', [], {'VALUE': 'text'}),
    'text_trim': S('text', [], {'TEXT': 'text'}),
    'text_contains': S('boolean', ['OP'], {'TEXT': 'text', 'PIECE': 'text'}),
    'text_segment': S('text', [], {'TEXT': 'text', 'START': 'number', 'LENGTH': 'number'}),
    'text_replace_all': S('text', [], {'TEXT': 'text', 'SEGMENT': 'text', 'REPLACEMENT': 'text'}),
    'text_starts_at': S('number', [], {'TEXT': 'text', 'PIECE': 'text'}),
    'text_split': S('list', ['OP'], {'TEXT': 'text', 'AT': 'text'}),
    'math_format_as_decimal': S('text', [], {'NUM': 'number', 'PLACES': 'number'}),
    'math_add': S('number', [], {}, dyn=dyn_items('NUM', 'number')),
    'math_multiply': S('number', [], {}, dyn=dyn_items('NUM', 'number')),
    'math_subtract': S('number', [], {'A': 'number', 'B': 'number'}),
    'math_division': S('number', [], {'A': 'number', 'B': 'number'}),
    'math_divide': S('number', ['OP'], {'DIVIDEND': 'number', 'DIVISOR': 'number'}),
    'math_abs': S('number', ['OP'], {'NUM': 'number'}),
    'math_round': S('number', ['OP'], {'NUM': 'number'}),
    'math_is_a_number': S('boolean', ['OP'], {'NUM': 'any'}),
    'math_compare': S('boolean', ['OP'], {'A': 'any', 'B': 'any'}),
    'logic_compare': S('boolean', ['OP'], {'A': 'any', 'B': 'any'}),
    'logic_negate': S('boolean', [], {'BOOL': 'boolean'}),
    'logic_operation': S('boolean', ['OP'], {}, dyn=dyn_logic),
    'lists_select_item': S('any', [], {'LIST': 'list', 'NUM': 'number'}),
    'lists_length': S('number', [], {'LIST': 'list'}),
    'lists_is_list': S('boolean', [], {'ITEM': 'any'}),
    'lists_add_items': S(None, [], {'LIST': 'list'}, dyn=dyn_items('ITEM', 'any'), stmt_block=True),
    'lists_insert_item': S(None, [], {'LIST': 'list', 'INDEX': 'number', 'ITEM': 'any'}, stmt_block=True),
    'lists_remove_item': S(None, [], {'LIST': 'list', 'INDEX': 'number'}, stmt_block=True),
    'controls_if': S(None, [], {}, dyn=dyn_if, stmt_block=True),
    'controls_choose': S('any', [], {'TEST': 'boolean', 'THENRETURN': 'any', 'ELSERETURN': 'any'}),
    'controls_forEach': S(None, ['VAR'], {'LIST': 'list'}, ['DO'], stmt_block=True),
    'controls_forRange': S(None, ['VAR'], {'START': 'number', 'END': 'number', 'STEP': 'number'}, ['DO'], stmt_block=True),
    'controls_do_then_return': S('any', [], {'VALUE': 'any'}, ['STM']),
    'local_declaration_expression': S('any', [], {'RETURN': 'any'}, dyn=dyn_locals),
    'local_declaration_statement': S(None, [], {}, ['STACK'], stmt_block=True, dyn=dyn_locals),
    'procedures_defnoreturn': S(None, ['NAME'], {}, ['STACK']),
    'procedures_defreturn': S(None, ['NAME'], {'RETURN': 'any'}),
    'procedures_callnoreturn': S(None, ['PROCNAME'], {}, stmt_block=True, dyn=dyn_proc_args),
    'procedures_callreturn': S('any', ['PROCNAME'], {}, dyn=dyn_proc_args),
    'color_make_color': S('number', [], {'COLORLIST': 'list'}),
    'component_event': S(None, ['COMPONENT_SELECTOR'], {}, ['DO']),
    # v1.7 (definicoes conferidas em blocklyeditor/src/blocks/text.js, lists.js e control.js)
    'text_changeCase': S('text', ['OP'], {'TEXT': 'text'}),
    'lists_replace_item': S(None, [], {'LIST': 'list', 'NUM': 'number', 'ITEM': 'any'}, stmt_block=True),
    'lists_position_in': S('number', [], {'ITEM': 'any', 'LIST': 'list'}),
    'lists_copy': S('list', [], {'LIST': 'list'}),
    'lists_to_csv_table': S('text', [], {'LIST': 'list'}),
    'lists_from_csv_table': S('list', [], {'TEXT': 'text'}),
    'lists_join_with_separator': S('text', [], {'SEPARATOR': 'text', 'LIST': 'list'}),
    'controls_while': S(None, [], {'TEST': 'boolean'}, ['DO'], stmt_block=True),
}
OPS_VALIDOS = {'text_changeCase': {'UPCASE', 'DOWNCASE'}, 'text_split': {'SPLIT'}}

# propriedades e metodos usados (tipos conferidos no codigo Java oficial)
PROPS = {
    ('TextBox', 'Text'): 'text', ('Label', 'Text'): 'text',
    ('Spinner', 'SelectionIndex'): 'number', ('Spinner', 'Selection'): 'text',
    ('Spinner', 'ElementsFromString'): 'text',
    ('ListView', 'Elements'): 'list', ('ListView', 'SelectionIndex'): 'number',
    ('Label', 'Visible'): 'boolean', ('VerticalArrangement', 'Visible'): 'boolean',
    ('Button', 'BackgroundColor'): 'number', ('Button', 'TextColor'): 'number',
    ('Button', 'Image'): 'text',                      # v1.4: aba ativa/inativa troca a imagem do botao
    ('Chart', 'Visible'): 'boolean',                  # v1.4: grafico some quando nao ha lancamentos
    ('ChartData2D', 'Colors'): 'list',                # v1.4: cores das fatias (verde/vermelho), lista de ARGB
    # v1.5 (tipos conferidos no codigo Java oficial: Image.Picture(String), Clock.TimerEnabled(boolean), Image da HVArrangement(String))
    ('Button', 'Text'): 'text', ('Image', 'Picture'): 'text', ('HorizontalArrangement', 'Image'): 'text',
    ('Clock', 'TimerEnabled'): 'boolean', ('Label', 'TextColor'): 'number',
    # v1.6 (assinaturas conferidas no codigo Java oficial; ver secao 1 do relatorio)
    ('ImagePicker', 'Selection'): 'text',                                   # String Selection()
    ('Button', 'Visible'): 'boolean',                                        # AndroidViewComponent.Visible(boolean)
    ('ImageSprite', 'Visible'): 'boolean',                                   # Sprite.Visible(boolean)
    ('ImageSprite', 'X'): 'number', ('ImageSprite', 'Y'): 'number',          # Sprite.X(double) / Y(double)
    ('ImageSprite', 'Width'): 'number', ('ImageSprite', 'Height'): 'number', # ImageSprite.Width(int) / Height(int)
    ('ImageSprite', 'Picture'): 'text',                                      # ImageSprite.Picture(String)
    ('Form', 'BackgroundColor'): 'number',                                   # Form.BackgroundColor(int)
    ('VerticalArrangement', 'Image'): 'text',                                # HVArrangement.Image(String)
    ('HorizontalArrangement', 'BackgroundColor'): 'number',                  # HVArrangement.BackgroundColor(int)
    ('TextBox', 'TextColor'): 'number', ('TextBox', 'HintColor'): 'number',  # TextBoxBase.TextColor(int) / HintColor(int)
    ('ListView', 'BackgroundColor'): 'number', ('ListView', 'ElementColor'): 'number',
    ('ListView', 'SelectionColor'): 'number', ('ListView', 'TextColor'): 'number',
    ('ListView', 'TextColorDetail'): 'number',                               # ListView.<...>(int argb)
    ('Chart', 'BackgroundColor'): 'number',                                  # Chart.BackgroundColor(int)
    ('Label', 'WidthPercent'): 'number',                                     # AndroidViewComponent.WidthPercent(int), so escrita
    # v1.7 (assinaturas conferidas no codigo Java oficial)
    ('Label', 'Height'): 'number',                                           # AndroidViewComponent.Height(int)
    ('Label', 'BackgroundColor'): 'number',                                  # Label.BackgroundColor(int argb)
    ('ListView', 'Height'): 'number', ('ListView', 'Visible'): 'boolean',    # AndroidViewComponent.Height(int) / Visible(boolean)
    ('HorizontalArrangement', 'Visible'): 'boolean',                         # AndroidViewComponent.Visible(boolean)
    ('Clock', 'TimerInterval'): 'number',                                    # Clock.TimerInterval(int)
    ('FilePicker', 'Selection'): 'text',                                     # FilePicker: String Selection() (so leitura)
    ('FilePicker', 'Image'): 'text', ('FilePicker', 'TextColor'): 'number',  # ButtonBase.Image(String) / TextColor(int)
    # v1.8: DatePicker (ButtonBase): Text/TextColor; Year/Month/Day(int, so leitura); Button.Enabled(boolean)
    ('DatePicker', 'Text'): 'text', ('DatePicker', 'TextColor'): 'number',
    ('DatePicker', 'Year'): 'number', ('DatePicker', 'Month'): 'number', ('DatePicker', 'Day'): 'number',
    ('Button', 'Enabled'): 'boolean',
    # v1.9: rosca desenhada no Canvas. Canvas.PaintColor(int argb); Width() = AndroidViewComponent.Width() -> int
    #       (largura MEDIDA na tela: 0 antes do primeiro layout)
    ('Canvas', 'PaintColor'): 'number', ('Canvas', 'Width'): 'number',
    # v1.9: "Escolher da galeria" com o fundo de pilula do tema: ButtonBase.Image(String) / TextColor(int)
    ('ImagePicker', 'Image'): 'text', ('ImagePicker', 'TextColor'): 'number',
}
# v2.0: TextBox.BackgroundColor(int) (TextBoxBase) -- a caixa "Colar mensagem" acompanha o fundo do tema
PROPS[('TextBox', 'BackgroundColor')] = 'number'
SO_ESCRITA = {('Label', 'WidthPercent')}       # propriedades sem bloco "get"
SO_LEITURA = {('ImagePicker', 'Selection'), ('FilePicker', 'Selection'),
              ('DatePicker', 'Year'), ('DatePicker', 'Month'), ('DatePicker', 'Day')}    # propriedades sem bloco "set"
METHODS = {
    ('TinyDB', 'StoreValue'): (None, ['text', 'any']),
    ('TinyDB', 'GetValue'): ('any', ['text', 'any']),
    ('Clock', 'Now'): ('instant', []),
    ('Clock', 'FormatDate'): ('text', ['instant', 'text']),
    ('Notifier', 'ShowAlert'): (None, ['any']),
    ('TextBox', 'HideKeyboard'): (None, []),          # v1.5
    ('Notifier', 'ShowMessageDialog'): (None, ['text', 'text', 'text']),
    ('Notifier', 'ShowChooseDialog'): (None, ['text', 'text', 'text', 'text', 'boolean']),
    ('ChartData2D', 'AddEntry'): (None, ['text', 'text']),
    ('ChartData2D', 'Clear'): (None, []),
    ('ListView', 'CreateElement'): ('any', ['text', 'text', 'text']),   # v1.4: (titulo, detalhe, imagem) -> dicionario
    ('ImagePicker', 'Open'): (None, []),                                # v1.6: Picker.Open()
    # v1.7: Clock.Year/Month/DayOfMonth(Calendar) -> int; File.SaveFile(String, String); File.ReadFrom(String);
    #       Sharing.ShareFile(String)
    ('Clock', 'Year'): ('number', ['instant']), ('Clock', 'Month'): ('number', ['instant']),
    ('Clock', 'DayOfMonth'): ('number', ['instant']),
    ('File', 'SaveFile'): (None, ['text', 'text']), ('File', 'ReadFrom'): (None, ['text']),
    ('Sharing', 'ShareFile'): (None, ['text']),
    # v1.8: Clock.SystemTime() -> long; Clock.AddDays(Calendar, int) -> Calendar; DatePicker.SetDateToDisplay(int, int, int)
    ('Clock', 'SystemTime'): ('number', []), ('Clock', 'AddDays'): ('instant', ['instant', 'number']),
    ('Clock', 'GetMillis'): ('number', ['instant']), ('Clock', 'MakeInstantFromMillis'): ('instant', ['number']),
    ('Clock', 'MakeInstantFromParts'): ('instant', ['number'] * 6),
    ('DatePicker', 'SetDateToDisplay'): (None, ['number', 'number', 'number']),
    # v1.9: Canvas.Clear(); Canvas.DrawArc(int left, int top, int right, int bottom, float startAngle,
    #       float sweepAngle, boolean useCenter, boolean fill)
    ('Canvas', 'Clear'): (None, []),
    ('Canvas', 'DrawArc'): (None, ['number'] * 6 + ['boolean', 'boolean']),
    # v1.9: Camera.TakePicture() (sem retorno; a foto chega em AfterPicture)
    ('Camera', 'TakePicture'): (None, []),
}
EVENTS = {('Form', 'Initialize'): [], ('Button', 'Click'): [], ('ListView', 'AfterPicking'): [],
          ('Notifier', 'AfterChoosing'): ['choice'],
          ('Image', 'Click'): [], ('TextBox', 'TextChanged'): [], ('Clock', 'Timer'): [],   # v1.5
          # v1.6: Canvas.Touched(float x, float y, boolean touchedAnySprite); Picker.AfterPicking()
          ('Canvas', 'Touched'): ['x', 'y', 'touchedAnySprite'], ('ImagePicker', 'AfterPicking'): [],
          # v1.7: File.AfterFileSaved(String fileName), File.GotText(String text), Picker.AfterPicking(),
          #       Form.ErrorOccurred(Component component, String functionName, int errorNumber, String message)
          ('File', 'AfterFileSaved'): ['fileName'], ('File', 'GotText'): ['text'], ('FilePicker', 'AfterPicking'): [],
          ('Form', 'ErrorOccurred'): ['component', 'functionName', 'errorNumber', 'message'],
          ('DatePicker', 'AfterDateSet'): [],                                                  # v1.8
          ('Camera', 'AfterPicture'): ['image']}                                               # v1.9: AfterPicture(String image)


def tg(e):
    return e.tag.split('}')[-1]


TIPO_EXT = {'boolean': 'boolean', 'text': 'text', 'number': 'number', 'list': 'list', 'any': 'any',
            'InstantInTime': 'instant', 'dictionary': 'any', 'component': 'any'}


def carregar_extensoes(bky_path):
    """v2.0: metodos, eventos e propriedades dos componentes de EXTENSAO vem da descricao que o proprio projeto traz
    (assets/external_comps/<pacote>/components.json, gerada pelo App Inventor ao compilar a extensao)."""
    base = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(bky_path)), '..', '..', '..', '..', 'assets',
                                         'external_comps'))
    if not os.path.isdir(base):
        base = os.environ.get('CONTO_EXT_DIR', '')     # copia de teste do .bky fora do pacote (autoteste)
    if not base or not os.path.isdir(base):
        return []
    lidos = []
    for pacote in sorted(os.listdir(base)):
        cj = os.path.join(base, pacote, 'components.json')
        if not os.path.isfile(cj):
            continue
        for d in json.load(open(cj, encoding='utf-8')):
            t = d['name']
            for m in d.get('methods', []):
                METHODS[(t, m['name'])] = (TIPO_EXT[m['returnType']] if m.get('returnType') else None,
                                           [TIPO_EXT[pp['type']] for pp in m.get('params', [])])
            for e in d.get('events', []):
                EVENTS[(t, e['name'])] = [pp['name'] for pp in e.get('params', [])]
            for pr in d.get('blockProperties', []):
                PROPS[(t, pr['name'])] = TIPO_EXT[pr['type']]
                if pr.get('rw') == 'read-only':
                    SO_LEITURA.add((t, pr['name']))
                elif pr.get('rw') == 'write-only':
                    SO_ESCRITA.add((t, pr['name']))
            lidos.append(t)
    return lidos


class Checker:
    def __init__(self, bky, scm):
        self.extensoes = carregar_extensoes(bky)
        self.errors = []
        self.warnings = []
        self.raw = open(bky, encoding='utf-8').read()
        self.root = ET.fromstring(self.raw)
        data = open(scm, encoding='utf-8').read()
        self.scm = json.loads(data[data.index('{'): data.rindex('}') + 1])
        self.comps = {}

        def reg(n):
            self.comps[n['$Name']] = n['$Type']
            for c in n.get('$Components', []):
                reg(c)
        reg(self.scm['Properties'])
        self.globals = set()
        self.procs = {}
        self.stats = collections.Counter()

    def err(self, msg):
        self.errors.append(msg)

    # ---------------------------------------------------------------- utilitarios
    @staticmethod
    def kids(b, kind):
        return [c for c in b if tg(c) == kind]

    def field(self, b, name):
        for c in self.kids(b, 'field'):
            if c.get('name') == name:
                return c.text or ''
        return None

    def value(self, b, name):
        for c in self.kids(b, 'value'):
            if c.get('name') == name:
                bl = [x for x in c if tg(x) == 'block']
                return bl[0] if bl else None
        return None

    def stmt(self, b, name):
        for c in self.kids(b, 'statement'):
            if c.get('name') == name:
                bl = [x for x in c if tg(x) == 'block']
                return bl[0] if bl else None
        return None

    def nxt(self, b):
        for c in self.kids(b, 'next'):
            bl = [x for x in c if tg(x) == 'block']
            return bl[0] if bl else None
        return None

    def mut(self, b):
        m = self.kids(b, 'mutation')
        return m[0] if m else None

    def where(self, b):
        return '%s(id=%s)' % (b.get('type'), b.get('id'))

    # ---------------------------------------------------------------- 1. estrutura
    def check_structure(self):
        if self.root.tag != NS + 'xml':
            self.err('raiz nao e <xml> no namespace do Blockly: ' + self.root.tag)
        if 'ns0' in self.raw:
            self.err('prefixo ns0 presente no arquivo')
        ids = collections.Counter(b.get('id') for b in self.root.iter(NS + 'block'))
        for k, v in ids.items():
            if v > 1:
                self.err('id duplicado: %s (%d vezes)' % (k, v))
        for e in self.root.iter():
            if not e.tag.startswith(NS):
                self.err('elemento fora do namespace: ' + e.tag)
        ya = [c for c in self.root if tg(c) == 'yacodeblocks']
        if len(ya) != 1 or ya[0].get('ya-version') != '237' or ya[0].get('language-version') != '39':
            self.err('elemento yacodeblocks ausente ou com versoes diferentes de 237/39')
        self.stats['blocos'] = sum(ids.values())

    # ---------------------------------------------------------------- 2/3/4. esquema e tipos
    def out_type(self, b):
        t = b.get('type')
        if t in SCHEMA:
            return SCHEMA[t]['out'] or 'none'
        if t == 'component_set_get':
            m = self.mut(b)
            if m.get('set_or_get') != 'get':
                return 'none'
            return PROPS.get((m.get('component_type'), m.get('property_name')), 'any')
        if t == 'component_component_block':
            return 'component:' + (self.mut(b).get('component_type') or '?')
        if t == 'component_method':
            m = self.mut(b)
            r = METHODS.get((m.get('component_type'), m.get('method_name')))
            return (r[0] or 'none') if r else 'any'
        return 'any'

    def check_block(self, b, expect_value):
        t = b.get('type')
        self.stats['tipo:' + t] += 1
        m = self.mut(b)
        # --- componentes
        if t == 'component_component_block':
            inst, ctype = m.get('instance_name'), m.get('component_type')
            self._check_comp(b, inst, ctype)
            present = {c.get('name') for c in self.kids(b, 'field')}
            if present != {'COMPONENT_SELECTOR'} or self.field(b, 'COMPONENT_SELECTOR') != inst:
                self.err('%s: campo COMPONENT_SELECTOR ausente/diferente da mutacao' % self.where(b))
            self.stats['componente:' + inst] += 1
            return dict(out='component:' + str(ctype), ins={}, stmts=set(), stmt_block=False)
        if t == 'component_set_get' and m.get('is_generic') == 'true':
            # bloco generico: "set/get <Tipo>.<Prop> of component"; sem instance_name, so o campo PROP
            ctype, prop, sog = m.get('component_type'), m.get('property_name'), m.get('set_or_get')
            if m.get('instance_name') is not None:
                self.err('%s: bloco generico com instance_name' % self.where(b))
            present = {c.get('name') for c in self.kids(b, 'field')}
            if present != {'PROP'} or self.field(b, 'PROP') != prop:
                self.err('%s: bloco generico deve ter so o campo PROP = property_name' % self.where(b))
            if ctype not in set(self.comps.values()):
                self.err('%s: bloco generico de um tipo que nao existe no projeto: %s' % (self.where(b), ctype))
            ptype = PROPS.get((ctype, prop))
            if ptype is None:
                self.err('%s: propriedade %s.%s nao esta na tabela conferida' % (self.where(b), ctype, prop))
                ptype = 'any'
            if sog == 'get' and (ctype, prop) in SO_ESCRITA:
                self.err('%s: %s.%s so pode ser escrita' % (self.where(b), ctype, prop))
            if sog == 'set' and (ctype, prop) in SO_LEITURA:
                self.err('%s: %s.%s so pode ser lida' % (self.where(b), ctype, prop))
            self.stats['generico:%s.%s' % (ctype, prop)] += 1
            ins = {'COMPONENT': 'component:' + str(ctype)}
            if sog == 'set':
                ins['VALUE'] = ptype
            return dict(out=('none' if sog == 'set' else ptype), ins=ins, stmts=set(), stmt_block=(sog == 'set'))
        if t == 'component_set_get':
            inst, ctype = m.get('instance_name'), m.get('component_type')
            prop, sog = m.get('property_name'), m.get('set_or_get')
            if m.get('is_generic') != 'false':
                self.err('%s: is_generic deve ser "false" ou "true"' % self.where(b))
            self._check_comp(b, inst, ctype)
            if self.field(b, 'COMPONENT_SELECTOR') != inst or self.field(b, 'PROP') != prop:
                self.err('%s: campos COMPONENT_SELECTOR/PROP diferentes da mutacao' % self.where(b))
            ptype = PROPS.get((ctype, prop))
            if ptype is None:
                self.err('%s: propriedade %s.%s nao esta na tabela conferida' % (self.where(b), ctype, prop))
                ptype = 'any'
            if sog == 'get' and (ctype, prop) in SO_ESCRITA:
                self.err('%s: %s.%s so pode ser escrita (nao existe bloco de leitura)' % (self.where(b), ctype, prop))
            if sog == 'set' and (ctype, prop) in SO_LEITURA:
                self.err('%s: %s.%s so pode ser lida (nao existe bloco de escrita)' % (self.where(b), ctype, prop))
            ins = {'VALUE': ptype} if sog == 'set' else {}
            return dict(out=('none' if sog == 'set' else ptype), ins=ins, stmts=set(), stmt_block=(sog == 'set'))
        if t == 'component_method':
            inst, ctype, meth = m.get('instance_name'), m.get('component_type'), m.get('method_name')
            self._check_comp(b, inst, ctype)
            sig = METHODS.get((ctype, meth))
            if sig is None:
                self.err('%s: metodo %s.%s nao esta na tabela conferida' % (self.where(b), ctype, meth))
                return dict(out='any', ins={}, stmts=set(), stmt_block=False)
            ins = {'ARG%d' % i: tp for i, tp in enumerate(sig[1])}
            return dict(out=(sig[0] or 'none'), ins=ins, stmts=set(), stmt_block=(sig[0] is None))
        sc = SCHEMA.get(t)
        if sc is None:
            self.err('tipo de bloco sem esquema (nao conferido): ' + t)
            return None
        ins = dict(sc['ins'])
        stmts = set(sc['stmts'])
        if sc['dyn']:
            d = sc['dyn'](m)
            ins.update(d)
            if t == 'controls_if':
                stmts |= dyn_if_stmts(m)
        # campos
        present = {c.get('name') for c in self.kids(b, 'field')}
        extra = present - sc['fields']
        if t in ('procedures_defnoreturn', 'procedures_defreturn'):
            extra = {x for x in extra if not re.fullmatch(r'VAR\d+', x)}
        if t in ('local_declaration_expression', 'local_declaration_statement'):
            extra = {x for x in extra if not re.fullmatch(r'VAR\d+', x)}
        if extra:
            self.err('%s: campos nao previstos %s' % (self.where(b), sorted(extra)))
        missing = sc['fields'] - present
        if missing:
            self.err('%s: campos faltando %s' % (self.where(b), sorted(missing)))
        if t in OPS_VALIDOS and self.field(b, 'OP') not in OPS_VALIDOS[t]:
            self.err('%s: OP invalido %r' % (self.where(b), self.field(b, 'OP')))
        return dict(out=sc['out'] or 'none', ins=ins, stmts=stmts, stmt_block=sc['stmt_block'])

    def _check_comp(self, b, inst, ctype):
        if inst not in self.comps:
            self.err('%s: componente inexistente no .scm: %s' % (self.where(b), inst))
        elif self.comps[inst] != ctype:
            self.err('%s: tipo do componente %s e %s no .scm, mas %s no bloco' % (self.where(b), inst, self.comps[inst], ctype))

    # ---------------------------------------------------------------- 5/6/7. caminhada com escopo
    def walk_stmts(self, b, env):
        while b is not None:
            self.walk(b, env, as_value=False)
            if b.get('type') == 'local_declaration_statement':
                pass
            b = self.nxt(b)

    def walk_value(self, parent, name, in_type, env):
        child = self.value(parent, name)
        if child is None:
            self.err('%s: soquete obrigatorio vazio: %s' % (self.where(parent), name))
            return
        ot = self.out_type(child)
        if ot == 'none':
            self.err('%s: a entrada %s recebeu um bloco de instrucao (%s)' % (self.where(parent), name, child.get('type')))
        elif not compatible(ot, in_type):
            self.err('%s: tipo incompativel na entrada %s: saida %s -> entrada %s (bloco %s)' %
                     (self.where(parent), name, ot, in_type, child.get('type')))
        self.walk(child, env, as_value=True)

    def walk(self, b, env, as_value):
        t = b.get('type')
        info = self.check_block(b, as_value)
        if info is None:
            return
        m = self.mut(b)
        if as_value and info['out'] == 'none':
            self.err('%s: bloco de instrucao usado como valor' % self.where(b))
        if (not as_value) and info['out'] != 'none':
            self.err('%s: bloco de valor usado como instrucao' % self.where(b))
        # entradas declaradas x presentes
        declared = set(info['ins'])
        present_vals = {c.get('name') for c in self.kids(b, 'value')}
        if present_vals - declared:
            self.err('%s: entradas de valor nao previstas: %s' % (self.where(b), sorted(present_vals - declared)))
        present_stm = {c.get('name') for c in self.kids(b, 'statement')}
        if present_stm - info['stmts']:
            self.err('%s: entradas de instrucao nao previstas: %s' % (self.where(b), sorted(present_stm - info['stmts'])))
        # ---- escopo e semantica por tipo
        if t == 'lexical_variable_get' or t == 'lexical_variable_set':
            name = self.field(b, 'VAR')
            if name.startswith('global '):
                if name[7:] not in self.globals:
                    self.err('%s: variavel global inexistente: %s' % (self.where(b), name))
            elif name not in env:
                self.err('%s: variavel fora de escopo / inexistente: %r (em escopo: %s)' % (self.where(b), name, sorted(env)))
            if t == 'lexical_variable_get' and m is not None:
                ep = [c.get('name') for c in m if tg(c) == 'eventparam']
                for e in ep:
                    if e not in env:
                        self.err('%s: eventparam %s fora do evento' % (self.where(b), e))
        if t == 'global_declaration':
            self.walk_value(b, 'VALUE', 'any', set())
            return
        if t == 'procedures_defnoreturn' or t == 'procedures_defreturn':
            params = [c.get('name') for c in m if tg(c) == 'arg']
            fld = [self.field(b, 'VAR%d' % i) for i in range(len(params))]
            if params != fld:
                self.err('%s: parametros da mutacao %s != campos %s' % (self.where(b), params, fld))
            penv = set(params)
            if t == 'procedures_defnoreturn':
                self.walk_stmts(self.stmt(b, 'STACK'), penv)
            else:
                self.walk_value(b, 'RETURN', 'any', penv)
            return
        if t in ('procedures_callnoreturn', 'procedures_callreturn'):
            name = self.field(b, 'PROCNAME')
            if m.get('name') != name:
                self.err('%s: mutacao name=%r != PROCNAME=%r' % (self.where(b), m.get('name'), name))
            d = self.procs.get(name)
            if d is None:
                self.err('%s: procedimento inexistente: %s' % (self.where(b), name))
            else:
                dtype, dparams = d
                args = [c.get('name') for c in m if tg(c) == 'arg']
                if args != dparams:
                    self.err('%s: argumentos %s != parametros da definicao %s' % (self.where(b), args, dparams))
                if (t == 'procedures_callreturn') != (dtype == 'procedures_defreturn'):
                    self.err('%s: chamada %s para definicao %s' % (self.where(b), t, dtype))
        if t == 'component_event':
            inst, ctype, ev = m.get('instance_name'), m.get('component_type'), m.get('event_name')
            self._check_comp(b, inst, ctype)
            params = EVENTS.get((ctype, ev))
            if params is None:
                self.err('%s: evento %s.%s nao esta na tabela' % (self.where(b), ctype, ev))
                params = []
            key = (inst, ev)
            if key in self.seen_events:
                self.err('evento duplicado: %s.%s' % key)
            self.seen_events.add(key)
            self.walk_stmts(self.stmt(b, 'DO'), set(params))
            return
        # ---- percorrer entradas de valor
        if t == 'controls_forEach':
            self.walk_value(b, 'LIST', 'list', env)
            self.walk_stmts(self.stmt(b, 'DO'), env | {self.field(b, 'VAR')})
            return
        if t == 'controls_forRange':
            for n in ('START', 'END', 'STEP'):
                self.walk_value(b, n, 'number', env)
            self.walk_stmts(self.stmt(b, 'DO'), env | {self.field(b, 'VAR')})
            return
        if t in ('local_declaration_statement', 'local_declaration_expression'):
            names = [c.get('name') for c in m if tg(c) == 'localname']
            fld = [self.field(b, 'VAR%d' % i) for i in range(len(names))]
            if names != fld:
                self.err('%s: localname %s != campos VARn %s' % (self.where(b), names, fld))
            for i in range(len(names)):
                self.walk_value(b, 'DECL%d' % i, 'any', env)      # iniciais no escopo externo
            inner = env | set(names)
            if t == 'local_declaration_statement':
                self.walk_stmts(self.stmt(b, 'STACK'), inner)
            else:
                self.walk_value(b, 'RETURN', 'any', inner)
            return
        if t == 'controls_do_then_return':
            self.walk_stmts(self.stmt(b, 'STM'), env)
            self.walk_value(b, 'VALUE', 'any', env)
            return
        if t == 'controls_if':
            for i, n in enumerate(sorted(n for n in info['ins'] if n.startswith('IF'))):
                self.walk_value(b, n, 'boolean', env)
            for n in sorted(info['stmts']):
                self.walk_stmts(self.stmt(b, n), env)
            return
        for n, tp in sorted(info['ins'].items()):
            self.walk_value(b, n, tp, env)
        for n in sorted(info['stmts']):
            self.walk_stmts(self.stmt(b, n), env)

    # ---------------------------------------------------------------- execucao
    def run(self):
        self.check_structure()
        self.seen_events = set()
        tops = [c for c in self.root if tg(c) == 'block']
        for b in tops:
            if b.get('type') == 'global_declaration':
                n = self.field(b, 'NAME')
                if n in self.globals:
                    self.err('global duplicada: ' + n)
                self.globals.add(n)
            elif b.get('type') in ('procedures_defnoreturn', 'procedures_defreturn'):
                n = self.field(b, 'NAME')
                if n in self.procs:
                    self.err('procedimento duplicado: ' + n)
                self.procs[n] = (b.get('type'), [c.get('name') for c in self.mut(b) if tg(c) == 'arg'])
        for b in tops:
            ty = b.get('type')
            if ty not in ('global_declaration', 'procedures_defnoreturn', 'procedures_defreturn', 'component_event'):
                self.err('bloco solto no topo do arquivo: ' + self.where(b))
                continue
            self.walk(b, set(), as_value=False if ty != 'procedures_defreturn' else False)
        # definicoes/globais nunca usadas (aviso)
        used_g = set()
        used_p = set()
        for b in self.root.iter(NS + 'block'):
            if b.get('type') in ('lexical_variable_get', 'lexical_variable_set'):
                n = self.field(b, 'VAR')
                if n.startswith('global '):
                    used_g.add(n[7:])
            if b.get('type') in ('procedures_callnoreturn', 'procedures_callreturn'):
                used_p.add(self.field(b, 'PROCNAME'))
        for g in sorted(self.globals - used_g):
            self.warnings.append('global nunca usada: ' + g)
        for p in sorted(set(self.procs) - used_p):
            self.warnings.append('procedimento nunca chamado: ' + p)
        return self


def main():
    c = Checker(sys.argv[1], sys.argv[2]).run()
    print('blocos:', c.stats['blocos'])
    print('componentes de extensao (descricao lida do proprio pacote):', c.extensoes)
    print('globais:', sorted(c.globals))
    print('procedimentos:', {k: v[1] for k, v in c.procs.items()})
    print('eventos:', sorted(c.seen_events))
    for w in c.warnings:
        print('AVISO:', w)
    if c.errors:
        print('\nERROS (%d):' % len(c.errors))
        for e in c.errors:
            print('  -', e)
        sys.exit(1)
    print('\nVERIFICACAO ESTATICA: OK (0 erros)')


if __name__ == '__main__':
    main()
