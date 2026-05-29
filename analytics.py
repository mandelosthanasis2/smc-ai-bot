"""
analytics.py — Analytics dashboard για SMC AI Bot
Προσθήκη νέας στρατηγικής: μόνο 1 γραμμή στο STRATEGIES dict
"""

from flask import Blueprint, jsonify, render_template_string
from database import get_conn
import json
import warnings
warnings.filterwarnings("ignore", category=SyntaxWarning)

analytics_bp = Blueprint("analytics", __name__)

# ── Config: πρόσθεσε νέα στρατηγική εδώ ──────────────────────────
STRATEGIES = {
    "A":  {"name": "Strategy A",  "color": "#3b82f6", "desc": "Daily Box + 1H RSI"},
    "B":  {"name": "Strategy B",  "color": "#8b5cf6", "desc": "1H Box + 15m RSI"},
    "C":  {"name": "Strategy C",  "color": "#f97316", "desc": "TV Webhook + 1H Box"},
    "CM": {"name": "Check Mark",  "color": "#14b8a6", "desc": "Check Mark Pattern"},
    "SMC": {"name": "Strategy SMC", "color": "#f5c518", "desc": "OB + FVG + CHoCH"},
}

# =================================================================
# DATA HELPERS
# =================================================================

def get_trades(strategy: str) -> list:
    conn = get_conn()
    if not conn:
        return []
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT type, entry, close, pnl, result, note,
                       divergence, news_score, trade_time as time, id,
                       ai_action, ai_confidence, ai_reasoning, ai_shadow_mode
                FROM trades
                WHERE strategy = %s
                ORDER BY id ASC
            """, (strategy,))
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        return []
    finally:
        conn.close()

def get_state(strategy: str) -> dict:
    conn = get_conn()
    if not conn:
        return {}
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM bot_state WHERE strategy = %s", (strategy,))
            row = cur.fetchone()
            return dict(row) if row else {}
    except Exception:
        return {}
    finally:
        conn.close()

def calc_stats(trades: list, initial_balance: float = 10000.0) -> dict:
    if not trades:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "total_pnl": 0, "avg_win": 0, "avg_loss": 0,
            "profit_factor": 0, "max_drawdown": 0,
            "best_trade": 0, "worst_trade": 0,
            "equity_curve": [], "pnl_by_hour": {}, "pnl_by_day": {},
            "top_hours": [], "bottom_hours": [], "best_days": [], "worst_days": [],
            "consecutive_wins": 0, "consecutive_losses": 0,
            "sharpe_ratio": 0, "expectancy": 0, "recovery_factor": 0, "max_drawdown_usd": 0,
            "ai_stats": {"total_ai_trades":0,"skips":0,"skip_accuracy":0,"doubles":0,
                         "double_accuracy":0,"reduces":0,"goes":0,"saved_pnl":0,
                         "shadow_trades":0,"active_trades":0,"skip_correct":0},
        }

    wins   = [t for t in trades if t["result"] == "WIN" and float(t["pnl"] or 0) > 0]
    losses = [t for t in trades if t["result"] == "LOSS"]
    total  = len(trades)

    pnls = [float(t["pnl"] or 0) for t in trades]
    win_pnls  = [p for p in pnls if p > 0]
    loss_pnls = [p for p in pnls if p < 0]

    avg_win  = round(sum(win_pnls)  / len(win_pnls),  2) if win_pnls  else 0
    avg_loss = round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0

    gross_profit = sum(win_pnls)
    gross_loss   = abs(sum(loss_pnls))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0

    # Equity curve
    balance = initial_balance
    equity_curve = [{"trade": 0, "balance": balance, "time": "Start"}]
    peak = balance
    max_dd = 0
    for i, t in enumerate(trades):
        balance = round(balance + float(t["pnl"] or 0), 2)
        equity_curve.append({
            "trade": i + 1,
            "balance": balance,
            "time": str(t["time"] or "")[:16],
            "pnl": float(t["pnl"] or 0),
            "result": t["result"],
        })
        if balance > peak:
            peak = balance
        dd = round((peak - balance) / peak * 100, 2) if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # PnL + Win rate ανά ώρα
    DAY_NAMES = ["Δευτέρα","Τρίτη","Τετάρτη","Πέμπτη","Παρασκευή","Σάββατο","Κυριακή"]
    pnl_by_hour = {str(h): {"pnl": 0, "trades": 0, "wins": 0, "win_rate": 0} for h in range(24)}
    pnl_by_day  = {str(d): {"pnl": 0, "trades": 0, "wins": 0, "win_rate": 0, "name": DAY_NAMES[d]} for d in range(7)}

    for t in trades:
        try:
            time_str = str(t["time"] or "")
            if len(time_str) >= 13:
                hour = str(int(time_str[11:13]))
            else:
                hour = "0"
            pnl_by_hour[hour]["pnl"]    = round(pnl_by_hour[hour]["pnl"] + float(t["pnl"] or 0), 2)
            pnl_by_hour[hour]["trades"] += 1
            if t["result"] == "WIN":
                pnl_by_hour[hour]["wins"] += 1

            # Day of week από trade_time string "YYYY-MM-DD HH:MM"
            if len(time_str) >= 10:
                from datetime import datetime
                try:
                    dt  = datetime.strptime(time_str[:10], "%Y-%m-%d")
                    dow = str(dt.weekday())  # 0=Monday
                    pnl_by_day[dow]["pnl"]    = round(pnl_by_day[dow]["pnl"] + float(t["pnl"] or 0), 2)
                    pnl_by_day[dow]["trades"] += 1
                    if t["result"] == "WIN":
                        pnl_by_day[dow]["wins"] += 1
                except Exception:
                    pass
        except Exception:
            pass

    # Υπολογισμός win rates
    for h in pnl_by_hour:
        tr = pnl_by_hour[h]["trades"]
        pnl_by_hour[h]["win_rate"] = round(pnl_by_hour[h]["wins"] / tr * 100, 1) if tr > 0 else 0

    for d in pnl_by_day:
        tr = pnl_by_day[d]["trades"]
        pnl_by_day[d]["win_rate"] = round(pnl_by_day[d]["wins"] / tr * 100, 1) if tr > 0 else 0

    # Top/Bottom windows (min 2 trades για να μετράει)
    hour_wr = [(h, pnl_by_hour[h]) for h in pnl_by_hour if pnl_by_hour[h]["trades"] >= 2]
    hour_wr.sort(key=lambda x: x[1]["win_rate"], reverse=True)
    top_hours    = hour_wr[:3]
    bottom_hours = hour_wr[-3:][::-1] if len(hour_wr) >= 3 else []

    day_wr = [(d, pnl_by_day[d]) for d in pnl_by_day if pnl_by_day[d]["trades"] >= 1]
    day_wr.sort(key=lambda x: x[1]["win_rate"], reverse=True)
    best_days  = day_wr[:2]
    worst_days = day_wr[-2:][::-1] if len(day_wr) >= 2 else []

    # ── Sharpe Ratio (annualized, risk-free=0) ──────────────────
    import math
    daily_returns = []
    running = initial_balance
    for t in trades:
        pnl = float(t["pnl"] or 0)
        ret = pnl / running if running > 0 else 0
        daily_returns.append(ret)
        running += pnl

    sharpe = 0.0
    if len(daily_returns) >= 5:
        avg_r = sum(daily_returns) / len(daily_returns)
        std_r = math.sqrt(sum((r - avg_r)**2 for r in daily_returns) / len(daily_returns))
        if std_r > 0:
            sharpe = round(avg_r / std_r * math.sqrt(252), 2)

    # ── Expectancy ────────────────────────────────────────────
    win_rate_dec = len([t for t in trades if t["result"] == "WIN"]) / total if total else 0
    expectancy   = round(win_rate_dec * avg_win + (1 - win_rate_dec) * avg_loss, 2)

    # ── Recovery Factor ───────────────────────────────────────
    recovery_factor = round(sum(pnls) / max_dd_abs, 2) if (max_dd_abs := max(
        (initial_balance + sum([float(t["pnl"] or 0) for t in trades[:i+1]]) - peak
         for i, t in enumerate(trades)
         for peak in [max(initial_balance + sum([float(t2["pnl"] or 0) for t2 in trades[:j+1]])
                         for j in range(i+1))]
    ), default=0) if (lambda: True)() else 1) > 0 else 0

    # Απλούστερος υπολογισμός recovery factor
    net_profit  = sum(pnls)
    max_dd_usd  = round(max_dd / 100 * initial_balance, 2)
    recovery_factor = round(net_profit / max_dd_usd, 2) if max_dd_usd > 0 else 0

    # ── AI Performance Stats ──────────────────────────────────
    ai_trades    = [t for t in trades if t.get("ai_action")]
    ai_skips     = [t for t in ai_trades if t.get("ai_action") == "SKIP"]
    ai_doubles   = [t for t in ai_trades if t.get("ai_action") == "DOUBLE_SIZE"]
    ai_reduces   = [t for t in ai_trades if t.get("ai_action") == "REDUCE_SIZE"]
    ai_goes      = [t for t in ai_trades if t.get("ai_action") == "GO"]

    # SKIP accuracy: πόσα από τα "SKIP" ήταν όντως losses
    skip_correct = len([t for t in ai_skips if t["result"] == "LOSS"])
    skip_accuracy = round(skip_correct / len(ai_skips) * 100, 1) if ai_skips else 0

    # DOUBLE accuracy: πόσα από τα "DOUBLE_SIZE" ήταν wins
    double_correct  = len([t for t in ai_doubles if t["result"] == "WIN"])
    double_accuracy = round(double_correct / len(ai_doubles) * 100, 1) if ai_doubles else 0

    # Saved PnL: πόσο θα χάναμε αν δεν ακούγαμε τα SKIP
    saved_pnl = round(sum(float(t["pnl"] or 0) for t in ai_skips if t["result"] == "LOSS"), 2)

    # AI vs No-AI comparison
    ai_trade_pnls    = [float(t["pnl"] or 0) for t in ai_trades]
    no_ai_trade_pnls = [float(t["pnl"] or 0) for t in trades if not t.get("ai_action")]
    ai_wins    = [t for t in ai_trades if t["result"] == "WIN"]
    no_ai_wins = [t for t in trades if not t.get("ai_action") and t["result"] == "WIN"]

    ai_wr    = round(len(ai_wins)    / len(ai_trades)               * 100, 1) if ai_trades        else 0
    no_ai_wr = round(len(no_ai_wins) / len([t for t in trades if not t.get("ai_action")]) * 100, 1)                if [t for t in trades if not t.get("ai_action")] else 0

    ai_avg_pnl    = round(sum(ai_trade_pnls)    / len(ai_trade_pnls),    2) if ai_trade_pnls    else 0
    no_ai_avg_pnl = round(sum(no_ai_trade_pnls) / len(no_ai_trade_pnls), 2) if no_ai_trade_pnls else 0

    # Shadow decision table — ανά trade
    shadow_decisions = []
    for t in ai_trades:
        action = t.get("ai_action", "")
        pnl    = float(t.get("pnl") or 0)
        result = t.get("result", "")
        correct = (
            (action == "SKIP"        and result == "LOSS") or
            (action == "GO"          and result == "WIN")  or
            (action == "DOUBLE_SIZE" and result == "WIN")  or
            (action == "REDUCE_SIZE" and result != "LOSS")
        )
        # Simulated PnL για κάθε απόφαση:
        # SKIP → τι χάθηκε/κερδίστηκε που θα αποφεύγαμε
        # DOUBLE → πραγματικό PnL * 2x
        # REDUCE → πραγματικό PnL * 0.5x
        # GO → ίδιο με το πραγματικό
        if action == "SKIP":
            sim_pnl_trade = 0.0           # δεν εκτελείται
            sim_label = "—"               # δεν μπαίνει θέση
        elif action == "DOUBLE_SIZE":
            sim_pnl_trade = round(pnl * 2, 2)
            sim_label = f"{'+'if pnl*2>=0 else ''}${pnl*2:.0f}"
        elif action == "REDUCE_SIZE":
            sim_pnl_trade = round(pnl * 0.5, 2)
            sim_label = f"{'+'if pnl*0.5>=0 else ''}${pnl*0.5:.0f}"
        else:  # GO
            sim_pnl_trade = round(pnl, 2)
            sim_label = f"{'+'if pnl>=0 else ''}${pnl:.0f}"

        shadow_decisions.append({
            "time":          str(t.get("time") or "")[:16],
            "type":          t.get("type", ""),
            "action":        action,
            "result":        result,
            "pnl":           round(pnl, 2),           # πραγματικό PnL
            "sim_pnl":       sim_pnl_trade,            # PnL αν εφαρμοζόταν η AI απόφαση
            "sim_label":     sim_label,
            "conf":          round(float(t.get("ai_confidence") or 0) * 100),
            "correct":       correct,
            "note":          str(t.get("note") or ""),
        })

    # Simulated PnL: τι θα γινόταν αν ο validator ήταν active (SKIP = δεν εκτελείται)
    sim_pnl  = round(sum(float(t.get("pnl") or 0) for t in ai_trades if t.get("ai_action") != "SKIP"), 2)
    real_pnl_ai = round(sum(float(t.get("pnl") or 0) for t in ai_trades), 2)
    sim_diff = round(sim_pnl - real_pnl_ai, 2)  # θετικό = ο validator θα βελτίωνε

    ai_stats = {
        "total_ai_trades":  len(ai_trades),
        "skips":            len(ai_skips),
        "skip_accuracy":    skip_accuracy,
        "skip_correct":     skip_correct,
        "doubles":          len(ai_doubles),
        "double_accuracy":  double_accuracy,
        "reduces":          len(ai_reduces),
        "goes":             len(ai_goes),
        "saved_pnl":        saved_pnl,
        "shadow_trades":    len([t for t in ai_trades if t.get("ai_shadow_mode")]),
        "active_trades":    len([t for t in ai_trades if not t.get("ai_shadow_mode")]),
        "shadow_decisions": shadow_decisions,
        "sim_diff":         sim_diff,
        "ai_win_rate":      ai_wr,
        "no_ai_win_rate":   no_ai_wr,
        "ai_avg_pnl":       ai_avg_pnl,
        "no_ai_avg_pnl":    no_ai_avg_pnl,
        "ai_trade_count":   len(ai_trades),
        "no_ai_trade_count": len([t for t in trades if not t.get("ai_action")]),
    }

    # ── Consecutive wins/losses
    max_cw = max_cl = cw = cl = 0
    for t in trades:
        if t["result"] == "WIN":
            cw += 1; cl = 0
            max_cw = max(max_cw, cw)
        else:
            cl += 1; cw = 0
            max_cl = max(max_cl, cl)

    return {
        "total_trades":        total,
        "wins":                len([t for t in trades if t["result"] == "WIN"]),
        "losses":              len(losses),
        "win_rate":            round(len([t for t in trades if t["result"] == "WIN"]) / total * 100, 1) if total else 0,
        "total_pnl":           round(sum(pnls), 2),
        "avg_win":             avg_win,
        "avg_loss":            avg_loss,
        "profit_factor":       profit_factor,
        "max_drawdown":        round(max_dd, 2),
        "best_trade":          round(max(pnls), 2) if pnls else 0,
        "worst_trade":         round(min(pnls), 2) if pnls else 0,
        "equity_curve":        equity_curve,
        "pnl_by_hour":         pnl_by_hour,
        "pnl_by_day":          pnl_by_day,
        "top_hours":           top_hours,
        "bottom_hours":        bottom_hours,
        "best_days":           best_days,
        "worst_days":          worst_days,
        "consecutive_wins":    max_cw,
        "consecutive_losses":  max_cl,
        "gross_profit":        round(gross_profit, 2),
        "gross_loss":          round(gross_loss, 2),
        "sharpe_ratio":        sharpe,
        "expectancy":          expectancy,
        "recovery_factor":     recovery_factor,
        "max_drawdown_usd":    max_dd_usd,
        "ai_stats":            ai_stats,
    }

# =================================================================
# API ENDPOINTS
# =================================================================

@analytics_bp.route("/api/analytics/<strategy>")
def api_analytics_strategy(strategy):
    strategy = strategy.upper()
    if strategy not in STRATEGIES:
        return jsonify({"error": "Unknown strategy"}), 404
    trades = get_trades(strategy)
    state  = get_state(strategy)
    stats  = calc_stats(trades, 10000.0)
    return jsonify({
        "strategy": strategy,
        "meta":     STRATEGIES[strategy],
        "state":    {k: float(v) if hasattr(v, '__float__') else v for k, v in state.items() if k != "position"},
        "stats":    stats,
        "trades":   trades,
    })

@analytics_bp.route("/api/analytics")
def api_analytics_all():
    result = {}
    for s in STRATEGIES:
        trades = get_trades(s)
        state  = get_state(s)
        stats  = calc_stats(trades, 10000.0)
        result[s] = {
            "meta":   STRATEGIES[s],
            "state":  {k: float(v) if hasattr(v, '__float__') else v for k, v in state.items() if k != "position"},
            "stats":  stats,
        }
    return jsonify(result)

# =================================================================
# ANALYTICS DASHBOARD HTML
# =================================================================

ANALYTICS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMC AI Bot — Analytics</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Syne:wght@400;600;700;800&display=swap');

*{box-sizing:border-box;margin:0;padding:0;}
:root{
  --bg:#060810;--bg2:#0c1020;--bg3:#111828;--bg4:#161e30;
  --border:#1a2540;--border2:#243050;
  --text:#e8edf8;--text2:#8892a8;--text3:#3d4f6e;
  --a:#3b82f6;--b:#8b5cf6;--c:#f97316;
  --green:#10b981;--red:#ef4444;--yellow:#f59e0b;
}
html,body{background:var(--bg);color:var(--text);font-family:'JetBrains Mono',monospace;min-height:100vh;}

/* NAV */
.nav{
  display:flex;align-items:center;gap:0;
  padding:0 24px;height:52px;
  background:var(--bg2);border-bottom:1px solid var(--border);
  position:sticky;top:0;z-index:100;
}
.nav-logo{font-family:'Syne',sans-serif;font-size:14px;font-weight:800;letter-spacing:2px;color:var(--text);margin-right:24px;}
.nav-logo span{color:var(--a);}
.nav-links{display:flex;gap:2px;margin-right:auto;}
.nav-link{
  font-size:10px;font-weight:500;padding:5px 12px;border-radius:5px;
  text-decoration:none;color:var(--text2);letter-spacing:1px;text-transform:uppercase;
  transition:all 0.15s;border:1px solid transparent;
}
.nav-link:hover{color:var(--text);background:var(--bg3);}
.nav-link.active-a{color:var(--a);background:rgba(59,130,246,0.1);border-color:rgba(59,130,246,0.2);}
.nav-link.active-b{color:var(--b);background:rgba(139,92,246,0.1);border-color:rgba(139,92,246,0.2);}
.nav-link.active-c{color:var(--c);background:rgba(249,115,22,0.1);border-color:rgba(249,115,22,0.2);}
.nav-right{display:flex;gap:8px;align-items:center;}
.nav-btn{
  font-size:10px;font-weight:600;padding:5px 14px;border-radius:5px;
  text-decoration:none;letter-spacing:0.5px;border:1px solid var(--border);
  color:var(--text2);transition:all 0.15s;
}
.nav-btn:hover{color:var(--text);border-color:var(--border2);}

/* TABS */
.tabs{
  display:flex;gap:2px;padding:20px 24px 0;
  border-bottom:1px solid var(--border);background:var(--bg2);
}
.tab{
  font-size:11px;font-weight:600;padding:8px 20px;
  border-radius:6px 6px 0 0;cursor:pointer;
  border:1px solid transparent;border-bottom:none;
  color:var(--text2);letter-spacing:0.5px;transition:all 0.15s;
  background:transparent;
}
.tab:hover{color:var(--text);}
.tab.active{
  color:var(--text);background:var(--bg);
  border-color:var(--border);border-bottom-color:var(--bg);
  margin-bottom:-1px;
}
.tab[data-tab="A"].active{color:var(--a);}
.tab[data-tab="B"].active{color:var(--b);}
.tab[data-tab="C"].active{color:var(--c);}
.tab[data-tab="SMC"].active{color:#f5c518;}
.tab[data-tab="compare"].active{color:var(--yellow);}

/* CONTENT */
.content{display:none;padding:24px;max-width:1400px;margin:0 auto;}
.content.active{display:block;}

/* STATS ROW */
.stats-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px;}
.stat-card{
  background:var(--bg3);border:1px solid var(--border);border-radius:10px;
  padding:14px 16px;position:relative;overflow:hidden;
}
.stat-card::before{
  content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:var(--accent,var(--a));opacity:0.6;
}
.stat-label{font-size:9px;color:var(--text3);text-transform:uppercase;letter-spacing:1.5px;margin-bottom:6px;}
.stat-value{font-size:22px;font-weight:700;letter-spacing:-0.5px;}
.stat-sub{font-size:9px;color:var(--text2);margin-top:3px;}

/* GRID 2 COL */
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:16px;}
@media(max-width:900px){.grid-2,.grid-3{grid-template-columns:1fr;}}

/* CHART CARD */
.chart-card{
  background:var(--bg3);border:1px solid var(--border);border-radius:12px;
  padding:20px;
}
.chart-title{
  font-family:'Syne',sans-serif;font-size:11px;font-weight:700;
  color:var(--text2);text-transform:uppercase;letter-spacing:2px;margin-bottom:16px;
  display:flex;align-items:center;gap:8px;
}
.chart-title span{width:6px;height:6px;border-radius:50%;background:var(--accent,var(--a));display:inline-block;}
.chart-wrap{position:relative;height:220px;}
.chart-wrap.tall{height:300px;}

/* TRADE TABLE */
.trade-table{width:100%;border-collapse:collapse;font-size:11px;}
.trade-table th{
  color:var(--text3);text-align:left;padding:8px 10px;
  border-bottom:1px solid var(--border);font-weight:500;
  text-transform:uppercase;letter-spacing:1px;font-size:9px;
}
.trade-table td{padding:7px 10px;border-bottom:1px solid rgba(26,37,64,0.5);}
.trade-table tr:hover td{background:rgba(255,255,255,0.02);}
.pill{display:inline-block;padding:2px 8px;border-radius:4px;font-size:9px;font-weight:700;letter-spacing:0.5px;}
.pill-long  {background:rgba(16,185,129,0.12);color:var(--green);}
.pill-short {background:rgba(239,68,68,0.12); color:var(--red);}
.pill-win   {background:rgba(16,185,129,0.12);color:var(--green);}
.pill-loss  {background:rgba(239,68,68,0.12); color:var(--red);}
.text-green{color:var(--green);}
.text-red{color:var(--red);}
.text-dim{color:var(--text3);}
.text-yellow{color:var(--yellow);}

/* HOUR HEATMAP */
.heatmap{display:grid;grid-template-columns:repeat(12,1fr);gap:4px;}
.heatmap-cell{
  aspect-ratio:1;border-radius:4px;cursor:pointer;
  position:relative;transition:transform 0.15s;
  display:flex;align-items:center;justify-content:center;
  font-size:8px;font-weight:600;color:rgba(255,255,255,0.5);
}
.heatmap-cell:hover{transform:scale(1.1);z-index:10;}
.heatmap-label{font-size:8px;color:var(--text3);text-align:center;margin-top:6px;}

/* COMPARE TABLE */
.compare-table{width:100%;border-collapse:collapse;font-size:12px;}
.compare-table th{
  color:var(--text3);text-align:left;padding:10px 14px;
  border-bottom:1px solid var(--border);font-size:9px;
  text-transform:uppercase;letter-spacing:1px;
}
.compare-table td{padding:10px 14px;border-bottom:1px solid rgba(26,37,64,0.5);}
.compare-table tr:hover td{background:rgba(255,255,255,0.02);}
.strategy-badge{
  display:inline-flex;align-items:center;gap:6px;
  font-size:11px;font-weight:700;
}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;}

/* LOADING */
.loading{
  display:flex;align-items:center;justify-content:center;
  height:200px;color:var(--text3);font-size:12px;letter-spacing:2px;
}

/* SCROLLABLE TABLE */
.table-wrap{max-height:360px;overflow-y:auto;}
.table-wrap::-webkit-scrollbar{width:4px;}
.table-wrap::-webkit-scrollbar-track{background:transparent;}
.table-wrap::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px;}
</style>
</head>
<body>

<nav class="nav">
  <div class="nav-logo">SMC <span>AI</span></div>
  <div class="nav-links">
    <a href="/" class="nav-link">Dashboard A</a>
    <a href="/b" class="nav-link">Dashboard B</a>
    <a href="/c" class="nav-link">Dashboard C</a>
    <a href="/cm" class="nav-link">Check Mark</a>
    <a href="/smc" class="nav-link">SMC</a>
  </div>
  <div class="nav-right">
    <span style="font-size:10px;color:var(--text3);letter-spacing:1px;">ANALYTICS</span>
  </div>
</nav>

<div class="tabs">
  <button class="tab active" data-tab="A" onclick="switchTab('A')">Strategy A</button>
  <button class="tab" data-tab="B" onclick="switchTab('B')">Strategy B</button>
  <button class="tab" data-tab="C" onclick="switchTab('C')">Strategy C</button>
  <button class="tab" data-tab="CM" onclick="switchTab('CM')">Check Mark</button>
  <button class="tab" data-tab="SMC" onclick="switchTab('SMC')">SMC</button>
  <button class="tab" data-tab="compare" onclick="switchTab('compare')">⚡ Compare</button>
  <button class="tab" data-tab="timing" onclick="switchTab('timing')">⏱ Timing</button>
</div>

<!-- STRATEGY A -->
<div class="content active" id="tab-A">
  <div class="loading" id="loading-A">Loading Strategy A...</div>
  <div id="data-A" style="display:none;"></div>
</div>

<!-- STRATEGY B -->
<div class="content" id="tab-B">
  <div class="loading" id="loading-B">Loading Strategy B...</div>
  <div id="data-B" style="display:none;"></div>
</div>

<!-- STRATEGY C -->
<div class="content" id="tab-C">
  <div class="loading" id="loading-C">Loading Strategy C...</div>
  <div id="data-C" style="display:none;"></div>
</div>

<!-- CHECK MARK -->
<div class="content" id="tab-CM">
  <div class="loading" id="loading-CM">Loading Check Mark...</div>
  <div id="data-CM" style="display:none;"></div>
</div>

<!-- SMC -->
<div class="content" id="tab-SMC">
  <div class="loading" id="loading-SMC">Loading SMC...</div>
  <div id="data-SMC" style="display:none;"></div>
</div>

<!-- COMPARE -->
<div class="content" id="tab-compare">
  <div class="loading" id="loading-compare">Loading comparison...</div>
  <div id="data-compare" style="display:none;"></div>
</div>

<!-- TIMING -->
<div class="content" id="tab-timing">
  <div id="data-timing" style="padding:24px;">
    <div style="display:flex;align-items:center;justify-content:center;height:200px;color:#3d4f6e;font-size:12px;letter-spacing:2px;">
      LOADING TIMING DATA...
    </div>
  </div>
</div>

<script>
const COLORS = { A: '#3b82f6', B: '#8b5cf6', C: '#f97316' };
const NAMES  = { A: 'Strategy A', B: 'Strategy B', C: 'Strategy C' };
const loaded = {};
let charts   = {};

function fmt(n, dec=2) {
  const v = parseFloat(n) || 0;
  return (v >= 0 ? '+' : '') + '$' + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits:dec, maximumFractionDigits:dec});
}
function fmtAbs(n, dec=2) {
  return '$' + (parseFloat(n)||0).toLocaleString('en-US', {minimumFractionDigits:dec, maximumFractionDigits:dec});
}

// ── TAB SWITCH ──────────────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.content').forEach(c => c.classList.remove('active'));
  document.querySelector(`.tab[data-tab="${tab}"]`).classList.add('active');
  document.getElementById(`tab-${tab}`).classList.add('active');
  if (tab === 'timing') { loadTiming(); return; }
  if (!loaded[tab]) loadTab(tab);
}

function loadTab(tab) {
  if (tab === 'compare') {
    loadCompare();
  } else {
    loadStrategy(tab);
  }
}

// ── STRATEGY TAB ────────────────────────────────────────────────
function loadStrategy(s) {
  fetch(`/api/analytics/${s}`)
    .then(r => r.json())
    .then(d => {
      renderStrategy(s, d);
      loaded[s] = true;
    })
    .catch(() => {
      document.getElementById(`loading-${s}`).textContent = 'Error loading data';
    });
}

function renderStrategy(s, d) {
  const color  = COLORS[s];
  const stats  = d.stats;
  const trades = d.trades || [];
  document.getElementById(`loading-${s}`).style.display = 'none';
  const el = document.getElementById(`data-${s}`);
  el.style.display = 'block';
  el.innerHTML = `
    <!-- STATS ROW -->
    <div class="stats-row" style="--accent:${color}">
      ${statCard('Balance', fmtAbs(d.state?.balance || 10000, 0), color)}
      ${statCard('Total P&L', fmt(stats.total_pnl), stats.total_pnl >= 0 ? 'var(--green)' : 'var(--red)')}
      ${statCard('Win Rate', stats.win_rate + '%', color, stats.wins + 'W / ' + stats.losses + 'L')}
      ${statCard('Trades', stats.total_trades, color)}
      ${statCard('Avg Win', fmt(stats.avg_win), 'var(--green)')}
      ${statCard('Avg Loss', fmt(stats.avg_loss), 'var(--red)')}
      ${statCard('Profit Factor', stats.profit_factor + 'x', stats.profit_factor >= 1.5 ? 'var(--green)' : 'var(--yellow)')}
      ${statCard('Max Drawdown', '-' + stats.max_drawdown + '%', stats.max_drawdown < 10 ? 'var(--green)' : 'var(--red)')}
      ${statCard('Best Trade', fmt(stats.best_trade), 'var(--green)')}
      ${statCard('Worst Trade', fmt(stats.worst_trade), 'var(--red)')}
      ${statCard('Max Cons. Wins', stats.consecutive_wins, color)}
      ${statCard('Max Cons. Loss', stats.consecutive_losses, 'var(--red)')}
      ${statCard('Sharpe Ratio', (stats.sharpe_ratio||0).toFixed(2), (stats.sharpe_ratio||0)>=2?'var(--green)':(stats.sharpe_ratio||0)>=1?'var(--yellow)':'var(--red)', '>2=great >1=good')}
      ${statCard('Expectancy', fmt(stats.expectancy||0), (stats.expectancy||0)>=0?'var(--green)':'var(--red)', 'avg $ per trade')}
      ${statCard('Recovery', (stats.recovery_factor||0).toFixed(2), (stats.recovery_factor||0)>=2?'var(--green)':'var(--yellow)', 'profit/max drawdown')}
    </div>

    <!-- AI VALIDATOR SECTION -->
    ${(() => {
      const ai = stats.ai_stats || {};
      if (!ai.total_ai_trades) return `
        <div style="background:rgba(59,130,246,0.05);border:1px solid rgba(59,130,246,0.15);border-radius:10px;padding:16px;margin-bottom:16px;">
          <div style="font-size:11px;font-weight:600;color:var(--a);letter-spacing:1px;margin-bottom:8px;">AI VALIDATOR</div>
          <div style="font-size:12px;color:var(--text2);">Shadow mode ενεργό — δεν υπάρχουν ακόμα trades με AI commentary.</div>
        </div>`;
      const skipColor = ai.skip_accuracy>=60?'var(--green)':ai.skip_accuracy>=40?'var(--yellow)':'var(--red)';
      const dblColor  = ai.double_accuracy>=60?'var(--green)':'var(--yellow)';
      const rec = ai.skip_accuracy>=60
        ? `<div style="margin-top:10px;font-size:11px;color:#4ade80;background:rgba(74,222,128,0.05);padding:8px 12px;border-radius:6px;">✅ SKIP accuracy ${ai.skip_accuracy}% — Μπορείς να απενεργοποιήσεις το shadow mode</div>`
        : ai.skips>=5
          ? `<div style="margin-top:10px;font-size:11px;color:#f59e0b;background:rgba(245,158,11,0.05);padding:8px 12px;border-radius:6px;">⚠️ SKIP accuracy ${ai.skip_accuracy}% — Συνέχισε σε shadow mode, χρειάζεται βελτίωση</div>`
          : `<div style="margin-top:10px;font-size:11px;color:var(--text2);">📊 Χρειάζονται 5+ SKIP decisions για αξιόπιστη μέτρηση (τώρα: ${ai.skips})</div>`;
      return `
        <div style="background:rgba(59,130,246,0.05);border:1px solid rgba(59,130,246,0.15);border-radius:10px;padding:16px;margin-bottom:16px;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">
            <div style="font-size:11px;font-weight:600;color:var(--a);letter-spacing:1px;">AI VALIDATOR — ${ai.shadow_trades} SHADOW · ${ai.active_trades} ACTIVE</div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;">
            ${statCard('AI Trades', ai.total_ai_trades, 'var(--a)')}
            ${statCard('SKIP Accuracy', (ai.skip_accuracy||0)+'%', skipColor, ai.skips+' skips · '+ai.skip_correct+' correct')}
            ${statCard('DOUBLE Acc.', (ai.double_accuracy||0)+'%', dblColor, ai.doubles+' doubles')}
            ${statCard('Saved Loss', fmt(ai.saved_pnl||0), 'var(--green)', 'από SKIP decisions')}
            ${statCard('GO', ai.goes||0, 'var(--green)')}
            ${statCard('REDUCE', ai.reduces||0, 'var(--yellow)')}
          </div>
          ${rec}

          <!-- Shadow Decision Table -->
          ${(() => {
            const decisions = ai.shadow_decisions || [];
            if (!decisions.length) return '';
            const correct = decisions.filter(d => d.correct).length;
            const accuracy = Math.round(correct / decisions.length * 100);
            const simDiff = ai.sim_diff || 0;
            const simColor = simDiff >= 0 ? 'var(--green)' : 'var(--red)';
            const simSign  = simDiff >= 0 ? '+' : '';

            const rows = decisions.map(d => {
              const actionColors = {GO:'#10b981',SKIP:'#ef4444',REDUCE_SIZE:'#f59e0b',DOUBLE_SIZE:'#3b82f6'};
              const actionIcons  = {GO:'✅',SKIP:'🚫',REDUCE_SIZE:'📉',DOUBLE_SIZE:'🚀'};
              const actionLabel  = {GO:'GO',SKIP:'SKIP',REDUCE_SIZE:'½x',DOUBLE_SIZE:'2x'};
              const resultColor  = d.result==='WIN'?'#10b981':d.result==='LOSS'?'#ef4444':'#f59e0b';
              const pnlColor     = d.pnl>=0?'#10b981':'#ef4444';
              const simColor2    = d.sim_pnl>d.pnl?'#10b981':d.sim_pnl<d.pnl?'#ef4444':'var(--text3)';
              const correctIcon  = d.correct?'✅':'❌';
              // Φόντο: SKIP+LOSS=σωστό(πράσινο), SKIP+WIN=λάθος(κόκκινο)
              // DOUBLE+WIN=σωστό, DOUBLE+LOSS=λάθος, REDUCE+LOSS=σωστό
              const rowBg =
                (d.action==='SKIP'   && d.result==='LOSS') ? 'rgba(74,222,128,0.05)' :
                (d.action==='SKIP'   && d.result==='WIN')  ? 'rgba(239,68,68,0.07)'  :
                (d.action==='DOUBLE_SIZE' && d.result==='WIN')  ? 'rgba(59,130,246,0.07)' :
                (d.action==='REDUCE_SIZE' && d.result==='LOSS') ? 'rgba(74,222,128,0.05)' : '';
              // sim_pnl label
              const simLabel = d.action==='SKIP' ? '<span style="color:var(--text3);font-size:9px">— (skip)</span>'
                : `<span style="color:${simColor2};font-size:10px">${d.sim_pnl>=0?'+':''}$${Math.abs(d.sim_pnl).toFixed(0)}</span>`;
              // diff label
              const diff = d.sim_pnl - d.pnl;
              const diffLabel = d.action==='SKIP'
                ? `<span style="color:${d.pnl<0?'#10b981':'#ef4444'};font-size:9px">${d.pnl<0?'saved $'+Math.abs(d.pnl).toFixed(0):'missed $'+Math.abs(d.pnl).toFixed(0)}</span>`
                : diff===0 ? '' : `<span style="color:${diff>0?'#10b981':'#ef4444'};font-size:9px">${diff>0?'+':''}$${Math.abs(diff).toFixed(0)}</span>`;
              return `<tr style="background:${rowBg};border-bottom:1px solid rgba(255,255,255,0.04)">
                <td style="padding:5px 8px;font-size:10px;color:var(--text3)">${d.time.slice(5)}</td>
                <td style="padding:5px 8px;font-size:10px;color:${d.type==='LONG'?'#10b981':'#ef4444'}">${d.type}</td>
                <td style="padding:5px 8px">
                  <span style="font-size:10px;color:${actionColors[d.action]||'#fff'};font-weight:600">${actionIcons[d.action]||''} ${actionLabel[d.action]||d.action}</span>
                  <span style="font-size:9px;color:var(--text3);margin-left:4px">${d.conf}%</span>
                </td>
                <td style="padding:5px 8px;font-size:10px;color:${resultColor}">${d.result}</td>
                <td style="padding:5px 8px;font-size:10px;color:${pnlColor};text-align:right">${d.pnl>=0?'+':''}$${Math.abs(d.pnl).toFixed(0)}</td>
                <td style="padding:5px 8px;text-align:right">${simLabel}</td>
                <td style="padding:5px 8px;text-align:right">${diffLabel}</td>
                <td style="padding:5px 8px;text-align:center">${correctIcon}</td>
              </tr>`;
            }).join('');

            return `
            <div style="margin-top:16px">
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                <div style="font-size:11px;font-weight:600;color:var(--text2);letter-spacing:0.5px">
                  📋 SHADOW DECISIONS — ${decisions.length} trades · ${accuracy}% correct
                </div>
                <div style="font-size:11px;font-weight:600;color:${simColor}">
                  Αν Active: ${simSign}$${Math.abs(simDiff).toFixed(2)}
                  <span style="font-size:9px;color:var(--text3);font-weight:400;margin-left:4px">vs πραγματικό</span>
                </div>
              </div>
              <div style="overflow-x:auto;border-radius:8px;border:1px solid rgba(255,255,255,0.06)">
                <table style="width:100%;border-collapse:collapse">
                  <thead>
                    <tr style="background:rgba(255,255,255,0.03)">
                      <th style="padding:6px 8px;font-size:9px;color:var(--text3);text-align:left;font-weight:600">TIME</th>
                      <th style="padding:6px 8px;font-size:9px;color:var(--text3);text-align:left;font-weight:600">TYPE</th>
                      <th style="padding:6px 8px;font-size:9px;color:var(--text3);text-align:left;font-weight:600">AI</th>
                      <th style="padding:6px 8px;font-size:9px;color:var(--text3);text-align:left;font-weight:600">RESULT</th>
                      <th style="padding:6px 8px;font-size:9px;color:var(--text3);text-align:right;font-weight:600">P&L</th>
                      <th style="padding:6px 8px;font-size:9px;color:var(--text3);text-align:right;font-weight:600">ΑΝ ACTIVE</th>
                      <th style="padding:6px 8px;font-size:9px;color:var(--text3);text-align:right;font-weight:600">ΔΙΑΦΟΡΑ</th>
                      <th style="padding:6px 8px;font-size:9px;color:var(--text3);text-align:center;font-weight:600">✓</th>
                    </tr>
                  </thead>
                  <tbody>${rows}</tbody>
                </table>
              </div>
              <div style="margin-top:8px;font-size:9px;color:var(--text3);line-height:1.6">
                🟢 SKIP + LOSS = σωστή απόφαση &nbsp;|&nbsp; 🔴 SKIP + WIN = χαμένη ευκαιρία &nbsp;|&nbsp; 🔵 DOUBLE + WIN = σωστή επιθετική θέση
              </div>
            </div>`;
          })()}

          ${(() => {
            const noAiCount = ai.no_ai_trade_count || 0;
            const aiCount   = ai.ai_trade_count    || 0;
            if (noAiCount < 3 || aiCount < 3) return '<div style="margin-top:10px;font-size:10px;color:var(--text2);">AI vs No-AI: χρειάζονται 3+ trades (AI: ' + aiCount + ', No-AI: ' + noAiCount + ')</div>';
            const aiWR    = (ai.ai_win_rate    ||0).toFixed(1);
            const noAiWR  = (ai.no_ai_win_rate ||0).toFixed(1);
            const aiAvg   = (ai.ai_avg_pnl     ||0).toFixed(1);
            const noAiAvg = (ai.no_ai_avg_pnl  ||0).toFixed(1);
            const wrDiff  = ((ai.ai_win_rate||0)-(ai.no_ai_win_rate||0)).toFixed(1);
            const pnlDiff = ((ai.ai_avg_pnl||0)-(ai.no_ai_avg_pnl||0)).toFixed(1);
            const wc = wrDiff>=0?'var(--green)'  :'var(--red)';
            const pc = pnlDiff>=0?'var(--green)' :'var(--red)';
            return '<div style="margin-top:12px;border-top:1px solid rgba(255,255,255,0.05);padding-top:12px;">'
              + '<div style="font-size:9px;color:var(--text3);letter-spacing:1px;margin-bottom:8px;">🆚 AI vs NO-AI</div>'
              + '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;font-size:10px;">'
              + '<div style="background:rgba(255,255,255,0.03);padding:8px;border-radius:6px;">'           + '<div style="color:var(--text3);font-size:9px;margin-bottom:4px;">WIN RATE</div>'                 + '<div style="color:var(--green);">AI: ' + aiWR + '%</div>'                                         + '<div style="color:var(--text2);">No AI: ' + noAiWR + '%</div>'                                    + '<div style="color:' + wc  + ';font-weight:600;">' + (wrDiff>=0?'+':'')  + wrDiff  + '%</div></div>'
              + '<div style="background:rgba(255,255,255,0.03);padding:8px;border-radius:6px;">'           + '<div style="color:var(--text3);font-size:9px;margin-bottom:4px;">AVG P&L</div>'                   + '<div style="color:var(--green);">AI: $' + aiAvg + '</div>'                                       + '<div style="color:var(--text2);">No AI: $' + noAiAvg + '</div>'                                  + '<div style="color:' + pc  + ';font-weight:600;">' + (pnlDiff>=0?'+':'') + '$' + pnlDiff + '</div></div>'
              + '<div style="background:rgba(255,255,255,0.03);padding:8px;border-radius:6px;">'           + '<div style="color:var(--text3);font-size:9px;margin-bottom:4px;">TRADES</div>'                   + '<div style="color:var(--green);">AI: ' + aiCount + '</div>'                                       + '<div style="color:var(--text2);">No AI: ' + noAiCount + '</div></div>'                          + '</div></div>';
          })()}
        </div>`;
    })()}

    <!-- CHARTS ROW 1 -->
    <div class="grid-2">
      <div class="chart-card">
        <div class="chart-title" style="--accent:${color}"><span></span>Equity Curve</div>
        <div class="chart-wrap tall"><canvas id="equity-${s}"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title" style="--accent:${color}"><span></span>P&L per Trade</div>
        <div class="chart-wrap tall"><canvas id="pnlbar-${s}"></canvas></div>
      </div>
    </div>

    <!-- CHARTS ROW 2 -->
    <div class="grid-2" style="margin-bottom:24px;">
      <div class="chart-card">
        <div class="chart-title" style="--accent:${color}"><span></span>P&L by Hour (UTC)</div>
        <div id="heatmap-${s}"></div>
      </div>
      <div class="chart-card">
        <div class="chart-title" style="--accent:${color}"><span></span>Win Rate by Hour</div>
        <div class="chart-wrap"><canvas id="hourbar-${s}"></canvas></div>
      </div>
    </div>

    <!-- TRADE HISTORY -->
    <div class="chart-card">
      <div class="chart-title" style="--accent:${color}"><span></span>Trade History (${trades.length} trades)</div>
      <div class="table-wrap">
        <table class="trade-table">
          <thead><tr>
            <th>#</th><th>Time</th><th>Type</th><th>Entry</th><th>Close</th>
            <th>P&L</th><th>Result</th><th>Note</th><th>Div</th>
              <th>AI</th>
          </tr></thead>
          <tbody>
            ${[...trades].reverse().slice(0,100).map((t,i) => `
              <tr>
                <td class="text-dim">${trades.length - i}</td>
                <td class="text-dim">${(t.time||'').substring(5,16)}</td>
                <td><span class="pill pill-${(t.type||'').toLowerCase()}">${t.type}</span></td>
                <td>$${parseFloat(t.entry||0).toLocaleString('en-US',{minimumFractionDigits:2})}</td>
                <td>$${parseFloat(t.close||0).toLocaleString('en-US',{minimumFractionDigits:2})}</td>
                <td class="${parseFloat(t.pnl||0)>=0?'text-green':'text-red'}">${fmt(t.pnl,1)}</td>
                <td><span class="pill pill-${(t.result||'').toLowerCase()}">${t.result}</span></td>
                <td class="text-dim" style="font-size:10px;">${t.note||'—'}</td>
                <td>${t.divergence ? '<span class="text-yellow">🔥</span>' : '<span class="text-dim">—</span>'}</td>
                <td>${(() => {
                  const a = t.ai_action;
                  if (!a) return '<span class="text-dim" style="font-size:9px;">—</span>';
                  const colors = {GO:'#10b981',SKIP:'#ef4444',REDUCE_SIZE:'#f59e0b',DOUBLE_SIZE:'#3b82f6'};
                  const icons  = {GO:'✅',SKIP:'🚫',REDUCE_SIZE:'📉',DOUBLE_SIZE:'🚀'};
                  const labels = {GO:'GO',SKIP:'SKIP',REDUCE_SIZE:'½x',DOUBLE_SIZE:'2x'};
                  const col    = colors[a] || '#8892a8';
                  const shadow = t.ai_shadow_mode ? ' title="Shadow mode — non eseguito"' : '';
                  const conf   = t.ai_confidence ? Math.round(t.ai_confidence*100)+'%' : '';
                  const reason = t.ai_reasoning ? t.ai_reasoning.replace(/"/g,'&quot;') : '';
                  const opacity = t.ai_shadow_mode ? '0.6' : '1';
                  return `<span
                    style="cursor:pointer;font-size:9px;font-weight:600;color:${col};opacity:${opacity};white-space:nowrap;"
                    title="${reason}"
                    ${shadow}
                    onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'"
                  >${icons[a]||''} ${labels[a]||a}${conf?' '+conf:''}${t.ai_shadow_mode?' 👁':''}</span>
                  <div style="display:none;position:absolute;z-index:999;max-width:280px;background:#111828;border:1px solid #1a2540;border-radius:8px;padding:10px;font-size:10px;color:#8892a8;line-height:1.5;margin-top:4px;">
                    ${reason || 'No reasoning available'}
                  </div>`;
                })()}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;

  // Equity chart
  const eq = stats.equity_curve;
  drawLine(`equity-${s}`, {
    labels: eq.map(p => p.time || p.trade),
    data:   eq.map(p => p.balance),
    color,
    fill: true,
    label: 'Balance',
  });

  // PnL bar
  drawBars(`pnlbar-${s}`, {
    labels: trades.map((_,i) => i+1),
    data:   trades.map(t => parseFloat(t.pnl||0)),
    colors: trades.map(t => parseFloat(t.pnl||0) >= 0 ? 'rgba(16,185,129,0.7)' : 'rgba(239,68,68,0.7)'),
    label: 'P&L',
  });

  // Heatmap
  renderHeatmap(`heatmap-${s}`, stats.pnl_by_hour, color);

  // Win rate by hour bar
  const hours = Object.keys(stats.pnl_by_hour).sort((a,b)=>parseInt(a)-parseInt(b));
  drawBars(`hourbar-${s}`, {
    labels: hours.map(h => h + 'h'),
    data:   hours.map(h => {
      const hd = stats.pnl_by_hour[h];
      return hd.trades > 0 ? Math.round(hd.wins / hd.trades * 100) : 0;
    }),
    colors: hours.map(h => {
      const hd = stats.pnl_by_hour[h];
      const wr = hd.trades > 0 ? hd.wins / hd.trades : 0;
      return wr >= 0.6 ? 'rgba(16,185,129,0.7)' : wr >= 0.4 ? 'rgba(245,158,11,0.7)' : 'rgba(239,68,68,0.5)';
    }),
    label: 'Win %',
    yMax: 100,
  });
}

// ── COMPARE TAB ─────────────────────────────────────────────────
function loadCompare() {
  fetch('/api/analytics')
    .then(r => r.json())
    .then(d => {
      renderCompare(d);
      loaded['compare'] = true;
    })
    .catch(() => {
      document.getElementById('loading-compare').textContent = 'Error loading data';
    });
}

function renderCompare(d) {
  document.getElementById('loading-compare').style.display = 'none';
  const el = document.getElementById('data-compare');
  el.style.display = 'block';

  const strategies = Object.keys(d);

  el.innerHTML = `
    <!-- COMPARISON TABLE -->
    <div class="chart-card" style="margin-bottom:16px;">
      <div class="chart-title" style="--accent:var(--yellow)"><span style="background:var(--yellow)"></span>Strategy Comparison</div>
      <table class="compare-table">
        <thead><tr>
          <th>Strategy</th><th>Balance</th><th>Total P&L</th>
          <th>Win Rate</th><th>Trades</th><th>Profit Factor</th>
          <th>Avg Win</th><th>Avg Loss</th><th>Max DD</th><th>Best</th><th>Worst</th>
        </tr></thead>
        <tbody>
          ${strategies.map(s => {
            const st = d[s].stats;
            const bal = parseFloat(d[s].state?.balance || 10000);
            const pnl = st.total_pnl;
            return `<tr>
              <td>
                <div class="strategy-badge">
                  <span class="dot" style="background:${COLORS[s]}"></span>
                  <span style="color:${COLORS[s]};font-weight:700;">${d[s].meta.name}</span>
                </div>
                <div style="font-size:9px;color:var(--text3);margin-top:2px;">${d[s].meta.desc}</div>
              </td>
              <td style="font-weight:600;">${fmtAbs(bal,0)}</td>
              <td class="${pnl>=0?'text-green':'text-red'}" style="font-weight:600;">${fmt(pnl)}</td>
              <td style="color:${st.win_rate>=55?'var(--green)':st.win_rate>=45?'var(--yellow)':'var(--red)'}">
                ${st.win_rate}%
                <div style="font-size:9px;color:var(--text3);">${st.wins}W/${st.losses}L</div>
              </td>
              <td>${st.total_trades}</td>
              <td style="color:${st.profit_factor>=1.5?'var(--green)':st.profit_factor>=1?'var(--yellow)':'var(--red)'}">${st.profit_factor}x</td>
              <td class="text-green">${fmt(st.avg_win)}</td>
              <td class="text-red">${fmt(st.avg_loss)}</td>
              <td style="color:${st.max_drawdown<10?'var(--green)':st.max_drawdown<20?'var(--yellow)':'var(--red)'}">${st.max_drawdown}%</td>
              <td class="text-green">${fmt(st.best_trade)}</td>
              <td class="text-red">${fmt(st.worst_trade)}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>

    <!-- EQUITY CURVES -->
    <div class="grid-2" style="margin-bottom:16px;">
      <div class="chart-card">
        <div class="chart-title" style="--accent:var(--yellow)"><span style="background:var(--yellow)"></span>Equity Curves — All Strategies</div>
        <div class="chart-wrap tall"><canvas id="compare-equity"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title" style="--accent:var(--yellow)"><span style="background:var(--yellow)"></span>P&L Distribution</div>
        <div class="chart-wrap tall"><canvas id="compare-pnl"></canvas></div>
      </div>
    </div>

    <!-- WIN RATE + PROFIT FACTOR -->
    <div class="grid-3">
      ${strategies.map(s => `
        <div class="chart-card">
          <div class="chart-title" style="--accent:${COLORS[s]}">
            <span style="background:${COLORS[s]}"></span>${d[s].meta.name} — Hourly P&L
          </div>
          <div id="compare-heatmap-${s}"></div>
        </div>
      `).join('')}
    </div>
  `;

  // Multi-line equity chart
  const ctx = document.getElementById('compare-equity').getContext('2d');
  if (charts['compare-equity']) charts['compare-equity'].destroy();
  charts['compare-equity'] = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: strategies.map(s => {
        const eq = d[s].stats.equity_curve;
        return {
          label: d[s].meta.name,
          data:  eq.map((p,i) => ({x: i, y: p.balance})),
          borderColor: COLORS[s],
          backgroundColor: COLORS[s] + '15',
          fill: false,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
        };
      }),
    },
    options: chartDefaults({
      scales: {
        x: { type:'linear', display:true, grid:{color:'rgba(255,255,255,0.03)'}, ticks:{color:'#3d4f6e',font:{size:9}} },
        y: { grid:{color:'rgba(255,255,255,0.03)'}, ticks:{color:'#3d4f6e',font:{size:9}, callback: v => '$'+v.toLocaleString()} },
      },
      plugins: {
        legend: { display:true, labels:{color:'#8892a8',font:{size:10},boxWidth:12} },
        tooltip: { callbacks: { label: ctx => ctx.dataset.label + ': $' + ctx.parsed.y.toLocaleString() } }
      }
    }),
  });

  // Bar chart: total pnl comparison
  const ctx2 = document.getElementById('compare-pnl').getContext('2d');
  if (charts['compare-pnl']) charts['compare-pnl'].destroy();
  charts['compare-pnl'] = new Chart(ctx2, {
    type: 'bar',
    data: {
      labels: strategies.map(s => d[s].meta.name),
      datasets: [
        {
          label: 'Gross Profit',
          data: strategies.map(s => d[s].stats.gross_profit),
          backgroundColor: 'rgba(16,185,129,0.6)',
          borderRadius: 4,
        },
        {
          label: 'Gross Loss',
          data: strategies.map(s => -d[s].stats.gross_loss),
          backgroundColor: 'rgba(239,68,68,0.6)',
          borderRadius: 4,
        },
        {
          label: 'Net P&L',
          data: strategies.map(s => d[s].stats.total_pnl),
          backgroundColor: strategies.map(s => d[s].stats.total_pnl >= 0 ? 'rgba(59,130,246,0.8)' : 'rgba(239,68,68,0.8)'),
          borderRadius: 4,
        },
      ],
    },
    options: chartDefaults({
      plugins: { legend: { display:true, labels:{color:'#8892a8',font:{size:10},boxWidth:12} } }
    }),
  });

  // Heatmaps per strategy
  strategies.forEach(s => {
    renderHeatmap(`compare-heatmap-${s}`, d[s].stats.pnl_by_hour, COLORS[s]);
  });
}

// ── CHART HELPERS ────────────────────────────────────────────────
function chartDefaults(extra = {}) {
  return {
    responsive: true, maintainAspectRatio: false,
    animation: { duration: 400 },
    plugins: {
      legend: { display: false },
      tooltip: { backgroundColor:'#111828', borderColor:'#1a2540', borderWidth:1, titleColor:'#8892a8', bodyColor:'#e8edf8', titleFont:{size:10}, bodyFont:{size:11} },
      ...extra.plugins,
    },
    scales: {
      x: { grid:{color:'rgba(255,255,255,0.03)'}, ticks:{color:'#3d4f6e', font:{size:9}, maxTicksLimit:12} },
      y: { grid:{color:'rgba(255,255,255,0.03)'}, ticks:{color:'#3d4f6e', font:{size:9}, callback: v => '$'+v} },
      ...extra.scales,
    },
    ...extra,
  };
}

function drawLine(id, {labels, data, color, fill, label}) {
  const ctx = document.getElementById(id)?.getContext('2d');
  if (!ctx) return;
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label, data,
        borderColor: color,
        backgroundColor: color + '18',
        fill,
        borderWidth: 2,
        pointRadius: data.length > 50 ? 0 : 2,
        pointBackgroundColor: color,
        tension: 0.3,
      }]
    },
    options: chartDefaults({
      scales: {
        x: { display: data.length <= 30, grid:{color:'rgba(255,255,255,0.03)'}, ticks:{color:'#3d4f6e',font:{size:9}} },
        y: { grid:{color:'rgba(255,255,255,0.03)'}, ticks:{color:'#3d4f6e',font:{size:9}, callback: v => '$'+v.toLocaleString()} },
      },
    }),
  });
}

function drawBars(id, {labels, data, colors, label, yMax}) {
  const ctx = document.getElementById(id)?.getContext('2d');
  if (!ctx) return;
  if (charts[id]) charts[id].destroy();
  const opts = chartDefaults({});
  if (yMax) opts.scales.y.max = yMax;
  opts.scales.y.ticks.callback = v => label === 'Win %' ? v + '%' : '$' + v;
  charts[id] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label, data,
        backgroundColor: colors || '#3b82f680',
        borderRadius: 2,
      }]
    },
    options: opts,
  });
}

function renderHeatmap(containerId, pnlByHour, color) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const hours = Array.from({length:24}, (_,i) => String(i));
  const pnls  = hours.map(h => pnlByHour[h]?.pnl || 0);
  const maxAbs = Math.max(...pnls.map(Math.abs), 1);

  el.innerHTML = `
    <div class="heatmap">
      ${hours.map(h => {
        const pnl    = pnlByHour[h]?.pnl || 0;
        const trades = pnlByHour[h]?.trades || 0;
        const intensity = Math.abs(pnl) / maxAbs;
        const bg = pnl > 0
          ? `rgba(16,185,129,${0.1 + intensity * 0.7})`
          : pnl < 0
            ? `rgba(239,68,68,${0.1 + intensity * 0.7})`
            : 'rgba(255,255,255,0.04)';
        return `<div class="heatmap-cell" style="background:${bg};" title="${h}:00 UTC — ${trades} trades — $${pnl.toFixed(0)}">${h}</div>`;
      }).join('')}
    </div>
    <div class="heatmap-label" style="margin-top:8px;font-size:9px;color:var(--text3);">
      Hour (UTC) · Green = profit · Red = loss · Intensity = magnitude
    </div>
  `;
}

function statCard(label, value, color, sub='') {
  return `
    <div class="stat-card" style="--accent:${color}">
      <div class="stat-label">${label}</div>
      <div class="stat-value" style="color:${color}">${value}</div>
      ${sub ? `<div class="stat-sub">${sub}</div>` : ''}
    </div>
  `;
}

// ── TIMING ANALYSIS ──────────────────────────────────────────
async function loadTiming() {
  document.getElementById('data-timing').innerHTML = `
    <div style="display:flex;align-items:center;justify-content:center;height:200px;color:var(--text2);font-size:13px;">
      Φόρτωση timing data...
    </div>`;

  let all = {};
  try {
    const res = await fetch('/api/analytics');
    all = await res.json();
  } catch(e) {
    document.getElementById('data-timing').innerHTML = `
      <div style="padding:40px;color:#ef4444;font-size:12px;">Error loading data: ${e.message}</div>`;
    return;
  }

  // Συγκεντρώνουμε όλα τα trades απ' όλες τις strategies
  const strats = ['A','B','C','CM','SMC'];
  let byHour = {};
  let byDay  = {};

  strats.forEach(s => {
    const st = all[s]?.stats || {};
    const ph = st.pnl_by_hour || {};
    const pd = st.pnl_by_day  || {};

    Object.keys(ph).forEach(h => {
      if (!byHour[h]) byHour[h] = {pnl:0, trades:0, wins:0, win_rate:0};
      byHour[h].pnl    += ph[h].pnl    || 0;
      byHour[h].trades += ph[h].trades || 0;
      byHour[h].wins   += ph[h].wins   || 0;
    });
    Object.keys(pd).forEach(d => {
      if (!byDay[d]) byDay[d] = {pnl:0, trades:0, wins:0, win_rate:0, name: pd[d].name};
      byDay[d].pnl    += pd[d].pnl    || 0;
      byDay[d].trades += pd[d].trades || 0;
      byDay[d].wins   += pd[d].wins   || 0;
    });
  });

  // Υπολογισμός win rates
  Object.keys(byHour).forEach(h => {
    byHour[h].win_rate = byHour[h].trades > 0
      ? Math.round(byHour[h].wins / byHour[h].trades * 100) : 0;
  });
  Object.keys(byDay).forEach(d => {
    byDay[d].win_rate = byDay[d].trades > 0
      ? Math.round(byDay[d].wins / byDay[d].trades * 100) : 0;
  });

  // Top/Bottom hours (min 2 trades)
  const hourArr = Object.entries(byHour)
    .filter(([h,v]) => v.trades >= 2)
    .sort((a,b) => b[1].win_rate - a[1].win_rate);
  const topH    = hourArr.slice(0,3);
  const bottomH = hourArr.slice(-3).reverse();

  // Best/Worst days
  const dayArr = Object.entries(byDay)
    .filter(([d,v]) => v.trades >= 1)
    .sort((a,b) => b[1].win_rate - a[1].win_rate);

  const totalTrades = Object.values(byHour).reduce((s,v) => s+v.trades, 0);

  document.getElementById('data-timing').innerHTML = `
    <!-- SUMMARY CARDS -->
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:20px;">
      ${topH.length ? `
        ${topH.map(([h,v]) => `
          <div class="stat-card" style="--accent:#10b981;">
            <div class="stat-label">🏆 Best: ${h}:00 UTC</div>
            <div class="stat-value" style="color:#10b981;">${v.win_rate}%</div>
            <div class="stat-sub">${v.trades} trades · $${v.pnl.toFixed(0)}</div>
          </div>`).join('')}
        ${bottomH.map(([h,v]) => `
          <div class="stat-card" style="--accent:#ef4444;">
            <div class="stat-label">⚠️ Worst: ${h}:00 UTC</div>
            <div class="stat-value" style="color:#ef4444;">${v.win_rate}%</div>
            <div class="stat-sub">${v.trades} trades · $${v.pnl.toFixed(0)}</div>
          </div>`).join('')}
      ` : `<div style="grid-column:1/-1;color:var(--text2);font-size:12px;padding:20px;">
        Δεν υπάρχουν αρκετά δεδομένα ακόμα (χρειάζονται 2+ trades/ώρα).
        Τα charts θα γεμίσουν καθώς το bot εκτελεί trades.
      </div>`}
    </div>

    <!-- HOURLY WIN RATE CHART -->
    <div class="chart-card" style="margin-bottom:16px;">
      <div class="chart-title" style="--accent:var(--a)">
        <span style="background:var(--a)"></span>
        Win Rate ανά Ώρα (UTC) — Όλες οι Στρατηγικές · ${totalTrades} trades
      </div>
      <div class="chart-wrap tall"><canvas id="timing-hour-wr"></canvas></div>
    </div>

    <!-- HOURLY PNL CHART -->
    <div class="chart-card" style="margin-bottom:16px;">
      <div class="chart-title" style="--accent:var(--yellow)">
        <span style="background:var(--yellow)"></span>P&L ανά Ώρα (USD)
      </div>
      <div class="chart-wrap"><canvas id="timing-hour-pnl"></canvas></div>
    </div>

    <!-- DAY OF WEEK -->
    <div class="grid-2" style="margin-bottom:16px;">
      <div class="chart-card">
        <div class="chart-title" style="--accent:var(--b)">
          <span style="background:var(--b)"></span>Win Rate ανά Ημέρα Εβδομάδας
        </div>
        <div class="chart-wrap"><canvas id="timing-day-wr"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title" style="--accent:var(--c)">
          <span style="background:var(--c)"></span>Αριθμός Trades ανά Ημέρα
        </div>
        <div class="chart-wrap"><canvas id="timing-day-count"></canvas></div>
      </div>
    </div>

    <!-- TRADES TABLE PER HOUR -->
    <div class="chart-card">
      <div class="chart-title" style="--accent:var(--text3)">
        <span style="background:var(--text3)"></span>Αναλυτικά ανά Ώρα
      </div>
      <div style="overflow-x:auto;">
        <table class="trades-table">
          <thead><tr>
            <th>Ώρα (UTC)</th><th>Trades</th><th>Wins</th><th>Losses</th>
            <th>Win Rate</th><th>Net P&L</th><th>Avg/Trade</th>
          </tr></thead>
          <tbody>
            ${Array.from({length:24},(_,i)=>String(i)).map(h => {
              const v = byHour[h] || {trades:0,wins:0,pnl:0,win_rate:0};
              if (v.trades === 0) return '';
              const losses = v.trades - v.wins;
              const avg = v.trades > 0 ? (v.pnl/v.trades).toFixed(1) : 0;
              const wrColor = v.win_rate >= 60 ? '#10b981' : v.win_rate >= 45 ? '#f59e0b' : '#ef4444';
              return `<tr>
                <td style="font-weight:600;">${h.padStart(2,'0')}:00</td>
                <td>${v.trades}</td>
                <td class="text-green">${v.wins}</td>
                <td class="text-red">${losses}</td>
                <td style="color:${wrColor};font-weight:600;">${v.win_rate}%</td>
                <td class="${v.pnl>=0?'text-green':'text-red'}">$${v.pnl.toFixed(0)}</td>
                <td class="${avg>=0?'text-green':'text-red'}">$${avg}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;

  // Chart: Win Rate ανά ώρα
  const hours = Array.from({length:24},(_,i)=>String(i));
  const wrData = hours.map(h => byHour[h]?.win_rate || 0);
  const wrColors = wrData.map(v => v >= 60 ? 'rgba(16,185,129,0.7)' : v >= 45 ? 'rgba(245,158,11,0.7)' : v > 0 ? 'rgba(239,68,68,0.7)' : 'rgba(255,255,255,0.05)');
  const ctx1 = document.getElementById('timing-hour-wr').getContext('2d');
  if (charts['timing-hour-wr']) charts['timing-hour-wr'].destroy();
  charts['timing-hour-wr'] = new Chart(ctx1, {
    type: 'bar',
    data: {
      labels: hours.map(h => h.padStart(2,'0')+':00'),
      datasets: [{
        label: 'Win Rate %',
        data: wrData,
        backgroundColor: wrColors,
        borderRadius: 3,
      }]
    },
    options: chartDefaults({
      scales: {
        x: { grid:{color:'rgba(255,255,255,0.02)'}, ticks:{color:'#3d4f6e',font:{size:8}} },
        y: { max:100, grid:{color:'rgba(255,255,255,0.03)'}, ticks:{color:'#3d4f6e',font:{size:9}, callback:v=>v+'%'} },
      },
      plugins: {
        tooltip: { callbacks: { label: c => `Win Rate: ${c.raw}% (${byHour[String(c.dataIndex)]?.trades||0} trades)` } }
      }
    }),
  });

  // Chart: PnL ανά ώρα
  const pnlData = hours.map(h => byHour[h]?.pnl || 0);
  const pnlColors = pnlData.map(v => v >= 0 ? 'rgba(16,185,129,0.6)' : 'rgba(239,68,68,0.6)');
  const ctx2 = document.getElementById('timing-hour-pnl').getContext('2d');
  if (charts['timing-hour-pnl']) charts['timing-hour-pnl'].destroy();
  charts['timing-hour-wr2'] = new Chart(ctx2, {
    type: 'bar',
    data: {
      labels: hours.map(h => h.padStart(2,'0')+':00'),
      datasets: [{ label: 'P&L $', data: pnlData, backgroundColor: pnlColors, borderRadius: 3 }]
    },
    options: chartDefaults({
      scales: {
        x: { grid:{color:'rgba(255,255,255,0.02)'}, ticks:{color:'#3d4f6e',font:{size:8}} },
        y: { grid:{color:'rgba(255,255,255,0.03)'}, ticks:{color:'#3d4f6e',font:{size:9}, callback:v=>'$'+v} },
      }
    }),
  });

  // Chart: Win Rate ανά ημέρα
  const days7 = ['0','1','2','3','4','5','6'];
  const dayLabels = days7.map(d => byDay[d]?.name || ['Δευ','Τρι','Τετ','Πεμ','Παρ','Σαβ','Κυρ'][+d]);
  const dayWR  = days7.map(d => byDay[d]?.win_rate || 0);
  const dayColors = dayWR.map(v => v >= 60 ? 'rgba(16,185,129,0.7)' : v >= 45 ? 'rgba(245,158,11,0.7)' : v > 0 ? 'rgba(239,68,68,0.7)' : 'rgba(255,255,255,0.05)');
  const ctx3 = document.getElementById('timing-day-wr').getContext('2d');
  if (charts['timing-day-wr']) charts['timing-day-wr'].destroy();
  charts['timing-day-wr'] = new Chart(ctx3, {
    type: 'bar',
    data: {
      labels: dayLabels,
      datasets: [{ label: 'Win Rate %', data: dayWR, backgroundColor: dayColors, borderRadius: 4 }]
    },
    options: chartDefaults({
      scales: {
        x: { grid:{display:false}, ticks:{color:'#8892a8',font:{size:11}} },
        y: { max:100, grid:{color:'rgba(255,255,255,0.03)'}, ticks:{color:'#3d4f6e',font:{size:9}, callback:v=>v+'%'} }
      }
    }),
  });

  // Chart: Trades count ανά ημέρα
  const dayCount = days7.map(d => byDay[d]?.trades || 0);
  const ctx4 = document.getElementById('timing-day-count').getContext('2d');
  if (charts['timing-day-count']) charts['timing-day-count'].destroy();
  charts['timing-day-count'] = new Chart(ctx4, {
    type: 'bar',
    data: {
      labels: dayLabels,
      datasets: [{ label: 'Trades', data: dayCount, backgroundColor: 'rgba(139,92,246,0.6)', borderRadius: 4 }]
    },
    options: chartDefaults({
      scales: {
        x: { grid:{display:false}, ticks:{color:'#8892a8',font:{size:11}} },
        y: { grid:{color:'rgba(255,255,255,0.03)'}, ticks:{color:'#3d4f6e',font:{size:9}} }
      },
      plugins: { tooltip: { callbacks: { label: c => `${c.raw} trades` } } }
    }),
  });
}

// ─────────────────────────────────────────────────────────────
// Load first tab on page load
loadStrategy('A');
</script>
</body>
</html>
"""

@analytics_bp.route("/analytics")
def analytics_index():
    return render_template_string(ANALYTICS_HTML)

@analytics_bp.route("/analytics/<strategy>")
def analytics_strategy(strategy):
    # Redirect to main analytics page με το σωστό tab
    return render_template_string(ANALYTICS_HTML)
