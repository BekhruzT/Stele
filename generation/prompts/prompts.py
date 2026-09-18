import json
from typing import Any, Dict, List, Optional

from core.types import \
    LessonMetadata
from prompts.common_prompts import \
    get_subject_specific_transcript_prompt_entries

TRANSCRIPT_PLANNER_PROMPT = """You are tasked with planning the selection of {figure}s for an educational video transcript on {subject}. Your goal is to identify 1-2 key {figure}s for each section of the lesson who are best suited to introduce and teach the key phrases associated with that section. The user will be providing you with a list of key phrases organized by section. 

To complete this task, follow these steps:
1. Carefully analyze the key phrases for each section.
2. Identify the most suitable {figure}s for teaching each lesson:
  a) For each section, choose 1-2 {figure}s who are best suited to convey the key points. Factors to consider include their direct involvement or observation of the topic, their expertise and contributions, and their historical significance and recognition.
  b) When selecting multiple figures for a section, consider their synergy and how they can complement each other in covering key aspects of the section. Choose figures that, together, will deliver the ideal lesson, rather than selecting on an individual basis. If necessary, you may select up to three figures per section, but only if the section is broad and requires the expertise of diverse individuals or needs to be presented from three different perspectives.
  c) While it's acceptable for a {figure} to appear in multiple sections, aim to diversify your selections when possible.
  d) Choose figures that represent diverse perspectives, showcasing cultural exchange and interaction between groups. Aim for a balance among figures of different origins, cultures, and occupations. This could include a mix of political/military leaders with cultural/religious with scholars.
{ssi_sensitive_figures}
     

Present your output as a valid JSON object, complying with the following schema:
<thoughts>
[Your evaluation of the requirements and brainstorming of possible options that would comply with the requirements]
</thoughts>
<plan> # Final plan for the video in the form of a JSON object
{{
  "key_figures": {{
    "<section 1 title>": [<STRING. 1-2 (at most 3) most competent key figures to present the section>],
    "<section 2 title>": ...,
    ...
  }}
}}
</plan>


Here are the sections and their key phrases:
<metadata>
{metadata}
</metadata>
"""

exam_focus = """
---

### ** Content Alignment, Efficiency, and Critical Thinking Skills**

- **Align with AP Exam Content:**
  - Thoroughly cover the topics and questions from the content plan.
  - Address each point with explanations, examples, and context.
  - Link content to broader {field} themes and {focus_area}.
  - Highlight exam relevance by indicating how topics may appear in exam questions.
  - Emphasize key terms and concepts significant for the exam.
  - Clearly state objectives and guide learning with cues throughout the lesson.
  - Conclude with a summary and encourage further reflection or study.

- **Maintain Efficiency:**
  - Focus on essential concepts required for the AP exam.
  - Exclude unnecessary details.
  - Keep explanations clear and concise to maintain engagement.

- **Enhance Critical Thinking:**
  - **Emphasize Reasoning Skills:**
    - Focus on {thinking_skills}.
    - Encourage critical thinking by posing analytical questions.
  - **Provide Context and Connections:**
    - Offer necessary {field} background.
    - Explore {relationships} relationships.
    - Relate the {field} contents to other fields when appropriate.

"""

structure_and_organization = """
---

### **Structure and Organization**

- **Use Anchor Points:**
  - Identify key anchor points for the transcript first and surround them with supporting information and context.
  - Surrounding information can include analogies, examples, rhetoric questions, deeper information that further explains the anchor point or makes it easy to understand. They can also include connections to other points to help transition between anchor points.

- **Dynamic Dialogue:**
  - Incorporate conversations between a host and {figure}s relevant to the topic.
  - First-Person Perspectives: Have {figure}s share experiences and insights in their own words.
  - Enhance Engagement: Use these interactions to emphasize key points and make {field} come alive.  
  - Select only key {figure}s for these interactions. These {figure}s should be relevant to the topic and part of {field} important {figure}s.

- **Ensure Clear Structure:**
  - Present information logically, with each point building on the last.
  - Employ smooth transitions to guide the viewer seamlessly.

- **Maintain Logical Progression:**
  - Connect ideas logically to aid comprehension.
  - Reinforce key concepts to enhance retention.


"""

historical_figures = """
### **Strategic Use of {figure}**
- A list of the most competent and synergistic {figure}s has been selected and categorized by section to deliver this lesson. As you discuss each key concept, ensure to explore the topic and its key points through the effective use of these figures who were directly involved.
- Utilize these figures strategically, unfolding {field} through their perspectives.
- Ensure the host appropriately introduces each figure before they provide their insights. 
- Consider and emulate this example of a figure introduction from a history lesson - “Let's hear what Genghis Khan has to say on this... and after that, we will unravel why it matters today.”
- Here are the selected figures for each key concept of the lesson:
{figures_by_section}
"""

#Very high level on what this lesson entails- do not go into details or key points. This will be covered later.
intro_structure = """
#### **Introduction structure**
- The introduction should be formatted something like: "In this lesson, we will talk about x...".
  - "x" is the lesson title followed by a 1-2 line high level summary of the overarching theme of the lesson.
- The lesson title is designed with curriculum focused language and is more formal and stiff, incorporate it in a natural way rephrasing it in a conversational tone.
  - Example: The lesson title is "Chinese Traditions Shape East Asia", the introduction should start like "In this lesson, we will talk about how Chinese traditions shaped East Asia..."
- The introduction should be something that's spoken in 10-20s.
- Skip greetings or welcoming statements and dive straight into the topic.
"""

INTRODUCTION_TRANSCRIPT_PROMPT = """
You are an expert {subject} teacher. You are generating the introduction part of the transcript for an instructional video of your course.

The lesson title is:
<lesson_title>
{lesson_title}
</lesson_title>

You are given the key concepts which needs to be covered in this video:
<key_concepts>
{key_concepts}
</key_concepts>

<structure>
{intro_structure}
</structure>

<instructions>
- **Balance Information and Engagement:**
  - Strive to create a script that is both informative and captivating.
- **Focus on Student Needs:**
  - Keep in mind that this is the only instructional source for the student; clarity and comprehensiveness are crucial.
- **Promote Active Learning:**
  - Encourage students to engage with the material actively, not just passively absorb information.
- **Include Lesson Title:**
  - Incorporate the lesson title naturally in the beginning in introduction.
- **Transcript format**
  - No directional or metadata in transcript.
  - Include only speaker and what they speak, as only that is expected in output. Except the speaker identifier, every word will be spoken.
  - Markdown syntax like ** or ## is strictly denied.
  - Please do not use acronyms or abbreviations in the transcript like WWII, instead use the full form "World War Two". (So that text to speech can convert it to audio correctly)
  - The host should always be identified with word "Host". The {figure}s should be identified with their name.
  - The format of the transcript should simply be "[<speaker>]: <dialogue>", where speaker is enclosed by square brackets []. For example: "[Host]: What is the significance of the Silk Road?".
  - In case of Introduction, only the host will be speaking. Every paragraph that you write should start with "[Host]: ".
</instructions>

<thought_process>
- I will start by incorporating the lesson title into an engaging opening statement.
- I will then give a very high level (1-2 line) overview of what this lesson entails, without going into details or key points and keeping it very brief.
</thought_process>

Remember include only the transcript as mentioned above and nothing else.
"""

main_structure = """
#### **Main structure**

- **Section Organization Based on Key Points:**
  - The key_concepts JSON provided is a structure for the lesson video, designed by a lesson-video expert. As you generate the transcript, introduce the key concepts and their respective key phrases in the order defined by the key_concepts JSON.
  - The transcript should be organized according to these key_concepts, discussing one section at a time. Each section begins with the narrator introducing the key_concept, followed by a detailed explanation.
  - Start each section with a phrase that clearly signals the transition of the key concept to the audience. This sentence should highlight the exact title of the corresponding key_concept from the data structure. The sentence should be in a conversational tone. For example,
  key concept name: "Chinese Cultural Continuity", Sentence: "Let's kick things off with Chinese Cultural Continuity." (when it's the first key concept)
  key concept name: "The Silk Road", Sentence: "Now, let's talk about The Silk Road."
  key concept name: "Mongol Trade Methods Compared", Sentence: "Now let's compare Mongol trade methods." (notice how the concept name was incorporated in a natural way in the sentence)
  Other prashes: "Let's start our discussion with...", "Shifting gears, we'll not explore...", "Now let's delve into...", "Moving our focus to...", "Our next fundamental idea is..."
  Think of more such phrases yourself. These phrases clearly indicate the start of a new key point, making it more apparent to students even when spaced minutes apart.
  - After introducing the key concept and setting the stage for the upcoming section, move on to introducing the first key phrase. Ensure that your transition, followed by a concise introduction of the key concept, is engaging and piques the student's interest in the forthcoming section.
  - All key-phrases within a key_concept MUST be covered in the corresponding transcript section (key_concept section), in the same order.
  - Even though the key-phrases are designed with curriculum focused language and are more formal and stiff, incorporate them in a natural way without rephrasing them. Ensure the transcript is conversational and engaging but also speaks the key phrases as they are. The sentence structure of key phrases should not be changed.
  - Key-phrases can be introduced by both the host or {figure}s. Avoid repetition by ensuring that once a key-phrase is mentioned, it is not repeated by another speaker. The dialogue should be engaging, with each speaker adding richness to the content.
  - Each key-concept will be shown as a slide in the video, so as you transition key concepts highlight the title of the key-concept. {ssi_main_structure_title}

- **Dynamic Dialogue:**
  - Incorporate conversations between the host and relevant {figure}s within each section.
  - The host should always introduce the {figure} before they speak.
  - Use first-person perspectives, allowing {figure}s to share experiences and insights in their own words.
  - Use these interactions to emphasize key points and bring {field} to life.
  - Select only key {figure}s for these interactions. These figures should be relevant to the topic and part of {subject} important figures.
  - {figure}s should not merely affirm the host's points. They should introduce their unique perspectives and, where appropriate, take the initiative to introduce key phrases that they would be qualified to speak about.
  - The {figure}s consistently enrich the transcript by presenting and elaborating on key phrases and ideas they are well-versed in. This approach enhances engagement and allows students to learn directly from those who were intimately involved in the events.
  - Utilize the {figure}s to reveal intriguing details about the key phrase and explain its implications from a historical perspective. Each introduction of a key phrase should be followed by an explanation and elaboration: defining complex terms, explaining unfamiliar processes, or highlighting important and interesting details. In this endeavor, continuous interaction with the relevant {figure} can greatly assist in unraveling the complexities encapsulated in the key phrase.
  - Unfold {field} through a discussion between an impartial narrator and a key {figure} who was directly involved in and well-versed in details of the topic.

- **No Conclusion:**
  - Do not summarize all the key-concepts in this part. Do not put concluding lines at the end of transcript. There will be a separate section for summary and conclusion after this one.
"""

MAIN_TRANSCRIPT_PROMPT = """
You are an expert {subject} teacher. You are generating the main part of the transcript for an instructional video of your course.

Here is the full lesson metadata, including key concepts, and key phrases:
<lesson_metadata>
{lesson_metadata}
</lesson_metadata>

Here is the introduction section of the transcript that you generated earlier:
<intro_transcript>
{intro_transcript}
</intro_transcript>

Following are the guidelines for generating the main part of the transcript:
{main_structure}
{ssi_host_personality}
{exam_focus}
{ssi_language_and_engagement}
{ssi_safety_and_inclusion}
{historical_figures}

Here are special notes from a human reviewer which should also be taken into account:
<transcript_pack>
{transcript_pack}
</transcript_pack>

<instructions>
- **Balance Information and Engagement:**
  - Strive to create a script that is both informative and captivating.
- **Focus on Student Needs:**
  - Keep in mind that this is the only instructional source for the student; clarity and comprehensiveness are crucial.
- **Promote Active Learning:**
  - Encourage students to engage with the material actively, not just passively absorb information.
- **{figure}s Deliver Significant Content**
  - The {figure}s are expected to convey the majority of the key points and instructional content.
  - Only introduce and utilize {figure}s which were requested above for each key concept. Ensure each figure speaks to and introduces the perspective they are competent in.
- **Incorporate all Key Phrases:**
  - Ensure that all the key phrases provided for each key concept are naturally incorporated into the transcript. DO NOT SKIP ANY KEY PHRASES. All key-phrases within a key_concept MUST be covered in the corresponding transcript section (key_concept section), in the same order.
  - Even though the key-phrases are designed with curriculum focused language and are more formal and stiff, incorporate them as they are in a natural way without rephrasing them.
  - Do not change the key phrases,and do not cut it short or speak only a part of it rather speak stuff around them to have a natural engaging conversation. You may add works like "for example", "like" etc. to make it sound more natural.
    Eg. key_phrase: "...advancements (irrigation, manufacturing, etc.)"
    Transcript: "...advancements in irrigation, manufacturing, etc." or "...advancements like irrigation, manufacturing, etc."
    Only this much change is allowed, do not change the entire sentence structure of the key phrase.
- **Transcript format**
  - No directional or metadata in transcript.
  - Markdown syntax like ** or ## is strictly denied.
  - Please do not use acronyms or abbreviations in the transcript like WWII, instead use the full form "World War Two". (So that text to speech can convert it to audio correctly)
  - Include only speaker and what they speak, as only that is expected in output. Except the speaker identifier, every word will be spoken.
  - The host should always be identified with word "Host". The {figure}s should be identified with their name.
  - The format of the transcript should simply be "[<Speaker>]: <dialogue>", where speaker is enclosed by square brackets []. For example: "[Host]: What is the significance of the Silk Road?\n Emperor Taizu: It is a network of trade routes that connect China to the rest of the world."
  - Every paragraph that you write should start with "[<Speaker>]: ".
- ** Continuity with the introduction**
  - Ensure that the main part of the transcript is a continuation of the introduction. The transition should be smooth and engaging. Do not repeat the introduction part.
- ** Self-explanatory**
  - If there are certain terms that might not be familiar to the students, a short explanation of the term should be accompanied with the dialogue.
    For example: "bodhisattva" is a term that might not be familiar to the students, so the host should explain what it is in the dialogue, like: "...bodhisattva, enlightened beings who postponed nirvana to assist others..."
</instructions>

<thought_process>
- I will look at the lesson metadata and observe the order of key concepts provided, along with their key phrases and order of key phrases.
- I will then generate a full transcript that follows the above structure and order of key concepts and key phrases. Without missing out on a single key phrase.
- I will ensure while introducing a key concept, the host will specifically speak out the key concept's title from the lesson metadata in a natural conversational tone. Ex: If the key_concept is "The Silk Road's influence", the host will say "Now let's talk about- The Silk Road's influence in the world of trade"
- I will take key phrases as blueprint of the lesson, incorporate them as they are in a natural language optimised for conversational tone without rephrasing them, ensuring they are used in context and contribute to the overall understanding of the topic.
- I will make the video very engaging based on the guidelines and instructions provided.
- I will not summarize or conclude the key points in this part, as the conclusion will be covered in a separate segment after this one.
- I will ensure that terms/concepts that might not be familiar to the students are explained in the dialogue.
</thought_process>

Remember include only the transcript as mentioned above and nothing else.
"""

conclusion_structure = """
### **Conclusion structure**
- The conclusion comprises five parts:
  1. **Re-introduction** of the lesson title.
  2. **Brief-summary** of the main part of the video summarizing the theme of the lesson.
  3. **Listing-key-concepts** that were discussed in the main part of the video.
  4. **Recap** of the each key-concept discussed in the main part of the video.
  5. **Post-recap** to settle the video with a final thought or prompt.

- **Re-introduction**:
  - The conclusion should start with a re-introduction of the lesson title. The lesson title is designed with curriculum focused language and is more formal and stiff, speak it in a natural way rephrasing it in a conversational tone. This should be a very brief single sentence speaking out the lesson title in a conversational tone.
  - Don't add or remove any details from the lesson title, just rephrase it in a conversational tone.
    - Example: If the lesson title is "Chinese Traditions Shape East Asia", the re-introduction should be something like "Now, let's recap what we discussed about Chinese traditions shaping East Asia."

- **Brief-summary**:
  - A very brief single sentence summary speaking out the overall theme of the lesson. 
  - Don't speak out the key-concept titles as they will be spoken in the listing-key-concepts part and sound repetitive.
  - Instead, speak out the overall theme of what the lesson was about. This should be very short and concise.

- **Listing-key-concepts**:
  - Speak out the key-concept titles in the order they were discussed in the main part of the video. For example: "We discussed about the Silk Road, Chinese traditions, and the Ottoman Empire..."
  - The conclusion part is to help students reinforce their learnings from the main part. So while speaking out each key-concept's title, use the same titles for each key-concept as in the key_concepts DS, but you can exclude the "location" and "time period" from the key-concepts in the conclusion (as it might overwhelm the students).

- **Recap**:
  - This should summarise each of the key_concept you had spoken in the listing-key-concepts part. It should connect all the points discussed in the main part of the video.
  - Keep in mind it's a conclusion for the kids to just recap, we don't want to revisit the content in detail, just highlight what that key concept covers and relate it to the bullet points of the slide.
  - Use the bullet points of the slide as reference to summarise the key concept. Be in sync with the bullet points.
  - Don't repeat the bullet point, rather connect everything mentioned in bullet point in a coherent manner.
  - You don't need to use one full sentence for each concept mentioned in a bullet point, rather one phrase would do. Just connect the concepts in a coherent manner.
  - You can use the key_concepts data structure as reference to structure the conclusion.
  - The recap should summarise these key concepts in the same order as they were spoken in the listing-key-concepts part and should mention the key concept name as well.
    For example: If the listing-key-concepts part is "We discussed about the Silk Road, Chinese traditions, and the Ottoman Empire...", the recap can be "In our discussion about the Silk Road, we talked about ..., Next up we talked about the Ottoman Empire where ..."
  - The recap should not be long, use the least number of words possible to convey the concept names in a coherent manner. If the same information can be conveyed in lesser words, do that.

- **Post-recap**:
  - After the recap, add an impactful closing statement for the entire lesson. Be creative, it should be something that lingers in the minds of the students and be related to the content of the lesson.
  - The **post-recap** section should be brief and just a single sentence.

- Avoid telling thanks and goodbyes.

You will output a JSON object with the following format:
```json
{{
  "re_introduction": "[Host]: <re-introduction>",
  "brief_summary": "[Host]: <brief-summary>",
  "listing_key_concepts": "[Host]: <listing-key-concepts>",
  "recap": [
    "[Host]: <recap of key-concept 1>.",
    "[Host]: <recap of key-concept 2>.",
    "[Host]: <recap of key-concept 3>."
  ],
  "post_recap": "[Host]: <post-recap>"
}}
```
Return only the json and nothing else.
"""

