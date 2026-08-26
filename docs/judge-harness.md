# The judge harness

**Status: Scorer shell + prompt
digest-pinning + full-pinned judgment capsules + MANUAL spot-check
adjudication + judge drift check + calibration harness seam.

The judge is a generic model-assisted recorded-claims engine: it reads
evidence (a conversation session's turns, per the [conversation-capsule
profile](../capsule_ledger/conversation/)), scores it against a digest-pinned
prompt, and appends a signed `judge_judgment` capsule — never a gate
decision. **The judge is never in the enforcement path** — the
`capsule_ledger.judge` package has no import of `guards.engine`/`GuardEngine`
anywhere in it (enforced by a structural test, `tests/test_judge_harness.py`),
not just documented as a rule.

## What it does not do

This harness does not implement scoring itself. Rubric-based LLM evaluation
is a mature, crowded OSS space (DeepEval, Phoenix, promptfoo, Ragas, ...) —
the harness's job is everything those frameworks don't do: pinning exactly
which prompt+label-set produced a claim, recording the evidence range as a
verifiable capsule, and chaining a human's spot-check disposition to it.

## The four record types

| Event | Built by | Shape |
|---|---|---|
| `judge_judgment` | `judge.build_judgment_capsule` | model id, prompt id + `prompt_digest`, evidence range (session id + turn capsule ids, + session digest once closed), label (from the prompt's closed `label_set`), `confidence_micros` (integer, 0–1,000,000 — floats are not digest-safe), optional `target_speaker_role`, and the full **judge pin** (below) |
| `judge_adjudication` | `judge.build_adjudication_capsule` | a real `disposition` block (`human_disposed=True`, `approver="human"`), chained to the judgment it disposes of |
| `judge_prompt_activated` | `judge.build_judge_prompt_activation_capsule` | a judge prompt/label-set change — same `epoch_opens` chain-of-epochs shape as `policy/activation.py`'s manifest activation |
| `judge_drift_check` | `judge.build_judge_drift_check_capsule` | a pinned judge re-run over its own cited evidence, sealed match-or-delta — chained `confirms` to the judgment it checks |

Every judgment answers "who judged the judge, with what prompt, on what
evidence" directly from the capsule — no side lookup. Evidence content is
never on a capsule (H2 invariant): only the evidence *range* (turn capsule
ids + session digest) is recorded; a `Scorer` reads the actual text wherever
it already lives (the caller's own payload store).

## The judge pin

A `judge_judgment` capsule's `detail.judge_pin` block is the full pin —
sealed once, never retrofittable, so it carries everything a later drift
check or calibration pass needs:

| Field | Meaning |
|---|---|
| `judge_pin_digest` | the pin's own identity — a digest over exactly the reproducible call shape (model id, model version, sampling params, prompt digest). Two judgments with the same digest are, by definition, the same pinned judge. |
| `model_id` / `model_version` | the model identity (`model_version` optional — a `Scorer` that can't report a version still produces a valid, just less specific, pin) |
| `sampling_params` | the call's sampling shape, digest-safe values only (int/str/bool — a float param like temperature must be pre-scaled by the caller, e.g. `{"temperature_micros": 700_000}`, same discipline `confidence` → `confidence_micros` uses) |
| `prompt_digest` | the digest-pinned prompt (also present at `detail.prompt_digest`) |
| `adjudication_sampling_rate_micros` | the harness's own declared policy — what fraction of judgments get a human spot-check (optional) |
| `measured_agreement_rate_micros` | the point-in-time measured agreement rate for this exact pin (`judge.compute_judge_calibration_stats`, re-derivable from the ledger — omitted, never a fabricated 0%, when this pin has no adjudicated judgments yet) |
| `external_proof` | an optional typed reference (`judge.ExternalProofRef`) to an external cryptographic proof artifact (e.g. zkML) backing the model computation — never the artifact itself, only a pointer. Absent today; the slot exists so attaching one later needs no format change. |

`judge_pin_digest`, `model_id`, and `prompt_digest` are always present;
everything else is omitted (not `null`) when not given.

## The judge drift check

`JudgeHarness.check_drift(judgment=..., evidence=...)` re-runs the harness's
own scorer/prompt over the SAME evidence a sealed judgment already cited,
and always seals a `judge_drift_check` capsule — match or delta, never a
silent disagreement. `drifted` is true when either the re-run's own
`judge_pin_digest` differs from the original (this isn't even the same judge
anymore — e.g. a silent model upgrade) or the pin matches but the label
differs (the same judge disagreed with itself). Both the original and
re-run label are recorded on the sealed capsule either way, so "what
drifted" is answerable from the ledger alone, not just a boolean.

Checking drift against a judgment sealed before this pin landed raises
`JUDGE_PIN_MISSING` — there is no reproducible identity to check against.

## The calibration harness seam

`judge.compute_judge_calibration_stats(ledger, judge_pin_digest)` folds a
ledger's own judgment/adjudication/drift-check history into plain measured
stats (`JudgeCalibrationStats`: judgment/adjudication/drift counts,
`agreement_rate`, `drift_rate`) for one judge pin — every field re-derivable
by re-scanning the ledger, never a stored/asserted value.
`JudgeHarness.run()` calls this automatically to populate
`measured_agreement_rate_micros` on each new judgment.

This module computes only plain descriptive stats — no calibration
*weighting* scheme lives here or anywhere in this repo. It is the consumer
seam the flagship record-grounding benchmark (τ²-bench, landing with the
public demo) will feed once it exists; until then it operates over whatever
judgments/adjudications a ledger already has.

## The `Scorer` seam

```python
class Scorer(Protocol):
    def score(self, *, evidence: JudgeEvidence, prompt: JudgePromptDefinition) -> ScoreResult: ...
```

- `judge.scorers.DeepEvalScorer` — the default (BYOM). A thin wrapper over
  `deepeval.metrics.GEval`: one GEval instance per candidate label ("does the
  evidence support this label?"), the highest-scoring label wins. Optional
  dependency (`pip install capsule-ledger[judge]`) — imported lazily, so the
  rest of the harness has no hard dependency on it.
- `judge.scorers.StaticScorer` — a deterministic, no-network reference
  implementation. Used by this repo's own tests/demos, and as proof the
  `Scorer` seam is genuinely swappable.

## Adjudication honesty

`build_adjudication_capsule` requires `judgment` to actually be a
`judge_judgment` capsule, and requires `label == judgment's own label`
whenever `agrees_with_judge=True` — claiming agreement while recording a
different label is a contradiction the builder refuses to seal, not a
caller convention.

## CLI

```
capsule judge run --ledger <dir> --prompt <prompt.yaml> --session <id> \
    --evidence-text "..." [--speaker-role user|assistant|human-agent] \
    [--scorer deepeval|static] [--model <id>]

capsule judge adjudicate --ledger <dir> --judgment <capsule_id> \
    --label <label> (--agree | --override) [--rationale "..."]
```

`judge run` auto-discovers the session's turn capsules and, when the session
has already closed, auto-chains the judgment to the session-close capsule
(relation `confirms`, provisional — the judge observes a different stream
than the session it judges; see [confirm-connector-interface.md's chain
relation note](confirm-connector-interface.md#chain-relation-under-revision)
for why this cross-stream relation choice is under revision) and carries its
`session_digest`. `--scorer static`
needs `--static-label`/`--static-confidence` and makes no model call — useful
for scripted demos; `--scorer deepeval` (the default) makes a real model call
and needs whatever DeepEval's configured model backend expects (e.g.
`OPENAI_API_KEY`).

## Prompt definition YAML

```yaml
prompt_id: conversation.agreement_reached/1.0.0
label_set: [agreement_reached, no_agreement]
instructions: Did the conversation reach agreement on a remedial action?
```

`prompt_digest()` is a SHA-256 over the JCS-canonical form (same mechanism
`folds/definition.py`'s `definition_digest()` uses) — a one-character rubric
edit changes the digest, so a drifted prompt can't silently keep producing
judgments that claim the old, audited wording.
