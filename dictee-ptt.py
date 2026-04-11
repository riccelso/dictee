#!/usr/bin/env -S python3 -u
"""dictee-ptt — push-to-talk / toggle daemon for dictee.

Listens to physical keyboards via evdev, exclusively captures the configured
key (grab + uinput re-emission), and triggers dictee according to the mode.

In hold mode: key-down = start, key-up = stop+transcribe.
In toggle mode: key-down = alternate start/stop.

Usage:
    dictee-ptt [--mode=toggle|hold] [--key=67] [--key-translate=67] [--mod-translate=alt]
    dictee-ptt --help

Examples:
    dictee-ptt --mode=hold --key=67                        # F9 hold
    dictee-ptt --mode=hold --key=67 --key-translate=67 --mod-translate=alt  # F9 + Alt+F9
    dictee-ptt --mode=toggle --key=67 --key-translate=68   # F9 / F10 separate

Requires: 'input' group for /dev/input/* and /dev/uinput.

Common Linux keycodes:
    F1=59  F2=60  F3=61  F4=62  F5=63  F6=64  F7=65  F8=66
    F9=67  F10=68 F11=87 F12=88 ESC=1
"""

import subprocess
import signal
import select
import os
import sys
import time
import fcntl
import re

try:
    import evdev
    from evdev import InputDevice, UInput, ecodes

    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False

# --- Config ---

CONF_PATH = os.path.expanduser("~/.config/dictee.conf")
DICTEE_BIN = None  # auto-detect
PIDFILE = "/tmp/recording_dictee_pid"
OWN_PIDFILE = "/tmp/dictee-ptt.pid"

EV_KEY = 1
KEY_DOWN = 1
KEY_UP = 0
KEY_REPEAT = 2
KEY_ESC = 1
KEY_LEFTALT = 56
KEY_RIGHTALT = 100
KEY_LEFTCTRL = 29
KEY_RIGHTCTRL = 97
KEY_LEFTSHIFT = 42
KEY_RIGHTSHIFT = 54

# Supported modifiers: name -> (left keycode, right keycode)
MODIFIERS = {
    "alt": (KEY_LEFTALT, KEY_RIGHTALT),
    "ctrl": (KEY_LEFTCTRL, KEY_RIGHTCTRL),
    "shift": (KEY_LEFTSHIFT, KEY_RIGHTSHIFT),
}

DEBOUNCE = 0.15  # 150ms debounce
STOP_COOLDOWN = 0.5  # 500ms — ignore spurious KEY_DOWN after stop
PIDFILE_TIMEOUT = 3.0  # attente max PIDFILE au key-up
MIN_HOLD_DURATION = 0.3  # 300ms — en dessous, cancel au lieu de transcrire
RESCAN_INTERVAL = 10  # secondes entre rescans claviers (hotplug)


def load_config():
    """Charge dictee.conf et retourne un dict."""
    conf = {}
    if os.path.isfile(CONF_PATH):
        with open(CONF_PATH) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    conf[k.strip()] = v.strip().strip('"').strip("'")
    return conf


def find_keyboards_evdev():
    """Find physical keyboards via evdev."""
    devs = []
    for path in evdev.list_devices():
        try:
            dev = InputDevice(path)
        except (PermissionError, OSError):
            continue
        caps = dev.capabilities(verbose=False)
        # EV_KEY present and at least alphanumeric keys
        if EV_KEY in caps and len(caps.get(EV_KEY, [])) > 30:
            name = dev.name.lower()
            if not any(
                x in name for x in ("virtual", "uinput", "dotool", "dictee-ptt")
            ):
                devs.append(dev)
            else:
                dev.close()
        else:
            dev.close()
    return devs


def find_keyboards_raw():
    """Find physical keyboards via /proc/bus/input/devices (fallback)."""
    devs = []
    try:
        with open("/proc/bus/input/devices") as f:
            content = f.read()
    except (PermissionError, FileNotFoundError):
        return devs

    for block in content.split("\n\n"):
        lines = block.strip().splitlines()
        name_line = handlers_line = ""
        for line in lines:
            if line.startswith("N:"):
                name_line = line
            elif line.startswith("H:"):
                handlers_line = line
        if "kbd" in handlers_line:
            if not re.search(
                r"virtual|uinput|dotool|dictee-ptt", name_line, re.IGNORECASE
            ):
                m = re.search(r"event\d+", handlers_line)
                if m:
                    devs.append(f"/dev/input/{m.group()}")
    return devs


