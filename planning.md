## Provenance Guard -- planning.md

Text is taken through a initial parser that scans for malicious prompts and filters out harmful attempts at prompt injection before transferred to the signal tools through POST /submit. The tool will classify based on type of text (e.g. poem, short story, blog post, novel, news, etc.) and weigh the confidence on each of the signals, average it down the asymmetric weightages of each signal, apply a transparency label when AI confidence exceeds 70% or human confidence exceeds 60%, an uncertain label for anything in between or whenever the two signals disagree, alongside a confidence score (0-1.00). Every attribute decision will be logged in the audit log with fields for attribution, confidence score, signals used, any requests for appeals, endpoints used (in order of usage).

The appeals workflow will submit to POST/ appeal endpoint and update status to under review, log it in the audit log and send a reponse to user- "Request under review. Please check back later."

---
## Detection signals

**LLM-based classification:** GROQ evaluates the *meaning and flow of logic* of the text including coherence, argument progression, factual consistency, and topical depth to produce an attribution, a confidence score (0–1.00), and a transparency label. This classification is strictly **semantic**, never structural: it must ignore punctuation, formatting, and surface grammar (those are handled by the Stylometric signal) to avoid double-counting the same evidence. The prompt is genre-aware (poem / short story / blog / novel / news), since "good logical flow" means different things per genre. Output is constrained to a strict JSON schema (`attribution`, `confidence`, `rationale`, `genre`) so it can be averaged with other signals. Low-confidence or refusal responses fall back to `uncertain` rather than guessing.

**Stylometric Heuristics:** Each is a cheap regex/stat computation (no model call), making it a fast complement to GROQ. Thresholds are calibrated per genre (set after classification). These tools will measure:
- Punctuation
    - the grammar used
    - looking for em dashes (high em-density/1k words => AI)
    - Unicode (AI) vs ASCII (human) characters like curly and straight apostrophes
    - AI is >95% consistent with 
        - Oxford comma consistency
        - Spacing regularity
        - Clean ellipsis form
- Sentence & paragraph structure
    - sentence length invariance (--> AI)
    - paragraph length uniformity (--> AI)
    - sentence opener diversity (lack of --> AI) measured by distinct first-word/first-bigram ratio
