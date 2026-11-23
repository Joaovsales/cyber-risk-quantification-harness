# Web search

`rqh search` is an optional web search for the data-collection skill, backed by the Tavily API. It needs a
`TAVILY_API_KEY` in the environment; without one it refuses cleanly, and every other command works without it. It
writes no file.

## Sub-features

- `no-key` refuses with exit 2, issue path `env.TAVILY_API_KEY`, rule `missing`, when the variable is unset or blank.
- `search` returns the API's result as `data` (exit 0) for `<query>` with `--max-results N` (default 5) and
  `--depth basic|advanced` (default `basic`).
- `network` turns a network or API fault into exit 1, issue path `search`, rule `network`.
- `usage` makes a bad `--depth` or a non-integer `--max-results` exit 2.

## How to get to it (user POV)

- `rqh search "<query>" [--max-results N] [--depth basic|advanced]` with `TAVILY_API_KEY` set.

## Driving it with verify.py and a browser

Preconditions:

- Any directory; no workspace is needed. `unset TAVILY_API_KEY` first (the recipe in
  [the index](./README.md#a-workspace-by-hand) does). `verify.py run` does not touch this command.

- **No key.** `rqh search "credential phishing incident cost"`: exit 2, `issues[0].path` `env.TAVILY_API_KEY`,
  `issues[0].rule` `missing`. `TAVILY_API_KEY="  " rqh search x` is the same exit 2.
- **Usage.** `rqh search x --depth deep` and `rqh search x --max-results many`: exit 2, rule `usage`.
- **With a key.** Only when the person running the check provides their own key: `rqh search "credential phishing
  incident cost" --max-results 3` is exit 0 with results in `data`. Without a key this step is `BLOCKED`, not `PASS`;
  the no-key and usage recipes above still prove the command's own behaviour.

## Gotchas

- Never print, log or commit the key. Pass it in the environment of the one command, not on the command line.
- A search with a key sends the query to an outside service. Use a generic query, never one built from a real
  organisation's scenario or data.
- The automated tests (`tests/search/`) cover the result shaping and the network fault offline; this recipe only adds
  the live call.
