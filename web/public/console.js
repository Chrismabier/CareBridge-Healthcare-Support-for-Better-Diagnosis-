/* CareBridge console client.
 * Streams the real C++ console application (via the Node server) into the browser.
 * Transport: Server-Sent Events for output, plain POST for keystrokes.
 *
 * The page can be served by the backend itself (same origin) or hosted statically
 * (e.g. GitHub Pages) and pointed at a backend with ?api=https://host.
 * The backend URL is remembered in localStorage and can be changed at any time
 * with the "Backend" button in the header.
 */
(function () {
  'use strict';

  var outEl = document.getElementById('out');
  var cmdEl = document.getElementById('cmd');
  var statusEl = document.getElementById('status');
  var terminalEl = document.getElementById('terminal');
  var chipsEl = document.getElementById('chips');
  var backendBanner = document.getElementById('backend-banner');
  var backendMsg = document.getElementById('backend-msg');
  var backendForm = document.getElementById('backend-form');
  var backendUrl = document.getElementById('backend-url');
  var backendLocal = document.getElementById('backend-local');
  var backendDismiss = document.getElementById('backend-dismiss');
  var backendCurrent = document.getElementById('backend-current');
  var backendPill = document.getElementById('backend-pill');

  var SESSION_KEY = 'carebridge.session';
  var SESSION_API_KEY = 'carebridge.session.api';
  var API_KEY = 'carebridge.api';
  var MAX_CHARS = 120000;

  var apiBase = '';
  var sessionId = null;
  var source = null;
  var text = '';
  var history = [];
  var historyIndex = -1;
  var busy = false;
  var ended = false;
  var runningSequence = false;
  var bannerDismissed = false;
  var streamErrors = 0;

  // ----------------------------------------------------------------- config

  // Normalise anything the user types (?api= value or the backend box) to an
  // origin such as "https://carebridge.onrender.com", or "" for same-origin.
  function normalizeApiBase(raw) {
    var value = String(raw == null ? '' : raw).trim().replace(/\/+$/, '');
    if (!value) return { ok: true, origin: '' };
    if (value === 'local' || value === 'same-origin' || value === 'same origin') {
      return { ok: true, origin: '' };
    }
    // Bare host without a scheme ("my-app.onrender.com") -> assume https.
    if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(value) && value.indexOf('/') === -1) {
      value = 'https://' + value;
    } else if (value.charAt(0) === '/' && value.charAt(1) !== '/') {
      return { ok: true, origin: '' }; // relative path -> same origin
    } else if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(value) && value.indexOf('://') === -1) {
      if (value.indexOf('.') !== -1 || value.indexOf(':') !== -1) value = 'https://' + value;
      else return { ok: true, origin: '' };
    }
    try {
      var parsed = new URL(value);
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        return { ok: false, error: 'URL must start with http:// or https://' };
      }
      return { ok: true, origin: parsed.origin };
    } catch (e) {
      return { ok: false, error: 'That does not look like a valid URL.' };
    }
  }

  function setApiBase(origin, opts) {
    opts = opts || {};
    apiBase = origin || '';
    if (apiBase) {
      try { localStorage.setItem(API_KEY, apiBase); } catch (e) { /* private mode */ }
    } else if (!opts.keepStored) {
      try { localStorage.removeItem(API_KEY); } catch (e) { /* private mode */ }
    }
    updateBackendUi();
  }

  function currentBackendLabel() {
    return apiBase || 'same origin (' + location.origin + ')';
  }

  function updateBackendUi() {
    var label = apiBase || 'same origin';
    if (backendPill) {
      backendPill.textContent = label;
      backendPill.title = 'Backend: ' + currentBackendLabel() + ' - click Backend to change';
      if (apiBase) backendPill.setAttribute('data-remote', 'true');
      else backendPill.removeAttribute('data-remote');
    }
    if (backendCurrent) backendCurrent.textContent = currentBackendLabel();
    if (backendUrl && document.activeElement !== backendUrl) backendUrl.value = apiBase;
    statusEl.title = 'Backend: ' + currentBackendLabel();
  }

  var params = new URLSearchParams(location.search);
  var fromQuery = params.get('api');
  if (fromQuery !== null) {
    // ?api= present (even if empty) overrides the remembered backend.
    var parsed = normalizeApiBase(fromQuery);
    if (parsed.ok) {
      setApiBase(parsed.origin);
    } else {
      try { apiBase = localStorage.getItem(API_KEY) || ''; } catch (e) { apiBase = ''; }
      updateBackendUi();
      showBanner('The ?api= URL in the address bar looks invalid (' + parsed.error + ' ' +
        'Falling back to the remembered backend. Paste a URL like https://your-backend-host below.');
      if (backendUrl) backendUrl.value = fromQuery;
    }
  } else {
    try { apiBase = localStorage.getItem(API_KEY) || ''; } catch (e) { apiBase = ''; }
    // Validate anything remembered from an older version.
    var stored = normalizeApiBase(apiBase);
    apiBase = stored.ok ? stored.origin : '';
    updateBackendUi();
  }

  function api(path) {
    return (apiBase ? apiBase.replace(/\/$/, '') : '') + path;
  }

  function setStatus(state, label) {
    statusEl.dataset.state = state;
    statusEl.textContent = label;
  }

  // ------------------------------------------------------------- backend box

  function showBanner(message) {
    if (!backendBanner) return;
    if (message && backendMsg) backendMsg.textContent = message;
    backendBanner.hidden = false;
    bannerDismissed = false;
    updateBackendUi();
  }

  function hideBanner() {
    if (!backendBanner) return;
    backendBanner.hidden = true;
  }

  function shareUrl() {
    var url = new URL(location.href);
    if (apiBase) url.searchParams.set('api', apiBase);
    else url.searchParams.delete('api');
    return url.toString();
  }

  function connectToBackend(raw) {
    var parsed = normalizeApiBase(raw);
    if (!parsed.ok) {
      showBanner('Could not use that backend URL: ' + parsed.error + ' ' +
        'Expected something like https://carebridge.onrender.com');
      return false;
    }
    if (location.protocol === 'https:' && parsed.origin.indexOf('http://') === 0) {
      showBanner('That backend uses plain http://, which browsers block from an https:// page ' +
        '(mixed content). Please use an https:// backend URL - Render, Fly.io and most hosts ' +
        'provide one automatically.');
      return false;
    }
    closeStream();
    try {
      sessionStorage.removeItem(SESSION_KEY);
      sessionStorage.removeItem(SESSION_API_KEY);
    } catch (e) { /* ignore */ }
    sessionId = null;
    ended = false;
    text = '';
    render();
    setApiBase(parsed.origin);
    try {
      history.replaceState(null, '', shareUrl());
    } catch (e) { /* file:// etc. */ }
    hideBanner();
    createSession(true);
    return true;
  }

  if (backendForm) {
    backendForm.addEventListener('submit', function (event) {
      event.preventDefault();
      connectToBackend(backendUrl.value);
    });
  }
  if (backendLocal) {
    backendLocal.addEventListener('click', function () {
      connectToBackend('');
    });
  }
  if (backendDismiss) {
    backendDismiss.addEventListener('click', function () {
      bannerDismissed = true;
      hideBanner();
      cmdEl.focus();
    });
  }
  var btnBackend = document.getElementById('btn-backend');
  if (btnBackend) {
    btnBackend.addEventListener('click', function () {
      showBanner('Paste the public URL of your CareBridge backend (the server that runs ' +
        'web/server.js). It is remembered in this browser and can be shared as ?api=URL.');
      if (backendUrl) {
        backendUrl.value = apiBase;
        backendUrl.focus();
        backendUrl.select();
      }
    });
  }

  // ------------------------------------------------------------- rendering

  var ANSI_RE = /\u001b\[([0-9;]*)m/g;
  var COLORS = {
    30: 'ansi-black', 31: 'ansi-red', 32: 'ansi-green', 33: 'ansi-yellow',
    34: 'ansi-blue', 35: 'ansi-magenta', 36: 'ansi-cyan', 37: 'ansi-white',
    90: 'ansi-bright-black', 91: 'ansi-bright-red', 92: 'ansi-bright-green',
    93: 'ansi-bright-yellow', 94: 'ansi-bright-blue', 95: 'ansi-bright-magenta',
    96: 'ansi-bright-cyan', 97: 'ansi-bright-white'
  };

  function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function ansiToHtml(s) {
    var html = '';
    var last = 0;
    var open = false;
    var match;
    ANSI_RE.lastIndex = 0;
    while ((match = ANSI_RE.exec(s)) !== null) {
      html += escapeHtml(s.slice(last, match.index));
      last = match.index + match[0].length;
      var codes = match[1].split(';');
      if (open) { html += '</span>'; open = false; }
      for (var i = 0; i < codes.length; i++) {
        var code = parseInt(codes[i], 10);
        if (code === 0 || code === 39) continue;
        var cls = COLORS[code];
        if (cls) { html += '<span class="' + cls + '">'; open = true; }
        else if (code === 1) { html += '<span class="ansi-bold">'; open = true; }
      }
    }
    html += escapeHtml(s.slice(last));
    if (open) html += '</span>';
    return html;
  }

  function atBottom() {
    return terminalEl.scrollHeight - terminalEl.scrollTop - terminalEl.clientHeight < 48;
  }

  function render() {
    var stick = atBottom();
    outEl.innerHTML = ansiToHtml(text);
    if (stick) terminalEl.scrollTop = terminalEl.scrollHeight;
  }

  function append(chunk) {
    text += chunk;
    if (text.length > MAX_CHARS) text = text.slice(-MAX_CHARS);
    render();
  }

  function echo(line) {
    text += '\u203a ' + line + '\n';
    if (text.length > MAX_CHARS) text = text.slice(-MAX_CHARS);
    render();
  }

  // ----------------------------------------------------------------- session

  function post(path, body) {
    return fetch(api(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : '{}'
    });
  }

  function readErrorMessage(res) {
    return res.text().then(function (raw) {
      if (!raw) return '';
      try {
        var data = JSON.parse(raw);
        return data && data.error ? String(data.error) : '';
      } catch (e) {
        return raw.length < 300 ? raw : '';
      }
    }).catch(function () { return ''; });
  }

  function describeFailure(status, serverMessage, err) {
    var where = currentBackendLabel();
    if (err) {
      // fetch itself threw: DNS, offline, CORS, mixed content, backend asleep.
      if (location.protocol === 'https:' && apiBase.indexOf('http://') === 0) {
        return 'The backend URL uses plain http://, which browsers block from an https:// page. ' +
          'Use an https:// backend URL instead.';
      }
      if (!apiBase) {
        return 'Could not reach a CareBridge server at this origin (' + where + '). ' +
          'If this page is served by the Node backend, is it still running? ' +
          'If this is a static copy (e.g. GitHub Pages), paste your backend URL below - ' +
          'see "Where do I get a backend URL?".';
      }
      return 'Could not reach the backend at ' + where + ' (' + err.message + '). ' +
        'Is the server running and publicly reachable over HTTPS? Free hosts (Render, Fly.io) ' +
        'sleep when idle, so the first connection can take up to a minute - press Connect to retry. ' +
        'Also check that ' + where + '/api/health loads in a new tab.';
    }
    if (status === 405) {
      if (!apiBase) {
        return 'This copy of the page is static (HTTP 405 on POST /api/session): it can only serve ' +
          'files, so there is no CareBridge server here to talk to. Deploy the backend once ' +
          '(Render / Fly.io / Docker - see DEPLOY.md), then paste its https:// URL below.';
      }
      return 'The server at ' + where + ' refused POST /api/session (HTTP 405). That usually means ' +
        'the URL points at a static host (e.g. GitHub Pages) rather than the Node backend. ' +
        'Check the URL - opening ' + where + '/api/health should return {"ok":true}.';
    }
    if (status === 404) {
      return 'The server at ' + where + ' answered but has no POST /api/session endpoint (HTTP 404). ' +
        'Is this URL really a CareBridge backend? ' + where + '/api/health should return {"ok":true}.';
    }
    if (status === 503) {
      return 'The backend at ' + where + ' is running but its CareBridge binary is missing ' +
        '(HTTP 503). ' + (serverMessage || 'Run `make` (or `npm run build`) where the server runs, then retry.');
    }
    if (status === 429) {
      return 'Too many sessions were started from your network (HTTP 429). Wait a minute, then press Connect to retry.';
    }
    if (serverMessage) return 'The backend at ' + where + ' answered HTTP ' + status + ': ' + serverMessage;
    return 'The backend at ' + where + ' answered HTTP ' + status + '.';
  }

  function createSession(isRetry) {
    // Mixed content is blocked before fetch even runs - explain instead of failing silently.
    if (location.protocol === 'https:' && apiBase.indexOf('http://') === 0) {
      setStatus('error', 'unavailable');
      var mixed = describeFailure(0, '', new Error('mixed content'));
      append('\n[carebridge] ' + mixed + '\n');
      showBanner(mixed);
      return;
    }
    setStatus('connecting', 'starting\u2026');
    fetch(api('/api/session'), { method: 'POST' })
      .then(function (res) {
        if (res.ok) return res.json();
        return readErrorMessage(res).then(function (serverMessage) {
          var failure = new Error('HTTP ' + res.status);
          failure.status = res.status;
          failure.serverMessage = serverMessage;
          throw failure;
        });
      })
      .then(function (data) {
        sessionId = data.id;
        try {
          sessionStorage.setItem(SESSION_KEY, sessionId);
          sessionStorage.setItem(SESSION_API_KEY, apiBase);
        } catch (e) { /* private mode */ }
        ended = false;
        streamErrors = 0;
        if (!bannerDismissed) hideBanner();
        openStream();
      })
      .catch(function (err) {
        if (!isRetry && !err.status) {
          // A remembered session id may be stale, or a sleeping host may need a
          // moment to wake: clear the id and try once more before giving up.
          try {
            sessionStorage.removeItem(SESSION_KEY);
            sessionStorage.removeItem(SESSION_API_KEY);
          } catch (e) { /* ignore */ }
          sessionId = null;
          setTimeout(function () { createSession(true); }, 1500);
          return;
        }
        setStatus('error', 'unavailable');
        var detail = describeFailure(err.status || 0, err.serverMessage || '', err.status ? null : err);
        append('\n[carebridge] ' + detail + '\n');
        if (!bannerDismissed) showBanner(detail);
      });
  }

  function openStream() {
    if (source) { source.close(); source = null; }
    if (!sessionId) return;
    streamErrors = 0;
    var streamUrl = api('/api/session/' + sessionId + '/stream');
    try {
      source = new EventSource(streamUrl);
    } catch (err) {
      setStatus('error', 'unavailable');
      var detail = describeFailure(0, '', err);
      append('\n[carebridge] ' + detail + '\n');
      showBanner(detail);
      return;
    }

    source.onopen = function () {
      streamErrors = 0;
      setStatus(ended ? 'ended' : 'live', ended ? 'ended' : 'connected');
      busy = false;
      cmdEl.disabled = false;
      cmdEl.focus();
    };

    source.onmessage = function (event) {
      var msg;
      try { msg = JSON.parse(event.data); } catch (e) { return; }
      if (msg.type === 'snapshot') {
        if (!text) text = msg.text || '';
        render();
        busy = false;
        if (!ended) setStatus('live', 'connected');
      } else if (msg.type === 'out') {
        busy = false;
        append(msg.text || '');
        if (!ended) setStatus('live', 'connected');
      } else if (msg.type === 'exit') {
        ended = true;
        setStatus('ended', 'session ended');
        append('\n[carebridge] The application closed. Press Restart to start a new session.\n');
      }
    };

    source.onerror = function () {
      // EventSource retries on its own; just reflect the state. If it never
      // connects, the backend URL is probably wrong or asleep - validate once.
      streamErrors += 1;
      if (!ended) setStatus('connecting', 'reconnecting\u2026');
      if (streamErrors === 3) {
        fetch(api('/api/health'))
          .then(function (res) {
            if (!res.ok) throw new Error('HTTP ' + res.status);
          })
          .catch(function (err) {
            var detail = describeFailure(0, '', err);
            if (!bannerDismissed) showBanner(detail);
          });
      }
    };
  }

  function closeStream() {
    if (source) { source.close(); source = null; }
  }

  // ------------------------------------------------------------------- input

  function ensureSession() {
    if (sessionId) return true;
    append('[carebridge] No session yet - starting one now\u2026\n');
    createSession(true);
    return false;
  }

  function sendLine(line) {
    if (runningSequence || ended) return;
    if (!ensureSession()) return;
    var value = String(line);
    echo(value);
    history.push(value);
    if (history.length > 100) history.shift();
    historyIndex = history.length;
    busy = true;

    post('/api/session/' + sessionId + '/input', { line: value })
      .then(function (res) {
        if (res.status === 404 || res.status === 409) {
          // Session is gone or the process exited - start over transparently.
          try {
            sessionStorage.removeItem(SESSION_KEY);
            sessionStorage.removeItem(SESSION_API_KEY);
          } catch (e) { /* ignore */ }
          sessionId = null;
          text = '';
          createSession(true);
        } else if (!res.ok) {
          append('[carebridge] input rejected (' + res.status + ')\n');
        }
      })
      .catch(function () {
        setStatus('connecting', 'reconnecting\u2026');
      });
  }

  function runSequence(steps) {
    if (runningSequence) return;
    if (!ensureSession()) return;
    runningSequence = true;
    cmdEl.disabled = true;
    var i = 0;
    (function next() {
      if (i >= steps.length) {
        runningSequence = false;
        cmdEl.disabled = false;
        cmdEl.focus();
        return;
      }
      sendLine(steps[i++]);
      setTimeout(next, 600);
    })();
  }

  cmdEl.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
      var value = cmdEl.value;
      cmdEl.value = '';
      if (value.length) sendLine(value);
      event.preventDefault();
      return;
    }
    if (event.key === 'ArrowUp') {
      if (historyIndex > 0) { historyIndex -= 1; cmdEl.value = history[historyIndex]; }
      event.preventDefault();
      return;
    }
    if (event.key === 'ArrowDown') {
      if (historyIndex < history.length - 1) { historyIndex += 1; cmdEl.value = history[historyIndex]; }
      else { historyIndex = history.length; cmdEl.value = ''; }
      event.preventDefault();
    }
  });

  // Clicking anywhere in the terminal focuses the prompt, like a real console.
  terminalEl.addEventListener('click', function (event) {
    if (window.getSelection && String(window.getSelection())) return;
    if (event.target.tagName !== 'A') cmdEl.focus();
  });

  // ----------------------------------------------------------------- controls

  document.getElementById('btn-clear').addEventListener('click', function () {
    text = '';
    render();
    cmdEl.focus();
  });

  function restartSession(wipe) {
    if (!ensureSession()) return;
    text = '';
    render();
    append(wipe
      ? '[carebridge] Resetting data to the sample dataset\u2026\n'
      : '[carebridge] Restarting the application\u2026\n');
    post('/api/session/' + sessionId + '/restart', { wipe: Boolean(wipe) })
      .then(function (res) {
        if (res.status === 404) {
          try {
            sessionStorage.removeItem(SESSION_KEY);
            sessionStorage.removeItem(SESSION_API_KEY);
          } catch (e) { /* ignore */ }
          sessionId = null;
          createSession(true);
          return;
        }
        ended = false;
        setTimeout(openStream, 400);
      })
      .catch(function () { createSession(true); });
  }

  document.getElementById('btn-restart').addEventListener('click', function () {
    restartSession(false);
  });

  document.getElementById('btn-reset').addEventListener('click', function () {
    restartSession(true);
  });

  chipsEl.addEventListener('click', function (event) {
    var btn = event.target.closest('.chip');
    if (!btn) return;
    if (btn.dataset.seq) runSequence(btn.dataset.seq.split('|'));
    else if (btn.dataset.send) sendLine(btn.dataset.send);
  });

  // Sessions are deliberately kept alive across reloads (the id lives in
  // sessionStorage); the server reaps anything idle for longer than the TTL.
  // A session id only makes sense for the backend that issued it, so a
  // remembered id from a different backend is discarded.

  // -------------------------------------------------------------------- boot

  var remembered = null;
  var rememberedApi = null;
  try {
    remembered = sessionStorage.getItem(SESSION_KEY);
    rememberedApi = sessionStorage.getItem(SESSION_API_KEY);
  } catch (e) { /* private mode */ }
  if (rememberedApi === null) rememberedApi = ''; // ids stored by older clients
  if (remembered && rememberedApi !== apiBase) {
    remembered = null;
    try {
      sessionStorage.removeItem(SESSION_KEY);
      sessionStorage.removeItem(SESSION_API_KEY);
    } catch (e) { /* ignore */ }
  }
  if (remembered) {
    sessionId = remembered;
    openStream();
    // Validate it still exists; create a new one when it does not.
    fetch(api('/api/session/' + sessionId))
      .then(function (res) {
        if (!res.ok) {
          try {
            sessionStorage.removeItem(SESSION_KEY);
            sessionStorage.removeItem(SESSION_API_KEY);
          } catch (e) { /* ignore */ }
          closeStream();
          sessionId = null;
          createSession(true);
        }
      })
      .catch(function () { setStatus('connecting', 'reconnecting\u2026'); });
  } else {
    createSession(false);
  }

  cmdEl.focus();
})();
