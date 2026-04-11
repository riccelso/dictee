# Configuration Wizard — dictee v1.1.0

## Summary

Add a step-by-step configuration wizard to `dictee-setup.py` to guide new users. The wizard triggers on first launch (no existing `~/.config/dictee.conf`) and remains accessible via a "Configuration Wizard" button in the classic form, or via `dictee --setup --wizard`.

## Architecture

### Approach: QStackedWidget in DicteeSetupDialog

A `QStackedWidget` with 5 pages is added inside the existing dialog. The mode (wizard or classic) is determined **once at startup** in `__init__()`.

```
DicteeSetupDialog
├── self.wizard_mode: bool
├── self.stack: QStackedWidget (5 pages)  ← wizard mode
├── self.scroll: QScrollArea              ← classic mode (existing)
└── Navigation bar: Previous | (n/5) | Next/Finish
```

### Mode Detection

```python
wizard_mode = True if:
  - ~/.config/dictee.conf does not exist (first launch)
  - --wizard argument passed on the command line
  - "Configuration Wizard" button clicked → closes and relaunches in wizard mode
```

### Conditional Construction (No Re-parenting)

Widgets are created once in `__init__()` and placed **directly** into the appropriate container based on `self.wizard_mode`:

- **Wizard mode** → widgets are added to the `QStackedWidget` pages
- **Classic mode** → widgets are added to the `QScrollArea` (as currently)

There is **no dynamic relocation** of widgets between modes. The "Configuration Wizard" button in classic mode **closes the dialog and relaunches** `dictee-setup.py --wizard` (new process).

### Visual Radio Buttons vs ComboBox

**Wizard mode** uses visual radio buttons (clickable blocks) for ASR and translation — more guided, clearer for first-time users.

**Classic mode** keeps the existing `QComboBox` widgets — compact, familiar for recurring users.

Both modes use the same internal variables (`self.asr_backend`, `self.trans_backend`). Radio buttons and ComboBox are created conditionally:

```python
if self.wizard_mode:
    self._build_asr_radio_buttons()   # creates clickable QFrames
else:
    self._build_asr_combobox()        # existing QComboBox
```

## Wizard Pages

### Page 1 — Welcome + ASR Backend

**Content:**
- Welcome message
- ASR backend selection via **visual radio buttons** (clickable blocks):
  - Parakeet-TDT 0.6B (recommended) — 25 languages, ~2.5 GB, ~0.8s
  - Vosk (lightweight) — 9+ languages, ~50 MB, ~1.5s
  - faster-whisper (99 languages) — ~500 MB–3 GB, ~0.3s
- Model installation status (✓ installed / ⚠ Download button)
- Conditional sub-options: Vosk language, Whisper model (appear below the selected choice)

**Validation before "Next":**
- The main model of the selected backend must be installed (or download in progress)

### Page 2 — Keyboard Shortcuts

**Content:**
- Detected environment (KDE Plasma / GNOME / tiling WM)
- Two `ShortcutButton` widgets to capture shortcuts:
  - Voice dictation (default: F9)
  - Dictation + Translation (default: Alt+F9)
- Real-time conflict detection:
  - **KDE**: via existing `check_kde_conflict()` (kglobalshortcutsrc)
  - **GNOME**: out of scope for v1.1.0 (no conflict detection, just gsettings write)
- Warning message if conflict detected (KDE only)

**Special case — Tiling WM:**
- No capture buttons
- Displays commands to manually add to Sway/i3/Hyprland config

**Validation:** none — default shortcuts are always valid.

### Page 3 — Translation

**Content:**
- Source/target languages side by side (pre-filled from system locale)
- Backend selection via visual radio buttons, **local options first**:
  1. **ollama** (100% local, best quality) — 2.3–3.4s
  2. **LibreTranslate** (100% local) — Docker ~2 GB, 0.1–0.3s
  3. **Google Translate** (online, fast) — 0.2–0.7s
  4. **Bing** (online) — 1.7–2.2s
- Conditional sub-options: ollama model, LibreTranslate port, download
- Automatic dependency detection (ollama installed? Docker accessible? translate-shell?)

**No activation toggle** — translation is optional by nature (dedicated shortcut).

**Validation:** none — translation configuration is always valid.

### Page 4 — Microphone, Visual Feedback, and Services

**Content:**

#### Microphone
- **Audio source selection** — ComboBox listing detected PipeWire/PulseAudio sources
- **Microphone volume slider** — control via `wpctl set-volume` or `pactl set-source-volume`
- **Real-time level indicator** — `QProgressBar` updated by a `QThread` that reads `parec` (PulseAudio) or `pw-record` (PipeWire) via a pipe, computes RMS on 100ms blocks, emits a `level(int)` signal. Refresh rate ~10 Hz.
- Detection and prompt to unmute if the microphone is muted
- **If no microphone detected**: non-blocking warning message "No microphone detected. Check your audio connection." The wizard continues normally.

