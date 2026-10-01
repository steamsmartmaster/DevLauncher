import sys
from pathlib import Path


def app_base_dir() -> Path:
    """运行时数据根目录。

    frozen（PyInstaller 打包）时返回 exe 所在目录（持久、用户可见），
    开发态返回仓库根。logs/ 与 plugins/ 等可写目录以此为基准，
    避免落到一次性临时解包目录（_MEIPASS）导致数据每次启动丢失。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
