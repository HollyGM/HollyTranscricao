"""Exportadores seguros de transcrição para Markdown, SRT e TXT."""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

# ───────────────────────── Helpers de formatação ─────────────────────────


def format_timestamp(seconds: float) -> str:
    total = int(max(0.0, seconds))
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    return f"[{h:02d}:{m:02d}:{s:02d}]"


def format_duration(seconds: float) -> str:
    total = int(max(0.0, seconds))
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    parts: list[str] = []
    if h:
        parts.append(f"{h}h")
    if m or h:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def _srt_timestamp(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    h = total_ms // 3_600_000
    m = (total_ms % 3_600_000) // 60_000
    s = (total_ms % 60_000) // 1000
    ms = total_ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ─────────── Pós-processamento: parágrafos, pontuação, baixa confiança ──

_SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")
_PARAGRAPH_GAP_SECONDS = 2.0  # gap mínimo para quebrar parágrafo dentro do mesmo locutor
_MAX_PARAGRAPH_CHARS = 600  # quebra forçada para evitar parágrafos gigantes


def _escape_table_cell(value: Any) -> str:
    """Evita que conteúdo transcrito quebre tabelas Markdown."""
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _safe_base_name(value: str) -> str:
    """Cria um nome de arquivo portátil entre macOS, Windows e Linux."""
    cleaned = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "_", value).strip(" .")
    if not cleaned:
        return "transcricao"
    if cleaned.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        cleaned = f"_{cleaned}"
    return cleaned[:180]


def _unique_output_path(output_dir: Path, filename: str) -> Path:
    """Nunca sobrescreve um resultado anterior."""
    candidate = output_dir / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    counter = 2
    while True:
        candidate = output_dir / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _atomic_write(path: Path, content: str) -> None:
    """Grava em arquivo temporário e só então publica o resultado final."""
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(temp_name)
        raise


