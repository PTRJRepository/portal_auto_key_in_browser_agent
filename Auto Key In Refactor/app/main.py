from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.core.category_registry import load_category_registry
from app.core.config import load_app_config
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    config = load_app_config()
    categories = load_category_registry()
    window = MainWindow(config, categories)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
