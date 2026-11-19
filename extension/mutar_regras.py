#!/usr/bin/env python3
"""Mutacao das regras da extensao (Regras.java): cada mutante e compilado e rodado com TesteRegras.java na JVM.
Detectado = TesteRegras acusa falha (ou nao compila/roda). Uso: APPINVENTOR=<appinventor-sources>/appinventor python3 mutar_regras.py"""
import os, re, shutil, subprocess, sys, tempfile
AQUI = os.path.dirname(os.path.abspath(__file__))
# json.jar do App Inventor (appinventor-sources/appinventor/lib/json/json.jar)
JSON = os.environ.get('JSON_JAR') or os.path.join(os.environ.get('APPINVENTOR', ''), 'lib', 'json', 'json.jar')
SRC = os.path.join(AQUI, 'src', 'com', 'conto', 'notificacoes', 'Regras.java')
TESTE = os.path.join(AQUI, 'test', 'com', 'conto', 'notificacoes', 'TesteRegras.java')
orig = open(SRC, encoding='utf-8').read()
MUT = [
    ('janela de repeticao zerada (a mesma notificacao entra varias vezes)', '10 * 60 * 1000L', '0L'),
    ('janela de repeticao de 1 minuto', '10 * 60 * 1000L', '60 * 1000L'),
    ('maximo guardado 300 -> 3000 (cresce sem limite pratico)', 'MAXIMO = 300', 'MAXIMO = 3000'),
    ('maximo: remove a mais NOVA em vez da mais antiga', 'arr.remove(0);', 'arr.remove(arr.length() - 1);'),
    ('app ignorado entra se estiver nos monitorados (ordem invertida)',
     '    if (naLista(ignorados, app)) {\n      return false;\n    }\n    return monitorados == null',
     '    if (monitorados != null && naLista(monitorados, app)) {\n      return true;\n    }\n    if (naLista(ignorados, app)) {\n      return false;\n    }\n    return monitorados == null'),
    ('monitorados vazio = NENHUM app', 'monitorados.trim().length() == 0 ||', 'monitorados.trim().length() < 0 ||'),
    ('lista com maiusculas/minusculas diferentes nao bate', 'p.trim().equalsIgnoreCase(app)', 'p.trim().equals(app)'),
    ('sem "BRL" como valor', ' || t.contains("brl")', ''),
    ('"reais" no meio de palavra conta ("surreais")', 't.contains(" reais")', 't.contains("reais")'),
    ('valor so com "R$" maiusculo (sem baixar a caixa)', '.toLowerCase();', ';'),
    ('repetida: compara so o titulo (textos diferentes viram repetidos)',
     ' && texto.equals(o.optString("texto"))', ''),
    ('repetida: ignora o app (apps diferentes com o mesmo texto viram repetidos)', 'app.equals(o.optString("app")) && ', ''),
    ('id sem o horario', 'return quando + "-" + ', 'return "x-" + '),
    ('semId apaga todas', '!o.optString("id").equals(id)', 'false'),
    # v2.0.1
    ('ja vistas esquecidas (reler a barra traz de volta o que ja foi tratado)', 'if (id.equals(vistos.optString(i))) {', 'if (false) {'),
    ('ja vistas sem limite (500 -> 5000)', 'MAX_VISTOS = 500', 'MAX_VISTOS = 5000'),
    ('ja vistas: esquece a mais NOVA', 'vistos.remove(0);', 'vistos.remove(vistos.length() - 1);'),
    ('guardada nao e lembrada como vista', '    marcarVisto(vistos, novo);\n', ''),
    ('filtro: resumo de grupo antes do app ignorado (motivo errado no diagnostico)',
     '    if (!monitorado(monitorados, ignorados, app)) {\n      return APP_FORA;\n    }\n    if (resumoDeGrupo) {\n      return RESUMO;\n    }',
     '    if (resumoDeGrupo) {\n      return RESUMO;\n    }\n    if (!monitorado(monitorados, ignorados, app)) {\n      return APP_FORA;\n    }'),
    ('filtro: ApenasComValor ignorado', 'if (soComValor && !temValor(titulo, texto))', 'if (!temValor(titulo, texto))'),
    ('diagnostico diz "ligado" com o leitor parado', '    } else if (conectado) {', '    } else if (true) {'),
]
res = []
for rotulo, a, b in MUT:
    assert orig.count(a) == 1, (rotulo, orig.count(a))
    d = tempfile.mkdtemp()
    pk = os.path.join(d, 'src', 'com', 'conto', 'notificacoes')
    os.makedirs(pk)
    open(os.path.join(pk, 'Regras.java'), 'w', encoding='utf-8').write(orig.replace(a, b))
    out = os.path.join(d, 'bin')
    r = subprocess.run(['javac', '-nowarn', '-encoding', 'UTF-8', '-d', out, '-cp', JSON, os.path.join(pk, 'Regras.java'), TESTE],
                       capture_output=True, text=True)
    if r.returncode != 0:
        res.append(('detectado (nao compila)', rotulo))
        continue
    r = subprocess.run(['java', '-cp', out + os.pathsep + JSON, 'com.conto.notificacoes.TesteRegras'], capture_output=True, text=True)
    m = re.search(r'(\d+) ok, (\d+) falhas', r.stdout)
    falhas = int(m.group(2)) if m else -1
    res.append(('detectado' if (falhas != 0 or r.returncode != 0) else 'SOBREVIVEU!', rotulo + ('  (%d falhas)' % falhas if m else '')))
    shutil.rmtree(d)
for e, r in res:
    print('%-24s %s' % (e, r))
n = sum(1 for e, _ in res if e.startswith('detectado'))
print('mutantes das regras da extensao detectados: %d/%d' % (n, len(res)))
sys.exit(0 if n == len(res) else 1)
