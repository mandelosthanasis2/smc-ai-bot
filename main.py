"""
main.py — NRM Bot v2
New design: sidebar, cards, mobile-first, no TradingView
"""

import os
import threading
from flask import Flask, render_template_string, jsonify, session
from bot import state, state_b, state_c, state_d, state_cm, state_smc, bot_thread
from bot import snapshot_state, state_lock, state_lock_b, state_lock_c, state_lock_d, state_lock_smc
from config import PORT
from analytics import analytics_bp
from auth import auth_bp, login_required
from analysis_agent import start_scheduler

COACH_HTML = """
<!DOCTYPE html>
<html lang="el">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Trading Coach — NRM Bot</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }

  body {
    background:#0d0f14;
    color:#e2e8f0;
    font-family:-apple-system,BlinkMacSystemFont,'DM Mono',monospace;
    height:100dvh;
    display:flex;
    flex-direction:column;
    overflow:hidden;
  }

  /* ── Header ── */
  .hd {
    display:flex; align-items:center; justify-content:space-between;
    padding:12px 16px;
    background:#111318;
    border-bottom:1px solid rgba(255,255,255,.07);
    flex-shrink:0;
  }
  .hd-left { display:flex; align-items:center; gap:10px; }
  .hd-icon { font-size:22px; }
  .hd-title { font-size:14px; font-weight:700; color:#e2e8f0; }
  .hd-sub { font-size:10px; color:#64748b; margin-top:1px; }
  .reset-btn {
    font-size:11px; background:rgba(255,255,255,.06); color:#94a3b8;
    border:1px solid rgba(255,255,255,.1); padding:6px 12px;
    border-radius:20px; cursor:pointer; font-family:inherit;
    -webkit-tap-highlight-color:transparent;
  }

  /* ── Chat area ── */
  .chat-wrap {
    flex:1; overflow-y:auto; overflow-x:hidden;
    padding:16px; display:flex; flex-direction:column; gap:12px;
    -webkit-overflow-scrolling:touch;
  }

  /* ── Messages ── */
  .msg {
    max-width:88%; line-height:1.65; font-size:13px;
    word-break:break-word;
    animation:fadeIn .2s ease;
  }
  @keyframes fadeIn { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:none} }

  .msg.user {
    align-self:flex-end;
    background:linear-gradient(135deg,#4f46e5,#6d28d9);
    color:#fff;
    padding:10px 14px;
    border-radius:18px 18px 4px 18px;
    box-shadow:0 2px 8px rgba(79,70,229,.3);
  }
  .msg.bot {
    align-self:flex-start;
    background:#1a1f2e;
    color:#e2e8f0;
    padding:12px 14px;
    border-radius:4px 18px 18px 18px;
    border:1px solid rgba(255,255,255,.07);
    white-space:pre-wrap;
  }
  .msg.loading {
    color:#64748b; font-style:italic; background:transparent;
    border:none; padding:4px 0;
  }

  /* ── Suggestions ── */
  .sug-wrap {
    flex-shrink:0;
    padding:10px 16px;
    display:flex; gap:8px; overflow-x:auto;
    border-top:1px solid rgba(255,255,255,.05);
    -webkit-overflow-scrolling:touch;
    scrollbar-width:none;
  }
  .sug-wrap::-webkit-scrollbar { display:none; }
  .sug-btn {
    flex-shrink:0;
    font-size:11px; background:rgba(167,139,250,.1); color:#a78bfa;
    border:1px solid rgba(167,139,250,.25); padding:7px 14px;
    border-radius:20px; cursor:pointer; font-family:inherit;
    white-space:nowrap;
    -webkit-tap-highlight-color:transparent;
    transition:background .15s;
  }
  .sug-btn:active { background:rgba(167,139,250,.25); }

  /* ── Input bar ── */
  .input-wrap {
    flex-shrink:0;
    display:flex; align-items:center; gap:8px;
    padding:10px 16px calc(10px + env(safe-area-inset-bottom));
    background:#111318;
    border-top:1px solid rgba(255,255,255,.07);
  }
  .chat-input {
    flex:1;
    background:#1e2330; border:1px solid rgba(255,255,255,.1);
    color:#e2e8f0; padding:11px 14px;
    border-radius:22px; outline:none;
    font-family:inherit; font-size:14px;
    -webkit-appearance:none;
    transition:border-color .15s;
  }
  .chat-input:focus { border-color:rgba(167,139,250,.5); }
  .send-btn {
    flex-shrink:0;
    width:42px; height:42px;
    background:linear-gradient(135deg,#4f46e5,#6d28d9);
    color:#fff; border:none; border-radius:50%;
    cursor:pointer; font-size:18px;
    display:flex; align-items:center; justify-content:center;
    -webkit-tap-highlight-color:transparent;
    transition:transform .1s;
  }
  .send-btn:active { transform:scale(.92); }
  .send-btn:disabled { opacity:.4; }

  /* ── Desktop sidebar ── */
  @media(min-width:768px) {
    body { flex-direction:row; }
    .sidebar {
      width:200px; background:#111318;
      border-right:1px solid rgba(255,255,255,.07);
      display:flex; flex-direction:column; padding:20px 0; flex-shrink:0;
    }
    .sb-logo { padding:0 16px 16px; font-size:12px; font-weight:700;
               color:#a78bfa; border-bottom:1px solid rgba(255,255,255,.07); margin-bottom:10px; }
    .sb-a { display:flex; align-items:center; gap:8px; padding:9px 16px;
            font-size:11px; color:#94a3b8; text-decoration:none; }
    .sb-a:hover, .sb-a.on { background:rgba(167,139,250,.08); color:#a78bfa; }
    .main-area { flex:1; display:flex; flex-direction:column; overflow:hidden; }
  }
  @media(max-width:767px) {
    .sidebar { display:none; }
    .main-area { flex:1; display:flex; flex-direction:column; overflow:hidden; }
  }
</style>
</head>
<body>

<!-- Desktop sidebar -->
<nav class="sidebar">
  <div class="sb-logo">📊 NRM Bot</div>
  <a href="/b"        class="sb-a"><span>🟣</span> Strategy B</a>
  <a href="/c"        class="sb-a"><span>🟠</span> Strategy C</a>
  <a href="/d"        class="sb-a"><span>🟢</span> Strategy D</a>
  <a href="/analytics"class="sb-a"><span>📈</span> Analytics</a>
  <a href="/coach"    class="sb-a on"><span>📚</span> Coach</a>
  <a href="/settings" class="sb-a"><span>⚙️</span> Settings</a>
</nav>

<div class="main-area">
  <!-- Header -->
  <div class="hd">
    <div class="hd-left">
      <span class="hd-icon">📚</span>
      <div>
        <div class="hd-title">Trading Coach</div>
        <div class="hd-sub">905 chunks · based on your books</div>
      </div>
    </div>
    <button class="reset-btn" onclick="resetChat()">↺ New</button>
  </div>

  <!-- Chat -->
  <div class="chat-wrap" id="chat">
    <div class="msg bot">Γεια! Είμαι ο Trading Coach σου, εκπαιδευμένος αποκλειστικά στα βιβλία σου.

Μπορώ να σε βοηθήσω με:
• Order Blocks, FVG, SMC concepts
• Supply &amp; Demand zones
• Market Structure (BOS, CHoCH)
• Risk Management
• Swing Trading setups
• Volume Profile &amp; Order Flow

Τι θέλεις να μάθεις σήμερα;</div>
  </div>

  <!-- Suggestions (horizontal scroll) -->
  <div class="sug-wrap" id="suggestions">
    {{ suggestions | safe }}
  </div>

  <!-- Input -->
  <div class="input-wrap">
    <input class="chat-input" id="inp" type="text"
           placeholder="Ρώτα για trading..."
           autocomplete="off" autocorrect="off" spellcheck="false"
           onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMsg()}">
    <button class="send-btn" id="send-btn" onclick="sendMsg()" aria-label="Send">➤</button>
  </div>
</div>

<script>
const chat    = document.getElementById('chat');
const inp     = document.getElementById('inp');
const sendBtn = document.getElementById('send-btn');

function addMsg(text, type) {
  const div = document.createElement('div');
  div.className = 'msg ' + type;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

async function sendMsg() {
  const msg = inp.value.trim();
  if (!msg) return;
  inp.value = '';
  sendBtn.disabled = true;
  inp.blur();

  addMsg(msg, 'user');
  const loading = addMsg('⏳ Σκέφτομαι...', 'msg loading');

  try {
    const r = await fetch('/api/coach', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:msg})
    });
    const d = await r.json();
    loading.remove();
    addMsg(d.answer || ('Σφάλμα: ' + (d.error||'άγνωστο')), d.answer ? 'bot' : 'msg loading');
  } catch(e) {
    loading.remove();
    addMsg('Σφάλμα σύνδεσης. Δοκίμασε ξανά.', 'msg loading');
  }

  sendBtn.disabled = false;
  chat.scrollTop = chat.scrollHeight;
}

function sendSuggestion(btn) {
  inp.value = btn.textContent;
  sendMsg();
}

async function resetChat() {
  await fetch('/api/coach/reset', {method:'POST'});
  const msgs = chat.querySelectorAll('.msg.user, .msg.bot:not(:first-child)');
  msgs.forEach(el => el.remove());
}

// Auto-focus on desktop only
if (window.innerWidth >= 768) inp.focus();
</script>
</body>
</html>
"""



