/* Bridge - AI Personal Assistant frontend.
 * Vanilla JS, no build step. Voice in = Web Speech API (SpeechRecognition),
 * voice out = speechSynthesis. All API calls are same-origin relative URLs. */
'use strict';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

/* localStorage can throw or be partitioned away when the app runs inside a
 * cross-origin preview iframe - never let storage break login. The token
 * always lives in memory first; storage is best-effort, with a sessionStorage
 * second chance. A bridge_token cookie (set by the server) is the third net. */
const store = {
  mem: {},
  get(key) {
    try { const v = localStorage.getItem(key); if (v) return v; } catch { /* blocked */ }
    try { const v = sessionStorage.getItem(key); if (v) return v; } catch { /* blocked */ }
    return this.mem[key] || '';
  },
  set(key, value) {
    this.mem[key] = value;
    try { localStorage.setItem(key, value); } catch { /* blocked */ }
    try { sessionStorage.setItem(key, value); } catch { /* blocked */ }
  },
  remove(key) {
    delete this.mem[key];
    try { localStorage.removeItem(key); } catch { /* blocked */ }
    try { sessionStorage.removeItem(key); } catch { /* blocked */ }
  },
};

const state = {
  token: store.get('bridge_token'),
  user: null,
  conversationId: null,
  documents: [],
  recognition: null,
  listening: false,
  reminderTimer: null,
};

/* -------------------------------------------------------------- utilities */
function toast(message, kind = '', timeout = 4500) {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = message;
  const close = document.createElement('button');
  close.className = 'btn btn-ghost btn-sm';
  close.textContent = 'Dismiss';
  close.onclick = () => el.remove();
  el.appendChild(close);
  $('#toasts').appendChild(el);
  if (timeout) setTimeout(() => el.remove(), timeout);
  return el;
}

function fmtDT(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

let verifyingSession = null;
async function handle401() {
  /* A single 401 must not nuke the session (proxies may drop the
   * Authorization header on some routes, tokens can race a restart, ...).
   * Confirm against /api/auth/me once; only log out if that also fails. */
  if (!state.token) { logout(); return; }
  if (!verifyingSession) {
    verifyingSession = (async () => {
      try {
        const me = await api('/api/auth/me', { silent401: true });
        state.user = me.user; // session is fine - keep going
      } catch {
        toast('Your session expired - please log in again.', 'error');
        logout();
      } finally { verifyingSession = null; }
    })();
  }
  return verifyingSession;
}

async function api(path, { method = 'GET', body = null, form = null, auth = true, silent401 = false } = {}) {
  const headers = {};
  if (auth && state.token) {
    headers.Authorization = `Bearer ${state.token}`;
    headers['X-Bridge-Token'] = state.token; // fallback if a proxy strips Authorization
  }
  let payload = form;
  if (body !== null) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, { method, headers, body: payload, credentials: 'same-origin' });
  } catch (err) {
    throw new Error('Network error - is the server running?');
  }
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { /* non-JSON */ }
  if (!res.ok) {
    if (res.status === 401 && !silent401) handle401();
    const msg = data?.error?.message || `Request failed (HTTP ${res.status})`;
    const error = new Error(msg);
    error.status = res.status;
    throw error;
  }
  return data;
}