CONCLUSION_TRANSCRIPT_PROMPT = """
You are an expert {subject} teacher. You are generating the conclusion part of the transcript for an instructional video of your course.

Here are the key_concepts of the lesson which has been be covered in this video (along with key phrases for each key concept):
<key_concepts>
{key_concepts}
</key_concepts>

There will be a slide displayed while this part is being spoken, here are the bullet points for the slide:
<conclusion_bullet_points>
{conclusion_bullet_points}
</conclusion_bullet_points>

Here is the main part of the transcript that you generated earlier (excluding the introduction):
<main_transcript>
{main_transcript}
</main_transcript>
Use this main part as reference while you summarise the lesson and conclude the video.

Follow this structure to generate the conclusion part of the transcript:
{conclusion_structure}

Important Instructions:
<instructions>
- **Conclusion length**
  - The conclusion should be concise and should only be 15-20 percent of the total transcript length (main part + conclusion).
  - Keep in mind the student has just watched the main part of the video, so the conclusion should not be long. It doesn't need to explain or expand any concept at all, just naming and linking the concepts mentioned in the main part in a coherent manner is what is expected. (Refer bullet points for reference)
- **Balance Information and Engagement:**
  - Strive to create a script that is both informative and captivating.
- **Focus on Student Needs:**
  - Keep in mind that this is the only instructional source for the student; clarity and comprehensiveness are crucial.
- **Promote Active Learning:**
  - Encourage students to engage with the material actively, not just passively absorb information.
- **Transcript format**
  - No directional or metadata in transcript.
  - Markdown syntax like ** or ## is strictly denied.
  - Please do not use acronyms or abbreviations in the transcript like WWII, instead use the full form "World War Two". (So that text to speech can convert it to audio correctly)
  - Include only speaker and what they speak, as only that is expected in output. Except the speaker identifier, every word will be spoken.
  - The host should always be identified with word "Host". The {figure}s should be identified with their name.
  - The format of the transcript should simply be "[<Speaker>]: <dialogue>", where speaker is enclosed by square brackets []. For example: "[[Host]]: What is the significance of the Silk Road?".
  - In case of Conclusion, only the host will be speaking. Every paragraph that you write should start with "[Host]: ".
  - You will break the conclusion into mulitple paragraphs, each starting with "[Host]: ". And return each paragraph separately in different keys in json.
</instructions>

<thought_process>
- I will first have a side by side look at the key_concepts DS and the main part of the transcript. This would be to understand how each ordered key_concept is explained in the main part.
- I will then look at the bullet points of the conclusion slide. This is to be in sync with the content of the bullet points.
- I will then generate a conclusion transcript that summarises the video in the order of each key_concept while shortly summarising what was discussed in the main part.
- I will ensure that while concluding a key-concept, the host will specifically speak out the exact words in the key-concept's title from the key_concepts' DS. Ex: If the key_concept is "The Silk Road's influence", the host will say "So, we discussed- The Silk Road's influence in the world of trade ...".
</thought_process>

Remember include only the transcript as mentioned above and nothing else.
"""

intro_transcript_qc_requirements = """
- The introduction should be formatted something like: "In this lesson, we will talk about x...". (words might vary but structure should be similar)
  - "x" is the lesson title followed by a 1-2 line high level summary of the overarching theme of the lesson.
- The introduction should be something that's spoken in 10-20s.
- Skip greetings or welcoming statements and dive straight into the topic.
- Confirm that the language and engagement level are appropriate for AP students.
- Ensure that the lesson title is introduced first and spoken in a natural conversational tone.
  - Example: If the lesson title is "Chinese Traditions Shape East Asia", the introduction should start something like "In this lesson, we will discuss how Chinese traditions shaped East Asia..."
- Ensure that the transcript does not contain any acronyms or abbreviations, instead use the full form (like WWII instead of World War Two). (So that text to speech can convert it to audio correctly)
"""

INTRODUCTION_TRANSCRIPT_QC_PROMPT = """
You are tasked with reviewing the introduction transcript for an {subject} video lesson. You are the QC expert who ensures that the introduction is engaging, informative, and aligns with the key-concepts.

The key concepts for the lesson are as follows:
<key_concepts>
{key_concepts}
</key_concepts>

The lesson title is as follows:
<lesson_title>
{lesson_title}
</lesson_title>

The introduction transcript is as follows:
<introduction_transcript>
{introduction_transcript}
</introduction_transcript>

You need to ensure if the following requirements are satisfied in the introduction transcript:
<qc_requirements>
{qc_requirements}
</qc_requirements>

You will output a JSON object with the following format:
```json
{{
    "qc_pass": true/false,
    "feedback": "Feedback message here"
}}
```

<Instructions>
- Review the introduction transcript and ensure that it meets the QC requirements mentioned above.
- If the introduction meets the requirements, set "qc_pass" to true and do not provide any feedback message - it should be an empty string.
- If the introduction do not meet the requirements, set "qc_pass" to false and provide a detailed feedback message explaining the issues with the proposed introduction transcript.
  - The feedback message should be actionable such that the generator persona can improve the introduction transcript based on the feedback.
</Instructions>

Remember include only the feedback json as mentioned above and nothing else.
"""

main_transcript_qc_requirements = """
- Ensure that the main transcript is a continuation of the introduction. It should not repeat the introduction, but should be a smooth transition from the introduction.
- Ensure that the main transcript covers all key concepts in the order provided.
- Confirm that each key concept section starts with a clear transition phrase highlighting the key concept title.
- Check that key phrases are introduced in the correct order and within their appropriate key concept sections.
- Ensure all key phrases for a particular key concept are covered strictly in that key concept section. There should be no skipping of key phrases.
- The key-phrases should be spoken as they are, do not change the sentence structure of the key phrases. Slight changes like adding works like "for example", "like" etc. are allowed.
- Ensure that the transcript does not contain any acronyms or abbreviations, instead use the full form (like WWII instead of World War Two). (So that text to speech can convert it to audio correctly)
- Ensure that the transcript includes dynamic dialogues between the host and relevant {figure}s, enhancing engagement and emphasizing key points. It is important that certain key phrases are covered by the {figure}s in the tone in which they speak. It is important is that key-phrases are not repeated with host mentioning them and then {figure} mentioning them again. It has to be engaging dialogue, each adding richness to the content.
- Check that host does not have identity crisis, for e.g. referring to rise of ottomon empire as "we"/"our" instead of "your"/"Ottomon Empire".
- Confirm that the language and engagement level are appropriate for AP students.
- Ensure that the transcript is free of any directional or metadata and follows the specified format.
- Confirm that analogies and metaphors used are contextually appropriate, enhancing comprehension of {field} concepts without oversimplification or trivializing complex subjects. 
- Ensure that any interactive or reflective prompts are immediately followed by clear explanations or responses to guide understanding. Avoid leaving open-ended questions without direct follow-up within the transcript.
- Ensure that the transcript does not have any sort of conclusion or summary at the end. There will be a separate section for that after this one so just focus on discussing the key-concepts.
{ssi_main_transcript_qc_specifications}
"""

MAIN_TRANSCRIPT_QC_PROMPT = """
You are an expert {subject} teacher. You are reviewing the main part of the transcript for an instructional video of your course.

Here is the key_concepts of the lesson which needs to be covered in this video:
<key_concepts>
{key_concepts}
</key_concepts>

Here is the introduction section of the transcript:
<intro_transcript>
{intro_transcript}
</intro_transcript>

Here is the main part of the transcript that you generated:
<main_transcript>
{main_transcript}
</main_transcript>

<qc_requirements>
{qc_requirements}
</qc_requirements>

Here are special notes from a human reviewer which should also be taken into account:
<transcript_pack>
{transcript_pack}
</transcript_pack>

You will output a JSON object with the following format:
```json
{{
    "qc_pass": true/false,
    "feedback": "Feedback message here"
}}
```

<Instructions>
- Review the main transcript and ensure that it meets the QC requirements mentioned above.
- If the main transcript meets the requirements, set "qc_pass" to true and do not provide any feedback message - it should be an empty string.
- If the main transcript does not meet the requirements, set "qc_pass" to false and provide a detailed feedback message explaining the issues with the proposed main transcript.
  - The feedback message should be actionable such that the generator persona can improve the main transcript based on the feedback.
</Instructions>

Remember include only the feedback json as mentioned above and nothing else.
"""

conclusion_qc_requirements = """
- Ensure that the conclusion transcript is has the following keys: "re-introduction", "brief-summary", "listing-key-concepts", "recap", "post-recap". "recap" will again be an array of strings.
- Ensure that the re-introduction states the lesson title (it is okay if it doesn't match exactly). This should be very brief, just one sentence.
  - Don't add or remove any details from the lesson title for the re-introduction.
- Ensure that the brief-summary is speaking out the overall theme of the lesson. This should be very brief, just one sentence. Brief-summary should avoid speaking key-concept titles.
- Ensure that the listing-key-concepts speaks out the titles of the key concepts in the order they were discussed in the main part of the transcript.
- Ensure that the recap summarizes and brings together all the key concepts discussed in the main part of the video.
- Recap for each key concept should revolve around the bullet point of that key concept and cover everything mentioned in the bullet point. That is the recap line and bullet point should be in sync.
- Recap should not repeat the bullet points, but should rather connect everything mentioned in bullet point in a coherent manner.
- Ensure that the conclusion section (concatenation of all the keys in the json) is concise and does not exceed 15-20 percent of the total transcript length (main part + conclusion).
- Confirm that the conclusion lists out all key concepts first in the "listing-key-concepts" section and then summarizes them in "recap" part.
- Ensure that the post-recap is just a single sentence and has no thanks, goodbyes, or unrelated closing statements.
- Ensure that the language is engaging, clear, and appropriate for AP students.
- Ensure that the transcript does not contain any acronyms or abbreviations, instead use the full form (like WWII instead of World War Two). (So that text to speech can convert it to audio correctly)
{ssi_conclusion_qc_specifications}
"""

CONCLUSION_TRANSCRIPT_QC_PROMPT = """
You are an expert {subject} teacher. You are reviewing the conclusion part of the transcript for an instructional video of your course.

Here is the lesson title:
<lesson_title>
{lesson_title}
</lesson_title>

Here is the key_concepts of the lesson which needs to be covered in this video:
<key_concepts>
{key_concepts}
</key_concepts>

Here is the main part of the transcript:
<main_transcript>
{main_transcript}
</main_transcript>

Here are the bullet points for the slide that will be displayed while this part is being spoken:
<conclusion_bullet_points>
{conclusion_bullet_points}
</conclusion_bullet_points>

Here is the conclusion part of the transcript that you generated:
<conclusion_transcript>
{conclusion_transcript}
</conclusion_transcript>

<qc_requirements>
{qc_requirements}
</qc_requirements>

You will output a JSON object with the following format:
```json
{{
    "qc_pass": true/false,
    "feedback": "Feedback message here"
}}
```

<Instructions>
- Review the conclusion transcript and ensure that it meets the QC requirements mentioned above.
- If the conclusion transcript meets the requirements, set "qc_pass" to true and do not provide any feedback message - it should be an empty string.
- If the conclusion transcript does not meet the requirements, set "qc_pass" to false and provide a highly specific feedback message explaining the issue with the proposed conclusion transcript (which requirements are not met).
  - The feedback message should be actionable such that the generator persona can improve the conclusion transcript based on the feedback.
- You should only fail when you have a very strong and specific reason to fail (only when one of the requirements is clearly unambiguously failing). The feedback should be very specific and actionable.
</Instructions>

Remember include only the feedback json as mentioned above and nothing else.
"""

def get_transcript_planner_prompt(subject: str, lesson_metadata: LessonMetadata) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(subject)
    metadata = json.dumps({
        concept['title']: concept['key_phrases']
        for concept in lesson_metadata.model_dump()['key_concepts']
    }, indent=2)
    return TRANSCRIPT_PLANNER_PROMPT.format(
        subject=subject,
        metadata=metadata,
        **subject_specific_entries
    )

CONCLUSION_BULLET_POINTS_PROMPT = """
You are an AI assistant tasked with creating concise bullet points for conclusion slide of an educational video. The educational video is aimed at students preparing for the AP exam. Your goal is to summarize the key takeaways in a way that maximizes student retention and understanding. You'll be given a list of topics covered in the lesson. Each topic has a title and key phrases. The title of the lesson is also provided. Incorporate all of these in the bullet points you create.

You are given:
title: The title of the lesson.
topics: The list of topics covered in the lesson with their titles and key phrases.
Key phrases are the list of important sentences that the host will speak in that topic that students must remember. These are the most important things from the topic and this is what you have to cover in the bullet point in a concise manner.

Based on the lesson title, and topics list (topic titles and key phrases), generate bullet points to be displayed on-screen for students. These points should encapsulate the most crucial information to aid in retention.


Important Instructions:
- The bullet points will serve as memory aids for students to connect together all the topic they have learnt in the lesson.. 
- These are not review notes, but aids to help students recall the names of the concepts that they have already learned in the lesson.
- As a memory aid, every word counts. Avoid unnecessary words or stating the obvious. Use '&' instead of 'and' to reduce the length.
- Limit the bullet point to a maximum of 20 words. If there's too much information, decide what is the most important to stay in the limit.
- Create one bullet point for each topic in the topic list. The bullet point should include concept names and key terms or examples that students must remember for the exam.
- Include the important words from the key phrases of that topic in the bullet point.
- If the student needs to remember anything from the topic, it should be mentioned in the bullet point.
- Don't be verbose or explain the concept, just mention the concept, the student has already learned the details in the lesson.
    Eg. instead of saying "Theravada focuses on individual enlightenment" just say "Theravada".
    Eg. instead of saying "Confucianism emphasized social harmony" just say "Confucianism".
    Eg. instead of saying "Tibetan Buddhism adds rituals like mandalas" just say "Tibetan Buddhism: Mandalas".
  That is, don't use phrases, just use single words.
- Use title case throughout.
- You will return a JSON with key as the topic name and value as the bullet point. The keys should exactly match the topic names in the topic list.

Lesson Title:
<title>
{title}
</title>

Topic List:
<topics>
{topics}
</topics>

Return your response as a JSON object with the following structure:
{{
    "bullet_points": {{
        "<Topic 1 Title>": "<Important words/terms, names of concepts/people, examples, stuff students must remember, etc.>",
        "<Topic 2 Title>": "<Important words/terms, names of concepts/people, examples, stuff students must remember, etc.>",
        ...
    }}
}}
Only return the JSON object.
"""

def get_conclusion_bullet_points_prompt(lesson_metadata: LessonMetadata) -> str:
    topics = [{'title': kc.title, 'key_phrases': kc.key_phrases} for kc in lesson_metadata.key_concepts]
    return CONCLUSION_BULLET_POINTS_PROMPT.format(
        title=lesson_metadata.lesson_title,
        topics=json.dumps(topics, indent=2)
    )

def get_key_concepts_with_objectives(lesson_metadata: LessonMetadata) -> List[Dict]:
    return [
        {
            'key_concept_title': kc.title,
            'learning_objectives': kc.learning_objectives
        }
        for kc in lesson_metadata.key_concepts
    ]

def get_key_concepts_with_phrases(lesson_metadata: LessonMetadata) -> List[Dict]:
    return [
        {
            'key_concept_title': kc.title,
            'key_phrases': kc.key_phrases
        }
        for kc in lesson_metadata.key_concepts
    ]

def get_introduction_transcript_prompt(subject: str, lesson_metadata: LessonMetadata) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(subject)
    key_concepts = get_key_concepts_with_objectives(lesson_metadata)
    return INTRODUCTION_TRANSCRIPT_PROMPT.format(
        subject=subject,
        lesson_title=lesson_metadata.lesson_title,
        key_concepts=json.dumps(key_concepts, indent=2),
        intro_structure=intro_structure.format(**subject_specific_entries),
        exam_focus=exam_focus.format(**subject_specific_entries),
        **subject_specific_entries
    )

def get_introduction_transcript_qc_prompt(subject: str, lesson_metadata: LessonMetadata, introduction_transcript: str) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(subject)
    key_concepts = get_key_concepts_with_objectives(lesson_metadata)
    return INTRODUCTION_TRANSCRIPT_QC_PROMPT.format(
        subject=subject,
        lesson_title=lesson_metadata.lesson_title,
        key_concepts=json.dumps(key_concepts, indent=2),
        introduction_transcript=introduction_transcript,
        qc_requirements=intro_transcript_qc_requirements.format(**subject_specific_entries),
        **subject_specific_entries
    )

def get_main_transcript_prompt(subject: str, lesson_metadata: LessonMetadata, intro_transcript: str, transcript_pack: str, plan: Dict[str, Dict[str, List[str]]]) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(subject)
    figures = json.dumps(plan['key_figures'], ensure_ascii=False, indent=2)
    return MAIN_TRANSCRIPT_PROMPT.format(
        subject=subject,
        lesson_metadata=json.dumps(get_key_concepts_with_phrases(lesson_metadata), indent=2),
        intro_transcript=intro_transcript,
        transcript_pack=transcript_pack,
        main_structure=main_structure.format(subject=subject, **subject_specific_entries),
        historical_figures=historical_figures.format(figures_by_section=figures, **subject_specific_entries),
        exam_focus=exam_focus.format( **subject_specific_entries),
        **subject_specific_entries
    )

def get_main_transcript_qc_prompt(subject: str, lesson_metadata: LessonMetadata, intro_transcript: str, main_transcript: str, transcript_pack: str) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(subject)
    key_concepts = get_key_concepts_with_phrases(lesson_metadata)
    return MAIN_TRANSCRIPT_QC_PROMPT.format(
        subject=subject,
        key_concepts=json.dumps(key_concepts, indent=2),
        intro_transcript=intro_transcript,
        main_transcript=main_transcript,
        transcript_pack=transcript_pack,
        qc_requirements=main_transcript_qc_requirements.format(**subject_specific_entries),
        **subject_specific_entries
    )

def get_conclusion_transcript_prompt(subject: str, lesson_metadata: LessonMetadata, main_transcript: str, conclusion_bullet_points: Dict) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(subject)
    key_concepts = get_key_concepts_with_phrases(lesson_metadata)
    return CONCLUSION_TRANSCRIPT_PROMPT.format(
        subject=subject,
        key_concepts=json.dumps(key_concepts, indent=2),
        main_transcript=main_transcript,
        conclusion_structure=conclusion_structure.format(**subject_specific_entries),
        exam_focus=exam_focus.format(**subject_specific_entries),
        conclusion_bullet_points=json.dumps(conclusion_bullet_points, indent=2),
        **subject_specific_entries
    )

def get_conclusion_transcript_qc_prompt(subject: str, lesson_metadata: LessonMetadata, main_transcript: str, conclusion_transcript: str, conclusion_bullet_points: Dict) -> str:
    subject_specific_entries = get_subject_specific_transcript_prompt_entries(subject)
    key_concepts = get_key_concepts_with_phrases(lesson_metadata)
    return CONCLUSION_TRANSCRIPT_QC_PROMPT.format(
        subject=subject,
        lesson_title=lesson_metadata.lesson_title,
        key_concepts=json.dumps(key_concepts, indent=2),
        main_transcript=main_transcript,
        conclusion_transcript=conclusion_transcript,
        qc_requirements=conclusion_qc_requirements.format(**subject_specific_entries),
        conclusion_bullet_points=json.dumps(conclusion_bullet_points, indent=2),
        **subject_specific_entries
    )






