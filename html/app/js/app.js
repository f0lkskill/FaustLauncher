/* ============================================================
   FaustLauncher Web UI — 前端逻辑
   浏览器直接打开 index.html 时使用内置 Mock 数据预览。
   顶层函数/变量直接位于全局命名空间 (无闭包包裹), 便于插件扩展直接调用内部 API。
   ============================================================ */
'use strict';

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
      const msg = (r && r.message) || String(r);
      const st = (r && r.stack) ? '\n' + r.stack.split('\n').slice(0, 6).join('\n') : '';
      show('ASYNC', msg + st);
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
      { id: 'custom_translation', name: '🔧 自定义汉化', desc: '可视化编辑 lang 下任意 JSON 文本\n一键编辑替换汉化文本\n自动记录差异性文本，汉化更新也不丢失修改内容！', image: 'custom_translation.png' },
      { id: 'gradient', name: '💻 渐变文本处理器', desc: '生成 Unity 富文本渐变色代码', image: 'gradient.png' },
      { id: 'folder_link', name: '📂 文件夹超链接', desc: '创建符号链接, 转移C盘资源文件', image: 'folder_link.png' },
      { id: 'nyos', name: '📖 今日指令', desc: '获取食指的最新指令\n仅供娱乐，请勿上升到指令成瘾。', image: 'nyos.png' },
      { id: 'extension_tools', name: '🧩 扩展工具', desc: '插件模板 / 打包发布\n给开发者提供的工具\n需要输入开发者密钥。', image: 'extension_tools.png' },
      { id: 'font', name: '📝 字体修改', desc: '选择字体替换汉化包字体', image: 'font.png' },
      // { id: 'auto_translate', name: '🤖 自动汉化', desc: '思知 AI 批量剧情文本翻译' },
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
  // 项目图标 (后端 bootstrap 就绪后替换为 data URI, 供下载中心/推荐卡/关于页图标回退)
  let PROJECT_ICON = '../../assets/images/icon/icon.png';
  let SETTING_CHANGES = {};   // key -> {value, touched}
  let currentPage = 'home';
  let pipeline = {
    running: false,
    currentIdx: -1,
    steps: [],
  };

  // 完整流水线 (启动游戏) / 汉化更新流水线 (不含启动游戏)
  // 左侧列表保留各步骤专属图标; 右侧详情大图标统一为火箭
  const STEPS_FULL = [
    { key: 'prepare', label: '准备检查', icon: '🔍' },
    { key: 'download', label: '下载汉化包', icon: '📥' },
    { key: 'resource', label: '检查资源', icon: '🗂️' },
    { key: 'bubble', label: '下载气泡', icon: '💬' },
    { key: 'install', label: '安装汉化', icon: '📦' },
    { key: 'mods', label: '更新插件/Mod', icon: '🧩' },
    { key: 'launch', label: '启动游戏', icon: '🚀' },
  ];
  // 汉化更新流水线: 不含"更新插件/Mod"和"启动游戏" (汉化更新不重载插件、不启动游戏)
  const STEPS_TRANSLATE = STEPS_FULL.filter(s => s.key !== 'launch' && s.key !== 'mods');

  // 流水线右侧详情文案 (fn 参数可拿当前汉化源, 区分 OurPlay / 零协会)
  function isOurPlaySource() {
    return Number(getSettingValue('translate_source') || 0) !== 0;
  }
  const STEP_DETAILS = {
    prepare: () => '正在检查游戏路径与运行环境...',
    download: () => isOurPlaySource()
      ? '正在从 OurPlay 服务器下载最新汉化包...'
      : '正在从零协会社区下载最新汉化包...',
    resource: () => '正在检查云端资源更新 (字体/素材)...',
    bubble: () => '正在下载战斗气泡汉化文本...',
    install: () => isOurPlaySource()
      ? '正在校验并转码 OurPlay 汉化包...'
      : '正在解压并将汉化文件合并到游戏目录...',
    mods: () => '正在对比云端版本, 更新已安装的插件与 Mod...',
    launch: () => '正在启动边狱巴士...',
  };

  // 更新流水线右侧详情区 (图标 + 文本)
  function updatePipeDetail(stepKey) {
    const icoEl = $('#pipe-detail-ico');
    const txtEl = $('#pipe-detail-text');
    if (!icoEl || !txtEl) return;
    const step = pipeline.steps.find(s => s.key === stepKey);
    icoEl.innerHTML = step ? esc(step.icon) : '';
    const fn = STEP_DETAILS[stepKey];
    txtEl.textContent = fn ? fn() : (step ? step.label : '');
  }

  // 流水线下载进度 (汉化包/资源/气泡/插件Mod): 右侧详情下方进度条
  function updatePipeDownloadProgress(data) {
    const box = $('#pipe-detail-dl');
    if (!box || !pipeline.running) return;
    box.hidden = false;
    const pct = Math.max(0, Math.min(100, Number(data.percent) || 0));
    const fill = $('#pipe-dl-fill');
    if (fill) fill.style.width = pct + '%';
    const meta = $('#pipe-dl-meta');
    if (meta) {
      meta.textContent = (data.downloaded != null && data.total != null)
        ? fmtBytes(data.downloaded) + ' / ' + fmtBytes(data.total) +
          (data.speed ? ' · ' + fmtSpeed(data.speed) : '')
        : pct.toFixed(0) + '%';
    }
  }

  function hidePipeDownloadProgress() {
    const box = $('#pipe-detail-dl');
    if (box) box.hidden = true;
    const fill = $('#pipe-dl-fill');
    if (fill) fill.style.width = '0%';
  }

  // 流水线中按下载任务名, 把右侧大图标换成对应 Mod/插件的真实图标
  function setPipeDetailIconByTask(taskName) {
    const icoEl = $('#pipe-detail-ico');
    if (!icoEl || !taskName) return;
    // 已是该图标则跳过
    if (icoEl.dataset.task === taskName) return;
    let iconUrl = '';
    const find = (arr) => {
      const hit = (arr || []).find(it => it.name === taskName);
      return hit ? hit.icon_url || '' : '';
    };
    iconUrl = find(dcAddonItems) || find(dcModItems);
    icoEl.dataset.task = taskName;
    if (!iconUrl) return;   // 找不到云端图标则保留步骤默认图标
    withTimeout(api.get_icon(iconUrl, taskName), 6000, '').then(uri => {
      if (uri && icoEl.dataset.task === taskName) {
        icoEl.innerHTML = '<img src="' + uri + '" alt="">';
      }
    }).catch(() => {});
  }

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

  // ---------------- 音效 (浏览器内核播放) ----------------
  const _soundUris = { welcome: '', click: '' };
  let _welcomePending = false;
  let _uiTransitionDone = false;
  let _welcomePlayed = false;

  function preloadSounds() {
    if (!api) return;
    withTimeout(api.get_sound('welcome'), 6000, '').then(u => {
      _soundUris.welcome = u;
      if (u && _uiTransitionDone) playWelcomeSound();
    }).catch(() => {});
    withTimeout(api.get_sound('click'), 6000, '').then(u => { _soundUris.click = u; }).catch(() => {});
  }

  function tryWelcome() {
    if (!_soundUris.welcome || !_welcomePending || _welcomePlayed) return;
    try {
      const a = new Audio(_soundUris.welcome);
      a.volume = 0.8;
      const p = a.play();
      if (p && p.then) p.then(() => { _welcomePending = false; _welcomePlayed = true; }).catch(() => {});
      else { _welcomePending = false; _welcomePlayed = true; }
    } catch (e) {}
  }

  function playUISound(kind) {
    if (kind === 'click' && BOOT && BOOT.settings_schema && !getSettingValue('click_sound')) return;
    const uri = _soundUris[kind];
    if (!uri) return;
    try {
      const a = new Audio(uri);
      a.volume = 0.8;
      a.play().catch(() => {});
    } catch (e) {}
  }

  function playWelcomeSound() {
    if (_welcomePlayed) return;
    _uiTransitionDone = true;
    _welcomePending = true;
    if (!_soundUris.welcome) return;
    tryWelcome();
  }

  // 全局点击音效 (覆盖几乎所有交互控件; 节流; 排除打字/滚动/气泡/通知/遮罩)
  function bindClickSound() {
    let last = 0;
    document.addEventListener('click', (e) => {
      const t = e.target;
      if (!t || !t.closest) return;
      if (t === document.body || t === document.documentElement) return;
      // autoplay 被拒时: 用户首次交互后补播欢迎音效
      if (_welcomePending) { tryWelcome(); return; }
      const now = Date.now();
      if (now - last < 40) return;
      if (t.classList && t.classList.contains('panel-overlay')) return;   // 遮罩本身
      if (t.closest('#term-body, #char-bubble, .toast')) return;
      last = now;
      playUISound('click');
    });
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
    if (termBody) {
      termBody.appendChild(div);
      while (termBody.children.length > 1500) termBody.firstChild.remove();
      if (termAutoScroll) termBody.scrollTop = termBody.scrollHeight;
    }
    handlePipelineLog(line);
  }

  window.__onLog = function (text) { addLog(text); };
