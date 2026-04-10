"""Echo service that decodes JWT claims from the Authorization header.

Serves an HTML dashboard at / and JSON API at /api or any other path.
Stores the last 20 requests for display on the dashboard.
"""

import base64
import collections
import json
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# Store last N requests
_MAX_REQUESTS = 20
_requests = collections.deque(maxlen=_MAX_REQUESTS)


def _decode_token(auth_header):
    """Decode a Bearer JWT and return claims dict."""
    if not auth_header.startswith("Bearer "):
        return {"error": "No Bearer token found"}
    token = auth_header[7:]
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return {
            "sub": payload.get("sub"),
            "azp": payload.get("azp"),
            "iss": payload.get("iss"),
            "aud": payload.get("aud"),
            "groups": payload.get("groups"),
            "exp": payload.get("exp"),
            "iat": payload.get("iat"),
            "scope": payload.get("scope"),
            "client_id": payload.get("client_id"),
            "preferred_username": payload.get("preferred_username"),
            "all_claims": payload,
        }
    except Exception as e:
        return {"error": str(e), "raw": token[:80] + "..."}


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AuthBridge Echo Service</title>
<style>
  :root {
    --red: #ee0000;
    --dark: #151515;
    --gray: #6a6e73;
    --light: #f0f0f0;
    --white: #ffffff;
    --green: #3e8635;
    --blue: #0066cc;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Red Hat Display', 'Segoe UI', system-ui, sans-serif;
    background: var(--light);
    color: var(--dark);
    line-height: 1.5;
  }
  header {
    background: var(--dark);
    color: var(--white);
    padding: 16px 32px;
    display: flex;
    align-items: center;
    gap: 16px;
  }
  header h1 { font-size: 20px; font-weight: 500; }
  header .badge {
    background: var(--red);
    color: var(--white);
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
  }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }
  .stat-card {
    background: var(--white);
    border-radius: 8px;
    padding: 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  }
  .stat-card .label { font-size: 12px; color: var(--gray); text-transform: uppercase; letter-spacing: 0.5px; }
  .stat-card .value { font-size: 24px; font-weight: 600; margin-top: 4px; }
  .stat-card .value.green { color: var(--green); }
  .stat-card .value.red { color: var(--red); }
  .request-card {
    background: var(--white);
    border-radius: 8px;
    margin-bottom: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    overflow: hidden;
  }
  .request-header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--light);
    display: flex;
    justify-content: space-between;
    align-items: center;
    cursor: pointer;
  }
  .request-header:hover { background: #fafafa; }
  .request-header .method {
    background: var(--blue);
    color: var(--white);
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
    margin-right: 8px;
  }
  .request-header .path { font-family: monospace; font-size: 14px; }
  .request-header .time { color: var(--gray); font-size: 13px; }
  .token-status {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
  }
  .token-status.present { background: #e7f5e2; color: var(--green); }
  .token-status.missing { background: #fce4e4; color: var(--red); }
  .request-body { padding: 20px; display: none; }
  .request-body.open { display: block; }
  .claims-grid {
    display: grid;
    grid-template-columns: 180px 1fr;
    gap: 8px;
    font-size: 14px;
  }
  .claims-grid .key {
    font-weight: 600;
    color: var(--gray);
    font-family: monospace;
    padding: 4px 0;
  }
  .claims-grid .val {
    font-family: monospace;
    word-break: break-all;
    padding: 4px 8px;
    background: #f5f5f5;
    border-radius: 4px;
  }
  .section-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--gray);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin: 16px 0 8px;
    padding-top: 16px;
    border-top: 1px solid var(--light);
  }
  .section-title:first-child { border-top: none; margin-top: 0; padding-top: 0; }
  .empty {
    text-align: center;
    padding: 60px 20px;
    color: var(--gray);
  }
  .empty h2 { font-size: 18px; margin-bottom: 8px; }
  .auto-refresh { font-size: 13px; color: var(--gray); }
  pre.raw {
    background: var(--dark);
    color: #a0ffa0;
    padding: 16px;
    border-radius: 8px;
    overflow-x: auto;
    font-size: 13px;
    margin-top: 12px;
  }
</style>
</head>
<body>
<header>
  <h1>AuthBridge Echo Service</h1>
  <span class="badge">Zero-Trust Demo</span>
  <span class="auto-refresh" id="refresh-status">Auto-refresh: 5s</span>
</header>
<div class="container">
  <div class="stats" id="stats"></div>
  <div id="requests"></div>
</div>
<script>
function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString() + ' ' + d.toLocaleDateString();
}
function toggleBody(el) {
  el.nextElementSibling.classList.toggle('open');
}
function render(data) {
  const reqs = data.requests || [];
  const withToken = reqs.filter(r => r.token && !r.token.error).length;
  const total = reqs.length;

  document.getElementById('stats').innerHTML = `
    <div class="stat-card">
      <div class="label">Total Requests</div>
      <div class="value">${total}</div>
    </div>
    <div class="stat-card">
      <div class="label">With Token</div>
      <div class="value green">${withToken}</div>
    </div>
    <div class="stat-card">
      <div class="label">Without Token</div>
      <div class="value red">${total - withToken}</div>
    </div>
    <div class="stat-card">
      <div class="label">Last Request</div>
      <div class="value" style="font-size:14px">${reqs.length ? formatTime(reqs[0].timestamp) : 'None'}</div>
    </div>
  `;

  if (!reqs.length) {
    document.getElementById('requests').innerHTML = `
      <div class="empty">
        <h2>No requests yet</h2>
        <p>Send a request to this service to see the decoded JWT claims.</p>
        <p style="margin-top:12px;font-family:monospace;font-size:13px">
          curl http://echo-service.team2.svc.cluster.local:8090/test
        </p>
      </div>`;
    return;
  }

  document.getElementById('requests').innerHTML = reqs.map((r, i) => {
    const hasToken = r.token && !r.token.error;
    const tokenBadge = hasToken
      ? '<span class="token-status present">Token Present</span>'
      : '<span class="token-status missing">No Token</span>';

    let bodyHtml = '';
    if (hasToken) {
      const t = r.token;
      const highlights = [
        ['azp', t.azp],
        ['client_id', t.client_id],
        ['sub', t.sub],
        ['iss', t.iss],
        ['aud', t.aud],
        ['scope', t.scope],
        ['groups', t.groups ? JSON.stringify(t.groups) : null],
        ['preferred_username', t.preferred_username],
        ['iat', t.iat ? formatTime(t.iat) : null],
        ['exp', t.exp ? formatTime(t.exp) : null],
      ].filter(([,v]) => v != null);

      bodyHtml = `
        <div class="section-title">Token Claims</div>
        <div class="claims-grid">
          ${highlights.map(([k,v]) => `<div class="key">${k}</div><div class="val">${v}</div>`).join('')}
        </div>
        <div class="section-title">All Claims</div>
        <pre class="raw">${JSON.stringify(t.all_claims, null, 2)}</pre>
      `;
    } else {
      bodyHtml = `<div class="section-title">No Token</div><p>${r.token ? r.token.error : 'No Authorization header'}</p>`;
    }

    bodyHtml += `
      <div class="section-title">Request Headers</div>
      <div class="claims-grid">
        ${Object.entries(r.headers || {}).filter(([k]) => k !== 'authorization').map(([k,v]) =>
          `<div class="key">${k}</div><div class="val">${v}</div>`
        ).join('')}
      </div>
    `;

    return `
      <div class="request-card">
        <div class="request-header" onclick="toggleBody(this)">
          <div>
            <span class="method">${r.method}</span>
            <span class="path">${r.path}</span>
            ${tokenBadge}
          </div>
          <span class="time">${formatTime(r.timestamp)}</span>
        </div>
        <div class="request-body${i === 0 ? ' open' : ''}">${bodyHtml}</div>
      </div>`;
  }).join('');
}

