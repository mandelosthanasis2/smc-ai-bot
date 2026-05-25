"""
auth.py — Login, Register, Settings, Admin για NRM Bot
Προσθέτει authentication χωρίς να αγγίζει το υπάρχον bot logic.
"""

from flask import Blueprint, render_template_string, request, redirect, url_for, session, jsonify
from functools import wraps
from database import (
    get_user_by_username, create_user, verify_password, change_password,
    get_user_settings, save_user_settings, get_all_users, get_admin_stats,
    approve_live_trading, reject_live_trading, toggle_user_active, request_live_trading
)

auth_bp = Blueprint('auth', __name__)

# ─────────────────────────────────────────────
# DECORATORS
# ─────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        if session.get('role') != 'admin':
            return redirect('/')
        return f(*args, **kwargs)
    return decorated

# ─────────────────────────────────────────────
# SHARED CSS
# ─────────────────────────────────────────────

BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0a0f1a; --bg2: #0f1623; --bg3: #111c2a;
  --border: #1e2a3a; --text: #e8f0fe; --text2: #4a6580; --text3: #2a3a4a;
  --blue: #3b8ef3; --green: #4ade80; --red: #f87171; --yellow: #facc15;
}
body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; min-height: 100vh; }
.card { background: var(--bg3); border: 0.5px solid var(--border); border-radius: 12px; padding: 24px; }
.btn { width: 100%; background: var(--blue); border: none; border-radius: 8px; padding: 12px; color: #fff; font-size: 14px; font-weight: 500; cursor: pointer; transition: opacity 0.2s; }
.btn:hover { opacity: 0.85; }
.btn-danger { background: #dc2626; }
.btn-success { background: #16a34a; }
.btn-sm { width: auto; padding: 5px 14px; font-size: 12px; border-radius: 6px; }
.input-group { margin-bottom: 14px; }
.input-group label { display: block; font-size: 11px; color: var(--text2); margin-bottom: 5px; }
.input-group input, .input-group select { width: 100%; background: #0a1120; border: 0.5px solid var(--border); border-radius: 8px; padding: 10px 12px; color: var(--text); font-size: 14px; outline: none; }
.input-group input:focus { border-color: var(--blue); }
.alert { padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-bottom: 14px; }
.alert-error { background: rgba(248,113,113,0.1); border: 0.5px solid rgba(248,113,113,0.3); color: #f87171; }
.alert-success { background: rgba(74,222,128,0.1); border: 0.5px solid rgba(74,222,128,0.3); color: #4ade80; }
.badge { font-size: 10px; padding: 3px 8px; border-radius: 5px; font-weight: 500; }
.badge-live { background: #14532d; color: #4ade80; }
.badge-paper { background: #1a1a0a; color: #facc15; border: 0.5px solid #3a3010; }
.badge-admin { background: #1e1b4b; color: #818cf8; }
.badge-pending { background: #1c1410; color: #fb923c; }
"""

# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────

LOGIN_HTML = """
<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NRM Bot — Login</title>
<style>""" + BASE_CSS + """
.wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
.logo-icon { width: 56px; height: 56px; background: var(--bg3); border-radius: 14px; display: flex; align-items: center; justify-content: center; margin: 0 auto 12px; border: 0.5px solid var(--border); font-size: 28px; }
.logo-title { font-size: 22px; font-weight: 600; color: var(--text); text-align: center; }
.logo-sub { font-size: 13px; color: var(--text2); text-align: center; margin-top: 4px; margin-bottom: 28px; }
.footer { text-align: center; margin-top: 16px; font-size: 12px; color: var(--text2); }
.footer a { color: var(--blue); text-decoration: none; }
</style></head><body>
<div class="wrap">
  <div style="width:100%;max-width:360px;">
    <div class="logo-icon">🤖</div>
    <div class="logo-title">NRM Bot</div>
    <div class="logo-sub">Automated crypto trading</div>
    <div class="card">
      {% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}
      <form method="POST">
        <div class="input-group">
          <label>Username</label>
          <input type="text" name="username" placeholder="Enter username" required autofocus>
        </div>
        <div class="input-group">
          <label>Password</label>
          <input type="password" name="password" placeholder="Enter password" required>
        </div>
        <button class="btn" type="submit">Sign in</button>
      </form>
    </div>
    <div class="footer">Don't have an account? <a href="/register">Sign up</a></div>
  </div>
</div>
<script>
function sendBriefing(session_type) {
  var labels = {morning:'🌅 Πρωινό', midday:'☀️ Μεσημεριανό', evening:'🌙 Βραδινό'};
  var btn = event.target;
  btn.disabled = true;
  btn.textContent = 'Αποστολή...';
  fetch('/admin/briefing', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session: session_type})
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) {
      btn.textContent = '✅ Εστάλη!';
      btn.style.color = '#4ade80';
    } else {
      btn.textContent = '❌ Error';
      btn.style.color = '#f87171';
      alert('Error: ' + (d.error || 'unknown'));
    }
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = labels[session_type] || session_type;
    }, 3000);
  })
  .catch(e => {
    btn.disabled = false;
    btn.textContent = '❌ Error';
    alert('Error: ' + e);
  });
}
</script>
</body></html>
"""

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect('/')
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = verify_password(username, password)
        if user:
            session['user_id']  = user['id']
            session['username'] = user['username']
            session['role']     = user['role']
            return redirect('/')
        else:
            error = 'Wrong username or password.'
    return render_template_string(LOGIN_HTML, error=error)

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# ─────────────────────────────────────────────
# REGISTER
# ─────────────────────────────────────────────

REGISTER_HTML = """
<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NRM Bot — Register</title>
<style>""" + BASE_CSS + """
.wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
.logo-title { font-size: 20px; font-weight: 600; color: var(--text); text-align: center; margin-bottom: 4px; }
.logo-sub { font-size: 13px; color: var(--text2); text-align: center; margin-bottom: 24px; }
.footer { text-align: center; margin-top: 16px; font-size: 12px; color: var(--text2); }
.footer a { color: var(--blue); text-decoration: none; }
</style></head><body>
<div class="wrap">
  <div style="width:100%;max-width:360px;">
    <div style="font-size:28px;text-align:center;margin-bottom:8px;">🤖</div>
    <div class="logo-title">Create account</div>
    <div class="logo-sub">NRM Bot — Automated trading</div>
    <div class="card">
      {% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}
      {% if success %}<div class="alert alert-success">{{ success }}</div>{% endif %}
      <form method="POST">
        <div class="input-group">
          <label>Username</label>
          <input type="text" name="username" placeholder="Choose a username" required>
        </div>
        <div class="input-group">
          <label>Email (optional)</label>
          <input type="email" name="email" placeholder="your@email.com">
        </div>
        <div class="input-group">
          <label>Password</label>
          <input type="password" name="password" placeholder="Min 6 characters" required>
        </div>
        <div class="input-group">
          <label>Confirm password</label>
          <input type="password" name="password2" placeholder="Repeat password" required>
        </div>
        <button class="btn" type="submit">Create account</button>
      </form>
    </div>
    <div class="footer">Already have an account? <a href="/login">Sign in</a></div>
  </div>
</div>
<script>
function sendBriefing(session_type) {
  var labels = {morning:'🌅 Πρωινό', midday:'☀️ Μεσημεριανό', evening:'🌙 Βραδινό'};
  var btn = event.target;
  btn.disabled = true;
  btn.textContent = 'Αποστολή...';
  fetch('/admin/briefing', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session: session_type})
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) {
      btn.textContent = '✅ Εστάλη!';
      btn.style.color = '#4ade80';
    } else {
      btn.textContent = '❌ Error';
      btn.style.color = '#f87171';
      alert('Error: ' + (d.error || 'unknown'));
    }
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = labels[session_type] || session_type;
    }, 3000);
  })
  .catch(e => {
    btn.disabled = false;
    btn.textContent = '❌ Error';
    alert('Error: ' + e);
  });
}
</script>
</body></html>
"""

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    success = None
    if request.method == 'POST':
        username  = request.form.get('username', '').strip()
        email     = request.form.get('email', '').strip() or None
        password  = request.form.get('password', '')
        password2 = request.form.get('password2', '')

        if len(username) < 3:
            error = 'Username must be at least 3 characters.'
        elif len(password) < 6:
            error = 'Password must be at least 6 characters.'
        elif password != password2:
            error = 'Passwords do not match.'
        elif get_user_by_username(username):
            error = 'Username already exists.'
        else:
            user = create_user(username, password, email)
            if user:
                success = 'Account created! You can now sign in.'
            else:
                error = 'Something went wrong. Please try again.'
    return render_template_string(REGISTER_HTML, error=error, success=success)

# ─────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────

SETTINGS_HTML = """
<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NRM Bot — Settings</title>
<style>""" + BASE_CSS + """
.layout { display: flex; min-height: 100vh; }
.sidebar { width: 200px; background: #080d14; border-right: 0.5px solid var(--border); padding: 16px 0; flex-shrink: 0; }
.sb-logo { display: flex; align-items: center; gap: 8px; padding: 0 16px 20px; font-size: 15px; font-weight: 600; }
.sb-item { display: flex; align-items: center; gap: 10px; padding: 9px 16px; font-size: 13px; color: var(--text2); text-decoration: none; }
.sb-item:hover, .sb-item.active { color: var(--blue); background: #0f1d2e; }
.main { flex: 1; padding: 28px; max-width: 700px; }
.page-title { font-size: 18px; font-weight: 600; margin-bottom: 24px; }
.section { margin-bottom: 24px; }
.section-title { font-size: 11px; color: var(--text2); letter-spacing: 0.5px; margin-bottom: 10px; }
.settings-card { background: var(--bg3); border: 0.5px solid var(--border); border-radius: 12px; overflow: hidden; }
.settings-item { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; border-bottom: 0.5px solid var(--border); }
.settings-item:last-child { border-bottom: none; }
.settings-item-left { display: flex; flex-direction: column; gap: 2px; }
.settings-item-title { font-size: 13px; color: var(--text); }
.settings-item-sub { font-size: 11px; color: var(--text2); }
.toggle-wrap { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text2); }
.range-wrap { display: flex; align-items: center; gap: 10px; }
.range-wrap input[type=range] { width: 120px; }
.range-val { font-size: 13px; font-weight: 600; color: var(--blue); min-width: 36px; }
.request-btn { background: rgba(59,142,243,0.15); border: 0.5px solid rgba(59,142,243,0.4); color: var(--blue); border-radius: 6px; padding: 6px 14px; font-size: 12px; cursor: pointer; }
.approved-badge { background: #14532d; color: #4ade80; padding: 6px 14px; border-radius: 6px; font-size: 12px; }
.pending-badge { background: #1c1410; color: #fb923c; padding: 6px 14px; border-radius: 6px; font-size: 12px; }
.ai-badge { display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:4px;font-size:10px;font-weight:600; }
.ai-badge-shadow { background:rgba(250,204,21,0.1);color:#facc15;border:0.5px solid rgba(250,204,21,0.3); }
.ai-badge-active { background:rgba(74,222,128,0.1);color:#4ade80;border:0.5px solid rgba(74,222,128,0.3); }
.ai-badge-off    { background:rgba(255,255,255,0.05);color:#4a6580;border:0.5px solid #1e2a3a; }
@media(max-width:700px){.sidebar{display:none;}.main{padding:16px;}}
</style></head><body>
<div class="layout">
  <div class="sidebar">
    <div class="sb-logo">🤖 NRM Bot</div>
    <a class="sb-item" href="/">📊 Dashboard</a>
    <a class="sb-item" href="/analytics">📈 Analytics</a>
    <a class="sb-item active" href="/settings">⚙️ Settings</a>
    {% if role == 'admin' %}<a class="sb-item" href="/admin">🛡️ Admin</a>{% endif %}
    <a class="sb-item" href="/logout" style="margin-top:auto;color:var(--red);">🚪 Logout</a>
  </div>
  <div class="main">
    <div class="page-title">Settings</div>
    {% if success %}<div class="alert alert-success">{{ success }}</div>{% endif %}
    {% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}
    <form method="POST">

      <div class="section">
        <div class="section-title">EXCHANGE — BITGET</div>
        <div class="card" style="padding:20px;">
          <div class="input-group">
            <label>API Key</label>
            <input type="text" name="bitget_api_key" value="{{ s.bitget_api_key or '' }}" placeholder="Bitget API key">
          </div>
          <div class="input-group">
            <label>Secret Key</label>
            <input type="password" name="bitget_secret_key" value="{{ s.bitget_secret_key or '' }}" placeholder="Bitget secret key">
          </div>
          <div class="input-group" style="margin-bottom:0;">
            <label>Passphrase</label>
            <input type="password" name="bitget_passphrase" value="{{ s.bitget_passphrase or '' }}" placeholder="Bitget passphrase">
          </div>
        </div>
      </div>

      <div class="section">
        <div class="section-title">NOTIFICATIONS — TELEGRAM (OPTIONAL)</div>
        <div class="card" style="padding:20px;">
          <div class="input-group">
            <label>Bot Token</label>
            <input type="text" name="telegram_token" value="{{ s.telegram_token or '' }}" placeholder="Leave empty to disable">
          </div>
          <div class="input-group" style="margin-bottom:0;">
            <label>Chat ID</label>
            <input type="text" name="telegram_chat_id" value="{{ s.telegram_chat_id or '' }}" placeholder="Your Telegram chat ID">
          </div>
        </div>
      </div>

      <div class="section">
        <div class="section-title">RISK MANAGEMENT</div>
        <div class="settings-card">
          <div class="settings-item">
            <div class="settings-item-left">
              <div class="settings-item-title">Risk per trade</div>
              <div class="settings-item-sub">% of capital per trade</div>
            </div>
            <div class="range-wrap">
              <input type="range" name="risk_percent" min="0.5" max="5" step="0.5"
                value="{{ s.risk_percent or 2.0 }}"
                oninput="document.getElementById('risk-val').textContent=this.value+'%'">
              <div class="range-val" id="risk-val">{{ s.risk_percent or 2.0 }}%</div>
            </div>
          </div>
        </div>
      </div>

      <div class="section">
        <div class="section-title">STRATEGIES</div>
        <div class="settings-card">
          {% for strat, label in [('a','Strategy A — Daily Box + 1H RSI'),('b','Strategy B — 1H Box + 15m RSI'),('c','Strategy C — 1H Box + Webhook'),('d','Strategy D — Order Block + FVG')] %}
          <div class="settings-item">
            <div class="settings-item-left">
              <div class="settings-item-title">{{ label }}</div>
            </div>
            <div class="toggle-wrap">
              <span>Off</span>
              <label style="position:relative;display:inline-block;width:36px;height:20px;">
                <input type="checkbox" name="strategy_{{ strat }}" style="opacity:0;width:0;height:0;"
                  {% if s['strategy_' + strat] %}checked{% endif %}>
                <span style="position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:{% if s['strategy_' + strat] %}#4ade80{% else %}#1e3a5a{% endif %};border-radius:10px;transition:0.2s;"></span>
              </label>
              <span>On</span>
            </div>
          </div>
          {% endfor %}
        </div>
      </div>

      <div class="section">
        <div class="section-title">AI VALIDATOR</div>
        <div class="settings-card">

          <div class="settings-item">
            <div class="settings-item-left">
              <div class="settings-item-title">AI Validator</div>
              <div class="settings-item-sub">Αναλύει κάθε signal πριν εκτελεστεί</div>
            </div>
            <div class="toggle-wrap">
              <span>Off</span>
              <label style="position:relative;display:inline-block;width:36px;height:20px;">
                <input type="checkbox" name="ai_validator_enabled" style="opacity:0;width:0;height:0;"
                  {% if s.get('ai_validator_enabled', True) %}checked{% endif %}
                  onchange="updateAiBadge()">
                <span id="ai-enabled-track" style="position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:{% if s.get('ai_validator_enabled', True) %}#4ade80{% else %}#1e3a5a{% endif %};border-radius:10px;transition:0.2s;"></span>
              </label>
              <span>On</span>
            </div>
          </div>

          <div class="settings-item">
            <div class="settings-item-left">
              <div class="settings-item-title">Shadow Mode</div>
              <div class="settings-item-sub">Καταγράφει αποφάσεις χωρίς να τις εφαρμόζει</div>
            </div>
            <div style="display:flex;align-items:center;gap:10px;">
              <span id="shadow-badge" class="ai-badge {% if s.get('ai_shadow_mode', True) %}ai-badge-shadow{% else %}ai-badge-active{% endif %}">
                {% if s.get('ai_shadow_mode', True) %}👁 SHADOW{% else %}⚡ ACTIVE{% endif %}
              </span>
              <div class="toggle-wrap">
                <span>Active</span>
                <label style="position:relative;display:inline-block;width:36px;height:20px;">
                  <input type="checkbox" name="ai_shadow_mode" style="opacity:0;width:0;height:0;"
                    {% if s.get('ai_shadow_mode', True) %}checked{% endif %}
                    onchange="updateShadowBadge(this)">
                  <span id="shadow-track" style="position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:{% if s.get('ai_shadow_mode', True) %}#4ade80{% else %}#1e3a5a{% endif %};border-radius:10px;transition:0.2s;"></span>
                </label>
                <span>Shadow</span>
              </div>
            </div>
          </div>

          <div class="settings-item" style="background:rgba(250,204,21,0.03);">
            <div class="settings-item-left" style="gap:6px;">
              <div class="settings-item-title" style="font-size:11px;color:#facc15;">⚠️ Πότε να απενεργοποιήσεις το Shadow Mode</div>
              <div class="settings-item-sub" style="line-height:1.6;">
                Άφησε Shadow Mode ON για τουλάχιστον <strong style="color:var(--text);">50 trades</strong>.<br>
                Μετά σύγκρινε: trades που ο AI θα έκοβε (SKIP) — ήταν losses;<br>
                Αν ναι σε > 60%, ενεργοποίησε το AI filter.
              </div>
            </div>
          </div>

        </div>
      </div>

      <div class="section">
        <div class="section-title">TRADING MODE</div>
        <div class="settings-card">
          <div class="settings-item">
            <div class="settings-item-left">
              <div class="settings-item-title">Current mode</div>
              <div class="settings-item-sub">
                {% if s.trading_mode == 'live' %}
                  <span class="badge badge-live">Live Trading</span>
                {% elif user.live_trading_requested %}
                  <span class="badge badge-pending">Request pending...</span>
                {% else %}
                  <span class="badge badge-paper">Paper Trading</span>
                {% endif %}
              </div>
            </div>
            <div>
              {% if s.trading_mode == 'live' %}
                <span class="approved-badge">✓ Approved</span>
              {% elif user.live_trading_requested %}
                <span class="pending-badge">⏳ Pending</span>
              {% else %}
                <button type="button" class="request-btn" onclick="requestLive()">Request Live Trading</button>
              {% endif %}
            </div>
          </div>
        </div>
      </div>

      <button class="btn" type="submit">Save settings</button>
    </form>

    <div class="section" style="margin-top:24px;">
      <div class="section-title">SECURITY</div>
      <div class="card" style="padding:20px;">
        <a href="/change-password" style="color:var(--blue);font-size:13px;text-decoration:none;">Change password →</a>
      </div>
    </div>

  </div>
</div>
<script>
function requestLive() {
  if (!confirm('Request live trading approval from admin?')) return;
  fetch('/request-live', {method:'POST'})
    .then(r => r.json())
    .then(d => { if(d.ok) location.reload(); });
}
function updateShadowBadge(cb) {
  const badge = document.getElementById('shadow-badge');
  const track = document.getElementById('shadow-track');
  if (cb.checked) {
    badge.className = 'ai-badge ai-badge-shadow';
    badge.textContent = '👁 SHADOW';
    track.style.background = '#4ade80';
  } else {
    badge.className = 'ai-badge ai-badge-active';
    badge.textContent = '⚡ ACTIVE';
    track.style.background = '#1e3a5a';
  }
}
</script>
<script>
function sendBriefing(session_type) {
  var labels = {morning:'🌅 Πρωινό', midday:'☀️ Μεσημεριανό', evening:'🌙 Βραδινό'};
  var btn = event.target;
  btn.disabled = true;
  btn.textContent = 'Αποστολή...';
  fetch('/admin/briefing', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session: session_type})
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) {
      btn.textContent = '✅ Εστάλη!';
      btn.style.color = '#4ade80';
    } else {
      btn.textContent = '❌ Error';
      btn.style.color = '#f87171';
      alert('Error: ' + (d.error || 'unknown'));
    }
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = labels[session_type] || session_type;
    }, 3000);
  })
  .catch(e => {
    btn.disabled = false;
    btn.textContent = '❌ Error';
    alert('Error: ' + e);
  });
}
</script>
</body></html>
"""

@auth_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user_id = session['user_id']
    from database import get_user_by_id
    user = get_user_by_id(user_id) or {}
    s = get_user_settings(user_id) or {}
    s.setdefault('bitget_api_key', '')
    s.setdefault('bitget_secret_key', '')
    s.setdefault('bitget_passphrase', '')
    s.setdefault('telegram_token', '')
    s.setdefault('telegram_chat_id', '')
    s.setdefault('risk_percent', 2.0)
    s.setdefault('strategy_a', True)
    s.setdefault('strategy_b', True)
    s.setdefault('strategy_c', True)
    s.setdefault('strategy_d', True)
    s.setdefault('trading_mode', 'paper')
    s.setdefault('ai_validator_enabled', True)
    s.setdefault('ai_shadow_mode', True)
    error = success = None
    if request.method == 'POST':
        new_settings = {
            'bitget_api_key':       request.form.get('bitget_api_key', '').strip(),
            'bitget_secret_key':    request.form.get('bitget_secret_key', '').strip(),
            'bitget_passphrase':    request.form.get('bitget_passphrase', '').strip(),
            'telegram_token':       request.form.get('telegram_token', '').strip(),
            'telegram_chat_id':     request.form.get('telegram_chat_id', '').strip(),
            'risk_percent':         float(request.form.get('risk_percent', 2.0)),
            'strategy_a':           'strategy_a' in request.form,
            'strategy_b':           'strategy_b' in request.form,
            'strategy_c':           'strategy_c' in request.form,
            'strategy_d':           'strategy_d' in request.form,
            'trading_mode':         s.get('trading_mode', 'paper'),
            'ai_validator_enabled': 'ai_validator_enabled' in request.form,
            'ai_shadow_mode':       'ai_shadow_mode' in request.form,
        }
        if save_user_settings(user_id, new_settings):
            s = new_settings
            success = 'Settings saved!'
        else:
            error = 'Failed to save settings.'
    return render_template_string(SETTINGS_HTML, s=s, user=user,
                                   role=session.get('role'), error=error, success=success)

@auth_bp.route('/request-live', methods=['POST'])
@login_required
def request_live():
    ok = request_live_trading(session['user_id'])
    return jsonify({'ok': ok})

# ─────────────────────────────────────────────
# CHANGE PASSWORD
# ─────────────────────────────────────────────

CHANGE_PW_HTML = """
<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NRM Bot — Change Password</title>
<style>""" + BASE_CSS + """
.wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
.back { display:block; text-align:center; margin-top:14px; color:var(--text2); font-size:12px; text-decoration:none; }
.back:hover { color: var(--blue); }
</style></head><body>
<div class="wrap">
  <div style="width:100%;max-width:360px;">
    <div style="font-size:15px;font-weight:600;margin-bottom:20px;text-align:center;">Change Password</div>
    <div class="card">
      {% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}
      {% if success %}<div class="alert alert-success">{{ success }}</div>{% endif %}
      <form method="POST">
        <div class="input-group">
          <label>Current password</label>
          <input type="password" name="current_password" required>
        </div>
        <div class="input-group">
          <label>New password</label>
          <input type="password" name="new_password" required>
        </div>
        <div class="input-group">
          <label>Confirm new password</label>
          <input type="password" name="new_password2" required>
        </div>
        <button class="btn" type="submit">Update password</button>
      </form>
    </div>
    <a class="back" href="/settings">← Back to settings</a>
  </div>
