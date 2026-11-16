// site/static/member-b.js（B案の確認）を Node で動かして確かめる。API は偽物。
//   1) B案だけ：ログイン前は null、ログイン後は API の鍵の表。open() で暗号化ファイルが開く
//   2) 合言葉（member.js）と並べる：両方の鍵を合わせる。API が止まっていても合言葉の鍵は返る
const fs = require('fs'), vm = require('vm'), path = require('path');
const root = path.join(__dirname, '..', 'site', 'static');
const API = 'https://api.example.test';

function sandbox(api, { search = '' } = {}) {
  const mem = {}, calls = [];
  const box = {
    window: { location: { search, pathname: '/members/', href: '' }, history: { replaceState: (a, b, url) => { box.window.location.replaced = url; } } },
    console, atob, btoa, TextEncoder, TextDecoder, crypto: globalThis.crypto, JSON, Uint8Array, String, Error, Object, Promise, URLSearchParams,
    encodeURIComponent,
    document: { querySelector: (sel) => sel === '[data-member-api]'
      ? { getAttribute: () => API + '/' } : { getAttribute: () => '/members/' } },
    fetch: async (url, init = {}) => {
      calls.push(`${init.method || 'GET'} ${url.replace(API, '')}`);
      if (!url.startsWith(API)) return { ok: false, status: 404, json: async () => ({}) };      // 鍵束（keyring.json）はない
      if (init.credentials !== 'include') throw new Error('credentials: include がない');
      return api(url.replace(API, ''), init);
    },
  };
  box.window.localStorage = { getItem: k => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = v; }, removeItem: k => { delete mem[k]; } };
  vm.createContext(box);
  return { box, calls, run: (file) => vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), box) };
}

const res = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

