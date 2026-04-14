# Programmes CLI

[Back to main README](../README.md)

---

## Overview

| Program | Description | Languages |
|---------|-------------|-----------|
| `transcribe` | Transcribe an audio file | Multilingual |
| `transcribe-daemon` | Unix socket server (preloaded model) | Multilingual |
| `transcribe-client` | Client: file, stdin or microphone | Multilingual |
| `transcribe-diarize` | Transcription + speaker identification | Multilingual |
| `transcribe-stream-diarize` | Real-time streaming + diarization | English only |

All binaries support `--help` / `-h`.

> **Tip**: dictee uses daemon mode (`transcribe-daemon` + `transcribe-client`). The model is loaded once into memory, subsequent transcriptions are near-instantaneous.

## Direct usage

```bash
# Transcribe a file (any format)
transcribe audio.mp3

# Daemon mode (faster for multiple files)
transcribe-daemon &
transcribe-client fichier1.wav
transcribe-client fichier2.ogg
cat audio.opus | transcribe-client

# Voice dictation from microphone (without dictee script)
transcribe-client
# → Records until Enter. Microphone is unmuted automatically if needed.

# Transcription with speaker identification
transcribe-diarize reunion.wav
# [0.00 - 2.50] Speaker 1: Bonjour à tous.
# [2.80 - 5.10] Speaker 2: Merci d'être venus.
```

## ONNX models

Models must be placed in `/usr/share/dictee/`:

```
/usr/share/dictee/
├── tdt/                  # ParakeetTDT (multilingue)
│   ├── encoder-model.onnx
│   ├── decoder_joint-model.onnx
│   └── vocab.txt
├── sortformer/           # Diarisation
│   └── diar_streaming_sortformer_4spk-v2.1.onnx
└── nemotron/             # Streaming (anglais)
    ├── encoder-model.onnx
    ├── decoder-model.onnx
    └── vocab.txt
```

Le modèle TDT est disponible sur HuggingFace : [istupakov/parakeet-tdt-0.6b-v3-onnx](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx).
