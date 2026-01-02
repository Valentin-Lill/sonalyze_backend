# Simulation Service

The Simulation Service provides **acoustic modeling capabilities** for the Sonalyze backend. It simulates room acoustics using the Image Source Method (ISM) or Ray Tracing, calculating metrics like RT60, clarity, and STI for virtual room configurations.

## Summary

The Simulation service handles:
- **Room Acoustics Simulation**: Model sound propagation in shoebox or polygon rooms
- **Material Library**: Database of acoustic materials with absorption/scattering coefficients
- **Reference Profiles**: Standard room profiles (IEC listening rooms, classrooms, etc.)
- **Multiple Simulation Methods**: Image Source Method (fast) or Ray Tracing (accurate with furniture)
- **Metric Calculation**: RT60, EDT, C50, C80, DRR, STI for source-receiver pairs

## Architecture Role

```
┌─────────────────────────────────────────────────────────────────┐
│                         GATEWAY                                  │
│            (HTTP Proxy + Gateway Events)                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SIMULATION SERVICE                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ ISM Simulator   │  │ Ray Tracer      │  │ Material        │  │
│  │ (pyroomacoustics)│  │ (3D Bounces)    │  │ Database        │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  │
│           │                    │                    │            │
│           └────────────────────┴────────────────────┘            │
│                                │                                 │
│                       ┌────────┴────────┐                        │
│                       │ Metric Engine   │                        │
│                       │ (RT60, C50, STI)│                        │
│                       └─────────────────┘                        │
└──────────────────────────────────────────────────────────────────┘
```

## Features

### Simulation Methods

#### Image Source Method (ISM)
- Fast geometric acoustics simulation
- Accurate for shoebox rooms without furniture
- Uses pyroomacoustics library
- Supports up to `max_order` reflections

#### Ray Tracing
- More accurate for complex geometries
- Supports furniture and obstacles
- 3D bounce simulation
- Configurable bounce count (default: 3, max: 30)

### Room Types

#### Shoebox Room
```json
{
  "type": "shoebox",
  "dimensions_m": [5.0, 4.0, 2.5],
  "default_material": {"absorption": 0.2, "scattering": 0.1},
  "wall_materials": {
    "floor": {"absorption": 0.1},
    "ceiling": {"absorption": 0.5}
  }
}
```

#### Polygon Room
```json
{
  "type": "polygon",
  "corners_m": [[0,0], [5,0], [5,4], [0,4]],
  "height_m": 2.5,
  "wall_material": {"absorption": 0.2},
  "floor_material": {"absorption": 0.1},
  "ceiling_material": {"absorption": 0.5}
}
```

### Furniture Support
```json
{
  "type": "box",
  "id": "desk_1",
  "min_m": [1.0, 1.0, 0.0],
  "max_m": [2.0, 1.5, 0.75],
  "material": {"absorption": 0.3, "scattering": 0.2}
}
```

## HTTP Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/simulate` | Run acoustic simulation |
| `GET` | `/reference-profiles` | Get standard room profiles |
| `GET` | `/materials` | Get available materials |

### Simulation Request

```json
{
  "room": {
    "type": "shoebox",
    "dimensions_m": [5.0, 4.0, 2.5],
    "default_material": {"absorption": 0.2}
  },
  "sources": [
    {"id": "speaker_1", "position_m": [2.5, 0.5, 1.2]}
  ],
  "microphones": [
    {"id": "mic_1", "position_m": [2.5, 3.5, 1.2]}
  ],
  "furniture": [],
  "sample_rate_hz": 16000,
  "max_order": 12,
  "air_absorption": true,
  "rir_duration_s": 2.0,
  "include_rir": false,
  "use_raytracing": false,
  "raytracing_bounces": 3
}
```

### Simulation Response

```json
{
  "sample_rate_hz": 16000,
  "pairs": [
    {
      "source_id": "speaker_1",
      "microphone_id": "mic_1",
      "metrics": {
        "rt60_s": 0.45,
        "edt_s": 0.38,
        "d50": 0.65,
        "c50_db": 2.8,
        "c80_db": 6.2,
        "drr_db": 3.1,
        "sti": 0.72,
        "sti_method": "mtf"
      },
      "rir": null,
      "warnings": []
    }
  ],
  "warnings": []
}
```

## Gateway Events

Events received via `POST /gateway/handle`:

