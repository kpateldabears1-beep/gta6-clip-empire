"""Authorize TikTok inbox uploads through Desktop Login Kit."""
import argparse
import getpass
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
import subprocess
from time import monotonic
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
import webbrowser

REDIRECT = "http://127.0.0.1:3455/callback/"


def authorize(key, secret):
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    params = {"client_key": key, "response_type": "code", "scope": "video.upload,video.list",
              "redirect_uri": REDIRECT, "state": state, "code_challenge_method": "S256",
              "code_challenge": hashlib.sha256(verifier.encode()).hexdigest()}
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Callback URLs contain short-lived authorization codes.

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path != "/callback/":
                self.send_error(404)
                return
            query = parse_qs(url.query)
            received = query.get("state", [""])[0]
            if not hmac.compare_digest(received.encode(), state.encode()):
                self.send_error(400, "State mismatch")
                return
            result.update(query)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"You may close this tab and return to the terminal.")

    with HTTPServer(("127.0.0.1", 3455), Callback) as server:
        server.timeout = 1
        url = "https://www.tiktok.com/v2/auth/authorize/?" + urlencode(params)
        if not webbrowser.open(url):
            print("Open this consent URL in your browser:", url)
        deadline = monotonic() + 300
        while not result and monotonic() < deadline:
            server.handle_request()
    if not result.get("code"):
        raise SystemExit("No authorization code received. Check consent and the registered redirect URI.")
    body = dict(client_key=key, client_secret=secret, code=result["code"][0],
                grant_type="authorization_code", redirect_uri=REDIRECT, code_verifier=verifier)
    req = Request("https://open.tiktokapis.com/v2/oauth/token/", data=urlencode(body).encode())
    with urlopen(req, timeout=30) as response:
        token = json.load(response)
    granted = token.get("scope", "").split(",")
    if not token.get("access_token") or "video.upload" not in granted:
        raise SystemExit("TikTok did not grant video.upload to this account.")
    if "video.list" not in granted:
        print("Inbox uploads enabled. Automatic bounty link lookup requires video.list.")
    return token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--repo", help="Set TikTok secrets using authenticated gh")
    target.add_argument("--clipboard", action="store_true", help="Copy current access token on macOS")
    args = parser.parse_args()
    key = input("TikTok client key: ").strip()
    secret = getpass.getpass("TikTok client secret: ").strip()
    token = authorize(key, secret)
    if args.repo:
        values = {"TIKTOK_CLIENT_KEY": key, "TIKTOK_CLIENT_SECRET": secret,
                  "TIKTOK_ACCESS_TOKEN": token["access_token"], "TIKTOK_REFRESH_TOKEN": token["refresh_token"]}
        for name, value in values.items():
            subprocess.run(["gh", "secret", "set", name, "--repo", args.repo], input=value, text=True, check=True)
        print("TikTok credentials saved to GitHub Actions secrets.")
    else:
        subprocess.run(["pbcopy"], input=token["access_token"], text=True, check=True)
        print("Paste into TIKTOK_ACCESS_TOKEN. This access token expires in", token["expires_in"], "seconds.")


if __name__ == "__main__":
    main()
