#!/usr/bin/python3
"""dictee-postprocess — post-processing filter for voice dictation.

Reads transcribed text from stdin, applies sequentially:
  1.  Regex rules (annotations, hesitations, voice commands, dedup, punctuation, elisions)
  2.  Advanced French elisions (with aspirated h)
  3.  Number-to-digit conversion (text2num, optional)
  4.  French typography (non-breaking spaces)
  5.  Dictionary (system + personal, with jellyfish phonetic matching)
  6.  Capitalization
  7.  Optional LLM correction (ollama / OpenAI / OpenRouter / Google Gemini / Claude / Groq)

Writes the result to stdout.

Configuration via environment variables:
  DICTEE_LANG_SOURCE       — source language (fr, en, de, ...) for filtering rules
  DICTEE_PP_ELISIONS       — true/false (default: true)  — advanced French elisions
  DICTEE_PP_NUMBERS        — true/false (default: true)  — number-to-digit conversion
  DICTEE_PP_TYPOGRAPHY     — true/false (default: true)  — French typography
  DICTEE_PP_CAPITALIZATION — true/false (default: true)  — automatic capitalization
  DICTEE_PP_FUZZY_DICT     — true/false (default: true)  — dictionary phonetic matching
  DICTEE_LLM_POSTPROCESS   — true/false (default: false) — LLM correction
  DICTEE_LLM_PROVIDER      — ollama/openai/openrouter/gemini/anthropic/groq (default: ollama)
  DICTEE_LLM_MODEL         — LLM model (default: gemma3:4b)
  DICTEE_LLM_TIMEOUT       — timeout in seconds (default: 10)
  DICTEE_LLM_CPU           — true/false (ollama only)
  DICTEE_LLM_ADDITIONAL_CONTEXT — additional context injected into the LLM prompt
  DICTEE_LLM_DEBUG         — true/false (detailed LLM logs on stderr)

Remote API keys read from the environment:
  OPENAI_API_KEY / OPENROUTER_API_KEY / GOOGLE_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY / GROQ_API_KEY
"""

import json
import os
import re
import sys
import time
import logging
import argparse
import subprocess
import urllib.error
import urllib.request

# ── Venv bootstrap ───────────────────────────────────────────────────
# If a dedicated venv exists (with text2num, jellyfish, etc.),
# add its site-packages to sys.path so imports work without re-exec.
# Re-exec via os.execv would lose stdin (pipe), so we inject the path instead.

XDG_DATA = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
_VENV_DIR = os.path.join(XDG_DATA, "dictee", "postprocess-env")
_VENV_SITE = os.path.join(
    _VENV_DIR,
    "lib",
    f"python{sys.version_info.major}.{sys.version_info.minor}",
    "site-packages",
)
if os.path.isdir(_VENV_SITE) and _VENV_SITE not in sys.path:
    sys.path.insert(0, _VENV_SITE)

# ── Paths ─────────────────────────────────────────────────────────────

XDG_CONFIG = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))

USER_RULES = os.path.join(XDG_CONFIG, "dictee", "rules.conf")
USER_DICT = os.path.join(XDG_CONFIG, "dictee", "dictionary.conf")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SYSTEM_RULES_CANDIDATES = [
    os.path.join(_SCRIPT_DIR, "rules.conf.default"),
    "/usr/share/dictee/rules.conf.default",
    os.path.join(XDG_DATA, "dictee", "rules.conf.default"),
]

SYSTEM_DICT_CANDIDATES = [
    os.path.join(_SCRIPT_DIR, "dictionary.conf.default"),
    "/usr/share/dictee/dictionary.conf.default",
    os.path.join(XDG_DATA, "dictee", "dictionary.conf.default"),
]

LANG = os.environ.get("DICTEE_LANG_SOURCE", "").lower()[:2]
LOGGER = logging.getLogger("dictee-postprocess")
VERBOSE = False


def _env_bool(var, default="true"):
    """Reads a boolean environment variable."""
    return os.environ.get(var, default).lower() == "true"


def _env_int(var, default):
    """Reads an integer environment variable."""
    try:
        return int(os.environ.get(var, str(default)))
    except (TypeError, ValueError):
        return default


