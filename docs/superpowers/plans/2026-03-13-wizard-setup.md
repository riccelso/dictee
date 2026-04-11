# dictee Configuration Wizard v1.1.0 — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a step-by-step configuration wizard to `dictee-setup.py` with 5 pages, visual radio buttons, real-time microphone testing, and dictation test.

**Architecture:** QStackedWidget with 5 pages in DicteeSetupDialog. Conditional construction: widgets are created once in `__init__()` and placed directly in the appropriate container (stack or scroll) based on `self.wizard_mode`. No dynamic re-parenting.

**Tech Stack:** PyQt6/PySide6, QStackedWidget, QThread (AudioLevelThread), parec/pw-record, wpctl/pactl, gettext i18n

**Spec:** `docs/superpowers/specs/2026-03-13-wizard-setup-design.md`

---

## Chunk 1: Infrastructure

### Task 1: --wizard argument in the shell script

**Files:**
- Modify: `dictee:83-85` (`--setup)` block)
- Modify: `dictee:10` (Usage comment)

- [ ] **Step 1: Add --wizard to the dictee script**

In `dictee`, modify the `--setup)` block and add `--wizard)`:

```bash
    --setup)
        shift
        exec dictee-setup "$@"
        ;;
    --wizard)
        exec dictee-setup --wizard
        ;;
```

And update the Usage comment on line 10:
```bash
# Usage: dictee [--translate] [--ollama] [--cancel] [--setup [--wizard]]
```

- [ ] **Step 2: Add --wizard parsing in dictee-setup.py**

In `dictee-setup.py`, modify `main()` (line 1937) to parse `--wizard`:

```python
def main():
    import sys
    wizard_flag = "--wizard" in sys.argv
    app = QApplication([])
    app.setApplicationName("dictee-setup")
    dialog = DicteeSetupDialog(wizard=wizard_flag)
    dialog.exec()
```

- [ ] **Step 3: Manual test**

```bash
dictee-setup --wizard  # must open without error
dictee --setup --wizard  # same via the shell script
```

- [ ] **Step 4: Commit**

```bash
git add dictee dictee-setup.py
git commit -m "feat: add --wizard argument to dictee and dictee-setup"
```

---

### Task 2: QStackedWidget + navigation bar

**Files:**
- Modify: `dictee-setup.py:953-960` (DicteeSetupDialog.__init__)

- [ ] **Step 1: Add wizard_mode and QStackedWidget in __init__**

Modify `DicteeSetupDialog.__init__` to accept `wizard=False`. Before building existing widgets, add:

```python
class DicteeSetupDialog(QDialog):
    def __init__(self, wizard=False):
        super().__init__()
        self.wizard_mode = wizard or not os.path.exists(CONF_PATH)
        # ... (existing DE detection code, config reading, etc.)
```

- [ ] **Step 2: Create wizard structure if wizard_mode**

After reading config and before building sections, add the conditional branch:

```python
if self.wizard_mode:
    self._build_wizard_ui()
else:
    self._build_classic_ui()
```

Extract the existing UI construction code into `_build_classic_ui()`. Create `_build_wizard_ui()` which creates the QStackedWidget with 5 empty pages + navigation bar.

- [ ] **Step 3: Implement _build_wizard_ui with navigation**

```python
from PyQt6.QtWidgets import QStackedWidget  # add to import

def _build_wizard_ui(self):
    main_layout = QVBoxLayout(self)
    self.stack = QStackedWidget()

    # 5 pages (empty for now)
    self.wizard_pages = []
    for i in range(5):
        page = QWidget()
        page.setLayout(QVBoxLayout())
        self.stack.addWidget(page)
        self.wizard_pages.append(page)

    main_layout.addWidget(self.stack)

    # Navigation bar
    nav = QHBoxLayout()
    self.btn_prev = QPushButton(_("← Previous"))
    self.btn_prev.clicked.connect(self._wizard_prev)
    self.lbl_step = QLabel()
    self.lbl_step.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.btn_next = QPushButton(_("Next →"))
    self.btn_next.clicked.connect(self._wizard_next)

    nav.addWidget(self.btn_prev)
    nav.addStretch()
    nav.addWidget(self.lbl_step)
    nav.addStretch()
    nav.addWidget(self.btn_next)
    main_layout.addLayout(nav)

    self._update_wizard_nav()
    self.setWindowTitle(_("dictee — Setup wizard"))
    self.resize(600, 500)
```

- [ ] **Step 4: Implement navigation methods**

```python
def _wizard_prev(self):
    idx = self.stack.currentIndex()
    if idx > 0:
        self.stack.setCurrentIndex(idx - 1)
        self._update_wizard_nav()

def _wizard_next(self):
    idx = self.stack.currentIndex()
    if idx == 4:  # last page → Finish
        self._on_wizard_finish()
        return
    if not self._validate_wizard_page(idx):
        return
    self.stack.setCurrentIndex(idx + 1)
    if idx + 1 == 4:  # arriving on page 5 → run checks
        self._run_wizard_checks()
    self._update_wizard_nav()

def _update_wizard_nav(self):
    idx = self.stack.currentIndex()
    self.btn_prev.setEnabled(idx > 0)
    self.lbl_step.setText(_("Step {n} of 5").format(n=idx + 1))
    if idx == 4:
        self.btn_next.setText(_("✓ Finish"))
        self.btn_next.setStyleSheet("background: #4a4; color: white; font-weight: bold; padding: 8px 20px;")
    else:
        self.btn_next.setText(_("Next →"))
        self.btn_next.setStyleSheet("")

def _validate_wizard_page(self, idx):
    """Validates the current page. Returns True if OK."""
    if idx == 0:  # ASR page: verify that the model is installed
        return self._validate_asr_model()
    return True  # pages 1-3: no validation

def _on_wizard_finish(self):
    self._on_apply()
    self.accept()
```

