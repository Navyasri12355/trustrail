# ── TrustRail Frontend Dockerfile ────────────────────────────────────────────
# Build context: frontend/

FROM node:20-slim

WORKDIR /app

# Copy package files first for better layer caching
COPY package.json package-lock.json ./

RUN npm ci

# Copy source (will be overridden by bind mount in dev)
COPY . .

EXPOSE 5173

# Vite must bind to 0.0.0.0 to be reachable outside the container
CMD ["npx", "vite", "--host", "0.0.0.0", "--port", "5173"]
