---
type: tool_order
before: {tool: Bash, input_match: '(rqh|rqharness)\s+(--json\s+)?status'}
after: {tool: Skill, input_match: '"skill"\s*:\s*"(?:[\w-]+:)?collect-data"'}
---
The router asks rqh status before it invokes the skill status names.
