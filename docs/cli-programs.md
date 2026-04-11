# CLI Programs

[Back to main README](../README.md)

---

## Overview

| Program | Description | Languages |
|---------|-------------|----------|
| `transcribe` | Audio file transcription | Multilingual |
| `transcribe-daemon` | Unix socket server (preloaded model) | Multilingual |
| `transcribe-client` | Client: file, stdin, or microphone | Multilingual |
| `transcribe-diarize` | Transcription + speaker identification | Multilingual |
| `transcribe-stream-diarize` | Real-time streaming + diarization | English only |

All binaries support `--help` / `-h`.

> **Tip**: dictee uses daemon mode (`transcribe-daemon` + `transcribe-client`). The model is loaded into memory only once, subsequent transcriptions are near-instant.

## Direct Usage

```bash
# Transcribe a file (any format)
transcribe audio.mp3

# Daemon mode (faster for multiple files)
transcribe-daemon &
transcribe-client fichier1.wav
transcribe-client fichier2.ogg
cat audio.opus | transcribe-client

# Voice dictation from microphone (without the dictee script)
transcribe-client
# → Records until Enter is pressed. The microphone is automatically unmuted if necessary.

# Transcription with speaker identification
transcribe-diarize reunion.wav
# [0.00 - 2.50] Speaker 1: Bonjour à tous.
# [2.80 - 5.10] Speaker 2: Merci d'être venus.
```

## ONNX Models

Models must be placed in `/usr/share/dictee/`:

```
/usr/share/dictee/
├── tdt/                  # ParakeetTDT (multilingual)
│   ├── encoder-model.onnx
│   ├── decoder_joint-model.onnx
│   └── vocab.txt
├── sortformer/           # Diarization
│   └── diar_streaming_sortformer_4spk-v2.1.onnx
└── nemotron/             # Streaming (English)
    ├── encoder-model.onnx
    ├── decoder-model.onnx
    └── vocab.txt
```

The TDT model is available on HuggingFace: [istupakov/parakeet-tdt-0.6b-v3-onnx](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx).
