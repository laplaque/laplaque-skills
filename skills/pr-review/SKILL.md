---
name: pr-review
description: >
  Review GitHub and GitLab pull/merge requests with inline comments posted
  directly to the PR/MR. Use this skill whenever the user asks to review a PR,
  review a pull request, review a merge request, check a PR/MR, look at a PR/MR,
  give feedback on a PR/MR, or provides a GitHub/GitLab PR/MR URL and wants code
  review. Also trigger when the user mentions reviewing changes, checking a diff,
  or wants CI/pipeline failures diagnosed on a PR/MR. This skill handles any
  programming language — Go, Python, TypeScript, Rust, Java, etc. It fetches the
  diff, analyzes code quality, checks for bugs and security issues, flags PII in
  code, enforces test coverage thresholds, cross-references against specs if
  provided, diagnoses CI failures, and posts structured inline review comments
  with severity ratings directly on the PR/MR.
---

# PR Review Skill

You are a code reviewer. Your job is to fetch a pull request (GitHub) or merge request (GitLab) diff, analyze it thoroughly, and post a structured review with inline comments on the exact lines where issues exist.

## Prerequisites

This skill requires either `gh` (GitHub CLI) or `glab` (GitLab CLI), authenticated via OAuth. See `references/cli-setup.md` for detailed setup instructions.

Before starting any review, run the verification step described in Step 0 below. If verification fails, stop and explain to the user exactly what is missing and how to fix it. Do not attempt workarounds like raw tokens or Python HTTP fallbacks — the CLI must be properly set up via OAuth.

## Workflow

### Step 0: Verify CLI setup and determine platform

Determine whether this is a GitHub or GitLab review:
- If the URL contains `github.com` → use `gh`
- If the URL contains `gitlab.com` or a known GitLab instance → use `glab`
- If ambiguous (just a repo name or PR number with no URL), **ask the user** which platform before proceeding

Then verify the CLI is ready:

**For GitHub (`gh`):**
```
gh auth status
```
Check that:
- Authentication method is **oauth_token** (not a personal access token)
- Token scopes include `repo` and `workflow`
- Active account is shown

If any check fails, stop and tell the user:
- What is missing (e.g., "gh is authenticated but missing the `workflow` scope")
- The exact command to fix it (e.g., `gh auth refresh -s repo,workflow`)
- Point them to `references/gh-setup.md` for full setup instructions

**For GitLab (`glab`):**
```
glab auth status
```
Check that:
- Authentication is active
- The token has `api` scope (covers read/write on MRs, pipelines, comments)

If verification fails, stop and explain what is missing. Do not proceed with the review.

### Step 1: Gather context

Collect these inputs:
- **PR/MR URL or number + repo** — required
- **Spec or originating prompt** — optional; if provided, cross-check implementation completeness
- **Review guidelines** — use this priority order:
  1. User's stated review preferences or guidelines (from conversation or user_preferences)
  2. Project-level guidelines (if referenced or known)
  3. Repo-level config files (`.golangci.yml`, `pyproject.toml`, `tsconfig.json`, `.eslintrc`, `Cargo.toml`, `.gitlab-ci.yml`, etc.) — fetch from the repo if available

### Step 2: Fetch PR/MR metadata

**GitHub:**
```
gh pr view {number} --repo {owner}/{repo} --json headRefOid,files,title,body
gh pr diff {number} --repo {owner}/{repo}
```

**GitLab:**
```
glab mr view {number} --repo {owner}/{repo}
glab mr diff {number} --repo {owner}/{repo}
```

From the metadata, extract:
- Commit SHA — needed for posting comments
- File list with additions/deletions — determines review mode
- PR/MR title and body — understand intent

### Step 2.5: Detect promotion merge

Promotion merges (dev → test, test → main, staging → prod, etc.) bundle commits that were already reviewed and approved in prior feature MRs. Re-running Step 4's full code-level analysis on those commits re-litigates approved work. This step splits the review path: chain-of-custody audit for promotion merges, normal review for everything else.

**Detection — BOTH checks must pass (AND, strict).**

