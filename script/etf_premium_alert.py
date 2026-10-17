#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纳指100 场内 ETF「低溢价」邮件告警。

规则（每只标的各算各的）：
    最新交易日的溢价率 < 该标的最近 EP_ALERT_WINDOW 个交易日的后 EP_ALERT_PCT 分位
        → 触发
    同一只标的在 EP_ALERT_COOLDOWN 个自然日内不重复报
    一轮里所有触发的标的汇总成一封邮件

  python script/etf_premium_alert.py check       只看会不会触发（不发信、不写状态）
  python script/etf_premium_alert.py preview     历史回放：过去会响哪些日子（用来调阈值）
  python script/etf_premium_alert.py send         触发就发邮件；只有发成功了才写状态
  python script/etf_premium_alert.py test-mail    不管触没触发，直接发一封测试信

环境变量：
  EP_ALERT_WINDOW   分位窗口（交易日），默认 750 ≈ 3 年
  EP_ALERT_PCT      分位档位，默认 0.20 = 后 20%
  EP_ALERT_MIN      历史不足这么多天就不判断，默认 250
  EP_ALERT_COOLDOWN 冷却（自然日），默认 15；设 0 就是「只要在线下就每天都报」
  SMTP_HOST         默认 smtp.qq.com
  SMTP_PORT         默认 465；465 → SSL，587 → STARTTLS，其余走明文
  SMTP_TLS          强制指定 ssl / starttls / none（一般不用填）
  SMTP_USER         发信账号，QQ 邮箱填完整地址
  SMTP_PASS         QQ 邮箱填「授权码」，不是登录密码
  SMTP_TO           收信地址，默认发给自己