(async () => {
  const out = {};
  // 暗号化ファイルを1つ作る（tools/members.py と同じ AES-256-GCM）
  const raw = crypto.getRandomValues(new Uint8Array(32)), iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await crypto.subtle.importKey('raw', raw, { name: 'AES-GCM' }, false, ['encrypt']);
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(JSON.stringify({ id: 'mock-001', title: '第1回' })));
  const b64 = (buf) => Buffer.from(buf).toString('base64');
  const KEYS = { 'mock-001': b64(raw) };

  // 1) B案だけ
  let signedIn = false, member = true;
  const api = async (pathName, init) => {
    if (pathName === '/keys') {
      if (!signedIn) return res(401, { error: 'signed_out' });
      const status = { member, state: member ? 'active' : 'past_due', period_end: 1900000000, cancels: false };
      return member ? res(200, { keys: KEYS, status }) : res(403, { error: 'inactive', status });
    }
    if (pathName === '/session') { signedIn = JSON.parse(init.body).token === 'good'; return res(signedIn ? 200 : 403, {}); }
    if (pathName === '/claim') { signedIn = JSON.parse(init.body).session_id === 'cs_test_1'; return res(signedIn ? 200 : 403, {}); }
    if (pathName === '/login') return JSON.parse(init.body).email.includes('@') ? res(200, { ok: true }) : res(400, {});
    if (pathName === '/checkout') return res(200, { url: 'https://checkout.stripe.test/pay' });
    if (pathName === '/portal') return res(200, { url: 'https://billing.stripe.test/portal' });
    if (pathName === '/logout') { signedIn = false; return res(200, {}); }
    return res(404, {});
  };
  let s = sandbox(api); s.run('member-b.js');
  let A = s.box.window.MemberAuth, B = s.box.window.MemberBilling;
  out.methodEmail = A.method === 'email';
  out.signedOutIsNull = (await A.keys()) === null && B.status().signedIn === false;
  out.passphraseLoginIsOff = (await A.login('ABCD-EFGH-JKMN-PQRS', [])) === false && (await A.expired()) === false;
  out.finishNothing = (await B.finish()) === null;
  out.sendLink = (await B.sendLink('taro@example.com')) === 'sent' && (await B.sendLink('x')) === 'bad_email';

  s = sandbox(api, { search: '?login=good&id=mock-001' }); s.run('member-b.js');
  A = s.box.window.MemberAuth; B = s.box.window.MemberBilling;
  out.finishLogin = (await B.finish()) === 'login' && s.box.window.location.replaced === '/members/?id=mock-001';   // 番号を URL に残さない
  const keys = await A.keys();
  out.keysAfterLogin = JSON.stringify(keys) === JSON.stringify(KEYS) && B.status().member === true;
  out.opens = (await A.open(keys['mock-001'], { iv: b64(iv), ct: b64(ct) })).title === '第1回';
  out.keysAreNotStored = s.box.window.localStorage.getItem('member-passphrase') === null && s.calls.filter(c => c === 'GET /keys').length === 1;
  await B.checkout(); out.checkout = s.box.window.location.href === 'https://checkout.stripe.test/pay';
  await B.portal(); out.portal = s.box.window.location.href === 'https://billing.stripe.test/portal';
  await A.logout(); out.logout = (await A.keys()) === null;

  signedIn = false;
  s = sandbox(api, { search: '?login=bad' }); s.run('member-b.js');
  out.finishFailed = (await s.box.window.MemberBilling.finish()) === 'failed' && (await s.box.window.MemberAuth.keys()) === null;
  s = sandbox(api, { search: '?joined=cs_test_1' }); s.run('member-b.js');
  out.finishJoined = (await s.box.window.MemberBilling.finish()) === 'joined' && (await s.box.window.MemberAuth.keys()) !== null;

  member = false;                                   // 支払い失敗：ログインはできているが、鍵は返らない
  s = sandbox(api); s.run('member-b.js');
  out.inactive = (await s.box.window.MemberAuth.keys()) === null && s.box.window.MemberBilling.status().signedIn === true
    && s.box.window.MemberBilling.status().state === 'past_due';
  member = true; signedIn = false;

  // 2) 合言葉と並べる（member.js を先に読み込む）
  s = sandbox(api); s.run('member.js');
  const passphraseAuth = s.box.window.MemberAuth;
  passphraseAuth.keys = async () => ({ 'mock-002': 'UEFTUw==' });        // 合言葉で開けた鍵がある、という状態にする
  s.run('member-b.js');
  A = s.box.window.MemberAuth;
  out.methodBoth = A.method === 'both';
  out.passphraseOnly = JSON.stringify(await A.keys()) === JSON.stringify({ 'mock-002': 'UEFTUw==' });
  signedIn = true;
  s = sandbox(api); s.run('member.js'); s.box.window.MemberAuth.keys = async () => ({ 'mock-002': 'UEFTUw==' }); s.run('member-b.js');
  out.merged = Object.keys(await s.box.window.MemberAuth.keys()).sort().join() === 'mock-001,mock-002';
  s = sandbox(async () => { throw new Error('down'); }); s.run('member.js');
  s.box.window.MemberAuth.keys = async () => ({ 'mock-002': 'UEFTUw==' }); s.run('member-b.js');
  out.apiDownPassphraseStillWorks = JSON.stringify(await s.box.window.MemberAuth.keys()) === JSON.stringify({ 'mock-002': 'UEFTUw==' });
  s = sandbox(async () => { throw new Error('down'); }); s.run('member-b.js');
  out.apiDownAloneIsAnError = await s.box.window.MemberAuth.keys().then(() => false, () => true);

  // 3) API の URL がなければ、何もしない（A案のまま）
  s = sandbox(api); s.box.document.querySelector = () => null; s.run('member-b.js');
  out.noApiNoChange = s.box.window.MemberAuth === undefined && s.box.window.MemberBilling === undefined;

  console.log(JSON.stringify(out));
})().catch(e => { console.error('FAIL', e); process.exit(1); });
