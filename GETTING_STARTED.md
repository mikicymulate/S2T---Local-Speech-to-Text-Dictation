# S2T — Getting Started (Run It Yourself)

This is the walk-through-it-cold guide. Follow it top to bottom the first time; after that,
the **Daily use** section at the top is all you need.

---

## TL;DR — the 10-second version

1. Make sure **LM Studio** is installed and open (it can be minimized).
2. Double-click **`run.bat`** in `C:\dev\AI\S2T`.
3. Wait ~15 seconds for the tray icon to turn green.
4. Click into any text box, **hold Right Ctrl**, speak, **release**. Your words appear.
5. To quit: right-click the tray icon (bottom-right of the taskbar) → **Quit**.

Everything below is detail for when something doesn't go like that.

---

## What this app is

Press a hotkey anywhere in Windows, talk, and your speech is typed into whatever text box
you're in — punctuated and cleaned up, with "um"/"uh"/"you know" removed. It runs **entirely
on your own PC**; nothing is sent to the cloud.

It works in two stages, both local:

1. **Your voice → rough text** using a Whisper speech model (runs inside the app).
2. **Rough text → clean text** using **LM Studio** running the `google/gemma-4-e4b` model.

If LM Studio isn't running, you still get the rough text — dictation never fully breaks.

---

## First-time setup (do this once)

You've already done most of this, but here's the full list in case you're on a fresh machine.

### 1. Requirements
- **Windows 10/11**
- **Python 3.13** (check: open PowerShell, run `python --version`)
- **LM Studio** desktop app installed, with the **`lms` command-line tool** available
  (check: `lms version`). If `lms` isn't found, open LM Studio once and enable its CLI,
  or reinstall.
- The **`google/gemma-4-e4b`** model downloaded inside LM Studio (check: `lms ls`).
  If it's missing: `lms get google/gemma-4-e4b`.

### 2. Install the Python packages
Open PowerShell in the project folder and run:

```powershell
cd C:\dev\AI\S2T
pip install -r requirements.txt
```

This is already done on your machine. You only redo it if you move to a new PC or the
packages get removed.

### 3. First run downloads the speech model
The very first time you run the app, it downloads the Whisper `small` model (~460 MB) from
the internet. This happens once; afterwards it works fully offline. Just give the first
launch an extra minute.

---

## Daily use

### Starting it
- **Easiest:** double-click **`run.bat`**.
- **Or from PowerShell:**
  ```powershell
  cd C:\dev\AI\S2T
  python main.py
  ```

A small console window opens showing status messages. Leave it open — closing it stops the
app. Within ~15 seconds you'll see lines like:

```
S2T running. Hold 'right ctrl' to dictate, press 'f8' to toggle hands-free.
...
LM Studio model ready
```

A **tray icon** (a little microphone) appears at the bottom-right of your taskbar. Its color
tells you the state:

| Color | Meaning |
|---|---|
| **Green** | On — ready to dictate |
| **Red** | Recording your voice right now |
| **Orange** | Transcribing / cleaning up |
| **Gray** | Dictation turned off |

> Wait for the icon to settle on **green** before your first dictation — that means both AI
> models finished loading. Dictating before then still works but the first one will be slow.

### Dictating — two ways

**Hold-to-talk (default: Right Ctrl)** — best for short bursts:
1. Click into any text box (browser, Notepad, chat, email — anything).
2. **Hold down Right Ctrl.** You'll hear a beep and the tray goes red.
3. Speak.
4. **Release Right Ctrl.** A lower beep plays, the tray goes orange, and a second or two
   later your cleaned-up text is typed in and also copied to the clipboard.

**Hands-free toggle (default: F8)** — best for long dictation:
1. Click into a text box.
2. **Press F8 once** to start (beep, red tray). You can let go — it keeps recording.
3. Talk as long as you want.
4. **Press F8 again** to stop and insert.

### Stopping it
- Right-click the tray microphone icon → **Quit**, **or**
- Close the console window, **or**
- Press `Ctrl+C` in the console window.

---

## The tray menu

Right-click the tray icon for:

- **Enabled** — checkbox to pause/resume dictation without quitting (hotkeys stop working
  while unchecked).
- **Open config** — opens `config.json` in your default editor (see settings below).
- **Reload config** — applies changes you made to `config.json` without restarting.
- **Open history** — opens `history.jsonl`, a log of everything you've dictated.
- **Quit** — exits cleanly.

---

## Changing settings — `config.json`

Right-click tray → **Open config**, edit, save, then right-click tray → **Reload config**.
The file lives at `C:\dev\AI\S2T\config.json`. Here's what each setting does:

