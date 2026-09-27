# Dockerfile — Vera bot (single process; state in memory with SQLite write-through on /data)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    VERA_DB_PATH=/data/vera.db \
    VERA_CASE_STUDIES_PATH=/app/reference/challenge/examples/case-studies.md

WORKDIR /app
RUN useradd --create-home --uid 1000 vera && mkdir -p /data && chown vera:vera /data

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .
# the validator's plagiarism check reads the case studies at runtime (V14)
COPY reference/challenge/examples/case-studies.md ./reference/challenge/examples/case-studies.md

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/v1/healthz' % os.environ.get('PORT','8080'), timeout=2)"

# Fly volumes mount root-owned: fix ownership, then drop privileges. Exactly one worker (ADR-001).
CMD ["sh", "-c", "chown vera:vera /data && exec setpriv --reuid=1000 --regid=1000 --init-groups uvicorn vera.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-graceful-shutdown 10 --log-level warning"]
