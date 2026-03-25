FROM python:3.11-slim

WORKDIR /app

# Sistemske zavisnosti (OpenCV + kompajliranje)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1-mesa-glx \
        libglib2.0-0 \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python zavisnosti
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download InsightFace modela u Docker image
# Ovo se skida JEDNOM tokom builda i ostaje zauvijek
RUN python -c "\
from insightface.app import FaceAnalysis; \
fa = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']); \
fa.prepare(ctx_id=0, det_size=(640, 640)); \
print('buffalo_l model ugrajen u Docker image!')"

# Kopiraj cijelu aplikaciju
COPY . .

EXPOSE 10000

CMD gunicorn app:app \
    --bind 0.0.0.0:${PORT:-10000} \
    --timeout 120 \
    --workers 1 \
    --preload
