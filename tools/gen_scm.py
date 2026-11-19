#!/usr/bin/env python3
"""Gera o Screen1.scm (arvore de componentes) do Conto v1.8.

Uso (como modulo):  scm_text() -> str      |  python3 gen_scm.py saida.scm

Regras que sigo (conferidas no codigo-fonte do App Inventor):
  - $Version de cada tipo = a mesma do arquivo original v1.2 (o servidor atualiza sozinho, se precisar);
    tipos novos usam a versao da YaVersion 237: Image 8, Canvas 15, ImageSprite 11, ImagePicker 6.
  - nomes de propriedade sao os atuais (ListView.FontSize, e nao o antigo TextSize).
  - larguras: -2 = preencher, N = dp, -(1000+P) = P% da largura da TELA.
  - nenhum componente que os blocos usam foi renomeado ou removido.

v1.6 - TEMA: toda propriedade que muda entre o tema claro e o escuro e declarada com uma FICHA
(cor('Texto'), img('Campo')...). O .scm recebe o valor do tema claro e a ficha fica registrada em TEMA_REG;
gen_conto.py gera, a partir desse registro, os blocos que repintam cada componente ao trocar de tema.
"""
import itertools
import json
import sys

import tema as T

_uuid = itertools.count(1000003, 7919)

VERSIONS = {
    'Form': 32, 'Label': 6, 'Button': 8, 'TextBox': 15, 'Spinner': 1, 'ListView': 11,
    'HorizontalArrangement': 4, 'VerticalArrangement': 4, 'Chart': 4, 'ChartData2D': 2,
    'Notifier': 7, 'TinyDB': 3, 'Clock': 4, 'Image': 8,
    'Canvas': 15, 'ImageSprite': 11, 'ImagePicker': 6, 'Camera': 3,
    'File': 4, 'Sharing': 2, 'FilePicker': 1,          # v1.7 (YaVersion 237)
    'DatePicker': 5,                                    # v1.8 (YaVersion.DATEPICKER_COMPONENT_VERSION)
    'LeitorNotificacoes': 1,                            # v2.0: extensao com.conto.notificacoes (versao do proprio .aix)
}

TEMA_REG = []      # (nome do componente, tipo, propriedade, Ficha) na ordem da arvore


class Ficha(object):
    """Valor que depende do tema. tipo = 'cor' (T.CORES) ou 'img' (T.IMAGENS)."""

    def __init__(self, tipo, nome):
        assert nome in (T.CORES if tipo == 'cor' else T.IMAGENS), nome
        self.tipo, self.nome = tipo, nome

    def claro(self):
        return T.aia(T.CORES[self.nome][0]) if self.tipo == 'cor' else T.IMAGENS[self.nome][0]

    def escuro(self):
        return T.aia(T.CORES[self.nome][1]) if self.tipo == 'cor' else T.IMAGENS[self.nome][1]


def cor(nome):
    return Ficha('cor', nome)


def img(nome):
    return Ficha('img', nome)


def comp(tipo, nome, props=None, filhos=None):
    d = {'$Name': nome, '$Type': tipo, '$Version': str(VERSIONS[tipo])}
    for k, v in (props or {}).items():
        if isinstance(v, Ficha):
            TEMA_REG.append((nome, tipo, k, v))
            v = v.claro()
        d[k] = str(v)
    d['Uuid'] = str(next(_uuid))
    if filhos:
        d['$Components'] = filhos
    return d


def pct(p):
    return -(1000 + p)


def _cor(c):
    return c if isinstance(c, Ficha) else T.aia(c)


# ----------------------------------------------------------------- pecas
def esp_v(nome, h):
    """Espacador vertical: rotulo vazio com altura fixa."""
    return comp('Label', nome, {'Text': '', 'Height': h, 'Width': -2, 'HasMargins': 'False', 'FontSize': 4})


def esp_h(nome, w):
    """Espacador horizontal: rotulo vazio com largura fixa (1 dp de altura para nao empurrar a linha)."""
    return comp('Label', nome, {'Text': '', 'Width': w, 'Height': 1, 'HasMargins': 'False', 'FontSize': 4})


def rotulo(nome, texto, fonte, tam, cor_, largura=-2, alinh=0, extra=None):
    p = {'Text': texto, 'FontSize': tam, 'FontTypeface': fonte, 'TextColor': _cor(cor_),
         'Width': largura, 'TextAlignment': alinh, 'HasMargins': 'False'}
    p.update(extra or {})
    return comp('Label', nome, p)


def botao(nome, texto, imagem, cor_texto, tam, h, largura=-2, fonte=T.F_BOLD, tipo='Button'):
    return comp(tipo, nome, {'Text': texto, 'Image': imagem, 'FontSize': tam, 'FontTypeface': fonte,
                             'TextColor': _cor(cor_texto), 'Width': largura, 'Height': h})


def botao_texto(nome, texto, cor_texto, h, tam=14, alinh=1, extra=None):
    """Botao so de texto (fundo 'nenhum'). v1.8.1: altura -1 (automatica) = o Android mede o texto + a margem interna
    (minimo 48 dp): nunca corta o texto, nem com a fonte do sistema maior."""
    p = {'Text': texto, 'Width': -2, 'Height': h, 'FontSize': tam, 'FontTypeface': T.F_BOLD,
         'TextColor': _cor(cor_texto), 'TextAlignment': alinh, 'BackgroundColor': '&H00FFFFFF'}
    p.update(extra or {})
    return comp('Button', nome, p)


def campo_texto(nome, hint, imagem_campo, nome_hz, prefixo=None, nome_pref=None):
    """Caixa de texto sobre um 'campo' arredondado (imagem). A TextBox fica transparente (cor 'nenhum')."""
    f = [esp_h('Esp' + nome_hz + 'A', 10)]
    if prefixo:
        f.append(rotulo(nome_pref, prefixo, T.F_BOLD, 15, cor('Marca'), largura=-1))
        f.append(esp_h('Esp' + nome_hz + 'B', 6))
    f.append(comp('TextBox', nome, {
        'Hint': hint, 'Width': -2, 'Height': 48, 'FontSize': 15, 'FontTypeface': T.F_MED,
        'BackgroundColor': '&H00FFFFFF', 'TextColor': cor('Texto'), 'HintColor': cor('Dica'),
        'NumbersOnly': 'False'}))
    return comp('HorizontalArrangement', nome_hz, {'Width': -2, 'Height': T.SIZES['campo_h'], 'AlignVertical': 2,
                                                  'Image': imagem_campo}, f)


def campo_lista(btn, imagem, texto, nome_hz):
    """Campo de escolha: icone da opcao + texto (botao transparente) sobre o 'campo' com seta. Toque abre a lista com icones."""
    return comp('HorizontalArrangement', nome_hz, {'Width': -2, 'Height': T.SIZES['campo_h'], 'AlignVertical': 2,
                                                  'Image': T.IMG_CAMPO_SEL}, [
        esp_h('Esp' + nome_hz + 'A', 9),
        comp('Image', imagem, {'Picture': T.IMG_IC_VAZIO, 'Width': 32, 'Height': 32, 'Clickable': 'True'}),
        esp_h('Esp' + nome_hz + 'B', 4),
        comp('Button', btn, {'Text': texto, 'Width': -2, 'Height': 48, 'FontSize': 14, 'FontTypeface': T.F_MED,
                             'TextColor': T.aia(T.HINT), 'TextAlignment': 0, 'BackgroundColor': '&H00FFFFFF'}),
        esp_h('Esp' + nome_hz + 'C', 38),
    ])


def erro_campo(nome):
    return rotulo(nome, '', T.F_MED, 12, cor('Perigo'), extra={'Visible': 'False'})


def chip(prefixo, legenda, valor_nome, seta):
    """Pastilha translucida do cabecalho: icone + legenda + valor."""
    return comp('HorizontalArrangement', 'Chip' + prefixo, {'Width': pct(44), 'AlignVertical': 2, 'Image': T.IMG_CHIP}, [
        esp_h('Esp' + prefixo + '1', 11),
        comp('Image', 'Img' + prefixo, {'Picture': seta, 'Width': 30, 'Height': 30}),
        esp_h('Esp' + prefixo + '2', 9),
        comp('VerticalArrangement', 'Col' + prefixo, {'Width': -2}, [
            esp_v('Esp' + prefixo + '3', 7),
            rotulo('LblCap' + prefixo, legenda, T.F_MED, 11.5, T.HDR_CAP),
            rotulo(valor_nome, 'R$ 0,00', T.F_XBOLD, 15, '#FFFFFF'),
            esp_v('Esp' + prefixo + '4', 7),
        ]),
    ])


