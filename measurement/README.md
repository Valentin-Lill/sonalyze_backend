# Measurement Service

The Measurement Service is the **computational engine** of the Sonalyze backend. It handles generation of measurement audio signals, storage of measurement jobs, and performs acoustic analysis on recorded audio to compute room acoustic metrics.

## Summary

The Measurement service handles:
- **Audio Signal Generation**: Creates precise measurement signals (logarithmic sine sweeps with sync chirps)
- **Job Management**: CRUD operations for measurement jobs with room maps and metadata
- **File Uploads**: Handles audio file uploads for analysis
- **Acoustic Analysis**: Deconvolution, impulse response extraction, and acoustic metrics computation
- **Reference Signal Storage**: Stores generated signals for later use during analysis

## Architecture Role

```
┌─────────────────────────────────────────────────────────────────┐
│                         GATEWAY                                  │
│            (HTTP Proxy + Gateway Events)                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   MEASUREMENT SERVICE                            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ Audio Generator │  │  Job Manager    │  │ Acoustic        │  │
│  │                 │  │                 │  │ Analysis        │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  │
│           │                    │                    │            │
│           └────────────────────┴────────────────────┘            │
│                                │                                 │
│                    ┌───────────┴───────────┐                     │
│                    │                       │                     │
│              ┌─────┴─────┐         ┌───────┴──────┐              │
│              │ Reference │         │ Job Storage  │              │
│              │   Store   │         │ (File-based) │              │
│              └───────────┘         └──────────────┘              │
└──────────────────────────────────────────────────────────────────┘
```

## Features

### Audio Signal Generation
Generates measurement audio with the following structure:
```
Time (s):    0.0   0.5   2.5          12.5   14.5  15.0
             │     │     │             │      │     │
Signal:      [CHIRP]--silence--[SWEEP]--silence--[CHIRP]
             │                 │                 │
             │                 │                 └─ End sync chirp
             │                 └─ Logarithmic sweep (20Hz-20kHz)
             └─ Start sync chirp (2kHz-10kHz)
```

- **Sync Chirps**: Short chirps at start and end for alignment
- **Measurement Sweep**: Logarithmic frequency sweep for impulse response extraction
- **Configurable**: Sample rate, frequency range, format (WAV/FLAC)

### Acoustic Analysis Pipeline
1. **Chirp Detection**: Cross-correlation to find sync chirps
2. **Alignment**: Extract sweep portion from recording
3. **Deconvolution**: Compute impulse response from sweep
4. **Metric Extraction**: Calculate RT60, EDT, C50, C80, DRR, STI

### Reference Signal Storage
- Stores generated chirp, sweep, and full signal
- Keyed by SHA-256 hash of audio bytes
- Ensures exact signal matching during analysis

## HTTP Endpoints

### Health & Jobs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/health` | Health check |
| `POST` | `/v1/jobs` | Create a new job |
| `GET` | `/v1/jobs/{job_id}` | Get job details, uploads, results |
| `POST` | `/v1/jobs/{job_id}/uploads/{name}` | Upload file to job |
| `POST` | `/v1/jobs/{job_id}/analyze` | Run analysis on job |

### Measurement Audio

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/measurement/audio` | Generate and download measurement audio |
| `GET` | `/v1/measurement/audio/info` | Get signal timing information |

#### Audio Generation Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `session_id` | - | Optional session ID for filename |
| `sample_rate` | `48000` | Sample rate in Hz (8000-192000) |
| `format` | `wav` | Output format: `wav` or `flac` |
| `sweep_f_start` | `20.0` | Sweep start frequency in Hz |
| `sweep_f_end` | `20000.0` | Sweep end frequency in Hz |

**Response Headers:**
- `X-Duration-Seconds`: Total duration
- `X-Sample-Rate`: Sample rate
- `X-Audio-Hash`: SHA-256 hash (use for analysis)

## Gateway Events

Events received via `POST /gateway/handle`:

| Event | Description | Data |
|-------|-------------|------|
| `measurement.create_job` | Create a new job | `{map, meta?}` |
| `measurement.get_job` | Get job data | `{job_id}` |
| `measurement.get_audio_info` | Get signal timing | `{sample_rate?}` |
| `analysis.run` | Run acoustic analysis | See below |

### Analysis Sources

The `analysis.run` event supports multiple input sources:

#### 1. Direct Impulse Response
```json
{
  "job_id": "...",
  "source": "impulse_response",
  "impulse_response_upload": "recording.wav"
}
```

#### 2. Sweep Deconvolution (Manual Reference)
```json
{
  "job_id": "...",
  "source": "sweep_deconvolution",
  "recording_upload": "recording.wav",
  "sweep_reference_upload": "sweep.wav"
}
```

#### 3. Sweep Deconvolution (Generated Reference)
```json
{
  "job_id": "...",
  "source": "sweep_deconvolution_generated",
  "recording_upload": "recording.wav",
  "audio_hash": "sha256_hash_from_audio_endpoint"
}
```

## Analysis Output

The analysis returns comprehensive acoustic metrics:

```json
{
  "job_id": "...",
  "results": {
    "samplerate_hz": 48000,
    "rt": {
      "rt60_s": 0.45,
      "edt_s": 0.38,
      "t20_s": 0.42,
      "t30_s": 0.44
    },
    "clarity": {
      "c50_db": 2.5,
      "c80_db": 5.8,
      "d50": 0.64,
      "d80": 0.79
    },
    "drr": {
      "drr_db": 3.2,
      "direct_to_late_db": 1.8
    },
    "quality": {
      "snr_db": 45.2,
      "peak_db": -3.1
    },
    "frequency_response": {...},
    "sti": {
      "sti": 0.72,
      "sti_male": 0.71,
      "sti_female": 0.73
    },
    "display_metrics": [...]
  }
}
```

### Metric Descriptions

| Metric | Description | Typical Range |
|--------|-------------|---------------|
| **RT60** | Reverberation time (60dB decay) | 0.2-2.0s |
| **EDT** | Early decay time | Similar to RT60 |
| **C50** | Clarity (50ms) for speech | -5 to +10 dB |
| **C80** | Clarity (80ms) for music | -5 to +10 dB |
| **D50** | Definition (50ms) | 0.3-0.8 |
| **DRR** | Direct-to-reverberant ratio | -5 to +10 dB |
| **STI** | Speech transmission index | 0-1 |

## Job Storage Structure

```
/data/{job_id}/
├── map.json           # Room configuration
├── job_meta.json      # Job metadata
├── uploads/           # Uploaded files
│   ├── recording.wav
│   └── ...
└── results/           # Analysis output
    ├── analysis.json
    └── alignment.json
