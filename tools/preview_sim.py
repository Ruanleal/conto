#!/usr/bin/env python3
"""Previas APROXIMADAS da v1.9 geradas a partir do ESTADO REAL do aplicativo rodando no simulador (ai_sim.py).

Abre o .aia entregue, faz o que a pessoa faria (digitar, escolher, tocar) e le o estado dos componentes depois de cada
passo; esse estado alimenta o renderizador (render_scm.py: HTML + Chromium, calibrado com as capturas reais do usuario).
Nao e um Android real -- fontes, sombras e espacamentos podem variar um pouco no aparelho.

v1.7: alem das cenas da v1.6, um historico realista de 15 meses (set/2025 a nov/2026) gravado no armazenamento antes
de abrir o app (como quem ja usa o app ha mais de um ano), para mostrar Evolucao, periodo, limites e o que se repete.

Uso: python3 preview_sim.py <arquivo.aia> <pasta_saida> [--rects]
"""
import datetime
import json
import os
import random
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_sim import App          # noqa: E402
import render_scm               # noqa: E402


def argb_hex(v):
    v = int(v) & 0xFFFFFFFF
    return '&H%08X' % v


def rgb_hex(v):
    v = int(v) & 0xFFFFFFFF
    return '#%02X%02X%02X' % ((v >> 16) & 255, (v >> 8) & 255, v & 255)


def estado_do_app(app):
    """Converte o estado dos componentes simulados nas chaves 'Nome.Propriedade' que o renderizador entende."""
    st = {}
    for nome, comp in app.comps.items():
        st[nome + '.Visible'] = 'True' if comp.visible else 'False'
        for p, v in comp.props.items():
            if p == 'Visible':
                continue
            if p.endswith('Color') or p == 'TextColorDetail':
                st['%s.%s' % (nome, p)] = argb_hex(v) if isinstance(v, int) else v
            elif isinstance(v, bool):
                st['%s.%s' % (nome, p)] = 'True' if v else 'False'
            else:
                st['%s.%s' % (nome, p)] = v if isinstance(v, str) else str(v)
        if comp.ctype == 'ImageSprite':
            x, y, w, h = comp.caixa()
            st.update({nome + '.X': str(x), nome + '.Y': str(y), nome + '.Width': str(w), nome + '.Height': str(h),
                       nome + '.Picture': comp.picture})
        if comp.ctype == 'ListView':
            st[nome + '.Elements'] = list(comp.elements)
    if 'ChartData2D1' in app.comps:          # pacotes ate a v1.8.1 (grafico de pizza)
        dd = app.comp('ChartData2D1')
        cores = dd.slice_colors()
        st['Chart1.slices'] = [(rot, val, rgb_hex(cor) if cor is not None else '#888888') for (rot, val), cor in zip(dd.entries, cores)]
        cor_rot = dd.props.get('DataLabelColor', '&HFFFFFFFF')
        st['Chart1.labelcolor'] = 'transparent' if cor_rot[2:4] == '00' else '#' + cor_rot[4:10]
    for nome, comp in app.comps.items():     # v1.9: o que esta desenhado em cada Canvas (a rosca)
        if comp.ctype == 'Canvas' and getattr(comp, 'ops', None):
            st[nome + '.ops'] = [dict(op, caixa=list(op['caixa'])) for op in comp.ops]
    return st


def escolher(app, tipo, nome):
    """Como a pessoa: toca no campo, a lista com icones abre, toca na opcao."""
    app.click('BtnCategoria' if tipo == 'cat' else 'BtnPagamento')
    app.pick_option(nome)


def lancar(app, tipo, desc, valor, cat, pag, repetir=False):
    app.type_text('TxtDescricao', desc)
    app.type_text('TxtValor', valor)
    escolher(app, 'cat', cat)
    escolher(app, 'pag', pag)
    if repetir:
        app.click('BtnRepetir')
    app.click('BtnEntrada' if tipo == 'Entrada' else 'BtnDespesa')


