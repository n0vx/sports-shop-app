/* SPORT STORE — небольшой JS без фреймворков. Без JS сайт тоже работает (формы отправляются обычным способом). */
(function () {
  'use strict';

  var MAX_PHOTO = 20 * 1024 * 1024;
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  var toasts = document.getElementById('toasts');

  /* ---------- всплывающие сообщения ---------- */
  function dismiss(el) {
    el.classList.add('is-hiding');
    setTimeout(function () { el.remove(); }, 320);
  }
  function toast(message, kind) {
    if (!toasts) { return; }
    var el = document.createElement('div');
    el.className = 'toast toast-' + (kind || 'ok');
    el.setAttribute('role', 'status');
    el.textContent = message;
    toasts.appendChild(el);
    setTimeout(function () { dismiss(el); }, 3200);
  }
  document.querySelectorAll('.toast').forEach(function (el) {
    setTimeout(function () { dismiss(el); }, 3800);
  });

  /* ---------- fetch с CSRF ---------- */
  function post(url, body, json) {
    var headers = { 'X-Requested-With': 'fetch', 'X-CSRF-Token': csrf, 'Accept': 'application/json' };
    if (json) { headers['Content-Type'] = 'application/json'; }
    return fetch(url, {
      method: 'POST', body: json ? JSON.stringify(body) : body, headers: headers, credentials: 'same-origin'
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, message: 'Неожиданный ответ сервера' }; });
    });
  }

  /* ---------- автоотправка форм, подтверждения, «В корзину» без перезагрузки ---------- */
  document.addEventListener('change', function (e) {
    var t = e.target;
    if (!t.matches || !t.matches('[data-autosubmit]') || !t.form) { return; }
    if (t.type === 'file') {
      if (!t.files.length) { return; }
      if (t.files[0].size > MAX_PHOTO) {
        toast('Файл слишком большой (максимум 20 МБ)', 'error');
        t.value = '';
        return;
      }
    }
    t.form.submit();
  });

  function updateCart(count) {
    var badge = document.getElementById('cart-count');
    if (!badge) { return; }
    badge.textContent = count;
    badge.classList.remove('bump');
    void badge.offsetWidth;
    badge.classList.add('bump');
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (form.dataset && form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      e.preventDefault();
      return;
    }
    if (form.matches && form.matches('[data-ajax]')) {
      e.preventDefault();
      var btn = form.querySelector('button');
      if (btn) { btn.disabled = true; }
      post(form.action, new FormData(form), false).then(function (d) {
        toast(d.message || 'Готово', d.ok ? 'ok' : 'error');
        if (typeof d.count === 'number') { updateCart(d.count); }
      }).catch(function () {
        toast('Нет связи с сервером. Попробуйте ещё раз.', 'error');
      }).then(function () {
        if (btn) { btn.disabled = false; }
      });
    }
  });

  /* ---------- предпросмотр фото в форме товара ---------- */
  var photoInput = document.getElementById('photo-input');
  if (photoInput) {
    photoInput.addEventListener('change', function () {
      var file = photoInput.files[0];
      var name = document.getElementById('photo-name');
      var tile = document.querySelector('.tile-preview');
      if (!file) { if (name) { name.textContent = ''; } return; }
      if (file.size > MAX_PHOTO) {
        toast('Файл слишком большой (максимум 20 МБ)', 'error');
        photoInput.value = '';
        return;
      }
      if (name) { name.textContent = file.name; }
      if (tile && file.type.indexOf('image/') === 0) {
        var img = tile.querySelector('img');
        if (!img) {
          img = document.createElement('img');
          img.alt = 'Выбранное фото';
          tile.textContent = '';
          tile.appendChild(img);
        }
        img.src = URL.createObjectURL(file);
      }
    });
  }

  /* ---------- окно «Оформление» ---------- */
  var dialog = document.getElementById('appearance');
  if (dialog) {
    var action = dialog.dataset.action;
    var color = document.getElementById('custom-accent');
    var timer = null;

    document.querySelectorAll('[data-open-dialog="appearance"]').forEach(function (b) {
      b.addEventListener('click', function () {
        if (typeof dialog.showModal === 'function') { dialog.showModal(); }
      });
    });
    dialog.querySelectorAll('[data-close]').forEach(function (b) {
      b.addEventListener('click', function () { dialog.close(); });
    });
    dialog.addEventListener('click', function (e) { if (e.target === dialog) { dialog.close(); } });

    dialog.querySelectorAll('.swatch').forEach(function (s) {
      s.style.backgroundColor = s.dataset.color;
    });

    function apply(d) {
      var root = document.documentElement;
      root.dataset.theme = d.theme;
      Object.keys(d.vars).forEach(function (name) { root.style.setProperty(name, d.vars[name]); });
      var meta = document.querySelector('meta[name="color-scheme"]');
      if (meta) { meta.content = d.theme; }
      dialog.querySelectorAll('[data-theme-choice]').forEach(function (b) {
        b.setAttribute('aria-pressed', String(b.dataset.themeChoice === d.theme));
      });
      dialog.querySelectorAll('.swatch').forEach(function (s) {
        s.setAttribute('aria-pressed', String(s.dataset.color.toUpperCase() === d.accent.toUpperCase()));
      });
      if (color) { color.value = d.accent.toLowerCase(); }
    }

    function save(payload) {
      post(action, payload, true).then(function (d) {
        if (d.ok) { apply(d); } else { toast(d.message || 'Не удалось сохранить', 'error'); }
      }).catch(function () { toast('Нет связи с сервером', 'error'); });
    }

    dialog.querySelectorAll('[data-theme-choice]').forEach(function (b) {
      b.addEventListener('click', function () { save({ theme: b.dataset.themeChoice }); });
    });
    dialog.querySelectorAll('.swatch').forEach(function (s) {
      s.addEventListener('click', function () { save({ accent: s.dataset.color }); });
    });
    if (color) {
      color.addEventListener('input', function () {  // пока тянут ползунок — не засыпаем сервер запросами
        clearTimeout(timer);
        timer = setTimeout(function () { save({ accent: color.value }); }, 180);
      });
    }
    var reset = dialog.querySelector('[data-reset-appearance]');
    if (reset) { reset.addEventListener('click', function () { save({ reset: true }); }); }
  }
})();