/* tiny safe Markdown renderer (escape first, then format) */
function renderMarkdown(src) {
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const codeBlocks = [];
  let text = esc(src).replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    codeBlocks.push(code.replace(/\n$/, ''));
    return `\u0001${codeBlocks.length - 1}\u0001`;
  });
  const inline = (s) => s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^\*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

  const lines = text.split('\n');
  let html = '', inList = false, listTag = 'ul', inTable = false;
  const closeList = () => { if (inList) { html += `</${listTag}>`; inList = false; } };
  const closeTable = () => { if (inTable) { html += '</tbody></table>'; inTable = false; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const codeRef = line.trim().match(/^\u0001(\d+)\u0001$/);
    if (codeRef) { closeList(); closeTable(); html += `<pre><code>${codeBlocks[+codeRef[1]]}</code></pre>`; continue; }
    if (/^\|.*\|$/.test(line.trim())) {
      const cells = line.trim().slice(1, -1).split('|').map((c) => c.trim());
      const next = (lines[i + 1] || '').trim();
      if (/^\|[\s|:-]+\|$/.test(next)) {
        closeList(); html += '<table><thead><tr>' + cells.map((c) => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>';
        inTable = true; i++; continue;
      }
      if (inTable) { html += '<tr>' + cells.map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>'; continue; }
    } else closeTable();
    const heading = line.match(/^(#{1,3})\s+(.+)/);
    if (heading) { closeList(); html += `<h${heading[1].length + 2}>${inline(heading[2])}</h${heading[1].length + 2}>`; continue; }
    const bullet = line.match(/^\s*[-*]\s+(.+)/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.+)/);
    if (bullet || numbered) {
      const tag = bullet ? 'ul' : 'ol';
      if (!inList || listTag !== tag) { closeList(); html += `<${tag}>`; inList = true; listTag = tag; }
      const item = (bullet || numbered)[1].replace(/^\[ \]\s*/, '☐ ').replace(/^\[x\]\s*/i, '☑ ');
      html += `<li>${inline(item)}</li>`; continue;
    }
    closeList();
    if (line.trim()) html += `<p>${inline(line)}</p>`;
  }
  closeList(); closeTable();
  return html || '<p></p>';
}

function stripForSpeech(md) {
  return md
    .replace(/```[\s\S]*?```/g, ' (code example on screen) ')
    .replace(/\|[^\n]*\|/g, ' ')
    .replace(/[#>*_`\-]{1,3}/g, ' ')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[⏰✅📝📄💻🎉✍️🔺🚀✨]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/* ---------------------------------------------------------------- speech */
let speaking = false;
function speak(text) {
  if (!('speechSynthesis' in window)) { toast('Text-to-speech is not supported in this browser.', 'error'); return; }
  stopSpeaking();
  const clean = stripForSpeech(text);
  if (!clean) return;
  const chunks = clean.match(/[^.!?\n]+[.!?]+|\S[^.!?\n]*$/g) || [clean];
  const voices = speechSynthesis.getVoices();
  const voice = voices.find((v) => v.lang && v.lang.startsWith(navigator.language.slice(0, 2))) || voices[0];
  chunks.slice(0, 12).forEach((chunk, idx) => {
    const utter = new SpeechSynthesisUtterance(chunk.trim());
    if (voice) utter.voice = voice;
    utter.rate = 1.02;
    if (idx === 0) utter.onstart = () => { speaking = true; $('#stop-speak-btn').classList.remove('hidden'); };
    utter.onend = utter.onerror = () => {
      if (idx === Math.min(chunks.length, 12) - 1) { speaking = false; $('#stop-speak-btn').classList.add('hidden'); }
    };
    speechSynthesis.speak(utter);
  });
}
function stopSpeaking() {
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  speaking = false;
  $('#stop-speak-btn')?.classList.add('hidden');
}

function setupRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const mic = $('#mic-btn');
  if (!SR) {
    mic.disabled = true;
    mic.title = 'Voice input needs Chrome or Edge (Web Speech API). Typing works everywhere.';
    $('#voice-hint').textContent = '🎤 Voice input is not supported in this browser (try Chrome/Edge). Everything else works by typing.';
    return;
  }
  $('#voice-hint').textContent = '🎤 Voice ready: tap the mic and say e.g. “Remind me to call the bank tomorrow at 10 a.m.” — it sends automatically.';
  const rec = new SR();
  rec.lang = navigator.language || 'en-US';
  rec.interimResults = true;
  rec.continuous = false;
  let finalText = '';
  rec.onresult = (event) => {
    let interim = '';
    for (const result of event.results) {
      if (result.isFinal) finalText += result[0].transcript;
      else interim += result[0].transcript;
    }
    $('#voice-status-text').textContent = `Listening… “${(finalText + ' ' + interim).trim()}”`;
    $('#chat-input').value = (finalText + interim).trim();
    autoGrow($('#chat-input'));
  };
  rec.onend = () => {
    state.listening = false;
    mic.classList.remove('listening');
    $('#voice-status').classList.add('hidden');
    const text = $('#chat-input').value.trim();
    finalText = '';
    if (text && state.autoSendVoice !== false) $('#chat-form').requestSubmit();
  };
  rec.onerror = (event) => {
    state.listening = false;
    mic.classList.remove('listening');
    $('#voice-status').classList.add('hidden');
    const hints = {
      'not-allowed': 'Microphone permission denied - allow mic access in the browser, then try again.',
      'no-speech': "I didn't hear anything - tap the mic and speak again.",
      'audio-capture': 'No microphone found on this device.',
      network: "The browser's speech service needs an internet connection.",
    };
    toast(hints[event.error] || `Voice input error: ${event.error}`, 'error');
  };
  state.recognition = rec;
  mic.addEventListener('click', () => {
    if (state.listening) { rec.stop(); return; }
    stopSpeaking();
    try {
      finalText = '';
      $('#voice-status-text').textContent = 'Listening… speak now';
      $('#voice-status').classList.remove('hidden');
      mic.classList.add('listening');
      state.listening = true;
      rec.start();
    } catch { /* already started */ }
  });
}

/* ------------------------------------------------------------------ auth */
function showAuth() {
  $('#auth-screen').classList.remove('hidden');
  $('#app').classList.add('hidden');
}
function showApp() {
  $('#auth-screen').classList.add('hidden');
  $('#app').classList.remove('hidden');
}
function logout() {
  state.token = '';
  state.user = null;
  store.remove('bridge_token');
  fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(() => {});
  if (state.reminderTimer) clearInterval(state.reminderTimer);
  showAuth();
}
async function onLoggedIn({ token, user }) {
  state.token = token;
  state.user = user;
  store.set('bridge_token', token);
  /* Verify the token actually works before entering the app, so a bad
   * proxy/header setup shows a clear error on the form instead of the
   * old "logged in for half a second, then bounced" loop. */
  const me = await api('/api/auth/me', { silent401: true });
  state.user = me.user;
  $('#user-chip').textContent = `${me.user.name} · ${me.user.email}`;
  showApp();
  bootApp().catch((e) => toast(e.message, 'error'));
}

function setupAuth() {
  const setTab = (login) => {
    $('#tab-login').classList.toggle('active', login);
    $('#tab-register').classList.toggle('active', !login);
    $('#login-form').classList.toggle('hidden', !login);
    $('#register-form').classList.toggle('hidden', login);
    $('#auth-error').textContent = '';
  };
  $('#tab-login').onclick = () => setTab(true);
  $('#tab-register').onclick = () => setTab(false);
  const fail = (e) => { $('#auth-error').textContent = e.message; };
  $('#login-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try { await onLoggedIn(await api('/api/auth/login', { method: 'POST', auth: false, silent401: true, body: { email: $('#login-email').value, password: $('#login-password').value } })); }
    catch (e) { fail(e); }
  });
  $('#register-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try { await onLoggedIn(await api('/api/auth/register', { method: 'POST', auth: false, silent401: true, body: { name: $('#register-name').value, email: $('#register-email').value, password: $('#register-password').value } })); }
    catch (e) { fail(e); }
  });
  $('#demo-btn').addEventListener('click', async () => {
    try { await onLoggedIn(await api('/api/auth/demo', { method: 'POST', auth: false, silent401: true })); }
    catch (e) { fail(e); }
  });
  $('#logout-btn').addEventListener('click', logout);
}

/* ------------------------------------------------------------------ chat */
function addMessage({ role, content, citations = [], tools = [], pending = false }) {
  const box = $('#messages');
  box.querySelector('.welcome')?.remove();
  const el = document.createElement('article');
  el.className = `msg ${role}`;
  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.innerHTML = `<span>${role === 'user' ? '🧑 You' : '🤖 Bridge'}</span>`;
  tools.forEach((t) => {
    const chip = document.createElement('span');
    chip.className = 'tool-chip'; chip.textContent = `🛠 ${t}`;
    meta.appendChild(chip);
  });
  el.appendChild(meta);
  const body = document.createElement('div');
  body.className = 'body';
  body.innerHTML = pending
    ? '<span class="typing">Thinking <span></span><span></span><span></span></span>'
    : renderMarkdown(content);
  el.appendChild(body);
  if (citations.length) {
    const wrap = document.createElement('div');
    wrap.className = 'citations';
    wrap.innerHTML = '<span class="cite-title">📚 Sources (from your files)</span>';
    citations.forEach((c) => {
      const btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'cite';
      btn.innerHTML = `<strong>${escapeHtml(c.label)}</strong>${escapeHtml(c.snippet || '')}`;
      btn.title = 'Open this source';
      btn.onclick = () => openCitation(c);
      wrap.appendChild(btn);
    });
    el.appendChild(wrap);
  }
  if (role === 'assistant' && !pending) {
    const actions = document.createElement('div');
    actions.className = 'msg-actions';
    const speakBtn = document.createElement('button');
    speakBtn.type = 'button'; speakBtn.textContent = '🔊 Read aloud';
    speakBtn.onclick = () => speaking ? stopSpeaking() : speak(content);
    const copyBtn = document.createElement('button');
    copyBtn.type = 'button'; copyBtn.textContent = '📋 Copy';
    copyBtn.onclick = async () => { try { await navigator.clipboard.writeText(content); toast('Copied.'); } catch { toast('Copy failed in this browser.', 'error'); } };
    actions.append(speakBtn, copyBtn);
    el.appendChild(actions);
  }
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
  return el;
}
function escapeHtml(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function openCitation(c) {
  if (c.source_type === 'document' && c.document_id) {
    switchTab('documents');
    $('#side-panel').classList.add('open');
    const detail = $('#doc-detail');
    detail.classList.remove('hidden');
    detail.innerHTML = `<strong>${escapeHtml(c.label)}</strong><p>${escapeHtml(c.snippet || '')}</p>
      <div class="row"><button class="btn btn-primary btn-sm" id="cite-ask">Ask about this document</button>
      <button class="btn btn-ghost btn-sm" id="cite-close">Close</button></div>`;
    $('#cite-close').onclick = () => detail.classList.add('hidden');
    $('#cite-ask').onclick = () => { $('#scope-select').value = String(c.document_id); detail.classList.add('hidden'); $('#chat-input').focus(); toast('Chatting with this document only - ask your question.'); };
  } else if (c.note_id) {
    switchTab('notes');
    $('#side-panel').classList.add('open');
    editNote(c.note_id).catch((e) => toast(e.message, 'error'));
  }
}

function showWelcome() {
  const box = $('#messages');
  box.innerHTML = '';
  const el = document.createElement('div');
  el.className = 'welcome';
  el.innerHTML = `<h2>👋 Hi${state.user ? ' ' + escapeHtml(state.user.name.split(' ')[0]) : ''}, I'm Bridge</h2>
    <p>Upload a PDF and ask about it (I'll cite page numbers), dictate reminders and tasks by voice,
    search your notes, or ask me to explain a programming concept.</p>`;
  const grid = document.createElement('div');
  grid.className = 'suggest-grid';
  [
    'What can you do?',
    'Explain how a priority queue works',
    'Remind me to drink water in 30 minutes',
    'Add task: buy groceries by Friday at 6pm',
    'Summarise my document',
    "What's on my task list?",
  ].forEach((text) => {
    const b = document.createElement('button');
    b.className = 'hint'; b.type = 'button'; b.textContent = text;
    b.onclick = () => { $('#chat-input').value = text; $('#chat-form').requestSubmit(); };
    grid.appendChild(b);
  });
  el.appendChild(grid);
  box.appendChild(el);
}

async function sendChat(message) {
  addMessage({ role: 'user', content: message });
  const pending = addMessage({ role: 'assistant', content: '', pending: true });
  $('#send-btn').disabled = true;
  try {
    const scope = $('#scope-select').value;
    const data = await api('/api/chat', {
      method: 'POST',
      body: { message, conversation_id: state.conversationId, document_id: scope ? Number(scope) : null },
    });
    state.conversationId = data.conversation_id;
    pending.remove();
    addMessage({ role: 'assistant', content: data.reply, citations: data.citations, tools: data.tools_used });
    if ($('#autoread-toggle').checked) speak(data.reply);
    await loadConversations();
    for (const panel of data.refresh || []) refreshPanel(panel);
    refreshStats().catch(() => {});
  } catch (e) {
    pending.remove();
    addMessage({ role: 'assistant', content: `⚠️ Something went wrong: ${e.message}\n\nYour message wasn't lost - press **Send** to try again.` });
    $('#chat-input').value = message;
  } finally {
    $('#send-btn').disabled = false;
    $('#chat-input').focus();
  }
}

function autoGrow(textarea) {
  textarea.style.height = 'auto';
  textarea.style.height = Math.min(textarea.scrollHeight, 140) + 'px';
}

function setupChat() {
  const input = $('#chat-input');
  input.addEventListener('input', () => autoGrow(input));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#chat-form').requestSubmit(); }
  });
  $('#chat-form').addEventListener('submit', (ev) => {
    ev.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    input.value = '';
    autoGrow(input);
    sendChat(message);
  });
  $('#stop-speak-btn').addEventListener('click', stopSpeaking);
  $$('.hint[data-say]').forEach((b) => b.addEventListener('click', () => {
    input.value = b.dataset.say;
    $('#chat-form').requestSubmit();
  }));
  $('#seed-btn').addEventListener('click', async () => {
    try {
      const data = await api('/api/demo/seed', { method: 'POST' });
      toast(`Demo data ready (+${data.created.notes} notes, +${data.created.tasks} tasks, +${data.created.documents} doc). Try: “What data structure handles appointment requests?”`);
      ['documents', 'notes', 'tasks', 'reminders'].forEach(refreshPanel);
      refreshStats().catch(() => {});
    } catch (e) { toast(e.message, 'error'); }
  });
}

/* ----------------------------------------------------------- conversations */
async function loadConversations() {
  const { conversations } = await api('/api/conversations');
  const list = $('#conversation-list');
  list.innerHTML = '';
  conversations.forEach((c) => {
    const li = document.createElement('li');
    if (c.id === state.conversationId) li.className = 'active';
    const btn = document.createElement('button');
    btn.className = 'conv'; btn.type = 'button'; btn.textContent = c.title; btn.title = c.title;
    btn.onclick = () => openConversation(c.id);
    const del = document.createElement('button');
    del.className = 'conv-del'; del.type = 'button'; del.textContent = '✕'; del.title = 'Delete conversation';
    del.onclick = async () => {
      try {
        await api(`/api/conversations/${c.id}`, { method: 'DELETE' });
        if (state.conversationId === c.id) { state.conversationId = null; showWelcome(); }
        loadConversations();
      } catch (e) { toast(e.message, 'error'); }
    };
    li.append(btn, del);
    list.appendChild(li);
  });
}

async function openConversation(id) {
  state.conversationId = id;
  const { messages } = await api(`/api/conversations/${id}/messages`);
  $('#messages').innerHTML = '';
  messages.forEach((m) => addMessage({ role: m.role, content: m.content, citations: m.citations, tools: m.tools }));
  if (!messages.length) showWelcome();
  await loadConversations();
}

/* --------------------------------------------------------------- documents */
async function loadDocuments() {
  const { documents } = await api('/api/documents');
  state.documents = documents;
  const list = $('#document-list');
  list.innerHTML = documents.length ? '' : '<li class="empty">No documents yet.<br>Upload a PDF to ask questions about it.</li>';
  const scope = $('#scope-select');
  const current = scope.value;
  scope.innerHTML = '<option value="">All documents &amp; notes</option>';
  documents.forEach((d) => {
    const opt = document.createElement('option');
    opt.value = d.id; opt.textContent = `📄 ${d.title}`;
    scope.appendChild(opt);

    const li = document.createElement('li');
    li.className = 'item';
    li.innerHTML = `<div class="title">📄 ${escapeHtml(d.title)}</div>
      <div class="sub">${escapeHtml(d.filename)} · ${d.num_pages} page(s) · ${d.num_chunks} chunks indexed · ${fmtDT(d.created_at)}</div>`;
    const actions = document.createElement('div');
    actions.className = 'actions';
    const sumBtn = document.createElement('button');
    sumBtn.className = 'btn btn-ghost'; sumBtn.textContent = '✍️ Summarise';
    sumBtn.onclick = async () => {
      sumBtn.disabled = true; sumBtn.textContent = 'Summarising…';
      try {
        const data = await api(`/api/documents/${d.id}/summarize`, { method: 'POST' });
        const detail = $('#doc-detail');
        detail.classList.remove('hidden');
        detail.innerHTML = `<strong>Summary - ${escapeHtml(data.title)}</strong><div class="body"></div>
          <div class="row"><button class="btn btn-ghost btn-sm" id="sum-speak">🔊 Read aloud</button>
          <button class="btn btn-ghost btn-sm" id="sum-close">Close</button></div>`;
        detail.querySelector('.body').innerHTML = renderMarkdown(data.summary);
        $('#sum-close').onclick = () => detail.classList.add('hidden');
        $('#sum-speak').onclick = () => speak(data.summary);
        detail.scrollIntoView({ behavior: 'smooth' });
      } catch (e) { toast(e.message, 'error'); }
      finally { sumBtn.disabled = false; sumBtn.textContent = '✍️ Summarise'; }
    };
    const askBtn = document.createElement('button');
    askBtn.className = 'btn btn-primary'; askBtn.textContent = '💬 Ask';
    askBtn.onclick = () => {
      scope.value = String(d.id);
      $('#side-panel').classList.remove('open');
      $('#chat-input').focus();
      toast(`Now chatting with “${d.title}” only. Ask a question - answers will cite pages.`);
    };
    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-danger'; delBtn.textContent = '🗑 Delete';
    delBtn.onclick = async () => {
      if (!confirm(`Delete “${d.title}” and its index?`)) return;
      try { await api(`/api/documents/${d.id}`, { method: 'DELETE' }); loadDocuments(); refreshStats(); }
      catch (e) { toast(e.message, 'error'); }
    };
    actions.append(sumBtn, askBtn, delBtn);
    li.appendChild(actions);
    list.appendChild(li);
  });
  if ([...scope.options].some((o) => o.value === current)) scope.value = current;
}

async function uploadFile(file) {
  if (!file) return;
  const status = $('#upload-status');
  status.textContent = `⏳ Uploading & indexing “${file.name}”…`;
  const form = new FormData();
  form.append('file', file);
  try {
    const doc = await api('/api/documents/upload', { method: 'POST', form });
    status.textContent = '';
    toast(`Indexed “${doc.title}” - ${doc.num_pages} page(s), ${doc.num_chunks} chunks. Ask me about it!`);
    await loadDocuments();
    refreshStats().catch(() => {});
    $('#scope-select').value = String(doc.id);
  } catch (e) {
    status.textContent = '';
    toast(e.message, 'error', 7000);
  }
}

function setupDocuments() {
  const zone = $('#drop-zone');
  $('#file-input').addEventListener('change', (e) => { uploadFile(e.target.files[0]); e.target.value = ''; });
  ['dragenter', 'dragover'].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add('dragover'); }));
  ['dragleave', 'drop'].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove('dragover'); }));
  zone.addEventListener('drop', (e) => uploadFile(e.dataTransfer.files[0]));
}

