/* ==============================================================================
 * js/features/tools.js — 实用工具面板(工具窗口入口)
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 工具卡片点击分发到各工具窗口/模态: 自动汉化、字体选择、渐变文本、扩展工具等
 *   · 字体预览与字体信息刷新
 * 本文件提供:
 *  函数: closePanel / openAutoTranslate / openFontSelector / openGradientTool / openExtensionTools
 * 依赖: 依赖 bootstrap/state/utils
 * 加载顺序: 18/22    (拆分自原 app.js 行 1519-1770)
 * ============================================================================== */
'use strict';

// ---------------- 工具面板 ----------------
// 统一的面板打开/关闭: 关闭时播放淡出动画后再移除 DOM; 点击遮罩空白处也可关闭
function closePanel(panel) {
  if (!panel || panel._closing) return;
  panel._closing = true;
  document.body.classList.remove('modal-open');
  panel.classList.add('closing');
  setTimeout(() => panel.remove(), 190);
}

// ---- 工具入口: 工具卡点击后分发到这里(每个工具一个 open* 函数) ----
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