1. **API-based — branch protection on source AND target.**
   - **GitHub:** `gh api repos/{owner}/{repo}/branches/{source}/protection` and `gh api repos/{owner}/{repo}/branches/{target}/protection`. HTTP 200 = protected; HTTP 404 = not protected.
   - **GitLab:** `glab api projects/{id}/protected_branches/{source}` and `glab api projects/{id}/protected_branches/{target}`. HTTP 200 = protected; HTTP 404 = not protected.
   - Both branches MUST return 200 for this check to pass. If either is unprotected, this check fails.

2. **Pattern-based — source→target matches a known promotion pattern** (exact branch names, case-insensitive; no globs — GitFlow `release/*` and `hotfix/*` deliberately fall through to normal review):
   - `dev → test`, `dev → staging`, `develop → main`, `develop → master`
   - `test → main`, `test → master`, `test → prod`, `test → production`, `test → release`
   - `staging → main`, `staging → master`, `staging → prod`, `staging → production`
   - `uat → prod`, `qa → prod`, `release → main`, `integration → main`
   - `next → main`, `preprod → prod`

**Decision tree:**

```
both branches protected AND names match a promotion pattern?
├── YES → chain-audit mode (proceed in this step; Step 3/Step 4 run for uncovered commits only)
└── NO  → proceed normally to Step 3
```

Record the detection result in the review evidence block:
`Promotion merge: yes (source-protected: PASS, target-protected: PASS, pattern: dev→test) | no`

If the API check fails because the CLI token lacks permission to read branch protection, treat the API check as INDETERMINATE — do **not** auto-fail to chain-audit mode (could mis-skip Step 4 on a feature MR), and do **not** auto-pass to normal mode (could over-review a promotion). Stop, flag the missing permission to the user, and let them decide which mode applies.

**Chain-audit mode**

Goal: verify each commit in this promotion was reviewed and approved in a prior MR. Skip code-level findings on covered commits.

**Upstream-chain definition.** For a promotion `X → Y`, the upstream chain of `X` is `{X}` plus the transitive set of branches reachable by walking *backwards* through the pattern list: every `B` such that `B → X` appears in the pattern list, plus everything upstream of those. Examples:
- `dev → test`: upstream chain of `dev` = `{dev}`.
- `test → main`: upstream chain of `test` = `{test, dev}` (because `dev → test` is in the pattern list).
- `staging → prod`: upstream chain of `staging` = `{staging}` (no in-list feeder for `staging`).
- `develop → main`: upstream chain of `develop` = `{develop}`.

A prior MR is **in-chain** if its target branch is in this set. Feature branches (anything not in the pattern list) are not "upstream" themselves — what matters is the target branch the prior MR merged into.

1. **Enumerate commits in the promotion MR.**
   - **GitHub:** `gh pr view {number} --json commits --jq '.commits[].oid'`
   - **GitLab:** `glab api projects/{id}/merge_requests/{iid}/commits --jq '.[].id'`

   Exclude merge commits introduced by the promotion itself (parent count > 1 on the promotion head); audit only the underlying feature commits.

2. **For each commit SHA, find the prior MR that introduced it.**
   - **GitHub:** `gh api repos/{owner}/{repo}/commits/{sha}/pulls --jq '.[] | {number, state, base: .base.ref, merged_at}'` lists every PR containing the commit. The same commit may appear in several PRs (the original feature→dev PR plus every subsequent promotion PR); the **earliest-merged** in-chain PR is the original approval. Approval check: `gh api repos/{owner}/{repo}/pulls/{n}/reviews --jq '.[] | select(.state=="APPROVED")'`.
   - **GitLab:** `glab api projects/{id}/repository/commits/{sha}/merge_requests --jq '.[] | {iid, state, target_branch, merged_at}'`. Same earliest-merged-in-chain logic. Approval check: `glab api projects/{id}/merge_requests/{iid}/approvals --jq '.approved_by'`.

3. **Cherry-pick detection (run before classifying as bypass).** If the commit message contains a `cherry picked from commit <ORIGINAL_SHA>` trailer (added by `git cherry-pick -x`), look up `ORIGINAL_SHA` via the same prior-MR API. If `ORIGINAL_SHA` traces to an approved in-chain prior MR, treat the cherry-pick as **COVERED** (record both SHAs in the table notes). If the footer is absent, present but the original SHA traces to nothing, or the original's prior MR was unapproved/out-of-chain, fall through to the bypass/unapproved/wrong-target classifications below. Multiple trailers (chained cherry-picks) — walk back to the earliest traceable SHA.

