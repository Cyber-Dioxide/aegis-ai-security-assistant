// Toolkit: small security utilities that run entirely in the browser (nothing is sent to the server).
import { $, esc, icons, toast } from './core.js';

const WORDS = ('acid acorn actor agent alarm album alpha amber anchor angle apple april arena armor arrow atlas attic audio aunt autumn '
  + 'badge bagel baker bamboo banjo barley basin beach beacon berry bison blade blaze blossom bonus border bottle brave bread breeze brick '
  + 'bridge bronze brush bucket buffalo cabin cactus camel canal candle canyon carbon cargo carpet castle cedar cello chalk charm cherry '
  + 'cider cinema circus citrus clover cobalt coffee comet copper coral cosmic cotton coyote crane crater cricket crystal cupid cyclone '
  + 'dahlia daisy dancer delta denim desert diesel dingo dolphin domino dragon drift eagle echo eclipse ember emerald engine epic falcon '
  + 'fern ferry fiddle figure flame flint forest fossil frost galaxy garden garlic gecko geyser ginger glacier globe gopher granite gravel '
  + 'hammer harbor harvest hazel helium hermit honey hornet husky iceberg igloo indigo island ivory jackal jaguar jasmine jelly jungle '
  + 'kayak kernel kettle kiwi koala ladder lagoon lantern laser lemon lilac lizard lobster locket lotus lunar magnet mango maple marble '
  + 'meadow meteor mint mirror mocha monsoon mosaic nebula nectar nickel noodle nugget oasis ocean olive onyx opal orbit orchid otter oyster '
  + 'paddle panda papaya parrot pebble pepper pigeon pilot pine pixel planet plasma plum pocket polar poppy prism pulsar quartz quill '
  + 'rabbit radar raven reef ribbon river rocket ruby saddle saffron salmon satin scarlet shadow shark signal silver sketch sonic spark '
  + 'sphinx spiral sprout squid stable summit sunset swan tango thunder tiger timber topaz tornado tulip tundra turbo turtle umbra '
  + 'valley vapor velvet violet vortex walnut walrus willow window wizard yacht yonder zebra zenith zephyr').split(' ');

const WORD_SET = new Set(WORDS);
const rand = (n) => { const a = new Uint32Array(1); crypto.getRandomValues(a); return a[0] % n; };

// ------------------------------------------------------------------ //
// Password strength (entropy estimate + common-pattern penalties)
// ------------------------------------------------------------------ //
const COMMON = ['password', '123456', 'qwerty', 'admin', 'welcome', 'letmein', 'iloveyou', 'monkey', 'dragon', 'pakistan', 'abc123', '111111'];
function strength(pw) {
  if (!pw) return { bits: 0, label: '—', color: 'var(--faint)', tips: [] };
  let pool = 0;
  if (/[a-z]/.test(pw)) pool += 26;
  if (/[A-Z]/.test(pw)) pool += 26;
  if (/\d/.test(pw)) pool += 10;
  if (/[^A-Za-z0-9]/.test(pw)) pool += 33;
  let bits = pw.length * Math.log2(Math.max(pool, 1));
  const tips = [];
  // Passphrases from our word list: entropy comes from the word choices, not the letter count.
  const words = pw.split('-');
  if (words.length >= 3 && words.slice(0, -1).every(w => WORD_SET.has(w))) {
    bits = (words.length - 1) * Math.log2(WORDS.length) + (/^\d+$/.test(words.at(-1)) ? Math.log2(90) : Math.log2(WORDS.length));
  }
  const low = pw.toLowerCase();
  if (COMMON.some(c => low.includes(c))) { bits = Math.min(bits, 20); tips.push('Contains a very common password'); }
  if (/(.)\1{2,}/.test(pw)) { bits -= 10; tips.push('Repeated characters'); }
  if (/(0123|1234|2345|3456|4567|5678|6789|abcd|qwer|asdf)/i.test(pw)) { bits -= 12; tips.push('Keyboard / number sequence'); }
  if (/(19|20)\d{2}/.test(pw)) { bits -= 6; tips.push('Looks like a year'); }
  if (pw.length < 12) tips.push('Use at least 12–16 characters');
  bits = Math.max(0, Math.round(bits));
  const [label, color] = bits < 40 ? ['Weak', 'var(--red)'] : bits < 60 ? ['Okay', 'var(--amber)'] : bits < 80 ? ['Strong', 'var(--lime)'] : ['Excellent', 'var(--cyan)'];
  const guesses = 2 ** bits / 1e10; // offline attack at 10 billion guesses/second
  const crack = guesses < 1 ? 'instantly' : guesses < 3600 ? `${Math.round(guesses / 60)} minutes`
    : guesses < 86400 * 365 ? `${Math.round(guesses / 86400)} days` : guesses < 86400 * 365 * 1e6 ? `${Math.round(guesses / 86400 / 365).toLocaleString()} years` : 'millions of years';
  return { bits, label, color, tips, crack };
}

