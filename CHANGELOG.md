# Histórico de versões

Todas as alterações relevantes são registradas neste arquivo. O projeto segue versionamento semântico.

## [2.0.1] — 2026-08-08

### Correções

- Motor MLX movido para um processo isolado; falhas nativas como `SIGBUS` deixam de fechar o aplicativo inteiro.
- Botão de cancelamento adicionado para interromper transcrições e downloads sem forçar o encerramento.
- Fechamento durante uma transcrição agora oferece cancelar e sair com segurança.
- Download inicial do modelo separado da estimativa de transcrição, evitando a barra presa em "Finalizando".
- Lista de modelos simplificada para Large V3 Turbo e Large V2.
- Large V2 adicionado como alternativa para comparar gravações com música ou ruído.

## [2.0.0] — 2026-08-08

### Identidade

- Novo nome público **HollyTranscrição** e identificador técnico **HollyTranscricao**.
- Identidade jurídica e monograma de advocacia removidos.
- Novo ícone com formas de diálogo e onda sonora, além de paleta violeta, coral e ciano.
- Ícones gerados para macOS (`.icns`), Windows (`.ico`) e Linux (`hicolor`).

### Segurança e privacidade

- Token do Hugging Face deixou de ser persistido e segredos legados são removidos das preferências.
- Integração oculta com servidor LLM removida; transcrições não são enviadas a APIs.
- Chamadas ao FFmpeg usam caminho resolvido, argumentos separados e execução sem shell.
- Escrita atômica e nomes únicos impedem sobrescrita acidental de resultados.

### Correções

- Numeração SRT sem lacunas quando há segmentos vazios.
- Escape de nomes de arquivo no YAML e de conteúdo em tabelas Markdown.
- Nomes de saída sanitizados para macOS, Windows e Linux.
- Correções jurídicas deixam de afetar gravações gerais.
- Encerramento brusco durante transcrição foi bloqueado para evitar resíduos temporários.

### Arquitetura

- WhisperX substituído por Faster-Whisper no modo CPU.
- Dependências de diarização isoladas como recurso opcional.
- Caminhos de log adaptados ao sistema operacional.
- Pacote Python renomeado para `hollytranscricao`.
- Testes, análise estática e automação de integração contínua adicionados.

## [1.0.0]

- Versão original como Legal Audio & Video Transcription Hub.
