CLASSIFY_KEY_CONCEPT_CHANGE_TYPE = """You will be given a key concept from a {subject} lesson and a related comment. Your task is to analyze the comment and categorize the type of change requested for the key concept.

Examine the key concept and the comment closely. Use these classification categories:

1. Create: A new separate key concept is requested or needs to be created
2. Update: A specific change to the existing key concept or the key phrases with in is requested. 
3. Delete: The removal of the concept is requested.
4. NonLocal: The requested change is not specific to this key concept and may affect other key concepts (e.g., moving the key concept, merging key concepts). 
5. NoChange: No change is required, or the issue has been resolved.

Instructions for analysis and classification:
- Carefully consider the relationship between the key concept and the comment.
- Determine if the requested change can be implemented within the scope of the current key concept or if it requires broader changes.
- If a creation of a key phrase is requested this is a Key Concept Update, not a Create. It is Create only if multiple phrases are affected and need to be regenerated.
- When differentiating between Create and Update:
  * If a key phrase addition is requested and can be incorporated without significant changes to the existing concept, classify it as an Update.
  * If the addition would substantially alter the current concept or is better suited as a separate concept, classify it as Create.
- For comments referring to non-local elements or relationships between concepts:
  * If the change can be implemented locally (within the current key concept), use Create, Update, or Delete as appropriate.
  * Only use NonLocal if the change necessarily involves modifying multiple key concepts or the overall structure of the lesson.
- Use NoChange if the comment suggests the issue has been resolved or no action is needed.
- When the user refers to 'this section', they are talking about the key concept itself. Therefore, any specific changes requested for 'this section' should be understood as an update request.

Present your analysis and classification in this format:

<analysis>
[Provide a detailed analysis of the key concept and comment, explaining your reasoning for the classification. Consider the implications of the requested change and how it relates to the current key concept.]
</analysis>

<classification>
[Create || Update || Delete || NoChange ]
</classification>

Examples:
1. Comment: "Add a note about the role of mitochondria in cellular respiration."
   Classification: Update (This adds information to an existing concept)

2. Comment: "This concept should come after the introduction of plate tectonics."
   Classification: NonLocal (This involves changing the order of concepts)

3. Comment: "Remove this section as it's no longer relevant to the curriculum."
   Classification: Delete (This requests removal of the entire concept)

4. Comment: "The Enlightenment should be introduced as a separate key concept."
   Classification: Create (This suggests creating a new key concept)

5. Comment: "This key concept had a faulty reference to Mesoamerica, its removed now."
   Classification: NoChange (This indicates the issue has been resolved)

Remember to provide a thorough analysis before giving your final classification. Consider all aspects of the comment and its implications for the key concept and the overall lesson structure."""

CLASSIFY_PHRASE_CHANGE_TYPE = """You will be given a key concept from a {subject} lesson and a related comment. Your job is to categorize the type of change requested for the key concept based on the comment.

Examine the key concept and the comment closely. Use these classification categories:

1. Create: A new key concept is requested.
2. Update: A specific change to the key concept is requested.
3. Delete: The removal of the concept is requested.
4. NonLocal: The requested change is not specific to the key concept and may affect other key concepts (e.g., moving the key concept, merging two key phrases).

Instructions:
- Differentiating between Create and Update can be challenging when a sub-concept addition is requested. If the sub-concept can be added without significant changes to the existing concept, it should be an update. Otherwise, it's better to create a separate key concept.
- Sometimes, the comment may refer to non-local elements or establish a relationship between this key concept and another one. However, this doesn't always necessitate a NonLocal change. A local change like create, update, or delete could be sufficient. For example:
 - Comment: Remove this as it refers to the maritime empires which appear much later. Although it refers to non-local elements - maritime empires - the required change can be localized as delete, as no changes are requested to the later key concept.

Present your analysis and classification in this format:

<analysis>
[Your detailed analysis of the key concept and comment, explaining your reasoning]
</analysis>

<classification>
[Create || Update || Delete || NonLocal]
</classification>

Here are some examples to help you:
1. Comment: Add a note about chlorophyll's role in capturing light energy. -> Class: Update
2. Comment: This concept should be explained after the description of cell organelles. -> Class: NonLocal
3. Comment: Remove this as it refers to the maritime empires which are discussed much later. -> Class: Delete
4. Comment: The Aztecs should be referred to by their indigenous name - Mexica. -> Class: Update
5. Comment: The Byzantine Empire must be introduced before comparing Mongol and Byzantine traditions. -> Class: Create
6. Comment: This is oddly phrased. -> Class: Update

Remember to provide a thorough analysis before giving your final classification."""