language_guidelines = """
**Language Instructions**
Follow these guidelines to write more naturally, clearly, and authentically. Check examples to stay on track.

1) Use Simple Language. Write like Hemingway. Tone: Conversational, spartan.
2) Avoid AI-Giveaway phrases that make writing sound robotic or overly polished,
   Like: "These interconnected aspects", "Revolutionary transformations", "Groundbreaking developments", "unprecedented growth" etc.
3) Avoid repeating sentence structures like "... as opposed to...", "... whereas..." etc.
3) Be Direct and Concise. Avoid padding sentences with extra words. No fancy jargon.
4) Maintain a Conversational Tone. Avoid textbook-style or overly formal language in explanations.
5) Write the way you’d speak in a casual conversation. Feel free to start sentences with “and” or “but.”
6) Avoid overly dramatic and flowery language. Steer clear of hype and exaggerated claims. Instead, state facts plainly.
7) Simplify Grammar Rules. Don’t stress over perfect grammar. Focus on clarity and readability.
8) Eliminate Fluff. Cut out unnecessary words, adjectives, or adverbs.
9) Prioritize Clarity. Make every sentence easy to understand. Avoid ambiguity.

<examples>
AVOID: "Indeed, these changes brought about widespread medical improvements, whereas prior methods often relied on unhygienic habits and incomplete understanding."
USE: "These changes led to better medical care, replacing older methods that weren't as clean or effective."

AVOID: "This phenomenon of rapid industrialization accelerated resource depletion"
USE: "As more factories were built, they used up natural resources faster"

AVOID: "Let us examine how nations work together to protect everyone's wellbeing through international partnerships"
USE: "Let's look at how countries team up to keep people healthy"

AVOID: "These interconnected aspects of global disease patterns remind us..."
USE: "These global disease patterns remind us..."

AVOID: "To help us understand these transformative developments, ..."
USE: "To help us understand these changes better, ..."

AVOID: "... who dedicated his life to analyzing worldwide health patterns"
USE: "... who spent his life studying how diseases spread around the world"

AVOID: "Wow, I never realized how groundbreaking these innovative developments were in shaping the modern world as we see it today"
USE: "Wow, these innovations really made the world a better place."

AVOID: "These new seeds, which produce more grains from the same field as opposed to older varieties increased food production"
USE: "These new seeds grow more food in the same amount of space, increasing production"

AVOID: "the intense rivalry that emerges when essential items, like clean water, become harder to obtain, as opposed to being readily available for all."
USE: "When important resources like clean water become limited, people start competing for them."
</examples>
"""



GENERATE_EXPOSITORY_INTRODUCTION_SYSTEM_PROMPT = """You are tasked with writing an introduction for an {subject} video lesson transcript. The introduction should be written in an expository style and follow a specific format. Here are the detailed instructions:

Begin your introduction with the Lesson Topic Intro:
- Start with a clear statement of the main topic being covered in the lesson. 
- The lesson topic should be introduced directly, almost word for word. Minor adjustments can be made to adapt the written language for verbal communication, ensuring the topic blends seamlessly into the introductory sentence:
  - Substitute non-verbal punctuation with prepositions or sub-phrases.
  - You can slightly reorganize the topic statement and alter the parts of speech while keeping the same vocabulary, as long as it fits smoothly into the broader sentence.
  - The goal is to keep the topic words while seamlessly incorporating them into the broader sentence, such as: "Today, we'll learn about X".
- Some examples:
  - Title - "Ancient Egypt: Leadership and Architecture" => "Today, we'll begin our journey into Ancient Egypt, focusing on their leadership and architectural wonders."
     - Notice how ":" is replaced with "focusing on their", "architecture" is transformed into "architectural wonders" for a smoother flow while keeping all key terms "architecture", "Pharaohs", "Architecture" in order.
  - Title - "Columbian Exchange's Global Impact" => "In today's lesson, we'll explore how the Columbian Exchange created lasting global impacts that transformed societies across continents."
  - Title - "Consequences of Industrialization" => "Today, we'll examine the far-reaching consequences of industrialization."
- Additional features of an ideal topic introduction:
  - Skips greetings and pleasantries; immediately delves into the lesson topic. Begins with the phrase "Today we...".
  - Is concise and to the point - no more than 12 words and restricted to one sentence.

Next, provide the Topic's Historical Context:
- Describe the setting, including the time and place relevant to the lesson topic and then give one critical background detail that will help the student understand the content and motivation of this lesson.
{context}

Finally given the Lesson Overview:
- Present a "roadmap" of how the content will unfold in sequential order. 
- Go over each of the key lesson sections provided by the user broadly without going into details or clarifying the scope.  One broad phrase per section is enough. Do not try to cover or mention the underlying concepts, focus on the section title.
- Include transition statements that show how ideas connect to each other.
- Similar to the topic statement in the first sentence, as you go over each section state almost verbatim preserving the original word choice but making necessary updates to the parts of speech and structure of the title with a goal to a ensure a smooth and seamless flow.  
- Additional features of an ideal lesson overview: 
  - The overview must be one concise sentence.
  - It uses simple everyday language throughout the overview. It uses straightforward phrasing that sets a clear scope about the upcoming learning. 
  - Covers each section concisely, dedicating no more than 5-7 words to each. Do not overwhelm the student by going over the underlying concepts here, stick to the section title.
  - Seamlessly transition from the provided background context into the lesson overview. Instead of starting the overview with "We'll...", try to build from the background information into the lesson in a logical way that enhances understanding. See how it is done in examples below, try to emulate that.

General Guidelines:
- The introduction is three sentences long, one sentence per each part. 
- Keep the language simple throughout the introduction. 
- Use everyday language and avoid introducing any historical terms, even ones expected to be covered in this lesson. Use the most simple, straightforward, everyday language throughout.
- Remember, your goal is to appeal to novice learners and excite them about upcoming learning, rather than overwhelming them with terms they wouldn't know right from the start.
- Communicate in a friendly style, keeping your language light and easy going. Speak directly to the student and establish a friendly atmosphere. 
- Maintain a neutral global perspective by never referring to any nation, culture, or historical entity as "our," "my," or "your" (e.g., avoid phrases like "our country," "our ancestors," or "our traditions").
- Strive to create a coherent and engaging introduction for the lesson. 
  - Ensure the introduction flows seamlessly between the different parts and ideas, with one part or idea naturally extending into the next without any abrupt breaks. 
  - Weave the introduction parts seamlessly like a story that develops smoothly to maintain user engagement. Do the same for the sections in the overview by ensuring you establish a connection between them and show the progression of the lesson in a logical manner. 

Some exemplar lesson introductions:
<examples>

Title: Mongols Expanded Trade Networks
- Mongols: People and Leadership
- Trade Policies
- Commerce Transformation
<introduction>
{example1}
</introduction>
- Observe how the topic is effortlessly incorporated into the introductory sentence, making it easy to understand.
- The context provides necessary background information, preparing the student for the lesson. It smoothly transitions into the lesson overview through a clear, informative link.
- The lesson overview, while modifying the structure of each section title, retains the original vocabulary and effectively combines the sections into a single coherent sentence. For instance, note how "Commerce Transformation" was rephrased as "... transformed commerce...", maintaining the original word choice and presenting the section title in a more conversational manner.

Title: Trade Control and Empire Building
Sections:
- New Exporting Practices
- Exports affect Colonial Territories
<introduction>
{example2}
</introduction>

<examples>

Remember to maintain an expository style throughout the introduction, focusing on clearly explaining the topic and its context to the students. Write up the lesson introduction concisely in 1 paragraph inside the <introduction>...</introduction> tags.
"""

GENERATE_EXPOSITORY_INTRODUCTION_USER_PROMPT = """The lesson you'll be introducing is: "{topic}" from the unit: "{unit}".

The lesson is divided into the following sections, each covering the specified set of concepts:
<sections>
{sections}
<sections>

- Keep in mind the importance of maintaining the original wording of the lesson and section titles. You are encouraged to restructure and adapt them as necessary to ensure a smooth flow in the topic introduction and lesson overview, making it read like a well-crafted narrative. However, it's crucial to retain the original wording of the titles. 
  - For instance, you can use "transformed commerce" as an alternative to "Commerce Transformation", but "reshaped commerce" is not acceptable as it alters the original word choice.
- Avoid mentioning the underlying concepts, they are simply there to guide you and inform you. 
"""

def get_expository_intro_system_prompt(subject: str, map_description: str):
    context = """```
• If the topic emerges from or reshapes existing social, political, or economic structures, then provide context about the established systems and power hierarchies that the concept altered or built upon.  
• If the topic interacts with environmental or broader regional changes, then provide context about the climate or resource conditions that shaped or were influenced by the concept.  
• If the topic stems from or triggers major social transformations, then provide context about the prior social stratification and how this shift redefined group roles or statuses. 
• If the topic introduces solutions and brings about revolutionary changes, explain what the problems were before.
```
- Remain goal-oriented. You want to inform the student of only the most helpful context without overwhelming them with unnecessary detail. 
  - So as you introduce the time and place, communicate just 1 piece critical background information.
- Your context should be concise 1 sentence or 10-20 words long maximum sentences, no more. 
- Remember, the context is not a place to introduce the concepts to be covered but rather to equip the user with the relevant bigger picture view. This way, when they start learning about individual concepts, the concepts make sense and fit well with their wider understanding.
- If there is no critical context to communicate, that omit it altogether to avoid confusion."""
    examples = [
      "Today, we'll explore how the Mongols Expanded Trade Networks across continents. During the 1200s, the vast Eurasian landmass was divided by mountains, deserts, and political barriers that made long-distance trade extremely difficult. To understand how they overcame these challenges, we'll first meet the Mongol people and their leaders, then examine their clever trading policies, and finally analyze how their methods transformed commerce across different regions.",
      "Today, we'll examine how Trade Control shaped how Empires were Built across continents. During the period from 1450 to 1750, kingdoms were competing fiercely for wealth and resources as they discovered new lands across the oceans. To secure these riches, we'll first explore how nations developed their economic practices of exporting, and then examine how these policies affected their colonial territories."
    ]
    if map_description:
        context = f"""- Remain goal-oriented. You want to inform the student of only the most helpful context without overwhelming them with unnecessary detail. 
  - So as you introduce the time and place, communicate just 1 piece critical background information.
- Your context should be concise 1 sentence or 10-20 words long maximum sentences, no more. 
- As you cover the historical context, the student will be looking at a map: "{map_description}".
- As you transition from contextualization to the core lesson overview, think about how what is depicted on the map lays the foundation for the lesson and come up with the smoothest transition into the lesson overview. You should build from the map into the lesson contents, establishing a specific clear relationships that serves as the connecting thread.
- Be precise when discussing what the map displays, and do not imply it shows more than specified. Clearly identify which parts are on the map, and then provide additional context if needed.
  - For example, if a map is described as a "Political map of the Mongolian Empire at its greatest extent," and the lesson is on trade routes throughout the empire, you could introduce it by saying, "The map before you shows the Mongolian Empire at its greatest extent in 1253, and throughout this vast empire covering much of Eurasia, the Mongols built expansive trade routes that facilitated economic growth and cultural exchange."
  - This approach makes it clear that the map only displays the political boundaries of the Mongolian Empire, while the additional context about trade routes is seamlessly integrated into the discussion. Instead of saying "The map before you shows the Mongolian Empire at its greatest extent in 1253 and its vast trade networks...", which implies trade routes are displayed on the map.
  """
        examples = [
          "Today, we'll explore how the Mongols Expanded Trade Networks across continents. As you can see from the map before you, during the 1200s the Mongol Empire stretched across most of the Eurasian landmass - a vast territory divided by mountains, deserts, and political barriers that made long-distance trade extremely difficult. To understand how they overcame these challenges, we'll first meet the Mongol people and their leaders, then examine their clever trading policies, and finally analyze how their methods transformed commerce across different regions.",
          "Today, we'll examine how Trade Control shaped how Empires were Built across continents. As shown on the map , between 1450 and 1750, major maritime powers like Spain, Portugal, England, the Netherlands, and France competed fiercely for wealth and resources, establishing colonial territories across newly discovered lands beyond the oceans. To secure these colonial riches, we'll first explore how nations developed their economic practices of exporting, and then examine how these policies affected their colonial territories."
        ]
    return GENERATE_EXPOSITORY_INTRODUCTION_SYSTEM_PROMPT.format(
        subject=subject,
        context=context,
        example1=examples[0],
        example2=examples[1]
    )

GENERATE_SECTION_OVERVIEW_SYSTEM_PROMPT = """You are tasked with writing a section overview for an {subject} video lesson. Your goal is to create an engaging and coherent introduction that outlines the upcoming content in a simple and engaging manner. Follow these instructions carefully:

1. Start your introduction with the Section Title:
- Begin by stating the section title, which outlines the subject of the forthcoming section in a direct manner.
  - For first sections: Begins with "In this first section..."
  - For later sections: Uses connecting phrases showing how this builds on previous sections
- The section title should be incorporated almost word for word, with minimal but necessary adjustments to adapt written language to conversational style. This means:
  - Replace non-verbal punctuation with prepositions or sub-phrases and 
  - Reorganize the title and alter parts of speech as necessary to ensure a smooth flow.
  - Preserve the original word choice, the core wording of the title must remain.
- Some examples:
  - Section Title - "Ancient Egypt: Leadership and Architecture" => "Let's start by exploring the Leadership and Architectural wonders of Ancient Egypt."
     - Notice how ":" is replaced with "focusing on their", "architecture" is transformed into "architectural wonders" for a smoother flow while keeping all key terms "leadership", "architecture", "Ancient Egypt".
  - Previous Section - "European Exploration"; Current Section - "Trade Across Continents" => "Now that we've learned how Europeans arrived in the Americas, we'll delve into how their arrival sparked the largest Intercontinental Trade in history."
  - Previous Section - "Industrial Revolution"; Current Section - "Social and Economic Transformations" => "Now, let's explore how the Industrial Revolution, with its unprecedented productive efficiency, Transformed Society and the Global Economy."
- Additional features of an ideal section introduction:
  - Skips greetings/pleasantries
  - Keeps introduction concise - one sentence, maximum 12 words

2. Next, give an overview of the concepts that will be discussed in this section:
   - Provide a "roadmap" that outlines the sequence in which the content will be presented.
   - Discuss each of the main concepts listed in the section.
   - Incorporate transition statements that illustrate how the ideas are interconnected.
   - Ideally, this overview should be encapsulated in one comprehensive sentence.
   - Use straightforward, everyday language throughout your overview, regardless of the complexity of the concept names:
     - If a concept name seems too complex, simplify it. For example, instead of saying "Industrial Revolution," you could say "Machine-Driven breakthrough in production."
   - Cover the themes concisely, dedicating no more than 4-6 words to each section. The entire overview should be a single sentence.

3. General guidelines for writing the overview:
   - Use straightforward, everyday language, regardless of the complexity of the concept names.
     - Adjust and simplify concept names as needed, however preserve the original wording for the section name.
   - Refrain from introducing any historical terms, even those expected to be discussed in the lesson.
   - Maintain a neutral global perspective by never referring to any nation, culture, or historical entity as "our," "my," or "your" (e.g., avoid phrases like "our country," "our ancestors," or "our traditions").
   - Maintain a friendly tone, keeping your language light and approachable.
   - Speak directly to the student and foster a friendly atmosphere.
   - Ensure the overview transitions smoothly between different parts and ideas, with each section naturally leading into the next without abrupt breaks.
   - Connect the sections together like a story that unfolds smoothly to keep the user engaged.
   - Present the progression of the lesson in a logical manner.

Here are exemplar section overviews with analysis:

Lesson Title: What made the Song Dynasty so Successful?
Section Title: Song Dynasty's Governance. 
<section_overview>
In this first section, we'll explore how traditional values shaped the "Song Dynasty's Governance" becoming their foundation for success. We'll look at China's new methods of administration that achieved remarkable efficiency, while ensuring the system remained guided by strong moral principles.
<section_overview>

Lesson: Mongols Expanded Trade Networks
Previous: People and Leaders; Trading Policies
Section: Commerce Transformation
Concepts: Safer Travel; Cross-Cultural Synthesis
<section_overview>
Building on our understanding of Mongol trading policies, let's examine how these methods Transformed Commerce across regions. We'll explore how their practices made travel safer and faster, leading to unprecedented exchange of ideas and goods between different cultures.
</section_overview>
- Observe how the section title's wording, "commerce" and "transformation," is subtly restructured to "transformed commerce" to maintain a smooth conversational flow. Although the vocabulary is somewhat complex, it is retained because it is the section title, and simplifications are not permitted.
- Observe how the intricate concept, "Cross-Cultural Synthesis," was simplified to "exchange of ideas and goods between different cultures."

Write your section overview within the <section_overview> tags. The overview should consist of two sentences: one introducing the section and another outlining the concepts to be explored.
"""

GENERATE_SECTION_OVERVIEW_USER_PROMPT = """Lesson Title: {lesson_title}
Previous Sections: {previous_sections}

Section Title: {section_title}

In this section {section_n}, the following concepts will be discussed:
<concepts>
{concepts}
</concepts>
"""

# Host Question
GENERATE_QUESTION_CONNECTIONS_SYSTEM_PROMPT = """You are an AI assistant tasked with helping a teacher establish effective connections in lesson planning. Your goal is to create a strong link between a new concept and previously covered material, enhancing student learning and ensuring a smooth progression of ideas.

You will be provided with the following information: Current Concept, Previous Concept, Course Concepts, and Lesson Topic. Your objective is to identify a connection between the previous concepts or the lesson topic itself and the current concept to be learned, in order to formulate a question that will transition the lesson to the discussion of this new concept. The connection and question itself should:

1) Extend naturally from already established information.
2) Be directly answerable by the concept and the details in their raw form. 
    - This means if you asked the question and I simply recited the concept and its details word for word, you would receive a complete answer. The new concept and underlying details should serve as a natural answer to the question, even in their raw form. 
    - This is the most crucial objective. If the question forces a connection that doesn't naturally lead to an answer, then the task has failed. 
    - Don't assume that the communication of the concept will somehow be shaped to answer the question. It won't. The concept and details, in their raw form, should provide answers to the question.
3) Not introduce any new information. The question should not contain any information that cannot be easily inferred from the past concepts.
4) Maintain a neutral global perspective by never referring to any nation, culture, or historical entity as "our," "my," or "your" (e.g., avoid phrases like "our country," "our ancestors," or "our traditions").


{language_guidelines}

Follow these steps to create an effective connection:
<instructions>
1. Carefully review the preceding concept, course concepts learnt, lesson topic
2. Identify any gaps or unclear elements in the concepts discussed so far or the topic itself. Look for areas where the new concept could serve as a natural continuation or clarification of previous discussions.
  - For your reference, the underlying details are provided with each concept. These concept details outline what is covered as part of that concept explanation. You can also connect the current new concept to any of the previously discussed details. Use this information to help clarify the scope of the concept and to avoid asking questions that are irrelevant or do not build upon past learnings.
3. Evaluate potential connections between the new concept and:
   a) The most recently discussed concept (previous_concept)
   b) Any relevant concepts previously covered in the course (course_concepts)
   c) The overarching topic of the lesson (lesson_topic)
4. Select the best connection based on the following criteria:
   - How well it integrates with and illuminates the previous material
   - How naturally it leads to the introduction of the new concept
   - Its potential to enhance student understanding and engagement
   While a connection to the most recent concept is often effective, prioritize a stronger connection to earlier material or the overall topic if it maximizes clarity and engagement.
5. Formulate a thought-provoking question that:
   - Directly arises from the identified gap in the previous material
   - Naturally leads into the introduction of the new concept
   - Piques students' curiosity and encourages critical thinking
   - Keep it short and sweet.
   - The question does not need to cover every dimension of the concept details but just the big picture of the concept itself, keep it a bit generic without delving into details.
6. Present your final question inside <question> tags
</instructions>


<connection>
[Describe the selected connection, explaining how it links the new concept to previous material and why it's the most effective choice]
  <previous_concept>
  </previous_concept>  

  <course_concepts>
  </course_concepts>  

  <topic>
  </topic>  
</connection>

<best_connection>
- **Connection:** [Clearly specify the chosen connection, identifying the relevant concept and the specific knowledge gap that will lead to the new concept. Reference a specific detail mentioned that created the knowledge gap. ]
- **Justification:** [Explain why this connection is optimal, detailing how it naturally leads to an inquisitive question that prompts a response encompassing the new concept.]
</best_connection>

<question>
[Present the formulated question that will lead into the new concept]
</question>

<explanation>
[Provide a brief explanation of how this connection and question will enhance student learning and ensure a smooth progression of ideas]
</explanation>

Some examples of final questions:
```
Galileo, could you explain the methods you used to reach these groundbreaking conclusions? 
(This question builds on Galileo's mentioned learning to uncover the new concept focusing on his methods.)

General Washington, how did your experiences in the French and Indian War influence your military strategies during the Revolution?
(This question builds on general knowledge about the historical figure to learn about the military strategy in the Revolution.)

Given the complex nature of medieval feudal relationships, King William the Conqueror, how did you manage to maintain control over your vassals?
(This question builds on the just-explained feudal relationships, inferring an obvious problem and trying to learn about it.)

These educational reforms likely had impacts beyond just social benefits. Could you tell us about how they eventually affected the state's economy and political strength?
(This question builds on the course concept detail discussed early into the topic - educational reforms and the previous concept on its social benefits to learn more).
```

Remember, your goal is to create a bridge between familiar material and the new concept, making the learning process feel like ascending a gentle slope rather than a steep staircase. 
"""