- [ ] **Step 5: Test**

```bash
dictee-setup --wizard  # must display 5 empty pages with working navigation
```

- [ ] **Step 6: Commit**

```bash
git add dictee-setup.py
git commit -m "feat: QStackedWidget + wizard navigation in dictee-setup"
```

---

### Task 3: "Setup wizard" button in classic mode

**Files:**
- Modify: `dictee-setup.py` — end of `_build_classic_ui()` (button bar)

- [ ] **Step 1: Add the button in the existing bar**

In `_build_classic_ui()`, in the button bar at the bottom (next to Cancel), add:

```python
btn_wizard = QPushButton(_("Setup wizard"))
btn_wizard.clicked.connect(self._launch_wizard)
button_layout.insertWidget(0, btn_wizard)  # on the left
```

- [ ] **Step 2: Implement _launch_wizard**

```python
def _launch_wizard(self):
    """Closes the dialog and relaunches in wizard mode."""
    self.reject()
    subprocess.Popen([sys.executable, __file__, "--wizard"])
```

Note: `sys` import already added in Task 1.

- [ ] **Step 3: Test**

```bash
dictee-setup  # classic mode, verify the "Wizard" button at bottom left
# Click → must close and reopen in wizard mode
```

- [ ] **Step 4: Commit**

```bash
git add dictee-setup.py
git commit -m "feat: 'Setup wizard' button in classic mode"
```

---

## Chunk 2: Pages 1 and 2

### Task 4: Page 1 — Welcome + ASR Backend (visual radio buttons)

**Files:**
- Modify: `dictee-setup.py` — `_build_wizard_ui()` + new methods

- [ ] **Step 1: Create _build_wizard_page_asr()**

Method that builds page 1 with visual radio buttons (clickable QFrame blocks):

```python
def _build_wizard_page_asr(self):
    page = self.wizard_pages[0]
    lay = page.layout()

    # Title
    title = QLabel(_("Welcome to dictee!"))
    title.setStyleSheet("font-size: 20px; font-weight: bold;")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(title)

    subtitle = QLabel(_("Choose your speech recognition engine."))
    subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
    subtitle.setStyleSheet("color: #888;")
    lay.addWidget(subtitle)

    # Visual radio buttons
    self.asr_radio_group = QButtonGroup(self)
    backends = [
        ("parakeet", "Parakeet-TDT 0.6B", _("Recommended"), _("25 languages, ~2.5 GB, ~0.8s")),
        ("vosk", "Vosk", _("Lightweight"), _("9+ languages, ~50 MB, ~1.5s")),
        ("whisper", "faster-whisper", _("99 languages"), _("~500 MB–3 GB, ~0.3s")),
    ]
    self._asr_radio_frames = {}
    for i, (key, name, badge, desc) in enumerate(backends):
        frame = self._make_radio_card(name, badge, desc)
        radio = QRadioButton()
        radio.setFixedSize(0, 0)  # hidden, logic control only
        self.asr_radio_group.addButton(radio, i)
        frame.mousePressEvent = lambda e, r=radio, k=key: self._select_asr_radio(r, k)
        lay.addWidget(frame)
        self._asr_radio_frames[key] = (frame, radio)

    # Default selection
    self._select_asr_radio(
        self._asr_radio_frames.get(self._current_asr, self._asr_radio_frames["parakeet"])[1],
        self._current_asr if self._current_asr in self._asr_radio_frames else "parakeet"
    )

    # Conditional sub-options (Vosk language, Whisper model)
    self._build_asr_sub_options(lay)

    # Installation status + download button
    self._build_asr_model_status(lay)

    lay.addStretch()
```

- [ ] **Step 2: Create _make_radio_card()**

Reusable widget for visual radio buttons:

```python
def _make_radio_card(self, title, badge, description, selected=False):
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    frame.setCursor(Qt.CursorShape.PointingHandCursor)
    frame.setStyleSheet(self._card_style(selected))
    frame.setFixedHeight(70)

    lay = QVBoxLayout(frame)
    lay.setContentsMargins(12, 8, 12, 8)

    top = QHBoxLayout()
    lbl_title = QLabel(f"<b>{title}</b>")
    top.addWidget(lbl_title)
    if badge:
        lbl_badge = QLabel(badge)
        lbl_badge.setStyleSheet("background: #233; color: #6a6; padding: 2px 8px; border-radius: 10px; font-size: 11px;")
        top.addWidget(lbl_badge)
    top.addStretch()
    lay.addLayout(top)

    lbl_desc = QLabel(description)
    lbl_desc.setStyleSheet("color: #888; font-size: 12px;")
    lay.addWidget(lbl_desc)

    return frame

def _card_style(self, selected):
    border = "2px solid #5566ff" if selected else "1px solid #444"
    bg = "#252545" if selected else "#1e1e2e"
    return f"QFrame {{ background: {bg}; border: {border}; border-radius: 8px; }}"
```

