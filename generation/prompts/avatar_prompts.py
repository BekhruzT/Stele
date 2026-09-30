SPEAKER_IDENTIFIER_PROMPT = """Given the speaker '{speaker}' and the following list of potential matches:
<candidate_matches>
{candidate_matches}
</candidate_matches>

Please select the most appropriate match for the speaker. If none are suitable, respond with 'None'. Return the result in JSON format with keys 'match_found' (boolean) and 'matching_candidate' (string that is exactly same as the supplied name in the candidate_matches). For example:
{{
"match_found": true,
"matching_candidate": "julius_caesar"
}}
or
{{
"match_found": false,
"matching_candidate": null
}}
Return only the json and nothing else."""


AVATAR_INTRODUCTION_PROMPT = """You are tasked with creating captivating one-liners for significant personas based on a given transcript. Your goal is to introduce each significant persona succinctly and memorably, focusing on key details from the transcript while maintaining similarity to the introducing phrase.

Here is the transcript:
<transcript>
{transcript}
</transcript>

Here is the phrases used to introduce each {figure} into the video:
<introducing_phrases>
{introducing_phrases}
</introducing_phrases>

Your task is to create a one-liner for each {figure} that introduces them based on key details from the transcript and maintains similarity to the introducing phrase. Follow these guidelines:

1. Make the one-liner succinct, up to 7 words.
2. The one-liner should be catchy, exciting the listener and being memorable. It should sound fluid and a little poetic.
3. Use maximally simple but memorable language.
4. Base the one-liner on the {figure}'s depiction in the transcript, not on general knowledge or their most renowned traits.
5. Ensure that the final one-liner has similar description and word choice as the introducing phrase.
6. About the language of a one-liner:
   - Choose words that are powerful and impactful.
   - If appropriate, make it clever or humorous.
   - Consider the knowledge and interests of students to maximize relevance and impact.
   - Use as few words as possible.
   - Ensure the message is easily understood.
   - Choose words that are simple and widely known, avoid unnecessary complexity.
   - The one-liner for each historical figure should mirror the description and wording used in their introduction as defined in <introducing_phrases>. Ensure your one-liner aligns with the figure's introduction in the transcript to maintain consistency between the written and verbal introductions.
   - Your introduction and the transcript introduction must be an almost word for word match. This requirement superceded all requirements about it being powerful, humourous and so on. Ensure your one liner resembles the transcript introduction

Here are some examples for reference:
1. Benjamin Franklin - Founding Father and electrical science pioneer
2. Genghis Khan - Renowned conqueror of Eurasia and guardian of the Silk Road
3. Marie Antoinette - Prominent patron of the arts
4. Cleopatra - Egyptian queen and skilled diplomat
5. Nero - Supporter of the Olympic Games

For each {figure} on the list, after going through the necessary reasoning, create a final one-liner following the guidelines and examples provided above. Present your results in the following format:
<introductions>
{{
    "<persona_name>": "<Your one-liner introduction>" 
}}
</introductions>

Ensure that each one-liner accurately reflects the character's portrayal in the transcript while being engaging and memorable. 
NOTE: The one-liner should is not supposed be a snippet from the transcript, but rather like the examples provided above.
"""


GENERATE_AVATER_IMAGE_PROMPT = """You are tasked with generating a prompt for a flux image generation model. This prompt will be used to create an avatar of a {figure} who will appear as a speaker in an educational {field} video. Follow these guidelines to create an effective and detailed prompt:

1. Use the provided {figure}, time period, and historical context to inform your description.

2. The image should be a close-up, capturing the upper body of the character (chest and up), with the avatar facing the front (front profile).

3. Describe what the avatar should be wearing, ensuring it is appropriate for the time period, historical context, and social status of the {figure}.

4. Include details about the character's gender, age, facial features, hairstyle, and any notable accessories or adornments.

5. Suggest a subtle blurred background that hints at the appropriate indoor setting without distracting from the main figure.

- Based on the figure description provided by the user, craft a detailed prompt for the image generation model. 
- Begin by acknowledging the {figure} and their notable achievements, then move on to the prompt. 
- Avoid mentioning the figure's accomplishments or the topic title within the prompt itself.
- Keep the prompt succinct 3-4 sentences maximum.
- Request only photorealistic portraits; cartoon-style or stylized depictions of {figure}s needs to be avoided.
- The background should be straightforward, subtly suggesting a characteristic to {figure}s indoor setting. It's important to specify that the background should be devoid of people.

Present your final prompt within <prompt> tags. Ensure that your description is historically accurate, visually compelling, and suitable for an educational context.

Some examples:
<prompt>
Generate a photorealistic image of Cleopatra, in here prime, as a speaker in an educational history video. The image should capture her from the front, focusing on her upper body. Cleopatra is dressed in an elaborate ancient Egyptian royal attire, complete with a golden diadem, intricate jewelry, and a finely embroidered linen gown. Her makeup emphasizes the traditional kohl-lined eyes and a subtle red lip, reflecting her iconic status. The background should be a soft, out-of-focus depiction of her palace interior to enhance her prominence as the central figure.
</prompt>

<prompt>
Generate a photorealistic image of Jennifer Doudna as a speaker in an educational biology video. The image should capture her from the front, focusing on her upper body. Doudna is in her middle ages, dressed in smart, modern academic attire, typically a neat blazer over a blouse. Her hairstyle is simple and professional, and her expression is thoughtful, reflecting her status as a pioneering scientist in CRISPR technology. The background should be a soft, out-of-focus depiction of a modern laboratory, subtly hinting at her research environment.
</prompt>"""