/* ------------------------------------------------------------------- notes */
function noteItem(n) {
  const li = document.createElement('li');
  li.className = 'item';
  const tags = (n.tags || '').split(',').map((t) => t.trim()).filter(Boolean)
    .map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join('');
  li.innerHTML = `<div class="title">${escapeHtml(n.title)}</div>
    <div class="sub">${escapeHtml((n.body || '').slice(0, 140))}${(n.body || '').length > 140 ? '…' : ''}</div>
    <div class="sub">${tags} ${fmtDT(n.updated_at)}</div>`;
  const actions = document.createElement('div');
  actions.className = 'actions';
  const edit = document.createElement('button');
  edit.className = 'btn btn-ghost'; edit.textContent = '✏️ Edit';
  edit.onclick = () => fillNoteEditor(n);
  const del = document.createElement('button');
  del.className = 'btn btn-danger'; del.textContent = '🗑 Delete';
  del.onclick = async () => {
    if (!confirm(`Delete note “${n.title}”?`)) return;
    try { await api(`/api/notes/${n.id}`, { method: 'DELETE' }); loadNotes(); refreshStats(); }
    catch (e) { toast(e.message, 'error'); }
  };
  actions.append(edit, del);
  li.appendChild(actions);
  return li;
}
function fillNoteEditor(n) {
  $('#note-editor').classList.remove('hidden');
  $('#note-id').value = n?.id || '';
  $('#note-title').value = n?.title || '';
  $('#note-body').value = n?.body || '';
  $('#note-tags').value = n?.tags || '';
  $('#note-title').focus();
}
async function editNote(id) {
  fillNoteEditor(await api(`/api/notes/${id}`));
}
async function loadNotes() {
  const { notes } = await api('/api/notes');
  const list = $('#note-list');
  list.innerHTML = notes.length ? '' : '<li class="empty">No notes yet. Create one, or tell the chat “note: …”.</li>';
  notes.forEach((n) => list.appendChild(noteItem(n)));
}
function setupNotes() {
  $('#note-new-btn').onclick = () => fillNoteEditor(null);
  $('#note-cancel').onclick = () => $('#note-editor').classList.add('hidden');
  $('#note-editor').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const id = $('#note-id').value;
    const body = { title: $('#note-title').value, body: $('#note-body').value, tags: $('#note-tags').value };
    try {
      await api(id ? `/api/notes/${id}` : '/api/notes', { method: id ? 'PUT' : 'POST', body });
      $('#note-editor').classList.add('hidden');
      toast(id ? 'Note updated.' : 'Note saved.');
      loadNotes(); refreshStats();
    } catch (e) { toast(e.message, 'error'); }
  });
  $('#note-search-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const q = $('#note-search-input').value.trim();
    if (!q) { loadNotes(); return; }
    try {
      const { results } = await api(`/api/notes/search?q=${encodeURIComponent(q)}`);
      const list = $('#note-list');
      list.innerHTML = results.length ? '' : `<li class="empty">No notes match “${escapeHtml(q)}”.</li>`;
      results.forEach((r) => {
        const li = document.createElement('li');
        li.className = 'item';
        li.innerHTML = `<div class="title">${escapeHtml(r.label)}</div><div class="sub">${escapeHtml(r.snippet)}</div>
          <div class="sub">relevance ${Math.round((r.score || 0) * 100)}%</div>`;
        const open = document.createElement('button');
        open.className = 'btn btn-ghost btn-sm'; open.textContent = 'Open';
        open.onclick = () => editNote(r.note_id).catch((e) => toast(e.message, 'error'));
        const actions = document.createElement('div'); actions.className = 'actions'; actions.appendChild(open);
        li.appendChild(actions);
        list.appendChild(li);
      });
    } catch (e) { toast(e.message, 'error'); }
  });
}

