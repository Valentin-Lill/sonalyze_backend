"""
Audio alignment module for synchronizing recordings using chirp detection.

This module provides functions to:
1. Detect sync chirps in recorded audio via cross-correlation
2. Align recordings to extract the measurement sweep portion
3. Handle edge cases like missing chirps or low SNR

The sync chirp (2kHz - 10kHz, 0.5s) at the start and end of the measurement
signal serves as a temporal marker to find where the sweep begins in a recording.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
import numpy as np
from scipy import signal as scipy_signal

from app.analysis.audio_generator import (
    MeasurementSignalConfig,
    generate_log_chirp,
    apply_fade,
    get_signal_timing,
)

logger = logging.getLogger(__name__)


@dataclass
class ChirpDetectionResult:
    """Result of chirp detection in a recording."""
    detected: bool
    sample_index: int  # Sample index where chirp starts
    time_seconds: float  # Time in seconds where chirp starts
    correlation_peak: float  # Peak correlation value (normalized)
    confidence: float  # Confidence score (0-1)
    

@dataclass
class AlignmentResult:
    """Result of audio alignment."""
    success: bool
    aligned_audio: np.ndarray
    sample_rate: int
    
    # Detected positions
    start_chirp: ChirpDetectionResult | None
    end_chirp: ChirpDetectionResult | None
    
    # Extracted regions (sample indices in original recording)
    sweep_start_sample: int
    sweep_end_sample: int
    
    # Debug info
    message: str
    original_length_samples: int
    aligned_length_samples: int


def generate_chirp_template(
    config: MeasurementSignalConfig | None = None,
) -> np.ndarray:
    """
    Generate the sync chirp template for cross-correlation.
    
    Args:
        config: Measurement signal configuration
        
    Returns:
        Chirp template as numpy array
    """
    if config is None:
        config = MeasurementSignalConfig()
    
    fade_samples = int(config.fade_duration * config.sample_rate)
    
    chirp = generate_log_chirp(
        duration=config.sync_chirp_duration,
        f_start=config.sync_chirp_f_start,
        f_end=config.sync_chirp_f_end,
        sample_rate=config.sample_rate,
        amplitude=1.0,
    )
    chirp = apply_fade(chirp, fade_samples)
    
    return chirp.astype(np.float64)


def detect_chirp(
    recording: np.ndarray,
    chirp_template: np.ndarray,
    sample_rate: int,
    search_start: int = 0,
    search_end: int | None = None,
    min_confidence: float = 0.3,
) -> ChirpDetectionResult:
    """
    Detect a sync chirp in a recording using normalized cross-correlation.
    
    Args:
        recording: The recorded audio signal
        chirp_template: The chirp template to search for
        sample_rate: Sample rate of both signals
        search_start: Start sample for search region
        search_end: End sample for search region (None = end of recording)
        min_confidence: Minimum correlation for a valid detection
        
    Returns:
        ChirpDetectionResult with detection info
    """
    if search_end is None:
        search_end = len(recording)
    
    # Extract search region
    search_region = recording[search_start:search_end].astype(np.float64)
    template = chirp_template.astype(np.float64)
    
    if len(search_region) < len(template):
        return ChirpDetectionResult(
            detected=False,
            sample_index=0,
            time_seconds=0.0,
            correlation_peak=0.0,
            confidence=0.0,
        )
    
    # Normalize template
    template = template - np.mean(template)
    template_norm = np.linalg.norm(template)
    if template_norm < 1e-10:
        template_norm = 1.0
    template = template / template_norm
    
    # Use scipy correlate for efficiency (mode='valid' gives output where
    # template fully overlaps with signal)
    # We use 'same' to maintain length, then find the peak
    correlation = scipy_signal.correlate(search_region, template, mode='valid')
    
    # Normalize correlation by local energy in sliding window
    # This makes it robust to amplitude variations
    window_size = len(template)
    
    # Calculate local energy using convolution (more efficient)
    energy = np.convolve(
        search_region ** 2,
        np.ones(window_size),
        mode='valid'
    )
    energy_norm = np.sqrt(np.maximum(energy, 1e-10))
    
    # Normalized correlation
    norm_correlation = correlation / energy_norm
    
    # Find peak
    peak_idx = int(np.argmax(np.abs(norm_correlation)))
    peak_value = float(norm_correlation[peak_idx])
    
    # Calculate confidence based on peak prominence
    # Compare peak to median of correlation
    median_corr = float(np.median(np.abs(norm_correlation)))
    if median_corr > 0:
        prominence = abs(peak_value) / median_corr
        confidence = min(1.0, prominence / 10.0)  # Normalize to 0-1
    else:
        confidence = 1.0 if abs(peak_value) > min_confidence else 0.0
    
    # Adjust index back to original recording coordinates
    absolute_index = search_start + peak_idx
    
    detected = abs(peak_value) >= min_confidence and confidence >= 0.2
    
    return ChirpDetectionResult(
        detected=detected,
        sample_index=absolute_index,
        time_seconds=absolute_index / sample_rate,
        correlation_peak=abs(peak_value),
        confidence=confidence,
    )


def align_recording(
    recording: np.ndarray,
    sample_rate: int,
    config: MeasurementSignalConfig | None = None,
    include_reverb_tail: bool = True,
    chirp_template: np.ndarray | None = None,
) -> AlignmentResult:
    """
    Align a recording by detecting sync chirps and extracting the sweep region.
    
    The function:
    1. Detects the start chirp to find where the measurement begins
    2. Optionally detects the end chirp for verification
    3. Extracts the sweep portion plus reverb tail
    
    Args:
        recording: The recorded audio signal (mono, float)
        sample_rate: Sample rate of the recording
        config: Measurement signal configuration (uses defaults if None)
        include_reverb_tail: Whether to include the post-sweep silence for reverb tail
        chirp_template: Optional pre-loaded chirp template. If provided, this
                       will be used instead of regenerating from config. This
                       ensures alignment uses the exact same chirp that was
                       played during measurement.
        
    Returns:
        AlignmentResult with aligned audio and detection info
    """
    if config is None:
        config = MeasurementSignalConfig(sample_rate=sample_rate)
    elif config.sample_rate != sample_rate:
        # Recreate config with correct sample rate
        config = MeasurementSignalConfig(sample_rate=sample_rate)
    
    recording = recording.astype(np.float64)
    original_length = len(recording)
    
    # Use provided chirp template or generate one
    if chirp_template is not None:
        logger.info(f"Using provided chirp template (length={len(chirp_template)})")
        chirp = chirp_template.astype(np.float64)
    else:
        logger.info("Generating chirp template from config")
        chirp = generate_chirp_template(config)
    
    # Get timing info
    timing = get_signal_timing(config)
    chirp_duration_samples = int(config.sync_chirp_duration * sample_rate)
    post_sync_silence_samples = int(config.post_sync_silence * sample_rate)
    sweep_duration_samples = int(config.sweep_duration * sample_rate)
    post_sweep_silence_samples = int(config.post_sweep_silence * sample_rate)
    
    # Expected total from chirp start to end of sweep + reverb tail
    expected_signal_length = (
        chirp_duration_samples +
        post_sync_silence_samples +
        sweep_duration_samples +
        post_sweep_silence_samples
    )
    
    logger.info(f"Searching for start chirp in recording (length={original_length} samples)")
    
    # Detect start chirp - search in first portion of recording
    # Allow up to 5 seconds of lead-in before the chirp
    max_lead_in_samples = int(5.0 * sample_rate)
    search_end_start = min(max_lead_in_samples + chirp_duration_samples * 2, original_length)
    
    start_chirp = detect_chirp(
        recording,
        chirp,
        sample_rate,
        search_start=0,
        search_end=search_end_start,
        min_confidence=0.25,
    )
    
    if not start_chirp.detected:
        logger.warning(
            f"Start chirp not detected (peak={start_chirp.correlation_peak:.3f}, "
            f"confidence={start_chirp.confidence:.3f}). Using fallback alignment."
        )
        # Fallback: assume recording starts near the beginning
        # Try to find any significant energy onset
        start_chirp = ChirpDetectionResult(
            detected=False,
            sample_index=0,
            time_seconds=0.0,
            correlation_peak=start_chirp.correlation_peak,
            confidence=start_chirp.confidence,
        )
    else:
        logger.info(
            f"Start chirp detected at sample {start_chirp.sample_index} "
            f"({start_chirp.time_seconds:.3f}s), confidence={start_chirp.confidence:.3f}"
        )
    
    # Calculate sweep region based on detected chirp position
    # Sweep starts after: chirp + post_sync_silence
    sweep_start = start_chirp.sample_index + chirp_duration_samples + post_sync_silence_samples
    
    # Sweep ends after: sweep_duration
    sweep_end = sweep_start + sweep_duration_samples
    
    # Include reverb tail (but NOT the end chirp)
    # The post_sweep_silence IS the reverb tail period, don't go beyond it
    if include_reverb_tail:
        extraction_end = sweep_end + post_sweep_silence_samples
    else:
        extraction_end = sweep_end
    
    # Detect end chirp for verification (optional)
    # End chirp should be after the reverb tail
    expected_end_chirp_start = sweep_end + post_sweep_silence_samples
    
    end_chirp = None
    if expected_end_chirp_start + chirp_duration_samples * 2 < original_length:
        search_start_end = max(0, expected_end_chirp_start - int(1.0 * sample_rate))
        search_end_end = min(original_length, expected_end_chirp_start + int(2.0 * sample_rate))
        
        end_chirp = detect_chirp(
            recording,
            chirp,
            sample_rate,
            search_start=search_start_end,
            search_end=search_end_end,
            min_confidence=0.2,
        )
        
        if end_chirp.detected:
            logger.info(
                f"End chirp detected at sample {end_chirp.sample_index} "
                f"({end_chirp.time_seconds:.3f}s), confidence={end_chirp.confidence:.3f}"
            )
            # Use end chirp position to refine extraction_end if needed
            # Don't include the end chirp in the output
            extraction_end = min(extraction_end, end_chirp.sample_index)
        else:
            logger.info("End chirp not detected (may be cut off or low SNR)")
    
    # Clamp to valid range
    sweep_start = max(0, sweep_start)
    sweep_end = min(original_length, sweep_end)
    extraction_end = min(original_length, extraction_end)
    
    # Extract the aligned audio (sweep + reverb tail)
    # We want to extract from sweep_start to extraction_end
    aligned_audio = recording[sweep_start:extraction_end].copy()
    
    # Determine success
    success = start_chirp.detected or start_chirp.correlation_peak > 0.15
    
    if len(aligned_audio) < sweep_duration_samples // 2:
        success = False
        message = f"Extracted audio too short ({len(aligned_audio)} samples)"
        logger.warning(message)
    else:
        message = (
            f"Aligned audio: {len(aligned_audio)} samples "
            f"({len(aligned_audio)/sample_rate:.2f}s) from original {original_length} samples"
        )
        logger.info(message)
    
    return AlignmentResult(
        success=success,
        aligned_audio=aligned_audio.astype(np.float32),
        sample_rate=sample_rate,
        start_chirp=start_chirp,
        end_chirp=end_chirp,
        sweep_start_sample=sweep_start,
        sweep_end_sample=sweep_end,
        message=message,
        original_length_samples=original_length,
        aligned_length_samples=len(aligned_audio),
    )


def extract_sweep_for_deconvolution(
    recording: np.ndarray,
    sample_rate: int,
    config: MeasurementSignalConfig | None = None,
    chirp_template: np.ndarray | None = None,
) -> tuple[np.ndarray, AlignmentResult]:
    """
    Extract and align the sweep portion from a recording for deconvolution.
    
    This is the main entry point for the alignment functionality.
    
    Args:
        recording: The recorded audio signal
        sample_rate: Sample rate of the recording
        config: Measurement signal configuration
        chirp_template: Optional pre-loaded chirp template. If provided, this
                       will be used instead of regenerating from config.
        
    Returns:
        Tuple of (aligned_recording, alignment_result)
    """
    result = align_recording(
        recording=recording,
        sample_rate=sample_rate,
        config=config,
        include_reverb_tail=True,
        chirp_template=chirp_template,
    )
    
    return result.aligned_audio, result
