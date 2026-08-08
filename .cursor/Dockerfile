FROM ubuntu:24.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    git curl ca-certificates \
    python3 python3-venv python3-dev python3-pip \
    postgresql postgresql-contrib \
    redis-server \
    libpq-dev build-essential \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 for the Vue frontend (matches apps/web/.nvmrc).
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nodejs \
    && corepack enable \
    && rm -rf /var/lib/apt/lists/*

USER ubuntu
