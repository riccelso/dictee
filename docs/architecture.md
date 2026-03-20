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
    -> dictee (bash) or transcribe-client
    -> transcribe-client (normalizes to 16 kHz mono WAV)
    -> Unix socket: $XDG_RUNTIME_DIR/transcribe.sock
    -> active ASR daemon (Parakeet | Vosk | Whisper)
    -> raw text
    -> optional dictee-postprocess
    -> optional translation (trans/libretranslate/ollama)
    -> dotool (focused app input) + clipboard + notifications
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
  - optional postprocessing (`dictee-postprocess`),
  - optional translation,
  - text injection (`dotool`),
  - clipboard and notifications.

Runtime state:

- `/dev/shm/.dictee_state` tracks `idle`, `recording`, `transcribing`, `cancelled`.
- per-user socket at `$XDG_RUNTIME_DIR/transcribe.sock` (fallback to `/tmp`).

### 4) Interfaces and utilities

- [dictee-tray.py](dictee-tray.py): tray icon, quick actions, daemon status.
- [dictee-setup.py](dictee-setup.py): backend, shortcuts, and service configuration.
- [dictee-ptt.py](dictee-ptt.py): push-to-talk/toggle helper.
- `plasmoid/`: KDE Plasma widget.

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
5. `dictee` applies optional postprocessing/translation.
6. Text is typed into the active app via `dotool`.

### Flow B: offline file CLI

1. User runs `transcribe file.ext`.
2. Binary converts to 16 kHz mono WAV if needed (`ffmpeg`).
3. Model is loaded in-process and transcription is printed to stdout.

### Flow C: transcription + diarization

1. User runs `transcribe-diarize` or `transcribe-stream-diarize`.
2. ASR + Sortformer are executed.
3. Text is time-aligned with speaker segments and printed per speaker.

## Limits and boundaries

- `dictee` desktop dictation depends on Linux userland tools (`pw-record`, `dotool`, `notify-send`, etc.).
- Diarization is currently CLI-focused, not integrated into the default typing workflow.
- ASR backends share protocol semantics but differ in implementation and model requirements.
