'use strict';
// Task 6: Bridge 插件槽与信号 静态接线测试 (TDD RED/GREEN)
// Task 7: 插件页 UI (列表 + 详情 + 侧栏页签) 行为断言
const fs = require('fs');
const path = require('path');
const { extractFunc, html } = require('./extract_func');

const MAIN = path.join(__dirname, '..', 'main.py');
const py = fs.readFileSync(MAIN, 'utf8');

let pass = 0, fail = 0;
const failures = [];
function check(cond, msg) {
  if (cond) pass++;
  else { fail++; failures.push(msg); console.log('  FAIL: ' + msg); }
}
function section(t) { console.log('\n== ' + t + ' =='); }

function extractMethod(name) {
  const marker = 'def ' + name + '(';
  const start = py.indexOf(marker);
  if (start < 0) return null;
  const rest = py.slice(start + marker.length);
  const m = /\n    (?:def |@)/.exec(rest);
  return m ? py.slice(start, start + marker.length + m.index) : py.slice(start);
}

// ================= 1. 两个信号 =================
section('静态: pluginsLoaded / pluginDetailLoaded 信号');
check(/pluginsLoaded\s*=\s*pyqtSignal\(str\)/.test(py), 'main.py 应含 pluginsLoaded = pyqtSignal(str)');
check(/pluginDetailLoaded\s*=\s*pyqtSignal\(str\)/.test(py), 'main.py 应含 pluginDetailLoaded = pyqtSignal(str)');

// ================= 2. 七个槽 =================
section('静态: 7 个插件槽');
const slots = ['getPlugins', 'getPluginDetail', 'setPluginEnabled',
  'savePluginConfig', 'reloadPlugins', 'openPluginFolder', 'uninstallPlugin'];
slots.forEach(function (s) {
  check(extractMethod(s) !== null, 'main.py 应含 def ' + s);
});

// ================= 3. 启动加载 + 持有 =================
section('静态: PluginManager 持有与启动 load_all()');
check(py.indexOf('PluginManager(') >= 0, 'main.py 应实例化 PluginManager(');
check(py.indexOf('load_all()') >= 0, 'main.py 应在启动流程调用 load_all()');

// ================= 4. 信号接线 =================
section('静态: MainWindow 连接两个信号');
check(py.indexOf('pluginsLoaded.connect(') >= 0, '应有 pluginsLoaded.connect(...)');
check(py.indexOf('pluginDetailLoaded.connect(') >= 0, '应有 pluginDetailLoaded.connect(...)');

// ================= 5. getPlugins =================
section('静态: getPlugins emit pluginsLoaded');
const gp = extractMethod('getPlugins');
check(gp !== null && gp.indexOf('pluginsLoaded.emit') >= 0, 'getPlugins 应 emit pluginsLoaded');
check(gp !== null && gp.indexOf('ensure_ascii=False') >= 0, 'getPlugins 应含 ensure_ascii=False');

// ================= 6. getPluginDetail =================
section('静态: getPluginDetail emit pluginDetailLoaded');
const gpd = extractMethod('getPluginDetail');
check(gpd !== null && gpd.indexOf('pluginDetailLoaded.emit') >= 0, 'getPluginDetail 应 emit pluginDetailLoaded');
check(gpd !== null && gpd.indexOf('ensure_ascii=False') >= 0, 'getPluginDetail 应含 ensure_ascii=False');

// ================= 7. setPluginEnabled =================
section('静态: setPluginEnabled 持久化并刷新列表');
const spe = extractMethod('setPluginEnabled');
check(spe !== null && spe.indexOf('set_enabled') >= 0, 'setPluginEnabled 应调 set_enabled');
check(spe !== null && spe.indexOf('pluginsLoaded.emit') >= 0, 'setPluginEnabled 应 emit pluginsLoaded');

// ================= 8. savePluginConfig =================
section('静态: savePluginConfig 解析 JSON + 校验结果回发详情');
const spc = extractMethod('savePluginConfig');
check(spc !== null && spc.indexOf('save_config') >= 0, 'savePluginConfig 应调 save_config');
check(spc !== null && spc.indexOf('json.loads') >= 0, 'savePluginConfig 应解析 jsonCfg');
check(spc !== null && spc.indexOf('pluginDetailLoaded.emit') >= 0, 'savePluginConfig 应 emit pluginDetailLoaded');

// ================= 9. reloadPlugins =================
section('静态: reloadPlugins 重载并刷新列表');
const rp = extractMethod('reloadPlugins');
check(rp !== null && rp.indexOf('reload(') >= 0, 'reloadPlugins 应调 reload(');
check(rp !== null && rp.indexOf('pluginsLoaded.emit') >= 0, 'reloadPlugins 应 emit pluginsLoaded');

// ================= 10. openPluginFolder 防穿越 =================
section('静态: openPluginFolder 走 folder_of 校验 + QDesktopServices');
const opf = extractMethod('openPluginFolder');
check(opf !== null && opf.indexOf('folder_of') >= 0, 'openPluginFolder 应调 folder_of');
check(opf !== null && opf.indexOf('QDesktopServices') >= 0, 'openPluginFolder 应用 QDesktopServices');
check(opf !== null && opf.indexOf('emit') >= 0, 'openPluginFolder 越界/失败时应 emit 提示信号');

