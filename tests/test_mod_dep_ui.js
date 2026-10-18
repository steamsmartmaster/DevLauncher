// 模组依赖：版本选择器要展示 required/optional，optional 可勾选后一并下载。
// incompatible 绝不能作为可安装项渲染——装上冲突模组会直接搞坏实例。
const { extractFunc, html } = require('./extract_func.js');
const fs = require('fs');
const path = require('path');

let pass = 0, fail = 0;
function check(cond, msg) {
    if (cond) { pass++; } else { fail++; console.log('  FAIL: ' + msg); }
}
function section(title) { console.log('\n== ' + title + ' =='); }

const SAMPLE = [
    { project_id: 'P7dR8mSH', version_id: null, dependency_type: 'required',
      file_name: null, title: 'Fabric API', slug: 'fabric-api', icon_url: '' },
    { project_id: 'AANobbMI', version_id: 'ygf8cVZg', dependency_type: 'optional',
      file_name: null, title: 'Sodium', slug: 'sodium', icon_url: '' },
    { project_id: 'bad00001', version_id: null, dependency_type: 'incompatible',
      file_name: null, title: 'Evil Mod', slug: 'evil-mod', icon_url: '' }
];

const depsSrc = extractFunc('renderVersionDeps');
section('renderVersionDeps: 必须存在');
check(depsSrc !== null, 'index.html 应含 function renderVersionDeps');

