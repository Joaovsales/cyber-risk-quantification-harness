---
type: llm
focus: last_message
criteria: 'PASS if the reply shows the scoped scenario and asks the user exactly one question: a single confirmation request whose choices are offered together, often as a numbered list (confirm on a route with the defaults, confirm and set n or seed, or change the scenario). A line that tells the user how to answer is part of that question. Listing "Confirm" as a choice is not a claim that anything was confirmed. FAIL if the reply asks a second, separate question, or says that the run was already confirmed (that rqh run confirm was run), simulated or reported.'
---
YOLO asks exactly one question in the scoping confirmation pass, and none after it. An eval run does not offer AskUserQuestion, so the skill asks in text and the reply is judged.