app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "nrmbot-secret-2024")
app.register_blueprint(analytics_bp)
app.register_blueprint(auth_bp)
bot_thread.start()

# Race condition guards — αποθηκεύουν timestamp τελευταίου signal
# Αν το ίδιο signal φτάσει μέσα σε 30s, αγνοείται
import time as _time
# (Το C dedup μετακινήθηκε στο strategies/strategy_c.py ως module-level guard.)
_d_last_signal_time = 0.0
_D_DEDUP_SECONDS = 30

# ── Start analysis agent scheduler (briefings at 08:00, 13:00, 20:00 Athens) ──
threading.Thread(target=start_scheduler, daemon=True).start()

CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:ital,wght@0,300;0,400;0,500;1,400&family=Syne:wght@400;600;700;800&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#080c14;--bg2:#0d1320;--bg3:#111929;--bg4:#162033;
  --b:rgba(255,255,255,.06);--b2:rgba(255,255,255,.10);
  --t:#e8edf5;--t2:#6b7a99;--t3:#3d4f6e;
  --g:#00e5a0;--r:#ff4d6a;--y:#ffc53d;--bl:#4d9eff;--pu:#a855f7;--te:#00d4c8;--or:#ff7c3f;
  --sw:220px;
}
body{background:var(--bg);color:var(--t);font-family:'DM Mono',monospace;min-height:100vh;-webkit-font-smoothing:antialiased}

