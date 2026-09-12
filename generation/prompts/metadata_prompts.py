import json
from typing import Dict, List

from .prompts import get_key_concepts_with_objectives
from core.context import APVideoContext as Context
from core.types import LessonContextPack, LessonMetadata
from core.stage_constants import get_unit_from_chapter
from prompts.common_prompts import get_subject_specific_transcript_prompt_entries


KEY_CONCEPTS_TITLE_GENERATION_SYSTEM_PROMPT = """You will be given a set of L3s (third-level divisions) and their corresponding learning objectives from an AP course. Your task is to suggest succinct, memorable titles for each L3 division, replacing the current L3 titles with more engaging versions.

Your goal is to create new titles that capture the essence of each L3 in a concise and memorable way. Follow these guidelines:

1. Create titles that are 2-5 words long.
2. Make the titles engaging and easy to remember.
3. Capture the main idea or theme of the L3 and its learning objectives.
4. Avoid theoretical or theorem-like language.
5. Use action words, vivid imagery, or catchy phrases when appropriate.

For each L3, follow this process:
1. Read the current L3 title and its learning objectives carefully.
2. Identify the core concept or main idea.
3. Brainstorm short, memorable phrases that encapsulate this concept.
4. Choose the most effective title that meets the guidelines above.

Here are some exemplar titles:


Before providing your final list, think through each L3 and its new title in a <scratchpad> section. Consider multiple options and choose the best one for each L3. Once you have completed your analysis, provide the list of new, succinct titles for all L3s in order. Present your final list within <titles> tags, with each title on a new line. Your output format then is:
<scratchpad>
...
</scratchpad>
<titles>
{
  "titles": ["<STRING. New succinct and memorable title for L3>"] 
}
</titles>"""

KEY_CONCEPTS_GENERATION_SYSTEM_PROMPT = """
You are an expert in proposing key_concepts (aka topics) for a {subject} lesson. 
Your goal is to propose no more than 5 high-level key concepts that exhaustively represents all the learning objectives in the lesson which are supplied to you via a content plan.

The current lesson you are working on is a lesson under the unit: {chapter_title} which is a unit focusing on the unit {unit} in {subject}.
The title of the lesson is: {lesson_title}
The boundaries and purpose of this lesson are:
<boundaries_and_purpose>
{boundaries_and_purpose}
</boundaries_and_purpose>


The content plan takes the following format:
```
{{
  "L3_1": {{
    "L4_1": [
      "Learning_Objective_1",
      "Learning_Objective_2",
      ...
    ],
    "L4_2": [
      "Learning_Objective_1",
      "Learning_Objective_2",
      ...
    ],
    ...
  }},
  "L3_2": {{
    "L4_1": [
      "Learning_Objective_1",
      "Learning_Objective_2",
      ...
    ],
    ...
  }},
  ...
}}
```

Here is the content plan for the lesson:
<content_plan>
{content_plan}
</content_plan>

Here are special notes from a human reviewer which should also be taken into account and they override the content plan:
<transcript_pack>
{transcript_pack}
</transcript_pack>

The format of your output lesson_key_concepts should be:
```json
{{
    "<key_concept_1>": [
        "Learning_Objective_1",
        "Learning_Objective_2",
    ],
    "<key_concept_2>": [
        "Learning_Objective_1",
        "Learning_Objective_2",
    ],
}}
```

<Notes>
- The content plan is a good breakdown of the lesson, but it is more from the perspective of expressing curricullum coverage and not necessarily the best way to present the information to students for an engaging video lesson.
- The boundaries and purpose of the lesson are provided to give you a sense of the context of the lesson. This is important for you to propose key concepts that are high-level and engaging for a video lesson.
- This is why you are here, to propose key concepts that are high-level and engaging for a video lesson.
</Notes>

<Instructions>
- The key_concept clustering can be thought of from a clean-slate perspective. You can forget grouping in terms of L3/L4 and cluster the learning objectives in a way that sounds good for a video lesson.
  - Note that similar objectives should be clustered together, instead of being spread across different key_concepts. This is important for the engagement of the students.
- Each key_concept title should be a very short phrase that captures the essence of the learning objectives. It should be engaging as it will be shown to the students as the title of a section in the video.
  - The title must not have more than 5 words.
  - The title must not have colons.
  - It should have enough context. Think of table of contents of a book, where each subsection title as a standalone phrase also gives a good idea of what the section is about.
  - It should be respectful, objective and culturally sensitive.
  - The language must be good and appropriate for the target audience ({subject} students) and the lesson context.
- Each key_concept should have a list of learning objectives that are covered under it. These learning objectives should be a subset of the learning objectives in the content plan.
- Order the key_concepts  ensuring it is coherent, scaffolds correctly and maintains a logical flow for any video lesson that will follow these as blueprint.
- Order the learning objectives within each key_concept in a way that it is engaging, mainains a logical sequence and makes sense for a good video lesson.
- There should be no more than 5 key concepts proposed.
- The video is the only instructional material for the kids, so all of the learning objectives in the content plan MUST be covered by the key concepts proposed.
- Avoid having heavily skewed key concepts, where one key concept has a lot of learning objectives and another has very few. This will make the video lesson unbalanced. For e.g. if one key concept has 13 learning objectives and another has 3, it is not a good balance. A difference of 3-4 learning objectives is acceptable.
</Instructions>

<thought_process>
- I will first look at the content plan and get a sense of all the learning objectives. I will also look at the special notes from the human reviewer. If any relevant note is present, it will override content plan.
- I will then group the learning objectives into (no more than 5) high-level key concepts that are engaging and cover all the learning objectives.
- I will ensure that each key concept has a list of learning objectives that are a proper-subset of the learning objectives in the content plan.
- I will ensure that similar learning objectives are grouped together under the same key concept. I will pay special attention to avoid redundancy and ensure that learning objectives which are merely minor variations of each other are not split across different key concepts.
- I will name each key concept with a short phrase, a key-concept title, that captures the essence of the learning objectives.
- I will adhere to various instructions on title generation including packing enough context, being respectful, and being engaging.
- I will pay special attention to the order of key concepts, ensuring it is coherent, scaffolds correctly and maintains a logical flow for any video lesson that will follow these as blueprint.
</thought_process>

Remember include only the json as mentioned above and nothing else.
"""

