FROM pytorch/pytorch:2.7.1-cuda12.6-cudnn9-runtime
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY worker worker
COPY shared shared
COPY pipeline pipeline
COPY versions.json .
ENV PYTHONUNBUFFERED=1 OPENFISH_DETECTOR_MODEL=/models/cfd-complete.pt
CMD ["python", "-m", "worker.handler"]
