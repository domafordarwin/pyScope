# app/main.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from PyQt5 import QtWidgets
from .ui.main_window import MainWindow
from .ui.style import apply_theme


def main():
    app = QtWidgets.QApplication(sys.argv)
    apply_theme(app)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
