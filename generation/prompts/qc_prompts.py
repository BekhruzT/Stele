QC_FINDER_SYSTEM_PROMPT = """You are a quality assurance specialist for educational content. Your task is to evaluate a {general_content} from an AP World History video lesson against specific quality criteria. {context} You will be provided with a guideline and an {general_content}. Your job is to compare the {general_content} against the guideline and determine whether the {general_content} meets the defined requirements.

The {general_content} you will be evaluating is the "{content_type}", which {content_description}. Here are the quality criteria you will use to evaluate the {general_content}:

<quality_criteria>
{quality_criteria}
</quality_criteria>

### Task: Evaluate the {general_content} against each criterion individually. For each criterion:
   a. Assess. Balanced objective assessment of whether the {general_content} meets the criterion.
   b. Evaluate. Final evaluation indicating whether the {general_content} is PASS or FAIL for the given guideline.
   c. Suggest. If the {general_content} fails the criterion, suggest the improvement to address the issue.

### Instructions
**Assessment**
- Approach this task critically, examining every detail of the text. Don't be lenient or ignore any potential issues. Be critical yet fair, pointing out only valid problems and violations.
- Give a detailed explanation of your assessment, highlighting the specific areas where the {general_content} either complies with or fails to meet the criteria.

**Language**
- Throughout use direct and straightforward language. 
- Be concise but specific in your assessments and suggestions. 
  - If you identify something is failing the guideline point it out specifically without any generalities or abstractions, quote the substring of concern and specifically indicate the issue with it.
  - Any level of vagueness may result in misinterpretation of the content, which can lead to dreadful consequences so be extremely specific and direct in pointing out the issue as well as defining the suggestion.

**Output**
- Your final response must be a Markdown complying with the following schema.

### Guideline Name
**Assessment**
<Detailed analysis, with issues highlighted as bullet points>

**Evaluation**
<evaluation>PASS || FAIL</evaluation>

**Recommendations**
<For each issue, provide a simple solution>"""

QC_FINDER_USER_PROMPT = """Here is the {general_content} you will be evaluating:

{transcript_segment}

{context}
"""

QC_FIXER_USER_PROMPT = """There were some problems found with the generated transcript segment. Please revise the following evaluation and adjust the segment accordingly. Here are some guidelines:

- Critical Thinking. Be discerning as some assessments or suggestions may be incorrect. 
   - If they contradict the instructions given above about the best practices for generating the transcript segment, feel free to disregard them.
   - If the assessments hold some truth and the suggestions can be implemented without breaking the guidelines for this segment, please incorporate them.
- Minimalism. Don't fix issues that weren't identified. Keep your entire output the same, except for the specific areas where you're instructed to make changes.
- Coherence. While most changes you make will be local, you must consider the overall flow of the entire segment. Ensure that the transcript remains coherent and flows smoothly, with one idea naturally leading into the next without any sudden breaks or unexpected shifts. 
   - Make sure the text surrounding the changes blends seamlessly with both the change and the rest of the transcript.
   - The segment should still read like a well-crafted story that develops smoothly to keep the user engaged and not lose their interest. 
- Consistency. Revise your previous output using the exact same tags, while incorporating the provided feedback.

<evaluation>
{finder}
</evaluation>
"""

