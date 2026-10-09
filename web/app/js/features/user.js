/* ============================================================================
 * js/features/user.js — 用户信息、云端同步与用户 ID 登录
 * ============================================================================ */
'use strict';

let userPageReady = false;
let userPageData = null;
let userIdVisible = false;   // 用户 ID 默认打码, 点"显示"才明文
let userLimitTimer = null;   // 冷却到期后的自动刷新定时器

function userNameFallback() {
  try {
    if (typeof getSettingValue === 'function' && typeof BOOT !== 'undefined' && BOOT && BOOT.settings_schema) {
      return String(getSettingValue('user_name') || 'Player');
    }
  } catch (e) { /* BOOT 未就绪时退回默认名 */ }
  return 'Player';
}

function userDataValues(data) {
  const user = (data && data.user) || {};
  const get = (key, fallback) => {
    const item = user[key];
    return item && item.value !== undefined ? item.value : fallback;
  };
  return {
    id: String(get('user_id', '')),
    skins: Array.isArray(get('unlocked_skins', [])) ? get('unlocked_skins', []) : [],
    name: String((data && data.user_name) || userNameFallback()),
  };
}

async function loadUserPage() {
  if (!api) return;
  const data = await api.get_user_info().catch(() => null);
  if (!data) return;
  userPageData = data;
  renderUserPage();
  renderRestrictions(data.restrictions);
  if (typeof renderSkinList === 'function' && skinList.length) renderSkinList();
}

// ---------------- 操作冷却 (改名 1 小时 / 登录 12 小时, 独立计时) ----------------
function formatLeft(seconds) {
  const t = Math.max(0, Math.floor(Number(seconds) || 0));
  if (!t) return '';
  if (t >= 86400) {
    const d = Math.floor(t / 86400), h = Math.floor((t % 86400) / 3600);
    return d + ' 天' + (h ? ' ' + h + ' 小时' : '');
  }
  if (t >= 3600) {
    const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60);
    return h + ' 小时' + (m ? ' ' + m + ' 分钟' : '');
  }
  return Math.max(1, Math.floor(t / 60)) + ' 分钟';
}

// 只重拉冷却状态 (改名/登录成功后调用, 让限制提示与按钮禁用立刻生效)
async function refreshRestrictions() {
  if (!api) return;
  const r = await api.get_restrictions().catch(() => null);
  if (!r) return;
  if (userPageData) userPageData.restrictions = r;
  renderRestrictions(r);
}

// 冷却期内直接禁用对应按钮 (后端还有一道硬拦截, 这里只是让用户一眼看到原因)
function renderRestrictions(r) {
  r = r || {};
  const renameLeft = formatLeft(r.rename_left);
  const loginLeft = formatLeft(r.login_left);

  const renameBtn = $('#user-name-open');
  if (renameBtn) {
    renameBtn.disabled = !!renameLeft;
    renameBtn.title = renameLeft
      ? '用户名 1 小时内只能修改一次，请 ' + renameLeft + '后再试'
      : '';
  }
  const loginBtn = $('#user-login-open');
  if (loginBtn) {
    loginBtn.disabled = !!loginLeft;
    loginBtn.title = loginLeft
      ? '登录 12 小时内只能进行一次，请 ' + loginLeft + '后再试'
      : '';
  }

  const note = $('#user-limit-note');
  if (!note) return;
  const lines = [];
  if (renameLeft) lines.push('用户名修改冷却中：还需 ' + renameLeft);
  if (loginLeft) lines.push('账号登录冷却中：还需 ' + loginLeft);
  note.hidden = !lines.length;
  note.innerHTML = lines.map(t => '<span class="user-limit-item">' + esc(t) + '</span>').join('');

  // 冷却到期后自动刷新一次, 届时按钮会自己恢复可用 (用户不必手动切页)
  if (userLimitTimer) { clearTimeout(userLimitTimer); userLimitTimer = null; }
  const lefts = [Number(r.rename_left) || 0, Number(r.login_left) || 0].filter(v => v > 0);
  if (lefts.length) {
    // 上限 30 分钟: 长冷却(12 小时)不必挂一个整天的定时器, 到期前分段复查即可
    const wait = Math.min(Math.min.apply(null, lefts) * 1000 + 1000, 30 * 60 * 1000);
    userLimitTimer = setTimeout(refreshRestrictions, wait);
  }
}