4. **Classify each commit:**
   - **COVERED** — found directly in a prior merged MR whose target is in the upstream chain, with at least one recorded approval; OR resolved via cherry-pick footer to such an MR.
   - **UNCOVERED (bypass)** — no prior MR found, and no cherry-pick footer (or footer leads nowhere). Possible causes: direct push to source branch, force-push artifact, undocumented cherry-pick. Flag as **HIGH** minimum; **CRITICAL** if the diff touches an auth, security, validation, or PII path.
   - **UNCOVERED (unapproved)** — prior MR exists (directly or via cherry-pick footer) but has no approval recorded. Flag as **HIGH** — merging unapproved code into a protected branch violates branch-protection intent.
   - **UNCOVERED (wrong-target)** — prior MR merged but its target branch is outside the upstream chain (e.g., a commit on `test` whose only prior MR targeted `release`, skipping `dev`). Flag as **MEDIUM** — sequencing violation.

5. **Emit the chain-of-custody table in the review body** (one row per commit, mandatory output):

   | Commit | Status | Prior MR | Approvers | Notes |
   |--------|--------|----------|-----------|-------|
   | `abc1234` | COVERED | #142 | @alice, @bob | feat/foo → dev |
   | `def5678` | COVERED (cherry-pick) | #138 (orig `1122aab`) | @carol | cherry-pick of #138 |
   | `9abcde0` | UNCOVERED (bypass) | — | — | direct push detected |
   | `5678fed` | UNCOVERED (unapproved) | #155 | (none) | prior MR merged with 0 approvals |

6. **Run Step 4 ONLY on uncovered commits.** Covered commits (including approved cherry-picks) skip code-level analysis entirely — correctness, architecture, test coverage, comment rot, PII, hacks-and-workarounds were all scored in the prior MR and their findings live in that MR's record. Do not re-litigate.

7. **Integration risk pass (only when ≥ 2 covered feature branches touch overlapping files).** Compute the file set per prior MR (`gh pr view {n} --json files` / `glab api projects/{id}/merge_requests/{iid}/changes`) and detect overlaps across the covered set. If two independently-reviewed feature branches touched the same file but were never integration-tested together, flag as **MEDIUM** with a "no joint integration test" finding. Overlap-free → no finding.

8. **Process compliance for the promotion MR itself.**
   - Promotion MR template gates: if the project has a separate `PROMOTION_MR_TEMPLATE.md` or a promotion-tagged section in the standard template, score per Step 3.7's gate-enumeration procedure, scoped to the promotion template (not the feature-MR template).
   - CI pipeline on the promotion head SHA per Step 6.
   - Approval / reviewer requirements for the promotion (which may differ from feature-MR requirements — e.g., release-manager sign-off, security-team approval).

**Adaptation of downstream steps for chain-audit mode**

- **Step 3 (Choose review mode):** does not apply to covered commits. For uncovered commits, count lines across uncovered-only and pick mode accordingly.
- **Step 3.5 (Pre-findings gate):** Q1 reframes from *"What specific problem does this MR solve?"* to *"Is this promotion properly sequenced (correct source/target direction, no skipped environments, source branch HEAD reachable from target's expected upstream)?"*. Q2–Q4 apply unchanged.
- **Step 3.7 (Gate enumeration):** still applies; scope to the promotion MR's own template, which may carry different requirements (e.g., *"all commits passed test environment"* rather than *"unit tests cover 90% on this diff"*). Feature-MR coverage gates do not re-apply to covered commits — those were scored in the prior MR.
- **Step 4 (Analyze the code):** runs ONLY on uncovered commits. Covered commits are out of scope for code findings.
- **Step 8 (verdict):** unchanged. Highest finding severity — from process violations (HIGH/CRITICAL on bypass/unapproved), integration risk (MEDIUM), or uncovered-commit code findings — drives the verdict per the existing table.

### Step 3: Choose review mode (adaptive)

Count total changed lines across all files.