GASTOS = [   # (tipo, descricao, valor, categoria, pagamento, data) -- cenas da v1.6 (um mes so)
    ('Despesa', 'Internet', '89,90', 'Moradia', 'Cartão de débito', (2026, 11, 3, 9, 15)),
    ('Despesa', 'Cinema', '64,00', 'Lazer', 'Pix', (2026, 11, 4, 20, 40)),
    ('Entrada', 'Reembolso', '15,90', 'Outros', 'Dinheiro', (2026, 11, 5, 9, 41)),
    ('Despesa', 'Curso de inglês', '199,90', 'Educação', 'Cartão de crédito', (2026, 11, 6, 8, 5)),
    ('Despesa', 'Mercado do mês', '1.250,99', 'Alimentação', 'Cartão de crédito', (2026, 11, 8, 18, 2)),
    ('Despesa', 'Farmácia', '58,70', 'Saúde', 'Pix', (2026, 11, 9, 11, 12)),
    ('Entrada', 'Salário', '4.800,00', 'Outros', 'Transferência bancária', (2026, 11, 10, 8, 30)),
    ('Despesa', 'Uber', '36,40', 'Transporte', 'Pix', (2026, 11, 10, 23, 5)),
    ('Despesa', 'Almoço', '42,50', 'Alimentação', 'Pix', (2026, 11, 11, 12, 25)),
]

AGORA = datetime.datetime(2026, 11, 12, 21, 30)


def historico_realista():
    """15 meses de uso (set/2025 a 12/nov/2026): salario, aluguel e contas fixas todo mes; mercado, transporte, lazer e
    compras variando; gastos caindo ao longo de 2026 (a 'vida financeira melhorando' que a aba Evolucao mostra)."""
    rnd = random.Random(17)
    regs = []

    def add(tipo, desc, cent, quando, cat, pag):
        regs.append([tipo, desc, cent, quando.strftime('%d/%m/%Y %H:%M'), cat, pag])
    meses = [(2025, m) for m in (9, 10, 11, 12)] + [(2026, m) for m in range(1, 12)]
    for n, (ano, mes) in enumerate(meses):
        fator = 1.0 - 0.025 * n                              # gasta um pouco menos a cada mes
        ultimo = 12 if (ano, mes) == (2026, 11) else 28

        def dia(d, h=10, mi=0):
            return datetime.datetime(ano, mes, d, h, mi)
        add('Entrada', 'Salário', 480000 if (ano, mes) < (2026, 3) else 520000, dia(5, 8, 30), 'Outros', 'Transferência bancária')
        if mes in (10, 12, 3, 6, 9):
            add('Entrada', 'Freela de design', rnd.choice([45000, 60000, 80000]), dia(min(18, ultimo), 19, 10), 'Outros', 'Pix')
        add('Despesa', 'Aluguel', 135000, dia(10, 9, 0), 'Moradia', 'Pix')
        if ultimo >= 12:
            add('Despesa', 'Internet', 9990, dia(12, 7, 40), 'Moradia', 'Cartão de débito')
        for d in (3, 17):
            if d <= ultimo:
                add('Despesa', 'Mercado', int(rnd.randint(42000, 61000) * fator), dia(d, 18, 20), 'Alimentação', 'Cartão de crédito')
        for d in (6, 14, 21, 27):
            if d <= ultimo:
                add('Despesa', rnd.choice(['Uber', 'Ônibus', 'Combustível']), int(rnd.randint(3500, 9000) * fator), dia(d, 8, 15),
                    'Transporte', 'Pix')
        for d in (8, 22):
            if d <= ultimo:
                add('Despesa', rnd.choice(['Cinema', 'Show', 'Bar com amigos', 'Streaming']), int(rnd.randint(6000, 24000) * fator),
                    dia(d, 21, 0), 'Lazer', 'Cartão de crédito')
        if 9 <= ultimo:
            add('Despesa', 'Farmácia', rnd.randint(4000, 15000), dia(9, 11, 10), 'Saúde', 'Pix')
        if (ano, mes) >= (2026, 1) and 11 <= ultimo:
            add('Despesa', 'Curso de inglês', 19990, dia(11, 8, 5), 'Educação', 'Cartão de crédito')
        if 20 <= ultimo:
            add('Despesa', rnd.choice(['Roupas', 'Presente', 'Casa']), int(rnd.randint(8000, 40000) * fator), dia(20, 16, 30),
                'Compras', 'Cartão de crédito')
    # novembro/2026 com o mes ainda pela metade: algumas despesas a mais para os limites terem o que mostrar
    add('Despesa', 'Feira', 18650, datetime.datetime(2026, 11, 7, 9, 30), 'Alimentação', 'Dinheiro')
    add('Despesa', 'Padaria', 4320, datetime.datetime(2026, 11, 12, 8, 10), 'Alimentação', 'Dinheiro')
    add('Despesa', 'Show', 21000, datetime.datetime(2026, 11, 11, 22, 0), 'Lazer', 'Cartão de crédito')
    regs.sort(key=lambda r: datetime.datetime.strptime(r[3], '%d/%m/%Y %H:%M'), reverse=True)
    chave_nov = 2026 * 12 + 10
    recorrentes = [['Entrada', 'Salário', 520000, 'Outros', 'Transferência bancária', 5, chave_nov],
                   ['Despesa', 'Aluguel', 135000, 'Moradia', 'Pix', 10, chave_nov]]
    limites = [120000, 40000, 0, 0, 30000, 0, 0, 0]       # Alimentacao, Transporte, ..., Lazer
    return regs, recorrentes, limites