去重状态在 _data/etf_premium/alert_state.json（记每只标的上次发信所依据的数据日）。
状态只在邮件真的发出去之后才写 —— 发信失败下次会重试，不会漏。
"""

import datetime
import glob
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(HERE), "_data", "etf_premium")
SERIES_DIR = os.path.join(DATA_DIR, "series")
STATE_PATH = os.path.join(DATA_DIR, "alert_state.json")

PAGE_URL = "https://yikolemon.github.io/etf-premium/"

DATE_FMT = "%Y-%m-%d"


def env_int(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        sys.exit("::error::%s 不是整数：%r" % (name, raw))


def env_float(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        sys.exit("::error::%s 不是数：%r" % (name, raw))


def settings():
    return {
        "window": env_int("EP_ALERT_WINDOW", 750),
        "pct": env_float("EP_ALERT_PCT", 0.20),
        "min_n": env_int("EP_ALERT_MIN", 250),
        "cooldown": env_int("EP_ALERT_COOLDOWN", 15),
    }


# ── 读数据 ────────────────────────────────────────────────────────────
def load_funds():
    """{code: name}"""
    with open(os.path.join(DATA_DIR, "funds.json"), encoding="utf-8") as fh:
        return {f["code"]: f.get("name", f["code"]) for f in json.load(fh)}


def load_series():
    """{code: [(date, premium), ...]}，按日期升序，premium 为小数。"""
    out = {}
    for path in sorted(glob.glob(os.path.join(SERIES_DIR, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        vals = []
        for row in doc["rows"]:
            prem = row[4]
            if prem is None:
                continue
            vals.append((datetime.date.fromisoformat(row[0]), float(prem)))
        out[doc["code"]] = vals
    return out


def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    return doc.get("last_alert", {}) or {}


def save_state(last_alert):
    doc = {
        "note": "低溢价告警的去重状态：每只标的上次发信所依据的数据日。"
                "由 script/etf_premium_alert.py 维护，不要手改。",
        "last_alert": {k: last_alert[k] for k in sorted(last_alert)},
    }
    with open(STATE_PATH, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ── 判断 ──────────────────────────────────────────────────────────────
def quantile(sorted_vals, p):
    """p 分位（用最接近的那个样本，不做插值）——样本是真实交易日，插值没意义。"""
    if not sorted_vals:
        return None
    k = int(round((len(sorted_vals) - 1) * p))
    return sorted_vals[max(0, min(len(sorted_vals) - 1, k))]


def threshold_for(vals, i, window, pct, min_n):
    """第 i 个点该用的门槛：只用它**之前**的 window 个交易日，不含当天。"""
    hist = [v for _, v in vals[max(0, i - window):i]]
    if len(hist) < min_n:
        return None
    return quantile(sorted(hist), pct)


def evaluate_last(series, funds, cfg, last_alert, today=None):
    """只看最新一天，返回 [(date, code, name, prem, threshold), ...]。"""
    hits = []
    for code in sorted(series):
        vals = series[code]
        if not vals:
            continue
        date, prem = vals[-1]
        if today is not None and date != today:
            continue
        q = threshold_for(vals, len(vals) - 1, cfg["window"], cfg["pct"], cfg["min_n"])
        if q is None or prem >= q:
            continue
        prev = last_alert.get(code)
        if prev:
            try:
                gap = (date - datetime.date.fromisoformat(prev)).days
            except ValueError:
                gap = cfg["cooldown"]
            if gap < cfg["cooldown"]:
                continue
        hits.append((date, code, funds.get(code, code), prem, q))
    return hits


def replay(series, funds, cfg):
    """把历史上每只标的的触发日子回放一遍（冷却期同样生效，状态从空开始）。"""
    events = []
    for code in sorted(series):
        vals = series[code]
        last_alert = None
        for i in range(len(vals)):
            date, prem = vals[i]
            q = threshold_for(vals, i, cfg["window"], cfg["pct"], cfg["min_n"])
            if q is None or prem >= q:
                continue
            if last_alert is not None and (date - last_alert).days < cfg["cooldown"]:
                continue
            last_alert = date
            events.append((date, code, funds.get(code, code), prem, q))
    events.sort()
    return events


# ── 渲染 ──────────────────────────────────────────────────────────────
def summary(text):
    """往 Actions 的 job summary 里写一行；本地跑没有这个文件，静默跳过。"""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass


def pct_str(x):
    return "%+.2f%%" % (x * 100)


def disp_width(s):
    """中日韩字符按两列算 —— 邮件多半等宽字体显示，不然表会歪。"""
    return sum(2 if ord(ch) > 0x1100 else 1 for ch in s)


def pad(s, width):
    return s + " " * max(0, width - disp_width(s))


def align(s, width):
    return " " * max(0, width - disp_width(s)) + s


def render_mail(hits, cfg, funds):
    date = max(h[0] for h in hits)
    names = [h[2] for h in hits]
    head = "、".join(names[:3]) + ("等 %d 只" % len(names) if len(names) > 3 else "")
    subject = "[溢价率] %d 只跌到近 %.1f 年的后 %.0f%% 分位 · %s" % (
        len(hits), cfg["window"] / 244.0, cfg["pct"] * 100, date.isoformat())

    lines = [
        "纳指100 场内 ETF：%s 的溢价率跌到近 %.1f 年的后 %.0f%% 分位（数据日 %s）。"
        % (head, cfg["window"] / 244.0, cfg["pct"] * 100, date.isoformat()),
        "",
    ]
    nw = max(disp_width(h[2]) for h in hits)
    lines.append("  %-8s  %s  %10s  %12s  %8s"
                 % ("代码", pad("名称", nw), "溢价率", "门槛", "距门槛"))
    for date, code, name, prem, q in hits:
        lines.append("  %-8s  %s  %s  %s  %s"
                     % (code, pad(name, nw), align(pct_str(prem), 10),
                        align(pct_str(q), 12), align("%+.2fpp" % ((prem - q) * 100), 8)))
    lines += [
        "",
        "口径：溢价率(T) = 场内收盘价(T) ÷ 基金单位净值(T-1) − 1（价格不复权、净值用单位净值）",
        "门槛 = 该标的最近 %d 个交易日的后 %.0f%% 分位；同一只标的 %d 个自然日内只报一次。"
        % (cfg["window"], cfg["pct"] * 100, cfg["cooldown"]),
        "",
        "图表：%s" % PAGE_URL,
        "",
        "（自动发送，不构成投资建议）",
    ]
    return subject, "\n".join(lines)


# ── 发信 ──────────────────────────────────────────────────────────────
def send_mail(subject, body):
    # GitHub 的 secrets 没配时传进来的是空串，不是「不存在」，
    # 所以这里不能用 dict.get 的默认值
    host = (os.environ.get("SMTP_HOST") or "").strip() or "smtp.qq.com"
    port = env_int("SMTP_PORT", 465)
    user = (os.environ.get("SMTP_USER") or "").strip()
    password = os.environ.get("SMTP_PASS") or ""
    to = (os.environ.get("SMTP_TO") or "").strip() or user
    if not user or not password:
        sys.exit("::error::缺少 SMTP_USER / SMTP_PASS（QQ 邮箱的 SMTP_PASS 填授权码）")
    # 授权码是 ASCII；粘进了中文/全角字符的话 smtplib 会抛一个看不懂的
    # UnicodeEncodeError，不如在这里说清楚
    try:
        user.encode("ascii")
        password.encode("ascii")
    except UnicodeEncodeError:
        sys.exit("::error::SMTP_USER / SMTP_PASS 里有非 ASCII 字符。"
                 "QQ 邮箱的授权码是 16 位字母，注意别把中文、全角字符或说明文字一起粘进去。")

    mode = (os.environ.get("SMTP_TLS") or "").strip().lower()
    if mode not in ("ssl", "starttls", "none"):
        mode = "ssl" if port == 465 else "starttls" if port == 587 else "none"

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body, charset="utf-8")

    ctx = ssl.create_default_context()
    if mode == "ssl":
        conn = smtplib.SMTP_SSL(host, port, timeout=30, context=ctx)
    else:
        conn = smtplib.SMTP(host, port, timeout=30)
    try:
        if mode == "starttls":
            conn.starttls(context=ctx)
        conn.login(user, password)
        conn.send_message(msg)
    finally:
        try:
            conn.quit()
        except Exception:
            pass
    return to, mode


# ── 子命令 ────────────────────────────────────────────────────────────
def cmd_check():
    cfg = settings()
    series, funds = load_series(), load_funds()
    hits = evaluate_last(series, funds, cfg, load_state())
    if not hits:
        print("没有标的触发（窗口 %d 日 / 后 %.0f%% 分位 / 冷却 %d 天）"
              % (cfg["window"], cfg["pct"] * 100, cfg["cooldown"]))
        return 0

    subject, body = render_mail(hits, cfg, funds)
    print("会触发（--check 不发信）：")
    print(body)
    print("\n主题：%s" % subject)
    return 0


def cmd_preview():
    cfg = settings()
    series, funds = load_series(), load_funds()
    events = replay(series, funds, cfg)
    if not events:
        print("这套阈值下历史上一次都不会响。")
        return 0

    by_day = {}
    for date, code, name, prem, q in events:
        by_day.setdefault(date, []).append((code, name, prem, q))

    per_fund = {}
    for date, code, _n, _p, _q in events:
        per_fund[code] = per_fund.get(code, 0) + 1

    print("配置：窗口 %d 日（近 %.1f 年）/ 后 %.0f%% 分位 / 冷却 %d 天"
          % (cfg["window"], cfg["window"] / 244.0, cfg["pct"] * 100, cfg["cooldown"]))
    print("历史回放 %s → %s" % (events[0][0], events[-1][0]))
    print()
    for code in sorted(per_fund):
        years = len(series[code]) / 244.0
        print("  %-8s %-16s %3d 次  （%.1f 次/年）"
              % (code, funds.get(code, ""), per_fund[code], per_fund[code] / years))
    days = sorted(by_day)
    print()
    print("  合计 %d 个「触发日」（%d 只次），平均一年 %.1f 天会收到邮件"
          % (len(days), len(events), len(days) / ((events[-1][0] - events[0][0]).days / 365.25)))
    print()
    print("最近 25 个触发日：")
    for date in days[-25:]:
        row = by_day[date]
        print("  %s  %d 只  %s" % (date, len(row),
                                   "、".join("%s %s" % (c, pct_str(p)) for c, _n, p, _q in row[:4])
                                   + (" …" if len(row) > 4 else "")))
    return 0


def cmd_send(dry_run=False):
    cfg = settings()
    series, funds = load_series(), load_funds()
    state = load_state()
    hits = evaluate_last(series, funds, cfg, state)
    if not hits:
        print("没有标的触发，不发信。")
        summary("### 低溢价告警\n\n没有标的触发（窗口 %d 日 / 后 %.0f%% 分位 / 冷却 %d 天）。"
                % (cfg["window"], cfg["pct"] * 100, cfg["cooldown"]))
        return 0

    subject, body = render_mail(hits, cfg, funds)
    print(body)
    print()
    if dry_run:
        print("（--dry-run，没发信、没写状态）")
        return 0

    try:
        to, mode = send_mail(subject, body)
    except (OSError, smtplib.SMTPException) as exc:
        # 状态这行绝不能在发信成功之前写 —— 写了就等于「通知过了」，
        # 而用户什么都没收到。失败就退出，下次跑会重来。
        print("::error::发信失败：%s: %s" % (type(exc).__name__, exc))
        print("常见原因：SMTP_USER / SMTP_PASS 不对、授权码被重置、QQ 邮箱没开 SMTP 服务、"
              "端口与加密方式不匹配（465 走 SSL、587 走 STARTTLS）。")
        print("在 Actions 里手动跑一次 `test-mail` 就能单独验证发信。")
        return 1
    print("已发送到 %s（%s）" % (to, mode))

    for date, code, _n, _p, _q in hits:
        state[code] = date.isoformat()
    save_state(state)
    print("已更新状态：%s" % ", ".join("%s → %s" % (h[1], h[0]) for h in hits))
    summary("### 低溢价告警：已发信到 %s\n\n"
            "| 代码 | 名称 | 溢价率 | 门槛（近 %.0f 年后 %.0f%%） |\n| --- | --- | --- | --- |\n%s"
            % (to, cfg["window"] / 244.0, cfg["pct"] * 100,
               "\n".join("| %s | %s | %s | %s |" % (c, n, pct_str(p), pct_str(q))
                         for _d, c, n, p, q in hits)))
    return 0


def cmd_test_mail():
    cfg = settings()
    series = load_series()
    newest = max((v[-1][0] for v in series.values() if v), default=datetime.date.today())
    subject = "[溢价率] 测试信（数据日 %s）" % newest.isoformat()
    body = "\n".join([
        "这是一封测试信，用来确认 SMTP 配置没问题。",
        "",
        "配置：窗口 %d 日 / 后 %.0f%% 分位 / 冷却 %d 天" % (cfg["window"], cfg["pct"] * 100, cfg["cooldown"]),
        "数据：%d 只标的，最新数据日 %s" % (len(series), newest.isoformat()),
        "",
        "图表：%s" % PAGE_URL,
    ])
    try:
        to, mode = send_mail(subject, body)
    except (OSError, smtplib.SMTPException) as exc:
        print("::error::测试信发送失败：%s: %s" % (type(exc).__name__, exc))
        print("常见原因：SMTP_USER / SMTP_PASS 不对、授权码被重置、QQ 邮箱没开 SMTP 服务、"
              "端口与加密方式不匹配（465 走 SSL、587 走 STARTTLS）。")
        return 1
    print("测试信已发送到 %s（%s）" % (to, mode))
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "check"
    args = argv[2:]
    if cmd == "check":
        return cmd_check()
    if cmd == "preview":
        return cmd_preview()
    if cmd == "send":
        return cmd_send(dry_run="--dry-run" in args)
    if cmd == "test-mail":
        return cmd_test_mail()
    print(__doc__.strip())
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
