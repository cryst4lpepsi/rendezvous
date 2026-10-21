"""make_icon.py OUT.ico - render the app icon (the same one the window uses) for the exe."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication([])
import app  # noqa: E402

ok = app.make_icon().pixmap(256, 256).save(sys.argv[1])
print(f"icon written to {sys.argv[1]}: {ok}")
sys.exit(0 if ok else 1)