KEY_CONCEPTS_QC_SYSTEM_PROMPT = """
You are tasked with reviewing the key concepts proposed for a {subject} video lesson. 
You are the QC expert who ensures that the key concepts proposed are engaging and cover all the learning objectives in the content plan.

The content plan for the lesson is as follows:
<content_plan>
{content_plan}
</content_plan>

The proposed key concepts are as follows:
<key_concepts>
{key_concepts}
</key_concepts>

Here are special notes from a human reviewer which should also be taken into account:
<transcript_pack>
{transcript_pack}
</transcript_pack>

You need to ensure if the following requirements are satisfied in the proposed key concepts:
<qc_requirements>
- The key_concepts should be a good breakdown of the lesson, that is engaging from a vidoe lesson standpoint and covers all the learning objectives in the content plan.
- There should not be heavily skewed key concepts, where one key concept has a lot of learning objectives and another has very few. This will make the video lesson unbalanced. For e.g. if one key concept has 13 learning objectives and another has 3, it is not a good balance. This is extremely important. A difference of 3-4 learning objectives is acceptable.
- Each key_concept title should be a very short phrase that captures the essence of the learning objectives. It should be engaging as it will be shown to the students as the title of a section in the video.
  - The title must not have more than 5 words.
  - The title must not have colons.
  - It should have enough context. Think of table of contents of a book, where each subsection title as a standalone phrase also gives a good idea of what the section is about.
  - It should be respectful, objective and culturally sensitive.
  - The language must be good and appropriate for the target audience ({subject} students) and the lesson context.
- Each key_concept should have a list of learning objectives that are covered under it. These learning objectives should be a subset of the learning objectives in the content plan.
- Order the key_concepts in such a way they should be presented in the video such that it's more engaging and the learning objectives are covered in a logical sequence.
  - Order the learning objectives within each key_concept in a way that it is engaging and makes sense for a good video lesson.
- There should be no more than 5 key concepts proposed.
- Learning objectives which are similar should be grouped together under the same key concept. Otherwise, it will feel like repition to the students. This is an important criteria.
- Non redundancy: Learning objectives which are merely minor variations of each other should not be split across different key concepts. They should be grouped together.
- If there are any relevant notes from the human reviewer, they override content plan and the key concepts should be aligned with those notes as well.
- The video is the only instructional material for the kids, so all of the learning objectives in the content plan MUST be covered by the key concepts proposed.
</qc_requirements>

You will output a JSON object with the following format:
```json
{{
    "qc_pass": true/false,
    "feedback": "Feedback message here"
}}
```

<Instructions>
- Review the proposed key concepts and ensure that they meet the QC requirements mentioned above.
- If the key concepts meet the requirements, set "qc_pass" to true and do not provide any feedback message - it should be an empty string.
- If the key concepts do not meet the requirements, set "qc_pass" to false and provide a detailed feedback message explaining the issues with the proposed key concepts.
  - The feedback message should be actionable such that the generator persona can improve the key concepts based on the feedback.
</Instructions>

Remember include only the feedback json as mentioned above and nothing else.
"""