// 用户 ID 打码: 默认只露首尾, 避免在共享屏幕/截图时直接暴露完整凭据
function maskUserId(id) {
  const s = String(id || '');
  if (!s) return '未初始化';
  if (userIdVisible) return s;
  if (s.length <= 6) return '•'.repeat(s.length);
  return s.slice(0, 3) + '•'.repeat(s.length - 5) + s.slice(-2);
}

// 确认框里的简短打码: 不跟随"显示 ID"开关, 旧 ID 始终不全量暴露
function maskIdBrief(id) {
  const s = String(id || '');
  if (!s) return '—';
  if (s.length <= 6) return s;
  return s.slice(0, 3) + '••••' + s.slice(-2);
}

function renderUserId() {
  const el = $('#user-page-id');
  const btn = $('#user-id-toggle');
  const values = userDataValues(userPageData);
  if (el) {
    el.textContent = maskUserId(values.id);
    el.classList.toggle('user-id-masked', !userIdVisible && !!values.id);
  }
  // 按钮用图标表达"点击后会发生什么":
  //   打码中 -> 睁眼 (点击显示); 明文 -> 划掉的眼睛 (点击隐藏)
  if (btn) {
    const file = userIdVisible ? 'preview-close-one.svg' : 'eye.svg';
    btn.title = userIdVisible ? '隐藏用户 ID' : '显示用户 ID';
    if (btn.dataset.iconState !== file) {
      btn.dataset.iconState = file;
      // 占位由 icons.js 的自动水合补全, 无需手动调用
      btn.innerHTML = '<svg class="ico" data-icon="' + file + '" viewBox="0 0 48 48" fill="none" aria-hidden="true"></svg>';
    }
  }
}

// ---------------- 游玩时长 ----------------
// 当前游玩时长: 后端读的是本机 Steam 的 localconfig.vdf —— 也就是上报给排行榜的那个值。
// 读不到就照实说（未安装/未登录 Steam），不编数字。
function renderPlaytime() {
  const el = $('#user-playtime');
  if (!el) return;
  const p = (userPageData && userPageData.playtime) || null;
  if (p && p.ok && p.seconds > 0) {
    el.textContent = p.text || (Math.round((p.hours || 0) * 10) / 10 + ' 小时');
    el.classList.remove('is-empty');
    // 面板只给小时；更细的写法（X 天 X 小时）放 hover 提示
    el.title = p.detail ? ('本机 Steam 记录：' + p.detail) : '本机 Steam 记录';
  } else {
    el.textContent = '读不到';
    el.classList.add('is-empty');
    el.title = (p && p.error) || '未安装 / 未登录 Steam';
  }
}

// 打开官网页面: 主页必须用服务端给的 profile_token 拼（拿用户 ID 拼会 404）。
// 拿不到链接时只提示，不打开坏链接。
function openSitePage(field, label) {
  const url = String((userPageData && userPageData[field]) || '').trim();
  if (!url) {
    toast('拿不到' + label + '链接：请先登录并同步一次云端', 'warn');
    return;
  }
  if (typeof window.__openUrl === 'function') { window.__openUrl(url); return; }
  if (api && api.open_url) { api.open_url(url).catch(e => toast(String(e), 'error')); return; }
  toast('浏览器预览模式：' + url, 'info', 4000);
}

function renderUserPage() {
  const values = userDataValues(userPageData);
  const name = $('#user-page-name');
  const count = $('#user-skin-count');
  if (name) name.textContent = values.name;
  renderUserId();
  renderPlaytime();
  if (count) count.textContent = values.skins.length + ' 个';
  const list = $('#user-skin-list');
  if (!list) return;
  if (!values.skins.length) {
    list.innerHTML = '<div class="user-empty">暂未解锁皮肤</div>';
    return;
  }
  const names = new Map((skinList || []).map(s => [s.id, s.name]));
  list.innerHTML = values.skins.map(sid =>
    '<div class="user-skin-item"><span class="user-skin-dot"></span><span>' + esc(names.get(sid) || sid) + '</span><code>' + esc(sid) + '</code></div>'
  ).join('');
}

// ---------------- 名称编辑 (二级模态) ----------------
// 写入 settings.json 的 user_name, 后端会顺手把昵称推回云端账号。
async function submitUserName(value, current) {
  if (!api) { toast('浏览器预览模式', 'warn'); return false; }
  if (!value) { toast('名称不能为空', 'warn'); return false; }
  if (value === current) { toast('名称没有变化', 'warn'); return false; }
  const result = await api.set_setting('user_name', value).catch(e => ({ error: String(e) }));
  if (result && result.error) { toast(result.error, 'warn', 5000); return false; }
  // 同步前端缓存与其它页面 (主页问候语 / 设置页输入框)
  if (typeof updateBootSetting === 'function') updateBootSetting('user_name', value);
  if (typeof updateHeroUser === 'function') updateHeroUser();
  if (userPageData) userPageData.user_name = value;
  renderUserPage();
  // 立刻拉一次冷却状态: 本次改名刚开始计时, 不刷新的话按钮还是可点的
  await refreshRestrictions();
  toast('名称已保存', 'success');
  return true;
}

