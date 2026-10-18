# -*- coding: utf-8 -*-
"""Turn tools/i18n/{strings.json,en.json} into ui/i18n_dict.js.

The dictionary is keyed by the Chinese source text, because that is what the
DOM actually contains: static markup, HTML built by JS, and attribute values
all reach the page as-is. ui/i18n.js walks text nodes and attributes, looks
each one up here, and writes back the English.

Every text node / attribute value becomes its own key. Sharing a key between a
whole JS literal and the text inside it would make a text node resolve to the
entire translated markup, so units_of() splits a source string first.

Messages assembled with `+` never match a whole text node, so ui/i18n.js falls
back to longest-match splicing of the dictionary's CJK fragments.
"""
import json
import pathlib
import re
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_FILE = ROOT / "ui" / "i18n_dict.js"
HERE = pathlib.Path(__file__).resolve().parent


class TextGrab(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.buf = []

    def _flush(self):
        if self.buf:
            self.parts.append("".join(self.buf))
            self.buf = []

    def handle_starttag(self, tag, attrs):
        self._flush()

    def handle_endtag(self, tag):
        self._flush()

    def handle_data(self, data):
        self.buf.append(data)

    def close(self):
        self._flush()
        super().close()


def text_nodes(markup: str) -> list:
    g = TextGrab()
    g.feed(markup)
    g.close()
    return [p.strip() for p in g.parts if p.strip()]


ATTR_RE = re.compile(r'\b(title|placeholder|aria-label)="([^"]*)"')


def attr_values(markup: str) -> list:
    return [(m.group(1), m.group(2).strip()) for m in ATTR_RE.finditer(markup)
            if m.group(2).strip()]


def units_of(zh: str, en: str) -> list:
    out = [(zh, en)]
    if "<" in zh:
        zt, et = text_nodes(zh), text_nodes(en)
        if zt and len(zt) == len(et):
            out.extend(zip(zt, et))
    za, ea = attr_values(zh), attr_values(en)
    if za and len(za) == len(ea) and all(a[0] == b[0] for a, b in zip(za, ea)):
        out.extend((a[1], b[1]) for a, b in zip(za, ea))
    return out


def build():
    en = json.loads((HERE / "en.json").read_text(encoding="utf-8"))
    entries = json.loads((HERE / "strings.json").read_text(encoding="utf-8"))
    zh_set = {e["zh"] for e in entries}
    missing = sorted(zh_set - set(en))
    extra = sorted(set(en) - zh_set)
    if missing:
        raise SystemExit("MISSING %d translations:\n  %s"
                         % (len(missing), "\n  ".join(missing[:40])))
    if extra:
        raise SystemExit("EXTRA %d keys not in source:\n  %s"
                         % (len(extra), "\n  ".join(extra[:40])))

    payload = {"map": {}, "mapEn": {}, "zh": {}, "en": {}}
    n = 0
    for zh in sorted(zh_set):
        for zi, ei in units_of(zh, en[zh]):
            if zi in payload["map"]:
                continue
            key = "u%04d" % n
            n += 1
            payload["map"][zi] = key
            payload["zh"][key] = zi
            payload["en"][key] = ei
            payload["mapEn"].setdefault(ei, key)

    js = "window.I18N_DATA = %s;\n" % json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"))
    OUT_FILE.write_text(js, encoding="utf-8")
    print("source keys:", len(zh_set), "index entries:", len(payload["map"]),
          "->", OUT_FILE.name, "bytes:", len(js.encode("utf-8")))


if __name__ == "__main__":
    build()
