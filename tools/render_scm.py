#!/usr/bin/env python3
"""Pre-visualizacao APROXIMADA de um Screen1.scm do App Inventor (HTML + Chromium).

Nao e o App Inventor nem um Android: e um renderizador que imita as regras de layout dos componentes
(arranjos, rotulos, botoes, caixas de texto, menus, lista, grafico de pizza) para eu conferir proporcoes,
cores e hierarquia antes de entregar. Foi calibrado contra os prints reais da v1.3 do usuario.

Uso (como modulo):  render(scm_path, assets_dir, out_png, tab=1, state={...}, density=2.75)
"""
import json
import math
import os
import re
import html

W_DP = 393          # largura da tela em dp (1080 px / 2.75)
H_DP = 873          # altura total em dp (2400 px / 2.75)
STATUS_DP = 34      # barra de status
NAV_DP = 20         # barra de navegacao inferior (preta, como nos prints)
TITLE_DP = 56       # barra de titulo do App Inventor


def color(v, default=None):
    """&HAARRGGBB -> rgba()"""
    if v is None:
        return default
    m = re.fullmatch(r'&H([0-9A-Fa-f]{8})', v)
    if not m:
        return default
    n = int(m.group(1), 16)
    a, r, g, b = (n >> 24) & 255, (n >> 16) & 255, (n >> 8) & 255, n & 255
    if a == 0:
        return 'transparent'
    return 'rgba(%d,%d,%d,%.3f)' % (r, g, b, a / 255.0)


def length(v):
    """-1 automatico, -2 preencher, N px, <=-1001 percentual da TELA"""
    if v is None:
        return ('auto', None)
    n = int(float(v))
    if n == -1:
        return ('auto', None)
    if n == -2:
        return ('fill', None)
    if n <= -1000:
        return ('px', (-1000 - n) * W_DP / 100.0 * -1 if False else (-(n + 1000)) * W_DP / 100.0)
    return ('px', float(n))


# v1.8.1: escala de fonte do sistema (Configuracoes > Tela > Tamanho da fonte). O App Inventor usa sp: o texto cresce e
# os tamanhos em dp nao. 1.0 = padrao; 1.15 = "grande"; 1.3 = "maior" (varia por fabricante).
FONT_SCALE = 1.0
# v1.8.1: margem interna que o Android poe em TODO botao (ButtonBase): o fundo padrao do tema (Widget.Material.Button /
# Widget.AppCompat.Button) e um InsetDrawable de 4dp nas laterais e 6dp em cima/embaixo com <padding> de 8dp x 4dp.
# O App Inventor troca o fundo (imagem, forma, cor), mas View.setBackground so troca o padding quando o fundo novo TEM
# padding (bitmap e ShapeDrawable nao tem): o texto fica numa caixa 12dp menor de cada lado e 10dp menor em cima/embaixo.
BTN_PAD_H, BTN_PAD_V = 12, 10
FONT_FILES = {}  # nome do arquivo de fonte -> caminho
LINE_HEIGHT = 1.35  # altura de linha do TextView do Android (includeFontPadding) calibrada com os prints (Roboto)
FONT_METRICS = {}   # arquivo de fonte (asset) -> (line_height_em, pad_top_em, pad_bottom_em), lido da propria fonte


def load_font_metrics(assets_dir):
    """O Android usa (top,bottom) da caixa da fonte para a 1a/ultima linha e (ascent,descent) entre linhas.
    Reproduzo isso: line-height = ascent+descent (hhea) e o excedente vira padding em cima/embaixo."""
    FONT_METRICS.clear()
    if not (assets_dir and os.path.isdir(assets_dir)):
        return
    try:
        from fontTools.ttLib import TTFont
    except Exception:
        return
    for fn in os.listdir(assets_dir):
        if fn.lower().endswith(('.ttf', '.otf')):
            f = TTFont(os.path.join(assets_dir, fn))
            upm = float(f['head'].unitsPerEm)
            asc, desc = f['hhea'].ascent, -f['hhea'].descent
            top = max(f['head'].yMax, asc)
            bottom = max(-f['head'].yMin, desc)
            FONT_METRICS[fn] = ((asc + desc) / upm, (top - asc) / upm, (bottom - desc) / upm)


