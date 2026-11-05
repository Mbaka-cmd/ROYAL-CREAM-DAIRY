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

/* patch-final3 */
(function(){
  function go(){
    var all=document.body.querySelectorAll('*'), track=null;
    for(var i=0;i<all.length;i++){
      var cs=getComputedStyle(all[i]);
      if(cs.animationName && cs.animationName!=='none' && /FRESH MILK/i.test(all[i].textContent) && all[i].children.length>3){track=all[i];break;}
    }
    if(!track) return;
    for(var j=0;j<track.children.length;j++){
      var c=track.children[j];
      c.style.paddingLeft='40px'; c.style.paddingRight='40px'; c.style.letterSpacing='.16em';
    }
    var strip=track.parentElement;
    if(strip && strip!==document.body){ document.body.insertBefore(strip, document.body.firstChild); }
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',go);}else{go();}
})();
