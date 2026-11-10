"""Connect the configured Amiro Google account and save its refresh token."""

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
import json
import os
import sys
import urllib.error
import urllib.request
import webbrowser

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app.core.config import settings  # noqa: E402

REDIRECT_URI = "http://localhost:8765/oauth2callback"
SCOPES = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.freebusy",
)


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    authorization_code = None
    authorization_error = None

    def do_GET(self):
        values = parse_qs(urlparse(self.path).query)
        OAuthCallbackHandler.authorization_code = values.get("code", [None])[0]
        OAuthCallbackHandler.authorization_error = values.get("error", [None])[0]
        body = b"Authorization complete. You can close this browser tab and return to the terminal."
        self.send_response(200 if OAuthCallbackHandler.authorization_code else 400)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def save_refresh_token(refresh_token: str) -> None:
    env_path = BACKEND_DIR / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    replacement = f"GOOGLE_CALENDAR_REFRESH_TOKEN={refresh_token}"
    for index, line in enumerate(lines):
        if line.startswith("GOOGLE_CALENDAR_REFRESH_TOKEN="):
            lines[index] = replacement
            break
    else:
        lines.append(replacement)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    if not settings.GOOGLE_CALENDAR_CLIENT_ID or not settings.GOOGLE_CALENDAR_CLIENT_SECRET:
        raise SystemExit("Set GOOGLE_CALENDAR_CLIENT_ID and GOOGLE_CALENDAR_CLIENT_SECRET in backend/.env first.")

    query = urlencode({
        "client_id": settings.GOOGLE_CALENDAR_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    })
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{query}"
    server = HTTPServer(("localhost", 8765), OAuthCallbackHandler)
    print("Opening Google authorization. Sign in with the account that owns the Amiro demo calendar.")
    print("If the browser does not open, visit this URL:\n" + auth_url)
    webbrowser.open(auth_url)
    try:
        while OAuthCallbackHandler.authorization_code is None and OAuthCallbackHandler.authorization_error is None:
            server.handle_request()
    finally:
        server.server_close()

    if OAuthCallbackHandler.authorization_error:
        raise SystemExit("Google authorization was not granted. Review the consent screen and try again.")

    body = urlencode({
        "client_id": settings.GOOGLE_CALENDAR_CLIENT_ID,
        "client_secret": settings.GOOGLE_CALENDAR_CLIENT_SECRET,
        "code": OAuthCallbackHandler.authorization_code,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()
    request = urllib.request.Request("https://oauth2.googleapis.com/token", data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            tokens = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Google token exchange failed ({exc.code}). Check OAuth consent and redirect URI settings.") from exc
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise SystemExit("Google did not return a refresh token. Revoke this app's access and run the script again.")
    save_refresh_token(refresh_token)
    print(f"Refresh token saved to {BACKEND_DIR / '.env'}")


if __name__ == "__main__":
    main()
