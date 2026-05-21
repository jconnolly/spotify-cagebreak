#!/usr/bin/env python3
"""Spotify OAuth (Authorization Code + PKCE) with a local callback catcher.

Usage:
    python3 spotify_auth.py <CLIENT_ID>
  or set SPOTIFY_CLIENT_ID and run with no args.

Registered redirect URI must be EXACTLY:  http://127.0.0.1:8888/callback
(add it in your app at https://developer.spotify.com/dashboard)

Saves a fresh token.json with refresh_token + the expanded read scopes
needed to analyze your tastes, plus playlist-modify for pushing later.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = " ".join([
    "user-top-read",
    "user-library-read",
    "user-read-recently-played",
    "user-follow-read",
    "playlist-read-private",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-read-private",
])
TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.json")

_result = {}


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        _result.update({k: v[0] for k, v in params.items()})
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        ok = "code" in _result
        msg = "Auth complete. Return to the terminal." if ok else f"Auth failed: {_result.get('error')}"
        self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())

    def log_message(self, *a):
        pass


def _exchange(client_id, code, verifier):
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": verifier,
    }).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    client_id = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SPOTIFY_CLIENT_ID")
    if not client_id:
        print("ERROR: pass CLIENT_ID as arg or set SPOTIFY_CLIENT_ID", file=sys.stderr)
        sys.exit(1)

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
    })

    server = http.server.HTTPServer(("127.0.0.1", 8888), _Handler)
    t = threading.Thread(target=server.handle_request)  # serve exactly one request
    t.start()

    print("\nOpen this URL in your browser (attempting auto-open):\n")
    print(auth_url + "\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    t.join(timeout=300)
    server.server_close()

    if _result.get("state") != state:
        print(f"ERROR: state mismatch or timeout. got={_result}", file=sys.stderr)
        sys.exit(1)
    if "code" not in _result:
        print(f"ERROR: no code returned: {_result}", file=sys.stderr)
        sys.exit(1)

    tok = _exchange(client_id, _result["code"], verifier)
    tok["client_id"] = client_id  # stash for future refresh
    with open(TOKEN_PATH, "w") as f:
        json.dump(tok, f, indent=2)
    print(f"\nSaved {TOKEN_PATH}")
    print("scopes:", tok.get("scope"))


if __name__ == "__main__":
    main()
