def audio_duration_seconds(path: str) -> float:
    import soundfile as sf
    info = sf.info(path)
    return round(info.frames / info.samplerate, 2)