- [ ] **Step 3: Create _select_asr_radio()**

```python
def _select_asr_radio(self, radio, key):
    radio.setChecked(True)
    self._current_asr = key
    # Update styles
    for k, (frame, _) in self._asr_radio_frames.items():
        frame.setStyleSheet(self._card_style(k == key))
    # Show/hide sub-options
    self._update_asr_sub_options(key)
```

- [ ] **Step 4: Implement _build_asr_sub_options() and _build_asr_model_status()**

Conditional sub-options (Vosk language, Whisper model) + installation status with Download button. Reuse existing Vosk/Whisper ComboBox logic (lines 1125-1180) but in the wizard layout.

- [ ] **Step 5: Implement _validate_asr_model()**

```python
def _validate_asr_model(self):
    """Verifies that the selected ASR model is installed."""
    key = self._current_asr
    if key == "parakeet":
        installed = self._check_parakeet_installed()
    elif key == "vosk":
        installed = self._check_vosk_model_installed()
    elif key == "whisper":
        installed = self._check_whisper_venv()
    else:
        installed = True

    if not installed:
        QMessageBox.warning(self, _("Model required"),
            _("Please download the model before continuing."))
    return installed
```

- [ ] **Step 6: Connect the page in _build_wizard_ui()**

Call `self._build_wizard_page_asr()` after creating the pages.

- [ ] **Step 7: Test**

```bash
dictee-setup --wizard  # Page 1: radio buttons, selection, sub-options, model status
```

- [ ] **Step 8: Commit**

```bash
git add dictee-setup.py
git commit -m "feat: wizard page 1 — ASR backend with visual radio buttons"
```

---

### Task 5: Page 2 — Keyboard Shortcuts

**Files:**
- Modify: `dictee-setup.py` — new method `_build_wizard_page_shortcuts()`

- [ ] **Step 1: Create _build_wizard_page_shortcuts()**

Reuses existing `ShortcutButton` (line 905), adapted to wizard layout:

```python
def _build_wizard_page_shortcuts(self):
    page = self.wizard_pages[1]
    lay = page.layout()

    title = QLabel(_("Keyboard shortcuts"))
    title.setStyleSheet("font-size: 20px; font-weight: bold;")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(title)

    # Detected environment
    env_label = QLabel(_("Detected: {env}").format(env=self.de_name))
    env_label.setStyleSheet("color: #8a8;")
    env_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(env_label)

    if self.de_type == "unsupported":
        # Tiling WM: show manual commands
        self._build_tiling_wm_instructions(lay)
    else:
        # KDE / GNOME: capture buttons
        form = QFormLayout()

        self.btn_capture = ShortcutButton(QKeySequence("F9"))
        self.btn_capture.shortcut_captured.connect(self._on_shortcut_captured)
        form.addRow(_("Voice dictation:"), self.btn_capture)

        self.btn_capture_translate = ShortcutButton(QKeySequence("Alt+F9"))
        self.btn_capture_translate.shortcut_captured.connect(self._on_shortcut_translate_captured)
        form.addRow(_("Dictation + Translation:"), self.btn_capture_translate)

        lay.addLayout(form)

        # Conflict detection (KDE only)
        if self.de_type == "kde":
            self.lbl_conflict = QLabel()
            lay.addWidget(self.lbl_conflict)
            self.btn_capture.shortcut_captured.connect(
                lambda seq: self._check_shortcut_conflict(seq, self.lbl_conflict))

    lay.addStretch()
```

- [ ] **Step 2: Implement _build_tiling_wm_instructions()**

```python
def _build_tiling_wm_instructions(self, layout):
    info = QLabel(_("Manual shortcut configuration required for your WM."))
    info.setStyleSheet("color: #ca6;")
    layout.addWidget(info)

    cmds = QLabel(
        "Sway/i3:\n"
        "  bindsym F9 exec dictee\n"
        "  bindsym Alt+F9 exec dictee --translate\n\n"
        "Hyprland:\n"
        "  bind = , F9, exec, dictee\n"
        "  bind = ALT, F9, exec, dictee --translate"
    )
    cmds.setStyleSheet("font-family: monospace; background: #1a1a2e; padding: 12px; border-radius: 6px;")
    cmds.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(cmds)
```

- [ ] **Step 3: Implement _check_shortcut_conflict()**

```python
def _check_shortcut_conflict(self, seq, label):
    """Checks KDE shortcut conflicts and displays in label."""
    accel = qt_key_to_kde(seq)
    conflict = check_kde_conflict(accel)
    if conflict:
        label.setText(_("⚠ Conflict: {app}").format(app=conflict))
        label.setStyleSheet("color: #ca6;")
    else:
        label.setText(_("✓ No conflict"))
        label.setStyleSheet("color: #6a6;")
```

- [ ] **Step 4: Connect in _build_wizard_ui()**

- [ ] **Step 5: Test**

```bash
dictee-setup --wizard  # Page 2: shortcuts, capture, conflict detection
```

