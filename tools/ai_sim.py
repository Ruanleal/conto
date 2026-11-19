#!/usr/bin/env python3
"""
Simulador (interpretador de arvore) do subconjunto do MIT App Inventor usado pelo Conto.

Executa o Screen1.bky (blocos) e o Screen1.scm (componentes) de verdade, bloco por bloco.
A semantica das primitivas foi copiada do codigo-fonte oficial lido em
appinventor-sources (runtime.scm, Spinner.java, TinyDB.java, JsonUtil.java,
YailNumberToString.java, ElementsUtil.java), e NAO de memoria:

  * text_replace_all  -> literal (Pattern.quote), nao regex
  * format-as-decimal -> (format #f "~,2f" n)  (ponto decimal, nunca virgula)
  * coerce-to-number  -> padded-string->number (trim + string->number do Kawa)
  * yail-equal?       -> equal? e, se falhar, comparacao numerica de strings numericas
  * yail-for-range    -> nao executa se start > end com passo positivo
  * Spinner.Selection -> item na posicao do Spinner (SelectionIndex); indice invalido => 0 / ""
  * TinyDB            -> JSON em SharedPreferences; strings "true"/"false" voltam como booleanos
  * Qualquer erro de runtime (indice de lista invalido, segmento fora do texto, etc.)
    aborta o evento e e registrado em app.runtime_errors, como o App Inventor faz.

Limite honesto: isto NAO e o runtime do MIT rodando num Android. E uma reproducao fiel do
comportamento lido no codigo-fonte; o teste final precisa ser feito no aparelho.
"""
import json
import math
import os
import re
import datetime
import xml.etree.ElementTree as ET
from fractions import Fraction


class YailRuntimeError(Exception):
    """Erro de runtime do App Inventor (mostra dialogo e aborta o manipulador de evento)."""


# --------------------------------------------------------------------------- utilidades XML
def _tag(el):
    return el.tag.split('}')[-1]


def _field(el, name, default=None):
    for c in el:
        if _tag(c) == 'field' and c.get('name') == name:
            return c.text if c.text is not None else ''
    return default


def _value(el, name):
    for c in el:
        if _tag(c) == 'value' and c.get('name') == name:
            for b in c:
                if _tag(b) == 'block':
                    return b
    return None


def _stmt(el, name):
    for c in el:
        if _tag(c) == 'statement' and c.get('name') == name:
            for b in c:
                if _tag(b) == 'block':
                    return b
    return None


def _next(el):
    for c in el:
        if _tag(c) == 'next':
            for b in c:
                if _tag(b) == 'block':
                    return b
    return None


def _mut(el):
    for c in el:
        if _tag(c) == 'mutation':
            return c
    return None


# --------------------------------------------------------------------------- numeros / textos
_INT = re.compile(r'^[+-]?[0-9]+$')
_DEC = re.compile(r'^[+-]?([0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)([eE][+-]?[0-9]+)?$')
_RAT = re.compile(r'^[+-]?[0-9]+/[0-9]+$')


def java_split(txt, at):
    """String.split(Pattern.quote(at)) com limite 0: sem ocorrencia -> [txt]; vazios do FIM sao descartados
    (";;" -> []); vazios do meio e do comeco ficam. at vazio: o caso especial do JavaStringUtils (letra a letra)."""
    if at == '':
        return list(txt) if txt != '' else ['']
    if at not in txt:
        return [txt]
    partes = txt.split(at)
    while partes and partes[-1] == '':
        partes.pop()
    return partes


def java_trim(s):
    """String.trim() do Java: remove caracteres <= U+0020 nas pontas (NAO remove NBSP)."""
    i, j = 0, len(s)
    while i < j and ord(s[i]) <= 32:
        i += 1
    while j > i and ord(s[j - 1]) <= 32:
        j -= 1
    return s[i:j]


def padded_string_to_number(s):
    """(string->number (trim s)) do Kawa, no subconjunto decimal. #f => None."""
    t = java_trim(s)
    if _INT.match(t):
        return int(t)
    if _RAT.match(t):
        fr = Fraction(t)
        return int(fr) if fr.denominator == 1 else float(fr)
    if _DEC.match(t):
        return float(t)
    return None


def as_number(x):
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return x
    if isinstance(x, str):
        return padded_string_to_number(x)
    return None


def coerce_to_number(x, op='operation'):
    n = as_number(x)
    if n is None:
        raise YailRuntimeError('The operation %s cannot accept the argument: %r' % (op, x))
    return n


def yail_number_to_string(f):
    """YailNumberToString.format (Locale.US)."""
    if f != f:
        return 'NaN'
    if f in (float('inf'), float('-inf')):
        return '+infinity' if f > 0 else '-infinity'
    if f == round(f):
        return str(int(f))
    mag = abs(f)
    if 1e-6 < mag < 1e6:
        s = '%.5f' % f
        s = s.rstrip('0')
        if s.endswith('.'):
            s += '0'
        return s
    return '%.4E' % f


def coerce_to_string(x):
    if isinstance(x, bool):
        return 'true' if x else 'false'
    if isinstance(x, str):
        return x
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        return yail_number_to_string(x)
    if isinstance(x, list):
        return '[' + ', '.join(coerce_to_string(i) if not isinstance(i, str) else i for i in x) + ']'
    if x is None:
        return '*nothing*'
    return str(x)


def yail_equal(a, b):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(yail_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, list) or isinstance(b, list):
        return False
    if type(a) == type(b) and a == b:
        return True
    na, nb = as_number(a), as_number(b)
    return na is not None and nb is not None and na == nb


def is_integer_valued(n):
    return isinstance(n, int) or (isinstance(n, float) and n == n and abs(n) != float('inf') and n == round(n))


def yail_divide(n, d):
    if d == 0:
        raise YailRuntimeError('Division by zero')
    if isinstance(n, int) and isinstance(d, int):
        return n // d if n % d == 0 else n / d
    return n / d


def _kawa_int_op(name, a, b):
    if not (is_integer_valued(a) and is_integer_valued(b)):
        raise YailRuntimeError('%s: arguments must be integers (%r, %r)' % (name, a, b))
    if b == 0:
        raise YailRuntimeError('%s: division by zero' % name)
    ia, ib = int(a), int(b)
    inexact = isinstance(a, float) or isinstance(b, float)
    if name == 'quotient':
        q = abs(ia) // abs(ib)
        r = q if (ia >= 0) == (ib >= 0) else -q
    elif name == 'remainder':
        r = abs(ia) % abs(ib)
        r = r if ia >= 0 else -r
    else:  # modulo
        r = ia % ib
    return float(r) if inexact else r


def _unescape_text_block(s):
    """AI.Yail.quotifyForREPL preserva \\n, \\t e \\r (viram quebra de linha/tab/CR no Scheme);
    qualquer outra barra invertida e escapada e continua sendo uma barra literal."""
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s) and s[i + 1] in 'ntr':
            out.append({'n': '\n', 't': '\t', 'r': '\r'}[s[i + 1]])
            i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def html_exibido(msg):
    """Como a mensagem de um dialogo do Notifier aparece: Notifier.stringToHTML = Html.fromHtml(message).
    Quebras de linha e espacos repetidos viram um espaco; <br> vira quebra de linha; &amp; &lt; &gt; &quot; viram o
    caractere; outras marcas <...> somem (aproximacao do Html.fromHtml, suficiente para conferir os textos do app)."""
    t = re.sub(r'\s+', ' ', msg)
    t = re.sub(r'(?i)<br\s*/?>', '\n', t)
    t = re.sub(r'<[^>]*>', '', t)
    for a, b in (('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"'), ('&#39;', "'"), ('&nbsp;', ' '), ('&amp;', '&')):
        t = t.replace(a, b)
    return '\n'.join(l.strip(' ') for l in t.split('\n')).strip()


def csv_de_tabela(linhas):
    """CsvUtil.toCsvTable + convert-to-strings-for-csv (runtime.scm): cada campo entre aspas (aspas dobradas),
    campos separados por ',' e cada linha terminada por CRLF."""
    out = []
    for row in linhas:
        if not isinstance(row, list):
            row = [row]                              # (make-yail-list yl)
        campos = [coerce_to_string(c) for c in row]
        out.append(','.join('"' + c.replace('"', '""') + '"' for c in campos) + '\r\n')
    return ''.join(out)


def tabela_de_csv(texto):
    """CsvUtil.fromCsvTable (CsvParser): celulas com ou sem aspas, "" dentro de aspas, fim de linha \n, \r\n ou \r,
    CADA celula passa por trim(); erro de sintaxe -> erro de execucao (yail-list-from-csv-table)."""
    s, n, i = texto, len(texto), 0
    linhas = []

    def erro(m):
        raise YailRuntimeError('Cannot parse text argument to "list from csv table" as a CSV-formatted table (%s)' % m)

    while i < n:
        row = []
        while True:
            if i < n and s[i] == '"':
                j = i + 1
                partes = []
                while True:
                    k = s.find('"', j)
                    if k < 0:
                        erro('unclosed quoted cell')
                    if k + 1 < n and s[k + 1] == '"':
                        partes.append(s[j:k + 1])
                        j = k + 2
                        continue
                    partes.append(s[j:k])
                    j = k + 1
                    break
                cel = ''.join(partes)
                while j < n and s[j] in ' \t':
                    j += 1
                if j < n and s[j] not in ',\n\r':
                    erro('non-whitespace between closing quote and delimiter or end')
                row.append(java_trim(cel))
                i = j
            else:
                j = i
                while j < n and s[j] not in ',\n\r':
                    if s[j] == '"':
                        erro('quote in unquoted cell')
                    j += 1
                row.append(java_trim(s[i:j]))
                i = j
            if i < n and s[i] == ',':
                i += 1
                if i >= n:
                    row.append('')                  # virgula no fim do texto: mais uma celula vazia
                    break
                continue
            if i < n and s[i] == '\r':
                i += 2 if (i + 1 < n and s[i + 1] == '\n') else 1
            elif i < n and s[i] == '\n':
                i += 1
            break
        linhas.append(row)
    return linhas


# --------------------------------------------------------------------------- JSON (TinyDB)
def json_representation(v):
    """JsonUtil.getJsonRepresentation"""
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v == round(v):
            return str(int(v))
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return '[' + ','.join(json_representation(i) for i in v) + ']'
    raise YailRuntimeError('Value failed to convert to JSON.')


def _convert_json_item(o):
    """JsonUtil.convertJsonItem: strings "true"/"false" (qualquer caixa) viram booleanos."""
    if o is None:
        return 'null'
    if isinstance(o, list):
        return [_convert_json_item(i) for i in o]
    if isinstance(o, bool):
        return o
    if isinstance(o, str):
        if o.lower() == 'false':
            return False
        if o.lower() == 'true':
            return True
        return o
    return o


def json_object(s):
    """JsonUtil.getObjectFromJson(s, true)"""
    if s == '' or s is None:
        return ''
    try:
        v = json.loads(s)
    except ValueError:
        raise YailRuntimeError('Value failed to convert from JSON.')
    if isinstance(v, list):
        return [_convert_json_item(i) for i in v]
    return v


# --------------------------------------------------------------------------- componentes
def _bool_prop(v):
    if isinstance(v, str):
        return v.strip().lower() == 'true'
    return bool(v)


