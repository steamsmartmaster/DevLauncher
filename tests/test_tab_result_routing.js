'use strict';
// 页签切换期间到达的搜索/热门结果路由测试 (TDD RED/GREEN)
// BUG: displaySearchResults 按"到达时的活动页签"路由 → 请求页签的占位符永不消失,
//      内容写进别的页签容器 (用户现象: 模组一直显示"正在从Modrinth加载模组列表...")
// FIX: Python 载荷携带 tab=content_type, JS 按 results.tab 路由, 无 tab 时回退活动页签
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
    _html: ''
  };
  Object.defineProperty(el, 'innerHTML', {
    get: function () { return el._html; },
    set: function (v) { el._html = String(v); el.children.length = 0; }
  });
  el.appendChild = function (c) {
    if (!c) return c;
    if (c._fragment) {
      c.children.forEach(function (x) { x.parentNode = el; el.children.push(x); });
      c.children.length = 0;
      return c;
    }
    c.parentNode = el;
    el.children.push(c);
    return c;
  };
  return el;
}

// activeTab: 被测代码读取 .download-tab.active; 每个场景显式指定活动页签
function makeDoc(activeTabType) {
  const byId = new Map();
  return {
    getElementById: function (id) {
      if (!byId.has(id)) byId.set(id, makeEl('div'));
      return byId.get(id);
    },
    createElement: function (t) { return makeEl(t); },
    createDocumentFragment: function () { const f = makeEl('#fragment'); f._fragment = true; return f; },
    querySelector: function (sel) {
      if (sel === '.download-tab.active') return { dataset: { dlTab: activeTabType } };
      return null;
    },
    querySelectorAll: function () { return []; },
    _byId: byId
  };
}

// ---------------- 工厂 ----------------
const src = extractFunc('displaySearchResults');
function buildApi(activeTabType) {
  if (!src) throw new Error('index.html 缺少 displaySearchResults');
  const body = [
    "function escapeHtml(t){ return String(t); }",
    'function formatNumber(n){ return String(n); }',
    src,
    'return displaySearchResults;'
  ].join('\n');
  const doc = makeDoc(activeTabType);
  const fn = new Function('document', body);
  return { display: fn(doc), doc: doc };
}

const HIT = {
  id: 'cool-mod', title: 'Cool Mod', description: 'd', downloads: 42,
  icon_url: '', author: 'a', loaders: [], project_type: 'mod', source: 'modrinth'
};
const PLACEHOLDER_MODS = '正在从Modrinth加载模组列表...';
const PLACEHOLDER_MODPACKS = '正在从Modrinth加载整合包列表...';

function seed(api, id, placeholder) {
  const c = api.doc.getElementById(id);
  c.innerHTML = placeholder;
  return c;
}

// ================= 1. 请求页签路由 (核心 BUG) =================
section('路由: 结果应写回请求页签 (活动页签是整合包)');
{
  const api = buildApi('modpacks'); // 到达时用户已切到 modpacks
  const modsC = seed(api, 'modsResults', PLACEHOLDER_MODS);
  const packC = seed(api, 'modpacksResults', PLACEHOLDER_MODPACKS);
  api.display({ tab: 'mods', hits: [HIT], isTrending: true, source: 'modrinth' });
  check(modsC.children.length === 1,
    'mods 应收到结果 (实际 children=' + modsC.children.length + ')');
  check(modsC.children.length > 0 && modsC.children[0].innerHTML.indexOf('Cool Mod') >= 0,
    'modsResults 卡片应含标题');
  check(modsC.innerHTML.indexOf('正在从Modrinth加载') === -1,
    'modsResults 占位符应被替换');
  check(packC.children.length === 0 && packC.innerHTML === PLACEHOLDER_MODPACKS,
    'modpacksResults 不应被别的页签结果污染 (实际: ' +
    (packC.children.length ? '被写入' : packC.innerHTML) + ')');
}

section('路由: 空结果也按请求页签显示 (活动页签是整合包)');
{
  const api = buildApi('modpacks');
  const modsC = seed(api, 'modsResults', PLACEHOLDER_MODS);
  const packC = seed(api, 'modpacksResults', PLACEHOLDER_MODPACKS);
  api.display({ tab: 'mods', hits: [], isTrending: true, source: 'modrinth' });
  check(modsC.innerHTML.indexOf('没有找到结果') >= 0,
    'modsResults 空结果应显示"没有找到结果" (实际: ' + modsC.innerHTML + ')');
  check(packC.children.length === 0 && packC.innerHTML === PLACEHOLDER_MODPACKS,
    'modpacksResults 空结果场景也不应被污染');
}

section('回退: 无 tab 字段时按活动页签 (向后兼容)');
{
  const api = buildApi('modpacks');
  const modsC = seed(api, 'modsResults', PLACEHOLDER_MODS);
  const packC = seed(api, 'modpacksResults', PLACEHOLDER_MODPACKS);
  api.display({ hits: [HIT], isTrending: true, source: 'modrinth' });
  check(packC.children.length === 1,
    '无 tab 时应回退到活动页签 modpacks (实际 children=' + packC.children.length + ')');
  check(modsC.children.length === 0 && modsC.innerHTML === PLACEHOLDER_MODS,
    '无 tab 回退时 modsResults 不应改动');
}

// ================= 2. 静态: 两侧都带 tab =================
section('静态: displaySearchResults 按 results.tab 路由');
check(/results\.tab/.test(src), 'displaySearchResults 应读取 results.tab');

section('静态: main.py 两个结果载荷携带 tab=content_type');
const tabInPayload = (MAIN.match(/"tab":\s*content_type/g) || []).length;
check(tabInPayload >= 2,
  'main.py 应在 2 处结果 JSON 中带 "tab": content_type (实际 ' + tabInPayload + ' 处)');
check(/result_json\s*=\s*json\.dumps\(\s*\{[\s\S]{0,500}?"tab":\s*content_type/.test(MAIN) ||
  /"isTrending":\s*True[\s\S]{0,80}?"tab":\s*content_type/.test(MAIN),
  '热门(trending) 载荷应包含 tab');

// ================= 汇总 =================
console.log('\n==============================');
console.log('PASS: ' + pass + '  FAIL: ' + fail);
if (fail) {
  console.log('失败项:');
  failures.forEach(function (f) { console.log('  - ' + f); });
}
process.exit(fail ? 1 : 0);
