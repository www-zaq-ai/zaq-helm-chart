"""Chart-only mock: no database setup or migrations are simulated as real."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import sys


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/channels/health" and self.headers.get("X-Forwarded-Proto") == "https":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, *_args):
        pass


if sys.argv[1] == "provision-db":
    sys.exit(0)
HTTPServer(("0.0.0.0", 4000), Health).serve_forever()