- [ ] **Step 6: Commit**

```bash
git add dictee-setup.py
git commit -m "feat: wizard page 2 — keyboard shortcuts with conflict detection"
```

---

## Chunk 3: Pages 3 and 4

### Task 6: Page 3 — Translation

**Files:**
- Modify: `dictee-setup.py` — new method `_build_wizard_page_translation()`

- [ ] **Step 1: Create _build_wizard_page_translation()**

Visual radio buttons for translation backends, local ones first:

```python
def _build_wizard_page_translation(self):
    page = self.wizard_pages[2]
    lay = page.layout()

    title = QLabel(_("Translation"))
    title.setStyleSheet("font-size: 20px; font-weight: bold;")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(title)

    subtitle = QLabel(_("Dictate in one language, get text in another. Optional."))
    subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
    subtitle.setStyleSheet("color: #888;")
    lay.addWidget(subtitle)

    # Source / target languages
    lang_row = QHBoxLayout()
    src_lay = QVBoxLayout()
    src_lay.addWidget(QLabel(_("Source language")))
    self.combo_src = QComboBox()
    for code, name in LANGUAGES:
        self.combo_src.addItem(f"{name} ({code})", code)
    self._set_combo_by_data(self.combo_src, self._current_src_lang, 0)
    src_lay.addWidget(self.combo_src)
    lang_row.addLayout(src_lay)

    arrow = QLabel("→")
    arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lang_row.addWidget(arrow)

    tgt_lay = QVBoxLayout()
    tgt_lay.addWidget(QLabel(_("Target language")))
    self.combo_tgt = QComboBox()
    for code, name in LANGUAGES:
        self.combo_tgt.addItem(f"{name} ({code})", code)
    self._set_combo_by_data(self.combo_tgt, self._current_tgt_lang, 1)
    tgt_lay.addWidget(self.combo_tgt)
    lang_row.addLayout(tgt_lay)
    lay.addLayout(lang_row)

    # Visual radio buttons — local ones first
    self.trans_radio_group = QButtonGroup(self)
    backends = [
        ("ollama", "ollama", _("100% local — Best quality"), _("translategemma — 2.3–3.4s")),
        ("libretranslate", "LibreTranslate", _("100% local"), _("Docker ~2 GB — 0.1–0.3s")),
        ("trans:google", "Google Translate", _("Online — Fast"), _("0.2–0.7s — translate-shell")),
        ("trans:bing", "Bing", _("Online"), _("1.7–2.2s — translate-shell")),
    ]
    self._trans_radio_frames = {}
    for i, (key, name, badge, desc) in enumerate(backends):
        frame = self._make_radio_card(name, badge, desc)
        radio = QRadioButton()
        radio.setFixedSize(0, 0)
        self.trans_radio_group.addButton(radio, i)
        frame.mousePressEvent = lambda e, r=radio, k=key: self._select_trans_radio(r, k)
        lay.addWidget(frame)
        self._trans_radio_frames[key] = (frame, radio)

    # Default selection
    default_trans = self._current_trans_backend or "trans:google"
    if default_trans in self._trans_radio_frames:
        self._select_trans_radio(self._trans_radio_frames[default_trans][1], default_trans)

    # Conditional sub-options (ollama model, LT port)
    self._build_trans_sub_options_wizard(lay)

    # Dependency status
    self._build_trans_deps_status(lay)

    lay.addStretch()
```

- [ ] **Step 2: Create _select_trans_radio()**

```python
def _select_trans_radio(self, radio, key):
    radio.setChecked(True)
    self._current_trans_backend = key
    for k, (frame, _) in self._trans_radio_frames.items():
        frame.setStyleSheet(self._card_style(k == key))
    self._update_trans_sub_options_wizard(key)
```

- [ ] **Step 3: Implement sub-options and dependency detection**

Ollama sub-options (model, download) and LibreTranslate (port, Docker) that appear conditionally. Automatic detection: `shutil.which("trans")`, `shutil.which("ollama")`, `shutil.which("docker")`.

- [ ] **Step 4: Connect in _build_wizard_ui()**

- [ ] **Step 5: Test**

```bash
dictee-setup --wizard  # Page 3: translation, radio buttons, sub-options
```

- [ ] **Step 6: Commit**

```bash
git add dictee-setup.py
git commit -m "feat: wizard page 3 — translation with local backends first"
```

---

### Task 7: AudioLevelThread + list_audio_sources()

**Files:**
- Modify: `dictee-setup.py` — new classes/functions before DicteeSetupDialog

- [ ] **Step 1: Implement list_audio_sources()**

```python
def list_audio_sources():
    """Lists microphone sources via pactl or wpctl.
    Returns [(id, description), ...] or [] if nothing detected.
    """
    sources = []
    try:
        out = subprocess.run(
            ["pactl", "list", "sources", "short"],
            capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            for line in out.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2 and "monitor" not in parts[1].lower():
                    source_id = parts[1]
                    desc = parts[1].replace(".", " ").replace("_", " ")
                    sources.append((source_id, desc))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if not sources:
        # Fallback wpctl
        try:
            out = subprocess.run(
                ["wpctl", "status"],
                capture_output=True, text=True, timeout=5
            )
            if out.returncode == 0:
                in_sources = False
                for line in out.stdout.splitlines():
                    if "Sources:" in line:
                        in_sources = True
                        continue
                    if in_sources and line.strip() == "":
                        break
                    if in_sources and "│" in line:
                        # Parse "│  * 47. source_name [vol: ...]"
                        m = re.search(r'(\d+)\.\s+(.+?)(?:\s+\[|$)', line)
                        if m:
                            sources.append((m.group(1), m.group(2).strip()))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return sources
```

