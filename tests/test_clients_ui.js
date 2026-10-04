// 下载页「客户端」子页签：目录渲染 / 新卡片排版 / 类型与分类筛选 / 选版本下载流程 / 打开页面
// 红→绿 TDD
const fs = require('fs');
const path = require('path');
const { extractFunc, html } = require('./extract_func.js');

let pass = 0, fail = 0;
function check(cond, msg) { if (cond) pass++; else { fail++; console.log('  FAIL: ' + msg); } }
function section(t) { console.log('\n== ' + t + ' =='); }
const py = fs.readFileSync(path.join(__dirname, '..', 'main.py'), 'utf8');

// ================= 静态: HTML =================
section('静态: 页签与容器');
check(/data-dl-tab="clients"/.test(html), 'download-tabs 应有 data-dl-tab="clients" 按钮');
check(/id="dlClients"/.test(html), '应有 #dlClients 内容容器');
check(/id="clientsResults"/.test(html), '应有 #clientsResults 结果网格');
check(/id="clientSearch"/.test(html), '应有 #clientSearch 搜索框');
check(/data-ctype="pack"/.test(html), '应有 pack 类型筛选 chip');

section('静态: JS 函数');
const REQUIRED = ['loadClients', 'renderClientList', 'setClientFilter', 'filterClients',
    'clientCardHtml', 'downloadClient', 'downloadClientWithPicker', 'openClientSite',
    'onClientDownloadFinished', 'openVersionPicker', 'closeVersionPicker', 'pickModVersion'];
