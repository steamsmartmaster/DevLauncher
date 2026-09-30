'use strict';
// Task 3: Bridge 账号槽与信号 静态接线测试 (TDD RED/GREEN)
// Task 4: 账户页多账号 UI — renderAccountList / 卡片 / 切换 / 删除 / 登出分支 (行为断言)
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { extractFunc, html } = require('./extract_func');

const MAIN = path.join(__dirname, '..', 'main.py');
const py = fs.readFileSync(MAIN, 'utf8');
const REPO = path.join(__dirname, '..');

let pass = 0, fail = 0;
const failures = [];
function check(cond, msg) {
  if (cond) pass++;
  else { fail++; failures.push(msg); console.log('  FAIL: ' + msg); }
}
function section(t) { console.log('\n== ' + t + ' =='); }

// 提取 Python 类方法源码：class 内 4 空格缩进的 def xxx( ... 到下一个同缩进 def / 装饰器为止
function extractMethod(name) {
  const marker = 'def ' + name + '(';
  const start = py.indexOf(marker);
  if (start < 0) return null;
  const rest = py.slice(start + marker.length);
  const m = /\n    (?:def |@)/.exec(rest);
  return m ? py.slice(start, start + marker.length + m.index) : py.slice(start);
}

function countOf(s) { return py.split(s).length - 1; }
function countIn(s, hay) { return hay.split(s).length - 1; }

// ================= 1. 信号与槽声明 =================
section('静态: accountsLoaded 信号 + 三个账号槽');
check(/accountsLoaded\s*=\s*pyqtSignal\(str\)/.test(py), 'main.py 应含 accountsLoaded = pyqtSignal(str)');
check(extractMethod('getAccounts') !== null, 'main.py 应含 def getAccounts');
check(extractMethod('switchAccount') !== null, 'main.py 应含 def switchAccount');
check(extractMethod('removeAccount') !== null, 'main.py 应含 def removeAccount');

// ================= 2. getAccounts 摘要 JSON =================
section('静态: getAccounts 摘要 JSON');
const ga = extractMethod('getAccounts');
check(ga !== null && ga.indexOf('ensure_ascii=False') >= 0, 'getAccounts 实现应含 ensure_ascii=False');
check(ga !== null && ga.indexOf('accountsLoaded.emit') >= 0, 'getAccounts 应 emit accountsLoaded');

// ================= 3. _emit_login_status 抽取与复用 =================
section('静态: _emit_login_status 抽取 + checkLoginStatus 复用');
const refs = countOf('_emit_login_status');
check(refs >= 2, '_emit_login_status 至少应有 2 处引用 (实际 ' + refs + ')');
const cls = extractMethod('checkLoginStatus');
check(cls !== null, 'main.py 应保留 def checkLoginStatus');
check(cls !== null && cls.indexOf('_emit_login_status()') >= 0, 'checkLoginStatus 应调用 _emit_login_status()');

// ================= 4. switch/remove 成功后复用登录态 emit =================
section('静态: switchAccount/removeAccount 复用 _emit_login_status');
const sw = extractMethod('switchAccount');
check(sw !== null && sw.indexOf('_emit_login_status(') >= 0, 'switchAccount 应调用 _emit_login_status(');
const rm = extractMethod('removeAccount');
check(rm !== null && rm.indexOf('_emit_login_status(') >= 0, 'removeAccount 应调用 _emit_login_status(');

// ================= 5. 质量审查: try 包裹 / 登出刷新 / 防御 =================
section('审查: switch/remove 的 payload 构建与 emit 置于 try 内');
const swBody = extractMethod('switchAccount');
check(swBody !== null && swBody.indexOf('accountsLoaded.emit') >= 0 &&
  swBody.indexOf('try:') >= 0 &&
  swBody.indexOf('try:') < swBody.indexOf('accountsLoaded.emit') &&
  swBody.indexOf('accountsLoaded.emit') < swBody.indexOf('except'),
  'switchAccount 应把 accountsLoaded.emit 放进 try(…store 操作…emit…except) 内');
