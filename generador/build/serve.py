import functools
import http.server
import sys


class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', 'http://localhost:5678')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()
http.server.ThreadingHTTPServer(('127.0.0.1', 8765), functools.partial(H, directory=sys.argv[1])).serve_forever()
