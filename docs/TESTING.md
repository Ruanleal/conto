# Testes e qualidade

Este guia explica como o Contô é testado, o que cada verificação prova e o que ela não prova. Os números são da versão 2.0.1.

## Resumo

| Verificação | Ferramenta | Resultado |
|---|---|---|
| Bateria de testes | `tools/test_conto.py` | 60/60 testes, 110.043 verificações |
| Teste de mutação do app | `tools/mutants.py` | 413/413 defeitos plantados detectados (347 nos blocos, 66 na tela e nas imagens) |
| Regras da extensão | `extension/test/.../TesteRegras.java` | 45/45 verificações |
| Mutação das regras da extensão | `extension/mutar_regras.py` | 21/21 defeitos detectados |
| Verificadores estáticos | `tools/verificar.sh` | 0 erros; autotestes 38/38 e 28/28 |
| Contraste dos textos | teste T27 da bateria | 1.231 textos em 50 telas (20 no tema escuro); mínimo 4,55:1 |
| CSV real × simulador | `tools/diferencial_csv.py` | 533 escritas e 4.202 leituras comparadas; 12 diferenças conhecidas |
| Reprodutibilidade | `tools/gerar_aia.sh` | o `.aia` gerado tem os mesmos 172 arquivos de `app/Conto.aia` |

## Como os testes funcionam

### Simulador dos blocos

O App Inventor não tem uma forma oficial de rodar os blocos fora do celular. Por isso o projeto tem um simulador próprio (`tools/ai_sim.py`), que lê o `Screen1.bky` e o `Screen1.scm` do `.aia` e executa os blocos reais, com o comportamento dos componentes lido no código-fonte do App Inventor: TinyDB, Notifier, seletores de data e de arquivo, câmera, relógios, listas, textos, CSV e a extensão de notificações.

Os testes agem como uma pessoa usando o app: digitam, escolhem nos menus, tocam nos botões, respondem às confirmações, fecham e reabrem o app. Depois conferem o que aparece na tela e o que ficou gravado.

### Bateria de testes

`tools/test_conto.py` tem 60 testes, de T00 a T62. Eles cobrem, entre outros:

- valores com vírgula e centavos, salvar, editar, excluir e a persistência depois de fechar e reabrir;
- migração dos dados das versões antigas;
- histórico com período e busca, gráfico, limites, evolução, metas e lançamentos que se repetem;
- planilha, backup e restauração, importação de extrato sem duplicar;
- leitura e interpretação das notificações do banco e o religamento do leitor;
- tela: cada propriedade, método e evento usado existe no código oficial do App Inventor, nenhum texto em caixa alta, texto dos botões cabendo em três larguras de tela e com a fonte do sistema maior;
- contraste de todos os textos nas telas desenhadas, nos dois temas;
- nenhum erro de execução em nenhum app aberto durante a bateria.

### Teste de mutação

Um teste que nunca falha não prova nada. O teste de mutação (`tools/mutants.py`) planta um defeito de cada vez no app, por exemplo trocar uma conta, apagar um bloco ou mudar uma imagem, e roda a bateria. O defeito precisa ser pego por pelo menos um teste. Na v2.0.1 foram 413 defeitos, e a bateria pegou todos.

### Extensão

As regras da extensão estão em `Regras.java`, sem depender do Android, e por isso rodam numa JVM comum: `TesteRegras.java` faz 45 verificações e `mutar_regras.py` planta 21 defeitos nelas. Esses dois testes rodam a cada push no GitHub Actions. A bateria também confere que o simulador decide igual ao `Regras.java` em 600 notificações aleatórias.

### Verificadores estáticos

- `bkycheck.py` confere os blocos contra a tela: nomes, encaixes, tipos, variáveis em escopo e chamadas de procedimento.
- `scm_check.py` confere cada propriedade, arquivo, método e evento contra o código Java oficial do App Inventor.
- `mutate_check.py` e `mutate_scm.py` plantam defeitos para provar que os verificadores enxergam erros.

### CSV real × simulador

`tools/diferencial_csv.py` compara o CSV do simulador com o `CsvUtil` do próprio App Inventor, compilado do código-fonte oficial. As 12 diferenças conhecidas são campos com mais de 10 mil caracteres, que o `CsvUtil` recusa e o simulador aceita.

## Como rodar

Os comandos e as dependências de cada ferramenta estão em [`tools/README.md`](../tools/README.md) e [`extension/README.md`](../extension/README.md). As saídas completas da v2.0.1 estão no arquivo `relatorios-de-teste-v2.0.1.zip` da [Release v2.0.1](https://github.com/Ruanleal/conto/releases/tag/v2.0.1).

## Limites

- O simulador não é um Android. Ele reproduz o comportamento lido no código do App Inventor, mas não substitui o teste no celular.
- As telas são desenhadas a partir do `.scm` e podem diferir do aparelho: em alguns celulares o layout fica mais alto, porque as imagens de fundo definem uma altura mínima.
- O serviço que recebe as notificações só roda de verdade no Android. Fora dele, foram testadas as regras em Java e o comportamento do app no simulador.
- O teste de mutação completo leva horas. Ele rodou na v2.0.1 em 17/11/2026; na publicação, uma amostra rodou de novo com os arquivos deste repositório.
- Os nomes de pessoas nos dados de teste são fictícios.
