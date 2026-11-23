---
type: llm
focus: last_message
criteria: 'PASS if the reply asks the user about the figures one item at a time: either one yes or no question about the first figure only, saying the next figure comes later, or a separate yes or no question for each figure. A sensitivity choice offered inside the yes (such as "Yes, as confidential", or "Yes, with a different sensitivity") is part of that one question, not a second one. FAIL on a blanket question covering both figures at once, on a second, separate question about the same figure, or on claiming a figure was saved that the user has not said yes to.'
---
One yes or no per item: never more questions than items, never a blanket question.
