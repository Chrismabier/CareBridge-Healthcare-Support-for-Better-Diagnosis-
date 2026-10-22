#!/usr/bin/env node
'use strict';
/**
 * CareBridge web server.
 *
 * Serves the static site and exposes a small HTTP API that drives the real
 * CareBridge C++ console application (one sandboxed process per browser tab):
 *
 *   POST   /api/session                 -> start a session      { id }
 *   GET    /api/session/:id/stream      -> Server-Sent Events   (program output)
 *   POST   /api/session/:id/input       -> send a line of input { line }
 *   POST   /api/session/:id/restart     -> restart (optionally wipe data)
 *   DELETE /api/session/:id             -> end the session
 *   GET    /api/health                  -> service + binary status
 *
 * Zero third-party dependencies: `node server.js` is all it takes.
 */

const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { SessionManager } = require('./lib/sessions');

const WEB_DIR = __dirname;
const ROOT_DIR = path.join(WEB_DIR, '..');
const PUBLIC_DIR = path.join(WEB_DIR, 'public');

const PORT = Number(process.env.PORT || 3000);
const HOST = process.env.HOST || '0.0.0.0'; // 0.0.0.0 so containers / PaaS can reach it
const TTL_MS = Number(process.env.CB_SESSION_TTL_MIN || 30) * 60 * 1000;
const MAX_SESSIONS = Number(process.env.CB_MAX_SESSIONS || 50);
const RUNTIME_DIR = path.resolve(
  process.env.CB_RUNTIME_DIR || path.join(WEB_DIR, 'runtime', 'sessions')
);
const BINARY = resolveBinary();
const CACHE_CONTROL = process.env.NODE_ENV === 'production' ? 'public, max-age=300' : 'no-store';

function resolveBinary() {
  const candidates = [];
  if (process.env.CB_BINARY) candidates.push(path.resolve(process.env.CB_BINARY));
  candidates.push(path.join(ROOT_DIR, 'carebridge'));
  if (process.platform === 'win32') candidates.push(path.join(ROOT_DIR, 'carebridge.exe'));
  return candidates.find((p) => fs.existsSync(p)) || candidates[0];
}

const sessions = new SessionManager({
  binary: BINARY,
  runtimeDir: RUNTIME_DIR,
  cwd: ROOT_DIR,
  ttlMs: TTL_MS,
  maxSessions: MAX_SESSIONS,
});

// ---------------------------------------------------------------- utilities

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
  '.txt': 'text/plain; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
};

function sendJson(res, status, body, done) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(payload),
    'Cache-Control': 'no-store',
  });
  res.end(payload, done);
}

function readJsonBody(req, limit = 8 * 1024) {
  return new Promise((resolve, reject) => {
    let raw = '';
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > limit) {
        // Stop buffering, answer 413, then drop the socket once flushed.
        req.pause();
        reject(
          Object.assign(new Error('payload too large'), { statusCode: 413, dropSocket: true })
        );
        return;
      }
      raw += chunk;
    });
    req.on('end', () => {
      if (!raw) return resolve({});
      try {
        resolve(JSON.parse(raw));
      } catch {
        reject(Object.assign(new Error('invalid JSON body'), { statusCode: 400 }));
      }
    });
    req.on('error', reject);
  });
}

// Very small per-IP token bucket - enough to stop accidental session floods.
const buckets = new Map();
function rateLimited(ip, { capacity = 20, refillPerMin = 10 } = {}) {
  const key = ip || 'unknown';
  const bucket = buckets.get(key) || { tokens: capacity, updatedAt: Date.now() };
  const elapsedMin = (Date.now() - bucket.updatedAt) / 60_000;
  bucket.tokens = Math.min(capacity, bucket.tokens + elapsedMin * refillPerMin);
  bucket.updatedAt = Date.now();
  if (bucket.tokens < 1) {
    buckets.set(key, bucket);
    return true;
  }
  bucket.tokens -= 1;
  buckets.set(key, bucket);
  return false;
}
setInterval(() => {
  const cutoff = Date.now() - 10 * 60_000;
  for (const [ip, bucket] of buckets) if (bucket.updatedAt < cutoff) buckets.delete(ip);
}, 5 * 60_000).unref();

// ---------------------------------------------------------------- static

function serveStatic(req, res, urlPath) {
  let rel = decodeURIComponent(urlPath.split('?')[0].split('#')[0]);
  if (rel === '/' || rel === '') rel = '/index.html';
  const target = path.join(PUBLIC_DIR, path.normalize(rel));
  if (!target.startsWith(PUBLIC_DIR)) {
    sendJson(res, 403, { error: 'forbidden' });
    return;
  }
  fs.stat(target, (err, stat) => {
    if (err || !stat.isFile()) {
      // unknown path -> SPA fallback
      fs.readFile(path.join(PUBLIC_DIR, '404.html'), (e404, buf) => {
        if (e404) {
          res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
          res.end('Not found');
        } else {
          res.writeHead(404, { 'Content-Type': MIME['.html'] });
          res.end(buf);
        }
      });
      return;
    }
    res.writeHead(200, {
      'Content-Type': MIME[path.extname(target).toLowerCase()] || 'application/octet-stream',
      'Content-Length': stat.size,
      'Cache-Control': CACHE_CONTROL,
      'X-Content-Type-Options': 'nosniff',
    });
    fs.createReadStream(target).pipe(res);
  });
}