def _as_int(value, onde):
    """Parametro Java 'int': o numero precisa ser inteiro (um 36.5 quebraria a chamada no aparelho)."""
    n = coerce_to_number(value, onde)
    # rigor de proposito: so aceito inteiro EXATO (o que yail-round e os literais produzem). Um resultado de divisao
    # (numero de ponto flutuante, mesmo "36.0") e recusado aqui para eu nunca depender de como o Kawa o converteria.
    if isinstance(n, bool) or not isinstance(n, int):
        raise YailRuntimeError('%s espera numero inteiro exato, recebeu %r' % (onde, value))
    return n


class Component(object):
    def __init__(self, app, name, ctype, props):
        self.app, self.name, self.ctype = app, name, ctype
        self.props = dict(props)
        self.visible = _bool_prop(props.get('Visible', 'True'))

    # propriedades genericas
    def get_prop(self, prop):
        if prop == 'Visible':
            return self.visible
        if prop in self.props:
            return self.props[prop]
        raise YailRuntimeError('%s.%s: propriedade nao simulada (get)' % (self.name, prop))

    def set_prop(self, prop, value):
        if prop == 'Visible':
            if not isinstance(value, bool):
                raise YailRuntimeError('%s.Visible espera booleano, recebeu %r' % (self.name, value))
            self.visible = value
        elif prop in ('Text', 'Hint'):
            self.props[prop] = coerce_to_string(value)
        elif prop in ('BackgroundColor', 'TextColor', 'HintColor', 'ElementColor', 'SelectionColor', 'TextColorDetail'):
            self.props[prop] = coerce_to_number(value, prop)
        elif prop in ('Width', 'Height'):
            # AndroidViewComponent.Width(int) / Height(int)
            self.props[prop] = _as_int(value, '%s.%s' % (self.name, prop))
        elif prop in ('WidthPercent', 'HeightPercent'):
            # AndroidViewComponent.WidthPercent(int pCent): fora de 0..100 dispara ERROR_BAD_PERCENT e nao muda nada;
            # aqui vira erro de execucao para o teste acusar. Dentro da faixa: Width = -pCent + LENGTH_PERCENT_TAG (-1000).
            pc = _as_int(value, '%s.%s' % (self.name, prop))
            if pc < 0 or pc > 100:
                raise YailRuntimeError('%s.%s: porcentagem fora de 0..100: %r' % (self.name, prop, pc))
            self.props[prop[:-7]] = -pc - 1000
        elif prop in ('Image', 'Picture'):
            # caminho de um arquivo de assets; texto simples
            self.props[prop] = coerce_to_string(value)
        else:
            raise YailRuntimeError('%s.%s: propriedade nao simulada (set)' % (self.name, prop))

    def call(self, method, args):
        raise YailRuntimeError('%s.%s: metodo nao simulado' % (self.name, method))


class Label(Component):
    def __init__(self, app, name, ctype, props):
        super().__init__(app, name, ctype, props)
        self.props.setdefault('Text', '')

    def set_prop(self, prop, value):
        super().set_prop(prop, value)
        # v1.5: o que a pessoa le (faixa de aviso e frases de erro sob os campos) entra no mesmo registro
        # que antes recebia os avisos do Notifier (app.alerts), para os testes lerem as mensagens mostradas
        if prop == 'Text' and self.name in ('LblAviso', 'LblErroValor', 'LblErroCat', 'LblErroPag') and self.props.get('Text', '') != '':
            self.app.alerts.append(self.props['Text'])


class Button(Label):
    def get_prop(self, prop):
        if prop == 'Enabled':
            return _bool_prop(self.props.get('Enabled', 'True')) if isinstance(self.props.get('Enabled', 'True'), str) else self.props['Enabled']
        return super().get_prop(prop)

    def set_prop(self, prop, value):
        if prop == 'Enabled':                  # ButtonBase.Enabled(boolean)
            if not isinstance(value, bool):
                raise YailRuntimeError('%s.Enabled espera booleano, recebeu %r' % (self.name, value))
            self.props['Enabled'] = value
            return
        super().set_prop(prop, value)

    def habilitado(self):
        v = self.props.get('Enabled', 'True')
        return v if isinstance(v, bool) else _bool_prop(v)


class TextBox(Label):
    def set_prop(self, prop, value):
        # TextBoxBase.TextChanged: "raised when the text is changed, either by the user or the program"
        antes = self.props.get('Text', '')
        super().set_prop(prop, value)
        if prop == 'Text' and self.props.get('Text', '') != antes:
            self.app.fire(self.name, 'TextChanged')

    def call(self, method, args):
        if method == 'HideKeyboard':
            return None
        return super().call(method, args)


class Arrangement(Component):
    pass


class Spinner(Component):
    def __init__(self, app, name, ctype, props):
        super().__init__(app, name, ctype, props)
        self.items = []
        self.pos = -1
        efs = props.get('ElementsFromString', '')
        if efs:
            self._set_items(self._split(efs))

    @staticmethod
    def _split(s):
        parts = s.split(',')
        while parts and parts[-1] == '':
            parts.pop()
        return parts

    def _set_items(self, items):
        old = self.pos
        self.items = list(items)
        n = len(self.items)
        if n == 0:
            self.pos = -1
        elif old < 0:
            self.pos = 0
        else:
            self.pos = min(old, n - 1)   # AdapterView.handleDataChanged fixa a posicao no intervalo

    def selection_index(self):
        n = self.pos + 1
        return n if 1 <= n <= len(self.items) else 0

    def get_prop(self, prop):
        if prop == 'SelectionIndex':
            return self.selection_index()
        if prop == 'Selection':
            i = self.selection_index()
            return '' if i == 0 else self.items[i - 1]
        if prop == 'Elements':
            return list(self.items)
        return super().get_prop(prop)

    def set_prop(self, prop, value):
        if prop == 'ElementsFromString':
            self._set_items(self._split(coerce_to_string(value)))
        elif prop == 'SelectionIndex':
            idx = coerce_to_number(value, 'SelectionIndex')
            idx = int(idx)
            idx = idx if 1 <= idx <= len(self.items) else 0
            self.pos = idx - 1
        elif prop == 'Selection':
            t = coerce_to_string(value)
            self.pos = self.items.index(t) if t in self.items else -1
        else:
            super().set_prop(prop, value)

    # acao do usuario (toque no item do menu)
    def user_select(self, text):
        if text not in self.items:
            raise AssertionError('%s nao tem o item %r (itens: %r)' % (self.name, text, self.items))
        self.pos = self.items.index(text)
        self.app.fire(self.name, 'AfterSelecting', text)


class ListView(Component):
    def __init__(self, app, name, ctype, props):
        super().__init__(app, name, ctype, props)
        self.elements = []
        self.sel = 0

    def get_prop(self, prop):
        if prop == 'Elements':
            return list(self.elements)
        if prop == 'SelectionIndex':
            return self.sel
        return super().get_prop(prop)

    def set_prop(self, prop, value):
        if prop == 'Elements':
            if not isinstance(value, list):
                raise YailRuntimeError('ListView.Elements espera lista')
            # o App Inventor guarda cada item como veio: texto ou dicionario (YailDictionary)
            self.elements = [dict(i) if isinstance(i, dict) else coerce_to_string(i) for i in value]
            self.sel = 0
        else:
            super().set_prop(prop, value)

    def call(self, method, args):
        if method == 'CreateElement':
            if len(args) != 3:
                raise YailRuntimeError('CreateElement espera 3 argumentos')
            # Component.LISTVIEW_KEY_MAIN_TEXT / _DESCRIPTION / _IMAGE = 'Text1' / 'Text2' / 'Image'
            return {'Text1': coerce_to_string(args[0]), 'Text2': coerce_to_string(args[1]),
                    'Image': coerce_to_string(args[2])}
        return super().call(method, args)

    def user_pick(self, index):
        assert 1 <= index <= len(self.elements), 'indice fora da lista visivel'
        self.sel = index
        self.app.fire(self.name, 'AfterPicking')


class Notifier(Component):
    def __init__(self, app, name, ctype, props):
        super().__init__(app, name, ctype, props)
        self.pending = None

    def call(self, method, args):
        if method == 'ShowAlert':
            self.app.alerts.append(coerce_to_string(args[0]))
            return None
        if method == 'ShowMessageDialog':
            msg, title, btn = args
            self.app.message_dialogs.append({'message': coerce_to_string(msg), 'title': coerce_to_string(title),
                                             'button': coerce_to_string(btn), 'texto': html_exibido(coerce_to_string(msg))})
            return None
        if method == 'ShowChooseDialog':
            msg, title, b1, b2, cancelable = args
            if not isinstance(cancelable, bool):
                raise YailRuntimeError('ShowChooseDialog: cancelable nao e booleano')
            botoes = [coerce_to_string(b1), coerce_to_string(b2)]
            # Notifier.twoButtonDialog: com cancelable = true entra um 3o botao com android.R.string.cancel
            # ("Cancelar" num aparelho em portugues), que dispara ChoosingCanceled e AfterChoosing("Cancelar")
            if cancelable:
                botoes.append('Cancelar')
            self.pending = {'message': coerce_to_string(msg), 'title': coerce_to_string(title),
                            'buttons': botoes, 'cancelable': cancelable, 'texto': html_exibido(coerce_to_string(msg))}
            self.app.dialogs.append(self.pending)
            return None
        return super().call(method, args)

    def user_choose(self, button_text):
        assert self.pending is not None, 'nenhum dialogo aberto'
        assert button_text in self.pending['buttons'], 'botao %r nao existe: %r' % (button_text, self.pending['buttons'])
        cancelar = self.pending['cancelable'] and button_text == self.pending['buttons'][-1] and len(self.pending['buttons']) == 3
        self.pending = None
        if cancelar:
            self.app.fire(self.name, 'ChoosingCanceled')
        self.app.fire(self.name, 'AfterChoosing', button_text)


class TinyDB(Component):
    def __init__(self, app, name, ctype, props):
        super().__init__(app, name, ctype, props)
        self.namespace = props.get('Namespace', 'TinyDB1')
        self.drop_writes = False      # injecao de falha nos testes: o armazenamento "engole" a gravacao

    @property
    def path(self):
        return os.path.join(self.app.db_dir, self.namespace + '.json')

    def _load(self):
        if not os.path.exists(self.path):
            return {}
        with open(self.path, encoding='utf-8') as f:
            return json.load(f)

    def call(self, method, args):
        if method == 'StoreValue':
            tag, val = coerce_to_string(args[0]), args[1]
            data = self._load()
            data[tag] = json_representation(val)       # (a conversao para JSON acontece mesmo se a gravacao falhar)
            if self.drop_writes:
                return None
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            return None
        if method == 'GetValue':
            tag, default = coerce_to_string(args[0]), args[1]
            s = self._load().get(tag, '')
            return default if len(s) == 0 else json_object(s)
        return super().call(method, args)