async function refresh() {
  try {
    const res = await fetch('/api/requests');
    const data = await res.json();
    render(data);
  } catch(e) { console.error(e); }
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


class EchoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "":
            self._serve_dashboard()
        elif self.path == "/api/requests":
            self._serve_requests_api()
        elif self.path == "/healthz":
            self._send_json({"status": "ok"})
        else:
            self._handle_echo()

    def do_POST(self):
        self._handle_echo()

    def _serve_dashboard(self):
        body = DASHBOARD_HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_requests_api(self):
        self._send_json({"requests": list(_requests)})

    def _handle_echo(self):
        auth = self.headers.get("Authorization", "")
        headers = {k: v for k, v in self.headers.items()}
        token = _decode_token(auth)

        result = {
            "timestamp": int(time.time()),
            "path": self.path,
            "method": self.command,
            "headers": headers,
            "token": token,
        }

        # Log to stdout
        if token.get("azp"):
            print(f"[echo] {self.command} {self.path} — azp={token['azp']} sub={token.get('sub')}", flush=True)
        else:
            print(f"[echo] {self.command} {self.path} — no token", flush=True)

        # Store for dashboard
        _requests.appendleft(result)

        self._send_json(result)

    def _send_json(self, data):
        body = json.dumps(data, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # Suppress default logging, we log in _handle_echo


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), EchoHandler)
    print(f"[echo] Listening on port {port}", flush=True)
    server.serve_forever()