# v1.8: extrato de banco (formato de conta corrente com cabecalho de agencia e linha de saldo)
EXTRATO_EXEMPLO = ('Extrato conta corrente\nAgência 1234 Conta 56789-0\n\nData;Lançamento;Ag./Origem;Valor (R$);Saldo (R$)\n'
                   '05/11/2026;PIX TRANSF MARIA;;-180,00;\n06/11/2026;SUPERMERCADO BOM PRECO;;-243,17;\n'
                   '07/11/2026;POSTO IPIRANGA;;-150,00;\n07/11/2026;SALDO DO DIA;;;2.950,00\n')


# v2.0: notificacoes de bancos (como o Android entrega: pacote do app, titulo, texto)
NOTIFS_EXEMPLO = [
    ('com.nu.production', 'Compra aprovada', 'Compra de R$ 45,90 APROVADA em MERCADO EXTRA para o cartão com final 1234.'),
    ('com.itau', 'Itaú', 'Compra aprovada no seu cartão final 1234 de R$ 120,00 em 12/11 às 14:32 em POSTO SHELL.'),
    ('com.nu.production', 'Pix recebido', 'Você recebeu um Pix de R$ 1.500,00 de JOÃO DA SILVA.'),
    ('br.com.intermedium', 'Inter', 'Saldo atualizado: R$ disponível'),
]


def gravar_armazenamento(db, regs, recorrentes, limites, extra=None):
    """Grava no TinyDB do simulador (mesmo formato JSON do TinyDB do App Inventor) antes de abrir o app."""
    os.makedirs(db, exist_ok=True)
    dados = {'lancamentos': json.dumps(regs, ensure_ascii=False), 'recorrentes': json.dumps(recorrentes, ensure_ascii=False),
             'orcamentos': json.dumps(limites)}
    dados.update(extra or {})
    json.dump(dados, open(os.path.join(db, 'Conto.json'), 'w', encoding='utf-8'), ensure_ascii=False)