**Quick mode (under 500 changed lines):**
Read the diff in a single pass. Analyze sequentially. This keeps things fast for small PRs.

**Deep mode (500+ changed lines):**
Split the diff by concern area and dispatch parallel agents:
- **Core logic** — business logic files, main implementations
- **Tests** — test files, benchmarks
- **Config and docs** — configuration, documentation, CI files
- **Peripheral modules** — utilities, helpers, pack/plugin files

Each agent reads its portion of the diff and reports:
- Summary of what the code does
- Issues found with severity
- Missing test coverage
- Security concerns (including PII)

The user can override the mode: "do a deep review" forces deep mode on small PRs; "quick review" forces quick mode on large ones.

### Step 3.5: Pre-findings gate (MANDATORY before analysis)

Answer these four questions before producing ANY finding. If you cannot answer all four, you haven't analyzed deeply enough — go back.

1. **What specific problem does this MR solve?** If unclear from MR body → immediate blocking finding.
2. **Is the pipeline green at the exact MR head SHA?** Verify SHA match between `glab mr view` and `glab ci status`. Different SHA = you checked the wrong pipeline.
3. **Has the author self-verified?** Template boxes checked, description filled, test plan completed. Every unchecked box is a separate finding.
4. **Does the approach make functional sense for the stated problem?** Would this change actually solve the problem in the environments where it runs (CI, prod)? If the mechanism can't trigger where it matters, that's a finding.

### Step 3.6: Re-review freshness gate (MANDATORY)

This step is required for any re-review or whenever new commits may exist.

1. Refresh baseline immediately before analysis:
  1. fetch current MR head SHA
  2. fetch MR head pipeline ID and status
  3. fetch current diff
2. Define review baseline tuple as:
  1. baseline_head_sha
  2. baseline_pipeline_id
3. Perform analysis only against baseline_head_sha.
4. Immediately before posting verdict, refresh MR head SHA again.
5. If refreshed head SHA differs from baseline_head_sha:
  1. abort posting
  2. mark analysis stale
  3. restart from Step 3.6 with the new head
6. Evidence block is mandatory in every posted review:
  1. Head SHA
  2. Head pipeline ID
  3. Head pipeline status
  4. Checked at (UTC timestamp)
7. **Re-walk Step 3.7 (Gate enumeration) in full on every re-review round.** Never assume previously-passing gates still pass at a new head SHA; never confine re-review to only the previously-failing gates. If the author addressed feedback via PR-body edit (no new commits), body-dependent gates must be re-scored against the updated body. A re-review takes comparable time to the original audit — fast turnaround is a signal of rubber-stamping, not of efficiency.
8. **Re-review finding ledger (forced output).** In the re-review body, maintain a row-per-prior-finding table. Every finding from any prior round carries forward with its original severity and is re-scored against the current head. Do not omit a row because "it was clearly fixed" — the table is the audit trail.

   | Finding | R-N severity | Artifact offered                   | Artifact valid? | R-current severity |
   |---------|--------------|------------------------------------|-----------------|--------------------|
   | C1      | CRITICAL     | code diff <file>:<line> (verified) | YES             | RESOLVED           |
   | M2      | MEDIUM       | "deferred to phase-N" thread reply | NO              | MEDIUM (stays)     |

   The "Artifact valid?" column is scored against the severity downgrade gate (Step 8). A row that reads NO cannot feed an APPROVE verdict — either the artifact is produced (re-score later) or the finding's severity stays at its prior classification and feeds the verdict table.

   The ledger lives in the re-review body alongside the Quality gates audit table (Step 3.7), visible to the author and to future readers — not in a scratch.

Do not approve, request changes, or comment without a fresh baseline and final pre-post SHA match.

### Step 3.7: Gate enumeration (MANDATORY before findings)

The project's quality gates are the binding merge contract. Treat them as text to parse and score per-clause, not as a checkbox.

