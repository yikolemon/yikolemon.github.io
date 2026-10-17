#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纳指100 场内 ETF 历史溢价率小工具。

  python script/etf_premium.py sync            增量更新 funds.json 里的全部标的
  python script/etf_premium.py sync 513100     只更新指定代码
  python script/etf_premium.py rebuild 513100  全量重抓（忽略已有净值缓存）
  python script/etf_premium.py check           校验 _data/etf_premium/（默认命令）
  python script/etf_premium.py show 513100     终端看这只 ETF 的年度溢价率分布
  python script/etf_premium.py compare         横向对比全部标的
  低溢价邮件告警是另一个脚本：
  python script/etf_premium_alert.py preview   回放历史上会响哪些日子（调阈值用）

口径（重要，别改）：
    溢价率(T) = 场内收盘价(T) ÷ 基金单位净值(T-1) − 1
    价格用**不复权**收盘价，净值用**单位净值**（两者都不能用复权/累计净值，否则分红会污染历史溢价率）。

数据来源：
    价格  https://web.ifzq.gtimg.cn/appstock/app/fqkline/get   （单次上限 640 根，按日期区间往回复溯）
    净值  https://api.fund.eastmoney.com/f10/lsjz              （固定 20 条/页）
    名称  https://hq.sinajs.cn/list=sh513100                   （用于校验 funds.json 里写的名字）

已知局限（写在这里免得以后自己踩）：
  曾经以为这里是「名义溢价率」，含一整段隔夜美股涨跌 —— 2026-10 用数据验过，那个说法是错的：
  QDII 的净值是按**美股交易日**记的，净值日 D 记的是美股 D 日（美东）那一段收盘，
  而次日 T 的场内价格反应的正是同一段，分子分母没有错位，算出来就是纯溢价。
  验法（两条独立的路子，结论一致）：
    1) 把各标的溢价率对「净值日那段美股涨跌」做回归，系数只有 -0.10（R² 0.002）——
       模型如果是「夹了一整段」，这个系数该在 1.0 附近。
    2) 场内价格的日收益与净值日那段的相关系数是 +0.60，与交易日本身那段只有 +0.06 ——
       说明价格跟着的就是净值日那一段。
  与集思录/HaoETF 的 iopv_discount_rt 差别只在「盘中实时」（它们用期货现价估），
  历史日线序列里没有需要剥离的隔夜涨跌。
  注意 2022-01-13（513100）和 2022-07-04（159941）的净值巨跳是份额折算，不是数据错误。
