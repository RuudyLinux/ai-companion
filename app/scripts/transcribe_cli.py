"""
Runs faster-whisper transcription in its own process, invoked via subprocess from
voice/stt.py. Necessary because ctranslate2 (faster-whisper's backend) bundles its own
CUDA/cuDNN runtime that crashes when it coexists in the same process as torch (XTTS) —
confirmed by reproduction: the conflict happens regardless of import order, so the two
libraries simply cannot share one process on this machine.

Usage: python transcribe_cli.py <audio_path>  -> prints transcript to stdout
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice.stt import transcribe

if __name__ == "__main__":
    audio_path = sys.argv[1]
    text = transcribe(audio_path)
    sys.stdout.buffer.write(text.encode("utf-8"))
