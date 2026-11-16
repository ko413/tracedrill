// Workers のテスト。Stripe・メール・KV はすべて偽物で、外へは何も送らない。
//   実行: node --test worker/test/worker.test.js    （追加のパッケージは不要。Node 20 以上）
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import worker, { verifyStripeSignature, entitlement, normalizeEmail } from '../src/index.js';

const SITE = 'https://tracedrill.com';
const API = 'https://api.tracedrill.com';
const WEBHOOK_SECRET = ['whsec', 'fake-for-tests'].join('_');
const KEYS = { 'mock-001': 'S0VZMQ==', 'mock-002': 'S0VZMg==', 'early-queue-ring-001': 'S0VZMw==' };

let clock, kv, env, stripeState, mails, stripeCalls, stripeDown;

class FakeKV {
  constructor() { this.map = new Map(); this.writes = 0; }
  async get(key) {
    const entry = this.map.get(key);
    if (!entry) return null;
    if (entry.expires && entry.expires <= clock) { this.map.delete(key); return null; }
    return entry.value;
  }
  async put(key, value, options) {
    this.writes++;
    this.map.set(key, { value: String(value), expires: options && options.expirationTtl ? clock + options.expirationTtl : null });
  }
  async delete(key) { this.map.delete(key); }
  keys(prefix) { return [...this.map.keys()].filter((k) => k.startsWith(prefix)); }
}