function genPassword(len, sets) {
  const chars = (sets.lower ? 'abcdefghijkmnopqrstuvwxyz' : '') + (sets.upper ? 'ABCDEFGHJKLMNPQRSTUVWXYZ' : '')
    + (sets.digits ? '23456789' : '') + (sets.symbols ? '!@#$%^&*-_=+?' : '');
  if (!chars) return '';
  return Array.from({ length: len }, () => chars[rand(chars.length)]).join('');
}
const genPassphrase = (n, sep) => Array.from({ length: n }, () => WORDS[rand(WORDS.length)]).join(sep) + sep + (10 + rand(90));

// ------------------------------------------------------------------ //
// IOCs
// ------------------------------------------------------------------ //
const refang = (s) => s.replace(/hxxp/gi, 'http').replace(/\[\.\]|\(\.\)|\{\.\}/g, '.').replace(/\[:\]/g, ':').replace(/\[@\]|\[at\]/gi, '@');
const defang = (s) => s.replace(/http/gi, 'hxxp').replace(/\.(?=[a-z0-9-]+(\b|\/|:))/gi, '[.]').replace(/@/g, '[@]');
function extractIocs(text) {
  const t = refang(text);
  const uniq = (a) => [...new Set(a)];
  return {
    URLs: uniq(t.match(/\bhttps?:\/\/[^\s"'<>]+/gi) || []),
    Domains: uniq((t.match(/\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,24})\b/gi) || []).filter(d => !/\.(png|jpg|gif|exe|dll|txt|pdf|docx?)$/i.test(d))),
    IPv4: uniq(t.match(/\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b/g) || []),
    Emails: uniq(t.match(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi) || []),
    'MD5': uniq(t.match(/\b[a-f0-9]{32}\b/gi) || []),
    'SHA-1': uniq(t.match(/\b[a-f0-9]{40}\b/gi) || []),
    'SHA-256': uniq(t.match(/\b[a-f0-9]{64}\b/gi) || []),
    CVEs: uniq((t.match(/\bCVE-\d{4}-\d{4,7}\b/gi) || []).map(c => c.toUpperCase())),
  };
}

// ------------------------------------------------------------------ //
// Encoding
// ------------------------------------------------------------------ //
const b64enc = (s) => btoa(String.fromCharCode(...new TextEncoder().encode(s)));
const b64dec = (s) => new TextDecoder().decode(Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/').replace(/\s/g, '') + '==='.slice((s.length + 3) % 4)), c => c.charCodeAt(0)));
const hexenc = (s) => [...new TextEncoder().encode(s)].map(b => b.toString(16).padStart(2, '0')).join('');
const hexdec = (s) => new TextDecoder().decode(new Uint8Array((s.replace(/[^a-f0-9]/gi, '').match(/../g) || []).map(h => parseInt(h, 16))));

async function digest(algo, data) {
  if (!crypto.subtle) throw new Error('Hashing needs HTTPS or localhost (browser security rule).');
  const buf = await crypto.subtle.digest(algo, data);
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}

// ------------------------------------------------------------------ //
// UI
// ------------------------------------------------------------------ //
export function initToolkit() {
  const root = $('#toolkit');
  root.innerHTML = `
    <div class="card tool">
      <h3><i data-lucide="key-round"></i>Password lab</h3>
      <div class="text-[12.5px] muted">Generate a strong one, or test yours (it never leaves this page).</div>
      <div class="flex gap-2"><input class="input mono" id="pw-in" placeholder="Type or generate a password" autocomplete="off" spellcheck="false">
        <button class="btn btn-icon" id="pw-copy" title="Copy"><i data-lucide="copy"></i></button></div>
      <div class="meter"><span id="pw-bar" style="width:0"></span></div>
      <div class="text-[12.5px]" id="pw-info"><span class="muted">Strength appears here.</span></div>
      <div class="flex flex-wrap gap-3 items-center text-[12.5px]">
        <label class="flex items-center gap-2">Length <input type="range" id="pw-len" min="8" max="64" value="20" style="accent-color:#10b981"><span class="mono" id="pw-len-v">20</span></label>
        ${['lower', 'upper', 'digits', 'symbols'].map(k => `<label class="flex items-center gap-1"><input type="checkbox" data-set="${k}" checked>${k}</label>`).join('')}
      </div>
      <div class="flex gap-2"><button class="btn btn-primary flex-1" id="pw-gen"><i data-lucide="dices"></i>Password</button>
        <button class="btn flex-1" id="pp-gen"><i data-lucide="text-cursor-input"></i>Passphrase</button></div>
    </div>

    <div class="card tool">
      <h3><i data-lucide="fingerprint"></i>Hash calculator</h3>
      <div class="text-[12.5px] muted">Hash text or a file to verify downloads / share IOCs. Files are read locally.</div>
      <textarea class="input mono" id="hash-in" rows="3" placeholder="Text to hash…"></textarea>
      <label class="btn btn-sm cursor-pointer" style="align-self:flex-start"><i data-lucide="file-up"></i>Hash a file<input type="file" id="hash-file" hidden></label>
      <div class="out" id="hash-out"></div>
    </div>

    <div class="card tool">
      <h3><i data-lucide="radar"></i>IOC extractor & defanger</h3>
      <div class="text-[12.5px] muted">Paste a report, email or log. Pulls out URLs, domains, IPs, hashes, CVEs — and defangs them for safe sharing.</div>
      <textarea class="input mono" id="ioc-in" rows="4" placeholder="Paste text with indicators… (hxxp://evil[.]com works too)"></textarea>
      <div class="flex gap-2"><button class="btn btn-sm btn-primary" id="ioc-extract"><i data-lucide="scan-search"></i>Extract</button>
        <button class="btn btn-sm" id="ioc-defang">Defang</button><button class="btn btn-sm" id="ioc-refang">Refang</button>
        <button class="btn btn-sm btn-ghost ml-auto" id="ioc-copy"><i data-lucide="copy"></i></button></div>
      <div class="out" id="ioc-out"></div>
    </div>

    <div class="card tool">
      <h3><i data-lucide="ticket"></i>JWT decoder</h3>
      <div class="text-[12.5px] muted">Inspect a token's header & claims (signature is not verified). Expiry is checked.</div>
      <textarea class="input mono" id="jwt-in" rows="3" placeholder="eyJhbGciOi…"></textarea>
      <div class="out" id="jwt-out"></div>
    </div>

    <div class="card tool">
      <h3><i data-lucide="binary"></i>Encoder / decoder</h3>
      <textarea class="input mono" id="enc-in" rows="3" placeholder="Input…"></textarea>
      <div class="flex flex-wrap gap-1.5">
        ${[['b64e', 'Base64 →'], ['b64d', '← Base64'], ['urle', 'URL →'], ['urld', '← URL'], ['hexe', 'Hex →'], ['hexd', '← Hex']]
          .map(([k, l]) => `<button class="chip" data-enc="${k}">${l}</button>`).join('')}
      </div>
      <div class="out" id="enc-out"></div>
    </div>`;
  icons(root);

  // Password lab
  const pwIn = $('#pw-in');
  const sets = () => Object.fromEntries([...root.querySelectorAll('[data-set]')].map(c => [c.dataset.set, c.checked]));
  const showStrength = () => {
    const s = strength(pwIn.value);
    $('#pw-bar').style.width = Math.min(100, s.bits) + '%';
    $('#pw-bar').style.background = s.color;
    $('#pw-info').innerHTML = pwIn.value
      ? `<b style="color:${s.color}">${s.label}</b> · ~${s.bits} bits · offline crack time: <b>${s.crack}</b>${s.tips.length ? `<div class="faint mt-1">${s.tips.map(esc).join(' · ')}</div>` : ''}`
      : '<span class="muted">Strength appears here.</span>';
  };
  pwIn.addEventListener('input', showStrength);
  $('#pw-len').addEventListener('input', (e) => { $('#pw-len-v').textContent = e.target.value; });
  $('#pw-gen').addEventListener('click', () => { pwIn.value = genPassword(Number($('#pw-len').value), sets()); showStrength(); });
  $('#pp-gen').addEventListener('click', () => { pwIn.value = genPassphrase(7, '-'); showStrength(); });
  $('#pw-copy').addEventListener('click', () => copy(pwIn.value));

  // Hashes
  const showHashes = async (data) => {
    const out = $('#hash-out');
    try {
      const rows = [];
      for (const a of ['SHA-1', 'SHA-256', 'SHA-384', 'SHA-512']) rows.push(`${a.padEnd(8)} ${await digest(a, data)}`);
      out.textContent = rows.join('\n');
    } catch (e) { out.textContent = e.message; }
  };
  $('#hash-in').addEventListener('input', (e) => showHashes(new TextEncoder().encode(e.target.value)));
  $('#hash-file').addEventListener('change', async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    $('#hash-out').textContent = `Hashing ${f.name}…`;
    await showHashes(await f.arrayBuffer());
    $('#hash-out').textContent = `${f.name} (${(f.size / 1024).toFixed(1)} KB)\n` + $('#hash-out').textContent;
  });

  // IOCs
  const iocIn = $('#ioc-in');
  const iocOut = $('#ioc-out');
  $('#ioc-extract').addEventListener('click', () => {
    const found = extractIocs(iocIn.value);
    const lines = Object.entries(found).filter(([, v]) => v.length).map(([k, v]) => `${k} (${v.length})\n  ${v.map(defang).join('\n  ')}`);
    iocOut.textContent = lines.join('\n\n') || 'No indicators found.';
  });
  $('#ioc-defang').addEventListener('click', () => { iocOut.textContent = defang(refang(iocIn.value)); });
  $('#ioc-refang').addEventListener('click', () => { iocOut.textContent = refang(iocIn.value); });
  $('#ioc-copy').addEventListener('click', () => copy(iocOut.textContent));

  // JWT
  $('#jwt-in').addEventListener('input', (e) => {
    const out = $('#jwt-out');
    const parts = e.target.value.trim().split('.');
    if (parts.length < 2) { out.textContent = ''; return; }
    try {
      const header = JSON.parse(b64dec(parts[0]));
      const payload = JSON.parse(b64dec(parts[1]));
      let note = '';
      if (payload.exp) {
        const exp = new Date(payload.exp * 1000);
        note = exp < new Date() ? `\n\n⚠ Expired ${exp.toLocaleString()}` : `\n\nValid until ${exp.toLocaleString()}`;
      }
      if (header.alg === 'none') note += '\n⚠ alg "none" — unsigned token, never accept this server-side.';
      out.textContent = `HEADER\n${JSON.stringify(header, null, 2)}\n\nPAYLOAD\n${JSON.stringify(payload, null, 2)}${note}`;
    } catch { out.textContent = 'Not a valid JWT.'; }
  });

  // Encoders
  root.querySelectorAll('[data-enc]').forEach(b => b.addEventListener('click', () => {
    const v = $('#enc-in').value;
    const fn = { b64e: b64enc, b64d: b64dec, urle: encodeURIComponent, urld: decodeURIComponent, hexe: hexenc, hexd: hexdec }[b.dataset.enc];
    try { $('#enc-out').textContent = fn(v); } catch (e) { $('#enc-out').textContent = `Can't decode: ${e.message}`; }
  }));
}

function copy(text) {
  if (!text) return;
  navigator.clipboard?.writeText(text).then(() => toast('Copied', 'success'), () => toast('Copy blocked by the browser', 'error'));
}
