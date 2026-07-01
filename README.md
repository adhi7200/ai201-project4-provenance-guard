# Provenance Guard

A multi-signal pipeline that attributes text as human-written or AI-generated, communicates its uncertainty honestly instead of forcing a binary verdict, shows the reader a plain-language transparency label, and gives creators a way to appeal. Built with Flask, Groq, and pure-Python stylometrics, backed by SQLite for a structured audit log.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows (Git Bash); use .venv/bin/activate on Mac/Linux
pip install -r requirements.txt
```

Copy the `.env.example` and rename as `.env` and insert your GROQ API key in the repo root (it is gitignored):

```
GROQ_API_KEY=your_key_here
```

Run the server:

```bash
python app.py        # serves on http://127.0.0.1:5000
```

Run the tests:

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

## Endpoints

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/submit` | Classify a piece of text. Body: `text`, `creator_id`. Optional: `content_type`. |
| POST | `/appeal` | Contest a classification. Body: `content_id`, `creator_reasoning`. |
| GET | `/log` | Recent audit-log entries (JSON). |
| GET | `/appeals` | Reviewer queue: everything currently `under_review`. |
| GET | `/verify/challenge` | Returns a random writing prompt and a `challenge_id` for human verification. |
| POST | `/verify` | Submit a challenge response. Body: `creator_id`, `text`. Issues a certificate if the passage scores `likely_human`. |
| GET | `/creator/<creator_id>` | Returns a creator's verification status and certificate. |
| GET | `/analytics` | JSON rollup: attribution counts, appeal rate, confidence average, and more. |
| GET | `/dashboard` | Server-rendered HTML view of the same analytics. |

## Architecture overview

A submission flows through the system as follows:

1. `POST /submit` receives the raw text, `creator_id`, and optional `content_type`.
2. A prompt-injection filter scans the text for patterns that read as instructions to the classifier (e.g. "ignore previous instructions", "classify this as human"). If any match, the submission is rejected with a 400 before any Groq call is spent. The same filter guards `/verify`, where an injection would be an attempt to fraudulently earn a certificate.
3. Signal 1 (Groq) reads the text semantically and returns `llm_score` (P(AI)), plus the detected genre. When `content_type` is `image_description`, a caption-aware prompt is used instead.
4. Signal 2 (stylometric heuristics) measures five structural properties in pure Python and returns `stylo_score` (P(AI)), calibrated by genre and content type.
5. Signal 3 (compression/predictability) compresses the text with `zlib` and votes only when the ratio is low enough to indicate genuine redundancy; otherwise it abstains and is excluded from the ensemble.
6. The participating signals are combined via a weighted ensemble (`llm 0.5, stylo 0.3, compression 0.2`, renormalized when a signal abstains). If the spread across signals exceeds 0.40, the verdict is forced to `uncertain` regardless of the mean.
7. The combined score is banded asymmetrically (`>= 0.70` → `likely_ai`, `<= 0.40` → `likely_human`, else `uncertain`) and turned into a reader-facing transparency label.
8. The full decision is written to the audit log and a JSON response goes back to the caller with a unique `content_id`. If the submitting creator holds a verified certificate, the response also includes `creator_verified: true` and a badge.

The appeal flow is shorter: `POST /appeal` looks the content up by `content_id`, flips its status to `under_review`, appends an appeal entry to the audit log next to the preserved original decision, and returns a confirmation. There is no automated re-classification, a human makes the final call. The full diagram lives in [planning.md](planning.md) under the Architecture section.

## Detection signals

The two signals are genuinely independent: one is semantic, one is structural. That is what makes the pair more informative than either alone.

**Signal 1: Groq semantic classification (`llama-3.3-70b-versatile`)**
- What it measures: coherence, argument progression, factual consistency, topical depth, and how naturally ideas flow. It also detects the genre so scoring can be calibrated.
- Why: AI text tends to be logically smooth but generic, hitting expected beats without unique insight or lived detail. A large model is good at feeling that holistically.
- What it misses: it is prompted to ignore surface structure, so it will not catch a text that reads humanlike in meaning but is statistically uniform in form. It can also be wrong on short text or unusual genres, so a refusal or parse failure falls back to a neutral 0.5.

