FROM denoland/deno:bin AS deno

FROM python:3.12-slim
WORKDIR /app

COPY --from=deno /deno /usr/local/bin/deno

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libffi-dev \
    libopus-dev \
    ffmpeg \
    atomicparsley \
    && rm -rf /var/lib/apt/lists/*

ARG TARGET=bot
COPY requirements-${TARGET}.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-${TARGET}.txt

COPY . .

CMD ["python", "main.py"]