window.__onTrayHint = function (text) { toast(text, 'info', 5000); };
// 卸载/安装插件/Mod 后由后端通知: 立即刷新已安装状态 (下载中心/主页每日推荐/资源管理)
window.__onResChanged = function (kind) {
  if (typeof downloadedSeen !== 'undefined') downloadedSeen.clear();
  // 资源管理: 仅当前在资源管理页才重刷, 保持分区/按钮组/搜索状态 (不在页内不强制刷新)
  if (currentPage === 'mod_addon' && typeof refreshMods === 'function') {
    refreshMods(true).then(() => { if (typeof syncResActions === 'function') syncResActions(); });
  }
  if (typeof renderDCList === 'function') {
    const dcList = document.getElementById('dc-list');
    if (dcList) renderDCList();
  }
  if (typeof _currentRec !== 'undefined' && _currentRec && typeof renderRecommend === 'function') {
    renderRecommend(_currentRec);
  }
};
// 后端自动设置游戏路径后同步前端 (设置页控件 + 首页路径 chip)
window.__onPathSynced = function () {
  if (typeof updatePathChip === 'function') updatePathChip();
  if (api) {
    api.get_setting('game_path').then(v => {
      if (v !== undefined && v !== null) {
        const inp = document.querySelector('[data-setting="game_path"] input');
        if (inp && inp.value !== String(v)) inp.value = String(v);
      }
    }).catch(() => {});
  }
};
// 卸载/删除失败 (如文件被占用) 时由后端通知
window.__onResError = function (msg) { toast('⚠ ' + msg, 'error', 6000); };

  window.__onEvent = function (event, data) {
    if (event === 'progress') {
      if (data && data.task) {
        updateDownloadTask(data.task, data);
        // 流水线 mods 阶段: 右侧详情逐个显示正在更新的 Mod/插件 (图标+进度+名称)
        const cur = pipeline.steps[pipeline.currentIdx];
        if (pipeline.running && cur && cur.key === 'mods') {
          updatePipeDownloadProgress(data);
          setPipeDetailIconByTask(data.task);
          const txtEl = $('#pipe-detail-text');
          if (txtEl) txtEl.textContent = '正在更新 ' + data.task + ' ...';
        }
        return;
      }
      // 汉化包/资源/气泡等主流程下载: 仅更新右侧详情进度条
      if (pipeline.running) updatePipeDownloadProgress(data);
    } else if (event === 'status') {
      if (data && typeof data === 'object' && data.task) {
        addLog('⟳ ' + String(data.text || ''));
        // 流水线运行中: 带 task 的状态逐项更新详情 (图标按任务名匹配云端图标)
        if (pipeline.running && data.text) {
          const txtEl = $('#pipe-detail-text');
          if (txtEl) txtEl.textContent = String(data.text);
          setPipeDetailIconByTask(data.task);
        }
        if (/(失败|错误|❌|出错)/.test(String(data.text || ''))) {
          failDownloadTask(data.task, String(data.text || '').slice(0, 80));
        }
        return;
      }
      // 对象形式 {text, icon}: 启动子步骤进度 → 更新流水线详情 (图标+文本)
      let text = data, icon = null;
      if (data && typeof data === 'object') { text = data.text || ''; icon = data.icon || null; }
      if (text) addLog('⟳ ' + String(text));
      if (pipeline.running && text) {
        const txtEl = $('#pipe-detail-text');
        if (txtEl) txtEl.textContent = String(text);
        const icoEl = $('#pipe-detail-ico');
        if (icoEl && icon) { icoEl.innerHTML = esc(icon); icoEl.dataset.task = ''; }
      }
    } else if (event === 'step') {
      // 若流水线未启动 (如启动时自动汉化更新), 自动显示并启动流水线
      if (!pipeline.running) pipelineReset(false);
      // 后端显式步骤推进 (与真实进度同步; 不再依赖日志关键词, 避免顺序错乱)
      const s = data && data.step;
      const idx = pipeline.steps.findIndex(x => x.key === s);
      if (idx >= 0 && idx > pipeline.currentIdx) {
        setPipelineStepDone(pipeline.currentIdx, true);
        pipeline.currentIdx = idx;
        setStep(idx, 'active');
        updatePipeDetail(s);
        hidePipeDownloadProgress();
      }
    } else if (event === 'pipeline_done') {
      // 自动流程 (启动时汉化更新) 完成后恢复按钮与流水线状态
      try { setPipelineButtonsDisabled(false); } catch (e) {}
      pipelineDone();
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
      // 状态统一由右侧详情面板显示
      hidePipeDownloadProgress();
      const icoEl = $('#pipe-detail-ico'), txtEl = $('#pipe-detail-text');
      if (icoEl) { icoEl.innerHTML = esc('🎮'); icoEl.dataset.task = ''; }
      if (txtEl) txtEl.textContent = '游戏已启动';
      // 游戏运行中保持按钮互斥 (退出后由 pipelineDone 恢复)
    } else if (event === 'game_exited') {
      pipelineDone();
      const icoEl = $('#pipe-detail-ico'), txtEl = $('#pipe-detail-text');
      if (icoEl) icoEl.innerHTML = esc('🎮');
      if (txtEl) txtEl.textContent = '游戏已退出';
    } else if (event === 'game_timeout') {
      pipelineError();
      const icoEl = $('#pipe-detail-ico'), txtEl = $('#pipe-detail-text');
      if (icoEl) icoEl.innerHTML = esc('❌');
      if (txtEl) txtEl.textContent = '等待游戏启动超时, 请检查游戏是否正常安装';
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
    // 第一步立即高亮 (修复: 此前 prepare 永远不会被点亮, 看起来第一/二步顺序反了)
    pipeline.currentIdx = 0;
    setStep(0, 'active');
    updatePipeDetail(pipeline.steps[0].key);
    hidePipeDownloadProgress();
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
    updatePipeDetail(pipeline.steps[idx].key);
  }

  function pipelineError() {
    // 状态统一由右侧详情面板显示
    const icoEl = $('#pipe-detail-ico'), txtEl = $('#pipe-detail-text');
    if (icoEl) { icoEl.innerHTML = esc('❌'); icoEl.dataset.task = ''; }
    if (txtEl) txtEl.textContent = '启动过程中出现错误, 详见终端';
    hidePipeDownloadProgress();
    const i = pipeline.currentIdx;
    if (i >= 0) setStep(i, 'active'); // 保留高亮
    setPipelineButtonsDisabled(false);
  }

  function pipelineDone() {
    pipeline.running = false;
    pipeline.steps.forEach((_, i) => setStep(i, 'done'));
    const icoEl = $('#pipe-detail-ico'), txtEl = $('#pipe-detail-text');
    if (icoEl) { icoEl.innerHTML = esc('✅'); icoEl.dataset.task = ''; }
    // 区分流程: 含"启动游戏"步骤的是完整启动流程, 否则是汉化更新流程
    const isLaunchFlow = pipeline.steps.some(s => s.key === 'launch');
    if (txtEl) txtEl.textContent = isLaunchFlow ? '启动流程全部完成' : '汉化更新完成';
    hidePipeDownloadProgress();
    setPipelineButtonsDisabled(false);
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
    const wrap = $('#pipe-steps');
    if (wrap) wrap.innerHTML = '';
    const icoEl = $('#pipe-detail-ico');
    if (icoEl) icoEl.dataset.task = '';
    hidePipeDownloadProgress();
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

  // 轻量细节提示: 匹配日志更新右侧文本, 但绝不推进步骤 (步骤完全由后端 _push_step 驱动)
  const PIPE_TEXT_HINTS = [
    { re: /转码/, text: 'OurPlay 汉化包转码中, 请稍候...' },
    { re: /核对汉化版本/, text: '正在核对汉化版本...' },
    { re: /检测到新的汉化版本/, text: '发现新版汉化, 正在应用更新...' },
    { re: /已是最新版本，无需更新|已是最新版本, 无需更新/, text: '汉化已是最新, 正在校验文件...' },
    { re: /解压/, text: '正在解压文件...' },
    { re: /合并汉化文件|安装到|写入汉化文件|复制汉化文件/, text: '正在将汉化文件合并到游戏目录...' },
    { re: /写回本地版本信息/, text: '正在登记汉化版本信息...' },
    { re: /更新字体资源|ChineseFont/, text: '正在更新字体资源...' },
    { re: /清理下载缓存|清理中间产物/, text: '正在清理下载缓存...' },
    { re: /对比云端插件与 Mod 版本|均为最新版本/, text: '插件与 Mod 均为最新版本' },
    { re: /重载插件/, text: '正在重载插件...' },
  ];

  function applyPipeTextHints(line) {
    const txtEl = $('#pipe-detail-text');
    if (!txtEl) return;
    for (const h of PIPE_TEXT_HINTS) {
      if (h.re.test(line)) { txtEl.textContent = h.text; return; }
    }
  }

  function handlePipelineLog(line) {
    if (!pipeline.running) return;
    if (/错误|失败|出错|❌/.test(line)) {
      if (!/汉化包下载失败|启动游戏失败/.test(line) || /下载过程中出错/.test(line)) {
        pipelineError();
      }
      return;
    }
    // 步骤推进完全信任后端 _push_step; 日志仅用于细节文本提示
    applyPipeTextHints(line);
  }

  // ---------------- 页面导航 ----------------
  let resInited = false;   // 资源管理页首次进入标记 (默认插件模式)

  function switchPage(name) {
    currentPage = name;
    // addLog('[页面] 切换到 ' + name);
    $$('.page').forEach(p => p.classList.remove('active'));
    const target = document.getElementById('page-' + name);
    if (target) target.classList.add('active');
    $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.page === name));
    $('#main').scrollTop = 0;
    if (name === 'mod_addon') {
      // 首次进入: 强制插件模式并加载对应按钮组 (之后保持用户选择)
      if (!resInited) {
        resInited = true;
        resKind = 'addon';
        $$('.res-tab').forEach(x => x.classList.toggle('active', x.dataset.kind === 'addon'));
        syncResActions();
      }
      refreshMods();
    }
    if (name === 'download_center') {
      // 无条件清空已安装缓存并重测本地 (资源中心删除插件/Mod 后进入立即同步)
      downloadedSeen.clear();
      if (dcAddonItems.length || dcModItems.length) {
        renderDCList();
      } else {
        initDownloadCenter();
      }
    }
    if (name === 'about') {
      if (!aboutData) loadAbout();
      else setAboutIndex(aboutIdx);
    }
  }

  // ---------------- 资源管理 (插件/Mod) ----------------
  let resKind = 'addon';          // 当前分区: addon | mod
  let resPage = 1;                // 当前页
  const RES_PAGE_SIZE = 5;        // 每页最多 5 个
  let resSearch = '';             // 资源管理搜索词
  let resAddons = [];             // 插件列表
  let resMods = [];               // Mod 列表

  // 按当前分区同步按钮组显示
  function syncResActions() {
    const a = $('#res-actions-addon'), m = $('#res-actions-mod');
    if (a) a.hidden = resKind !== 'addon';
    if (m) m.hidden = resKind !== 'mod';
  }

  function bindResReinstallButtons() {
    const addonBtn = $('#btn-reinstall-addon');
    const modBtn = $('#btn-reinstall-mod');
    if (addonBtn) addonBtn.onclick = () => {
      const dirs = resAddons.filter(x => x.reinstall_available).map(x => x.dir || x.name);
      if (dirs.length) confirmReinstall('addon', dirs, '插件');
      else toast('缓存中没有可精确匹配的插件', 'warn');
    };
    if (modBtn) modBtn.onclick = () => {
      const dirs = resMods.filter(x => x.reinstall_available).map(x => x.dir || x.name);
      if (dirs.length) confirmReinstall('mod', dirs, 'Mod');
      else toast('缓存中没有可精确匹配的 Mod', 'warn');
    };
  }

  async function refreshMods(keepPage) {
    if (!api) { toast('浏览器预览模式', 'warn'); return; }
    try {
      const d = await api.get_mods_data();
      resAddons = d.addons || [];
      resMods = d.dir_mods || [];
      if (!keepPage) resPage = 1;
      renderResList();
      syncResActions();   // 保持按钮组与当前分区一致
      bindResReinstallButtons();
    } catch (e) {
      const list = $('#res-list');
      if (list) list.innerHTML = '<div class="res-empty">读取失败: ' + esc(String(e)) + '</div>';
    }
  }

  function confirmReinstall(kind, dirs, label) {
    const panel = document.createElement('div');
    panel.className = 'panel-overlay';
    panel.innerHTML = '<div class="panel-card"><div class="panel-head"><h3>确认重装' + label + '</h3><button class="panel-close">✕</button></div>' +
      '<div class="panel-body"><p>将删除本地资源，并使用启动时缓存的云端信息重新安装。是否继续？</p></div>' +
      '<div class="panel-foot"><button class="btn btn-ghost" data-no>取消</button><button class="btn btn-primary" data-yes>确认重装</button></div></div>';
    document.body.appendChild(panel);
    const close = () => closePanel(panel);
    panel.querySelector('.panel-close').onclick = close;
    panel.querySelector('[data-no]').onclick = close;
    panel.querySelector('[data-yes]').onclick = async () => {
      const btn = panel.querySelector('[data-yes]');
      btn.disabled = true;
      const r = await api.reinstall_resources(kind, dirs).catch(e => ({ error: String(e) }));
      if (r && r.error) toast('重装失败: ' + r.error, 'error');
      else toast('已开始重装' + label, 'info', 3000);
      close();
    };
  }

  function renderResList() {
    const list = $('#res-list');
    if (!list) return;
    list.innerHTML = '';
    let items = resKind === 'addon' ? resAddons : resMods;
    if (resSearch) {
      const kw = resSearch.toLowerCase();
      items = items.filter(it =>
        (it.name || '').toLowerCase().includes(kw) ||
        (it.description || '').toLowerCase().includes(kw));
    }
    const totalPages = Math.max(1, Math.ceil(items.length / RES_PAGE_SIZE));
    if (resPage > totalPages) resPage = totalPages;
    const pageItems = items.slice((resPage - 1) * RES_PAGE_SIZE, resPage * RES_PAGE_SIZE);
    if (!pageItems.length) {
      list.innerHTML = '<div class="res-empty">' + (resKind === 'addon' ? '暂无插件 (addons/ 目录)' : '暂无 Mod (mods/ 目录)') + '</div>';
    } else {
      pageItems.forEach((item, i) => { const c = buildResCard(item); if (c) { c.style.animationDelay = (i * 0.05) + 's'; list.appendChild(c); } });
    }
    renderResPagination($('#res-pagination'), items.length, totalPages);
  }

  function renderResPagination(pagination, totalItems, totalPages) {
    if (!pagination) return;
    pagination.innerHTML = '';
    const prev = document.createElement('button');
    prev.textContent = '←';
    prev.disabled = resPage <= 1;
    prev.onclick = () => { if (resPage > 1) { resPage--; renderResList(); } };
    pagination.appendChild(prev);
    for (let i = 1; i <= totalPages; i++) {
      const b = document.createElement('button');
      b.textContent = i;
      if (i === resPage) b.classList.add('active');
      b.onclick = () => { resPage = i; renderResList(); };
      pagination.appendChild(b);
    }
    const next = document.createElement('button');
    next.textContent = '→';
    next.disabled = resPage >= totalPages;
    next.onclick = () => { if (resPage < totalPages) { resPage++; renderResList(); } };
    pagination.appendChild(next);
  }

  // 作者链接渲染 (可点击超链接)
  function authorLinksHtml(links) {
    if (!links || !links.length) return '';
    return links.map(l =>
      '<a class="res-author-link" href="' + esc(l.url || '#') + '" target="_blank" onclick="event.stopPropagation()">' + esc(l.name) + '</a>'
    ).join(' · ');
  }

  // 卡片 3D 跟随鼠标: 容器级事件委托 (避免卡片边缘因 transform 导致的抽搐闪烁)
  function addCardTilt(card) {
    card.addEventListener('mousemove', (e) => {
      const r = card.getBoundingClientRect();
      const px = Math.max(-0.5, Math.min(0.5, (e.clientX - r.left) / r.width - 0.5));
      const py = Math.max(-0.5, Math.min(0.5, (e.clientY - r.top) / r.height - 0.5));
      // 角度减半 + 死区收缩, 边缘不会把指针"甩出"卡片造成闪烁
      card.style.transform = 'perspective(600px) rotateY(' + (px * 7).toFixed(2) +
        'deg) rotateX(' + (-py * 6).toFixed(2) + 'deg)';
    });
    card.addEventListener('mouseleave', () => {
      card.style.transform = '';   // 瞬间复位, 避免平滑过渡造成"3d聚焦后恢复"的视觉
    });
    card.addEventListener('mouseenter', () => { card.style.transition = 'none'; });
  }

  // 资源卡片: 下载中心样式, 图标用目录下图片, 名字旁启用/禁用标识, hover 渐变描边 + 3D 跟随
  function buildResCard(item) {
    const name = item.name || '未知';
    const enabled = !!item.enabled;
    const desc = item.description || '（无描述）';
    const ver = item.version || '';
    const card = document.createElement('div');
    card.className = 'res-card' + (enabled ? '' : ' disabled');
    card.innerHTML =
      '<div class="res-card-main">' +
        '<img class="res-icon" src="' + (item.icon || PROJECT_ICON) + '" alt="" onerror="this.src=\'' + PROJECT_ICON + '\'">' +
        '<div class="res-info">' +
          '<div class="res-title-row">' +
            '<span class="res-title">' + esc(name) +
              '<span class="res-state-badge ' + (enabled ? 'on' : 'off') + '">' + (enabled ? '已启用' : '已禁用') + '</span>' +
            '</span>' +
            (ver ? '<span class="res-ver-inline">v' + esc(ver) + '</span>' : '') +
          '</div>' +
          '<div class="res-desc">' + esc(desc) + '</div>' +
          (authorLinksHtml(item.author_links) ? '<div class="res-desc">' + authorLinksHtml(item.author_links) + '</div>' : '') +
        '</div>' +
      '</div>' +
      '<div class="res-card-ops">' +
        '<button class="res-menu-btn">⋯</button>' +
        '<label class="res-switch">' +
          '<input type="checkbox" ' + (enabled ? 'checked' : '') + '><span class="slider"></span>' +
        '</label>' +
      '</div>';
    card.querySelector('.res-switch input').onchange = async (e) => {
      e.stopPropagation();
      if (!api) { toast('浏览器预览模式', 'warn'); return; }
      const fn = resKind === 'addon' ? api.set_addon_enabled : api.set_mod_enabled;
      try {
        const r = await fn(item.dir || item.name, e.target.checked);
        if (r && r.error) { toast('操作失败: ' + r.error, 'error'); e.target.checked = !e.target.checked; return; }
        item.enabled = e.target.checked;
        // 同步内存 settings.enable, 保证详细界面(设置开关)一致
        if (item.settings) item.settings.enable = e.target.checked;
        renderResList();
      } catch (err) { toast('操作失败: ' + err, 'error'); e.target.checked = !e.target.checked; }
    };
    card.querySelector('.res-menu-btn').onclick = () => openResModal(resKind, item);
    addCardTilt(card);
    return card;
  }

  // 设置项名称翻译 (目前仅 enable)
  const SETTING_LABELS = { enable: '启用' };

  // 设置字段渲染 (bool→开关, number→数字框, 其余→文本框); enable 标签译为"启用"
  function renderSettingsFields(settings) {
    const keys = settings ? Object.keys(settings) : [];
    if (!keys.length) return '<div class="res-empty">暂无配置项</div>';
    let html = '<div class="res-settings">';
    keys.forEach(k => {
      const v = settings[k];
      const label = SETTING_LABELS[k] || k;
      if (typeof v === 'boolean') {
        html += '<label class="res-set-row"><span class="res-set-name">' + esc(label) + '</span>' +
          '<span class="switch"><input type="checkbox" data-set="' + esc(k) + '"' + (v ? ' checked' : '') + '><span class="slider"></span></span></label>';
      } else if (typeof v === 'number') {
        html += '<label class="res-set-row"><span class="res-set-name">' + esc(label) + '</span>' +
          '<input type="number" step="any" data-set="' + esc(k) + '" value="' + esc(v) + '"></label>';
      } else {
        html += '<label class="res-set-row"><span class="res-set-name">' + esc(label) + '</span>' +
          '<input type="text" data-set="' + esc(k) + '" value="' + esc(v) + '"></label>';
      }
    });
    html += '</div>';
    return html;
  }

  function collectSettingsFields(panel) {
    const s = {};
    panel.querySelectorAll('[data-set]').forEach(el => {
      const k = el.dataset.set;
      if (el.type === 'checkbox') s[k] = el.checked;
      else if (el.type === 'number') s[k] = Number(el.value);
      else s[k] = el.value;
    });
    return s;
  }

  // 模态窗口 (插件/Mod 统一): 无标题栏, X 与名字同排; 设置表单自动保存; 操作按钮
  function openResModal(kind, item) {
    const existing = document.getElementById('res-modal');
    if (existing) { closePanel(existing); return; }
    document.body.classList.add('modal-open');
    const isAddon = kind === 'addon';
    const dir = item.dir || item.name;   // 文件夹名 (后端操作用)
    const name = item.name || '';
    const enabled = !!item.enabled;
    const author = item.author || '';
    const ver = item.version || '';
    const panel = document.createElement('div');
    panel.id = 'res-modal';
    panel.className = 'panel-overlay';
    panel.innerHTML =
      '<div class="panel-card">' +
        '<div class="res-detail-head">' +
          '<img class="res-detail-icon" src="' + (item.icon || PROJECT_ICON) + '" onerror="this.src=\'' + PROJECT_ICON + '\'">' +
          '<div class="res-detail-main">' +
            '<div class="res-detail-title-row">' +
              '<span class="res-detail-name">' + esc(name) + '</span>' +
              '<button class="panel-close" id="res-modal-close">✕</button>' +
            '</div>' +
            '<div class="res-detail-sub">' +
              (ver ? '<span class="res-ver-inline">v' + esc(ver) + '</span>' : '') +
              (authorLinksHtml(item.author_links) || '') +
            '</div>' +
            '<div class="res-detail-state ' + (enabled ? 'on' : 'off') + '">' + (enabled ? '● 已启用' : '○ 已禁用') + '</div>' +
          '</div>' +
        '</div>' +
        '<div class="res-detail-desc">' + esc(item.description || '（无描述）') + '</div>' +
        renderSettingsFields(item.settings) +
        '<div class="res-detail-ops">' +
           '<button class="btn btn-ghost" id="res-open-dir">打开目录</button>' +
           (item.reinstall_available ? '<button class="btn btn-primary" id="res-reinstall">↻ 重装</button>' : '') +
           '<button class="btn btn-danger" id="res-delete">删除</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(panel);
    panel.addEventListener('click', (e) => { if (e.target === panel) closePanel(panel); });
    $('#res-modal-close').onclick = () => closePanel(panel);

    $('#res-open-dir').onclick = async () => {
      const r = await api.open_mod_item_dir(kind, dir).catch(e => ({ error: String(e) }));
      if (r && r.error) toast(r.error, 'error');
    };
    if (item.reinstall_available) {
      $('#res-reinstall').onclick = () => confirmReinstall(kind, [dir], isAddon ? '插件' : 'Mod');
    }
    $('#res-delete').onclick = async () => {
      try {
        if (isAddon) {
          const r = await api.delete_addon(dir);
          if (r && r.error) { toast('删除失败: ' + r.error, 'error'); return; }
          toast('已删除 ' + name, 'success');
          closePanel(panel);
          refreshMods(true);
        } else {
          // Mod 删除在后台线程执行 (可能清理游戏目录副本), 立即反馈, 结果由钩子通知
          await api.delete_mod(dir).catch(() => {});
          toast('正在卸载 ' + name + '...', 'info', 2500);
          closePanel(panel);
        }
      } catch (err) { toast('卸载失败: ' + err, 'error'); }
    };
    // 自动保存: 任一设置变化 → 防抖写回, 并即时更新模态内状态标识
    let saveTimer = null;
    const saveNow = () => {
      const settings = collectSettingsFields(panel);
      const fn = isAddon ? api.set_addon_settings : api.set_mod_settings;
      fn(dir, settings).then(r => {
        if (r && r.error) { toast('保存失败: ' + r.error, 'error'); return; }
        // 更新模态内启用/禁用状态
        const st = panel.querySelector('.res-detail-state');
        if (st) {
          const en = settings.enable !== undefined ? !!settings.enable : enabled;
          st.className = 'res-detail-state ' + (en ? 'on' : 'off');
          st.textContent = en ? '● 已启用' : '○ 已禁用';
        }
        refreshMods(true);   // 保持当前页, 刷新列表状态标识
      }).catch(err => { toast('保存失败: ' + err, 'error'); });
    };
    panel.querySelectorAll('[data-set]').forEach(el => {
      const ev = el.type === 'text' || el.type === 'number' ? 'input' : 'change';
      el.addEventListener(ev, () => {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(saveNow, 500);
      });
    });
  }

  // ---------------- 下载中心 ----------------
  // 本次会话内已确认下载完成的项 (kind:name), 下载完成即时生效; 刷新列表仍会以后端检测为准
  const downloadedSeen = new Set();
  let _currentRec = null;   // 当前渲染的随机推荐 {kind, item}

  function applyDownloadedStyle(btn) {
    btn.className = 'btn btn-downloaded';
    btn.textContent = '✓ 已下载';
    btn.disabled = true;
    btn.onclick = null;
  }

  // 下载完成/检测到已安装时: 即时把对应按钮换成绿色"已下载"
  function markItemDownloaded(kind, name) {
    downloadedSeen.add(kind + ':' + name);
    // 更新下载中心卡片: 标题旁显示"已安装"
    document.querySelectorAll('#dc-list .res-card').forEach(card => {
      const title = card.querySelector('.res-title');
      if (title && title.textContent.trim().indexOf(name) === 0) {
        markCardInstalled(card);
      }
    });
    if (_currentRec && _currentRec.item && _currentRec.item.name === name &&
        (!kind || _currentRec.kind === kind)) {
      const dl = $('#rec-dl');
      if (dl) applyDownloadedStyle(dl);
    }
  }

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
        // 即时更新下载中心/推荐卡的按钮为"已下载" (无需重启)
        if (t.kind) markItemDownloaded(t.kind, name);
        // 资源管理刷新由后端"解压完成"钩子 (__onResChanged) 触发, 保证落盘后再刷
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
    maybeCloseDrawer();
  }

  function updateFabVisibility() {
    const fab = $('#dl-fab');
    const active = downloadTasks.filter(t => t.status === 'downloading' || t.status === 'waiting');
    if (active.length) {
      fab.querySelector('.dl-fab-ico').textContent = '📥';
      fab.classList.add('visible');
    } else {
      fab.querySelector('.dl-fab-ico').textContent = '';
      fab.classList.remove('visible');
    }
  }

  // 所有下载任务结束后自动关闭抽屉
  function maybeCloseDrawer() {
    const active = downloadTasks.some(t => t.status === 'downloading' || t.status === 'waiting');
    if (!active && $('#dl-drawer').classList.contains('open')) {
      setTimeout(() => toggleDrawer(false), 200);
    }
  }

  function toggleDrawer(open) {
    $('#dl-drawer').classList.toggle('open', open);
    $('#dl-overlay').classList.toggle('show', open);
  }

  function renderDownloadDrawer() {
    const list = $('#dl-list');
    if (!list) return;
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
    // 静默处理重复下载: 已有活跃的同名任务则忽略, 不重复添加 (避免进度条抽搐)
    if (downloadTasks.some(t => t.name === name && (t.status === 'downloading' || t.status === 'waiting'))) {
      return;
    }
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

  // ---------------- 下载中心 (资源管理式) ----------------
  let dcKind = 'addon';
  let dcPage = 1;
  let dcSearch = '';             // 下载中心搜索词
  let dcAddonItems = [];
  let dcModItems = [];

  function initDownloadCenter() {
    if (!api) return;
    $$('.res-tab[data-dc]').forEach(t => t.addEventListener('click', () => {
      $$('.res-tab[data-dc]').forEach(x => x.classList.remove('active'));
      t.classList.add('active');
      dcKind = t.dataset.dc;
      dcPage = 1;
      renderDCList();
    }));
    loadDCDisplay();
  }

  function loadDCDisplay() {
    const cardEl = $('#page-download_center .card');
    const list = $('#dc-list');
    if (list) list.innerHTML = '';
    showFrameLoading(cardEl);   // 圆圈加载动画, 不显示文字
    Promise.all([
      api.get_addon_list().catch(d => ({ pages: [], error: String(d) })),
      api.get_mod_list().catch(d => ({ pages: [], error: String(d) })),
    ]).then(([addonRes, modRes]) => {
      hideFrameLoading(cardEl);
      dcAddonItems = (addonRes.pages || []).flat().filter(Boolean);
      dcModItems = (modRes.pages || []).flat().filter(Boolean);
      dcPage = 1;
      renderDCList();
    }).catch(e => {
      hideFrameLoading(cardEl);
      if (list) list.innerHTML = '<div class="res-empty">⚠ ' + esc(String(e)) + '</div>';
    });
  }

  function renderDCList() {
    const list = $('#dc-list');
    if (!list) return;
    list.innerHTML = '';
    let items = dcKind === 'addon' ? dcAddonItems : dcModItems;
    if (dcSearch) {
      const kw = dcSearch.toLowerCase();
      items = items.filter(it =>
        (it.name || '').toLowerCase().includes(kw) ||
        (it.desc || '').toLowerCase().includes(kw));
    }
    const totalPages = Math.max(1, Math.ceil(items.length / RES_PAGE_SIZE));
    if (dcPage > totalPages) dcPage = totalPages;
    const pageItems = items.slice((dcPage - 1) * RES_PAGE_SIZE, dcPage * RES_PAGE_SIZE);
    if (!pageItems.length) {
      list.innerHTML = '';
    } else {
      pageItems.forEach((item, i) => { const c = buildDCCard(item, dcKind); if (c) { c.style.animationDelay = (i * 0.05) + 's'; list.appendChild(c); } });
      hydrateIcons(list);
    }
    renderDCPagination($('#dc-pagination'), items.length, totalPages);
  }

  function renderDCPagination(pagination, totalItems, totalPages) {
    if (!pagination) return;
    pagination.innerHTML = '';
    const prev = document.createElement('button');
    prev.textContent = '←';
    prev.disabled = dcPage <= 1;
    prev.onclick = () => { if (dcPage > 1) { dcPage--; renderDCList(); } };
    pagination.appendChild(prev);
    for (let i = 1; i <= totalPages; i++) {
      const b = document.createElement('button');
      b.textContent = i;
      if (i === dcPage) b.classList.add('active');
      b.onclick = () => { dcPage = i; renderDCList(); };
      pagination.appendChild(b);
    }
    const next = document.createElement('button');
    next.textContent = '→';
    next.disabled = dcPage >= totalPages;
    next.onclick = () => { if (dcPage < totalPages) { dcPage++; renderDCList(); } };
    pagination.appendChild(next);
  }

  // 卡片标记"已安装"
  function markCardInstalled(card) {
    const title = card.querySelector('.res-title');
    if (title && !title.querySelector('.res-state-badge.installed')) {
      title.insertAdjacentHTML('beforeend', '<span class="res-state-badge installed">已安装</span>');
    }
  }

  // 下载中心卡片: 资源管理卡片样式, 省略号 → 模态 (下载按钮在模态内), 已安装检测
  function buildDCCard(item, kind) {
    const disabled = item.disabled;
    const card = document.createElement('div');
    card.className = 'res-card' + (disabled ? ' disabled' : '');
    card.innerHTML =
      '<div class="res-card-main">' +
        '<img class="res-icon" src="' + PROJECT_ICON + '" alt="" ' +
          'data-icon-url="' + esc(item.icon_url || '') + '" data-icon-name="' + esc(item.name || '') + '" ' +
          'onerror="this.src=\'' + PROJECT_ICON + '\'">' +
        '<div class="res-info">' +
          '<div class="res-title-row">' +
            '<span class="res-title">' + esc(item.name || '未知') + (disabled ? ' (暂不可用)' : '') + '</span>' +
            (item.version ? '<span class="res-ver-inline">v' + esc(item.version) + '</span>' : '') +
          '</div>' +
          '<div class="res-desc">' + esc(item.desc || '无描述') + '</div>' +
          '<div class="res-desc">⬇ ' + (item.download_count || 0) + (authorLinksHtml(dcAuthorLinks(item.authors)) ? ' · ' + authorLinksHtml(dcAuthorLinks(item.authors)) : '') + '</div>' +
        '</div>' +
      '</div>' +
      '<button class="res-menu-btn" title="更多操作">⋯</button>';
    card.querySelector('.res-menu-btn').onclick = () => openDcModal(kind, item);
    addCardTilt(card);
    // 已安装检测: 实时钩子 (下载完成即时更新) + 每次渲染检测
    if (api && !disabled) {
      const key = kind + ':' + item.name;
      if (downloadedSeen.has(key)) {
        markCardInstalled(card);
      } else {
        withTimeout(api.check_item_downloaded(kind, item.name), 5000, { downloaded: false })
          .then(r => { if (r && r.downloaded) { markCardInstalled(card); downloadedSeen.add(key); } })
          .catch(() => {});
      }
    }
    return card;
  }

  function dcAuthorLinks(authors) {
    if (authors && typeof authors === 'object' && !Array.isArray(authors)) {
      return Object.entries(authors).map(([n, u]) => ({ name: n, url: u }));
    }
    return [];
  }

  // 下载中心模态: 详情 + 下载按钮
  function openDcModal(kind, item) {
    const existing = document.getElementById('dc-modal');
    if (existing) { closePanel(existing); return; }
    document.body.classList.add('modal-open');
    const disabled = item.disabled;
    const panel = document.createElement('div');
    panel.id = 'dc-modal';
    panel.className = 'panel-overlay';
    panel.innerHTML =
      '<div class="panel-card">' +
        '<div class="res-detail-head">' +
          '<img class="res-detail-icon" src="' + PROJECT_ICON + '" alt="" ' +
            'data-icon-url="' + esc(item.icon_url || '') + '" data-icon-name="' + esc(item.name || '') + '" ' +
            'onerror="this.src=\'' + PROJECT_ICON + '\'">' +
          '<div class="res-detail-main">' +
            '<div class="res-detail-title-row">' +
              '<span class="res-detail-name">' + esc(item.name || '未知') + '</span>' +
              '<button class="panel-close" id="dc-modal-close">✕</button>' +
            '</div>' +
            '<div class="res-detail-sub">' +
              (item.version ? '<span class="res-ver-inline">v' + esc(item.version) + '</span>' : '') +
              (authorLinksHtml(dcAuthorLinks(item.authors)) || '') +
            '</div>' +
            '<div class="res-detail-state off">⬇ ' + (item.download_count || 0) + ' 次下载</div>' +
          '</div>' +
        '</div>' +
        '<div class="res-detail-desc">' + esc(item.desc || '无描述') + '</div>' +
        '<div class="res-detail-ops">' +
          '<button class="btn btn-primary" id="dc-modal-dl" ' + (disabled ? 'disabled' : '') + '>📥 下载</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(panel);
    hydrateIcons(panel);
    panel.addEventListener('click', (e) => { if (e.target === panel) closePanel(panel); });
    $('#dc-modal-close').onclick = () => closePanel(panel);
    if (!disabled) {
      const dlBtn = $('#dc-modal-dl');
      dlBtn.onclick = () => {
        startDownloadItem(kind, item);
        closePanel(panel);
      };
      // 已安装检测: 已安装则禁止再次下载
      const key = kind + ':' + item.name;
      if (downloadedSeen.has(key)) {
        dlBtn.disabled = true;
        dlBtn.textContent = '✓ 已安装';
      } else {
        withTimeout(api.check_item_downloaded(kind, item.name), 5000, { downloaded: false })
          .then(r => {
            if (r && r.downloaded) {
              dlBtn.disabled = true;
              dlBtn.textContent = '✓ 已安装';
            }
          }).catch(() => {});
      }
    }
  }

  // ---------------- 工具面板 ----------------
  // 统一的面板打开/关闭: 关闭时播放淡出动画后再移除 DOM; 点击遮罩空白处也可关闭
  function closePanel(panel) {
    if (!panel || panel._closing) return;
    panel._closing = true;
    document.body.classList.remove('modal-open');
    panel.classList.add('closing');
    setTimeout(() => panel.remove(), 190);
  }

  function openAutoTranslate() {
    if (!api) { toast('浏览器预览模式', 'warn'); return; }
    const existing = document.getElementById('at-panel');
    if (existing) { closePanel(existing); return; }
    const panel = document.createElement('div');
    panel.id = 'at-panel';
    panel.className = 'panel-overlay';
    panel.innerHTML =
      '<div class="panel-card panel-card-wide">' +
        '<div class="panel-head"><h3>🤖 自动汉化</h3><button class="panel-close" id="at-close">✕</button></div>' +
        '<div class="panel-body">' +
          '<div class="at-row"><label>源文本目录</label><input type="text" id="at-source" placeholder="留空使用默认"></div>' +
          '<div class="at-row"><label>输出目录</label><input type="text" id="at-target" placeholder="留空使用默认"></div>' +
          '<div class="at-row"><label>黑名单 (每行一个)</label><textarea id="at-blacklist" rows="4" placeholder="ProjectGSLessonName.json"></textarea></div>' +
          '<div class="progress-track"><div class="progress-fill" id="at-progress"></div></div>' +
          '<div id="at-log" class="at-log"></div>' +
        '</div>' +
        '<div class="panel-foot"><button class="btn btn-ghost" id="at-stop">⏹ 停止</button><button class="btn btn-primary" id="at-start">🚀 开始</button></div>' +
      '</div>';
    document.body.appendChild(panel);
    panel.addEventListener('click', (e) => { if (e.target === panel) closePanel(panel); });
    $('#at-close').onclick = () => closePanel(panel);
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
    if (existing) { closePanel(existing); return; }
    const panel = document.createElement('div');
    panel.id = 'font-panel';
    panel.className = 'panel-overlay';
    panel.innerHTML =
      '<div class="panel-card panel-card-wide">' +
        '<div class="panel-head"><h3>📝 字体修改</h3><button class="panel-close" id="font-close">✕</button></div>' +
        '<div class="panel-body">' +
          '<div class="font-tabs"><button class="font-tab active" data-font="context">Context 字体</button><button class="font-tab" data-font="title">Title 字体</button></div>' +
          '<div id="font-info" class="font-info"></div>' +
          '<div id="font-preview" class="font-preview">' +
            '<div class="fp-title">边狱巴士 Limbus Company</div>' +
            '<div class="fp-text">但丁，今天的任务也请多指教。All results are meaningless.</div>' +
            '<div class="fp-num">0123456789 · HP 45 / SAN 25 · #01</div>' +
          '</div>' +
        '</div>' +
        '<div class="panel-foot"><input type="file" id="font-file" accept=".ttf,.otf" hidden><button class="btn btn-ghost" id="font-delete">删除自定义字体</button><button class="btn btn-primary" id="font-select">选择字体文件</button></div>' +
      '</div>';
    document.body.appendChild(panel);
    panel.addEventListener('click', (e) => { if (e.target === panel) closePanel(panel); });
    $('#font-close').onclick = () => closePanel(panel);
    let currentFontTab = 'context';
    // 真实加载自定义字体文件, 让预览文本用该字体渲染
    async function loadFontPreview() {
      const pv = $('#font-preview');
      if (!pv) return;
      try {
        const r = await withTimeout(api.get_font_data(currentFontTab), 8000, { uri: '' });
        const famName = 'FP_' + currentFontTab;
        if (r && r.uri) {
          const face = new FontFace(famName, 'url(' + r.uri + ')');
          await face.load();
          document.fonts.add(face);
          pv.style.fontFamily = "'" + famName + "', var(--font)";
        } else {
          pv.style.fontFamily = 'var(--font)';   // 无自定义字体 → 默认
        }
      } catch (e) {
        pv.style.fontFamily = 'var(--font)';
      }
    }
    function refreshFontInfo() {
      const card = panel.querySelector('.panel-card');
      showFrameLoading(card);
      Promise.all([
        api.get_font_info(),
        loadFontPreview(),
      ]).then(([d]) => {
        const info = d[currentFontTab] || {};
        $('#font-info').innerHTML = info.exists
          ? '✓ 已使用自定义字体 (' + (info.size / 1024).toFixed(1) + ' KB)'
          : '使用默认字体';
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
    if (existing) { closePanel(existing); return; }
    const panel = document.createElement('div');
    panel.id = 'gradient-panel';
    panel.className = 'panel-overlay';
    panel.innerHTML =
      '<div class="panel-card panel-card-wide">' +
        '<div class="panel-head"><h3>💻 渐变文本处理器</h3><button class="panel-close" id="gradient-close">✕</button></div>' +
        '<div class="panel-body">' +
          '<div class="grad-section">' +
            '<div class="grad-title">🎨 颜色设置</div>' +
            '<div class="grad-color-row">' +
              '<span class="gc-label">起始颜色</span><input type="color" id="gradient-start" value="#00e5ff">' +
              '<span class="gc-sep"></span>' +
              '<span class="gc-label">结束颜色</span><input type="color" id="gradient-end" value="#ffffff">' +
            '</div>' +
          '</div>' +
          '<div class="grad-section">' +
            '<div class="grad-title">⚙️ 渐变设置</div>' +
            '<div class="grad-rate-row">' +
              '<span class="gc-label">渐变度 <i>(值越大渐变越快)</i></span>' +
              '<input type="range" id="gradient-rate" min="0.1" max="5" step="0.1" value="2">' +
              '<span class="range-val" id="gradient-rate-val">2.0</span>' +
            '</div>' +
          '</div>' +
          '<div class="grad-section">' +
            '<div class="grad-title">✏️ 输入文本</div>' +
            '<textarea id="gradient-input" rows="2" class="at-row-input">你也将安息, 化作哀蝶消散吧...</textarea>' +
          '</div>' +
          '<div class="grad-section">' +
            '<div class="grad-title">🎯 实时预览</div>' +
            '<div id="gradient-preview" class="gradient-preview"><span style="opacity:.4">输入文本后实时预览</span></div>' +
          '</div>' +
          '<div class="grad-section">' +
            '<div class="grad-title">📋 生成的 Unity 富文本</div>' +
            '<textarea id="gradient-output" rows="3" readonly class="grad-output"></textarea>' +
          '</div>' +
        '</div>' +
        '<div class="panel-foot"><button class="btn btn-primary" id="gradient-copy">📋 复制 Unity 富文本</button></div>' +
      '</div>';
    document.body.appendChild(panel);
    panel.addEventListener('click', (e) => { if (e.target === panel) closePanel(panel); });
    $('#gradient-close').onclick = () => closePanel(panel);

    const out = $('#gradient-output'), prev = $('#gradient-preview');
    const rateVal = $('#gradient-rate-val');
    let gradTimer = null;
    function regenGrad() {
      rateVal.textContent = Number($('#gradient-rate').value).toFixed(1);
      clearTimeout(gradTimer);
      gradTimer = setTimeout(async () => {
        const text = $('#gradient-input').value;
        if (!text.trim()) {
          out.value = '';
          prev.innerHTML = '<span style="opacity:.4">输入文本后实时预览</span>';
          return;
        }
        try {
          const r = await api.generate_gradient_text(
            text, $('#gradient-start').value, $('#gradient-end').value,
            parseFloat($('#gradient-rate').value));
          if (!r || r.error) return;
          out.value = r.result;
          prev.innerHTML = r.result
            .replace(/<color=#([0-9a-fA-F]{3,6})>/g, '<span style="color:#$1">')
            .replace(/<\/color>/g, '</span>');
        } catch (e) { /* 实时生成失败静默, 下次输入会重试 */ }
      }, 250);
    }
    ['#gradient-input', '#gradient-start', '#gradient-end'].forEach(sel => {
      $(sel).addEventListener('input', regenGrad);
    });
    $('#gradient-rate').addEventListener('input', regenGrad);
    regenGrad();

    $('#gradient-copy').onclick = () => {
      const v = out.value;
      if (!v) { toast('还没有可复制的结果', 'warn'); return; }
      navigator.clipboard.writeText(v).then(() => toast('已复制', 'success')).catch(() => toast('复制失败', 'error'));
    };
  }

  function openExtensionTools() {
    if (!api) { toast('浏览器预览模式', 'warn'); return; }
    const existing = document.getElementById('ext-panel');
    if (existing) { closePanel(existing); return; }
    const panel = document.createElement('div');
    panel.id = 'ext-panel';
    panel.className = 'panel-overlay';
    panel.innerHTML =
      '<div class="panel-card">' +
        '<div class="panel-head"><h3>🧩 扩展工具</h3><button class="panel-close" id="ext-close">✕</button></div>' +
        '<div class="panel-body ext-center">' +
          '<div class="at-row"><label style="text-align:center"></label>' +
            '<input type="text" id="ext-key" placeholder="请输入密钥" autocomplete="off" spellcheck="false" style="text-align:center">' +
          '</div>' +
          '<button class="btn btn-primary" id="ext-verify" style="width:100%;justify-content:center;margin-top:6px">验证</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(panel);
    panel.addEventListener('click', (e) => { if (e.target === panel) closePanel(panel); });
    $('#ext-close').onclick = () => closePanel(panel);
    $('#ext-key').onkeydown = (e) => { if (e.key === 'Enter') $('#ext-verify').click(); };
    setTimeout(() => $('#ext-key').focus(), 120);
    $('#ext-verify').onclick = async () => {
      const key = $('#ext-key').value.trim();
      if (!key) { toast('请输入密钥', 'warn'); return; }
      const r = await api.verify_extension_key(key);
      if (r.ok) {
        closePanel(panel);
        api.open_extension_tools_window().then(ok => {
          toast(ok ? '扩展工具已打开' : '打开失败', ok ? 'success' : 'error');
        });
      } else { toast(r.error || '密钥错误', 'error'); }
    };
  }

  // ---------------- 渲染 ----------------
  function render() {
    const b = BOOT;
    // 版本 (关于页版本号由 get_contributors 提供, 主页版本卡在这里更新)
    const sv = $('#stat-version');
    if (sv) sv.textContent = b.version;
    // 背景色
    applyTheme(b.bg_color);
    applyGlassFactor();
    applyHwAccel();
    applyFrameLimit();
    // 项目图标 (后端 data URI, 供下载中心/推荐卡图标回退)
    if (b.icon_uri) {
      PROJECT_ICON = b.icon_uri;
      const heroImg = document.querySelector('.hero-aside .hero-bg-icon');
      if (heroImg) heroImg.src = b.icon_uri;
      const brandImg = document.querySelector('.brand-icon');
      if (brandImg) brandImg.src = b.icon_uri;
      const tbIcon = document.querySelector('#titlebar .tb-icon');
      if (tbIcon) tbIcon.src = b.icon_uri;
    }
    // 状态芯片 (游戏路径实时从后端读取, 自动填充/设置修改都会同步)
    updatePathChip();
    // 快捷方式 & 工具
    updateSourceChip();
    renderFeatures(b.features);
    renderTools(b.tools);
    // 设置
    renderSettings(b.settings_schema);
    // 欢迎音效提示
    if (IS_BROWSER) toast('浏览器预览模式, 部分功能不可用', 'warn', 4000);
  }

  // ---------------- 主页: 更新内容 / 随机推荐 ----------------

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
    _currentRec = rec;
    const dl = $('#rec-dl');
    if (dl) {
      dl.onclick = (e) => {
        e.stopPropagation();
        if (!api) { toast('浏览器预览模式', 'warn'); return; }
        startDownloadItem(rec.kind, it);
      };
      // 已下载检测 (每次渲染都重新检测)
      if (api) {
        const key = rec.kind + ':' + it.name;
        if (downloadedSeen.has(key)) {
          applyDownloadedStyle(dl);
        } else {
          withTimeout(api.check_item_downloaded(rec.kind, it.name), 5000, { downloaded: false })
            .then(r => { if (r && r.downloaded) applyDownloadedStyle(dl); }).catch(() => {});
        }
      }
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

  function applyGlassFactor() {
    let v = 1;
    try {
      const s = BOOT && BOOT.settings_schema ? BOOT.settings_schema.glass_factor : null;
      if (s) v = Number(s.value !== undefined ? s.value : s.default) || 1;
    } catch (e) { v = 1; }
    document.documentElement.style.setProperty('--glass-factor', String(v));
  }

  // 启用毛玻璃开关: 关闭时给 body 加 no-hw, 禁用 backdrop-filter 等毛玻璃高消耗效果
  function applyHwAccel() {
    let v = true;
    try {
      const s = BOOT && BOOT.settings_schema ? BOOT.settings_schema.glass_enabled : null;
      if (s) v = Boolean(s.value !== undefined ? s.value : s.default);
    } catch (e) { v = true; }
    document.body.classList.toggle('no-hw', !v);
  }

  // 帧渲染上限: 限制 JS 动画 rAF 帧率, 减少毛玻璃卡片等每帧重绘的 GPU 开销
  let frameLimit = 60;
  let __lastRafT = 0;
  function applyFrameLimit() {
    let idx = 2;
    try {
      const s = BOOT && BOOT.settings_schema ? BOOT.settings_schema.frame_limit : null;
      if (s) idx = Number(s.value !== undefined ? s.value : s.default) || 2;
    } catch (e) { idx = 2; }
    const fpsList = [30, 45, 60, 90, 120];
    frameLimit = fpsList[idx] || 60;
  }
  function rafThrottle(cb) {
    if (frameLimit >= 120) return requestAnimationFrame(cb);
    const interval = 1000 / frameLimit;
    const loop = (t) => {
      if (t - __lastRafT >= interval) { __lastRafT = t; cb(t); }
      else requestAnimationFrame(loop);
    };
    return requestAnimationFrame(loop);
  }

  // 轮播交互保持原生刷新频率，不受设置中的全局帧率上限影响。
  const carouselRAF = (cb) => requestAnimationFrame(cb);

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
  let featStep = 340;   // 卡片间距, 随主区宽度自适应

  // 计算卡片尺寸: 中间卡完整 + 两侧卡自然露出 (卡宽 ≈ 主区宽/2.2, 间距 = 卡宽, 不重叠),
  // 受高度上限约束 (等比例拉伸)
  function computeFeatSize() {
    const main = document.getElementById('main');
    const W = Math.max(320, (main ? main.clientWidth : 720) - 60);
    const H = Math.max(360, window.innerHeight - 150);  // 留出 #main padding + 指示点
    let c = W / 2.2;
    const cMaxH = H * 3 / 4 * 0.92;                      // 高度约束: 卡高不超高
    if (c > cMaxH) c = cMaxH;
    c = Math.max(220, Math.min(c, 520));
    // 间距比卡宽大 12%, 卡片之间留出空隙, 不贴太近
    return { w: Math.round(c), h: Math.round(c * 4 / 3), step: Math.round(c * 1.12) };
  }

  function applyFeatSize() {
    const stage = $('#features-stage');
    if (!stage) return;
    const s = computeFeatSize();
    // 快捷方式与工具页共用同一卡片尺寸
    ['#features-stage', '#tools-stage'].forEach(sel => {
      const st = $(sel);
      if (st) {
        st.style.width = s.w + 'px';
        st.style.height = s.h + 'px';
        st.style.fontSize = (s.w / 7.5).toFixed(1) + 'px';  // 内容字号随卡片等比例缩放
      }
    });
    featStep = s.step;
    layoutCarousel(false);
    layoutToolsCarousel(false);
  }

  function isBoxLayout() {
    const s = BOOT && BOOT.settings_schema ? BOOT.settings_schema.page_layout : null;
    if (!s) return false;
    const v = s.value !== undefined ? s.value : s.default;
    return Number(v) === 1;   // 1 = 箱式布局
  }

  function renderFeatures(features) {
    const stage = $('#features-stage');
    if (!stage) return;
    const box = isBoxLayout();
    const carouselEl = $('#features-carousel');
    const gridEl = $('#features-grid');
    const dotsEl = $('#features-dots');
    if (carouselEl) carouselEl.hidden = box;
    if (dotsEl) dotsEl.hidden = box;
    const list = (features || []).filter(Boolean);
    featTotal = list.length;
    featAngle = 0;
    if (box) {
      // 箱式布局: 网格平铺, 点击打开
      if (gridEl) {
        gridEl.hidden = false;
        gridEl.innerHTML = '';
        list.forEach((f) => {
          const card = document.createElement('button');
          card.className = 'box-card';
          const bg = f.image_uri || (f.image ? '../../assets/images/features/' + f.image : '');
          card.innerHTML =
            '<div class="box-card-bg">' + (bg ? '<img src="' + esc(bg) + '" alt="" draggable="false">' : '') + '</div>' +
            '<div class="box-card-body">' +
              '<div class="box-card-name">' + esc(f.name) + '</div>' +
              '<div class="box-card-desc">' + esc(f.desc || '') + '</div>' +
            '</div>';
          card.onclick = () => {
            if (api) api.open_feature(f.name).catch(e => toast(String(e), 'error'));
            else toast('浏览器预览模式', 'warn');
          };
          gridEl.appendChild(card);
        });
      }
      return;
    }
    stage.innerHTML = '';
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
      inner.dataset.featureName = f.name;   // 单击打开 (在轮播拖拽判定中触发)
      wrap.appendChild(inner);
      stage.appendChild(wrap);
    });
    // 底部指示点: 点击跳转到对应卡片
    const dotsWrap = document.getElementById('features-dots');
    if (dotsWrap) {
      dotsWrap.innerHTML = '';
      list.forEach((_, i) => {
        const dot = document.createElement('button');
        dot.className = 'cdot';
        dot.title = '跳到第 ' + (i + 1) + ' 个快捷方式';
        dot.addEventListener('click', () => {
          if (typeof window.__featGoTo === 'function') window.__featGoTo(i);
          else { featAngle = i; layoutCarousel(true); }
        });
        dotsWrap.appendChild(dot);
      });
    }
    applyFeatSize();
  }

  // CoverFlow 式循环轮播: 卡片沿弧线排列, 中间正面最大, 两侧倾斜有立体感但保持 1:1 不缩小,
  // 无限循环; 支持 float offset 实现丝滑拖拽 (不再 Math.round 跳变)
function layoutCarousel(smooth) {
    const stage = $('#features-stage');
    if (!stage || !featTotal) return;
    const n = featTotal || 1;
    // 用浮点 offset, 拖拽时连续变化不跳变
    const offset = featAngle;
    const X = [0, featStep, featStep * 2]; // d=0,1,2 横向位置 (间距 = 卡宽, 三卡无缝填满)
    const S = [1, 1, 1];         // 缩放: 全部 1:1, 不缩小 (仅保留倾斜的立体感)
    const DEPTH = 80, ANGLE = 16; // 深度/角度: 保留 CoverFlow 立体层次与倾斜
    const OPACITY = [1, 0.9, 0.65]; // 远离中心的卡轻微渐隐, 层次过渡更柔和
    const cards = stage.querySelectorAll('.carousel-item');
    if (!cards.length) return;
    cards.forEach((card, i) => {
      let d = ((i - offset) % n + n) % n;
      if (d > n / 2) d = d - n;
      const prev = card._d;
      const jumped = prev !== undefined && Math.abs(d - prev) > n / 2;
      card._d = d;
      const ad = Math.abs(d);
      const idx = Math.min(Math.floor(ad), 2);   // 必须取整, 否则浮点索引取到 undefined
      const frac = ad - idx;
      const xBase = X[idx] ?? 0;
      const xNext = (X[idx + 1] ?? (xBase + featStep));
      const x = (d < 0 ? -1 : 1) * (xBase + (xNext - xBase) * frac);
      const scale = S[idx] ?? 1;
      const z = -ad * DEPTH;
      const rot = d * ANGLE;
      const opacity = OPACITY[idx] ?? 0.65;
      card.style.opacity = String(opacity);
      card.style.transition = (smooth && !jumped)
        ? 'transform .45s cubic-bezier(.22,.75,.28,1), opacity .45s ease'
        : 'none';
      card.style.transform = 'translate3d(' + (x || 0).toFixed(2) + 'px, 0, ' + (z || 0).toFixed(2) + 'px) rotateY(' + (rot || 0).toFixed(2) + 'deg) scale(' + scale.toFixed(4) + ')';
    });
    // 同步底部指示点: 当前居中的卡高亮
    const activeDot = ((Math.round(offset) % n) + n) % n;
    const dots = document.querySelectorAll('#features-dots .cdot');
    dots.forEach((d, i) => d.classList.toggle('active', i === activeDot));
  }

  function bindFeaturesCarousel() {
    const carousel = $('#features-carousel');
    if (!carousel) return;
    let featTarget = 0, animRAF = null;

    // 平滑滚动: 每次滚轮设目标=当前对齐位±1, rAF 缓动接近 (无惯性飞远/无卡顿)
    const animLoop = () => {
      const diff = featTarget - featAngle;
      featAngle += diff * 0.15;
      layoutCarousel(false);
      if (Math.abs(diff) < 0.01) {
        featAngle = featTarget;
        layoutCarousel(true);
        animRAF = null;
      } else {
        animRAF = carouselRAF(animLoop);
      }
    };
    const stopWheelAnim = () => {
      if (animRAF) { cancelAnimationFrame(animRAF); animRAF = null; }
    };

    // 指示点跳转: 停止滚轮动画后再设角度, 避免 animLoop 覆盖造成卡位
    window.__featGoTo = (i) => {
      stopAll();
      stopWheelAnim();
      featAngle = i;
      layoutCarousel(true);
    };

    carousel.addEventListener('wheel', (e) => {
      e.preventDefault();
      if (dragging) return;
      stopAll();
      featTarget = Math.round(featAngle) + (e.deltaY < 0 ? 1 : -1);
      if (!animRAF) animRAF = carouselRAF(animLoop);
    }, { passive: false });

    // ---- 丝滑拖拽: rAF 渲染 + spring 弹性吸附 ----
    let dragging = false, startX = 0, dragBase = 0;
    let moved = false, pressEl = null, pressName = null;
    let rafId = null, springId = null;

    const stopAll = () => {
      if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
      if (springId) { cancelAnimationFrame(springId); springId = null; }
    };

    const clearPress = () => {
      if (pressEl) { pressEl.classList.remove('card-press'); pressEl = null; }
      pressName = null;
    };

    // 跟手阶段: rAF 持续渲染, featAngle 浮点跟随
    const startRenderLoop = () => {
      stopAll();
      const loop = () => {
        layoutCarousel(false);
        rafId = carouselRAF(loop);
      };
      rafId = carouselRAF(loop);
    };

    // 松手后: spring 弹性吸附到最近整数 (不抽动)
    const springToNearest = () => {
      stopAll();
      const target = Math.round(featAngle);
      const startVal = featAngle;
      const t0 = performance.now();
      const duration = 320; // ms
      const step = (now) => {
        const p = Math.min(1, (now - t0) / duration);
        // ease-out cubic: 平滑减速
        const ease = 1 - Math.pow(1 - p, 3);
        featAngle = startVal + (target - startVal) * ease;
        layoutCarousel(p < 0.98); // 接近结束时加回过渡
        if (p < 1) { springId = carouselRAF(step); }
        else { featAngle = target; layoutCarousel(true); }
      };
      springId = carouselRAF(step);
    };

    carousel.addEventListener('pointerdown', (e) => {
      dragging = true;
      moved = false;
      startX = e.clientX;
      dragBase = featAngle;
      stopWheelAnim();
      stopAll();
      startRenderLoop();
      // 按下反馈: 卡片缩小 + 高亮
      const hit = e.target.closest('.carousel-item-inner');
      if (hit) {
        pressEl = hit;
        pressName = hit.dataset.featureName || null;
        hit.classList.add('card-press');
      }
    });

    window.addEventListener('pointermove', (e) => {
      if (!dragging) return;
      const dx = e.clientX - startX;
      if (Math.abs(dx) > 6 && !moved) {
        moved = true;
        clearPress();   // 开始拖动, 取消按压缩放反馈
      }
      // 灵敏度: 拖 200px = 切 1 张; 方向取反 (向右拖 = 上一张, 向左拖 = 下一张)
      featAngle = dragBase - dx / 220;
    });
    window.addEventListener('pointerup', () => {
      if (!dragging) return;
      dragging = false;
      stopAll();
      // 未发生拖拽位移 -> 判定为单击, 打开对应快捷方式
      const clickName = pressName;   // 先保存, clearPress 会清空它
      if (!moved && clickName) {
        clearPress();
        if (api) api.open_feature(clickName).catch(e => toast(String(e), 'error'));
        else toast('浏览器预览模式', 'warn');
      } else {
        clearPress();
      }
      springToNearest();
    });
    window.addEventListener('pointercancel', () => {
      if (!dragging) return;
      dragging = false;
      clearPress();
      stopAll();
      springToNearest();
    });
  }

  const TOOL_PENDING = [];

  // 工具点击分发 (供轮播单击判定调用)
  function openToolAction(t) {
    const pending = TOOL_PENDING.includes(t.id);
    if (pending) { toast('该工具将在后续版本接入 Web UI', 'warn'); return; }
    if (t.page) { switchPage(t.page); return; }
    if (t.id === 'auto_translate') { openAutoTranslate(); return; }
    if (t.id === 'font') { openFontSelector(); return; }
    if (t.id === 'gradient') { openGradientTool(); return; }
    if (t.id === 'extension_tools') { openExtensionTools(); return; }
    if (api) api.open_tool(t.id).catch(e => toast(String(e), 'error'));
    else toast('浏览器预览模式', 'warn');
  }

  // 工具页: 与快捷方式完全一致的 3D 轮播展示
  let toolsTotal = 0, toolsAngle = 0;
  let toolsData = [];

  function renderTools(tools) {
    const stage = $('#tools-stage');
    if (!stage) return;
    const box = isBoxLayout();
    const carouselEl = $('#tools-carousel');
    const gridEl = $('#tools-grid');
    const dotsEl = $('#tools-dots');
    if (carouselEl) carouselEl.hidden = box;
    if (dotsEl) dotsEl.hidden = box;
    const list = (tools || []).filter(Boolean);
    toolsTotal = list.length;
    toolsAngle = 0;
    toolsData = list;
    if (box) {
      // 箱式布局: 网格平铺, 点击打开工具
      if (gridEl) {
        gridEl.hidden = false;
        gridEl.innerHTML = '';
        list.forEach((t) => {
          const card = document.createElement('button');
          card.className = 'box-card';
          const bg = t.image_uri || (t.image ? '../../assets/images/tools/' + t.image : '');
          card.innerHTML =
            '<div class="box-card-bg">' + (bg ? '<img src="' + esc(bg) + '" alt="" draggable="false">' : '') + '</div>' +
            '<div class="box-card-body">' +
              '<div class="box-card-name">' + esc(t.name) + '</div>' +
              '<div class="box-card-desc">' + esc(t.desc || '') + '</div>' +
            '</div>';
          card.onclick = () => openToolAction(t);
          gridEl.appendChild(card);
        });
      }
      return;
    }
    stage.innerHTML = '';
    if (!toolsTotal) return;
    list.forEach((t, i) => {
      const wrap = document.createElement('div');
      wrap.className = 'carousel-item';
      const inner = document.createElement('div');
      inner.className = 'carousel-item-inner';
      // 图片处理逻辑与快捷方式一致: 无图片则留空
      const bg = t.image_uri || (t.image ? '../../assets/images/tools/' + t.image : '');
      const bgHtml = bg ? '<img class="carousel-item-bg" src="' + esc(bg) + '" alt="" draggable="false">' : '';
      inner.innerHTML = bgHtml +
        '<div class="carousel-item-content">' +
          '<div class="lc-ico">' + esc(t.name.split(' ')[0]) + '</div>' +
          '<div class="lc-name">' + esc(t.name.split(' ').slice(1).join(' ') || t.name) + '</div>' +
          '<div class="lc-desc">' + esc(t.desc || '') + '</div>' +
        '</div>';
      inner.dataset.toolId = t.id;   // 单击打开 (在轮播拖拽判定中触发)
      wrap.appendChild(inner);
      stage.appendChild(wrap);
    });
    // 底部指示点: 点击跳转到对应卡片
    const dotsWrap = document.getElementById('tools-dots');
    if (dotsWrap) {
      dotsWrap.innerHTML = '';
      list.forEach((_, i) => {
        const dot = document.createElement('button');
        dot.className = 'cdot';
        dot.title = '跳到第 ' + (i + 1) + ' 个工具';
        dot.addEventListener('click', () => {
          if (typeof window.__toolsGoTo === 'function') window.__toolsGoTo(i);
          else { toolsAngle = i; layoutToolsCarousel(true); }
        });
        dotsWrap.appendChild(dot);
      });
    }
    applyFeatSize();
  }

// 工具轮播布局: 与快捷方式完全一致 (间距/倾斜/渐隐)
function layoutToolsCarousel(smooth) {
    const stage = $('#tools-stage');
    if (!stage || !toolsTotal) return;
    const n = toolsTotal || 1;
    const offset = toolsAngle;
    const X = [0, featStep, featStep * 2];
    const S = [1, 1, 1];
    const DEPTH = 80, ANGLE = 16;
    const OPACITY = [1, 0.9, 0.65];
    const cards = stage.querySelectorAll('.carousel-item');
    if (!cards.length) return;
    cards.forEach((card, i) => {
      let d = ((i - offset) % n + n) % n;
      if (d > n / 2) d = d - n;
      const prev = card._d;
      const jumped = prev !== undefined && Math.abs(d - prev) > n / 2;
      card._d = d;
      const ad = Math.abs(d);
      const idx = Math.min(Math.floor(ad), 2);
      const frac = ad - idx;
      const xBase = X[idx] ?? 0;
      const xNext = (X[idx + 1] ?? (xBase + featStep));
      const x = (d < 0 ? -1 : 1) * (xBase + (xNext - xBase) * frac);
      const scale = S[idx] ?? 1;
      const z = -ad * DEPTH;
      const rot = d * ANGLE;
      const opacity = OPACITY[idx] ?? 0.65;
      card.style.opacity = String(opacity);
      card.style.transition = (smooth && !jumped)
        ? 'transform .45s cubic-bezier(.22,.75,.28,1), opacity .45s ease'
        : 'none';
      card.style.transform = 'translate3d(' + (x || 0).toFixed(2) + 'px, 0, ' + (z || 0).toFixed(2) + 'px) rotateY(' + (rot || 0).toFixed(2) + 'deg) scale(' + scale.toFixed(4) + ')';
    });
    const activeDot = ((Math.round(offset) % n) + n) % n;
    const dots = document.querySelectorAll('#tools-dots .cdot');
    dots.forEach((d, i) => d.classList.toggle('active', i === activeDot));
  }

  function bindToolsCarousel() {
    const carousel = $('#tools-carousel');
    if (!carousel) return;
    let toolsTarget = 0, animRAF = null;

    // 平滑滚动: 每次滚轮设目标=当前对齐位±1, rAF 缓动接近 (无惯性飞远/无卡顿)
    const animLoop = () => {
      const diff = toolsTarget - toolsAngle;
      toolsAngle += diff * 0.15;
      layoutToolsCarousel(false);
      if (Math.abs(diff) < 0.01) {
        toolsAngle = toolsTarget;
        layoutToolsCarousel(true);
        animRAF = null;
      } else {
        animRAF = carouselRAF(animLoop);
      }
    };
    const stopWheelAnim = () => {
      if (animRAF) { cancelAnimationFrame(animRAF); animRAF = null; }
    };

    // 指示点跳转: 停止滚轮动画后再设角度, 避免 animLoop 覆盖造成卡位
    window.__toolsGoTo = (i) => {
      stopAll();
      stopWheelAnim();
      toolsAngle = i;
      layoutToolsCarousel(true);
    };

    carousel.addEventListener('wheel', (e) => {
      e.preventDefault();
      if (dragging) return;
      stopAll();
      toolsTarget = Math.round(toolsAngle) + (e.deltaY < 0 ? 1 : -1);
      if (!animRAF) animRAF = carouselRAF(animLoop);
    }, { passive: false });

    let dragging = false, startX = 0, dragBase = 0;
    let moved = false, pressEl = null, pressId = null;
    let rafId = null, springId = null;

    const stopAll = () => {
      if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
      if (springId) { cancelAnimationFrame(springId); springId = null; }
    };

    const clearPress = () => {
      if (pressEl) { pressEl.classList.remove('card-press'); pressEl = null; }
      pressId = null;
    };

    const startRenderLoop = () => {
      stopAll();
      const loop = () => {
        layoutToolsCarousel(false);
        rafId = carouselRAF(loop);
      };
      rafId = carouselRAF(loop);
    };

    const springToNearest = () => {
      stopAll();
      const target = Math.round(toolsAngle);
      const startVal = toolsAngle;
      const t0 = performance.now();
      const duration = 320;
      const step = (now) => {
        const p = Math.min(1, (now - t0) / duration);
        const ease = 1 - Math.pow(1 - p, 3);
        toolsAngle = startVal + (target - startVal) * ease;
        layoutToolsCarousel(p < 0.98);
        if (p < 1) { springId = carouselRAF(step); }
        else { toolsAngle = target; layoutToolsCarousel(true); }
      };
      springId = carouselRAF(step);
    };

    carousel.addEventListener('pointerdown', (e) => {
      dragging = true;
      moved = false;
      startX = e.clientX;
      dragBase = toolsAngle;
      stopWheelAnim();
      stopAll();
      startRenderLoop();
      const hit = e.target.closest('.carousel-item-inner');
      if (hit) {
        pressEl = hit;
        pressId = hit.dataset.toolId || null;
        hit.classList.add('card-press');
      }
    });

    window.addEventListener('pointermove', (e) => {
      if (!dragging) return;
      const dx = e.clientX - startX;
      if (Math.abs(dx) > 6 && !moved) {
        moved = true;
        clearPress();
      }
      toolsAngle = dragBase - dx / 220;
    });
    window.addEventListener('pointerup', () => {
      if (!dragging) return;
      dragging = false;
      stopAll();
      const clickId = pressId;   // 先保存, clearPress 会清空它
      if (!moved && clickId) {
        clearPress();
        const t = toolsData.find(x => x.id === clickId);
        if (t) openToolAction(t);
      } else {
        clearPress();
      }
      springToNearest();
    });
    window.addEventListener('pointercancel', () => {
      if (!dragging) return;
      dragging = false;
      clearPress();
      stopAll();
      springToNearest();
    });
  }

  // ---------------- 设置 ----------------
  function getSettingValue(key) {
    const s = BOOT.settings_schema[key];
    if (!s) return null;
    if (SETTING_CHANGES[key]) return SETTING_CHANGES[key].value;
    return s.value !== undefined ? s.value : s.default;
  }

  // 设置写入后同步前端缓存, 保证 charRange 等实时读取新值 (即时生效)
  function updateBootSetting(key, v) {
    if (BOOT && BOOT.settings_schema && BOOT.settings_schema[key]) {
      BOOT.settings_schema[key].value = v;
    }
  }

  function getSettingOptions(key) {
    const s = BOOT.settings_schema[key];
    return (s && s.options) || [];
  }

  // 主页汉化源芯片: 设置更改后立即调用同步
  function updateSourceChip() {
    const sc = $('#chip-source');
    if (!sc) return;
    const src = getSettingValue('translate_source');
    if (typeof src === 'number') {
      const opts = getSettingOptions('translate_source');
      sc.innerHTML = '<span class="dot"></span><span>汉化源: ' + esc(opts[src] || '未知') + '</span>';
    }
  }

  // 主页游戏路径芯片: 实时从后端读取 (首次自动填充/设置修改都会同步)
  function updatePathChip() {
    const gp = $('#chip-gamepath');
    if (!gp) return;
    const render = (p) => {
      if (p) {
        gp.className = 'chip ok';
        gp.innerHTML = '<span class="dot"></span><span>游戏路径: ' + esc(shortPath(p)) + '</span>';
      } else {
        gp.className = 'chip warn';
        gp.innerHTML = '<span class="dot"></span><span>游戏路径: 未配置</span>';
      }
    };
    if (api) {
      withTimeout(api.get_setting('game_path'), 4000, '').then(v => render(v)).catch(() => render(BOOT && BOOT.game_path));
    } else {
      render(BOOT && BOOT.game_path);
    }
  }

  function markChanged(key, value) {
    SETTING_CHANGES[key] = { value };
    const s = BOOT.settings_schema[key];
    if (s && s.key_el) s.key_el.dataset.changed = '1';
  }

  function renderSettings(schema) {
    const container = $('#settings-groups');
    if (!container) return;
    container.innerHTML = '';
    SETTING_CHANGES = {};
    const groups = {};
    Object.keys(schema).forEach(key => {
      const s = schema[key];
      const page = s.page || '系统';
      if (page != '系统'){
        if (!groups[page]) groups[page] = [];
        groups[page].push({ key, s });
      }
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
        try {
          const row = document.createElement('div');
          row.className = 'set-row';
          s.key_el = row;
          row.innerHTML = '<div class="set-info">' +
            '<div class="set-name">' + esc(s.name || key) + '</div>' +
            (s.description ? '<div class="set-desc">' + esc(s.description).replace(/\n/g, '<br>') + '</div>' : '') +
            '</div>';
        row.appendChild(buildControl(key, s));
        g.appendChild(row);
        } catch (err) { /* 单个设置项渲染失败不阻断整体 */ }
      });
      container.appendChild(g);
    });
  }

  function buildControl(key, s) {
    const wrap = document.createElement('div');
    wrap.className = 'set-control';
    wrap.dataset.setting = key;
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
        if (key === 'glass_enabled') { if (BOOT && BOOT.settings_schema) BOOT.settings_schema[key].value = e.target.checked; applyHwAccel(); }   // 毛玻璃即时生效
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
        if (key === 'translate_source') updateSourceChip();   // 主页汉化源立即同步
        if (key === 'page_layout') {
          // 快捷方式/工具布局切换即时重渲染
          if (BOOT && BOOT.settings_schema) BOOT.settings_schema[key].value = Number(sel.value);
          if (currentPage === 'features' && BOOT && BOOT.features) renderFeatures(BOOT.features);
          if (currentPage === 'tools' && BOOT && BOOT.tools) renderTools(BOOT.tools);
        }
        if (key === 'frame_limit') { if (BOOT && BOOT.settings_schema) BOOT.settings_schema[key].value = Number(sel.value); applyFrameLimit(); }   // 帧率上限即时生效
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
        if (key === 'bg_gaussian_blur') refreshBackgrounds();   // 模糊度立即生效
        if (key === 'glass_factor') { if (BOOT && BOOT.settings_schema) BOOT.settings_schema[key].value = v; applyGlassFactor(); }  // 毛玻璃系数即时生效
      };
      wrap.appendChild(rw);
      return wrap;
    }
    // range2: 范围值 [最小, 最大], 两个数值输入
    if (type === 'range2') {
      const min = Number(s.min) || 0, max = Number(s.max) || 60, step = Number(s.step) || 1;
      const cur = getSettingValue(key);
      const curA = Array.isArray(cur) ? cur : (Array.isArray(s.default) ? s.default : [min, max]);
      const mk = (initVal) => {
        const inp = document.createElement('input');
        inp.type = 'number'; inp.min = min; inp.max = max; inp.step = step;
        inp.value = Number(initVal);
        inp.style.width = '86px'; inp.style.marginRight = '8px';
        return inp;
      };
      const iMin = mk(curA[0]), iMax = mk(curA[1]);
      const lblMin = document.createElement('span'); lblMin.className = 'range2-lbl'; lblMin.textContent = '最小';
      const lblMax = document.createElement('span'); lblMax.className = 'range2-lbl'; lblMax.textContent = '最大';
      const row = document.createElement('div');
      row.style.display = 'flex'; row.style.alignItems = 'center'; row.style.gap = '6px';
      row.appendChild(lblMin); row.appendChild(iMin); row.appendChild(lblMax); row.appendChild(iMax);
      const save = () => {
        const a = Number(iMin.value), b = Number(iMax.value);
        const lo = Math.min(a, b), hi = Math.max(a, b);
        iMin.value = lo; iMax.value = hi;   // 输入框同步, 避免显示 min>max
        markChanged(key, [lo, hi]);
        if (api) api.set_setting(key, [lo, hi]).then(() => updateBootSetting(key, [lo, hi])).catch(err => toast(String(err), 'error'));
      };
      iMin.onchange = save; iMax.onchange = save;
      wrap.appendChild(row);
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
      inp.onchange = () => { markChanged(key, inp.value); if (api) api.set_setting(key, inp.value).catch(e => toast(String(e), 'error')); updatePathChip(); };
      return wrap;
    }
    inp.onchange = () => {
      markChanged(key, inp.value);
      if (api) api.set_setting(key, inp.value).catch(err => toast(String(err), 'error'));
      if (key === 'game_path') updatePathChip();   // 主页游戏路径实时同步
    };
    wrap.appendChild(inp);
    return wrap;
  }

  // ---------------- 关于页 ----------------
  let aboutData = null;      // 后端贡献者数据
  let aboutIdx = 1;          // 当前板块: 0=程序介绍, 1=贡献者 (默认贡献者)

  function loadAbout() {
    if (!api) return;
    withTimeout(api.get_contributors(), 8000, null).then(d => {
      aboutData = d;
      renderAbout();
    }).catch(() => {});
  }

  function renderAbout() {
    if (!aboutData) return;
    // 程序介绍
    const p = aboutData.program || {};
    const prog = $('#about-panel-program');
    if (prog) {
      prog.innerHTML =
        '<div class="about-program-card">' +
          '<img class="about-program-icon" src="' + PROJECT_ICON + '" alt="">' +
          '<h1>FaustLauncher</h1>' +
          '<div class="ap-sub">浮士德启动器 · 您人生中绝无仅有的完美启动器</div>' +
          (p.version ? '<div class="ap-ver">' + esc(p.version) + '</div>' : '') +
          '<div class="ap-desc">' + esc(p.description || '') + '</div>' +
          '<div class="ap-links">' +
            '<button class="btn btn-ghost" data-link="https://github.com/f0lkskill/FaustLauncher">📦 GitHub</button>' +
            '<button class="btn btn-ghost" data-link="https://space.bilibili.com/599331034">🎬 反馈渠道</button>' +
          '</div>' +
        '</div>';
      // 外链绑定
      $$('[data-link]', prog).forEach(b => b.addEventListener('click', () => {
        const u = b.dataset.link;
        if (api) api.open_url(u).catch(() => {});
        else window.open(u, '_blank');
      }));
    }
    // 贡献者
    const contributors = aboutData.contributors || [];
    const card = $('#about-panel-contributors');
    if (card) {
      card.innerHTML =
        '<div class="about-contrib-card">' +
          '<div class="ac-list" id="ac-list"></div>' +
          '<div class="ac-detail" id="ac-detail"></div>' +
        '</div>';
      const list = $('#ac-list');
      contributors.forEach((c, i) => {
        const item = document.createElement('div');
        item.className = 'ac-item' + (i === 0 ? ' active' : '');
        item.innerHTML = '<img src="' + (c.icon_uri || PROJECT_ICON) + '" alt="">' +
          '<span>' + esc(c.name) + '</span>';
        item.onclick = () => {
          $$('.ac-item', list).forEach(x => x.classList.remove('active'));
          item.classList.add('active');
          renderContributorDetail(contributors[i]);
        };
        list.appendChild(item);
      });
      if (contributors.length) renderContributorDetail(contributors[0]);
    }
    buildAboutDots();
    setAboutIndex(aboutIdx);
  }

  function renderContributorDetail(c) {
    const d = $('#ac-detail');
    if (!d) return;
    const linkIcons = { github: '🐙 GitHub', blbl: '📺 B站', website: '🌐 网站', 官网: '🌐 官网' };
    const linkHtml = Object.entries(c.links || {}).map(([k, u]) =>
      '<button class="btn btn-ghost" style="font-size:12px;padding:6px 12px" onclick="window.__openUrl(\'' + esc(u) + '\')">' + (linkIcons[k] || '🔗 ' + k) + '</button>'
    ).join('') || '';
    d.innerHTML =
      '<div class="ac-detail-head">' +
        '<img class="ac-detail-avatar" src="' + (c.icon_uri || PROJECT_ICON) + '" alt="">' +
        '<div>' +
          '<div class="ac-detail-name">' + esc(c.name) + '</div>' +
          '<span class="ac-detail-role">' + esc(c.role) + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="ac-detail-desc">' + esc(c.description || '') + '</div>' +
      (linkHtml ? '<div class="ac-detail-links">' + linkHtml + '</div>' : '');
  }

  function buildAboutDots() {
    const wrap = $('#about-dots');
    if (!wrap) return;
    wrap.innerHTML = '';
    ['程序介绍', '贡献者'].forEach((label, i) => {
      const dot = document.createElement('button');
      dot.className = 'cdot' + (i === aboutIdx ? ' active' : '');
      dot.title = label;
      dot.onclick = () => setAboutIndex(i);
      wrap.appendChild(dot);
    });
  }

  function setAboutIndex(i) {
    aboutIdx = i;
    const panels = document.querySelectorAll('#about-stage .about-panel');
    panels.forEach((p, idx) => p.classList.toggle('active', idx === i));
    document.querySelectorAll('#about-dots .cdot').forEach((d, idx) => d.classList.toggle('active', idx === i));
  }

  // 关于页循环滚动切换板块 (0 程序介绍 ⇄ 1 贡献者, 无限循环)
  function bindAboutScroll() {
    const stage = $('#about-stage');
    if (!stage) return;
    let lock = false;
    stage.addEventListener('wheel', (e) => {
      e.preventDefault();
      if (lock) return;
      lock = true;
      setTimeout(() => { lock = false; }, 350);
      const total = document.querySelectorAll('#about-stage .about-panel').length;
      if (e.deltaY > 0) setAboutIndex((aboutIdx + 1) % total);
      else setAboutIndex((aboutIdx - 1 + total) % total);
    }, { passive: false });
  }

  // 关于页外链 (贡献者详情按钮)
  window.__openUrl = function (u) {
    if (api) api.open_url(u).catch(() => {});
    else window.open(u, '_blank');
  };
  // 启动与汉化更新互斥: 任一流程进行中, 两个按钮都禁用, 直到流程结束才恢复
  function setPipelineButtonsDisabled(disabled) {
    $('#btn-launch').disabled = disabled;
    $('#btn-translate').disabled = disabled;
  }

  async function onLaunch() {
    if (!api) { toast('浏览器预览模式, 无法启动游戏', 'warn'); return; }
    if (pipeline.running) return;   // 有流程正在进行, 不允许重复触发
    if (!$('#btn-launch').disabled) {
      setPipelineButtonsDisabled(true);
      pipelineReset(true); // 启动游戏: 含"启动游戏"步骤
      try { await api.launch_game(); } catch (e) { toast(String(e), 'error'); pipelineError(); }
    }
  }

  async function onTranslate() {
    if (!api) { toast('浏览器预览模式, 无法更新汉化', 'warn'); return; }
    if (pipeline.running) return;   // 汉化更新时禁止启动游戏 (反之亦然)
    if (!$('#btn-translate').disabled) {
      setPipelineButtonsDisabled(true);
      pipelineReset(false); // 汉化更新: 不含"启动游戏"步骤
      try { await api.update_translation(); }
      catch (e) { toast(String(e), 'error'); }
      setTimeout(() => { setPipelineButtonsDisabled(false); pipelineDone(); }, 800);
    }
  }

  // ---------------- 事件绑定 ----------------
  function bindEvents() {
    // 自定义标题栏: 拖动窗口 + 最小化/关闭
    const tb = document.getElementById('titlebar');
    if (tb) {
      const tbMin = document.getElementById('tb-min');
      const tbClose = document.getElementById('tb-close');
      if (tbMin) tbMin.addEventListener('click', () => { if (api) api.minimize_window().catch(() => {}); });
      if (tbClose) tbClose.addEventListener('click', () => { if (api) api.close_window().catch(() => {}); });
      // 拖动使用绝对屏幕坐标，后端根据拖动起点计算窗口位置，避免异步增量请求竞态
      tb.addEventListener('mousedown', (e) => {
        if (e.button !== 0 || e.target.closest('.tb-btn') || !e.target.closest('.tb-drag') || !api) return;
        e.preventDefault();
        e.stopPropagation();
        let dragRAF = null, pendingX = e.screenX, pendingY = e.screenY;
        let moveChain = api.begin_move_window(e.screenX, e.screenY).catch(() => {});
        const flush = () => {
          dragRAF = null;
          const x = pendingX, y = pendingY;
          moveChain = moveChain.then(() => api.move_window(x, y)).catch(() => {});
        };
        const onMove = (ev) => {
          pendingX = ev.screenX;
          pendingY = ev.screenY;
          if (!dragRAF) dragRAF = requestAnimationFrame(flush);
        };
        const onUp = () => {
          window.removeEventListener('mousemove', onMove);
          window.removeEventListener('mouseup', onUp);
          if (dragRAF) { cancelAnimationFrame(dragRAF); dragRAF = null; }
          const x = pendingX, y = pendingY;
          moveChain = moveChain
            .then(() => api.move_window(x, y))
            .then(() => api.end_move_window())
            .catch(() => {});
        };
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
      });
    }
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
    // 设置: 自动保存 (各控件修改即保存, 无保存按钮)
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
    $('.term-head').addEventListener('click', () => {
      const wasOpen = term.classList.contains('open');
      term.classList.toggle('open');
      if (!wasOpen && term.classList.contains('open')) retractCharIfBottom();
    });
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
    // 资源管理页: Mod 分区按钮
    $('#btn-open-mod-dir').addEventListener('click', async () => {
      if (!api) { toast('浏览器预览模式', 'warn'); return; }
      const r = await api.open_mods_dir('dir').catch(e => ({ error: String(e) }));
      if (r && r.error) toast(r.error, 'error');
    });
    $('#btn-open-mod-window').addEventListener('click', async () => {
      if (!api) { toast('浏览器预览模式', 'warn'); return; }
      const ok = await api.open_mod_manager_window().catch(() => false);
      toast(ok ? '独立 Mod 管理器已打开' : '打开失败, 详见终端', ok ? 'success' : 'error');
    });
    // 资源管理页: 插件分区按钮
    $('#btn-open-addon-dir').addEventListener('click', async () => {
      if (!api) { toast('浏览器预览模式', 'warn'); return; }
      const r = await api.open_mods_dir('addon').catch(e => ({ error: String(e) }));
      if (r && r.error) toast(r.error, 'error');
    });
    $('#btn-install-addon').addEventListener('click', async () => {
      if (!api) { toast('浏览器预览模式', 'warn'); return; }
      const r = await api.install_addon_dialog().catch(e => ({ error: String(e) }));
      if (r && r.error) toast('安装失败: ' + r.error, 'error');
      else if (r && r.ok) { toast('插件已安装', 'success'); refreshMods(); }
    });
    // 资源管理/下载中心搜索框
    const resSearchEl = $('#res-search');
    if (resSearchEl) resSearchEl.addEventListener('input', () => { resSearch = resSearchEl.value.trim(); resPage = 1; renderResList(); });
    const dcSearchEl = $('#dc-search');
    if (dcSearchEl) dcSearchEl.addEventListener('input', () => { dcSearch = dcSearchEl.value.trim(); dcPage = 1; renderDCList(); });
    // 资源管理页: 插件/Mod 切换 (按钮组随之切换)
    $$('.res-tab').forEach(t => t.addEventListener('click', () => {
      $$('.res-tab').forEach(x => x.classList.remove('active'));
      t.classList.add('active');
      resKind = t.dataset.kind;
      resPage = 1;
      syncResActions();
      renderResList();
    }));
    // 初始化按钮组状态 (默认插件分区)
    syncResActions();
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
      // tilt 是轻量 transform (卡片无 blur), 保持满帧跟随
      if (!tiltRAF) tiltRAF = requestAnimationFrame(applyTiltFrame);
    });
    document.addEventListener('mouseleave', () => {
      applyTiltBase();
    });
  }

  // ---------------- 背景 ----------------
  let _bgInterval = null;

  function applyBackgrounds(uris) {
    if (!uris || !uris.length) return;
    if (_bgInterval) { clearInterval(_bgInterval); _bgInterval = null; }
    const layer = $('#bg-layer');
    if (!layer) return;
    let idx = Math.floor(Math.random() * uris.length);
    let bgSlot = 'a';
    const show = (u) => {
      const im = new Image();
      im.onload = () => {
        const nextSlot = bgSlot === 'a' ? 'b' : 'a';
        layer.style.setProperty('--bg-image-' + nextSlot, 'url("' + u.replace(/"/g, '\\"') + '")');
        layer.classList.add('show-img');
        void layer.offsetWidth;
        layer.classList.add('bg-' + nextSlot);
        const oldSlot = bgSlot;
        setTimeout(() => layer.classList.remove('bg-' + oldSlot), 1150);
        bgSlot = nextSlot;
      };
      im.src = u;
    };
    show(uris[idx]);
    if (uris.length > 1) {
      _bgInterval = setInterval(() => {
        let n;
        do { n = Math.floor(Math.random() * uris.length); } while (n === idx);
        idx = n;
        show(uris[idx]);
      }, 25000);
    }
  }

  // 模糊度等背景相关设置变更后立即重新拉取背景
  function refreshBackgrounds() {
    if (api) withTimeout(api.get_backgrounds(), 6000, []).then(applyBackgrounds).catch(() => {});
  }

  // ---------------- 角色小人 (随机边缘探头摇摆) ----------------
  let charImages = [];
  let charGreetings = {};
  let _charGreetingsReady = false;
  let charEl = null, charImgEl = null;
  const CHAR_EDGES = ['right', 'bottom', 'top'];

  function initCharacter() {
    charEl = document.getElementById('character');
    if (!charEl) return;
    charImgEl = document.getElementById('character-img');
    charEl.addEventListener('click', onCharClick);
    // 图片与问候语都就绪后立即显示一次 (不等冷却)
    const tryStart = () => {
      if (charImages.length && _charGreetingsReady) characterCycle();
    };
    if (api) {
      withTimeout(api.get_characters(), 6000, []).then(list => {
        charImages = (list && list.length) ? list : [charFallbackItem()];
        tryStart();
      }).catch(() => { charImages = [charFallbackItem()]; tryStart(); });
      withTimeout(api.get_character_greetings(), 6000, {}).then(map => {
        charGreetings = map || {};
        _charGreetingsReady = true;
        tryStart();
      }).catch(() => { charGreetings = {}; _charGreetingsReady = true; tryStart(); });
    } else {
      charImages = [charFallbackItem()];
      charGreetings = {};
      _charGreetingsReady = true;
      characterCycle();
    }
  }

  function charFallbackItem() {
    return { name: 'faust_1.png', uri: '../../assets/images/character/faust_1.png' };
  }

  // 角色间隔范围设置 [min,max] (可在设置页调整)
  function charRange(key, dmin, dmax) {
    const s = BOOT && BOOT.settings_schema ? BOOT.settings_schema[key] : null;
    let v = s ? s.value : null;
    if (!Array.isArray(v) || v.length < 2) v = (s && Array.isArray(s.default)) ? s.default : [dmin, dmax];
    const a = Number(v[0]) || dmin, b = Number(v[1]) || dmax;
    return [Math.min(a, b), Math.max(a, b)];
  }
  function randInRange(r) { return (r[0] || 0) + Math.random() * ((r[1] || r[0] || 0) - (r[0] || 0)); }

  function scheduleCharacter() {
    const r = charRange('char_appear_interval', 10, 30);
    setTimeout(characterCycle, randInRange(r) * 1000);   // 缩回后在范围内随机再次出现
  }

  // 在边缘上随机像素位置 (比率 15%~85%), 并据此计算初始倾斜角度
  function randomCharPos(edge) {
    const ratio = 15 + Math.random() * 70;           // 沿边缘的随机位置 (15%~85%)
    const base = ((ratio - 50) / 50) * 10;           // 位置越偏边, 倾角越大 (±10°)
    const jitter = Math.random() * 6 - 3;            // 额外 ±3° 抖动
    const pos = { ratio: ratio.toFixed(1), angle: (base + jitter).toFixed(1) };
    if (edge === 'right') {
      // 角色为半身像 (无腿): 底部藏在屏幕下缘之外, 仅露出上半身
      pos.bottom = '-' + (40 + Math.random() * 40).toFixed(0) + 'px';
    }
    return pos;
  }

  function applyCharPose(edge, pos, hidden, noAnim) {
    const s = charEl.style;
    s.transition = noAnim ? 'none' : 'transform .75s cubic-bezier(.2,.8,.3,1)';
    s.left = 'auto'; s.right = 'auto'; s.top = 'auto'; s.bottom = 'auto';
    if (edge === 'right') {
      // 底部藏在屏幕外 (无腿), 仅水平镜像面向左, 探头露出约 75% 宽
      s.bottom = pos.bottom || '-50px';
      s.right = '0';
      s.transform = 'translate(' + (hidden ? '110%' : '25%') + ', 0) scaleX(-1)';
    } else if (edge === 'bottom') {
      s.left = pos.ratio + '%'; s.bottom = '0';
      s.transform = 'translate(-50%, ' + (hidden ? '110%' : '28%') + ') rotate(' + pos.angle + 'deg)';
    } else { // top
      // 顶部探头: 垂直翻转 (scaleY -1), 露出的是头部而非腿部
      s.left = pos.ratio + '%'; s.top = '0';
      s.transform = 'translate(-50%, ' + (hidden ? '-110%' : '-28%') + ') rotate(' + pos.angle + 'deg) scaleY(-1)';
    }
  }

  // 随机播放一次角色动效 (摇摆/弹跳/震动/缩放弹入/左右探头)
  function playCharAnim() {
    const CHAR_ANIMS = ['char-wiggle', 'char-bounce', 'char-shake', 'char-pop', 'char-nod'];
    const animClass = CHAR_ANIMS[Math.floor(Math.random() * CHAR_ANIMS.length)];
    charImgEl.classList.remove('char-wiggle', 'char-bounce', 'char-shake', 'char-pop', 'char-nod');
    void charImgEl.offsetWidth;
    charImgEl.classList.add(animClass);
    if (charEl._animTimer) { clearTimeout(charEl._animTimer); charEl._animTimer = null; }
    charEl._animTimer = setTimeout(() => charImgEl.classList.remove(animClass), 1400);
  }

  // 探头期间循环展示问候语: 每隔几秒换一条新文本, 每次配合角色动效
  function startCharSpeech(edge, pos, greetings) {
    if (!greetings || !greetings.length) return;
    let lastIdx = -1;
    const next = () => {
      let idx = Math.floor(Math.random() * greetings.length);
      if (greetings.length > 1 && idx === lastIdx) idx = (idx + 1) % greetings.length;
      lastIdx = idx;
      playCharAnim();
      showCharBubble(edge, pos, greetings[idx]);
      if (charEl._speechTimer) { clearTimeout(charEl._speechTimer); charEl._speechTimer = null; }
      const sr = charRange('char_speech_interval', 10, 15);
      charEl._speechTimer = setTimeout(next, randInRange(sr) * 1000);   // 范围内随机换一条
    };
    next();
  }

  // 角色问候语气泡: 弹入 -> 停留 -> 旋转坠落, 紧贴角色实际矩形, 箭头指向角色
  function showCharBubble(edge, pos, text) {
    const b = document.getElementById('char-bubble');
    if (!b || !text) return;
    hideCharBubble();
    b.style.display = '';
    b.style.setProperty('--bx', '0');
    b.style.setProperty('--by', '0');
    b.textContent = text;
    b.style.left = 'auto'; b.style.right = 'auto'; b.style.top = 'auto'; b.style.bottom = 'auto';
    const centered = (edge === 'bottom' || edge === 'top');   // 顶/底边缘气泡水平居中
    b.classList.add(edge === 'right' ? 'b-right' : edge === 'bottom' ? 'b-bottom' : 'b-top');
    // 用角色实际变换后的矩形定位, 保证气泡紧贴角色
    const cr = charEl.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight;
    if (edge === 'right') {
      // 角色在右下角: 气泡紧贴角色左侧, 垂直与角色中部对齐
      b.style.right = (vw - cr.left + 14) + 'px';
      b.style.top = (cr.top + cr.height / 2) + 'px';
      b.style.setProperty('--by', '-50%');
    } else if (edge === 'bottom') {
      // 角色在底部: 气泡在角色正上方居中
      b.style.left = (cr.left + cr.width / 2) + 'px';
      b.style.bottom = (vh - cr.top + 14) + 'px';
    } else { // top
      // 角色在顶部: 气泡在角色正下方居中
      b.style.left = (cr.left + cr.width / 2) + 'px';
      b.style.top = (cr.bottom + 14) + 'px';
    }
    charEl._bubbleCentered = centered;
    b.classList.add(centered ? 'char-bubble-in-c' : 'char-bubble-in');
    charEl._bubbleFallTimer = setTimeout(() => {
      b.classList.remove('char-bubble-in', 'char-bubble-in-c');
      b.classList.add(centered ? 'char-bubble-fall-c' : 'char-bubble-fall');
      charEl._bubbleGoneTimer = setTimeout(hideCharBubble, 950);
    }, 3500);
  }

  function hideCharBubble() {
    const b = document.getElementById('char-bubble');
    if (!b) return;
    if (charEl._bubbleFallTimer) { clearTimeout(charEl._bubbleFallTimer); charEl._bubbleFallTimer = null; }
    if (charEl._bubbleGoneTimer) { clearTimeout(charEl._bubbleGoneTimer); charEl._bubbleGoneTimer = null; }
    b.className = '';
    b.style.display = 'none';
  }

  function clearCharTimers() {
    if (charEl._wiggleTimer) { clearTimeout(charEl._wiggleTimer); charEl._wiggleTimer = null; }
    if (charEl._stayTimer) { clearTimeout(charEl._stayTimer); charEl._stayTimer = null; }
    if (charEl._speechTimer) { clearTimeout(charEl._speechTimer); charEl._speechTimer = null; }
    if (charEl._animTimer) { clearTimeout(charEl._animTimer); charEl._animTimer = null; }
    if (charImgEl) charImgEl.classList.remove('char-wiggle', 'char-bounce', 'char-shake', 'char-pop', 'char-nod');
    hideCharBubble();
  }

  // 点击立即缩回, 再次出现间隔同 scheduleCharacter (40s~120s)
  function onCharClick() {
    if (!charEl || charEl._edge == null) return;
    clearCharTimers();
    applyCharPose(charEl._edge, charEl._pos, true);
    setTimeout(scheduleCharacter, 800);   // 等收回动画完成
  }

  // 终端拉起时强制底部角色缩回 (底部会被终端遮挡)
  function retractCharIfBottom() {
    if (!charEl || charEl._edge !== 'bottom') return;
    clearCharTimers();
    const pos = charEl._pos;
    applyCharPose('bottom', pos, true);
    charEl._edge = null;
    setTimeout(scheduleCharacter, 800);
  }

  // 角色需要避让的关键交互元素 (尽量覆盖全部可点击控件)
  const CHAR_COLLIDE_SEL = 'button, a, input, select, textarea, [role="button"], .btn, .nav-item, .link-card, .dc-card, .mod-card, .set-row, .cdot, .chip, .term-head, .term-toggle, .dl-fab, .status-chips, .hero-actions, .dc-tab, .stat-label, .set-control';

  // 探测: 该边缘+位置是否与关键交互元素重叠 (临时放到可见位测 rect, 带膨胀边距)
  function posCollides(edge, pos) {
    if (!charEl) return false;
    applyCharPose(edge, pos, false, true);
    const r = charEl.getBoundingClientRect();
    const PAD = 8;   // 与关键元素保持间距, 视觉上不贴住
    const rr = { left: r.left - PAD, right: r.right + PAD, top: r.top - PAD, bottom: r.bottom + PAD };
    const els = document.querySelectorAll(CHAR_COLLIDE_SEL);
    for (let i = 0; i < els.length; i++) {
      const t = els[i];
      if (!t || t === charEl || t.contains(charEl) || charEl.contains(t)) continue;
      const tr = t.getBoundingClientRect();
      if (tr.width === 0 || tr.height === 0) continue;
      if (rr.right > tr.left && rr.left < tr.right && rr.bottom > tr.top && rr.top < tr.bottom) {
        return true;
      }
    }
    return false;
  }

  function characterCycle() {
    if (!charEl || !charImages.length) { scheduleCharacter(); return; }
    // 终端展开时避开底部边缘 (底部被终端占用)
    const termEl = document.getElementById('terminal');
    const termOpen = termEl ? termEl.classList.contains('open') : false;
    const availEdges = termOpen ? CHAR_EDGES.filter(e => e !== 'bottom') : CHAR_EDGES;
    // 多次尝试找一个不遮挡关键交互元素的位置 (最多 12 次)
    let edge, pos;
    for (let attempt = 0; attempt < 12; attempt++) {
      edge = availEdges[Math.floor(Math.random() * availEdges.length)];
      pos = randomCharPos(edge);
      if (!posCollides(edge, pos)) break;
    }
    charEl._edge = edge;
    charEl._pos = pos;
    // 随机选图片, 并按图片名取问候语表 (循环展示)
    const item = charImages[Math.floor(Math.random() * charImages.length)];
    charImgEl.src = item.uri;
    const greetings = charGreetings[item.name] || [];
    clearCharTimers();
    // 先无动画重置到新边缘的隐藏位, 下一帧再探头滑入
    applyCharPose(edge, pos, true, true);
    requestAnimationFrame(() => requestAnimationFrame(() => applyCharPose(edge, pos, false)));
    // 滑入完成后启动循环问候语 (每几秒换一条, 每次配合角色动效)
    charEl._wiggleTimer = setTimeout(() => {
      startCharSpeech(edge, pos, greetings);
    }, 800);
    // 停留设定时间 (范围内随机) 后收回, 然后进入下一轮
    charEl._stayTimer = setTimeout(() => {
      clearCharTimers();   // 停止文本循环与动效, 避免缩回后仍在展示
      applyCharPose(edge, pos, true);
      scheduleCharacter();
    }, randInRange(charRange('char_stay_interval', 40, 60)) * 1000);
  }

  // ---------------- 初始化 ----------------
  async function init() {
    // pywebview 注入时机不定, 每次初始化都重新探测
    api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
    IS_BROWSER = !api;
    const appRoot = document.getElementById('app');
    const titlebar = document.getElementById('titlebar');
    const startupRoots = [appRoot, titlebar].filter(Boolean);
    startupRoots.forEach(el => el.classList.add('startup-pending'));
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
      bindToolsCarousel();
      bindClickSound();
      initCharacter();
      bindAboutScroll();
      // 窗口缩放时重新计算卡片尺寸, 保持三卡填满主区宽度
      window.addEventListener('resize', () => {
        if (currentPage === 'features' || currentPage === 'tools') applyFeatSize();
      });
    } catch (e) {
      console.error('UI 初始化出错:', e);
    }
    // 基础 UI 已绑定后通知后端显示窗口，但 Splash 继续保留，直到下面的
    // bootstrap 和 render 完成，避免先显示纯色/半成品界面后再突然替换。
    if (api && typeof api.ui_ready === 'function') {
      requestAnimationFrame(() => requestAnimationFrame(() => {
        try { api.ui_ready().catch(() => {}); } catch (e) { /* 忽略 */ }
      }));
    }
    // 提前并行加载背景图与音效 (不依赖 bootstrap, 消除背景初始加载延迟)
    if (api) {
      withTimeout(api.get_backgrounds(), 6000, []).then(applyBackgrounds).catch(() => {});
      preloadSounds();
      // 定时同步主页路径芯片 (后端首次自动填充游戏路径后, 主页能及时更新)
      setInterval(() => {
        if (currentPage === 'home') updatePathChip();
      }, 5000);
      // 主页时钟 (年月日 + 秒级时间)
      const WEEK_CN = ['日', '一', '二', '三', '四', '五', '六'];
      const tickClock = () => {
        const d = new Date();
        const de = $('#hc-date'), te = $('#hc-time');
        if (de) de.textContent = d.getFullYear() + '年' + (d.getMonth() + 1) + '月' + d.getDate() + '日 星期' + WEEK_CN[d.getDay()];
        if (te) te.textContent = [d.getHours(), d.getMinutes(), d.getSeconds()].map(n => String(n).padStart(2, '0')).join(':');
      };
      tickClock();
      setInterval(tickClock, 1000);
    }
    try {
      if (api) {
        BOOT = await withTimeout(api.get_bootstrap(), 8000, null);
        if (!BOOT) { BOOT = MOCK; toast('后端响应超时, 已进入预览模式', 'error', 5000); }
        withTimeout(api.get_terminal(), 5000, []).then(lines => (lines || []).forEach(l => addLog(l))).catch(() => {});
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
    const splash = document.getElementById('app-splash');
    if (splash) {
      // UI 已完成渲染：与 Splash 淡出同时显示，避免转场结束时集中切换造成卡顿。
      requestAnimationFrame(() => {
        startupRoots.forEach(el => {
          el.classList.remove('startup-pending');
          el.classList.add('startup-ready');
        });
        splash.classList.add('hide');
        playWelcomeSound();
        setTimeout(() => { try { splash.remove(); } catch (e) {} }, 460);
      });
    } else {
      startupRoots.forEach(el => {
        el.classList.remove('startup-pending');
        el.classList.add('startup-ready');
      });
      playWelcomeSound();
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

// 对外插件 API: 全局命名空间 (供插件/扩展脚本直接调用内部功能)
window.Faust = {
  esc,
  toast,
  toastTop,
  addLog,
  switchPage,
  startDownloadItem,
  refreshMods,
  refreshRecommend,
  markItemDownloaded,
  fmtBytes,
  fmtSpeed,
  openResModal,
  openDcModal,
  get currentPage() { return currentPage; },
  get BOOT() { return BOOT; },
  get PROJECT_ICON() { return PROJECT_ICON; },
};

// 保底: splash 最多显示 15 秒 (init 异常时自动淡出, 避免卡在预加载画面)
setTimeout(() => {
  const splash = document.getElementById('app-splash');
  if (splash) {
    splash.classList.add('hide');
    setTimeout(() => { try { splash.remove(); } catch (e) {} }, 460);
    [document.getElementById('app'), document.getElementById('titlebar')].filter(Boolean).forEach(el => {
      el.classList.remove('startup-pending');
      el.classList.add('startup-ready');
    });
    playWelcomeSound();
  }
}, 15000);