class Clock(Component):
    def get_prop(self, prop):
        if prop == 'TimerEnabled':
            return _bool_prop(self.props.get('TimerEnabled', 'True'))
        return super().get_prop(prop)

    def set_prop(self, prop, value):
        if prop == 'TimerEnabled':
            if not isinstance(value, bool):
                raise YailRuntimeError('Clock.TimerEnabled espera booleano, recebeu %r' % (value,))
            self.props['TimerEnabled'] = value
        elif prop == 'TimerInterval':
            self.props['TimerInterval'] = _as_int(value, 'Clock.TimerInterval')     # Clock.TimerInterval(int)
        else:
            super().set_prop(prop, value)

    def call(self, method, args):
        if method == 'Now':
            return self.app.now
        if method == 'AddDays':             # Clock.AddDays(instante, dias) -> novo instante
            inst = args[0]
            if not isinstance(inst, datetime.datetime):
                raise YailRuntimeError('Clock.AddDays espera um instante')
            return inst + datetime.timedelta(days=_as_int(args[1], 'Clock.AddDays'))
        if method == 'SystemTime':          # milissegundos desde 1970 (System.currentTimeMillis)
            return int((self.app.now - datetime.datetime(1970, 1, 1)).total_seconds() * 1000)
        # Os instantes do simulador sao a hora LOCAL sem fuso; SystemTime/GetMillis/MakeInstantFromMillis usam a mesma
        # conversao (como se o fuso fosse UTC), entao as tres concordam entre si como no aparelho
        # (GetMillis(MakeInstantFromMillis(x)) = x e SystemTime = GetMillis(Now)).
        if method == 'GetMillis':           # Clock.GetMillis(instante) = instant.getTimeInMillis()
            inst = args[0]
            if not isinstance(inst, datetime.datetime):
                raise YailRuntimeError('Clock.GetMillis espera um instante')
            return int(round((inst - datetime.datetime(1970, 1, 1)).total_seconds() * 1000))
        if method == 'MakeInstantFromMillis':
            ms = _as_int(args[0], 'Clock.MakeInstantFromMillis')      # parametro Java long
            return datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=ms)
        if method == 'MakeInstantFromParts':
            # Clock.MakeInstantFromParts(ano, mes 1-12, dia, hora, minuto, segundo): Dates.DateInstant(ano, mes, dia)
            # (meia-noite LOCAL, lida com SimpleDateFormat "MM/dd/yyyy") e depois HOUR_OF_DAY/MINUTE/SECOND.
            # Data invalida no aparelho dispara Screen1.ErrorOccurred; o app so passa datas tiradas de instantes
            # validos, entao aqui ela e tratada como defeito do proprio app (erro).
            partes = [_as_int(a, 'Clock.MakeInstantFromParts') for a in args]
            try:
                return datetime.datetime(*partes)
            except ValueError as e:
                raise YailRuntimeError('Clock.MakeInstantFromParts com data invalida: %r (%s)' % (partes, e))
        if method in ('Year', 'Month', 'DayOfMonth'):
            inst = args[0]
            if not isinstance(inst, datetime.datetime):
                raise YailRuntimeError('Clock.%s espera um instante' % method)
            # Clock.Month = Dates.Month(instant) + 1 (1..12); DayOfMonth 1..31
            return {'Year': inst.year, 'Month': inst.month, 'DayOfMonth': inst.day}[method]
        if method == 'FormatDate':
            inst, pattern = args
            fmt = (coerce_to_string(pattern).replace('yyyy', '%Y').replace('dd', '%d')
                   .replace('MM', '%m').replace('HH', '%H').replace('mm', '%M').replace('ss', '%S'))
            return inst.strftime(fmt)
        return super().call(method, args)


class ChartData2D(Component):
    def __init__(self, app, name, ctype, props):
        super().__init__(app, name, ctype, props)
        self.entries = []
        self.colors = None      # None = cor padrao do componente

    def set_prop(self, prop, value):
        if prop == 'Colors':
            if not isinstance(value, list):
                raise YailRuntimeError('ChartData2D.Colors espera uma lista')
            if len(value) == 0:
                # PieChartDataModel usa "indice % colors.size()": lista vazia = divisao por zero no aparelho
                raise YailRuntimeError('ChartData2D.Colors: lista vazia (quebra o grafico de pizza)')
            cores = []
            for c in value:
                try:
                    n = int(str(c))            # Long.parseLong(colors.getString(i))
                except ValueError:
                    raise YailRuntimeError('ChartData2D.Colors: cor invalida %r' % (c,))
                cores.append(n)
            self.colors = cores
            return
        super().set_prop(prop, value)

    def slice_colors(self):
        """Cor de cada fatia como o MPAndroidChart escolhe: colors[i % n]."""
        if not self.colors:
            return [None] * len(self.entries)
        return [self.colors[i % len(self.colors)] for i in range(len(self.entries))]

    def call(self, method, args):
        if method == 'Clear':
            self.entries = []
            return None
        if method == 'AddEntry':
            x, y = coerce_to_string(args[0]), coerce_to_string(args[1])
            self.entries.append((x, float(padded_string_to_number(y))))
            return None
        return super().call(method, args)


class Form(Component):
    pass


class ImagePicker(Button):
    """Botao que abre a galeria (Picker.click). AfterPicking so acontece se a pessoa escolher uma imagem."""

    def __init__(self, app, name, ctype, props):
        super().__init__(app, name, ctype, props)
        self.selection = ''

    def get_prop(self, prop):
        if prop == 'Selection':
            return self.selection
        return super().get_prop(prop)

    def call(self, method, args):
        if method == 'Open':
            self.app.galeria_aberta.append(self.name)
            return None
        return super().call(method, args)

    def user_pick_image(self, caminho_salvo):
        """A pessoa escolheu uma imagem; o ImagePicker a copia para a pasta do app e guarda o caminho em Selection."""
        self.selection = caminho_salvo
        self.app.fire(self.name, 'AfterPicking')


class FilePicker(ImagePicker):
    """Picker com Action 'Pick Existing File' (ACTION_OPEN_DOCUMENT): Selection = URI content:// do documento."""

    def user_pick_file(self, uri):
        self.selection = uri
        self.app.fire(self.name, 'AfterPicking')

    def user_cancel(self):
        """A pessoa abre o seletor e volta sem escolher: FilePicker.resultReturned recebe Intent nulo e chama
        dispatchErrorOccurredEvent(this, "Open", ERROR_FILEPICKER_NO_URI_RETURNED = 4501) (FilePicker.java; o
        Form.onActivityResult repassa tambem o resultado cancelado). Selection nao muda; AfterPicking nao acontece."""
        self.app.erro_componente(self, 'Open', 4501, 'No URI returned to FilePicker')


class DatePicker(Button):
    """DatePicker (ButtonBase): nasce com a data de hoje; o toque abre o calendario do Android; ao confirmar, Year/Month
    (1-12)/Day mudam e AfterDateSet acontece DEPOIS (Handler.post). SetDateToDisplay com data invalida -> ErrorOccurred
    2401 e nada muda (DatePicker.java)."""

    def __init__(self, app, name, ctype, props):
        super().__init__(app, name, ctype, props)
        hoje = app.now
        self.ano, self.mes, self.dia = hoje.year, hoje.month, hoje.day

    def get_prop(self, prop):
        if prop == 'Year':
            return self.ano
        if prop == 'Month':
            return self.mes
        if prop == 'Day':
            return self.dia
        return super().get_prop(prop)

    def call(self, method, args):
        if method == 'SetDateToDisplay':
            y, m, d = [_as_int(x, 'DatePicker.SetDateToDisplay') for x in args]
            try:
                datetime.date(y, m, d)
            except ValueError:
                self.app.erro_componente(self, 'SetDateToDisplay', 2401, 'data invalida')
                return None
            self.ano, self.mes, self.dia = y, m, d
            return None
        if method == 'LaunchPicker':
            self.app.calendario_aberto.append(self.name)
            return None
        return super().call(method, args)

    def user_set_date(self, y, m, d):
        datetime.date(y, m, d)
        self.ano, self.mes, self.dia = y, m, d
        self.app.depois(lambda: self.app.fire(self.name, 'AfterDateSet'))


class File(Component):
    """File (escopo App): SaveFile/ReadFrom sao assincronos (outra thread) e o resultado chega DEPOIS do evento
    atual, como no aparelho (AfterFileSaved / GotText postados na thread da interface). ReadFrom de 'content:...'
    le pelo ContentResolver (documento escolhido no FilePicker). Erros viram Screen1.ErrorOccurred."""

    def __init__(self, app, name, ctype, props):
        super().__init__(app, name, ctype, props)
        self.falhar = None            # injecao de falha nos testes: 'gravar' ou 'ler'

    def call(self, method, args):
        if method == 'SaveFile':
            texto, nome = coerce_to_string(args[0]), coerce_to_string(args[1])
            if nome.startswith('//'):
                self.app.erro_componente(self, 'SaveFile', 2105, nome)
                return None
            if self.falhar == 'gravar':
                self.app.depois(lambda: self.app.erro_componente(self, 'SaveFile', 2104, nome))
                return None
            self.app.arquivos[nome] = texto          # OutputStreamWriter (UTF-8 no Android)
            self.app.depois(lambda: self.app.fire(self.name, 'AfterFileSaved', nome))
            return None
        if method == 'ReadFrom':
            nome = coerce_to_string(args[0])
            if nome.startswith('content:'):
                conteudo = self.app.documentos.get(nome)
            else:
                conteudo = self.app.arquivos.get(nome)
            if conteudo is None or self.falhar == 'ler':
                self.app.depois(lambda: self.app.erro_componente(self, 'ReadFrom', 2101, nome))
                return None
            texto = conteudo.replace('\r\n', '\n')    # IOUtils.normalizeNewLines
            self.app.depois(lambda: self.app.fire(self.name, 'GotText', texto))
            return None
        return super().call(method, args)


class Sharing(Component):
    """Sharing.ShareFile: caminho relativo -> pasta do escopo padrao da tela (App); arquivo inexistente ->
    ErrorOccurred 2001 (na hora); senao abre o compartilhamento do Android com o arquivo."""

    def call(self, method, args):
        if method == 'ShareFile':
            nome = coerce_to_string(args[0])
            if nome not in self.app.arquivos:
                self.app.erro_componente(self, 'ShareFileWithMessage', 2001, nome)
                return None
            ext = nome.rsplit('.', 1)[-1].lower()
            tipo = {'csv': 'text/comma-separated-values', 'txt': 'text/plain'}.get(ext, 'application/octet-stream')
            self.app.compartilhados.append({'arquivo': nome, 'tipo': tipo, 'texto': self.app.arquivos[nome]})
            return None
        return super().call(method, args)


