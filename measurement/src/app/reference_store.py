"""
Reference store for measurement signals.

Stores the sync chirp and sweep signals when measurement audio is generated,
so they can be reused during analysis for alignment and deconvolution.

This ensures that even if the signal configuration changes, analysis will
use the exact same references that were used during the measurement.
"""
from __future__ import annotations

import hashlib
import json
import logging
import pathlib
from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import soundfile as sf

from app.settings import settings


logger = logging.getLogger(__name__)


@dataclass
class StoredReference:
    """Metadata for a stored reference signal."""
    audio_hash: str
    sample_rate: int
    config: dict[str, Any]
    
    # Paths relative to reference directory
    chirp_path: str
    sweep_path: str
    full_signal_path: str


class ReferenceStore:
    """
    Store and retrieve measurement reference signals.
    
    References are keyed by the SHA-256 hash of the full measurement audio,
    ensuring deterministic retrieval.
    """
    
    def __init__(self, root_dir: pathlib.Path | None = None):
        if root_dir is None:
            # Use data_dir from settings, with 'references' subdirectory
            base_dir = pathlib.Path(settings.data_dir)
            # If data_dir doesn't exist or isn't writable, fall back to local directory
            try:
                base_dir.mkdir(parents=True, exist_ok=True)
                root_dir = base_dir / "references"
            except (PermissionError, OSError):
                # Fall back to local directory for development
                root_dir = pathlib.Path(__file__).parent.parent.parent.parent / "measurement_data" / "references"
                logger.warning(f"Using fallback reference store directory: {root_dir}")
        
        self.root_dir = root_dir
        try:
            self.root_dir.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as e:
            logger.warning(f"Could not create reference store directory {root_dir}: {e}")
    
    def _ref_dir(self, audio_hash: str) -> pathlib.Path:
        """Get directory for a specific reference."""
        # Use first 8 chars as subdirectory to avoid too many files in one dir
        return self.root_dir / audio_hash[:8] / audio_hash
    
    def store_reference(
        self,
        audio_hash: str,
        sample_rate: int,
        config_dict: dict[str, Any],
        chirp: np.ndarray,
        sweep: np.ndarray,
        full_signal: np.ndarray,
    ) -> StoredReference:
        """
        Store reference signals for later retrieval.
        
        Args:
            audio_hash: SHA-256 hash of the full measurement audio
            sample_rate: Sample rate of the signals
            config_dict: Configuration used to generate the signals
            chirp: The sync chirp signal
            sweep: The measurement sweep signal
            full_signal: The complete measurement signal
            
        Returns:
            StoredReference with paths to stored files
        """
        ref_dir = self._ref_dir(audio_hash)
        ref_dir.mkdir(parents=True, exist_ok=True)
        
        # Save signals as WAV files
        chirp_path = ref_dir / "chirp.wav"
        sweep_path = ref_dir / "sweep.wav"
        full_path = ref_dir / "full_signal.wav"
        
        sf.write(str(chirp_path), chirp.astype(np.float32), sample_rate, subtype='FLOAT')
        sf.write(str(sweep_path), sweep.astype(np.float32), sample_rate, subtype='FLOAT')
        sf.write(str(full_path), full_signal.astype(np.float32), sample_rate, subtype='FLOAT')
        
        # Save metadata
        ref = StoredReference(
            audio_hash=audio_hash,
            sample_rate=sample_rate,
            config=config_dict,
            chirp_path="chirp.wav",
            sweep_path="sweep.wav",
            full_signal_path="full_signal.wav",
        )
        
        meta_path = ref_dir / "metadata.json"
        with open(meta_path, "w") as f:
            json.dump(asdict(ref), f, indent=2)
        
        logger.info(f"Stored reference signals for hash {audio_hash[:16]}...")
        
        return ref
    
    def load_reference(self, audio_hash: str) -> StoredReference | None:
        """
        Load reference metadata by audio hash.
        
        Args:
            audio_hash: SHA-256 hash of the measurement audio
            
        Returns:
            StoredReference if found, None otherwise
        """
        ref_dir = self._ref_dir(audio_hash)
        meta_path = ref_dir / "metadata.json"
        
        if not meta_path.exists():
            logger.debug(f"No stored reference for hash {audio_hash[:16]}...")
            return None
        
        try:
            with open(meta_path) as f:
                data = json.load(f)
            return StoredReference(**data)
        except Exception as e:
            logger.warning(f"Failed to load reference metadata: {e}")
            return None
    
    def load_chirp(self, audio_hash: str) -> tuple[np.ndarray, int] | None:
        """
        Load the chirp signal by audio hash.
        
        Returns:
            Tuple of (chirp_signal, sample_rate) or None if not found
        """
        ref = self.load_reference(audio_hash)
        if ref is None:
            return None
        
        chirp_path = self._ref_dir(audio_hash) / ref.chirp_path
        if not chirp_path.exists():
            logger.warning(f"Chirp file not found: {chirp_path}")
            return None
        
        try:
            chirp, sr = sf.read(str(chirp_path), dtype='float64')
            return chirp, sr
        except Exception as e:
            logger.warning(f"Failed to load chirp: {e}")
            return None
    
    def load_sweep(self, audio_hash: str) -> tuple[np.ndarray, int] | None:
        """
        Load the sweep signal by audio hash.
        
        Returns:
            Tuple of (sweep_signal, sample_rate) or None if not found
        """
        ref = self.load_reference(audio_hash)
        if ref is None:
            return None
        
        sweep_path = self._ref_dir(audio_hash) / ref.sweep_path
        if not sweep_path.exists():
            logger.warning(f"Sweep file not found: {sweep_path}")
            return None
        
        try:
            sweep, sr = sf.read(str(sweep_path), dtype='float64')
            return sweep, sr
        except Exception as e:
            logger.warning(f"Failed to load sweep: {e}")
            return None
    
    def load_full_signal(self, audio_hash: str) -> tuple[np.ndarray, int] | None:
        """
        Load the full measurement signal by audio hash.
        
        Returns:
            Tuple of (signal, sample_rate) or None if not found
        """
        ref = self.load_reference(audio_hash)
        if ref is None:
            return None
        
        signal_path = self._ref_dir(audio_hash) / ref.full_signal_path
        if not signal_path.exists():
            logger.warning(f"Full signal file not found: {signal_path}")
            return None
        
        try:
            signal, sr = sf.read(str(signal_path), dtype='float64')
            return signal, sr
        except Exception as e:
            logger.warning(f"Failed to load full signal: {e}")
            return None
    
    def has_reference(self, audio_hash: str) -> bool:
        """Check if a reference exists for the given hash."""
        ref_dir = self._ref_dir(audio_hash)
        return (ref_dir / "metadata.json").exists()


# Global instance
reference_store = ReferenceStore()