def font_css(face, bold, size, pad=True):
    fam = "Roboto, 'Noto Sans', sans-serif"
    lh, pt, pb = LINE_HEIGHT, 0.0, 0.0
    if face and face not in ('0', '1', '2', '3'):
        fam = "'F_%s', Roboto, sans-serif" % re.sub(r'\W', '_', face)
        if face in FONT_METRICS:
            lh, pt, pb = FONT_METRICS[face]
    elif face == '2':
        fam = 'serif'
    elif face == '3':
        fam = 'monospace'
    w = 700 if bold else 400
    size = float(size) * FONT_SCALE
    css = 'font-family:%s;font-weight:%d;font-size:%.3fpx;line-height:%.4f;' % (fam, w, size, lh)
    if pad and (pt or pb):
        css += 'padding-top:%.4fem;padding-bottom:%.4fem;' % (pt, pb)
    return css


class Renderer:
    def __init__(self, scm, assets, state, tab, density):
        self.assets = assets
        self.state = state or {}
        self.tab = tab
        self.density = density
        self.comps = {}
        self.form = scm['Properties']
        self.counter = 0

    # ------------------------------------------------------------------ util
    def prop(self, c, name, default=None):
        key = '%s.%s' % (c.get('$Name'), name)
        if key in self.state:
            return str(self.state[key])
        return c.get(name, default)

    def visible(self, c):
        name = c.get('$Name')
        v = self.prop(c, 'Visible', 'True')
        # Os paineis das abas sao mostrados/escondidos em tempo de execucao pelos blocos (mostrarAba):
        # o valor do designer (Visible=False) nao vale depois do Initialize, entao so a aba ativa conta.
        if (name + '.Visible') in self.state:
            return self.state[name + '.Visible'] == 'True'   # estado real deixado pelos blocos (v1.6: vale para todo componente)
        if name == 'PnlLancar':
            return self.tab == 1
        if name == 'PnlHistorico':
            return self.tab == 2
        if name == 'PnlGrafico':
            return self.tab == 3
        return v != 'False'

    def size_css(self, c, parent_vertical):
        css = []
        wk, wv = length(self.prop(c, 'Width'))
        hk, hv = length(self.prop(c, 'Height'))
        if wk == 'px':
            css.append('width:%.2fpx;flex:none;' % wv if not parent_vertical else 'width:%.2fpx;' % wv)
        elif wk == 'fill':
            css.append('align-self:stretch;' if parent_vertical else 'flex:1 1 0;min-width:0;')
        if hk == 'px':
            css.append('height:%.2fpx;' % hv + ('flex:none;' if parent_vertical else ''))
        elif hk == 'fill':
            css.append('flex:1 1 0;min-height:0;' if parent_vertical else 'align-self:stretch;')
        return ''.join(css)

    # --------------------------------------------------------------- render
    def render_children(self, c, vertical):
        out = []
        for ch in c.get('$Components', []):
            out.append(self.render(ch, vertical))
        return ''.join(out)

    def render(self, c, parent_vertical):
        t = c['$Type']
        name = c['$Name']
        if t in ('TinyDB', 'Clock', 'Notifier', 'File', 'Sharing', 'Camera', 'LeitorNotificacoes'):     # nao visiveis (v1.9: Camera; v2.0: extensao)
            return ''
        if not self.visible(c):
            return ''
        fn = getattr(self, 'r_' + t, None)
        if fn is None:
            return '<div style="outline:1px dashed red">%s?</div>' % t
        return fn(c, parent_vertical)

    def arrangement(self, c, parent_vertical, vertical):
        ah = self.prop(c, 'AlignHorizontal', '1')
        av = self.prop(c, 'AlignVertical', '1')
        hmap = {'1': 'flex-start', '2': 'flex-end', '3': 'center'}
        vmap = {'1': 'flex-start', '2': 'center', '3': 'flex-end'}
        if vertical:
            inner = 'flex-direction:column;align-items:%s;justify-content:%s;' % (hmap.get(ah, 'flex-start'), vmap.get(av, 'flex-start'))
        else:
            inner = 'flex-direction:row;justify-content:%s;align-items:%s;' % (hmap.get(ah, 'flex-start'), vmap.get(av, 'flex-start'))
        bg = color(self.prop(c, 'BackgroundColor'))
        style = 'display:flex;%s' % inner
        if bg and bg != 'transparent':
            style += 'background:%s;' % bg
        img = self.prop(c, 'Image')
        if img:
            p = self.asset_url(img)
            if p:
                style += "background-image:url('%s');background-size:100%% 100%%;background-repeat:no-repeat;" % p
        style += self.size_css(c, parent_vertical)
        wk, _ = length(self.prop(c, 'Width'))
        hk, _ = length(self.prop(c, 'Height'))
        if wk == 'px' and hk == 'px':
            # filho maior que o arranjo de tamanho fixo e cortado nas bordas. 'will-change' poe o arranjo numa camada propria:
            # sem isso o Chromium recorta cada filho separadamente em posicoes fracionarias (393 dp x 2,75) e deixa um
            # filete da foto na borda -- defeito so do meu renderizador (no Android os limites da View sao pixels inteiros)
            style += 'overflow:hidden;will-change:transform;'
        return '<div class="c" data-name="%s" style="%s">%s</div>' % (c['$Name'], style, self.render_children(c, vertical))

    def r_VerticalArrangement(self, c, pv):
        return self.arrangement(c, pv, True)

    def r_HorizontalArrangement(self, c, pv):
        return self.arrangement(c, pv, False)

    def r_Label(self, c, pv):
        text = self.prop(c, 'Text', '')
        size = float(self.prop(c, 'FontSize', '14'))
        bold = self.prop(c, 'FontBold', 'False') == 'True'
        face = self.prop(c, 'FontTypeface', '0')
        col = color(self.prop(c, 'TextColor'), '#000')
        al = {'0': 'left', '1': 'center', '2': 'right'}.get(self.prop(c, 'TextAlignment', '0'), 'left')
        margin = 2 if self.prop(c, 'HasMargins', 'True') != 'False' else 0
        bg = color(self.prop(c, 'BackgroundColor'))
        style = font_css(face, bold, size) + 'color:%s;text-align:%s;margin:%spx;white-space:pre-wrap;' % (col, al, margin)
        if bg and bg != 'transparent':
            style += 'background:%s;' % bg
        # sem largura definida o rotulo ocupa so o conteudo
        style += self.size_css(c, pv)
        if self.prop(c, 'Width') in (None, '-1') and pv:
            style += 'align-self:auto;'
        return '<div class="c" data-name="%s" style="%s">%s</div>' % (c['$Name'], style, html.escape(text).replace('\n', '<br>') if False else html.escape(text))

    def r_Button(self, c, pv):
        """Botao como o ButtonBase do App Inventor desenha no Android (v1.8.1: margem interna e sombra do tema).
        - com imagem: a figura estica sobre o botao inteiro e o tamanho minimo vai a zero (setMinSize(0, 0));
        - sem imagem: 88 x 48 dp de tamanho minimo; forma padrao (0) com fundo "nenhum" = o fundo do tema com a cor
          apagada (PorterDuff CLEAR), mas o contorno/sombra do Material continua: no aparelho aparece um quadrado vazio
          (o defeito das fotos do usuario na v1.8); com forma 1-3 a forma e desenhada na cor e, sendo "nenhum", sem sombra;
        - o texto fica DENTRO da margem interna (BTN_PAD_H x BTN_PAD_V), quebra linha como o TextView e o que nao cabe
          e cortado; texto mais alto que a caixa comeca no topo (TextView.getVerticalOffset da 0) e perde o pe."""
        text = self.prop(c, 'Text', '')
        size = float(self.prop(c, 'FontSize', '14'))
        bold = self.prop(c, 'FontBold', 'False') == 'True'
        face = self.prop(c, 'FontTypeface', '0')
        col = color(self.prop(c, 'TextColor'), '#000')
        img = self.prop(c, 'Image')
        url = self.asset_url(img) if img else None
        wk, _ = length(self.prop(c, 'Width'))
        hk, _ = length(self.prop(c, 'Height'))
        al = {'0': 'flex-start', '1': 'center', '2': 'flex-end'}.get(self.prop(c, 'TextAlignment', '1'), 'center')
        ta = {'flex-start': 'left', 'center': 'center', 'flex-end': 'right'}[al]
        rawbg = self.prop(c, 'BackgroundColor', '&H00000000')
        shape = self.prop(c, 'Shape', '0')
        style = 'position:relative;display:flex;box-sizing:border-box;padding:%dpx %dpx;color:%s;' % (BTN_PAD_V, BTN_PAD_H, col)
        moldura = ''
        if url:
            style += "background-image:url('%s');background-size:100%% 100%%;background-repeat:no-repeat;" % url
            minw = minh = 0
        else:
            minw, minh = 88, 48
            if rawbg == '&H00FFFFFF':
                style += 'background:transparent;'
                if shape == '0':
                    moldura = ('<div class="moldura" style="position:absolute;left:4px;right:4px;top:6px;bottom:6px;border-radius:2px;'
                               'box-shadow:0 1px 1.5px rgba(0,0,0,.30),0 1px 4px rgba(0,0,0,.16);pointer-events:none"></div>')
            else:
                bg = color(rawbg, '#d6d7d7')
                if rawbg in (None, '&H00000000'):
                    bg = '#d6d7d7'
                radius = {'0': 2, '1': 10.0 / self.density, '2': 0, '3': 999}.get(shape, 2)
                style += 'background:%s;border-radius:%.2fpx;' % (bg, radius)
        if wk == 'auto':
            style += 'min-width:%dpx;' % minw
        if hk == 'auto':
            style += 'min-height:%dpx;' % minh
        style += self.size_css(c, pv)
        caixa = ('flex:1 1 auto;min-width:0;min-height:0;overflow:hidden;display:flex;'
                 'align-items:safe center;justify-content:safe %s;' % al)
        letra = font_css(face, bold, size) + 'display:block;max-width:100%%;text-align:%s;white-space:pre-wrap;overflow-wrap:anywhere;' % ta
        return ('<div class="c" data-name="%s" data-btn="1" style="%s">%s<div class="cx" style="%s"><span class="tx" style="%s">%s</span></div></div>'
                % (c['$Name'], style, moldura, caixa, letra, html.escape(text)))

    def r_TextBox(self, c, pv):
        size = float(self.prop(c, 'FontSize', '14'))
        face = self.prop(c, 'FontTypeface', '0')
        bold = self.prop(c, 'FontBold', 'False') == 'True'
        hint = self.prop(c, 'Hint', '')
        text = self.prop(c, 'Text', '')
        col = color(self.prop(c, 'TextColor'), 'rgba(0,0,0,.87)')
        hcol = color(self.prop(c, 'HintColor'), 'rgba(0,0,0,.38)')
        rawbg = self.prop(c, 'BackgroundColor')
        shown = html.escape(text) if text else '<span style="color:%s">%s</span>' % (hcol, html.escape(hint))
        style = font_css(face, bold, size, pad=False) + 'color:%s;' % col
        style += 'box-sizing:border-box;display:flex;align-items:center;padding:0 4px 0 4px;min-height:42px;position:relative;'
        underline = '<i style="position:absolute;left:0;right:0;bottom:7px;height:1.4px;background:rgba(0,0,0,.42)"></i>'
        al = {'0': 'flex-start', '1': 'center', '2': 'flex-end'}.get(self.prop(c, 'TextAlignment', '0'), 'flex-start')
        style += 'justify-content:%s;' % al
        if rawbg not in (None, '&H00000000'):
            # qualquer cor diferente de "padrao" (inclusive "nenhum" = &H00FFFFFF) troca o fundo e some o tracinho
            bg = color(rawbg)
            if bg and bg != 'transparent':
                style += 'background:%s;' % bg
            underline = ''
        style += self.size_css(c, pv)
        return '<div class="c" data-name="%s" style="%s">%s%s</div>' % (c['$Name'], style, shown, underline)

    def r_Spinner(self, c, pv):
        size = float(self.prop(c, 'FontSize', '14'))
        face = self.prop(c, 'FontTypeface', '0')
        bold = self.prop(c, 'FontBold', 'False') == 'True'
        items = (self.prop(c, 'ElementsFromString', '') or '').split(',')
        col = color(self.prop(c, 'TextColor'), 'rgba(0,0,0,.87)')
        al = {'0': 'flex-start', '1': 'center', '2': 'flex-end'}.get(self.prop(c, 'TextAlignment', '1'), 'center')
        style = font_css(face, bold, size, pad=False) + 'color:%s;' % col
        style += 'box-sizing:border-box;display:flex;align-items:center;justify-content:%s;min-height:25px;position:relative;padding:0 48px 0 0;' % al
        style += self.size_css(c, pv)
        arrow = '<div style="position:absolute;right:18px;top:50%;margin-top:-3px;width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;border-top:6px solid #fff"></div>'
        sel = self.state.get('%s.Selection' % c['$Name'])
        return '<div class="c" data-name="%s" style="%s">%s%s</div>' % (c['$Name'], style, html.escape(sel if sel else (items[0] if items else '')), arrow)

    def r_ImagePicker(self, c, pv):
        return self.r_Button(c, pv)

    def r_FilePicker(self, c, pv):        # v1.7: botao 'Restaurar backup' (um Picker, desenhado como botao)
        return self.r_Button(c, pv)

    def r_DatePicker(self, c, pv):        # v1.8: campo de data (ButtonBase, desenhado como botao)
        return self.r_Button(c, pv)

    def r_Canvas(self, c, pv):
        """Canvas com sprites de imagem: cada sprite visivel e desenhado no retangulo (X, Y, Width, Height) em dp,
        esticado nesse retangulo (como ImageSprite.onDraw), na ordem de Z; o Canvas corta o que passa das bordas."""
        bg = color(self.prop(c, 'BackgroundColor'), '#fff')
        style = 'position:relative;overflow:hidden;flex:none;background:%s;' % bg + self.size_css(c, pv)
        sprites = []
        for ch in c.get('$Components', []):
            if ch['$Type'] != 'ImageSprite' or not self.visible(ch):
                continue
            url = self.asset_url(self.prop(ch, 'Picture', ''))
            if not url:
                continue
            x, y = float(self.prop(ch, 'X', '0')), float(self.prop(ch, 'Y', '0'))
            w, h = float(self.prop(ch, 'Width', '0')), float(self.prop(ch, 'Height', '0'))
            z = float(self.prop(ch, 'Z', '1'))
            sprites.append((z, '<img data-name="%s" src="%s" style="position:absolute;left:%.2fpx;top:%.2fpx;width:%.2fpx;height:%.2fpx;display:block">' % (
                ch['$Name'], url, x, y, w, h)))
        sprites.sort(key=lambda t: t[0])
        desenho = self.desenho_canvas(c)
        return '<div class="c" data-name="%s" style="%s">%s%s</div>' % (c['$Name'], style, desenho, ''.join(h for _, h in sprites))

    def desenho_canvas(self, c):
        """v1.9: a camada de desenho do Canvas (o que os blocos desenharam, registrado pelo simulador), em SVG por cima
        do fundo e por baixo dos sprites. Angulos como no Android: graus, a partir das 3 horas, no sentido do relogio.
        Traco com ponta reta (padrao do Paint). Desenho feito ANTES de a view ser medida sai como no aparelho: num bitmap
        de 32 x 48 px esticado para o tamanho real."""
        ops = self.state.get('%s.ops' % c['$Name']) or []
        if not ops:
            return ''
        w, h = float(self.prop(c, 'Width', '0')), float(self.prop(c, 'Height', '0'))
        normais, esticados = [], []
        for op in ops:
            if op.get('tipo') != 'arco' or op.get('apaga'):
                continue                      # PaintColor = None apaga pixels (modo CLEAR): nao desenho nada
            l, t, r, b = [float(x) for x in op['caixa']]
            cx, cy, rx, ry = (l + r) / 2, (t + b) / 2, (r - l) / 2, (b - t) / 2
            n = int(op['cor']) & 0xFFFFFFFF
            cor = 'rgba(%d,%d,%d,%.3f)' % ((n >> 16) & 255, (n >> 8) & 255, n & 255, ((n >> 24) & 255) / 255.0)
            sw, lw = float(op['varre']), float(op['largura'])
            enche = bool(op.get('preencher'))
            pinta = 'fill="%s" stroke="none"' % cor if enche else 'fill="none" stroke="%s" stroke-width="%.3f" stroke-linecap="butt"' % (cor, lw)
            if sw == 0:
                continue
            if abs(sw) >= 360 and not op.get('centro'):
                el = '<ellipse cx="%.3f" cy="%.3f" rx="%.3f" ry="%.3f" %s/>' % (cx, cy, rx, ry, pinta)
            else:
                sw = max(-359.999, min(359.999, sw))
                a0, a1 = math.radians(float(op['ini'])), math.radians(float(op['ini']) + sw)
                x0, y0 = cx + rx * math.cos(a0), cy + ry * math.sin(a0)
                x1, y1 = cx + rx * math.cos(a1), cy + ry * math.sin(a1)
                d = 'M%.3f,%.3f A%.3f,%.3f 0 %d %d %.3f,%.3f' % (x0, y0, rx, ry, 1 if abs(sw) > 180 else 0, 1 if sw > 0 else 0, x1, y1)
                if op.get('centro'):
                    d = 'M%.3f,%.3f L%.3f,%.3f' % (cx, cy, x0, y0) + d[d.index(' A'):] + ' Z'
                elif enche:
                    d += ' Z'
                el = '<path d="%s" %s/>' % (d, pinta)
            (esticados if op.get('esticado') else normais).append(el)
        svg = ''.join(normais)
        if esticados:
            bw, bh = 32 / self.density, 48 / self.density            # o bitmap inicial, em dp
            svg += '<g transform="scale(%.4f,%.4f)"><svg x="0" y="0" width="%.4f" height="%.4f" viewBox="0 0 %.4f %.4f" overflow="hidden">%s</svg></g>' % (
                w / bw, h / bh, bw, bh, bw, bh, ''.join(esticados))
        return '<svg data-name="%s_desenho" viewBox="0 0 %.3f %.3f" style="position:absolute;left:0;top:0;width:%.3fpx;height:%.3fpx;overflow:hidden">%s</svg>' % (
            c['$Name'], w, h, w, h, svg)

    def r_Image(self, c, pv):
        pic = self.prop(c, 'Picture', '')
        p = self.asset_url(pic)
        style = self.size_css(c, pv)
        if self.prop(c, 'Width') in (None, '-1') and pv:
            style += 'align-self:auto;'
        return '<img class="c" data-name="%s" src="%s" style="%sobject-fit:contain;margin:0;">' % (c['$Name'], p or '', style)

    def r_ListView(self, c, pv):
        rows = self.state.get('%s.Elements' % c['$Name'], [])
        layout = self.prop(c, 'ListViewLayout', '0')
        fs = float(self.prop(c, 'FontSize', self.prop(c, 'TextSize', '22')))
        fsd = float(self.prop(c, 'FontSizeDetail', '14'))
        ft = self.prop(c, 'FontTypeface', '0')
        ftd = self.prop(c, 'FontTypefaceDetail', '0')
        col = color(self.prop(c, 'TextColor'), '#fff')
        cold = color(self.prop(c, 'TextColorDetail'), '#fff')
        bg = color(self.prop(c, 'BackgroundColor'), '#000')
        elc = color(self.prop(c, 'ElementColor'), 'transparent')
        rad = float(self.prop(c, 'ElementCornerRadius', '0')) / self.density
        mar = float(self.prop(c, 'ElementMarginsWidth', '0')) / self.density
        iw = float(self.prop(c, 'ImageWidth', '200')) / self.density
        ih = float(self.prop(c, 'ImageHeight', '200')) / self.density
        pad = 15 / self.density
        items = []
        for i, r in enumerate(rows):
            if isinstance(r, dict):
                t1, t2, im = r.get('Text1', ''), r.get('Text2', ''), r.get('Image', '')
            else:
                t1, t2, im = str(r), '', ''
            body = '<div style="%scolor:%s;white-space:pre-wrap">%s</div>' % (font_css(ft, False, fs), col, html.escape(t1))
            if layout != '0' and t2 != '':
                body += '<div style="%scolor:%s;white-space:pre-wrap">%s</div>' % (font_css(ftd, False, fsd), cold, html.escape(t2))
            icon = ''
            if layout in ('3', '4') and im and self.asset_url(im):
                icon = '<img src="%s" style="width:%.2fpx;height:%.2fpx;flex:none;margin-right:%.2fpx;display:block">' % (self.asset_url(im), iw, ih, 15 / self.density)
            top = mar if i == 0 else 0
            items.append('<div style="display:flex;align-items:center;background:%s;border-radius:%.2fpx;padding:%.2fpx;margin:%.2fpx %.2fpx %.2fpx %.2fpx;">%s<div style="flex:1 1 0;min-width:0">%s</div></div>' % (
                elc, rad, pad, top, mar, mar, mar, icon, body))
        style = 'background:%s;' % bg + self.size_css(c, pv) + 'display:flex;flex-direction:column;overflow:hidden;'
        return '<div class="c" data-name="%s" style="%s">%s</div>' % (c['$Name'], style, ''.join(items))

    def r_Chart(self, c, pv):
        slices = self.state.get('%s.slices' % c['$Name'], [])
        legend = self.prop(c, 'LegendEnabled', 'True') != 'False'
        bg = color(self.prop(c, 'BackgroundColor'), 'transparent')
        lblcol = self.state.get('%s.labelcolor' % c['$Name'], '#000')
        hole = 100 - int(self.prop(c, 'PieRadius', '100'))
        total = sum(v for _, v, _ in slices) or 1
        paths = []
        ang = -math.pi / 2
        R = 100
        for label, v, col in slices:
            frac = v / total
            a2 = ang + 2 * math.pi * frac
            x1, y1 = R * math.cos(ang), R * math.sin(ang)
            x2, y2 = R * math.cos(a2), R * math.sin(a2)
            large = 1 if frac > 0.5 else 0
            if frac >= 0.9999:
                d = 'M0,%d A%d,%d 0 1 1 0,%d A%d,%d 0 1 1 0,%d Z' % (-R, R, R, R, R, R, -R)
            else:
                d = 'M0,0 L%.2f,%.2f A%d,%d 0 %d 1 %.2f,%.2f Z' % (x1, y1, R, R, large, x2, y2)
            mid = (ang + a2) / 2
            tx, ty = 0.62 * R * math.cos(mid), 0.62 * R * math.sin(mid)
            paths.append('<path d="%s" fill="%s" stroke="%s" stroke-width="1.4" stroke-linejoin="round"/>' % (d, col, bg if bg != 'transparent' else '#fff'))
            txt = ('{:,.0f}'.format(v)).replace(',', '.')
            paths.append('<text x="%.1f" y="%.1f" font-size="4.6" fill="%s" text-anchor="middle" dominant-baseline="middle" font-family="Roboto">%s</text>' % (tx, ty, lblcol, txt))
            ang = a2
        hole_svg = '<circle r="%d" fill="white"/>' % (R * hole / 100.0) if hole > 0 else ''
        leg = ''
        if legend:
            leg = '<div style="display:flex;justify-content:center;gap:12px;font:13px Roboto;color:#000;padding:4px 0 6px">%s</div>' % ''.join(
                '<span style="display:flex;align-items:center;gap:5px"><i style="display:inline-block;width:12px;height:12px;background:%s"></i>%s</span>' % (col, html.escape(lab)) for lab, _, col in slices)
        style = 'background:%s;display:flex;flex-direction:column;align-items:center;justify-content:center;' % bg + self.size_css(c, pv)
        svg = '<svg viewBox="-104 -104 208 208" style="flex:1 1 0;min-height:0;max-width:100%%;width:100%%">%s%s</svg>' % (''.join(paths), hole_svg)
        return '<div class="c" data-name="%s" style="%s">%s%s</div>' % (c['$Name'], style, svg if slices else '', leg)

    # ------------------------------------------------------------- pagina
    def asset_url(self, name):
        if not name:
            return None
        if name.startswith('file://'):               # v1.9: foto tirada com a camera (URL de arquivo)
            from urllib.parse import unquote
            return name if os.path.exists(unquote(name[len('file://'):])) else None
        if os.path.isabs(name):                      # foto escolhida pela pessoa (fora dos assets)
            return 'file://' + name if os.path.exists(name) else None
        p = os.path.join(self.assets, name)
        if os.path.exists(p):
            return 'file://' + os.path.abspath(p)
        return None

    def page(self):
        f = self.form
        load_font_metrics(self.assets)
        bgc = color(self.state.get('Screen1.BackgroundColor', f.get('BackgroundColor')), '#fff')
        status_col = color(f.get('PrimaryColorDark'), '#004d40')
        prim = color(f.get('PrimaryColor'), '#00796b')
        title_visible = f.get('TitleVisible', 'True') != 'False'
        face = ''
        fonts = []
        for fn in sorted(os.listdir(self.assets)) if os.path.isdir(self.assets) else []:
            if fn.lower().endswith(('.ttf', '.otf')):
                fonts.append("@font-face{font-family:'F_%s';src:url('file://%s');}" % (re.sub(r'\W', '_', fn), os.path.abspath(os.path.join(self.assets, fn))))
        top = STATUS_DP + (TITLE_DP if title_visible else 0)
        viewport_h = H_DP - top - NAV_DP
        ah = f.get('AlignHorizontal', '1')
        hmap = {'1': 'flex-start', '2': 'flex-end', '3': 'center'}
        content = self.render_children(f, True)
        form_style = 'display:flex;flex-direction:column;align-items:%s;width:%dpx;min-height:%dpx;background:%s;' % (hmap.get(ah, 'flex-start'), W_DP, viewport_h, bgc)
        title_html = ''
        if title_visible:
            title_html = ('<div style="height:%dpx;background:%s;color:#fff;font:500 20px Roboto;display:flex;align-items:center;padding:0 16px;justify-content:space-between;box-shadow:0 2px 4px rgba(0,0,0,.3);position:relative;z-index:2">'
                          '<span>%s</span><span style="font-size:22px">&#8942;</span></div>') % (TITLE_DP, prim, html.escape(f.get('Title', '')))
        doc = """<!doctype html><html><head><meta charset="utf-8"><style>
%s
html,body{margin:0;padding:0;background:#222;}
*{box-sizing:border-box}
.phone{width:%dpx;height:%dpx;position:relative;overflow:hidden;font-family:Roboto,'Noto Sans',sans-serif;background:%s}
.status{height:%dpx;background:%s;color:#fff;font:500 15px Roboto;display:flex;align-items:center;padding:0 18px;gap:6px}
.scroll{height:%dpx;overflow:hidden}
.navbar{height:%dpx;background:#000;display:flex;align-items:center;justify-content:center}
.navbar i{display:block;width:124px;height:4px;border-radius:2px;background:#ddd}
img.c{display:block}
</style></head><body><div class="phone">
<div class="status"><span>22:25</span></div>%s
<div class="scroll"><div id="form" style="%s">%s</div></div>
<div class="navbar"><i></i></div></div></body></html>""" % (
            '\n'.join(fonts), W_DP, H_DP, bgc, STATUS_DP, status_col, viewport_h, NAV_DP, title_html, form_style, content)
        return doc


