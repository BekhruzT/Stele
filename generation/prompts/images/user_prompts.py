


GENERATE_MERMAID_CODE_USER_PROMPT = '''Audience - {audience}
ImageDescription - {image_description}'''

GENERATE_SVG_CODE_USER_PROMPT = '''Audience - {audience}
ImageDescription - {image_description}'''


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
