IMAGES_QC_SYSTEM_PROMPT = """User
As a Quality Checker, your role is to evaluate the images provided based on the criteria set in the description. You will be assessing whether the image meets the 'must', 'should', and 'must_not' conditions specified. 

What to do:

- Carefully examine the image provided.
- Determine whether the 'must' condition is met. This is a non-negotiable aspect of the image. If it is not met, the image is not suitable.
- Evaluate whether the 'should' conditions are met. These are not mandatory, but they enhance the quality and relevance of the image.
- Ensure that none of the 'must_not' conditions are present in the image. These are elements that should definitely not be in the image.

Output Format:
```json
{
  "Evaluation": {
    "must": {
      "condition": "<original must condition>", 
      "met": <true or false>, 
      "justify": <justify choice of true or false>
    }, 
    "should": [
      {
        "condition": "<original shouldcondition>", 
        "met": <true or false>, 
        "justify": <justify choice of true or false>
      }, 
      ...
    ], 
    "must_not": [
      {
        "condition": "<original must  not condition>", 
        "met": <true or false>, 
        "justify": <justify choice of true or false>
      }, 
      ...
    ]
  }
}
```
"""

IMAGES_QC_USER_PROMPT = """Evaluate the image against the conditions below:

```Conditions
{conditions}
"""


def get_subject_agnostic_prompt(prompt, kwargs):
    placeholders = subject_specifications[[
        k for k in subject_specifications.keys() if k in kwargs['subject'].lower()][0]]
    return prompt.format(**kwargs, **placeholders)


IMAGES_QC_SYSTEM_PROMPT2 = """As a Quality Checker, your role is to evaluate a set of images provided based on the criteria set in the description. You will be comparing multiple images at once and determining which one best meets the 'must', 'should', and 'must_not' conditions specified. Keep in mind, these images are intended for use in {grade} {subject} textbooks, so accuracy, particularly in terms of {accuracy} in question, is paramount. {case_specifics}

What to do:

- Carefully examine each image provided.
- Determine which image best meets the 'must' condition. This is a non-negotiable aspect of the image. If it is not met, the image is not suitable.
- Evaluate which image best meets the 'should' conditions. These are not mandatory, but they enhance the quality and relevance of the image.
- Ensure that the 'must_not' conditions are least present in the chosen image. These are elements that should definitely not be in the image.
- {instructions}
- Compare the images and decide which one best meets all the conditions.
- Do not make a decision without comparing all the images.

Also return a confidence score as a integer 1-5. Criteria for scores: 1,3 5 are provided fill in the gap for 2,4. Note for best image a score range of 1-2 => search for new images; 3 => calls for more detail examination of best image; 4-5 => accepts image to be used in the book.
1 - The best image does not meet the 'must' condition or violates geographic/temporal accuracy. 
3 - The best image meets the 'must' condition and is generally accurate. Some 'should' and 'must_not' conditions are met.
5 - The best image meets all conditions and is highly accurate. It is highly suitable for a {subject} textbook.

You always respond in the format below, even if all images are inappropriate:
```json
{{
  "Best Image": "<Image number e.g. Image 3>",
  "Justification": "<why is the best image in terms of the must, should and must nots. what are the tradeoffs compared to other images>? What makes it the most accurate representation of {accuracy}?",
  "Confidence": <1-5>
}}
```

Conditions to meet:
```json
{conditions}
```
"""

ABSOLUTE_IMAGE_EVAL_PROMPT = """As a Quality Checker, your role is to evaluate a single image based on the criteria provided in the description.

Here's your process:
- Carefully examine the given image. Compare it with the specified conditions.
- For each condition, describe how the image either meets or fails to meet it. Provide a rationale for your assessment.
- Your evaluation should follow this structure:
  1) Reflection. Consider the condition and its implications. Reflect on the elements of the image that are directly and indirectly relevant.
  2) Assessment. Determine if the condition is met. Be critical in your evaluation.
  3) Justification. Explain why you have concluded that the image has either passed or failed.
  4) Suggestion. If the condition is not met, propose a solution based on your visual analysis of the image's compliance with the criteria.

Additional Instructions
- Be specific in your evaluation and language. Avoid generic terms like "good", instead, specify exactly what is good or bad. Refer to specific elements in the image.
- Be careful when connecting the condition to the image, ensuring you make only accurate associations and conclusions.
- Evaluate each condition separately, without combining them.
- Do not request additional evidence to evaluate compliance with any condition. If the current contents are insufficient to evaluate compliance, assume the condition is met. 
- If you're unsure whether a condition has been met, assume it has and mark it as PASS.
- Examples of Suggestions: If a legend interferes with diagram objects, you might suggest, 'There seems to be some space on the bottom right of the diagram, consider positioning the legend there.
- Do not attempt any quantitative evaluation. If a condition requires a specific quantitative evaluation, assume the condition is met.
- Be specific. Clearly state the exact items or reasons that caused the image to fail, making detailed references to elements within the image.

Always respond in a Markdown format:
--------------
### Evaluation
#### Condition 1:
<Provide a detailed Reflection, Assessment, Justification, and Suggestion on Compliance with condition 1>
#### Condition 2:

### Synthesis
<Summarize your detailed evaluation into a concise JSON detailing the reason for PASS or FAIL of each condition, and the fix Suggestion in case of failure.>
```json
{
  "<condition definition>": {
      "evaluation": "<Justification (+ Suggestion)>",
      "status": "PASS || FAIL"
  },
  ....
}
```
--------------
"""

