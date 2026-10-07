import multiprocessing

# CRÍTICO (PyInstaller + macOS): precisa ser a PRIMEIRA coisa a rodar.
# Sem isto, qualquer biblioteca (torch/pyannote/faster-whisper) que crie um
# processo filho via "spawn" faz o app congelado se relançar do zero, abrindo
# uma segunda janela em vez de executar apenas o worker.
multiprocessing.freeze_support()

import logging
import os
import sys
from pathlib import Path

# macOS GUI App PATH Patch e Correções Específicas:
# 1. Adicionamos os caminhos padrão do Homebrew para garantir o acesso ao FFmpeg.
# 2. Desativamos o NNPACK no PyTorch (USE_NNPACK=0) pois ele causa SIGABRT
#    e crash (abort trap 6) em Apple Silicon quando executado dentro de um QThread.
os.environ["USE_NNPACK"] = "0"

# 3. Limitamos o OpenMP e as threads do PyTorch a 1. O PyTorch gerencia mal
#    a criação de threads (libomp) dentro de QThreads empacotadas via PyInstaller,
#    resultando em crashes no TensorIteratorBase::serial_for_each (.omp_outlined.).
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

if sys.platform == "darwin":
    homebrew_paths = ["/opt/homebrew/bin", "/usr/local/bin"]
    current_path = os.environ.get("PATH", "")
    for path in homebrew_paths:
        if path not in current_path:
            current_path = path + os.path.pathsep + current_path
    os.environ["PATH"] = current_path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from hollytranscricao.gui.main_window import MainWindow
from hollytranscricao.version import APP_NAME, APP_SLUG, ORGANIZATION_NAME, __version__

# Logs: console quando disponível (desenvolvimento) + arquivo na pasta padrão
# de cada sistema operacional.
# Em um .app empacotado (console=False) sys.stdout é None; sem o handler de
# arquivo os logs desapareceriam e o StreamHandler(None) geraria erros mudos.
_log_handlers: list = []
if sys.stdout is not None:
    _log_handlers.append(logging.StreamHandler(sys.stdout))


def _user_log_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / APP_SLUG
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / APP_SLUG / "Logs"
    root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / APP_SLUG.lower()


try:
    _log_dir = _user_log_dir()
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_handlers.append(logging.FileHandler(_log_dir / "app.log", encoding="utf-8"))
except OSError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_log_handlers or [logging.NullHandler()],
)
logger = logging.getLogger(APP_SLUG)


def get_resource_path(relative_path: str) -> str:
    """Localiza um recurso em desenvolvimento ou no pacote do PyInstaller."""
    try:
        # PyInstaller cria uma pasta temporária em sys._MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        # Em desenvolvimento, usa o diretório pai da pasta 'app' (raiz do projeto)
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def load_stylesheet(app: QApplication):
    """Carrega o arquivo styles.css e aplica como folha de estilo da aplicação (QSS)."""
    # Usar get_resource_path para compatibilidade com PyInstaller
    css_path = get_resource_path(os.path.join("hollytranscricao", "gui", "styles.css"))

    if os.path.exists(css_path):
        try:
            with open(css_path, encoding="utf-8") as f:
                stylesheet = f.read()
                app.setStyleSheet(stylesheet)
            logger.info("Estilo CSS carregado de: %s", css_path)
        except OSError as exc:
            logger.error("Falha ao carregar arquivo de estilos CSS: %s", exc)
    else:
        logger.warning("Arquivo styles.css não encontrado em: %s", css_path)


def main() -> int:
    logger.info("Iniciando %s %s...", APP_NAME, __version__)

    # O MLX só é inicializado no motor isolado. Um teste de GPU aqui também
    # poderia provocar uma falha nativa e fechar a interface antes de abrir.

    # Criar instância da aplicação Qt
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(ORGANIZATION_NAME)
    icon_path = get_resource_path(os.path.join("assets", "icon_1024.png"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Carregar e aplicar estilos QSS personalizados
    load_stylesheet(app)

    # Instanciar e exibir a janela principal
    window = MainWindow()
    window.show()

    # Iniciar o loop de eventos do Qt
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
