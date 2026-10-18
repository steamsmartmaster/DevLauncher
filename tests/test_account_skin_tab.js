'use strict';
// 规格: 皮肤与披风 + 账户管理 从设置页分离到独立标签页 (在插件按钮上方)
const { extractFunc, html } = require('./extract_func');

let pass = 0, fail = 0;
const failures = [];
function check(cond, msg) {
  if (cond) pass++;
  else { fail++; failures.push(msg); console.log('  FAIL: ' + msg); }
}
function section(t) { console.log('\n== ' + t + ' =='); }
function count(hay, needle) { return hay.split(needle).length - 1; }

function slice(from, to) {
  const i = html.indexOf(from);
  if (i < 0) return null;
  const j = html.indexOf(to, i);
  return j < 0 ? html.slice(i) : html.slice(i, j);
}

const settingsBlock = slice('id="settingsPage"', '<div class="right-panel">');
const accountBlock = slice('id="accountPage"', 'id="pluginsPage"');
const navBlock = slice('<div class="nav-items">', '<div class="main-content">');

section('静态: 三个区块均可定位');
check(settingsBlock !== null, '应能定位 settingsPage 区块');
check(accountBlock !== null, '应能定位 accountPage 区块');
check(navBlock !== null, '应能定位侧栏 nav-items 区块');

section('静态: 「皮肤与披风」分组已离开设置页');
check(settingsBlock !== null && settingsBlock.indexOf('皮肤与披风') < 0,
  '设置页不得再含 皮肤与披风 分组标题');
check(settingsBlock !== null && settingsBlock.indexOf('id="skinPreview"') < 0,
  '设置页不得再含 #skinPreview');
check(settingsBlock !== null && settingsBlock.indexOf('id="capeList"') < 0,
  '设置页不得再含 #capeList');
check(settingsBlock !== null && settingsBlock.indexOf('id="skinVariant"') < 0,
  '设置页不得再含 #skinVariant');

section('静态: 账户页接管皮肤与披风全部控件');
check(accountBlock !== null && accountBlock.indexOf('皮肤与披风') >= 0,
  '账户页应含 皮肤与披风 分组标题');
check(accountBlock !== null && accountBlock.indexOf('id="skinPreview"') >= 0,
  '账户页应含 #skinPreview 预览图');
check(accountBlock !== null && accountBlock.indexOf('id="skinVariant"') >= 0,
  '账户页应含 #skinVariant 下拉');
check(accountBlock !== null && accountBlock.indexOf('id="capeList"') >= 0,
  '账户页应含 #capeList 披风列表');
check(accountBlock !== null && accountBlock.indexOf('id="skinsStatus"') >= 0,
  '账户页应含 #skinsStatus 状态位');
check(accountBlock !== null && accountBlock.indexOf('pickSkinFile()') >= 0,
  '账户页应保留 更换皮肤 按钮接线');
check(accountBlock !== null && accountBlock.indexOf('capeHide()') >= 0,
  '账户页应保留 隐藏披风 按钮接线');
check(accountBlock !== null && accountBlock.indexOf('id="accountList"') >= 0,
  '账户页应保留账户列表容器 (账户管理并存)');

section('静态: 文案全局只出现一次 (无重复分组)');
check(count(html, '皮肤与披风') === 1, '皮肤与披风 应全局仅 1 次 (实际 ' + count(html, '皮肤与披风') + ')');
check(count(html, 'id="skinPreview"') === 1, '#skinPreview 应全局仅 1 个 (实际 ' + count(html, 'id="skinPreview"') + ')');
check(count(html, 'id="capeList"') === 1, '#capeList 应全局仅 1 个 (实际 ' + count(html, 'id="capeList"') + ')');

section('静态: 皮肤/披风标签置顶为卡片上方的小标题 (不再竖排)');
function indexes(hay, needle) {
  const out = [];
  let i = hay.indexOf(needle);
  while (i >= 0) { out.push(i); i = hay.indexOf(needle, i + needle.length); }
  return out;
}
function cssRule(selector) {
  const i = html.indexOf(selector);
  if (i < 0) return null;
  const j = html.indexOf('}', i);
  return j < 0 ? null : html.slice(i, j + 1);
}
const capIdxs = accountBlock === null ? [] : indexes(accountBlock, 'skin-cape-caption');
const cardIdxs = accountBlock === null ? [] : indexes(accountBlock, 'settings-item--skin-cape');
check(capIdxs.length === 3, '账户页应有 3 个 .skin-cape-caption 小标题 (当前皮肤/披风/说明，实际 ' + capIdxs.length + ')');
check(count(html, '<div class="skin-cape-caption">') === 3,
  '小标题应为块级 <div> (width:100% 才能独占一行; <span> 会失效)');
