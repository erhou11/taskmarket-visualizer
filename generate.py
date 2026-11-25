#!/usr/bin/env python3
"""Taskmarket live market visualizer — static generator.

Fetches the public Taskmarket API (no key) server-side, computes derived
views (weekly distinct requesters, lifecycle insights, money-flow), and
writes a single self-contained index.html (inline SVG charts, no external
CDN, no analytics, no wallet connection) plus og.png (PIL, if available).

Usage: python3 generate.py [output_dir]
"""
import json, math, os, sys, time, urllib.request, urllib.error
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

BASE = "https://api.taskmarket.dev"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36 taskmarket-visualizer/1.0"}
CHAINS = {4217: {"name": "Tempo", "ccy": "OUSD"}, 8453: {"name": "Base", "ccy": "USDC"}}
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))

import subprocess
def fetch(path, tries=4):
    url = BASE + path
    for i in range(tries):
        try:
            out = subprocess.run(
                ["curl", "-sS", "--max-time", "60", "-A", UA["User-Agent"], url],
                capture_output=True, timeout=70)
            if out.returncode == 0 and out.stdout:
                return json.loads(out.stdout.decode())
            raise RuntimeError(f"curl rc={out.returncode} {out.stderr.decode()[:120]}")
        except Exception as e:
            if i == tries - 1:
                print(f"WARN fetch failed {path}: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (i + 1))

def money(micro):
    """micro-units string/int -> dollars float"""
    try:
        return int(micro) / 1_000_000
    except Exception:
        return 0.0

def fmt_money(v):
    if v >= 1000:
        return "$" + f"{v:,.0f}"
    return "$" + f"{v:,.2f}"

def fmt_num(v):
    return f"{int(v):,}"

def esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))

def fetch_all_tasks(chain):
    tasks, cursor = [], None
    for _ in range(40):  # hard cap 4000 tasks
        q = f"/api/tasks?chainId={chain}&sort=newest&limit=100"
        if cursor:
            q += "&cursor=" + urllib.request.quote(cursor, safe="")
        d = fetch(q)
        if not d or not d.get("tasks"):
            break
        tasks.extend(d["tasks"])
        if not d.get("hasMore") or not d.get("nextCursor"):
            break
        cursor = d["nextCursor"]
    return tasks

def iso_week(dt):
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"

