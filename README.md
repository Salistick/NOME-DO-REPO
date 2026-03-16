# TTS Live

Bot desktop em Python para monitorar chats da Twitch e do YouTube com integracao de TTS usando Amazon Polly.

O ponto principal de execucao e o arquivo [app.py](/C:/Users/Salis/OneDrive/Documents/BOT/Bot_Live/app.py), que inicializa a GUI, os conectores de plataforma e o pipeline de audio.

## Recursos

- Conexao com Twitch via OAuth e IRC
- Monitoramento com uma conta Twitch e envio de mensagens com outra conta bot
- Conexao com YouTube via OAuth e monitoramento de live chat
- Leitura de mensagens com Amazon Polly
- GUI simples em Tkinter para ligar e desligar Twitch e YouTube
- Comandos via chat para controlar TTS e alternar lives do YouTube
- Cache local de autenticacao e configuracoes em `data/`

## Configuracao

Crie um arquivo `.env` na raiz do projeto com as chaves necessarias.

### Twitch

```env
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
TWITCH_REDIRECT_URI=
TWITCH_CHANNEL=
TWITCH_BOT_CLIENT_ID=
TWITCH_BOT_CLIENT_SECRET=
TWITCH_BOT_REDIRECT_URI=
TWITCH_BOT_LOGIN=
TWITCH_BOT_ACCESS_TOKEN=
TWITCH_BOT_REFRESH_TOKEN=
```

Na Twitch, a conta conectada pela GUI continua sendo a conta monitorada no chat. As mensagens enviadas pelo bot saem pela conta configurada nas variaveis `TWITCH_BOT_*`.

### YouTube

```env
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REDIRECT_URI=
```

### Amazon Polly

```env
AWS_REGION=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
POLLY_VOICE_ID=Ricardo
POLLY_ENGINE=neural
POLLY_OUTPUT_FORMAT=mp3
POLLY_SAMPLE_RATE=24000
```

Ao iniciar:

- a GUI abre com os botoes de Twitch e YouTube
- a Twitch pode reconectar usando cache salvo
- o chat monitorado na Twitch e o da conta conectada na GUI
- as respostas e comandos enviados na Twitch saem pela conta bot configurada no `.env`
- o YouTube pode reconectar usando a conta principal salva
- o TTS e iniciado uma vez e compartilhado entre as plataformas

## Comandos de chat

### Publicos

- `!ms mensagem` - envia uma mensagem para leitura normal

### Administrativos na Twitch

- `!mm mensagem` - leitura com prioridade
- `!rate X` - altera intervalo entre audios
- `!time X` - altera cooldown por usuario
- `!len X` - altera limite de palavras
- `!pause` - pausa o player
- `!stop` - limpa fila e interrompe o audio atual
- `!resume` - retoma o player
- `!modosub` - alterna modo apenas para subs/mods
- `!config` - mostra configuracao atual
- `!lives` - lista contas/lives salvas do YouTube
- `!ytoff` - desliga todo o monitoramento do YouTube
- `!live1`, `!live2`, ... - troca o monitoramento do YouTube
- `!clive1`, `!clive2`, ... - remove uma conta/live salva

## Observacoes

- O projeto foi organizado para uso local/desktop.
- Tokens e configuracoes ficam persistidos em `data/`.
- O YouTube depende de live ativa para iniciar o monitoramento de chat.
- O TTS usa sanitizacao de texto para reduzir spam e melhorar a fala em PT-BR.
