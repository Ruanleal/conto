#!/usr/bin/env python3
"""Gera 'fotos' de teste (desenhadas aqui, nenhuma foto real): retrato 900x1200, paisagem 1600x900 e quadrada 800x800.
Cada uma tem um rosto estilizado no CENTRO e marcas coloridas nos cantos, para a previa mostrar se o recorte
do avatar ficou centralizado e sem deformar (o rosto tem de continuar redondo).

Uso: python3 foto_teste.py <pasta>   ->  retrato.jpg, paisagem.jpg, quadrada.png
"""
import os
import sys

from PIL import Image, ImageDraw


def foto(w, h, ceu, chao):
    S = 2
    img = Image.new('RGB', (w * S, h * S), ceu)
    d = ImageDraw.Draw(img)
    for y in range(h * S):                       # degrade simples de cima para baixo
        t = y / float(h * S)
        cor = tuple(int(ceu[i] + (chao[i] - ceu[i]) * t) for i in range(3))
        d.line([(0, y), (w * S, y)], fill=cor)
    m = min(w, h) * S
    cx, cy = w * S / 2.0, h * S / 2.0
    # ombros, pescoco, cabeca, cabelo, olhos, sorriso
    d.ellipse([cx - m * 0.42, cy + m * 0.26, cx + m * 0.42, cy + m * 1.10], fill=(34, 87, 122))
    d.rectangle([cx - m * 0.07, cy + m * 0.14, cx + m * 0.07, cy + m * 0.32], fill=(222, 170, 135))
    r = m * 0.25
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(236, 188, 150))
    d.pieslice([cx - r * 1.08, cy - r * 1.15, cx + r * 1.08, cy + r * 0.95], 180, 360, fill=(60, 42, 33))
    for sx in (-1, 1):
        d.ellipse([cx + sx * r * 0.42 - r * 0.09, cy - r * 0.02 - r * 0.09, cx + sx * r * 0.42 + r * 0.09, cy - r * 0.02 + r * 0.09], fill=(40, 30, 28))
    d.arc([cx - r * 0.45, cy + r * 0.05, cx + r * 0.45, cy + r * 0.62], 20, 160, fill=(150, 60, 60), width=int(r * 0.07))
    # marcas nos 4 cantos (devem ficar FORA do circulo do avatar)
    k = int(m * 0.12)
    for (x, y), cor in (((0, 0), (255, 60, 60)), ((w * S - k, 0), (60, 200, 90)), ((0, h * S - k), (70, 120, 255)), ((w * S - k, h * S - k), (250, 210, 60))):
        d.rectangle([x, y, x + k, y + k], fill=cor)
    return img.resize((w, h), Image.LANCZOS)


def main(pasta):
    os.makedirs(pasta, exist_ok=True)
    foto(900, 1200, (255, 196, 140), (255, 236, 200)).save(os.path.join(pasta, 'retrato.jpg'), quality=90)
    foto(1600, 900, (150, 205, 245), (225, 240, 250)).save(os.path.join(pasta, 'paisagem.jpg'), quality=90)
    foto(800, 800, (200, 180, 240), (240, 230, 250)).save(os.path.join(pasta, 'quadrada.png'))
    print('fotos de teste em', pasta)


if __name__ == '__main__':
    main(sys.argv[1])