transcript_content_guidelines = {
    "LESSON INTRODUCTION": {
        "description": "introduces the lesson topic with relevant background information and provides a concise overview of the main points the lesson will cover",
        "guidelines": """- Abbreviations. No abbreviations are used. 
  - Consider replacing essential topic abbreviations with a brief, explanatory phrase.
  - For example, instead of 'UN', use 'all countries working together for peace'. The replacement for these abbreviations depends on the context. However, aim to keep this replacement concise, ideally no more than 4 words. The shorter, the better.
  - Rewrite abbreviations that are not terminologies in their complete form. For example, use "twentieth" instead of "20th".

- Context Relevance. The context, provided in the second sentence, is crucial for understanding the forthcoming lesson outlined in the subsequent overview. It sets the necessary background, clarifying the purpose without including irrelevant details.
  - Identify any context sub-phrases that seem irrelevant and propose a correction. We aim to avoid non-essential contextual details to prevent overwhelming or confusing the student.

- Spoken language: This segment relies entirely on spoken language, not written language. The transcript can be read aloud to a student verbatim without causing confusion.
  - Non-verbal punctuation: Replace any violations with prepositions or succinct sub-phrases.
    - For instance, rather than saying "Confucianism - a philosophy that...", say "Confucianism is a philosophy that...". 
    - If slashes are used, substitute them with commas (which are acceptable punctuation marks), or words like "or" or "either", etc.
    - Punctuation that indicates the speed of speech, tone, or style is acceptable and should be kept.
    - Unless the punctuation must be replaced with a preposition or a sub-phrase, it is not an error and should be maintained.
  - Bracket usage: Brackets are used for natural verbal asides that flow with speech, such as additional context or references to previous topics. The guideline is that you should be able to read the text aloud, word for word, while ignoring the brackets.
    - Acceptable bracket usage example: "greenhouse gases (which are responsible for rising temperatures)". Reading this aloud, word for word, while ignoring the brackets will maintain the accuracy and clarity of the spoken language.
    - Unacceptable bracket usage example: "... a few proactive shots (vaccines) could...". This should be rewritten as "... a few proactive shots, or vaccines, could ....".

- Neutral Global Perspective. The host must maintain a neutral global perspective without assuming a shared national identity with the audience.
  - No National Ownership: The host should never refer to any nation or culture as "our," "my," or "your" (e.g., "our country," "our democracy," "our ancestors").
    - Example of Violation: "Next, let's discuss how our young nation faced challenges after independence" assumes the audience identifies with that specific nation.
    - Example of Compliance: "Next, let's discuss how the United States faced challenges after independence" maintains objective perspective.
  - Geographic References: When geographic or cultural references are necessary, they should be stated objectively without implying the audience shares that identity.
    - Example of Violation: "In our Western tradition, democracy has been important."
    - Example of Compliance: "In the Western tradition, democracy has been important."
  - Historical Context: Even when discussing events where national identity might be relevant, the host should maintain historical objectivity rather than implying shared heritage.
    - Example of Violation: "Our founding fathers established a new form of government."
    - Example of Compliance: "America's founding fathers established a new form of government."
 """
    },
    "SECTION OVERVIEW": {
        "description": "introduces the section topic and briefly outlines the key concepts to be explored",
        "guidelines": """- Abbreviations. No abbreviations are used. 
  - Consider replacing essential topic abbreviations with a brief, explanatory phrase.
  - For example, instead of 'UN', use 'all countries working together for peace'. The replacement for these abbreviations depends on the context. However, aim to keep this replacement concise, ideally no more than 4 words. The shorter, the better.
  - Rewrite abbreviations that are not terminologies in their complete form. For example, use "twentieth" instead of "20th".

- Concise Overview. The lesson overview, presented in the final sentence, should concisely list all the main points of the upcoming lesson. Every detail mentioned must be essential for understanding the forthcoming lesson; otherwise, it should be omitted.
  - If you notice unnecessary detail or repetition, please suggest a correction.

- Spoken language: This segment relies entirely on spoken language, not written language. The transcript can be read aloud to a student verbatim without causing confusion.
  - Non-verbal punctuation: Replace any violations with prepositions or succinct sub-phrases.
    - For instance, rather than saying "Confucianism - a philosophy that...", say "Confucianism is a philosophy that...". 
    - If slashes are used, substitute them with commas (which are acceptable punctuation marks), or words like "or" or "either", etc.
    - Punctuation that indicates the speed of speech, tone, or style is acceptable and should be kept.
    - Unless the punctuation must be replaced with a preposition or a sub-phrase, it is not an error and should be maintained.
  - Bracket usage: Brackets are used for natural verbal asides that flow with speech, such as additional context or references to previous topics. The guideline is that you should be able to read the text aloud, word for word, while ignoring the brackets.
    - Acceptable bracket usage example: "greenhouse gases (which are responsible for rising temperatures)". Reading this aloud, word for word, while ignoring the brackets will maintain the accuracy and clarity of the spoken language.
    - Unacceptable bracket usage example: "... a few proactive shots (vaccines) could...". This should be rewritten as "... a few proactive shots, or vaccines, could ....".

- Neutral Global Perspective. The host must maintain a neutral global perspective without assuming a shared national identity with the audience.
  - No National Ownership: The host should never refer to any nation or culture as "our," "my," or "your" (e.g., "our country," "our democracy," "our ancestors").
    - Example of Violation: "Next, let's discuss how our young nation faced challenges after independence" assumes the audience identifies with that specific nation.
    - Example of Compliance: "Next, let's discuss how the United States faced challenges after independence" maintains objective perspective.
  - Geographic References: When geographic or cultural references are necessary, they should be stated objectively without implying the audience shares that identity.
    - Example of Violation: "In our Western tradition, democracy has been important."
    - Example of Compliance: "In the Western tradition, democracy has been important."
  - Historical Context: Even when discussing events where national identity might be relevant, the host should maintain historical objectivity rather than implying shared heritage.
    - Example of Violation: "Our founding fathers established a new form of government."
    - Example of Compliance: "America's founding fathers established a new form of government."
 """
    },
    "CURIOUS QUESTION": {
        "description": "poses an intriguing question that builds on previous knowledge and guides the conversation towards the next concept of interest",
        "guidelines": """Use the below guidelines only to evaluate the question appearing as the last sentence of the transcript segment, ignore the text preceding and any violations it may have. Focus on the question, while applying the guidelines below:
  
- Abbreviations. Use abbreviations that can be pronounced letter by letter. Avoid those that require a different pronunciation than what the individual letters suggest, or those that include punctuation. 
  - If any violations are found, suggest a fix. Try to preserve the abbreviation if possible, or rewrite it in the form that is most commonly spoken. The focus should be on verbal accuracy, not written form. Feel free to suggest the abbreviation is dropped, if necessary.
  - Examples of unsuitable abbreviations:
    - "WWI" is not pronounced as "WW Eye". It should be written as "World War One". To preserve the abbreviation, you could rewrite it as "WW One", but that's not how it's typically spoken.
    - "Dr." includes a period. It should be written as "Doctor"
    - 20th - is an ordinal. Should be rewritten as twentieth
  - Examples of appropriate abbreviations, which are also appropriate for spoken language. You should retain all abbreviations that can be accurately pronounced letter by letter or in their entirety.
    - UN, UNICEF, GDP, NASA, W3C, iOS.
    
- Spoken language: This segment relies entirely on spoken language, not written language. The transcript can be read aloud to a student verbatim without causing confusion.
  - Non-verbal punctuation: Replace any violations with prepositions or succinct sub-phrases.
    - For instance, rather than saying "Confucianism - a philosophy that...", say "Confucianism is a philosophy that...". 
    - If slashes are used, substitute them with commas (which are acceptable punctuation marks), or words like "or" or "either", etc.
    - Punctuation that indicates the speed of speech, tone, or style is acceptable and should be kept.
    - Unless the punctuation must be replaced with a preposition or a sub-phrase, it is not an error and should be maintained.
  - Bracket usage: Brackets are used for natural verbal asides that flow with speech, such as additional context or references to previous topics. The guideline is that you should be able to read the text aloud, word for word, while ignoring the brackets.
    - Acceptable bracket usage example: "greenhouse gases (which are responsible for rising temperatures)". Reading this aloud, word for word, while ignoring the brackets will maintain the accuracy and clarity of the spoken language.
    - Unacceptable bracket usage example: "... a few proactive shots (vaccines) could...". This should be rewritten as "... a few proactive shots, or vaccines, could ....".

- Neutral Global Perspective. The host must maintain a neutral global perspective without assuming a shared national identity with the audience.
  - No National Ownership: The host should never refer to any nation or culture as "our," "my," or "your" (e.g., "our country," "our democracy," "our ancestors").
    - Example of Violation: "Next, let's discuss how our young nation faced challenges after independence" assumes the audience identifies with that specific nation.
    - Example of Compliance: "Next, let's discuss how the United States faced challenges after independence" maintains objective perspective.
  - Geographic References: When geographic or cultural references are necessary, they should be stated objectively without implying the audience shares that identity.
    - Example of Violation: "In our Western tradition, democracy has been important."
    - Example of Compliance: "In the Western tradition, democracy has been important."
  - Historical Context: Even when discussing events where national identity might be relevant, the host should maintain historical objectivity rather than implying shared heritage.
    - Example of Violation: "Our founding fathers established a new form of government."
    - Example of Compliance: "America's founding fathers established a new form of government."
    
- Referring to the historical figure: The question may need to directly address the historical figure who will be answering it. The user will specify if this is necessary. If it's not required, bypass this step and consider it a PASS.
  - If a direct reference is needed, simply modify the question by adding the historical figure's name at the beginning. The user will inform you of the figure's identity.
    - Example. Figure: Confucius. Question: How did your philosophy shape Chinese society? => "Confucius, how did your philosophy shape Chinese Society?" - Keep this change very simple just direct the question at the figure by mentioning their name at the start (if not already) and keep the rest of the question exactly as is.
  - Your suggestion should clarify that indeed the previous explanation was not delivered by the current historical figure, however the next explanation will be.
    - "The previous explanation and recap focused on a different figure; however, the upcoming question and explanation will be directed at figure X. Therefore, figure X name must be mentioned in the question, even though it hasn't appeared previously. This is a hard requirement."
"""
    },
    "CONCEPT EXPLANATION": {
        "description": "is a thorough explanation of a specific concept delivered by a historic figure",
        "guidelines": """
- Complete Concept Coverage: The explanation should cover all aspects listed in the concept syllabus without any omissions.
  - Full Coverage: Every piece of information, term, or detail listed in the concept syllabus should be included in the explanation.
    - Example of Compliance: If the syllabus refers to "three types of Roman social classes: patricians, plebeians, and slaves," the explanation should mention all three classes, not just patricians and plebeians.
    - Example of Violation: If the syllabus mentions "effects of the Columbian Exchange on both European and Native American populations" but the explanation only discusses European impacts, this would be considered incomplete coverage.
  - Depth is not a criterion. While the explanation should touch on every sub-detail in the syllabus, the level of detail for each point can vary based on its importance. If some points are explained more thoroughly than others, as long as all points are mentioned, it's acceptable.
  - If the explanation fails to meet the criteria, in your feedback: identify the specific details that were missed and suggest where they could be included. Keep your suggestions focused on what was missed and where it could be added, without recommending how extensively the missing detail should be covered.
  - Ideally, the transcript's language should closely match the syllabus, covering details as precisely as specified. Minor adaptations for smoother language and flow are acceptable, but they shouldn't result in significant differences or even slight inaccuracies in the content.
  - Fail the transcript if it omits even the smallest detail or uses imprecise language that doesn't align with the syllabus, leading to incorrect learning.

- Out of syllabus check: The transcript should not add any new detail at any cost apart from what is in the concept syllabus.
  - For example: When explaining Reconquista, if the facts don't mention fall of Granada, transcript also should not mention it. Even such tiny details should not be added even for the sake of completeness.
  - For example: When talking about story of Columbus reaching some shore with his ships, transcript should not add names of the ships itself if the facts don't mention them. It can say "Columbus reached xyz shore with his ships" but not "Columbus reached xyz shore with his ships  Nina, Pinta and Santa Maria" if the facts don't have the names of the ships.
  - For example: When talking about the Aztec Empire, if the facts dont' mention lake Texcoco, transcript should also not mention it. Even though how linked it is to the Aztec Empire, it should not be added.
  - If these details are not present, it is because they are not important for the concept and should not be added to avoid cognitive load. Flag if any such details are added.
  
## Smooth Flow and Transitions

- Transitions between sentences and paragraphs. Ensure each new idea connects logically to the previous one without abrupt shifts that might confuse listeners.
  - Abrupt transitions occur when new concepts, terminology, or examples are introduced without proper setup or connection to previous content.
  - If a term/concept is introduced and their relevance becomes clear post their introduction this is a strong violation. Always ensure that term's/concept's importance is clear beforehand by linking it explicitly to previous content. A sentence should never start with a new concept or term. Instead, begin sentences with connecting phrases that weave everything into a seamless narrative. 
  - If violations are found, suggest a transitional phrase or clarifying context to create a bridge between ideas.
  - If a background context or an example is given before explaining the main idea, the transcript must clearly link the context or example to the idea being explained. The concept should not be introduced unless this clear connection is made.
- Examples of violations and compliances:
    - Example of Violation: "That's how the arms race worked during the Cold War. The 'military-industrial complex' is the tight link between armed forces and weapons builders..." - Military-industrial complex is introduced at sentence start, with no explicit build up from the Arms Race. It's unclear why the term is relevant. 
    - Example of Compliance: "That's how the arms race worked during the Cold War. This competition was intensified by what became known as the 'military-industrial complex' - the tight link between armed forces and weapons builders..."
    - Example of Violation: "Others, like the White Revolution in Iran, showed peaceful land redistribution programs meant to lessen old inequalities. Now, communism and socialism both focus on spreading resources more evenly..." - Sentence starts with introducing idealistic concepts: communism and socialism without a connecting phrase to clarify relevance.
    - Example of Compliance: "Others, like the White Revolution in Iran, showed peaceful land redistribution programs meant to lessen old inequalities. Many of these post-colonial resource redistributions were inspired by socialist or communist ideals as a way to address the economic inequalities left by colonialism. These ideals advocate spreading resources more evenly..."
    - Example of Violation: "Many newly independent nations struggled with corruption. Patronage systems distribute jobs and resources based on loyalty rather than merit." - Sentence starts with "Patronage systems" without connecting to the context of  post-colonial corruption.
    - Example of Compliance: "Many newly independent nations struggled with corruption. This corruption often took the form of patronage systems, which distribute jobs and resources based on loyalty rather than merit."

- Spoken language: This segment relies entirely on spoken language, not written language. The transcript can be read aloud to a student verbatim without causing confusion.
  - Non-verbal punctuation: Replace any violations with prepositions or succinct sub-phrases.
    - For instance, rather than saying "Confucianism - a philosophy that...", say "Confucianism is a philosophy that...". 
    - If slashes are used, substitute them with commas (which are acceptable punctuation marks), or words like "or" or "either", etc.
    - Punctuation that indicates the speed of speech, tone, or style is acceptable and should be kept.
    - Unless the punctuation must be replaced with a preposition or a sub-phrase, it is not an error and should be maintained.
  - Bracket usage: Brackets are used for natural verbal asides that flow with speech, such as additional context or references to previous topics. The guideline is that you should be able to read the text aloud, word for word, while ignoring the brackets.
    - Acceptable bracket usage example: "greenhouse gases (which are responsible for rising temperatures)". Reading this aloud, word for word, while ignoring the brackets will maintain the accuracy and clarity of the spoken language.
    - Unacceptable bracket usage example: "... a few proactive shots (vaccines) could...". This should be rewritten as "... a few proactive shots, or vaccines, could ....".

- Abbreviations. Use abbreviations that can be pronounced letter by letter. Avoid those that require a different pronunciation than what the individual letters suggest, or those that include punctuation. 
  - If any violations are found, suggest a fix. Try to preserve the abbreviation if possible, or rewrite it in the form that is most commonly spoken. The focus should be on verbal accuracy, not written form. Feel free to suggest the abbreviation is dropped, if necessary.
  - Examples of unsuitable abbreviations:
    - "WWI" is not pronounced as "WW Eye". It should be written as "World War One". To preserve the abbreviation, you could rewrite it as "WW One", but that's not how it's typically spoken.
    - "Dr." includes a period. It should be written as "Doctor"
    - 20th - is an ordinal. Should be rewritten as twentieth
  - Examples of appropriate abbreviations, which are also appropriate for spoken language. You should retain all abbreviations that can be accurately pronounced letter by letter or in their entirety.
    - UN, UNICEF, GDP, NASA, W3C, iOS.
  """
    },
    "RECAP": {
        "description": "summarizes the insights from the viewpoint of a student who has recently grasped a new concept",
        "guidelines": """- Abbreviations. Use abbreviations that can be pronounced letter by letter. Avoid those that require a different pronunciation than what the individual letters suggest, or those that include punctuation. 
  - If any violations are found, suggest a fix. Try to preserve the abbreviation if possible, or rewrite it in the form that is most commonly spoken. The focus should be on verbal accuracy, not written form. Feel free to suggest the abbreviation is dropped, if necessary.
  - Examples of unsuitable abbreviations:
    - "WWI" is not pronounced as "WW Eye". It should be written as "World War One". To preserve the abbreviation, you could rewrite it as "WW One", but that's not how it's typically spoken.
    - "Dr." includes a period. It should be written as "Doctor"
    - 20th - is an ordinal. Should be rewritten as twentieth
  - Examples of appropriate abbreviations, which are also appropriate for spoken language. You should retain all abbreviations that can be accurately pronounced letter by letter or in their entirety.
    - UN, UNICEF, GDP, NASA, W3C, iOS.

- Spoken language: This segment relies entirely on spoken language, not written language. The transcript can be read aloud to a student verbatim without causing confusion.
  - Non-verbal punctuation: Replace any violations with prepositions or succinct sub-phrases.
    - For instance, rather than saying "Confucianism - a philosophy that...", say "Confucianism is a philosophy that...". 
    - If slashes are used, substitute them with commas (which are acceptable punctuation marks), or words like "or" or "either", etc.
    - Punctuation that indicates the speed of speech, tone, or style is acceptable and should be kept.
    - Unless the punctuation must be replaced with a preposition or a sub-phrase, it is not an error and should be maintained.
  - Bracket usage: Brackets are used for natural verbal asides that flow with speech, such as additional context or references to previous topics. The guideline is that you should be able to read the text aloud, word for word, while ignoring the brackets.
    - Acceptable bracket usage example: "greenhouse gases (which are responsible for rising temperatures)". Reading this aloud, word for word, while ignoring the brackets will maintain the accuracy and clarity of the spoken language.
    - Unacceptable bracket usage example: "... a few proactive shots (vaccines) could...". This should be rewritten as "... a few proactive shots, or vaccines, could ....".

- Straightforward. The language mirrors an enthusiastic student sharing their recent discoveries, but does so in a way that is succinct and reflective, without unnecessary embellishment or pretense.

- Neutral Global Perspective. The host must maintain a neutral global perspective without assuming a shared national identity with the audience.
  - No National Ownership: The host should never refer to any nation or culture as "our," "my," or "your" (e.g., "our country," "our democracy," "our ancestors").
    - Example of Violation: "Next, let's discuss how our young nation faced challenges after independence" assumes the audience identifies with that specific nation.
    - Example of Compliance: "Next, let's discuss how the United States faced challenges after independence" maintains objective perspective.
  - Geographic References: When geographic or cultural references are necessary, they should be stated objectively without implying the audience shares that identity.
    - Example of Violation: "In our Western tradition, democracy has been important."
    - Example of Compliance: "In the Western tradition, democracy has been important."
  - Historical Context: Even when discussing events where national identity might be relevant, the host should maintain historical objectivity rather than implying shared heritage.
    - Example of Violation: "Our founding fathers established a new form of government."
    - Example of Compliance: "America's founding fathers established a new form of government."

- Brief. There's no superfluous detail or repetition. The entire reflection flows naturally and doesn't become tedious. There's no part that could be removed without sacrificing engagement or valuable content summary.
  - If you spot any chance to be more succinct without compromising content or meaning, feel free to suggest a revision.
""",
    },
        "LESSON CONCLUSION": {
        "description": "concludes the lesson by briefly reviewing the key learnings and integrating them into a larger, cohesive narrative",
        "guidelines": """- Abbreviations. Use abbreviations that can be pronounced letter by letter. Avoid those that require a different pronunciation than what the individual letters suggest, or those that include punctuation. 
  - If any violations are found, suggest a fix. Try to preserve the abbreviation if possible, or rewrite it in the form that is most commonly spoken. The focus should be on verbal accuracy, not written form. Feel free to suggest the abbreviation is dropped, if necessary.
  - Examples of unsuitable abbreviations:
    - "WWI" is not pronounced as "WW Eye". It should be written as "World War One". To preserve the abbreviation, you could rewrite it as "WW One", but that's not how it's typically spoken.
    - "Dr." includes a period. It should be written as "Doctor"
    - 20th - is an ordinal. Should be rewritten as twentieth
  - Examples of appropriate abbreviations, which are also appropriate for spoken language. You should retain all abbreviations that can be accurately pronounced letter by letter or in their entirety.
    - UN, UNICEF, GDP, NASA, W3C, iOS.
    
- Spoken language: This segment relies entirely on spoken language, not written language. The transcript can be read aloud to a student verbatim without causing confusion.
  - Non-verbal punctuation: Replace any violations with prepositions or succinct sub-phrases.
    - For instance, rather than saying "Confucianism - a philosophy that...", say "Confucianism is a philosophy that...". 
    - If slashes are used, substitute them with commas (which are acceptable punctuation marks), or words like "or" or "either", etc.
    - Punctuation that indicates the speed of speech, tone, or style is acceptable and should be kept.
    - Unless the punctuation must be replaced with a preposition or a sub-phrase, it is not an error and should be maintained.
  - Bracket usage: Brackets are used for natural verbal asides that flow with speech, such as additional context or references to previous topics. The guideline is that you should be able to read the text aloud, word for word, while ignoring the brackets.
    - Acceptable bracket usage example: "greenhouse gases (which are responsible for rising temperatures)". Reading this aloud, word for word, while ignoring the brackets will maintain the accuracy and clarity of the spoken language.
    - Unacceptable bracket usage example: "... a few proactive shots (vaccines) could...". This should be rewritten as "... a few proactive shots, or vaccines, could ....".
    
  - Neutral Global Perspective. The host must maintain a neutral global perspective without assuming a shared national identity with the audience.
  - No National Ownership: The host should never refer to any nation or culture as "our," "my," or "your" (e.g., "our country," "our democracy," "our ancestors").
    - Example of Violation: "Next, let's discuss how our young nation faced challenges after independence" assumes the audience identifies with that specific nation.
    - Example of Compliance: "Next, let's discuss how the United States faced challenges after independence" maintains objective perspective.
  - Geographic References: When geographic or cultural references are necessary, they should be stated objectively without implying the audience shares that identity.
    - Example of Violation: "In our Western tradition, democracy has been important."
    - Example of Compliance: "In the Western tradition, democracy has been important."
  - Historical Context: Even when discussing events where national identity might be relevant, the host should maintain historical objectivity rather than implying shared heritage.
    - Example of Violation: "Our founding fathers established a new form of government."
    - Example of Compliance: "America's founding fathers established a new form of government."  
    """
    },
}


