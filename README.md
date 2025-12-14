# Sonalyze Backend

A microservices-based backend for the Sonalyze acoustic measurement and analysis application.

## Architecture Overview

The Sonalyze backend consists of five microservices that work together to provide acoustic measurement, analysis, and simulation capabilities:

```
                    ┌─────────────────────────────────────────────────┐
                    │                   Clients                        │
                    │            (Mobile/Web Apps)                     │
                    └─────────────────────┬───────────────────────────┘
                                          │
                                          │ WebSocket / HTTP
                                          ▼
                    ┌─────────────────────────────────────────────────┐
                    │                  Gateway                         │
                    │              (Port 8000)                         │
                    │   - WebSocket connection management              │
                    │   - Event routing                                │
                    │   - Rate limiting                                │
                    └─────────┬──────────────┬───────────────┬────────┘
                              │              │               │
              ┌───────────────┘              │               └───────────────┐
              │                              │                               │
              ▼                              ▼                               ▼
┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│         Lobby           │  │      Measurement        │  │       Simulation        │
│       (Port 8001)       │  │       (Port 8002)       │  │       (Port 8003)       │
│  - Lobby management     │  │  - Audio processing     │  │  - Room acoustics       │
│  - Participants         │  │  - Analysis jobs        │  │  - RIR generation       │
│  - Role assignment      │  │  - RT60, STI metrics    │  │  - Acoustic metrics     │
└───────────┬─────────────┘  └─────────────────────────┘  └─────────────────────────┘
            │
            ▼
┌─────────────────────────┐
│        Storage          │
│       (Port 8004)       │
│  - Persistent data      │
│  - PostgreSQL           │
│  - Alembic migrations   │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│       PostgreSQL        │
│       (Port 5432)       │
└─────────────────────────┘
```

## Microservices

### Gateway Service

**Purpose:** Entry point for all client connections. Handles WebSocket connections, message routing, and rate limiting.

**Features:**
- WebSocket connection management with device identification
- Event-based message routing to downstream services
- Rate limiting (configurable RPS and burst)
- Internal broadcast API for server-to-client messaging

**Events Routed:**
- `lobby.*`, `role.*` → Lobby Service
- `measurement.*`, `analysis.*` → Measurement Service
- `simulation.*` → Simulation Service

**Environment Variables:**
| Variable | Default | Description |
|----------|---------|-------------|
| `LOBBY_URL` | `http://lobby:8000` | Lobby service URL |
| `MEASUREMENT_URL` | `http://measurement:8000` | Measurement service URL |
| `SIMULATION_URL` | `http://simulation:8000` | Simulation service URL |
| `INTERNAL_AUTH_TOKEN` | - | Token for internal broadcast API |
| `MAX_MESSAGE_BYTES` | `65536` | Maximum message size |
| `RATE_LIMIT_RPS` | `10.0` | Rate limit (requests/second) |
| `RATE_LIMIT_BURST` | `20` | Rate limit burst capacity |
| `HTTP_TIMEOUT_SECONDS` | `10.0` | Upstream request timeout |

---

### Lobby Service

**Purpose:** Manages lobbies, participants, and role assignments for collaborative measurement sessions.

**Features:**
- Create and manage measurement lobbies
- Participant join/leave tracking
- Role assignment (microphone, speaker)
- Event log for lobby activity
- Measurement session state management

**API Endpoints:**
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/lobbies` | Create a new lobby |
| `POST` | `/lobbies/join` | Join a lobby by code |
| `GET` | `/lobbies/{lobby_id}` | Get lobby details |
| `POST` | `/lobbies/{lobby_id}/leave` | Leave a lobby |
| `POST` | `/lobbies/{lobby_id}/roles` | Assign participant role |
| `POST` | `/lobbies/{lobby_id}/start` | Start measurement |
| `GET` | `/lobbies/{lobby_id}/events` | Get lobby events |

**Gateway Events:**
- `lobby.create` - Create a new lobby
- `lobby.join` - Join a lobby (requires `code`)
- `lobby.leave` - Leave a lobby (requires `lobby_id`)
- `lobby.get` - Get lobby info (requires `lobby_id` or `code`)
- `lobby.start` - Start measurement session
- `role.assign` - Assign role to participant

**Environment Variables:**
| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./lobby.db` | Database connection string |
| `SERVICE_NAME` | `lobby` | Service identifier |

---

### Measurement Service

**Purpose:** Handles audio file processing, impulse response analysis, and acoustic metric calculations.