GENERATE_AVATER_IMAGE_USER_PROMPT = """Compose a prompt for {figure_name}, who will be portrayed as a {figure} in the topic of '{topic}', relevant to the {focus_area} of {unit}."""

MATCH_SIGNIFICANT_FIGURE_VOICE_PROMPT = """You are tasked with finding the best matching voice for a given {figure} from a dictionary of voice descriptions. Follow these steps carefully:

Here is a dictionary of voices with their respective descriptions:
<voice_dictionary>
{voices}
</voice_dictionary>

3. Analyze the {figure}'s characteristics based on the provided information and infer important descriptors, that will help in identifying the most suitable voice:
   - Estimated age
   - Gender
   - Personality traits
   - Speaking style (if known)

4. Compare these characteristics to the voice descriptions in the dictionary. Look for matches in:
   - Age
   - Gender
   - Pitch
   - Speaking style

5. Choose the voice that best matches the {figure}'s characteristics. If there isn't a perfect match, select the closest option.

6. Provide your answer in the following format:
   <best_match>
   <thoughts>
   Your evaluation of the {figure}'s characteristics and assessment again the voice descriptions.
   </thoughts>
   <voice_id>Insert the ID of the best matching voice here</voice_id>
   </best_match>

Remember to consider all aspects of the {figure} and voice descriptions when making your decision. If you're unsure between two options, explain the pros and cons of each before making your final choice."""

MATCH_SIGNIFICANT_FIGURE_VOICE_USER_PROMPT = "Figure: {figure_name}\nTopic: {unit} - {topic}.\nPortrait Description: {image_prompt}"

NO_PORTRAIT_DESCRIPTION = "No image description found, please infer an appropriate voice based on the significant figure's name."

AVATAR_INTRODUCTION_USER_PROMPT = "Here is the list of signficant personas:\n<personas>\n{personas}\n</personas>"

AVATAR_INTRODUCTION_TRIGGER_WORD_USER_PROMPT = "<phrases>\n{phrases}\n</phrases>"


AVATAR_INTRODUCTION_TRIGGER_WORD_PROMPT = """You are tasked with identifying the exact phrase and corresponding trigger word for the introduction of a specific character in a given text. Your goal is to pinpoint where the character is first mentioned and determine the precise word that should cue the character's appearance.

To complete this task, follow these steps:

1. Carefully read through the provided phrases and locate the exact phrase where the specified figure is first introduced or mentioned.
2. Within that phrase, identify the trigger word. The trigger word should be:
   - The exact word that introduces or first mentions the figure
   - Preferably a noun or proper noun
   - Not a generic verb or article

Additional guidelines:
- Examples:
   - In the phrase, 'Let's welcome Alexander the Great, a famous military strategist and leader who transformed the world in the 4th century BC.', the trigger word is Alexander.
   - In the phrase, 'Let's welcome the final Emperor of Russia, named after Saint Nicholas - Nicholas II.', the trigger word is Emperor.
- The introduction phrase should be the complete sentence or clause where the figure is first mentioned.
- The trigger word must appear in the introduction phrase.
- If the figure name consists of multiple words, the trigger word should be the first word of the name, unless a more specific or unique word would be more appropriate.
- In case the figure is referred to by a pronoun or title before being named, use the phrase where the full name is first mentioned.
- Use the template provided below, maintaining the same format and copying it exactly, but with the end times filled in as appropriate. Enclose in <matches> tags.

<matches>
```json
{template}
```
</matches>"""