// ---------------------------------------------------------------- SSE stream

function streamSession(req, res, id) {
  const session = sessions.get(id);
  if (!session) {
    sendJson(res, 404, { error: 'session not found' });
    return;
  }
  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no', // do not let proxies buffer the stream
  });
  res.write(': carebridge stream open\n\n');

  const send = (event) => {
    res.write(`data: ${JSON.stringify(event)}\n\n`);
  };
  const unsubscribe = session.subscribe(send);

  const keepAlive = setInterval(() => {
    res.write(': ping\n\n');
  }, 15_000);

  const cleanup = () => {
    clearInterval(keepAlive);
    unsubscribe();
  };
  req.on('close', cleanup);
  req.on('error', cleanup);
  res.on('close', cleanup);
}

// ---------------------------------------------------------------- router

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const { pathname } = url;
  const ip = (req.headers['x-forwarded-for'] || '').split(',')[0].trim() || req.socket.remoteAddress;

  // The console client can be hosted elsewhere (e.g. GitHub Pages) and pointed
  // at this backend with ?api=https://host - so /api is CORS enabled.
  if (pathname.startsWith('/api/')) {
    res.setHeader('Access-Control-Allow-Origin', req.headers.origin || '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    res.setHeader('Vary', 'Origin');
    if (req.method === 'OPTIONS') {
      res.writeHead(204);
      res.end();
      return;
    }
  }

  try {
    if (pathname === '/api/health') {
      const stats = sessions.stats();
      sendJson(res, 200, {
        ok: true,
        service: 'carebridge-web',
        binary: path.relative(ROOT_DIR, BINARY),
        binaryPresent: fs.existsSync(BINARY),
        node: process.version,
        uptimeSec: Math.round(process.uptime()),
        sessions: stats,
      });
      return;
    }

    if (pathname === '/api/session' && req.method === 'POST') {
      if (rateLimited(ip)) {
        sendJson(res, 429, { error: 'too many sessions started, please wait a moment' });
        return;
      }
      if (!fs.existsSync(BINARY)) {
        sendJson(res, 503, {
          error:
            'CareBridge binary not built. Run `make` (or `npm run build`) in the project root, then retry.',
        });
        return;
      }
      const session = sessions.create();
      sendJson(res, 201, { id: session.id, createdAt: session.createdAt, ttlMs: TTL_MS });
      return;
    }

    let match = pathname.match(/^\/api\/session\/([^/]+)\/stream$/);
    if (match && req.method === 'GET') {
      streamSession(req, res, match[1]);
      return;
    }

    if (pathname.startsWith('/api/session/')) {
      const parts = pathname.split('/').filter(Boolean); // api session <id> [action]
      const id = parts[2];
      const action = parts[3];
      const session = sessions.get(id);
      if (!session) {
        sendJson(res, 404, { error: 'session not found' });
        return;
      }

      if (action === 'input' && req.method === 'POST') {
        const body = await readJsonBody(req);
        if (typeof body.line !== 'string') {
          sendJson(res, 400, { error: 'body must be { line: string }' });
          return;
        }
        const ok = session.write(body.line);
        sendJson(res, ok ? 202 : 409, { accepted: ok, alive: session.alive });
        return;
      }

      if (action === 'restart' && req.method === 'POST') {
        const body = await readJsonBody(req).catch(() => ({}));
        const fresh = sessions.restart(id, { wipe: Boolean(body && body.wipe) });
        sendJson(res, 200, { id, alive: Boolean(fresh && fresh.alive), wiped: Boolean(body && body.wipe) });
        return;
      }

      if (req.method === 'GET') {
        sendJson(res, 200, session.status());
        return;
      }
      if (req.method === 'DELETE') {
        sessions.destroy(id);
        sendJson(res, 200, { id, destroyed: true });
        return;
      }
    }

    if (pathname === '/api/session' && req.method === 'GET') {
      sendJson(res, 200, { sessions: sessions.stats() });
      return;
    }

    if (pathname.startsWith('/api/')) {
      sendJson(res, 404, { error: 'unknown endpoint' });
      return;
    }

    if (req.method === 'GET' || req.method === 'HEAD') {
      serveStatic(req, res, pathname);
      return;
    }

    sendJson(res, 405, { error: 'method not allowed' });
  } catch (err) {
    sendJson(res, err.statusCode || 500, { error: err.message || 'internal error' }, () => {
      if (err.dropSocket) req.destroy();
    });
  }
});

// ---------------------------------------------------------------- startup

if (require.main === module) {
  sessions.startReaper();

  const shutdown = (signal) => {
    process.stdout.write(`\n[carebridge] ${signal} received, stopping sessions...\n`);
    sessions.stop();
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 2000).unref();
  };
  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));

  server.listen(PORT, HOST, () => {
    const lines = [
      '',
      '  CareBridge web console',
      `  URL      : http://${HOST === '0.0.0.0' ? 'localhost' : HOST}:${PORT}`,
      `  Binary   : ${path.relative(ROOT_DIR, BINARY)}${fs.existsSync(BINARY) ? '' : '  (MISSING - run make)'}`,
      `  Sessions : ${RUNTIME_DIR}`,
      `  Node     : ${process.version}   TTL: ${Math.round(TTL_MS / 60000)} min`,
      '',
    ];
    process.stdout.write(lines.join('\n'));
  });
}

module.exports = { server, sessions };