ABSOLUTE_IMAGE_ENHANCER_PROMPT = """As a Description Enhancer, your role is to take a single-line description and expand it into a detailed query with lists of 'must', 'should', and 'must_not' conditions. These enhanced descriptions are intended for use in {subject} textbooks, so accuracy, particularly in terms of {accuracy} in question, is paramount. The enhanced description will be used to guide the search and selection of suitable images for the textbook.

What to do:

- Thoroughly review the single-line description provided.
- Develop a list of specific 'must' conditions that directly stem from and enhance the original description. These are essential image criteria; if any are not met, the image will be rejected.
- Based on the description, infer a list of 'should' conditions that the final image ideally should meet. These are not mandatory, but they improve the quality and relevance of the image.
- 'Must' conditions concern data, textual and visual contents, and relationships between elements. Formatting details like colors, sizes, opacity, weight, etc., should be specified as part of 'should' conditions as these are non-critical elements that do not compromise the relevance and accuracy of the diagram.
- Identify a list of 'must_not' conditions based on potential misinterpretations or undesirable elements inferred from the description. If something is already specified in the 'must' condition, avoid duplicating it by negating and placing it as 'must_not'.
- Ensure each specified condition is concise, similar to a Google search query.
- {instructions}

Output Format:
```json
{{
  "must": ["<list of 2-3 non-negotiable aspects of the image>"],
  "should": ["<list of 2-3 conditions that enhance the quality and relevance of the image>"],
  "must_not": ["<list of 2-3 elements that should not be in the image>"]
}}
```"""

subject_specifications = {
    "history": {
        "accuracy": "the time period and region",
        "instructions": "Pay special attention to the accuracy of the time period and region in the images. As these images are for history textbooks, they must accurately represent the historical context.\n- Do not approve an image if it does not accurately represent the time period and region.",
        "must": "the period or region involved to ensure geographic and temporal accuracy"
    },
    "math": {
        "accuracy": "mathematical concepts and problem-solving methods",
        "instructions": "Ensure that the mathematical concepts and problem-solving methods are depicted clearly and accurately. Images should directly display the concept in question and enhance understanding.\n- Reject any image that misrepresents or inaccurately depicts the mathematical concepts.",
        "must": "mathematical concepts, specific equations, and numerals involved to ensure conceptual accuracy"
    },
    "math diagrams": {
        "accuracy": "geometric shapes, diagrams, tabular data, and graph representations",
        "instructions": "Ensure that the diagrams, graphs, tables, and geometric shapes are depicted clearly and accurately. Diagrams should directly represent the mathematical concept or data accurately and enhance comprehension.\n- Reject any diagram that misrepresents or inaccurately depicts the relationships or data.\nThe must conditions must be with respect to the expected final image of the diagram. No conditions requesting any animations or dynamic action should be made. So if the description involves an animation think about what would need to be in the final frame.",
        "must": "correct labeling, accurate scale and proportions, and clarity in the representation of data or relationships"
    }
}


IMAGES_QC_ENHANCE_DESRIPTION = """As a Description Enhancer, your role is to take a single-line description and expand it into a detailed query with 'must', 'should', and 'must_not' conditions. These enhanced descriptions are intended for use in {subject} textbooks, so accuracy, particularly in terms of {accuracy} in question, is paramount. The enhanced description will be used to guide the search and selection of suitable images for the textbook.

What to do:

- Carefully examine the single-line description provided.
- Define a specific 'must' condition, the definition should highly overlap and enhance the original description. This is a non-negotiable image criteria, if its not met the image will be disposed.
- Use the description to infer a list of 'should' and 'must_not' conditions that the final image should ideally meet. These are not mandatory conditions, but they enhance the quality and relevance of the image.
- Depending on the emphasis placed in the description, the must clause may need to have mention of the {must}.
- Each specified condition must be concise, like a google search query

Output Format:
```json
{{
  "must": "<non-negotiable aspect of the image>",
  "should": ["<list of 2-3 conditions that enhance the quality and relevance of the image>"],
  "must_not": ["<list of 2-3 elements that should not be in the image>"]
}}
```"""

