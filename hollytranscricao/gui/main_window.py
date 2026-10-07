"""Janela principal do HollyTranscrição.

Layout:
  [ Header ]
  [ DropZone (arquivo) ]
  [ GroupBox: Transcrição    — backend, modelo, vocabulário, ruído ]
  [ GroupBox: Locutores      — token HF, tipo, min/max ]
  [ GroupBox: Saída          — pasta, formatos, refino LLM ]
  [ Ações ] [ Console ] [ Progresso ]
"""

from __future__ import annotations

import datetime
import html
import importlib.util
import logging
import os
import platform
import sys
import time
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from hollytranscricao.gui.worker import TranscriptionWorker
from hollytranscricao.version import APP_NAME, APP_SLUG, ORGANIZATION_NAME, __version__

logger = logging.getLogger(__name__)

# Bump quando defaults mudarem; reseta seleções salvas dos usuários antigos.
# 4: diarização passou a ter interruptor próprio (antes bastava um token salvo
#    para ligá-la em toda transcrição) e min/max locutores voltam para "auto".
SETTINGS_VERSION = "6"

# O FFmpeg identifica o formato pelo conteúdo do arquivo, não pela extensão;
# esta lista só alimenta o filtro do seletor e o aviso de formato incomum.
MEDIA_EXTENSIONS = (
    # Áudio
    ".mp3",
    ".wav",
    ".ogg",
    ".opus",
    ".m4a",
    ".flac",
    ".aac",
    ".wma",
    ".aiff",
    ".amr",
    # Vídeo
    ".mp4",
    ".mov",
    ".qt",
    ".m4v",
    ".mkv",
    ".webm",
    ".avi",
    ".wmv",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".ts",
)

MEDIA_FILE_FILTER = (
    f"Arquivos de mídia ({' '.join(f'*{ext}' for ext in MEDIA_EXTENSIONS)});;Todos os arquivos (*)"
)


def _resource_path(relative_path: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / relative_path


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, AttributeError):
        return False


