(function () {
  var input = document.getElementById('dash-search-input');
  if (!input) return;
  var box = document.getElementById('dash-search-results');
  var url = input.getAttribute('data-url');
  var timer = null, ctl = null, links = [], idx = -1;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }
  function clear() {
    box.textContent = ''; box.hidden = true; links = []; idx = -1;
    input.setAttribute('aria-expanded', 'false');
  }
  function mark() {
    links.forEach(function (a, i) { a.classList.toggle('active', i === idx); });
    if (links[idx]) links[idx].scrollIntoView({ block: 'nearest' });
  }
  function group(title, rows) {
    if (!rows || !rows.length) return;
    box.appendChild(el('div', 'search-group', title));
    rows.forEach(function (r) {
      var a = el('a', 'search-item');
      a.href = r.url;
      var main = el('span', 'search-main');
      main.appendChild(el('strong', '', r.title));
      main.appendChild(el('span', 'search-sub', r.sub || ''));
      a.appendChild(main);
      if (r.badge) a.appendChild(el('span', 'st', r.badge));
      box.appendChild(a);
      links.push(a);
    });
  }
  function render(data) {
    box.textContent = ''; links = []; idx = -1;
    group('Orders', data.orders);
    group('Customers', data.customers);
    group('Products', data.products);
    if (!links.length) box.appendChild(el('div', 'search-empty', 'No matches'));
    box.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  }
  function run() {
    var q = input.value.trim();
    if (q.length < 2) { clear(); return; }
    if (ctl) ctl.abort();
    ctl = new AbortController();
    fetch(url + '?q=' + encodeURIComponent(q), { credentials: 'same-origin', signal: ctl.signal, headers: { 'Accept': 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error('search ' + r.status); return r.json(); })
      .then(render)
      .catch(function (e) {
        if (e.name === 'AbortError') return;
        box.textContent = ''; box.appendChild(el('div', 'search-empty', 'Search is unavailable. Try again shortly.')); box.hidden = false;
      });
  }
  input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(run, 150); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); if (links.length) { idx = (idx + 1) % links.length; mark(); } }
    else if (e.key === 'ArrowUp') { e.preventDefault(); if (links.length) { idx = (idx - 1 + links.length) % links.length; mark(); } }
    else if (e.key === 'Enter') { var t = links[idx >= 0 ? idx : 0]; if (t) { e.preventDefault(); window.location.href = t.href; } }
    else if (e.key === 'Escape') { clear(); input.blur(); }
  });
  document.addEventListener('keydown', function (e) {
    var tag = (e.target.tagName || '').toLowerCase();
    var typing = tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); input.focus(); input.select(); }
    else if (e.key === '/' && !typing) { e.preventDefault(); input.focus(); }
  });
  document.addEventListener('click', function (e) { if (!e.target.closest('.dash-search')) clear(); });
  input.addEventListener('focus', function () { if (input.value.trim().length >= 2 && !links.length) run(); });
})();