for (const n of REQUIRED) {
    check(extractFunc(n) !== null, 'index.html 应含 function ' + n);
}
check(/pythonInterface\.getClients\(/.test(html), '应调 pythonInterface.getClients');
check(/pythonInterface\.downloadClientVersion\(/.test(html), '应调 pythonInterface.downloadClientVersion');
check(/pythonInterface\.openClientSite\(/.test(html), '应调 pythonInterface.openClientSite');

section('静态: openVersionPicker 客户端分支');
const ovp = extractFunc('openVersionPicker');
check(ovp !== null, 'openVersionPicker 应存在');
if (ovp) {
    check(/contentType === 'clients'/.test(ovp), "openVersionPicker 应有 contentType==='clients' 分支");
    check(/getClientVersions\(/.test(ovp), '客户端分支应调 getClientVersions');
    check(/getModpackVersions\(/.test(ovp), '包条目应复用 getModpackVersions');
}

section('静态: 卡片新排版（图标+名称 / 描述 / 右下按钮）');
const cch = extractFunc('clientCardHtml');
check(cch !== null, 'clientCardHtml 应存在');
if (cch) {
    check(/client-card-top/.test(cch), '卡片应有 client-card-top 头部行');
    check(/client-icon/.test(cch), '卡片应有 client-icon 图标区');
    check(/client-icon-fallback/.test(cch), '图标应有字母兜底 fallback');
    check(/c\.category/.test(cch), '卡片应渲染 category 徽章');
    check(/downloadClientWithPicker/.test(cch), '下载按钮应接 downloadClientWithPicker');
    check(/打开页面/.test(cch), 'open_page 条目应显示 打开页面');
}
check(/\.client-icon\s*\{/.test(html), 'CSS 应有 .client-icon 定义');

section('静态: downloadClientWithPicker 流程');
const dcwp = extractFunc('downloadClientWithPicker');
check(dcwp !== null, 'downloadClientWithPicker 应存在');
if (dcwp) {
    check(/openVersionPicker\(/.test(dcwp), '应打开版本选择器');
    check(/'clients'/.test(dcwp), '客户端条目应走 clients 分支');
    check(/'modpacks'/.test(dcwp), '包条目应走 modpacks 分支');
    check(/downloadClientVersion\(/.test(dcwp), '选中版本后应调 downloadClientVersion');
}

section('静态: switchDownloadTab 特判 clients');
const sw = extractFunc('switchDownloadTab');
check(sw !== null, 'switchDownloadTab 应存在');
if (sw) {
    check(/tab === 'clients'/.test(sw) && /loadClients\(\)/.test(sw), '首开 clients 应走 loadClients 而非 trending');
}

section('静态: main.py 槽/信号/接线');
check(/clientsLoaded\s*=\s*pyqtSignal\(str\)/.test(py), '应有 clientsLoaded 信号');
check(/clientDownloadFinished\s*=\s*pyqtSignal\(str\)/.test(py), '应有 clientDownloadFinished 信号');
check(/def getClients\(self\)/.test(py), '应有 getClients 槽');
check(/def downloadClient\(self, client_id: str\)/.test(py), '应有 downloadClient(client_id) 槽');
check(/def getClientVersions\(self, client_id: str\)/.test(py), '应有 getClientVersions(client_id) 槽');
check(/def downloadClientVersion\(self, client_id: str, version_id: str, custom_name: str\)/.test(py),
    '应有 downloadClientVersion(client_id, version_id, custom_name) 槽');
check(/def openClientSite\(self, url: str\)/.test(py), '应有 openClientSite(url) 槽');
check(/self\.bridge\.clientsLoaded\.connect\(self\._on_clients_loaded\)/.test(py), 'clientsLoaded 应接线 _on_clients_loaded');
check(/self\.bridge\.clientDownloadFinished\.connect\(self\._on_client_download_finished\)/.test(py), 'clientDownloadFinished 应接线');
const gcv = py.match(/def getClientVersions\(self[\s\S]{0,700}/);
check(gcv !== null && gcv[0].indexOf('modVersions.emit') >= 0,
    'getClientVersions 应复用 modVersions 信号（updateModVersions 渲染）');
const dcv = py.match(/def downloadClientVersion\(self[\s\S]{0,3500}/);
check(dcv !== null && dcv[0].indexOf('meteor_api.get_jar') >= 0, 'downloadClientVersion 应含 meteor_api.get_jar');
check(dcv !== null && dcv[0].indexOf('downloadModpackVersion(') >= 0, 'downloadClientVersion 应委托 downloadModpackVersion 下整合包');
const ocl = py.match(/def _on_clients_loaded\(self[\s\S]{0,300}/);
check(ocl !== null && ocl[0].indexOf('renderClientList(') >= 0, '_on_clients_loaded 应 runJavaScript renderClientList(');
const ocdf = py.match(/def _on_client_download_finished\(self[\s\S]{0,300}/);
check(ocdf !== null && ocdf[0].indexOf('onClientDownloadFinished(') >= 0, '_on_client_download_finished 应注入 onClientDownloadFinished(');
check(fs.existsSync(path.join(__dirname, '..', 'launcher_core', 'clients_catalog.py')), 'clients_catalog.py 应存在');
check(fs.existsSync(path.join(__dirname, '..', 'launcher_core', 'api_github.py')), 'api_github.py 应存在');
check(fs.existsSync(path.join(__dirname, '..', 'launcher_core', 'api_meteor.py')), 'api_meteor.py 应存在');

// ================= 行为环境 =================
function buildEnv() {
    const elements = {};
    function el(id) {
        if (!elements[id]) {
            elements[id] = {
                id, innerHTML: '', value: '', textContent: '', style: {},
                classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
                dataset: {}, options: [], appendChild() {}, querySelectorAll: () => [],
                addEventListener() {}, disabled: false
            };
        }
        return elements[id];
    }
    const documentStub = {
        getElementById: (id) => el(id),
        createElement: () => {
            const node = { className: '', innerHTML: '', style: {}, dataset: {}, appendChild() {}, classList: { add() {}, toggle() {} } };
            let text = '';
            // 真实 escapeHtml 用 textContent→innerHTML 转义（浏览器行为），测试环境需等价模拟
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
    const calls = {
        getClients: [], downloadClient: [], downloadClientVersion: [], openClientSite: [],
        getClientVersions: [], getModpackVersions: [], toast: []
    };
    const pythonInterface = {
        getClients: (...a) => calls.getClients.push(a),
        downloadClient: (...a) => calls.downloadClient.push(a),
        downloadClientVersion: (...a) => calls.downloadClientVersion.push(a),
        openClientSite: (...a) => calls.openClientSite.push(a),
        getClientVersions: (...a) => calls.getClientVersions.push(a),
        getModpackVersions: (...a) => calls.getModpackVersions.push(a),
        searchMods: () => {}
    };
    function showToast(msg, type) { calls.toast.push([msg, type]); }
    const fnNames = ['escapeHtml', 'escapeAttr', 'loadClients', 'renderClientList', 'setClientFilter', 'filterClients',
        'clientCardHtml', 'downloadClient', 'downloadClientWithPicker', 'openClientSite',
        'onClientDownloadFinished', 'openVersionPicker', 'closeVersionPicker', 'pickModVersion'];
    let src = `
        var clientsData = [];
        var clientsType = 'all';
        var clientsQuery = '';
        var clientsDownloading = {};
        var clientsDownloaded = {};
        var versionPickerCallback = null;
        var versionPickerData = [];
    `;
    const missing = [];
    for (const n of fnNames) {
        const body = extractFunc(n);
        if (!body) { missing.push(n); continue; }
        src += '\n' + body + '\n';
    }
    src += `\nreturn { loadClients: loadClients, renderClientList: renderClientList,
        setClientFilter: setClientFilter, filterClients: filterClients,
        downloadClient: downloadClient, downloadClientWithPicker: downloadClientWithPicker,
        openClientSite: openClientSite, onClientDownloadFinished: onClientDownloadFinished,
        openVersionPicker: openVersionPicker, pickModVersion: pickModVersion,
        getClientsState: function(){ return { data: clientsData, type: clientsType,
            downloading: clientsDownloading, downloaded: clientsDownloaded,
            pickerCbSet: versionPickerCallback !== null }; } };`;
    let api;
    try {
        api = new Function('document', 'pythonInterface', 'showToast', src)
            (documentStub, pythonInterface, showToast);
    } catch (e) {
        console.log('  ENV ERROR: ' + e.message + (missing.length ? ' missing:' + missing : ''));
        return { api: null, calls, elements, missing };
    }
    return { api, calls, elements, missing };
}

const CAT = [
    { id: 'meteor', name: 'Meteor Client', type: 'client', category: '作弊-综合', platform: 'web', endpoint: 'https://meteorclient.com/api/download', strategy: 'meteor_download', kind: 'jar', note: '官网直下', icon: 'https://github.com/MeteorDevelopment.png?size=128' },
    { id: 'bleachhack', name: 'BleachHack', type: 'client', category: '作弊-综合', platform: 'github', endpoint: 'BleachDev/BleachHack', strategy: 'github_latest_jar', kind: 'jar', note: '多版本 jar', icon: 'https://github.com/BleachDev.png?size=128' },
    { id: 'optix', name: 'Optix Client', type: 'client', category: 'PVP-竞技', platform: 'modrinth', endpoint: 'optixclient', strategy: 'modrinth_latest_jar', kind: 'jar', note: 'PVP 竞技', icon: '' },
    { id: 'payload', name: 'Payload Utility Mod', type: 'client', category: '作弊-辅助', platform: 'web', endpoint: 'https://github.com/franktheory/Payload-Utility-Mod', strategy: 'open_page', kind: 'page', note: '打开仓库页', icon: '' },
    { id: 'spunky-pvp-plus', name: 'Spunky PVP Plus', type: 'pack', category: '', platform: 'modrinth', endpoint: 'spunky-pvp-plus', strategy: 'modrinth_modpack', kind: 'modpack', note: 'PVP 整合包', icon: '' },
    { id: 'ath', name: 'All The Hacks (ATH)', type: 'pack', category: '', platform: 'web', endpoint: 'https://www.modpackindex.com/modpack/149934/all-the-hacks-ath', strategy: 'open_page', kind: 'page', note: 'Modpack Index 页面', icon: '' }
];
function mkCatalog() {
    // 13 client + 6 pack（与真实目录同构）
    const list = [];
    const cli = CAT.filter(c => c.type === 'client');
    const pks = CAT.filter(c => c.type === 'pack');
    for (let i = 0; i < 13; i++) {
        list.push(i < cli.length ? cli[i]
            : { id: 'client' + i, name: 'Client ' + i, type: 'client', category: '', platform: 'modrinth', endpoint: 'slug' + i, strategy: 'modrinth_latest_jar', kind: 'jar', note: '', icon: '' });
    }
    for (let i = 0; i < 6; i++) {
        list.push(i < pks.length ? pks[i]
            : { id: 'pack' + i, name: 'Pack ' + i, type: 'pack', category: '', platform: 'modrinth', endpoint: 'pk' + i, strategy: 'modrinth_modpack', kind: 'modpack', note: '', icon: '' });
    }
    return list;
}

section('行为: loadClients');
let env = buildEnv();
check(env.api !== null, '测试环境应可构建' + (env.missing ? ' 缺函数:' + env.missing : ''));
if (env.api) {
    env.api.loadClients();
    check(env.calls.getClients.length === 1, 'loadClients 应调 getClients');
    check(env.elements['clientsResults'].innerHTML.indexOf('加载') >= 0, '应先显示加载占位');
}

section('行为: renderClientList 渲染 19 卡 + 新排版');
env = buildEnv();
if (env.api) {
    env.api.renderClientList(mkCatalog());
    const box = env.elements['clientsResults'];
    const htmlOut = box.innerHTML;
    const cards = (htmlOut.match(/data-client-id=/g) || []).length;
    check(cards === 19, '应渲染 19 张卡, 实际 ' + cards);
    check(htmlOut.indexOf('client-card-top') >= 0 && htmlOut.indexOf('client-icon') >= 0, '卡片应有新排版结构');
    check(htmlOut.indexOf('<img class="client-icon-img" src="https://github.com/MeteorDevelopment.png') >= 0, '有 icon 条目应渲染 img');
    const athSeg = htmlOut.split('data-client-id="ath"')[1] || '';
    check(athSeg.slice(0, 400).indexOf('client-icon-img') < 0, 'icon 为空条目不应渲染 img');
    check(htmlOut.indexOf('client-icon-fallback') >= 0, '应有字母兜底 fallback');
    check(htmlOut.indexOf('作弊-综合') >= 0, '应渲染 category 徽章');
    check(htmlOut.indexOf('Meteor Client') >= 0 && htmlOut.indexOf('ATH') >= 0, '应含 Meteor Client 与 ATH');
    check(htmlOut.indexOf('打开页面') >= 0, 'open_page 条目应显示 打开页面');
    check(htmlOut.indexOf('openClientSite') >= 0, '打开页面应接 openClientSite');
    check(htmlOut.indexOf('downloadClientWithPicker') >= 0, '下载按钮应接 downloadClientWithPicker');
}

section('行为: 类型筛选');
env = buildEnv();
if (env.api) {
    env.api.renderClientList(mkCatalog());
    env.api.setClientFilter('pack');
    let cards = (env.elements['clientsResults'].innerHTML.match(/data-client-id=/g) || []).length;
    check(cards === 6, 'pack 筛选应 6 卡, 实际 ' + cards);
    env.api.setClientFilter('client');
    cards = (env.elements['clientsResults'].innerHTML.match(/data-client-id=/g) || []).length;
    check(cards === 13, 'client 筛选应 13 卡, 实际 ' + cards);
    env.api.setClientFilter('all');
    cards = (env.elements['clientsResults'].innerHTML.match(/data-client-id=/g) || []).length;
    check(cards === 19, 'all 应回 19 卡, 实际 ' + cards);
}

section('行为: 搜索过滤（名称 + 分类）');
env = buildEnv();
if (env.api) {
    env.api.renderClientList(mkCatalog());
    env.elements['clientSearch'].value = 'bleachhack';
    env.api.filterClients();
    const htmlOut = env.elements['clientsResults'].innerHTML;
    const cards = (htmlOut.match(/data-client-id=/g) || []).length;
    check(cards === 1 && htmlOut.indexOf('BleachHack') >= 0, '搜索 bleachhack 应只剩 1 卡, 实际 ' + cards);
    env.elements['clientSearch'].value = '作弊';
    env.api.filterClients();
    const catCards = (env.elements['clientsResults'].innerHTML.match(/data-client-id=/g) || []).length;
    check(catCards === 3, '按分类「作弊」应命中 3 卡 (meteor/bleachhack/payload), 实际 ' + catCards);
    env.elements['clientSearch'].value = 'zzz-not-found';
    env.api.filterClients();
    const cards2 = (env.elements['clientsResults'].innerHTML.match(/data-client-id=/g) || []).length;
    check(cards2 === 0, '无匹配应 0 卡');
    check(env.elements['clientsResults'].innerHTML.indexOf('没有匹配') >= 0, '无匹配应有空态文案');
}

section('行为: 选版本流程（客户端 → clients 分支）');
env = buildEnv();
if (env.api) {
    env.api.renderClientList(mkCatalog());
    env.api.downloadClientWithPicker('meteor');
    check(env.calls.getClientVersions.length === 1 && env.calls.getClientVersions[0][0] === 'meteor',
        '客户端条目应调 getClientVersions(id), 实际 ' + JSON.stringify(env.calls.getClientVersions));
    check(env.api.getClientsState().pickerCbSet === true, '打开选择器应登记回调');
    env.api.pickModVersion('1.21.11', '1.21.11 - 86');
    check(env.calls.downloadClientVersion.length === 1 &&
        env.calls.downloadClientVersion[0][0] === 'meteor' &&
        env.calls.downloadClientVersion[0][1] === '1.21.11',
        '选中版本应调 downloadClientVersion(id, versionId), 实际 ' + JSON.stringify(env.calls.downloadClientVersion));
    check(env.api.getClientsState().downloading['meteor'] === true, '选版本后应进入下载中');
    check(env.elements['clientsResults'].innerHTML.indexOf('下载中') >= 0, '卡片应显示 下载中');
    check(env.api.getClientsState().pickerCbSet === false, '选择后应清空回调');
}

section('行为: 选版本流程（整合包 → modpacks 分支）');
env = buildEnv();
if (env.api) {
    env.api.renderClientList(mkCatalog());
    env.api.downloadClientWithPicker('spunky-pvp-plus');
    check(env.calls.getModpackVersions.length === 1 &&
        env.calls.getModpackVersions[0][0] === 'spunky-pvp-plus' &&
        env.calls.getModpackVersions[0][1] === 'modrinth',
        '包条目应调 getModpackVersions(id, source), 实际 ' + JSON.stringify(env.calls.getModpackVersions));
    env.api.pickModVersion('ver-uuid-1', 'v1.0');
    check(env.calls.downloadClientVersion.length === 1 &&
        env.calls.downloadClientVersion[0][0] === 'spunky-pvp-plus' &&
        env.calls.downloadClientVersion[0][1] === 'ver-uuid-1',
        '包选版本后应调 downloadClientVersion, 实际 ' + JSON.stringify(env.calls.downloadClientVersion));
    check(!env.api.getClientsState().downloading['spunky-pvp-plus'], '包下载不设卡片下载中态（安装由全局进度提示）');
}

section('行为: open_page 安全分支');
env = buildEnv();
if (env.api) {
    env.api.renderClientList(mkCatalog());
    env.api.downloadClientWithPicker('ath');
    check(env.calls.openClientSite.length === 1 && env.calls.openClientSite[0][0].indexOf('modpackindex.com') >= 0,
        'open_page 条目经此入口应直接 openClientSite, 实际 ' + JSON.stringify(env.calls.openClientSite));
    check(env.calls.getClientVersions.length === 0 && env.calls.getModpackVersions.length === 0,
        'open_page 不应拉版本列表');
}

section('行为: downloadClient 快速下载（latest 直下）');
env = buildEnv();
if (env.api) {
    env.api.renderClientList(mkCatalog());
    env.api.downloadClient('bleachhack');
    check(env.calls.downloadClient.length === 1 && env.calls.downloadClient[0][0] === 'bleachhack',
        '应调 pythonInterface.downloadClient(id)');
    check(env.elements['clientsResults'].innerHTML.indexOf('下载中') >= 0, '下载中卡片应显示 下载中');
}

section('行为: 下载完成态');
env = buildEnv();
if (env.api) {
    env.api.renderClientList(mkCatalog());
    env.api.downloadClient('bleachhack');
    env.api.onClientDownloadFinished({ id: 'bleachhack', ok: true, message: '已保存 bleachhack-1.19.4.jar' });
    const html2 = env.elements['clientsResults'].innerHTML;
    check(html2.indexOf('已下载') >= 0, '完成后卡片应标记 已下载');
    check(env.calls.toast.some(t => t[0].indexOf('bleachhack-1.19.4.jar') >= 0), '应 toast 文件名');
    check(!env.api.getClientsState().downloading['bleachhack'], '下载中状态应清除');
    env.api.onClientDownloadFinished({ id: 'meteor', ok: false, message: '网络错误' });
    check(env.calls.toast.some(t => t[1] === 'error'), '失败应 error toast');
    check(!env.api.getClientsState().downloaded['meteor'], '失败不应标记已下载');
}

section('行为: openClientSite');
env = buildEnv();
if (env.api) {
    env.api.openClientSite('https://aresclient.org/');
    check(env.calls.openClientSite.length === 1 && env.calls.openClientSite[0][0] === 'https://aresclient.org/', '应透传 url');
}

console.log('\nPASS: ' + pass + '  FAIL: ' + fail);
process.exit(fail ? 1 : 0);
