"""Extract design tokens (colors / fonts / sizes) from ardot-exported SVGs."""
import re, os, json, glob
from collections import Counter

TPL = "<repo>/templates"
files = sorted(glob.glob(os.path.join(TPL, "*.svg")))

color_re = re.compile(r'(?:fill|stroke)="#([0-9A-Fa-f]{6,8})"')
font_re = re.compile(r'font-family="([^"]+)"')
size_re = re.compile(r'font-size="([0-9.]+)"')
text_re = re.compile(r'<text\b')

def norm(c):
    c = c.upper()
    if len(c) == 8:  # strip alpha for palette grouping
        c = c[:6]
    return "#" + c

out = {}
global_colors = Counter()
for f in files:
    name = os.path.basename(f)
    data = open(f, encoding="utf-8", errors="ignore").read()
    cols = [norm(c) for c in color_re.findall(data)]
    fonts = font_re.findall(data)
    sizes = [float(s) for s in size_re.findall(data)]
    global_colors.update(cols)
    out[name] = {
        "bytes": len(data),
        "color_count": len(cols),
        "top_colors": Counter(cols).most_common(15),
        "fonts": sorted(set(fonts)),
        "font_sizes": sorted(set(sizes)),
        "has_text": bool(text_re.search(data)),
    }

print("===== PER-FILE =====")
for name, d in out.items():
    print(f"\n## {name}  ({d['bytes']}B, colors={d['color_count']}, text={d['has_text']})")
    print("  TOP COLORS:", " ".join(f"{c}×{n}" for c, n in d["top_colors"]))
    if d["fonts"]:
        print("  FONTS:", ", ".join(d["fonts"]))
    if d["font_sizes"]:
        print("  SIZES:", d["font_sizes"])

print("\n===== GLOBAL PALETTE (dedup, by frequency) =====")
for c, n in global_colors.most_common(40):
    print(f"  {c}  ×{n}")

# save
json.dump({"files": out, "palette": global_colors.most_common()},
          open("<repo>/_design_spec.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("\nsaved _design_spec.json")