MEDIR_BOTOES_JS = """() => { const o = {};
  document.querySelectorAll('[data-btn]').forEach(e => {
    const cx = e.querySelector('.cx'), tx = e.querySelector('.tx');
    const re = e.getBoundingClientRect(), rc = cx.getBoundingClientRect(), rt = tx.getBoundingClientRect();
    if (re.width === 0 && re.height === 0) return;
    const st = getComputedStyle(tx), lh = parseFloat(st.lineHeight);
    const pad = parseFloat(st.paddingTop) + parseFloat(st.paddingBottom);
    o[e.dataset.name] = {botao: [re.width, re.height], caixa: [rc.width, rc.height], texto: [tx.scrollWidth, rt.height],
                         texto_txt: tx.textContent, linhas: tx.textContent ? Math.round((rt.height - pad) / lh) : 0,
                         moldura: !!e.querySelector('.moldura'), fonte_px: parseFloat(st.fontSize)};
  });
  return o; }"""


def render(scm_path, assets_dir, out_png, tab=1, state=None, density=2.75, report_rects=False, full_height=False,
           largura_dp=None, escala_fonte=1.0, report_botoes=False):
    """report_botoes=True devolve (rects, botoes): para cada botao visivel, o tamanho da caixa de texto (dentro da
    margem interna do Android), o tamanho do texto ja quebrado em linhas e se ha a moldura do tema (quadrado vazio).
    largura_dp / escala_fonte: outra largura de tela e outro tamanho de fonte do sistema (padrao: 393 dp e 1,0)."""
    global W_DP, FONT_SCALE
    w0, f0 = W_DP, FONT_SCALE
    W_DP, FONT_SCALE = (largura_dp or w0), escala_fonte
    try:
        return _render(scm_path, assets_dir, out_png, tab, state, density, report_rects, full_height, report_botoes)
    finally:
        W_DP, FONT_SCALE = w0, f0


