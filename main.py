"""
main.py — SMC AI Bot Dashboard v2
Beautiful UI with TradingView chart embedded
"""

from flask import Flask, render_template_string, jsonify
from bot import state, bot_thread
from config import PORT

app = Flask(__name__)
bot_thread.start()

DASHBOARD = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMC AI Bot</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

  * { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:       #0a0e1a;
    --bg2:      #111827;
    --bg3:      #1a2235;
    --border:   #1e2d45;
    --border2:  #243550;
    --text:     #e2e8f0;
    --text2:    #94a3b8;
    --text3:    #475569;
    --green:    #10b981;
    --green2:   #059669;
    --red:      #ef4444;
    --red2:     #dc2626;
    --yellow:   #f59e0b;
    --blue:     #3b82f6;
    --purple:   #8b5cf6;
    --glow-g:   0 0 20px rgba(16,185,129,0.15);
    --glow-r:   0 0 20px rgba(239,68,68,0.15);
    --glow-y:   0 0 20px rgba(245,158,11,0.15);
  }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', sans-serif;
    min-height: 100vh;
  }

  /* ── LAYOUT ── */
  .app { display: grid; grid-template-columns: 1fr 360px; min-height: 100vh; height: 100vh; overflow: hidden; }
  .main-col { grid-column: 1; display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
  .side-col  { grid-column: 2; background: var(--bg2); border-left: 1px solid var(--border); display: flex; flex-direction: column; overflow-y: auto; overflow-x: hidden; }

  /* ── TOP BAR ── */
  .topbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 20px;
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
  }
  .topbar-left { display: flex; align-items: center; gap: 12px; }
  .logo { font-size: 15px; font-weight: 700; color: var(--text); letter-spacing: -0.3px; }
  .logo span { color: var(--green); }
  .badge {
    font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: 20px;
    letter-spacing: 0.5px; text-transform: uppercase;
  }
  .badge-paper  { background: rgba(245,158,11,0.15); color: var(--yellow); border: 1px solid rgba(245,158,11,0.3); }
  .badge-live   { background: rgba(16,185,129,0.15); color: var(--green);  border: 1px solid rgba(16,185,129,0.3); }
  .badge-green  { background: rgba(16,185,129,0.15); color: var(--green);  border: 1px solid rgba(16,185,129,0.3); }
  .badge-red    { background: rgba(239,68,68,0.15);  color: var(--red);    border: 1px solid rgba(239,68,68,0.3); }
  .badge-gray   { background: rgba(71,85,105,0.3);   color: var(--text2);  border: 1px solid var(--border); }
  .topbar-right { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text3); }
  .pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--green); animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }

  /* ── CHART AREA ── */
  .chart-wrap {
    flex: 1;
    background: var(--bg);
    height: calc(100vh - 100px);
    min-height: 400px;
    position: relative;
    overflow: hidden;
  }
  .chart-wrap > div,
  .chart-wrap .tradingview-widget-container,
  .chart-wrap .tradingview-widget-container__widget {
    height: 100% !important;
    width: 100% !important;
  }
  .chart-wrap iframe {
    height: 100% !important;
    width: 100% !important;
    border: none !important;
  }
  .chart-toolbar {
    display: flex; align-items: center; gap: 6px;
    padding: 8px 16px;
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .tf-btn {
    font-size: 11px; font-weight: 500; padding: 4px 10px;
    border-radius: 6px; cursor: pointer; border: 1px solid var(--border);
    background: transparent; color: var(--text2);
    transition: all 0.15s;
  }
  .tf-btn:hover, .tf-btn.active {
    background: var(--blue); color: white; border-color: var(--blue);
  }
  .chart-label { font-size: 11px; color: var(--text3); margin-left: auto; }
  #tv-chart { width: 100%; height: 100%; }

  /* ── SIDE PANEL ── */
  .side-section { padding: 16px; border-bottom: 1px solid var(--border); }
  .side-title {
    font-size: 10px; font-weight: 600; color: var(--text3);
    text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px;
  }

  /* ── PRICE HEADER ── */
  .price-display { padding: 16px; border-bottom: 1px solid var(--border); }
  .price-symbol { font-size: 11px; color: var(--text3); margin-bottom: 4px; }
  .price-main { font-size: 28px; font-weight: 700; letter-spacing: -1px; }
  .price-change { font-size: 12px; margin-top: 2px; }

  /* ── STATS GRID ── */
  .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .stat-card {
    background: var(--bg3); border: 1px solid var(--border);
    border-radius: 10px; padding: 10px 12px;
  }
  .stat-label { font-size: 9px; color: var(--text3); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }
  .stat-value { font-size: 16px; font-weight: 600; }

  /* ── SIGNAL CARD ── */
  .signal-card {
    border-radius: 10px; padding: 14px;
    border: 1px solid var(--border);
    background: var(--bg3);
  }
  .signal-type {
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 13px; font-weight: 700; padding: 5px 14px;
    border-radius: 8px; margin-bottom: 10px;
  }
  .signal-long  { background: rgba(16,185,129,0.15); color: var(--green); border: 1px solid rgba(16,185,129,0.3); }
  .signal-short { background: rgba(239,68,68,0.15);  color: var(--red);   border: 1px solid rgba(239,68,68,0.3); }
  .signal-wait  { background: rgba(71,85,105,0.2);   color: var(--text2); border: 1px solid var(--border); }
  .signal-text  { font-size: 11px; color: var(--text2); line-height: 1.6; }

  /* ── BOX LEVELS ── */
  .box-levels { display: flex; flex-direction: column; gap: 6px; }
  .level-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 12px; border-radius: 8px;
  }
  .level-pdh { background: rgba(239,68,68,0.08);  border: 1px solid rgba(239,68,68,0.2); }
  .level-mid { background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.2); }
  .level-pdl { background: rgba(16,185,129,0.08); border: 1px solid rgba(16,185,129,0.2); }
  .level-name { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
  .level-desc { font-size: 9px; opacity: 0.6; margin-top: 1px; }
  .level-price { font-size: 14px; font-weight: 700; font-variant-numeric: tabular-nums; }

  /* ── POSITION CARD ── */
  .pos-card {
    background: var(--bg3); border-radius: 10px; padding: 14px;
    border: 1px solid rgba(245,158,11,0.3);
  }
  .pos-row {
    display: flex; justify-content: space-between;
    padding: 6px 0; border-bottom: 1px solid var(--border);
    font-size: 12px;
  }
  .pos-row:last-child { border-bottom: none; }
  .pos-key { color: var(--text2); }

  /* ── RSI BAR ── */
  .rsi-wrap { margin-top: 8px; }
  .rsi-bar-bg { height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; margin-top: 4px; }
  .rsi-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s ease; }

  /* ── NEWS ── */
  .news-score-badge {
    display: inline-block; padding: 2px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 600; margin-left: 6px;
  }
  .news-summary { font-size: 11px; color: var(--text2); margin-top: 6px; line-height: 1.5; }
  .news-hl { font-size: 10px; color: var(--text3); padding: 4px 0; border-bottom: 1px solid var(--border); }

  /* ── TRADE TABLE ── */
  .trade-table { width: 100%; border-collapse: collapse; font-size: 11px; }
  .trade-table th { color: var(--text3); text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); font-weight: 500; }
  .trade-table td { padding: 6px 8px; border-bottom: 1px solid rgba(30,45,69,0.5); }
  .pill {
    display: inline-block; padding: 2px 7px; border-radius: 4px;
    font-size: 9px; font-weight: 600; text-transform: uppercase;
  }
  .pill-long  { background: rgba(16,185,129,0.15); color: var(--green); }
  .pill-short { background: rgba(239,68,68,0.15);  color: var(--red);   }
  .pill-win   { background: rgba(16,185,129,0.15); color: var(--green); }
  .pill-loss  { background: rgba(239,68,68,0.15);  color: var(--red);   }
  .pill-div   { background: rgba(245,158,11,0.15); color: var(--yellow);}

  /* ── ERRORS ── */
  .error-item { font-size: 10px; color: var(--red); padding: 3px 0; }

  /* ── BOTTOM BAR ── */
  .bottombar {
    padding: 10px 20px;
    background: var(--bg2); border-top: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: center;
    font-size: 10px; color: var(--text3);
  }

  /* ── MOBILE ── */
  @media (max-width: 900px) {
    .app {
      grid-template-columns: 1fr;
      grid-template-rows: auto auto;
    }
    .main-col { grid-column: 1; grid-row: 1; }
    .side-col {
      grid-column: 1; grid-row: 2;
      border-left: none;
      border-top: 1px solid var(--border);
      max-height: none;
    }
    .chart-wrap {
      height: 55vw;
      min-height: 280px;
      max-height: 420px;
    }
    .stats-grid { grid-template-columns: 1fr 1fr; }
    .topbar { padding: 10px 14px; flex-wrap: wrap; gap: 6px; }
    .logo { font-size: 14px; }
    .price-main { font-size: 22px; }
  }
  @media (max-width: 480px) {
    .chart-wrap { height: 60vw; min-height: 240px; }
    .tf-btn { padding: 3px 7px; font-size: 10px; }
    .side-section { padding: 12px; }
  }

  .divider { width: 1px; height: 16px; background: var(--border); }
  .text-green { color: var(--green); }
  .text-red   { color: var(--red);   }
  .text-yellow{ color: var(--yellow);}
  .text-blue  { color: var(--blue);  }
  .text-gray  { color: var(--text2); }
  .text-dim   { color: var(--text3); }