def find_dictee_bin():
    """Trouve le script dictee."""
    for p in [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "dictee"),
        os.path.expanduser("~/.local/bin/dictee"),
        "/usr/bin/dictee",
    ]:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return "dictee"


def run_dictee_async(*args, no_animation=False):
    """Lance dictee en subprocess non-bloquant."""
    cmd = [DICTEE_BIN, "--no-esc-listener"] + list(args)
    env = None
    if no_animation:
        env = os.environ.copy()
        env["DICTEE_ANIMATION"] = "none"
    try:
        subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
        )
    except Exception as e:
        print(f"[ptt] error {cmd}: {e}", file=sys.stderr)


def wait_pidfile():
    """Wait for PIDFILE to appear (dictee started pw-record)."""
    deadline = time.monotonic() + PIDFILE_TIMEOUT
    while time.monotonic() < deadline:
        if os.path.isfile(PIDFILE):
            return True
        time.sleep(0.02)
    return False


def acquire_lock():
    """Prevent multiple instances via flock."""
    try:
        lf = open(OWN_PIDFILE, "w")
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lf.write(str(os.getpid()))
        lf.flush()
        return lf
    except OSError:
        print("[ptt] another instance is already active!", file=sys.stderr)
        sys.exit(1)


def sync_state():
    """Resync internal state with real state (PIDFILE)."""
    return os.path.isfile(PIDFILE)


# ─── Common PTT logic ────────────────────────────────────────────────


