FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python -c "from insightface.app import FaceAnalysis; fa = FaceAnalysis(name='buffalo_l', root='/root/.insightface', providers=['CPUExecutionProvider']); fa.prepare(ctx_id=0, det_size=(160,160)); print('Model preuzet!')"

COPY . .

EXPOSE 10000

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--timeout", "120", "--workers", "1"]
