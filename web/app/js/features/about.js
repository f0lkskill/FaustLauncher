/* ==============================================================================
 * js/features/about.js — 关于页
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 程序信息与贡献者面板、横向滚动与圆点指示、贡献者详情模态
 * 本文件提供:
 *  函数: loadAbout / renderAbout / renderContributorDetail / buildAboutDots / setAboutIndex / bindAboutScroll / setPipelineButtonsDisabled / onLaunch / onTranslate
 *  状态/常量: aboutData / aboutIdx
 *  全局入口: window.__openUrl
 * 依赖: 依赖 bootstrap/state/utils
 * 加载顺序: 21/22    (拆分自原 app.js 行 2913-3065)
 * ============================================================================== */
'use strict';

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
          '<button class="btn btn-ghost" data-link="https://github.com/f0lkskill/FaustLauncher">' + iconSvg('code') + ' GitHub</button>' +
          '<button class="btn btn-ghost" data-link="https://space.bilibili.com/599331034">' + iconSvg('share') + ' 反馈渠道</button>' +
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
  // 贡献者外链按钮: 左侧图标按链接类型区分 (统一走 assets/icon 的 SVG)
  const linkIcons = {
    github: { icon: 'code', label: 'GitHub' },
    blbl: { icon: 'share', label: 'B站' },
    website: { icon: 'share', label: '网站' },
    '官网': { icon: 'share', label: '官网' },
  };
  const linkHtml = Object.entries(c.links || {}).map(([k, u]) => {
    const meta = linkIcons[k] || { icon: 'share', label: k };
    return '<button class="btn btn-ghost" style="font-size:12px;padding:6px 12px" onclick="window.__openUrl(\'' + esc(u) + '\')">' +
      iconSvg(meta.icon) + ' ' + esc(meta.label) + '</button>';
  }).join('') || '';
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
// 启动与汉化更新互斥。有了下方状态机后, 按钮的文案/图标/禁用态统一由
// renderLaunchButtons 依据 launchBtnState 推导, 这里只做"结束流程"的收尾,
// 避免两套逻辑互相覆盖 (以前它会无差别把按钮复位成"启动游戏/汉化更新")。
function setPipelineButtonsDisabled(disabled) {
  if (disabled) {
    $('#btn-launch').disabled = true;
    $('#btn-translate').disabled = true;
    return;
  }
  // 恢复: 清掉流程标记后按真实状态(含游戏是否在运行)重绘
  launchBtnState.pipeline = false;
  launchBtnState.pipelineKind = null;
  syncLaunchButtons();
}

// ---------------- 启动/更新按钮状态机 ----------------
// 两个按钮各自独立变形, 中止按钮**留在原来那个按钮上**:
//   启动游戏按钮: 启动游戏(power) → 中止启动(close) → 关闭游戏(close)
//   汉化更新按钮: 汉化更新(translate) → 中止更新(close)
// 即: 点"启动游戏"后的中止入口在启动按钮, 点"汉化更新"后的中止入口在汉化按钮,
// 不会串到另一个按钮上去。
//
// gameAlive 由后端 get_launch_state / game_state 事件驱动, 因此用户自己先开游戏
// 再回来点按钮时, 也会正确显示"关闭游戏"。
let launchBtnState = { pipeline: false, pipelineKind: null, gameAlive: false };

function _setBtnContent(btn, iconEl, textEl, iconName, text, cls) {
  if (iconEl && iconName) iconEl.innerHTML = iconSvg(iconName);
  if (textEl) textEl.textContent = text;
  if (btn && cls !== undefined) btn.className = cls;
}