// ================= 11. uninstallPlugin =================
section('静态: uninstallPlugin 卸载并刷新列表');
const up = extractMethod('uninstallPlugin');
check(up !== null && up.indexOf('uninstall') >= 0, 'uninstallPlugin 应调 uninstall');
check(up !== null && up.indexOf('pluginsLoaded.emit') >= 0, 'uninstallPlugin 应 emit pluginsLoaded');

// ================= S2. 槽异常逃逸防护 =================
section('静态: S2 savePluginConfig 整体 try 内');
{
  const bodies = [];
  const tryRe = /\r?\n        try:\r?\n([\s\S]*?)\r?\n        except[^\n]*:/g;
  let tm;
  while ((tm = tryRe.exec(spc)) !== null) bodies.push(tm[1]);
  check(bodies.some(function (b) {
    return b.indexOf('save_config') >= 0 &&
      b.indexOf('self.plugins.detail') >= 0 &&
      b.indexOf('json.dumps') >= 0;
  }), 'savePluginConfig 的 save_config/detail/json.dumps 应全部在 try 内');
}

section('静态: S2 openPluginFolder 整体 try/except → errorOccurred');
check(/try:/.test(opf) && /except Exception/.test(opf) && opf.indexOf('errorOccurred.emit') >= 0,
  'openPluginFolder 应整体 try/except 并 emit errorOccurred');

section('静态: 规格16 uninstallPlugin False 分支补 errorOccurred');
check(up !== null && up.indexOf('errorOccurred.emit("卸载失败")') >= 0,
  'uninstallPlugin 失败(False) 分支应 emit 卸载失败');

// ================= M7. 启动健壮性 =================
section('静态: M7 启动 load_all 延后 + try/except');
check(/QTimer\.singleShot\(0,\s*self\._startup_load_plugins\)/.test(py),
  '启动 load_all 应经 QTimer.singleShot(0, self._startup_load_plugins) 延后');
{
  const slp = extractMethod('_startup_load_plugins');
  check(slp !== null && slp.indexOf('load_all()') >= 0 &&
    slp.indexOf('except Exception') >= 0 && slp.indexOf('logger.error') >= 0,
    '_startup_load_plugins 应 try/except 包裹 load_all 并 logger.error (不崩启动)');
}

// ================= 12. MainWindow 信号槽 → JS =================
section('静态: _on_plugins_loaded / _on_plugin_detail_loaded 调 JS 渲染');
const opl = extractMethod('_on_plugins_loaded');
check(opl !== null && opl.indexOf('renderPluginList(') >= 0, '_on_plugins_loaded 应 runJavaScript renderPluginList(');
const opd = extractMethod('_on_plugin_detail_loaded');
check(opd !== null && opd.indexOf('renderPluginDetail(') >= 0, '_on_plugin_detail_loaded 应 runJavaScript renderPluginDetail(');

