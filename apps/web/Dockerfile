FROM node:22-alpine AS builder
WORKDIR /app
RUN corepack enable
COPY . .
RUN pnpm install --frozen-lockfile
# Vite inlines VITE_* vars into the built JS at compile time, not at container runtime -- must be
# passed as a Docker build arg (see docker-compose.yml's web.build.args), not just an env var on
# the running container, or the frontend silently falls back to the same-origin '/api' path.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN pnpm build

FROM nginx:stable-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
