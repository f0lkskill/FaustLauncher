/* ==============================================================================
 * js/features/settings.js — 设置页
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 设置项渲染(按 page 分组/分页签)、控件构建(开关/下拉/滑块/颜色/路径)
 *   · 改动收集与即时生效(applySettingSideEffect)、单项重置、恢复默认
 * 本文件提供:
 *  函数: getSettingValue / updateBootSetting / getSettingOptions / updateSourceChip / updatePathChip / markChanged / applySettingSideEffect / switchSettingsTab / resetOneSetting / renderSettings / buildControl
 *  状态/常量: settingsActiveTab
 * 依赖: 依赖 bootstrap/state/utils/ui.theme
 * 加载顺序: 20/22    (拆分自原 app.js 行 2605-2912)
 * ============================================================================== */
'use strict';

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

// 主页汉化源芯片: 名字以后端为准 (插件可注册自定义汉化源, 插件加载/重载后会变)
function updateSourceChip() {
  const sc = $('#chip-source');
  if (!sc) return;
  const render = (name) => {
    sc.innerHTML = '<span class="dot"></span><span>汉化源: ' + esc(name || '未知') + '</span>';
  };
  const fallback = () => {
    const src = getSettingValue('translate_source');
    if (typeof src !== 'number') return;
    const opts = getSettingOptions('translate_source');
    render(opts[src] || '未知');
  };
  if (!api) { fallback(); return; }
  withTimeout(api.get_translate_source_name(), 4000, '')
    .then(name => { if (name) render(name); else fallback(); })
    .catch(fallback);
}

