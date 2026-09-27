'use strict';
// 加载器兼容矩阵测试 (TDD RED/GREEN)
// 规则来源: HMCL InstallerItemGroup (HMCL/src/main/java/org/jackhuang/hmcl/ui/InstallerItem.java:172-178)
//   mutualIncompatible(forge, fabric, quilt, neoforge, ...)      -> 四者两两互斥
//   addIncompatibles(optiFine, fabric, quilt, neoforge, ...)     -> OptiFine 与三者互斥; 与 Forge 兼容
//   addIncompatibles(fabricApi, forge, ..., optiFine, ...)       -> Fabric API 与 forge/neoforge/optifine 互斥, 与 fabric/quilt 兼容 (本仓库无 fabricapi 卡, 仅作规则对照)
// BUG(旧): forge:[neoforge], fabric:[quilt] 等只记了一半 → 装了 Forge 后 Fabric/Quilt 仍可点安装
const fs = require('fs');
const { extractFunc, html } = require('./extract_func');

let pass = 0, fail = 0;
const failures = [];
function check(cond, msg) {
  if (cond) pass++;
  else { fail++; failures.push(msg); console.log('  FAIL: ' + msg); }
}
function section(t) { console.log('\n== ' + t + ' =='); }

// ---------------- 提取被测代码 ----------------
function extractLoaderIncompatible() {
  const m = html.match(/var LOADER_INCOMPATIBLE = (\{[\s\S]*?\});/);
  if (!m) throw new Error('index.html 缺少 LOADER_INCOMPATIBLE');
  return new Function('return (' + m[1] + ')')();
}

const MAP = extractLoaderIncompatible();

function pairsOf(map, a) {
  return (map[a] || []).slice().sort();
}
function expectSet(actual, expected, msg) {
  const e = expected.slice().sort();
  check(JSON.stringify(actual) === JSON.stringify(e),
    msg + ' 期望[' + e.join(',') + '] 实际[' + actual.join(',') + ']');
}

section('HMCL 矩阵: forge/fabric/quilt/neoforge 两两互斥');
expectSet(pairsOf(MAP, 'forge'), ['fabric', 'neoforge', 'quilt'], 'forge 的互斥集');
expectSet(pairsOf(MAP, 'fabric'), ['forge', 'neoforge', 'optifine', 'quilt'], 'fabric 的互斥集');
expectSet(pairsOf(MAP, 'quilt'), ['fabric', 'forge', 'neoforge', 'optifine'], 'quilt 的互斥集');
expectSet(pairsOf(MAP, 'neoforge'), ['fabric', 'forge', 'optifine', 'quilt'], 'neoforge 的互斥集');

section('HMCL 矩阵: OptiFine 与 fabric/quilt/neoforge 互斥, 与 Forge 兼容');
expectSet(pairsOf(MAP, 'optifine'), ['fabric', 'neoforge', 'quilt'], 'optifine 的互斥集');
check(!(MAP.forge || []).includes('optifine'), 'forge 不应与 optifine 互斥');
check(!(MAP.optifine || []).includes('forge'), 'optifine 不应与 forge 互斥 (HMCL: 二者可共存)');

section('矩阵对称性: a 互斥 b 当且仅当 b 互斥 a');
const KEYS = ['forge', 'fabric', 'quilt', 'neoforge', 'optifine'];
for (const a of KEYS) {
  for (const b of KEYS) {
    if (a === b) continue;
    const ab = (MAP[a] || []).includes(b);
    const ba = (MAP[b] || []).includes(a);
    check(ab === ba, '对称性破坏: ' + a + '->' + b + '=' + ab + ', ' + b + '->' + a + '=' + ba);
    check(!ab || !MAP[a].includes(a), a + ' 不应与自身互斥');
  }
}

// ---------------- markIncompatibleLoaders 行为 (安装弹窗) ----------------
const markSrc = extractFunc('markIncompatibleLoaders');
if (!markSrc) throw new Error('index.html 缺少 markIncompatibleLoaders');

