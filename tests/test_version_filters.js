'use strict';
// 下载→版本页 4 项需求离线测试 (TDD RED/GREEN)
// 1) 版本卡分片渲染防卡顿  2) 下拉统一排序(正式版→愚人节→其他, 选中置顶)
// 3) dlVersionFilter 默认正式版 + 不被 populate 清空
// 4) 头部筛选标签仅在 下载页+版本子tab 显示
const fs = require('fs');
const path = require('path');

const INDEX = path.join(__dirname, '..', 'ui', 'index.html');
const html = fs.readFileSync(INDEX, 'utf8');

// ---------------- 从 index.html 抽取函数源码 ----------------
function skipString(s, i) {
  const q = s[i];
  i++;
  while (i < s.length) {
    if (s[i] === '\\') { i += 2; continue; }
    if (s[i] === q) return i;
    i++;
  }
  return i;
}

function extractFunc(name) {
  const re = new RegExp('function\\s+' + name + '\\s*\\(');
  const m = re.exec(html);
  if (!m) return null;
  let i = m.index + m[0].length - 1; // 指向 '('
  let depth = 0;
  for (; i < html.length; i++) {
    const c = html[i];
    if (c === '(') depth++;
    else if (c === ')') { depth--; if (depth === 0) break; }
  }
  i = html.indexOf('{', i);
  if (i < 0) return null;
  let d = 0;
  for (; i < html.length; i++) {
    const c = html[i];
    if (c === "'" || c === '"' || c === '`') { i = skipString(html, i); continue; }
    if (c === '/' && html[i + 1] === '/') {
      const nl = html.indexOf('\n', i);
      if (nl < 0) return null;
      i = nl;
      continue;
    }
    if (c === '/' && html[i + 1] === '*') {
      const e = html.indexOf('*/', i + 2);
      if (e < 0) return null;
      i = e + 1;
      continue;
    }
    if (c === '{') d++;
    else if (c === '}') { d--; if (d === 0) return html.slice(m.index, i + 1); }
  }
  return null;
}

// ---------------- DOM 桩 ----------------
function makeClassList(initial) {
  const s = new Set(initial || []);
  return {
    add: function () { for (let i = 0; i < arguments.length; i++) s.add(arguments[i]); },
    remove: function () { for (let i = 0; i < arguments.length; i++) s.delete(arguments[i]); },
    toggle: function (c, f) {
      if (f === undefined) { if (s.has(c)) s.delete(c); else s.add(c); }
      else if (f) s.add(c); else s.delete(c);
    },
    contains: function (c) { return s.has(c); },
    _set: s
  };
}

