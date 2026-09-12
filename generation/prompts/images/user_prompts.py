FACTS_EXTRACTION_USER_PROMPT = '''Educational material - 
{teaching_content}
'''

FACTCHECK_PROMPT = '''
Teaching Content - 
{teaching_content}
Is this Teaching Content CORRECT, INCORRECT or NOT SURE. Give the output in this format: {{\"Verdict\": \"\", \"Reason\": \"\"}}
'''

IMAGE_DESCRIPTION_TUNE_USER_PROMPT = '''Grade - {grade}
StandardID - {standard_id}
ImageDescription - {image_description}'''


RECTIFY_FACTUAL_CONTENT_USER_PROMPT = '''Teaching Content - 
{teaching_content}

Expert Review - 
{expert_review}
'''

CLASSIFY_IMAGE_DESCRIPTION_TUNE_USER_PROMPT = '''Grade - {grade}
StandardID - {standard_id}
ImageDescription - {image_description}'''

GENERATE_MERMAID_CODE_USER_PROMPT = '''Grade - {grade}
StandardID - {standard_id}
ImageDescription - {image_description}'''

GENERATE_SVG_CODE_USER_PROMPT = '''Grade - {grade}
StandardID - {standard_id}
ImageDescription - {image_description}'''

FETCH_DESCRIPTION_TUNE_USER_PROMPT = '''Image_alt - {alt}
Content - {content}'''

TUNE_USER_PROMPT = '''
Input Text:

{text}'''

SECTION_ORDERING_USER_PROMPT = '''
I am writing a study guide book on AP world history. The content is organized into different units and chapters.
The unit is defined by a period which would be 1200-1450, 1450-1750, 1750-1900, 1900-Present.
Within a unit, we have different chapters and they would be based on theme which would be Governance, Economics Systems, Social Interactions and Organization, Cultural Developments and Interactions, Technology and Innovation, Humans and the Environments.
Within a chapter, we have different sections.
I want to order the sections, for a given chapter, in a way that is easy to follow and enhances the narrative and
 ensuring that it meets the each section objectives to the fullest.
 
You can follow below steps to order the sections:
Step 1: Infer the content of each section for an AP World history study guide based on information provided about the sections.
Step 2: Think about the rationale behind the ordering which explains why is this sequence easy to follow and enhances the narrative.
Step 3: For each section determine notes, if any required, that section writer should be aware of when writing the content for the section while following your sequence. 
The notes should be related only on how to connect the content of the section to the content of the previous and next sections.
If there are no notes required for a section, you can leave it blank.

Here is the unit title: {unit_title} 
Here is the chapter title: {chapter_title}
Here are the sections and their objectives: {sections_objectives}

Please provide the order of the sections in the json format.Ensure to return json only and nothing else.:
{{
    "rationale": "Rationale behind the ordering which explains why is this sequence easy to follow and enhances the narrative",
    "sequence": {{"section1": 1, "section2": 2, "section3": 3}},
    "connection_notes": {{"section1": "Notes for section 1", "section2": "Notes for section 2", "section3": "Notes for section 3"}}
}} 
'''

SUBSECTION_ORDERING_USER_PROMPT = '''
I am writing a study guide book on AP world history. The content is organized into different units and chapters.
The unit is defined by a period which would be 1200-1450, 1450-1750, 1750-1900, 1900-Present.
Within a unit, we have different chapters and they would be based on theme which would be Governance, Economics Systems, Social Interactions and Organization, Cultural Developments and Interactions, Technology and Innovation, Humans and the Environments.
Within a chapter, we have different sections. And within a section we have different subsections.

I want to order the subsections, for a given section, in a way that is easy to follow and enhances the narrative,
 ensuring that it meets the section objectives and each subsection objectives to the fullest.
 
ou can follow below steps to order the sections:
Step 1: Infer the content of each section for an AP World history study guide based on information provided about the subsections.
Step 2: Think about the rationale behind the ordering which explains why is this sequence easy to follow and enhances the narrative.
Step 3: For each subsection determine notes, if any required, that section writer should be aware of when writing the content for the subsection while following your sequence. 
The notes should be related only on how to connect the content of the subsection to the content of the previous and next subsections.
If there are no notes required for a section, you can leave it blank.
 
 Here is the unit title: {unit_title}
Here is the chapter title: {chapter_title}
 Here is the section title: {section_title}
 Here is the section objective: {section_objective}
 
 Here are the subsections and their objectives: {subsections_objectives}
 
Please provide the order of the subsections in the json format.Ensure to return json only and nothing else.:
{{
    "rationale": "Rationale behind the ordering which explains why is this sequence easy to follow and enhances the narrative",
    "sequence": {{"subsection1": 1, "subsection2": 2, "subsection3": 3}},
    "connection_notes": {{"subsection1": "Notes for subsection 1", "subsection2": "Notes for subsection 2", "subsection3": "Notes for subsection 3"}}
}}
 '''

