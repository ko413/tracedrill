/* 会員の確認・B案（Stripe の定期課金＋Cloudflare Workers）。まだ公開していない。

   site.yaml の members.method が "both" か "stripe" のときだけ、会員ページに読み込まれる。
     both   … member.js（合言葉）の後に読み込まれ、両方を使えるようにする（移行の期間）
     stripe … このファイルだけが読み込まれる
   "passphrase"（既定）のときは読み込まれず、今までと何も変わらない。

   mock.js から見た形は member.js と同じ（MemberAuth.keys / login / logout / expired / open）。
   加えて、支払いに関する操作を MemberBilling として出す。
   鍵は Workers が「会員である」と確かめたときだけ返す。この端末には保存しない。 */
(function () {
  'use strict';

  var root = document.querySelector('[data-member-api]');
  var API = root ? root.getAttribute('data-member-api').replace(/\/$/, '') : '';
  if (!API) return;

  var passphrase = window.MemberAuth || null;      // member.js が先に読み込まれていれば、合言葉も使える
  var cache;                                       // undefined＝まだ聞いていない、null＝開けるものがない
  var state = { signedIn: false, member: false, state: 'none', period_end: null, cancels: false };

  function post(path, body) {
    return fetch(API + path, { method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  }

  async function fetchKeys() {
    var response = await fetch(API + '/keys', { credentials: 'include', cache: 'no-store' });
    var body = await response.json().catch(function () { return {}; });
    if (response.status === 401) { state.signedIn = false; return null; }
    if (response.status !== 200 && response.status !== 403) throw new Error('keys');
    state.signedIn = true;
    if (body.status) { state.member = body.status.member; state.state = body.status.state;
      state.period_end = body.status.period_end; state.cancels = body.status.cancels; }
    return response.status === 200 ? body.keys : null;
  }

  async function serverKeys() {
    if (cache === undefined) cache = await fetchKeys();
    return cache;
  }

  function bytes(b64) {
    var bin = atob(b64);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  window.MemberBilling = {
    // ログインしているか、会員か、解約の予約中か。keys() の後で正しい値になる
    status: function () { return state; },

    // 入会（plan を省略）または単品の購入を始める。Stripe の決済ページへ移る
    checkout: async function (plan, bundle) {
      var response = await post('/checkout', { plan: plan || 'member', bundle: bundle });
      if (!response.ok) throw new Error('checkout');
      window.location.href = (await response.json()).url;
    },

    // 支払い方法の変更・解約・領収書（Stripe のページへ移る）
    portal: async function () {
      var response = await post('/portal');
      if (!response.ok) throw new Error('portal');
      window.location.href = (await response.json()).url;
    },

    // ログイン用のリンクをメールで送る。会員でないアドレスでも、返事は同じ
    sendLink: async function (email) {
      var response = await post('/login', { email: email });
      if (response.status === 400) return 'bad_email';
      if (!response.ok) throw new Error('login');
      return 'sent';
    },

    // 決済のあと（?joined=…）や、メールのリンク（?login=…）で戻ってきたときの仕上げ。
    // 戻り値：'joined' / 'login' / 'failed' / null（どちらでもない）
    finish: async function () {
      var params = new URLSearchParams(window.location.search);
      var joined = params.get('joined'), login = params.get('login');
      if (!joined && !login) return null;
      var response = joined ? await post('/claim', { session_id: joined }) : await post('/session', { token: login });
      params.delete('joined'); params.delete('login');
      var rest = params.toString();
      window.history.replaceState(null, '', window.location.pathname + (rest ? '?' + rest : ''));   // 番号を URL に残さない
      cache = undefined;
      if (!response.ok) return 'failed';
      return joined ? 'joined' : 'login';
    }
  };

  window.MemberAuth = {
    method: passphrase ? 'both' : 'email',

    keys: async function () {
      var all = {}, found = false;
      if (passphrase) {
        var mine = await passphrase.keys();
        if (mine) { Object.keys(mine).forEach(function (id) { all[id] = mine[id]; }); found = true; }
      }
      var theirs = null;
      try { theirs = await serverKeys(); } catch (e) { if (!passphrase) throw e; }   // 合言葉の人は、API が止まっていても開ける
      if (theirs) { Object.keys(theirs).forEach(function (id) { all[id] = theirs[id]; }); found = true; }
      return found ? all : null;
    },

    // 入力欄は合言葉用。メールでのログインは MemberBilling.sendLink を使う
    login: async function (input, singleIds) {
      return passphrase ? passphrase.login(input, singleIds) : false;
    },

    logout: function () {
      cache = undefined;
      state.signedIn = false;
      if (passphrase) passphrase.logout();
      return post('/logout').catch(function () { /* 通信できなくても、端末側は消えている */ });
    },

    expired: async function () {
      return passphrase ? passphrase.expired() : false;
    },

    // 鍵（Base64）と暗号化されたファイルから、中身を取り出す。member.js の open と同じ処理
    open: async function (keyB64, box) {
      var key = await crypto.subtle.importKey('raw', bytes(keyB64), { name: 'AES-GCM' }, false, ['decrypt']);
      var plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: bytes(box.iv) }, key, bytes(box.ct));
      return JSON.parse(new TextDecoder().decode(plain));
    }
  };
})();
