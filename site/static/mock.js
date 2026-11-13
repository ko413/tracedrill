/* 模試・先行公開ドリルの画面。

   会員かどうかの確認は member.js（MemberAuth）に任せ、このファイルは
   「目次を出す」「中身を開く」「解く・採点する」だけを受け持つ。
   無料のサンプル模試も同じ画面で動く（暗号化していないファイルを読むだけ）。 */
(function () {
  'use strict';

  var root = document.getElementById('members-app');
  if (!root) return;
  var base = root.getAttribute('data-members-base');
  var samplePath = root.getAttribute('data-sample');
  var noteUrl = root.getAttribute('data-note-url') || '';
  var app = document.getElementById('mock-app');

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (name) {
      if (name === 'text') node.textContent = attrs[name];
      else if (name === 'html') node.innerHTML = attrs[name];      // 自分のビルドが作った HTML だけを渡す
      else node.setAttribute(name, attrs[name]);
    });
    (children || []).forEach(function (child) { if (child) node.appendChild(child); });
    return node;
  }

  function store(key, value) {
    try {
      if (value === undefined) return JSON.parse(window.localStorage.getItem(key));
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (e) { /* 保存できなくても解ける */ }
    return null;
  }

  function fetchJson(path) {
    return fetch(path, { cache: 'no-cache' }).then(function (response) {
      if (!response.ok) throw new Error(path);
      return response.json();
    });
  }

  function clock(seconds) {
    var m = Math.floor(seconds / 60), s = seconds % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  // ---- 解く画面 ----

  function questionNode(q, index) {
    var name = 'q' + index;
    var choices;
    if (q.blanks.length > 1) {
      var head = el('tr', {}, [el('th')].concat(q.blanks.map(function (b) { return el('th', { text: b }); })));
      var rows = q.choices.map(function (c) {
        var input = el('input', { type: 'radio', name: name, value: c.label });
        var label = el('label', {}, [input, document.createTextNode(' ' + c.label)]);
        return el('tr', { 'data-label': c.label },
          [el('th', {}, [label])].concat(c.texts.map(function (t) { return el('td', { text: t }); })));
      });
      choices = el('div', { 'class': 'scroll-x' }, [
        el('table', { 'class': 'combo' }, [el('thead', {}, [head]), el('tbody', {}, rows)])]);
    } else {
      choices = el('fieldset', { 'class': 'exam-choices' }, q.choices.map(function (c) {
        return el('label', { 'data-label': c.label }, [
          el('input', { type: 'radio', name: name, value: c.label }),
          document.createTextNode(' '), el('b', { text: c.label }), document.createTextNode('　'),
          el('span', { text: c.texts[0] })]);
      }));
    }
    return el('section', { 'class': 'question mock-question', id: 'mock-q' + (index + 1) }, [
      el('h2', { text: '問' + (index + 1) }),
      el('p', { 'class': 'exam-lead', text: q.lead }),
      el('div', {}, q.body.map(function (p) { return el('p', { text: p }); })),
      el('p', { 'class': 'exam-heading', text: '〔プログラム〕' }),
      el('p', { 'class': 'scroll-hint', text: '横にスクロールできます' }),
      el('div', { 'class': 'program scroll-x', html: q.program_html }),
      el('p', { 'class': 'exam-heading', text: '解答群' }),
      choices,
      el('div', { 'class': 'result', 'aria-live': 'polite' })
    ]);
  }

  function showReview(section, q, chosen) {
    var ok = chosen === q.answer;
    section.classList.add(ok ? 'is-correct' : 'is-wrong');
    Array.prototype.forEach.call(section.querySelectorAll('input'), function (input) { input.disabled = true; });
    var right = section.querySelector('[data-label="' + q.answer + '"]');
    if (right) right.classList.add('is-answer');
    if (chosen && !ok) {
      var wrong = section.querySelector('[data-label="' + chosen + '"]');
      if (wrong) wrong.classList.add('is-chosen-wrong');
    }
    var result = section.querySelector('.result');
    result.appendChild(el('p', { 'class': 'verdict', text: ok ? '正解です。' : (chosen ? '不正解です。' : '未解答です。') }));
    result.appendChild(el('p', {}, [el('strong', { text: '正解：' + q.answer + '　' + q.answer_text })]));
    result.appendChild(el('p', { 'class': 'note', text: q.title + '（' + q.level + '）' }));
    result.appendChild(el('ul', {}, q.explain.map(function (line) { return el('li', { text: line }); })));
    result.appendChild(el('p', { text: q.explanation }));
    var note = q.marker_line ? 'α の行は，行番号つきのプログラムでは ' + q.marker_line + ' 行目です。' : '';
    result.appendChild(el('details', { 'class': 'hint' }, [
      el('summary', { text: '行番号つきのプログラムとトレース表（全ステップ）を見る' }),
      note ? el('p', { 'class': 'note', text: note }) : null,
      el('div', { 'class': 'scroll-x', html: q.review_html })]));
  }

  function play(bundle, options) {
    var isMock = bundle.kind === 'mock' && bundle.minutes > 0;
    var total = bundle.questions.length;
    var resultKey = 'mock-result:' + bundle.id;
    var timer = null, deadline = 0, startedAt = 0, graded = false;

    app.textContent = '';
    app.hidden = false;
    var summary = el('div', { 'class': 'mock-summary', 'aria-live': 'polite' });
    var timerBar = el('div', { 'class': 'mock-timer', hidden: '' });
    var paper = el('div', { id: 'mode-exam', hidden: '' }, bundle.questions.map(questionNode));
    var gradeButton = el('button', { type: 'button', 'class': 'button', text: '採点する' });
    var footer = el('p', { 'class': 'mock-actions', hidden: '' }, [gradeButton]);

    var intro = el('div', { 'class': 'mock-intro' }, [
      el('h2', { text: bundle.title }),
      el('p', { text: isMock
        ? total + '問・' + bundle.minutes + '分。本番と同じく、行番号のないプログラムを読んで解答群から選びます。'
          + '「始める」を押すと時間を計り始めます。'
        : total + '問。時間は計りません。すべて選んでから「採点する」を押してください。' })
    ]);
    var last = store(resultKey);
    if (last) intro.appendChild(el('p', { 'class': 'note', text: '前回の結果：' + last.score + ' / ' + last.total + ' 問正解（' + last.date + '）' }));
    var startButton = el('button', { type: 'button', 'class': 'button', text: isMock ? '始める' : '問題を表示する' });
    intro.appendChild(el('p', {}, [startButton]));

    [intro, summary, timerBar, paper, footer].forEach(function (node) { app.appendChild(node); });

    function tick() {
      var left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
      timerBar.textContent = '残り ' + clock(left);
      if (left <= 0) grade(true);
    }

    function grade(timeUp) {
      if (graded) return;
      graded = true;
      if (timer) window.clearInterval(timer);
      var score = 0, blank = 0;
      bundle.questions.forEach(function (q, index) {
        var section = document.getElementById('mock-q' + (index + 1));
        var checked = section.querySelector('input:checked');
        var chosen = checked ? checked.value : '';
        if (!chosen) blank += 1;
        if (chosen === q.answer) score += 1;
        showReview(section, q, chosen);
      });
      var used = startedAt ? Math.round((Date.now() - startedAt) / 1000) : 0;
      var today = new Date();
      store(resultKey, { score: score, total: total,
        date: today.getFullYear() + '/' + (today.getMonth() + 1) + '/' + today.getDate() });
      timerBar.hidden = true;
      footer.hidden = true;
      summary.textContent = '';
      summary.appendChild(el('h2', { text: '結果：' + score + ' / ' + total + ' 問正解（' + Math.round(score * 100 / total) + '%）' }));
      var parts = [];
      if (timeUp) parts.push('時間切れのため、その時点の解答で採点しました。');
      if (isMock && used) parts.push('かかった時間：' + clock(used) + '。');
      if (blank) parts.push('未解答：' + blank + '問。');
      parts.push('各問の下に、正解・解説・トレース表があります。');
      summary.appendChild(el('p', { text: parts.join(' ') }));
      var wrong = bundle.questions.map(function (q, i) {
        var s = document.getElementById('mock-q' + (i + 1));
        return s.classList.contains('is-correct') ? null : el('a', { href: '#mock-q' + (i + 1), 'class': 'chip', text: '問' + (i + 1) });
      }).filter(Boolean);
      if (wrong.length) summary.appendChild(el('p', { 'class': 'mock-wrong' }, [document.createTextNode('見直す問題： ')].concat(wrong)));
      if (options && options.after) summary.appendChild(options.after());
      summary.scrollIntoView();
    }

    startButton.addEventListener('click', function () {
      intro.hidden = true;
      paper.hidden = false;
      footer.hidden = false;
      if (isMock) {
        startedAt = Date.now();
        deadline = startedAt + bundle.minutes * 60 * 1000;
        timerBar.hidden = false;
        tick();
        timer = window.setInterval(tick, 1000);
      }
    });
    gradeButton.addEventListener('click', function () { grade(false); });
  }

  // ---- 会員ページ（目次と合言葉） ----

  function joinLink(text) {
    return noteUrl ? el('a', { 'class': 'button', href: noteUrl, rel: 'noopener', text: text })
                   : el('span', { 'class': 'note', text: '入会ページは準備中です。' });
  }

  function listNode(index, keys) {
    var kinds = { mock: '模試', drill: '先行公開ドリル' };
    var items = index.bundles.map(function (b) {
      var meta = kinds[b.kind] + '・' + b.count + '問' + (b.minutes ? '・' + b.minutes + '分' : '') + '・' + b.issued.replace('-', '年') + '月';
      var last = store('mock-result:' + b.id);
      if (last) meta += '　前回 ' + last.score + ' / ' + last.total;
      var title = keys && keys[b.id]
        ? el('a', { href: base + '?id=' + encodeURIComponent(b.id), text: b.title })
        : el('span', { text: b.title });
      var extra = b.public_path ? el('span', { 'class': 'note', text: '（無料公開済み）' }) : null;
      return el('li', {}, [title, extra, el('span', { 'class': 'mock-meta', text: meta })]);
    });
    return el('ul', { 'class': 'mock-list' }, items);
  }

  function loginNode(message, onDone) {
    var input = el('input', { type: 'text', id: 'member-pass', autocomplete: 'off', autocapitalize: 'characters',
      placeholder: '例：ABCD-EFGH-JKMN-PQRS', 'aria-describedby': 'member-pass-note' });
    var button = el('button', { type: 'submit', 'class': 'button', text: '開く' });
    var note = el('p', { 'class': 'note', id: 'member-pass-note', 'aria-live': 'polite', text: message || '' });
    var form = el('form', { 'class': 'member-login' }, [
      el('label', { 'for': 'member-pass', text: '今月の合言葉' }), input, button, note]);
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      button.disabled = true;
      note.textContent = '確認しています…';
      window.MemberAuth.login(input.value).then(function (ok) {
        if (ok) return onDone();
        button.disabled = false;
        note.textContent = '合言葉が違います。合言葉は毎月変わります。note の会員限定記事で、今月の合言葉を確認してください。';
      }).catch(function () {
        button.disabled = false;
        note.textContent = '読み込みに失敗しました。通信の状態を確かめて、もう一度お試しください。';
      });
    });
    return form;
  }

  function membersPage() {
    var id = new URLSearchParams(window.location.search).get('id');
    var status = document.getElementById('member-status');
    status.textContent = '読み込んでいます…';

    Promise.all([fetchJson(base + 'index.json'), window.MemberAuth.keys(), window.MemberAuth.expired()])
      .then(function (values) {
        var index = values[0], keys = values[1], expired = values[2];
        status.textContent = '';
        if (!keys) {
          status.appendChild(loginNode(
            expired ? '合言葉が新しくなりました。note の会員限定記事で、今月の合言葉を確認してください。' : '',
            function () { window.location.reload(); }));
          status.appendChild(el('p', {}, [joinLink('note で会員になる')]));
          status.appendChild(el('h2', { text: '会員が解ける模試・ドリル' }));
          status.appendChild(listNode(index, null));
          return null;
        }
        if (!id) {
          document.getElementById('member-intro').hidden = true;      // 確認済みなら、一覧をすぐ見せる
          status.appendChild(el('h2', { text: '模試・ドリルを選ぶ' }));
          status.appendChild(el('p', { 'class': 'note', text: '過去の回（バックナンバー）も、すべて解けます。結果はこの端末に記録されます。' }));
          status.appendChild(listNode(index, keys));
          var out = el('button', { type: 'button', 'class': 'chip', text: 'この端末の合言葉を消す' });
          out.addEventListener('click', function () { window.MemberAuth.logout(); window.location.reload(); });
          status.appendChild(el('p', {}, [out]));
          return null;
        }
        if (!keys[id]) {
          status.appendChild(el('p', { text: 'この模試は見つかりませんでした。' }));
          status.appendChild(el('p', {}, [el('a', { href: base, text: '一覧に戻る' })]));
          return null;
        }
        return fetchJson(base + 'data/' + encodeURIComponent(id) + '.json')
          .then(function (box) { return window.MemberAuth.open(keys[id], box); })
          .then(function (bundle) {
            document.getElementById('member-intro').hidden = true;
            status.appendChild(el('p', {}, [el('a', { href: base, text: '← 模試・ドリルの一覧' })]));
            play(bundle, null);
          });
      })
      .catch(function () {
        status.textContent = '読み込みに失敗しました。通信の状態を確かめて、ページを開き直してください。';
      });
  }

  function samplePage() {
    fetchJson(samplePath).then(function (bundle) {
      play(bundle, { after: function () {
        return el('div', { 'class': 'mock-upsell' }, [
          el('p', { text: '会員になると、毎月追加される模試と、これまでのすべての回を解けます。新しいアルゴリズムのドリルも先に解けます。' }),
          el('p', {}, [el('a', { 'class': 'button', href: base, text: '会員ページを見る' })])]);
      } });
    }).catch(function () {
      app.hidden = false;
      app.textContent = '読み込みに失敗しました。ページを開き直してください。';
    });
  }

  if (!window.crypto || !window.crypto.subtle) {
    var warn = document.getElementById('member-status') || app;
    warn.hidden = false;
    if (!samplePath) { warn.textContent = 'このブラウザでは会員ページを開けません。新しいブラウザで、https のアドレスから開いてください。'; return; }
  }
  if (samplePath) samplePage(); else membersPage();
})();
