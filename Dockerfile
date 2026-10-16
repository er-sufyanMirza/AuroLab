# ══════════════════════════════════════════════════════════════════════════════
# AuroLab — Multi-stage Docker Build
# Stage 1: builder  — install Python deps + compile any C extensions
# Stage 2: runtime  — lean final image without build tools
# ══════════════════════════════════════════════════════════════════════════════

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# System build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build tools (for pybullet, pyzmq C extensions)
    gcc g++ make \
    # PyMuPDF needs these headers
    libmupdf-dev mupdf-tools \
    # python-magic needs libmagic
    libmagic1 \
    # Tesseract OCR binary (for pytesseract PDF fallback)
    tesseract-ocr tesseract-ocr-eng \
    # Git (sentence-transformers downloads models)
    git \
    # Clean up apt lists to keep layer small
    && rm -rf /var/lib/apt/lists/*

WORKDIR /install

# Install PyTorch CPU-only FIRST (huge package, own layer for caching)
RUN pip install --no-cache-dir \
    torch==2.4.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# Copy and install remaining requirements
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="AuroLab"
LABEL description="Autonomous Physical AI Lab Automation — FastAPI backend + Streamlit dashboard"
LABEL version="2.0.0"

# Runtime system deps only (no compilers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # python-magic runtime
    libmagic1 \
    # Tesseract OCR runtime
    tesseract-ocr tesseract-ocr-eng \
    # curl for healthcheck
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin

# ── App setup ─────────────────────────────────────────────────────────────────
WORKDIR /app

# Copy project files
COPY . .

# Create data directories
RUN mkdir -p \
    data/chroma \
    data/pdfs \
    data/eval \
    logs

# Non-root user for security
RUN groupadd -r aurolab && useradd -r -g aurolab -s /bin/false aurolab
RUN chown -R aurolab:aurolab /app
USER aurolab

# Pre-download sentence-transformers model at build time so container starts fast
# (downloads ~90MB all-MiniLM-L6-v2 into HuggingFace cache)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" \
    || echo "Model download skipped — will download on first run"

# ── Ports ─────────────────────────────────────────────────────────────────────
EXPOSE 8080   
# FastAPI backend
EXPOSE 8501   
# Streamlit dashboard

# ── Health check ──────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# ── Default: start backend ────────────────────────────────────────────────────
# Override CMD to start streamlit instead:
#   docker run aurolab streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0
CMD ["python", "main.py"]