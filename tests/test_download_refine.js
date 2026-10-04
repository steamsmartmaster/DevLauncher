// 下载页细化：模组筛选面板（类别/加载器/安装环境/游戏版本）+ 版本卡片右下角加载器图标
// 红→绿 TDD：先断言期望结构，实现后转 GREEN
const fs = require('fs');
const path = require('path');
const { extractFunc, html } = require('./extract_func.js');

let pass = 0, fail = 0;
function check(cond, msg) {
    if (cond) { pass++; } else { fail++; console.log('  FAIL: ' + msg); }
}
function section(title) { console.log('\n== ' + title + ' =='); }

// ================= 静态结构 =================
section('静态: 面板结构');
check(/id="modFilterPanel"/.test(html), 'index.html 应含 id="modFilterPanel"');
check(/id="mfCatList"/.test(html) && /id="mfLoaderList"/.test(html), '应含类别/加载器容器');
check(/id="mfEnvList"/.test(html) && /id="mfVersionList"/.test(html), '应含安装环境/游戏版本容器');
check(/id="mfCatMore"/.test(html) && /id="mfVersionMore"/.test(html), '应含类别/版本 查看剩余按钮');
check(/class="mod-filter-layout"/.test(html), '应含 mod-filter-layout 两列布局');
check(/清除筛选/.test(html), '应含清除筛选入口');
check(!/id="modGameVersion"/.test(html), '旧 modGameVersion 下拉应被移除');
check(!/id="modLoaderFilter"/.test(html), '旧 modLoaderFilter 下拉应被移除');