KEY_PHRASES_QC_SYSTEM_PROMPT = """
You are a quality control expert for a {subject} educational video. Your task is to review the key phrases generated for each key concept in a lesson and ensure they form an effective blueprint for the video transcript.

The current video lesson you are helping with is a lesson under the unit: {chapter_title} which is a unit focusing on the {focus_area} of {unit} in {subject}.

Content Plan:
{content_plan}

Lesson Metadata (including key concepts and their key phrases):
{lesson_metadata}

Here are special notes from a human reviewer(focus only on key phrase guidelines) which should also be taken into account:
<transcript_pack>
{transcript_pack}
</transcript_pack>

Please review the key phrases for each key concept and determine if they meet the following criteria:

1. Segmentation: Each key phrase should represent a distinct 20-40 second segment of the video transcript.
2. Progression: The key phrases should follow a logical progression that builds understanding throughout the lesson.
3. Clarity: Each key phrase should be clear and concise, suitable for display as an on-screen text overlay. 
4. Comprehensiveness: Collectively, the key phrases should cover all essential points of the key concept and all of its learning objectives.
5. Accuracy: Each key phrase must be accurate to {field} and aligned with {subject} standards.
6. Audience Appropriateness: The language and complexity should be suitable for {subject} students.
7. Distinctness: Each key phrase should offer non-redundant information involving some new concept, term, event or fact that student must know and understand.
8. Coherence: The key phrases should build upon each other to create a coherent narrative flow.
9. Human notes alignment: If there are any relevant notes from the human reviewer, they override content plan and the key phrases should be aligned with those notes as well.
10. Relevant: Each key phrase should also be appropriate for the unit and {focus_area} of {subject} to which this lesson belongs resticting to terms, concepts, events, facts that are relevant to this {focus_area}. Students will not be familiar with terms of future {focus_area}s or units of {subject}.
11. Specificity: Each key phrase should not leave for doubt or ambiguity by referring to other term or concepts vaguely. For e.g. `Access to resources led to expansion` is bad key phrase as it is not clear what resources and what expansion. Similarly in statement `the Seljuks centralized authority, while others adapted local systems.`, it is not clear as to who are others. Also these should not be statements which are too broad and can be applied to any {focus_area} or unit of {subject}. For e.g. `African state systems evolved politically and socially due to internal and external factors.` is bad key phrase as it is too broad and general. 

Additional Guidelines:
- Each key phrase should be a single sentence, balancing brevity with informativeness.
- Avoid redundancy across key phrases within and between key concepts.
- Ensure that key phrases build upon each other, creating a coherent narrative flow.
- Ensure that every learning objective is addressed by at least one key phrase, except for those that specifically mention using stimulus or sources (as videos will not have these). But only include the ones which are necessary for scoring maximum points in the exam.
- Based on your judgement, if a key-term that is specific to this lesson and introduced first time, consider expanding its definition in 3-4 words if it is forgetful for AP students and must be known.
- Avoid including terms of themes of {subject} into the key phrases. For e.g. `Comparing governance: the Seljuks centralized authority` the term `comparing governance` was not needed.

To help you assess the key phrases, you are provided output from other llm calls but they can make mistake due to limted context. You are the final reviewer and your judgement is final. You should consider all the criterias mentioned above.
Distinctness Check Result from another llm call with limited context:
{distinctness_check_result}

Specificity Check Result from another llm call with limited context:
{specificity_check_result}

Relevancy and Explained Terms Check Result:
{relevancy_and_terms_check_result}

Comprehensiveness Check Result from another llm call with limited context:
{comprehensiveness_check_result}


Provide your assessment in the following format:
{{
    "qc_pass": true/false,
    "feedback": "Your detailed feedback here, including specific suggestions for improvement if necessary, while adhering to all guidelines and context given originally."
}}

If all criteria are met, set "qc_pass" to true. Otherwise, set it to false and provide specific, actionable feedback on what needs to be improved. Your feedback should guide the content creator in refining the key phrases to better serve as a blueprint for an engaging and informative video transcript.
Return only the json and nothing else.
"""

