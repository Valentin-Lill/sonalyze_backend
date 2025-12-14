# measurement service

Receives uploaded measurement signals (impulse responses or sweep recordings) and computes room-acoustic metrics.

## Run (docker)

```bash
docker build -t sonalyze-measurement ./measurement

docker run --rm -p 8002:8000 \
  -e MEASUREMENT_DATA_DIR=/data \
  -v $(pwd)/.measurement-data:/data \
  sonalyze-measurement
```

OpenAPI docs: `http://localhost:8002/docs`

## Quick test

Create a job:

```bash
curl -sS -X POST http://localhost:8002/v1/jobs \
  -H 'content-type: application/json' \
  -d '{"map": {"room": {"vertices": [[0,0],[5,0],[5,4],[0,4]], "height_m": 2.6}, "sources": [{"id": "spk1", "position": [2.5, 2.0, 1.2]}], "receivers": [{"id": "mic1", "position": [1.0, 1.0, 1.2]}]}}'
```

Upload an impulse response WAV:

```bash
curl -sS -X POST http://localhost:8002/v1/jobs/<JOB_ID>/uploads/impulse_response \
  -F file=@ir.wav
```

Run analysis:

```bash
curl -sS -X POST http://localhost:8002/v1/jobs/<JOB_ID>/analyze \
  -H 'content-type: application/json' \
  -d '{"source": "impulse_response"}'
```
