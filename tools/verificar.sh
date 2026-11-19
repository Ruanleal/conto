#!/bin/bash
# Verificadores estaticos e autotestes sobre os arquivos extraidos de um .aia do Conto.
#
# Uso:  APPINVENTOR=<appinventor-sources>/appinventor bash verificar.sh <arquivo.aia>
#   APPINVENTOR  pasta "appinventor" do repositorio mit-cml/appinventor-sources (o scm_check compara a tela com o
#                codigo-fonte oficial dos componentes)
#   WORK_DIR     opcional: pasta de trabalho (padrao: uma pasta temporaria)
T=$(cd "$(dirname "$0")" && pwd)
AIA=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
A=${APPINVENTOR:?defina APPINVENTOR=<appinventor-sources>/appinventor}
RT=$A/components/src/com/google/appinventor/components/runtime
X=${WORK_DIR:-$(mktemp -d)}/pacote_extraido
rm -rf "$X" && mkdir -p "$X" && (cd "$X" && unzip -q "$AIA")
C=$X/src/appinventor/ai_conto/Conto
export CONTO_EXT_DIR=$X/assets/external_comps    # a extensao do pacote (os autotestes copiam o .bky)
echo "pacote: $(basename "$AIA")  sha256 $(sha256sum "$AIA" | cut -c1-64)"
echo
echo "######## 1) bkycheck: blocos x tela (tipos, propriedades, eventos, variaveis, procedimentos)"
python3 -I "$T/bkycheck.py" "$C/Screen1.bky" "$C/Screen1.scm" | cut -c1-400
echo
echo "######## 2) scm_check: tela/assets/blocos x codigo-fonte oficial do App Inventor"
python3 -I "$T/scm_check.py" "$C/Screen1.scm" "$C/Screen1.bky" "$X/assets" "$RT"
echo
echo "######## 3) autoteste do bkycheck (defeitos plantados nos blocos)"
python3 -I "$T/mutate_check.py" "$C"
echo
echo "######## 4) autoteste do scm_check (defeitos plantados na tela)"
(cd "$T" && python3 mutate_scm.py "$C/Screen1.scm" "$C/Screen1.bky" "$X/assets" "$RT")
echo
echo "######## 5) tamanho de cada metodo compilado (blocos por procedimento/evento)"
python3 -I "$T/tamanho_metodos.py" "$C/Screen1.bky"
