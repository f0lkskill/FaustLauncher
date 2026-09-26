/* ==============================================================================
 * js/core/bridge.js — 后端 → 前端 事件入口(唯一入口, 全部挂在 window 上)
 * ------------------------------------------------------------------------------
 * 职责:
 *   · window.__onLog       终端日志追加
 *   · window.__onTrayHint  托盘提示
 *   · window.__onResChanged 插件/Mod 增删后刷新已安装状态
 *   · window.__onPathSynced 后端自动填充游戏路径后同步设置页与主页
 *   · window.__onResError  卸载/删除失败提示
 *   · window.__onEvent    进度/状态/步骤/对话框/游戏启动退出/版本更新 的统一分发
 * 本文件提供:
 *  全局入口: window.__onLog / window.__onTrayHint / window.__onResChanged / window.__onPathSynced / window.__onResError / window.__onEvent
 * 依赖: 依赖 state/utils/terminal/downloads/pipeline/version_modal (均为运行时调用, 加载顺序不敏感)
 * 加载顺序: 4/22    (拆分自原 app.js 行 453-575)
 * ============================================================================== */
'use strict';

// ---- 推送入口(Python 侧 evaluate_js 调用; 这些名字是对外契约, 不要重命名) ----
window.__onLog = function (text) { addLog(text); };
window.__onTrayHint = function (text) { toast(text, 'info', 5000); };
// 卸载/安装插件/Mod 后由后端通知: 立即刷新已安装状态 (下载中心/主页每日推荐/资源管理)
window.__onResChanged = function (kind) {
if (typeof downloadedSeen !== 'undefined') downloadedSeen.clear();
// 资源管理: 仅当前在资源管理页才重刷, 保持分区/按钮组/搜索状态 (不在页内不强制刷新)
if (currentPage === 'mod_addon' && typeof refreshMods === 'function') {
  refreshMods(true).then(() => { if (typeof syncResActions === 'function') syncResActions(); });
}
if (typeof renderDCList === 'function') {
  const dcList = document.getElementById('dc-list');
  if (dcList) renderDCList();
}
if (typeof _currentRec !== 'undefined' && _currentRec && typeof renderRecommend === 'function') {
  renderRecommend(_currentRec);
}
// 插件增删/重载后: 插件可能注册了自定义汉化源, 主页"汉化源"名字要重新取
if (typeof updateSourceChip === 'function') updateSourceChip();
};
// 后端自动设置游戏路径后同步前端 (设置页控件 + 首页路径 chip)
window.__onPathSynced = function () {
if (typeof updatePathChip === 'function') updatePathChip();
if (api) {
  api.get_setting('game_path').then(v => {
    if (v !== undefined && v !== null) {
      const inp = document.querySelector('[data-setting="game_path"] input');
      if (inp && inp.value !== String(v)) inp.value = String(v);
    }
  }).catch(() => {});
}
};
// 卸载/删除失败 (如文件被占用) 时由后端通知
window.__onResError = function (msg) { toast(msg, 'error', 6000, 'caution'); };

