// 页面切换性能：重列表卡片跳过离屏布局（content-visibility）
// 红→绿 TDD：先断言样式契约，实现后转 GREEN
// 实测依据：下载页 105 张 .version-card 时，切换 .page.active 的样式+布局中位数 59.3ms
// （约 3.5 帧）；加 content-visibility 后降至 6.9ms，截图逐像素无差异。
const fs = require('fs');
const path = require('path');
const { html } = require('./extract_func.js');

let pass = 0, fail = 0;
function check(cond, msg) {
    if (cond) { pass++; } else { fail++; console.log('  FAIL: ' + msg); }
}
function section(title) { console.log('\n== ' + title + ' =='); }

function ruleOf(selectorRe) {
    const m = html.match(selectorRe);
    return m ? m[0] : '';
}

section('CSS: .version-card 离屏跳过布局');
const cardCss = ruleOf(/\.version-card\s*\{[^}]*\}/);
check(cardCss.length > 0, '应存在 .version-card 样式规则');
check(/content-visibility:\s*auto/.test(cardCss),
    '.version-card 应含 content-visibility: auto（实测: ' +
    (cardCss.match(/content-visibility:[^;]*/) || ['未找到'])[0] + '）');

section('CSS: contain-intrinsic-size 占位高度');
check(/contain-intrinsic-size:\s*auto\s*\d+px/.test(cardCss),
    '.version-card 应含 contain-intrinsic-size: auto <N>px（防止滚动条跳动），实测: ' +
    (cardCss.match(/contain-intrinsic-size:[^;]*/) || ['未找到'])[0]);
const sizePx = /contain-intrinsic-size:\s*auto\s*(\d+)px/.exec(cardCss);
const px = sizePx ? parseInt(sizePx[1], 10) : 0;
check(px >= 80 && px <= 240,
    'contain-intrinsic-size 的占位高度应落在卡片实际高度区间 [80,240]px，实测: ' + px + 'px');

section('CSS: 不使用 contain: content（会破坏网格滚动）');
check(!/contain:\s*content/.test(cardCss),
    '.version-card 不应使用 contain: content（实测该写法无收益且影响内在尺寸）');

section('回归: 版本网格仍为 CSS Grid 且卡片可点');
check(/\.version-grid\s*\{[^}]*\}/.test(html), '应保留 .version-grid 样式');
check(/grid-template-columns:\s*repeat\(auto-fill/.test(ruleOf(/\.version-grid\s*\{[^}]*\}/)),
    '.version-grid 应保持 auto-fill 网格布局');
check(/\.version-card:hover/.test(html), '应保留 .version-card:hover 效果');

console.log('\n===============================');
console.log('PASS: ' + pass + '  FAIL: ' + fail);
console.log('===============================');
process.exit(fail > 0 ? 1 : 0);
