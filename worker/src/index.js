/* 会員の確認（B案）：Stripe の定期課金と Cloudflare Workers。

   まだ公開していない。設定と公開の手順は MIGRATION_B.md。
   秘密の値はここに書かない。すべて env（wrangler secret / .dev.vars）から受け取る。

   env:
     MEMBERS               KV。会員の状態・ログイン用の番号・セッション・鍵の表
     STRIPE_SECRET_KEY     Stripe の（できれば制限付き）シークレットキー
     STRIPE_WEBHOOK_SECRET Webhook の署名を確かめる値
     MAIL_API_KEY          メール送信サービス（Resend）のキー
     MAIL_FROM             送信元（例 "擬似言語トレースドリル <login@tracedrill.com>"）
     SITE_URL              サイトの URL（例 https://tracedrill.com）。CORS と戻り先に使う
     PLANS                 JSON。{"member": {"price": "price_…", "mode": "subscription"}}
                           単品は {"single": {"price": "price_…", "mode": "payment", "bundles": ["mock-001"]}}
     TERMS_URL             （任意）利用規約の URL。あれば Checkout で同意のチェックを必須にする
     KEY_TABLE             （任意）鍵の表の JSON。なければ KV の "keytable" を使う

   KV に入れるもの（メールアドレスそのものは保存しない。SHA-256 のハッシュだけ）:
     member:<メールのハッシュ>   {customers: {cus_…: {status, period_end, plan, sub}}, singles: [...], checked}
     customer:<cus_…>            メールのハッシュ
     token:<番号のハッシュ>      メールのハッシュ（15分で消える。1回使ったら消す）
     session:<番号のハッシュ>    メールのハッシュ（30日で消える）
     event:<evt_…>               処理済みの Webhook（7日で消える）
     ratelimit:<メールのハッシュ> ログイン用メールの送りすぎ防止（2分で消える）
     keytable                    鍵の表（private/keys.json の中身）
*/

const TOKEN_TTL = 15 * 60;
const SESSION_TTL = 30 * 24 * 60 * 60;
const EVENT_TTL = 7 * 24 * 60 * 60;
const RATE_TTL = 120;
const STALE_AFTER = 12 * 60 * 60;          // これより古い状態は、鍵を渡す前に Stripe で確かめ直す
const SIGNATURE_TOLERANCE = 5 * 60;
const ACTIVE = ['active', 'trialing'];     // 模試を開ける状態。past_due（支払い失敗）は開けない
const COOKIE = 'td_session';

// ---------- 小さな道具 ----------

const encoder = new TextEncoder();

function hex(buffer) {
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function sha256(text) {
  return hex(await crypto.subtle.digest('SHA-256', encoder.encode(text)));
}

function randomToken() {
  return hex(crypto.getRandomValues(new Uint8Array(32)));
}

export function normalizeEmail(value) {
  const email = String(value || '').normalize('NFKC').trim().toLowerCase();
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && email.length <= 254 ? email : null;
}

// 長さが同じ文字列を、途中で打ち切らずに比べる（署名の比較用）
function sameText(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function now() {
  return Math.floor(Date.now() / 1000);
}

function siteOrigin(env) {
  return new URL(env.SITE_URL).origin;
}

function json(env, body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'Access-Control-Allow-Origin': siteOrigin(env),
      'Access-Control-Allow-Credentials': 'true',
      'Vary': 'Origin',
      ...headers,
    },
  });
}

function plans(env) {
  try { return JSON.parse(env.PLANS || '{}'); } catch (e) { return {}; }
}

async function kvGet(env, key) {
  const text = await env.MEMBERS.get(key);
  return text === null ? null : JSON.parse(text);
}

function kvPut(env, key, value, ttl) {
  return env.MEMBERS.put(key, JSON.stringify(value), ttl ? { expirationTtl: ttl } : undefined);
}

// ---------- Stripe ----------

function form(params, prefix = '', out = new URLSearchParams()) {
  for (const [key, value] of Object.entries(params)) {
    const name = prefix ? `${prefix}[${key}]` : key;
    if (value === undefined || value === null) continue;
    if (typeof value === 'object') form(value, name, out);
    else out.append(name, String(value));
  }
  return out;
}

