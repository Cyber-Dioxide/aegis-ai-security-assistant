// Documents page: template gallery + library of generated PDFs.
import { $, api, esc, icons, modal, previewPdf, state, timeAgo, toast } from './core.js';
import { startWithPrompt } from './chat.js';
import { newBlankDocument, openDocument } from './studio.js';

export const TEMPLATES = [
  ['shield-half', 'Information Security Policy', 'Policy', 'a company-wide Information Security Policy (roles, asset management, access control, encryption, logging, incident reporting, enforcement)'],
  ['siren', 'Incident Response Plan', 'Plan', 'an Incident Response Plan with severity levels, roles (RACI), the six IR phases, a communication plan and contact table'],
  ['skull', 'Ransomware Playbook', 'Playbook', 'a step-by-step ransomware response playbook for the first 72 hours, with checklists and decision points'],
  ['key-round', 'Password & MFA Standard', 'Policy', 'a Password, Passkey & MFA Standard (length, managers, rotation, MFA methods, exceptions)'],
  ['laptop', 'Acceptable Use & BYOD Policy', 'Policy', 'an Acceptable Use and Bring-Your-Own-Device policy for staff'],
  ['scale', 'Website Privacy Notice', 'Policy', 'a GDPR-style website privacy notice (data collected, purposes, lawful bases, retention, rights, cookies, contact)'],
  ['database-zap', 'Data Breach Checklist', 'Checklist', 'a personal-data breach response checklist including the 72-hour regulator notification and affected-user communication'],
  ['graduation-cap', 'Security Awareness Handout', 'Handout', 'a friendly one-page security awareness handout for non-technical staff (phishing, passwords, MFA, updates, reporting)'],
  ['clipboard-check', 'Vendor Security Questionnaire', 'Template', 'a vendor / third-party security questionnaire with sections and yes/no + evidence columns'],
  ['gauge', 'Risk Assessment Report', 'Assessment', 'an IT risk assessment report with a risk register table (likelihood, impact, score, owner, treatment)'],
  ['bug', 'Penetration Test Report', 'Report', 'a penetration test report template (scope, methodology, findings table with CVSS, remediation, appendix)'],
  ['hard-drive-download', 'Backup & Recovery Plan', 'Plan', 'a backup and disaster recovery plan using the 3-2-1-1-0 rule, RPO/RTO targets and restore testing'],
];