"""

import bisect
import datetime
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(HERE), "_data", "etf_premium")
SERIES_DIR = os.path.join(DATA_DIR, "series")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MAX_NAV_GAP_DAYS = 12   # 交易日与所用净值日期间隔超过这么多天，就丢弃这个点（停牌/长假）
STALE_DAYS = 20         # series 最后一天超过这么多天没更新就提醒
COLS = ("date", "close", "nav_date", "nav", "premium")

errors = []
warnings = []


def bad(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def rel(path):
    try:
        return os.path.relpath(path, DATA_DIR).replace("\\", "/")
    except ValueError:
        return path


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        bad("%s 不是合法 JSON：第 %d 行第 %d 列 %s" % (rel(path), exc.lineno, exc.colno, exc.msg))
    except IOError as exc:
        bad("读不到 %s：%s" % (rel(path), exc.strerror))
    return None


EXP_RE = re.compile(r'(?<![\w"])-?\d+(?:\.\d+)?[eE][-+]?\d+(?![\w"])')


def plain_numbers(text):
    """把 JSON 里的指数写法换成定点小数。

    json 对 |x| < 1e-4 的浮点会输出指数形式，而尾数没有小数点的那种
    （round(x, 6) 出来的 9e-05、-7e-05）会被 YAML 1.1 系的解析器判成**字符串**，
    于是数字进了页面就变字符串，前端一求和就是 NaN。Jekyll 读 _data/*.json
    正是走这条路。-7.6e-05 带小数点反而没事，但这种「有时是数字有时是字符串」
    更危险，所以这里一律写成定点小数。
    """
    def fix(match):
        out = "%.10f" % float(match.group(0))
        return out.rstrip("0").rstrip(".") if "." in out else out

    fixed = EXP_RE.sub(fix, text)
    json.loads(fixed)          # 改完必须还是合法 JSON，坏了立刻炸在脚本里
    return fixed


def save(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(body, ensure_ascii=False, indent=2) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(plain_numbers(text))


# ── HTTP ──────────────────────────────────────────────────────────────
def http_text(url, referer=None, tries=5):
    """东财/腾讯偶发掐连接，重试几次；失败把最后一次异常抛出去。"""
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:                      # noqa: BLE001 —— 网络层什么都可能抛
            last = exc
            time.sleep(1.2 * (i + 1))
    raise last


def http_json(url, referer=None, **kw):
    return json.loads(http_text(url, referer, **kw))


# ── 数据源 ────────────────────────────────────────────────────────────
def fetch_prices(exchange, code):
    """不复权日K → {日期: 收盘价}。整段重抓（每只基金也就 6 个请求）。"""
    sym = ("sh" if exchange == "SH" else "sz") + code
    out = {}
    end = datetime.date.today().isoformat()
    for _ in range(80):
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?" + urllib.parse.urlencode(
            {"param": "%s,day,1990-01-01,%s,640," % (sym, end)}
        )
        data = http_json(url).get("data", {}).get(sym, {}) or {}
        rows = data.get("day") or data.get("qfqday") or []
        if not rows:
            break
        for row in rows:
            out[row[0]] = float(row[2])               # [日期, 开, 收, 高, 低, 量]
        if len(rows) < 640:
            break
        end = (datetime.date.fromisoformat(rows[0][0]) - datetime.timedelta(days=1)).isoformat()
        time.sleep(0.3)
    return out


def fetch_navs(code, known):
    """单位净值 → {净值日期: 单位净值}。从第 1 页往回翻，整页都已存在就停（增量）。"""
    fresh = {}
    page = 1
    while page <= 400:
        url = "https://api.fund.eastmoney.com/f10/lsjz?" + urllib.parse.urlencode(
            {"fundCode": code, "pageIndex": page, "pageSize": 20}
        )
        body = http_json(url, referer="https://fundf10.eastmoney.com/")
        data = body.get("Data")
        if not data:
            raise RuntimeError("东财没返回 %s 的净值（代码写错了？）" % code)
        rows = data.get("LSJZList") or []
        if not rows:
            break
        all_known = True
        for it in rows:
            if it.get("DWJZ"):
                fresh[it["FSRQ"]] = float(it["DWJZ"])
                if it["FSRQ"] not in known:
                    all_known = False
        if all_known:
            break
        if len(fresh) + len(known) >= body.get("TotalCount", 0):
            break
        page += 1
        time.sleep(0.25)

    merged = dict(known)
    merged.update(fresh)
    return merged


def fetch_name(exchange, code):
    """新浪的官方简称，用来跟 funds.json 里手写的名字对一下。"""
    sym = ("sh" if exchange == "SH" else "sz") + code
    try:
        req = urllib.request.Request(
            "https://hq.sinajs.cn/list=" + sym,
            headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            txt = resp.read().decode("gbk", "replace")
        return txt.split('"')[1].split(",")[0] or None
    except Exception:                                  # noqa: BLE001
        return None


# ── 计算 ──────────────────────────────────────────────────────────────
def build_rows(prices, navs):
    """溢价率(T) = 收盘价(T) ÷ 单位净值(严格早于 T 的最近一天) − 1"""
    nav_dates = sorted(navs)
    rows = []
    for date in sorted(prices):
        i = bisect.bisect_left(nav_dates, date) - 1
        if i < 0:
            continue
        nav_date = nav_dates[i]
        gap = (datetime.date.fromisoformat(date) - datetime.date.fromisoformat(nav_date)).days
        if gap > MAX_NAV_GAP_DAYS:
            continue
        close, nav = prices[date], navs[nav_date]
        if nav <= 0:
            continue
        rows.append([date, close, nav_date, nav, round(close / nav - 1, 6)])
    return rows


def known_navs(series):
    """从已有 rows 里还原净值表，增量更新时当缓存用。"""
    return {r[2]: r[3] for r in series.get("rows", []) if len(r) >= 5 and r[2]}


# ── sync ──────────────────────────────────────────────────────────────
def read_funds():
    funds = load(os.path.join(DATA_DIR, "funds.json"))
    if funds is None:
        return []
    if not isinstance(funds, list) or not funds:
        bad("funds.json 应该是一个非空数组")
        return []
    return [f for f in funds if isinstance(f, dict) and f.get("code")]


def cmd_sync(codes, rebuild=False):
    funds = read_funds()
    if not funds:
        print("funds.json 里没读到任何标的，先补一个。")
        return 1
    if codes:
        known = {f["code"] for f in funds}
        unknown = [c for c in codes if c not in known]
        if unknown:
            print("funds.json 里没有这些代码：%s" % ", ".join(unknown))
            return 1
        funds = [f for f in funds if f["code"] in codes]

    print("更新 %d 只 ETF  ——  _data/etf_premium/" % len(funds))
    print("")
    for f in funds:
        code, exch = f["code"], f.get("exchange", "SH").upper()
        path = os.path.join(SERIES_DIR, code + ".json")
        old = {} if rebuild else (load(path) or {})
        t0 = time.time()

        prices = fetch_prices(exch, code)
        cache = {} if rebuild else known_navs(old)
        navs = fetch_navs(code, cache)
        rows = build_rows(prices, navs)
        fresh = len(set(navs) - set(cache))

        # 别让一次抓取失手把攒下来的历史覆盖掉。
        # build_rows 对同一批输入是确定的，而净值集合只会变大（增量缓存 + 新页），
        # 所以行数**只应该增长或持平**。变少一定是数据源没抓全（接口返回了 200
        # 但内容空/只给了一页）—— 这时候宁可这一只不写，也不要写坏。
        old_rows = old.get("rows") or []
        if old_rows and len(rows) < len(old_rows):
            warn("%s：这次只算出 %d 行，比已有的 %d 行少，八成是数据源没抓全 —— "
                 "这一只先不写（确认要全量重抓就用 rebuild %s）"
                 % (code, len(rows), len(old_rows), code))
            continue

        live = fetch_name(exch, code)
        if not live:
            warn("%s 在行情接口查不到，代码写错了吗？" % code)

        save(path, {
            "code": code,
            "exchange": exch,
            "name": f.get("name") or live,
            "manager": f.get("manager", ""),
            "tracking": f.get("tracking", ""),
            "listed": rows[0][0] if rows else None,
            "updated": datetime.date.today().isoformat(),
            "unit": "CNY",
            "method": "溢价率 = 场内收盘价(T) ÷ 基金单位净值(T-1) − 1（价格不复权、净值用单位净值）",
            "columns": list(COLS),
            "rows": rows,
        })
        if rows:
            print("  %-8s %-18s %5d 个交易日  %s → %s  (%d 条新净值, %.0fs)"
                  % (code, f.get("name") or live, len(rows), rows[0][0], rows[-1][0],
                     fresh, time.time() - t0))
        else:
            print("  %-8s 没抓到数据" % code)

    print("")
    for msg in warnings:
        print("! " + msg)
    return 0


# ── check ─────────────────────────────────────────────────────────────
def check_series(code, body):
    label = "series/%s.json" % code
    if not isinstance(body, dict):
        bad("%s：最外层应该是一个对象" % label)
        return None
    if body.get("code") != code:
        bad('%s：里面的 code 是 %r，跟文件名对不上' % (label, body.get("code")))
    if list(body.get("columns") or []) != list(COLS):
        bad("%s：columns 不对，应该是 %s" % (label, list(COLS)))

    rows = body.get("rows")
    if not isinstance(rows, list) or not rows:
        bad("%s：缺少 rows 数组" % label)
        return None

    dates, prev = [], None
    worst = 0.0
    for i, r in enumerate(rows, 1):
        if not isinstance(r, list) or len(r) != len(COLS):
            bad("%s：第 %d 行不是 %d 元数组" % (label, i, len(COLS)))
            return None
        date, close, nav_date, nav, prem = r
        if not DATE_RE.match(str(date)) or not DATE_RE.match(str(nav_date)):
            bad("%s：第 %d 行日期格式不对（%r / %r）" % (label, i, date, nav_date))
        if not (nav_date < date):
            bad("%s：第 %d 行净值日期 %s 不早于交易日 %s" % (label, i, nav_date, date))
        if not (isinstance(nav, (int, float)) and nav > 0):
            bad("%s：第 %d 行净值不是正数（%r）" % (label, i, nav))
            continue
        if not (isinstance(close, (int, float)) and close > 0):
            bad("%s：第 %d 行收盘价不是正数（%r）" % (label, i, close))
            continue
        worst = max(worst, abs(close / nav - 1 - prem))
        if not -0.5 < prem < 1.0:
            warn("%s：%s 的溢价率 %+.2f%% 离谱，确认一下" % (label, date, prem * 100))
        if prev is not None and date <= prev:
            bad("%s：日期没有严格递增（%s 后面是 %s）" % (label, prev, date))
        prev = date
        dates.append(date)

    if worst > 1e-5:
        bad("%s：premium 跟 close÷nav−1 对不上（最大差 %.6f）" % (label, worst))

    if body.get("listed") and body["listed"] != dates[0]:
        warn("%s：listed 是 %s，但第一行是 %s" % (label, body["listed"], dates[0]))

    last = datetime.date.fromisoformat(dates[-1])
    age = (datetime.date.today() - last).days
    if age > STALE_DAYS:
        warn("%s：最后一天是 %s，已经 %d 天没更新了，跑一下 sync" % (label, dates[-1], age))
    return set(dates)


def check_no_exponent(code, path):
    """序列文件里不许出现指数写法。

    json 会把 |x| < 1e-4 的浮点写成 9e-05 / -7e-05 这种**尾数没有小数点**的形式，
    Jekyll 解析 _data/*.json 时（YAML 1.1 口径）会把它当字符串，数字到了页面上
    就变字符串、求和变 NaN。save() 已经强制写成定点小数，这里再守一道 ——
    手改过文件的话能当场发现。
    """
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except IOError:
        return
    hits = EXP_RE.findall(text)
    if hits:
        bad("%s.json：有 %d 处指数写法（如 %s），页面会把它们当字符串。重跑一次 sync" %
            (code, len(hits), hits[0]))


def cmd_check():
    if not os.path.isdir(DATA_DIR):
        print("找不到 %s" % rel(DATA_DIR))
        return 1

    meta = load(os.path.join(DATA_DIR, "meta.json"))
    if meta is not None and not isinstance(meta, dict):
        bad("meta.json 最外层应该是一个对象")

    funds = read_funds()
    codes = [f["code"] for f in funds]

    listed = []
    if os.path.isdir(SERIES_DIR):
        listed = [n[:-5] for n in sorted(os.listdir(SERIES_DIR)) if n.endswith(".json")]

    for code in listed:
        path = os.path.join(SERIES_DIR, code + ".json")
        check_no_exponent(code, path)
        body = load(path)
        if body is not None:
            check_series(code, body)

    missing = [c for c in codes if c not in listed]
    if missing:
        warn("funds.json 里这 %d 只还没有数据，跑一下 sync：" % len(missing))
        for c in missing:
            warn("    - %s" % c)
    extra = [c for c in listed if c not in codes]
    if extra:
        warn("series/ 里这 %d 个文件不在 funds.json 里（会被页面忽略）：" % len(extra))
        for c in extra:
            warn("    - %s" % c)

    return report(len(codes), len(listed))


def report(n_funds, n_series):
    print("检查 _data/etf_premium/  ——  %d 只标的，%d 份序列" % (n_funds, n_series))
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
        print("发现 %d 个错误、%d 个提醒 —— 先修掉错误。" % (len(errors), len(warnings)))
        return 1
    if warnings:
        print("没发现错误，%d 个提醒自己确认一下。" % len(warnings))
        return 0
    print("✓ 一切正常，可以提交了。")
    return 0


# ── show ──────────────────────────────────────────────────────────────
def cmd_show(code):
    path = os.path.join(SERIES_DIR, code + ".json")
    if not os.path.exists(path):
        print("没有 %s，先跑 sync。" % rel(path))
        return 1
    body = load(path) or {}
    rows = body.get("rows") or []
    if not rows:
        print("%s 没有数据。" % code)
        return 1

    prems = sorted(r[4] for r in rows)
    n = len(prems)
    q = lambda p: prems[min(n - 1, int(n * p))]        # noqa: E731

    print("%s %s（%s / %s）—— %d 个交易日  %s → %s"
          % (code, body.get("name", ""), body.get("exchange", ""), body.get("manager", ""),
             n, rows[0][0], rows[-1][0]))
    print("")
    print("  溢价率  最低 %+.2f%%  p25 %+.2f%%  中位 %+.2f%%  p75 %+.2f%%  p95 %+.2f%%  最高 %+.2f%%"
          % (prems[0] * 100, q(.25) * 100, q(.5) * 100, q(.75) * 100, q(.95) * 100, prems[-1] * 100))
    print("")
    print("  %-6s%6s%10s%10s%10s%10s" % ("年份", "交易日", "均值", "中位", "最高", "最低"))
    by_year = {}
    for r in rows:
        by_year.setdefault(r[0][:4], []).append(r[4])
    for year in sorted(by_year):
        v = sorted(by_year[year])
        print("  %-6s%6d%10s%10s%10s%10s"
              % (year, len(v), pct(sum(v) / len(v)), pct(v[len(v) // 2]), pct(v[-1]), pct(v[0])))
    print("")
    print("  最近 5 个交易日：")
    for r in rows[-5:]:
        print("    %s  收盘 %-8.3f  净值 %s = %-8.4f  溢价 %+.2f%%" % (r[0], r[1], r[2], r[3], r[4] * 100))
    return 0


def pct(x):
    return "%+.2f%%" % (x * 100)


# ── compare ───────────────────────────────────────────────────────────
def cmd_compare():
    funds = read_funds()
    series = {}
    for f in funds:
        path = os.path.join(SERIES_DIR, f["code"] + ".json")
        if os.path.exists(path):
            body = load(path) or {}
            if body.get("rows"):
                series[f["code"]] = body
    if not series:
        print("还没有任何数据，先跑 sync。")
        return 1

    print("各年度溢价率均值（空格 = 当时还没上市）")
    print("")
    codes = list(series)
    print("%-6s" % "年份" + "".join("%12s" % c for c in codes))
    years = sorted({r[0][:4] for b in series.values() for r in b["rows"]})
    for year in years:
        line = "%-6s" % year
        for c in codes:
            v = [r[4] for r in series[c]["rows"] if r[0][:4] == year]
            line += "%12s" % (pct(sum(v) / len(v)) if v else "-")
        print(line)
    print("")
    print("最新溢价率 / 全历史中位数")
    print("")
    print("%-8s%-18s%10s%10s%10s" % ("代码", "名称", "最新", "中位", "最高"))
    for c, b in series.items():
        vals = sorted(r[4] for r in b["rows"])
        print("%-8s%-18s%10s%10s%10s"
              % (c, b.get("name", ""), pct(b["rows"][-1][4]),
                 pct(vals[len(vals) // 2]), pct(vals[-1])))
    return 0


# ── main ──────────────────────────────────────────────────────────────
def main(argv):
    cmd = argv[1] if len(argv) > 1 else "check"
    args = argv[2:]
    if cmd == "check":
        return cmd_check()
    if cmd == "sync":
        return cmd_sync(args)
    if cmd == "rebuild":
        return cmd_sync(args, rebuild=True)
    if cmd == "compare":
        return cmd_compare()
    if cmd == "show":
        if not args:
            print("用法：python script/etf_premium.py show 513100")
            return 1
        return cmd_show(args[0])
    print(__doc__.strip())
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
