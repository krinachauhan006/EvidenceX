# Caddy with the rate-limit module (github.com/mholt/caddy-ratelimit), built with the
# official xcaddy builder image. Stock Caddy has no rate limiter.
FROM caddy:2-builder AS builder
RUN xcaddy build --with github.com/mholt/caddy-ratelimit

FROM caddy:2-alpine
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
