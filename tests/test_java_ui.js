// P0-1 设置页 Java 扫描列表：静态结构 / 渲染 / 使用(双输入同步) / 隐藏 / 空态与错误 / 扫描按钮
// 红→绿 TDD
const fs = require('fs');
const path = require('path');
const { extractFunc, html } = require('./extract_func.js');

let pass = 0, fail = 0;
function check(cond, msg) { if (cond) pass++; else { fail++; console.log('  FAIL: ' + msg); } }
function section(t) { console.log('\n== ' + t + ' =='); }

section('静态: Java 扫描 UI');
check(html.indexOf('id="javaListItems"') >= 0, '应有 javaListItems 容器');
check(html.indexOf('id="javaListEmpty"') >= 0, '应有 javaListEmpty 空态');
check(/onclick="scanJavas\(\)"/.test(html), '应有扫描按钮');
check(/querySelectorAll\('#javaPath'\)/.test(html), 'loadSettings/setJavaPathValue 应同步两个同 id 输入');
check(/pythonInterface\.hideJava/.test(html), '应调 pythonInterface.hideJava');
check((html.match(/onchange="javaPathEdited\(this\)"/g) || []).length === 2,
    '两个 javaPath 输入都应 onchange=javaPathEdited(this)');

section('静态: JS 函数存在');
for (const n of ['scanJavas', 'setJavaPathValue', 'hideJavaPath', 'onJavasScanned', 'javaPathEdited']) {
    check(extractFunc(n) !== null, 'index.html 应含 function ' + n);
}

