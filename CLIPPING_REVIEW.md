# GTA clipping setup review — revised November 14, 2026

## Scope and evidence

Reviewed the first loaded results of the user's YouTube query, excluding ads, game trailers and unrelated graphics analysis. Search results change and are not a finite playlist. Initially read two full transcripts. On November 14, successfully read the full Strategy transcript previously marked inaccessible, plus a related 22-minute campaign tutorial. The transcript panels needed time to load even when the exporter failed. Four full transcripts have now been read; this is not a claim to have watched their complete audiovisual demonstrations or every search result. Earnings claims remain unverified.

Full transcripts reviewed:

- [Jad M.H — Free GTA clipper skill](https://www.youtube.com/watch?v=5-SDYLlGZFw): audio-first screening, transcription, loudness/chat activity, strict shortlisting, then targeted rendering. Shows a claimed four-hour stream yielding three clips. Offers local Claude/Ollama approaches. The claimed timing and potential views were not independently benchmarked.
- [Kevis Unfiltered — Claude GTA channel](https://www.youtube.com/watch?v=WJY5PGY-rM0): research topics viewers care about; write an original angle; review AI scripts; package clearly; use modest tags. Promotes ChannelRecipe, including paid volume features. Its channel results do not establish this channel's likely earnings.
- [GTA 6 Explained — Full Strategy](https://www.youtube.com/watch?v=1ecn2fLXDQ0): 0:29–1:37 emphasizes original commentary, creativity and creator permission; 2:43–3:28 suggests optional AI initial cuts and learning free tools before paying. This is advice, not a complete automation implementation.
- [Kamil Sattar — Claude + Whop tutorial](https://www.youtube.com/watch?v=6nGc3yCGByI): 4:37–6:29 compares campaign rates, caps and remaining budgets; 6:45–11:53 studies winners and audience-specific hooks; 12:15–16:21 uses only campaign resources and converts exact rules into an edit brief; 18:14–18:42 removes boring cuts and moves the strong spoken reaction to the opening; 21:47–22:08 submits the live URL for review. The demonstrated campaign forbids added background music. Its deadline, rates and rules are not universal. The title says $6,500/month, while at 0:54–1:10 the speaker attributes about $1,000 of a $3,200 balance to clipping. None of these balances are verified here.

Long-form results with inaccessible transcripts:

- [Romayroh — $10K/month](https://www.youtube.com/watch?v=mBG1S1KdPTE)
- [Korpi Creator — Viral AI videos](https://www.youtube.com/watch?v=qwZxGSoRMzE)
- [AI Vision — Claude Shorts channel](https://www.youtube.com/watch?v=5mGEmbVVV2s)
- [Syrax — Monetized in seven days](https://www.youtube.com/watch?v=z7AZZXk3K5o)
- [Alex Christian — Make real money](https://www.youtube.com/watch?v=OgFi_EORQmY)
- [AiKey — Generate gameplay](https://www.youtube.com/watch?v=whAA0_NiPho)

Shorts with inaccessible transcripts (IDs from the actual search results):
FPxLuqKlOBg, yZ7RcW75gPE, lRO8MfoLM6M, 4Lw1EppsSBU, Kjpvm9fbVYw,
NtfIypCrAq8, ckpYeDGJysQ, AU7Rd8ual-8, B5QoEKZtvK0, PWSPg6WXy0o,
lC1b-FzDFOE, 3uh0VsqxaOQ, ui9hbHVSVnA, BsxeWbsHQz0, D3C-PnwcFsI.
Several titles explicitly disclose Higgsfield partnerships. A sponsored tool demonstration is not payout evidence.

## Selected approach

Keep the existing CPU-only cloud stack: creator-cleared sources, source view counts/velocity, Whisper, FFmpeg, Redis duplicate protection and verified backups. Test five different clips per day, maintain editorial review and compare outcomes before expanding.

Applied:

1. Add relative audio-energy spikes and opening-word timing/filler to candidate scoring. These are inexpensive heuristics, not semantic AI judgments or guarantees of entertainment.
2. Disable unused TikTok compilations on cloud runs unless TikTok credentials or an explicit BUILD_COMPILATION override exists. Avoid rendering another 65 seconds for an unconnected destination.
3. Preserve original gameplay/reaction audio with loudness normalization; added music is opt-in. Caption cards contain at most three words and last no more than 1.8 seconds.
4. Add explicit $500/month scenario math to the existing cloud report. No source-view-to-revenue conversion and no invented payouts.

Not installed: third-party downloadable skills, paid subscriptions, local Ollama models, paid video generators, or paid communities. A local 16–32 GB LLM does not fit the user's cloud-only constraint or the current standard runner.

Correction: the earlier changes did not implement the main tutorial's discovery workflow. Ranking already-cut clips by volume is not semantic story selection. Long recordings can contain better moments than existing public clips; the previous dismissal of that path was unsupported.

Added `stream_review.py` and the manual **Audio-first stream review** cloud workflow. It validates a reviewed source and age restrictions, retrieves an audio section (1–60 minutes per run), transcribes it, and exports 12-minute windows with 44 seconds of overlap. `bestaudio` is preferred; sources lacking a separate audio rendition may transfer a muxed section before discarding video. It never downloads a full multi-hour video to find a short moment. After an editor selects setup/payoff stories, render mode downloads only those 18–43.9-second sections, checks speech/music, renders sparse captions with original audio, and verifies decoding. Artifacts stay in GitHub for seven days; temporary media/models are removed from the runner. No social credentials are exposed to this workflow.

This is an editor-assisted draft path, not autonomous semantic selection. The review prompt explicitly rejects context-dependent jokes, filler and invented visual events. Decisions are bound to the source and transcript digest; overlaps, out-of-range times and missing story reasons are rejected. Only the already-cleared DougDoug archival plane source is configured as an integration test; it was already published and is not a new content recommendation or permission for current VODs. Add approved long recordings individually to `review_sources.json`, then analyze sections and place the editor's decision in `reviews/<source_id>.json`. Visual/audio preview review remains required before publication. There is no approved funded campaign, authenticated retention feedback loop, live-chat spike analysis, automatic facecam detection or unattended semantic model integration yet.

Validation: 48 local tests ran, 40 passed and eight environment-dependent checks skipped. [Live source validation/audio transcription](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43609853778) passed on the 33-second archival test source. The transcript supports testing 12.1–32.9 seconds as a stronger story, preserving the spoken landing payoff at 24.52 seconds. [The selected-section run](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43610104699) successfully retrieved the review artifact and downloaded the section, but the music-risk screen rejected it before rendering. No successful new rendered preview or improvement in retention is claimed. A rejection now produces a diagnostic JSON with the precise flagged interval; the classifier is not copyright identification. Do not truncate away the payoff simply to get a passing screen. The full multi-hour path has not been benchmarked on an approved long recording.

## Money decision

November 14 follow-up: [diagnostic run 43611649341](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43611649341) confirmed the music-risk rejection at source seconds **23.14–31.30**, overlapping the spoken landing payoff. The rejection report was archived successfully (artifact 14119963897); nothing rendered or published. The outcome is recorded in `reviews/dougdoug-plane.json` to prevent unchanged retries. Next work should investigate the actual audio/classifier evidence or choose another approved source, not remove the payoff or weaken the threshold to obtain a pass. An hourly Codex chat follow-up is active; it is separate from the GitHub cloud video workers.

Prioritize a funded creator campaign or editing contract as the first revenue experiment, with explicit permitted platforms, rate, approved footage, remaining budget, and submission rules. DougDoug fan permission is not a bounty contract. A public GTA music campaign has now been found; see [the dated campaign research](CAMPAIGN_RESEARCH.md). It supports TikTok/Instagram, not the currently connected YouTube route. No paid campaign enrollment or eligibility has been verified for this channel.

November 14 classifier investigation: [run 43617368361](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43617368361) validated the new diagnostic trace test and retained the same rejection. The downloaded section was exactly 20.8 seconds. Within the 23.14–31.30s interval, 16 of 17 hops were classified as music; music scores were 0.414–0.984 and speech scores 0–0.414, including ten hops overlapping Whisper words. Singing scores were at most 0.020. This supports a music-dominant classifier result, not a claim to identify copyrighted music or a claim of zero speech. Thresholds were not changed. Forty local tests passed, nine environment-dependent checks skipped; the new NumPy trace regression passed on the runner. Next candidate: the separately cleared archival counting clip, with the same channel/age checks and no publishing authority inferred from preview processing.

Maintain YouTube as the connected distribution test. Reused-content rules require meaningful original contribution; captions, hashtags, music and vertical cropping do not guarantee admission to monetization. The dated November 13 publication backup exception has expired; preview artifacts are not authorization to publish new clips without the required backup.

[Counting-source analysis 43617660796](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43617660796) passed source validation and transcription. Its spoken payoff finishes around 6.36 seconds, with only isolated transcribed words until 36.22 seconds. The editor rejected it for insufficient evidence of a strong 18–43.9-second continuous story, rather than padding the quota. The decision is saved in `reviews/dougdoug-counting.json`. Empty selections with an explicit rejection reason now exit cleanly before downloading video or loading the audio classifier, matching the review prompt's promise that zero selections is valid. Next work should find a stronger approved archival source, not repeatedly process these two rejected stories. No new video was published.

At a hypothetical net $0.10/1,000 qualified views, $500 requires 5,000,000 qualified views before expenses/tax. At a hypothetical $1 campaign CPM with a 10% fee, it requires 555,556 approved qualifying views. These rates are illustrative, not offers or this channel's measured RPM. Add all monthly expenses before calculating profit.

November 14 voice-control preview: [source analysis 43622804580](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43622804580) passed. The 8.9–35.9s selection retains repeated commands and the final thankful reaction; uncertain Whisper command spellings are omitted from on-screen captions while the transcript still feeds speech/music screening. The first render attempt exposed a real path bug: FFmpeg ran in the output directory but was given only the source basename from a different temporary directory. The renderer now uses the absolute input path. A new separate-directory regression and all six story checks passed on the runner. [Render 43623342326](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43623342326) then passed music screening, rendering, decoding, artifact upload and cleanup. The 27-second draft is in [artifact 14124797522](https://github.com/kpateldabears1-beep/gta6-clip-empire/actions/runs/43623342326/artifacts/14124797522), expiring November 21 at 17:52 UTC. This is technical validation, not completed visual/audio editorial review or proof of copyright clearance. No social publication occurred. Check the prior source ledger before any release; it came from the older batch's candidate list. Local suite: 51 tests, 41 passed, ten environment-dependent skips.

Current next work: review the successful cloud draft without downloading media to this computer; complete durable backup setup; verify the TikTok/Instagram account connections and full brief for the public paid lead in `CAMPAIGN_RESEARCH.md`. The public GTA music campaign does not accept YouTube. Do not repeatedly process the two rejected sources or treat the successful technical preview as a fresh, approved upload.

Still needed: durable backup after the November 13-only GitHub exception; an approved paid campaign; publisher connections for Instagram/Rumble; TikTok account authorization; actual analytics and payout evidence. Do not treat public RSS views as retention, engaged views, qualified views, or revenue.

## Primary references checked

- [YouTube YPP eligibility](https://support.google.com/youtube/answer/72851): ad-sharing qualification and review.
- [YouTube monetization policies](https://support.google.com/youtube/answer/1311392): reused and inauthentic content, independent of copyright permission.
- [Shorts ad guidance](https://support.google.com/youtube/answer/12929256): non-original Shorts ineligible for revenue sharing.
- [Content Rewards fees](https://help.contentrewards.com/en/articles/15725120-how-your-payout-fees-work): CPM fees of 10% of earnings.
- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions): standard public-repository compute and storage billing are distinct.

No fixed dollar revenue or monetization date is promised. Recheck current terms and available campaign budgets before committing production to them.