```

## Reference Storage Structure

```
/data/references/{hash_prefix}/{full_hash}/
├── metadata.json      # Configuration used
├── chirp.wav          # Sync chirp signal
├── sweep.wav          # Measurement sweep
└── full_signal.wav    # Complete measurement signal
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEASUREMENT_DATA_DIR` | `/data` | Directory for job storage |
| `MEASUREMENT_DEBUG_DIR` | `debug_audio` | Directory for debug audio files |
| `MEASUREMENT_MAX_UPLOAD_MB` | `50` | Maximum upload size in MB |
| `HOST` | `0.0.0.0` | Server host |
| `PORT` | `8000` | Server port |

## Internal Packages

| Module | Description |
|--------|-------------|
| `app.main` | FastAPI application with CORS middleware |
| `app.api.routes` | HTTP REST API endpoints |
| `app.gateway_handler` | Gateway event handler |
| `app.storage` | File-based job storage |
| `app.reference_store` | Reference signal storage and retrieval |
| `app.models` | Pydantic models for requests/responses |
| `app.settings` | Configuration from environment |

### Analysis Subpackage

| Module | Description |
|--------|-------------|
| `app.analysis.audio_generator` | Measurement signal generation |
| `app.analysis.alignment` | Chirp detection and signal alignment |
| `app.analysis.metrics` | RT60, clarity, DRR calculation |
| `app.analysis.sti` | Speech transmission index |
| `app.analysis.io` | Audio file I/O utilities |

## Dependencies

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
pydantic==2.10.3
pydantic-settings==2.6.1
numpy==2.1.3
scipy==1.14.1
soundfile==0.12.1
python-multipart==0.0.20
httpx==0.27.0
```

## Running Locally

```bash
cd measurement
pip install -r requirements.txt

# Start the server
MEASUREMENT_DATA_DIR=./data uvicorn app.main:app --reload --port 8002

# Or using the main module
python -m app.main
```

## Docker

```bash
docker build -t sonalyze-measurement .
docker run -p 8002:8000 \
  -v $(pwd)/measurement_data:/data \
  -e MEASUREMENT_DATA_DIR=/data \
  sonalyze-measurement
```

## Usage Example

### 1. Generate Measurement Audio
```bash
curl "http://localhost:8002/v1/measurement/audio?sample_rate=48000" \
  -o measurement.wav \
  -D - | grep X-Audio-Hash
# X-Audio-Hash: abc123...
```

### 2. Create a Job
```bash
curl -X POST http://localhost:8002/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"map": {"room": {"vertices": [[0,0],[5,0],[5,4],[0,4]], "height_m": 2.5}}, "meta": {}}'
# {"job_id": "uuid-here"}
```

### 3. Upload Recording
```bash
curl -X POST "http://localhost:8002/v1/jobs/{job_id}/uploads/recording.wav" \
  -F "file=@recording.wav"
```

### 4. Run Analysis
```bash
curl -X POST "http://localhost:8002/v1/jobs/{job_id}/analyze" \
  -H "Content-Type: application/json" \
  -d '{"source": "sweep_deconvolution_generated", "recording_upload": "recording.wav", "audio_hash": "abc123..."}'
```