def _desenhar(b, scm_path, assets_dir, out_png, tab, state, density, report_rects, full_height, report_botoes):
    """Uma cena num navegador ja aberto (b). W_DP/FONT_SCALE ja estao valendo."""
    txt = open(scm_path, encoding='utf-8').read()
    scm = json.loads(txt[txt.index('{'):txt.rindex('}') + 1])
    r = Renderer(scm, assets_dir, state, tab, density)
    doc = r.page()
    html_path = out_png + '.html'
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(doc)
    rects = {}
    pg = b.new_page(viewport={'width': W_DP, 'height': H_DP}, device_scale_factor=density)
    try:
        pg.goto('file://' + os.path.abspath(html_path))
        pg.wait_for_timeout(250)
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(250)
        botoes = pg.evaluate(MEDIR_BOTOES_JS) if report_botoes else None
        if report_rects:
            rects = pg.evaluate("""() => { const o = {}; document.querySelectorAll('[data-name]').forEach(e => { const r = e.getBoundingClientRect(); o[e.dataset.name] = [r.left, r.top, r.width, r.height]; }); return o; }""")
        if full_height:
            h = pg.evaluate("document.getElementById('form').getBoundingClientRect().height")
            pg.set_viewport_size({'width': W_DP, 'height': int(h + 80)})
            pg.evaluate("document.querySelector('.scroll').style.height='auto'; document.querySelector('.phone').style.height='auto'")
        pg.screenshot(path=out_png, full_page=False)
    finally:
        pg.close()
    return (rects, botoes) if report_botoes else rects