function makeBtn(loader) {
  const classes = new Set();
  const attrs = {};
  return {
    dataset: { loader: loader },
    disabled: false,
    classList: {
      add: c => classes.add(c),
      remove: c => classes.delete(c),
      contains: c => classes.has(c)
    },
    setAttribute: (k, v) => { attrs[k] = v; },
    removeAttribute: k => { delete attrs[k]; },
    get tooltip() { return attrs['data-tooltip']; },
    get isIncompatible() { return classes.has('incompatible'); }
  };
}

function runMark(installedTypes) {
  const loaders = ['none', 'fabric', 'forge', 'neoforge', 'quilt', 'optifine'];
  const btns = loaders.map(makeBtn);
  const doc = {
    querySelectorAll: sel =>
      sel === '#modLoaderModal .mod-loader-btn' ? btns : []
  };
  const fn = new Function('document', 'LOADER_INCOMPATIBLE',
    markSrc + '\nreturn markIncompatibleLoaders;')(doc, MAP);
  fn(installedTypes);
  const byLoader = {};
  loaders.forEach((l, i) => { byLoader[l] = btns[i]; });
  return byLoader;
}

section('弹窗: 装了 Forge → Fabric/Quilt/NeoForge 灰, OptiFine 可装, Forge 已安装');
let r = runMark(['forge']);
check(r.fabric.isIncompatible && r.fabric.tooltip === '与 Forge 不兼容', 'fabric 应显示 与 Forge 不兼容');
check(r.quilt.isIncompatible && r.quilt.tooltip === '与 Forge 不兼容', 'quilt 应显示 与 Forge 不兼容');
check(r.neoforge.isIncompatible && r.neoforge.tooltip === '与 Forge 不兼容', 'neoforge 应显示 与 Forge 不兼容');
check(!r.optifine.isIncompatible && !r.optifine.disabled && !r.optifine.tooltip, 'optifine 应可安装 (HMCL: OptiFine+Forge 兼容)');
check(r.forge.isIncompatible && r.forge.tooltip === '已安装', 'forge 应显示已安装');
check(!r.none.disabled, 'none 不应被禁用');

section('弹窗: 装了 Fabric → Forge/NeoForge/Quilt/OptiFine 全灰, Fabric 已安装');
r = runMark(['fabric']);
check(r.forge.isIncompatible && r.forge.tooltip === '与 Fabric 不兼容', 'forge 应与 Fabric 不兼容');
check(r.neoforge.isIncompatible && r.neoforge.tooltip === '与 Fabric 不兼容', 'neoforge 应与 Fabric 不兼容');
check(r.quilt.isIncompatible && r.quilt.tooltip === '与 Fabric 不兼容', 'quilt 应与 Fabric 不兼容 (旧代码漏)');
check(r.optifine.isIncompatible && r.optifine.tooltip === '与 Fabric 不兼容', 'optifine 应与 Fabric 不兼容');
check(r.fabric.tooltip === '已安装', 'fabric 应显示已安装');

section('弹窗: 装了 OptiFine → Forge 可装, Fabric/Quilt/NeoForge 灰');
r = runMark(['optifine']);
check(!r.forge.isIncompatible && !r.forge.disabled, 'forge 与 OptiFine 兼容可装');
check(r.fabric.isIncompatible && r.fabric.tooltip === '与 OptiFine 不兼容', 'fabric 应与 OptiFine 不兼容');
check(r.quilt.isIncompatible && r.quilt.tooltip === '与 OptiFine 不兼容', 'quilt 应与 OptiFine 不兼容');
check(r.neoforge.isIncompatible && r.neoforge.tooltip === '与 OptiFine 不兼容', 'neoforge 应与 OptiFine 不兼容');
check(r.optifine.tooltip === '已安装', 'optifine 应显示已安装');

section('弹窗: 未装任何加载器 → 全部可点');
r = runMark([]);
for (const l of ['fabric', 'forge', 'neoforge', 'quilt', 'optifine']) {
  check(!r[l].isIncompatible && !r[l].disabled && !r[l].tooltip, l + ' 应可安装且无提示');
}

// ---------------- updateInstalledLoaders 安装行 (模组加载器页) ----------------
const updateSrc = extractFunc('updateInstalledLoaders');
if (!updateSrc) throw new Error('index.html 缺少 updateInstalledLoaders');