const rmBody = extractMethod('removeAccount');
check(rmBody !== null && rmBody.indexOf('accountsLoaded.emit') >= 0 &&
  rmBody.indexOf('try:') >= 0 &&
  rmBody.indexOf('try:') < rmBody.indexOf('accountsLoaded.emit') &&
  rmBody.indexOf('accountsLoaded.emit') < rmBody.indexOf('except'),
  'removeAccount 应把 accountsLoaded.emit 放进 try(…store 操作…emit…except) 内');

section('审查: getAccounts 异常兜底 + 返回 payload');
check(ga !== null && ga.indexOf('errorOccurred.emit') >= 0 && ga.indexOf('获取账号列表失败') >= 0,
  'getAccounts 应在异常时 errorOccurred.emit("获取账号列表失败")');
check(ga !== null && ga.indexOf('return payload') >= 0, 'getAccounts 应 return payload');

section('审查: _emit_login_status 带 loggedOut 字段');
const elsBody = extractMethod('_emit_login_status');
check(elsBody !== null && elsBody.indexOf('loggedOut') >= 0, '_emit_login_status 实现应含 loggedOut 字段');

section('审查: logout 登出后刷新账号列表 isCurrent');
const loBody = extractMethod('logout');
check(loBody !== null && loBody.indexOf('accountsLoaded.emit') >= 0, 'logout 槽应 emit accountsLoaded 刷新 isCurrent');

// ================= Task 4 静态: index.html 结构 =================
section('静态: accountPage 重构 (列表/空态/删除按钮)');
check(/id="accountList"/.test(html), 'index.html 应含 id="accountList" 容器');
check(html.indexOf('暂无账号，添加一个吧') >= 0, 'index.html 应含空态文案 暂无账号，添加一个吧');
check(/onclick="[^"]*confirmRemoveAccount\(/.test(html), '卡片删除按钮应绑 confirmRemoveAccount(id)');
check(/onclick="[^"]*event\.stopPropagation\(\)[^"]*confirmRemoveAccount\(/.test(html),
  '删除按钮应先 stopPropagation 防止冒泡触发 switchAccount');
