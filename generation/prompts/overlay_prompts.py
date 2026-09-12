import os

from core.types import \
    DiagramType
from core.clients.openai import assistant_message, user_message

DISABLE_TREE_DESCRIPTION = os.getenv('DISABLE_TREE_DESCRIPTION', 'false')

BULLET_TITLE_TRIGGER_SYSTEM = """
You are an AI assistant tasked with identifying the exact words used in a sentence corresponding to a title, given the list of titles and the sentence. The sentence speaks out the list of titles, it might use the exact same words as in the title or slightly different. Your job is to identify what words it uses for each title.
"""

BULLET_TITLE_TRIGGER_USER = """
Given the following list of titles and the sentence, identify the exact words used in the sentence that correspond to each title.

List of titles:
<titles>
{titles}
</titles>

Sentence:
<sentence>
{sentence}
</sentence>

Return a JSON object with the following structure:
{{
    "<exact_title_from_the_list_of_titles>": "<exact_words_used_in_the_sentence_that_correspond_to_the_title>"
}}
Return only the JSON object and nothing else.
"""

BULLET_POINT_SYSTEM = """
You are an AI assistant tasked with creating concise bullet points for conclusion slide of an educational video. The educational video is aimed at students preparing for the AP exam. Your goal is to summarize the key takeaways in a way that maximizes student retention and understanding. You'll be given conclusion_text which is the transcript of the conclusion part of the video which the speaker will be speaking when we display our conclusion slide. You'll also be given a list of topics covered in the lesson. Each topic has a title and key phrases. The title of the lesson is also provided. Incorporate all of these in the bullet points you create.
"""

BULLET_POINT_USER = """
Based on the provided conclusion text, lesson title, and topics list, generate bullet points to be displayed on-screen for students. These points should encapsulate the most crucial information to aid in retention.

You are given:
title: The title of the lesson.
conclusion_text: The transcript that will be spoken when the conclusion slide is displayed.
topics: The list of topics covered in the lesson with their titles and key phrases.
Key phrases are the list of important phrases that the host will speak in that topic that students must remember.

Important Instructions:
- The bullet points will serve as memory aids for students to remember the key takeaways from the lesson.
- These are not review notes, but aids to help students recall key points that they have already learned.
- As a memory aid, every word counts. Avoid unnecessary words or stating the obvious.
- Create one bullet point for each topic in the topic list. The bullet point should include key terms or examples that students must remember for the exam.
- Include important words from the key phrases of that topic in the bullet point.
- The bullet points should follow the same order as the topics in the topic list.
- Use title case throughout.
- You will return a JSON with key as the topic name and value as the bullet point. The keys should exactly match the topic names in the topic list.

Lesson Title:
<title>
{title}
</title>

Conclusion Text:
<conclusion_text>
{conclusion_text}
</conclusion_text>

Topic List:
<topics>
{topics}
</topics>

Return your response as a JSON object with the following structure:
{{
    "bullet_points": [
        "<1 Topic Name>": "<Examples or Supporting Points>",
        "<2 Topic Name>": "<Examples or Supporting Points>",
        ...
    ]
}}
Only return the JSON object.
"""


TOPIC_TRANSITION_SYSTEM = """
You are an AI assistant tasked with identifying the exact moment in a section overview where the section title is introduced. Each section in an educational video has an overview that introduces what will be covered in that section. Your goal is to find the exact sentence and phrase where the section title is mentioned or closely paraphrased in the overview text.
"""

TOPIC_TRANSITION_USER = """
Please analyze the following section overview and identify where the section title is introduced. The section title may not appear verbatim in the overview - it might be paraphrased or described differently.
you need to:
- Identify the trigger sentence for section title. This is the sentence that signal the start of a new topic.
- Identify the trigger phrase for section title. This is the exact set of words within the trigger sentence that 
corresponds to the name of the new topic.

Section Title:
<section_title>
{section_title}
</section_title>

Section Overview:
<section_overview>
{overview}
</section_overview>

Important Instructions:
- The "trigger_sentence" must be an exact match to a sentence from the overview that introduces or references the section title
- The "trigger_phrase" must be an exact match to words within the trigger sentence that most closely correspond to the section title
- If you cannot find an exact match for the section title, look for phrases that convey the same meaning
- The phrase must appear in the exact form in the transcript - do not modify or paraphrase it

Respond with a JSON object in the following format:
{{
    "trigger_sentence": "The exact verbatim sentence that introduces the section title",
    "trigger_phrase": "The exact verbatim set of words within the trigger_sentence that corresponds to the section title"
}}
Please return only the JSON object and nothing else.
"""

KEY_PHRASE_SYSTEM = """
You are an AI assistant tasked with matching key phrases to corresponding verbatim sentences/phrases from a transcript for an educational video, aimed at students preparing for the AP exam. There are certain 'key phrases' that are very important sentences for the students to remember. These will be spoken by the host of the video and will get overlayed on the video while they are spoken, to aid in student retention. Now we already have the transcript and the list of key phrases. The task is to identify at which sentence/phrase of the transcript the key phrase is being spoken. Your goal is to find the closest verbatim sentence/phrase from the transcript which correspond to the particular key phrase for each of the key phrases (it will be almost exactly the same as the key phrase but might have some very slight variations).
"""

KEY_PHRASE_USER = """
Given the following transcript and the list of key phrases, identify the verbatim sentence/phrase that correspond/match with each of the key phrases.

Important Instructions:
<instructions>
- You have to return a JSON which will have "phrase" and "verbatim_phrase" as keys for each of the key phrases. Don't leave out any key phrases.
- The "phrase" is the key phrase that you are provided and must match exactly be a key phrase from the list of key phrases provided.
- The key phrase will most likely be directly spoken in the transcript, if not it varies very slightly. You have to find the sentence from the transcript that matches the key phrase almost exactly (because it might slightly vary from the key phrase). Carefully identify it. This will be the "verbatim_phrase".
- The "verbatim_phrase" must exactly be a verbatim sentence/phrase from the transcript. The words, the punctuation, the case should all match. It's like you are copying a sentence/phrase from the transcript directly.
- No 2 verbatim_phrase should overlap with each other strictly. Each key phrase should have a unique verbatim_phrase.
</instructions>

Transcript:
<transcript>
{transcript}
</transcript>

Key phrases:
<key_phrases>
{key_phrases}
</key_phrases>

Return a JSON object with the following structure:
{{
    "key_phrases": [
        {{
            "phrase": "The exact key phrase that you are provided in the list of key phrases",
            "verbatim_phrase": "The exact verbatim sentence/phrase from the transcript that corresponds to the key phrase (it will be almost exactly the same as the key phrase but might have some very slight variations)",
        }},
        ...
    ]
}}
Return only the JSON object and nothing else.
"""


CORRECT_VERBATIM_PHRASE_USER = """
Given the following transcript,

Transcript segments:
<transcript>
{segments}
</transcript>

Pick one single sentecne from the transcript (the dialogues) that is most identical to the following sentence:
<sentence>
{phrase}
</sentence>

Return only the sentence in plain text and nothing else.
"""


