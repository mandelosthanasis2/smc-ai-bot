"""
main.py — Entry point for Railway deployment
Starts the bot in a background thread + serves the web dashboard
Run locally: python main.py
Deploy: push to Railway (uses Procfile)
"""

from flask import Flask, render_template_string, jsonify
from bot import state, bot_thread
from config import PORT

app = Flask(__name__)

# ── Start bot thread ──────────────────────────────────────────────
bot_thread.start()

# ══════════════════════════════════════════════════════════════════
# DASHBOARD HTML
# ══════════════════════════════════════════════════════════════════

DASHBOARD = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="20">
<title>SMC AI Bot — Bitget</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #060b18;
  color: #c8d8f0;
  font-family: 'Courier New', monospace;
  padding: 16px;
  max-width: 900px;
  margin: 0 auto;
}
h1   { font-size: 16px; color: #f0c040; letter-spacing: 3px; margin-bottom: 4px; }
.sub { font-size: 10px; color: #2a4a6f; letter-spacing: 2px; margin-bottom: 18px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 16px; }
.card { background: #0a1221; border: 1px solid #142038; border-radius: 10px; padding: 12px 14px; }
.lbl  { font-size: 9px; color: #3a5a8f; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 5px; }
.val  { font-size: 18px; font-weight: bold; }
.val.sm { font-size: 13px; }
.green  { color: #00ff88; }
.red    { color: #ff4466; }
.yellow { color: #f0c040; }
.gray   { color: #4a6fa5; }
.purple { color: #a855f7; }
.section { font-size: 10px; color: #3a5a8f; letter-spacing: 3px; text-transform: uppercase; margin: 18px 0 8px; }
.box-zones { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 16px; }
.zone { border-radius: 10px; padding: 12px; text-align: center; }
.zone-short { background: #ff446610; border: 1px solid #ff446625; }
.zone-mid   { background: #f0c04010; border: 1px solid #f0c04025; }
.zone-long  { background: #00ff8810; border: 1px solid #00ff8825; }
.pos-box { background: #0a1221; border: 1px solid #f0c04030; border-radius: 10px; padding: 14px; margin-bottom: 16px; }
.pos-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
.pos-item { display: flex; justify-content: space-between; border-top: 1px solid #0e1f35; padding-top: 6px; }
.news-box { background: #0a1221; border: 1px solid #142038; border-radius: 10px; padding: 14px; margin-bottom: 16px; }
.news-score { display: inline-block; padding: 2px 10px; border-radius: 5px; font-size: 11px; margin-left: 8px; }
.news-score.pos { background: #00ff8820; color: #00ff88; }
.news-score.neg { background: #ff446620; color: #ff4466; }
.news-score.neu { background: #4a6fa520; color: #4a6fa5; }
.news-summary { font-size: 11px; color: #6a8fbf; margin-top: 6px; line-height: 1.5; }
.headlines { margin-top: 8px; }
.hl-item { font-size: 10px; color: #2a4a6f; padding: 3px 0; border-bottom: 1px solid #0a1520; }
table { width: 100%; border-collapse: collapse; font-size: 11px; }
th { background: #0d1829; color: #3a5a8f; text-align: left; padding: 7px 9px; border-bottom: 1px solid #142038; }
td { padding: 7px 9px; border-bottom: 1px solid #0a1520; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 5px; font-size: 10px; }
.pill.long  { background: #00ff8820; color: #00ff88; }
.pill.short { background: #ff446620; color: #ff4466; }
.pill.win   { background: #00ff8820; color: #00ff88; }
.pill.loss  { background: #ff446620; color: #ff4466; }
.errors { background: #1a0808; border: 1px solid #ff446630; border-radius: 8px; padding: 10px; margin-bottom: 14px; }
.err-item { font-size: 10px; color: #ff4466; padding: 2px 0; }
.footer { text-align: center; font-size: 9px; color: #0f2035; letter-spacing: 2px; margin-top: 16px; }
.mode-badge { display: inline-block; padding: 2px 8px; border-radius: 5px; font-size: 10px;
              background: #f0c04020; color: #f0c040; border: 1px solid #f0c04040; }
</style>
</head>
<body>

<h1>⚡ SMC AI TRADING BOT</h1>
<div class="sub">
  BITGET · BTC/USDT PERP · {{ leverage }}x LEVERAGE · AUTO-REFRESH 20s
  <span class="mode-badge">{{ mode }}</span>
</div>

<!-- STATS -->
<div class="grid">
  <div class="card">
    <div class="lbl">Balance</div>
    <div class="val green">${{ "%.2f"|format(balance) }}</div>
  </div>
  <div class="card">
    <div class="lbl">Total P&L</div>
    <div class="val {{ 'green' if pnl >= 0 else 'red' }}">
      {{ '+' if pnl >= 0 else '' }}${{ "%.2f"|format(pnl) }}
    </div>
  </div>
  <div class="card">
    <div class="lbl">Win Rate</div>
    <div class="val yellow">{{ win_rate }}%</div>
  </div>
  <div class="card">
    <div class="lbl">W / L</div>
    <div class="val gray">{{ wins }}W {{ losses }}L</div>
  </div>
  <div class="card">
    <div class="lbl">RSI (1H)</div>
    <div class="val {{ 'red' if rsi > 70 else 'green' if rsi < 30 else 'gray' }}">{{ rsi }}</div>
  </div>
  <div class="card">
    <div class="lbl">Last Cycle</div>
    <div class="val sm gray">{{ last_cycle }}</div>
  </div>
</div>

<!-- SIGNAL -->
<div class="card" style="margin-bottom:16px; border-color: {{ '#00ff8840' if 'LONG' in signal else '#ff446640' if 'SHORT' in signal else '#142038' }}">
  <div class="lbl">Current Signal</div>
  <div class="val sm" style="color: {{ '#00ff88' if 'LONG' in signal and 'block' not in signal.lower() else '#ff4466' if 'SHORT' in signal and 'block' not in signal.lower() else '#4a6fa5' }}">
    {{ signal }}
  </div>
  {% if signal_time %}<div style="font-size:10px; color:#2a4a6f; margin-top:4px;">{{ signal_time }}</div>{% endif %}
</div>

<!-- BOX -->
{% if box %}
<div class="section">📦 Previous Day Box — {{ box.date }}</div>
<div class="box-zones">
  <div class="zone zone-short">
    <div class="lbl" style="color:#ff4466;">SHORT ZONE</div>
    <div class="val red">${{ "%.2f"|format(box.high) }}</div>
    <div style="font-size:9px; color:#ff446680; margin-top:3px;">RSI > 75 + SMC</div>
  </div>
  <div class="zone zone-mid">
    <div class="lbl" style="color:#f0c040;">TP TARGET</div>
    <div class="val yellow">${{ "%.2f"|format(box.mid) }}</div>
    <div style="font-size:9px; color:#f0c04080; margin-top:3px;">Both setups</div>
  </div>
  <div class="zone zone-long">
    <div class="lbl" style="color:#00ff88;">LONG ZONE</div>
    <div class="val green">${{ "%.2f"|format(box.low) }}</div>
    <div style="font-size:9px; color:#00ff8880; margin-top:3px;">RSI < 25 + SMC</div>
  </div>
</div>
<div style="font-size:10px; color:#2a4a6f; margin-bottom:16px;">
  Box size: ${{ "%.2f"|format(box.size) }} &nbsp;·&nbsp; R/R 1:2 &nbsp;·&nbsp; Risk 2%/trade &nbsp;·&nbsp; Current price: <span class="yellow">${{ "%.2f"|format(current_price) }}</span>
</div>
{% endif %}

<!-- OPEN POSITION -->
{% if position %}
<div class="pos-box">
  <div class="lbl">Open Position
    <span class="pill {{ 'long' if position.type == 'LONG' else 'short' }}">{{ position.type }}</span>
  </div>
  <div class="pos-grid">
    <div>
      <div class="pos-item"><span class="gray" style="font-size:10px;">Entry</span> <span>${{ "%.2f"|format(position.entry) }}</span></div>
      <div class="pos-item"><span class="gray" style="font-size:10px;">Take Profit</span> <span class="green">${{ "%.2f"|format(position.tp) }}</span></div>
      <div class="pos-item"><span class="gray" style="font-size:10px;">Stop Loss</span> <span class="red">${{ "%.2f"|format(position.sl) }}</span></div>
    </div>
    <div>
      <div class="pos-item"><span class="gray" style="font-size:10px;">Qty (BTC)</span> <span>{{ position.qty }}</span></div>
      <div class="pos-item"><span class="gray" style="font-size:10px;">AI Score</span>
        <span class="{{ 'green' if position.news_score > 0 else 'red' if position.news_score < 0 else 'gray' }}">{{ position.news_score }}</span>
      </div>
      <div class="pos-item"><span class="gray" style="font-size:10px;">Opened</span> <span style="font-size:10px;">{{ position.time }}</span></div>
    </div>
  </div>
  {% if position.news_summary %}
  <div class="news-summary" style="margin-top:8px;">🤖 {{ position.news_summary }}</div>
  {% endif %}
</div>
{% endif %}

<!-- AI NEWS -->
<div class="news-box">
  <div class="lbl">
    🤖 AI News Analysis
    <span class="news-score {{ 'pos' if news_score > 0 else 'neg' if news_score < 0 else 'neu' }}">
      Score: {{ news_score }}
    </span>
  </div>
  {% if news_summary %}
  <div class="news-summary">{{ news_summary }}</div>
  {% endif %}
  {% if headlines %}
  <div class="headlines">
    {% for h in headlines[:8] %}
    <div class="hl-item">• {{ h }}</div>
    {% endfor %}
  </div>
  {% endif %}
</div>

<!-- ERRORS -->
{% if errors %}
<div class="errors">
  <div class="lbl" style="color:#ff4466;">Recent Errors</div>
  {% for e in errors[-5:] %}
  <div class="err-item">{{ e }}</div>
  {% endfor %}
</div>
{% endif %}

<!-- TRADE HISTORY -->
{% if trades %}
<div class="section">📋 Trade History</div>
<div style="background:#0a1221; border:1px solid #142038; border-radius:10px; overflow:hidden; margin-bottom:16px;">
  <table>
    <tr><th>Time</th><th>Type</th><th>Entry</th><th>Close</th><th>P&L</th><th>Result</th><th>AI</th></tr>
    {% for t in trades[-30:]|reverse %}
    <tr>
      <td class="gray">{{ t.time }}</td>
      <td><span class="pill {{ 'long' if t.type == 'LONG' else 'short' }}">{{ t.type }}</span></td>
      <td>${{ "%.2f"|format(t.entry) }}</td>
      <td>${{ "%.2f"|format(t.close) }}</td>
      <td class="{{ 'green' if t.pnl >= 0 else 'red' }}">{{ '+' if t.pnl >= 0 else '' }}${{ "%.2f"|format(t.pnl) }}</td>
      <td><span class="pill {{ 'win' if t.result == 'WIN' else 'loss' }}">{{ t.result }}</span></td>
      <td class="{{ 'green' if t.news_score > 0 else 'red' if t.news_score < 0 else 'gray' }}">{{ t.news_score }}</td>
    </tr>
    {% endfor %}
  </table>
</div>
{% endif %}

<div class="footer">⚠ PAPER TRADING · NO REAL MONEY · FOR EDUCATIONAL USE · AUTO-REFRESH 20s</div>
</body>
</html>
"""


@app.route("/")
def index():
    s    = state
    wins = s["wins"]
    losses = s["losses"]
    total  = wins + losses
    return render_template_string(
        DASHBOARD,
        mode          = s["mode"],
        leverage      = s.get("leverage", 1),
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
    print(f"   Mode: {state['mode']}")
    print(f"   Dashboard: http://localhost:{PORT}\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)