- [ ] **Step 2: Implement AudioLevelThread**

```python
class AudioLevelThread(QThread):
    """Continuously reads the microphone, emits RMS level (0-100)."""
    level = Signal(int)

    def __init__(self, source_id=None):
        super().__init__()
        self._running = True
        self._source_id = source_id
        self._process = None

    def run(self):
        import struct, math
        cmd = self._build_record_cmd()
        if not cmd:
            return
        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            while self._running and self._process.poll() is None:
                # 100ms of s16le mono 16kHz = 3200 bytes = 1600 samples
                data = self._process.stdout.read(3200)
                if len(data) < 3200:
                    break
                samples = struct.unpack(f"<{len(data)//2}h", data)
                rms = math.sqrt(sum(s*s for s in samples) / len(samples))
                normalized = min(100, int(rms / 327.67))  # 32767 → 100
                self.level.emit(normalized)
        except Exception:
            pass
        finally:
            self.stop()

    def _build_record_cmd(self):
        """Builds the parec or pw-record command."""
        if shutil.which("parec"):
            cmd = ["parec", "--format=s16le", "--rate=16000", "--channels=1"]
            if self._source_id:
                cmd.extend(["--device", self._source_id])
            return cmd
        elif shutil.which("pw-record"):
            cmd = ["pw-record", "--format=s16", "--rate=16000", "--channels=1", "-"]
            return cmd
        return None

    def stop(self):
        self._running = False
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
```

- [ ] **Step 3: Unit test**

```python
# Quick test in a Python terminal
from dictee_setup import list_audio_sources
print(list_audio_sources())  # must list microphones
```

- [ ] **Step 4: Commit**

```bash
git add dictee-setup.py
git commit -m "feat: AudioLevelThread and list_audio_sources() for microphone monitoring"
```

---

### Task 8: Page 4 — Microphone, visual feedback, services

**Files:**
- Modify: `dictee-setup.py` — new method `_build_wizard_page_visual()`

- [ ] **Step 1: Create _build_wizard_page_visual() — Microphone section**

```python
def _build_wizard_page_visual(self):
    page = self.wizard_pages[3]
    lay = page.layout()

    # Use a QScrollArea since this page is dense
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    content = QWidget()
    content_lay = QVBoxLayout(content)

    title = QLabel(_("Microphone, visual feedback & services"))
    title.setStyleSheet("font-size: 20px; font-weight: bold;")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    content_lay.addWidget(title)

    # === Microphone ===
    mic_group = QGroupBox(_("Microphone"))
    mic_lay = QVBoxLayout(mic_group)

    # Audio source
    sources = list_audio_sources()
    self.cmb_audio_source = QComboBox()
    if sources:
        for src_id, desc in sources:
            self.cmb_audio_source.addItem(desc, src_id)
    else:
        self.cmb_audio_source.addItem(_("No microphone detected"), "")
        self.cmb_audio_source.setEnabled(False)

    mic_lay.addWidget(QLabel(_("Audio source:")))
    mic_lay.addWidget(self.cmb_audio_source)

    # Volume slider
    from PyQt6.QtWidgets import QSlider
    vol_row = QHBoxLayout()
    vol_row.addWidget(QLabel(_("Volume:")))
    self.slider_volume = QSlider(Qt.Orientation.Horizontal)
    self.slider_volume.setRange(0, 150)
    self.slider_volume.setValue(100)
    self.slider_volume.valueChanged.connect(self._on_volume_changed)
    vol_row.addWidget(self.slider_volume)
    self.lbl_volume = QLabel("100%")
    vol_row.addWidget(self.lbl_volume)
    mic_lay.addLayout(vol_row)

    # Level indicator
    self.bar_mic_level = QProgressBar()
    self.bar_mic_level.setRange(0, 100)
    self.bar_mic_level.setTextVisible(False)
    self.bar_mic_level.setFixedHeight(12)
    mic_lay.addWidget(self.bar_mic_level)

    # Warning if no microphone
    if not sources:
        warn = QLabel(_("⚠ No microphone detected. Check your audio connection."))
        warn.setStyleSheet("color: #ca6;")
        mic_lay.addWidget(warn)

    content_lay.addWidget(mic_group)
```

- [ ] **Step 2: Visual feedback section (checkboxes)**