def _configure_logging(verbose=False):
    """Configure the script logger."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="[dictee-postprocess] %(message)s",
        stream=sys.stderr,
    )


def _preview_text(text, max_len=120):
    """Returns a compact preview of the text for logging."""
    escaped = text.replace("\n", "\\n")
    if len(escaped) <= max_len:
        return escaped
    return escaped[: max_len - 3] + "..."


def _log_stage(name, before, after, elapsed_ms):
    """Standard log for a pipeline stage."""
    if not VERBOSE:
        return
    changed = before != after
    LOGGER.debug(
        "%s | %s | %.1f ms | len %d -> %d",
        name,
        "changed" if changed else "unchanged",
        elapsed_ms,
        len(before),
        len(after),
    )
    if changed:
        LOGGER.debug("  before: %r", _preview_text(before))
        LOGGER.debug("  after : %r", _preview_text(after))


def _llm_debug(msg):
    """LLM debug log independent of pipeline verbose mode."""
    if _env_bool("DICTEE_LLM_DEBUG", "false"):
        print(f"[dictee-postprocess] {msg}", file=sys.stderr)


# ── Loading regex rules ──────────────────────────────────────────────

_RULE_RE = re.compile(r"^\s*\[([a-z]{2}|\*)\]\s*/(.+)/(.+)/([igm]*)\s*$")

# Rules with empty replacement: /PATTERN//FLAGS
_RULE_EMPTY_RE = re.compile(r"^\s*\[([a-z]{2}|\*)\]\s*/(.+)//([igm]*)\s*$")


def _parse_rules(path):
    """Parse a rules file, returns [(pattern_compiled, replacement)]."""
    rules = []
    if not os.path.isfile(path):
        return rules
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Try empty replacement first
            m = _RULE_EMPTY_RE.match(line)
            if m:
                lang_tag, pattern, flags_str = m.groups()
                replacement = ""
            else:
                m = _RULE_RE.match(line)
                if not m:
                    continue
                lang_tag, pattern, replacement, flags_str = m.groups()
            # Filter by language
            if lang_tag != "*" and LANG and lang_tag != LANG:
                continue
            flags = 0
            if "i" in flags_str:
                flags |= re.IGNORECASE
            if "m" in flags_str:
                flags |= re.MULTILINE
            # \s in character classes [,.\s] should not consume \n produced by other rules
            # Replace \s with \t (space + tab) in character classes
            pattern = re.sub(
                r"\[([^\]]*?)\\s([^\]]*?)\]",
                lambda m: "[" + m.group(1) + r" \t" + m.group(2) + "]",
                pattern,
            )
            try:
                compiled = re.compile(pattern, flags)
            except re.error:
                continue
            # Convert escape sequences in the replacement
            replacement = (
                replacement.replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace("\\u00a0", "\u00a0")
                .replace("\\u202f", "\u202f")
                .replace("\\u2026", "\u2026")
                .replace("\\u2014", "\u2014")
                .replace("\\u00ab", "\u00ab")
                .replace("\\u00bb", "\u00bb")
            )
            rules.append((compiled, replacement))
    return rules


def load_rules():
    """Load system rules, then user rules."""
    rules = []
    for candidate in SYSTEM_RULES_CANDIDATES:
        if os.path.isfile(candidate):
            rules.extend(_parse_rules(candidate))
            break
    rules.extend(_parse_rules(USER_RULES))
    return rules


def apply_rules(text, rules):
    """Apply regex rules sequentially."""
    for pattern, replacement in rules:
        text = pattern.sub(replacement, text)
    return text


# ── Advanced French elisions ─────────────────────────────────────────

# Words starting with aspirated h (NO elision)
H_ASPIRE = frozenset(
    {
        "hache",
        "haie",
        "haine",
        "hall",
        "halte",
        "halo",
        "hamac",
        "hameau",
        "hamster",
        "hanche",
        "handicap",
        "hangar",
        "hanter",
        "happer",
        "harasser",
        "harceler",
        "hardi",
        "harem",
        "hareng",
        "haricot",
        "harpe",
        "hasard",
        "hâte",
        "hausse",
        "haut",
        "haute",
        "hauts",
        "hautes",
        "hauteur",
        "havre",
        "hérisson",
        "hernie",
        "héron",
        "héros",
        "herse",
        "hêtre",
        "heurter",
        "hibou",
        "hiérarchie",
        "hippie",
        "hisser",
        "hocher",
        "hockey",
        "hollande",
        "homard",
        "hongrie",
        "honte",
        "hoquet",
        "horde",
        "hors",
        "hot",
        "hotte",
        "houblon",
        "houille",
        "houle",
        "housse",
        "hublot",
        "huer",
        "huit",
        "huitième",
        "hurler",
        "hutte",
        "hyène",
    }
)

ELISION_WORDS = {
    "je": "j'",
    "me": "m'",
    "te": "t'",
    "se": "s'",
    "le": "l'",
    "la": "l'",
    "ne": "n'",
    "de": "d'",
    "que": "qu'",
    "ce": "c'",
}

_VOWELS = "aeiouyàâäéèêëîïôöùûüÿæœ"
_VOWEL_PATTERN = f"[{_VOWELS}{_VOWELS.upper()}]"
# mute h followed by a vowel (but NOT aspirated h)
_H_MUET_VOWEL = f"[hH]{_VOWEL_PATTERN}"

# Pre-compile elision patterns
_H_ASPIRE_SORTED = sorted(H_ASPIRE, key=len, reverse=True)
_H_ASPIRE_RE = "|".join(re.escape(h) for h in _H_ASPIRE_SORTED)
_ELISION_PATTERNS = []
for _word, _elided in ELISION_WORDS.items():
    # Matches: word + space + (vowel OR mute h), except aspirated h
    _pat = re.compile(
        rf"\b{re.escape(_word)}\s+(?!(?:{_H_ASPIRE_RE})\b)({_VOWEL_PATTERN}\w*|{_H_MUET_VOWEL}\w*)",
        re.IGNORECASE,
    )
    _ELISION_PATTERNS.append((_pat, _elided))

_SI_IL_RE = re.compile(r"\bsi\s+(ils?)\b", re.IGNORECASE)


def fix_elisions(text):
    """Fix missing elisions (je ai → j'ai) with aspirated h support."""
    for pattern, elided in _ELISION_PATTERNS:

        def _elide(m, e=elided):
            rest = m.group(1)
            # Preserve case: if the original word started with uppercase
            # and the elision is at the start of a sentence, keep the uppercase on the elision
            return (
                e + rest.lower()
                if rest[0].isupper() and len(rest) > 1 and rest[1:] == rest[1:].lower()
                else e + rest
            )

        text = pattern.sub(_elide, text)
    text = _SI_IL_RE.sub(r"s'\1", text)
    return text


# ── Number conversion (text2num) ─────────────────────────────────────

try:
    from text_to_num import alpha2digit

    _HAS_TEXT2NUM = True
except ImportError:
    _HAS_TEXT2NUM = False

_TEXT2NUM_LANGS = frozenset({"fr", "en", "es", "pt", "de", "it", "nl"})


def convert_numbers(text):
    """Convert spelled-out numbers to digits."""
    if not _HAS_TEXT2NUM or LANG not in _TEXT2NUM_LANGS:
        return text
    try:
        return alpha2digit(text, LANG)
    except Exception:
        return text


# ── French typography ────────────────────────────────────────────────

_NBSP = "\u00a0"  # non-breaking space (before :, after «, before »)
_NNBSP = "\u202f"  # narrow non-breaking space (before ; ? !)

# Pre-compile typography patterns
_TYPO_BEFORE_THIN = re.compile(
    r"(?<=\S)\s*([;!?])"
)  # narrow non-breaking space before ; ! ? (except at start of line)
_TYPO_BEFORE_COLON = re.compile(
    r"(?<=\S)\s*(:)"
)  # non-breaking space before : (except at start of line)
_TYPO_AFTER_LGUILL = re.compile(r"«\s*")  # space after «
_TYPO_BEFORE_RGUILL = re.compile(r"\s*»")  # space before »
_TYPO_ELLIPSIS = re.compile(r"\.{3,}")  # ... → …
_TYPO_EN_QUOTES = re.compile(r'"([^"]+)"')  # "x" → « x »


def fix_portuguese_typography(text):
    _NO_SPACE_BEFORE = re.compile(r'\s+([.,;:!?])')
    _NO_SPACE_AFTER_OPEN = re.compile(r'([(•])\s+')
    _EN_QUOTES = re.compile(r'"([^"]+)"')
    _ELLIPSIS = re.compile(r'\.{3,}')
    text = _ELLIPSIS.sub('\u2026', text)
    text = _EN_QUOTES.sub(f'"\u2018\\1\u2019"', text)
    text = _NO_SPACE_BEFORE.sub(r'\1', text)
    text = _NO_SPACE_AFTER_OPEN.sub(r'\1 ', text)
    return text


_PT_COMMON_WORDS = frozenset({
    "a", "o", "e", "é", "de", "do", "da", "em", "no", "na", "um", "uma",
    "que", "não", "se", "por", "com", "para", "mas", "como", "mais",
    "ao", "aos", "às", "à", "ou", "ele", "ela", "eles", "elas", "nos",
    "nós", "vos", "lhe", "lhes", "meu", "minha", "teu", "tua", "seu",
    "sua", "este", "esta", "esse", "essa", "aquele", "aquela", "isto",
    "isso", "aquilo", "muito", "pouco", "tudo", "nada", "algo", "cada",
    "quando", "onde", "quem", "qual", "quanto", "aqui", "ali", "lá",
    "ainda", "já", "só", "também", "sempre", "nunca", "hoje", "ontem",
    "amanhã", "bem", "mal", "sim", "entre", "sobre", "até", "depois",
    "antes", "onde", "aonde", "porque", "pois", "portanto", "então",
    "contudo", "todavia", "porém", "senão", "conforme", "segundo",
    "era", "ser", "ter", "está", "estou", "estava", "foram", "fora",
    "vai", "vou", "tem", "tinha", "têm", "fiz", "fez", "fizeram",
    "pode", "posso", "deve", "deveria", "quer", "quero", "disse",
    "diz", "vê", "vir", "vim", "vieram", "dar", "dei", "deu", "deram",
    "ir", "irei", "iria", "fazer", "saber", "poder", "querer", "dizer",
    "ver", "dar", "estar", "haver", "havia", "houve", "teria", "seria",
})

_EN_COMMON_WORDS = frozenset({
    "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can",
    "this", "that", "these", "those", "with", "from", "into",
    "about", "than", "then", "there", "here", "where", "when",
    "what", "which", "who", "whom", "how", "not", "but", "and",
    "for", "you", "your", "they", "them", "their", "his", "her",
    "she", "him", "it", "its", "my", "our", "we", "me", "us",
    "all", "some", "any", "many", "much", "very", "just", "also",
    "now", "still", "even", "only", "other", "new", "first",
    "like", "get", "got", "make", "made", "know", "think", "say",
    "said", "go", "went", "come", "came", "see", "saw", "take",
    "look", "want", "need", "try", "use", "find", "give",
})

_EN_TO_PT = {
    "the": "o",
    "and": "e",
    "is": "é",
    "in": "em",
    "to": "para",
    "of": "de",
    "that": "que",
    "it": "isso",
    "you": "você",
    "he": "ele",
    "was": "era",
    "for": "por",
    "on": "em",
    "are": "são",
    "with": "com",
    "as": "como",
    "his": "seu",
    "they": "eles",
    "at": "em",
    "be": "ser",
    "this": "este",
    "have": "ter",
    "from": "de",
    "or": "ou",
    "one": "um",
    "had": "tinha",
    "by": "por",
    "but": "mas",
    "not": "não",
    "what": "que",
    "all": "tudo",
    "were": "eram",
    "we": "nós",
    "when": "quando",
    "can": "pode",
    "said": "disse",
    "there": "lá",
    "use": "usa",
    "an": "um",
    "each": "cada",
    "which": "qual",
    "she": "ela",
    "do": "fazer",
    "how": "como",
    "their": "seu",
    "if": "se",
    "will": "vai",
    "up": "cima",
    "about": "sobre",
    "out": "fora",
    "many": "muitos",
    "then": "então",
    "them": "eles",
    "these": "estes",
    "so": "assim",
    "some": "alguns",
    "would": "seria",
    "make": "fazer",
    "like": "como",
    "no": "não",
    "has": "tem",
    "him": "ele",
    "time": "tempo",
    "very": "muito",
    "just": "só",
    "know": "saber",
    "take": "tomar",
    "people": "pessoas",
    "into": "em",
    "year": "ano",
    "your": "seu",
    "good": "bom",
    "some": "algum",
    "could": "poderia",
    "see": "ver",
    "than": "que",
    "now": "agora",
    "look": "olhar",
    "only": "só",
    "come": "vir",
    "its": "seu",
    "over": "sobre",
    "think": "pensar",
    "also": "também",
    "back": "voltar",
    "after": "depois",
    "work": "trabalho",
    "first": "primeiro",
    "well": "bem",
    "even": "mesmo",
    "want": "querer",
    "because": "porque",
    "any": "qualquer",
    "these": "estes",
    "give": "dar",
    "day": "dia",
    "most": "mais",
    "find": "encontrar",
    "here": "aqui",
    "thing": "coisa",
    "many": "muitos",
    "right": "certo",
    "still": "ainda",
}


def fix_pt_en_mixing(text):
    if LANG != "pt":
        return text
    words = re.findall(r'\b[a-zA-ZÀ-ÿ]+\b', text)
    if not words:
        return text
    en_count = sum(1 for w in words if w.lower() in _EN_COMMON_WORDS)
    pt_count = sum(1 for w in words if w.lower() in _PT_COMMON_WORDS)
    total = len(words)
    if total == 0:
        return text
    en_ratio = en_count / total
    pt_ratio = pt_count / total
    if en_ratio > 0.6 and pt_ratio < 0.15:
        if VERBOSE:
            LOGGER.debug(
                "language reject: pt expected, en_ratio=%.3f pt_ratio=%.3f",
                en_ratio, pt_ratio,
            )
        return ""
    if pt_ratio >= en_ratio and en_count > 0:
        for en_word, pt_word in _EN_TO_PT.items():
            pattern = re.compile(r'\b' + re.escape(en_word) + r'\b', re.IGNORECASE)

            def _replace(m, repl=pt_word):
                orig = m.group(0)
                if orig.isupper():
                    return repl.upper()
                if orig[0].isupper():
                    return repl[0].upper() + repl[1:]
                return repl

            text = pattern.sub(_replace, text)
    return text


def fix_french_typography(text):
    """Apply French typographic rules."""
    text = _TYPO_ELLIPSIS.sub("\u2026", text)
    text = _TYPO_EN_QUOTES.sub(f"\u00ab{_NBSP}\\1{_NBSP}\u00bb", text)
    text = _TYPO_BEFORE_THIN.sub(f"{_NNBSP}\\1", text)
    text = _TYPO_BEFORE_COLON.sub(f"{_NBSP}\\1", text)
    text = _TYPO_AFTER_LGUILL.sub(f"\u00ab{_NBSP}", text)
    text = _TYPO_BEFORE_RGUILL.sub(f"{_NBSP}\u00bb", text)
    return text


# ── Dictionary loading ───────────────────────────────────────────────

_DICT_RE = re.compile(r"^\s*\[([a-z]{2}|\*)\]\s*(.+?)=(.+?)\s*$")


def _parse_dictionary(path):
    """Parse a dictionary file, returns [(word, word_re, replacement)]."""
    entries = []
    if not os.path.isfile(path):
        return entries
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = _DICT_RE.match(line)
            if not m:
                continue
            lang_tag, word, replacement = m.groups()
            if lang_tag != "*" and LANG and lang_tag != LANG:
                continue
            word = word.strip()
            replacement = replacement.strip()
            try:
                word_re = re.compile(
                    r"\b" + re.escape(word) + r"\b",
                    re.IGNORECASE,
                )
            except re.error:
                continue
            entries.append((word, word_re, replacement))
    return entries


def load_dictionary():
    """Load system dictionary, then user dictionary."""
    entries = []
    for candidate in SYSTEM_DICT_CANDIDATES:
        if os.path.isfile(candidate):
            entries.extend(_parse_dictionary(candidate))
            break
    entries.extend(_parse_dictionary(USER_DICT))
    return entries


# Optional jellyfish import for phonetic matching
try:
    import jellyfish

    _HAS_JELLYFISH = True
except ImportError:
    _HAS_JELLYFISH = False

_FUZZY_THRESHOLD = 0.85


def apply_dictionary(text, entries, fuzzy=True):
    """Apply dictionary with case preservation + phonetic fallback."""
    # Phase 1: exact replacement via regex (fast)
    matched_spans = set()
    for word, word_re, replacement in entries:

        def _replace(m, repl=replacement):
            matched_spans.add((m.start(), m.end()))
            orig = m.group(0)
            if orig.isupper():
                return repl.upper()
            if orig[0].isupper():
                return repl[0].upper() + repl[1:]
            return repl

        text = word_re.sub(_replace, text)

    # Phase 2: jellyfish phonetic matching (if enabled)
    if not fuzzy or not _HAS_JELLYFISH or not entries:
        return text

    words_in_text = re.findall(r"\b[a-zA-ZÀ-ÿ]{2,}\b", text)
    if not words_in_text:
        return text

    # Build an index of dictionary keys
    dict_keys = [(w.lower(), replacement) for w, _, replacement in entries]

    for text_word in set(words_in_text):
        text_word_lower = text_word.lower()
        best_score = 0.0
        best_replacement = None
        for dict_word, replacement in dict_keys:
            if dict_word == text_word_lower:
                break  # already matched in phase 1
            score = jellyfish.jaro_winkler_similarity(text_word_lower, dict_word)
            if score > best_score and score >= _FUZZY_THRESHOLD:
                best_score = score
                best_replacement = replacement
        else:
            # No break → no exact match → apply fuzzy
            if best_replacement:
                pat = re.compile(r"\b" + re.escape(text_word) + r"\b")

                def _fuzzy_replace(m, repl=best_replacement):
                    orig = m.group(0)
                    if orig.isupper():
                        return repl.upper()
                    if orig[0].isupper():
                        return repl[0].upper() + repl[1:]
                    return repl

                text = pat.sub(_fuzzy_replace, text)

    return text


# ── Capitalisation ───────────────────────────────────────────────────

_CAP_AFTER_PUNCT = re.compile(r"([.!?\u2026])(\s+)([a-zà-ÿ])")
_CAP_AFTER_NEWLINE = re.compile(r"(\n\s*)([a-zà-ÿ])")


def fix_capitalization(text):
    """Capitalize after end punctuation and at the start of text."""
    if not text:
        return text
    # Start of text
    if text[0].islower():
        text = text[0].upper() + text[1:]
    # After . ! ? … — preserve line breaks
    text = _CAP_AFTER_PUNCT.sub(
        lambda m: m.group(1) + m.group(2) + m.group(3).upper(), text
    )
    # After line break
    text = _CAP_AFTER_NEWLINE.sub(lambda m: m.group(1) + m.group(2).upper(), text)
    return text


# ── LLM correction ───────────────────────────────────────────────────

DEFAULT_PROMPT = (
    "<role>\n"
    "Ton rôle est de corriger une transcription provenant d'un ASR. "
    "Tu n'es pas un assistant conversationnel.\n"
    "</role>\n"
    "<instructions>\n"
    "- Corrige l'orthographe et la grammaire.\n"
    "- Supprime les répétitions et hésitations.\n"
    "- Ne modifie jamais le sens ni le contenu.\n"
    "- Ne réponds pas aux questions et ne les commente pas.\n"
    "- Ne génère aucun commentaire ni introduction.\n"
    "- Si tu ne sais pas ou qu'il n'y a rien à modifier, "
    "renvoie la transcription telle quelle.\n"
    "</instructions>\n"
    "{additional_context}"
    "<input>{text}</input>"
)

PROMPT_PATH = os.path.join(XDG_CONFIG, "dictee", "llm-prompt.txt")


def _load_prompt():
    if os.path.isfile(PROMPT_PATH):
        with open(PROMPT_PATH, encoding="utf-8") as f:
            return f.read().strip()
    return DEFAULT_PROMPT


def _http_json(url, payload, headers, timeout):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        ValueError,
        OSError,
    ):
        return None


