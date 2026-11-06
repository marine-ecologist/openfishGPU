FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home app && mkdir /data && chown app /data
COPY server server
COPY shared shared
COPY web web
COPY versions.json .
USER app
ENV DATABASE_PATH=/data/jobs.sqlite3
EXPOSE 8000
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
