// Document Studio: edit the current chat's document (markdown) and re-render the PDF by hand.
import { $, api, esc, icons, previewPdf, state, toast } from './core.js';
import * as convos from './convos.js';

let open = false;
let loadedId = null;   // id whose source is in the editor
let source = '';
let info = null;
let dirty = false;

const BLANK = (cls) => `title: Untitled document
subtitle:
type: Guide
classification: ${cls}
version: 1.0
---
# 1. Introduction
Start writing in **markdown**. Use \`- [ ]\` for checklists, \`> **Warning:**\` for callouts,
| tables | like | this |, and ~~~ for code blocks.
`;

export function setDocument(c, docInfo) {
  c.docId = docInfo.id;
  convos.save();
  loadedId = null; // force reload
  renderStudio();
}

export function openStudio() {
  open = true;
  $('#studio').classList.add('open');
  $('#studio-backdrop').classList.add('open');
  renderStudio();
}

export function closeStudio() {
  open = false;
  $('#studio').classList.remove('open');
  $('#studio-backdrop').classList.remove('open');
}

export async function openDocument(docId) {
  const c = convos.current();
  c.docId = docId;
  convos.save();
  loadedId = null;
  openStudio();
}

export function newBlankDocument() {
  const c = convos.current();
  c.docId = null;
  convos.save();
  loadedId = '__new__';
  source = BLANK(state.health?.branding?.default_classification || 'INTERNAL');
  info = null;
  dirty = true;
  openStudio();
}

export async function renderStudio() {
  const c = convos.current();
  $('#studio-badge').hidden = !c.docId;
  if (!open) return;

  if (c.docId && loadedId !== c.docId) {
    const res = await api(`/api/documents/${encodeURIComponent(c.docId)}/source`);
    if (res.ok) {
      loadedId = c.docId; source = res.source; info = res.document; dirty = false;
    } else {
      c.docId = null; convos.save();
    }
  } else if (!c.docId && loadedId !== '__new__') {
    loadedId = null; info = null; source = '';
  }

  $('#studio-title').textContent = info?.title || (loadedId === '__new__' ? 'new document' : 'no document');
  $('#studio-dirty').hidden = !dirty;
  const body = $('#studio-body');
  const foot = $('#studio-foot');

  if (!loadedId) {
    body.innerHTML = `
      <div class="empty-studio">
        <div class="big">🛡️</div>
        <div class="font-display font-semibold text-[16px] mb-1" style="color:var(--text)">No document in this chat yet</div>
        <p class="text-[13px] mb-4">Ask ${esc(state.agentName)} for a policy, playbook, checklist or report — or write one yourself in markdown.</p>
        <button class="btn btn-primary" id="btn-studio-blank"><i data-lucide="file-plus-2"></i>Start a blank document</button>
      </div>`;
    foot.innerHTML = '';
    icons(body);
    $('#btn-studio-blank').addEventListener('click', newBlankDocument);
    return;
  }

  body.innerHTML = `
    <div class="text-[12px] muted">Front matter (title, type, classification…) sits above the <span class="mono">---</span> line. The body is markdown.
      You can also just ask ${esc(state.agentName)} in chat to change it.</div>
    <textarea class="editor" id="studio-editor" spellcheck="true">${esc(source)}</textarea>`;
  foot.innerHTML = `
    <div class="flex gap-2">
      <button class="btn btn-primary flex-1" id="btn-render"><i data-lucide="file-check-2"></i>${info ? 'Save & re-render PDF' : 'Create PDF'}</button>
      ${info ? `
        <button class="btn btn-icon" id="btn-studio-preview" title="Preview"><i data-lucide="eye"></i></button>
        <a class="btn btn-icon" href="${esc(info.pdf_url)}" download title="Download PDF"><i data-lucide="download"></i></a>
        <a class="btn btn-icon" href="${esc(info.md_url)}" download title="Download markdown"><i data-lucide="file-code-2"></i></a>` : ''}
      <button class="btn btn-icon btn-ghost" id="btn-studio-detach" title="Close this document (start fresh)"><i data-lucide="file-x-2"></i></button>
    </div>`;
  icons(body);
  icons(foot);

  const ed = $('#studio-editor');
  ed.addEventListener('input', () => { source = ed.value; dirty = true; $('#studio-dirty').hidden = false; });
  ed.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); render(); }
  });
  $('#btn-render').addEventListener('click', render);
  $('#btn-studio-preview')?.addEventListener('click', () => previewPdf(info.pdf_url, info.title));
  $('#btn-studio-detach').addEventListener('click', () => {
    if (dirty && !confirm('Discard unsaved edits?')) return;
    c.docId = null; convos.save(); loadedId = null; dirty = false; renderStudio();
  });
}

async function render() {
  const c = convos.current();
  const btn = $('#btn-render');
  btn.disabled = true;
  const res = await api('/api/documents', { method: 'POST', body: { source, id: info?.id || null } });
  btn.disabled = false;
  if (!res.ok) return toast(res.error || 'Render failed', 'error');
  info = res.document;
  loadedId = info.id;
  c.docId = info.id;
  dirty = false;
  convos.save();
  toast(`${info.title} saved`, 'success');
  window.dispatchEvent(new CustomEvent('hx:documents-changed'));
  renderStudio();
}

export function initStudio() {
  $('#btn-toggle-studio').addEventListener('click', () => (open ? closeStudio() : openStudio()));
  $('#btn-close-studio').addEventListener('click', closeStudio);
  $('#studio-backdrop').addEventListener('click', closeStudio);
  if (window.innerWidth > 1280 && convos.current().docId) openStudio();
}