section('静态: pythonInterface 调用点');
check(/pythonInterface\.scanJavas\(/.test(html), 'scanJavas 应调 pythonInterface.scanJavas');
check(/pythonInterface\.hideJava\(/.test(html), 'hideJavaPath 应调 pythonInterface.hideJava');

function buildEnv() {
    const elements = {};
    function el(id) {
        if (!elements[id]) {
            elements[id] = {
                id, innerHTML: '', value: '', textContent: '', style: {},
                classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
                dataset: {}, options: [], checked: false,
                appendChild() {}, querySelectorAll: () => [],
                addEventListener() {}, disabled: false,
                setAttribute(k, v) { (this._attrs = this._attrs || {})[k] = String(v); },
                getAttribute(k) { return (this._attrs && k in this._attrs) ? this._attrs[k] : null; },
                removeAttribute(k) { if (this._attrs) delete this._attrs[k]; }
            };
        }
        return elements[id];
    }
    const box = el('javaListItems');
    box.childNodes = [];
    let boxHtml = '';
    Object.defineProperty(box, 'innerHTML', {
        get() { return boxHtml; },
        set(v) { boxHtml = String(v); box.childNodes = []; }
    });
    box.appendChild = function (c) { this.childNodes.push(c); };
    box.removeChild = function (c) {
        const i = this.childNodes.indexOf(c);
        if (i >= 0) this.childNodes.splice(i, 1);
    };

    const javaA = el('javaPath');
    const javaB = el('javaPath2');
    const documentStub = {
        getElementById: (id) => el(id),
        createElement: () => {
            const node = {
                className: '', innerHTML: '', style: {}, dataset: {},
                childNodes: [], _attrs: {},
                classList: { add() {}, toggle() {}, remove() {}, contains: () => false },
                appendChild(c) { this.childNodes.push(c); },
                setAttribute(k, v) { this._attrs[k] = String(v); },
                getAttribute(k) { return (k in this._attrs) ? this._attrs[k] : null; },
                removeChild(c) {
                    const i = this.childNodes.indexOf(c);
                    if (i >= 0) this.childNodes.splice(i, 1);
                }
            };
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
        querySelectorAll: (sel) => (sel === '#javaPath' ? [javaA, javaB] : []),
        querySelector: () => null
    };
    const calls = { scanJavas: [], hideJava: [], saveSettings: [], toast: [] };
    const pythonInterface = {
        scanJavas: (...a) => calls.scanJavas.push(a),
        hideJava: (...a) => calls.hideJava.push(a),
        saveSettings: (...a) => calls.saveSettings.push(a),
        selectJavaPath: () => {}
    };
    function showToast(msg, type) { calls.toast.push([msg, type]); }
    const fnNames = ['escapeHtml', 'scanJavas', 'setJavaPathValue', 'hideJavaPath',
        'onJavasScanned', 'javaPathEdited', 'saveSettings'];
    let src = '';
    const missing = [];
    for (const n of fnNames) {
        const body = extractFunc(n);
        if (!body) { missing.push(n); continue; }
        src += '\n' + body + '\n';
    }
    src += `\nreturn { scanJavas: scanJavas, setJavaPathValue: setJavaPathValue,
        hideJavaPath: hideJavaPath, onJavasScanned: onJavasScanned,
        javaPathEdited: javaPathEdited };`;
    let api;
    try {
        api = new Function('document', 'pythonInterface', 'showToast', src)
            (documentStub, pythonInterface, showToast);
    } catch (e) {
        console.log('  ENV ERROR: ' + e.message + (missing.length ? ' missing:' + missing : ''));
        return { api: null, calls, elements, missing, javaA, javaB };
    }
    return { api, calls, elements, missing, javaA, javaB };
}

section('行为: onJavasScanned 渲染/使用/隐藏');
let env = buildEnv();
check(env.api !== null, '测试环境应可构建' + (env.missing && env.missing.length ? ' 缺函数:' + env.missing : ''));
if (env.api) {
    env.api.onJavasScanned(JSON.stringify({
        javas: [
            { path: 'C:\\jdk17\\bin\\java.exe', major: 17, version: '17.0.9' },
            { path: 'C:\\jdk21\\bin\\javaw.exe', major: 21, version: '21.0.1' }
        ],
        recommend: 'C:\\jdk21\\bin\\javaw.exe', mc_version: '1.21.11'
    }));
    const rows = env.elements['javaListItems'].childNodes;
    check(rows.length === 2, '应渲染 2 行, 实际 ' + rows.length);
    check(String(rows[0].innerHTML).indexOf('J17') >= 0, '行1应有 J17 徽章');
    check(String(rows[1].innerHTML).indexOf('J21') >= 0, '行2应有 J21 徽章');
    check(String(rows[1].innerHTML).indexOf('推荐') >= 0, '推荐项应带 推荐 徽章');
    check(String(rows[0].innerHTML).indexOf('jdk17') >= 0, '行1应含路径文本');
    check(env.elements['javaListEmpty'].style.display === 'none', '有结果时空态应隐藏');
    check(rows[0].getAttribute('data-path') === 'C:\\jdk17\\bin\\java.exe', '行应带 data-path');

    rows[1].childNodes[rows[1].childNodes.length - 2].onclick();
    check(env.javaA.value === 'C:\\jdk21\\bin\\javaw.exe', '使用应写输入框1, 实际 ' + env.javaA.value);
    check(env.javaB.value === 'C:\\jdk21\\bin\\javaw.exe', '使用应同步输入框2, 实际 ' + env.javaB.value);
    check(env.calls.saveSettings.length === 1, '使用后应 saveSettings, 实际 ' + env.calls.saveSettings.length);

    rows[0].childNodes[rows[0].childNodes.length - 1].onclick();
    check(env.calls.hideJava.length === 1 &&
        env.calls.hideJava[0][0] === 'C:\\jdk17\\bin\\java.exe',
        '隐藏应调 hideJava(path), 实际 ' + JSON.stringify(env.calls.hideJava));
    check(env.elements['javaListItems'].childNodes.length === 1, '隐藏后应剩 1 行');
}

section('行为: 空列表与错误');
env = buildEnv();
if (env.api) {
    env.api.onJavasScanned(JSON.stringify({ javas: [], recommend: '' }));
    check(env.elements['javaListEmpty'].style.display === 'block', '空列表应显示空态');
    check(env.elements['javaListItems'].childNodes.length === 0, '空列表不应有行');
    env.api.onJavasScanned(JSON.stringify({ javas: [], error: 'boom' }));
    check(env.calls.toast.some(t => String(t[0]).indexOf('boom') >= 0), '错误应 toast');
    check(env.calls.toast.some(t => t[1] === 'error'), 'toast 应为 error 类型');
}

section('行为: 扫描按钮与手动输入同步');
env = buildEnv();
if (env.api) {
    env.api.scanJavas();
    check(env.calls.scanJavas.length === 1, 'scanJavas 应调 pythonInterface.scanJavas');
    env.javaB.value = 'D:\\jdk8\\bin\\java.exe';
    env.api.javaPathEdited(env.javaB);
    check(env.javaA.value === 'D:\\jdk8\\bin\\java.exe', '手动改输入框2应镜像到输入框1');
    check(env.calls.saveSettings.length === 1, '手动输入后应 saveSettings');
}

console.log('\n通过: ' + pass + ' / 失败: ' + fail);
process.exit(fail ? 1 : 0);