/* SIDEBAR */
.sb{width:var(--sw);background:var(--bg2);border-right:1px solid var(--b);display:flex;flex-direction:column;position:fixed;top:0;left:0;bottom:0;z-index:100}
.sb-logo{padding:18px 16px 14px;border-bottom:1px solid var(--b);display:flex;align-items:center;gap:10px}
.sb-mark{width:30px;height:30px;background:linear-gradient(135deg,var(--g),var(--bl));border-radius:7px;display:flex;align-items:center;justify-content:center;font-family:'Syne',sans-serif;font-size:13px;font-weight:800;color:#080c14;flex-shrink:0}
.sb-name{font-family:'Syne',sans-serif;font-weight:700;font-size:14px}
.sb-sub{font-size:9px;color:var(--t3);letter-spacing:1px}
.sb-sec{padding:12px 16px 4px;font-size:9px;color:var(--t3);letter-spacing:1.5px;text-transform:uppercase}
.sb-a{display:flex;align-items:center;gap:9px;padding:8px 16px;font-size:11px;color:var(--t2);text-decoration:none;transition:all .15s;position:relative}
.sb-a:hover{color:var(--t);background:rgba(255,255,255,.03)}
.sb-a.on{color:var(--t);background:rgba(255,255,255,.05)}
.sb-a.on::before{content:'';position:absolute;left:0;top:0;bottom:0;width:2px;background:var(--g);border-radius:0 2px 2px 0}
.sb-strat{display:flex;align-items:center;gap:9px;padding:7px 16px;text-decoration:none;transition:all .15s}
.sb-strat:hover{background:rgba(255,255,255,.03)}
.sb-strat.on .sn{font-family:'Syne',sans-serif;font-size:12px;font-weight:700}
.sn{font-family:'Syne',sans-serif;font-size:12px;font-weight:600;color:var(--t2)}
.sd{font-size:9px;color:var(--t3)}
.sb-dot{width:7px;height:7px;border-radius:2px;flex-shrink:0}
.sb-bot{margin-top:auto;border-top:1px solid var(--b);padding:12px 16px;display:flex;align-items:center;gap:8px}
.sb-av{width:26px;height:26px;border-radius:6px;background:linear-gradient(135deg,#1a6bcc,var(--pu));display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:#fff;font-family:'Syne',sans-serif;flex-shrink:0}
.sb-un{font-size:11px;color:var(--t)}
.sb-ro{font-size:9px;color:var(--t3)}
.sb-lo{margin-left:auto;color:var(--t3);text-decoration:none;font-size:16px;transition:color .15s}
.sb-lo:hover{color:var(--r)}

/* MAIN */
.main{margin-left:var(--sw);padding:22px}

/* TOPBAR */
.tb{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;flex-wrap:wrap;gap:10px}
.tb-title{font-family:'Syne',sans-serif;font-size:19px;font-weight:700}
.tb-r{display:flex;align-items:center;gap:8px;flex-wrap:wrap}

/* BADGE */
.bx{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:4px;font-size:10px;font-family:'DM Mono',monospace}
.bx-paper{background:rgba(255,197,61,.1);color:var(--y);border:1px solid rgba(255,197,61,.2)}
.bx-live{background:rgba(0,229,160,.1);color:var(--g);border:1px solid rgba(0,229,160,.2)}
.bx-gray{background:rgba(255,255,255,.05);color:var(--t2);border:1px solid var(--b)}
.bx-g{background:rgba(0,229,160,.1);color:var(--g);border:1px solid rgba(0,229,160,.2)}
.bx-r{background:rgba(255,77,106,.1);color:var(--r);border:1px solid rgba(255,77,106,.2)}
.ld{width:5px;height:5px;border-radius:50%;background:currentColor;animation:bk 2s infinite}
@keyframes bk{0%,100%{opacity:1}50%{opacity:.3}}

/* STATS */
.sg{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px}
.sc{background:var(--bg2);border:1px solid var(--b);border-radius:11px;padding:14px;position:relative;overflow:hidden;transition:border-color .2s}
.sc:hover{border-color:var(--b2)}
.sc::after{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.05),transparent)}
.sl{font-size:9px;color:var(--t3);letter-spacing:1.5px;text-transform:uppercase;margin-bottom:7px}
.sv{font-family:'Syne',sans-serif;font-size:21px;font-weight:700;line-height:1;margin-bottom:3px}
.ss{font-size:9px;color:var(--t3)}
.sv.g{color:var(--g)}.sv.r{color:var(--r)}.sv.y{color:var(--y)}.sv.bl{color:var(--bl)}.sv.te{color:var(--te)}.sv.or{color:var(--or)}.sv.pu{color:var(--pu)}

/* RSI */
.rsi-row{display:flex;justify-content:space-between;font-size:10px;color:var(--t3);margin-bottom:3px}
.rsi-tr{height:3px;background:var(--bg4);border-radius:2px;overflow:hidden;margin-bottom:16px}
.rsi-fi{height:100%;border-radius:2px;transition:width .5s ease}

/* MID ROW */
.mr{display:grid;grid-template-columns:1fr 290px;gap:10px;margin-bottom:16px}

/* CARD */
.cd{background:var(--bg2);border:1px solid var(--b);border-radius:11px;overflow:hidden}
.cd-hd{padding:12px 14px;border-bottom:1px solid var(--b);display:flex;align-items:center;justify-content:space-between}
.cd-tt{font-size:9px;color:var(--t3);letter-spacing:1.5px;text-transform:uppercase}
.cd-bd{padding:14px}

/* SIGNAL */
.sig-bx{padding:14px}
.sig-badge{display:inline-flex;align-items:center;gap:5px;padding:5px 12px;border-radius:5px;font-family:'Syne',sans-serif;font-size:13px;font-weight:700;margin-bottom:10px}
.sig-lo{background:rgba(0,229,160,.1);color:var(--g);border:1px solid rgba(0,229,160,.2)}
.sig-sh{background:rgba(255,77,106,.1);color:var(--r);border:1px solid rgba(255,77,106,.2)}
.sig-wt{background:rgba(255,255,255,.04);color:var(--t2);border:1px solid var(--b)}
.sig-dt{font-size:11px;color:var(--t2);line-height:1.6}
.sig-tm{font-size:10px;color:var(--t3);margin-top:5px}

/* BOX */
.box-g{display:flex;flex-direction:column;gap:5px}
.box-r{display:flex;justify-content:space-between;align-items:center;padding:7px 10px;border-radius:5px}
.box-pdh{background:rgba(255,77,106,.06);border:1px solid rgba(255,77,106,.15)}
.box-mid{background:rgba(255,197,61,.06);border:1px solid rgba(255,197,61,.15)}
.box-pdl{background:rgba(0,229,160,.06);border:1px solid rgba(0,229,160,.15)}
.box-lb{font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.5px}
.box-ds{font-size:8px;color:var(--t3);margin-top:1px}
.box-pr{font-family:'Syne',sans-serif;font-size:13px;font-weight:700}

/* POSITION */
.pr{display:flex;justify-content:space-between;align-items:center;padding:8px 14px;border-bottom:1px solid var(--b);font-size:11px}
.pr:last-child{border-bottom:none}
.pk{color:var(--t3)}.pv{color:var(--t);font-weight:500}

/* TRADE TABLE */
.tt{width:100%;border-collapse:collapse}
.tt th{font-size:9px;color:var(--t3);text-align:left;padding:8px 14px;border-bottom:1px solid var(--b);letter-spacing:1px;text-transform:uppercase;font-weight:500}
.tt td{padding:7px 14px;border-bottom:1px solid rgba(255,255,255,.03);font-size:11px}
.tt tr:last-child td{border-bottom:none}
.tt tr:hover td{background:rgba(255,255,255,.02)}

/* PILL */
.pi{display:inline-block;padding:2px 6px;border-radius:3px;font-size:9px;font-weight:700;font-family:'Syne',sans-serif}
.pi-lo{background:rgba(0,229,160,.1);color:var(--g)}
.pi-sh{background:rgba(255,77,106,.1);color:var(--r)}
.pi-wi{background:rgba(0,229,160,.1);color:var(--g)}
.pi-ls{background:rgba(255,77,106,.1);color:var(--r)}

/* BOTTOM */
.br{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:0}

/* MOBILE NAV */
.mn{display:none;position:fixed;bottom:0;left:0;right:0;background:var(--bg2);border-top:1px solid var(--b);padding:7px 0 max(7px,env(safe-area-inset-bottom));z-index:100}
.mn-in{display:flex;justify-content:space-around}
.mn a{display:flex;flex-direction:column;align-items:center;gap:3px;font-size:9px;color:var(--t3);text-decoration:none;padding:3px 6px;letter-spacing:.5px;transition:color .15s}
.mn a.on{color:var(--g)}

/* NEWS */
.nw-sc{display:inline-flex;align-items:center;gap:3px;padding:2px 7px;border-radius:3px;font-size:10px;font-weight:600}
.nw-p{background:rgba(0,229,160,.1);color:var(--g)}
.nw-n{background:rgba(255,77,106,.1);color:var(--r)}
.nw-z{background:rgba(255,255,255,.05);color:var(--t2)}
.nw-sm{font-size:11px;color:var(--t2);line-height:1.6;margin-top:7px}
.nw-hl{font-size:10px;color:var(--t3);padding:4px 0;border-bottom:1px solid var(--b)}
.nw-hl:last-child{border-bottom:none}

/* COLORS */
.tg{color:var(--g)}.tr{color:var(--r)}.ty{color:var(--y)}.tbl{color:var(--bl)}.tte{color:var(--te)}.tor{color:var(--or)}.tpu{color:var(--pu)}.td{color:var(--t3)}.tm{color:var(--t2)}

/* RESPONSIVE */
@media(max-width:1100px){.sg{grid-template-columns:repeat(2,1fr)}.mr{grid-template-columns:1fr}.br{grid-template-columns:1fr}}
@media(max-width:768px){.sb{display:none}.main{margin-left:0;padding:14px 10px 76px}.sg{gap:8px}.mn{display:block}.tb-title{font-size:16px}}
@media(max-width:400px){.sv{font-size:17px}}
"""

def sb(active='a', username='', role=''):
    strats = [
        ('a','#4d9eff','A','Daily Box + RSI'),
        ('b','#a855f7','B','1H Box + 15m RSI'),
        ('c','#ff7c3f','C','1H Box + Webhook'),
        ('cm','#00d4c8','CM','Check Mark Pattern'),
        ('smc','#f5c518','SMC','OB + FVG + CHoCH'),
    ]
    sh = ''
    for k,c,l,d in strats:
        on = 'on' if active==k else ''
        col = f'color:{c}' if active==k else ''
        sh += f'<a href="/{""if k=="a" else k}" class="sb-strat {on}"><span class="sb-dot" style="background:{c}"></span><span><div class="sn" style="{col}">{("Check Mark" if k=="cm" else "Strategy "+l)}</div><div class="sd">{d}</div></span></a>'
    al = f'<a href="/admin" class="sb-a {"on" if active=="admin" else ""}"><span>🛡</span><span>Admin</span></a>' if role=='admin' else ''
    ini = username[:2].upper() if username else 'U'
    return f'''<div class="sb">
<div class="sb-logo"><div class="sb-mark">N</div><div><div class="sb-name">NRM Bot</div><div class="sb-sub">AUTO TRADING</div></div></div>
<div class="sb-sec">Strategies</div>{sh}
<div class="sb-sec">Analytics</div>
<a href="/analytics" class="sb-a {"on" if active=="analytics" else ""}"><span>📈</span><span>Analytics</span></a>
      <a href="/coach" class="sb-a {"on" if active=="coach" else ""}"><span>📚</span><span>Coach</span></a>
<div class="sb-sec">Account</div>
<a href="/settings" class="sb-a {"on" if active=="settings" else ""}"><span>⚙️</span><span>Settings</span></a>
{al}
<div class="sb-bot"><div class="sb-av">{ini}</div><div><div class="sb-un">{username}</div><div class="sb-ro">{role}</div></div><a href="/logout" class="sb-lo" title="Logout">↩</a></div>
</div>'''

def mn(active='a'):
    items = [('/', 'a','A'),('/b','b','B'),('/c','c','C'),('/cm','cm','CM'),('/smc','smc','SMC'),('/analytics','analytics','📈'),('/coach','coach','📚'),('/settings','settings','⚙')]
    h = '<nav class="mn"><div class="mn-in">'
    for href,k,l in items:
        h += f'<a href="{href}" class="{"on" if active==k else ""}">{l}</a>'
    h += '</div></nav>'
    return h

TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>NRM Bot — Strategy {{ sl }}</title>
<style>{{ css }}</style>
</head>
<body>
{{ sidebar|safe }}
<div class="main">

<div class="tb">
  <div style="display:flex;align-items:center;gap:10px">
    <div class="tb-title">Strategy {{ sl }}</div>
    <span class="bx {{ 'bx-paper' if mode=='PAPER' else 'bx-live' }}"><span class="ld"></span>{{ mode }}</span>
    {% if positions and positions|length > 1 %}<span class="bx bx-g">{{ positions|length }} OPEN</span>{% elif position %}<span class="bx {{ 'bx-g' if position.type=='LONG' else 'bx-r' }}">{{ position.type }} OPEN</span>{% endif %}
  </div>
  <div class="tb-r">
    <span class="bx bx-gray">BTCUSDT PERP</span>
    <span class="bx bx-gray">BITGET</span>
    <span class="bx bx-gray" id="s-cycle">{{ last_cycle }}</span>
    {% if sl in ['B','C'] %}
    <button id="trailing-btn" onclick="toggleTrailing('{{ strategy_id }}')"
      style="background:rgba(255,200,0,.12);color:#ffc800;border:1px solid rgba(255,200,0,.4);padding:4px 10px;border-radius:5px;font-size:9px;cursor:pointer;font-family:'DM Mono',monospace;letter-spacing:1px;margin-right:4px;">
      🚀 TRAILING
    </button>
    {% endif %}
    <button onclick="resetStrategy('{{ strategy_id }}')"
      style="background:rgba(255,255,255,.05);color:var(--t2);border:1px solid var(--b);padding:4px 10px;border-radius:5px;font-size:9px;cursor:pointer;font-family:'DM Mono',monospace;letter-spacing:1px;">
      🔄 RESET
    </button>
  </div>
</div>

<div class="sg">
  <div class="sc"><div class="sl">Balance</div><div class="sv {{ sc }}" id="s-bal">${{ "{:,.0f}".format(balance) }}</div><div class="ss">USDT Perpetual</div></div>
  <div class="sc"><div class="sl">Total P&L</div><div class="sv {{ 'g' if pnl>=0 else 'r' }}" id="s-pnl">{{ '+' if pnl>=0 else '' }}${{ "{:.2f}".format(pnl) }}</div><div class="ss" id="s-pnlp">all time</div></div>
  <div class="sc"><div class="sl">Win Rate</div><div class="sv y" id="s-wr">{{ wr }}%</div><div class="ss" id="s-wl">{{ wins }}W · {{ losses }}L</div></div>
  <div class="sc"><div class="sl">BTC Price</div><div class="sv bl" id="s-px">${{ "{:,.0f}".format(current_price) }}</div><div class="ss"><span id="s-rsi" class="{{ 'tr' if rsi>70 else 'tg' if rsi<30 else 'tm' }}">RSI {{ rsi }}</span></div></div>
</div>

<div class="rsi-row"><span>RSI (14)</span><span id="s-rsiv">{{ rsi }}</span></div>
<div class="rsi-tr"><div class="rsi-fi" id="s-rsif" style="width:{{ rsi }}%;background:{{ '#ff4d6a' if rsi>70 else '#00e5a0' if rsi<30 else '#4d9eff' }}"></div></div>

<div class="mr">
  <div class="cd">
    <div class="cd-hd"><div class="cd-tt">Current Signal</div>{% if sl in ['C','D'] %}<span class="bx bx-gray">⚡ TradingView</span>{% endif %}</div>
    <div class="sig-bx">
      {% if 'LONG' in signal and 'HOLDING' not in signal and 'block' not in signal.lower() %}
        <div id="sig-b" class="sig-badge sig-lo">▲ LONG</div>
      {% elif 'SHORT' in signal and 'HOLDING' not in signal and 'block' not in signal.lower() %}
        <div id="sig-b" class="sig-badge sig-sh">▼ SHORT</div>
      {% elif 'HOLDING' in signal %}
        <div id="sig-b" class="sig-badge sig-wt">◆ HOLDING</div>
      {% else %}
        <div id="sig-b" class="sig-badge sig-wt">◌ WAIT</div>
      {% endif %}
      <div id="sig-t" class="sig-dt">{{ signal }}</div>
      <div id="sig-tm" class="sig-tm">{{ signal_time }}</div>
    </div>
    {% if ns is defined %}
    <div style="padding:0 14px 10px;display:flex;align-items:center;gap:8px">
      <span class="td" style="font-size:10px">AI NEWS</span>
      <span id="s-ns" class="nw-sc {{ 'nw-p' if ns>0 else 'nw-n' if ns<0 else 'nw-z' }}">Score: {{ ns }}</span>
    </div>
    {% endif %}
  </div>

  {% if box %}
  <div class="cd">
    <div class="cd-hd"><div class="cd-tt">{{ 'Daily Box' if sl=='A' else '1H Box' }} · {{ box.get('date', box.get('time','')) }}</div></div>
    <div class="cd-bd" style="padding-top:8px">
      <div class="box-g">
        <div class="box-r box-pdh"><div><div class="box-lb tr">PDH · Short</div><div class="box-ds">RSI &gt; 70 → Sell</div></div><div class="box-pr tr">${{ "{:,.2f}".format(box.high) }}</div></div>
        <div class="box-r box-mid"><div><div class="box-lb ty">MID · TP</div><div class="box-ds">Take Profit</div></div><div class="box-pr ty">${{ "{:,.2f}".format(box.mid) }}</div></div>
        <div class="box-r box-pdl"><div><div class="box-lb tg">PDL · Long</div><div class="box-ds">RSI &lt; 30 → Buy</div></div><div class="box-pr tg">${{ "{:,.2f}".format(box.low) }}</div></div>
      </div>
      <div style="margin-top:8px;font-size:10px;color:var(--t3);display:flex;gap:10px">
        <span>Size: ${{ "{:,.0f}".format(box.size) }}</span><span>R/R 1:2</span><span>Risk 2%</span>
      </div>
    </div>
  </div>
  {% elif strategy_id == 'CM' %}
  <div class="cd">
    <div class="cd-hd"><div class="cd-tt">Signal Source</div></div>
    <div style="padding:26px 14px;text-align:center">
      <div style="font-size:26px;margin-bottom:6px">✓</div>
      <div style="font-size:11px;color:var(--t2)">Check Mark Pattern<br>Auto-scan @ 13:30 UTC (NY open)</div>
      <div style="font-size:10px;color:var(--t3);margin-top:8px">Manipulation → Blowoff → Pivot → Entry</div>
    </div>
  </div>
  {% else %}
  <div class="cd">
    <div class="cd-hd"><div class="cd-tt">Signal Source</div></div>
    <div style="padding:26px 14px;text-align:center">
      <div style="font-size:26px;margin-bottom:6px">⚡</div>
      <div style="font-size:11px;color:var(--t2)">Waiting for<br>TradingView webhook</div>
    </div>
  </div>
  {% endif %}
</div>

<div class="br">
  {% macro poscard(position, idx=0, total=1) %}
  <div class="cd">
    <div class="cd-hd"><div class="cd-tt">Open Position{{ ' #' ~ idx if total > 1 else '' }}</div><span class="pi {{ 'pi-lo' if position.type=='LONG' else 'pi-sh' }}">{{ position.type }}</span></div>
    <div>
      <div class="pr"><span class="pk">Entry</span><span class="pv">${{ "{:,.2f}".format(position.entry) }}</span></div>
      {% if position.tp is defined and position.tp1 is not defined %}<div class="pr"><span class="pk">Take Profit</span><span class="pv tg">${{ "{:,.2f}".format(position.tp) }}</span></div>{% endif %}
      {% if position.tp1 is defined %}<div class="pr"><span class="pk">TP1{{ ' ✓' if position.phase1_done else '' }}</span><span class="pv tg">${{ "{:,.2f}".format(position.tp1) }}</span></div><div class="pr"><span class="pk">TP2</span><span class="pv tte">${{ "{:,.2f}".format(position.tp2) }}</span></div>{% endif %}
      {% if position.phase1_done and not position.trailing_active %}
      <div class="pr"><span class="pk" style="color:#ffc800">🔒 SL (Break Even)</span><span class="pv" style="color:#ffc800">${{ "{:,.2f}".format(position.sl) }}</span></div>
      {% elif position.trailing_active %}
      <div class="pr"><span class="pk" style="color:#ffc800">🚀 Trailing SL</span><span class="pv" style="color:#ffc800">${{ "{:,.2f}".format(position.trailing_sl) }}</span></div>
      <div class="pr"><span class="pk">Peak Price</span><span class="pv tg">${{ "{:,.2f}".format(position.trailing_peak) }}</span></div>
      {% else %}
      <div class="pr"><span class="pk">Stop Loss</span><span class="pv tr">${{ "{:,.2f}".format(position.sl) }}</span></div>
      {% endif %}
      <div class="pr"><span class="pk">Size (BTC)</span><span class="pv">{{ position.qty }}</span></div>
      <div class="pr"><span class="pk">Opened</span><span class="pv td">{{ position.time }}</span></div>
      {% if position.has_divergence %}<div class="pr"><span class="pk">Divergence</span><span class="pv ty">🔥 DOUBLE</span></div>{% endif %}
      {% if position.has_confluence %}<div class="pr"><span class="pk">Confluence</span><span class="pv tte">🔥 Strong</span></div>{% endif %}
    </div>
  </div>
  {% endmacro %}
  {% if positions and positions|length > 0 %}
  {% for p in positions %}{{ poscard(p, loop.index, positions|length) }}{% endfor %}
  {% elif position %}
  {{ poscard(position) }}
  {% else %}
  <div class="cd"><div style="padding:26px 14px;text-align:center;color:var(--t3);font-size:11px">No open position</div></div>
  {% endif %}

  <div class="cd">
    <div class="cd-hd"><div class="cd-tt">Trade History</div>{% if trades %}<span class="bx bx-gray">{{ trades|length }} trades</span>{% endif %}</div>
    {% if trades %}
    <table class="tt">
      <thead><tr><th>Time</th><th>Type</th><th>P&L</th><th>Result</th></tr></thead>
      <tbody id="tb">
        {% for t in trades[-15:]|reverse %}
        <tr>
          <td class="td">{{ t.time[5:16] if t.time else '—' }}</td>
          <td><span class="pi {{ 'pi-lo' if t.type=='LONG' else 'pi-sh' }}">{{ t.type }}</span></td>
          <td class="{{ 'tg' if t.pnl>=0 else 'tr' }}">{{ '+' if t.pnl>=0 else '' }}${{ "{:.1f}".format(t.pnl) }}</td>
          <td><span class="pi {{ 'pi-wi' if t.result=='WIN' else 'pi-ls' }}">{{ t.result }}</span></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div style="padding:26px 14px;text-align:center;color:var(--t3);font-size:11px">No trades yet</div>
    {% endif %}
  </div>
</div>

{% if strategy_id == 'CM' %}
<div class="cd" style="margin-top:10px">
  <div class="cd-hd"><div class="cd-tt">📖 Πώς δουλεύει η Check Mark</div></div>
  <div class="cd-bd" style="padding:16px;font-size:12px;line-height:1.7;color:var(--t2)">
    <p style="margin-bottom:12px">Η στρατηγική εκμεταλλεύεται τη <b style="color:var(--t1)">χειραγώγηση τιμής</b> στο άνοιγμα της US session (13:30 UTC). Το σχήμα στο chart μοιάζει με τσεκ (✓).</p>

    <div style="margin-bottom:10px">
      <div style="color:#14b8a6;font-weight:600;margin-bottom:4px">1️⃣ THE CHECK (Opening Range)</div>
      <div style="color:var(--t3)">Παίρνει το πρώτο 15m κερί μετά το NY open. Ελέγχει αν είναι <b>Manipulation Candle</b> (εύρος &gt; 20% του Daily ATR) και <b>Blowoff</b> (έσπασε το προηγούμενο day high/low και γύρισε πίσω — σκοτώνοντας τα stop-losses).</div>
    </div>

    <div style="margin-bottom:10px">
      <div style="color:#14b8a6;font-weight:600;margin-bottom:4px">2️⃣ THE PIVOT (Επιβεβαίωση)</div>
      <div style="color:var(--t3)">Στο 5m chart ψάχνει <b>double/triple test</b> της ζώνης: η τιμή ξαναπλησιάζει το level αλλά δεν το σπάει και αναπηδά. Επιβεβαιώνει ότι οι buyers/sellers είναι πραγματικά εκεί.</div>
    </div>

    <div style="margin-bottom:10px">
      <div style="color:#14b8a6;font-weight:600;margin-bottom:4px">3️⃣ THE MARK (Είσοδος)</div>
      <div style="color:var(--t3)">Entry όταν πράσινο 5m κερί κλείνει πάνω από κόκκινο (LONG) ή το αντίστροφο (SHORT). <b>SL:</b> κάτω από το blowoff low. <b>TP1</b> (κοντινός στόχος): κλείνει 50% + SL→break-even. <b>TP2</b> (μακρινός στόχος): κλείνει το υπόλοιπο 50%.</div>
    </div>

    <div style="margin-top:12px;padding:10px;background:rgba(20,184,166,.08);border-radius:6px;border:1px solid rgba(20,184,166,.2)">
      <div style="font-size:11px;color:var(--t3)">⚙️ <b style="color:var(--t1)">Ρυθμίσεις:</b> Σκαν @ 13:30 UTC · ATR threshold 20% · Pivot 2+ tests · Risk 2% · 2-phase exit (TP1 50% + break-even → TP2)</div>
    </div>

    <div style="margin-top:8px;font-size:10px;color:var(--t3)">Μετά το entry, περνά από τον AI Validator (trend, OB, FVG, volume, news, knowledge base) για την τελική απόφαση GO/SKIP/DOUBLE/REDUCE.</div>
  </div>
</div>
{% endif %}

{% if strategy_id == 'SMC' %}
<div class="cd" style="margin-top:10px">
  <div class="cd-hd"><div class="cd-tt">📖 Πώς δουλεύει η SMC</div></div>
  <div class="cd-bd" style="padding:16px;font-size:12px;line-height:1.7;color:var(--t2)">
    <p style="margin-bottom:12px">Στρατηγική <b style="color:var(--t1)">Smart Money Concepts</b> (OB + FVG + CHoCH). Τα signals έρχονται από το <b>TradingView webhook</b> — το Pine script εντοπίζει το setup και στέλνει entry/SL/TP στο bot.</p>

    <div style="margin-bottom:10px">
      <div style="color:#f5c518;font-weight:600;margin-bottom:4px">1️⃣ ORDER BLOCK + FVG</div>
      <div style="color:var(--t3)">Εντοπίζει <b>Order Block</b> (η τελευταία κερί πριν από impulsive move) σε confluence με <b>Fair Value Gap</b> (imbalance/κενό στην τιμή που τείνει να γεμίσει).</div>
    </div>

    <div style="margin-bottom:10px">
      <div style="color:#f5c518;font-weight:600;margin-bottom:4px">2️⃣ CHoCH (Change of Character)</div>
      <div style="color:var(--t3)">Επιβεβαίωση αλλαγής δομής: η τιμή σπάει το προηγούμενο swing high/low, σηματοδοτώντας πιθανή αντιστροφή τάσης προς την κατεύθυνση του trade.</div>
    </div>

    <div style="margin-bottom:10px">
      <div style="color:#f5c518;font-weight:600;margin-bottom:4px">3️⃣ ENTRY + 2-PHASE EXIT</div>
      <div style="color:var(--t3)">Entry στη ζώνη confluence (OB+FVG). <b>SL:</b> πέρα από το Order Block. <b>TP1</b> (κοντινός): κλείνει 50% + SL→break-even. <b>TP2</b> (μακρινός): κλείνει το υπόλοιπο 50%. <b>Strong confluence</b> → διπλάσιο μέγεθος θέσης.</div>
    </div>

    <div style="margin-top:12px;padding:10px;background:rgba(245,197,24,.08);border-radius:6px;border:1px solid rgba(245,197,24,.2)">
      <div style="font-size:11px;color:var(--t3)">⚙️ <b style="color:var(--t1)">Ρυθμίσεις:</b> TradingView webhook · Risk 2% (×2 strong confluence) · 2-phase exit (TP1 50% + break-even → TP2) · Dedup 30s</div>
    </div>

    <div style="margin-top:8px;font-size:10px;color:var(--t3)">Μετά το entry, περνά από τον AI Validator (trend, OB, FVG, volume, news, knowledge base) για την τελική απόφαση GO/SKIP/DOUBLE/REDUCE.</div>
  </div>
</div>
{% endif %}

{% if nsm is defined and nsm %}
<div class="cd" style="margin-top:10px">
  <div class="cd-hd"><div class="cd-tt">AI News Analysis</div><span id="s-ns2" class="nw-sc {{ 'nw-p' if ns>0 else 'nw-n' if ns<0 else 'nw-z' }}">Score: {{ ns }}</span></div>
  <div class="cd-bd"><div class="nw-sm" id="nw-sm">{{ nsm }}</div><div style="margin-top:8px" id="nw-hl">{% for h in hl[:5] %}<div class="nw-hl">• {{ h }}</div>{% endfor %}</div></div>
</div>
{% endif %}

</div>
{{ mobile_nav|safe }}

<script>
const AURL='{{ api_url }}';
function f(n,d=2){return '$'+Number(n).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d})}
function el(i){return document.getElementById(i)}
function upd(){
  fetch(AURL).then(r=>r.json()).then(s=>{
    const price=s.current_price||0,rsi=s.current_rsi||50;
    const w=s.wins||0,l=s.losses||0,tot=w+l,wr=tot>0?Math.round(w/tot*100):0;
    if(el('s-bal'))el('s-bal').textContent=f(s.balance,0);
    if(el('s-px'))el('s-px').textContent=f(price,0);
    if(el('s-wr'))el('s-wr').textContent=wr+'%';
    if(el('s-wl'))el('s-wl').textContent=w+'W · '+l+'L';
    if(el('s-cycle'))el('s-cycle').textContent=s.last_cycle||'';
    const pe=el('s-pnl');
    if(pe){pe.textContent=(s.pnl_total>=0?'+':'')+f(s.pnl_total);pe.className='sv '+(s.pnl_total>=0?'g':'r')}
    if(el('s-rsi'))el('s-rsi').textContent='RSI '+rsi;
    if(el('s-rsiv'))el('s-rsiv').textContent=rsi;
    const fi=el('s-rsif');
    if(fi){fi.style.width=rsi+'%';fi.style.background=rsi>70?'#ff4d6a':rsi<30?'#00e5a0':'#4d9eff'}
    const sig=s.last_signal||'';
    const sb=el('sig-b'),st=el('sig-t'),stm=el('sig-tm');
    if(st)st.textContent=sig;
    if(stm)stm.textContent=s.last_signal_time||'';
    if(sb){
      if(sig.includes('LONG')&&!sig.includes('HOLDING')&&!sig.toLowerCase().includes('block')){sb.textContent='▲ LONG';sb.className='sig-badge sig-lo'}
      else if(sig.includes('SHORT')&&!sig.includes('HOLDING')&&!sig.toLowerCase().includes('block')){sb.textContent='▼ SHORT';sb.className='sig-badge sig-sh'}
      else if(sig.includes('HOLDING')){sb.textContent='◆ HOLDING';sb.className='sig-badge sig-wt'}
      else{sb.textContent='◌ WAIT';sb.className='sig-badge sig-wt'}
    }
    if(s.trades&&s.trades.length>0){
      const tb=el('tb');
      if(tb)tb.innerHTML=[...s.trades].reverse().slice(0,15).map(t=>
        '<tr><td class="td">'+(t.time||'').substring(5,16)+'</td>'+
        '<td><span class="pi '+(t.type==='LONG'?'pi-lo':'pi-sh')+'">'+t.type+'</span></td>'+
        '<td class="'+(t.pnl>=0?'tg':'tr')+'">'+(t.pnl>=0?'+':'')+f(t.pnl,1)+'</td>'+
        '<td><span class="pi '+(t.result==='WIN'?'pi-wi':'pi-ls')+'">'+t.result+'</span></td></tr>'
      ).join('');
    }
    if (typeof d.trailing_enabled !== 'undefined') updateTrailingBtn(d.trailing_enabled);
  }).catch(e=>console.log(e));
}
setInterval(upd,10000);upd();
document.addEventListener('visibilitychange',()=>{if(!document.hidden)upd()});

function resetStrategy(strategy) {
  if (!confirm('Reset Strategy ' + strategy + ' - Θα διαγραφουν τα trades!')) return;
  fetch('/reset/' + strategy, {method:'POST'})
    .then(r=>r.json())
    .then(d=>{
      if(d.ok){alert('Strategy ' + strategy + ' reset OK');location.reload();}
      else{alert('Error: ' + (d.error||'unknown'));}
    }).catch(e=>alert('Error: '+e));
}
function toggleTrailing(strategy) {
  fetch('/toggle-trailing/' + strategy, {method:'POST'})
    .then(r=>r.json())
    .then(d=>{
      if(d.ok !== undefined) updateTrailingBtn(d.enabled);
      else alert('Error: ' + (d.error||'unknown'));
    }).catch(e=>alert('Error: '+e));
}
function updateTrailingBtn(enabled) {
  const btn = document.getElementById('trailing-btn');
  if (!btn) return;
  if (enabled) {
    btn.style.background='rgba(255,200,0,.12)';
    btn.style.color='#ffc800';
    btn.style.borderColor='rgba(255,200,0,.4)';
    btn.title='Trailing ON — κλικ για OFF';
  } else {
    btn.style.background='rgba(255,255,255,.05)';
    btn.style.color='var(--t3)';
    btn.style.borderColor='var(--b)';
    btn.title='Trailing OFF — κλικ για ON';
  }
}
</script>
</body></html>"""


def render_dash(active, api_url, sc, s, extra={}):
    wins = s.get('wins',0); losses = s.get('losses',0); total = wins+losses
    username = session.get('username',''); role = session.get('role','user')
    return render_template_string(TMPL,
        css=CSS, sidebar=sb(active,username,role), mobile_nav=mn(active),
        sl=active.upper(), sc=sc, api_url=api_url,
        strategy_id=active.upper(),
        mode=s.get('mode','PAPER'),
        balance=s.get('balance',10000), pnl=s.get('pnl_total',0),
        wins=wins, losses=losses, wr=round(wins/total*100) if total>0 else 0,
        rsi=s.get('current_rsi',50),
        signal=s.get('last_signal','Waiting...'),
        signal_time=s.get('last_signal_time',''),
        last_cycle=s.get('last_cycle',''),
        position=s.get('position'),
        positions=s.get('positions'),
        box=s.get('box'),
        current_price=s.get('current_price',0),
        trades=s.get('trades',[]),
        ns=extra.get('ns',0), nsm=extra.get('nsm',''), hl=extra.get('hl',[]),
    )


@app.route('/')
@login_required
def index():
    s = snapshot_state('A')
    return render_dash('a','/api','bl', s, {
        'ns': s.get('last_news_score',0),
        'nsm': s.get('last_news_summary',''),
        'hl': s.get('last_news_headlines',[]),
    })

@app.route('/b')
@login_required
def strategy_b():
    s = snapshot_state('B'); s['current_price'] = snapshot_state('A').get('current_price',0)
    return render_dash('b','/api/b','pu', s)

@app.route('/c')
@login_required
def strategy_c():
    return render_dash('c','/api/c','or', snapshot_state('C'))

@app.route('/d')
@login_required
def strategy_d():
    s = snapshot_state('D'); s['box'] = None
    return render_dash('d','/api/d','te', s)

@app.route('/api')
@login_required
def api():
    from bot import rt
    data = snapshot_state('A')
    # Προσθήκη live price/RSI για το analysis_agent.py
    _state = data
    data["price"]    = rt.price if rt.price > 0 else _state.get("current_price", 0)
    data["rsi_1h"]   = round(rt.rsi_1h, 2) if hasattr(rt, "rsi_1h") else _state.get("current_rsi", 0)
    data["rsi_15m"]  = round(rt.rsi_15m, 2) if hasattr(rt, "rsi_15m") else 0
    data["box_high"] = (_state.get("box") or {}).get("high", 0)
    data["box_low"]  = (_state.get("box") or {}).get("low", 0)
    data["mid"]      = (_state.get("box") or {}).get("mid", 0)
    return jsonify(data)

@app.route('/api/b')
@login_required
def api_b(): return jsonify(snapshot_state('B'))

@app.route('/api/c')
@login_required
def api_c(): return jsonify(snapshot_state('C'))

@app.route('/api/d')
@login_required
def api_d(): return jsonify(snapshot_state('D'))

@app.route('/cm')
@login_required
def strategy_cm():
    s = snapshot_state('CM'); s['box'] = None
    return render_dash('cm','/api/cm','te', s)

@app.route('/api/cm')
@login_required
def api_cm(): return jsonify(snapshot_state('CM'))

@app.route('/smc')
@login_required
def strategy_smc_page():
    s = snapshot_state('SMC'); s['box'] = None
    return render_dash('smc','/api/smc','pu', s)

@app.route('/api/smc')
@login_required
def api_smc(): return jsonify(snapshot_state('SMC'))


# ── WEBHOOKS (no login) ──────────────────────────────────────
from flask import request
import threading

def _wh_d(sig, price=None, data=None):
    global _d_last_signal_time
    from bot import rt,state_d,save_state_d,send_telegram,calc_qty,place_order_paper,place_order_live,TRADING_MODE,RISK_PER_TRADE,state_lock_d
    from datetime import datetime,timezone
    if data is None: data={}
    p=price or rt.price
    now = _time.time()
    if p<=0 or state_d['position']: return
    if now - _d_last_signal_time < _D_DEDUP_SECONDS:
        log.info(f"[D] Duplicate signal ignored (last={now-_d_last_signal_time:.1f}s ago)")
        return
    _d_last_signal_time = now
    il=sig=='LONG'
    try:
        sl=float(data.get('sl',0)) or (p*.985 if il else p*1.015)
        tp1=float(data.get('tp1',0)) or (p+abs(p-sl)*2 if il else p-abs(sl-p)*2)
        tp2=float(data.get('tp2',0)) or (p+abs(p-sl)*3 if il else p-abs(sl-p)*3)
    except: sl=p*.985 if il else p*1.015; d=abs(p-sl); tp1=p+d*2 if il else p-d*2; tp2=p+d*3 if il else p-d*3
    sl=round(sl,2); tp1=round(tp1,2); tp2=round(tp2,2)
    cf=data.get('confluence','normal')=='strong'
    qty=calc_qty(state_d['balance'],RISK_PER_TRADE*(2 if cf else 1),p,sl)
    # ── AI Validator ──────────────────────────────────────────────
    from bot import _ai_validate, rt as _rt, AI_SHADOW_MASTER
    _ai_act,_ai_mult,_ai_res = _ai_validate(
        strategy="D", side=sig,
        entry_price=p, stop_loss=sl, take_profit=tp1 if tp1 else tp,
        rsi_15m=_rt.rsi_15m, rsi_1h=_rt.rsi_1h,
        box=None, has_divergence=cf,
        trades=state_d.get("trades",[]), balance=state_d.get("balance",10000),
    )
    if _ai_act == "SKIP": return
    if _ai_act in ("REDUCE_SIZE","DOUBLE_SIZE"): qty=round(qty*_ai_mult,4)
    # ─────────────────────────────────────────────────────────────
    oid=place_order_paper(sig,qty,p,sl,tp1) if TRADING_MODE=='PAPER' else place_order_live(sig,qty,sl,tp1)
    if oid:
        import json as _json
        with state_lock_d:
            state_d['position']={'type':sig,'entry':p,'sl':sl,'tp1':tp1,'tp2':tp2,'qty':qty,'time':datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),'order_id':oid,'has_confluence':cf,'phase1_done':False,
                                'ai_action':_ai_act,'ai_shadow':AI_SHADOW_MASTER,
                                'ai_confidence': (_ai_res.confidence if _ai_res else 0),
                                'ai_reasoning': (_json.dumps(_ai_res.reasoning) if _ai_res and _ai_res.reasoning else "")}
            state_d['last_signal']=sig; state_d['last_signal_time']=datetime.now(timezone.utc).strftime('%H:%M UTC')
        save_state_d()
        send_telegram(f"{'🔴' if sig=='SHORT' else '🟢'} <b>[D] {sig}</b>\nEntry: ${p:,.2f} | TP1: ${tp1:,.2f} | TP2: ${tp2:,.2f} | SL: ${sl:,.2f}")

