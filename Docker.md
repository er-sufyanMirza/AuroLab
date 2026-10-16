# AuroLab — Docker Guide

## Quick Start

```bash
# 1. Copy and fill env file
cp .env.example .env
# Edit .env: set GROQ_API_KEY=gsk_...

# 2. Build and start everything
docker-compose up --build

# Backend:   http://localhost:8080
# Dashboard: http://localhost:8501
# API docs:  http://localhost:8080/docs
```

## Commands

```bash
# Start all services
docker-compose up --build

# Start in background (detached)
docker-compose up -d --build

# Backend only
docker-compose up backend

# Watch logs
docker-compose logs -f backend
docker-compose logs -f dashboard

# Stop everything
docker-compose down

# Stop and delete all data volumes (full reset)
docker-compose down -v

# Rebuild after code changes
docker-compose up --build --force-recreate
```

## Services

| Service   | Port | URL                        |
|-----------|------|----------------------------|
| backend   | 8080 | http://localhost:8080      |
| dashboard | 8501 | http://localhost:8501      |
| API docs  | 8080 | http://localhost:8080/docs |

## Build the image manually

```bash
# Build backend image
docker build -t aurolab-backend:latest .

# Run backend only
docker run -p 8080:8080 \
  -e GROQ_API_KEY=gsk_your_key \
  -v $(pwd)/data:/app/data \
  aurolab-backend:latest

# Run dashboard only (needs backend running)
docker run -p 8501:8501 aurolab-backend:latest \
  streamlit run dashboard/app.py \
  --server.port=8501 \
  --server.address=0.0.0.0 \
  --server.headless=true
```

## Persisted Data

Docker volumes survive container restarts:

| Volume          | Contents                              |
|-----------------|---------------------------------------|
| aurolab-chroma  | ChromaDB vector store (your PDFs)     |
| aurolab-data    | SQLite DBs, registry.json, telemetry  |
| aurolab-logs    | Structured JSON logs                  |

To backup your data:
```bash
docker run --rm \
  -v aurolab-data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/aurolab-data-backup.tar.gz /data
```

## Image size breakdown

| Layer                          | Approx size |
|--------------------------------|-------------|
| python:3.11-slim base          | ~130 MB     |
| System deps (tesseract, magic) | ~80 MB      |
| PyTorch CPU-only               | ~700 MB     |
| sentence-transformers + model  | ~200 MB     |
| ChromaDB + other Python deps   | ~400 MB     |
| AuroLab app code               | ~10 MB      |
| **Total**                      | **~1.5 GB** |

> PyTorch is the largest component. For a smaller image, replace
> PyBullet simulation with mock mode and remove torch entirely.

## Environment Variables

| Variable               | Required | Default    | Description              |
|------------------------|----------|------------|--------------------------|
| GROQ_API_KEY           | Yes      | —          | Groq API key             |
| AUROLAB_SIM_MODE       | No       | pybullet   | mock/pybullet/live       |
| AUROLAB_VISION_BACKEND | No       | mock       | mock/groq                |
| CHROMA_PERSIST         | No       | /app/data/chroma | ChromaDB path      |
| PORT                   | No       | 8080       | Backend port             |
| ENV                    | No       | prod       | prod/dev (dev=hot reload)|

## Windows Docker Desktop Notes

If using Docker Desktop on Windows:
- Make sure WSL2 backend is enabled (Settings → General → Use WSL2)
- Volume paths use Linux format inside containers
- Data volumes are stored in WSL2 filesystem automatically

```powershell
# Windows PowerShell equivalent of docker run with volume
docker run -p 8080:8080 `
  -e GROQ_API_KEY=gsk_your_key `
  -v ${PWD}/data:/app/data `
  aurolab-backend:latest
```

## Troubleshooting

**Backend fails to start:**
```bash
docker-compose logs backend
# Check for: GROQ_API_KEY not set, port already in use
```

**Dashboard can't connect to backend:**
```bash
# The dashboard uses http://localhost:8080 internally
# In Docker, services communicate via container names
# shared.py API_BASE is hardcoded to localhost — this works because
# both containers share the host network in compose
```

**ChromaDB model download fails:**
```bash
# First run downloads all-MiniLM-L6-v2 (~90MB)
# Needs internet access. Check Docker network settings.
# Or pre-bake the model: already done in Dockerfile RUN step
```

**Out of memory during build:**
```bash
# PyTorch build needs ~4GB RAM
# Docker Desktop → Settings → Resources → Memory → increase to 6GB
```