// ================= Task 7 静态: 侧栏导航第 8 项 =================
section('静态: 侧栏第 8 项 data-page=plugins');
check(/<div class="nav-item[^>]*data-page="plugins">/.test(html), 'nav 应含 <div class="nav-item" data-page="plugins">');
{
  const navMatch = /<div class="nav-item[^>]*data-page="plugins">([\s\S]*?)<\/div>/.exec(html);
  check(navMatch !== null && navMatch[1].indexOf('<span class="tooltip">插件</span>') >= 0,
    'plugins 导航项 tooltip 应为 插件');
  check(navMatch !== null && /<svg[\s\S]*?<\/svg>/.test(navMatch[1]), 'plugins 导航项应含 SVG 图标');
}

section('静态: 页标题映射');
check(/'plugins':\s*'插件'/.test(html), "navigateTo titles 应含 'plugins': '插件'");

// ================= Task 7 静态: 页面结构 =================
section('静态: pluginsPage 两个视图');
check(/id="pluginsPage"/.test(html), 'index.html 应含 id="pluginsPage"');
check(/class="plugin-list-view/.test(html), '应含 .plugin-list-view 列表视图');
check(/class="plugin-detail-view/.test(html), '应含 .plugin-detail-view 详情视图');
check(/id="pluginList"/.test(html), '应含 id="pluginList" 列表容器');
check(/id="pluginListView"/.test(html), '应含 id="pluginListView" 列表视图容器');
check(/id="pluginDetailView"/.test(html), '应含 id="pluginDetailView" 详情视图容器');
check(/id="pluginContent"/.test(html), '应含 id="pluginContent" 自定义内容区');
check(/放入 plugins\/ 文件夹即可识别/.test(html), '应含列表空态文案 放入 plugins/ 文件夹即可识别');
check(/启用插件后可用/.test(html), '应含禁用占位文案 启用插件后可用');

section('静态: CSS 类');
['plugin-card', 'plugin-badge', 'plugin-settings', 'plugin-content-box', 'plugin-list-view', 'plugin-detail-view']
  .forEach(function (cls) {
    check(new RegExp('\\.' + cls + '\\s*\\{').test(html), 'CSS 应含 .' + cls + ' 样式');
  });
check(/\.plugin-badge\.status-error\s*\{/.test(html) && /\.plugin-badge\.status-disabled\s*\{/.test(html),
  'plugin-badge 应有 status-error / status-disabled 三色变体');
check(/\.plugin-card-name\s*\{[^}]*min-width/.test(html),
  'M8: .plugin-card-name 应含 min-width (flex 溢出防护)');

section('静态: 新 JS 函数存在且可抽取');
['escapeAttr', 'pluginBadgeMeta', 'pluginBadgeHtml', 'pluginCardHtml', 'renderPluginList', 'openPluginDetail', 'backToPluginList',
  'renderPluginDetail', 'pluginSettingInputHtml', 'pluginFieldInput',
  'savePluginForm', 'togglePluginEnabled', 'reloadPlugin', 'uninstallPlugin',
  'confirmUninstallPlugin', 'openPluginFolder', 'setPluginView']
  .forEach(function (n) {
    check(extractFunc(n) !== null, 'index.html 应含 function ' + n);
  });

section('静态: navigateTo plugins 分支');
{
  const navSrc = extractFunc('navigateTo');
  check(navSrc !== null && navSrc.indexOf("page === 'plugins'") >= 0, "navigateTo 应含 page === 'plugins' 分支");
  check(navSrc !== null && navSrc.indexOf('getPlugins') >= 0, 'navigateTo 的 plugins 分支应调 getPlugins');
  check(navSrc !== null && navSrc.indexOf("setPluginView('list')") >= 0,
    "规格16③: navigateTo('plugins') 应重置子视图回列表 setPluginView('list')");
}

section('静态: 7 槽 pythonInterface 调用');
['getPlugins', 'getPluginDetail', 'setPluginEnabled', 'savePluginConfig',
  'reloadPlugins', 'openPluginFolder', 'uninstallPlugin']
  .forEach(function (s) {
    check(html.indexOf('pythonInterface.' + s) >= 0, 'index.html 应调 pythonInterface.' + s);
  });

section('静态: 状态缓存声明');
check(/(?:let|var)\s+pluginListCache\s*=\s*\[\s*\]/.test(html), '应声明 pluginListCache = []');
check(/(?:let|var)\s+currentDetailId\s*=/.test(html), '应声明 currentDetailId');
check(/(?:let|var)\s+pluginFormValues\s*=/.test(html), '应声明 pluginFormValues');

// ================= DOM 桩 + 工厂 =================
function makeClassList() {
  const s = new Set();
  return {
    add: function () { for (let i = 0; i < arguments.length; i++) s.add(arguments[i]); },
    remove: function () { for (let i = 0; i < arguments.length; i++) s.delete(arguments[i]); },
    toggle: function (c, force) {
      const want = force === undefined ? !s.has(c) : !!force;
      if (want) s.add(c); else s.delete(c);
      return want;
    },
    contains: function (c) { return s.has(c); }
  };
}
function makeEl(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(),
    children: [],
    style: {},
    value: '',
    textContent: '',
    className: '',
    checked: false,
    type: '',
    dataset: {},
    _html: ''
  };
  el.classList = makeClassList();
  Object.defineProperty(el, 'innerHTML', {
    get: function () { return el._html; },
    set: function (v) { el._html = String(v); el.children.length = 0; }
  });
  el.setAttribute = function (k, v) { el.dataset[k] = v; };
  el.getAttribute = function (k) { return el.dataset[k] === undefined ? null : el.dataset[k]; };
  el.appendChild = function (c) { c.parentNode = el; el.children.push(c); return c; };
  el.querySelector = function () { return null; };
  el.querySelectorAll = function () { return []; };
  return el;
}
function makeDoc(opts) {
  opts = opts || {};
  const byId = new Map();
  const missing = opts.missing || [];
  return {
    getElementById: function (id) {
      if (missing.indexOf(id) >= 0) return null;
      if (!byId.has(id)) byId.set(id, makeEl('div'));
      return byId.get(id);
    },
    createElement: function (t) { return makeEl(t); },
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    _byId: byId
  };
}

const PLUGIN_CACHE_DECL = (/(?:let|var)\s+pluginListCache\s*=\s*\[\s*\]/.exec(html) || [])[0] || 'var pluginListCache = [];';
const PLUGIN_DETAIL_DECL = (/(?:let|var)\s+currentDetailId\s*=[^;\n]*/.exec(html) || [])[0] || 'var currentDetailId = null;';
const PLUGIN_FORM_DECL = (/(?:let|var)\s+pluginFormValues\s*=\s*\{[^}]*\}/.exec(html) || [])[0] || 'var pluginFormValues = {};';

// 被测函数的辅助依赖候选集: 仅当被注入源码真实引用 dep( 时才要求存在;
// 真实缺失 → 推入 api.missing 早退 (M5 诚实性, 不静默跳过导致调用期裸崩)
const PLUGIN_DEPS = ['escapeAttr', 'pluginBadgeMeta', 'pluginBadgeHtml', 'setPluginView', 'backToPluginList'];

function buildPluginApi(opts) {
  opts = opts || {};
  const want = (opts.fns || []).slice();
  const srcMap = {};
  const missing = [];
  const forceDeps = opts.forceDeps || [];
  want.forEach(function (n) {
    const s = extractFunc(n);
    if (s) srcMap[n] = s;
    else missing.push(n);
  });
  if (!missing.length) {
    let grew = true;
    while (grew) {
      grew = false;
      const all = Object.keys(srcMap).map(function (k) { return srcMap[k]; }).join('\n');
      PLUGIN_DEPS.concat(forceDeps).forEach(function (dep) {
        if (srcMap[dep] !== undefined || missing.indexOf(dep) >= 0) return;
        const referenced = new RegExp('\\b' + dep + '\\s*\\(').test(all);
        if (!referenced && forceDeps.indexOf(dep) < 0) return;
        const s = extractFunc(dep);
        if (s) { srcMap[dep] = s; grew = true; } else missing.push(dep);
      });
    }
  }
  const srcs = Object.keys(srcMap).map(function (k) { return srcMap[k]; });
  const doc = opts.doc || makeDoc({ missing: opts.missingIds || [] });
  const calls = {
    getPlugins: 0, getPluginDetail: [], setPluginEnabled: [], savePluginConfig: [],
    reloadPlugins: 0, openPluginFolder: [], uninstallPlugin: [], toast: [],
    nav: [], confirms: []
  };
  const confirmAnswer = opts.confirm === undefined ? true : opts.confirm;
  const pythonInterface = {
    getPlugins: function () { calls.getPlugins += 1; return '[]'; },
    getPluginDetail: function (id) { calls.getPluginDetail.push(id); },
    setPluginEnabled: function (id, en) { calls.setPluginEnabled.push([id, en]); },
    savePluginConfig: function (id, cfg) { calls.savePluginConfig.push([id, cfg]); },
    reloadPlugins: function () { calls.reloadPlugins += 1; },
    openPluginFolder: function (id) { calls.openPluginFolder.push(id); },
    uninstallPlugin: function (id) { calls.uninstallPlugin.push(id); }
  };
  const showToast = function (m, t) { calls.toast.push([m, t]); };
  const navigateTo = function (p) { calls.nav.push(p); };
  const confirmFn = function (msg) { calls.confirms.push(msg); return confirmAnswer; };
  if (missing.length) return { missing: missing, calls: calls, doc: doc };

  const retLines = ['return {'];
  Object.keys(srcMap).forEach(function (n) { retLines.push('  ' + n + ': ' + n + ','); });
  retLines.push('  get pluginListCache(){ return pluginListCache; },');
  retLines.push('  get currentDetailId(){ return currentDetailId; },');
  retLines.push('  get pluginFormValues(){ return pluginFormValues; },');
  retLines.push('  calls: calls');
  retLines.push('};');
  const body = [
    PLUGIN_CACHE_DECL,
    PLUGIN_DETAIL_DECL,
    PLUGIN_FORM_DECL,
    'function escapeHtml(t){ return String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }',
    'function escapeAttr(t){ return String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/\'/g, "&#39;"); }',
    srcs.join('\n'),
    retLines.join('\n')
  ].join('\n');
  let fns;
  try {
    const factory = new Function('document', 'pythonInterface', 'confirm', 'showToast', 'navigateTo', 'calls', body);
    fns = factory(doc, pythonInterface, confirmFn, showToast, navigateTo, calls);
  } catch (e) {
    return { missing: ['<拼装失败: ' + e.message + '>'], calls: calls, doc: doc };
  }
  return { missing: [], fns: fns, calls: calls, doc: doc };
}

const PLUGINS = [
  { id: 'hello-sample', name: '示例插件', version: '1.0.0', author: 'DevLauncher', icon: '👋', description: '演示插件能力', status: 'enabled', errorMsg: '', hasSettings: true, hasContent: true },
  { id: 'other', name: '另一个', version: '0.2.0', author: 'Someone', icon: '🔧', description: '其他插件', status: 'disabled', errorMsg: '', hasSettings: false, hasContent: false },
  { id: 'broken', name: '坏插件', version: '0.1.0', author: 'X', icon: '💥', description: '出错了', status: 'error', errorMsg: 'boom failed', hasSettings: false, hasContent: false }
];

// ================= 行为: renderPluginList =================
section('行为: renderPluginList 渲染 3 张卡片');
{
  const api = buildPluginApi({ fns: ['pluginCardHtml', 'renderPluginList'] });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.renderPluginList(PLUGINS);
    const out = api.doc.getElementById('pluginList').innerHTML;
    check((out.match(/<div class="plugin-card[" ]/g) || []).length === 3,
      '应渲染 3 张卡片 (实际 ' + (out.match(/<div class="plugin-card[" ]/g) || []).length + ')');
    check(out.indexOf('示例插件') >= 0 && out.indexOf('坏插件') >= 0, '卡片应含插件名称');
    check(out.indexOf('v1.0.0 · DevLauncher') >= 0, '卡片应含 v版本 · 作者 元信息');
    check(out.indexOf('status-enabled') >= 0 && out.indexOf('status-disabled') >= 0 && out.indexOf('status-error') >= 0,
      '3 张卡片应分别带 启用/禁用/错误 状态 class');
    check(out.indexOf('启用') >= 0 && out.indexOf('禁用') >= 0 && out.indexOf('错误') >= 0,
      '应含三色徽章文案 启用/禁用/错误');
    check(out.indexOf("openPluginDetail('hello-sample')") >= 0, '整卡点击应绑定 openPluginDetail(id)');
    check(out.indexOf('boom failed') >= 0, 'error 卡片应显示 errorMsg');
    check(out.indexOf('hello-sample') >= 0 && out.indexOf('broken') >= 0, '卡片应携带 data-id');
    const evil = api.fns.pluginCardHtml({ id: 'x', name: '<img src=x onerror=alert(1)>', version: '1', author: 'A', description: 'd', status: 'enabled' });
    check(evil.indexOf('&lt;img') >= 0 && evil.indexOf('<img') < 0, '插件名应 HTML 转义 (XSS)');
  }
}