| Setting | Default | What it does |
|---|---|---|
| `mic_device` | `null` | Which microphone to use. `null` = Windows default. To pick a specific one, put part of its name in quotes, e.g. `"Realtek"`. (List your mics with the command in Troubleshooting.) |
| `whisper.model` | `"small"` | Speech accuracy vs. speed. Options, small→large: `tiny`, `base`, `small`, `medium`, `large-v3`. Bigger = more accurate but slower. `small` is a good balance. |
| `whisper.language` | `null` | `null` auto-detects the language. Set to `"en"` (or your language) to lock it — slightly faster and more accurate if you always speak one language. |
| `hotkeys.hold` | `"right ctrl"` | The hold-to-talk key. Examples: `"right alt"`, `"ctrl+space"`. |
| `hotkeys.toggle` | `"f8"` | The hands-free start/stop key. |
| `insert_mode` | `"paste"` | How text gets in. `"paste"` = simulate Ctrl+V (fast, reliable). `"type"` = type it out key-by-key (use if an app blocks paste). `"clipboard_only"` = just copy, you paste yourself. |
| `restore_clipboard` | `false` | `false` leaves the dictated text on your clipboard. `true` puts back whatever you had copied before. |
| `sound_cues` | `true` | The start/stop beeps. Set `false` for silence. |
| `dictionary` | `{}` | Fix words the AI mishears. Example below. |
| `lmstudio.enabled` | `true` | `false` skips the cleanup step (you get raw Whisper text, faster but with fillers/no punctuation). |
| `lmstudio.model` | `"google/gemma-4-e4b"` | Which LM Studio model does the cleanup. |
| `lmstudio.gpu_offload` | `"off"` | Leave `"off"` on this laptop — the GPU is too small for this model and turning it on makes things much slower. |

### Custom dictionary example
If it keeps writing "speech to text" when you say "Speech-to-Text", or your name wrong, teach it:

```json
"dictionary": {
  "speech to text": "Speech-to-Text",
  "michael matricks": "Michael Matrix"
}
```

Left side = roughly what it hears (lowercase is fine), right side = what you want written.

---

## Troubleshooting

**The tray icon never appears / console shows an error and closes.**
Run it from PowerShell so you can read the error:
```powershell
cd C:\dev\AI\S2T
python main.py
```
Also check the log file `C:\dev\AI\S2T\s2t.log`.

**Nothing happens when I hold Right Ctrl.**
- Make sure the tray icon is green (ready) and **Enabled** is checked in the tray menu.
- Another program may be using Right Ctrl — change `hotkeys.hold` in config to something like
  `"right alt"`, then Reload config.
- If you're dictating into a program you ran **as Administrator**, keystrokes from S2T get
  blocked. Fix: run S2T as Administrator too (right-click `run.bat` → Run as administrator).

**Text is on my clipboard but doesn't get typed in.**
Some apps block simulated paste. Open config, set `insert_mode` to `"type"`, Reload config.

**The cleanup is slow, or my text comes out with fillers still in it.**
That means the LM Studio step timed out and it fell back to raw text. Check:
- LM Studio is open and its server is on: run `lms server status` (should say running).
- The model is available: `lms ls` should list `google/gemma-4-e4b`.
- The app auto-starts the server and loads the model, but the *first* cleanup after launch
  can take a few extra seconds while the model loads. Wait for the tray to go green.

**It's using the wrong microphone.**
List your microphones:
```powershell
python -c "import sounddevice; print(sounddevice.query_devices())"
```
Find the one you want, put part of its name (in quotes) into `mic_device` in config, Reload.

**Transcription is too slow on my machine.**
Set `whisper.model` to `"base"` (or `"tiny"`) in config, and set `whisper.language` to your
language (e.g. `"en"`). Reload config.

---

## Where things live

| File | What it is |
|---|---|
| `run.bat` | Double-click to start the app |
| `main.py` | The program entry point (`python main.py`) |
| `config.json` | Your settings |
| `history.jsonl` | Log of every dictation (raw + cleaned) |
| `s2t.log` | Technical log for troubleshooting |
| `s2t\` | The app's source code |
| `README.md` | Shorter technical overview |

---

## Quick reference card

```
START      double-click run.bat  (or: python main.py)
DICTATE    hold Right Ctrl, speak, release      (short)
           press F8, speak, press F8 again      (long/hands-free)
PAUSE      tray menu → uncheck Enabled
SETTINGS   tray menu → Open config → edit → Reload config
QUIT       tray menu → Quit
```
