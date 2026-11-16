# Histórico de versões

Todas as alterações relevantes são registradas neste arquivo. O projeto segue versionamento semântico.

## [2.0.5] — 2026-11-16

### Segurança

- `certifi` 2026.7.22 → 2026.10.23, empacotado no aplicativo e usado nas conexões HTTPS do download dos modelos. A versão anterior incluía raízes da autoridade emSign com chaves intermediárias comprometidas (alerta crítico de 20/10/2026).
- `filelock` 3.32.6 → 4.2.10 (13 alertas, usado pelo cache de modelos do `huggingface_hub`), `msgpack` 1.2.2 → 1.2.4 (dependência do `pip-audit`), `setuptools` 84.0.0 → 84.2.1 e Pillow 12.3.0 → 13.0.0 (só no build, para gerar os ícones; 62 alertas).
- `requirements.txt` e `pyproject.toml` passam a exigir `certifi` e `filelock` corrigidos, como já faziam com o `urllib3`.
- Novo `requirements-macos-lock.txt` trava as 81 bibliotecas do build, todas sem alertas conhecidos na consulta de 16/11/2026. Antes não havia travas, e o ambiente tinha se afastado das versões declaradas.
- A verificação do GitHub passa a auditar as dependências instaladas (`pip-audit`) e a rodar também uma vez por mês.

### Desempenho

- O PyTorch (cerca de 400 MB) e o Pillow deixam de ir dentro do aplicativo. Só a separação de interlocutores e o DeepFilterNet usam o PyTorch, e os dois são complementos opcionais fora do pacote padrão. O motor padrão (MLX, Faster-Whisper e CTranslate2) funciona sem ele.
- Com a redução de ruído ligada e sem o DeepFilterNet instalado, o aplicativo vai direto ao filtro do FFmpeg, sem carregar o PyTorch (cerca de 3 segundos por transcrição). A barra de progresso informa o método realmente usado.

### Novo

- `HollyTranscricao --autoteste arquivo` transcreve um arquivo sem abrir a janela e termina com `AUTOTESTE OK`. Serve para conferir o aplicativo empacotado.

## [2.0.4] — 2026-10-02

### Segurança e estabilidade

- urllib3 atualizado para 2.8.0, corrigindo CVE-2026-97687, CVE-2026-97688 e CVE-2026-97689; os requisitos impedem reinstalar versões vulneráveis.
- MLX e MLX Metal atualizados para 0.32.3, com correções de deadlocks e operações Metal.
- Inicialização da interface deixa de executar operações nativas na GPU; o motor permanece no processo isolado.
- Cancelamento passa a funcionar também durante a criação do motor. No macOS/Linux, encerra os subprocessos da operação e remove os arquivos temporários após o término do motor.
- Seleção de mídia e início de outra transcrição ficam bloqueados enquanto o motor trabalha.

### Correções

- Exportações concorrentes passam a publicar arquivos com exclusividade e nomes únicos, impedindo que uma instância sobrescreva o resultado de outra.
- Mudanças de interlocutor dentro de um segmento são preservadas quando há alinhamento completo por palavra.
- Redução de ruído por FFmpeg concluída com sucesso passa a constar corretamente nos metadados.
- Pastas digitadas com `~` são normalizadas e o botão de abertura identifica o formato gerado.
- Versão e número de build no README sincronizados com o aplicativo.

## [2.0.3] — 2026-09-30

### Manutenção

- Qt/PySide6 atualizado de 6.11.1 para 6.11.2, incluindo as correções de estabilidade da interface.
- Ferramentas de build e qualidade atualizadas: PyInstaller 6.22.3 e Ruff 0.16.9.
- Selo de versão do README corrigido.
- Auditoria de dependências (`pip-audit`) sem vulnerabilidades conhecidas no núcleo.

## [2.0.2] — 2026-09-11

### Correções

- Vídeos QuickTime (`.qt`) e outros contêineres comuns (`.m4v`, `.avi`, `.wmv`, `.mpg`, `.mpeg`, `.3gp`, `.ts`, `.aiff`, `.amr`) passam a aparecer no seletor de arquivos e deixam de disparar o aviso de formato não suportado.

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
