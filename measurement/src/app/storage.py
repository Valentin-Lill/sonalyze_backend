from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LocalJobStore:
    root_dir: pathlib.Path

    def job_dir(self, job_id: str) -> pathlib.Path:
        return self.root_dir / job_id

    def ensure_job(self, job_id: str) -> pathlib.Path:
        job_dir = self.job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "uploads").mkdir(exist_ok=True)
        (job_dir / "results").mkdir(exist_ok=True)
        return job_dir

    def write_json(self, path: pathlib.Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        os.replace(tmp_path, path)

    def read_json(self, path: pathlib.Path) -> Any:
        return json.loads(path.read_text())

    def save_upload_bytes(self, job_id: str, name: str, content: bytes) -> pathlib.Path:
        job_dir = self.ensure_job(job_id)
        path = job_dir / "uploads" / name
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_bytes(content)
        os.replace(tmp_path, path)
        return path

    def save_upload_stream(self, job_id: str, name: str, fileobj) -> pathlib.Path:
        job_dir = self.ensure_job(job_id)
        path = job_dir / "uploads" / name
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("wb") as f:
            while True:
                chunk = fileobj.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        os.replace(tmp_path, path)
        return path