**Features:**
- Audio file upload and management
- Impulse response extraction via sweep deconvolution
- Acoustic metrics: RT60, EDT, C50, C80, D50, DRR
- Speech Transmission Index (STI) calculation
- Frequency response analysis

**API Endpoints:**
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/health` | Health check |
| `POST` | `/v1/jobs` | Create analysis job |
| `GET` | `/v1/jobs/{job_id}` | Get job details |
| `POST` | `/v1/jobs/{job_id}/uploads/{name}` | Upload audio file |
| `POST` | `/v1/jobs/{job_id}/analyze` | Run analysis |

**Gateway Events:**
- `measurement.create_job` - Create a new measurement job
- `measurement.get_job` - Get job details
- `analysis.run` - Run analysis on uploaded data

**Analysis Sources:**
- `impulse_response` - Direct IR file upload
- `sweep_deconvolution` - Extract IR from sweep recording

**Environment Variables:**
| Variable | Default | Description |
|----------|---------|-------------|
| `MEASUREMENT_DATA_DIR` | `/data` | Data storage directory |
| `MEASUREMENT_MAX_UPLOAD_MB` | `50` | Maximum upload size |
| `HOST` | `0.0.0.0` | Server host |
| `PORT` | `8000` | Server port |

---

### Simulation Service

**Purpose:** Performs room acoustics simulations using pyroomacoustics for RIR generation and metric prediction.

**Features:**
- Shoebox and polygon room geometry support
- Multi-source, multi-microphone configurations
- Wall material absorption/scattering coefficients
- Room impulse response (RIR) generation
- Acoustic metrics: RT60, EDT, C50, C80, D50, DRR, STI

**API Endpoints:**
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/simulate` | Run simulation |

**Gateway Events:**
- `simulation.run` - Run room acoustics simulation
- `simulation.health` - Check service health

**Room Types:**
- `shoebox` - Rectangular room with per-wall materials
- `polygon` - Arbitrary 2D polygon extruded to height

**Environment Variables:**
| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Server port |

---

### Storage Service

**Purpose:** Persistent data storage API with PostgreSQL backend and Alembic migrations.

**Features:**
- Device registration and management
- Lobby persistence
- Measurement data storage
- Analysis output storage
- Simulation job tracking

**API Endpoints (v1):**
| Resource | Operations |
|----------|------------|
| `/v1/devices` | CRUD |
| `/v1/lobbies` | CRUD + by-code lookup |
| `/v1/participants` | CRUD |
| `/v1/measurements` | CRUD |
| `/v1/analysis_outputs` | CRUD |
| `/v1/simulation_jobs` | CRUD |
| `/v1/simulation_results` | CRUD |

**Environment Variables:**
| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | - | PostgreSQL connection string (required) |
| `RUN_MIGRATIONS` | `true` | Run Alembic migrations on startup |
| `LOG_LEVEL` | `INFO` | Logging level |

---

## Requirements

### System Requirements
- Docker 20.10+ with Docker Compose v2
- 4GB+ RAM recommended
- 10GB+ disk space for data storage

### Per-Service Python Dependencies

#### Gateway
```
fastapi>=0.110
uvicorn[standard]>=0.27
httpx>=0.27
pydantic>=2.6
```

#### Lobby
```
fastapi==0.115.6
uvicorn[standard]==0.32.1
SQLAlchemy[asyncio]==2.0.36
asyncpg==0.30.0
aiosqlite==0.20.0
pydantic-settings==2.6.1
```

#### Measurement
```
fastapi==0.115.6
uvicorn[standard]==0.32.1
pydantic==2.10.3
pydantic-settings==2.6.1
numpy==2.1.3
scipy==1.14.1
soundfile==0.12.1
python-multipart==0.0.20
```

#### Simulation
```
fastapi==0.115.6
uvicorn[standard]==0.32.1
pydantic==2.10.3
numpy==1.26.4
scipy==1.11.4
pyroomacoustics==0.7.7
```

#### Storage
```
fastapi==0.115.6
uvicorn[standard]==0.32.1
pydantic==2.10.3
pydantic-settings==2.6.1
SQLAlchemy==2.0.36
asyncpg==0.30.0
psycopg2-binary==2.9.10
alembic==1.14.0
orjson==3.10.12
python-json-logger==2.0.7
```

---

## Getting Started

