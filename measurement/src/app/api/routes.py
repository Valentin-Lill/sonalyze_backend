from __future__ import annotations

import dataclasses
import hashlib
import logging
import pathlib
import re
import uuid

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.analysis.audio_generator import (
    MeasurementSignalConfig,
    generate_measurement_audio_bytes,
    generate_measurement_signal,
    generate_log_chirp,
    apply_fade,
    get_signal_timing,
)
from app.analysis.io import normalize_peak, read_audio_mono
from app.reference_store import reference_store
from app.analysis.metrics import (
    build_display_metrics,
    clarity_definition_metrics,
    deconvolve_sweep,
    drr_metrics,
    freq_response_summary,
    rt_metrics_from_ir,
    snr_quality,
)
from app.analysis.sti import sti_from_impulse_response
from app.models import AnalyzeRequest, AnalyzeResponse, CreateJobRequest, CreateJobResponse
from app.settings import settings
from app.storage import LocalJobStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")
store = LocalJobStore(root_dir=pathlib.Path(settings.data_dir))

_SAFE_UPLOAD_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/jobs", response_model=CreateJobResponse)
def create_job(req: CreateJobRequest) -> CreateJobResponse:
    job_id = str(uuid.uuid4())
    job_dir = store.ensure_job(job_id)
    store.write_json(job_dir / "map.json", req.map.model_dump(mode="json"))
    store.write_json(job_dir / "job_meta.json", req.meta)
    return CreateJobResponse(job_id=job_id)


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job_dir = store.ensure_job(job_id)
    payload = {
        "job_id": job_id,
        "map": store.read_json(job_dir / "map.json"),
        "meta": store.read_json(job_dir / "job_meta.json"),
        "uploads": sorted([p.name for p in (job_dir / "uploads").glob("*") if p.is_file()]),
    }
    results_path = job_dir / "results" / "analysis.json"
    if results_path.exists():
        payload["results"] = store.read_json(results_path)
    return payload


@router.post("/jobs/{job_id}/uploads/{upload_name}")
def upload(job_id: str, upload_name: str, file: UploadFile = File(...)) -> dict:
    if not _SAFE_UPLOAD_RE.match(upload_name):
        raise HTTPException(status_code=400, detail="Invalid upload_name")
    content = file.file
    size = 0
    # enforce max size
    max_bytes = int(settings.max_upload_mb) * 1024 * 1024
    job_dir = store.ensure_job(job_id)
    path = job_dir / "uploads" / upload_name
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("wb") as f:
        while True:
            chunk = content.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Upload too large (>{settings.max_upload_mb} MB)")
            f.write(chunk)
    tmp_path.replace(path)
    return {"job_id": job_id, "upload": upload_name, "bytes": size}


@router.post("/jobs/{job_id}/analyze", response_model=AnalyzeResponse)
def analyze(job_id: str, req: AnalyzeRequest) -> AnalyzeResponse:
    job_dir = store.ensure_job(job_id)
    uploads_dir = job_dir / "uploads"

    if req.source == "impulse_response":
        name = req.impulse_response_upload or "impulse_response"
        ir_path = uploads_dir / name
        if not ir_path.exists():
            raise HTTPException(status_code=400, detail=f"Missing upload '{name}'")

        ir, fs = read_audio_mono(str(ir_path))
        ir = normalize_peak(ir)

    elif req.source == "sweep_deconvolution":
        rec_name = req.recording_upload or "recording"
        sweep_name = req.sweep_reference_upload or "sweep_reference"
        rec_path = uploads_dir / rec_name
        sweep_path = uploads_dir / sweep_name
        if not rec_path.exists() or not sweep_path.exists():
            raise HTTPException(status_code=400, detail=f"Missing uploads '{rec_name}' and/or '{sweep_name}'")

        rec, fs_r = read_audio_mono(str(rec_path))
        sweep, fs_s = read_audio_mono(str(sweep_path))
        if fs_r != fs_s:
            raise HTTPException(status_code=400, detail=f"Samplerate mismatch recording={fs_r} sweep={fs_s}")

        ir = deconvolve_sweep(rec, sweep)
        ir = normalize_peak(ir)
        fs = fs_r

    else:
        raise HTTPException(status_code=400, detail="Invalid source")

    rt = rt_metrics_from_ir(ir, fs)
    clarity = clarity_definition_metrics(ir, fs)
    drr = drr_metrics(ir, fs)
    quality = snr_quality(ir)
    freq_resp = freq_response_summary(ir, fs)
    sti = sti_from_impulse_response(ir, fs)

    results = {
        "samplerate_hz": fs,
        "rt": rt,
        "clarity": clarity,
        "drr": drr,
        "quality": quality,
        "frequency_response": freq_resp,
        "sti": sti,
        # Universal display format - frontend renders this dynamically
        "display_metrics": build_display_metrics(
            rt=rt,
            clarity=clarity,
            drr=drr,
            quality=quality,
            sti=sti,
        ),
    }

    store.write_json(job_dir / "results" / "analysis.json", results)

    return AnalyzeResponse(job_id=job_id, results=results)


# =============================================================================
# Measurement Audio Endpoints
# =============================================================================

