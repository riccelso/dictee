# Configuration Wizard — dictee v1.1.0

## Summary

Add a step-by-step configuration assistant (wizard) to `dictee-setup.py` to guide new users. The wizard triggers on first launch (absence of `~/.config/dictee.conf`) and remains accessible via a "Setup wizard" button in the classic form, or via `dictee --setup --wizard`.

## Architecture

### Approach: QStackedWidget in DicteeSetupDialog

A `QStackedWidget` with 5 pages is added in the existing dialog. The mode (wizard or classic) is determined **once at startup** in `__init__()`.

```
DicteeSetupDialog
├── self.wizard_mode: bool
├── self.stack: QStackedWidget (5 pages)  ← wizard mode
├── self.scroll: QScrollArea              ← classic mode (existing)
└── Navigation bar: Previous | (n/5) | Next/Finish
```

### Mode detection

```python
wizard_mode = True if:
  - ~/.config/dictee.conf doesn't exist (first launch)
  - --wizard argument passed via command line
  - "Setup wizard" button clicked → closes and restarts in wizard mode
```

### Conditional construction (no re-parenting)

Widgets are created once in `__init__()` and placed **directly** in the correct container based on `self.wizard_mode` :

- **Wizard mode** → widgets are added to the `QStackedWidget` pages
- **Classic mode** → widgets are added to the `QScrollArea` (as currently)

There is **no dynamic widget movement** between modes. The "Setup wizard" button in classic mode **closes the dialog and restarts** `dictee-setup.py --wizard` (new process).

### Visual radio buttons vs ComboBox

The **wizard mode** uses visual radio buttons (clickable blocks) for ASR and translation — more guided, clearer for first contact.

The **classic mode** retains existing `QComboBox` — compact, familiar for recurring users.

Both modes use the same internal variable (`self.asr_backend`, `self.trans_backend`). Radio buttons and ComboBox are created conditionally :

```python
if self.wizard_mode:
    self._build_asr_radio_buttons()   # creates clickable QFrame
else:
    self._build_asr_combobox()        # existing QComboBox
```

## Wizard pages

### Page 1 — Welcome + ASR Backend

**Content :**
- Welcome message
- ASR backend selection via **visual radio buttons** (clickable blocks) :
  - Parakeet-TDT 0.6B (recommended) — 25 languages, ~2.5 GB, ~0.8s
  - Vosk (lightweight) — 9+ languages, ~50 MB, ~1.5s
  - faster-whisper (99 languages) — ~500 MB–3 GB, ~0.3s
- Model installation status (✓ installed / ⚠ download button)
- Conditional sub-options: Vosk language, Whisper model (appear under selected choice)

**Validation before "Next" :**
- The main model of the selected backend must be installed (or download in progress)

### Page 2 — Keyboard shortcuts

**Content :**
- Detected environment (KDE Plasma / GNOME / tiling WM)
- Two `ShortcutButton` to capture shortcuts :
  - Voice dictation (default: F9)
  - Dictation + Translation (default: Alt+F9)
- Real-time conflict detection :
  - **KDE** : via existing `check_kde_conflict()` (kglobalshortcutsrc)
  - **GNOME** : out of scope for v1.1.0 (no conflict detection, just gsettings write)
- Warning message if conflict detected (KDE only)

**Tiling WM special case :**
- No capture buttons
- Displays commands to add manually to Sway/i3/Hyprland config

**Validation:** none — default shortcuts are always valid.

### Page 3 — Translation

**Content :**
- Source/target languages side by side (pre-filled from system locale)
- Backend selection via visual radio buttons, **local first** :
  1. **ollama** (100% local, best quality) — 2.3–3.4s
  2. **LibreTranslate** (100% local) — Docker ~2 GB, 0.1–0.3s
  3. **Google Translate** (online, fast) — 0.2–0.7s
  4. **Bing** (online) — 1.7–2.2s
- Conditional sub-options: ollama model, LibreTranslate port, download
- Automatic dependency detection (ollama installed? Docker accessible? translate-shell?)

**No activation toggle** — translation is optional by nature (dedicated shortcut).

**Validation:** none — translation configuration is always valid.

### Page 4 — Microphone, visual feedback and services

**Content :**

#### Microphone
- **Audio source selection** — ComboBox listing detected PipeWire/PulseAudio sources
- **Microphone volume slider** — control via `wpctl set-volume` or `pactl set-source-volume`
- **Real-time level indicator** — `QProgressBar` updated by a `QThread` that reads `parec` (PulseAudio) or `pw-record` (PipeWire) via a pipe, calculates RMS on 100ms blocks, emits `level(int)` signal. Refresh ~10 Hz.
- Detection and suggestion to unmute if microphone is muted
- **If no microphone detected** : non-blocking warning message "No microphone detected. Check your audio connection." The wizard continues normally.