def parse_dt(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

# ---------- SVG chart helpers ----------
def line_chart(series, w=680, h=170, color="#E74079", fmt=lambda v: f"{v:,.0f}"):
    """series: list of (label, value). Returns inline SVG string."""
    if not series:
        return "<p class='muted'>No data.</p>"
    vals = [v for _, v in series]
    mx = max(vals) if max(vals) > 0 else 1
    mn = 0
    pad_l, pad_r, pad_t, pad_b = 8, 8, 14, 20
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    n = len(series)
    pts = []
    for i, (_, v) in enumerate(series):
        x = pad_l + (iw * i / (n - 1) if n > 1 else iw / 2)
        y = pad_t + ih - (v - mn) / (mx - mn) * ih
        pts.append((x, y))
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = path + f" L{pts[-1][0]:.1f},{pad_t+ih} L{pts[0][0]:.1f},{pad_t+ih} Z"
    dots = ""
    step = max(1, n // 12)
    for i in range(0, n, step):
        x, y = pts[i]
        dots += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{color}"><title>{esc(series[i][0])}: {esc(fmt(series[i][1]))}</title></circle>'
    last = pts[-1]
    dots += f'<circle cx="{last[0]:.1f}" cy="{last[1]:.1f}" r="3" fill="{color}"><title>{esc(series[-1][0])}: {esc(fmt(series[-1][1]))}</title></circle>'
    labels = ""
    for i in range(0, n, step):
        x, _ = pts[i]
        labels += f'<text x="{x:.1f}" y="{h-4}" fill="#B0A79D" font-size="9" text-anchor="middle">{esc(series[i][0][-5:] if len(series[i][0])>6 else series[i][0])}</text>'
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img">'
            f'<text x="{pad_l}" y="10" fill="#B0A79D" font-size="10">max {esc(fmt(mx))}</text>'
            f'<path d="{area}" fill="{color}" opacity="0.14"/>'
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"/>{dots}{labels}</svg>')

def bar_rows(items, total, color="#E74079"):
    """items: list of (label, count). Horizontal bars in HTML/CSS."""
    if total <= 0:
        total = sum(c for _, c in items) or 1
    out = []
    for label, c in items:
        pct = c / total * 100
        out.append(f'<div class="bar-row"><span class="bar-label">{esc(label)}</span>'
                   f'<span class="bar-track"><span class="bar-fill" style="width:{pct:.1f}%;background:{color}"></span></span>'
                   f'<span class="bar-val">{fmt_num(c)} · {pct:.1f}%</span></div>')
    return "\n".join(out)

def heatmap_table(hm, row_labels=None):
    if not hm or not hm.get("cells"):
        return "<p class='muted'>No heatmap data.</p>"
    rows, cols = hm["rowKeys"], hm["colKeys"]
    grid = {(c["row"], c["col"]): c["count"] for c in hm["cells"]}
    mx = max(grid.values()) if grid else 1
    th = "".join(f"<th>{esc(c[-5:] if len(str(c))>6 else c)}</th>" for c in cols)
    body = []
    for r in rows:
        label = (row_labels or {}).get(str(r), str(r))
        tds = []
        for c in cols:
            v = grid.get((str(r), str(c)), 0)
            a = 0.06 + 0.94 * (math.sqrt(v / mx) if mx else 0) if v else 0
            bg = f"background:rgba(231,64,121,{a:.2f})" if v else ""
            tds.append(f'<td style="{bg}" title="{esc(label)} · {esc(c)}: {v}">{v if v else ""}</td>')
        body.append(f"<tr><th class='rowh'>{esc(label)}</th>{''.join(tds)}</tr>")
    return f'<div class="hm-wrap"><table class="hm"><thead><tr><th></th>{th}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'

# ---------- per-chain build ----------
def build_chain(chain):
    meta = CHAINS[chain]
    stats = fetch(f"/api/market/stats?chainId={chain}") or {}
    breakdowns = fetch(f"/api/stats/breakdowns?chainId={chain}") or {}
    series = {}
    for rng, bucket in [("7d", "day"), ("30d", "day"), ("90d", "week"), ("all", "week")]:
        series[rng] = fetch(f"/api/stats/platform-time-series?chainId={chain}&range={rng}&bucket={bucket}") or []
    hm_mode = fetch(f"/api/stats/activity-heatmap?chainId={chain}&range=30d&dimension=mode")
    hm_hour = fetch(f"/api/stats/activity-heatmap?chainId={chain}&range=30d&dimension=hourOfWeek")
    feed = fetch(f"/api/stats/activity-feed?chainId={chain}&limit=20") or {}
    tasks = fetch_all_tasks(chain)
    now = datetime.now(timezone.utc)

    # --- derived: weekly distinct requesters (from /api/tasks, ISO week of createdAt) ---
    weekly = defaultdict(set)
    weekly_count = Counter()
    for t in tasks:
        dt = parse_dt(t.get("createdAt") or "")
        if dt and t.get("requester"):
            weekly[iso_week(dt)].add(t["requester"].lower())
            weekly_count[iso_week(dt)] += 1
    weeks_sorted = sorted(weekly.keys())[-10:]

    # --- derived: lifecycle insights from task list ---
    total_tasks = len(tasks)
    status_c = Counter(t.get("status", "?") for t in tasks)
    mode_c = Counter(t.get("mode", "?") for t in tasks)
    req_c = Counter((t.get("requester") or "").lower() for t in tasks)
    req_vol = Counter()
    for t in tasks:
        req_vol[(t.get("requester") or "").lower()] += money(t.get("reward"))
    total_vol = sum(req_vol.values())
    top1_share = (max(req_c.values()) / total_tasks * 100) if total_tasks and req_c else 0
    top5 = sum(c for _, c in req_c.most_common(5))
    top5_share = (top5 / total_tasks * 100) if total_tasks else 0
    top1_vol_share = (max(req_vol.values()) / total_vol * 100) if total_vol and req_vol else 0
    expired_undecided = status_c.get("expired", 0)
    open_past_expiry = sum(1 for t in tasks if t.get("status") == "open"
                           and parse_dt(t.get("expiryTime") or "") and parse_dt(t["expiryTime"]) < now)
    subs = [int(t.get("submissionCount") or 0) for t in tasks]
    avg_subs = sum(subs) / len(subs) if subs else 0
    # decision window: median review+decision window from terms (days), stated as configured window
    dw = []
    for t in tasks:
        terms = t.get("terms") or {}
        if terms.get("decisionWindowSecs"):
            dw.append(terms["decisionWindowSecs"] / 86400)
    avg_decision_days = sum(dw) / len(dw) if dw else 0
    # fastest growing mode: last 7d vs prior 7d task counts by mode
    g = {}
    for mode in mode_c:
        last = sum(1 for t in tasks if t.get("mode") == mode and parse_dt(t.get("createdAt") or "")
                   and parse_dt(t["createdAt"]) >= now - timedelta(days=7))
        prev = sum(1 for t in tasks if t.get("mode") == mode and parse_dt(t.get("createdAt") or "")
                   and now - timedelta(days=14) <= parse_dt(t["createdAt"]) < now - timedelta(days=7))
        g[mode] = (last, prev, (last - prev))
    fastest = max(g.items(), key=lambda kv: kv[1][2]) if g else (None, (0, 0, 0))

    # --- money flow aggregates (from task list sample) ---
    open_vol = sum(money(t.get("reward")) for t in tasks if t.get("status") == "open")
    completed_n = status_c.get("completed", 0)
    ts_all = series.get("all") or []
    paid_total = sum(money(r.get("paidVolume")) for r in ts_all)
    reward_total_ts = sum(money(r.get("rewardVolume")) for r in ts_all)

    return {
        "meta": meta, "stats": stats, "breakdowns": breakdowns, "series": series,
        "hm_mode": hm_mode, "hm_hour": hm_hour, "feed": feed.get("items", []),
        "tasks_n": total_tasks, "weeks": [(w, len(weekly[w]), weekly_count[w]) for w in weeks_sorted],
        "status_c": status_c, "mode_c": mode_c,
        "insights": {
            "top1_share": top1_share, "top5_share": top5_share, "top1_vol_share": top1_vol_share,
            "expired": expired_undecided, "open_past_expiry": open_past_expiry,
            "avg_subs": avg_subs, "avg_decision_days": avg_decision_days,
            "fastest": fastest, "growth": g, "distinct_requesters": len(req_c),
        },
        "flow": {"open_vol": open_vol, "completed_n": completed_n,
                 "paid_total": paid_total, "reward_total_ts": reward_total_ts,
                 "total_vol_list": total_vol},
    }

def chain_html(cid, d):
    m, s = d["meta"], d["stats"]
    ins = d["insights"]
    cards = [
        ("Open tasks", fmt_num(s.get("openTasks", 0))),
        ("Active agents · 7d", fmt_num(s.get("activeAgents7d", 0))),
        ("Active workers · 7d", fmt_num(s.get("activeWorkers7d", 0))),
        ("Registered workers", fmt_num(s.get("registeredWorkers", 0))),
        ("Workers paid", fmt_num(s.get("paidWorkers", 0))),
        ("Active wallets", fmt_num(s.get("activeWallets", 0))),
        ("Tasks listed (all pages)", fmt_num(d["tasks_n"])),
        ("Distinct requesters", fmt_num(ins["distinct_requesters"])),
    ]
    cards_html = "".join(f'<div class="card"><div class="card-num">{v}</div><div class="card-label">{k}</div></div>' for k, v in cards)

    # time series blocks per range
    metrics = [("activeAgents", "Active agents", "#E74079", lambda v: f"{v:,.0f}"),
               ("tasksCreated", "Tasks posted", "#D9A097", lambda v: f"{v:,.0f}"),
               ("rewardVolume", "Reward volume posted", "#EFE9E2", fmt_money),
               ("paidVolume", "Rewards paid out", "#7FB069", fmt_money)]
    ts_html = ""
    for rng in ["7d", "30d", "90d", "all"]:
        rows = d["series"].get(rng) or []
        blocks = ""
        for key, label, color, fmt in metrics:
            conv = (lambda v: money(v)) if key in ("rewardVolume", "paidVolume") else (lambda v: v)
            ser = [(r["bucket"], conv(r.get(key) or 0)) for r in rows]
            blocks += f'<div class="chart-box"><h4>{label}</h4>{line_chart(ser, color=color, fmt=fmt)}</div>'
        ts_html += f'<div class="ts-range" data-range="{rng}" style="display:{"block" if rng=="30d" else "none"}"><div class="chart-grid">{blocks}</div></div>'

    bd = d["breakdowns"]
    mode_items = [(x["mode"], x["count"]) for x in bd.get("mode", [])]
    status_items = [(x["status"], x["count"]) for x in bd.get("status", [])]
    mode_total = sum(c for _, c in mode_items)
    status_total = sum(c for _, c in status_items)

    dow = {"0": "Mon", "1": "Tue", "2": "Wed", "3": "Thu", "4": "Fri", "5": "Sat", "6": "Sun"}
    hm_hour_html = ""
    if d["hm_hour"]:
        hm2 = dict(d["hm_hour"])
        hm2["colKeys"] = [str(i) for i in range(24)]
        hm_hour_html = heatmap_table(hm2, row_labels=dow)

    feed_html = ""
    for it in d["feed"][:15]:
        ts = esc((it.get("timestamp") or "")[:16].replace("T", " "))
        amt = fmt_money(money(it["amount"])) if it.get("amount") else ""
        feed_html += (f'<li><span class="feed-type">{esc(it.get("type"))}</span> '
                      f'<span class="feed-title">{esc((it.get("taskTitle") or "")[:90])}</span> '
                      f'<span class="feed-meta">{ts} UTC {esc(amt)}</span></li>')
    if not feed_html:
        feed_html = "<li class='muted'>No recent activity returned.</li>"

    weeks_rows = "".join(
        f'<tr><td>{esc(w)}</td><td>{fmt_num(u)}</td><td>{fmt_num(c)}</td></tr>' for w, u, c in d["weeks"])
    fm, (fl, fp, fd) = ins["fastest"][0], ins["fastest"][1]
    flow = d["flow"]
    # money-flow: simple SVG flow with real aggregates
    flow_svg = f'''<svg viewBox="0 0 680 150" width="100%" role="img">
<rect x="10" y="45" width="150" height="60" rx="10" fill="#221E1A" stroke="#453E37"/>
<text x="85" y="70" fill="#EFE9E2" font-size="12" text-anchor="middle">Requesters</text>
<text x="85" y="90" fill="#B0A79D" font-size="11" text-anchor="middle">{fmt_num(ins["distinct_requesters"])} distinct</text>
<rect x="265" y="45" width="150" height="60" rx="10" fill="#221E1A" stroke="#453E37"/>
<text x="340" y="70" fill="#EFE9E2" font-size="12" text-anchor="middle">Escrow posted</text>
<text x="340" y="90" fill="#B0A79D" font-size="11" text-anchor="middle">{fmt_money(flow["reward_total_ts"])} all-time series</text>
<rect x="520" y="10" width="150" height="55" rx="10" fill="#221E1A" stroke="#453E37"/>
<text x="595" y="33" fill="#EFE9E2" font-size="12" text-anchor="middle">Paid to winners</text>
<text x="595" y="52" fill="#B0A79D" font-size="11" text-anchor="middle">{fmt_money(flow["paid_total"])}</text>
<rect x="520" y="85" width="150" height="55" rx="10" fill="#221E1A" stroke="#453E37"/>
<text x="595" y="108" fill="#EFE9E2" font-size="12" text-anchor="middle">Still open</text>
<text x="595" y="127" fill="#B0A79D" font-size="11" text-anchor="middle">{fmt_money(flow["open_vol"])} in open tasks</text>
<path d="M160,75 L265,75" stroke="#E74079" stroke-width="3" fill="none"/>
<path d="M415,65 C470,55 470,40 520,38" stroke="#7FB069" stroke-width="3" fill="none"/>
<path d="M415,85 C470,95 470,110 520,112" stroke="#D9A097" stroke-width="3" fill="none"/>
</svg>'''

    return f'''
<section class="chain" data-chain="{cid}">
  <div class="cards">{cards_html}</div>

  <h3>Activity over time</h3>
  <div class="range-switch" role="group" aria-label="Range">
    {"".join(f'<button data-range-btn="{r}" class="{"on" if r=="30d" else ""}">{r}</button>' for r in ["7d","30d","90d","all"])}
  </div>
  {ts_html}

  <div class="two-col">
    <div><h3>Tasks by mode</h3>{bar_rows(mode_items, mode_total)}</div>
    <div><h3>Tasks by status</h3>{bar_rows(status_items, status_total, color="#D9A097")}</div>
  </div>

  <h3>Money flow ({esc(m["ccy"])})</h3>
  <div class="panel">{flow_svg}
  <p class="muted">Escrow and paid totals are summed from the platform time-series (all range). “Still open” sums the rewards of tasks currently in <i>open</i> status in the full task list. Reward is held in escrow until the requester accepts a result.</p></div>

  <h3>Lifecycle insights</h3>
  <div class="panel"><ul class="insights">
    <li>Requester concentration: the top requester accounts for <b>{ins["top1_share"]:.1f}%</b> of listed tasks; the top 5 account for <b>{ins["top5_share"]:.1f}%</b>. Top requester by reward volume: <b>{ins["top1_vol_share"]:.1f}%</b> of listed volume.</li>
    <li>Expired without a decision: <b>{fmt_num(ins["expired"])}</b> tasks; open past their expiry time: <b>{fmt_num(ins["open_past_expiry"])}</b>.</li>
    <li>Competition: <b>{ins["avg_subs"]:.1f}</b> submissions per task on average. Configured decision window averages <b>{ins["avg_decision_days"]:.1f} days</b> (from each task’s terms).</li>
    <li>Fastest-growing mode (last 7 days vs prior 7 days, by tasks posted): <b>{esc(fm or "—")}</b> ({fl} vs {fp}, change {fd:+d}).</li>
  </ul></div>

  <h3>Weekly distinct requesters</h3>
  <div class="panel"><p class="muted">Method: every page of <span class="mono">/api/tasks</span> for this chain was fetched; each task’s requester address was counted once per ISO week of its creation date. Addresses are counted, not named.</p>
  <table class="plain"><thead><tr><th>ISO week</th><th>Distinct requesters</th><th>Tasks posted</th></tr></thead><tbody>{weeks_rows}</tbody></table></div>

  <h3>Activity heatmap — by mode, last 30 days</h3>
  {heatmap_table(d["hm_mode"])}
  <h3>Activity heatmap — by day of week × hour (UTC), last 30 days</h3>
  {hm_hour_html}

  <h3>Latest activity</h3>
  <ul class="feed">{feed_html}</ul>
</section>'''

CSS = """
*{box-sizing:border-box}html,body{margin:0;padding:0}
body{background:#12100E;color:#EFE9E2;font-family:'Inter Tight',system-ui,-apple-system,'Segoe UI',Roboto,'Noto Sans',sans-serif;line-height:1.5}
a{color:#D9A097}
.wrap{max-width:1060px;margin:0 auto;padding:20px 16px 48px}
header{padding:28px 0 8px;background:radial-gradient(600px 220px at 85% 0%,#3A1420 0%,#12100E 70%)}
h1{font-family:Georgia,'Times New Roman','Noto Serif',serif;font-weight:400;font-size:clamp(30px,6vw,52px);margin:0 0 6px}
h1 em{color:#E74079;font-style:italic}
h3{font-family:Georgia,'Times New Roman',serif;font-weight:400;font-size:22px;margin:30px 0 10px}
h4{margin:0 0 4px;font-size:13px;color:#B0A79D;font-weight:600}
.mono,code{font-family:ui-monospace,'SF Mono',Menlo,Consolas,monospace;font-size:.92em}
.muted{color:#B0A79D;font-size:14px}
.asof{color:#B0A79D;font-size:14px}
.chain-switch,.range-switch{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}
.chain-switch button,.range-switch button{background:#221E1A;color:#EFE9E2;border:1px solid #453E37;border-radius:999px;padding:8px 16px;cursor:pointer;font:inherit;font-size:14px}
.chain-switch button.on,.range-switch button.on{background:#E74079;border-color:#E74079;color:#FFF6E8}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-top:16px}
.card{background:#221E1A;border:1px solid #453E37;border-radius:14px;padding:14px}
.card-num{font-size:26px;font-weight:600}
.card-label{color:#B0A79D;font-size:12.5px;margin-top:2px}
.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.chart-box,.panel{background:#221E1A;border:1px solid #453E37;border-radius:14px;padding:14px}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.bar-row{display:grid;grid-template-columns:110px 1fr 110px;gap:8px;align-items:center;margin:7px 0;font-size:13.5px}
.bar-track{background:#12100E;border-radius:6px;height:12px;overflow:hidden}
.bar-fill{display:block;height:100%;border-radius:6px}
.bar-val{color:#B0A79D;text-align:right}
.hm-wrap{overflow-x:auto;background:#221E1A;border:1px solid #453E37;border-radius:14px;padding:10px}
table.hm{border-collapse:collapse;font-size:10.5px;min-width:640px}
table.hm td,table.hm th{padding:3px 4px;text-align:center;color:#EFE9E2;white-space:nowrap}
table.hm th.rowh{text-align:right;color:#B0A79D;font-size:11.5px;padding-right:8px}
table.plain{border-collapse:collapse;width:100%;font-size:14px}
table.plain td,table.plain th{border-bottom:1px solid #453E37;padding:6px 8px;text-align:left}
ul.feed{list-style:none;padding:0;margin:0}
ul.feed li{background:#221E1A;border:1px solid #453E37;border-radius:10px;padding:9px 12px;margin:7px 0;font-size:14px}
.feed-type{color:#E74079;font-family:ui-monospace,Menlo,monospace;font-size:12px;margin-right:8px}
.feed-meta{display:block;color:#B0A79D;font-size:12px}
ul.insights{margin:0;padding-left:18px}ul.insights li{margin:7px 0}
footer{border-top:1px solid #453E37;margin-top:36px;padding-top:16px;color:#B0A79D;font-size:13.5px}
@media (max-width:700px){.chart-grid,.two-col{grid-template-columns:1fr}.bar-row{grid-template-columns:88px 1fr 92px}}
"""

JS = """
document.querySelectorAll('[data-chain-btn]').forEach(b=>b.addEventListener('click',()=>{
 document.querySelectorAll('[data-chain-btn]').forEach(x=>x.classList.toggle('on',x===b));
 document.querySelectorAll('.chain').forEach(s=>s.style.display=(s.dataset.chain===b.dataset.chainBtn?'block':'none'));
}));
document.querySelectorAll('.chain').forEach(sec=>{
 sec.querySelectorAll('[data-range-btn]').forEach(b=>b.addEventListener('click',()=>{
  sec.querySelectorAll('[data-range-btn]').forEach(x=>x.classList.toggle('on',x===b));
  sec.querySelectorAll('.ts-range').forEach(r=>r.style.display=(r.dataset.range===b.dataset.rangeBtn?'block':'none'));
 }));
});
"""

def make_og(path, totals):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        print("PIL unavailable, skipping og.png", file=sys.stderr)
        return
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), (18, 16, 14))
    dr = ImageDraw.Draw(img, "RGBA")
    for i in range(300):
        a = int(90 * (1 - i / 300))
        dr.ellipse([W - 420 + i // 2, -180 + i // 3, W + 180 - i // 2, 300 - i // 3], fill=(58, 20, 32, a))
    def font(sz, serif=False):
        for p in (["/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"] if serif else
                  ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]):
            if os.path.exists(p):
                return ImageFont.truetype(p, sz)
        return ImageFont.load_default()
    dr.text((60, 70), "Taskmarket, in numbers", font=font(64, serif=True), fill=(239, 233, 226))
    dr.text((60, 160), "A live market visualizer — real API data, refreshed every 15 minutes.", font=font(26), fill=(176, 167, 157))
    y = 250
    for label, val in totals:
        dr.text((60, y), val, font=font(44), fill=(231, 64, 121))
        dr.text((430, y + 12), label, font=font(26), fill=(239, 233, 226))
        y += 78
    dr.text((60, H - 60), "taskmarket.dev", font=font(24), fill=(217, 160, 151))
    img.save(path, "PNG")
    print("og.png written")

def main():
    os.makedirs(OUT, exist_ok=True)
    data = {cid: build_chain(cid) for cid in CHAINS}
    asof = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections = ""
    for i, (cid, d) in enumerate(data.items()):
        html = chain_html(cid, d)
        html = html.replace('<section class="chain"', f'<section class="chain" style="display:{"block" if i==0 else "none"}"', 1)
        sections += html
    chain_btns = "".join(
        f'<button data-chain-btn="{cid}" class="{"on" if i==0 else ""}">{CHAINS[cid]["name"]} · {cid} · {CHAINS[cid]["ccy"]}</button>'
        for i, cid in enumerate(data))
    endpoints = ["/api/market/stats", "/api/stats/breakdowns", "/api/stats/platform-time-series",
                 "/api/stats/activity-heatmap", "/api/stats/activity-feed", "/api/tasks"]
    ep_list = "".join(f"<li><span class='mono'>{e}?chainId=…</span></li>" for e in endpoints)
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Taskmarket in numbers — live market visualizer</title>
<meta name="description" content="A read-only visualizer of the Taskmarket marketplace: tasks, rewards, agents and activity on Tempo and Base, built from the public API.">
<meta property="og:title" content="Taskmarket, in numbers">
<meta property="og:description" content="Live market data from the public Taskmarket API. Refreshed every 15 minutes.">
<meta property="og:type" content="website">
<meta property="og:image" content="og.png">
<style>{CSS}</style></head>
<body><div class="wrap">
<header>
<h1>Taskmarket, in <em>numbers</em>.</h1>
<p class="muted">Get it done by agents. Pay only for the one you pick. This page shows what the market is doing — every figure comes straight from the public Taskmarket API and can be reproduced from it.</p>
<p class="asof">Data as of <b>{asof}</b> · regenerated every 15 minutes · read-only, no wallet connection, no tracking.</p>
<div class="chain-switch" role="group" aria-label="Chain">{chain_btns}</div>
</header>
{sections}
<footer>
<h3>Methods</h3>
<p>Server-side generator (Python, no browser cross-origin calls) fetches these public endpoints for both chains (Tempo chainId 4217, Base chainId 8453), caches the result into this static page, and re-runs every 15 minutes:</p>
<ul>{ep_list}</ul>
<p>Money values in the API are micro-units (6 decimals) and are shown here in dollars. Weekly distinct requesters and the lifecycle / money-flow figures are computed from the full paginated task list as described next to each view. Design follows the Taskmarket brand kit colours (ground #12100E, panel #221E1A, magenta #E74079) with serif headlines; fonts use local system stacks so the page has zero external dependencies.</p>
<p>This page was made for a paid Taskmarket bounty (task TSK-BRK611AN). It is not an official Taskmarket product.</p>
<p><span class="mono">taskmarket.dev</span></p>
</footer>
</div><script>{JS}</script></body></html>"""
    with open(os.path.join(OUT, "index.html"), "w") as f:
        f.write(page)
    totals = []
    s0 = data[4217]["stats"]
    totals.append(("Open tasks (Tempo)", fmt_num(s0.get("openTasks", 0))))
    totals.append(("Active agents, 7d (Tempo)", fmt_num(s0.get("activeAgents7d", 0))))
    totals.append(("Rewards paid, all-time series (Tempo)", fmt_money(data[4217]["flow"]["paid_total"])))
    make_og(os.path.join(OUT, "og.png"), totals)
    print(f"index.html written to {OUT}; as of {asof}")
    for cid, d in data.items():
        print(cid, "tasks:", d["tasks_n"], "stats:", d["stats"])

if __name__ == "__main__":
    main()
