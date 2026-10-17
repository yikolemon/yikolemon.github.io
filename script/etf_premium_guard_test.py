# -*- coding: utf-8 -*-
"""验证 cmd_sync 的「行数不许倒退」护栏：抓取失手时不能覆盖已有历史。

在临时目录里跑，绝不碰真数据。
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根
tmp = tempfile.mkdtemp(prefix="ep_guard_")
shutil.copytree(os.path.join(SRC, "script"), os.path.join(tmp, "script"))
shutil.copytree(os.path.join(SRC, "_data", "etf_premium"),
                os.path.join(tmp, "_data", "etf_premium"))

spec = importlib.util.spec_from_file_location(
    "ep", os.path.join(tmp, "script", "etf_premium.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

want = os.path.join(tmp, "_data", "etf_premium")
assert os.path.normcase(m.DATA_DIR) == os.path.normcase(want), m.DATA_DIR
print("临时工作区：%s" % tmp)

PATH = os.path.join(m.SERIES_DIR, "513100.json")
with open(PATH, encoding="utf-8") as fh:
    before = json.load(fh)
print("原始 513100：%d 行，updated=%s" % (len(before["rows"]), before["updated"]))

real_prices = m.fetch_prices
m.fetch_name = lambda exch, code: "（测试里不查名字）"

# ── 场景 1：接口返回 200 但只给了最近 10 天（历史被截断）─────────────
m.fetch_prices = lambda exch, code: {
    d: 1.0 for d in ("2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06",
                     "2026-10-07", "2026-10-08", "2026-10-09")
}
print("\n[1] 模拟「只抓到 7 天」的截断响应 …")
rc = m.cmd_sync(["513100"])
with open(PATH, encoding="utf-8") as fh:
    after = json.load(fh)
print("    sync 返回 %d，护栏提示：%s" % (rc, m.warnings[-1] if m.warnings else "（无！）"))
assert after["rows"] == before["rows"], "护栏失效：已有历史被截断覆盖了！"
assert after["updated"] == before["updated"], "护栏失效：文件被改写了！"
print("    ✓ 文件原封不动，历史保住了")

# ── 场景 2：返回空价格（最容易发生的失败）───────────────────────────
m.warnings.clear()
m.fetch_prices = lambda exch, code: {}
print("\n[2] 模拟「价格接口返回空」…")
m.cmd_sync(["513100"])
with open(PATH, encoding="utf-8") as fh:
    empty = json.load(fh)
assert empty["rows"] == before["rows"], "护栏失效：空响应把历史清空了！"
print("    ✓ 没有变成 rows: []，历史保住了")

# ── 场景 3：正常抓取应当照写（护栏不能误伤）────────────────────────
m.warnings.clear()
m.fetch_prices = real_prices
print("\n[3] 真实抓取（行数应当持平或增长，并且真的写入）…")
m.cmd_sync(["513100"])
with open(PATH, encoding="utf-8") as fh:
    ok = json.load(fh)
print("    抓完：%d 行（原 %d 行），护栏提示：%s"
      % (len(ok["rows"]), len(before["rows"]), m.warnings or "（无，正常）"))
assert len(ok["rows"]) >= len(before["rows"]), "正常抓取被误伤"
assert [r[0] for r in ok["rows"][:len(before["rows"])]] == [r[0] for r in before["rows"]], \
    "正常抓取把老行改掉了"
print("    ✓ 正常路径没被护栏挡住")

# ── 场景 4：rebuild 是逃生口，不看护栏 ────────────────────────────────
m.warnings.clear()
print("\n[4] rebuild 应当绕过护栏（全量重抓的逃生口）…")
m.cmd_sync(["513100"], rebuild=True)
with open(PATH, encoding="utf-8") as fh:
    rb = json.load(fh)
print("    rebuild 后 %d 行，护栏提示：%s"
      % (len(rb["rows"]), m.warnings or "（无，符合预期）"))
assert len(rb["rows"]) >= 3261, "rebuild 没抓到完整历史"
print("    ✓ rebuild 正常")

print("\n全部通过。")
shutil.rmtree(tmp, ignore_errors=True)