mcq_guidelines = {
    "MCQs": {
        "description": "assess how well students have understood the concept they have been just taught in the video",
        "guidelines": """
Some context on MCQ's: The correct answer option is labeled as 'correct: true', while the incorrect distractor options as 'correct: false'.
## Transcript-Based Answers
Answerable from Transcript: Every MCQ must be fully answerable using only the information provided in the concept transcript. 

- Context: This guideline applies only to evaluating the correct answer option, not the distractors.

- Requirements:
  - The correct answer must be clearly supported by information in the lesson transcript. It does not have to be explicitly stated; it can be implied or inferred, as long as the transcript provides all necessary information to determine the correct answer.
    - Example of Compliance: If the transcript describes Athenian democracy by explaining the role of the Assembly and limited citizenship, a question asking "Which feature distinguished Athenian democracy?" with answer options related to these points is acceptable.
    - Example of Violation: If the transcript states "The Ming Dynasty engaged in maritime exploration," but the question asks about the impacts of Zheng He's voyages to the Hormuz Islands, which were not covered, this would require outside knowledge and is unacceptable.
  - The correct answer can be subtly implied, as long as students can reasonably infer it from information provided in the lesson. It is also acceptable if students can identify the correct answer by eliminating incorrect options using only information available in the transcript.

- Suggestions for Evaluation:
  - When reviewing a question, clearly identify the information in the lesson that supports the correct answer. If you cannot find relevant details or reasoning in the lesson to justify the correct answer or to eliminate incorrect options, the question does not meet this requirement.
  - If a violation occurs, clearly state what information is missing. Request that the question be revised so students can answer it using only information provided in the lesson, while still assessing important historical concepts from the syllabus.

## Transcript-Sourced Explanations
Explanation Content Validity: The explanations for each MCQ option must be clear and relevant, as well as understandable from the information in the transcript.

- Requirements for Correct Answer Explanations:
  - Explanations for correct answers must rely entirely on information provided in the transcript and should not introduce external knowledge.
    - Example of Violation: An explanation stating, "This aligns with historian Peter Frankopan's thesis about the Silk Roads as central to world history," introduces external information if the transcript never discusses this historian or thesis.
  - Slight and subtle inclusion of external context is acceptable only if the main reasoning clearly remains based on historical information provided in the transcript.

- Requirements for Incorrect Answer Explanations:
  - Explanations for incorrect answers must clearly show how information from the transcript contradicts the incorrect option. Minor external context is acceptable only if it supplements reasoning primarily based on the transcript.
    - Example of Acceptable Minor Context: Explaining why "The Ming Dynasty prioritized naval exploration above all other policies" is incorrect by stating, "Although the Ming Dynasty initially supported naval voyages under Zheng He, these voyages were later abandoned in favor of other priorities," adds minimal external context while still relying mainly on transcript content.

- Suggestions for Evaluation:
  - If violations occur, clearly identify the violation and suggest how to fix it. For correct answers, suggest ways to better align the explanation with information provided in the transcript.
    - Your suggested explanation should not reference information sources or use phrases such as "transcript," "syllabus," "text," "is mentioned," or "according to." Instead, keep explanations focused entirely on clarifying historical concepts rather than justifying through evidence or sources.

## External Source References in Explanations

- Requirements
  - Questions, answer options, and explanations must not reference external sources of information. Avoid phrases such as "transcript," "syllabus," "content," "narrative," "text," "the explanation," "is mentioned," "according to," etc. Students do not have access to these sources, and referencing them will confuse students.
  - Questions, answer options, and explanations should rely solely on historical terms and information. They should directly discuss historical facts and concepts without mentioning external sources.

- Suggestions for Evaluation:
  - If you identify any such reference, suggest a fix. Usually, simply removing the reference while keeping the surrounding wording intact will resolve the issue.

## Answer Length Balance

- Length Distribution Across Options: The correct answer should not be identifiable merely by its length, as this creates an artificial cue unrelated to content knowledge.
  - Evaluate the MCQs against this guideline only if explicitly requested by the user. This is an optional guideline, so unless the user requests evaluation of, PASS the MCQs on this front.
  - If guideline is to be evaluated:
    1) Identify each MCQ with a correct option shorter than the longer one
    2) Suggest specific extensions for one or two incorrect options based on transcript content
       - Remember options should maintain similar structure, specificity, and detail level while remaining historically 
       - Alternatively, suggest how the correct answer might be condensed if it contains unnecessary elaboration
"""
    } 
}

