// i18n：词典数据完整性 + 运行时契约（locale 探测/持久化/双向切换/文本节点翻译）
// i18n.js 依赖 window/document/navigator/localStorage，所以用最小 DOM 垫片加载它，
// 而不是把运行时拆成可注入的模块——真实页面里的加载顺序必须和这里一致。
const fs = require('fs');
const path = require('path');

let pass = 0, fail = 0;
function check(cond, msg) { if (cond) pass++; else { fail++; console.log('  FAIL: ' + msg); } }
function section(title) { console.log('\n== ' + title + ' =='); }

const UI = path.join(__dirname, '..', 'ui');
const dictSrc = fs.readFileSync(path.join(UI, 'i18n_dict.js'), 'utf8');
const runSrc = fs.readFileSync(path.join(UI, 'i18n.js'), 'utf8');
const html = fs.readFileSync(path.join(UI, 'index.html'), 'utf8');

function markupText(page) {
    const stripped = page
        .replace(/<script[\s\S]*?<\/script>/gi, '')
        .replace(/<style[\s\S]*?<\/style>/gi, '')
        .replace(/<!--[\s\S]*?-->/g, '');
    const out = [];
    const re = />([^<>]+)</g;
    let m;
    while ((m = re.exec(stripped))) {
        const t = m[1].replace(/\s+/g, ' ').trim();
        if (t) out.push(t);
    }
    const attrs = [];
    const are = /\b(title|placeholder|aria-label)="([^"]+)"/g;
    while ((m = are.exec(stripped))) attrs.push(m[2].trim());
    return { texts: out, attrs: attrs };
}
const sourceStrings = markupText(html);

section('词典数据');
const dict = {};
new Function('window', dictSrc)(dict);
const D = dict.I18N_DATA;
check(D && typeof D === 'object', 'i18n_dict.js 应挂 window.I18N_DATA');
check(D.map && D.mapEn && D.zh && D.en, '应有 map/mapEn/zh/en 四张表');
const enKeys = Object.keys(D.en);
check(enKeys.length >= 300, 'en 词条应 >= 300，实际 ' + enKeys.length);
// 单字量词（如「个」出现在 '(' + n + '个)' 这类拼接里）译成空串是刻意的：英文不带量词。
const CJK_ONE = /^[㐀-鿿]$/;
check(enKeys.every(k => typeof D.en[k] === 'string'
    && (D.en[k].length > 0 || CJK_ONE.test(D.zh[k] || ''))),
    'en 词条不得为空（单字量词除外）');
check(enKeys.every(k => !/[㐀-鿿]/.test(D.en[k])),
    'en 词条不得残留中文: '
    + enKeys.filter(k => /[㐀-鿿]/.test(D.en[k])).slice(0, 5)
        .map(k => D.zh[k] + ' => ' + D.en[k]).join(' | '));
function norm(s) { return String(s).replace(/\s+/g, ' ').trim(); }
const normMap = {};
for (const k in D.map) if (D.map.hasOwnProperty(k)) normMap[norm(k)] = true;

const zhSource = sourceStrings.texts.concat(sourceStrings.attrs)
    .filter(s => /[㐀-鿿]/.test(s));
const missingZh = zhSource.filter(z => !normMap[norm(z)]);
check(missingZh.length === 0, '页面静态文案应全部入 map，缺 ' + missingZh.length
    + ': ' + missingZh.slice(0, 5).join(' | '));
const badRound = Object.keys(D.map).filter(k => {
    const en = D.en[D.map[k]];
    return en === undefined || D.mapEn[en] === undefined;
});
check(badRound.length === 0, 'map/mapEn 应可双向回指，异常 '
    + badRound.length + ': ' + badRound.slice(0, 5).join(' | '));
// 英文文本可以重复出现，mapEn 按值合并，所以比数量没有意义；要断言每个英文值都可回查
check(enKeys.every(k => D.mapEn[D.en[k]] !== undefined),
    'mapEn 应覆盖 en 全部词条');
const htmlFrags = Object.keys(D.map).filter(s => s.indexOf('<') >= 0);
const unpaired = htmlFrags.filter(s => {
    // 片段可能在标签中间被截断（如 `<dd title="`），残留的 `<` 片段不是文本节点，跳过
    const zhTexts = s.replace(/<[^>]*>/g, '|').split('|')
        .map(x => norm(x)).filter(t => t && t.indexOf('<') < 0);
    return zhTexts.some(t => !normMap[t]);
});
check(unpaired.length === 0, 'HTML 片段的内层文本应可被 DOM 命中，未配对 '
    + unpaired.length + ': ' + unpaired.slice(0, 3).join(' | '));
check(htmlFrags.length > 20, '应识别出 HTML 片段，实际 ' + htmlFrags.length);