class Canvas(Component):
    """v1.9: alem dos sprites, a CAMADA DE DESENHO (Canvas.java / CanvasView), copiada do codigo-fonte:
    - Width()/Height() (AndroidViewComponent) = tamanho da VIEW / densidade: 0 ate o Android medir a view, o que so
      acontece na passada de layout DEPOIS do evento (App.quadro) e so se o Canvas estiver a mostra (ele e todos os
      arranjos em volta visiveis); depois de medida, a view guarda o tamanho mesmo se o arranjo for escondido;
    - CanvasView nasce com um bitmap de 32 x 48 px (CANVAS_PREFERRED_WIDTH/HEIGHT); em onSizeChanged ele e ESTICADO
      para o tamanho real (createScaledBitmap): o que foi desenhado antes da medida sai deformado (op['esticado']);
    - BackgroundColor (set) e Clear() apagam a camada de desenho (clearDrawingLayer);
    - DrawArc(int left, int top, int right, int bottom, float startAngle, float sweepAngle, boolean useCenter,
      boolean fill): coordenadas em dp (x densidade), com uma COPIA do Paint do momento (cor = PaintColor, espessura =
      LineWidth x densidade, ponta reta = padrao do Paint); PaintColor COLOR_DEFAULT vira preto e COLOR_NONE apaga."""
    COLOR_DEFAULT = 0x00000000
    COLOR_NONE = 0x00FFFFFF
    PRETO = 0xFF000000

    def __init__(self, app, name, ctype, props):
        super().__init__(app, name, ctype, props)
        self.ops = []                 # o que esta desenhado na camada de desenho, na ordem
        self.medido = False           # a view ja passou por um layout com o tamanho real
        self.limpezas = 0             # quantas vezes a camada foi apagada (Clear ou BackgroundColor)
        self.paint_color = self._de_designer(props.get('PaintColor', '&HFF000000'))
        self.line_width = float(props.get('LineWidth', 2))     # DEFAULT_LINE_WIDTH = 2

    @staticmethod
    def _de_designer(v):
        v = str(v)
        return int(v[2:], 16) if v.startswith('&H') else int(float(v)) & 0xFFFFFFFF

    def largura(self):
        # tamanho da view depois de medida: (int)(dp * densidade) px; Canvas.Width() = (int)(px / densidade)
        d = self.app.density
        return int(int(int(float(self.props.get('Width', 0))) * d) / d)

    def altura(self):
        d = self.app.density
        return int(int(int(float(self.props.get('Height', 0))) * d) / d)

    def get_prop(self, prop):
        if prop == 'Width':
            return self.largura() if self.medido else 0
        if prop == 'Height':
            return self.altura() if self.medido else 0
        if prop == 'PaintColor':
            return self.paint_color
        if prop == 'LineWidth':
            return self.line_width
        return super().get_prop(prop)

    def set_prop(self, prop, value):
        if prop == 'PaintColor':                       # Canvas.PaintColor(int argb)
            self.paint_color = _as_int(value, self.name + '.PaintColor') & 0xFFFFFFFF
        elif prop == 'LineWidth':                      # Canvas.LineWidth(float width)
            self.line_width = float(coerce_to_number(value, self.name + '.LineWidth'))
        elif prop == 'BackgroundColor':
            super().set_prop(prop, value)
            self._apagar()                             # CanvasView.setBackgroundColor -> clearDrawingLayer()
        else:
            super().set_prop(prop, value)
            if prop in ('Width', 'Height', 'WidthPercent', 'HeightPercent'):
                self.medido = False                    # novo tamanho: a proxima medida estica o que estiver desenhado

    def _apagar(self):
        self.ops = []
        self.limpezas += 1

    def call(self, method, args):
        if method == 'Clear':
            self._apagar()
            return None
        if method == 'DrawArc':
            if len(args) != 8:
                raise YailRuntimeError('Canvas.DrawArc espera 8 argumentos, recebeu %d' % len(args))
            caixa = tuple(_as_int(a, '%s.DrawArc (%s)' % (self.name, n))
                          for a, n in zip(args[:4], ('left', 'top', 'right', 'bottom')))
            ini = float(coerce_to_number(args[4], 'Canvas.DrawArc startAngle'))
            varre = float(coerce_to_number(args[5], 'Canvas.DrawArc sweepAngle'))
            for a, n in ((args[6], 'useCenter'), (args[7], 'fill')):
                if not isinstance(a, bool):
                    raise YailRuntimeError('Canvas.DrawArc: %s espera booleano, recebeu %r' % (n, a))
            cor = self.paint_color
            if cor == self.COLOR_DEFAULT:
                cor = self.PRETO
            self.ops.append({'tipo': 'arco', 'caixa': caixa, 'ini': ini, 'varre': varre, 'centro': args[6],
                             'preencher': args[7], 'cor': cor, 'apaga': self.paint_color == self.COLOR_NONE,
                             'largura': self.line_width, 'esticado': not self.medido})
            return None
        return super().call(method, args)

    def user_touch(self, x=1.0, y=1.0, sprite=False):
        self.app.fire(self.name, 'Touched', x, y, sprite)


class Camera(Component):
    """v1.9: Camera.java. TakePicture abre o app de camera do Android (outra tela, fora do app); o resultado volta
    depois, em resultReturned: foto tirada -> AfterPicture(URL do arquivo, 'file:///...jpg'); voltou sem tirar ->
    nenhum evento; a camera nao devolveu foto -> ErrorOccurred 201. Na 1a vez o Android pergunta a permissao CAMERA
    (BulkPermissionRequest): negada -> Form.PermissionDenied, que sem manipulador vira ErrorOccurred 908.
    O teste escolhe o que a pessoa faz (App.camera_tirar / camera_voltar / camera_negar / camera_sem_foto)."""

    def __init__(self, app, name, ctype, props):
        super().__init__(app, name, ctype, props)
        self.aberta = False
        self.aberturas = 0

    def call(self, method, args):
        if method == 'TakePicture':
            if args:
                raise YailRuntimeError('Camera.TakePicture nao recebe argumentos')
            self.aberta = True
            self.aberturas += 1
            return None
        return super().call(method, args)


class LeitorNotificacoes(Component):
    """v2.0: a extensao com.conto.notificacoes (fonte em ext/src, compilada com as ferramentas do App Inventor).
    O que vale no aparelho e o codigo Java; aqui as REGRAS de Regras.java foram copiadas (e o teste T58 compara este
    simulador com o Regras.java de verdade, rodando na JVM, em centenas de casos):
    - o servico do Android (ServicoNotificacoes) so recebe notificacoes com o "Acesso a notificacoes" liberado;
    - guarda as que tem "R$", "BRL" ou " reais" (ApenasComValor, padrao), de qualquer app (AppsMonitorados vazio) menos
      o proprio; a mesma (app, titulo, texto) em menos de 10 min e repetida; no maximo 300 (saem as mais antigas);
    - o que foi guardado continua guardado ao fechar e abrir o app (SharedPreferences -> arquivo no db_dir);
    - Pendentes() = [id, app, nome do app, titulo, texto, quando] por item, da mais antiga para a mais nova;
    - NotificacaoRecebida so dispara com o app aberto (o componente vivo).
    v2.0.1: o leitor pode ser DESLIGADO pelo sistema (ex.: Xiaomi com o app no fundo): ai nada e guardado, mas a
    notificacao continua na BARRA; Reconectar() religa e o leitor rele a barra (onListenerConnected); o que ja foi
    guardado alguma vez (lista 'vistos', 500 ids) nao volta; Diagnostico() conta tudo que o servico viu."""
    MAXIMO = 300
    MAX_VISTOS = 500
    PROPRIO = 'appinventor.ai_conto.Conto'
    GUARDADA, DO_APP, APP_FORA, RESUMO, VAZIA, SEM_VALOR, JA_VISTA, REPETIDA = (
        'guardada', 'do próprio Contô', 'app ignorado', 'resumo de grupo', 'sem texto', 'sem valor em R$',
        'já guardada antes', 'repetida')
    JANELA_MS = 10 * 60 * 1000
    NOMES = {'com.nu.production': 'Nubank', 'com.itau': 'Itaú', 'br.com.itau': 'Itaú', 'com.bradesco': 'Bradesco',
             'br.com.bb.android': 'Banco do Brasil', 'br.com.gabba.Caixa': 'Caixa', 'br.gov.caixa.tem': 'Caixa Tem',
             'com.santander.app': 'Santander', 'br.com.intermedium': 'Inter', 'com.c6bank.app': 'C6 Bank',
             'com.picpay': 'PicPay', 'com.mercadopago.wallet': 'Mercado Pago', 'br.com.uol.ps.myaccount': 'PagBank'}

    def __init__(self, app, name, ctype, props):
        super().__init__(app, name, ctype, props)
        self.aberturas_config = 0
        self.aberturas_info = 0
        st = self._estado()
        if 'ApenasComValor' in props:
            st['so_valor'] = str(props['ApenasComValor']).lower() == 'true'
        if 'AppsMonitorados' in props:
            st['apps'] = props['AppsMonitorados']
        if 'AppsIgnorados' in props:
            st['ignorados'] = props['AppsIgnorados']
        self._gravar(st)

    # -- "SharedPreferences" da extensao (sobrevive a fechar e abrir o app)
    def _arq(self):
        return os.path.join(self.app.db_dir, 'conto_notificacoes.json')

    def _estado(self):
        try:
            return json.load(open(self._arq(), encoding='utf-8'))
        except Exception:
            return {'pendentes': [], 'apps': '', 'so_valor': True, 'acesso': False}

    @staticmethod
    def _completar(st):
        for k, v in (('vistos', []), ('barra', []), ('conectado', True), ('diag_vistas', 0), ('diag_app', ''),
                     ('diag_motivo', ''), ('diag_quando', 0)):
            st.setdefault(k, v)
        return st

    def _gravar(self, st):
        json.dump(st, open(self._arq(), 'w', encoding='utf-8'), ensure_ascii=False)

    @staticmethod
    def tem_valor(titulo, texto):
        t = (' ' + titulo + ' ' + texto + ' ').lower()
        return 'r$' in t or 'brl' in t or ' reais' in t

    IGNORADOS = ('com.whatsapp,com.whatsapp.w4b,org.telegram.messenger,com.instagram.android,com.facebook.orca,'
                 'com.facebook.katana,com.google.android.gm,com.microsoft.office.outlook,com.discord,com.snapchat.android,'
                 'com.twitter.android,com.zhiliaoapp.musically,com.linkedin.android')

    @staticmethod
    def na_lista(lista, app):
        return any(p.strip() and p.strip().lower() == app.lower() for p in (lista or '').split(','))

    @classmethod
    def monitorado(cls, monitorados, ignorados, app):
        if cls.na_lista(ignorados, app):
            return False
        return not (monitorados or '').strip() or cls.na_lista(monitorados, app)

    @staticmethod
    def java_hash(s):
        h = 0
        for ch in s:
            for unidade in ([ord(ch)] if ord(ch) < 0x10000 else
                            [0xD800 + ((ord(ch) - 0x10000) >> 10), 0xDC00 + ((ord(ch) - 0x10000) & 0x3FF)]):
                h = (31 * h + unidade) & 0xFFFFFFFF
        return h

    @classmethod
    def guardar(cls, lista, app, titulo, texto, quando):
        """Regras.guardar: devolve o id, ou None se e a mesma de novo em menos de 10 min."""
        for o in reversed(lista):
            if o['app'] == app and o['titulo'] == titulo and o['texto'] == texto and abs(quando - o['quando']) < cls.JANELA_MS:
                return None
        idn = '%d-%x' % (quando, cls.java_hash(app + '|' + titulo + '|' + texto))
        lista.append({'id': idn, 'app': app, 'titulo': titulo, 'texto': texto, 'quando': quando})
        while len(lista) > cls.MAXIMO:
            lista.pop(0)
        return idn

    @classmethod
    def filtro(cls, app, proprio, monitorados, ignorados, resumo, titulo, texto, so_valor):
        """Regras.filtro: o motivo para NAO guardar, ou None."""
        if app is None or app == proprio:
            return cls.DO_APP
        if not cls.monitorado(monitorados, ignorados, app):
            return cls.APP_FORA
        if resumo:
            return cls.RESUMO
        if not titulo and not texto:
            return cls.VAZIA
        if so_valor and not cls.tem_valor(titulo, texto):
            return cls.SEM_VALOR
        return None

    @classmethod
    def id_de(cls, app, titulo, texto, quando):
        return '%d-%x' % (quando, cls.java_hash(app + '|' + titulo + '|' + texto))

    @classmethod
    def guardar_se_nova(cls, lista, vistos, app, titulo, texto, quando):
        """Regras.guardarSeNova: (motivo, id)."""
        if cls.id_de(app, titulo, texto, quando) in vistos:
            return cls.JA_VISTA, None
        idn = cls.guardar(lista, app, titulo, texto, quando)
        if idn is None:
            return cls.REPETIDA, None
        vistos.append(idn)
        while len(vistos) > cls.MAX_VISTOS:
            vistos.pop(0)
        return cls.GUARDADA, idn

    def _processar(self, st, app, titulo, texto, quando):
        """ServicoNotificacoes.processar: filtra, guarda se nova e anota no diagnostico. Devolve o id ou None."""
        motivo = self.filtro(app, self.PROPRIO, st.get('apps', ''), st.get('ignorados', self.IGNORADOS), False,
                             titulo, texto, st.get('so_valor', True))
        if motivo == self.DO_APP:
            return None
        idn = None
        if motivo is None:
            motivo, idn = self.guardar_se_nova(st['pendentes'], st['vistos'], app, titulo, texto, quando)
        st['diag_vistas'] += 1
        st['diag_app'], st['diag_motivo'], st['diag_quando'] = app, motivo, quando
        return idn

    def chegou(self, app, titulo, texto, quando):
        """Uma notificacao aparece no celular: fica na barra; o servico so a recebe com o acesso liberado e o leitor
        ligado. Devolve o id guardado ou None."""
        st = self._completar(self._estado())
        st['barra'].append([app, titulo, texto, quando])
        idn = None
        if st.get('acesso') and st['conectado']:
            idn = self._processar(st, app, titulo, texto, quando)
        self._gravar(st)
        return idn

    def desconectar(self):
        """O sistema derruba o leitor (ex.: Xiaomi com o app no fundo) e nao o religa sozinho."""
        st = self._completar(self._estado())
        st['conectado'] = False
        self._gravar(st)

    def limpar_barra(self):
        st = self._completar(self._estado())
        st['barra'] = []
        self._gravar(st)

    def reconectar(self):
        """Reconectar() + onListenerConnected: religa (com acesso) e rele a barra. Devolve os ids guardados."""
        st = self._completar(self._estado())
        if not st.get('acesso'):
            return []
        st['conectado'] = True
        novos = []
        for app, titulo, texto, quando in st['barra']:
            idn = self._processar(st, app, titulo, texto, quando)
            if idn is not None:
                novos.append((idn, app, titulo, texto))
        self._gravar(st)
        return novos

    def diagnostico(self, st):
        acesso = bool(st.get('acesso'))
        conectado = acesso and st['conectado']
        if not acesso:
            s = 'Leitor desligado (acesso não liberado)'
        elif conectado:
            s = 'Leitor ligado'
        else:
            s = 'Leitor parado pelo Android: toque em Atualizar para religar'
        n = st['diag_vistas']
        s += ' • %d %s' % (n, 'notificação vista' if n == 1 else 'notificações vistas')
        if st['diag_app']:
            hora = (datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=st['diag_quando'])).strftime('%d/%m %H:%M')
            s += ' • última: %s às %s (%s)' % (self.nome_app(st['diag_app']), hora, st['diag_motivo'])
        return s

    def nome_app(self, pacote):
        return self.NOMES.get(pacote, pacote)

    def get_prop(self, prop):
        st = self._estado()
        if prop == 'ApenasComValor':
            return bool(st.get('so_valor', True))
        if prop == 'AppsMonitorados':
            return st.get('apps', '')
        if prop == 'AppsIgnorados':
            return st.get('ignorados', self.IGNORADOS)
        return super().get_prop(prop)

    def set_prop(self, prop, value):
        st = self._estado()
        if prop == 'ApenasComValor':
            if not isinstance(value, bool):
                raise YailRuntimeError('LeitorNotificacoes.ApenasComValor espera booleano')
            st['so_valor'] = value
        elif prop == 'AppsMonitorados':
            st['apps'] = '' if value is None else str(value).strip()
        elif prop == 'AppsIgnorados':
            st['ignorados'] = '' if value is None else str(value).strip()
        else:
            return super().set_prop(prop, value)
        self._gravar(st)

    def call(self, method, args):
        st = self._estado()
        if method == 'AcessoLiberado':
            return bool(st.get('acesso'))
        if method == 'AbrirConfiguracaoDeAcesso':
            self.aberturas_config += 1
            return None
        if method == 'AbrirInformacoesDoApp':
            self.aberturas_info += 1
            return None
        if method == 'Pendentes':
            return [[o['id'], o['app'], self.nome_app(o['app']), o['titulo'], o['texto'], str(o['quando'])]
                    for o in st['pendentes']]
        if method == 'QuantidadePendente':
            return len(st['pendentes'])
        if method == 'Remover':
            if len(args) != 1:
                raise YailRuntimeError('LeitorNotificacoes.Remover espera 1 argumento')
            idn = coerce_to_string(args[0])
            st['pendentes'] = [o for o in st['pendentes'] if o['id'] != idn]
            self._gravar(st)
            return None
        if method == 'LimparTudo':
            st['pendentes'] = []
            self._gravar(st)
            return None
        if method == 'NomeDoApp':
            return self.nome_app(str(args[0]))
        if method == 'LeitorConectado':
            st = self._completar(st)
            return bool(st.get('acesso')) and bool(st['conectado'])
        if method == 'Diagnostico':
            return self.diagnostico(self._completar(st))
        if method == 'Reconectar':
            self.reconexoes = getattr(self, 'reconexoes', 0) + 1
            for idn, app, titulo, texto in self.reconectar():
                # avisar() usa runOnUiThread: o evento roda DEPOIS do bloco que chamou Reconectar
                self.app.depois(lambda a=(idn, app, titulo, texto): self.app.fire(
                    self.name, 'NotificacaoRecebida', a[0], a[1], self.nome_app(a[1]), a[2], a[3]))
            return None
        return super().call(method, args)