def ollama_postprocess(text, prompt, model, timeout):
    env = os.environ.copy()
    if _env_bool("DICTEE_LLM_CPU", "false"):
        env["OLLAMA_NUM_GPU"] = "0"
    try:
        result = subprocess.run(
            ["ollama", "run", "--hidethinking", model, prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        _llm_debug(
            "ollama rc={} stdout_len={} stderr_len={}".format(
                result.returncode,
                len((result.stdout or "").strip()),
                len((result.stderr or "").strip()),
            )
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        _llm_debug(f"ollama timeout after {timeout}s")
        return None
    except (FileNotFoundError, OSError) as exc:
        _llm_debug(f"ollama exec error: {exc}")
        return None
    return None


def openai_postprocess(text, prompt, model, timeout):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    payload = {
        "model": model,
        "input": prompt,
    }
    data = _http_json(
        "https://api.openai.com/v1/responses",
        payload,
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout,
    )
    if not data:
        return None
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    for item in data.get("output", []):
        for content in item.get("content", []):
            text_value = content.get("text")
            if isinstance(text_value, str) and text_value.strip():
                return text_value.strip()
    return None


def openrouter_postprocess(text, prompt, model, timeout):
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None
    data = _http_json(
        "https://openrouter.ai/api/v1/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        },
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://dictee.local",
            "X-Title": "dictee",
        },
        timeout,
    )
    if not data:
        return None
    for choice in data.get("choices", []):
        message = choice.get("message", {})
        text_value = message.get("content")
        if isinstance(text_value, str) and text_value.strip():
            return text_value.strip()
    return None


def gemini_postprocess(text, prompt, model, timeout):
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    data = _http_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
        {"contents": [{"parts": [{"text": prompt}]}]},
        {"Content-Type": "application/json"},
        timeout,
    )
    if not data:
        return None
    for candidate in data.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            text_value = part.get("text")
            if isinstance(text_value, str) and text_value.strip():
                return text_value.strip()
    return None


def anthropic_postprocess(text, prompt, model, timeout):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    data = _http_json(
        "https://api.anthropic.com/v1/messages",
        {
            "model": model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        },
        {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        timeout,
    )
    if not data:
        return None
    for item in data.get("content", []):
        text_value = item.get("text")
        if isinstance(text_value, str) and text_value.strip():
            return text_value.strip()
    return None


def groq_postprocess(text, prompt, model, timeout):
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    data = _http_json(
        "https://api.groq.com/openai/v1/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        },
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout,
    )
    if not data:
        return None
    for choice in data.get("choices", []):
        message = choice.get("message", {})
        text_value = message.get("content")
        if isinstance(text_value, str) and text_value.strip():
            return text_value.strip()
    return None


def _adaptive_timeout(base, text_len):
    extra = (text_len // 1000) * 2
    return min(base + extra, 120)


def llm_postprocess(text):
    """Send text to the configured LLM provider for grammatical correction."""
    provider = (
        os.environ.get("DICTEE_LLM_PROVIDER", "ollama").strip().lower() or "ollama"
    )
    model = os.environ.get("DICTEE_LLM_MODEL", "gemma3:4b")
    base_timeout = _env_int("DICTEE_LLM_TIMEOUT", 10)
    timeout = _adaptive_timeout(base_timeout, len(text))
    additional_context = os.environ.get("DICTEE_LLM_ADDITIONAL_CONTEXT", "").strip()
    additional_context_block = ""
    if additional_context:
        additional_context_block = (
            f"<additional_context>\n{additional_context}\n</additional_context>\n"
        )
    if VERBOSE:
        LOGGER.debug("llm provider=%s model=%s timeout=%ss", provider, model, timeout)
    _llm_debug(f"llm provider={provider} model={model} timeout={timeout}s")
    prompt_tpl = _load_prompt()
    prompt = prompt_tpl.format(
        text=text,
        additional_context=additional_context_block,
    )

    handlers = {
        "ollama": ollama_postprocess,
        "openai": openai_postprocess,
        "openrouter": openrouter_postprocess,
        "gemini": gemini_postprocess,
        "google": gemini_postprocess,
        "anthropic": anthropic_postprocess,
        "groq": groq_postprocess,
    }
    handler = handlers.get(provider, ollama_postprocess)
    try:
        corrected = handler(text, prompt, model, timeout)
        if corrected:
            if VERBOSE:
                LOGGER.debug("llm output accepted")
            _llm_debug("llm output accepted")
            return corrected
        if VERBOSE:
            LOGGER.debug("llm returned empty output; keeping original text")
        _llm_debug("llm returned empty output; keeping original text")
    except Exception as exc:
        if VERBOSE:
            LOGGER.debug("llm failed (%s); keeping original text", exc)
        _llm_debug(f"llm failed ({exc}); keeping original text")
    return text  # fallback: unchanged text


# ── Main ─────────────────────────────────────────────────────────────


def main():
    global VERBOSE
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show internal post-processing steps (stderr)",
    )
    args = parser.parse_args()
    VERBOSE = (
        args.verbose
        or _env_bool("DICTEE_PP_VERBOSE", "false")
        or _env_bool("DICTEE_VERBOSE", "false")
    )
    _configure_logging(VERBOSE)

    text = sys.stdin.read()
    if VERBOSE:
        LOGGER.debug("start lang=%s", LANG or "auto")
        LOGGER.debug("input raw len=%d preview=%r", len(text), _preview_text(text))
    # Remove the trailing \n added by echo (but keep intentional \n)
    if text.endswith("\n"):
        text = text[:-1]
    if not text.strip():
        if VERBOSE:
            LOGGER.debug("input empty/whitespace, nothing to process")
        sys.stdout.write(text)
        return

    # 0. Wrong language detection (multilingual ASR confused on short audio)
    # Rules first try to recover known voice commands
    # (e.g. Cyrillic "А линия" → \n for "à la ligne").
    # If after rules the text is still in the wrong script, reject it.

    # 1-5. Regex rules (annotations, hesitations, voice commands,
    #       dedup, punctuation, basic elisions, cleanup)
    start = time.perf_counter()
    before = text
    rules = load_rules()
    if VERBOSE:
        LOGGER.debug("rules loaded=%d", len(rules))
    if rules:
        text = apply_rules(text, rules)
    _log_stage("rules", before, text, (time.perf_counter() - start) * 1000.0)
    # Trim leading spaces (removed hesitations/annotations)
    # but preserve trailing \n (voice commands "à la ligne")
    start = time.perf_counter()
    before = text
    text = text.lstrip(" \t").rstrip(" \t")
    _log_stage("trim", before, text, (time.perf_counter() - start) * 1000.0)

    # 5b. Wrong language rejection (after rules, which may have converted known commands)
    if LANG:
        _LATIN_LANGS = {
            "fr",
            "en",
            "de",
            "es",
            "it",
            "pt",
            "nl",
            "pl",
            "ro",
            "cs",
            "sv",
            "da",
            "no",
            "fi",
            "hu",
            "tr",
        }
        _CYRILLIC_LANGS = {"ru", "uk", "bg", "sr", "mk", "be"}
        letters = [c for c in text if c.isalpha()]
        if letters:
            cyrillic = sum(1 for c in letters if "\u0400" <= c <= "\u04ff")
            ratio = cyrillic / len(letters)
            if LANG in _LATIN_LANGS and ratio > 0.5:
                if VERBOSE:
                    LOGGER.debug(
                        "language reject: latin expected, cyrillic ratio=%.3f", ratio
                    )
                sys.stdout.write("")
                return
            if LANG in _CYRILLIC_LANGS and ratio < 0.2:
                if VERBOSE:
                    LOGGER.debug(
                        "language reject: cyrillic expected, cyrillic ratio=%.3f", ratio
                    )
                sys.stdout.write("")
                return

    # 5c. PT/EN language mixing detection and correction
    if _env_bool("DICTEE_PP_LANG_MIXING", "true"):
        start = time.perf_counter()
        before = text
        text = fix_pt_en_mixing(text)
        _log_stage("pt_en_mixing", before, text, (time.perf_counter() - start) * 1000.0)
        if not text:
            sys.stdout.write("")
            return

    # 6. Advanced French elisions (with aspirated h)
    if LANG == "fr" and _env_bool("DICTEE_PP_ELISIONS"):
        start = time.perf_counter()
        before = text
        text = fix_elisions(text)
        _log_stage("elisions", before, text, (time.perf_counter() - start) * 1000.0)

    # 7. Number → digit conversion
    if _env_bool("DICTEE_PP_NUMBERS"):
        start = time.perf_counter()
        before = text
        text = convert_numbers(text)
        _log_stage("numbers", before, text, (time.perf_counter() - start) * 1000.0)

    # 8. French typography (non-breaking spaces)
    if LANG == "fr" and _env_bool("DICTEE_PP_TYPOGRAPHY"):
        start = time.perf_counter()
        before = text
        text = fix_french_typography(text)
        _log_stage("typography", before, text, (time.perf_counter() - start) * 1000.0)

    # 8b. Portuguese typography
    if LANG == "pt" and _env_bool("DICTEE_PP_TYPOGRAPHY"):
        start = time.perf_counter()
        before = text
        text = fix_portuguese_typography(text)
        _log_stage("pt_typography", before, text, (time.perf_counter() - start) * 1000.0)

    # 9. (final cleanup already in regex rules step 5)

    # 10. Dictionary (system + personal, with phonetic matching)
    start = time.perf_counter()
    before = text
    dictionary = load_dictionary()
    if VERBOSE:
        LOGGER.debug(
            "dictionary entries=%d fuzzy=%s",
            len(dictionary),
            _env_bool("DICTEE_PP_FUZZY_DICT"),
        )
    if dictionary:
        text = apply_dictionary(
            text,
            dictionary,
            fuzzy=_env_bool("DICTEE_PP_FUZZY_DICT"),
        )
    _log_stage("dictionary", before, text, (time.perf_counter() - start) * 1000.0)

    # 11. Capitalization
    if _env_bool("DICTEE_PP_CAPITALIZATION"):
        start = time.perf_counter()
        before = text
        text = fix_capitalization(text)
        _log_stage(
            "capitalization", before, text, (time.perf_counter() - start) * 1000.0
        )

    # 12. LLM correction (optional)
    if _env_bool("DICTEE_LLM_POSTPROCESS", "false"):
        start = time.perf_counter()
        before = text
        text = llm_postprocess(text)
        _log_stage("llm", before, text, (time.perf_counter() - start) * 1000.0)

    if VERBOSE:
        LOGGER.debug("done output len=%d preview=%r", len(text), _preview_text(text))
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