check(cardIdxs.length === 3, '账户页应有 3 张 .settings-item--skin-cape 卡片 (实际 ' + cardIdxs.length + ')');
check(capIdxs.length === 3 && cardIdxs.length === 3 &&
  capIdxs.every(function (c, n) { return c < cardIdxs[n]; }),
  '每个小标题都应排在其卡片之前 (当前皮肤/披风/说明 均置顶)');
const labelIdxs = accountBlock === null ? [] : indexes(accountBlock, 'class="settings-item-label"');
check(labelIdxs.length === 0,
  '账户页不应再有被压缩成竖排的 .settings-item-label (共 ' + labelIdxs.length + ' 处)');
const capRule = cssRule('.skin-cape-caption {');
check(capRule !== null && capRule.indexOf('width: 100%') >= 0,
  '.skin-cape-caption 应占满一行 (置顶到卡片上方)');
check(capRule !== null && capRule.indexOf('flex: none') >= 0,
  '.skin-cape-caption 应设 flex: none (换行时不被压缩)');
const cardRule = cssRule('.settings-item.settings-item--skin-cape {');
check(cardRule !== null && cardRule.indexOf('flex-wrap: wrap') >= 0,
  '.settings-item--skin-cape 应允许换行 (长状态串不再挤扁标签)');
check(html.indexOf('.settings-item-label {') >= 0 && cssRule('.settings-item-label {') !== null &&
  cssRule('.settings-item-label {').indexOf('flex: 1') >= 0,
  '通用 .settings-item-label { flex: 1 } 不应被改动 (其他设置项外观不变)');

section('静态: 侧栏顺序 → 设置, 账户, 插件 (新页签在插件上方)');
const navPages = navBlock === null ? [] : (navBlock.match(/data-page="([^"]+)"/g) || [])
  .map(function (s) { return s.replace(/data-page="|"/g, ''); });
const expected = ['versions', 'download', 'mods', 'worlds', 'resourcepacks', 'settings', 'account', 'plugins'];
check(navPages.join(',') === expected.join(','),
  '侧栏页签顺序应为 ' + expected.join(',') + ' (实际 ' + navPages.join(',') + ')');
check(navPages.indexOf('account') === navPages.indexOf('plugins') - 1,
  '账户页签应紧邻插件页签上方 (account=' + navPages.indexOf('account') + ', plugins=' + navPages.indexOf('plugins') + ')');
check(navPages.indexOf('settings') < navPages.indexOf('account'),
  '账户页签应在设置页签之后');

section('静态: navigateTo 的 account 分支承担刷新');
const navSrc = extractFunc('navigateTo');
function branch(key) {
  if (navSrc === null) return null;
  const i = navSrc.indexOf("page === '" + key + "'");
  if (i < 0) return null;
  const rest = navSrc.slice(i);
  const j = rest.indexOf('} else if');
  return j < 0 ? rest : rest.slice(0, j);
}
const accBranch = branch('account');
const setBranch = branch('settings');
check(accBranch !== null, "navigateTo 应含 page === 'account' 分支");
check(accBranch !== null && accBranch.indexOf('getAccounts') >= 0,
  'account 分支应调 getAccounts');
check(accBranch !== null && accBranch.indexOf('skinsRefreshNow()') >= 0,
  'account 分支应调 skinsRefreshNow()');
check(setBranch === null || setBranch.indexOf('skinsRefreshNow') < 0,
  'settings 分支不应再调 skinsRefreshNow');

section('静态: 皮肤相关 JS 函数仍完整');
['skinsRefreshNow', 'pickSkinFile', 'onSkinFileSelected', 'equipCape', 'capeHide', 'onSkinsResult',
  'renderSkinsProfile', 'renderCapeList', 'setSkinsStatus']
  .forEach(function (n) {
    check(extractFunc(n) !== null, 'index.html 应仍含 function ' + n);
  });

section('静态: 披风预览 #capePreview 位于披风卡片内且排在列表前');
check(accountBlock !== null && count(accountBlock, 'id="capePreview"') === 1,
  '账户页应恰含 1 个 #capePreview (实际 ' + (accountBlock === null ? -1 : count(accountBlock, 'id="capePreview"')) + ')');
check(count(html, 'id="capePreview"') === 1,
  '#capePreview 应全局仅 1 个 (实际 ' + count(html, 'id="capePreview"') + ')');
const cpIdx = accountBlock === null ? -1 : accountBlock.indexOf('id="capePreview"');
const clIdx = accountBlock === null ? -1 : accountBlock.indexOf('id="capeList"');
check(cpIdx >= 0 && clIdx >= 0 && cpIdx < clIdx, '#capePreview 应排在 id="capeList" 之前 (即在披风卡片内)');
const capeCardStarts = accountBlock === null ? [] :
  indexes(accountBlock, '<div class="settings-item settings-item--skin-cape"');
