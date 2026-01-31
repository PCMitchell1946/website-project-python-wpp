# Guestbook (Flask) - Minimal Example

Simple guestbook app for learning Flask.

Quick start

1. Create and activate a virtual environment (recommended).
2. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

3. Run locally:

```powershell
python Website.py
```

Open http://127.0.0.1:5000 in your browser.

Notes
- The app now persists entries to a local SQLite database file `guestbook.db` (auto-created on first run).
- The app uses basic input validation and displays success/error messages.

Deploy
- A simple `Procfile` is included for deploy targets like Render or Heroku.
- For Render: create a new Python web service, connect your repo, and Render will use `requirements.txt` and the `Procfile`.

Security notes for deployment
- Set a strong secret key before deploying: in your host service set the environment variable `SECRET_KEY` to a long, random value.
- Ensure your service uses HTTPS. Secure cookies (`SESSION_COOKIE_SECURE`) are enabled by default when not in debug mode.
- Rate limiting and security headers are enabled (via `Flask-Limiter` and `flask-talisman`).
- To set `SECRET_KEY` locally on Windows PowerShell before starting the app:

```powershell
$env:SECRET_KEY = 'replace-with-a-secure-random-value'
python app.py
```

---

## Sharing your local site (alpha testing) ✅

Two recommended ways to share your local server with friends:

A) Quick & easy — **ngrok** (no router changes)
- Install and sign up at https://ngrok.com. Save your authtoken (`ngrok authtoken <token>`).
- In PowerShell (repo root):
  - `.\	ools\start_ngrok.ps1` (or run `ngrok http 5000` directly)
- ngrok will print a public HTTPS URL (e.g., `https://abcd-1234.ngrok.io`) that you can share.

B) More stable, production-like — **Caddy** + domain (requires DNS & port forwarding)
- Edit `Caddyfile` in the repo root and set your domain and email.
- Make sure your domain points to your public IP (A record) and forward ports 80/443 on your router to your PC.
- Start Caddy: `.\tools\start_caddy.ps1` (requires `caddy.exe` on PATH).

Notes & safety:
- For quick tests, ngrok is easiest and provides HTTPS by default. It is ideal for alpha testing.
- For long-running public sites, use Caddy or nginx + Let's Encrypt and follow security hardening steps (set `DEBUG=False`, keep `SECRET_KEY` secret, enable firewall rules and monitor logs).

