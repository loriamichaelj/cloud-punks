# syntax=docker/dockerfile:1
# Build context is ui/ only (it needs nothing from libs/):
#   docker build -t retail/ui:dev-<sha> ui

FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY index.html tsconfig.json vite.config.ts ./
COPY scripts scripts
COPY src src
# The only build-time switch. Off unless a local build asks for the demo tools.
ARG VITE_DEMO_TOOLS=false
ENV VITE_DEMO_TOOLS=$VITE_DEMO_TOOLS
RUN npm run build

# 1.30.5 on Alpine 3.24 is the current stable line (the 1.27 tag stopped getting rebuilt and carried
# dozens of fixable HIGH and CRITICAL findings). The version is pinned, not a moving tag.
FROM nginxinc/nginx-unprivileged:1.30.5-alpine3.24
# Apply any OS fixes released since the base image was built, then drop root again.
USER root
RUN apk upgrade --no-cache
COPY nginx.conf /etc/nginx/nginx.conf
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8005
# Run as the nginx user (uid 101), declared by number so Kubernetes can verify runAsNonRoot.
USER 101
