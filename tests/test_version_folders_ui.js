'use strict';
// 版本管理页"文件目录"区块 (TDD RED/GREEN)
// renderVersionFolders: 按载荷顺序渲染行(识别→中文名, 未识别→原名), 点击打开对应文件夹
// loadVersionFolders/openVersionFolder: 调 Python 槽, 携带 selectedVersion
const fs = require('fs');
const path = require('path');
const { extractFunc, html } = require('./extract_func');

const MAIN = fs.readFileSync(path.join(__dirname, '..', 'main.py'), 'utf8');

let pass = 0, fail = 0;
const failures = [];
function check(cond, msg) {
  if (cond) pass++;
  else { fail++; failures.push(msg); console.log('  FAIL: ' + msg); }
}
function section(t) { console.log('\n== ' + t + ' =='); }

// ---------------- DOM 桩 ----------------
function makeEl(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(),
    children: [],
    className: '',
    textContent: '',
    onclick: null,
    _html: ''
  };
  Object.defineProperty(el, 'innerHTML', {
    get: function () { return el._html; },
    set: function (v) { el._html = String(v); el.children.length = 0; }
  });
  el.appendChild = function (c) {
    c.parentNode = el;
    el.children.push(c);
    return c;
  };
  return el;
}

function makeDoc() {
  const byId = new Map();
  return {
    getElementById: function (id) {
      if (!byId.has(id)) byId.set(id, makeEl('div'));
      return byId.get(id);
    },
    createElement: function (t) { return makeEl(t); },
    _byId: byId
  };
}

// ---------------- 工厂 ----------------
const NAMES = ['renderVersionFolders', 'loadVersionFolders', 'openVersionFolder'];
const srcs = {};
NAMES.forEach(function (n) { srcs[n] = extractFunc(n); });

function buildApi(selectedVersion) {
  const doc = makeDoc();
  const calls = [];
  const pythonInterface = {
    getVersionFolders: function (v) { calls.push(['getVersionFolders', v]); },
    openVersionFolder: function (v, s) { calls.push(['openVersionFolder', v, s]); }
  };
  const missing = NAMES.filter(function (n) { return !srcs[n]; });
  if (missing.length) return { doc: doc, calls: calls, fns: null, missing: missing };
  const body = [
    'function escapeHtml(t){ return String(t); }',
    NAMES.map(function (n) { return srcs[n]; }).join('\n'),
    'return { renderVersionFolders: renderVersionFolders, loadVersionFolders: loadVersionFolders, openVersionFolder: openVersionFolder };'
  ].join('\n');
  const fn = new Function('document', 'pythonInterface', 'selectedVersion', body);
  return { doc: doc, calls: calls, fns: fn(doc, pythonInterface, selectedVersion), missing: [] };
}

const PAYLOAD = {
  path: 'D:/mc/versions/my-1.20.1',
  version_id: 'my-1.20.1',
  folders: [
    { name: 'mods', label: '模组文件夹', recognized: true },
    { name: 'saves', label: '世界文件夹', recognized: true },
    { name: 'JourneyMapData', label: 'JourneyMapData', recognized: false }
  ]
};

// ================= 1. 存在性 (RED: 缺函数应 FAIL 而非报错) =================
section('存在: 必需函数可从 index.html 抽取');
const probe = buildApi('v1');
check(probe.missing.length === 0,
  '缺少函数: ' + (probe.missing.join(',') || '-'));

