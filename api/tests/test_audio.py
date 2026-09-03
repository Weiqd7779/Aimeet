import numpy as np

from app.live.audio import resample_pcm16


def test_resample_pcm16_length_ratio() -> None:
    samples = np.arange(160, dtype="<i2")
    output = np.frombuffer(resample_pcm16(samples.tobytes()), dtype="<i2")

    assert len(output) == 240


def test_resample_pcm16_constant_signal_stays_constant() -> None:
    samples = np.full(160, 1234, dtype="<i2")

    output = np.frombuffer(resample_pcm16(samples.tobytes()), dtype="<i2")

    assert len(output) == 240
    assert np.all(output == 1234)