</style>
</head>
<body>

<div class="app">

  <!-- ══ MAIN COLUMN ══ -->
  <div class="main-col">

    <!-- TOP BAR -->
    <div class="topbar">
      <div class="topbar-left">
        <div class="logo">SMC <span>AI</span> Bot</div>
        <span class="badge {{ 'badge-paper' if mode == 'PAPER' else 'badge-live' }}">{{ mode }}</span>
        <span class="badge badge-gray">BTC/USDT PERP</span>
        <span class="badge badge-gray">BITGET</span>
        {% if position %}
        <span class="badge {{ 'badge-green' if position.type == 'LONG' else 'badge-red' }}">
          {{ position.type }} OPEN
        </span>
        {% endif %}
      </div>
      <div class="topbar-right">
        <div class="pulse"></div>
        <span>LIVE</span>
        <div class="divider"></div>
        <span>{{ last_cycle }}</span>
      </div>
    </div>

    <!-- CHART TOOLBAR -->
    <div class="chart-toolbar">
      <button class="tf-btn" onclick="setTF('1')">1m</button>
      <button class="tf-btn" onclick="setTF('5')">5m</button>
      <button class="tf-btn" onclick="setTF('15')">15m</button>
      <button class="tf-btn active" onclick="setTF('60')" id="tf-60">1H</button>
      <button class="tf-btn" onclick="setTF('240')">4H</button>
      <button class="tf-btn" onclick="setTF('D')">1D</button>
      <span class="chart-label">powered by TradingView</span>
    </div>

    <!-- TRADINGVIEW CHART -->
    <div class="chart-wrap">
      <div class="tradingview-widget-container" id="tv-chart" style="height:100%;width:100%;">
        <div class="tradingview-widget-container__widget" style="height:calc(100% - 32px);width:100%;"></div>
        <div class="tradingview-widget-copyright" style="display:none;"></div>
      </div>
    </div>

    <!-- BOTTOM BAR -->
    <div class="bottombar">
      <span>⚠ PAPER TRADING · NO REAL MONEY · EDUCATIONAL USE ONLY</span>
      <span>Auto-refresh 20s</span>
    </div>

  </div>

  <!-- ══ SIDE COLUMN ══ -->
  <div class="side-col">

    <!-- PRICE -->
    <div class="price-display">
      <div class="price-symbol">BTCUSDT · Perpetual</div>
      <div class="price-main {{ 'text-green' if current_price > 0 else 'text-gray' }}">
        ${{ "{:,.2f}".format(current_price) }}
      </div>
      <div class="price-change">
        <span class="badge {{ 'badge-green' if rsi < 30 else 'badge-red' if rsi > 70 else 'badge-gray' }}">
          RSI {{ rsi }}
        </span>
        {% if divergence %}
        <span class="badge badge-paper" style="margin-left:4px;">📊 Divergence!</span>
        {% endif %}
      </div>
    </div>

    <!-- STATS -->
    <div class="side-section">
      <div class="side-title">Performance</div>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">Balance</div>
          <div class="stat-value text-green">${{ "{:,.0f}".format(balance) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Total P&L</div>
          <div class="stat-value {{ 'text-green' if pnl >= 0 else 'text-red' }}">
            {{ '+' if pnl >= 0 else '' }}${{ "{:.2f}".format(pnl) }}
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Win Rate</div>
          <div class="stat-value text-yellow">{{ win_rate }}%</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">W / L</div>
          <div class="stat-value text-gray">{{ wins }}W · {{ losses }}L</div>
        </div>
      </div>

      <!-- RSI Bar -->
      <div class="rsi-wrap">
        <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text3);margin-top:10px;">
          <span>RSI (14)</span><span>{{ rsi }}</span>
        </div>
        <div class="rsi-bar-bg">
          <div class="rsi-bar-fill" style="width:{{ rsi }}%;background:{{ '#ef4444' if rsi > 70 else '#10b981' if rsi < 30 else '#3b82f6' }};"></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:9px;color:var(--text3);margin-top:2px;">
          <span>0</span><span>30</span><span>70</span><span>100</span>
        </div>
      </div>
    </div>

    <!-- SIGNAL -->
    <div class="side-section">
      <div class="side-title">Current Signal</div>
      <div class="signal-card">
        {% if 'LONG' in signal and 'block' not in signal.lower() and 'HOLDING' not in signal %}
          <div class="signal-type signal-long">▲ LONG</div>
        {% elif 'SHORT' in signal and 'block' not in signal.lower() and 'HOLDING' not in signal %}
          <div class="signal-type signal-short">▼ SHORT</div>
        {% elif 'HOLDING' in signal %}
          <div class="signal-type signal-wait">◆ {{ position.type if position else 'HOLDING' }}</div>
        {% else %}
          <div class="signal-type signal-wait">◌ WAIT</div>
        {% endif %}
        <div class="signal-text">{{ signal }}</div>
        {% if signal_time %}
        <div style="font-size:10px;color:var(--text3);margin-top:6px;">{{ signal_time }}</div>
        {% endif %}
      </div>
    </div>

    <!-- PREVIOUS DAY BOX -->
    {% if box %}
    <div class="side-section">
      <div class="side-title">Previous Day Box · {{ box.date }}</div>
      <div class="box-levels">
        <div class="level-row level-pdh">
          <div>
            <div class="level-name text-red">PDH · Short Zone</div>
            <div class="level-desc">RSI > 70 → Sell</div>
          </div>
          <div class="level-price text-red">${{ "{:,.2f}".format(box.high) }}</div>
        </div>
        <div class="level-row level-mid">
          <div>
            <div class="level-name text-yellow">MID · Take Profit</div>
            <div class="level-desc">TP for both setups</div>
          </div>
          <div class="level-price text-yellow">${{ "{:,.2f}".format(box.mid) }}</div>
        </div>
        <div class="level-row level-pdl">
          <div>
            <div class="level-name text-green">PDL · Long Zone</div>
            <div class="level-desc">RSI < 30 → Buy</div>
          </div>
          <div class="level-price text-green">${{ "{:,.2f}".format(box.low) }}</div>
        </div>
      </div>
      <div style="font-size:10px;color:var(--text3);margin-top:8px;display:flex;gap:12px;">
        <span>Size: ${{ "{:,.0f}".format(box.size) }}</span>
        <span>R/R: 1:2</span>
        <span>Risk: 2% (4% w/ div)</span>
      </div>
    </div>
    {% endif %}

    <!-- OPEN POSITION -->
    {% if position %}
    <div class="side-section">
      <div class="side-title">Open Position</div>
      <div class="pos-card">
        <div class="pos-row">
          <span class="pos-key">Type</span>
          <span class="pill {{ 'pill-long' if position.type == 'LONG' else 'pill-short' }}">
            {{ position.type }}
          </span>
        </div>
        <div class="pos-row">
          <span class="pos-key">Entry</span>
          <span>${{ "{:,.2f}".format(position.entry) }}</span>
        </div>
        <div class="pos-row">
          <span class="pos-key">Take Profit</span>
          <span class="text-green">${{ "{:,.2f}".format(position.tp) }}</span>
        </div>
        <div class="pos-row">
          <span class="pos-key">Stop Loss</span>
          <span class="text-red">${{ "{:,.2f}".format(position.sl) }}</span>
        </div>
        <div class="pos-row">
          <span class="pos-key">Size (BTC)</span>
          <span>{{ position.qty }}</span>
        </div>
        <div class="pos-row">
          <span class="pos-key">Divergence</span>
          <span>{% if position.get('has_divergence') %}<span class="pill pill-div">🔥 DOUBLE</span>{% else %}Normal{% endif %}</span>
        </div>
        <div class="pos-row">
          <span class="pos-key">AI Score</span>
          <span class="{{ 'text-green' if position.news_score > 0 else 'text-red' if position.news_score < 0 else 'text-gray' }}">
            {{ position.news_score }}
          </span>
        </div>
        <div class="pos-row">
          <span class="pos-key">Opened</span>
          <span class="text-dim">{{ position.time }}</span>
        </div>
        {% if position.news_summary %}
        <div style="margin-top:8px;font-size:10px;color:var(--text2);line-height:1.5;">
          📰 {{ position.news_summary[:100] }}
        </div>
        {% endif %}
      </div>
    </div>
    {% endif %}

    <!-- AI NEWS -->
    <div class="side-section">
      <div class="side-title">
        AI News Analysis
        <span class="news-score-badge {{ 'badge-green' if news_score > 0 else 'badge-red' if news_score < 0 else 'badge-gray' }}">
          Score: {{ news_score }}
        </span>
      </div>
      {% if news_summary %}
      <div class="news-summary">{{ news_summary }}</div>
      {% endif %}
      {% for h in headlines[:6] %}
      <div class="news-hl">• {{ h }}</div>
      {% endfor %}
    </div>

    <!-- ERRORS -->
    {% if errors %}
    <div class="side-section">
      <div class="side-title" style="color:var(--red);">Recent Errors</div>
      {% for e in errors[-3:] %}
      <div class="error-item">{{ e }}</div>
      {% endfor %}
    </div>
    {% endif %}

    <!-- TRADE HISTORY -->
    {% if trades %}
    <div class="side-section">
      <div class="side-title">Trade History</div>
      <table class="trade-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Type</th>
            <th>P&L</th>
            <th>Result</th>
            <th>Div</th>
          </tr>
        </thead>
        <tbody>
          {% for t in trades[-15:]|reverse %}
          <tr>
            <td class="text-dim">{{ t.time[5:16] }}</td>
            <td><span class="pill {{ 'pill-long' if t.type == 'LONG' else 'pill-short' }}">{{ t.type }}</span></td>
            <td class="{{ 'text-green' if t.pnl >= 0 else 'text-red' }}">
              {{ '+' if t.pnl >= 0 else '' }}${{ "{:.1f}".format(t.pnl) }}
            </td>
            <td><span class="pill {{ 'pill-win' if t.result == 'WIN' else 'pill-loss' }}">{{ t.result }}</span></td>
            <td>{% if t.get('divergence') %}<span class="text-yellow">🔥</span>{% else %}<span class="text-dim">—</span>{% endif %}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% endif %}

  </div><!-- end side-col -->
