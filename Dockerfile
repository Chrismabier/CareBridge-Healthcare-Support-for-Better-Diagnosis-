# ---------------------------------------------------------------------------
# CareBridge - production image for the web console.
#
# Stage 1 compiles the C++17 application.
# Stage 2 runs only the Node server + the compiled binary (no compiler, small
# image, non-root user).
#
#   docker build -t carebridge:latest .
#   docker run --rm -p 3000:3000 carebridge:latest
# ---------------------------------------------------------------------------

FROM gcc:12-bookworm AS build
WORKDIR /src
COPY Makefile ./
COPY src ./src
RUN make

FROM node:22-bookworm-slim AS runtime
ENV NODE_ENV=production \
    PORT=3000 \
    CB_SESSION_TTL_MIN=30 \
    CB_MAX_SESSIONS=50
WORKDIR /app

# Web runtime (server + static client)
COPY web/package.json ./web/package.json
COPY web/server.js ./web/server.js
COPY web/scripts ./web/scripts
COPY web/lib ./web/lib
COPY web/public ./web/public

# Compiled CareBridge binary (the server looks for ../carebridge)
COPY --from=build /src/carebridge /app/carebridge

RUN useradd --create-home --uid 10001 carebridge \
 && mkdir -p /app/web/runtime/sessions \
 && chown -R carebridge:carebridge /app

USER carebridge
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "require('node:http').get('http://127.0.0.1:'+(process.env.PORT||3000)+'/api/health',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "web/server.js"]