function makeEl(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(),
    children: [],
    style: {},
    dataset: {},
    attributes: {},
    value: '',
    textContent: '',
    disabled: false,
    onclick: null,
    className: '',
    _html: '',
    classList: makeClassList()
  };
  Object.defineProperty(el, 'innerHTML', {
    get: function () { return el._html; },
    set: function (v) {
      el._html = String(v);
      el.children.length = 0;
      if (el.tagName === 'SELECT') el.value = '';
    }
  });
  Object.defineProperty(el, 'options', {
    get: function () { return el.children.filter(function (c) { return c.tagName === 'OPTION'; }); }
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
  el.removeChild = function (c) {
    const i = el.children.indexOf(c);
    if (i >= 0) el.children.splice(i, 1);
    return c;
  };
  el.querySelector = function () { return null; };
  el.querySelectorAll = function () { return []; };
  el.addEventListener = function () {};
  el.setAttribute = function (k, v) { el.attributes[k] = v; };
  el.getAttribute = function (k) { return k in el.attributes ? el.attributes[k] : null; };
  return el;
}

function makeDocument() {
  const byId = new Map();
  const TAGS = {
    dlVersionFilter: 'select', modGameVersion: 'select', modpackGameVersion: 'select',
    pickerGameVersion: 'select', dlVersionSearch: 'input', searchInput: 'input',
    launchBtn: 'button'
  };
  const filterBtns = ['all', 'release', 'snapshot'].map(function (f) {
    const b = makeEl('button');
    b.dataset.filter = f;
    b.classList.add('filter-btn');
    if (f === 'all') b.classList.add('active');
    return b;
  });
  const headerActions = makeEl('div');
  headerActions.classList.add('header-actions');
  headerActions.style.display = 'none';
  const doc = {
    getElementById: function (id) {
      if (!byId.has(id)) byId.set(id, makeEl(TAGS[id] || 'div'));
      return byId.get(id);
    },
    createElement: function (t) { return makeEl(t); },
    createDocumentFragment: function () { const f = makeEl('#fragment'); f._fragment = true; return f; },
    querySelector: function (sel) {
      if (sel === '.header-actions') return headerActions;
      return null;
    },
    querySelectorAll: function (sel) {
      if (sel === '.filter-btn' || sel === '.header-actions .filter-btn') return filterBtns;
      return [];
    },
    addEventListener: function () {},
    removeEventListener: function () {},
    _byId: byId,
    _filterBtns: filterBtns,
    _headerActions: headerActions
  };
  return doc;
}

// ---------------- 工厂: 拼装被测函数 ----------------
function buildEnv() {
  const doc = makeDocument();
  const rafQueue = [];
  const raf = function (cb) { rafQueue.push(cb); return rafQueue.length; };
  raf.flush = function () {
    let n = 0;
    while (rafQueue.length && n < 10000) { rafQueue.shift()(); n++; }
    return n;
  };
  raf.pending = function () { return rafQueue.length; };

  const REQUIRED = [
    'createVersionCard', 'renderDownloadGrid', 'populateGameVersionDropdowns',
    'updateInstalledGrid', 'updateVersionGrid', 'filterDownloadVersions',
    'selectVersion', 'setFilter', 'navigateTo', 'switchDownloadTab'
  ];
  const OPTIONAL = ['versionRank', 'syncHeaderTags'];
  const parts = [];
  REQUIRED.forEach(function (n) {
    const src = extractFunc(n);
    if (!src) throw new Error('index.html 缺少必需函数: ' + n);
    parts.push(src);
  });
  OPTIONAL.forEach(function (n) {
    const src = extractFunc(n);
    if (src) parts.push(src);
  });

  const preamble = [
    'var pythonInterface = null;',
    "var currentPage = 'versions';",
    'var isLoggedIn = false;',
    "var selectedVersion = '';",
    'var versions = [];',
    "var currentFilter = 'all';",
    'var needsDownloadGridRender = false;',
    'var tabLoadedFlags = { mods:false, modpacks:false, worlds:false, datapacks:false };',
    "var currentDlTab = 'versions';",
    'var dlRenderGen = 0;',
    'var installCalls = [];',
    'var trendingCalls = [];',
    'function installVersionWithLoader(id){ installCalls.push(id); }',
    'function loadTrendingContent(tab){ trendingCalls.push(tab); }',
    'function showLoading(){}',
    'function loadModsFromLauncher(){}',
    'function loadWorldsFromLauncher(){}',
    'function loadResourcepacksFromLauncher(){}',
    'function escapeHtml(t){ return String(t); }'
  ].join('\n');

  const ret = [
    'return {',
    '  navigateTo: navigateTo,',
    '  renderDownloadGrid: renderDownloadGrid,',
    '  populateGameVersionDropdowns: populateGameVersionDropdowns,',
    '  selectVersion: selectVersion,',
    '  setFilter: setFilter,',
    '  switchDownloadTab: switchDownloadTab,',
    '  updateVersionGrid: updateVersionGrid,',
    '  filterDownloadVersions: filterDownloadVersions,',
    "  versionRank: (typeof versionRank === 'function') ? versionRank : null,",
    "  syncHeaderTags: (typeof syncHeaderTags === 'function') ? syncHeaderTags : null,",
    '  installCalls: installCalls,',
    '  trendingCalls: trendingCalls,',
    '  state: {',
    "    get currentPage(){ return currentPage; }, set currentPage(v){ currentPage = v; },",
    "    get currentFilter(){ return currentFilter; }, set currentFilter(v){ currentFilter = v; },",
    "    get selectedVersion(){ return selectedVersion; }, set selectedVersion(v){ selectedVersion = v; },",
    "    get versions(){ return versions; }, set versions(v){ versions = v; },",
    "    get needsDownloadGridRender(){ return needsDownloadGridRender; }, set needsDownloadGridRender(v){ needsDownloadGridRender = v; },",
    "    get currentDlTab(){ return currentDlTab; }, set currentDlTab(v){ currentDlTab = v; },",
    "    get dlRenderGen(){ return dlRenderGen; }",
    '  }',
    '};'
  ].join('\n');

  const factory = new Function('document', 'requestAnimationFrame', preamble + '\n' + parts.join('\n') + '\n' + ret);
  const api = factory(doc, raf);
  return { api: api, doc: doc, raf: raf, state: api.state };
}

// ---------------- 夹具 & 断言 ----------------
const FIXTURE = [
  { id: '1.21.1', type: 'release', releaseTime: '2024-08-08T10:00:00+00:00' },
  { id: '1.19', type: 'release', releaseTime: '2022-06-07T10:00:00+00:00' },
  { id: '1.19-pre1', type: 'old_beta', releaseTime: '2022-06-01T10:00:00+00:00' },
  { id: '25w14craftmine', type: 'snapshot', releaseTime: '2025-04-01T12:00:00+00:00' },
  { id: '25w18a', type: 'snapshot', releaseTime: '2025-05-07T12:00:00+00:00' },
  { id: 'b1.7.3', type: 'old_beta', releaseTime: '2011-07-08T00:00:00+00:00' }
];

function makeVersions(n, prefix) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const id = prefix + String(i).padStart(3, '0');
    out.push({ id: id, type: 'release', releaseTime: '2024-01-01T00:00:00+00:00' });
  }
  return out;
}