IDENTIFY_BULLET_POINT_TRIGGER_WORD = """As a content editor for online lessons, your role is to synchronize bullet point text reveals with the corresponding spoken phrases from the transcript. The aim is to align each bullet point with the precise phrase and word that should trigger its appearance, creating a smooth integration of text and narration.

### Instructions
- Strategically align each bullet point with the corresponding phrase where the text should appear. Identify the exact word within the phrase that initiates the text reveal.
- Prioritize the first phrase that pertains to a given bullet point.
- The trigger word cannot be a verb. It can be:
  - A key term or concept mentioned in the bullet point
  - A reference to data, numerical values, or variables related to the bullet point content
  - A transition word or phrase that introduces a new idea or concept
- Trigger words CANNOT be: discuss, explain, mention, list, etc.
- Determine the exact word that should reveal the bullet point text. For instance:
  - In the phrase 'Let's discuss the three main causes of climate change.', the word 'causes' triggers the appearance of the 'Causes' header for the bullet point list.
- The bullet point should only appear once all the necessary context for the point has been provided. Here are some examples:
  - In the sentence, 'The first principle of economics we'll cover is scarcity', the bullet point reveal is triggered by the word 'scarcity'. This is because 'principle' is mentioned before the specific concept is named; 'first' is not specific enough; 'economics' is too general. However, if the bullet point starts with a general account mentioning Principles of Economics, the trigger word is 'Economics'.
  - In the sentence, 'Next up were Navigational Technologies, the compass and the astrolabe...', if the general theme of technologies is mentioned, the trigger word is 'Navigational'.
  - In the sentence, 'In addition, Improved Commercial Practices came along like credit, paper money, and standardized...' and the bullet point is 'Practice developments:...', the trigger word is 'Commercial'. This is because the trigger word should ideally not be a generic adjective or verb, such as 'Improved'.
- Use the template provided below, maintaining the same format and copying it exactly, but with the end times filled in as appropriate. Enclose in <matches> tags.

<matches>
```json
{template}
```
</matches>
"""

TEXT_SLIDE_CONTENT_SYSTEM = """
You are an AI assistant tasked with creating effective text slides for an educational video. Your goal is to identify the most important content that should appear on a slide based on a given transcript and concept syllabus. Follow these instructions carefully:

Goals:
- Bullet points effectively summarize the content and tell the full story of the syllabus facts.
- Each bullet point almost directly quotes the transcript.
  - Minor modifications may be present to the beginning and end of the excerpt if necessary, to ensure it forms a standalone bullet.
  - No part of the excerpt is removed while forming a bullet, whether it's unnecessary or for any other reason. The core of the bullet matches the transcript excerpt word for word.
- Each bullet forms a robust, complete, and standalone point outlining a key learning according to the concept syllabus.
   - Robust means it includes a term and its definition, a key relationship, or features a strong central verb.
   - Complete means it forms a full sentence.
   - Standalone means the point presents a learning that is valuable and makes sense even without the other bullets.
- All key terms, their definitions, key relationships, and concepts are captured in some bullet.
- Each bullet included is critical to understanding the concept syllabus, anything that is not critical to the concept (not part of syllabus facts) is filtered out to avoid overloading the student.
- Bullet points contain only the information/knowledge that is mentioned in the concept syllabus. Something that is in transcript but not mentioned in syllabus is not included in text slide.
- Text slide should not display stuff like "AP World History" or "APUSH" or "AP Exam" or "AP Test" or anything related to the AP Exam, just the actual content of the concept.
- Each and every detail mentioned in the syllabus facts must get covered in the text slide if transcript mentions it. 

To create an effective text slide:

1. Analyze the concept syllabus:
   - Note any specific terms, definitions, or key points mentioned

2. Analyze the transcript:
   - Look for content that directly relates to the main topics and subtopics from the syllabus
   - Identify key terms and their definitions, critical explanations and important concepts mentioned by the host that are part of the concept syllabus.
   - Key term definitions that are mentioned in syllabus must be captured above all even if it presents a less important detail than others.

3. Select the most critical points for the slide:
   - Avoid including ANY information/knowledge that is not mentioned in the concept syllabus. (The points should come from intersection of syllabus and transcript knowledge)
   - Choose content that is essential to understanding the concept. Each and every detail mentioned in the syllabus facts is essential and must be included if transcript mentions it.
   - Do not shorten the names if any, use the full name as in the syllabus facts when first time referencing any person. For each proper noun (people, places, organizations) mentioned in your bullet points, verify that all contextual information from the syllabus (such as country associations, time periods, roles) is included alongside them when first time referencing them. All proper nouns presnt in syllabus facts must be mentioned in the bullet points.
   - Prioritize definitions and key points that align with the syllabus
   - Avoid including introductory examples, introductory context, and filler content from the explanation transcript. The syllabus facts don't have filler content.
   - Limit the selection to 3-4 main points to keep the slide concise and readable

4. Format the selected content:
   - Keep each point brief, not more than 15 words. Take this as a guideline, not a strict rule. Never sacrifice critical contextual information or details for the sake of brevity.
   - Each bullet point should be an almost word for word excerpt from the transcript
       - Slight necessary modifications are allowed to start and end of each excerpt so it forms an appropriate standalone bullet point.
       - As you extract an excerpt from the transcript to form a bullet, you may not trim out unnecessary details from the middle of the excerpt only the edges. 
   - You may replace some sub-phrases or prepositions with punctuation marks for brevity and common shorthand notations like &.
       - Don't use uncommon shorthand notations like # (number), ~ (approximately), etc.
   - Do not break a single transcript sentence into two or more bullets points. One transcript sentence should correspond to only one bullet point.
   - Avoid personal pronouns, even if they are used in the transcript. Note that the transcript is delivered by a historical figure - {figure_name}. For instance,
      - Instead of "My empire", say "{figure_name}'s empire" or name the empire being referred to, e.g., "Tang Dynasty".
      - Instead of "I", if the role of the person is critical to the point being made, replace it with their name - {figure_name}. Otherwise, omit the personal part entirely.
    - Do not end any bullet with '...' or ',' other punctuation marks except for a period, complete the sentence ensuring point is strong and standalone.
    - Capitalize the first letter of each bullet point.

5. Verify before finalizing:
 - Is there any detail that was present in the syllabus facts that was also mentioned in the transcript but you didn't include? If yes, add it.
 - Do the bullet points tell the full story of the syllabus facts? If not, add what is missing.
 - Is there any named entity (name of person, group, place etc., proper noun) that was present in syllabus facts but not in the text slide? If yes, please add it.
 - Are the number of points crossing 5? If so, bring it down to 5 by:
    - concatenating some points together where it makes sense, even if it hurts the brevity guideline.
    - drop stuff that is not critical and is just padding or repetitive. But do not drop any detail or something that is part of the syllabus facts.

Return a JSON object with the following structure inside <answer> tags:

<answer>
```json
{{
    "title": "<1-4 word title of the concept being taught>",
    "points": [
        "<Excerpt from transcript capturing key learning.>",
        "<Another excerpt from transcript.>",
        "<A third excerpt if necessary.>",
        "<A fourth excerpt if necessary.>"
    ]
}}
```
</answer>

After the slide content, provide a brief explanation of your choices:

Remember, your goal is to create a slide that effectively summarizes the most crucial information from the transcript while aligning with the concept syllabus. 
"""

