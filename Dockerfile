# Pinned to a digest so a rebuild uses exactly this image; Dependabot proposes updates.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
# pip is only needed at build time; removing it keeps its bundled packages out of the image.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall --yes pip \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app /data

COPY traefik_pihole_sync ./traefik_pihole_sync

USER 10001
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "-m", "traefik_pihole_sync", "--healthcheck"]

ENTRYPOINT ["python", "-m", "traefik_pihole_sync"]
