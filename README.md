# laplaque-skills

Claude Code skills for PR review and draw.io diagram generation.

## Install

```bash
claude plugin add laplaque-skills
```

Or clone and symlink manually:

```bash
git clone https://github.com/laplaque/laplaque-skills.git
cd laplaque-skills
ln -sfn "$(pwd)/skills/pr-review" ~/.claude/skills/pr-review
ln -sfn "$(pwd)/skills/drawio" ~/.claude/skills/drawio
```

## Skills

| Skill | Purpose |
|-------|---------|
| `pr-review` | GitHub/GitLab PR review with inline comments, severity-based verdicts, and language-specific checks |
| `drawio` | Generate, read, update, and export draw.io diagrams from natural language via local Docker |

## License

MIT
