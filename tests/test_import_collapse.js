// 导入收起改造：收起 → 整窗消失，进度合并到侧边栏启动按钮上方的下载面板
// 红→绿 TDD
const fs = require('fs');
const path = require('path');
const { extractFunc, html } = require('./extract_func.js');

let pass = 0, fail = 0;
function check(cond, msg) { if (cond) pass++; else { fail++; console.log('  FAIL: ' + msg); } }
function section(t) { console.log('\n== ' + t + ' =='); }

// ================= 静态: HTML =================
section('静态: HTML 结构');
check(/id="downloadProgressPanel"/.test(html), '应有 #downloadProgressPanel 侧边栏面板');
check(html.indexOf('id="downloadProgressPanel"') < html.indexOf('id="launchBtn"'),
    '面板应位于 #launchBtn 上方');
check(/id="importExpandBtn"/.test(html), '面板内应有 #importExpandBtn 展开按钮');
check(/id="importExpandBtn"[^>]*onclick="expandImportModal\(\)"/.test(html) ||
    /onclick="expandImportModal\(\)"[^>]*id="importExpandBtn"/.test(html),
    '展开按钮应接 expandImportModal');
check(!/id="importMiniView"/.test(html), '不应再有弹窗内 mini 卡 #importMiniView（收起改为整窗消失）');
check(!/id="importFullView"/.test(html), '不应再有 #importFullView 包装层');
check(!/\.import-collapsed/.test(html), '不应再有 .import-collapsed 原位缩小样式');

