/* 模試・先行公開ドリルの画面。

   会員かどうかの確認は member.js（MemberAuth）に任せ、このファイルは
   「目次を出す」「中身を開く」「解く・採点する」だけを受け持つ。
   無料のサンプル模試も同じ画面で動く（暗号化していないファイルを読むだけ）。 */
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

  // 端末の中への保存。store(key) で読む、store(key, 値) で書く、store(key, null) で消す
  function store(key, value) {
    try {
      if (value === undefined) return JSON.parse(window.localStorage.getItem(key));
      if (value === null) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, JSON.stringify(value));
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

  // 計測用。アクセス計測（Cloudflare Web Analytics）は「ページの閲覧」しか数えられないので、
  // 模試を始めた・採点したときに、アドレスだけを専用のものに切り替えて1回の閲覧として数えさせる。
  // 切り替え先（…/started/、…/graded/）には、開き直したときのために元のページへ戻すだけのページを置いてある。
  function countStep(step) {
    var stepBase = root.getAttribute('data-step-base');
    if (!stepBase || !window.history || !window.history.pushState) return;
    try { window.history.pushState({ step: step }, '', stepBase + step + '/'); } catch (e) { /* 数えられなくても解ける */ }
  }

  // 採点結果に付ける「題材別の正誤」。linkBase があるとき（サンプル模試）は、練習問題へのリンクも付ける。
  function breakdownNode(bundle, correct, linkBase) {
    var rows = bundle.questions.map(function (q, i) {
      var name = linkBase
        ? el('a', { href: linkBase + encodeURIComponent(q.template_id.replace(/-00[2-9]$/, '-001')) + '/', text: q.title })
        : document.createTextNode(q.title);
      return el('tr', { 'class': correct[i] ? 'is-correct' : 'is-wrong' }, [
        el('td', {}, [el('a', { href: '#mock-q' + (i + 1), text: '問' + (i + 1) })]),
        el('td', { text: correct[i] ? '○' : '×' }),       // 結果は、スマホでも見える左側に置く
        el('td', {}, [name]),
        el('td', { text: q.level })]);
    });
    var table = el('table', { 'class': 'mock-breakdown' }, [
      el('thead', {}, [el('tr', {}, ['問', '結果', '題材', 'レベル'].map(function (h) { return el('th', { text: h }); }))]),
      el('tbody', {}, rows)]);
    var nodes = [el('h3', { text: '題材別の結果' }), el('div', { 'class': 'scroll-x' }, [table])];
    var missed = bundle.questions.filter(function (q, i) { return !correct[i]; });
    if (linkBase && missed.length) {
      // 次に解くドリル：間違えた題材を、やさしい順に3つまで
      var seen = {}, next = [];
      missed.forEach(function (q) {
        var id = q.template_id.replace(/-00[2-9]$/, '-001');
        if (!seen[id] && next.length < 3) { seen[id] = true; next.push({ id: id, title: q.title }); }
      });
      nodes.push(el('h3', { text: '次に解くドリル' }));
      nodes.push(el('p', { text: '間違えた題材から、やさしい順に選びました。値を変えた問題を続けて解くと、手順が身につきます。' }));
      nodes.push(el('ul', { 'class': 'links' }, next.map(function (item) {
        return el('li', {}, [el('a', { href: linkBase + encodeURIComponent(item.id) + '/', text: '「' + item.title + '」の解説と練習問題' })]);
      })));
    } else if (linkBase) {
      nodes.push(el('p', { text: '全問正解です。ほかの題材や、長めのトレース（じっくり）にも挑戦してみてください。' }));
    }
    return el('div', { 'class': 'mock-breakdown-box' }, nodes);
  }

  function play(bundle, options) {
    var isMock = bundle.kind === 'mock' && bundle.minutes > 0;
    var total = bundle.questions.length;
    var resultKey = 'mock-result:' + bundle.id;
    var progressKey = 'mock-progress:' + bundle.id;      // 途中の解答と開始時刻（開き直しても続けられるように）
    var timer = null, deadline = 0, startedAt = 0, graded = false, left = 0;

    app.textContent = '';
    app.hidden = false;
    var summary = el('div', { 'class': 'mock-summary', 'aria-live': 'polite', tabindex: '-1' });
    var timerBar = el('div', { 'class': 'mock-timer', hidden: '' });
    var paper = el('div', { id: 'mode-exam', hidden: '' }, bundle.questions.map(questionNode));
    var gradeButton = el('button', { type: 'button', 'class': 'button', text: '採点する' });
    var pending = el('span', { 'class': 'mock-pending', 'aria-live': 'polite' });
    var footer = el('div', { 'class': 'mock-actions', hidden: '' }, [pending, el('p', {}, [gradeButton])]);

    var intro = el('div', { 'class': 'mock-intro' }, [
      el('h2', { text: bundle.title }),
      el('p', { text: isMock
        ? total + '問・' + bundle.minutes + '分。本番と同じく、行番号のないプログラムを読んで解答群から選びます。'
          + '「始める」を押すと時間を計り始めます。途中でページを閉じても、同じ端末なら続きから再開できます。'
        : total + '問。時間は計りません。すべて選んでから「採点する」を押してください。' })
    ]);
    var last = store(resultKey);
    if (last) intro.appendChild(el('p', { 'class': 'note', text: '前回の結果：' + last.score + ' / ' + last.total + ' 問正解（' + last.date + '）' }));

    // 途中まで解いた記録があれば、続きから再開できる（模試は、制限時間が残っているときだけ）
    var saved = store(progressKey);
    var savedCount = saved && saved.answers ? Object.keys(saved.answers).length : 0;
    var canResume = saved && (!isMock || (saved.startedAt && saved.startedAt + bundle.minutes * 60000 > Date.now()));
    var startButton = el('button', { type: 'button', 'class': 'button', text: isMock ? '始める' : '問題を表示する' });
    var resumeButton = null;
    if (canResume && (savedCount || isMock)) {
      var remain = isMock ? '・残り ' + clock(Math.round((saved.startedAt + bundle.minutes * 60000 - Date.now()) / 1000)) : '';
      resumeButton = el('button', { type: 'button', 'class': 'button', text: '続きから再開する' });
      intro.appendChild(el('p', { 'class': 'note', text: '途中まで解いた記録があります（解答済み ' + savedCount + '問' + remain + '）。' }));
      startButton.className = 'chip';
      startButton.textContent = '最初からやり直す';
    }
    // ボタンは説明文より前に置く（スマホの最初の画面に入るように）
    intro.insertBefore(el('p', { 'class': 'mock-start' }, [resumeButton, startButton]), intro.children[1]);

    [intro, summary, timerBar, paper, footer].forEach(function (node) { app.appendChild(node); });

    function answers() {
      var map = {};
      bundle.questions.forEach(function (q, index) {
        var checked = document.querySelector('#mock-q' + (index + 1) + ' input:checked');
        if (checked) map[index] = checked.value;
      });
      return map;
    }

    // 上に固定する帯（残り時間と解答済みの数）と、採点ボタンの上の「未解答」の案内
    function refresh() {
      var done = Object.keys(answers()).length;
      timerBar.textContent = (isMock ? '残り ' + clock(left) + '　' : '') + '解答 ' + done + ' / ' + total;
      pending.textContent = '';
      var missing = bundle.questions.map(function (q, i) { return i; })
        .filter(function (i) { return !document.querySelector('#mock-q' + (i + 1) + ' input:checked'); });
      if (missing.length) {
        pending.appendChild(document.createTextNode('未解答：'));
        missing.slice(0, 8).forEach(function (i) {
          pending.appendChild(el('a', { href: '#mock-q' + (i + 1), 'class': 'chip', text: '問' + (i + 1) }));
        });
        if (missing.length > 8) pending.appendChild(document.createTextNode(' ほか' + (missing.length - 8) + '問'));
      } else {
        pending.textContent = 'すべて解答済みです。';
      }
    }

    function tick() {
      left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
      refresh();
      if (left <= 0) grade(true);
    }

    function grade(timeUp) {
      if (graded) return;
      graded = true;
      if (timer) window.clearInterval(timer);
      var score = 0, blank = 0, correct = [];
      bundle.questions.forEach(function (q, index) {
        var section = document.getElementById('mock-q' + (index + 1));
        var checked = section.querySelector('input:checked');
        var chosen = checked ? checked.value : '';
        if (!chosen) blank += 1;
        if (chosen === q.answer) score += 1;
        correct.push(chosen === q.answer);
        showReview(section, q, chosen);
      });
      var used = startedAt ? Math.round((Date.now() - startedAt) / 1000) : 0;
      var today = new Date();
      store(resultKey, { score: score, total: total,
        date: today.getFullYear() + '/' + (today.getMonth() + 1) + '/' + today.getDate() });
      store(progressKey, null);                      // 採点したら、途中の記録は消す
      timerBar.hidden = true;
      footer.hidden = true;
      summary.textContent = '';
      // 顔文字はサンプル模試だけ（会員ページは kaomoji.js を読み込まないので、何も出ない）
      if (window.Kaomoji) {
        var cheer = el('p', { 'class': 'mock-cheer' });
        window.Kaomoji.say(cheer, 'done');
        summary.appendChild(cheer);
      }
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
      summary.appendChild(breakdownNode(bundle, correct, options && options.linkBase));
      if (options && options.after) summary.appendChild(options.after());
      countStep('graded');
      summary.scrollIntoView();
      summary.focus({ preventScroll: true });        // キーボード・読み上げの人が、結果から読み始められるように
    }

    function begin(resume) {
      intro.hidden = true;
      paper.hidden = false;
      footer.hidden = false;
      timerBar.hidden = false;
      // 説明文をたたんで、問題をすぐ見せる
      Array.prototype.forEach.call(document.querySelectorAll('[data-hide-on-start]'), function (node) { node.hidden = true; });
      if (resume && saved) {
        Object.keys(saved.answers || {}).forEach(function (index) {
          var input = document.querySelector('#mock-q' + (Number(index) + 1) + ' input[value="' + saved.answers[index] + '"]');
          if (input) input.checked = true;
        });
        startedAt = saved.startedAt || Date.now();
      } else {
        startedAt = Date.now();
        countStep('started');                        // 再開は、もう一度数えない
      }
      store(progressKey, { startedAt: startedAt, answers: answers() });
      if (isMock) {
        deadline = startedAt + bundle.minutes * 60 * 1000;
        tick();
        timer = window.setInterval(tick, 1000);
      } else {
        refresh();
      }
      var first = document.getElementById('mock-q1');
      first.setAttribute('tabindex', '-1');
      first.focus({ preventScroll: true });
      (isMock ? timerBar : first).scrollIntoView();
    }

    paper.addEventListener('click', pickComboRow);
    paper.addEventListener('change', function () {
      if (graded) return;
      store(progressKey, { startedAt: startedAt, answers: answers() });
      refresh();
    });
    startButton.addEventListener('click', function () { begin(false); });
    if (resumeButton) resumeButton.addEventListener('click', function () { begin(true); });
    gradeButton.addEventListener('click', function () { grade(false); });
  }

  // ---- 会員ページ（目次と合言葉） ----

  function joinLink(text) {
    if (!noteUrl) return el('span', { 'class': 'note', text: '入会ページは準備中です。' });
    // 押した回数を数える（…/join/ への切り替え）。数え終わる前にページを離れないよう、note は新しいタブで開く
    var link = el('a', { 'class': 'button', href: noteUrl, target: '_blank', rel: 'noopener', text: text });
    link.addEventListener('click', function () { countStep('join'); });
    return link;
  }

  function listNode(index, keys) {
    var kinds = { mock: '模試', drill: '先行公開ドリル' };
    var items = index.bundles.map(function (b) {
      var meta = kinds[b.kind] + '・' + b.count + '問' + (b.minutes ? '・' + b.minutes + '分' : '') + '・' + b.issued.replace('-', '年') + '月';
      var last = store('mock-result:' + b.id);
      if (last) meta += '　前回 ' + last.score + ' / ' + last.total;
      var open = keys && keys[b.id];
      var title = open
        ? el('a', { href: base + '?id=' + encodeURIComponent(b.id), text: b.title })
        : el('span', { text: b.title });
      var extra = b.public_path ? el('span', { 'class': 'note', text: '（無料公開済み）' }) : null;
      // 単品で買える回：まだ開けていない人にだけ、販売ページへのリンクを出す
      var single = !open && b.single && b.single_url
        ? el('a', { 'class': 'mock-single', href: b.single_url, rel: 'noopener', text: 'この回だけ購入する（note）' })
        : null;
      return el('li', {}, [title, extra, el('span', { 'class': 'mock-meta', text: meta }), single]);
    });
    return el('ul', { 'class': 'mock-list' }, items);
  }

  function loginNode(message, onDone, singleIds) {
    var hasSingles = singleIds && singleIds.length > 0;
    var input = el('input', { type: 'text', id: 'member-pass', autocomplete: 'off', autocapitalize: 'characters',
      placeholder: '例：ABCD-EFGH-JKMN-PQRS', 'aria-describedby': 'member-pass-note' });
    var button = el('button', { type: 'submit', 'class': 'button', text: '開く' });
    var note = el('p', { 'class': 'note', id: 'member-pass-note', 'aria-live': 'polite', text: message || '' });
    var form = el('form', { 'class': 'member-login' }, [
      el('label', { 'for': 'member-pass', text: hasSingles ? '合言葉（会員の方は今月の合言葉、単品で購入した方はその回の合言葉）' : '今月の合言葉' }),
      input, button, note]);
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      button.disabled = true;
      note.textContent = '確認しています…';
      window.MemberAuth.login(input.value, singleIds || []).then(function (ok) {
        if (ok) return onDone();
        button.disabled = false;
        note.textContent = '合言葉が違います。会員の合言葉は毎月変わります。note の会員限定記事で、今月の合言葉を確認してください。';
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

        // 開ける模試を指定して来た → そのまま解く画面へ
        if (id && keys && keys[id]) {
          return fetchJson(base + 'data/' + encodeURIComponent(id) + '.json')
            .then(function (box) { return window.MemberAuth.open(keys[id], box); })
            .then(function (bundle) {
              document.getElementById('member-intro').hidden = true;
              status.appendChild(el('p', {}, [el('a', { href: base, text: '← 模試・ドリルの一覧' })]));
              play(bundle, null);
            });
        }

        // 単品用の合言葉を試す順番：指定された回があれば、それを先に
        var singleIds = index.bundles.filter(function (b) { return b.single; }).map(function (b) { return b.id; });
        if (id && singleIds.indexOf(id) > 0) { singleIds.splice(singleIds.indexOf(id), 1); singleIds.unshift(id); }
        var openAll = keys && index.bundles.every(function (b) { return keys[b.id]; });

        if (keys) document.getElementById('member-intro').hidden = true;      // 確認済みなら、一覧をすぐ見せる
        if (id && !index.bundles.some(function (b) { return b.id === id; })) {
          status.appendChild(el('p', { text: 'この模試は見つかりませんでした。' }));
        }
        if (!openAll) {
          var message = expired ? '会員の合言葉が新しくなりました。note の会員限定記事で、今月の合言葉を確認してください。' : '';
          status.appendChild(loginNode(message, function () { window.location.reload(); }, singleIds));
          status.appendChild(el('p', {}, [joinLink('note で会員になる')]));
        }
        status.appendChild(el('h2', { text: keys ? '模試・ドリルを選ぶ' : '会員が解ける模試・ドリル' }));
        if (openAll) {
          status.appendChild(el('p', { 'class': 'note', text: '過去の回（バックナンバー）も、すべて解けます。結果はこの端末に記録されます。' }));
        }
        status.appendChild(listNode(index, keys));
        if (keys) {
          var out = el('button', { type: 'button', 'class': 'chip', text: 'この端末の合言葉を消す' });
          out.addEventListener('click', function () { window.MemberAuth.logout(); window.location.reload(); });
          status.appendChild(el('p', {}, [out]));
        }
        return null;
      })
      .catch(function () {
        status.textContent = '読み込みに失敗しました。通信の状態を確かめて、ページを開き直してください。';
      });
  }

  function samplePage() {
    fetchJson(samplePath).then(function (bundle) {
      play(bundle, { linkBase: root.getAttribute('data-algo-base'), after: function () {
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
  // HTML に書いてある入会ボタン（会員ページの上部）も、押した回数を数える
  Array.prototype.forEach.call(document.querySelectorAll('[data-join]'), function (link) {
    link.addEventListener('click', function () { countStep('join'); });
  });
  if (samplePath) samplePage(); else membersPage();
})();
