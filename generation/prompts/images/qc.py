from prompts.images.system_prompts import get_subject_agnostic_prompt  # noqa: F401


IMAGES_QC_SYSTEM_PROMPT2 = """As a Quality Checker, your role is to evaluate a set of images provided based on the criteria set in the description. You will be comparing multiple images at once and determining which one best meets the 'must', 'should', and 'must_not' conditions specified. Keep in mind, these images are intended for {subject} videos for a {audience}, so accuracy, particularly in terms of {accuracy} in question, is paramount. {case_specifics}

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

IMAGE_VISIBLE_PROMPT = "Is image visible? Return yes or no"

ABSOLUTE_IMAGE_EVAL_USER_PROMPT = "Evaluate this Image. Make sure to dedicate a sentence per: Analysis, Assessment, and Justification for every condition. Evaluation should necessarily include 3 sentences per condition. Be verbose but specific. Conditions to meet: \n```\n{conditions}\n```"

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


