// Settings: AI providers, privacy, persona, branding.
import { $, $$, api, debounce, esc, icons, state, toast } from './core.js';
import * as convos from './convos.js';

const LOGO = {
  ollama: ['#111827', '🦙'], gemini: ['#4285f4', 'G'], groq: ['#f55036', 'GQ'], openai: ['#10a37f', 'AI'],
  anthropic: ['#d97757', 'A'], openrouter: ['#6366f1', 'OR'], mistral: ['#fa520f', 'M'], deepseek: ['#4d6bfe', 'DS'],
  xai: ['#000000', 'X'], custom: ['#64748b', '⚙'],
};

let tab = 'ai';
let ai = null;
let selected = null;
let onChange = () => {};

export function initSettings(changed) {
  onChange = changed;
  $('#settings-tabs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-tab]');
    if (b) showSettings(b.dataset.tab);
  });
}

export async function showSettings(which) {
  if (which) tab = which;
  $$('#settings-tabs .tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  const panel = $('#settings-panel');
  panel.innerHTML = '<div class="muted p-4">Loading…</div>';
  await ({ ai: renderAI, privacy: renderPrivacy, persona: renderPersona, branding: renderBranding }[tab])(panel);
  icons(panel);
}

const toggle = (id, on) => `<label class="switch"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}><span></span></label>`;

// ================================================================== //
// AI Brain
// ================================================================== //
async function renderAI(panel) {
  ai = await api('/api/ai/providers');
  selected = selected || ai.active;
  const card = (p) => {
    const [bg, txt] = LOGO[p.id] || ['#666', '?'];
    const flag = p.id === ai.active ? '<span class="badge badge-ok p-flag">ACTIVE</span>'
      : p.api_key_source ? '<span class="badge badge-catalog p-flag">key set</span>' : '';
    const where = p.kind === 'ollama' || p.id === 'custom' ? '<span class="local-badge"><i data-lucide="hard-drive"></i>local</span>' : '<span class="faint text-[11px]">cloud</span>';
    return `<div class="card provider ${p.id === selected ? 'sel' : ''}" data-p="${p.id}">
      ${flag}<div class="p-logo" style="background:${bg}">${txt}</div>
      <div class="p-name">${esc(p.label)}</div><div class="p-sub">${esc(p.tagline)}</div><div class="mt-1">${where}</div></div>`;
  };
  panel.innerHTML = `
    <div class="flex flex-col gap-4">
      <div class="card p-5">
        <h3 class="font-display text-[18px] font-semibold m-0">Pick ${esc(state.agentName)}'s brain</h3>
        <p class="text-[13px] muted mt-1 mb-4">For maximum privacy run a local model with Ollama — nothing leaves your machine.
          Cloud providers are faster; ${esc(state.agentName)} masks personal data before sending (see Privacy).
          Keys are stored in <span class="mono">secrets.json</span> on this server only.</p>
        <div class="provider-grid">${ai.providers.map(card).join('')}</div>
      </div>
      <div class="card p-5" id="prov-config"></div>
      <div class="card p-5">
        <div class="flex items-center justify-between gap-4">
          <div><div class="font-semibold">Creativity</div><div class="text-[12.5px] muted">Lower = precise & consistent. Higher = more creative writing.</div></div>
          <div class="flex items-center gap-3"><input type="range" min="0" max="1" step="0.05" id="temp" value="${ai.temperature}" style="accent-color:#10b981;width:160px"><span class="mono" id="temp-v">${ai.temperature}</span></div>
        </div>
      </div>
    </div>`;
  renderProviderConfig();
  panel.querySelectorAll('[data-p]').forEach(c => c.addEventListener('click', () => {
    selected = c.dataset.p;
    panel.querySelectorAll('[data-p]').forEach(x => x.classList.toggle('sel', x === c));
    renderProviderConfig();
  }));
  const temp = $('#temp');
  temp.addEventListener('input', () => { $('#temp-v').textContent = temp.value; });
  temp.addEventListener('change', async () => {
    await api('/api/ai/settings', { method: 'POST', body: { temperature: Number(temp.value) } });
    toast('Creativity updated', 'success');
  });
}

function renderProviderConfig() {
  const p = ai.providers.find(x => x.id === selected);
  const box = $('#prov-config');
  const [bg, txt] = LOGO[p.id] || ['#666', '?'];
  const isActive = p.id === ai.active;
  const keyNote = p.api_key_source === 'env' ? `Using <span class="mono">${esc(p.env_key)}</span> from the environment.`
    : p.api_key_source === 'saved' ? 'Key saved. Paste a new one to replace it.' : '';
  box.innerHTML = `
    <div class="flex items-center gap-3 mb-4">
      <div style="width:40px;height:40px;border-radius:12px;display:grid;place-items:center;font-weight:800;color:white;background:${bg};font-family:'Space Grotesk'">${txt}</div>
      <div><div class="font-display font-semibold text-[17px]">${esc(p.label)}</div><div class="text-[12.5px] muted">${esc(p.tagline)}</div></div>
      ${isActive ? '<span class="badge badge-ok ml-auto">ACTIVE</span>' : '<button class="btn btn-primary ml-auto" id="prov-activate"><i data-lucide="zap"></i>Use this</button>'}
    </div>
    <div class="flex flex-col gap-4">
      ${p.needs_key || p.id === 'custom' ? `
      <div>
        <label class="label">API key ${p.key_url ? `· <a href="${esc(p.key_url)}" target="_blank" rel="noopener noreferrer" style="color:#6ee7b7">get one ↗</a>` : ''}</label>
        <div class="flex gap-2">
          <input class="input mono" type="password" id="prov-key" autocomplete="off" placeholder="${p.api_key_masked ? esc(p.api_key_masked) : 'paste your key'}">
          ${p.api_key_source === 'saved' ? '<button class="btn btn-danger" id="prov-key-del" title="Remove saved key"><i data-lucide="trash-2"></i></button>' : ''}
        </div>
        ${keyNote ? `<div class="text-[12px] muted mt-1">${keyNote}</div>` : ''}
      </div>` : `
      <div class="text-[13px] muted">No key needed. Make sure Ollama is running (<span class="mono">ollama serve</span>) and a model is pulled (<span class="mono">ollama pull gemma3:4b</span>).</div>`}
      <div>
        <label class="label">Model</label>
        <div class="flex gap-2">
          <input class="input mono" id="prov-model" list="prov-models" value="${esc(p.model)}" placeholder="model id">
          <datalist id="prov-models">${(p.suggested_models || []).map(m => `<option value="${esc(m)}">`).join('')}</datalist>
          <button class="btn" id="prov-fetch"><i data-lucide="list-restart"></i><span class="hide-sm">Fetch models</span></button>
        </div>
        <div class="flex flex-wrap gap-1.5 mt-2" id="prov-model-chips"></div>
      </div>
      <details ${p.id === 'custom' || p.id === 'ollama' ? 'open' : ''}>
        <summary class="text-[13px] muted cursor-pointer">Advanced: base URL</summary>
        <input class="input mono mt-2" id="prov-url" value="${esc(p.base_url)}" placeholder="${esc(p.default_base_url)}">
      </details>
      <div class="flex flex-wrap items-center gap-2">
        <button class="btn btn-primary" id="prov-save"><i data-lucide="save"></i>Save</button>
        <button class="btn" id="prov-test"><i data-lucide="activity"></i>Test connection</button>
        <span class="text-[13px]" id="prov-test-result"></span>
      </div>
    </div>`;
  icons(box);

  const chips = (models) => {
    $('#prov-model-chips').innerHTML = models.slice(0, 24).map(m => `<button class="chip" data-m="${esc(m)}">${esc(m)}</button>`).join('');
    $$('#prov-model-chips [data-m]').forEach(c => c.addEventListener('click', () => { $('#prov-model').value = c.dataset.m; }));
  };
  const fetchModels = async (quiet = false) => {
    const res = await api(`/api/ai/models?provider=${p.id}`);
    if (res.ok) {
      chips(res.models);
      $('#prov-models').innerHTML = res.models.map(m => `<option value="${esc(m)}">`).join('');
      if (!quiet) toast(`${res.models.length} models found`, 'success');
    } else if (!quiet) toast(res.error || 'Could not list models', 'error');
  };
  if (p.id === 'ollama') fetchModels(true);

  const save = async (extra = {}) => {
    const body = { provider: p.id, model: $('#prov-model').value.trim(), base_url: $('#prov-url').value.trim(), ...extra };
    const keyEl = $('#prov-key');
    if (keyEl && keyEl.value.trim()) body.api_key = keyEl.value.trim();
    const res = await api('/api/ai/settings', { method: 'POST', body });
    if (!res.ok) toast(res.error || 'Save failed', 'error');
    return res.ok;
  };
  const reload = async () => {
    const pb = $('#view-settings .page-body');
    const y = pb.scrollTop;
    await showSettings('ai');
    pb.scrollTop = y;
    onChange();
  };
  $('#prov-fetch').addEventListener('click', async () => { await save(); fetchModels(); });
  $('#prov-save').addEventListener('click', async () => { if (await save()) { toast(`${p.label} saved`, 'success'); reload(); } });
  $('#prov-key-del')?.addEventListener('click', async () => {
    if (!confirm(`Remove the saved ${p.label} key from this server?`)) return;
    await api('/api/ai/settings', { method: 'POST', body: { provider: p.id, api_key: '' } });
    toast('Key removed', 'success');
    reload();
  });
  $('#prov-activate')?.addEventListener('click', async () => {
    if (await save({ active_provider: p.id })) { toast(`${state.agentName} now runs on ${p.label}`, 'success'); reload(); }
  });
  $('#prov-test').addEventListener('click', async () => {
    await save();
    const out = $('#prov-test-result');
    out.innerHTML = '<span class="status-line" style="padding:0"><span class="orb"></span><span class="shimmer">pinging…</span></span>';
    const res = await api('/api/ai/test', { method: 'POST', body: { provider: p.id } });
    out.innerHTML = res.ok ? `<span style="color:var(--lime)">✓ ${esc(res.model)} replied in ${res.elapsed_s}s</span>`
      : `<span style="color:var(--red)">✗ ${esc(res.error || 'failed')}</span>`;
  });
}

// ================================================================== //
// Privacy
// ================================================================== //
async function renderPrivacy(panel) {
  const s = await api('/api/settings');
  const p = s.privacy;
  panel.innerHTML = `
    <div class="flex flex-col gap-4">
      <div class="card p-5">
        <div class="setting-row"><div><div class="font-semibold">Mask personal data for cloud AI</div>
          <div class="text-[12.5px] muted">Emails, phone numbers, public IPs, card numbers, national IDs, IBANs, passwords and API keys are replaced with
          placeholders like <span class="mono">[EMAIL_1]</span> before anything is sent to Gemini/OpenAI/etc., and restored in the reply on your side.</div></div>${toggle('pv-cloud', p.redact_for_cloud)}</div>
        <div class="setting-row"><div><div class="font-semibold">Also mask for local models</div>
          <div class="text-[12.5px] muted">Usually unnecessary — Ollama runs on your own hardware.</div></div>${toggle('pv-local', p.redact_for_local)}</div>
      </div>
      <div class="card p-5">
        <div class="font-semibold mb-1">Try it</div>
        <div class="text-[12.5px] muted mb-3">See exactly what the AI provider would receive.</div>
        <textarea class="input mono" rows="4" id="pv-test">Hi, I'm Sara (sara.ahmed@example.com, +92 300 1234567). Our VPN at 185.220.101.45 was hit. password: Winter2026!</textarea>
        <div class="out mt-3" id="pv-out"></div>
        <div class="text-[12px] mt-2" id="pv-found"></div>
      </div>
      <div class="card p-5">
        <div class="font-semibold">Where your data lives</div>
        <ul class="text-[13px] muted" style="padding-left:18px;margin:8px 0 14px;line-height:1.7">
          <li>Chats: only in <b>this browser</b> (localStorage). Never stored on the server.</li>
          <li>Documents: <span class="mono">data/documents/</span> on the server (markdown + PDF).</li>
          <li>Settings & API keys: <span class="mono">data/settings.json</span>, <span class="mono">data/secrets.json</span> (owner-only permissions).</li>
          <li>No analytics, no telemetry, no third-party calls except the AI provider you choose and the UI's CDN assets.</li>
        </ul>
        <button class="btn btn-danger" id="pv-wipe"><i data-lucide="trash-2"></i>Delete all chats in this browser</button>
      </div>
    </div>`;
  const post = (body) => api('/api/settings', { method: 'POST', body: { privacy: body } }).then(() => { toast('Privacy settings saved', 'success'); onChange(); });
  $('#pv-cloud').addEventListener('change', (e) => post({ redact_for_cloud: e.target.checked }));
  $('#pv-local').addEventListener('change', (e) => post({ redact_for_local: e.target.checked }));
  const preview = debounce(async () => {
    const res = await api('/api/privacy/preview', { method: 'POST', body: { text: $('#pv-test').value } });
    $('#pv-out').textContent = res.redacted || '';
    $('#pv-found').innerHTML = res.found?.length ? `<span style="color:var(--lime)">Masked: ${esc(res.found.join(', '))}</span>` : '<span class="muted">Nothing sensitive detected.</span>';
  }, 250);
  $('#pv-test').addEventListener('input', preview);
  preview();
  $('#pv-wipe').addEventListener('click', () => {
    if (!confirm('Delete every chat stored in this browser? Documents on the server are kept.')) return;
    convos.wipeAll();
    toast('All chats deleted from this browser', 'success');
    onChange();
  });
}

// ================================================================== //
// Persona
// ================================================================== //
async function renderPersona(panel) {
  const a = (await api('/api/settings')).agent;
  const tones = [['genz', 'Gen-Z ✨'], ['friendly', 'Friendly 😊'], ['professional', 'Professional 👔']];
  panel.innerHTML = `
    <div class="card p-5 flex flex-col gap-5">
      <div><label class="label">Agent name</label><input class="input" id="p-name" value="${esc(a.name)}" style="max-width:280px"></div>
      <div><label class="label">Vibe</label>
        <div class="segmented" id="p-tone">${tones.map(([k, l]) => `<button data-t="${k}" class="${a.tone === k ? 'active' : ''}">${l}</button>`).join('')}</div>
        <div class="text-[12.5px] muted mt-2">Changes how it chats. Documents always stay professional.</div></div>
      <div><label class="label">House rules (optional)</label>
        <textarea class="input" rows="5" id="p-custom" placeholder="e.g. We use Microsoft 365 and CrowdStrike. Align documents with ISO 27001. Our DPO is privacy@example.com.">${esc(a.custom_instructions)}</textarea></div>
      <div><button class="btn btn-primary" id="p-save"><i data-lucide="save"></i>Save persona</button></div>
    </div>`;
  let tone = a.tone;
  panel.querySelectorAll('[data-t]').forEach(b => b.addEventListener('click', () => {
    tone = b.dataset.t;
    panel.querySelectorAll('[data-t]').forEach(x => x.classList.toggle('active', x === b));
  }));
  $('#p-save').addEventListener('click', async () => {
    const res = await api('/api/settings', { method: 'POST', body: { agent: { name: $('#p-name').value.trim() || 'Aegis', tone, custom_instructions: $('#p-custom').value } } });
    if (res.ok) { toast('Persona saved', 'success'); onChange(); }
  });
}

// ================================================================== //
// Branding (used on every PDF)
// ================================================================== //
async function renderBranding(panel) {
  const s = await api('/api/settings');
  const b = s.branding;
  const field = (k, l, ph = '') => `<label><span class="label">${l}</span><input class="input" data-b="${k}" value="${esc(b[k] || '')}" placeholder="${esc(ph)}"></label>`;
  panel.innerHTML = `
    <div class="card p-5 flex flex-col gap-4">
      <div class="text-[13px] muted">These details appear in the header and footer of every PDF. Fork-friendly: rebrand for your own organisation.</div>
      <div class="grid md:grid-cols-2 gap-3">
        ${field('organization', 'Organisation', 'Hiderox Technologies')}${field('website', 'Website', 'hiderox.com')}
        ${field('tagline', 'Tagline', 'Cyber Security & Privacy')}${field('email', 'Contact email', 'security@example.com')}
        <label><span class="label">Default classification</span>
          <select class="select" data-b="default_classification">${['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'].map(c => `<option ${c === b.default_classification ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
        <label><span class="label">Accent colour</span><input type="color" data-b="accent_color" value="${esc(b.accent_color)}" style="width:60px;height:38px;border:0;background:none"></label>
      </div>
      ${field('footer_note', 'Footer note (optional)', 'e.g. © Hiderox Technologies — do not distribute')}
      <div class="flex items-center gap-3">
        <img src="/api/branding/logo?t=${Date.now()}" alt="logo" style="width:44px;height:44px;object-fit:contain;border-radius:10px;background:var(--surface-2);padding:4px">
        <label class="btn btn-sm cursor-pointer"><i data-lucide="image-up"></i>Upload PDF logo (PNG/JPG)<input type="file" id="b-logo" accept=".png,.jpg,.jpeg" hidden></label>
        ${s.has_logo ? '<button class="btn btn-sm btn-ghost" id="b-logo-del">Remove</button>' : ''}
      </div>
      <div><button class="btn btn-primary" id="b-save"><i data-lucide="save"></i>Save branding</button></div>
    </div>`;
  $('#b-save').addEventListener('click', async () => {
    const out = {};
    panel.querySelectorAll('[data-b]').forEach(i => { out[i.dataset.b] = i.value.trim(); });
    const res = await api('/api/settings', { method: 'POST', body: { branding: out } });
    if (res.ok) { toast('Branding saved — new PDFs will use it', 'success'); onChange(); }
  });
  $('#b-logo').addEventListener('change', async (e) => {
    const fd = new FormData();
    fd.append('file', e.target.files[0]);
    const res = await api('/api/branding/logo', { method: 'POST', form: fd });
    toast(res.ok ? 'Logo uploaded' : res.error, res.ok ? 'success' : 'error');
    showSettings('branding');
  });
  $('#b-logo-del')?.addEventListener('click', async () => {
    await api('/api/branding/logo', { method: 'DELETE' });
    showSettings('branding');
  });
}
