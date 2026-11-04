(function () {
  "use strict";

  var script = document.currentScript;
  var id = script ? script.getAttribute("data-ga-id") || "" : "";

  function optedOut() {
    var nav = window.navigator || {};
    return nav.doNotTrack === "1" || window.doNotTrack === "1" || nav.globalPrivacyControl === true;
  }

  var enabled = /^G-[A-Z0-9]{4,20}$/.test(id) && !optedOut();
  if (!enabled) {
    window.rcTrack = function () {};
    return;
  }

  window.dataLayer = window.dataLayer || [];
  function gtag() {
    window.dataLayer.push(arguments);
  }

  var config = { allow_google_signals: false, allow_ad_personalization_signals: false };
  // The confirmation URL contains a private token: never send it to Google.
  if (location.pathname.indexOf("/order/") === 0) {
    config.page_location = location.origin + "/order/confirmation/";
    config.page_title = "Order confirmation";
  }

  var tag = document.createElement("script");
  tag.async = true;
  tag.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(id);
  document.head.appendChild(tag);

  gtag("js", new Date());
  gtag("config", id, config);

  window.rcTrack = function (name, params) {
    gtag("event", name, params || {});
  };

  function readJson(elementId) {
    var el = document.getElementById(elementId);
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  function init() {
    var view = readJson("ga-view-item");
    if (view) window.rcTrack("view_item", view);

    var purchase = readJson("ga-purchase");
    if (purchase && purchase.transaction_id) {
      var key = "rc_ga_tx";
      var seen = [];
      try {
        seen = JSON.parse(localStorage.getItem(key) || "[]");
      } catch (e) {
        seen = [];
      }
      if (seen.indexOf(purchase.transaction_id) === -1) {
        window.rcTrack("purchase", purchase);
        seen.push(purchase.transaction_id);
        try {
          localStorage.setItem(key, JSON.stringify(seen.slice(-20)));
        } catch (e) {}
      }
    }
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest ? event.target.closest("a[data-track=whatsapp]") : null;
    if (link) window.rcTrack("whatsapp_click", { link_location: "footer" });
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();