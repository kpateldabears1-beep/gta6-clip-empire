# GTA clip pipeline

The worker selects fast-growing GTA clips, uploads a public YouTube Short, and sends a compilation to the TikTok inbox when the source material and account allow it. Preview mode renders the same edits. Media and Whisper run in a temporary directory on the Ubuntu runner.

## Configure the repository

Put the source and the hidden `.github/workflows/pipeline.yml` on the default branch. The workflow supports a public or private repository. Standard public-repository runners have free compute. Anyone with repository read access can download retained workflow artifacts, including preview videos and their credits. Check your storage, Redis, and account limits before enabling the schedule. [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

Use **Settings → Secrets and variables → Actions**.

| Setting | Value |
| --- | --- |
| Secrets `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | Credentials for a confidential Twitch app. |
| Secret `REDIS_URL` | Upstash TLS connection string beginning with `rediss://`. |
| Variable `ALLOWED_BROADCASTER_IDS` | Comma-separated numeric Twitch IDs for footage you own or have permission to reuse. You can also list IDs in `streamers.json`. |
| Variable `ALLOWED_KICK_CHANNELS` | Comma-separated Kick channel slugs with permission to reuse their footage. Kick-only runs need no Twitch credentials. |
| Secrets `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | One Google Desktop OAuth client for the intended channel. The workflow also accepts the same names with the suffix `_1`. |
| Optional TikTok secrets | The TikTok helper sets `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`, and `TIKTOK_ACCESS_TOKEN`. An access token alone works until it expires. |
| Variable `DAILY_POST_CAP` | Integer 1 through 25. Defaults to 5. Manual deliveries count toward the same Chicago calendar day. |
| Variable `ENABLE_SCHEDULE` | Set to `true` to enable scheduled public YouTube uploads. Manual runs work independently. |

## Authorize your accounts

From this source directory, use a GitHub CLI session authorized to set Actions secrets on the intended repository. Neither helper prints tokens. You can use the macOS `--clipboard` option instead of `--repo OWNER/gta6-clip-empire` to copy just the requested token into GitHub Secrets. Clear the clipboard afterward with `pbcopy < /dev/null`.

**YouTube.** Enable YouTube Data API v3 in the Google Cloud project, configure the OAuth consent screen, and download a Desktop OAuth client JSON outside the repository. Choose the intended YouTube channel in the browser. External OAuth apps in testing may issue refresh tokens with short lifetimes. [Google Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app) · [Token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)

```sh
python3 -m venv /tmp/gta-youtube-auth
/tmp/gta-youtube-auth/bin/pip install 'google-auth-oauthlib>=1.2,<2'
/tmp/gta-youtube-auth/bin/python scripts/youtube_auth.py ~/Downloads/client_secret_YOUR_FILE.json --repo OWNER/gta6-clip-empire
```

**TikTok.** Configure Desktop Login Kit and Content Posting API for the app. Register exactly `http://127.0.0.1:3455/callback/` and obtain access to `video.upload` and `video.list` (for confirmed bounty share links). Run the following command and complete browser consent. The helper uses a state check and TikTok's desktop PKCE convention. The worker refreshes access as needed. It stores rotated tokens as ciphertext in Redis using key material derived from the GitHub secrets. Keep Redis persistent. If that state is lost or consent expires, run the helper again. [Desktop Login Kit](https://developers.tiktok.com/docs/en/login-kit-desktop) · [Token management](https://developers.tiktok.com/docs/en/oauth-user-access-token-management)

```sh
python3 scripts/tiktok_auth.py --repo OWNER/gta6-clip-empire
```

## Run a preview and deliver

Select **Actions → GTA clips → Run workflow → verify** to check the installed dependencies, render and decode synthetic footage, and exercise delivery reservations against a disposable Redis server on the runner. This mode runs without account credentials and sends no videos.

Select **gta5-sample** to render the 26-second freeway ramp Short from the [Unlisted Thoughts GTA V B-Roll Set](https://archive.org/details/ut-gtav-b-roll). The creator released their recording under CC0. The edit replaces the original soundtrack and adds timed commentary and credit. Download the verified MP4 from the run's seven-day artifact. Checking **Publish the GTA V sample once** also uploads through the production YouTube client. A repository deployment records the attempt before contacting YouTube to prevent repeat uploads. This one-off source stays outside Twitch discovery.

1. Open **Actions → GTA clips → Run workflow → preview**. The one-day artifact contains `youtube.mp4`, source metadata in `batch.json`, and `tiktok.mp4` if two or three clips can supply enough usable footage. Preview leaves delivery counters and reservations untouched.
2. Review the files, then select **deliver** to process current candidates and request **public visibility on YouTube**. A new run can select different clips from the previous preview. Check the reported visibility in the job log and processing in YouTube Studio.
3. Open the TikTok inbox notification to edit and publish the compilation. Without TikTok credentials, the compilation is available in the artifact. TikTok may limit pending inbox shares. A failed or delayed transfer remains associated with the batch. Direct Post requires a creator-facing preview, choice of privacy, and explicit consent per video. TikTok excludes private account-management utilities from that integration. [TikTok sharing guidelines](https://developers.tiktok.com/docs/en/content-sharing-guidelines)
4. Set `ENABLE_SCHEDULE=true` and your desired `DAILY_POST_CAP`. Starting November 13, 2026, the five daily windows open at 08:15, 11:15, 14:15, 17:15 and 20:15 America/Chicago. The preferred feed alternates Kick/Twitch; either may fill an empty slot with a cleared clip. Late runs outside the window skip delivery. Rendering and platform processing take additional time. With no cleared channels, the run reports a skipped window. Lower caps, insufficient footage and platform limits can reduce deliveries.

Clips need at least 100 source views by default, plus an eligible action or reaction. Up to 12 candidates are screened, with total views and view velocity contributing to the final score. Short-specific captions for YouTube, Instagram and Rumble are saved in `batch.json` for connected publishers or manual handoff. Only YouTube currently supports automatic public delivery here.

## Selection and editing

The **Channel performance and GTA discovery** workflow runs every three hours. Set `YOUTUBE_CHANNEL_ID` to the public destination channel. Its Actions summary ranks recent uploads by observed view changes and lists GTA candidates by source views per minute. It scans up to ten recent pages per GTA category as well as the creator watchlist. Category discovery is used only for research and never adds channels to the publishing allowlist. Upstash stores the latest counts and the last observation from each UTC day for 35 days. The public feed covers recent uploads and can lag Studio. Campaigns calculate eligible views and payouts separately. This workflow fetches metadata only. It runs independently of publishing, and does not need a Mac, social login or persistent video files.

`streamers.json` sets the lookback, game names and creator watchlist. Each watchlist entry has a Twitch `broadcaster_id`, a Kick `username`, or both. Set its `campaign_watermark` to the exact tracking code supplied by Whop Content Rewards, Vyro, Clipster or Reach.cat. With a blank code the credit shows only the handle. Set `ALLOWED_BROADCASTER_IDS` and `ALLOWED_KICK_CHANNELS` separately for channels you have permission to publish. Legacy Twitch campaigns in `priority_streamers` still work and can supply YouTube `extra_tags`.

Run `python3 main.py kick-trending` to list fresh public clip metadata, or select **kick-trending** in GitHub Actions. It reads the configured Kick usernames and ranks clips from the last three hours by views per minute. N3on and Rangesh share one feed. Marlon is tracked on Twitch. For rendering, only cleared channels and GTA V/VI categories enter the shared queue. Kick ledger keys use the `kick:` prefix.

The producer resolves Twitch game IDs, rejects untitled or generic clips, and ranks the remaining footage by views per minute of age (one-minute floor). It prefers GTA VI when at least five eligible clips exist and otherwise uses available GTA V footage. The Redis queue holds up to 50 ranked candidates. The worker examines up to six, skips unavailable downloads and quiet clips, and selects the first eligible Short. It measures 100 ms audio windows, requires at least half a second above −40 dBFS, and trims up to 1.5 seconds of leading quiet audio. Transcript keyword hits are recorded in the manifest for review.

The worker screens the actual cut before rendering. Whisper supplies timed words and explicit music cues. Each source and each selected compilation excerpt must contain at least four spoken words inside its boundaries. Transcript annotations are excluded. The source manifest records words per minute. Google’s YAMNet scores audible 0.48-second intervals for speech, music and singing. A run of 17 audible intervals (8.16 seconds) with at least 14 likely singing or instrumental music intervals and no detected speech skips the source in both outputs. Quiet intervals and detected speech break the run. The classifier identifies sound types; it cannot identify a track, its owner, or whether its use is licensed. Missed music and false positives are possible. If the screen fails, the run stops before delivery. [YAMNet model](https://github.com/tensorflow/models/tree/master/research/audioset/yamnet)

YouTube cuts and individual compilation segments run from 18 seconds to strictly under 44 seconds. TikTok cuts use 2–3 distinct sources targeting 65 seconds. Both outputs use 1080×1920 H.264 at 30 fps with 44.1 kHz stereo AAC, a full-length top hook, a permanent lower-left `Clip: @handle` credit followed by the optional campaign code for that segment, and animated two-word captions. During transcript gaps, a neutral visual cue keeps the caption track active. The archive sample keeps its original creator credit. Set normalized `[left, top, width, height]` facecam coordinates per broadcaster in `editorial.json`. The default assumes a lower-left camera and puts it below the gameplay. The upper 1080×1150 panel center-crops gameplay and the lower 1080×770 panel centers the configured facecam crop. Hooks use three to five words derived from the source title, with an optional editorial override. Discovery rejects silent footage. The renderer retains its silent-audio fallback for synthetic verification and standalone editing. Set a broadcaster's value to `null` for a gameplay-only layout. Add original clip-specific analysis with this structure:

```json
{"facecams":{"12345":[0,0.55,0.32,0.35]},"clips":{"ActualClipID":{"hook":"Why the getaway worked","notes":[{"start":2,"end":7,"text":"Watch the rear wheel as the driver accelerates."}]}}}
```

Fair use is determined case by case. Attribution, captions and a duration cap cannot establish fair use, prevent claims or guarantee monetization. Original analysis and the underlying rights matter. [YouTube fair use guidance](https://support.google.com/youtube/answer/9783148) · [YouTube channel monetization policies](https://support.google.com/youtube/answer/1311392) · [TikTok Creator Rewards](https://support.tiktok.com/en/business-and-creator/creator-rewards-program/creator-rewards-program)

## Recovery and tests

Delivery atomically reserves selected source IDs in `gta-clips:v1` and one UTC-day slot per platform upload in `gta-clips:daily:YYYY-MM-DD`. A YouTube Short plus a TikTok inbox upload costs two slots. With one slot left the worker sends the Short. A GitHub artifact costs zero slots, and the one-off YouTube sample shares the same cap. External publishers manage their own limits. A timeout may follow a successful upload, so an uncertain attempt consumes its slot. The ledger records each destination separately. Check Studio, the TikTok inbox and the one-day artifact before retrying an uncertain transfer. Use the artifact to finish a partially delivered batch. The runner removes its media and model at job exit.

Run `python3 -m unittest discover -s tests -v` with FFmpeg and ffprobe on the test machine. The synthetic render exercises the camera layout, silence handling, audio normalization to a common sample rate, concatenation and decoding. Live verification requires the accounts and credentials above.

## R2 backups and Reels download URLs

Add Actions secrets `R2_ENDPOINT_URL` (your bucket's HTTPS S3 endpoint), `R2_BUCKET`, `R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY`. Use a bucket-scoped R2 Object Read & Write credential. The workflow uploads each final Short, compilation and one-off GTA V sample before delivery and cleanup. It verifies the stored length, SHA-256 metadata and MP4 content type. Object keys include the content digest so retries of identical files use the same key. After a backup failure the workflow blocks publishing and attempts to retain the rendered files as a seven-day recovery artifact. A hosted runner's temporary disk is disposable.

Open the private R2 object `manifests/<GitHub run ID>/<attempt>.json`. Each video entry has a six-hour presigned GET URL in `video_url` and a UTC `expires_at`. Supply the URL to Instagram's Reels ingestion while it is valid. Anyone holding the URL can read that one object until expiry. The bucket can stay private. To renew a URL, generate another presigned GET for the manifest's persistent `key` using a bucket-authorized client. [Cloudflare presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/)

## Overnight monitoring

Use **Actions → GTA clips → Run workflow → dry-run**, or install `requirements-health.txt`, FFmpeg/ffprobe and eSpeak, then run `python main.py --dry-run`. The CLI and Actions summary report PASS or FAIL for each of six checks. A failed check makes the command exit nonzero after the remaining checks run.

- Twitch exchanges `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` for an app token and looks up GTA V in Helix. Kick checks the public clips response and also checks OAuth if either optional Kick credential is configured.
- Redis writes a unique health key through `REDIS_URL`, reads and compares its value, then deletes it. The key expires in two minutes if the runner stops early.
- FFmpeg generates a short spoken test clip, renders blue gameplay above a red facecam, and verifies the pixels on either side of the split and the stereo AAC stream. Whisper must recognize the test phrase in that render. R2 uploads the same clip to a private `health/` key, compares the signed download by SHA-256 and deletes the object. If rendering fails after the source is generated, Whisper and R2 use that source and identify it in the report.

The overnight run starts daily at **09:17 UTC** (3:17 a.m. CST or 4:17 a.m. CDT). The job uses a standard Ubuntu runner with a ten-minute timeout and creates no artifact or social post. At 31 scheduled checks per month, its timeout allows at most 310 runner-minutes, plus up to three minutes per failed run for alert delivery. Standard runner compute is free in this public repository. Artifact storage, other workflows and external services have separate allowances. [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

Set the Actions secret `DISCORD_WEBHOOK_URL` to the private Discord channel's webhook. Optional Telegram delivery uses `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Failed scheduled runs send the run link and available traceback, including file names, line numbers, functions, exception classes and chained failures. Long traces span multiple messages. Credentials, locals, raw request URLs and third-party exception bodies are excluded. Setup failures that precede Python include the failed step and available runner exit code.

## Clipping bounty alerts

Set the Actions secret `DISCORD_WEBHOOK_URL` to a webhook in your private channel. Add the supplied `campaign_watermark` to an entry in `priority_streamers`, or set `"priority": true` and the watermark on a cleared watchlist creator. A Kick-only priority entry can use `username` or `kick_username` and still needs its handle in `ALLOWED_KICK_CHANNELS`. Leave the watermark blank to stop tracking new renders for that campaign.

Each alert gives the public post link, the source handles and campaign codes for that particular cut, and the deadline calculated from the original publication time plus 30 minutes. The pipeline checks immediately after upload. Delayed publication and failed notifications stay in Redis for up to 30 days. Enable `ENABLE_BOUNTY_TRACKING=true` for five-minute checks when the ordinary posting schedule is off. You can also run **Clipping bounty alerts** manually. GitHub can delay scheduled jobs. A retry after Discord accepted a message but the acknowledgment was lost can duplicate the notification.

YouTube uses a confirmed public, processed upload response or an exact match in the public channel feed. TikTok waits for a moderated public video ID, then looks up its share URL and publication time. A creator still completes inbox publication in TikTok. Existing TikTok tokens need consent for the additional `video.list` scope. [YouTube feed](https://developers.google.com/youtube/v3/guides/push_notifications) · [TikTok post status](https://developers.tiktok.com/docs/content-posting-api-reference-get-video-status) · [TikTok video query](https://developers.tiktok.com/docs/tiktok-api-v2-video-query)

For Instagram Reels, Rumble, or a manually completed post, have the account's publisher send an authenticated GitHub `repository_dispatch` of type `clip-published` **after public publication**. Use the platform's confirmed permalink and publication time. The `run_id` is the rendered `batch_id` from `batch.json` and `cut` is `short` or `compilation`. The callback looks up the campaign credits saved for that cut. For example, a publisher would send this shape to the repository's dispatches endpoint:

```json
{
  "event_type": "clip-published",
  "client_payload": {
    "run_id": "123456789",
    "cut": "short",
    "platform": "instagram",
    "url": "https://www.instagram.com/reel/EXAMPLE/",
    "published_at": "2026-11-12T14:00:00Z"
  }
}
```

The supported platform names are `youtube`, `tiktok`, `instagram` and `rumble`. Signed R2 ingestion URLs, inbox receipts, and artifact links cannot be submitted as public post links. Instagram and Rumble require a connected publisher or an authenticated callback after a manual post. [GitHub repository dispatch](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event)