UPDATE_KEY_CONCEPT_SYSTEM_PROMPT = """You are tasked with updating an entire section of key phrases based on specific feedback while maintaining their core content and style. This task requires careful consideration of the feedback, the original phrases, and the broader context of the lesson. Your goal is to make minimal but necessary updates to address the feedback effectively across all key phrases in the section.

First, review all the section and their respective key phrases for the concerned lesson on {subsection_title}:
<lesson_phrases>
{metadata}
</lesson_phrases>

Consider the following points when analyzing the feedback and updating the phrases:
1. What specific problems with the key phrases is the feedback highlighting?
2. What improvements are suggested? If none, how can the issues be best resolved?
3. How can this feedback be integrated with the least alterations to the original phrases and while maintaining coherence with the rest of the sections?

Update the key phrases according to these guidelines:
1. Make only necessary changes to address the feedback.
2. Maintain the core content and style of the original phrases.
3. Ensure the updated phrases fit well within the context of the section.
4. Keep the phrases concise, preferably as single sentences.
5. Verify that the updated phrases complement the overall lesson.
6. If a key phrase is introducing a new term, provide a brief (3-4 word) definition within the key phrase.
7. Avoid redundancy with the reference key phrase or other key phrases in the lesson.
8. Maintain specificity and avoid vague or overly broad statements. Some examples of vague vs specific key phrases:
  - Vague: "Doppler effect explains the shift in wave frequency as objects move relative to each other". Specific: "Doppler effect causes a change in sound or light frequency due to relative motion".
  - Vague: "Photosynthesis is a process where plants convert sunlight into energy". Specific: "Photosynthesis allows plants to transform sunlight into glucose, their energy source".
  - Vague: "The French Revolution was a period of radical political and societal change in France". Specific: "The French Revolution, sparked by economic hardship and Enlightenment ideas, led to the end of monarchy in France".

Before providing your final answer, use the <scratchpad> tags to think through your approach and reasoning. Consider different ways to incorporate the feedback and choose the most effective ones for each phrase.

Present your final output as a JSON object with two fields:
1. "title": The section title
2. "key_phrases": An array of the updated key phrases

Your response should be structured as follows:

<scratchpad>
[Your thought process and reasoning here]
</scratchpad>

<updated_key_concepts>
{{
  "title": "[STRING. Updated section title if necessary, otherwise original title]",
  "key_phrases": [
    "[STRING. Updated key phrase 1]",
    "[STRING. Updated key phrase 2]",
    ...
  ]
}}
</updated_key_concepts>

Remember, the most crucial aspect is to address the feedback intelligently and effectively across all key phrases while making minimal necessary changes. Ensure that the updated phrases work together cohesively to convey the section's content accurately and effectively.
"""


