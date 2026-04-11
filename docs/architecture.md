# Project Architecture (dictee)

[Back to main README](README.md)

---

## Goal

`dictee` is a local Linux dictation system. The architecture separates:

- **Rust ASR core** (inference and decoding),
- **backend daemons** (long-running processes with preloaded models),
- **clients/orchestration** (audio capture, translation, and typing),
- **visual interfaces** (KDE Plasmoid, tray icon, and setup UI).

## High-level view

```text
Microphone/file
    -> dictee (bash) / dictee-ptt / transcribe-client
    -> transcribe-client (normalizes to 16 kHz mono WAV)
    -> Unix socket: $XDG_RUNTIME_DIR/transcribe.sock
    -> active ASR daemon (Parakeet | Vosk | Whisper)
    -> raw text
    -> optional dictee-postprocess
    -> optional translation (trans/libretranslate/ollama)
    -> text injection (clipboard paste shortcut by default; dotool fallback/mode) + notifications

Configuration/control plane
    -> dictee-setup (writes ~/.config/dictee.conf, manages services)
    -> dictee-tray (service/status and quick actions)
```

## Layers and components

### 1) Rust core (`src/`)

- `parakeet_rs` library in [src/lib.rs](src/lib.rs)
- Main pipeline (Parakeet/Nemotron/Sortformer):
  - audio preprocessing,
  - ONNX execution (CPU/CUDA and other providers),
  - token decoding into text/timestamps,
  - optional diarization (`sortformer` feature).

Main binaries:

- [src/bin/transcribe.rs](src/bin/transcribe.rs): file transcription.
- [src/bin/transcribe_daemon.rs](src/bin/transcribe_daemon.rs): Parakeet daemon over Unix socket.
- [src/bin/transcribe_client.rs](src/bin/transcribe_client.rs): client (file, stdin, microphone) for the daemon.
- [src/bin/transcribe_diarize.rs](src/bin/transcribe_diarize.rs): transcription + diarization (not part of the default desktop dictation flow).
- [src/bin/transcribe_stream_diarize.rs](src/bin/transcribe_stream_diarize.rs): streaming + diarization (English only).

### 2) ASR daemons (`systemd --user`)

Mutually exclusive services (same socket protocol):

- [pkg/dictee/usr/lib/systemd/user/dictee.service](pkg/dictee/usr/lib/systemd/user/dictee.service): Parakeet (`/usr/bin/transcribe-daemon`)
- [pkg/dictee/usr/lib/systemd/user/dictee-vosk.service](pkg/dictee/usr/lib/systemd/user/dictee-vosk.service): Vosk
- [pkg/dictee/usr/lib/systemd/user/dictee-whisper.service](pkg/dictee/usr/lib/systemd/user/dictee-whisper.service): faster-whisper

Shared contract:

- receives a WAV file path via Unix socket,
- returns text (or `ERROR: ...`),
- keeps the model in memory to reduce latency.

### 3) Dictation orchestration

- [dictee](dictee) coordinates the UX flow:
  - recording (`pw-record`),
  - `transcribe-client` call,
  - optional postprocessing (`dictee-postprocess.py`),
  - optional translation,
  - text injection (`paste_text` strategy),
  - clipboard and notifications.

Input injection strategy (`dictee`):

- Default mode: `DICTEE_PASTE_MODE=clipboard`
  - copies text with `wl-copy`
  - triggers app paste shortcut (`Shift+Insert`, fallback `Ctrl+V`) using `wtype` (preferred) or `dotool`
  - avoids character-by-character typing issues (keyboard layout/special chars such as `ç`)
- Optional mode: `DICTEE_PASTE_MODE=dotool` (or `--paste-dotool`)
  - uses `dotool` type/key path directly
- Auto mode: `DICTEE_PASTE_MODE=auto`
  - prefers clipboard strategy when available on Wayland, otherwise falls back to dotool typing.

Runtime state:

- `/dev/shm/.dictee_state` tracks `idle`, `recording`, `transcribing`, `cancelled`.
- per-user socket at `$XDG_RUNTIME_DIR/transcribe.sock` (fallback to `/tmp`).
- runtime flags/files under `/tmp` are used to persist one-session options (translate backend, LLM flag, notification id, recording pid).

### 4) Post-processing and LLM correction

- [dictee-postprocess.py](dictee-postprocess.py) is a stdin->stdout pipeline.
- Main stages:
  - regex rules (`rules.conf.default` + user `~/.config/dictee/rules.conf`),
  - French elisions/typography (when source language is `fr`),
  - numbers conversion,
  - dictionary replacements (`dictionary.conf.default` + user dictionary),
  - capitalization,
  - optional LLM correction.