def bloco_resumo(pref, titulo, ponto):
    """Secao 'recentes' do grafico: titulo com ponto colorido + duas colunas (descricao | valor), ate 3 linhas."""
    return comp('VerticalArrangement', 'PnlRes' + pref, {'Width': -2, 'Visible': 'False'}, [
        comp('HorizontalArrangement', 'HzRes' + pref + 'Tit', {'Width': -2, 'AlignVertical': 2}, [
            comp('Image', 'ImgRes' + pref, {'Picture': ponto, 'Width': 10, 'Height': 10}),
            esp_h('EspRes' + pref + 'A', 8),
            rotulo('LblRes' + pref + 'Tit', titulo, T.F_SEMI, 13, cor('Suave')),
        ]),
        esp_v('EspRes' + pref + 'B', 4),
        comp('HorizontalArrangement', 'HzRes' + pref, {'Width': -2}, [
            rotulo('LblRes' + pref + 'Nomes', '', T.F_MED, 14, cor('Texto')),
            rotulo('LblRes' + pref + 'Valores', '', T.F_BOLD, 14, cor('Texto'), largura=-1, alinh=2),
        ]),
        esp_v('EspRes' + pref + 'C', 12),
    ])


N_LINHAS_CAT = len(T.CATEGORIAS)


def linha_categoria(i):
    """v1.9: uma linha da lista do cartao "Gastos por categoria": bolinha na cor da fatia | nome ... valor; embaixo,
    a barra do limite (so quando a categoria tem limite) e o texto (% das despesas ou quanto do limite foi usado).
    As 8 linhas existem na tela; os blocos preenchem da maior para a menor e escondem as que sobram."""
    s = str(i)
    return comp('VerticalArrangement', 'PnlCat' + s, {'Width': -2, 'Visible': 'False'}, [
        comp('HorizontalArrangement', 'HzCat' + s, {'Width': -2, 'AlignVertical': 2}, [
            comp('Image', 'ImgCat' + s, {'Picture': T.img_ponto_cat(i), 'Width': T.PONTO_CAT, 'Height': T.PONTO_CAT}),
            esp_h('EspCat' + s + 'A', 8),
            rotulo('LblCatNome' + s, T.CATEGORIAS[i - 1][0], T.F_SEMI, 14, cor('Texto')),
            rotulo('LblCatValor' + s, 'R$ 0,00', T.F_BOLD, 14, cor('Texto'), largura=-1, alinh=2),
        ]),
        comp('HorizontalArrangement', 'HzCatSub' + s, {'Width': -2}, [
            esp_h('EspCat' + s + 'S', T.PONTO_CAT + 8),
            comp('VerticalArrangement', 'ColCat' + s, {'Width': -2}, [
                esp_v('EspCat' + s + 'B', 4),
                comp('HorizontalArrangement', 'HzCatTrilho' + s, {'Width': -2, 'Height': 8, 'BackgroundColor': cor('Trilho'),
                                                                 'Visible': 'False'}, [
                    comp('Label', 'LblCatBarra' + s, {'Text': '', 'Width': pct(1), 'Height': 8, 'HasMargins': 'False',
                                                       'FontSize': 4, 'BackgroundColor': T.aia(T.RED)}),
                ]),
                esp_v('EspCat' + s + 'C', 3),
                rotulo('LblCatPct' + s, '0,0% das despesas', T.F_MED, 12, cor('Suave')),
            ]),
        ]),
        esp_v('EspCat' + s + 'D', 12),
    ])


def avatar(pref, lado, fundo, mascara):
    """Avatar redondo com foto recortada pelo centro.

    Como funciona (regras lidas em Sprite.java / ImageSprite.java / Canvas.java):
      - a caixa (lado x lado) mostra o avatar padrao como imagem de fundo e centraliza um Canvas 3x maior,
        transparente; so o miolo (lado x lado) do Canvas aparece, o resto e cortado pela caixa;
      - SprFoto<pref> e a foto: os blocos dao a ela o tamanho que COBRE o miolo mantendo a proporcao e a
        centralizam. O Canvas e 3x maior justamente para a foto caber inteira dentro dele: um sprite que passa
        da borda do Canvas e empurrado de volta (Sprite.moveIntoBounds), o que tiraria a foto do centro;
      - SprMascara<pref> fica por cima (Z maior): quadrado na cor do fundo com um furo redondo.
    """
    C = 3 * lado
    F = T.MASCARA_FOLGA      # a moldura passa um pouco do avatar: a borda dela fica fora da area visivel
    return comp('VerticalArrangement', 'BoxAvatar' + pref, {'Width': lado, 'Height': lado, 'AlignHorizontal': 3,
                                                           'AlignVertical': 2, 'Image': fundo}, [
        comp('Canvas', 'Canvas' + pref, {'Width': C, 'Height': C, 'BackgroundColor': '&H00FFFFFF'}, [
            comp('ImageSprite', 'SprFoto' + pref, {'X': lado, 'Y': lado, 'Z': 1, 'Visible': 'False',
                                                   'Rotates': 'False', 'Enabled': 'False'}),
            comp('ImageSprite', 'SprMascara' + pref, {'Picture': mascara, 'X': lado - F, 'Y': lado - F, 'Z': 2,
                                                      'Width': lado + 2 * F, 'Height': lado + 2 * F,
                                                      'Rotates': 'False', 'Enabled': 'False'}),
        ]),
    ])


def cartao(nome, col, imagem, filhos, extra=None):
    """Cartao (imagem de fundo arredondada) com uma coluna interna de 86% da tela."""
    p = {'Width': -2, 'Image': imagem, 'AlignHorizontal': 3}
    p.update(extra or {})
    return comp('VerticalArrangement', nome, p, [
        esp_v('Esp' + nome + '0', 18),
        comp('VerticalArrangement', col, {'Width': pct(86)}, filhos),
        esp_v('Esp' + nome + '1', 18),
    ])


# ----------------------------------------------------------------- v1.7: pecas novas
EVO_ALT = 112        # altura (dp) da area das barras "mes a mes"


def barra(nome, largura, cor_hex):
    """Barra vertical: rotulo vazio com fundo colorido; os blocos mudam a altura (Height em dp)."""
    return comp('Label', nome, {'Text': '', 'Width': largura, 'Height': 0, 'HasMargins': 'False', 'FontSize': 4,
                                'BackgroundColor': T.aia(cor_hex)})


def coluna_mes(i):
    """Coluna do grafico 'mes a mes': barra verde (entradas) + vermelha (despesas), alinhadas pela base, e a inicial do
    mes como botao (toque = abre aquele mes no Grafico)."""
    s = str(i)
    return comp('VerticalArrangement', 'ColMes' + s, {'Width': -2, 'AlignHorizontal': 3}, [
        comp('HorizontalArrangement', 'HzBarMes' + s, {'Height': EVO_ALT, 'AlignVertical': 3, 'AlignHorizontal': 3}, [
            barra('LblBarE' + s, 7, T.GREEN),
            esp_h('EspBar' + s, 2),
            barra('LblBarD' + s, 7, T.RED),
        ]),
        esp_v('EspMes' + s, 4),
        # v1.8.1: a inicial e uma IMAGEM quadrada (o texto de botao estreito sumia no aparelho); a coluna a centraliza
        comp('Button', 'BtnMes' + s, {'Text': '', 'Image': T.img_mes(T.LETRAS_MES[i - 1], 'n'), 'Width': T.MES_LADO,
                                      'Height': T.MES_LADO}),
    ])


