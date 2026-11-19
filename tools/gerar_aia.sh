#!/bin/bash
# Gera as imagens do tema e o projeto do Conto (.aia) com os geradores desta pasta.
#
# Uso:  bash gerar_aia.sh <projeto_original_extraido> <pasta_fontes> <pasta_saida>
#   projeto_original_extraido  o .aia original do Conto (a versao de partida), descompactado. Alguns blocos que nao
#                              mudaram (navegacao entre abas) sao copiados dele.
#   pasta_fontes               pacotes npm @expo-google-fonts/manrope e @expo-google-fonts/roboto (0.4.3)
#   pasta_saida                recebe assets/, proj/ e Conto.aia
# A extensao que vai dentro do .aia vem de ../extension/com.conto.notificacoes.aix (ou de EXT_DIR, se definido).
set -eo pipefail
T=$(cd "$(dirname "$0")" && pwd)
ORIG=$(cd "${1:?informe o projeto original extraido}" && pwd); FONTES=$(cd "${2:?informe a pasta das fontes}" && pwd)
OUT=${3:?informe a pasta de saida}
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
if [ -z "$EXT_DIR" ]; then
  EXT_DIR="$OUT/extcomp"; rm -rf "$EXT_DIR"; mkdir -p "$EXT_DIR"
  (cd "$EXT_DIR" && unzip -q "$T/../extension/com.conto.notificacoes.aix")
fi
export EXT_DIR
rm -rf "$OUT/assets"
python3 "$T/gen_assets.py" "$OUT/assets" "$FONTES" | tail -1
python3 "$T/gen_conto.py" "$ORIG" "$OUT/proj" "$OUT/Conto.aia" "$OUT/assets" | tail -1
