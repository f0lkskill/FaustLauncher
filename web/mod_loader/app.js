/* ============================================================
   Mod 加载器进度页 —— 前端逻辑 (web/mod_loader/app.js)

   设计要点 (相比 tkinter 版卡顿的根源):
     1. 每 200ms 拉一次 get_state(), 但**只动变化的节点**:
        日志用「重叠 diff」只 append / 移除最少节点, 阶段只切 class,
        线程行按名字复用 DOM, 不整块重建, 不闪烁。
     2. 所有过渡交给 CSS (进度条 width、阶段 highlight), JS 不做动画。
     3. 请求串行化: 上一帧没回来就不再发, 慢机器上也不会堆积。
   ============================================================ */
(function () {
  "use strict";

  var POLL_MS = 200;
  var READY_RETRY_MS = 60;

  var $ = function (id) { return document.getElementById(id); };

  var ui = {
    icon: $("ml-icon"),
    logo: document.querySelector(".ml-logo"),
    title: $("ml-title"),
    sub: $("ml-sub"),
    chip: $("ml-chip"),
    bar: $("ml-bar"),
    barTrack: $("ml-bar-track"),
    stageLabel: $("ml-stage-label"),
    pct: $("ml-pct"),
    steps: $("ml-steps"),
    threadCount: $("ml-thread-count"),
    threads: $("ml-threads"),
    logCount: $("ml-log-count"),
    log: $("ml-log"),
    footStatus: $("ml-foot-status"),
    footHint: $("ml-foot-hint"),
    close: $("ml-close")
  };

  // ---- 已渲染状态 (用于 diff) ----
  var cache = {
    kind: null,
    stageNo: -1,
    pct: -1,
    stages: [],       // [{n, state, node}]
    stepNodes: [],    // 按序号索引的节点
    threadNodes: {},  // name -> {node, note, stage}
    logs: [],         // [{text, level}] 上一帧的原始数据
    iconShown: false,
    closeShown: false,
    busy: false
  };

  // ============================================================
  // 文案
  // ============================================================
  function headline(state) {
    if (state.error) return "加载失败";
    if (state.kind === "launch") return "游戏已启动";
    if (state.kind === "restore") return "正在恢复原版文件";
    return "正在加载模组";
  }

  function chipInfo(state) {
    if (state.error) return { text: "出错", cls: "err", bar: "err" };
    if (state.kind === "launch") return { text: "已启动", cls: "ok", bar: "ok" };
    if (state.kind === "restore") return { text: "恢复中", cls: "running", bar: "run" };
    if (!state.pid) return { text: "加载中", cls: "running", bar: "run" };
    return { text: "加载中", cls: "running", bar: "run" };
  }

  function hintInfo(state) {
    if (state.error) return state.error;
    if (state.kind === "launch") return "游戏退出后会自动恢复原版文件";
    if (state.kind === "restore") return "恢复完成后窗口会自动关闭";
    return "";
  }

  // ============================================================
  // 渲染: 头部 / 进度条
  // ============================================================
  function renderHeader(state) {
    var chip = chipInfo(state);

    if (cache.kind !== state.kind || cache.errorText !== state.error) {
      cache.kind = state.kind;
      cache.errorText = state.error;
      ui.title.textContent = headline(state);
      ui.chip.textContent = chip.text;
      ui.chip.className = "ml-chip " + chip.cls;
      ui.bar.className = "ml-bar " + chip.bar;
      ui.footHint.textContent = hintInfo(state);
    }

    var sub = state.stage_text || "准备中…";
    if (ui.sub.textContent !== sub) ui.sub.textContent = sub;

    var pct = Math.max(0, Math.min(100, state.pct || 0));
    if (pct !== cache.pct) {
      cache.pct = pct;
      ui.bar.style.width = pct.toFixed(1) + "%";
      ui.pct.textContent = pct.toFixed(0) + "%";
    }

    var label = state.stage_no > 0 ? ("阶段 " + state.stage_no + " / 6") : "准备中";
    if (ui.stageLabel.textContent !== label) ui.stageLabel.textContent = label;

    if (state.icon && !cache.iconShown) {
      cache.iconShown = true;
      ui.icon.src = state.icon;
      ui.logo.classList.add("has-icon");
    }
  }

  // ============================================================
  // 渲染: 阶段条 (首次建节点, 之后只切 class)
  // ============================================================
  function renderStages(stages) {
    if (!stages || !stages.length) return;

    if (!cache.stepNodes.length) {
      var frag = document.createDocumentFragment();
      stages.forEach(function (s) {
        var box = document.createElement("div");
        box.className = "ml-step";
        var dot = document.createElement("span");
        dot.className = "ml-step-dot";
        dot.textContent = "✓";
        var txt = document.createElement("span");
        txt.className = "ml-step-text";
        txt.textContent = s.title;
        box.appendChild(dot);
        box.appendChild(txt);
        frag.appendChild(box);
        cache.stepNodes.push(box);
      });
      ui.steps.appendChild(frag);
    }

    stages.forEach(function (s, i) {
      var node = cache.stepNodes[i];
      if (!node) return;
      var cls = "ml-step" + (s.state === "pending" ? "" : " " + s.state);
      if (node.className !== cls) node.className = cls;
      // 未开始的阶段显示序号, 完成的显示对勾的 dot 文本
      var dot = node.firstChild;
      var mark = s.state === "pending" ? String(s.n) : "✓";
      if (dot.textContent !== mark) dot.textContent = mark;
    });
  }

  // ============================================================
  // 渲染: 线程列表 (按 name 复用节点)
  // ============================================================
  function renderThreads(threads) {
    threads = threads || [];
    if (ui.threadCount.textContent !== String(threads.length)) {
      ui.threadCount.textContent = String(threads.length);
    }

    if (!threads.length) {
      if (!ui.threads.querySelector(".ml-empty")) {
        ui.threads.innerHTML = '<div class="ml-empty">暂无活跃线程</div>';
      }
      cache.threadNodes = {};
      return;
    }
    var empty = ui.threads.querySelector(".ml-empty");
    if (empty) empty.remove();

    var seen = {};
    threads.forEach(function (t) {
      seen[t.name] = true;
      var entry = cache.threadNodes[t.name];
      var note = [t.stage, t.description].filter(Boolean).join(" · ");

      if (!entry) {
        var row = document.createElement("div");
        row.className = "ml-thread";
        var dot = document.createElement("span");
        dot.className = "ml-thread-dot";
        var name = document.createElement("span");
        name.className = "ml-thread-name";
        name.textContent = t.name;
        name.title = t.name;
        var noteEl = document.createElement("span");
        noteEl.className = "ml-thread-note";
        noteEl.textContent = note;
        row.appendChild(dot);
        row.appendChild(name);
        row.appendChild(noteEl);
        ui.threads.appendChild(row);
        cache.threadNodes[t.name] = { node: row, note: noteEl };
      } else if (entry.note.textContent !== note) {
        entry.note.textContent = note;
      }
    });

    Object.keys(cache.threadNodes).forEach(function (name) {
      if (!seen[name]) {
        cache.threadNodes[name].node.remove();
        delete cache.threadNodes[name];
      }
    });
  }

  // ============================================================
  // 渲染: 日志 (重叠 diff —— 只 append/移除最少节点)
  // ============================================================
  function overlap(prev, next) {
    // 找最大 k: prev 的后 k 条 == next 的前 k 条
    var max = Math.min(prev.length, next.length);
    for (var k = max; k > 0; k--) {
      var ok = true;
      for (var i = 0; i < k; i++) {
        if (prev[prev.length - k + i].text !== next[i].text) { ok = false; break; }
      }
      if (ok) return k;
    }
    return 0;
  }

  // 日志格式: "2026-10-15 14:04:17,615 [INFO] xxx" (无时间戳的行原样显示)
  var TS_RE = /^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[,.]\d{3})\s*(?:\[([A-Za-z]+)\])?\s*([\s\S]*)$/;

  function makeLogLine(item, animate) {
    var line = document.createElement("div");
    line.className = "ml-line " + (item.level || "info") + (animate ? " is-new" : "");

    var text = item.text || "";
    var m = TS_RE.exec(text);
    var ts = m ? m[1].replace("T", " ").replace(".", ",") : "";
    var lv = m ? (m[2] || "") : "";
    var msg = m ? (m[3] || "") : text;

    if (ts) {
      var tsEl = document.createElement("span");
      tsEl.className = "ml-ts";
      tsEl.textContent = ts;
      line.appendChild(tsEl);
    }
    if (lv) {
      var lvEl = document.createElement("span");
      lvEl.className = "ml-lv";
      lvEl.textContent = lv;
      line.appendChild(lvEl);
    }
    var msgEl = document.createElement("span");
    msgEl.className = "ml-msg";
    msgEl.textContent = msg;
    line.appendChild(msgEl);
    return line;
  }

  function renderLogs(lines) {
    lines = lines || [];
    var box = ui.log;

    if (ui.logCount.textContent !== String(lines.length)) {
      ui.logCount.textContent = String(lines.length);
    }

    // 必须在改动 DOM **之前**测量: 追加日志后 scrollHeight 已经变大,
    // 那时再判断会把"本来贴着底部"误判成"用户上滚了"(旧版日志不自动滚的根因)。
    var hadContent = cache.logs.length > 0;
    var stick = !hadContent ||
      (box.scrollHeight - box.scrollTop - box.clientHeight < 32);

    var k = overlap(cache.logs, lines);
    var removeCount = cache.logs.length - k;
    var addItems = lines.slice(k);

    if (!removeCount && !addItems.length) return;

    var i;
    for (i = 0; i < removeCount; i++) {
      if (box.firstChild) box.removeChild(box.firstChild);
    }

    if (addItems.length) {
      var frag = document.createDocumentFragment();
      var animateFrom = addItems.length > 12 ? addItems.length - 12 : 0;
      for (i = 0; i < addItems.length; i++) {
        frag.appendChild(makeLogLine(addItems[i], i >= animateFrom));
      }
      box.appendChild(frag);
    }

    cache.logs = lines;
    if (stick) {
      box.scrollTop = box.scrollHeight;
      // 首帧/内容不足一屏时, 布局尚未稳定, 下一帧再贴一次底
      requestAnimationFrame(function () { box.scrollTop = box.scrollHeight; });
    }
  }

  // ============================================================
  // 主循环
  // ============================================================
  function renderFooter(state) {
    var s = ((state.elapsed_ms || 0) / 1000).toFixed(1);
    var text = "已运行 " + s + "s";
    if (ui.footStatus.textContent !== text) ui.footStatus.textContent = text;

    var show = !!(state.error || state.done);
    if (show !== cache.closeShown) {
      cache.closeShown = show;
      ui.close.hidden = !show;
    }
  }

  function apply(state) {
    if (!state) return;
    renderHeader(state);
    renderStages(state.stages);
    renderThreads(state.threads);
    renderLogs(state.log);
    renderFooter(state);
  }

  function poll() {
    if (cache.busy) return;
    var api = window.pywebview && window.pywebview.api;
    if (!api || !api.get_state) {
      setTimeout(poll, READY_RETRY_MS);
      return;
    }
    cache.busy = true;
    api.get_state().then(function (state) {
      cache.busy = false;
      apply(state);
    }).catch(function (err) {
      cache.busy = false;
      console.warn("[Mod加载器] get_state 失败:", err);
    });
  }

  // ---- 交互 ----
  ui.close.addEventListener("click", function () {
    var api = window.pywebview && window.pywebview.api;
    if (api && api.close) api.close();
  });

  // 首帧: 立刻渲染一次, 之后固定节奏轮询 (setTimeout 链, 慢机器上不堆积)
  function loop() {
    poll();
    setTimeout(loop, POLL_MS);
  }
  loop();
})();
