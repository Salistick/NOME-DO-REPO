# TTS Live

Aplicativo Windows que acompanha chats da Twitch, YouTube e Kick e transforma comandos em voz usando Amazon Polly. A interface permite selecionar plataformas, saída de áudio e credenciais AWS.

## Compatibilidade

| Forma de uso | Requisitos |
| --- | --- |
| Executável ou instalador | Windows de 64 bits; não exige instalar Python. |
| Código-fonte | Windows, Python 3.12 ou 3.13 e dependências deste repositório. |
| Voz e plataformas | Internet, saída de áudio disponível, conta AWS com acesso ao Polly e configuração das plataformas usadas. |

O pacote foi validado localmente no Windows 11 de 64 bits com Python 3.13.15. As dependências também tiveram seus wheels Windows Python 3.12 verificados; isso não equivale a testar o aplicativo em todas as máquinas. Outras versões do Windows e dispositivos ARM não foram validados. Linux e macOS não são suportados pela versão atual.

Ao mudar de PC ou perfil Windows, faça login e configure o Polly novamente se necessário. As credenciais criptografadas não são automaticamente portáveis entre usuários ou computadores.

## Melhorias de confiabilidade

- Filas limitadas e espera por capacidade antes de solicitar mais sínteses ao Polly.
- Pausa, prioridade e cancelamento protegidos contra concorrência; erros AWS não encerram o worker.
- Tokens protegidos pelo Windows, configurações gravadas atomicamente e recuperação explícita.
- Bloqueio de instância antes de carregar/migrar credenciais e reconexões sem duplicar monitores.
- Leitura autenticada do YouTube por API oficial, dependências fixadas com hashes e checks automatizados.

A validação local passou **138 testes**, abertura do executável e um ciclo isolado de instalação, upgrade e desinstalação com preservação de dados. Contas reais e síntese paga não foram usadas nesses testes.

## Executar pelo código

Requer Windows, Python 3.12 ou 3.13 e uma saída de áudio disponível. Na pasta do repositório, execute no PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe app.py
```

Preencha o `.env` apenas para as plataformas que usarão login. O callback cadastrado no aplicativo de cada plataforma deve ser idêntico ao respectivo `*_REDIRECT_URI`. A leitura pública por canal está disponível sem OAuth; respostas no chat dependem de autenticação/configuração do remetente.

Na primeira execução, configure o Amazon Polly pelo assistente. Ele oferece chave de acesso e AWS SSO; perfis AWS locais existentes também são suportados pelo armazenamento. O Polly é um serviço pago: o custo depende do uso e da conta AWS. Login, listagens e validação AWS rodam em segundo plano; cancelar impede que uma operação atrasada salve credenciais.

Tokens das plataformas e segredos do `.env` são protegidos pelo Windows para o usuário atual. Na migração, os valores secretos do `.env` viram referências e passam para `data/platform_secrets.bin`; o original exato fica criptografado em `data/env_original.bin`. Os arquivos de tokens mantêm os nomes `.json` por compatibilidade, mas seu conteúdo passa a ser protegido. Falha ao descriptografar gera erro explícito, sem substituir a conta por um cache vazio.

Para alterar um segredo, substitua sua referência no `.env` pelo novo valor; ele será protegido na próxima abertura. Para desativá-lo, deixe a atribuição vazia, como `TWITCH_BOT_ACCESS_TOKEN=`. Remover apenas o arquivo `.env` não apaga os valores já guardados no armazenamento protegido.

## Comandos de chat

| Comando | Comportamento |
| --- | --- |
| `!ms mensagem` | Enfileira fala pública, respeitando permissões, cooldown e limite de palavras da plataforma. |
| `!mm mensagem` | Fala administrativa com prioridade. |
| `!pause`, `!resume`, `!stop` | Pausa, retoma ou cancela a fila. Falas administrativas podem ultrapassar a pausa. |
| `!rate 2.5` | Define o intervalo geral entre áudios, em segundos. |
| `!time 5` | Define o cooldown por usuário na plataforma de origem. |
| `!len 20` | Define o limite de palavras da plataforma de origem. |
| `!modosub` | Alterna o modo restrito a assinantes e administradores na plataforma. |
| `!config` | Mostra a configuração atual. |
| `!lives`, `!live1`, `!clive1`, `!ytoff` | Lista contas YouTube, seleciona, remove uma conta salva ou desliga o monitoramento. |

Exceto `!ms`, os comandos exigem broadcaster ou moderador. Remover uma conta pelo `!cliveN` apaga sua autenticação local.

Cada etapa da fila admite até 100 itens pendentes, reservando uma vaga para prioridade administrativa. Mensagens normais adicionais são descartadas quando a etapa de síntese está cheia. A síntese aguarda capacidade de reprodução antes de pedir mais áudio ao Polly. A entrada é limitada a 1.000 caracteres e o nome a 100 antes das conversões; o texto normal sanitizado continua limitado a 220 caracteres.

## Dados e diagnóstico

Os dados ficam em `data/`, ao lado do código ou executável: contas, configurações, pronúncias, áudios temporários e logs. O log principal é `data/logs/app.log`; atualizações usam `updater.log` e `installer.log` nessa pasta. Faça backup de `data/` e `.env` antes de migrar a instalação. A desinstalação preserva dados e configurações criados durante o uso.

O app bloqueia uma segunda instância na mesma pasta de dados; o Windows libera o bloqueio mesmo se o processo cair. Para uma execução isolada, defina `TTSLIVE_DATA_DIR` com o caminho da pasta desejada antes de abrir o aplicativo.

## Recuperar credenciais

Feche o app e use o mesmo perfil Windows que protegeu os arquivos. Um backup criptografado não garante recuperação em outro usuário ou computador; nesse caso pode ser necessário autenticar novamente.

Quando um cache legado é migrado, uma cópia protegida recebe o sufixo `.migration.bak`. A recuperação é explícita e não revela os valores. Pelo código:

```powershell
.\.venv\Scripts\python.exe app.py --recover-token twitch --data-dir .\data
.\.venv\Scripts\python.exe app.py --recover-env --data-dir .\data
```

No executável, use `TTSLive.exe` com os mesmos argumentos. `--recover-token` aceita `twitch`, `youtube` ou `kick`. Esses comandos funcionam antes do carregamento da configuração e recusam alterar dados de uma instância aberta. Backups de migração não existem necessariamente para contas cadastradas depois; mantenha seu próprio backup protegido ou faça login novamente. Esquecer uma conta também remove seus tokens da cópia de recuperação.

O Polly salva configuração e segredo juntos em `data/aws_polly_credentials.bundle.bin`, com troca atômica. Na migração, os arquivos antigos são preservados. Para recuperar explicitamente esse par legado pelo código, use `PollyCredentialStore().recover_legacy_configuration()`; a versão substituída fica em `.bundle.bin.recovery.bak`. Uma configuração nova também pode ser validada pelo assistente antes de substituir um bundle inacessível.

## Testes e análise

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe benchmarks/benchmark_message_store.py
```

