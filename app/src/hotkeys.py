"""Global hotkey handling.

Supports two backends:
1. evdev (Linux) - Works natively on Wayland, reads from input-remapper devices
2. pynput (fallback) - Cross-platform, requires X11/XWayland
"""

import logging
import os
import select
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional

try:
    import evdev
    import evdev.ecodes as ecodes
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False

from pynput import keyboard

_debug_hotkeys = os.environ.get("AI_TYPER_DEBUG_HOTKEYS", "").lower() in ("1", "true", "yes")
logger = logging.getLogger(__name__)
if _debug_hotkeys:
    logging.basicConfig(level=logging.DEBUG)
    logger.setLevel(logging.DEBUG)

DEBOUNCE_INTERVAL_MS = 100
MAX_CALLBACK_THREADS = 2

KEY_MAP = {
    "f1": keyboard.Key.f1, "f2": keyboard.Key.f2, "f3": keyboard.Key.f3,
    "f4": keyboard.Key.f4, "f5": keyboard.Key.f5, "f6": keyboard.Key.f6,
    "f7": keyboard.Key.f7, "f8": keyboard.Key.f8, "f9": keyboard.Key.f9,
    "f10": keyboard.Key.f10, "f11": keyboard.Key.f11, "f12": keyboard.Key.f12,
    "f13": keyboard.Key.f13, "f14": keyboard.Key.f14, "f15": keyboard.Key.f15,
    "f16": keyboard.Key.f16, "f17": keyboard.Key.f17, "f18": keyboard.Key.f18,
    "f19": keyboard.Key.f19, "f20": keyboard.Key.f20,
    "ctrl": keyboard.Key.ctrl, "alt": keyboard.Key.alt,
    "shift": keyboard.Key.shift, "super": keyboard.Key.cmd,
    "space": keyboard.Key.space, "enter": keyboard.Key.enter,
}

KEY_DISPLAY_MAP = {v: k.upper() for k, v in KEY_MAP.items()}

EVDEV_KEY_MAP = {
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64,
    "f7": 65, "f8": 66, "f9": 67, "f10": 68, "f11": 87, "f12": 88,
    "f13": 183, "f14": 184, "f15": 185, "f16": 186, "f17": 187,
    "f18": 188, "f19": 189, "f20": 190, "f21": 191, "f22": 192,
    "f23": 193, "f24": 194,
    "ctrl": 29, "alt": 56, "shift": 42, "super": 125,
    "space": 57, "enter": 28,
}

EVDEV_KEY_DISPLAY_MAP = {v: k.upper() for k, v in EVDEV_KEY_MAP.items()}


def parse_hotkey(hotkey_str: str) -> Optional[set]:
    """Parse a hotkey string like 'f15' into a set of keys."""
    if not hotkey_str or not hotkey_str.strip():
        return None
    parts = [p.strip().lower() for p in hotkey_str.split("+")]
    keys = set()
    for part in parts:
        if part in KEY_MAP:
            keys.add(KEY_MAP[part])
        elif len(part) == 1:
            keys.add(keyboard.KeyCode.from_char(part))
        else:
            return None
    return keys if keys else None


def key_to_string(key) -> str:
    """Convert a pynput key to a display string."""
    if key in KEY_DISPLAY_MAP:
        return KEY_DISPLAY_MAP[key]
    elif hasattr(key, "char") and key.char:
        return key.char.upper()
    elif hasattr(key, "vk") and key.vk:
        vk = key.vk
        if 124 <= vk <= 135:
            return f"F{vk - 111}"
        if 65482 <= vk <= 65493:
            return f"F{vk - 65469}"
        return f"vk:{vk}"
    return str(key)