class ImageSprite(Component):
    """Geometria copiada de ImageSprite.java / Sprite.java (origem no canto superior esquerdo, u = v = 0):
    Width()/Height() devolvem o tamanho natural da imagem (em px / densidade) quando o tamanho e automatico (-1);
    toda mudanca chama registerChange -> hitEdge -> moveIntoBounds, que empurra o sprite para dentro do Canvas."""

    def __init__(self, app, name, ctype, props):
        super().__init__(app, name, ctype, props)
        self.canvas = None
        self.width_hint = int(float(props.get('Width', -1)))
        self.height_hint = int(float(props.get('Height', -1)))
        self.x_left = float(props.get('X', 0.0))
        self.y_top = float(props.get('Y', 0.0))
        self.picture = props.get('Picture', '')
        self.natural = self._medir(self.picture)
        self.empurroes = 0          # quantas vezes moveIntoBounds mexeu neste sprite

    # -- tamanho natural (MediaUtil.getBitmapOptions + decodificacao + escala pela densidade)
    def _medir(self, caminho):
        if not caminho:
            return None
        # v1.9: a camera devolve uma URL de arquivo ('file:///storage/.../Pictures/app_inventor_123.jpg'), que o
        # MediaUtil abre como FILE_URL; a galeria (ImagePicker) devolve um caminho absoluto
        if caminho.startswith('file://'):
            from urllib.parse import unquote
            arq = unquote(caminho[len('file://'):])
        else:
            arq = caminho if os.path.isabs(caminho) else os.path.join(self.app.assets_dir or '', caminho)
        if not os.path.exists(arq):
            return None                      # "Unable to load": drawable = null
        try:
            from PIL import Image, ImageOps
            with Image.open(arq) as im:
                im = ImageOps.exif_transpose(im)      # MediaUtil.applyExifRotation
                w, h = im.size
        except Exception:
            return None
        d = self.app.density
        max_w, max_h = self.app.display_dp
        sample = 1
        while (w // sample > max_w) and (h // sample > max_h):
            sample *= 2
        if sample == 1:
            pw, ph = (int(d * w), int(d * h)) if d != 1.0 else (w, h)
        else:
            pw, ph = -(-w // sample), -(-h // sample)
        return (pw, ph)

    def Width(self):
        if self.width_hint in (-1, -2) or self.width_hint <= -1000:
            return 0 if self.natural is None else int(self.natural[0] / self.app.density)
        return self.width_hint

    def Height(self):
        if self.height_hint in (-1, -2) or self.height_hint <= -1000:
            return 0 if self.natural is None else int(self.natural[1] / self.app.density)
        return self.height_hint

    def _register_change(self):
        cw, ch = self.canvas.largura(), self.canvas.altura()
        west, north = self.x_left < 0, self.y_top < 0
        east, south = self.x_left + self.Width() > cw, self.y_top + self.Height() > ch
        if not (west or north or east or south):
            return
        # Sprite.moveIntoBounds
        moved = False
        if self.Width() > cw:
            if self.x_left != 0:
                self.x_left, moved = 0.0, True
        elif west:
            self.x_left, moved = 0.0, True
        elif east:
            self.x_left, moved = float(cw - self.Width()), True
        if self.Height() > ch:
            if self.y_top != 0:
                self.y_top, moved = 0.0, True
        elif north:
            self.y_top, moved = 0.0, True
        elif south:
            self.y_top, moved = float(ch - self.Height()), True
        if moved:
            self.empurroes += 1

    def get_prop(self, prop):
        if prop == 'Width':
            return self.Width()
        if prop == 'Height':
            return self.Height()
        if prop == 'X':
            return self.x_left
        if prop == 'Y':
            return self.y_top
        if prop == 'Picture':
            return self.picture
        return super().get_prop(prop)

    def set_prop(self, prop, value):
        if prop == 'Width':
            self.width_hint = _as_int(value, self.name + '.Width')
        elif prop == 'Height':
            self.height_hint = _as_int(value, self.name + '.Height')
        elif prop == 'X':
            self.x_left = float(coerce_to_number(value, 'X'))
        elif prop == 'Y':
            self.y_top = float(coerce_to_number(value, 'Y'))
        elif prop == 'Picture':
            self.picture = coerce_to_string(value)
            self.props['Picture'] = self.picture
            self.natural = self._medir(self.picture)
        elif prop == 'Visible':
            super().set_prop(prop, value)
        else:
            raise YailRuntimeError('%s.%s: propriedade nao simulada (set)' % (self.name, prop))
        self._register_change()

    def caixa(self):
        """Retangulo desenhado (como em ImageSprite.onDraw), em dp do Canvas: (x, y, w, h)."""
        return (float(round(self.x_left)), float(round(self.y_top)), float(self.Width()), float(self.Height()))


COMPONENT_CLASSES = {
    'Form': Form, 'Label': Label, 'Button': Button, 'TextBox': TextBox,
    'VerticalArrangement': Arrangement, 'HorizontalArrangement': Arrangement,
    'Spinner': Spinner, 'ListView': ListView, 'Notifier': Notifier, 'TinyDB': TinyDB,
    'Clock': Clock, 'Chart': Component, 'ChartData2D': ChartData2D, 'Image': Component,
    'ImagePicker': ImagePicker, 'Canvas': Canvas, 'ImageSprite': ImageSprite, 'Camera': Camera,
    'File': File, 'Sharing': Sharing, 'FilePicker': FilePicker, 'DatePicker': DatePicker,
    'LeitorNotificacoes': LeitorNotificacoes,          # v2.0: extensao
}

EVENT_PARAMS = {
    ('Notifier', 'AfterChoosing'): ['choice'],
    ('Spinner', 'AfterSelecting'): ['selection'],
    ('Canvas', 'Touched'): ['x', 'y', 'touchedAnySprite'],
    ('File', 'AfterFileSaved'): ['fileName'], ('File', 'GotText'): ['text'],
    ('Form', 'ErrorOccurred'): ['component', 'functionName', 'errorNumber', 'message'],
    ('Camera', 'AfterPicture'): ['image'],
    ('LeitorNotificacoes', 'NotificacaoRecebida'): ['id', 'app', 'nomeDoApp', 'titulo', 'texto'],
    ('LeitorNotificacoes', 'Erro'): ['mensagem'],
}


# --------------------------------------------------------------------------- app
class App(object):
    """Uma execucao do aplicativo (abrir o app). Reabrir = criar outro App com o mesmo db_dir."""

    def __init__(self, bky_path, scm_path, db_dir, now=None, run_initialize=True, assets_dir=None, density=2.75,
                 display_dp=(393, 873)):
        self.db_dir = db_dir
        # pasta de assets do pacote (para medir imagens): <pacote>/assets, a partir de src/appinventor/ai_x/App/Screen1.scm
        if assets_dir is None:
            cand = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(scm_path)), '..', '..', '..', '..', 'assets'))
            assets_dir = cand if os.path.isdir(cand) else None
        self.assets_dir = assets_dir
        self.density = density
        self.display_dp = display_dp
        self.galeria_aberta = []
        self.calendario_aberto = []
        self.toques_ignorados = []
        os.makedirs(db_dir, exist_ok=True)
        self.now = now or datetime.datetime(2026, 11, 11, 20, 55)
        self.alerts = []
        self.dialogs = []
        self.message_dialogs = []
        self.runtime_errors = []
        self.comps = {}
        self.g = {}
        self.procs = {}
        self.events = {}
        self.fila = []              # eventos postados para depois do evento atual (resultado de operacao assincrona)
        self.profundidade = 0
        self.arquivos = {}          # pasta do app (escopo App): nome -> texto
        self.documentos = {}        # documentos que a pessoa pode escolher no FilePicker: uri -> texto
        self.compartilhados = []    # cada abertura do compartilhamento do Android
        self.erros_componente = []
        self._load_scm(scm_path)
        self._load_bky(bky_path)
        if run_initialize:
            self.fire('Screen1', 'Initialize')

    # -- carga
    def _load_scm(self, path):
        txt = open(path, encoding='utf-8').read()
        body = txt[txt.index('{'): txt.rindex('}') + 1]
        data = json.loads(body)

        self.parent = {}

        def build(node, pai=None):
            ctype = node['$Type']
            props = {k: v for k, v in node.items() if not k.startswith('$')}
            cls = COMPONENT_CLASSES.get(ctype)
            if cls is None:
                raise NotImplementedError('componente nao simulado: ' + ctype)
            comp = cls(self, node['$Name'], ctype, props)
            self.comps[node['$Name']] = comp
            self.parent[node['$Name']] = pai
            if ctype == 'ImageSprite':
                comp.canvas = self.comps[pai]
            for ch in node.get('$Components', []):
                build(ch, node['$Name'])

        build(data['Properties'])

    def _load_bky(self, path):
        root = ET.parse(path).getroot()
        pending_globals = []
        for b in root:
            if _tag(b) != 'block':
                continue
            t = b.get('type')
            if t == 'global_declaration':
                pending_globals.append(b)
            elif t in ('procedures_defnoreturn', 'procedures_defreturn'):
                self.procs[_field(b, 'NAME')] = b
            elif t == 'component_event':
                m = _mut(b)
                self.events[(m.get('instance_name'), m.get('event_name'))] = b
            else:
                raise NotImplementedError('bloco de topo nao suportado: ' + t)
        for b in pending_globals:
            self.g[_field(b, 'NAME')] = self.ev(_value(b, 'VALUE'), [])

    # -- API de teste (acoes do usuario)
    def comp(self, name):
        return self.comps[name]

    def type_text(self, name, text):
        # o usuario digitando = mesmo caminho de uma mudanca de texto (dispara TextChanged se mudou)
        self.comps[name].set_prop('Text', text)

    def fire_timer(self, name):
        """Um tick do Clock (so acontece se TimerEnabled estiver ligado, como no aparelho)."""
        if self.comps[name].get_prop('TimerEnabled'):
            self.fire(name, 'Timer')
            return True
        return False

    def esperar_rosca(self, relogio='ClockRosca', maximo=200):
        """v1.9: deixa o tempo passar para um Clock (40 ms por tick) ate ele se desligar sozinho; devolve quantos ticks
        houve. maximo protege o teste de um relogio que nunca desliga (o resultado volta como -1)."""
        n = 0
        while self.fire_timer(relogio):
            n += 1
            if n >= maximo:
                return -1
        return n

    def pick_option(self, nome):
        """Toque numa linha da lista de opcoes (categoria/pagamento) pelo texto exibido."""
        lv = self.comps['ListaOpcoes']
        textos = [e['Text1'] if isinstance(e, dict) else e for e in lv.elements]
        lv.user_pick(textos.index(nome) + 1)

    def select(self, name, item):
        # v1.5: sem Spinner, a pessoa toca no campo e escolhe na lista com icones (app antigo v1.2 continua com Spinner)
        if name not in self.comps and name in ('SpnCategoria', 'SpnPagamento'):
            self.click('BtnCategoria' if name == 'SpnCategoria' else 'BtnPagamento')
            return self.pick_option(item)
        self.comps[name].user_select(item)

    def click(self, name):
        comp = self.comps[name]
        # Image.java: o toque so vira evento Click se Clickable estiver ligado (senao nao ha OnClickListener)
        if comp.ctype == 'Image' and str(comp.props.get('Clickable', 'False')) != 'True':
            return
        # um componente que a pessoa nao ve nao pode ser tocado
        if not self.shown(name):
            raise AssertionError('%s nao esta visivel na tela; a pessoa nao consegue tocar nele' % name)
        # botao desabilitado (Enabled = falso): o toque nao faz nada (ButtonBase: setEnabled(false))
        if isinstance(comp, Button) and not comp.habilitado():
            self.toques_ignorados.append(name)
            return
        self.fire(name, 'Click')

    def touch(self, name):
        """Toque num Canvas (dispara Touched)."""
        self.comps[name].user_touch()

    def pick_file(self, uri, conteudo=None, picker='PickerRestaurar'):
        """A pessoa toca em 'Restaurar backup', o seletor de documentos do Android abre e ela escolhe um arquivo."""
        if not self.shown(picker):
            raise AssertionError('%s nao esta visivel na tela; a pessoa nao consegue tocar nele' % picker)
        if conteudo is not None:
            self.documentos[uri] = conteudo
        self.comps[picker].user_pick_file(uri)

    def depois(self, acao):
        self.fila.append(acao)

    def erro_componente(self, comp, funcao, numero, mensagem):
        """Form.dispatchErrorOccurredEvent -> Screen1.ErrorOccurred; sem manipulador: ShowAlert('Error N: ...')."""
        self.erros_componente.append((comp.name, funcao, numero, mensagem))
        if ('Screen1', 'ErrorOccurred') in self.events:
            self.fire('Screen1', 'ErrorOccurred', comp, funcao, numero, mensagem)
        else:
            self.alerts.append('Error %d: %s' % (numero, mensagem))

    def cancel_pick(self, picker):
        """A pessoa toca no seletor de arquivos e volta sem escolher nada."""
        if not self.shown(picker):
            raise AssertionError('%s nao esta visivel na tela; a pessoa nao consegue tocar nele' % picker)
        self.comps[picker].user_cancel()

    def pick_date(self, picker, y, m, d):
        """A pessoa toca no campo de data, o calendario abre e ela confirma o dia y-m-d."""
        if not self.shown(picker):
            raise AssertionError('%s nao esta visivel na tela; a pessoa nao consegue tocar nele' % picker)
        self.comps[picker].user_set_date(y, m, d)
        while self.profundidade == 0 and self.fila:
            self.fila.pop(0)()

    # -- v1.9: a camera do celular (o app abriu a camera com TakePicture; a pessoa decide la fora)
    def _camera_aberta(self, camera):
        cam = self.comps[camera]
        if not cam.aberta:
            raise AssertionError('a camera (%s) nao foi aberta pelo app' % camera)
        cam.aberta = False
        return cam

    # -- v2.0: notificacoes do banco (o que o Android e o servico da extensao fazem fora dos blocos)
    def _leitor(self):
        return next(c for c in self.comps.values() if isinstance(c, LeitorNotificacoes))

    def liberar_acesso_notificacoes(self, sim=True):
        """A pessoa ativa (ou desativa) o Conto em 'Acesso a notificacoes' nas configuracoes do Android."""
        lt = self._leitor()
        st = lt._estado()
        st['acesso'] = bool(sim)
        lt._gravar(st)

    def chegar_notificacao(self, app, titulo, texto, quando_ms=None):
        """Uma notificacao chega no celular. Com o app ABERTO (este App), o componente dispara NotificacaoRecebida
        (via runOnUiThread: depois do que estiver rodando). Devolve o id guardado ou None."""
        if quando_ms is None:
            quando_ms = int((self.now - datetime.datetime(1970, 1, 1)).total_seconds() * 1000)
        lt = self._leitor()
        idn = lt.chegou(app, titulo, texto, quando_ms)
        if idn is not None:
            self.fire(lt.name, 'NotificacaoRecebida', idn, app, lt.nome_app(app), titulo, texto)
        return idn

    def camera_tirar(self, caminho, camera='CameraFoto'):
        """Tira a foto e confirma (na 1a vez, antes, libera a permissao): RESULT_OK com arquivo -> AfterPicture."""
        self._camera_aberta(camera)
        self.fire(camera, 'AfterPicture', caminho)

    def camera_voltar(self, camera='CameraFoto'):
        """Volta da camera sem tirar foto: RESULT_CANCELED -> o App Inventor so apaga o arquivo vazio, sem evento."""
        self._camera_aberta(camera)

    def camera_negar(self, camera='CameraFoto'):
        """Toca em 'Nao permitir' na pergunta do Android: PermissionDenied sem manipulador -> ErrorOccurred 908."""
        cam = self._camera_aberta(camera)
        self.erro_componente(cam, 'TakePicture', 908,
                             'The permission CAMERA has been denied. Please enable it in the Settings app.')
        while self.profundidade == 0 and self.fila:
            self.fila.pop(0)()
        self.quadro()

    def camera_sem_foto(self, camera='CameraFoto'):
        """O app de camera devolve OK mas sem foto (arquivo vazio e sem dados): ErrorOccurred 201."""
        cam = self._camera_aberta(camera)
        self.erro_componente(cam, 'TakePicture', 201, 'The camera did not return an image.')
        self.quadro()

    def pick_image(self, caminho, picker='PickerFoto'):
        """A pessoa toca no ImagePicker, a galeria abre e ela escolhe a imagem 'caminho'."""
        self.comps[picker].user_pick_image(caminho)

    def shown(self, name):
        """True se o componente e todos os arranjos em volta dele estao visiveis (o que a pessoa realmente ve)."""
        while name is not None:
            if not self.comps[name].visible:
                return False
            name = self.parent.get(name)
        return True

    def text(self, name):
        return self.comps[name].props.get('Text', '')

    def answer_dialog(self, button):
        self.comps['Notifier1'].user_choose(button)

    def pick_history_row(self, index):
        self.comps['ListaHistorico'].user_pick(index)

    def last_alert(self):
        return self.alerts[-1] if self.alerts else None

    # -- eventos
    def quadro(self):
        """v1.9: a passada de layout do Android, que vem DEPOIS do evento: todo Canvas que esta a mostra (ele e todos os
        arranjos em volta visiveis) e medido e ganha o tamanho de verdade (CanvasView.onSizeChanged)."""
        for nome, c in self.comps.items():
            if isinstance(c, Canvas) and not c.medido and self.shown(nome):
                c.medido = True
                for op in c.ops:
                    op['esticado'] = True              # o bitmap de 32 x 48 px e esticado para o tamanho real

    def fire(self, inst, event, *args):
        blk = self.events.get((inst, event))
        if blk is None:
            while self.profundidade == 0 and self.fila:
                self.fila.pop(0)()
            if self.profundidade == 0:
                self.quadro()
            return
        ctype = self.comps[inst].ctype
        names = EVENT_PARAMS.get((ctype, event), [])
        frame = dict(zip(names, args))
        self.profundidade += 1
        try:
            self.run(_stmt(blk, 'DO'), [frame])
        except YailRuntimeError as e:
            self.runtime_errors.append('%s.%s: %s' % (inst, event, e))
        finally:
            self.profundidade -= 1
        # terminado o evento mais externo, a thread da interface executa o que foi postado (AfterFileSaved, GotText...)
        while self.profundidade == 0 and self.fila:
            self.fila.pop(0)()
        if self.profundidade == 0:
            self.quadro()                              # v1.9: e depois redesenha a tela (layout)

    # -- avaliacao
    def lookup(self, name, env):
        if name.startswith('global '):
            key = name[len('global '):]
            if key not in self.g:
                raise YailRuntimeError('variavel global inexistente: ' + key)
            return self.g[key]
        for fr in reversed(env):
            if name in fr:
                return fr[name]
        raise YailRuntimeError('variavel inexistente: ' + name)

    def assign(self, name, value, env):
        if name.startswith('global '):
            self.g[name[len('global '):]] = value
            return
        for fr in reversed(env):
            if name in fr:
                fr[name] = value
                return
        raise YailRuntimeError('variavel inexistente (set): ' + name)

    def run(self, blk, env):
        while blk is not None:
            self.stmt(blk, env)
            blk = _next(blk)

    def stmt(self, b, env):
        t = b.get('type')
        m = _mut(b)
        if t == 'controls_if':
            ne = int(m.get('elseif', '0')) if m is not None else 0
            has_else = m is not None and m.get('else', '0') == '1'
            for i in range(ne + 1):
                test = self.ev(_value(b, 'IF%d' % i), env)
                if not isinstance(test, bool):
                    raise YailRuntimeError('controls_if: teste nao e booleano: %r' % (test,))
                if test:
                    self.run(_stmt(b, 'DO%d' % i), env)
                    return
            if has_else:
                self.run(_stmt(b, 'ELSE'), env)
        elif t == 'lexical_variable_set':
            self.assign(_field(b, 'VAR'), self.ev(_value(b, 'VALUE'), env), env)
        elif t == 'component_set_get':
            if m.get('set_or_get') != 'set':
                raise NotImplementedError('getter usado como instrucao')
            if m.get('is_generic') == 'true':
                comp = self._componente_do_tipo(self.ev(_value(b, 'COMPONENT'), env), m.get('component_type'), 'setter')
            else:
                comp = self.comps[m.get('instance_name')]
            comp.set_prop(m.get('property_name'), self.ev(_value(b, 'VALUE'), env))
        elif t == 'component_method':
            self.ev(b, env)
        elif t == 'procedures_callnoreturn':
            self.call_proc(b, env)
        elif t == 'controls_forEach':
            lst = self.ev(_value(b, 'LIST'), env)
            if not isinstance(lst, list):
                raise YailRuntimeError('foreach: o segundo argumento nao e uma lista: %r' % (lst,))
            var = _field(b, 'VAR')
            for item in list(lst):
                self.run(_stmt(b, 'DO'), env + [{var: item}])
        elif t == 'controls_forRange':
            var = _field(b, 'VAR')
            start = coerce_to_number(self.ev(_value(b, 'START'), env), 'for range')
            end = coerce_to_number(self.ev(_value(b, 'END'), env), 'for range')
            step = coerce_to_number(self.ev(_value(b, 'STEP'), env), 'for range')
            if step == 0 and start == end:
                self.run(_stmt(b, 'DO'), env + [{var: start}])
            elif (start < end and step <= 0) or (start > end and step >= 0) or (start != end and step == 0):
                pass
            else:
                i = start
                while not ((i < end) if step < 0 else (i > end)):
                    self.run(_stmt(b, 'DO'), env + [{var: i}])
                    i = i + step
        elif t == 'lists_add_items':
            lst = self.ev(_value(b, 'LIST'), env)
            n = int(m.get('items', '1'))
            if not isinstance(lst, list):
                raise YailRuntimeError('add items to list: nao e lista')
            for i in range(n):
                lst.append(self.ev(_value(b, 'ITEM%d' % i), env))
        elif t == 'lists_insert_item':
            lst = self.ev(_value(b, 'LIST'), env)
            idx = coerce_to_number(self.ev(_value(b, 'INDEX'), env), 'insert list item')
            item = self.ev(_value(b, 'ITEM'), env)
            if not isinstance(lst, list):
                raise YailRuntimeError('insert list item: nao e lista')
            if idx < 1 or idx > len(lst) + 1:
                raise YailRuntimeError('Insert list item: indice invalido %r' % idx)
            lst.insert(int(idx) - 1, item)
        elif t == 'lists_remove_item':
            lst = self.ev(_value(b, 'LIST'), env)
            idx = coerce_to_number(self.ev(_value(b, 'INDEX'), env), 'remove list item')
            if not isinstance(lst, list):
                raise YailRuntimeError('remove list item: nao e lista')
            if len(lst) == 0:
                raise YailRuntimeError('Remove list item: lista vazia')
            if idx < 1 or idx > len(lst):
                raise YailRuntimeError('Remove list item: indice invalido %r (tamanho %d)' % (idx, len(lst)))
            del lst[int(idx) - 1]
        elif t == 'local_declaration_statement':
            frame = self._locals(b, env)
            self.run(_stmt(b, 'STACK'), env + [frame])
        elif t == 'lists_replace_item':
            # yail-list-set-item!: indice < 1 ou > tamanho -> erro de execucao
            lst = self.ev(_value(b, 'LIST'), env)
            idx = coerce_to_number(self.ev(_value(b, 'NUM'), env), 'replace list item')
            item = self.ev(_value(b, 'ITEM'), env)
            if not isinstance(lst, list):
                raise YailRuntimeError('Replace list item: nao e lista: %r' % (lst,))
            if idx < 1:
                raise YailRuntimeError('Replace list item: indice menor que 1')
            if idx > len(lst):
                raise YailRuntimeError('Replace list item: indice %s maior que o tamanho %d' % (idx, len(lst)))
            if not is_integer_valued(idx):
                raise YailRuntimeError('Replace list item: indice nao inteiro %r' % (idx,))
            lst[int(idx) - 1] = item
        elif t == 'controls_while':
            while True:
                test = self.ev(_value(b, 'TEST'), env)
                if not isinstance(test, bool):
                    raise YailRuntimeError('while: teste nao booleano: %r' % (test,))
                if not test:
                    break
                self.run(_stmt(b, 'DO'), env)
        else:
            raise NotImplementedError('instrucao nao suportada: ' + t)

    def _componente_do_tipo(self, c, tipo, quem):
        # coerce-to-component-of-type: precisa ser um componente daquele tipo (set-and-coerce-property-and-check!)
        if not isinstance(c, Component) or c.ctype != tipo:
            raise YailRuntimeError('Property %s was expecting a %s component but got a %r instead.' % (quem, tipo, c))
        return c

    def _locals(self, b, env):
        frame = {}
        i = 0
        while _field(b, 'VAR%d' % i) is not None:
            # Scheme "let": os iniciais sao avaliados no escopo EXTERNO
            frame[_field(b, 'VAR%d' % i)] = self.ev(_value(b, 'DECL%d' % i), env)
            i += 1
        return frame

    def call_proc(self, b, env):
        name = _field(b, 'PROCNAME')
        pdef = self.procs.get(name)
        if pdef is None:
            raise YailRuntimeError('procedimento inexistente: ' + name)
        params = []
        i = 0
        while _field(pdef, 'VAR%d' % i) is not None:
            params.append(_field(pdef, 'VAR%d' % i))
            i += 1
        args = []
        for i in range(len(params)):
            blk = _value(b, 'ARG%d' % i)
            if blk is None:
                raise YailRuntimeError('chamada de %s sem o argumento %d' % (name, i))
            args.append(self.ev(blk, env))
        frame = dict(zip(params, args))
        if pdef.get('type') == 'procedures_defnoreturn':
            self.run(_stmt(pdef, 'STACK'), [frame])
            return None
        return self.ev(_value(pdef, 'RETURN'), [frame])

    def ev(self, b, env):
        if b is None:
            raise YailRuntimeError('soquete vazio')
        t = b.get('type')
        m = _mut(b)
        # ---- literais
        if t == 'text':
            return _unescape_text_block(_field(b, 'TEXT', ''))
        if t == 'math_number':
            s = _field(b, 'NUM')
            return int(s) if re.fullmatch(r'-?[0-9]+', s) else float(s)
        if t in ('logic_boolean', 'logic_false'):
            return _field(b, 'BOOL') == 'TRUE'
        if t == 'lexical_variable_get':
            return self.lookup(_field(b, 'VAR'), env)
        if t == 'lists_create_with':
            n = int(m.get('items', '0')) if m is not None else 0
            return [self.ev(_value(b, 'ADD%d' % i), env) for i in range(n)]
        if t == 'color_make_color':
            rgb = self.ev(_value(b, 'COLORLIST'), env)
            r, g, bl = [int(coerce_to_number(x)) for x in rgb[:3]]
            return (255 << 24) | (r << 16) | (g << 8) | bl
        # ---- logica
        if t == 'logic_compare':
            a, c = self.ev(_value(b, 'A'), env), self.ev(_value(b, 'B'), env)
            r = yail_equal(a, c)
            return (not r) if _field(b, 'OP') == 'NEQ' else r
        if t == 'logic_negate':
            v = self.ev(_value(b, 'BOOL'), env)
            if not isinstance(v, bool):
                raise YailRuntimeError('not: argumento nao booleano')
            return not v
        if t == 'logic_operation':
            n = int(m.get('items', '2')) if m is not None else 2
            names = ['A', 'B'] + ['BOOL%d' % i for i in range(2, n)]
            is_and = _field(b, 'OP') == 'AND'
            for nm in names:
                v = self.ev(_value(b, nm), env)
                if not isinstance(v, bool):
                    raise YailRuntimeError('and/or: argumento nao booleano: %r' % (v,))
                if is_and and not v:
                    return False
                if (not is_and) and v:
                    return True
            return is_and
        # ---- matematica
        if t == 'math_compare':
            op = _field(b, 'OP')
            a, c = self.ev(_value(b, 'A'), env), self.ev(_value(b, 'B'), env)
            if op == 'EQ':
                return yail_equal(a, c)
            if op == 'NEQ':
                return not yail_equal(a, c)
            na, nc = coerce_to_number(a, op), coerce_to_number(c, op)
            return {'LT': na < nc, 'LTE': na <= nc, 'GT': na > nc, 'GTE': na >= nc}[op]
        if t in ('math_add', 'math_multiply'):
            n = int(m.get('items', '2')) if m is not None else 2
            vals = [coerce_to_number(self.ev(_value(b, 'NUM%d' % i), env), t) for i in range(n)]
            r = 0 if t == 'math_add' else 1
            for v in vals:
                r = r + v if t == 'math_add' else r * v
            return r
        if t == 'math_subtract':
            return coerce_to_number(self.ev(_value(b, 'A'), env)) - coerce_to_number(self.ev(_value(b, 'B'), env))
        if t == 'math_division':
            return yail_divide(coerce_to_number(self.ev(_value(b, 'A'), env)),
                               coerce_to_number(self.ev(_value(b, 'B'), env)))
        if t == 'math_divide':
            op = {'MODULO': 'modulo', 'REMAINDER': 'remainder', 'QUOTIENT': 'quotient'}[_field(b, 'OP')]
            return _kawa_int_op(op, coerce_to_number(self.ev(_value(b, 'DIVIDEND'), env)),
                                coerce_to_number(self.ev(_value(b, 'DIVISOR'), env)))
        if t == 'math_abs':
            return abs(coerce_to_number(self.ev(_value(b, 'NUM'), env)))
        if t in ('math_round', 'math_ceiling', 'math_floor'):
            # O gerador oficial (generators/yail/math.js) trata os tres como `math_single` e escolhe a funcao pelo
            # campo OP: ROUND -> yail-round, CEILING -> yail-ceiling, FLOOR -> yail-floor; as tres sao
            # (inexact->exact (round|ceiling|floor x)) em runtime.scm => inteiro EXATO.
            # (Ate a v1.4 este simulador ignorava OP e sempre arredondava: um bloco trocado para FLOOR passava
            #  despercebido. Descoberto pelo teste de mutacao M22; agora cada modo e executado de verdade.)
            op = _field(b, 'OP')
            x = coerce_to_number(self.ev(_value(b, 'NUM'), env))
            if op == 'ROUND':
                return int(round(x))        # round do Scheme = metade para o par
            if op == 'FLOOR':
                return math.floor(x)
            if op == 'CEILING':
                return math.ceil(x)
            raise NotImplementedError('%s com OP=%s' % (t, op))
        if t == 'math_is_a_number':
            v = coerce_to_string(self.ev(_value(b, 'NUM'), env))   # tipo declarado '(text)
            op = _field(b, 'OP')
            if op == 'NUMBER':
                return padded_string_to_number(v) is not None
            raise NotImplementedError('is a number? ' + op)
        if t == 'math_format_as_decimal':
            x = coerce_to_number(self.ev(_value(b, 'NUM'), env))
            places = coerce_to_number(self.ev(_value(b, 'PLACES'), env))
            if places == 0:
                return int(round(x))
            return '%.*f' % (int(places), x)       # (format #f "~,Nf" x): ponto decimal
        # ---- texto
        if t == 'text_join':
            n = int(m.get('items', '2')) if m is not None else 2
            return ''.join(coerce_to_string(self.ev(_value(b, 'ADD%d' % i), env)) for i in range(n))
        if t == 'text_length':
            return len(coerce_to_string(self.ev(_value(b, 'VALUE'), env)))
        if t == 'text_isEmpty':
            return len(coerce_to_string(self.ev(_value(b, 'VALUE'), env))) == 0
        if t == 'text_trim':
            return java_trim(coerce_to_string(self.ev(_value(b, 'TEXT'), env)))
        if t == 'text_contains':
            mode = _field(b, 'OP')
            txt = coerce_to_string(self.ev(_value(b, 'TEXT'), env))
            piece = coerce_to_string(self.ev(_value(b, 'PIECE'), env))
            if mode != 'CONTAINS':
                raise NotImplementedError('text_contains modo ' + str(mode))
            return txt.find(piece) >= 0
        if t == 'text_segment':
            txt = coerce_to_string(self.ev(_value(b, 'TEXT'), env))
            start = coerce_to_number(self.ev(_value(b, 'START'), env))
            length = coerce_to_number(self.ev(_value(b, 'LENGTH'), env))
            if start < 1:
                raise YailRuntimeError('Segment: Start is less than 1 (%s).' % start)
            if length < 0:
                raise YailRuntimeError('Segment: Length is negative (%s).' % length)
            if (start - 1) + length > len(txt):
                raise YailRuntimeError('Segment: Start (%s) + length (%s) - 1 exceeds text length (%s).'
                                       % (start, length, len(txt)))
            return txt[int(start) - 1:int(start) - 1 + int(length)]
        if t == 'text_changeCase':
            txt = coerce_to_string(self.ev(_value(b, 'TEXT'), env))
            op = _field(b, 'OP')
            if op == 'DOWNCASE':
                return txt.lower()          # String.toLowerCase (string-to-lower-case)
            if op == 'UPCASE':
                return txt.upper()
            raise NotImplementedError('text_changeCase ' + str(op))
        if t == 'text_starts_at':        # runtime.scm string-starts-at: indexOf + 1 (0 = nao achou)
            txt = coerce_to_string(self.ev(_value(b, 'TEXT'), env))
            pc = coerce_to_string(self.ev(_value(b, 'PIECE'), env))
            return txt.find(pc) + 1
        if t == 'text_split':            # so o modo SPLIT: JavaStringUtils.split = String.split(Pattern.quote(at)), limite 0
            if (m.get('mode') if m is not None else None) != 'SPLIT' or _field(b, 'OP') != 'SPLIT':
                raise NotImplementedError('text_split modo ' + str(_field(b, 'OP')))
            txt = coerce_to_string(self.ev(_value(b, 'TEXT'), env))
            at = coerce_to_string(self.ev(_value(b, 'AT'), env))
            return java_split(txt, at)
        if t == 'text_replace_all':
            txt = coerce_to_string(self.ev(_value(b, 'TEXT'), env))
            seg = coerce_to_string(self.ev(_value(b, 'SEGMENT'), env))
            rep = coerce_to_string(self.ev(_value(b, 'REPLACEMENT'), env))
            return txt.replace(seg, rep) if seg != '' else txt      # Pattern.quote => literal
        # ---- listas
        if t == 'lists_select_item':
            lst = self.ev(_value(b, 'LIST'), env)
            idx = coerce_to_number(self.ev(_value(b, 'NUM'), env), 'select list item')
            if not isinstance(lst, list):
                raise YailRuntimeError('Select list item: nao e lista: %r' % (lst,))
            if idx < 1:
                raise YailRuntimeError('Select list item: indice menor que 1')
            if idx > len(lst):
                raise YailRuntimeError('Select list item: indice %s maior que o tamanho %d' % (idx, len(lst)))
            return lst[int(idx) - 1]
        if t == 'lists_length':
            lst = self.ev(_value(b, 'LIST'), env)
            if not isinstance(lst, list):
                raise YailRuntimeError('length of list: nao e lista: %r' % (lst,))
            return len(lst)
        if t == 'lists_is_list':
            return isinstance(self.ev(_value(b, 'ITEM'), env), list)
        if t == 'lists_position_in':
            # yail-list-index: posicao (1..n) do primeiro item yail-equal?, 0 se nao achar
            item = self.ev(_value(b, 'ITEM'), env)
            lst = self.ev(_value(b, 'LIST'), env)
            if not isinstance(lst, list):
                raise YailRuntimeError('index in list: nao e lista')
            for i, x in enumerate(lst):
                if yail_equal(item, x):
                    return i + 1
            return 0
        if t == 'lists_copy':
            def copia(x):
                return [copia(i) for i in x] if isinstance(x, list) else x      # yail-list-copy (profunda)
            lst = self.ev(_value(b, 'LIST'), env)
            if not isinstance(lst, list):
                raise YailRuntimeError('copy list: nao e lista')
            return copia(lst)
        if t == 'lists_to_csv_table':
            lst = self.ev(_value(b, 'LIST'), env)
            if not isinstance(lst, list):
                raise YailRuntimeError('Argument value to "list to csv table" must be a list')
            return csv_de_tabela(lst)
        if t == 'lists_from_csv_table':
            return tabela_de_csv(coerce_to_string(self.ev(_value(b, 'TEXT'), env)))
        if t == 'lists_join_with_separator':
            sep = coerce_to_string(self.ev(_value(b, 'SEPARATOR'), env))
            lst = self.ev(_value(b, 'LIST'), env)
            if not isinstance(lst, list):
                raise YailRuntimeError('join with separator: nao e lista')
            return sep.join(coerce_to_string(x) for x in lst)       # JavaStringUtils.join (item.toString())
        # ---- controle
        if t == 'controls_choose':
            test = self.ev(_value(b, 'TEST'), env)
            if not isinstance(test, bool):
                raise YailRuntimeError('choose: teste nao booleano: %r' % (test,))
            return self.ev(_value(b, 'THENRETURN' if test else 'ELSERETURN'), env)
        if t == 'controls_do_then_return':
            self.run(_stmt(b, 'STM'), env)
            return self.ev(_value(b, 'VALUE'), env)
        if t == 'local_declaration_expression':
            frame = self._locals(b, env)
            return self.ev(_value(b, 'RETURN'), env + [frame])
        # ---- procedimentos
        if t == 'procedures_callreturn':
            return self.call_proc(b, env)
        if t == 'procedures_callnoreturn':
            return self.call_proc(b, env)
        # ---- componentes
        if t == 'component_set_get':
            if m.get('set_or_get') != 'get':
                raise NotImplementedError('setter usado como valor')
            if m.get('is_generic') == 'true':
                comp = self._componente_do_tipo(self.ev(_value(b, 'COMPONENT'), env), m.get('component_type'), 'getter')
                return comp.get_prop(m.get('property_name'))
            return self.comps[m.get('instance_name')].get_prop(m.get('property_name'))
        if t == 'component_component_block':
            return self.comps[m.get('instance_name')]
        if t == 'component_method':
            comp = self.comps[m.get('instance_name')]
            args = []
            i = 0
            while _value(b, 'ARG%d' % i) is not None:
                args.append(self.ev(_value(b, 'ARG%d' % i), env))
                i += 1
            return comp.call(m.get('method_name'), args)
        raise NotImplementedError('bloco nao suportado pelo simulador: ' + t)

    def call_by_name(self, name, *args):
        """Chama um procedimento diretamente (para testes unitarios das funcoes puras)."""
        pdef = self.procs[name]
        params = []
        i = 0
        while _field(pdef, 'VAR%d' % i) is not None:
            params.append(_field(pdef, 'VAR%d' % i))
            i += 1
        frame = dict(zip(params, args))
        if pdef.get('type') == 'procedures_defnoreturn':
            self.run(_stmt(pdef, 'STACK'), [frame])
            return None
        return self.ev(_value(pdef, 'RETURN'), [frame])