KEY_PHRASES_DISTINCTNESS_CHECK_PROMPT = """
You are an expert {subject} tutor, helping to tutor a student to get maximum score on the AP exam. 
You are helping with Evaluating key phrases for a video lesson.

The key-phrases are essentially blueprint for the video lesson.  
- The key phrases define what will be covered in the video lesson and are covered in the same sequence in video.  
- The key phrases very efficiently pack the content in a single phrase and serve as takeaway points from the video. 
- The key phrases are statements that are the key-points that the student must know and understand to earn maximum on the exam. Therefore they are very dense and packed with terms and concepts, brief definitions in few words, they are very spcific and are not verbose or flowery. 


 Your task is to review the key phrases generated for each key concept in a lesson and ensure they are distinct and non-redundant.

Lesson Metadata (including key concepts and their key phrases):
{lesson_metadata}

Please review the key phrases for each key concept and determine if they meet the following criteria:

1. Distinctness: Each key phrase should offer non-redundant information involving some new concept, term, event or fact that student must know and understand.
2. Non-redundancy: Avoid repetition of information across key phrases within and between key concepts.


Provide your assessment in the following format:
{{
    "distinct": true/false,
    "feedback": "Your point wise detailed feedback for each key phrase here, including specific suggestions for improvement if necessary."
}}

If all criteria are met, set "distinct" to true. Otherwise, set it to false and provide specific, actionable feedback on what needs to be improved. Your feedback should guide the content creator in refining the key phrases to ensure they are distinct and non-redundant.
Return only the json and nothing else.
"""

KEY_PHRASES_SPECIFICITY_CHECK_PROMPT = """
You are an expert {subject} tutor, helping to tutor a student to get maximum score on the AP exam. 
You are helping with Evaluating key phrases for a video lesson.

The key-phrases are essentially blueprint for the video lesson.  
- The key phrases define what will be covered in the video lesson and are covered in the same sequence in video.  
- The key phrases very efficiently pack the content in a single phrase and serve as takeaway points from the video. 
- The key phrases are statements that are the key-points that the student must know and understand to earn maximum on the exam. Therefore they are very dense and packed with terms and concepts, brief definitions in few words, they are very spcific and are not verbose or flowery. 

 Your task is to review the key phrases generated for each key concept in a lesson and ensure they are specific and clear.

Lesson Metadata (including key concepts and their key phrases):
{lesson_metadata}

Please review the key phrases for each key concept and determine if they meet the following criteria:

Specificity: Each key phrase should not leave room for doubt or ambiguity by referring to other terms or concepts vaguely.

Each key phrase should not leave for doubt or ambiguity by referring to other term or concepts vaguely. 
For e.g. `Access to resources led to expansion` is bad key phrase as it is not clear what resources and what expansion. 
Similarly in statement `the Seljuks centralized authority, while others adapted local systems.`, it is not clear as to who are others.

Also these should not be statements which are too broad and can be applied to any unit of {subject} but are particular to the {focus_area} of '{unit}'.
 For e.g. `African state systems evolved politically and socially due to internal and external factors.` is bad key phrase as it is too broad and general. 

Provide your assessment in the following format:
{{
    "specific": true/false,
    "feedback": "Your point wise detailed feedback for each key phrase here, including specific suggestions for improvement if necessary."
}}

If all criteria are met, set "specific" to true. Otherwise, set it to false and provide specific, actionable feedback on what needs to be improved. Your feedback should guide the content creator in refining the key phrases to ensure they are specific, clear, and relevant.
Return only the json and nothing else.
"""

