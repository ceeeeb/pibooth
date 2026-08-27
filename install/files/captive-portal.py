#!/usr/bin/env python3
"""Captive portal redirector for the Pibooth guest hotspot.

The hotspot dnsmasq resolves every domain to this host, so the connectivity
probes Android and iOS run on joining the network land here. Answering them
with a redirect instead of the expected 204/Success makes the phone conclude a
portal is in the way and pop the gallery open on its own.
"""
import http.server
import socketserver

LISTEN_ADDRESS = "10.42.0.1"
PORT = 80
GALLERY_URL = "http://10.42.0.1:8081/"


class RedirectHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", GALLERY_URL)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    do_POST = do_GET

    def log_message(self, fmt, *args):
        pass


class ThreadedServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with ThreadedServer((LISTEN_ADDRESS, PORT), RedirectHandler) as httpd:
        httpd.serve_forever()
