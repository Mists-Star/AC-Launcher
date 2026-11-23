"""恢复「随包内置功能扩展」层：从 HEAD 取回被删的 bundled 代码块，保留远程索引层。"""
import io
import subprocess
import sys

REPO = "d:/Claw/mc_launcher"


def head_text(path: str) -> str:
    return subprocess.run(
        ["git", "show", f"HEAD:{path}"], cwd=REPO, capture_output=True, check=True
    ).stdout.decode("utf-8")


def read(path: str) -> str:
    with io.open(f"{REPO}/{path}", encoding="utf-8", newline="") as f:
        return f.read()


def write(path: str, txt: str) -> None:
    with io.open(f"{REPO}/{path}", "w", encoding="utf-8", newline="") as f:
        f.write(txt)


def between(txt: str, start_marker: str, end_marker: str) -> str:
    i = txt.index(start_marker)
    j = txt.index(end_marker, i)
    return txt[i:j]


def replace_between(txt: str, start_marker: str, end_marker: str,
                    new: str, occurrence: int = 0) -> str:
    """把 [start_marker, end_marker) 之间替换为 new（保留 end_marker）。"""
    i = txt.index(start_marker)
    j = txt.index(end_marker, i)
    return txt[:i] + new + txt[j:]


# ── 1. src/features.py ────────────────────────────────────────────────
fp = "src/features.py"
head = head_text(fp)
cur = read(fp)

# 1a. 导入 get_resource_path（bundled_root 需要）
old_imp = "from .paths import get_data_dir\n"
assert cur.count(old_imp) == 1
cur = cur.replace(old_imp, "from .paths import get_data_dir, get_resource_path\n")

# 1b. bundled_root()（HEAD 里位于 feature_root 之后、_root 之前）
seg_root = between(head, "def bundled_root() -> str:", "def _root(root")
anchor = "def _root(root: str | None) -> str:"
assert cur.count(anchor) == 1
cur = cur.replace(anchor, seg_root.rstrip("\n") + "\n\n\n" + anchor)

# 1c. 内置包六个函数（HEAD 的整段，含小节标题注释）
seg_builtin = between(
    head,
    "# ── 内置包：首次安装 / 删除后不自动重装",
    "# ── 安装 / 卸载 ─",
)
mark_install = "# ── 安装 / 卸载 ─"
assert cur.count(mark_install) == 1
cur = cur.replace(mark_install, seg_builtin + mark_install)

# 1d. 文档字符串改成混合模式
old_doc_tail = (
    "`registry.json` 只记录「曾经装过的包」：玩家主动删掉的包不会被下一次\n"
    "启动自动装回；只有设置页点「安装」或 `install_from_*` 才恢复。\n"
    "\n"
    "远程索引（可选）：\n"
    "    启动器可从配置的 URL 拉取 `features-index.json`，获取官方/社区扩展列表，\n"
    "    含下载地址、校验哈希、版本等元数据。主程序**不再内置任何扩展包**。\n"
)
new_doc_tail = (
    "`registry.json` 只记录「曾经装过的包」：玩家主动删掉的包不会被下一次\n"
    "启动自动装回；只有设置页点「安装」或 `restore_builtin()` 才恢复。\n"
    "\n"
    "远程索引（可选）：\n"
    "    启动器可从配置的 URL 拉取 `features-index.json`，获取官方/社区扩展列表，\n"
    "    含下载地址、校验哈希、版本等元数据。内置包与远程扩展**并存**：内置包随\n"
    "    安装包发布（`assets/features` 进 git，删了能一键装回），远程扩展按需下载。\n"
)
assert cur.count(old_doc_tail) == 1
cur = cur.replace(old_doc_tail, new_doc_tail)

old_dir = "    <data>/features/<id>/entry.py        # 必须暴露 create_page(ctx)\n"
new_dir = (
    old_dir
    + "    assets/features/<id>/...             # 随安装包发布的内置原始包（git 跟踪）\n"
)
assert cur.count(old_dir) == 1
cur = cur.replace(old_dir, new_dir)

write(fp, cur)
print(f"[ok] {fp}: bundled_root + 6 个内置包函数已恢复，文档字符串改为混合模式")

# ── 2. src/main_window.py ─────────────────────────────────────────────
mp = "src/main_window.py"
mw = read(mp)
old_seed = (
    "        # 功能扩展包：不再内置，玩家从远程仓库按需安装"
    "（见 features.fetch_feature_index）。\n"
)
new_seed = (
    "        # round-167：功能扩展包（音乐/成就/控制台等）可被玩家整包删除。\n"
    "        # 首次启动复制内置包；玩家删掉后不再自动装回\n"
    "        # （见 features.ensure_builtins，可在模块页手动装回）。\n"
    "        try:\n"
    "            features.ensure_builtins()\n"
    "        except Exception:  # noqa: BLE001 - 扩展系统坏了也不能挡启动\n"
    "            pass\n"
)
assert mw.count(old_seed) == 1, "main_window 播种锚点没找到"
mw = mw.replace(old_seed, new_seed)
write(mp, mw)
print(f"[ok] {mp}: ensure_builtins() 播种已恢复")

print("DONE")