window.__onEvent = function (event, data) {
  if (event === 'progress') {
    if (data && data.task) {
      updateDownloadTask(data.task, data);
      // 流水线 mods 阶段: 右侧详情逐个显示正在更新的 Mod/插件 (图标+进度+名称)
      const cur = pipeline.steps[pipeline.currentIdx];
      if (pipeline.running && cur && cur.key === 'mods') {
        updatePipeDownloadProgress(data);
        setPipeDetailIconByTask(data.task);
        const txtEl = $('#pipe-detail-text');
        if (txtEl) txtEl.textContent = '正在更新 ' + data.task + ' ...';
      }
      return;
    }
    // 汉化包/资源/气泡等主流程下载: 仅更新右侧详情进度条
    if (pipeline.running) updatePipeDownloadProgress(data);
  } else if (event === 'status') {
    if (data && typeof data === 'object' && data.task) {
      addLog('⟳ ' + String(data.text || ''));
      // 流水线运行中: 带 task 的状态逐项更新详情 (图标按任务名匹配云端图标)
      if (pipeline.running && data.text) {
        const txtEl = $('#pipe-detail-text');
        if (txtEl) txtEl.textContent = String(data.text);
        setPipeDetailIconByTask(data.task);
      }
      if (/(失败|错误|❌|出错)/.test(String(data.text || ''))) {
        failDownloadTask(data.task, String(data.text || '').slice(0, 80));
      }
      return;
    }
    // 对象形式 {text, icon}: 启动子步骤进度 → 更新流水线详情 (图标+文本)
    let text = data, icon = null;
    if (data && typeof data === 'object') { text = data.text || ''; icon = data.icon || null; }
    if (text) addLog('⟳ ' + String(text));
    if (pipeline.running && text) {
      const txtEl = $('#pipe-detail-text');
      if (txtEl) txtEl.textContent = String(text);
      const icoEl = $('#pipe-detail-ico');
      if (icoEl && icon) { icoEl.innerHTML = iconSvgAuto(icon); icoEl.dataset.task = ''; }
    }
  } else if (event === 'step') {
    // 若流水线未启动 (如启动时自动汉化更新), 自动显示并启动流水线
    if (!pipeline.running) pipelineReset(false);
    // 后端显式步骤推进 (与真实进度同步; 不再依赖日志关键词, 避免顺序错乱)
    const s = data && data.step;
    const idx = pipeline.steps.findIndex(x => x.key === s);
    if (idx >= 0 && idx > pipeline.currentIdx) {
      setPipelineStepDone(pipeline.currentIdx, true);
      pipeline.currentIdx = idx;
      setStep(idx, 'active');
      updatePipeDetail(s);
      hidePipeDownloadProgress();
    }
  } else if (event === 'pipeline_done') {
    // 自动流程 (启动时汉化更新) 完成后恢复按钮与流水线状态
    try { setPipelineButtonsDisabled(false); } catch (e) {}
    pipelineDone();
  } else if (event === 'dialog') {
    const d = data || {};
    const kind = d.kind || 'showinfo';
    const isErr = /error|ask/.test(kind);
    const text = (d.title ? '[' + d.title + '] ' : '') + (d.message || '');
    toast(text, isErr ? 'error' : 'warn', 6000);
    if (isErr && pipeline.running) pipelineError();
  } else if (event === 'game_started') {
    const li = pipeline.steps.findIndex(s => s.key === 'launch');
    setPipelineStepDone(li, true);
    // 状态统一由右侧详情面板显示
    hidePipeDownloadProgress();
    const icoEl = $('#pipe-detail-ico'), txtEl = $('#pipe-detail-text');
    if (icoEl) { icoEl.innerHTML = iconSvg('allApplication'); icoEl.dataset.task = ''; }
    if (txtEl) txtEl.textContent = '游戏已启动';
    // 游戏运行中保持按钮互斥 (退出后由 pipelineDone 恢复)
  } else if (event === 'game_exited') {
    pipelineDone();
    const icoEl = $('#pipe-detail-ico'), txtEl = $('#pipe-detail-text');
    if (icoEl) icoEl.innerHTML = iconSvg('allApplication');
    if (txtEl) txtEl.textContent = '游戏已退出';
  } else if (event === 'game_timeout') {
    pipelineError();
    const icoEl = $('#pipe-detail-ico'), txtEl = $('#pipe-detail-text');
    if (icoEl) icoEl.innerHTML = iconSvg('harm');
    if (txtEl) txtEl.textContent = '等待游戏启动超时, 请检查游戏是否正常安装';
    toast('等待游戏启动超时', 'error', 6000);
    setTimeout(() => { pipelineIdle(); }, 4000);
  } else if (event === 'path_confirm') {
    // Steam VDF 自动检测到游戏路径 -> 弹模态窗口问用户 (path 为空则直接要求手选)
    if (typeof openPathConfirmModal === 'function') openPathConfirmModal(data || {});
    return;
  } else if (event === 'version_update') {
    // 应用内版本更新模态窗口: 下载进度/状态 (status/progress/ready/error)
    updateVersionModalProgress(data);
  }
};
