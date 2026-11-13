/* 会員の確認（鍵を手に入れる部分）。

   模試の画面（mock.js）がこのファイルに頼むのは、次の3つだけ。
     MemberAuth.keys()        … 模試の名前 → 鍵 の表を返す。会員と確認できなければ null
     MemberAuth.login(入力)   … 入力（今は合言葉）で確認する。成功なら true
     MemberAuth.logout()      … 確認した状態を消す
   会員の確認方法を変えるとき（合言葉 → Stripe＋Workers など）は、このファイルだけを差し替える。
   その場合 keys() は、ログイン済みなら Workers から鍵の表を受け取って返せばよい。

   今の方式：合言葉から鍵を作り（PBKDF2）、公開してある鍵束 keyring.json を開く（AES-GCM）。
   合言葉は端末の中にだけ保存し、どこにも送らない。 */
(function () {
  'use strict';

  var STORE_KEY = 'member-passphrase';
  var cache = null;

  function base() {
    var el = document.querySelector('[data-members-base]');
    return el ? el.getAttribute('data-members-base') : '/members/';
  }

  function bytes(b64) {
    var bin = atob(b64);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  // 全角・小文字・ハイフン・空白のゆれを吸収する（tools/members.py と同じ規則）
  function normalize(text) {
    return String(text).normalize('NFKC').toUpperCase().replace(/[^\p{L}\p{N}]/gu, '');
  }

  function saved() {
    try { return window.localStorage.getItem(STORE_KEY); } catch (e) { return null; }
  }

  function save(value) {
    try {
      if (value === null) window.localStorage.removeItem(STORE_KEY);
      else window.localStorage.setItem(STORE_KEY, value);
    } catch (e) { /* 保存できなくても、このページを開いている間は使える */ }
  }

  async function openKeyring(passphrase) {
    var response = await fetch(base() + 'keyring.json', { cache: 'no-store' });
    if (!response.ok) throw new Error('keyring');
    var ring = await response.json();
    var material = await crypto.subtle.importKey(
      'raw', new TextEncoder().encode(normalize(passphrase)), 'PBKDF2', false, ['deriveKey']);
    var key = await crypto.subtle.deriveKey(
      { name: 'PBKDF2', hash: 'SHA-256', salt: bytes(ring.salt), iterations: ring.iter },
      material, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
    var plain;
    try {
      plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: bytes(ring.iv) }, key, bytes(ring.ct));
    } catch (e) {
      return null;                       // 合言葉が違う（または先月のもの）
    }
    return JSON.parse(new TextDecoder().decode(plain)).keys;
  }

  window.MemberAuth = {
    method: 'passphrase',

    keys: async function () {
      if (cache) return cache;
      var passphrase = saved();
      if (!passphrase) return null;
      cache = await openKeyring(passphrase);
      return cache;
    },

    login: async function (input) {
      cache = await openKeyring(input);
      if (!cache) return false;
      save(normalize(input));
      return true;
    },

    logout: function () {
      cache = null;
      save(null);
    },

    // 前に確認できていたのに開けなくなった（＝合言葉が月替わりで変わった）かどうか
    expired: async function () {
      return saved() !== null && (await this.keys()) === null;
    }
  };

  // 鍵（Base64）と暗号化されたファイルから、中身（JSON）を取り出す。確認方法が変わっても共通。
  window.MemberAuth.open = async function (keyB64, box) {
    var key = await crypto.subtle.importKey('raw', bytes(keyB64), { name: 'AES-GCM' }, false, ['decrypt']);
    var plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: bytes(box.iv) }, key, bytes(box.ct));
    return JSON.parse(new TextDecoder().decode(plain));
  };
})();
