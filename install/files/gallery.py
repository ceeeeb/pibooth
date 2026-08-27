#!/usr/bin/env python3
"""Pibooth local photo gallery served over HTTP for LAN access.

Reads a session marker file written by the pibooth-gallery-qr plugin:
  - mtime defines the session-start cutoff
  - the file content is the absolute path to the photos directory
"""
import glob
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import quote, unquote

PORT = int(os.environ.get("GALLERY_PORT", "8081"))
SESSION_FILE = os.environ.get("GALLERY_SESSION_FILE", "/tmp/pibooth-session-start")
PATTERN = "*_pibooth.jpg"


def session_info():
    """Return (photos_dir, start_ts) or (None, 0) if no session is active."""
    try:
        with open(SESSION_FILE) as f:
            photos_dir = f.read().strip()
        return (photos_dir or None), os.path.getmtime(SESSION_FILE)
    except OSError:
        return None, 0


def session_photos():
    photos_dir, cutoff = session_info()
    if not photos_dir:
        return []
    photos = []
    for path in glob.glob(os.path.join(photos_dir, PATTERN)):
        try:
            if os.path.getmtime(path) >= cutoff:
                photos.append(path)
        except OSError:
            pass
    photos.sort(key=os.path.getmtime, reverse=True)
    return photos


PAGE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Photothèque</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, sans-serif; margin: 0; background: #111; color: #eee; }}
header {{ padding: 0.8em 1em; background: #1f2937; position: sticky; top: 0; z-index: 1; }}
h1 {{ margin: 0; font-size: 1.2em; }}
.count {{ font-size: 0.85em; color: #9ca3af; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 4px; padding: 4px; }}
.grid a {{ display: block; aspect-ratio: 1; overflow: hidden; }}
.grid img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
.empty {{ text-align: center; padding: 3em 1em; color: #9ca3af; }}
#lightbox {{ position: fixed; inset: 0; background: rgba(0,0,0,.96); display: none;
             align-items: center; justify-content: center; z-index: 100;
             touch-action: manipulation; }}
#lightbox.open {{ display: flex; }}
#lightbox img {{ max-width: 100vw; max-height: 100vh; object-fit: contain; display: block; }}
#lightbox .nav {{ position: absolute; top: 0; bottom: 0; width: 30%;
                  display: flex; align-items: center; padding: 0 1em;
                  font-size: 2em; color: rgba(255,255,255,.6);
                  user-select: none; -webkit-tap-highlight-color: transparent; }}
#lightbox .nav.prev {{ left: 0; }}
#lightbox .nav.next {{ right: 0; justify-content: flex-end; }}
#lightbox .close {{ position: absolute; top: 0.5em; right: 0.5em;
                    font-size: 1.8em; color: rgba(255,255,255,.7);
                    padding: 0.2em 0.5em; user-select: none; }}
</style>
</head>
<body>
<header><h1>Photothèque</h1><div class="count">{count} photo(s)</div></header>
{body}
<div id="lightbox" role="dialog" aria-hidden="true">
  <div class="nav prev" data-action="prev">‹</div>
  <img alt="">
  <div class="nav next" data-action="next">›</div>
  <div class="close" data-action="close">×</div>
</div>
<script>
(function() {{
  var grid = document.querySelector('.grid');
  if (!grid) return;
  var srcs = Array.prototype.map.call(grid.querySelectorAll('a'), function(a) {{ return a.getAttribute('href'); }});
  var lb = document.getElementById('lightbox');
  var lbImg = lb.querySelector('img');
  var idx = -1;
  var refreshTimer = null;

  function show(i) {{
    if (i < 0 || i >= srcs.length) return;
    idx = i;
    lbImg.src = srcs[i];
    lb.classList.add('open');
    lb.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    clearTimeout(refreshTimer);
  }}
  function close() {{
    lb.classList.remove('open');
    lb.setAttribute('aria-hidden', 'true');
    lbImg.src = '';
    document.body.style.overflow = '';
    scheduleRefresh();
  }}
  function next() {{ if (idx < srcs.length - 1) show(idx + 1); }}
  function prev() {{ if (idx > 0) show(idx - 1); }}
  function scheduleRefresh() {{
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(function() {{ location.reload(); }}, 30000);
  }}

  grid.addEventListener('click', function(e) {{
    var a = e.target.closest('a');
    if (!a) return;
    e.preventDefault();
    show(srcs.indexOf(a.getAttribute('href')));
  }});
  lb.addEventListener('click', function(e) {{
    var action = e.target.getAttribute('data-action');
    if (action === 'prev') {{ prev(); return; }}
    if (action === 'next') {{ next(); return; }}
    close();
  }});
  document.addEventListener('keydown', function(e) {{
    if (!lb.classList.contains('open')) return;
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowRight') next();
    else if (e.key === 'ArrowLeft') prev();
  }});
  scheduleRefresh();
}})();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index", "/index.html"):
            return self._index()
        if self.path.startswith("/img/"):
            return self._image(unquote(self.path[len("/img/"):]))
        self.send_error(404)

    def _index(self):
        photos = session_photos()
        if not photos:
            body = '<p class="empty">Aucune photo pour l\'instant.</p>'
        else:
            tiles = "\n".join(
                f'<a href="/img/{quote(os.path.basename(p))}" target="_blank">'
                f'<img loading="lazy" src="/img/{quote(os.path.basename(p))}" alt=""></a>'
                for p in photos
            )
            body = f'<div class="grid">{tiles}</div>'
        self._send(200, "text/html; charset=utf-8",
                   PAGE.format(count=len(photos), body=body).encode())

    def _image(self, name):
        if not name or "/" in name or "\\" in name or ".." in name or "\x00" in name:
            return self.send_error(403)
        photos_dir, cutoff = session_info()
        if not photos_dir:
            return self.send_error(404)
        path = os.path.join(photos_dir, name)
        try:
            if not os.path.isfile(path) or os.path.getmtime(path) < cutoff:
                return self.send_error(404)
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return self.send_error(500)
        self._send(200, "image/jpeg", data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