google_examples = [
    {"role": "user", "content": "Map of Medieval Europe"},
    {"role": "assistant", "content": "```json\n{\n  \"must\": \"Map of Europe during the Medieval period\",\n  \"should\": [\"Include major kingdoms and empires of the period\", \"Show geographical boundaries\", \"Include labels in English\", \"Be a close-up view of the European region\"],\n  \"must_not\": [\"Include modern political boundaries\", \"Be a map of another geographical region\", \"Show a global or generic world map\"]\n}\n```"},
    {"role": "user", "content": "Map of Medieval Europe"},
    {"role": "assistant", "content": "```json\n{\n  \"must\": \"Authentic Chinese compass from the 1300s\",\n  \"should\": [\"Show close-up of compass details\", \"Include Chinese characters or symbols\"],\n  \"must_not\": [\"Show modern or western-style compasses\", \"Include unrelated objects or artifacts\", \"Depict a compass from a different time period\", \"Show inaccurate replicas\"]\n}\n```"}
]


case_specifications = {
    "ai": {
        "main_prompt": "Specifically, you will be evaluating AI-generated images. While these images may not be authentic historical artifacts, they should serve to enhance the reader's immersion into the historical narrative and accurately depict the situations being discussed.",
        "examples": google_examples,
        "update_description_prompt": "",
        "final_query_prompt": ""
    },
    "web": {
        "main_prompt": "",
        "examples": google_examples,
        "update_description_prompt": """- Take advantage of google's advanced query features. For instance
  - Use ( -"remove phrase" ) with quotes to remove a phrase from returned results
  - Use ( "return exact phrase" ) with quotes to make sure returned results contain this exact phrase.""",
        "final_query_prompt": "Your final search should only include essential keywords. Be smart and selective with your word choice. For example, instead of saying `Napoleon battling on a field with guns and swords`, simply say `Napoleon battling`. The field, guns, and swords are already implicitly understood."
    },
    "svg": {
        "main_prompt": "",
        "examples": [],
        "update_description_prompt": "",
        "final_query_prompt": ""
    },
    "mermaid": {
        "main_prompt": "",
        "examples": [],
        "update_description_prompt": "",
        "final_query_prompt": ""
    },
    "Manim.py Plot": {
        "main_prompt": "",
        "examples": [],
        "update_description_prompt": "",
        "final_query_prompt": ""
    }
}


UPDATE_DESCRIPTION_PROMPTS = [
    """As an expert in crafting google queries to find the best matches you assist the user in perfecting their google search queries to find the best results. The user is searching for an image, but so far has not been successful. The user will present both the original query used as well as an evaluation of the results retrieved with that query. You will to thoroughly analyze the evaluation to pinpoint the shortcoming of the query and redesign.

Bear in mind the following:
- Queries are best when their concise but specific, so more description does not yield better results however being succinct does.
{case_specific_practices}
""",
    """First, let's identify the issues with the image description "{description}", based on the evaluation of the resulting images. Before redesigning the query, we need to pinpoint the common problem and its potential source in the query. Please respond with a list of problems, along with a mention of the potential source.

```Evaluation
{evaluation}
```
""",
    """Now, based on your analysis of the problems, you can modify the query. {description}

Output format:
```json
{{
"query": <new_query>
}}
```
"""
]

MULTIQUERY_PROMPT = """You are an AI language model assistant. Your task is to generate {n} different versions of the given user search query to generate relevant images using AI. By generating multiple perspectives on the user question, your goal is to help the user overcome some of the limitations of the distance-based similarity search.  Provide these alternative search queries separated by newlines.

Original question: {query}"""


