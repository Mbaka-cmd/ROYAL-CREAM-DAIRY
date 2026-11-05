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


/* patch-hero-fade */
(function(){
  function go(){
    var base=document.querySelector('.hero-bg');
    if(!base || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    var alt=document.createElement('div');
    alt.className='hero-bg hero-bg-alt';
    alt.setAttribute('aria-hidden','true');
    base.parentNode.insertBefore(alt, base.nextSibling);
    setInterval(function(){ alt.classList.toggle('on'); }, 30000);
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',go);}else{go();}
})();


/* patch-trust-cats */
(function(){
  function go(){
    /* 1. move the trust row into the hero, under the Order now button */
    var need=['fresh & natural dairy','pay on delivery','proudly local'];
    function has(el){var s=(el.textContent||'').toLowerCase();return need.every(function(n){return s.indexOf(n)>-1;});}
    var cands=[].filter.call(document.body.querySelectorAll('div,ul,section'),has);
    var row=cands.filter(function(el){return ![].some.call(el.children,has);})[0];
    var target=document.querySelector('.hero-actions');
    if(row && target && !target.contains(row)){
      var old=row.parentElement;
      row.classList.add('rc-trust');
      target.parentNode.insertBefore(row,target.nextSibling);
      while(old && old!==document.body && !(old.textContent||'').trim() && !old.querySelector('img,svg,a,button')){
        var up=old.parentElement; old.remove(); old=up;
      }
    }
    /* 2. product photos on the category tiles */
    var base=(document.querySelector('link[href*="storefront.css"]')||{}).href;
    if(!base) return;
    base=base.replace(/css\/storefront\.css.*$/,'images/cat/');
    var map={'fresh milk':'milk.jpg','yoghurt':'yoghurt.jpg','yogurt':'yoghurt.jpg','butter':'butter.jpg'};
    [].forEach.call(document.querySelectorAll('a[href*="/products/"]'),function(a){
      var label=(a.textContent||'').trim().toLowerCase();
      var file=map[label]; var svg=a.querySelector('svg');
      if(!file||!svg||a.querySelector('.rc-catimg')) return;
      var img=document.createElement('img');
      img.className='rc-catimg'; img.src=base+file; img.alt=''; img.loading='lazy';
      var holder=svg.parentElement===a?svg:svg.parentElement;
      holder.parentNode.replaceChild(img,holder);
    });
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',go);}else{go();}
})();


/* patch-circles */
(function(){
  function go(){
    var names=['fresh milk','mala','yoghurt','yogurt','butter'];
    [].forEach.call(document.querySelectorAll('a[href*="/products/"]'),function(a){
      var label=(a.textContent||'').trim().toLowerCase();
      if(names.indexOf(label)<0) return;
      var img=a.querySelector('.rc-catimg');
      var svg=a.querySelector('svg');
      if(!img && !svg) return;
      a.classList.add('rc-cat');
      if(!img && svg){
        var holder=svg.parentElement===a?svg:svg.parentElement;
        holder.classList.add('rc-catico');
      }
    });
  }
  /* run after the earlier script has inserted the photos */
  if(document.readyState==='complete'){setTimeout(go,0);}else{window.addEventListener('load',function(){setTimeout(go,0);});}
})();


/* patch-how */
(function(){
  var ICONS=[
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/><path d="M2 3h3l2.6 12.2a1 1 0 0 0 1 .8h8.8a1 1 0 0 0 1-.8L20 8H6"/></svg>',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="6" width="19" height="12" rx="2"/><circle cx="12" cy="12" r="2.6"/><path d="M6 9.5v.01M18 14.5v.01"/></svg>'
  ];
  function go(){
    var ol=document.querySelector('ol.steps');
    if(!ol || ol.closest('.rc-how')) return;
    var h=null, hs=document.querySelectorAll('h2');
    for(var i=0;i<hs.length;i++){ if(/how ordering works/i.test(hs[i].textContent)){h=hs[i];break;} }
    var wrap=document.createElement('section');
    wrap.className='rc-how';
    var sub=document.createElement('p'); sub.className='rc-how-sub'; sub.textContent='Three simple steps. No account needed.';
    /* find the Delivery banner, then climb to the block that sits beside our section */
    var banner=null;
    for(var j=0;j<hs.length;j++){ if(/delivery in chuka/i.test(hs[j].textContent)){banner=hs[j];break;} }
    var anchor=banner;
    while(anchor && anchor.parentElement && !anchor.parentElement.contains(ol)) anchor=anchor.parentElement;
    if(!anchor || !anchor.parentNode) return;
    anchor.parentNode.insertBefore(wrap, anchor);
    if(h) wrap.appendChild(h); wrap.appendChild(sub); wrap.appendChild(ol);
    [].forEach.call(ol.children,function(li,k){
      var ico=document.createElement('span'); ico.className='rc-stepico'; ico.setAttribute('aria-hidden','true');
      ico.innerHTML=ICONS[k%ICONS.length];
      li.insertBefore(ico, li.firstChild);
    });
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',go);}else{go();}
})();