function openUserNameModal() {
  const old = document.getElementById('user-name-modal');
  if (old) old.remove();
  const current = userDataValues(userPageData).name;
  const panel = document.createElement('div');
  panel.id = 'user-name-modal';
  panel.className = 'panel-overlay';
  panel.innerHTML = '<div class="panel-card user-modal-card">' +
    '<div class="panel-head"><h3>修改名称</h3>' + panelCloseBtn('user-name-close') + '</div>' +
    '<div class="panel-body user-modal-body">' +
      '<p class="user-modal-tip">名称会写入设置，并同步到你的云端账号。</p>' +
      '<input class="user-modal-input is-text" id="user-name-input" type="text" maxlength="24" ' +
        'placeholder="输入你的名称" autocomplete="off" spellcheck="false" value="' + esc(current) + '">' +
    '</div>' +
    '<div class="panel-foot"><button class="btn btn-ghost" id="user-name-cancel">取消</button>' +
      '<button class="btn btn-primary" id="user-name-submit">保存</button></div>' +
    '</div>';
  document.body.appendChild(panel);
  document.body.classList.add('modal-open');
  // 关闭统一走 closePanel: 它会加 .closing 播完淡出动画再摘除节点,
  // 直接 panel.remove() 会跳过动画, 与其它模态窗口不一致。
  const close = () => closePanel(panel);
  $('#user-name-close').onclick = close;
  $('#user-name-cancel').onclick = close;
  panel.addEventListener('click', (e) => { if (e.target === panel) close(); });
  const input = $('#user-name-input');
  const submit = async () => {
    const btn = $('#user-name-submit');
    const value = input ? input.value.trim() : '';
    // 先做本地校验, 避免"名称没变"这类无效请求也去禁用按钮
    if (!value) { toast('名称不能为空', 'warn'); return; }
    if (value === current) { toast('名称没有变化', 'warn'); return; }
    if (btn) btn.disabled = true;
    const ok = await submitUserName(value, current);
    if (btn) btn.disabled = false;
    if (ok) close();
  };
  $('#user-name-submit').onclick = submit;
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); submit(); }
    });
  }
  setTimeout(() => { if (input) { input.focus(); input.select(); } }, 0);
}

function enterUserPage() {
  // 每次进入都刷新: 昵称可能在设置页改过, 解锁列表也可能刚变化
  userPageReady = true;
  loadUserPage();
}

async function syncUserFromPage() {
  if (!api) return;
  const btn = $('#user-sync');
  if (btn) btn.disabled = true;
  const result = await api.sync_user().catch(e => ({ ok: false, error: String(e) }));
  if (btn) btn.disabled = false;
  if (!result || !result.ok) toast((result && result.error) || '同步失败', 'error');
  else {
    // 同步成功后**重新拉一次完整资料**再渲染。
    // 以前这里用 `{ user, user_name }` 这个两键残片整体覆盖 userPageData，把
    // profile / playtime / profile_url / leaderboard_url 一起丢了 —— 于是刚点完"同步云端"，
    // 服务端资料面板、游玩时长、主页/排行榜按钮立刻全变"读不到"，切页重新 loadUserPage 才恢复。
    // 后端 sync_user 返回的字段名是 `cloud`，跟 get_user_info 的 `profile` 并不一致，
    // 所以别再手动拼一遍，直接复用 loadUserPage（顺带拿到刚上报后的游玩时长与冷却状态）。
    await loadUserPage();
    if (typeof loadSkins === 'function') await loadSkins();
    toast('用户信息已同步', 'success');
    // 本地已并集成功、但写回服务端失败: 皮肤会一直留在本地, 下次同步再补传
    if (result.push_error) toast('云端写入未完成：' + result.push_error, 'warn', 6000);
  }
}