SECTION_SUMMARY_USER_PROMPT = '''I need you to summarize the content plan for a section of the textbook consisting of below sub-sections.
The summary will be used to lookup and locate the sections for content of any topic covered within the section.
Since this is a history book, the topics could be various entities and other historical events or terms of significance or the topic could be a particular aspect of a historical event or entity.
Ensure that the summary contains all the key terms and concepts covered in the section and is concise and informative.
Kindly help generate a summary for the section which can be used to lookup and locate the sections for content of any topic covered within the section by an AI bot.
Try to keep the summary as condensed as possible without missing on any topics.
Here are the sub-sections:
{subsections}
'''

SINGLE_WORD_TOPICS_USER_PROMPT = '''
I am writing a study guide book on AP world history. The content is organized into different units and chapters.
Within a chapter, we have different sections. And within a section we have different subsections.

I have attached content plan for a subsection in a chapter of the textbook.
I want to lookup and locate content in other sections or chapters of the book that might also be speaking on some aspect of the topics covered in this subsection.
Since this is a history book, the topics could be various entities and other historical events or terms of significance or the topic could be a particular aspect of a historical event or entity.


Extract key single word topics from the content plan so that we can lookup related sections on the topics present in this subsection.
Maximum three topics selected based on their importance in this subsection.
You should output in json format as below
[
    "topic1",
    "topic2"
]

{content_plan}
'''

PLAN_PLOTLY_DIAGRAM_PROMPT = """Start by planning for the diagram: {description}

 Determine the following:
  - Type of diagram needed: table, line plot, histogram, scatter plot, pie chart, box plot, or any other type supported in `plotly`.
  - Value: Parse the diagram description to determine the variable titles and their corresponding values. Organize this data into a dictionary, with keys as the variable title and values as the value or a list of values.
  - Padded Data: If no additional data is needed, keep this as None. Otherwise, use your judgement to generate a logical set of values and extend the values list.
  - Labels: Specify any labels you want the diagram to include. The key is the label type and the value is the label text. For example, {{
    "x_label": "Time (s)", "y_label": "Revenue"}}.
  - Title: Specify the diagram title. Keep it succinct but informative. e.g. Revenue over time. 
"""

CODE_PLOTLY_DIAGRAM_PROMPT = """Now, let's move on to the second step: generating the diagram. The diagram is - {description}.

With your plan in place, it's time to write the code using `plotly`. Use the plan you created as a guide. Here's a basic structure to follow:

1. Import the `plotly` library.
2. Define your data. Use the dictionary you created during the planning stage. This will include your variable titles and their corresponding values, along with any additional values if necessary.
3. Define your layout. This includes labels and titles, which you organized during the planning stage.
4. Create the figure using the `plotly` function that corresponds to the type of diagram you're creating.

### Formatting
- Include logical and concise labels and titles.
- Minimize margins to 0, with exception of the top margin. If there is a title make sure the top margin is set to 35.
- If you are creating a table, you must dynamically adjust its height to avoid whitespaces. In `fig.update_layout` set `height=(len(rows) + 4)*20`.

Remember, do not execute `fig.show()` on the figure afterwards, just define the figure. 
Only output the code and in the following structure:
```python
{{code}}
```
"""

REMOVE_NSFW_CONCEPTS_USER_PROMPT = """Here is a prompt that was flagged as NSFW by an AI model. 

Prompt:
<original prompt>
{prompt}
</original prompt>

First jot down all the potential words/phrases that might be leading to the issue of NSFW.
Then remove all those parts from the prompt and return and updated prompt in <new_prompt></new_prompt> tags.
"""