function escapeHtmlStub(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function renderDeps(deps, versionId) {
    if (depsSrc === null) return '<<NO_FUNC>>';
    const fn = new Function('escapeHtml', depsSrc + '\nreturn renderVersionDeps;')(escapeHtmlStub);
    return fn(deps, versionId === undefined ? 'ver123' : versionId);
}

let out = '';
try {
    out = renderDeps(SAMPLE);
    check(true, 'renderVersionDeps(含三类) 不应抛异常');
} catch (e) {
    check(false, 'renderVersionDeps 抛异常: ' + e.message);
    out = '';
}

section('renderVersionDeps: required 展示、optional 可勾、incompatible 不出现');
check(out.indexOf('Fabric API') >= 0, 'required 依赖应按标题渲染（裸 project_id 对用户无意义）');
check(out.indexOf('Sodium') >= 0, 'optional 依赖应按标题渲染');
check(out.indexOf('AANobbMI') >= 0, 'optional 依赖项目 id 应渲染');
check(out.indexOf('bad00001') < 0, 'incompatible 不应作为可安装项渲染');
check(out.indexOf('vp-dep-req') >= 0, 'required 应有 vp-dep-req 标识');
check(out.indexOf('vp-dep-opt') >= 0, 'optional 应有 vp-dep-opt 标识（复选框）');
check(out.indexOf('type="checkbox"') >= 0, 'optional 应是复选框而非纯文本');
check(out.indexOf('data-project="AANobbMI"') >= 0, '复选框要带 data-project 供提交时取值');
check(out.indexOf('data-version="ver123"') >= 0,
    '复选框要带 data-version=当前版本——列表里多版本同时渲染，不带会把别处的勾选串进来');
check(renderDeps(SAMPLE, 'other456').indexOf('data-version="other456"') >= 0,
    'data-version 必须跟随传入的版本 id，而不是写死');

section('renderVersionDeps: 空/无有效依赖不渲染空框');
check(renderDeps([]) === '', '空数组应返回空串');
check(renderDeps(null) === '', 'null 应返回空串');
check(renderDeps(undefined) === '', 'undefined 应返回空串');
check(renderDeps(SAMPLE.filter(d => d.dependency_type === 'incompatible')) === '',
    '只剩 incompatible 时应返回空串（无处可安装）');

section('pickModVersion: 勾选的 optional 以 JSON 数组串交给 Python');
const pickerSrc = extractFunc('pickModVersion');
check(pickerSrc !== null, 'index.html 应含 function pickModVersion');

function runPick(checkedProjects) {
    const calls = [];
    const els = checkedProjects.map(p => ({
        checked: true, dataset: { project: p, version: 'ver123' }
    }));
    const documentStub = {
        getElementById: id => (id === 'versionPickerName' ? { value: '' } : null),
        querySelectorAll: sel => (sel.indexOf('.vp-dep-opt') >= 0 ? els : [])
    };
    const pi = { downloadModVersion: (...args) => calls.push(args) };
    const fn = new Function(
        'document', 'closeVersionPicker', 'versionPickerCallback', 'pythonInterface',
        pickerSrc + '\nreturn pickModVersion;'
    )(documentStub, () => {}, null, pi);
    fn('ver123', 'Some Version');
    return calls;
}

let calls = [];
try {
    calls = runPick(['AANobbMI']);
    check(true, 'pickModVersion 不应抛异常');
} catch (e) {
    check(false, 'pickModVersion 抛异常: ' + e.message);
    calls = [];
}
check(calls.length === 1, '应调用一次 downloadModVersion, 实际 ' + calls.length);
if (calls.length === 1) {
    check(calls[0][0] === '', '第1参 content_id 应为空串');
    check(calls[0][1] === 'ver123', '第2参应是选中的 version id');
    check(calls[0][2] === '["AANobbMI"]',
        '第3参应是勾选项目的 JSON 数组串, 实际 ' + JSON.stringify(calls[0][2]));
}

calls = runPick([]);
check(calls.length === 1 && calls[0][2] === '[]',
    '未勾选任何依赖也应传 "[]" 而不是漏参, 实际 ' + JSON.stringify(calls.length === 1 ? calls[0][2] : null));

section('renderVersionPickerItem: 必须把 v.dependencies 接进渲染');
const itemSrc = extractFunc('renderVersionPickerItem');
check(itemSrc !== null, 'index.html 应含 function renderVersionPickerItem');
check(itemSrc && itemSrc.indexOf('renderVersionDeps') >= 0,
    'renderVersionPickerItem 应调用 renderVersionDeps');
check(itemSrc && /dependencies/.test(itemSrc),
    'renderVersionPickerItem 应读 v.dependencies');

section('main.py: getModVersions 带出 dependencies、槽签名收 JSON 串');
const mainSrc = fs.readFileSync(path.join(__dirname, '..', 'main.py'), 'utf8');
const mv = /def getModVersions\([\s\S]{0,2200}?self\.modVersions\.emit/.exec(mainSrc);
check(mv !== null, 'getModVersions 应存在');
check(mv && mv[0].indexOf('parse_dependencies') >= 0,
    'getModVersions 应调用 parse_dependencies（否则 UI 永远拿不到依赖）');
check(mv && mv[0].indexOf('get_project_versions') >= 0,
    '依赖应来自已有的 get_project_versions 结果，不该再发一次请求');

const sig = /def downloadModVersion\(self[^)]*\)/.exec(mainSrc);
check(sig !== null, 'downloadModVersion 应存在');
const sigParams = sig ? sig[0].slice(sig[0].indexOf('(') + 1, sig[0].lastIndexOf(')')) : '';
check(sigParams.split(',').length === 4,
    'downloadModVersion 应是 self + 三参 (content_id, version_id, deps_json), 实际 ' + sigParams);
check(sigParams.indexOf('optional_deps_json') >= 0,
    '第三参应接收勾选依赖的 JSON 串, 实际 ' + sigParams);

const dmv = /def downloadModVersion\([\s\S]{0,2500}?threading\.Thread/.exec(mainSrc);
check(dmv !== null, 'downloadModVersion 应存在');
check(dmv && dmv[0].indexOf('build_download_plan') >= 0,
    'downloadModVersion 应走 build_download_plan 组装下载清单');
check(dmv && dmv[0].indexOf('parse_chosen_ids') >= 0,
    'downloadModVersion 应用 parse_chosen_ids 安全解析 JS 传来的 JSON 串');
check(dmv && dmv[0].indexOf('_resolve_dep_version') >= 0,
    '勾选的依赖要经 _resolve_dep_version 解析成可下载版本');
check(/from launcher_core\.api_modrinth import[\s\S]{0,400}?build_download_plan/.test(mainSrc),
    'main.py 应导入 build_download_plan');
check(/from launcher_core\.api_modrinth import[\s\S]{0,400}?parse_dependencies/.test(mainSrc),
    'main.py 应导入 parse_dependencies');

section('CSS 与事件：依赖块要看得见，点它不能误触发下载');
for (const cls of ['.vp-deps {', '.vp-deps-row {', '.vp-deps-label {',
                   '.vp-dep-req {', '.vp-dep-opt {']) {
    check(html.indexOf(cls) >= 0, '缺少样式 ' + cls);
}
check(out.indexOf('stopPropagation') >= 0,
    '依赖块必须 stopPropagation——它嵌在带 onclick 的 .version-picker-item 里，不拦就会点了复选框直接开下载');
check(/\.version-picker-item \{[\s\S]{0,200}?flex-wrap: wrap/.test(html),
    '.version-picker-item 需要 flex-wrap，否则依赖块会被挤在同一行右侧');

console.log('\nPASS: ' + pass + ' FAIL: ' + fail);
process.exit(fail ? 1 : 0);
