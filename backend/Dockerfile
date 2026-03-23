# ── Base image ─────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ── System dependencies za dlib / face_recognition ────────────────────────────
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libgtk-3-dev \
    libboost-python-dev \
    libboost-thread-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# ── Radni direktorij ───────────────────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies (kopiraj requirements prvo za cache) ───────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir cmake
RUN pip install --no-cache-dir dlib
RUN pip install --no-cache-dir -r requirements.txt

# ── Kopiraj kod ────────────────────────────────────────────────────────────────
COPY . .

# ── Port ───────────────────────────────────────────────────────────────────────
EXPOSE 10000

# ── Start command ──────────────────────────────────────────────────────────────
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--workers", "1", "--timeout", "120", "app:app"]
