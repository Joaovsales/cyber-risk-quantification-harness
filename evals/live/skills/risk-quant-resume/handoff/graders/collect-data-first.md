---
type: tool_order
before: {tool: Skill, input_match: '"skill"\s*:\s*"(?:[\w-]+:)?collect-data"'}
after: {tool: Skill, input_match: '"skill"\s*:\s*"(?:[\w-]+:)?(?:simulate|report|scope-scenario)"'}
---
collect-data runs before any other phase skill.