def main(aia, out_dir, rects=False, fotos=None):
    work = os.path.join(out_dir, '_pacote')
    shutil.rmtree(work, ignore_errors=True)
    with zipfile.ZipFile(aia) as z:
        z.extractall(work)
    base = os.path.join(work, 'src', 'appinventor', 'ai_conto', 'Conto')
    bky, scm, assets = base + '/Screen1.bky', base + '/Screen1.scm', os.path.join(work, 'assets')
    # fotos de teste (foto_teste.py) ficam na pasta de trabalho da bateria (SP)
    fotos = fotos or os.path.join(os.environ.get('SP') or os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'fotos_teste')
    saida = {}
    botoes = {}    # v1.8.1: cena -> botao -> caixa de texto (dentro da margem interna do Android) x texto, moldura
    estados = {}   # v1.8.1: cena -> estado dos componentes (para redesenhar a cena em outra largura/tamanho de fonte)
    fila = []      # v1.8.1: (cena, trabalho) desenhados todos juntos no fim
    cores = {}     # cena -> {'Componente.TextColor': '&H..'}: cor REAL do texto naquele momento (o tema muda as cores)
    erros = []

    def foto(app, nome, alto=False):
        """Fotografa o que os blocos deixaram na tela. alto=True: pagina inteira (a tela rola no aparelho)."""
        if 'ClockRosca' in app.comps:
            app.esperar_rosca()          # v1.9: a pessoa olha a tela um instante depois: o ClockRosca ja desenhou
        st = estado_do_app(app)
        cores[nome] = {k: v for k, v in st.items() if k.endswith(('.TextColor', '.HintColor', '.BackgroundColor'))}
        png = os.path.join(out_dir, nome + '.png')
        tab = int(app.g.get('abaAtual', 1))
        # v1.8.1: o estado e guardado agora e todas as cenas sao desenhadas no fim, num navegador so (mais rapido)
        fila.append((nome, {'scm_path': scm, 'assets_dir': assets, 'out_png': png, 'tab': tab, 'state': st,
                            'report_rects': rects, 'full_height': alto, 'report_botoes': True}))
        estados[nome] = {'tab': tab, 'alto': alto, 'state': st}
        erros.extend(app.runtime_errors)
        return png

    # ---- app novo, sem dados (tema claro)
    db = os.path.join(out_dir, '_db_vazio')
    shutil.rmtree(db, ignore_errors=True)
    app = App(bky, scm, db, now=AGORA)
    foto(app, 'lancar_vazio', alto=True)
    app.click('BtnNavHistorico')
    foto(app, 'historico_vazio')
    app.click('BtnNavGrafico')
    foto(app, 'grafico_vazio', alto=True)
    app.click('BtnNavEvolucao')
    foto(app, 'evolucao_vazio', alto=True)
    app.touch('CanvasTopo')
    foto(app, 'perfil_vazio', alto=True)

    # ---- quem ja usa o app ha 15 meses (tema claro)
    db = os.path.join(out_dir, '_db_uso')
    shutil.rmtree(db, ignore_errors=True)
    regs, recorrentes, limites = historico_realista()
    gravar_armazenamento(db, regs, recorrentes, limites)
    app = App(bky, scm, db, now=AGORA)
    # perfil: nome + foto (retrato) -> cabecalho com saudacao e avatar
    app.touch('CanvasTopo')
    app.type_text('TxtNome', 'Marina Costa')
    # v1.9: foto tirada na hora com a camera do celular (a camera devolve uma URL de arquivo)
    app.click('BtnTirarFoto')
    app.camera_tirar('file://' + os.path.join(fotos, 'retrato.jpg'))
    app.click('BtnSalvarPerfil')
    foto(app, 'perfil', alto=True)
    app.click('BtnExportar')                    # planilha: AfterFileSaved -> compartilhamento; mensagem no cartao
    foto(app, 'perfil_exportou', alto=True)
    # v1.8: importar um extrato de banco (confirmacao "Importar") -> mensagem no cartao
    app.pick_file('content://docs/extrato_banco.csv', EXTRATO_EXEMPLO, picker='PickerImportar')
    app.answer_dialog('Importar')
    foto(app, 'perfil_importou', alto=True)
    app.click('BtnPerfilVoltar')

    def cenas(suf):
        app.click('BtnNavLancar')
        app.type_text('TxtDescricao', 'Farmácia')
        app.type_text('TxtValor', '1.250,99')
        escolher(app, 'cat', 'Saúde')
        escolher(app, 'pag', 'Cartão de crédito')
        app.click('BtnRepetir')                 # marca "Repetir todo mes"
        app.pick_date('PickerData', AGORA.year, AGORA.month, AGORA.day - 1)    # v1.8: data de ontem
        foto(app, 'lancar_preenchido' + suf, alto=True)
        app.click('BtnRepetir')
        app.click('BtnCategoria')
        foto(app, 'seletor_categoria' + suf)
        app.pick_option('Saúde')
        # erros inline (campo vermelho + frase sob o campo)
        app.type_text('TxtDescricao', '')
        app.type_text('TxtValor', 'jsjsjsbs')
        app.g['categoriaSel'] = app.g['pagamentoSel'] = ''
        app.g['categoriaIcone'] = app.g['pagamentoIcone'] = ''
        app.call_by_name('atualizarCampos')
        app.click('BtnDespesa')
        foto(app, 'lancar_erros' + suf, alto=True)
        app.type_text('TxtValor', '')
        app.click('BtnNavHistorico')
        foto(app, 'historico' + suf)
        app.type_text('TxtBusca', 'mercado')
        foto(app, 'historico_busca' + suf)
        app.click('BtnLimparBusca')
        # editar: toca na 1a linha e escolhe Editar
        app.pick_history_row(1)
        app.answer_dialog('Editar')
        foto(app, 'lancar_edicao' + suf, alto=True)
        app.click('BtnCancelarEdicao')
        app.click('BtnNavGrafico')
        foto(app, 'grafico' + suf, alto=True)
        app.click('BtnLimites')
        foto(app, 'limites' + suf, alto=True)
        app.type_text('TxtOrc6', '12,3,4')
        app.click('BtnSalvarOrc')
        foto(app, 'limites_erro' + suf, alto=True)
        app.click('BtnOrcVoltar')
        app.click('BtnNavEvolucao')
        foto(app, 'evolucao' + suf, alto=True)
        if suf == '':
            app.click('BtnMes10')                # v1.9: toque em "O" (outubro): o resumo passa a ser de outubro
            foto(app, 'evolucao_outubro', alto=True)
            app.click('BtnMes11')
        # v1.8: meta de economia (criar no tema claro; editar no escuro)
        app.click('BtnCriarMeta' if app.shown('BtnCriarMeta') else 'BtnMetaEditar')
        if suf == '':
            app.type_text('TxtMetaNome', 'Viagem para o Nordeste')
            app.type_text('TxtMetaValor', '12.000,00')
            for _ in range(6):
                app.click('BtnPrazoProx')
        foto(app, 'meta_editar' + suf, alto=True)
        app.click('BtnSalvarMeta')
        foto(app, 'evolucao_meta' + suf, alto=True)
        app.click('BtnNavLancar')
        foto(app, 'lancar_meta' + suf, alto=True)

    cenas('')
    app.click('BtnNavGrafico')
    app.click('BtnModoAno')
    foto(app, 'grafico_ano', alto=True)
    app.click('BtnNavHistorico')
    app.click('BtnModoTudo')
    foto(app, 'historico_tudo')
    app.click('BtnModoMes')
    # aviso de sucesso (faixa verde) no tema claro
    app.click('BtnNavLancar')
    lancar(app, 'Entrada', 'Venda', '12,50', 'Outros', 'Pix')
    foto(app, 'lancar_aviso_ok', alto=True)
    app.fire_timer('ClockAviso')
    foto(app, 'lancar_vazio_com_dados', alto=True)

    # ---- tema escuro (botao da lua no cabecalho)
    app.click('ImgTema')
    cenas('_escuro')
    app.click('BtnNavLancar')
    lancar(app, 'Despesa', 'Padaria', '18,40', 'Alimentação', 'Dinheiro')
    foto(app, 'lancar_aviso_ok_escuro', alto=True)
    app.fire_timer('ClockAviso')
    app.touch('CanvasTopo')
    foto(app, 'perfil_escuro', alto=True)
    # foto em paisagem no perfil (confere o recorte pelo centro)
    app.pick_image(os.path.join(fotos, 'paisagem.jpg'))
    foto(app, 'perfil_escuro_paisagem')
    # ---- v2.0: notificacoes do banco (abre de novo o mesmo aparelho: tema escuro guardado; depois o claro)
    app = App(bky, scm, db, now=AGORA)
    epoca = datetime.datetime(1970, 1, 1)
    quando = lambda minutos: int((AGORA - datetime.timedelta(minutes=minutos) - epoca).total_seconds() * 1000)
    for suf in ('_escuro', ''):
        app.liberar_acesso_notificacoes(False)
        app.touch('CanvasTopo')
        app.click('BtnNotificacoes')
        foto(app, 'notificacoes_sem_acesso' + suf, alto=True)
        app.liberar_acesso_notificacoes()
        if suf == '_escuro':
            for k, (pac, ti, tx) in enumerate(NOTIFS_EXEMPLO):
                app.chegar_notificacao(pac, ti, tx, quando(90 - 20 * k))
        app.click('BtnNotifAtualizar')
        foto(app, 'notificacoes' + suf, alto=True)
        app.click('BtnInterpretar')                          # campo vazio: frase vermelha sob o campo
        foto(app, 'notificacoes_colar_erro' + suf, alto=True)
        app.type_text('TxtColar', 'Pix enviado: R$ 50,00 para Maria Souza.')
        app.click('BtnInterpretar')                          # preenche o Lancar para a pessoa conferir
        foto(app, 'lancar_colado' + suf, alto=True)
        app.fire_timer('ClockAviso')
        app.call_by_name('limparFormulario')
        foto(app, 'lancar_notif' + suf, alto=True)           # faixa "N lancamentos das notificacoes para conferir"
        if suf == '_escuro':
            app.click('ImgTema')
    erros.extend(app.runtime_errors)
    for (nome, _), (r_, b_) in zip(fila, render_scm.render_varios([t for _, t in fila])):
        saida[nome], botoes[nome] = r_, b_
    json.dump({k: v for k, v in saida.items()}, open(os.path.join(out_dir, 'rects.json'), 'w'), indent=1)
    json.dump(cores, open(os.path.join(out_dir, 'cores.json'), 'w'), indent=1)
    json.dump(botoes, open(os.path.join(out_dir, 'botoes.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    json.dump(estados, open(os.path.join(out_dir, 'estados.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print('previas em', out_dir, sorted(saida), 'erros de execucao:', erros)
    return saida


def redesenhar(out_dir, cenas, variantes, foto=True):
    """v1.8.1: redesenha cenas ja fotografadas (estados.json) em outras larguras de tela e/ou tamanhos de fonte do
    sistema, num navegador so. variantes = [(largura_dp, escala_fonte), ...]. Devolve {'393_1.15': {cena: botoes}}."""
    estados = json.load(open(os.path.join(out_dir, 'estados.json'), encoding='utf-8'))
    base = os.path.join(out_dir, '_pacote', 'src', 'appinventor', 'ai_conto', 'Conto')
    scm, assets = base + '/Screen1.scm', os.path.join(out_dir, '_pacote', 'assets')
    trabalhos, chaves = [], []
    for larg, esc in variantes:
        chave = '%d_%.2f' % (larg, esc)
        for nome in cenas:
            e = estados[nome]
            trabalhos.append({'scm_path': scm, 'assets_dir': assets, 'out_png': os.path.join(out_dir, '%s_%s.png' % (nome, chave)),
                              'tab': e['tab'], 'state': e['state'], 'full_height': e['alto'], 'largura_dp': larg,
                              'escala_fonte': esc, 'report_botoes': True})
            chaves.append((chave, nome))
    res = render_scm.render_varios(trabalhos)
    out = {}
    for (chave, nome), (_, botoes) in zip(chaves, res):
        out.setdefault(chave, {})[nome] = botoes
    return out


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], rects='--rects' in sys.argv)