def _wh_smc(sig, price=None, data=None):
    """SMC webhook → delegate στο αυτόνομο strategies/strategy_smc.py module."""
    from bot import (rt, state_smc, save_state_smc, send_telegram, calc_qty,
                     place_order_paper, place_order_live, _ai_validate,
                     _send_ai_trade_summary, TRADING_MODE, state_lock_smc)
    from strategies import strategy_smc

    def _place(side, qty, entry, sl, tp):
        return (place_order_paper(side, qty, entry, sl, tp) if TRADING_MODE == "PAPER"
                else place_order_live(side, qty, sl, tp))

    deps = {
        "get_price":       lambda: rt.price,
        "calc_qty":        calc_qty,
        "place_order":     _place,
        "send_telegram":   send_telegram,
        "ai_validate":     _ai_validate,
        "save_state":      save_state_smc,
        "send_ai_summary": _send_ai_trade_summary,
        "trading_mode":    TRADING_MODE,
        "rt":              rt,
        "lock":            state_lock_smc,
    }
    strategy_smc.process_webhook(deps, state_smc, sig, price, data)

def _wh_a(sig, price=None, data=None):
    from bot import rt,state,build_daily_box,get_candles,calc_qty,place_order_paper,place_order_live
    from bot import find_4h_sr,detect_divergence,fetch_news,ai_news_score,save_state,send_telegram,TRADING_MODE,RISK_PER_TRADE,state_lock
    from datetime import datetime,timezone
    if data is None: data={}
    p=price or rt.price
    if p<=0 or state['position']: return
    c4=get_candles('4H',500); c1=get_candles('1H',200)
    if not c4 or not c1: return
    box=build_daily_box(c4)
    if not box: return
    state['box']=box
    sup,res=find_4h_sr(c4,p)
    with rt.lock: cl1=list(rt.closes_1h)
    bd,_=detect_divergence(cl1,[c['high'] for c in c1][-20:],[c['low'] for c in c1][-20:])
    _,bear_d=detect_divergence(cl1,[c['high'] for c in c1][-20:],[c['low'] for c in c1][-20:])
    if sig=='SHORT':
        sl=round(res*1.003,2); tp=box['mid']
        if tp>=p: tp=round(p*.99,2)
        if sl<=p: sl=round(p*1.01,2)
        if sl>p*1.015: sl=round(p*1.015,2)
        rp=RISK_PER_TRADE*2 if bear_d else RISK_PER_TRADE
    else:
        sl=round(sup*.997,2); tp=box['mid']
        if tp<=p: tp=round(p*1.01,2)
        if sl>=p: sl=round(p*.99,2)
        if sl<p*.985: sl=round(p*.985,2)
        rp=RISK_PER_TRADE*2 if bd else RISK_PER_TRADE
    qty=calc_qty(state['balance'],rp,p,sl)
    hl=fetch_news(); sc,sm=ai_news_score(hl,sig,p,box)
    oid=place_order_paper(sig,qty,p,sl,tp) if _TRADING_MODE_C=='PAPER' else place_order_live(sig,qty,sl,tp)
    if oid:
        with state_lock:
            state['position']={'type':sig,'entry':p,'sl':sl,'tp':tp,'qty':qty,'time':datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),'order_id':oid,'news_score':sc,'news_summary':sm,'has_divergence':bear_d}
            state['last_signal']=sig; state['last_signal_time']=datetime.now(timezone.utc).strftime('%H:%M UTC')
        save_state()
        send_telegram(f"{'🔴' if sig=='SHORT' else '🟢'} <b>[A] {sig}</b>\nEntry: ${p:,.2f} | TP: ${tp:,.2f} | SL: ${sl:,.2f}")

