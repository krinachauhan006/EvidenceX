# EvidenceX web (Next.js 14). Production image.
#
# NEXT_PUBLIC_API_BASE_URL is compiled into the browser bundle at BUILD time.
# Leave it empty for the recommended single-domain setup (the reverse proxy routes
# /api/* and /health to the API, so the browser uses same-origin relative URLs).
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
ARG NEXT_PUBLIC_API_BASE_URL=""
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
# Refuse to bake a loopback API address into a production bundle.
RUN case "$NEXT_PUBLIC_API_BASE_URL" in *localhost*|*127.0.0.1*) echo "NEXT_PUBLIC_API_BASE_URL must not point at localhost in a production build" >&2; exit 1;; esac
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build && npm prune --omit=dev

FROM node:20-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
RUN addgroup -S web && adduser -S web -G web
COPY --from=build --chown=web:web /app/.next ./.next
COPY --from=build --chown=web:web /app/public ./public
COPY --from=build --chown=web:web /app/node_modules ./node_modules
COPY --from=build --chown=web:web /app/package.json ./package.json
COPY --from=build --chown=web:web /app/next.config.mjs ./next.config.mjs
# next.config.mjs imports the CSP builder and the API proxy rules at start-up.
COPY --from=build --chown=web:web /app/lib/csp.mjs ./lib/csp.mjs
COPY --from=build --chown=web:web /app/lib/api-proxy.mjs ./lib/api-proxy.mjs
USER web
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1
CMD ["npx", "next", "start", "-p", "3000", "-H", "0.0.0.0"]