/* ------------------------------------------------------------------- tasks */
async function loadTasks() {
  const { tasks } = await api('/api/tasks');
  const list = $('#task-list');
  list.innerHTML = tasks.length ? '' : '<li class="empty">No tasks. Add one above or say “add task: …” in chat.</li>';
  tasks.forEach((t) => {
    const li = document.createElement('li');
    const overdue = !t.done && t.due_at && new Date(t.due_at) < new Date();
    li.className = `item${t.done ? ' done' : ''}${overdue ? ' overdue' : ''}`;
    const row = document.createElement('div');
    row.className = 'task-row';
    const box = document.createElement('input');
    box.type = 'checkbox'; box.className = 'checkbox'; box.checked = t.done; box.title = 'Mark done/undone';
    box.onchange = async () => {
      try { await api(`/api/tasks/${t.id}`, { method: 'PATCH', body: { done: box.checked } }); loadTasks(); refreshStats(); }
      catch (e) { toast(e.message, 'error'); box.checked = !box.checked; }
    };
    const grow = document.createElement('div');
    grow.className = 'grow';
    grow.innerHTML = `<div class="title">${escapeHtml(t.title)}</div>
      <div class="sub"><span class="tag">${escapeHtml(t.list_name || 'Tasks')}</span>
      ${t.priority === 'high' ? '<span class="tag high">high 🔺</span>' : ''}
      ${t.due_at ? `· due ${fmtDT(t.due_at)}${overdue ? ' ⚠️ overdue' : ''}` : ''}</div>
      ${t.details ? `<div class="sub">${escapeHtml(t.details)}</div>` : ''}`;
    const del = document.createElement('button');
    del.className = 'btn btn-danger btn-sm'; del.textContent = '🗑';
    del.onclick = async () => {
      try { await api(`/api/tasks/${t.id}`, { method: 'DELETE' }); loadTasks(); refreshStats(); }
      catch (e) { toast(e.message, 'error'); }
    };
    row.append(box, grow, del);
    li.appendChild(row);
    list.appendChild(li);
  });
}
function setupTasks() {
  $('#task-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const due = $('#task-due').value;
    try {
      await api('/api/tasks', {
        method: 'POST',
        body: {
          title: $('#task-title').value,
          due_at: due ? new Date(due).toISOString() : null,
          priority: $('#task-priority').value,
          list_name: $('#task-list-name').value.trim() || 'Tasks',
        },
      });
      ev.target.reset();
      $('#task-priority').value = 'normal';
      toast('Task added.');
      loadTasks(); refreshStats();
    } catch (e) { toast(e.message, 'error'); }
  });
}

