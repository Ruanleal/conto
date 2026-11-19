#!/bin/bash
# Compila a extensao LeitorNotificacoes e gera com.conto.notificacoes.aix com as ferramentas do proprio App Inventor
# (processador de anotacoes, ExternalComponentGenerator e d8), como faz o "ant extensions" do appinventor-sources.
#
# Uso:  APPINVENTOR=<appinventor-sources>/appinventor PROC=<processadores> bash build.sh
#   APPINVENTOR  pasta "appinventor" do repositorio mit-cml/appinventor-sources (com lib/ e components/src)
#   PROC         classes compiladas do pacote com.google.appinventor.components.scripts do mesmo repositorio
#                (ComponentDescriptorGenerator, ComponentListGenerator, ExternalComponentGenerator...)
#   BUILD        opcional: pasta de trabalho (padrao: ./build). O .aix sai em $BUILD/out/
set -e
E=$(cd "$(dirname "$0")" && pwd)
A=${APPINVENTOR:?defina APPINVENTOR=<appinventor-sources>/appinventor}
P=${PROC:?defina PROC=<pasta com os processadores de anotacao compilados do App Inventor>}
B=${BUILD:-$E/build}
rm -rf "$B"; mkdir -p "$B/classes" "$B/gen" "$B/extcomp" "$B/extclass" "$B/deps" "$B/out"
CP=$(sed "s|\$A|$A|g" "$E/classpath.txt" | paste -sd: -)
cd "$E"
javac -nowarn -encoding UTF-8 -source 8 -target 8 -implicit:none -Xlint:-options -d "$B/classes" -s "$B/gen" -cp "$CP" \
  -sourcepath "$A/components/src:$A/common/src" -processorpath "$P:$A/lib/guava/guava-20.0.jar:$A/lib/json/json.jar" \
  -processor com.google.appinventor.components.scripts.ComponentDescriptorGenerator,com.google.appinventor.components.scripts.ComponentListGenerator \
  src/com/conto/notificacoes/*.java 2>&1 | grep -v "^Picked up" | grep -v "^Note:" || true
test -f "$B/classes/com/conto/notificacoes/LeitorNotificacoes.class"
java -cp "$P:$A/lib/json/json.jar" com.google.appinventor.components.scripts.ExternalComponentGenerator \
  "$B/gen/simple_components.json" "$B/gen/simple_components_build_info.json" "$B/extcomp" "$B/classes" "$B/deps" "$B/extclass" false 2>&1 | grep -v "^Picked" | grep -v "^$"
(cd "$B/extclass/com.conto.notificacoes" && jar cf ../com.conto.notificacoes.jar com)
cp "$B/extclass/com.conto.notificacoes.jar" "$B/extcomp/com.conto.notificacoes/files/AndroidRuntime.jar"
java -cp "$A/lib/android/tools/d8.jar" com.android.tools.r8.D8 --lib "$A/lib/android/android-34/android.jar" --min-api 21 \
  --output "$B/extcomp/com.conto.notificacoes/classes.jar" "$B/extclass/com.conto.notificacoes.jar" 2>&1 | grep -v "^Picked" | grep -v "was not found, it is required for default" | grep -v "^Warning in" || true
(cd "$B/extcomp" && zip -qrX "$B/out/com.conto.notificacoes.aix" com.conto.notificacoes)
unzip -l "$B/out/com.conto.notificacoes.aix" | tail -n +4 | head -n -2