function baseOf(id) {
  const m = id.match(/^(\d+\.\d+(?:\.\d+)?)/);
  return m ? m[1] : id;
}
function fixtureRank(v) {
  if (v.type === 'release') return 0;
  if ((v.releaseTime || '').indexOf('-04-01') !== -1) return 1;
  return 2;
}
function oracleRank(value) {
  const related = FIXTURE.filter(function (v) { return baseOf(v.id) === value; });
  if (!related.length) return 0; // commonVersions 未见 → 0
  return Math.min.apply(null, related.map(fixtureRank));
}

let pass = 0, fail = 0;
const failures = [];
function check(cond, msg) {
  if (cond) pass++;
  else { fail++; failures.push(msg); console.log('  FAIL: ' + msg); }
}
function section(t) { console.log('\n== ' + t + ' =='); }
function seedSelect(env, id, opts, value) {
  const sel = env.doc.getElementById(id);
  sel.innerHTML = '';
  opts.forEach(function (o) {
    const el = env.doc.createElement('option');
    el.value = o[0];
    el.textContent = o[1];
    sel.appendChild(el);
  });
  sel.value = value;
}
const TYPE_OPTS = [['all', '全部'], ['release', '正式版'], ['snapshot', '快照版']];
const BLANK_FIRST = [['', '全部版本']];

// ================= 1. 静态检查 =================
section('静态: 需求3 dlVersionFilter 默认正式版');
check(/function\s+versionRank\s*\(/.test(html), '缺少 versionRank 函数');
const selIds = /selectIds\s*=\s*\[([^\]]*)\]/.exec(html);
check(!!selIds, '找不到 selectIds 声明');
if (selIds) {
  check(selIds[1].indexOf('dlVersionFilter') === -1, 'selectIds 不应包含 dlVersionFilter (实际: ' + selIds[1] + ')');
  check(selIds[1].indexOf('modGameVersion') !== -1, 'selectIds 应包含 modGameVersion');
  check(selIds[1].indexOf('modpackGameVersion') !== -1, 'selectIds 应包含 modpackGameVersion');
}
const dlSel = /<select[^>]*id="dlVersionFilter"[^>]*>[\s\S]*?<\/select>/.exec(html);
check(!!dlSel, '找不到 dlVersionFilter select');
if (dlSel) {
  check(/<option value="release"\s+selected/.test(dlSel[0]), 'dlVersionFilter 应默认选中 release');
  check(dlSel[0].indexOf('onchange="setFilter(this.value)"') !== -1, 'dlVersionFilter onchange 应为 setFilter(this.value)');
}
check(html.indexOf('id="searchInput"') !== -1, '头部搜索框应保留');
check(/oninput="filterDownloadVersions\(\)"/.test(html), 'dlVersionSearch 应仍走 filterDownloadVersions');

