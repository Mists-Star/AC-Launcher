"""round-152 文案门禁：AI 禁用词 + 提示文案长度预算（allowlist 只缩不增）。

对齐 `docs/style-gates.md` 的人工门禁，把其中两条可以机器判定的规则自动化：

1. **禁用词**：营销腔 / AI 高频词（中英各一张表）出现即 FAIL。
2. **提示长度**：`_hint` / `_help` / `_note` 类长文案按加权长度预算
   （汉字计 1，拉丁/数字/空格/标点计 0.5）——中文 40、英文 80。
   存量超标项登记在 `tests/copy_allowlist.txt`（格式 `lang|key`，`#` 注释）。

allowlist **只缩不增**：
  * 当前超标但不在表里 → FAIL（新增问题，必须改文案或明确登记）；
  * 已在表里但不再超标 / 键已删除 → FAIL（要求删掉该行，防止表变成垃圾桶）。

多句提示只统计、不判失败（留给人工按语境判断，避免误杀合理说明）。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src.i18n import _STRINGS as STRINGS  # noqa: E402

HELP_SUFFIX = ("_hint", "_help", "_note", ".hint", ".help", ".note")
BUDGET = {"zh": 40, "en": 80}
ALLOWLIST = os.path.join(HERE, "tests", "copy_allowlist.txt")

BANNED = {
    "zh": ["赋能", "极致", "一站式", "全方位", "焕新", "打造", "沉浸式",
           "立即体验", "开启你的"],
    "en": ["additionally", "crucial", "delve", "enhance", "foster", "showcase",
           "seamless", "vibrant", "pivotal", "tapestry", "leverage"],
}


def weighted(text: str) -> float:
    """中文全角按 1、其余按 0.5 计（与 style-gates 的口径一致）。"""
    return sum(1.0 if "\u4e00" <= ch <= "\u9fff" else 0.5 for ch in text)


def lang_tables() -> list[tuple[str, str]]:
    en_key = next(k for k in STRINGS if k.lower().startswith("en"))
    return [("zh", "zh-CN"), ("en", en_key)]


def load_allowlist() -> tuple[dict[tuple[str, str], int], list[str]]:
    entries: dict[tuple[str, str], int] = {}
    problems: list[str] = []
    if not os.path.isfile(ALLOWLIST):
        return entries, problems
    with open(ALLOWLIST, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "|" not in line:
                problems.append("第 %d 行格式错误（应为 lang|key）：%s" % (lineno, line))
                continue
            lang, key = (part.strip() for part in line.split("|", 1))
            if lang not in BUDGET:
                problems.append("第 %d 行语言未知（%s）：%s" % (lineno, lang, line))
                continue
            entries[(lang, key)] = lineno
    return entries, problems


def main() -> int:
    allow, allow_problems = load_allowlist()
    failures: list[str] = list(allow_problems)
    print("文案门禁（禁用词 / 提示长度）")

    current: dict[tuple[str, str], tuple[float, str]] = {}
    for lang, code in lang_tables():
        table = STRINGS[code]
        helps = [k for k in table if k.endswith(HELP_SUFFIX)]
        over = [k for k in helps if weighted(table[k]) > BUDGET[lang]]
        multi = [k for k in helps
                 if sum(table[k].count(x) for x in "。！？") > 1]
        for key in over:
            current[(lang, key)] = (weighted(table[key]), table[key])
        print("  OK   %s：%d 键 / 提示 %d 条 / 超标 %d（多句提示 %d，仅统计）"
              % (lang, len(table), len(helps), len(over), len(multi)))

        # 禁用词（大小写不敏感；中文表直接子串匹配）
        hits = 0
        for key, value in table.items():
            low = value.lower()
            for word in BANNED[lang]:
                if word.lower() in low:
                    hits += 1
                    failures.append(
                        "[%s] 禁用词「%s」→ %s：%s"
                        % (lang, word, key, value.replace("\n", " ")[:80]))
        if hits:
            print("  FAIL %s：禁用词命中 %d 条" % (lang, hits))
        else:
            print("  OK   %s：禁用词 0 命中" % lang)

    # allowlist 只缩不增：新增问题 vs 过期条目
    new = sorted(set(current) - set(allow))
    stale = sorted(set(allow) - set(current))

    for lang, key in new:
        score, value = current[(lang, key)]
        failures.append("[%s] 提示超预算 %.1f（> %d）：%s：%s"
                        % (lang, score, BUDGET[lang], key,
                           value.replace("\n", " ")[:80]))
    for lang, key in stale:
        failures.append("[%s] allowlist 过期，请删除该行：%s（第 %d 行）"
                        % (lang, key, allow[(lang, key)]))
    if new:
        print("  FAIL 新增超预算 %d 条（改文案，或按规矩确认后登记）" % len(new))
    if stale:
        print("  FAIL allowlist 过期 %d 条（只缩不增，请删行）" % len(stale))
    if not new and not stale:
        print("  OK   allowlist %d 条，无新增、无过期" % len(allow))

    print()
    if failures:
        for line in failures:
            print("  - " + line)
        print("FAILED: %d 项" % len(failures))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