section('行为: renderPluginList 空态');
{
  const api = buildPluginApi({ fns: ['pluginCardHtml', 'renderPluginList'] });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.renderPluginList([]);
    const out = api.doc.getElementById('pluginList').innerHTML;
    check(out.indexOf('放入 plugins/ 文件夹即可识别') >= 0, '空数组应显示空态文案');
    check((out.match(/<div class="plugin-card[" ]/g) || []).length === 0, '空数组不应渲染卡片');
    api.fns.renderPluginList(null);
    check(api.doc.getElementById('pluginList').innerHTML.indexOf('放入 plugins/') >= 0, 'null 载荷也应显示空态');
  }
}

// ================= 行为: 打开/返回详情 =================
section('行为: openPluginDetail → getPluginDetail + 视图切换');
{
  const api = buildPluginApi({ fns: ['setPluginView', 'openPluginDetail', 'backToPluginList'] });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.openPluginDetail('hello-sample');
    check(api.calls.getPluginDetail.length === 1 && api.calls.getPluginDetail[0] === 'hello-sample',
      '应调 pythonInterface.getPluginDetail("hello-sample")');
    check(api.fns.currentDetailId === 'hello-sample', 'currentDetailId 应记录当前详情 id');
    check(api.doc.getElementById('pluginDetailView').classList.contains('active') === true,
      '详情视图应激活 active');
    check(api.doc.getElementById('pluginListView').classList.contains('active') === false,
      '列表视图应退出 active');
    api.fns.openPluginDetail('');
    check(api.calls.getPluginDetail.length === 1, '空 id 不应发起请求');
    api.fns.backToPluginList();
    check(api.calls.getPlugins >= 1, '返回列表应调 getPlugins 刷新');
    check(api.doc.getElementById('pluginListView').classList.contains('active') === true,
      '返回后列表视图应重新激活');
    check(api.doc.getElementById('pluginDetailView').classList.contains('active') === false,
      '返回后详情视图应退出');
  }
}

