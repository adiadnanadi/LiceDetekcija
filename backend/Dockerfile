FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    libopenblas-dev \
    liblapack-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Preuzmi gotov dlib wheel - ne treba kompajliranje!
RUN wget -q https://github.com/z-mahmud22/Dlib_Windows_Python3.x/releases/download/v1.0/dlib-19.24.99-cp311-cp311-linux_x86_64.whl \
    && pip install --no-cache-dir dlib-19.24.99-cp311-cp311-linux_x86_64.whl \
    && rm dlib-19.24.99-cp311-cp311-linux_x86_64.whl

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--workers", "1", "--timeout", "120", "app:app"]