def _wh_c(sig, price=None, data=None):
    """Strategy C webhook → delegate στο αυτόνομο strategies/strategy_c.py module."""
    import os as _os
    from bot import (rt, state_c, save_state_c, send_telegram, calc_qty,
                     place_order_paper, place_order_live, get_candles, build_1h_box,
                     _ai_validate, _send_ai_trade_summary, TRADING_MODE, RISK_PER_TRADE,
                     AI_SHADOW_MASTER, state_lock_c)
    from strategies import strategy_c

    # Per-strategy overrides — TRADING_MODE_C / RISK_PER_TRADE_C αν υπάρχουν
    _TRADING_MODE_C = _os.environ.get("TRADING_MODE_C", TRADING_MODE).upper()
    _RISK_C = float(_os.environ.get("RISK_PER_TRADE_C", str(RISK_PER_TRADE)))

    def _place(side, qty, entry, sl, tp):
        return (place_order_paper(side, qty, entry, sl, tp) if _TRADING_MODE_C == 'PAPER'
                else place_order_live(side, qty, sl, tp))

    deps = {
        "get_price":        lambda: rt.price,
        "calc_qty":         calc_qty,
        "place_order":      _place,
        "send_telegram":    send_telegram,
        "ai_validate":      _ai_validate,
        "save_state":       save_state_c,
        "send_ai_summary":  _send_ai_trade_summary,
        "get_candles":      get_candles,
        "build_1h_box":     build_1h_box,
        "rt":               rt,
        "risk_pct":         _RISK_C,
        "ai_shadow_master": AI_SHADOW_MASTER,
        "lock":             state_lock_c,
    }
    strategy_c.process_webhook(deps, state_c, sig, price, data)


