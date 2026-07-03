/* drDRO docs — shared UI behaviour (no dependencies). */
(function () {
  "use strict";

  /* Mobile nav toggle ------------------------------------------------------ */
  var toggle = document.querySelector(".nav-toggle");
  var links = document.querySelector(".nav-links");
  if (toggle && links) {
    toggle.addEventListener("click", function () {
      links.classList.toggle("open");
    });
    links.addEventListener("click", function (e) {
      if (e.target.tagName === "A") links.classList.remove("open");
    });
  }

  /* Copy-to-clipboard buttons --------------------------------------------- */
  document.querySelectorAll(".copy-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var sel = btn.getAttribute("data-copy");
      var pre = sel ? document.querySelector(sel) : btn.closest(".code").querySelector("pre");
      if (!pre) return;
      var text = pre.innerText.replace(/ /g, " ");
      navigator.clipboard.writeText(text).then(function () {
        var old = btn.textContent;
        btn.textContent = "Copied";
        btn.classList.add("copied");
        setTimeout(function () {
          btn.textContent = old;
          btn.classList.remove("copied");
        }, 1600);
      });
    });
  });

  /* Lightbox for screenshots ---------------------------------------------- */
  var lb = document.createElement("div");
  lb.className = "lightbox";
  lb.innerHTML =
    '<button class="lb-close" aria-label="Close">&times;</button>' +
    '<img alt=""><div class="lb-cap"></div>';
  document.body.appendChild(lb);
  var lbImg = lb.querySelector("img");
  var lbCap = lb.querySelector(".lb-cap");

  function openLb(src, cap) {
    lbImg.src = src;
    lbCap.textContent = cap || "";
    lb.classList.add("open");
  }
  function closeLb() { lb.classList.remove("open"); lbImg.src = ""; }
  lb.addEventListener("click", closeLb);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeLb(); });

  document.querySelectorAll("[data-zoom]").forEach(function (img) {
    img.addEventListener("click", function (e) {
      e.stopPropagation();
      openLb(img.getAttribute("data-zoom") || img.src, img.getAttribute("data-cap") || img.alt);
    });
  });

  /* Tabs ------------------------------------------------------------------- */
  document.querySelectorAll("[data-tabs]").forEach(function (group) {
    var btns = group.querySelectorAll(".tab-btn");
    var panels = group.querySelectorAll(".tab-panel");
    btns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var t = btn.getAttribute("data-tab");
        btns.forEach(function (b) { b.classList.toggle("active", b === btn); });
        panels.forEach(function (p) { p.classList.toggle("active", p.getAttribute("data-panel") === t); });
      });
    });
  });

  /* Scroll-spy for doc TOC ------------------------------------------------- */
  var tocLinks = Array.prototype.slice.call(document.querySelectorAll(".toc a"));
  if (tocLinks.length && "IntersectionObserver" in window) {
    var map = {};
    var sections = tocLinks.map(function (a) {
      var id = a.getAttribute("href").slice(1);
      var el = document.getElementById(id);
      if (el) map[id] = a;
      return el;
    }).filter(Boolean);

    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) {
          tocLinks.forEach(function (a) { a.classList.remove("active"); });
          if (map[en.target.id]) map[en.target.id].classList.add("active");
        }
      });
    }, { rootMargin: "-15% 0px -75% 0px" });
    sections.forEach(function (s) { obs.observe(s); });
  }

  /* Video facades — swap the thumbnail for a player only on click ---------- */
  document.querySelectorAll(".video-thumb[data-ytid]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var id = btn.getAttribute("data-ytid");
      var embed = document.createElement("div");
      embed.className = "video-embed";
      var ifr = document.createElement("iframe");
      ifr.src = "https://www.youtube-nocookie.com/embed/" + id + "?autoplay=1&rel=0";
      ifr.title = btn.getAttribute("aria-label") || "YouTube video player";
      ifr.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
      ifr.setAttribute("allowfullscreen", "");
      embed.appendChild(ifr);
      btn.replaceWith(embed);
    });
  });

  /* Lazy-load thumbnails via data-bg (avoids 14 image requests before paint) */
  var bgImgs = document.querySelectorAll(".video-thumb[data-bg]");
  if (bgImgs.length && "IntersectionObserver" in window) {
    var bo = new IntersectionObserver(function (entries, obs) {
      entries.forEach(function (en) {
        if (en.isIntersecting) {
          var el = en.target;
          el.style.backgroundImage = "url('" + el.getAttribute("data-bg") + "')";
          obs.unobserve(el);
        }
      });
    }, { rootMargin: "200px" });
    bgImgs.forEach(function (el) { bo.observe(el); });
  } else {
    bgImgs.forEach(function (el) { el.style.backgroundImage = "url('" + el.getAttribute("data-bg") + "')"; });
  }

  /* Year in footer --------------------------------------------------------- */
  var y = document.querySelector("[data-year]");
  if (y) y.textContent = new Date().getFullYear();
})();