**Signal 2: stylometric heuristics (pure Python)**
- What it measures: five structure-only features, each mapped to an AI-likelihood and averaged: sentence-length burstiness (variance of sentence length), sentence-opener diversity, transition/connective-phrase density, punctuation polish (em dashes and smart quotes), and informality (contraction and casual-"i" rate).
- Why: AI prose is measurably more uniform and more polished than human writing. These are cheap to compute, deterministic, reproducible, and need no model call, so they complement the semantic signal well.
- What it misses: it is easily gamed (find-replace the em dashes, add a few typos) and it is unreliable on short text, so below 30 words it abstains to 0.5. Features that have no evidence are held at a neutral baseline rather than counted as human, since absence of an em dash is not proof a human wrote something.

## Confidence scoring

Each signal outputs P(AI) in the range 0 to 1. They are combined via a **weighted ensemble** rather than a flat average:

- Default weights: `llm 0.5, stylo 0.3, compression 0.2`. When the compression signal abstains (ordinary prose), its weight is dropped and the remaining weights are renormalized, so the ensemble always sums to 1.
- `combined = weighted mean of P(AI) across participating signals`
- **Spread gate**: if `max(P(AI)) - min(P(AI))` across participating signals exceeds 0.40, the signals disagree and the verdict is forced to `uncertain` regardless of the mean. This is the generalization of a two-signal gap gate to N signals.

