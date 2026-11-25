/* ==============================================================================
 * YisangMirrorFlow 单页前端（web/mod_workflow/app.js）
 * ------------------------------------------------------------------------------
 * 只保留“打包工作流”一个页面；每个包卡片内融合了：
 *   · 打包（zip/bank → carra2/rebank）、解包、添加文件、打开/删除
 *   · “信息”就地填写 mod_info / addon_info（先手动包装）
 *   · “发布”在打包完成后可用：校验必填 → 版本自增 → 上传，日志走模态/浮标
 * 所有后端调用都走同一个 window.pywebview.api（OverviewApi）。
 * ============================================================================== */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  var ui = {
    mark: $("wf-mark"),
    icon: $("wf-icon"),
    version: $("wf-version"),
    list: $("wf-list"),
    count: $("wf-count"),
    gamePath: $("wf-game-path"),
    soundState: $("wf-sound-state"),
    threads: $("wf-threads"),
    modal: $("wf-modal"),
    newName: $("wf-new-name"),
    toast: $("wf-toast")
  };

  var api = null;

  /* ============================================================
     公共
     ============================================================ */
  function invoke(name) {
    var args = Array.prototype.slice.call(arguments, 1);
    if (!api) return Promise.reject(new Error("pywebview 尚未就绪"));
    return api[name].apply(api, args);
  }

  var toastTimer = null;
  function toast(message, isError) {
    if (!ui.toast) return;
    ui.toast.textContent = message || "";
    ui.toast.classList.toggle("err", !!isError);
    ui.toast.hidden = !message;
    if (toastTimer) clearTimeout(toastTimer);
    if (message) {
      toastTimer = setTimeout(function () { ui.toast.hidden = true; }, 3600);
    }
  }

  function errorText(result) {
    if (!result) return "操作失败";
    return result.error || result.message || result.msg || "操作失败";
  }

  function fmtSize(bytes) {
    var n = Number(bytes) || 0;
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
    return (n / 1024 / 1024 / 1024).toFixed(2) + " GB";
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function closeModal(node) {
    // 播放关闭动画后再真正隐藏（.closing 规则见 style.css）
    if (!node || node.hidden || node.classList.contains("closing")) return;
    node.classList.add("closing");
    setTimeout(function () {
      node.classList.remove("closing");
      node.hidden = true;
    }, 150);
  }

  var confirmCb = null;
  function openConfirm(message, onOk) {
    confirmCb = typeof onOk === "function" ? onOk : null;
    var msg = $("confirm-msg");
    if (msg) msg.textContent = message || "";
    var node = $("confirmModal");
    if (node) { node.classList.remove("closing"); node.hidden = false; }
  }

  function closeConfirm() {
    confirmCb = null;
    closeModal($("confirmModal"));
  }

  function showListLoading() {
    if (!ui.list) return;
    ui.list.textContent = "";
    var box = el("div", "wf-loading");
    box.appendChild(el("div", "spinner"));
    box.appendChild(el("div", null, "正在载入本地数据…"));
    ui.list.appendChild(box);
  }

  function fileUrl(path) {
    if (!path) return "";
    try {
      return "file:///" + encodeURI(String(path).replace(/\\/g, "/"));
    } catch (e) {
      return "";
    }
  }

  /* ============================================================
     打包工作流
     ============================================================ */
  var state = null;
  var lastListKey = "";
  var busy = false;
  var startBusy = {};
  var publishBusy = {};

  function statusInfo(pkg) {
    var status = pkg.job && pkg.job.status ? pkg.job.status : "idle";
    if (status === "running") return { text: "打包中", cls: "running" };
    if (status === "done") return { text: "已完成", cls: "done" };
    if (status === "failed") return { text: "失败", cls: "failed" };
    if (status === "interrupted") return { text: "已中断", cls: "interrupted" };
    if (pkg.kind === "addon") return { text: "插件包", cls: "idle" };
    return { text: "待打包", cls: "idle" };
  }

  function listKey(packages) {
    return JSON.stringify(packages.map(function (p) {
      return [
        p.name, p.counts, p.kind,
        (p.info && p.info.name) || "", (p.info && p.info.version) || "",
        (p.icon || "").length,
        p.job && p.job.status, p.job && p.job.message,
        (p.publish_missing || []).join(","), p.publish_ready ? 1 : 0,
        p.last_version || "",
        startBusy[p.name] ? 1 : 0, publishBusy[p.name] ? 1 : 0,
        p.files.map(function (f) { return f.name + ":" + f.size; }).join("|")
      ];
    }));
  }

  function applyState(next) {
    if (!next || !next.ok) {
      if (next && next.error) toast(next.error, true);
      return;
    }
    state = next;

    if (next.icon && ui.icon && !ui.icon.dataset.ready) {
      ui.icon.src = next.icon;
      ui.icon.dataset.ready = "1";
      if (ui.mark) ui.mark.classList.add("has-icon");
    }

    ui.version.textContent = "Mod 打包工作流 · v" + (next.version || "?");
    var game = next.game || {};
    ui.gamePath.value = game.path || "";
    if (game.path && game.sound_exists) {
      ui.soundState.textContent = "音效目录已就绪";
      ui.soundState.className = "wf-state ok";
    } else if (game.path) {
      ui.soundState.textContent = "未找到原版音效目录";
      ui.soundState.className = "wf-state err";
    } else {
      ui.soundState.textContent = "未设置游戏目录";
      ui.soundState.className = "wf-state";
    }

    if (next.threads && document.activeElement !== ui.threads) {
      ui.threads.value = String(next.threads);
    }

    var key = listKey(next.packages || []);
    if (key !== lastListKey) {
      lastListKey = key;
      renderList(next.packages || []);
    }
  }

  function renderList(packages) {
    ui.count.textContent = String(packages.length);
    ui.list.textContent = "";

    if (!packages.length) {
      var empty = el("div", "wf-empty");
      empty.appendChild(el("div", null, "还没有打包包。"));
      empty.appendChild(el("div", null, "点“新建包”，再添加 .zip / .bank 文件；插件包可直接填写信息发布。"));
      ui.list.appendChild(empty);
      return;
    }

    packages.forEach(function (pkg) {
      ui.list.appendChild(renderCard(pkg));
    });
  }

  function renderCard(pkg) {
    var status = statusInfo(pkg);
    var running = pkg.job && pkg.job.status === "running";
    var counts = pkg.counts || {};
    var info = pkg.info || {};

    var card = el("div", "wf-card " + status.cls);

    // ---- 头部：图标 + 名字/版本 + 徽标 ----
    var head = el("div", "wf-card-head");

    var iconWrap = el("div", "wf-card-icon");
    if (pkg.icon) {
      iconWrap.classList.add("has-img");
      var im = el("img");
      im.src = pkg.icon;
      im.alt = "";
      iconWrap.appendChild(im);
    } else {
      iconWrap.textContent = "?";
    }
    head.appendChild(iconWrap);

    var titleBox = el("div", "wf-card-title");
    titleBox.appendChild(el("div", "wf-card-name", info.name || pkg.name));
    if (info.version) titleBox.appendChild(el("div", "wf-card-ver", "v" + info.version));
    head.appendChild(titleBox);

    head.appendChild(el("span", "wf-chip kind", pkg.kind === "addon" ? "插件包" : "Mod 包"));
    head.appendChild(el("span", "wf-chip " + status.cls, status.text));
    card.appendChild(head);

    // ---- 计数 ----
    var meta = el("div", "wf-meta");
    [
      ["zip", counts[".zip"] || 0],
      ["7z", counts[".7z"] || 0],
      ["rar", counts[".rar"] || 0],
      ["bank", counts[".bank"] || 0],
      ["carra2", counts[".carra2"] || 0],
      ["rebank", counts[".rebank"] || 0]
    ].forEach(function (pair) {
      var item = el("span");
      item.appendChild(el("b", null, String(pair[1])));
      item.appendChild(document.createTextNode(" " + pair[0]));
      meta.appendChild(item);
    });
    card.appendChild(meta);

    if (pkg.job && pkg.job.status === "failed" && pkg.job.message) {
      card.appendChild(el("div", "wf-job-msg", pkg.job.message));
    } else if (pkg.job && pkg.job.status === "interrupted") {
      card.appendChild(el("div", "wf-job-msg", "打包进程已退出，请重新开始。"));
    }

    // ---- 文件 ----
    var files = el("div", "wf-files");
    if (!pkg.files || !pkg.files.length) {
      files.appendChild(el("span", "wf-files-empty", "包内暂无打包文件"));
    } else {
      pkg.files.forEach(function (file) {
        var chip = el("span", "wf-file");
        chip.appendChild(el("span", "wf-file-name", file.name));
        chip.appendChild(el("span", "wf-file-size", fmtSize(file.size)));
        if (!running) {
          var remove = el("button", "wf-file-x", "×");
          remove.addEventListener("click", function (event) {
            event.stopPropagation();
            openConfirm("从包中移除 " + file.name + " ？", function () {
              invoke("remove_file", pkg.name, file.name).then(function (result) {
                if (!result.ok) return toast(errorText(result), true);
                applyState(result.state);
              }).catch(function (err) { toast(String(err), true); });
            });
          });
          chip.appendChild(remove);
        }
        files.appendChild(chip);
      });
    }
    card.appendChild(files);

    // ---- 操作 ----
    var actions = el("div", "wf-card-actions");

    var start = el("button", "wf-btn primary", status.cls === "done" ? "重新打包" : "开始打包");
    start.disabled = !pkg.can_start || running || !!startBusy[pkg.name];
    start.addEventListener("click", function () {
      startBusy[pkg.name] = true;
      start.disabled = true;
      invoke("start_package", pkg.name).then(function (result) {
        delete startBusy[pkg.name];
        if (!result.ok) {
          toast(errorText(result), true);
          applyState(result.state);
          return;
        }
        toast("已开始打包: " + pkg.name);
        applyState(result.state);
      }).catch(function (err) {
        delete startBusy[pkg.name];
        start.disabled = false;
        toast(String(err), true);
      });
    });
    actions.appendChild(start);

    var add = el("button", "wf-btn", "添加文件");
    add.disabled = running;
    add.addEventListener("click", function () {
      invoke("add_files", pkg.name).then(function (result) {
        if (result.canceled) return;
        if (!result.ok) return toast(errorText(result), true);
        var msg = "已导入 " + result.added + " 个文件";
        if (result.unpacked && result.unpacked.length) {
          msg += "，自动解包 " + result.unpacked.length + " 个归档";
        }
        var hasErr = false;
        if (result.skipped && result.skipped.length) {
          msg += "，跳过: " + result.skipped.join(", ");
          hasErr = true;
        }
        if (result.errors && result.errors.length) {
          msg += "；" + result.errors.join("；");
          hasErr = true;
        }
        toast(msg, hasErr);
        applyState(result.state);
      }).catch(function (err) { toast(String(err), true); });
    });
    actions.appendChild(add);

    actions.appendChild(el("span", "wf-spacer"));

    var open = el("button", "wf-btn ghost", "打开目录");
    open.addEventListener("click", function () {
      invoke("open_package", pkg.name).then(function (result) {
        if (!result.ok) toast(errorText(result), true);
      }).catch(function (err) { toast(String(err), true); });
    });
    actions.appendChild(open);

    // 信息（就地包装）：填 mod_info / addon_info + 图标
    var infoBtn = el("button", "wf-btn ghost", "信息");
    infoBtn.addEventListener("click", function () { openInfo(pkg.name); });
    actions.appendChild(infoBtn);

    // 删除
    var del = el("button", "wf-btn ghost danger", "删除");
    del.disabled = running;
    del.addEventListener("click", function () {
      openConfirm("删除包 " + pkg.name + " 及其中的文件？此操作不可撤销。", function () {
        invoke("delete_package", pkg.name).then(function (result) {
          if (!result.ok) return toast(errorText(result), true);
          toast("已删除: " + pkg.name);
          applyState(result.state);
        }).catch(function (err) { toast(String(err), true); });
      });
    });
    actions.appendChild(del);

    // 发布（删除右侧）：打包完成（插件包免打包）才可点；点击前先校验必填
    var pub = el("button", "wf-btn primary", "发布");
    pub.disabled = running || !!publishBusy[pkg.name] || !pkg.publish_ready;
    if (!running && !pkg.publish_ready) {
      pub.title = pkg.kind === "addon" ? "正在处理，稍候" : "请先完成打包";
    }
    pub.addEventListener("click", function () {
      var missing = pkg.publish_missing || [];
      if (missing.length) {
        toast("请先补全信息：" + missing.join("、"), true);
        openInfo(pkg.name);
        return;
      }
      startPublish(pkg.name);
    });
    actions.appendChild(pub);

    card.appendChild(actions);
    return card;
  }

  function refresh() {
    if (busy || !api) return Promise.resolve();
    if (document.hidden) return Promise.resolve();
    busy = true;
    return invoke("get_state").then(function (result) {
      busy = false;
      applyState(result);
    }).catch(function (err) {
      busy = false;
      toast(String(err), true);
    });
  }

  function setKind(kind) {
    document.querySelectorAll(".wf-kind").forEach(function (b) {
      b.classList.toggle("active", b.dataset.kind === kind);
    });
  }

  function getKind() {
    var b = document.querySelector(".wf-kind.active");
    return b ? b.dataset.kind : "mod";
  }

  function openNewModal() {
    ui.modal.classList.remove("closing");
    ui.modal.hidden = false;
    ui.newName.value = "新包";
    setKind("mod");
    setTimeout(function () {
      ui.newName.focus();
      ui.newName.select();
    }, 30);
  }

  function closeNewModal() {
    closeModal(ui.modal);
  }

  function createPackage() {
    var name = ui.newName.value.trim();
    var kind = getKind();
    invoke("create_package", name, kind).then(function (result) {
      if (!result.ok) return toast(errorText(result), true);
      closeNewModal();
      toast("已创建" + (kind === "addon" ? "插件包" : "包") + ": " + result.name);
      applyState(result.state);
    }).catch(function (err) { toast(String(err), true); });
  }

  /* ============================================================
     包信息模态（先手动包装再发布）
     ============================================================ */
  var infoCtx = { name: "", iconPath: "" };
  var authorsMap = {};

  function setInfoIcon(uri) {
    var img = $("info-icon-img"), plus = $("info-icon-plus"), btn = $("info-icon");
    if (!img || !btn) return;
    if (uri) {
      img.src = uri;
      img.hidden = false;
      if (plus) plus.hidden = true;
      btn.classList.add("has-icon");
    } else {
      img.hidden = true;
      img.removeAttribute("src");
      if (plus) plus.hidden = false;
      btn.classList.remove("has-icon");
    }
  }

  function renderAuthors() {
    var box = $("info-authors");
    if (!box) return;
    box.textContent = "";
    var keys = Object.keys(authorsMap);
    if (!keys.length) {
      box.appendChild(el("div", "author-empty", "还没有作者，点下方添加"));
      return;
    }
    keys.forEach(function (name) {
      var row = el("div", "author-item");
      row.appendChild(el("span", "an", name));
      row.appendChild(el("span", "al", authorsMap[name] || "(无链接)"));
      var x = el("button", "ax", "×");
      x.type = "button";
      x.addEventListener("click", function () {
        delete authorsMap[name];
        renderAuthors();
      });
      row.appendChild(x);
      box.appendChild(row);
    });
  }

  async function openInfo(name) {
    infoCtx = { name: name, iconPath: "" };
    var modal = $("infoModal");
    modal.classList.remove("closing");
    modal.hidden = false;
    $("info-loading").hidden = false;
    $("info-body").hidden = true;
    try {
      var r = await invoke("get_package_info", name);
      if (!r.ok) {
        toast(errorText(r), true);
        closeModal(modal);
        return;
      }
      $("info-title").textContent = r.kind === "addon" ? "插件包信息" : "Mod 包信息";
      $("info-name").value = (r.info && r.info.name) || "";
      $("info-desc").value = (r.info && r.info.desc) || "";
      $("info-version").value = (r.info && r.info.version) || "0.0.1";

      authorsMap = {};
      var authors = (r.info && r.info.authors) || {};
      if (Array.isArray(authors)) {
        authors.forEach(function (k) {
          if (typeof k === "string") authorsMap[k] = "";
        });
      } else if (authors && typeof authors === "object") {
        Object.keys(authors).forEach(function (k) { authorsMap[k] = authors[k] || ""; });
      }
      renderAuthors();
      setInfoIcon(r.icon);
      $("info-hint").textContent = (r.missing && r.missing.length)
        ? ("待补全：" + r.missing.join("、")) : "";
      $("info-loading").hidden = true;
      $("info-body").hidden = false;
    } catch (e) {
      toast(String(e), true);
      $("info-loading").hidden = true;
      $("info-body").hidden = false;
    }
  }

  async function saveInfo() {
    var name = infoCtx.name;
    if (!name) return;
    var data = {
      name: $("info-name").value.trim(),
      desc: $("info-desc").value.trim(),
      version: $("info-version").value.trim() || "0.0.1",
      authors: authorsMap,
      icon_path: infoCtx.iconPath || ""
    };
    try {
      var r = await invoke("save_package_info", name, data);
      if (!r.ok) { toast(errorText(r), true); return; }
      toast("信息已保存");
      closeModal($("infoModal"));
      if (r.state) applyState(r.state);
    } catch (e) {
      toast(String(e), true);
    }
  }

  /* ---- 作者子模态 ---- */
  function openAuthorModal() {
    $("author-name").value = "";
    $("author-link").value = "";
    $("authorModal").classList.remove("closing");
    $("authorModal").hidden = false;
    setTimeout(function () { $("author-name").focus(); }, 30);
  }

  function confirmAuthor() {
    var name = $("author-name").value.trim();
    if (!name) { toast("请填写作者名字", true); return; }
    authorsMap[name] = $("author-link").value.trim();
    renderAuthors();
    closeModal($("authorModal"));
  }

  /* ============================================================
     发布日志（模态 + 右下角浮标）
     ============================================================ */
  var logResultText = "";

  function openLog(title) {
    $("log-title").textContent = title || "发布日志";
    $("log-fill").style.width = "0%";
    $("log-status").textContent = "准备中...";
    $("log-text").textContent = "";
    logResultText = "";
    $("logModal").classList.remove("closing");
    $("logModal").hidden = false;
    $("logFloat").hidden = true;
  }

  function minimizeLog() {
    $("logModal").hidden = true;
    var txt = $("log-status").textContent || "发布中...";
    $("log-float-text").textContent = txt;
    $("logFloat").hidden = false;
  }

  function restoreLog() {
    $("logFloat").hidden = true;
    $("logModal").hidden = false;
  }

  function closeLog() {
    closeModal($("logModal"));
    $("logFloat").hidden = true;
  }

  // Python 侧通过 evaluate_js 推送进度/日志
  window.__onPublishProgress = function (p) {
    var pct = Math.max(0, Math.min(100, Math.round((p && p.percent) || 0)));
    var text = (p && p.text) || "";
    var fill = $("log-fill");
    if (fill) fill.style.width = pct + "%";
    var st = $("log-status");
    if (st) st.textContent = text + " " + pct + "%";
    if ($("logModal") && $("logModal").hidden) {
      $("log-float-text").textContent = (text || "发布中") + " " + pct + "%";
      $("logFloat").hidden = false;
    }
  };

  window.__onPublishLog = function (s) {
    var t = $("log-text");
    if (!t) return;
    t.textContent += (t.textContent ? "\n" : "") + String(s);
    t.scrollTop = t.scrollHeight;
    logResultText = t.textContent;
  };

  async function startPublish(name) {
    publishBusy[name] = true;
    lastListKey = "";
    refresh();
    openLog("发布 - " + name);
    try {
      var r = await invoke("publish_package", name);
      var t = $("log-text");
      if (r.log) t.textContent = r.log;
      $("log-fill").style.width = r.ok ? "100%" : "0%";
      $("log-status").textContent = r.ok
        ? ("发布完成 · v" + (r.version || ""))
        : (r.msg || "发布失败");
      if (r.ok) toast("发布成功: " + name);
      else toast(r.msg || "发布失败", true);
      if ($("logModal").hidden) {
        $("log-float-text").textContent = r.ok ? ("完成 v" + (r.version || "")) : (r.msg || "失败");
        $("logFloat").hidden = false;
      }
      if (r.state) applyState(r.state);
    } catch (e) {
      $("log-status").textContent = "发布失败: " + errorText(e);
      toast(String(e), true);
    } finally {
      delete publishBusy[name];
      lastListKey = "";
      refresh();
    }
  }

  /* ============================================================
     绑定 & 启动
     ============================================================ */
  function bindWorkflow() {
    $("wf-new").addEventListener("click", openNewModal);
    document.querySelectorAll(".wf-kind").forEach(function (b) {
      b.addEventListener("click", function () { setKind(b.dataset.kind); });
    });
    $("wf-new-cancel").addEventListener("click", closeNewModal);
    $("wf-new-confirm").addEventListener("click", createPackage);
    ui.newName.addEventListener("keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); createPackage(); }
      else if (event.key === "Escape") { closeNewModal(); }
    });
    ui.modal.addEventListener("mousedown", function (event) {
      if (event.target === ui.modal) closeNewModal();
    });

    $("wf-refresh").addEventListener("click", function () {
      lastListKey = "";
      refresh();
    });

    $("wf-open-mods").addEventListener("click", function () {
      invoke("open_mods_dir").then(function (result) {
        if (!result.ok) toast(errorText(result), true);
      }).catch(function (err) { toast(String(err), true); });
    });

    $("wf-pick-game").addEventListener("click", function () {
      invoke("pick_game_dir").then(function (result) {
        if (result.canceled) return;
        if (!result.ok) return toast(errorText(result), true);
        applyState(result.state);
        if (result.game && result.game.sound_exists) toast("游戏目录已保存");
        else toast("已保存，但没有找到原版音效目录", true);
      }).catch(function (err) { toast(String(err), true); });
    });

    ui.gamePath.addEventListener("change", function () {
      invoke("set_game_path", ui.gamePath.value).then(function (result) {
        if (!result.ok) return toast(errorText(result), true);
        applyState(result.state);
      }).catch(function (err) { toast(String(err), true); });
    });

    ui.threads.addEventListener("change", function () {
      invoke("set_threads", ui.threads.value).then(function (result) {
        if (!result.ok) return toast(errorText(result), true);
        ui.threads.value = String(result.threads);
        toast("线程数已保存: " + result.threads);
      }).catch(function (err) { toast(String(err), true); });
    });
  }

  function bindModals() {
    // 信息模态
    $("info-close").addEventListener("click", function () { closeModal($("infoModal")); });
    $("info-cancel").addEventListener("click", function () { closeModal($("infoModal")); });
    $("info-save").addEventListener("click", saveInfo);
    $("info-icon").addEventListener("click", async function () {
      try {
        var path = await invoke("pick_icon");
        if (!path) return;
        infoCtx.iconPath = path;
        // 用后端读成 data URI 预览，避免 file:// 破图/缓存问题
        var d = await invoke("read_image_data_uri", path);
        if (d && d.ok && d.uri) setInfoIcon(d.uri);
        else { setInfoIcon(""); toast((d && d.error) || "无法预览该图片", true); }
      } catch (e) { toast(String(e), true); }
    });
    $("info-add-author").addEventListener("click", openAuthorModal);
    $("infoModal").addEventListener("mousedown", function (event) {
      if (event.target === $("infoModal")) closeModal($("infoModal"));
    });

    // 作者模态
    $("author-close").addEventListener("click", function () { closeModal($("authorModal")); });
    $("author-cancel").addEventListener("click", function () { closeModal($("authorModal")); });
    $("author-add").addEventListener("click", confirmAuthor);
    $("author-link").addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); confirmAuthor(); }
    });
    $("authorModal").addEventListener("mousedown", function (event) {
      if (event.target === $("authorModal")) closeModal($("authorModal"));
    });

    // 日志模态 + 浮标
    $("log-min").addEventListener("click", minimizeLog);
    $("log-close").addEventListener("click", closeLog);
    $("log-float-open").addEventListener("click", function (e) { e.stopPropagation(); restoreLog(); });
    $("logFloat").addEventListener("click", restoreLog);

    // 自定义确认模态
    $("confirm-ok").addEventListener("click", function () {
      var cb = confirmCb;
      closeConfirm();
      if (cb) { try { cb(); } catch (e) {} }
    });
    $("confirm-cancel").addEventListener("click", closeConfirm);
    $("confirmModal").addEventListener("mousedown", function (event) {
      if (event.target === $("confirmModal")) closeConfirm();
    });
  }

  function boot() {
    api = window.pywebview && window.pywebview.api;
    if (!api) return;
    bindWorkflow();
    bindModals();
    showListLoading();
    refresh();
    setInterval(refresh, 1400);
  }

  if (window.pywebview && window.pywebview.api) {
    boot();
  } else {
    window.addEventListener("pywebviewready", boot, { once: true });
  }
})();