function templateModal([icon, title, type, what]) {
  const prev = state.lastOrg || {};
  modal(`
    <div class="flex items-center gap-2 mb-1"><i data-lucide="${icon}" class="w-5 h-5" style="color:#6ee7b7"></i>
      <h3 class="font-display font-semibold text-[18px] m-0">${esc(title)}</h3>
      <button class="btn btn-ghost btn-icon ml-auto" data-close><i data-lucide="x"></i></button></div>
    <p class="text-[13px] muted mt-1 mb-4">A few details make it specific to you. Everything is optional.</p>
    <div class="flex flex-col gap-3">
      <label><span class="label">Organisation</span><input class="input" id="t-org" value="${esc(prev.org || '')}" placeholder="e.g. Acme Health (Pvt) Ltd"></label>
      <label><span class="label">Size & industry</span><input class="input" id="t-ctx" value="${esc(prev.ctx || '')}" placeholder="e.g. 45 staff, healthcare clinic, Microsoft 365, hybrid work"></label>
      <label><span class="label">Anything else to include</span><textarea class="input" id="t-extra" rows="3" placeholder="e.g. Must align with ISO 27001, mention our IT lead Sara as owner"></textarea></label>
      <label><span class="label">Classification</span>
        <select class="select" id="t-cls">${['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'].map(c => `<option ${c === (state.health?.branding?.default_classification || 'INTERNAL') ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
    </div>
    <div class="flex justify-end gap-2 mt-5"><button class="btn" data-close>Cancel</button><button class="btn btn-primary" id="t-go"><i data-lucide="sparkles"></i>Write it</button></div>`,
  { onMount: (el, close) => {
    el.querySelector('#t-go').addEventListener('click', () => {
      const org = el.querySelector('#t-org').value.trim();
      const ctx = el.querySelector('#t-ctx').value.trim();
      const extra = el.querySelector('#t-extra').value.trim();
      const cls = el.querySelector('#t-cls').value;
      state.lastOrg = { org, ctx };
      const prompt = `Create a PDF document (type: ${type}, classification: ${cls}): ${what}.`
        + (org ? ` Organisation: ${org}.` : '')
        + (ctx ? ` Context: ${ctx}.` : '')
        + (extra ? ` Also: ${extra}` : '');
      close();
      startWithPrompt(prompt);
    });
  } });
}

let docs = [];

export async function showDocuments() {
  const grid = $('#templates-grid');
  if (!grid.childElementCount) {
    grid.innerHTML = TEMPLATES.map((t, i) => `
      <div class="card template-card" data-t="${i}">
        <div class="flex items-center gap-2 font-semibold"><i data-lucide="${t[0]}" class="w-4 h-4" style="color:#6ee7b7"></i>${esc(t[1])}</div>
        <div class="text-[11.5px] muted mt-1">${esc(t[2])}</div>
      </div>`).join('');
    icons(grid);
  }
  const res = await api('/api/documents');
  docs = res.documents || [];
  $('#nav-doc-count').textContent = docs.length || '';
  renderDocs();
}

function renderDocs() {
  const f = ($('#docs-search').value || '').toLowerCase();
  const list = docs.filter(d => `${d.title} ${d.meta?.type || ''}`.toLowerCase().includes(f));
  const grid = $('#docs-grid');
  grid.innerHTML = list.length ? list.map(d => {
    const cls = (d.meta?.classification || '').toUpperCase();
    return `
      <div class="card qcard" data-id="${esc(d.id)}" style="align-items:flex-start">
        <div class="ico"><i data-lucide="file-lock-2"></i></div>
        <div class="min-w-0 flex-1">
          <div class="font-semibold truncate">${esc(d.title)}</div>
          <div class="text-[12px] muted">${esc(d.meta?.type || 'Document')} · ${timeAgo(d.updated_at)} · ${d.words} words</div>
          <div class="flex gap-1.5 mt-2 items-center">
            ${cls ? `<span class="cls cls-${esc(cls)}">${esc(cls)}</span>` : ''}
            <button class="btn btn-sm btn-ghost" data-act="edit" title="Edit"><i data-lucide="file-pen-line"></i></button>
            <a class="btn btn-sm btn-ghost" href="${esc(d.pdf_url)}" download title="Download PDF"><i data-lucide="download"></i></a>
            <button class="btn btn-sm btn-ghost btn-danger" data-act="delete" title="Delete"><i data-lucide="trash-2"></i></button>
          </div>
        </div>
      </div>`;
  }).join('') : `<div class="muted">No documents yet — pick a template above or ask ${esc(state.agentName)} in chat.</div>`;
  icons(grid);
}

export function initDocuments() {
  $('#templates-grid').addEventListener('click', (e) => {
    const card = e.target.closest('[data-t]');
    if (card) templateModal(TEMPLATES[Number(card.dataset.t)]);
  });
  $('#docs-search').addEventListener('input', renderDocs);
  $('#btn-blank-doc').addEventListener('click', () => {
    window.dispatchEvent(new CustomEvent('hx:navigate', { detail: 'chat' }));
    newBlankDocument();
  });
  $('#docs-grid').addEventListener('click', async (e) => {
    if (e.target.closest('a')) return;
    const card = e.target.closest('[data-id]');
    if (!card) return;
    const d = docs.find(x => x.id === card.dataset.id);
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (act === 'delete') {
      if (!confirm(`Delete "${d.title}"? This removes the PDF and its source.`)) return;
      await api(`/api/documents/${encodeURIComponent(d.id)}`, { method: 'DELETE' });
      toast('Deleted', 'success');
      showDocuments();
    } else if (act === 'edit') {
      window.dispatchEvent(new CustomEvent('hx:navigate', { detail: 'chat' }));
      openDocument(d.id);
    } else {
      previewPdf(d.pdf_url, d.title);
    }
  });
  window.addEventListener('hx:documents-changed', () => api('/api/documents').then(r => {
    docs = r.documents || [];
    $('#nav-doc-count').textContent = docs.length || '';
    if ($('#view-documents').classList.contains('active')) renderDocs();
  }));
}
