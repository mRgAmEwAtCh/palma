# ── Frontend build ────────────────────────────────────────────────────────────
# Static output is platform-independent, so build it natively even for multi-arch images.
FROM --platform=$BUILDPLATFORM node:25-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ── Runtime ───────────────────────────────────────────────────────────────────
FROM python:3.14-slim

LABEL org.opencontainers.image.title="Palma" \
      org.opencontainers.image.description="Proxmox And Linux Maintenance via Ansible: a mobile-first web UI for your homelab" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/app \
    DATA_DIR=/data \
    PLAYBOOKS_DIR=/playbooks \
    FRONTEND_DIST=/app/frontend \
    SSH_KEY_PATH=/home/app/.ssh/id_ed25519 \
    ANSIBLE_COLLECTIONS_PATH=/usr/share/ansible/collections

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY playbooks/requirements.yml /tmp/requirements.yml
RUN ansible-galaxy collection install -r /tmp/requirements.yml -p /usr/share/ansible/collections

COPY backend/app ./app
COPY --from=web /web/dist ./frontend
COPY playbooks /playbooks
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
