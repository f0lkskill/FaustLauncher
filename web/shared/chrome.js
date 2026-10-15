/* ============================================================
   子窗口统一标题栏 —— 结构与交互 (web/shared/chrome.js)

   由 functions/base/window_chrome.py 注入:
     window.__FL_CHROME__ = {title, icon, poll_ms}
     <chrome.js 全文>

   职责:
     1. 在 <body> 顶部插入与主界面同款的 #fl-titlebar (图标 + 标题 + 最小化/关闭)
     2. 拖动标题栏移动窗口 (绝对屏幕坐标 + requestAnimationFrame 串行化,
        与主界面 web/app/js/core/events.js 的拖动实现一致)
     3. 倒轮询 api.theme_revision(): 主程序切换皮肤后, 子窗口立刻重建
        <style id="fl-theme"> —— 不需要重启子窗口
   ============================================================ */
(function () {
  "use strict";

  var CFG = window.__FL_CHROME__ || {};
  var BAR_ID = "fl-titlebar";
  var THEME_ID = "fl-theme";

  function api() { return (window.pywebview && window.pywebview.api) || null; }
  function q(id) { return document.getElementById(id); }

  // ---------------- 标题栏 DOM ----------------
  function buildBar() {
    var existed = q(BAR_ID);
    if (existed) return existed;

    var bar = document.createElement("div");
    bar.id = BAR_ID;

    var drag = document.createElement("div");
    drag.className = "tb-drag";

    var icon = document.createElement("img");
    icon.className = "tb-icon";
    icon.setAttribute("draggable", "false");
    icon.alt = "";
    if (CFG.icon) { icon.src = CFG.icon; } else { icon.hidden = true; }

    var title = document.createElement("span");
    title.className = "tb-title";
    title.textContent = CFG.title || (document.title || "");
    title.title = title.textContent;

    drag.appendChild(icon);
    drag.appendChild(title);

    var actions = document.createElement("div");
    actions.className = "tb-actions";

    var min = document.createElement("button");
    min.className = "tb-btn";
    min.id = "fl-tb-min";
    min.type = "button";
    min.innerHTML = "&#x2212;";
    min.title = "最小化";

    var close = document.createElement("button");
    close.className = "tb-btn tb-close";
    close.id = "fl-tb-close";
    close.type = "button";
    close.innerHTML = "&#x2715;";
    close.title = "关闭";

    actions.appendChild(min);

    // frameless 窗口没有系统最大化按钮, 尺寸可变的窗口自己补一个
    var max = null;
    if (CFG.resizable !== false) {
      max = document.createElement("button");
      max.className = "tb-btn";
      max.id = "fl-tb-max";
      max.type = "button";
      max.innerHTML = "&#x25A1;";
      max.title = "最大化";
      actions.appendChild(max);
    }
    actions.appendChild(close);
    bar.appendChild(drag);
    bar.appendChild(actions);

    var body = document.body || document.documentElement;
    body.insertBefore(bar, document.body ? document.body.firstChild : null);

    document.documentElement.classList.add("fl-chrome");
    if (document.body) document.body.classList.add("fl-chrome");

    bindDrag(bar);

    min.addEventListener("click", function () {
      var a = api();
      if (a && a.minimize_window) { try { a.minimize_window(); } catch (e) {} }
    });
    close.addEventListener("click", function () {
      var a = api();
      if (a && a.close_window) { try { a.close_window(); } catch (e) {} }
    });

    if (max) {
      max.addEventListener("click", function () { toggleMax(); });
    }
    buildResizeHandles();
    return bar;
  }

  // ---------------- 最大化 ----------------
  function setMaxGlyph(on) {
    var b = q("fl-tb-max");
    if (!b) return;
    b.innerHTML = on ? "&#x2750;" : "&#x25A1;";
    b.title = on ? "向下还原" : "最大化";
  }

  function toggleMax() {
    var a = api();
    if (a && a.toggle_maximize_window) {
      try {
        Promise.resolve(a.toggle_maximize_window()).then(function (on) {
          setMaxGlyph(!!on);
        }).catch(function () {});
      } catch (e) {}
    }
  }

  // ---------------- 边框缩放 (frameless 窗口没有系统边框) ----------------
  var EDGES = [
    ["n", "top:0;left:0;right:0;height:3px;cursor:ns-resize"],
    ["s", "bottom:0;left:0;right:0;height:4px;cursor:ns-resize"],
    ["w", "top:0;bottom:0;left:0;width:4px;cursor:ew-resize"],
    ["e", "top:0;bottom:0;right:0;width:4px;cursor:ew-resize"],
    ["nw", "top:0;left:0;width:10px;height:10px;cursor:nwse-resize"],
    ["ne", "top:0;right:0;width:10px;height:10px;cursor:nesw-resize"],
    ["sw", "bottom:0;left:0;width:10px;height:10px;cursor:nesw-resize"],
    ["se", "bottom:0;right:0;width:10px;height:10px;cursor:nwse-resize"]
  ];

  function buildResizeHandles() {
    if (CFG.resizable === false) return;
    if (q("fl-resize-layer")) return;
    var layer = document.createElement("div");
    layer.id = "fl-resize-layer";
    EDGES.forEach(function (pair) {
      var d = document.createElement("div");
      d.className = "fl-rz fl-rz-" + pair[0];
      d.setAttribute("style", pair[1]);
      d.addEventListener("mousedown", function (e) { bindResize(e, pair[0]); });
      layer.appendChild(d);
    });
    var body = document.body || document.documentElement;
    body.appendChild(layer);
  }

  function bindResize(e, edge) {
    if (e.button !== 0) return;
    var a = api();
    if (!a || !a.begin_resize_window) return;
    e.preventDefault();
    e.stopPropagation();

    var raf = null, px = e.screenX, py = e.screenY;
    var chain = Promise.resolve();
    var call = function (fn, args) {
      var f = a[fn];
      if (!f) return;
      chain = chain.then(function () {
        try { return f.apply(a, args); } catch (err) { return null; }
      }).catch(function () {});
    };

    call("begin_resize_window", [edge, e.screenX, e.screenY]);

    var flush = function () {
      raf = null;
      call("resize_window", [px, py]);
      var on = false;
      try { on = q("fl-tb-max") && q("fl-tb-max").innerHTML.indexOf("\u2750") >= 0; } catch (err) {}
      if (on) setMaxGlyph(false);
    };
    var onMove = function (ev) {
      px = ev.screenX;
      py = ev.screenY;
      if (!raf) raf = requestAnimationFrame(flush);
    };
    var onUp = function () {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      if (raf) { cancelAnimationFrame(raf); raf = null; }
      call("resize_window", [px, py]);
      call("end_resize_window", []);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  // ---------------- 拖动 ----------------
  function bindDrag(bar) {
    bar.addEventListener("mousedown", function (e) {
      if (e.button !== 0) return;
      var t = e.target;
      if (!t || !t.closest) return;
      if (t.closest(".tb-btn")) return;
      if (!t.closest(".tb-drag")) return;

      var a = api();
      if (!a || !a.begin_move_window) return;
      e.preventDefault();
      e.stopPropagation();

      var raf = null, px = e.screenX, py = e.screenY;
      var chain = Promise.resolve();
      var call = function (fn, x, y) {
        var f = a[fn];
        if (!f) return;
        chain = chain.then(function () {
          try { return x === undefined ? f() : f(x, y); } catch (err) { return null; }
        }).catch(function () {});
      };

      call("begin_move_window", e.screenX, e.screenY);

      var flush = function () {
        raf = null;
        call("move_window", px, py);
      };
      var onMove = function (ev) {
        px = ev.screenX;
        py = ev.screenY;
        if (!raf) raf = requestAnimationFrame(flush);
      };
      var onUp = function () {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        if (raf) { cancelAnimationFrame(raf); raf = null; }
        call("move_window", px, py);
        call("end_move_window");
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    });

    // 双击标题栏 = 最大化/还原 (和系统标题栏一致); 固定尺寸窗口只阻止选中
    bar.addEventListener("dblclick", function (e) {
      e.preventDefault();
      var t2 = e.target;
      if (t2 && t2.closest && t2.closest(".tb-btn")) return;
      if (CFG.resizable === false) return;
      toggleMax();
    });
  }

  // ---------------- 皮肤热更新 ----------------
  var revision = null;

  function injectTheme(css) {
    var s = q(THEME_ID);
    if (!s) {
      s = document.createElement("style");
      s.id = THEME_ID;
      (document.head || document.documentElement).appendChild(s);
    }
    s.textContent = css || "";
  }

  function pollTheme() {
    var a = api();
    if (!a || !a.theme_revision || !a.get_full_theme_css) return;
    var p;
    try { p = a.theme_revision(); } catch (e) { return; }
    Promise.resolve(p).then(function (r) {
      if (revision === null) { revision = r; return; }
      if (r === revision) return;
      revision = r;
      return Promise.resolve(a.get_full_theme_css()).then(function (css) {
        injectTheme(css);
        if (typeof CFG.on_skin_change === "function") {
          try { CFG.on_skin_change(); } catch (e) {}
        }
      });
    }).catch(function () {});
  }

  function start() {
    buildBar();
    setInterval(pollTheme, CFG.poll_ms || 1200);
  }

  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start);
})();