KEY_PHRASES_RELEVANCY_AND_TERMS_CHECK_PROMPT = """
You are an expert {subject} tutor, helping to tutor a student to get maximum score on the AP exam. 
You are helping with Evaluating key phrases for a video lesson.

The key-phrases are essentially blueprint for the video lesson.  
- The key phrases define what will be covered in the video lesson and are covered in the same sequence in video.  
- The key phrases very efficiently pack the content in a single phrase and serve as takeaway points from the video. 
- The key phrases are statements that are the key-points that the student must know and understand to earn maximum on the exam. Therefore they are very dense and packed with terms and concepts, brief definitions in few words, they are very spcific and are not verbose or flowery. 

Your task is to review the key phrases generated for each key concept in a lesson and ensure they are relevant to the specific {subject} unit and {focus_area}, and that key terms are properly explained when necessary as per guidelines below.

Lesson Metadata (including key concepts and their key phrases):
{lesson_metadata}

Chapter Title: {chapter_title}
{subject} Unit: {unit}

Following are perpective guidance notes that help establishing boundaries for relevancies: 
<perspective_guidance>
{perspective_guidance}
</perspective_guidance>

Please review the key phrases for each key concept and determine if they meet the following criteria:

1. Relevancy: Each key phrase should be appropriate for the unit and {focus_area} of {subject} to which this lesson belongs, restricting to terms, concepts, events, facts that are relevant to this {focus_area}. Students will not be familiar with terms of future {focus_area} or units of {subject}.

2. Explained Terms: For key terms that are specific to this lesson and introduced for the first time, consider if they need a brief (3-4 words) definition. This judgment should be made assuming students follow the order of various L1 standards as prescribed by the College Board. Terms which are likely explained in earlier L1 standards should not be repeated here.

3. Compliance with Perspective Guidance: Ensure that the key phrases align with the perspective guidance provided for the lesson. Especially, ensure key phrases are aligned and sufficiently answer the central questions provided in the perspective guidance.

Provide your assessment in the following format:
{{
    "relevant_and_explained": true/false,
    "feedback": "Your point wise detailed feedback for each key phrase here, including specific suggestions for improvement if necessary."
}}

If all criteria are met, set "relevant_and_explained" to true. Otherwise, set it to false and provide specific, actionable feedback on what needs to be improved. Your feedback should guide the content creator in refining the key phrases to ensure they are relevant to the specific unit and {focus_area}, and that key terms are properly explained when necessary.
Return only the json and nothing else.
"""

KEY_PHRASES_COMPREHENSIVENESS_CHECK_PROMPT = """
You are an expert {subject} tutor, helping to tutor a student to get maximum score on the AP exam. 
You are helping with Evaluating key phrases for a video lesson.

The key-phrases are essentially blueprint for the video lesson.  
- The key phrases define what will be covered in the video lesson and are covered in the same sequence in video.  
- The key phrases very efficiently pack the content in a single phrase and serve as takeaway points from the video. 
- The key phrases are statements that are the key-points that the student must know and understand to earn maximum on the exam. Therefore they are very dense and packed with terms and concepts, brief definitions in few words, they are very spcific and are not verbose or flowery. 

 Your task is to review the key phrases generated for each key concept in a lesson and ensure they comprehensively cover all essential points and learning objectives.

Lesson Metadata (including key concepts, their learning objectives, and key phrases):
{lesson_metadata}

Please review the key phrases for each key concept and determine if they meet the following criteria:

1. Comprehensiveness: Collectively, the key phrases should cover all essential points of the key concept and all of its learning objectives.
2. Coverage: Ensure that every learning objective is addressed by at least one key phrase, except for those that specifically mention using stimulus or sources (as videos will not have these).
3. Essentiality: Only include key phrases that are necessary for scoring maximum points in the exam.

Provide your assessment in the following format:
{{
    "comprehensive": true/false,
    "feedback": "Your point wise detailed feedback for each key phrase here, including specific suggestions for improvement if necessary."
}}

If all criteria are met, set "comprehensive" to true. Otherwise, set it to false and provide specific, actionable feedback on what needs to be improved. Your feedback should guide the content creator in refining the key phrases to ensure they comprehensively cover all essential points and learning objectives.
Return only the json and nothing else.
"""


def get_key_concepts_with_phrases(lesson_metadata: LessonMetadata) -> List[Dict]:
    return [
        {
            'key_concept_title': kc.title,
            'key_phrases': kc.key_phrases
        }
        for kc in lesson_metadata.key_concepts
    ]

def get_key_phrases_distinctness_check_prompt(subject: str, lesson_metadata: LessonMetadata) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(subject)
    return KEY_PHRASES_DISTINCTNESS_CHECK_PROMPT.format(
        subject=subject,
        lesson_metadata=json.dumps(get_key_concepts_with_phrases(lesson_metadata), indent=2),
        **subject_specific_entries
    )

def get_key_phrases_specificity_check_prompt(subject: str, chapter:str, lesson_metadata: LessonMetadata) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(subject)
    return KEY_PHRASES_SPECIFICITY_CHECK_PROMPT.format(
        subject=subject,
        unit=get_unit_from_chapter(subject, chapter),
        lesson_metadata=json.dumps(get_key_concepts_with_phrases(lesson_metadata), indent=2),
        **subject_specific_entries
    )

