# Multi-architecture and multi-distribution — Packaging Roadmap

> Post-v1.0.0 — packaging for other architectures and Linux distributions.

## Current state (v1.0.0)

- **Architecture**: amd64 (x86_64) only
- **Formats**: .deb (Debian/Ubuntu), .tar.gz (generic)
- **Packages**: dictee-cuda, dictee-cpu, dictee-plasmoid
- **Build**: `build-deb.sh`, native compilation

## Target architectures

### aarch64 (ARM64) — High priority

Target: Raspberry Pi 5, ARM servers (Oracle Cloud, AWS Graviton), Asahi Linux (Apple Silicon).

**Constraints:**
- Rust cross-compilation: well supported via `cross` or `cargo-cross`
- dotool (Go): native cross-compilation (`GOARCH=arm64`)
- ONNX Runtime (`ort`): precompiled binaries available for aarch64
- CUDA: available on aarch64 (Jetson, servers)
- Parakeet model: identical (portable ONNX), ~2.5 GB RAM required

**Approach:**
```bash
# Via cross (Docker-based)
cargo install cross
cross build --release --target aarch64-unknown-linux-gnu

# Or via native toolchain
rustup target add aarch64-unknown-linux-gnu
sudo apt install gcc-aarch64-linux-gnu
cargo build --release --target aarch64-unknown-linux-gnu
```

**Packages produced:**
- `dictee-cpu_X.X.X_arm64.deb`
- `dictee-cuda_X.X.X_arm64.deb`
- `dictee-X.X.X_arm64.tar.gz`

### armv7 / riscv64 — Not planned

- armv7 (ARM32): insufficient RAM for Parakeet (2.5 GB model)
- riscv64: ONNX Runtime not supported

## Target distributions

### RPM (Fedora, openSUSE, RHEL) — High priority

Second largest Linux user base after Debian/Ubuntu.

**Approach:**
- Use `fpm` (Effing Package Manager) to convert or generate directly
- Or write a native `.spec` file for `rpmbuild`

```bash
# Via fpm (simplest)
gem install fpm
fpm -s dir -t rpm -n dictee-cpu -v 1.0.0 \
    --architecture x86_64 \
    --depends pipewire --depends curl --depends ffmpeg \
    --description "Fast speech-to-text with NVIDIA Parakeet" \
    usr/=/usr/

# Or convert from the .deb
fpm -s deb -t rpm dictee-cpu_1.0.0_amd64.deb
```

**Dependencies to adapt:**
| Debian (.deb) | Fedora (.rpm) |
|---|---|
| `pipewire` | `pipewire` |
| `ffmpeg` | `ffmpeg-free` |
| `libnotify-bin` | `libnotify` |
| `python3-gi` | `python3-gobject` |
| `gir1.2-ayatanaappindicator3-0.1` | `libayatana-appindicator-gtk3` |
| `python3-numpy` | `python3-numpy` |
| `wl-clipboard` | `wl-clipboard` |

**Packages produced:**
- `dictee-cpu-X.X.X-1.x86_64.rpm`
- `dictee-cuda-X.X.X-1.x86_64.rpm`
- `dictee-cpu-X.X.X-1.aarch64.rpm` (when ARM64 is ready)

### AUR PKGBUILD (Arch Linux) — Medium priority

Active community, low effort (single PKGBUILD file).

**Approach:**
```bash
# PKGBUILD — compile from source
pkgname=dictee
pkgver=1.0.0
pkgrel=1
pkgdesc="Fast speech-to-text with NVIDIA Parakeet"
arch=('x86_64' 'aarch64')
url="https://github.com/rcspam/dictee"
license=('GPL-3.0-or-later')
depends=('pipewire' 'dotool' 'ffmpeg' 'curl')
optdepends=(
    'wl-clipboard: clipboard copy'
    'libnotify: desktop notifications'
    'python-gobject: dictee-tray'
    'python-numpy: plasmoid audio visualization'
)
makedepends=('rust' 'go' 'scdoc')
source=("$pkgname-$pkgver.tar.gz::https://github.com/rcspam/dictee/archive/v$pkgver.tar.gz")

build() {
    cd "$pkgname-$pkgver"
    cargo build --release --features sortformer
}

package() {
    cd "$pkgname-$pkgver"
    install -Dm755 target/release/transcribe "$pkgdir/usr/bin/transcribe"
    install -Dm755 target/release/transcribe-daemon "$pkgdir/usr/bin/transcribe-daemon"
    install -Dm755 target/release/transcribe-client "$pkgdir/usr/bin/transcribe-client"
    install -Dm755 target/release/transcribe-diarize "$pkgdir/usr/bin/transcribe-diarize"
    install -Dm755 target/release/transcribe-stream-diarize "$pkgdir/usr/bin/transcribe-stream-diarize"
    install -Dm755 dictee "$pkgdir/usr/bin/dictee"
    install -Dm755 dictee-setup.py "$pkgdir/usr/bin/dictee-setup"
    install -Dm755 dictee-tray.py "$pkgdir/usr/bin/dictee-tray"
    # ... man pages, services, icons, locales, plasmoid
}
```

Arch already has `dotool` in the community repositories → no need to bundle it.

**Publication:** submit to https://aur.archlinux.org/

## Target build matrix

| Arch | .deb | .rpm | AUR | .tar.gz |
|------|------|------|-----|---------|
| **amd64** | CPU + CUDA | CPU + CUDA | PKGBUILD | CPU |
| **aarch64** | CPU + CUDA | CPU + CUDA | PKGBUILD | CPU |

## CI/CD Automation (GitHub Actions)

To automate multi-arch/multi-distro builds:

```yaml
# .github/workflows/release.yml (sketch)
strategy:
  matrix:
    include:
      - target: x86_64-unknown-linux-gnu
        arch: amd64
        features: "sortformer"
      - target: x86_64-unknown-linux-gnu
        arch: amd64
        features: "cuda,sortformer"
      - target: aarch64-unknown-linux-gnu
        arch: arm64
        features: "sortformer"
```

Use `cross` in CI for ARM64 cross-compilation.

## Roadmap

| Version | Target | Effort |
|---------|-------|--------|
| v1.1.0 | .rpm amd64 (Fedora/openSUSE) via `fpm` | ~1 day |
| v1.1.0 | AUR PKGBUILD (Arch) | ~0.5 day |
| v1.2.0 | aarch64 .deb + .rpm + .tar.gz | ~2-3 days |
| v1.2.0 | GitHub Actions multi-arch CI/CD | ~1-2 days |
