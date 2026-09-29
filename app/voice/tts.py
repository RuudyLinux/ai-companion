"""Local text-to-speech via pyttsx3 (Windows SAPI5 voices) — fully offline, no API calls.

A fresh engine is created per call rather than reused: pyttsx3 wraps COM objects on
Windows, and COM objects created on one thread can't be reused safely from another —
FastAPI's threadpool for sync endpoints doesn't guarantee the same thread each request.
"""

import pyttsx3


def synthesize_to_file(text: str, out_path: str) -> None:
    engine = pyttsx3.init()
    engine.save_to_file(text, out_path)
    engine.runAndWait()
    engine.stop()
