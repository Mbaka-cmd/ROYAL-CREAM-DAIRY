(function () {
  "use strict";

  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* Header gets a stronger shadow once the page is scrolled. */
  function initHeader() {
    var header = document.querySelector(".site-header");
    if (!header) return;
    var ticking = false;
    function update() {
      ticking = false;
      header.classList.toggle("scrolled", (window.pageYOffset || 0) > 8);
    }
    window.addEventListener("scroll", function () {
      if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(update);
      }
    }, { passive: true });
    update();
  }

  /* Cart badge bumps whenever its number really changes (cart.js sets the text). */
  function initBadgeBump() {
    if (reduce || !window.MutationObserver) return;
    document.querySelectorAll("[data-cart-count]").forEach(function (badge) {
      var last = badge.textContent;
      new MutationObserver(function () {
        if (badge.textContent === last) return;
        last = badge.textContent;
        badge.classList.remove("bump");
        void badge.offsetWidth;
        badge.classList.add("bump");
      }).observe(badge, { childList: true, characterData: true, subtree: true });
      badge.addEventListener("animationend", function () {
        badge.classList.remove("bump");
      });
    });
  }

  /* Cards, tiles and steps rise in one after another as they enter the screen. */
  function initRise() {
    if (reduce || !("IntersectionObserver" in window)) return;
    var els = Array.prototype.slice.call(
      document.querySelectorAll(".grid .card, .cat-tile, .steps li, .trust-item")
    );
    if (!els.length) return;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.remove("rise-pending");
        entry.target.classList.add("rise-in");
        io.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -6% 0px", threshold: 0.08 });
    els.forEach(function (el, i) {
      el.style.setProperty("--d", (i % 4) * 70 + "ms");
      el.classList.add("rise-pending");
      io.observe(el);
    });
  }

  function init() {
    initHeader();
    initBadgeBump();
    initRise();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

/* patch-final4 */
(function(){
  var WORDS=/^(fresh\s*milk|mala|yoghurt|yogurt|butter|[\s\u00b7\u2022.\-|,])+$/i;
  function go(){
    var best=null;
    var els=document.body.querySelectorAll('div,ul,section,p');
    for(var i=0;i<els.length;i++){
      var el=els[i], t=(el.textContent||'').trim();
      if(!t || !WORDS.test(t)) continue;
      var n=(t.match(/fresh\s*milk|mala|yoghurt|yogurt|butter/ig)||[]).length;
      if(n<8) continue;
      best=el; /* keep going: the last match in document order is the innermost, so climb below */
      break;
    }
    if(!best) return;
    /* climb to the outermost ancestor that is still only the marquee */
    var strip=best;
    while(strip.parentElement && strip.parentElement!==document.body){
      var pt=(strip.parentElement.textContent||'').trim();
      if(WORDS.test(pt)) strip=strip.parentElement; else break;
    }
    strip.classList.add('rc-marquee');
    var h=document.querySelector('.site-header');
    var anchor=h;
    while(anchor && anchor.parentElement && anchor.parentElement!==document.body) anchor=anchor.parentElement;
    if(anchor && anchor.parentNode){ anchor.parentNode.insertBefore(strip, anchor.nextSibling); }
    else { document.body.insertBefore(strip, document.body.firstChild); }
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',go);}else{go();}
})();
