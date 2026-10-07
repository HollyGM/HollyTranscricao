# Relatório de revisão — HollyTranscrição 2.0.4

Revisão inicial realizada em 8 de agosto de 2026 sobre a versão 1.0.0 original. Nova revisão do código e das dependências em 2 de outubro de 2026.

## Atualização de 2 de outubro de 2026

- O aplicativo instalado estava na versão 2.0.3, build 4. As alterações locais existentes foram preservadas.
- A auditoria encontrou três vulnerabilidades conhecidas no urllib3 2.7.0: [CVE-2026-97687](https://github.com/urllib3/urllib3/security/advisories/GHSA-8988-9cw3-xx77), [CVE-2026-97688](https://github.com/urllib3/urllib3/security/advisories/GHSA-gh4c-6fx4-qh6g) e [CVE-2026-97689](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw). A atualização para 2.8.0 corrigiu os alertas. `pip check` e `pip-audit` passaram no ambiente atualizado.
- [MLX 0.32.3](https://github.com/ml-explore/mlx/releases/tag/v0.32.3) e MLX Metal 0.32.3 substituíram 0.32.2. O teste de operações Metal passou.
- Foram corrigidos cancelamento durante o startup, encerramento de subprocessos no macOS/Linux, limpeza de temporários pelo processo da interface, seleção de mídia durante uma operação, expansão de `~` no destino e metadados de redução de ruído.
- A interface deixou de executar o teste nativo de GPU antes de iniciar seu loop. A inferência permanece no processo protegido.
- A formatação de diarização foi corrigida para respeitar mudanças de locutor por palavra, quando existe alinhamento completo. O complemento Pyannote permanece fora do pacote padrão.
- Exportações simultâneas recebem nomes distintos por publicação atômica exclusiva, inclusive quando o destino não permite hardlinks no macOS. Testes verificaram que todos os resultados permanecem completos.
- Os 44 testes automatizados passaram, incluindo regressões de cancelamento, encerramento de descendentes, preservação de resultados simultâneos, diarização e interface. Ruff, Bandit (severidade média/alta), compilação Python e verificação de dependências passaram.
- Uma gravação sintética em português foi transcrita com MLX na GPU e redução de ruído FFmpeg; os três formatos foram gerados e seus metadados conferidos.
- O motor do pacote PyInstaller também transcreveu a gravação sintética pela GPU e gerou Markdown, SRT e TXT. A assinatura local foi verificada com `codesign --verify --deep --strict`.
- Versão 2.0.4 (build 5) instalada em `/Applications/HollyTranscricao.app`; a interface foi aberta e exibiu a versão correta. A versão anterior foi preservada em `build/update-2026-10-02/HollyTranscricao-2.0.3.app`, junto do snapshot das alterações locais anteriores.

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