</div>
<script>
function sendBriefing(session_type) {
  var labels = {morning:'🌅 Πρωινό', midday:'☀️ Μεσημεριανό', evening:'🌙 Βραδινό'};
  var btn = event.target;
  btn.disabled = true;
  btn.textContent = 'Αποστολή...';
  fetch('/admin/briefing', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session: session_type})
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) {
      btn.textContent = '✅ Εστάλη!';
      btn.style.color = '#4ade80';
    } else {
      btn.textContent = '❌ Error';
      btn.style.color = '#f87171';
      alert('Error: ' + (d.error || 'unknown'));
    }
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = labels[session_type] || session_type;
    }, 3000);
  })
  .catch(e => {
    btn.disabled = false;
    btn.textContent = '❌ Error';
    alert('Error: ' + e);
  });
}
</script>
</body></html>
"""

@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password_route():
    error = success = None
    if request.method == 'POST':
        current  = request.form.get('current_password', '')
        new_pw   = request.form.get('new_password', '')
        new_pw2  = request.form.get('new_password2', '')
        user = verify_password(session['username'], current)
        if not user:
            error = 'Current password is wrong.'
        elif len(new_pw) < 6:
            error = 'New password must be at least 6 characters.'
        elif new_pw != new_pw2:
            error = 'Passwords do not match.'
        else:
            if change_password(session['user_id'], new_pw):
                success = 'Password updated!'
            else:
                error = 'Failed to update password.'
    return render_template_string(CHANGE_PW_HTML, error=error, success=success)

# ─────────────────────────────────────────────
# ADMIN PANEL
# ─────────────────────────────────────────────

ADMIN_HTML = """
<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NRM Bot — Admin</title>
<style>""" + BASE_CSS + """
.layout { display: flex; min-height: 100vh; }
.sidebar { width: 200px; background: #080d14; border-right: 0.5px solid var(--border); padding: 16px 0; flex-shrink: 0; }
.sb-logo { display: flex; align-items: center; gap: 8px; padding: 0 16px 20px; font-size: 15px; font-weight: 600; }
.sb-item { display: flex; align-items: center; gap: 10px; padding: 9px 16px; font-size: 13px; color: var(--text2); text-decoration: none; }
.sb-item:hover, .sb-item.active { color: var(--blue); background: #0f1d2e; }
.main { flex: 1; padding: 28px; }
.page-title { font-size: 18px; font-weight: 600; margin-bottom: 24px; }
.stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 28px; }
.stat { background: var(--bg3); border: 0.5px solid var(--border); border-radius: 10px; padding: 16px; }
.stat-lbl { font-size: 10px; color: var(--text2); margin-bottom: 6px; }
.stat-val { font-size: 22px; font-weight: 600; }
table { width: 100%; border-collapse: collapse; background: var(--bg3); border-radius: 10px; overflow: hidden; border: 0.5px solid var(--border); }
th { font-size: 10px; color: var(--text2); text-align: left; padding: 10px 14px; border-bottom: 0.5px solid var(--border); font-weight: 500; }
td { font-size: 12px; padding: 10px 14px; border-bottom: 0.5px solid var(--border); vertical-align: middle; }
tr:last-child td { border-bottom: none; }
.action-btn { border: none; border-radius: 5px; padding: 4px 10px; font-size: 11px; cursor: pointer; font-weight: 500; }
.btn-approve { background: #14532d; color: #4ade80; }
.btn-reject  { background: #450a0a; color: #f87171; }
.btn-disable { background: #1e2a3a; color: var(--text2); }
.btn-enable  { background: #1a2f4a; color: var(--blue); }
@media(max-width:700px){.sidebar{display:none;}.main{padding:16px;}}
</style></head><body>
<div class="layout">
  <div class="sidebar">
    <div class="sb-logo">🤖 NRM Bot</div>
    <a class="sb-item" href="/">📊 Dashboard</a>
    <a class="sb-item" href="/analytics">📈 Analytics</a>
    <a class="sb-item" href="/settings">⚙️ Settings</a>
    <a class="sb-item active" href="/admin">🛡️ Admin</a>
    <a class="sb-item" href="/logout" style="color:var(--red);">🚪 Logout</a>
  </div>
  <div class="main">
    <div class="page-title" style="display:flex;align-items:center;justify-content:space-between;">
      Admin Panel
      <div style="display:flex;gap:8px;">
        <button onclick="sendBriefing('morning')" style="background:#0f1d2e;color:#4ade80;border:1px solid #14532d;padding:7px 14px;border-radius:7px;font-size:11px;cursor:pointer;">🌅 Πρωινό Briefing</button>
        <button onclick="sendBriefing('midday')"  style="background:#0f1d2e;color:#facc15;border:1px solid #3a2f0a;padding:7px 14px;border-radius:7px;font-size:11px;cursor:pointer;">☀️ Μεσημεριανό</button>
        <button onclick="sendBriefing('evening')" style="background:#0f1d2e;color:#818cf8;border:1px solid #1e1b4b;padding:7px 14px;border-radius:7px;font-size:11px;cursor:pointer;">🌙 Βραδινό</button>
      </div>
    </div>
    {% if msg %}<div style="background:#0f1d2e;border:1px solid #14532d;color:#4ade80;padding:10px 14px;border-radius:8px;font-size:12px;margin-bottom:16px;">{{ msg }}</div>{% endif %}

    <div class="stats-row">
      <div class="stat"><div class="stat-lbl">Total Users</div><div class="stat-val">{{ stats.total_users }}</div></div>
      <div class="stat"><div class="stat-lbl">Active Users</div><div class="stat-val" style="color:var(--green);">{{ stats.active_users }}</div></div>
      <div class="stat"><div class="stat-lbl">Live Trading</div><div class="stat-val" style="color:var(--blue);">{{ stats.live_users }}</div></div>
      <div class="stat"><div class="stat-lbl">Pending Requests</div><div class="stat-val" style="color:var(--yellow);">{{ stats.pending_requests }}</div></div>
      <div class="stat"><div class="stat-lbl">Total Trades</div><div class="stat-val">{{ stats.total_trades }}</div></div>
    </div>

    <table>
      <thead>
        <tr>
          <th>User</th>
          <th>Role</th>
          <th>Mode</th>
          <th>Strategies</th>
          <th>Risk</th>
          <th>Status</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {% for u in users %}
        <tr>
          <td>
            <div style="font-weight:500;">{{ u.username }}</div>
            <div style="font-size:10px;color:var(--text2);">{{ u.email or '—' }}</div>
          </td>
          <td>
            <span class="badge {% if u.role == 'admin' %}badge-admin{% else %}badge-paper{% endif %}">
              {{ u.role }}
            </span>
          </td>
          <td>
            {% if u.trading_mode == 'live' %}
              <span class="badge badge-live">Live</span>
            {% elif u.live_trading_requested %}
              <span class="badge badge-pending">Pending</span>
            {% else %}
              <span class="badge badge-paper">Paper</span>
            {% endif %}
          </td>
          <td style="font-size:11px;color:var(--text2);">
            {% if u.strategy_a %}A{% endif %}
            {% if u.strategy_b %}B{% endif %}
            {% if u.strategy_c %}C{% endif %}
            {% if u.strategy_d %}D{% endif %}
          </td>
          <td>{{ u.risk_percent or 2.0 }}%</td>
          <td>
            {% if u.is_active %}
              <span style="color:var(--green);font-size:11px;">● Active</span>
            {% else %}
              <span style="color:var(--red);font-size:11px;">● Disabled</span>
            {% endif %}
          </td>
          <td style="display:flex;gap:4px;flex-wrap:wrap;">
            {% if u.live_trading_requested and not u.live_trading_approved %}
              <button class="action-btn btn-approve" onclick="adminAction('approve_live', {{ u.id }})">✓ Approve Live</button>
              <button class="action-btn btn-reject"  onclick="adminAction('reject_live',  {{ u.id }})">✗ Reject</button>
            {% endif %}
            {% if u.role != 'admin' %}
              {% if u.is_active %}
                <button class="action-btn btn-disable" onclick="adminAction('disable', {{ u.id }})">Disable</button>
              {% else %}
                <button class="action-btn btn-enable" onclick="adminAction('enable', {{ u.id }})">Enable</button>
              {% endif %}
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
<script>
function adminAction(action, userId) {
  const labels = {
    approve_live: 'Approve live trading?',
    reject_live:  'Reject live trading request?',
    disable:      'Disable this user?',
    enable:       'Enable this user?',
  };
  if (!confirm(labels[action] || 'Are you sure?')) return;
  fetch('/admin/action', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action, user_id: userId})
  }).then(r => r.json()).then(d => { if(d.ok) location.reload(); });
}
</script>
<script>
function sendBriefing(session_type) {
  var labels = {morning:'🌅 Πρωινό', midday:'☀️ Μεσημεριανό', evening:'🌙 Βραδινό'};
  var btn = event.target;
  btn.disabled = true;
  btn.textContent = 'Αποστολή...';
  fetch('/admin/briefing', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session: session_type})
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) {
      btn.textContent = '✅ Εστάλη!';
      btn.style.color = '#4ade80';
    } else {
      btn.textContent = '❌ Error';
      btn.style.color = '#f87171';
      alert('Error: ' + (d.error || 'unknown'));
    }
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = labels[session_type] || session_type;
    }, 3000);
  })
  .catch(e => {
    btn.disabled = false;
    btn.textContent = '❌ Error';
    alert('Error: ' + e);
  });
}
</script>
</body></html>
"""

@auth_bp.route('/admin')
@admin_required
def admin():
    users = get_all_users()
    stats = get_admin_stats()
    msg   = request.args.get('msg')
    return render_template_string(ADMIN_HTML, users=users, stats=stats, msg=msg)

@auth_bp.route('/admin/briefing', methods=['POST'])
@admin_required
def admin_briefing():
    """Στέλνει manual briefing στο Telegram."""
    import threading
    data = request.get_json() or {}
    session_type = data.get('session', 'morning')

    session_labels = {
        'morning': '🌅 ΠΡΩΙ',
        'midday':  '☀️ ΜΕΣΗΜΕΡΙ',
        'evening': '🌙 ΒΡΑΔΥ',
    }
    label = session_labels.get(session_type, '📊 MANUAL')

    try:
        from analysis_agent import run_briefing
        threading.Thread(target=run_briefing, args=(label,), daemon=True).start()
        return jsonify({"ok": True, "session": label})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@auth_bp.route('/admin/action', methods=['POST'])
@admin_required
def admin_action():
    data    = request.get_json() or {}
    action  = data.get('action')
    user_id = data.get('user_id')
    if not action or not user_id:
        return jsonify({'ok': False})
    if action == 'approve_live':
        ok = approve_live_trading(user_id)
    elif action == 'reject_live':
        ok = reject_live_trading(user_id)
    elif action == 'disable':
        ok = toggle_user_active(user_id, False)
    elif action == 'enable':
        ok = toggle_user_active(user_id, True)
    else:
        ok = False
    return jsonify({'ok': ok})