def linha_orcamento(i):
    """Linha do painel de limites: icone, nome da categoria e campo 'R$ ____' (vazio = sem limite)."""
    s = str(i)
    return comp('VerticalArrangement', 'PnlOrc' + s, {'Width': -2}, [
        comp('HorizontalArrangement', 'HzOrc' + s, {'Width': -2, 'AlignVertical': 2}, [
            comp('Image', 'ImgOrc' + s, {'Picture': T.CATEGORIAS[i - 1][1], 'Width': 32, 'Height': 32}),
            esp_h('EspOrc' + s + 'A', 10),
            rotulo('LblOrcNome' + s, T.CATEGORIAS[i - 1][0], T.F_SEMI, 14, cor('Texto')),
            comp('HorizontalArrangement', 'HzCampoOrc' + s, {'Width': T.SIZES['campo_curto_w'], 'Height': T.SIZES['campo_h'],
                                                            'AlignVertical': 2, 'Image': img('CampoCurto')}, [
                esp_h('EspOrc' + s + 'B', 10),
                # caixa um pouco maior que o texto (centralizado): as letras nao encostam na borda do rotulo
                rotulo('LblOrcRs' + s, 'R$', T.F_BOLD, 15, cor('Marca'), largura=26, alinh=1),
                esp_h('EspOrc' + s + 'C', 6),
                comp('TextBox', 'TxtOrc' + s, {
                    'Hint': 'Sem limite', 'Width': -2, 'Height': 48, 'FontSize': 15, 'FontTypeface': T.F_MED,
                    'BackgroundColor': '&H00FFFFFF', 'TextColor': cor('Texto'), 'HintColor': cor('Dica'),
                    'NumbersOnly': 'False'}),
            ]),
        ]),
        esp_v('EspOrc' + s + 'D', 8),
    ])


def linha_evo(pref, nome):
    """Linha 'nome ............ valor' + frase de comparacao embaixo (aba Evolucao)."""
    return comp('VerticalArrangement', 'PnlEvo' + pref, {'Width': -2}, [
        comp('HorizontalArrangement', 'HzEvo' + pref, {'Width': -2, 'AlignVertical': 2}, [
            rotulo('LblEvo' + pref + 'Nome', nome, T.F_SEMI, 14, cor('Texto')),
            rotulo('LblEvo' + pref + 'Valor', 'R$ 0,00', T.F_BOLD, 14, cor('Texto'), largura=-1, alinh=2),
        ]),
        esp_v('EspEvo' + pref + 'A', 2),
        rotulo('LblEvo' + pref + 'Comp', '', T.F_MED, 12.5, cor('Suave')),
        esp_v('EspEvo' + pref + 'B', 10),
    ])


def pilula(nome_hz, botoes, largura=-2):
    """Controle segmentado (fundo das abas + botoes em pilula)."""
    filhos = [esp_h(nome_hz + 'E1', 4)]
    for i, (nome, texto) in enumerate(botoes):
        filhos.append(botao(nome, texto, T.IMG_ABA_ON if i == 0 else T.IMG_ABA_OFF, '#FFFFFF' if i == 0 else T.MUTED, 13, T.PILULA_H))
    filhos.append(esp_h(nome_hz + 'E2', 4))
    return comp('HorizontalArrangement', nome_hz, {'Width': largura, 'Height': T.SIZES['abas_h'], 'AlignVertical': 2,
                                                  'Image': img('Abas')}, filhos)


def linha_dados(pref, tipo, nome, texto, icone):
    """v1.8: linha de "Seus dados": icone + texto (o botao/seletor ocupa a linha) + seta, sobre o fundo das abas."""
    return comp('HorizontalArrangement', 'HzDados' + pref, {'Width': -2, 'Height': T.SIZES['perigo_h'], 'AlignVertical': 2,
                                                            'Image': img('Abas')}, [
        esp_h('EspDad' + pref + 'A', 14),
        comp('Image', 'ImgDados' + pref, {'Picture': img('Ic' + icone), 'Width': 24, 'Height': 24}),
        esp_h('EspDad' + pref + 'B', 10),
        comp(tipo, nome, {'Text': texto, 'Width': -2, 'Height': 48, 'FontSize': 14.5, 'FontTypeface': T.F_SEMI,
                          'TextColor': cor('Texto'), 'TextAlignment': 0, 'BackgroundColor': '&H00FFFFFF'}),
        comp('Image', 'ImgSeta' + pref, {'Picture': img('IcSeta'), 'Width': 16, 'Height': 16}),
        esp_h('EspDad' + pref + 'C', 12),
    ])


def botao_secundario(nome, texto, tipo='Button'):
    """Botao de largura total com o fundo das abas (contorno discreto) e texto na cor do tema."""
    return botao(nome, texto, img('Abas'), cor('Texto'), 14, T.SIZES['perigo_h'], tipo=tipo)


