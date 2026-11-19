#!/usr/bin/env python3
"""Fonte unica do tema do Conto v1.4: paleta, nomes de arquivos de imagem e medidas (em dp).

gen_assets.py (imagens) e gen_scm.py (tela) importam daqui, para que cor/medida nunca divirjam.
"""


def hexrgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def aia(h, a=255):
    """'#RRGGBB' -> '&HAARRGGBB' (formato de cor do App Inventor)."""
    r, g, b = hexrgb(h)
    return '&H%02X%02X%02X%02X' % (a, r, g, b)


def lum(h):
    def ch(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = hexrgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contraste(a, b):
    la, lb = lum(a), lum(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


# ------------------------------------------------------------------ paleta
BG = '#F1F5F3'            # fundo da tela
CARD = '#FFFFFF'
INK = '#10201C'           # texto principal
MUTED = '#566862'         # texto secundario / legendas
HINT = '#687A73'          # dica dos campos (contraste 4,55:1 sobre branco, nivel AA)
BORDER = '#CBD8D3'        # contorno dos campos
EMERALD = '#0E7C66'       # cor da marca
EMERALD_DARK = '#06302B'  # barra de status + topo do cabecalho
EMERALD_MID = '#0B6A57'   # base do cabecalho
GREEN = '#1FA06A'         # entradas (grafico, icones)
GREEN_D = '#168656'       # botao + Entrada
RED = '#E5484D'           # despesas (grafico, icones)
RED_D = '#D13D43'         # botao - Despesa
GOLD = '#F6B93B'          # moeda da marca
HDR_LIGHT = '#B5DDD2'     # textos claros sobre o cabecalho
HDR_CAP = '#EAF7F2'          # legenda dos chips (medido nas previas: >= 4,5:1 inclusive sobre o disco claro)
DANGER_TXT = '#B3303A'
DANGER_BG = '#FDEEEE'
DANGER_BORDER = '#F2C4C7'
SELECTION = '#DDEFE8'     # linha tocada no historico

# ------------------------------------------------------------------ fontes (arquivos em assets/)
F_MED = 'Manrope-Medium.ttf'
F_SEMI = 'Manrope-SemiBold.ttf'
F_BOLD = 'Manrope-Bold.ttf'
F_XBOLD = 'Manrope-ExtraBold.ttf'
FONT_SRC = {   # arquivo no pacote -> arquivo baixado
    F_MED: '500Medium/Manrope_500Medium.ttf',
    F_SEMI: '600SemiBold/Manrope_600SemiBold.ttf',
    F_BOLD: '700Bold/Manrope_700Bold.ttf',
    F_XBOLD: '800ExtraBold/Manrope_800ExtraBold.ttf',
}
FONT_LICENSE = 'Manrope-OFL.txt'

# ------------------------------------------------------------------ imagens (nomes em assets/)
IMG_TOPO = 'fundo_topo.png'
IMG_CHIP = 'chip.png'
IMG_LOGO = 'logo.png'
IMG_ICONE = 'icone.png'
IMG_SETA_ENT = 'seta_entrada.png'
IMG_SETA_DESP = 'seta_despesa.png'
IMG_CAMPO = 'campo.png'
IMG_CAMPO_SEL = 'campo_select.png'
IMG_CARTAO_LANCAR = 'cartao_lancar.png'
IMG_CARTAO_GRAF = 'cartao_grafico.png'
IMG_ABAS = 'abas_fundo.png'
IMG_ABA_ON = 'aba_ativa.png'
# v1.8.1: altura das pilulas (abas, Mes/Ano/Tudo, Claro/Escuro, Escolher foto). O Android tira 10 dp em cima e 10 dp
# embaixo de TODO botao (margem interna do tema, que o App Inventor nao zera): com 40 dp sobravam 20 dp para o texto,
# menos que uma linha da Manrope Bold de 14 sp (21,1 dp) -- o texto saia cortado no pe.
PILULA_H = 44
FONTE_ABA_NAV = 12      # v1.8.1: era 13; 'Histórico'/'Evolução' quebravam em 2 linhas numa tela de 360 dp
IMG_ABA_OFF = 'aba_inativa.png'
IMG_BTN_ENT = 'btn_entrada.png'
IMG_BTN_DESP = 'btn_despesa.png'
IMG_BTN_PERIGO = 'btn_perigo.png'
IMG_PONTO_VERDE = 'ponto_verde.png'
IMG_PONTO_VERM = 'ponto_vermelho.png'
IMG_CAMPO_ERRO = 'campo_erro.png'
IMG_CAMPO_SEL_ERRO = 'campo_select_erro.png'
IMG_AVISO_OK = 'aviso_ok.png'
IMG_AVISO_ERRO = 'aviso_erro.png'
IMG_IC_VAZIO = 'ic_vazio.png'
# (nome exibido, arquivo do icone, emoji, cor do fundo do ladrilho)
CATEGORIAS = [
    ('Alimentação', 'ic_cat_alimentacao.png', '\U0001F354', '#FDEBD3'),
    ('Transporte', 'ic_cat_transporte.png', '\U0001F697', '#DCEBFB'),
    ('Moradia', 'ic_cat_moradia.png', '\U0001F3E0', '#E6F1DC'),
    ('Saúde', 'ic_cat_saude.png', '\U0001F48A', '#FBDFE3'),
    ('Lazer', 'ic_cat_lazer.png', '\U0001F3AE', '#E8E0F8'),
    ('Compras', 'ic_cat_compras.png', '\U0001F6CD\uFE0F', '#FCE3F0'),
    ('Educação', 'ic_cat_educacao.png', '\U0001F393', '#DDE7F7'),
    ('Outros', 'ic_cat_outros.png', '\U0001F4E6', '#EADFD2'),
]
PAGAMENTOS = [
    ('Dinheiro', 'ic_pag_dinheiro.png', '\U0001F4B5', '#DDF1E3'),
    ('Pix', 'ic_pag_pix.png', '\U0001F4A0', '#D9F1F0'),
    ('Cartão de crédito', 'ic_pag_credito.png', '\U0001F4B3', '#FBE6D2'),
    ('Cartão de débito', 'ic_pag_debito.png', '\U0001F4B3', '#DCE8FA'),
    ('Transferência bancária', 'ic_pag_transferencia.png', '\U0001F3E6', '#E7E4F6'),
]
AVISO_OK_BG = '#E3F5EC'
AVISO_OK_BORDER = '#BDE5D0'
AVISO_OK_TXT = '#0B5F3D'

# ------------------------------------------------------------------ v1.6: tema escuro, perfil e grafico por categoria
TRILHO = '#E3EBE7'        # fundo das barras do grafico por categoria (tema claro)
D_BG = '#0D1513'          # fundo da tela (escuro)
D_CARD = '#17221F'        # cartoes
D_CARD_BORDER = '#2A3B36'
D_INK = '#E8F1ED'         # texto principal
D_MUTED = '#A9BAB3'       # texto secundario
D_HINT = '#93A69F'        # dica dos campos
D_FIELD = '#1C2925'       # preenchimento dos campos
D_BORDER = '#3F534C'      # contorno dos campos
D_EMERALD = '#5AD6B4'     # cor da marca usada como TEXTO sobre fundo escuro
D_DANGER_TXT = '#FF9DA1'
D_DANGER_BG = '#3A1E21'
D_DANGER_BORDER = '#6B3237'
D_RED_BORDER = '#FF6B70'  # borda do campo com erro
D_SELECTION = '#243631'
D_AVISO_OK_BG = '#12372C'
D_AVISO_OK_BORDER = '#1F5C49'
D_AVISO_OK_TXT = '#8FE5C2'
D_TRILHO = '#2A3834'
D_VAZIO_BG = '#25332F'    # ladrilho neutro do icone "ainda nao escolhido"
D_VAZIO_FG = '#A9BAB3'

# v1.7: comparacoes e orcamento
BOM_TXT = '#137A4D'       # 5,4:1 sobre branco
D_BOM_TXT = '#6EDDA5'
BARRA_OK = '#178A5A'
D_BARRA_OK = '#2FBF7F'
BARRA_ALERTA = '#B87400'
D_BARRA_ALERTA = '#F0B23E'
ALERTA_TXT = '#8A5A00'    # 5,9:1 sobre branco
D_ALERTA_TXT = '#F6C567'

MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
MESES_CURTOS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
INICIAIS = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D']

# fichas de cor: nome -> (claro, escuro). Os blocos guardam o valor atual em globais "cor<Nome>".
CORES = {
    'Texto': (INK, D_INK),
    'Suave': (MUTED, D_MUTED),
    'Dica': (HINT, D_HINT),
    'Marca': (EMERALD, D_EMERALD),
    'Perigo': (DANGER_TXT, D_DANGER_TXT),
    'AvisoOk': (AVISO_OK_TXT, D_AVISO_OK_TXT),
    'Fundo': (BG, D_BG),
    'Cartao': (CARD, D_CARD),
    'Selecao': (SELECTION, D_SELECTION),
    'Trilho': (TRILHO, D_TRILHO),
    # v1.7
    'Bom': (BOM_TXT, D_BOM_TXT),                 # texto de comparacao favoravel (gastou menos, ganhou mais)
    'BarraOk': (BARRA_OK, D_BARRA_OK),           # orcamento: ate 80% do limite
    'BarraAlerta': (BARRA_ALERTA, D_BARRA_ALERTA),   # orcamento: 80% a 100%
    'BarraEstouro': (RED, RED),                  # orcamento: passou do limite
    'Alerta': (ALERTA_TXT, D_ALERTA_TXT),        # texto "perto do limite"
    # v1.8
    'BarraMeta': (EMERALD, D_EMERALD),           # progresso da meta
}


def escuro(arq):
    """Nome do arquivo da variante escura de uma imagem: 'campo.png' -> 'campo_d.png'."""
    return arq[:-4] + '_d.png'


IMG_AVATAR = 'avatar_padrao.png'          # avatar sem foto (cartao do perfil)
IMG_MASCARA = 'mascara_cartao.png'        # moldura com furo redondo, na cor do cartao (recorta a foto em circulo)
IMG_AVATAR_TOPO = 'avatar_topo.png'       # avatar sem foto (cabecalho)
IMG_MASCARA_TOPO = 'mascara_topo.png'     # moldura do avatar do cabecalho
IMG_TEMA_LUA = 'ic_lua.png'               # botao do cabecalho no tema claro (toque = escurecer)
IMG_TEMA_SOL = 'ic_sol.png'               # botao do cabecalho no tema escuro (toque = clarear)
IMG_CAMPO_CURTO = 'campo_curto.png'       # v1.7: campo estreito (limites por categoria)
IMG_CAMPO_CURTO_ERRO = 'campo_curto_erro.png'
IMG_BUSCA = 'ic_busca.png'                # v1.7: lupa do campo de busca
IMG_CHECK_OFF = 'ic_check_off.png'        # v1.7: caixa "Repetir todo mes" desmarcada
IMG_CHECK_ON = 'ic_check_on.png'
# v1.8: icones das linhas de "Seus dados", calendario do campo de data, alvo da meta, seta de linha e cartao pequeno
IC18 = ['limites', 'importar', 'planilha', 'backup', 'restaurar', 'calendario', 'alvo', 'seta', 'sino']   # sino: v2.0
IMG_IC18 = {n: 'ic_%s.png' % n for n in IC18}
IMG_CARTAO_MINI = 'cartao_mini.png'

# fichas de imagem: nome -> (claro, escuro). Os blocos guardam o nome atual em globais "img<Nome>".
IMAGENS = {
    'CartaoLancar': (IMG_CARTAO_LANCAR, escuro(IMG_CARTAO_LANCAR)),
    'CartaoGraf': (IMG_CARTAO_GRAF, escuro(IMG_CARTAO_GRAF)),
    'Campo': (IMG_CAMPO, escuro(IMG_CAMPO)),
    'CampoSel': (IMG_CAMPO_SEL, escuro(IMG_CAMPO_SEL)),
    'CampoErro': (IMG_CAMPO_ERRO, escuro(IMG_CAMPO_ERRO)),
    'CampoSelErro': (IMG_CAMPO_SEL_ERRO, escuro(IMG_CAMPO_SEL_ERRO)),
    'Abas': (IMG_ABAS, escuro(IMG_ABAS)),
    'AvisoOk': (IMG_AVISO_OK, escuro(IMG_AVISO_OK)),
    'AvisoErro': (IMG_AVISO_ERRO, escuro(IMG_AVISO_ERRO)),
    'Vazio': (IMG_IC_VAZIO, escuro(IMG_IC_VAZIO)),
    'Perigo': (IMG_BTN_PERIGO, escuro(IMG_BTN_PERIGO)),
    'Avatar': (IMG_AVATAR, escuro(IMG_AVATAR)),
    'Mascara': (IMG_MASCARA, escuro(IMG_MASCARA)),
    'TemaIcone': (IMG_TEMA_LUA, IMG_TEMA_SOL),
    # v1.7
    'CampoCurto': (IMG_CAMPO_CURTO, escuro(IMG_CAMPO_CURTO)),
    'CampoCurtoErro': (IMG_CAMPO_CURTO_ERRO, escuro(IMG_CAMPO_CURTO_ERRO)),
    'Busca': (IMG_BUSCA, escuro(IMG_BUSCA)),
    'CheckOff': (IMG_CHECK_OFF, escuro(IMG_CHECK_OFF)),
    'CheckOn': (IMG_CHECK_ON, escuro(IMG_CHECK_ON)),
    # v1.8
    'CartaoMini': (IMG_CARTAO_MINI, escuro(IMG_CARTAO_MINI)),
}
IMAGENS.update({'Ic' + n[0].upper() + n[1:]: (IMG_IC18[n], escuro(IMG_IC18[n])) for n in IC18})

# v1.8.1: no Android, um botao SEM imagem com fundo "nenhum" ganha a moldura/sombra do tema Material e uma margem
# interna de ~12 dp dos lados e ~10 dp em cima/embaixo (ButtonBase.java + estilo de botao do Android). Nos botoes
# pequenos isso apaga o texto (setas, "x" e iniciais dos meses apareciam como quadrados vazios ou cortados no
# aparelho). Esses botoes passam a ser IMAGEM (a figura ocupa o botao inteiro, sem margem) e os de texto ganham
# forma "arredondada" (o App Inventor tira a sombra quando a forma nao e a padrao e o fundo e "nenhum").
IMG_SETA_ESQ = 'seta_esq.png'
IMG_SETA_DIR = 'seta_dir.png'
IMG_FECHAR = 'ic_fechar.png'
SETA_W, SETA_H = 52, 40          # todos os botoes de seta tem este tamanho (dp): a figura nunca distorce
FECHAR_LADO = 44                 # botao "x" da busca (dp)
MES_LADO = 28                    # botao da inicial do mes no "Mes a mes" (dp)
LETRAS_MES = ['j', 'f', 'm', 'a', 'm', 'j', 'j', 'a', 's', 'o', 'n', 'd']
ESTADOS_MES = {'a': 'Marca', 'f': 'Dica', 'n': 'Suave'}     # mes atual / mes que ainda vem / os outros


def img_mes(letra, estado, esc=False):
    """Arquivo da inicial do mes: 'mes_j_n.png' (claro) / 'mes_j_n_d.png' (escuro)."""
    return 'mes_%s_%s%s.png' % (letra, estado, '_d' if esc else '')


IMAGENS.update({
    'SetaEsq': (IMG_SETA_ESQ, escuro(IMG_SETA_ESQ)),
    'SetaDir': (IMG_SETA_DIR, escuro(IMG_SETA_DIR)),
    'Fechar': (IMG_FECHAR, escuro(IMG_FECHAR)),
    'Nada': (IMG_ABA_OFF, IMG_ABA_OFF),      # imagem transparente: a seta "some" mas o botao continua no lugar
})

AVATAR = 96            # lado (dp) do avatar no cartao do perfil
AVATAR_TOPO = 40       # lado (dp) do avatar no cabecalho
MASCARA_FOLGA = 2      # quanto (dp) a moldura redonda passa do avatar de cada lado
BARRA_MAX = 72         # largura maxima da barra de categoria, em % da largura da tela

# ------------------------------------------------------------------ medidas (dp) usadas pelas imagens
W_TELA = 393
SIZES = {
    'header_h': 210,        # altura do cabecalho (medida no renderizador e ajustada; v1.6: linha do avatar)
    'avatar_fx': 0.899, 'avatar_fy': 0.133,   # centro do avatar do cabecalho em fracao do cabecalho (medido na previa)
    'chip_w': 173, 'chip_h': 54,
    'campo_w': 338, 'campo_h': 48,
    'cartao_lancar_h': 482,
    'cartao_grafico_h': 400,
    'abas_w': 361, 'abas_h': 52,      # v1.8.1: era 48 (pilulas de 40 -> 44 dp)
    'btn_w': 164, 'btn_h': 52,
    'perigo_w': 361, 'perigo_h': 48,
    'aviso_w': 361, 'aviso_h': 56,
    'campo_curto_w': 150,   # v1.7: campo dos limites por categoria
    'mini_h': 76,           # v1.8: cartao pequeno da meta (aba Lancar)
}

# ------------------------------------------------------------------ v1.9: rosca "Gastos por categoria"
# Uma cor FIXA por categoria (na ordem de CATEGORIAS), nos dois temas: a fatia da rosca e a bolinha da linha da
# categoria. Todas com contraste >= 3:1 sobre o cartao (claro: branco; escuro: D_CARD) e bem diferentes entre si.
CORES_CAT = [
    ('#D9730D', '#F2A65A'),   # Alimentacao: laranja
    ('#2F6FDB', '#7AA7F5'),   # Transporte: azul
    ('#2E8B57', '#6CCB8F'),   # Moradia: verde
    ('#D64550', '#FF8A92'),   # Saude: vermelho
    ('#7C4DDB', '#B49BFF'),   # Lazer: roxo
    ('#C2408A', '#F48FC4'),   # Compras: rosa
    ('#0F8A9C', '#4FC6D6'),   # Educacao: azul-petroleo
    ('#8D6E58', '#C9A88E'),   # Outros: marrom
]
N_CORES_CAT = len(CORES_CAT)
# Fora de CORES/IMAGENS de proposito: cada nome registrado ali vira um 'set' em cada ramo do definirTema, que
# passaria de 441 blocos (o maior procedimento ja comprovado compilando). As listas ficam em globais do app
# (coresCatClaro/Escuro, pontosCatClaro/Escuro) e a rosca escolhe pelo tema na hora de montar.


def img_ponto_cat(i, esc=False):
    """Bolinha na cor da categoria i (1..8): 'ponto_cat3.png' / 'ponto_cat3_d.png'."""
    return 'ponto_cat%d%s.png' % (i, '_d' if esc else '')


ROSCA_LADO = 132      # Canvas da rosca (dp)
ROSCA_ANEL = 26       # espessura do anel (dp): furo de 40 dp de raio em 66 (61%)
PONTO_CAT = 10        # bolinha da categoria (dp)
# v1.9: botao secundario em pilula com contorno ("Escolher da galeria", ao lado de "Tirar foto")
IMG_PILULA_SEC = 'pilula_contorno.png'
PILULA_SEC_W = 226    # largura de desenho (dp): a coluna ao lado do avatar tem ~200-240 dp
IMAGENS['PilulaSec'] = (IMG_PILULA_SEC, escuro(IMG_PILULA_SEC))

if __name__ == '__main__':
    pares = [('INK', 'CARD'), ('MUTED', 'CARD'), ('HINT', 'CARD'), ('EMERALD', 'CARD'),
             ('CARD', 'GREEN_D'), ('CARD', 'RED_D'), ('CARD', 'GREEN'), ('CARD', 'RED'),
             ('CARD', 'EMERALD'), ('HDR_LIGHT', 'EMERALD_MID'), ('HDR_CAP', 'EMERALD_MID'),
             ('DANGER_TXT', 'DANGER_BG'), ('INK', 'BG'), ('MUTED', 'BG')]
    g = globals()
    for a, b in pares:
        print('%-10s sobre %-12s contraste %.2f' % (a, b, contraste(g[a], g[b])))
    print('--- tema escuro')
    for a, b in [('D_INK', 'D_CARD'), ('D_MUTED', 'D_CARD'), ('D_HINT', 'D_FIELD'), ('D_EMERALD', 'D_CARD'), ('D_INK', 'D_BG'),
                 ('D_MUTED', 'D_BG'), ('D_DANGER_TXT', 'D_CARD'), ('D_DANGER_TXT', 'D_DANGER_BG'), ('D_AVISO_OK_TXT', 'D_AVISO_OK_BG'),
                 ('D_INK', 'D_FIELD'), ('D_MUTED', 'D_FIELD'), ('GREEN', 'D_CARD'), ('RED', 'D_CARD'), ('RED', 'D_TRILHO'), ('RED', 'TRILHO'),
                 ('D_BORDER', 'D_CARD'), ('D_VAZIO_FG', 'D_VAZIO_BG'), ('D_EMERALD', 'D_FIELD'), ('D_INK', 'D_SELECTION'),
                 ('BOM_TXT', 'CARD'), ('D_BOM_TXT', 'D_CARD'), ('ALERTA_TXT', 'CARD'), ('D_ALERTA_TXT', 'D_CARD'),
                 ('BARRA_OK', 'TRILHO'), ('BARRA_ALERTA', 'TRILHO'), ('D_BARRA_OK', 'D_TRILHO'), ('D_BARRA_ALERTA', 'D_TRILHO')]:
        print('%-14s sobre %-14s contraste %.2f' % (a, b, contraste(g[a], g[b])))
