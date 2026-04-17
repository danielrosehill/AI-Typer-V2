# Keyboard Emulation (Type-at-cursor)

## What the app actually does

When "Type at cursor" is enabled, the app does **not** type the transcription character-by-character. Instead:

1. Copy the transcribed text to the clipboard (`wl-copy`, falling back to `xclip`).
2. Synthesize **Ctrl+Shift+V** via `ydotool` to paste at the current cursor position.
3. Restore the previous clipboard contents ~300 ms later (best-effort).

This clipboard-paste approach is instantaneous for any length of text and avoids per-character timing issues that plague direct key-synthesis on Wayland.

## Why Ctrl+Shift+V (not Ctrl+V)

Terminals — Konsole, GNOME Terminal, Alacritty, VS Code's integrated terminal, the Claude Code CLI in a terminal — **do not treat Ctrl+V as paste**. In a terminal, Ctrl+V is reserved as the readline/`stty` `lnext` function (quote-the-next-keystroke).

Ctrl+Shift+V is the universal paste shortcut on Linux: it works in Konsole and all terminals, in Kate and other KDE editors, in browsers, and in virtually every GUI app. Kate also accepts Ctrl+V, so switching to Ctrl+Shift+V loses nothing.

This is the root cause of the earlier "works in Kate but not in terminal" bug.

## Why `ydotool` on KDE Plasma Wayland

Wayland intentionally sandboxes keystroke injection (no global `XTestFakeKeyEvent` equivalent). Available options on Ubuntu 25.10 + KDE Plasma + Wayland:

| Tool | Mechanism | Works on KWin Wayland? | Notes |
|---|---|---|---|
| `ydotool` | `/dev/uinput` (kernel virtual input device) | **Yes, reliably** | Requires the `ydotoold` daemon and access to `/dev/uinput`. Session-agnostic. |
| `wtype` | Wayland `virtual_keyboard_v1` protocol | Partially — KWin support has been unreliable across versions | Would be the "pure Wayland" choice if it worked consistently. |
| `xdotool` | X11 `XTest` | No | X11-only. Won't work under Wayland sessions. |
| Direct key-synthesis (typing each character) | Any of the above | Works but slow for long text | Also breaks on dead keys, IME, non-ASCII. |

**Decision**: `ydotool` with clipboard + Ctrl+Shift+V is the most reliable path on KDE Plasma Wayland today. If KWin's `virtual_keyboard_v1` support stabilizes in a future Plasma release, switching to `wtype` for pure-Wayland injection becomes an option.

## Runtime requirements

- `ydotool` and `ydotoold` installed (`apt install ydotool`)
- `ydotoold` running (system service or user service)
- User in the `input` group, OR `/dev/uinput` permissions granted to the user
- `wl-copy` (Wayland) or `xclip` (X11 fallback) for clipboard access

## Key-code details

`ydotool` receives raw Linux input-event key codes rather than symbolic names for modified shortcuts. The app sends:

```
ydotool key 29:1 42:1 47:1 47:0 42:0 29:0
           ^    ^    ^    ^    ^    ^
           |    |    |    |    |    └─ release LeftCtrl (29)
           |    |    |    |    └───── release LeftShift (42)
           |    |    |    └────────── release V (47)
           |    |    └─────────────── press V (47)
           |    └──────────────────── press LeftShift (42)
           └───────────────────────── press LeftCtrl (29)
```

Codes are from `linux/input-event-codes.h`.