- LLM providers supported:
  - `ollama` (default local path),
  - `openai`,
  - `openrouter`,
  - `gemini`/`google`,
  - `anthropic`,
  - `groq`,
  - `openai_compatible` (generic OpenAI-compatible endpoint — LM Studio, LocalAI, Ollama OpenAI mode, text-generation-webui, etc.; configured via `DICTEE_LLM_OPENAI_COMPAT_URL` and optional `DICTEE_LLM_OPENAI_COMPAT_KEY`).
- The script supports verbose diagnostics:
  - CLI flag `-v/--verbose`,
  - env flags `DICTEE_PP_VERBOSE=true` or `DICTEE_VERBOSE=true`,
  - dedicated LLM debug logs with `DICTEE_LLM_DEBUG=true`.
- If a dedicated postprocess venv exists at `~/.local/share/dictee/postprocess-env`,
  its `site-packages` are injected at runtime (no re-exec) to preserve stdin piping.

### 5) Interfaces and utilities

- [dictee-tray.py](dictee-tray.py): tray icon, quick actions, daemon status.
- [dictee-setup.py](dictee-setup.py):
  - writes `~/.config/dictee.conf`,
  - configures ASR backend, translation backend, postprocess/LLM options, and PTT hotkeys,
  - can run in wizard mode (`--wizard`),
  - enables/disables systemd user services (`dictee`, `dictee-tray`, `dictee-ptt`, and backend services).
- [dictee-ptt.py](dictee-ptt.py):
  - push-to-talk daemon (`hold` or `toggle`),
  - uses `evdev` + `uinput` when available (preferred),
  - falls back to raw `/dev/input` reading when needed.
- `plasmoid/`: KDE Plasma widget.

### 6) Packaging architecture (root vs `pkg/`)

Repository model:

- Root scripts are the development source of truth:
  - `dictee`, `dictee-setup.py`, `dictee-tray.py`, `dictee-ptt.py`, `dictee-postprocess.py`.
- `pkg/dictee/...` is a package template/staging tree used by installers and package builds.

Build/install behavior:

- `build_and_install.sh` syncs root scripts into `pkg/dictee/usr/bin/` before installation.
- `build-deb.sh` and `build-rpm.sh` copy `pkg/dictee` to a temporary staging directory (`mktemp` under `/tmp`) and build from that staging copy.
- `install.sh` installs to `/usr/local` and uses root scripts as primary source for core runtime scripts.
- `PKGBUILD` follows the same split: root scripts + `pkg/dictee` template assets/services.

Cleanup policy:

- `scripts/clean-volatile-artifacts.sh` removes only volatile build artifacts
  (`__pycache__`, `*.pyc`, `*.pyo`, root `dictee.plasmoid`).
- `pkg/dictee` is intentionally not deleted during cleanup.

## Model artifacts

Default install path: `/usr/share/dictee/`:

- `tdt/` (Parakeet-TDT),
- `nemotron/` (streaming),
- `sortformer/` (diarization).

## Main flows

### Flow A: interactive dictation

1. User triggers a shortcut/UI action.
2. `dictee` records audio.
3. `dictee` calls `transcribe-client`, which sends WAV to the daemon over Unix socket.
4. Daemon returns text.
5. `dictee` applies optional postprocessing/translation (and optional LLM correction through postprocess).
6. Text is injected into the active app through `paste_text` (clipboard paste by default, dotool mode/fallback when selected or required).

### Flow A2: push-to-talk daemon mode

1. `dictee-ptt` captures configured hotkeys (hold/toggle).
2. It invokes `dictee` start/stop/cancel commands depending on key events and mode.
3. Resulting text follows the same `dictee` pipeline as Flow A.

### Flow B: offline file CLI

1. User runs `transcribe file.ext`.
2. Binary converts to 16 kHz mono WAV if needed (`ffmpeg`).
3. Model is loaded in-process and transcription is printed to stdout.

### Flow C: transcription + diarization

1. User runs `transcribe-diarize` or `transcribe-stream-diarize`.
2. ASR + Sortformer are executed.
3. Text is time-aligned with speaker segments and printed per speaker.

## Limits and boundaries

- `dictee` desktop dictation depends on Linux userland tools (`pw-record`, `notify-send`, and one of `wtype`/`dotool` for paste/input events).
- Diarization is currently CLI-focused, not integrated into the default typing workflow.
- ASR backends share protocol semantics but differ in implementation and model requirements.
- Packaging keeps a deliberate duplication (root source + `pkg` template), so editing only inside `pkg/dictee/usr/bin` can be overwritten by normal build/install workflows.
