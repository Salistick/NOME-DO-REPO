# Histórico de mudanças

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
