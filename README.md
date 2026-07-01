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
| POST | `/submit` | Classify a piece of text. Body: `text`, `creator_id`. |
| POST | `/appeal` | Contest a classification. Body: `content_id`, `creator_reasoning`. |
| GET | `/log` | Recent audit-log entries (JSON). |
| GET | `/appeals` | Reviewer queue: everything currently `under_review`. |

## Architecture overview

A submission flows through the system as follows:

1. `POST /submit` receives the raw text and `creator_id`.
2. Signal 1 (Groq) reads the text semantically and returns a probability that it is AI-generated (`llm_score`), plus the detected genre.
3. Signal 2 (stylometric heuristics) measures structural properties of the text in pure Python and returns its own probability (`stylo_score`), calibrated by the detected genre.
4. The two scores are combined through an agreement gate into a single confidence and an attribution band (`likely_ai`, `likely_human`, or `uncertain`).
5. The attribution and confidence are turned into a reader-facing transparency label.
6. The full decision (both signal scores, combined confidence, attribution, label, genre) is written to the audit log, and a JSON response goes back to the caller with a unique `content_id`.

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

Both signals output P(AI) in the range 0 to 1. They are combined with an **agreement gate** rather than a flat average, so conflicting signals never produce false confidence:

- `gap = |llm_score - stylo_score|`
- `gap <= 0.25` (signals agree): `combined = mean(llm_score, stylo_score)`
- `gap > 0.25` (signals disagree): force `uncertain` regardless of the mean

The bands are **asymmetric** because on a writing platform a false positive (calling a human's work AI) is worse than a false negative:

- `combined >= 0.70` and signals agree: `likely_ai`
- `combined <= 0.40` (P(human) >= 0.60): `likely_human`
- anything else: `uncertain`

So a P(AI) of 0.60 does not clear the 0.70 AI bar and lands in `uncertain (leaning AI)`, while a 0.95 clears it and reads as a confident AI verdict.

0.51 and 0.95 map to genuinely different places, not a hard flip at 0.5. The confidence shown to the reader is the confidence in the stated verdict (P(AI) for an AI verdict, P(human) for a human verdict), so the number always matches the words.

**How it was validated.** The pipeline was run on four deliberately chosen inputs spanning the range (clearly AI, clearly human, formal human, lightly-edited AI), printing both signal scores separately so a misbehaving signal is visible. This surfaced and fixed two real bugs: the stylometric signal was counting absent features as human evidence (dragging clear-AI text down into `uncertain`), and the uncertain branch was reporting a misleadingly high confidence number.

**Two example submissions with noticeably different confidence:**

Higher-confidence case (clearly AI text):
```
llm_score=0.80  stylo_score=0.65  combined=0.727  -> likely_ai
label: "This text shows signals commonly associated with AI generation
        (confidence: 73%). This is an automated estimate, not a verdict.
        If you wrote it yourself, you can appeal."
```

Lower-confidence / opposite case (casual human text):
```
llm_score=0.20  stylo_score=0.25  combined=0.224  -> likely_human
label: "This text reads as human-written (confidence: 78%).
        No strong AI-generation signals were detected."
```

For contrast, a formal human paragraph produced `llm=0.40, stylo=0.52, combined=0.46 -> uncertain`, which is exactly the honest outcome for genuinely ambiguous input.

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

Reasoning: a real writer submits their own work occasionally, a handful of pieces in a sitting at most, so 10 per minute never gets in a genuine user's way while 100 per day comfortably covers heavy legitimate use. An adversary trying to probe or flood the classifier (each `/submit` costs a Groq call) is stopped quickly and cheaply. Appeals are rarer and higher-friction by nature, so their limits are tighter. Verified: a 12-request burst returns HTTP 200 up to the limit and then 429 for the rest.

## Audit log

Every decision is written to a structured SQLite audit log (not print statements). Each entry records the content id, creator id, timestamp, event type, attribution, combined confidence, both individual signal scores, status, and (for appeals) the creator's reasoning. Real sample from `GET /log`:

```json
{"content_id": "4008c299", "creator_id": "u1", "timestamp": "2026-07-01T04:03:45.667Z", "event": "submit", "attribution": "likely_ai", "confidence": 0.727, "llm_score": 0.8, "stylo_score": 0.654, "status": "classified", "appeal_reasoning": null}
{"content_id": "9f704613", "creator_id": "u2", "timestamp": "2026-07-01T04:03:46.354Z", "event": "submit", "attribution": "likely_human", "confidence": 0.776, "llm_score": 0.2, "stylo_score": 0.247, "status": "classified", "appeal_reasoning": null}
{"content_id": "4008c299", "creator_id": "u1", "timestamp": "2026-07-01T04:03:46.453Z", "event": "appeal", "attribution": "likely_ai", "confidence": 0.727, "llm_score": 0.8, "stylo_score": 0.654, "status": "under_review", "appeal_reasoning": "I wrote this myself, I am a non-native speaker so my style is formal."}
```

The appeal entry preserves the original decision (attribution, both signal scores) next to the creator's reasoning, which is what a human reviewer sees in the `/appeals` queue.

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


