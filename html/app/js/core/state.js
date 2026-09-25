/* ==============================================================================
 * js/core/state.js — 全局状态与常量 + 流水线步骤定义
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 浏览器预览用 MOCK 数据(无 pywebview 时兜底)
 *   · 应用级状态: BOOT / PROJECT_ICON / SETTING_CHANGES / currentPage / pipeline
 *   · 启动流水线与汉化更新流水线的步骤表(STEPS_FULL / STEPS_TRANSLATE)与详情文案
 *   · 流水线右侧详情区(图标/文本/下载进度)、按任务名匹配云端图标
 * 本文件提供:
 *  函数: isOurPlaySource / updatePipeDetail / updatePipeDownloadProgress / hidePipeDownloadProgress / setPipeDetailIconByTask
 *  状态/常量: MOCK / BOOT / PROJECT_ICON / SETTING_CHANGES / currentPage / pipeline / STEPS_FULL / STEPS_TRANSLATE / STEP_DETAILS
 * 依赖: 依赖 bootstrap.js; 流水线状态被 bridge/pipeline 读写
 * 加载顺序: 2/22    (拆分自原 app.js 行 105-241)
 * ============================================================================== */
'use strict';

// ---------------- Mock (浏览器预览) ----------------
const MOCK = {
  version: 'V0.7.1-release',
  game_path: '',
  bg_color: '#181818',
  features: [
    { name: '📁 游戏目录', desc: '打开边狱巴士安装目录', image: 'game_directory.png' },
    { name: '🔄 零协会', desc: '前往零协会汉化组主页', image: 'zeroasso.png' },
    { name: '📒 气泡文本', desc: '下载气泡 Mod 汉化版', image: '' },
    { name: '📝 维基', desc: '边狱巴士灰机 Wiki', image: 'wiki.png' },
    { name: '📖 N网', desc: '下载边狱巴士 Mod', image: 'nexus.png' },
    { name: '📦 GitHub', desc: '查看本项目源码', image: 'github.png' },
  ],
  tools: [
    { id: 'custom_translation', name: '🔧 自定义汉化', desc: '可视化编辑 lang 下任意 JSON 文本\n一键编辑替换汉化文本\n自动记录差异性文本，汉化更新也不丢失修改内容！', image: 'custom_translation.png' },
    { id: 'gradient', name: '💻 渐变文本处理器', desc: '生成 Unity 富文本渐变色代码', image: 'gradient.png' },
    { id: 'folder_link', name: '📂 文件夹超链接', desc: '创建符号链接, 转移C盘资源文件', image: 'folder_link.png' },
    { id: 'nyos', name: '📖 今日指令', desc: '获取食指的最新指令\n仅供娱乐，请勿上升到指令成瘾。', image: 'nyos.png' },
    { id: 'extension_tools', name: '🧩 扩展工具', desc: '插件模板 / 打包发布\n给开发者提供的工具\n需要输入开发者密钥。', image: 'extension_tools.png' },
    { id: 'font', name: '📝 字体修改', desc: '选择字体替换汉化包字体', image: 'font.png' },
    // { id: 'auto_translate', name: '🤖 自动汉化', desc: '思知 AI 批量剧情文本翻译' },
  ],
  settings_schema: {
    game_path: { name: '游戏路径', type: 'string', default: '', value: '', description: '游戏安装路径', page: '通用' },
    translate_source: { name: '汉化包平台方', type: 'combobox', options: ['零协会', 'OurPlay 普通版', 'OurPlay 神人版'], default: 0, value: 0, description: '选择下载的汉化包来源平台', page: '通用' },
    after_gui_exit: { name: '退出后操作', type: 'combobox', options: ['最小化到系统托盘', '关闭程序'], default: 0, value: 0, description: '退出程序后, 程序将如何操作', page: '通用' },
    user_name: { name: '用户名', type: 'string', default: 'Player', value: 'Player', description: '你的用户名，将显示在边狱巴士的个人车票上', page: '美化' },
    enable_show_user_name: { name: '显示用户名', type: 'boolean', default: true, value: true, description: '是否显示用户名在边狱巴士的个人车票上', page: '美化' },
    enable_mods: { name: '启用Mod功能', type: 'boolean', default: true, value: true, description: '是否加载 Mod', page: 'Mod' },
    bubble_text_gradient_rate: { name: '气泡文本渐变系数', type: 'float', default: 0.4, value: 0.4, min: 0.1, max: 1.0, step: 0.1, description: '越大的值意味着颜色渐变越快', page: '美化' },
    bg_color: { name: '主题颜色（实验性）', type: 'color', default: '#181818', value: '#181818', description: '应用程序的主题颜色', page: '其它' },
    version_info: { name: '版本信息', type: 'UNABLE_TO_EDIT', default: 'V0.7.1-release', value: 'V0.7.1-release', description: '当前应用程序的版本信息' },
  },
  is_frozen: false,
  project_root: '',
};