// 主页问候语: 用设置里的玩家名 (user_name), 改设置后立即同步
function updateHeroUser() {
  const el = $('#hero-user');
  if (!el) return;
  const render = (v) => {
    const name = String(v == null ? '' : v).trim();
    el.textContent = name || '但丁';   // 没设置就保留原来的味道
  };
  render(getSettingValue('user_name'));
  // 开机时再向后端核对一次 (与游戏路径芯片同一套做法, 保证显示的一定是已保存的值)
  if (api) {
    withTimeout(api.get_setting('user_name'), 3000, null)
      .then(v => { if (v != null) render(v); })
      .catch(() => {});
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

// ---------------- 游戏路径确认 (Steam VDF 自动检测 -> 询问用户) ----------------
// 硬性约定 (2026-09-25):
//   1) 路径里必须有 LimbusCompany.exe —— Steam 自动检测到的路径也一样, 没这个文件就
//      视为"没检测到", 不允许点"是"直接确认, 必须让用户自己选;
//   2) 没选出有效路径之前, 界面被这个模态完全锁住: 没有关闭按钮, 点遮罩/Esc 都无效,
//      同时给 body 加 .path-locked 让 #app 整体不可点 (标题栏的最小化/关闭仍可用);
//   3) 只有后端确认写入成功 (ok=true) 才关窗解锁; 取消选择 / 选到没有 exe 的目录都停在原地。
//
// 渲染流程 (2026-09-25 修: 不再"先说检测不到, 又突然改口弹新窗口"):
//   锁定(检测中, 转圈) --后端结果--> 确认窗口(是/不是) 或 手选窗口
//   · 启动时路径无效/未设置 -> 立刻锁界面并显示"正在检测", 后端结果没到之前不下结论;
//   · 后端结果 (push path_confirm, 或兜底轮询 get_pending_steam_path) 到了才渲染最终状态;
//   · 等满 PC_POLL_MAX_MS 仍没结果 (后端异常) -> 兜底切到"请选择游戏目录";
//   · **同一状态绝不重建 DOM** (以前每次重渲染都把按钮组顶掉, 结果没到前点都点不到);
//   · 轮询拿到结果立刻收工, 不会反复触发; 用户正在操作时收到的推送延后应用, 不打断操作。
let pcModalEl = null;      // 当前模态 DOM
let pcState = '';          // 当前渲染状态签名 (loading / ask:路径 / manual:原因)
let pcSettled = false;     // 已经写入有效路径 -> 不再打扰
let pcPolled = false;      // 兜底轮询已结束 (拿到结果 / 超时 / 接口不可用)
let pcPulling = false;     // 轮询是否在跑
let pcBusy = false;        // 正在等待后端写入 / 用户选目录
let pcDeferred = null;     // 交互中收到的后端推送, 等交互结束再应用
let pcLastRaw = '';        // 最近一次后端给的原始路径 (被否掉时用于说明)
let pcExeName = 'LimbusCompany.exe';   // 后端给的 exe 名 (界面提示用)

const PC_POLL_MAX_MS = 15000;    // 等后端检测结果的上限
const PC_POLL_STEP_MS = 800;

function pcLock(on) {
  try {
    document.body.classList.toggle('path-locked', !!on);
    document.body.classList.toggle('modal-open', !!on);
  } catch (e) {}
}

function closePathModal() {
  const el = pcModalEl;
  pcModalEl = null;
  pcState = '';
  pcBusy = false;
  pcDeferred = null;
  pcLock(false);
  if (el) closePanel(el);
}

function pcHint(text, kind) {
  const el = document.getElementById('pc-hint');
  if (!el) return;
  if (!text) { el.hidden = true; el.textContent = ''; return; }
  el.hidden = false;
  el.className = 'pc-hint' + (kind ? ' ' + kind : '');
  el.textContent = text;
}

// 后端错误码 -> 人话
function pcErrorText(err) {
  if (err === 'empty') return '路径不能为空';
  if (err === 'not_found') return '目录不存在';
  if (err === 'no_exe') return '这个目录下没有 ' + pcExeName;
  if (err === 'no_game_path') return '还没有设置有效的游戏路径';
  return err || '未知错误';
}

// 结束一次交互: 把期间收到的后端推送补上 (同状态不重建, 所以不会顶掉按钮)
function pcEndBusy() {
  pcBusy = false;
  const d = pcDeferred;
  pcDeferred = null;
  if (d && !pcSettled) renderPathConfirmModal(d);
}

// 底部按钮: 确认模式给"是/不是"; 手选模式给"选择游戏目录"; 检测中不给按钮
function pcRenderFoot(mode) {
  const foot = document.getElementById('pc-foot');
  if (!foot) return;
  if (mode === 'ask') {
    foot.innerHTML = '<button class="btn btn-ghost" id="pc-no">不是，我自己选</button>' +
      '<button class="btn btn-primary" id="pc-yes">是，就用它</button>';
  } else if (mode === 'manual') {
    foot.innerHTML = '<button class="btn btn-primary" id="pc-pick">选择游戏目录…</button>';
  } else {
    foot.innerHTML = '<span class="pc-foot-note">正在等待检测结果…</span>';
  }
  const yes = document.getElementById('pc-yes');
  if (yes) yes.onclick = pcAcceptDetected;
  const no = document.getElementById('pc-no');
  if (no) no.onclick = pcPickManually;
  const pick = document.getElementById('pc-pick');
  if (pick) pick.onclick = pcPickManually;
}

// 状态签名: 相同就不重建 DOM (这是"按钮组被顶掉"的根治点)
function pcStateKey(d) {
  const raw = String((d && d.path) || '').trim();
  if (raw && d.path_ok !== false) return 'ask:' + raw;
  return raw ? 'manual:invalid:' + raw : 'manual:empty';
}

// 构建/就地替换模态 (替换时不做关闭动画, 避免遮罩闪一下)
function pcMount(eyebrow, title, bodyHtml, footMode, hint, hintKind) {
  if (pcModalEl) { const old = pcModalEl; pcModalEl = null; old.remove(); }
  const panel = document.createElement('div');
  panel.id = 'pc-modal';
  panel.className = 'pc-overlay';
  panel.innerHTML =
    '<div class="pc-card">' +
      '<span class="pc-accent" aria-hidden="true"></span>' +
      '<header class="pc-head">' +
        '<img class="pc-mark" src="' + PROJECT_ICON + '" alt="" draggable="false">' +
        '<div class="pc-head-main">' +
          '<div class="pc-eyebrow">' + eyebrow + '</div>' +
          '<div class="pc-title">' + title + '</div>' +
        '</div>' +
      '</header>' +
      '<div class="pc-rule"></div>' + bodyHtml +
      '<div class="pc-hint" id="pc-hint" hidden></div>' +
      '<footer class="pc-foot" id="pc-foot"></footer>' +
    '</div>';
  document.body.appendChild(panel);
  pcModalEl = panel;
  pcLock(true);           // 锁住 #app: 没选出有效路径之前什么都点不了
  pcRenderFoot(footMode);
  if (hint) pcHint(hint, hintKind || '');
}

// 检测中: 只锁界面 + 转圈, 不下"没检测到"的结论
function renderPathLoading() {
  if (pcBusy) return;
  if (pcModalEl && pcState === 'loading') return;
  pcState = 'loading';
  pcMount('正在检测游戏路径', '正在从 Steam 读取边狱巴士路径…',
    '<div class="pc-loading"><span class="pc-spin" aria-hidden="true"></span>' +
      '<span>正在解析 Steam 库文件，稍等片刻…</span></div>' +
    '<div class="pc-desc">检测到有效路径会请你确认；没检测到就需要你自己选一个游戏目录。</div>',
    'loading');
}

function renderPathConfirmModal(d) {
  d = d || {};
  if (pcBusy) { pcDeferred = d; return; }        // 用户正在操作: 别打断, 结束再应用
  if (d.game_exe) pcExeName = String(d.game_exe);
  const exe = pcExeName;
  const key = pcStateKey(d);
  if (pcModalEl && pcState === key) return;      // 状态没变 -> 绝不重建
  const raw = String(d.path || '').trim();
  pcLastRaw = raw;
  const canConfirm = !!raw && d.path_ok !== false;   // 目录里有 exe 才允许"是"
  pcState = key;
  if (canConfirm) {
    pcMount('检测到游戏路径', '这是你的游戏路径吗？',
      '<div class="pc-desc">启动器已自动从 <b>Steam VDF</b> 读取到边狱巴士安装路径（不是你手填的）：</div>' +
      '<div class="pc-path" title="' + esc(raw) + '">' + esc(raw) + '</div>',
      'ask');
    return;
  }
  const body = raw
    ? '<div class="pc-desc">启动器从 <b>Steam VDF</b> 读到的路径里<b>没有 ' + esc(exe) + '</b>，按无效路径处理：</div>' +
      '<div class="pc-path" title="' + esc(raw) + '">' + esc(raw) + '</div>' +
      '<div class="pc-desc">请手动选择游戏根目录（目录里必须有 <code>' + esc(exe) + '</code>），否则启动器无法继续使用。</div>'
    : '<div class="pc-desc">启动器没能从 <b>Steam VDF</b> 自动找到边狱巴士。' +
      '请手动选择游戏根目录（目录里必须有 <code>' + esc(exe) + '</code>），否则启动器无法继续使用。</div>';
  pcMount('需要设置游戏路径', '请选择游戏目录', body, 'manual',
    raw ? 'Steam 里读到的是上面这个路径，但里面没有 ' + exe + '，请自己选一个游戏目录。' : '',
    raw ? 'warn' : '');
}

function openPathConfirmModal(d) {
  d = d || {};
  if (d.force) { pcSettled = false; pcPolled = false; }   // 路径后来失效: 重新锁界面
  if (pcSettled) return;                                  // 已写入有效路径, 不再打扰
  renderPathConfirmModal(d);
}

// 写入成功: 关窗解锁 + 提示 (自动下探一层时说明一下)
function pcDone(r) {
  pcSettled = true;
  pcPolled = true;
  closePathModal();
  const path = (r && r.path) || '';
  const extra = (r && r.auto_fixed) ? '（已自动定位到含 ' + pcExeName + ' 的子目录）' : '';
  toastTop('游戏路径已保存: ' + path + extra, 'success', 5000);
  updatePathChip();
}

// 「是」: 让后端写入自动检测到的路径 (后端仍会硬校验 exe)
async function pcAcceptDetected() {
  if (!api) { pcHint('浏览器预览模式无法写入设置', 'warn'); return; }
  if (pcBusy) return;
  pcBusy = true;
  pcHint('正在写入…');
  const r = await api.confirm_steam_game_path(true).catch(e => ({ ok: false, error: String(e) }));
  if (r && r.ok) { pcDone(r); return; }
  // 后端否掉了自动检测到的路径 (没 exe / 目录没了) -> 直接换成手选窗口
  const code = (r && r.error) || '';
  pcBusy = false;
  renderPathConfirmModal({ path: code === 'no_exe' ? pcLastRaw : '', path_ok: false,
                           game_exe: pcExeName });
  pcHint('自动检测到的路径不可用（' + pcErrorText(code) + '），请自己选一个游戏目录。', 'error');
  pcEndBusy();
}

// 「不是」/ 没检测到: 强制自己选 (非空 + 目录里有 exe 才算选好; 取消就停在这里等重选)
async function pcPickManually() {
  if (!api) { pcHint('浏览器预览模式无法选择目录', 'warn'); return; }
  if (pcBusy) return;
  pcBusy = true;
  // 先否定自动检测到的路径, 让后端别再用它
  api.confirm_steam_game_path(false).catch(() => {});
  pcHint('正在等待选择游戏目录…');
  const picked = await api.pick_folder().catch(() => '');
  const path = String(picked || '').trim();
  if (!path) {
    // 路径非空是硬要求: 空路径不写入, 窗口也不关, 等用户重新选
    pcHint('没有选择任何目录。游戏路径不能为空，请重新点「选择游戏目录…」选一个。', 'warn');
    pcEndBusy();
    return;
  }
  const r = await api.apply_game_path(path).catch(e => ({ ok: false, error: String(e) }));
  if (r && r.ok) { pcDone(r); return; }
  const code = r && r.error;
  pcHint(code === 'no_exe'
    ? '这个目录里没有 ' + pcExeName + '。请选到游戏根目录（' + pcExeName + ' 所在的那个文件夹），否则启动器无法继续。'
    : '这个路径不可用（' + pcErrorText(code) + '），请重新选择。', 'error');
  pcEndBusy();
}

// 启动即锁: 设置里存的路径无效 (或压根没设置) 时, 不等后端延迟检查, 立刻锁界面。
// 只显示"检测中", 等后端结果到了再决定弹确认窗口还是手选窗口 (避免先说"没检测到"又改口)。
function lockFromBootPath() {
  if (!api || pcSettled || pcModalEl) return;
  if (typeof BOOT === 'undefined' || !BOOT) return;
  if (BOOT.game_path_ok === undefined) return;       // 老后端 / 预览模式: 不做预锁
  if (BOOT.game_path_ok) return;                     // 路径有效, 放行
  renderPathLoading();
}

// 兜底: 后端检测是异步的, 结果可能早于/晚于前端就绪 —— 轮询到结果立刻收工并渲染最终状态
async function pullPendingPathConfirm() {
  lockFromBootPath();
  if (!api || pcSettled || pcPolled || pcPulling) return;
  if (typeof api.get_pending_steam_path !== 'function') {
    pcPolled = true;
    renderPathConfirmModal({ path: '', path_ok: false, game_exe: pcExeName });
    return;
  }
  pcPulling = true;
  const t0 = Date.now();
  try {
    while (Date.now() - t0 < PC_POLL_MAX_MS) {
      if (pcSettled) return;
      const info = await api.get_pending_steam_path().catch(() => null);
      if (info && typeof info === 'object' && info.checked) {
        pcPolled = true;                 // 一次性: 拿到结果就再也不轮询
        openPathConfirmModal(info);
        return;
      }
      await new Promise(r => setTimeout(r, PC_POLL_STEP_MS));
    }
    if (!pcSettled) {                    // 后端一直没结果 (异常): 兜底让用户自己选
      pcPolled = true;
      renderPathConfirmModal({ path: '', path_ok: false, game_exe: pcExeName });
    }
  } finally {
    pcPulling = false;
  }
}

// ---- 改动收集与即时生效 ----
function markChanged(key, value) {
  SETTING_CHANGES[key] = { value };
  const s = BOOT.settings_schema[key];
  if (s && s.key_el) s.key_el.dataset.changed = '1';
}

let settingsActiveTab = null;   // 当前激活的设置分区 tab (重渲染后保留)

// 设置项即时生效副作用 (重置单项后手动触发, 与 buildControl 中保持一致)
function applySettingSideEffect(key, v) {
  if (!BOOT || !BOOT.settings_schema) return;
  const s = BOOT.settings_schema[key];
  if (key === 'glass_enabled') { BOOT.settings_schema[key].value = v; applyHwAccel(); }
  else if (key === 'translate_source') updateSourceChip();
  else if (key === 'user_name') updateHeroUser();
  else if (key === 'page_layout') {
    BOOT.settings_schema[key].value = v;
    if (currentPage === 'features' && BOOT.features) renderFeatures(BOOT.features);
    if (currentPage === 'tools' && BOOT.tools) renderTools(BOOT.tools);
  }
  else if (key === 'frame_limit') { BOOT.settings_schema[key].value = v; applyFrameLimit(); }
  else if (key === 'bg_gaussian_blur') refreshBackgrounds();
  else if (key === 'glass_factor') { BOOT.settings_schema[key].value = v; applyGlassFactor(); }
  else if (key === 'game_path') updatePathChip();
  else if (s && s.type === 'color') applyTheme(v);
}

// 切换设置分区 tab (重播"设置项逐行淡入"的加载动画)
function switchSettingsTab(page) {
  settingsActiveTab = page;
  $$('#settings-groups .set-tab').forEach(t => t.classList.toggle('active', t.dataset.page === page));
  let active = null;
  $$('#settings-groups .settings-group').forEach(g => {
    g.hidden = g.dataset.page !== page;
    if (!g.hidden) active = g;
  });
  animateSettingsGroup(active);
}

// 重播分区的"设置项进入动画": 逐行错峰淡入上浮
// (切换 tab / 首次渲染 / 恢复默认后重渲染时调用)
function animateSettingsGroup(group) {
  if (!group) return;
  const rows = group.querySelectorAll('.set-row');
  if (!rows.length) return;
  group.classList.remove('sg-enter');
  void group.offsetWidth;                   // 强制重排, 让动画可以重播
  rows.forEach((row, i) => { row.style.animationDelay = Math.min(i * 0.03, 0.3) + 's'; });
  group.classList.add('sg-enter');
}

// 重置单个设置项为默认值
async function resetOneSetting(key) {
  if (!api) { toast('浏览器预览模式', 'warn'); return; }
  const s = BOOT.settings_schema[key];
  if (!s) return;
  if (s.type === 'UNABLE_TO_EDIT' || s.type === 'unable_to_edit') return;
  if (s.default === undefined) { toast('该设置项没有默认值', 'warn'); return; }
  try {
    await api.set_setting(key, s.default);
    delete SETTING_CHANGES[key];
    if (BOOT.settings_schema) BOOT.settings_schema[key].value = s.default;
    applySettingSideEffect(key, s.default);
    renderSettings(BOOT.settings_schema);
    toast('已重置: ' + (s.name || key), 'success');
  } catch (e) { toast('重置失败: ' + e, 'error'); }
}

// 恢复所有设置项为默认值
// (设置页顶部右侧那个"↺ 恢复默认"按钮的逻辑; 按钮由 renderSettings 创建并绑定, 见那里)
async function resetAllSettings() {
  if (!api) { toast('浏览器预览模式', 'warn'); return; }
  const btn = $('#btn-reset-settings');
  if (btn && btn.disabled) return;                 // 防连点
  if (btn) { btn.disabled = true; btn.textContent = '↺ 重置中…'; }
  try {
    const schema = BOOT.settings_schema;
    for (const key of Object.keys(schema)) {
      const s = schema[key];
      // 跳过无法编辑的项
      if (s.type === 'UNABLE_TO_EDIT' || s.type === 'unable_to_edit') continue;
      if (s.default !== undefined) await api.set_setting(key, s.default);
    }
    await api.save_settings({});
    SETTING_CHANGES = {};
    const fresh = await api.get_bootstrap();
    BOOT.settings_schema = fresh.settings_schema;
    renderSettings(BOOT.settings_schema);           // 重渲染(会重建按钮), 各分区重播进入动画
    toast('已恢复默认设置', 'success');
  } catch (e) {
    toast('重置失败: ' + e, 'error');
    const b = $('#btn-reset-settings');             // 失败时恢复按钮可用
    if (b) { b.disabled = false; b.textContent = '↺ 恢复默认'; }
  }
}

// ---- 设置页渲染: 分组 / 分页签 ----
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
  if (!pages.includes(settingsActiveTab)) settingsActiveTab = pages[0] || null;
  // 顶部分页 tab
  const tabsBox = document.createElement('div');
  tabsBox.className = 'settings-tabs';
  pages.forEach(page => {
    const t = document.createElement('button');
    t.className = 'set-tab' + (page === settingsActiveTab ? ' active' : '');
    t.type = 'button';
    t.dataset.page = page;
    t.textContent = page;
    t.onclick = () => switchSettingsTab(page);
    tabsBox.appendChild(t);
  });
  
  // 重置所有设置项按钮(靠右): 由本函数动态创建, 因此就在这里绑定点击行为
  const resetBtn = document.createElement('button');
  resetBtn.className = 'btn btn-ghost';
  resetBtn.id = 'btn-reset-settings';
  resetBtn.textContent = '↺ 恢复默认';
  resetBtn.onclick = resetAllSettings;
  tabsBox.appendChild(resetBtn);

  container.appendChild(tabsBox);
  // 分区内容 (仅显示当前 tab)
  const groupEls = {};                      // page -> group 元素, 供切换 tab 时重播进入动画
  pages.forEach(page => {
    const g = document.createElement('div');
    g.className = 'settings-group';
    g.dataset.page = page;
    groupEls[page] = g;
    if (page !== settingsActiveTab) g.hidden = true;
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
        // 每项独立重置按钮 (不可编辑项除外)
        if (s.type !== 'UNABLE_TO_EDIT' && s.type !== 'unable_to_edit' && s.default !== undefined) {
          const rb = document.createElement('button');
          rb.className = 'set-reset';
          rb.type = 'button';
          rb.title = '重置该设置为默认值';
          rb.innerHTML = '↺';
          rb.onclick = () => resetOneSetting(key);
          row.appendChild(rb);
        }
        g.appendChild(row);
      } catch (err) { /* 单个设置项渲染失败不阻断整体 */ }
    });
    container.appendChild(g);
  });
  // 首次渲染 / 恢复默认后重渲染: 当前分区也播一次"逐行淡入"
  animateSettingsGroup(groupEls[settingsActiveTab]);
}