function makeEl(tag) {
  const el = { tagName: tag, children: [], className: '', _html: '' };
  Object.defineProperty(el, 'innerHTML', {
    get() { return el._html; },
    set(v) { el._html = String(v); el.children.length = 0; }
  });
  el.appendChild = c => { if (c && c._fragment) { c.children.forEach(x => el.children.push(x)); c.children.length = 0; } else if (c) { el.children.push(c); } return c; };
  return el;
}

function runUpdate(loaders) {
  const byId = new Map();
  const doc = {
    getElementById(id) {
      if (id === 'modLoaderModal') return { style: { display: 'none' } };
      if (!byId.has(id)) byId.set(id, makeEl('div'));
      return byId.get(id);
    },
    createElement: t => makeEl(t),
    createDocumentFragment() { const f = makeEl('#f'); f._fragment = true; return f; }
  };
  const fn = new Function('document', 'LOADER_INCOMPATIBLE',
    updateSrc + '\nreturn updateInstalledLoaders;')(doc, MAP);
  fn({ version_id: 'v1', loaders: loaders });
  return doc.getElementById('modLoadersList').innerHTML;
}

section('加载器页: 装了 Forge → 安装行 Fabric/Quilt/NeoForge 灰, OptiFine 可点');
let out = runUpdate([{ type: 'forge', version: '55.1.13', name: 'Forge' }]);
check(out.includes('<button class="mod-loader-btn incompatible" disabled data-tooltip="与 Forge 不兼容">Fabric</button>'), '安装行 fabric 应灰并提示与 Forge 不兼容');
check(out.includes('<button class="mod-loader-btn incompatible" disabled data-tooltip="与 Forge 不兼容">Quilt</button>'), '安装行 quilt 应灰');
check(out.includes('<button class="mod-loader-btn incompatible" disabled data-tooltip="与 Forge 不兼容">NeoForge</button>'), '安装行 neoforge 应灰');
check(out.includes('<button class="mod-loader-btn" onclick="installLoaderToVersion(\'v1\', \'optifine\')">OptiFine</button>'), '安装行 optifine 应可点 (与 Forge 兼容)');
check(!out.includes('>OptiFine</button>') || !/incompatible" disabled data-tooltip="[^"]*">OptiFine/.test(out), 'optifine 不应带 incompatible');
check(out.includes('55.1.13') || out.includes('Forge'), '已安装卡片应显示 Forge');

section('加载器页: 装了 Fabric → 安装行 Forge/NeoForge/Quilt/OptiFine 全灰');
out = runUpdate([{ type: 'fabric', version: '0.19.5', name: 'Fabric' }]);
check(out.includes('<button class="mod-loader-btn incompatible" disabled data-tooltip="与 Fabric 不兼容">Forge</button>'), '安装行 forge 应灰');
check(out.includes('<button class="mod-loader-btn incompatible" disabled data-tooltip="与 Fabric 不兼容">NeoForge</button>'), '安装行 neoforge 应灰');
check(out.includes('<button class="mod-loader-btn incompatible" disabled data-tooltip="与 Fabric 不兼容">Quilt</button>'), '安装行 quilt 应灰');
check(out.includes('<button class="mod-loader-btn incompatible" disabled data-tooltip="与 Fabric 不兼容">OptiFine</button>'), '安装行 optifine 应灰');
check(!out.includes('data-tooltip="与 Fabric 不兼容">Fabric'), 'fabric 自身不在安装行(已安装)');

// ---------------- 静态接线 ----------------
section('静态: 两处消费同一矩阵');
const uses = (html.match(/LOADER_INCOMPATIBLE/g) || []).length;
check(uses >= 3, 'LOADER_INCOMPATIBLE 应被定义并被两处消费 (出现≥3次), 实际 ' + uses);
check(html.includes("markIncompatibleLoaders(installedTypes)"), '弹窗应调用 markIncompatibleLoaders');
check(html.includes('var incompatible = LOADER_INCOMPATIBLE[type]'), '安装行应读取 LOADER_INCOMPATIBLE');

console.log('\n==============================');
console.log('PASS: ' + pass + '  FAIL: ' + fail);
if (fail > 0) {
  console.log('\n失败清单:');
  failures.forEach(f => console.log(' - ' + f));
  process.exit(1);
}
