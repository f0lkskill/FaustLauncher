/* ==============================================================================
 * js/app.js — 入口: 启动流程 / 对外插件 API / 收尾兜底
 * ------------------------------------------------------------------------------
 * 职责:
 *   · init(): 顺序启动(探测 api → 页面与事件绑定 → 背景/音效 → bootstrap → render → 收敛)
 *   · window.Faust: 对外插件 API(供扩展脚本调用内部功能)
 *   · splash 最长 15 秒兜底淡出(init 异常也不会卡在预加载画面)
 * 本文件提供:
 *  启动编排: init —— 按 ① 环境准备 → ② 首屏数据 → ③ UI 绑定 → ④ 通知后端 → ⑤ 预取(背景/音效/时钟)
 *                      → ⑥ 拉取 bootstrap → ⑦ 渲染与尺寸锁定 → ⑧ 收尾(splash 淡出) 的顺序编排
 *  阶段函数: startupPrepare / startupLoadFirstScreen / startupBindUI / startupNotifyUiReady /
 *            startupStartPrefetch / startHomeClock / startupFetchBootstrap / startupRender / startupFinish
 *  全局入口: window.Faust
 * 依赖: 必须最后加载(启动即调用前面所有模块)
 * 加载顺序: 22/22    (拆分自原 app.js 行 3772-3920)
 * ------------------------------------------------------------------------------
 * 【文件分区总览】(由原 3900 行单体 app.js 按功能拆分, 内容未改动)
 *
 *   js/core/          基座层 — 环境、状态、工具、与后端的通道、应用外壳
 *     bootstrap.js      环境探测(api/IS_BROWSER)、全局错误浮层、卡片 loading 兜底、$ / $$、诊断工具
 *     state.js          MOCK 预览数据 + 全局状态(BOOT/currentPage/pipeline) + 流水线步骤与详情文案
 *     utils.js           esc/toast/toastTop/withTimeout/hydrateIcons/fmtBytes/fmtSpeed/shortPath
 *     bridge.js         后端 → 前端的事件入口(window.__onLog/__onEvent/__onResChanged/...)
 *     events.js         页面切换(switchPage) + 全局 DOM 事件绑定(bindEvents)
 *
 *   js/ui/            界面件层 — 可复用的外观与交互
 *     theme.js          主题色推导、玻璃透明度、硬件加速、帧率上限、rAF 节流
 *     sound.js          欢迎/点击音效(浏览器内核播放)
 *     frame_loading.js  卡片加载转圈(spinner)控制
 *     terminal.js       ANSI → HTML 着色 + 终端日志追加
 *     tilt.js           3D 鼠标聚焦倾斜
 *     background.js     背景图层
 *     character.js      角色小人(探头摇摆)与问候语气泡
 *     carousel.js       3D 卡片轮播(快捷方式/工具)与丝滑拖拽
 *     version_modal.js  版本更新二级模态窗口
 *
 *   js/features/      业务层 — 页面级功能
 *     pipeline.js       启动/汉化更新流水线
 *     resources.js      资源管理页(本地插件/Mod)
 *     downloads.js      下载中心 + 下载任务抽屉
 *     tools.js          实用工具面板与工具窗口入口
 *     home.js           主页(整体渲染入口 render / 更新内容 / 随机推荐)
 *     settings.js       设置页
 *     about.js          关于页
 *
 * 【维护约定】
 *   1. 所有文件共享同一个全局作用域(顶层函数/变量即全局 API, 便于插件扩展直接调用),
 *      因此不能给两个文件声明同名顶层 const/let/var/function, 也不能随意打乱加载顺序。
 *      新增模块请插到对应层级内, 并同步更新 index.html 的 <script> 列表与这里的总览。
 *   2. 每个文件自带 'use strict'; 保持严格模式与原单体文件一致。
 *   3. 改动前端后请同步提升 index.html 里 style.css / *.js 的 ?v=NN 缓存版本号。
 *   4. 新增代码请按原风格分区块, 用 `// ---------------- 区块名 ----------------` 分隔。
 * ============================================================================== */
'use strict';

// ---------------- 初始化 (启动流程) ----------------
// 启动拆成 8 个有名字的阶段, init() 只负责按顺序编排它们:
//   ① 环境准备 → ② 首屏数据(不等待) → ③ UI 绑定 → ④ 通知后端 → ⑤ 预取(背景/音效/时钟)
//   → ⑥ 拉取 bootstrap → ⑦ 渲染与尺寸锁定 → ⑧ 收尾(splash 淡出)
// 好处: 每个阶段可单独排查, 任何一步失败都不会整屏白掉(降级路径见各阶段内部)。