class GlobalHotkeyListener:
    """Manages global hotkey listening via pynput."""

    def __init__(self):
        self.hotkeys: Dict[str, set] = {}
        self.callbacks: Dict[str, Callable] = {}
        self.release_callbacks: Dict[str, Callable] = {}
        self.pressed_keys: set = set()
        self.active_hotkeys: set = set()
        self.listener: Optional[keyboard.Listener] = None
        self._lock = threading.Lock()
        self._last_trigger_time: Dict[str, float] = {}
        self._executor = ThreadPoolExecutor(max_workers=MAX_CALLBACK_THREADS, thread_name_prefix="hotkey")

    def register(self, name: str, hotkey_str: str, callback: Callable,
                 release_callback: Optional[Callable] = None) -> bool:
        keys = parse_hotkey(hotkey_str)
        if keys is None:
            with self._lock:
                self.hotkeys.pop(name, None)
                self.callbacks.pop(name, None)
                self.release_callbacks.pop(name, None)
            return False
        with self._lock:
            self.hotkeys[name] = keys
            self.callbacks[name] = callback
            if release_callback:
                self.release_callbacks[name] = release_callback
            else:
                self.release_callbacks.pop(name, None)
        return True

    def unregister(self, name: str):
        with self._lock:
            self.hotkeys.pop(name, None)
            self.callbacks.pop(name, None)
            self.release_callbacks.pop(name, None)
            self.active_hotkeys.discard(name)

    def start(self):
        if self.listener is not None:
            return
        self.listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self.listener.start()

    def stop(self):
        if self.listener is not None:
            self.listener.stop()
            self.listener = None
        self.pressed_keys.clear()
        self.active_hotkeys.clear()
        self._executor.shutdown(wait=False)

    def _should_debounce(self, name: str) -> bool:
        now = time.time() * 1000
        last_time = self._last_trigger_time.get(name, 0)
        if now - last_time < DEBOUNCE_INTERVAL_MS:
            return True
        self._last_trigger_time[name] = now
        return False

    def _on_press(self, key):
        normalized = self._normalize_key(key)
        self.pressed_keys.add(normalized)
        with self._lock:
            for name, hotkey_keys in self.hotkeys.items():
                if name not in self.active_hotkeys:
                    if hotkey_keys and hotkey_keys.issubset(self.pressed_keys):
                        self.active_hotkeys.add(name)
                        callback = self.callbacks.get(name)
                        if callback and not self._should_debounce(name):
                            try:
                                self._executor.submit(callback)
                            except RuntimeError:
                                pass

    def _on_release(self, key):
        normalized = self._normalize_key(key)
        self.pressed_keys.discard(normalized)
        with self._lock:
            released = []
            for name in list(self.active_hotkeys):
                hotkey_keys = self.hotkeys.get(name, set())
                if hotkey_keys and not hotkey_keys.issubset(self.pressed_keys):
                    released.append(name)
            for name in released:
                self.active_hotkeys.discard(name)
                release_callback = self.release_callbacks.get(name)
                if release_callback:
                    try:
                        self._executor.submit(release_callback)
                    except RuntimeError:
                        pass

    def _normalize_key(self, key):
        if hasattr(key, "vk") and key.vk is not None:
            vk = key.vk
            if vk in (65505, 65506):
                return keyboard.Key.shift
            if vk in (65507, 65508):
                return keyboard.Key.ctrl
            if vk in (65513, 65514):
                return keyboard.Key.alt
            if 124 <= vk <= 135:
                key_name = f"f{vk - 111}"
                if key_name in KEY_MAP:
                    return KEY_MAP[key_name]
            if 65482 <= vk <= 65493:
                key_name = f"f{vk - 65469}"
                if key_name in KEY_MAP:
                    return KEY_MAP[key_name]
        return key


