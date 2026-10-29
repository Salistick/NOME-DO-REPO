# Análise técnica — TTS Live

Revisão iniciada em 28/10/2026, baseada no clone de `Salistick/NOME-DO-REPO`, commit `cbe66c8`. As alterações foram preparadas na branch `codex/review-improvements`; sua publicação é registrada no histórico Git e no pull request correspondente. Não foram alteradas contas de plataformas nem publicada uma release do aplicativo.

As sugestões foram tratadas em uma segunda rodada em **29/10/2026**. Os resultados e os limites atualizados estão abaixo. Snapshot de segurança do código salvo em `../backups/tts-before-followup-20261028-230057.zip`.

## Escopo e avaliação

Foram revisados os módulos de inicialização, interface, configuração, logging, atualização, build/instalação, Twitch, YouTube, Kick, TTS, credenciais e deduplicação, além dos assets/configurações versionados. A revisão combinou leitura de código, análise estática e testes com serviços simulados. Ela não comprova funcionamento dos endpoints externos nem ausência de todos os defeitos.

A separação entre plataformas, síntese e reprodução é uma boa base. O maior ganho possível nesta revisão estava em confiabilidade: uma exceção podia encerrar um worker, reconexões podiam manter threads antigas, e filas ilimitadas antecipavam sínteses pagas sem capacidade de reprodução. O projeto também não tinha suíte de testes e seu README não explicava a instalação.

Fluxo principal: **chat da plataforma → normalização/deduplicação → autorização/comando → sanitização → fila de síntese Polly → fila de reprodução pygame**. Configurações e contas são mantidas em arquivos locais.

## Problemas corrigidos

P1 indica risco de perda de funcionamento, permissões incorretas ou efeitos destrutivos. P2 indica problemas de robustez, consumo ou comportamento que também merecem correção.

| Prioridade | Antes | Correção e arquivos principais |
| --- | --- | --- |
| P1 | Erros de serviço/conexão da AWS escapavam do worker e podiam interromper todo TTS posterior. | Tratamento de `ClientError`/`BotoCoreError`, com teste de recuperação. `services/tts/tts_manager.py`. |
| P1 | Filas sem limite podiam acumular memória, disco, atraso e sínteses pagas. | Até 100 itens pendentes por etapa, vaga administrativa e espera por capacidade antes de sintetizar. `tts_manager.py`, `audio_player.py`. |
| P1 | `!stop` seguido de retomada podia ressuscitar síntese ou áudio já selecionado; pausa após seleção podia ser ignorada. | Gerações de cancelamento, preservação da tarefa pausada e descarte de arquivos obsoletos. `tts_manager.py`, `audio_player.py`. |
| P1 | Parar/reconectar esquecia threads ainda vivas; resolução de canal podia terminar depois do cancelamento. | Referências mantidas até o término, verificações de cancelamento e status de encerramento. Bots/monitores das três plataformas. |
| P1 | Badges com substrings como `non-subscriber` ou `model` podiam corresponder a permissões da Kick. | Correspondência explícita de roles e assinatura ativa. `kick_pusher_event_mapper.py`. |
| P1 | JSON Kick válido mas não objeto podia encerrar o monitor. | Validação de formato antes do processamento. `kick_pusher_client.py`. |
| P1 | O comando guiado AWS apagava todas as access keys do usuário IAM do bot antes de criar outra. | Removida revogação automática; se não houver capacidade para outra chave, a criação falha preservando as existentes. `polly_setup_dialog.py`. |
| P2 | Cancelar seleção SSO podia sobrescrever o segredo salvo anteriormente. | Login SSO permanece pendente até confirmar conta e role. `polly_credentials.py`. |
| P2 | JSON era sobrescrito diretamente, com risco de truncamento; alterações de contas podiam competir. | Temporários exclusivos, flush/fsync e troca atômica; locks nos caminhos concorrentes. Stores de estado, TTS, tokens e YouTube. |
| P2 | Estado/configuração com formato inesperado ou NaN/Infinity podia falhar na inicialização ou nos comandos. | Normalização de tipos e validação de números finitos. `app_state.py`, `tts_state.py`, `tts_manager.py`. |
| P2 | Áudio parcial, rejeitado ou cancelado podia ficar órfão; stream Polly não era fechado explicitamente. | Fechamento de streams, remoção de parciais e descarte/limpeza das filas. `polly_client.py`, `audio_player.py`. |
| P2 | Deduplicação movia IDs sem atualizar timestamp, invalidando poda; cooldown tinha corrida entre threads. | TTL ordenado e verificações/marcações sob lock e relógio monotônico. `message_dedupe.py`, `tts_manager.py`. |
| P2 | IRC perdia caracteres UTF-8 fragmentados; remetente separado não consumia PING. | Decoder incremental, envio serializado, rejeição de CRLF e leitor para keepalive. `twitch_irc.py`, `twitch_sender.py`. |
| P2 | VIP/mod assinante podia perder atributo de assinatura; envio podia indicar sucesso sem envio real. | Flags independentes e retorno real de falha dos remetentes. `twitch_bot.py`, `kick_chat_sender.py`. |
| P2 | Monitor público YouTube substituía `signal.signal` globalmente; responses HTTP podiam ficar abertas. | Uso de `interruptable=False` do pytchat e fechamento de responses. Monitores YouTube. |
| P2 | Descoberta de live era repetida imediatamente após não encontrar resultado. | Uma descoberta por ciclo, respeitando nova tentativa. `youtube_bot.py`. |
| P2 | Cache YouTube reconstruía índices de até 5.000 mensagens a cada nova mensagem com janela cheia. | `deque` e índice por objeto; remoção incremental O(1), snapshots protegidos e deduplicação no lote. `youtube_message_store.py`. |
| P2 | Conversões ocorriam antes do corte de tamanho, permitindo tokens numéricos gigantes. | Entrada bruta limitada a 1.000 caracteres e nome a 100; saída normal de 220 mantida. Pronúncias customizadas são texto literal no SSML. `text_sanitizer.py`. |
| P2 | Updater não validava digest/tamanho, usava temporário previsível e parsing permissivo de versão. | SHA-256 e tamanho exatos, URL da release, diretório exclusivo, versão numérica, bloqueio de expansões de batch e parada limitada em falha. `auto_updater.py`. |
| P2 | Erros de workers criavam janelas Tk fora da thread principal; falha parcial de inicialização não limpava tudo. | Fila de avisos consumida pela GUI e encerramento de serviços já construídos. `app.py`, `launcher_gui.py`. |
| P2 | Falha ao salvar geometria podia impedir fechamento; botões eram redesenhados sem mudança. | Salvamento isolado do encerramento e redraw só quando necessário. `launcher_gui.py`. |
| P2 | Desinstalação removia todo o diretório, incluindo dados e `.env`. | Removida regra ampla; Inno remove arquivos instalados e preserva dados do usuário. `installer.iss`. |