// ================= 静态: JS =================
section('静态: JS 函数与契约');
for (const n of ['collapseImportModal', 'expandImportModal', 'resetImportCollapsed',
    'updateModpackImportProgress', 'onModpackImportComplete', 'closeModpackImportModal']) {
    check(extractFunc(n) !== null, 'index.html 应含 function ' + n);
}
const col = extractFunc('collapseImportModal');
if (col) {
    check(/modpackImporting/.test(col), '收起应保留「导入开始后才能收起」门控');
    check(/导入开始后才能收起/.test(col), '收起门控应有 toast 文案');
    check(/importCollapsed = true/.test(col), '收起应置 importCollapsed 标志');
    check(/'none'/.test(col), '收起应把弹窗 display:none（窗口消失）');
    check(/downloadProgressPanel/.test(col), '收起应立即显示侧边栏下载面板');
    check(!/importMiniView/.test(col), '收起不应再切换弹窗内 mini 卡');
    check(!/import-collapsed/.test(col), '收起不应再加 import-collapsed 类');
}
const exp = extractFunc('expandImportModal');
if (exp) {
    check(/'flex'/.test(exp), '展开应恢复弹窗 display:flex');
    check(/resetImportCollapsed\(/.test(exp), '展开应经 resetImportCollapsed 重置收起态');
    check(!/import-collapsed/.test(exp), '展开不应再操作 import-collapsed 类');
}
const ric = extractFunc('resetImportCollapsed');
if (ric) {
    check(/importExpandBtn/.test(ric), 'resetImportCollapsed 应隐藏面板上的展开按钮');
    check(/importCollapsed = false/.test(ric), 'resetImportCollapsed 应清收起标志');
}
const upd = extractFunc('updateModpackImportProgress');
if (upd) {
    check(/importCollapsed/.test(upd), '进度函数应有 importCollapsed 分支（写侧边栏面板）');
    check(/downloadProgressTitle/.test(upd), '收起进度应写面板标题');
    check(/downloadProgressCount/.test(upd), '收起进度应写面板计数');
    check(/progressFill/.test(upd), '收起进度应写面板进度条');
    check(/downloadFileList/.test(upd), '收起进度应写面板文件列表');
    check(/downloadProgressPanel/.test(upd), '收起进度应强制显示面板');
    check(!/importMiniCount/.test(upd), '不应再更新已删除的 mini 卡元素');
}
const comp = extractFunc('onModpackImportComplete');
if (comp) {
    check(/expandImportModal\(/.test(comp), '完成时应自动展开弹窗（收起态也能看到结果）');
    check(/downloadProgressPanel/.test(comp), '完成时应回收侧边栏面板');
}
const close = extractFunc('closeModpackImportModal');
if (close) {
    check(/resetImportCollapsed\(/.test(close), '关闭弹窗应走 resetImportCollapsed 重置收起态');
    check(!/expandImportModal\(/.test(close), '关闭弹窗不应调 expandImportModal（会重新弹出窗口）');
}

// ================= 行为环境 =================
function buildEnv() {
    const elements = {};
    function el(id) {
        if (!elements[id]) {
            elements[id] = {
                id, innerHTML: '', value: '', textContent: '', style: {},
                classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
                dataset: {}, options: [], appendChild() {}, querySelectorAll: () => [],
                addEventListener() {}, disabled: false,
                setAttribute(k, v) { this[k] = v; }, removeAttribute(k) { delete this[k]; }
            };
        }
        return elements[id];
    }
    const documentStub = {
        getElementById: (id) => el(id),
        createElement: () => {
            const node = { className: '', innerHTML: '', style: {}, dataset: {}, appendChild() {}, classList: { add() {}, toggle() {} } };
            let text = '';
            Object.defineProperty(node, 'textContent', {
                get: () => text,
                set: (v) => {
                    text = String(v == null ? '' : v);
                    node.innerHTML = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                }
            });
            return node;
        },
        querySelectorAll: () => [],
        querySelector: () => null
    };
    const calls = { toast: [] };
    const pythonInterface = { loadVersions() {}, loadMods() {} };
    function showToast(msg, type) { calls.toast.push([msg, type]); }
    const fnNames = ['escapeHtml', 'collapseImportModal', 'expandImportModal', 'resetImportCollapsed',
        'updateModpackImportProgress', 'dlFileItemHtml', 'onModpackImportComplete',
        'closeModpackImportModal', 'resetModpackImportCancelBtn'];
    let src = `
        var modpackImporting = false;
        var importCollapsed = false;
        var pendingModpackPath = '';
        var modpackImportLastFileCount = { downloaded: 0, total: 0 };
        var modpackImportLastPct = 0;
    `;
    const missing = [];
    for (const n of fnNames) {
        const body = extractFunc(n);
        if (!body) { missing.push(n); continue; }
        src += '\n' + body + '\n';
    }
    src += `\nreturn { collapseImportModal: collapseImportModal,
        expandImportModal: expandImportModal, resetImportCollapsed: resetImportCollapsed,
        updateModpackImportProgress: updateModpackImportProgress,
        onModpackImportComplete: onModpackImportComplete,
        closeModpackImportModal: closeModpackImportModal,
        getState: function() { return { importing: modpackImporting, collapsed: importCollapsed }; },
        setImporting: function(v) { modpackImporting = v; } };`;
    ['modpackImportModal', 'importExpandBtn', 'downloadProgressPanel', 'downloadProgressTitle',
        'downloadProgressCount', 'progressFill', 'downloadFileList', 'modpackImportResult',
        'modpackImportTitle', 'modpackImportCancelBtn', 'modpackImportProgress'
    ].forEach(el);
    let api;
    try {
        api = new Function('document', 'pythonInterface', 'showToast', 'setTimeout', src)
            (documentStub, pythonInterface, showToast, function() {});
    } catch (e) {
        console.log('  ENV ERROR: ' + e.message + (missing.length ? ' missing:' + missing : ''));
        return { api: null, calls, elements, missing };
    }
    return { api, calls, elements, missing };
}

let env = buildEnv();
check(env.api !== null, '测试环境应可构建' + (env.missing ? ' 缺函数:' + env.missing : ''));

section('行为: 未导入时收起被拦截');
env = buildEnv();
if (env.api) {
    env.api.collapseImportModal();
    check(env.calls.toast.some(t => String(t[0]).indexOf('导入开始后才能收起') >= 0),
        '应提示 导入开始后才能收起');
    check(!env.elements['modpackImportModal'].style.display, '弹窗不应被隐藏');
    check(env.api.getState().collapsed === false, '不应置收起标志');
}

section('行为: 导入中收起 → 窗口消失 + 面板出现在启动按钮上方');
env = buildEnv();
if (env.api) {
    env.api.setImporting(true);
    env.elements['modpackImportModal'].style.display = 'flex';
    env.api.collapseImportModal();
    check(env.elements['modpackImportModal'].style.display === 'none',
        '收起后弹窗应 display:none, 实际 ' + env.elements['modpackImportModal'].style.display);
    check(env.elements['importExpandBtn'].style.display === 'inline-flex',
        '面板展开按钮应显示, 实际 ' + env.elements['importExpandBtn'].style.display);
    check(env.elements['downloadProgressPanel'].style.display === 'block',
        '侧边栏下载面板应显示, 实际 ' + env.elements['downloadProgressPanel'].style.display);
    check(String(env.elements['downloadProgressTitle'].textContent) === '正在导入...',
        '空标题时应回填默认文案, 实际 "' + env.elements['downloadProgressTitle'].textContent + '"');
    check(env.api.getState().collapsed === true, '应置收起标志');
}

section('行为: 收起状态下进度写入侧边栏面板');
env = buildEnv();
if (env.api) {
    env.api.setImporting(true);
    env.elements['modpackImportModal'].style.display = 'flex';
    env.api.collapseImportModal();
    env.api.updateModpackImportProgress(1, 2, '正在下载模组', 2, 5, [
        { name: 'a.jar', status: 'done', size: 100 },
        { name: 'b.jar', status: 'done', size: 100 },
        { name: 'c.jar', status: 'downloading', progress: 50, size: 100 }
    ]);
    check(String(env.elements['downloadProgressTitle'].textContent) === '正在下载模组',
        '面板标题应更新为 message, 实际 "' + env.elements['downloadProgressTitle'].textContent + '"');
    check(String(env.elements['downloadProgressCount'].textContent) === '2/5 · 50%',
        '面板计数应 2/5 · 50%, 实际 "' + env.elements['downloadProgressCount'].textContent + '"');
    check(env.elements['progressFill'].style.width === '50%',
        '面板进度条应 50%, 实际 ' + env.elements['progressFill'].style.width);
    check(env.elements['downloadFileList'].innerHTML.indexOf('c.jar') >= 0,
        '面板文件列表应含下载中文件');
    check(env.elements['downloadProgressPanel'].style.display === 'block',
        '进度 tick 应保持面板显示');
}

section('行为: 未收起时进度不写侧边栏面板');
env = buildEnv();
if (env.api) {
    env.api.updateModpackImportProgress(1, 2, 'msg', 1, 2, []);
    check(!env.elements['downloadProgressPanel'].style.display,
        '未收起不应显示/操作侧边栏面板, 实际 ' + env.elements['downloadProgressPanel'].style.display);
    check(!env.elements['downloadProgressTitle'].textContent,
        '未收起不应写面板标题');
}

section('行为: 展开恢复弹窗');
env = buildEnv();
if (env.api) {
    env.api.setImporting(true);
    env.elements['modpackImportModal'].style.display = 'flex';
    env.api.collapseImportModal();
    env.api.expandImportModal();
    check(env.elements['modpackImportModal'].style.display === 'flex',
        '展开应恢复弹窗, 实际 ' + env.elements['modpackImportModal'].style.display);
    check(env.elements['importExpandBtn'].style.display === 'none',
        '展开按钮应隐藏, 实际 ' + env.elements['importExpandBtn'].style.display);
    check(env.api.getState().collapsed === false, '展开应清收起标志');
}

section('行为: 收起状态下完成 → 自动展开并回收面板');
env = buildEnv();
if (env.api) {
    env.api.setImporting(true);
    env.elements['modpackImportModal'].style.display = 'flex';
    env.api.collapseImportModal();
    env.api.onModpackImportComplete({ success: false, error: 'boom' });
    check(env.elements['modpackImportModal'].style.display === 'flex',
        '完成后应自动展开弹窗, 实际 ' + env.elements['modpackImportModal'].style.display);
    check(env.elements['importExpandBtn'].style.display === 'none',
        '面板展开按钮应回收, 实际 ' + env.elements['importExpandBtn'].style.display);
    check(env.elements['downloadProgressPanel'].style.display === 'none',
        '侧边栏面板应收回, 实际 ' + env.elements['downloadProgressPanel'].style.display);
    check(env.api.getState().importing === false, '导入锁应释放');
    check(String(env.elements['modpackImportResult'].innerHTML).indexOf('boom') >= 0,
        '应渲染失败信息');
}

section('行为: 弹窗从未打开时完成不弹出（内置网页下载流）');
env = buildEnv();
if (env.api) {
    env.api.onModpackImportComplete({ success: true, downloaded: 1, total: 1, version_name: 'LiquidBounce' });
    check(env.elements['modpackImportModal'].style.display !== 'flex',
        '弹窗未打开过且未收起时完成不应自动弹出, 实际 ' + env.elements['modpackImportModal'].style.display);
    check(env.elements['downloadProgressPanel'].style.display === 'none' ||
        !env.elements['downloadProgressPanel'].style.display,
        '面板应保持隐藏');
    check(env.api.getState().importing === false, '导入锁应释放');
}

console.log('\nPASS: ' + pass + '  FAIL: ' + fail);
process.exit(fail ? 1 : 0);
