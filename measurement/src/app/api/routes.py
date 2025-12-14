from __future__ import annotations

import pathlib
import re
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.analysis.io import normalize_peak, read_audio_mono
from app.analysis.metrics import (
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

    results = {
        "samplerate_hz": fs,
        "rt": rt_metrics_from_ir(ir, fs),
        "clarity": clarity_definition_metrics(ir, fs),
        "drr": drr_metrics(ir, fs),
        "quality": snr_quality(ir),
        "frequency_response": freq_response_summary(ir, fs),
        "sti": sti_from_impulse_response(ir, fs),
    }

    store.write_json(job_dir / "results" / "analysis.json", results)

    return AnalyzeResponse(job_id=job_id, results=results)
