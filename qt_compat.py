import os

from maya import cmds


def maya_major_version():
    version = cmds.about(version=True)
    try:
        return int(str(version).split()[0].split(".")[0])
    except Exception:
        return 2024


if maya_major_version() >= 2025:
    os.environ["QT_API"] = "pyside6"
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance
else:
    os.environ["QT_API"] = "pyside2"
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import wrapInstance


__all__ = ["QtCore", "QtGui", "QtWidgets", "wrapInstance"]