</div><!-- end app -->

<!-- TRADINGVIEW WIDGET SCRIPT -->
<script>
let currentTF = '60';

function setTF(tf) {
  currentTF = tf;
  document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  loadChart(tf);
}

function loadChart(interval) {
  const container = document.getElementById('tv-chart');
  container.innerHTML = '';

  const wrapper = document.createElement('div');
  wrapper.className = 'tradingview-widget-container';
  wrapper.style.cssText = 'height:100%;width:100%;';

  const widget = document.createElement('div');
  widget.className = 'tradingview-widget-container__widget';
  widget.style.cssText = 'height:100%;width:100%;';
  wrapper.appendChild(widget);

  const script = document.createElement('script');
  script.type = 'text/javascript';
  script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
  script.async = true;
  script.innerHTML = JSON.stringify({
    "autosize": true,
    "symbol": "BITGET:BTCUSDT.P",
    "interval": interval,
    "timezone": "Etc/UTC",
    "theme": "dark",
    "style": "1",
    "locale": "en",
    "backgroundColor": "#0a0e1a",
    "gridColor": "rgba(30,45,69,0.3)",
    "hide_top_toolbar": false,
    "hide_legend": false,
    "hide_side_toolbar": false,
    "allow_symbol_change": false,
    "save_image": false,
    "withdateranges": true,
    "studies": [
      "RSI@tv-basicstudies",
      "VWAP@tv-basicstudies"
    ],
    "support_host": "https://www.tradingview.com"
  });
  wrapper.appendChild(script);
  container.appendChild(wrapper);
}

// Load chart on page ready
loadChart('60');

// Auto-refresh every 20 seconds
setTimeout(() => location.reload(), 20000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    s      = state
    wins   = s["wins"]
    losses = s["losses"]
    total  = wins + losses
    return render_template_string(
        DASHBOARD,
        mode          = s["mode"],
        balance       = s["balance"],
        pnl           = s["pnl_total"],
        wins          = wins,
        losses        = losses,
        win_rate      = round(wins / total * 100) if total > 0 else 0,
        rsi           = s["current_rsi"],
        divergence    = s.get("last_divergence", False),
        signal        = s["last_signal"],
        signal_time   = s["last_signal_time"],
        last_cycle    = s["last_cycle"],
        position      = s["position"],
        box           = s["box"],
        current_price = s["current_price"],
        news_score    = s["last_news_score"],
        news_summary  = s["last_news_summary"],
        headlines     = s["last_news_headlines"],
        trades        = s["trades"],
        errors        = s["errors"],
    )


@app.route("/api")
def api():
    return jsonify(state)


if __name__ == "__main__":
    print(f"\n🚀 SMC AI Bot starting on port {PORT}")
    print(f"   Dashboard: http://localhost:{PORT}\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)