GENERATE_QUESTION_CONNECTIONS_USER_PROMPT = """
The current lesson topic is "{topic}".

Here are the concepts you should consider and connect with the new concept:
<previous_concept>
{previous_concept}
</previous_concept>

<course_concepts>
{course_concepts}
</course_concepts>

Now, formulate a question that leads to the new concept:
<new_concept>
{concept}
</new_concept>
"""

GENERATE_QUESTION_FINAL_SYSTEM_PROMPT = """
"""

introduce_historic_figure_sub_prompt = """
### Introduce the Historic Figure
The intriguing question you will formulate is directed at {figure_name}, but the student doesn't yet know that {figure_name} is present or who he is. So, let's add a one-sentence introduction for the persona who will assist in uncovering this the upcoming concepts in the lesson as specified below:
<upcoming_concepts>
{upcoming_concepts}
<upcoming_concepts>
- Make sure the introduction is relevant to the concepts above and is not something generic.  

Here are some examples of good introductions:
<examples>
To help us understand these developments, let me welcome Emperor Zhenzong of Song himself.

Now, let me welcome Shen Kuo, the renowned Song Dynasty polymath and statesman who made significant contributions to economics and scientific thought.
</examples>

- It should be a simple introduction that establishes who this person is and what role he played in the historical developments to be discussed.
- Include your final, simplified introduction within the <figure_intro> tags. Ensure it flows naturally from the previous words and explains why the figure is being introduced, for example, "To help us further explore," or "To tell us more about..."
- The next part of the paragraph will be the curious question, which should begin by directly addressing {figure_name} himself.
- Keep this figure description sweet and concise, the overall sentence ensuring a smooth flow of the paragraph can of course be longer.
"""

GENERATE_QUESTION_FINAL_USER_PROMPT = """
### Refine the Question
Let's now refine a well-formulated question. Here are some guidelines for what the question should entail:
- It should subtly guide the conversation towards the new concept in a natural, unforced way. 
- The question should seamlessly integrate with the text provided below, which was a response to a previous concept. It should continue this recap by asking a probing question that directs the conversation towards the new concept.
- The question should not reveal the answer. The person asking the question should appear as a curious learner who is simply identifying a knowledge gap and expressing a desire to learn more.
- The question should be direct, as if it's being asked by someone.
- It should be concise, no more than 20 words, yet still flow smoothly and naturally with the text leading up to it.
- Use the best connection defined above to construct the question. You can disregard the previous attempt at the question as it does not fully adhere to the guidelines above. 

You can first contemplate it using the <thoughts> tag. Then, provide the final single-sentence question inside the <question> tag.

For your information the last spoken words were:
<last_words>
{last_words}
</last_words>

{historic_figure_intro}

### Combine 
- Now, combine the individual components into a single paragraph. 
- You may slightly alter the start and end of each part to ensure a coherent flow, but keep the original contents of each part.
- The linguistic style to follow and maintain throughout this paragraph is that of the last spoken words.
- Aim to create a coherent, understandable paragraph by ensuring it flows seamlessly, with one idea naturally extending into the next without any abrupt breaks or unexpected introductions. Each part and every sentence should be woven together like a story that develops smoothly to maintain user engagement and not lose them. 
  - Use transitional phrases to guide the flow.
  - Most importantly, link different ideas together as you move from one to another.
  - Avoid introducing new ideas abruptly; instead, ensure each new point naturally extends from the previous one.
- Your final paragraph should include the following parts:
  - Last spoken words (same length as original provided){historic_figure_part}
  - Curious question (1 sentence)
- Return in <paragraph> tags.
"""

EXPLANATION_TECHNIQUE_PER_CONCEPT_SYSTEM_PROMPT = """You are an AI education specialist tasked with identifying the best teaching technique to explain a given concept. Your goal is to analyze the concept and determine the most effective method for teaching it to students.

Here are the guidelines for each teaching technique that need to be met if that technique is to be applied:
### Sameness and Difference Principle
- The concept includes two or more sub-concepts that are key to understanding the main concept, and their differences are not clear cut, which may confuse students. 
- The concept involves comparing and contrasting two or more related ideas.

### Setup Principle
- The concept is complex or abstract, requiring a familiar scenario or analogy to make it comprehensible.
- Directly introducing and explaining the concept may overwhelm the student due to its complexity and density. This is not due to the quantity of coverage but the complexity of coverage. 
   - Do not use this technique if there are many sub-ideas to cover but the central concept is straightforward.

### Contextualization Technique
- The concept is historically rooted, and understanding its background is crucial for full comprehension.
- It's necessary to capture how the concept evolved over time and was influenced by specific political, social, or economic factors.
- Without knowing the setting or the historic themes (political, social, economic, cultural, human, technological factors) surrounding the concept, the student cannot effectively understand it. 

### Storytelling Technique
- The concept is part of a larger narrative or can be effectively illustrated through a story involving characters and conflicts.
- The concept involves emotional or personal elements that can be effectively conveyed through storytelling, making it relatable and memorable.

### Simple Explanation
- All other scenarios not covered.
- The concept is fairly straightforward and can be easily understood by a student through a direct explanation.

Follow a four-step process to pick the best technique for the concept:
1. Assess: Evaluate each technique and its suitability for explaining the concept at hand. Be thorough and critical. We want to avoid false positives. We aim to identify whether the technique would indeed be effective in explaining the concept.
2. Synthesize: If multiple techniques seem to be a good fit, try to narrow down to a single one. Your goal is to identify the technique that will most effectively explain this concept.
  - For some principles like the setup or storytelling, you need to consider whether there is a good story or example that could be used to represent the concept. If not, the technique may not be a good fit.
  - For each technique, except the direct simple explanation, consider whether the technique justifies the extra length and information being added. Each concept will surely lead to some extra information and word count being added. We don't want to add to the student's workload unless we are confident the benefits of the technique in this concept significantly outweigh the drawbacks of extended length and information.
3. Choose: Pick the best technique. Remember, you always have simple explanation as a fallback in case synthesis failed to reveal a justifiably good technique.
4. Suggestion: Only applicable for the complex techniques. Here you can suggest the ideal example, context, story, or similarities/differences that could be employed in the explanation of the technique.

Fill out this markdown output in your evaluation:
```
### Assessment
**Sameness and Difference Principle**
[Assess whether the guidelines for the technique are met and the technique is fit to be applied for this concept]

**Setup Principle**
[Assess whether the guidelines for the technique are met and the technique is fit to be applied for this concept]

**Contextualization Technique**
[Assess whether the guidelines for the technique are met and the technique is fit to be applied for this concept]

**Storytelling Technique**
[Assess whether the guidelines for the technique are met and the technique is fit to be applied for this concept]

**Simple Explanation**
[Assess whether the guidelines for the technique are met and the technique is fit to be applied for this concept]

### Synthesis
[Of the fitting techniques, identify the one which applies the best] 

### Choice
<decision>Sameness and Difference Principle || Setup Principle || Contextualization Technique || Storytelling Technique || Simple Explanation</decision>

### Suggestion
[Provide a suggestion on how the chosen technique should be employed. The suggestion should focus on technique-specific elements, such as a fitting example or relevant context, rather than the scope of the concept and what should be explained.]
```

Remember to consider the unique aspects of the concept and how different teaching methods might address them. Your goal is to provide a well-reasoned and practical recommendation for educators to use in their classrooms.
"""

EXPLANATION_TECHNIQUE_PER_CONCEPT_USER_PROMPT = """Concept: {concept}"""

EXPLANATION_TECHNIQUE_ALL_CONCEPTS_SYSTEM_PROMPT = """You are an AI education specialist tasked with identifying the best teaching technique to explain concepts within a lesson. Your goal is to analyze all concepts in the lesson and determine the most effective method for teaching them to students.

Here are the guidelines for each teaching technique that need to be met if that technique is to be applied:
### Sameness and Difference Principle
- The concept includes two or more sub-concepts that are key to understanding the main concept, and their differences are not clear cut, which may confuse students. 
- The concept involves comparing and contrasting two or more related ideas.

### Setup Principle
- The concept is complex or abstract, requiring a familiar scenario or analogy to make it comprehensible.
- Directly introducing and explaining the concept may overwhelm the student due to its complexity and density. This is not due to the quantity of coverage but the complexity of coverage. 
   - Do not use this technique if there are many sub-ideas to cover but the central concept is straightforward.

### Contextualization Technique
- The concept is historically rooted, and understanding its background is crucial for full comprehension.
- It's necessary to capture how the concept evolved over time and was influenced by specific political, social, or economic factors.
- Without knowing the setting or the historic themes (political, social, economic, cultural, human, technological factors) surrounding the concept, the student cannot effectively understand it. 

### Storytelling Technique
- The concept is part of a larger narrative or can be effectively illustrated through a story involving characters and conflicts.
- The concept involves emotional or personal elements that can be effectively conveyed through storytelling, making it relatable and memorable.

### Simple Explanation
- All other scenarios not covered.
- The concept is fairly straightforward and can be easily understood by a student through a direct explanation.

Follow a four-step process to pick the best technique for the lesson's concepts:
1. Assess: Evaluate each technique and its suitability for explaining the concepts at hand. Be thorough and critical. We want to avoid false positives. We aim to identify whether the technique would indeed be effective in explaining the concepts.
2. Synthesize: If multiple techniques seem to be a good fit, try to narrow down to a single one. Your goal is to identify the technique that will most effectively explain these concepts.
  - For some principles like the setup or storytelling, you need to consider whether there is a good story or example that could be used to represent the concepts. If not, the technique may not be a good fit.
  - For each technique, except the direct simple explanation, consider whether the technique justifies the extra length and information being added. Each concept will surely lead to some extra information and word count being added. We don't want to add to the student's workload unless we are confident the benefits of the technique in these concepts significantly outweigh the drawbacks of extended length and information.
3. Choose: Pick the best technique. Remember, you always have simple explanation as a fallback in case synthesis failed to reveal a justifiably good technique.
4. Suggestion: Only applicable for the complex techniques. Here you can suggest the ideal example, context, story, or similarities/differences that could be employed in the explanation of the technique.

Fill out this json schema for every cocnept:
```json - Evaluation Schema
{{
  "Assessment": {{
    "Sameness and Difference Principle": "<Assess whether the guidelines for the technique are met and the technique is fit to be applied for this concept>",
    "Setup Principle": "<Assess whether the guidelines for the technique are met and the technique is fit to be applied for this concept>",
    "Contextualization Technique": "<Assess whether the guidelines for the technique are met and the technique is fit to be applied for this concept>",
    "Storytelling Technique": "<Assess whether the guidelines for the technique are met and the technique is fit to be applied for this concept>",
    "Simple Explanation": "<Assess whether the guidelines for the technique are met and the technique is fit to be applied for this concept>"
  }},
  "Synthesis": "<Of the fitting techniques, identify the one which applies the best>",
  "Choice": "<Sameness and Difference Principle || Setup Principle || Contextualization Technique || Storytelling Technique || Simple Explanation>",
  "Suggestion": "<Provide a suggestion on how the chosen technique should be employed. The suggestion should focus on technique-specific elements, such as a fitting example or relevant context, rather than the scope of the concept and what should be explained.>"
}}
```

Remember to consider the unique aspects of the concept and how different teaching methods might address them. Your goal is to provide a well-reasoned and practical recommendation for educators to use in their classrooms.
"""

EXPLANATION_TECHNIQUE_ALL_CONCEPTS_USER_PROMPT = """Here is the list of concepts:
{concepts}

Evaluate each individually and return a large JSON following this schema:
```json
{
  "<Concept. Verbatim rewrite of the concept being evaluated>": <EvaluationSchema Filled>,
  ...
}
```
"""

SYNTHESIZE_RELATIONSHIPS_SYSTEM_PROMPT = """You will be given a concept syllabus that outlines a concepts and its underlying details. Along with the concept you will receive relationships defining the connection between the current concept details and the details of other concepts previously covered in the lesson. Your task is to rewrite the relationships as concise, direct statement that explicitly and specifically draw the connection between two two concept details.

To complete this task, follow these steps:

1. Carefully read and understand the details of both the current concept and the related concept as presented in the syllabus.
2. Identify the specific relationship between these two concepts. Pay close attention to how the relationships JSON describes their connection.
3. Construct a single, concise sentence that outlines this relationship. Your statement should:
   - Be specific and avoid referencing generic terms like "source" and "target"
   - Specifically mention which part of the relationship refers to the current concept detail and which to a previously covered concept detail, as you draw the connection between the two. You must explicitly state and highlight the part which was covered earlier.
   - Make a strong, standalone claim relating the two concept details
   - Be written from the perspective of the current concept
   - Not simply restate the concept details, but focus on their relationship
   - State how this current concept detail relates to or build on the previous concepts. 
4. Ensure your statements are direct and explicit about how these concept details are connected. 
5. Double-check that your statement doesn't use unnecessary jargon or complex language. It should be clear and straightforward.

Provide your response in the following format, expanding on the current concept syllabus by injecting the relationship definition under the respective concept detail

<relationship_statement>
Concept: <Concept Name>
Concept Details:
 1) <Detail 1>
    - Relationships: 
       a) <Relationship 1>
    ...
  ...
</relationship_statement>

Remember, the goal is to create a clear, concise, and specific statement about how these two concepts relate to each other, based on the information provided in the concept syllabus."""

SYNTHESIZE_RELATIONSHIPS_USER_PROMPT = """
Here is the current concept syllabus:
<concept_syllabus>
{concept_syllabus}
</concept_syllabus>


The related concept details are:
<related_concepts>
{related_concepts}
</related_concepts>
Your relationship definition must draw from the previous concept and incorporated into the current one. All related concepts have been covered earlier in the lesson, and now we aim to build on them. Clearly state how the previous concept connects or contributes to the current one. Be clear about which part pertains to the previous concept.
{intra_unit_concepts}
When updating the concept syllabus, only add the relationships. Do not edit the existing syllabus. The concept statement and details should remain exactly as they are.
"""

