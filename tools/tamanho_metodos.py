#!/usr/bin/env python3
"""Estimativa do tamanho de cada metodo Java que o compilador do App Inventor (Kawa) gera a partir dos blocos.

Cada procedimento/evento vira uma lambda (um metodo). Dentro dele, o corpo de 'para cada' / 'para cada numero'
(forrange/foreach: (lambda (x) corpo)) e cada operando de 'e'/'ou' (and-delayed/or-delayed: (lambda () x)) viram
metodos separados; o resto (se/senao, escolher, variaveis locais, chamadas) fica no mesmo metodo.
A JVM limita um metodo a 64 KB de bytecode; um corpo enorme num metodo so pode falhar no build ("code too large").
Este script conta blocos por metodo para comparar versoes e manter cada corpo pequeno.

Uso: python3 tamanho_metodos.py <Screen1.bky> [<outro.bky> ...]
"""
import sys
import xml.etree.ElementTree as ET

NS = '{https://developers.google.com/blockly/xml}'


def tg(e):
    return e.tag.split('}')[-1]


def nome(b):
    t = b.get('type')
    f = {x.get('name'): x.text for x in b if tg(x) == 'field'}
    if t.startswith('procedures_def'):
        return f.get('NAME')
    if t == 'component_event':
        m = [x for x in b if tg(x) == 'mutation'][0]
        return '%s.%s' % (m.get('instance_name'), m.get('event_name'))
    return '%s %s' % (t, f.get('NAME'))


def medir(raiz, rotulo, saida):
    """Conta os blocos do metodo de 'raiz'; sub-metodos (corpos de laco, operandos de e/ou) vao para 'saida'."""
    n = 0
    pilha = [raiz]
    while pilha:
        b = pilha.pop()
        n += 1
        t = b.get('type')
        for c in b:
            k = tg(c)
            if k in ('value', 'statement', 'next'):
                filhos = [x for x in c if tg(x) == 'block']
                if not filhos:
                    continue
                sub = filhos[0]
                if t in ('controls_forRange', 'controls_forEach') and k == 'statement' and c.get('name') == 'DO':
                    medir(sub, rotulo + ' > laco', saida)
                    continue
                if t == 'logic_operation' and k == 'value':
                    medir(sub, rotulo + ' > e/ou', saida)
                    continue
                pilha.append(sub)
    saida.append((n, rotulo))
    return n


def main(paths):
    for p in paths:
        r = ET.parse(p).getroot()
        metodos = []
        for b in r:
            if tg(b) == 'block':
                medir(b, nome(b), metodos)
        metodos.sort(reverse=True)
        total = sum(1 for _ in r.iter(NS + 'block'))
        print('%s: %d blocos; %d metodos; maiores: %s' % (p, total, len(metodos),
                                                         ', '.join('%s=%d' % (r_, n) for n, r_ in metodos[:8])))


if __name__ == '__main__':
    main(sys.argv[1:])
