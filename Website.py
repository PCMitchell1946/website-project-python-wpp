import os
import threading
import time
import logging
from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from pathlib import Path
from datetime import datetime
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

# Secret key should come from the environment in production
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(24)

# Security-related cookie settings
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# SESSION_COOKIE_SECURE defaults to True in non-debug; can be forced via env var
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', str(not app.debug)).lower() in ('1', 'true', 'yes')

# Limit request sizes (e.g., form submissions)
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024  # 8 KB

# Apply strong security headers (CSP, HSTS, Referrer Policy, etc.)
# Force HTTPS and HSTS in production by default but allow toggling via env vars
_FORCE_HTTPS = os.environ.get('GUESTBOOK_FORCE_HTTPS', '')
if _FORCE_HTTPS == '':
    _force_https = not app.debug
else:
    _force_https = _FORCE_HTTPS.lower() in ('1', 'true', 'yes')

Talisman(
    app,
    content_security_policy={"default-src": ["'self'"]},
    force_https=_force_https,
    strict_transport_security=True,
    strict_transport_security_max_age=31536000,  # 1 year
    strict_transport_security_include_subdomains=True,
    strict_transport_security_preload=True,
    session_cookie_secure=app.config['SESSION_COOKIE_SECURE'],
    frame_options='SAMEORIGIN',
    referrer_policy='strict-origin-when-cross-origin',
)

# Rate limiting to reduce spam/abuse
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=["200 per day", "50 per hour"])

# SQLite DB path
DB_PATH = Path(__file__).parent / 'guestbook.db'


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        '''
    )
    conn.commit()
    conn.close()


# Initialize the database when the module is imported (simple and reliable)
init_db()

# -----------------------------
# Lightweight in-memory cache and DB poller
# - Configurable via environment variables
# - Uses file mtime to avoid unnecessary DB queries
# - Default poll interval: 10s (tunable)
# -----------------------------
POLL_INTERVAL = int(os.environ.get('GUESTBOOK_POLL_INTERVAL', '10'))
ENABLE_POLLER = os.environ.get('GUESTBOOK_ENABLE_POLLER', '1') == '1'
USE_CACHE = os.environ.get('GUESTBOOK_USE_CACHE', '1') == '1'

_CACHE_LOCK = threading.Lock()
_entries_cache = []  # newest-first, list of dicts with id,name,message,created_at
_last_id = 0
_last_mtime = None


def _load_initial_cache():
    """Load the newest 100 entries into the in-memory cache."""
    global _entries_cache, _last_id, _last_mtime
    try:
        conn = get_db_connection()
        cur = conn.execute('SELECT id, name, message, created_at FROM entries ORDER BY id DESC LIMIT 100')
        rows = cur.fetchall()
        conn.close()
        with _CACHE_LOCK:
            _entries_cache = [dict(r) for r in rows]
            if rows:
                _last_id = rows[0]['id']
        try:
            _last_mtime = DB_PATH.stat().st_mtime
        except OSError:
            _last_mtime = None
    except Exception:
        logging.exception('Failed to load initial cache')


def _poll_db(interval):
    """Background thread that checks file mtime and pulls new rows if the DB changed."""
    global _entries_cache, _last_id, _last_mtime
    while True:
        try:
            try:
                mtime = DB_PATH.stat().st_mtime
            except OSError:
                time.sleep(interval)
                continue

            if _last_mtime is None:
                _last_mtime = mtime
            elif mtime != _last_mtime:
                conn = get_db_connection()
                cur = conn.execute('SELECT id, name, message, created_at FROM entries WHERE id > ? ORDER BY id DESC', (_last_id,))
                rows = cur.fetchall()
                conn.close()
                if rows:
                    with _CACHE_LOCK:
                        new = [dict(r) for r in rows]
                        _entries_cache = new + _entries_cache
                        _last_id = max(_last_id, rows[0]['id'])
                _last_mtime = mtime
        except Exception:
            logging.exception('DB poller error')
        time.sleep(interval)


_poller_started = False

@app.before_request
def _ensure_poller_started():
    """Ensure the poller and cache are started on the first incoming request.
    Uses a simple flag so the work is only done once per process."""
    global _poller_started
    if not _poller_started:
        _poller_started = True
        if USE_CACHE:
            _load_initial_cache()
        if ENABLE_POLLER and USE_CACHE:
            t = threading.Thread(target=_poll_db, args=(POLL_INTERVAL,), daemon=True)
            t.start()


@app.route('/')
def index():
    if USE_CACHE:
        with _CACHE_LOCK:
            entries = list(_entries_cache)  # copy to avoid holding lock during render
        return render_template('index.html', entries=entries)

    conn = get_db_connection()
    cur = conn.execute('SELECT name, message, created_at FROM entries ORDER BY id DESC LIMIT 100')
    entries = cur.fetchall()
    conn.close()
    return render_template('index.html', entries=entries)


@app.route('/submit', methods=['POST'])
@limiter.limit('10 per minute')
def submit():
    name = request.form.get('name', '').strip() or 'Anonymous'
    message = request.form.get('message', '').strip()

    # Basic validation
    if not message:
        flash('Message is required.', 'error')
        return redirect(url_for('index'))
    if len(name) > 50:
        flash('Name must be 50 characters or fewer.', 'error')
        return redirect(url_for('index'))
    if len(message) > 1000:
        flash('Message is too long (max 1000 characters).', 'error')
        return redirect(url_for('index'))

    created_at = datetime.utcnow().isoformat()
    conn = get_db_connection()
    cur = conn.execute(
        'INSERT INTO entries (name, message, created_at) VALUES (?, ?, ?)',
        (name, message, created_at),
    )
    conn.commit()
    last_row_id = cur.lastrowid
    conn.close()

    # Update cache immediately for lower latency
    if USE_CACHE:
        try:
            with _CACHE_LOCK:
                new = {'id': last_row_id, 'name': name, 'message': message, 'created_at': created_at}
                _entries_cache = [new] + _entries_cache
                global _last_id
                _last_id = max(_last_id, last_row_id)
        except Exception:
            logging.exception('Failed to update cache on submit')

    flash('Thanks — your message was posted!', 'success')
    return redirect(url_for('index'))


if __name__ == '__main__':
    # Support optional local SSL using environment variables (for development/testing):
    # set GUESTBOOK_SSL_CERT and GUESTBOOK_SSL_KEY to paths of cert/key files
    ssl_cert = os.environ.get('GUESTBOOK_SSL_CERT')
    ssl_key = os.environ.get('GUESTBOOK_SSL_KEY')
    ssl_context = (ssl_cert, ssl_key) if ssl_cert and ssl_key else None

    app.run(debug=True, host='127.0.0.1', port=5000, ssl_context=ssl_context)
