
import io
import os
import sys

__all__ = ["harden_stdio"]

_hardened = False

def _harden_rich_null_file():
    try:
        module = sys.modules.get("rich.console")
        null_file = getattr(module, "NULL_FILE", None)
        if null_file is not None and hasattr(null_file, "reconfigure"):
            null_file.reconfigure(errors="replace")
    except Exception:
        pass

def harden_stdio(force=False):
    global _hardened
    if _hardened and not force:
        return sys.stdout
    _hardened = True

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8", errors="replace"))
            except Exception:
                pass
            continue
        try:
            stream.reconfigure(errors="replace")          # type: ignore[attr-defined]
            continue
        except Exception:
            pass
        try:
            buffer = getattr(stream, "buffer")
            encoding = getattr(stream, "encoding", None) or "utf-8"
            setattr(sys, name, io.TextIOWrapper(buffer, encoding=encoding,
                                                errors="replace", line_buffering=True))
        except Exception:
            pass

    _harden_rich_null_file()
    return sys.stdout