Os testes simulam rede, AWS e reprodução; não precisam de contas nem enviam mensagens. A proteção de credenciais é testada com DPAPI real e valores fictícios. O benchmark compara o cache atual à revisão original `cbe66c8`, com gravações desabilitadas apenas durante a medição. A análise completa e as limitações estão em [ANALISE.md](ANALISE.md).

Para validar as plataformas com contas e áudio reais, siga [TESTES_INTEGRACAO.md](TESTES_INTEGRACAO.md).

Dependências diretas são mantidas nos arquivos `requirements*.in`; os `.txt` incluem versões transitivas fixadas e hashes. Para regenerar os locks e validar, execute `build_scripts/refresh_dependency_locks.ps1`. O repositório inclui configuração do Dependabot para propor atualizações semanais, sujeitas aos checks.

## Build e atualização

Execute `build_exe.bat`, ou `build_scripts/build_windows.ps1`, para gerar um build em pasta exclusiva; o script informa o caminho final. O script executa testes e verifica o executável gerado com GUI, proteção de credenciais e bloqueio de segunda instância, sem áudio ou rede. Para compilar o instalador local, passe `-InnoCompiler` com o caminho de `ISCC.exe`. O workflow Windows também faz essa validação e usa Inno Setup 6.7.4 com hash e assinatura do fornecedor verificados. O smoke de build não instala o aplicativo.

O modo `TTSLiveValidationBuild` do instalador exige pasta explícita, usa identidade própria e desativa atalhos, registro de desinstalação e execução automática. Nesta revisão, variantes desse modo passaram por instalação, upgrade e desinstalação em `build_validation/`, preservando os arquivos de dados fictícios. O instalador normal do usuário não foi executado nesse ciclo.

A assinatura digital do TTS depende dos secrets `WINDOWS_CODESIGN_CERT_BASE64` e `WINDOWS_CODESIGN_CERT_PASSWORD`, com timestamp opcional em `WINDOWS_CODESIGN_TIMESTAMP_URL`. Um build local sem esses certificados permanece sem assinatura de editor.

O atualizador roda somente no executável Windows. Releases estáveis devem usar tags numéricas como `v1.2.3`, incluir `TTSLiveInstaller.exe` e publicar tamanho e digest SHA-256 válidos na API do GitHub. O download é verificado antes de executar. Releases sem digest, versões de desenvolvimento e prereleases não são instaladas automaticamente. Tentativas com falha são preservadas para diagnóstico por sete dias. A limpeza só remove diretórios marcados pelo próprio atualizador, preservando conteúdo desconhecido, links e pastas antigas sem marcador.

A leitura autenticada do YouTube usa REST oficial, respeitando `pollingIntervalMillis`, e prioriza descoberta/revalidação oficial. Falhas de API, quota ou permissões podem usar leitura pública como fallback; sem login, o caminho público continua necessário. A leitura Kick ainda usa Pusher: sua alternativa oficial exige um webhook publicamente acessível e infraestrutura externa.