section('静态: CSS');
check(/\.mod-filter-panel\s*\{/.test(html), '应有 .mod-filter-panel 样式');
check(/\.mf-chip\s*\{/.test(html), '应有 .mf-chip 样式');
check(/\.mf-chip\.active\s*\{/.test(html), '应有 .mf-chip.active 样式');
check(/\.version-loader-icon\s*\{/.test(html), '应有 .version-loader-icon 样式');
check(/position:\s*absolute/.test((html.match(/\.version-loader-icon\s*\{[^}]*\}/) || [''])[0]), 'version-loader-icon 应绝对定位');
check((html.match(/\.version-card\s*\{[^}]*\}/) || ['']).join('').indexOf('position: relative') >= 0, '.version-card 应 position:relative');

section('静态: 函数存在');
const REQUIRED = [
    'toggleModFilter', 'toggleMfExpand', 'clearModFilters', 'getModFilterCsv',
    'hasModFilters', 'renderModFilterPanel'
];
for (const n of REQUIRED) {
    check(extractFunc(n) !== null, 'index.html 应含 function ' + n);
}
check(/pythonInterface\.searchMods\(/.test(html), '应调 pythonInterface.searchMods');
check(/static\/icons\/cat\//.test(html), '类别图标应引用 static/icons/cat/');
check(/static\/icons\/loaders\//.test(html), '加载器图标应引用 static/icons/loaders/');
check(/static\/icons\/grass_block\.png/.test(html), '原版应引用 grass_block.png');
check(/static\/icons\/env\/client\.svg/.test(html), '环境图标应引用 env/client.svg');

// ================= 数据声明求值 =================
section('数据: MF_CATEGORIES/LOADERS/ENV');
function evalDecl(name) {
    const m = html.match(new RegExp('(?:var|let|const)\\s+' + name + '\\s*=\\s*(\\[[\\s\\S]*?\\]);'));
    if (!m) return null;
    try { return new Function('return ' + m[1])(); } catch (e) { return null; }
}
const cats = evalDecl('MF_CATEGORIES');
check(Array.isArray(cats) && cats.length === 19, 'MF_CATEGORIES 应 19 项, 实际 ' + (cats ? cats.length : 'missing'));
if (Array.isArray(cats)) {
    const slugs = cats.map(c => c.slug);
    check(slugs[0] === 'adventure' && slugs[5] === 'food', '前 6 应为 adventure..food');
    check(slugs.includes('worldgen') && slugs.includes('utility'), '应含 worldgen/utility');
    check(cats.every(c => c.icon.indexOf('static/icons/cat/') === 0), '类别图标路径应 static/icons/cat/');
}
const loaders = evalDecl('MF_LOADERS');
check(Array.isArray(loaders) && loaders.length === 4, 'MF_LOADERS 应 4 项');
if (Array.isArray(loaders)) {
    check(loaders.map(l => l.slug).join(',') === 'fabric,forge,neoforge,quilt', '加载器顺序 fabric,forge,neoforge,quilt');
    check(loaders.every(l => l.icon.indexOf('static/icons/loaders/') === 0), '加载器图标路径应 static/icons/loaders/');
}
const envs = evalDecl('MF_ENVS');
check(Array.isArray(envs) && envs.length === 2, 'MF_ENVS 应 2 项');
if (Array.isArray(envs)) {
    check(envs[0].slug === 'client' && envs[1].slug === 'server', '环境应 client,server');
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
                addEventListener() {}
            };
        }
        return elements[id];
    }
    const documentStub = {
        getElementById: (id) => {
            if (id === 'modSearch') return el('modSearch');
            return el(id);
        },
        createElement: () => ({ className: '', innerHTML: '', style: {}, dataset: {}, appendChild() {}, classList: { add() {}, toggle() {} } }),
        querySelectorAll: () => [],
        querySelector: () => null
    };
    const calls = { searchMods: [], searchContentFiltered: [], trending: [], toast: [] };
    const pythonInterface = {
        searchMods: (...a) => calls.searchMods.push(a),
        searchContentFiltered: (...a) => calls.searchContentFiltered.push(a),
        loadTrendingContent: (...a) => calls.trending.push(a)
    };
    function showToast(msg, type) { calls.toast.push([msg, type]); }
    function getCurrentSource() { return 'modrinth'; }
    const preamble = `
        var modFilters = { categories: [], loaders: [], environments: [], versions: [] };
        var mfExpanded = { categories: false, loaders: false, environments: false, versions: false };
        var mfVersionsList = ['26.3', '26.2', '1.21.11', '1.21.10', '1.21.9', '1.21.8', '1.21.7', '1.21.6', '1.21.5', '1.20.1'];
        var MF_SHOWN = { categories: 6, loaders: 4, environments: 2, versions: 8 };
        var selectedVersion = '';
        var versions = [];
        var currentFilter = 'all';
    `;
    const fnNames = ['toggleModFilter', 'toggleMfExpand', 'clearModFilters', 'getModFilterCsv',
        'hasModFilters', 'renderModFilterPanel', 'searchContentFiltered', 'createVersionCard',
        'mfChipHtml', 'mfRenderList', 'mfRenderMore'];
    let src = preamble;
    const missing = [];
    for (const n of fnNames) {
        const body = extractFunc(n);
        if (!body) { missing.push(n); continue; }
        src += '\n' + body + '\n';
    }
    src += `\nreturn { modFilters: modFilters, mfExpanded: mfExpanded,
        toggleModFilter: toggleModFilter, toggleMfExpand: toggleMfExpand,
        clearModFilters: clearModFilters, getModFilterCsv: getModFilterCsv,
        hasModFilters: hasModFilters, renderModFilterPanel: renderModFilterPanel,
        searchContentFiltered: searchContentFiltered, createVersionCard: createVersionCard,
        MF_CATEGORIES: typeof MF_CATEGORIES !== 'undefined' ? MF_CATEGORIES : null };`;
    // MF_* 数据在 index.html 顶层，注入进来
    const dataInject = ['MF_CATEGORIES', 'MF_LOADERS', 'MF_ENVS'].map(n => {
        const d = evalDecl(n);
        return d ? `var ${n} = ${JSON.stringify(d)};` : '';
    }).join('\n');
    let api;
    try {
        api = new Function('document', 'pythonInterface', 'showToast', 'getCurrentSource',
            dataInject + src)(documentStub, pythonInterface, showToast, getCurrentSource);
    } catch (e) {
        console.log('  ENV ERROR: ' + e.message + (missing.length ? ' missing:' + missing : ''));
        return { api: null, calls, elements, missing };
    }
    return { api, calls, elements, missing, getElementById: documentStub.getElementById };
}

section('行为: toggleModFilter');
let env = buildEnv();
check(env.api !== null, '测试环境应可构建' + (env.missing ? ' 缺函数:' + env.missing : ''));
if (env.api) {
    env.api.toggleModFilter('categories', 'adventure');
    check(env.api.modFilters.categories.length === 1 && env.api.modFilters.categories[0] === 'adventure', '应加入 adventure');
    check(env.calls.searchMods.length === 1, '启用筛选后应自动触发 searchMods');
    env.api.toggleModFilter('categories', 'adventure');
    check(env.api.modFilters.categories.length === 0, '再次点击应移除');
    env.api.toggleModFilter('loaders', 'fabric');
    env.api.toggleModFilter('loaders', 'quilt');
    check(env.api.getModFilterCsv('loaders') === 'fabric,quilt', 'csv 应为 fabric,quilt');
    check(env.api.hasModFilters() === true, 'hasModFilters 应为 true');
    env.api.clearModFilters();
    check(env.api.modFilters.loaders.length === 0 && env.api.modFilters.categories.length === 0, 'clear 应清空全部');
    check(env.api.hasModFilters() === false, 'clear 后 hasModFilters 为 false');
}

section('行为: renderModFilterPanel / 展开收起');
env = buildEnv();
if (env.api) {
    env.api.renderModFilterPanel();
    const catHtml = env.elements['mfCatList'] ? env.elements['mfCatList'].innerHTML : '';
    check(catHtml.indexOf('mf-chip') >= 0, '类别区应渲染 chips');
    check(catHtml.indexOf('adventure') >= 0 && catHtml.indexOf('worldgen') < 0, '折叠时应只渲染前 6 项');
    check(catHtml.indexOf('static/icons/cat/adventure.svg') >= 0, 'chip 应带类别图标');
    const more = env.elements['mfCatMore'] ? env.elements['mfCatMore'].innerHTML : '';
    check(more.indexOf('查看剩余 13 项') >= 0, '类别应显示 查看剩余 13 项, 实际: ' + more);
    env.api.toggleMfExpand('categories');
    const catHtml2 = env.elements['mfCatList'].innerHTML;
    check(catHtml2.indexOf('worldgen') >= 0, '展开后应渲染全部 19 项');
    check((env.elements['mfCatMore'].innerHTML || '').indexOf('收起') >= 0, '展开后按钮应为 收起');
    const loaderHtml = env.elements['mfLoaderList'].innerHTML;
    check(loaderHtml.indexOf('static/icons/loaders/fabric.png') >= 0, '加载器 chip 应带 logo');
    check((env.elements['mfLoaderMore'] ? env.elements['mfLoaderMore'].innerHTML : '') === '' ||
        env.elements['mfLoaderMore'].style.display === 'none' ||
        (env.elements['mfLoaderMore'].innerHTML || '').indexOf('查看剩余') < 0,
        '加载器 4 项全展示不应有查看剩余');
    const envHtml = env.elements['mfEnvList'].innerHTML;
    check(envHtml.indexOf('env/client.svg') >= 0 && envHtml.indexOf('Client') >= 0, '环境 chip 应带图标与 Client');
    const verHtml = env.elements['mfVersionList'].innerHTML;
    check(verHtml.indexOf('1.21.11') >= 0, '版本区应渲染 mfVersionsList');
    check(verHtml.indexOf('1.20.1') < 0, '折叠时 8 项内不应出现尾部版本');
}

section('行为: searchContentFiltered mods 分流');
env = buildEnv();
if (env.api) {
    env.getElementById('modSearch').value = '';
    env.api.searchContentFiltered('mods');
    check(env.calls.searchMods.length === 0, '空关键词+无筛选不应请求');
    check(env.calls.toast.length === 1 && env.calls.toast[0][0].indexOf('关键词') >= 0, '应提示输入关键词');
    env.api.toggleModFilter('categories', 'optimization');
    env.calls.searchMods.length = 0;
    env.getElementById('modSearch').value = '';
    env.api.searchContentFiltered('mods');
    check(env.calls.searchMods.length === 1, '有筛选+空关键词应请求');
    const a = env.calls.searchMods[0];
    check(a.length === 6, 'searchMods 应传 6 参, 实际 ' + a.length);
    check(a[0] === '' && a[3] === 'optimization', '参数顺序 query..categories..');
    env.getElementById('modSearch').value = 'sodium';
    env.calls.searchMods.length = 0;
    env.api.searchContentFiltered('mods');
    check(env.calls.searchMods[0][0] === 'sodium', '关键词应透传');
    check(env.calls.searchMods[0][5] === 'modrinth', 'source 应为 modrinth');
    env.getElementById('modpackSearch').value = 'pack';
    env.calls.searchContentFiltered.length = 0;
    env.api.searchContentFiltered('modpacks');
    check(env.calls.searchContentFiltered.length === 1, 'modpacks 应继续走旧 searchContentFiltered');
    check(env.calls.searchMods.length === 1 && env.calls.searchMods[0][0] === 'sodium', 'modpacks 不应污染 mods 请求');
}

section('行为: createVersionCard 右下角图标');
env = buildEnv();
if (env.api) {
    const fabricCard = env.api.createVersionCard({ id: '1.20.1-Fabric-0.16.9', type: 'release', releaseTime: 'x' }, false);
    const fHtml = fabricCard.innerHTML || '';
    check(fHtml.indexOf('version-loader-icon') >= 0, '卡片应含 version-loader-icon');
    check(fHtml.indexOf('static/icons/loaders/fabric.png') >= 0, 'Fabric 版本应配 fabric.png');
    const neoCard = env.api.createVersionCard({ id: '1.21.1-NeoForge-21.1.0', type: 'release', releaseTime: 'x' }, false);
    check((neoCard.innerHTML || '').indexOf('loaders/neoforge.png') >= 0, 'NeoForge 应配 neoforge.png');
    const vanillaCard = env.api.createVersionCard({ id: '1.21.4', type: 'release', releaseTime: 'x' }, false);
    const vHtml = vanillaCard.innerHTML || '';
    check(vHtml.indexOf('grass_block.png') >= 0, '原版应配 3D 草方块');
    check(vHtml.indexOf('loaders/') < 0, '原版不应带加载器图标');
    check(vHtml.indexOf('onerror') >= 0, '图标应有加载失败兜底');

    // 整合包版本 id 无 -Fabric- 段 → 按条目 loaders 字段判定（修复用户报告）
    const packCard = env.api.createVersionCard({
        id: 'Fabulously Optimized 13.2.2 for 26.1.2', type: 'release', releaseTime: 'x',
        loaders: [{ type: 'fabric', version: '0.19.3', name: 'Fabric' }]
    }, false);
    const pHtml = packCard.innerHTML || '';
    check(pHtml.indexOf('static/icons/loaders/fabric.png') >= 0, '整合包应按 loaders 字段显示 fabric.png');
    check(pHtml.indexOf('grass_block') < 0, '已检出 loader 不应显示草方块');
    check(pHtml.indexOf('Fabric') >= 0, '应带 Fabric 加载器 badge');
}

console.log('\nPASS: ' + pass + '  FAIL: ' + fail);
process.exit(fail ? 1 : 0);
