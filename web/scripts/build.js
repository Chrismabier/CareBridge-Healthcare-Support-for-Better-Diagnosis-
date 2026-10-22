#!/usr/bin/env node
/**
 * Build helper for the CareBridge web runtime.
 *
 * The web console does NOT re-implement CareBridge: it runs the real C++ binary
 * (src/*.cpp) and streams its stdin/stdout to the browser. So the binary has to
 * exist before the server starts. This script builds it with `make` when it is
 * missing or stale, so a plain `npm install && npm start` works on a fresh
 * checkout (and on hosting platforms that run `npm run build`).
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const WEB_DIR = path.join(__dirname, '..');
const ROOT_DIR = path.join(WEB_DIR, '..');

const candidates = [];
if (process.env.CB_BINARY) candidates.push(process.env.CB_BINARY);
candidates.push(path.join(ROOT_DIR, 'carebridge'));
if (process.platform === 'win32') candidates.push(path.join(ROOT_DIR, 'carebridge.exe'));

const existing = candidates.find((p) => fs.existsSync(p));
const sources = ['src/main.cpp', 'src/HealthcareSystem.cpp']
  .map((rel) => path.join(ROOT_DIR, rel))
  .filter((p) => fs.existsSync(p));

function stale(binary) {
  if (!sources.length) return false;
  const binaryMtime = fs.statSync(binary).mtimeMs;
  return sources.some((s) => fs.statSync(s).mtimeMs > binaryMtime);
}

if (existing && !stale(existing)) {
  console.log(`[carebridge] binary up to date: ${path.relative(ROOT_DIR, existing)}`);
  process.exit(0);
}

const make = process.platform === 'win32' ? 'nmake' : 'make';
console.log(`[carebridge] building C++ binary with ${make} ...`);
const result = spawnSync(make, ['-C', ROOT_DIR], { stdio: 'inherit', shell: process.platform === 'win32' });

if (result.status !== 0) {
  console.error(
    '\n[carebridge] Build failed. Install a C++17 compiler (g++ 9+, clang, MSVC) and re-run,\n' +
      'or build manually:  g++ -std=c++17 -O2 -o carebridge src/main.cpp src/HealthcareSystem.cpp\n'
  );
  process.exit(result.status === null ? 1 : result.status);
}
console.log('[carebridge] build ok');
