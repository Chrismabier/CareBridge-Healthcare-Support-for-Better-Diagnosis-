'use strict';
/**
 * Session manager for the CareBridge web console.
 *
 * Every browser tab gets its own sandboxed CareBridge process: the real C++
 * binary (src/main.cpp) with its own `data/` directory, so two users never see
 * each other's patients, doctors or appointments. Output is streamed out and
 * keystrokes are piped in, exactly like a local terminal session.
 */

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { StringDecoder } = require('node:string_decoder');

const MAX_BUFFER_CHARS = 200_000; // rolling output buffer kept for reconnects
const MAX_INPUT_CHARS = 2_000;
const SESSION_ID_RE = /^[0-9a-f]{32}$/;
const KILL_GRACE_MS = 5_000;

function now() {
  return Date.now();
}

class Session {
  constructor({ id, binary, dataDir, cwd }) {
    this.id = id;
    this.binary = binary;
    this.dataDir = dataDir;
    this.cwd = cwd;
    this.child = null;
    this.buffer = '';
    this.subscribers = new Set();
    this.createdAt = now();
    this.lastActivityAt = now();
    this.exitCode = null;
    this.started = false;
    this.decoder = null;
  }

  get alive() {
    return Boolean(this.child) && this.exitCode === null && this.child.exitCode === null;
  }

  start() {
    if (this.started) return;
    this.started = true;
    fs.mkdirSync(this.dataDir, { recursive: true });

    let child;
    try {
      child = spawn(this.binary, [this.dataDir], {
        cwd: this.cwd,
        stdio: ['pipe', 'pipe', 'pipe'],
        env: { ...process.env, CB_SESSION_ID: this.id },
        windowsHide: true,
      });
    } catch (err) {
      this.started = false;
      this.emit(`\r\n[carebridge] Could not start the application: ${err.message}\r\n`);
      this.exitCode = -1;
      return;
    }

    this.child = child;
    this.decoder = new StringDecoder('utf8');

    child.stdout.on('data', (chunk) => this.emit(this.decoder.write(chunk)));
    child.stderr.on('data', (chunk) => this.emit(this.decoder.write(chunk)));
    child.on('error', (err) => this.emit(`\r\n[carebridge] process error: ${err.message}\r\n`));
    child.on('close', (code) => {
      const tail = this.decoder ? this.decoder.end() : '';
      if (tail) this.emit(tail);
      this.exitCode = code === null ? -1 : code;
      this.emitEvent({ type: 'exit', code: this.exitCode, at: now() });
      this.closeSubscribers();
    });

    // stdin errors are expected once the process exits - keep them quiet.
    child.stdin.on('error', () => {});
  }

  /** Append text to the rolling buffer and push it to every open stream. */
  emit(text) {
    if (!text) return;
    this.lastActivityAt = now();
    this.buffer += text;
    if (this.buffer.length > MAX_BUFFER_CHARS) {
      this.buffer = this.buffer.slice(-MAX_BUFFER_CHARS);
    }
    this.emitEvent({ type: 'out', text, at: now() });
  }

  emitEvent(event) {
    for (const send of this.subscribers) {
      try {
        send(event);
      } catch {
        /* subscriber went away; the 'close' handler removes it */
      }
    }
  }

  /** Send one line of input (a trailing newline is added, like pressing Enter). */
  write(line) {
    if (!this.alive) return false;
    let text = String(line == null ? '' : line).replace(/\r?\n/g, ' ');
    if (text.length > MAX_INPUT_CHARS) text = text.slice(0, MAX_INPUT_CHARS);
    this.lastActivityAt = now();
    try {
      this.child.stdin.write(text + '\n');
      return true;
    } catch {
      return false;
    }
  }

  subscribe(send) {
    this.subscribers.add(send);
    send({ type: 'snapshot', text: this.buffer, alive: this.alive, at: now() });
    this.lastActivityAt = now();
    return () => this.subscribers.delete(send);
  }