MANIM_DIAGRAM_QUALITY_CRITERIA_PROMPT = """As a Quality Assessor for generated diagrams, your task is to create a list of conditions that define the quality standards for the diagram, based on the original description. These conditions should evaluate how well the diagram meets the initial instructions and its overall quality. The conditions are designed to assess diagrams created for {subject} textbooks, so accuracy, especially in terms of {accuracy}, is crucial. The conditions will guide the iterative improvement of the diagram. 

### Instructions:
- Carefully review the single-line description provided.
- Create a list of specific conditions that directly relate to and improve the original description. These are critical diagram criteria; if any are not met, the diagram will be rejected.
- Based on the description, deduce a list of 'should' conditions that the final diagram ideally should meet. These are not explicitly requested conditions, but should be met to achieve a high-quality and relevant diagram.
- 'Must' conditions relate to data, textual and visual contents, and relationships between elements. Formatting details like colors, sizes, opacity, weight, etc., should be specified as part of 'should' conditions as these are non-critical elements that do not compromise the relevance and accuracy of the diagram.
- Ensure each specified condition is concise and sets a specific quality standard to be achieved.
- Here are some example conditions that may apply to any given instruction and the resulting generated diagram:
  - Specific conditions assessing accurate and clear representation of mathematical concepts and problem-solving methods. The image should directly display the concept in question and enhance understanding.
  - If the instruction requested the addition of certain text directly or indirectly, ensure the text is legible.
- Every generated criterion must be specific to the instruction at hand. It can't be generic statements like 'Diagram should be accurate.' Instead, it should define the specific criteria under which the diagram is accurate. This applies to every generated condition.
- Avoid nitpicking when generating conditions. Each quality criterion should establish a valid standard which, if not met, would mean the instruction has not been fulfilled or the generated diagram is not presentable.
- **Mandatory Requirements** - These are criteria that apply universally to any diagram generation step and must be strictly enforced.
  - Any object created and added to the scene should be: 
    - 1) Clearly visible
    - 2) Non-interfering with other objects, but rather enhancing them. For example, if a label is added for a point, there should be a condition ensuring that the label doesn't overlap the point but appears in its immediate vicinity.
  - If a new object added to the scene is directly related to an existing object, the formatting (e.g., color) of the new object should match that of the existing one. When defining the criteria, mention both the new object(s) and their related counterparts.

### Constraints:
- You are creating specific criteria to assess quality and compliance with respect to one instruction. The entire diagram is generated in multiple steps. When generating criteria, ensure they don't concern elements that should appear later but assess the diagram as expected in the current step. The user will provide the current diagram instruction along with the resulting diagram, and the context of all diagram generation steps. Be mindful of the other steps to avoid irrelevant or premature criteria that will unnecessarily fail the generated diagram.

Output Format:
```json
{{
  "must": ["<list of 3-6 non-negotiable aspects of the image>"],
  "should": ["<list of 3-7 conditions that enhance the quality of the image>"]
}}
```"""

MANIM_DIAGRAM_QUALITY_CRITERIA_USER_PROMPT = """Here is the complete plan for the diagram generation:
{plan}

The latest instruction is: {step}.

Remember, don't get ahead of yourself with the conditions. Create conditions that evaluate the diagram as it should appear in the current step, without considering elements that will be added later. Concentrate on what the diagram should ideally look like at its current stage of development.

"""

MANIM_DIAGRAM_FIXER_REQUEST = """Synthesize the Quality Assessor's review into a single, comprehensive qualitative evaluation of the problems identified in the diagram.

### Instructions
- Use precise and concise language. Avoid unnecessary words.
- Describe the issues in the diagram with a specific visual account, providing a qualitative, not quantitative, assessment.
- Analyze with respect to formatting, arrangement, locations, readability, presence of elements, their relative formatting, etc. 
- For each failed condition, mention what is observed on the screen and what should ideally be there.
- If the original quality assessor's evaluation included a suggestion on how to fix the issue or any relevant information that could help in addressing it, mention it gently in a suggestive, not demanding, manner. 

### Response structure:
Respond in markdown following the structure below:
 1. Analysis. Examine the conditions that the diagram was assessed on and the reasons for failure as listed in the evaluation. 
 2. Synthesis. Provide a single qualitative assessment of the issues in the diagram. Your assessment should be specific, mentioning specific objects and the specific problem with each. Do not add text under the list of issues.
```
### Analysis
<Analysis of the diagram evaluation: the conditions and the reasons for failure>

### Synthesis
<A specific account of the issues in the diagram>
```

### Example of synthesis:
``` Example 1
### Synthesis
Please adjust the diagram to resolve the following issues:
1) The diagram's background is white, which could benefit from a light gray color for better contrast.
2) The text annotation on the red point is barely visible. Increasing the font size would improve legibility.
3) The axes tick labels overlap with the ticks, making the numbers hard to read. A slight increase in the gap between the tick and the number could resolve this issue.
```
```Example 2
### Synthesis
Please adjust the diagram to resolve the following issue: The Y-axis label is partially out of frame. This could be fixed by moving the label to the top of the axis and rotating it to be horizontally aligned instead of vertical.
```
```Example 3
### Synthesis
Please adjust the diagram to resolve the following issues:
1) The diagram uses blue squares to mark data points, but red dots would be more appropriate.
2) The diagram's legend overlaps with the data points, obscuring them. This reduces the visibility of the points and the legibility of the legend. Moving the legend to the top right of the diagram, where there is space, could solve this issue.
```"""