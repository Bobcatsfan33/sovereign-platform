## Stage 1 — build the SPA bundle ─────────────────────────────────────
FROM node:22-alpine AS build
WORKDIR /portal

# Cache deps independent of source changes.
COPY apps/portal/package.json apps/portal/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY apps/portal/ ./
# Build-time API endpoints. Defaults work for local docker-compose;
# production sets these to the real broker / audit hostnames.
ARG VITE_BROKER_URL=
ARG VITE_AUDIT_URL=
ARG VITE_DEV_BEARER_TOKEN=dev-token
ENV VITE_BROKER_URL=${VITE_BROKER_URL}
ENV VITE_AUDIT_URL=${VITE_AUDIT_URL}
ENV VITE_DEV_BEARER_TOKEN=${VITE_DEV_BEARER_TOKEN}
RUN npm run build

## Stage 2 — serve the static bundle ──────────────────────────────────
FROM nginx:1.27-alpine
COPY apps/portal/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /portal/dist /usr/share/nginx/html

# React Router uses HTML5 history, so 404s on deep links must fall
# back to /index.html. nginx.conf takes care of it.
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O- http://localhost/ > /dev/null 2>&1 || exit 1
