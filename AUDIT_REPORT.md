# Relatório de revisão — HollyTranscrição 2.0.1

Revisão realizada em 8 de agosto de 2026 sobre a versão 1.0.0 original.

## Problemas corrigidos

| Área | Problema anterior | Correção em 2.0.0 |
|---|---|---|
| Segredos | Token do Hugging Face salvo em texto simples | Token mantido apenas em memória e preferência legada removida |
| Privacidade | Código oculto podia enviar trechos a uma URL de LLM | Integração removida do aplicativo e do pipeline |
| Dados | Resultados existentes eram sobrescritos | Nomes únicos e gravação atômica |
| Exportação | SRT podia ter numeração com lacunas | Contador independente de segmentos vazios |
| Markdown | Nome de arquivo podia quebrar o YAML | Valor serializado com escape seguro |
| Markdown | Locutores e correções podiam quebrar tabelas | Células escapadas |
| Conteúdo | Regras jurídicas eram aplicadas a qualquer áudio | Regras especializadas agora dependem do tipo de gravação |
| Processos | FFmpeg era resolvido somente na execução | Caminho explícito, sem shell e com erros limitados |
| Encerramento | Saída forçada podia deixar temporários | Fechamento bloqueado enquanto a transcrição trabalha |
| Compatibilidade | Logs presos ao caminho do macOS | Caminhos próprios para macOS, Windows e Linux |
| Dependências | WhisperX fixava PyTorch 2.8 | Faster-Whisper passou a atender o modo CPU |
| Estabilidade MLX | Uma falha nativa fechava toda a interface | Motor isolado em processo monitorado; a interface permanece aberta |
| Progresso | Download de modelo podia aparecer como "Finalizando" | Download ocorre antes da estimativa, com estado visual próprio |
| Cancelamento | Operações nativas bloqueantes exigiam encerramento forçado | Cancelamento encerra somente o processo protegido |

## Verificações automatizadas

- Compilação de todos os módulos Python.
- Ruff para qualidade, imports e padrões de segurança.
- Bandit para riscos comuns de segurança.
- Pytest para exportação, pós-processamento, identidade da interface e privacidade do token.
- Inicialização da interface em modo gráfico sem tela.

## Limitações conhecidas

- A separação de interlocutores depende de Pyannote/PyTorch, permanece opcional e possui uma cadeia de dependências maior.
- Em 8 de agosto de 2026, a auditoria do núcleo não encontrou vulnerabilidades conhecidas. O complemento de diarização ainda recebe um alerta no PyTorch 2.11; a correção exige PyTorch 2.13, mas ainda não existe uma versão correspondente do Torchaudio. Por isso ele não faz parte do build padrão e não deve ser distribuído em pacote público até a sincronização upstream.
- A primeira utilização baixa modelos de transcrição; o tamanho depende do modelo escolhido.
- O pacote macOS ainda precisa de assinatura e notarização para distribuição pública sem alertas do Gatekeeper.
- Windows, Linux e Mac Intel estão preparados no código, mas exigem testes reais e instaladores próprios antes de serem declarados estáveis.
