import os

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
icon_dir = os.path.join(base, "assets", "icons")
# round-180：官方 logo 有 SVG / PNG / ICO 三种原格式，全部原样入 QRC
files = sorted(f for f in os.listdir(icon_dir)
               if f.lower().endswith((".svg", ".png", ".ico")))

lines = ['<RCC>\n', '  <qresource prefix="/icons">\n']
for f in files:
    lines.append(f'    <file alias="{f}">assets/icons/{f}</file>\n')
lines.append('  </qresource>\n')
lines.append('</RCC>\n')

with open(os.path.join(base, "icons.qrc"), "w", encoding="utf-8") as fp:
    fp.writelines(lines)

print(f"Generated icons.qrc with {len(files)} icons")