function reply(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

// Stripe と Resend の代わり
async function fakeFetch(input, init = {}) {
  const url = new URL(typeof input === 'string' ? input : input.url);
  if (url.host === 'api.resend.com') {
    assert.equal(init.headers.Authorization, 'Bearer mail-key');
    mails.push(JSON.parse(init.body));
    return reply({ id: 'mail_1' });
  }
  assert.equal(url.host, 'api.stripe.com');
  assert.equal(init.headers.Authorization, 'Bearer stripe-key');
  stripeCalls.push(`${init.method} ${url.pathname}`);
  if (stripeDown) return reply({ error: { type: 'api_error' } }, 500);
  const path = url.pathname.replace('/v1', '');
  let m;
  if (init.method === 'POST' && path === '/checkout/sessions') {
    const params = Object.fromEntries(new URLSearchParams(init.body));
    stripeState.lastCheckout = params;
    return reply({ id: 'cs_test_new', url: 'https://checkout.stripe.com/c/pay/cs_test_new' });
  }
  if ((m = path.match(/^\/checkout\/sessions\/(.+)$/))) {
    const found = stripeState.checkouts[m[1]];
    return found ? reply(found) : reply({ error: { type: 'invalid_request_error' } }, 404);
  }
  if ((m = path.match(/^\/customers\/(.+)$/))) return reply(stripeState.customers[m[1]]);
  if (path === '/subscriptions') {
    const customer = url.searchParams.get('customer');
    return reply({ data: stripeState.subscriptions.filter((s) => s.customer === customer) });
  }
  if (init.method === 'POST' && path === '/billing_portal/sessions') {
    const params = Object.fromEntries(new URLSearchParams(init.body));
    stripeState.lastPortal = params;
    return reply({ url: 'https://billing.stripe.com/p/session/test' });
  }
  return reply({ error: { type: 'invalid_request_error' } }, 404);
}

const realFetch = globalThis.fetch, realNow = Date.now;

beforeEach(() => {
  clock = 1_800_000_000;
  Date.now = () => clock * 1000;
  globalThis.fetch = fakeFetch;
  kv = new FakeKV();
  mails = []; stripeCalls = []; stripeDown = false;
  stripeState = { customers: {}, subscriptions: [], checkouts: {} };
  env = { MEMBERS: kv, STRIPE_SECRET_KEY: 'stripe-key', STRIPE_WEBHOOK_SECRET: WEBHOOK_SECRET, MAIL_API_KEY: 'mail-key',
    MAIL_FROM: 'ドリル <login@tracedrill.com>', SITE_URL: SITE,
    PLANS: JSON.stringify({ member: { price: 'price_member', mode: 'subscription' },
      single: { price: 'price_single', mode: 'payment', bundles: ['mock-001'] } }) };
  kv.map.set('keytable', { value: JSON.stringify(KEYS), expires: null });
});

process.on('exit', () => { globalThis.fetch = realFetch; Date.now = realNow; });

// ---- 道具 ----

function call(method, path, { body, cookie, origin = SITE, headers = {} } = {}) {
  const init = { method, headers: { ...headers } };
  if (origin) init.headers.Origin = origin;
  if (cookie) init.headers.Cookie = cookie;
  if (body !== undefined) { init.body = typeof body === 'string' ? body : JSON.stringify(body); init.headers['Content-Type'] = 'application/json'; }
  return worker.fetch(new Request(API + path, init), env);
}

function sign(payload, secret = WEBHOOK_SECRET, at = clock) {
  return `t=${at},v1=${createHmac('sha256', secret).update(`${at}.${payload}`).digest('hex')}`;
}

let eventNumber = 0;
function sendEvent(type, object, { id, signature } = {}) {
  const payload = JSON.stringify({ id: id || `evt_${++eventNumber}`, type, data: { object } });
  return call('POST', '/webhook', { body: payload, origin: null, headers: { 'Stripe-Signature': signature || sign(payload) } });
}

function subscription(customer, status, extra = {}) {
  return { id: `sub_${customer}`, customer, status, created: clock, current_period_end: clock + 30 * 86400,
    cancel_at_period_end: false, items: { data: [{ price: { id: 'price_member' } }] }, ...extra };
}

// 入会：Stripe に契約ができ、決済完了の Webhook が届く
async function join(email = 'taro@example.com', customer = 'cus_1') {
  stripeState.customers[customer] = { id: customer, email };
  stripeState.subscriptions = stripeState.subscriptions.filter((s) => s.customer !== customer);
  stripeState.subscriptions.push(subscription(customer, 'active'));
  const session = { id: `cs_test_${customer}`, mode: 'subscription', status: 'complete', payment_status: 'paid', customer,
    created: clock, customer_details: { email }, metadata: { plan: 'member' } };
  stripeState.checkouts[session.id] = session;
  const response = await sendEvent('checkout.session.completed', session);
  assert.equal(response.status, 200);
  return session;
}

function setStatus(customer, status, extra = {}) {
  const sub = stripeState.subscriptions.find((s) => s.customer === customer);
  Object.assign(sub, { status }, extra);
  return sub;
}

function cookieOf(response) {
  const header = response.headers.get('Set-Cookie');
  assert.ok(header, 'Set-Cookie がある');
  return header.split(';')[0];
}

// メールのリンクでログインして、Cookie を返す
async function signIn(email = 'taro@example.com') {
  const before = mails.length;
  assert.equal((await call('POST', '/login', { body: { email } })).status, 200);
  assert.equal(mails.length, before + 1, 'ログイン用のメールが1通送られる');
  const token = mails.at(-1).text.match(/\?login=([0-9a-f]{64})/)[1];
  const response = await call('POST', '/session', { body: { token } });
  assert.equal(response.status, 200);
  return { cookie: cookieOf(response), token };
}

async function getKeys(cookie) {
  const response = await call('GET', '/keys', { cookie });
  return { status: response.status, body: await response.json() };
}

// ---- 入会 ----

test('入会ボタン：Stripe の決済ページの URL を返し、月額・自動更新・解約方法を最終確認の画面に出す', async () => {
  const response = await call('POST', '/checkout', { body: {} });
  assert.deepEqual(await response.json(), { url: 'https://checkout.stripe.com/c/pay/cs_test_new' });
  const sent = stripeState.lastCheckout;
  assert.equal(sent.mode, 'subscription');
  assert.equal(sent['line_items[0][price]'], 'price_member');
  assert.equal(sent.success_url, `${SITE}/members/?joined={CHECKOUT_SESSION_ID}`);
  assert.equal(sent.locale, 'ja');
  assert.match(sent['custom_text[submit][message]'], /毎月自動で更新/);
  assert.match(sent['custom_text[submit][message]'], /解約/);
  assert.match(sent['custom_text[submit][message]'], /tokushoho/);
  assert.equal(sent['consent_collection[terms_of_service]'], undefined);       // 利用規約の URL がなければ、同意欄は出さない
});

test('利用規約の URL を設定すると、同意のチェックが必須になる', async () => {
  env.TERMS_URL = `${SITE}/terms/`;
  await call('POST', '/checkout', { body: {} });
  assert.equal(stripeState.lastCheckout['consent_collection[terms_of_service]'], 'required');
  assert.match(stripeState.lastCheckout['custom_text[terms_of_service_acceptance][message]'], /利用規約/);
  assert.match(stripeState.lastCheckout['custom_text[submit][message]'], /毎月自動で更新/);
});

test('設定していないプランは断る', async () => {
  assert.equal((await call('POST', '/checkout', { body: { plan: 'team' } })).status, 400);
  env.PLANS = '{}';
  assert.equal((await call('POST', '/checkout', { body: {} })).status, 400);
});

test('入会 → メールのリンクでログイン → 鍵の表が返る', async () => {
  await join();
  const { cookie } = await signIn();
  const { status, body } = await getKeys(cookie);
  assert.equal(status, 200);
  assert.deepEqual(body.keys, KEYS);
  assert.equal(body.status.member, true);
  assert.equal(body.status.state, 'active');
  assert.match(mails[0].subject, /ログイン/);
  assert.deepEqual(mails[0].to, ['taro@example.com']);
});

test('支払いを終えて戻ってきたら、メールを待たずにログイン済みになる（Webhook より先でもよい）', async () => {
  stripeState.customers.cus_9 = { id: 'cus_9', email: 'hana@example.com' };
  stripeState.subscriptions.push(subscription('cus_9', 'active'));
  stripeState.checkouts.cs_test_9 = { id: 'cs_test_9', mode: 'subscription', status: 'complete', payment_status: 'paid',
    customer: 'cus_9', created: clock, customer_details: { email: 'Hana@Example.com' }, metadata: {} };
  const response = await call('POST', '/claim', { body: { session_id: 'cs_test_9' } });
  assert.equal(response.status, 200);
  assert.deepEqual((await getKeys(cookieOf(response))).body.keys, KEYS);
});

test('支払いが済んでいない・古い・でたらめな決済 ID では、ログイン済みにならない', async () => {
  stripeState.checkouts.cs_test_open = { id: 'cs_test_open', mode: 'subscription', status: 'open', payment_status: 'unpaid',
    customer: null, created: clock, customer_details: null };
  assert.equal((await call('POST', '/claim', { body: { session_id: 'cs_test_open' } })).status, 403);
  const session = await join();
  clock += 2 * 86400;
  assert.equal((await call('POST', '/claim', { body: { session_id: session.id } })).status, 403);
  assert.equal((await call('POST', '/claim', { body: { session_id: '../customers/cus_1' } })).status, 400);
  assert.equal((await call('POST', '/claim', { body: { session_id: 'cs_test_none' } })).status, 500);
});

// ---- 更新・解約・支払い失敗 ----

test('更新：期間の終わりが延びても、そのまま開ける', async () => {
  await join();
  clock += 30 * 86400 + 60;
  const sub = setStatus('cus_1', 'active', { current_period_end: clock + 30 * 86400 });
  await sendEvent('invoice.paid', { customer: 'cus_1', subscription: sub.id });
  const { cookie } = await signIn();
  const { status, body } = await getKeys(cookie);
  assert.equal(status, 200);
  assert.equal(body.status.period_end, clock + 30 * 86400);
});

test('解約の予約：期間の終わりまでは開く。終わったら開かない', async () => {
  await join();
  const { cookie } = await signIn();
  const sub = setStatus('cus_1', 'active', { cancel_at_period_end: true });
  await sendEvent('customer.subscription.updated', sub);
  let result = await getKeys(cookie);
  assert.equal(result.status, 200);
  assert.equal(result.body.status.cancels, true);
  clock += 29 * 86400;
  assert.equal((await getKeys(cookie)).status, 200);            // 期間の終わりの前日も開く
  clock += 86400 + 60;
  setStatus('cus_1', 'canceled');
  await sendEvent('customer.subscription.deleted', { ...sub, status: 'canceled' });
  result = await getKeys((await signIn()).cookie);
  assert.equal(result.status, 403);
  assert.equal(result.body.error, 'inactive');
  assert.equal(result.body.keys, undefined);
});

test('解約の Webhook が届かなくても、期間が過ぎたら Stripe に確かめ直して閉じる', async () => {
  await join();
  const { cookie } = await signIn();
  setStatus('cus_1', 'canceled');                       // Stripe 側では解約済み。Webhook は届いていない
  assert.equal((await getKeys(cookie)).status, 200);    // 12時間以内は、前に確かめた状態を使う
  clock += 13 * 3600;
  assert.equal((await getKeys(cookie)).status, 403);
});

test('支払い失敗：開かなくなる。カードを直して支払えたら、また開く', async () => {
  await join();
  const { cookie } = await signIn();
  setStatus('cus_1', 'past_due');
  await sendEvent('invoice.payment_failed', { customer: 'cus_1' });
  const failed = await getKeys(cookie);
  assert.equal(failed.status, 403);
  assert.equal(failed.body.status.state, 'past_due');
  setStatus('cus_1', 'active');
  await sendEvent('invoice.paid', { customer: 'cus_1' });
  assert.equal((await getKeys(cookie)).status, 200);
});

test('Webhook が逆の順番で届いても、Stripe の今の状態に合う', async () => {
  await join();
  const { cookie } = await signIn();
  const old = { ...subscription('cus_1', 'active') };
  setStatus('cus_1', 'canceled');
  await sendEvent('customer.subscription.deleted', { ...old, status: 'canceled' });
  await sendEvent('customer.subscription.updated', old);        // 古い「有効」が後から届く
  assert.equal((await getKeys(cookie)).status, 403);
});

test('入り直し：解約した人が同じメールでもう一度入会すると、また開く', async () => {
  await join('taro@example.com', 'cus_1');
  setStatus('cus_1', 'canceled');
  await sendEvent('customer.subscription.deleted', { customer: 'cus_1' });
  await join('taro@example.com', 'cus_2');                       // Stripe は新しい顧客を作る
  const { cookie } = await signIn();
  assert.equal((await getKeys(cookie)).status, 200);
});

test('Stripe が止まっていても、最近確かめた会員は開ける。3日確かめられなければ閉じる', async () => {
  await join();
  const { cookie } = await signIn();
  stripeDown = true;
  clock += 13 * 3600;
  assert.equal((await getKeys(cookie)).status, 200);
  clock += 3 * 86400;
  assert.equal((await getKeys(cookie)).status, 503);
});

// ---- Webhook の安全 ----

test('署名のない・違う・古い Webhook は拒否し、何も書かない', async () => {
  const session = { id: 'cs_x', mode: 'subscription', status: 'complete', customer: 'cus_1', customer_details: { email: 'a@example.com' } };
  const payload = JSON.stringify({ id: 'evt_bad', type: 'checkout.session.completed', data: { object: session } });
  const before = kv.writes;
  for (const signature of [null, 't=1,v1=00', sign(payload, 'whsec_other'), sign(payload, WEBHOOK_SECRET, clock - 3600), 'garbage']) {
    const headers = signature ? { 'Stripe-Signature': signature } : {};
    const response = await call('POST', '/webhook', { body: payload, origin: null, headers });
    assert.equal(response.status, 400);
  }
  assert.equal((await call('POST', '/webhook', { body: payload + ' ', origin: null, headers: { 'Stripe-Signature': sign(payload) } })).status, 400);
  assert.equal(kv.writes, before);
  assert.equal(stripeCalls.length, 0);
});

test('署名の確認：正しければ true。秘密の値がなければ必ず false', async () => {
  const payload = '{"id":"evt_1"}';
  assert.equal(await verifyStripeSignature(payload, sign(payload), WEBHOOK_SECRET, clock), true);
  assert.equal(await verifyStripeSignature(payload, sign(payload), '', clock), false);
  assert.equal(await verifyStripeSignature(payload, sign(payload), undefined, clock), false);
  const rotated = `t=${clock},v1=${'0'.repeat(64)},${sign(payload).split(',')[1]}`;     // 鍵の入れ替え中は v1 が2つ付く
  assert.equal(await verifyStripeSignature(payload, rotated, WEBHOOK_SECRET, clock), true);
});

test('同じ Webhook が2回届いても、処理は1回だけ', async () => {
  const session = await join();
  const calls = stripeCalls.length;
  const again = await sendEvent('checkout.session.completed', session, { id: `evt_${eventNumber}` });
  assert.equal(await again.text(), 'ok (duplicate)');
  assert.equal(stripeCalls.length, calls);
});

test('処理の途中で失敗したら 500 を返し、「済み」にしない（Stripe が送り直す）', async () => {
  stripeState.customers.cus_1 = { id: 'cus_1', email: 'taro@example.com' };
  stripeState.subscriptions.push(subscription('cus_1', 'active'));
  stripeDown = true;
  assert.equal((await sendEvent('customer.subscription.created', { customer: 'cus_1' }, { id: 'evt_retry' })).status, 500);
  stripeDown = false;
  assert.equal((await sendEvent('customer.subscription.created', { customer: 'cus_1' }, { id: 'evt_retry' })).status, 200);
  const { cookie } = await signIn();
  assert.equal((await getKeys(cookie)).status, 200);
});

test('関係のない種類の Webhook は、何もせず受け取る', async () => {
  const response = await sendEvent('charge.refunded', { customer: 'cus_404' });
  assert.equal(response.status, 200);
  assert.equal(stripeCalls.length, 0);
});

// ---- ログイン ----

test('会員でないメールでも返事は同じ。メールは送らず、何も書かない', async () => {
  await join();
  const member = await call('POST', '/login', { body: { email: 'taro@example.com' } });
  const before = kv.writes;
  const stranger = await call('POST', '/login', { body: { email: 'nobody@example.com' } });
  assert.equal(stranger.status, member.status);
  assert.equal(await stranger.text(), await member.text());
  assert.equal(mails.length, 1);
  assert.equal(kv.writes, before);
});

test('ログイン用のリンクは1回だけ、15分だけ使える', async () => {
  await join();
  const { token } = await signIn();
  assert.equal((await call('POST', '/session', { body: { token } })).status, 403);            // 2回目
  clock += 121;
  await call('POST', '/login', { body: { email: 'taro@example.com' } });
  const late = mails.at(-1).text.match(/\?login=([0-9a-f]{64})/)[1];
  clock += 15 * 60 + 1;
  assert.equal((await call('POST', '/session', { body: { token: late } })).status, 403);       // 期限切れ
  assert.equal((await call('POST', '/session', { body: { token: 'f'.repeat(64) } })).status, 403);
  assert.equal((await call('POST', '/session', { body: { token: 'x' } })).status, 400);
});

test('ログイン用のメールは、同じ宛先に2分に1通まで', async () => {
  await join();
  for (let i = 0; i < 5; i++) await call('POST', '/login', { body: { email: 'TARO@example.com ' } });
  assert.equal(mails.length, 1);
  clock += 121;
  await call('POST', '/login', { body: { email: 'taro@example.com' } });
  assert.equal(mails.length, 2);
});

test('メールアドレスの形でないものは断る。大文字・全角・前後の空白は同じ人として扱う', async () => {
  assert.equal((await call('POST', '/login', { body: { email: 'not-an-email' } })).status, 400);
  assert.equal((await call('POST', '/login', { body: {} })).status, 400);
  assert.equal(normalizeEmail('  Ｔaro@Example.COM '), 'taro@example.com');
  assert.equal(normalizeEmail('a b@example.com'), null);
});

test('メールアドレスそのものは KV に保存しない', async () => {
  await join();
  await signIn();
  for (const [key, entry] of kv.map) {
    assert.ok(!key.includes('taro') && !entry.value.includes('taro@'), `${key} にメールアドレスが入っている`);
  }
});

test('ログインしていない・でたらめな Cookie では鍵を返さない', async () => {
  await join();
  assert.equal((await getKeys(null)).status, 401);
  assert.equal((await getKeys('td_session=' + 'a'.repeat(64))).status, 401);
  assert.equal((await getKeys('td_session=../../member')).status, 401);
});

test('セッションは30日で切れる。ログアウトすると、その Cookie では開けない', async () => {
  await join();
  const first = await signIn();
  const out = await call('POST', '/logout', { cookie: first.cookie });
  assert.match(out.headers.get('Set-Cookie'), /Max-Age=0/);
  assert.equal((await getKeys(first.cookie)).status, 401);
  clock += 121;
  const second = await signIn();
  clock += 30 * 86400 + 1;
  setStatus('cus_1', 'active', { current_period_end: clock + 86400 });
  assert.equal((await getKeys(second.cookie)).status, 401);
});

test('Cookie は HttpOnly・Secure・SameSite=Lax', async () => {
  await join();
  await call('POST', '/login', { body: { email: 'taro@example.com' } });
  const token = mails[0].text.match(/\?login=([0-9a-f]{64})/)[1];
  const header = (await call('POST', '/session', { body: { token } })).headers.get('Set-Cookie');
  assert.match(header, /HttpOnly/); assert.match(header, /Secure/); assert.match(header, /SameSite=Lax/);
});

// ---- 支払い・解約のページ ----

test('「支払い・解約」：ログイン済みなら Stripe の管理ページの URL を返す', async () => {
  await join();
  const { cookie } = await signIn();
  const response = await call('POST', '/portal', { cookie });
  assert.deepEqual(await response.json(), { url: 'https://billing.stripe.com/p/session/test' });
  assert.equal(stripeState.lastPortal.customer, 'cus_1');
  assert.equal(stripeState.lastPortal.return_url, `${SITE}/members/`);
  assert.equal((await call('POST', '/portal', {})).status, 401);
});

test('解約した人も、ログインして支払いのページを開ける（入り直しや領収書のため）', async () => {
  await join();
  setStatus('cus_1', 'canceled');
  await sendEvent('customer.subscription.deleted', { customer: 'cus_1' });
  const { cookie } = await signIn();
  assert.equal((await getKeys(cookie)).status, 403);
  assert.equal((await call('POST', '/portal', { cookie })).status, 200);
});

// ---- 外からの要求の制限 ----

test('状態を変える要求は、サイトのページから来たものだけ受け付ける', async () => {
  for (const origin of ['https://evil.example', null]) {
    assert.equal((await call('POST', '/checkout', { body: {}, origin })).status, 403);
    assert.equal((await call('POST', '/login', { body: { email: 'a@example.com' }, origin })).status, 403);
  }
  const response = await call('OPTIONS', '/keys');
  assert.equal(response.status, 204);
  assert.equal(response.headers.get('Access-Control-Allow-Origin'), SITE);
  assert.equal(response.headers.get('Access-Control-Allow-Credentials'), 'true');
  assert.equal((await call('GET', '/nothing')).status, 404);
  assert.equal((await call('GET', '/webhook')).status, 404);
});

test('エラーの返事や記録に、秘密の値を出さない', async () => {
  const logged = [];
  const original = console.error;
  console.error = (...args) => logged.push(args.join(' '));
  try {
    stripeDown = true;
    const response = await call('POST', '/checkout', { body: {} });
    assert.equal(response.status, 500);
    const text = (await response.text()) + logged.join('\n');
    assert.ok(!text.includes('stripe-key') && !text.includes(WEBHOOK_SECRET) && !text.includes('mail-key'));
  } finally { console.error = original; }
});

// ---- 後から足すもの（単品・法人）の余地 ----

test('単品：買った回の鍵だけが返る。会員になると全部が返る', async () => {
  const response = await call('POST', '/checkout', { body: { plan: 'single', bundle: 'mock-001' } });
  assert.equal(response.status, 200);
  assert.equal(stripeState.lastCheckout.mode, 'payment');
  assert.equal(stripeState.lastCheckout['metadata[bundle]'], 'mock-001');
  assert.equal(stripeState.lastCheckout['custom_text[submit][message]'], undefined);    // 自動更新の説明は、単品には出さない
  assert.equal((await call('POST', '/checkout', { body: { plan: 'single', bundle: 'mock-002' } })).status, 400);   // 売っていない回

  const session = { id: 'cs_test_single', mode: 'payment', status: 'complete', payment_status: 'paid', customer: 'cus_5',
    created: clock, customer_details: { email: 'jiro@example.com' }, metadata: { plan: 'single', bundle: 'mock-001' } };
  stripeState.customers.cus_5 = { id: 'cus_5', email: 'jiro@example.com' };
  await sendEvent('checkout.session.completed', session);
  await sendEvent('checkout.session.completed', session, { id: 'evt_again_single' });
  const { cookie } = await signIn('jiro@example.com');
  let result = await getKeys(cookie);
  assert.deepEqual(result.body.keys, { 'mock-001': KEYS['mock-001'] });
  assert.equal(result.body.status.member, false);

  await join('jiro@example.com', 'cus_6');
  result = await getKeys(cookie);
  assert.deepEqual(result.body.keys, KEYS);
});

test('何を開けるかの判断は1か所（entitlement）。有効・お試し中だけが全部を開ける', () => {
  const member = (status) => ({ customers: { cus_1: { status } }, singles: ['mock-001'] });
  assert.deepEqual(entitlement(member('active')), { all: true, singles: [] });
  assert.deepEqual(entitlement(member('trialing')), { all: true, singles: [] });
  for (const status of ['past_due', 'canceled', 'unpaid', 'incomplete', 'incomplete_expired', 'paused', 'none']) {
    assert.deepEqual(entitlement(member(status)), { all: false, singles: ['mock-001'] });
  }
  assert.deepEqual(entitlement({ customers: {} }), { all: false, singles: [] });
});

test('鍵の表は、環境変数 KEY_TABLE があればそちらを使う', async () => {
  await join();
  const { cookie } = await signIn();
  env.KEY_TABLE = JSON.stringify({ 'mock-009': 'TkVX' });
  assert.deepEqual((await getKeys(cookie)).body.keys, { 'mock-009': 'TkVX' });
});

test('契約の期間の終わりが明細の中にある版の API でも読める', async () => {
  stripeState.customers.cus_1 = { id: 'cus_1', email: 'taro@example.com' };
  const sub = subscription('cus_1', 'active');
  delete sub.current_period_end;
  sub.items.data[0].current_period_end = clock + 7 * 86400;
  stripeState.subscriptions.push(sub);
  await sendEvent('customer.subscription.created', sub);
  const { cookie } = await signIn();
  assert.equal((await getKeys(cookie)).body.status.period_end, clock + 7 * 86400);
});