text_slide_content_examples = [
    {"role": "user", "content": "<transcript>\nBy the mid-20th century, multiple regions had emerged with strong manufacturing sectors, relying on fossil fuels for transportation and economic expansion. This era saw the rise of advanced engineering methods as opposed to simpler manual practices, paving the way for large-scale production. Commerce and trade expanded rapidly, setting the stage for significant growth in places such as Asia.\n\nI observed how reliance on coal soared as we sought to power mechanical devices for manufacturing and transportation. Industrial development, or the broad expansion of large-scale economic activities, spurred nations to burn fossil fuels, generating more greenhouse gas emissions, as opposed to modest levels seen in earlier, smaller-scale production. After 1950, the rapid industrialization and economic growth of places like China and India intensified global CO2 emissions, leading to environmental challenges including global warming and climate change. Many nations recognized that these energy sources accelerated economic gains, yet the resultant pollution grew to a scale affecting the entire planet. Thus, the surge in industrial development and fossil fuel usage remains a powerful force that shaped modern economies and the environment in profound ways.\n</transcript>"},
    {"role": "assistant", "content": "```json\n{\n    \"title\": \"Industrial Development\",\n    \"points\": [\n        \"Industrial development - the broad expansion of large-scale economic activities\",\n        \"Industrial development spurred nations to burn fossil fuels, generating more greenhouse gas emissions\",\n        \"After 1950, the rapid industrialization and economic growth of places like China and India intensified global CO2 emissions\",\n        \"This lead to environmental challenges including global warming and climate change\",\n        \"Energy sources accelerated economic gains\"\n    ]\n}\n```\n\nExplanation:  \n\u2022 Key bullet points directly emphasize fossil fuels, greenhouse gas emissions, and economic growth trend, omitting the less critical initial context provided.\n\u2022 Each bullet is almost a direct quote from the transcript, with minimal but necessary modifications to ensure standalone clarity, such as the addition of \"Industrial development\" at the start of bullet two.\n\u2022 Each bullet covers a single idea, making it digestible (e.g., the definition and impact of the industrial revolution were split into two points).\n\u2022 For brevity, counter statements are excluded, punctuation marks substitute prepositions (e.g., \"-\" in point 1), and repetitive statements (e.g., \", yet the resultant pollution grew to a scale affecting the entire planet\" which was part of point 5) are removed.  \n\u2022 Definitions and relationships (e.g., industrial development leading to increased emissions) are preserved for a concise yet comprehensive representation of the concept.\n"}
]

TEXT_SLIDE_CONTENT_USER = """Here is the concept syllabus:

<concept_syllabus>
{concept}
</concept_syllabus>

Here is the transcript of the explanation:

<transcript>
{transcript}
</transcript>

Remember, don't base your points on any initial context given that surrounds the main idea outlined in the syllabus. Each bullet point should concentrate on the core content specified in the syllabus. Disregard any initial background information provided, as these are not important and should not appear as a bullet point.
"""

TEXT_SLIDE_TIMINGS_SYSTEM_PROMPT = """
You are an AI assistant tasked with identifying the trigger phrases for a text slide and it's bullet points from a transcript for an educational video.
You will be given a list of points that'll be displayed on the text slide and a transcript. Your task is to identify the exact verbatim phrases from the transcript that each point is covering, as well as identify where the core explanation begins (the start of the text slide). Extract the transcript phrases word for word.

Follow these steps to complete the task:

1. Read through the entire transcript to familiarize yourself with the content.

2. Identify the start of the core explanation:
   a. Look for a clear transitional phrase that moves from context/examples into the main concept explanation
       - This will be the start of the text slide, so it must strictly appear before all phrases that you'll be identifying for the points.
   b. This phrase must appear before the first point is discussed. 
       - It should be atleast 10 words long, the first word will mark the beginning of the text slide, rest of the words will just be used to uniquely locate the phrase in the transcript. 
       - Pick the phrase preceding 5 words of point 1 if you must. It doesn't need to be start of a sentence, either.
       - If the first point happens to be the start of the transcript, then the start of the text slide will be the first 10 words of the transcript.
   c. Ignore any initial comments, context-setting, or preliminary examples

3. For each point in the list:
   a. Carefully analyze the point to understand its main idea or topic
   b. Search the transcript for a phrase that closely matches or represents this point
   c. When you find a matching phrase, extract it word for word from the transcript
   d. Make sure the extracted phrase captures the essence of the point without including unnecessary information
   e. Ensure the extracted phrases align perfectly with the start and end of the point, excluding any unnecessary text beyond the core point.
     - Example
       - Sentence: "Meanwhile, in the Americas, new colonial hierarchies maintained elite dominance by keeping power among landowners and administrators, despite rising merchant fortunes."
       - Point: "In the Americas, new colonial hierarchies dominated by keeping power among landowners and administrators."
       - Phrase: "in the Americas, new colonial hierarchies maintained elite dominance by keeping power among landowners and administrators"
       - Explanation: The phrase aligns perfectly with the start and end of the point, omitting the extra text "Meanwhile" and "despite rising merchant fortunes". The phrase also aligns with the transcript in the middle parts where the point replaces "maintained elite dominance", ensuring consistency with the original text.

4. If you cannot find an exact match for a point, look for the closest relevant phrase that conveys a similar idea.

5. Ensure that the extracted phrases are verbatim from the transcript. Do not paraphrase or modify the text in any way.

6. If a point seems to match multiple phrases in the transcript, choose the one that most accurately and concisely represents the point.

7. After processing all points, format your output as a JSON-like dictionary inside <answer></answer> tags according to the following schema:

<answer>
```json
{
    "slide_start": "<word for word phrase indicating start of core explanation (this must appear before all other phrases in the matches list)>",
    "matches": [
        {
            "point": "<point>",
            "phrase": "<word for word phrase from transcript corresponding to the point>"
        }
    ]
}
```
</answer>

8. Double-check that all extracted phrases are exact quotes from the transcript and that they accurately represent the corresponding points.

Remember to maintain the exact wording and punctuation from the transcript in your extracted phrases.
"""

