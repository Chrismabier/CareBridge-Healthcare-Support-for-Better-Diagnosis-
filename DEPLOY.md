# Deploying CareBridge

CareBridge is a **C++17 console application**. It ships with a small zero-dependency Node
runtime (`web/`) that runs the real compiled binary and streams its terminal into the browser,
so the project can be deployed as a web app **without rewriting or re-implementing any of the
C++ logic**.

```
browser  --HTTP/SSE-->  web/server.js  --stdin/stdout-->  ./carebridge  (C++17)
```

Two things get deployed:

| Target | What it is | Where |
|---|---|---|
| **Web app** (console) | Node server + compiled binary, one sandboxed process per browser tab | Docker, Render, Fly.io, any VPS |
| **Static site** | Landing page + console client (`web/public`) | GitHub Pages, on every push to `main` |

---

## 1. Quick start (local)

```bash
make                 # compile src/ -> ./carebridge
cd web && npm start  # http://localhost:3000
```

* Landing page: <http://localhost:3000/>
* Console: <http://localhost:3000/console.html>
* Health check: <http://localhost:3000/api/health>

`npm start` boots the server; if the binary is missing or stale, run `npm run build` (it calls
`make` for you). Node 18+ is required, and there are **no npm dependencies**.

## 2. Docker (recommended)

```bash
docker compose up --build          # http://localhost:3000
# or, without compose:
docker build -t carebridge:latest .
docker run --rm -p 3000:3000 -v carebridge-sessions:/app/web/runtime/sessions carebridge:latest
```

The image is multi-stage: `gcc:12` compiles the C++ sources, then only the binary plus
`node:22-slim` runtime ship in the final image, which runs as a non-root user with a
health check on `/api/health`.

## 3. Managed platforms

### Render (Blueprint)
`render.yaml` is committed. **Dashboard → New → Blueprint → pick this repo**. Render builds
the Docker image, injects `PORT` and uses `/api/health` as the health-check path.

### Fly.io
```bash
curl -L https://fly.io/install.sh | sh   # or: brew install flyctl
fly auth login
fly apps create carebridge            # skip if the app already exists
fly deploy                            # uses fly.toml (Mumbai region, 256 MB VM)
fly open
```
Machines auto-suspend when idle, so an unused deployment costs (almost) nothing.

### Railway / Koyeb / any "Docker from repo" host
Point it at the repository — the `Dockerfile` at the root is picked up automatically. Set the
port to `3000` (or let the platform inject `PORT`; the server honours it).

### VPS (Ubuntu) with systemd
```bash
sudo apt install -y build-essential nodejs
git clone https://github.com/Chrismabier/CareBridge-Healthcare-Support-for-Better-Diagnosis-.git
cd CareBridge-Healthcare-Support-for-Better-Diagnosis-
make
sudo tee /etc/systemd/system/carebridge.service >/dev/null <<'EOF'
[Unit]
Description=CareBridge web console
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/carebridge/web
Environment=PORT=3000
Environment=CB_SESSION_TTL_MIN=30
ExecStart=/usr/bin/node /opt/carebridge/web/server.js
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now carebridge
```
Put it behind nginx/Caddy for TLS and to proxy `/` (keep `proxy_buffering off` and SSE working).

## 4. GitHub Pages (static site — UI only, needs a backend)

`.github/workflows/pages.yml` deploys `web/public` (landing page + console client) on every
push to `main`. Enable it once under **Settings → Pages → Source: GitHub Actions**.

Pages can only serve static files: it cannot run the Node server or the C++ binary. So the
console hosted there **always** needs a backend to talk to — opening it without one fails with
`Could not reach the CareBridge server (HTTP 405)`, because Pages rejects the
`POST /api/session` call with “Method Not Allowed”. That is expected: it means “no backend”.

Fix it in two steps:

1. Deploy the backend once (§2 or §3 — Render Blueprint is the easiest free option).
   Verify it in a new tab: `https://your-backend-host/api/health` must return `{"ok":true,…}`.
2. Point the Pages console at it — either paste the URL into the **Backend** box in the
   console header, or open:
   ```
   https://<user>.github.io/CareBridge-Healthcare-Support-for-Better-Diagnosis-/console.html?api=https://your-backend-host
   ```

The backend URL is remembered in `localStorage` (per browser). It must be reachable over
**HTTPS** — browsers block `http://` backends from an `https://` page (mixed content).
CORS on `/api/*` is already configured in `web/server.js`, and a bare host
(`?api=my-app.onrender.com`) is accepted and assumed to be `https://`.

| Symptom on the Pages console | Meaning |
|---|---|
| `HTTP 405` | No backend configured — the request went to Pages itself (§4). |
| `Failed to fetch` / `reconnecting…` | Backend URL wrong, backend asleep (free hosts need ~1 min to wake), or not HTTPS. |
| `HTTP 404` on `/api/session` | URL points at something that is not a CareBridge backend — check `/api/health`. |
| `HTTP 503` | Backend is up but its C++ binary was not built (`make` / `npm run build`). |

## 5. CI/CD

`.github/workflows/ci.yml` runs on every push and pull request:

* **build-test** — compiles with `g++` (Linux), `clang++` (Linux) and MSVC (Windows) plus `make`
  on macOS, and runs `make test`.
* **web** — boots the server and drives a real session over HTTP (create session → log in as the
  demo patient → assert on the streamed output).
* **docker** — builds the image and, on `main`, publishes it to
  `ghcr.io/<owner>/carebridge:latest` / `:sha-<commit>` (the repository name itself is not a valid
  Docker image name, so the image is published as `carebridge` under your GHCR namespace).

```bash
docker pull ghcr.io/chrismabier/carebridge:latest
docker run --rm -p 3000:3000 ghcr.io/chrismabier/carebridge:latest
```

## 6. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `3000` | HTTP port (hosted platforms set this automatically) |
| `HOST` | `0.0.0.0` | Bind address |
| `CB_BINARY` | `../carebridge` | Path to the compiled binary |
| `CB_RUNTIME_DIR` | `web/runtime/sessions` | Where per-session `data/` directories live |
| `CB_SESSION_TTL_MIN` | `30` | Idle minutes before a session process is killed |
| `CB_MAX_SESSIONS` | `50` | Hard cap on concurrent CareBridge processes |
| `NODE_ENV` | – | `production` enables static asset caching |

## 7. HTTP API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/session` | Start a session → `{ id }` |
| `GET` | `/api/session/:id/stream` | Server-Sent Events: program output |
| `POST` | `/api/session/:id/input` | Send a line: `{ line: "1" }` |
| `POST` | `/api/session/:id/restart` | Restart the process (`{ wipe: true }` also resets data) |
| `DELETE` | `/api/session/:id` | End the session and delete its data |
| `GET` | `/api/health` | Service, binary and session status |

## 8. Operational notes

* **Isolation** — every tab gets its own process and its own `data/` directory, so visitors never
  see each other's patients, appointments or records.
* **Cleanup** — sessions are killed when idle past the TTL, when the cap is reached, and on server
  shutdown (`SIGINT`/`SIGTERM`); the data directory is removed with the session.
* **Limits** — input lines are capped at 2 000 characters, JSON bodies at 8 KB, and session
  creation is rate limited per IP (20 tokens, 10/minute refill).
* **Data** — session data lives on the container filesystem. Mount
  `/app/web/runtime/sessions` (compose/fly do this) if you want it to survive restarts.
* **Prototype** — passwords use a simple non-secure hash and there is no encryption, audit trail or
  concurrency control. Keep it behind a trusted network; it is not a medical system.
