// 下载进度条：updateProgress 曾引用不存在的 #downloadProgressFile → TypeError，
// 面板出现但 progressFill 永不更新（版本安装/模组下载/内容下载的条全死）
const { extractFunc, html } = require('./extract_func.js');

let pass = 0, fail = 0;
function check(cond, msg) {
    if (cond) { pass++; } else { fail++; console.log('  FAIL: ' + msg); }
}
function section(title) { console.log('\n== ' + title + ' =='); }

function makeDom() {
    const els = {};
    return {
        getElementById(id) {
            if (!html.includes('id="' + id + '"')) return null;
            if (!els[id]) els[id] = { textContent: '', style: {}, innerHTML: '' };
            return els[id];
        },
        _els: els
    };
}

const src = extractFunc('updateProgress');
section('updateProgress: 引用的 DOM 必须真实存在');
check(src !== null, 'index.html 应含 function updateProgress');
const refs = [];
const re = /getElementById\(\s*['"]([\w-]+)['"]\s*\)/g;
let m;
while ((m = re.exec(src || '')) !== null) refs.push(m[1]);
check(refs.length >= 3, 'updateProgress 应引用进度面板元素, 实际 ' + refs.length);
for (const id of refs) {
    check(html.includes('id="' + id + '"'), '引用的 #' + id + ' 必须存在于 DOM');
}

section('updateProgress: 百分比 → 进度条推进');
function run(progress, text) {
    const dom = makeDom();
    global.document = dom;
    const fn = new Function(src + '\nreturn updateProgress;')();
    fn(progress, text);
    return dom._els;
}
let els;
try {
    els = run(42.4, '正在下载 foo.jar');
    check(true, 'updateProgress(42.4) 不应抛异常');
} catch (e) {
    check(false, 'updateProgress(42.4) 抛异常: ' + e.message);
    els = {};
}
if (els.progressFill) {
    const w = String(els.progressFill.style.width);
    check(w.endsWith('%'), '进度条宽度应为百分比, 实际 ' + w);
    check(Math.abs(parseFloat(w) - 42.4) < 1, '宽度应≈42%, 实际 ' + w);
    check(els.progressFill.style.animation === 'none', '有百分比时应关掉条纹动画');
}
check(els.downloadProgressPanel && els.downloadProgressPanel.style.display === 'block',
    '面板应显示');
check(els.downloadProgressTitle && els.downloadProgressTitle.textContent.indexOf('foo.jar') >= 0,
    '标题应显示下载文案');
check(els.downloadProgressCount && /%/.test(els.downloadProgressCount.textContent),
    '计数位应显示百分比, 实际 "' + (els.downloadProgressCount ? els.downloadProgressCount.textContent : 'missing') + '"');

section('updateProgress: 负值 → 条纹（不确定进度）');
try {
    els = run(-1, '[7] downloading client.jar');
    check(true, 'updateProgress(-1) 不应抛异常');
} catch (e) {
    check(false, 'updateProgress(-1) 抛异常: ' + e.message);
    els = {};
}
if (els.progressFill) {
    check(String(els.progressFill.style.animation).indexOf('progressStripes') >= 0,
        '负进度应启条纹动画, 实际 "' + els.progressFill.style.animation + '"');
}
check(els.downloadProgressCount && els.downloadProgressCount.textContent === '',
    '负进度无百分比可显示');

section('main.py: 文案注入与版本安装进度接线');
const mainSrc = require('fs').readFileSync(
    require('path').join(__dirname, '..', 'main.py'), 'utf8');
const m2 = /def _on_progress_update\(self[\s\S]{0,400}/.exec(mainSrc);
check(m2 !== null, '_on_progress_update 应存在');
check(m2 && m2[0].indexOf('json.dumps') >= 0,
    '文案应经 json.dumps 注入（文件名含引号会打断 JS 字面量）');
const m3 = /def installVersion\(self[\s\S]{0,3400}?threading\.Thread/.exec(mainSrc);
check(m3 !== null, 'installVersion 应存在');
check(m3 && m3[0].indexOf('"setMax"') >= 0, 'installVersion 应接 mll setMax');
check(m3 && m3[0].indexOf('"setProgress"') >= 0, 'installVersion 应接 mll setProgress');

console.log('\nPASS: ' + pass + ' FAIL: ' + fail);
process.exit(fail ? 1 : 0);