async function stripe(env, method, path, params) {
  const init = { method, headers: { Authorization: `Bearer ${env.STRIPE_SECRET_KEY}` } };
  let url = `https://api.stripe.com/v1${path}`;
  if (params && method === 'GET') url += `?${form(params)}`;
  else if (params) {
    init.headers['Content-Type'] = 'application/x-www-form-urlencoded';
    init.body = form(params).toString();
  }
  const response = await fetch(url, init);
  const body = await response.json();
  if (!response.ok) {
    const error = new Error(`stripe ${response.status} ${body && body.error ? body.error.type : ''}`);
    error.status = response.status;
    throw error;
  }
  return body;
}

// Stripe-Signature ヘッダー（t=…,v1=…）を確かめる。合わなければ false
export async function verifyStripeSignature(payload, header, secret, at = now()) {
  if (!header || !secret) return false;
  const parts = { t: null, v1: [] };
  for (const piece of header.split(',')) {
    const [key, value] = piece.split('=');
    if (key === 't') parts.t = value;
    if (key === 'v1') parts.v1.push(value);
  }
  if (!parts.t || !/^\d+$/.test(parts.t) || parts.v1.length === 0) return false;
  if (Math.abs(at - Number(parts.t)) > SIGNATURE_TOLERANCE) return false;
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const expected = hex(await crypto.subtle.sign('HMAC', key, encoder.encode(`${parts.t}.${payload}`)));
  return parts.v1.some((candidate) => sameText(candidate, expected));
}

// 契約の期間の終わり。API の版によって、契約の直下か、明細（items）の中にある
function periodEnd(subscription) {
  if (subscription.current_period_end) return subscription.current_period_end;
  const items = (subscription.items && subscription.items.data) || [];
  return items.reduce((latest, item) => Math.max(latest, item.current_period_end || 0), 0) || null;
}

function planOf(env, subscription) {
  const prices = ((subscription.items && subscription.items.data) || []).map((item) => item.price && item.price.id);
  for (const [name, plan] of Object.entries(plans(env))) {
    if (plan.mode !== 'payment' && prices.includes(plan.price)) return name;
  }
  return 'member';
}

// ---------- 会員の状態 ----------

async function readMember(env, hash) {
  return (await kvGet(env, `member:${hash}`)) || { customers: {}, singles: [], checked: 0 };
}

// Stripe の今の状態を読んで、KV に書く。Webhook が届いた順番に左右されないよう、毎回 Stripe に聞き直す
async function syncCustomer(env, customerId, knownHash) {
  let hash = knownHash || (await env.MEMBERS.get(`customer:${customerId}`));
  if (!hash) {
    const customer = await stripe(env, 'GET', `/customers/${customerId}`);
    const email = normalizeEmail(customer.email);
    if (!email) return null;                       // メールのない顧客は会員にできない
    hash = await sha256(email);
  }
  const list = await stripe(env, 'GET', '/subscriptions', { customer: customerId, status: 'all', limit: 20 });
  const subs = list.data || [];
  // 有効な契約があればそれを、なければいちばん新しい契約を、その顧客の状態とする
  const best = subs.find((s) => ACTIVE.includes(s.status)) || subs.sort((a, b) => b.created - a.created)[0];
  const member = await readMember(env, hash);
  member.customers[customerId] = best
    ? { status: best.status, period_end: periodEnd(best), plan: planOf(env, best), sub: best.id,
        cancel_at_period_end: !!best.cancel_at_period_end }
    : { status: 'none', period_end: null, plan: null, sub: null, cancel_at_period_end: false };
  member.checked = now();
  await kvPut(env, `member:${hash}`, member);
  await env.MEMBERS.put(`customer:${customerId}`, hash);
  return hash;
}

// 何を開けるか。法人プランなどを足すときは、ここに条件を足す
export function entitlement(member) {
  const all = Object.values(member.customers || {}).some((c) => ACTIVE.includes(c.status));
  return { all, singles: all ? [] : [...(member.singles || [])] };
}

