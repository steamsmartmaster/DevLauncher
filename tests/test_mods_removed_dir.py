# -*- coding: utf-8 -*-
"""loadMods 子目录扫描不得把 _removed_mods 回收目录当活跃模组。

复现：delete_mod 把 jar 移进 mods/_removed_mods/ 后，列表仍会扫出这些
"幽灵模组"（长度恒定），再点删除时 delete_mod 用 basename 去顶层找 → 报不存在。
"""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")


def _loadmods_body():
    m = re.search(r"def loadMods\(self[\s\S]*?(?=\n    @pyqtSlot|\n    def [a-z])", SRC)
    assert m, "loadMods 应存在"
    return m.group(0)


def test_subdir_scan_skips_removed_mods():
    body = _loadmods_body()
    assert "_removed_mods" in body, "loadMods 子目录扫描应显式排除 _removed_mods 回收目录"
    # 子目录遍历分支内必须有跳过判断
    assert re.search(
        r"elif item\.is_dir\(\):[\s\S]{0,200}?_removed_mods", body
    ), "子目录分支应跳过 _removed_mods"
