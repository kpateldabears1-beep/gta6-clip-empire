# GTA clip pipeline

The hourly worker selects fast-growing GTA clips, uploads a public YouTube Short, and sends a compilation to the TikTok inbox when the source material and account allow it. Preview mode renders the same edits. Media and Whisper run in a temporary directory on the Ubuntu runner.

## Configure the repository

Put the source and the hidden `.github/workflows/pipeline.yml` on the default branch. The workflow supports a public or private repository. Standard public-repository runners have free compute. Anyone with repository read access can download retained workflow artifacts, including preview videos and their credits. Check your storage, Redis, and account limits before enabling the schedule. [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

Use **Settings → Secrets and variables → Actions**.

| Setting | Value |
| --- | --- |
| Secrets `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | Credentials for a confidential Twitch app. |
| Secret `REDIS_URL` | Upstash TLS connection string beginning with `rediss://`. |
| Variable `ALLOWED_BROADCASTER_IDS` | Comma-separated numeric Twitch IDs for footage you own or have permission to reuse. You can also list IDs in `streamers.json`. |
| Secrets `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | One Google Desktop OAuth client for the intended channel. The workflow also accepts the same names with the suffix `_1`. |
| Optional TikTok secrets | The TikTok helper sets `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`, and `TIKTOK_ACCESS_TOKEN`. An access token alone works until it expires. |
| Variable `DAILY_POST_CAP` | Integer 1 through 25. Defaults to 5. Manual deliveries count toward the same UTC day. |
| Variable `ENABLE_SCHEDULE` | Set to `true` to enable scheduled public YouTube uploads. Manual runs work independently. |

## Authorize your accounts

From this source directory, use a GitHub CLI session authorized to set Actions secrets on the intended repository. Neither helper prints tokens. You can use the macOS `--clipboard` option instead of `--repo OWNER/gta6-clip-empire` to copy just the requested token into GitHub Secrets. Clear the clipboard afterward with `pbcopy < /dev/null`.

**YouTube.** Enable YouTube Data API v3 in the Google Cloud project, configure the OAuth consent screen, and download a Desktop OAuth client JSON outside the repository. Choose the intended YouTube channel in the browser. External OAuth apps in testing may issue refresh tokens with short lifetimes. [Google Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app) · [Token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)

```sh
python3 -m venv /tmp/gta-youtube-auth
/tmp/gta-youtube-auth/bin/pip install 'google-auth-oauthlib>=1.2,<2'
/tmp/gta-youtube-auth/bin/python scripts/youtube_auth.py ~/Downloads/client_secret_YOUR_FILE.json --repo OWNER/gta6-clip-empire
```

**TikTok.** Configure Desktop Login Kit and Content Posting API for the app. Register exactly `http://127.0.0.1:3455/callback/` and obtain access to `video.upload`. Run the following command and complete browser consent. The helper uses a state check and TikTok's desktop PKCE convention. The worker refreshes access as needed. It stores rotated tokens as ciphertext in Redis using key material derived from the GitHub secrets. Keep Redis persistent. If that state is lost or consent expires, run the helper again. [Desktop Login Kit](https://developers.tiktok.com/docs/en/login-kit-desktop) · [Token management](https://developers.tiktok.com/docs/en/oauth-user-access-token-management)

```sh
python3 scripts/tiktok_auth.py --repo OWNER/gta6-clip-empire
```

## Run a preview and deliver

Select **Actions → GTA clips → Run workflow → verify** to check the installed dependencies, render and decode synthetic footage, and exercise delivery reservations against a disposable Redis server on the runner. This mode runs without account credentials and sends no videos.

Select **gta5-sample** to render the 26-second freeway ramp Short from the [Unlisted Thoughts GTA V B-Roll Set](https://archive.org/details/ut-gtav-b-roll). The creator released their recording under CC0. The edit replaces the original soundtrack and adds timed commentary and credit. Download the verified MP4 from the run's seven-day artifact. Checking **Publish the GTA V sample once** also uploads through the production YouTube client. A repository deployment records the attempt before contacting YouTube to prevent repeat uploads. This one-off source stays outside Twitch discovery.

1. Open **Actions → GTA clips → Run workflow → preview**. The one-day artifact contains `youtube.mp4`, source metadata in `batch.json`, and `tiktok.mp4` if two or three clips can supply enough usable footage. Preview leaves delivery counters and reservations untouched.
2. Review the files, then select **deliver** to process current candidates and request **public visibility on YouTube**. A new run can select different clips from the previous preview. Check the reported visibility in the job log and processing in YouTube Studio.
3. Open the TikTok inbox notification to edit and publish the compilation. Without TikTok credentials, the compilation is available in the artifact. TikTok may limit pending inbox shares. A failed or delayed transfer remains associated with the batch. Direct Post requires a creator-facing preview, choice of privacy, and explicit consent per video. TikTok excludes private account-management utilities from that integration. [TikTok sharing guidelines](https://developers.tiktok.com/docs/en/content-sharing-guidelines)
4. Set `ENABLE_SCHEDULE=true` and your desired `DAILY_POST_CAP`. The schedule runs on the hour, plus 23:30 UTC at cap 25. Lower caps spread eligible render windows across the day. GitHub scheduling delays, shortages of eligible footage, or channel limits can reduce actual deliveries. Google documents a default of 100 video insert calls per day per project. Check the actual quota for your project. [YouTube quotas](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits) · [YouTube upload visibility](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert)

## Selection and editing

`streamers.json` sets the lookback (three hours by default), game names, and optional channel campaigns. For each campaign, add an object such as `{"broadcaster_id":"12345","username":"your_channel","campaign_watermark":"Campaign name","extra_tags":["#YourCampaign"]}` to `priority_streamers`. Campaign tags and watermarks apply to YouTube only. Keep promotional branding out of the TikTok cut.

The producer resolves Twitch game IDs, rejects untitled or generic clips, and ranks the remaining footage by views per minute of age (one-minute floor). It prefers GTA VI when at least five eligible clips exist and otherwise uses available GTA V footage. The Redis queue holds up to 50 ranked candidates. The worker examines up to six, skips unavailable downloads and quiet clips, and selects the first eligible Short. It measures 100 ms audio windows, requires at least half a second above −40 dBFS, and trims up to 1.5 seconds of leading quiet audio. Transcript keyword hits are recorded in the manifest for review.

YouTube cuts run 25–44 seconds before encoding. TikTok cuts use 2–3 distinct sources targeting 65 seconds. Both outputs use 1080×1920 H.264 at 30 fps with 44.1 kHz stereo AAC, a top hook, source credits and word-highlighted captions. Set normalized `[left, top, width, height]` facecam coordinates per broadcaster in `editorial.json`. The default assumes a lower-left camera and shows it in the top third. Set a broadcaster's value to `null` for a gameplay-only layout. Add original clip-specific analysis with this structure:

```json
{"facecams":{"12345":[0,0.55,0.32,0.35]},"clips":{"ActualClipID":{"hook":"Why the getaway worked","notes":[{"start":2,"end":7,"text":"Watch the rear wheel as the driver accelerates."}]}}}
```

Captions and reframing alone do not establish monetization eligibility. [YouTube channel monetization policies](https://support.google.com/youtube/answer/1311392) · [TikTok Creator Rewards](https://support.tiktok.com/en/business-and-creator/creator-rewards-program/creator-rewards-program)

## Recovery and tests

Delivery atomically reserves all source IDs in `gta-clips:v1` and one daily slot in `gta-clips:daily:YYYY-MM-DD` before calling either platform. A timeout may follow a successful upload, so an uncertain attempt consumes its slot. The ledger records each destination separately. Check Studio, the TikTok inbox and the one-day artifact before retrying an uncertain transfer. Use the artifact to finish a partially delivered batch. The runner removes its media and model at job exit.

Run `python3 -m unittest discover -s tests -v` with FFmpeg and ffprobe on the test machine. The synthetic render exercises the camera layout, silence handling, audio normalization to a common sample rate, concatenation and decoding. Live verification requires the accounts and credentials above.
