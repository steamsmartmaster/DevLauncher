// 图形化游戏设置（options.txt）：卡片 → 页面 → 按控件类型渲染 → 只回传改动 → 存盘。
// 前端把值拼进 HTML，所以任何动态内容都必须过 escapeHtml。
const fs = require('fs');
const path = require('path');

let pass = 0, fail = 0;
function check(cond, msg) { if (cond) pass++; else { fail++; console.log('  FAIL: ' + msg); } }
function section(title) { console.log('\n== ' + title + ' =='); }

// 按函数名切窗口而不是用非贪婪正则：函数体内有嵌套花括号，
// 正则会在第一个 `}` 就收口，导致断言查的是半截函数。
function fnSrc(src, name, span) {
    var i = src.indexOf('function ' + name + '(');
    return i < 0 ? '' : src.slice(i, i + (span || 1200));
}

const html = fs.readFileSync(path.join(__dirname, '..', 'ui', 'index.html'), 'utf8');
const mainSrc = fs.readFileSync(path.join(__dirname, '..', 'main.py'), 'utf8');

section('入口：版本管理页有卡片，页面存在');
check(/class="version-mgmt-card" onclick="openGameOptions\(\)"/.test(html),
    '版本管理卡片网格应有 onclick="openGameOptions()" 的卡片');
check(html.indexOf('id="versionGameOptionsPage"') >= 0, '应有 versionGameOptionsPage 页面');
check(/function openGameOptions\(/.test(html), '应有 function openGameOptions');
const openSrc = fnSrc(html, 'openGameOptions', 700);
check(openSrc.indexOf("navigateTo('versionGameOptions')") >= 0,
    'openGameOptions 应导航到 versionGameOptions 页');
check(openSrc.indexOf('pythonInterface.getGameOptions') >= 0,
    'openGameOptions 应向后端要数据');
check(openSrc.indexOf('selectedVersion') >= 0,
    'openGameOptions 应传 selectedVersion');

section('渲染：按分组与控件类型');
check(/function renderGameOptions\(/.test(html), '应有 function renderGameOptions');
const rsrc = fnSrc(html, 'renderGameOptions', 4000);
check(rsrc.length > 0, 'renderGameOptions 应能被抽取');
check(rsrc.indexOf('type === \'bool\'') >= 0, 'renderGameOptions 应按 bool 渲染开关');
check(/type === 'int'|type === 'float'/.test(rsrc), 'renderGameOptions 应按 int/float 渲染滑条');
check(rsrc.indexOf('type === \'choice\'') >= 0, 'renderGameOptions 应按 choice 渲染下拉');
check(rsrc.indexOf('escapeHtml') >= 0, '渲染 label/hint/值必须过 escapeHtml（它们来自 options.txt）');
check(rsrc.indexOf('data-key') >= 0, '控件应带 data-key 以便收集改动');
check(/function collectGameOptionsUpdates\(/.test(html), '应有 function collectGameOptionsUpdates');

const csrc = fnSrc(html, 'collectGameOptionsUpdates', 1200);
check(csrc.length > 0, 'collectGameOptionsUpdates 应能被抽取');
check(csrc.indexOf('data-orig') >= 0, '应记录原始值，否则无法区分「用户改的」和「本来就有的」');

section('保存：走桥接');
check(/function saveGameOptions\(/.test(html), '应有 function saveGameOptions');
const ssrc = fnSrc(html, 'saveGameOptions', 900);
check(ssrc.indexOf('pythonInterface.saveGameOptions') >= 0,
    'saveGameOptions 应调用 pythonInterface.saveGameOptions');
check(ssrc.indexOf('collectGameOptionsUpdates') >= 0,
    'saveGameOptions 应只提交改动');
check(ssrc.indexOf('JSON.stringify') >= 0, '改动须序列化为 JSON 字符串');
check(ssrc.indexOf('showToast') >= 0, '提交后应有反馈');

section('main.py：信号 + 槽');
check(/gameOptionsLoaded\s*=\s*pyqtSignal\(str\)/.test(mainSrc), '应声明 gameOptionsLoaded 信号');
check(/gameOptionsSaved\s*=\s*pyqtSignal\(str\)/.test(mainSrc), '应声明 gameOptionsSaved 信号');
check(/@pyqtSlot\(str\)\s*\n\s*def getGameOptions\(/.test(mainSrc), '应有 @pyqtSlot(str) getGameOptions');
check(/@pyqtSlot\(str, str\)\s*\n\s*def saveGameOptions\(/.test(mainSrc), '应有 @pyqtSlot(str, str) saveGameOptions');

const getAt = mainSrc.indexOf('def getGameOptions(self, version_id: str)');
const getBody = getAt < 0 ? '' : mainSrc.slice(getAt, getAt + 1600);
check(getBody.indexOf('threading.Thread') >= 0,
    'getGameOptions 应在后台线程读文件（网络无关，但文件 IO 仍不该在 UI 线程）');
check(getBody.indexOf('read_options') >= 0, 'getGameOptions 应用 game_options.read_options');
check(getBody.indexOf('options_path') >= 0, 'getGameOptions 应用 options_path 解析隔离路径');
check(getBody.indexOf('list_option_specs') >= 0, 'getGameOptions 应下发字段目录给 UI');

const saveAt = mainSrc.indexOf('def saveGameOptions(self, version_id: str, updates_json: str)');
const saveBody = saveAt < 0 ? '' : mainSrc.slice(saveAt, saveAt + 1400);
check(saveBody.indexOf('threading.Thread') >= 0, 'saveGameOptions 应在后台线程写文件');
check(saveBody.indexOf('build_updates') >= 0,
    'saveGameOptions 应用 build_updates 合并（保住未知键）');
check(saveBody.indexOf('write_options') >= 0, 'saveGameOptions 应用 write_options 落盘');

section('main.py：信号接到 MainWindow 并推给 JS');
check(/self\.bridge\.gameOptionsLoaded\.connect\(self\._on_game_options_loaded\)/.test(mainSrc),
    '应 connect gameOptionsLoaded');
check(/self\.bridge\.gameOptionsSaved\.connect\(self\._on_game_options_saved\)/.test(mainSrc),
    '应 connect gameOptionsSaved');
check(/def _on_game_options_loaded\(self, data: str\)[\s\S]{0,300}?runJavaScript\([^)]*renderGameOptions/.test(mainSrc),
    '_on_game_options_loaded 应调用 JS renderGameOptions');
check(/def _on_game_options_saved\(self, data: str\)[\s\S]{0,300}?runJavaScript\([^)]*(showToast|onGameOptionsSaved)/.test(mainSrc),
    '_on_game_options_saved 应把结果推给 JS');

console.log('\nPASS: ' + pass + ' FAIL: ' + fail);
process.exit(fail ? 1 : 0);
