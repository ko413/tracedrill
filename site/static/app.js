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

  root.classList.add('js');

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
        root.querySelector('.score').textContent = practice.length + '問中 ' + correct + '問正解でした。';
        pressChip(practice.length - 1);
      }
      markScrollable();
    });
  });

  chips.forEach(function (chip, index) {
    chip.addEventListener('click', function () { pressChip(index); });
  });

  if (examSection && quiz.exam) {
    enableButton(examSection).addEventListener('click', function () {
      if (grade(examSection, quiz.exam.answer, false) === null) return;
      root.classList.add('exam-done');
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