text_slides_timings_examples = [
    user_message("""The text slide points are:
<points>
[
  "Around 1000 CE, many in Sub-Saharan Africa faced a shift, as farming replaced nomadic life.",
  "Sedentary societies, or permanent settlements, needed more formal ways to share resources, in contrast to nomads.",
  "Sub-Saharan societies governed themselves through kinship networks instead of centralized rule.",
  "This new stability shaped politics: people needed rules for farmland use and conflict resolution."
]
</points>

The transcript is:
<transcript>
Picture yourself leaving a weekend campsite for a new house, where you must decide who cooks meals and who fixes the roof. Around 1000 CE, many in Sub-Saharan Africa faced a similar shift, as farming replaced nomadic life. Such sedentary societies, or permanent settlements, needed more formal ways to share resources, in contrast to nomads who move with the seasons. In addition, they often governed themselves through kinship networks instead of centralized rule, relying on family relationships and village gatherings for major decisions. You can look back on the Bantu migrations we discussed to see how new farmland and trade routes shaped these settled worlds. This new stability shaped politics: people needed rules for farmland use and conflict resolution, though strong central authority rarely emerged, and farming also demanded organized labor, storage, and local leadership, unlike quick moves to fresh hunting grounds. Now, let's see if you're ready for a few questions about Sedentary Societies.
</transcript>"""),
    assistant_message("""<answer>
```json
{
    "slide_start": "Around 1000 CE, many in Sub-Saharan Africa faced a shift.",
    "matches": [
        {
            "point": "Around 1000 CE, many in Sub-Saharan Africa faced a shift.",
            "phrase": "Around 1000 CE, many in Sub-Saharan Africa faced a similar shift, as farming replaced nomadic life."
        },
        {
            "point": "Sedentary societies, or permanent settlements, needed more formal ways to share resources, in contrast to nomads.",
            "phrase": "Such sedentary societies, or permanent settlements, needed more formal ways to share resources, in contrast to nomads who move with the seasons."
        },
        {
            "point": "Sub-Saharan societies governed themselves through kinship networks instead of centralized rule.",
            "phrase": "They often governed themselves through kinship networks instead of centralized rule"
        },
        {
            "point": "This new stability shaped politics: people needed rules for farmland use and conflict resolution. Farming also demanded organized labor, storage, and local leadership.",
            "phrase": "This new stability shaped politics: people needed rules for farmland use and conflict resolution, though strong central authority rarely emerged, and farming also demanded organized labor, storage, and local leadership, unlike quick moves to fresh hunting grounds."
        }
    ]
}
```
</answer>"""),
    user_message("""1) The phrase extraction matches the beginning well, but includes too much text. It should end at "shift" rather than continuing to the end of the sentence.

2) The phrase doesn't align precisely with the point. It should start with "Sedentary societies" (without "Such") and end with "nomads" (without "who move with the seasons").

3) Point 3 is perfectly executed. You correctly matched "They" in the transcript with "Sub-Saharan" in the point, and maintained proper alignment at both ends.

4) You correctly included the full transcript text for point 4, even though the point itself is shorter. However, the phrase should have ended at "and local leadership" to match the point's ending."""),
    assistant_message("""I'll apply the feedback to ensure each phrase perfectly aligns with the start and end of the bullet point:

<answer>
```json
{
    "slide_start": "Around 1000 CE, many in Sub-Saharan Africa faced a shift.",
    "matches": [
        {
            "point": "Around 1000 CE, many in Sub-Saharan Africa faced a shift.",
            "phrase": "Around 1000 CE, many in Sub-Saharan Africa faced a similar shift."
        },
        {
            "point": "Sedentary societies, or permanent settlements, needed more formal ways to share resources, in contrast to nomads.",
            "phrase": "sedentary societies, or permanent settlements, needed more formal ways to share resources, in contrast to nomads"
        },
        {
            "point": "Sub-Saharan societies governed themselves through kinship networks instead of centralized rule.",
            "phrase": "They often governed themselves through kinship networks instead of centralized rule"
        },
        {
            "point": "This new stability shaped politics: people needed rules for farmland use and conflict resolution. Farming also demanded organized labor, storage, and local leadership.",
            "phrase": "This new stability shaped politics: people needed rules for farmland use and conflict resolution, though strong central authority rarely emerged, and farming also demanded organized labor, storage, and local leadership,"
        }
    ]
}
```
</answer>""")

]
TEXT_SLIDE_TIMINGS_USER_PROMPT = """
Do the same here. Remember to ensure, ensure each phrase perfectly aligns with the start and end of the bullet point. The phrase must exclude any text padded to phrase start and end, if its not mentioned in the point.

The text slide points are:
<points>
{points}
</points>

The transcript is:
<transcript>
{transcript}
</transcript>
"""


DIAGRAM_TIMINGS_SYSTEM_PROMPT = """
You are an AI assistant tasked with identifying the trigger phrases for elements of a diagram from a transcript for an educational video. The diagram is supposed to appear on the screen progressively, so every element of the diagram will appear on screen when it starts being talked about in the transcript. Your duty is to identify these trigger phrases (the parts that should reveal the element on screen)

You will be given the transcript and the content of the diagram. I'll give you a model (schema) of the diagram that you need to fill. Your task is to identify the phrases from the transcript that should trigger the appearance of each element in the diagram, as well as identify the phrase that should trigger the appearance of the whole diagram.

Follow these steps to complete the task:

1. Read through the entire transcript to familiarize yourself with the content.

2. Identify the start of the core explanation (trigger phrase for the whole diagram):
   a. Look for a clear transitional phrase that moves from intial context/examples into the main concept explanation (starts talking about stuff in the diagram)
   b. This phrase must STRICTLY appear before all other trigger phrases in the transcript that you'll be identifying. 
       - It can be as short as 5 words, but it must absolutely not overlap with the phrase for the earliest element that pops up on screen. 
       - Pick the 5 words preceding the earliest diagram element if you must. It doesn't need to be start of a sentence, either.
   c. Ignore any initial comments, context-setting, or preliminary examples
   d. This phrase should be stored in the start_phrase field of the diagram model

3. For each element in the diagram content:
   a. Carefully analyze the element to understand its main idea or topic
   b. Search the transcript for a phrase that closely matches or represents this element
   c. When you find a matching phrase, extract it word for word from the transcript
   d. Make sure the extracted phrase captures the essence of the element without including unnecessary information
   e. Ensure the phrase begins at the exact starting point of the text. The end can extend beyond, but the beginning must coincide with the start of the point:
       - For Example. Text: "Escape suffering" => Phrase should be: "escaping suffering. It emphasize that", not "Buddhism focuses on escaping suffering" even though the latter makes more sense as a phrase.
       
4. If you cannot find an exact reference for an element, look for the closest relevant phrase that conveys a similar idea.

5. Ensure that the extracted phrases are verbatim from the transcript. Do not paraphrase or modify the text in any way.

6. Always use the FIRST mention of an element in the transcript, even if it's brief or part of a list. Do not sacrifice the first mention for a better explanation that appears later - the goal is to identify where elements are introduced, not where they are best explained.

7. Format your output as a JSON-like dictionary inside <answer></answer> tags strictly following the diagram schema:

<answer>
```json
{model}
```
</answer>

8. Double-check that all extracted phrases are exact quotes from the transcript and that they accurately represent the corresponding elements.

Remember to maintain the exact wording and punctuation from the transcript in your extracted phrases.
Fill every phrase field in the model supplied, not just for points but for titles as well if required by the model schema. Fill them based on your best judgement even if they are not explicitly mentioned in the transcript.
"""

DIAGRAM_TIMINGS_USER_PROMPT = """
The transcript is:
<transcript>
{transcript}
</transcript>

The diagram content is:
<diagram_content>
{points}
</diagram_content>

{custom}
Your response must strictly be a JSON object strictly following the provided model schema.
"""

