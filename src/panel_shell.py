"""Dialog compatibility shell mixin (round-222).

Several dialogs are thin ``QDialog`` wrappers around an inner ``QWidget`` panel
(``self.panel``). Historical call sites and tests still talk to the *dialog* as
if it were the panel, so the shell forwards attribute reads/writes and the close
event to ``self.panel``.

Until round-222 each of those dialogs carried a byte-identical copy of
``__getattr__`` / ``__setattr__`` / ``closeEvent``. This module is the single
source of truth. Deliberately kept tiny and dependency-free (only ``object``
and ``super``); it must **not** import Qt so any QWidget-based shell can use it.

Usage::

    class MyDialog(PanelShellMixin, QDialog):
        def __init__(self, ...):
            super().__init__(parent)
            self.panel = MyPanel(...)

The mixin must come **first** in the MRO so ``super().closeEvent(ev)`` resolves
to ``QDialog.closeEvent``.

☠ ``__setattr__`` forwarding is not optional: writing e.g.
``dlg._dl_phase = "download"`` on the shell while the panel reads its own
``_dl_phase`` leaves the status line frozen (caught by round-197 Java download
test). Read-only forwarding alone is a real bug.
"""


class PanelShellMixin:
    """Forward attribute access and closeEvent to ``self.panel``."""

    def __getattr__(self, name):
        # Guard against recursion while ``panel`` has not been assigned yet.
        if name == "panel":
            raise AttributeError(name)
        return getattr(self.panel, name)

    def __setattr__(self, name, value):
        """Write-through to the inner panel.

        ☠ Only forwarding *reads* is not enough: ``dlg._dl_phase = "download"``
        would set the attribute on the shell while the panel keeps reading its
        own ``_dl_phase`` → the status line never updates (round-197).
        """
        if name in ("panel",):
            object.__setattr__(self, name, value)
            return
        panel = self.__dict__.get("panel")
        if panel is not None and hasattr(panel, name):
            setattr(panel, name, value)
            return
        object.__setattr__(self, name, value)

    def closeEvent(self, ev):  # noqa: N802 - Qt naming
        """Forward close to the panel (it may own background threads)."""
        panel = self.__dict__.get("panel")
        if panel is not None:
            try:
                panel.closeEvent(ev)
                return
            except Exception:  # noqa: BLE001 - fall back to Qt close
                pass
        super().closeEvent(ev)
