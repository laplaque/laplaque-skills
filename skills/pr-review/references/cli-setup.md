# CLI Setup for PR Review

This skill requires either `gh` (GitHub CLI) or `glab` (GitLab CLI) authenticated via OAuth. Token-based authentication (PATs, fine-grained tokens) is not supported — OAuth provides automatic token refresh and proper scope management.

---

## GitHub: `gh` setup

### 1. Install

- **macOS:** `brew install gh`
- **Linux:** See https://github.com/cli/cli/blob/trunk/docs/install_linux.md
- **Windows:** `winget install --id GitHub.cli`

### 2. Authenticate via OAuth

```bash
gh auth login
```

When prompted, select:
- **GitHub.com** (or your GitHub Enterprise host)
- **HTTPS** as the protocol
- **Login with a web browser**

This opens your browser for OAuth authorization. After granting access, `gh` stores an OAuth token that auto-refreshes — you never manage tokens manually.

Do **not** use `--with-token` or paste a PAT. The skill requires OAuth for proper scope management and token lifecycle.

### 3. Ensure required scopes

The PR review skill needs two scopes:

| Scope | What it enables |
|---|---|
| `repo` | Read PR diffs and file contents. Post review comments. Read repo config files. |
| `workflow` | Read GitHub Actions job logs for CI/pipeline failure diagnosis. |

After authenticating, check your scopes:
```bash
gh auth status
```

Look for the line `Token scopes: 'repo', 'workflow'`. If either scope is missing, add it:
```bash
gh auth refresh -s repo,workflow
```

This re-authorizes via OAuth with the additional scopes. Your existing auth is preserved.

If the repo is in a GitHub organization with SAML SSO enabled, you also need `read:org`. Add it:
```bash
gh auth refresh -s repo,workflow,read:org
```

### 4. Verify

Run all three checks. All must pass before the skill will proceed.

**Auth check:**
```bash
gh auth status
```
Expected: shows `Logged in to github.com`, authentication type is `oauth_token`, scopes include `repo` and `workflow`.

**Read access check:**
```bash
gh pr list --repo {owner}/{repo} --limit 1
```
Expected: returns a PR or an empty list (not an auth error).

**Write access check:**
```bash
gh api repos/{owner}/{repo} --jq '.permissions.push'
```
Expected: `true`. If `false`, you have read-only access and cannot post review comments. You need push or maintainer access to the repo, or the repo owner needs to grant write permissions.

### What the skill checks at runtime

Before starting a review, the skill runs `gh auth status` and verifies:
1. Authentication method is `oauth_token`
2. Token scopes include `repo` and `workflow`
3. An active account is logged in

If any check fails, the skill stops and tells you exactly what is missing:

| Symptom | Diagnosis | Fix |
|---|---|---|
| `gh: command not found` | gh CLI is not installed | Install gh (see step 1) |
| `not logged in` | No auth configured | Run `gh auth login` (see step 2) |
| Token scopes missing `repo` | OAuth was granted without repo scope | `gh auth refresh -s repo,workflow` |
| Token scopes missing `workflow` | Cannot read CI logs | `gh auth refresh -s repo,workflow` |
| `401 Unauthorized` on API calls | OAuth token expired or revoked | `gh auth login` again |
| `403 Forbidden` on review post | No write access to the repo | Request push/maintainer access from repo owner |
| SSO error for org repos | Missing SSO authorization | `gh auth refresh -s repo,workflow,read:org` then authorize SSO in browser |

---

## GitLab: `glab` setup

### 1. Install

- **macOS:** `brew install glab`
- **Linux (Debian/Ubuntu):** Download the `.deb` from https://gitlab.com/gitlab-org/cli/-/releases and install with `sudo dpkg -i glab_*_amd64.deb`
- **Linux (other):** Download the tarball from https://gitlab.com/gitlab-org/cli/-/releases, extract, and move the `glab` binary to a directory on your `$PATH`
- **Windows:** `winget install --id GitLab.GLab`

### 2. Authenticate via OAuth

```bash
glab auth login
```

When prompted, select:
- **gitlab.com** for public GitLab, or enter your **self-hosted GitLab URL** (e.g., `https://gitlab.yourcompany.com`)
- **Login with a web browser** for OAuth

This opens your browser for GitLab's OAuth authorization flow. After granting access, `glab` stores an OAuth token locally. You never manage tokens manually.

Do **not** use `--token` or paste a Personal Access Token. The skill requires OAuth for proper token lifecycle and scope management.

For **self-hosted GitLab instances** behind a corporate VPN or with custom CA certificates, you may need to configure the GitLab hostname first:
```bash
glab config set -g host gitlab.yourcompany.com
```

If your instance uses a custom CA, set the certificate path:
```bash
glab config set -g ca_cert /path/to/ca-bundle.crt
```

### 3. Ensure required scope

