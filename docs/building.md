# Building from source

[Back to main README](../README.md)

---

## Prerequisites

- **Rust** (edition 2021)
- **ffmpeg** (for audio format conversion)
- **Go** + **scdoc** + **libxkbcommon-dev** (for dotool)

## Build

```bash
# CPU only
cargo build --release

# CUDA + diarization
cargo build --release --features "cuda,sortformer"

# Debian packages (CPU + CUDA)
./build-deb.sh
```

## Cargo Features

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
Audio (any format)
    │ ffmpeg (if not WAV)
WAV 16kHz mono
    │ preemphasis (0.97)
STFT (n_fft=512, hop=160, win=400, Hann)
    │
Mel-spectrogram (128 bins, Slaney)
    │
ONNX model (ParakeetTDT / Nemotron)
    │
Decoder (tokens → text)
    │
Timestamp aggregation (tokens → words → sentences)
    │ [optional]
Sortformer (diarization)
    │
Final text with timestamps / speakers
```
