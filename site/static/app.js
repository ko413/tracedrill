// 全ページ共通：横にはみ出す表に「横にスクロールできます」の案内を付ける。
// 問題ページ：練習モード（設問を順に解く）と本番形式（1問）の切替え、答え合わせ、トレース表の強調。
// 外部のライブラリは使っていない。問題のデータはページ内の <script id="quiz-data"> にある。
(function () {
  'use strict';

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

  // 答え合わせの共通部分。正解なら true を返す。
  function grade(section, answer) {
    var chosen = section.querySelector('input[type="radio"]:checked');
    if (!chosen) return null;
    var ok = chosen.value === answer;
    section.classList.add('answered', ok ? 'is-correct' : 'is-wrong');
    section.querySelector('.verdict').textContent = ok ? '正解です。' : '不正解です。';
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
      var ok = grade(section, q.answer);
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
      if (grade(examSection, quiz.exam.answer) === null) return;
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