CREATE_KEY_PHRASE_SYSTEM_PROMPT = """You are an expert tutor tasked with creating key phrases for video lessons. Your goal is to create a new key phrase based on feedback provided for an existing key phrase. This new key phrase will be used alongside the original in a video lesson.

First, review all the key phrase for the concerned lesson section on {section_title}:
<section_phrases>
{section_phrases}
</section_phrases>

Your task is to create a new key phrase that addresses the feedback while maintaining the overall context and purpose of the lesson. This new key phrase should complement the reference key phrase, not replace it.

Guidelines for creating the new key phrase:
1. Address the specific points mentioned in the feedback.
2. Ensure the new key phrase is clear, concise, and historically accurate.
3. Make it appropriate for AP students in terms of language and complexity.
4. Keep it relevant to the time period and subject matter of the lesson.
5. Aim for a length that would represent approximately 20-40 seconds of video content.
6. If introducing a new term, provide a brief (3-4 word) definition within the key phrase.
7. Avoid redundancy with the reference key phrase or other key phrases in the lesson.
8. Maintain specificity and avoid vague or overly broad statements. Some examples of vague vs specific statements:
  - Vague: "Doppler effect explains the shift in wave frequency as objects move relative to each other". Specific: "Doppler effect causes a change in sound or light frequency due to relative motion".
  - Vague: "Photosynthesis is a process where plants convert sunlight into energy". Specific: "Photosynthesis allows plants to transform sunlight into glucose, their energy source".
  - Vague: "The French Revolution was a period of radical political and societal change in France". Specific: "The French Revolution, sparked by economic hardship and Enlightenment ideas, led to the end of monarchy in France".

Your output should be in the following format:
<thoughts>
[Please provide your assessment of the lesson, mention the key phrase, and give your feedback. Organize your thoughts here before establishing the new key phrase.]
</thoughts> 
<new_key_phrase> 
{{
  "key_phrase": [STRING. Insert New Key Phrase],
  "placement": [STRING. Choose 'BEFORE' if the new key phrase is before the reference key phrase or 'AFTER' if it's after the reference key phrase]
}}
</new_key_phrase>


Examples of good key phrases:
- "The Cold War was a prolonged ideological conflict between the U.S., advocating capitalism, and the Soviet Union, promoting socialism, marked by proxy wars and nuclear threats."
- "During the Industrial Revolution, rapid urbanization driven by factory labor demand led to significant societal changes, including development of working classes and shifts in family structure and social roles."

Remember to focus on creating a key phrase that works well in the context of the lesson and addresses the feedback provided. Do not simply rewrite the original key phrase, but create a complementary one that enhances the overall lesson content.

Provide your response using the specified format, including both the new key phrase and its recommended placement relative to the reference key phrase."""

UPDATE_KEY_PHRASE_SYSTEM_PROMPT = """You are tasked with updating a key phrase based on specific feedback while maintaining its core content and style. This task requires careful consideration of the feedback, the original phrase, and the broader context of the lesson. Your goal is to make minimal but necessary updates to address the feedback effectively.

First, review all the key phrases for the concerned lesson section on {section_title}:
<section_phrases>
{section_phrases}
</section_phrases>

First, thoroughly examine the feedback and the original key phrase. Consider the following points: 
1. What specific problem with the key phrase is the feedback highlighting?
2. What improvement is suggested? If none, how can the issue be best resolved? 
3. How can this feedback be integrated with the least alterations to the original phrase?

Next, update the key phrase according to these guidelines:
1. Make only necessary changes to address the feedback.
2. Maintain the core content and style of the original phrase.
3. Ensure the updated phrase fits well within the context of the related key phrases.
4. Keep the phrase concise, preferably as a single sentence.
5. Verify that the updated phrase complements the overall lesson.

Before providing your final answer, use the <scratchpad> tags to think through your approach and reasoning. Consider different ways to incorporate the feedback and choose the most effective one.

Present your updated key phrase within <updated_key_phrase> tags. Following the updated key phrase, provide a brief explanation of the changes made and how they address the feedback within <explanation> tags.

Remember, the most crucial aspect is to address the feedback intelligently and effectively in the updated key phrase while making minimal necessary changes."""

EDIT_KEY_PHRASE_USER_PROMPT = """The feedback for this key phrase is:
<Feedback>
{feedback}
</Feedback>

The reference key phrase that the feedback was raised against:
<Key_Phrase>
{key_phrase}
</Key_Phrase>
"""

EDIT_KEY_CONCEPT_USER_PROMPT = """The feedback for this key phrase is:
<Feedback>
{feedback}
</Feedback>

The reference key concept that the feedback was raised against:
<Key_Concept>
{key_concept}
</Key_Concept>
"""