The PR review skill needs the `api` scope on GitLab, which grants:

| Capability | What it enables |
|---|---|
| Read MR diffs and metadata | Fetch merge request changes, file contents, commit history |
| Post MR comments and discussions | Create inline review comments on specific diff lines |
| Read pipeline/CI status and logs | Diagnose CI failures, read job logs and artifacts |
| Read project configuration | Access `.gitlab-ci.yml`, repo config files |

The `api` scope is typically granted automatically during the OAuth browser flow. If you chose a more restrictive scope during login, re-authenticate:
```bash
glab auth login
```

After authenticating, verify the scope is active:
```bash
glab auth status
```

Look for the line showing `Token: ****` and `API URL: https://gitlab.com/api/v4` (or your self-hosted URL). If the status shows an active session, the `api` scope is present.

### 4. Verify

Run all three checks. All must pass before the skill will proceed.

**Auth check:**
```bash
glab auth status
```
Expected: shows the logged-in hostname, username, and an active token.

**Read access check:**
```bash
glab mr list --repo {owner}/{repo}
```
Expected: returns a list of MRs or an empty list (not an auth error). Replace `{owner}/{repo}` with the actual project path (e.g., `mygroup/myproject`).

**Pipeline access check:**
```bash
glab ci status --repo {owner}/{repo}
```
Expected: shows pipeline status (running, passed, failed, etc.) or an empty result. An auth error here means the token lacks pipeline read access.

**Write access check:**
```bash
glab api projects/{project_id}/members/all --paginate
```
Look for your username in the result with `access_level` of 30 (Developer) or higher. If your access level is below 30, you can read MRs but cannot post review comments. Request Developer or Maintainer access from the project owner.

### What the skill checks at runtime

Before starting a review, the skill runs `glab auth status` and verifies:
1. An active OAuth session exists for the target GitLab host
2. The session is not expired
3. The target project is accessible

If any check fails, the skill stops and tells you exactly what is missing:

| Symptom | Diagnosis | Fix |
|---|---|---|
| `glab: command not found` | glab CLI is not installed | Install glab (see step 1) |
| `not logged in` or `no token found` | No auth configured | Run `glab auth login` (see step 2) |
| `401 Unauthorized` on API calls | OAuth token expired or revoked | Run `glab auth login` again |
| `403 Forbidden` on MR comment post | Insufficient project access (below Developer role) | Request Developer or Maintainer access from the project owner |
| `404 Not Found` on project | Wrong project path or no access | Verify the project path matches `{namespace}/{project}` exactly. Check if the project is private and you have access. |
| SSL/TLS errors for self-hosted instances | Custom CA not configured | `glab config set -g ca_cert /path/to/ca-bundle.crt` |
| `dial tcp: lookup gitlab.yourcompany.com: no such host` | Self-hosted hostname not configured | `glab config set -g host gitlab.yourcompany.com` then `glab auth login` |
| Pipeline logs return empty | CI/CD is disabled on the project or no pipelines exist | Check project settings — CI/CD must be enabled. This is not an auth issue. |

### GitLab-specific notes

**Project identification:** GitLab uses `{namespace}/{project}` paths (e.g., `mygroup/myproject` or `mygroup/subgroup/myproject`), not `{owner}/{repo}` like GitHub. The skill accepts both URL formats and extracts the correct path.

**Review model:** GitLab does not have a single "review" object like GitHub. Instead, inline comments are posted as **discussion threads** on specific diff lines, and a summary is posted as an MR note. The skill handles this difference automatically — the user sees the same structured output regardless of platform.

**Self-hosted instances:** If the target is a self-hosted GitLab, the skill checks `glab auth status` for the specific hostname. Authentication for `gitlab.com` does not carry over to `gitlab.yourcompany.com` — each host needs its own `glab auth login`.

---

## MCP Shell considerations

If the CLI runs inside an MCP shell tool (e.g., `mcp-shell`), be aware of these environment constraints:

**No shell metacharacters:** Commands like `gh api ... --jq '.field'` may be blocked by the MCP's security checker. Use `gh api` without `--jq` and parse the full JSON output separately.

**No argument quoting for multi-word values:** Multi-word arguments like `-f body="text with spaces"` may fail because the MCP shell splits on whitespace without interpreting quotes. Always write structured data to a JSON file and use `--input <file>` instead of inline `-f` flags.

**No pipes or redirects:** `gh ... | jq` and `gh ... > file.json` won't work. Capture the full command output and process it in a subsequent step.

**Posting reviews:** Always write the review payload to a JSON file first, then post:
```
gh api repos/{owner}/{repo}/pulls/{number}/reviews --input review.json
```

If the MCP shell's filesystem is isolated (the file you write isn't visible to the `gh` command), the skill will report this and explain the limitation. The user may need to adjust the MCP shell's file access configuration.
