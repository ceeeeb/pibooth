#!/usr/bin/env python3
"""Mini web portal to add Wi-Fi networks to the Pi via nmcli.

Listens on port 8080. Intended for use on the local LAN only.
"""
import html
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

PORT = 8080
# Bound to every interface by default; the guest hotspot is kept out by the
# nftables input chain installed with the access point, not by this bind.
LISTEN_ADDRESS = "0.0.0.0"
# wlan1 runs the guest hotspot: client connections must stay on the built-in radio.
CLIENT_IFACE = "wlan0"


def list_saved_wifi():
    out = subprocess.run(
        ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
        capture_output=True, text=True, check=False,
    )
    rows = []
    for line in out.stdout.strip().splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[1] == "802-11-wireless":
            rows.append(parts[0])
    return rows


def scan_networks():
    subprocess.run(
        ["nmcli", "device", "wifi", "rescan", "ifname", CLIENT_IFACE],
        capture_output=True, check=False,
    )
    out = subprocess.run(
        ["nmcli", "-t", "-f", "SSID,SIGNAL", "device", "wifi", "list",
         "ifname", CLIENT_IFACE],
        capture_output=True, text=True, check=False,
    )
    seen = set()
    rows = []
    for line in out.stdout.strip().splitlines():
        if ":" not in line:
            continue
        ssid, signal = line.rsplit(":", 1)
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        try:
            rows.append((ssid, int(signal)))
        except ValueError:
            pass
    rows.sort(key=lambda r: -r[1])
    return rows


# nmcli has no "--" end-of-options sentinel: it reads "--" as a literal profile
# name. A value starting with "-" would therefore be parsed as an option, so
# reject those outright rather than trying to escape them.
MAX_SSID_BYTES = 32
MAX_PSK_LENGTH = 63


def reject_reason(ssid, password):
    """Return why these credentials are unusable, or None when they are fine."""
    if not ssid:
        return "SSID vide."
    if ssid.startswith("-") or password.startswith("-"):
        return "SSID et mot de passe ne peuvent pas commencer par un tiret."
    if len(ssid.encode("utf-8")) > MAX_SSID_BYTES:
        return f"SSID trop long (maximum {MAX_SSID_BYTES} octets)."
    if len(password) > MAX_PSK_LENGTH:
        return f"Mot de passe trop long (maximum {MAX_PSK_LENGTH} caracteres)."
    if any(char in ssid + password for char in "\0\r\n"):
        return "Caractere de controle interdit."
    return None


def connect(ssid, password):
    reason = reject_reason(ssid, password)
    if reason:
        return False, reason

    subprocess.run(
        ["sudo", "nmcli", "connection", "delete", ssid],
        capture_output=True, check=False,
    )
    cmd = ["sudo", "nmcli", "device", "wifi", "connect", ssid,
           "ifname", CLIENT_IFACE]
    if password:
        cmd += ["password", password]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode == 0, (result.stdout + result.stderr).strip()


PAGE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pibooth Wi-Fi</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 480px; margin: 1em auto; padding: 0 1em; }}
h1 {{ font-size: 1.3em; }}
input, select, button {{ width: 100%; padding: 0.7em; margin: 0.3em 0; font-size: 1em; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px; }}
button {{ background: #2563eb; color: white; border: none; }}
.msg {{ padding: 0.7em; border-radius: 4px; margin: 0.5em 0; }}
.ok {{ background: #d1fae5; }}
.err {{ background: #fee2e2; }}
.saved {{ font-size: 0.85em; color: #666; margin-top: 1em; }}
</style>
</head>
<body>
<h1>Pibooth Wi-Fi</h1>
{message}
<form method="post" action="/add">
<select name="ssid_select" onchange="document.getElementById('ssid').value=this.value">
<option value="">— réseaux détectés —</option>
{options}
</select>
<input id="ssid" name="ssid" placeholder="SSID" required>
<input name="password" type="password" placeholder="Mot de passe (vide si ouvert)">
<button type="submit">Connecter</button>
</form>
<p class="saved">Profils enregistrés : {saved}</p>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _render(self, message=""):
        options = "\n".join(
            f'<option value="{html.escape(s)}">{html.escape(s)} ({sig}%)</option>'
            for s, sig in scan_networks()
        )
        saved = ", ".join(html.escape(n) for n in list_saved_wifi()) or "aucun"
        body = PAGE.format(message=message, options=options, saved=saved).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/wifi"):
            self._render()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/add":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        data = parse_qs(self.rfile.read(length).decode())
        ssid = data.get("ssid", [""])[0].strip()
        password = data.get("password", [""])[0]
        if not ssid:
            self._render('<div class="msg err">SSID requis</div>')
            return
        ok, msg = connect(ssid, password)
        css = "ok" if ok else "err"
        text = "Connecté !" if ok else f"Échec : {html.escape(msg)}"
        self._render(f'<div class="msg {css}">{text}</div>')

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer((LISTEN_ADDRESS, PORT), Handler).serve_forever()