let lastCardBeforeCp = -1;
capeCardStarts.forEach(function (c) { if (c < cpIdx) lastCardBeforeCp = c; });
check(lastCardBeforeCp >= 0,
  'id="capePreview" 之前应存在 .settings-item--skin-cape 卡片开头 (直接父卡片)');
check(lastCardBeforeCp >= 0 && accountBlock.slice(lastCardBeforeCp, cpIdx).indexOf('</div>') < 0,
  '#capePreview 应是卡片的直接子元素 (卡片开头与预览之间不得有其他元素闭合)');

section('静态: renderCapeList 驱动披风预览 (有图显示 / 无图隐藏 / 空列表也隐藏)');
const capeFn = extractFunc('renderCapeList');
check(capeFn !== null && capeFn.indexOf('capePreview') >= 0,
  'renderCapeList 应引用 #capePreview');
check(capeFn !== null && capeFn.indexOf('capePreview') >= 0 &&
  capeFn.indexOf('.src') >= 0 && capeFn.indexOf('.url') >= 0,
  'renderCapeList 应把披风 url 写入预览 src');
check(capeFn !== null && capeFn.indexOf("'none'") >= 0,
  'renderCapeList 无 url 时应把预览 display 设为 none');
const cpPos = capeFn === null ? -1 : capeFn.indexOf('capePreview');
const noCapePos = capeFn === null ? -1 : capeFn.indexOf('暂无披风');
check(cpPos >= 0 && noCapePos >= 0 && cpPos < noCapePos,
  '#capePreview 处理须排在 暂无披风 早退之前 (空列表分支同样会隐藏预览)');

section('静态: #skinVariant 改用共享 .settings-input (深色主题, 无内联配色)');
function extractSelectTag(id) {
  const i = html.indexOf('id="' + id + '"');
  if (i < 0) return null;
  const a = html.lastIndexOf('<select', i);
  const b = html.indexOf('>', i);
  return (a < 0 || b < 0) ? null : html.slice(a, b + 1);
}
const svTag = extractSelectTag('skinVariant');
check(svTag !== null && svTag.indexOf('class="settings-input"') >= 0,
  '#skinVariant 应带 class="settings-input" (与其他 select 同款)');
const svStyle = svTag === null ? '' : (svTag.match(/style="([^"]*)"/) || [])[1] || '';
check(svStyle.length > 0 && svStyle.indexOf('background') < 0,
  '#skinVariant 内联样式不得含 background (原生浅色主题残留)');
check(svStyle.indexOf('border') < 0, '#skinVariant 内联样式不得含 border');
check(svStyle.indexOf('color:') < 0, '#skinVariant 内联样式不得含 color:');
check(svStyle.indexOf('width:auto') >= 0,
  '#skinVariant 内联样式应含 width:auto (压过 .settings-input 的 120px)');
check(svStyle.indexOf('min-width') >= 0,
  '#skinVariant 内联样式应含 min-width (选项文字不被裁剪)');

section('静态: 微软登录按钮为四色品牌 Logo (3 处, 无单色描边残留)');
const msLogo = '<svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;">' +
  '<rect x="2" y="2" width="9" height="9" fill="#F25022"/>' +
  '<rect x="13" y="2" width="9" height="9" fill="#7FBA00"/>' +
  '<rect x="2" y="13" width="9" height="9" fill="#00A4EF"/>' +
  '<rect x="13" y="13" width="9" height="9" fill="#FFB900"/></svg>';
check(count(html, msLogo) === 3,
  '四色微软 Logo 应恰好 3 处 (实际 ' + count(html, msLogo) + ')');
let monoMs = 0;
let rectIdx = html.indexOf('<rect x="2" y="2"');
while (rectIdx >= 0) {
  const svgA = html.lastIndexOf('<svg', rectIdx);
  const svgB = html.indexOf('</svg>', rectIdx);
  const svgTag = (svgA >= 0 && svgB >= 0) ? html.slice(svgA, svgB + 6) : '';
  if (svgTag.indexOf('stroke="white"') >= 0) monoMs++;
  rectIdx = html.indexOf('<rect x="2" y="2"', rectIdx + 1);
}
check(monoMs === 0,
  'stroke="white" 与 <rect x="2" y="2" 组合应为 0 处 (实际 ' + monoMs + ')');
const msA = html.indexOf('<rect x="2" y="2"');
const msSvg = msA < 0 ? '' : html.slice(html.lastIndexOf('<svg', msA), html.indexOf('</svg>', msA) + 6);
['#F25022', '#7FBA00', '#00A4EF', '#FFB900'].forEach(function (hex) {
  check(msSvg.indexOf(hex) >= 0, '微软 Logo 标签内应含品牌色 ' + hex);
});

console.log('\n==============================');
console.log('PASS: ' + pass + '  FAIL: ' + fail);
if (fail) {
  console.log('失败项:');
  failures.forEach(function (f) { console.log('  - ' + f); });
}
process.exit(fail ? 1 : 0);