```python
    # === Visual feedback ===
    vis_group = QGroupBox(_("Visual feedback during recording"))
    vis_lay = QVBoxLayout(vis_group)

    self.chk_plasmoid = QCheckBox(_("KDE Plasma widget"))
    self.chk_anim_speech = QCheckBox(_("animation-speech (fullscreen overlay, Wayland)"))
    self.chk_tray = QCheckBox(_("Notification icon (dictee-tray)"))

    # Smart pre-checking
    if self.de_type == "kde":
        self.chk_plasmoid.setChecked(True)
    else:
        self.chk_tray.setChecked(True)

    # Installation status
    for chk, check_fn, name in [
        (self.chk_plasmoid, self._check_plasmoid_installed, "plasmoid"),
        (self.chk_anim_speech, lambda: bool(shutil.which(ANIMATION_SPEECH_BIN)), "animation-speech"),
    ]:
        if check_fn():
            chk.setToolTip(_("✓ Installed"))
        else:
            chk.setToolTip(_("Not installed"))

    vis_lay.addWidget(self.chk_plasmoid)
    vis_lay.addWidget(self.chk_anim_speech)
    vis_lay.addWidget(self.chk_tray)
    content_lay.addWidget(vis_group)
```

- [ ] **Step 3: Startup services section**

```python
    # === Services ===
    svc_group = QGroupBox(_("Startup services"))
    svc_lay = QVBoxLayout(svc_group)

    self.chk_daemon = QCheckBox(_("Start transcription daemon at login"))
    self.chk_daemon.setChecked(True)
    svc_lay.addWidget(self.chk_daemon)

    self.chk_clipboard = QCheckBox(_("Copy transcription to clipboard"))
    self.chk_clipboard.setChecked(False)
    svc_lay.addWidget(self.chk_clipboard)

    content_lay.addWidget(svc_group)

    content_lay.addStretch()
    scroll.setWidget(content)
    lay.addWidget(scroll)
```

- [ ] **Step 4: Implement _on_volume_changed()**

```python
def _on_volume_changed(self, value):
    self.lbl_volume.setText(f"{value}%")
    vol = value / 100.0
    source = self.cmb_audio_source.currentData()
    if shutil.which("wpctl") and source:
        subprocess.Popen(["wpctl", "set-volume", source, f"{vol:.2f}"])
    elif shutil.which("pactl") and source:
        subprocess.Popen(["pactl", "set-source-volume", source, f"{value}%"])
```

- [ ] **Step 5: Start/stop AudioLevelThread**

Start the thread when arriving on page 4, stop it when leaving:

```python
def _start_audio_level(self):
    source = self.cmb_audio_source.currentData() if hasattr(self, 'cmb_audio_source') else None
    if source:
        self._audio_thread = AudioLevelThread(source)
        self._audio_thread.level.connect(self.bar_mic_level.setValue)
        self._audio_thread.start()

def _stop_audio_level(self):
    if hasattr(self, '_audio_thread') and self._audio_thread.isRunning():
        self._audio_thread.stop()
        self._audio_thread.wait(2000)
```

Modify `_wizard_next()` and `_wizard_prev()` to call `_start_audio_level()` on page 4 entry and `_stop_audio_level()` on exit.

- [ ] **Step 6: Connect in _build_wizard_ui()**

- [ ] **Step 7: Test**

```bash
dictee-setup --wizard  # Page 4: microphone with level, visual, services
```

- [ ] **Step 8: Commit**

```bash
git add dictee-setup.py
git commit -m "feat: wizard page 4 — microphone, visual feedback, startup services"
```

---

## Chunk 4: Page 5, integration, i18n, polish

### Task 9: Page 5 — Test

**Files:**
- Modify: `dictee-setup.py` — new method `_build_wizard_page_test()`

- [ ] **Step 1: Create _build_wizard_page_test()**

```python
def _build_wizard_page_test(self):
    page = self.wizard_pages[4]
    lay = page.layout()

    title = QLabel(_("Let's test!"))
    title.setStyleSheet("font-size: 20px; font-weight: bold;")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(title)

    subtitle = QLabel(_("Let's verify everything works correctly."))
    subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
    subtitle.setStyleSheet("color: #888;")
    lay.addWidget(subtitle)

    # Automatic checks
    checks_group = QGroupBox(_("Automatic checks"))
    checks_lay = QVBoxLayout(checks_group)
    self._check_labels = {}
    check_items = [
        ("daemon", _("ASR Daemon")),
        ("model", _("Model installed")),
        ("shortcut", _("Shortcut registered")),
        ("audio", _("Audio (PipeWire/PulseAudio)")),
        ("dotool", _("dotool")),
    ]
    for key, label_text in check_items:
        row = QHBoxLayout()
        icon = QLabel("⏳")
        icon.setFixedWidth(24)
        lbl = QLabel(label_text)
        btn_fix = QPushButton(_("Fix"))
        btn_fix.setFixedWidth(60)
        btn_fix.hide()
        row.addWidget(icon)
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(btn_fix)
        checks_lay.addLayout(row)
        self._check_labels[key] = (icon, lbl, btn_fix)

    lay.addWidget(checks_group)

    # Dictation test
    test_group = QGroupBox(_("Dictation test"))
    test_lay = QVBoxLayout(test_group)
    test_lay.addWidget(QLabel(_("Click the button below and speak for a few seconds.")))

    self.btn_test_dictee = QPushButton(_("🎤 Test dictation"))
    self.btn_test_dictee.setStyleSheet("padding: 12px 24px; font-size: 14px;")
    self.btn_test_dictee.clicked.connect(self._on_test_dictee)
    test_lay.addWidget(self.btn_test_dictee)

    from PyQt6.QtWidgets import QTextEdit
    self.txt_test_result = QTextEdit()
    self.txt_test_result.setReadOnly(True)
    self.txt_test_result.setMaximumHeight(80)
    self.txt_test_result.setPlaceholderText(_("Result will appear here..."))
    test_lay.addWidget(self.txt_test_result)

    lay.addWidget(test_group)

    # Final message
    self.lbl_ready = QLabel(_("🎉 All set! Press your shortcut anytime to dictate."))
    self.lbl_ready.setStyleSheet("color: #afa; font-size: 16px; font-weight: bold;")
    self.lbl_ready.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.lbl_ready.hide()
    lay.addWidget(self.lbl_ready)

    lay.addStretch()
```

