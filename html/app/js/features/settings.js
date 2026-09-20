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

// 切换设置分区 tab
function switchSettingsTab(page) {
  settingsActiveTab = page;
  $$('#settings-groups .set-tab').forEach(t => t.classList.toggle('active', t.dataset.page === page));
  $$('#settings-groups .settings-group').forEach(g => { g.hidden = g.dataset.page !== page; });
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
  container.appendChild(tabsBox);
  // 分区内容 (仅显示当前 tab)
  pages.forEach(page => {
    const g = document.createElement('div');
    g.className = 'settings-group';
    g.dataset.page = page;
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