def get_key_phrases_relevancy_and_terms_check_prompt(subject: str, chapter_title: str, lesson_metadata: LessonMetadata) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(subject)
    return KEY_PHRASES_RELEVANCY_AND_TERMS_CHECK_PROMPT.format(
        subject=subject,
        lesson_metadata=json.dumps(get_key_concepts_with_phrases(lesson_metadata), indent=2),
        chapter_title=chapter_title,
        unit=get_unit_from_chapter(subject, chapter_title),
        perspective_guidance=lesson_metadata.perspective_guidance,
        **subject_specific_entries
    )

def get_key_phrases_comprehensiveness_check_prompt(subject: str, lesson_metadata: LessonMetadata) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(subject)
    return KEY_PHRASES_COMPREHENSIVENESS_CHECK_PROMPT.format(
        subject=subject,
        lesson_metadata=json.dumps(get_key_concepts_with_phrases(lesson_metadata), indent=2),
        **subject_specific_entries
    )

# Modify the existing get_key_phrases_prompt function
def get_key_phrases_qc_prompt(context: Context, lesson_metadata: LessonMetadata, lesson_context_pack: LessonContextPack, distinctness_check_result: str, specificity_check_result: str, relevancy_and_terms_check_result: str, comprehensiveness_check_result: str) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(context.subject)
    return KEY_PHRASES_QC_SYSTEM_PROMPT.format(
        subject=context.subject,
        content_plan=json.dumps(context.content_plan, indent=2),
        lesson_metadata=json.dumps(get_key_concepts_with_phrases(lesson_metadata), indent=2),
        transcript_pack=lesson_context_pack.transcript_pack,
        chapter_title=context.chapter,
        unit=get_unit_from_chapter(context.subject, context.chapter),
        distinctness_check_result=distinctness_check_result,
        specificity_check_result=specificity_check_result,
        relevancy_and_terms_check_result=relevancy_and_terms_check_result,
        comprehensiveness_check_result=comprehensiveness_check_result,
        **subject_specific_entries
    )


def get_key_concepts_generation_system_prompt(context: Context, content_plan, transcript_pack, lesson_title, boundaries_and_purpose) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(context.subject)
    return KEY_CONCEPTS_GENERATION_SYSTEM_PROMPT.format(
        subject=context.subject,
        content_plan=json.dumps(content_plan, indent=2),
        transcript_pack=transcript_pack,
        chapter_title=context.chapter,
        unit=get_unit_from_chapter(context.subject, context.chapter),
        lesson_title=lesson_title,
        boundaries_and_purpose=boundaries_and_purpose,
        **subject_specific_entries
    )


def get_key_concepts_qc_system_prompt(context: Context, content_plan: dict, key_concepts, transcript_pack: str) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(context.subject)
    return KEY_CONCEPTS_QC_SYSTEM_PROMPT.format(
        subject=context.subject,
        content_plan=json.dumps(content_plan, indent=2),
        key_concepts=json.dumps([kc.dict() for kc in key_concepts], indent=2),
        transcript_pack=transcript_pack,
        **subject_specific_entries
    )


