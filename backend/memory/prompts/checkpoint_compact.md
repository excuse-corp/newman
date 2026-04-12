You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM that will resume the task.

Include:
- Current progress and key decisions made
- Important context, constraints, or user preferences
- What remains to be done (clear next steps)
- Any critical data, examples, or references needed to continue

Additional rules:
- If an existing checkpoint summary is provided, merge it into one refreshed summary instead of appending raw logs.
- Focus on durable context that still matters after older messages are removed.
- Preserve confirmed facts, accepted or rejected approaches, tool findings, error diagnoses, and concrete references when they matter.
- Do not invent reasoning, hidden chain-of-thought, tool outputs, or facts not present in the provided material.
- Be concise, structured, and focused on helping the next LLM seamlessly continue the work.
