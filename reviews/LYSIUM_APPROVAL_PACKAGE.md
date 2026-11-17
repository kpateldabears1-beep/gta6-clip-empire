# Lysium draft — Prayer Before The Getaway

Prepared November 15, 2026. **Submission authorized; file attachment pending. Not submitted, brand-approved or publicly posted.**

## Exact video

- **25.7 seconds**, vertical 1080×1920 H.264 MP4, stereo AAC original source audio; no added music.
- [Finished MP4 bundle](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43758501170/artifacts/14178438950): use `preview-1.mp4`. GitHub copy expires November 22 at 20:32 UTC.
- Durable private R2 copy: bucket `daily-getaway-clips`, object `reviews/d764b5e064e80b3d46075dc698e4e27ad2b8816ac24577611fcc0aa527333ee7/preview.mp4` (40,187,823 bytes).
- SHA-256: `d764b5e064e80b3d46075dc698e4e27ad2b8816ac24577611fcc0aa527333ee7`.
- [Backup verification](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43758868141): upload, full-object hash readback and temporary signed GET all passed. Private download manifest: `manifests/43758868141/1.json`; its signed link expires after six hours, while the video stays stored.

## Edit and evidence

Source: [Lysium — Lord takes the wheel](https://www.twitch.tv/lysium/clip/TrustworthyRichPenguinNomNom-zl3nbXhe6Sz7152a), **21.3–47.0 seconds**. The original recording was verified as NoPixel V on Lysium's channel. The cut removes the earlier repeated setup, keeps the driving question and prayer, then the drive-away and completed apology. The center square crop enlarges the scene without inventing a facecam. A brief four-word hook and permanent `Clip: @Lysium` credit replace heavy captioning. No uncertain ASR subtitles are added.

[Render](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43758501170) passed the unchanged music screen, crop/path and permanent-credit pixel regressions, plus decoding. [QA](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43758748876) verified the selected file and six frames. Redis had no prior record for the source. Audio measures −16.74 LUFS integrated, −2.03 dBTP peak, **14.70 LU range**. The compressor does not establish consistent dialogue or better subjective sound: the measured range increased from the older cut. Full-motion and listening review is still required before calling this editorially approved. The final six frames confirm credit remains visible after the opening hook disappears. The earlier render with disappearing credit is superseded. Technical screening does not establish copyright clearance or audience performance.

## Proposed YouTube title and caption

**Benji's prayer turns into a getaway | GTA RP**

```text
A roadside prayer. A getaway. Then the apology.

GTA V roleplay on NoPixel V.
Clip: @Lysium — https://twitch.tv/Lysium

#GTA5 #GTARP #NoPixel #Lysium #Shorts
```

## Prepared draft-review note

```text
Draft for @DailyGetawayClips on YouTube: “Benji's prayer turns into a getaway.”

25.7-second NoPixel V edit from your “Lord takes the wheel” clip (21.3–47.0s). It keeps the original audio, adds no music, enlarges the gameplay, and includes permanent @Lysium credit with a brief opening hook. The channel bio links to twitch.tv/Lysium.

Please review this exact draft and proposed caption before publication. Happy to revise any timing, framing or wording you want changed.
```

## Remaining release steps

1. Watch/listen to the entire exact MP4, especially dialogue intelligibility and the opening question. Do not treat frame samples as this review.
2. The campaign form is open with the proposed caption entered. Upload this MP4 in the [Lysium campaign's Drafts form](https://contentrewards.com/c/campaigns/6d896f33-152f-42a9-92f4-662199228349); await explicit approval of this exact version. The form requires a video file, not a GitHub artifact URL. No brand message or draft submission has been sent by the agent.
3. Record the brand's approval reference and actual full-playback review in `reviews/releases/lysium-wheel.json`. The `approved_release_sha256` must equal `release_digest(plan)` from `scripts/release_review.py`, binding the video and complete approved YouTube metadata. The current status is deliberately `not_submitted`. Only after real approval, run **Release exact approved Lysium draft → publish** on main. It retrieves and hashes the durable R2 file, reserves the source against the daily cap, preserves exact caption text, and records the YouTube receipt in Redis and R2. Use its default **verify** mode to check cloud retrieval without any YouTube upload or reservation. Do not use generic `deliver`, which discovers fresh candidates.
4. Submit the resulting live YouTube URL to the campaign. No earnings are promised.

R2 setup and durable backup are complete. The user authorized one temporary local copy solely to submit this exact draft, then removal. Its SHA-256 was verified. File upload remained blocked even after the user confirmed enabling file access in the Work profile. The user's latest instruction prohibits interacting with their active Chrome browser, including native controls, profiles and tabs. Do not resume the earlier picker handoff or repeat requests to toggle that setting. No attachment or submission receipt exists. The authorized temporary copy is Downloads/preview.mp4 and must be removed after submission or abandonment. All other media remains on cloud runners. Current publishing scope is YouTube only; see [verified setup status](SETUP_STATUS.md). Creator approval and the final listening review remain separate.
