FROM python:3.11-slim

WORKDIR /app

# Sistemske zavisnosti za OpenCV
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Python zavisnosti
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ⬇️ PRE-DOWNLOAD modela tokom builda (KLJUČNO!)
# Ovo će se skinuti JEDNOM i ostati u Docker image-u
RUN python -c "\
from insightface.app import FaceAnalysis; \
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']); \
app.prepare(ctx_id=0, det_size=(640, 640)); \
print('Model uspješno prebačen u image!')"

# Kopiraj aplikaciju
COPY . .

# Gunicorn sa dovoljnim timeout-om
CMD gunicorn app:app \
    --bind 0.0.0.0:${PORT:-10000} \
    --timeout 120 \
    --workers 1 \
    --preload