# Figure Explanation
explanation_technique_guidelines = {
  "Simple Explanation": {
    "guidelines": """
#### Applying the Simple Explanation Technique

**Explaining the Concept**
- Begin your answer with a clear definition of the concept, then proceed to explain it in simple terms for the student.
- Any relevant sub-terms introduced should also be clearly explained.
- Communicate the significance of the concept, its importance, and its impact on historical developments.
- Each concept explanation should define and explain the concept, followed by an outline of the concept's significance or a clarifying example or analogy.

**Relating Concepts**
- As you explain the concept, connect historical developments to current practices to demonstrate the evolution and ongoing relevance of key ideas. This builds a comprehensive understanding of the subject.
- Integrate new information with existing knowledge and broader themes to establish clear context and practical applications.

**Using Examples for Explanation**
- Incorporate practical, real-world examples to demonstrate theoretical concepts in action. This approach makes learning more concrete and memorable.
- Select analogies from common experiences to transform abstract ideas into easily understood concepts.
- Think deeply and reason carefully when identifying the best example or analogy to illustrate and clarify the concept. The example or analogy should accurately portray the concept and be relatable to the student, so take your time in devising the perfect one.

**Language**
- Express complex historical concepts through clear, straightforward statements that maintain accuracy.
- Deliver factual information directly and precisely, without unnecessary narrative elements.
- Ensure explanations remain accessible while incorporating essential technical terminology that students should master.
- Except for the relevant important historical terms under the concept, each word in the explanation should be a simple term that is frequently used in everyday life, even in a middle school classroom. Avoid unnecessary complexity and keep it simple to facilitate comprehension.
  - Speak as if you are talking to a seventh grader. Be straightforward, clear, and simple.
  - As students listen to your explanation, they shouldn't have any "What? Why? How?" questions arising. Everything needs to be simple, reasoned, and clarified. 
  - Be thorough and ensure each 'What' has either a 'How', a 'Why', or both, to ensure complete comprehension of the concept.

Limit the explanation to 150-200 words. Or between 5-7 sentences. Write up just  a single paragraph. 
""",
    "suggestion_usage": ""
  },
# ---------------------------------------------------------------------------------------------
  "Sameness and Difference Principle": {
    "guidelines": """
#### Applying the Sameness and Difference Principle

- The user will specify the terms or ideas under the concept that need clarification and distinction through the Sameness and Difference Principle. Apply the principle only to those terms explaining what they are and/or what they are not. 
- If the principle is being applied to multiple terms:
  - Before applying the principle, make sure to outline and explain the overarching concept.
  - As you explain the overarching concept, extend your explanation into the terms or ideas. 
    - If they are closely linked sibling terms, it might be a good idea to list each one in a natural manner under the concept before delving deeper and explaining them through the principle.

- **Applying the Sameness and Difference Principle**:
  - The goal when applying the Sameness and Difference Principle is to help students develop precise understanding of ambigious or complex concepts by going beyond the abstract definition to explicitly identify what something is and/or isn't. Whether comparing multiple concepts or defining a single concept through contrasts with familiar alternatives.
  - The application of this principle generally follows the following structure:
    - Begins by defining the term or idea as specified in the concept syllabus. This definition should be concise and strong. (always do this defining/explaining before going into what it is not)
    - Clearly specify what the term or idea is and/or is not, in line with the suggestion provided by the user.
    - Optionally if term or idea is complex enough, quickly check student's understanding of the term/idea with a simple situational question, followed by a Yes or No answer. The question should be:
      - Simple and straightforward, not designed to trick the student. Highly relatable and easy to understand. If applicable, make the student the main character of the hypothetical scenario and ensure it's something relatable from everyday life.
      - Based solely on the provided term explanation. The question should not necessitate any additional knowledge beyond the given explanation and basic general knowledge. It should be a simple and straightforward application of the just learnt term or idea.
  - Once answered, provide a brief affirmation of the answer and the reasoning behind it to recap the term or idea.
   - The answer reiterates on the established learnings as opposed to introducing new information. 
  - If the principle is being applied to multiple terms/ideas, make sure to connect them together through transitional statements and compare and contrast. 
 - Here are some examples below, these snippets are directly extracted from an exemplar transcript so follow the same style as you apply the principle:
```
Popular Sovereignty and Direct Republicanism:
There are many ways citizens can exercise power in governance. In my time, the most popular methods were popular sovereignty and direct republicanism. Popular sovereignty means power belongs to the people, who exercise it by voting and choosing representatives. Direct republicanism goes a step further—citizens directly participate in making laws and policies themselves, not just through representatives. Here's the difference: with popular sovereignty, you might vote for a senator to make decisions for you. In direct republicanism, you'd actually vote on the laws yourself, like in a town hall meeting. So, if your city holds a vote where all citizens decide whether to build a new park, is this popular sovereignty? No, it's direct republicanism! Because you're actively participating in making the decision, instead of leaving it to representatives like the mayor. So remember—while both give power to the people, popular sovereignty works through representatives, while direct republicanism puts decision-making directly in citizens' hands.

Civil Disobedience:
Gandhi's Salt March challenged unfair British laws through civil disobedience. Civil disobedience is when people peacefully, without violance or physical force, refuse to follow unjust laws to create social change. So, if you sit quietly on your school steps refusing to move as a protest against an unfair dress code, is that civil disobedience? Yes! When you stand up to injustice without violence, that's civil disobedience in action.
```
- Here is an of a bad application of the Sameness and Difference principle:
   - "Meanwhile, nuclear power, which harnesses energy from splitting atoms, offered vast energy in smaller amounts of material, whereas before large quantities of coal or oil were needed to achieve similar output. So, if you employ reactors and nuclear fusion, are you using nuclear power? Yes! So you know that this technology comes with distinct safety concerns and radioactive waste dilemmas, instead of the more direct but polluting emphasis of petroleum."
   - The explanation did not refer to reactors or fusion, yet these terms appear in the question. The question is also overly complex; it should be simplified and more direct.
   - The explanation did not discuss waste or safety, but these topics are included in the answer.

Your answer should be delivered in a single large paragraph. Limit the core concept explanation to 5-7 sentences or 150-200 words. Depending on the number of terms for which Sameness and Difference is being applied you may go over this limit by 2-3 sentences. 
""",
    "suggestion_usage": "\nFollow this suggestion when applying the Sameness and Difference Principle, as it indicates the terms or ideas to which the principle should be applied:\n{suggestion}\n"
  },
# ---------------------------------------------------------------------------------------------
  "Setup Principle": {
    "guidelines": """
#### Applying the Setup Principle

- Setup principle tries to get the student in the right frame of mind to learn a concept by connecting it to their existing knowledge and experiences. This is done by opening with a relatable scenario, analogy, or question that bridges their everyday understanding to the new concept, easing in new learning. For example, before teaching about inflation, you might start by asking "Have you noticed how your favorite candy bar costs more now than it did a few years ago?" This creates an immediate personal connection to the concept and primes the student's mind for deeper learning.
- As you transition from the familiar situations to the unfamiliar concept, maintain the familiar imagery by drawing vivid parallels between the concept and the example/analogy/scenario. Continuously strive to make the abstract concept more tangible by enabling visualization of it using the example/analogy/scenario.
  - Use the similarity between the example/analogy/scenario and the concept itself to transition from the familiar to the unfamiliar seamlessly bridging the gap between the two.
  - Only having setup the central idea or term, formally define and explain it.
- As you explain the concept in response to the student's question, it's a good idea to continuously refer back to the initial example/analogy/scenario. This simplifies the concept for the student and reinforces a strong mental image.
- Ensure that the example/analogy/scenario you present at the beginning is something the student can easily and effortlessly visualize. The goal is for this example/analogy/scenario to facilitate learning, not make it more challenging. 

Here are some references of how you can introduce setup examples and seamlessly transition into the concept, while maintaining clear connections.
<references>
In my time, we didn't have Amazon or global shipping, but we still managed to get exotic goods from thousands of miles away through what we called the Silk Road. The Silk Road wasn't just one road, but a vast network of trade routes...

Picture soccer tryouts for the varsity team, where each player faces a series of tough drills to demonstrate their abilities. Just as tryouts reveal the best ballers, civil service exams were official tests conducted by imperial China to find the most knowledgeable and capable people for government service instead of granting positions based on family background...

Consider modern large tech companies, many offer employees stocks and company benefits in exchange for their work and loyalty. This concept of mutual obligation was figured out centuries ago by the Europeans through the Feudal System, where lords gave land and protection to people in exchange for their service and allegiance...

Think about how you feel when someone comes into your room, takes your things, and tells you they're in charge now. This is similar to how many societies felt during the age of colonialism...
</references >
The references may not fully illustrate this, but remember, as you further develop the concept, to link it back to the initial setup example. Your goal is to make the abstract idea more concrete.
The user will specify the term/idea that needs setting up. Apply the principle only to that term using either their suggested example/analogy/scenario, or if inadequate, create a simple relatable one that bridges everyday understanding to the concept 

Limit the explanation to 150-200 words, or between 5-7 sentences. In addition to these explanation limits, allocate 15-40 words or 1-2 sentences to the setup example. Write up just a single paragraph.
""",
    "suggestion_usage": "Here is a suggestion on the potential example or analogy you could use to setup the concept at hand: \"{suggestion}\""
  },
# ---------------------------------------------------------------------------------------------
  "Contextualization Technique": {
    "guidelines": """
#### Applying the Contextualization Technique

- **Introduce Relevant Historical Context**:
  - Start by outlining the broader historical environment surrounding the concept. 
    - Scope the context only to contextual elements that are important to understand this concept specifically. 
    - Context that is significant but not knowing it won't prevent learning of the concept should not be included
    - Initial context definition should take up no more that 2-3 sentences so be very selective about the context you will use. Do not delve or mention the concept until you have cover thoroughly covered the relevant context. Spend 2-3 sentences outlining the relevant context.
    - Here it is critical to use <thoughts> tag extensively to brainstorm and identify the most import context elements. Think about the significance of the concept to that time specifically, what circumstances were surrounding the formation of the concept.
    - Relevant context may include the setting (time and place) and historic themes (political, economical, social, cultural, environmental). It maybe that previously learnt concepts establish the relevant and necessary context for this concept, in such case keep the contextualization brief and just draw the connection from the previous concepts into this one as outlined in the concept syllabus. Here are examples of relevant context:
• If the concept emerges from or reshapes existing social, political, or economic structures, then provide context about the established systems and power hierarchies that the concept altered or built upon.  
• If the concept reflects or transforms cultural and intellectual currents, then provide context about the dominant beliefs, philosophies, or cultural norms that set the stage for such a shift.  
• If the concept arises through technological or scientific advancements, then provide context about the prior state of knowledge or practice that allowed new discoveries or inventions to flourish.  
• If the concept is connected to demographic shifts, then provide context about population changes or migrations that led to new social dynamics.  
• If the concept interacts with environmental or broader regional changes, then provide context about the climate or resource conditions that shaped or were influenced by the concept.  
• If the concept transcends local boundaries through global or cross-cultural exchanges, then provide context about the interconnected networks or communication methods that facilitated its spread.  
• If the concept leads to or evolves from changes in governance and administrative practices, then provide context about existing political and bureaucratic systems and how they adapted.  
• If the concept stems from or triggers major social transformations, then provide context about the prior social stratification and how this shift redefined group roles or statuses.  

- **Connect the Concept to Its Context**:
  - Bridge the gap from the context to the concept. Explain how surrounding events, cultures, or social structures influenced the development of the concept.
  - Use the historical context to transition into a detailed explanation of the concept.
  - Emphasize the cause-and-effect relationships to show why the concept emerged and the significance it had. Refer back to the context, did it change something?
  - Continuously refer back to the initial context provided to reinforce understanding and maintain a clear connection between the concept and its historical significance. Tie back the details you are uncovering about the concept to the context.

- **Summarize and Reinforce Understanding**:
  - Conclude by summarizing how the concept fits within the broader historical narrative.
  - Review the key points about the concept's influence and implications to ensure comprehensive understanding.
  - Limit your summary to just 1 sentence.

Dedicate the first 2-3 sentences, or 50-75 words, to setting the stage for the concept by defining the relevant context. Then, start a new line and proceed to introduce and explain the concept. Limit the explanation to 100-150 words, or between 3-6 sentences. Your <answer> tag then should include 2 paragraphs: one for contextualization and the other for explanation.""",
    "suggestion_usage": "Consider this suggestion for appropriate context. Use it as a guide, not a strict rule, and feel free to override it if necessary. On a side note, it doesn't consider relationships, which may sometimes serve as appropriate context. Anyway, guidelines on Applying the Contextualization Technique should be your main reference: \"{suggestion}\""
  },
# ---------------------------------------------------------------------------------------------
  "Storytelling Technique": {
    "guidelines": """
#### Applying the Storytelling Technique

• Narrative Foundations  
  - Use narrativity to significantly enhance comprehension and retention of information, and integrate narratives into lessons to create a coherent and engaging storyline.  
  - Introduce the setting and characters by setting the scene and introducing the main characters.  
  - The entire explanation should be a story, with every sentence from the first to the last contributing to the plot development. 
    - Start with the exposition, then continue to the rising action, climax, falling action, and finally, the resolution.
    - The exposition is the only part where the concept may not be demonstrated and may just set the scene of the story. Every other narrative element should contribute to the story, with the resolution concluding it by re-emphasizing the historical significance of the concept.

• Character and Conflict  
  - Direct attention to relatable and compelling characters that students can identify with, establishing a connection between characters and students’ own experiences.  
  - Introduce conflicts or problems by presenting challenges the characters must face, mirroring the learning challenges students encounter.  
  - Show how the characters overcome these challenges, providing a model for students to follow.  

• Story Progression and Resolution  
  - Highlight the turning point, the most intense part of the story where the main conflict reaches its peak.  
  - Demonstrate how the characters begin resolving the conflict.  
  - Explain the aftermath of the story's climax and how the characters address its consequences.  
  - Wrap up the story by tying up loose ends and reflecting on lessons learned.  

• Tone and Engagement  
  - Use tone to influence students' emotional engagement and motivation.  
  - Adjust the tone of the story to match the learning objectives and the emotional state of the students, employing a positive conversational and enthusiastic style to enhance the learning experience.  

• Multimedia and Relevance  
  - Exclude extraneous information to keep the narrative focused and clear.  
  - Craft stories that evoke a range of emotions, from curiosity and excitement to empathy and compassion.  
  - Contextualize stories within students' real-world experiences by relating them to everyday life, current events, and the broader world, ensuring relevance and deeper engagement.  

**Demonstrating the Concept**
- The story should consistently demonstrate and signify the concept at hand. The two should be deeply intertwined, with the concept essentially serving as the central theme of the story.
- The story is meant to bring the concept to life through real-life experiences and its impact or unfolding. 
- Since the historical figure - {figure_name} - is well-versed in the concept, the story should be one they have experienced and delivered as such. You may make up a story as a moment from the historical figure's life, but without distorting any historical facts or developments. 
- If the concept is an event, ensure to deliver an accurate non-fictional account of the event without introducing made-up elements for the sake of the story. For such stories, make sure to indicate in first person that the historical figure may not have experienced it but...
- Thoroughly reason and think as you first plan and then execute the transcript:
  - Identify all the sub-concepts or details under the concept that must be revealed and explained to ensure full comprehension of the entire concept. Focus on depth over breadth: for a concept, focus on child concepts as opposed to sibling ones. 
  - If there are many sub-concepts, make sure to mention them all while communicating their united significance. However, for the sake of lesson time, delve deeper into a few most critical ones to the lesson. 
  - Depending on the concept, identify the best way to integrate it into the story and how it should be enacted.  
  - Identify a story plot that most vividly demonstrates the concept and its underlying details. 
  - Plan thoroughly every plot development and concept revelation, ensuring it is smooth and nothing is introduced abruptly. Everything should develop and uncover smoothly, ensuring seamless transitions and knowledge acquisition.

Dedicate the first 2 sentences, or 35-50 words, to the exposition and setting the stage for the concept by defining the relevant context or conflict. Start a new paragraph and proceed to core story. Limit the story 130-180 words, or between 4-7 sentences. 
""",
    "suggestion_usage": ""
  }

}

EXPLANATION_BASE_SYSTEM_PROMPT = """You are tasked with explaining a concept from the perspective of a historic figure, specifically {figure_name}. As {figure_name} you are very well versed in the concept: "{concept}". You will now be explaining this concept to a {subject} student, who is interested in knowing and understanding only the most critical aspects of the concept without being bogged down by maybe interesting but not critical details that won't help him in the exam. 

Embody the persona of {figure_name} and explain the "{concept}" as if you are this historic figure addressing a student. {figure_name} lived through the events related to this concept and is highly knowledgeable about it. Occasionally, for authenticity, use personal pronouns. For example, if you are the emperor, you can say "my empire."

Follow these guidelines:
**1. Response Structure & Flow**
- Begin each response by directly responding to the question and expanding into detailed explanations. 
  - Skip personal introductions and proceed directly to answering the core question.
  - Do not repeat the question or confirm what the student is asking. Proceed to answer immediately, applying the teaching principles specified by the user.
- Structure content from fundamental concepts to advanced ideas. This systematic approach enables students to build understanding progressively.
- Strive to create a coherent, comprehensible explanation by ensuring it flows seamlessly, with one idea naturally extending into the next without any abrupt breaks or unexpected introductions. The concept and every fact under it should be woven together like a story that develops smoothly to maintain user engagement and not lose them. 
  - Use transitional phrases to guide the flow of your explanation.
  - Most importantly, link different ideas together as you move from one to another.
  - Avoid introducing new ideas abruptly; instead, ensure each new point naturally extends from the previous one.
- Explain the concept not individual concept details. Your explanation should be holistic striving to explain the overarching concept through the individual concept details. This requires that you don't simply cover the details but also establish explicit connections between details, ensuring a smooth flow and clear display of their place in the bigger picture of the concept as a whole. 
  - This also entails your explanations stay balanced and do not favor one detail over the other, although some favoritism is allowed towards the more complex details to ensure thorough comprehension.
  
**2. Content Scope Management**
- Make sure to thoroughly explain the core concept and take advantage of the provided concept details as follows:
  - Ensure to communicate each detail and explain them to an appropriate extent to ensure comprehensive understanding of the material.
  - Use the provided concept details to narrow down the breadth of coverage and avoid introducing information that goes beyond this scope. 
  - Introduce and explain terminology and details specifically mentioned in this concept syllabus, avoid introducing anything out of scope. There should not be any new term being taught besides what is in the concept syllabus.
  - Remember, the goal is to teach a concept thoroughly but within the scope outlined by the concept syllabus to avoid overwhelming the student and burdening them with potentially important but not critical knowledge.
- DO NOT add any extra detail at any cost apart from what is in the concept syllabus.
  - For example: When explaining Reconquista, if the facts don't mention fall of Granada, you also should not mention it. Even such tiny details should not be added even for the sake of completeness.
  - For example: When talking about story of Columbus reaching some shore with his ships, don't add names of the ships yourself if the facts don't mention them. You can say "Columbus reached xyz shore with his ships" but not "Columbus reached xyz shore with his ships  Nina, Pinta and Santa Maria" if the facts don't have the names of the ships.
  - For example: When talking about the Aztec Empire, if the facts dont' mention lake Texcoco, you should also not mention it. Even though you know you know how linked it is to the Aztec Empire, don't add it.
  - If these details are not present, it is because they are not important for the concept and should not be added to avoid cognitive load.
- Present both the core concept and its significance clearly, focusing on essential information defined while avoiding unnecessary complexity.
- Keep track of the previous concepts covered in this lesson, as provided by the user. Use the list of previous concepts and their details wisely to avoid repetition and maintain student engagement.
  - Avoid repeating similar content. Instead, emphasize how these past concepts relate to the current one.
  - If a term from a previous topic is mentioned, even without a clear definition, don't redefine or re-explain it in your current explanation.
- If any additional cross unit facts are provided, use them to enrich the explanation and add depth to the concept.
{inter_unit_fact_instructions}
{high_level_fact_instructions}

**3. Clarity & Comprehension Techniques**
- Define new terminology immediately upon introduction to ensure complete comprehension throughout the explanation.
  - This concerns terms explicitly defined in the current concept syllabus, not once simply mentioned. If a term isn't defined, it's probably because the student is expected to already know it. 
  - The syllabus precisely details what the student needs to learn. Hence, any terms not explicitly defined in the syllabus can be used freely in the context explanation.
- To ensure clarity and facilitate understanding of the content, pair each term definition or complex idea explanation with a difference clarifier. 
  - This is a contrasting statement that indicates what the term or idea is not, or what change it introduces. 
  - Each contrasting statement clarifies a term or idea that is central or critical to the concept, not a secondary detail.
  - Useful phrases for these include, but are not limited to, 'as opposed to', 'instead of', 'whereas before', etc.
  - Apply this principle sparingly, only to central terms and ideas or complex explanations. A good number is 2, although anything in the range of 1-3 is acceptable.

**4.{relationship_instructions} Language & Communication Style**
- Use straightforward, everyday language that is easily understandable and engaging. 
  - In your explanation, you may only use the historical terminology mentioned in the concept definition or in the concept details. 
  - Any term not mentioned in the concept definition or details should be avoided. If necessary, you can replace the term with a defining phrase. For example, instead of using the term "Industrial Revolution" you could say "machines started replacing manual labor". (this is only when "Industrial Revolution" is not mentioned in the concept definition or details, if it mentioned, then use that)
  - Apart from the historical terminology mentioned in the concept syllabus, every word in the explanation should be simple and commonplace.
  - In the explanation, avoid referencing any terms or ideas that will appear in the upcoming concepts.
  - While embodying the historical figure do not try to emulate there speech style. Avoid using outdated words or phrases that a modern student wouldn't understand. Instead, opt for simpler, more straightforward alternatives. For example, use "plan" instead of "stratagem", "workers" instead of "proletariat", or "moral behavior" instead of "righteousness".
- Use the phrasing and terminology of the facts as much as possible. For example:
  - If the facts state "marriage of A and B" the use the word "marriage" and not "union" or "partnership".
  - If the facts state "monarchy" then use the word "monarchy" and not "government" or "realm".
  - If no specific terminology is present, then use the most common and appropriate term.
- Sometimes the fact itself is phrased in the best possible way, in such cases it is better to use that phrasing than to try to change it everytime. Use your best judgement, goal is to explain in most simple and natural way while being true to the facts.
{language_guidelines}

You will be using specialized teaching techniques to explain the concept. Follow the guidelines below to ace the answer to the question and thoroughly explain the concept maximizing comprehension of the content and retention:
{explanation_techniques}

Before writing up the answer use the <thoughts> tag to limit the scope of the concept, identify the most critical aspects that you you will define and explain and any relevant components of the teaching principles you will be applying. Then proceed to writing up the answer.

Remember to stay in character as {figure_name} throughout your explanation. Do not break character or reference modern events or knowledge that would not have been available to {figure_name}.

Provide your response within <answer>. After the closing </answer> tag provide a 1-2 sentence justification as why this is a good explanation. Inside the <answer> tag do not include any introduction of yourself; begin directly with addressing the concept. 
"""

EXPLANATION_BASE_USER_PROMPT = """
Here are the concepts the student has just learned as part of their lesson on "{topic}":

{previous_concepts_instructions}

For your reference, these are the upcoming concepts. Avoid jumping ahead and mentioning them or their underlying ideas. Do not even allude to them or mention any details that would be better covered in the upcoming concepts; focus only on the core concept and underlying details.
```Upcoming Concepts
{upcoming_concepts}
```

The student asked this question after learning those concepts:
```
{question}
```

Now, answer the student's question by explaining this concept:
```
{concept}
```
{suggestions}

{question_instructions}
"""

