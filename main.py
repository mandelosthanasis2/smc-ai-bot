"""
main.py — NRM Bot Dashboard
Multi-user SaaS with login, settings, admin panel
"""

import os
from flask import Flask, render_template_string, jsonify, session, redirect
from bot import state, state_b, state_c, state_d, bot_thread
from config import PORT
from analytics import analytics_bp
from auth import auth_bp, login_required

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "nrmbot-secret-2024")
app.register_blueprint(analytics_bp)
app.register_blueprint(auth_bp)
bot_thread.start()

DASHBOARD = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NRM Bot</title>
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

  .app { display: grid; grid-template-columns: 1fr 360px; min-height: 100vh; height: 100vh; overflow: hidden; }
  .main-col { grid-column: 1; display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
  .side-col  { grid-column: 2; background: var(--bg2); border-left: 1px solid var(--border); display: flex; flex-direction: column; overflow-y: auto; overflow-x: hidden; }

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

  .side-section { padding: 16px; border-bottom: 1px solid var(--border); }
  .side-title {
    font-size: 10px; font-weight: 600; color: var(--text3);
    text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px;
  }

  .price-display { padding: 16px; border-bottom: 1px solid var(--border); }
  .price-symbol { font-size: 11px; color: var(--text3); margin-bottom: 4px; }
  .price-main { font-size: 28px; font-weight: 700; letter-spacing: -1px; }
  .price-change { font-size: 12px; margin-top: 2px; }

  .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .stat-card {
    background: var(--bg3); border: 1px solid var(--border);
    border-radius: 10px; padding: 10px 12px;
  }
  .stat-label { font-size: 9px; color: var(--text3); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }
  .stat-value { font-size: 16px; font-weight: 600; }

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

  .rsi-wrap { margin-top: 8px; }
  .rsi-bar-bg { height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; margin-top: 4px; }
  .rsi-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s ease; }

  .news-score-badge {
    display: inline-block; padding: 2px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 600; margin-left: 6px;
  }
  .news-summary { font-size: 11px; color: var(--text2); margin-top: 6px; line-height: 1.5; }
  .news-hl { font-size: 10px; color: var(--text3); padding: 4px 0; border-bottom: 1px solid var(--border); }

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

  .error-item { font-size: 10px; color: var(--red); padding: 3px 0; }

  .bottombar {
    padding: 10px 20px;
    background: var(--bg2); border-top: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: center;
    font-size: 10px; color: var(--text3);
  }

  @media (max-width: 900px) {
    .app { grid-template-columns: 1fr; grid-template-rows: auto auto; }
    .main-col { grid-column: 1; grid-row: 1; }
    .side-col { grid-column: 1; grid-row: 2; border-left: none; border-top: 1px solid var(--border); max-height: none; }
    .stats-grid { grid-template-columns: 1fr 1fr; }
    .topbar { padding: 10px 14px; flex-wrap: wrap; gap: 6px; }
    .logo { font-size: 14px; }
    .price-main { font-size: 22px; }
  }

  .divider { width: 1px; height: 16px; background: var(--border); }
  .text-green { color: var(--green); }
  .text-red   { color: var(--red);   }
  .text-yellow{ color: var(--yellow);}
  .text-blue  { color: var(--blue);  }
  .text-gray  { color: var(--text2); }
  .text-dim   { color: var(--text3); }

  /* USER NAV */
  .user-nav { display: flex; align-items: center; gap: 8px; }
  .user-nav a { font-size: 11px; padding: 4px 10px; border-radius: 6px; text-decoration: none; border: 1px solid var(--border); color: var(--text2); }
  .user-nav a:hover { color: var(--text); border-color: var(--text2); }
  .user-nav .logout { color: var(--red); border-color: rgba(239,68,68,0.3); }
</style>
</head>
<body>

