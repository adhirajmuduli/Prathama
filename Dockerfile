FROM python:3.10.22-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    TRENDSMAPP_DATABASE_PATH=/data/trendsmapp.db \
    TRENDSMAPP_DEMO_MODE=true

WORKDIR /app

COPY requirements.lock.txt requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip==24.3.1 \
    && python -m pip install --no-cache-dir -r requirements.lock.txt \
    && addgroup --system --gid 10001 trendsmapp \
    && adduser --system --uid 10001 --ingroup trendsmapp --home /app trendsmapp

COPY --chown=trendsmapp:trendsmapp . .
RUN mkdir -p /data /app/uploads /app/static/data/uploads /tmp/matplotlib \
    && chown -R trendsmapp:trendsmapp /data /app/uploads /app/static/data/uploads /tmp/matplotlib

USER trendsmapp
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
