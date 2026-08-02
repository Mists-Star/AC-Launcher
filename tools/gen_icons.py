"""Dev tool: regenerate launcher SVG icons (line-art, Light Modern style).

Run:  python tools/gen_icons.py
Icons are simple stroke SVGs matching assets/icons/*.svg already in the repo
(stroke #475569, accent #6366F1). Add new entries to ICONS and re-run.
"""
import os

OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "icons")
STROKE = "#475569"
ACCENT = "#6366F1"

WRAP = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{s}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{i}</svg>'
)

ICONS = {
    # brand logo: AC wordmark (Absolute Controller) — geometric A + C,
    # accent stroke; the hexagon vibe nods to the Absolute Solver motif.
    "logo": (
        '<path d="M6.5 18 L11 6 L15.5 18" stroke="{ACCENT}" stroke-width="2.2" stroke-linejoin="round"/>'
        '<path d="M8.2 14 H13.8" stroke="{ACCENT}" stroke-width="2.2" stroke-linecap="round"/>'
        '<path d="M18.6 7 A 5 5 0 1 0 18.6 17" stroke="{ACCENT}" stroke-width="2.2" stroke-linecap="round"/>'
    ),

    # third-party / external (Yggdrasil) login
    "external": '<path d="M14 4h6v6"/><path d="M20 4L11 13"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',

    # shader packs (lighting / sun)
    "shader": '<circle cx="12" cy="12" r="4.5"/><path d="M12 2v2.5"/><path d="M12 19.5V22"/><path d="M2 12h2.5"/><path d="M19.5 12H22"/><path d="M4.9 4.9l1.8 1.8"/><path d="M17.3 17.3l1.8 1.8"/><path d="M4.9 19.1l1.8-1.8"/><path d="M17.3 6.7l1.8-1.8"/>',

    # resource packs (image frame)
    "resourcepack": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="M21 16l-5-5L5 20"/>',

    # modpacks (package / box)
    "modpack": '<path d="M21 8l-9-5-9 5v8l9 5 9-5z"/><path d="M3 8l9 5 9-5"/><path d="M12 13v8"/>',

    # multiplayer servers
    "server": '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><circle cx="7" cy="7.5" r="0.9" fill="{s}"/><circle cx="7" cy="16.5" r="0.9" fill="{s}"/>',

    # language
    "language": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c2.5 2.5 3.5 6 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-6-3.5-9s1-6.5 3.5-9z"/>',

    # repair / fix (wrench)
    "repair": '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.1-2.1z"/>',

    # import (arrow down into tray) — cross-launcher import
    "import": '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 21h14"/>',

    # export (arrow up out of tray)
    "export": '<path d="M12 21V9"/><path d="M7 14l5-5 5 5"/><path d="M5 3h14"/>',

    # console / logs (terminal)
    "console": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3"/><path d="M13 15h4"/>',

    # crash analyzer (warning triangle)
    "crash": '<path d="M10.3 3.3 2 18a2 2 0 0 0 1.7 3h16.6a2 2 0 0 0 1.7-3L13.7 3.3a2 2 0 0 0-3.4 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',

    # skin preview (user)
    "skin": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',

    # Java management (coffee)
    "java": '<path d="M4 9h13v4a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5z"/><path d="M17 10h2a2 2 0 0 1 0 4h-2"/><path d="M7 3v2M11 3v2M15 3v2"/>',

    # directory / folder
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h3.5l2 2H19a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
}


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for name, inner in ICONS.items():
        svg = WRAP.format(s=STROKE, i=inner)
        svg = svg.replace("{ACCENT}", ACCENT)  # resolve brand accent in logo/wordmark
        with open(os.path.join(OUT, name + ".svg"), "w", encoding="utf-8") as f:
            f.write(svg)
        print("wrote", name + ".svg")


if __name__ == "__main__":
    main()