### Quick Start with Docker Compose

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd sonalyze_backend
   ```

2. **Start all services:**
   ```bash
   docker compose up -d
   ```

3. **Check service health:**
   ```bash
   # Gateway
   curl http://localhost:8000/healthz
   
   # Lobby
   curl http://localhost:8001/health
   
   # Measurement
   curl http://localhost:8002/v1/health
   
   # Simulation
   curl http://localhost:8003/health
   
   # Storage
   curl http://localhost:8004/healthz
   ```

4. **View logs:**
   ```bash
   docker compose logs -f
   ```

5. **Stop all services:**
   ```bash
   docker compose down
   ```

### Debugging With Fresh Containers

Use the following chain when you need to blow away every image layer, rebuild, and stream all logs right in the foreground (no `-d`). It turns on unbuffered Python output and asks any service that respects `LOG_LEVEL` to switch to verbose logging:

```bash
docker compose down --remove-orphans && \
DOCKER_BUILDKIT=1 docker compose build --no-cache && \
PYTHONUNBUFFERED=1 LOG_LEVEL=DEBUG docker compose up --force-recreate --remove-orphans
```

To laser-focus on a single microservice while the rest keep running, leave the stack up in another terminal (for example via `docker compose up -d`) and rerun just the service you care about with rebuilt layers and live logs:

```bash
PYTHONUNBUFFERED=1 LOG_LEVEL=DEBUG docker compose up --build --force-recreate --no-deps simulation
```

Swap `simulation` for any other service name (gateway, measurement, storage, etc.) to tail that component in isolation while the rest of the system keeps serving traffic as usual.

### Running Individual Services

Each service can be run independently for development:

```bash
# Gateway
cd gateway
pip install -r requirements.txt
uvicorn gateway.main:app --reload --port 8000

# Lobby (requires DATABASE_URL)
cd lobby
pip install -r requirements.txt
DATABASE_URL=sqlite+aiosqlite:///./lobby.db uvicorn main:app --app-dir src --reload --port 8001

# Measurement
cd measurement
pip install -r requirements.txt
python -m app.main

# Simulation
cd simulation
pip install -r requirements.txt
uvicorn sonalyze_simulation.main:app --reload --port 8003

# Storage (requires PostgreSQL)
cd storage
pip install -r requirements.txt
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/sonalyze uvicorn app.main:app --app-dir src --reload --port 8004
```

---

## WebSocket API

### Connection

Connect to the gateway WebSocket endpoint:
```
ws://localhost:8000/ws?device_id=<your-device-id>
```

Or connect without device_id and send an `identify` message:
```json
{
  "event": "identify",
  "request_id": "req-1",
  "data": {
    "device_id": "your-device-id"
  }
}
```

### Message Format

**Client → Server:**
```json
{
  "event": "lobby.create",
  "request_id": "optional-request-id",
  "data": {}
}
```

**Server → Client (Response):**
```json
{
  "type": "response",
  "event": "lobby.create",
  "request_id": "optional-request-id",
  "data": {
    "lobby_id": "...",
    "code": "ABC123"
  }
}
```

**Server → Client (Event):**
```json
{
  "type": "event",
  "event": "participant.joined",
  "data": {
    "device_id": "...",
    "lobby_id": "..."
  }
}
```

**Server → Client (Error):**
```json
{
  "type": "error",
  "event": "lobby.create",
  "request_id": "optional-request-id",
  "error": {
    "code": "error_code",
    "message": "Human readable message",
    "details": {}
  }
}
```

---

## Environment Variables

Create a `.env` file in the root directory for custom configuration:

```env
# Authentication
INTERNAL_AUTH_TOKEN=your-secure-token

# Database (for production)
POSTGRES_USER=sonalyze
POSTGRES_PASSWORD=your-secure-password
POSTGRES_DB=sonalyze

# Gateway settings
RATE_LIMIT_RPS=10.0
RATE_LIMIT_BURST=20
MAX_MESSAGE_BYTES=65536

# Measurement settings
MEASUREMENT_MAX_UPLOAD_MB=50
```

---

## Development

### Project Structure

```
sonalyze_backend/
├── docker-compose.yml      # Main orchestration file
├── README.md
├── gateway/                # Gateway service
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/gateway/
├── lobby/                  # Lobby service
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/
├── measurement/            # Measurement service
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/app/
├── simulation/             # Simulation service
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/sonalyze_simulation/
└── storage/                # Storage service
    ├── Dockerfile
    ├── requirements.txt
    └── src/
        ├── alembic/        # Database migrations
        └── app/
```

### Adding Database Migrations

```bash
cd storage/src
alembic revision -m "description"
# Edit the generated migration file
alembic upgrade head
```

---

## License

See [LICENSE](LICENSE) file for details.