def _render(scm_path, assets_dir, out_png, tab, state, density, report_rects, full_height, report_botoes):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            return _desenhar(b, scm_path, assets_dir, out_png, tab, state, density, report_rects, full_height, report_botoes)
        finally:
            b.close()


def render_varios(trabalhos):
    """v1.8.1: varias cenas com UM navegador (bem mais rapido). Cada trabalho e um dict com os argumentos de render()
    (scm_path, assets_dir, out_png, tab, state, density, report_rects, full_height, largura_dp, escala_fonte,
    report_botoes). Devolve a lista de resultados, na mesma ordem."""
    from playwright.sync_api import sync_playwright
    global W_DP, FONT_SCALE
    w0, f0 = W_DP, FONT_SCALE
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            for t in trabalhos:
                W_DP, FONT_SCALE = (t.get('largura_dp') or w0), t.get('escala_fonte', 1.0)
                out.append(_desenhar(b, t['scm_path'], t['assets_dir'], t['out_png'], t.get('tab', 1), t.get('state'),
                                     t.get('density', 2.75), t.get('report_rects', False), t.get('full_height', False),
                                     t.get('report_botoes', False)))
        finally:
            W_DP, FONT_SCALE = w0, f0
            b.close()
    return out


if __name__ == '__main__':
    import sys
    render(sys.argv[1], sys.argv[2], sys.argv[3], tab=int(sys.argv[4]) if len(sys.argv) > 4 else 1)