async function keyTable(env) {
  if (env.KEY_TABLE) return JSON.parse(env.KEY_TABLE);
  return (await kvGet(env, 'keytable')) || {};
}

// ---------- セッション ----------

function readCookie(request) {
  const header = request.headers.get('Cookie') || '';
  for (const piece of header.split(';')) {
    const [name, ...rest] = piece.trim().split('=');
    if (name === COOKIE) return rest.join('=');
  }
  return null;
}

function cookie(env, value, maxAge) {
  const secure = env.SITE_URL.startsWith('https://') ? ' Secure;' : '';
  return `${COOKIE}=${value}; Path=/; HttpOnly;${secure} SameSite=Lax; Max-Age=${maxAge}`;
}

async function startSession(env, hash) {
  const token = randomToken();
  await env.MEMBERS.put(`session:${await sha256(token)}`, hash, { expirationTtl: SESSION_TTL });
  return cookie(env, token, SESSION_TTL);
}

async function sessionHash(env, request) {
  const token = readCookie(request);
  if (!token || !/^[0-9a-f]{64}$/.test(token)) return null;
  return env.MEMBERS.get(`session:${await sha256(token)}`);
}

// ---------- メール ----------

async function sendLoginMail(env, email, link) {
  const text = [
    '擬似言語トレースドリルのログイン用リンクです。',
    '',
    link,
    '',
    'このリンクは15分間、1回だけ使えます。',
    'お心当たりがない場合は、このメールを破棄してください（何も起きません）。',
  ].join('\n');
  const response = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${env.MAIL_API_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ from: env.MAIL_FROM, to: [email], subject: '【擬似言語トレースドリル】ログイン用リンク', text }),
  });
  if (!response.ok) throw new Error(`mail ${response.status}`);
}

// ---------- 各エンドポイント ----------

// 入会（または単品の購入）を始める。Stripe の決済ページの URL を返す
async function checkout(env, request) {
  const body = await request.json().catch(() => ({}));
  const name = body.plan || 'member';
  const plan = plans(env)[name];
  if (!plan || !plan.price) return json(env, { error: 'unknown_plan' }, 400);
  const site = env.SITE_URL.replace(/\/$/, '');
  const params = {
    mode: plan.mode || 'subscription',
    line_items: { 0: { price: plan.price, quantity: 1 } },
    success_url: `${site}/members/?joined={CHECKOUT_SESSION_ID}`,
    cancel_url: `${site}/members/`,
    locale: 'ja',
    metadata: { plan: name },
  };
  if (params.mode === 'payment') {
    if (!(plan.bundles || []).includes(body.bundle)) return json(env, { error: 'unknown_bundle' }, 400);
    params.metadata.bundle = body.bundle;
    params.customer_creation = 'always';
  } else {
    // 申込みの最終確認の画面に、毎月の自動更新と解約の方法を出す（特定商取引法 第12条の6）
    params.custom_text = { submit: { message:
      `月額制です。解約するまで毎月自動で更新され、同じ金額が請求されます。解約は会員ページの「支払い・解約」からいつでもでき、次の更新日以降は請求されません。詳しくは[特定商取引法に基づく表記](${site}/tokushoho/)をご覧ください。` } };
  }
  if (env.TERMS_URL) {
    params.consent_collection = { terms_of_service: 'required' };
    params.custom_text = { ...(params.custom_text || {}),
      terms_of_service_acceptance: { message: `[利用規約](${env.TERMS_URL})に同意します。` } };
  }
  const session = await stripe(env, 'POST', '/checkout/sessions', params);
  return json(env, { url: session.url });
}