def get_explanation_base_system_prompt(subject: str, figure_name: str, concept_title: str, concept: str, explanation_techniques: List[str], relationships: str = ''):
    inter_unit_fact_instructions = ""
    if "(CROSS UNIT DETAIL)" in concept:
        inter_unit_fact_instructions = """- When handling details labeled as (CROSS UNIT DETAIL), strive to create significant links and clarify new information. CROSS UNIT DETAIL refers to details that connect previous topics with the current one, strengthening the concept.
  - Your objective is to show students how their prior knowledge supports new learning without reiterating old concepts. Identify the element related to previously learned material and briefly remind the student, prompting active recall without reteaching the concept.
    - Use concise references to stimulate student recall ("As you remember from...") while keeping the focus on the current concept and its importance.
  - Consider these links as bridges: recognize previous learning on one side, introduce new content on the other, and clearly demonstrate how the current concept is reinforced. Past learnings can serve as a foundation to facilitate new understandings.
    - These connections should enhance comprehension of the current concept without sidetracking into a review of past material.
    - As needed, per instructions above, clarify the new learnings. 
  """

    intra_unit_relationships = ""
    if "(INTRA UNIT)" in concept:
        intra_unit_relationships = """- Note some relationships are marked (INTRA UNIT), these represent connections to concepts covered not in this lesson but in past lessons:
  - Treat them similar to other relationships as defined above, using them as a foundation to build new understanding. For example:
    - "Your understanding of feudal land ownership helps explain why the merchant class's new wealth was so revolutionary..."
    - "Just as you learned how guilds controlled medieval production, this new factory system completely broke that model by..."
  - Reference these connections to facilitate and deepen comprehension of the current concept, not merely to remind of past learning
  - Keep references brief but purposeful - they should illuminate the current concept by leveraging what students already know, not reteaching
  - Let previous knowledge serve as scaffolding for new ideas, making complex concepts more accessible through familiar frameworks
  """
        
    relationship_instructions = ""
    if relationships:
        relationship_instructions = f""" Historical Connections & Relationships**
- Your explanation should not only cover the concept and its underlying details, but also establish connections with previously learned concepts that were learnt earlier in this same lesson.
- Relationships between each concept detail and previous concepts are outlined in the concept syllabus under the relevant concept detail.
- Incorporate these relationships, as outlined in the concept syllabus, naturally into your explanation. They should be integrated seamlessly.
- By establishing these connections, you will enhance student understanding by linking new information to existing knowledge. Well-structured, simple and clear connections aid in deeper retention of facts.
- Strong connections enable students to develop the historical thinking skills and reasoning processes necessary for success in the AP exam. 
- While these relationships are important the main focus should be on the core concept and its details, the relevant relationships can be mentioned briefly as secondary information, if appropriate. Keep their reference short and simple. 
- Do not re-explain previous material; reference it briefly and focus on outlining the connection. Avoid repetition, as it frustrates students, for that do not include any details about related concepts beyond a terse reference needed to establish the critical connection.
- Relationships must be used as information chunks that enhance comprehension and retention of the core concept and detail.
- Examples of better quality explanation that can be aided by the connections:
```
- Emissions & IPCC: The transcript mentions IPCC after discussing emissions, but doesn't explicitly say that the problem of emissions led to the creation of the IPCC.
- IPCC & Kyoto Protocol: The transcript says "This scientific grounding led us...to adopt major agreements, including the 1997 Kyoto Protocol." It could be stronger: "It was because of the IPCC's evidence and scientific consensus that the international community was able to create agreements like the Kyoto Protocol."
  - Kyoto protocol can also be used as an example of the tensions between environmental protection and economic development.
- When talking about industrialization, transcript mentions China and India "After 1950, places like China and India grew industrially at an astonishing rate..." This is descriptive, but it could be framed as an example: "We saw a powerful example of this rapid industrialization in nations like China and India."
```
{intra_unit_relationships}
**5."""

    high_level_fact_instructions = ""
    if "(HIGH LEVEL)" in concept:
        high_level_fact_instructions = """- HIGH LEVEL FACTS INSTRUCTIONS:
  - Facts marked as (HIGH LEVEL) are advanced facts that synthesize or provide an overview of the simpler, lower-level facts. Such facts will usually be placed after the underlying lower level facts in the concept syllabus. The underlying lower level facts might span across current and previous concepts.
  - Explanation for such facts should be limited to just one sentence covering the high level idea and not delve into the details of the underlying lower level facts again.
  - For such facts do not repeat or reexplain the lower level facts. Instead, use them as a synthesis to provide a broader overview to close off the explanation of underlying lower level facts.
  - The explanation technique doesn't need to be applied to such facts.
  - If the high level fact adds any new information that is not already covered, do cover it fully, but if states already covered information, do not explain that information again, it's okay to just reference it.
  - Example:
    - After explaining the lower level facts about the Industrial Revolution, the high level fact might be: "The Industrial Revolution was a period of rapid industrial growth and technological advancement that transformed societies globally." Here, we won't dive into the details of the Industrial Revolution again, but instead use it as a synthesis to close off the explanation of the lower level facts. If it had added some new information, we would have explained that new information fully but if it merely restated information already covered in the underlying lower level facts, we would have just referenced it.
    """

    explanation_techniques = "\n\n".join([explanation_technique_guidelines[technique]['guidelines'] for technique in explanation_techniques])
    return EXPLANATION_BASE_SYSTEM_PROMPT.format(
            subject=subject,
            figure_name=figure_name,
            concept=concept_title,
            inter_unit_fact_instructions=inter_unit_fact_instructions,
            high_level_fact_instructions=high_level_fact_instructions,
            explanation_techniques=explanation_techniques,
            language_guidelines=language_guidelines,
            relationship_instructions=relationship_instructions
        )

def get_explanation_base_user_prompt(topic: str, previous_concepts: str, upcoming_concepts: str, question: str, concept: str, teaching_techniques, ask_question: bool = False):
    previous_concepts_instructions = "This is in fact the first concept in the lesson, there are no previous concepts."
    if len(previous_concepts.strip()):
        previous_concepts_instructions = f"""```Previous Concept
{previous_concepts}
```
Please take advantage of these previous concepts properly, which means:
- Refer back to any of the previous concepts if they contribute to understanding the core of the current concept with adding breadth or providing related but not core information.
- The combined recall statement must: Integrate smoothly into the overall transcript; remain brief and not reiterate previous knowledge but merely refer back to it and remind the students of its earlier coverage; and be contextually correct, logical, and pertinent.
- Do not explain anything again that has already been covered in the previous concepts. We don't want to repeat ourselves at all. It is okay to mention or refer back to previous concepts but do not explain them again.
- Examples
```
- When examining the Magna Carta, a quick reminder of feudal oaths can add clarity, but the central idea is that it was the first formal agreement to limit the power of the monarchy."
- "As we saw earlier, American individualism reinforces Jeffersonian democracy, it...". This is a bad callback because the student has only learned about American individualism, but has not yet observed how it reinforces democracy which is only being covered in the current concept. This is an inaccurate misleading callback.
- A better example would be, "Jeffersonian democracy was reinforced by American individualism, the common mindset we learned about earlier...". Short, accurate, and seamless.
- Another good example is, "As we discussed earlier, the 1950s saw a surge in population growth. This growth has been a major driver of deforestation which is..." - While it's preferable for the current concept to be the object and the previous one the subject, the arrangement is still acceptable since the previous concept led to the current one.
```
"""

    question_instructions = ""
    if ask_question:
        question_instructions = """After explaining the concept, wrap up with a succinct invitation for students to answer questions about the material they've just learned. This will help reinforce their understanding. Here are a few examples:
- "So, dear learner to ensure you've grasped the material, let's go through some questions."
- "Now, my students, let's answer some questions about the X" - where X is the concept name integrated nicely and concisely.
- "Time to test your understanding of X with a few questions."
There are many other ways you can phrase this, in fact you should be creative about it. The key is to cordially invite students to answer questions in a manner that is laconic, friendly, directed at the students, and suitable for the speaker's style.
- Guidelines: 
1) Avoid asking content questions directly; instead, kindly invite them to answer a few questions.
2) Keep it concise and friendly with just one sentence.
3) Do not give the students a choice (like "shall we go through some questions?"); students have to answer questions without a choice. Hence directly invite them to answer questions in a friendly manner.
4) Keep in mind this is not doubt clearing where the student can ask questions. Here the student is expected to answer questions about the material they've just learned to test their understanding. (So do not go like "Let's see if you have any questions")
"""
    
    suggestions = "\n".join([explanation_technique_guidelines[technique.choice.value]['suggestion_usage'].format(suggestion=technique.suggestion) for technique in teaching_techniques if explanation_technique_guidelines[technique.choice.value]['suggestion_usage']])
    
    return EXPLANATION_BASE_USER_PROMPT.format(
        topic=topic,
        previous_concepts_instructions=previous_concepts_instructions,
        upcoming_concepts=upcoming_concepts,
        question=question,
        concept=concept,
        suggestions=suggestions,
        question_instructions=question_instructions
    ).strip()

EXPLANATION_REWRITE_SYSTEM_PROMPT = """
"""

EXPLANATION_REWRITE_USER_PROMPT="""
This explanation fails not stylistically ideal. It lacks some smoothness and natural flow. Let's rewrite the explanation focusing on these stylistic features and ace them. We want an explanation that is delivered on behalf of {figure_name}, one that gradually reveals key detail and explanation, builds natural connections between the details, and guides students to discover the deeper significance of this concept in the context.

**Speak Naturally as {figure_name}**
- Maintain a conversational yet knowledgeable tone, as if you're explaining a topic you're passionate about to an interested listener.
- When introducing complex terms, explain them immediately, as if you're speaking to a young student unfamiliar with the concept.
- Respond directly to the student without referring back to them. There's no need for greetings or references to them as your student.
- Gradually layer information, starting with foundational concepts and adding complexity only when the previous understanding is secure. However, this doesn't mean breaking up a unit of content that should be delivered as a whole for maximum clarity.
- Approach it like unraveling a mystery. Each piece of information should naturally spark curiosity about what comes next, rather than forcing revelations.
- While speaking on behalf of the historical figure, maintain a moderate tone and a normal discussion style. The figure should sound like a regular teacher, not overly characterized.

Carefully assess the current <answer> tag against the stylistic guidelines and proceed to rewrite it. 
- Do not add, remove, or change the content in any way. 
- Your objective is to rewrite the same content while adhering to the stylistic guidelines. 
- As you write, ensure that you don't violate any of the guidelines regarding Explanation, Recap, Relating Concepts, Examples, Language, and Structure. 
- Do not add in personal scenarios, new examples, or new analogies. Focus on improving the smoothness of flow without modifying the content. 
- Present your final answer inside the <answer> tags and conclude with a 1-2 sentence justification.

Here are some examples of a natural flowing and smooth explanation:
```
Exactly. The civil service exams functioned like an open talent show, welcoming anyone with the right skills to step forward. For the first time, your family name didn't determine your future - whether you were a farmer's child or a general's son, you had an equal chance at securing a government position. This system broke down the old barriers of class and birth, creating new paths for talented individuals to rise through society. Gone were the days of appointing officials simply because of their family connections - like my distant cousin Yao Ming, who, bless his heart, managed taxation but couldn't tell a scroll from a tea leaf!

To address this, we suppressed these local powers and brought all regions under the direct authority of the central government. A central government means the power and decision-making authority is concentrated in a single administration, my administration, rather than being distributed among various local warlords. Through a central government we were able to create and enforce standardized laws and policies throughout the entire empire. We ensured that all regions, no matter how distant, were governed under the same principles and regulations as the capital. This consistency reduced regional disparities, minimized the influence of local powers who might pursue their own interests over those of the empire, and fostered a harmonious and stable society. Centralized governance allowed us to address the needs of the people uniformly, strengthening the unity and stability of the empire.

For the first time, the public saw not just competent but ethically guided governance. Officials, trained in Confucian principles of integrity and righteousness, demonstrated their commitment through honest management of public funds and genuine service to their communities. This ethical leadership transformed public attitudes - villages that once resisted taxation began contributing willingly when they saw their resources being used responsibly for community benefit. We reinforced this trust through strict anti-corruption measures, including severe penalties for bribery. The result was a new model of governance that earned unprecedented public confidence and cooperation.

Of course. We adopted Champa rice from Southeast Asia because it matured quickly and was resilient to drought. This allowed farmers to harvest multiple crops in a single year, dramatically increasing food production. The increased food supply supported a growing population and spurred urbanization. Excess rice could be sold in markets, fueling the economy. People were able to pursue occupations beyond farming, such as becoming artisans or merchants, which diversified and strengthened our economic foundations.
```
"""

# Host Recap
RECAP_PLAN_SYSTEM_PROMPT = """You will be given a concept explanation. Your task is to act as a learner who has just grasped this new concept and create a recap of it.

Your goal is to convery a sense of amazement and surprise at the concept and synthesize the concept explanation into a concise recap that captures the core idea and its significance.

Guidelines for Natural Learning Recaps:
1. Vary Your Openings
   - Don't always start with "Wow" or "I never realized"
   - Use transition phrases like (randomly choose one similar to these examples):
     • "That really shows how..."
     • "So basically..."
     • "I see now that..."
     • "This helps explain why..."
     • "It's clear that..."
     • "That means..."
     • "Now I understand how..."
     • "I can see how..."


2. Keep Reactions and Enthusiasm Authentic
   - Avoid forced excitement or artificial "aha" moments
   - Express genuine interest through the insight itself, not through exclamations
   - Don't overuse words like "mind-blowing", "fascinating", "incredible"

3. Connect to Real Impact
   - Link the concept to its practical effects
   - Connect it to broader implications
   - Show why it matters in simple terms
   - Focus on the most important consequence

4. Maintain a neutral global perspective by never referring to any nation, culture, or historical entity as "our," "my," or "your" (e.g., avoid phrases like "our country," "our ancestors," or "our traditions").

Present your recap within <recap> tags. Keep it concise - 1-2 sentences maximum.

Examples of Good Recaps:
• "That shows how small changes in farming can put entire communities at risk."
• "So protecting forests does more than save trees - it keeps water flowing and communities healthy."
• "This explains why countries need to work together on climate issues."

Some generic language guidelines:
{language_guidelines}

Remember: You're a learner who just understood this concept. Share that understanding naturally, without forced enthusiasm."""

RECAP_PLAN_USER_PROMPT = """Here's the concept explanation:

<concept>
{concept}
</concept>

<concept_explanation>
{concept_explanation}
</concept_explanation>
"""

RECAP_FINAL_SYSTEM_PROMPT = """
"""

RECAP_FINAL_USER_PROMPT = """
"""

ADD_TRANSCRIPT_PAUSES_SYSTEM_PROMPT = """You will be given a transcript and guidelines for adding strategic pauses. Your task is to insert pause tags into the transcript without changing any of the original text. 

Your goal is to strategically add pauses in different places of the transcript to:
• Allow listeners to process and internalize complex information just presented
• Reduce cognitive load by breaking down dense information into digestible segments
• Simulate a more natural, conversational speaking rhythm that improves engagement
• Help segment and structure the content by clearly separating different topics or ideas

Further Instructions:
• Enclose the start and end of each pause tag with an empty space, even if a punctuation mark follows (e.g., `hello world <pause=""> .` )
• Use pauses sparingly, only at critical locations specified below. 
• When historical figures explain concepts, include a few 2.0 second pauses.
  - Only add these pauses at key points, after complex explanations, to give students time to understand the information.
  - Use these pauses sparingly, not after every sentence, but only where necessary. A good rule of thumb is to limit to a maximum of three.
  - Avoid using these pauses to separate initial context or examples, as this information is not critical.
• During recaps by the host, refrain from pausing until the historical figure is introduced or a question is asked. Strictly follow the guidelines below.

Here are the guidelines for inserting pauses:

<pause_guidelines>
• 0.5-second pauses:  
  – Follow short affirmations or exclamations.  
  – Follow quick "Yes/No" responses.  
    • Example: "Yes! <pause="0.5s"> So, not cheating on an exam shows moral integrity."  

• 0.75-second pauses:  
  – Separate elements of a list or sub-ideas appearing in the same sentence.  
    • Example: "...A: Seeking revenge when wronged, <pause="0.75s"> B: Acting with moral integrity..."  
    • Example: "...In examining the Song dynasty's success, we'll look at how traditional Chinese values shaped leadership, <pause="0.75s"> explore how merit-based testing helped appoint the most competent officials, <pause="0.75s">..."  

• 1.0-second pauses: 
  – Follow rhetorical questions or short conceptual checks.  
    • Example: "If you stand up for someone who is being mistreated, are you showing moral integrity? <pause="1.0s"> Yes or no?"  
  – Follow curious questions by the host before historic figure responds - At the end of every exchange by the host, before the historic figure jumps in.
    • Example: "...How did this philosophy shape the development of Chinese governance? \<break time="1.0s" /\> \n[Confucius]: My teachings profoundly influenced..."  
  – Follows analogies.  
      • Example: "Just as a family prospers when each member ..., our empire flourished when ... . <pause="1.0s">Similarly when"
  – After the host recaps the concept explained and before introducing the new historic figure or asking a new curious question.
    • Example: "[Host]:  Fascinating <pause="0.5s"> while Confucianism's ... it gave officials fresh perspectives to navigate these issues. <pause="1.0s">  Could you now share how this ... "

• 2.0-second pauses:  
  – At the end of every interaction by a historic figure
    • Example: "[Confucius]...ensures that public needs are handled by those with the right skills and knowledge. <pause="2.0s"> \n[Host]: Ah, so a bureaucratic government is ...."
  – After lesson and section overviews
    • Example: "[Host]: ... In this first section, we'll explore X. We'll examine A, B, and C. <pause="2.0s"> To help us understand Y, lets welcome ..."
  - Before any invitation from a historic figure to test/quiz the students.
    • Example: ".. good governance. <pause="2.0s"> Now, dear students, shall we test your grasp of the Mandate of Heaven with a few questions ..."
  – 1-3 such pauses are used throughout the historical figure's explanation to lighten the flow and let the student consolidate the material.
    • Example: "The National Assembly formed leading to... <pause="2.0s"> This revolutionary fervor then ..."
</pause_guidelines>

Instructions for adding pauses:
1. Read through the transcript carefully.
2. Identify appropriate locations for pauses based on the guidelines provided.
3. Insert pause tags at these locations using the format <pause="X.Xs">, where X.X is the pause duration in seconds (0.5, 0.75, 1.0, 2.0).
4. Do not alter any of the original text in the transcript.
5. Ensure that the pauses are placed logically and enhance the flow and comprehension of the content.

Here are some examples:
<examples>
[Host]: Today we take our first step towards understanding What Made the Song Dynasty So Successful. Spanning from 960 to 1279 A.D., the Song Dynasty was a period of remarkable cultural and economic growth in China. Renowned for its technological advancements, flourishing arts, and the establishment of a strong centralized government, the dynasty set the foundation for modern Chinese society. <pause="1.5s"> In examining the Song dynasty's success, we'll look at how traditional Chinese values shaped leadership <pause="0.75s"> , explore how merit-based testing helped appoint the most competent officials <pause="0.75s"> , and see how these systems led to lasting political stability, social advancement, and economic growth in medieval China. <pause="2.0s">  

[Host]: In this first lesson, we'll explore how traditional values shaped the Song Dynasty's governance - examining how organized and ethical governance became their foundation for success. <pause="1.0s"> We'll look at China's new methods of administration that achieved remarkable efficiency, while ensuring the system remained guided by strong moral principles. <pause="2.0s"> Joining us is Confucius, the philosopher whose teachings have shaped Chinese thought for millennia. Confucius, could you explain the fundamental principles of Confucianism? <pause="1.0s"> 

[Confucius]: I spoke of the Five Relationships. They form the bedrock of a harmonious society: ruler to subject <pause="0.75s"> , parent to child <pause="0.75s"> , husband to wife <pause="0.75s"> , elder sibling to younger sibling <pause="0.75s"> , and friend to friend.  <pause="2.0s">  Moved by my teachings, the locals started realigning their relationships. The local magistrate, previously ruling through fear, hosted open forums for villagers to express their concerns. His newfound kindness fostered genuine loyalty among his subjects. Husbands and wives began making decisions together, strengthening their households through partnership. Even the marketplace changed as merchants, embracing the principles of true friendship, conducted trade with honesty and mutual consideration.  Within a season, the village that had once been divided by suspicion and self-interest became unified through proper observation of these 5 sacred relationships. <pause="2.0s">

[Host]: Your story perfectly illustrates how observing these Five Relationships promotes social harmony. It's not about dominance and submission, but about each of us fulfilling our unique roles within each relationship for the benefit of everyone. <pause="1.0s"> As we consider how these principles of respect and duty evolved over the centuries to shape Chinese society, I'm reminded that we have another distinguished guest waiting to share his perspective. Zhu Xi, as a leading Neo-Confucian scholar of the Song Dynasty, could you explain how your philosophy built upon and reinterpreted these foundational teachings? <pause="1.0s"> 

[Zhu Xi]: Originally, officials were primarily selected based on their technical skills, such as their administrative competence and policy expertise. <pause="1.0s"> Neo-Confucianism transformed this approach by emphasizing that true leadership required moral qualities like fairness, integrity, and compassion.  We promoted continuous personal development, guiding officials to strengthen their moral compass through self-reflection and ethical education, alongside their technical expertise.  <pause="2.0s">  This harmonious blend produced something remarkable - skilled leaders who embraced their social responsibility, naturally prioritizing public service over self-interest, creating a stronger governance system for our Dynasty.  <pause="2.0s"> Now, dear students, let's answer some questions about the Neo-Confucianism. <pause="2.0s">  
</examples>

Now, please rewrite the given transcript, inserting appropriate pauses according to the guidelines. Output your answer within <modified_transcript> tags.
"""

