/* 顔文字はこのファイルにまとめてある。差し替えるときは FACES の中だけを書き換える。

   入れる場所（ここ以外には出さない）:
     correct … 練習形式と「今日の1問」で正解したとき（毎回ランダムに1つ）
     wrong   … 同じく不正解のとき
     daily   … トップの「今日の1問」の見出し
     hint    … 練習形式のヒントのボタン
     done    … サンプル模試の採点結果
     lead    … トップの説明文の最後
   入れない場所: 問題文、選択肢、解説、トレース表、本番形式、会員ページ（会員ページではこのファイルを読み込まない）。

   文字の選び方: 今の顔文字は、すべて日本語の基本的な文字（JIS の範囲）だけで作ってある。
   日本語が表示できる端末なら欠けない。タイ文字・アラビア文字・結合記号を含む顔文字
   （例 (๑˃̵ᴗ˂̵)و ）は、端末によって欠けたり並びが入れ替わったりするので、使うときは実機で確かめる。
   全部で10個前後に保つ。 */
(function () {
  'use strict';

  var FACES = {
    correct: ['(｀･ω･´)ゞ', 'ヽ(´▽｀)ノ', '(*´∀｀*)', '(≧▽≦)'],
    wrong: ['(´・ω・｀)', '(・ω・；)'],
    daily: ['(｀･ω･´)'],
    hint: ['φ(・ω・ )'],
    done: ['＼(＾▽＾)／'],
    lead: ['(・∀・)ノ']
  };

  // 顔文字と一緒に出す言葉。顔文字を使わない場所の文言は、各ファイルに元のまま残してある。
  var WORDS = {
    correct: '正解！',
    wrong: 'おしい…！確かめてみよう',
    done: 'おつかれさま！'
  };

  function pick(kind) {
    var list = FACES[kind] || [];
    return list.length ? list[Math.floor(Math.random() * list.length)] : '';
  }

  // 要素の末尾に顔文字を足す。読み上げソフトには読ませない（aria-hidden）。
  function decorate(el, kind) {
    var face = pick(kind);
    if (!el || !face) return;
    var span = document.createElement('span');
    span.className = 'kaomoji';
    span.setAttribute('aria-hidden', 'true');
    span.textContent = face;
    el.appendChild(span);
  }

  // 「言葉＋顔文字」を要素に入れる（正解・不正解・採点結果）
  function say(el, kind) {
    if (!el) return;
    el.textContent = WORDS[kind] || '';
    decorate(el, kind);
  }

  window.Kaomoji = { pick: pick, decorate: decorate, say: say };

  function init() {
    var marked = document.querySelectorAll('[data-kaomoji]');
    for (var i = 0; i < marked.length; i++) decorate(marked[i], marked[i].getAttribute('data-kaomoji'));
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
