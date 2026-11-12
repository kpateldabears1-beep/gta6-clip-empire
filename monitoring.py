"""Status messages contain platform IDs, safe stack frames, and a GitHub run link."""
import json
import os
from pathlib import Path
import re
import sys
import traceback
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def error_trace(exc, stage=None):
    frames = traceback.extract_tb(exc.__traceback__)[-6:]
    stack = " > ".join(f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in frames)
    status = getattr(getattr(exc, "response", None), "status_code", None) or getattr(exc, "code", None)
    detail = type(exc).__name__ + (f" HTTP {status}" if isinstance(status, int) else "")
    # Exclude exception bodies, source lines and locals: SDKs can put credentials in all three.
    if isinstance(exc, (KeyError, ValueError)) and re.fullmatch(r"(?:Missing )?[A-Z][A-Z0-9_]*", str(exc).strip("'")):
        detail += " " + str(exc).strip("'")
    trace = f"{detail} | {stack}"
    if stage:
        trace = stage + ": " + trace
    if os.getenv("RUNNER_TEMP"):
        with (Path(os.environ["RUNNER_TEMP"]) / "clips-error-trace.txt").open("a") as f:
            print(trace, file=f)
    return trace


def send_alert(message):
    discord = os.getenv("DISCORD_WEBHOOK_URL")
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    run = os.getenv("GITHUB_RUN_ID")
    if run:
        message = message[:1650] + f"\nhttps://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run}"
    targets = []
    if discord:
        targets.append(("Discord", discord, {"content": message[:1950], "allowed_mentions": {"parse": []}}))
    if token and chat:
        targets.append(("Telegram", f"https://api.telegram.org/bot{token}/sendMessage",
                        {"chat_id": chat, "text": message[:4000]}))
    errors = []
    if bool(token) != bool(chat):
        errors.append("Telegram needs both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    if not targets and not errors:
        print("Alert destination missing: configure Discord or Telegram.", file=sys.stderr)
        return False
    for name, url, payload in targets:
        try:
            req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json",
                                                                        "User-Agent": "DailyGetawayClips/1.0"})
            with urlopen(req, timeout=10) as response:
                if name == "Telegram" and json.load(response).get("ok") is not True:
                    raise ValueError("Telegram rejected the message")
        except Exception as exc:
            reason = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
            errors.append(f"{name}: {reason}")
    if errors:
        raise RuntimeError("Alert delivery failed: " + ", ".join(errors))
    return True


def notify_post(platform, receipt):
    if platform == "youtube":
        return send_alert("YouTube upload confirmed: https://www.youtube.com/shorts/" + receipt)
    if platform == "tiktok" and receipt.startswith("PUBLISH_COMPLETE:"):
        return send_alert("TikTok confirmed publication: " + receipt.split(":", 1)[1])
    return False


def failure_alert():
    # Actions gives the job and failed step even when the failure predates Python setup.
    import subprocess
    repo, run, attempt = (os.environ[k] for k in ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"))
    endpoint = f"repos/{repo}/actions/runs/{run}/attempts/{attempt}/jobs?per_page=100"
    details = []
    try:
        jobs = json.loads(subprocess.check_output(["gh", "api", endpoint], timeout=15))["jobs"]
        for job in jobs:
            if job["conclusion"] in ("failure", "timed_out", "cancelled"):
                steps = [s["name"] for s in job.get("steps", []) if s["conclusion"] in ("failure", "cancelled")]
                details.append(f"{job['name']} ({job['conclusion']}): " + ", ".join(steps))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        details.append("GitHub step details unavailable.")
    trace = os.getenv("FAILURE_TRACE", "").strip()
    return send_alert("\n".join(filter(None, ["Scheduled GTA clips run failed", *details, trace])))


if __name__ == "__main__":
    sys.exit(0 if failure_alert() else 1)
