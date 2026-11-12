"""One-time Desktop OAuth. Never print credentials or put secrets in command arguments."""
import argparse
import json
from pathlib import Path
import subprocess

from google_auth_oauthlib.flow import InstalledAppFlow

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("client_json", type=Path)
target = parser.add_mutually_exclusive_group(required=True)
target.add_argument("--repo", metavar="OWNER/REPO", help="set all three YouTube secrets via authenticated gh")
target.add_argument("--clipboard", action="store_true", help="copy only the refresh token on macOS")
args = parser.parse_args()
config = json.loads(args.client_json.read_text())
client = config["installed"]
flow = InstalledAppFlow.from_client_config(config, ["https://www.googleapis.com/auth/youtube.upload"],
                                           autogenerate_code_verifier=True)
creds = flow.run_local_server(host="127.0.0.1", port=0, access_type="offline", prompt="consent")
if not creds.refresh_token:
    raise SystemExit("Google did not return a refresh token; repeat consent for the intended account.")
if args.repo:
    for key, value in {"YOUTUBE_CLIENT_ID": client["client_id"],
                       "YOUTUBE_CLIENT_SECRET": client["client_secret"],
                       "YOUTUBE_REFRESH_TOKEN": creds.refresh_token}.items():
        subprocess.run(["gh", "secret", "set", key, "--repo", args.repo], input=value, text=True, check=True)
    print("Saved all three YouTube secrets to the selected repository.")
else:
    subprocess.run(["pbcopy"], input=creds.refresh_token, text=True, check=True)
    print("Refresh token copied. Paste into GitHub Actions secret YOUTUBE_REFRESH_TOKEN, then clear clipboard.")
