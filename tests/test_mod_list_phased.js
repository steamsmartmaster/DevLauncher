'use strict';
// 模组列表渐进渲染：首屏 15 条完整卡片 + 其余骨架占位 + 逐帧替换
const { extractFunc, html } = require('./extract_func.js');

let pass = 0, fail = 0;
function check(cond, msg) {
    if (cond) { pass++; } else { fail++; console.log('  FAIL: ' + msg); }
}
function section(title) { console.log('\n== ' + title + ' =='); }

const FUNCS = ['modDisplayName', 'modPlaceholderIconHtml', 'modIconHtml',
    'modInnerHtml', 'modItemHtml', 'modSameList', 'upgradeModRow',
    'upgradeModRows', 'renderModList', 'updateModIndex'];

function parseRows(html) {
    const out = [];
    const re = /<div class="([^"]*)" data-filename="([^"]*)"/g;
    let m;
    while ((m = re.exec(String(html)))) out.push({ cls: m[1], file: m[2] });
    return out;
}

function makeList() {
    function makeNode(cls, file) {
        const node = { _inner: '', className: cls, _attrs: { 'data-filename': file } };
        Object.defineProperty(node, 'innerHTML', {
            get() { return this._inner; },
            set(v) { this._inner = String(v); },
        });
        node.getAttribute = function (k) { return this._attrs[k]; };
        return node;
    }
    const list = {
        _html: '',
        scrollTop: 0,
        children: [],
    };
    list.insertAdjacentHTML = function (pos, v) {
        this._html += String(v);
        parseRows(v).forEach(function (r) { this.children.push(makeNode(r.cls, r.file)); }, this);
    };
    Object.defineProperty(list, 'innerHTML', {
        get() { return this._html; },
        set(v) {
            this._html = String(v);
            this.children = parseRows(v).map(function (r) { return makeNode(r.cls, r.file); });
        },
    });
    return list;
}

function makeCtx() {
    const modsList = makeList();
    const versionModsList = makeList();
    const lists = { modsList: modsList, versionModsList: versionModsList };
    const rafQueue = [];
    let clock = 0;
    const state = { page: 'mods', modRenderGen: 0, selectedVersion: '' };
    const prelude = `
var MOD_FIRST_BATCH = 15;
var MOD_UPGRADE_BUDGET_MS = 8;
var modRenderGen = __state.modRenderGen;
var selectedVersion = '';
var currentPage = 'mods';
var document = { getElementById: function (id) { return __lists[id] || null; } };
var performance = { now: function () { __clock.v += 1; return __clock.v; } };
var requestAnimationFrame = function (fn) { __raf.push(fn); return __raf.length; };
function escapeHtml(t) {
    return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function modActionsHtml(filename, enabled) {
    return '<button class="act" data-f="' + filename + '" data-e="' + enabled + '"></button>';
}
`;
    const factory = new Function('__lists', '__raf', '__clock', '__state',
        prelude + FUNCS.map(function (n) {
            const src = extractFunc(n);
            if (!src) throw new Error('missing function: ' + n);
            return src;
        }).join('\n') + `
return {
    renderModList: renderModList,
    updateModIndex: updateModIndex,
    modDisplayName: modDisplayName,
    modInnerHtml: modInnerHtml,
    setPage: function (p) { currentPage = p; },
    setSelected: function (v) { selectedVersion = v; },
    getGen: function () { return modRenderGen; },
    bump: function () { modRenderGen += 1; },
    doc: { getElementById: function (id) { return __lists[id] || null; } },
};`);
    const api = factory(lists, rafQueue, { v: 0 }, state);
    return { api: api, lists: lists, raf: rafQueue, state: state, setClock: function (n) { clock = n; } };
}

function makeMods(n, prefix) {
    const arr = [];
    for (let i = 0; i < n; i++) {
        arr.push({
            name: (prefix || 'Mod') + ' ' + i,
            filename: 'file-' + i + '.jar',
            enabled: i % 7 !== 0,
            version: '1.0.' + i,
            mod_id: 'mod' + i,
            icon: 'data:image/png;base64,AAAA',
        });
    }
    return arr;
}

function rowsOf(listHtml) {
    return String(listHtml).split('<div class="mod-item').slice(1);
}

function drain(raf, limit) {
    let frames = 0;
    while (raf.length && frames < (limit || 400)) {
        const batch = raf.splice(0, raf.length);
        batch.forEach(function (fn) { fn(); });
        frames++;
    }
    return frames;
}

section('source: 15 条首屏 + 骨架 + 逐帧升级');
check(/var MOD_FIRST_BATCH = 15;/.test(html), '应定义 MOD_FIRST_BATCH = 15');
check(html.includes('mod-placeholder') || html.includes('modPlaceholderIconHtml'), '应有占位图标');
check(html.includes('mod-pending'), '骨架行应带 mod-pending');
check(html.includes('requestAnimationFrame(frame)'), '追加与升级应走 requestAnimationFrame');
check(html.includes("insertAdjacentHTML('beforeend', buf)"), '骨架行应分帧追加');
check(html.includes('if (gen !== modRenderGen) return;'), '升级应带代次保护');
check(html.includes('function updateModIndex(index)'), '应提供 updateModIndex');

section('renderModList: 300 个模组');
const c1 = makeCtx();
c1.api.renderModList(makeMods(300), 'modsList');
let rows1 = rowsOf(c1.lists.modsList.innerHTML);
check(rows1.length === 15, '首帧只插入 15 行, got ' + rows1.length);
check(c1.lists.modsList.children.length === 15, '首帧 DOM 只有 15 个节点');
let headOk = true;
for (let i = 0; i < 15; i++) {
    if (!rows1[i].includes('Mod ' + i)) headOk = false;
    if (!rows1[i].includes('data:image/png;base64')) headOk = false;
}
check(headOk, '前 15 行无需等待即带真实名称与图标');
check(c1.raf.length === 1, '剩余行应排队到下一帧, got ' + c1.raf.length);

c1.raf.splice(0, c1.raf.length).forEach(function (fn) { fn(); });
const midRows = rowsOf(c1.lists.modsList.innerHTML);
check(midRows.length > 15 && midRows.length < 300, '骨架应分帧追加, got ' + midRows.length);
const lastSkeleton = midRows[midRows.length - 1];
check(lastSkeleton.includes('file-' + (midRows.length - 1) + '.jar'), '骨架行应显示文件名');
check(!lastSkeleton.includes('<img'), '骨架行不应加载图标 <img>');
check(lastSkeleton.includes('mod-pending'), '骨架行应带 mod-pending');

const frames1 = drain(c1.raf);
check(c1.lists.modsList.children.length === 300, '最终应有 300 个节点');
let allFull = true;
for (let i = 15; i < 300; i++) {
    if (!c1.lists.modsList.children[i]._inner.includes('Mod ' + i)) allFull = false;
    if (!c1.lists.modsList.children[i]._inner.includes('<img')) allFull = false;
}
check(allFull, '第 16 行起最终应替换为完整内容, frames=' + frames1);
check(c1.lists.modsList.children[15]._inner.indexOf('file-15.jar') > 0, '顺序应保持: 第 16 行是 file-15.jar');
check(c1.lists.modsList.children[299]._inner.includes('Mod 299'), '最后一行应升级到 Mod 299');

section('renderModList: 少于 15 个模组');
const c2 = makeCtx();
c2.api.renderModList(makeMods(7, 'Small'), 'modsList');
const rows2 = rowsOf(c2.lists.modsList.innerHTML);
check(rows2.length === 7, '应生成 7 行');
check(c2.raf.length === 0, '不足 15 行时不应排队升级');
check(rows2[6].includes('Small 6') && rows2[6].includes('<img'), '7 个模组应全部完整渲染');

section('renderModList: 空列表');
const c3 = makeCtx();
c3.api.renderModList([], 'modsList');
check(c3.lists.modsList.innerHTML.includes('进'.replace('进', '尚未安装')), '空列表应显示占位文案');
check(c3.raf.length === 0, '空列表不应排队');

section('代次保护: 重新渲染后旧帧失效');
const c4 = makeCtx();
c4.api.renderModList(makeMods(60, 'Old'), 'modsList');
const staleFrame = c4.raf.shift();
c4.api.renderModList(makeMods(60, 'New'), 'modsList');
staleFrame();
check(c4.lists.modsList.children.length === 15, '旧帧不应追加骨架, got ' + c4.lists.modsList.children.length);
check(c4.api.getGen() === 2, '代次应递增到 2, got ' + c4.api.getGen());
drain(c4.raf);
check(c4.lists.modsList.children[20]._inner.includes('New 20'), '新代次应在自己帧内完成升级');

section('滚动位置保持');
const c5 = makeCtx();
c5.lists.modsList.scrollTop = 120;
c5.lists.modsList.innerHTML = '<div class="mod-item">old</div>';
c5.lists.modsList.scrollTop = 240;
c5.api.renderModList(makeMods(40), 'modsList');
check(c5.lists.modsList.scrollTop === 240, '重渲染后应保持 scrollTop, got ' + c5.lists.modsList.scrollTop);

section('updateModIndex: 立即画骨架');
const c6 = makeCtx();
c6.state.page = 'mods';
c6.api.setPage('mods');
c6.api.updateModIndex([
    { filename: 'alpha.jar', enabled: true },
    { filename: 'beta.jar.disabled', enabled: false },
    { filename: 'gamma.jar', enabled: true },
]);
const rows6 = rowsOf(c6.lists.modsList.innerHTML);
check(rows6.length === 3, '应生成 3 行骨架, got ' + rows6.length);
check(rows6[0].includes('alpha.jar') && rows6[0].includes('alpha'), '骨架应显示文件名');
check(!rows6[0].includes('<img'), '骨架不应含 <img>');
check(rows6[1].includes('mod-disabled'), '禁用模组骨架应带 mod-disabled');
check(rows6[0].includes('mod-pending'), '骨架应带 mod-pending');
check(c6.raf.length === 0, '骨架渲染不应排队升级');

section('updateModIndex: 页面不匹配时忽略');
const c7 = makeCtx();
c7.api.setPage('versions');
c7.api.updateModIndex([{ filename: 'zeta.jar', enabled: true }]);
check(c7.lists.modsList.innerHTML === '', '非模组页不应渲染');
check(c7.lists.versionModsList.innerHTML === '', '非模组页不应渲染到版本模组列表');
c7.api.setPage('versionMods');
c7.api.updateModIndex([{ filename: 'zeta.jar', enabled: true }]);
check(rowsOf(c7.lists.versionModsList.innerHTML).length === 1, '版本模组页应渲染到 versionModsList');

section('骨架升级后不保留 pending 样式（颜色一致）');
const c9 = makeCtx();
c9.api.renderModList(makeMods(40), 'modsList');
drain(c9.raf);
let pendingLeft = 0;
for (let i = 0; i < c9.lists.modsList.children.length; i++) {
    if (c9.lists.modsList.children[i].className.indexOf('mod-pending') >= 0) pendingLeft++;
}
check(pendingLeft === 0, '升级后仍有 ' + pendingLeft + ' 行保留 mod-pending');
check(c9.lists.modsList.children[30]._inner.includes('Mod 30'), '升级内容应写回原节点');

section('索引骨架 + 完整列表：复用节点，不整表重建');
const c10 = makeCtx();
c10.api.setPage('mods');
const mods10 = makeMods(40, 'Reuse');
c10.api.updateModIndex(mods10.map(function (m) {
    return { filename: m.filename, enabled: m.enabled };
}));
const snapshot = c10.lists.modsList.children.slice();
const beforeHtml = c10.lists.modsList.innerHTML;
check(snapshot.length === 40, '索引应先铺 40 行骨架');
c10.api.renderModList(mods10, 'modsList');
check(c10.lists.modsList.children.length === 40, '完整列表不应重复插入');
check(c10.lists.modsList.children[0] === snapshot[0], '应复用已有骨架节点');
check(c10.lists.modsList.innerHTML === beforeHtml, '复用路径不应重写列表 HTML');
drain(c10.raf);
check(c10.lists.modsList.children[0]._inner.includes('Reuse 0'), '复用节点应被升级');
check(c10.lists.modsList.children[39]._inner.includes('Reuse 39'), '末行也应升级');
let pending10 = 0;
for (let i = 0; i < 40; i++) {
    if (c10.lists.modsList.children[i].className.indexOf('mod-pending') >= 0) pending10++;
}
check(pending10 === 0, '复用升级后无 pending 样式, left=' + pending10);

section('已完成列表再次渲染：零 DOM 工作');
const c12 = makeCtx();
c12.api.setPage('mods');
const mods12 = makeMods(30, 'Again');
c12.api.updateModIndex(mods12.map(function (m) {
    return { filename: m.filename, enabled: m.enabled };
}));
c12.api.renderModList(mods12, 'modsList');
drain(c12.raf);
const html12 = c12.lists.modsList.innerHTML;
const nodes12 = c12.lists.modsList.children.slice();
const inner12 = nodes12.map(function (n) { return n._inner; });
c12.api.renderModList(mods12, 'modsList');
check(c12.raf.length === 0, '重复进入页面不应再排队升级, got ' + c12.raf.length);
check(c12.lists.modsList.innerHTML === html12, '重复渲染不应改动列表 HTML');
check(c12.lists.modsList.children.every(function (n, i) { return n === nodes12[i]; }), '节点应完全复用');
check(c12.lists.modsList.children[0]._inner === inner12[0], '已完成行不应被重写');

section('复用路径保持滚动位置');
const c11 = makeCtx();
c11.api.setPage('mods');
const mods11 = makeMods(40, 'Scroll');
c11.api.updateModIndex(mods11.map(function (m) {
    return { filename: m.filename, enabled: m.enabled };
}));
c11.lists.modsList.scrollTop = 360;
c11.api.renderModList(mods11, 'modsList');
check(c11.lists.modsList.scrollTop === 360, '复用后 scrollTop 应保持, got ' + c11.lists.modsList.scrollTop);

section('文件名 => 显示名');
const c8 = makeCtx();
check(c8.api.modDisplayName('sodium-fabric-0.5.8.jar') === 'sodium-fabric-0.5.8', '应去掉 .jar');
check(c8.api.modDisplayName('sodium.jar.disabled') === 'sodium', '应去掉 .disabled');
check(c8.api.modDisplayName('') === '', '空文件名应安全');

console.log('\n通过: ' + pass + ' / 失败: ' + fail);
process.exit(fail === 0 ? 0 : 1);
