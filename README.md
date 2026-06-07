# laplaque-skills

AI coding assistant skills for PR review and draw.io diagram generation. Works with Claude Code, Codex, and any tool that reads the skill format.

## Install

### Claude Code

```bash
claude plugin add laplaque-skills
```

Or symlink manually:

```bash
git clone https://github.com/laplaque/laplaque-skills.git
cd laplaque-skills
ln -sfn "$(pwd)/skills/pr-review" ~/.claude/skills/pr-review
ln -sfn "$(pwd)/skills/drawio" ~/.claude/skills/drawio
```

### Codex

```bash
codex plugin add laplaque-skills@personal
```

Or point your personal marketplace at this repo:

```bash
mkdir -p ~/.agents/plugins/plugins
ln -sfn <path-to-laplaque-skills> ~/.agents/plugins/plugins/laplaque-skills
```

## Skills

| Skill | Purpose |
|-------|---------|
| `pr-review` | GitHub/GitLab PR review with inline comments, severity-based verdicts, and language-specific checks |
| `drawio` | Generate, read, update, and export draw.io diagrams from natural language via local Docker |

## License

MIT
