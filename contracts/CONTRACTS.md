# The contracts — where the actual magic lives

The scripts are 400 lines of bash. The system works because of two documents and one
ledger. This file explains each so you can write your own.

## 1. The goal brief (human-authored, frozen during the run)

Read `contracts/GOAL_BRIEF.example.md`. Structure that has survived real overnight runs:

- **Objective** — one paragraph, measurable ("raise decode/prefill/concurrency while
  keeping acceptance pins green").
- **Constraints** — the never-break-known-good list: rollback tags, published configs,
  reference outputs. This is the ONLY guard the e/acc auto-answer respects.
- **Validate** — the exact command to run after every change (static test suite,
  benchmark script, pin diff). Mechanical, not vibes.
- **Stop when** — the 12h window, targets hit, or named pause conditions.
- **Ownership notes** — anything the loop must not touch (long-running conversions,
  other jobs on the box).

The agent's creativity happens *inside* this document. If the brief is vague, the
night is wasted — write it like a work order for a contractor you'll never speak to.

## 2. The disk handoff (agent-authored every episode)

End-of-turn contract, enforced by the episode prompt:

```
turn-<N>: <what landed> — NEXT: <the highest-value next step>
```

Appended to the board (KANBAN-style file) AND committed. Episodes are stateless; the
board is the brain. A cold episode orients in ~2 minutes: read the brief, tail the
board, `git log`, preflight the environment. The handoff line is what makes death
cheap — an episode that dies mid-work leaves a trail, and the next one resumes from
the last landed increment, not from zero.

## 3. The experiment ledger

`experiments/experiments.example.tsv`, pattern credit: bro4all/autoresearch-tenstorrent
(the Tenstorrent port of karpathy/autoresearch).

```
date	area	metric	value	unit	status	run_id	description
```

Rules that make it load-bearing:

- **Every benchmarked A/B gets a row.** keep, discard, crash — losses are logged, not
  hidden. Only `published` rows cite a public run id.
- **Never redefine a metric.** `tok_s` means the same thing in every row, forever.
- **Never compare across profiles.** Same config, same device path, or the row says
  `reference` (not comparable to serve numbers).
- The **driver counts ledger-file growth as productive work** — this is what makes
  benchmark-only episodes survive the judge.

Why a TSV and not a wiki: the driver's judge reads it mechanically (md5 delta), you
can `git log -p` it, and it diffs cleanly in PRs. Prose lies by omission; a row
per experiment doesn't.

## The agent prompt (episode-launcher.sh)

Each episode gets one prompt with four parts:

1. **Orientation** (read-before-act): goal brief → board tail → git log → environment
   preflight (what must be up, what must be left alone).
2. **Ledger rule**: every A/B → row; never redefine metrics.
3. **One focused unit of work**: implement, validate with the narrowest suite, bench if
   serve-affecting, commit + board line.
4. **Exit vocabulary**: `USER_DECISION_NEEDED: <question>` to escalate a decision to the
   human (auto-answered per policy), `OVERNIGHT_WINDOW_COMPLETE` to end the night cleanly.

That last part is the human/machine interface: the agent never blocks waiting for a
human, and the human never gets a 6 a.m. surprise decision they didn't authorize.
