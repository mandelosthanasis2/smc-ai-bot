"""
analytics.py — Analytics dashboard για SMC AI Bot
Προσθήκη νέας στρατηγικής: μόνο 1 γραμμή στο STRATEGIES dict
"""

from flask import Blueprint, jsonify, render_template_string
from database import get_conn
import json

analytics_bp = Blueprint("analytics", __name__)

# ── Config: πρόσθεσε νέα στρατηγική εδώ ──────────────────────────
STRATEGIES = {
    "A": {"name": "Strategy A", "color": "#3b82f6", "desc": "Daily Box + 1H RSI"},
    "B": {"name": "Strategy B", "color": "#8b5cf6", "desc": "1H Box + 15m RSI"},
    "C": {"name": "Strategy C", "color": "#f97316", "desc": "TV Webhook + 1H Box"},
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
                       divergence, news_score, trade_time as time, id
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
            "equity_curve": [], "pnl_by_hour": {},
            "consecutive_wins": 0, "consecutive_losses": 0,
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

    # PnL ανά ώρα
    pnl_by_hour = {str(h): {"pnl": 0, "trades": 0, "wins": 0} for h in range(24)}
    for t in trades:
        try:
            time_str = str(t["time"] or "")
            hour = str(int(time_str[11:13])) if len(time_str) >= 13 else "0"
            pnl_by_hour[hour]["pnl"]    = round(pnl_by_hour[hour]["pnl"] + float(t["pnl"] or 0), 2)
            pnl_by_hour[hour]["trades"] += 1
            if t["result"] == "WIN":
                pnl_by_hour[hour]["wins"] += 1
        except Exception:
            pass

    # Consecutive wins/losses
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
        "consecutive_wins":    max_cw,
        "consecutive_losses":  max_cl,
        "gross_profit":        round(gross_profit, 2),
        "gross_loss":          round(gross_loss, 2),
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
  </div>
  <div class="nav-right">
    <span style="font-size:10px;color:var(--text3);letter-spacing:1px;">ANALYTICS</span>
  </div>
</nav>

<div class="tabs">
  <button class="tab active" data-tab="A" onclick="switchTab('A')">Strategy A</button>
  <button class="tab" data-tab="B" onclick="switchTab('B')">Strategy B</button>
  <button class="tab" data-tab="C" onclick="switchTab('C')">Strategy C</button>
  <button class="tab" data-tab="compare" onclick="switchTab('compare')">⚡ Compare</button>
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

<!-- COMPARE -->
<div class="content" id="tab-compare">
  <div class="loading" id="loading-compare">Loading comparison...</div>
  <div id="data-compare" style="display:none;"></div>
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
    </div>

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
