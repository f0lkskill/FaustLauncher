/* ============================================================
   FaustLauncher Web UI — 前端逻辑
   浏览器直接打开 index.html 时使用内置 Mock 数据预览。
   ============================================================ */
(() => {
  'use strict';

// 证明本 JS 已执行 (覆盖 HTML 静态 build-tag; 若侧边栏底部仍显示旧文字则说明 JS 是缓存旧版)
  try {
    var _tag = document.getElementById('build-tag');
    if (_tag) _tag.textContent = 'JS 已执行 v6 · ' + new Date().getTime();
  } catch (_) {}

  // 全局 JS 错误浮层: 前端一旦报错, 在窗口底部显示, 便于排查 (无需开 DevTools)
  (function _errOverlay() {
    function show(tag, msg) {
      try {
        let box = document.getElementById('js-err');
        if (!box) {
          box = document.createElement('div');
          box.id = 'js-err';
          box.style.cssText = 'position:fixed;bottom:6px;left:6px;right:6px;z-index:99999;' +
            'background:rgba(140,20,20,.96);color:#ffd;font:12px/1.45 monospace;' +
            'padding:6px 10px;border-radius:6px;white-space:pre-wrap;max-height:38vh;overflow:auto;';
          document.body.appendChild(box);
        }
        box.textContent = (box.textContent ? box.textContent + '\n---\n' : '') +
          '[' + tag + '] ' + msg;
      } catch (_) {}
    }
    window.addEventListener('error', function (e) {
      show('JS', (e.message || '') + (e.filename ? '\n@ ' + e.filename + ':' + (e.lineno || '') : ''));
    });
    window.addEventListener('unhandledrejection', function (e) {
      const r = e && e.reason;
      show('ASYNC', (r && r.message) || String(r));
    });
  })();

  // 兜底: 仅当极端卡死时才强制结束主页 loading (30 秒), 避免破坏慢速加载的圆圈
  setTimeout(function () {
    ['stat-version-card', 'rec-card'].forEach(function (id) {
      var f = document.getElementById(id);
      if (f) f.classList.remove('loading');
    });
  }, 30000);

  // 兜底: 按内容是否已渲染来决定是否结束 loading (移除圆圈)。
  // 一旦 changelog-body / rec-body 不再是 "加载中" 占位文本, 即强制移除对应卡片的 loading 类。
  // 用 trim() 排除换行/空格等空白节点, 避免空卡片被误判为"已加载"
  setInterval(function () {
    var ch = document.getElementById('changelog-body');
    if (ch && ch.textContent.trim() && ch.textContent.indexOf('加载中') === -1) {
      var f1 = document.getElementById('stat-version-card');
      if (f1) f1.classList.remove('loading');
    }
    var rb = document.getElementById('rec-body');
    if (rb && rb.textContent.trim() && rb.textContent.indexOf('加载中') === -1) {
      var f2 = document.getElementById('rec-card');
      if (f2) f2.classList.remove('loading');
    }
  }, 800);

  let api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;

  // 诊断: 在 DevTools Console 敲 window.__diag() 查看圆圈元素详情
  window.__diag = function () {
    var out = [];
    ['stat-version-card', 'rec-card'].forEach(function (id) {
      var f = document.getElementById(id);
      if (!f) { out.push(id + ': 不存在'); return; }
      var sp = f.querySelector('.frame-spinner');
      var cs = sp ? getComputedStyle(sp) : null;
      out.push(id + ': class=[' + f.className + ']' +
        (sp ? (' spinner=[display:' + cs.display + ';position:' + cs.position + '] html=' + sp.outerHTML.slice(0, 60)) : ' spinner=无'));
    });
    var spins = document.querySelectorAll('.frame-spinner');
    out.push('页面 .frame-spinner 总数=' + spins.length);
    spins.forEach(function (s) {
      var cs = getComputedStyle(s);
      out.push('  el: display=' + cs.display + ' parent=' + (s.parentElement ? s.parentElement.id || s.parentElement.className : '?'));
    });
    var rot = document.querySelectorAll('.frame-spinner span, .pipe-step.active .st-ico, [class*=spin]');
    out.push('旋转元素数=' + rot.length);
    var cb = document.getElementById('changelog-body');
    var rb = document.getElementById('rec-body');
    out.push('changelog-body text=[' + (cb ? cb.textContent.trim().slice(0, 60) : '?') + ']');
    out.push('rec-body text=[' + (rb ? rb.textContent.trim().slice(0, 60) : '?') + ']');
    return out.join('\n');
  };

  // 诊断: 强制隐藏所有圆圈 (测试用)
  window.__hideCircles = function () {
    var n = 0;
    document.querySelectorAll('.frame-spinner').forEach(function (s) {
      s.style.display = 'none'; n++;
    });
    ['stat-version-card', 'rec-card'].forEach(function (id) {
      var f = document.getElementById(id);
      if (f) f.classList.remove('loading');
    });
    return '已隐藏 ' + n + ' 个圆圈';
  };
  let IS_BROWSER = !api;

  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => [...(r || document).querySelectorAll(s)];

  // ---------------- Mock (浏览器预览) ----------------
  const MOCK = {
    version: 'V0.7.1-release',
    game_path: '',
    bg_color: '#181818',
    features: [
      { name: '📁 游戏目录', desc: '打开边狱巴士安装目录', image: 'game_directory.png' },
      { name: '🔄 零协会', desc: '前往零协会汉化组主页', image: 'zeroasso.png' },
      { name: '📒 气泡文本', desc: '下载气泡 Mod 汉化版', image: '' },
      { name: '📝 维基', desc: '边狱巴士灰机 Wiki', image: 'wiki.png' },
      { name: '📖 N网', desc: '下载边狱巴士 Mod', image: 'nexus.png' },
      { name: '📦 GitHub', desc: '查看本项目源码', image: 'github.png' },
    ],
    tools: [
      { id: 'nyos', name: '📖 今日指令', desc: '获取食指的最新指令' },
      { id: 'mod_manager', name: '📦 Mod 管理器', desc: '管理边狱巴士 Mod 文件', page: 'mod_addon' },
      { id: 'custom_translation', name: '🔧 自定义汉化', desc: '可视化编辑 lang 下任意 JSON 文本' },
      { id: 'folder_link', name: '📂 文件夹超链接', desc: '创建符号链接, 释放 C 盘' },
      { id: 'extension_tools', name: '🧩 扩展工具', desc: '插件模板 / 打包发布' },
      { id: 'font', name: '📝 字体修改', desc: '选择字体替换汉化包字体' },
      { id: 'auto_translate', name: '🤖 自动汉化', desc: '思知 AI 批量剧情文本翻译' },
      { id: 'gradient', name: '💻 渐变文本处理器', desc: '生成 Unity 富文本渐变色代码' },
    ],
    settings_schema: {
      game_path: { name: '游戏路径', type: 'string', default: '', value: '', description: '游戏安装路径', page: '通用' },
      translate_source: { name: '汉化包平台方', type: 'combobox', options: ['零协会', 'OurPlay 普通版', 'OurPlay 神人版'], default: 0, value: 0, description: '选择下载的汉化包来源平台', page: '通用' },
      after_gui_exit: { name: '退出后操作', type: 'combobox', options: ['最小化到系统托盘', '关闭程序'], default: 0, value: 0, description: '退出程序后, 程序将如何操作', page: '通用' },
      user_name: { name: '用户名', type: 'string', default: 'Player', value: 'Player', description: '你的用户名，将显示在边狱巴士的个人车票上', page: '美化' },
      enable_show_user_name: { name: '显示用户名', type: 'boolean', default: true, value: true, description: '是否显示用户名在边狱巴士的个人车票上', page: '美化' },
      enable_mods: { name: '启用Mod功能', type: 'boolean', default: true, value: true, description: '是否加载 Mod', page: 'Mod' },
      bubble_text_gradient_rate: { name: '气泡文本渐变系数', type: 'float', default: 0.4, value: 0.4, min: 0.1, max: 1.0, step: 0.1, description: '越大的值意味着颜色渐变越快', page: '美化' },
      bg_color: { name: '主题颜色（实验性）', type: 'color', default: '#181818', value: '#181818', description: '应用程序的主题颜色', page: '其它' },
      version_info: { name: '版本信息', type: 'UNABLE_TO_EDIT', default: 'V0.7.1-release', value: 'V0.7.1-release', description: '当前应用程序的版本信息' },
    },
    is_frozen: false,
    project_root: '',
  };

  // ---------------- 全局状态 ----------------
  let BOOT = null;
  let SETTING_CHANGES = {};   // key -> {value, touched}
  let currentPage = 'home';
  let pipeline = {
    running: false,
    currentIdx: -1,
    steps: [],
  };

  // 完整流水线 (启动游戏) / 汉化更新流水线 (不含启动游戏)
  const STEPS_FULL = [
    { key: 'prepare', label: '准备检查', icon: '🔍' },
    { key: 'download', label: '下载汉化包', icon: '📥' },
    { key: 'resource', label: '检查资源', icon: '🗂️' },
    { key: 'bubble', label: '下载气泡', icon: '💬' },
    { key: 'install', label: '安装汉化', icon: '📦' },
    { key: 'mods', label: '加载插件/Mod', icon: '🧩' },
    { key: 'launch', label: '启动游戏', icon: '🚀' },
  ];
  // 汉化更新流水线: 不含"加载插件/Mod"和"启动游戏" (汉化更新不重载插件、不启动游戏)
  const STEPS_TRANSLATE = STEPS_FULL.filter(s => s.key !== 'launch' && s.key !== 'mods');

  // ---------------- 工具函数 ----------------
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function toast(msg, type = 'info', ms = 3200) {
    const box = $('#toasts');
    const el = document.createElement('div');
    el.className = 'toast ' + type;
    el.innerHTML = esc(msg);
    box.appendChild(el);
    setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 320); }, ms);
  }

  function toastTop(msg, type = 'info', ms = 3200) {
    let box = document.getElementById('toasts-top');
    if (!box) {
      box = document.createElement('div');
      box.id = 'toasts-top';
      document.body.appendChild(box);
    }
    const el = document.createElement('div');
    el.className = 'toast ' + type;
    el.innerHTML = esc(msg);
    box.appendChild(el);
    setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 320); }, ms);
  }

  function withTimeout(p, ms, fallback) {
    // 网络请求兜底超时: 防止云端慢/断网导致页面卡死
    return Promise.race([
      Promise.resolve(p),
      new Promise(res => setTimeout(() => res(fallback), ms)),
    ]);
  }

  // 图标走后端 get_icon (带磁盘缓存), 避免每次渲染都重新下载远程图标
  // 返回 Promise 数组, 便于调用方在图标全部加载完成后才结束 loading (圆圈)
  function hydrateIcons(root) {
    const promises = [];
    if (!api) return promises;
    const imgs = (root || document).querySelectorAll('img[data-icon-url]');
    imgs.forEach(img => {
      const url = img.getAttribute('data-icon-url');
      const name = img.getAttribute('data-icon-name') || '';
      if (!url) return;
      promises.push(withTimeout(api.get_icon(url, name), 6000, '').then(uri => {
        if (uri) img.src = uri;
      }).catch(() => {}));
    });
    return promises;
  }

  function fmtBytes(n) {
    if (n == null) return '-';
    n = Number(n);
    if (n >= 1024 * 1024 * 1024) return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
    if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
    if (n >= 1024) return (n / 1024).toFixed(1) + ' KB';
    return n + ' B';
  }

  // 后端 speed 单位是 KB/s (非字节)
  function fmtSpeed(kbps) {
    kbps = Number(kbps) || 0;
    if (kbps >= 1024) return (kbps / 1024).toFixed(2) + ' MB/s';
    if (kbps >= 1) return kbps.toFixed(1) + ' KB/s';
    return Math.round(kbps * 1024) + ' B/s';
  }

  // ---------------- Frame 加载转圈动画 ----------------
  // 用内联样式直接控制 spinner 显示/隐藏, 不依赖 CSS 规则 (.card.loading .frame-spinner)
  // 隐藏时先淡出 (opacity 过渡), 再 display:none, 让蒙版平滑消失
  function setFrameLoading(frame, on) {
    if (!frame) return;
    frame.classList.toggle('loading', on);
    const sp = frame.querySelector('.frame-spinner');
    if (!sp) return;
    if (sp._fadeTimer) { clearTimeout(sp._fadeTimer); sp._fadeTimer = null; }
    if (on) {
      sp.style.display = 'flex';
      void sp.offsetWidth;   // 强制 reflow, 确保 opacity 过渡生效
      sp.style.opacity = '1';
    } else {
      sp.style.opacity = '0';
      sp._fadeTimer = setTimeout(() => { sp.style.display = 'none'; sp._fadeTimer = null; }, 420);
    }
  }
  function showFrameLoading(frame) { setFrameLoading(frame, true); }
  function hideFrameLoading(frame) { setFrameLoading(frame, false); }

  // ---------------- ANSI 转 HTML ----------------
  const ANSI_COLORS = {
    30: '#555a68', 31: '#ef4444', 32: '#10b981', 33: '#f59e0b',
    34: '#38bdf8', 35: '#c084fc', 36: '#22d3ee', 37: '#e8ecf4',
    90: '#6b7689', 91: '#f87171', 92: '#34d399', 93: '#fbbf24',
    94: '#60a5fa', 95: '#d8b4fe', 96: '#67e8f9', 97: '#ffffff',
  };

  function ansiToHtml(text) {
    const parts = String(text).split(/\x1b\[/);
    let out = parts[0];
    let cls = 'info';
    for (let i = 1; i < parts.length; i++) {
      const m = /^([0-9;]*)m/.exec(parts[i]);
      if (!m) { out += parts[i]; continue; }
      const codes = m[1] ? m[1].split(';') : [];
      let rest = parts[i].slice(m[0].length);
      if (codes.includes('0')) { cls = 'info'; out += '</span>'.repeat(0) + rest; continue; }
      let style = '';
      if (codes.includes('1')) style += 'font-weight:bold;';
      for (const c of codes) {
        if (ANSI_COLORS[c]) { style += 'color:' + ANSI_COLORS[c] + ';'; break; }
        if (c >= 40 && c <= 47) style += 'background:#2d3650;';
      }
      out += '<span style="' + style + '">' + esc(rest) + '</span>';
    }
    // 简易语义色
    if (/❌|错误|失败|出错/.test(out)) cls = 'error';
    else if (/✓|成功|完成|安装到/.test(out)) cls = 'success';
    else if (/警告/.test(out)) cls = 'warning';
    else if (/开始|正在|下载|检查/.test(out)) cls = 'wait';
    return { html: out, cls };
  }

  // ---------------- 终端 ----------------
  const termBody = $('#term-body');
  let termAutoScroll = true;

  function addLog(text) {
    const line = String(text == null ? '' : text).replace(/\r/g, '');
    if (!line.trim()) return;
    const { html, cls } = ansiToHtml(line);
    const div = document.createElement('div');
    div.className = 'term-line ' + cls;
    const t = new Date();
    const ts = t.toTimeString().slice(0, 8);
    div.innerHTML = '<span class="t-time">[' + ts + ']</span>' + html;
    termBody.appendChild(div);
    while (termBody.children.length > 1500) termBody.firstChild.remove();
    if (termAutoScroll) termBody.scrollTop = termBody.scrollHeight;
    handlePipelineLog(line);
  }

  window.__onLog = function (text) { addLog(text); };

  window.__onEvent = function (event, data) {
    if (event === 'progress') {
      if (data && data.task) {
        updateDownloadTask(data.task, data);
        return;
      }
      const pct = Math.max(0, Math.min(100, Number(data.percent) || 0));
      $('#pipe-progress').style.width = pct + '%';
      if (pipeline.running) {
        $('#pipe-status-text').textContent =
          (data.downloaded != null && data.total != null)
            ? fmtBytes(data.downloaded) + ' / ' + fmtBytes(data.total) +
              (data.speed ? '  ·  ' + fmtSpeed(data.speed) : '')
            : pct.toFixed(0) + '%';
      }
      if (pct >= 100) setPipelineStepDone(pipeline.currentIdx, true);
    } else if (event === 'status') {
      if (data && typeof data === 'object' && data.task) {
        addLog('⟳ ' + String(data.text || ''));
        if (/(失败|错误|❌|出错)/.test(String(data.text || ''))) {
          failDownloadTask(data.task, String(data.text || '').slice(0, 80));
        }
        return;
      }
      addLog('⟳ ' + String(data));
    } else if (event === 'step') {
      // 后端显式步骤推进 (与真实进度同步, 不再依赖日志关键词)
      const s = data && data.step;
      const idx = pipeline.steps.findIndex(x => x.key === s);
      if (idx >= 0 && idx > pipeline.currentIdx) {
        setPipelineStepDone(pipeline.currentIdx, true);
        pipeline.currentIdx = idx;
        setStep(idx, 'active');
      }
    } else if (event === 'dialog') {
      const d = data || {};
      const kind = d.kind || 'showinfo';
      const isErr = /error|ask/.test(kind);
      const text = (d.title ? '[' + d.title + '] ' : '') + (d.message || '');
      toast(text, isErr ? 'error' : 'warn', 6000);
      if (isErr && pipeline.running) pipelineError();
    } else if (event === 'game_started') {
      const li = pipeline.steps.findIndex(s => s.key === 'launch');
      setPipelineStepDone(li, true);
      $('#pipe-status-text').textContent = '🎮 正在游戏中';
      $('#pipe-status-text').className = 'pipe-status done';
      $('#btn-launch').disabled = false;
      $('#btn-translate').disabled = false;
    } else if (event === 'game_exited') {
      pipelineDone();
      $('#pipe-status-text').textContent = '游戏已退出';
    } else if (event === 'game_timeout') {
      pipelineError();
      $('#pipe-status-text').textContent = '等待游戏启动超时, 请检查游戏是否正常安装';
      toast('等待游戏启动超时', 'error', 6000);
      setTimeout(() => { pipelineIdle(); }, 4000);
    }
  };

  // ---------------- 流水线 ----------------
  function flipGridBelow(applyLayoutChange) {
    // FLIP: 流水线卡显隐引起的布局位移, 让下方 grid-2 平滑移动
    const grid = document.querySelector('.grid-2');
    if (!grid) return;
    const before = grid.getBoundingClientRect().top;
    applyLayoutChange();
    const after = grid.getBoundingClientRect().top;
    const dy = before - after;
    if (!dy) return;
    grid.style.transition = 'none';
    grid.style.transform = 'translateY(' + dy + 'px)';
    void grid.offsetWidth;
    grid.style.transition = '';
    grid.style.transform = '';
  }

  function pipelineReset(withLaunch) {
    pipeline.running = true;
    pipeline.currentIdx = -1;
    pipeline.steps = withLaunch ? STEPS_FULL.slice() : STEPS_TRANSLATE.slice();
    $('#pipe-progress').style.width = '0%';
    $('#pipe-status-text').textContent = '初始化中...';
    $('#pipe-status-text').className = 'pipe-status running';
    const card = $('#pipeline-card');
    flipGridBelow(() => { card.hidden = false; });
    card.classList.remove('visible');
    void card.offsetWidth; // 强制 reflow, 保证过渡动画生效
    requestAnimationFrame(() => card.classList.add('visible'));
    const wrap = $('#pipe-steps');
    wrap.innerHTML = '';
    pipeline.steps.forEach((s, i) => {
      const el = document.createElement('div');
      el.className = 'pipe-step';
      el.id = 'pstep-' + i;
      el.innerHTML = '<span class="st-ico">' + s.icon + '</span><span>' + esc(s.label) + '</span>';
      wrap.appendChild(el);
    });
  }

  function setStep(i, state) {
    const el = document.getElementById('pstep-' + i);
    if (!el) return;
    el.className = 'pipe-step ' + state;
  }

  function setPipelineStepDone(i, isDone) {
    if (i < 0) return;
    for (let j = 0; j <= i; j++) setStep(j, isDone ? 'done' : 'active');
    pipeline.currentIdx = Math.max(pipeline.currentIdx, i);
  }

  function pipelineAdvance() {
    const idx = pipeline.currentIdx + 1;
    if (idx >= pipeline.steps.length) return;
    pipeline.currentIdx = idx;
    setStep(idx, 'active');
  }

  function pipelineError() {
    $('#pipe-status-text').textContent = '启动过程中出现错误, 详见终端';
    $('#pipe-status-text').className = 'pipe-status error';
    const i = pipeline.currentIdx;
    if (i >= 0) setStep(i, 'active'); // 保留高亮
    $('#btn-launch').disabled = false;
    $('#btn-translate').disabled = false;
  }

  function pipelineDone() {
    pipeline.running = false;
    pipeline.steps.forEach((_, i) => setStep(i, 'done'));
    $('#pipe-progress').style.width = '100%';
    $('#pipe-status-text').textContent = '流水线完成';
    $('#pipe-status-text').className = 'pipe-status done';
    $('#btn-launch').disabled = false;
    $('#btn-translate').disabled = false;
    clearTimeout(pipeline._hideTimer);
    pipeline._hideTimer = setTimeout(() => pipelineIdle(), 1500);
  }

  function pipelineIdle() {
    // 流程回归初始状态: 流水线卡滑出消失, 复位进度
    clearTimeout(pipeline._hideTimer);
    const card = $('#pipeline-card');
    card.classList.remove('visible');
    pipeline.running = false;
    pipeline.currentIdx = -1;
    $('#pipe-progress').style.width = '0%';
    $('#pipe-status-text').textContent = '等待中';
    $('#pipe-status-text').className = 'pipe-status';
    const wrap = $('#pipe-steps');
    if (wrap) wrap.innerHTML = '';
    setTimeout(() => {
      flipGridBelow(() => { card.hidden = true; });
    }, 350);
  }

  const KEYWORD_MAP = [
    { k: 'download', re: /开始下载汉化包|下载翻译资源/ },
    { k: 'resource', re: /汉化包下载完成|检查资源/ },
    { k: 'bubble', re: /开始下载气泡文本/ },
    { k: 'install', re: /气泡文本载入完成|检测到新的汉化版本|安装到|复制汉化文件|最新版本/ },
    { k: 'mods', re: /汉化下载及处理全部完成|重载插件|加载.*[Mm]od/ },
    { k: 'launch', re: /启动游戏|正在启动|launch/ },
  ];

  function handlePipelineLog(line) {
    if (!pipeline.running) return;
    if (/错误|失败|出错|❌/.test(line)) {
      if (!/汉化包下载失败|启动游戏失败/.test(line) || /下载过程中出错/.test(line)) {
        pipelineError();
      }
      return;
    }
    if (/汉化下载及处理全部完成/.test(line)) {
      setPipelineStepDone(pipeline.steps.findIndex(s => s.key === 'install'), true);
      pipelineAdvance();
      return;
    }
for (const m of KEYWORD_MAP) {
      if (m.re.test(line)) {
        const idx = pipeline.steps.findIndex(s => s.key === m.k);
        if (idx >= 0 && idx > pipeline.currentIdx) {
          setPipelineStepDone(pipeline.currentIdx, true);
          pipeline.currentIdx = idx;
          setStep(idx, 'active');
        }
      }
    }
  }

  // ---------------- 页面导航 ----------------
  function switchPage(name) {
    currentPage = name;
    addLog('[页面] 切换到 ' + name);
    $$('.page').forEach(p => p.classList.remove('active'));
    const target = document.getElementById('page-' + name);
    if (target) target.classList.add('active');
    $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.page === name));
    $('#main').scrollTop = 0;
    if (name === 'mod_addon') refreshMods();
    if (name === 'download_center') initDownloadCenter();
  }

  // ---------------- Mod 管理 ----------------
  const MOD_ICONS = { '.bank': '🔊', '.carra2': '🖼️', '.rebank': '🧩' };
  let modDeleteArm = null;   // 二次点击确认删除 {key, el}

  async function refreshMods() {
    if (!api) { toast('浏览器预览模式', 'warn'); return; }
    const wrapDir = $('#dir-mods-list');
    const wrapSingle = $('#single-mods-list');
    wrapDir.innerHTML = '<div class="mod-empty">加载中...</div>';
    wrapSingle.innerHTML = '';
    try {
      const d = await api.get_mods_data();
      const dirs = d.dir_mods || [];
      const singles = d.single_files || [];
      $('#dir-mods-count').textContent = dirs.length ? dirs.length + ' 个' : '空';
      $('#single-mods-count').textContent = singles.length ? singles.length + ' 个' : '空';
      wrapDir.innerHTML = '';
      if (!dirs.length) wrapDir.innerHTML = '<div class="mod-empty">mods/ 目录下暂无 Mod（将包含 mod_info.json 的文件夹放入即可）</div>';
      dirs.forEach(m => wrapDir.appendChild(buildDirModCard(m)));
      wrapSingle.innerHTML = '';
      if (!singles.length) wrapSingle.innerHTML = '<div class="mod-empty">暂无单文件 Mod（.bank / .carra2 / .rebank）</div>';
      singles.forEach(f => wrapSingle.appendChild(buildSingleModCard(f)));
    } catch (e) {
      wrapDir.innerHTML = '<div class="mod-empty">读取失败: ' + esc(String(e)) + '</div>';
    }
  }

  function buildDirModCard(m) {
    const card = document.createElement('div');
    card.className = 'mod-card' + (m.enabled ? ' on' : '');
    card.innerHTML =
      '<div class="mod-main">' +
        '<div class="mod-title">' + esc(m.name) +
          (m.version ? ' <span class="mod-ver">v' + esc(m.version) + '</span>' : '') +
          (m.author ? ' <span class="mod-author">by ' + esc(m.author) + '</span>' : '') +
        '</div>' +
        '<div class="mod-desc">' + esc(m.description || '（无描述）') + '</div>' +
        (m.files && m.files.length ? '<div class="mod-files">文件: ' + esc(m.files.join(', ')) + '</div>' : '') +
      '</div>' +
      '<div class="mod-ops">' +
        '<label class="switch" title="启用/禁用"><input type="checkbox" data-act="toggle"' + (m.enabled ? ' checked' : '') + '><span class="slider"></span></label>' +
        '<button class="btn btn-ghost btn-mini" data-act="del">🗑</button>' +
      '</div>';
    card.querySelector('[data-act="toggle"]').onchange = async e => {
      try {
        const r = await api.set_mod_enabled(m.name, e.target.checked);
        if (r && r.error) { toast('切换失败: ' + r.error, 'error'); refreshMods(); return; }
        card.classList.toggle('on', e.target.checked);
        toast((e.target.checked ? '已启用 ' : '已禁用 ') + m.name, 'success');
      } catch (err) { toast('切换失败: ' + err, 'error'); refreshMods(); }
    };
    card.querySelector('[data-act="del"]').onclick = async () => {
      if (modDeleteArm !== m.name) {
        modDeleteArm = m.name;
        toast('再次点击 🗑 确认删除 ' + m.name, 'warn', 2500);
        setTimeout(() => { if (modDeleteArm === m.name) modDeleteArm = null; }, 3000);
        return;
      }
      modDeleteArm = null;
      try {
        const r = await api.delete_mod(m.name);
        if (r && r.error) { toast('删除失败: ' + r.error, 'error'); return; }
        toast('已删除 ' + m.name, 'success');
        refreshMods();
      } catch (err) { toast('删除失败: ' + err, 'error'); }
    };
    return card;
  }

  function buildSingleModCard(f) {
    const card = document.createElement('div');
    card.className = 'mod-card' + (f.enabled ? ' on' : '');
    card.innerHTML =
      '<div class="mod-main">' +
        '<div class="mod-title">' + (MOD_ICONS[f.ext] || '📄') + ' ' + esc(f.name) +
          ' <span class="mod-ver">' + esc(f.type_label || f.ext) + ' · ' + esc(f.size) + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="mod-ops">' +
        '<label class="switch" title="启用/禁用"><input type="checkbox" data-act="toggle"' + (f.enabled ? ' checked' : '') + '><span class="slider"></span></label>' +
        '<button class="btn btn-ghost btn-mini" data-act="del">🗑</button>' +
      '</div>';
    card.querySelector('[data-act="toggle"]').onchange = async e => {
      try {
        const r = await api.toggle_single_file(f.raw_name);
        if (r && r.error) { toast('切换失败: ' + r.error, 'error'); refreshMods(); return; }
        card.classList.toggle('on', e.target.checked);
        toast((e.target.checked ? '已启用 ' : '已禁用 ') + f.name, 'success');
      } catch (err) { toast('切换失败: ' + err, 'error'); refreshMods(); }
    };
    card.querySelector('[data-act="del"]').onclick = async () => {
      const key = 'single:' + f.raw_name;
      if (modDeleteArm !== key) {
        modDeleteArm = key;
        toast('再次点击 🗑 确认删除 ' + f.name, 'warn', 2500);
        setTimeout(() => { if (modDeleteArm === key) modDeleteArm = null; }, 3000);
        return;
      }
      modDeleteArm = null;
      try {
        const r = await api.delete_single_file(f.raw_name);
        if (r && r.error) { toast('删除失败: ' + r.error, 'error'); return; }
        toast('已删除 ' + f.name, 'success');
        refreshMods();
      } catch (err) { toast('删除失败: ' + err, 'error'); }
    };
    return card;
  }

  // ---------------- 下载中心 ----------------
  let dcCurrentTab = 'addon';
  let dcAddonPages = [];
  let dcModPages = [];
  let dcAddonPage = 1;
  let dcModPage = 1;

  // ---------------- 下载任务抽屉 ----------------
  let downloadTasks = [];

  function addDownloadTask(t) {
    const idx = downloadTasks.findIndex(x => x.name === t.name);
    if (idx >= 0) {
      downloadTasks[idx].status = 'waiting';
      downloadTasks[idx].icon = t.icon || PROJECT_ICON;
      downloadTasks[idx].percent = 0;
    } else {
      downloadTasks.push({ name: t.name, kind: t.kind, icon: t.icon || PROJECT_ICON, status: 'waiting', percent: 0, downloaded: 0, total: 0, speed: 0 });
    }
    renderDownloadDrawer();
    updateFabVisibility();
  }

  function updateDownloadTask(name, data) {
    const t = downloadTasks.find(x => x.name === name);
    if (!t) return;
    if (data.percent !== undefined) {
      t.percent = Math.max(0, Math.min(100, Number(data.percent) || 0));
      if (data.downloaded !== undefined) t.downloaded = data.downloaded;
      if (data.total !== undefined) t.total = data.total;
      if (data.speed !== undefined) t.speed = data.speed;
      const wasDone = t.status === 'done';
      t.status = t.percent >= 100 ? 'done' : 'downloading';
      if (t.status === 'done' && !wasDone) {
        toastTop(name + ' 下载完成', 'success');
        setTimeout(() => removeDownloadTask(name, true), 300);
      }
    }
    // 原位更新进度, 不重建 DOM (保证进度条过渡平滑)
    const row = document.querySelector('.dl-task[data-name="' + CSS.escape(name) + '"]');
    if (row && !row.classList.contains('leaving')) {
      const pct = Math.round(t.percent || 0);
      row.classList.remove('waiting', 'downloading', 'done', 'error');
      row.classList.add(t.status);
      row.querySelector('.dl-fill').style.width = pct + '%';
      const meta = row.querySelector('.dl-meta');
      meta.textContent = t.status === 'done' ? '✓ 已完成'
        : t.status === 'error' ? '✗ ' + esc(t.error || '下载失败')
        : t.status === 'waiting' ? '等待中…'
        : fmtBytes(t.downloaded) + ' / ' + fmtBytes(t.total) +
          (t.speed ? ' · ' + fmtSpeed(t.speed) : '');
    } else {
      renderDownloadDrawer();
    }
    updateFabVisibility();
  }

  function failDownloadTask(name, text) {
    const t = downloadTasks.find(x => x.name === name);
    if (!t) return;
    t.status = 'error';
    t.error = text;
    setTimeout(() => removeDownloadTask(name, true), 8000);
    renderDownloadDrawer();
    updateFabVisibility();
  }

  function removeDownloadTask(name, animate) {
    const row = document.querySelector('.dl-task[data-name="' + CSS.escape(name) + '"]');
    if (animate && row) {
      row.classList.add('leaving');
      setTimeout(() => removeDownloadTask(name, false), 300);
      return;
    }
    const idx = downloadTasks.findIndex(x => x.name === name);
    if (idx >= 0) downloadTasks.splice(idx, 1);
    renderDownloadDrawer();
    updateFabVisibility();
  }

  function updateFabVisibility() {
    const active = downloadTasks.some(t => t.status === 'downloading' || t.status === 'waiting');
    $('#dl-fab').classList.toggle('visible', active);
  }

  function toggleDrawer(open) {
    $('#dl-drawer').classList.toggle('open', open);
    $('#dl-overlay').classList.toggle('show', open);
  }

  function renderDownloadDrawer() {
    const list = $('#dl-list');
    const prevPos = new Map();
    [...list.children].forEach(c => prevPos.set(c.dataset.name, c.getBoundingClientRect().top));
    if (!downloadTasks.length) {
      list.innerHTML = '<div class="dl-empty">暂无下载任务</div>';
      return;
    }
    list.innerHTML = '';
    downloadTasks.forEach(t => {
      const row = document.createElement('div');
      row.className = 'dl-task ' + t.status;
      row.dataset.name = t.name;
      const pct = Math.round(t.percent || 0);
      const info = t.status === 'done' ? '✓ 已完成'
        : t.status === 'error' ? '✗ ' + esc(t.error || '下载失败')
        : t.status === 'waiting' ? '等待中…'
        : fmtBytes(t.downloaded) + ' / ' + fmtBytes(t.total) +
          (t.speed ? ' · ' + fmtSpeed(t.speed) : '');
      row.innerHTML =
        '<img class="dl-icon" src="' + esc(t.icon || PROJECT_ICON) + '" onerror="this.src=\'' + PROJECT_ICON + '\'">' +
        '<div class="dl-info">' +
          '<div class="dl-name">' + esc(t.name) +
            '<span class="dl-kind">' + (t.kind === 'addon' ? '插件' : 'Mod') + '</span></div>' +
          '<div class="dl-track"><div class="dl-fill" style="width:' + pct + '%"></div></div>' +
          '<div class="dl-meta">' + info + '</div>' +
        '</div>';
      list.appendChild(row);
    });
    // FLIP: 保留下来的任务从旧位置平滑滑上去
    requestAnimationFrame(() => {
      [...list.children].forEach(c => {
        const old = prevPos.get(c.dataset.name);
        if (old == null) return;
        const dy = old - c.getBoundingClientRect().top;
        if (dy) {
          c.animate([
            { transform: 'translateY(' + dy + 'px)' },
            { transform: 'translateY(0)' },
          ], { duration: 300, easing: 'ease' });
        }
      });
    });
  }

  function startDownloadItem(kind, item) {
    const url = item.dowload_url || item.download_url || item.url;
    if (!url) { toast('下载链接无效', 'error'); return; }
    const name = item.name || 'unknown';
    item.download_count = (Number(item.download_count) || 0) + 1;
    updateDownloadCountDisplay(name, item.download_count);
    addDownloadTask({ name, kind, icon: item.icon_url || PROJECT_ICON });
    toggleDrawer(true);
    if (api && kind === 'addon') {
      api.increase_download_count(kind, name).catch(() => {});
      api.download_addon(name, url).catch(e => { toast('下载失败: ' + e, 'error'); failDownloadTask(name, String(e)); });
    } else if (api) {
      api.increase_download_count(kind, name).catch(() => {});
      api.download_mod(name, url).catch(e => { toast('下载失败: ' + e, 'error'); failDownloadTask(name, String(e)); });
    } else {
      toast('浏览器预览模式', 'warn');
    }
  }

  function updateDownloadCountDisplay(name, count) {
    document.querySelectorAll('.dc-card').forEach(card => {
      const title = card.querySelector('.dc-title');
      if (title && title.textContent.replace(' (暂不可用)', '') === name) {
        const el = card.querySelector('.dc-count');
        if (el) el.textContent = '⬇ ' + count;
      }
    });
  }

  function initDownloadCenter() {
    if (!api) return;
    $$('.dc-tab').forEach(t => t.addEventListener('click', () => {
      $$('.dc-tab').forEach(x => x.classList.remove('active'));
      t.classList.add('active');
      dcCurrentTab = t.dataset.dcTab;
      if (dcCurrentTab === 'addon') displayAddonPage(1);
      else displayModPage(1);
    }));
    loadDCDisplay();
  }

  function loadDCDisplay() {
    const content = $('#dc-content');
    const frame = $('#page-download_center');
    content.innerHTML = '';
    showFrameLoading(frame);
    Promise.all([
      api.get_addon_list().catch(d => ({ pages: [], error: String(d) })),
      api.get_mod_list().catch(d => ({ pages: [], error: String(d) })),
    ]).then(([addonRes, modRes]) => {
      hideFrameLoading(frame);
      dcAddonPages = addonRes.pages || [];
      dcModPages = modRes.pages || [];
      if (dcCurrentTab === 'addon') displayAddonPage(1);
      else displayModPage(1);
    }).catch(e => {
      hideFrameLoading(frame);
      content.innerHTML = '<div class="dc-empty dc-error">⚠ ' + esc(String(e)) + '</div>';
    });
  }

  function displayAddonPage(page) {
    const content = $('#dc-content');
    if (!dcAddonPages.length || page < 1 || page > dcAddonPages.length) {
      content.innerHTML = '<div class="dc-empty">未获取到插件数据</div>';
      renderDCPagination('addon', 1, 1);
      return;
    }
    dcAddonPage = page;
    const items = dcAddonPages[page - 1];
    renderDCPage('addon', items, page, dcAddonPages.length);
  }

  function displayModPage(page) {
    const content = $('#dc-content');
    if (!dcModPages.length || page < 1 || page > dcModPages.length) {
      content.innerHTML = '<div class="dc-empty">未获取到 Mod 数据</div>';
      renderDCPagination('mod', 1, 1);
      return;
    }
    dcModPage = page;
    const items = dcModPages[page - 1];
    renderDCPage('mod', items, page, dcModPages.length);
  }

  function renderDCPage(kind, items, page, totalPage) {
    const content = $('#dc-content');
    content.innerHTML = '';
    if (!items || !items.length) {
      content.innerHTML = '<div class="dc-empty">暂无数据</div>';
      renderDCPagination(kind, page, totalPage);
      return;
    }
    items.forEach(item => content.appendChild(buildDCCard(item, kind)));
    renderDCPagination(kind, page, totalPage);
  }

  function buildDCCard(item, kind) {
    const card = document.createElement('div');
    const disabled = item.disabled;
    card.className = 'dc-card' + (disabled ? ' disabled' : '');
    const authors = item.authors || {};
    const authorHtml = Object.entries(authors).map(([n, u]) =>
      '<a class="dc-author" href="' + esc(u || '#') + '" target="_blank">' + esc(n) + '</a>'
    ).join(' ');
    card.innerHTML =
      '<div class="dc-card-main">' +
        '<img class="dc-icon" src="' + PROJECT_ICON + '" alt="" ' +
          'data-icon-url="' + esc(item.icon_url || '') + '" data-icon-name="' + esc(item.name || '') + '" ' +
          'onerror="this.src=\'' + PROJECT_ICON + '\'">' +
        '<div class="dc-info">' +
          '<div class="dc-title-row">' +
            '<span class="dc-title">' + esc(item.name || '未知') + (disabled ? ' (暂不可用)' : '') + '</span>' +
            '<span class="dc-version">v' + esc(item.version || '?') + '</span>' +
          '</div>' +
          '<div class="dc-desc">' + esc(item.desc || '无描述') + '</div>' +
          (authorHtml ? '<div class="dc-authors">' + authorHtml + '</div>' : '') +
          '<div class="dc-count">⬇ ' + (item.download_count || 0) + '</div>' +
        '</div>' +
      '</div>' +
      '<div class="dc-actions">' +
        '<button class="btn btn-primary btn-download" ' + (disabled ? 'disabled' : '') + '>📥 下载</button>' +
      '</div>';
    if (!disabled) {
      const btn = card.querySelector('.btn-download');
      btn.onclick = () => startDownloadItem(kind, item);
    }
    hydrateIcons(card);
    return card;
  }

  function renderDCPagination(kind, page, totalPage) {
    const displayPage = kind === 'addon' ? displayAddonPage : displayModPage;
    const mk = (id) => {
      const el = document.getElementById(id);
      el.innerHTML = '';
      const info = document.createElement('span');
      info.className = 'dc-page-info';
      info.textContent = '第 ' + page + ' 页，共 ' + totalPage + ' 页';
      el.appendChild(info);
      if (page > 1) {
        const prev = document.createElement('button');
        prev.className = 'btn btn-ghost btn-mini';
        prev.textContent = '← 上一页';
        prev.onclick = () => displayPage(page - 1);
        el.appendChild(prev);
      }
      if (page < totalPage) {
        const next = document.createElement('button');
        next.className = 'btn btn-ghost btn-mini';
        next.textContent = '下一页 →';
        next.onclick = () => displayPage(page + 1);
        el.appendChild(next);
      }
    };
    mk('dc-pagination-top');
    mk('dc-pagination-bottom');
  }

  // ---------------- 工具面板 ----------------
  function openAutoTranslate() {
    if (!api) { toast('浏览器预览模式', 'warn'); return; }
    const existing = document.getElementById('at-panel');
    if (existing) { existing.remove(); return; }
    const panel = document.createElement('div');
    panel.id = 'at-panel';
    panel.className = 'panel-overlay';
    panel.innerHTML =
      '<div class="panel-card panel-card-wide">' +
        '<div class="panel-head"><h3>🤖 自动汉化</h3><button class="btn btn-ghost" id="at-close">✕</button></div>' +
        '<div class="panel-body">' +
          '<div class="at-row"><label>源文本目录</label><input type="text" id="at-source" placeholder="留空使用默认"></div>' +
          '<div class="at-row"><label>输出目录</label><input type="text" id="at-target" placeholder="留空使用默认"></div>' +
          '<div class="at-row"><label>黑名单 (每行一个)</label><textarea id="at-blacklist" rows="4" placeholder="ProjectGSLessonName.json"></textarea></div>' +
          '<div class="progress-track"><div class="progress-fill" id="at-progress"></div></div>' +
          '<div id="at-log" class="at-log"></div>' +
        '</div>' +
        '<div class="panel-foot"><button class="btn btn-primary" id="at-start">🚀 开始</button><button class="btn btn-ghost" id="at-stop">⏹ 停止</button></div>' +
      '</div>';
    document.body.appendChild(panel);
    $('#at-close').onclick = () => panel.remove();
    $('#at-start').onclick = async () => {
      const source = $('#at-source').value.trim();
      const target = $('#at-target').value.trim();
      const blacklist = $('#at-blacklist').value.split('\n').map(s => s.trim()).filter(Boolean);
      toast('自动汉化已启动...', 'info');
      await api.start_auto_translate(source, target, blacklist);
    };
    $('#at-stop').onclick = () => toast('已停止 (需重启生效)', 'info');
  }

  function openFontSelector() {
    if (!api) { toast('浏览器预览模式', 'warn'); return; }
    const existing = document.getElementById('font-panel');
    if (existing) { existing.remove(); return; }
    const panel = document.createElement('div');
    panel.id = 'font-panel';
    panel.className = 'panel-overlay';
    panel.innerHTML =
      '<div class="panel-card panel-card-wide">' +
        '<div class="panel-head"><h3>📝 字体修改</h3><button class="btn btn-ghost" id="font-close">✕</button></div>' +
        '<div class="panel-body">' +
          '<div class="font-tabs"><button class="font-tab active" data-font="context">Context 字体</button><button class="font-tab" data-font="title">Title 字体</button></div>' +
          '<div id="font-info" class="font-info"></div>' +
        '</div>' +
        '<div class="panel-foot"><input type="file" id="font-file" accept=".ttf,.otf" hidden><button class="btn btn-primary" id="font-select">选择字体文件</button><button class="btn btn-ghost" id="font-delete">删除自定义字体</button></div>' +
      '</div>';
    document.body.appendChild(panel);
    $('#font-close').onclick = () => panel.remove();
    let currentFontTab = 'context';
    function refreshFontInfo() {
      const card = panel.querySelector('.panel-card');
      showFrameLoading(card);
      api.get_font_info().then(d => {
        const info = d[currentFontTab] || {};
        $('#font-info').innerHTML = info.exists ? '大小: ' + (info.size / 1024).toFixed(1) + ' KB' : '使用默认字体';
      }).catch(() => {}).finally(() => hideFrameLoading(card));
    }
    $$('.font-tab').forEach(t => t.onclick = () => {
      $$('.font-tab').forEach(x => x.classList.remove('active'));
      t.classList.add('active');
      currentFontTab = t.dataset.font;
      refreshFontInfo();
    });
    $('#font-select').onclick = () => $('#font-file').click();
    $('#font-file').onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = async (ev) => {
        try {
          const bytes = new Uint8Array(ev.target.result);
          let binary = '';
          for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
          const b64 = btoa(binary);
          const r = await api.upload_font(currentFontTab, b64);
          if (r.error) toast('上传失败: ' + r.error, 'error');
          else toast('字体已替换', 'success');
          refreshFontInfo();
        } catch (err) { toast('文件读取失败: ' + err, 'error'); }
      };
      reader.readAsArrayBuffer(file);
    };
    $('#font-delete').onclick = async () => {
      const r = await api.delete_font(currentFontTab);
      if (r.error) toast('删除失败: ' + r.error, 'error');
      else toast('已删除', 'success');
      refreshFontInfo();
    };
    refreshFontInfo();
  }

  function openGradientTool() {
    if (!api) { toast('浏览器预览模式', 'warn'); return; }
    const existing = document.getElementById('gradient-panel');
    if (existing) { existing.remove(); return; }
    const panel = document.createElement('div');
    panel.id = 'gradient-panel';
    panel.className = 'panel-overlay';
    panel.innerHTML =
      '<div class="panel-card panel-card-wide">' +
        '<div class="panel-head"><h3>💻 渐变文本处理器</h3><button class="btn btn-ghost" id="gradient-close">✕</button></div>' +
        '<div class="panel-body">' +
          '<div class="at-row"><label>输入文本</label><textarea id="gradient-input" rows="3" placeholder="输入要添加渐变的文本"></textarea></div>' +
          '<div class="gradient-colors"><div class="at-row"><label>起始颜色</label><input type="color" id="gradient-start" value="#ff0000"></div><div class="at-row"><label>结束颜色</label><input type="color" id="gradient-end" value="#0000ff"></div></div>' +
          '<div class="at-row"><label>渐变度 <span id="gradient-rate-val">2.0</span></label><input type="range" id="gradient-rate" min="0.5" max="5" step="0.1" value="2"></div>' +
          '<div class="at-row"><label>预览</label><div id="gradient-preview" class="gradient-preview"></div></div>' +
          '<div class="at-row"><label>输出 (Unity 富文本)</label><textarea id="gradient-output" rows="3" readonly placeholder="生成的代码会显示在这里"></textarea></div>' +
        '</div>' +
        '<div class="panel-foot"><button class="btn btn-primary" id="gradient-generate">⚡ 生成</button><button class="btn btn-ghost" id="gradient-copy">📋 复制</button></div>' +
      '</div>';
    document.body.appendChild(panel);
    $('#gradient-close').onclick = () => panel.remove();
    $('#gradient-rate').oninput = () => $('#gradient-rate-val').textContent = $('#gradient-rate').value;
    $('#gradient-generate').onclick = async () => {
      const text = $('#gradient-input').value;
      if (!text.trim()) { toast('请输入文本', 'warn'); return; }
      const r = await api.generate_gradient_text(text, $('#gradient-start').value, $('#gradient-end').value, parseFloat($('#gradient-rate').value));
      if (r.error) { toast('生成失败: ' + r.error, 'error'); return; }
      $('#gradient-output').value = r.result;
      $('#gradient-preview').innerHTML = r.result
        .replace(/<color=#([0-9a-fA-F]{3,6})>/g, '<span style="color:#$1">')
        .replace(/<\/color>/g, '</span>');
    };
    $('#gradient-copy').onclick = () => {
      const out = $('#gradient-output').value;
      if (!out) { toast('请先生成', 'warn'); return; }
      navigator.clipboard.writeText(out).then(() => toast('已复制', 'success')).catch(() => toast('复制失败', 'error'));
    };
  }

  function openExtensionTools() {
    if (!api) { toast('浏览器预览模式', 'warn'); return; }
    const existing = document.getElementById('ext-panel');
    if (existing) { existing.remove(); return; }
    const panel = document.createElement('div');
    panel.id = 'ext-panel';
    panel.className = 'panel-overlay';
    panel.innerHTML =
      '<div class="panel-card">' +
        '<div class="panel-head"><h3>🧩 扩展工具</h3><button class="btn btn-ghost" id="ext-close">✕</button></div>' +
        '<div class="panel-body">' +
          '<div class="at-row"><label>开发者工具密钥</label><input type="password" id="ext-key" placeholder="请输入密钥" autofocus></div>' +
          '<div class="dc-empty" style="padding:10px">插件模板 / 打包发布 / 发布 Mod (需密钥)</div>' +
        '</div>' +
        '<div class="panel-foot"><button class="btn btn-primary" id="ext-verify">验证</button></div>' +
      '</div>';
    document.body.appendChild(panel);
    $('#ext-close').onclick = () => panel.remove();
    $('#ext-key').onkeydown = (e) => { if (e.key === 'Enter') $('#ext-verify').click(); };
    $('#ext-verify').onclick = async () => {
      const key = $('#ext-key').value.trim();
      if (!key) { toast('请输入密钥', 'warn'); return; }
      const r = await api.verify_extension_key(key);
      if (r.ok) {
        panel.remove();
        api.open_extension_tools_window().then(ok => {
          toast(ok ? '扩展工具已打开' : '打开失败', ok ? 'success' : 'error');
        });
      } else { toast(r.error || '密钥错误', 'error'); }
    };
  }

  // ---------------- 渲染 ----------------
  function render() {
    const b = BOOT;
    // 版本
    $('#about-version').textContent = b.version;
    $('#stat-version').textContent = b.version;
    // 背景色
    applyTheme(b.bg_color);
    // 项目图标 (后端 data URI, 供下载中心/推荐卡图标回退)
    if (b.icon_uri) {
      PROJECT_ICON = b.icon_uri;
      const heroImg = document.querySelector('.hero-logo img');
      if (heroImg) heroImg.src = b.icon_uri;
      const brandImg = document.querySelector('.brand-icon');
      if (brandImg) brandImg.src = b.icon_uri;
    }
    // 状态芯片
    const gp = $('#chip-gamepath');
    if (b.game_path) { gp.className = 'chip ok'; gp.innerHTML = '<span class="dot"></span><span>游戏路径: ' + esc(shortPath(b.game_path)) + '</span>'; }
    else { gp.className = 'chip warn'; gp.innerHTML = '<span class="dot"></span><span>游戏路径: 未配置</span>'; }
    const sc = $('#chip-source');
    const src = getSettingValue('translate_source');
    if (typeof src === 'number') {
      const opts = getSettingOptions('translate_source');
      sc.innerHTML = '<span class="dot"></span><span>汉化源: ' + esc(opts[src] || '未知') + '</span>';
    }
    // 快捷方式 & 工具
    renderFeatures(b.features);
    renderTools(b.tools);
    // 设置
    renderSettings(b.settings_schema);
    // 欢迎音效提示
    if (IS_BROWSER) toast('浏览器预览模式, 部分功能不可用', 'warn', 4000);
  }

  // ---------------- 主页: 更新内容 / 随机推荐 ----------------
  let PROJECT_ICON = '../../assets/images/icon/icon.png';  // 后端 bootstrap 就绪后替换为 data URI

  function mdToHtml(md) {
    if (!md) return '<span class="changelog-empty">暂无更新内容</span>';
    const lines = String(md).replace(/\r/g, '').split('\n');
    let html = '';
    let inList = false;
    const closeList = () => { if (inList) { html += '</ul>'; inList = false; } };
    for (const raw of lines) {
      const line = raw.trim();
      if (!line) { closeList(); continue; }
      const h = /^(#{1,3})\s+(.*)/.exec(line);
      if (h) { closeList(); const lv = h[1].length + 2; html += '<h' + lv + '>' + esc(h[2]) + '</h' + lv + '>'; continue; }
      const li = /^[-*]\s+(.*)/.exec(line);
      if (li) { if (!inList) { html += '<ul>'; inList = true; } html += '<li>' + esc(li[1]) + '</li>'; continue; }
      closeList();
      html += '<p>' + esc(line) + '</p>';
    }
    closeList();
    return html;
  }

  async function loadHomeExtras() {
    const frame = $('#stat-version-card');
    if (!api) {
      hideFrameLoading(frame);
      return;
    }
    showFrameLoading(frame);
    try {
      const md = await withTimeout(api.get_changelog(), 6000, null);
      // 无论超时/成功/出错, 都离开 "加载中" 占位, 保证内容感知兜底移除圆圈
      const body = $('#changelog-body');
      if (md == null) {
        body.innerHTML = '<span class="changelog-empty">⚠ 更新内容加载超时</span>';
      } else {
        body.innerHTML = mdToHtml(md);
      }
    } catch (e) {
      $('#changelog-body').innerHTML = '<span class="changelog-empty">⚠ 更新内容错误: ' + esc(String(e)) + '</span>';
    } finally {
      hideFrameLoading(frame);
    }
  }

  function pickRecItem(x) {
    return {
      name: x.name || '未知',
      desc: x.desc || '',
      icon_url: x.icon_url || '',
      version: x.version || '',
      download_count: x.download_count || 0,
      authors: x.authors || {},
      url: x.dowload_url || x.download_url || '',
    };
  }

  let recPool = [];

  async function loadRecommend() {
    const frame = $('#rec-card');
    const setMsg = (t) => {
      $('#rec-body').innerHTML = '<span class="changelog-empty">' + t + '</span>';
      setFrameLoading($('#rec-card'), false);
    };
    if (!api) {
      hideFrameLoading(frame);
      setMsg('浏览器预览模式');
      return;
    }
    showFrameLoading(frame);
    let recErr = '';
    try {
      const [a, m] = await withTimeout(Promise.all([
        api.get_addon_list(), api.get_mod_list(),
      ]), 30000, { pages: [], error: 'timeout' });
      if (a && a.error) recErr = '插件列表: ' + a.error + '；';
      if (m && m.error) recErr += 'Mod列表: ' + m.error + '；';
      const addons = ((a && a.pages) || []).flat()
        .filter(x => x && !x.disabled).map(x => ({ item: pickRecItem(x), kind: 'addon' }));
      const mods = ((m && m.pages) || []).flat()
        .filter(x => x && !x.disabled).map(x => ({ item: pickRecItem(x), kind: 'mod' }));
      recPool = addons.concat(mods);
    } catch (e) {
      recErr = String(e && e.message || e);
    }
    // 先保证 rec-body 有内容 (成功渲染或明确错误), 圆圈由"内容感知轮询"在
    // rec-body 有实际内容后自动移除 — 内容没出来, 圆圈就一直在, 绝不提前消失
    if (recPool.length) {
      try {
        renderRecommend(recPool[Math.floor(Math.random() * recPool.length)]);
      } catch (e) {
        setMsg('⚠ 渲染失败: ' + esc(String(e && e.message || e)));
      }
    } else {
      setMsg('⚠ ' + esc(recErr || '暂无推荐 (网络异常或加载超时)'));
    }
  }

  function refreshRecommend() {
    if (recPool.length) {
      renderRecommend(recPool[Math.floor(Math.random() * recPool.length)]);
    } else {
      loadRecommend();
    }
  }

  function renderRecommend(rec) {
    const body = $('#rec-body');
    if (!rec || !rec.item) {
      body.innerHTML = '<span class="changelog-empty">' + esc((rec && rec.error) || '暂无推荐') + '</span>';
      return;
    }
    const it = rec.item;
    const iconUrl = it.icon_url || '';
    const rawAuthors = it.authors;
    const authors = (rawAuthors && typeof rawAuthors === 'object' && !Array.isArray(rawAuthors)) ? rawAuthors : {};
    const authorHtml = Object.entries(authors).map(([n, u]) =>
      '<a class="dc-author" href="' + esc(u || '#') + '" target="_blank">' + esc(n) + '</a>'
    ).join(' ');
    body.innerHTML =
      '<div class="rec-main">' +
        '<img class="rec-icon" src="' + PROJECT_ICON + '" alt="" ' +
          'data-icon-url="' + esc(iconUrl) + '" data-icon-name="' + esc(it.name) + '" ' +
          'onerror="this.src=\'' + PROJECT_ICON + '\'">' +
        '<div class="rec-info">' +
          '<div class="rec-badge">' + (rec.kind === 'addon' ? '🔌 插件' : '🎮 Mod') + '</div>' +
          '<div class="rec-title">' + esc(it.name) +
            (it.version ? ' <span class="rec-ver">v' + esc(it.version) + '</span>' : '') + '</div>' +
          '<div class="rec-count">⬇ ' + (it.download_count || 0) + ' 次下载</div>' +
        '</div>' +
      '</div>' +
      '<div class="rec-desc" title="' + esc(it.desc || '') + '">' + esc(it.desc || '暂无描述') + '</div>' +
      (authorHtml ? '<div class="rec-authors">' + authorHtml + '</div>' : '');
    // 图标全部加载完成后才移除推荐卡圆圈 (推荐"完整"显示后才消失, 不提前)
    const _recCard = $('#rec-card');
    Promise.all(hydrateIcons(body)).finally(() => {
      setFrameLoading(_recCard, false);
    });
    const foot = $('#rec-foot');
    foot.innerHTML = it.url
      ? '<button class="btn btn-primary btn-mini" id="rec-dl">📥 下载</button>'
      : '';
    const dl = $('#rec-dl');
    if (dl) {
      dl.onclick = (e) => {
        e.stopPropagation();
        if (!api) { toast('浏览器预览模式', 'warn'); return; }
        startDownloadItem(rec.kind, it);
      };
    }
    body.onclick = (e) => {
      if (e.target.closest('#rec-dl') || e.target.closest('a')) return;
      refreshRecommend();
    };
  }

  function shortPath(p) {
    p = String(p || '');
    if (p.length <= 28) return p;
    const parts = p.split(/[\\/]/);
    const head = parts.slice(0, 2).join('/');
    return head + '/…/' + parts.slice(-1)[0];
  }

  function applyTheme(color) {
    if (!color) return;
    color = String(color);
    if (/^#[0-9a-fA-F]{6}$/.test(color)) {
      // 主题色只调整窗口底色, 高亮色固定为 vscode 蓝 (避免黑底覆盖 accent)
      document.documentElement.style.setProperty('--bg', color);
      document.documentElement.style.setProperty('--bg-tint', color);
    }
  }

  function shadeColor(hex, pct) {
    const n = parseInt(hex.slice(1), 16);
    let r = (n >> 16) & 255, g = (n >> 8) & 255, bl = n & 255;
    r = Math.max(0, Math.min(255, Math.round(r + r * pct / 100)));
    g = Math.max(0, Math.min(255, Math.round(g + g * pct / 100)));
    bl = Math.max(0, Math.min(255, Math.round(bl + bl * pct / 100)));
    return '#' + ((r << 16) | (g << 8) | bl).toString(16).padStart(6, '0');
  }

  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    const r = (n >> 16) & 255, g = (n >> 8) & 255, bl = n & 255;
    return 'rgba(' + r + ',' + g + ',' + bl + ',' + a + ')';
  }

  // ---------------- 快捷方式 / 工具 ----------------
  let featTotal = 0, featAngle = 0;

  function renderFeatures(features) {
    const stage = $('#features-stage');
    if (!stage) return;
    stage.innerHTML = '';
    const list = (features || []).filter(Boolean);
    featTotal = list.length;
    featAngle = 0;
    if (!featTotal) return;
    list.forEach((f, i) => {
      const wrap = document.createElement('div');
      wrap.className = 'carousel-item';
      const inner = document.createElement('div');
      inner.className = 'carousel-item-inner';
      const bg = f.image_uri || (f.image ? '../../assets/images/features/' + f.image : '');
      const bgHtml = bg ? '<img class="carousel-item-bg" src="' + esc(bg) + '" alt="" draggable="false">' : '';
      inner.innerHTML = bgHtml +
        '<div class="carousel-item-content">' +
          '<div class="lc-ico">' + esc(f.name.split(' ')[0]) + '</div>' +
          '<div class="lc-name">' + esc(f.name.split(' ').slice(1).join(' ') || f.name) + '</div>' +
          '<div class="lc-desc">' + esc(f.desc || '') + '</div>' +
        '</div>';
      inner.ondblclick = () => { if (api) api.open_feature(f.name).catch(e => toast(e, 'error')); else toast('浏览器预览模式', 'warn'); };
      wrap.appendChild(inner);
      stage.appendChild(wrap);
    });
    layoutCarousel(false);
  }

  // CoverFlow 式循环轮播: 卡片沿弧线排列, 中间最大最正, 两侧转向但内容可见, 无限循环
  function layoutCarousel(smooth) {
    const stage = $('#features-stage');
    if (!stage) return;
    const n = featTotal || 1;
    const offset = Math.round(featAngle);
    const X = [0, 270, 480];     // d=0,1,2 的横向位置 (最外侧向内收拢, 避免被窗口裁剪)
    const S = [1, 0.87, 0.68];   // 对应缩放
    const DEPTH = 170, ANGLE = 26;
    const cards = stage.querySelectorAll('.carousel-item');
    cards.forEach((card, i) => {
      let d = (((i - offset) % n) + n) % n;
      if (d > n / 2) d = d - n;
      const prev = card._d;
      const jumped = prev !== undefined && Math.abs(d - prev) > n / 2;
      card._d = d;
      const ad = Math.abs(d);
      const idx = Math.min(ad, 2);
      const x = d < 0 ? -X[idx] : X[idx];
      const scale = S[idx];
      const z = -ad * DEPTH;
      const rot = d * ANGLE;
      card.style.transition = (smooth && !jumped) ? 'transform .5s cubic-bezier(.22,.75,.28,1)' : 'none';
      card.style.transform = 'translate3d(' + x + 'px, 0, ' + z + 'px) rotateY(' + rot + 'deg) scale(' + scale.toFixed(3) + ')';
    });
  }

  function bindFeaturesCarousel() {
    const carousel = $('#features-carousel');
    if (!carousel) return;
    let lock = false;
    // 滚轮: 每格切一张, 无限循环
    carousel.addEventListener('wheel', (e) => {
      e.preventDefault();
      if (lock) return;
      lock = true;
      setTimeout(() => { lock = false; }, 300);
      featAngle += (e.deltaY > 0 ? 1 : -1);
      layoutCarousel(true);
    }, { passive: false });
    // 指针拖拽: 全程跟手 (window 级监听, 移出卡片区也不断), 松手吸附
    let dragging = false, startX = 0, dragBase = 0;
    const onMove = (e) => {
      if (!dragging) return;
      const dx = e.clientX - startX;
      featAngle = dragBase + dx / 200;
      layoutCarousel(false);
    };
    const onUp = () => {
      if (!dragging) return;
      dragging = false;
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      featAngle = Math.round(featAngle);
      layoutCarousel(true);
    };
    carousel.addEventListener('pointerdown', (e) => {
      dragging = true;
      startX = e.clientX;
      dragBase = featAngle;
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
      layoutCarousel(false);
    });
    window.addEventListener('pointercancel', onUp);
  }

  const TOOL_PENDING = [];

  function renderTools(tools) {
    const grid = $('#tools-grid');
    grid.innerHTML = '';
    (tools || []).forEach(t => {
      const pending = TOOL_PENDING.includes(t.id);
      const card = document.createElement('div');
      card.className = 'link-card' + (pending ? ' disabled' : '');
      card.innerHTML = '<div class="lc-ico">' + esc(t.name.split(' ')[0]) + '</div>' +
        '<div class="lc-name">' + esc(t.name.split(' ').slice(1).join(' ') || t.name) + '</div>' +
        '<div class="lc-desc">' + esc(t.desc || '') + '</div>' +
        (pending ? '<div class="lc-desc">🕐 将在后续版本接入 Web UI</div>' : '');
      card.onclick = () => {
        if (pending) { toast('该工具将在后续版本接入 Web UI', 'warn'); return; }
        if (t.page) { switchPage(t.page); return; }
        if (t.id === 'auto_translate') { openAutoTranslate(); return; }
        if (t.id === 'font') { openFontSelector(); return; }
        if (t.id === 'gradient') { openGradientTool(); return; }
        if (t.id === 'extension_tools') { openExtensionTools(); return; }
        if (api) api.open_tool(t.id).catch(e => toast(String(e), 'error'));
        else toast('浏览器预览模式', 'warn');
      };
      grid.appendChild(card);
    });
  }

  // ---------------- 设置 ----------------
  function getSettingValue(key) {
    const s = BOOT.settings_schema[key];
    if (!s) return null;
    if (SETTING_CHANGES[key]) return SETTING_CHANGES[key].value;
    return s.value !== undefined ? s.value : s.default;
  }

  function getSettingOptions(key) {
    const s = BOOT.settings_schema[key];
    return (s && s.options) || [];
  }

  function markChanged(key, value) {
    SETTING_CHANGES[key] = { value };
    const s = BOOT.settings_schema[key];
    if (s && s.key_el) s.key_el.dataset.changed = '1';
  }

  function renderSettings(schema) {
    const container = $('#settings-groups');
    container.innerHTML = '';
    SETTING_CHANGES = {};
    const groups = {};
    Object.keys(schema).forEach(key => {
      const s = schema[key];
      const page = s.page || '系统';
      if (!groups[page]) groups[page] = [];
      groups[page].push({ key, s });
    });
    const order = ['通用', '美化', 'Mod', '翻译', '其它', '系统'];
    const pages = Object.keys(groups).sort((a, b) => {
      const ia = order.indexOf(a), ib = order.indexOf(b);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    pages.forEach(page => {
      const g = document.createElement('div');
      g.className = 'settings-group';
      g.innerHTML = '<div class="sg-title">' + esc(page) + '</div>';
      groups[page].forEach(({ key, s }) => {
        const row = document.createElement('div');
        row.className = 'set-row';
        s.key_el = row;
        row.innerHTML = '<div class="set-info">' +
          '<div class="set-name">' + esc(s.name || key) + '</div>' +
          (s.description ? '<div class="set-desc">' + esc(s.description).replace(/\n/g, '<br>') + '</div>' : '') +
          '</div>';
        row.appendChild(buildControl(key, s));
        g.appendChild(row);
      });
      container.appendChild(g);
    });
  }

  function buildControl(key, s) {
    const wrap = document.createElement('div');
    wrap.className = 'set-control';
    const type = s.type;
    if (type === 'UNABLE_TO_EDIT' || type === 'unable_to_edit') {
      const v = s.value !== undefined ? s.value : s.default;
      const display = typeof v === 'object' ? JSON.stringify(v) : String(v);
      wrap.innerHTML = '<span class="readonly-val">' + esc(display) + '</span>';
      return wrap;
    }
    if (type === 'boolean') {
      wrap.innerHTML = '<label class="switch"><input type="checkbox" ' + (getSettingValue(key) ? 'checked' : '') + '><span class="slider"></span></label>';
      wrap.firstChild.querySelector('input').onchange = e => {
        markChanged(key, e.target.checked);
        if (api) api.set_setting(key, e.target.checked).catch(err => toast(String(err), 'error'));
      };
      return wrap;
    }
    if (type === 'combobox') {
      const opts = s.options || [];
      const sel = document.createElement('select');
      const cur = Number(getSettingValue(key)) || 0;
      opts.forEach((o, i) => {
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = o;
        sel.appendChild(opt);
      });
      sel.selectedIndex = Math.min(cur, opts.length - 1);
      sel.onchange = () => {
        markChanged(key, Number(sel.value));
        if (api) api.set_setting(key, Number(sel.value)).catch(err => toast(String(err), 'error'));
      };
      wrap.appendChild(sel);
      return wrap;
    }
    if (type === 'color') {
      const inp = document.createElement('input');
      inp.type = 'color';
      inp.value = getSettingValue(key) || '#181818';
      inp.onchange = () => {
        markChanged(key, inp.value);
        applyTheme(inp.value);
        if (api) api.set_setting(key, inp.value).catch(err => toast(String(err), 'error'));
      };
      wrap.appendChild(inp);
      return wrap;
    }
    if (type === 'float' || type === 'integer') {
      const min = Number(s.min) || 0, max = Number(s.max) || 100, step = Number(s.step) || 1;
      const range = document.createElement('input');
      range.type = 'range';
      range.min = min; range.max = max; range.step = step;
      range.value = getSettingValue(key);
      const val = document.createElement('span');
      val.className = 'range-val';
      val.textContent = range.value;
      const rw = document.createElement('div');
      rw.className = 'range-wrap';
      rw.appendChild(range); rw.appendChild(val);
      range.oninput = () => { val.textContent = range.value; };
      range.onchange = () => {
        const v = type === 'integer' ? parseInt(range.value, 10) : parseFloat(range.value);
        markChanged(key, v);
        if (api) api.set_setting(key, v).catch(err => toast(String(err), 'error'));
      };
      wrap.appendChild(rw);
      return wrap;
    }
    // string
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.value = String(getSettingValue(key) == null ? '' : getSettingValue(key));
    if (key === 'game_path') {
      const btn = document.createElement('button');
      btn.className = 'btn btn-ghost';
      btn.textContent = '浏览…';
      btn.style.padding = '7px 12px';
      btn.onclick = async () => {
        if (!api) { toast('浏览器预览模式', 'warn'); return; }
        const p = await api.pick_folder();
        if (p) { inp.value = p; markChanged(key, p); api.set_setting(key, p).catch(e => toast(String(e), 'error')); }
      };
      const rw = document.createElement('div');
      rw.style.display = 'flex'; rw.style.gap = '8px'; rw.style.alignItems = 'center';
      rw.appendChild(inp); rw.appendChild(btn);
      wrap.appendChild(rw);
      inp.style.width = '200px';
      inp.onchange = () => { markChanged(key, inp.value); if (api) api.set_setting(key, inp.value).catch(e => toast(String(e), 'error')); };
      return wrap;
    }
    inp.onchange = () => {
      markChanged(key, inp.value);
      if (api) api.set_setting(key, inp.value).catch(err => toast(String(err), 'error'));
    };
    wrap.appendChild(inp);
    return wrap;
  }

  // ---------------- 启动 / 更新 ----------------
  async function onLaunch() {
    if (!api) { toast('浏览器预览模式, 无法启动游戏', 'warn'); return; }
    if (!$('#btn-launch').disabled) {
      $('#btn-launch').disabled = true;
      pipelineReset(true); // 启动游戏: 含"启动游戏"步骤
      try { await api.launch_game(); } catch (e) { toast(String(e), 'error'); pipelineDone(); }
    }
  }

  async function onTranslate() {
    if (!api) { toast('浏览器预览模式, 无法更新汉化', 'warn'); return; }
    if (!$('#btn-translate').disabled) {
      $('#btn-translate').disabled = true;
      pipelineReset(false); // 汉化更新: 不含"启动游戏"步骤
      try { await api.update_translation(); }
      catch (e) { toast(String(e), 'error'); }
      setTimeout(() => { $('#btn-translate').disabled = false; pipelineDone(); }, 800);
    }
  }

  // ---------------- 事件绑定 ----------------
  function bindEvents() {
    // 导航
    $$('.nav-item').forEach(b => b.addEventListener('click', () => switchPage(b.dataset.page)));
    // 主页按钮
    $('#btn-launch').addEventListener('click', onLaunch);
    $('#btn-translate').addEventListener('click', onTranslate);
    // 关于外链
    $$('[data-link]').forEach(b => b.addEventListener('click', () => {
      const url = b.dataset.link;
      if (api) api.open_url(url).catch(e => toast(String(e), 'error'));
      else window.open(url, '_blank');
    }));
    // 设置
    $('#btn-save-settings').addEventListener('click', async () => {
      if (!api) { toast('浏览器预览模式', 'warn'); return; }
      const changes = {};
      Object.keys(SETTING_CHANGES).forEach(k => { changes[k] = SETTING_CHANGES[k].value; });
      try {
        await api.save_settings(changes);
        SETTING_CHANGES = {};
        toast('设置已保存', 'success');
      } catch (e) { toast('保存失败: ' + e, 'error'); }
    });
    $('#btn-reset-settings').addEventListener('click', async () => {
      if (!api) { toast('浏览器预览模式', 'warn'); return; }
      try {
        const schema = BOOT.settings_schema;
        for (const key of Object.keys(schema)) {
          const s = schema[key];
          if (s.type === 'UNABLE_TO_EDIT') continue;
          if (s.default !== undefined) await api.set_setting(key, s.default);
        }
        await api.save_settings({});
        SETTING_CHANGES = {};
        const fresh = await api.get_bootstrap();
        BOOT.settings_schema = fresh.settings_schema;
        renderSettings(BOOT.settings_schema);
        toast('已恢复默认设置', 'success');
      } catch (e) { toast('重置失败: ' + e, 'error'); }
    });
    // 终端
    const term = $('#terminal');
    $('.term-head').addEventListener('click', () => term.classList.toggle('open'));
    $('#btn-copy-term').addEventListener('click', e => {
      e.stopPropagation();
      const text = $$('.term-line', termBody).map(l => l.textContent).join('\n');
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(() => toast('已复制到剪贴板', 'success')).catch(() => toast('复制失败', 'error'));
      else toast('复制失败: 当前环境不支持剪贴板', 'error');
    });
    $('#btn-clear-term').addEventListener('click', e => {
      e.stopPropagation();
      termBody.innerHTML = '';
      if (api) api.clear_terminal().catch(() => {});
    });
    // Mod 管理页
    $('#btn-apply-mods').addEventListener('click', async () => {
      if (!api) { toast('浏览器预览模式', 'warn'); return; }
      try { await api.apply_mods(); toast('正在应用 Mod, 详见终端日志', 'info'); }
      catch (e) { toast('应用失败: ' + e, 'error'); }
    });
    $('#btn-open-mod-dir').addEventListener('click', async () => {
      if (!api) { toast('浏览器预览模式', 'warn'); return; }
      const r = await api.open_mods_dir('dir').catch(e => ({ error: String(e) }));
      if (r && r.error) toast(r.error, 'error');
    });
    $('#btn-open-single-dir').addEventListener('click', async () => {
      if (!api) { toast('浏览器预览模式', 'warn'); return; }
      const r = await api.open_mods_dir('single').catch(e => ({ error: String(e) }));
      if (r && r.error) toast(r.error, 'error');
    });
    $('#btn-open-mod-window').addEventListener('click', async () => {
      if (!api) { toast('浏览器预览模式', 'warn'); return; }
      const ok = await api.open_mod_manager_window().catch(() => false);
      toast(ok ? '独立 Mod 管理器已打开' : '打开失败, 详见终端', ok ? 'success' : 'error');
    });
    termBody.addEventListener('scroll', () => {
      termAutoScroll = (termBody.scrollTop + termBody.clientHeight >= termBody.scrollHeight - 4);
    });
    // 下载任务抽屉
    $('#dl-fab').addEventListener('click', () => toggleDrawer(!$('#dl-drawer').classList.contains('open')));
    $('#dl-close').addEventListener('click', () => toggleDrawer(false));
    $('#dl-overlay').addEventListener('click', () => toggleDrawer(false));
    // 背景点击预览用
    window.addEventListener('resize', () => {});
  }

  // ---------------- 3D 鼠标聚焦倾斜 (主页全局跟随, 其他页面仅悬浮) ----------------
  const TILT_SEL = '.card, .link-card, .dc-card, .hero, .chip, .dc-tab';
  let tiltRAF = null;
  let tiltMX = 0;
  let tiltMY = 0;
  function applyTiltBase() {
    document.querySelectorAll(TILT_SEL).forEach(el => {
      // 主页控件保留基准倾角; 其他页面控件还原无变形
      el.style.transform = el.closest('#page-home')
        ? 'perspective(900px) rotateX(2deg) rotateY(-1deg)'
        : '';
    });
  }
  function applyTiltFrame() {
    tiltRAF = null;
    const mx = tiltMX;
    const my = tiltMY;
    document.querySelectorAll(TILT_SEL).forEach(el => {
      const r = el.getBoundingClientRect();
      if (!r.width) return;
      const inHome = !!el.closest('#page-home');
      const hovered = el.matches(':hover');
      if (!inHome && !hovered) {
        if (el.style.transform) el.style.transform = '';
        return;
      }
      const x = Math.max(-1, Math.min(1, (mx - (r.left + r.width / 2)) / (r.width / 2)));
      const y = Math.max(-1, Math.min(1, (my - (r.top + r.height / 2)) / (r.height / 2)));
      const s = hovered ? ' scale(1.02)' : '';
      el.style.transform = 'perspective(900px) rotateY(' + (x * 3.5).toFixed(2) + 'deg) rotateX(' +
        (-y * 3.5 + (inHome ? 2 : 0)).toFixed(2) + 'deg)' + s;
    });
  }
  function applyTilt() {
    applyTiltBase();
    document.addEventListener('mousemove', (e) => {
      tiltMX = e.clientX;
      tiltMY = e.clientY;
      if (!tiltRAF) tiltRAF = requestAnimationFrame(applyTiltFrame);
    });
    document.addEventListener('mouseleave', () => {
      applyTiltBase();
    });
  }

  // ---------------- 背景 ----------------
  function applyBackgrounds(uris) {
    if (!uris || !uris.length) return;
    let idx = 0;
    const layer = $('#bg-layer');
    const img = new Image();
    img.onload = () => {
      layer.style.backgroundImage = 'url(' + uris[idx] + ')';
      layer.classList.add('show-img');
    };
    img.src = uris[0];
    setInterval(() => {
      if (!uris.length) return;
      idx = (idx + 1) % uris.length;
      const im2 = new Image();
      im2.onload = () => {
        layer.style.backgroundImage = 'url(' + uris[idx] + ')';
      };
      im2.src = uris[idx];
    }, 25000);
  }

  // ---------------- 初始化 ----------------
  async function init() {
    // pywebview 注入时机不定, 每次初始化都重新探测
    api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
    IS_BROWSER = !api;
    // 立即显示主页, 让推荐卡/版本卡圆圈一开始就可见 (否则在 display:none 页面里转, 用户看不到)
    switchPage('home');
    // 主页加载最早触发, 独立于 bindEvents/applyTilt/BOOT/render,
    // 任何后续步骤出错都不会阻断, 预置 spinner 必被 finally 移除
    loadHomeExtras().catch(e => console.error('主页加载失败:', e));
    loadRecommend().catch(e => console.error('推荐加载失败:', e));
    try {
      bindEvents();
      applyTilt();
      bindFeaturesCarousel();
    } catch (e) {
      console.error('UI 初始化出错:', e);
    }
    try {
      if (api) {
        BOOT = await withTimeout(api.get_bootstrap(), 8000, null);
        if (!BOOT) { BOOT = MOCK; toast('后端响应超时, 已进入预览模式', 'error', 5000); }
        withTimeout(api.get_terminal(), 5000, []).then(lines => (lines || []).forEach(l => addLog(l))).catch(() => {});
        withTimeout(api.get_backgrounds(), 6000, []).then(applyBackgrounds).catch(() => {});
      } else {
        BOOT = MOCK;
      }
    } catch (e) {
      console.error(e);
      BOOT = MOCK;
      toast('后端初始化失败: ' + String(e), 'error', 6000);
      hideFrameLoading($('#stat-version-card'));
      hideFrameLoading($('#rec-card'));
      $('#changelog-body').innerHTML = '<span class="changelog-empty">初始化失败: ' + esc(String(e)) + '</span>';
      $('#rec-body').innerHTML = '<span class="changelog-empty">初始化失败</span>';
    }
    try {
      render();
    } catch (e) {
      console.error('render 出错:', e);
    }
    applyTiltBase();
    // 锁定初始窗口内容宽度: 最大化/缩放窗口后控件保持初始大小并居中
    const firstPage = document.querySelector('.page');
    if (firstPage) {
      document.documentElement.style.setProperty('--page-w', Math.floor(firstPage.getBoundingClientRect().width) + 'px');
    }
  }

  // pywebview 注入 window.pywebview 存在时序竞态, 等待 pywebviewready
  if (api) {
    init();
  } else {
    window.addEventListener('pywebviewready', init, { once: true });
    // 浏览器预览兜底: 无 pywebview 环境 3 秒后进入 Mock 模式
    setTimeout(() => { if (!BOOT) { init(); } }, 3000);
  }
})();