function openUserLoginModal() {
  const old = document.getElementById('user-login-modal');
  if (old) old.remove();
  const panel = document.createElement('div');
  panel.id = 'user-login-modal';
  panel.className = 'panel-overlay';
  panel.innerHTML = '<div class="panel-card user-modal-card">' +
    '<div class="panel-head"><h3>使用用户 ID 登录</h3>' + panelCloseBtn('user-login-close') + '</div>' +
    '<div class="panel-body user-modal-body"><p class="user-modal-tip">输入你的用户 ID 进行登录。</p><input class="user-modal-input" id="user-login-input" type="text" placeholder="" autocomplete="off"></div>' +
    '<div class="panel-foot"><button class="btn btn-ghost" id="user-login-cancel">取消</button><button class="btn btn-primary" id="user-login-submit">登录</button></div>' +
    '</div>';
  document.body.appendChild(panel);
  document.body.classList.add('modal-open');
  // 关闭统一走 closePanel: 它会加 .closing 播完淡出动画再摘除节点,
  // 直接 panel.remove() 会跳过动画, 与其它模态窗口不一致。
  const close = () => closePanel(panel);
  $('#user-login-close').onclick = close;
  $('#user-login-cancel').onclick = close;
  panel.addEventListener('click', e => { if (e.target === panel) close(); });
  $('#user-login-submit').onclick = () => {
    const input = $('#user-login-input');
    const id = input ? input.value.trim() : '';
    if (!id) { toast('请输入用户 ID', 'warn'); return; }
    if (id === userDataValues(userPageData).id) { toast('当前已经是该账号', 'warn'); return; }
    // 切换账号会替换本地身份, 先让用户确认一次
    openLoginConfirmModal(id, () => doUserLogin(id, close));
  };
  setTimeout(() => $('#user-login-input')?.focus(), 0);
}

// 账号切换确认: 告知当前账号将被替换
function openLoginConfirmModal(userId, onConfirm) {
  const old = document.getElementById('user-login-confirm');
  if (old) old.remove();
  const cur = userDataValues(userPageData);
  const panel = document.createElement('div');
  panel.id = 'user-login-confirm';
  panel.className = 'panel-overlay';
  panel.innerHTML = '<div class="panel-card user-modal-card">' +
    '<div class="panel-head"><h3>确认切换账号</h3>' + panelCloseBtn('user-login-confirm-close') + '</div>' +
    '<div class="panel-body user-modal-body">' +
      '<div class="login-switch">' +
        '<div class="login-switch-row"><span class="user-label">当前账号</span>' +
          '<code>' + esc(maskIdBrief(cur.id)) + '</code>' +
        '</div>' +
        '<div class="login-switch-arrow">↓</div>' +
        '<div class="login-switch-row"><span class="user-label">切换为</span><code>' + esc(userId) + '</code></div>' +
      '</div>' +
      '<p class="unlock-hint">切换后，本地的已解锁皮肤以该账号的云端记录为准。</p>' +
    '</div>' +
    '<div class="panel-foot"><button class="btn btn-ghost" id="user-login-confirm-cancel">取消</button>' +
      '<button class="btn btn-primary" id="user-login-confirm-ok">确认切换</button></div>' +
    '</div>';
  document.body.appendChild(panel);
  document.body.classList.add('modal-open');
  const close = () => closePanel(panel);
  $('#user-login-confirm-close').onclick = close;
  $('#user-login-confirm-cancel').onclick = close;
  panel.addEventListener('click', (e) => { if (e.target === panel) close(); });
  $('#user-login-confirm-ok').onclick = () => { close(); onConfirm(); };
}

// 确认后真正执行登录 (只切换本地身份, 不动云端其它账号的记录)
async function doUserLogin(id, closeLoginModal) {
  const result = await api.login_user(id).catch(e => ({ ok: false, error: String(e) }));
  if (!result || !result.ok) { toast((result && result.error) || '登录失败', 'error'); return; }
  if (typeof closeLoginModal === 'function') closeLoginModal();
  // 昵称跟随新账号 (后端已写入设置项, 这里同步前端缓存与主页问候语)
  const newName = (result.cloud && result.cloud.user_name) || '';
  if (newName) {
    if (typeof updateBootSetting === 'function') updateBootSetting('user_name', newName);
    if (typeof updateHeroUser === 'function') updateHeroUser();
  }
  await loadUserPage();
  if (typeof loadSkins === 'function') await loadSkins();
  toast('已切换账号', 'success');
}

