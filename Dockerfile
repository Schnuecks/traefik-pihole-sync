# Pinned to a digest so a rebuild uses exactly this image; Dependabot proposes updates.
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app /data

COPY traefik_pihole_sync ./traefik_pihole_sync

USER 10001
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "-m", "traefik_pihole_sync", "--healthcheck"]

ENTRYPOINT ["python", "-m", "traefik_pihole_sync"]
