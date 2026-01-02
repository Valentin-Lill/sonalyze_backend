# Sonalyze Backend

A **microservices-based backend** for the Sonalyze acoustic measurement and room analysis application. The system enables multi-device synchronized acoustic measurements, room impulse response analysis, and acoustic simulation.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Microservices](#microservices)
- [Getting Started](#getting-started)
- [WebSocket Protocol](#websocket-protocol)
- [Environment Variables](#environment-variables)
- [Development](#development)
- [License](#license)

---

## Overview

Sonalyze is a platform for measuring and analyzing room acoustics. The backend supports:

- **Multi-device measurement sessions**: Coordinate multiple smartphones acting as speakers and microphones
- **Real-time communication**: WebSocket-based protocol for synchronized measurements
- **Acoustic analysis**: Compute RT60, EDT, C50/C80, DRR, STI from recordings
- **Room simulation**: Predict acoustic properties using pyroomacoustics
- **Persistent storage**: Track devices, lobbies, measurements, and results

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                 CLIENTS                                          │
│                        (Flutter Mobile App, Web Browser)                         │
└─────────────────────────────────────┬───────────────────────────────────────────┘
                                      │
                                      │ WebSocket + HTTP
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                 GATEWAY                                          │
│                              (Port 8000)                                         │
│                                                                                  │
│  ┌─────────────────────┐  ┌────────────────────┐  ┌─────────────────────────┐   │
│  │   WebSocket Hub     │  │    HTTP Proxy      │  │   Internal Broadcast    │   │
│  │   /ws               │  │    /v1/*           │  │   /internal/broadcast   │   │
│  │                     │  │                    │  │                         │   │
│  │ • Device tracking   │  │ • Measurement API  │  │ • Push events to        │   │
│  │ • Rate limiting     │  │ • Job uploads      │  │   connected clients     │   │
│  │ • Event routing     │  │ • Simulation API   │  │                         │   │
│  └──────────┬──────────┘  └─────────┬──────────┘  └────────────┬────────────┘   │
│             │                       │                          │                 │
│             └───────────────────────┴──────────────────────────┘                 │
│                                     │                                            │
│                              Event Router                                        │
└─────────────────────────────────────┬───────────────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
          ▼                           ▼                           ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│       LOBBY         │   │    MEASUREMENT      │   │     SIMULATION      │
│    (Port 8001)      │   │     (Port 8002)     │   │     (Port 8003)     │
│                     │   │                     │   │                     │
│ • Lobby CRUD        │   │ • Audio generation  │   │ • Room acoustics    │
│ • Participant mgmt  │   │ • Job management    │   │ • ISM / Ray tracing │
│ • Role assignment   │   │ • File uploads      │   │ • Material database │
│ • 11-step protocol  │   │ • Acoustic analysis │   │ • Reference profiles│
│ • Real-time events  │   │ • Reference store   │   │                     │
│                     │   │                     │   │                     │
│ [PostgreSQL/SQLite] │   │ [File Storage]      │   │ [Stateless]         │
└──────────┬──────────┘   └─────────────────────┘   └─────────────────────┘
           │
           │ Broadcasts
           ▼
    ┌─────────────┐
    │   Gateway   │
    │  (Clients)  │
    └─────────────┘
                          
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                 STORAGE                                          │
│                              (Port 8004)                                         │
│                                                                                  │
│  Persistent REST API for all domain entities                                    │
│                                                                                  │
│  /v1/devices  /v1/lobbies  /v1/participants  /v1/measurements                   │
│  /v1/analysis-outputs  /v1/simulation-jobs  /v1/simulation-results              │
│                                                                                  │
│                          ┌─────────────────┐                                     │
│                          │   PostgreSQL    │                                     │
│                          │   + Alembic     │                                     │
│                          └─────────────────┘                                     │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Service Communication Flow

```
┌──────────┐     WebSocket      ┌─────────┐     HTTP POST      ┌─────────────┐
│  Client  │ ─────────────────► │ Gateway │ ─────────────────► │ Lobby/Meas/ │
│          │                    │         │  /gateway/handle   │ Simulation  │
│          │ ◄───────────────── │         │ ◄───────────────── │             │
└──────────┘   Response/Event   └────┬────┘     Response       └─────────────┘
                                     │
                                     │ POST /internal/broadcast
                                     │ (from services)
                                     ▼
                              ┌─────────────┐
                              │ Push events │
                              │ to clients  │
                              └─────────────┘
```

---

## Microservices

| Service | Port | Description | Database |
|---------|------|-------------|----------|
| **Gateway** | 8000 | WebSocket hub, HTTP proxy, event router | None |
| **Lobby** | 8001 | Lobby management, measurement coordination | PostgreSQL |
| **Measurement** | 8002 | Audio generation, analysis, job storage | File system |
| **Simulation** | 8003 | Room acoustics simulation | None |
| **Storage** | 8004 | Persistent data API | PostgreSQL |

### Gateway Service

The **single entry point** for all client connections.

| Feature | Description |
|---------|-------------|
| WebSocket | Device identification, rate limiting, message routing |
| HTTP Proxy | Forwards `/v1/measurement/*`, `/v1/jobs/*`, `/v1/simulation/*` |
| Broadcast API | Push events to connected clients by device ID |

**Event Routing:**
- `lobby.*`, `role.*` → Lobby Service
- `measurement.create_session`, `measurement.start_speaker`, etc. → Lobby (stateful)
- `measurement.create_job`, `analysis.run` → Measurement (stateless)
- `simulation.*` → Simulation Service

[📖 Full Documentation](gateway/README.md)

---

### Lobby Service

Manages **lobbies** and coordinates **synchronized multi-device measurements**.

| Feature | Description |
|---------|-------------|
| Lobby CRUD | Create/join/leave with unique 6-char codes |
| Participants | Track devices and their speaker/microphone roles |
| Measurement Protocol | 11-step synchronized measurement coordination |
| Broadcasts | Push lobby updates to all participants |

**Key Events:**
- `lobby.create`, `lobby.join`, `lobby.leave`
- `role.assign` (speaker/microphone)
- `measurement.create_session`, `measurement.ready`, `measurement.playback_complete`

[📖 Full Documentation](lobby/README.md)

---

### Measurement Service

Handles **audio signal generation** and **acoustic analysis**.

| Feature | Description |
|---------|-------------|
| Audio Generation | Logarithmic sine sweep with sync chirps |
| Job Management | Create jobs, upload files, run analysis |
| Analysis | RT60, EDT, C50/C80, DRR, STI calculation |
| Alignment | Chirp detection for recording alignment |

**Key Endpoints:**
- `GET /v1/measurement/audio` - Download measurement signal
- `POST /v1/jobs/{id}/uploads/{name}` - Upload recording
- `POST /v1/jobs/{id}/analyze` - Run analysis

[📖 Full Documentation](measurement/README.md)

---

### Simulation Service

Performs **room acoustics simulation** using pyroomacoustics.

| Feature | Description |
|---------|-------------|
| Room Types | Shoebox (rectangular) or polygon geometry |
| Simulation Methods | Image Source Method (fast) or Ray Tracing (accurate) |
| Materials | Database of absorption/scattering coefficients |
| Output | RT60, EDT, C50/C80, DRR, STI for each source-receiver pair |

**Key Endpoints:**
- `POST /simulate` - Run room simulation
- `GET /materials` - Get available materials
- `GET /reference-profiles` - Get standard room profiles

[📖 Full Documentation](simulation/README.md)

---

### Storage Service

**Persistent data layer** with PostgreSQL backend.

| Entity | Description |
|--------|-------------|
| Devices | Registered client devices |
| Lobbies | Measurement session containers |
| Participants | Device-lobby associations |
| Measurements | Raw measurement metadata |
| Analysis Outputs | Computed acoustic metrics |
| Simulation Jobs/Results | Simulation requests and outputs |

**All endpoints:** `GET`, `POST`, `PATCH`, `DELETE` for CRUD operations.

[📖 Full Documentation](storage/README.md)

---

## Getting Started

### Prerequisites

- **Docker** 20.10+ with Docker Compose v2
- **4GB+ RAM** recommended
- **10GB+ disk** for measurement data

### Quick Start with Docker Compose

```bash
# Clone the repository
git clone <repository-url>
cd sonalyze_backend

# Start all services
docker compose up -d

# Check health
curl http://localhost:8000/healthz  # Gateway
curl http://localhost:8001/health   # Lobby (via internal network)

# View logs
docker compose logs -f

# Stop all services
docker compose down
```

### Service Ports

| Service | Internal Port | External Port |
|---------|---------------|---------------|
| Gateway | 8000 | **8000** (exposed) |
| Lobby | 8000 | - |
| Measurement | 8000 | - |
| Simulation | 8000 | - |
| Storage | 8000 | - |
| PostgreSQL | 5432 | - |
| PostgreSQL (Lobby) | 5432 | - |

> **Note:** Only the Gateway is exposed externally. All other services communicate via the Docker network.

### Running Individual Services (Development)

```bash
# Gateway
cd gateway
pip install -r requirements.txt
uvicorn gateway.main:app --reload --port 8000

# Lobby (with SQLite for dev)
cd lobby
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8001

# Measurement
cd measurement
pip install -r requirements.txt
MEASUREMENT_DATA_DIR=./data uvicorn app.main:app --reload --port 8002

# Simulation
cd simulation
pip install -r requirements.txt
uvicorn sonalyze_simulation.main:app --reload --port 8003

# Storage (requires PostgreSQL)
cd storage
pip install -r requirements.txt
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/sonalyze \
uvicorn app.main:app --app-dir src --reload --port 8004
```

### Debug Mode

For debugging with fresh containers and verbose logging:

```bash
docker compose down --remove-orphans && \
DOCKER_BUILDKIT=1 docker compose build --no-cache && \
PYTHONUNBUFFERED=1 LOG_LEVEL=DEBUG docker compose up --force-recreate --remove-orphans
```

To rebuild and restart a single service:

```bash
PYTHONUNBUFFERED=1 LOG_LEVEL=DEBUG docker compose up --build --force-recreate --no-deps simulation
```

---

## WebSocket Protocol

### Connection

```javascript
// Connect with device_id
const ws = new WebSocket('ws://localhost:8000/ws?device_id=my-device-123');

// Or connect and identify
const ws = new WebSocket('ws://localhost:8000/ws');
ws.send(JSON.stringify({
  event: 'identify',
  request_id: 'req-1',
  data: { device_id: 'my-device-123' }
}));
```

### Message Format

**Client → Server:**
```json
{
  "event": "lobby.create",
  "request_id": "req-123",
  "data": {}
}
```

**Server → Client (Response):**
```json
{
  "type": "response",
  "event": "lobby.create",
  "request_id": "req-123",
  "data": {
    "lobby_id": "abc-def",
    "code": "ABC123",
    "state": "open"
  }
}
```

**Server → Client (Push Event):**
```json
{
  "type": "event",
  "event": "lobby.updated",
  "data": {
    "type": "participant_joined",
    "device_id": "other-device",
    "lobby_id": "abc-def"
  }
}
```

**Server → Client (Error):**
```json
{
  "type": "error",
  "event": "lobby.create",
  "request_id": "req-123",
  "error": {
    "code": "bad_request",
    "message": "Missing required field"
  }
}
```

### Event Reference

| Event | Service | Description |
|-------|---------|-------------|
| `identify` | Gateway | Identify device |
| `lobby.create` | Lobby | Create lobby |
| `lobby.join` | Lobby | Join by code |
| `lobby.leave` | Lobby | Leave lobby |
| `lobby.get` | Lobby | Get lobby info |
| `lobby.start` | Lobby | Start measurement |
| `role.assign` | Lobby | Assign speaker/mic role |
| `measurement.create_session` | Lobby | Create measurement session |
| `measurement.start_speaker` | Lobby | Start speaker cycle |
| `measurement.ready` | Lobby | Signal client ready |
| `measurement.speaker_audio_ready` | Lobby | Speaker has audio |
| `measurement.recording_started` | Lobby | Mic is recording |
| `measurement.playback_complete` | Lobby | Speaker finished |
| `measurement.recording_uploaded` | Lobby | Mic uploaded recording |
| `measurement.create_job` | Measurement | Create analysis job |
| `measurement.get_job` | Measurement | Get job data |
| `analysis.run` | Measurement | Run acoustic analysis |
| `simulation.run` | Simulation | Run room simulation |

---

## Environment Variables

### docker-compose.yml Environment

```yaml
# Gateway
LOBBY_URL: http://lobby:8000
MEASUREMENT_URL: http://measurement:8000
SIMULATION_URL: http://simulation:8000
INTERNAL_AUTH_TOKEN: ${INTERNAL_AUTH_TOKEN:-sonalyze_internal_token}
MAX_MESSAGE_BYTES: 65536
RATE_LIMIT_RPS: 10.0
RATE_LIMIT_BURST: 20
HTTP_TIMEOUT_SECONDS: 30.0

# Lobby
DATABASE_URL: postgresql+asyncpg://lobby:lobby_secret@postgres-lobby:5432/lobby
GATEWAY_URL: http://gateway:8000
MEASUREMENT_URL: http://measurement:8000
INTERNAL_AUTH_TOKEN: ${INTERNAL_AUTH_TOKEN:-sonalyze_internal_token}

# Measurement
MEASUREMENT_DATA_DIR: /data
MEASUREMENT_MAX_UPLOAD_MB: 50

# Storage
DATABASE_URL: postgresql+asyncpg://sonalyze:sonalyze_secret@postgres:5432/sonalyze
RUN_MIGRATIONS: "true"
LOG_LEVEL: INFO
```

### Custom .env File

Create a `.env` file in the project root:

```env
# Security
INTERNAL_AUTH_TOKEN=your-secure-random-token

# PostgreSQL (Storage)
POSTGRES_USER=sonalyze
POSTGRES_PASSWORD=your-secure-password
POSTGRES_DB=sonalyze

# PostgreSQL (Lobby)
POSTGRES_LOBBY_USER=lobby
POSTGRES_LOBBY_PASSWORD=your-secure-password
POSTGRES_LOBBY_DB=lobby
```

---

## Development

### Project Structure

```
sonalyze_backend/
├── docker-compose.yml          # Service orchestration
├── README.md                   # This file
├── LICENSE
├── PLAN.md
│
├── gateway/                    # Gateway Service
│   ├── Dockerfile
│   ├── README.md
│   ├── requirements.txt
│   └── src/gateway/
│       ├── main.py             # FastAPI app, WebSocket, HTTP proxy
│       ├── router.py           # Event routing logic
│       ├── connection_manager.py
│       ├── config.py
│       ├── models.py
│       ├── http_client.py
│       └── rate_limit.py
│
├── lobby/                      # Lobby Service
│   ├── Dockerfile
│   ├── README.md
│   ├── requirements.txt
│   └── src/
│       ├── main.py             # FastAPI app, HTTP endpoints
│       ├── gateway_handler.py  # WebSocket event handling
│       ├── service.py          # Business logic
│       ├── measurement_coordinator.py  # 11-step protocol
│       ├── broadcast.py        # Gateway broadcast client
│       ├── models.py           # SQLAlchemy models
│       ├── schemas.py          # Pydantic schemas
│       ├── db.py
│       └── settings.py
│
├── measurement/                # Measurement Service
│   ├── Dockerfile
│   ├── README.md
│   ├── requirements.txt
│   ├── debug_audio/            # Debug audio files
│   └── src/app/
│       ├── main.py
│       ├── api/routes.py       # HTTP endpoints
│       ├── gateway_handler.py  # WebSocket event handling
│       ├── storage.py          # Job file storage
│       ├── reference_store.py  # Signal reference storage
│       ├── models.py
│       ├── settings.py
│       └── analysis/           # Audio processing
│           ├── audio_generator.py
│           ├── alignment.py
│           ├── metrics.py
│           ├── sti.py
│           └── io.py
│
├── simulation/                 # Simulation Service
│   ├── Dockerfile
│   ├── README.md
│   ├── requirements.txt
│   └── src/sonalyze_simulation/
│       ├── main.py
│       ├── routes.py           # HTTP endpoints
│       ├── gateway_handler.py  # WebSocket event handling
│       ├── schemas.py
│       ├── simulate.py         # ISM simulation
│       ├── simulate_raytracing.py
│       ├── materials.py
│       ├── reference_profiles.py
│       ├── payload_adapter.py
│       └── acoustics/          # Acoustic calculations
│           ├── pyroom.py
│           └── metrics.py
│
├── storage/                    # Storage Service
│   ├── Dockerfile
│   ├── README.md
│   ├── requirements.txt
│   └── src/
│       ├── alembic/            # Database migrations
│       ├── alembic.ini
│       ├── entrypoint.sh
│       └── app/
│           ├── main.py
│           ├── db.py
│           ├── models.py
│           ├── schemas.py
│           ├── settings.py
│           ├── http_errors.py
│           ├── utils.py
│           └── routers/        # REST API endpoints
│               ├── devices.py
│               ├── lobbies.py
│               ├── participants.py
│               ├── measurements.py
│               ├── analysis_outputs.py
│               ├── simulation_jobs.py
│               └── simulation_results.py
│
└── measurement_data/           # Persistent measurement data (volume)
```

### Database Migrations (Storage)

```bash
cd storage/src

# Generate migration
alembic revision --autogenerate -m "Add new column"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

### Testing

```bash
# Run all service tests
docker compose exec lobby pytest
docker compose exec measurement pytest
docker compose exec simulation pytest
docker compose exec storage pytest
```

---

## API Quick Reference

### Create a Measurement Session (Full Flow)

```bash
# 1. Connect WebSocket and create lobby
ws://localhost:8000/ws?device_id=admin-device
{"event": "lobby.create", "request_id": "1", "data": {}}
# Response: {"type": "response", "event": "lobby.create", "data": {"lobby_id": "...", "code": "ABC123"}}

# 2. Others join the lobby
{"event": "lobby.join", "request_id": "2", "data": {"code": "ABC123"}}

# 3. Assign roles
{"event": "role.assign", "request_id": "3", "data": {
  "lobby_id": "...",
  "target_device_id": "speaker-device",
  "role": "speaker",
  "role_slot_id": "speaker_1"
}}

# 4. Create measurement job
{"event": "measurement.create_job", "request_id": "4", "data": {
  "map": {"room": {"vertices": [[0,0],[5,0],[5,4],[0,4]], "height_m": 2.5}},
  "meta": {}
}}
# Response: {"data": {"job_id": "..."}}

# 5. Create measurement session
{"event": "measurement.create_session", "request_id": "5", "data": {
  "job_id": "...",
  "lobby_id": "...",
  "speakers": [{"device_id": "speaker-device", "slot_id": "speaker_1"}],
  "microphones": [{"device_id": "mic-device", "slot_id": "mic_1"}]
}}

# 6. Start measurement
{"event": "measurement.start_speaker", "request_id": "6", "data": {"session_id": "..."}}
# ... 11-step protocol proceeds automatically
```

### Run Simulation

```bash
curl -X POST http://localhost:8000/v1/simulation/simulate \
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

### Get Measurement Audio

```bash
curl "http://localhost:8000/v1/measurement/audio?sample_rate=48000" -o measurement.wav
```

---

## License

See [LICENSE](LICENSE) file for details.