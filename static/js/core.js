// Shared helpers + app state. Every other module imports from here.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export const state = {
  health: null,
  tone: 'genz',
  agentName: 'Aegis',
};

// ------------------------------------------------------------------ //
// API
// ------------------------------------------------------------------ //
export async function api(path, { method = 'GET', body, form } = {}) {
  const opts = { method, headers: {}, credentials: 'same-origin' };
  if (form) {
    opts.body = form;
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  if (resp.status === 401) { location.href = '/login'; return { ok: false, error: 'Signed out' }; }
  let data;
  try { data = await resp.json(); } catch { data = { ok: false, error: `HTTP ${resp.status}` }; }
  if (!resp.ok && data.ok === undefined) data.ok = false;
  return data;
}

// ------------------------------------------------------------------ //
// Storage (never throws — private mode / blocked storage just means no persistence)
// ------------------------------------------------------------------ //
export const store = {
  get(key, fallback = null) {
    try { const v = localStorage.getItem('hx.' + key); return v == null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem('hx.' + key, JSON.stringify(value)); } catch { /* ignore */ }
  },
};

// ------------------------------------------------------------------ //
// UI bits
// ------------------------------------------------------------------ //
export function esc(str) {
  if (str == null) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

export function icons(root) {
  if (window.lucide) window.lucide.createIcons({ attrs: { 'stroke-width': 2 }, nameAttr: 'data-lucide', root });
}

export function toast(msg, kind = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  const icon = { success: 'check-circle-2', error: 'alert-triangle', info: 'shield' }[kind] || 'shield';
  el.innerHTML = `<i data-lucide="${icon}"></i><span>${esc(msg)}</span>`;
  $('#toasts').appendChild(el);
  icons(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; }, 3600);
  setTimeout(() => el.remove(), 4000);
}

export function md(text) {
  const html = window.marked ? window.marked.parse(text || '', { breaks: true, gfm: true }) : esc(text).replace(/\n/g, '<br>');
  return window.DOMPurify ? window.DOMPurify.sanitize(html) : esc(text);
}

export function modal(html, { wide = false, onMount } = {}) {
  const root = $('#modal-root');
  const bg = document.createElement('div');
  bg.className = 'modal-bg';
  bg.innerHTML = `<div class="modal ${wide ? 'wide' : ''}">${html}</div>`;
  const close = () => { bg.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  bg.addEventListener('mousedown', (e) => { if (e.target === bg) close(); });
  document.addEventListener('keydown', onKey);
  root.appendChild(bg);
  icons(bg);
  bg.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', close));
  if (onMount) onMount(bg.firstElementChild, close);
  return close;
}

export function previewPdf(url, title = 'Preview') {
  const sep = url.includes('?') ? '&' : '?';
  modal(`
    <div class="flex items-center gap-2 mb-3 px-1">
      <i data-lucide="file-lock-2" class="w-5 h-5" style="color:#6ee7b7"></i>
      <div class="font-display font-semibold truncate">${esc(title)}</div>
      <a class="btn btn-sm ml-auto" href="${esc(url)}" download><i data-lucide="download"></i>Download</a>
      <button class="btn btn-ghost btn-icon" data-close><i data-lucide="x"></i></button>
    </div>
    <iframe src="${esc(url + sep + 'inline=1&t=' + Date.now())}"></iframe>`, { wide: true });
}

export function debounce(fn, ms = 250) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

export function uid() {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
}

export function timeAgo(iso) {
  const d = new Date(iso);
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)}d ago`;
  return d.toLocaleDateString();
}

// Tone-aware microcopy for agent status lines.
const STATUS_COPY = {
  genz: {
    thinking: 'scanning the threat landscape',
    'writing your document': 'drafting your doc, no cap',
    'rendering the PDF': 'stamping it into a PDF',
  },
};
export function statusCopy(s) {
  return (STATUS_COPY[state.tone] || {})[s] || s;
}

export const SHIELD = '<img src="/static/img/logo.svg" alt="" style="width:100%;height:100%">';
