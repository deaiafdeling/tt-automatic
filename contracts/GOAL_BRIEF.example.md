# GOAL BRIEF — overnight loop (27 Sep 19:55 → ≥12h)

User directive: continue Hermes's loop (change → bench → publish → search) until
Flash-Next is significantly faster; SRAM/L1 work included; research rewriting Python
parts in a lower-level language; improve prefill AND concurrency to acceptable levels.
Owner: pi (second TT operator). Hermes crons continue (bounty-watch, serve-restart).

## Contract

**Objective:** Raise serve quality-of-speed on all three axes — decode (fixed-cost
cuts + targeted L1 pins), prefill (367 → ≥700 tok/s), concurrency (≥2 concurrent chat
requests at ≥60% aggregate efficiency) — while keeping acceptance pins green.

**Constraints:**
- Never break known-good: rollback tags (`checkpoint-20260926-serve-good`,
  `checkpoint-20260927-arm2-win`), the published 69.3 record config
  (FUSED_OFF="" env), acceptance pins identical-token vs
  `analysis/acceptance_ref_wrapOFF_20260927T1912.json` (handoff arrays).
- Mesh windows only via the ladder (tt-mesh-window skill); serve back UP before any
  turn ends; background subagents NEVER touch devices.
- Commit every landed increment (tt-contrib + fork); never commit weights/profile.log.
- Publish only winners (localmaxxing protocol); losses recorded not posted.
- No architecture pivots without the user (T19 DFlash2 stays user-gated).
- exl3q-convert48 (PID 57024) owns CPU; do not kill, do not write payload/.

**Validate:** `bench_flashnext_chat.py 300` + `sweep_fused.py` after every serve
change; acceptance pins diff after every serve restart; static pytest suites for every
code change; `lmx_speedtest.py` dry-run then POST only on a canonical win.

**Checkpoints:** each landed step = git commit + KANBAN line (T22 prefill, T23
concurrency, T24 attribution, T25 draft-pin, T26 python-rewrite research).

**Stop when:** 12h elapse OR all three axes hit target OR a pause condition fires:
device unrecoverable after the reset ladder, acceptance pins break unfixably in-window,
or a decision needs the user (architecture, spend). Leave the serve UP either way.

## Working hypotheses (to verify, not assume)

- H1 (fixed-cost pass): pass wall ~60–65 ms is constant across 2.2–4.8 tok/pass
  (acceptance events) → decode is per-pass-cost-bound, not per-token/DRAM-BW-bound.
  Effective DRAM use ~6% of spec on the current bf8b traffic model. ⇒ traffic-only
  L1 pins ≈ 0 gain; pins pay only where DRAM *latency* sits on the per-pass critical
  path (draft steps, small linears, sparsity/index pages).
- H2 (prefill): 2.7 ms/tok at 32-row chunks ⇒ ~86 ms/chunk of which weights-BW is
  ~4–5 ms ⇒ prefill is ALSO fixed-cost/serialization-bound per chunk, not BW-bound.
  External datapoint: ~1200 tok/s prefill exists on this box class (Lottolabs TT
  entry, 2048-tok prompt). Their TTFT 1689 ms vs our 58 ms warm — different regime.
- H3 (concurrency): the serve serializes requests on one chain (queue_wait 0 today
  because single client). Options ranked: measure → document → interleave prefill of
  request 2 with decode of request 1 → T17 batched-verify lanes (big).
- H4 (python rewrite): #55553 measured per-op launch ≈ 0 in trace replay; our pass is
  a traced replay. Host cost per pass = accept bookkeeping + yields + ple refresh +
  sampler. Measure the mtp_step-internal host share; rewrite only what measures big.
  Candidates: the session loop (Cython/C++), sampler, detokenizer. vLLM/SGLang moved
  schedulers to Rust for ~µs-level gains at batch>1 — our batch=1 traced loop may not
  have the same exposure.
