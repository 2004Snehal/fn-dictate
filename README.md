# fn-dictate

Hold the **fn** key, speak, let go. Your words get typed wherever the cursor is: Slack, Notes, VS Code, a browser, anywhere.

Everything runs on your Mac. The speech model is [IBM Granite Speech 4.1 2B](https://huggingface.co/ibm-granite/granite-speech-4.1-2b-GGUF) (Apache 2.0), served by [Ollama](https://ollama.com). No audio leaves your computer, and there are no API keys or subscriptions.

- **Speed:** about 1 s to transcribe 5 s of speech on an Apple Silicon MacBook Air.
- **RAM:** about 2.4–3.2 GB while the model is loaded. Ollama frees it after 30 min of no use.
- **Disk:** about 3.1 GB for the model.

## Requirements

- macOS on Apple Silicon (M1 or newer). Intel Macs work but are slower.
- 8 GB RAM minimum; 12 GB or more is comfortable.
- [Homebrew](https://brew.sh), Python 3.9+, and Ollama (tested with Ollama 0.35.0).

## Install

```bash
brew install ollama python   # skip what you already have
open -a Ollama               # or: brew services start ollama

git clone https://github.com/2004Snehal/fn-dictate.git
cd fn-dictate
./install.sh
```

`install.sh` creates a `.venv`, installs the Python packages, and downloads the model (3.1 GB, once). If the download drops, the script retries and resumes. You can also run it again.

## One-time macOS setup

1. **Stop fn from opening the emoji picker.** Go to System Settings > Keyboard and set **Press 🌐 key to** to **Do Nothing**. If the Dictation shortcut there uses fn, change it too.
2. **Grant permissions to your terminal app** (Terminal, iTerm, Warp, …) in System Settings > Privacy & Security:
   - **Microphone**: to record your voice.
   - **Input Monitoring**: to see when fn is pressed.
   - **Accessibility**: to type the text (it presses Cmd+V for you).

   macOS usually asks the first time you run the app. After granting, **quit and reopen the terminal**.

## Use

```bash
./run.sh --test     # record 5 s, print what it heard (checks mic + model)
./run.sh            # start dictating; keep this window open
```

Then, in any app: **hold fn**, hear a *tink*, speak, **release fn**, hear a *pop*. The text appears a second later.

- Tapping fn quickly (under 0.3 s) is ignored.
- Using fn with another key (fn+F1, fn+arrow) cancels the recording, so normal shortcuts still work.
- Long dictations are split into 30 s pieces automatically.
- Your clipboard is restored after each paste.

Press `Ctrl+C` in the terminal to quit. Or have it start on its own at every login: see the next section.

### Options

```
./run.sh --no-sound          # no tink/pop sounds
./run.sh --dry-run           # print transcripts, don't type them
./run.sh --keep-alive 1h     # keep the model in RAM longer (-1 = forever)
./run.sh --model <name>      # use another Ollama audio model
./run.sh --url http://host:11434   # use Ollama on another machine
```

## Start automatically at login

```bash
./autostart.sh on        # start now and at every login, in the background (no terminal needed)
./autostart.sh status    # is it running?
./autostart.sh logs      # see transcripts and errors
./autostart.sh restart   # after changing permissions
./autostart.sh off       # stop and remove
```

The background process is **Python**, not your terminal, so macOS asks for Microphone, Input Monitoring and Accessibility again, this time for Python. If Python does not show up in Input Monitoring or Accessibility, click **+** and add the `Python.app` path that `./autostart.sh on` prints. Then run `./autostart.sh restart`.

> **Security note:** these permissions are granted to the Homebrew Python app as a whole. Any other script run with that same Python also gets keyboard and screen-control access. If that worries you, skip autostart and use `./run.sh` in a terminal. A Homebrew Python upgrade can also reset the permissions; grant them again if dictation stops working.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Cannot listen to the keyboard` | Give your terminal **Input Monitoring** and **Accessibility**, then quit and reopen it. |
| Nothing gets typed but transcripts print | Your terminal is missing the **Accessibility** permission. |
| `(silence, skipped)` every time | The terminal has no **Microphone** permission, or the wrong input device is selected in System Settings > Sound > Input. |
| Emoji picker pops up | Set **Press 🌐 key to: Do Nothing** (see setup step 1). |
| `Cannot reach Ollama` | Start it: `open -a Ollama`. |
| `Model not found` | `ollama pull hf.co/ibm-granite/granite-speech-4.1-2b-GGUF:Q8_0` |
| First word gets cut off | Wait for the *tink* before you start speaking. |

## How it works

1. A listen-only macOS event tap watches the fn key (keycode 63).
2. While fn is held, the microphone records 16 kHz mono audio.
3. On release, the audio is sent as a WAV file to Ollama's `/api/chat` with Granite Speech.
4. The text goes on the clipboard and the app sends Cmd+V. Then the old clipboard comes back.

It is all in one file, `fn_dictate.py`.

## License

MIT for this code. The Granite Speech model is Apache 2.0 by IBM.