def _split_into_paragraphs(blocks: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """Recebe os segmentos consecutivos de um mesmo locutor e devolve parágrafos.

    Cada parágrafo é uma tupla ``(texto, start_time)`` onde ``start_time`` é o
    início do primeiro bloco daquele parágrafo (em segundos).

    Quebra parágrafo quando:
      - há gap > _PARAGRAPH_GAP_SECONDS entre fim de um e início do próximo, OU
      - o parágrafo atual já passou de _MAX_PARAGRAPH_CHARS e terminou em sentença.
    """
    paragraphs: list[list[str]] = [[]]
    starts: list[float | None] = [None]
    prev_end: float | None = None

    for block in blocks:
        text = block["text"].strip()
        if not text:
            continue
        start = float(block.get("start", 0.0))
        end = float(block.get("end", 0.0))

        if prev_end is not None:
            gap = start - prev_end
            current_chars = sum(len(t) for t in paragraphs[-1])
            ends_sentence = paragraphs[-1] and bool(_SENTENCE_END.search(paragraphs[-1][-1][-3:]))
            if gap >= _PARAGRAPH_GAP_SECONDS or (
                current_chars >= _MAX_PARAGRAPH_CHARS and ends_sentence
            ):
                paragraphs.append([])
                starts.append(None)

        if starts[-1] is None:
            starts[-1] = start
        paragraphs[-1].append(text)
        prev_end = end

    out: list[tuple[str, float]] = []
    for chunks, start in zip(paragraphs, starts, strict=True):
        if not chunks:
            continue
        out.append((" ".join(chunks).strip(), float(start or 0.0)))
    return out


_MIN_WORD_LEN_FOR_CONFIDENCE_MARK = 5  # ignora palavras curtas: "é", "eu", "o", "aí", "pro"...


def _mark_low_confidence(
    text: str,
    words: list[dict[str, Any]],
    threshold: float = 0.40,
    enabled: bool = True,
) -> str:
    """Envolve palavras com baixa confiança em ``_itálico_``.

    Filtros aplicados para evitar poluição visual:
      - Pula palavras curtas (< _MIN_WORD_LEN_FOR_CONFIDENCE_MARK) — pequenas têm
        score baixo no Whisper sem que isso seja informativo.
      - Pula stopwords comuns.
      - Threshold padrão baixo (0.40) — só marca palavras realmente duvidosas.
    """
    if not enabled or not words:
        return text

    stopwords = {
        "o",
        "a",
        "os",
        "as",
        "um",
        "uma",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "e",
        "ou",
        "que",
        "se",
        "no",
        "na",
        "nos",
        "nas",
        "em",
        "por",
        "pra",
        "pro",
        "para",
        "com",
        "sem",
        "como",
        "mas",
        "também",
        "já",
        "só",
        "ai",
        "aí",
        "é",
        "eu",
        "tu",
        "ele",
        "ela",
        "nós",
        "vós",
        "eles",
        "elas",
        "ser",
        "ter",
        "estar",
        "ir",
        "vir",
        "ver",
        "fazer",
        "dar",
        "tá",
        "né",
        "ah",
        "então",
        "olha",
        "veja",
        "bom",
    }

    # ``words`` está na mesma ordem do texto, então a n-ésima aparição de um
    # token na lista corresponde à n-ésima aparição no texto. Guardar esse
    # índice é o que permite marcar a ocorrência certa quando a mesma palavra
    # se repete no bloco e só uma delas saiu duvidosa.
    suspects: list[tuple[str, int]] = []
    occurrences: dict[str, int] = {}
    for w in words:
        token = (w.get("word") or w.get("text") or "").strip()
        if not token:
            continue
        index = occurrences.get(token, 0)
        occurrences[token] = index + 1

        score = w.get("score")
        if score is None:
            score = w.get("probability")
        if score is None:
            continue
        clean = token.lower().strip(" .,;:!?\"'()[]")
        if len(clean) < _MIN_WORD_LEN_FOR_CONFIDENCE_MARK:
            continue
        if clean in stopwords:
            continue
        if float(score) < threshold:
            suspects.append((token, index))

    if not suspects:
        return text

    # Resolve todas as posições sobre o texto ORIGINAL e só então aplica as
    # inserções da direita para a esquerda, para que os deslocamentos causados
    # pelos underscores não movam as marcações seguintes.
    spans: list[tuple[int, int]] = []
    for token, index in suspects:
        hits = list(re.finditer(rf"(?<!_)\b{re.escape(token)}\b(?!_)", text))
        if index < len(hits):
            spans.append(hits[index].span())

    marked = text
    for start, end in sorted(set(spans), reverse=True):
        marked = f"{marked[:start]}_{marked[start:end]}_{marked[end:]}"
    return marked


# ────────────────────────── Sumário de locutores ─────────────────────────


def build_speaker_summary(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Calcula tempo total e número de turnos por locutor."""
    stats: dict[str, dict[str, Any]] = {}
    for seg in segments:
        spk = seg.get("speaker") or "Locutor"
        s = stats.setdefault(spk, {"turns": 0, "seconds": 0.0})
        s["turns"] += 1
        s["seconds"] += max(0.0, float(seg.get("end", 0.0)) - float(seg.get("start", 0.0)))

    # Ordena por tempo de fala desc
    return [
        {"speaker": spk, "turns": v["turns"], "seconds": v["seconds"]}
        for spk, v in sorted(stats.items(), key=lambda kv: kv[1]["seconds"], reverse=True)
    ]


# ───────────────────────────── Exportadores ──────────────────────────────


def render_markdown(
    *,
    original_filename: str,
    result: dict[str, Any],
    metadata: dict[str, Any],
    summary_markdown: str = "",
    low_confidence_threshold: float = 0.40,
    mark_low_confidence: bool = True,
) -> str:
    """Gera Markdown estruturado, portátil e fácil de revisar."""
    segments: list[dict[str, Any]] = result.get("segments", [])
    duration = float(result.get("duration", 0.0))
    diarized = bool(result.get("diarized"))
    backend = result.get("backend", "whisperx")
    model = result.get("model", "?")

    processed_at = _dt.datetime.now().astimezone().isoformat(timespec="minutes")

    md: list[str] = []

    # ── Cabeçalho YAML para Obsidian/markdown tooling ──
    md.append("---")
    md.append(f"arquivo: {json.dumps(original_filename, ensure_ascii=False)}")
    md.append(f"duracao: {format_duration(duration)}")
    md.append(f"data_processamento: {processed_at}")
    md.append(f"backend: {backend}")
    md.append(f"modelo_whisper: {model}")
    md.append(f"tratamento_ruido: {'sim' if metadata.get('noise_reduction') else 'nao'}")
    md.append(f"diarizacao: {'sim' if diarized else 'nao'}")
    md.append(f"tipo_gravacao: {metadata.get('recording_type', 'nao_informado')}")
    md.append("---")
    md.append("")

    # ── Título visível ──
    md.append(f"# Transcrição — {original_filename}")
    md.append("")

    # ── Sumário de locutores ──
    # Sem diarização todos os segmentos caem em "Locutor": a tabela viraria uma
    # linha só repetindo a duração do arquivo, então não vale o espaço.
    speaker_stats = build_speaker_summary(segments) if diarized else []
    if speaker_stats:
        md.append("## Locutores detectados")
        md.append("")
        md.append("| Locutor | Turnos | Tempo de fala |")
        md.append("|---|---:|---:|")
        for s in speaker_stats:
            speaker = _escape_table_cell(s["speaker"])
            md.append(f"| {speaker} | {s['turns']} | {format_duration(s['seconds'])} |")
        md.append("")

    # Aviso de falha de diarização
    if not diarized and metadata.get("hf_token"):
        err = result.get("error_diarization") or "Motivo não informado."
        md.append("> [!WARNING]")
        md.append(f"> Diarização falhou: {err}")
        md.append("")

    # Resumo opcional fornecido pelo chamador; o app não envia conteúdo à rede.
    if summary_markdown.strip():
        md.append("## Resumo")
        md.append("")
        md.append(summary_markdown.strip())
        md.append("")

    md.append("---")
    md.append("")
    md.append("## Transcrição")
    md.append("")

    # ── Corpo: agrupar por locutor, gerar parágrafos por pausa ──
    grouped = _group_consecutive_by_speaker(segments)

    for group in grouped:
        speaker = group["speaker"]
        start = group["start"]
        blocks = group["blocks"]

        # Marca baixa confiança palavra a palavra antes de juntar
        marked_blocks: list[dict[str, Any]] = []
        for b in blocks:
            marked_text = _mark_low_confidence(
                b["text"],
                b.get("words") or [],
                threshold=low_confidence_threshold,
                enabled=mark_low_confidence,
            )
            marked_blocks.append({**b, "text": marked_text})

        paragraphs = _split_into_paragraphs(marked_blocks)
        if not paragraphs:
            continue

        if diarized:
            md.append(f"### {format_timestamp(start)} — **{speaker}**")
            md.append("")

        # Timestamp intermediário para conseguir localizar o trecho no áudio.
        # Com diarização cada troca de locutor já ancora a leitura, então basta
        # um marco a cada ~5 parágrafos; sem diarização a transcrição inteira é
        # um bloco único e cada parágrafo precisa do seu próprio marco — é o que
        # permite localizar um trecho sem reouvir a gravação inteira.
        stamp_every = 5 if diarized else 1
        for idx, (para, para_start) in enumerate(paragraphs):
            if idx % stamp_every == 0 and (idx > 0 or not diarized):
                md.append(f"**{format_timestamp(para_start)}**")
                md.append("")
            md.append(para)
            md.append("")

    if not grouped:
        md.append("*Nenhum conteúdo de áudio pôde ser transcrito.*")
        md.append("")

    # ── Rodapé de auditoria das correções automáticas ──
    corrections: dict[str, int] = result.get("corrections") or {}
    if corrections:
        md.append("---")
        md.append("")
        md.append("## Revisão automática aplicada")
        md.append("")
        md.append(
            "Correções determinísticas feitas sobre a saída bruta do Whisper. "
            "Listadas aqui para conferência:"
        )
        md.append("")
        md.append("| Correção | Ocorrências |")
        md.append("|---|---:|")
        for desc, count in sorted(corrections.items(), key=lambda kv: -kv[1]):
            md.append(f"| {_escape_table_cell(desc)} | {count} |")
        md.append("")

    return "\n".join(md)


def _group_consecutive_by_speaker(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agrupa segmentos consecutivos do mesmo locutor preservando blocos individuais."""
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for seg in segments:
        speaker = seg.get("speaker", "Locutor")
        if current is None or speaker != current["speaker"]:
            current = {
                "speaker": speaker,
                "start": float(seg.get("start", 0.0)),
                "blocks": [seg],
            }
            groups.append(current)
        else:
            current["blocks"].append(seg)

    return groups


def render_srt(segments: list[dict[str, Any]]) -> str:
    """Gera legenda SRT a partir dos segmentos."""
    lines: list[str] = []
    counter = 1
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        speaker = seg.get("speaker")
        prefix = f"[{speaker}] " if speaker and speaker != "Locutor" else ""
        lines.append(str(counter))
        start = _srt_timestamp(float(seg.get("start", 0.0)))
        end = _srt_timestamp(float(seg.get("end", 0.0)))
        lines.append(f"{start} --> {end}")
        lines.append(prefix + text)
        lines.append("")
        counter += 1
    return "\n".join(lines)


def render_plain_text(segments: list[dict[str, Any]], diarized: bool = True) -> str:
    """Gera texto puro com timestamps e, quando disponível, locutores."""
    out: list[str] = []

    if not diarized:
        # Sem locutores, agrupar por locutor produziria uma única linha com a
        # gravação inteira. Quebrar por pausa e prefixar cada parágrafo com o
        # timestamp facilita localizar o trecho no áudio.
        for para, para_start in _split_into_paragraphs(segments):
            out.append(f"{format_timestamp(para_start)} {para}")
            out.append("")
        return "\n".join(out)

    for g in _group_consecutive_by_speaker(segments):
        text = " ".join((b.get("text") or "").strip() for b in g["blocks"]).strip()
        if not text:
            continue
        out.append(f"{format_timestamp(g['start'])} {g['speaker']}: {text}")
        out.append("")
    return "\n".join(out)


def write_outputs(
    output_dir: str,
    base_name: str,
    *,
    md_content: str = "",
    segments: list[dict[str, Any]],
    write_md: bool = True,
    write_srt: bool = False,
    write_txt: bool = False,
    diarized: bool = True,
) -> dict[str, str]:
    """Escreve formatos solicitados sem sobrescrever arquivos existentes."""
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)
    if not output_path.is_dir():
        raise NotADirectoryError(f"Destino não é uma pasta: {output_path}")

    safe_base = _safe_base_name(base_name)
    paths: dict[str, str] = {}

    if write_md and md_content:
        md_path = _unique_output_path(output_path, f"{safe_base}_transcricao.md")
        _atomic_write(md_path, md_content)
        paths["md"] = str(md_path)

    if write_srt:
        srt_path = _unique_output_path(output_path, f"{safe_base}.srt")
        _atomic_write(srt_path, render_srt(segments))
        paths["srt"] = str(srt_path)

    if write_txt:
        txt_path = _unique_output_path(output_path, f"{safe_base}_transcricao.txt")
        _atomic_write(txt_path, render_plain_text(segments, diarized=diarized))
        paths["txt"] = str(txt_path)

    return paths