DIAGRAM_CONTENT_SYSTEM = """
You are an AI assistant tasked with creating educational diagrams for AP exam preparation content. Your goal is to organize complex concepts into clear visual structures for diagrams that help students understand and retain key information.

You will be creating a {type} to {purpose}.
You have to determine the content of the diagram based on the explanation transcript and the concept syllabus.

## Input:
You'll be given the concept syllabus that'll contain the facts about the concept and some additional information.
You'll also be given the explanation transcript that'll spoken to explain the concept.

## Important Instructions:
- The diagram content should stem from the explanation transcript but should ONLY and ONLY include things that are part of the facts (facts and cross unit facts) mentioned in the concept syllabus.
- Only include points in the diagram that explicitly in the concept syllabus. If a detail appears in the explanation transcript but is not confirmed by the syllabus, do not add it as a element in the diagram (branch, key point, circle, node etc.).
- Only include information and relationships that are explicitly mentioned in the explanation transcript and is clearly part of the facts (facts and cross unit facts) in the concept syllabus. Do not create or infer information or relationships on your own.
- Each text in the diagram should convey the exact meaning that is conveyed in the explanation transcript. Do not alter the meaning just to make it fit the diagram. An overflow of text is acceptable in worst case but not altering the meaning.
- The number of elements in diagram should be minimal - just enough to cover everything mentioned in the facts that is also spoken in the explanation transcript. If the explanation covers fewer things, use fewer elements rather than making up content
- All points/elements in the diagram must be direct quotes or close paraphrases from the explanation transcript. Any element/point that you include in diagram should be talked about or mentioned somewhere in the explanation transcript.
- For all text in the diagram use the language/words used in the explanation transcript and not the concept syllabus.
- Choose appropriate Font Awesome icons (classic solid free ones) when needed that best represent the element (use common icons like: book, users, crown, scroll, landmark, scale-balanced, building-columns, etc.)
- For the font awesome icons, use the icon name without the fa- prefix. (e.g. use globe instead of fa-globe)
- The number of elements in parts of diagram need not be even. Should be decided based on what's being covered in the explanation.
- Do not paraphrase important terms mentioned in the facts in concept syllabus like "Civil Service Examination" (use the exact term), "The Green Revolution" (use the exact term), etc.
- The diagram should not display stuff like "AP World History" or "APUSH" or "AP Exam" or "AP Test" or anything related to the AP Exam, just the actual content of the concept.
- Do include full forms of abbreviations if they are mentioned in the syllabus facts.
- Do not omit any details if present in syllabus facts and was spoken in the explanation transcript like (full name of a person, places, dates, etc.)
- All proper nouns present in syllabus facts must be mentioned in the diagram.

Verify before finalizing:
- Is there any detail that was present in the syllabus facts that was also mentioned in the explanation transcript but you didn't include in the diagram? If yes, add it.
- Does the diagram tell the full story of the facts in the concept syllabus? if not, add what is missing.
- Is there any named entity (name of person, group, place etc., proper noun) that was present in syllabus facts but not in the diagram? If yes, please add it.

NOTE: The diagram will be revealed progressively, so ideally the diagram content should follow the same order as the explanation transcript whenever possible.

## {type}-Specific Instructions:
{instructions}

## Output:
You'll output the diagram content in form of a JSON object.
Your response must strictly follow this JSON schema:
<output_schema>
{schema}
</output_schema>

Return only the JSON object and nothing else.
"""

DIAGRAM_CONTENT_USER = """
Create the {type} diagram structure for the given concept.

Concept Syllabus:
<concept_syllabus>
{concept_data}
</concept_syllabus>

Explanation transcript:
<explanation>
{explanation}
</explanation>

The transcript is delivered by the historical figure - {figure_name}.

Return only the JSON object and nothing else.
"""