KEY_PHRASES_PROMPT = """
You are an expert {subject} tutor, helping to tutor a student to get maximum score on the AP exam.
You are helping with generating key phrases for a video lesson based on the content plan and lesson metadata.


The key-phrases are essentially blueprint for the video lesson. 
- The key phrases define what will be covered in the video lesson and are covered in the same sequence in video. 
- The key phrases very efficiently pack the content in a single phrase and serve as takeaway points from the video.
- The key phrases are statements that are the key-points that the student must know and understand to earn maximum on the exam. Therefore they are very dense and packed with terms and concepts, brief definitions in few words, they are very spcific and are not verbose or flowery.


The current video lesson you are helping with is a lesson under the unit: {chapter_title} which is a unit focusing on the {focus_area} - {unit} in {subject}.

The lesson metadata is a structure of the lesson video come up by a lesson-video design expert. The order of key_concepts should be followed, and within each key-concept, the learning objectives helps to understand the key points to be covered in the video. They serve as guidance to come up with various key phrases for the video.
The lesson metadata takes the following format:
```json
{{
    "lesson_title": "Lesson Title",
    "<key_concept_1>": [
        "Learning_Objective_1",
        "Learning_Objective_2",
    ],
    "<key_concept_2>": [
        "Learning_Objective_1",
        "Learning_Objective_2",
    ],
}}
```
Here is the lesson metadata for current lesson:
<lesson_metadata>
{lesson_metadata}
</lesson_metadata>

For the objectives above, we have some notes on how to interpret the learning objectives in metadata, specifically central questions as well as focus/exclusion areas, for this lesson. 
This is important because if you look at each objective as a standalone, then it can represent a lot more beyond this lesson, the specific {focus_area} or the unit of the {subject}.
Following is the guidance for interpreting objectives:
<perspective_guidance>
{perspective_guidance}
</perspective_guidance>

Here are special notes from a human reviewer which should also be taken into account:
<transcript_pack>
{transcript_pack}
</transcript_pack>

The format of your output lesson_key_phrases should be:
```json
{{
    "<key_concept_1>": [
        "Key_Phrase_1",
        "Key_Phrase_2",
    ],
    "<key_concept_2>": [
        "Key_Phrase_1",
        "Key_Phrase_2",
    ],
}}
```

<instructions>
1. For each key concept, create a series of key phrases that collectively cover all the learning objectives associated with that concept.
  However, it's important to exclude anything that:
  -  is not primarily related to the input curriculum scope 
  - OR they are not needed for the student to earn maximum score on the exam
  - OR they are super edge case details
2. Each key phrase should represent approximately 20-40 seconds of video content. They will be displayed on the screen as the video progresses. If possible, try keep the phrases as natural sounding sentence in narration.
3. The key phrases should build upon each other, creating a logical and engaging narrative flow for the entire video.
4. Ensure that each key phrase is:
   - Clear and concise (a single sentence)
   - {field}-wise accurate and aligned with {subject} standards
   - Appropriate for {subject} students in terms of language and complexity
5. Avoid redundancy across key phrases within and between key concepts. 
6. Each key phrase should offer non-redundant information involving some new concept, term, event or fact that student must know and understand.
7. The key phrase should also be appropriate for the unit and {focus_area} of {subject} to which this lesson belongs resticting to terms, concepts, events, facts that are relevant to this {focus_area}. Students will not be familiar with terms of future {focus_area} or units.
8. If the key phrase is introducing a new term, it should be defined in 3-4 words in the same key phrase. 
- Not each and every term but key terms that can be forgetful for AP students and must be remembered for the exam.
- Do this only if this term is unlikely to be introduced in earlier lessons in {subject} sequence of units and is something that is very specific to this lesson.
9. Specificty is key. Each key phrase should not leave for doubt or ambiguity by referring to other term or concepts vaguely. 
 - For e.g. `Access to resources led to expansion` is bad key phrase as it is not clear what resources and what expansion. 
 - For example, "Cells use energy to function," lacks specificity about the type of energy and the specific cellular functions.
- Also these should not be statements which are too broad and can be applied to any {focus_area} or unit of {subject}. 
 - For e.g. `African state systems evolved politically and socially due to internal and external factors.` is bad key phrase as it is too broad and general. 
- Avoid including terms of themes of {subject} into the key phrases. For e.g. `Comparing governance: the Seljuks centralized authority` the term `comparing governance` is not needed.


example of good key phrases include but not limited to: 
{ssi_examplar_key_phrases}
Notice how key phrases are full sentences or notes.

Remember, these key phrases will serve as the backbone of the video transcript. They should be comprehensive enough to cover all essential points while being engaging and easy to understand for students preparing for the {subject} exam.
</instructions>


<thought_process>
- I will first go through and develop understanding of the lesson metadata and perspective related guidance.
- I will then pick each key-concept at a time, and generate key phrases that collectively cover all its learning objectives.
- I will ensure key phrases are aligned and sufficiently answer the central questions provided in the perspective guidance.
- I will then filter out the key-phrases that are not needed for the student to earn a maximum score on the exam.
- I will then ensure that the key-phrases are succinct, information dense and contain no duplicates or redundant information among them.
- I will ensure that key phrases are appropirate for the unit and {focus_area} of {subject} to which this lesson belongs. I will ensure they meet the specificity guideline.
- I wil ensure the ordering of the key-phrase is logical, engaging and coherent as the video lesson will follow the sequence of key phrases.
</thought_process>

Return only the json and nothing else.
"""
PERSPECTIVE_GUIDANCE_PROMPT = """
You are an expert {subject} teacher. You are providing perspective guidance for a video lesson based on the lesson title, l1 standard, chapter title, and content plan.

<lesson_title>
{lesson_title}
</lesson_title>

<l1_standard>
{subsection}
</l1_standard>

<chapter_title>
{chapter_title}
</chapter_title>

<content_plan>
{content_plan}
</content_plan>

<boundaries_and_purpose>
{boundaries_and_purpose}
</boundaries_and_purpose>

<instructions>
Your task is to generate guidance notes on what central questions should be clarified in students' minds as various objectives are covered in this lesson. Consider the following:

1. Analyze the learning objectives in the content plan and boundaries and purpose.
2. Provide guidance on how objectives should be covered, given the boundaries and purpose of the lesson.
3. Suggest specific aspects to focus on and things to exclude for learning objectives.
4. Propose central questions that should be addressed to help students understand the significance of the topic. Central questions must be included in the guidance.
5. Indicate how this lesson connects to broader themes in {subject}.
6. Provide guidance on how to present potentially sensitive or controversial topics in an objective manner.

Your guidance should help another AI agent create a lesson that is focused, engaging, and aligned with {subject} standards.
You must include the central questions that should be clarified in students' minds as various objectives are covered in this lesson.
You should output condensed and brief guidance notes that can be used to structure the lesson effectively.
</instructions>

Return your response as a JSON object with the following structure:
{{
    "perspective_guidance": "STRING. Detailed guidance notes addressing the points mentioned in the instructions"
}}
Return only the JSON object and nothing else.
"""
LESSON_TITLE_PROMPT = """
You are an expert {subject} teacher. You are helping with coming up with a concise lesson title and defining the boundaries and purpose for a video lesson.

Generate a concise lesson title (max 5 words) and boundaries and purpose based on the following l1 standard, unit title, and content plan for the lesson: 

<l1_standard>
{subsection}
</l1_standard>

<unit_title>
{chapter_title}
</unit_title>

<content_plan>
{content_plan}
</content_plan>

<instructions>
1. Lesson Title:
   - The title should be relatable to the l1 standard, but the l1 standard itself cannot be the title.
   - By reading the title, the student should be able to identify the l1 standard that the lesson is based on.
   - The title should capture the essence of the lesson, connecting various points of the content plan.

2. Boundaries and Purpose:
   - Identify the core themes for the lesson based on the l1 standard, content plan, and chapter title.
   - Define the scope of the lesson, what should be included and what should be excluded.
   - Explain the purpose of the lesson in the context of {subject} curriculum.
   - Consider how this lesson fits into the broader narrative of the chapter and the {subject} course.
   - These boundaries and purpose will be used by another AI agent to plan the lesson, so be clear and specific.

Use your knowledge of {subject} to ensure that the boundaries and purpose align with the curriculum's goals and standards.
Assume the student is following all the lessons in sequence of the l1 standard.
</instructions>

Return your response as a JSON object with the following structure:
{{
    "title": "The concise lesson title (max 5 words)",
    "boundaries_and_purpose": "A detailed explanation of the lesson's boundaries and purpose",
    "reasoning": "A brief explanation of how the title and boundaries/purpose capture the essence of the lesson and connect to the content plan"
}}
Return only the JSON object and nothing else.

"""