section('运行时加载（DOM 垫片）');
function makeStorage() {
    const store = {};
    return {
        getItem: k => (k in store ? store[k] : null),
        setItem: (k, v) => { store[k] = String(v); },
        _store: store
    };
}
function makeElement(name, text, attrs) {
    return {
        nodeType: 1, nodeName: name,
        attrs: Object.assign({}, attrs || {}),
        getAttribute: function (a) { return (a in this.attrs) ? this.attrs[a] : null; },
        setAttribute: function (a, v) { this.attrs[a] = v; }
    };
}
function bootRuntime(navLang, storage) {
    const textNodes = [];
    const attrEls = [];
    const doc = {
        readyState: 'complete', nodeType: 9,
        documentElement: { nodeName: 'HTML' },
        addEventListener: function () { },
        dispatchEvent: function () { return true; },
        createEvent: function () {
            return { initCustomEvent: function () { } };
        },
        createTreeWalker: function (root) {
            const list = root.__textNodes || [];
            let i = -1;
            return { nextNode: function () { i++; return i < list.length ? list[i] : null; } };
        },
        querySelectorAll: function () { return attrEls; },
        __textNodes: textNodes
    };
    const sandbox = {
        window: {},
        document: doc,
        navigator: { language: navLang },
        localStorage: storage,
        NodeFilter: { SHOW_TEXT: 4 },
        MutationObserver: undefined,
        CustomEvent: function () { }
    };
    sandbox.window.document = doc;
    sandbox.window.navigator = sandbox.navigator;
    sandbox.window.localStorage = storage;
    new Function('window', dictSrc)(sandbox.window);
    const fn = new Function('window', 'document', 'navigator', 'localStorage',
        'NodeFilter', 'MutationObserver', 'CustomEvent',
        runSrc + '\n;return window.I18N;');
    const I18N = fn(sandbox.window, doc, sandbox.navigator, sandbox.localStorage,
        sandbox.NodeFilter, sandbox.MutationObserver, sandbox.CustomEvent);
    return { I18N, doc, textNodes, attrEls, storage };
}

section('locale 探测');
let rt = bootRuntime('en-US', makeStorage());
check(rt.I18N.locale() === 'en', 'navigator.language=en-US 应探测到 en，实际 '
    + rt.I18N.locale());
rt = bootRuntime('zh-CN', makeStorage());
check(rt.I18N.locale() === 'zh-CN', 'navigator.language=zh-CN 应得到 zh-CN');
rt = bootRuntime('fr-FR', makeStorage());
check(rt.I18N.locale() === 'zh-CN', '未识别语言应回落 zh-CN，实际 ' + rt.I18N.locale());
const st = makeStorage();
st.setItem('devlauncher.locale', 'en');
rt = bootRuntime('zh-CN', st);
check(rt.I18N.locale() === 'en', '已保存的偏好应覆盖系统语言');
rt = bootRuntime('en-US', makeStorage());
check(rt.I18N.setLocale('bogus') === false, '未知 locale 应被拒绝');
check(rt.I18N.setLocale('zh-CN') === true, '合法 locale 应被接受');
check(rt.storage.getItem('devlauncher.locale') === 'zh-CN',
    'setLocale 应把偏好写进 localStorage');
check(rt.I18N.locale() === 'zh-CN', 'setLocale 后 locale() 应立即生效');

section('文本节点翻译与双向切换');
rt = bootRuntime('zh-CN', makeStorage());
function pushText(value, parentName) {
    const node = { nodeType: 3, nodeName: '#text', nodeValue: value,
        parentNode: { nodeName: parentName || 'DIV' } };
    rt.textNodes.push(node);
    return node;
}
const nLabel = pushText('设置');
const nPad = pushText('  模组  ');
const nScript = pushText('设置', 'SCRIPT');
const nAttr = makeElement('INPUT', '', { placeholder: '搜索世界...' });
rt.attrEls.push(nAttr);
rt.I18N.setLocale('en');
check(nLabel.nodeValue === 'Settings', '文本节点 应译为 Settings，实际 '
    + JSON.stringify(nLabel.nodeValue));
check(nPad.nodeValue === '  Mods  ', '应保留首尾空白，实际 '
    + JSON.stringify(nPad.nodeValue));
check(nScript.nodeValue === '设置', 'SCRIPT 内的文本不应被翻译');
check(nAttr.getAttribute('placeholder') === 'Search worlds...',
    'placeholder 属性应被翻译，实际 ' + nAttr.getAttribute('placeholder'));
check(rt.I18N.locale() === 'en', '切换后 locale 应为 en');

rt.I18N.setLocale('zh-CN');
check(nLabel.nodeValue === '设置', '切回 zh 应还原，实际 '
    + JSON.stringify(nLabel.nodeValue));
check(nPad.nodeValue === '  模组  ', '切回 zh 应保留空白，实际 '
    + JSON.stringify(nPad.nodeValue));
check(nAttr.getAttribute('placeholder') === '搜索世界...',
    '切回 zh 应还原 placeholder，实际 ' + nAttr.getAttribute('placeholder'));

