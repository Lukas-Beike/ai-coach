FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8090 \
    DATA_DIR=/data

WORKDIR /app
COPY server.py /app/server.py
COPY backend /app/backend
COPY garmin-login.py /app/garmin-login.py
COPY public /app/public
COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r /app/requirements.txt \
    && addgroup --system --gid 101 app \
    && adduser --system --uid 100 --ingroup app app \
    && mkdir -p /data \
    && chown -R app:app /data \
    && chmod -R a-w /app
USER app
EXPOSE 8090
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8090') + '/api/health', timeout=2)"

CMD ["python", "/app/server.py"]