#### Visual feedback
- **Multi-selection** (checkboxes, not radio — you can combine):
  - KDE Plasma widget (recommended if KDE detected)
  - animation-speech (fullscreen overlay, Wayland)
  - Notification icon (dictee-tray, for non-KDE)
- Environment detection → intelligent pre-check:
  - KDE → plasmoid checked
  - GNOME/Xfce/Sway → tray checked
- Integrated "Install" button if animation-speech or plasmoid missing

#### Startup services
- Toggle: start transcription daemon at login (ON by default)
- Toggle: copy transcription to clipboard (OFF by default)

**Validation:** none.

### Page 5 — Test

**Content :**

#### Automatic checks
Launched immediately on arriving at the page:
- Active ASR daemon (systemctl --user is-active)
- Model installed
- Shortcut registered (kglobalshortcutsrc / gsettings)
- Audio detected (PipeWire/PulseAudio)
- dotool functional

Each check: ✓ green if OK, ✗ red + "Fix" button that returns to the relevant page.

#### Dictation test
- "Test dictation" button — directly calls `transcribe-client` as subprocess (the Rust binary that records microphone and sends to daemon via Unix socket). Captures stdout (the transcribed text) and displays it in a read-only `QTextEdit`.
- No need for `dotool` or `--test` mode in `dictee` script — we bypass the chain.
- 10 second timeout. Button changes to "Stop" during recording.
- **Optional** — "Finish" is always clickable without having tested

#### Final message
- "All set!" with reminder of configured shortcut

**"Finish" button** (green) → calls `_on_apply()`, saves config, closes wizard.

## Navigation

```
[Previous]  Step n of 5  [Next →]     (pages 1-4)
[Previous]  Step 5 of 5  [✓ Finish]    (page 5)
```

- "Previous" disabled on page 1
- "Next" validates current page before advancing
- "Finish" calls `_on_apply()` (same function as classic form)
- Textual progress indicator "Step n of 5"

## Classic mode — modifications

- Added **"Setup wizard"** button at bottom left (next to Cancel)
- Clicking it **closes the dialog and restarts** `dictee-setup --wizard`
- Added **Microphone** section (source, volume, level) to classic form as well
- Everything else in classic form remains identical

## CLI argument

```bash
dictee --setup           # classic if config exists, wizard otherwise
dictee --setup --wizard  # force wizard mode
```

The `dictee` script passes `--wizard` to `dictee-setup` if present.

## New configuration keys

```bash
# Added to ~/.config/dictee.conf
DICTEE_AUDIO_SOURCE=alsa_input.pci-0000_00_1f.3.analog-stereo  # PipeWire/PA source ID
```

Microphone volume is **not persisted** in dictee.conf — it is applied immediately via `wpctl`/`pactl` and the audio system retains it. The audio source is persisted to allow restoration.

## Audio source detection

```python
def list_audio_sources():
    """Lists microphone sources via wpctl or pactl."""
    # 1. Try wpctl status → parse Sources (Audio/Sources section)
    # 2. Fallback pactl list sources short
    # Returns: [(id, name, description), ...]
    # Returns [] if no tool available

class AudioLevelThread(QThread):
    """Continuously reads microphone, emits RMS level."""
    level = Signal(int)  # 0-100

    def run(self):
        # Launch parec (PA) or pw-record (PipeWire) as subprocess
        # Read 1600 sample blocks (100ms at 16kHz, mono, s16le)
        # Calculate RMS → normalize 0-100 → emit level signal
        # Cleanly exit when self._running = False
```

## Modified files

| File | Modification |
|------|-------------|
| `dictee-setup.py` | QStackedWidget, 5 wizard pages, microphone section, AudioLevelThread, visual radio buttons, assistant button |
| `dictee` (shell script) | Passing `--wizard` to `dictee-setup` |
| `po/dictee.pot` | New wizard strings (~30 strings) |
| `po/{fr,de,es,it,uk,pt}.po` | Translations of new strings |

**Estimate:** ~500-600 lines added to `dictee-setup.py` (1945 → ~2500-2550 lines).

## What doesn't change

- `_on_apply()` — unchanged (wizard calls the same function)
- Download threads (ModelDownloadThread, VenvInstallThread, etc.) — unchanged
- KDE/GNOME shortcut handling — unchanged
- General format of `~/.config/dictee.conf` — extended (new key `DICTEE_AUDIO_SOURCE`)

## Out of scope for v1.1.0

- GNOME shortcut conflict detection
- Pre-compiled aarch64 support (compile from sources only)
- `dictee --test` mode in shell script