#### Visual Feedback
- **Multi-selection** (checkboxes, not radio — can be combined):
  - KDE Plasma widget (recommended if KDE detected)
  - animation-speech (fullscreen overlay, Wayland)
  - Notification icon (dictee-tray, for non-KDE)
- Environment detection → smart pre-checking:
  - KDE → plasmoid checked
  - GNOME/Xfce/Sway → tray checked
- Integrated "Install" button if animation-speech or plasmoid is missing

#### Startup Services
- Toggle: start transcription daemon at login (ON by default)
- Toggle: copy transcription to clipboard (OFF by default)

**Validation:** none.

### Page 5 — Test

**Content:**

#### Automatic Checks
Launched upon arriving on the page:
- ASR daemon active (systemctl --user is-active)
- Model installed
- Shortcut registered (kglobalshortcutsrc / gsettings)
- Audio detected (PipeWire/PulseAudio)
- dotool functional

Each check: green ✓ if OK, red ✗ + "Fix" button that returns to the relevant page.

#### Dictation Test
- "Test Dictation" button — calls `transcribe-client` directly as a subprocess (the Rust binary that records the mic and sends to the daemon via Unix socket). Captures stdout (the transcribed text) and displays it in a read-only `QTextEdit`.
- No need for `dotool` or `--test` mode in the `dictee` script — we short-circuit the chain.
- 10-second timeout. The button changes to "Stop" during recording.
- **Optional** — "Finish" is always clickable without having tested

#### Final Message
- "All set!" with a reminder of the configured shortcut

**"Finish" button** (green) → calls `_on_apply()`, saves config, closes the wizard.

## Navigation

```
[Previous]  Step n of 5  [Next →]     (pages 1-4)
[Previous]  Step 5 of 5  [✓ Finish]   (page 5)
```

- "Previous" disabled on page 1
- "Next" validates the current page before advancing
- "Finish" calls `_on_apply()` (same function as the classic form)
- Textual progress indicator "Step n of 5"

## Classic Mode — Changes

- Added **"Configuration Wizard"** button at the bottom left (next to Cancel)
- Clicking it **closes the dialog and relaunches** `dictee-setup --wizard`
- Added **Microphone** section (source, volume, level) in the classic form as well
- Everything else in the classic form remains identical

## CLI Argument

```bash
dictee --setup           # classic if config exists, wizard otherwise
dictee --setup --wizard  # forces wizard mode
```

The `dictee` script passes `--wizard` to `dictee-setup` if present.

## New Configuration Keys

```bash
# Added to ~/.config/dictee.conf
DICTEE_AUDIO_SOURCE=alsa_input.pci-0000_00_1f.3.analog-stereo  # PipeWire/PA source ID
```

Microphone volume is **not persisted** in dictee.conf — it is applied immediately via `wpctl`/`pactl` and the audio system retains it. The audio source is persisted so it can be restored.

## Audio Source Detection

```python
def list_audio_sources():
    """Lists microphone sources via wpctl or pactl."""
    # 1. Try wpctl status → parse Sources (Audio/Sources section)
    # 2. Fallback pactl list sources short
    # Returns: [(id, name, description), ...]
    # Returns [] if no tool available

class AudioLevelThread(QThread):
    """Continuously reads the mic, emits RMS level."""
    level = Signal(int)  # 0-100

    def run(self):
        # Launches parec (PA) or pw-record (PipeWire) as subprocess
        # Reads blocks of 1600 samples (100ms at 16kHz, mono, s16le)
        # Computes RMS → normalizes 0-100 → emits level signal
        # Terminates cleanly when self._running = False
```

## Modified Files

| File | Change |
|------|--------|
| `dictee-setup.py` | QStackedWidget, 5 wizard pages, microphone section, AudioLevelThread, visual radio buttons, wizard button |
| `dictee` (shell script) | Passes `--wizard` to `dictee-setup` |
| `po/dictee.pot` | New wizard strings (~30 strings) |
| `po/{fr,de,es,it,uk,pt}.po` | Translations of new strings |

**Estimate:** ~500-600 lines added to `dictee-setup.py` (1945 → ~2500-2550 lines).

## What Doesn't Change

- `_on_apply()` — unchanged (the wizard calls the same function)
- Download threads (ModelDownloadThread, VenvInstallThread, etc.) — unchanged
- KDE/GNOME shortcut handling — unchanged
- General format of `~/.config/dictee.conf` — extended (new key `DICTEE_AUDIO_SOURCE`)

## Out of Scope for v1.1.0

- GNOME shortcut conflict detection
- Pre-compiled aarch64 support (source compilation only)
- `dictee --test` mode in the shell script