check(/onclick="switchAccount\(/.test(html), '卡片点击应绑 switchAccount(id)');
check(/\.account-card\s*\{/.test(html), 'CSS 应新增 .account-card 卡片样式');
check(/\.account-card\.is-current\s*\{/.test(html), 'CSS 应新增 .account-card.is-current 当前描边样式');
check(/\.account-card-avatar\s*\{/.test(html), 'CSS 应新增 .account-card-avatar 头像样式');
const cardCss = /\.account-card\s*\{[^}]*\}/.exec(html);
check(cardCss !== null && /padding:\s*12px 14px/.test(cardCss[0]),
  '.account-card padding 应为 12px 14px (实际: ' + (cardCss ? (cardCss[0].match(/padding:[^;]*/) || [''])[0] : '未找到') + ')');
check(cardCss !== null && cardCss[0].indexOf('44px') < 0,
  '.account-card 不应残留右侧 44px 死空白');
check(/function\s+toggleOfflineForm\s*\(/.test(html) && /function\s+offlineLogin\s*\(/.test(html) &&
  /function\s+startLogin\s*\(/.test(html), '底部添加区应保留 toggleOfflineForm/offlineLogin/startLogin');

section('静态: 新 JS 函数存在且可抽取');
['accountCardHtml', 'renderAccountList', 'switchAccount', 'removeAccount', 'confirmRemoveAccount']
  .forEach(function (n) {
    check(extractFunc(n) !== null, 'index.html 应含 function ' + n);
  });
check(/(?:let|var)\s+accountListCache\s*=\s*\[\s*\]/.test(html), 'index.html 应声明 accountListCache 数组缓存');

section('静态: renderAccountList 缓存同步先于容器守卫 (M2)');
const rSrc = extractFunc('renderAccountList');
check(rSrc !== null, 'index.html 应含 function renderAccountList');
const iCacheAssign = rSrc === null ? -1 : rSrc.indexOf('accountListCache =');
const iListGuard = rSrc === null ? -1 : rSrc.indexOf('if (!list)');
check(iCacheAssign >= 0 && iListGuard >= 0 && iCacheAssign < iListGuard,
  '缓存赋值必须在 if (!list) 守卫之前 (实际 ' + iCacheAssign + ' vs ' + iListGuard + ')');

section('静态: navigateTo account 分支拉取账号列表');
const navSrc = extractFunc('navigateTo');
check(navSrc !== null && navSrc.indexOf("page === 'account'") >= 0, "navigateTo 应含 page === 'account' 分支");
check(navSrc !== null && navSrc.indexOf('getAccounts') >= 0, 'navigateTo 的 account 分支应调 getAccounts');

section('静态: updateLoginStatus loggedOut 分支先于 isLoggedIn = true');
const ulsSrc = extractFunc('updateLoginStatus');
const iLogged = ulsSrc === null ? -1 : ulsSrc.indexOf('loggedOut');
const iIsLoggedIn = ulsSrc === null ? -1 : ulsSrc.indexOf('isLoggedIn = true');
check(iLogged >= 0, 'updateLoginStatus 应含 loggedOut 分支');
check(iIsLoggedIn >= 0, 'updateLoginStatus 应保留 isLoggedIn = true 登录分支');
check(iLogged >= 0 && iIsLoggedIn >= 0 && iLogged < iIsLoggedIn,
  'loggedOut 分支必须位于 isLoggedIn = true 之前 (实际 ' + iLogged + ' vs ' + iIsLoggedIn + ')');
check(ulsSrc !== null && ulsSrc.indexOf('updateUserUI()') >= 0, 'loggedOut 分支应调用 updateUserUI()');

section('静态: 登录成功路径刷新账号列表');
check(ulsSrc !== null && ulsSrc.indexOf('getAccounts') >= 0, 'updateLoginStatus 应调 getAccounts 刷新列表');
const olSrc = extractFunc('offlineLogin');
// 测试随规格调整 (M1): 列表刷新统一走 loginComplete→updateLoginStatus，offlineLogin 不再冗余拉取
check(olSrc !== null && olSrc.indexOf('getAccounts') < 0,
  'offlineLogin 不应冗余调 getAccounts (刷新由 updateLoginStatus 承担)');

// ================= S1 静态: silent 标志 =================
section('静态: silent 标志 (切号/删除不踢出账户页)');
check(elsBody !== null && /def _emit_login_status\(self,\s*silent=False\)/.test(elsBody),
  '_emit_login_status 签名应为 (self, silent=False)');
check(elsBody !== null && elsBody.indexOf("'silent'") >= 0,
  "_emit_login_status payload 应带 'silent' 字段");
check(cls !== null && cls.indexOf('silent=True') < 0,
  'checkLoginStatus 应保持 silent=False 启动行为 (不应传 silent=True)');
check(sw !== null && sw.indexOf('_emit_login_status(silent=True)') >= 0,
  'switchAccount 成功路径应调 _emit_login_status(silent=True)');
check(rm !== null && rm.indexOf('_emit_login_status(silent=True)') >= 0,
  'removeAccount 成功路径应调 _emit_login_status(silent=True)');
check(ulsSrc !== null && /if\s*\(\s*data\.silent\s*\)/.test(ulsSrc),
  'updateLoginStatus 应含 if (data.silent) 分支');
const iSilent = ulsSrc === null ? -1 : ulsSrc.search(/if\s*\(\s*data\.silent\s*\)/);
const iNav = ulsSrc === null ? -1 : ulsSrc.indexOf('navigateTo(');
check(iSilent >= 0 && iNav >= 0 && iSilent < iNav,
  'data.silent 分支必须位于 navigateTo( 之前 (实际 ' + iSilent + ' vs ' + iNav + ')');

// ================= Task 4 静态: main.py 接线 (C) =================
section('静态: accountsLoaded → MainWindow → renderAccountList 接线');
check(/self\.bridge\.accountsLoaded\.connect\(self\._on_accounts_loaded\)/.test(py),
  'main.py 接线区应含 self.bridge.accountsLoaded.connect(self._on_accounts_loaded)');
const oal = extractMethod('_on_accounts_loaded');
check(oal !== null, 'main.py 应含 def _on_accounts_loaded');
check(oal !== null && oal.indexOf('runJavaScript') >= 0, '_on_accounts_loaded 应走 runJavaScript (与 versionsLoaded 同款模式)');
check(oal !== null && oal.indexOf('renderAccountList(') >= 0, '_on_accounts_loaded 应调 renderAccountList(...)');

// ================= Task 4 区分度: b1.0 基线 (3338369) 0 命中 =================
section('区分度: 基线 3338369 应 0 命中新标记');
const HEAD_MARKERS = ['renderAccountList', 'confirmRemoveAccount', 'id="accountList"', 'account-card'];
function hits(text) {
  if (text === null || text === undefined) return -1;
  return HEAD_MARKERS.reduce(function (n, m) { return n + countIn(m, text); }, 0);
}
let headHtml = null;
try {
  headHtml = execSync('git show 3338369:ui/index.html', {
    cwd: REPO, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], maxBuffer: 16 * 1024 * 1024
  });
} catch (e) { headHtml = null; }
if (headHtml === null) {
  check(false, '无法读取 3338369:ui/index.html 做基线检查 (git show 失败)');
} else {
  check(hits(headHtml) === 0, '基线 3338369 应 0 命中新标记 (实际 ' + hits(headHtml) + ')');
}
const curHits = hits(html);
check(curHits >= 6, '当前 index.html 新标记应 ≥6 命中 (基线为 0, 实际 ' + curHits + ')');

// ================= DOM 桩 + 工厂 =================
function makeClassList() {
  const s = new Set();
  return {
    add: function () { for (let i = 0; i < arguments.length; i++) s.add(arguments[i]); },
    remove: function () { for (let i = 0; i < arguments.length; i++) s.delete(arguments[i]); },
    toggle: function (c) { if (s.has(c)) s.delete(c); else s.add(c); },
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
    _html: ''
  };
  el.classList = makeClassList();
  Object.defineProperty(el, 'innerHTML', {
    get: function () { return el._html; },
    set: function (v) { el._html = String(v); el.children.length = 0; }
  });
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

const CACHE_DECL = (/(?:let|var)\s+accountListCache\s*=\s*\[\s*\]/.exec(html) || [])[0] || 'var accountListCache = [];';
const LOGIN_DECL = (/(?:let|var)\s+isLoggedIn\s*=\s*false/.exec(html) || [])[0] || 'var isLoggedIn = false;';

function buildApi(opts) {
  opts = opts || {};
  const want = opts.fns || [];
  const srcs = [];
  const missing = [];
  want.forEach(function (n) {
    let s = extractFunc(n);
    if (s && opts.spyUserUI && n === 'updateUserUI') {
      // 真实实现改名保留，另包一层计数桩，便于断言"updateUserUI 被调用"
      s = s.replace('function updateUserUI(', 'function __realUpdateUserUI(');
    }
    if (s) srcs.push(s); else missing.push(n);
  });
  const doc = opts.doc || makeDoc({ missing: opts.missingIds || [] });
  const calls = {
    switchAccount: [], removeAccount: [], getAccounts: 0, offlineLogin: [],
    toast: [], nav: [], confirms: [], userUI: 0
  };
  const confirmAnswer = opts.confirm === undefined ? true : opts.confirm;
  const pythonInterface = {
    switchAccount: function (id) { calls.switchAccount.push(id); },
    removeAccount: function (id) { calls.removeAccount.push(id); },
    getAccounts: function () { calls.getAccounts += 1; return '[]'; },
    offlineLogin: function (u) { calls.offlineLogin.push(u); },
    startLogin: function () { calls.startLogin = (calls.startLogin || 0) + 1; },
    logout: function () {}
  };
  const showToast = function (m, t) { calls.toast.push([m, t]); };
  const navigateTo = function (p) { calls.nav.push(p); };
  const confirmFn = function (msg) { calls.confirms.push(msg); return confirmAnswer; };
  if (missing.length) return { missing: missing, calls: calls, doc: doc };

  const retLines = ['return {'];
  want.forEach(function (n) { retLines.push('  ' + n + ': ' + n + ','); });
  retLines.push('  get isLoggedIn(){ return isLoggedIn; },');
  retLines.push('  get accountListCache(){ return accountListCache; },');
  retLines.push('  calls: calls');
  retLines.push('};');
  const spyWrapper = opts.spyUserUI
    ? ['function updateUserUI() { calls.userUI += 1; return __realUpdateUserUI(); }']
    : [];
  const body = [
    CACHE_DECL,
    LOGIN_DECL,
    'function escapeHtml(t){ return String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }',
    'function escapeAttr(t){ return String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/\'/g, "&#39;"); }',
    srcs.join('\n'),
    spyWrapper.join('\n'),
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

const ACCOUNTS = [
  { id: 'a1', type: 'offline', name: 'Steve', uuid: 'u1', lastUsed: '2026-01-01', isCurrent: true },
  { id: 'a2', type: 'microsoft', name: 'Alex', uuid: 'u2', lastUsed: '2026-01-02', isCurrent: false },
  { id: 'a3', type: 'offline', name: '张三', uuid: 'u3', lastUsed: '2026-01-03', isCurrent: false }
];

// ================= 行为: renderAccountList =================
section('行为: renderAccountList 渲染 3 张卡片');
{
  const api = buildApi({ fns: ['accountCardHtml', 'renderAccountList'] });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.renderAccountList(ACCOUNTS);
    const out = api.doc.getElementById('accountList').innerHTML;
    check((out.match(/<div class="account-card[" ]/g) || []).length === 3,
      '应渲染 3 张卡片 (实际 ' + (out.match(/<div class="account-card[" ]/g) || []).length + ')');
    check(out.indexOf('离线') >= 0, '应含 离线 徽章文案');
    check(out.indexOf('Microsoft') >= 0, '应含 Microsoft 徽章文案');
    check(/account-card is-current/.test(out), '当前卡片应带 is-current 描边 class');
    check(out.indexOf('✓') >= 0, '当前卡片应带 ✓ 当前标记');
    check(out.indexOf('a1') >= 0 && out.indexOf('a2') >= 0 && out.indexOf('a3') >= 0,
      '3 张卡片应携带各自 data-id');
    check(out.indexOf("switchAccount('a1')") >= 0 && out.indexOf("switchAccount('a3')") >= 0,
      '整卡点击应绑定 switchAccount(id)');
    check(out.indexOf("confirmRemoveAccount('a1')") >= 0,
      '卡片应含删除按钮 confirmRemoveAccount(id)');
    check(out.indexOf('access_token') < 0 && JSON.stringify(out).indexOf('access_token') < 0,
      '渲染输出不得出现 access_token');
    check(JSON.stringify(api.fns.accountListCache).indexOf('access_token') < 0,
      '缓存摘要同样不得出现 access_token');
  }
}

section('行为: renderAccountList 空态');
{
  const api = buildApi({ fns: ['accountCardHtml', 'renderAccountList'] });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.renderAccountList([]);
    const out = api.doc.getElementById('accountList').innerHTML;
    check(out.indexOf('暂无账号') >= 0, '空数组应显示空态文案 暂无账号 (实际: ' + out.slice(0, 60) + ')');
    check((out.match(/<div class="account-card[" ]/g) || []).length === 0, '空数组不应渲染卡片');
    api.fns.renderAccountList(null);
    const out2 = api.doc.getElementById('accountList').innerHTML;
    check(out2.indexOf('暂无账号') >= 0, 'null 载荷也应显示空态文案');
  }
}

section('行为: accountCardHtml 首字母头像');
{
  const api = buildApi({ fns: ['accountCardHtml'] });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    const en = api.fns.accountCardHtml({ id: 'b1', type: 'offline', name: 'Steve', isCurrent: false });
    check(en.indexOf('<div class="account-card-avatar">S</div>') >= 0,
      '英文名应取首字母大写 S (实际片段: ' + (en.match(/account-card-avatar">[^<]*/) || [''])[0] + ')');
    const zh = api.fns.accountCardHtml({ id: 'b2', type: 'microsoft', name: '张三', isCurrent: false });
    check(zh.indexOf('account-card-avatar">张</div>') >= 0,
      '中文名应取首字 张 (实际片段: ' + (zh.match(/account-card-avatar">[^<]*/) || [''])[0] + ')');
    check(en.indexOf('离线') >= 0 && zh.indexOf('Microsoft') >= 0, '徽章文案应随 type 切换');
    check(en.indexOf('is-current') < 0 && en.indexOf('✓') < 0, '非当前项不应带 is-current/✓');
  }
}

// ================= 行为: switchAccount =================
section('行为: switchAccount 调度与当前项去重');
{
  const api = buildApi({ fns: ['accountCardHtml', 'renderAccountList', 'switchAccount'] });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.renderAccountList(ACCOUNTS);
    api.fns.switchAccount('a2');
    check(api.calls.switchAccount.join(',') === 'a2',
      "switchAccount('a2') 应转发给 bridge (实际: " + JSON.stringify(api.calls.switchAccount) + ')');
    api.fns.switchAccount('a1');
    check(api.calls.switchAccount.join(',') === 'a2',
      '当前账号再次点击不应重复调用 (实际: ' + JSON.stringify(api.calls.switchAccount) + ')');
    api.fns.switchAccount('');
    check(api.calls.switchAccount.length === 1, '空 id 不应调用 bridge');
  }
}

// ================= 行为: remove / confirm =================
section('行为: removeAccount 与 confirmRemoveAccount');
{
  const api = buildApi({ fns: ['removeAccount', 'confirmRemoveAccount'], confirm: true });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.removeAccount('x');
    check(api.calls.removeAccount.join(',') === 'x', "removeAccount('x') 应调 pythonInterface.removeAccount");
    api.fns.confirmRemoveAccount('y');
    check(api.calls.confirms.length === 1, 'confirmRemoveAccount 应弹 confirm 二次确认');
    check(api.calls.removeAccount.join(',') === 'x,y', '确认后应调用 removeAccount (实际: ' + JSON.stringify(api.calls.removeAccount) + ')');
  }
  const api2 = buildApi({ fns: ['removeAccount', 'confirmRemoveAccount'], confirm: false });
  check(api2.missing.length === 0, '缺少函数(取消路径): ' + (api2.missing.join(',') || '-'));
  if (!api2.missing.length) {
    api2.fns.confirmRemoveAccount('z');
    check(api2.calls.removeAccount.length === 0,
      'confirm 取消时不应调用 removeAccount (实际: ' + JSON.stringify(api2.calls.removeAccount) + ')');
    check(api2.calls.confirms.length === 1, '取消路径也应弹出 confirm');
  }
}

// ================= 行为: updateLoginStatus =================
section('行为: updateLoginStatus 的 loggedOut 分支 (阻断项)');
{
  const api = buildApi({ fns: ['updateUserUI', 'updateLoginStatus'] });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.updateLoginStatus({ loggedOut: true, name: '未登录', id: '', isOffline: false });
    check(api.fns.isLoggedIn === false, 'loggedOut 应置 isLoggedIn = false (实际: ' + api.fns.isLoggedIn + ')');
    check(api.calls.nav.length === 0, 'loggedOut 不应 navigateTo (实际: ' + JSON.stringify(api.calls.nav) + ')');
    check(api.calls.toast.length === 0, 'loggedOut 不应弹 欢迎 toast (实际: ' + JSON.stringify(api.calls.toast) + ')');
    check(api.doc.getElementById('logoutBtn').style.display === 'none',
      'loggedOut 应经 updateUserUI 隐藏 logoutBtn');
    check(api.doc.getElementById('sidebarUserName').textContent === '未登录',
      'loggedOut 侧栏应显示 未登录');

    const api2 = buildApi({ fns: ['updateUserUI', 'updateLoginStatus'] });
    api2.fns.updateLoginStatus({ loggedOut: false, name: 'Steve', id: 'a1', isOffline: true });
    check(api2.fns.isLoggedIn === true, '登录态应置 isLoggedIn = true');
    check(api2.calls.nav.join(',') === 'versions', '登录成功应 navigateTo(versions) (实际: ' + JSON.stringify(api2.calls.nav) + ')');
    check(api2.calls.getAccounts >= 1, '登录成功后应调 getAccounts 刷新账号列表');
    check(api2.doc.getElementById('pageAvatar').textContent === 'S', '登录成功页头像应为 S');
  }
}

// ================= 行为: offlineLogin 成功路径 =================
section('行为: offlineLogin 调 bridge (刷新改走 updateLoginStatus)');
{
  const api = buildApi({ fns: ['offlineLogin'] });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.doc.getElementById('offlineUsername').value = 'Steve';
    api.fns.offlineLogin();
    check(api.calls.offlineLogin.join(',') === 'Steve', 'offlineLogin 应转发用户名 (实际: ' + JSON.stringify(api.calls.offlineLogin) + ')');
    // 测试随规格调整 (M1): 不再冗余 getAccounts，列表刷新由 updateLoginStatus 承担
    check(api.calls.getAccounts === 0,
      'offlineLogin 不应冗余调 getAccounts (实际 ' + api.calls.getAccounts + ' 次)');

    const empty = buildApi({ fns: ['offlineLogin'] });
    empty.doc.getElementById('offlineUsername').value = '   ';
    empty.fns.offlineLogin();
    check(empty.calls.offlineLogin.length === 0, '空用户名不应提交');
    check(empty.calls.toast.length === 1 && empty.calls.toast[0][0].indexOf('请输入用户名') >= 0,
      '空用户名应提示 请输入用户名');
  }
}

// ================= S1 行为: silent 更新登录态 =================
section('行为: silent 切号/删除只更新登录态 (不踢页不弹窗不重拉)');
{
  const api = buildApi({ fns: ['updateUserUI', 'updateLoginStatus'], spyUserUI: true });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.updateLoginStatus({ name: 'B', id: 'b1', isOffline: true, loggedOut: false, silent: true });
    check(api.fns.isLoggedIn === true, 'silent 登录态应置 isLoggedIn = true (实际: ' + api.fns.isLoggedIn + ')');
    check(api.calls.nav.length === 0,
      'silent 不应 navigateTo (实际: ' + JSON.stringify(api.calls.nav) + ')');
    check(api.calls.toast.length === 0,
      'silent 不应弹 欢迎 toast (实际: ' + JSON.stringify(api.calls.toast) + ')');
    check(api.calls.getAccounts === 0,
      'silent 不应再拉 getAccounts (列表由 accountsLoaded 直推, 实际 ' + api.calls.getAccounts + ' 次)');
    check(api.calls.userUI >= 1, 'silent 应调用 updateUserUI (实际 ' + api.calls.userUI + ' 次)');
  }
  // 反向: 非 silent 的登录成功路径仍 navigate + toast + 拉列表
  const api2 = buildApi({ fns: ['updateUserUI', 'updateLoginStatus'] });
  if (!api2.missing.length) {
    api2.fns.updateLoginStatus({ name: 'C', id: 'c1', isOffline: true, loggedOut: false });
    check(api2.calls.nav.join(',') === 'versions', '非 silent 仍应 navigateTo(versions)');
    check(api2.calls.toast.length === 1, '非 silent 仍应弹欢迎 toast');
    check(api2.calls.getAccounts >= 1, '非 silent 仍应调 getAccounts');
  }
}

// ================= I-1 行为: silent 分支同步身份展示 =================
section('行为: I-1 silent 分支写侧栏/页头用户名与头像首字母');
{
  const api = buildApi({ fns: ['updateUserUI', 'updateLoginStatus'], spyUserUI: true });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.updateLoginStatus({ name: 'B', id: 'b1', isOffline: false, loggedOut: false, silent: true });
    check(api.doc.getElementById('sidebarUserName').textContent === 'B',
      'silent 后 sidebarUserName 应写为 B (实际 ' +
      JSON.stringify(api.doc.getElementById('sidebarUserName').textContent) + ')');
    check(api.doc.getElementById('sidebarAvatar').textContent === 'B',
      'silent 后 sidebarAvatar 应同步首字母 B');
    check(api.doc.getElementById('pageUserName').textContent === 'B',
      'silent 后 pageUserName 应写为 B');
    check(api.doc.getElementById('pageAvatar').textContent === 'B',
      'silent 后 pageAvatar 应同步首字母 B');
    check(api.calls.nav.length === 0 && api.calls.toast.length === 0 && api.calls.getAccounts === 0,
      'I-1 不改变 silent 语义: 仍不 navigate/toast/getAccounts');
  }
}

// ================= M2 行为: 容器缺失时缓存仍同步 =================
section('行为: #accountList 缺失时缓存仍与后端一致 (M2)');
{
  const api = buildApi({ fns: ['accountCardHtml', 'renderAccountList'], missingIds: ['accountList'] });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    api.fns.renderAccountList(ACCOUNTS);
    check(api.doc.getElementById('accountList') === null, '前置: 文档应无 #accountList 容器');
    check(api.fns.accountListCache.length === 3,
      '容器缺失时缓存也应同步为 3 条 (实际 ' + api.fns.accountListCache.length + ')');
  }
}

// ================= 可选8: XSS 转义 =================
section('行为: accountCardHtml 对名字做 HTML 转义 (可选8)');
{
  const api = buildApi({ fns: ['accountCardHtml'] });
  if (!api.missing.length) {
    const evil = api.fns.accountCardHtml({ id: 'x1', type: 'offline', name: '<img src=x onerror=alert(1)>', isCurrent: false });
    check(evil.indexOf('&lt;img src=x onerror=alert(1)&gt;') >= 0,
      '名字应被转义为 &lt;img ...&gt; (实际片段: ' + (evil.match(/account-card-name">[^<]*/) || [''])[0] + ')');
    check(evil.indexOf('<img') < 0, '输出不得出现原始 <img 标签');
    const amp = api.fns.accountCardHtml({ id: 'x2', type: 'offline', name: 'A&B', isCurrent: false });
    check(amp.indexOf('A&amp;B') >= 0, '& 应转义为 &amp;');
  }
}

// ================= S1: 账号卡属性上下文引号转义 =================
section('行为: S1 accountCardHtml data-id/onclick 属性转义引号');
{
  const api = buildApi({ fns: ['accountCardHtml'] });
  check(api.missing.length === 0, '缺少函数: ' + (api.missing.join(',') || '-'));
  if (!api.missing.length) {
    const q = api.fns.accountCardHtml({ id: 'a"b\'c', type: 'offline', name: 'Q' });
    check(q.indexOf('data-id="a&quot;b&#39;c"') >= 0,
      'data-id 属性应经 escapeAttr 转义 (实际片段: ' + (q.match(/data-id="[^"]*"/) || [''])[0] + ')');
    check(q.indexOf('data-id="a"b\'c"') < 0, '不得出现未转义的 data-id="a"b\'c"');
    check(q.indexOf("switchAccount('a&quot;b&#39;c')") >= 0,
      'onclick 内联参数应经 escapeAttr 转义');
  }
}

// ================= 汇总 =================
console.log('\n==============================');
console.log('PASS: ' + pass + '  FAIL: ' + fail);
if (fail) {
  console.log('失败项:');
  failures.forEach(function (f) { console.log('  - ' + f); });
}
process.exit(fail ? 1 : 0);
