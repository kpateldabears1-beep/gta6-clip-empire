"""Status messages contain platform IDs, safe stack frames, and a GitHub run link."""
import json
import os
from pathlib import Path
import re
import sys
import traceback
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class DiagnosticError(RuntimeError):
    """A diagnostic written by this application that can be included in an alert."""


def exception_detail(exc):
    detail = type(exc).__name__
    status = getattr(getattr(exc, "response", None), "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int):
        detail += f" HTTP {status}"
    if isinstance(exc, DiagnosticError):
        return detail + ": " + str(exc)
    if isinstance(exc, (KeyError, ValueError)) and re.fullmatch(r"(?:Missing )?[A-Z][A-Z0-9_]*", str(exc).strip("'")):
        detail += " " + str(exc).strip("'")
    if isinstance(getattr(exc, "returncode", None), int):
        detail += f" (exit {exc.returncode})"
    return detail


def error_trace(exc, stage=None):
    detail = exception_detail(exc)
    summary = f"{stage}: {detail}" if stage else detail
    if os.getenv("RUNNER_TEMP"):
        # Keep every stack frame and chained cause. Raw messages, source lines, request URLs
        # and local variables can contain credentials and are never forwarded.
        chain, seen = [], set()
        cause = exc
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            chain.append(cause)
            cause = cause.__cause__ or (None if cause.__suppress_context__ else cause.__context__)
        with (Path(os.environ["RUNNER_TEMP"]) / "clips-error-trace.txt").open("a") as f:
            print(summary, file=f)
            for cause in reversed(chain):
                print("Traceback (most recent call last):", file=f)
                for frame, line in traceback.walk_tb(cause.__traceback__):
                    print(f"  {Path(frame.f_code.co_filename).name}:{line} in {frame.f_code.co_name}", file=f)
                print(exception_detail(cause), file=f)
    return summary


def send_alert(message, *, discord_only=False):
    discord = os.getenv("DISCORD_WEBHOOK_URL")
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    run = os.getenv("GITHUB_RUN_ID")
    if run:
        message = message[:1650] + f"\nhttps://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run}"
    targets = []
    if discord:
        targets.append(("Discord", discord, {"content": message[:1950], "allowed_mentions": {"parse": []}}))
    if token and chat and not discord_only:
        targets.append(("Telegram", f"https://api.telegram.org/bot{token}/sendMessage",
                        {"chat_id": chat, "text": message[:4000]}))
    errors = []
    if not discord_only and bool(token) != bool(chat):
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


def runner_diagnostics(log):
    # A Python process can fail during import, before main.py opens its diagnostic file.
    # Forward only the filename, line number, and function from a standard Python frame.
    details = []
    for path, line, function in re.findall(
            rb'\bFile "([^"\r\n]+)", line (\d+), in ([\w.<>]+)', log):
        filename = Path(os.fsdecode(path)).name
        if re.fullmatch(r"[\w.-]+\.py|<stdin>|<string>", filename):
            details.append(f"  {filename}:{line.decode()} in {function.decode('ascii')}")
    types = re.findall(rb"(?:^|\s)([A-Za-z_][\w.]*(?:Error|Exception)):", log)
    details.extend(t.decode("ascii") for t in dict.fromkeys(types))
    codes = re.findall(rb"##\[error\]Process completed with exit code (\d+)\.", log)
    details.extend("Runner exit code " + c.decode() for c in dict.fromkeys(codes))
    return details


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
                if not os.getenv("FAILURE_TRACE"):
                    logs = subprocess.run(["gh", "api", f"repos/{repo}/actions/jobs/{job['id']}/logs"],
                                          capture_output=True, timeout=12)
                    if logs.returncode == 0:
                        details.extend(runner_diagnostics(logs.stdout))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        details.append("GitHub step details unavailable.")
    trace = os.getenv("FAILURE_TRACE", "").strip("\n")
    if not trace and os.getenv("RUNNER_TEMP"):
        path = Path(os.environ["RUNNER_TEMP"]) / "clips-error-trace.txt"
        if path.is_file():
            trace = path.read_text().strip()
    message = "\n".join(filter(None, ["Scheduled GTA clips run failed", *details, trace]))
    # Discord limits text to 2,000 characters. Preserve long traces and leave room for the run link.
    while len(message) > 1500:
        end = message.rfind("\n", 0, 1501)
        if end < 1:
            end = 1500
        if not send_alert(message[:end]):
            return False
        message = message[end:].lstrip("\n")
    return send_alert(message)


if __name__ == "__main__":
    sys.exit(0 if failure_alert() else 1)
