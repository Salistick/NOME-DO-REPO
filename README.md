# Bot Live

Bot desktop em Python para monitorar chats da Twitch e do YouTube com integracao de TTS usando Amazon Polly.

O ponto principal de execucao e o arquivo [app.py](/C:/Users/Salis/OneDrive/Documents/BOT/Bot_Live/app.py), que inicializa a GUI, os conectores de plataforma e o pipeline de audio.

## Recursos

- Conexao com Twitch via OAuth e IRC
- Conexao com YouTube via OAuth e monitoramento de live chat
- Leitura de mensagens com Amazon Polly
- GUI simples em Tkinter para ligar e desligar Twitch e YouTube
- Comandos via chat para controlar TTS e alternar lives do YouTube
- Cache local de autenticacao e configuracoes em `data/`

## Estrutura

```text
app.py                    # ponto de entrada
launcher_gui.py           # interface desktop
config.py                 # configuracoes globais e paths
app_state.py              # persistencia de estado simples
platforms/twitch/         # autenticacao, IRC e bot Twitch
platforms/youtube/        # autenticacao, resolver de live e bot YouTube
services/tts/             # TTS, sanitizacao de texto e player de audio
```

## Requisitos

- Python 3.13+
- Git
- Conta e credenciais Twitch
- Conta e credenciais Google/YouTube
- Credenciais AWS com acesso ao Amazon Polly

## Instalacao

```powershell
git clone https://github.com/Salistick/NOME-DO-REPO.git
cd NOME-DO-REPO
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Se o projeto ainda nao tiver `requirements.txt`, instale as dependencias que o codigo usa:

```powershell
pip install python-dotenv requests boto3 pygame pytchat yt-dlp
```

## Configuracao

Crie um arquivo `.env` na raiz do projeto com as chaves necessarias.

### Twitch

```env
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
TWITCH_REDIRECT_URI=
TWITCH_CHANNEL=
```

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
POLLY_VOICE_ID=Camila
POLLY_ENGINE=neural
POLLY_OUTPUT_FORMAT=mp3
POLLY_SAMPLE_RATE=24000
```

## Execucao

```powershell
python app.py
```

Ao iniciar:

- a GUI abre com os botoes de Twitch e YouTube
- a Twitch pode reconectar usando cache salvo
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
- `!live1`, `!live2`, ... - troca o monitoramento do YouTube
- `!clive1`, `!clive2`, ... - remove uma conta/live salva

## Seguranca

Arquivos sensiveis nao devem ser versionados.

Itens ignorados no projeto:

- `.env`
- `data/`
- `__pycache__/`

## Observacoes

- O projeto foi organizado para uso local/desktop.
- Tokens e configuracoes ficam persistidos em `data/`.
- O YouTube depende de live ativa para iniciar o monitoramento de chat.
- O TTS usa sanitizacao de texto para reduzir spam e melhorar a fala em PT-BR.

## Publicacao de alteracoes

```powershell
git add .
git commit -m "Sua mensagem"
git push
```
