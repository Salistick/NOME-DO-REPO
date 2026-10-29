# Roteiro de validação com contas reais

Este roteiro complementa os testes automatizados. Nenhuma etapa com login, chat, reprodução ou Polly real foi executada nesta revisão. O build local e os testes isolados usam dados fictícios.

## Preparação

1. Escolha um canal de teste e configure os aplicativos OAuth das plataformas que serão usados, com os callbacks do `.env.example`.
2. Preencha o `.env` da instalação de teste. Na primeira abertura, seus segredos serão migrados para armazenamento protegido pelo Windows; não precisam ser compartilhados no chat.
3. Use uma pasta de dados exclusiva para o teste, definindo `TTSLIVE_DATA_DIR` antes de abrir o executável. Faça login nas plataformas pelo menu e configure sua conta Polly pelo assistente.
4. Selecione a saída de áudio. O botão **Testar** gera um sinal local; `!ms` e `!mm` usam Polly e podem gerar cobrança na conta configurada.

## Verificações

| Ação | Resultado esperado |
| --- | --- |
| Abrir novamente com a mesma pasta de dados. | Segunda instância bloqueada; a primeira continua funcionando. |
| Configurar credenciais AWS e cancelar durante login/listagem/validação. | Janela continua respondendo; resposta atrasada não salva a configuração cancelada. |
| Enviar `!ms teste de voz` no canal de teste. | Uma fala, com plataforma e remetente corretos. |
| Repetir antes de terminar o cooldown. | Segunda fala pública recusada. |
| Enviar comando administrativo com conta sem permissão. | Configuração não muda. |
| Pausar, enviar uma fala normal e depois `!mm prioridade` com moderador. | Fala normal aguarda; fala administrativa mantém prioridade. |
| Retomar após a pausa. | Fala normal preservada e tocada uma vez. |
| Enviar `!stop` enquanto há síntese e retomar depois. | Fala cancelada não reaparece. Uma chamada Polly já enviada pode terminar e cobrar. |
| Desconectar/reconectar durante tentativa de conexão. | Nenhum monitor duplicado nem mensagem lida duas vezes pelo mesmo ID. |
| Fechar e abrir novamente com o mesmo perfil Windows. | Contas e configurações recuperadas sem pedir todas as credenciais novamente. |
| Esquecer uma conta pelo menu. | Conta e tokens removidos, incluindo backup de migração correspondente. |
| Monitorar YouTube autenticado. | Descoberta/revalidação oficial e leitura do chat respeitam o intervalo de polling recebido. |
| Monitorar canal público sem autenticação. | Fallback público funciona enquanto o endpoint externo estiver disponível. |

## Evidências a registrar

Registre plataforma, horário, versão, resultado e trecho do log referente à falha. Não inclua tokens, chaves, códigos OAuth ou arquivos de credenciais. Os logs ficam em `data/logs/`, ou na pasta definida por `TTSLIVE_DATA_DIR`.

O webhook oficial da Kick exige infraestrutura pública adicional com validação de assinatura. O teste do cliente desktop atual não valida essa integração futura. Assinatura de editor também depende do certificado do responsável pelo projeto.
