from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Dict

from .contracts import OcrResult


class PluginRunner:
    def __init__(self, plugin_root: Path, plugin_name: str, global_options: Dict[str, Any]):
        root = str(plugin_root.resolve())
        if root not in sys.path:
            sys.path.insert(0, root)
        module = importlib.import_module(plugin_name)
        info = getattr(module, "PluginInfo", None)
        if not isinstance(info, dict) or info.get("group") != "ocr":
            raise ValueError("PluginInfo.group must be ocr")
        api_class = info.get("api_class")
        if not callable(api_class):
            raise ValueError("PluginInfo.api_class must be callable")
        self._api = api_class(global_options)
        self._started = False

    def start(self, local_options: Dict[str, Any]) -> None:
        message = str(self._api.start(local_options))
        if message.startswith("[Error]"):
            raise RuntimeError(message)
        self._started = True

    def run_path(self, path: Path) -> OcrResult:
        if not self._started:
            raise RuntimeError("plugin has not been started")
        return OcrResult.from_plugin_dict(self._api.runPath(str(path)))

    def close(self) -> None:
        if self._started:
            self._api.stop()
            self._started = False

    def __enter__(self) -> "PluginRunner":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
