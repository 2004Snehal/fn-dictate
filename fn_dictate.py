#!/usr/bin/env python3
"""fn-dictate: hold the fn key, speak, release -> the text is typed where your cursor is.

Speech-to-text runs 100% locally with IBM Granite Speech 4.1 2B served by Ollama.
macOS only.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
import wave

import numpy as np
import sounddevice as sd
import Quartz
from AppKit import NSPasteboard, NSPasteboardTypeString, NSSound

DEFAULT_MODEL = "hf.co/ibm-granite/granite-speech-4.1-2b-GGUF:Q8_0"
DEFAULT_URL = "http://127.0.0.1:11434"
PROMPT = "can you transcribe the speech into a written format?"

SAMPLE_RATE = 16000
FN_KEYCODE = 63        # kVK_Function
V_KEYCODE = 9          # kVK_ANSI_V, used for Cmd+V
MAX_CHUNK_SEC = 30     # Granite context is 4096 tokens; keep chunks short
MIN_HOLD_SEC = 0.3     # ignore accidental taps of fn
SILENCE_RMS = 0.003    # skip recordings quieter than this


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def play(name: str, enabled: bool) -> None:
    if enabled:
        sound = NSSound.soundNamed_(name)
        if sound is not None:
            sound.play()


# --------------------------------------------------------------------------- Ollama

class Ollama:
    def __init__(self, url: str, model: str, keep_alive: str):
        self.url = url.rstrip("/")
        self.model = model
        self.keep_alive = keep_alive

    def _request(self, path: str, body: dict | None = None, timeout: float = 120):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def check(self) -> None:
        try:
            tags = self._request("/api/tags", timeout=5)
        except (urllib.error.URLError, OSError):
            sys.exit(f"Cannot reach Ollama at {self.url}. Start it with: open -a Ollama  (or: ollama serve)")
        names = {m["name"] for m in tags.get("models", [])}
        wanted = self.model if ":" in self.model else self.model + ":latest"
        if wanted not in names:
            sys.exit(f"Model not found in Ollama. Pull it with:\n  ollama pull {self.model}")

    def warm(self) -> None:
        """Load the model in the background so the first transcription is fast."""
        def _go():
            try:
                self._request("/api/generate", {"model": self.model, "keep_alive": self.keep_alive})
            except Exception:
                pass
        threading.Thread(target=_go, daemon=True).start()

    def _transcribe_chunk(self, audio: np.ndarray) -> str:
        body = {
            "model": self.model,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0},
            "messages": [{"role": "user", "content": PROMPT, "images": [wav_b64(audio)]}],
        }
        return self._request("/api/chat", body)["message"]["content"].strip()

    def transcribe(self, audio: np.ndarray) -> str:
        step = SAMPLE_RATE * MAX_CHUNK_SEC
        parts = [self._transcribe_chunk(audio[i:i + step]) for i in range(0, len(audio), step)]
        return " ".join(p for p in parts if p)


def wav_b64(audio: np.ndarray) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    return base64.b64encode(buf.getvalue()).decode()


def clean(text: str) -> str:
    text = " ".join(text.split())
    if not text:
        return ""
    return text[0].upper() + text[1:] + " "


# --------------------------------------------------------------------------- audio

class Recorder:
    def __init__(self):
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None

    def _callback(self, indata, frames, t, status):
        with self._lock:
            self._frames.append(indata[:, 0].copy())

    def start(self) -> None:
        with self._lock:
            self._frames = []
        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                      callback=self._callback)
        self._stream.start()

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            frames, self._frames = self._frames, []
        return np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)


# --------------------------------------------------------------------------- typing

def paste(text: str) -> None:
    """Put text on the clipboard, press Cmd+V, then restore the old clipboard."""
    pb = NSPasteboard.generalPasteboard()
    old = pb.stringForType_(NSPasteboardTypeString)
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)

    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateCombinedSessionState)
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(src, V_KEYCODE, down)
        Quartz.CGEventSetFlags(ev, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGAnnotatedSessionEventTap, ev)

    time.sleep(0.3)  # give the target app time to read the clipboard
    if old is not None:
        pb.clearContents()
        pb.setString_forType_(old, NSPasteboardTypeString)


# --------------------------------------------------------------------------- fn key

class FnListener:
    """Listen-only event tap that reports fn down / up / cancel (fn+another key)."""

    def __init__(self, events: queue.Queue):
        self.events = events
        self.fn_down = False
        self.tap = None

    def _callback(self, proxy, etype, event, refcon):
        if etype in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
            Quartz.CGEventTapEnable(self.tap, True)
        elif etype == Quartz.kCGEventFlagsChanged:
            keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
            if keycode == FN_KEYCODE:
                down = bool(Quartz.CGEventGetFlags(event) & Quartz.kCGEventFlagMaskSecondaryFn)
                if down != self.fn_down:
                    self.fn_down = down
                    self.events.put("down" if down else "up")
        elif etype == Quartz.kCGEventKeyDown and self.fn_down:
            self.events.put("cancel")  # fn used as a modifier (fn+F1, fn+arrow, ...)
        return event

    def run(self) -> None:
        mask = (Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
                | Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown))
        self.tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly, mask, self._callback, None)
        if self.tap is None:
            sys.exit("Cannot listen to the keyboard. Give your terminal app permission in\n"
                     "System Settings > Privacy & Security > Input Monitoring (and Accessibility),\n"
                     "then quit and reopen the terminal.")
        source = Quartz.CFMachPortCreateRunLoopSource(None, self.tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self.tap, True)
        # Run in short slices so Ctrl+C reaches Python.
        while True:
            Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 0.5, False)


def permission_target() -> str:
    """The app macOS shows in Privacy settings: the terminal, or Python.app when run in the background."""
    if sys.stdin is not None and sys.stdin.isatty():
        return "your terminal app"
    real = os.path.realpath(sys.executable)
    app = os.path.join(real.split("/bin/")[0], "Resources", "Python.app")
    return app if os.path.isdir(app) else real


def request_permissions() -> None:
    """Ask macOS for keyboard permissions and log what is missing."""
    checks = [("Input Monitoring", "CGPreflightListenEventAccess", "CGRequestListenEventAccess"),
              ("Accessibility", "CGPreflightPostEventAccess", "CGRequestPostEventAccess")]
    for label, preflight, request in checks:
        if not hasattr(Quartz, preflight):
            continue
        if getattr(Quartz, preflight)():
            log(f"{label}: allowed")
        else:
            getattr(Quartz, request)()
            log(f"{label}: NOT allowed. Enable it for {permission_target()} in System Settings > "
                f"Privacy & Security > {label}, then restart fn-dictate.")


# --------------------------------------------------------------------------- main loop

def controller(events: queue.Queue, jobs: queue.Queue, recorder: Recorder,
               ollama: Ollama, sounds: bool) -> None:
    recording = False
    started = 0.0
    while True:
        ev = events.get()
        if ev == "down" and not recording:
            ollama.warm()
            try:
                recorder.start()
            except Exception as e:
                log(f"Microphone error: {e}")
                play("Basso", sounds)
                continue
            recording, started = True, time.time()
            log("fn down: recording...")
            play("Tink", sounds)
        elif ev == "cancel" and recording:
            recorder.stop()
            recording = False
            log("cancelled (fn used with another key)")
        elif ev == "up" and recording:
            audio = recorder.stop()
            recording = False
            if time.time() - started < MIN_HOLD_SEC:
                log("fn tap too short, ignored (hold it while you speak)")
                continue
            play("Pop", sounds)
            jobs.put(audio)


def worker(jobs: queue.Queue, ollama: Ollama, sounds: bool, dry_run: bool) -> None:
    while True:
        audio = jobs.get()
        if audio.size == 0 or float(np.sqrt(np.mean(audio ** 2))) < SILENCE_RMS:
            log("(silence, skipped)")
            continue
        t = time.time()
        try:
            text = clean(ollama.transcribe(audio))
        except Exception as e:
            log(f"Transcription failed: {e}")
            play("Basso", sounds)
            continue
        log(f"[{len(audio) / SAMPLE_RATE:.1f}s audio, {time.time() - t:.1f}s] {text.strip()}")
        if text and not dry_run:
            paste(text)


def self_test(ollama: Ollama, seconds: float) -> None:
    log(f"Recording {seconds:.0f}s from the microphone. Speak now...")
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    log("Transcribing...")
    t = time.time()
    text = ollama.transcribe(audio[:, 0])
    log(f"({time.time() - t:.1f}s) {text or '(nothing heard)'}")


def main() -> None:
    p = argparse.ArgumentParser(description="Hold fn to dictate anywhere on macOS (local Granite Speech via Ollama).")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name")
    p.add_argument("--url", default=DEFAULT_URL, help="Ollama server URL")
    p.add_argument("--keep-alive", default="5m",
                   help="How long Ollama keeps the model in RAM after last use (e.g. 10m, 1h, -1 = forever)")
    p.add_argument("--no-sound", action="store_true", help="Disable start/stop sounds")
    p.add_argument("--dry-run", action="store_true", help="Print transcripts but do not type them")
    p.add_argument("--test", nargs="?", const=5, type=float, metavar="SECONDS",
                   help="Record a few seconds, print the transcript, and exit")
    args = p.parse_args()

    ollama = Ollama(args.url, args.model, args.keep_alive)
    ollama.check()

    if args.test is not None:
        self_test(ollama, args.test)
        return

    request_permissions()
    ollama.warm()

    events: queue.Queue = queue.Queue()
    jobs: queue.Queue = queue.Queue()
    sounds = not args.no_sound
    threading.Thread(target=controller, args=(events, jobs, Recorder(), ollama, sounds), daemon=True).start()
    threading.Thread(target=worker, args=(jobs, ollama, sounds, args.dry_run), daemon=True).start()

    log(f"Ready. Hold fn, speak, release. Model: {args.model}. Ctrl+C to quit.")
    try:
        FnListener(events).run()
    except KeyboardInterrupt:
        log("Bye.")


if __name__ == "__main__":
    main()