/* --------------------------------------------------------------- reminders */
async function loadReminders() {
  const { reminders } = await api('/api/reminders?include_done=true');
  const list = $('#reminder-list');
  const open = reminders.filter((r) => !r.done);
  list.innerHTML = open.length ? '' : '<li class="empty">No pending reminders.</li>';
  open.forEach((r) => {
    const li = document.createElement('li');
    const overdue = new Date(r.remind_at) < new Date();
    li.className = `item${overdue ? ' overdue' : ''}`;
    li.innerHTML = `<div class="title">⏰ ${escapeHtml(r.title)}</div>
      <div class="sub">${fmtDT(r.remind_at)}${overdue ? ' · due now' : ''}</div>`;
    const actions = document.createElement('div');
    actions.className = 'actions';
    const done = document.createElement('button');
    done.className = 'btn btn-primary'; done.textContent = '✓ Done';
    done.onclick = async () => { await api(`/api/reminders/${r.id}`, { method: 'PATCH', body: { done: true } }); loadReminders(); refreshStats(); };
    const snooze = document.createElement('button');
    snooze.className = 'btn btn-ghost'; snooze.textContent = '💤 +10 min';
    snooze.onclick = async () => {
      const when = new Date(Math.max(new Date(r.remind_at).getTime(), Date.now()) + 10 * 60000);
      await api(`/api/reminders/${r.id}`, { method: 'PATCH', body: { remind_at: when.toISOString() } });
      loadReminders();
    };
    const del = document.createElement('button');
    del.className = 'btn btn-danger'; del.textContent = '🗑 Delete';
    del.onclick = async () => { await api(`/api/reminders/${r.id}`, { method: 'DELETE' }); loadReminders(); refreshStats(); };
    actions.append(done, snooze, del);
    li.appendChild(actions);
    list.appendChild(li);
  });
}
function setupReminders() {
  $('#reminder-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try {
      await api('/api/reminders', {
        method: 'POST',
        body: { title: $('#reminder-title').value, remind_at: new Date($('#reminder-when').value).toISOString() },
      });
      ev.target.reset();
      toast('Reminder set.');
      loadReminders(); refreshStats();
    } catch (e) { toast(e.message, 'error'); }
  });
  $('#notify-btn').addEventListener('click', async () => {
    if (!('Notification' in window)) { toast('This browser does not support notifications.', 'error'); return; }
    const perm = await Notification.requestPermission();
    toast(perm === 'granted' ? '🔔 Notifications enabled - reminders will pop up even in another tab.' : 'Notifications not granted; in-app alerts still work.', perm === 'granted' ? '' : 'error');
  });
  const poll = async () => {
    if (!state.token) return;
    try {
      const { due } = await api('/api/reminders/due');
      due.forEach((r) => {
        toast(`⏰ Reminder: ${r.title}`, 'reminder', 15000);
        if ('Notification' in window && Notification.permission === 'granted') {
          new Notification('Bridge reminder', { body: r.title, tag: `reminder-${r.id}` });
        }
        if ($('#autoread-toggle').checked) speak(`Reminder: ${r.title}`);
      });
      if (due.length) loadReminders();
    } catch { /* stay silent between polls */ }
  };
  poll();
  state.reminderTimer = setInterval(poll, 25000);
}