1. **Identify the gate-defining document.** This is the project's authoritative source of merge requirements. It may be:
   - `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, or another model-instructions file at the repo root
   - `CONTRIBUTING.md` or `docs/CONTRIBUTING.md`
   - A `.github/PULL_REQUEST_TEMPLATE.md` (or per-type variants under `.github/PULL_REQUEST_TEMPLATE/`)
   - A docs file titled "Quality Gates", "Merge Requirements", "Definition of Done", or "PR Checklist"

   Search the repo root for these by name; grep for section headings ("Quality Gates", "Definition of Done", "Merge Requirements", etc.) if none are obvious. If multiple candidates exist, prefer the most-recently-modified one. Record which document was used in the review evidence block. If no such document exists, fall back to the user's stated review guidelines (Step 1 priority order) and note that explicitly.

2. **Copy each gate bullet verbatim** into a working scratch (the plan file, an in-message table, or a temp note). Do not paraphrase — verbatim preserves sub-clauses you might otherwise compress away.

3. **Parse every clause and sub-clause separately.** A gate like ``go test -race ./... passes — including TestX for every Y`` is TWO assertions: (a) `go test -race ./...` exits 0, AND (b) `TestX` is exercised for every `Y`. Score each separately. Sub-clauses are common and easy to miss — the conjunctions "including", "and", "as well as", "for every", "incl." usually signal one.

4. **Read referenced documents before scoring.** If a gate clause names a document, path, or section (e.g. "see `docs/foo.md` §6"), open that document and read the named section *before* scoring the clause. Score from the document's actual content, not from the gate's surface text or the author's framing. Pattern-matching the author's section header to the gate text is not scoring.

5. **Apply local-rule qualifiers before scoring.** For each gate clause, check whether loaded local rules confirm, refine, elaborate on, or exempt the gate before turning it into a finding. Local rules include user-provided instructions, project-level guidance, repository instructions, PR/MR templates, branch/workflow policy, and relevant reviewer context loaded for the session. Record the applicable qualifier in the quality gates audit table, or explicitly note that no local qualifier was found. Higher-priority local rules can narrow or exempt a lower-priority gate; lower-priority rules can add evidence requirements but cannot override a higher-priority exemption.

6. **Score each clause as PASS / PARTIAL / FAIL / NEED-EVIDENCE** based strictly on evidence the author offered in the PR body, commit messages, or PR comments, after applying any local-rule qualifier from the previous step. Treat "no evidence offered for this clause" as a FINDING (NEED-EVIDENCE) — not a pass-by-default, and not a license to investigate (see Step 6.5).

7. **Form findings + verdict only after every clause is scored.** Verdict follows the highest-severity finding per Step 8. Verdict is NOT determined by a gestalt impression of the PR or by author response latency.

Include the per-clause scoring as a "Quality gates audit" table in the posted review body so the author sees which clauses you scored and how.

### Step 4: Analyze the code

For every file in the diff, evaluate against these dimensions. Weight them based on what the review guidelines prioritize.

**Correctness:**
- Logic errors, off-by-one, nil/null dereference risks
- Race conditions in concurrent code
- Resource leaks (unclosed handles, unbounded maps/caches, goroutine leaks)
- Error handling — are errors swallowed silently? Propagated with context?
- **Silent Failure Hunt:** Explicitly check for empty `catch`, `except`, or `recover` blocks. Flag any error suppression that doesn't include a mandatory `log` or `TODO` explaining why it's ignored. **CRITICAL** if in a data-persistence or security path.

**Security:**
- Input validation at trust boundaries
- Credential handling — secrets in code, API keys in config
- Injection risks (SQL, command, regex)
- Auth bypass paths
- **PII exposure** — flag any hardcoded personally identifiable information in the code or test fixtures. This includes email addresses, phone numbers, physical addresses, IP addresses, SSNs, credit card numbers, names tied to real individuals, and any other data that could identify a person. Test files using real-looking PII (e.g., `john.doe@company.com`, `555-123-4567`) should use obviously fake values (e.g., `test@example.com`, `000-000-0000`) or be generated/randomized. PII in code is a **CRITICAL** finding — it is a compliance and legal risk regardless of whether the repo is public or private.

**Data quality & Type Design:**
- False positive risk — does the pattern match things it shouldn't?
- False negative risk — does it miss valid inputs?
- Validation — are checksums, range checks, or format validators present where needed?
- **Type Design Analysis:** Check for leaky abstractions. Are internal state variables or invariants exposed through public types/structs? Are exported types too large (God objects)? Enforce encapsulation and "make illegal states unrepresentable" where possible.

**Architecture:**
- Single responsibility — does each module/function do one thing?
- Interface boundaries — are abstractions clean?
- Dependency direction — do high-level modules depend on low-level ones?

**Hacks and workarounds (disqualifying):**
Any code that bypasses proper implementation is a finding. Hacks are not acceptable in production code and must be replaced with proper solutions before merge. Scan for:
- `TODO`, `FIXME`, `HACK`, `WORKAROUND`, `TEMP`, `XXX`, `KLUDGE` comments — each one is an admission that the code is not ready. Flag as **HIGH** minimum. If the hack is in a security, auth, or data path, flag as **CRITICAL**.
- Hardcoded values that should be configurable — magic numbers, hardcoded URLs, embedded timeouts, fixed retry counts, hardcoded credentials or endpoints. Flag as **HIGH**.
- Commented-out code — dead code left behind signals incomplete cleanup. Flag as **MEDIUM** unless it disables a security check, in which case **CRITICAL**.
- Copy-pasted blocks with minor variations — indicates a missing abstraction. Flag as **MEDIUM**.
- Try/catch or recover blocks that swallow errors to force execution past a known failure — this masks bugs. Flag as **HIGH**.
- Feature flags or environment checks that bypass validation, auth, or security in non-production environments (e.g., `if env != "prod" { skipAuth() }`) — these inevitably leak to production. Flag as **CRITICAL**.
- Monkey-patching, runtime type coercion, reflection hacks, or unsafe casts used to work around type system constraints. Flag as **HIGH**.
- Sleep/delay calls used as synchronization (instead of proper signals, channels, or condition variables). Flag as **HIGH**.
- Shell-outs or exec calls that delegate to external commands what should be done in-process. Flag as **MEDIUM** unless the command handles untrusted input, in which case **CRITICAL** (command injection risk).
- **Linting suppression comments** — any comment that silences a linter, type checker, or static analysis tool without fixing the underlying issue. (See language-specific fixes).

**Test coverage:**
Test coverage is a hard gate, not a suggestion. The thresholds apply to **code changed in this PR**, not to the entire package or repository. 
- **90% minimum per changed file**
- **95% minimum across all changes**

**Path-classification before severity.** For every "missing test" finding, identify the *consumer* of the changed code — where the value is read, where the function is called, where the config slice is consumed. If any consumer is on an auth, security, validation, or PII-handling path, severity is **HIGH** minimum, **CRITICAL** if the path is the only barrier to credential or PII exposure. Severity follows consequence-of-regression, not size-of-diff. Worked example: a one-line addition to an `AuthDomains` config slice with no `defaults()` test assertion is HIGH — a future refactor can drop the entry, rerouting OAuth payloads into systems that should bypass them. Trace the consumer before assigning severity; do not classify a coverage gap by how the diff "looks."

**Config-presence is necessary, not sufficient, for new entries on a security path.** When a PR adds an entry to a security-classifier slice/map (auth domains, allowlists/denylists, security middleware tables, role mappings, PII bypass lists), require BOTH (1) a config-presence assertion that the entry is in the configured slice AND (2) a functional assertion that the consumer behaves correctly for that entry (e.g., for a new `AuthDomains` entry, `isAuthRequest("oauth2.googleapis.com", "/...") == true`; for a new allowlist entry, the gate function returns the expected verdict on that input). Config presence alone leaves the consumer's logic unguarded — a future refactor of the consumer (changed lookup pattern, added path-prefix requirement, swapped the underlying table) silently breaks behavior while the config-presence test stays green. Either part missing is **HIGH**.

**Subset coverage requires explicit rationale.** When a test exercises a subset of new inputs (domains, providers, format variants, etc.) that all flow through the same downstream code path, the implicit reasoning "they share the code path → transitively covered" is **MEDIUM**, not LOW or NIT. The assumption only lives in the reviewer's head; future refactors that split or specialize the shared path silently leave the untested inputs uncovered. Required fix: either (a) extend the table to cover all inputs (preferred — usually one line), or (b) make the rationale explicit BOTH in the test docstring (e.g. "subset chosen as representative; all N share the `<X>` code path") AND in the corresponding development docs. The goal is that a future reader unfamiliar with the original PR can answer "why aren't all N inputs tested here?" without consulting PR history.

**Documentation & Comment Rot:**
- Are public APIs documented?
- Do comments explain "why" not "what"?
- **Comment Rot Check:** Compare docstrings and comments against the implementation. Flag any documentation that has diverged from the actual code behavior.

### Step 5: If a spec was provided, cross-check

For each requirement or config field in the spec:
- Is it implemented?
- Is it validated?
- Is it tested?
- Is it documented?

Report any gaps as findings.

### Step 6: Check CI pipeline (always — not optional)

Pipeline status is a merge gate. **Always** check it.
- **GitHub:** `gh pr checks {number}`
- **GitLab:** `glab ci status`

**Author's documented baseline-vs-result evidence (always — not optional).** The author is responsible for proving the code still functions as it should — by documenting baseline state (what passed before the change) AND post-change results (what passes after). CI green is external evidence the suite ran; it is not a substitute for the author's own documented due diligence, and you must check that the author actually offered the proof.

For the **original commit** on the PR, scan the PR body for explicit claims:
- Test suite executed (e.g., `make check`, `go test -race ./...`, `pytest --cov`)
- No regressions vs baseline — ideally with the affected pre-existing test names enumerated, not just "all tests pass"
- Coverage numbers attached to the changed functions or files

For **revision commits pushed in response to prior reviews**, the same evidence must be re-stated against the *revised* code — either in the revision commit body, or in an updated PR-body comment. A revision that materially changes function shape (split, merge, rename, refactor) invalidates the original commit's per-function coverage claims and the original "no regressions" claim; both need to be re-asserted against the new code. A revision commit message that only describes WHAT changed and announces new tests, without re-stating the baseline-and-post-revision picture, leaves the reviewer inferring correctness from CI status alone.

If the author has pushed revisions without re-asserting baseline-vs-result for the revised code, flag as **MEDIUM**. The fix is documentation — a PR comment or amended commit body with (1) baseline state, (2) post-revision state, (3) updated per-function coverage on changed functions. It is not more code.

### Step 6.5: Reviewer-scope hard stop (per finding)

The reviewer's job is to evaluate evidence the author offered, not to substitute reviewer-side investigation for that evidence.

**STOP and flag missing-evidence — do NOT investigate — when about to:**
- Run a test, lint check, or build to verify a gate is met
- Grep the codebase to verify a symbol exists for every type/case the gate names
- Open CI logs to extract per-line coverage, test counts, or per-test status
- Read a test file to count its cases on the author's behalf
- Open source files to enumerate branches the author should have tested
- Manually run any command listed in a gate to see its output

If the author didn't offer evidence for a clause, the finding is **"evidence not offered for clause X"** — not "let me check." Substituting reviewer-side investigation for author-side evidence:

- Lets the author skip the documentation half of the gate
- Hides the gap from future readers of the PR — your investigation lives in your head, not the PR record
- Wastes reviewer attention on confirming things the author should claim and own

Before posting any finding (or any verdict), run this per-finding check:

- What evidence did the author offer for this clause, verbatim?
- Am I about to verify a gate by investigating? If yes — STOP. Reformulate as a missing-evidence finding.

If you find yourself reasoning "but it's quick to check," that's exactly the failure mode this hard stop exists to prevent.

### Step 7: Identify exact line numbers

Determine the **exact new-side line number** in the diff using `gh api` or `glab api` hunk parsing. This is critical for accurate inline comments.

### Step 8: Determine review event

The review event is determined by the **highest severity finding**:

**Severity downgrade gate (applies before the verdict table below).**

A finding's severity cannot be lowered by author response alone. Any of the following downgrade triggers requires a durable, reviewer-verifiable artifact before the finding's classification changes:

- **Deferral to a follow-up PR / release / phase** → both a tracking issue filed in the project's tracker AND an in-code anchor (TODO comment, doc reference) on the relevant code line pointing to that issue. Author reply in a review thread does NOT count as a tracking artifact.
- **Citation of a spec, design decision, or internal doc** → the cited document must be in-tree, linked from the PR, or have the relevant clause quoted into the PR thread. A citation the reviewer cannot read is not evidence.
- **"Existing convention" / "matches elsewhere in the codebase"** → a `file:line` reference proving the convention exists.
- **"Will be fixed in a follow-up"** → same as deferral above; "I'll do it later" is a claim, not an artifact.

Without the artifact, the finding's severity stays at its initial classification and feeds the verdict table as if no downgrade was offered.

This gate applies on every round, not just re-reviews. A first-round PR body that says "deferred to v2" without an issue reference triggers the same gate. The gate is mechanical — verdict generation cannot route around it without producing a visibly contradictory ledger entry (Step 3.6 #8).

| Highest finding | Event | Meaning |
|---|---|---|
| MEDIUM or above | `REQUEST_CHANGES` | PR is not ready — author must address issues before merge |
| LOW only | `COMMENT` | No blockers, but leaving observations |
| None | `APPROVE` | Clean — ready to merge |

There is no middle ground. A review with any MEDIUM, HIGH, or CRITICAL finding is a hard `REQUEST_CHANGES`. Half-approval does not exist.

Pipeline status does not influence this table. A green pipeline does not reduce finding severity or permit downgrading REQUEST_CHANGES to COMMENT.

### Step 9: Post the review

**API mapping:**

| Action | GitHub (`gh api`) | GitLab (`glab api`) |
|---|---|---|
| Approve | `POST /repos/{owner}/{repo}/pulls/{number}/reviews` with `event: "APPROVE"` | `POST /projects/{id}/merge_requests/{iid}/approve` |
| Request Changes | `POST /repos/{owner}/{repo}/pulls/{number}/reviews` with `event: "REQUEST_CHANGES"` | Post comment with `/request_changes` quick action |
| Comment Only | `POST /repos/{owner}/{repo}/pulls/{number}/reviews` with `event: "COMMENT"` | `POST /projects/{id}/merge_requests/{iid}/notes` |

**Status state — re-review caveats.**

- **GitHub:** Posting `APPROVE` does NOT dismiss a prior `REQUEST_CHANGES` from the same reviewer — they are stacked, independent review records. After re-reviewing and approving, explicitly dismiss the earlier review via `gh api -X PUT repos/{owner}/{repo}/pulls/{number}/reviews/{review_id}/dismissals -f message="..."`. Without this, branch protection still blocks merge.
- **GitLab:** Each reviewer has a SINGLE state (not started / in progress / approved / requested changes), not stacked records. Switching state — for example `/approve` after a prior `/request_changes` — replaces the previous state in place. No dismissal step is needed. To force a fresh review from an existing reviewer (resetting their state and re-notifying), post `/request_review @user` (alias `/reviewer`).
- **GitLab tier caveat:** Request-changes-as-merge-block is a Premium/Ultimate feature. On Free tier, requesting changes is advisory only and does not block merge. Verify the project tier before relying on `/request_changes` as a hard gate.
- **GitLab approve SHA pinning:** For APPROVE actions, require SHA pinning. Use approval with explicit SHA. If SHA mismatch occurs, refresh and rerun Step 3.6. Never post approval against an unpinned or stale head.

**Summary body** includes:
```markdown
## PR Review: {title}

### Pipeline status
[PASS / BLOCKED]

### Test coverage verdict
[PASS / FAIL / UNVERIFIABLE]

### Path to Approval (Action Plan)
1. [Blocker 1] -> Resolve by [Fix]
2. [Blocker 2] -> Resolve by [Fix]
...
3. Fix CI pipeline failure.

### Verdict
[APPROVE / REQUEST_CHANGES / COMMENT]
```

**Inline comments** each tagged with severity (**CRITICAL**, **HIGH**, **MEDIUM**, **LOW**).

## Language-specific awareness

- **Go:** Check error handling, race conditions, goroutine lifecycle.
- **Python:** **Pydantic V2 is mandatory.** Reject V1 syntax (`@validator`, `.dict()`, etc.).
- **TypeScript:** Check `strict: true`, runtime validation (Zod/Valibot).
- **Rust:** Check ownership/borrowing, `unwrap()`, unsafe blocks.
- **Java:** Check null handling, try-with-resources, thread safety.
