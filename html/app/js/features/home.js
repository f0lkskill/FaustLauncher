/* ==============================================================================
 * js/features/home.js — 主页与整体渲染入口
 * ------------------------------------------------------------------------------
 * 职责:
 *   · render(): 依据 BOOT 数据渲染版本号、快捷方式、工具、设置等全部区块
 *   · 更新内容(changelog)的极简 Markdown 渲染 mdToHtml
 *   · 随机推荐: 候选池、抽取、渲染与刷新
 * 本文件提供:
 *  函数: render / mdToHtml / loadHomeExtras / pickRecItem / loadRecommend / refreshRecommend / renderRecommend
 *  状态/常量: recPool
 * 依赖: 依赖 bootstrap/state/utils/theme/features.* (运行时调用)
 * 加载顺序: 19/22    (拆分自原 app.js 行 1771-1971)
 * ============================================================================== */
'use strict';

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
  // 主页称呼 (玩家名) + 快捷方式 & 工具
  updateHeroUser();
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
  if (!md) return '<span class="changelog-empty">啊呀，看起来这里什么都没有呢...</span>';
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
    const md = await withTimeout(api.get_changelog(), 100000, null);
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
