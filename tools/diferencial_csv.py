#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Teste DIFERENCIAL do CSV: simulador (ai_sim.csv_de_tabela / tabela_de_csv) x CsvUtil REAL do App Inventor
(CsvUtil.java + YailList.java copiados do codigo-fonte oficial e compilados sem alteracao; so JSON/Android/anotacao
viraram "stubs" vazios para compilar, e o caminho do CSV nao passa por eles).
Uso: python3 -I diferencial_csv.py <pasta csv_java> <kawa.jar>
Cada caso compara o resultado EXATO (texto gerado, tabela lida ou erro x erro). Termina com 'DIFERENCAS: 0' se tudo bateu."""
import base64, os, random, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_sim import csv_de_tabela, tabela_de_csv, YailRuntimeError  # noqa: E402

PASTA, KAWA = sys.argv[1], sys.argv[2]


def b64(s):
    return base64.b64encode(s.encode('utf-8')).decode('ascii')


def unb64(s):
    return base64.b64decode(s).decode('utf-8')


def enc_tabela(t):
    return '|'.join(','.join('b' + b64(f) for f in row) for row in t)


def dec_tabela(s):
    if s == '':
        return []
    return [[unb64(f[1:]) for f in r.split(',')] for r in s.split('|')]


consultas = []      # (descricao, op, argumento python)


voltas = {}        # indice da consulta FROM -> tabela esperada na ida e volta


def to(desc, tabela):
    consultas.append((desc, 'TO', tabela))
    # ida e volta: o texto escrito, lido de novo, devolve a mesma tabela (o leitor tira espacos das pontas: trim do Java)
    from ai_sim import java_trim
    voltas[len(consultas)] = [[java_trim(f) for f in row] for row in tabela]
    consultas.append((desc + ' (lido de volta)', 'FROM', csv_de_tabela(tabela)))


def frm(desc, texto):
    consultas.append((desc, 'FROM', texto))


rnd = random.Random(20261113)
CHARS_DIFICEIS = ['"', ',', ';', '\n', '\r', '\r\n', ' ', '\t', '=', '-', '+', '@', "'", 'é', 'Ç', 'ã', '€', '😀',
                  ' ', ' ', 'true', 'false', 'R$ 1.234,56', '0', '']

# A) tabelas parecidas com o backup do app (cabecalho, lancamentos, limites, repeticoes, perfil, tema) com textos dificeis
for k in range(400):
    linhas = [['Conto-backup', '1', '%02d/%02d/2026 %02d:%02d' % (rnd.randint(1, 28), rnd.randint(1, 12), rnd.randint(0, 23), rnd.randint(0, 59))]]
    for _ in range(rnd.randint(0, 6)):
        desc = ''.join(rnd.choice(CHARS_DIFICEIS + ['Mercado', 'Uber', 'aluguel', 'x']) for _ in range(rnd.randint(0, 6)))
        linhas.append(['L', rnd.choice(['Entrada', 'Despesa']), desc, str(rnd.randint(1, 10 ** 9)),
                       '%02d/%02d/2026 10:00' % (rnd.randint(1, 28), rnd.randint(1, 12)), rnd.choice(['Alimentação', 'Saúde', 'Outros']),
                       rnd.choice(['Pix', 'Cartão de crédito', 'Dinheiro'])])
    linhas.append(['O'] + [str(rnd.choice([0, 0, 50000, 123456])) for _ in range(8)])
    if rnd.random() < 0.5:
        linhas.append(['R', 'Despesa', 'Aluguel "apto"', '150000', 'Moradia', 'Pix', str(rnd.randint(1, 31)), str(rnd.randint(0, 24300))])
    linhas.append(['P', rnd.choice(['Marina', '  Ana  ', 'José "Zé"', '', 'a,b'])])
    linhas.append(['T', rnd.choice(['claro', 'escuro'])])
    to('backup aleatorio %d' % k, linhas)

# B) campos isolados com cada caractere/trecho dificil (inclusive espacos nas pontas, que o leitor tira)
for c in CHARS_DIFICEIS:
    for forma in ('%s', 'a%s', '%sa', ' %s ', 'a%sb%sc'):
        to('campo %r em %r' % (c, forma), [[forma.replace('%s', c), 'fim']])

# C) textos CSV aleatorios (validos ou nao): o leitor real e o simulado tem de concordar, inclusive no erro
ALFA = ['"', '"', ',', '\n', '\r', ' ', '\t', 'a', 'é', ';', '""']
for k in range(3000):
    frm('texto aleatorio %d' % k, ''.join(rnd.choice(ALFA) for _ in range(rnd.randint(0, 24))))

# D) um backup realista cortado em CADA posicao (arquivo incompleto) e com as quebras de linha normalizadas
#    como o File.ReadFrom faz (\r\n -> \n)
real = csv_de_tabela([['Conto-backup', '1', '13/11/2026 07:00'],
                      ['L', 'Despesa', 'Ele disse "oi", e foi', '1599', '12/11/2026 21:00', 'Lazer', 'Pix'],
                      ['L', 'Entrada', '', '100', '01/11/2026 08:00', 'Outros', 'Dinheiro'],
                      ['O', '0', '80000', '0', '0', '0', '0', '0', '0'],
                      ['R', 'Despesa', 'Aluguel', '150000', 'Moradia', 'Pix', '31', '24310'],
                      ['P', 'Marina'], ['T', 'escuro'], ['Fim', '2']])
for n in range(len(real) + 1):
    frm('backup cortado em %d' % n, real[:n])
    frm('backup cortado em %d (LF)' % n, real[:n].replace('\r\n', '\n'))
for extra in ('\n', '\r\n', '\n\n', ' ', '﻿'):
    frm('backup + %r no fim' % extra, real + extra)
frm('backup com BOM no inicio', '﻿' + real)
frm('backup com \\r no fim (sem \\n)', real[:-1])

# E) campos grandes (o leitor real tem um buffer de 10.240 caracteres)
for tam in (100, 5000, 10000, 10237, 10238, 10239, 10240, 12000):
    to('campo com %d caracteres' % tam, [['L', 'x' * tam, 'fim']])
    frm('celula entre aspas com %d caracteres' % tam, '"L","' + 'x' * tam + '","fim"\r\n')

# --- executa no Java real (um processo so)
entrada = ''.join('%s\t%s\n' % (op, enc_tabela(a) if op == 'TO' else b64(a)) for _, op, a in consultas)
cp = os.pathsep.join([os.path.join(PASTA, 'classes'), os.path.join(PASTA, 'harness'), KAWA])
r = subprocess.run(['java', '-cp', cp, 'CsvDiff'], input=entrada.encode('utf-8'), capture_output=True, timeout=600)
saida = [l for l in r.stdout.decode('utf-8').split('\n') if l]
assert len(saida) == len(consultas), (len(saida), len(consultas), r.stderr.decode()[-500:])

dif = []
cont = {'TO': 0, 'FROM': 0, 'erros_iguais': 0, 'voltas': 0}
for idx, ((desc, op, a), linha) in enumerate(zip(consultas, saida)):
    st, carga = linha.split('\t', 1)
    if op == 'TO':
        java = unb64(carga) if st == 'OK' else ('ERRO', unb64(carga))
        try:
            sim = csv_de_tabela(a)
        except Exception as e:   # noqa: BLE001
            sim = ('ERRO', repr(e))
        if java != sim:
            dif.append((desc, op, a, java, sim))
        cont['TO'] += 1
    else:
        java = dec_tabela(carga) if st == 'OK' else 'ERRO'
        try:
            sim = tabela_de_csv(a)
        except YailRuntimeError:
            sim = 'ERRO'
        if java != sim:
            dif.append((desc, op, a, java if java == 'ERRO' else java, sim))
        elif java == 'ERRO':
            cont['erros_iguais'] += 1
        if idx in voltas:
            cont['voltas'] += 1
            if java != voltas[idx]:
                dif.append((desc, 'IDA E VOLTA', a, java, voltas[idx]))
        cont['FROM'] += 1

print('CSV: simulador x CsvUtil REAL do App Inventor (Java, mesmo codigo-fonte do componente)')
print('  escrita (lista -> tabela CSV) ....... %d casos' % cont['TO'])
print('  leitura (tabela CSV -> lista) ....... %d casos (%d deles com erro de sintaxe nos dois)' % (cont['FROM'], cont['erros_iguais']))
print('  ida e volta no Java real ............ %d tabelas escritas e lidas de novo = a mesma tabela (pontas sem espaco)' % cont['voltas'])
for d in dif[:40]:
    print('  DIFERENCA:', d[0], '| op', d[1], '| entrada', repr(d[2])[:120], '| real', repr(d[3])[:160], '| simulador', repr(d[4])[:160])
print('DIFERENCAS: %d' % len(dif))