class PttState:
    def __init__(
        self,
        mode,
        key_dictee,
        key_translate,
        mod_translate="",
        key_llm=0,
        key_translate_llm=0,
    ):
        self.mode = mode
        self.key_dictee = key_dictee
        self.key_translate = key_translate
        # Modifier for translation (e.g. "alt" -> Alt+F9)
        self.mod_translate = mod_translate
        # Keys for LLM modes
        self.key_llm = key_llm
        self.key_translate_llm = key_translate_llm
        self.recording = False
        self.recording_translate = False
        self.recording_llm = False
        self.recording_translate_llm = False
        self.last_down_time = 0
        self.last_stop_time = 0
        self.keys_held = set()

    def _mod_held(self, mod_name):
        """Check if a modifier is held."""
        if not mod_name or mod_name not in MODIFIERS:
            return False
        left, right = MODIFIERS[mod_name]
        return left in self.keys_held or right in self.keys_held

    def _any_mod_held(self):
        """Check if any modifier is held."""
        for left, right in MODIFIERS.values():
            if left in self.keys_held or right in self.keys_held:
                return True
        return False

    def _any_recording(self):
        """Return True if a recording is active."""
        return (
            self.recording
            or self.recording_translate
            or self.recording_llm
            or self.recording_translate_llm
        )

    def handle_event(self, code, value):
        """Process a keyboard event. Returns True if the event is consumed."""
        all_keys = {
            k
            for k in (
                self.key_dictee,
                self.key_translate,
                self.key_llm,
                self.key_translate_llm,
            )
            if k
        }
        if value == KEY_REPEAT:
            return code in all_keys or code == KEY_ESC

        # Deduplicate multiple keyboards
        if value == KEY_DOWN:
            if code in self.keys_held:
                return code in all_keys
            self.keys_held.add(code)
        elif value == KEY_UP:
            self.keys_held.discard(code)

        now = time.monotonic()

        # Resync if dictee has crashed
        if self._any_recording() and now - self.last_down_time > PIDFILE_TIMEOUT + 2:
            if not sync_state():
                print("[ptt] resync: recording stopped externally")
                self.recording = False
                self.recording_translate = False
                self.recording_llm = False
                self.recording_translate_llm = False
                self.last_stop_time = now

        # ESC: cancel
        if code == KEY_ESC and value == KEY_DOWN:
            if self._any_recording():
                print("[ptt] ESC → cancel")
                run_dictee_async("--cancel")
                self.recording = False
                self.recording_translate = False
                self.recording_llm = False
                self.recording_translate_llm = False
                self.last_stop_time = now
            return False  # let ESC through to applications

        # Prevent simultaneous recordings (separate keys)
        if self._any_recording():
            if not self.recording and code == self.key_dictee:
                return True
            if not self.recording_translate and code == self.key_translate:
                return True
            if not self.recording_llm and code == self.key_llm:
                return True
            if not self.recording_translate_llm and code == self.key_translate_llm:
                return True

        # Transcribe+LLM+translate key (high priority)
        if self.key_translate_llm and code == self.key_translate_llm:
            self._handle_translate_llm(value, now)
            return True

        # Transcribe+LLM only key
        if self.key_llm and code == self.key_llm:
            self._handle_llm(value, now)
            return True

        # Dictation key (or dictation+translation if same key with modifier)
        if code == self.key_dictee:
            if self.key_translate and self.key_translate == self.key_dictee:
                # Same key for dictation and translation — route by state
                if value == KEY_UP:
                    # KEY_UP: route to active handler, NOT by modifier
                    # (user may release Alt before F9)
                    if self.recording_translate:
                        # Toggle: already in translation -> stop
                        self._handle_translate(value, now)
                    elif self.recording:
                        # Toggle: already in dictation -> stop
                        self._handle_dictee(value, now)
                    elif self.mod_translate and self._mod_held(self.mod_translate):
                        self._handle_translate(value, now)
                    elif not self._any_mod_held():
                        self._handle_dictee(value, now)
                    else:
                        return False  # unknown modifier, let through
            else:
                # Separate keys — direct route
                if self.mod_translate and self._mod_held(self.mod_translate):
                    self._handle_translate(value, now)
                else:
                    self._handle_dictee(value, now)
            return True  # consommer

        # Separate translation key (different from key_dictee)
        if self.key_translate and code == self.key_translate:
            self._handle_translate(value, now)
            return True  # consume

        return False  # let through

    def _check_debounce(self, now):
        if now - self.last_down_time < DEBOUNCE:
            return False
        if now - self.last_stop_time < STOP_COOLDOWN:
            return False
        return True

    def _handle_dictee(self, value, now):
        if self.mode == "hold":
            if value == KEY_DOWN and not self.recording:
                if not self._check_debounce(now):
                    return
                self.last_down_time = now
                print("[ptt] hold: start")
                run_dictee_async(no_animation=True)
                self.recording = True
            elif value == KEY_UP and self.recording:
                # Always wait for PIDFILE before acting
                for _ in range(50):  # 1s max
                    if os.path.isfile(PIDFILE):
                        break
                    time.sleep(0.02)
                hold_duration = now - self.last_down_time
                if hold_duration < MIN_HOLD_DURATION:
                    print("[ptt] hold: cancel (trop court)")
                    run_dictee_async("--cancel")
                else:
                    print("[ptt] hold: stop")
                    run_dictee_async()
                self.recording = False
                self.last_stop_time = now
        else:  # toggle
            if value == KEY_DOWN:
                if not self._check_debounce(now):
                    return
                self.last_down_time = now
                if not self.recording:
                    print("[ptt] toggle: start")
                    run_dictee_async()
                    self.recording = True
                else:
                    print("[ptt] toggle: stop")
                    run_dictee_async()
                    self.recording = False
                    self.last_stop_time = now

    def _handle_translate(self, value, now):
        if self.mode == "hold":
            if value == KEY_DOWN and not self.recording_translate:
                if not self._check_debounce(now):
                    return
                self.last_down_time = now
                print("[ptt] hold: start+translate")
                run_dictee_async("--translate", no_animation=True)
                self.recording_translate = True
            elif value == KEY_UP and self.recording_translate:
                # Always wait for PIDFILE before acting
                for _ in range(50):  # 1s max
                    if os.path.isfile(PIDFILE):
                        break
                    time.sleep(0.02)
                hold_duration = now - self.last_down_time
                if hold_duration < MIN_HOLD_DURATION:
                    print("[ptt] hold: cancel+translate (trop court)")
                    run_dictee_async("--cancel")
                else:
                    print("[ptt] hold: stop+translate")
                    run_dictee_async("--translate")
                self.recording_translate = False
                self.last_stop_time = now
        else:  # toggle
            if value == KEY_DOWN:
                if not self._check_debounce(now):
                    return
                self.last_down_time = now
                if not self.recording_translate:
                    print("[ptt] toggle: start+translate")
                    run_dictee_async("--translate")
                    self.recording_translate = True
                else:
                    print("[ptt] toggle: stop+translate")
                    run_dictee_async("--translate")
                    self.recording_translate = False
                    self.last_stop_time = now

    def _handle_llm(self, value, now):
        if self.mode == "hold":
            if value == KEY_DOWN and not self.recording_llm:
                if not self._check_debounce(now):
                    return
                self.last_down_time = now
                print("[ptt] hold: start+llm")
                run_dictee_async("--llm", no_animation=True)
                self.recording_llm = True
            elif value == KEY_UP and self.recording_llm:
                for _ in range(50):  # 1s max
                    if os.path.isfile(PIDFILE):
                        break
                    time.sleep(0.02)
                hold_duration = now - self.last_down_time
                if hold_duration < MIN_HOLD_DURATION:
                    print("[ptt] hold: cancel+llm (trop court)")
                    run_dictee_async("--cancel")
                else:
                    print("[ptt] hold: stop+llm")
                    run_dictee_async("--llm")
                self.recording_llm = False
                self.last_stop_time = now
        else:  # toggle
            if value == KEY_DOWN:
                if not self._check_debounce(now):
                    return
                self.last_down_time = now
                if not self.recording_llm:
                    print("[ptt] toggle: start+llm")
                    run_dictee_async("--llm")
                    self.recording_llm = True
                else:
                    print("[ptt] toggle: stop+llm")
                    run_dictee_async("--llm")
                    self.recording_llm = False
                    self.last_stop_time = now

    def _handle_translate_llm(self, value, now):
        if self.mode == "hold":
            if value == KEY_DOWN and not self.recording_translate_llm:
                if not self._check_debounce(now):
                    return
                self.last_down_time = now
                print("[ptt] hold: start+translate+llm")
                run_dictee_async("--translate", "--llm", no_animation=True)
                self.recording_translate_llm = True
            elif value == KEY_UP and self.recording_translate_llm:
                for _ in range(50):  # 1s max
                    if os.path.isfile(PIDFILE):
                        break
                    time.sleep(0.02)
                hold_duration = now - self.last_down_time
                if hold_duration < MIN_HOLD_DURATION:
                    print("[ptt] hold: cancel+translate+llm (trop court)")
                    run_dictee_async("--cancel")
                else:
                    print("[ptt] hold: stop+translate+llm")
                    run_dictee_async("--translate", "--llm")
                self.recording_translate_llm = False
                self.last_stop_time = now
        else:  # toggle
            if value == KEY_DOWN:
                if not self._check_debounce(now):
                    return
                self.last_down_time = now
                if not self.recording_translate_llm:
                    print("[ptt] toggle: start+translate+llm")
                    run_dictee_async("--translate", "--llm")
                    self.recording_translate_llm = True
                else:
                    print("[ptt] toggle: stop+translate+llm")
                    run_dictee_async("--translate", "--llm")
                    self.recording_translate_llm = False
                    self.last_stop_time = now


