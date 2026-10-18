// 导出 mrpack：版本卡片上的按钮 → 槽 → 后台线程 → 信号 → runJavaScript 回 UI。
// 链路任何一环断了都会表现为「点了没反应」，所以整条链都要锁。
const fs = require('fs');
const path = require('path');

let pass = 0, fail = 0;
function check(cond, msg) {
    if (cond) { pass++; } else { fail++; console.log('  FAIL: ' + msg); }
}
function section(title) { console.log('\n== ' + title + ' =='); }

const html = fs.readFileSync(path.join(__dirname, '..', 'ui', 'index.html'), 'utf8');
const mainSrc = fs.readFileSync(path.join(__dirname, '..', 'main.py'), 'utf8');

section('ui: 版本卡片有导出按钮');
const btn = /onclick="event\.stopPropagation\(\);exportMrpack\([^"]*"[^>]*title="([^"]*)"/.exec(html);
check(btn !== null, '已安装版本的版本卡片应有 onclick=exportMrpack(...) 的按钮');
check(btn && btn[1].indexOf('mrpack') >= 0, '按钮 title 应点明是导出 mrpack, 实际 ' + (btn ? btn[1] : 'missing'));
check(/function exportMrpack\(versionId\)/.test(html), 'index.html 应含 function exportMrpack');
const exportFn = /function exportMrpack\(versionId\)\s*\{[\s\S]{0,400}?\n\s*\}/.exec(html);
check(exportFn && exportFn[0].indexOf('pythonInterface.exportMrpack') >= 0,
    'exportMrpack 应调用 pythonInterface.exportMrpack');
check(exportFn && exportFn[0].indexOf('showToast') >= 0,
    '点击后应先给反馈，否则后台打包期间用户会以为没点上');
check(/function onMrpackExported\(/.test(html), 'index.html 应含 function onMrpackExported');

section('main.py: 槽 + 信号 + 线程');
const slot = /def exportMrpack\(self, version_name: str\)/.exec(mainSrc);
check(slot !== null, '应有 exportMrpack 槽');
check(/@pyqtSlot\(str\)\s*\n\s*def exportMrpack\(/.test(mainSrc),
    'exportMrpack 应是 @pyqtSlot(str)');
const slotBody = /def exportMrpack\(self, version_name: str\)[\s\S]{0,900}?threading\.Thread/.exec(mainSrc);
check(slotBody !== null, 'exportMrpack 应把打包放进后台线程（否则同步 zip 会卡死 UI）');
check(slotBody && slotBody[0].indexOf('export_mrpack') >= 0,
    'exportMrpack 应调用 ModpackImporter.export_mrpack');
check(slotBody && slotBody[0].indexOf('mrpackExported.emit') >= 0,
    'exportMrpack 结果应经 mrpackExported 信号回传');
check(/mrpackExported\s*=\s*pyqtSignal\(str\)/.test(mainSrc),
    '应声明 mrpackExported = pyqtSignal(str)');

section('main.py: 信号接到 MainWindow 并推给 JS');
check(/self\.bridge\.mrpackExported\.connect\(self\._on_mrpack_exported\)/.test(mainSrc),
    '应在 MainWindow 里 connect mrpackExported');
const handler = /def _on_mrpack_exported\(self, data: str\)[\s\S]{0,400}?runJavaScript\([^)]*onMrpackExported/.exec(mainSrc);
check(handler !== null, '应有 _on_mrpack_exported 处理器');
check(handler && handler[0].indexOf('onMrpackExported') >= 0,
    '_on_mrpack_exported 应调用 JS 的 onMrpackExported');
const slotAll = /def exportMrpack\(self, version_name: str\)[\s\S]{0,900}?threading\.Thread/.exec(mainSrc);
check(slotAll && slotAll[0].indexOf('json.dumps') >= 0,
    '路径含反斜杠/引号，必须经 json.dumps 注入 JS 字面量');

console.log('\nPASS: ' + pass + ' FAIL: ' + fail);
process.exit(fail ? 1 : 0);