MCQ_FIXER_USER_PROMPT = """There were some issues identified with the generated MCQs. Please revise the evaluation below and adjust the MCQs accordingly. Make only the minimal edits necessary, continuing to follow the original guidelines. Maintain the same language and format.
- Exclude any mention of historical sources as justification or in any other context, even if specifically suggested in the evaluation. This includes terms such as "passage," "content," "narrative," "transcript," "syllabus," "mentioned," etc.
  - Example Violation: "These northern European nations were not specified as sponsors of northern Atlantic exploration during this era.". Instead could be "These northern European nations were not the main sponsors of northern Atlantic exploration during this era, but rather England, France, and the Netherlands were." Note how there is no reference to external sources (e.g. not specified) but direct discussion of historical facts presented in the transcript.
- The correct answer and explanation must be directly based on the transcript. Do not include any external or unrelated information.
- The explanation for the correct answer should not simply restate the question and answer. Instead, it should include supporting historical details directly from the transcript without explicitly referencing it. Do not add any external details not originally present in the transcript.
- Do not alter the question, answer, or explanation unless strictly necessary based on this evaluation.

<evaluation>
{finder}
</evaluation>"""


videoplan_guidelines = {
    "SEQUENCING AND GROUPING": {
        "description": "organizes historical content into a logical, pedagogically sound structure with appropriate sequencing and grouping of facts",
        "guidelines": """
- Complete Facts Coverage. Every fact from the original syllabus must appear in the video plan without exception.
  - Facts Inclusion: Every individual fact from the syllabus must be included verbatim in the video plan.
  - Evaluate the plan against this guideline only if explicitly requested by the user. This is an optional guideline, so unless the user requests evaluation of, PASS the MCQs on this front. If evaluation is requested, user will specify the missing facts, make sure to quote them in your evaluation and request they are added at an appropriate place, in line with best practices of sequencing and grouping.

- Simple Section Titles. 
Section titles must be simple, clear, and directly representative of the included content.
  - Straightforward Terminology: Titles should use common language unless specific historical terms are directly mentioned in the concepts the section covers.
    - Example of Compliance: Using "Tang Dynasty Expansion" when the concepts directly discuss Tang territorial growth and policies.
    - Example of Violation: Using specialized terminology like "Bretton Woods Organizations" when underlying concepts discuss "IMF and World Bank" but never directly reference them as "Bretton Wood Organizations"
    - Example of Violation: Using unnecessarily complex wording, even if it's not historical terminology—for example, saying "Geopolitical Power Equilibrium Dynamics" instead of the simpler "Geopolitical Power Balances".
  - Titles should be concise (1-6 words), student-friendly, and avoid listing style (e.g., "Politics and Society").
  - If violations occur, suggest clearer, more representative titles that maintain accuracy while improving accessibility.

- Organization
  - Ideal guidelines for organizing facts into concepts and sections (these are recommendations, not strict pass/fail rules):
    - Each concept should have between 2 and 4 facts.
    - Each section should have between 2 and 5 concepts.
  - Violations that FAIL QC:
    - A section contains only one concept. If this happens, request that the concept be moved and the affected sections adjusted accordingly.
    - Three or more concepts each contain 4 facts. If this occurs, request rearranging facts to reduce density. Too many concepts with 4 facts each make it harder for students to absorb information.
    - A concept contains 5 or more facts. In this case, request splitting the concept into two smaller, easier-to-understand concepts.
  - Suggestions:
    - If any violations are found, request necessary updates are made to section titles, concept names, and descriptions as part of the rearrangement.
"""
    },
    "TEACHING TECHNIQUES": {
        "description": "selects appropriate teaching techniques and visual formats to enhance student understanding of historical concepts",
        "guidelines": """
## Content-Restricted References. 
Teaching technique suggestions must not reference any material beyond what is being covered in the concept.
  - Self-Contained Suggestions: All teaching technique recommendations must only reference facts or terms that appear within the concept being taught.
    - Example of Compliance: For a concept on "Mongol conquest strategies," suggesting "Use a Sameness and Difference to highlight differences between steppe nomadic tactics and traditional Chinese military approaches" when both are mentioned in the concept's facts. However if Chinese Military approaches are not mentioned in the facts or relationships, the comparison would be inapproprate.
  - Suggestions may include additional details if they expand on existing information and remain within the original scope of the facts. They should not introduce new, unrelated terms or ideas that go beyond the scope.
    - Example: For a fact on "Mandate of Heaven," the suggestion "Highlight the cyclical nature of the Mandate of Heaven, emphasizing it can be lost through poor governance" is acceptable, even if "cyclical nature" isn't explicitly mentioned in the original facts. However, contrasting it with the "European divine right" concept would be unacceptable, as it introduces unrelated information beyond the intended scope.
  - Exceptions:
    - References to non-historical material are allowed if used only to help explain a concept, provided they do not introduce external domain knowledge.
    - The contextualization technique may introduce some external information, but only if this information is essential background knowledge that helps clarify the concept rather than raising additional questions.
  - If violations occur, suggest revisions that limit references strictly to the concept's content.

- Usage of Teaching Techniques:
  - Contextualization Technique. 
    - Use this technique only at critical points, where the concept and its underlying facts lack essential background information needed to contextualize and support upcoming learning.
    - If the current or previous concepts already provide the necessary background context, this technique becomes unnecessary. In such cases, request a different technique that better fits the concept's characteristics.
  - Setup Principle
    - This technique aims to simplify or clarify complex concepts using familiar examples or analogies. However, it can sometimes lead to unclear or ineffective examples.
    - Check that the requested example or analogy is relatable and clearly illustrates the particular term/process/other. If you can think of a better analogy or example—one that high school students would find more relatable and easier to understand—suggest it. Ideally, brainstorm and propose 2-3 alternative examples or analogies.
  - Sameness and Difference:
    - Make sure the terms selected for this technique are genuinely difficult to understand from a simple definition alone, and have nuances that the technique can help clarify. If the terms are straightforward and easy to grasp, recommend removing the technique.
"""
    }
}