ADD_TRANSCRIPT_PAUSES_USER_PROMPT = """
<transcript>
{transcript}
</transcript>
"""


CONCLUSION_SLIDE_BULLETS_SYSTEM_PROMPT = """You are an AI assistant tasked with creating concise bullet points for the conclusion slide of an educational video aimed at students preparing for the {subject} exam. Your goal is to summarize the key takeaways in a way that maximizes student retention and understanding. You'll be given a lesson title and under it a list of sections covered in the lesson, each with a name, and section details that captures what was taught in that section.

Goal
- Create on-screen bullet points based on lesson titles and section lists (including section name and section details). These points should highlight the most important information to help students remember.
- The bullet points will act as memory aids, helping students link together the concepts they've learned in the lesson.
- These are not review notes, but tools to help students recall the concepts they've already learned.
- Each section should have one main-bullet point, and one sub-bullet point that should cover the section details in a way that clarifies the main-bullet.
   - The main-bullet should be brief and capture the section name with minimal modifications allowed to make it more natural.
   - The sub-bullet should clarify the main-bullet and limit the scope of the section to the section details.
   - The sub-bullet should be brief (not more than 10 words), starting with a strong active verb.
      - Examples of strong action verbs include Expose, Worsen, Protect, etc., as opposed to weak descriptive verbs like Highlight, Show, Make, Notes, etc.
- Provide a recap, not a repetition: remind students of what they've learned by broadly outlining the big picture.
   - By outlining the big picture, you allow the student to connect the dots and actively recall the learned material.
   - Avoid extra detail to not take away the student's opportunity for active recall.
- Each main-bullet and sub-bullet should collectively paint a complete and cohesive big picture.
   - This means their usage and phrasing should work together towards the same goal.
- Each item in section details is covered.

Guidelines
- Avoid verbosity or explaining the section details, just mention it; the student has already learned the details in the lesson.
- Use terminology that is consistent with the provided schema of section and section details. Every term included in the bullets should match the schema.
- Avoid introducing any new terms not covered in the schema. Aim to provide a simple conclusion that summarizes the learnings, rather than introducing new concepts.
- Use title case throughout.
- You will return a JSON with the lesson title and under it main-bullet (section names) as the key and the sub-bullet (section details) as the value. The keys should match exactly with the section names in the sections list.
- As a memory aid, every word matters. Avoid unnecessary words or stating the obvious. Use '&' instead of 'and' to keep it short.
- There should be one main-bullet and one sub-bullet per section. 
- Wherever possible especially for the sub-bullet use simpler language, no need to pack in complex terms just clarify the concept.
- Each item in the section details should be given some weight (atleast mention) in the sub-bullet.

Output Format
Return your response as a JSON object with the following structure:

```json
{{
    "<lesson title>": {{
        "<main_bullet_contents (section name)>": [
            "<sub_bullet_contents (section details)>"
        ],
        ...
    }}
}}
```"""

CONCLUSION_TRANSCRIPT_SYSTEM_PROMPT = """You are an AI assistant tasked with creating a conclusion transcript for an educational video aimed at students preparing for the {subject} exam. You will be given a JSON object containing bullet points that summarize the key takeaways from the lesson. Your goal is to transform these bullet points into a cohesive, flowing transcript that ties all the concepts together.

Goal:
- Create a conclusion transcript that:
  - Incorporates each concept and its underlying detail as outlined in the bullet points.
- Links the concepts together to form a larger picture. As the transcript moves from one concept to the next, the connection between them should be communicated to ensure a smooth logical transition.
- Reads like a well-constructed story, with each concept naturally flowing into the next.
- Use terminology and phrasing that aligns with the wording of the bullet points.
  - The choice of words throughout the transcript should be consistent with the bullet points, almost mirroring them word for word. However, necessary adaptations should be made to ensure a smooth and consistent flow in the transcript, which is crucial.
- Paint the big picture by putting all concepts in perspective and establishing their relevance and connection.
- Serve to remind the student of the key takeaways, providing an opportunity for active recall of the lower-level details instead of revealing them again.
- Communicate in elaborate spoken language.

Guidelines for creating the transcript:
- Begin with a brief introduction that sets the stage for the conclusion. 
  - Mention the topic and section title within the first sentence. The lesson topic was divided into multiple sections, and you will be concluding only one of those.
  - Avoid explicit terminology like 'topic'. Instead, say something like: "As we conclude our lesson on X, focusing on Y, let's revisit our key learnings."
- Address each concept in the order they appear in the JSON.
- For each concept:
  - Mention the concept title, with slight adaptation to fit into the broader sentence, ensuring the fluidity of the transcript.
  - Clarify the concept using its sub-bullet. Do not introduce any more details.
  - Transition seamlessly to the next concept by leveraging their inherent connection. 
- Use transitional phrases to move smoothly between concepts.
- Conclude with a statement that ties everything together and emphasizes the importance of these new learnings.

When writing the transcript:
- Use language that is clear and accessible to high school students.
- Maintain a conversational tone while still being informative.
- Maintain a neutral global perspective by never referring to any nation, culture, or historical entity as "our," "my," or "your" (e.g., avoid phrases like "our country," "our ancestors," or "our traditions").
- Use the exact wording from the bullet points when possible, but adapt as needed for flow. Ensuring a seamlessly flowing transcript is paramount. It should smoothly develop from one concept to another, gradually completing the picture for the section.
- Avoid using text that is suitable for written language but not for spoken communication. 
  - Replace hyphens or colons with substitute phrases such as prepositions
     - For example "The Art of Negotiation: Techniques and Strategies" => ""Techniques and Strategies in the Art of Negotiation
  - Some titles may be too direct to ensure brevity; you will need to inject sub-phrases, such as prepositions, to ensure the transcript flows smoothly when spoken.
- Do not introduce new information not present in the bullet points.
- Keep the explanation of each concept brief, as students have already learned the details.
- Compose three short paragraphs following the structure outlined below:
  1. Prepare the groundwork for the conclusion.
  2. Review the concepts: main points and sub-points, integrating them into a coherent narrative that encapsulates the learnings. 
     - Dedicate one sentence to each main point.
     - The main and sub bullets must appear almost word for word in the transcript.
  3. Conclude with a final sentence that ties all the learnings together and wraps up the lesson as a whole.

Format your response as follows:
<conclusion_transcript>
[Your transcript here]
</conclusion_transcript>

Some examples:
<examples>
Main Bullets:
Algebraic Notation and Symbols
Algorithms
Advanced Trigonometry

<conclusion_transcript>
As we wrap up our exploration of the Islamic Golden Age's contributions to mathematics and science, focusing on their groundbreaking developments in algebra, let's review the key innovations we've discovered.

The Islamic scholars revolutionized mathematical thinking by developing algebraic notation and symbols, transforming abstract concepts into a practical system of problem-solving. This systematic approach to mathematics was further enhanced by their pioneering work in algorithms, which provided step-by-step methods for solving complex mathematical problems. Building on these foundations, they made remarkable advances in trigonometry, particularly through their development of sine and cosine functions.

Through these interconnected achievements, Islamic mathematicians created a mathematical framework that not only solved contemporary problems but continues to influence how we approach mathematics today.
</conclusion_transcript>

<conclusion_transcript>
As we conclude this first part in our series on what made the Song Dynasty so successful - focusing on their system of efficient and ethical governance - let's reflect on the key themes we've uncovered. 

The Song Dynasty established efficient bureaucratic governance through organized division of responsibilities. This structure, while technically sound, was guided by Confucian principles - teachings that shaped not just governance, but all aspects of social behavior. Neo-Confucianism then enriched these traditional teachings by emphasizing personal growth and understanding. 

Through this combination - efficient bureaucratic organization guided by Confucian values and enhanced by Neo-Confucian thought - the Song Dynasty created a governance system that was both technically effective and ethically sound, laying the foundation for their remarkable success. 
</conclusion_transcript>
</examples>

Remember, your goal is to create a conclusion that helps students see the big picture and reinforces their understanding of the key concepts they've learned in the lesson."""

CONCLUSION_TRANSCRIPT_USER_PROMPT = """You are concluding, not a single section but rather an entire lesson on "{title}". 
<bullet_points>
{bullets}
</bullet_points>"""


MCQ_PER_CONCEPT_SYSTEM_PROMPT = """You are tasked with generating a set of Multiple Choice Questions (MCQs) based on a given concept explanation and syllabus. Your goal is to create questions that accurately assess a student's understanding of the critical content outlined in the concept syllabus.

Your task is to generate {n_questions} MCQs, at least one per concept detail outlined in the syllabus, that align with both the concept explanation and the concept syllabus. It's crucial to focus on assessing the student's understanding of the content defined in the syllabus, rather than testing on additional details that may be present in the concept explanation.

For each question, follow this structure:
1. Question: A clear, simple question that tests understanding and application of key knowledge from the syllabus.  
  - Arrange questions from easier to harder.  
  - Ensure each question matches exactly what was taught (syllabus and explanation).  
    - A student who has read the transcript should be able to answer without needing extra information or referring to the syllabus.  
    - Use the syllabus to identify important points to test, but base the question entirely on information from the transcript. Use wording similar to the transcript and avoid details not mentioned there.  
  - Make sure the question is clear, simple, and asks only one thing.  
    - Students should understand the question without needing to look at the transcript or other questions.

2. Options: Provide 4 answer choices.  
  - Include one unambiguously correct answer and three distractors.  
  - Keep all answer choices similar in length and sentence structure.  
    - Do not make the correct answer stand out by making it longer, more complicated, or structured differently from the distractors.  
    - Similar length and parallel structure create homogeneity ensuring the correct answer blends in with the distractors.

  - Correct Answer Guidelines:  
    - The correct answer must be unambiguously correct. Avoid having multiple options contain valid information with options differing only in degree of precision, completeness, or emphasis leaving room for debate and uncertainty over which answer is right.

  - Distractor Guidelines:
    - Avoid absolute words (e.g., always, never, all, none) in distractors. Absolute terms often signal incorrect answers. Absolute terms are acceptable in distractors only when the correct answer too includes them. 
    - Distractors should seem plausible to students who have partial knowledge. Distractors should appeal to students who have incomplete understanding. 
    - Base distractors on common misunderstandings or typical errors.
    - Avoid partially correct distractors (unless explicitly testing for the "BEST answer").  
    - Ensure distractors are clearly distinct from each other, with no overlap.
    - Include distractors that closely match the wording of the transcript or similar in content to the correct answer. This ensures the correct answer blends in naturally and is not immediately obvious to students.

  - Clearly label each option as correct or incorrect and provide a brief explanation.

3. Explanation: Provide a short, one-sentence explanation clearly stating why each answer option is correct or incorrect.  
  - Clearly explain why the chosen answer is correct or incorrect using historical reasoning and information directly from the transcript.  
  - Use the explanation to clarify each option, showing explicitly why it is true or false.  
  - Avoid simply repeating the question or answer; instead, include historical details from the transcript to support your reasoning.
  - Examples:  
    - Poor: "Consumer culture rose due to higher wages, rather than reduced living expenses." - Explanation simply repeats the correct answer without adding historical reasoning or context.  
    - Poor: "A formal academic approach was not a principle of Daoism." - Explanation restates the question and answer without providing additional historical insight.  
    - Good: "This formal academic approach contradicts Daoism's emphasis on simplicity and natural spontaneity." - Explanation clarifies the historical reasoning behind the correct answer, highlighting a direct contradiction and providing a learning opportunity.  
    - Good: "Creoles were actually well-educated, but their birthplace, not their education, prevented them from holding high positions." - Explanation clearly identifies the historical reason why the distractor is incorrect, providing additional context.  
    - Good: "The dominance of local feudal lords and lack of trade-based bureaucracy caused fragmented political landscapes where regional powers maintained autonomous control of regional affairs, slowing the development of centralized state authority." - Explanation connects historical details clearly to the correct answer, clarifying why it is true.
  - Use only information and wording from the lesson transcript; do not introduce external facts or new terminology.  
  - For incorrect answers, clearly explain why they are wrong, turning each incorrect option into a learning opportunity.


General Guidleines:
- Use wording similar to the transcript throughout the questions, answers, and explanations, while ensuring the questions test key historical concepts identified as important in the syllabus.  
- Do not refer to sources such as "passage," "content," "narrative," "transcript," "syllabus," "mentioned," etc. The multiple-choice questions should directly assess students' understanding of historical concepts, not their memory of the lesson itself.  
  - Incorrect example: "Christianity is not mentioned as a significant religious force in..."  
  - Correct example: "Islam's significant influence in Southeast Asia came after 1200, while Christianity wasn't a major influence during this period."
  - Incorrect example: "historic evidence suggests," "the text mentions," "X is not mentioned", "the explanation states"  etc. Avoid all references to historical sources or third-party statements including the transcript explanation and syllabus, as students do not have access to these.
- Use direct and simple language throughout. Questions, answer options, and explanations should all be clear, concise, and easy to understand. Avoid overly formal or textbook-style wording, favoring a light tone and style; keep explanations straightforward and student-friendly.
- Choose everyday language that students can easily follow, rather than copying complex phrasing of the transcript. Ensure each sentence is clear and easy to understand.
- Keep questions, answers, and explanations brief. Avoid unnecessary words or padding; favor terseness in wording.

Format your output as a JSON inside <mcq_set></mcq_set> tags, as follows:

<mcq_set>
[
  {{
    "question": "<Question assessing understanding of syllabus content based on the explanation transcript>",
    "answer_options": [
      {{
        "id": "a || b || c || d",
        "answer": "<STRING. Answer option>",
        "correct": true || false,
        "explanation": "<1 sentence explaining why this answer is correct or wrong>"
      }}
    ]
  }}
]
</mcq_set>

Remember to create questions that are straightforward yet effectively assess the student's understanding of the key concept details outlined in the concept syllabus. Ensure that your questions and explanations only use information presented in the syllabus or transcript.
"""

MCQ_PER_CONCEPT_USER_PROMPT = """Carefully read and analyze the following, before generating the MCQs:

<concept_explanation>
{concept_transcript}
</concept_explanation>

<concept_syllabus>
{concept_syllabus}
</concept_syllabus>
"""


TRANSCRIPT_INSERT_VISUAL_REFERENCE_SYSTEM_PROMPT = """I have a transcript explaining a historical concept. I want to add images to accompany the transcript, specifically an image of the movable type. The image should appear after the artifact is first mentioned in the transcript. There are three main ways to do this:

1) Overlay with Contextual Reference  
Overlay the image when the artifact is first mentioned, provided the mention is only background context and doesn't contain critical teaching information.  
- When not to use: If the first mention of the artifact contains critical teaching information that also appears in the diagram. Overlaying the image in this case would split the student's attention and cause confusion.  
- Example usage:  
  - Transcript: "Caravels were agile ships which my Portuguese counterparts fashioned out of our shared knowledge of sails and hull design, combining the square rigs you saw on other European vessels with our lateen sail traditions from Arab waters, making them swift, maneuverable..."  
  - Diagram: "Caravels combined square rigs with lateen sails, making them swift, maneuverable..."  
    → The first part of the transcript ("Caravels were agile ships... shared knowledge of sails and hull design") doesn't appear in the diagram. This makes it suitable as a contextual reference for overlaying the image.

2) Add a Pause  
After the artifact is first mentioned, insert a pause to display the image.  
- When not to use: If the pause interrupts the sentence or speech flow.  
- Example usage:  
  - Transcript: "Their design went hand in hand with the sternpost rudder, a hinged steering device at the rear of the ship which..."  
    → A pause after "sternpost rudder" works well here, as it doesn't disrupt the flow. The phrase "a hinged steering device..." simply defines "sternpost rudder."  
  - Transcript: "In the Renaissance period, European map makers created the Mercator Projection, which let us draw a straight path from one point to another..."  
    → A pause after "Mercator Projection" works well here, as it doesn't disrupt the flow.
  - Neither of the provided examples qualifies as a contextual reference. In both examples, the artifact is mentioned at the end of the contextual sentence rather than at the beginning. Overlaying the image before explicitly mentioning the artifact would not work clearly. Therefore, a pause is required instead.

3) Add Direct Reference to the Image in the Transcript  
If neither a pause nor contextual overlay is suitable, explicitly direct the student's attention to the image with a concise phrase.  
- Usage:  
  - Insert a short phrase after introducing the artifact, such as: "Here is what lateen sails looked like."  
  - Adjust the surrounding sentences slightly to ensure the narrative flows smoothly. Avoid abrupt jumps or interruptions. The transcript should remain a clear, smoothly flowing story


Output Format, depends on the chosen Method. Start with a thorough analysis and reasoning to support the method chosen, then conclude with the final output following the format below.
```
<method>Contextual Reference | Pause | Direct Reference</method>

If method is Contextual Reference:
<context_phrase>[Exact phrase from the transcript during which the image should appear]</context_phrase>

If method is Pause:
<prior_phrase>[Exact transcript phrase immediately before the pause]</prior_phrase>
<post_phrase>[Exact transcript phrase immediately after the pause]</post_phrase>

If method is Direct Reference:
<reference_phrase>[A short, clear phrase added to explicitly introduce the image]</reference_phrase>
<transcript>[Updated transcript including the new reference phrase with adjusted surrounding sentences to ensure smooth narrative flow.]</transcript>
```"""

TRANSCRIPT_INSERT_VISUAL_REFERENCE_USER_PROMPT = """Pick the method to incorporating the image. The image to be added is of the {artifact}.

<transcript>
{transcript}
</transcript>

<diagram>
{diagram}
</diagram>"""


# =========================== LORE / SLEEP NARRATION =============================================
# Sentence and pacing targets below are measured off the channels that own this format, not invented.

