(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  var ui = {
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
  var state = null;
  var lastListKey = "";
  var busy = false;
  var startBusy = {};
  var toastTimer = null;

  function invoke(name) {
    var args = Array.prototype.slice.call(arguments, 1);
    if (!api) return Promise.reject(new Error("pywebview 尚未就绪"));
    return api[name].apply(api, args);
  }

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
    return result.error || result.message || "操作失败";
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
        startBusy[p.name] ? 1 : 0
      ];
    }));
  }

  function applyState(next) {
    if (!next || !next.ok) {
      if (next && next.error) toast(next.error, true);
      return;
    }
    state = next;

    ui.version.textContent = "Mod 打包工作流 · v" + (next.version || "?");
    var game = next.game || {};
    ui.gamePath.value = game.path || "";
    ui.gamePath.title = game.path || "";
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
      empty.appendChild(el("div", null, "点右上角“新建包”，再添加 .zip / .bank 文件。"));
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
          remove.title = "从包中移除";
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

  function bind() {
    $("wf-new").addEventListener("click", openNewModal);
    $("wf-new-cancel").addEventListener("click", closeNewModal);
    $("wf-new-confirm").addEventListener("click", createPackage);
    ui.newName.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        createPackage();
      } else if (event.key === "Escape") {
        closeNewModal();
      }
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

  function boot() {
    api = window.pywebview && window.pywebview.api;
    if (!api) return;
    bind();
    refresh();
    setInterval(refresh, 1400);
  }

  if (window.pywebview && window.pywebview.api) {
    boot();
  } else {
    window.addEventListener("pywebviewready", boot, { once: true });
  }
})();
