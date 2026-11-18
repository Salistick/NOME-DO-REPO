# Histórico de mudanças

## v1.3.0 — 2026-11-17

- Donos de live e moderadores podem usar `!skip` para interromper a fala atual de `!ms` ou `!mm`, inclusive durante o carregamento do áudio.
- O comando preserva as demais mensagens da fila e libera a próxima fala elegível sem esperar o intervalo de `!rate`.

[Comparação completa com v1.2.3](https://github.com/Salistick/NOME-DO-REPO/compare/v1.2.3...v1.3.0).

## v1.2.3 — 2026-11-17

- Os comandos `!ms` e `!mm` usam pausas de 10 ms na vírgula, 20 ms no ponto e vírgula e nos dois-pontos, 30 ms entre frases, 40 ms nas reticências e 60 ms entre parágrafos.
- O último sinal de pontuação mantém a entonação da voz sem acrescentar uma pausa programada ao fim da mensagem.

[Comparação completa com v1.2.2](https://github.com/Salistick/NOME-DO-REPO/compare/v1.2.2...v1.2.3).

## v1.2.2 — 2026-11-16

- O OAuth da Twitch, do YouTube e da Kick aceita o retorno apenas pela interface local, valida o `state` e rejeita redirecionamentos nas requisições de token. Use um callback HTTP com `localhost`, `127.0.0.1` ou `[::1]` e o caminho registrado na plataforma.
- Os logs deixam de incluir o e-mail e o ID da conta do YouTube e o conteúdo das respostas de erro nas rotas de autenticação. O IRC da Twitch exige TLS 1.2 ou superior.
- O atualizador consulta os metadados diretamente no endpoint de releases do GitHub. Variantes locais de `.env` são ignoradas pelo Git.
- As Actions são fixadas por SHA e a permissão de escrita fica restrita ao job de publicação. Foram atualizados boto3, botocore, pip, Ruff, checkout, setup-python e upload-artifact.

[Comparação completa com v1.2.1](https://github.com/Salistick/NOME-DO-REPO/compare/v1.2.1...v1.2.2).

## v1.2.1 — 2026-11-06

- Os comandos `!ms` e `!mm` usam novas pausas de locução para vírgula (200 ms), ponto e vírgula e dois-pontos (400 ms), ponto final, interrogação e exclamação (600 ms) e reticências `…` ou `...` (750 ms).
- Uma linha em branco marca a mudança de parágrafo e gera uma única pausa de 1 segundo, mesmo após outra pontuação. A pausa entre parágrafos é preservada ao limitar o número de palavras.

[Comparação completa com v1.2.0](https://github.com/Salistick/NOME-DO-REPO/compare/v1.2.0...v1.2.1).

## v1.2.0 — 2026-10-29

Reúne as melhorias de confiabilidade, proteção de credenciais e distribuição implementadas desde a v1.1.12.

### Aplicativo

- Filas limitadas, controle de capacidade e recuperação do worker após erros do Amazon Polly.
- Correções de concorrência ao pausar, retomar, cancelar falas e reconectar as plataformas.
- Limpeza de arquivos de áudio e fechamento dos recursos de reprodução.
- Interface de configuração do Polly com operações de rede em segundo plano e cancelamento seguro.
- Leitura autenticada do YouTube pela API oficial, respeitando os intervalos de consulta, com fallback público.
- Tratamento mais robusto de mensagens e permissões na Twitch e na Kick; cache de mensagens otimizado.

### Dados e atualização

- Gravação atômica e validação das configurações.
- Proteção de tokens e segredos pelo Windows, com migração e recuperação explícita.
- Configuração e credenciais do Polly salvas juntas em um bundle atômico.
- Bloqueio de segunda instância antes do carregamento e da migração dos dados.
- Validação de versão, URL, tamanho e SHA-256 antes de instalar uma atualização.
- Limpeza restrita aos arquivos temporários identificados pelo próprio atualizador e preservação dos dados na desinstalação.

### Build e documentação

- Correção do YAML que impedia a execução dos workflows de build e publicação.
- Validação independente dos workflows com actionlint.
- Dependências fixadas com hashes e preservação dos pacotes Windows quando o Dependabot regenera os locks no Linux.
- Build Windows com testes antes do empacotamento e smoke test offline do executável.
- README atualizado, análise técnica e roteiro de testes de integração.

### Validação e migração

- 142 testes automatizados, com checks no Windows usando Python 3.12 e 3.13.
- Build do EXE e do instalador validado pelo GitHub Actions; ciclo local isolado de instalação, upgrade e desinstalação com preservação de dados.
- Contas reais das plataformas e síntese paga do Polly não foram usadas na validação automatizada.
- Faça backup de `data/` e `.env` antes de atualizar. Credenciais protegidas pelo Windows podem exigir novo login ao mudar de usuário ou computador.

[Comparação completa com v1.1.12](https://github.com/Salistick/NOME-DO-REPO/compare/v1.1.12...v1.2.0).