VIDEOPLAN_FIXER_USER_PROMPT = """There were some issues identified with the generated plan. Please revise the evaluation below and adjust the plan accordingly. Make only the minimal edits necessary, while continuing to follow the original guidelines. Maintain the same language and format.

<evaluation>
{finder}
</evaluation>"""

content_guidelines = {
  "Transcript": {
      "name": "transcript segment",
      "context": "The transcript follows a podcast-like structure where a host interacts with reanimated historic figures to explain concepts to children.",
      "guidelines": transcript_content_guidelines,
      "fixer": QC_FIXER_USER_PROMPT
  },
  "MCQs": {
      "name": "MCQs",
      "context": "You will be assessing multiple-choice questions (MCQs) that test a student's grasp of a particular history concept they've recently learned from a video. You will be given the video's transcript for reference. Also, ",
      "guidelines": mcq_guidelines,
      "fixer": MCQ_FIXER_USER_PROMPT
  },
    "VideoPlan": {
      "name": "video plan",
      "context": "The video plan converts the raw syllabus requirements into a structured lesson plan. It defines the order and grouping of syllabus content, as well as the teaching methods and visual aids to use when explaining concepts. This helps optimize student learning.",
      "guidelines": videoplan_guidelines,
      "fixer": VIDEOPLAN_FIXER_USER_PROMPT
  }         
}