/* ------------------------------------------------------------------- misc */
async function refreshStats() {
  const s = await api('/api/stats');
  $('#stats-chip').textContent = `${s.documents} docs · ${s.notes} notes · ${s.open_tasks} open tasks · ${s.pending_reminders} reminders · ${s.indexed_chunks} indexed chunks`;
}
function refreshPanel(name) {
  ({ documents: loadDocuments, notes: loadNotes, tasks: loadTasks, reminders: loadReminders })[name]?.()
    .catch((e) => toast(e.message, 'error'));
}
function switchTab(name) {
  $$('.panel-tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  $$('.tab-page').forEach((p) => p.classList.toggle('hidden', p.id !== `tab-${name}`));
}
function setupPanel() {
  $$('.panel-tab').forEach((t) => t.addEventListener('click', () => switchTab(t.dataset.tab)));
  $('#panel-toggle').addEventListener('click', () => $('#side-panel').classList.toggle('open'));
  $('#new-chat-btn').addEventListener('click', async () => {
    state.conversationId = null;
    showWelcome();
    await loadConversations();
    $('#chat-input').focus();
  });
}

async function bootApp() {
  const health = await api('/api/health', { auth: false, silent401: true });
  const badge = $('#llm-badge');
  if (health.llm.enabled) {
    badge.textContent = `🧠 ${health.llm.model}`;
    badge.title = `Connected to ${health.llm.base_url}`;
    badge.classList.remove('offline');
  } else {
    badge.textContent = '📴 Offline demo mode';
    badge.title = health.llm.hint || '';
    badge.classList.add('offline');
  }
  const me = await api('/api/auth/me', { silent401: true }).catch(() => null);
  if (me) { state.user = me.user; $('#user-chip').textContent = `${me.user.name} · ${me.user.email}`; }
  showWelcome();
  await Promise.all([loadConversations(), loadDocuments(), loadNotes(), loadTasks(), loadReminders(), refreshStats()]);
  const conversations = $$('#conversation-list .conv');
  if (conversations.length) conversations[0].click();
}

window.addEventListener('DOMContentLoaded', async () => {
  setupAuth();
  setupChat();
  setupDocuments();
  setupNotes();
  setupTasks();
  setupReminders();
  setupPanel();
  setupRecognition();
  if ('speechSynthesis' in window) speechSynthesis.getVoices(); // warm up voice list
  if (state.token) {
    try {
      const me = await api('/api/auth/me', { silent401: true });
      state.user = me.user;
      $('#user-chip').textContent = `${me.user.name} · ${me.user.email}`;
      showApp();
      await bootApp();
    } catch { logout(); }
  } else showAuth();
});