def arvore():
    global _uuid
    _uuid = itertools.count(1000003, 7919)
    del TEMA_REG[:]

    topo = comp('VerticalArrangement', 'CardSaldo', {'Width': -2, 'Image': T.IMG_TOPO, 'AlignHorizontal': 3}, [
        esp_v('EspTopo', 8),
        comp('HorizontalArrangement', 'HzMarca', {'Width': pct(90), 'AlignVertical': 2}, [
            comp('Image', 'ImgLogo', {'Picture': T.IMG_LOGO, 'Width': 28, 'Height': 28}),
            esp_h('EspMarca', 9),
            rotulo('LblMarca', 'Contô', T.F_XBOLD, 21, '#FFFFFF', largura=-1),
            rotulo('LblSaudacao', '', T.F_SEMI, 13, T.HDR_CAP, alinh=2),
            esp_h('EspMarca3', 10),
            comp('Image', 'ImgTema', {'Picture': img('TemaIcone'), 'Width': 34, 'Height': 34, 'Clickable': 'True'}),
            esp_h('EspMarca4', 8),
            avatar('Topo', T.AVATAR_TOPO, T.IMG_AVATAR_TOPO, T.IMG_MASCARA_TOPO),
        ]),
        esp_v('EspMarca2', 6),
        rotulo('LblSaldoTitulo', 'Saldo atual', T.F_SEMI, 13, T.HDR_LIGHT, largura=pct(90)),
        rotulo('LblSaldo', 'R$ 0,00', T.F_XBOLD, 36, '#FFFFFF', largura=pct(90)),
        esp_v('EspSaldo', 10),
        comp('HorizontalArrangement', 'HzResumo', {'Width': pct(90)}, [
            chip('Entradas', 'Entradas no mês', 'LblEntradas', T.IMG_SETA_ENT),
            esp_h('EspChips', pct(2)),
            chip('Despesas', 'Despesas no mês', 'LblDespesas', T.IMG_SETA_DESP),
        ]),
        esp_v('EspBase', 18),
    ])

    abas = comp('HorizontalArrangement', 'HzNav', {'Width': pct(92), 'Height': T.SIZES['abas_h'], 'AlignVertical': 2,
                                                  'Image': img('Abas')}, [
        esp_h('EspNav1', 4),
        # v1.8.1: pilula de 44 dp e texto de 12 sp (cabem os 4 nomes sem cortar em telas de 360 dp)
        botao('BtnNavLancar', 'Lançar', T.IMG_ABA_ON, '#FFFFFF', T.FONTE_ABA_NAV, T.PILULA_H),
        botao('BtnNavHistorico', 'Histórico', T.IMG_ABA_OFF, T.MUTED, T.FONTE_ABA_NAV, T.PILULA_H),
        botao('BtnNavGrafico', 'Gráfico', T.IMG_ABA_OFF, T.MUTED, T.FONTE_ABA_NAV, T.PILULA_H),
        botao('BtnNavEvolucao', 'Evolução', T.IMG_ABA_OFF, T.MUTED, T.FONTE_ABA_NAV, T.PILULA_H),
        esp_h('EspNav2', 4),
    ])

    # v1.7: periodo (Historico e Grafico): Mes | Ano | Tudo + setas para andar no tempo
    periodo = comp('VerticalArrangement', 'PnlPeriodo', {'Width': pct(92), 'Visible': 'False', 'AlignHorizontal': 3}, [
        pilula('HzModo', [('BtnModoMes', 'Mês'), ('BtnModoAno', 'Ano'), ('BtnModoTudo', 'Tudo')]),
        esp_v('EspPer1', 4),
        comp('HorizontalArrangement', 'HzPerNav', {'Width': -2, 'AlignVertical': 2}, [
            # v1.8.1: setas como imagem (os blocos trocam pela imagem transparente quando nao ha para onde ir)
            comp('Button', 'BtnPerAnt', {'Text': '', 'Image': 'seta_esq.png', 'Width': T.SETA_W, 'Height': T.SETA_H}),
            rotulo('LblPeriodo', 'novembro de 2026', T.F_BOLD, 16, cor('Texto'), alinh=1),
            comp('Button', 'BtnPerProx', {'Text': '', 'Image': 'seta_dir.png', 'Width': T.SETA_W, 'Height': T.SETA_H}),
        ]),
        esp_v('EspPer2', 8),
    ])

    aviso = comp('VerticalArrangement', 'BoxAviso', {'Width': pct(92), 'Visible': 'False'}, [
        comp('HorizontalArrangement', 'PnlAviso', {'Width': -2, 'AlignVertical': 2, 'Image': T.IMG_AVISO_ERRO}, [
            esp_h('EspAv1', 14),
            comp('VerticalArrangement', 'ColAviso', {'Width': -2}, [
                esp_v('EspAv2', 12),
                rotulo('LblAviso', '', T.F_SEMI, 14, T.DANGER_TXT),
                esp_v('EspAv3', 12),
            ]),
            esp_h('EspAv4', 14),
        ]),
        esp_v('EspAv5', 10),
    ])

    seletor = comp('VerticalArrangement', 'PnlPicker', {'Width': -2, 'Visible': 'False', 'AlignHorizontal': 3}, [
        rotulo('LblPickerTitulo', 'Escolha uma categoria', T.F_BOLD, 19, cor('Texto'), largura=pct(90)),
        esp_v('EspP0', 3),
        rotulo('LblPickerSub', 'Toque na opção desejada.', T.F_MED, 12.5, cor('Suave'), largura=pct(90)),
        esp_v('EspP1', 8),
        comp('ListView', 'ListaOpcoes', {
            'Width': -2, 'Height': 400, 'ListViewLayout': 3, 'BackgroundColor': cor('Fundo'),
            'ElementColor': cor('Cartao'), 'SelectionColor': cor('Selecao'),
            'TextColor': cor('Texto'), 'FontSize': 17, 'FontTypeface': T.F_SEMI,
            'ImageWidth': 96, 'ImageHeight': 96, 'ElementCornerRadius': 40, 'ElementMarginsWidth': 33}),
        esp_v('EspP2', 6),
        botao('BtnPickerVoltar', 'Voltar', img('Abas'), cor('Texto'), 14, T.SIZES['perigo_h'], largura=pct(92)),
        esp_v('EspP3', 14),
    ])

    # v1.8: meta em andamento (so aparece quando ha meta); toque em "Ver" abre a aba Evolucao
    meta_mini = comp('HorizontalArrangement', 'PnlMetaMini', {'Width': -2, 'Height': T.SIZES['mini_h'], 'AlignVertical': 2,
                                                              'Image': img('CartaoMini'), 'Visible': 'False'}, [
        esp_h('EspMM1', 28),
        comp('Image', 'ImgMetaMini', {'Picture': img('IcAlvo'), 'Width': 30, 'Height': 30}),
        esp_h('EspMM2', 12),
        comp('VerticalArrangement', 'ColMetaMini', {'Width': -2}, [
            rotulo('LblMetaMini', '', T.F_BOLD, 14, cor('Texto')),
            esp_v('EspMM3', 6),
            comp('HorizontalArrangement', 'HzBarMetaMini', {'Width': pct(50), 'Height': 8, 'BackgroundColor': cor('Trilho')}, [
                comp('Label', 'BarMetaMini', {'Text': '', 'Width': 1, 'Visible': 'False', 'Height': 8, 'HasMargins': 'False', 'FontSize': 4,
                                              'BackgroundColor': cor('BarraMeta')}),
            ]),
            esp_v('EspMM4', 5),
            rotulo('LblMetaMiniSub', '', T.F_MED, 12, cor('Suave')),
        ]),
        comp('Button', 'BtnMetaMini', {'Text': 'Ver', 'Width': 56, 'Height': 48, 'FontSize': 14, 'FontTypeface': T.F_BOLD,
                                       'TextColor': cor('Marca'), 'BackgroundColor': '&H00FFFFFF'}),
        esp_h('EspMM5', 20),
    ])

    # v2.0: ha lancamentos das notificacoes do banco esperando conferencia
    aviso_notif = comp('HorizontalArrangement', 'HzAvisoNotif', {'Width': -2, 'Height': T.SIZES['mini_h'], 'AlignVertical': 2,
                                                                'Image': img('CartaoMini'), 'Visible': 'False'}, [
        esp_h('EspAN1', 28),
        comp('Image', 'ImgAvisoNotif', {'Picture': img('IcSino'), 'Width': 26, 'Height': 26}),
        esp_h('EspAN2', 10),
        comp('Button', 'BtnAvisoNotif', {'Text': '', 'Width': -2, 'Height': 48, 'FontSize': 14, 'FontTypeface': T.F_BOLD,
                                         'TextColor': cor('Marca'), 'TextAlignment': 0, 'BackgroundColor': '&H00FFFFFF'}),
        esp_h('EspAN3', 20),
    ])

    lancar = comp('VerticalArrangement', 'PnlLancar', {'Width': -2, 'AlignHorizontal': 3}, [
        aviso,
        aviso_notif,
        meta_mini,
        cartao('CartaoLancar', 'ColLancar', img('CartaoLancar'), [
            rotulo('LblTituloLancar', 'Novo lançamento', T.F_BOLD, 19, cor('Texto')),
            esp_v('EspL00', 3),
            rotulo('LblSubLancar', 'Registre uma entrada ou uma despesa.', T.F_MED, 12.5, cor('Suave')),
            esp_v('EspL0', 12),
            rotulo('LblRotuloDesc', 'Descrição', T.F_SEMI, 12, cor('Suave')),
            esp_v('EspL1', 5),
            campo_texto('TxtDescricao', 'Ex.: Salário, Mercado', img('Campo'), 'HzCampoDesc'),
            esp_v('EspL2', 11),
            rotulo('LblRotuloValor', 'Valor', T.F_SEMI, 12, cor('Suave')),
            esp_v('EspL3', 5),
            campo_texto('TxtValor', 'Ex.: 25,90 ou 1.250,99', T.IMG_CAMPO, 'HzCampoValor', prefixo='R$', nome_pref='LblReais'),
            erro_campo('LblErroValor'),
            esp_v('EspL4', 11),
            rotulo('LblCategoria', 'Categoria', T.F_SEMI, 12, cor('Suave')),
            esp_v('EspL5', 5),
            campo_lista('BtnCategoria', 'ImgCatIcone', 'Selecione uma categoria', 'HzCampoCat'),
            erro_campo('LblErroCat'),
            esp_v('EspL6', 11),
            rotulo('LblPagamento', 'Forma de pagamento ou recebimento', T.F_SEMI, 12, cor('Suave')),
            esp_v('EspL7', 5),
            # v1.8.1: texto mais curto (o antigo quebrava em 2 linhas e era cortado em telas de 360 dp ou com fonte grande)
            campo_lista('BtnPagamento', 'ImgPagIcone', 'Selecione uma forma', 'HzCampoPag'),
            erro_campo('LblErroPag'),
            esp_v('EspL8', 11),
            # v1.8: data (opcional; "Hoje" se a pessoa nao mexer)
            rotulo('LblRotuloData', 'Data', T.F_SEMI, 12, cor('Suave')),
            esp_v('EspL8b', 5),
            comp('HorizontalArrangement', 'HzCampoData', {'Width': -2, 'Height': T.SIZES['campo_h'], 'AlignVertical': 2,
                                                         'Image': img('CampoSel')}, [
                esp_h('EspDataA', 13),
                comp('Image', 'ImgData', {'Picture': img('IcCalendario'), 'Width': 24, 'Height': 24}),
                esp_h('EspDataB', 9),
                comp('DatePicker', 'PickerData', {'Text': 'Hoje', 'Width': -2, 'Height': 48, 'FontSize': 14, 'FontTypeface': T.F_MED,
                                                  'TextColor': cor('Texto'), 'TextAlignment': 0, 'BackgroundColor': '&H00FFFFFF'}),
                esp_h('EspDataC', 38),
            ]),
            erro_campo('LblErroData'),
            esp_v('EspL8c', 10),
            # v1.7: repetir todo mes (caixa desenhada; o toque na caixa ou no texto alterna)
            comp('HorizontalArrangement', 'HzRepetir', {'Width': -2, 'AlignVertical': 2}, [
                comp('Image', 'ImgRepetir', {'Picture': img('CheckOff'), 'Width': 26, 'Height': 26, 'Clickable': 'True'}),
                esp_h('EspRep1', 6),
                comp('Button', 'BtnRepetir', {'Text': 'Repetir todo mês (ex.: aluguel, salário)', 'Width': -2, 'Height': -1,
                                              'FontSize': 13.5, 'FontTypeface': T.F_MED, 'TextColor': cor('Texto'),
                                              'TextAlignment': 0, 'BackgroundColor': '&H00FFFFFF'}),
            ]),
            esp_v('EspL9', 10),
            comp('HorizontalArrangement', 'HzBotoes', {'Width': -2}, [
                botao('BtnEntrada', '+ Entrada', T.IMG_BTN_ENT, '#FFFFFF', 16, T.SIZES['btn_h']),
                esp_h('EspBotoes', 10),
                botao('BtnDespesa', '− Despesa', T.IMG_BTN_DESP, '#FFFFFF', 16, T.SIZES['btn_h']),
            ]),
            botao_texto('BtnCancelarEdicao', 'Cancelar edição', cor('Suave'), -1, extra={'Visible': 'False'}),
        ]),
        esp_v('EspLFim', 8),
    ])

    historico = comp('VerticalArrangement', 'PnlHistorico', {'Width': -2, 'Height': -2, 'Visible': 'False', 'AlignHorizontal': 3}, [
        rotulo('LblTituloHist', 'Histórico', T.F_BOLD, 19, cor('Texto'), largura=pct(90)),
        esp_v('EspH00', 3),
        rotulo('LblDicaHist', 'Toque em um lançamento para editar ou excluir.', T.F_MED, 12.5, cor('Suave'), largura=pct(90)),
        esp_v('EspH0', 8),
        # v1.7: busca
        comp('HorizontalArrangement', 'HzCampoBusca', {'Width': pct(92), 'Height': T.SIZES['campo_h'], 'AlignVertical': 2,
                                                      'Image': img('Campo')}, [
            esp_h('EspBusca1', 12),
            comp('Image', 'ImgBusca', {'Picture': img('Busca'), 'Width': 20, 'Height': 20}),
            esp_h('EspBusca2', 8),
            comp('TextBox', 'TxtBusca', {
                'Hint': 'Buscar descrição, categoria ou pagamento', 'Width': -2, 'Height': 48, 'FontSize': 14,
                'FontTypeface': T.F_MED, 'BackgroundColor': '&H00FFFFFF', 'TextColor': cor('Texto'),
                'HintColor': cor('Dica'), 'NumbersOnly': 'False'}),
            comp('Button', 'BtnLimparBusca', {'Text': '', 'Image': img('Fechar'), 'Width': T.FECHAR_LADO, 'Height': T.FECHAR_LADO,
                                              'Visible': 'False'}),
        ]),
        esp_v('EspH01', 6),
        rotulo('LblResumoHist', '', T.F_SEMI, 13, cor('Suave'), largura=pct(90)),
        esp_v('EspH02', 6),
        rotulo('LblVazio', 'Nenhum lançamento ainda. Comece pela aba Lançar!', T.F_MED, 14, cor('Suave'), largura=pct(90), alinh=1),
        comp('ListView', 'ListaHistorico', {
            'Width': -2, 'Height': -2, 'ListViewLayout': 4, 'BackgroundColor': cor('Fundo'),
            'ElementColor': cor('Cartao'), 'SelectionColor': cor('Selecao'),
            'TextColor': cor('Texto'), 'TextColorDetail': cor('Suave'),
            'FontSize': 17, 'FontSizeDetail': 12.5, 'FontTypeface': T.F_XBOLD, 'FontTypefaceDetail': T.F_MED,
            'ImageWidth': 112, 'ImageHeight': 112, 'ElementCornerRadius': 40, 'ElementMarginsWidth': 33}),
        esp_v('EspH1', 4),
        botao('BtnLimpar', 'Apagar tudo', img('Perigo'), cor('Perigo'), 14, T.SIZES['perigo_h'], largura=pct(92)),
        esp_v('EspH2', 14),
    ])

    grafico = comp('VerticalArrangement', 'PnlGrafico', {'Width': -2, 'Visible': 'False', 'AlignHorizontal': 3}, [
        # v1.9 (pedido do usuario): UM cartao so. Rosca "Gastos por categoria" no lugar da pizza Entradas x Despesas e,
        # embaixo dela, a lista de categorias (antes "Categorias e limites", num cartao a parte), cada uma com a cor da
        # sua fatia; "Ultimos lancamentos" saiu (ja estao no Historico). A rosca e DESENHADA num Canvas (DrawArc): o
        # grafico de pizza do App Inventor (MPAndroidChart) pinta o furo da rosca sempre de branco.
        cartao('CartaoGrafico', 'ColGrafico', img('CartaoGraf'), [
            comp('HorizontalArrangement', 'HzTituloGraf', {'Width': -2, 'AlignVertical': 2}, [
                rotulo('LblTituloGraf', 'Gastos por categoria', T.F_BOLD, 19, cor('Texto')),
                comp('Button', 'BtnLimites', {'Text': 'Limites', 'Width': -1, 'Height': -1, 'FontSize': 14, 'FontTypeface': T.F_BOLD,
                                              'TextColor': cor('Marca'), 'TextAlignment': 2, 'BackgroundColor': '&H00FFFFFF'}),
            ]),
            rotulo('LblSubGraf', 'Total de gastos', T.F_MED, 12.5, cor('Suave')),
            esp_v('EspG01', 2),
            comp('HorizontalArrangement', 'HzRosca', {'Width': -2, 'AlignVertical': 2}, [
                comp('VerticalArrangement', 'ColTotGraf', {'Width': -2}, [
                    rotulo('LblLegDespValor', 'R$ 0,00', T.F_XBOLD, 24, cor('Texto')),
                    esp_v('EspG02', 12),
                    rotulo('LblLegEntNome', 'Entradas', T.F_MED, 12.5, cor('Suave')),
                    rotulo('LblLegEntValor', 'R$ 0,00', T.F_BOLD, 15, cor('Texto')),
                    esp_v('EspG03', 8),
                    rotulo('LblLegSaldoNome', 'Saldo do mês', T.F_MED, 12.5, cor('Suave')),
                    rotulo('LblLegSaldoValor', 'R$ 0,00', T.F_XBOLD, 15, cor('Texto')),
                ]),
                esp_h('EspRosca', 10),
                comp('Canvas', 'CanvasRosca', {'Width': T.ROSCA_LADO, 'Height': T.ROSCA_LADO, 'BackgroundColor': '&H00FFFFFF',
                                               'LineWidth': T.ROSCA_ANEL}),
            ]),
            esp_v('EspG1', 16),
            rotulo('LblVazioGraf', 'Sem dados ainda. Registre uma entrada ou despesa.', T.F_MED, 13.5, cor('Suave'), alinh=1),
            comp('VerticalArrangement', 'PnlCats', {'Width': -2, 'Visible': 'False'},
                 [linha_categoria(i) for i in range(1, N_LINHAS_CAT + 1)]),
        ]),
        esp_v('EspGFim', 8),
    ])

    perfil = comp('VerticalArrangement', 'PnlPerfil', {'Width': -2, 'Visible': 'False', 'AlignHorizontal': 3}, [
        cartao('CartaoPerfil', 'ColPerfil', img('CartaoLancar'), [
            rotulo('LblTituloPerfil', 'Seu perfil', T.F_BOLD, 19, cor('Texto')),
            esp_v('EspPf00', 3),
            rotulo('LblSubPerfil', 'Nome e foto ficam guardados só neste aparelho.', T.F_MED, 12.5, cor('Suave')),
            esp_v('EspPf0', 14),
            comp('HorizontalArrangement', 'HzFoto', {'Width': -2, 'AlignVertical': 2}, [
                avatar('Perfil', T.AVATAR, img('Avatar'), img('Mascara')),
                esp_h('EspPf1', 16),
                comp('VerticalArrangement', 'ColFoto', {'Width': -2}, [
                    # v1.9 (pedido do usuario): tirar a foto na hora, com a camera do celular, ou escolher da galeria
                    botao('BtnTirarFoto', 'Tirar foto', T.IMG_ABA_ON, '#FFFFFF', 13, T.PILULA_H),
                    esp_v('EspPf2', 6),
                    botao('PickerFoto', 'Escolher da galeria', img('PilulaSec'), cor('Texto'), 13, T.PILULA_H, tipo='ImagePicker'),
                    esp_v('EspPf2b', 2),
                    botao_texto('BtnRemoverFoto', 'Remover foto', cor('Perigo'), -1),
                ]),
            ]),
            esp_v('EspPf3', 16),
            rotulo('LblRotuloNome', 'Nome', T.F_SEMI, 12, cor('Suave')),
            esp_v('EspPf4', 5),
            campo_texto('TxtNome', 'Como você quer ser chamado?', img('Campo'), 'HzCampoNome'),
            esp_v('EspPf5', 16),
            rotulo('LblRotuloTema', 'Aparência', T.F_SEMI, 12, cor('Suave')),
            esp_v('EspPf6', 5),
            comp('HorizontalArrangement', 'HzTema', {'Width': -2, 'Height': T.SIZES['abas_h'], 'AlignVertical': 2,
                                                    'Image': img('Abas')}, [
                esp_h('EspTema1', 4),
                botao('BtnTemaClaro', 'Claro', T.IMG_ABA_ON, '#FFFFFF', 13, T.PILULA_H),
                botao('BtnTemaEscuro', 'Escuro', T.IMG_ABA_OFF, T.MUTED, 13, T.PILULA_H),
                esp_h('EspTema2', 4),
            ]),
            esp_v('EspPf7', 18),
            botao('BtnSalvarPerfil', 'Salvar perfil', T.IMG_BTN_ENT, '#FFFFFF', 16, T.SIZES['btn_h']),
            esp_v('EspPf8', 8),
            rotulo('LblPerfilMsg', '', T.F_SEMI, 13, T.AVISO_OK_TXT, alinh=1, extra={'Visible': 'False'}),
        ]),
        esp_v('EspPfRec0', 6),
        # v1.7: lancamentos que se repetem
        cartao('CartaoRecorrentes', 'ColRecorrentes', img('CartaoGraf'), [
            rotulo('LblTituloRec', 'Lançamentos que se repetem', T.F_BOLD, 19, cor('Texto')),
            esp_v('EspRec0', 3),
            rotulo('LblSubRec', 'São lançados sozinhos todo mês, no mesmo dia. Toque em um para parar de repetir.', T.F_MED, 12.5, cor('Suave')),
            esp_v('EspRec1', 10),
            rotulo('LblSemRec', 'Nenhum ainda. Marque “Repetir todo mês” ao lançar.', T.F_MED, 14, cor('Suave'), alinh=1),
            comp('ListView', 'ListaRecorrentes', {
                'Width': -2, 'Height': 64, 'ListViewLayout': 1, 'BackgroundColor': cor('Cartao'),
                'ElementColor': cor('Fundo'), 'SelectionColor': cor('Selecao'),
                'TextColor': cor('Texto'), 'TextColorDetail': cor('Suave'),
                'FontSize': 15, 'FontSizeDetail': 12.5, 'FontTypeface': T.F_BOLD, 'FontTypefaceDetail': T.F_MED,
                'ElementCornerRadius': 30, 'ElementMarginsWidth': 6, 'Visible': 'False'}),
        ]),
        esp_v('EspPfDados0', 6),
        # v1.7: seus dados (limites, planilha, backup)
        cartao('CartaoDados', 'ColDados', img('CartaoGraf'), [
            rotulo('LblTituloDados', 'Seus dados', T.F_BOLD, 19, cor('Texto')),
            esp_v('EspDad0', 3),
            rotulo('LblSubDados', 'Traga o extrato do seu banco, leve tudo para o Excel e faça backup para não perder nada '
                   'se trocar de celular.', T.F_MED, 12.5, cor('Suave')),
            esp_v('EspDad1', 12),
            linha_dados('Lim', 'Button', 'BtnLimites2', 'Limites por categoria', 'Limites'),
            esp_v('EspDad2', 8),
            linha_dados('Imp', 'FilePicker', 'PickerImportar', 'Importar extrato do banco', 'Importar'),
            esp_v('EspDad2b', 8),
            linha_dados('Exp', 'Button', 'BtnExportar', 'Exportar planilha', 'Planilha'),
            esp_v('EspDad3', 8),
            linha_dados('Bkp', 'Button', 'BtnBackup', 'Fazer backup', 'Backup'),
            esp_v('EspDad4', 8),
            linha_dados('Res', 'FilePicker', 'PickerRestaurar', 'Restaurar backup', 'Restaurar'),
            esp_v('EspDad5n', 8),
            linha_dados('Not', 'Button', 'BtnNotificacoes', 'Notificações do banco', 'Sino'),     # v2.0
            esp_v('EspDad5', 8),
            rotulo('LblBackupInfo', 'Você ainda não fez backup.', T.F_MED, 12.5, cor('Suave'), alinh=1),
            esp_v('EspDad6', 6),
            rotulo('LblDadosMsg', '', T.F_SEMI, 13, cor('AvisoOk'), alinh=1, extra={'Visible': 'False'}),
        ]),
        esp_v('EspPfFim', 8),
        botao('BtnPerfilVoltar', 'Voltar', img('Abas'), cor('Texto'), 14, T.SIZES['perigo_h'], largura=pct(92)),
        esp_v('EspPfFim2', 14),
    ])

    # v1.7: evolucao (mes atual x anteriores, mes a mes, saldo acumulado, ano a ano)
    evolucao = comp('VerticalArrangement', 'PnlEvolucao', {'Width': -2, 'Visible': 'False', 'AlignHorizontal': 3}, [
        # v1.8: meta de economia
        cartao('CartaoMeta', 'ColMeta', img('CartaoGraf'), [
            comp('HorizontalArrangement', 'HzTituloMeta', {'Width': -2, 'AlignVertical': 2}, [
                comp('Image', 'ImgTituloMeta', {'Picture': img('IcAlvo'), 'Width': 24, 'Height': 24}),
                esp_h('EspTM1', 8),
                rotulo('LblTituloMeta', 'Sua meta', T.F_BOLD, 19, cor('Texto')),
                comp('Button', 'BtnMetaEditar', {'Text': 'Editar', 'Width': -1, 'Height': -1, 'FontSize': 14, 'FontTypeface': T.F_BOLD,
                                                 'TextColor': cor('Marca'), 'TextAlignment': 2, 'BackgroundColor': '&H00FFFFFF',
                                                 'Visible': 'False'}),
            ]),
            esp_v('EspMeta0', 3),
            rotulo('LblSubMeta', 'Escolha quanto quer juntar e até quando. O app mostra se você está no caminho.',
                   T.F_MED, 12.5, cor('Suave')),
            comp('VerticalArrangement', 'PnlMetaAtiva', {'Width': -2, 'Visible': 'False'}, [
                rotulo('LblMetaNome', '', T.F_XBOLD, 17, cor('Texto')),
                esp_v('EspMeta1', 6),
                comp('HorizontalArrangement', 'HzMetaValores', {'Width': -2, 'AlignVertical': 2}, [
                    rotulo('LblMetaGuardado', '', T.F_BOLD, 14, cor('Texto')),
                    rotulo('LblMetaPct', '', T.F_BOLD, 14, cor('Marca'), largura=-1, alinh=2),
                ]),
                esp_v('EspMeta2', 6),
                comp('HorizontalArrangement', 'HzBarMeta', {'Width': pct(86), 'Height': 12, 'BackgroundColor': cor('Trilho')}, [
                    comp('Label', 'BarMeta', {'Text': '', 'Width': 1, 'Visible': 'False', 'Height': 12, 'HasMargins': 'False', 'FontSize': 4,
                                              'BackgroundColor': cor('BarraMeta')}),
                ]),
                esp_v('EspMeta3', 10),
                rotulo('LblMetaPrazo', '', T.F_MED, 13, cor('Texto')),
                esp_v('EspMeta4', 4),
                rotulo('LblMetaRitmo', '', T.F_SEMI, 13, cor('Suave')),
            ]),
            esp_v('EspMeta5', 12),
            botao('BtnCriarMeta', 'Criar meta', T.IMG_BTN_ENT, '#FFFFFF', 16, T.SIZES['btn_h']),
        ]),
        esp_v('EspEvoMeta', 6),
        # v1.9 (pedido do usuario): o resumo do mes (antes um cartao a parte, so do mes atual) entrou neste cartao e
        # mostra o mes tocado; "Saldo acumulado" e "Ano a ano" sairam (as setas do ano continuam levando aos anteriores)
        cartao('CartaoEvoMeses', 'ColEvoMeses', img('CartaoGraf'), [
            comp('HorizontalArrangement', 'HzEvoAno', {'Width': -2, 'AlignVertical': 2}, [
                rotulo('LblTituloMeses', 'Mês a mês', T.F_BOLD, 19, cor('Texto')),
                comp('Button', 'BtnEvoAnoAnt', {'Text': '', 'Image': 'seta_esq.png', 'Width': T.SETA_W, 'Height': T.SETA_H}),
                rotulo('LblEvoAno', '2026', T.F_BOLD, 16, cor('Texto'), largura=-1, alinh=1),
                comp('Button', 'BtnEvoAnoProx', {'Text': '', 'Image': 'seta_dir.png', 'Width': T.SETA_W, 'Height': T.SETA_H}),
            ]),
            rotulo('LblSubMeses', 'Toque em um mês para ver o resumo dele.', T.F_MED, 12.5, cor('Suave')),
            esp_v('EspEvoM2', 10),
            comp('HorizontalArrangement', 'HzMeses', {'Width': -2}, [coluna_mes(i) for i in range(1, 13)]),
            esp_v('EspEvoM3', 8),
            comp('HorizontalArrangement', 'HzLegEvo', {'Width': -2, 'AlignVertical': 2, 'AlignHorizontal': 3}, [
                comp('Image', 'ImgLegEvoE', {'Picture': T.IMG_PONTO_VERDE, 'Width': 10, 'Height': 10}),
                esp_h('EspLegEvo1', 6),
                rotulo('LblLegEvoE', 'Entradas', T.F_MED, 12.5, cor('Suave'), largura=-1),
                esp_h('EspLegEvo2', 16),
                comp('Image', 'ImgLegEvoD', {'Picture': T.IMG_PONTO_VERM, 'Width': 10, 'Height': 10}),
                esp_h('EspLegEvo3', 6),
                rotulo('LblLegEvoD', 'Despesas', T.F_MED, 12.5, cor('Suave'), largura=-1),
            ]),
            esp_v('EspEvoM4', 16),
            # resumo do mes escolhido (tocado nas iniciais; comeca no mes atual)
            rotulo('LblTituloEvo', 'Este mês', T.F_BOLD, 16, cor('Texto')),
            esp_v('EspEvo0', 4),
            rotulo('LblEvoFrase', '', T.F_XBOLD, 15, cor('Texto')),
            esp_v('EspEvo1', 12),
            linha_evo('Desp', 'Despesas'),
            linha_evo('Ent', 'Entradas'),
            botao_texto('BtnEvoVerMes', 'Ver gastos por categoria deste mês', cor('Marca'), -1),
            esp_v('EspEvoM5', 6),
            comp('HorizontalArrangement', 'HzEvoDiv', {'Width': -2, 'Height': 1, 'BackgroundColor': cor('Trilho')}),
            esp_v('EspEvoM6', 12),
            comp('HorizontalArrangement', 'HzEvoAnoRes', {'Width': -2}, [
                rotulo('LblEvoAnoNomes', '', T.F_MED, 13.5, cor('Texto')),
                rotulo('LblEvoAnoValores', '', T.F_BOLD, 13.5, cor('Texto'), largura=-1, alinh=2),
            ]),
        ]),
        esp_v('EspEvoFim', 14),
    ])

    # v1.7: limites por categoria (orcamento mensal)
    orcamento = comp('VerticalArrangement', 'PnlOrcamento', {'Width': -2, 'Visible': 'False', 'AlignHorizontal': 3}, [
        cartao('CartaoOrc', 'ColOrc', img('CartaoLancar'), [
            rotulo('LblTituloOrc', 'Limites por mês', T.F_BOLD, 19, cor('Texto')),
            esp_v('EspOrc0', 3),
            rotulo('LblSubOrc', 'Quanto você quer gastar, no máximo, em cada categoria por mês. Deixe em branco para não ter limite.',
                   T.F_MED, 12.5, cor('Suave')),
            esp_v('EspOrc1', 14),
        ] + [linha_orcamento(i) for i in range(1, N_LINHAS_CAT + 1)] + [
            rotulo('LblErroOrc', '', T.F_MED, 12.5, cor('Perigo'), extra={'Visible': 'False'}),
            esp_v('EspOrc2', 10),
            botao('BtnSalvarOrc', 'Salvar limites', T.IMG_BTN_ENT, '#FFFFFF', 16, T.SIZES['btn_h']),
        ]),
        esp_v('EspOrcFim', 8),
        botao('BtnOrcVoltar', 'Voltar', img('Abas'), cor('Texto'), 14, T.SIZES['perigo_h'], largura=pct(92)),
        esp_v('EspOrcFim2', 14),
    ])

    # v1.8: meta de economia (criar / editar / remover)
    meta = comp('VerticalArrangement', 'PnlMeta', {'Width': -2, 'Visible': 'False', 'AlignHorizontal': 3}, [
        cartao('CartaoMetaEdit', 'ColMetaEdit', img('CartaoLancar'), [
            rotulo('LblTituloMetaEdit', 'Meta de economia', T.F_BOLD, 19, cor('Texto')),
            esp_v('EspME0', 3),
            rotulo('LblSubMetaEdit', 'Quanto você quer juntar e até quando. O progresso conta o que você guardar '
                   '(entradas menos despesas) a partir de hoje.', T.F_MED, 12.5, cor('Suave')),
            esp_v('EspME1', 14),
            rotulo('LblRotuloMetaNome', 'Nome da meta', T.F_SEMI, 12, cor('Suave')),
            esp_v('EspME2', 5),
            campo_texto('TxtMetaNome', 'Ex.: Viagem, Reserva de emergência', img('Campo'), 'HzCampoMetaNome'),
            esp_v('EspME3', 11),
            rotulo('LblRotuloMetaValor', 'Quanto juntar', T.F_SEMI, 12, cor('Suave')),
            esp_v('EspME4', 5),
            campo_texto('TxtMetaValor', 'Ex.: 5.000,00', img('Campo'), 'HzCampoMetaValor', prefixo='R$', nome_pref='LblMetaRs'),
            erro_campo('LblErroMetaValor'),
            esp_v('EspME5', 11),
            rotulo('LblRotuloMetaPrazo', 'Até quando', T.F_SEMI, 12, cor('Suave')),
            esp_v('EspME6', 5),
            comp('HorizontalArrangement', 'HzCampoMetaPrazo', {'Width': -2, 'Height': T.SIZES['campo_h'], 'AlignVertical': 2,
                                                              'Image': img('Campo')}, [
                comp('Button', 'BtnPrazoAnt', {'Text': '', 'Image': 'seta_esq.png', 'Width': T.SETA_W, 'Height': T.SETA_H}),
                rotulo('LblMetaPrazoEdit', '', T.F_BOLD, 15, cor('Texto'), alinh=1),
                comp('Button', 'BtnPrazoProx', {'Text': '', 'Image': 'seta_dir.png', 'Width': T.SETA_W, 'Height': T.SETA_H}),
            ]),
            esp_v('EspME7', 10),
            comp('HorizontalArrangement', 'HzMetaSaldo', {'Width': -2, 'AlignVertical': 2}, [
                comp('Image', 'ImgMetaSaldo', {'Picture': img('CheckOff'), 'Width': 26, 'Height': 26, 'Clickable': 'True'}),
                esp_h('EspME8', 6),
                comp('Button', 'BtnMetaSaldo', {'Text': 'Incluir meu saldo atual', 'Width': -2, 'Height': -1,
                                                'FontSize': 13.5, 'FontTypeface': T.F_MED, 'TextColor': cor('Texto'),
                                                'TextAlignment': 0, 'BackgroundColor': '&H00FFFFFF'}),
            ]),
            esp_v('EspME9', 12),
            botao('BtnSalvarMeta', 'Salvar meta', T.IMG_BTN_ENT, '#FFFFFF', 16, T.SIZES['btn_h']),
            botao_texto('BtnRemoverMeta', 'Remover meta', cor('Perigo'), -1, extra={'Visible': 'False'}),
        ]),
        esp_v('EspMEFim', 8),
        botao('BtnMetaVoltar', 'Voltar', img('Abas'), cor('Texto'), 14, T.SIZES['perigo_h'], largura=pct(92)),
        esp_v('EspMEFim2', 14),
    ])

    # v2.0: lancamentos sugeridos a partir das notificacoes do banco + colar uma mensagem do banco
    notif = comp('VerticalArrangement', 'PnlNotif', {'Width': -2, 'Visible': 'False', 'AlignHorizontal': 3}, [
        cartao('CartaoNotif', 'ColNotif', img('CartaoLancar'), [
            rotulo('LblTituloNotif', 'Notificações do banco', T.F_BOLD, 19, cor('Texto')),
            esp_v('EspNt0', 3),
            rotulo('LblSubNotif', 'O Contô lê as notificações de compras, Pix e transferências dos apps de banco e sugere os '
                   'lançamentos. Nada é lançado sem você confirmar.', T.F_MED, 12.5, cor('Suave')),
            esp_v('EspNt1', 10),
            rotulo('LblNotifStatus', '', T.F_SEMI, 13, cor('Suave')),
            rotulo('LblNotifDiag', '', T.F_MED, 11.5, cor('Suave'), extra={'Visible': 'False'}),     # v2.0.1
            comp('VerticalArrangement', 'PnlNotifAcesso', {'Width': -2, 'Visible': 'False'}, [
                esp_v('EspNt2', 8),
                rotulo('LblNotifAjuda', 'Toque em “Liberar acesso” e ative o Contô na lista. Se o Android disser que é uma '
                       'configuração restrita, toque em “Abrir informações do app”, no menu de três pontinhos escolha “Permitir configurações '
                       'restritas” e tente de novo.', T.F_MED, 12.5, cor('Texto')),
                esp_v('EspNt3', 10),
                botao('BtnNotifAcesso', 'Liberar acesso', T.IMG_BTN_ENT, '#FFFFFF', 15, T.SIZES['btn_h']),
                esp_v('EspNt4', 6),
                botao_secundario('BtnNotifInfoApp', 'Abrir informações do app'),
            ]),
            esp_v('EspNt5', 12),
            rotulo('LblNotifVazio', 'Nenhuma notificação nova. Quando chegar uma compra, Pix ou transferência, ela aparece aqui.',
                   T.F_MED, 14, cor('Suave'), alinh=1),
            comp('ListView', 'ListaNotif', {
                'Width': -2, 'Height': 64, 'ListViewLayout': 1, 'BackgroundColor': cor('Cartao'),
                'ElementColor': cor('Fundo'), 'SelectionColor': cor('Selecao'),
                'TextColor': cor('Texto'), 'TextColorDetail': cor('Suave'),
                'FontSize': 15, 'FontSizeDetail': 12.5, 'FontTypeface': T.F_BOLD, 'FontTypefaceDetail': T.F_MED,
                'ElementCornerRadius': 30, 'ElementMarginsWidth': 6, 'Visible': 'False'}),
            esp_v('EspNt6', 10),
            botao('BtnNotifLancarTodos', 'Lançar todos', T.IMG_BTN_ENT, '#FFFFFF', 16, T.SIZES['btn_h']),
            esp_v('EspNt7', 6),
            botao_secundario('BtnNotifIgnorarTodos', 'Ignorar todas'),
            esp_v('EspNt8', 4),
            botao_texto('BtnNotifAtualizar', 'Atualizar', cor('Marca'), -1),
            rotulo('LblNotifMsg', '', T.F_SEMI, 13, cor('AvisoOk'), alinh=1, extra={'Visible': 'False'}),
        ]),
        esp_v('EspNtC', 6),
        cartao('CartaoColar', 'ColColar', img('CartaoGraf'), [
            rotulo('LblTituloColar', 'Colar mensagem do banco', T.F_BOLD, 19, cor('Texto')),
            esp_v('EspCl0', 3),
            rotulo('LblSubColar', 'Copie a notificação ou a mensagem de texto do banco e cole aqui. O Contô preenche o lançamento '
                   'para você conferir.', T.F_MED, 12.5, cor('Suave')),
            esp_v('EspCl1', 10),
            comp('TextBox', 'TxtColar', {'Width': -2, 'Height': 96, 'MultiLine': 'True', 'Hint': 'Ex.: Compra aprovada de R$ 45,90 em Mercado Bom Preço',
                                         'FontSize': 14, 'FontTypeface': T.F_MED, 'TextColor': cor('Texto'),
                                         # no fundo cinza do campo a cor 'Dica' nao chega a 4,5:1 (medido no T27): 'Suave'
                                         'HintColor': cor('Suave'), 'BackgroundColor': cor('Fundo')}),
            erro_campo('LblErroColar'),
            esp_v('EspCl2', 10),
            botao('BtnInterpretar', 'Preencher o lançamento', T.IMG_BTN_ENT, '#FFFFFF', 16, T.SIZES['btn_h']),
        ]),
        esp_v('EspNtFim', 8),
        botao('BtnNotifVoltar', 'Voltar', img('Abas'), cor('Texto'), 14, T.SIZES['perigo_h'], largura=pct(92)),
        esp_v('EspNtFim2', 14),
    ])

    form = {
        '$Name': 'Screen1', '$Type': 'Form', '$Version': str(VERSIONS['Form']),
        'AppName': 'Contô', 'Title': 'Contô',
        'AlignHorizontal': '3', 'BackgroundColor': cor('Fundo').claro(),
        'Icon': T.IMG_ICONE,
        'PrimaryColor': T.aia(T.EMERALD), 'PrimaryColorDark': T.aia(T.EMERALD_DARK), 'AccentColor': T.aia(T.EMERALD),
        'Sizing': 'Responsive', 'ShowListsAsJson': 'True', 'TitleVisible': 'False', 'DefaultFileScope': 'App',
        'Uuid': '0',
        '$Components': [
            topo, esp_v('EspAbas0', 12), abas, esp_v('EspAbas1', 10), periodo,
            lancar, seletor, historico, grafico, perfil, evolucao, orcamento, meta, notif,
            comp('TinyDB', 'TinyDB1', {'Namespace': 'Conto'}),
            comp('Notifier', 'Notifier1'),
            comp('Clock', 'Clock1', {'TimerEnabled': 'False'}),
            comp('Clock', 'ClockAviso', {'TimerEnabled': 'False', 'TimerInterval': 3000}),
            # v1.9: desenha a rosca DEPOIS que o Canvas ganha tamanho na tela (ver desenharRosca nos blocos)
            comp('Clock', 'ClockRosca', {'TimerEnabled': 'False', 'TimerInterval': 40, 'TimerAlwaysFires': 'False'}),
            comp('Camera', 'CameraFoto'),          # v1.9: foto do perfil tirada na hora
            comp('File', 'File1', {'DefaultScope': 'App'}),
            comp('Sharing', 'Sharing1'),
            comp('LeitorNotificacoes', 'LeitorNotificacoes1'),     # v2.0: extensao com.conto.notificacoes
        ],
        'Scrollable': 'True',
    }
    TEMA_REG.append(('Screen1', 'Form', 'BackgroundColor', cor('Fundo')))
    sem_moldura(form)
    return {'authURL': ['ai2.appinventor.mit.edu'], 'YaVersion': '237', 'Source': 'Form', 'Properties': form}


