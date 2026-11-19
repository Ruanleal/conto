#!/usr/bin/env python3
"""Gera as imagens e copia as fontes do tema do Conto v1.4.

Uso:  python3 -I gen_assets.py <pasta_assets_saida> <pasta_fontes_baixadas> [medidas.json]

Tudo e desenhado aqui com Pillow (nenhuma imagem de terceiros). As fontes sao a familia Manrope
(licenca SIL OFL 1.1), copiada junto com o texto da licenca.
"""
import json
import math
import os
import shutil
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import tema as T

SS = 4   # super-amostragem para bordas suaves


def rgba(h, a=255):
    r, g, b = T.hexrgb(h)
    return (r, g, b, a)


def save(img, path):
    img.save(path, optimize=True)


def lerp(c1, c2, t):
    return tuple(c1[i] + (c2[i] - c1[i]) * t for i in range(3))


def gradient_rgb(w, h, stops, angle_deg):
    """Degrade linear (w x h). stops=[(pos, '#hex')...]; angulo 90 = de cima para baixo, 0 = esquerda->direita."""
    ang = math.radians(angle_deg)
    dx, dy = math.cos(ang), math.sin(ang)
    ys, xs = np.mgrid[0:h, 0:w]
    p = (xs - w / 2.0) * dx + (ys - h / 2.0) * dy
    pmax = (abs(w * dx) + abs(h * dy)) / 2.0
    t = np.clip((p / pmax + 1.0) / 2.0, 0.0, 1.0)
    out = np.zeros((h, w, 3), dtype=np.float64)
    pos = [s[0] for s in stops]
    for c in range(3):
        out[..., c] = np.interp(t, pos, [T.hexrgb(s[1])[c] for s in stops])
    return out


def rr_mask(w, h, r, corners=(True, True, True, True)):
    """Mascara de retangulo arredondado (w x h px, ja em escala final) com antialias por super-amostragem."""
    m = Image.new('L', (w * SS, h * SS), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], radius=r * SS, fill=255, corners=corners)
    return m.resize((w, h), Image.LANCZOS)


def with_alpha(rgb_arr, mask):
    h, w = rgb_arr.shape[:2]
    rgba_arr = np.zeros((h, w, 4), dtype=np.uint8)
    rgba_arr[..., :3] = np.clip(rgb_arr, 0, 255).astype(np.uint8)
    rgba_arr[..., 3] = np.asarray(mask, dtype=np.uint8)
    return Image.fromarray(rgba_arr, 'RGBA')


# --------------------------------------------------------------------------- cabecalho
def make_topo(path, w_dp, h_dp, scale=2, raio_dp=30):
    w, h = int(w_dp * scale), int(h_dp * scale)
    base = gradient_rgb(w, h, [(0.0, T.EMERALD_DARK), (0.55, '#08493F'), (1.0, T.EMERALD_MID)], 62)
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), 'RGB').convert('RGBA')
    # discos translucidos de fundo (profundidade)
    ov = Image.new('RGBA', (w * 2, h * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    def disco(cx, cy, r, a):
        d.ellipse([(cx - r) * 2, (cy - r) * 2, (cx + r) * 2, (cy + r) * 2], fill=(255, 255, 255, a))
    disco(w * 0.92, h * 0.10, h * 0.62, 14)
    disco(w * 0.78, h * 0.02, h * 0.34, 12)
    disco(w * 0.05, h * 1.02, h * 0.55, 10)
    ov = ov.resize((w, h), Image.LANCZOS)
    img = Image.alpha_composite(img, ov)
    # cantos inferiores arredondados
    m = rr_mask(w, h, int(raio_dp * scale), corners=(False, False, True, True))
    a = np.asarray(img.getchannel('A'), dtype=np.float64) * (np.asarray(m, dtype=np.float64) / 255.0)
    img.putalpha(Image.fromarray(a.astype(np.uint8), 'L'))
    save(img, path)


def make_chip(path, w_dp, h_dp, scale=3, raio_dp=16):
    w, h = int(w_dp * scale), int(h_dp * scale)
    img = Image.new('RGBA', (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = raio_dp * scale * SS
    d.rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], radius=r, fill=(255, 255, 255, 34))
    bw = max(1, int(scale * SS * 0.9))
    d.rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], radius=r, outline=(255, 255, 255, 56), width=bw)
    save(img.resize((w, h), Image.LANCZOS), path)