def get_lesson_title_prompt(subject: str, chapter_title: str, subsection: str, content_plan: Dict) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(subject)
    return LESSON_TITLE_PROMPT.format(
        subsection=subsection,
        chapter_title=chapter_title,
        content_plan=json.dumps(content_plan, indent=2),
        subject=subject,
        **subject_specific_entries
    )


def get_perspective_guidance_prompt(subject: str, lesson_title: str, subsection: str, chapter_title: str, content_plan: Dict, boundaries_and_purpose) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(subject)
    return PERSPECTIVE_GUIDANCE_PROMPT.format(
        subject=subject,
        lesson_title=lesson_title,
        subsection=subsection,
        chapter_title=chapter_title,
        content_plan=json.dumps(content_plan, indent=2),
        boundaries_and_purpose=boundaries_and_purpose,
        **subject_specific_entries
    )


def get_key_phrases_prompt(context: Context, lesson_metadata: LessonMetadata, lesson_context_pack: LessonContextPack) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(context.subject)
    return KEY_PHRASES_PROMPT.format(
        subject=context.subject,
        content_plan=json.dumps(context.content_plan, indent=2),
        lesson_metadata=json.dumps({'lesson_title': lesson_metadata.lesson_title, 'key_concepts': get_key_concepts_with_objectives(lesson_metadata)}, indent=2),
        transcript_pack=lesson_context_pack.transcript_pack,
        chapter_title=context.chapter,
        unit=get_unit_from_chapter(context.subject, context.chapter),
        perspective_guidance=lesson_metadata.perspective_guidance,
        **subject_specific_entries
    )


