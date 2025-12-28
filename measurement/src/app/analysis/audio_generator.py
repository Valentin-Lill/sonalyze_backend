"""
Audio generation module for acoustic measurements.

Generates measurement signals containing:
- Sync chirp (for temporal alignment)
- Silence (for chirp decay)
- Measurement sweep (logarithmic sine sweep for impulse response extraction)
- Trailing silence (for room decay/reverb tail capture)
- Final sync chirp (for verification)

Signal structure (default 15s):
    0.0s  -  0.5s: Sync Chirp (2kHz - 10kHz)
    0.5s  -  2.5s: Silence (2s for sync chirp decay)
    2.5s  - 12.5s: Measurement Sweep (20Hz - 20kHz, 10s)
   12.5s  - 14.5s: Silence (room decay/reverb tail)
   14.5s  - 15.0s: Sync Chirp (verification)
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import soundfile as sf


@dataclass
class MeasurementSignalConfig:
    """Configuration for measurement signal generation."""
    
    sample_rate: int = 48000
    
    # Sync chirp parameters
    sync_chirp_duration: float = 0.5  # seconds
    sync_chirp_f_start: float = 2000.0  # Hz
    sync_chirp_f_end: float = 10000.0  # Hz
    
    # Silence durations
    post_sync_silence: float = 2.0  # seconds (for sync chirp decay)
    post_sweep_silence: float = 2.0  # seconds (for reverb tail)
    
    # Measurement sweep parameters
    sweep_duration: float = 10.0  # seconds
    sweep_f_start: float = 20.0  # Hz
    sweep_f_end: float = 20000.0  # Hz
    
    # Output parameters
    amplitude: float = 0.9  # Peak amplitude (0.0-1.0)
    fade_duration: float = 0.01  # seconds for fade in/out
    
    @property
    def total_duration(self) -> float:
        """Calculate total signal duration in seconds."""
        return (
            self.sync_chirp_duration +
            self.post_sync_silence +
            self.sweep_duration +
            self.post_sweep_silence +
            self.sync_chirp_duration
        )
    
    @property
    def total_samples(self) -> int:
        """Calculate total number of samples."""
        return int(self.total_duration * self.sample_rate)


def generate_log_chirp(
    duration: float,
    f_start: float,
    f_end: float,
    sample_rate: int,
    amplitude: float = 1.0,
) -> np.ndarray:
    """
    Generate a logarithmic (exponential) sine sweep.
    
    A logarithmic sweep has constant energy per octave, which is preferred
    for room acoustic measurements as it weights all frequency bands equally
    in a perceptually meaningful way.
    
    Args:
        duration: Length of the sweep in seconds
        f_start: Starting frequency in Hz
        f_end: Ending frequency in Hz
        sample_rate: Sample rate in Hz
        amplitude: Peak amplitude (0.0-1.0)
    
    Returns:
        NumPy array containing the chirp signal
    """
    num_samples = int(duration * sample_rate)
    t = np.linspace(0, duration, num_samples, endpoint=False)
    
    # Logarithmic sweep rate
    k = duration / np.log(f_end / f_start)
    
    # Phase of logarithmic sweep
    phase = 2 * np.pi * f_start * k * (np.exp(t / k) - 1)
    
    signal = amplitude * np.sin(phase)
    return signal.astype(np.float32)


def apply_fade(
    signal: np.ndarray,
    fade_samples: int,
) -> np.ndarray:
    """Apply fade-in and fade-out to a signal using raised cosine."""
    if fade_samples <= 0 or signal.size < 2 * fade_samples:
        return signal
    
    # Raised cosine fade
    fade_in = 0.5 * (1 - np.cos(np.linspace(0, np.pi, fade_samples)))
    fade_out = 0.5 * (1 + np.cos(np.linspace(0, np.pi, fade_samples)))
    
    result = signal.copy()
    result[:fade_samples] *= fade_in
    result[-fade_samples:] *= fade_out
    
    return result


def generate_measurement_signal(
    config: MeasurementSignalConfig | None = None,
) -> tuple[np.ndarray, int]:
    """
    Generate a complete measurement signal.
    
    Args:
        config: Configuration for signal generation. Uses defaults if None.
    
    Returns:
        Tuple of (signal array, sample rate)
    """
    if config is None:
        config = MeasurementSignalConfig()
    
    fade_samples = int(config.fade_duration * config.sample_rate)
    
    # Generate sync chirp
    sync_chirp = generate_log_chirp(
        duration=config.sync_chirp_duration,
        f_start=config.sync_chirp_f_start,
        f_end=config.sync_chirp_f_end,
        sample_rate=config.sample_rate,
        amplitude=config.amplitude,
    )
    sync_chirp = apply_fade(sync_chirp, fade_samples)
    
    # Generate measurement sweep
    measurement_sweep = generate_log_chirp(
        duration=config.sweep_duration,
        f_start=config.sweep_f_start,
        f_end=config.sweep_f_end,
        sample_rate=config.sample_rate,
        amplitude=config.amplitude,
    )
    measurement_sweep = apply_fade(measurement_sweep, fade_samples)
    
    # Generate silence segments
    post_sync_silence = np.zeros(
        int(config.post_sync_silence * config.sample_rate),
        dtype=np.float32,
    )
    post_sweep_silence = np.zeros(
        int(config.post_sweep_silence * config.sample_rate),
        dtype=np.float32,
    )
    
    # Concatenate all segments
    signal = np.concatenate([
        sync_chirp,          # 0.0s - 0.5s
        post_sync_silence,   # 0.5s - 2.5s
        measurement_sweep,   # 2.5s - 12.5s
        post_sweep_silence,  # 12.5s - 14.5s
        sync_chirp,          # 14.5s - 15.0s (same sync chirp for verification)
    ])
    
    return signal, config.sample_rate


def generate_measurement_audio_bytes(
    config: MeasurementSignalConfig | None = None,
    format: str = "WAV",
    subtype: str = "PCM_16",
) -> bytes:
    """
    Generate measurement audio and return as bytes.
    
    Args:
        config: Configuration for signal generation
        format: Audio format (WAV, FLAC, etc.)
        subtype: Audio subtype (PCM_16, PCM_24, FLOAT, etc.)
    
    Returns:
        Audio file as bytes
    """
    signal, sample_rate = generate_measurement_signal(config)
    
    buffer = io.BytesIO()
    sf.write(buffer, signal, sample_rate, format=format, subtype=subtype)
    buffer.seek(0)
    
    return buffer.read()


def generate_measurement_audio_file(
    path: str,
    config: MeasurementSignalConfig | None = None,
    format: str | None = None,
    subtype: str = "PCM_16",
) -> None:
    """
    Generate measurement audio and save to file.
    
    Args:
        path: Output file path
        config: Configuration for signal generation
        format: Audio format (auto-detected from extension if None)
        subtype: Audio subtype (PCM_16, PCM_24, FLOAT, etc.)
    """
    signal, sample_rate = generate_measurement_signal(config)
    sf.write(path, signal, sample_rate, format=format, subtype=subtype)


def get_signal_timing(config: MeasurementSignalConfig | None = None) -> dict:
    """
    Get timing information for the measurement signal.
    
    This is useful for clients to know when each segment starts/ends.
    
    Returns:
        Dictionary with timing information in seconds
    """
    if config is None:
        config = MeasurementSignalConfig()
    
    t = 0.0
    timing = {
        "sample_rate": config.sample_rate,
        "total_duration": config.total_duration,
        "segments": [],
    }
    
    # First sync chirp
    timing["segments"].append({
        "name": "sync_chirp_start",
        "type": "chirp",
        "start": t,
        "end": t + config.sync_chirp_duration,
        "f_start": config.sync_chirp_f_start,
        "f_end": config.sync_chirp_f_end,
    })
    t += config.sync_chirp_duration
    
    # Post-sync silence
    timing["segments"].append({
        "name": "post_sync_silence",
        "type": "silence",
        "start": t,
        "end": t + config.post_sync_silence,
    })
    t += config.post_sync_silence
    
    # Measurement sweep
    timing["segments"].append({
        "name": "measurement_sweep",
        "type": "sweep",
        "start": t,
        "end": t + config.sweep_duration,
        "f_start": config.sweep_f_start,
        "f_end": config.sweep_f_end,
    })
    t += config.sweep_duration
    
    # Post-sweep silence (reverb tail)
    timing["segments"].append({
        "name": "reverb_tail",
        "type": "silence",
        "start": t,
        "end": t + config.post_sweep_silence,
    })
    t += config.post_sweep_silence
    
    # Final sync chirp
    timing["segments"].append({
        "name": "sync_chirp_end",
        "type": "chirp",
        "start": t,
        "end": t + config.sync_chirp_duration,
        "f_start": config.sync_chirp_f_start,
        "f_end": config.sync_chirp_f_end,
    })
    
    # Useful time offsets for synchronization
    timing["sweep_start"] = timing["segments"][2]["start"]
    timing["sweep_end"] = timing["segments"][2]["end"]
    timing["recommended_recording_start"] = 0.0
    timing["recommended_recording_end"] = config.total_duration
    
    return timing
