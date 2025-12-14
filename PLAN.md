# Sonalyze Backend Plan (Python)

## Goal
Sonalyze enables **acoustic measurements** and **room-acoustics simulations** using normal consumer hardware (smartphone speakers + microphones). The backend supports:
- Real-time coordination of multi-device measurements ("lobbies")
- Collection + analysis of measurement data
- Running simulations (via **pyroomacoustics**)
- WebSocket-based real-time communication with the frontend

## High-level requirements (from product constraints)
- Microservices architecture
- Each microservice is dockerized
- Each microservice lives in its own folder at repo root
- WebSockets are used for frontend connections
- Data stored in Postgres

---

## Proposed microservices

### 1) `gateway/` (WebSocket API + edge)
**Purpose:** Single entrypoint for the frontend.

**Responsibilities**
- Accept WebSocket connections from clients
- Identify clients (e.g., device id)
- Route events/commands to internal services (lobby, measurement, simulation)
- Fan-out real-time updates to connected clients
- Enforce rate limiting / message size limits

**Tech suggestions**
- Python: FastAPI + `uvicorn` + WebSockets, or `websockets` library
- Internal comms: HTTP (FastAPI)

**Key APIs (WebSocket events)**
- `lobby.create`, `lobby.join`, `lobby.leave`
- `role.assign`, `role.update`
- `measurement.start`, `measurement.stop`, `measurement.upload_chunk`, `measurement.status`
- `analysis.request`, `analysis.progress`, `analysis.result`
- `simulation.request`, `simulation.progress`, `simulation.result`

---

### 2) `lobby/` (Sessions + roles)
**Purpose:** Create and manage “lobbies” for coordinated measurement sessions.

**Responsibilities**
- Create/join/leave lobbies
- Manage participants and roles (speaker / microphone / observer)
- Orchestrate the measurement workflow state machine
- Produce events for state changes (participant joined, role assigned, measurement started…)

**Data stored**
- Lobby metadata (creator, code, state)
- Participants (device id, role, status)

**Notes**
- Keep “real-time” logic in this service (domain source of truth), while `gateway/` focuses on connectivity.

---

### 3) `measurement/` (Ingest + analysis)
**Purpose:** Receive measurement data and compute acoustic metrics.

**Responsibilities**
- Accept uploaded measurement signals (audio samples, sweeps, impulse responses)
- Validate + normalize data (sample rates, formats)
- Run analysis pipelines (e.g., impulse response extraction, RT60 estimation, frequency response)
- Persist raw + derived results via storage service

**Potential compute tasks**
- Deconvolution / impulse response extraction
- RT60 (multiple bands), EDT, clarity (C50/C80), DRR
- SNR checks / quality scoring

---

### 4) `simulation/` (pyroomacoustics)
**Purpose:** Run room-acoustics simulations (CPU-heavy) and return results.

**Responsibilities**
- Provide a simulation API (room geometry, materials, source/receiver positions)
- Run pyroomacoustics simulations
- Return simulated impulse responses / acoustic indicators

**Notes**
- Treat as async work (queue) if simulations are expensive.

---

### 5) `storage/` (DB access layer)
**Purpose:** Central service owning Postgres schema and persistence operations.

**Why separate?**
- Enforces a single DB owner (schema + migrations + access patterns)
- Reduces direct coupling and credential sprawl

**Responsibilities**
- Own Postgres schema + migrations
- Provide CRUD APIs for:
  - devices
  - lobbies, participants
  - measurements (raw blobs references), analysis outputs
  - simulation jobs + results

**Alternatives**
- If you prefer more autonomy per service, each service can own its own schema (same Postgres instance) and connect directly. That’s simpler early, but you must manage migrations and credentials per service.