# Diagram-specific configurations
DIAGRAM_CONFIGS = {
    DiagramType.MIND_MAP: {
        "type": "Mind map",
        "purpose": "organize the key ideas into a clear hierarchial grouping",
        "instructions": """
- The root node should represent the main concept
- Create 2-5 main branches (children) that represent key ideas in the concept
- Choose a relevant Font Awesome icon for the root node and each branch
- For each branch, provide 1-4 specific points that summarize the idea
- Points should be concise phrases: not more than 5-6 words
- The number of points in each branch need not be even
- Total elements (branches + points) should not exceed 12
""",
        "schema": """
{{
    "root": {{
        "title": "Main Concept Title",
        "icon": "font-awesome-icon-name-without-fa-prefix"
    }},
    "categories": [
        {{
            "title": {{
                "text": "Branch Title",
                "icon": "font-awesome-icon-name-without-fa-prefix"
            }},
            "points": [
                "specific point 1",
                "specific point 2",
                "specific point 3"
            ]
        }},
        ...
    ]
    }}
}}
""",
        "qc_requirements": """
- Root node should represent the main concept
- Each branch should represent a distinct key idea in the concept
- Branch titles should represent the key idea in the concept and shouldn't exceed 3-4 words
- Points under each branch should be concise phrases: don't exceed 5-6 words
- Total number of branches should be 2-5
- Each branch should have 1-4 points
- Total elements (branches + points) should not exceed 12
"""
    },
    DiagramType.VENN_DIAGRAM: {
        "type": "Venn diagram",
        "purpose": "effectively compare and contrast 2-3 related ideas",
        "instructions": """
- Create either 2 or 3 circles based on the natural grouping of ideas
- Each circle should represent a distinct concept or category
- Points in each circle should be unique characteristics of that concept
- Number of points should be minimal (not more than 3-4 per circle)
- The points should be very concise words not more than 5-6 words
- The intersection text should capture common elements (max 6-7 words)
- The number of points in each circle need not be equal
- The title should be concise and capture the main idea of the diagram
- The subtitle should be concise and elaborate more on what the diagram is about
""",
        "schema": """
{{
    "title": "Clear, concise title for the diagram",
    "subtitle": "Optional subtitle providing context",
    "circles": [
        {{
            "name": "Name of first concept/category",
            "points": [
                "unique characteristic 1",
                "unique characteristic 2",
            ]
        }},
        // 2-3 circles total
    ],
    "intersection_text": "Text describing what all concepts have in common"
}}
""",
        "qc_requirements": """
- Title should be concise and capture the main idea of the diagram
- Subtitle should be concise and clear
- Each circle should have a distinct name
- Points in each circle should be unique to that circle
- Points should be concise phrases not more than 5-6 words
- Each circle should have not more than 4 points
- Intersection text should be 6-7 words max
"""
    },
    DiagramType.TREE: {
        "type": "Tree diagram",
        "purpose": "organize the information into a clear parent-child structure",
        "instructions": """
- Create a single root node representing the main concept
- Rood node should have the is_root flag set to true
- Create a logical hierarchy with parent-child relationships with upto 3 levels
- The depth should not exceed 3 levels (root → child → grandchild) i.e. (root → child → child → child) is not allowed
- Each node should have a concise title (not more than about 3 words)
- All other important details about the node (such as names, places, important terms etc.) can be placed in description
  - For example, title: "Agricultural Revolution" and description: "Green Revolution, Land Reform, Technological Advancements"
  - These details (description) need not be added everytime, only add them if they are important and relevant to the node otherwise keep just the concise title. Mostly these would be present in the leaf nodes.
  - Don't use phrases, keep it as concise as possible. We don't want paragraph, just a few words when there details that shouldn't be missed.
  - The description should never exceed 6-7 words. The only and only exception is if you are mentioning a list of things (like list of 5 permanent members of UN Security Council), in that case you should complete the list and not trim it because of 6-7 words limit.
- If there is a need to go beyond 3 levels, put the child nodes after grandchild in description of grandchild separated by commas.
- Choose a relevant Font Awesome icon for each node
- The tree should have not more than 10 nodes total to keep it concise and readable
- The number of children need not be even, decide as per the content
- Each subtree need not reach the maximum depth, decide what's best for the content
""",
        "schema": """
{{
    "title": "Tree Diagram",
    "tree": {{
        "title": "Root Node Title",
        "icon": "font-awesome-icon-name-without-fa-prefix",
        "is_root": true,
        "children": [
            {{
                "title": "Child Node Title",
                "icon": "font-awesome-icon-name-without-fa-prefix",
                "children": [
                    {{
                        "title": "Grandchild Node Title",
                        "icon": "font-awesome-icon-name-without-fa-prefix",
                        "description" (optional): "Description of the grandchild node (not more than 6-7 words)"
                    }}
                ]
            }},
            // More nodes as needed
        ]
    }}
}}
""",
        "qc_requirements": """
- Root node title should capture the main idea of the tree
- Each node should have a concise title (not more than about 3 words)
- Tree depth should not exceed 3 levels (root → child → grandchild) i.e. (root → child → child → child) is not allowed
- Total nodes should not be more than 10
- The description should never exceed 7 words. The only and only exception is if it is mentioning a list of things (like list of 5 permanent members of UN Security Council), in such cases it is allowed to exceed the word limit to complete the list.
"""
    } if DISABLE_TREE_DESCRIPTION == 'false' else {
        "type": "Tree diagram",
        "purpose": "organize the information into a clear parent-child structure",
        "instructions": """
- Create a single root node representing the main concept
- Rood node should have the is_root flag set to true
- Create a logical hierarchy with parent-child relationships with upto 3 levels
- The depth should not exceed 3 levels (root → child → grandchild) i.e. (root → child → child → child) is not allowed
- Each node should have a concise title (not more than about 3 words)
- Choose a relevant Font Awesome icon for each node
- The tree should have not more than 10 nodes total to keep it concise and readable
- The number of children need not be even, decide as per the content
- Each subtree need not reach the maximum depth, decide what's best for the content
""",
        "schema": """
{{
    "title": "Tree Diagram",
    "tree": {{
        "title": "Root Node Title",
        "icon": "font-awesome-icon-name-without-fa-prefix",
        "is_root": true,
        "children": [
            {{
                "title": "Child Node Title",
                "icon": "font-awesome-icon-name-without-fa-prefix",
                "children": [
                    {{
                        "title": "Grandchild Node Title",
                        "icon": "font-awesome-icon-name-without-fa-prefix",
                    }}
                ]
            }},
            // More nodes as needed
        ]
    }}
}}
""",
        "qc_requirements": """
- Root node title should capture the main idea of the tree
- Each node should have a concise title (not more than about 3 words)
- Tree depth should not exceed 3 levels (root → child → grandchild) i.e. (root → child → child → child) is not allowed
- Total nodes should not be more than 10
"""
    }
}

def get_diagram_content_system_prompt(diagram_type: DiagramType):
    config = DIAGRAM_CONFIGS[diagram_type]
    return DIAGRAM_CONTENT_SYSTEM.format(
        type=config["type"],
        purpose=config["purpose"],
        instructions=config["instructions"],
        schema=config["schema"]
    )

def get_diagram_content_user_prompt(diagram_type: DiagramType, concept_data: str, explanation: str, figure_name: str):
    return DIAGRAM_CONTENT_USER.format(
        type=diagram_type,
        concept_data=concept_data,
        explanation=explanation,
        figure_name=figure_name
    )


LESSON_ORGANIZER_IDENTIFIER_SYSTEM = """
You are an AI assistant tasked with identifying the part of the introduction of the lesson transcript that states what will be covered in the lesson.
The part can be tricky to identify, so be careful. There will be some starting sentences to build context and the part that states what will be covered will start after that.

You'll also be given a list of sections that will be covered, so you can use that to identify the part that states what will be covered in the lesson. Note that these won't be spoken exactly but will help you identify the required part.

For example if introduction is:
<introduction>
Today, we'll explore how technology transformed daily life in the twentieth century. In 1900, most people lived much like their grandparents did, with limited access to electricity, cars, or modern medicine. These dramatic changes unfolded through breakthroughs in farming methods and environmental impacts, advances in how people connected and moved around, and improvements in healthcare and power sources that reshaped society.
</introduction>

and the sections are:
<sections>
[
    "The Green Revolution",
    "Global Connectivity",
    "Healthcare and Power Sources"
]
</sections>

The part of the introduction that states what will be covered in the lesson will be:
<output>
These dramatic changes unfolded through breakthroughs in farming methods and environmental impacts, advances in how people connected and moved around, and improvements in healthcare and power sources that reshaped society.
</output>
(without the <output> tags)

You must return an exact verbatim part of the introduction that states what will be covered in the lesson.
"""

LESSON_ORGANIZER_IDENTIFIER_USER = """
This is the introduction part of a lesson transcript:
<introduction>
{introduction}
</introduction>

This is the list of sections that will be covered in the lesson:
<sections>
{sections}
</sections>

Return only the exact part of the introduction that states what will be covered in the lesson and nothing else (without the <output> tags)
"""

LESSON_ORGANIZER_CONTENT_SYSTEM = """
We are creating an automated pipeline for generating educational lesson videos for AP exam preparation.
You are an AI assistant tasked with creating a mind map for the lesson overview of the lesson.

You'll be given the lesson title, the section names, and the sentence that states what will be covered in the lesson.
This mindmap would be displayed in the beginning of the lesson when this sentence will be spoken.

The mindmap has root node and children nodes. Root node would be lesson title and children nodes would be section names.

Now the nodes won't have the exact lesson title or exact section names. They would be paraphrases:
1) For the lesson title (root node), it should be paraphrased to a short and concise phrase if it's more than 3-4 words, else keep it the same.
So if the lesson title is "What made the Song Dynasty Successful?"
The root node should be "Song Dyansty's Success"

2) For the section names (children nodes), they should be paraphrased to a short and concise phrase that aligns with what's spoken in that sentence. The section name may not be exactly mentioned in the sentence, hence this paraphrasing is important to align the text on screen with what's spoken.

IMPORTANT:
- The mindmap can only handle 5 categories, so if there are more than 5 sections, you have to merge some section names into a single category. Example: "Industrial Revolution" and "Medical Inovations" can be merged into a single category "Industrial Revolution and Medical Innovations"
- But do this merging only and only if there are 6 or more sections, else keep them separate.

You have to fill the provided JSON schema for the mind map:
<json_output_schema>
{{
    "root": {{
        "title": "Lesson Title",
        "icon": "font-awesome-icon-name-without-fa-prefix"
    }},
    "categories": [
        {{
            "title": {{
                "text": "Section Name",
                "icon": "font-awesome-icon-name-without-fa-prefix"
            }},
            "points": []
        }},
        ...
    ]
    }}
}}
</json_output_schema>

Also determine relevant icons for each node. Use the icon name without the fa- prefix. (e.g. use globe instead of fa-globe)
The icons should be valid font awesome classic solid free icons.
Keep the points list empty for each category.
"""