O SHA-256 esperado usa o campo `digest` da API oficial de [assets de releases do GitHub](https://docs.github.com/en/rest/releases/assets). Ele verifica integridade em relação ao arquivo publicado; assinatura de editor permanece opcional no build. Releases sem digest válido deixam de ser atualizadas automaticamente.

## Validação realizada

- **138 testes aprovados**, incluindo cancelamento durante síntese/resolução, threads concorrentes, permissões, UTF-8 fragmentado, corrupção de download, migração/recuperação de credenciais, falhas de gravação, cancelamento do assistente AWS e pré-processamento nativo do instalador.
- Ruff aprovado, compilação sintática dos módulos aprovada e `pip check` sem dependências quebradas.
- Interface principal e janelas Polly construídas com serviços simulados, sem conexão nem reprodução. DPAPI exercitado de fato com dados fictícios.
- Script PowerShell de assinatura analisado sintaticamente, sem executar operações de certificado.
- Checks adicionados para Python 3.12 e 3.13 no Windows; workflow de build testa antes de empacotar. Esses workflows ainda não foram executados remotamente.

Ambiente local: Windows, Python 3.13.15, dependências em `.venv`. Downloads com hashes das dependências foram verificados para wheels Windows Python 3.12 e 3.13; isso não equivale a executar o app no Python 3.12. O executável completo gerado por PyInstaller passou teste real de abertura, GUI, DPAPI com fixture e bloqueio de segunda instância em pasta isolada. Variantes isoladas do instalador passaram por instalação, upgrade e desinstalação; serviços reais não foram usados.

### Medição do cache

Execute `python benchmarks/benchmark_message_store.py`. Compara commit original com implementação atual: três repetições, mediana, 1.000 inserções numa janela cheia de 5.000 mensagens. Gravações ficam desabilitadas durante inserções nas duas versões.

| Implementação | Mediana |
| --- | ---: |
| Original `cbe66c8` | 773,584 ms |
| Atual | 1,394 ms |

Nesse recorte em memória, a melhora foi de aproximadamente **555 vezes**. O resultado varia por máquina e não representa aceleração equivalente do aplicativo inteiro, da rede, do Polly ou da reprodução.

## Resultado das sugestões em 29/10/2026

| Sugestão | Resultado |
| --- | --- |
| Proteger tokens OAuth e segredos do `.env`. | **Implementado.** `secure_storage.py` usa DPAPI por usuário Windows; caches Twitch/YouTube/Kick migram com backup criptografado. `secret_config.py` preserva a semântica do dotenv, incluindo duplicatas, interpolação, BOM e CRLF; segredos saem do `.env` e seu original exato fica protegido. Recuperação explícita disponível também no executável. |
| Tirar rede AWS da janela de configuração. | **Implementado.** Login, listagens de contas/roles, validação e salvamento rodam em workers; resultados chegam ao Tk por fila. Cancelamento e gerações descartam respostas obsoletas e impedem salvamento tardio. |
| Transação conjunta Polly. | **Implementado.** Um bundle protegido contém versão, revisão, configuração e segredo; uma única troca atômica confirma tudo. Verificação de leitura antecede a gravação. Comparação de revisão impede um refresh SSO antigo de sobrescrever uma troca de conta. Migração preserva o par antigo e recuperação é explícita. |
| Bloquear múltiplas instâncias. | **Implementado.** `single_instance.py` mantém lock do sistema operacional por pasta durante toda a execução, adquirido antes da migração da configuração no bootstrap. Testes incluem segundo processo, liberação após queda e ordem de aquisição antes do carregamento de credenciais. |
| Fixar dependências e preparar atualizações verificadas. | **Implementado.** Runtime/build/dev têm versões transitivas e hashes; scripts regeneram locks e rodam checks. Dependabot semanal e CI Windows 3.12/3.13 estão configurados nos arquivos versionados do repositório. |
| Reduzir endpoints não oficiais. | **Melhorado no YouTube.** Descoberta e revalidação autenticadas priorizam APIs oficiais; monitor autenticado usa REST `list` documentado, removendo tentativa de `/stream` não documentada. O intervalo oficial de polling é respeitado. Leitura pública continua como fallback e para uso sem login. Na Kick, substituir Pusher por eventos oficiais depende de um webhook público e infraestrutura ainda não configurados. |
| Testar build/instalador/assinatura. | **Build e ciclo isolado concluídos.** PyInstaller e Inno geraram os artefatos; smoke e recuperação passaram no EXE. Variantes de teste 0.0.1/0.0.2, sem registro/atalhos/Run e com identidade própria, instalaram e atualizaram em pasta exclusiva; hashes de `.env` e dados fictícios foram preservados. A desinstalação removeu o EXE e preservou esses dados. Testes nativos verificam que `[Files]` e `[UninstallDelete]` são os mesmos do instalador normal. O fluxo completo do auto-updater de produção e a assinatura do TTS não foram executados. |
| Consolidar persistência atômica. | **Implementado.** `persistence.py` centraliza gravação de bytes/JSON com serialização antecipada, temporário exclusivo, fsync e replace. Stores e pronúncias usam esse helper; `youtube_json.py` mantém import compatível. |
| Limpar temporários antigos. | **Implementado.** Retenção de sete dias, somente diretórios com marcador de propriedade do updater. Conteúdo inesperado, links, junctions e diretórios sem marcador são preservados; não há exclusão recursiva. |
| Testar contas reais e transmissão. | **Depende das contas de teste.** Nenhuma credencial real foi fornecida/configurada neste clone. Os testes e o executável de validação não enviam chat, não reproduzem áudio e não chamam Polly pago. |

A proteção por usuário segue a [API DPAPI da Microsoft](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata). Backups exigem um perfil capaz de descriptografá-los; reautenticação pode ser necessária ao trocar de computador/usuário. Não há fallback para texto em claro nem substituição automática por tokens antigos.

O YouTube autenticado usa [liveBroadcasts.list](https://developers.google.com/youtube/v3/live/docs/liveBroadcasts/list) e [liveChatMessages.list](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/list). O polling tem implicações de latência/cota e respeita o intervalo recebido. A alternativa oficial de eventos Kick exige um [webhook público](https://github.com/KickEngineering/KickDevDocs/blob/main/events/introduction.md) com [validação de assinatura](https://github.com/KickEngineering/KickDevDocs/blob/main/events/webhook-security.md); essa infraestrutura não pode ser substituída por uma conexão desktop local equivalente.

HTTP, OAuth e TLS ainda podem levar até seus timeouts para terminar. A parada pode retornar com worker encerrando; nova conexão aguarda esse término para evitar duplicação. O limite das filas não interrompe nem estorna uma chamada Polly que já foi enviada.

Não foram executados login real, envio de chat, síntese paga, reprodução de áudio, assinatura do TTS ou auto-update de produção. A instalação/upgrade/desinstalação usou somente variantes isoladas; o instalador normal do usuário não foi executado. `data/` e `build_validation/` pertencem apenas a este clone e estão ignorados pelo Git. O certificado válido conferido nesta rodada é do fornecedor do compilador Inno; isso não representa assinatura de editor do aplicativo TTS.

Artefatos finais: `build_validation/run-20261029-002/dist/TTSLive.exe` e `TTSLiveInstaller.exe`, ambos com aproximadamente 55,5 MB e sem assinatura de editor. O manifesto `build_validation/validation.json` registra hashes, versões, resultados, testes de recuperação e limites. O build final executou os 138 testes e validou o executável com o bloqueio antecipado no bootstrap.
