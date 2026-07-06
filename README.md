# S2T — Local Speech-to-Text Dictation

A **Speech-to-Text** dictation tool for Windows that runs **100% on local AI**. Hold a hotkey in any application, speak, release — clean, punctuated text is pasted at your cursor and left on the clipboard.

Two-stage pipeline, all offline:

1. **Speech → text**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) running locally on CPU (int8).
2. **Text → clean text**: your **LM Studio** server (`google/gemma-4-e4b` by default) adds punctuation, removes filler words ("um", "uh", "you know") and applies your custom dictionary. If LM Studio is offline, the raw Whisper transcript is used instead — dictation never breaks.

> **New here / just want to run it?** See **[GETTING_STARTED.md](GETTING_STARTED.md)** — a plain-language, step-by-step runbook. This README is the shorter technical overview.

## Setup

```
pip install -r requirements.txt
python main.py
```

- First run downloads the Whisper model (~460 MB for `small`) from Hugging Face; fully offline afterwards.
- If LM Studio's server isn't running, the app starts it via `lms server start` and warms the model up (the model loads on the first request, so give it a moment after launch).
- A **green** tray icon appears when running (gray when dictation is turned off). It turns **red** while recording and **orange** while transcribing.

## Usage

| Action | Default key |
|---|---|
| Hold-to-talk: record while held, insert on release | hold **Right Ctrl** |
| Hands-free toggle: press to start, press again to stop & insert | **F8** |

While recording, a small pill appears at the bottom of the screen. After release, the cleaned text is:

- **pasted at the cursor** of whatever app has focus (simulated Ctrl+V), and
- **left on the clipboard** so you can paste it again anywhere.

Every dictation is logged to `history.jsonl` (timestamp, raw transcript, cleaned text).

## Settings window

Right-click the tray icon → **Settings…** opens a small window that shows at a glance whether
dictation is **ON** (green) or **OFF** (gray), with a one-click toggle. From there you can:

- **Pick the microphone** from a dropdown, with a live level meter to confirm it's hearing you.
- **Choose the LM Studio model** from a dropdown; selecting one loads it into LM Studio right away.
- **Change the hotkeys**: click *Change…* next to *Hold to talk* or *Hands-free toggle*, then press
  the new key. The toggle accepts combos (e.g. Ctrl+Alt+Space); the hold key is a single key.
  Esc cancels.

The tray menu also has **Microphone** and **Model** submenus for quick switching without opening
the window. All choices are written back to `config.json`.

## Configuration — `config.json`

Created with defaults on first run. Edit it (tray → *Open config*), then tray → *Reload config*.
Microphone and model can also be set from the **Settings window** above.

| Key | Default | Notes |
|---|---|---|
| `mic_device` | `null` | Input device index or name substring; `null` = system default |
| `whisper.model` | `"small"` | `tiny`/`base`/`small`/`medium`/`large-v3`/`distil-large-v3`/`large-v3-turbo`. Bigger = more accurate, slower on CPU |
| `whisper.language` | `null` | `null` auto-detects; set e.g. `"en"` to lock and speed up |
| `hotkeys.hold` / `hotkeys.toggle` | `"right ctrl"` / `"f8"` | Any [keyboard](https://github.com/boppreh/keyboard) key name, e.g. `"ctrl+alt+space"` for toggle |
| `insert_mode` | `"paste"` | `paste` (Ctrl+V, most reliable) · `type` (simulated keystrokes, for apps that block paste) · `clipboard_only` |
| `restore_clipboard` | `false` | `true` puts your previous clipboard content back after pasting |
| `lmstudio.enabled` | `true` | `false` = raw Whisper output only |
| `lmstudio.model` | `"google/gemma-4-e4b"` | Any model available in LM Studio (`lms ls`); the app loads it at startup if needed |
| `lmstudio.gpu_offload` | `"off"` | Passed to `lms load --gpu`: `"off"`, `"max"`, or `0`–`1`. Keep `"off"` if the model is bigger than your VRAM — partial offload can make generation 30× slower |
| `dictionary` | `{}` | Vocabulary fixes, e.g. `{"speech to text": "Speech-to-Text", "gemma": "Gemma"}` |
| `sound_cues` | `true` | Beep on record start/stop |
| `max_record_seconds` | `300` | Hard cap per dictation |

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```

The suite is offline and hardware-free — the microphone, LM Studio, the global keyboard
hook and the real `config.json`/`history.jsonl` are all mocked or redirected to temp files,
so it's safe to run anywhere. `python -m mypy` type-checks `main.py` and the `s2t` package.

## Troubleshooting

- **Nothing happens on the hotkey** — another app may grab the key; change `hotkeys.hold` in config. Some elevated (admin) windows ignore keystrokes from non-elevated apps: run `python main.py` from an admin terminal to dictate into admin windows.
- **No text inserted but clipboard has it** — the target app may block simulated Ctrl+V; set `insert_mode` to `"type"`.
- **Slow transcription** — use a smaller `whisper.model` (`base`), or set `whisper.language` to your language to skip detection.
- **"LM Studio cleanup failed" in the log** — check `lms server status` and that the model in `lmstudio.model` exists (`lms ls`). Dictation still works with raw transcripts meanwhile.
- **Cleanup times out / raw text inserted** — hybrid reasoning models (Gemma 4, Qwen3) may "think" for minutes before answering. The built-in prompt sends `/no_think` to suppress this; if you switch to a different model and see timeouts, make sure it either isn't a reasoning model or honors `/no_think`.
- **Wrong microphone** — set `mic_device` to a name substring from the log/`python -c "import sounddevice; print(sounddevice.query_devices())"`.
- **Logs** — `s2t.log` next to `main.py`.