# --------------------------------------------------------------------------- icones
def arrow_icon(path, up, size=224):
    """Circulo suave com seta (verde para cima = entrada, vermelha para baixo = despesa)."""
    cor = T.GREEN if up else T.RED
    fundo = '#DDF3E8' if up else '#FCE3E4'
    img = Image.new('RGBA', (size * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = size * SS / 2.0
    R = size * SS * 0.39
    d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=rgba(fundo))
    # seta
    wd = size * SS * 0.062
    L = size * SS * 0.17
    sgn = -1 if up else 1
    y_tip = cy + sgn * L          # ponta
    y_tail = cy - sgn * L
    col = rgba(cor)
    d.line([(cx, y_tail), (cx, y_tip)], fill=col, width=int(wd))
    head = L * 0.78
    d.line([(cx, y_tip), (cx - head, y_tip - sgn * head)], fill=col, width=int(wd))
    d.line([(cx, y_tip), (cx + head, y_tip - sgn * head)], fill=col, width=int(wd))
    for (px, py) in [(cx, y_tail), (cx, y_tip), (cx - head, y_tip - sgn * head), (cx + head, y_tip - sgn * head)]:
        d.ellipse([px - wd / 2, py - wd / 2, px + wd / 2, py + wd / 2], fill=col)
    save(img.resize((size, size), Image.LANCZOS), path)


def dot_icon(path, hexcolor, size=48):
    img = Image.new('RGBA', (size * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([0, 0, size * SS - 1, size * SS - 1], fill=rgba(hexcolor))
    save(img.resize((size, size), Image.LANCZOS), path)


def ponto_cat(path, hexcolor, lado_dp=None, scale=3):
    """v1.9: bolinha da legenda da rosca (lado PONTO_CAT dp, 3x), reduzida pela media: todo pixel visivel tem
    exatamente a cor da fatia (o teste compara a cor da bolinha com a cor que os blocos usam no desenho)."""
    lado = (lado_dp or T.PONTO_CAT) * scale
    img = Image.new('RGBA', (lado * SS, lado * SS), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse([0, 0, lado * SS - 1, lado * SS - 1], fill=rgba(hexcolor))
    save(reduzir_sem_halo(img, (lado, lado)), path)


def make_logo(path, size):
    """Marca: quadrado arredondado esmeralda, anel branco em 'C' fechado por uma moeda dourada."""
    S = size * SS
    base = gradient_rgb(S, S, [(0.0, '#0A4A40'), (1.0, '#16967C')], 55)
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), 'RGB').convert('RGBA')
    mask = Image.new('L', (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.225), fill=255)
    img.putalpha(mask)
    d = ImageDraw.Draw(img)
    cx = cy = S / 2.0
    R = S * 0.285                      # raio da linha central do anel
    sw = S * 0.115                     # espessura do anel
    gap = 36                           # abertura do C (graus de cada lado do eixo leste)
    bbox = [cx - R - sw / 2, cy - R - sw / 2, cx + R + sw / 2, cy + R + sw / 2]
    d.arc(bbox, start=gap, end=360 - gap, fill=(255, 255, 255, 255), width=int(sw))
    for ang in (gap, 360 - gap):
        ex = cx + R * math.cos(math.radians(ang))
        ey = cy + R * math.sin(math.radians(ang))
        d.ellipse([ex - sw / 2, ey - sw / 2, ex + sw / 2, ey + sw / 2], fill=(255, 255, 255, 255))
    # moeda dourada no centro do anel
    rc = S * 0.105
    d.ellipse([cx - rc, cy - rc, cx + rc, cy + rc], fill=rgba(T.GOLD))
    rc2 = rc * 0.56
    d.ellipse([cx - rc2, cy - rc2, cx + rc2, cy + rc2], outline=(255, 255, 255, 120), width=max(1, int(S * 0.012)))
    save(img.resize((size, size), Image.LANCZOS), path)


# --------------------------------------------------------------------------- campos, cartoes, botoes
def make_campo(path, w_dp, h_dp, seta=False, scale=3, raio_dp=13, erro=False, fill=None, borda=None, borda_erro=None, cor_seta=None):
    w, h = int(w_dp * scale), int(h_dp * scale)
    img = Image.new('RGBA', (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = raio_dp * scale * SS
    bw = int(1.3 * scale * SS)
    if erro:
        bw = int(1.9 * scale * SS)
    d.rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], radius=r, fill=rgba(fill or T.CARD),
                        outline=rgba((borda_erro or T.RED_D) if erro else (borda or T.BORDER)), width=bw)
    if seta:
        cx = (w_dp - 22) * scale * SS
        cy = h * SS / 2.0
        a = 5.2 * scale * SS
        lw = int(2.1 * scale * SS)
        pts = [(cx - a, cy - a * 0.5), (cx, cy + a * 0.5), (cx + a, cy - a * 0.5)]
        d.line(pts, fill=rgba(cor_seta or T.EMERALD), width=lw, joint='curve')
        for p in (pts[0], pts[2]):
            d.ellipse([p[0] - lw / 2, p[1] - lw / 2, p[0] + lw / 2, p[1] + lw / 2], fill=rgba(cor_seta or T.EMERALD))
    save(img.resize((w, h), Image.LANCZOS), path)


def make_cartao(path, w_dp, h_dp, scale=2, raio_dp=22, lado=12, topo=3, base=10, fill=None, contorno='#DDE6E2', sombra_rgb=(16, 48, 40), forca=1.0):
    """Cartao branco com sombra suave. O corpo fica afastado das bordas da imagem (lado/topo/base em dp)."""
    w, h = int(w_dp * scale), int(h_dp * scale)
    S = SS
    box = [lado * scale * S, topo * scale * S, (w_dp - lado) * scale * S - 1, (h_dp - base) * scale * S - 1]
    mask = Image.new('L', (w * S, h * S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=raio_dp * scale * S, fill=255)
    # sombra: mascara deslocada e desfocada
    def sombra(dy_dp, blur_dp, alpha):
        sh = Image.new('L', (w * S, h * S), 0)
        sh.paste(mask, (0, int(dy_dp * scale * S)))
        sh = sh.filter(ImageFilter.GaussianBlur(blur_dp * scale * S))
        arr = np.asarray(sh, dtype=np.float64) * alpha
        return arr
    a = np.maximum(sombra(3.0, 7.0, 0.16 * forca), sombra(1.0, 1.6, 0.10 * forca))
    comp = np.zeros((h * S, w * S, 4), dtype=np.float64)
    comp[..., 0], comp[..., 1], comp[..., 2] = sombra_rgb
    comp[..., 3] = a
    base_img = Image.fromarray(np.clip(comp, 0, 255).astype(np.uint8), 'RGBA')
    corpo = Image.new('RGBA', (w * S, h * S), (0, 0, 0, 0))
    corpo.paste(Image.new('RGBA', (w * S, h * S), rgba(fill or T.CARD)), (0, 0), mask)
    out = Image.alpha_composite(base_img, corpo)
    # contorno finissimo
    bd = ImageDraw.Draw(out)
    bd.rounded_rectangle(box, radius=raio_dp * scale * S, outline=rgba(contorno), width=max(1, int(0.8 * scale * S)))
    save(out.resize((w, h), Image.LANCZOS), path)


def make_pill(path, w_dp, h_dp, fill, outline=None, scale=3, raio_dp=None, grad=None, border_dp=1.2):
    w, h = int(w_dp * scale), int(h_dp * scale)
    r = (raio_dp if raio_dp is not None else h_dp / 2.0) * scale
    mask = rr_mask(w, h, int(r))
    if grad:
        arr = gradient_rgb(w, h, [(0.0, grad[0]), (1.0, grad[1])], 90)
    else:
        arr = np.zeros((h, w, 3))
        arr[..., :] = T.hexrgb(fill)
    img = with_alpha(arr, mask)
    if outline:
        big = Image.new('RGBA', (w * SS, h * SS), (0, 0, 0, 0))
        ImageDraw.Draw(big).rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], radius=int(r * SS), outline=rgba(outline),
                                              width=max(1, int(border_dp * scale * SS)))
        img = Image.alpha_composite(img, big.resize((w, h), Image.LANCZOS))
    save(img, path)


EMOJI_FONT = '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf'


def make_icone(path, emoji, bg, size=96):
    """Ladrilho arredondado em cor suave com o emoji (Noto Color Emoji, licenca OFL) desenhado como imagem."""
    f = ImageFont.truetype(EMOJI_FONT, 109)
    tmp = Image.new('RGBA', (160, 160), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((80, 80), emoji, font=f, embedded_color=True, anchor='mm')
    box = tmp.getbbox()
    tmp = tmp.crop(box)
    lado = int(size * 0.60)
    tmp.thumbnail((lado, lado), Image.LANCZOS)
    tile = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    m = rr_mask(size, size, int(size * 0.28))
    base = Image.new('RGBA', (size, size), rgba(bg))
    tile.paste(base, (0, 0), m)
    tile.alpha_composite(tmp, ((size - tmp.width) // 2, (size - tmp.height) // 2))
    save(tile, path)


def make_icone_vazio(path, size=96, bg='#E9EFEC', fg='#6B7F78'):
    """Ladrilho neutro (cinza) com um '+' para o campo ainda nao escolhido."""
    big = size * SS
    img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * 0.28), fill=rgba(bg))
    c, a, w = big / 2, big * 0.17, int(big * 0.07)
    d.line([(c - a, c), (c + a, c)], fill=rgba(fg), width=w)
    d.line([(c, c - a), (c, c + a)], fill=rgba(fg), width=w)
    for p in ((c - a, c), (c + a, c), (c, c - a), (c, c + a)):
        d.ellipse([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2], fill=rgba(fg))
    save(img.resize((size, size), Image.LANCZOS), path)


# --------------------------------------------------------------------------- v1.6: avatar, molduras e botao de tema
def _silhueta(d, S, cor):
    """Pessoa estilizada (cabeca + ombros) dentro de um quadrado S x S."""
    cx = S / 2.0
    rh = S * 0.175
    cy = S * 0.40
    d.ellipse([cx - rh, cy - rh, cx + rh, cy + rh], fill=cor)
    rx, ry = S * 0.33, S * 0.30
    oy = S * 0.985
    d.ellipse([cx - rx, oy - ry, cx + rx, oy + ry], fill=cor)


def make_avatar(path, bg, fg, size=288, anel=None):
    """Avatar padrao: disco colorido com a silhueta, recortado em circulo (fora do circulo fica transparente)."""
    S = size * SS
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([0, 0, S - 1, S - 1], fill=bg)
    _silhueta(d, S, fg)
    circ = Image.new('L', (S, S), 0)
    ImageDraw.Draw(circ).ellipse([0, 0, S - 1, S - 1], fill=255)
    img.putalpha(Image.fromarray(np.minimum(np.asarray(img.getchannel('A')), np.asarray(circ)).astype(np.uint8), 'L'))
    if anel:
        ImageDraw.Draw(img).ellipse([0, 0, S - 1, S - 1], outline=anel, width=max(1, int(S * 0.022)))
    save(img.resize((size, size), Image.LANCZOS), path)


def make_mascara(path, cor, lado_dp, folga_dp=T.MASCARA_FOLGA, escala=3, anel=None):
    """Moldura: quadrado na cor do fundo com um FURO redondo transparente. Fica por cima da foto e a deixa redonda.
    O quadrado e 'folga_dp' maior que o avatar de cada lado (o furo tem exatamente o lado do avatar): assim a borda
    da moldura cai FORA da area visivel e nenhum filete da foto aparece no contorno do quadrado."""
    S = (lado_dp + 2 * folga_dp) * escala * SS
    m = folga_dp * escala * SS
    img = Image.new('RGBA', (S, S), cor)
    furo = Image.new('L', (S, S), 255)
    ImageDraw.Draw(furo).ellipse([m, m, S - 1 - m, S - 1 - m], fill=0)
    img.putalpha(furo)
    if anel:
        ImageDraw.Draw(img).ellipse([m, m, S - 1 - m, S - 1 - m], outline=anel, width=max(1, int(lado_dp * escala * SS * 0.022)))
    save(img.resize((S // SS, S // SS), Image.LANCZOS), path)


def cor_do_topo(topo_png, fx, fy):
    """Cor do cabecalho (imagem ja gerada) no ponto de fracoes (fx, fy): usada na moldura do avatar do cabecalho."""
    im = Image.open(topo_png).convert('RGBA')
    x, y = int(im.width * fx), int(im.height * fy)
    box = im.crop((x - 6, y - 6, x + 6, y + 6)).resize((1, 1), Image.BOX)
    r, g, b, a = box.getpixel((0, 0))
    return (r, g, b, 255)


def make_icone_tema(path, lua, size=144):
    """Botao do cabecalho: ladrilho translucido (como as pastilhas) com lua (tema claro) ou sol (tema escuro) em branco."""
    S = size * SS
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(S * 0.30)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=(255, 255, 255, 34))
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, outline=(255, 255, 255, 56), width=max(1, int(S * 0.025)))
    g = Image.new('L', (S, S), 0)
    gd = ImageDraw.Draw(g)
    c = S / 2.0
    if lua:
        R = S * 0.235
        gd.ellipse([c - R, c - R, c + R, c + R], fill=255)
        ox, oy, R2 = S * 0.105, -S * 0.085, S * 0.205
        gd.ellipse([c + ox - R2, c + oy - R2, c + ox + R2, c + oy + R2], fill=0)
    else:
        R = S * 0.125
        gd.ellipse([c - R, c - R, c + R, c + R], fill=255)
        lw = int(S * 0.05)
        for k in range(8):
            a = math.radians(45 * k)
            x1, y1 = c + math.cos(a) * S * 0.20, c + math.sin(a) * S * 0.20
            x2, y2 = c + math.cos(a) * S * 0.285, c + math.sin(a) * S * 0.285
            gd.line([(x1, y1), (x2, y2)], fill=255, width=lw)
            for (px, py) in ((x1, y1), (x2, y2)):
                gd.ellipse([px - lw / 2, py - lw / 2, px + lw / 2, py + lw / 2], fill=255)
    branco = Image.new('RGBA', (S, S), (255, 255, 255, 255))
    branco.putalpha(g)
    img = Image.alpha_composite(img, branco)
    save(img.resize((size, size), Image.LANCZOS), path)


# --------------------------------------------------------------------------- v1.7: lupa e caixa de marcar
def make_lupa(path, cor, size=72):
    """Lupa simples (circulo + cabo) na cor 'cor', fundo transparente."""
    S = size * SS
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lw = int(S * 0.10)
    cx, cy, r = S * 0.42, S * 0.42, S * 0.25
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=cor, width=lw)
    a = math.radians(45)
    x1, y1 = cx + math.cos(a) * (r + lw * 0.3), cy + math.sin(a) * (r + lw * 0.3)
    x2, y2 = S * 0.86, S * 0.86
    d.line([(x1, y1), (x2, y2)], fill=cor, width=int(lw * 1.25))
    for (px, py) in ((x2, y2),):
        q = lw * 0.62
        d.ellipse([px - q, py - q, px + q, py + q], fill=cor)
    save(img.resize((size, size), Image.LANCZOS), path)


def make_check(path, marcado, cor, borda, fundo, size=84):
    """Caixa de marcar arredondada: vazia (so contorno) ou cheia na cor da marca com o visto branco."""
    S = size * SS
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = int(S * 0.08)
    r = int(S * 0.22)
    if marcado:
        d.rounded_rectangle([m, m, S - 1 - m, S - 1 - m], radius=r, fill=cor)
        lw = int(S * 0.11)
        pts = [(S * 0.28, S * 0.52), (S * 0.44, S * 0.68), (S * 0.73, S * 0.36)]
        d.line(pts, fill=(255, 255, 255, 255), width=lw, joint='curve')
        for p in (pts[0], pts[2]):
            d.ellipse([p[0] - lw / 2, p[1] - lw / 2, p[0] + lw / 2, p[1] + lw / 2], fill=(255, 255, 255, 255))
    else:
        d.rounded_rectangle([m, m, S - 1 - m, S - 1 - m], radius=r, fill=fundo, outline=borda, width=int(S * 0.075))
    save(img.resize((size, size), Image.LANCZOS), path)


# --------------------------------------------------------------------------- v1.8: icones de traco (linha simples)
def make_ic18(path, nome, cor, size=96):
    """Icones de traco na cor 'cor' (fundo transparente), desenhados em 4x e reduzidos."""
    S = size * SS
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = max(2, int(S * 0.085))
    u = S / 24.0                     # grade de 24 "pontos" (como os icones de traco comuns)
    P = lambda x, y: (x * u, y * u)
    def linha(*pts):
        d.line([P(*p) for p in pts], fill=cor, width=w, joint='curve')
        for p in (pts[0], pts[-1]):
            q = w / 2.0
            d.ellipse([p[0] * u - q, p[1] * u - q, p[0] * u + q, p[1] * u + q], fill=cor)
    def caixa(x0, y0, x1, y1, r):
        d.rounded_rectangle([x0 * u, y0 * u, x1 * u, y1 * u], radius=r * u, outline=cor, width=w)
    if nome == 'limites':            # velocimetro: meio circulo + ponteiro
        d.arc([3 * u, 5 * u, 21 * u, 23 * u], 180, 360, fill=cor, width=w)
        linha((12, 14), (16.5, 9.5))
        q = w * 0.9
        d.ellipse([12 * u - q, 14 * u - q, 12 * u + q, 14 * u + q], fill=cor)
        linha((3.5, 14), (5.5, 14)); linha((18.5, 14), (20.5, 14))
    elif nome == 'importar':         # bandeja + seta para baixo
        linha((12, 3), (12, 14)); linha((7.5, 9.5), (12, 14), (16.5, 9.5))
        linha((3.5, 14.5), (3.5, 19.5), (20.5, 19.5), (20.5, 14.5))
    elif nome == 'planilha':         # tabela
        caixa(3.5, 4, 20.5, 20, 2.5)
        linha((3.5, 9.5), (20.5, 9.5)); linha((3.5, 14.8), (20.5, 14.8)); linha((9.5, 9.5), (9.5, 20))
    elif nome == 'backup':           # nuvem + seta para cima
        d.arc([3 * u, 9 * u, 11 * u, 17 * u], 90, 270, fill=cor, width=w)
        d.arc([6.5 * u, 4.5 * u, 17.5 * u, 15.5 * u], 180, 330, fill=cor, width=w)
        d.arc([13 * u, 8.5 * u, 21 * u, 16.5 * u], 270, 90, fill=cor, width=w)
        linha((7, 17), (17, 17))
        linha((12, 20.5), (12, 11.5)); linha((9, 14.5), (12, 11.5), (15, 14.5))
    elif nome == 'restaurar':        # seta em circulo (voltar no tempo)
        d.arc([4 * u, 4 * u, 20 * u, 20 * u], 200, 520, fill=cor, width=w)
        linha((4.6, 7.5), (5.2, 12.2), (9.6, 10.6))
        linha((12, 8), (12, 12), (15, 14))
    elif nome == 'calendario':
        caixa(3.5, 5, 20.5, 20.5, 2.5)
        linha((3.5, 10), (20.5, 10)); linha((8, 3), (8, 7)); linha((16, 3), (16, 7))
        for (x, y) in ((8, 14), (12, 14), (16, 14), (8, 17.5), (12, 17.5)):
            q = w * 0.75
            d.ellipse([x * u - q, y * u - q, x * u + q, y * u + q], fill=cor)
    elif nome == 'alvo':             # alvo (meta)
        for r in (9, 5.5):
            d.ellipse([(12 - r) * u, (12 - r) * u, (12 + r) * u, (12 + r) * u], outline=cor, width=w)
        q = 2.2 * u
        d.ellipse([12 * u - q, 12 * u - q, 12 * u + q, 12 * u + q], fill=cor)
    elif nome == 'seta':             # chevron ">"
        linha((9.5, 6), (15.5, 12), (9.5, 18))
    elif nome == 'sino':             # v2.0: sino (notificacoes)
        d.arc([5.5 * u, 4 * u, 18.5 * u, 17 * u], 180, 360, fill=cor, width=w)
        linha((5.5, 10.5), (5.5, 15), (3.5, 17.5), (20.5, 17.5), (18.5, 15), (18.5, 10.5))
        linha((12, 2.5), (12, 4))
        d.arc([9.5 * u, 17.5 * u, 14.5 * u, 22 * u], 0, 180, fill=cor, width=w)
    else:
        raise ValueError(nome)
    save(img.resize((size, size), Image.LANCZOS), path)


def reduzir_sem_halo(img, tamanho):
    """v1.8.1: reduz o desenho supersampleado pela MEDIA de cada bloco (Image.BOX). O LANCZOS cria um anel mais claro
    na borda do traco (ate +9 em cada canal); com a media, todo pixel visivel tem exatamente a cor do desenho e so a
    transparencia varia na borda (o Pillow ja pre-multiplica o alfa ao reduzir RGBA)."""
    return img.resize(tamanho, Image.BOX)


def make_seta(path, direita, cor, w_dp=None, h_dp=None, scale=3):
    """v1.8.1: seta "<" / ">" como IMAGEM do botao (no Android o texto de um botao pequeno some atras da margem
    interna do tema). A figura tem o MESMO formato do botao (SETA_W x SETA_H dp), entao nada distorce."""
    w_dp = w_dp or T.SETA_W
    h_dp = h_dp or T.SETA_H
    W, H = w_dp * scale * SS, h_dp * scale * SS
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = scale * SS                          # 1 dp
    alt, larg, esp = 15.0, 8.0, 2.6         # altura e largura do chevron e espessura do traco (dp), como o "<" de 24sp
    cx, cy = W / 2.0, H / 2.0
    if direita:
        pts = [(cx - larg / 2 * u, cy - alt / 2 * u), (cx + larg / 2 * u, cy), (cx - larg / 2 * u, cy + alt / 2 * u)]
    else:
        pts = [(cx + larg / 2 * u, cy - alt / 2 * u), (cx - larg / 2 * u, cy), (cx + larg / 2 * u, cy + alt / 2 * u)]
    w = int(esp * u)
    d.line(pts, fill=cor, width=w, joint='curve')
    for p in (pts[0], pts[-1]):
        q = w / 2.0
        d.ellipse([p[0] - q, p[1] - q, p[0] + q, p[1] + q], fill=cor)
    save(reduzir_sem_halo(img, (w_dp * scale, h_dp * scale)), path)


def make_fechar(path, cor, lado_dp=None, scale=3):
    """v1.8.1: "x" do campo de busca como imagem do botao."""
    lado_dp = lado_dp or T.FECHAR_LADO
    S = lado_dp * scale * SS
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = scale * SS
    r, esp = 5.5, 2.2
    c = S / 2.0
    w = int(esp * u)
    for (x0, y0, x1, y1) in ((c - r * u, c - r * u, c + r * u, c + r * u), (c - r * u, c + r * u, c + r * u, c - r * u)):
        d.line([(x0, y0), (x1, y1)], fill=cor, width=w)
        for (x, y) in ((x0, y0), (x1, y1)):
            q = w / 2.0
            d.ellipse([x - q, y - q, x + q, y + q], fill=cor)
    save(reduzir_sem_halo(img, (lado_dp * scale, lado_dp * scale)), path)


def make_letra_mes(path, letra, cor, fonte_ttf, lado_dp=None, tam_sp=12.5, scale=3):
    """v1.8.1: inicial do mes (J F M ...) como imagem quadrada do botao, centrada pela altura das maiusculas."""
    lado_dp = lado_dp or T.MES_LADO
    S = lado_dp * scale * SS
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(fonte_ttf, int(round(tam_sp * scale * SS)))
    x0, y0, x1, y1 = d.textbbox((0, 0), letra, font=f)
    d.text(((S - (x1 - x0)) / 2.0 - x0, (S - (y1 - y0)) / 2.0 - y0), letra, font=f, fill=cor)
    save(reduzir_sem_halo(img, (lado_dp * scale, lado_dp * scale)), path)


def make_transparent(path, size=8):
    save(Image.new('RGBA', (size, size), (0, 0, 0, 0)), path)


# --------------------------------------------------------------------------- principal
def main(out_dir, fonts_dir, sizes_json=None):
    sizes = dict(T.SIZES)
    if sizes_json and os.path.exists(sizes_json):
        sizes.update(json.load(open(sizes_json)))
    os.makedirs(out_dir, exist_ok=True)
    P = lambda n: os.path.join(out_dir, n)

    make_topo(P(T.IMG_TOPO), T.W_TELA, sizes['header_h'])
    make_chip(P(T.IMG_CHIP), sizes['chip_w'], sizes['chip_h'])
    make_logo(P(T.IMG_LOGO), 120)
    make_logo(P(T.IMG_ICONE), 512)
    arrow_icon(P(T.IMG_SETA_ENT), True)
    arrow_icon(P(T.IMG_SETA_DESP), False)
    make_campo(P(T.IMG_CAMPO), sizes['campo_w'], sizes['campo_h'], seta=False)
    make_campo(P(T.IMG_CAMPO_SEL), sizes['campo_w'], sizes['campo_h'], seta=True)
    make_campo(P(T.IMG_CAMPO_ERRO), sizes['campo_w'], sizes['campo_h'], seta=False, erro=True)
    make_campo(P(T.IMG_CAMPO_SEL_ERRO), sizes['campo_w'], sizes['campo_h'], seta=True, erro=True)
    make_pill(P(T.IMG_AVISO_OK), sizes['aviso_w'], sizes['aviso_h'], T.AVISO_OK_BG, outline=T.AVISO_OK_BORDER, raio_dp=14)
    make_pill(P(T.IMG_AVISO_ERRO), sizes['aviso_w'], sizes['aviso_h'], T.DANGER_BG, outline=T.DANGER_BORDER, raio_dp=14)
    make_icone_vazio(P(T.IMG_IC_VAZIO))
    for nome, arq, emo, bg in T.CATEGORIAS + T.PAGAMENTOS:
        make_icone(P(arq), emo, bg)
    make_cartao(P(T.IMG_CARTAO_LANCAR), T.W_TELA, sizes['cartao_lancar_h'])
    make_cartao(P(T.IMG_CARTAO_GRAF), T.W_TELA, sizes['cartao_grafico_h'])
    make_pill(P(T.IMG_ABAS), sizes['abas_w'], sizes['abas_h'], '#FFFFFF', outline=T.BORDER)
    make_pill(P(T.IMG_ABA_ON), 110, T.PILULA_H, T.EMERALD, grad=('#0E8069', '#0B6A57'))   # topo mais claro = 4,87:1 com texto branco
    make_pill(P(T.IMG_PILULA_SEC), T.PILULA_SEC_W, T.PILULA_H, '#FFFFFF', outline=T.BORDER)          # v1.9
    make_transparent(P(T.IMG_ABA_OFF))
    make_pill(P(T.IMG_BTN_ENT), sizes['btn_w'], sizes['btn_h'], T.GREEN_D, raio_dp=16, grad=(T.GREEN_D, '#0F6E45'))   # o ponto mais claro ja da 4,59:1 com texto branco
    make_pill(P(T.IMG_BTN_DESP), sizes['btn_w'], sizes['btn_h'], T.RED_D, raio_dp=16, grad=(T.RED_D, '#B9333A'))   # o ponto mais claro ja da 4,71:1 com texto branco
    make_pill(P(T.IMG_BTN_PERIGO), sizes['perigo_w'], sizes['perigo_h'], T.DANGER_BG, outline=T.DANGER_BORDER, raio_dp=16)
    dot_icon(P(T.IMG_PONTO_VERDE), T.GREEN)
    dot_icon(P(T.IMG_PONTO_VERM), T.RED)
    # v1.9: bolinhas da legenda da rosca, uma por categoria, nos dois temas (a cor e a mesma da fatia)
    for i, (cl, es) in enumerate(T.CORES_CAT, 1):
        ponto_cat(P(T.img_ponto_cat(i)), cl)
        ponto_cat(P(T.img_ponto_cat(i, True)), es)

    # ---- v1.6: variantes do tema escuro (mesmo desenho, outra paleta) -> arquivo "<nome>_d.png"
    E = T.escuro
    campo_d = dict(fill=T.D_FIELD, borda=T.D_BORDER, borda_erro=T.D_RED_BORDER, cor_seta=T.D_EMERALD)
    make_campo(P(E(T.IMG_CAMPO)), sizes['campo_w'], sizes['campo_h'], seta=False, **campo_d)
    make_campo(P(E(T.IMG_CAMPO_SEL)), sizes['campo_w'], sizes['campo_h'], seta=True, **campo_d)
    make_campo(P(E(T.IMG_CAMPO_ERRO)), sizes['campo_w'], sizes['campo_h'], seta=False, erro=True, **campo_d)
    make_campo(P(E(T.IMG_CAMPO_SEL_ERRO)), sizes['campo_w'], sizes['campo_h'], seta=True, erro=True, **campo_d)
    make_pill(P(E(T.IMG_AVISO_OK)), sizes['aviso_w'], sizes['aviso_h'], T.D_AVISO_OK_BG, outline=T.D_AVISO_OK_BORDER, raio_dp=14)
    make_pill(P(E(T.IMG_AVISO_ERRO)), sizes['aviso_w'], sizes['aviso_h'], T.D_DANGER_BG, outline=T.D_DANGER_BORDER, raio_dp=14)
    make_icone_vazio(P(E(T.IMG_IC_VAZIO)), bg=T.D_VAZIO_BG, fg=T.D_VAZIO_FG)
    cartao_d = dict(fill=T.D_CARD, contorno=T.D_CARD_BORDER, sombra_rgb=(0, 0, 0), forca=1.6)
    make_cartao(P(E(T.IMG_CARTAO_LANCAR)), T.W_TELA, sizes['cartao_lancar_h'], **cartao_d)
    make_cartao(P(E(T.IMG_CARTAO_GRAF)), T.W_TELA, sizes['cartao_grafico_h'], **cartao_d)
    make_pill(P(E(T.IMG_ABAS)), sizes['abas_w'], sizes['abas_h'], T.D_CARD, outline=T.D_BORDER)
    make_pill(P(E(T.IMG_PILULA_SEC)), T.PILULA_SEC_W, T.PILULA_H, T.D_CARD, outline=T.D_BORDER)      # v1.9
    make_pill(P(E(T.IMG_BTN_PERIGO)), sizes['perigo_w'], sizes['perigo_h'], T.D_DANGER_BG, outline=T.D_DANGER_BORDER, raio_dp=16)

    # ---- v1.6: perfil (avatar padrao + moldura redonda) e botao de tema do cabecalho
    make_avatar(P(T.IMG_AVATAR), rgba('#D6ECE4'), rgba(T.EMERALD), anel=rgba('#B9D9CD'))
    make_avatar(P(E(T.IMG_AVATAR)), rgba('#22362F'), rgba('#7FD9BF'), anel=rgba('#35514A'))
    make_mascara(P(T.IMG_MASCARA), rgba(T.CARD), T.AVATAR, anel=rgba('#B9D9CD'))
    make_mascara(P(E(T.IMG_MASCARA)), rgba(T.D_CARD), T.AVATAR, anel=rgba('#35514A'))
    cor = cor_do_topo(P(T.IMG_TOPO), sizes.get('avatar_fx', 0.90), sizes.get('avatar_fy', 0.13))
    disco = tuple(int(c + (255 - c) * 0.20) for c in cor[:3]) + (255,)
    make_avatar(P(T.IMG_AVATAR_TOPO), disco, (255, 255, 255, 255), size=160, anel=(255, 255, 255, 150))
    make_mascara(P(T.IMG_MASCARA_TOPO), cor, T.AVATAR_TOPO, escala=4, anel=(255, 255, 255, 150))
    make_icone_tema(P(T.IMG_TEMA_LUA), True)
    make_icone_tema(P(T.IMG_TEMA_SOL), False)

    # ---- v1.7: campo estreito (limites), lupa da busca, caixa "Repetir todo mes"
    cw = sizes['campo_curto_w']
    make_campo(P(T.IMG_CAMPO_CURTO), cw, sizes['campo_h'])
    make_campo(P(T.IMG_CAMPO_CURTO_ERRO), cw, sizes['campo_h'], erro=True)
    make_campo(P(E(T.IMG_CAMPO_CURTO)), cw, sizes['campo_h'], **campo_d)
    make_campo(P(E(T.IMG_CAMPO_CURTO_ERRO)), cw, sizes['campo_h'], erro=True, **campo_d)
    make_lupa(P(T.IMG_BUSCA), rgba(T.MUTED))
    make_lupa(P(E(T.IMG_BUSCA)), rgba(T.D_MUTED))
    make_check(P(T.IMG_CHECK_OFF), False, rgba(T.EMERALD), rgba('#8FA39B'), rgba(T.CARD))
    make_check(P(T.IMG_CHECK_ON), True, rgba(T.EMERALD), rgba('#8FA39B'), rgba(T.CARD))
    make_check(P(E(T.IMG_CHECK_OFF)), False, rgba(T.D_EMERALD), rgba('#7D928A'), rgba(T.D_FIELD))
    make_check(P(E(T.IMG_CHECK_ON)), True, rgba('#2FA889'), rgba('#7D928A'), rgba(T.D_FIELD))

    # ---- v1.8: icones (marca no claro; marca clara no escuro; seta discreta) e cartao pequeno da meta
    for n in T.IC18:
        claro, escuro_ = (rgba(T.MUTED), rgba(T.D_MUTED)) if n == 'seta' else (rgba(T.EMERALD), rgba(T.D_EMERALD))
        make_ic18(P(T.IMG_IC18[n]), n, claro)
        make_ic18(P(E(T.IMG_IC18[n])), n, escuro_)
    make_cartao(P(T.IMG_CARTAO_MINI), T.W_TELA, sizes['mini_h'], raio_dp=18, base=8)
    make_cartao(P(E(T.IMG_CARTAO_MINI)), T.W_TELA, sizes['mini_h'], raio_dp=18, base=8, **cartao_d)

    # ---- v1.8.1: setas, "x" da busca e iniciais dos meses como imagem (claro e escuro)
    make_seta(P(T.IMG_SETA_ESQ), False, rgba(T.EMERALD))
    make_seta(P(T.IMG_SETA_DIR), True, rgba(T.EMERALD))
    make_seta(P(E(T.IMG_SETA_ESQ)), False, rgba(T.D_EMERALD))
    make_seta(P(E(T.IMG_SETA_DIR)), True, rgba(T.D_EMERALD))
    make_fechar(P(T.IMG_FECHAR), rgba(T.MUTED))
    make_fechar(P(E(T.IMG_FECHAR)), rgba(T.D_MUTED))
    fonte_bold = os.path.join(fonts_dir, 'package', T.FONT_SRC[T.F_BOLD])
    for letra in sorted(set(T.LETRAS_MES)):
        for estado, ficha in T.ESTADOS_MES.items():
            claro_hex, escuro_hex = T.CORES[ficha]
            make_letra_mes(P(T.img_mes(letra, estado)), letra.upper(), rgba(claro_hex), fonte_bold)
            make_letra_mes(P(T.img_mes(letra, estado, True)), letra.upper(), rgba(escuro_hex), fonte_bold)

    # fontes + licenca
    for dst, rel in T.FONT_SRC.items():
        shutil.copyfile(os.path.join(fonts_dir, 'package', rel), P(dst))
    lic = os.path.join(fonts_dir, 'package', 'LICENSE_FONT')
    if os.path.exists(lic):
        shutil.copyfile(lic, P(T.FONT_LICENSE))
    print('assets gerados em', out_dir, '->', len(os.listdir(out_dir)), 'arquivos')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
