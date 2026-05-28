# Contributing

This repository uses a pull-request workflow. Keep changes focused, documented, and easy for teammates to review.

## Git Workflow

1. Start from the latest `main`.

   ```bash
   git checkout main
   git pull origin main
   ```

2. Create a branch for your work.

   ```bash
   git checkout -b feature/name-task
   ```

3. Commit small, meaningful changes.

4. Push your branch and open a pull request.

5. Wait for review before merging.

Do not push directly to `main`.

## Branch Naming

- `feature/name-task`
- `fix/name-issue`
- `docs/name-topic`

## Pull Request Rules

- Explain what changed and why.
- Link any relevant issue, task, or class deliverable.
- Include screenshots or sample output when helpful.
- Confirm tests pass locally.
- Keep compliance notes updated when touching source adapters or data collection logic.

## Code Style

- Python 3.11+
- Format with Black.
- Lint with Ruff.
- Keep type hints clear enough for mypy-friendly code.
- Prefer small functions with obvious inputs and outputs.
- Do not commit real secrets, API keys, downloaded private data, or credentials.

## Commit Message Examples

```text
Add base job source interface
Create starter deduplication tests
Document source approval checklist
Fix ranking score for empty student profile
```

## Compliance Expectations

Do not implement unauthorized scraping, login scraping, CAPTCHA bypassing, proxy rotation, or scraping of LinkedIn or other restricted sources. Source adapters must use approved APIs, exports, partnerships, or other compliant access methods.