LESSON_ORGANIZER_CONTENT_USER = """
The mindmap's title and nodes have been prefilled, you just need to fill in the icons.

Return the JSON below word for word, with the icon fields filled in:
```
{organizer_data}
```

Return the JSON object with the mind map structure and nothing else.
"""

SECTION_ORGANIZER_IDENTIFIER_SYSTEM = """
We have the section overview part of the transcript for an educational lesson video. Video has different sections, each section covers some concepts. Sections starts with a section overview that introduces the section and tell what concepts will be covered in that section and then speaks some other stuff. You are an AI assistant tasked with identifying trimming down the other stuff and return the overview back starting from the start but ending right after what will be convered is stated.

You'll also be given a list of concepts that will be covered in the section, use this to identify the part that states what will be covered, you have to stop right after this part is stated. Note that these concept names won't be spoken exactly but will help you identify the required part.

For example if section overview is:
<overview>
In this first section, we'll explore how farming and environmental changes shaped the \"Agriculture and Environment\" landscape during the 1900s. We'll examine the impressive gains of the Green Revolution in food production, while also considering the unexpected environmental consequences that followed these agricultural advances. To help us understand these revolutionary agricultural developments, I'm pleased to welcome Dr. Norman Borlaug, the Nobel Peace Prize-winning scientist who spearheaded the Green Revolution. Dr.
</overview>

And the concepts are:
<concepts>
[
    "Rise of Green Revolution",
    "Green Revolution's Consequences"
]
</concepts>

The part that introduces the section and states what will be covered is:
<output>
In this first section, we'll explore how farming and environmental changes shaped the \"Agriculture and Environment\" landscape during the 1900s. We'll examine the impressive gains of the Green Revolution in food production, while also considering the unexpected environmental consequences that followed these agricultural advances.
</output>
(without the <output> tags)

Notice how this starts from the beginning of the overview and ends right after what will be covered is stated, trimming down the other stuff. You have to do the same.

You must return a verbatim part of the overview that introduces the section and states what will be covered in the section.
"""

SECTION_ORGANIZER_IDENTIFIER_USER = """
This is the overview part of a section:
<overview>
{overview}
</overview>

This is the list of concepts that will be covered in the section:
<concepts>
{concepts}
</concepts>

Identify the starting part of the overview that introduces the section and states what will be covered in the section.

Return only the starting part of the overview that introduces the section and states what will be covered in the section and nothing else (without the <output> tags)
"""


SECTION_ORGANIZER_CONTENT_SYSTEM = """
You are an AI assistant tasked with creating a mind map for a section overview in an educational lesson video for AP exam preparation. You will be given a lesson overview transcript, along with the true section title and true concept names. Your task is to identify the adapted versions of these in the transcript and create a mind map structure.

First, carefully read the following lesson overview transcript:

<lesson_overview_transcript>
{overview}
</lesson_overview_transcript>

Your task is to:

1. Identify the adapted section title in the transcript that corresponds to the true section title. This will be the root node of your mind map.
  - The wording of the root title suggested must closely resemble how the title is presented in the transcript. 
  - The transcript should normally mention the true section title verbatim, if so stick to the true title.
  - The closer the root tile is to the true section title better, but staying true to the phrasing in the lesson transcript is more important.
  - The title length should be 2-5 words, the shorter the better. 

2. For each true concept name, find its adapted version in the transcript. These will be the child nodes of your mind map.
  - There should be one child node or category added per each concept.
  - The wording of this category created must closely resemble how its presented in the transcript.
  - The category length should be 1-4 words. Focus and extract the core concept.
  - It is critical, that the category names you pick is the representation of the concept in the lesson transcript provided. That is each category name should almost be a substring of the lesson transcript. At times the concept name and phrasing in the transcript might be very distant due to the simplifications performed in the transcript, regardless you must remain intelligent and identify the matching phrase. 
  - You must adhere to the transcript wording of each concept at all times, do not paraphrase or modify the text in any way even if its to resemble the true concept name. This is absolutely forbidden.
  - The concept presentations in the transcript will appear back to back in a single sentence, usually the second sentence. Use this to your advantage, and make sure to extract the correct phrasing representation of the concept from that sentence. 
  - Use title case
  - Do not extract phrase from the address to a historic figure if any, that sentence does not contain references to the concepts and should not be meddled with.

3. Suggest a representative Font Awesome icon for the root node and each child node that best illustrates the section or concept. Use the icon name without the fa- prefix. (e.g. use globe instead of fa-globe)

When identifying the adapted versions, look for simpler phrasings or explanations that convey the same meaning as the true titles and concepts. The adapted versions should be extracted almost verbatim from the transcript but stated in a concise manner.

IMPORTANT:
- The mindmap can only handle 5 categories, so if there are more than 5 concepts, you have to merge some concept names into a single category. Example: "Rise of Green Revolution" and "Green Revolution's Consequences" can be merged into a single category "Green Revolution"
- But do this merging only and only if there are 6 or more concepts, else keep them separate.
- Do not split a single concept into multiple categories. Concept list will be provided, stick to it for the categories unless there are more than 5 concepts.

Present your mind map structure in the following format:

<mind_map>
{{
    "root": {{
        "title": "Adapted Section Title",
        "icon": "font-awesome-icon-name-without-fa-prefix"
    }},
    "categories": [
        {{
            "title": {{
                "text": "Adapted Concept Name",
                "icon": "font-awesome-icon-name-without-fa-prefix"
            }},
            "points": []
        }},
        ...
    ]
}}
</mind_map>

Ensure that you include all the concepts mentioned in the true concept names, adapting them based on how they appear in the transcript. If you cannot find an adapted version for a concept, use the original true concept name and note that an adaptation wasn't found.

The icons should be a valid font awesome classic solid free icon.

Remember, your goal is to create a mind map structure that accurately represents the section overview while using the language and explanations provided in the transcript.
"""

SECTION_ORGANIZER_CONTENT_USER = """
Here are the true section title and concept names that have been adapted in the transcript:

<true_section_title>
{section_title}
</true_section_title>
Stick to the above specified section title even if it doesn't exactly match the transcript, in this case maintaining consistency with the true title is paramount. This doesn't concern the concepts, there use the adapted namings as per the transcript.

<true_concept_names>
{concepts}
</true_concept_names>
"""

