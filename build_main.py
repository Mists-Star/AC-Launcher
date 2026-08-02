import json
from mcp_ardot import ArdotMCP

FILE = "cocraft://localhost/file/709193132093693"
c = ArdotMCP()

# figure out current top-level nodes to clean up probe residue
st = c.fetch_editor_state(include_schema=False, include_general=False)
top = json.loads(st["result"]["content"][0]["text"])["data"]["currentPageTopLevelNodes"]
print("TOP-LEVEL:", [(n.get("id"), n.get("name")) for n in top])
ids = [n["id"] for n in top if n.get("id") != "0:1"]
cleanup = "\n".join(f'D("{i}")' for i in ids)

ops = cleanup + '''
screen = I("0:1", { type:"frame", width:980, height:620, fill:"#1e1e1e", cornerRadius:"$:MC:radiusLg", layout:"vertical", padding:"$:MC:space3", gap:"$:MC:space3" })
topBar = I(screen, { type:"frame", width:"fill_container", height:56, fill:"#2a2a2e", cornerRadius:"$:MC:radius", layout:"horizontal", gap:"$:MC:space2", padding:"$:MC:space2", alignItems:"center" })
logo = I(topBar, { type:"text", content:"AC Launcher", fontSize:"$:MC:textXl", fills:"#e5e5e5" })
spacer = I(topBar, { type:"frame", width:"fill_container", height:1, fill:"#2a2a2e" })
acct = I(topBar, { type:"frame", height:"fill_container", fill:"#33333a", cornerRadius:"$:MC:radiusSm", padding:"$:MC:space1", layout:"horizontal", alignItems:"center" })
acctText = I(acct, { type:"text", content:"未登录", fontSize:"$:MC:textSm", fills:"#9ca3af" })
body = I(screen, { type:"frame", width:"fill_container", height:"fill_container", fill:"#1e1e1e", layout:"vertical", gap:"$:MC:space3", padding:"$:MC:space3", alignItems:"center", justifyContent:"center" })
verLabel = I(body, { type:"text", content:"游戏版本", fontSize:"$:MC:textSm", fills:"#9ca3af" })
verSel = I(body, { type:"frame", width:320, height:44, fill:"#2a2a2e", cornerRadius:"$:MC:radius", layout:"horizontal", padding:"$:MC:space2", alignItems:"center", justifyContent:"space-between" })
verText = I(verSel, { type:"text", content:"1.21.5", fontSize:"$:MC:textBase", fills:"#e5e5e5" })
verArrow = I(verSel, { type:"text", content:"▾", fontSize:"$:MC:textBase", fills:"#9ca3af" })
play = I(body, { type:"frame", width:280, height:56, fill:"#7c3aed", cornerRadius:"$:MC:radiusLg", layout:"horizontal", alignItems:"center", justifyContent:"center", gap:"$:MC:space1" })
playText = I(play, { type:"text", content:"开始游戏", fontSize:"$:MC:textLg", fills:"#ffffff" })
bottomBar = I(screen, { type:"frame", width:"fill_container", height:40, fill:"#2a2a2e", cornerRadius:"$:MC:radius", layout:"horizontal", padding:"$:MC:space2", alignItems:"center", justifyContent:"space-between" })
status = I(bottomBar, { type:"text", content:"就绪", fontSize:"$:MC:textSm", fills:"#9ca3af" })
settings = I(bottomBar, { type:"frame", height:"fill_container", width:90, fill:"#33333a", cornerRadius:"$:MC:radiusSm", layout:"horizontal", alignItems:"center", justifyContent:"center" })
settingsText = I(settings, { type:"text", content:"设置", fontSize:"$:MC:textSm", fills:"#e5e5e5" })
'''
r = c.call_tool("batch_edit", {"fileUrl": FILE, "operations": ops})
txt = r["result"]["content"][0]["text"]
d = json.loads(txt)
print("MAIN success:", d.get("success"))
print("MAIN ops count:", len(d.get("data", {}).get("operations", [])))
print("MAIN issues:", json.dumps(d.get("potentialIssues", []), ensure_ascii=False)[:1500])