section('重复应用应幂等');
rt.I18N.setLocale('en');
const before = nLabel.nodeValue;
rt.I18N.translate(rt.doc);
check(nLabel.nodeValue === before, '重复 translate 不应再次改写');

section('拼接消息：长词优先的子串替换');
const composed = pushText('确定要删除世界 "foo" 吗？');
rt.I18N.setLocale('en');
const enOut = composed.nodeValue;
check(!/[㐀-鿿]/.test(enOut),
    '拼接消息译完不应残留中文，实际 ' + JSON.stringify(enOut));
check(enOut.indexOf('Delete world') >= 0 && enOut.indexOf('"foo"') >= 0,
    '应保留动态内容并替换静态片段，实际 ' + JSON.stringify(enOut));

section('t() 与 lookup()');
check(rt.I18N.t('no_such_key') === 'no_such_key', '未知 key 应回退成 key 本身');
const knownKey = D.map['设置'];
check(rt.I18N.t(knownKey) === 'Settings', 't(key) 在 en 下应返回英文');
check(rt.I18N.lookup('设置') === 'Settings', 'lookup(中文) 应返回英文');
check(rt.I18N.lookup('完全不存在的文案') === null, '未收录文案应返回 null');
check(Array.isArray(rt.I18N.LOCALES) && rt.I18N.LOCALES.indexOf('en') >= 0
    && rt.I18N.LOCALES.indexOf('zh-CN') >= 0, 'LOCALES 应含 zh-CN 与 en');

section('index.html 接线');
check(/<script src="qrc:\/\/\/qtwebchannel\/qwebchannel\.js"><\/script>\s*<script src="i18n_dict\.js"><\/script>\s*<script src="i18n\.js"><\/script>/.test(html),
    'i18n_dict.js + i18n.js 应紧跟 qwebchannel 之后');
const qi = html.indexOf('qwebchannel.js');
const di = html.indexOf('i18n_dict.js');
const ri = html.indexOf('i18n.js');
check(qi < di && di < ri, '脚本顺序应为 qwebchannel → dict → runtime');
check(html.indexOf('id="uiLocale"') >= 0, '设置页应有 uiLocale 选择器');
check(/id="uiLocale" onchange="changeLocale\(this\.value\)"/.test(html),
    'uiLocale 应 onchange 调 changeLocale');
check(/<option value="zh-CN">/.test(html) && /<option value="en">/.test(html),
    '应有 zh-CN 与 en 两个选项');
check(/function changeLocale\(loc\)/.test(html), '应有 function changeLocale');
check(/function syncLocaleSelect\(/.test(html), '应有 function syncLocaleSelect');
const clSrc = html.slice(html.indexOf('function changeLocale('));
check(clSrc.indexOf('I18N.setLocale(loc)') >= 0, 'changeLocale 应调 I18N.setLocale');
const sySrc = html.slice(html.indexOf('function syncLocaleSelect('));
check(sySrc.indexOf('I18N.locale()') >= 0, 'syncLocaleSelect 应读 I18N.locale()');
check(/i18n:change/.test(runSrc), '运行时应广播 i18n:change 事件');
check(/MutationObserver/.test(runSrc), '运行时应用 MutationObserver 跟进动态注入的节点');
check(/localStorage/.test(runSrc) && /devlauncher\.locale/.test(runSrc),
    '偏好应持久化在 devlauncher.locale');

section('内层单元必须译成纯文本，而不是整段 HTML');
const inner = Object.keys(D.map).find(s => s.indexOf('<') >= 0
    && D.map[s] !== undefined);
if (inner) {
    const innerZh = D.zh[D.map[inner]];
    const innerEn = D.en[D.map[inner]];
    const text = innerZh.replace(/<[^>]*>/g, '|').split('|')
        .map(x => norm(x)).filter(t => t && t.indexOf('<') < 0)[0];
    if (text) {
        const got = rt.I18N.lookup(text);
        check(got !== null && got.indexOf('<') < 0,
            'HTML 片段的内层文本应译成纯文本，实际 ' + JSON.stringify(got));
        check(innerEn.indexOf('<') >= 0, '整段 HTML 自身应译成含标签的 HTML');
    }
}
const titled = Object.keys(D.map).find(s => /\btitle="/.test(s));
check(titled !== undefined, '应存在含 title 属性的片段条目');
if (titled) {
    const m = /\btitle="([^"]+)"/.exec(titled);
    if (m && /[㐀-鿿]/.test(m[1])) {
        const got = rt.I18N.lookup(m[1]);
        check(got !== null && got.indexOf('<') < 0,
            '片段里的 title 值应能单独翻译，实际 ' + JSON.stringify(got));
    }
}

console.log('\nPASS: ' + pass + ' FAIL: ' + fail);
process.exit(fail ? 1 : 0);
