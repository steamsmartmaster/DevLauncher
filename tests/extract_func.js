'use strict';
// 共享: 从 index.html 抽取函数源码 (花括号配对, 字符串/注释感知)
const fs = require('fs');
const path = require('path');

const INDEX = path.join(__dirname, '..', 'ui', 'index.html');
const html = fs.readFileSync(INDEX, 'utf8');

function skipString(s, i) {
  const q = s[i];
  i++;
  while (i < s.length) {
    if (s[i] === '\\') { i += 2; continue; }
    if (s[i] === q) return i;
    i++;
  }
  return i;
}

function extractFunc(name) {
  const re = new RegExp('function\\s+' + name + '\\s*\\(');
  const m = re.exec(html);
  if (!m) return null;
  let i = m.index + m[0].length - 1; // 指向 '('
  let depth = 0;
  for (; i < html.length; i++) {
    const c = html[i];
    if (c === '(') depth++;
    else if (c === ')') { depth--; if (depth === 0) break; }
  }
  i = html.indexOf('{', i);
  if (i < 0) return null;
  let d = 0;
  for (; i < html.length; i++) {
    const c = html[i];
    if (c === "'" || c === '"' || c === '`') { i = skipString(html, i); continue; }
    if (c === '/' && html[i + 1] === '/') {
      const nl = html.indexOf('\n', i);
      if (nl < 0) return null;
      i = nl;
      continue;
    }
    if (c === '/' && html[i + 1] === '*') {
      const e = html.indexOf('*/', i + 2);
      if (e < 0) return null;
      i = e + 1;
      continue;
    }
    if (c === '{') d++;
    else if (c === '}') { d--; if (d === 0) return html.slice(m.index, i + 1); }
  }
  return null;
}

module.exports = { extractFunc, html, INDEX };