  closeSubscribers() {
    for (const send of this.subscribers) {
      try {
        send({ type: 'exit', code: this.exitCode, at: now() });
      } catch {
        /* ignore */
      }
    }
    this.subscribers.clear();
  }

  kill() {
    if (!this.child) return;
    const child = this.child;
    this.child = null;
    if (child.exitCode === null && child.signalCode === null) {
      try {
        child.kill('SIGTERM');
        setTimeout(() => {
          if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
        }, KILL_GRACE_MS).unref();
      } catch {
        /* already gone */
      }
    }
  }

  /** Wipe this session's data directory (CareBridge re-seeds sample data). */
  resetData() {
    fs.rmSync(this.dataDir, { recursive: true, force: true });
  }

  status() {
    return {
      id: this.id,
      alive: this.alive,
      exitCode: this.exitCode,
      createdAt: this.createdAt,
      lastActivityAt: this.lastActivityAt,
      idleMs: now() - this.lastActivityAt,
      outputChars: this.buffer.length,
    };
  }
}

class SessionManager {
  constructor({ binary, runtimeDir, cwd, ttlMs = 30 * 60 * 1000, maxSessions = 50 }) {
    this.binary = binary;
    this.runtimeDir = runtimeDir;
    this.cwd = cwd;
    this.ttlMs = ttlMs;
    this.maxSessions = maxSessions;
    this.sessions = new Map();
    this.reaper = null;
    fs.mkdirSync(runtimeDir, { recursive: true });
  }

  create() {
    if (this.sessions.size >= this.maxSessions) this.evictOldest(this.sessions.size - this.maxSessions + 1);
    const id = crypto.randomBytes(16).toString('hex');
    const session = new Session({
      id,
      binary: this.binary,
      dataDir: path.join(this.runtimeDir, id),
      cwd: this.cwd,
    });
    this.sessions.set(id, session);
    session.start();
    return session;
  }

  get(id) {
    if (!SESSION_ID_RE.test(String(id || ''))) return null;
    return this.sessions.get(id) || null;
  }

  destroy(id) {
    const session = this.get(id);
    if (!session) return false;
    session.kill();
    session.resetData();
    this.sessions.delete(id);
    return true;
  }

  /** Restart the process; when `wipe` is true the sample data is re-seeded. */
  restart(id, { wipe = false } = {}) {
    const session = this.get(id);
    if (!session) return null;
    session.kill();
    if (wipe) session.resetData();
    const fresh = new Session({
      id,
      binary: this.binary,
      dataDir: session.dataDir,
      cwd: this.cwd,
    });
    this.sessions.set(id, fresh);
    fresh.start();
    if (wipe) fresh.emit('\r\n[carebridge] Data reset - sample data restored.\r\n');
    return fresh;
  }

  evictOldest(count) {
    const ordered = [...this.sessions.values()].sort((a, b) => a.lastActivityAt - b.lastActivityAt);
    for (const session of ordered.slice(0, Math.max(0, count))) this.destroy(session.id);
  }

  /** Kill sessions that have been idle for longer than the TTL. */
  sweep() {
    const cutoff = now() - this.ttlMs;
    for (const session of [...this.sessions.values()]) {
      if (session.lastActivityAt < cutoff) this.destroy(session.id);
    }
  }

  startReaper(intervalMs = 60_000) {
    if (this.reaper) return;
    this.reaper = setInterval(() => this.sweep(), intervalMs);
    this.reaper.unref();
  }

  stop() {
    if (this.reaper) clearInterval(this.reaper);
    this.reaper = null;
    for (const id of [...this.sessions.keys()]) this.destroy(id);
  }

  stats() {
    let alive = 0;
    for (const session of this.sessions.values()) if (session.alive) alive += 1;
    return { total: this.sessions.size, alive, ttlMs: this.ttlMs, maxSessions: this.maxSessions };
  }
}

module.exports = { SessionManager, Session, SESSION_ID_RE, MAX_INPUT_CHARS, MAX_BUFFER_CHARS };
