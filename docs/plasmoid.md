# KDE Plasma 6 Widget

[Back to main README](../README.md)

---

Native KDE Plasma 6 widget with real-time audio visualization, daemon status, and quick controls.

## Installation

```bash
# Included in the .deb, or manually:
kpackagetool6 -t Plasma/Applet -i /usr/share/dictee/dictee.plasmoid

# Update
kpackagetool6 -t Plasma/Applet -u /usr/share/dictee/dictee.plasmoid
```

Right-click on the panel → "Add Widgets…" → search for "Dictée".

## Animation Styles

Five styles available, all with Hanning envelope, per-style sensitivity, and optional rainbow colors:

| Bars | Wave | Pulse | Dots | Waveform |
|:------:|:----:|:---------:|:------:|:------------:|
| ![Barres](../plasmoid/assets/anim-bars.svg?v=2) | ![Onde](../plasmoid/assets/anim-wave.svg) | ![Pulsation](../plasmoid/assets/anim-pulse.svg) | ![Points](../plasmoid/assets/anim-dots.svg) | ![Forme d'onde](../plasmoid/assets/anim-waveform.svg) |

Rainbow mode: ![Rainbow](../plasmoid/assets/anim-rainbow.svg?v=2)

## Settings

- **Microphone volume** — adjust the input level directly from the widget config
- **Silence threshold** — zeroes out audio below a threshold for clean silence
- **Auto-calibration** — captures ambient noise at startup for optimal normalization
- **Sensitivity** — power curve per animation style (`pow(raw, 1/sens)`)
- **Envelope shape** — adjustable Hanning power (flat → sharp)
- **Envelope center** — shifts the peak across the frequency range (80–4000 Hz)
- **Per-style controls** — number of bars, spacing, radius, speed, etc.

## Dependencies

- `python3-numpy` — FFT computation for visualization
- `pulseaudio-utils` — `parec` for real-time audio capture
