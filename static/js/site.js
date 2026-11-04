(function () {
  "use strict";

  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) return;

  function inView(el) {
    var rect = el.getBoundingClientRect();
    var height = window.innerHeight || document.documentElement.clientHeight;
    return rect.top < height && rect.bottom > 0;
  }

  function initReveal() {
    if (!("IntersectionObserver" in window)) return;
    var items = Array.prototype.slice.call(document.querySelectorAll(".reveal"));
    if (!items.length) return;
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.remove("reveal-hidden");
            entry.target.classList.add("reveal-in");
            observer.unobserve(entry.target);
          }
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
    );
    items.forEach(function (el) {
      if (!inView(el)) {
        el.classList.add("reveal-hidden");
        observer.observe(el);
      }
    });
  }

  function initParallax() {
    var hero = document.querySelector("[data-parallax]");
    if (!hero) return;
    var bg = hero.querySelector(".hero-bg");
    if (!bg) return;
    var ticking = false;
    function update() {
      ticking = false;
      var y = window.pageYOffset || 0;
      if (y > hero.offsetHeight) return;
      bg.style.transform = "translate3d(0," + Math.round(y * 0.25) + "px,0)";
    }
    window.addEventListener(
      "scroll",
      function () {
        if (!ticking) {
          ticking = true;
          window.requestAnimationFrame(update);
        }
      },
      { passive: true }
    );
  }

  function init() {
    initReveal();
    initParallax();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();