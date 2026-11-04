(function () {
  "use strict";

  var root = document.getElementById("checkout-root");
  if (!root || !window.RCCart) return;

  var form = document.getElementById("checkout-form");
  var linesEl = document.getElementById("cart-lines");
  var totalsEl = document.getElementById("cart-totals");
  var msgEl = document.getElementById("cart-message");
  var emptyEl = document.getElementById("cart-empty");
  var submitBtn = document.getElementById("place-order");
  var cartInput = form.querySelector("[name=cart]");
  var keyInput = form.querySelector("[name=idempotency_key]");
  var csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;
  var validateUrl = root.getAttribute("data-validate-url");
  var state = { valid: false };
  var seq = 0; var tracked = false; function trackBeginCheckout(data) { if (tracked || !window.rcTrack || !data.lines.length) { return; } tracked = true; window.rcTrack("begin_checkout", { currency: "KES", value: parseFloat(data.subtotal) || 0, items: data.lines.map(function (l) { return { item_id: String(l.variant_id), item_name: l.product + " " + l.variant, price: parseFloat(l.unit_price) || 0, quantity: l.quantity }; }) }); }

  function newKey() {
    if (window.crypto && window.crypto.randomUUID) {
      return window.crypto.randomUUID().replace(/-/g, "");
    }
    return String(Date.now()) + Math.random().toString(16).slice(2) + Math.random().toString(16).slice(2);
  }

  function getKey() {
    try {
      var k = sessionStorage.getItem("rc_idem");
      if (!k) {
        k = newKey();
        sessionStorage.setItem("rc_idem", k);
      }
      return k;
    } catch (e) {
      return newKey();
    }
  }

  keyInput.value = getKey();

  function fmt(s) {
    return "KSh " + (/\.00$/.test(s) ? s.slice(0, -3) : s);
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function setMessage(text) {
    msgEl.textContent = text || "";
  }

  function updateSubmit() {
    submitBtn.disabled = !state.valid;
  }

  function qtyButton(label, aria, handler) {
    var b = el("button", "qty-btn", label);
    b.type = "button";
    b.setAttribute("aria-label", aria);
    b.addEventListener("click", handler);
    return b;
  }

  function render(data) {
    emptyEl.hidden = true;
    linesEl.textContent = "";
    data.lines.forEach(function (line) {
      var row = el("div", "cart-line" + (line.ok ? "" : " bad"));

      var info = el("div", "cart-line-info");
      info.appendChild(el("strong", "", line.product));
      info.appendChild(el("span", "muted", line.variant + " \u00b7 " + fmt(line.unit_price)));
      if (line.message) info.appendChild(el("span", "warn", line.message));
      row.appendChild(info);

      row.appendChild(el("div", "cart-line-total", fmt(line.line_total)));

      var qty = el("div", "qty");
      qty.appendChild(qtyButton("\u2212", "Decrease quantity", function () {
        RCCart.set(line.variant_id, line.quantity - 1);
        refresh();
      }));
      qty.appendChild(el("span", "qty-num", String(line.quantity)));
      qty.appendChild(qtyButton("+", "Increase quantity", function () {
        RCCart.set(line.variant_id, line.quantity + 1);
        refresh();
      }));
      row.appendChild(qty);

      var remove = el("button", "link-btn", "Remove");
      remove.type = "button";
      remove.addEventListener("click", function () {
        RCCart.remove(line.variant_id);
        refresh();
      });
      row.appendChild(remove);

      linesEl.appendChild(row);
    });

    totalsEl.textContent = "";
    function addTotal(label, value, grand) {
      var row = el("div", grand ? "grand" : "");
      row.appendChild(el("dt", "", label));
      row.appendChild(el("dd", "", value));
      totalsEl.appendChild(row);
    }
    addTotal("Subtotal", fmt(data.subtotal));
    if (parseFloat(data.delivery_fee) > 0) addTotal("Delivery", fmt(data.delivery_fee));
    addTotal("Total", fmt(data.total), true);
  }

  function showEmpty() {
    linesEl.textContent = "";
    totalsEl.textContent = "";
    emptyEl.hidden = false;
    state.valid = false;
    setMessage("");
    updateSubmit();
  }

  function refresh() {
    var items = RCCart.items();
    cartInput.value = JSON.stringify(items);
    if (!items.length) {
      showEmpty();
      return;
    }
    var mine = ++seq;
    fetch(validateUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify({ items: items })
    })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        if (mine !== seq) return;
        if (data.unavailable && data.unavailable.length) {
          data.unavailable.forEach(function (id) {
            RCCart.remove(id);
          });
          refresh();
          setMessage("Some items are no longer available and were removed.");
          return;
        }
        render(data);
        state.valid = !!data.valid; trackBeginCheckout(data);
        setMessage(data.valid ? "" : "Please fix the highlighted items.");
        updateSubmit();
      })
      .catch(function () {
        if (mine !== seq) return;
        state.valid = false;
        setMessage("Could not check your cart. Check your connection and try again.");
        updateSubmit();
      });
  }

  form.addEventListener("submit", function (event) {
    cartInput.value = JSON.stringify(RCCart.items());
    if (!state.valid) {
      event.preventDefault();
      setMessage("Please fix your cart before placing the order.");
      return;
    }
    submitBtn.disabled = true;
    submitBtn.textContent = "Placing order...";
  });

  window.addEventListener("pageshow", function () {
    submitBtn.textContent = "Place order";
    refresh();
  });

  refresh();
})();