- [ ] **Step 2: Implement _run_wizard_checks()**

```python
def _run_wizard_checks(self):
    """Runs the automatic checks on page 5."""
    checks = {
        "daemon": self._check_daemon_active,
        "model": self._check_model_installed,
        "shortcut": self._check_shortcut_registered,
        "audio": self._check_audio_available,
        "dotool": lambda: bool(shutil.which("dotool")),
    }
    page_map = {"daemon": 0, "model": 0, "shortcut": 1, "audio": 3}
    all_ok = True

    for key, check_fn in checks.items():
        icon, lbl, btn_fix = self._check_labels[key]
        try:
            ok = check_fn()
        except Exception:
            ok = False

        if ok:
            icon.setText("✓")
            icon.setStyleSheet("color: #6a6; font-size: 18px;")
            btn_fix.hide()
        else:
            icon.setText("✗")
            icon.setStyleSheet("color: #a66; font-size: 18px;")
            if key in page_map:
                btn_fix.show()
                target_page = page_map[key]
                btn_fix.clicked.connect(lambda _, p=target_page: self._go_to_page(p))
            all_ok = False

    if all_ok:
        self.lbl_ready.show()

def _go_to_page(self, page_idx):
    self.stack.setCurrentIndex(page_idx)
    self._update_wizard_nav()
```

- [ ] **Step 3: Implement individual check functions**

```python
def _check_daemon_active(self):
    asr = self._current_asr
    svc = {"parakeet": "dictee", "vosk": "dictee-vosk", "whisper": "dictee-whisper"}.get(asr, "dictee")
    r = subprocess.run(["systemctl", "--user", "is-active", svc], capture_output=True, text=True)
    return r.stdout.strip() == "active"

def _check_model_installed(self):
    asr = self._current_asr
    if asr == "parakeet":
        return self._check_parakeet_installed()
    elif asr == "vosk":
        return self._check_vosk_model_installed()
    elif asr == "whisper":
        return self._check_whisper_venv()
    return True

def _check_shortcut_registered(self):
    if self.de_type == "kde":
        # Check in kglobalshortcutsrc
        rc = os.path.expanduser("~/.config/kglobalshortcutsrc")
        if os.path.isfile(rc):
            with open(rc) as f:
                return "dictee.desktop" in f.read()
    return True  # GNOME/unsupported: assumed OK

def _check_audio_available(self):
    return bool(list_audio_sources())
```

- [ ] **Step 4: Implement _on_test_dictee()**

```python
def _on_test_dictee(self):
    """Launches transcribe-client as a subprocess for testing."""
    self.btn_test_dictee.setText(_("⏹ Stop"))
    self.btn_test_dictee.setEnabled(True)
    self.txt_test_result.clear()

    self._test_thread = TestDicteeThread()
    self._test_thread.result.connect(self._on_test_result)
    self._test_thread.start()

class TestDicteeThread(QThread):
    result = Signal(str)

    def run(self):
        try:
            r = subprocess.run(
                ["transcribe-client"],
                capture_output=True, text=True, timeout=10
            )
            self.result.emit(r.stdout.strip() if r.returncode == 0 else _("Error: ") + r.stderr.strip())
        except subprocess.TimeoutExpired:
            self.result.emit(_("Timeout (10s)"))
        except FileNotFoundError:
            self.result.emit(_("transcribe-client not found"))

def _on_test_result(self, text):
    self.txt_test_result.setPlainText(text)
    self.btn_test_dictee.setText(_("🎤 Test dictation"))
```

- [ ] **Step 5: Connect in _build_wizard_ui()**

- [ ] **Step 6: Test**

```bash
dictee-setup --wizard  # Page 5: automatic checks + dictation test
```

- [ ] **Step 7: Commit**

```bash
git add dictee-setup.py
git commit -m "feat: wizard page 5 — automatic checks and dictation test"
```

---

### Task 10: Connect _on_apply() to the wizard

**Files:**
- Modify: `dictee-setup.py` — `_on_wizard_finish()` and `_on_apply()`

- [ ] **Step 1: Adapt _on_apply() to support both modes**

Wizard mode uses `self._current_asr` and `self._current_trans_backend` (strings) instead of ComboBoxes. Modify `_on_apply()` to read from the correct sources:

```python
def _on_apply(self):
    if self.wizard_mode:
        trans_data = self._current_trans_backend
        asr_backend = self._current_asr
        # The language/volume ComboBoxes exist in both modes
    else:
        trans_data = self.cmb_trans_backend.currentData()
        asr_backend = self.cmb_asr_backend.currentData() or "parakeet"

    # ... rest of the code is identical, use trans_data and asr_backend
```

