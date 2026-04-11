# Analysis of Murmure — Features for post-v1.0.0

> Reference: [github.com/Kieirra/murmure](https://github.com/Kieirra/murmure) v1.7.0 (February 2026)
> Objective: evaluate Murmure's features for future integration into dictee.

## Overview

Murmure is a local, private voice dictation application, based on the same Parakeet TDT 0.6B v3 model.
Stack: Tauri + React + TypeScript (frontend), Rust (backend). Cross-platform (Windows, macOS, Linux).
License AGPL v3, 299 commits.

## Comparative Positioning

| Aspect | dictee | Murmure |
|--------|--------|---------|
| **Platforms** | Linux only | Windows, macOS, Linux |
| **Stack** | Shell + Rust + PyQt6 + QML | Tauri + React + Rust |
| **ASR Backends** | 3 (Parakeet, Vosk, faster-whisper) | 1 (Parakeet) |
| **Diarization** | Yes (Sortformer, 4 speakers) | No |
| **Daemon mode** | Yes (near-instant transcriptions) | No |
| **Native DE widget** | KDE Plasma 6 (5 animations) | No |
| **System integration** | systemd, dotool, PipeWire, D-Bus | Tauri auto-start |
| **Translation** | 4 backends (Google, Bing, LibreTranslate, ollama) | Via LLM only |
| **Post-processing rules** | 2 hardcoded FR rules | Full engine (regex, smart, exact) |
| **Dictionary** | No | Beider-Morse phonetic correction |
| **LLM post-processing** | No (translation only) | Ollama + OpenAI API, multi-prompts |
| **Voice activation** | No (push-to-talk) | VAD + wake word + fuzzy matching |
| **License** | GPL-3.0 | AGPL-3.0 |

## Features to Consider

### 1. Configurable Rules Engine

**Priority: high** — Medium effort, high value-add.

#### What Murmure Does

5-step pipeline in `src-tauri/src/formatting_rules/formatter.rs`:

1. **Short text correction**: if ≤N words → lowercase + remove trailing punctuation (preserves acronyms and mixed-case words like "iPhone")
2. **Custom rules** with 3 matching modes:
   - **Smart** (default): case-insensitive, handles spaces/punctuation around the match
   - **Exact**: literal replacement
   - **Regex**: full pattern with capture groups (`$1`, `$2`)
3. **Punctuation spacing**: space before `?` and `!`
4. **Number conversion**: text→digits via `text2num` (7 languages: FR, EN, DE, IT, ES, NL, PT)
5. **Trailing space** at the end of transcription

UX: drag-and-drop interface, rules are reorderable/toggleable, JSON import/export.

#### Current State in dictee

Two hardcoded rules in the shell script `dictee`:
- "point à la ligne" → line break
- "trois petits points" → `...`

#### Implementation Options for dictee

- **Option A — Shell script**: rules file `~/.config/dictee-rules.conf` (format `pattern|replacement|mode`), applied via `sed`/`awk` after transcription. Simple but limited.
- **Option B — Python**: Python module in `dictee-setup.py` or standalone, with PyQt6 UI for editing rules. More feature-rich, consistent with the existing stack.
- **Option C — Rust**: integrate into `transcribe-client` or `transcribe-daemon`. More performant but heavier to maintain.

Recommendation: **Option B** — post-processing is already in shell, a config file + Python parser would be the most pragmatic approach.

---

### 2. Personal Dictionary (Phonetic Correction)

**Priority: medium** — High effort, targeted value (proper nouns, jargon).

#### What Murmure Does

Code in `src-tauri/src/dictionary/dictionary.rs`. **Post-ASR** correction via **Beider-Morse** phonetic matching:

1. Phonetically encodes each word in the dictionary (Beider-Morse algorithm, ~130 rule files for ~20 languages)
2. Encodes each word in the transcription
3. If phonetic codes match → substitution

Structure: `Arc<Mutex<HashMap<String, Vec<String>>>>` (thread-safe).

Applied **before** the LLM and **before** formatting rules.

UX: simple text field, removable tags, CSV import/export.

#### Current State in dictee

No equivalent.

#### Implementation Options for dictee

- **Simple option**: exact replacement dictionary (`misrecognized_word → correction`) in a config file. No phonetics but covers 80% of the need.
- **Advanced option**: integrate a phonetic library (e.g., `rphonetic` in Rust, or `phonetics` in Python). Beider-Morse is complex (~130 rule files).

Recommendation: start with the **simple option** (exact replacement), iterate toward phonetic if demand is strong.

---

### 3. General-Purpose LLM Post-Processing

**Priority: medium-high** — Medium effort (ollama infra already in place), high value.

#### What Murmure Does

Code in `src-tauri/src/llm/llm.rs`. Two providers:
- **Local**: Ollama (`POST {url}/generate`, timeout 120s)
- **Remote**: OpenAI-compatible API (`POST {url}/chat/completions` with Bearer token, timeout 60s)

5 prompt presets:
1. **General**: spelling/grammar correction
2. **Medical**: medical terminology and acronyms
3. **TypeScript**: voice→code conversion
4. **Developer (Cursor)**: technical correction for IDE
5. **Translation**: automatic translation

Injectable variables: `{{TRANSCRIPT}}`, `{{DICTIONARY}}`. Temperature 0.0.

Pipeline: transcription → dictionary → **LLM** → formatting rules.

3 trigger modes: Standard (no LLM), LLM (post-processing), Command (with selected context).

#### Current State in dictee

- Translation via ollama/translategemma already implemented (`dictee --translate --ollama`)
- The ollama infrastructure is in place
- No grammar correction or custom prompts

#### Implementation Options for dictee

dictee already has the ollama path. It would suffice to:
1. Add a `--llm` (or `--postprocess`) option to the `dictee` script
2. Prompts directory `~/.config/dictee-prompts/` (one file per preset)
3. Section in `dictee --setup` to choose the model and edit prompts
4. `DICTEE_LLM_PROMPT` variable in `dictee.conf`

The "Command" mode (selected context) is interesting for developers but more complex (requires capturing selected text via `wl-copy`/`xsel`).

#### Recommended Model: `ministral-3:3b`

After evaluation, the best trade-off for grammar correction in dictee is **ministral-3:3b** (Mistral AI):

| Criterion | ministral-3:3b | qwen2.5:1.5b |
|-----------|----------------|---------------|
| **Disk size** | 1.9 GB | 986 MB |
| **RAM** | ~3 GB | ~2 GB |
| **Thinking** | No | No |
| **French** | Excellent (Mistral = French company) | Good |
| **Languages** | 40+ | 29 |
| **License** | Apache 2.0 | Apache 2.0 |

Alternatives considered:
- **Qwen2.5:1.5b**: lighter (986 MB) and faster, but less good at French
- **Qwen3:1.7b**: good but requires `/no_think` to disable reasoning
- **gemma3:1b**: the lightest (815 MB), decent FR quality but nothing more

Prompt inspired by Murmure (`DEFAULT_GENERAL_PROMPT` in `helpers.rs`):

```
Correct only the following text according to these strict rules:
- Fix spelling and grammar.
- Remove repetitions and hesitations.
- Never change the meaning or content.
- Do not answer questions or comment on them.
- Do not generate any comments or introduction.
- If nothing needs to be modified, return the text as-is.
```

Installation:
```bash
ollama pull ministral-3:3b   # recommended (better French)
ollama pull qwen2.5:1.5b     # lightweight alternative (986 MB, faster)
```

---

### 4. Voice Activation (Wake Word)

**Priority: low** — High effort, niche need.

#### What Murmure Does

Code in `src-tauri/src/wake_word/wake_word.rs`. 3-phase architecture:

1. **Audio acquisition** via `cpal` (cross-platform audio lib), dedicated permanent thread
2. **VAD (Voice Activity Detection)** via RMS analysis:
   - Speech threshold: RMS > 0.015 / Silence threshold: RMS < 0.01
   - Speech confirmation delay: 200ms / Silence: 400ms
   - Pre-buffer: 400ms (captures audio before detection)
   - RMS sampling every 33ms
3. **Transcription and matching**:
   - Audio resampled to 16kHz, transcribed by Parakeet INT8
   - Double matching: exact substring + fuzzy Levenshtein (distance ≤1 for short words, ≤2 otherwise)
   - Normalization: lowercase, accent removal (NFD)

4 configurable triggers: "ok alix" (dictation), "alix command", "alix cancel", "alix validate".

5 action types: Record, RecordLlmMode, Cancel, Validate.

#### Current State in dictee

Push-to-talk only (keyboard shortcut). No VAD or wake word.

#### Implementation Options for dictee

- Would require an additional daemon listening permanently
- Non-negligible CPU/battery consumption
- Complexity: VAD + continuous transcription + matching = a lot of code
- Simpler alternative: integrate basic VAD into `transcribe-client` for "auto-stop" (stop recording when the user stops speaking), without wake word

Recommendation: **defer** — push-to-talk is sufficient for the majority of use cases. Silence-based auto-stop would be a more realistic first step.

---

## Suggested Roadmap (post-v1.0.0)

| Version | Feature | Effort |
|---------|---------|--------|
| v1.1.0 | Configurable rules engine | ~2-3 days |
| v1.1.0 | LLM post-processing (grammar correction, custom prompts) | ~2 days |
| v1.2.0 | Replacement dictionary (exact, then phonetic) | ~1-3 days |
| v1.3.0+ | Silence auto-stop (basic VAD) | ~2 days |
| v2.0.0+ | Wake word / voice activation | ~1-2 weeks |

## Notes

- Murmure is AGPL v3 — do not copy code directly, draw inspiration from the architecture only
- The Murmure pipeline (dictionary → LLM → rules) is a good ordering model
- The number→digit conversion (`text2num`) is a subtle but very useful day-to-day feature
