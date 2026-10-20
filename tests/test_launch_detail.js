'use strict';
// 启动详细过程面板：分阶段事件 + 游戏早期日志，必须实时可见、可折叠、不注入 HTML
const { extractFunc, html } = require('./extract_func.js');

let pass = 0, fail = 0;
function check(cond, msg) {
    if (cond) { pass++; } else { fail++; console.log('  FAIL: ' + msg); }
}
function section(title) { console.log('\n== ' + title + ' =='); }

function makeEl(tag) {
    const el = {
        tagName: tag,
        className: '',
        textContent: '',
        style: {},
        childNodes: [],
        scrollTop: 0,
        appendChild(c) { this.childNodes.push(c); },
        removeChild(c) {
            const i = this.childNodes.indexOf(c);
            if (i >= 0) this.childNodes.splice(i, 1);
        },
        get firstChild() { return this.childNodes[0] || null; },
        get scrollHeight() { return this.childNodes.length * 18; },
    };
    Object.defineProperty(el, 'innerHTML', {
        get() { return ''; },
        set(v) { if (v === '') this.childNodes.length = 0; },
    });
    return el;
}

function makeDocument(ids) {
    const els = {};
    ids.forEach(function (id) { els[id] = makeEl('div'); });
    return {
        getElementById(id) { return els[id] || null; },
        createElement(tag) { return makeEl(tag); },
        _els: els,
    };
}

const IDS = ['launchDetailPanel', 'launchDetailLog', 'launchDetailToggle'];

function load(name) {
    const src = extractFunc(name);
    if (!src) return null;
    return new Function(src + '\nreturn ' + name + ';')();
}

section('markup: 面板存在且在启动按钮上方');
check(html.includes('id="launchDetailPanel"'), '应有 #launchDetailPanel');
check(html.includes('id="launchDetailLog"'), '应有 #launchDetailLog');
check(html.includes('id="launchDetailToggle"'), '应有 #launchDetailToggle');
check(html.includes('onclick="toggleLaunchDetail()"'), '折叠按钮应调用 toggleLaunchDetail');
check(html.includes('启动详情'), '面板标题应为「启动详情」');
check(html.includes('class="download-file-list launch-detail-log"'), '日志区应复用滚动列表样式');
{
    const iSection = html.indexOf('class="launch-section"');
    const iPanel = html.indexOf('id="launchDetailPanel"');
    const iBtn = html.indexOf('id="launchBtn"');
    check(iSection !== -1 && iPanel !== -1 && iBtn !== -1, 'launch-section / panel / button 均应存在');
    check(iSection < iPanel && iPanel < iBtn, '面板应在启动按钮之前、启动区之内');
}

section('appendLaunchDetail: 追加行、时间戳、自动滚动');
const append = load('appendLaunchDetail');
check(typeof append === 'function', '应能抽取 appendLaunchDetail');
{
    const dom = makeDocument(IDS);
    global.document = dom;
    append('check_version', '检查版本 1.20.1');
    const log = dom._els.launchDetailLog;
    check(dom._els.launchDetailPanel.style.display === 'block', '首行后应显示面板');
    check(log.childNodes.length === 1, '应追加 1 行, 实际 ' + log.childNodes.length);
    const row = log.childNodes[0];
    check(row.className.includes('launch-detail-line'), '行应有 launch-detail-line 类');
    check(/^\d{2}:\d{2}:\d{2}$/.test(row.childNodes[0].textContent), '首列应为 HH:MM:SS 时间戳');
    check(row.childNodes[1].textContent === '检查版本 1.20.1', '文本应原样显示');
    check(log.scrollTop === log.scrollHeight, '应自动滚动到底部');
}

section('appendLaunchDetail: 文本不经过 HTML 解析');
{
    const src = extractFunc('appendLaunchDetail');
    check(src.indexOf('innerHTML') === -1, 'appendLaunchDetail 不得使用 innerHTML');
    const dom = makeDocument(IDS);
    global.document = dom;
    append('log', '<img src=x onerror=alert(1)>');
    const body = dom._els.launchDetailLog.childNodes[0].childNodes[1];
    check(body.textContent.indexOf('onerror') !== -1, '危险文本应作为纯文本保留');
    check(body.textContent.indexOf('<img') === 0, '尖括号不应被吞掉');
}

section('appendLaunchDetail: 步骤配色');
{
    const cases = [
        ['ready', 'is-ready'],
        ['error', 'is-error'],
        ['java_fail', 'is-error'],
        ['exit', 'is-error'],
        ['version_ok', 'is-ok'],
        ['command_ok', 'is-ok'],
        ['log', null],
    ];
    for (const [step, cls] of cases) {
        const dom = makeDocument(IDS);
        global.document = dom;
        append(step, 'x');
        const row = dom._els.launchDetailLog.childNodes[0];
        if (cls) check(row.className.includes(cls), step + ' 应带 ' + cls);
        else check(!/ is-(ok|ready|error)/.test(row.className), step + ' 不应带状态色');
    }
}

section('appendLaunchDetail: 行数上限 200');
{
    const dom = makeDocument(IDS);
    global.document = dom;
    for (let i = 0; i < 205; i++) append('log', 'line ' + i);
    const log = dom._els.launchDetailLog;
    check(log.childNodes.length === 200, '应只保留 200 行, 实际 ' + log.childNodes.length);
    check(log.childNodes[199].childNodes[1].textContent === 'line 204', '应保留最新的行');
}

section('launchDetailClear / toggleLaunchDetail');
const clear = load('launchDetailClear');
const toggle = load('toggleLaunchDetail');
check(typeof clear === 'function' && typeof toggle === 'function', '应能抽取清空与折叠函数');
{
    const dom = makeDocument(IDS);
    global.document = dom;
    append('log', 'a');
    append('log', 'b');
    clear();
    check(dom._els.launchDetailLog.childNodes.length === 0, '清空应移除全部行');
    check(dom._els.launchDetailPanel.style.display === 'none', '清空后应隐藏面板');
    check(dom._els.launchDetailToggle.textContent === '收起', '清空后按钮应复位为「收起」');
}
{
    const dom = makeDocument(IDS);
    global.document = dom;
    toggle();
    check(dom._els.launchDetailLog.style.display === 'none', '第一次折叠应隐藏日志');
    check(dom._els.launchDetailToggle.textContent === '展开', '折叠后按钮应为「展开」');
    toggle();
    check(dom._els.launchDetailLog.style.display === 'block', '再次点击应展开');
    check(dom._els.launchDetailToggle.textContent === '收起', '展开后按钮应为「收起」');
}

section('接线: 启动时清空、安装时隐藏');
{
    const launchSrc = extractFunc('launchGame') || '';
    check(launchSrc.includes('launchDetailClear()'), 'launchGame 应清空上次的详情');
    const updateSrc = extractFunc('updateLaunchButton') || '';
    check(updateSrc.includes('launchDetailPanel'), 'updateLaunchButton 应引用详情面板');
    check(updateSrc.includes("detailPanel.style.display = 'none'"), '安装开始时应隐藏旧详情');
}

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exitCode = fail ? 1 : 0;
