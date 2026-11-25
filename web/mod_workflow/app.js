/* ==============================================================================
 * YisangMirrorFlow 合并前端（web/mod_workflow/app.js）
 * ------------------------------------------------------------------------------
 * 一个 pywebview 窗口里分两页，共用常驻头部（品牌 + 页面切换）：
 *   · 打包工作流：包列表 / 新建 / 添加文件 / 解包 / 开始打包（轮询 .workflow_job.json）
 *   · 扩展工具：包装 Mod / 生成插件模板 / 发布 Mod·插件（原 web/extension_tools）
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
    foot: $("wf-foot-text"),
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

  /* ============================================================
     页面切换（常驻头部）
     ============================================================ */
  var currentPage = "workflow";
  var extInited = false;

  function switchPage(name) {
    currentPage = name;
    document.querySelectorAll(".wf-pagetab").forEach(function (t) {
      t.classList.toggle("active", t.dataset.page === name);
    });
    for (const [key, id] of Object.entries({ workflow: "page-workflow", ext: "page-ext" })) {
      var node = $(id);
      if (node) node.classList.toggle("show", key === name);
    }
    if (name === "ext" && !extInited) {
      extInited = true;
      initExtension();
    }
    if (name === "workflow") {
      lastListKey = "";
      refresh();
    }
  }

  function bindPageswitch() {
    document.querySelectorAll(".wf-pagetab").forEach(function (t) {
      t.addEventListener("click", function () { switchPage(t.dataset.page); });
    });
  }

  /* ============================================================
     Workflow 页面
     ============================================================ */
  var state = null;
  var lastListKey = "";
  var busy = false;
  var startBusy = {};
  var unpackBusy = {};

  function statusInfo(pkg) {
    var status = pkg.job && pkg.job.status ? pkg.job.status : "idle";
    if (status === "running") return { text: "打包中", cls: "running" };
    if (status === "done") return { text: "已完成", cls: "done" };
    if (status === "failed") return { text: "失败", cls: "failed" };
    if (status === "interrupted") return { text: "已中断", cls: "interrupted" };
    return { text: "待打包", cls: "idle" };
  }

  function listKey(packages) {
    return JSON.stringify(packages.map(function (p) {
      return [
        p.name, p.counts,
        p.files.map(function (f) { return f.name + ":" + f.size; }).join("|"),
        p.job && p.job.status,
        p.job && p.job.message,
        startBusy[p.name] ? 1 : 0,
        unpackBusy[p.name] ? 1 : 0
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

    ui.version.textContent = "Mod 打包工作流 · 扩展工具 · v" + (next.version || "?");
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
      empty.appendChild(el("div", null, "点“新建包”，再添加 .zip / .bank 文件。"));
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

    var card = el("div", "wf-card " + status.cls);

    var head = el("div", "wf-card-head");
    head.appendChild(el("div", "wf-card-name", pkg.name));
    head.appendChild(el("span", "wf-chip " + status.cls, status.text));
    card.appendChild(head);

    var meta = el("div", "wf-meta");
    [
      ["zip", counts[".zip"] || 0],
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

    var files = el("div", "wf-files");
    if (!pkg.files || !pkg.files.length) {
      files.appendChild(el("span", "wf-files-empty", "包内暂无文件"));
    } else {
      pkg.files.forEach(function (file) {
        var chip = el("span", "wf-file");
        chip.appendChild(el("span", "wf-file-name", file.name));
        chip.appendChild(el("span", "wf-file-size", fmtSize(file.size)));
        if (!running) {
          var remove = el("button", "wf-file-x", "×");
          remove.addEventListener("click", function (event) {
            event.stopPropagation();
            if (!confirm("从包中移除 " + file.name + " ？")) return;
            invoke("remove_file", pkg.name, file.name).then(function (result) {
              if (!result.ok) return toast(errorText(result), true);
              applyState(result.state);
            }).catch(function (err) { toast(String(err), true); });
          });
          chip.appendChild(remove);
        }
        files.appendChild(chip);
      });
    }
    card.appendChild(files);

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

    var unpack = el("button", "wf-btn", "解包");
    unpack.disabled = running || !!unpackBusy[pkg.name] || !(counts[".zip"] > 0);
    unpack.addEventListener("click", function () {
      if (!confirm("将解压包内全部 zip，重复文件会覆盖，继续？")) return;
      unpackBusy[pkg.name] = true;
      unpack.disabled = true;
      invoke("unpack_zips", pkg.name).then(function (result) {
        delete unpackBusy[pkg.name];
        if (!result.ok) {
          toast(errorText(result), true);
          refresh();
          return;
        }
        var msg = "解包完成: " + result.unpacked + "/" + result.zip_count + " 个 zip";
        if (result.extracted_files) msg += "，共 " + result.extracted_files + " 个文件";
        if (result.errors && result.errors.length) {
          msg += "；" + result.errors.join("；");
          toast(msg, true);
        } else {
          toast(msg);
        }
        if (result.state) applyState(result.state);
        else refresh();
      }).catch(function (err) {
        delete unpackBusy[pkg.name];
        toast(String(err), true);
        refresh();
      });
    });
    actions.appendChild(unpack);

    var add = el("button", "wf-btn", "添加文件");
    add.disabled = running;
    add.addEventListener("click", function () {
      invoke("add_files", pkg.name).then(function (result) {
        if (result.canceled) return;
        if (!result.ok) return toast(errorText(result), true);
        var msg = "已添加 " + result.added + " 个文件";
        if (result.skipped && result.skipped.length) {
          msg += "，跳过: " + result.skipped.join(", ");
        }
        toast(msg, !!(result.skipped && result.skipped.length));
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

    var del = el("button", "wf-btn ghost danger", "删除");
    del.disabled = running;
    del.addEventListener("click", function () {
      if (!confirm("删除包 " + pkg.name + " 及其中的文件？此操作不可撤销。")) return;
      invoke("delete_package", pkg.name).then(function (result) {
        if (!result.ok) return toast(errorText(result), true);
        toast("已删除: " + pkg.name);
        applyState(result.state);
      }).catch(function (err) { toast(String(err), true); });
    });
    actions.appendChild(del);

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

  function openNewModal() {
    ui.modal.hidden = false;
    ui.newName.value = "新包";
    setTimeout(function () {
      ui.newName.focus();
      ui.newName.select();
    }, 30);
  }

  function closeNewModal() {
    ui.modal.hidden = true;
  }

  function createPackage() {
    var name = ui.newName.value.trim();
    invoke("create_package", name).then(function (result) {
      if (!result.ok) return toast(errorText(result), true);
      closeNewModal();
      toast("已创建包: " + result.name);
      applyState(result.state);
    }).catch(function (err) { toast(String(err), true); });
  }

  function bindWorkflow() {
    $("wf-new").addEventListener("click", openNewModal);
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
        if (result.game && result.game.sound_exists) {
          toast("游戏目录已保存");
        } else {
          toast("已保存，但没有找到原版音效目录", true);
        }
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

  /* ============================================================
     Extension 页面（原 web/extension_tools）
     ============================================================ */
  function exSetMsg(text, isErr) {
    var m = $("ex-msg");
    if (!m) return;
    m.textContent = text || "";
    m.className = "msg" + (isErr ? " err" : "");
  }

  function errTextLocal(e) {
    return (e && (e.message || e)) || e;
  }

  function parseTagList(value) {
    var source = Array.isArray(value) ? value : String(value || "").split(/[,，\n\r]+/);
    var result = [];
    var seen = new Set();
    source.forEach(function (raw) {
      if (typeof raw !== "string") return;
      var tag = raw.trim();
      if (!tag || tag.length > 32 || seen.has(tag) || result.length >= 8) return;
      seen.add(tag);
      result.push(tag);
    });
    return result;
  }

  function parseTagsStyleInput(inputId) {
    var text = $(inputId).value.trim();
    if (!text) return null;
    var parsed;
    try {
      parsed = JSON.parse(text);
    } catch (e) {
      throw new Error("标签颜色必须是合法 JSON 对象");
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("标签颜色必须是 JSON 对象");
    }
    return parsed;
  }

  var secIds = { "1": "sec-wrap", "2": "sec-plugin", "3": "sec-publish", "4": "sec-addon-publish" };

  function switchMode(mode) {
    document.querySelectorAll("#page-ext .tab").forEach(function (t) {
      t.classList.toggle("active", t.dataset.mode === mode);
    });
    for (var m in secIds) {
      if (Object.prototype.hasOwnProperty.call(secIds, m)) {
        $(secIds[m]).classList.toggle("show", m === mode);
      }
    }
    exSetMsg("");
    if (mode === "1") { fillModsSelect("wrap-mods", false); }
    if (mode === "3") { fillModsSelect("pub-mods", true); }
    if (mode === "4") { fillAddonsSelect("addon-pub-addons", true); }
  }

  async function fillModsSelect(selId, wrappedOnly) {
    try {
      var mods = await invoke("list_mods");
      var sel = $(selId);
      var prev = sel.value;
      sel.innerHTML = "";
      var usable = (mods || []).filter(function (m) { return !wrappedOnly || m.wrapped; });
      if (!usable.length) {
        var o = document.createElement("option");
        o.value = "";
        o.textContent = wrappedOnly ? "(mods/ 下暂无已包装 Mod)" : "(mods/ 下没有文件夹)";
        sel.appendChild(o);
        return;
      }
      usable.forEach(function (m) {
        var op = document.createElement("option");
        op.value = m.path;
        op.textContent = m.wrapped ? m.name : m.name + " (未打包)";
        sel.appendChild(op);
      });
      if (prev) sel.value = prev;
    } catch (e) {
      console.error(e);
    }
  }

  async function fillAddonsSelect(selId, usableOnly) {
    try {
      var addons = await invoke("list_addons");
      var sel = $(selId);
      if (!sel) return;
      var prev = sel.value;
      sel.innerHTML = "";
      var usable = (addons || []).filter(function (a) { return !usableOnly || a.wrapped; });
      if (!usable.length) {
        var o = document.createElement("option");
        o.value = "";
        o.textContent = usableOnly ? "(addons/ 下暂无含 addon_info.json 的插件)" : "(addons/ 下没有文件夹)";
        sel.appendChild(o);
        return;
      }
      usable.forEach(function (a) {
        var op = document.createElement("option");
        op.value = a.path;
        op.textContent = a.wrapped ? a.name : a.name + " (缺 addon_info.json)";
        sel.appendChild(op);
      });
      if (prev) sel.value = prev;
    } catch (e) {
      console.error(e);
    }
  }

  async function pickFolderAndSet(inputId, scanFn) {
    try {
      var path = await invoke("pick_folder");
      if (!path) return;
      $(inputId).value = path;
      if (scanFn) await scanFn(path);
    } catch (e) {
      exSetMsg("选择文件夹失败: " + errTextLocal(e), true);
    }
  }

  async function chooseFromMods(inputId, scanFn) {
    var selId = inputId === "wrap-folder" ? "wrap-mods" : "pub-mods";
    var sel = $(selId);
    var path = sel.value;
    if (!path) {
      toast("mods/ 下没有可选的 Mod", true);
      return;
    }
    $(inputId).value = path;
    if (scanFn) await scanFn(path);
  }

  function bindFolderInput(inputId, scanFn) {
    var input = $(inputId);
    var timer = null;
    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var v = input.value.trim();
        if (v && scanFn) scanFn(v);
      }, 350);
    });
    input.addEventListener("change", function () {
      var v = input.value.trim();
      if (v && scanFn) scanFn(v);
    });
  }

  /* 模式1: 包装 Mod */
  var wrapState = { files: [], extra: [] };

  function wrapIsSingleFile() {
    var r = document.querySelector('input[name="wrap-type"]:checked');
    return !!r && r.value === "single";
  }

  async function scanWrapFolder(path) {
    try {
      var r = await invoke("scan_mod_files", path, wrapIsSingleFile());
      if (!r.ok) {
        wrapState = { files: [], extra: [] };
        exSetMsg(r.error, true);
        return false;
      }
      wrapState = { files: r.files || [], extra: [] };
      exSetMsg("");
      return true;
    } catch (e) {
      exSetMsg("扫描失败: " + errTextLocal(e), true);
      return false;
    }
  }

  /* 模式3: 发布 Mod */
  async function loadPublishPreview(path, syncTags) {
    if (syncTags === undefined) syncTags = true;
    try {
      var r = await invoke("preview_mod", path);
      if (!r.ok) {
        $("pub-preview").textContent = r.error;
        $("pub-preview").classList.add("err");
        return false;
      }
      var i = r.info;
      if (syncTags) {
        $("pub-tags").value = parseTagList(i.tags).join(", ");
        var style = i.tags_style;
        $("pub-tags-style").value = style && typeof style === "object" ? JSON.stringify(style) : "";
      }
      var lines = [
        "名称: " + (i.name || ""),
        "版本: " + ((i.version || "").trim() || "0.0.1"),
        "作者: " + JSON.stringify(i.authors || {}),
        "描述: " + ((i.desc || "").trim() || "(空)"),
        "标签: " + (parseTagList($("pub-tags").value).join(", ") || "(无)"),
        "载入文件: " + ((i.file_names || []).join(", ") || "(空)"),
        "",
        "上传后: 图标 → 蓝奏云 FaustLauncher.icons, 压缩包 → FaustLauncher.Mods,",
        "       dowload_url/icon_url = 直链解析链接, download_count=0, disabled=false",
        "单文件上限: " + (r.max_size_mb || 66) + " MB (web_config.json → lanzou.max_size_mb, 该账号实测约 66MB)",
      ];
      $("pub-preview").textContent = lines.join("\n");
      $("pub-preview").classList.remove("err");
      return true;
    } catch (e) {
      $("pub-preview").textContent = "预览失败: " + errTextLocal(e);
      $("pub-preview").classList.add("err");
      return false;
    }
  }

  /* 模式4: 发布插件 */
  async function loadAddonPreview(path, syncTags) {
    if (syncTags === undefined) syncTags = true;
    try {
      var r = await invoke("preview_addon", path);
      if (!r.ok) {
        $("addon-pub-preview").textContent = r.error;
        $("addon-pub-preview").classList.add("err");
        return false;
      }
      var i = r.info;
      if (syncTags) {
        $("addon-pub-tags").value = parseTagList(i.tags).join(", ");
        var style = i.tags_style;
        $("addon-pub-tags-style").value = style && typeof style === "object" ? JSON.stringify(style) : "";
      }
      var lines = [
        "名称: " + (i.name || ""),
        "版本: " + ((i.version || "").trim() || "0.0.1"),
        "作者: " + JSON.stringify(i.authors || {}),
        "描述: " + ((i.desc || "").trim() || "(空)"),
        "标签: " + (parseTagList($("addon-pub-tags").value).join(", ") || "(无)"),
        "",
        "上传后: 图标 → 蓝奏云 FaustLauncher.icons, 压缩包 → FaustLauncher.Addons,",
        "       dowload_url/icon_url = 直链解析链接, download_count 沿用云端旧值,",
        "       同名插件视为更新并置顶（插件库 total_addons 重算）",
        "单文件上限: " + (r.max_size_mb || 66) + " MB (web_config.json → lanzou.max_size_mb)",
      ];
      $("addon-pub-preview").textContent = lines.join("\n");
      $("addon-pub-preview").classList.remove("err");
      return true;
    } catch (e) {
      $("addon-pub-preview").textContent = "预览失败: " + errTextLocal(e);
      $("addon-pub-preview").classList.add("err");
      return false;
    }
  }

  /* 信息表单弹层 */
  var formCtx = null;

  function openForm(type, nameDefault, files, extra, singleFile) {
    formCtx = { type: type, files: files || [], extra: extra || [], iconPath: "", singleFile: !!singleFile };
    $("form-title").textContent = type === "wrap"
      ? (formCtx.singleFile ? "填写信息 - 包装单文件 Mod" : "填写信息 - 包装 Mod")
      : "填写信息 - 生成插件";
    $("form-name").value = nameDefault;
    $("form-desc").value = "";
    $("form-version").value = "0.0.1";
    $("form-authors").value = "";
    $("form-icon-hint").textContent = "不选择则自动生成默认图标";
    $("form-files-field").style.display = type === "wrap" ? "" : "none";
    renderFormFiles();
    $("formOverlay").classList.add("show");
    $("form-name").focus();
  }

  function renderFormFiles() {
    var box = $("form-files");
    box.innerHTML = "";
    var extraSet = new Set(formCtx.extra.map(function (p) { return p.split(/[\\/]/).pop(); }));
    if (!formCtx.files.length) {
      var d = document.createElement("div");
      d.className = "empty";
      d.textContent = "未发现 .bank/.carra2 文件，可通过「添加其他文件」选择";
      box.appendChild(d);
      return;
    }
    formCtx.files.forEach(function (f) {
      var label = document.createElement("label");
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = true;
      cb.value = f;
      var span = document.createElement("span");
      span.textContent = f;
      if (extraSet.has(f)) span.className = "extra";
      label.appendChild(cb);
      label.appendChild(span);
      box.appendChild(label);
    });
  }

  function parseAuthors() {
    var authors = {};
    $("form-authors").value.split("\n").forEach(function (line) {
      line = line.trim();
      if (!line) return;
      var idx = line.indexOf("|");
      if (idx >= 0) {
        authors[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
      } else {
        authors[line] = "";
      }
    });
    return authors;
  }

  function bindExtension() {
    document.querySelectorAll("#page-ext .tab").forEach(function (t) {
      t.addEventListener("click", function () { switchMode(t.dataset.mode); });
    });

    $("wrap-browse").addEventListener("click", function () { pickFolderAndSet("wrap-folder", scanWrapFolder); });
    $("wrap-from-mods").addEventListener("click", function () { chooseFromMods("wrap-folder", scanWrapFolder); });

    document.querySelectorAll('input[name="wrap-type"]').forEach(function (r) {
      r.addEventListener("change", function () {
        var v = $("wrap-folder").value.trim();
        if (v) scanWrapFolder(v);
      });
    });

    $("wrap-mods").addEventListener("change", function () {
      var v = $("wrap-mods").value;
      if (!v) return;
      $("wrap-folder").value = v;
      scanWrapFolder(v);
    });

    $("wrap-start").addEventListener("click", async function () {
      var folder = $("wrap-folder").value.trim();
      if (!folder) { exSetMsg("请先选择原始文件夹", true); return; }
      if (!(await scanWrapFolder(folder))) return;
      var base = folder.split(/[\\/]/).pop() || "";
      openForm("wrap", base, wrapState.files, wrapState.extra, wrapIsSingleFile());
    });

    $("plugin-start").addEventListener("click", function () {
      var name = $("plugin-name").value.trim();
      if (!name) { exSetMsg("请先填写插件名称", true); return; }
      openForm("plugin", name, [], []);
    });

    $("pub-browse").addEventListener("click", function () { pickFolderAndSet("pub-folder", loadPublishPreview); });
    $("pub-from-mods").addEventListener("click", function () { chooseFromMods("pub-folder", loadPublishPreview); });
    $("pub-mods").addEventListener("change", function () {
      var v = $("pub-mods").value;
      if (!v) return;
      $("pub-folder").value = v;
      loadPublishPreview(v);
    });

    $("pub-upload").addEventListener("click", async function () {
      var folder = $("pub-folder").value.trim();
      if (!folder) { exSetMsg("请先选择 Mod 文件夹", true); return; }
      var tags, tagsStyle;
      try {
        tags = parseTagList($("pub-tags").value);
        tagsStyle = parseTagsStyleInput("pub-tags-style");
      } catch (e) {
        exSetMsg(errTextLocal(e), true); return;
      }
      if (!(await loadPublishPreview(folder, false))) return;
      var btn = $("pub-upload");
      var progress = $("pub-progress");
      var fill = $("pub-progress-fill");
      var ptext = $("pub-progress-text");
      btn.disabled = true;
      btn.textContent = "上传中...";
      $("pub-log").textContent = "";
      $("pub-log").className = "log";
      progress.style.display = "";
      fill.style.width = "0%";
      ptext.textContent = "准备中...";
      try {
        var r = await invoke("publish_mod", folder, tags, tagsStyle);
        var logEl = $("pub-log");
        logEl.textContent = r.log || "";
        logEl.className = "log " + (r.ok ? "ok" : "err");
        exSetMsg(r.msg, !r.ok);
        if (r.ok) toast("发布成功: " + ((r.info && r.info.name) || ""));
      } catch (e) {
        exSetMsg("发布失败: " + errTextLocal(e), true);
      } finally {
        btn.disabled = false;
        btn.textContent = "🚀 上传到云端";
        setTimeout(function () { progress.style.display = "none"; }, 3000);
      }
    });

    $("addon-pub-browse").addEventListener("click", function () { pickFolderAndSet("addon-pub-folder", loadAddonPreview); });
    $("addon-pub-from-addons").addEventListener("click", async function () {
      var sel = $("addon-pub-addons");
      var path = sel && sel.value;
      if (!path) { toast("addons/ 下没有可选的插件", true); return; }
      $("addon-pub-folder").value = path;
      await loadAddonPreview(path);
    });
    $("addon-pub-addons").addEventListener("change", function () {
      var v = $("addon-pub-addons").value;
      if (!v) return;
      $("addon-pub-folder").value = v;
      loadAddonPreview(v);
    });
    bindFolderInput("addon-pub-folder", loadAddonPreview);

    $("addon-pub-upload").addEventListener("click", async function () {
      var folder = $("addon-pub-folder").value.trim();
      if (!folder) { exSetMsg("请先选择插件文件夹", true); return; }
      var tags, tagsStyle;
      try {
        tags = parseTagList($("addon-pub-tags").value);
        tagsStyle = parseTagsStyleInput("addon-pub-tags-style");
      } catch (e) {
        exSetMsg(errTextLocal(e), true); return;
      }
      if (!(await loadAddonPreview(folder, false))) return;
      var btn = $("addon-pub-upload");
      var progress = $("addon-pub-progress");
      var fill = $("addon-pub-progress-fill");
      var ptext = $("addon-pub-progress-text");
      btn.disabled = true;
      btn.textContent = "上传中...";
      $("addon-pub-log").textContent = "";
      $("addon-pub-log").className = "log";
      progress.style.display = "";
      fill.style.width = "0%";
      ptext.textContent = "准备中...";
      try {
        var r = await invoke("publish_addon", folder, tags, tagsStyle);
        var logEl = $("addon-pub-log");
        logEl.textContent = r.log || "";
        logEl.className = "log " + (r.ok ? "ok" : "err");
        exSetMsg(r.msg, !r.ok);
        if (r.ok) toast("发布成功: " + ((r.info && r.info.name) || ""));
      } catch (e) {
        exSetMsg("发布失败: " + errTextLocal(e), true);
      } finally {
        btn.disabled = false;
        btn.textContent = "🚀 上传到云端";
        setTimeout(function () { progress.style.display = "none"; }, 3000);
      }
    });

    $("form-add-files").addEventListener("click", async function () {
      try {
        var paths = await invoke("pick_files");
        if (!paths || !paths.length) return;
        paths.forEach(function (p) {
          var base = p.split(/[\\/]/).pop();
          if (formCtx.files.indexOf(base) < 0) {
            formCtx.files.push(base);
            formCtx.extra.push(p);
          }
        });
        renderFormFiles();
      } catch (e) {
        toast("添加文件失败: " + errTextLocal(e), true);
      }
    });

    $("form-pick-icon").addEventListener("click", async function () {
      try {
        var path = await invoke("pick_icon");
        if (!path) return;
        formCtx.iconPath = path;
        $("form-icon-hint").textContent = path;
      } catch (e) {
        toast("选择图标失败: " + errTextLocal(e), true);
      }
    });

    $("form-confirm").addEventListener("click", async function () {
      var name = $("form-name").value.trim();
      if (!name) { toast("请填写名称", true); return; }
      var data = {
        name: name,
        desc: $("form-desc").value.trim(),
        version: $("form-version").value.trim() || "0.0.1",
        authors: parseAuthors(),
        icon_path: formCtx.iconPath || "",
      };
      var btn = $("form-confirm");
      btn.disabled = true;
      try {
        var r;
        if (formCtx.type === "wrap") {
          data.folder = $("wrap-folder").value.trim();
          data.files = Array.from(document.querySelectorAll("#form-files input:checked")).map(function (c) { return c.value; });
          data.extra_files = formCtx.extra;
          data.single_file = formCtx.singleFile;
          r = await invoke("wrap_mod", data);
        } else {
          r = await invoke("spawn_extension", data);
        }
        if (r.ok) {
          $("formOverlay").classList.remove("show");
          exSetMsg(r.msg);
          toast("生成成功");
          fillModsSelect("wrap-mods", false);
          fillModsSelect("pub-mods", true);
        } else {
          exSetMsg(r.msg, true);
          toast(r.msg, true);
        }
      } catch (e) {
        exSetMsg("生成失败: " + errTextLocal(e), true);
      } finally {
        btn.disabled = false;
      }
    });

    $("form-cancel").addEventListener("click", function () { $("formOverlay").classList.remove("show"); });
    $("form-close").addEventListener("click", function () { $("formOverlay").classList.remove("show"); });
  }

  /* 发布进度/日志实时推送 (Python 侧经 pywebview evaluate_js 调用) */
  window.__onPublishProgress = function (p) {
    var progress = $("pub-progress"), fill = $("pub-progress-fill"), ptext = $("pub-progress-text");
    if (!progress || !fill || !ptext) return;
    var pct = Math.max(0, Math.min(100, Math.round((p && p.percent) || 0)));
    progress.style.display = "";
    fill.style.width = pct + "%";
    ptext.textContent = ((p && p.text) || "") + " " + pct + "%";
  };
  window.__onPublishLog = function (s) {
    var elx = $("pub-log");
    if (!elx) return;
    elx.textContent += (elx.textContent ? "\n" : "") + String(s);
    elx.scrollTop = elx.scrollHeight;
  };
  window.__onAddonProgress = function (p) {
    var progress = $("addon-pub-progress"), fill = $("addon-pub-progress-fill"), ptext = $("addon-pub-progress-text");
    if (!progress || !fill || !ptext) return;
    var pct = Math.max(0, Math.min(100, Math.round((p && p.percent) || 0)));
    progress.style.display = "";
    fill.style.width = pct + "%";
    ptext.textContent = ((p && p.text) || "") + " " + pct + "%";
  };
  window.__onAddonLog = function (s) {
    var elx = $("addon-pub-log");
    if (!elx) return;
    elx.textContent += (elx.textContent ? "\n" : "") + String(s);
    elx.scrollTop = elx.scrollHeight;
  };

  async function loadBg() {
    try {
      var a = await invoke("assets");
      if (a && a.bg) $("bgimg").src = a.bg;
    } catch (e) {
      console.error(e);
    }
  }

  function initExtension() {
    fillModsSelect("wrap-mods", false);
    fillModsSelect("pub-mods", true);
    bindFolderInput("wrap-folder", scanWrapFolder);
    bindFolderInput("pub-folder", loadPublishPreview);
    loadBg();
  }

  /* ============================================================
     启动
     ============================================================ */
  function boot() {
    api = window.pywebview && window.pywebview.api;
    if (!api) return;
    bindPageswitch();
    bindWorkflow();
    bindExtension();
    refresh();
    setInterval(refresh, 1400);
  }

  if (window.pywebview && window.pywebview.api) {
    boot();
  } else {
    window.addEventListener("pywebviewready", boot, { once: true });
  }
})();
