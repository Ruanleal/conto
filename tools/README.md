# Ferramentas

Scripts em Python que geram o projeto do Contô e o testam. Requerem Python 3, Pillow e numpy; para desenhar as telas, usam o Chromium pelo Playwright.

## Arquivos

**Geradores**

| Arquivo | Função |
|---|---|
| `tema.py` | Cores, fontes e medidas dos temas claro e escuro |
| `gen_assets.py` | Desenha as imagens do tema (botões, cartões, ícones) |
| `gen_scm.py` | Monta a tela (`Screen1.scm`) |
| `gen_conto.py` | Monta os blocos (`Screen1.bky`) e empacota o `.aia` |
| `gerar_aia.sh` | Roda os geradores e produz o `Conto.aia` |

**Simulador**

| Arquivo | Função |
|---|---|
| `ai_sim.py` | Executa os blocos do `.aia` como o App Inventor |
| `render_scm.py` | Desenha uma tela a partir do `.scm` e do estado do simulador |
| `preview_sim.py` | Roteiro das telas de exemplo usadas em `docs/screenshots/` |
| `foto_teste.py` | Gera fotos de teste desenhadas (nenhuma foto real) |
| `medir_contraste.py` | Mede o contraste dos textos nas telas |

**Testes e verificadores**

| Arquivo | Função |
|---|---|
| `test_conto.py` | Bateria de testes (60 testes) |
| `mutants.py` | Teste de mutação: planta defeitos no app, um por vez, e confere se a bateria pega |
| `bkycheck.py` | Verifica os blocos contra a tela (tipos, propriedades, eventos, variáveis, procedimentos) |
| `scm_check.py` | Verifica a tela, os arquivos e os blocos contra o código-fonte oficial do App Inventor |
| `mutate_check.py`, `mutate_scm.py` | Autotestes dos dois verificadores, com defeitos plantados |
| `tamanho_metodos.py` | Mede o tamanho de cada método compilado |
| `diferencial_csv.py` | Compara o CSV do simulador com o `CsvUtil` real do App Inventor |
| `verificar.sh` | Roda os verificadores e os autotestes num `.aia` |

## Como rodar

**Gerar o `.aia`**

```bash
bash tools/gerar_aia.sh <projeto_original_extraido> <pasta_fontes> <pasta_saida>
```

- `projeto_original_extraido`: o `.aia` original do Contô (versão 1.2), descompactado. Alguns blocos que não mudaram, como a navegação entre abas, são copiados dele.
- `pasta_fontes`: os pacotes npm `@expo-google-fonts/manrope` e `@expo-google-fonts/roboto` (versão 0.4.3).

O `.aia` gerado tem os mesmos 172 arquivos de `app/Conto.aia`, byte a byte.

**Verificadores**

```bash
APPINVENTOR=<appinventor-sources>/appinventor bash tools/verificar.sh app/Conto.aia
```

**Bateria de testes**

```bash
SP=<pasta de trabalho> python3 -I tools/test_conto.py app/Conto.aia
```

A pasta de trabalho precisa ter:

| Pasta | Conteúdo |
|---|---|
| `aia_original/` | O projeto original (versão 1.2), descompactado |
| `ai2src/repo/` | O repositório [appinventor-sources](https://github.com/mit-cml/appinventor-sources) |
| `ext/src/`, `ext/teste/` | Os códigos de `extension/src/` e `extension/test/` |
| `ext/extcomp/` | A extensão compilada (a pasta `extcomp` criada pelo `extension/build.sh`) |
| `fotos_teste/` | As fotos geradas por `foto_teste.py` |
| `final181/previas/rects.json` | Medidas das telas da v1.8.1, usadas num teste de comparação |

Variáveis opcionais: `ONLY` e `SKIP` (lista de testes, por exemplo `ONLY=T27,T59`), `REPORT`, `WORK_DIR` e `PREVIEW_DIR`.

**Teste de mutação**

```bash
SP=<pasta de trabalho> python3 tools/mutants.py app/Conto.aia
```

Usa a mesma pasta de trabalho da bateria e cria nela `mut_src18/` e `mut_app18/`. `JOBS` define quantos mutantes rodam ao mesmo tempo e `MUTANTES_SO` escolhe alguns (por exemplo `MUTANTES_SO=M01,S01`). A execução completa leva horas.

**CSV real × simulador**

```bash
python3 -I tools/diferencial_csv.py <pasta csv_java> <kawa.jar>
```

`csv_java` contém o `CsvUtil.java` e o `YailList.java` do App Inventor compilados; `kawa.jar` vem de `appinventor-sources/appinventor/lib/kawa/`.

Os resultados da v2.0.1 estão em [`docs/TESTING.md`](../docs/TESTING.md).
