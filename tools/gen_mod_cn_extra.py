"""从 net_api_cache 提取未翻译 mod 名，批量机翻生成「中文名补充表」。

用法：venv/Scripts/python.exe tools/gen_mod_cn_extra.py
输出：src/mod_cn_extra.py（_MOD_CN_EXTRA 字典，供 mod_names.cn_name 读取）

这是一次性/按需重跑的离线工具：翻译结果固化成源码，运行时零网络开销。
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

CACHE = r"D:\Appdata\AC_Launcher\data\cache\net_api_cache.json"
OUT = os.path.join(HERE, "src", "mod_cn_extra.py")

from src.mod_names import cn_name  # noqa: E402


def collect_missing():
    with open(CACHE, encoding="utf-8") as f:
        c = json.load(f)
    missing = {}

    def visit(o):
        if isinstance(o, dict):
            slug, title = o.get("slug"), o.get("title")
            if (isinstance(slug, str) and isinstance(title, str) and slug
                    and title and slug not in missing):
                disp = cn_name(slug, title)
                # 表外（返回原名）或表内但值就是纯英文名 → 需要翻译
                if disp == title and not re.search(r"[\u4e00-\u9fff]", title):
                    missing[slug] = title
            for v in o.values():
                visit(v)
        elif isinstance(o, list):
            for v in o:
                visit(v)

    for k, v in c.items():
        payload = v.get("v", v.get("value")) if isinstance(v, dict) else v
        visit(payload)
    return missing


def clean_title(t: str) -> str:
    """剥离 emoji / 版本尾缀，让翻译更准。"""
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", t)  # emoji
    t = re.sub(r"[\[(【][^\])】]*[\])】]\s*$", "", t)              # 尾部 [fabric] 等
    return t.strip() or ""


def _write_table(out_path: str, out: dict) -> None:
    """把译名表原子写盘（防中途被杀丢数据）。"""
    lines = [
        "# -*- coding: utf-8 -*-",
        '"""Mod 中文名补充表（由 tools/gen_mod_cn_extra.py 生成，勿手改）。',
        "",
        "数据来源：用户本地搜索缓存里出现过的 mod，机器翻译生成。",
        "mod_names.cn_name 在内置表未命中时查本表。可重跑脚本增量补充。",
        '"""',
        "",
        "_MOD_CN_EXTRA = {",
    ]
    for slug in sorted(out):
        lines.append("    %r: %r," % (slug, out[slug]))
    lines += ["}", ""]
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.replace(tmp, out_path)


def main():
    missing = collect_missing()
    print("missing cn mods: %d" % len(missing))
    if not missing:
        return

    import queue
    import threading
    from src import net_api

    # ☠ 个别 mod 名会让 translate_text 里的 requests 挂死（DNS/proxy 卡住，
    # 连 4s/12s 的 requests timeout 都兜不住）。用守护线程 + queue 硬超时，
    # 超过 8s 直接跳过，不让整批翻译卡死在一个条目上。
    def _translate_one(text, q):
        try:
            q.put(("ok", net_api.translate_text(text, "zh-CN")))
        except BaseException as e:  # noqa: BLE001
            q.put(("err", e))

    def translate_with_timeout(text, seconds=8):
        q = queue.Queue()
        th = threading.Thread(target=_translate_one, args=(text, q), daemon=True)
        th.start()
        try:
            kind, val = q.get(timeout=seconds)
        except queue.Empty:
            return None  # 硬超时
        if kind == "err":
            raise val
        return val

    out = {}
    # 断点续传：若上次生成的表还在，先读入已翻译项
    if os.path.isfile(OUT):
        try:
            import ast
            tree = ast.parse(open(OUT, encoding="utf-8").read())
            for node in tree.body:
                if (isinstance(node, ast.Assign)
                        and any(getattr(t, "id", "") == "_MOD_CN_EXTRA"
                                for t in node.targets)):
                    out.update(ast.literal_eval(node.value))
            print("resumed: %d entries from existing table" % len(out))
        except Exception:
            pass

    t0 = time.time()
    for i, (slug, title) in enumerate(sorted(missing.items()), 1):
        if slug in out:
            continue  # 断点续传：已有
        clean = clean_title(title)
        if not clean:
            continue
        try:
            zh = translate_with_timeout(clean, 8)
            if zh is None:
                print("  TIMEOUT %-30s" % slug)
                continue
            zh = " ".join(str(zh).split())
            # 翻译没产出中文（可能原样返回）→ 跳过
            if not zh or not re.search(r"[\u4e00-\u9fff]", zh):
                print("  SKIP %-30s -> %s" % (slug, zh[:30]))
                continue
            out[slug] = "%s（%s）" % (title, zh)
            print("  [%d/%d] %-30s -> %s" % (i, len(missing), slug, zh[:30]))
        except Exception as e:
            print("  ERR %-30s %s" % (slug, str(e)[:50]))
        # 每 25 条存一次盘，防止中途被杀丢失全部成果
        if i % 25 == 0:
            _write_table(OUT, out)
        # 翻译 API 有频率限制，稍微间隔
        time.sleep(0.1)

    _write_table(OUT, out)
    print("\nwrote %s: %d entries (%.1fs)" % (OUT, len(out), time.time() - t0))


if __name__ == "__main__":
    main()
