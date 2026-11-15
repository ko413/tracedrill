/* 会員の確認（鍵を手に入れる部分）。

   模試の画面（mock.js）がこのファイルに頼むのは、次の3つだけ。
     MemberAuth.keys()               … 模試の名前 → 鍵 の表を返す。何も開けられなければ null
     MemberAuth.login(入力, 候補)    … 入力（今は合言葉）で確認する。成功なら true。
                                        候補は、単品用の合言葉があるかもしれない模試の名前の一覧（なくてもよい）
     MemberAuth.logout()             … 確認した状態を消す
   会員の確認方法を変えるとき（合言葉 → Stripe＋Workers など）は、このファイルだけを差し替える。
   その場合 keys() は、ログイン済みなら Workers から鍵の表を受け取って返せばよい。

   今の方式：合言葉から鍵を作り（PBKDF2）、公開してある鍵束を開く（AES-GCM）。鍵束は2種類ある。
     keyring.json         … 会員用。今月の合言葉で開く。全部の模試の鍵が入っている
     single/<名前>.json   … 単品用。その回の合言葉で開く。その模試の鍵だけが入っている
   合言葉は端末の中にだけ保存し、どこにも送らない。 */
(function () {
  'use strict';

  var STORE_KEY = 'member-passphrase';
  var SINGLE_KEY = 'member-single-passphrases';     // { 模試の名前: 合言葉 }
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

  function savedSingles() {
    try { return JSON.parse(window.localStorage.getItem(SINGLE_KEY)) || {}; } catch (e) { return {}; }
  }

  function saveSingles(map) {
    try {
      if (map === null) window.localStorage.removeItem(SINGLE_KEY);
      else window.localStorage.setItem(SINGLE_KEY, JSON.stringify(map));
    } catch (e) { /* 同上 */ }
  }

  // 鍵束を合言葉で開いて、鍵の表を返す。合言葉が違えば null。file は base() からの場所
  async function openKeyring(passphrase, file) {
    var response = await fetch(base() + file, { cache: 'no-store' });
    if (!response.ok) {
      if (file !== 'keyring.json') return null;      // 単品用の鍵束がない模試は、開けないだけ
      throw new Error('keyring');
    }
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

  function merge(into, keys) {
    Object.keys(keys || {}).forEach(function (id) { into[id] = keys[id]; });
  }

  window.MemberAuth = {
    method: 'passphrase',

    keys: async function () {
      if (cache) return cache;
      var all = {};
      var passphrase = saved();
      if (passphrase) merge(all, await openKeyring(passphrase, 'keyring.json'));
      var singles = savedSingles();
      for (var id of Object.keys(singles)) {
        merge(all, await openKeyring(singles[id], 'single/' + encodeURIComponent(id) + '.json'));
      }
      cache = Object.keys(all).length ? all : null;
      return cache;
    },

    login: async function (input, singleIds) {
      var keys = await openKeyring(input, 'keyring.json');
      if (keys) {
        save(normalize(input));
        cache = null;
        return true;
      }
      for (var id of (singleIds || [])) {
        var one = await openKeyring(input, 'single/' + encodeURIComponent(id) + '.json');
        if (one && one[id]) {
          var singles = savedSingles();
          singles[id] = normalize(input);
          saveSingles(singles);
          cache = null;
          return true;
        }
      }
      return false;
    },

    logout: function () {
      cache = null;
      save(null);
      saveSingles(null);
    },

    // 前に会員として確認できていたのに開けなくなった（＝合言葉が月替わりで変わった）かどうか
    expired: async function () {
      var passphrase = saved();
      return passphrase !== null && (await openKeyring(passphrase, 'keyring.json')) === null;
    }
  };

  // 鍵（Base64）と暗号化されたファイルから、中身（JSON）を取り出す。確認方法が変わっても共通。
  window.MemberAuth.open = async function (keyB64, box) {
    var key = await crypto.subtle.importKey('raw', bytes(keyB64), { name: 'AES-GCM' }, false, ['decrypt']);
    var plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: bytes(box.iv) }, key, bytes(box.ct));
    return JSON.parse(new TextDecoder().decode(plain));
  };
})();