if (probe.missing.length === 0) {
  // ================= 2. 渲染 =================
  section('渲染: 识别→中文名, 未识别→原名, 保持载荷顺序');
  {
    const api = buildApi('my-1.20.1');
    api.fns.renderVersionFolders(PAYLOAD);
    const pathEl = api.doc.getElementById('versionFoldersPath');
    const list = api.doc.getElementById('versionFoldersList');
    check(pathEl.textContent === PAYLOAD.path,
      '路径头应显示实际目录 (实际: ' + pathEl.textContent + ')');
    check(list.children.length === 3,
      '应渲染 3 行 (实际 ' + list.children.length + ')');
    check(list.children[0] && list.children[0].innerHTML.indexOf('模组文件夹') >= 0,
      '第1行应为中文名"模组文件夹"');
    check(list.children[1] && list.children[1].innerHTML.indexOf('世界文件夹') >= 0,
      '第2行应为中文名"世界文件夹"');
    check(list.children[2] && list.children[2].innerHTML.indexOf('JourneyMapData') >= 0,
      '第3行未识别应显示原名');
    check(list.children[0] && list.children[0].innerHTML.indexOf('模组') >= 0 &&
      list.children[0].className.indexOf('recognized') >= 0,
      '识别行应带 recognized 类');
    check(list.children[2] && list.children[2].className.indexOf('recognized') === -1,
      '未识别行不应带 recognized 类');
    check(list._html.indexOf('此文件夹内没有子文件夹') === -1,
      '有内容时不应显示空提示');
  }

  section('点击: 调 openVersionFolder(selectedVersion, 文件夹名)');
  {
    const api = buildApi('my-1.20.1');
    api.fns.renderVersionFolders(PAYLOAD);
    const list = api.doc.getElementById('versionFoldersList');
    list.children[0].onclick();
    list.children[2].onclick();
    check(api.calls.length === 2 &&
      api.calls[0][0] === 'openVersionFolder' && api.calls[0][1] === 'my-1.20.1' &&
      api.calls[0][2] === 'mods',
      '第1行点击应调 openVersionFolder(my-1.20.1, mods) (实际 ' +
      JSON.stringify(api.calls) + ')');
    check(api.calls[1] && api.calls[1][2] === 'JourneyMapData',
      '未识别行点击应传原名 (实际 ' + JSON.stringify(api.calls[1] || null) + ')');
  }

  section('空列表: 显示提示, 不渲染行');
  {
    const api = buildApi('my-1.20.1');
    api.fns.renderVersionFolders({ path: 'D:/mc/versions/x', folders: [] });
    const list = api.doc.getElementById('versionFoldersList');
    check(list.children.length === 0, '空列表不应有行');
    check(list._html.indexOf('此文件夹内没有子文件夹') >= 0,
      '空列表应显示"此文件夹内没有子文件夹" (实际: ' + list._html + ')');
  }

  section('刷新: loadVersionFolders 调槽并携带 selectedVersion');
  {
    const api = buildApi('my-1.20.1');
    api.fns.loadVersionFolders();
    check(api.calls.length === 1 && api.calls[0][0] === 'getVersionFolders' &&
      api.calls[0][1] === 'my-1.20.1',
      '应调 getVersionFolders(my-1.20.1) (实际 ' + JSON.stringify(api.calls) + ')');
  }
}

// ================= 3. 静态: 前后端接线 =================
section('静态: index.html 接线');
check(/id="versionFoldersList"/.test(html), '版本管理页应有 versionFoldersList 容器');
check(/id="versionFoldersPath"/.test(html), '版本管理页应有 versionFoldersPath 路径头');
check((html.match(/loadVersionFolders\(\)/g) || []).length >= 1,
  'index.html 应至少 1 处调用 loadVersionFolders()');

section('静态: main.py 槽与信号');
check(/versionFoldersLoaded\s*=\s*pyqtSignal\(str\)/.test(MAIN), '缺少 versionFoldersLoaded 信号');
check(/def getVersionFolders\(/.test(MAIN), '缺少 getVersionFolders 槽');
check(/def openVersionFolder\(/.test(MAIN), '缺少 openVersionFolder 槽');
check(/versionFoldersLoaded\.connect\(/.test(MAIN), 'versionFoldersLoaded 应已 connect');
check(/renderVersionFolders\(/.test(MAIN), '信号应回调 JS renderVersionFolders');

// ================= 汇总 =================
console.log('\n==============================');
console.log('PASS: ' + pass + '  FAIL: ' + fail);
if (fail) {
  console.log('失败项:');
  failures.forEach(function (f) { console.log('  - ' + f); });
}
process.exit(fail ? 1 : 0);
