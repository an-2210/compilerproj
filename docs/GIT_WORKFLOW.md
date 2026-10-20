# Git workflow

The original `meheli-initial` branch and commit `f91955b6ce0fe9ceb860971d4bc361c2ad1491d5` were preserved. Systems work lives on `feature/systems-engineering`. No empty `main`, `develop`, or teammate feature branches were created. Keep commits scoped to tested milestones.

To inspect: `git status`, `git log --oneline -5`, `git branch -vv`, `git remote -v`. To review this work: `git diff meheli-initial...feature/systems-engineering`. On this machine Git may flag ownership because Codex runs under another Windows account; use a repository-specific `git -c safe.directory=<absolute-checkout-path> ...` if required. Do not configure a wildcard globally.

Before publishing, fetch `origin`, inspect branch conflicts and authentication, then push with `git push -u origin feature/systems-engineering`. Open a pull request targeting the repository's intended integration branch after checks pass. Never force-push or merge into a shared stable branch without authorization. If a remote branch has moved, fetch and review it before any merge. Recovery starts with `git status` and the immutable commit IDs; avoid hard resets and clean commands.
