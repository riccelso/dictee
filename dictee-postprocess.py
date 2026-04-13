#!/usr/bin/python3
"""dictee-postprocess — post-processing filter for voice dictation.

Reads transcribed text from stdin, applies sequentially:
  1.  Regex rules (annotations, hesitations, voice commands, dedup, punctuation, elisions)
  2.  Advanced French elisions (with h aspirés)
  3.  Number to digit conversion (text2num, optional)
  4.  French typography (non-breaking spaces)
  5.  Dictionary (system + personal, with phonetic jellyfish matching)
  6.  Capitalization
  7.  Optional LLM adjustment (grammar fix / better text, with chunking for large text)

Writes the result to stdout.

Configuration via environment variables:
  DICTEE_LANG_SOURCE       -- source language (fr, en, de, ...) for rule filtering
  DICTEE_PP_ELISIONS       -- true/false (default: true)  -- advanced French elisions
  DICTEE_PP_NUMBERS        -- true/false (default: true)  -- number to digit conversion
  DICTEE_PP_TYPOGRAPHY     -- true/false (default: true)  -- French typography
  DICTEE_PP_CAPITALIZATION -- true/false (default: true)  -- auto-capitalization
  DICTEE_PP_FUZZY_DICT     -- true/false (default: true)  -- phonetic dictionary matching
  DICTEE_LLM_POSTPROCESS   -- true/false (default: false) -- LLM adjustment
  DICTEE_LLM_PROVIDER      -- ollama/openai/openrouter/gemini/anthropic/groq (default: ollama)
  DICTEE_LLM_MODEL         -- LLM model (default: gemma3:4b)
  DICTEE_LLM_TIMEOUT       -- base timeout in seconds (default: 10, adaptive scaling for large text)
  DICTEE_LLM_CPU           -- true/false (ollama only)
  DICTEE_LLM_ADDITIONAL_CONTEXT -- additional context injected into LLM prompt (domain jargon)
  DICTEE_LLM_DEBUG         -- true/false (detailed LLM logs to stderr)

Remote API keys read from environment:
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

# ── Chemins ──────────────────────────────────────────────────────────

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
    """Lit une variable d'environnement booléenne."""
    return os.environ.get(var, default).lower() == "true"


def _env_int(var, default):
    """Lit une variable d'environnement entière."""
    try:
        return int(os.environ.get(var, str(default)))
    except (TypeError, ValueError):
        return default


def _configure_logging(verbose=False):
    """Configure le logger du script."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="[dictee-postprocess] %(message)s",
        stream=sys.stderr,
    )


def _preview_text(text, max_len=120):
    """Retourne un aperçu compact du texte pour logs."""
    escaped = text.replace("\n", "\\n")
    if len(escaped) <= max_len:
        return escaped
    return escaped[: max_len - 3] + "..."


def _log_stage(name, before, after, elapsed_ms):
    """Log standard d'une étape de pipeline."""
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
    """Log LLM debug indépendant du mode verbose pipeline."""
    if _env_bool("DICTEE_LLM_DEBUG", "false"):
        print(f"[dictee-postprocess] {msg}", file=sys.stderr)


# ── Chargement des règles regex ──────────────────────────────────────

_RULE_RE = re.compile(r"^\s*\[([a-z]{2}|\*)\]\s*/(.+)/(.+)/([igm]*)\s*$")

# Règles avec remplacement vide : /PATTERN//FLAGS
_RULE_EMPTY_RE = re.compile(r"^\s*\[([a-z]{2}|\*)\]\s*/(.+)//([igm]*)\s*$")