function renderLaunchButtons() {
  const launchBtn = $('#btn-launch');
  const transBtn = $('#btn-translate');
  if (!launchBtn || !transBtn) return;
  const icoEl = $('#btn-launch-ico');
  const txtEl = $('#btn-launch-text');
  const tTxtEl = $('#btn-translate-text');
  const busy = launchBtnState.pipeline;
  const kind = launchBtnState.pipelineKind;

  // 流程进行中: 只有"发起该流程的那个按钮"变成中止, 另一个保持禁用
  // (启动与汉化更新互斥, 不会同时跑两个流程)
  const launchBusy = busy && kind === 'launch';
  const transBusy = busy && kind === 'translate';

  if (launchBusy) {
    _setBtnContent(launchBtn, icoEl, txtEl, 'close', '中止启动', 'btn btn-danger');
    launchBtn.disabled = false;   // 唯一可点的按钮: 中止
  } else if (launchBtnState.gameAlive) {
    _setBtnContent(launchBtn, icoEl, txtEl, 'close', '关闭游戏', 'btn btn-danger');
    launchBtn.disabled = busy;    // 汉化更新进行中时不可点
  } else {
    _setBtnContent(launchBtn, icoEl, txtEl, 'power', '启动游戏', 'btn btn-primary');
    launchBtn.disabled = busy;
  }

  if (transBusy) {
    _setBtnContent(transBtn, null, tTxtEl, null, '中止更新', 'btn btn-danger');
    transBtn.disabled = false;    // 唯一可点的按钮: 中止
  } else {
    _setBtnContent(transBtn, null, tTxtEl, null, '汉化更新', 'btn btn-success');
    transBtn.disabled = busy;
  }
}

// 向后端要一次真实状态并刷新按钮 (启动时 / 流程结束后 / 页面切回主页时调用)
async function syncLaunchButtons() {
  if (!api || !api.get_launch_state) { renderLaunchButtons(); return; }
  try {
    const st = await withTimeout(api.get_launch_state(), 5000, null);
    if (st) {
      launchBtnState.pipeline = !!st.running;
      launchBtnState.pipelineKind = st.kind || null;
      launchBtnState.gameAlive = !!st.game_alive;
    }
  } catch (e) { /* 拿不到就按当前本地状态渲染 */ }
  renderLaunchButtons();
}

// ---------------- 流程状态收敛轮询 ----------------
// 后端并非每条收尾路径都会向前端推事件。典型: 启动流程走到 launcher.launch()
// 时已经没有中止检查点 —— 既不会抛 _PipelineAborted (推不出 pipeline_aborted),
// 也没有别的结束事件, 于是按钮会永久卡在"中止启动"。
// 因此流程期间定期问一次后端"还在跑吗": 后端说流程已结束就主动收尾。
// (汉化更新原本靠 onTranslate 末尾的 setTimeout 兜底, 这里统一成同一条可靠路径。)
let _pipelineWatchTimer = null;

function stopPipelineWatch() {
  if (_pipelineWatchTimer) {
    clearInterval(_pipelineWatchTimer);
    _pipelineWatchTimer = null;
  }
}

function startPipelineWatch() {
  stopPipelineWatch();
  _pipelineWatchTimer = setInterval(async () => {
    if (!launchBtnState.pipeline) { stopPipelineWatch(); return; }
    if (!api || !api.get_launch_state) return;
    try {
      const st = await withTimeout(api.get_launch_state(), 4000, null);
      if (st && st.running === false) {
        stopPipelineWatch();
        finishPipelineUI();   // 后端流程已结束: 清流程标记并恢复按钮
      }
    } catch (e) { /* 本轮拿不到就下轮再试 */ }
  }, 2000);
}

