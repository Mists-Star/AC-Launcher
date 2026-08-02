import json
from mcp_ardot import ArdotMCP

FILE = "cocraft://localhost/file/709193132093693"


def hx(h: str):
    h = h.lstrip("#")
    return {"r": int(h[0:2], 16) / 255, "g": int(h[2:4], 16) / 255, "b": int(h[4:6], 16) / 255, "a": 1}


def main():
    c = ArdotMCP()

    # 1) re-apply with SPACELESS set name "MC" (spaces broke var binding)
    tokens = {
        "MC": {
            "modes": ["Dark"],
            "variables": {
                "bg":        {"type": "COLOR", "value": hx("1e1e1e")},
                "panel":     {"type": "COLOR", "value": hx("2a2a2e")},
                "panelHi":   {"type": "COLOR", "value": hx("33333a")},
                "accent":    {"type": "COLOR", "value": hx("7c3aed")},
                "accentHover":{"type": "COLOR", "value": hx("8b5cf6")},
                "text":      {"type": "COLOR", "value": hx("e5e5e5")},
                "textDim":   {"type": "COLOR", "value": hx("9ca3af")},
                "danger":    {"type": "COLOR", "value": hx("ef4444")},
                "success":   {"type": "COLOR", "value": hx("22c55e")},
                "border":    {"type": "COLOR", "value": hx("3a3a40")},
                "space1": {"type": "FLOAT", "value": 8},
                "space2": {"type": "FLOAT", "value": 16},
                "space3": {"type": "FLOAT", "value": 24},
                "space4": {"type": "FLOAT", "value": 32},
                "radiusSm": {"type": "FLOAT", "value": 6},
                "radius":   {"type": "FLOAT", "value": 10},
                "radiusLg": {"type": "FLOAT", "value": 16},
                "textXs":  {"type": "FLOAT", "value": 11},
                "textSm":  {"type": "FLOAT", "value": 13},
                "textBase":{"type": "FLOAT", "value": 14},
                "textLg":  {"type": "FLOAT", "value": 16},
                "textXl":  {"type": "FLOAT", "value": 20},
                "textTitle":{"type": "FLOAT", "value": 28},
            },
        }
    }
    r1 = c.call_tool("apply_variables", {"fileUrl": FILE, "variables": tokens, "replace": True})
    print("APPLY:", json.dumps(r1, ensure_ascii=False)[:400])

    # 2) cleanup earlier probe (6:26 is parent of 6:27)
    r2 = c.call_tool("batch_edit", {"fileUrl": FILE, "operations": 'D("6:26")'})
    print("CLEANUP:", json.dumps(r2, ensure_ascii=False)[:300])

    # 3) probe2: spaceless var binding + literal colors
    ops = '''
root = I("0:1", { type:"frame", x:0, y:0, width:960, height:600, fill:"#1e1e1e", cornerRadius:"$:MC:radiusLg", layout:"vertical", gap:"$:MC:space2", padding:"$:MC:space3" })
title = I(root, { type:"text", content:"AC Launcher", fontSize:"$:MC:textTitle", fills:"#e5e5e5" })
'''
    r3 = c.call_tool("batch_edit", {"fileUrl": FILE, "operations": ops})
    txt = r3["result"]["content"][0]["text"]
    d = json.loads(txt)
    print("PROBE2 success:", d.get("success"))
    print("PROBE2 issues:", json.dumps(d.get("potentialIssues", []), ensure_ascii=False)[:1200])


if __name__ == "__main__":
    main()
