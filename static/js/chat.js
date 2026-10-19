// Chat view: conversation list, message rendering, streaming the agent's replies.
import { $, $$, SHIELD, esc, icons, md, previewPdf, state, statusCopy, timeAgo, toast, uid } from './core.js';
import * as convos from './convos.js';
import { openStudio, renderStudio, setDocument } from './studio.js';

let streaming = null; // AbortController while a reply is streaming
const renderQueue = new Set();
let renderScheduled = false;

// ------------------------------------------------------------------ //
// Sidebar conversation list
// ------------------------------------------------------------------ //
export function renderConvoList() {
  const cur = convos.current();
  const list = $('#convo-list');
  const items = convos.all().filter(c => c.messages.length || c.id === cur.id);
  list.innerHTML = items.map(c => `
    <div class="convo-item ${c.id === cur.id ? 'active' : ''}" data-id="${c.id}">
      ${c.docId ? '<i data-lucide="file-lock-2" class="w-3.5 h-3.5 flex-none" style="color:#6ee7b7"></i>' : '<i data-lucide="message-square" class="w-3.5 h-3.5 flex-none"></i>'}
      <span class="title">${esc(c.title)}</span>
      <button class="del" data-del="${c.id}" title="Delete chat"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i></button>
    </div>`).join('') || '<div class="text-[12px] faint px-3">No chats yet</div>';
  icons(list);
}

function bindConvoList() {
  $('#convo-list').addEventListener('click', (e) => {
    const del = e.target.closest('[data-del]');
    if (del) {
      e.stopPropagation();
      if (streaming) return toast('Hold up — wait for the reply to finish', 'error');
      convos.remove(del.dataset.del);
      renderChat();
      return;
    }
    const item = e.target.closest('.convo-item');
    if (item && !streaming) {
      convos.select(item.dataset.id);
      renderChat();
      window.dispatchEvent(new CustomEvent('hx:navigate', { detail: 'chat' }));
    }
  });
}

export function newChat() {
  if (streaming) return;
  if (convos.current().messages.length) convos.create();
  renderChat();
  $('#composer-input').focus();
}

// ------------------------------------------------------------------ //
// Rendering
// ------------------------------------------------------------------ //
export function renderChat() {
  const c = convos.current();
  $('#chat-title').textContent = c.title;
  const inner = $('#messages-inner');
  if (!c.messages.length) {
    inner.innerHTML = heroHtml();
    $$('.suggestion', inner).forEach(s => s.addEventListener('click', () => send(s.dataset.prompt)));
  } else {
    inner.innerHTML = c.messages.map(messageHtml).join('');
  }
  icons(inner);
  renderConvoList();
  renderStudio();
  scrollToBottom(true);
}

const SUGGESTIONS = [
  ['file-lock-2', 'Write a security policy', 'Create a PDF: Acceptable Use & Password Policy for a 30-person software company. Include MFA, password manager and BYOD rules.'],
  ['fish', 'Is this phishing?', 'Is this phishing? "Your Microsoft 365 password expires today. Keep your current password: hxxps://m365-secure-login[.]top/keep"'],
  ['server-cog', 'Harden a server', 'Give me a hardening checklist for a fresh Ubuntu 24.04 web server (SSH, firewall, updates, logging).'],
  ['siren', 'Incident response', "We think a laptop has ransomware. What do we do in the first hour? Then make it a one-page PDF playbook."],
  ['scale', 'Privacy compliance', 'What do we need for GDPR if we run a small e-commerce store with EU customers? Make me a checklist.'],
  ['user-round-check', 'Personal privacy', 'How do I lock down my Instagram, WhatsApp and Google account against hijacking?'],
];

function heroHtml() {
  const name = esc(state.agentName);
  const org = esc(state.health?.branding?.organization || 'Hiderox Technologies');
  const genz = state.tone === 'genz';
  const title = genz ? `stay safe, stay <span class="grad-text">private</span>.` : `Your <span class="grad-text">security & privacy</span> co-pilot.`;
  const sub = genz
    ? `I'm ${name} by ${org} — your cyber bestie. Ask me about threats, privacy, compliance or literally anything, and I'll spin up polished PDFs on demand.`
    : `I'm ${name} by ${org}. Ask about security, privacy and compliance — or anything else — and I'll draft professional PDF documents on demand.`;
  return `
    <div class="hero">
      <div class="hero-orb" style="background:transparent;box-shadow:none;width:84px;height:84px">${SHIELD}</div>
      <h1 class="font-display">${title}</h1>
      <p>${sub}</p>
      <div class="suggestions" style="grid-template-columns:repeat(auto-fill,minmax(240px,1fr))">
        ${SUGGESTIONS.map(([ic, t, p]) => `
          <div class="suggestion card" data-prompt="${esc(p)}">
            <div class="s-title"><i data-lucide="${ic}"></i>${t}</div>
            <div class="s-sub">${esc(p.length > 110 ? p.slice(0, 108) + '…' : p)}</div>
          </div>`).join('')}
      </div>
    </div>`;
}