def _parse_rules(path):
    """Parse un fichier de règles, retourne [(pattern_compiled, replacement)]."""
    rules = []
    if not os.path.isfile(path):
        return rules
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Essayer d'abord le remplacement vide
            m = _RULE_EMPTY_RE.match(line)
            if m:
                lang_tag, pattern, flags_str = m.groups()
                replacement = ""
            else:
                m = _RULE_RE.match(line)
                if not m:
                    continue
                lang_tag, pattern, replacement, flags_str = m.groups()
            # Filtrer par langue
            if lang_tag != "*" and LANG and lang_tag != LANG:
                continue
            flags = 0
            if "i" in flags_str:
                flags |= re.IGNORECASE
            if "m" in flags_str:
                flags |= re.MULTILINE
            # \s dans les classes [,.\s] ne doit pas manger les \n produits par d'autres règles
            # Remplacer \s par \t  (espace + tab) dans les classes de caractères
            pattern = re.sub(
                r"\[([^\]]*?)\\s([^\]]*?)\]",
                lambda m: "[" + m.group(1) + r" \t" + m.group(2) + "]",
                pattern,
            )
            try:
                compiled = re.compile(pattern, flags)
            except re.error:
                continue
            # Convertir les séquences d'échappement dans le remplacement
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
    """Charge les règles système puis utilisateur."""
    rules = []
    for candidate in SYSTEM_RULES_CANDIDATES:
        if os.path.isfile(candidate):
            rules.extend(_parse_rules(candidate))
            break
    rules.extend(_parse_rules(USER_RULES))
    return rules


def apply_rules(text, rules):
    """Applique les règles regex séquentiellement."""
    for pattern, replacement in rules:
        text = pattern.sub(replacement, text)
    return text


# ── Élisions françaises avancées ─────────────────────────────────────

# Mots commençant par h aspiré (PAS d'élision)
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
# h muet suivi de voyelle (mais PAS h aspiré)
_H_MUET_VOWEL = f"[hH]{_VOWEL_PATTERN}"

# Pré-compiler les patterns d'élision
_H_ASPIRE_SORTED = sorted(H_ASPIRE, key=len, reverse=True)
_H_ASPIRE_RE = "|".join(re.escape(h) for h in _H_ASPIRE_SORTED)
_ELISION_PATTERNS = []
for _word, _elided in ELISION_WORDS.items():
    # Matche : mot + espace + (voyelle OU h muet), sauf h aspiré
    _pat = re.compile(
        rf"\b{re.escape(_word)}\s+(?!(?:{_H_ASPIRE_RE})\b)({_VOWEL_PATTERN}\w*|{_H_MUET_VOWEL}\w*)",
        re.IGNORECASE,
    )
    _ELISION_PATTERNS.append((_pat, _elided))

_SI_IL_RE = re.compile(r"\bsi\s+(ils?)\b", re.IGNORECASE)


def fix_elisions(text):
    """Corrige les élisions manquantes (je ai → j'ai) avec h aspirés."""
    for pattern, elided in _ELISION_PATTERNS:

        def _elide(m, e=elided):
            rest = m.group(1)
            # Préserver la casse : si le mot original commençait par majuscule
            # et l'élision est en début de phrase, garder la majuscule sur l'élision
            return (
                e + rest.lower()
                if rest[0].isupper() and len(rest) > 1 and rest[1:] == rest[1:].lower()
                else e + rest
            )

        text = pattern.sub(_elide, text)
    text = _SI_IL_RE.sub(r"s'\1", text)
    return text


# ── Conversion nombres (text2num) ────────────────────────────────────

try:
    from text_to_num import alpha2digit

    _HAS_TEXT2NUM = True
except ImportError:
    _HAS_TEXT2NUM = False

_TEXT2NUM_LANGS = frozenset({"fr", "en", "es", "pt", "de", "it", "nl"})


def convert_numbers(text):
    """Convertit les nombres en toutes lettres en chiffres."""
    if not _HAS_TEXT2NUM or LANG not in _TEXT2NUM_LANGS:
        return text
    try:
        return alpha2digit(text, LANG)
    except Exception:
        return text


# ── Typographie française ────────────────────────────────────────────

_NBSP = "\u00a0"  # espace insécable (avant :, après «, avant »)
_NNBSP = "\u202f"  # espace fine insécable (avant ; ? !)

