// site/static/progress.js（学習記録）を Node で確かめる。
//   保存できる環境／保存できない環境（プライベートブラウズなど）／壊れた保存内容
const fs = require('fs'), vm = require('vm'), path = require('path');
const source = fs.readFileSync(path.join(__dirname, '..', 'site', 'static', 'progress.js'), 'utf8');

function load(storage) {
  const box = { window: {}, JSON, Object, Array, Math, Date, String };
  if (storage !== undefined) Object.defineProperty(box.window, 'localStorage', { get: storage });
  vm.createContext(box);
  vm.runInContext(source, box);
  return box.window.Progress;
}

function memoryStorage(initial) {
  const mem = Object.assign({}, initial);
  const api = { getItem: k => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = String(v); }, removeItem: k => { delete mem[k]; } };
  return { get: () => api, mem };
}

const out = {};
// 1) ふつうの環境
let s = memoryStorage();
let P = load(s.get);
out.available = P.available() === true;
out.emptyAtFirst = P.get('stack-basic-001/02') === null && P.summary().done === 0 && P.review().length === 0;
P.record('stack-basic-001/02', true); P.record('stack-basic-001/03', false); P.record('loop-sum-001/01', false);
out.recorded = P.get('stack-basic-001/02') === 'ok' && P.get('stack-basic-001/03') === 'ng';
out.summary = JSON.stringify(P.summary()) === JSON.stringify({ done: 3, ok: 1, ng: 2 });
out.review = P.review().join() === 'loop-sum-001/01,stack-basic-001/03' && P.review('stack-basic-001/').join() === 'stack-basic-001/03';
out.count = JSON.stringify(P.count('stack-basic-001/')) === JSON.stringify({ ok: 1, ng: 1 });
P.record('stack-basic-001/03', true);
out.latestWins = P.get('stack-basic-001/03') === 'ok' && P.review('stack-basic-001/').length === 0;
// 保存されるのは、識別子・結果・日時だけ
const saved = JSON.parse(s.mem['drill-progress']);
out.onlyIdResultTime = Object.keys(s.mem).join() === 'drill-progress'
  && Object.values(saved).every(e => Object.keys(e).sort().join() === 'r,t' && /^(ok|ng)$/.test(e.r) && Number.isInteger(e.t));
P.record('../../etc', true); P.record('<script>', true); P.record(42, true);
out.badIdsIgnored = Object.keys(JSON.parse(s.mem['drill-progress'])).length === 3;
out.persists = load(s.get).get('stack-basic-001/02') === 'ok';
P.clear();
out.cleared = !('drill-progress' in s.mem) && P.summary().done === 0;

// 2) 保存できない環境：読むのも書くのも例外。エラーにならず、ページの中では印が付く
const throwing = () => ({ getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }, removeItem() { throw new Error('denied'); } });
P = load(throwing);
out.unavailable = P.available() === false;
let threw = false;
try { P.record('stack-basic-001/02', false); P.get('x/1'); P.summary(); P.review(); P.count('x/'); } catch (e) { threw = true; }
out.noErrorWithoutStorage = !threw && P.get('stack-basic-001/02') === 'ng' && P.summary().ng === 1;
try { P.clear(); } catch (e) { threw = true; }
out.clearWithoutStorage = !threw && P.summary().done === 0;
// localStorage に触れただけで例外になるブラウザ
P = load(() => { throw new Error('SecurityError'); });
threw = false;
try { P.record('a-1/01', true); P.summary(); P.clear(); } catch (e) { threw = true; }
out.noErrorWhenAccessThrows = !threw && P.available() === false;
// localStorage そのものがない
P = load(undefined);
threw = false;
try { P.record('a-1/01', true); } catch (e) { threw = true; }
out.noErrorWhenMissing = !threw && P.get('a-1/01') === 'ok';

// 3) 保存内容が壊れている・ほかの形になっている
for (const [name, text] of [['brokenJson', '{oops'], ['arrayInstead', '[1,2]'], ['stringInstead', '"x"'], ['oddEntries', '{"a-1/01":{"r":"maybe"},"b-1/02":null,"c-1/03":{"r":"ok","t":1}}']]) {
  s = memoryStorage({ 'drill-progress': text });
  P = load(s.get);
  threw = false;
  let sum;
  try { sum = P.summary(); P.review(); P.get('a-1/01'); P.count('b-1/'); } catch (e) { threw = true; }
  out[name] = !threw && sum.done === (name === 'oddEntries' ? 1 : 0);
}
console.log(JSON.stringify(out));
