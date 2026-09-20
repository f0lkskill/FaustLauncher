/* ==============================================================================
 * js/features/pipeline.js — 启动/汉化更新流水线
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 步骤条渲染与状态推进(准备→下载→资源→气泡→安装→更新插件Mod→启动)
 *   · 关键字兜底解析(日志关键字 → 步骤推进)
 *   · 流水线卡显隐的 FLIP 布局过渡
 * 本文件提供:
 *  函数: flipGridBelow / pipelineReset / setStep / setPipelineStepDone / pipelineAdvance / pipelineError / pipelineDone / pipelineIdle / applyPipeTextHints / handlePipelineLog
 *  状态/常量: KEYWORD_MAP / PIPE_TEXT_HINTS
 * 依赖: 依赖 bootstrap/state/utils/ui.terminal
 * 加载顺序: 15/22    (拆分自原 app.js 行 576-723)
 * ============================================================================== */
'use strict';

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
