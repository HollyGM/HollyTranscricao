# Empacotamento

## macOS — Apple Silicon

Use Python 3.12 em um Mac Apple Silicon. Instale o FFmpeg e as dependências completas:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-dev.txt
python assets/build_icons.py
pyinstaller --noconfirm --clean HollyTranscricao.spec
```

O aplicativo será criado em `dist/HollyTranscricao.app`. O build padrão não inclui Pyannote. O pacote local não é assinado nem notarizado; para distribuição pública, configure um certificado Developer ID, assinatura de código e notarização da Apple.

Para um build local experimental com diarização, instale `requirements-diarization.txt` e defina `HOLLY_INCLUDE_DIARIZATION=1` ao executar o PyInstaller. Leia antes as limitações de dependências no relatório de auditoria.

## Windows e Linux

O código usa Faster-Whisper em CPU nesses sistemas, mas os instaladores ainda precisam de validação em máquinas reais. O ponto de entrada é:

```bash
python -m hollytranscricao.main
```

Ao criar um instalador, inclua o ícone `assets/icon.ico` no Windows ou os arquivos de `assets/icons/hicolor` no Linux. O FFmpeg precisa estar disponível no `PATH` do usuário ou ser distribuído conforme os termos de sua própria licença.

## Versão

A fonte única da versão está em `hollytranscricao/version.py`. Atualize também o `CHANGELOG.md` a cada lançamento.
