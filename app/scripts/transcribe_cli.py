"""
Runs faster-whisper transcription in its own process, invoked by voice/stt_runner.py.
Necessary because ctranslate2 (faster-whisper's backend) bundles its own CUDA/cuDNN
runtime that crashes when it coexists in the same process as torch (XTTS) — confirmed
by reproduction: the conflict happens regardless of import order, so the two libraries
simply cannot share one process on this machine.

Usage: python transcribe_cli.py <audio_path>
  stdout: {"text": "...", "language": "en"}   exit 0
  stderr: error description                    exit 1 (bad usage) / 2 (failure)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: transcribe_cli.py <audio_path>", file=sys.stderr)
        return 1
    audio_path = sys.argv[1]
    if not Path(audio_path).is_file():
        print("audio file not found", file=sys.stderr)
        return 1
    try:
        from voice.stt import transcribe

        text, language = transcribe(audio_path)
    except Exception as exc:  # report and exit non-zero; the parent maps this to STT_FAILED
        print(f"transcription failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(json.dumps({"text": text, "language": language}, ensure_ascii=False).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