// ① 环境准备: 探测 pywebview 桥接对象(注入时机不定, 每次初始化都重新探测), 给外壳打上启动态;
//    立即显示主页, 让推荐卡/版本卡圆圈一开始就可见 (否则在 display:none 的页面里转, 用户看不到)。
//    返回收尾阶段要用的根元素。
function startupPrepare() {
  api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
  IS_BROWSER = !api;
  const appRoot = document.getElementById('app');
  const titlebar = document.getElementById('titlebar');
  const startupRoots = [appRoot, titlebar].filter(Boolean);
  startupRoots.forEach(el => el.classList.add('startup-pending'));
  switchPage('home');
  return startupRoots;
}

// ② 首屏数据: 主页加载最早触发, 独立于 bindEvents/applyTilt/BOOT/render,
//    任何后续步骤出错都不会阻断, 预置 spinner 必被 finally 移除
function startupLoadFirstScreen() {
  loadHomeExtras().catch(e => console.error('主页加载失败:', e));
  loadRecommend().catch(e => console.error('推荐加载失败:', e));
}

// ③ 一次性 UI 绑定: 出错只记录日志, 不阻断后面的数据渲染
function startupBindUI() {
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
    // 绑定中途抛异常会让它后面的交互静默失效(按钮点不动/3D 聚焦失效/抽屉打不开),
    // 所以除了 console, 还要打到终端与提示上, 别再让这类问题藏起来
    console.error('UI 初始化出错:', e);
    addLog('\u001b[91m[UI] 事件绑定失败: ' + (e && e.message ? e.message : e) + '\u001b[0m');
    toast('界面初始化异常, 部分按钮可能不可用 (详见终端)', 'error', 6000);
  }
}

// ④ 通知后端"基础 UI 已绑定, 可以显示窗口了"。Splash 继续保留, 直到下面的
//    bootstrap 和 render 完成, 避免先显示纯色/半成品界面后再突然替换。
function startupNotifyUiReady() {
  if (!api || typeof api.ui_ready !== 'function') return;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    try { api.ui_ready().catch(() => {}); } catch (e) { /* 忽略 */ }
  }));
}

// ⑤ 预取: 背景图与音效并行加载 (不依赖 bootstrap, 消除背景初始加载延迟),
//    并启动主页的两个定时同步 (路径芯片 / 时钟)
function startupStartPrefetch() {
  if (!api) return;
  withTimeout(api.get_backgrounds(), 6000, []).then(applyBackgrounds).catch(() => {});
  preloadSounds();
  // 定时同步主页路径芯片 (后端首次自动填充游戏路径后, 主页能及时更新)
  setInterval(() => {
    if (currentPage === 'home') updatePathChip();
  }, 5000);
  startHomeClock();
}

// 主页时钟 (年月日 + 秒级时间)
function startHomeClock() {
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

// ⑥ 拉取后端 bootstrap 数据: 超时/失败一律降级到 MOCK(预览模式)并给出可读提示
async function startupFetchBootstrap() {
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
}

// ⑦ 渲染 + 锁定初始窗口内容宽度 (最大化/缩放窗口后控件保持初始大小并居中)
function startupRender() {
  try {
    render();
  } catch (e) {
    console.error('render 出错:', e);
  }
  applyTiltBase();
  const firstPage = document.querySelector('.page');
  if (firstPage) {
    document.documentElement.style.setProperty('--page-w', Math.floor(firstPage.getBoundingClientRect().width) + 'px');
  }
}

// ⑧ 收尾: 标记启动完成, 并与 Splash 淡出同时显示, 避免转场结束时集中切换造成卡顿
function startupFinish(startupRoots) {
  const reveal = () => startupRoots.forEach(el => {
    el.classList.remove('startup-pending');
    el.classList.add('startup-ready');
  });
  const splash = document.getElementById('app-splash');
  if (!splash) { reveal(); playWelcomeSound(); return; }
  requestAnimationFrame(() => {
    reveal();
    splash.classList.add('hide');
    playWelcomeSound();
    setTimeout(() => { try { splash.remove(); } catch (e) {} }, 460);
  });
}

// 启动编排: 顺序即依赖顺序 (渲染必须等 bootstrap; 收尾必须等渲染)
async function init() {
  const startupRoots = startupPrepare();
  startupLoadFirstScreen();
  startupBindUI();
  startupNotifyUiReady();
  startupStartPrefetch();
  await startupFetchBootstrap();
  startupRender();
  startupFinish(startupRoots);
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
  openVersionModal,
  closeVersionModal,
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
