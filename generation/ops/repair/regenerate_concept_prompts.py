
regeneration_guidelines_by_asset = {
    "MCQs": """Conditions requiring MCQ regeneration:

If Transcript Changed AND:
  - The transcript change affects the explanation of the correct answer.

If Concept Changed AND:
  - The concept change affects the core idea assessed by the MCQ. Each MCQ must assess the central idea of the concept. If the concept change shifts the focus away from the original core idea, the MCQ must be updated accordingly.
""",
    "Raw Transcript": """Conditions requiring Raw Transcript regeneration:

If the requested changes involve more than minor adjustments (such as pauses). For example, if explanations need to be added, removed, or rephrased, the Raw Transcript must be regenerated.
"""
}

SYSTEM_PROMPT_DETERMINE_NEED_FOR_CHANGE = """You are tasked with determining whether a specific type of asset needs updating based on changes in underlying dependencies. Your goal is to analyze the provided information and decide if the asset requires regeneration.

The asset type in question is {asset_type}. The user will specify the changes made to the asset type. Use the guidelines below to determine whether the changes made warrant a regeneration:
<regeneration_guidelines>
{regeneration_guidelines}
</regeneration_guidelines>

Your task is to carefully analyze the change context and compare it against the regeneration guidelines. Consider how the change might impact the {asset_type} and whether it meets the criteria for regeneration.

Use the following scratchpad to organize your thoughts and analysis:

<scratchpad>
1. Summarize the key changes made to the asset based on the change context provided
2. Evaluate the changes against the regeneration guidelines, and determine if the changes warrant a regeneration.
</scratchpad>

After completing your analysis, make a decision on whether the {asset_type} needs to be regenerated. 

Provide your final output in the following JSON format within <output> tags:

<output>
{{
  "regenerate": [true/false],
  "reasoning": "[A clear explanation of why the change does or does not warrant regeneration, based on your analysis]"
}}
</output>

Ensure that your reasoning is thorough and directly relates to the change context and regeneration guidelines provided."""

USER_PROMPT_DETERMINE_NEED_FOR_CHANGE = """Here is the change made to the {asset_type}:
```
{change_context}
```

{asset}
"""

SYSTEM_PROMPT_UPDATE_TRANSCRIPT = """You are tasked with updating a specific concept's transcript content based on a requested change.

Your task is to:
1. Update only the specified concept's explanation in the transcript
2. Maintain the same style, tone, and format as the original
3. Ensure the change is integrated naturally and maintains coherence
4. Keep all other parts of the transcript unchanged. Make minimal necessary edits, changing only what was specifically requested in the change request.

Respond with the updated transcript content for this concept only. Place the transcript inside <transcript> tags."""

USER_PROMPT_UPDATE_TRANSCRIPT = """Current transcript content for the concept:
{transcript_content}

Change requested:
{change_request}

Please provide the updated transcript content for this concept."""