lore_language_guidelines = """
**Voice for a Sleep-Lore Narration**
One host, read aloud, for someone lying in the dark with their eyes closed. Follow these rules;
check the examples to stay calibrated.

1) SENTENCE LENGTH AND RHYTHM. Aim for 22-26 words on average. Most sentences belong in the
   14-32 word range; 38 words is a hard ceiling. Split before a second subordinate clause starts
   carrying a second fact. After one long sentence, let the next land at 12-20 words. A sentence
   under nine words is a rare landing point, no more than once per paragraph. Continuity belongs
   between paragraphs and scenes; an individual sentence may finish cleanly without dragging the
   next sentence behind it with "and," "but," or another dependent clause.
2) PLAIN, NOT ORNATE. Plainness comes from word choice and syntax, never from brevity -- a long
   sentence is fine, an ornate one is not. Write like a knowledgeable friend talking quietly, not
   like a novelist: everyday vocabulary, contractions, ordinary syntax. Avoid clause-folding that
   unspools for four lines, literary imagery, and stacked figures of speech -- at most one plain
   simile every few paragraphs, and no more than one sensory clause at a time before you move on.
   Ornateness is the most common failure mode here; if a sentence sounds like printed-book prose,
   rewrite it with plainer words, not fewer of them. Technical and period terms are ornateness
   too: any term a tired non-specialist may not know (sextant, escapement, interdict, caravel)
   either gets a plain gloss folded into the same sentence on first use, set off with commas
   ("a sextant, the handheld instrument sailors used to measure how high the sun sat") or is
   replaced outright by the plain description. Never let a term stand in for an explanation.
   Ration em-dashes to at most one per paragraph — dash-heavy prose is itself a tell; commas,
   parentheses, and "called X," do the same work more quietly.
3) DENSITY, NOT PADDING. Every paragraph is anchored by a verifiable specific — a named person,
   real date, real number, real mechanism. One or two plain connective sentences may carry no
   proper noun; a tired listener needs room between names. Give separate facts separate sentences
   instead of packing them into one comma chain. For the single largest number in a segment, one
   human-scale comparison may help. Draw it from the story's own world or from plain
   universal measures — never from a modern object the material doesn't mention (no smartphones,
   no tennis courts), and never state a comparison you can't verify: a wrong analogy is worse
   than a bare number. Do not write standalone announcement sentences ("Here's where
   it gets strange.") — fold anticipation into the sentence that carries the fact. Brief
   atmospheric passages (the physical world the actors moved through: weather, terrain, light,
   texture, sound) are valid substance, not filler; they give the listener density respite and are
   distinct from empty commentary.
4) CONFIDENT IGNORANCE. When sources are silent, say exactly what is unknown and why, then return
   to the known facts. Do not manufacture a lesson from every silence, call the gap revealing, or
   turn missing records into a profound-sounding conclusion.
5) Quote primary sources. Wherever a real document, chronicle, letter, inscription or traveller's
   account appears in the facts you were given, quote it directly and say who wrote it and roughly
   when. This is the strongest texture available here and it costs nothing.
6) SIGNPOST SPARINGLY. At most one orienting phrase per segment may help a listener who drifted
   and rejoined. Keep it brief and inside the factual movement. Do not open a paragraph with
   "To understand that, we need to look at..." or turn orientation into a repeated template.
7) CURIOUS, NEVER GRIPPING, AND FLAT IN ENERGY. The listener should stay mildly interested but must
   never NEED to know what happens next: no cliffhangers, no withheld reveals, no "what happened
   next would change everything" -- resolve things as you go. Keep the energy even start to finish,
   with no build to a climax and nothing a narrator would raise their voice for. Minute 80 should
   be about as engaging as minute 5. Viewers of this format complain specifically when an episode
   turns out too interesting to fall asleep to.
8) One narrator throughout. If a historical figure's words matter, quote them inside the narration
   ("He wrote that...", "According to the chronicle...") rather than performing them as a second
   speaker. Never write a dialogue tag for a second character.
9) A correction can be useful once in an opening when the supplied facts establish the mistaken
   belief. Do not make myth-busting a repeating structure or invent what "most people assume."
10) Avoid AI-giveaway phrasing: "these interconnected aspects," "revolutionary transformation,"
   "unprecedented," "groundbreaking," "let's dive in," "buckle up," "fascinating," "stay tuned,"
   "little did they know," "stands as a testament."
11) AUDIO-HOSTILE FORMATS. Never deliver a correspondence table or enumerated mapping as a list
   ("A means X, B means Y, C means Z, D means W"). A listener cannot track a memorisation list
   while drifting. If information requires mapping several items to their equivalents, embed the
   most important one or two naturally in prose and let the rest go: "Sogdian families took
   Chinese surnames keyed to their home cities — Kang for Samarkand, An for Bukhara" is enough;
   listing all five is audio-hostile. The same applies to any list of more than two items that
   requires active retention to use.
12) Stay inside the facts. Names, dates, numbers, events and decisions must come from the facts you
    were given. Modest scene-setting (weather, the look of a room) may be filled in, but keep it
    light and never invent a specific claim.
13) NEVER SELL THE STORY. Do not tell the listener a fact is important, surprising, or the reason
    the story exists ("that number is the reason this story gets told at all", "this is what
    matters most") — and write no aphoristic pivot lines that dress a fact up as a clever reversal
    ("It was, more precisely, a clock that did not exist yet"). Both read as a narrator pushing an
    agenda, and the listener hears the push. State the fact in plain order and move on; if it is
    interesting, it will be interesting on its own.
14) SAY IT ONCE. A fact, definition, or gloss appears in full exactly once in the whole piece.
    If it has already been narrated, touch it in half a sentence at most, naming the thing itself
    ("the wreck off Scilly", "the £20,000 prize") — never a second retelling, never a second gloss
    of a term already explained, and never a citation of your own narration ("as already covered
    in this account", "already described earlier"): the listener was asleep for half of it and
    the reference must read naturally either way. A person gets full name and title on first
    mention only; after that, surname alone.
15) EXACT AND CONSISTENT. Spell every name and place exactly as the material spells them, and keep
    every number and date identical each time it recurs. Never drift to a variant spelling, a
    different county, or a differently rounded figure for the same fact.
16) BANNED RHETORIC — each of these patterns reads as generated text, and one instance is enough
    to break the spell:
    - negation-first drama: "was not an abstraction", "This was not X. It was Y.", "Nobody had
      rescinded the Act — no clerk had misfiled it."
    - echo repetition: "It killed men, and it killed them in large numbers"; two consecutive
      sentences opening on the same negation ("No storm... No instrument...").
    - narration about the narration: "a gap worth naming plainly", "is where this story goes
      next", "a thread this account picks up later", "a separate thread we'll pick up".
    - referring to your source or your own narration: "the material", "the concepts you were
      given", "the record before us", "this account", "this telling", "as already noted", "as
      mentioned earlier", "already described", "that will be covered later". The listener must
      never sense a document behind the voice — refer back by naming the thing itself ("the
      wreck off Scilly"), and say "no ship's log names him", never "the material doesn't say".
    - profundity that doesn't parse: "outlasted him by only two days short of nothing at all".
    - stock thesis pivots: "At its heart", "crucially", "it is worth noting", "The picture most
      of us have", "And so we come to", "To understand that, we need to look at".
    Say the plain version instead, or cut the sentence.
17) HOW WE KNOW IS PART OF THE STORY. When the facts name a source — a chronicler, a signed
    certificate, an archive, a modern researcher — spend at most one paragraph on who recorded
    the fact and whether they witnessed it. Most segments need no archive paragraph. Never repeat
    that records are incomplete merely because the subject changed.
18) DO NOT KEEP RESTATING THE THESIS. A framing claim gets one full statement in the opening and
    may return briefly in the close. Inside the body, stay with the place and people in front of
    you. Do not repeatedly announce where power, wealth, knowledge, or the "real center" sat.

<examples>
AVOID (ornate and clause-folding -- the problem is the literary vocabulary and stacked imagery,
not the length): "Somewhere north of the Gobi, where the grass runs pale and long under a sky
that has no edge to it, the old riders gave a name to the wind that comes down off the mountains,
because it carried the cold that had slept all winter in the stone."
USE (plain vocabulary, medium-length, flowing -- not chopped into short fragments): "In early
spring a cold wind comes down off the Khentii mountains, and the riders who lived on that grass
had a name for it. They called it the grey wind, because it carried the cold that had been sitting
inside the stone all winter long."

AVOID (choppy -- short sentences stacked, subjects hopping, flat tails; this is the cheap AI
register): "They'd come from the Black Sea. A Franciscan friar named Michele da Piazza lived in
the city. He wrote down what happened. And here's the part almost nobody expects. The people who
lived through it came out better off."
USE (medium, flowing, dense, no empty announcements): "They had come from the Black Sea, and a
Franciscan friar named Michele da Piazza watched them dock and wrote down what he saw. What nobody
expected was that the people who lived through the years ahead would come out better off than
their parents had ever been."

AVOID (refuses to signpost): "The ships kept coming into port even as the deaths climbed."
USE (signposts openly): "We'll come back to those ships shortly. But first we need to talk about
where the sickness had already been, years before it ever reached Italy."

AVOID (suspense that keeps a listener awake): "What happened next would change the empire forever,
and not for the better..."
USE (resolves as it goes): "The decision was made that spring, and it turned out badly. We know
roughly why, because two of the men in the room wrote about it afterwards."

AVOID (no source, no number): "The city was enormous and impressed everyone who saw it."
USE (quoted source, hard number): "A Portuguese missionary called Antonio da Madalena reached it
in 1586. He wrote that it was 'of such extraordinary construction that it is not possible to
describe it with a pen.' The city covered more than a thousand square kilometres. That is larger
than modern New York."

AVOID (dialogue as a second speaker): "[Advisor]: My lord, the granaries are empty."
USE (reported in one voice): "His advisors told him the granaries were empty. One of them wrote
later that the king already knew."
</examples>
"""


LORE_COLD_OPEN_SYSTEM_PROMPT = """You are writing the opening of a long-form (about {target_minutes} minutes) "sleep-lore" history video: one continuous host narrating a true story from history, meant to run as background listening for someone falling asleep. The subject area is {subject}.

This opening is the most important passage in the piece, and for a reason specific to this format: listeners replay these videos many times and almost never reach the end, so the opening is the part actually heard.

It has to excite and intrigue. But the excitement comes from SCALE, PARADOX and WONDER -- never from suspense, threat, or withholding an answer. "Half of Europe died in four years, and the survivors came out richer" is the right kind of hook: it is startling, and it resolves rather than teases. A cliffhanger is the wrong kind.

Write it as four short movements, in one continuous flow. Do not label them or number them.

1. THE BIG PICTURE. Open wide. Before any specific scene, give the listener the whole subject at a glance and a reason to care about the next hour: the scale of the thing, the stakes, and the central paradox or surprise at the heart of it. Lead with your single most striking true fact or comparison drawn from the material you were given — do not reach outside it for a bigger statistic — stated in short plain sentences. A myth-bust is the strongest form -- name what most people assume, then say the evidence points somewhere else. This movement is what makes someone stay, and it must come FIRST. Do not open on a named individual on a particular afternoon; that is movement 2. Three to six short sentences.
2. THE SCENE. Now descend from the wide view into one specific, documented moment: a named person, a real date, a real place, drawn from the material you were given. The strongest version -- the device Fall of Civilizations uses in nearly every episode -- is a traveller from a LATER era stumbling on the remains of the thing this video is about: a missionary reaching ruins in the jungle, a scholar finding a buried library -- but use it only when the material supplies that traveller and their words. Quote a written source only if the material contains the quote; never invent one, recall one from memory, or introduce a person the material does not mention. Keep sensory description to a clause or two -- this is a factual scene, not a mood piece. Make the descent explicit if it helps ("But it starts with twelve ships.").
3. THE PROMISE. Tell the listener, in plain language, three or four specific and genuinely odd things they will hear about later. Name them concretely -- a lost legion, a letter that was never delivered, a king buried under a car park. Strange and specific is what makes this work. Do not write an abstract table of contents, and do not say "in this video we will explore."
4. THE SETTLE-IN. Close the opening by inviting the listener to get comfortable, in plain conversational words, as its own short beat. This is a genre convention and it is spoken directly, not woven into the historical scene: something in the spirit of "So get comfortable, dim the lights, and let's take this slowly." Then begin the story proper.

Do NOT end the opening on a cliffhanger or an unresolved threat. End it by simply starting.

{lore_language_guidelines}

Write only the opening passage itself, inside <cold_open>...</cold_open> tags -- no preamble, no meta-commentary, nothing outside the tags. Target length: {target_words} words."""

LORE_COLD_OPEN_USER_PROMPT = """The full story this video will tell is: "{topic}", covering:
<sections>
{sections}
</sections>

Use these to choose a documented opening scene, and to pick the three or four strangest, most specific details to name in the promise. Name those details concretely; do not restate the section list as an outline.
"""

def get_lore_cold_open_system_prompt(subject: str, target_minutes: int, target_words: int = 400) -> str:
    return LORE_COLD_OPEN_SYSTEM_PROMPT.format(
        subject=subject, target_minutes=target_minutes, target_words=target_words,
        lore_language_guidelines=lore_language_guidelines)


LORE_SEGMENT_SYSTEM_PROMPT = """You are the sole narrator of a long-form "sleep-lore" history video, continuing a story already in progress. You are about {progress_pct}% of the way through the piece; {pacing_note}

Your task is to turn one concept from the syllabus into its own self-contained segment that also advances the larger story. Getting the depth right is the entire craft here:

- BEGIN IN THE MATERIAL. Never open with "So let's", "Let's now look at", "Let's take X", or any sentence that announces what you are about to do. Never restate the topic as an opening line. The bridge before this segment has already set the direction — enter the content directly: open on a fact, a person, a date, or a place. The reader will follow without being told they are about to follow.
- Go deep — CONCRETE AND PROCEDURAL, not lyrical. Walk through the real mechanics step by step: how a ritual was performed, how a ship was loaded, how a law was enforced, who did which job and in what sequence. Name the people, dates, and numbers the listener needs, then allow a plain sentence between dense clusters. Use at most one human-scale comparison in the segment, for the single measurement that most needs it. Quote a source only when the supplied facts contain its words.
- Every 500-700 words of entity-dense narration, insert one 40-80 word atmospheric passage with near-zero proper nouns: the physical world the actors moved through — the weather, the terrain, the sounds, the texture of the place. These are not filler; they lower listener entity density and give the mind space to drift. Example register: "The road ran through flat country here, past fields that had been worked for centuries. The air in summer was thick with dust from the caravans, and it settled on everything within a mile of the main track." Then return to the facts.
- Keep the energy flat throughout. This segment must not be more dramatic than its neighbours; bring it to a plain resting point. END ON A FACT: the last sentence states a fact, plainly, and stops — never end by announcing what the account covers next ("What the Board made of that is where this story goes next"); the bridge handles the handoff. If a thread genuinely must wait, one plain mid-segment sentence ("We'll come back to the prize money.") is enough, and at most once every few segments.
- Write as much as this concept genuinely warrants — no more, no less. A concept with many specific documented facts may need 500-800 words; a genuinely narrower one may need 300. The test: would a new reader understand both what happened and why it mattered? Stop when yes.

{lore_language_guidelines}

Write only the substory itself, inside <segment>...</segment> tags -- no headers, no labels, no meta-commentary."""

LORE_SEGMENT_USER_PROMPT = """Topic of the overall piece: "{topic}"

What has happened in the narration so far (a compressed summary, not verbatim -- do not repeat it, just stay consistent with it and build from where it left off):
```
{narrative_so_far}
```

The concept to turn into this substory:
```
{concept}
```

What comes immediately after this substory, for your own awareness only (do not preview or mention it directly -- just make sure your ending thread points naturally toward it):
```
{upcoming}
```
"""

def get_lore_segment_system_prompt(progress_pct: int) -> str:
    # Deliberately close to flat: this format does not escalate, and most listeners are asleep.
    if progress_pct < 25:
        pacing_note = ("keep the energy level and unhurried. Concrete detail is what holds a "
                       "listener here, not drama. Place the listener in the world before "
                       "naming everything in it — keep entity density lighter here.")
    elif progress_pct < 60:
        pacing_note = ("hold the same steady register. This is the factual heart of the piece; "
                       "entity density can rise — listeners who have stayed are calibrated. "
                       "Do not escalate the emotional register, only the specificity.")
    else:
        pacing_note = ("hold the same steady register. Most listeners are already asleep. "
                       "Begin stepping back from dense proper-noun sequences toward reflective, "
                       "lower-density prose — the shape of the piece should be widening again, "
                       "not tightening. If the concept requires many unfamiliar proper nouns, "
                       "introduce only the two or three most essential ones; let the others "
                       "stay in the background or be omitted. A late-piece listener has no "
                       "mental headroom to track a new cast of characters.")
    return LORE_SEGMENT_SYSTEM_PROMPT.format(
        progress_pct=progress_pct, pacing_note=pacing_note,
        lore_language_guidelines=lore_language_guidelines)


LORE_BRIDGE_SYSTEM_PROMPT = """You are the sole narrator of a long-form sleep-lore history video, writing a short connective passage between two segments. Use one to three plain sentences.

If the two moments share a real cause, place, person, object, or date, name that connection once and move. If they do not, make a clean geographic or temporal scene cut; do not recap the previous passage merely to manufacture continuity. A bridge may ask a question occasionally, but most should not. Never use a fixed rotation of bridge templates.

Do not end the bridge by naming the next topic, in any phrasing — "X is next", "we turn to X now", "the towns are next", "we'll pick that up next", "we'll come to that next", "more on that shortly". Any sentence whose job is to promise that a topic is coming is the same violation regardless of which verb carries it. The bridge opens the door; the segment walks through it. End on a question, an image, or a pivot phrase — the next segment begins without re-announcement.

Do not use "That's where we'll leave X for now. To understand what happened next, we need to..." — it is a stock template and sounds like one after the third repetition. Do not end on a tease or cliffhanger.

{lore_language_guidelines}

Write only the bridge passage, inside <bridge>...</bridge> tags."""

LORE_BRIDGE_USER_PROMPT = """End of the substory just told:
```
{previous_ending}
```

Where the next substory begins:
```
{next_opening_note}
```
"""

def get_lore_bridge_system_prompt() -> str:
    return LORE_BRIDGE_SYSTEM_PROMPT.format(lore_language_guidelines=lore_language_guidelines)


LORE_CLOSE_SYSTEM_PROMPT = """You are the sole narrator, writing the closing passage of a long-form sleep-lore history video. By now the listener may well be asleep, and that is a success, not a failure -- write for whichever is true. This passage should:

- Introduce no new information or concepts.
- Return briefly to the opening question or scene, and give the plainest honest answer. Then let the topic stay larger than the telling: the best closes acknowledge that this subject contains more than one video can hold, without teasing a sequel. A quiet image that carries the open question works better than a neat summary — leave something still standing.
- In the final paragraph, narrow to one concrete object, place, or physical action already present
  in the opening. Introduce no comparison, new region, thesis, or historical balancing there.
- End with "Good night" — two words, on their own, as the last thing spoken. Do not address the listener directly in the final passage ("you don't have to follow the rest of this," "you don't have to stay awake"); direct address at the end risks waking someone who is drifting. Let the image and "Good night" do the releasing work.
- Do not tease a next episode.

{lore_language_guidelines}

Write only the closing passage, inside <close>...</close> tags. Target length: {target_words} words."""

LORE_CLOSE_USER_PROMPT = """Topic of the piece: "{topic}"

The opening image/question this piece began with:
```
{opening_note}
```

How the story arrived, in brief (for your own continuity -- do not restate it):
```
{narrative_so_far}
```
"""

def get_lore_close_system_prompt(target_words: int = 250) -> str:
    return LORE_CLOSE_SYSTEM_PROMPT.format(target_words=target_words,
                                           lore_language_guidelines=lore_language_guidelines)