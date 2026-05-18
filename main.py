"""
main.py — SMC AI Bot Dashboard v2
Beautiful UI with TradingView chart embedded
"""

from flask import Flask, render_template_string, jsonify
from bot import state, state_b, state_c, bot_thread
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
        <a href="/b" style="font-size:11px;padding:3px 10px;border-radius:5px;background:rgba(139,92,246,0.15);color:#a855f7;border:1px solid rgba(139,92,246,0.3);text-decoration:none;margin-right:8px;">Strategy B →</a><span class="cycle-time">{{ last_cycle }}</span>
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
      <div class="price-main text-green price-main">
        ${{ "{:,.2f}".format(current_price) }}
      </div>
      <div class="price-change">
        <span class="badge badge-gray" id="rsi-badge">RSI <span class="rsi-val">{{ rsi }}</span></span>
        <span class="badge badge-paper" id="div-badge" style="margin-left:4px;display:{{ 'inline-block' if divergence else 'none' }};">📊 Divergence!</span>
      </div>
    </div>

    <!-- STATS -->
    <div class="side-section">
      <div class="side-title">Performance</div>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">Balance</div>
          <div class="stat-value text-green balance-val">${{ "{:,.0f}".format(balance) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Total P&L</div>
          <div class="stat-value {{ 'text-green' if pnl >= 0 else 'text-red' }} pnl-val">{{ '+' if pnl >= 0 else '' }}${{ "{:.2f}".format(pnl) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Win Rate</div>
          <div class="stat-value text-yellow wr-val">{{ win_rate }}%</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">W / L</div>
          <div class="stat-value text-gray wl-val">{{ wins }}W · {{ losses }}L</div>
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

// ── LIVE DATA UPDATE via fetch (no page reload) ─────────────────
function fmt(n, dec=2) {
  return '$' + Number(n).toLocaleString('en-US', {minimumFractionDigits:dec, maximumFractionDigits:dec});
}

function renderPanel(s) {
  const wins  = s.wins   || 0;
  const losses= s.losses || 0;
  const total = wins + losses;
  const wr    = total > 0 ? Math.round(wins/total*100) : 0;
  const rsi   = s.current_rsi || 50;
  const price = s.current_price || 0;
  const box   = s.box;
  const pos   = s.position;

  // ── Price ──
  document.getElementById('price-val').textContent  = fmt(price);
  document.getElementById('cycle-val').textContent  = s.last_cycle || '';

  // ── RSI badge ──
  const rsiBadge = document.getElementById('rsi-badge');
  rsiBadge.textContent = 'RSI ' + rsi;
  rsiBadge.className   = 'badge ' + (rsi > 70 ? 'badge-red' : rsi < 30 ? 'badge-green' : 'badge-gray');

  // ── RSI bar ──
  const bar = document.getElementById('rsi-bar');
  bar.style.width      = rsi + '%';
  bar.style.background = rsi > 70 ? '#ef4444' : rsi < 30 ? '#10b981' : '#3b82f6';
  document.getElementById('rsi-num').textContent = rsi;

  // ── Divergence ──
  const divBadge = document.getElementById('div-badge');
  divBadge.style.display = s.last_divergence ? 'inline-block' : 'none';

  // ── Stats ──
  document.getElementById('bal-val').textContent  = fmt(s.balance, 0);
  const pnlEl = document.getElementById('pnl-val');
  pnlEl.textContent  = (s.pnl_total >= 0 ? '+' : '') + fmt(s.pnl_total);
  pnlEl.className    = 'stat-value pnl-val ' + (s.pnl_total >= 0 ? 'text-green' : 'text-red');
  document.getElementById('wr-val').textContent   = wr + '%';
  document.getElementById('wl-val').textContent   = wins + 'W · ' + losses + 'L';

  // ── Signal ──
  const sigType = document.getElementById('sig-type');
  const sigText = document.getElementById('sig-text');
  const sigTime = document.getElementById('sig-time');
  sigText.textContent = s.last_signal || '';
  sigTime.textContent = s.last_signal_time || '';
  const sig = s.last_signal || '';
  if (sig.includes('LONG') && !sig.toLowerCase().includes('block') && !sig.includes('HOLDING')) {
    sigType.textContent  = '▲ LONG';
    sigType.className    = 'signal-type signal-long';
  } else if (sig.includes('SHORT') && !sig.toLowerCase().includes('block') && !sig.includes('HOLDING')) {
    sigType.textContent  = '▼ SHORT';
    sigType.className    = 'signal-type signal-short';
  } else if (sig.includes('HOLDING')) {
    sigType.textContent  = '◆ ' + (pos ? pos.type : 'HOLDING');
    sigType.className    = 'signal-type signal-wait';
  } else {
    sigType.textContent  = '◌ WAIT';
    sigType.className    = 'signal-type signal-wait';
  }

  // ── Box ──
  const boxSec = document.getElementById('box-section');
  if (box) {
    boxSec.style.display = 'block';
    document.getElementById('box-date').textContent = box.date || '';
    document.getElementById('box-high').textContent = fmt(box.high);
    document.getElementById('box-mid').textContent  = fmt(box.mid);
    document.getElementById('box-low').textContent  = fmt(box.low);
    document.getElementById('box-size').textContent = fmt(box.size, 0);
  } else {
    boxSec.style.display = 'none';
  }

  // ── Open Position ──
  const posSec = document.getElementById('pos-section');
  if (pos) {
    posSec.style.display = 'block';
    document.getElementById('pos-type').textContent  = pos.type;
    document.getElementById('pos-type').className    = 'pill ' + (pos.type==='LONG' ? 'pill-long' : 'pill-short');
    document.getElementById('pos-entry').textContent = fmt(pos.entry);
    document.getElementById('pos-tp').textContent    = fmt(pos.tp);
    document.getElementById('pos-sl').textContent    = fmt(pos.sl);
    document.getElementById('pos-qty').textContent   = pos.qty;
    document.getElementById('pos-div').innerHTML     = pos.has_divergence
      ? '<span class="pill pill-div">🔥 DOUBLE</span>' : 'Normal';
    document.getElementById('pos-score').textContent = pos.news_score || 0;
    document.getElementById('pos-score').className   =
      pos.news_score > 0 ? 'text-green' : pos.news_score < 0 ? 'text-red' : 'text-gray';
    document.getElementById('pos-time').textContent  = pos.time || '';
    document.getElementById('pos-news').textContent  = pos.news_summary
      ? '📰 ' + pos.news_summary.substring(0,100) : '';
    // Live unrealised PnL - only if price is valid
    if (price > 0) {
      const unreal = pos.type === 'LONG'
        ? (price - pos.entry) * pos.qty
        : (pos.entry - price) * pos.qty;
      const unrealEl = document.getElementById('pos-unreal');
      if (unrealEl) {
        unrealEl.textContent = (unreal >= 0 ? '+' : '-') + fmt(Math.abs(unreal));
        unrealEl.className   = 'stat-value ' + (unreal >= 0 ? 'text-green' : 'text-red');
      }
    }
  } else {
    posSec.style.display = 'none';
  }

  // ── News ──
  document.getElementById('news-score').textContent  = 'Score: ' + (s.last_news_score || 0);
  document.getElementById('news-score').className    =
    'news-score-badge ' + (s.last_news_score > 0 ? 'badge-green' : s.last_news_score < 0 ? 'badge-red' : 'badge-gray');
  document.getElementById('news-summary').textContent = s.last_news_summary || '';
  const hlDiv = document.getElementById('news-headlines');
  if (s.last_news_headlines) {
    hlDiv.innerHTML = s.last_news_headlines.slice(0,6).map(h =>
      '<div class="news-hl">• ' + h + '</div>'
    ).join('');
  }

  // ── Trade History ──
  const tradeSec = document.getElementById('trade-section');
  const tradeBody = document.getElementById('trade-body');
  if (s.trades && s.trades.length > 0) {
    tradeSec.style.display = 'block';
    const rows = [...s.trades].reverse().slice(0,15).map(t =>
      '<tr>' +
      '<td class="text-dim">' + (t.time||'').substring(5,16) + '</td>' +
      '<td><span class="pill ' + (t.type==='LONG'?'pill-long':'pill-short') + '">' + t.type + '</span></td>' +
      '<td class="' + (t.pnl>=0?'text-green':'text-red') + '">' + (t.pnl>=0?'+':'') + fmt(t.pnl,1) + '</td>' +
      '<td><span class="pill ' + (t.result==='WIN'?'pill-win':'pill-loss') + '">' + t.result + '</span></td>' +
      '<td>' + (t.divergence ? '<span class="text-yellow">🔥</span>' : '<span class="text-dim">—</span>') + '</td>' +
      '</tr>'
    ).join('');
    tradeBody.innerHTML = rows;
  } else {
    tradeSec.style.display = 'none';
  }

  // ── Errors ──
  const errSec  = document.getElementById('err-section');
  const errDiv  = document.getElementById('err-body');
  if (s.errors && s.errors.length > 0) {
    errSec.style.display = 'block';
    errDiv.innerHTML = s.errors.slice(-3).map(e => '<div class="error-item">' + e + '</div>').join('');
  } else {
    errSec.style.display = 'none';
  }

  // ── Pulse flash ──
  const dot = document.querySelector('.pulse');
  if (dot) {
    dot.style.background = '#f59e0b';
    setTimeout(() => { dot.style.background = '#10b981'; }, 400);
  }
}

function updateData() {
  fetch('/api')
    .then(r => r.json())
    .then(renderPanel)
    .catch(err => console.log('Update error:', err));
}

setInterval(updateData, 10000);
updateData();

// Smart reload: only reload full page when tab is hidden (user not watching)
// This refreshes trade history, news etc. without interrupting the user
let reloadTimer = null;

document.addEventListener('visibilitychange', function() {
  if (document.hidden) {
    // Tab hidden: schedule full reload after 60s
    reloadTimer = setTimeout(() => location.reload(), 60000);
  } else {
    // Tab visible again: cancel reload, just fetch fresh data
    if (reloadTimer) clearTimeout(reloadTimer);
    updateData();
  }
});
</script>
</body>
</html>
"""



# ═══════════════════════════════════════════════════════════════
# DASHBOARD B — Strategy B (15m entry | 1H box | R/R 2:1)
# ═══════════════════════════════════════════════════════════════
DASHBOARD_B = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMC AI Bot — Strategy B</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0a0e1a; --bg2: #111827; --bg3: #1a2235;
  --border: #1e2d45; --text: #e2e8f0; --text2: #94a3b8; --text3: #475569;
  --green: #10b981; --red: #ef4444; --yellow: #f59e0b; --blue: #3b82f6; --purple: #8b5cf6;
}
body { background: var(--bg); color: var(--text); font-family: Inter, monospace; }
.app { display: grid; grid-template-columns: 1fr 360px; min-height: 100vh; }
.main-col { display: flex; flex-direction: column; }
.side-col { background: var(--bg2); border-left: 1px solid var(--border); overflow-y: auto; }
.topbar { display: flex; align-items: center; justify-content: space-between; padding: 14px 20px; background: var(--bg2); border-bottom: 1px solid var(--border); }
.logo { font-size: 15px; font-weight: 700; }
.logo span { color: var(--purple); }
.badge { font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: 20px; letter-spacing: 0.5px; }
.badge-b { background: rgba(139,92,246,0.15); color: var(--purple); border: 1px solid rgba(139,92,246,0.3); }
.badge-paper { background: rgba(245,158,11,0.15); color: var(--yellow); border: 1px solid rgba(245,158,11,0.3); }
.badge-gray { background: rgba(71,85,105,0.3); color: var(--text2); border: 1px solid var(--border); }
.topbar-right { font-size: 11px; color: var(--text3); display: flex; align-items: center; gap: 8px; }
.pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--purple); animation: pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
.chart-toolbar { display: flex; align-items: center; gap: 6px; padding: 8px 16px; background: var(--bg2); border-bottom: 1px solid var(--border); }
.tf-btn { font-size: 11px; font-weight: 500; padding: 4px 10px; border-radius: 6px; cursor: pointer; border: 1px solid var(--border); background: transparent; color: var(--text2); transition: all 0.15s; }
.tf-btn.active { background: var(--purple); color: white; border-color: var(--purple); }
.chart-wrap { flex: 1; height: calc(100vh - 100px); min-height: 400px; overflow: hidden; }
.chart-wrap > div, .chart-wrap .tradingview-widget-container, .chart-wrap .tradingview-widget-container__widget { height: 100% !important; width: 100% !important; }
.side-section { padding: 16px; border-bottom: 1px solid var(--border); }
.side-title { font-size: 10px; font-weight: 600; color: var(--text3); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }
.price-display { padding: 16px; border-bottom: 1px solid var(--border); }
.price-main { font-size: 28px; font-weight: 700; color: var(--green); }
.stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.stat-card { background: var(--bg3); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }
.stat-label { font-size: 9px; color: var(--text3); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }
.stat-value { font-size: 16px; font-weight: 600; }
.signal-card { border-radius: 10px; padding: 14px; border: 1px solid var(--border); background: var(--bg3); }
.signal-type { display: inline-flex; align-items: center; font-size: 13px; font-weight: 700; padding: 5px 14px; border-radius: 8px; margin-bottom: 10px; }
.signal-long  { background: rgba(16,185,129,0.15); color: var(--green);  border: 1px solid rgba(16,185,129,0.3); }
.signal-short { background: rgba(239,68,68,0.15);  color: var(--red);    border: 1px solid rgba(239,68,68,0.3); }
.signal-wait  { background: rgba(71,85,105,0.2);   color: var(--text2);  border: 1px solid var(--border); }
.box-levels { display: flex; flex-direction: column; gap: 6px; }
.level-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border-radius: 8px; }
.level-pdh { background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.2); }
.level-mid { background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.2); }
.level-pdl { background: rgba(16,185,129,0.08); border: 1px solid rgba(16,185,129,0.2); }
.level-name { font-size: 10px; font-weight: 600; text-transform: uppercase; }
.level-price { font-size: 14px; font-weight: 700; }
.pos-card { background: var(--bg3); border-radius: 10px; padding: 14px; border: 1px solid rgba(139,92,246,0.3); }
.pos-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 12px; }
.pos-row:last-child { border-bottom: none; }
.trade-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.trade-table th { color: var(--text3); text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
.trade-table td { padding: 6px 8px; border-bottom: 1px solid rgba(30,45,69,0.5); }
.pill { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 9px; font-weight: 600; }
.pill-long  { background: rgba(16,185,129,0.15); color: var(--green); }
.pill-short { background: rgba(239,68,68,0.15);  color: var(--red);   }
.pill-win   { background: rgba(16,185,129,0.15); color: var(--green); }
.pill-loss  { background: rgba(239,68,68,0.15);  color: var(--red);   }
.nav-link { display: inline-block; padding: 4px 12px; border-radius: 6px; font-size: 11px; background: rgba(139,92,246,0.15); color: var(--purple); border: 1px solid rgba(139,92,246,0.3); text-decoration: none; }
.nav-link.active-a { background: rgba(59,130,246,0.15); color: var(--blue); border-color: rgba(59,130,246,0.3); }
.bottombar { padding: 10px 20px; background: var(--bg2); border-top: 1px solid var(--border); display: flex; justify-content: space-between; font-size: 10px; color: var(--text3); }
.text-green { color: var(--green); } .text-red { color: var(--red); } .text-yellow { color: var(--yellow); } .text-gray { color: var(--text2); } .text-dim { color: var(--text3); } .text-purple { color: var(--purple); }
.rsi-bar-bg { height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; margin-top: 4px; }
.rsi-bar-fill { height: 100%; border-radius: 3px; }
@media (max-width: 900px) {
  .app { grid-template-columns: 1fr; }
  .side-col { border-left: none; border-top: 1px solid var(--border); }
  .chart-wrap { height: 55vw; min-height: 280px; }
}
</style>
</head>
<body>
<div class="app">
  <div class="main-col">
    <div class="topbar">
      <div style="display:flex;align-items:center;gap:10px;">
        <div class="logo">SMC <span>AI</span> Bot</div>
        <span class="badge badge-b">STRATEGY B</span>
        <span class="badge badge-paper">PAPER</span>
        <span class="badge badge-gray">15m · 1H BOX</span>
        <span class="badge badge-gray">R/R 2:1</span>
        {% if position %}<span class="badge" style="background:rgba(139,92,246,0.15);color:#a855f7;border:1px solid rgba(139,92,246,0.3);">{{ position.type }} OPEN</span>{% endif %}
      </div>
      <div class="topbar-right">
        <a href="/" class="nav-link active-a">Strategy A</a>
        <a href="/b" class="nav-link">Strategy B</a>
        <div class="pulse"></div>
        <a href="/b" style="font-size:11px;padding:3px 10px;border-radius:5px;background:rgba(139,92,246,0.15);color:#a855f7;border:1px solid rgba(139,92,246,0.3);text-decoration:none;margin-right:8px;">Strategy B →</a><span class="cycle-time">{{ last_cycle }}</span>
      </div>
    </div>
    <div class="chart-toolbar">
      <button class="tf-btn" onclick="setTF('1')">1m</button>
      <button class="tf-btn active" onclick="setTF('15')" id="tf-15">15m</button>
      <button class="tf-btn" onclick="setTF('60')">1H</button>
      <button class="tf-btn" onclick="setTF('240')">4H</button>
      <span style="font-size:11px;color:#475569;margin-left:auto;">powered by TradingView</span>
    </div>
    <div class="chart-wrap"><div id="tv-chart"></div></div>
    <div class="bottombar">
      <span>⚠ PAPER TRADING · STRATEGY B · 15m ENTRY · 1H BOX · R/R 2:1</span>
      <span>Auto-refresh 10s</span>
    </div>
  </div>

  <div class="side-col">
    <div class="price-display">
      <div style="font-size:11px;color:var(--text3);margin-bottom:4px;">BTCUSDT · 15m</div>
      <div class="price-main" id="price-val">${{ "{:,.2f}".format(current_price) }}</div>
      <div style="margin-top:6px;">
        <span class="badge {{ 'badge-paper' if rsi < 30 else 'badge-gray' }}" id="rsi-badge" style="{{ 'background:rgba(239,68,68,0.15);color:#ef4444;border-color:#ef4444' if rsi > 70 else '' }}">RSI {{ rsi }}</span>
        {% if divergence %}<span class="badge badge-b" style="margin-left:4px;" id="div-badge">📊 Div!</span>{% else %}<span id="div-badge" style="display:none;"></span>{% endif %}
      </div>
    </div>

    <div class="side-section">
      <div class="side-title">Performance</div>
      <div class="stats-grid">
        <div class="stat-card"><div class="stat-label">Balance</div><div class="stat-value text-green" id="bal-val">${{ "{:,.0f}".format(balance) }}</div></div>
        <div class="stat-card"><div class="stat-label">Total P&L</div><div class="stat-value {{ 'text-green' if pnl >= 0 else 'text-red' }}" id="pnl-val">{{ '+' if pnl >= 0 else '' }}${{ "{:.2f}".format(pnl) }}</div></div>
        <div class="stat-card"><div class="stat-label">Win Rate</div><div class="stat-value text-yellow" id="wr-val">{{ win_rate }}%</div></div>
        <div class="stat-card"><div class="stat-label">W / L</div><div class="stat-value text-gray" id="wl-val">{{ wins }}W · {{ losses }}L</div></div>
      </div>
      <div style="margin-top:10px;">
        <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text3);">
          <span>RSI 15m</span><span id="rsi-num">{{ rsi }}</span>
        </div>
        <div class="rsi-bar-bg">
          <div class="rsi-bar-fill" id="rsi-bar" style="width:{{ rsi }}%;background:{{ '#ef4444' if rsi > 70 else '#10b981' if rsi < 30 else '#3b82f6' }};"></div>
        </div>
      </div>
    </div>

    <div class="side-section">
      <div class="side-title">Current Signal</div>
      <div class="signal-card">
        <div id="sig-type" class="signal-type signal-wait">◌ WAIT</div>
        <div id="sig-text" style="font-size:11px;color:var(--text2);">{{ signal }}</div>
        <div id="sig-time" style="font-size:10px;color:var(--text3);margin-top:4px;">{{ signal_time }}</div>
      </div>
    </div>

    {% if box %}
    <div class="side-section">
      <div class="side-title">1H Box · {{ box.time }}</div>
      <div class="box-levels">
        <div class="level-row level-pdh">
          <div><div class="level-name text-red">HIGH · Short Zone</div><div style="font-size:9px;opacity:0.6;">RSI > 70 → Sell</div></div>
          <div class="level-price text-red" id="box-high">${{ "{:,.2f}".format(box.high) }}</div>
        </div>
        <div class="level-row level-mid">
          <div><div class="level-name text-yellow">MID · Take Profit</div><div style="font-size:9px;opacity:0.6;">R/R 2:1</div></div>
          <div class="level-price text-yellow" id="box-mid">${{ "{:,.2f}".format(box.mid) }}</div>
        </div>
        <div class="level-row level-pdl">
          <div><div class="level-name text-green">LOW · Long Zone</div><div style="font-size:9px;opacity:0.6;">RSI < 30 → Buy</div></div>
          <div class="level-price text-green" id="box-low">${{ "{:,.2f}".format(box.low) }}</div>
        </div>
      </div>
      <div style="font-size:10px;color:var(--text3);margin-top:8px;">Box size: ${{ "{:,.0f}".format(box.size) }} · SL = TP/2 · R/R 2:1</div>
    </div>
    {% endif %}

    {% if position %}
    <div class="side-section">
      <div class="side-title">Open Position</div>
      <div class="pos-card">
        <div class="pos-row"><span style="color:var(--text2);">Type</span><span class="pill {{ 'pill-long' if position.type=='LONG' else 'pill-short' }}" id="pos-type">{{ position.type }}</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Entry</span><span id="pos-entry">${{ "{:,.2f}".format(position.entry) }}</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Unrealised</span><span id="pos-unreal" class="text-gray">—</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Take Profit</span><span class="text-green" id="pos-tp">${{ "{:,.2f}".format(position.tp) }}</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Stop Loss</span><span class="text-red" id="pos-sl">${{ "{:,.2f}".format(position.sl) }}</span></div>
        <div class="pos-row"><span style="color:var(--text2);">R/R</span><span class="text-purple">2:1</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Qty</span><span id="pos-qty">{{ position.qty }}</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Opened</span><span class="text-dim" id="pos-time">{{ position.time }}</span></div>
      </div>
    </div>
    {% endif %}

    {% if trades %}
    <div class="side-section">
      <div class="side-title">Trade History</div>
      <table class="trade-table">
        <thead><tr><th>Time</th><th>Type</th><th>P&L</th><th>Result</th><th>Div</th></tr></thead>
        <tbody id="trade-body">
          {% for t in trades[-15:]|reverse %}
          <tr>
            <td class="text-dim">{{ t.time[5:16] }}</td>
            <td><span class="pill {{ 'pill-long' if t.type=='LONG' else 'pill-short' }}">{{ t.type }}</span></td>
            <td class="{{ 'text-green' if t.pnl >= 0 else 'text-red' }}">{{ '+' if t.pnl >= 0 else '' }}${{ "{:.1f}".format(t.pnl) }}</td>
            <td><span class="pill {{ 'pill-win' if t.result=='WIN' else 'pill-loss' }}">{{ t.result }}</span></td>
            <td>{% if t.get('divergence') %}<span style="color:#f59e0b;">🔥</span>{% else %}<span class="text-dim">—</span>{% endif %}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% endif %}
  </div>
</div>

<script>
let currentTF = '15';
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
    "autosize": true, "symbol": "BITGET:BTCUSDT.P",
    "interval": interval, "timezone": "Etc/UTC",
    "theme": "dark", "style": "1", "locale": "en",
    "backgroundColor": "#0a0e1a", "gridColor": "rgba(30,45,69,0.3)",
    "studies": ["RSI@tv-basicstudies"],
    "support_host": "https://www.tradingview.com"
  });
  wrapper.appendChild(script);
  container.appendChild(wrapper);
}
loadChart('15');

function updateData() {
  fetch('/api/b')
    .then(r => r.json())
    .then(s => {
      const price = s.current_price || 0;
      document.getElementById('price-val').textContent = '$' + price.toLocaleString('en-US', {minimumFractionDigits:2});
      document.getElementById('cycle-time') && (document.querySelector('.cycle-time').textContent = s.last_cycle || '');
      const rsi = s.current_rsi || 50;
      document.getElementById('rsi-num').textContent = rsi;
      const bar = document.getElementById('rsi-bar');
      bar.style.width = rsi + '%';
      bar.style.background = rsi > 70 ? '#ef4444' : rsi < 30 ? '#10b981' : '#3b82f6';
      document.getElementById('bal-val').textContent = '$' + (s.balance||0).toLocaleString('en-US',{minimumFractionDigits:0});
      const pnl = s.pnl_total || 0;
      const pnlEl = document.getElementById('pnl-val');
      pnlEl.textContent = (pnl>=0?'+':'') + '$' + Math.abs(pnl).toFixed(2);
      pnlEl.className = 'stat-value ' + (pnl>=0?'text-green':'text-red');
      const w = s.wins||0, l = s.losses||0;
      document.getElementById('wl-val').textContent = w + 'W · ' + l + 'L';
      document.getElementById('wr-val').textContent = (w+l>0?Math.round(w/(w+l)*100):0) + '%';
      const sig = s.last_signal || '';
      const sigType = document.getElementById('sig-type');
      document.getElementById('sig-text').textContent = sig;
      if (sig.includes('LONG') && !sig.includes('HOLDING')) { sigType.textContent = '▲ LONG'; sigType.className = 'signal-type signal-long'; }
      else if (sig.includes('SHORT') && !sig.includes('HOLDING')) { sigType.textContent = '▼ SHORT'; sigType.className = 'signal-type signal-short'; }
      else { sigType.textContent = '◌ WAIT'; sigType.className = 'signal-type signal-wait'; }
      if (s.position) {
        const pos = s.position;
        if (price > 0) {
          const unreal = pos.type === 'LONG' ? (price - pos.entry) * pos.qty : (pos.entry - price) * pos.qty;
          const unrealEl = document.getElementById('pos-unreal');
          if (unrealEl) { unrealEl.textContent = (unreal>=0?'+':'') + '$' + Math.abs(unreal).toFixed(2); unrealEl.className = unreal>=0?'text-green':'text-red'; }
        }
      }
    }).catch(e => console.log(e));
}
setInterval(updateData, 10000);
updateData();

document.addEventListener('visibilitychange', function() {
  if (!document.hidden) updateData();
});
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

@app.route("/api/b")
def api_b():
    return jsonify(state_b)

@app.route("/b")
def strategy_b():
    s    = state_b
    wins = s.get("wins", 0)
    losses = s.get("losses", 0)
    total  = wins + losses
    return render_template_string(
        DASHBOARD_B,
        balance       = s.get("balance", 10000),
        pnl           = s.get("pnl_total", 0),
        wins          = wins,
        losses        = losses,
        win_rate      = round(wins/total*100) if total > 0 else 0,
        rsi           = s.get("current_rsi", 50),
        divergence    = s.get("last_divergence", False),
        signal        = s.get("last_signal", "Starting..."),
        signal_time   = s.get("last_signal_time", ""),
        last_cycle    = s.get("last_cycle", ""),
        position      = s.get("position"),
        box           = s.get("box"),
        current_price = state.get("current_price", 0),
        trades        = s.get("trades", []),
        errors        = s.get("errors", []),
    )


if __name__ == "__main__":
    print(f"\n🚀 SMC AI Bot starting on port {PORT}")
    print(f"   Dashboard: http://localhost:{PORT}\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)

# =================================================================
# WEBHOOK ENDPOINTS — TradingView Alerts
# =================================================================

from flask import request
import threading

def execute_webhook_trade(signal_type, strategy, price_override=None):
    """Execute trade from TradingView webhook signal."""
    from bot import rt, state, state_b, run_strategy_a, build_daily_box, build_1h_box
    from bot import get_candles, calc_qty, place_order_paper, place_order_live
    from bot import find_4h_sr, detect_divergence, fetch_news, ai_news_score
    from bot import save_state, save_state_b, send_telegram
    from bot import TRADING_MODE, RISK_PER_TRADE
    from config import LEVERAGE
    import os
    from datetime import datetime, timezone
    from collections import deque

    price = price_override or rt.price
    if price <= 0:
        return {"error": "No price available"}, 400

    if strategy == "A":
        # Strategy A webhook trade
        if state["position"]:
            return {"error": "Position already open"}, 400

        candles_4h = get_candles("4H", 500)
        candles_1h = get_candles("1H", 200)
        if not candles_4h or not candles_1h:
            return {"error": "No candle data"}, 400

        box = build_daily_box(candles_4h)
        if not box:
            return {"error": "No box"}, 400
        state["box"] = box

        support, resistance = find_4h_sr(candles_4h, price)
        balance = state["balance"]

        with rt.lock:
            closes_1h = list(rt.closes_1h)
        highs_1h = [c["high"] for c in candles_1h]
        lows_1h  = [c["low"]  for c in candles_1h]
        bull_div, bear_div = detect_divergence(closes_1h, highs_1h[-20:], lows_1h[-20:])

        if signal_type == "SHORT":
            sl = round(resistance * 1.003, 2)
            tp = box["mid"]
            if tp >= price: tp = round(price * 0.99, 2)
            if sl <= price: sl = round(price * 1.01, 2)
            if sl > price * 1.015: sl = round(price * 1.015, 2)
            risk_pct = RISK_PER_TRADE * 2 if bear_div else RISK_PER_TRADE
        else:  # LONG
            sl = round(support * 0.997, 2)
            tp = box["mid"]
            if tp <= price: tp = round(price * 1.01, 2)
            if sl >= price: sl = round(price * 0.99, 2)
            if sl < price * 0.985: sl = round(price * 0.985, 2)
            risk_pct = RISK_PER_TRADE * 2 if bull_div else RISK_PER_TRADE

        qty = calc_qty(balance, risk_pct, price, sl)
        headlines = fetch_news()
        score, summary = ai_news_score(headlines, signal_type, price, box)

        order_id = place_order_paper(signal_type, qty, price, sl, tp) if TRADING_MODE == "PAPER"                    else place_order_live(signal_type, qty, sl, tp)

        if order_id:
            state["position"] = {
                "type": signal_type, "entry": price, "sl": sl, "tp": tp,
                "qty": qty, "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "order_id": order_id, "news_score": score,
                "news_summary": summary, "has_divergence": bear_div,
                "source": "TradingView Webhook"
            }
            state["last_signal"] = signal_type
            state["last_signal_time"] = datetime.now(timezone.utc).strftime("%H:%M UTC")
            save_state()
            send_telegram(
                f"{'🔴' if signal_type=='SHORT' else '🟢'} <b>[A] {signal_type} (TV Webhook)</b>\n"
                f"Entry: ${price:,.2f} | TP: ${tp:,.2f} | SL: ${sl:,.2f}\n"
                f"{'🔥 DIV' if bear_div else 'Normal'}"
            )
            return {"ok": True, "trade": signal_type, "entry": price, "tp": tp, "sl": sl}

    elif strategy == "C":
        # Strategy C — webhook only, uses state_c
        from bot import state_c, save_state_c, finalize_trade_c
        if state_c.get("position"):
            return {"error": "Position C already open"}, 400

        candles_1h = get_candles("1H", 50)
        if not candles_1h:
            return {"error": "No candle data"}, 400

        box = build_1h_box(candles_1h)
        if not box:
            return {"error": "No box"}, 400

        balance = state_c.get("balance", 10000.0)

        if signal_type == "SHORT":
            tp_dist = price - box["mid"]
            if tp_dist <= 0: return {"error": "TP dist invalid for SHORT"}, 400
            sl_dist = tp_dist / 2
            tp = box["mid"]
            sl = round(price + sl_dist, 2)
        else:  # LONG
            tp_dist = box["mid"] - price
            if tp_dist <= 0: return {"error": "TP dist invalid for LONG"}, 400
            sl_dist = tp_dist / 2
            tp = box["mid"]
            sl = round(price - sl_dist, 2)

        qty = calc_qty(balance, RISK_PER_TRADE, price, sl)
        order_id = place_order_paper(signal_type, qty, price, sl, tp) if TRADING_MODE == "PAPER"                    else place_order_live(signal_type, qty, sl, tp)

        if order_id:
            state_c["position"] = {
                "type": signal_type, "entry": price, "sl": sl, "tp": tp,
                "qty": qty, "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "order_id": order_id, "has_divergence": False,
                "source": "TradingView Webhook"
            }
            state_c["last_signal"]      = signal_type
            state_c["last_signal_time"] = datetime.now(timezone.utc).strftime("%H:%M UTC")
            save_state_c()
            send_telegram(
                f"{'🔴' if signal_type=='SHORT' else '🟢'} <b>[C] {signal_type} (TV Webhook)</b>\n"
                f"Entry: ${price:,.2f} | TP: ${tp:,.2f} | SL: ${sl:,.2f}\n"
                f"R/R 2:1"
            )
            return {"ok": True, "trade": signal_type, "entry": price, "tp": tp, "sl": sl}

    return {"error": "Invalid strategy"}, 400


@app.route("/webhook/a", methods=["POST"])
def webhook_a():
    """TradingView webhook for Strategy A."""
    try:
        data = request.get_json(force=True) or {}
        # TradingView sends: {"signal": "LONG"} or {"signal": "SHORT"}
        signal = data.get("signal", "").upper()
        price  = float(data.get("price", 0)) or None

        if signal not in ("LONG", "SHORT"):
            return {"error": f"Invalid signal: {signal}"}, 400

        # Run in background thread to not block webhook response
        def run():
            execute_webhook_trade(signal, "A", price)
        threading.Thread(target=run, daemon=True).start()

        return {"ok": True, "received": signal, "strategy": "A"}
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/webhook/c", methods=["POST"])
def webhook_c():
    """TradingView webhook for Strategy C."""
    try:
        data = request.get_json(force=True) or {}
        signal = data.get("signal", "").upper()
        price  = float(data.get("price", 0)) or None

        if signal not in ("LONG", "SHORT"):
            return {"error": f"Invalid signal: {signal}"}, 400

        def run():
            execute_webhook_trade(signal, "C", price)
        threading.Thread(target=run, daemon=True).start()

        return {"ok": True, "received": signal, "strategy": "C"}
    except Exception as e:
        return {"error": str(e)}, 500
