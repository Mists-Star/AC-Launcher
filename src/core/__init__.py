"""Launcher core: pure logic layer (no Qt, no GUI).

Everything in here is testable without a display and is deliberately free of
PySide imports so it can run in a worker thread or even headless. Progress
reporting uses minecraft-launcher-lib's callback dict convention
({"setStatus", "setProgress", "setMax"}), which the UI layer bridges to Qt
signals (see src/worker.py).
"""