function messageHtml(m) {
  if (m.role === 'user') {
    return `<div class="msg user" data-id="${m.id}"><div class="bubble">${esc(m.content)}</div></div>`;
  }
  return `<div class="msg assistant" data-id="${m.id}">
    <div class="avatar" style="background:transparent">${SHIELD}</div>
    <div class="bubble">${assistantInner(m)}</div>
  </div>`;
}

function assistantInner(m) {
  const parts = [`<div class="msg-name">${esc(state.agentName)}<span class="faint font-normal">${m.ts ? timeAgo(m.ts) : ''}</span></div>`];
  if (m.privacy) {
    parts.push(`<span class="privacy-chip" title="Masked before sending to ${esc(m.privacy.provider)}, restored on your side">
      <i data-lucide="shield-check"></i>kept private: ${esc(m.privacy.items.join(', '))}</span>`);
  }
  if (m.content) parts.push(`<div class="md ${m.pending && !m.status ? 'cursor' : ''}">${md(m.content)}</div>`);
  if (m.pending && (m.status || !m.content)) {
    parts.push(`<div class="status-line"><span class="orb"></span><span class="shimmer">${esc(statusCopy(m.status || 'thinking'))}…</span></div>`);
  }
  if (m.doc) parts.push(docCardHtml(m.doc));
  if (m.docError) parts.push(`<div class="error-box"><b>PDF not created.</b> ${esc(m.docError)}</div>`);
  if (m.error) parts.push(`<div class="error-box"><b>Oops.</b> ${esc(m.error)}</div>`);
  return parts.join('');
}

export function docCardHtml(d) {
  const cls = (d.meta?.classification || '').toUpperCase();
  return `
    <div class="doc-card"><div class="doc-card-inner">
      <div class="qc-top">
        <div class="min-w-0">
          <div class="flex items-center gap-2 mb-1">
            <span class="badge badge-ok"><i data-lucide="check" class="w-3 h-3"></i>${d.updated ? 'UPDATED' : 'PDF READY'}</span>
            ${d.meta?.type ? `<span class="doc-kicker">${esc(d.meta.type)}</span>` : ''}
          </div>
          <div class="font-display font-semibold text-[17px]">${esc(d.title)}</div>
          <div class="text-[12px] muted">${d.meta?.subtitle ? esc(d.meta.subtitle) + ' · ' : ''}~${d.pages_hint} page${d.pages_hint === 1 ? '' : 's'} · ${d.words} words</div>
        </div>
        ${cls ? `<span class="cls cls-${esc(cls)}">${esc(cls)}</span>` : ''}
      </div>
      <div class="qc-actions mt-3">
        <button class="btn btn-sm btn-primary" data-act="studio" data-doc="${esc(d.id)}"><i data-lucide="file-pen-line"></i>Edit</button>
        <button class="btn btn-sm" data-act="preview" data-url="${esc(d.pdf_url)}" data-title="${esc(d.title)}"><i data-lucide="eye"></i>Preview</button>
        <a class="btn btn-sm" href="${esc(d.pdf_url)}" download><i data-lucide="download"></i>PDF</a>
        <a class="btn btn-sm btn-ghost" href="${esc(d.md_url)}" download><i data-lucide="file-code-2"></i>.md</a>
      </div>
    </div></div>`;
}

function rerenderMessage(m) {
  renderQueue.add(m);
  if (renderScheduled) return;
  renderScheduled = true;
  requestAnimationFrame(() => {
    renderScheduled = false;
    for (const msg of renderQueue) {
      const el = $(`.msg[data-id="${msg.id}"] .bubble`);
      if (el) { el.innerHTML = assistantInner(msg); icons(el); }
    }
    renderQueue.clear();
    scrollToBottom();
  });
}

function scrollToBottom(force = false) {
  const box = $('#messages');
  if (force || box.scrollHeight - box.scrollTop - box.clientHeight < 160) box.scrollTop = box.scrollHeight;
}

