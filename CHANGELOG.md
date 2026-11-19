# Changelog

Todas as mudanças relevantes do Contô ficam registradas aqui. O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

## [2.0.1] - 2026-11-17

### Corrigido

- O leitor de notificações parava de receber notificações quando o Android (por exemplo, em celulares Xiaomi) desligava o serviço. Agora o app pede para religar o leitor ao abrir e ao tocar em **Atualizar**, o serviço pede para ser religado quando o sistema o desliga e, ao voltar, relê as notificações que ainda estão na barra, sem repetir as que já foram tratadas.
- "Fulano enviou um Pix para você" agora vira a entrada "Pix de Fulano". Antes, a descrição saía com o fim da notificação ("Pix para visualizar o pagamento").

### Adicionado

- Linha de diagnóstico no painel de notificações: se o leitor está ligado, quantas notificações ele viu e o que aconteceu com a última.
- Descrições "Fatura" e "Parcela" para notificações de pagamento de fatura e de parcelas.

### Problemas conhecidos

- O Android mostra a versão do app como 1.0 (ver [Limitações conhecidas](README.md#limitações-conhecidas)).

## [2.0] - 2026-11-16

### Adicionado

- Extensão **Leitor de notificações** (`com.conto.notificacoes`): lê as notificações dos apps de banco, mesmo com o app fechado, e sugere lançamentos para conferir (lançar, ignorar, lançar todos ou ignorar todas).
- Faixa no Lançar com quantas notificações esperam conferência.
- **Colar mensagem do banco**: o texto de uma notificação ou de um SMS preenche o lançamento para conferir.

### Alterado

- A importação de extrato não duplica o que já entrou pelas notificações, mesmo com a descrição diferente, e extratos que se sobrepõem só trazem as linhas novas.

## [1.9] - 2026-11-16

### Adicionado

- Foto do perfil pela câmera (**Tirar foto**), além da galeria.

### Alterado

- Gráfico: a pizza de entradas e despesas virou a rosca **Gastos por categoria**, com o total do período, as entradas, o saldo e uma cor fixa para cada categoria. A lista de categorias serve de legenda e mostra os limites.
- Evolução mais enxuta: o cartão da meta e o **Mês a mês**, com o resumo do mês escolhido.

## [1.8.1] - 2026-11-14

### Adicionado

- Confirmação ao excluir um lançamento, ao salvar uma edição e ao remover a foto.

### Corrigido

- Botões que apareciam vazios ou cortados no Android: setas ‹ ›, iniciais dos meses, "x" da busca e botões só de texto.
- Mudar a data de um lançamento para "hoje" não alterava a data.

## [1.8] - 2026-11-14

### Adicionado

- **Importar extrato do banco** (CSV): encontra as colunas pelo nome, entende datas e valores em vários formatos, sugere a categoria pela descrição e não duplica lançamentos.
- **Metas de economia**, com progresso, quanto guardar por mês e previsão pelo ritmo dos últimos 3 meses.
- Campo de data no Lançar, para registrar dias passados.
- Data do último backup e lembrete de backup.

### Alterado

- **Seus dados** virou uma lista com ícones, e o Lançar e a Evolução ganharam visual novo.

## [1.7] - 2026-11-13

### Adicionado

- Aba **Evolução**: resumo do mês comparado com o mês anterior, mês a mês, saldo acumulado e ano a ano.
- Período **Mês | Ano | Tudo** no Histórico e no Gráfico.
- Busca no Histórico, sem diferença de maiúsculas e acentos.
- Edição de lançamentos.
- Limites por categoria, com aviso ao lançar.
- **Repetir todo mês** (aluguel, salário).
- Exportar planilha (CSV), fazer e restaurar backup.

## [1.6] - 2026-11-12

### Adicionado

- Gastos por categoria no Gráfico.
- Tema claro e escuro.
- Perfil com nome e foto, e saudação no cabeçalho.

## [1.5] - 2026-11-12

### Adicionado

- Ícone em cada categoria e em cada forma de pagamento.
- Resumo dos últimos lançamentos abaixo do gráfico.

### Alterado

- Erros de preenchimento aparecem em vermelho logo abaixo do campo, e o aviso de sucesso vira uma faixa verde que some sozinha.

## [1.4] - 2026-11-11

### Alterado

- Redesenho completo: cabeçalho com saldo, abas em formato de pílula, cartões, histórico em cartões, tipografia Manrope e ícone próprio.
- Gráfico com cores que têm significado (entradas em verde, despesas em vermelho) e legenda com valores e porcentagens.

## [1.3] - 2026-11-11

### Corrigido

- Categoria e forma de pagamento passam a ser escolhidas de forma independente.
- Valores com vírgula e centavos (15,90 e 1.250,99).
- Despesas e entradas são salvas, aparecem no histórico e entram nos totais.
- Os lançamentos continuam lá depois de fechar e reabrir o app, e os dados da versão anterior são migrados.

## [1.2]

- Versão original do projeto.

[2.0.1]: https://github.com/Ruanleal/conto/releases/tag/v2.0.1
