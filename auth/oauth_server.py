# auth/oauth_server.py

import http.server
import socketserver
import threading
import webbrowser
from urllib.parse import urlparse, parse_qs

from auth.oauth_client import exchange_code_for_token
from auth.token_store import save_token


PORT = 1717


class OAuthHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path != "/oauth/callback":
            self.send_response(404)
            self.end_headers()
            return

        query = parse_qs(parsed.query)
        auth_code = query.get("code")

        if not auth_code:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing auth code")
            return

        auth_code = auth_code[0]

        try:
            token_data = exchange_code_for_token(auth_code)
            save_token(token_data)

            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                b"Salesforce login successful. You may close this window."
            )

            # Stop server after success
            threading.Thread(target=self.server.shutdown).start()

        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())


def start_oauth_server():
    """
    Start local OAuth callback server.
    """
    with socketserver.TCPServer(("localhost", PORT), OAuthHandler) as httpd:
        httpd.serve_forever()