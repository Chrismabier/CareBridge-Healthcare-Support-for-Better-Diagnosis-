/* CareBridge console client.
 * Streams the real C++ console application (via the Node server) into the browser.
 * Transport: Server-Sent Events for output, plain POST for keystrokes.
 */
(function () {
  'use strict';

  var outEl = document.getElementById('out');
  var cmdEl = document.getElementById('cmd');
  var statusEl = document.getElementById('status');
  var terminalEl = document.getElementById('terminal');
  var chipsEl = document.getElementById('chips');

  var SESSION_KEY = 'carebridge.session';
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

  // ----------------------------------------------------------------- config

  var params = new URLSearchParams(location.search);
  var fromQuery = params.get('api');
  if (fromQuery) {
    try {
      apiBase = new URL(fromQuery, location.href).origin;
      localStorage.setItem(API_KEY, apiBase);
    } catch (e) {
      apiBase = '';
    }
  } else {
    apiBase = localStorage.getItem(API_KEY) || '';
  }

  function api(path) {
    return (apiBase ? apiBase.replace(/\/$/, '') : '') + path;
  }

  function setStatus(state, label) {
    statusEl.dataset.state = state;
    statusEl.textContent = label;
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

  function createSession(isRetry) {
    setStatus('connecting', 'starting\u2026');
    return fetch(api('/api/session'), { method: 'POST' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        sessionId = data.id;
        sessionStorage.setItem(SESSION_KEY, sessionId);
        ended = false;
        openStream();
      })
      .catch(function (err) {
        if (isRetry) {
          setStatus('error', 'unavailable');
          append(
            '\n[carebridge] Could not reach the CareBridge server (' + err.message + ').\n' +
            'If you are on a static copy of this page, connect it to a running backend:\n' +
            '  ' + location.pathname + '?api=https://your-carebridge-host\n'
          );
        } else {
          // Session id may be stale (server restarted) - start a fresh one.
          sessionStorage.removeItem(SESSION_KEY);
          sessionId = null;
          setTimeout(function () { createSession(true); }, 1200);
        }
      });
  }

  function openStream() {
    if (source) { source.close(); source = null; }
    if (!sessionId) return;
    source = new EventSource(api('/api/session/' + sessionId + '/stream'));

    source.onopen = function () {
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
      // EventSource retries on its own; just reflect the state.
      if (!ended) setStatus('connecting', 'reconnecting\u2026');
    };
  }

  function closeStream() {
    if (source) { source.close(); source = null; }
  }

  // ------------------------------------------------------------------- input

  function sendLine(line) {
    if (runningSequence || ended) return;
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
          sessionStorage.removeItem(SESSION_KEY);
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

  document.getElementById('btn-restart').addEventListener('click', function () {
    text = '';
    render();
    append('[carebridge] Restarting the application\u2026\n');
    post('/api/session/' + sessionId + '/restart', { wipe: false })
      .then(function () {
        ended = false;
        setTimeout(openStream, 400);
      })
      .catch(function () { createSession(true); });
  });

  document.getElementById('btn-reset').addEventListener('click', function () {
    text = '';
    render();
    append('[carebridge] Resetting data to the sample dataset\u2026\n');
    post('/api/session/' + sessionId + '/restart', { wipe: true })
      .then(function () {
        ended = false;
        setTimeout(openStream, 400);
      })
      .catch(function () { createSession(true); });
  });

  chipsEl.addEventListener('click', function (event) {
    var btn = event.target.closest('.chip');
    if (!btn) return;
    if (btn.dataset.seq) runSequence(btn.dataset.seq.split('|'));
    else if (btn.dataset.send) sendLine(btn.dataset.send);
  });

  // Sessions are deliberately kept alive across reloads (the id lives in
  // sessionStorage); the server reaps anything idle for longer than the TTL.

  // -------------------------------------------------------------------- boot

  var remembered = sessionStorage.getItem(SESSION_KEY);
  if (remembered) {
    sessionId = remembered;
    openStream();
    // Validate it still exists; create a new one when it does not.
    fetch(api('/api/session/' + sessionId))
      .then(function (res) {
        if (!res.ok) {
          sessionStorage.removeItem(SESSION_KEY);
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
