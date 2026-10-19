"""Robot-voice text to speech (pyttsx3 - the classic Windows SAPI voice).

Speech runs on its own thread so the game never stalls. Only the newest line matters: if the Czar
moves on before the voice finishes, queued lines are dropped. If pyttsx3 isn't installed, Windows'
built-in System.Speech (the same robot voice) is used through PowerShell instead.
"""
import queue
import re
import subprocess
import sys
import threading


def speakable(text):
    """Card text -> something a speech engine reads well."""
    t = re.sub(r"_+", " blank ", text)
    t = t.replace("\n", ". ").replace("&", " and ")
    t = re.sub(r"[*#\[\]{}<>|~^]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


class Speaker:
    def __init__(self, rate=165, volume=1.0):
        self.rate = rate
        self.volume = volume
        self.q = queue.Queue()
        self.thread = None
        self.backend = None  # "pyttsx3" | "powershell" | None (nothing available)
        self.error = None

    def say(self, text):
        text = speakable(text)
        if not text:
            return
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        while True:  # newest line wins
            try:
                self.q.get_nowait()
            except queue.Empty:
                break
        self.q.put(text)

    def _run(self):
        engine = None
        try:
            if sys.platform == "win32":
                import comtypes  # pyttsx3's SAPI driver needs COM set up on this thread
                comtypes.CoInitialize()
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            engine.setProperty("volume", self.volume)
            # Drive pyttsx3's loop by hand: runAndWait() hangs on its second call from a thread,
            # and this way a new line can cut off the previous one.
            engine.startLoop(False)
            self.backend = "pyttsx3"
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            engine = None
            self.backend = "powershell" if sys.platform == "win32" else None
        if engine is not None:
            while True:
                try:
                    text = self.q.get(timeout=0.03)
                    if text is None:
                        break
                    try:
                        if engine.isBusy():
                            engine.stop()
                        engine.say(text)
                    except Exception as e:  # noqa: BLE001
                        self.error = str(e)
                except queue.Empty:
                    pass
                try:
                    engine.iterate()
                except Exception as e:  # noqa: BLE001
                    self.error = str(e)
            try:
                engine.endLoop()
            except Exception:  # noqa: BLE001
                pass
            return
        while True:
            text = self.q.get()
            if text is None:
                break
            try:
                if self.backend == "powershell":
                    script = ("Add-Type -AssemblyName System.Speech; "
                              "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Rate = 1; "
                              "$s.Speak([Console]::In.ReadToEnd())")
                    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                   input=text, text=True, timeout=60,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception as e:  # noqa: BLE001 - a voice glitch must never take the game down
                self.error = str(e)

    def close(self):
        if self.thread:
            self.q.put(None)


_speaker = None


def speaker():
    global _speaker
    if _speaker is None:
        _speaker = Speaker()
    return _speaker