// 支払いを終えて戻ってきた人を、その場でログイン済みにする（メールを待たせない）
async function claim(env, request) {
  const body = await request.json().catch(() => ({}));
  if (!/^cs_[A-Za-z0-9_]+$/.test(body.session_id || '')) return json(env, { error: 'bad_request' }, 400);
  const session = await stripe(env, 'GET', `/checkout/sessions/${body.session_id}`);
  // 決済ページを作ってから1日以内のものだけ（古い URL の使い回しを防ぐ）
  if (session.status !== 'complete' || session.payment_status === 'unpaid' || now() - session.created > 86400) {
    return json(env, { error: 'not_paid' }, 403);
  }
  const hash = await applyCheckout(env, session);
  if (!hash) return json(env, { error: 'not_paid' }, 403);
  return json(env, { ok: true }, 200, { 'Set-Cookie': await startSession(env, hash) });
}

// 決済の完了を会員の状態に反映する。Webhook と claim の両方から呼ぶ（何回呼んでも同じ結果）
async function applyCheckout(env, session) {
  const email = normalizeEmail(session.customer_details && session.customer_details.email);
  if (!email || !session.customer) return null;
  const hash = await sha256(email);
  if (session.mode === 'payment') {
    const bundle = session.metadata && session.metadata.bundle;
    if (session.payment_status === 'paid' && bundle) {
      const member = await readMember(env, hash);
      if (!member.singles.includes(bundle)) member.singles.push(bundle);
      await kvPut(env, `member:${hash}`, member);
    }
    await env.MEMBERS.put(`customer:${session.customer}`, hash);
    return hash;
  }
  return syncCustomer(env, session.customer, hash);
}

async function webhook(env, request) {
  const payload = await request.text();
  const ok = await verifyStripeSignature(payload, request.headers.get('Stripe-Signature'), env.STRIPE_WEBHOOK_SECRET);
  if (!ok) return new Response('bad signature', { status: 400 });
  const event = JSON.parse(payload);
  if (await env.MEMBERS.get(`event:${event.id}`)) return new Response('ok (duplicate)');
  const object = event.data.object;
  if (event.type === 'checkout.session.completed' || event.type === 'checkout.session.async_payment_succeeded') {
    await applyCheckout(env, object);
  } else if (event.type.startsWith('customer.subscription.') || event.type === 'invoice.payment_failed'
             || event.type === 'invoice.paid' || event.type === 'invoice.payment_succeeded') {
    if (object.customer) await syncCustomer(env, object.customer);
  }
  // 処理が終わってから「済み」と記録する（途中で失敗したら Stripe が送り直す）
  await env.MEMBERS.put(`event:${event.id}`, '1', { expirationTtl: EVENT_TTL });
  return new Response('ok');
}

// ログイン用のリンクをメールで送る。会員でなくても同じ返事を返す（誰が会員かを外から調べられないように）
async function login(env, request) {
  const body = await request.json().catch(() => ({}));
  const email = normalizeEmail(body.email);
  const same = json(env, { ok: true });
  if (!email) return json(env, { error: 'bad_email' }, 400);
  const hash = await sha256(email);
  const member = await kvGet(env, `member:${hash}`);
  if (!member) return same;                                        // 会員でない：何も書かず、何も送らない
  const access = entitlement(member);
  const known = access.all || access.singles.length > 0 || Object.keys(member.customers).length > 0;
  if (!known) return same;
  if (await env.MEMBERS.get(`ratelimit:${hash}`)) return same;      // 送ったばかり
  const token = randomToken();
  await env.MEMBERS.put(`ratelimit:${hash}`, '1', { expirationTtl: RATE_TTL });
  await env.MEMBERS.put(`token:${await sha256(token)}`, hash, { expirationTtl: TOKEN_TTL });
  // リンクの行き先はサイト。ページのスクリプトが番号を POST して初めて使われる
  // （メールの安全確認がリンクを先に開いても、番号は消費されない）
  await sendLoginMail(env, email, `${env.SITE_URL.replace(/\/$/, '')}/members/?login=${token}`);
  return same;
}

async function session(env, request) {
  const body = await request.json().catch(() => ({}));
  if (!/^[0-9a-f]{64}$/.test(body.token || '')) return json(env, { error: 'invalid' }, 400);
  const key = `token:${await sha256(body.token)}`;
  const hash = await env.MEMBERS.get(key);
  if (!hash) return json(env, { error: 'invalid' }, 403);            // 使用済み・期限切れ・でたらめ
  await env.MEMBERS.delete(key);
  return json(env, { ok: true }, 200, { 'Set-Cookie': await startSession(env, hash) });
}

