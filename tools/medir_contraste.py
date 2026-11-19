#!/usr/bin/env python3
"""Mede, nas PREVIAS renderizadas, o contraste real (WCAG) de cada texto contra o que esta atras dele.
Para cada Label/TextBox (e botao de fundo transparente) com cor de texto: recorta o retangulo do componente (rects.json)
e usa o pior caso do fundo em volta das letras (percentil 5/95 de luminancia do anel de 2 px da borda do recorte).
v1.6: a cor do texto e a que os blocos deixaram NAQUELA cena (cores.json, gravado por preview_sim) -- o tema escuro
troca as cores em tempo de execucao, entao a cor do .scm (tema claro) nao serve para as cenas escuras.
Uso: python3 medir_contraste.py <pasta_previas> <Screen1.scm> [aba=lancar_vazio]"""
import json
import sys

from PIL import Image

DENS = 2.75


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


def medir(pasta, scm_path, nome_png, runtime_colors=None):
    t = open(scm_path, encoding='utf-8').read()
    data = json.loads(t[t.index('{'): t.rindex('}') + 1])
    rects = json.load(open(pasta + '/rects.json'))[nome_png]
    im = Image.open('%s/%s.png' % (pasta, nome_png)).convert('RGB')
    try:
        reais = json.load(open(pasta + '/cores.json')).get(nome_png, {})
    except IOError:
        reais = {}
    out = []

    def rec(n):
        nome = n['$Name']
        transparente = n['$Type'] == 'Button' and n.get('BackgroundColor') == '&H00FFFFFF' and 'Image' not in n
        if (n['$Type'] in ('Label', 'TextBox') or transparente) and nome in rects:
            for chave in ('TextColor', 'HintColor'):
                if chave not in n:
                    continue
                if chave == 'HintColor' and n['$Type'] != 'TextBox':
                    continue
                if n['$Type'] == 'Label' and not n.get('Text') and not reais:
                    continue
                x, y, w, h = rects[nome]
                if w < 2 or h < 2:
                    continue
                # campos de texto e botoes transparentes: o retangulo inclui o contorno do campo (desenhado pela imagem do pai) -> encolhe 6 dp
                ins = 6.0 if n['$Type'] in ('TextBox', 'Button') else 0.0
                x, y, w, h = x + ins, y + ins, w - 2 * ins, h - 2 * ins
                if nome.startswith('LblErro'):
                    # v1.5: a frase de erro encosta na borda vermelha do campo; o antisserrilhado da borda entra na 1a linha de pixels
                    # do retangulo e NAO e fundo do texto -> descarta 3 dp no topo (o fundo real do texto e o cartao branco)
                    y, h = y + 3.0, h - 3.0
                box = (int(x * DENS), int(y * DENS), int((x + w) * DENS), int((y + h) * DENS))
                crop = im.crop(box)
                txt = cor(reais.get('%s.%s' % (nome, chave), n[chave]))
                # fundo = anel de 2 px nas bordas do recorte (as letras ficam no meio, sem pixels "misturados" pelo antisserrilhado)
                W, H = crop.size
                anel = [crop.getpixel((i, j)) for i in range(W) for j in range(H) if i < 2 or j < 2 or i >= W - 2 or j >= H - 2]
                if len(anel) < 10:
                    continue
                luminancias = sorted(anel, key=lum)
                claro = lum(txt) > 0.4
                pior = luminancias[int(len(anel) * 0.95)] if claro else luminancias[int(len(anel) * 0.05)]
                out.append((nome, chave, round(contraste(txt, pior), 2), '#%02X%02X%02X' % pior))
        for ch in n.get('$Components', []):
            rec(ch)
    rec(data['Properties'])
    return out


if __name__ == '__main__':
    pasta, scm = sys.argv[1], sys.argv[2]
    for aba in (sys.argv[3:] or ['lancar_vazio']):
        print('==', aba)
        for nome, chave, r, bg in sorted(medir(pasta, scm, aba), key=lambda x: x[2]):
            print('  %-18s %-10s %5.2f  fundo pior caso %s %s' % (nome, chave, r, bg, '' if r >= 4.5 else '  <<< abaixo de 4,5'))
