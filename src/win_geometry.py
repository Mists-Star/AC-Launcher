"""Window placement helpers (round-223).

Kept dependency-free on purpose: the splash / welcome windows are the very
first Qt objects created at boot, so this module must not drag in the UI kit
or any page module. It only talks to the ``QWidget`` it is handed.

☠ Do not "fix" this by adding a ``Qt`` import: ``widget.screen()`` already
returns a ``QScreen``; importing Qt here would only widen the boot-time
import graph of the startup path.
"""


def center_on_screen(widget) -> None:
    """Move ``widget`` to the centre of its current screen's available area.

    Uses ``availableGeometry()`` (excludes the taskbar) and silently does
    nothing when Qt reports no screen (headless / offscreen platforms) —
    the old per-class copies had exactly that guard.
    """
    screen = widget.screen()
    if screen is None:
        return
    area = screen.availableGeometry()
    widget.move(
        area.x() + (area.width() - widget.width()) // 2,
        area.y() + (area.height() - widget.height()) // 2,
    )
