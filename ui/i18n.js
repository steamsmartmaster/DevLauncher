(function (global) {
  'use strict';

  var DATA = global.I18N_DATA || { map: {}, mapEn: {}, zh: {}, en: {} };
  var STORE_KEY = 'devlauncher.locale';
  var LOCALES = ['zh-CN', 'en'];
  var DEFAULT_LOCALE = 'zh-CN';
  var ATTRS = ['title', 'placeholder', 'aria-label'];
  var CJK = /[㐀-鿿豈-﫿]/;
  var applying = false;
  var current = null;
  var observer = null;

  var keysByLen = null;

  function cjkKeys() {
    if (keysByLen) return keysByLen;
    var out = [];
    for (var k in DATA.map) {
      if (DATA.map.hasOwnProperty(k) && CJK.test(k)) out.push(k);
    }
    out.sort(function (a, b) { return b.length - a.length; });
    keysByLen = out;
    return out;
  }

  function readStore() {
    try {
      return global.localStorage ? global.localStorage.getItem(STORE_KEY) : null;
    } catch (e) { return null; }
  }

  function writeStore(v) {
    try {
      if (global.localStorage) global.localStorage.setItem(STORE_KEY, v);
    } catch (e) { }
  }

  function detectLocale() {
    var saved = readStore();
    if (saved && LOCALES.indexOf(saved) >= 0) return saved;
    var nav = (global.navigator && global.navigator.language) || '';
    return /^en\b/i.test(nav) ? 'en' : DEFAULT_LOCALE;
  }

  function locale() {
    if (!current) current = detectLocale();
    return current;
  }

  function table() {
    return locale() === 'en' ? DATA.en : DATA.zh;
  }

  function t(key, vars) {
    var raw = table()[key];
    if (raw === undefined) raw = DATA.zh[key];
    if (raw === undefined) return key;
    if (vars) {
      raw = raw.replace(/\{(\w+)\}/g, function (_m, name) {
        return Object.prototype.hasOwnProperty.call(vars, name)
          ? String(vars[name]) : '{' + name + '}';
      });
    }
    return raw;
  }

  function lookup(text) {
    var key = DATA.map[text];
    if (key !== undefined) return table()[key];
    key = DATA.mapEn[text];
    if (key !== undefined) return table()[key];
    return null;
  }

  function spliceZH(core) {
    var keys = cjkKeys();
    var out = '';
    var i = 0;
    while (i < core.length) {
      var hit = null;
      for (var j = 0; j < keys.length; j++) {
        if (core.substr(i, keys[j].length) === keys[j]) { hit = keys[j]; break; }
      }
      if (hit) {
        var v = table()[DATA.map[hit]];
        out += (v === undefined ? hit : v);
        i += hit.length;
      } else {
        out += core.charAt(i);
        i++;
      }
    }
    return out;
  }

  function convert(core) {
    if (!core) return core;
    var wantEN = locale() === 'en';
    var isCJK = CJK.test(core);
    if (wantEN && !isCJK) return null;
    if (!wantEN && isCJK) return null;
    var direct = lookup(core);
    if (direct !== null && direct !== core) return direct;
    if (wantEN) {
      var spliced = spliceZH(core);
      return spliced === core ? null : spliced;
    }
    return null;
  }

  function translateString(s) {
    if (typeof s !== 'string' || !s) return null;
    var lead = (s.match(/^\s*/) || [''])[0];
    var tail = (s.match(/\s*$/) || [''])[0];
    var core = s.slice(lead.length, s.length - tail.length);
    var next = convert(core);
    if (next === null) return null;
    return lead + next + tail;
  }

  function walkText(root) {
    if (!root) return;
    var doc = root.ownerDocument || document;
    var walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var nodes = [];
    var n;
    while ((n = walker.nextNode())) nodes.push(n);
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      if (!node.nodeValue || node.parentNode === null) continue;
      var tag = node.parentNode.nodeName;
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TEXTAREA') continue;
      var next = translateString(node.nodeValue);
      if (next !== null && next !== node.nodeValue) node.nodeValue = next;
    }
  }

  function walkAttrs(root) {
    var els = [];
    var all;
    if (root.nodeType === 1) {
      els.push(root);
      all = root.querySelectorAll(ATTRS.map(function (a) {
        return '[' + a + ']';
      }).join(','));
      for (var i = 0; i < all.length; i++) els.push(all[i]);
    } else if (root.nodeType === 9) {
      all = root.querySelectorAll(ATTRS.map(function (a) {
        return '[' + a + ']';
      }).join(','));
      for (var j = 0; j < all.length; j++) els.push(all[j]);
    }
    for (var e = 0; e < els.length; e++) {
      for (var a = 0; a < ATTRS.length; a++) {
        var name = ATTRS[a];
        var val = els[e].getAttribute(name);
        if (!val) continue;
        var next = translateString(val);
        if (next !== null && next !== val) els[e].setAttribute(name, next);
      }
    }
  }

  function translate(root) {
    if (!root) return;
    applying = true;
    try {
      walkText(root);
      walkAttrs(root);
    } finally {
      applying = false;
    }
  }

  function setLocale(loc) {
    if (LOCALES.indexOf(loc) < 0) return false;
    current = loc;
    writeStore(loc);
    translate(document);
    var ev;
    try {
      ev = new CustomEvent('i18n:change', { detail: { locale: loc } });
    } catch (e) {
      ev = document.createEvent('CustomEvent');
      ev.initCustomEvent('i18n:change', false, false, { locale: loc });
    }
    document.dispatchEvent(ev);
    return true;
  }

  function startObserver() {
    if (!global.MutationObserver || observer) return;
    observer = new MutationObserver(function (records) {
      if (applying) return;
      for (var i = 0; i < records.length; i++) {
        var r = records[i];
        if (r.type === 'characterData' && r.target) {
          if (r.target.nodeName === 'SCRIPT' || r.target.nodeName === 'STYLE') continue;
          translate(r.target.parentNode || r.target);
          return;
        }
        for (var j = 0; j < r.addedNodes.length; j++) {
          var node = r.addedNodes[j];
          if (node.nodeType === 1 || node.nodeType === 3) translate(node);
        }
      }
    });
    observer.observe(document.documentElement, {
      childList: true, subtree: true, characterData: true
    });
  }

  function boot() {
    current = detectLocale();
    translate(document);
    startObserver();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  global.I18N = {
    LOCALES: LOCALES,
    locale: locale,
    setLocale: setLocale,
    detectLocale: detectLocale,
    t: t,
    translate: translate,
    lookup: lookup
  };
})(window);