# ================================= QC PROMPTS =================================

# Common QC prompts
QC_SYSTEM_PROMPT = """
You are an AI assistant tasked with reviewing content for an educational video against some strict requirements. The context of the content and the requirements will be provided to you.

Your job is to understand the requirements and review the content against each of the requirements.
Then return your review inside <review> tags in form of a JSON with following fields:
<review>
{
    "qc_pass": boolean, true if the content passes all the requirements, false otherwise
    "feedback": detailed feedback if issues found, empty string if passed
}
</review>

Important Instructions:
- Review thoroughly against ALL requirements
- Set qc_pass=true only if ALL requirements are met
- If qc_pass=false, provide specific, actionable feedback
- When providing feedback, only focus on the specific requirement that failed
- It is totally fine to fail just a single requirement
- Fail a requirement only if it strictly fails the criteria
- Focus on substantive issues, not minor details
- Feedback should be clear enough to make specific improvements

Before returning your review, perform a thorough analysis inside <analysis>. Evaluating each guidelines and diving deep where possible violations seem to appear.
"""

QC_USER_PROMPT = """
# Context and requirements
{requirements}

# Generated content
<{content_type}>
{output}
</{content_type}>

Review the content against all the requirements keeping in mind the context and the instructions provided.
Return only the feedback JSON object and nothing else.
"""

# Generic QC feedback prompt template
QC_FEEDBACK_PROMPT = """
I have reviewed the {content_type} and requirements failed that need to be addressed:

<Changes required>
{feedback}
</Changes required>

Please make the necessary changes and return only the updated {content_type}.
Ensure each suggested change is incorporated fully and correctly.
Do not forget or neglect the initial instructions, incorporate changes in a way that is consistent with the initial instructions.
Use your best judgement to apply the changes, but do not respond with anything else but the updated {content_type}.
"""

# Text slide specific requirements template
TEXT_SLIDE_QC_REQUIREMENTS = """
We are generating the contents for a text slide to explain a concept in the video. The text slide will have a title and some points.

The text slide content was generated using the concept syllabus and the transcript (spoken when text slide is shown).

Concept Syllabus:
<concept_syllabus>
{concept}
</concept_syllabus>

Transcript:
<transcript>
{transcript}
</transcript>

The transcript is delivered by a historical figure - {figure_name}.

Review the generated text slide contents against these strict requirements:

1. Transcript Matching:
   - Each bullet point must be an almost direct quote from the transcript
   - Slight modifications are allowed but only at the edges (start and end words)
   - Minimal modification is allowed at the middle level, provided it affects sub-phrases no longer than 25% of the entire bullet. For example, the bullet may exclude minor details or clarifiers not essential to the core syllabus, or replace pronouns, or other necessary rephrasing.
   - Each point should correspond to a contigous transcript segment and not be a combination of multiple segments
   - Do not break a single transcript sentence into two or more bullets points. One transcript sentence should correspond to only one bullet point.

2. Out of syllabus check:
   - Anything mentioned in textslide should not be out of syllabus. Any information that is not part of concept syllabus should be flagged
    - Does each detail mentioned in the concept syllabus and transcript appear in the text slide?.
        - If you find a missing detail, analyze it in your analysis tags. Answer two questions:
            - Is the detail significant enough to form its own bullet point?
            - Will adding it to an existing bullet point cause a mismatch between the bullet point and the transcript, meaning the bullet point is no longer a continuous segment of the transcript?
        - If the answer to the first question is yes and there are fewer than five bullet points, suggest adding the bullet point. If the answer to the second question is yes, do not suggest adding the detail to a bullet point.
   - The text slide should not display stuff like "AP World History" or "APUSH" or "AP Exam" or "AP Test" or anything related to the AP Exam, just the actual content of the concept.
   - All proper nouns present in syllabus facts must be mentioned in the text slide.
3. Formatting:
   - Points must end with a period (should not end with '...' or ',' or other punctuations)
   - There should be no personal pronouns in points (I, my, we). It is okay to use the name of historical figure instead.
      - An exception is when a pronoun refers back to a subject already mentioned in the bullet point. If the subject is identified earlier in the same bullet point, later references to it via pronouns are permitted. 
         - For instance, "Safavids and Ottomans adjusted themselves: they did X..." is acceptable because it 'themselves' is referring back to the 'Safavids and Ottomans' mentioned at bullet start, while "We adjusted ourselves: we did X..." is not as it is unclear what 'we' or 'ourselves' refers to.
         - Evaluate lack of subject specification based on each bullet's merits, disregard what the transcript says here. Question for each bullet is, "Does it use personal pronouns without having specified the subject?"
   - The only shorthand allowed is '&' (don't use #, ~, etc.)
   - Points must start with a capital letter.

4. Content Limits:
   - Number of points should not exceed 5. If there are more, some points should be combined in the most reasonable way.

The modifications you suggest should also be very closely aligned with the transcript text.
"""

length_violation_feedback = """
### Violation in Bullet points lengths
                    
The bullet points are too long, exceeding the {length_limit} character limit by {overflow} characters. Please shorten them to meet the requirement. 
- It's best to trim from the beginning and end rather than the middle. 
- Focus on removing less important parts based on the syllabus, which outlines key learning points. If a bullet point includes details not in the syllabus, consider it unnecessary and remove it. 
- Avoid replacing phrases with shorter ones to keep the content consistent with the transcript. Always prioritize removing less crucial details over making them more concise.

Trim just the necessary amount do not overdo and risk :
 - losing key learnings from the syllabus
 - causing significant mismatch between transcript and bullet point contents, by removing partial phrases from the bullets."""

# Diagram specific requirements template
DIAGRAM_QC_REQUIREMENTS = """
We are generating the contents for a {diagram_type} diagram to explain a concept in the video. The diagram content was generated using the concept syllabus and transcript.

Concept Syllabus:
<concept_syllabus>
{concept}
</concept_syllabus>

Transcript:
<transcript>
{transcript}
</transcript>

The transcript is delivered by the historical figure - {figure_name}.

Review the generated diagram contents against these strict requirements:

1. {diagram_type} Requirements:
{diagram_specific_requirements}

2. General Diagram Requirements:
- Anything mentioned in the diagram should not be outside of the facts mentioned in the concept syllabus. Each diagram element MUST be part of the facts in the concept syllabus.
- Each element in the diagram should be closely related to some segment in the transcript. Element should not be unrelated to the transcript
- Each text in the diagram should be conveying the exact meaning that was conveyed in the transcript. Meaning should not be altered in any way.
- The diagram should not display stuff like "AP World History" or "APUSH" or "AP Exam" or "AP Test" or anything related to the AP Exam, just the actual content of the concept.
- Abbreviations should be expanded if the full forms are mentioned in the concept syllabus.

- Is there any detail that was present in the syllabus facts as well as transcript spoke it but wasn't included in the diagram? If yes, add it.
- Details like names of people, places, dates, events, diseases, etc. should not be omitted if present in the syllabus facts and was spoken in the transcript.
- All proper nouns present in syllabus facts must be mentioned in the diagram.
"""