"""Loads KEY=VALUE lines from a .env file in the project root (no extra
package needed). Real environment variables always win over .env."""
import os
from pathlib import Path

_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    # utf-8-sig: Windows Notepad / PowerShell may prepend a BOM
    for _line in _env.read_text(encoding="utf-8-sig").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            if _v.strip():
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