// ================= 行为: renderPluginDetail =================
const DETAIL = {
  id: 'hello-sample', name: '示例插件', version: '1.0.0', author: 'DevLauncher', icon: '👋',
  description: '演示', status: 'enabled', errorMsg: '', hasSettings: true,
  settings: [
    { key: 'greeting', label: '问候语', type: 'text', default: '你好', value: '你好' },
    { key: 'enabled_anim', label: '显示动画', type: 'toggle', default: true, value: false },
    { key: 'max_items', label: '最大条目', type: 'number', default: 5, value: 5 }
  ],
  contentHtml: "<div class='plugin-content'>你好</div>"
};

section('行为: renderPluginDetail 基本信息 + contentHtml 注入');
{
  const api = buildPluginApi({
    fns: ['setPluginView', 'pluginSettingInputHtml', 'pluginFieldInput', 'renderPluginDetail']
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.renderPluginDetail(DETAIL);
    const nameEl = api.doc.getElementById('pluginDetailName');
    check(nameEl.textContent === '示例插件', '详情标题应为 示例插件 (实际 ' + nameEl.textContent + ')');
    const metaEl = api.doc.getElementById('pluginDetailMeta');
    check(metaEl.textContent.indexOf('v1.0.0') >= 0 && metaEl.textContent.indexOf('DevLauncher') >= 0,
      '详情元信息应含 v1.0.0 与作者 (实际 ' + metaEl.textContent + ')');
    const badge = api.doc.getElementById('pluginDetailBadge');
    check(badge.textContent === '启用', '详情徽章文案应为 启用 (实际 ' + badge.textContent + ')');
    check(badge.className.indexOf('status-enabled') >= 0, '详情徽章 class 应含 status-enabled');
    const info = api.doc.getElementById('pluginDetailInfo').innerHTML;
    check(info.indexOf('hello-sample') >= 0, '信息 dl 应含 id');
    check(info.indexOf('1.0.0') >= 0 && info.indexOf('DevLauncher') >= 0, '信息 dl 应含 版本/作者');
    const content = api.doc.getElementById('pluginContent');
    check(content.innerHTML.indexOf("class='plugin-content'") >= 0, 'pluginContent 应注入 contentHtml');
    check(api.doc.getElementById('pluginSettings').style.display !== 'none', '有 settings 时设置区应可见');
    check(api.fns.currentDetailId === 'hello-sample', 'renderPluginDetail 应更新 currentDetailId');
  }
}

section('行为: renderPluginDetail 三类型设置表单');
{
  const api = buildPluginApi({
    fns: ['setPluginView', 'pluginSettingInputHtml', 'pluginFieldInput', 'renderPluginDetail']
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.renderPluginDetail(DETAIL);
    const form = api.doc.getElementById('pluginSettingsForm').innerHTML;
    check(/<input type="text"[^>]*data-key="greeting"/.test(form), 'text 应渲染为 <input type="text" data-key="greeting">');
    check(/<input type="checkbox"[^>]*data-key="enabled_anim"/.test(form), 'toggle 应渲染为 <input type="checkbox" data-key="enabled_anim">');
    check(/<input type="number"[^>]*data-key="max_items"/.test(form), 'number 应渲染为 <input type="number" data-key="max_items">');
    check(/value="你好"/.test(form), 'text 输入应带当前 value');
    check(form.indexOf('checked') < 0, 'value=false 的 toggle 不应带 checked');
    check(api.fns.pluginFormValues.greeting === '你好' && api.fns.pluginFormValues.max_items === 5,
      '渲染应同步初始化 pluginFormValues');
  }
}

section('行为: renderPluginDetail 禁用/错误态占位');
{
  const api = buildPluginApi({
    fns: ['setPluginView', 'pluginSettingInputHtml', 'pluginFieldInput', 'renderPluginDetail']
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    const disabled = Object.assign({}, DETAIL, { status: 'disabled', contentHtml: '' });
    api.fns.renderPluginDetail(disabled);
    const content = api.doc.getElementById('pluginContent');
    check(content.innerHTML.indexOf('启用插件后可用') >= 0, '禁用态应显示 启用插件后可用 占位');
    check(content.innerHTML.indexOf('plugin-content') < 0, '禁用态不应注入 contentHtml');
    const badge = api.doc.getElementById('pluginDetailBadge');
    check(badge.textContent === '禁用' && badge.className.indexOf('status-disabled') >= 0,
      '禁用态徽章应为 禁用/status-disabled (实际 ' + badge.textContent + '/' + badge.className + ')');
    check(api.doc.getElementById('pluginDetailActions').innerHTML.indexOf('启用') >= 0,
      '禁用态操作行应出现 启用 按钮');

    const broken = Object.assign({}, DETAIL, { status: 'error', errorMsg: 'boom failed', contentHtml: '' });
    api.fns.renderPluginDetail(broken);
    check(api.doc.getElementById('pluginDetailBadge').textContent === '错误', '错误态徽章应为 错误');
    const errEl = api.doc.getElementById('pluginDetailError');
    check(errEl.style.display !== 'none' && errEl.textContent.indexOf('boom failed') >= 0,
      '错误态应显示 errorMsg 提示条');
    check(api.doc.getElementById('pluginDetailActions').innerHTML.indexOf('重新加载') >= 0,
      '操作行应含 重新加载 按钮');
  }
}

section('行为: savePluginForm → savePluginConfig(id, json)');
{
  const api = buildPluginApi({
    fns: ['setPluginView', 'pluginSettingInputHtml', 'pluginFieldInput', 'renderPluginDetail', 'savePluginForm']
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.renderPluginDetail(DETAIL);
    api.fns.pluginFieldInput('greeting', { type: 'text', value: 'Hi' });
    api.fns.pluginFieldInput('enabled_anim', { type: 'checkbox', checked: true });
    api.fns.pluginFieldInput('max_items', { type: 'number', value: '9' });
    api.fns.savePluginForm();
    check(api.calls.savePluginConfig.length === 1, '应调 pythonInterface.savePluginConfig');
    const [id, cfg] = api.calls.savePluginConfig[0];
    check(id === 'hello-sample', 'savePluginConfig 首参应为插件 id (实际 ' + id + ')');
    const parsed = JSON.parse(cfg);
    check(parsed.greeting === 'Hi', '配置 JSON 应含 greeting=Hi (实际 ' + JSON.stringify(parsed) + ')');
    check(parsed.enabled_anim === true && parsed.max_items === 9,
      'checkbox → true, number → 9 (实际 ' + JSON.stringify(parsed) + ')');
  }
}

section('行为: 启停/重载/卸载/打开文件夹 接线');
{
  const api = buildPluginApi({
    fns: ['togglePluginEnabled', 'reloadPlugin', 'confirmUninstallPlugin', 'uninstallPlugin', 'openPluginFolder']
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.togglePluginEnabled('hello-sample', false);
    check(api.calls.setPluginEnabled.length === 1 &&
      api.calls.setPluginEnabled[0][0] === 'hello-sample' && api.calls.setPluginEnabled[0][1] === false,
      'togglePluginEnabled 应调 setPluginEnabled(id, false)');
    api.fns.reloadPlugin();
    check(api.calls.reloadPlugins >= 1, 'reloadPlugin 应调 reloadPlugins');
    api.fns.confirmUninstallPlugin('hello-sample');
    check(api.calls.uninstallPlugin.length === 1 && api.calls.uninstallPlugin[0] === 'hello-sample',
      '确认后应调 uninstallPlugin(id)');
    check(api.calls.confirms.length === 1, '卸载应弹 confirm 二次确认');
    api.fns.openPluginFolder('hello-sample');
    check(api.calls.openPluginFolder.length === 1 && api.calls.openPluginFolder[0] === 'hello-sample',
      '应调 openPluginFolder(id)');
  }
}

section('行为: 卸载 confirm 取消不执行');
{
  const api = buildPluginApi({
    fns: ['confirmUninstallPlugin', 'uninstallPlugin'], confirm: false
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.confirmUninstallPlugin('hello-sample');
    check(api.calls.uninstallPlugin.length === 0, '取消确认不应执行卸载');
    check(api.calls.confirms.length === 1, '应弹过 confirm');
  }
}

section('行为: 容器缺失时 renderPluginList 不抛错 (M2 同款防御)');
{
  const api = buildPluginApi({
    fns: ['pluginCardHtml', 'renderPluginList'], missingIds: ['pluginList']
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    let threw = false;
    try { api.fns.renderPluginList(PLUGINS); } catch (e) { threw = true; }
    check(!threw, '容器缺失不应抛出异常');
    check(api.fns.pluginListCache.length === 3, '容器缺失时缓存仍应同步为 3 条');
  }
}

// ================= 合并修复轮: 行为断言 =================

section('行为: S1 属性上下文引号转义 (value/title) + key 白名单渲染');
{
  const api = buildPluginApi({
    fns: ['setPluginView', 'pluginSettingInputHtml', 'pluginFieldInput', 'renderPluginDetail', 'pluginCardHtml']
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    const d = Object.assign({}, DETAIL, {
      settings: [{ key: 'greeting', label: '问候语', type: 'text', default: '', value: 'a" b\'' }]
    });
    api.fns.renderPluginDetail(d);
    const form = api.doc.getElementById('pluginSettingsForm').innerHTML;
    check(form.indexOf('value="a&quot; b&#39;"') >= 0,
      'text value 应经 escapeAttr 渲染为 value="a&quot; b&#39;"');
    check(form.indexOf('value="a" b\'"') < 0, '不得出现未转义的 value="a" b\'"');
    const card = api.fns.pluginCardHtml({
      id: 'x1', name: 'N', version: '1', author: 'A', description: 'd',
      status: 'error', errorMsg: 'a" b\''
    });
    check(card.indexOf('title="a&quot; b&#39;"') >= 0, 'title 属性应经 escapeAttr 转义');
    check(card.indexOf('title="a" b\'"') < 0, 'title 不得出现未转义引号');
    const d2 = Object.assign({}, DETAIL, {
      settings: [
        { key: 'bad"key', label: '坏', type: 'text', value: 'leak' },
        { key: 'good_key', label: '好', type: 'text', value: 'ok' }
      ]
    });
    api.fns.renderPluginDetail(d2);
    const form2 = api.doc.getElementById('pluginSettingsForm').innerHTML;
    check(form2.indexOf('data-key="good_key"') >= 0, '白名单内 key 应正常渲染');
    check(form2.indexOf('leak') < 0 && form2.indexOf('bad"key') < 0,
      '不合白名单的 key 应被过滤, 不进渲染');
    check(api.fns.pluginFormValues['bad"key'] === undefined,
      '不合白名单的 key 不应写入 pluginFormValues');
  }
}

section('行为: 规格15 详情信息 dl 含「目录」');
{
  const api = buildPluginApi({
    fns: ['setPluginView', 'pluginSettingInputHtml', 'pluginFieldInput', 'renderPluginDetail']
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    const d = Object.assign({}, DETAIL, { dir: 'D:\\plugins\\hello-sample' });
    api.fns.renderPluginDetail(d);
    const info = api.doc.getElementById('pluginDetailInfo').innerHTML;
    check(info.indexOf('<dt>目录</dt>') >= 0, '信息 dl 应含 <dt>目录</dt>');
    check(info.indexOf('title="D:\\plugins\\hello-sample"') >= 0,
      '目录应以 title 悬停显示全路径');
    check(info.indexOf('hello-sample') >= 0, '目录应缩略显示末段');
  }
}

section('行为: 规格16① 卸载成功回列表 + 清空 currentDetailId');
{
  const api = buildPluginApi({
    fns: ['setPluginView', 'pluginSettingInputHtml', 'pluginFieldInput',
      'renderPluginDetail', 'uninstallPlugin']
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.renderPluginDetail(DETAIL);
    check(api.fns.currentDetailId === 'hello-sample', '前置: 应停在详情视图');
    api.fns.uninstallPlugin('hello-sample');
    check(api.calls.uninstallPlugin.length === 1 && api.calls.uninstallPlugin[0] === 'hello-sample',
      '应调 pythonInterface.uninstallPlugin(id)');
    check(api.fns.currentDetailId === null, '卸载后 currentDetailId 应清空');
    check(api.doc.getElementById('pluginListView').classList.contains('active') === true,
      '卸载后应回到列表视图');
    check(api.doc.getElementById('pluginDetailView').classList.contains('active') === false,
      '卸载后详情视图应退出');
    check(api.calls.getPlugins >= 1, '卸载后应刷新列表 (getPlugins)');
  }
}

section('行为: 规格16② 列表不含 currentDetailId 时自动回列表');
{
  const api = buildPluginApi({
    fns: ['setPluginView', 'pluginSettingInputHtml', 'pluginFieldInput',
      'renderPluginDetail', 'pluginCardHtml', 'renderPluginList']
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.renderPluginDetail(DETAIL);
    check(api.fns.currentDetailId === 'hello-sample', '前置: 应停在详情视图');
    api.fns.renderPluginList([{ id: 'other', name: '其他', status: 'enabled' }]);
    check(api.fns.currentDetailId === null,
      'pluginsLoaded 列表不含当前详情 id 时应清空 currentDetailId');
    check(api.doc.getElementById('pluginListView').classList.contains('active') === true,
      '应自动切回列表视图');
    check(api.doc.getElementById('pluginDetailView').classList.contains('active') === false,
      '详情视图应退出');
  }
}

section('行为: M1 同 id 重渲染保留未保存表单 (切 id 才清空)');
{
  const api = buildPluginApi({
    fns: ['setPluginView', 'pluginSettingInputHtml', 'pluginFieldInput', 'renderPluginDetail']
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.renderPluginDetail(DETAIL);
    api.fns.pluginFieldInput('greeting', { type: 'text', value: '自定' });
    api.fns.renderPluginDetail(DETAIL);
    check(api.fns.pluginFormValues.greeting === '自定',
      '同 id 重渲染应保留未保存输入 (实际 ' + api.fns.pluginFormValues.greeting + ')');
    const form = api.doc.getElementById('pluginSettingsForm').innerHTML;
    check(form.indexOf('value="自定"') >= 0, '输入框应回填未保存值 自定');
    const other = Object.assign({}, DETAIL, { id: 'other-plugin' });
    api.fns.renderPluginDetail(other);
    check(api.fns.pluginFormValues.greeting === '你好',
      '切换到不同 id 应清空未保存输入, 回到 detail 值');
  }
}

section('行为: I-2 跨插件表单残留 (A 的未保存输入不写进 B)');
{
  const api = buildPluginApi({
    fns: ['setPluginView', 'pluginSettingInputHtml', 'pluginFieldInput',
      'renderPluginDetail', 'openPluginDetail', 'backToPluginList']
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    const A = Object.assign({}, DETAIL, { id: 'plugin-a' });
    const B = Object.assign({}, DETAIL, { id: 'plugin-b' });
    api.fns.openPluginDetail('plugin-a');
    api.fns.renderPluginDetail(A);
    api.fns.pluginFieldInput('greeting', { type: 'text', value: 'X' });
    check(api.fns.pluginFormValues.greeting === 'X', '前置: 模拟 A 的未保存输入 X');
    api.fns.backToPluginList();
    api.fns.openPluginDetail('plugin-b');
    api.fns.renderPluginDetail(B);
    check(api.fns.pluginFormValues.greeting === '你好',
      'B 的表单状态应回到 B 的值 (实际 ' + api.fns.pluginFormValues.greeting + ')');
    const form = api.doc.getElementById('pluginSettingsForm').innerHTML;
    check(form.indexOf('value="你好"') >= 0, 'B 的输入框应回填 B 的值 你好');
    check(form.indexOf('value="X"') < 0, '不得把 A 的残留值 X 写进 B 的表单');
  }
}

section('行为: M2 详情早退不滞留 (空 id 回列表 + 提示)');
{
  const api = buildPluginApi({
    fns: ['setPluginView', 'pluginSettingInputHtml', 'pluginFieldInput', 'renderPluginDetail']
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.renderPluginDetail(DETAIL);
    api.fns.renderPluginDetail({ id: '', name: '' });
    check(api.calls.getPlugins >= 1, '空 detail 应回列表刷新 (getPlugins)');
    check(api.calls.toast.length > 0 && api.calls.toast[0][0] === '插件不存在',
      '应提示 插件不存在 (实际 ' + JSON.stringify(api.calls.toast) + ')');
    check(api.fns.currentDetailId === null, 'currentDetailId 应清空');
    check(api.doc.getElementById('pluginListView').classList.contains('active') === true,
      '应回到列表视图');
  }
}

section('行为: M4① toggle 后 getPluginDetail 计数 +1');
{
  const api = buildPluginApi({ fns: ['togglePluginEnabled'] });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.togglePluginEnabled('hello-sample', true);
    check(api.calls.getPluginDetail.length === 1,
      'toggle 后应调 getPluginDetail 刷新详情 (实际 ' + api.calls.getPluginDetail.length + ')');
  }
}

section('行为: M4② savePluginForm 成功回包 → toast');
{
  const api = buildPluginApi({
    fns: ['setPluginView', 'pluginSettingInputHtml', 'pluginFieldInput', 'renderPluginDetail']
  });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.renderPluginDetail(Object.assign({}, DETAIL, { success: true }));
    check(api.calls.toast.length === 1 && api.calls.toast[0][0] === '设置已保存',
      'success:true 回包应 toast 设置已保存 (实际 ' + JSON.stringify(api.calls.toast) + ')');
  }
}

section('M5: 缺失依赖推入 api.missing 不裸崩');
{
  const api = buildPluginApi({
    fns: ['pluginCardHtml', 'renderPluginList'], forceDeps: ['fakeMissingDep999']
  });
  check(api.missing.indexOf('fakeMissingDep999') >= 0,
    '缺失依赖应推入 api.missing (实际 ' + JSON.stringify(api.missing) + ')');
  check(api.fns === undefined, '依赖缺失时应早退返回 missing, 不进入可调用状态');
}

// ================= 汇总 =================
console.log('\n==============================');
console.log('PASS: ' + pass + '  FAIL: ' + fail);
if (fail) {
  console.log('失败项:');
  failures.forEach(function (f) { console.log('  - ' + f); });
}
process.exit(fail ? 1 : 0);