| Event | Description | Data |
|-------|-------------|------|
| `simulation.run` | Run simulation | Same as `/simulate` body |
| `simulation.health` | Health check | (empty) |

## Reference Profiles

The service provides standard acoustic profiles for comparison:

| Profile | Description | Target RT60 |
|---------|-------------|-------------|
| `iec_listening_room` | IEC 60268-13 listening room | 0.3-0.4s |
| `classroom_good` | Well-treated classroom | 0.4-0.6s |
| `classroom_typical` | Typical untreated classroom | 0.8-1.2s |
| `lecture_hall` | Large lecture hall | 0.8-1.0s |
| `concert_hall` | Concert hall acoustics | 1.8-2.2s |

## Materials Database

Available acoustic materials with absorption and scattering coefficients:

| Material | Absorption | Scattering |
|----------|------------|------------|
| `concrete` | 0.02 | 0.05 |
| `brick` | 0.03 | 0.10 |
| `plaster` | 0.05 | 0.05 |
| `glass` | 0.03 | 0.02 |
| `wood_panel` | 0.10 | 0.15 |
| `carpet` | 0.30 | 0.20 |
| `curtain_heavy` | 0.50 | 0.40 |
| `acoustic_panel` | 0.80 | 0.10 |

## Simulation Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `sample_rate_hz` | `16000` | Sample rate for RIR |
| `max_order` | `12` | Maximum reflection order (ISM) |
| `air_absorption` | `true` | Include air absorption |
| `rir_duration_s` | `2.0` | Trim RIR to this duration |
| `include_rir` | `false` | Include raw RIR in response |
| `use_raytracing` | `false` | Force ray tracing mode |
| `raytracing_bounces` | `3` | Bounces for ray tracing (max: 30) |

## Acoustic Metrics

| Metric | Description | Unit |
|--------|-------------|------|
| **RT60** | Reverberation time (60dB decay) | seconds |
| **EDT** | Early decay time | seconds |
| **D50** | Definition (50ms energy ratio) | 0-1 |
| **C50** | Clarity for speech (50ms) | dB |
| **C80** | Clarity for music (80ms) | dB |
| **DRR** | Direct-to-reverberant ratio | dB |
| **STI** | Speech transmission index | 0-1 |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Server port |

## Internal Packages

| Module | Description |
|--------|-------------|
| `sonalyze_simulation.main` | FastAPI application |
| `sonalyze_simulation.routes` | HTTP API endpoints |
| `sonalyze_simulation.gateway_handler` | Gateway event handler |
| `sonalyze_simulation.schemas` | Pydantic models for requests/responses |
| `sonalyze_simulation.simulate` | ISM simulation orchestration |
| `sonalyze_simulation.simulate_raytracing` | Ray tracing simulation |
| `sonalyze_simulation.materials` | Material database |
| `sonalyze_simulation.reference_profiles` | Standard room profiles |
| `sonalyze_simulation.payload_adapter` | Request normalization |

### Acoustics Subpackage

| Module | Description |
|--------|-------------|
| `sonalyze_simulation.acoustics.pyroom` | pyroomacoustics room builder |
| `sonalyze_simulation.acoustics.metrics` | Acoustic metric calculations |

## Dependencies

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
pydantic==2.10.3
numpy==1.26.4
scipy==1.11.4
pyroomacoustics==0.7.7
```

## Running Locally

```bash
cd simulation
pip install -r requirements.txt

# Start the server
uvicorn sonalyze_simulation.main:app --reload --port 8003
```

## Docker

```bash
docker build -t sonalyze-simulation .
docker run -p 8003:8000 sonalyze-simulation
```

## Usage Example

### Via HTTP API
```bash
curl -X POST http://localhost:8003/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "room": {
      "type": "shoebox",
      "dimensions_m": [5.0, 4.0, 2.5],
      "default_material": {"absorption": 0.2}
    },
    "sources": [{"id": "s1", "position_m": [2.5, 0.5, 1.2]}],
    "microphones": [{"id": "m1", "position_m": [2.5, 3.5, 1.2]}]
  }'
```

### Via WebSocket (through Gateway)
```json
{
  "event": "simulation.run",
  "request_id": "req-123",
  "data": {
    "room": {"type": "shoebox", "dimensions_m": [5.0, 4.0, 2.5]},
    "sources": [{"id": "s1", "position_m": [2.5, 0.5, 1.2]}],
    "microphones": [{"id": "m1", "position_m": [2.5, 3.5, 1.2]}]
  }
}
```
