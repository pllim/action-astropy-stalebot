# GitHub Action for Astropy stalebot

Handle stale issues and pull requests (PRs) according to Astropy policies.
Create a `.github/workflows/stalebot.yml` as follows.
Except for `GITHUB_TOKEN`, other `env` entries are optional:

```yaml
name: Astropy stalebot

on:
  schedule:
    # * is a special character in YAML so you have to quote this string
    # run every day at 5:30 am UTC
    - cron: '30 5 * * *'
  workflow_dispatch:

jobs:
  stalebot:
    runs-on: ubuntu-latest
    steps:
      - uses: pllim/action-astropy-stalebot@main
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

Options that are configurable via `env`:

| env | Default | Description |
| --- | --- | --- |
| `STALEBOT_DRYRUN` | 0 | Set to 1 for dry-run |
| `STALEBOT_SLEEP` | 0 | Number of seconds to sleep between each issue and PR. This is not needed unless you get trip GitHub spam detector. |
| `STALEBOT_MAX_ISSUES` | 50 | Number of issues marked as stale to process each run. Set to -1 to skip this check. |
| `STALEBOT_MAX_PRS` | 200 | Number of PRs marked as stale to process each run. Set to -1 to skip this check. |
| `STALEBOT_CLOSED_BY_BOT_LABEL` | closed-by-bot | Label bot will apply when closing issues and PRs. |
| `STALEBOT_KEEP_OPEN_LABEL` | keep-open | Label to skip stalebot checks. |
| `STALEBOT_STALE_LABEL` | Close? | Label to mark issues and PRs as stale. |
| `STALEBOT_WARN_ISSUE_SECONDS` | 0 | How long to wait before issuing warning after an issue is marked as stale. |
| `STALEBOT_CLOSE_ISSUE_SECONDS` | 604800 | How long to wait after issue is stale before closing it. |
| `STALEBOT_WARN_PR_SECONDS` | 12960000 | How long to wait before issuing warning after the last commit in a PR. This is ignored if PR is marked as stale manually. |
| `STALEBOT_CLOSE_PR_SECONDS` | 2592000 | How long to wait after PR is stale before closing it. |