# Pré-compiler les patterns de typographie
_TYPO_BEFORE_THIN = re.compile(
    r"(?<=\S)\s*([;!?])"
)  # espace fine insécable avant ; ! ? (sauf début de ligne)
_TYPO_BEFORE_COLON = re.compile(
    r"(?<=\S)\s*(:)"
)  # espace insécable avant : (sauf début de ligne)
_TYPO_AFTER_LGUILL = re.compile(r"«\s*")  # espace après «
_TYPO_BEFORE_RGUILL = re.compile(r"\s*»")  # espace avant »
_TYPO_ELLIPSIS = re.compile(r"\.{3,}")  # ... → …
_TYPO_EN_QUOTES = re.compile(r'"([^"]+)"')  # "x" → « x »


def fix_french_typography(text):
    """Applique les règles typographiques françaises."""
    # Points de suspension
    text = _TYPO_ELLIPSIS.sub("\u2026", text)
    # Guillemets anglais → français
    text = _TYPO_EN_QUOTES.sub(f"\u00ab{_NBSP}\\1{_NBSP}\u00bb", text)
    # Espaces insécables avant ponctuation haute
    text = _TYPO_BEFORE_THIN.sub(f"{_NNBSP}\\1", text)
    text = _TYPO_BEFORE_COLON.sub(f"{_NBSP}\\1", text)
    # Espaces autour des guillemets
    text = _TYPO_AFTER_LGUILL.sub(f"\u00ab{_NBSP}", text)
    text = _TYPO_BEFORE_RGUILL.sub(f"{_NBSP}\u00bb", text)
    return text


# ── Chargement du dictionnaire ───────────────────────────────────────

_DICT_RE = re.compile(r"^\s*\[([a-z]{2}|\*)\]\s*(.+?)=(.+?)\s*$")


def _parse_dictionary(path):
    """Parse un fichier de dictionnaire, retourne [(word, word_re, replacement)]."""
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
    """Charge le dictionnaire système puis utilisateur."""
    entries = []
    for candidate in SYSTEM_DICT_CANDIDATES:
        if os.path.isfile(candidate):
            entries.extend(_parse_dictionary(candidate))
            break
    entries.extend(_parse_dictionary(USER_DICT))
    return entries


# Import optionnel jellyfish pour matching phonétique
try:
    import jellyfish

    _HAS_JELLYFISH = True
except ImportError:
    _HAS_JELLYFISH = False

_FUZZY_THRESHOLD = 0.85


def apply_dictionary(text, entries, fuzzy=True):
    """Applique le dictionnaire avec préservation de casse + fallback phonétique."""
    # Phase 1 : remplacement exact par regex (rapide)
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

    # Phase 2 : matching phonétique jellyfish (si activé)
    if not fuzzy or not _HAS_JELLYFISH or not entries:
        return text

    words_in_text = re.findall(r"\b[a-zA-ZÀ-ÿ]{2,}\b", text)
    if not words_in_text:
        return text

    # Construire un index des clés du dictionnaire
    dict_keys = [(w.lower(), replacement) for w, _, replacement in entries]

    for text_word in set(words_in_text):
        text_word_lower = text_word.lower()
        best_score = 0.0
        best_replacement = None
        for dict_word, replacement in dict_keys:
            if dict_word == text_word_lower:
                break  # déjà matché en phase 1
            score = jellyfish.jaro_winkler_similarity(text_word_lower, dict_word)
            if score > best_score and score >= _FUZZY_THRESHOLD:
                best_score = score
                best_replacement = replacement
        else:
            # Pas de break → pas de match exact → appliquer fuzzy
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
    """Capitalise après ponctuation de fin et en début de texte."""
    if not text:
        return text
    # Début du texte
    if text[0].islower():
        text = text[0].upper() + text[1:]
    # Après . ! ? … — préserver les sauts de ligne
    text = _CAP_AFTER_PUNCT.sub(
        lambda m: m.group(1) + m.group(2) + m.group(3).upper(), text
    )
    # Après saut de ligne
    text = _CAP_AFTER_NEWLINE.sub(lambda m: m.group(1) + m.group(2).upper(), text)
    return text


# ── Correction LLM ──────────────────────────────────────────────────

