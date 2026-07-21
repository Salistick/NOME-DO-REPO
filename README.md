Bot desktop em Python para monitorar chats da Twitch, YouTube e Kick com integracao de TTS usando Amazon Polly.

## Sanitizacao e pronuncia do TTS

O default do projeto fica versionado em `assets/tts_pronunciations.default.json`.

Na primeira execucao, o bot cria uma copia local em `data/tts_pronunciations.json`. Essa copia local fica fora do Git e permite ajustar pronuncias sem alterar codigo.

Estrutura basica:

```json
{
  "single_words": {
    "gg": "g g",
    "lol": "risos"
  },
  "phrases": {
    "poke x games": "poke x games"
  }
}
```

Para depurar o texto antes do Polly, defina `TTS_DEBUG_SANITIZER=1` no `.env`. O log mostrara texto original, texto limpo, texto normalizado e SSML final.

## Configuracao por plataforma

Os comandos `!len`, `!time`, `!modosub` e `!config` usam a plataforma de origem da mensagem.

Exemplo: `!modosub` enviado na Twitch altera somente a Twitch. O mesmo comando enviado no YouTube altera somente o YouTube.

O comando `!rate` e geral, pois existe uma unica fila de audio compartilhada entre as plataformas.