- [ ] **Step 2: Save DICTEE_AUDIO_SOURCE**

Add in `save_config()`:

```python
def save_config(..., audio_source=""):
    # ... existing lines ...
    if audio_source:
        f.write(f"DICTEE_AUDIO_SOURCE={audio_source}\n")
```

And in `_on_apply()`:
```python
audio_source = ""
if hasattr(self, 'cmb_audio_source'):
    audio_source = self.cmb_audio_source.currentData() or ""
```

- [ ] **Step 3: Test the complete flow**

```bash
# Remove config to test first launch
mv ~/.config/dictee.conf ~/.config/dictee.conf.bak
dictee-setup  # must open in wizard mode
# Navigate the 5 pages → Finish → verify dictee.conf created
mv ~/.config/dictee.conf.bak ~/.config/dictee.conf
```

- [ ] **Step 4: Commit**

```bash
git add dictee-setup.py
git commit -m "feat: connect _on_apply() to wizard + DICTEE_AUDIO_SOURCE"
```

---

### Task 11: Microphone section in classic mode

**Files:**
- Modify: `dictee-setup.py` — `_build_classic_ui()`

- [ ] **Step 1: Add the Microphone section in the classic form**

After the existing "Visual feedback" section, add a QGroupBox "Microphone" with:
- Audio source ComboBox
- Volume slider
- Level bar (AudioLevelThread)

Reuse the same logic as wizard page 4.

- [ ] **Step 2: Start AudioLevelThread on open in classic mode**

In `_build_classic_ui()`, start the thread. Stop it in `closeEvent()`.

- [ ] **Step 3: Test**

```bash
dictee-setup  # classic mode, verify the microphone section
```

- [ ] **Step 4: Commit**

```bash
git add dictee-setup.py
git commit -m "feat: microphone section in classic form"
```

---

### Task 12: i18n — new strings

**Files:**
- Modify: `po/dictee.pot`
- Modify: `po/{fr,de,es,it,uk,pt}.po`

- [ ] **Step 1: Extract new strings**

```bash
xgettext --language=Python --keyword=_ --output=po/dictee.pot \
    --package-name=dictee --package-version=1.1.0 \
    dictee-setup.py dictee-tray.py
```

- [ ] **Step 2: Update .po files**

```bash
for lang in fr de es it uk pt; do
    msgmerge --update po/$lang.po po/dictee.pot
done
```

- [ ] **Step 3: Translate new strings (~30)**

Open each `.po` file and translate strings marked `fuzzy` or empty. Main strings:
- "Welcome to dictee!", "Choose your speech recognition engine."
- "Keyboard shortcuts", "Previous", "Next", "Finish"
- "Translation", "Dictate in one language, get text in another."
- "Microphone", "Audio source:", "Volume:", "No microphone detected."
- "Let's test!", "Test dictation", "All set!"
- "Setup wizard", "Step {n} of 5"
- Etc.

- [ ] **Step 4: Compile .mo files**

```bash
for lang in fr de es it uk pt; do
    msgfmt -o po/$lang.mo po/$lang.po
done
```

- [ ] **Step 5: Commit**

```bash
git add po/
git commit -m "feat: wizard i18n — 6 languages (fr, de, es, it, uk, pt)"
```

---

### Task 13: Version bump 1.1.0

**Files:**
- Modify: `Cargo.toml` (version)
- Modify: `build-deb.sh` (×3: version, pkg name, changelog)
- Modify: `pkg/dictee/DEBIAN/control` (version)
- Modify: `plasmoid/package/metadata.json` (version)
- Modify: `README.md`, `README.fr.md` (version badge/text)

- [ ] **Step 1: Bump all files**

Follow the MEMORY.md checklist: Cargo.toml, build-deb.sh (×3), control, metadata.json, READMEs.

- [ ] **Step 2: Commit**

```bash
git add Cargo.toml build-deb.sh pkg/dictee/DEBIAN/control plasmoid/package/metadata.json README.md README.fr.md
git commit -m "chore: bump version 1.0.0 → 1.1.0"
```

---

### Task 14: Final integration test

- [ ] **Step 1: Test wizard first launch**

```bash
mv ~/.config/dictee.conf ~/.config/dictee.conf.bak
dictee-setup  # must open in wizard mode automatically
# Navigate all pages, verify each section
# Finish → verify dictee.conf created with all keys
mv ~/.config/dictee.conf.bak ~/.config/dictee.conf
```

- [ ] **Step 2: Test forced wizard**

```bash
dictee --setup --wizard  # must open in wizard even with existing config
dictee-setup --wizard    # same
```

- [ ] **Step 3: Test classic mode**

```bash
dictee-setup  # classic mode (config exists)
# Verify: "Wizard" button present, microphone section present
# Click "Wizard" → must relaunch in wizard mode
```

- [ ] **Step 4: Test i18n**

```bash
LANGUAGE=de dictee-setup --wizard  # verify German translation
LANGUAGE=es dictee-setup --wizard  # verify Spanish translation
```

- [ ] **Step 5: Final commit if fixes needed**

```bash
git add -u
git commit -m "fix: wizard integration fixes"
```