// ------------------------------------------------------------------ //
// Sending + streaming
// ------------------------------------------------------------------ //
export async function send(text) {
  text = (text || '').trim();
  if (!text || streaming) return;
  const c = convos.current();
  $('#composer-input').value = '';
  autosize();

  c.messages.push({ id: uid(), role: 'user', content: text, ts: new Date().toISOString() });
  const reply = { id: uid(), role: 'assistant', content: '', ts: new Date().toISOString(), pending: true, status: '' };
  c.messages.push(reply);
  convos.touch(c);
  renderChat();

  streaming = new AbortController();
  setSending(true);
  try {
    const resp = await fetch('/api/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: convos.historyFor(c), doc_id: c.docId }),
      signal: streaming.signal,
      credentials: 'same-origin',
    });
    if (resp.status === 401) { location.href = '/login'; return; }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop();
      for (const raw of events) {
        const line = raw.trim();
        if (!line.startsWith('data:')) continue;
        let ev;
        try { ev = JSON.parse(line.slice(5)); } catch { continue; }
        handleEvent(c, reply, ev);
      }
    }
  } catch (err) {
    if (err.name === 'AbortError') reply.content += reply.content ? '\n\n_(stopped)_' : '_(stopped)_';
    else reply.error = `Network error: ${err.message}`;
  } finally {
    reply.pending = false;
    reply.status = '';
    streaming = null;
    setSending(false);
    convos.touch(c);
    rerenderMessage(reply);
    renderConvoList();
  }
}

function handleEvent(c, reply, ev) {
  switch (ev.type) {
    case 'status': reply.status = ev.content; break;
    case 'privacy': reply.privacy = { items: ev.items, provider: ev.provider }; break;
    case 'token': reply.status = ''; reply.content += ev.content; break;
    case 'document':
      reply.doc = ev;
      setDocument(c, ev);
      if (window.innerWidth > 1280) openStudio();
      toast(`${ev.title} is ready`, 'success');
      window.dispatchEvent(new CustomEvent('hx:documents-changed'));
      break;
    case 'document_error': reply.docError = ev.error; break;
    case 'final': reply.content = ev.text || reply.content; reply.status = ''; break;
    case 'error': reply.error = ev.error; reply.status = ''; break;
  }
  rerenderMessage(reply);
}

function setSending(on) {
  const btn = $('#btn-send');
  btn.classList.toggle('stop', on);
  btn.innerHTML = on ? '<i data-lucide="square"></i>' : '<i data-lucide="arrow-up"></i>';
  btn.disabled = on ? false : !$('#composer-input').value.trim();
  btn.setAttribute('aria-label', on ? 'Stop' : 'Send');
  icons(btn);
}

function autosize() {
  const t = $('#composer-input');
  t.style.height = 'auto';
  t.style.height = Math.min(t.scrollHeight, 220) + 'px';
  if (!streaming) $('#btn-send').disabled = !t.value.trim();
}

/** Start a chat that asks the agent to write a document from a template prompt. */
export function startWithPrompt(prompt) {
  if (streaming) return;
  if (convos.current().messages.length) convos.create();
  renderChat();
  window.dispatchEvent(new CustomEvent('hx:navigate', { detail: 'chat' }));
  send(prompt);
}

// ------------------------------------------------------------------ //
// Wiring
// ------------------------------------------------------------------ //
export function initChat() {
  bindConvoList();
  const input = $('#composer-input');
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      send(input.value);
    }
  });
  $('#btn-send').addEventListener('click', () => (streaming ? streaming.abort() : send(input.value)));
  $$('[data-insert]').forEach(b => b.addEventListener('click', () => {
    input.value = b.dataset.insert;
    autosize();
    input.focus();
    const i = input.value.indexOf('[');
    if (i >= 0) input.setSelectionRange(i, input.value.indexOf(']', i) + 1);
  }));
  $('#btn-new-chat').addEventListener('click', () => {
    newChat();
    window.dispatchEvent(new CustomEvent('hx:navigate', { detail: 'chat' }));
  });
  $('#messages').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    if (b.dataset.act === 'preview') previewPdf(b.dataset.url, b.dataset.title);
    if (b.dataset.act === 'studio') {
      const c = convos.current();
      c.docId = b.dataset.doc;
      convos.save();
      openStudio();
    }
  });
  renderChat();
}

export const isStreaming = () => !!streaming;
