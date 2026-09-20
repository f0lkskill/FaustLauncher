/* ==============================================================================
 * js/core/events.js — 应用外壳: 页面切换 + 全局事件绑定
 * ------------------------------------------------------------------------------
 * 职责:
 *   · switchPage: 侧栏导航与各页面懒初始化(资源管理/下载中心/设置/关于)
 *   · bindEvents: 窗口标题栏、启动/汉化按钮、资源管理页、下载中心、设置页、终端、下载抽屉等全部（绑定集中一处便于排查）
 * 本文件提供:
 *  函数: switchPage / bindEvents
 *  状态/常量: resInited
 * 依赖: 依赖 bootstrap/state/utils; 页面模块的函数在运行时调用
 * 加载顺序: 5/22    (拆分自原 app.js 行 724-759 + 3066-3241)
 * ============================================================================== */
'use strict';

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
    // 进入即清空旧列表 + 转圈, 等本次刷新结束再整屏渲染
    // (避免"旧列表先显示 -> 拉回数据又重画一遍"看起来像刷新两次)
    enterResourcePage();
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
  // 手动刷新云端列表: 忽略本次启动的已获取内容, 强制重新从云端拉取
  const dcRefreshEl = $('#dc-refresh');
  if (dcRefreshEl) dcRefreshEl.addEventListener('click', async () => {
    if (!api) { toast('浏览器预览模式', 'warn'); return; }
    if (dcRefreshEl.disabled) return;
    const oldText = dcRefreshEl.textContent;
    dcRefreshEl.disabled = true;
    dcRefreshEl.textContent = '⟳ 刷新中…';
    try {
      const r = await api.refresh_cloud_list('both');
      if (r && r.error) {
        toast('云端刷新失败: ' + r.error, 'error');
      } else {
        const c = (r && r.counts) || {};
        toast('已从云端刷新: ' + (c.addon || 0) + ' 插件 / ' + (c.mod || 0) + ' Mod', 'success');
      }
      loadDCDisplay();
    } catch (e) {
      toast('云端刷新失败: ' + e, 'error');
    } finally {
      dcRefreshEl.disabled = false;
      dcRefreshEl.textContent = oldText;
    }
  });
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
  // 主页版本卡: 点击查看版本信息 (有更新时可从这里手动下载)
  const verCard = $('#stat-version-card');
  if (verCard) {
    verCard.classList.add('clickable');
    verCard.addEventListener('click', async () => {
      if (!api) { toast('浏览器预览模式', 'warn'); return; }
      try {
        const d = await api.get_version_modal();
        if (d && d.error) { toast('读取版本信息失败: ' + d.error, 'error'); return; }
        openVersionModal(d);
      } catch (e) {
        toast('读取版本信息失败: ' + e, 'error');
      }
    });
  }
  // 背景点击预览用
  window.addEventListener('resize', () => {});
}
