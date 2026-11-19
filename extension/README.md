# Extensão Leitor de notificações (`com.conto.notificacoes`)

Extensão do MIT App Inventor que o Contô usa para ler as notificações dos apps de banco. Versão 1.1.

O App Inventor não tem bloco para ler notificações de outros apps. Esta extensão traz um `NotificationListenerService`, que o Android liga quando a pessoa libera o "Acesso a notificações" para o app, e um componente com os blocos que o app usa.

## Arquivos

| Caminho | Conteúdo |
|---|---|
| `com.conto.notificacoes.aix` | A extensão compilada. Ela já vem dentro do `app/Conto.aia`. |
| `src/com/conto/notificacoes/` | Código Java: `LeitorNotificacoes` (o componente), `ServicoNotificacoes` (o serviço do Android), `Armazem` (guarda no celular) e `Regras` (regras puras, testáveis fora do Android) |
| `test/com/conto/notificacoes/TesteRegras.java` | 45 verificações das regras, numa JVM comum |
| `mutar_regras.py` | Teste de mutação das regras: planta 21 defeitos, um por vez, e confere se o teste pega cada um |
| `build.sh` e `classpath.txt` | Compilação com as ferramentas do próprio App Inventor |

## Blocos

| Tipo | Nomes |
|---|---|
| Propriedades | `ApenasComValor` (padrão: ligado), `AppsMonitorados` (vazio = todos), `AppsIgnorados` |
| Eventos | `NotificacaoRecebida`, `Erro` |
| Métodos | `AcessoLiberado`, `AbrirConfiguracaoDeAcesso`, `AbrirInformacoesDoApp`, `Pendentes`, `QuantidadePendente`, `Remover`, `LimparTudo`, `NomeDoApp`, `Reconectar`, `LeitorConectado`, `Diagnostico` |

## Como funciona

1. Com o acesso liberado, o Android liga o `ServicoNotificacoes`, que recebe cada notificação, mesmo com o app fechado.
2. `Regras.filtro` descarta as notificações do próprio app, as de apps ignorados, os resumos de grupo, as sem texto e, com `ApenasComValor` ligado, as sem valor em R$.
3. As que passam vão para o `Armazem` (SharedPreferences, só no celular). Ele guarda até 300 pendentes; a mesma notificação de novo em menos de 10 minutos conta como repetida; e as 500 últimas já vistas não voltam quando o serviço relê a barra de notificações.
4. O app pega as pendentes com `Pendentes`, interpreta cada uma e mostra para a pessoa conferir antes de lançar.
5. Se o Android derrubar o serviço, ele pede para ser religado. Ao abrir, o app chama `Reconectar` e mostra o texto de `Diagnostico`.

Por padrão, `AppsIgnorados` lista apps de conversa, e-mail e redes sociais (WhatsApp, Telegram, Instagram, Messenger, Facebook, Gmail, Outlook, Discord, Snapchat, X, TikTok e LinkedIn): mensagens pessoais não são movimentação do banco.

## Compilar

```bash
APPINVENTOR=/caminho/appinventor-sources/appinventor PROC=/caminho/processadores bash build.sh
```

- `APPINVENTOR`: a pasta `appinventor` do repositório [mit-cml/appinventor-sources](https://github.com/mit-cml/appinventor-sources).
- `PROC`: as classes compiladas de `com.google.appinventor.components.scripts`, do mesmo repositório (o processador de anotações e o `ExternalComponentGenerator`).
- Requer Java 8 ou mais novo e `zip`. O `.aix` sai em `build/out/`.

## Testar

```bash
javac -d build/regras -cp json.jar \
  src/com/conto/notificacoes/Regras.java test/com/conto/notificacoes/TesteRegras.java
java -cp build/regras:json.jar com.conto.notificacoes.TesteRegras

JSON_JAR=json.jar python3 mutar_regras.py
```

`json.jar` é a biblioteca [org.json](https://github.com/stleary/JSON-java); o App Inventor traz uma cópia em `appinventor/lib/json/json.jar`. Os dois testes rodam a cada push no GitHub Actions.
