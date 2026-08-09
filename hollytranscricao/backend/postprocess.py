"""Correções determinísticas, explícitas e auditáveis da transcrição.

Motivação
---------
O ``initial_prompt`` do Whisper só influencia a PRIMEIRA janela de 30 segundos
quando ``condition_on_previous_text=False`` — ver ``mlx_whisper/transcribe.py``:
depois de cada janela o ``prompt_reset_since`` avança até o fim da fila de
tokens e o prompt inicial é descartado. As regras derivadas do campo
"Vocabulário" ajudam a uniformizar termos no restante do arquivo.

Princípio de segurança
----------------------
Trocar uma palavra correta por outra é pior do que preservar a saída incerta do
reconhecimento de voz. As regras especializadas só são aplicadas quando o tipo
de gravação foi marcado como audiência/oitiva. Por isso uma regra só entra se:

1. a forma incorreta não existe em português (``espeça-se``, ``com signo``); ou
2. a forma incorreta é impossível no contexto ancorado pela regex
   (``e ata`` logo depois de ``registro``/``consignado``).

Toda substituição aplicada é contabilizada e vai para o rodapé do Markdown,
de modo que a correção seja auditável em vez de silenciosa.
"""

from __future__ import annotations

import re

Rule = tuple[str, str, str]  # (padrão, substituição, descrição para auditoria)


# ─────────────────────────────── Regras ────────────────────────────────
# Todas rodam com IGNORECASE; a caixa da primeira letra do trecho original
# é preservada na substituição.

_RULES: list[Rule] = [
    # "consigno" ouvido como "com signo" — "signo" não cabe em ata judicial.
    (r"\bcom\s+signo\b", "consigno", "com signo → consigno"),
    # "expeça-se" ouvido como "espeça-se": o verbo "espeçar" não existe.
    (r"\bespeça(-se|\s+se)\b", r"expeça\1", "espeça-se → expeça-se"),
    (r"\bespeçam(-se|\s+se)\b", r"expeçam\1", "espeçam-se → expeçam-se"),
    # O "em" nasal reduzido a "e" antes de substantivo processual.
    # "registro e ata" / "lavrado e ata" não são construções válidas.
    (
        r"\b(registr\w+|consign\w+|constou|constar[áa]?|lavrad[ao]|lançad[ao]|assentad[ao])"
        r"\s+e\s+ata\b",
        r"\1 em ata",
        "… e ata → … em ata",
    ),
    # Mesmo fenômeno com particípio + "em sentença/acórdão".
    (
        r"\b(apreciad[ao]|analisad[ao]|decidid[ao]|examinad[ao]|resolvid[ao]|enfrentad[ao])"
        r"\s+e\s+(sentença|acórdão)\b",
        r"\1 em \2",
        "… e sentença → … em sentença",
    ),
    # "por hora" (unidade de tempo) onde cabe "por ora" (por enquanto).
    # Ancorado em verbo decisório para nunca tocar em "R$ 200 por hora".
    (
        r"\b(indefiro|defiro|mantenho|suspendo|sobresto|aguardo|reservo)\b"
        r"([^.;!?]{0,60}?)\bpor\s+hora\b",
        r"\1\2por ora",
        "por hora → por ora (em decisão)",
    ),
    # Vícios de escuta em expressões fixas do foro.
    (r"\bdata\s+vênia\s+de\b", "data venia de", "data vênia → data venia"),
    (r"\bmeritíssimo\s+juíz\b", "Meritíssimo Juiz", "juíz → Juiz"),
    (
        r"\bautos\s+do\s+processo\s+de\s+número\b",
        "autos do processo número",
        "processo de número → processo número",
    ),
]

# Padrões avaliados e conscientemente NÃO corrigidos, para não se perder o
# raciocínio numa revisão futura:
#   • "preliminar e eventual apelação" → "em eventual": "e eventual recurso"
#     é enumeração legítima; o risco de reescrever certo por errado é alto.
#   • "a" / "há" em prazos: depende de sentido temporal que a regex não vê.
#   • "seção" / "sessão": ambas correntes no foro, sem âncora confiável.


# Prefixos que o Whisper costuma soltar do radical em termos longos.
# Só estes são considerados ao derivar regras do campo "Vocabulário",
# justamente para não inventar recortes arbitrários de palavra.
_SPLIT_PREFIXES = ("re", "des", "in", "im", "pre", "pro", "sub", "inter", "contra", "extra")


def _rules_from_vocabulary(vocabulary: str) -> list[Rule]:
    """Deriva regras de junção para os termos digitados no campo Vocabulário.

    Cobre o caso em que o Whisper quebra o termo em duas palavras
    (``re negociação`` em vez de ``renegociação``). Termos que já são
    compostos (``habeas corpus``) são ignorados — ali a separação é correta.
    """
    rules: list[Rule] = []
    seen: set[str] = set()

    for raw in re.split(r"[,;\n]", vocabulary or ""):
        term = raw.strip().strip("\"'“”‘’.…()[]")
        if " " in term or len(term) < 7 or not term.isalpha() or term.lower() in seen:
            continue
        seen.add(term.lower())

        low = term.lower()
        for prefix in _SPLIT_PREFIXES:
            rest = low[len(prefix) :]
            if low.startswith(prefix) and len(rest) >= 4:
                rules.append(
                    (
                        rf"\b{re.escape(prefix)}\s+{re.escape(rest)}\b",
                        low,
                        f"{prefix} {rest} → {low}",
                    )
                )
                break

    return rules


def _preserve_case(original: str, replacement: str) -> str:
    """Mantém a caixa da primeira letra do trecho substituído."""
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def correct_text(
    text: str,
    extra_rules: list[Rule] | None = None,
    *,
    specialized: bool = False,
) -> tuple[str, dict[str, int]]:
    """Aplica as regras. Devolve ``(texto_corrigido, {descrição: ocorrências})``."""
    applied: dict[str, int] = {}
    out = text

    rules = (list(_RULES) if specialized else []) + list(extra_rules or [])
    for pattern, repl, desc in rules:

        def _sub(m: re.Match, replacement: str = repl) -> str:
            return _preserve_case(m.group(0), m.expand(replacement))

        out, n = re.compile(pattern, re.IGNORECASE).subn(_sub, out)
        if n:
            applied[desc] = applied.get(desc, 0) + n

    return out, applied


def correct_segments(
    segments: list[dict],
    vocabulary: str = "",
    *,
    specialized: bool = False,
) -> dict[str, int]:
    """Corrige ``seg['text']`` in-place na lista inteira e devolve o relatório.

    As palavras individuais (``seg['words']``) não são reescritas: servem só
    para marcar baixa confiança e ancorar timestamps, e mexer nelas quebraria
    o alinhamento com o áudio.
    """
    extra = _rules_from_vocabulary(vocabulary)
    total: dict[str, int] = {}

    for seg in segments:
        fixed, applied = correct_text(seg.get("text", ""), extra, specialized=specialized)
        if applied:
            seg["text"] = fixed
            for desc, n in applied.items():
                total[desc] = total.get(desc, 0) + n

    return total
