import json
import time
from mcp_ardot import ArdotMCP

c = ArdotMCP()
FILE = "cocraft://localhost/file/709193132093693"

OPS1 = '''
dlg = I("0:1", { type:"frame", width:440, height:560, fill:"#2a2a2e", cornerRadius:"$:MC:radiusLg", layout:"vertical", padding:"$:MC:space3", gap:"$:MC:space3", name:"SettingsDialog" })
title = I(dlg, { type:"text", content:"设置", fontSize:"$:MC:textXl", fills:"#e5e5e5" })
secRAM = I(dlg, { type:"frame", width:"fill_container", height:"auto", layout:"vertical", gap:"$:MC:space1", name:"RAM" })
ramLbl = I(secRAM, { type:"text", content:"分配内存 (RAM)", fontSize:"$:MC:textSm", fills:"#9ca3af" })
ramTrack = I(secRAM, { type:"frame", width:"fill_container", height:6, fill:"#1e1e1e", cornerRadius:3, name:"track" })
ramHandle = I(ramTrack, { type:"frame", x:200, width:16, height:16, fill:"#7c3aed", cornerRadius:8, name:"handle" })
ramVal = I(secRAM, { type:"text", content:"4096 MB", fontSize:"$:MC:textBase", fills:"#e5e5e5" })
secJava = I(dlg, { type:"frame", width:"fill_container", height:"auto", layout:"vertical", gap:"$:MC:space1", name:"Java" })
javaLbl = I(secJava, { type:"text", content:"Java 路径 (自动检测)", fontSize:"$:MC:textSm", fills:"#9ca3af" })
javaInput = I(secJava, { type:"frame", width:"fill_container", height:40, fill:"#1e1e1e", cornerRadius:"$:MC:radius", padding:"$:MC:space2", layout:"horizontal", alignItems:"center" })
javaText = I(javaInput, { type:"text", content:"C:/Program Files/Java/jdk-21/bin/java.exe", fontSize:"$:MC:textSm", fills:"#e5e5e5" })
'''

OPS2 = '''
secRes = I("{dlg}", { type:"frame", width:"fill_container", height:"auto", layout:"vertical", gap:"$:MC:space1", name:"Resolution" })
resLbl = I(secRes, { type:"text", content:"游戏分辨率", fontSize:"$:MC:textSm", fills:"#9ca3af" })
resInput = I(secRes, { type:"frame", width:"fill_container", height:40, fill:"#1e1e1e", cornerRadius:"$:MC:radius", padding:"$:MC:space2", layout:"horizontal", alignItems:"center" })
resText = I(resInput, { type:"text", content:"1920 x 1080", fontSize:"$:MC:textSm", fills:"#e5e5e5" })
secJVM = I("{dlg}", { type:"frame", width:"fill_container", height:"auto", layout:"vertical", gap:"$:MC:space1", name:"JVM" })
jvmLbl = I(secJVM, { type:"text", content:"JVM 启动参数", fontSize:"$:MC:textSm", fills:"#9ca3af" })
jvmBox = I(secJVM, { type:"frame", width:"fill_container", height:72, fill:"#1e1e1e", cornerRadius:"$:MC:radius", padding:"$:MC:space2" })
jvmText = I(jvmBox, { type:"text", content:"-XX:+UseG1GC -XX:+UnlockExperimentalVMOptions", fontSize:"$:MC:textSm", fills:"#9ca3af" })
secTheme = I("{dlg}", { type:"frame", width:"fill_container", height:"auto", layout:"horizontal", alignItems:"center", justifyContent:"space-between", name:"Theme" })
themeLbl = I(secTheme, { type:"text", content:"深色主题", fontSize:"$:MC:textBase", fills:"#e5e5e5" })
switch = I(secTheme, { type:"frame", width:48, height:26, fill:"#7c3aed", cornerRadius:13, layout:"horizontal", justifyContent:"flex-end", padding:3 })
switchKnob = I(switch, { type:"frame", width:20, height:20, fill:"#ffffff", cornerRadius:10 })
btnRow = I("{dlg}", { type:"frame", width:"fill_container", height:"auto", layout:"horizontal", gap:"$:MC:space2", justifyContent:"flex-end" })
cancelBtn = I(btnRow, { type:"frame", width:100, height:40, fill:"#33333a", cornerRadius:"$:MC:radius", layout:"horizontal", alignItems:"center", justifyContent:"center" })
cancelTxt = I(cancelBtn, { type:"text", content:"取消", fontSize:"$:MC:textBase", fills:"#e5e5e5" })
saveBtn = I(btnRow, { type:"frame", width:100, height:40, fill:"#7c3aed", cornerRadius:"$:MC:radius", layout:"horizontal", alignItems:"center", justifyContent:"center" })
saveTxt = I(saveBtn, { type:"text", content:"保存", fontSize:"$:MC:textBase", fills:"#ffffff" })
'''

def cleanup():
    st = c.fetch_editor_state(include_schema=False, include_general=False)
    top = json.loads(st["result"]["content"][0]["text"])["data"]["currentPageTopLevelNodes"]
    old = [n["id"] for n in top if n.get("name") == "SettingsDialog"]
    if old:
        c.call_tool("batch_edit", {"fileUrl": FILE, "operations": "\n".join(f'D("{i}")' for i in old)})
        print("cleaned:", old)

def run_once():
    cleanup()
    r1 = c.call_tool("batch_edit", {"fileUrl": FILE, "operations": OPS1})
    if not r1 or not r1.get("result") or not r1["result"].get("content"):
        return None, None
    d1 = json.loads(r1["result"]["content"][0]["text"])
    if not d1.get("success") or d1.get("potentialIssues"):
        return None, d1
    dlg = None
    for op in d1.get("data", {}).get("operations", []):
        if op.get("type") == "Insert" and op.get("node", {}).get("name") == "SettingsDialog":
            dlg = op["node"]["id"]
    if not dlg:
        return None, d1
    c.call_tool("batch_edit", {"fileUrl": FILE, "operations": f'U("{dlg}", {{ x:"1040", y:"40" }})'})
    r2 = c.call_tool("batch_edit", {"fileUrl": FILE, "operations": OPS2.format(dlg=dlg)})
    if not r2 or not r2.get("result") or not r2["result"].get("content"):
        return None, None
    d2 = json.loads(r2["result"]["content"][0]["text"])
    if not d2.get("success") or d2.get("potentialIssues"):
        return None, d2
    return dlg, d2

for attempt in range(1, 5):
    dlg, res = run_once()
    if dlg:
        print(f"SETTINGS OK on attempt {attempt}, dialog id: {dlg}")
        break
    print(f"attempt {attempt} failed, retry...")
    time.sleep(2)
else:
    print("SETTINGS FAILED after 4 attempts")
