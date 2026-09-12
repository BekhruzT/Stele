from typing import Dict, List
import json

from core.types import LessonMetadataWithContext

def get_suggest_improvements_prompt(chapter_title: str, current_subsection_title: str, processed_lessons: List[LessonMetadataWithContext], current_lesson: LessonMetadataWithContext, potential_redundancies: List[Dict[str, str]]) -> str:
    return f"""
You are an expert reviewer for in {current_lesson.context.course}. You are helping improve key-phrases of all the lessons (by correcting redundant phrases) in {chapter_title} taking into account the full context and high level view of the entire chapter.

There is one to one correspondence between lessons and l1-standard of {current_lesson.context.course}. Infact, the l1-standard is the title of the lesson. That already gives you lot of context on what the boundaries of the lesson are.

The key-phrases are essentially blueprint for the video lesson.  
- The key phrases define what will be covered in the video lesson and are covered in the same sequence in video.  
- The key phrases very efficiently pack the content in a single phrase and serve as takeaway points from the video. 
- The key phrases are statements that are the key-points that the student must know and understand to earn maximum on the exam. Therefore they are very dense and packed with terms and concepts, brief definitions in few words, they are very spcific and are not verbose or flowery. 

Here is the dump of all the key-phrases developed till now along with learning objectives of various key concepts of that lesson. They will help you understand the context and points being covered in the chapter.
The last lesson is the current lesson which is titled {current_subsection_title}.
<all_lessons_context>
{json.dumps([{'subsection': lesson.context.subsection, 'metadata': lesson.metadata.dict()} for lesson in processed_lessons] + [{'subsection': current_subsection_title, 'metadata': current_lesson.metadata.dict()}], indent=2)}
</all_lessons_context>

To do quality work and help you focus, you are given a list of potential redundancies found by semantic similarity in the lessons of {chapter_title}. They are supplied with lesson names.
Currently we focus only on these supplied set of redundancies as potential problem areas. 
We evaluate whether they need to be changed or not. If they need changes, we suggest what changes to make.

<potential_redundancies>
{json.dumps(potential_redundancies, indent=2)}
</potential_redundancies>

Suggest specific improvements to address these redundancies. Consider changes to any lesson, not just the current or last one.
Take into account the learning objectives provided for each redundant pair when suggesting improvements.
<strategy>
- For each redundant pair, first identify which lesson they belong to, identify which lesson is earlier and which is later in the chapter. Also understand the learning objectives, key-concepts and key-phrases of both the lessons.
- If a phrase is redundant and part of earlier lesson in the pair (identified by order of l1 standard in {current_lesson.context.course} curriculum), it either does not belong to that lesson or it is covering more than it should in that lesson. Depending on the other phrases in that lesson, you can decide to either delete it or replace it via rewrite with another appropriate phrase to fit in the lesson.
- If a phrase is redundant and part of latter lesson in the pair, it either does not belong to the cluster/l1-standard of that lesson (in which case it should be deleted) or it is not truly covering the nuanced aspect of the topic that learning objective of that lesson is trying to achieve(in which case it should be replaced with another more apppropriate phrase). 
- For e.g. if learning objectives of different lessons are motivation of Marshall plan and impact of Marshall plan respectively, yet the redundant phrases briefly discuss Marshall plan, you can then rewrite the phrases discussing countering soviet influence as motivation and restoration of infrastructure/industries in europe among various other things as impact.
- Depending on the case, you might alter both the phrases in the pair or alter only one phrase.
</strategy>

<quality_criteria>
- Each phrase should be something that student must know and understand to earn maximum on the exam. We want to be efficient and not include unnecessary details.
- Each key phrase should offer non-redundant information involving some new concept, term, event or fact that student must know and understand.
- Specificity: Each key phrase should not leave room for doubt or ambiguity by referring to other terms or concepts vaguely.
For e.g. `Access to resources led to expansion` is bad key phrase as it is not clear what resources and what expansion. 
Similarly in statement `the Seljuks centralized authority, while others adapted local systems.`, it is not clear as to who are others.
Also these should not be statements which are too broad and can be applied to any period or unit of the subject.
For e.g. `African state systems evolved politically and socially due to internal and external factors.` is bad key phrase as it is too broad and general. 
- Explained Terms: For key terms that are specific to this lesson and introduced for the first time, consider if they need a brief (3-4 words) definition. This judgment should be made assuming students follow the order of various L1 standards as prescribed by the College Board. Terms which are likely explained in earlier L1 standards should not be repeated here.
</quality_criteria>

Provide your suggestions in the following JSON format:
{{
    "improvements": [
        {{
            "lesson": "Subsection title of the lesson to be modified",
            "related_learning_objectives": "Learning objectives related to the key-phrase or key-concept being improved",
            "thought_process": "Your thought process for the change considering the learning objectives and other key-phrases in the lesson . Explain your reason for either why something was out of place or why something was not achieving the nuanced aspect of the topic that learning objective of that lesson is trying to achieve or why something was missing",
            "type": "rewrite|delete|add",
            "target": "key_phrase|key_concept",
            "original": "Original text (if applicable)",
            "suggested": "Suggested change (if applicable)",
            "placement": {{
                "target_phrase": "Existing phrase to place the new phrase relative to (for 'add' type only)",
                "position": "before|after (for 'add' type only)"
            }}
        }}
    ]
}}

Be surgical and specific in your suggestions. Only suggest changes if they significantly improve the lesson's quality and coherence within the chapter.
Ensure that your suggestions align with the learning objectives of the lessons involved.
For 'add' type improvements, always specify a target phrase and whether to add before or after it.
Return only the json and nothing else.
    """

def get_verify_changes_prompt(chapter_title: str, current_subsection_title: str, processed_lessons: List[LessonMetadataWithContext], current_lesson: LessonMetadataWithContext, improvements: List[Dict]) -> str:
    return f"""
You are verifying the following proposed changes for the lessons in {chapter_title}:

{json.dumps(improvements, indent=2)}

All lessons context (including the current lesson):
{json.dumps([{'subsection': lesson.context.subsection, 'metadata': lesson.metadata.dict()} for lesson in processed_lessons] + [{'subsection': current_subsection_title, 'metadata': current_lesson.metadata.dict()}], indent=2)}

Verify that these changes maintain the integrity of all lessons and improve the overall coherence of the chapter.

Provide your verification in the following JSON format:
{{
    "changes_approved": true/false,
    "verification": "A String. Your detailed verification, explaining why changes are approved or not"
}}

Be critical in your verification, ensuring that the proposed changes truly enhance the quality and coherence of the lessons.
"""