# ─── Backend evdev (grab + uinput) ─────────────────────────────────


def run_evdev(ptt):
    """Main evdev loop: grab keyboards, filter PTT key, re-emit the rest."""
    devices = find_keyboards_evdev()
    if not devices:
        print("[ptt] aucun clavier détecté!", file=sys.stderr)
        sys.exit(1)

    print(f"[ptt] claviers: {[d.path for d in devices]}")

    # Create virtual keyboard to re-emit non-PTT events
    ui = UInput(name="dictee-ptt-passthrough")
    print(f"[ptt] uinput: {ui.device.path}")

    # Grab all keyboards
    for dev in devices:
        try:
            dev.grab()
            print(f"[ptt] grab: {dev.name}")
        except OSError as e:
            print(f"[ptt] grab failed {dev.name}: {e}", file=sys.stderr)

    # Flush buffered events (avoid processing stale KEY_DOWN at startup)
    for dev in devices:
        try:
            while dev.read_one() is not None:
                pass
        except (OSError, BlockingIOError):
            pass

    running = True
    last_rescan = time.monotonic()

    def on_signal(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    print("[ptt] listening (evdev grab)...")

    # Grace period: ignore events for 500ms after startup
    # to avoid processing KEY_DOWN queued in the kernel
    startup_time = time.monotonic()
    STARTUP_GRACE = 0.5

    try:
        while running:
            # Hotplug: periodically rescan
            now_mono = time.monotonic()
            if now_mono - last_rescan > RESCAN_INTERVAL:
                last_rescan = now_mono
                known_paths = {d.path for d in devices}
                for new_dev in find_keyboards_evdev():
                    if new_dev.path not in known_paths:
                        try:
                            new_dev.grab()
                            devices.append(new_dev)
                            print(f"[ptt] hotplug grab: {new_dev.name}")
                        except OSError:
                            new_dev.close()
                    else:
                        new_dev.close()

            # Clean up dead devices
            dead = []
            for dev in devices:
                try:
                    dev.fd  # accès fd pour vérifier
                except Exception:
                    dead.append(dev)
            for dev in dead:
                print(f"[ptt] clavier perdu: {dev.path}")
                devices.remove(dev)

            if not devices:
                time.sleep(1)
                last_rescan = 0
                continue

            # select sur les fd evdev
            try:
                r, _, _ = select.select(devices, [], [], 1.0)
            except (ValueError, OSError):
                # Clean up invalid fds
                bad = []
                for dev in devices:
                    try:
                        select.select([dev], [], [], 0)
                    except (ValueError, OSError):
                        bad.append(dev)
                for dev in bad:
                    print(f"[ptt] clavier perdu: {dev.path}")
                    try:
                        dev.close()
                    except OSError:
                        pass
                    devices.remove(dev)
                continue

            for dev in r:
                try:
                    for event in dev.read():
                        # Grace period: re-emit everything without processing during startup
                        if time.monotonic() - startup_time < STARTUP_GRACE:
                            if event.type == EV_KEY:
                                pass  # ignore stale KEYs
                            else:
                                ui.write_event(event)
                            continue

                        if event.type != EV_KEY:
                            # Re-emit non-keyboard events (SYN, MSC, etc.)
                            ui.write_event(event)
                            continue

                        consumed = ptt.handle_event(event.code, event.value)
                        if not consumed:
                            ui.write_event(event)

                    ui.syn()
                except OSError:
                    # Device disconnected
                    print(f"[ptt] keyboard disconnected: {dev.path}")
                    try:
                        dev.close()
                    except OSError:
                        pass
                    devices.remove(dev)
    finally:
        # Ungrab + close cleanly
        for dev in devices:
            try:
                dev.ungrab()
            except OSError:
                pass
            try:
                dev.close()
            except OSError:
                pass
        ui.close()


# ─── Backend raw (fallback without evdev) ──────────────────────────────


def run_raw(ptt):
    """Main raw /dev/input loop (fallback). PTT key leaks to applications."""
    import struct

    EVENT_SIZE = struct.calcsize("llHHi")
    EVENT_FMT = "llHHi"

    kbd_paths = find_keyboards_raw()
    if not kbd_paths:
        print("[ptt] aucun clavier détecté!", file=sys.stderr)
        sys.exit(1)

    print(f"[ptt] keyboards: {kbd_paths}")
    print(
        "[ptt] WARNING: raw mode — PTT key leaks to applications",
        file=sys.stderr,
    )

    fds = []
    for dev in kbd_paths:
        try:
            fds.append(open(dev, "rb", buffering=0))
        except (PermissionError, FileNotFoundError) as e:
            print(f"[ptt] cannot open {dev}: {e}", file=sys.stderr)

    if not fds:
        print("[ptt] no accessible keyboard! ('input' group required)", file=sys.stderr)
        sys.exit(1)

    # Flush buffered events (avoid processing stale KEY_DOWN at startup)
    for f in fds:
        try:
            os.read(f.fileno(), 65536)
        except (OSError, BlockingIOError):
            pass

    running = True
    last_rescan = time.monotonic()

    def on_signal(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    print("[ptt] listening (raw)...")

    while running:
        # Clean up dead fds
        dead = [f for f in fds if f.closed]
        for f in dead:
            fds.remove(f)

        # Hotplug
        now_mono = time.monotonic()
        if now_mono - last_rescan > RESCAN_INTERVAL:
            last_rescan = now_mono
            existing = {f.name for f in fds}
            for dev in find_keyboards_raw():
                if dev not in existing:
                    try:
                        fds.append(open(dev, "rb", buffering=0))
                        print(f"[ptt] keyboard added: {dev}")
                    except (PermissionError, FileNotFoundError):
                        pass

        if not fds:
            time.sleep(1)
            last_rescan = 0
            continue

        try:
            ready, _, _ = select.select(fds, [], [], 1.0)
        except (ValueError, OSError):
            bad = []
            for f in fds:
                try:
                    select.select([f], [], [], 0)
                except (ValueError, OSError):
                    bad.append(f)
            for f in bad:
                try:
                    f.close()
                except OSError:
                    pass
                fds.remove(f)
            continue

        for f in ready:
            try:
                data = f.read(EVENT_SIZE)
            except OSError:
                try:
                    f.close()
                except OSError:
                    pass
                continue
            if len(data) < EVENT_SIZE:
                continue

            _sec, _usec, ev_type, code, value = struct.unpack(EVENT_FMT, data)
            if ev_type != EV_KEY:
                continue

            ptt.handle_event(code, value)

    for f in fds:
        try:
            f.close()
        except OSError:
            pass


# ─── Main ───────────────────────────────────────────────────────────


def main():
    global DICTEE_BIN

    mode = "toggle"
    key_dictee = 67  # F9
    key_translate = 0  # disabled by default
    mod_translate = ""  # translation modifier (alt, ctrl, shift)
    conf = load_config()

    mode = conf.get("DICTEE_PTT_MODE", mode)
    if "DICTEE_PTT_KEY" in conf:
        key_dictee = int(conf["DICTEE_PTT_KEY"])
    if "DICTEE_PTT_KEY_TRANSLATE" in conf:
        key_translate = int(conf["DICTEE_PTT_KEY_TRANSLATE"])
    mod_translate = conf.get("DICTEE_PTT_MOD_TRANSLATE", mod_translate)
    key_llm = 0
    key_translate_llm = 0
    if "DICTEE_PTT_KEY_LLM" in conf:
        key_llm = int(conf["DICTEE_PTT_KEY_LLM"])
    if "DICTEE_PTT_KEY_TRANSLATE_LLM" in conf:
        key_translate_llm = int(conf["DICTEE_PTT_KEY_TRANSLATE_LLM"])

    for arg in sys.argv[1:]:
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1]
        elif arg.startswith("--key="):
            key_dictee = int(arg.split("=", 1)[1])
        elif arg.startswith("--key-translate="):
            key_translate = int(arg.split("=", 1)[1])
        elif arg.startswith("--mod-translate="):
            mod_translate = arg.split("=", 1)[1]
        elif arg.startswith("--key-llm="):
            key_llm = int(arg.split("=", 1)[1])
        elif arg.startswith("--key-translate-llm="):
            key_translate_llm = int(arg.split("=", 1)[1])
        elif arg == "--help":
            print(__doc__)
            sys.exit(0)

    lock_file = acquire_lock()
    DICTEE_BIN = find_dictee_bin()

    mod_info = f" mod_translate={mod_translate}" if mod_translate else ""
    llm_info = f" key_llm={key_llm}" if key_llm else ""
    trans_llm_info = (
        f" key_translate_llm={key_translate_llm}" if key_translate_llm else ""
    )
    print(
        f"[ptt] mode={mode} key={key_dictee} key_translate={key_translate}{mod_info}{llm_info}{trans_llm_info}"
    )
    print(f"[ptt] dictee={DICTEE_BIN}")

    ptt = PttState(
        mode,
        key_dictee,
        key_translate,
        mod_translate,
        key_llm=key_llm,
        key_translate_llm=key_translate_llm,
    )

    if HAS_EVDEV:
        print("[ptt] backend: evdev (grab + uinput)")
        run_evdev(ptt)
    else:
        print("[ptt] backend: raw (evdev not available)", file=sys.stderr)
        run_raw(ptt)

    try:
        os.unlink(OWN_PIDFILE)
    except OSError:
        pass
    lock_file.close()
    print("[ptt] stopped.")


if __name__ == "__main__":
    main()