class EvdevHotkeyListener:
    """Evdev-based global hotkey listener for Linux/Wayland."""

    def __init__(self):
        self.hotkeys: Dict[str, set] = {}
        self.callbacks: Dict[str, Callable] = {}
        self.release_callbacks: Dict[str, Callable] = {}
        self.pressed_keys: set = set()
        self.active_hotkeys: set = set()
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._devices: List = []
        self._last_trigger_time: Dict[str, float] = {}
        self._executor = ThreadPoolExecutor(max_workers=MAX_CALLBACK_THREADS, thread_name_prefix="evdev-hotkey")

    def _find_devices(self) -> List:
        if not EVDEV_AVAILABLE:
            return []
        devices = []
        try:
            for path in evdev.list_devices():
                try:
                    device = evdev.InputDevice(path)
                    name_lower = device.name.lower()
                    if "input-remapper" in name_lower and "keyboard" in name_lower:
                        devices.append(device)
                except (PermissionError, OSError):
                    continue
        except Exception:
            pass
        return devices

    def register(self, name: str, hotkey_str: str, callback: Callable,
                 release_callback: Optional[Callable] = None) -> bool:
        if not hotkey_str or not hotkey_str.strip():
            with self._lock:
                self.hotkeys.pop(name, None)
                self.callbacks.pop(name, None)
                self.release_callbacks.pop(name, None)
            return False
        parts = [p.strip().lower() for p in hotkey_str.split("+")]
        key_codes = set()
        for part in parts:
            if part in EVDEV_KEY_MAP:
                key_codes.add(EVDEV_KEY_MAP[part])
            else:
                return False
        if not key_codes:
            return False
        with self._lock:
            self.hotkeys[name] = key_codes
            self.callbacks[name] = callback
            if release_callback:
                self.release_callbacks[name] = release_callback
            else:
                self.release_callbacks.pop(name, None)
        return True

    def unregister(self, name: str):
        with self._lock:
            self.hotkeys.pop(name, None)
            self.callbacks.pop(name, None)
            self.release_callbacks.pop(name, None)
            self.active_hotkeys.discard(name)

    def start(self):
        if self._running:
            return
        self._devices = self._find_devices()
        if not self._devices:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        for device in self._devices:
            try:
                device.close()
            except Exception:
                pass
        self._devices = []
        self.pressed_keys.clear()
        self.active_hotkeys.clear()
        self._executor.shutdown(wait=False)

    def _should_debounce(self, name: str) -> bool:
        now = time.time() * 1000
        last_time = self._last_trigger_time.get(name, 0)
        if now - last_time < DEBOUNCE_INTERVAL_MS:
            return True
        self._last_trigger_time[name] = now
        return False

    def _listen_loop(self):
        while self._running:
            try:
                r, w, x = select.select(self._devices, [], [], 0.1)
                for device in r:
                    try:
                        for event in device.read():
                            if event.type == ecodes.EV_KEY:
                                self._handle_key_event(event.code, event.value)
                    except (OSError, IOError):
                        continue
            except Exception:
                time.sleep(0.1)

    def _handle_key_event(self, code: int, value: int):
        if value == 1:
            self.pressed_keys.add(code)
            self._check_hotkeys_press()
        elif value == 0:
            self.pressed_keys.discard(code)
            self._check_hotkeys_release()

    def _check_hotkeys_press(self):
        with self._lock:
            for name, hotkey_codes in self.hotkeys.items():
                if name not in self.active_hotkeys:
                    if hotkey_codes and hotkey_codes.issubset(self.pressed_keys):
                        self.active_hotkeys.add(name)
                        callback = self.callbacks.get(name)
                        if callback and not self._should_debounce(name):
                            try:
                                self._executor.submit(callback)
                            except RuntimeError:
                                pass

    def _check_hotkeys_release(self):
        with self._lock:
            released = []
            for name in list(self.active_hotkeys):
                hotkey_codes = self.hotkeys.get(name, set())
                if hotkey_codes and not hotkey_codes.issubset(self.pressed_keys):
                    released.append(name)
            for name in released:
                self.active_hotkeys.discard(name)
                release_callback = self.release_callbacks.get(name)
                if release_callback:
                    try:
                        self._executor.submit(release_callback)
                    except RuntimeError:
                        pass


def create_hotkey_listener():
    """Create the best available hotkey listener for this platform."""
    if EVDEV_AVAILABLE:
        listener = EvdevHotkeyListener()
        devices = listener._find_devices()
        if devices:
            for d in devices:
                try:
                    d.close()
                except Exception:
                    pass
            return EvdevHotkeyListener()

    return GlobalHotkeyListener()