// ---- 控件构建: 开关 / 下拉 / 滑块 / 颜色 / 路径 / 只读 ----
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
      if (!p) return;
      // 游戏路径必须过 exe 硬校验 (与启动时的确认窗口同一套规则)
      const r = await api.apply_game_path(p).catch(e => ({ ok: false, error: String(e) }));
      if (!r || !r.ok) {
        toast('这个目录不能用：' + pcErrorText(r && r.error) + '（目录里必须有 ' + pcExeName + '）', 'error', 6000);
        return;
      }
      inp.value = r.path;
      markChanged(key, r.path);
      updatePathChip();
      if (r.auto_fixed) toast('已自动定位到含 ' + pcExeName + ' 的子目录：' + r.path, 'info', 5000);
    };
    const rw = document.createElement('div');
    rw.style.display = 'flex'; rw.style.gap = '8px'; rw.style.alignItems = 'center';
    rw.appendChild(inp); rw.appendChild(btn);
    wrap.appendChild(rw);
    inp.style.width = '200px';
    inp.onchange = async () => {
      const v = String(inp.value || '').trim();
      if (!v) { toast('游戏路径不能为空', 'warn'); return; }
      const r = await api.apply_game_path(v).catch(e => ({ ok: false, error: String(e) }));
      if (!r || !r.ok) {
        toast('路径无效：' + pcErrorText(r && r.error) + '（目录里必须有 ' + pcExeName + '）', 'error', 6000);
        return;
      }
      if (r.path !== inp.value) inp.value = r.path;
      markChanged(key, r.path);
      updatePathChip();
    };
    return wrap;
  }
  inp.oninput = () => {   // 主页称呼随输入即时同步
    if (key === 'user_name') { updateBootSetting(key, inp.value); updateHeroUser(); }
  };
  inp.onchange = () => {
    markChanged(key, inp.value);
    if (api) api.set_setting(key, inp.value).catch(err => toast(String(err), 'error'));
    if (key === 'game_path') updatePathChip();   // 主页游戏路径实时同步
    if (key === 'user_name') { updateBootSetting(key, inp.value); updateHeroUser(); }   // 主页称呼立即同步
  };
  wrap.appendChild(inp);
  return wrap;
}
