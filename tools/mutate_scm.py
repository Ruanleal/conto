#!/usr/bin/env python3
"""Autoteste do verificador scm_check.py: planta defeitos conhecidos no .scm/.bky e confirma que CADA um e acusado.
Um verificador que so diz "OK" nao prova nada; este mostra que ele e capaz de dizer "ERRO".
Uso: python3 mutate_scm.py <Screen1.scm> <Screen1.bky> <assets> <runtime_java>"""
import json
import os
import re
import shutil
import sys
import tempfile

import scm_check as S


def carregar(scm):
    t = open(scm, encoding='utf-8').read()
    return json.loads(t[t.index('{'): t.rindex('}') + 1])


def salvar(data, path):
    open(path, 'w', encoding='utf-8').write('#|\n$JSON\n' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n|#')


def achar(data, nome):
    def rec(n):
        if n['$Name'] == nome:
            return n
        for c in n.get('$Components', []):
            r = rec(c)
            if r:
                return r
    return rec(data['Properties'])


def main(scm, bky, assets, rt):
    base = carregar(scm)
    bky_txt = open(bky, encoding='utf-8').read()
    tmp = tempfile.mkdtemp()
    classes_cache = None
    casos = []

    def scm_mut(desc, fn):
        casos.append((desc, 'scm', fn))

    def bky_mut(desc, old, new):
        casos.append((desc, 'bky', (old, new)))

    # ---- defeitos na tela
    def renomear_prop(comp, antiga, nova):
        def f(d):
            n = achar(d, comp)
            n[nova] = n.pop(antiga)
        return f

    def definir(comp, prop, valor):
        def f(d):
            achar(d, comp)[prop] = valor
        return f

    scm_mut('ListaHistorico: FontSize -> TextSize (o defeito real da v1.3)', renomear_prop('ListaHistorico', 'FontSize', 'TextSize'))
    scm_mut('cor malformada (&HFFF) no fundo do cabecalho', definir('CardSaldo', 'BackgroundColor', '&HFFF'))
    scm_mut('imagem inexistente em assets/', definir('CardSaldo', 'Image', 'nao_existe.png'))
    scm_mut('propriedade inventada (Foo) num Label', definir('LblSaldo', 'Foo', 'x'))
    scm_mut('booleano em minusculo (Visible=false)', definir('PnlHistorico', 'Visible', 'false'))
    scm_mut('largura invalida (-5)', definir('BtnLimpar', 'Width', '-5'))
    scm_mut('fonte inexistente em assets/', definir('LblSaldo', 'FontTypeface', 'Manrope-Light.ttf'))
    scm_mut('FontSize negativo', definir('LblSaldo', 'FontSize', '-3'))
    scm_mut('Sizing invalido', definir('Screen1', 'Sizing', 'Responsiv'))
    scm_mut('tipo de componente inexistente', lambda d: achar(d, 'LblSaldo').__setitem__('$Type', 'Etiqueta'))
    scm_mut('componente duplicado (LblSaldo vira LblEntradas)', lambda d: achar(d, 'LblSaldo').__setitem__('$Name', 'LblEntradas'))
    scm_mut('valor nao-texto no .scm (numero JSON)', definir('LblSaldo', 'FontSize', 36))
    # v1.9: o grafico de pizza (Chart1/ChartData2D1) saiu; os defeitos equivalentes agora sao plantados na rosca (Canvas)
    scm_mut('propriedade so de blocos escrita como de designer (Canvas.BackgroundImageinBase64)',
            definir('CanvasRosca', 'BackgroundImageinBase64', 'iVBORw0KGgo='))
    scm_mut('Canvas.LineWidth com texto', definir('CanvasRosca', 'LineWidth', 'grossa'))
    scm_mut('Canvas.LineWidth negativo', definir('CanvasRosca', 'LineWidth', '-26'))
    scm_mut('Clock.TimerInterval com texto', definir('ClockRosca', 'TimerInterval', 'rapido'))

    # ---- defeitos nos blocos
    bky_mut('metodo inexistente (CreateElement -> AddElement)', 'method_name="CreateElement"', 'method_name="AddElement"')
    bky_mut('metodo inexistente (DrawArc -> DrawArch)', 'method_name="DrawArc"', 'method_name="DrawArch"')
    bky_mut('propriedade inexistente (PaintColor -> PaintColour)', 'property_name="PaintColor"', 'property_name="PaintColour"')
    bky_mut('evento inexistente (AfterChoosing -> AfterChoice)', 'event_name="AfterChoosing"', 'event_name="AfterChoice"')
    bky_mut('evento inexistente (Clock.Timer -> Clock.Tick)', 'event_name="Timer"', 'event_name="Tick"')
    bky_mut('bloco aponta para componente que nao existe', 'instance_name="CanvasRosca"', 'instance_name="Rosca9"')
    bky_mut('tipo do componente no bloco diverge do .scm', 'component_type="Canvas"', 'component_type="Spinner"')
    # v1.7: blocos genericos e componente como valor
    bky_mut('generico com propriedade inexistente (Label.Height -> Label.Altura)',
            'set_or_get="set" property_name="Height" is_generic="true"', 'set_or_get="set" property_name="Altura" is_generic="true"')
    bky_mut('generico de um tipo sem nenhum componente no projeto (Label -> Slider)',
            'component_type="Label" set_or_get="set" property_name="Height" is_generic="true"',
            'component_type="Slider" set_or_get="set" property_name="Height" is_generic="true"')
    bky_mut('bloco componente com o tipo errado (File1 como Sharing)', 'component_type="File" instance_name="File1"',
            'component_type="Sharing" instance_name="File1"')
    scm_mut('FilePicker com Action inventada', definir('PickerRestaurar', 'Action', 'Pick Anything'))
    scm_mut('escopo de arquivo inventado na tela', definir('Screen1', 'DefaultFileScope', 'Nuvem'))

    ok = True
    for i, (desc, alvo, mut) in enumerate(casos, 1):
        scm_t = os.path.join(tmp, 'S%d.scm' % i)
        bky_t = os.path.join(tmp, 'S%d.bky' % i)
        if alvo == 'scm':
            d = json.loads(json.dumps(base))
            mut(d)
            salvar(d, scm_t)
            shutil.copy(bky, bky_t)
        else:
            old, new = mut
            if old not in bky_txt:
                print('  [%2d] ? defeito nao aplicavel (texto nao encontrado): %s' % (i, desc))
                ok = False
                continue
            shutil.copy(scm, scm_t)
            open(bky_t, 'w', encoding='utf-8').write(bky_txt.replace(old, new, 1))
        errs, _ = S.main(scm_t, bky_t, assets, rt)
        detectado = bool(errs)
        ok = ok and detectado
        print('  [%2d] %s  %s' % (i, 'DETECTADO' if detectado else 'PASSOU DESPERCEBIDO !!', desc))
        if detectado:
            print('        -> ' + errs[0][:150])
    # controle: sem defeito nenhum, tem de dar zero erros
    errs, _ = S.main(scm, bky, assets, rt)
    print('  controle (arquivos originais): %d erros' % len(errs))
    ok = ok and not errs
    print('AUTOTESTE DO VERIFICADOR DO .SCM: ' + ('OK - %d/%d defeitos plantados foram detectados' % (len(casos), len(casos)) if ok else 'FALHOU'))
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:5]))