async function onLaunch() {
  if (!api) { toast('浏览器预览模式, 无法启动游戏', 'warn'); return; }
  // 情形一: 正跑着"启动游戏"流程 -> 中止它 (中止入口就在本按钮上)
  if (launchBtnState.pipeline) {
    if (launchBtnState.pipelineKind === 'launch') doAbortPipeline();
    return;   // 汉化更新进行中: 本按钮已禁用, 不做任何事
  }
  // 情形二: 游戏已在运行 -> 关闭游戏
  if (launchBtnState.gameAlive) {
    const btn = $('#btn-launch');
    const txtEl = $('#btn-launch-text');
    if (btn) btn.disabled = true;
    if (txtEl) txtEl.textContent = '正在关闭...';
    try {
      const r = await api.kill_game();
      // 以后端回报的**真实** game_alive 为准: 关闭可能因权限不足而失败,
      // 不能因为"发出了关闭请求"就认为游戏已经关了 (否则按钮会一直显示关闭游戏)
      if (r && typeof r.game_alive === 'boolean') {
        launchBtnState.gameAlive = r.game_alive;
      } else if (r && r.ok) {
        launchBtnState.gameAlive = false;
      }
      if (r && r.ok) {
        toast('已关闭游戏', 'success');
      } else {
        toast('关闭游戏失败: ' + ((r && r.error) || '未知错误'), 'error', 6000);
      }
    } catch (e) { toast(String(e), 'error'); }
    if (btn) btn.disabled = false;
    // 再向后端确认一次, 彻底避免本地状态与真实状态不一致
    await syncLaunchButtons();
    return;
  }
  // 情形三: 正常启动
  if (pipeline.running) return;   // 有流程正在进行 (兜底)
  if ($('#btn-launch').disabled) return;
  launchBtnState.pipeline = true;
  launchBtnState.pipelineKind = 'launch';
  renderLaunchButtons();
  pipelineReset(true); // 启动游戏: 含"启动游戏"步骤
  startPipelineWatch();
  try {
    const r = await api.launch_game();
    if (r && r.ok === false) {
      // 后端拒绝启动 (例如已有流程在跑): pipelineError 内部会清掉流程标记并恢复按钮,
      // 否则按钮会一直停在"中止启动"却等不到任何收尾事件
      pipelineError();
      if (r.message) toast(r.message, 'warn', 6000);
    }
  } catch (e) {
    toast(String(e), 'error'); pipelineError();
  }
}

// 中止当前流程 (启动/汉化更新共用同一后端标志; 按钮文案按流程类型区分)
async function doAbortPipeline() {
  if (!api) return;
  const isLaunch = launchBtnState.pipelineKind === 'launch';
  const btn = isLaunch ? $('#btn-launch') : $('#btn-translate');
  const txtEl = isLaunch ? $('#btn-launch-text') : $('#btn-translate-text');
  if (btn) btn.disabled = true;   // 防重复点击, 等后端回事件
  if (txtEl) txtEl.textContent = isLaunch ? '正在中止启动...' : '正在中止更新...';
  toast(isLaunch ? '正在中止启动流程...' : '正在中止更新流程...', 'warn', 3000);
  try {
    const r = await api.abort_pipeline();
    // 后端此刻已经没有流程在跑: 说明流程其实早已结束 (只是前端还停在中止态),
    // 立即收尾, 不必干等一个永远不会到来的 pipeline_aborted 事件
    if (r && r.running === false) {
      finishPipelineUI();
      return;
    }
  } catch (e) {
    toast('中止失败: ' + String(e), 'error');
    if (btn) btn.disabled = false;
  }
}

async function onTranslate() {
  if (!api) { toast('浏览器预览模式, 无法更新汉化', 'warn'); return; }
  // 正跑着"汉化更新"流程 -> 中止它 (中止入口就在本按钮上)
  if (launchBtnState.pipeline) {
    if (launchBtnState.pipelineKind === 'translate') doAbortPipeline();
    return;   // 启动流程进行中: 本按钮已禁用
  }
  if (pipeline.running) return;   // 兜底
  if ($('#btn-translate').disabled) return;
  launchBtnState.pipeline = true;
  launchBtnState.pipelineKind = 'translate';
  renderLaunchButtons();
  pipelineReset(false); // 汉化更新: 不含"启动游戏"步骤
  startPipelineWatch();
  let r = null;
  try {
    r = await api.update_translation();
  } catch (e) { toast(String(e), 'error'); }
  if (r && r.ok === false && r.message) toast(r.message, 'warn', 6000);
  setTimeout(() => { finishPipelineUI(); }, 800);
}
