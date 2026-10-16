#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金数据小工具。

  python script/fund.py check            校验 _data/fund/（默认命令）
  python script/fund.py new 2026-10-24   用上次持仓做模板，新建这一天的快照

check 专门抓那些「不报错但数据不对」的问题——尤其是 id 拼错，
它在页面上是静默消失的，只有这里能发现。
"""

import difflib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(HERE), "_data", "fund")
SNAP_DIR = os.path.join(DATA_DIR, "snapshots")

VENUES = ("场内", "场外")
CHANNELS = ("场内", "场外直销", "场外分销")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

errors = []
warnings = []


def bad(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def load(path):
    """读 JSON；语法错误直接报成「第几行」，省得自己数括号。"""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        bad("%s 不是合法 JSON：第 %d 行第 %d 列 %s" % (rel(path), exc.lineno, exc.colno, exc.msg))
    except IOError as exc:
        bad("读不到 %s：%s" % (rel(path), exc.strerror))
    return None


def rel(path):
    """显示成 snapshots/2025-09-12.json 这种短路径，跟其它提示统一。"""
    try:
        return os.path.relpath(path, DATA_DIR).replace("\\", "/")
    except ValueError:
        return path


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


# ── 基金档案 ──────────────────────────────────────────────────────────
def check_funds(funds):
    if not isinstance(funds, list) or not funds:
        bad("funds.json 应该是一个非空数组")
        return []

    ids = []
    for i, f in enumerate(funds, 1):
        if not isinstance(f, dict):
            bad("funds.json 第 %d 项不是对象" % i)
            continue
        fid = f.get("id")
        label = fid or ("第 %d 项" % i)
        if not fid or not isinstance(fid, str):
            bad("funds.json %s：缺少 id" % label)
            continue
        if fid in ids:
            bad('funds.json 里 id "%s" 重复了' % fid)
        ids.append(fid)

        if not f.get("name"):
            warn('funds.json "%s"：没有 name，页面会显示成一串 id' % fid)
        if f.get("venue") not in VENUES:
            warn('funds.json "%s"：venue 是 %r，页面只认 场内 / 场外' % (fid, f.get("venue")))
        if f.get("channel") not in CHANNELS:
            warn(
                'funds.json "%s"：channel 是 %r，页面只认 场内 / 场外直销 / 场外分销'
                % (fid, f.get("channel"))
            )
    return ids


def suggest(bad_id, ids):
    close = difflib.get_close_matches(bad_id, ids, n=1, cutoff=0.6)
    return '\n      是不是想写 "%s"？' % close[0] if close else ""


# ── 快照 ──────────────────────────────────────────────────────────────
def read_snapshots():
    if not os.path.isdir(SNAP_DIR):
        bad("找不到 %s" % rel(SNAP_DIR))
        return []

    files = [n for n in os.listdir(SNAP_DIR) if n.lower().endswith(".json")]
    snaps = []
    for name in files:
        date = name[:-5]
        if not DATE_RE.match(date):
            bad("snapshots/%s：文件名必须是 YYYY-MM-DD.json —— 日期是从文件名取的" % name)
            continue
        body = load(os.path.join(SNAP_DIR, name))
        if body is None:
            continue
        if not isinstance(body, dict):
            bad("snapshots/%s：最外层应该是一个对象" % name)
            continue
        if "date" in body:
            warn(
                "snapshots/%s：里面的 date 是多余的（日期取文件名），删掉免得对不上"
                % name
            )
        holdings = body.get("holdings")
        if not isinstance(holdings, list):
            bad("snapshots/%s：缺少 holdings 数组" % name)
            continue
        snaps.append({"file": name, "date": date, "note": body.get("note", ""), "holdings": holdings})
    snaps.sort(key=lambda s: s["date"])
    return snaps


def check_snapshot(snap, prev, ids):
    label = "snapshots/" + snap["file"]
    seen = set()
    unknown = 0

    for h in snap["holdings"]:
        if not isinstance(h, dict):
            bad("%s：holdings 里混进了非对象" % label)
            continue
        fid = h.get("id")
        if fid is None:
            bad("%s：有一条 holdings 没写 id" % label)
            continue
        if fid not in ids:
            unknown += 1
            bad('%s：id "%s" 不在 funds.json 里%s' % (label, fid, suggest(fid, ids)))
            continue
        if fid in seen:
            bad('%s：id "%s" 出现了两次' % (label, fid))
        seen.add(fid)

        for key in ("invested", "value"):
            if not is_number(h.get(key)):
                bad('%s：「%s」的 %s 不是数字（%r）' % (label, fid, key, h.get(key)))
            elif h[key] < 0:
                bad('%s：「%s」的 %s 是负数（%r）' % (label, fid, key, h[key]))

    # 跟上一份快照比：漏记、投入倒退
    if prev is not None:
        prev_map = {h.get("id"): h for h in prev["holdings"] if isinstance(h, dict)}
        cur_map = {h.get("id"): h for h in snap["holdings"] if isinstance(h, dict)}

        gone = [i for i in prev_map if i in ids and i not in cur_map]
        if gone:
            warn("%s：上次有、这次没写的 %d 只（漏记了，还是真的清仓了？）" % (label, len(gone)))
            for fid in gone:
                warn("    - %s" % (names.get(fid) or fid))

        for fid, h in cur_map.items():
            if fid not in ids or fid not in prev_map:
                continue
            before, after = prev_map[fid].get("invested"), h.get("invested")
            if is_number(before) and is_number(after) and after < before:
                warn(
                    "%s：「%s」累计投入 %s → %s 变少了（没有清仓却倒退，抄错了吧？）"
                    % (label, names.get(fid) or fid, fmt(before), fmt(after))
                )


def fmt(x):
    return ("%.2f" % x).rstrip("0").rstrip(".")


names = {}


# ── check ─────────────────────────────────────────────────────────────
def cmd_check():
    if not os.path.isdir(DATA_DIR):
        print("找不到 %s" % rel(DATA_DIR))
        return 1

    meta = load(os.path.join(DATA_DIR, "meta.json"))
    if meta is not None and not isinstance(meta, dict):
        bad("meta.json 最外层应该是一个对象")

    funds = load(os.path.join(DATA_DIR, "funds.json"))
    ids = check_funds(funds) if funds is not None else []
    names.update({f["id"]: f.get("name", "") for f in (funds or []) if isinstance(f, dict) and f.get("id")})

    snaps = read_snapshots()

    for i, snap in enumerate(snaps):
        check_snapshot(snap, snaps[i - 1] if i else None, ids)

    # 日期重复（同一天两份文件不可能，因为文件名唯一；这里查乱序/未来）
    dates = [s["date"] for s in snaps]
    if dates != sorted(dates):
        bad("快照日期没有按时间递增：%s" % ", ".join(dates))
    if dates and dates[0] > _today():
        bad("最早的快照 %s 在今天之后，确认一下日期" % dates[0])

    # 从没在任何快照里出现过的基金
    if snaps:
        used = set()
        for s in snaps:
            used.update(h.get("id") for h in s["holdings"] if isinstance(h, dict))
        unused = [i for i in ids if i not in used]
        if unused:
            warn("funds.json 里有 %d 只基金从没在任何快照里出现过：" % len(unused))
            for fid in unused:
                warn("    - %s" % (names.get(fid) or fid))

    return report(len(ids), len(snaps))


def _today():
    import datetime

    return datetime.date.today().isoformat()


def report(n_funds, n_snaps):
    print("检查 _data/fund/  ——  %d 只基金，%d 份快照" % (n_funds, n_snaps))
    print("")

    for msg in warnings:
        print("! " + msg)
    if warnings:
        print("")
    for msg in errors:
        print("✗ " + msg)
    if errors:
        print("")

    if errors:
        print("发现 %d 个错误、%d 个提醒 —— 先修掉错误再提交。" % (len(errors), len(warnings)))
        print("（id 拼错的后果是那只基金在页面上静默消失，不会报错。）")
        return 1
    if warnings:
        print("没发现错误，%d 个提醒自己确认一下。" % len(warnings))
        return 0
    print("✓ 一切正常，可以提交了。")
    return 0


# ── new ───────────────────────────────────────────────────────────────
def cmd_new(date):
    if not DATE_RE.match(date):
        print("日期要写成 YYYY-MM-DD，比如 2026-10-24")
        return 1
    dest = os.path.join(SNAP_DIR, date + ".json")
    if os.path.exists(dest):
        print("snapshots/%s.json 已经存在了 —— 追加模式不覆盖，换个日期或先删掉它。" % date)
        return 1

    snaps = read_snapshots()
    if not snaps:
        print("还没有任何快照，第一份得自己手写。")
        return 1
    last = snaps[-1]
    if date <= last["date"]:
        print("新快照的日期 %s 要晚于上一份 %s。" % (date, last["date"]))
        return 1

    funds = load(os.path.join(DATA_DIR, "funds.json")) or []
    known = {f.get("id") for f in funds if isinstance(f, dict)}
    body = {
        "note": "",
        "holdings": [
            {"id": h.get("id"), "invested": h.get("invested"), "value": h.get("value")}
            for h in last["holdings"]
            if isinstance(h, dict) and h.get("id") in known
        ],
    }
    with open(dest, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(body, ensure_ascii=False, indent=2) + "\n")

    print("✓ 已新建 snapshots/%s.json" % date)
    print("  模板取自 %s 的 %d 只持仓，数字还是上次的 —— 逐个改成今天抄到的。" % (last["date"], len(body["holdings"])))
    print("  note 可以写一句备注（留空也行）。")
    print("")
    print("  改完跑一下：python script/fund.py check")
    return 0


# ── main ──────────────────────────────────────────────────────────────
def main(argv):
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "check":
        return cmd_check()
    if cmd in ("new", "add", "snapshot"):
        if len(argv) < 3:
            print("用法：python script/fund.py new 2026-10-24")
            return 1
        return cmd_new(argv[2])
    print(__doc__.strip())
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