<div class="app">

  <div class="main-col">

    <div class="topbar">
      <div class="topbar-left">
        <div class="logo">NRM <span>Bot</span></div>
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
        <a href="/" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(59,130,246,0.25);color:#60a5fa;border:1px solid rgba(59,130,246,0.5);text-decoration:none;font-weight:600;">A</a>
        <a href="/b" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(139,92,246,0.15);color:#a855f7;border:1px solid rgba(139,92,246,0.3);text-decoration:none;">B</a>
        <a href="/c" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(249,115,22,0.15);color:#f97316;border:1px solid rgba(249,115,22,0.3);text-decoration:none;">C</a>
        <a href="/d" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(20,184,166,0.15);color:#14b8a6;border:1px solid rgba(20,184,166,0.3);text-decoration:none;">D</a>
        <a href="/analytics" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(245,158,11,0.15);color:#f59e0b;border:1px solid rgba(245,158,11,0.3);text-decoration:none;">📊</a>
        <a href="/settings" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(71,85,105,0.2);color:#94a3b8;border:1px solid #1e2d45;text-decoration:none;">⚙️</a>
        {% if session_role == 'admin' %}
        <a href="/admin" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(129,140,248,0.15);color:#818cf8;border:1px solid rgba(129,140,248,0.3);text-decoration:none;">🛡️</a>
        {% endif %}
        <a href="/logout" style="font-size:11px;padding:4px 10px;border-radius:6px;background:rgba(239,68,68,0.1);color:#ef4444;border:1px solid rgba(239,68,68,0.2);text-decoration:none;">↩</a>
        <div class="pulse"></div>
        <span>LIVE</span>
        <span class="cycle-time" style="margin-left:4px;">{{ last_cycle }}</span>
      </div>
    </div>

    <div class="bottombar" style="border-top:none;border-bottom:1px solid var(--border);">
      <span>⚠ PAPER TRADING · NO REAL MONEY · EDUCATIONAL USE ONLY</span>
      <span>Auto-refresh 10s</span>
    </div>

  </div>

  <div class="side-col">

    <div class="price-display">
      <div class="price-symbol">BTCUSDT · Perpetual</div>
      <div class="price-main text-green" id="price-val">
        ${{ "{:,.2f}".format(current_price) }}
      </div>
      <div class="price-change">
        <span class="badge badge-gray" id="rsi-badge">RSI <span class="rsi-val">{{ rsi }}</span></span>
        <span class="badge badge-paper" id="div-badge" style="margin-left:4px;display:{{ 'inline-block' if divergence else 'none' }};">📊 Divergence!</span>
      </div>
    </div>

    <div class="side-section">
      <div class="side-title">Performance</div>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">Balance</div>
          <div class="stat-value text-green" id="bal-val">${{ "{:,.0f}".format(balance) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Total P&L</div>
          <div class="stat-value {{ 'text-green' if pnl >= 0 else 'text-red' }}" id="pnl-val">{{ '+' if pnl >= 0 else '' }}${{ "{:.2f}".format(pnl) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Win Rate</div>
          <div class="stat-value text-yellow" id="wr-val">{{ win_rate }}%</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">W / L</div>
          <div class="stat-value text-gray" id="wl-val">{{ wins }}W · {{ losses }}L</div>
        </div>
      </div>

      <div class="rsi-wrap">
        <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text3);margin-top:10px;">
          <span>RSI (14)</span><span id="rsi-num">{{ rsi }}</span>
        </div>
        <div class="rsi-bar-bg">
          <div class="rsi-bar-fill" id="rsi-bar" style="width:{{ rsi }}%;background:{{ '#ef4444' if rsi > 70 else '#10b981' if rsi < 30 else '#3b82f6' }};"></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:9px;color:var(--text3);margin-top:2px;">
          <span>0</span><span>30</span><span>70</span><span>100</span>
        </div>
      </div>
    </div>

    <div class="side-section">
      <div class="side-title">Current Signal</div>
      <div class="signal-card">
        {% if 'LONG' in signal and 'block' not in signal.lower() and 'HOLDING' not in signal %}
          <div id="sig-type" class="signal-type signal-long">▲ LONG</div>
        {% elif 'SHORT' in signal and 'block' not in signal.lower() and 'HOLDING' not in signal %}
          <div id="sig-type" class="signal-type signal-short">▼ SHORT</div>
        {% elif 'HOLDING' in signal %}
          <div id="sig-type" class="signal-type signal-wait">◆ {{ position.type if position else 'HOLDING' }}</div>
        {% else %}
          <div id="sig-type" class="signal-type signal-wait">◌ WAIT</div>
        {% endif %}
        <div id="sig-text" class="signal-text">{{ signal }}</div>
        {% if signal_time %}
        <div id="sig-time" style="font-size:10px;color:var(--text3);margin-top:6px;">{{ signal_time }}</div>
        {% endif %}
      </div>
    </div>

    {% if box %}
    <div class="side-section">
      <div class="side-title">Previous Day Box · {{ box.date }}</div>
      <div class="box-levels">
        <div class="level-row level-pdh">
          <div>
            <div class="level-name text-red">PDH · Short Zone</div>
            <div class="level-desc">RSI > 70 → Sell</div>
          </div>
          <div class="level-price text-red" id="box-high">${{ "{:,.2f}".format(box.high) }}</div>
        </div>
        <div class="level-row level-mid">
          <div>
            <div class="level-name text-yellow">MID · Take Profit</div>
            <div class="level-desc">TP for both setups</div>
          </div>
          <div class="level-price text-yellow" id="box-mid">${{ "{:,.2f}".format(box.mid) }}</div>
        </div>
        <div class="level-row level-pdl">
          <div>
            <div class="level-name text-green">PDL · Long Zone</div>
            <div class="level-desc">RSI < 30 → Buy</div>
          </div>
          <div class="level-price text-green" id="box-low">${{ "{:,.2f}".format(box.low) }}</div>
        </div>
      </div>
      <div style="font-size:10px;color:var(--text3);margin-top:8px;display:flex;gap:12px;">
        <span>Size: ${{ "{:,.0f}".format(box.size) }}</span>
        <span>R/R: 1:2</span>
        <span>Risk: 2% (4% w/ div)</span>
      </div>
    </div>
    {% endif %}

    {% if position %}
    <div id="pos-section" class="side-section">
      <div class="side-title">Open Position</div>
      <div class="pos-card">
        <div class="pos-row">
          <span class="pos-key">Type</span>
          <span id="pos-type" class="pill {{ 'pill-long' if position.type == 'LONG' else 'pill-short' }}">{{ position.type }}</span>
        </div>
        <div class="pos-row"><span class="pos-key">Entry</span><span id="pos-entry">${{ "{:,.2f}".format(position.entry) }}</span></div>
        <div class="pos-row"><span class="pos-key">Take Profit</span><span class="text-green" id="pos-tp">${{ "{:,.2f}".format(position.tp) }}</span></div>
        <div class="pos-row"><span class="pos-key">Stop Loss</span><span class="text-red" id="pos-sl">${{ "{:,.2f}".format(position.sl) }}</span></div>
        <div class="pos-row"><span class="pos-key">Size (BTC)</span><span id="pos-qty">{{ position.qty }}</span></div>
        <div class="pos-row"><span class="pos-key">Divergence</span><span id="pos-div">{% if position.get('has_divergence') %}<span class="pill pill-div">🔥 DOUBLE</span>{% else %}Normal{% endif %}</span></div>
        <div class="pos-row"><span class="pos-key">AI Score</span><span id="pos-score" class="{{ 'text-green' if position.news_score > 0 else 'text-red' if position.news_score < 0 else 'text-gray' }}">{{ position.news_score }}</span></div>
        <div class="pos-row"><span class="pos-key">Opened</span><span id="pos-time" class="text-dim">{{ position.time }}</span></div>
        {% if position.news_summary %}
        <div id="pos-news" style="margin-top:8px;font-size:10px;color:var(--text2);line-height:1.5;">📰 {{ position.news_summary[:100] }}</div>
        {% endif %}
      </div>
    </div>
    {% else %}
    <div id="pos-section" class="side-section" style="display:none;"></div>
    {% endif %}

    <div class="side-section">
      <div class="side-title">
        AI News Analysis
        <span id="news-score" class="news-score-badge {{ 'badge-green' if news_score > 0 else 'badge-red' if news_score < 0 else 'badge-gray' }}">
          Score: {{ news_score }}
        </span>
      </div>
      {% if news_summary %}
      <div id="news-summary" class="news-summary">{{ news_summary }}</div>
      {% endif %}
      <div id="news-headlines">
        {% for h in headlines[:6] %}
        <div class="news-hl">• {{ h }}</div>
        {% endfor %}
      </div>
    </div>

    {% if errors %}
    <div id="err-section" class="side-section">
      <div class="side-title" style="color:var(--red);">Recent Errors</div>
      <div id="err-body">
        {% for e in errors[-3:] %}
        <div class="error-item">{{ e }}</div>
        {% endfor %}
      </div>
    </div>
    {% else %}
    <div id="err-section" style="display:none;"></div>
    {% endif %}

    {% if trades %}
    <div id="trade-section" class="side-section">
      <div class="side-title">Trade History</div>
      <table class="trade-table">
        <thead>
          <tr><th>Time</th><th>Type</th><th>P&L</th><th>Result</th><th>Div</th></tr>
        </thead>
        <tbody id="trade-body">
          {% for t in trades[-15:]|reverse %}
          <tr>
            <td class="text-dim">{{ t.time[5:16] }}</td>
            <td><span class="pill {{ 'pill-long' if t.type == 'LONG' else 'pill-short' }}">{{ t.type }}</span></td>
            <td class="{{ 'text-green' if t.pnl >= 0 else 'text-red' }}">{{ '+' if t.pnl >= 0 else '' }}${{ "{:.1f}".format(t.pnl) }}</td>
            <td><span class="pill {{ 'pill-win' if t.result == 'WIN' else 'pill-loss' }}">{{ t.result }}</span></td>
            <td>{% if t.get('divergence') %}<span class="text-yellow">🔥</span>{% else %}<span class="text-dim">—</span>{% endif %}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <div id="trade-section" style="display:none;"></div>
    {% endif %}

  </div>
</div>

<script>
function fmt(n, dec=2) {
  return '$' + Number(n).toLocaleString('en-US', {minimumFractionDigits:dec, maximumFractionDigits:dec});
}

function updateData() {
  fetch('/api')
    .then(r => r.json())
    .then(s => {
      const wins = s.wins || 0, losses = s.losses || 0;
      const total = wins + losses;
      const wr = total > 0 ? Math.round(wins/total*100) : 0;
      const rsi = s.current_rsi || 50;
      const price = s.current_price || 0;

      document.getElementById('price-val').textContent = fmt(price);
      document.getElementById('rsi-badge').textContent = 'RSI ' + rsi;
      document.getElementById('rsi-badge').className = 'badge ' + (rsi > 70 ? 'badge-red' : rsi < 30 ? 'badge-green' : 'badge-gray');
      document.getElementById('rsi-bar').style.width = rsi + '%';
      document.getElementById('rsi-bar').style.background = rsi > 70 ? '#ef4444' : rsi < 30 ? '#10b981' : '#3b82f6';
      document.getElementById('rsi-num').textContent = rsi;
      document.getElementById('div-badge').style.display = s.last_divergence ? 'inline-block' : 'none';

      document.getElementById('bal-val').textContent = fmt(s.balance, 0);
      const pnlEl = document.getElementById('pnl-val');
      pnlEl.textContent = (s.pnl_total >= 0 ? '+' : '') + fmt(s.pnl_total);
      pnlEl.className = 'stat-value ' + (s.pnl_total >= 0 ? 'text-green' : 'text-red');
      document.getElementById('wr-val').textContent = wr + '%';
      document.getElementById('wl-val').textContent = wins + 'W · ' + losses + 'L';

      const sig = s.last_signal || '';
      const sigType = document.getElementById('sig-type');
      document.getElementById('sig-text').textContent = sig;
      if (document.getElementById('sig-time')) document.getElementById('sig-time').textContent = s.last_signal_time || '';
      if (sig.includes('LONG') && !sig.toLowerCase().includes('block') && !sig.includes('HOLDING')) {
        sigType.textContent = '▲ LONG'; sigType.className = 'signal-type signal-long';
      } else if (sig.includes('SHORT') && !sig.toLowerCase().includes('block') && !sig.includes('HOLDING')) {
        sigType.textContent = '▼ SHORT'; sigType.className = 'signal-type signal-short';
      } else if (sig.includes('HOLDING')) {
        sigType.textContent = '◆ HOLDING'; sigType.className = 'signal-type signal-wait';
      } else {
        sigType.textContent = '◌ WAIT'; sigType.className = 'signal-type signal-wait';
      }

      const pos = s.position;
      const posSec = document.getElementById('pos-section');
      if (pos) {
        posSec.style.display = 'block';
        document.getElementById('pos-type').textContent = pos.type;
        document.getElementById('pos-type').className = 'pill ' + (pos.type==='LONG'?'pill-long':'pill-short');
        document.getElementById('pos-entry').textContent = fmt(pos.entry);
        document.getElementById('pos-tp').textContent = fmt(pos.tp);
        document.getElementById('pos-sl').textContent = fmt(pos.sl);
        document.getElementById('pos-qty').textContent = pos.qty;
        document.getElementById('pos-div').innerHTML = pos.has_divergence ? '<span class="pill pill-div">🔥 DOUBLE</span>' : 'Normal';
        document.getElementById('pos-score').textContent = pos.news_score || 0;
        document.getElementById('pos-time').textContent = pos.time || '';
      } else {
        posSec.style.display = 'none';
      }

      document.getElementById('news-score').textContent = 'Score: ' + (s.last_news_score || 0);
      document.getElementById('news-summary').textContent = s.last_news_summary || '';
      if (s.last_news_headlines) {
        document.getElementById('news-headlines').innerHTML = s.last_news_headlines.slice(0,6).map(h => '<div class="news-hl">• ' + h + '</div>').join('');
      }

      const tradeSec = document.getElementById('trade-section');
      if (s.trades && s.trades.length > 0) {
        tradeSec.style.display = 'block';
        document.getElementById('trade-body').innerHTML = [...s.trades].reverse().slice(0,15).map(t =>
          '<tr><td class="text-dim">' + (t.time||'').substring(5,16) + '</td>' +
          '<td><span class="pill ' + (t.type==='LONG'?'pill-long':'pill-short') + '">' + t.type + '</span></td>' +
          '<td class="' + (t.pnl>=0?'text-green':'text-red') + '">' + (t.pnl>=0?'+':'') + fmt(t.pnl,1) + '</td>' +
          '<td><span class="pill ' + (t.result==='WIN'?'pill-win':'pill-loss') + '">' + t.result + '</span></td>' +
          '<td>' + (t.divergence ? '<span class="text-yellow">🔥</span>' : '<span class="text-dim">—</span>') + '</td></tr>'
        ).join('');
      } else {
        tradeSec.style.display = 'none';
      }
    }).catch(err => console.log('Update error:', err));
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


# ═══════════════════════════════════════════════════════════════
# DASHBOARD B
# ═══════════════════════════════════════════════════════════════
DASHBOARD_B = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NRM Bot — Strategy B</title>
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
.bottombar { padding: 10px 20px; background: var(--bg2); border-top: 1px solid var(--border); display: flex; justify-content: space-between; font-size: 10px; color: var(--text3); }
.text-green { color: var(--green); } .text-red { color: var(--red); } .text-yellow { color: var(--yellow); } .text-gray { color: var(--text2); } .text-dim { color: var(--text3); } .text-purple { color: var(--purple); }
.rsi-bar-bg { height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; margin-top: 4px; }
.rsi-bar-fill { height: 100%; border-radius: 3px; }
@media (max-width: 900px) {
  .app { grid-template-columns: 1fr; }
  .side-col { border-left: none; border-top: 1px solid var(--border); }
}
</style>
</head>
<body>
<div class="app">
  <div class="main-col">
    <div class="topbar">
      <div style="display:flex;align-items:center;gap:10px;">
        <div class="logo">NRM <span style="color:var(--purple);">Bot</span></div>
        <span class="badge badge-b">STRATEGY B</span>
        <span class="badge badge-paper">PAPER</span>
        <span class="badge badge-gray">15m · 1H BOX</span>
        <span class="badge badge-gray">R/R 2:1</span>
        {% if position %}<span class="badge" style="background:rgba(139,92,246,0.15);color:#a855f7;border:1px solid rgba(139,92,246,0.3);">{{ position.type }} OPEN</span>{% endif %}
      </div>
      <div class="topbar-right">
        <a href="/" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(59,130,246,0.15);color:#60a5fa;border:1px solid rgba(59,130,246,0.3);text-decoration:none;">A</a>
        <a href="/b" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(139,92,246,0.25);color:#a855f7;border:1px solid rgba(139,92,246,0.5);text-decoration:none;font-weight:600;">B</a>
        <a href="/c" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(249,115,22,0.15);color:#f97316;border:1px solid rgba(249,115,22,0.3);text-decoration:none;">C</a>
        <a href="/d" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(20,184,166,0.15);color:#14b8a6;border:1px solid rgba(20,184,166,0.3);text-decoration:none;">D</a>
        <a href="/settings" style="font-size:11px;padding:4px 10px;border-radius:6px;background:rgba(71,85,105,0.2);color:#94a3b8;border:1px solid #1e2d45;text-decoration:none;">⚙️</a>
        <a href="/logout" style="font-size:11px;padding:4px 10px;border-radius:6px;background:rgba(239,68,68,0.1);color:#ef4444;border:1px solid rgba(239,68,68,0.2);text-decoration:none;">↩</a>
        <div class="pulse"></div>
        <span class="cycle-time">{{ last_cycle }}</span>
      </div>
    </div>
    <div class="bottombar" style="border-top:none;border-bottom:1px solid var(--border);">
      <span>⚠ PAPER TRADING · STRATEGY B · 15m ENTRY · 1H BOX · R/R 2:1</span>
      <span>Auto-refresh 10s</span>
    </div>
  </div>

  <div class="side-col">
    <div class="price-display">
      <div style="font-size:11px;color:var(--text3);margin-bottom:4px;">BTCUSDT · 15m</div>
      <div class="price-main" id="price-val">${{ "{:,.2f}".format(current_price) }}</div>
      <div style="margin-top:6px;">
        <span class="badge badge-gray" id="rsi-badge">RSI {{ rsi }}</span>
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
          <div><div class="level-name text-red">HIGH · Short Zone</div></div>
          <div class="level-price text-red">${{ "{:,.2f}".format(box.high) }}</div>
        </div>
        <div class="level-row level-mid">
          <div><div class="level-name text-yellow">MID · Take Profit</div></div>
          <div class="level-price text-yellow">${{ "{:,.2f}".format(box.mid) }}</div>
        </div>
        <div class="level-row level-pdl">
          <div><div class="level-name text-green">LOW · Long Zone</div></div>
          <div class="level-price text-green">${{ "{:,.2f}".format(box.low) }}</div>
        </div>
      </div>
    </div>
    {% endif %}

    {% if position %}
    <div class="side-section">
      <div class="side-title">Open Position</div>
      <div class="pos-card">
        <div class="pos-row"><span style="color:var(--text2);">Type</span><span class="pill {{ 'pill-long' if position.type=='LONG' else 'pill-short' }}">{{ position.type }}</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Entry</span><span>${{ "{:,.2f}".format(position.entry) }}</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Take Profit</span><span class="text-green">${{ "{:,.2f}".format(position.tp) }}</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Stop Loss</span><span class="text-red">${{ "{:,.2f}".format(position.sl) }}</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Qty</span><span>{{ position.qty }}</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Opened</span><span class="text-dim">{{ position.time }}</span></div>
      </div>
    </div>
    {% endif %}

    {% if trades %}
    <div class="side-section">
      <div class="side-title">Trade History</div>
      <table class="trade-table">
        <thead><tr><th>Time</th><th>Type</th><th>P&L</th><th>Result</th></tr></thead>
        <tbody id="trade-body">
          {% for t in trades[-15:]|reverse %}
          <tr>
            <td class="text-dim">{{ t.time[5:16] }}</td>
            <td><span class="pill {{ 'pill-long' if t.type=='LONG' else 'pill-short' }}">{{ t.type }}</span></td>
            <td class="{{ 'text-green' if t.pnl >= 0 else 'text-red' }}">{{ '+' if t.pnl >= 0 else '' }}${{ "{:.1f}".format(t.pnl) }}</td>
            <td><span class="pill {{ 'pill-win' if t.result=='WIN' else 'pill-loss' }}">{{ t.result }}</span></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% endif %}
  </div>
</div>

<script>
function updateData() {
  fetch('/api/b').then(r => r.json()).then(s => {
    const price = s.current_price || 0;
    document.getElementById('price-val').textContent = '$' + price.toLocaleString('en-US', {minimumFractionDigits:2});
    const rsi = s.current_rsi || 50;
    document.getElementById('rsi-num').textContent = rsi;
    document.getElementById('rsi-badge').textContent = 'RSI ' + rsi;
    document.getElementById('rsi-bar').style.width = rsi + '%';
    document.getElementById('rsi-bar').style.background = rsi > 70 ? '#ef4444' : rsi < 30 ? '#10b981' : '#3b82f6';
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
  }).catch(e => console.log(e));
}
setInterval(updateData, 10000);
updateData();
</script>
</body>
</html>
"""


# ═══════════════════════════════════════════════════════════════
# DASHBOARD C
# ═══════════════════════════════════════════════════════════════
DASHBOARD_C = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NRM Bot — Strategy C</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0a0e1a; --bg2: #111827; --bg3: #1a2235;
  --border: #1e2d45; --text: #e2e8f0; --text2: #94a3b8; --text3: #475569;
  --green: #10b981; --red: #ef4444; --yellow: #f59e0b; --blue: #3b82f6; --orange: #f97316;
}
body { background: var(--bg); color: var(--text); font-family: Inter, sans-serif; }
.app { display: grid; grid-template-columns: 1fr 360px; min-height: 100vh; }
.main-col { display: flex; flex-direction: column; }
.side-col { background: var(--bg2); border-left: 1px solid var(--border); overflow-y: auto; }
.topbar { display: flex; align-items: center; justify-content: space-between; padding: 14px 20px; background: var(--bg2); border-bottom: 1px solid var(--border); }
.logo { font-size: 15px; font-weight: 700; }
.badge { font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: 20px; letter-spacing: 0.5px; }
.badge-c { background: rgba(249,115,22,0.15); color: var(--orange); border: 1px solid rgba(249,115,22,0.3); }
.badge-paper { background: rgba(245,158,11,0.15); color: var(--yellow); border: 1px solid rgba(245,158,11,0.3); }
.badge-gray { background: rgba(71,85,105,0.3); color: var(--text2); border: 1px solid var(--border); }
.topbar-right { font-size: 11px; color: var(--text3); display: flex; align-items: center; gap: 8px; }
.pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--orange); animation: pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
.side-section { padding: 16px; border-bottom: 1px solid var(--border); }
.side-title { font-size: 10px; font-weight: 600; color: var(--text3); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }
.price-display { padding: 16px; border-bottom: 1px solid var(--border); }
.price-main { font-size: 28px; font-weight: 700; color: var(--orange); }
.stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.stat-card { background: var(--bg3); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }
.stat-label { font-size: 9px; color: var(--text3); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }
.stat-value { font-size: 16px; font-weight: 600; }
.signal-card { border-radius: 10px; padding: 14px; border: 1px solid var(--border); background: var(--bg3); }
.signal-type { display: inline-flex; align-items: center; font-size: 13px; font-weight: 700; padding: 5px 14px; border-radius: 8px; margin-bottom: 10px; }
.signal-long  { background: rgba(16,185,129,0.15); color: var(--green);  border: 1px solid rgba(16,185,129,0.3); }
.signal-short { background: rgba(239,68,68,0.15);  color: var(--red);    border: 1px solid rgba(239,68,68,0.3); }
.signal-wait  { background: rgba(71,85,105,0.2);   color: var(--text2);  border: 1px solid var(--border); }
.pos-card { background: var(--bg3); border-radius: 10px; padding: 14px; border: 1px solid rgba(249,115,22,0.3); }
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
.text-green { color: var(--green); } .text-red { color: var(--red); } .text-yellow { color: var(--yellow); }
.text-orange { color: var(--orange); } .text-gray { color: var(--text2); } .text-dim { color: var(--text3); }
.rsi-bar-bg { height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; margin-top: 4px; }
.rsi-bar-fill { height: 100%; border-radius: 3px; }
@media (max-width: 900px) { .app { grid-template-columns: 1fr; } .side-col { border-left: none; border-top: 1px solid var(--border); } }
</style>
</head>
<body>
<div class="app">
  <div class="main-col">
    <div class="topbar">
      <div style="display:flex;align-items:center;gap:10px;">
        <div class="logo">NRM <span style="color:var(--orange);">Bot</span></div>
        <span class="badge badge-c">STRATEGY C</span>
        <span class="badge badge-paper">PAPER</span>
        <span class="badge badge-gray">TV WEBHOOK · R/R 2:1</span>
        {% if position %}<span class="badge" style="background:rgba(249,115,22,0.15);color:#f97316;border:1px solid rgba(249,115,22,0.3);">{{ position.type }} OPEN</span>{% endif %}
      </div>
      <div class="topbar-right">
        <a href="/" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(59,130,246,0.15);color:#60a5fa;border:1px solid rgba(59,130,246,0.3);text-decoration:none;">A</a>
        <a href="/b" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(139,92,246,0.15);color:#a855f7;border:1px solid rgba(139,92,246,0.3);text-decoration:none;">B</a>
        <a href="/c" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(249,115,22,0.25);color:#f97316;border:1px solid rgba(249,115,22,0.5);text-decoration:none;font-weight:600;">C</a>
        <a href="/d" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(20,184,166,0.15);color:#14b8a6;border:1px solid rgba(20,184,166,0.3);text-decoration:none;">D</a>
        <a href="/settings" style="font-size:11px;padding:4px 10px;border-radius:6px;background:rgba(71,85,105,0.2);color:#94a3b8;border:1px solid #1e2d45;text-decoration:none;">⚙️</a>
        <a href="/logout" style="font-size:11px;padding:4px 10px;border-radius:6px;background:rgba(239,68,68,0.1);color:#ef4444;border:1px solid rgba(239,68,68,0.2);text-decoration:none;">↩</a>
        <div class="pulse"></div>
        <span id="cycle-time">{{ last_cycle }}</span>
      </div>
    </div>
  </div>

  <div class="side-col">
    <div class="price-display">
      <div style="font-size:11px;color:var(--text3);margin-bottom:4px;">BTCUSDT · 15m</div>
      <div class="price-main" id="price-val">${{ "{:,.2f}".format(current_price) }}</div>
      <div style="margin-top:6px;">
        <span class="badge badge-gray" id="rsi-badge">RSI {{ rsi }}</span>
        <span style="background:rgba(249,115,22,0.15);color:var(--orange);border:0.5px solid rgba(249,115,22,0.3);padding:3px 8px;border-radius:5px;font-size:10px;font-weight:600;margin-left:6px;">⚡ TradingView</span>
      </div>
    </div>

    <div class="side-section">
      <div class="side-title">Performance</div>
      <div class="stats-grid">
        <div class="stat-card"><div class="stat-label">Balance</div><div class="stat-value text-orange" id="bal-val">${{ "{:,.0f}".format(balance) }}</div></div>
        <div class="stat-card"><div class="stat-label">Total P&L</div><div class="stat-value {{ 'text-green' if pnl >= 0 else 'text-red' }}" id="pnl-val">{{ '+' if pnl >= 0 else '' }}${{ "{:.2f}".format(pnl) }}</div></div>
        <div class="stat-card"><div class="stat-label">Win Rate</div><div class="stat-value text-yellow" id="wr-val">{{ win_rate }}%</div></div>
        <div class="stat-card"><div class="stat-label">W / L</div><div class="stat-value text-gray" id="wl-val">{{ wins }}W · {{ losses }}L</div></div>
      </div>
    </div>

    <div class="side-section">
      <div class="side-title">Current Signal</div>
      <div class="signal-card">
        {% if 'LONG' in signal and 'HOLDING' not in signal %}
          <div id="sig-type" class="signal-type signal-long">▲ LONG</div>
        {% elif 'SHORT' in signal and 'HOLDING' not in signal %}
          <div id="sig-type" class="signal-type signal-short">▼ SHORT</div>
        {% else %}
          <div id="sig-type" class="signal-type signal-wait">⚡ WAITING WEBHOOK</div>
        {% endif %}
        <div id="sig-text" style="font-size:11px;color:var(--text2);">{{ signal }}</div>
        <div id="sig-time" style="font-size:10px;color:var(--text3);margin-top:4px;">{{ signal_time }}</div>
      </div>
    </div>

    {% if position %}
    <div class="side-section">
      <div class="side-title">Open Position</div>
      <div class="pos-card">
        <div class="pos-row"><span style="color:var(--text2);">Type</span><span class="pill {{ 'pill-long' if position.type=='LONG' else 'pill-short' }}">{{ position.type }}</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Entry</span><span>${{ "{:,.2f}".format(position.entry) }}</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Take Profit</span><span class="text-green">${{ "{:,.2f}".format(position.tp) }}</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Stop Loss</span><span class="text-red">${{ "{:,.2f}".format(position.sl) }}</span></div>
        <div class="pos-row"><span style="color:var(--text2);">Opened</span><span class="text-dim">{{ position.time }}</span></div>
      </div>
    </div>
    {% endif %}

    {% if trades %}
    <div class="side-section">
      <div class="side-title">Trade History</div>
      <table class="trade-table">
        <thead><tr><th>Time</th><th>Type</th><th>P&L</th><th>Result</th></tr></thead>
        <tbody>
          {% for t in trades[-15:]|reverse %}
          <tr>
            <td class="text-dim">{{ t.time[5:16] }}</td>
            <td><span class="pill {{ 'pill-long' if t.type=='LONG' else 'pill-short' }}">{{ t.type }}</span></td>
            <td class="{{ 'text-green' if t.pnl >= 0 else 'text-red' }}">{{ '+' if t.pnl >= 0 else '' }}${{ "{:.1f}".format(t.pnl) }}</td>
            <td><span class="pill {{ 'pill-win' if t.result=='WIN' else 'pill-loss' }}">{{ t.result }}</span></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% endif %}
  </div>
</div>

<script>
function updateData() {
  fetch('/api/c').then(r => r.json()).then(s => {
    const price = s.current_price || 0;
    document.getElementById('price-val').textContent = '$' + price.toLocaleString('en-US',{minimumFractionDigits:2});
    document.getElementById('rsi-badge').textContent = 'RSI ' + (s.current_rsi||50);
    document.getElementById('bal-val').textContent = '$' + (s.balance||0).toLocaleString('en-US',{minimumFractionDigits:0});
    const pnl = s.pnl_total||0;
    const pnlEl = document.getElementById('pnl-val');
    pnlEl.textContent = (pnl>=0?'+':'') + '$' + Math.abs(pnl).toFixed(2);
    pnlEl.className = 'stat-value '+(pnl>=0?'text-green':'text-red');
    const w=s.wins||0, l=s.losses||0;
    document.getElementById('wl-val').textContent = w+'W · '+l+'L';
    document.getElementById('wr-val').textContent = (w+l>0?Math.round(w/(w+l)*100):0)+'%';
  }).catch(e => console.log(e));
}
setInterval(updateData, 10000);
updateData();
</script>
</body>
</html>
"""


# ═══════════════════════════════════════════════════════════════
# DASHBOARD D
# ═══════════════════════════════════════════════════════════════
DASHBOARD_D = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NRM Bot — Strategy D</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0a0e1a; --bg2: #111827; --bg3: #1a2235;
  --border: #1e2d45; --text: #e2e8f0; --text2: #94a3b8; --text3: #475569;
  --green: #10b981; --red: #ef4444; --yellow: #f59e0b; --blue: #3b82f6;
  --purple: #8b5cf6; --teal: #14b8a6;
}
body { background: var(--bg); color: var(--text); font-family: Inter, sans-serif; }
.app { display: grid; grid-template-columns: 1fr 360px; min-height: 100vh; }
.main-col { display: flex; flex-direction: column; }
.side-col { background: var(--bg2); border-left: 1px solid var(--border); overflow-y: auto; }
.topbar { display: flex; align-items: center; justify-content: space-between; padding: 14px 20px; background: var(--bg2); border-bottom: 1px solid var(--border); }
.logo { font-size: 15px; font-weight: 700; }
.badge { font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: 20px; letter-spacing: 0.5px; }
.badge-d { background: rgba(20,184,166,0.15); color: var(--teal); border: 1px solid rgba(20,184,166,0.3); }
.badge-paper { background: rgba(245,158,11,0.15); color: var(--yellow); border: 1px solid rgba(245,158,11,0.3); }
.badge-tv { background: rgba(59,130,246,0.15); color: var(--blue); border: 1px solid rgba(59,130,246,0.3); }
.topbar-right { font-size: 11px; color: var(--text3); display: flex; align-items: center; gap: 8px; }
.pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--teal); animation: pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
.side-section { padding: 16px; border-bottom: 1px solid var(--border); }
.side-title { font-size: 10px; font-weight: 600; color: var(--text3); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }
.price-display { padding: 16px; border-bottom: 1px solid var(--border); }
.price-main { font-size: 28px; font-weight: 700; color: var(--teal); }
.stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.stat-card { background: var(--bg3); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }
.stat-label { font-size: 9px; color: var(--text3); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }
.stat-value { font-size: 18px; font-weight: 700; }
.signal-box { padding: 14px 16px; background: var(--bg3); border-radius: 10px; border: 1px solid var(--border); }
.signal-type { font-size: 13px; font-weight: 700; display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.pos-card { background: var(--bg3); border-radius: 10px; border: 1px solid var(--border); padding: 14px; }
.pos-row { display: flex; justify-content: space-between; font-size: 11px; padding: 3px 0; }
.pos-label { color: var(--text3); }
.pos-val { font-weight: 600; }
.trade-row { display: grid; grid-template-columns: 1fr auto auto auto; gap: 8px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 11px; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 9px; font-weight: 700; }
.pill-long { background: rgba(16,185,129,0.15); color: var(--green); }
.pill-short { background: rgba(239,68,68,0.15); color: var(--red); }
.pill-win { background: rgba(16,185,129,0.15); color: var(--green); }
.pill-loss { background: rgba(239,68,68,0.15); color: var(--red); }
@media (max-width: 900px) { .app { grid-template-columns: 1fr; } .side-col { border-left: none; border-top: 1px solid var(--border); } }
</style>
</head>
<body>
<div class="app">
  <div class="main-col">
    <div class="topbar">
      <div style="display:flex;align-items:center;gap:10px;">
        <div class="logo">NRM <span style="color:var(--teal);">Bot</span></div>
        <span class="badge badge-d">STRATEGY D</span>
        <span class="badge badge-paper">PAPER</span>
        <span class="badge badge-tv">TV WEBHOOK</span>
        <span style="background:rgba(20,184,166,0.15);color:var(--teal);border:1px solid rgba(20,184,166,0.3);font-size:9px;padding:2px 6px;border-radius:4px;font-weight:700;">R/R 2:1 / 3:1</span>
      </div>
      <div class="topbar-right">
        <a href="/" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(59,130,246,0.15);color:#60a5fa;border:1px solid rgba(59,130,246,0.3);text-decoration:none;">A</a>
        <a href="/b" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(139,92,246,0.15);color:#a855f7;border:1px solid rgba(139,92,246,0.3);text-decoration:none;">B</a>
        <a href="/c" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(249,115,22,0.15);color:#f97316;border:1px solid rgba(249,115,22,0.3);text-decoration:none;">C</a>
        <a href="/d" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(20,184,166,0.25);color:#14b8a6;border:1px solid rgba(20,184,166,0.5);text-decoration:none;font-weight:700;">D</a>
        <a href="/analytics" style="font-size:11px;padding:4px 12px;border-radius:6px;background:rgba(245,158,11,0.15);color:#f59e0b;border:1px solid rgba(245,158,11,0.3);text-decoration:none;">📊</a>
        <a href="/settings" style="font-size:11px;padding:4px 10px;border-radius:6px;background:rgba(71,85,105,0.2);color:#94a3b8;border:1px solid #1e2d45;text-decoration:none;">⚙️</a>
        <a href="/logout" style="font-size:11px;padding:4px 10px;border-radius:6px;background:rgba(239,68,68,0.1);color:#ef4444;border:1px solid rgba(239,68,68,0.2);text-decoration:none;">↩</a>
        <div class="pulse"></div>
        <span id="live-time"></span>
      </div>
    </div>
  </div>

  <div class="side-col">
    <div class="price-display">
      <div style="font-size:10px;color:var(--text3);margin-bottom:4px;">BTCUSDT · Perpetual</div>
      <div class="price-main" id="live-price">${{ "%.2f"|format(current_price) }}</div>
    </div>

    <div class="side-section">
      <div class="side-title">Performance</div>
      <div class="stats-grid">
        <div class="stat-card"><div class="stat-label">Balance</div><div class="stat-value" style="color:var(--teal)">${{ "%.0f"|format(balance) }}</div></div>
        <div class="stat-card"><div class="stat-label">Total P&L</div><div class="stat-value" style="color:{% if pnl >= 0 %}var(--green){% else %}var(--red){% endif %}">{{ '+' if pnl >= 0 else '' }}${{ "%.2f"|format(pnl) }}</div></div>
        <div class="stat-card"><div class="stat-label">Win Rate</div><div class="stat-value" style="color:var(--teal)">{{ win_rate }}%</div></div>
        <div class="stat-card"><div class="stat-label">W / L</div><div class="stat-value">{{ wins }}W · {{ losses }}L</div></div>
      </div>
    </div>

    <div class="side-section">
      <div class="side-title">Current Signal</div>
      <div class="signal-box">
        {% if position %}
          <div class="signal-type" style="color:{% if position.type=='LONG' %}var(--green){% else %}var(--red){% endif %}">
            {{ position.type }}
          </div>
          <div style="font-size:10px;color:var(--text2);">{{ position.time }}</div>
          {% if position.has_confluence %}
          <div style="margin-top:6px;"><span class="badge" style="background:rgba(20,184,166,0.15);color:var(--teal);border:1px solid rgba(20,184,166,0.3);">🔥 Strong Confluence</span></div>
          {% endif %}
        {% else %}
          <div class="signal-type" style="color:var(--text2)">○ WAIT</div>
          <div style="font-size:10px;color:var(--text2);">{{ signal }}</div>
          {% if signal_time %}<div style="font-size:10px;color:var(--text3);">{{ signal_time }}</div>{% endif %}
        {% endif %}
      </div>
    </div>

    {% if position %}
    <div class="side-section">
      <div class="side-title">Open Position</div>
      <div class="pos-card">
        <div class="pos-row"><span class="pos-label">Type</span><span class="pos-val" style="color:{% if position.type=='LONG' %}var(--green){% else %}var(--red){% endif %}">{{ position.type }}</span></div>
        <div class="pos-row"><span class="pos-label">Entry</span><span class="pos-val">${{ "%.2f"|format(position.entry) }}</span></div>
        <div class="pos-row"><span class="pos-label">TP1 (2:1)</span><span class="pos-val" style="color:var(--green)">${{ "%.2f"|format(position.tp1) }}</span></div>
        <div class="pos-row"><span class="pos-label">TP2 (3:1)</span><span class="pos-val" style="color:var(--teal)">${{ "%.2f"|format(position.tp2) }}</span></div>
        <div class="pos-row"><span class="pos-label">Stop Loss</span><span class="pos-val" style="color:var(--red)">${{ "%.2f"|format(position.sl) }}</span></div>
        <div class="pos-row"><span class="pos-label">Qty</span><span class="pos-val">{{ position.qty }}</span></div>
        {% if position.phase1_done %}
        <div style="margin-top:8px;padding:6px;background:rgba(16,185,129,0.1);border-radius:6px;font-size:10px;color:var(--green);text-align:center;">✓ TP1 HIT — Riding to TP2</div>
        {% endif %}
      </div>
    </div>
    {% endif %}

    <div class="side-section">
      <div class="side-title">Trade History</div>
      {% if trades %}
        {% for t in trades|reverse %}{% if loop.index <= 15 %}
        <div class="trade-row">
          <div>
            <span class="pill pill-{{ t.type|lower }}">{{ t.type }}</span>
            <div style="font-size:9px;color:var(--text3);margin-top:2px;">{{ t.time[5:16] if t.time else '' }}</div>
          </div>
          <div style="font-size:10px;color:var(--text2)">{{ t.note or '—' }}</div>
          <div style="font-size:11px;font-weight:600;color:{% if t.pnl >= 0 %}var(--green){% else %}var(--red){% endif %}">{{ '+' if t.pnl >= 0 else '' }}${{ "%.1f"|format(t.pnl) }}</div>
          <span class="pill pill-{{ t.result|lower }}">{{ t.result }}</span>
        </div>
        {% endif %}{% endfor %}
      {% else %}
        <div style="color:var(--text3);font-size:11px;">No trades yet</div>
      {% endif %}
    </div>
  </div>
</div>

<script>
setInterval(() => {
  document.getElementById('live-time').textContent = new Date().toUTCString().slice(17,25) + ' UTC';
}, 1000);
setInterval(() => {
  fetch('/api/d').then(r => r.json()).then(d => {
    const price = d.current_price || 0;
    if (price > 0) document.getElementById('live-price').textContent = '$' + price.toLocaleString('en-US', {minimumFractionDigits:2});
  });
}, 10000);
</script>
</body>
</html>
"""


# =================================================================
# ROUTES
# =================================================================

@app.route("/")
@login_required
def index():
    s = state
    wins = s["wins"]
    losses = s["losses"]
    total = wins + losses
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
        session_role  = session.get("role"),
    )

@app.route("/api")
@login_required
def api():
    return jsonify(state)

@app.route("/api/b")
@login_required
def api_b():
    return jsonify(state_b)

@app.route("/api/c")
@login_required
def api_c():
    return jsonify(state_c)

@app.route("/api/d")
@login_required
def api_d():
    return jsonify(state_d)

@app.route("/b")
@login_required
def strategy_b():
    s = state_b
    wins = s.get("wins", 0)
    losses = s.get("losses", 0)
    total = wins + losses
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

@app.route("/c")
@login_required
def strategy_c():
    s = state_c
    wins = s.get("wins", 0)
    losses = s.get("losses", 0)
    total = wins + losses
    return render_template_string(
        DASHBOARD_C,
        balance       = s.get("balance", 10000),
        pnl           = s.get("pnl_total", 0),
        wins          = wins,
        losses        = losses,
        win_rate      = round(wins/total*100) if total > 0 else 0,
        rsi           = s.get("current_rsi", 50),
        divergence    = s.get("last_divergence", False),
        signal        = s.get("last_signal", "Waiting for TradingView signal..."),
        signal_time   = s.get("last_signal_time", ""),
        last_cycle    = s.get("last_cycle", ""),
        position      = s.get("position"),
        box           = s.get("box"),
        current_price = s.get("current_price", 0),
        trades        = s.get("trades", []),
        errors        = s.get("errors", []),
    )

@app.route("/d")
@login_required
def strategy_d():
    s = state_d
    wins = s.get("wins", 0)
    losses = s.get("losses", 0)
    total = wins + losses
    return render_template_string(
        DASHBOARD_D,
        balance       = s.get("balance", 10000),
        pnl           = s.get("pnl_total", 0),
        wins          = wins,
        losses        = losses,
        win_rate      = round(wins/total*100) if total > 0 else 0,
        signal        = s.get("last_signal", "Waiting for TradingView signal..."),
        signal_time   = s.get("last_signal_time", ""),
        last_cycle    = s.get("last_cycle", ""),
        position      = s.get("position"),
        current_price = s.get("current_price", 0),
        trades        = s.get("trades", []),
        errors        = s.get("errors", []),
    )


# =================================================================
# WEBHOOKS — TradingView Alerts (δεν χρειάζονται login)
# =================================================================

from flask import request
import threading

def execute_webhook_trade_d(signal_type, price_override=None, data=None):
    from bot import rt, state_d, save_state_d, send_telegram, calc_qty, place_order_paper, place_order_live
    from bot import TRADING_MODE, RISK_PER_TRADE
    from datetime import datetime, timezone
    if data is None: data = {}

    price = price_override or rt.price
    if price <= 0:
        return {"error": "No price available"}, 400
    if state_d["position"]:
        return {"error": "Position already open for Strategy D"}, 400

    is_long = signal_type == "LONG"
    try:
        sl  = float(data.get("sl",  0)) or (price * 0.985 if is_long else price * 1.015)
        tp1 = float(data.get("tp1", 0)) or (price + abs(price - sl) * 2.0 if is_long else price - abs(sl - price) * 2.0)
        tp2 = float(data.get("tp2", 0)) or (price + abs(price - sl) * 3.0 if is_long else price - abs(sl - price) * 3.0)
    except Exception:
        sl  = price * 0.985 if is_long else price * 1.015
        sl_dist = abs(price - sl)
        tp1 = price + sl_dist * 2.0 if is_long else price - sl_dist * 2.0
        tp2 = price + sl_dist * 3.0 if is_long else price - sl_dist * 3.0

    sl = round(sl, 2); tp1 = round(tp1, 2); tp2 = round(tp2, 2)
    confluence = data.get("confluence", "normal") == "strong"
    risk_pct = RISK_PER_TRADE * 2 if confluence else RISK_PER_TRADE
    qty = calc_qty(state_d["balance"], risk_pct, price, sl)
    order_id = place_order_paper(signal_type, qty, price, sl, tp1) if TRADING_MODE == "PAPER" \
               else place_order_live(signal_type, qty, sl, tp1)

    if order_id:
        state_d["position"] = {
            "type": signal_type, "entry": price, "sl": sl,
            "tp1": tp1, "tp2": tp2, "qty": qty,
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "order_id": order_id, "has_confluence": confluence,
            "phase1_done": False, "source": "TradingView OB+FVG+CHoCH",
        }
        state_d["last_signal"] = signal_type
        state_d["last_signal_time"] = datetime.now(timezone.utc).strftime("%H:%M UTC")
        save_state_d()
        send_telegram(
            f"{'🔴' if signal_type=='SHORT' else '🟢'} <b>[D] {signal_type} (OB+FVG+CHoCH)</b>\n"
            f"Entry: ${price:,.2f} | TP1: ${tp1:,.2f} | TP2: ${tp2:,.2f} | SL: ${sl:,.2f}\n"
            f"{'🔥 Strong Confluence' if confluence else 'Normal'}"
        )
        return {"ok": True, "trade": signal_type, "entry": price, "tp1": tp1, "tp2": tp2, "sl": sl}
    return {"error": "Order failed"}, 500


def execute_webhook_trade_a(signal_type, price_override=None, data=None):
    from bot import rt, state, build_daily_box, get_candles, calc_qty
    from bot import place_order_paper, place_order_live, find_4h_sr, detect_divergence
    from bot import fetch_news, ai_news_score, save_state, send_telegram
    from bot import TRADING_MODE, RISK_PER_TRADE
    from datetime import datetime, timezone
    if data is None: data = {}

    price = price_override or rt.price
    if price <= 0:
        return {"error": "No price available"}, 400
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
    else:
        sl = round(support * 0.997, 2)
        tp = box["mid"]
        if tp <= price: tp = round(price * 1.01, 2)
        if sl >= price: sl = round(price * 0.99, 2)
        if sl < price * 0.985: sl = round(price * 0.985, 2)
        risk_pct = RISK_PER_TRADE * 2 if bull_div else RISK_PER_TRADE

    qty = calc_qty(balance, risk_pct, price, sl)
    headlines = fetch_news()
    score, summary = ai_news_score(headlines, signal_type, price, box)
    order_id = place_order_paper(signal_type, qty, price, sl, tp) if TRADING_MODE == "PAPER" \
               else place_order_live(signal_type, qty, sl, tp)

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
    return {"error": "Order failed"}, 500


def execute_webhook_trade_c(signal_type, price_override=None, data=None):
    from bot import rt, state_c, save_state_c, send_telegram, calc_qty
    from bot import place_order_paper, place_order_live, get_candles, build_1h_box
    from bot import TRADING_MODE, RISK_PER_TRADE
    from datetime import datetime, timezone
    import logging
    log = logging.getLogger(__name__)
    if data is None: data = {}

    price = price_override or rt.price
    if price <= 0:
        return {"error": "No price available"}, 400
    if state_c.get("position"):
        return {"error": "Position C already open"}, 400

    tp = float(data.get("tp", 0)) if data else 0
    sl = float(data.get("sl", 0)) if data else 0

    if not tp or not sl:
        candles_1h = get_candles("1H", 50)
        if not candles_1h:
            return {"error": "No candle data"}, 400
        box = build_1h_box(candles_1h)
        if not box:
            return {"error": "No box"}, 400
        if signal_type == "SHORT":
            tp = box["mid"]
            sl = round(price + (price - box["mid"]) / 2, 2)
        else:
            tp = box["mid"]
            sl = round(price - (box["mid"] - price) / 2, 2)
    else:
        tp = round(tp, 2)
        sl = round(sl, 2)

    if signal_type == "SHORT" and (tp >= price or sl <= price):
        return {"error": f"Invalid SHORT levels: entry={price} tp={tp} sl={sl}"}, 400
    if signal_type == "LONG" and (tp <= price or sl >= price):
        return {"error": f"Invalid LONG levels: entry={price} tp={tp} sl={sl}"}, 400

    balance = state_c.get("balance", 10000.0)
    qty = calc_qty(balance, RISK_PER_TRADE, price, sl)
    order_id = place_order_paper(signal_type, qty, price, sl, tp) if TRADING_MODE == "PAPER" \
               else place_order_live(signal_type, qty, sl, tp)

    if order_id:
        rr = round(abs(tp - price) / abs(sl - price), 2)
        state_c["position"] = {
            "type": signal_type, "entry": price, "sl": sl, "tp": tp,
            "qty": qty, "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "order_id": order_id, "has_divergence": False,
            "source": "TradingView Webhook"
        }
        state_c["last_signal"] = signal_type
        state_c["last_signal_time"] = datetime.now(timezone.utc).strftime("%H:%M UTC")
        save_state_c()
        log.info(f"[C] {signal_type} opened: entry={price} tp={tp} sl={sl} R/R={rr}")
        send_telegram(
            f"{'🔴' if signal_type=='SHORT' else '🟢'} <b>[C] {signal_type} (TV Webhook)</b>\n"
            f"Entry: ${price:,.2f} | TP: ${tp:,.2f} | SL: ${sl:,.2f}\nR/R: {rr}:1"
        )
        return {"ok": True, "trade": signal_type, "entry": price, "tp": tp, "sl": sl, "rr": rr}
    return {"error": "Order failed"}, 500


@app.route("/webhook/a", methods=["POST"])
def webhook_a():
    try:
        data = request.get_json(force=True) or {}
        signal = data.get("signal", "").upper()
        price  = float(data.get("price", 0)) or None
        if signal not in ("LONG", "SHORT"):
            return {"error": f"Invalid signal: {signal}"}, 400
        threading.Thread(target=lambda: execute_webhook_trade_a(signal, price, data), daemon=True).start()
        return {"ok": True, "received": signal, "strategy": "A"}
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/webhook/c", methods=["POST"])
def webhook_c():
    try:
        data = request.get_json(force=True) or {}
        signal = data.get("signal", "").upper()
        price  = float(data.get("price", 0)) or None
        if signal not in ("LONG", "SHORT"):
            return {"error": f"Invalid signal: {signal}"}, 400
        threading.Thread(target=lambda: execute_webhook_trade_c(signal, price, data), daemon=True).start()
        return {"ok": True, "received": signal, "strategy": "C"}
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/webhook/d", methods=["POST"])
def webhook_d():
    try:
        data   = request.get_json(force=True) or {}
        signal = data.get("signal", "").upper()
        price  = float(data.get("price", 0)) or None
        if signal not in ("LONG", "SHORT"):
            return {"error": f"Invalid signal: {signal}"}, 400
        threading.Thread(target=lambda: execute_webhook_trade_d(signal, price, data), daemon=True).start()
        return {"ok": True, "received": signal, "strategy": "D"}
    except Exception as e:
        return {"error": str(e)}, 500


if __name__ == "__main__":
    print(f"\n🚀 NRM Bot starting on port {PORT}")
    print(f"   Dashboard: http://localhost:{PORT}\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)
