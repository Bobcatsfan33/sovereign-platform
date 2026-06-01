## Stage 1 — build the SPA bundle ─────────────────────────────────────
# Phase 5.4 STIG hardening: pinned node + nginx tags, non-root nginx
# user, OCI labels, healthcheck, hardened response headers (nginx.conf).
FROM node:22.13.0-alpine AS build
WORKDIR /portal

# Cache deps independent of source changes.
COPY apps/portal/package.json apps/portal/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY apps/portal/ ./
ARG VITE_BROKER_URL=
ARG VITE_AUDIT_URL=
ARG VITE_DEV_BEARER_TOKEN=dev-token
ENV VITE_BROKER_URL=${VITE_BROKER_URL}
ENV VITE_AUDIT_URL=${VITE_AUDIT_URL}
ENV VITE_DEV_BEARER_TOKEN=${VITE_DEV_BEARER_TOKEN}
RUN npm run build

## Stage 2 — serve the static bundle ──────────────────────────────────
# `nginx:1.27-alpine` ships an `nginx` non-root user but the default
# config still binds :80 (privileged). We rebind to :8080 inside the
# container and let the orchestrator publish on :8088 externally —
# matches docker-compose port mapping.
FROM nginx:1.27.4-alpine

LABEL org.opencontainers.image.title="sovereign-platform-portal" \
      org.opencontainers.image.description="Sovereign Platform self-service catalog SPA (React/TS)" \
      org.opencontainers.image.source="https://github.com/Bobcatsfan33/sovereign-platform" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.vendor="Sovereign Platform"

# Refresh Alpine packages so the runtime layer picks up the latest
# security patches available at build time. This pulls libxml2's
# CVE-2026-6732 fix (2.13.9-r1) automatically on architectures where
# Alpine 3.21 has already backported it (e.g. aarch64); on x86_64 the
# backport is still propagating, and libxml2 cannot be force-upgraded
# ahead of it because nginx-module-xslt/njs + libxslt hard-link the base
# libxml2.so.2 (see .trivyignore CVE-2026-6732 + POA&M 5.4-CVE-libxml2).
# `--update-cache` makes the cache key change per build so buildx's
# gha cache cannot replay a stale apk layer past a published fix.
RUN apk --no-cache --update-cache upgrade

COPY apps/portal/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /portal/dist /usr/share/nginx/html

# Make nginx's runtime paths writable by the unprivileged user.
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /var/log/nginx \
 && touch /var/run/nginx.pid \
 && chown nginx:nginx /var/run/nginx.pid \
 # Drop the default privileged listener and run on 8080 inside the container.
 && sed -i 's/listen 80;/listen 8080;/' /etc/nginx/conf.d/default.conf

USER nginx
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O- http://localhost:8080/ > /dev/null 2>&1 || exit 1