- Lexical structure
    - type-token ratio / vocabulary richness
    - function-word frequency distribution (Burrows's Delta style: *the, of, and, to, that, it*)
    - hapax legomena rate (words appearing once; higher --> human)
    - average word length / syllable count (longer, more Latinate --> AI)
- Formatting artifacts
    - unprompted markdown scaffolding: bullets, **bold lead-ins:**, headers, numbered lists (--> AI)
    - list-item grammatical parallelism (rigid --> AI)
- Repetition & rhythm
    - n-gram repetition of connective phrases ("it's important to note", "plays a crucial role") (--> AI)
    - bigram/trigram self-similarity across the document
    - transition-word density (high --> AI)
- Error signature (often strongest)
    - typo / misspelling rate (near-zero --> AI)
    - grammatical-imperfection rate: comma splices, fragments, tense drift (present --> human)
    - internal inconsistency: mixed US/UK spelling, mid-document formatting shifts (present --> human)

**Design notes:**
- Per-genre calibration is required (a poem is bursty + clean by design; a blog tolerates markdown).
- The em-dash signal is popular but easily defeated by find-replace and prone to false positives, weighed as low signal
- All features degrade gracefully on short text where LLM classification is shaky, and produce a single normalized stylometric confidence (0–1.00) to feed the weighted average.

## Uncertainty representation
Each signal outputs a P(AI) score from 0 to 1.00 (`llm_score`, `stylo_score`). The two are combined through an agreement gate before they get banded into a label, so conflicting signals never produce false confidence.
- agreement gate: `gap = |llm_score - stylo_score|`
    - `gap <= 0.25` (signals agree): `combined = mean(llm_score, stylo_score)`, confidence reported as-is
    - `gap > 0.25` (signals disagree): force uncertain regardless of the mean, since our signals are conflicting
- bands, asymmetric so a tie favors the creator (a false positive is worse than a false negative here)
    - `combined >= 0.70` and signals agree: Likely AI
    - `combined <= 0.40`, i.e. P(human) >= 0.60: Likely human
    - anything else: Uncertain
- what a 0.6 means: P(AI) = 0.60 sits below the 0.70 AI bar, so it labels Uncertain (leaning AI), not AI. A 0.95 clears the bar and gives a confident AI label, so 0.51 and 0.95 land in genuinely different places
- genre calibration: genre is detected first, then the stylometric thresholds (burstiness, markdown tolerance, typo expectations) are picked per genre before scoring, so a clean poem is not auto-flagged as AI
- validation: run the 4 test inputs (clear-AI, clear-human, formal-human, edited-AI), print `llm_score` and `stylo_score` separately, and confirm the bands hold and the edited-AI case lands in uncertain through the gate

## Transparency label design
Neutral and non-accusatory, with the confidence percentage shown so a non-technical reader can weigh it.

**Highly confident human:** (P(AI) <= 0.40)
> "This text reads as human-written (confidence: {pct}%). No strong AI-generation signals were detected."

**Highly confident AI:** (P(AI) >= 0.70 and both signals agree)
> "This text shows signals commonly associated with AI generation (confidence: {pct}%). This is an automated estimate, not a verdict. If you wrote it yourself, you can appeal."

**Uncertain:** (between the bands, or the signals disagree)
> "Attribution uncertain (confidence: {pct}%). Our signals were mixed or inconclusive for this text, so treat its origin as unconfirmed."

## Appeals workflow
A creator who disputes a classification can contest it, which flags the content for human review without any automated re-classification.
- who: the content creator (the `creator_id` on the original submission)
- provides: `content_id` and `creator_reasoning` (free text)
- system does: look up `content_id`, set status to "under_review", append an appeal entry to the audit log next to the preserved original decision (original attribution, confidence, both signal scores), and return "Request under review. Please check back later."
- reviewer view (appeal queue): all entries with `status = under_review`, showing the original text, `llm_score`, `stylo_score`, combined confidence, the label shown, `creator_reasoning`, and timestamps
- no automated re-classification, a human makes the final call

## Anticipated edge cases
- non-native formal writer: clean grammar, low typo rate, and uniform structure, so stylometry false-positives it as AI. mitigated by the higher AI bar plus appeals, and GROQ may rescue it through genuine lived-experience cues
- repetitive simple-vocab poem: low type-token ratio, high n-gram repetition, and uniform line length, so the heuristics read it as AI. mitigated by genre-aware calibration (poem thresholds)
- lightly-edited AI output: a human breaks the surface tells and adds typos but the semantic flow stays AI, so stylometry says human while GROQ says AI and the gate forces uncertain. the honest outcome, and a demo of why gating beats a flat average
- very short text (under ~50 words): both signals get unreliable, so it defaults to uncertain

## Architecture
Submission flow: raw text enters `POST /submit` with an optional `content_type`, passes the prompt-injection filter (which rejects text that reads as an instruction to the classifier), gets a genre from the classifier, then three signals score it (GROQ semantic, stylometric heuristics, and compression/predictability). The compression signal abstains on ordinary prose and only joins the vote when it detects real redundancy. The participating signals go through the weighted ensemble with a spread gate, the label generator turns the combined score into label text, the decision is written to the audit log, and the JSON response goes back to the caller (with a Verified Human badge if the creator holds a certificate). Appeal flow: `POST /appeal` looks up the content by id, sets its status to under_review, appends to the audit log, and returns a confirmation. Verification flow: `POST /verify` runs the same ensemble on a live writing sample and issues a certificate if it scores likely_human. Analytics: `GET /analytics` and `GET /dashboard` roll up the stored decisions.

```mermaid
---
config:
  layout: elk
---
flowchart TD
    caller[Caller]
    post["POST /submit<br/>(optional content_type)"]
    filter["Prompt-Injection Filter<br/>(rejects text that reads as an instruction to the classifier)"]
    classifier[Genre Classifier]
    groq[GROQ Semantic Signal]
    stylometric[Stylometric Heuristics Signal]
    compression["Compression/Predictability Signal<br/>(abstains on ordinary prose,<br/>joins when redundancy detected)"]
    ensemble["Weighted Ensemble<br/>with Spread Gate"]
    labelGen[Label Generator]
    auditLog[Audit Log]
    response["JSON Response<br/>(adds Verified Human badge<br/>if certificate present)"]

    caller -->|raw text| post
    post --> filter
    filter -->|passes| classifier
    classifier -->|genre| groq
    classifier --> stylometric
    classifier --> compression
    groq -->|score| ensemble
    stylometric -->|score| ensemble
    compression -->|conditional score| ensemble
    ensemble -->|combined score| labelGen
    labelGen -->|label text| auditLog
    auditLog --> response
    response -->|JSON| caller

    classDef input stroke:#38bdf8,fill:#f0f9ff
    classDef process stroke:#a78bfa,fill:#f5f3ff
    classDef decision stroke:#facc15,fill:#fefce8
    classDef output stroke:#4ade80,fill:#f0fdf4
    class caller input
    class post,filter,classifier,groq,stylometric,compression,ensemble,labelGen process
    class auditLog,response output
```

``` mermaid
---
config:
  layout: elk
---
flowchart TD
    %% Appeal Flow
    subgraph A["Appeal Flow — POST /appeal"]
        U["User submits POST /appeal (content_id)"] --> G1["API Gateway looks up content by id"]
        G1 --> S1["Content Service updates status → under_review"]
        S1 --> L1["Audit Log appends entry"]
        L1 --> U1["Return 200 OK (Appeal confirmed)"]
    end

    classDef appeal stroke:#818cf8,fill:#eef2ff
    class A,U,G1,S1,L1,U1 appeal

    %% Verification Flow
    subgraph V["Verification Flow — POST /verify"]
        W["Writer submits POST /verify (writing sample)"] --> G2["API Gateway evaluates sample via Ensemble Model"]
        G2 --> E["Ensemble Model returns score = likely_human / likely_ai"]
        E --> C["Certificate Service issues certificate if likely_human"]
        C --> W1["Return verification result (with certificate)"]
    end

    classDef verify stroke:#2dd4bf,fill:#f0fdfa
    class V,W,G2,E,C,W1 verify

    %% Analytics Flow
    subgraph N["Analytics — GET /analytics /dashboard"]
        M["Moderator sends GET /analytics"] --> G3["API Gateway queries Analytics DB (summary)"]
        G3 --> D1["Analytics DB returns aggregated results"]
        D1 --> M1["Return JSON metrics"]
        M1 --> M2["Moderator sends GET /dashboard"]
        M2 --> G4["API Gateway queries Analytics DB (dashboard data)"]
        G4 --> D2["Analytics DB returns visualization data"]
        D2 --> M3["Return dashboard view"]
    end

    classDef analytics stroke:#fb923c,fill:#fff7ed
    class N,M,G3,D1,M1,M2,G4,D2,M3 analytics
```

## AI Tools Plan
For each implementation milestone: which spec sections to hand the AI tool, what to ask it to generate, and how to verify the output before wiring it in.
- M3 (submission endpoint + first signal): provide the Detection signals section + the architecture diagram. ask for the Flask app skeleton with the `POST /submit` stub, the GROQ signal function, the audit-log writer, and a `GET /log` endpoint. verify the signal function standalone on a few inputs, then curl `/submit` and inspect the JSON.
- M4 (second signal + confidence scoring): provide Detection signals + Uncertainty representation + the diagram. ask for the stylometric signal function and the agreement-gated scoring logic. verify the 4 test inputs land in distinct bands, printing `llm_score` and `stylo_score` separately to catch a misbehaving signal.
- M5 (production layer): provide Transparency label design + Appeals workflow + the diagram. ask for the label-generation function, the `POST /appeal` endpoint, and Flask-Limiter setup. verify all 3 labels are reachable, an appeal flips status to under_review, and a 12-request loop returns 429s after the limit.

## Stretch Features

### Ensemble detection (3rd signal + weighted voting)
Adds a third, genuinely distinct signal and moves the pipeline from a 2-signal gate to a documented weighted ensemble.
- 3rd signal, compression/predictability: `zlib`-compress the text and take the ratio of compressed to raw size. More predictable/repetitive writing compresses smaller, which reads AI-like. It measures raw information redundancy, so it is distinct from both the semantic signal and the stylometric heuristics. Measurement showed ordinary AI and human prose compress almost identically (~0.65), so this is a one-directional cue: strong redundancy votes AI, but ordinary compressibility is not evidence of a human. On short text or ordinary prose it abstains and is left out of the ensemble rather than diluting the other signals.
- weighted ensemble: each signal reports P(AI), and the combined score is a weighted mean.
    - weights: llm 0.5, stylo 0.3, compression 0.2
    - rationale: GROQ is heaviest because semantics is the hardest property to fake, stylometry is a solid but gameable middle, compression is the noisiest cue so it gets the least say
- generalized agreement gate: if the spread (max P(AI) minus min P(AI) across the signals) is too wide, the signals disagree and the verdict is forced to uncertain. same intent as the old two-signal gap gate, extended to three.
- bands and display confidence are unchanged (AI >= 0.70, human <= 0.40, verdict-matched confidence).

### Analytics dashboard (HTML page + JSON API)
Aggregates submission data into a live dashboard served two ways: a JSON endpoint for programmatic access and a server-rendered HTML page for the browser.
- `GET /analytics` returns counts by attribution, genre, and content_type; appeal rate; average combined confidence; signal-agreement rate; and verified-creator submission count.
- `GET /dashboard` renders the same numbers as a plain HTML page via `render_template_string`, no JavaScript required.
- `get_analytics()` in `store.py` computes everything in a single database pass over the `content` and `audit_log` tables.

### Provenance certificate (live writing challenge)
A creator earns a "Verified Human" credential by completing a live writing challenge scored by the ensemble pipeline.
- `GET /verify/challenge` returns a random writing prompt and a `challenge_id`.
- `POST /verify` accepts `creator_id`, `challenge_id`, and the written `text`. The ensemble pipeline scores the passage; if it comes back `likely_human`, a `certificate_id` (uuid) is issued, the creator is marked verified in a new `creators` table, and the credential is returned. Otherwise a friendly failure message is returned.
- `/submit` response gains `creator_verified` (bool) and a `badge` field when the submitting creator holds a certificate. `creator_verified` is stored on the content row.
- `GET /creator/<creator_id>` returns credential status.
- Verification attempts are logged to `audit_log` as `event='verify'`.

### Multi-modal support (image descriptions)
Extends the pipeline to a second content type alongside plain text.
- `/submit` takes an optional `content_type`, either `text` (default) or `image_description` (an image caption or alt-text).
- the signals are made modality-aware: GROQ is told when the input is a caption so it judges natural flow appropriately, and the stylometric signal uses a caption-calibrated path with a lower minimum-word threshold, since captions are short by nature.
- `content_type` is stored on the content row and in the audit log, and echoed back in the response, so the modality is visible everywhere.
- schema note: the new `content_type` column is added through a small migration helper (PRAGMA table_info then ALTER TABLE ADD COLUMN) so the existing dev database is preserved rather than dropped.