class DropZone(QFrame):
    """Área para arrastar e soltar / clicar para selecionar arquivo de mídia."""

    fileDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setProperty("dragged", "false")
        self.setFixedHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        self.iconLabel = QLabel("📥", self)
        self.iconLabel.setStyleSheet("font-size: 28px;")
        self.iconLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.iconLabel)

        self.textLabel = QLabel("Arraste e solte o arquivo aqui ou clique para selecionar", self)
        self.textLabel.setObjectName("dropLabel")
        self.textLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.textLabel)

        self.subTextLabel = QLabel("MP3, WAV, M4A, OGG, FLAC, OPUS, MP4, MOV, MKV…", self)
        self.subTextLabel.setObjectName("dropSubLabel")
        self.subTextLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.subTextLabel)

        self.selectedFileLabel = QLabel("", self)
        self.selectedFileLabel.setObjectName("fileLabel")
        self.selectedFileLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selectedFileLabel.setWordWrap(True)
        self.selectedFileLabel.setVisible(False)
        layout.addWidget(self.selectedFileLabel)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("dragged", "true")
            self._refresh_style()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setProperty("dragged", "false")
        self._refresh_style()

    def dropEvent(self, event: QDropEvent):
        self.setProperty("dragged", "false")
        self._refresh_style()
        urls = event.mimeData().urls()
        if urls:
            self.set_file(urls[0].toLocalFile())

    def set_file(self, file_path: str):
        if not self.isEnabled() or not self.acceptDrops():
            return
        # Pastas e itens inexistentes não são entradas válidas para o FFmpeg
        if not os.path.isfile(file_path):
            QMessageBox.warning(
                self,
                "Entrada inválida",
                "Selecione um arquivo de áudio ou vídeo (pastas não são suportadas).",
            )
            return

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in MEDIA_EXTENSIONS:
            QMessageBox.warning(
                self,
                "Formato não suportado",
                f"O formato {ext} pode não ser reconhecido. "
                "Prefira formatos conhecidos de áudio ou vídeo.",
            )

        self.selectedFileLabel.setText(f"✓  {os.path.basename(file_path)}")
        self.selectedFileLabel.setVisible(True)
        self.textLabel.setText('Pronto. Clique em "Processar Transcrição".')
        self.fileDropped.emit(file_path)

    def mousePressEvent(self, event):
        # acceptDrops() dobra como flag de "processamento em andamento":
        # a MainWindow o desativa durante a transcrição, e trocar de arquivo
        # no meio da execução só confundiria o usuário.
        if not self.acceptDrops():
            return
        if event.button() == Qt.MouseButton.LeftButton:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Selecionar arquivo de mídia",
                "",
                MEDIA_FILE_FILTER,
            )
            if file_path:
                self.set_file(file_path)

    def _refresh_style(self):
        self.style().unpolish(self)
        self.style().polish(self)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(780, 920)
        self.setMinimumSize(720, 720)

        self.settings = QSettings(ORGANIZATION_NAME, APP_SLUG)
        self._mlx_supported = sys.platform == "darwin" and platform.machine() == "arm64"
        self._diarization_available = _module_available("pyannote.audio")
        self.selected_file_path = ""
        self.generated_md_path = ""
        self.worker = None
        self._close_when_cancelled = False

        # Progresso estimado por tempo (a transcrição é uma chamada bloqueante
        # sem sub-progresso; sem isto a barra fica parada e parece travada).
        self._eta_timer = QTimer(self)
        self._eta_timer.setInterval(500)
        self._eta_timer.timeout.connect(self._tick_eta)
        self._eta_start = 0.0
        self._eta_total = 0.0

        self._init_ui()
        self._load_settings()

    # ──────────────────────────────── UI ────────────────────────────────

    def _init_ui(self):
        # Área rolável: garante que o conteúdo nunca seja espremido/sobreposto
        # mesmo que a janela seja menor que a soma dos cards.
        scroll = QScrollArea(self)
        scroll.setObjectName("rootScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCentralWidget(scroll)

        central = QWidget()
        central.setObjectName("rootContainer")
        scroll.setWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        # Cabeçalho com identidade própria do produto
        brand_row = QHBoxLayout()
        brand_row.setSpacing(12)
        logo = QLabel()
        logo.setObjectName("appLogo")
        logo_path = _resource_path("assets/icon_1024.png")
        if logo_path.exists():
            logo.setPixmap(
                QPixmap(str(logo_path)).scaled(
                    52,
                    52,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        brand = QLabel(f"HOLLYTRANSCRIÇÃO  ·  v{__version__}")
        brand.setObjectName("brandLabel")
        brand_row.addWidget(logo)
        brand_row.addWidget(brand)
        brand_row.addStretch(1)
        root.addLayout(brand_row)

        title = QLabel("Transcrição de Áudio & Vídeo")
        title.setObjectName("titleLabel")
        root.addWidget(title)

        subtitle = QLabel(
            "Converta áudio e vídeo em texto no próprio computador. "
            "Depois do download dos modelos, o conteúdo permanece local."
        )
        subtitle.setObjectName("subtitleLabel")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # Drop zone
        self.drop_zone = DropZone(self)
        self.drop_zone.fileDropped.connect(self._on_file_selected)
        root.addWidget(self.drop_zone)

        # Três seções
        root.addWidget(self._build_transcription_section())
        root.addWidget(self._build_speakers_section())
        root.addWidget(self._build_output_section())

        # Ações
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.process_btn = QPushButton("▶  Processar Transcrição")
        self.process_btn.setObjectName("primaryButton")
        self.process_btn.setEnabled(False)
        self.process_btn.clicked.connect(self._start_processing)
        actions.addWidget(self.process_btn, stretch=2)

        self.cancel_btn = QPushButton("■  Cancelar")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_processing)
        actions.addWidget(self.cancel_btn, stretch=1)

        self.open_md_btn = QPushButton("Abrir arquivo gerado")
        self.open_md_btn.setEnabled(False)
        self.open_md_btn.clicked.connect(self._open_generated_md)
        actions.addWidget(self.open_md_btn, stretch=1)

        root.addLayout(actions)

        # Console
        console_label = QLabel("Console de Execução")
        console_label.setStyleSheet("color: #9aa7c2; font-size: 12px; margin-top: 4px;")
        root.addWidget(console_label)

        self.console = QTextEdit()
        self.console.setObjectName("logConsole")
        self.console.setReadOnly(True)
        self.console.setFixedHeight(170)
        self.console.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root.addWidget(self.console)

        # Progresso
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        root.addWidget(self.progress_bar)

    @staticmethod
    def _make_section(title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("sectionCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(2)
        # Impede que o card seja espremido abaixo do tamanho do seu conteúdo
        # (causa raiz da sobreposição de widgets no macOS).
        outer.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        outer.addWidget(title_label)

        return card, outer

    @staticmethod
    def _add_field(layout: QVBoxLayout, label_text: str, widget: QWidget):
        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        layout.addSpacing(6)
        layout.addWidget(label)
        layout.addWidget(widget)

    def _build_transcription_section(self) -> QFrame:
        card, lay = self._make_section("🎙️  TRANSCRIÇÃO")

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(
            [
                "MLX-Whisper · GPU do Apple Silicon (recomendado)",
                "Faster-Whisper · CPU (compatibilidade)",
            ]
        )
        if not self._mlx_supported:
            self.backend_combo.setItemText(0, "MLX-Whisper · indisponível neste sistema")
            item = self.backend_combo.model().item(0)
            if item is not None:
                item.setEnabled(False)
        self.backend_combo.setToolTip(
            "MLX-Whisper roda Whisper diretamente nos cores GPU do Apple Silicon,\n"
            "muito mais rápido que CPU. Use Faster-Whisper como alternativa portátil."
        )
        self._add_field(lay, "Mecanismo", self.backend_combo)

        self.model_combo = QComboBox()
        self.model_combo.addItems(
            [
                "large-v3-turbo — recomendado: rápido e preciso",
                "large-v2 — alternativa para áudio com música ou ruído",
            ]
        )
        self.model_combo.setToolTip(
            "Large V3 Turbo: melhor equilíbrio para uso geral e modelo recomendado.\n\n"
            "Large V2: modelo integral e mais lento, oferecido como alternativa para\n"
            "comparar gravações difíceis. O resultado varia conforme o áudio e ele\n"
            "não é necessariamente melhor em toda gravação. No primeiro uso, baixa ~3,1 GB."
        )
        self._add_field(lay, "Modelo", self.model_combo)

        self.prompt_input = QLineEdit()
        self.prompt_input.setPlaceholderText("Nomes próprios, siglas e termos técnicos")
        self.prompt_input.setToolTip(
            "Termos separados por vírgula — nomes próprios, siglas e vocabulário específico.\n\n"
            "Atenção ao alcance real: o Whisper só usa esta lista nos primeiros\n"
            "30 segundos do áudio (depois disso ele descarta o prompt inicial).\n"
            "Algumas junções seguras derivadas deste campo podem ser aplicadas\n"
            "ao arquivo inteiro e ficam listadas no fim do Markdown."
        )
        self._add_field(lay, "Vocabulário", self.prompt_input)

        self.noise_checkbox = QCheckBox("Reduzir ruído (DeepFilterNet/FFmpeg)")
        self.noise_checkbox.setToolTip(
            "Aplica supressão de ruído antes da transcrição.\n"
            "Útil para gravações com chiado ou ruído constante.\n"
            "Áudios já tratados podem ficar com esta opção desligada."
        )
        lay.addSpacing(6)
        lay.addWidget(self.noise_checkbox)

        return card

    def _build_speakers_section(self) -> QFrame:
        card, lay = self._make_section("👥  LOCUTORES / DIARIZAÇÃO")

        # A diarização precisa de um interruptor próprio. Enquanto ela era
        # ativada pela mera presença do token, um token salvo meses antes
        # continuava rodando o Pyannote em toda transcrição — medido no M5,
        # isso derruba o pipeline de 10,6x para 1,8x realtime (uma audiência
        # de 2 h passa de ~11 min para mais de 1 h).
        self.diarize_checkbox = QCheckBox("Separar interlocutores (Pyannote)")
        self.diarize_checkbox.setToolTip(
            "DESLIGADO (padrão): transcrição corrida, ~10x mais rápido que o áudio.\n"
            "Uma gravação de 2 h levou cerca de 11 minutos no Mac de referência.\n\n"
            "LIGADO: identifica cada voz como Interlocutor 1, 2, 3…\n"
            "Medido no M5: fica de 3 a 6 vezes mais lento (a mesma gravação\n"
            "de 2 h passa de ~11 min para 35–70 min).\n\n"
            "Vale a pena só quando saber quem falou é essencial."
        )
        self.diarize_checkbox.toggled.connect(self._on_diarize_toggled)
        if not self._diarization_available:
            self.diarize_checkbox.setChecked(False)
            self.diarize_checkbox.setEnabled(False)
            self.diarize_checkbox.setText(
                "Separar interlocutores (complemento Pyannote não instalado)"
            )
        lay.addSpacing(4)
        lay.addWidget(self.diarize_checkbox)

        self.hf_token_input = QLineEdit()
        self.hf_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.hf_token_input.setPlaceholderText("hf_… (necessário para baixar o modelo Pyannote)")
        self.hf_token_input.setToolTip(
            "Token do Hugging Face, usado para baixar o modelo Pyannote.\n"
            "Por segurança, não é salvo: ao fechar o aplicativo ele é descartado."
        )
        self._add_field(lay, "Token Hugging Face", self.hf_token_input)

        self.recording_combo = QComboBox()
        self.recording_combo.addItems(
            [
                "Reunião",
                "Entrevista ou depoimento",
                "Aula ou palestra",
                "Audiência ou oitiva",
                "Mensagem de áudio",
                "Outro",
            ]
        )
        self.recording_combo.setToolTip(
            "Vai pro cabeçalho YAML do Markdown para referência futura."
        )
        self._add_field(lay, "Tipo de gravação", self.recording_combo)

        speakers_row = QWidget()
        speakers_layout = QHBoxLayout(speakers_row)
        speakers_layout.setContentsMargins(0, 0, 0, 0)
        speakers_layout.setSpacing(8)
        self.min_speakers_spin = QSpinBox()
        self.min_speakers_spin.setRange(0, 20)
        self.min_speakers_spin.setSpecialValueText("auto")
        self.min_speakers_spin.setToolTip(
            "Mínimo de locutores esperados (0 = detecção automática)."
        )
        self.max_speakers_spin = QSpinBox()
        self.max_speakers_spin.setRange(0, 20)
        self.max_speakers_spin.setSpecialValueText("auto")
        self.max_speakers_spin.setToolTip(
            "Máximo de locutores esperados (0 = detecção automática).\n\n"
            "Cuidado: um teto alto encarece muito o agrupamento do Pyannote.\n"
            "Medido no M5 sobre a mesma amostra: 'auto' levou 17 s, teto 20\n"
            "levou 48 s. Se possível, informe o número real de pessoas ou\n"
            "deixe em auto — nunca 20 'por garantia'."
        )
        arrow = QLabel("→")
        arrow.setStyleSheet("color: #55627e; padding: 0 6px;")
        speakers_layout.addWidget(self.min_speakers_spin)
        speakers_layout.addWidget(arrow)
        speakers_layout.addWidget(self.max_speakers_spin)
        speakers_layout.addStretch(1)
        self._add_field(lay, "Locutores esperados", speakers_row)

        return card

    def _build_output_section(self) -> QFrame:
        card, lay = self._make_section("💾  SAÍDA")

        dir_row = QWidget()
        dir_layout = QHBoxLayout(dir_row)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(6)
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setPlaceholderText("Onde os arquivos finais serão salvos")
        dir_layout.addWidget(self.output_dir_input, stretch=1)
        self.browse_btn = QPushButton("📁")
        self.browse_btn.setObjectName("iconButton")
        self.browse_btn.setToolTip("Escolher pasta…")
        self.browse_btn.clicked.connect(self._browse_output_dir)
        dir_layout.addWidget(self.browse_btn)
        self._add_field(lay, "Pasta de destino", dir_row)

        formats_row = QWidget()
        formats_layout = QHBoxLayout(formats_row)
        formats_layout.setContentsMargins(0, 0, 0, 0)
        formats_layout.setSpacing(14)
        self.fmt_md_checkbox = QCheckBox("Markdown (.md)")
        self.fmt_srt_checkbox = QCheckBox("Legenda (.srt)")
        self.fmt_txt_checkbox = QCheckBox("Texto (.txt)")
        for cb, tip in [
            (
                self.fmt_md_checkbox,
                "Markdown estruturado com cabeçalho, tabela de locutores e timestamps.",
            ),
            (self.fmt_srt_checkbox, "Legenda SRT pronta para uso em vídeo."),
            (self.fmt_txt_checkbox, "Texto puro para editores, e-mails e documentos."),
        ]:
            cb.setToolTip(tip)
            formats_layout.addWidget(cb)
        formats_layout.addStretch(1)
        self._add_field(lay, "Formatos de saída", formats_row)

        return card

    # ─────────────────────────── Persistência ───────────────────────────

    def _load_settings(self):
        """Carrega configurações com migração entre versões."""
        saved_version = str(self.settings.value("settings_version", "1"))
        is_fresh = saved_version != SETTINGS_VERSION

        if is_fresh:
            # Defaults novos (forçar large-v3-turbo + MLX, ainda que houvesse configuração antiga)
            self.model_combo.setCurrentIndex(0)  # large-v3-turbo
            self.backend_combo.setCurrentIndex(0 if self._mlx_supported else 1)
            self.recording_combo.setCurrentIndex(0)
            self.noise_checkbox.setChecked(False)
            self.fmt_md_checkbox.setChecked(True)
            self.fmt_srt_checkbox.setChecked(False)
            self.fmt_txt_checkbox.setChecked(False)
            self.diarize_checkbox.setChecked(False)
            self.min_speakers_spin.setValue(0)
            self.max_speakers_spin.setValue(0)
        else:
            self._safe_set_index(self.model_combo, self.settings.value("model_index", 0), default=0)
            backend_default = 0 if self._mlx_supported else 1
            self._safe_set_index(
                self.backend_combo,
                self.settings.value("backend_index", backend_default),
                default=backend_default,
            )
            if not self._mlx_supported and self.backend_combo.currentIndex() == 0:
                self.backend_combo.setCurrentIndex(1)
            self._safe_set_index(
                self.recording_combo, self.settings.value("recording_index", 0), default=0
            )
            self.noise_checkbox.setChecked(self.settings.value("apply_noise", "false") == "true")
            self.fmt_md_checkbox.setChecked(self.settings.value("fmt_md", "true") == "true")
            self.fmt_srt_checkbox.setChecked(self.settings.value("fmt_srt", "false") == "true")
            self.fmt_txt_checkbox.setChecked(self.settings.value("fmt_txt", "false") == "true")
            self.diarize_checkbox.setChecked(self.settings.value("diarize", "false") == "true")
            try:
                self.min_speakers_spin.setValue(int(self.settings.value("min_speakers", 0)))
                self.max_speakers_spin.setValue(int(self.settings.value("max_speakers", 0)))
            except (ValueError, TypeError):
                pass

        # Tokens nunca são persistidos. Remove também eventual segredo salvo
        # por versões anteriores do aplicativo.
        self.settings.remove("hf_token")
        legacy_settings = QSettings("LegalTranscriptionHub", "TranscriptionHubApp")
        legacy_settings.remove("hf_token")
        legacy_settings.sync()
        self.settings.sync()
        self.hf_token_input.clear()
        self.prompt_input.setText(self.settings.value("initial_prompt", ""))

        output_dir = self.settings.value("output_dir", "") or os.path.join(
            os.path.expanduser("~"), "Downloads"
        )
        self.output_dir_input.setText(output_dir)

        if not self._diarization_available:
            self.diarize_checkbox.setChecked(False)
        self._on_diarize_toggled(self.diarize_checkbox.isChecked())

    @staticmethod
    def _safe_set_index(combo: QComboBox, value, default: int):
        try:
            idx = int(value)
            if 0 <= idx < combo.count():
                combo.setCurrentIndex(idx)
            else:
                combo.setCurrentIndex(default)
        except (ValueError, TypeError):
            combo.setCurrentIndex(default)

    def _save_settings(self):
        s = self.settings
        s.setValue("settings_version", SETTINGS_VERSION)
        s.remove("hf_token")
        s.setValue("model_index", self.model_combo.currentIndex())
        s.setValue("backend_index", self.backend_combo.currentIndex())
        s.setValue("recording_index", self.recording_combo.currentIndex())
        s.setValue("min_speakers", self.min_speakers_spin.value())
        s.setValue("max_speakers", self.max_speakers_spin.value())
        s.setValue("output_dir", self.output_dir_input.text().strip())
        s.setValue("apply_noise", "true" if self.noise_checkbox.isChecked() else "false")
        s.setValue("initial_prompt", self.prompt_input.text().strip())
        s.setValue("diarize", "true" if self.diarize_checkbox.isChecked() else "false")
        s.setValue("fmt_md", "true" if self.fmt_md_checkbox.isChecked() else "false")
        s.setValue("fmt_srt", "true" if self.fmt_srt_checkbox.isChecked() else "false")
        s.setValue("fmt_txt", "true" if self.fmt_txt_checkbox.isChecked() else "false")

    # ─────────────────────────── Interação ──────────────────────────────

    def _browse_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, "Selecionar pasta de destino", self.output_dir_input.text()
        )
        if dir_path:
            self.output_dir_input.setText(dir_path)

    def _on_diarize_toggled(self, checked: bool):
        """Só faz sentido pedir token e número de locutores se houver diarização."""
        checked = checked and self._diarization_available
        for widget in (self.hf_token_input, self.min_speakers_spin, self.max_speakers_spin):
            widget.setEnabled(checked)

    def _on_file_selected(self, file_path: str):
        if self.worker and self.worker.isRunning():
            return
        self.selected_file_path = file_path
        self.process_btn.setEnabled(True)
        self._log(f"Arquivo selecionado: {os.path.basename(file_path)}")

    def _log(self, message: str, level: str = "INFO"):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        color = "#34d399"  # verde
        lower = message.lower()
        if "erro" in lower or "critical" in level.lower() or "falhou" in lower:
            color = "#f87171"  # vermelho
        elif "aviso" in lower or "warning" in level.lower():
            color = "#fbbf24"  # amarelo
        elif "passo" in lower or "concluído" in lower or "concluido" in lower:
            color = "#a78bfa"  # violeta da marca

        # Escapar HTML: mensagens de erro podem conter '<', '>' ou '&' e
        # corromperiam a renderização rich-text do console.
        safe_message = html.escape(message).replace("\n", "<br>")
        formatted = (
            f'<span style="color:#8a93a6;">[{timestamp}]</span> '
            f'<span style="color:{color};">{safe_message}</span>'
        )
        self.console.append(formatted)
        self.console.ensureCursorVisible()

    def _start_processing(self):
        if self.worker and self.worker.isRunning():
            return
        if not self.selected_file_path:
            return

        # O arquivo pode ter sido movido/renomeado desde a seleção; melhor
        # falhar agora do que após minutos de processamento.
        if not os.path.isfile(self.selected_file_path):
            QMessageBox.warning(
                self,
                "Arquivo não encontrado",
                f"O arquivo selecionado não existe mais:\n{self.selected_file_path}\n\n"
                "Selecione o arquivo novamente.",
            )
            return

        if not any(
            [
                self.fmt_md_checkbox.isChecked(),
                self.fmt_srt_checkbox.isChecked(),
                self.fmt_txt_checkbox.isChecked(),
            ]
        ):
            QMessageBox.warning(
                self,
                "Formato de saída",
                "Selecione pelo menos um formato de saída (Markdown, SRT ou TXT).",
            )
            return

        # Pasta de destino vazia geraria erro somente no FINAL do pipeline
        # (após toda a transcrição). Validar/normalizar antes de começar.
        output_dir = self.output_dir_input.text().strip()
        if not output_dir:
            output_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        output_dir = os.path.abspath(os.path.expanduser(output_dir))
        self.output_dir_input.setText(output_dir)
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Pasta de destino inválida",
                f"Não foi possível usar a pasta de destino:\n{output_dir}\n\n{exc}",
            )
            return

        if self.diarize_checkbox.isChecked():
            if not self.hf_token_input.text().strip():
                QMessageBox.warning(
                    self,
                    "Token necessário",
                    "A separação de interlocutores usa o modelo Pyannote, que exige "
                    "um token do Hugging Face.\n\nInforme o token ou desmarque "
                    '"Separar interlocutores".',
                )
                return

            # Pyannote falha com erro críptico quando min > max
            if (
                self.min_speakers_spin.value()
                and self.max_speakers_spin.value()
                and self.min_speakers_spin.value() > self.max_speakers_spin.value()
            ):
                QMessageBox.warning(
                    self,
                    "Locutores esperados",
                    "O mínimo de locutores não pode ser maior que o máximo.",
                )
                return

        self._save_settings()

        self.process_btn.setEnabled(False)
        self.open_md_btn.setEnabled(False)
        self.open_md_btn.setText("Abrir arquivo gerado")
        self.generated_md_path = ""
        self.drop_zone.setAcceptDrops(False)
        self.drop_zone.setEnabled(False)

        model_mapping = ["large-v3-turbo", "large-v2"]
        backend_mapping = ["mlx", "faster-whisper"]
        recording_mapping = [
            "reuniao",
            "entrevista_depoimento",
            "aula_palestra",
            "audiencia_oitiva",
            "mensagem_audio",
            "outro",
        ]

        selected_model = model_mapping[self.model_combo.currentIndex()]
        selected_backend = backend_mapping[self.backend_combo.currentIndex()]
        selected_recording = recording_mapping[self.recording_combo.currentIndex()]

        self.progress_bar.setRange(0, 0)
        self.console.clear()

        # O token só chega ao pipeline quando a diarização está marcada: é ele
        # que liga o Pyannote lá no backend, e um token guardado não pode
        # ressuscitar a etapa mais cara do processo sem o usuário pedir.
        diarize = self.diarize_checkbox.isChecked()
        hf_token = self.hf_token_input.text().strip() if diarize else ""

        self._log("=== Iniciando pipeline de transcrição local ===", level="STEP")
        self._log(f"Arquivo: {os.path.basename(self.selected_file_path)}")
        self._log(f"Backend: {selected_backend} | Modelo: {selected_model}")
        self._log(
            "Diarização: LIGADA (3 a 6x mais lento)"
            if diarize
            else "Diarização: desligada (modo rápido)"
        )

        min_spk = (self.min_speakers_spin.value() or None) if diarize else None
        max_spk = (self.max_speakers_spin.value() or None) if diarize else None

        self.worker = TranscriptionWorker(
            input_file_path=self.selected_file_path,
            output_md_dir=self.output_dir_input.text().strip(),
            hf_token=hf_token,
            whisper_model=selected_model,
            initial_prompt=self.prompt_input.text().strip(),
            apply_noise_reduction=self.noise_checkbox.isChecked(),
            backend=selected_backend,
            min_speakers=min_spk,
            max_speakers=max_spk,
            recording_type=selected_recording,
            write_md=self.fmt_md_checkbox.isChecked(),
            write_srt=self.fmt_srt_checkbox.isChecked(),
            write_txt=self.fmt_txt_checkbox.isChecked(),
        )

        self.worker.progress_signal.connect(self._on_worker_progress)
        self.worker.finished_signal.connect(self._on_worker_finished)
        self.worker.error_signal.connect(self._on_worker_error)
        self.worker.cancelled_signal.connect(self._on_worker_cancelled)
        self.worker.eta_signal.connect(self._on_eta_received)
        self.cancel_btn.setEnabled(True)
        self.worker.start()

    def _cancel_processing(self):
        if not self.worker or not self.worker.isRunning():
            return
        answer = QMessageBox.question(
            self,
            "Cancelar transcrição",
            "Deseja cancelar a transcrição em andamento?\n\n"
            "O arquivo original não será alterado.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.cancel_btn.setEnabled(False)
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("Cancelando…")
            self._log("Cancelamento solicitado. Encerrando o motor com segurança…", "WARNING")
            self.worker.cancel()

    def _on_worker_progress(self, message: str):
        self._log(message)
        # Detectar fallback para CPU e alertar o usuário com popup
        if "⚠️" in message and "CPU" in message and "FALHOU" in message:
            QMessageBox.warning(
                self,
                "GPU Indisponível — Modo Lento",
                "A transcrição via GPU (MLX) falhou e está rodando na CPU, "
                "que é MUITO mais lenta (~20x).\n\n"
                "Recomendação: CANCELE e reporte o erro do console.\n\n"
                "Detalhes no console de execução.",
            )

    def _on_worker_finished(self, output_paths):
        self._stop_eta_timer()

        if not isinstance(output_paths, dict):
            output_paths = {"md": str(output_paths)}

        md_path = output_paths.get("md")
        self.generated_md_path = md_path or next(iter(output_paths.values()), "")
        output_kind = "md" if md_path else next(iter(output_paths), "")
        open_labels = {
            "md": "Abrir Markdown (.md)",
            "srt": "Abrir legenda (.srt)",
            "txt": "Abrir texto (.txt)",
        }
        self.open_md_btn.setText(open_labels.get(output_kind, "Abrir arquivo gerado"))

        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(1000)
        self.progress_bar.setFormat("Concluído ✓")

        self._log("=== Processamento concluído com sucesso ===", level="STEP")
        for kind, path in output_paths.items():
            self._log(f"  • {kind.upper()}: {path}", level="SUCCESS")

        self.process_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.open_md_btn.setEnabled(bool(self.generated_md_path))
        self.drop_zone.setAcceptDrops(True)
        self.drop_zone.setEnabled(True)
        if self.generated_md_path:
            self.open_md_btn.setFocus()

        files_msg = "\n".join(os.path.basename(p) for p in output_paths.values())
        QMessageBox.information(
            self,
            "Sucesso",
            f"Transcrição gerada com sucesso.\n\nArquivos:\n{files_msg}",
        )

    def _on_worker_error(self, error_message: str):
        self._stop_eta_timer()

        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Falhou")
        self._log(f"ERRO: {error_message}", level="CRITICAL")
        self._log("=== Processamento falhou ===", level="CRITICAL")
        self.process_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.drop_zone.setAcceptDrops(True)
        self.drop_zone.setEnabled(True)
        QMessageBox.critical(
            self,
            "Falha no pipeline",
            f"Ocorreu um erro ao processar a transcrição:\n\n{error_message}",
        )

    def _on_worker_cancelled(self):
        self._stop_eta_timer()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Cancelado")
        self._log("=== Transcrição cancelada pelo usuário ===", level="WARNING")
        self.process_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.drop_zone.setAcceptDrops(True)
        self.drop_zone.setEnabled(True)
        if self._close_when_cancelled:
            self._close_when_cancelled = False
            if self.worker and self.worker.isRunning():
                self.worker.finished.connect(self.close)
            else:
                QTimer.singleShot(0, self.close)

    # ─────────────────── ETA / Barra de Progresso Real ───────────────────

    def _on_eta_received(self, estimated_seconds: float, backend_label: str):
        """Recebe estimativa de tempo do worker e inicia barra determinística."""
        self._eta_total = max(5.0, estimated_seconds)
        self._eta_start = time.monotonic()
        self._eta_backend_label = backend_label

        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        mins = int(self._eta_total // 60)
        secs = int(self._eta_total % 60)
        self.progress_bar.setFormat(f"~{mins}m {secs:02d}s restante — {backend_label}")
        self._log(f"⏱️ Estimativa: ~{mins}m {secs:02d}s ({backend_label})")

        self._eta_timer.start()

    def _tick_eta(self):
        """Timer de 500ms que avança a barra com base no tempo decorrido vs estimado."""
        if self._eta_total <= 0:
            return

        elapsed = time.monotonic() - self._eta_start
        ratio = min(elapsed / self._eta_total, 0.98)  # nunca chega a 100% antes de concluir
        self.progress_bar.setValue(int(ratio * 1000))

        remaining = max(0, self._eta_total - elapsed)
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        label = getattr(self, "_eta_backend_label", "")

        if remaining > 0:
            self.progress_bar.setFormat(f"~{mins}m {secs:02d}s restante — {label}")
        else:
            self.progress_bar.setFormat(f"Finalizando… — {label}")

    def _stop_eta_timer(self):
        """Para o timer de ETA e reseta estado."""
        self._eta_timer.stop()
        self._eta_total = 0.0
        self._eta_start = 0.0

    # ───────────────────────────────────────────────────────────────────

    def _open_generated_md(self):
        if self.generated_md_path and os.path.exists(self.generated_md_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.generated_md_path))
        else:
            QMessageBox.warning(
                self, "Aviso", "O arquivo não foi encontrado ou ainda não foi gerado."
            )
            self.open_md_btn.setEnabled(False)

    def closeEvent(self, event):
        """Oferece cancelamento seguro enquanto o motor isolado trabalha."""
        if hasattr(self, "worker") and self.worker and self.worker.isRunning():
            answer = QMessageBox.question(
                self,
                "Transcrição em andamento",
                "A transcrição ainda está em andamento. Deseja cancelá-la e fechar "
                "o aplicativo?\n\nO arquivo original não será alterado.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._close_when_cancelled = True
                self.cancel_btn.setEnabled(False)
                self.worker.cancel()
            event.ignore()
            return
        event.accept()
