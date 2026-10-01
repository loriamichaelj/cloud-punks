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

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8005
# nginx-unprivileged already runs as a non-root user (uid 101).