def _reset_trades_db(strategy: str):
    """Διαγράφει trades από DB για μια στρατηγική."""
    try:
        from database import get_conn
        conn = get_conn()
        if conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM trades WHERE strategy=%s",
                    (strategy,)
                )
            conn.commit()
            conn.close()
            log.info(f"Reset trades DB for strategy {strategy}")
    except Exception as e:
        log.warning(f"Reset {strategy} trades DB error: {e}")

# ── TRADING COACH ────────────────────────────────────────────────
@app.route('/coach')
@login_required
def coach_page():
    """Trading Coach chat page."""
    from flask import session as flask_session
    suggestions_html = ""
    try:
        from coach_agent import SUGGESTIONS
        suggestions_html = "".join(
            f'<button class="sug-btn" onclick="sendSuggestion(this)">{s}</button>'
            for s in SUGGESTIONS
        )
    except Exception:
        pass

    return render_template_string(COACH_HTML, suggestions=suggestions_html)

@app.route('/api/coach', methods=['POST'])
@login_required
def api_coach():
    """Coach chat API."""
    from flask import request as req, session as flask_session
    try:
        data    = req.get_json(force=True) or {}
        message = data.get('message', '').strip()
        if not message:
            return jsonify({'error': 'Empty message'}), 400
        session_id = f"user_{flask_session.get('user_id', 1)}"
        from coach_agent import chat
        answer = chat(message, session_id)
        return jsonify({'answer': answer, 'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/coach/reset', methods=['POST'])
@login_required
def api_coach_reset():
    from flask import session as flask_session
    session_id = f"user_{flask_session.get('user_id', 1)}"
    from coach_agent import reset_session
    msg = reset_session(session_id)
    return jsonify({'ok': True, 'message': msg})

# ── TRAILING TOGGLE ─────────────────────────────────────────────
@app.route('/toggle-trailing/<strategy>', methods=['POST'])
def toggle_trailing(strategy):
    from bot import state_b, save_state_b, state_c, save_state_c
    if 'username' not in __import__('flask').session:
        return __import__('flask').jsonify({'error':'Unauthorized'}), 401
    s = strategy.upper()
    try:
        if s == 'B':
            with state_lock_b:
                state_b['trailing_enabled'] = not state_b.get('trailing_enabled', True)
                enabled = state_b['trailing_enabled']
            save_state_b()
            return __import__('flask').jsonify({'ok': True, 'enabled': enabled})
        elif s == 'C':
            with state_lock_c:
                state_c['trailing_enabled'] = not state_c.get('trailing_enabled', True)
                enabled = state_c['trailing_enabled']
            save_state_c()
            return __import__('flask').jsonify({'ok': True, 'enabled': enabled})
        return __import__('flask').jsonify({'error': 'Invalid strategy'}), 400
    except Exception as e:
        return __import__('flask').jsonify({'error': str(e)}), 500

# ── RESET ENDPOINTS ─────────────────────────────────────────────
@app.route('/reset/<strategy>', methods=['POST'])
def reset_strategy(strategy):
    # Ελέγχουμε session manually για να επιστρέφουμε JSON (όχι redirect)
    if 'username' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    """Reset μιας στρατηγικής στα default values."""
    from bot import state, state_b, state_c, state_d
    from bot import save_state, save_state_b, save_state_c, save_state_d
    from bot import DEFAULT_STATE, DEFAULT_STATE_B
    from database import db_save_state

    s = strategy.upper()
    if s not in ('A','B','C','D'):
        return jsonify({"error": "Invalid strategy"}), 400

    reset_balance = 10000.0

    if s == 'A':
        with state_lock:
            state.update({
                "balance": reset_balance, "pnl_total": 0,
                "wins": 0, "losses": 0, "position": None,
                "trades": [], "last_signal": "WAIT",
            })
        db_save_state("A", snapshot_state("A"))
        _reset_trades_db("A")
        save_state()
    elif s == 'B':
        with state_lock_b:
            state_b.update({
                "balance": reset_balance, "pnl_total": 0,
                "wins": 0, "losses": 0, "position": None,
                "trades": [], "last_signal": "WAIT",
            })
        db_save_state("B", snapshot_state("B"))
        _reset_trades_db("B")
        save_state_b()
    elif s == 'C':
        with state_lock_c:
            state_c.update({
                "balance": reset_balance, "pnl_total": 0,
                "wins": 0, "losses": 0, "position": None,
                "trades": [], "last_signal": "WAIT",
            })
        db_save_state("C", snapshot_state("C"))
        _reset_trades_db("C")
        save_state_c()
    elif s == 'D':
        with state_lock_d:
            state_d.update({
                "balance": reset_balance, "pnl_total": 0,
                "wins": 0, "losses": 0, "position": None,
                "trades": [], "last_signal": "WAIT",
            })
        db_save_state("D", snapshot_state("D"))
        _reset_trades_db("D")
        save_state_d()

    return jsonify({"ok": True, "strategy": s, "reset_to": reset_balance})


@app.route('/webhook/a', methods=['POST'])
def webhook_a():
    try:
        d=request.get_json(force=True) or {}; sig=d.get('signal','').upper(); px=float(d.get('price',0)) or None
        if sig not in ('LONG','SHORT'): return {'error':'Invalid'},400
        threading.Thread(target=lambda:_wh_a(sig,px,d),daemon=True).start()
        return {'ok':True,'strategy':'A'}
    except Exception as e: return {'error':str(e)},500

@app.route('/webhook/c', methods=['POST'])
def webhook_c():
    try:
        d=request.get_json(force=True) or {}; sig=d.get('signal','').upper(); px=float(d.get('price',0)) or None
        if sig not in ('LONG','SHORT'): return {'error':'Invalid'},400
        threading.Thread(target=lambda:_wh_c(sig,px,d),daemon=True).start()
        return {'ok':True,'strategy':'C'}
    except Exception as e: return {'error':str(e)},500

@app.route('/webhook/d', methods=['POST'])
def webhook_d():
    try:
        d=request.get_json(force=True) or {}; sig=d.get('signal','').upper(); px=float(d.get('price',0)) or None
        if sig not in ('LONG','SHORT'): return {'error':'Invalid'},400
        threading.Thread(target=lambda:_wh_d(sig,px,d),daemon=True).start()
        return {'ok':True,'strategy':'D'}
    except Exception as e: return {'error':str(e)},500

@app.route('/webhook/smc', methods=['POST'])
def webhook_smc():
    try:
        d=request.get_json(force=True) or {}; sig=d.get('signal','').upper(); px=float(d.get('price',0)) or None
        if sig not in ('LONG','SHORT'): return {'error':'Invalid'},400
        threading.Thread(target=lambda:_wh_smc(sig,px,d),daemon=True).start()
        return {'ok':True,'strategy':'SMC'}
    except Exception as e: return {'error':str(e)},500

if __name__ == '__main__':
    print(f'\n🚀 NRM Bot starting on port {PORT}')
    app.run(host='0.0.0.0', port=PORT, debug=False)
