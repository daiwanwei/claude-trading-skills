# Daily Trading Routine

Execution is always local: the routine is a Python script in this repository.
The scheduler is only a trigger. Claude Code is the supported trigger; the
Codex Scheduled Task setup is kept below as an alternative. Pick one — running
both would double the API spend, though the PID lock keeps a concurrent second
invocation safe (`SKIPPED_OVERLAP`).

This routine automates the machine-safe portion of `market-regime-daily` and,
only when both risk gates allow it, the screening portion of
`swing-opportunity-daily`. It stops at the weekly-chart review gate. It never
places orders, calculates position sizes, writes trade plans, or creates active
theses.

## One-time setup

Run these commands from the repository root:

```bash
cp config/daily-trading-routine.example.toml \
  config/daily-trading-routine.local.toml
```

Edit the local file and uncomment `account_size` with a real positive account
value. The local file is ignored by Git. Do not put the value in the example,
the Scheduled Task prompt, or a committed file.

Confirm that the thesis state directory in the TOML matches the repository. The
default is `state/theses`. An empty directory is valid and produces an
empty-state circuit-breaker evaluation.

The FMP-backed screeners read `FMP_API_KEY` from the environment. This project
loads it through `.envrc`; allow the file with `direnv allow` if needed. Check
presence without printing the secret:

```bash
direnv exec . sh -c 'test -n "$FMP_API_KEY" && echo "FMP_API_KEY is set"'
```

## Validate before using network data

The dry run validates all TOML values and prints the planned child commands
with the account value redacted. It does not run a skill or consume API quota.

```bash
direnv exec . .venv/bin/python scripts/run_daily_trading_routine.py --dry-run
```

Run the live workflow manually once before scheduling it:

```bash
direnv exec . .venv/bin/python scripts/run_daily_trading_routine.py
```

Use `--as-of YYYY-MM-DD` for a deterministic freshness check and `--verbose`
to print the final redacted summary. Required-skill failures return a non-zero
exit code. Risk-gate stops, stale-data stops, and overlapping invocations are
safe outcomes and return zero.

## What runs

1. Market Breadth, Uptrend Analyzer, and Market Top Detector run concurrently.
   Macro Regime Detector joins them when `enable_macro_regime` is true.
2. Exposure Coach runs only if the three required artifacts are valid and
   fresh. When Macro Regime Detector produced a usable artifact, the runner
   also passes it as `--regime`. That input carries the largest weight in
   Exposure Coach and is one of its three critical inputs, so supplying it
   removes the reduced-confidence penalty the posture would otherwise carry.
   Macro Regime Detector stays optional either way: it is excluded from the
   freshness gate, and a failure becomes a warning instead of a stop. When it
   is disabled or failed, Exposure Coach runs without `--regime` and lowers
   its own confidence, which is the intended degraded path.

   Note that a supplied regime does not simply raise the ceiling. A
   `Broadening` regime scores high and lifts it, while a `Contraction` regime
   scores low and pulls it sharply down. The point is that the posture is
   computed from a complete input set, not that the number moves in a
   particular direction.
3. Drawdown Circuit Breaker runs only when exposure says
   `NEW_ENTRY_ALLOWED`; only `TRADING_ALLOWED` advances.
4. VCP runs as the required screener. Theme Detector runs by default.
5. Momentum Burst, Exhaustion Hammer, and CANSLIM run only when enabled in the
   local TOML. A failure in one of these optional screeners becomes a warning.
6. The runner writes a manual-review queue and stops before human chart review.

Each invocation writes an isolated UTC-stamped directory under
`reports/daily-trading-routine/`. `summary.json` is the stable machine-readable
artifact and `summary.md` is the operator view. The child circuit-breaker
artifact is scrubbed of `account_size` before the run is summarized.

Common final statuses are:

