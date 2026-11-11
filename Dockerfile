FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/pulse

COPY pyproject.toml ./
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY app/ ./app/
COPY scripts/ ./scripts/

RUN python -m pip install --no-cache-dir . \
    && useradd --system --uid 10001 --create-home pulse \
    && mkdir -p /var/lib/pulse \
    && chown -R pulse:pulse /var/lib/pulse

USER pulse
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
