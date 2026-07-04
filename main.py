"""CopyForge — entry point."""
import importlib.util
import sys
import os

# Allow long paths on Windows
if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW.restype = ctypes.c_bool
    except Exception:
        pass


def _check_deps():
    missing = [pkg for pkg in ("customtkinter",)
               if importlib.util.find_spec(pkg) is None]
    if missing:
        print(
            "Missing dependencies: " + ", ".join(missing) + "\n"
            "Run:  pip install -r requirements.txt"
        )
        sys.exit(1)


_check_deps()

from gui import App  # noqa: E402

if __name__ == "__main__":
    app = App()
    app.mainloop()
