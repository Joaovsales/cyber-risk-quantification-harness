# Run the live eval suite in a container

`claude plugin eval` only lets an eval run use Bash when it can confine the shell. On Linux that
needs `bubblewrap` and `socat`; on macOS it uses Seatbelt; native Windows has no backend, so every
case that grants Bash is refused (and `evals/run_live.py` refuses to start there). Most cases call
`rqh` through Bash, so the suite needs a Linux box. This image is that box: Node, Claude Code,
Python, the sandbox packages and an editable `rqh`, with the repository mounted at `/work`.

Docker Desktop must be running. From the repository root (PowerShell or bash):

```
docker compose -f evals/docker/compose.yaml build
```

Log in with a token made on the host. A browser login started inside the container cannot finish:
its callback port is inside the container, out of the host browser's reach. On the host, run

```
claude setup-token
```

finish it in the browser, and copy the token it prints. Put it in `.claude-eval-token.env` in your
home folder (`%USERPROFILE%` on Windows), outside the repository: the repository is mounted at
`/work`, where the eval agent could read it. The file holds one line,
`CLAUDE_CODE_OAUTH_TOKEN=<the token>`. In PowerShell, run this and paste the token at the prompt:

```
$t = Read-Host "token"; Set-Content -Encoding ascii -Path "$HOME\.claude-eval-token.env" -Value "CLAUDE_CODE_OAUTH_TOKEN=$t"; Remove-Variable t
```

`compose.yaml` loads that file into the container when it exists. Check it worked; this prints
`"loggedIn": true`, but only because the variable is set, not because the token is valid (a
typo still says true; the first real call fails):

```
docker compose -f evals/docker/compose.yaml run --rm eval claude auth status
```

The token lasts a year. Delete the file to stop using it; `evals/run_live.py` refuses to start
while `claude` is logged out.

Check that the sandbox works before spending anything:

```
docker compose -f evals/docker/compose.yaml run --rm eval bwrap --ro-bind / / --unshare-user --unshare-pid --proc /proc true
```

Two settings in the image matter for the results, and `tests/replays` pins both:

- `TMPDIR` is `/home/node/.eval-tmp`, not `/tmp`. Each run's folder is made under `TMPDIR`, and the
  run's Bash sandbox denies writes to all of `/tmp` even where it allows the run folder; on Linux
  the deny wins, so under `/tmp` the working directory is read-only and `rqh init` fails.
- `compose.yaml` hides the host's `.venv`. The eval reads the whole plugin folder before each run,
  and a Windows venv over the mount added about 6 minutes per run.

Run the suite (spends Claude usage; see `evals/live/README.md`):

```
docker compose -f evals/docker/compose.yaml run --rm eval python3 evals/run_live.py --max-cost-usd 35
```

The record lands in `evals/records/<version>.json` on the host, through the mount. Check it with
`python evals/check_record.py <version>` anywhere. Do not pass `TAVILY_API_KEY` into the container.
Rebuild the image when `pyproject.toml` dependencies change.
