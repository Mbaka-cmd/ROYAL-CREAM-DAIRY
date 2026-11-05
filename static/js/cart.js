(function () {
  "use strict";

  var KEY = "rc_cart";
  var MAX_QTY = 50;

  function load() {
    try {
      var data = JSON.parse(localStorage.getItem(KEY) || "{}");
      return data && typeof data === "object" && !Array.isArray(data) ? data : {};
    } catch (e) {
      return {};
    }
  }

  function save(cart) {
    try {
      localStorage.setItem(KEY, JSON.stringify(cart));
    } catch (e) {}
  }

  function total(cart) {
    var n = 0;
    Object.keys(cart).forEach(function (k) {
      n += Number(cart[k]) || 0;
    });
    return n;
  }

  function updateBadges() {
    var n = total(load());
    document.querySelectorAll("[data-cart-count]").forEach(function (el) {
      el.textContent = n;
      el.hidden = n === 0;
    });
  }

  var toastTimer = null;
  function toast(message) {
    var el = document.getElementById("toast");
    if (!el) return;
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      el.classList.remove("show");
    }, 1800);
  }

  var api = {
    get: load,
    items: function () {
      var cart = load();
      return Object.keys(cart).map(function (id) {
        return { variant_id: parseInt(id, 10), quantity: cart[id] };
      });
    },
    set: function (id, qty) {
      var cart = load();
      qty = Math.floor(Number(qty));
      if (!(qty >= 1)) {
        delete cart[id];
      } else {
        cart[id] = Math.min(qty, MAX_QTY);
      }
      save(cart);
      updateBadges();
    },
    remove: function (id) {
      var cart = load();
      delete cart[id];
      save(cart);
      updateBadges();
    },
    clear: function () {
      try {
        localStorage.removeItem(KEY);
        sessionStorage.removeItem("rc_idem");
      } catch (e) {}
      updateBadges();
    },
    toast: toast,
    updateBadges: updateBadges
  };
  window.RCCart = api;

  document.addEventListener("click", function (event) {
    var btn = event.target.closest ? event.target.closest(".js-add") : null;
    if (!btn || btn.disabled) return;
    var id = btn.getAttribute("data-variant");
    var max = Math.min(parseInt(btn.getAttribute("data-max"), 10) || MAX_QTY, MAX_QTY);
    var current = load()[id] || 0;
    if (current + 1 > max) {
      toast("Only " + max + " available.");
      return;
    }
    api.set(id, current + 1);
    toast("Added to cart"); if (window.rcTrack) { var price = Number(btn.getAttribute("data-price")) || 0; window.rcTrack("add_to_cart", { currency: "KES", value: price, items: [{ item_id: id, item_name: btn.getAttribute("data-name") || "", price: price, quantity: 1 }] }); }
  });

  function init() {
    if (document.body.getAttribute("data-clear-cart") === "1") {
      api.clear();
    }
    updateBadges();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();