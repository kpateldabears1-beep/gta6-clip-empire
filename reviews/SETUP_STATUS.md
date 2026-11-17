# Verified setup — November 15, 2026

**November 16 update:** the exact-draft release path is now implemented and cloud-verified in [run 44020823720](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/44020823720). It retrieved the private R2 video, verified full SHA-256 and found no existing source reservation. Its publishing step was skipped. The release plan remains `not_submitted`; actual playback review and brand approval are still required. The previous temporary `Downloads/preview.mp4` is no longer present; the agent did not download a replacement. The finished MP4 is still in the [render artifact](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43758501170/artifacts/14178438950) and durable R2 backup.

**Current scope: YouTube only**, explicitly selected by the user. TikTok, Instagram and Rumble setup/publication are deferred. Do not interact with the user's Chrome browser. No new video was submitted or published during this audit.

## Ramp-up checklist

| Requested item | Verified state |
| --- | --- |
| Increase daily cap | Live Actions variable `DAILY_POST_CAP=25`. Redis reservations use the America/Chicago calendar day. This is a ceiling, not a promise of 25 uploads. |
| Enable scheduled posting | `ENABLE_SCHEDULE=true`; GTA clips workflow is active. Five configured windows: 08:15, 11:15, 14:15, 17:15, 20:15 America/Chicago. GitHub may delay scheduled starts. |
| Manual preview and delivery | Both modes exist. **A new deliver run selects current candidates, not the exact earlier preview.** Do not use it to release the Lysium approval draft. |
| Alternate Twitch/Kick | Scheduling alternates the preferred feed and permits cleared fallback sources. Both production allowlists are unset; `priority_streamers` is empty. Watchlist names are discovery candidates, not repost permissions. |
| Twitch connection | Blocked: `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` are absent. Do not substitute fabricated IDs or call membership permission for unrestricted automated reposting. |
| Kick connection | Public feed passed the live cloud check without app keys. This does not establish reuse permission for any creator. |
| Audio-first story review | Analyze/render workflow is active and supports 1–60 minutes of bounded analysis. The current 25.7-second Lysium edit has completed render, technical QA and durable archive. Full listening review and individual brand approval remain outstanding. |
| Campaign codes | Watchlist tracking codes are blank. No Whop/Vyro/Clipster/Reach.cat code has been supplied or invented. Lysium's separate per-draft approval requirement still applies. |
| Bounty checks | `ENABLE_BOUNTY_TRACKING=true`; active workflow requests checks every five minutes. No `DISCORD_WEBHOOK_URL` is configured, so external notifications are not operational. No bounty earnings are verified. |
| R2 backups | All four R2 credential settings are present. Exact Lysium file has durable private backup with full hash readback. New live health check passed upload, signed download and deletion of the temporary probe. |
| Cross-posting and publication callbacks | Deferred by the YouTube-only instruction. No connected TikTok, Instagram or Rumble publisher. `clip-published` records a real published URL for a registered campaign cut; it does not publish a video. No synthetic publication receipts were sent. |

The live secret-name audit found Redis, YouTube and R2 credentials only. Discord/Telegram failure alerts are implemented but have no configured destination. Scheduled failures remain visible in GitHub Actions.

## Cloud evidence

[Health run 43765281313](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43765281313) ran once after verifying no active/queued duplicate. It completed with **5/6 checks passed**, and correctly returned failure for the missing Twitch credentials:

- FAIL: Twitch app keys and Helix — missing `TWITCH_CLIENT_ID` (both Twitch secrets are absent).
- PASS: Kick public feed.
- PASS: Redis write/read/delete.
- PASS: FFmpeg gameplay above facecam, stereo AAC.
- PASS: Whisper transcription of the rendered spoken fixture.
- PASS: R2 upload, signed download and deletion of that fixture.

All generated media and transcription ran on the hosted runner. This test did not publish or attempt brand submission. It does not test audience engagement or renew YouTube authorization.

[Posting run 43754348661](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43754348661) was successful as a workflow, but its rendering, archiving and delivery steps were **skipped**. No cleared production creators are configured. Do not report this as a successful post.

## Exact next release

Use [the Lysium approval package](LYSIUM_APPROVAL_PACKAGE.md). The final file is `d764b5e064e80b3d46075dc698e4e27ad2b8816ac24577611fcc0aa527333ee7`, backed up by [run 43758868141](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43758868141).

The user authorized submitting it for review, but file attachment failed and no submission receipt exists. Do not retry the unchanged browser upload or ask again for the same extension setting. The user forbids interaction with their active Chrome. After full playback review, the exact draft must reach the campaign and receive explicit brand approval before public YouTube publication. Generic delivery is not the exact-artifact release path.

The desktop continuation automation was observed paused; this is separate from the enabled GitHub cloud schedules. Its state was left unchanged. R2 has usage billing under the user's explicit authorization; it is not a guaranteed zero-cost service. The expired November 13 GitHub-only publishing-backup exception was not reused.
