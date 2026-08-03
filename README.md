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

## Amazon Polly

Na primeira inicializacao sem configuracao salva, o app solicita uma conta AWS do usuario para usar o Amazon Polly. As credenciais do Polly nao sao mais obrigatorias no `.env`.

O modo principal e `Configurar facil`. O app abre o AWS CloudShell no navegador padrao, copia um comando pronto que cria um usuario IAM dedicado com permissao minima para Polly, e o usuario cola o resultado no app.

Tambem existem alternativas avancadas: login AWS via IAM Identity Center ou chave IAM ja existente. Quando chave IAM e usada, o segredo fica protegido no Windows pelo usuario logado e a configuracao fica em `data/aws_polly_config.json`.

Fluxo simples:

1. Clique em `Abrir AWS CloudShell`.
2. Faca login na AWS.
3. Volte ao bot e clique em `Copiar comando`. Ele copia varias linhas de codigo de uma vez.
4. No AWS CloudShell, clique no terminal preto, cole com `Ctrl+V` e pressione Enter.
5. Espere o comando terminar. No final aparece uma linha com `AKIA...` e uma chave secreta.
6. Copie somente essa linha final das credenciais. Nao copie os comandos, o simbolo `$` nem textos acima.
7. Cole essa linha no app e clique no botao verde `Salvar e testar`.

Se a copia automatica falhar, use este comando no AWS CloudShell:

```bash
aws iam create-user --user-name TTSLivePollyBot 2>/dev/null || true
aws iam put-user-policy --user-name TTSLivePollyBot --policy-name TTSLivePollySynthesizeSpeechOnly --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"polly:SynthesizeSpeech","Resource":"*"}]}'
for key in $(aws iam list-access-keys --user-name TTSLivePollyBot --query 'AccessKeyMetadata[].AccessKeyId' --output text); do aws iam delete-access-key --user-name TTSLivePollyBot --access-key-id "$key"; done
aws iam create-access-key --user-name TTSLivePollyBot --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text
```

Permissao minima recomendada para a chave IAM:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "polly:SynthesizeSpeech",
      "Resource": "*"
    }
  ]
}
```

## Configuracao por plataforma

Os comandos `!len`, `!time`, `!modosub` e `!config` usam a plataforma de origem da mensagem.

Exemplo: `!modosub` enviado na Twitch altera somente a Twitch. O mesmo comando enviado no YouTube altera somente o YouTube.

O comando `!rate` e geral, pois existe uma unica fila de audio compartilhada entre as plataformas.
