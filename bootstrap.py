"""One service namespace shared by the tool plugin and its dashboard API."""
from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path

_LOCK = threading.RLock()


def load_core():
    root = Path(__file__).resolve().parent / "cteam"
    name = "hermes_construction_team_core"
    with _LOCK:
        if name in sys.modules:
            module = sys.modules[name]
            if Path(module.__file__).resolve().parent != root:
                raise RuntimeError("Construction core namespace belongs to another installation")
            return module
        spec = importlib.util.spec_from_file_location(name, root / "__init__.py", submodule_search_locations=[str(root)])
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not create construction core module spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        return module
