def audio_duration_seconds(path: str) -> float:
    import soundfile as sf

    info = sf.info(path)
    return round(info.frames / info.samplerate, 2)


def convert_to_wav(src: str, dst: str, sample_rate: int = 24000) -> None:
    """Decodes any container PyAV understands (webm/ogg/mp3/m4a/...) to mono 16-bit WAV,
    the one format every engine (XTTS, F5-TTS, Inworld) accepts as a clone reference."""
    import av
    import numpy as np
    import soundfile as sf

    resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
    chunks = []
    with av.open(src) as container:
        stream = next(s for s in container.streams if s.type == "audio")
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):  # flush
            chunks.append(out.to_ndarray().reshape(-1))
    samples = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
    sf.write(dst, samples, sample_rate, subtype="PCM_16")
