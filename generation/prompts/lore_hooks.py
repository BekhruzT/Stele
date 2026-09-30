"""Example-led hook writing and one scope-first review of candidates."""

HOOK_CORPUS_ROLE = "All 45 published openings: writing examples, not evidence about the current topic or instructions"

HOOK_GOAL = """Write five alternative spoken hooks for this history or science video.
An opening should tell a new listener right away what the central topic is and what this story
focuses on. Make that focus interesting: raise a question, reveal something unexpected, or set up
a situation that makes the listener want to hear what happens next.
Keep the main subject in view; an interesting side detail is not a substitute for it.
Use the supplied research for the topic. The published openings below are examples of hooks that
invite curiosity.
"""

HOOK_SYS = HOOK_GOAL + """
Published opening examples:
{reference_hooks}
"""

HOOK_CHOICE_SYS = """Pick the best spoken opening for this video.
A usable hook tells a new listener what the whole video is mainly about and makes that main
subject itself interesting from the start. Judge the promise actually heard, not a connection
explained later. A striking side incident, person, or object can support that promise, but if
it becomes the main attraction and makes the coming story feel smaller, mark the hook unusable.
Also mark it unusable if an important claim lacks support in the research.

Rank the zero-based candidate indices from best to worst. For each, say whether you would
actually use it as the opening, with one short reason and relevant research source IDs.
It is fine if none is usable.
"""