// ---------------- 全局状态 ----------------
let BOOT = null;
// 项目图标 (后端 bootstrap 就绪后替换为 data URI, 供下载中心/推荐卡/关于页图标回退)
// 默认值必须是**页面同源**的文件 (pywebview 用本地 http 服务加载页面, root = html/app/,
// ../../assets/... 会被服务端拒绝 -> 坏图; bootstrap 到了之后这里会换成 data URI)
let PROJECT_ICON = 'assets/icon/icon.png';
let SETTING_CHANGES = {};   // key -> {value, touched}
let currentPage = 'home';
let pipeline = {
  running: false,
  currentIdx: -1,
  steps: [],
};

// 完整流水线 (启动游戏) / 汉化更新流水线 (不含启动游戏)
// 左侧列表保留各步骤专属图标; 右侧详情大图标统一为火箭
const STEPS_FULL = [
  { key: 'prepare', label: '准备检查', icon: '🔍' },
  { key: 'download', label: '下载汉化包', icon: '📥' },
  { key: 'resource', label: '检查资源', icon: '🗂️' },
  { key: 'bubble', label: '下载气泡', icon: '💬' },
  { key: 'install', label: '安装汉化', icon: '📦' },
  { key: 'mods', label: '更新插件/Mod', icon: '🧩' },
  { key: 'launch', label: '启动游戏', icon: '🚀' },
];
// 汉化更新流水线: 不含"更新插件/Mod"和"启动游戏" (汉化更新不重载插件、不启动游戏)
const STEPS_TRANSLATE = STEPS_FULL.filter(s => s.key !== 'launch' && s.key !== 'mods');

// 流水线右侧详情文案 (fn 参数可拿当前汉化源, 区分 OurPlay / 零协会)
function isOurPlaySource() {
  return Number(getSettingValue('translate_source') || 0) !== 0;
}
const STEP_DETAILS = {
  prepare: () => '正在检查游戏路径与运行环境...',
  download: () => isOurPlaySource()
    ? '正在从 OurPlay 服务器下载最新汉化包...'
    : '正在从零协会社区下载最新汉化包...',
  resource: () => '正在检查云端资源更新 (字体/素材)...',
  bubble: () => '正在下载战斗气泡汉化文本...',
  install: () => isOurPlaySource()
    ? '正在校验并转码 OurPlay 汉化包...'
    : '正在解压并将汉化文件合并到游戏目录...',
  mods: () => '正在对比云端版本, 更新已安装的插件与 Mod...',
  launch: () => '正在启动边狱巴士...',
};

// 更新流水线右侧详情区 (图标 + 文本)
function updatePipeDetail(stepKey) {
  const icoEl = $('#pipe-detail-ico');
  const txtEl = $('#pipe-detail-text');
  if (!icoEl || !txtEl) return;
  const step = pipeline.steps.find(s => s.key === stepKey);
  icoEl.innerHTML = step ? esc(step.icon) : '';
  const fn = STEP_DETAILS[stepKey];
  txtEl.textContent = fn ? fn() : (step ? step.label : '');
}

// 流水线下载进度 (汉化包/资源/气泡/插件Mod): 右侧详情下方进度条
function updatePipeDownloadProgress(data) {
  const box = $('#pipe-detail-dl');
  if (!box || !pipeline.running) return;
  box.hidden = false;
  const pct = Math.max(0, Math.min(100, Number(data.percent) || 0));
  const fill = $('#pipe-dl-fill');
  if (fill) fill.style.width = pct + '%';
  const meta = $('#pipe-dl-meta');
  if (meta) {
    meta.textContent = (data.downloaded != null && data.total != null)
      ? fmtBytes(data.downloaded) + ' / ' + fmtBytes(data.total) +
        (data.speed ? ' · ' + fmtSpeed(data.speed) : '')
      : pct.toFixed(0) + '%';
  }
}

function hidePipeDownloadProgress() {
  const box = $('#pipe-detail-dl');
  if (box) box.hidden = true;
  const fill = $('#pipe-dl-fill');
  if (fill) fill.style.width = '0%';
}

// 流水线中按下载任务名, 把右侧大图标换成对应 Mod/插件的真实图标
function setPipeDetailIconByTask(taskName) {
  const icoEl = $('#pipe-detail-ico');
  if (!icoEl || !taskName) return;
  // 已是该图标则跳过
  if (icoEl.dataset.task === taskName) return;
  let iconUrl = '';
  const find = (arr) => {
    const hit = (arr || []).find(it => it.name === taskName);
    return hit ? hit.icon_url || '' : '';
  };
  iconUrl = find(dcAddonItems) || find(dcModItems);
  icoEl.dataset.task = taskName;
  if (!iconUrl) return;   // 找不到云端图标则保留步骤默认图标
  withTimeout(api.get_icon(iconUrl, taskName), 6000, '').then(uri => {
    if (uri && icoEl.dataset.task === taskName) {
      icoEl.innerHTML = '<img src="' + uri + '" alt="">';
    }
  }).catch(() => {});
}