@router.get("/measurement/audio")
def get_measurement_audio(
    session_id: str | None = Query(default=None, description="Session ID for tracking"),
    sample_rate: int = Query(default=48000, ge=8000, le=192000, description="Sample rate in Hz"),
    format: str = Query(default="wav", description="Audio format: wav or flac"),
    sweep_f_start: float = Query(default=20.0, ge=20.0, le=20000.0, description="Sweep start frequency in Hz"),
    sweep_f_end: float = Query(default=20000.0, ge=20.0, le=20000.0, description="Sweep end frequency in Hz"),
) -> Response:
    """
    Get the measurement audio file.
    
    Returns a WAV or FLAC file containing the measurement signal:
    - 0.0s - 0.5s: Sync Chirp (2kHz - 10kHz)
    - 0.5s - 2.5s: Silence
    - 2.5s - 12.5s: Measurement Sweep (configurable frequency range)
    - 12.5s - 14.5s: Silence (reverb tail)
    - 14.5s - 15.0s: Sync Chirp
    
    The chirp and sweep signals are stored for later use during analysis,
    keyed by the audio hash returned in X-Audio-Hash header.
    
    Query parameters:
    - sweep_f_start: Start frequency of the measurement sweep (default: 20 Hz)
    - sweep_f_end: End frequency of the measurement sweep (default: 20000 Hz)
    
    For smartphone measurements, use sweep_f_start=200 and sweep_f_end=12000
    to stay within the typical smartphone speaker/microphone range.
    """
    config = MeasurementSignalConfig(
        sample_rate=sample_rate,
        sweep_f_start=sweep_f_start,
        sweep_f_end=sweep_f_end,
    )
    
    if format.lower() == "flac":
        audio_format = "FLAC"
        media_type = "audio/flac"
        extension = "flac"
    else:
        audio_format = "WAV"
        media_type = "audio/wav"
        extension = "wav"
    
    audio_bytes = generate_measurement_audio_bytes(
        config=config,
        format=audio_format,
        subtype="PCM_16",
    )
    
    filename = f"measurement_signal.{extension}"
    if session_id:
        filename = f"measurement_{session_id}.{extension}"
    
    # Calculate SHA-256 hash of the audio bytes
    sha256_hash = hashlib.sha256(audio_bytes).hexdigest()

    # Store reference signals (chirp, sweep, full signal) for later alignment/deconvolution
    # This ensures we use the exact same signals that were played during measurement
    if not reference_store.has_reference(sha256_hash):
        try:
            # Generate the raw signals for storage
            full_signal, _ = generate_measurement_signal(config)
            
            # Generate the sync chirp
            fade_samples = int(config.fade_duration * config.sample_rate)
            chirp = generate_log_chirp(
                duration=config.sync_chirp_duration,
                f_start=config.sync_chirp_f_start,
                f_end=config.sync_chirp_f_end,
                sample_rate=config.sample_rate,
                amplitude=config.amplitude,
            )
            chirp = apply_fade(chirp, fade_samples)
            
            # Extract the sweep from the full signal
            timing = get_signal_timing(config)
            sweep_start = int(timing["sweep_start"] * config.sample_rate)
            sweep_end = int(timing["sweep_end"] * config.sample_rate)
            sweep = full_signal[sweep_start:sweep_end]
            
            # Store everything
            reference_store.store_reference(
                audio_hash=sha256_hash,
                sample_rate=config.sample_rate,
                config_dict=dataclasses.asdict(config),
                chirp=chirp,
                sweep=sweep,
                full_signal=full_signal,
            )
            logger.info(f"Stored reference signals for audio hash {sha256_hash[:16]}...")
        except Exception as e:
            logger.warning(f"Failed to store reference signals: {e}")

    # Save generated audio to disk for debugging
    try:
        debug_dir = pathlib.Path(settings.debug_dir)
        debug_dir.mkdir(parents=True, exist_ok=True)
        debug_file = debug_dir / filename
        with open(debug_file, "wb") as f:
            f.write(audio_bytes)
        logger.info(f"Saved debug audio to {debug_file}")
    except Exception as e:
        logger.warning(f"Failed to save debug audio: {e}")
    
    return Response(
        content=audio_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Duration-Seconds": str(config.total_duration),
            "X-Sample-Rate": str(config.sample_rate),
            "X-Audio-Hash": sha256_hash,
        },
    )


@router.get("/measurement/audio/info")
def get_measurement_audio_info(
    sample_rate: int = Query(default=48000, ge=8000, le=192000, description="Sample rate in Hz"),
    sweep_f_start: float = Query(default=20.0, ge=20.0, le=20000.0, description="Sweep start frequency in Hz"),
    sweep_f_end: float = Query(default=20000.0, ge=20.0, le=20000.0, description="Sweep end frequency in Hz"),
) -> dict:
    """
    Get timing information about the measurement signal.
    
    Returns the structure and timing of each segment in the measurement audio.
    Useful for clients to know when to start/stop recording and where the
    sync chirps are located.
    """
    config = MeasurementSignalConfig(
        sample_rate=sample_rate,
        sweep_f_start=sweep_f_start,
        sweep_f_end=sweep_f_end,
    )
    return get_signal_timing(config)