The bands are **asymmetric** because on a writing platform a false positive (calling a human's work AI) is worse than a false negative:

- `combined >= 0.70` and signals agree: `likely_ai`
- `combined <= 0.40` (P(human) >= 0.60): `likely_human`
- anything else: `uncertain`

So a P(AI) of 0.60 does not clear the 0.70 AI bar and lands in `uncertain (leaning AI)`, while a 0.95 clears it and reads as a confident AI verdict. The confidence shown to the reader is verdict-matched: P(AI) for an AI verdict, P(human) for a human verdict, and `max(combined, 1 - combined)` for uncertain, so the number always matches the words.

**How it was validated.** The pipeline was run on four deliberately chosen inputs spanning the range (clearly AI, clearly human, formal human, lightly-edited AI), printing all signal scores separately so a misbehaving signal is visible. This surfaced and fixed two real bugs: the stylometric signal was counting absent features as human evidence (dragging clear-AI text down into `uncertain`), and the uncertain branch was reporting a misleadingly high confidence number.

**Two example submissions with noticeably different confidence** (real `/submit` output):

Higher-confidence case (clearly AI text):
```
llm_score=0.80  stylo_score=0.654  combined=0.745  -> likely_ai
label: "This text shows signals commonly associated with AI generation
        (confidence: 74%). This is an automated estimate, not a verdict.
        If you wrote it yourself, you can appeal."
```

Lower-confidence / opposite case (casual human text):
```
llm_score=0.20  stylo_score=0.278  combined=0.229  -> likely_human
label: "This text reads as human-written (confidence: 77%).
        No strong AI-generation signals were detected."
```

The two land 52 points apart in confidence (74% AI vs 77% human), so the scoring produces genuinely different verdicts and labels, not a constant with a shifting number.

## Transparency label

Labels are neutral and non-accusatory, and always show the confidence as a percentage so a non-technical reader can weigh it. The three variants (exact text, `{pct}` filled in at runtime):

**Highly confident human** (P(AI) <= 0.40):
> "This text reads as human-written (confidence: {pct}%). No strong AI-generation signals were detected."

**Highly confident AI** (P(AI) >= 0.70 and both signals agree):
> "This text shows signals commonly associated with AI generation (confidence: {pct}%). This is an automated estimate, not a verdict. If you wrote it yourself, you can appeal."

**Uncertain** (between the bands, or the signals disagree):
> "Attribution uncertain (confidence: {pct}%). Our signals were mixed or inconclusive for this text, so treat its origin as unconfirmed."

The false-positive asymmetry shows up in the wording too: the AI label explicitly frames itself as an estimate rather than a verdict and points the creator to the appeal path.

## Rate limiting

Applied with Flask-Limiter (in-memory storage), per client IP:

- `/submit`: **10 per minute, 100 per day**
- `/appeal`: **5 per minute, 50 per day**

Reasoning: a real writer submits their own work occasionally, a handful of pieces in a sitting at most, so 10 per minute never gets in a genuine user's way while 100 per day comfortably covers heavy legitimate use. An adversary trying to probe or flood the classifier (each `/submit` costs a Groq call) is stopped quickly and cheaply. Appeals are rarer and higher-friction by nature, so their limits are tighter.

Verified with a 12-request burst against `/submit` (real status-code output, run while the server was live):

```
200
200
200
200
200
200
200
200
200
200
429
429
```

The first 10 requests in the window are accepted, the 11th and 12th are rejected with HTTP 429, confirming the per-minute limit fires exactly at the configured threshold.

## Audit log

Every decision is written to a structured SQLite audit log (not print statements). Each entry records the content id, creator id, timestamp, event type, attribution, combined confidence, both individual signal scores, status, and (for appeals) the creator's reasoning. Real sample from `GET /log`:

```json
{"content_id": "cd50e12b", "creator_id": "demo-ai", "timestamp": "2026-07-01T05:22:27.319Z", "event": "submit", "attribution": "likely_ai", "confidence": 0.745, "llm_score": 0.8, "stylo_score": 0.654, "status": "classified", "appeal_reasoning": null}
{"content_id": "857b0b28", "creator_id": "demo-human", "timestamp": "2026-07-01T05:22:27.684Z", "event": "submit", "attribution": "likely_human", "confidence": 0.771, "llm_score": 0.2, "stylo_score": 0.278, "status": "classified", "appeal_reasoning": null}
{"content_id": "cd50e12b", "creator_id": "demo-ai", "timestamp": "2026-07-01T05:22:58.473Z", "event": "appeal", "attribution": "likely_ai", "confidence": 0.745, "llm_score": 0.8, "stylo_score": 0.654, "status": "under_review", "appeal_reasoning": "I wrote this myself for a class essay. I am a non-native English speaker so my style leans formal."}
```

The appeal entry preserves the original decision (attribution, both signal scores) next to the creator's reasoning, which is what a human reviewer sees in the `/appeals` queue. Note the same `content_id` (`cd50e12b`) appears twice: first as the original `submit` classified `likely_ai`, then as the `appeal` that flipped its status to `under_review`.

Appeal submission and status update (real output):

```bash
curl -s -X POST http://127.0.0.1:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "cd50e12b-9e3b-450b-858c-5fe132e6eb7d", "creator_reasoning": "I wrote this myself for a class essay. I am a non-native English speaker so my style leans formal."}'
```

```json
{"content_id": "cd50e12b-9e3b-450b-858c-5fe132e6eb7d", "status": "under_review", "message": "Request under review. Please check back later."}
```

## Stretch features

### Ensemble detection (3 signals, weighted voting)

The pipeline runs a third signal and combines all three with a documented weighted ensemble instead of a two-signal gate.

- **Third signal, compression/predictability** (`compression_signal` in `signals.py`): the text is compressed with `zlib` and the ratio of compressed to raw size is taken. Redundant, low-entropy writing compresses smaller, which reads AI-like. It measures raw information redundancy, so it is genuinely distinct from the semantic and stylometric signals. Measuring real prose showed that ordinary AI and human text compress almost identically (both around 0.65), so this is a one-directional cue: strong redundancy votes AI, but ordinary compressibility is not evidence of a human. On short or ordinary text the signal abstains and is left out of the ensemble rather than diluting the other two.
- **Weighted ensemble** (`scoring.py`): each participating signal reports P(AI) and the combined score is a weighted mean with `llm 0.5, stylo 0.3, compression 0.2`. GROQ is heaviest because semantics is the hardest property to fake, stylometry is a solid but gameable middle, and compression is the noisiest cue so it gets the least say. When a signal abstains, its weight is dropped and the rest are renormalized.
- **Generalized agreement gate**: if the spread (max minus min P(AI) across the participating signals) exceeds 0.40, the signals disagree and the verdict is forced to `uncertain`. This is the two-signal gap gate extended to N signals. The asymmetric bands and verdict-matched confidence are unchanged.

Verified live with three inputs, each showing individual signal scores alongside the ensemble result (real `/submit` output):

```
# Ordinary AI prose -- compression abstains (ordinary entropy)
llm_score=0.80  stylo_score=0.654  compression_score=null   combined=0.745  -> likely_ai

# Casual human prose -- compression abstains
llm_score=0.20  stylo_score=0.278  compression_score=null   combined=0.229  -> likely_human

# Repetitive passage ("The system is efficient. The system is reliable...") -- compression fires
llm_score=0.99  stylo_score=0.690  compression_score=0.891  combined=0.880  -> likely_ai  (all three agree)
```

The third case is the ensemble working as designed: the compression signal only enters the vote when it detects real redundancy (here ratio dropped below 0.45), and with all three signals pointing the same way the confidence climbs to 0.88.

### Analytics dashboard (HTML page + JSON API)

Two views of the same rollup data, computed from the live database:

- `GET /analytics` -- JSON endpoint with: total submissions, counts by attribution / genre / content type, appeal rate, average combined confidence, signal-agreement rate (fraction of submissions that reached a non-uncertain verdict), and verified-creator submission count.
- `GET /dashboard` -- server-rendered HTML table of the same numbers via `render_template_string`, readable in a browser with no JavaScript.

All metrics are computed in `get_analytics()` in `store.py` directly over the `content` and `audit_log` tables. The appeal rate and signal-agreement rate together show how often the system is contested and how often its signals actually converge -- the two most useful indicators of classifier health over time.

Sample `GET /analytics` response (real output). The three required metrics are the attribution breakdown (detection pattern), the appeal rate, and the signal-agreement rate as the additional metric of choice:

```json
{
  "total_submissions": 20,
  "by_attribution": {"likely_ai": 5, "likely_human": 6, "uncertain": 9},
  "by_genre": {"blog": 9, "image_description": 1, "other": 10},
  "by_content_type": {"text": 19, "image_description": 1},
  "appeal_rate": 0.1,
  "avg_confidence": 0.7,
  "signal_agreement_rate": 0.55,
  "verified_creator_submissions": 1
}
```

### Provenance certificate (live writing challenge)

A creator earns a "Verified Human" badge by completing a live writing challenge scored by the same ensemble pipeline used for classification.

- `GET /verify/challenge` returns a random personal-experience prompt and a `challenge_id`. The prompts are designed to be hard to answer generically -- they ask for specific memories, changed opinions, or misread situations.
- `POST /verify` accepts `creator_id` and the written `text`. The ensemble runs on the passage; a `likely_human` verdict issues a `certificate_id` (uuid), stores it in the `creators` table, and returns the credential. Any other verdict returns a friendly failure with a suggestion to try a different sample.
- Verified creators get a `creator_verified: true` field and a `badge: "Verified Human creator"` on every subsequent `/submit` response. The `creator_verified` flag is also stored on the content row so analytics can count verified submissions.
- `GET /creator/<creator_id>` shows credential status and the `verified_at` timestamp.
- Verification attempts are logged to the audit log as `event='verify'` with the attribution and confidence from that run.

Verified live (real output):

```bash
curl http://127.0.0.1:5000/verify/challenge
```
```json
{"challenge_id": "2be41c4d1effc176", "prompt": "Write about something you wish you had said at the time."}
```

```bash
curl -s -X POST http://127.0.0.1:5000/verify \
  -H "Content-Type: application/json" \
  -d '{"creator_id":"demo-human","text":"honestly i changed my mind about mornings this year. used to think i was a night person, hated waking up early... but i started walking my dog at 6am and now weirdly i love it. still hate the alarm though."}'
```
```json
{"verified": true, "certificate_id": "f519c5f5-ee13-4e9b-a738-bfb4918e0545", "message": "Verification passed. Your Verified Human badge is now active."}
```

A subsequent `/submit` from the same creator now carries the badge, distinguishing it from a standard classification response:
```json
{"content_id": "332be8bb-...", "attribution": "likely_human", "confidence": 0.803,
 "creator_verified": true, "badge": "Verified Human creator",
 "label": "This text reads as human-written (confidence: 80%). No strong AI-generation signals were detected."}
```

The `badge` field is separate from the neutral transparency `label`: the label describes the content's attribution, while the badge marks the creator as a verified human. An unverified creator's response has `creator_verified: false` and no `badge` field at all.

### Multi-modal support (image descriptions)

`/submit` accepts an optional `content_type` field: `"text"` (default) or `"image_description"` for image captions and alt-text.

- **Groq signal** switches to a caption-aware system prompt when `content_type` is `"image_description"`, so the model judges specificity and naturalness of observation rather than argument progression, which is the wrong lens for a caption.
- **Stylometric signal** uses a lower minimum-word threshold for captions (8 words vs 30 for prose) so a short caption can score rather than abstain by default.
- `content_type` is stored on the content row and written to the audit log, and echoed in the `/submit` response, so the modality is visible throughout.

Example caption submission and response (real output):

```bash
curl -s -X POST http://127.0.0.1:5000/submit \
  -H "Content-Type: application/json" \
  -d '{"text":"A golden retriever leaping through autumn leaves in a sun-dappled park while a kid laughs in the background","creator_id":"demo-human","content_type":"image_description"}'
```
```json
{
  "content_id": "3c22f8e5-f27e-4d04-9578-af96f4e88c2d",
  "attribution": "likely_human",
  "confidence": 0.694,
  "genre": "image_description",
  "content_type": "image_description",
  "llm_score": 0.2,
  "stylo_score": 0.483,
  "rationale": "The description includes specific, natural details like the dog breed, season, and the kid's laughter, suggesting a human observation.",
  "label": "This text reads as human-written (confidence: 69%). No strong AI-generation signals were detected."
}
```

The `content_type` is echoed in the response and the caption-aware Groq prompt drives the rationale toward observation specificity, which is the right lens for a caption rather than argument flow.

## Known limitations

- **Lightly-edited AI output slips through as human.** In testing, an AI-drafted paragraph that a human lightly edited scored `llm=0.20, stylo=0.38 -> likely_human`. This is tied directly to the signals: once a human breaks the surface tells (em dashes, adds a typo, varies a sentence) the stylometric signal relaxes, and if the semantic flow reads natural the Groq signal relaxes too. When both signals genuinely relax, there is nothing left to catch. This is the honest failure mode of any detector and the reason the appeal path exists.
- **Non-native formal writers risk a false positive.** Clean grammar, low typo rate, and uniform structure are exactly what the stylometric signal reads as AI. The asymmetric bar plus appeals are the mitigation, but this population is where the system is most likely to be unfair, which is why the AI label is worded as an estimate, not an accusation.

## Spec reflection

**Where the spec helped:** deciding the meaning of the confidence score before writing any scoring code paid off directly. Because planning.md fixed what a 0.6 should mean to a user (below the AI bar, so uncertain-leaning-AI) and committed to an agreement gate, the scoring function was a near-mechanical translation of the spec, and the four-input validation caught the two bugs immediately because the expected bands were already written down.

**Where the implementation diverged:** the intro of planning.md describes combining signals by "asymmetric weightages," implying fixed per-signal weights. During design that became an agreement gate instead: an equal mean when the signals agree, and a forced `uncertain` when they disagree. The gate turned out to encode the same intent (trust the signals more when they concur) while also giving a principled, honest answer when they conflict, which fixed weights could not.

## AI usage

- I directed the AI to generate the stylometric signal function from the Detection signals section of planning.md (the five feature families). It produced a working first version, but on the four-input validation the clearly-AI paragraph scored only 0.49 and fell into `uncertain`. I diagnosed that two features (sentence-opener diversity and punctuation) were treating the absence of a feature as strong human evidence, and directed the AI to recenter them to a neutral baseline. After that fix, clear-AI text scored 0.65 and all three bands became reachable.
- I directed the AI to generate the confidence-scoring function against the Uncertainty representation spec. Reviewing its output I caught that the `uncertain` branch reported `1 - abs(combined - 0.5) * 2`, which made a near coin-flip display as high confidence (92%) next to the word "uncertain." I overrode it to report the strength of the insufficient lean instead, so an uncertain verdict never shows a misleadingly confident number.

## Portfolio walkthrough

[Watch the walkthrough](https://www.loom.com/share/your-video-id)