| Status | Meaning |
| --- | --- |
| `COMPLETED_REVIEW_REQUIRED` | Both gates passed; inspect the queue and weekly charts manually. |
| `STOPPED_BY_EXPOSURE_GATE` | Market posture does not allow new entries. |
| `STOPPED_STALE_DATA` | A required market artifact is missing a usable recent source date. |
| `STOPPED_BY_CIRCUIT_BREAKER` | Account controls require cooldown or halt. |
| `FAILED_REQUIRED_SKILL` | A required command, artifact, or schema failed. |
| `SKIPPED_OVERLAP` | Another invocation already owns the routine lock. |

## Create the Claude Code scheduled task

This is the supported trigger. The task is stored by the app under
`~/.claude/scheduled-tasks/daily-trading-routine/SKILL.md`, so no cron file or
automation metadata belongs in this repository.

- Cron `30 6 * * 2-6` — Tuesday through Saturday at 06:30, evaluated in the
  machine's local timezone. This is the morning after each US session closes.
- The machine must be awake and Claude Code must be open when the task is due.
  A task that comes due while the app is closed runs on next launch.
- Each run starts with no memory of the session that created it, so the stored
  prompt is self-contained.

Recreate or edit it with the task prompt below:

Substitute your own absolute checkout path on the `cd` line — the stored task
has no working directory from this session. That prompt lives outside the
repository, so a machine-specific path is fine there but must never be
committed here.

```text
Run the repository's fail-closed daily trading routine. First cd to the
checkout, then run:

direnv exec . .venv/bin/python scripts/run_daily_trading_routine.py

Then read the generated summary.json and report the final status, exposure
decision, circuit-breaker decision, macro regime label if present, warnings,
and manual-review candidates. Do not print secrets or account size. Do not
place orders, calculate position sizes, write trade plans, or create or
activate theses. If the manual-review queue is non-empty, ask me to review the
weekly charts before any further trade decision. If the command fails, report
the error and the latest summary path.
```

## Alternative: Codex Scheduled Task

Create a standalone Scheduled Task in the Codex app using this repository as a
local project. Use this schedule:

- Tuesday through Saturday at 06:30 Asia/Taipei
- Local execution, not a worktree, so ignored configuration, `.envrc`, thesis
  state, and prior reports are available
- Notifications enabled for completed runs and failures

Use this English task prompt:

```text
Run the repository's fail-closed daily trading routine with:
direnv exec . .venv/bin/python scripts/run_daily_trading_routine.py

Then read the generated summary.json and report the final status, exposure
decision, circuit-breaker decision, warnings, and manual-review candidates. Do
not print secrets or account size. Do not place orders, calculate position
sizes, write trade plans, or create or activate theses. If the manual-review
queue is non-empty, ask me to review the weekly charts before any further trade
decision. If the command fails, report the error and the latest summary path.
```

Codex Scheduled Tasks are stored by the app, so no cron or automation metadata
file belongs in this repository. The machine must be awake and the Codex app
must be running when a local task is due.

## Troubleshooting

- Missing local TOML: copy the example, then set a real positive
  `account_size`. The runner intentionally refuses the commented placeholder.
- Missing FMP key: run the presence check above and `direnv allow`. Do not echo
  or paste the key into logs.
- Stale data: inspect the three market child JSON artifacts and their source
  dates. The runner will not bypass the configured freshness limit.
- Network or sandbox denial: grant only the Scheduled Task's required outbound
  data access and repository report writes, then rerun. Do not broaden it to
  broker or order permissions.
- Closed exposure or circuit gate: this is a normal stop. Read the decisions in
  the summary; do not force the screener stage.
- Timeout: inspect the named child directory and raise only that workload's
  value under `[timeouts]` if the command is healthy but consistently slow.
- Overlap: wait for the active PID to finish. A genuinely stale lock is replaced
  automatically on the next invocation.
- Empty thesis state: valid for a new journal. Corrupt YAML is fail-closed;
  repair the named thesis record before rerunning.
- Child failure: use the artifact paths and warning in `summary.json`. A missing
  or malformed required JSON is treated as a failure, never as permission.

## Tests

The isolated runner suite does not use the network:

```bash
.venv/bin/python -m pytest scripts/tests/test_daily_trading_routine.py -q
```
