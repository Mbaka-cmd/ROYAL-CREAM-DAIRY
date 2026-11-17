(function () {
  function norm(v) { return /^\d+$/.test(v) ? v + '_COMPLETED' : v; }
  function has(k) { try { return !!localStorage.getItem('wa_fwd_' + k); } catch (e) { return false; } }
  function mark(k) { try { localStorage.setItem('wa_fwd_' + k, '1'); } catch (e) {} }
  function paint() {
    document.querySelectorAll('[data-wa-key]').forEach(function (r) {
      if (has(r.getAttribute('data-wa-key'))) r.classList.add('done');
    });
  }
  paint();

  document.addEventListener('click', function (e) {
    var c = e.target.closest('[data-wa-copy]');
    if (c) {
      var t = document.querySelector(c.getAttribute('data-wa-copy'));
      if (t && navigator.clipboard) { navigator.clipboard.writeText(t.value); c.textContent = 'Copied'; }
    }
    var f = e.target.closest('[data-wa-fwd]');
    if (f) { mark(norm(f.getAttribute('data-wa-fwd'))); paint(); }
  });

  var b = document.getElementById('wa-badge');
  if (!b) return;
  var items = [];
  try { items = JSON.parse(b.getAttribute('data-items') || '[]'); } catch (e) {}
  var open = items.filter(function (i) { return !has(i.pk + '_COMPLETED'); });
  if (!open.length) return;
  b.textContent = open.length;
  b.classList.add('on');

  var first = open[0], key = 'wa_toast_' + first.pk;
  try { if (sessionStorage.getItem(key)) return; sessionStorage.setItem(key, '1'); } catch (e) {}
  var t = document.createElement('div'); t.className = 'wa-toast';
  var s = document.createElement('strong'); s.textContent = 'Order ' + first.ref + ' completed';
  var p = document.createElement('div');
  p.textContent = 'Forward the receipt to ' + first.name + ' on WhatsApp.' + (open.length > 1 ? ' (+' + (open.length - 1) + ' more)' : '');
  var row = document.createElement('div'); row.className = 'wa-toast-row';
  var a = document.createElement('a'); a.href = first.url; a.textContent = 'Open Messages';
  var x = document.createElement('button'); x.type = 'button'; x.textContent = 'Dismiss';
  x.addEventListener('click', function () { t.remove(); });
  row.appendChild(a); row.appendChild(x);
  t.appendChild(s); t.appendChild(p); t.appendChild(row);
  document.body.appendChild(t);
})();