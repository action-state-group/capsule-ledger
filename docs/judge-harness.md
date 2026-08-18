# The judge harness

**Status: Scorer shell + prompt
digest-pinning + judgment capsules + MANUAL spot-check adjudication.

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

## The three record types

| Event | Built by | Shape |
|---|---|---|
| `judge_judgment` | `judge.build_judgment_capsule` | model id, prompt id + `prompt_digest`, evidence range (session id + turn capsule ids, + session digest once closed), label (from the prompt's closed `label_set`), `confidence_micros` (integer, 0–1,000,000 — floats are not digest-safe), optional `target_speaker_role` |
| `judge_adjudication` | `judge.build_adjudication_capsule` | a real `disposition` block (`human_disposed=True`, `approver="human"`), chained to the judgment it disposes of |
| `judge_prompt_activated` | `judge.build_judge_prompt_activation_capsule` | a judge prompt/label-set change — same `epoch_opens` chain-of-epochs shape as `policy/activation.py`'s manifest activation |

Every judgment answers "who judged the judge, with what prompt, on what
evidence" directly from the capsule — no side lookup. Evidence content is
never on a capsule (H2 invariant): only the evidence *range* (turn capsule
ids + session digest) is recorded; a `Scorer` reads the actual text wherever
it already lives (the caller's own payload store).

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
(relation `confirms`) and carries its `session_digest`. `--scorer static`
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
