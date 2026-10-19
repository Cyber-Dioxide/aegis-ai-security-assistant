// Conversations live in this browser's localStorage only: [{id, title, messages, docId, updatedAt}]
import { store, uid } from './core.js';

const MAX_CONVOS = 50;
let convos = store.get('convos', []);
let currentId = store.get('currentConvo', null);

export function save() {
  convos.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
  convos = convos.slice(0, MAX_CONVOS);
  store.set('convos', convos);
  store.set('currentConvo', currentId);
}

export function all() { return convos; }

export function current() {
  let c = convos.find(x => x.id === currentId);
  if (!c) c = create();
  return c;
}

export function create() {
  const c = { id: uid(), title: 'New chat', messages: [], docId: null, updatedAt: Date.now() };
  convos.unshift(c);
  currentId = c.id;
  save();
  return c;
}

export function select(id) {
  if (convos.some(c => c.id === id)) {
    currentId = id;
    save();
  }
}

export function remove(id) {
  convos = convos.filter(c => c.id !== id);
  if (currentId === id) currentId = convos[0]?.id || null;
  save();
}

export function wipeAll() {
  convos = [];
  currentId = null;
  save();
}

export function touch(c) {
  c.updatedAt = Date.now();
  if (c.title === 'New chat') {
    const first = c.messages.find(m => m.role === 'user');
    if (first) c.title = first.content.replace(/\s+/g, ' ').slice(0, 48) + (first.content.length > 48 ? '…' : '');
  }
  save();
}

/** Messages in the shape the backend expects, with document events summarised as text. */
export function historyFor(c) {
  return c.messages
    .filter(m => (m.role === 'user' || m.role === 'assistant') && !m.pending)
    .map(m => {
      let content = m.content || '';
      if (m.doc) content += `\n[Document "${m.doc.title}" ${m.doc.updated ? 'updated' : 'created'} as PDF]`;
      if (m.error && !content) content = `[Error: ${m.error}]`;
      return { role: m.role, content: content.trim() };
    })
    .filter(m => m.content);
}
