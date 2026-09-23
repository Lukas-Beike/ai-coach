FROM python:3.14-slim@sha256:caaf356f40667c496d405780745b9ac25771c189a51dfcc42430d531ea09f8a2

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8090 \
    DATA_DIR=/data

WORKDIR /app
COPY server.py /app/server.py
COPY backend /app/backend
COPY garmin-login.py /app/garmin-login.py
COPY public /app/public
COPY requirements.lock /app/requirements.lock

RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r /app/requirements.lock \
    && addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /data \
    && chown -R app:app /app /data
USER app
EXPOSE 8090
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/api/health', timeout=2)"

CMD ["python", "/app/server.py"]
