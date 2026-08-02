# Public repository initialization

The distributed source ZIP is history-free and contains no remote.

1. Extract it into Termux private storage.
2. Run `bash scripts/bootstrap-termux.sh`.
3. Run `bash scripts/public-init-audit.sh`.
4. Inspect the audit evidence and source tree.
5. Run `bash scripts/init-public-repo.sh`.

The final command initializes `main`, reruns the full gate and stages all source files. It does not commit unless `--commit` is provided, add a remote, create a GitHub repository or push.

After review:

```bash
git status --short --branch
git diff --cached --check
git commit -m 'Initial public release candidate'
git remote add origin git@github.com:cbkii/otast.git
git push -u origin main
```

Create the empty public GitHub repository only after the local commit is ready. Do not attach the history of any development repository.
