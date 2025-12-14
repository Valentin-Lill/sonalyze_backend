# simulation/

Room-acoustics simulation microservice for Sonalyze.

- HTTP API (FastAPI)
- Runs `pyroomacoustics` to simulate RIRs
- Computes acoustic metrics (RT60, EDT, D50, C50/C80, DRR)

## Run (Docker)

```bash
docker build -t sonalyze-simulation ./simulation
docker run --rm -p 8000:8000 sonalyze-simulation
```

Health check:

```bash
curl http://localhost:8000/health
```

## Run (local)

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src uvicorn sonalyze_simulation.main:app --reload
```

## Simulate

```bash
curl -X POST http://localhost:8000/simulate \
  -H 'content-type: application/json' \
  -d '{
    "sample_rate_hz": 16000,
    "max_order": 12,
    "air_absorption": true,
    "rir_duration_s": 2.0,
    "include_rir": false,
    "room": {
      "type": "shoebox",
      "dimensions_m": [6.0, 4.0, 2.7],
      "default_material": {"absorption": 0.25, "scattering": 0.0},
      "wall_materials": {
        "floor": {"absorption": 0.05, "scattering": 0.0},
        "ceiling": {"absorption": 0.6, "scattering": 0.0}
      }
    },
    "sources": [{"id": "spk1", "position_m": [1.0, 1.0, 1.2]}],
    "microphones": [{"id": "mic1", "position_m": [4.0, 2.0, 1.2]}]
  }'
```

Notes:
- `furniture` is accepted in the request schema but not yet modeled (currently ignored).
- `sti` is returned only if your `pyroomacoustics` build exposes an STI helper; otherwise it is `null` with a warning.
