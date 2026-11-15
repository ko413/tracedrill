// member.js を Node で動かし、Python が作った鍵束と暗号化ファイルを実際に開けるか確かめる
// 使い方: node node_member_check.js <公開フォルダ> <会員の合言葉> <模試の名前> <member.js> [単品の合言葉 単品の模試の名前]
const fs = require('fs'), vm = require('vm'), path = require('path');
const [dir, passphrase, bundleId, script, singlePass, singleId] = process.argv.slice(2);
const mem = {};
const sandbox = {
  window: {}, console, atob, TextEncoder, TextDecoder, crypto: globalThis.crypto, JSON, Uint8Array, String, Error, Object,
  encodeURIComponent,
  document: { querySelector: () => ({ getAttribute: () => '/members/' }) },
  fetch: async (url) => { const f = path.join(dir, url.replace('/members/', ''));
    return fs.existsSync(f) ? { ok: true, json: async () => JSON.parse(fs.readFileSync(f, 'utf8')) } : { ok: false }; },
};
sandbox.window.localStorage = { getItem: k => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = v; }, removeItem: k => { delete mem[k]; } };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(script, 'utf8'), sandbox);
(async () => {
  const A = sandbox.window.MemberAuth;
  const out = { before: await A.keys(), wrong: await A.login('AAAA-BBBB-CCCC-DDDD', singleId ? [singleId] : []) };
  if (singlePass) {
    // 単品の合言葉：その回だけが開く。会員用の鍵束は開かない
    out.singleOk = await A.login(singlePass.toLowerCase(), [singleId]);
    const only = await A.keys();
    out.singleIds = Object.keys(only).sort();
    const box1 = JSON.parse(fs.readFileSync(path.join(dir, 'data', singleId + '.json'), 'utf8'));
    out.singleTitle = (await A.open(only[singleId], box1)).id;
    out.singleExpired = await A.expired();
    A.logout();
    out.afterSingle = await A.keys();
  }
  out.ok = await A.login(passphrase.toLowerCase().replace(/-/g, ' '));   // 小文字・空白でも通る
  const keys = await A.keys();
  out.ids = Object.keys(keys).sort();
  const box = JSON.parse(fs.readFileSync(path.join(dir, 'data', bundleId + '.json'), 'utf8'));
  const bundle = await A.open(keys[bundleId], box);
  out.title = bundle.title; out.count = bundle.questions.length;
  out.expired = await A.expired();
  A.logout(); out.after = await A.keys();
  console.log(JSON.stringify(out));
})().catch(e => { console.error('FAIL', e); process.exit(1); });