// 鍵の表を返す。ここが「会員かどうかの確認」
async function keys(env, request) {
  const hash = await sessionHash(env, request);
  if (!hash) return json(env, { error: 'signed_out' }, 401);
  let member = await readMember(env, hash);
  const stale = now() - (member.checked || 0) > STALE_AFTER
    || Object.values(member.customers).some((c) => ACTIVE.includes(c.status) && c.period_end && c.period_end < now());
  if (stale) {
    // Webhook が届いていなくても、古い状態のまま鍵を渡さない
    try {
      for (const customerId of Object.keys(member.customers)) await syncCustomer(env, customerId, hash);
      member = await readMember(env, hash);
    } catch (e) {
      if (now() - (member.checked || 0) > 3 * 24 * 60 * 60) return json(env, { error: 'unavailable' }, 503);
    }
  }
  const access = entitlement(member);
  const table = await keyTable(env);
  const result = {};
  for (const [id, key] of Object.entries(table)) {
    if (access.all || access.singles.includes(id)) result[id] = key;
  }
  const states = Object.values(member.customers);
  const current = states.find((c) => ACTIVE.includes(c.status)) || states[0] || null;
  const status = { member: access.all, state: current ? current.status : 'none',
    period_end: current ? current.period_end : null, cancels: current ? !!current.cancel_at_period_end : false };
  if (Object.keys(result).length === 0) return json(env, { error: 'inactive', status }, 403);
  return json(env, { keys: result, status });
}

async function portal(env, request) {
  const hash = await sessionHash(env, request);
  if (!hash) return json(env, { error: 'signed_out' }, 401);
  const member = await readMember(env, hash);
  const ids = Object.keys(member.customers);
  const customerId = ids.find((id) => ACTIVE.includes(member.customers[id].status))
    || ids.find((id) => member.customers[id].status !== 'none') || ids[0];
  if (!customerId) return json(env, { error: 'no_customer' }, 404);
  const created = await stripe(env, 'POST', '/billing_portal/sessions',
    { customer: customerId, return_url: `${env.SITE_URL.replace(/\/$/, '')}/members/` });
  return json(env, { url: created.url });
}

async function logout(env, request) {
  const token = readCookie(request);
  if (token && /^[0-9a-f]{64}$/.test(token)) await env.MEMBERS.delete(`session:${await sha256(token)}`);
  return json(env, { ok: true }, 200, { 'Set-Cookie': cookie(env, '', 0) });
}

const ROUTES = {
  'POST /checkout': checkout,
  'POST /claim': claim,
  'POST /login': login,
  'POST /session': session,
  'GET /keys': keys,
  'POST /portal': portal,
  'POST /logout': logout,
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (request.method === 'POST' && url.pathname === '/webhook') return await webhook(env, request);
      if (request.method === 'OPTIONS') {
        return new Response(null, { status: 204, headers: {
          'Access-Control-Allow-Origin': siteOrigin(env), 'Access-Control-Allow-Credentials': 'true',
          'Access-Control-Allow-Methods': 'GET, POST, OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type',
          'Access-Control-Max-Age': '86400', 'Vary': 'Origin' } });
      }
      const handler = ROUTES[`${request.method} ${url.pathname}`];
      if (!handler) return json(env, { error: 'not_found' }, 404);
      // 状態を変える要求は、サイトのページから来たものだけ受け付ける
      if (request.method === 'POST' && request.headers.get('Origin') !== siteOrigin(env)) {
        return json(env, { error: 'forbidden' }, 403);
      }
      return await handler(env, request);
    } catch (error) {
      console.error(`${request.method} ${url.pathname}: ${error && error.message}`);   // 秘密の値やメールアドレスは書かない
      if (url.pathname === '/webhook') return new Response('error', { status: 500 });   // Stripe が送り直す
      return json(env, { error: 'server_error' }, 500);
    }
  },
};
