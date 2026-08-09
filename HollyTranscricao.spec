# -*- mode: python ; coding: utf-8 -*-
import importlib.util
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata, collect_submodules, collect_data_files, collect_dynamic_libs

version_data = {}
version_file = Path(SPECPATH) / 'hollytranscricao' / 'version.py'
exec(compile(version_file.read_text(encoding='utf-8'), str(version_file), 'exec'), version_data)
APP_ID = version_data['APP_ID']
APP_NAME = version_data['APP_NAME']
APP_SLUG = version_data['APP_SLUG']
BUILD_NUMBER = version_data['BUILD_NUMBER']
__version__ = version_data['__version__']


def has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, AttributeError):
        return False


HAS_DIARIZATION = (
    os.environ.get('HOLLY_INCLUDE_DIARIZATION') == '1'
    and has_module('pyannote.audio')
)
OPTIONAL_EXCLUDES = [] if HAS_DIARIZATION else [
    'lightning',
    'pyannote',
    'pytorch_lightning',
    'torchaudio',
    'torchcodec',
]

# =============================================================================
# DATAS: Arquivos de dados não-Python que precisam estar no bundle
# =============================================================================
datas = []

# Arquivo de estilos da GUI
datas += [('hollytranscricao/gui/styles.css', 'hollytranscricao/gui')]
datas += [('assets/icon_1024.png', 'assets')]

# Metadados de pacotes do núcleo
datas += copy_metadata('huggingface-hub')
datas += copy_metadata('faster-whisper')
datas += copy_metadata('ctranslate2')
datas += copy_metadata('mlx-whisper')
datas += copy_metadata('mlx')
datas += copy_metadata('tiktoken')

# Diarização é opcional. O build padrão não a instala nem a empacota.
if HAS_DIARIZATION:
    for package in (
        'torchcodec',
        'pyannote.audio',
        'pyannote.core',
        'pyannote.pipeline',
        'pyannote.database',
    ):
        datas += copy_metadata(package)

# Arquivos de dados dos pacotes (yamls, onnx, binários, etc.)
# faster_whisper: inclui silero_vad_v6.onnx
datas += collect_data_files('faster_whisper')
# ctranslate2: inclui libctranslate2.dylib
datas += collect_data_files('ctranslate2')
if HAS_DIARIZATION:
    datas += collect_data_files('pyannote.audio')
    datas += collect_data_files('torchaudio')
# mlx + mlx-whisper: inclui mlx_metal.dylib e assets
datas += collect_data_files('mlx')
datas += collect_data_files('mlx_whisper')
# tiktoken_ext: encoders (cl100k_base, etc.)
datas += collect_data_files('tiktoken')
datas += collect_data_files('tiktoken_ext')

# =============================================================================
# HIDDEN IMPORTS: Módulos que o PyInstaller não detecta automaticamente
# =============================================================================
hiddenimports = []

# faster_whisper e ctranslate2
hiddenimports += collect_submodules('faster_whisper')
hiddenimports += collect_submodules('ctranslate2')

# MLX e MLX-Whisper (todos os submodulos para o backend GPU do M5)
hiddenimports += collect_submodules('mlx')
hiddenimports += collect_submodules('mlx_whisper')
hiddenimports += collect_submodules('tiktoken')
hiddenimports += collect_submodules('tiktoken_ext')

hiddenimports += ['soundfile']

if HAS_DIARIZATION:
    for package in (
        'pyannote.audio',
        'pyannote.core',
        'pyannote.pipeline',
        'pyannote.database',
    ):
        hiddenimports += collect_submodules(package)
    hiddenimports += [
        'sklearn',
        'sklearn.utils._cython_blas',
        'sklearn.neighbors.typedefs',
        'sklearn.neighbors.quad_tree',
        'sklearn.tree',
        'sklearn.tree._utils',
        'librosa',
        'einops',
        'asteroid_filterbanks',
        'omegaconf',
        'hydra',
        'torch_audiomentations',
    ]

# =============================================================================
# BINARIES: Bibliotecas nativas (.dylib/.so) que precisam de reescrita de @rpath
#
# CRÍTICO: collect_data_files copia .dylib como dados (sem reescrita de rpath).
# Somente arquivos na lista 'binaries' têm seus @rpath/@loader_path reescritos
# pelo PyInstaller para funcionarem dentro do .app bundle.
# Sem isto, o MLX falha em runtime e cai para o Faster-Whisper em CPU.
# =============================================================================
binaries = []
binaries += collect_dynamic_libs('mlx')        # libmlx.dylib, libjaccl.dylib
binaries += collect_dynamic_libs('mlx_whisper') # se houver extensões nativas
binaries += collect_dynamic_libs('ctranslate2') # libctranslate2.dylib

# =============================================================================
# ANÁLISE
# =============================================================================
a = Analysis(
    ['hollytranscricao/main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['hooks/rthook_mlx_metallib.py'],
    excludes=OPTIONAL_EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_SLUG,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64' if sys.platform == 'darwin' else None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_SLUG,
)
app = BUNDLE(
    coll,
    name=f'{APP_SLUG}.app',
    icon='assets/icon.icns',
    bundle_identifier=APP_ID,
    info_plist={
        'CFBundleDisplayName': APP_NAME,
        'CFBundleName': APP_SLUG,
        'CFBundleShortVersionString': __version__,
        'CFBundleVersion': str(BUILD_NUMBER),
        'NSHighResolutionCapable': True,
        'NSHumanReadableCopyright': 'Copyright 2026 HollyApps · Apache-2.0',
    },
)
