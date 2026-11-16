// 全ページ共通：横にはみ出す表に「横にスクロールできます」の案内を付ける。
// 問題ページ：練習モード（設問を順に解く）と本番形式（1問）の切替え、答え合わせ、トレース表の強調。
// 外部のライブラリは使っていない。問題のデータはページ内の <script id="quiz-data"> にある。
(function () {
  'use strict';

  // 組合せ表（空欄が2つある問題）：行のどこを押しても、その行の選択肢を選ぶ。
  // 丸やラベルを直接押したときはブラウザに任せる（キーボードの Tab・矢印・Space もそのまま）。
  function pickComboRow(event) {
    if (event.comboRowDone || !event.target || !event.target.closest) return;
    var row = event.target.closest('.combo tbody tr');
    if (!row || event.target.closest('input, label, a')) return;
    var input = row.querySelector('input[type="radio"]');
    if (!input || input.disabled) return;
    event.comboRowDone = true;                  // 同じクリックを2回処理しない（mock.js と app.js の両方にあるため）
    if (!input.checked) {
      input.checked = true;
      input.dispatchEvent(new Event('change', { bubbles: true }));     // 解答の保存や「解答する」ボタンの有効化を動かす
    }
    input.focus({ preventScroll: true });
  }
  document.addEventListener('click', pickComboRow);


  // 正解・不正解の表示。friendly のときだけ、やわらかい言葉と顔文字にする（文言と顔文字は kaomoji.js）。
  function verdict(el, ok, friendly) {
    if (friendly && window.Kaomoji) window.Kaomoji.say(el, ok ? 'correct' : 'wrong');
    else el.textContent = ok ? '正解です。' : '不正解です。';
  }


  function all(selector, scope) {
    return Array.prototype.slice.call((scope || document).querySelectorAll(selector));
  }

  // ---- 横スクロールの案内 ----
  function markScrollable() {
    all('.scroll-x').forEach(function (box) {
      var hint = box.previousElementSibling;
      var has = hint && hint.classList.contains('scroll-hint');
      var needs = box.scrollWidth > box.clientWidth + 4;
      if (needs && !has) {
        hint = document.createElement('p');
        hint.className = 'scroll-hint';
        hint.textContent = '← 横にスクロールできます →';
        box.parentNode.insertBefore(hint, box);
      } else if (!needs && has) {
        hint.parentNode.removeChild(hint);
      }
    });
  }
  markScrollable();
  window.addEventListener('resize', markScrollable);

  // ---- トップページ：今日の1問 ----

  // ---- 行の印：プログラムの行を押すと背景色が変わる（もう一度押すと戻る）。トレース中の「今ここ」の目印 ----
  // 練習形式・本番形式・模試のどれでも使える。保存はしない（ページを開いている間だけ）。
  function toggleMark(row) {
    var on = !row.classList.contains('marked');
    row.classList.toggle('marked', on);
    if (on) row.setAttribute('aria-current', 'true'); else row.removeAttribute('aria-current');
  }

  function programRow(target) {
    var row = target && target.closest ? target.closest('.program .giji-code tr') : null;
    return row && !row.closest('.program-review') ? row : null;
  }

  // キーボード用：プログラムごとに Tab で1回だけ止まり、↑↓で行を移る。Enter か Space で印を付け外しする
  function setupLines(scope) {
    all('.program .giji-code', scope || document).forEach(function (table) {
      if (table.getAttribute('data-lines-ready')) return;
      table.setAttribute('data-lines-ready', '1');
      var rows = all('tr', table);
      rows.forEach(function (row, index) { row.setAttribute('tabindex', index === 0 ? '0' : '-1'); });
    });
  }

  document.addEventListener('click', function (event) {
    var row = programRow(event.target);
    if (!row) return;
    if (String(window.getSelection ? window.getSelection() : '') !== '') return;     // 文字を選んでいる最中は何もしない
    toggleMark(row);
  });

  document.addEventListener('keydown', function (event) {
    var row = programRow(event.target);
    if (!row || event.target !== row) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggleMark(row);
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      var next = event.key === 'ArrowDown' ? row.nextElementSibling : row.previousElementSibling;
      if (!next) return;
      event.preventDefault();
      row.setAttribute('tabindex', '-1');
      next.setAttribute('tabindex', '0');
      next.focus();
    }
  });

  setupLines(document);
  window.LineMarks = { setup: setupLines };

  // ---- 共有：X の投稿画面を開くリンクを作る（本人が押したときだけ開く。自動では投稿しない） ----
  function shareLink(text, url) {
    var link = document.createElement('a');
    link.className = 'chip share-x';
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.href = 'https://twitter.com/intent/tweet?text=' + encodeURIComponent(text) +
      '&url=' + encodeURIComponent(url) + '&hashtags=' + encodeURIComponent('基本情報技術者試験');
    link.textContent = '結果を X に投稿する';
    return link;
  }
  window.ShareX = { link: shareLink };

  // ---- 学習記録の表示（一覧の印、解いた数、要復習だけ解く、記録を消す） ----
  var siteBase = (function () {
    var brand = document.querySelector('.site-header .brand');
    return ((brand && brand.getAttribute('href')) || '/').replace(/\/$/, '');
  })();
  var MARKS = { ok: '正解', ng: '要復習', none: '未着手' };

  function problemPath(id, review) {
    return siteBase + '/q/' + id + '/' + (review ? '?review=' + encodeURIComponent(review) : '');
  }

  function markNode(state) {
    var node = document.createElement('span');
    node.className = 'progress-mark progress-' + state;
    node.textContent = MARKS[state];
    return node;
  }

  function paintProgress() {
    var P = window.Progress;
    if (!P) return;
    all('.progress-mark, .progress-count').forEach(function (node) { node.parentNode.removeChild(node); });
    // 解説ページの問題リスト：問題ごとに印
    all('.problem-list a').forEach(function (link) {
      var found = /\/q\/([a-z0-9-]+\/[0-9]+)\/?$/.exec(link.getAttribute('href') || '');
      if (!found) return;
      link.parentNode.insertBefore(markNode(P.get(found[1]) || 'none'), link.nextSibling);
    });
    // トップの一覧：題材ごとに数
    all('[data-progress-set]').forEach(function (item) {
      var count = P.count(item.getAttribute('data-progress-set') + '/');
      var node = document.createElement('em');
      node.className = 'progress-count';
      node.textContent = count.ok + count.ng === 0 ? '未着手'
        : '正解 ' + count.ok + '問' + (count.ng ? '・要復習 ' + count.ng + '問' : '');
      if (count.ng) node.classList.add('has-review');
      (item.querySelector('a') || item).appendChild(node);
    });
    // 解いた数の表示
    var box = document.getElementById('progress-box');
    if (!box) return;
    var scope = (box.getAttribute('data-progress-scope') || '').split(/\s+/).filter(Boolean);
    var total = P.summary();
    var review = scope.length ? scope.reduce(function (list, prefix) { return list.concat(P.review(prefix)); }, []) : P.review();
    box.textContent = '';
    if (total.done === 0) { box.hidden = true; return; }
    box.hidden = false;
    var line = document.createElement('p');
    line.textContent = '学習記録（この端末）：解いた問題 ' + total.done + '問／正解 ' + total.ok + '問／要復習 ' + total.ng + '問';
    box.appendChild(line);
    var actions = document.createElement('p');
    if (review.length) {
      var go = document.createElement('a');
      go.className = 'chip';
      go.href = problemPath(review[0], scope.length ? scope.map(function (x) { return x.replace(/\/$/, ''); }).join(',') : 'all');
      go.textContent = (scope.length ? 'この題材の要復習だけ解く（' : '要復習の問題だけ解く（') + review.length + '問）';
      actions.appendChild(go);
      actions.appendChild(document.createTextNode(' '));
    }
    var clear = document.createElement('button');
    clear.type = 'button';
    clear.className = 'chip';
    clear.textContent = '記録を消す';
    clear.addEventListener('click', function () {
      if (clear.getAttribute('data-armed')) { P.clear(); paintProgress(); return; }
      clear.setAttribute('data-armed', '1');                       // 2回押して初めて消す（押し間違い防止）
      clear.textContent = 'もう一度押すと、すべての記録を消します';
      var cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'chip';
      cancel.textContent = 'やめる';
      cancel.addEventListener('click', paintProgress);
      actions.appendChild(document.createTextNode(' '));
      actions.appendChild(cancel);
    });
    actions.appendChild(clear);
    box.appendChild(actions);
  }

  paintProgress();
  window.addEventListener('pageshow', function (event) { if (event.persisted) paintProgress(); });   // 「戻る」で一覧に戻ったとき

  // ---- トレース表の「1ステップずつ表示」：次へ・前へ・すべて表示 ----
  // 表の中身（HTML）はそのままで、先の行を隠すだけ。今のステップの行と、プログラムの対応する行に印を付ける。
  function setupStepper(wrap, code) {
    var table = wrap && wrap.querySelector('.giji-trace');
    if (!table || wrap.getAttribute('data-stepper')) return;
    var rows = all('tbody tr', table);
    if (rows.length < 2) return;
    wrap.setAttribute('data-stepper', '1');
    var on = false, at = 1;

    function button(text) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'chip';
      b.textContent = text;
      return b;
    }
    var start = button('1ステップずつ表示');
    var prev = button('← 前へ'), next = button('次へ →'), showAll = button('すべて表示');
    var label = document.createElement('span');
    label.className = 'step-label';
    label.setAttribute('aria-live', 'polite');
    var bar = document.createElement('p');
    bar.className = 'step-controls';
    [start, prev, label, next, showAll].forEach(function (node) { bar.appendChild(node); });
    wrap.parentNode.insertBefore(bar, wrap);

    function render() {
      all('tr.step-now', table).forEach(function (row) { row.classList.remove('step-now'); });
      if (code) all('tr.step-line', code).forEach(function (row) { row.classList.remove('step-line'); });
      start.hidden = on;
      prev.hidden = next.hidden = showAll.hidden = label.hidden = !on;
      rows.forEach(function (row, index) { row.hidden = on && index >= at; });
      if (!on) return;
      var current = rows[at - 1];
      current.classList.add('step-now');
      var line = current.getAttribute('data-line');
      if (code && line) {
        all('tr[data-line="' + line + '"]', code).forEach(function (row) { row.classList.add('step-line'); });
      }
      label.textContent = 'ステップ ' + at + ' / ' + rows.length + (line ? '（' + line + ' 行目）' : '');
      prev.disabled = at <= 1;
      next.disabled = at >= rows.length;
      // 表の中だけをスクロールして、今の行を見える位置にする（ページ全体は動かさない）
      var top = current.offsetTop - table.tHead.offsetHeight;
      if (top < wrap.scrollTop || current.offsetTop + current.offsetHeight > wrap.scrollTop + wrap.clientHeight) {
        wrap.scrollTop = Math.max(0, current.offsetTop + current.offsetHeight - wrap.clientHeight + 4);
      }
    }

    function go(step) { at = Math.min(rows.length, Math.max(1, step)); render(); }
    start.addEventListener('click', function () { on = true; at = 1; render(); next.focus(); });
    prev.addEventListener('click', function () { go(at - 1); if (prev.disabled) next.focus(); });
    next.addEventListener('click', function () { go(at + 1); if (next.disabled) showAll.focus(); });
    showAll.addEventListener('click', function () { on = false; render(); start.focus(); });
    bar.addEventListener('keydown', function (event) {            // ボタンにフォーカスがある間は、← → でも進められる
      if (!on) return;
      if (event.key === 'ArrowRight') { event.preventDefault(); go(at + 1); }
      if (event.key === 'ArrowLeft') { event.preventDefault(); go(at - 1); }
    });
    render();
    markScrollable();
  }

  // 解説ページの例題のトレース表（ヒントの表には付けない）
  (function () {
    var heading = document.getElementById('example');
    if (!heading) return;
    var wrap = heading.parentNode.querySelector('#example ~ .giji-trace-wrap');
    var program = document.getElementById('program');
    var code = program ? program.parentNode.querySelector('#program ~ .giji-code, #program ~ * .giji-code') : null;
    if (wrap) setupStepper(wrap, code);
  })();

  // 表示していた時間だけを計る時計（タブを切り替えている間は止める）
  function stopwatch() {
    var total = 0, since = null, running = false;
    function resume() { if (running && since === null && !document.hidden) since = Date.now(); }
    function hold() { if (since !== null) { total += Date.now() - since; since = null; } }
    document.addEventListener('visibilitychange', function () { if (document.hidden) hold(); else resume(); });
    return {
      start: function () { running = true; resume(); },
      pause: function () { hold(); running = false; },
      seconds: function () { return Math.round((total + (since !== null ? Date.now() - since : 0)) / 1000); }
    };
  }

  function clockText(seconds) {
    var m = Math.floor(seconds / 60), sec = seconds % 60;
    return (m ? m + '分' : '') + (m && sec < 10 ? '0' : '') + sec + '秒';
  }

  // 日付（日本時間）で決まる1問を出す。同じ日は誰が見ても同じ問題になる。
  (function () {
    var dailyData = document.getElementById('daily-data');
    var body = document.getElementById('daily-body');
    if (!dailyData || !body) return;
    var items = JSON.parse(dailyData.textContent);
    if (!items.length) return;
    var base = (document.querySelector('.site-header .brand').getAttribute('href') || '/').replace(/\/$/, '');
    var now = new Date(Date.now() + 9 * 3600 * 1000);
    var today = Math.floor(now.getTime() / 86400000);
    var offset = 0;

    function esc(text) {
      return String(text).replace(/[&<>"]/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
      });
    }

    function show(item) {
      var choices = item.choices.map(function (c) {
        return '<label><input type="radio" name="daily" value="' + esc(c.label) + '"> <b>' + esc(c.label) +
               '</b>　<span>' + esc(c.text) + '</span></label>';
      }).join('');
      var explain = item.explain.map(function (line) { return '<li>' + esc(line) + '</li>'; }).join('');
      body.className = 'question';
      body.innerHTML =
        '<p class="daily-meta"><span class="badge">' + esc(item.level) + '</span> ' + esc(item.title) + '</p>' +
        '<p class="daily-call">次のプログラムを <code>' + esc(item.call) + '</code> で呼び出す。</p>' +
        item.source_html +
        '<p class="prompt">' + esc(item.prompt) + '</p>' +
        '<div class="daily-choices">' + choices + '</div>' +
        '<button type="button" class="button answer-button" disabled>解答する</button>' +
        '<div class="result after-answer" aria-live="polite"><p class="verdict"></p>' +
        '<p><strong>正解：' + esc(item.answer) + '　' + esc(item.answer_text) + '</strong></p><ul>' + explain + '</ul>' +
        '<p class="daily-next"><a class="button" href="' + esc(base + item.path) + '">トレース表で確かめる</a> ' +
        '<button type="button" class="chip" id="daily-another">別の問題を解く</button></p></div>';
      if (item.line) {
        all('.giji-code tr[data-line="' + item.line + '"]', body).forEach(function (el) { el.classList.add('focus'); });
      }
      var button = body.querySelector('.answer-button');
      all('input[type="radio"]', body).forEach(function (radio) {
        radio.addEventListener('change', function () { button.disabled = false; });
      });
      button.addEventListener('click', function () {
        var chosen = body.querySelector('input[type="radio"]:checked');
        if (!chosen) return;
        var ok = chosen.value === item.answer;
        body.classList.add('answered', ok ? 'is-correct' : 'is-wrong');
        verdict(body.querySelector('.verdict'), ok, true);
        all('input[type="radio"]', body).forEach(function (radio) {
          radio.disabled = true;
          if (radio.value === item.answer) radio.parentNode.classList.add('is-answer');
          else if (radio.checked) radio.parentNode.classList.add('is-chosen-wrong');
        });
        button.hidden = true;
      });
      body.querySelector('#daily-another').addEventListener('click', function () {
        offset += 1;
        show(items[(today + offset) % items.length]);
        document.getElementById('daily-label').textContent = 'もう1問';
        if (window.Kaomoji) window.Kaomoji.decorate(document.getElementById('daily-label'), 'daily');
        markScrollable();
      });
      markScrollable();
    }

    // 見出しの文字を入れ直すので、顔文字もここで付け直す（kaomoji.js が先に付けた分は上書きされる）
    document.getElementById('daily-label').textContent =
      '今日の1問（' + (now.getUTCMonth() + 1) + '/' + now.getUTCDate() + '）';
    if (window.Kaomoji) window.Kaomoji.decorate(document.getElementById('daily-label'), 'daily');
    show(items[today % items.length]);
  })();

  // ---- 問題ページ ----
  var dataEl = document.getElementById('quiz-data');
  var root = document.getElementById('problem');
  if (!dataEl || !root) return;
  var quiz = JSON.parse(dataEl.textContent);
  var practice = all('.question[data-kind="practice"]', root);
  var examSection = root.querySelector('.question[data-kind="exam"]');
  var chips = all('.focus-buttons .chip', root);
  var correct = 0;
  var problemId = root.getAttribute('data-problem-id') || '';
  var topic = root.getAttribute('data-topic') || '';
  var pageUrl = (document.querySelector('link[rel="canonical"]') || {}).href || window.location.href.split('?')[0];

  root.classList.add('js');

  // ---- 要復習だけを続けて解く（?review=all、または ?review=題材の識別子） ----
  var reviewScope = new URLSearchParams(window.location.search).get('review');
  var reviewBar = document.getElementById('review-bar');

  function reviewList() {
    if (!reviewScope || !window.Progress) return [];
    if (reviewScope === 'all') return window.Progress.review();
    return reviewScope.split(',').reduce(function (list, set) {
      return /^[a-z0-9-]+$/.test(set) ? list.concat(window.Progress.review(set + '/')) : list;
    }, []);
  }

  function showReviewBar(finished) {
    if (!reviewScope || !reviewBar) return;
    var rest = reviewList().filter(function (id) { return id !== problemId; });
    reviewBar.hidden = false;
    reviewBar.textContent = '';
    var text = document.createElement('span');
    text.textContent = '要復習の問題だけを解いています。' + (finished
      ? (rest.length ? 'この問題のほかに、あと ' + rest.length + '問。' : '要復習の問題は、これで最後です。')
      : 'この問題のほかに、あと ' + rest.length + '問。');
    reviewBar.appendChild(text);
    if (finished && rest.length) {
      // 識別子の順で、今の問題の次（なければ先頭）へ
      var after = rest.filter(function (id) { return id > problemId; });
      var link = document.createElement('a');
      link.className = 'button';
      link.href = problemPath(after[0] || rest[0], reviewScope);
      link.textContent = '次の要復習の問題 →';
      reviewBar.appendChild(document.createTextNode(' '));
      reviewBar.appendChild(link);
    }
    var stop = document.createElement('a');
    stop.className = 'chip';
    stop.href = window.location.pathname;
    stop.textContent = 'やめる';
    reviewBar.appendChild(document.createTextNode(' '));
    reviewBar.appendChild(stop);
  }

  // 解き終えたとき：学習記録に書き、共有ボタンを出す（押したときだけ X の投稿画面が開く）
  function finished(allCorrect, shareText) {
    if (window.Progress && problemId) window.Progress.record(problemId, allCorrect);
    var row = document.getElementById('share-row');
    if (row) {
      row.textContent = '';
      row.appendChild(shareLink(shareText, pageUrl));
      row.hidden = false;
    }
    if (reviewScope) {
      showReviewBar(true);
      reviewBar.scrollIntoView({ block: 'nearest' });
    }
  }

  showReviewBar(false);

  // 問題を開いてから答え終えるまでの時間（形式ごとに別々に計る。答え終えたあとにだけ表示する。保存はしない）
  var watches = { practice: stopwatch(), exam: stopwatch() };
  var timed = { practice: false, exam: false };

  // 解説のトレース表を、1ステップずつ表示できるようにする
  setupStepper(root.querySelector('.review .giji-trace-wrap'), root.querySelector('.program-review .giji-code'));

  function clearFocus() {
    all('.giji-code tr.focus', root).forEach(function (el) { el.classList.remove('focus'); });
    ['focus-line', 'focus-pass', 'focus-col'].forEach(function (name) {
      all('.giji-trace .' + name, root).forEach(function (el) { el.classList.remove(name); });
    });
  }

  // 設問が指す行・回・変数に色を付ける。withTrace が偽なら、解いている最中のプログラムの行だけ。
  function applyFocus(q, withTrace) {
    clearFocus();
    if (!q || !q.line) return;
    var codeScope = withTrace ? '.program-review' : '#mode-practice .program';
    if (withTrace || q.showLineBefore) {
      all(codeScope + ' tr[data-line="' + q.line + '"]', root).forEach(function (el) { el.classList.add('focus'); });
    }
    if (!withTrace) return;
    all('.giji-trace tr[data-line="' + q.line + '"]', root).forEach(function (el) { el.classList.add('focus-line'); });
    if (q.step) {
      all('.giji-trace tr[data-step="' + q.step + '"]', root).forEach(function (el) {
        el.classList.remove('focus-line');
        el.classList.add('focus-pass');
      });
    }
    if (q.variable) {
      all('.giji-trace [data-var="' + q.variable + '"]', root).forEach(function (el) { el.classList.add('focus-col'); });
    }
  }

  function pressChip(index) {
    chips.forEach(function (chip, i) { chip.setAttribute('aria-pressed', i === index ? 'true' : 'false'); });
    applyFocus(quiz.practice[index], true);
  }

  // 答え合わせの共通部分。正解なら true を返す。friendly は練習形式だけ true（本番形式は顔文字なし）。
  function grade(section, answer, friendly) {
    var chosen = section.querySelector('input[type="radio"]:checked');
    if (!chosen) return null;
    var ok = chosen.value === answer;
    section.classList.add('answered', ok ? 'is-correct' : 'is-wrong');
    verdict(section.querySelector('.verdict'), ok, friendly);
    all('input[type="radio"]', section).forEach(function (radio) {
      radio.disabled = true;
      var row = radio.closest('tr') || radio.parentNode;
      if (radio.value === answer) row.classList.add('is-answer');
      else if (radio.checked) row.classList.add('is-chosen-wrong');
    });
    section.querySelector('.answer-button').hidden = true;
    return ok;
  }

  function enableButton(section) {
    var button = section.querySelector('.answer-button');
    all('input[type="radio"]', section).forEach(function (radio) {
      radio.addEventListener('change', function () { button.disabled = false; });
    });
    return button;
  }

  practice.forEach(function (section, index) {
    var q = quiz.practice[index];
    enableButton(section).addEventListener('click', function () {
      var ok = grade(section, q.answer, true);
      if (ok === null) return;
      if (ok) correct += 1;

      // 空欄補充に答えたら、空欄をその場で正解に置き換える（プログラムの高さは変わらない）
      if (q.type === 'fill_blank') {
        all('#mode-practice .program .blank', root).forEach(function (el) {
          el.textContent = q.answerText;
          el.classList.add('filled');
        });
      }

      var next = practice[index + 1];
      if (next) {
        next.classList.remove('locked');
        applyFocus(quiz.practice[index + 1], false);
      } else {
        root.classList.add('all-done');
        watches.practice.pause();
        timed.practice = true;
        root.querySelector('.score').textContent = practice.length + '問中 ' + correct + '問正解でした。' +
          '（かかった時間：' + clockText(watches.practice.seconds()) + '）';
        pressChip(practice.length - 1);
        finished(correct === practice.length,
          '「' + topic + '」の擬似言語トレース練習問題を解きました（' + practice.length + '問中' + correct + '問正解）');
      }
      markScrollable();
    });
  });

  chips.forEach(function (chip, index) {
    chip.addEventListener('click', function () { pressChip(index); });
  });

  if (examSection && quiz.exam) {
    enableButton(examSection).addEventListener('click', function () {
      var examOk = grade(examSection, quiz.exam.answer, false);
      if (examOk === null) return;
      root.classList.add('exam-done');
      watches.exam.pause();
      timed.exam = true;
      var timeNote = document.createElement('p');
      timeNote.className = 'note time-note';
      timeNote.textContent = '解答までの時間：' + clockText(watches.exam.seconds());
      examSection.querySelector('.result').appendChild(timeNote);
      finished(examOk, '「' + topic + '」の擬似言語トレース練習問題（本番形式）' + (examOk ? 'に正解しました' : 'に挑戦しました'));
      applyFocus(quiz.exam, true);
      markScrollable();
    });
  }

  // ---- 形式の切替え ----
  function setMode(mode) {
    root.setAttribute('data-mode', mode);
    all('.mode-switch .chip', root).forEach(function (chip) {
      chip.setAttribute('aria-pressed', chip.getAttribute('data-mode') === mode ? 'true' : 'false');
    });
    var score = root.querySelector('.score');
    if (mode === 'exam') {
      score.hidden = true;
      if (root.classList.contains('exam-done')) applyFocus(quiz.exam, true);
      else clearFocus();
    } else {
      score.hidden = false;
      if (root.classList.contains('all-done')) pressChip(practice.length - 1);
      else applyFocus(quiz.practice[practice.filter(function (s) { return s.classList.contains('answered'); }).length], false);
    }
    // 見ている形式の時計だけを進める
    ['practice', 'exam'].forEach(function (name) {
      if (name === mode && !timed[name]) watches[name].start(); else watches[name].pause();
    });
    try { window.localStorage.setItem('drill-mode', mode); } catch (e) { /* 保存できなくても動作に支障はない */ }
    markScrollable();
  }

  all('.mode-switch .chip', root).forEach(function (chip) {
    chip.addEventListener('click', function () { setMode(chip.getAttribute('data-mode')); });
  });

  var initial = 'practice';
  if (quiz.exam) {
    if (window.location.hash === '#exam') initial = 'exam';
    else {
      try { if (window.localStorage.getItem('drill-mode') === 'exam') initial = 'exam'; } catch (e) { /* 既定のまま */ }
    }
  }
  setMode(initial);
})();

/* トップの問題一覧：上の「入門・基礎・中級」のリンクから来たとき、その分類を開く。
   開閉そのものは details・summary の機能で、このスクリプトがなくても動く。 */
(function () {
  function openTarget() {
    var id = window.location.hash.slice(1);
    var target = id ? document.getElementById(id) : null;
    if (target && target.tagName === 'DETAILS' && target.classList.contains('level-group')) {
      target.open = true;
      target.scrollIntoView();
    }
  }
  window.addEventListener('hashchange', openTarget);
  document.addEventListener('click', function (event) {
    var link = event.target.closest ? event.target.closest('.level-entry a') : null;
    if (link && link.hash === window.location.hash) openTarget();   // 同じリンクをもう一度押したとき
  });
  openTarget();
})();