function bindUserEvents() {
  on('#user-copy-id', 'click', async () => {
    const values = userDataValues(userPageData);
    if (!values.id) return;
    // 即使处于打码状态, 复制的也是完整 ID
    try { await navigator.clipboard.writeText(values.id); toast('用户 ID 已复制', 'success'); }
    catch (_) { toast('复制失败', 'error'); }
  });
  on('#user-id-toggle', 'click', () => { userIdVisible = !userIdVisible; renderUserId(); });
  on('#user-name-open', 'click', openUserNameModal);
  on('#user-sync', 'click', syncUserFromPage);
  on('#user-open-profile', 'click', () => openSitePage('profile_url', '我的主页'));
  on('#user-open-leaderboard', 'click', () => openSitePage('leaderboard_url', '排行榜'));
  on('#user-login-open', 'click', openUserLoginModal);
  bindRestrictionsRefresh();
}

// ---------------- 窗口聚焦时刷新冷却时间 ----------------
// 为什么要监听焦点: 窗口在后台时 setTimeout 会被浏览器大幅节流(最短也常驻 1 分钟),
// 上一步挂的"冷却到期自动刷新"定时器在后台并不可靠;
// 而且用户可能刚从设置页改名、或切到别的窗口待了很久才回来。
// 每次窗口重新获得焦点就重新取一次冷却余量, 提示与按钮状态立刻回到准确值。
let _lastLimitSync = 0;
const LIMIT_SYNC_MIN_GAP = 8000;    // 8 秒内不重复请求 (alt-tab 来回切时避免刷接口)

function syncRestrictionsOnFocus() {
  const now = Date.now();
  if (now - _lastLimitSync < LIMIT_SYNC_MIN_GAP) return;
  _lastLimitSync = now;
  refreshRestrictions();
}

function bindRestrictionsRefresh() {
  window.addEventListener('focus', syncRestrictionsOnFocus);
  // 窗口最小化/恢复时 visibilitychange 也会触发, 作为 focus 的补充
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) syncRestrictionsOnFocus();
  });
  syncRestrictionsOnFocus();   // 启动时先取一次, 不必等第一次聚焦
}

function openSkinUnlockModal(skin) {
  const old = document.getElementById('skin-unlock-modal');
  if (old) old.remove();
  const condition = skin.unlock || {};
  const text = condition.description || '完成皮肤配置中的解锁条件后验证。';
  const panel = document.createElement('div');
  panel.id = 'skin-unlock-modal';
  panel.className = 'panel-overlay';
  panel.innerHTML = '<div class="panel-card user-modal-card unlock-modal-card">' +
    '<div class="panel-head"><h3>解锁 ' + esc(skin.name || skin.id) + '</h3>' + panelCloseBtn('skin-unlock-close') + '</div>' +
    '<div class="panel-body user-modal-body">' +
      '<div class="unlock-state"><span class="unlock-state-dot"></span>待解锁</div>' +
      '<p class="unlock-condition">' + esc(text) + '</p>' +
      '<p class="unlock-hint">点击验证后，启动器会检查当前条件是否满足。</p>' +
    '</div>' +
    '<div class="panel-foot"><button class="btn btn-ghost" id="skin-unlock-cancel">取消</button><button class="btn btn-primary" id="skin-unlock-check">验证并解锁</button></div>' +
    '</div>';
  document.body.appendChild(panel);
  document.body.classList.add('modal-open');
  // 关闭统一走 closePanel: 它会加 .closing 播完淡出动画再摘除节点,
  // 直接 panel.remove() 会跳过动画, 与其它模态窗口不一致。
  const close = () => closePanel(panel);
  $('#skin-unlock-close').onclick = close;
  $('#skin-unlock-cancel').onclick = close;
  panel.addEventListener('click', e => { if (e.target === panel) close(); });
  $('#skin-unlock-check').onclick = async () => {
    const btn = $('#skin-unlock-check');
    btn.disabled = true;
    const check = await api.verify_skin_unlock(skin.id).catch(e => ({ ok: false, error: String(e) }));
    if (!check || !check.ok || !check.unlocked) {
      btn.disabled = false;
      toast((check && check.error) || '解锁条件未满足', 'warn');
      return;
    }
    const result = await api.unlock_skin(skin.id).catch(e => ({ ok: false, error: String(e) }));
    if (!result || !result.ok) { btn.disabled = false; toast((result && result.error) || '解锁失败', 'error'); return; }
    close();
    await loadSkins();
    await loadUserPage();
    // 解锁即立刻用上: 未解锁期间后端把"当前皮肤"回退成了默认皮肤,
    // 这里重新应用一次, 玻璃窗的"使用中"标记与实际外观才一致。
    const target = (skinList || []).find(s => s.id === skin.id);
    if (target) await applySkin(target);
    toast('皮肤已解锁并同步云端', 'success');
  };
}