section('静态: 需求4 头部标签显隐');
check(/function\s+syncHeaderTags\s*\(/.test(html), '缺少 syncHeaderTags 函数');
const syncCalls = (html.match(/syncHeaderTags\(\);/g) || []).length;
check(syncCalls >= 3, 'syncHeaderTags() 应在 navigateTo/switchDownloadTab/DOMContentLoaded 调用 3 处 (实际 ' + syncCalls + ')');
check(/var\s+currentDlTab\s*=\s*'versions'/.test(html), "缺少 var currentDlTab = 'versions'");
check(/var\s+dlRenderGen\s*=\s*0/.test(html), '缺少 var dlRenderGen = 0');
check(/data-filter="snapshot"/.test(html), '头部筛选标签应保留');

// ================= 2. versionRank =================
section('versionRank 分级');
let env = buildEnv();
check(typeof env.api.versionRank === 'function', 'versionRank 应可从 index.html 抽取');
if (typeof env.api.versionRank === 'function') {
  const vr = env.api.versionRank;
  check(vr({ type: 'release' }) === 0, 'release → 0');
  check(vr({ type: 'release', releaseTime: '2024-04-01T00:00:00+00:00' }) === 0, 'release 含 04-01 仍 → 0');
  check(vr({ type: 'snapshot', releaseTime: '2025-04-01' }) === 1, 'snapshot 2025-04-01 → 1');
  check(vr({ type: 'snapshot', releaseTime: '2025-04-01T12:00:00+00:00' }) === 1, 'snapshot 2025-04-01T... → 1');
  check(vr({ type: 'old_beta', releaseTime: '2011-04-01' }) === 1, 'old_beta 04-01 → 1');
  check(vr({ type: 'snapshot', releaseTime: '2025-05-07' }) === 2, '普通 snapshot → 2');
  check(vr({ type: 'old_beta', releaseTime: '2011-07-08' }) === 2, 'old_beta → 2');
  check(vr({ type: 'snapshot' }) === 2, '无 releaseTime → 2');
}

// ================= 3. 下拉统一排序 =================
section('需求2: 下拉统一排序');
env = buildEnv();
env.state.versions = FIXTURE;
env.state.selectedVersion = '';
seedSelect(env, 'modGameVersion', BLANK_FIRST, '');
seedSelect(env, 'modpackGameVersion', BLANK_FIRST, '');
seedSelect(env, 'pickerGameVersion', BLANK_FIRST, '');
env.api.populateGameVersionDropdowns();
const opts = env.doc.getElementById('modGameVersion').options.slice(1).map(function (o) { return o.value; });
let last = -1, mono = true;
opts.forEach(function (v) { const r = oracleRank(v); if (r < last) mono = false; last = r; });
check(mono, 'modGameVersion 秩应单调不减 (实际头部: ' + opts.slice(0, 5).join(',') + ')');
check(opts.indexOf('1.21.1') !== -1 && opts.indexOf('25w14craftmine') !== -1 && opts.indexOf('1.21.1') < opts.indexOf('25w14craftmine'), '正式版 应排在 愚人节前');
check(opts.indexOf('25w14craftmine') !== -1 && opts.indexOf('25w18a') !== -1 && opts.indexOf('25w14craftmine') < opts.indexOf('25w18a'), '愚人节 应排在 普通快照前');
check(opts.indexOf('25w14craftmine') !== -1 && opts.indexOf('b1.7.3') !== -1 && opts.indexOf('25w14craftmine') < opts.indexOf('b1.7.3'), '愚人节 应排在 old_beta 前');
check(opts.slice(-3).join(',') === '25w14craftmine,b1.7.3,25w18a', '末尾应为 25w14craftmine,b1.7.3,25w18a (实际: ' + opts.slice(-3).join(',') + ')');
const popts = env.doc.getElementById('pickerGameVersion').options.slice(1).map(function (o) { return o.value; });
let plast = -1, pmono = true;
popts.forEach(function (v) { const r = oracleRank(v); if (r < plast) pmono = false; plast = r; });
check(pmono, 'pickerGameVersion 秩应单调不减');

section('需求2: 选中版本置顶');
env = buildEnv();
env.state.versions = FIXTURE;
env.state.selectedVersion = '25w18a';
seedSelect(env, 'modGameVersion', BLANK_FIRST, '');
seedSelect(env, 'pickerGameVersion', BLANK_FIRST, '');
env.api.populateGameVersionDropdowns();
const mopts = env.doc.getElementById('modGameVersion').options;
check(mopts.length > 1 && mopts[1].value === '25w18a', 'modGameVersion 首个版本项应为选中的 25w18a (实际: ' + (mopts[1] && mopts[1].value) + ')');
check(mopts.filter(function (o) { return o.value === '25w18a'; }).length === 1, '置顶不应产生重复项');
const popts2 = env.doc.getElementById('pickerGameVersion').options;
check(popts2.length > 1 && popts2[1].value === '25w18a', 'pickerGameVersion 首个版本项应为选中的 25w18a');

section('需求2: selectVersion 后重新填充');
env = buildEnv();
env.state.versions = FIXTURE;
env.state.selectedVersion = '';
seedSelect(env, 'modGameVersion', BLANK_FIRST, '');
env.api.populateGameVersionDropdowns();
env.api.selectVersion('25w18a');
const sopts = env.doc.getElementById('modGameVersion').options;
check(sopts.length > 1 && sopts[1].value === '25w18a', 'selectVersion 应重新填充并置顶选中版本 (实际: ' + (sopts[1] && sopts[1].value) + ')');

// ================= 4. dlVersionFilter 不被 populate 破坏 =================
section('需求3: populate 不破坏 dlVersionFilter');
env = buildEnv();
env.state.versions = FIXTURE;
seedSelect(env, 'dlVersionFilter', TYPE_OPTS, 'release');
env.api.populateGameVersionDropdowns();
const dl = env.doc.getElementById('dlVersionFilter');
check(dl.options.map(function (o) { return o.value; }).join(',') === 'all,release,snapshot',
  'dlVersionFilter 类型选项应保持不变 (实际: ' + dl.options.map(function (o) { return o.value; }).join(',') + ')');
check(dl.value === 'release', 'dlVersionFilter 选中值应保持 release (实际: ' + dl.value + ')');

section('需求3: 其它下拉重建后保留选中值');
env = buildEnv();
env.state.versions = FIXTURE;
seedSelect(env, 'modGameVersion', BLANK_FIRST, '');
env.api.populateGameVersionDropdowns();
const mg = env.doc.getElementById('modGameVersion');
check(mg.options.some(function (o) { return o.value === '1.19'; }), '首次填充应含 1.19');
mg.value = '1.19';
env.api.populateGameVersionDropdowns();
check(mg.value === '1.19', 'modGameVersion 重建后应保留选中值 (实际: ' + mg.value + ')');

// ================= 5. 分片渲染 =================
section('需求1: renderDownloadGrid 分片渲染');
env = buildEnv();
env.state.versions = makeVersions(100, 'v');
env.state.currentPage = 'download';
env.state.currentFilter = 'all';
env.doc.getElementById('dlVersionFilter').value = 'all';
env.doc.getElementById('dlVersionSearch').value = '';
const grid = env.doc.getElementById('downloadGrid');
env.api.renderDownloadGrid();
check(grid.children.length > 0 && grid.children.length < 100,
  '首帧应只渲染部分卡片 (实际 ' + grid.children.length + '/100)');
env.raf.flush();
check(grid.children.length === 100, 'flush 后应渲染全部 100 张 (实际 ' + grid.children.length + ')');
check(grid.children.length === 100 && grid.children[99].innerHTML.indexOf('>v099<') >= 0, '末张卡片应为 v099');
grid.children[99].onclick();
check(env.api.installCalls[env.api.installCalls.length - 1] === 'v099', 'onclick 闭包应绑定正确 id');

section('需求1: 新渲染覆盖旧渲染 (gen 守卫)');
env = buildEnv();
env.doc.getElementById('dlVersionFilter').value = 'all';
env.state.versions = makeVersions(100, 'A');
env.api.renderDownloadGrid();
env.state.versions = makeVersions(50, 'B');
env.api.renderDownloadGrid();
  env.raf.flush();
  const grid2 = env.doc.getElementById('downloadGrid');
check(grid2.children.length === 50, '覆盖后应只剩 50 张 (实际 ' + grid2.children.length + ')');
check(grid2.children.every(function (c) { return c.innerHTML.indexOf('>B0') >= 0; }), '覆盖后卡片应全部来自第二次渲染');

section('需求1: 空结果应终止遗留分片');
env = buildEnv();
env.doc.getElementById('dlVersionFilter').value = 'all';
env.state.versions = makeVersions(100, 'A');
env.api.renderDownloadGrid();
env.state.versions = [];
env.api.renderDownloadGrid();
env.raf.flush();
const grid3 = env.doc.getElementById('downloadGrid');
check(grid3.children.length === 0, '空结果 flush 后不应有遗留卡片 (实际 ' + grid3.children.length + ')');
check(grid3.innerHTML.indexOf('没有匹配的版本') >= 0, '空结果应显示提示文案');

section('需求1: 类型筛选仍生效');
env = buildEnv();
env.state.versions = FIXTURE;
env.state.currentPage = 'download';
seedSelect(env, 'dlVersionFilter', TYPE_OPTS, 'release');
env.api.renderDownloadGrid();
const gRel = env.doc.getElementById('downloadGrid');
check(gRel.children.length === 2 && gRel.children.every(function (c) { return c.innerHTML.indexOf('version-badge release') >= 0; }),
  '筛选 release 应只留正式版 (实际 ' + gRel.children.length + ')');
seedSelect(env, 'dlVersionFilter', TYPE_OPTS, 'all');
env.state.currentFilter = 'snapshot';
env.api.renderDownloadGrid();
const gSnap = env.doc.getElementById('downloadGrid');
check(gSnap.children.length > 0 && gSnap.children.every(function (c) { return c.innerHTML.indexOf('version-badge snapshot') >= 0; }),
  'typeFilter=all + 标签 snapshot 时应只留快照');

// ================= 6. 头部标签显隐 =================
section('需求4: 头部标签显隐');
env = buildEnv();
env.doc._filterBtns.forEach(function (b) { b.style.display = 'none'; });
env.api.navigateTo('download');
check(env.doc._headerActions.style.display === 'flex', '下载页 header-actions 应显示');
check(env.doc._filterBtns.every(function (b) { return b.style.display !== 'none'; }), '下载页+版本tab 筛选标签应显示');

env = buildEnv();
env.doc._filterBtns.forEach(function (b) { b.style.display = ''; });
env.state.currentPage = 'download';
env.api.switchDownloadTab('modpacks');
check(env.state.currentDlTab === 'modpacks', 'switchDownloadTab 应更新 currentDlTab (实际: ' + env.state.currentDlTab + ')');
check(env.doc._filterBtns.every(function (b) { return b.style.display === 'none'; }), '切到整合包tab 筛选标签应隐藏');

env = buildEnv();
env.doc._filterBtns.forEach(function (b) { b.style.display = 'none'; });
env.state.currentPage = 'download';
env.state.currentDlTab = 'versions';
env.api.switchDownloadTab('versions');
check(env.doc._filterBtns.every(function (b) { return b.style.display !== 'none'; }), '切回版本tab 筛选标签应显示');

env = buildEnv();
env.doc._filterBtns.forEach(function (b) { b.style.display = ''; });
env.doc._headerActions.style.display = 'flex';
env.api.navigateTo('settings');
check(env.doc._headerActions.style.display === 'none', '非下载页 header-actions 应隐藏');
check(env.doc._filterBtns.every(function (b) { return b.style.display === 'none'; }), '非下载页 筛选标签应隐藏');

env = buildEnv();
env.doc._filterBtns.forEach(function (b) { b.style.display = 'none'; });
env.state.currentDlTab = 'versions';
env.api.navigateTo('download');
check(env.doc._filterBtns.every(function (b) { return b.style.display !== 'none' }), '回到下载页 筛选标签应显示');

// ================= 7. setFilter 回归 =================
section('回归: setFilter 同步标签与下拉');
env = buildEnv();
env.state.versions = FIXTURE;
env.state.currentPage = 'download';
seedSelect(env, 'dlVersionFilter', TYPE_OPTS, 'all');
env.api.setFilter('release');
check(env.state.currentFilter === 'release', 'setFilter 应更新 currentFilter');
check(env.doc.getElementById('dlVersionFilter').value === 'release', 'setFilter 应同步 dlVersionFilter');
const relBtn = env.doc._filterBtns.find(function (b) { return b.dataset.filter === 'release'; });
const allBtn = env.doc._filterBtns.find(function (b) { return b.dataset.filter === 'all'; });
check(relBtn.classList.contains('active'), '正式版标签应 active');
check(!allBtn.classList.contains('active'), '全部标签应非 active');
const gs = env.doc.getElementById('downloadGrid');
check(gs.children.length === 2 && gs.children.every(function (c) { return c.innerHTML.indexOf('version-badge release') >= 0; }),
  'setFilter 后下载网格应只留正式版');

// ================= 汇总 =================
console.log('\n==============================');
console.log('PASS: ' + pass + '  FAIL: ' + fail);
if (fail) {
  console.log('失败项:');
  failures.forEach(function (f) { console.log('  - ' + f); });
}
process.exit(fail ? 1 : 0);
