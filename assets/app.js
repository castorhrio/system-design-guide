/* ==========================================================================
   系统设计中文精讲 — 交互脚本
   1) 主题切换  2) 移动端目录  3) 全文搜索  4) 本页目录高亮
   5) 回到顶部  6) 代码块复制
   无任何外部依赖，离线可用。
   ========================================================================== */
(function () {
  "use strict";

  var SITE = window.SDG_SITE || {};
  var PREFIX = SITE.prefix || "";   /* 当前页面到站点根的相对前缀，如 "../../" */

  /* ---------------- 1. 主题 ---------------- */
  var root = document.documentElement;
  var themeBtn = document.getElementById("themeToggle");

  function applyTheme(t) {
    root.setAttribute("data-theme", t);
    if (themeBtn) {
      themeBtn.textContent = t === "dark" ? "\u2600" : "\u263D";
      themeBtn.setAttribute("aria-label", t === "dark" ? "切换到浅色" : "切换到深色");
      themeBtn.title = t === "dark" ? "切换到浅色" : "切换到深色";
    }
  }
  function currentTheme() {
    return root.getAttribute("data-theme") || "dark";
  }
  if (themeBtn) {
    applyTheme(currentTheme());
    themeBtn.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      applyTheme(next);
      try { localStorage.setItem("sdg-theme", next); } catch (e) {}
    });
  }

  /* ---------------- 2. 移动端目录 ---------------- */
  var navToggle = document.getElementById("navToggle");
  var sidebar = document.getElementById("sidebar");
  var scrim = document.getElementById("scrim");

  function closeNav() {
    if (sidebar) sidebar.classList.remove("open");
    if (scrim) scrim.classList.remove("show");
  }
  if (navToggle && sidebar) {
    navToggle.addEventListener("click", function () {
      var open = sidebar.classList.toggle("open");
      if (scrim) scrim.classList.toggle("show", open);
    });
  }
  if (scrim) scrim.addEventListener("click", closeNav);
  window.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeNav();
  });

  /* ---------------- 3. 全文搜索 ---------------- */
  var input = document.getElementById("search");
  var panel = document.getElementById("searchResults");
  var INDEX = null;
  var loading = false;
  var sel = -1;
  var results = [];

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function mark(q, text) {
    var s = esc(text);
    if (!q) return s;
    var i = s.toLowerCase().indexOf(q.toLowerCase());
    if (i < 0) return s;
    return s.slice(0, i) + "<mark>" + s.slice(i, i + q.length) + "</mark>" + s.slice(i + q.length);
  }

  function loadIndex(cb) {
    if (INDEX) return cb();
    if (loading) return;
    loading = true;
    fetch(PREFIX + "assets/search.json")
      .then(function (r) { return r.json(); })
      .then(function (d) { INDEX = d; loading = false; cb(); })
      .catch(function () { INDEX = []; loading = false; cb(); });
  }

  function runSearch(q) {
    q = q.trim();
    if (!q) { panel.hidden = true; results = []; return; }
    var ql = q.toLowerCase();
    var out = [];
    for (var i = 0; i < INDEX.length; i++) {
      var it = INDEX[i];
      var hHit = it.h.toLowerCase().indexOf(ql) >= 0;
      var xHit = it.x.toLowerCase().indexOf(ql) >= 0;
      var tHit = it.t.toLowerCase().indexOf(ql) >= 0;
      if (!hHit && !xHit && !tHit) continue;
      out.push({ it: it, score: (hHit ? 3 : 0) + (tHit ? 2 : 0) + (xHit ? 1 : 0) });
      if (out.length > 400) break;
    }
    out.sort(function (a, b) { return b.score - a.score; });
    results = out.slice(0, 30);
    render(q);
  }

  function render(q) {
    if (!results.length) {
      panel.innerHTML = '<div class="sr-empty">没有匹配的内容</div>';
      panel.hidden = false;
      return;
    }
    var html = '<div class="sr-head">找到 ' + results.length + ' 条结果</div>';
    for (var i = 0; i < results.length; i++) {
      var it = results[i].it;
      html +=
        '<a class="sr-item" href="' + esc(PREFIX + (it.u || "")) + '">' +
        '<span class="sr-title">' + mark(q, it.h) + "</span>" +
        '<span class="sr-path">' + esc(it.t) + "</span>" +
        '<span class="sr-x">' + mark(q, it.x) + "</span>" +
        "</a>";
    }
    panel.innerHTML = html;
    panel.hidden = false;
    sel = -1;
  }

  function moveSel(d) {
    var items = panel.querySelectorAll(".sr-item");
    if (!items.length) return;
    if (sel >= 0 && items[sel]) items[sel].classList.remove("sel");
    sel = (sel + d + items.length) % items.length;
    items[sel].classList.add("sel");
    items[sel].scrollIntoView({ block: "nearest" });
  }

  if (input && panel) {
    var timer = null;
    input.addEventListener("focus", function () { loadIndex(function () { runSearch(input.value); }); });
    input.addEventListener("input", function () {
      var v = input.value;
      loadIndex(function () {
        clearTimeout(timer);
        timer = setTimeout(function () { runSearch(v); }, 90);
      });
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); moveSel(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); moveSel(-1); }
      else if (e.key === "Enter") {
        var items = panel.querySelectorAll(".sr-item");
        if (items.length) {
          var target = sel >= 0 ? items[sel] : items[0];
          window.location.href = target.getAttribute("href");
        }
      } else if (e.key === "Escape") {
        panel.hidden = true;
        input.blur();
      }
    });
    document.addEventListener("click", function (e) {
      if (!panel.contains(e.target) && e.target !== input) panel.hidden = true;
    });
  }

  // 快捷键：/ 或 Ctrl+K 聚焦搜索
  window.addEventListener("keydown", function (e) {
    var tag = (e.target.tagName || "").toLowerCase();
    var typing = tag === "input" || tag === "textarea" || e.target.isContentEditable;
    if (typing) return;
    if (e.key === "/" || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k")) {
      if (input) { e.preventDefault(); input.focus(); input.select(); }
    }
  });

  /* ---------------- 4. 本页目录高亮 ---------------- */
  var tocLinks = document.querySelectorAll(".toc a[href^='#']");
  if (tocLinks.length && "IntersectionObserver" in window) {
    var map = {};
    tocLinks.forEach(function (a) { map[decodeURIComponent(a.getAttribute("href").slice(1))] = a; });
    var heads = document.querySelectorAll(".md h2[id], .md h3[id]");
    var visible = {};
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { visible[en.target.id] = en.isIntersecting ? en.intersectionRatio : 0; });
      var best = null, bestTop = Infinity;
      Object.keys(visible).forEach(function (id) {
        var el = document.getElementById(id);
        if (!el) return;
        var top = el.getBoundingClientRect().top;
        if (top < 120 && top > -1e6 && Math.abs(top - 90) < bestTop) { bestTop = Math.abs(top - 90); best = id; }
      });
      if (!best) {
        // 回退：取第一个仍在视口下方的标题
        for (var i = 0; i < heads.length; i++) {
          if (heads[i].getBoundingClientRect().top > 90) { best = heads[i].id; break; }
        }
      }
      tocLinks.forEach(function (a) { a.classList.remove("active"); });
      if (best && map[best]) map[best].classList.add("active");
    }, { rootMargin: "-80px 0px -70% 0px", threshold: [0, 1] });
    heads.forEach(function (h) { io.observe(h); });
  }

  /* ---------------- 5. 回到顶部 ---------------- */
  var toTop = document.getElementById("toTop");
  if (toTop) {
    var onScroll = function () {
      toTop.classList.toggle("show", window.scrollY > 700);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    toTop.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  /* ---------------- 6. 代码块复制 ---------------- */
  document.querySelectorAll(".md pre").forEach(function (pre) {
    var wrap = document.createElement("div");
    wrap.className = "code-wrap";
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    var btn = document.createElement("button");
    btn.className = "code-copy";
    btn.type = "button";
    btn.textContent = "复制";
    btn.addEventListener("click", function () {
      var code = pre.querySelector("code");
      var text = code ? code.innerText : pre.innerText;
      var done = function () {
        btn.textContent = "已复制";
        btn.classList.add("done");
        setTimeout(function () { btn.textContent = "复制"; btn.classList.remove("done"); }, 1400);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { fallback(text, done); });
      } else {
        fallback(text, done);
      }
    });
    wrap.appendChild(btn);
  });

  function fallback(text, done) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); done(); } catch (e) {}
    document.body.removeChild(ta);
  }
})();
