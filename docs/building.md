# Compilation depuis les sources

[Back to main README](../README.md)

---

## Prerequisites

- **Rust** (edition 2021)
- **ffmpeg** (for audio format conversion)
- **Go** + **scdoc** + **libxkbcommon-dev** (for dotool)

## Build

```bash
# CPU uniquement
cargo build --release

# CUDA + diarisation
cargo build --release --features "cuda,sortformer"

# Paquets Debian (CPU + CUDA)
./build-deb.sh
```

## Cargo features

| Feature | Description |
|---------|-------------|
| `cpu` | CPU execution (default) |
| `cuda` | NVIDIA GPU via CUDA |
| `tensorrt` | TensorRT optimization |
| `coreml` | Apple CoreML |
| `directml` | Microsoft DirectML |
| `openvino` | Intel OpenVINO |
| `sortformer` | Diarization (required for `*-diarize`) |

## Tests

```bash
cargo test
cargo test --features sortformer
```

## Audio pipeline (internal architecture)

```
Audio (tout format)
    │ ffmpeg (si non-WAV)
WAV 16kHz mono
    │ preemphasis (0.97)
STFT (n_fft=512, hop=160, win=400, Hann)
    │
Mel-spectrogram (128 bins, Slaney)
    │
Modèle ONNX (ParakeetTDT / Nemotron)
    │
Décodeur (tokens → texte)
    │
Agrégation timestamps (tokens → mots → phrases)
    │ [optionnel]
Sortformer (diarisation)
    │
Texte final avec horodatages / locuteurs
```