BOTOES = ('Button', 'DatePicker', 'FilePicker', 'ImagePicker', 'ListPicker', 'TimePicker')


def sem_moldura(no):
    """v1.8.1: no Android (ButtonBase.java), botao de forma padrao com fundo "nenhum" e sem imagem recebe de volta o
    fundo do tema com a cor apagada e MANTEM a sombra/contorno do Material (no aparelho: um quadrado em volta). Com
    forma diferente da padrao, o App Inventor desenha a forma na cor "nenhum" e tira a sombra (setOutlineProvider(null)).
    Por isso todo botao de texto transparente fica com forma 1 (arredondada)."""
    if no.get('$Type') in BOTOES and 'Image' not in no and no.get('BackgroundColor') == '&H00FFFFFF':
        no['Shape'] = '1'
    for f in no.get('$Components', []):
        sem_moldura(f)


def nomes_unicos(arv):
    """Todo componente precisa de um nome unico na tela (o App Inventor identifica cada um pelo $Name)."""
    vistos, repetidos = set(), []

    def visita(c):
        n = c['$Name']
        if n in vistos:
            repetidos.append(n)
        vistos.add(n)
        for f in c.get('$Components', []):
            visita(f)
    visita(arv['Properties'])
    assert not repetidos, 'nomes de componente repetidos: %s' % repetidos
    return arv


def scm_text():
    return '#|\n$JSON\n' + json.dumps(nomes_unicos(arvore()), ensure_ascii=False, separators=(',', ':')) + '\n|#'


if __name__ == '__main__':
    open(sys.argv[1], 'w', encoding='utf-8', newline='').write(scm_text())
    print('scm escrito:', sys.argv[1])
