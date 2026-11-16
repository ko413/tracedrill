/* 学習記録（ログイン不要。この端末のブラウザの中にだけ保存する。サーバーには送らない）

   保存するもの：問題の識別子（例 "stack-basic-001/02"）、結果（ok＝正解 / ng＝要復習）、解いた日時。それだけ。
   問題文・選んだ答え・合言葉などは保存しない。
   保存できない環境（プライベートブラウズ、保存を禁止する設定など）では、何も記録せずに黙って動く。

   使い方（ほかのスクリプトから）:
     Progress.record('stack-basic-001/02', true)   正解なら true、1つでも間違えたら false
     Progress.get(id) → 'ok' / 'ng' / null
     Progress.summary() → {done, ok, ng}
     Progress.review() → 要復習の識別子（並び順は識別子の順）
     Progress.clear()
*/
(function () {
  'use strict';
  var KEY = 'drill-progress';
  var memory = null;          // 保存できない環境では、ページを開いている間だけここに持つ

  function read() {
    if (memory) return memory;
    try {
      var data = JSON.parse(window.localStorage.getItem(KEY) || '{}');
      return data && typeof data === 'object' && !Array.isArray(data) ? data : {};
    } catch (e) { return {}; }
  }

  function write(data) {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(data));
      return true;
    } catch (e) {
      memory = data;          // 保存はできないが、このページの中では印が付く
      return false;
    }
  }

  function valid(id) {
    return typeof id === 'string' && /^[a-z0-9-]+\/[0-9]+$/.test(id);
  }

  // 保存内容が壊れていても落ちないように、結果は必ずここを通して読む
  function result(data, id) {
    var entry = valid(id) ? data[id] : null;
    return entry && (entry.r === 'ok' || entry.r === 'ng') ? entry.r : null;
  }

  var api = {
    // 保存できる環境かどうか（試しに書いて消す）
    available: function () {
      try {
        window.localStorage.setItem(KEY + ':test', '1');
        window.localStorage.removeItem(KEY + ':test');
        return true;
      } catch (e) { return false; }
    },
    record: function (id, correct) {
      if (!valid(id)) return;
      var data = read();
      data[id] = { r: correct ? 'ok' : 'ng', t: Math.floor(Date.now() / 1000) };
      write(data);
    },
    get: function (id) {
      return result(read(), id);
    },
    summary: function () {
      var data = read(), ok = 0, ng = 0;
      Object.keys(data).forEach(function (id) {
        var r = result(data, id);
        if (r === 'ok') ok += 1; else if (r === 'ng') ng += 1;
      });
      return { done: ok + ng, ok: ok, ng: ng };
    },
    // 要復習の問題。prefix（例 "stack-basic-001/"）を渡すと、その題材だけ
    review: function (prefix) {
      var data = read();
      return Object.keys(data).filter(function (id) {
        return result(data, id) === 'ng' && (!prefix || id.indexOf(prefix) === 0);
      }).sort();
    },
    // 題材ごとの数（トップの一覧用）
    count: function (prefix) {
      var data = read(), ok = 0, ng = 0;
      Object.keys(data).forEach(function (id) {
        if (id.indexOf(prefix) !== 0) return;
        var r = result(data, id);
        if (r === 'ok') ok += 1; else if (r === 'ng') ng += 1;
      });
      return { ok: ok, ng: ng };
    },
    clear: function () {
      memory = null;
      try { window.localStorage.removeItem(KEY); } catch (e) { /* もともと保存されていない */ }
    }
  };

  window.Progress = api;
})();
