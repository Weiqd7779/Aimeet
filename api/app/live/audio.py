import numpy as np


def resample_pcm16(audio: bytes, source_rate: int = 16_000, target_rate: int = 24_000) -> bytes:
    """Linearly resample little-endian PCM16 audio to a new sample rate."""
    samples = np.frombuffer(audio, dtype="<i2")
    if not len(samples) or source_rate == target_rate:
        return audio
    output_length = round(len(samples) * target_rate / source_rate)
    positions = np.linspace(0, len(samples) - 1, output_length)
    resampled = np.interp(positions, np.arange(len(samples)), samples)
    return np.rint(resampled).clip(-32768, 32767).astype("<i2").tobytes()