DEFAULT_PROMPT = (
    "<role>\n"
    "You are a voice transcription post-processor. "
    "You are NOT a conversational assistant.\n"
    "You MUST output ONLY the processed text, nothing else.\n"
    "</role>\n"
    "<task>\n"
    "Analyze the transcription and apply ONE of two modes:\n"
    "\n"
    "MODE 1 - GRAMMAR FIX (apply when):\n"
    "- The text is conversational or spoken language\n"
    "- Contains self-corrections (e.g. 'I mean', 'actually', 'quer dizer', 'alias')\n"
    "- Has broken reasoning that needs linearization\n"
    "- Contains ASR errors, grammar mistakes, or wrong domain terms\n"
    "\n"
    "In this mode:\n"
    "- Linearize self-corrections into clean flowing text\n"
    "- Fix grammar, spelling, and punctuation\n"
    "- Correct technical/domain terms using the additional context below\n"
    "- NEVER change meaning or add information\n"
    "- Remove repetitions and hesitations\n"
    "\n"
    "MODE 2 - BETTER TEXT (apply when AND ONLY WHEN you are CONFIDENT):\n"
    "- The text is clearly an explanation or reasoning "
    "(has beginning, development, conclusion)\n"
    "- The speaker is constructing a structured argument\n"
    "- You can confidently identify the logical flow\n"
    "\n"
    "In this mode:\n"
    "- Improve clarity and robustness of the explanation\n"
    "- Strengthen the reasoning structure\n"
    "- Use precise vocabulary\n"
    "- Keep the speaker's voice and intent\n"
    "\n"
    "IMPORTANT: If you are unsure which mode to apply, "
    "ALWAYS use GRAMMAR FIX.\n"
    "If you cannot confidently identify explanatory structure, "
    "use GRAMMAR FIX.\n"
    "Grammar Fix is the safe default.\n"
    "</task>\n"
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
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        _llm_debug(f"http {exc.code} from {url}: {body}")
    except (
        urllib.error.URLError,
        TimeoutError,
        ValueError,
        OSError,
    ) as exc:
        _llm_debug(f"http error from {url}: {exc}")
    return None


def ollama_postprocess(text, prompt, model, timeout):
    env = os.environ.copy()
    if _env_bool("DICTEE_LLM_CPU", "false"):
        env["OLLAMA_NUM_GPU"] = "0"
    try:
        proc = subprocess.Popen(
            ["ollama", "run", "--hidethinking", model],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        stdout, stderr = proc.communicate(input=prompt.encode("utf-8"), timeout=timeout)
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        _llm_debug(
            "ollama rc={} stdout_len={} stderr_len={} prompt_len={}".format(
                proc.returncode,
                len(stdout_text.strip()),
                len(stderr_text.strip()),
                len(prompt),
            )
        )
        if proc.returncode != 0:
            _llm_debug(f"ollama stderr: {stderr_text[:500]}")
        if proc.returncode == 0 and stdout_text.strip():
            return stdout_text.strip()
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


def _chunk_text(text, max_chars=4000):
    """Split text on sentence boundaries into chunks of max_chars."""
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+|\n", text)
    chunks = []
    current = ""
    for sentence in sentences:
        if not sentence.strip():
            continue
        if len(current) + len(sentence) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = sentence
        else:
            current = current + " " + sentence if current else sentence
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [text]


def llm_postprocess(text):
    """Envoie le texte au provider LLM configure pour correction grammaticale."""
    provider = (
        os.environ.get("DICTEE_LLM_PROVIDER", "ollama").strip().lower() or "ollama"
    )
    model = os.environ.get("DICTEE_LLM_MODEL", "gemma3:4b")
    base_timeout = _env_int("DICTEE_LLM_TIMEOUT", 10)
    additional_context = os.environ.get("DICTEE_LLM_ADDITIONAL_CONTEXT", "").strip()
    additional_context_block = ""
    if additional_context:
        additional_context_block = (
            f"<additional_context>\n{additional_context}\n</additional_context>\n"
        )

    chunks = _chunk_text(text)
    needs_chunking = len(chunks) > 1
    _llm_debug(
        f"llm provider={provider} model={model} base_timeout={base_timeout}s "
        f"text_len={len(text)} chunks={len(chunks)}"
    )

    prompt_tpl = _load_prompt()
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

    results = []
    for chunk in chunks:
        timeout = min(base_timeout + (len(chunk) / 1000) * 2, 60)
        prompt = prompt_tpl.format(
            text=chunk,
            additional_context=additional_context_block,
        )
        _llm_debug(f"chunk len={len(chunk)} timeout={timeout:.1f}s")
        try:
            corrected = handler(chunk, prompt, model, timeout)
            if corrected:
                results.append(corrected)
            else:
                _llm_debug("chunk returned empty; keeping original")
                results.append(chunk)
        except Exception as exc:
            _llm_debug(f"chunk failed ({exc}); keeping original")
            results.append(chunk)

    final = "\n".join(results) if needs_chunking else results[0]
    if VERBOSE:
        LOGGER.debug("llm output accepted, chunks=%d", len(chunks))
    _llm_debug("llm output accepted")
    return final


# ── Main ─────────────────────────────────────────────────────────────


def main():
    global VERBOSE
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="affiche les étapes internes de post-traitement (stderr)",
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
    # Supprimer le \n ajouté par echo (mais garder les \n intentionnels)
    if text.endswith("\n"):
        text = text[:-1]
    if not text.strip():
        if VERBOSE:
            LOGGER.debug("input empty/whitespace, nothing to process")
        sys.stdout.write(text)
        return

    # 0. Détection de mauvaise langue (ASR multilingue confus sur audio court)
    # Les règles tentent d'abord de récupérer les commandes vocales connues
    # (ex: cyrillique "А линия" → \n pour "à la ligne").
    # Si après les règles le texte est toujours dans le mauvais script, on le rejette.

    # 1-5. Règles regex (annotations, hésitations, commandes vocales,
    #       dédup, ponctuation, élisions basiques, nettoyage)
    start = time.perf_counter()
    before = text
    rules = load_rules()
    if VERBOSE:
        LOGGER.debug("rules loaded=%d", len(rules))
    if rules:
        text = apply_rules(text, rules)
    _log_stage("rules", before, text, (time.perf_counter() - start) * 1000.0)
    # Nettoyer les espaces en début (hésitations/annotations supprimées)
    # mais préserver les \n de fin (commandes vocales "à la ligne")
    start = time.perf_counter()
    before = text
    text = text.lstrip(" \t").rstrip(" \t")
    _log_stage("trim", before, text, (time.perf_counter() - start) * 1000.0)

    # 5b. Rejet mauvaise langue (après les règles, qui ont pu convertir les commandes connues)
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

    # 6. Élisions françaises avancées (avec h aspirés)
    if LANG == "fr" and _env_bool("DICTEE_PP_ELISIONS"):
        start = time.perf_counter()
        before = text
        text = fix_elisions(text)
        _log_stage("elisions", before, text, (time.perf_counter() - start) * 1000.0)

    # 7. Conversion nombres → chiffres
    if _env_bool("DICTEE_PP_NUMBERS"):
        start = time.perf_counter()
        before = text
        text = convert_numbers(text)
        _log_stage("numbers", before, text, (time.perf_counter() - start) * 1000.0)

    # 8. Typographie française (espaces insécables)
    if LANG == "fr" and _env_bool("DICTEE_PP_TYPOGRAPHY"):
        start = time.perf_counter()
        before = text
        text = fix_french_typography(text)
        _log_stage("typography", before, text, (time.perf_counter() - start) * 1000.0)

    # 9. (nettoyage final déjà dans les règles regex étape 5)

    # 10. Dictionnaire (système + personnel, avec matching phonétique)
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

    # 11. Capitalisation
    if _env_bool("DICTEE_PP_CAPITALIZATION"):
        start = time.perf_counter()
        before = text
        text = fix_capitalization(text)
        _log_stage(
            "capitalization", before, text, (time.perf_counter() - start) * 1000.0
        )

    # 12. Correction LLM (optionnelle)
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
