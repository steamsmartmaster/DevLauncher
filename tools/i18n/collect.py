# -*- coding: utf-8 -*-
"""Extract every user-facing Chinese string from ui/index.html.

Markup text, title/placeholder/aria-label attributes and the three JS string
flavours are collected into strings.json, which build.py then turns into
ui/i18n_dict.js. Run collect.py whenever copy is added to the UI.
"""
import hashlib
import json
import pathlib
import re
from collections import Counter
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "ui" / "index.html"
OUT = pathlib.Path(__file__).resolve().parent / "strings.json"
CJK = re.compile(r"[一-鿿]")


def key_for(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


class Walker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raw_text = []
        self.blocks = []
        self.attrs = []
        self.scripts = []
        self._in_raw = 0
        self._raw_buf = []
        self._script_depth = 0

    def _flush_text(self):
        if self.raw_text:
            self.blocks.append("".join(self.raw_text))
            self.raw_text = []

    def handle_starttag(self, tag, attrs):
        self._flush_text()
        if tag in ("script", "style"):
            if tag == "script":
                self._script_depth += 1
            self._in_raw += 1
            self._raw_buf = []
        for k, v in attrs:
            if k in ("title", "placeholder", "aria-label") and v and CJK.search(v):
                self.attrs.append(v.strip())

    def handle_endtag(self, tag):
        self._flush_text()
        if tag in ("script", "style") and self._in_raw:
            if tag == "script" and self._script_depth:
                self._script_depth -= 1
                self.scripts.append("".join(self._raw_buf))
            self._in_raw -= 1
            self._raw_buf = []

    def handle_data(self, data):
        if self._in_raw:
            self._raw_buf.append(data)
            return
        self.raw_text.append(data)

    def finish(self):
        self._flush_text()
        self.close()


def collect():
    raw = SRC.read_text(encoding="utf-8")
    w = Walker()
    w.feed(raw)
    w.finish()

    found = {}

    def add(s, kind):
        s = " ".join(s.split())
        if not s or not CJK.search(s):
            return
        found.setdefault(s, {"key": key_for(s), "kinds": []})
        if kind not in found[s]["kinds"]:
            found[s]["kinds"].append(kind)

    for b in w.blocks:
        add(b, "html_text")
    for a in w.attrs:
        add(a, "attr")

    script_src = "\n".join(w.scripts)
    for m in re.finditer(r"'([^'\\\n]*)'", script_src):
        add(m.group(1), "js_sq")
    for m in re.finditer(r'"([^"\\\n]*)"', script_src):
        add(m.group(1), "js_dq")
    for m in re.finditer(r"`([^`]*)`", script_src):
        add(m.group(1), "js_template")
    return found, w


if __name__ == "__main__":
    found, w = collect()
    items = sorted(found.items(), key=lambda kv: kv[1]["key"])
    payload = [{"key": v["key"], "zh": k, "kinds": v["kinds"]} for k, v in items]
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print("script blocks:", len(w.scripts),
          "sizes:", sorted((len(s) for s in w.scripts), reverse=True)[:5])
    print("markup text blocks:", len(w.blocks))
    print("attrs:", len(w.attrs))
    print("total unique:", len(payload))
    print("kinds:", Counter(k for it in payload for k in it["kinds"]))
    lens = sorted(len(it["zh"]) for it in payload)
    print("len min/med/p90/max:", lens[0], lens[len(lens) // 2],
          lens[int(len(lens) * .9)], lens[-1])
