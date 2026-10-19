// Hiderox Aegis — bootstrap: routing, health/status, theme, wiring.
import { $, $$, api, icons, state } from './core.js';
import { initChat, renderChat } from './chat.js';
import { initStudio } from './studio.js';
import { initDocuments, showDocuments } from './documents.js';
import { initToolkit } from './toolkit.js';
import { initSettings, showSettings } from './settings.js';

const VIEWS = ['chat', 'documents', 'toolkit', 'settings'];

function navigate(view, push = true) {
  if (!VIEWS.includes(view)) view = 'chat';
  $$('.view').forEach(v => v.classList.toggle('active', v.id === `view-${view}`));
  $$('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  $('#sidebar').classList.remove('open');
  if (push && location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
  if (view === 'documents') showDocuments();
  if (view === 'settings') showSettings();
  if (view === 'chat') setTimeout(() => $('#composer-input').focus(), 50);
}

async function refreshHealth() {
  const h = await api('/api/health');
  if (h.status !== 'ok' || !h.ai) return;
  state.health = h;
  state.tone = h.agent?.tone || 'genz';
  state.agentName = h.agent?.name || 'Aegis';
  $('#agent-name').textContent = state.agentName;
  $('#org-name').textContent = `by ${h.branding?.organization || 'Hiderox Technologies'}`;
  $('#model-provider').textContent = h.ai.label;
  $('#model-name').textContent = h.ai.model;
  $('#model-dot').className = `status-dot ${h.ai.reachable ? 'ok' : 'bad'}`;
  $('#model-chip').title = h.ai.reachable ? `${h.ai.label} · ${h.ai.model}` : `${h.ai.label} isn't reachable — click to fix`;
  $('#nav-doc-count').textContent = h.documents || '';
  const masking = h.ai.local ? h.privacy?.redact_for_local : h.privacy?.redact_for_cloud;
  $('#privacy-badge').innerHTML = h.ai.local
    ? '<i data-lucide="hard-drive"></i>local AI · fully private'
    : masking ? '<i data-lucide="shield-check"></i>cloud AI · PII masked' : '<span style="color:var(--amber)">cloud AI · masking off</span>';
  icons($('#privacy-badge'));
  $('#composer-input').placeholder = state.tone === 'genz'
    ? `Ask ${state.agentName} anything — threats, privacy, or "make me a PDF"…` : `Message ${state.agentName}…`;
  document.title = `${state.agentName} · ${h.branding?.organization || 'Hiderox'}`;
}

function initTheme() {
  $('#btn-theme').addEventListener('click', () => {
    const light = document.documentElement.classList.toggle('light');
    try { localStorage.setItem('hx.theme', light ? 'light' : 'dark'); } catch { /* ignore */ }
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  icons();
  initTheme();
  $$('.nav-btn').forEach(b => b.addEventListener('click', () => navigate(b.dataset.view)));
  $$('[data-open-sidebar]').forEach(b => b.addEventListener('click', () => $('#sidebar').classList.add('open')));
  $$('[data-close-sidebar]').forEach(b => b.addEventListener('click', () => $('#sidebar').classList.remove('open')));
  $('#model-chip').addEventListener('click', () => { navigate('settings'); showSettings('ai'); });
  window.addEventListener('hx:navigate', (e) => navigate(e.detail));
  window.addEventListener('hashchange', () => navigate(location.hash.slice(1) || 'chat', false));  // back/forward, typed links

  await refreshHealth();
  initChat();
  initStudio();
  initDocuments();
  initToolkit();
  initSettings(async () => { await refreshHealth(); renderChat(); });
  navigate(location.hash.slice(1) || 'chat', false);
  setInterval(refreshHealth, 30000);
});
