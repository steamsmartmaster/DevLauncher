import json
from pathlib import Path
from typing import Any


class Settings:
    """Manage launcher settings"""

    _LAUNCHER_DIR = Path(__file__).parent.parent

    DEFAULT_SETTINGS = {
        "minecraft_dir": str(Path.home() / ".minecraft"),
        "max_memory": 4096,
        "min_memory": 1024,
        "java_path": "",
        "jvm_args": "",
        "window_width": 854,
        "window_height": 480,
        "fullscreen": False,
        "show_snapshots": True,
        "show_old": False,
        "client_id": "",
        "background": str(_LAUNCHER_DIR / "ui" / "bg.png"),
        "theme_primary": "#ffffff",
        "theme_gradient_start": "#ffffff",
        "theme_gradient_end": "#888888",
        "version_isolation": False
    }

    def __init__(self):
        self._settings_file = Path.home() / ".mc-launcher" / "settings.json"
        self._settings: dict[str, Any] = {}
        self._load()

    def _load(self):
        """Load settings from file, merging with defaults"""
        defaults = self.DEFAULT_SETTINGS.copy()
        if self._settings_file.exists():
            with open(self._settings_file, "r") as f:
                defaults.update(json.load(f))
        self._settings = defaults

    def save(self):
        """Save settings to file"""
        self._settings_file.parent.mkdir(exist_ok=True)
        with open(self._settings_file, "w") as f:
            json.dump(self._settings, f, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value"""
        return self._settings.get(key, default)

    def set(self, key: str, value: Any):
        """Set a setting value"""
        self._settings[key] = value
        self.save()

    def __getitem__(self, key: str) -> Any:
        return self._settings.get(key)

    def __setitem__(self, key: str, value: Any):
        self._settings[key] = value
        self.save()
