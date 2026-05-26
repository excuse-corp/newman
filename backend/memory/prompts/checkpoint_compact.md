You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM that will resume the task.

Include:
- Current progress and key decisions made
- Important context, constraints, or user preferences
- What remains to be done (clear next steps)
- Any critical data, examples, or references needed to continue

Additional rules:
- If an existing checkpoint summary is provided, merge it into one refreshed summary instead of appending raw logs.
- Focus on durable context that still matters after older messages are removed.
- Preserve confirmed facts, accepted or rejected approaches, error diagnoses, and concrete references only when they still matter for future turns.
- Do not include routine process chronology, tool-by-tool narration, file read/write bookkeeping, memory maintenance notes, workflow IDs, request IDs, turn IDs, group IDs, or similar internal tracing data.
- Do not enumerate completed branches, filler material, test scaffolding, or incidental examples unless they remain active constraints or are the actual user goal.
- Tool findings should only be kept when they create a durable constraint, unblock the next step, or contain a user-visible result that will otherwise be lost.
- Prefer the smallest summary that still lets the next model continue the task correctly.
- Do not invent reasoning, hidden chain-of-thought, tool outputs, or facts not present in the provided material.
- Be concise, structured, and focused on helping the next LLM seamlessly continue the work.
