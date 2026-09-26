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
