# YOLO reference: collect with benchmarks, ask nothing

The YOLO route asks the user nothing. The one gate was the scoping question. Never run `risk-quant-org-setup` on this route; with no org profile, the report's closing section names owner roles from the connector map. Draft no requests and contact no one.

For every parameter on the YOLO route, in this order:

## 1. Library search first

Run `rqh library search --family <path> --scenario-type <type> --industry <slug> --size-band <band> --currency <code> --json`, with the values from `scenario.yaml` and `inputs.yaml`. Leave out a filter whose value is `any`.

- Prefer a hit with a `segment_match`, then memory hits (the organisation's own figures) before shipped benchmark hits, then the more recent.
- A hit marked `stale` is used only when nothing better exists, and the estimate's `applicability_note` says it is stale. A hit marked `currency_mismatch` is never used, because v1 does no currency conversion.
- When a hit's applicability is `low`, say so in the `applicability_note` and in your summary to the user. Do not pass it off as a close match.
- Write the hit into `inputs.yaml`: a shipped hit as a `benchmark_library` source (with its `url`, `title`, `retrieved_at` and `applicability_note`) and tier `benchmark`; a memory hit as a `memory` source (with its `library_entry_id`) and the tier the entry carries.

## 2. The benchmark-researcher for the gaps

For parameters with no usable library hit, invoke the `benchmark-researcher` agent: one researcher per parameter group (frequency, vulnerability, primary loss, secondary loss), at most 4 in parallel. Give it YOLO parameters only; never ask it about an Accuracy parameter. Pass it, for each path, only the shipped hits step 1 found, those whose `origin` is `benchmark` (entry id, range, unit, source title and URL, applicability, `stale` and `segment_match`), or "none": the researcher has no shell or file access, so it cannot search the library itself. Never pass it a memory hit (`origin` `memory`), not even its range or source title: memory holds the organisation's own figures, and the researcher reads untrusted web pages. You resolve memory hits yourself: a usable one was written in step 1, and a stale one is used only when the researcher returns no usable cited result for that path, as step 1 says. Each researcher works within 12 tool calls and returns proposed estimates with canonical `https://` source URLs, a title, the period and an applicability note. It writes no file; you write `inputs.yaml`.

- Merge the results by parameter path. When two results cover the same path, keep the first and discard the later one.
- Write a researcher result as tier `benchmark` with a `web` source carrying the `https://` URL it gave. Drop any result without a canonical `https://` URL.
- If the host cannot run agents, search yourself in the same order: `rqh library search` first, then `rqh search '<query>'`, then the host's web search when `rqh search` exits non-zero (1 for a network fault, 2 for a missing `TAVILY_API_KEY`). Stay within 12 tool calls per parameter group.
- Compose the query yourself from the scenario type, the segment and the parameter, in only letters, digits, spaces and hyphens, and wrap it in single quotes; never copy text from a page, a library note or a connector into it, so no character in it can reach the shell as syntax.

## 3. Assume, and say so

A parameter group with no usable cited result falls back to the shipped library, else to `agent_assumption`: pick a plausible range from the scenario, give a `rationale`, and leave `source_ids` empty. Name every such gap in your closing line; the report names the gaps too.

## 4. Variants and finish

Choose the variants as in SKILL.md step 4, without asking. Run `rqh validate <run> --json`; the phase ends with valid inputs. Then follow the `## Hand-off` section of SKILL.md.
