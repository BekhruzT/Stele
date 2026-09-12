import json
from typing import List

from core.stage_constants import \
    get_unit_from_chapter
from prompts.common_prompts import \
    get_subject_specific_clips_prompt_entries

DEFINE_TRANSCRIPT_CLIPS = """You are a video transcript analyzer. Your task is to analyze a given transcript, refine suggested splits, and for each segment, determine what should appear on the screen to complement the narration. The output should be structured in a specific JSON format.

Follow these steps to complete the task:

1. Review the suggested splits provided. These splits are intended to create segments of roughly equal length, but they may not always be at visually appropriate places in the text.

2. Analyze each suggested split and make minor adjustments if necessary. You may move words or phrases between adjacent segments to improve coherence, but be cautious:
   - For each segment the number of word allowed to add or remove will be indicated through the fields positive_tolerance and negative_tolerance, respectively.
   - Ensure that each adjusted segment forms a coherent idea or visual element.
   - Do not miss a single phrase from the original transcript.
   - The first and last split must be at least 7 words long, ideally this condition must be true for all splits.
   - Remember to convert the entire transcript from start to finish, word for word. If certain parts are difficult to visualize, suggest general visuals that fit the lesson's theme and complement the current visual story.

3. Based on your analysis, create a JSON object for each segment following this structure:
   {{
     "text": "The transcript segment",
     "media": {{
       "description": "<Vivid description of the media>"
     }}
   }}

4. When describing videos or images, provide a detailed and vivid description:
   - Please remember that the transcript is based on the {focus_area} - '{unit}' - and the topic - '{topic}'. {ssi_custom_clip_specifications}
   - Describe a single scene. If there are any actions involved or important details that will require emphasis, mention them.
   - Your description should be 3-4 sentences long, incorporating any relevant context from the surrounding transcript.
   - Be specific about visual elements that capture unique features of the era or setting.
   - Be concise and avoid romanticizing the description with excessive details.
   - Concentrate on one scene per segment. Avoid asking for a collage or montage of multiple scenes.
   - If there's a comparison or contrast between different scenes, highlight the more impactful and relevant scene prominently.
   - Avoid asking for significant changes in the scenes. The overall setting should remain consistent.
   - Refrain from requesting visuals that will likely require text. Any text in images should be avoided. Therefore, avoid asking for items like signs or open books. If you do request such elements, ensure you specify how to avoid including text, such as through symbols or illustrations.

5. Make sure the visual elements you choose accurately represent the content of each segment text and help the viewer understand the narration. To do this, consider each visual as part of a larger story. Each visual should:
  - Help the student visualize the current narration, as outlined in the segment text
  - Have unique content, different from all other scenes
  - Maintain a consistent style and atmosphere with all other scenes, as if they are part of a single movie clip filmed with the same camera, ideally reflecting similar themes and styles.

Your final output should be a JSON array containing all these objects. Place the array inside <segments></segments> tags. Ensure that your analysis is thorough, consistent, and enhances the viewer's understanding of the content.

Remember, you are to identify and refine the segments only within the provided transcript and suggested splits. Do not alter the overall content or meaning of the transcript in any way.
"""

DEFINE_CLIPS_USER_PROMPT = """{speaker_insert}
Here is the transcript you will be working with:

<transcript>
{transcript}
</transcript>

And here are the suggested splits for the transcript:
<suggested_splits>
{suggest_splits}
</suggested_splits>

- If there's only one brief proposed division, there's no need for additional analysis. Simply recommend a suitable media, despite the limited context, based on your understanding and lesson topic and period.
- Remember, your goal is to transform the present content into a visual story by incorporating unique imagery that are similar in theme and style. This will help illustrate the narrative and establish a visual storyline.
- Make sure your JSON response covers the entire transcript end to end. Any padded text (forming a partial sentence at the start or end of the transcript), must necessarily be included in the splits. 
"""

FIX_CLIPS_USER_PROMPT = """There were some issues with the validation of the generated segments. The primary areas of concern included:
1. Ensuring the extracted text exactly matches a substring from the transcript.
2. Making sure the length of the edge phrase meets the minimum duration requirement.

Below is the validation error JSON that captures all the failed splits, categorized by the type of validation error.
```
{validation_errors}
```

You need to adjust the segments JSON you created above to account for the errors that have occurred. 

For the Phrase Too Short Error:
 - Extend the phrase slightly by incorporating some text from the adjacent clip.
 - Update the media description to reflect the new text.

For the No Matching Phrase Error:
 - Rephrase the text to match exactly what is stated in the transcript. It must be a verbatim match.
 - Keep the rest of the JSON, including all other segments and the media fields, exactly the same.
 
Note, if you add any text snippet to a specific split, you must remove that exact text snippet from the neighboring split.

Ensure the splits cover the entire transcript from start to finish, word for word. For phrases that are difficult to visualize, provide general imagery that matches the lesson's theme and supports the visual narrative.
"""

def get_system_prompt_define_clips(context):
   unit = get_unit_from_chapter(context.subject, context.chapter)
   ssi = get_subject_specific_clips_prompt_entries(context.subject)
   return DEFINE_TRANSCRIPT_CLIPS.format(unit=unit, topic=context.subsection, **ssi)

def get_user_prompt_define_clips(transcript: str, suggested_splits: List[str], speaker:str, custom_instruction: str=""):
   speaker_insert = ""
   # if speaker and speaker.lower() != 'host':
   # speaker_insert = f"The following transcript is delivered by {speaker}. The video will show {speaker} presenting this part of the lesson, so make sure none of the images/videos you suggest include {speaker}. The suggested images and videos should accompany and enhance the message being conveyed, rather than re-presenting {speaker}."
   if speaker:
    speaker_insert = f"Please avoid proposing any images or videos that depict the following characters: {speaker}, particularly if they are mentioned in the provided transcript splits. If one of them is specifically referred to, you might consider illustrating the typical environment in which the character functions but not themselves."
   return DEFINE_CLIPS_USER_PROMPT.format(speaker_insert=speaker_insert, suggest_splits=json.dumps(suggested_splits, indent=2), transcript=transcript)+custom_instruction

IMAGE_GEN_SYSTEM_PROMPT = """You are an AI assistant tasked with creating an ideal image generation prompt based on a given scene description. Your goal is to craft a detailed and effective prompt that will result in a high-quality, visually striking image.

First, determine if the description is of a static scene or a video. If it describes a video, focus on the very first frame or scene. Filter out any video-specific elements and concentrate on what would ideally be visible in the initial image. Consider how upcoming scenes might influence the first frame, but remember that you're describing a single, static image.

For example, if the description is of a falling star video, your first scene would likely depict a night sky, possibly with a bright point of light just beginning to streak across it.

Now, consider these general guidelines that should be applied to all image prompts:
<general_guidelines>
1. **Be Specific and Detailed**. Include precise details such as setting, objects, colors, mood, and specific elements you want in the image.
2. **Use Descriptive Language**. Employ clear, visual descriptions and avoid abstract terms to help the AI better understand and generate the desired image.
3. **Define the Mood or Atmosphere**. Use mood descriptors like "serene," "chaotic," "mystical", etc. to set the emotional tone of the image.
4. **Specify Composition and Perspective**. Mention desired perspectives such as close-up, wide shot, or specific angles to frame the scene correctly.
5. **Detail Lighting and Time of Day**. Clarify lighting conditions (e.g., sunny, candlelight) and time of day to influence the image's mood and visibility.
6. **Describe Actions or Movements**. If dynamic imagery is desired, describe actions or movements to add energy to the scene.
7. **Avoid Overloading the Prompt**. Provide enough detail to guide the AI but avoid excessive specifics that could confuse the model.
8. **Use Commas to Separate Elements**. Clearly separate different elements of your prompt with commas to help the AI distinguish between them.
9. **Focus on Positive Descriptions**. Concentrate on what you want to include rather than what you want to exclude, unless using a platform that supports negative prompts effectively.
10. **Avoid splitscreen Images**. Ensure that the prompt is for a single image and not a split-screen or triptych or any other multi-image format.
11. **Avoid Text in Images**. Refrain from requesting visuals that will likely require text. Any text in images should be avoided. Therefore, avoid asking for items like signs or open books. If you do request such elements, ensure you specify how to avoid including text, such as through symbols or illustrations.
</general_guidelines>

Additionally, here are optional guidelines that should be used when appropriate:
<optional_guidelines>
1. **Incorporate Artistic Styles**. Always request a photorealistic image.
2. **Use Analogies or Comparisons**. Employ comparisons or analogies to familiar scenes or styles for clearer interpretation (e.g., "like Van Gogh's Starry Night").
3. **Employ Photographic Terminologies**. Use terms related to photography like "low angle," "backlighting," or "shallow depth of field" to specify visual details.
4. **Utilize Artistic References**. Reference specific artists or art movements to infuse their techniques or aesthetics into your image.
5. **Specify Environmental Context**. Include details about the environment or background to place the subject in a more defined space.
</optional_guidelines>

Additional Requirements: These requirements must be met regardless of the original scene description. You may need to make minimal necessary edits to the description to ensure compliance with the following guidelines:
- Focus on a single scene: avoid splitscreen or collage.
  - If the scene description suggests a splitscreen, ignore it. Concentrate on a single prominent scene. If you can merge the actions intended to be shown in each split into a single image description, that's great. If not, due to completely different settings or other reasons, that's also acceptable.
  - The goal is to create a coherent image that makes sense and doesn't overwhelm the student.
- Avoid requesting text and items like signs or open books. If text objects are the main subject of the scene, consider using symbols or illustrations to replace the textual elements and convey the intended message.
  - For example, if the scene description suggests showing a student studying from an open book, instead of showing the actual text in the book, you could illustrate the concept being studied. If the lesson is about photosynthesis, you could show a plant with sunlight and water being absorbed, and oxygen being released

Examples:
- See how these prompts focus on only the critical subject and avoid overloading the prompt with excessive details. You to should, avoid extravagance or overly vivid descriptions that are insignificant to the scene's message and purpose but add unnecessary complexity to the prompt.
- IMPORTANT: The prompt should be extremely succinct, 1-3 sentences maximum. This must be always followed, the prompt can't be too detailed and long otherwise it will produce terir
<examples>
{ssi_enhance_image_prompt_examples}
</examples>

Enclose your finalized prompt within <prompt>[YOUR PROMPT]</prompt> tags.
"""

IMAGE_GEN_USER_PROMPT = """### Further Instructions
 - Incorporate these guidelines into your prompt as appropriate. Be sure to use descriptive language that captures the mood, lighting, composition, and key elements of the scene. Include relevant artistic styles, camera angles, or other technical details that would enhance the image.
 - Craft your image prompt in a clear, succinct manner that will guide an image generation AI to create the most compelling Photo-Realistic visualization of the scene. Aim for a prompt that is detailed enough to capture the essence of the scene but not so complex that it becomes confusing.
 - Please provide your final image generation prompt within <prompt> tags. Your prompt should be a single, well-structured paragraph without any line breaks.
 - It's crucial that every requested element and its composition are accurate to {field}. The image will be used as part of a {field} lesson, so it's essential that the intended message is conveyed in the clearest and most accurate way possible.
{ssi_enhance_image_description}

<scene_description>
{description}
</scene_description>
"""

RUNWAY_VIDEO_PROMPT = """You are tasked with creating a video prompt based on a given image prompt. Your goal is to describe how the static image should be animated, including subtle movements, camera actions, and changes that maintain the original theme and atmosphere. Follow these instructions carefully:

1. First, you will be presented with an image prompt. Read it carefully to understand the scene, elements, and atmosphere described.

2. Next, you will be given a set of guidelines for creating the video prompt. Adhere to these guidelines strictly when crafting your response.

<guidelines>
Skip to main content
Go to Runway Get Help
Search
Search documentation, tutorials, tools, and tips
Runway  Creating with Runway  Gen-3 Alpha
Gen-3 Alpha Prompting Guide

Gen-3 Alpha has endless potential to bring your artistic vision to life for a wide variety of use cases. Creating a strong prompt that conveys the scene is the key to generating video aligned with your concept.

This article covers different example structures, keywords and prompting tips to help you get started with Gen-3 Alpha. These are just examples – don't be afraid to experiment when bringing your ideas to life.

 

Prompt Structures
Text-only Base Prompt
Text-only prompts are most effective when they follow a clear structure that divides details about the scene, subject and camera movement into separate sections.

Using the following structure should help provide consistent results while you're familiarizing yourself with Gen-3 Alpha:

[camera movement]: [establishing scene]. [additional details].
Using this structure, your prompt for a woman standing in a tropical rainforest might look like this:

Low angle static shot: The camera is angled up at a woman wearing all orange as she stands in a tropical rainforest with colorful flora. The dramatic sky is overcast and gray.
Repeating or reinforcing key ideas in different sections of your prompt can help increase adherence in the output. For example, you might note that the camera quickly flies through the scenes in a hyperspeed shot.

Try to keep your prompt focused on what should be in the scene. For example, you would prompt for a clear sky rather than a sky with no clouds.

 

Image + Text Base Prompt
When using input images, focus on describing the movement you'd like in the output, rather than the contents of the image.

In example, you might try the following prompt if using an input image that features a character:

Subject cheerfully poses, her hands forming a peace sign.
Using a text prompt that significantly differs from the input image may lead to unexpected results. Keep in mind that complex scene transitions may require multiple iterations to achieve the desired output.

 

Sample Prompts
Seamless Transitions
Continuous hyperspeed FPV footage: The camera seamlessly flies through a glacial canyon to a dreamy cloudscape.

 

Camera Movement
A glowing ocean at night time with bioluminescent creatures under water. The camera starts with a macro close-up of a glowing jellyfish and then expands to reveal the entire ocean lit up with various glowing colors under a starry sky. Camera Movement: Begin with a macro shot of the jellyfish, then gently pull back and up to showcase the glowing ocean.

 
Text Title Cards
A title screen with dynamic movement. The scene starts at a colorful paint-covered wall. Suddenly, black paint pours on the wall to form the word "Runway". The dripping paint is detailed and textured, centered, superb cinematic lighting.

 

Prompt Keywords
Keywords can be beneficial to achieve specific styles in your output. Ensuring that keywords are cohesive with your overall prompt will make them more apparent in your output.

In example, including keywords about skin texture wouldn't be beneficial to a wide angle shot where the camera is not closely focused on a face. A wide angle shot might instead benefit from additional details about the environment.

While keeping this cohesiveness in mind, below are different keywords you can experiment with while drafting your prompts.

 

Camera Styles
Keyword	Output
Low angle	
High angle	
Overhead	
FPV	
Hand held	
Wide angle	
Close up	
Macro cinematography	
Over the shoulder	
Tracking	
Establishing wide	
50mm lens	
SnorriCam	
Realistic documentary	
Camcorder	
 

Lighting Styles
Keyword	Output
Diffused lighting	
Silhouette	
Lens flare	
Back lit	
Side lit	
[color] gel lighting	
Venetian lighting	
 

Movement Speeds
Keyword	Output
Dynamic motion	
Slow motion	
Fast motion	
Timelapse	
 

Movement Types
Keyword	Output
Grows	
Emerges	
Explodes	
Ascends	
Undulates	
Warps	
Transforms	
Ripples	
Shatters	
Unfolds	
Vortex	
 

Style and Aesthetic
Keyword	Output
Moody	
Cinematic	
Iridescent	
Home video VHS	
Glitchcore	
 

Text Styles
Keyword	Output
Bold	
Graffiti	
Neon	
Varsity	
Embroidery	
 

Bracket Placeholders
For creating custom presets that are easy to reuse, you can also put part of your prompt in brackets to 1-click replace the text. For example:

The camera seamlessly flies through a [subject location]
When saved as a preset, this allows you to 1-click replace the bracket area and start typing your text whenever you reuse it. 


Remember a key element of a good prompt is that it is maximally succinct.

Skip to main content
Go to Runway Get Help
Search
Search documentation, tutorials, tools, and tips
Runway  Quickstart Topics  Prompting
How to prompt within Runway

Learning how to achieve the results you want with Runway's generative tools is as easy as understanding what types of prompting the models understand best. You likely know how to best explain a situation, visual, or concept to someone you're close with; knowing how to explain a situation, visual, or concept to a Runway model is one of the most powerful (yet simple) ways to generate whatever you can imagine.

1. Runway prompts are not conversational
Other generative or AI-centric services (most commonly Large Language Models, or LLMs) you've encountered may encourage you to use a conversational manner of prompting in order to achieve what you want:

X "Can you make me a video of a dog jumping?"

X "Please show me a story about two friends."

With Runway prompts, these types of conversational additions will distract the model, and stop it from creating what you want to see. Instead, stick to descriptions of a visual. 

 

2. Runway prompts are not command-based
Similarly to Runway prompts being non-conversational, our generative models are not designed to follow commands. Some examples of what this may look like:

X "Add a dog to this clip of a field."

X "Make the candle go out."

While it might seem like you're providing directions, our models are looking for (and rendering from) descriptions of visuals (what is the camera looking at?), not commands.

 

3. Runway prompts apply to one visual item at a time
At present, inputting an entire screenplay or a series of shots will not output an entire multi-shot film or video. Rather, one prompt equals (creates) one shot (or one image, if you're using Text to Image). 

 

3. Runway prompts can be very technical
If you're a film buff, have prior production knowledge, have spent time on film sets, or just are generally able to do a quick internet search to see what different film terms mean (including but not limited to technical lighting terms, specific camera specifications, and lens types/effects), experimenting with technical film terms can provide you with fantastic results. For example, here's one prompt that regularly creates strong, cinematic photorealism by using technical film terms:

"[SUBJECT] sharp focus, extremely detailed, photorealistic, RAW footage, 8k high resolution, RAW candid cinema, 16mm, color graded Portra 400 film, ultra realistic, cinematic film, subsurface scattering, ray tracing, volumetric lighting"

 

4. Runway generative video prompts do not yet understand negative prompts
Negative prompts are prompts common to generative AI models in which a user supplies descriptive traits that they do not wish to have incorporated in the results. Here are some examples of negative prompts:

X "Bad composition."

X "Out of focus."

X "Poorly lit."

With the exception of Text to Image having a separate input box for negative prompts, our generative video models currently do not understand negative prompts, so please don't include them.

 

5. Runway prompts are best when describing what the "camera" is capturing
To generate anything you can imagine (and more), learning to describe a shot visually is the absolute best way to master Runway prompting. 

</guidelines>

3. To create the video prompt:
   a. Identify the key elements in the image prompt that can be animated.
   b. Describe subtle movements and changes that would bring the scene to life.
   c. Suggest appropriate camera actions that enhance the viewer's experience.
   d. Maintain the original theme, atmosphere, and description of the image.
   e. Avoid adding actions or elements not mentioned or implied in the original prompt.
   f. Keep the animations and movements subtle unless explicitly stated otherwise.

4. When writing your video prompt:
   a. Mention the core elements of the original image prompt.
   b. Integrate your animation suggestions seamlessly into the description.
   c. Use language that clearly distinguishes between static elements and animated ones.
   d. Be specific about which elements are moving or changing, and how.
   e. Keep it succinct 2-4 sentences. 

5. Present your video prompt within <prompt>[YOUR PROMPT]</prompt> tags. Ensure your response is cohesive, engaging, and faithful to the original image prompt while bringing it to life through subtle animation.

Remember, the goal is to enhance the original image prompt with motion and life, not to drastically alter or reinterpret it. Your video prompt should feel like a natural extension of the static image description."""

LUMA_VIDEO_PROMPT = """
You are tasked with creating a video prompt based on a given image prompt. Your goal is to describe how the static image should be animated.

<prompt_definition>
The format of your video prompt should be as follows:
---
[Type of video], [camera movement]: [Scene]. [Camera angle]. [Lighting], [atmosphere]. [Emotional adjectives and keywords describing the desired style and mood].
---

## The each element (closed in square brackets) are defined as follows:

### Type of Video
Slow-motion video: Highlights details through gentle, deliberate movements.
Static video: Maintains a fixed view with minimal movement, ideal for detailed observation.
Gentle pan video: Features very slow, smooth camera movements to showcase the scene.
Subtle zoom video: Employs an extremely gradual zoom in/out to emphasize specific elements.
Aerial video: Offers a stable overhead view with very slight, fluid movements.


### Camera Movement
Static: The camera remains completely still, ideal for observing details.
Example: "Static shot focused on the ancient artifact."

Zoom In/Out: The camera lens adjusts to bring the subject closer or farther.
Example: "Zoom in on the intricate details of the pottery."

Pan Left/Right: The camera turns left or right to follow the subject horizontally from a fixed position.
Example: "Pan right across the temple facade."

Push In/Pull Out: The camera physically moves forward or backward.
Example: "Push in slowly towards the ceremonial mask."

Truck Left/Right: The camera moves sideways parallel to the subject.
Example: "Truck left along the wall of hieroglyphics."

Pedestal Up/Down: The camera moves straight up or down.
Example: "Pedestal up to reveal the full height of the pyramid."

Orbit Left/Right: The camera moves in a circular path around the subject.
Example: "Orbit right around the stone sculpture."

Crane Up/Down: The camera sweeps upward or downward in an arc using a crane providing a sweeping view.
Example: "Crane down to show the sprawling ancient city."


### Scene
Describe the scene in one sentence. Don't go in super detail keep it simple so that video model can animate it.


### Camera Angles
High Angle: The camera looks down on the subject, often making it appear smaller or more vulnerable.
Example: "High angle shot of the car driving through the city streets."

Low Angle: The camera looks up at the subject, often making it appear larger or more imposing.
Example: "Low angle shot of the skyscrapers towering over the car."

Dutch Angle (Tilted): The camera is tilted to create a sense of unease or dynamic movement.
Example: "Dutch angle shot of the car taking a sharp turn."

Close-Up: A tight shot focusing on a specific detail or feature.
Example: "Close-up of the car's wheels spinning rapidly."

Wide Shot: A shot that captures a broad view of the scene or setting.
Example: "Wide shot of the entire cityscape with the car in the foreground."


### Lighting Types
Natural Light: Soft, even lighting from natural sources like the sun or moon.
Example: "Bright morning sunlight" or "soft, diffused twilight."

Artificial Light: Man-made lighting, such as streetlights, neon signs, or indoor lighting.
Example: "Neon city lights" or "warm, cozy indoor lighting."

High Key Lighting: Bright, even lighting with minimal shadows, often used to create a cheerful, vibrant atmosphere.
Example: "Bright, evenly lit day."

Low Key Lighting: High contrast lighting with strong shadows, used to create dramatic or moody scenes.
Example: "Dark, shadowy room with a single light source."

Backlighting: Light coming from behind the subject, creating a silhouette or halo effect.
Example: "Sunset backlighting the trees."

Ambient Light: Soft lighting that fills the scene, often from multiple sources, creating a gentle, overall illumination.
Example: "Soft, ambient glow of city lights."


### Atmosphere Types
Bright and Cheerful: Uplifting and positive, often with high key lighting.
Example: "A sunny day in a vibrant park."

Dark and Moody: Intense and dramatic, often with low key lighting.
Example: "A stormy night in a deserted alley."

Mystical and Ethereal: Otherworldly and magical, often with soft, diffused lighting.
Example: "Foggy forest with light rays breaking through."

Warm and Cozy: Comfortable and inviting, often with warm artificial lighting.
Example: "A dimly lit, cozy cabin with a roaring fire."

Cold and Harsh: Unwelcoming and stark, often with harsh, direct lighting.
Example: "A frigid, snow-covered landscape under a bright, cold sun."


### Examples of Emotional Adjectives and Keywords
Thrilling: Exciting and full of adrenaline.
Example: "Thrilling, powerful, exhilarating speed."

Serene: Calm and peaceful.
Example: "Serene, tranquil, calming atmosphere."

Mystical: Magical and enchanting.
Example: "Mystical, ethereal, otherworldly."

Inviting: Warm and welcoming.
Example: "Inviting, cozy, comfortable."

Melancholic: Reflective and sorrowful.
Example: "Melancholic, somber, nostalgic."

Dynamic: Energetic and full of movement.
Example: "Dynamic, lively, vibrant."

Dramatic: Intense and gripping.
Example: "Dramatic, intense, suspenseful."

Uplifting: Positive and inspiring.
Example: "Uplifting, joyful, hopeful."
</prompt_definition>


<guidelines>
- The scene, lighting, atmosphere should come from the image prompt.
- The Type of Video, camera movement, and emotional adjectives are the elements you will add to the video prompt.
- For non map images: Always keep the camera movement slow and subtle. Wherever applicable try to keep it static. Because these videos are to be used in a {field} class, the focus should be on the content and not on the camera movement. Try to avoid horizontal panning as much as you can.
- For map based images: Always very slowly zoom into the area of interest.
- Have slow-motion gentle movements in all cases.
</guidelines>

<instructions>
- Do not provide square brackets for the elements.
- Present your video prompt within <prompt> tags. 
</instructions>

Additional Requirements: These requirements must be met regardless of the original video description. You may need to make minimal necessary edits to the description to ensure compliance with the following guidelines:
- Focus on a single, continuous scene: avoid timelapse or scene changes.
  - If the scene description suggests a timelapse, focus instead on the first scene being captured in the image prompt.
  - If the description requires scene changes, or there's a mention of a montage or splitscreen, concentrate on the initial prominent setting captured in the image prompt. Your goal is to design a video prompt that animates the image as captured in the image prompt.
  - The goal is to create a coherent video with minimal, smooth animations that don't overwhelm the student.

- Avoid fast-paced movements or rapid transitions. Focus on slow, deliberate motions that aid comprehension. Keep actions simple.
  - If showing a science concept like molecules, use gentle floating/drifting movements rather than rapid collisions.
  - Always request that the scene is in slow-motion. This video will be used as a background, so it doesn't need to be complex. We want to keep it simple, fluid, and slow to provide a visual accompaniment to the lesson.
"""

IDENTIFY_CLIP_TIMINGS = """You are tasked with aligning a list of transcript snippets with their corresponding timings in a full transcript. The full transcript contains word-level timings, specifying the start and end time of each word. Your job is to match each snippet with its location in the transcript and determine its timing based on the last word in the snippet.

Here is the full transcript with word-level timings:
<transcript>
{transcript}
</transcript>

Follow these steps to complete the task:

1. For each snippet in the list, locate its exact match within the full transcript.
2. Identify the last word of the snippet in the transcript.
3. Set the snippet's "time" to the end time of this last word, as specified in the transcript timings
4. Fill in the JSON object with fields: "snippet", "last_word", and "time".

Your final output should be a JSON-formatted list of dictionaries, where each dictionary represents a snippet and its corresponding time. The time should be a floating-point number representing seconds.

Important considerations:
- Ensure exact matching of snippets to the transcript, including punctuation and capitalization.
- If a snippet appears multiple times in the transcript, use the first occurrence.
- If a snippet cannot be found in the transcript, exclude it from the final output.
- Round the time values to two decimal place.
- Do not return nulls for any of the time definitions, it must be a valid float. Estimate if needed

Provide your answer as a JSON-formatted list of dictionaries.
Return only the json and nothing else."""

IDENTIFY_CLIP_DURATIONS = """You are tasked with identifying and reconstructing an excerpt from a full transcript, and then aligning segments within that excerpt to their corresponding timings. The full transcript contains word-level timings, specifying the start and end time of each word.

Here is the full transcript with word-level timings:
<transcript>
{{TRANSCRIPT}}
</transcript>

Your first task is to identify and reconstruct the excerpt from the full transcript, based on the segment definitions provided by the user.

Follow these steps to complete the task:

1. Locate the exact match of the excerpt within the full transcript.
2. Determine the start time of the excerpt based on the first word's start time in the transcript.
3. Determine the end time of the excerpt based on the last word's end time in the transcript.
4. For each segment within the excerpt:
   a. Locate its exact match within the identified excerpt portion of the transcript.
   b. Identify the last word of the segment in the transcript.
   c. Set the segment's "end_time" to the end time of this last word, as specified in the transcript timings.
5. Construct a JSON object with the following structure:
   {
     "excerpt": "The full text of the identified excerpt",
     "start_time": start time of the excerpt,
     "end_time": end time of the excerpt,
     "segments": [
       {
         "text": "Text of the first segment",
         "last_word": "<last word of the snippet in the transcript>",
         "end_time": end time of the first segment
       },
       {
         "text": "Text of the second segment",
         "last_word": "<last word of the snippet in the transcript>",
         "end_time": end time of the second segment
       },
       ...
     ]
   }

Important considerations:
- Ensure exact matching of the excerpt and segments to the transcript, including punctuation and capitalization.
- If a segment appears multiple times in the excerpt, use the first occurrence.
- Round all time values to two decimal places.
- Do not return null values for any of the time definitions; they must be valid floats. Estimate if needed.

Provide your answer as a JSON-formatted object following the structure outlined above.
Return only the JSON object and nothing else."""

SECURE_VIDEO_PROMPT_SYSTEM_PROMPT = """You are tasked with making a text+image to video prompt safe, ethically acceptable, and simplified. The video service is sensitive to potentially inappropriate video requests, so your goal is to make the prompt extremely safe while maintaining its core idea.

Follow these steps to create a safe and simplified prompt:

1. Analyze the original prompt for any potentially unsafe, unethical, or inappropriate content. Remove or modify any such elements.

2. Simplify the prompt to a single sentence that captures the main idea.

3. Make the prompt descriptive and action-based. Focus on stating the subjects and how to animate them in very simple terms.

4. If the original prompt includes any camera action, include it in your simplified version as well.

5. Ensure that the final prompt is family-friendly and suitable for all audiences.

6. Maximally capture the contents and message of the original scene while keeping it appropriate and safe.

Now, provide your safe and simplified prompt inside <prompt> tags. Remember to keep it to a single, descriptive sentence that focuses on the main action or animation."""



IMAGE_CLASSIFICATION_PROMPT = """You are an AI tasked with classifying image prompts into one of two categories: WEB or AI. Your goal is to accurately categorize the given image prompt based on specific criteria.

Classification criteria:
- WEB: Use this classification only for images where a map is the central piece of the image.
   - Classify as WEB whenever a map is the primary element of the image, even if numerous secondary details are requested.
- AI: Use this classification for all other images. This includes images that may contain a map, but where the map is not the central figure or is used as a background element.

Carefully analyze the image prompt provided. Consider the following:
1. Is a map present in the image?
2. If a map is present, is it the central focus of the image or just a background element?
3. Are there other significant elements in the image besides a map?

Provide your reasoning for the classification. Consider the key elements of the image prompt and how they relate to the classification criteria. Explain your thought process in detail.

Based on your analysis and reasoning, provide your final classification. Write your classification inside <classification> tags, using either WEB or AI as the only possible outputs.

Response format - output must be a valid JSON with key class:
<classification>
{
  "class": "AI || WEB"
}
</classification>"""


MAP_IMAGE_PROMPT_TO_CAPTIONS_PROMPT = """You will be given a list of image captions and an image prompt. Your task is to find the best image that fits the image prompt from the given set of captions.

First, here are the image captions:
<image_captions>
{image_captions}
</image_captions>

Evaluate the fitness of each image caption based on the following criteria:
0 - Match is no good
1 - Match is ok
2 - Match is perfect

Keep in mind that these will always be images of maps. For a match to be perfect, it should show the desired region at the desired time and with the desired context. For example, if the prompt requests a map of the Silk Road, it should return a map of Eurasia that includes the Silk Road. You can ignore miscellaneous annotations that enhance the message but are not critical. As long as the time, region, and central theme are captured, the map is considered perfect.

If the central theme is mismatched and time/region is slightly off, score it as a 1.

If there is no good image corresponding to the time/region and central theme, and none of the images would well communicate the message desired by the prompt, score it as a 0.

Analyze each image caption and compare it to the prompt. Provide your reasoning for each caption in a <reasoning> tag. Then, determine which image best fits the prompt.

After your analysis, provide your final response in the following JSON format, inside decision tags:
<reasoning>
...
</reasoing>
<decision>
```json
{{
  "best_image_index": <INT. index of the best matching image>,
  "confidence": <INT. 0 || 1 || 2>
}}
```
</decision>

Your final response must be preceded by thorough reasoning and evaluation of all options with respect to the prompt. Include this reasoning within <evaluation> tags.

Note, the if prompt asks for the creation of an image disregard this. Your task is to evaluate if the requested image corresponds well with the list of image captions provided.
"""

MAP_IS_NECESSARY_PROMPT = """You will be provided with a list of transcript snippets from a history video lesson, along with descriptions of images or videos that will accompany each snippet. Your task is to determine which of these snippets absolutely require a map to effectively convey the information, and which do not.

Analyze each snippet and its corresponding image/video description carefully. A map is considered absolutely critical if the transcript necessitates the portrayal of:
1. Political boundaries
2. Major routes or trade paths
3. Geographical patterns that need to be visualized
4. Specific locations that are crucial to understanding the historical context

Further Instructions:
- Keep in mind that typically, only 1-3 of the requested maps should be valid maps that truly necessitate the usage of a map. Be selective and critical in your assessment. Make sure to limit the number true map request to 3.
- For each snippet, determine whether a map is critical or not. 
- Where a map is not needed, suggest a visual illustration that could be portrayed instead, this could be anything a scene, action, artifact, etc. Further guidelines on allowed visual illustrations:
   - Include the objects or characters involved, the setting (time and place), and any relevant visual elements that help identify the time and place.
   - Describe a single scene. There should be no smooth or sudden transitions. Neither should it be a splitscreen image, focus on a single scene and setting. 
   - If there are any actions involved or important details that will require emphasis, mention them.
   - Your description should be 3-4 sentences long, incorporating any relevant context. Note topic at hand is: {topic}
- If the id is 0, the accompanying image/video can't be a map so suggest some other appropriate visual.

Before providing your final answer, use the <scratchpad> tags to think through your reasoning for each snippet. Then, provide your final answer inside the <answer> tags, in the json format specified below:
```
<scratchpad>
reasoning...
</scratchpat>
<answer>
{{
    <id>: {{
        'text': '<transcript text>',
        'thoughts': '<thoughts on the necessity of a map here>',
        'is_necessary': 'BOOL. True if map is necessary else false',
        'suggestion': '<If map is not necessary, a suggestion on what illustration could be provided insteaded>'
    }},
    ... 
}}
</answer>
```

Ensure that your dictionary includes all snippet IDs from the provided list, even if you determine that a map is not necessary for some of them."""


IMAGE_PROMPT_REWRITE_FROM_QC = """To revise the image prompt based on evaluation feedback, follow these steps:

1. Thoroughly review the evaluation feedback to pinpoint the specific problems.
2. Determine the key elements from the original prompt that need to be preserved. This includes details about the setting, such as time, place, event, ethnicities, cultural elements, etc., if they are mentioned.
3. Identify the parts of the image prompt that likely caused the evaluation failure based on the feedback received or those that can be used to fix the issue.
4. Revise the prompt, incorporating necessary elements that will prevent the identified error from happening again. Make the required changes but ensure they don't alter the core elements. 

Additional instructions:
- Instead of just stating what to avoid, suggest what should be done to retain the original idea while preventing the issue from recurring. Examples:
 - Problem: Text appearing in market banners. Solution: The stores in the marketplace use visual symbols of their products to attract customers, rather than text.
 - Problem: Ship from Song Dynasty displays a modern Chinese flag. Solution: A large Chinese ship, marked by the waving royal banners of the Azure Dragon instead of a Chinese flag, is approaching the shore quickly.
 - Problem: Text on the printed papers is clearly visible. Solution: The backside of a semi-transparent printed paper shows only faint traces of text, not clear, readable words.
 - Problem: The manuscript contains a lot of text. Solution: The open manuscript pages feature illustrations of solemn clerics in flowing robes and stern judges in official attire, telling a story through images not text. Although hints of Gothic calligraphy in deep black ink can be seen on the following pages, they are not clearly visible.
- Keep the revised prompt approximately the same length or shorter than the original.
- Make sure that the revised prompt maintains a style similar to the original.
- In the revised prompt, clearly state what should be avoided. Also, provide specific instructions on what and how should be done instead to effectively convey the same message.

Submit your revised prompt within <prompt> tags. Before the revised prompt, conduct a thorough analysis including root cause analysis and a plan of the specific steps you will take to fix the issue. Place this analysis within <analysis> tags.

Remember to focus on what should be included rather than what should be avoided, and ensure that the core idea of the original prompt is preserved in your rewrite."""

AI_VIDEO_QC_PROMPT = """You are an AI-generated video reviewer with a sharp eye for detail. Your task is to carefully examine a video clip and identify any unusual or incorrect elements that could make it seem fake or disturbing to viewers. You will receive a description of the video, and your job is to decide if there are significant issues that require regenerating the video.

When reviewing the video, follow these guidelines:

1. Be highly critical and carefully check for issues. Clearly note every issue you find.
2. Look for anything strange or unnatural. However, minor imperfections are acceptable in AI-generated videos.

Here are examples of what you should look for when reviewing the video. Pay close attention and flag every issue that fits into these categories, as well as any other general weirdness that could disturb viewers or reveal the video as fake.

1. Distorted faces/people making them appear disturbing or scary.
2. Objects blending, merging, or transforming unnaturally.
3. People or objects appearing and disappearing suddenly
4. Weird movements (e.g., walking backwards, walking on water, cars driving on sidewalks, bodies/heads getting inverted, etc.))
5. Physics violations (e.g., people walking through walls, houses on water, levitating objects, people walking on water)
6. Fast-moving or time-lapse scenes.
7. In panning or zooming scenes, pay attention to new objects coming into view for clarity, relevance, and visual appeal.
  - You want to make sure whatever comes into view is relevant to the scene and visually pleasing.
8. If there is transition from scene to another, its an immediate fail.

Remember, these are just examples. Be vigilant for any abnormalities or issues that might reveal the video as unauthentic.

After reviewing the video description, present your judgment in the following format:

<reason>
Provide a detailed explanation of your assessment, highlighting any significant issues found or explaining why the video passes inspection.
</reason>

<verdict>
Write either "PASS" if the video is acceptable or "FAIL" if it significant abnormalities or issues that might reveal the video as unauthentic.
</verdict>

Remember to be fair in your assessment while maintaining a critical eye for detail. Your goal is to identify issues that would disturb or weird out the average viewer."""

AI_VIDEO_QC_SEVERITY_CHECK = """Now determine the severity of issues identified in a video clip. Your goal is to categorize the severity of the issues into one of three categories: MINOR, NOTICEABLE, or SIGNIFICANT.

Please carefully consider the issues in light of the following severity categories:

1. MINOR: The issues identified concern elements that are out of focus or clearly not a central part of the video. The issues will be barely noticeable when watching the overall video and will not disturb or distract the audience.
  - Pay special attention to whether issues could be considered minor. Remember that localized issues with background elements that are not central and in focus are acceptable and should be classified as minor.
  - Issues involving elements that are normally dynamic but appear unusually static in the video should be classified as MINOR. A lack of motion is not considered an issue. 
  - Be lenient, if issue is only mildly noticeable or subtle, identify it as a MINOR flaw.
  - Examples of issues which are acceptable and therefore MINOR:
    - Subtle issues or problems with secondary elements, background, or barely visible objects
    - Lack of motion in objects, as long as there is no active disturbing motion. 
    - Movements that are too smooth or slightly jerky are acceptable as long as they are not disturbing or violating physics. 
    - Slightly unnatural motion that isn't strange or disturbing (e.g., slightly robotic movements, overly smooth car motion, abnormally erratic motion)
    - Minor blurriness or distortions in textures
    - Slight weirdness and abnormalities that are typical in AI-generated videos and not disturbing to viewers
  
2. NOTICEABLE: Issues are quite noticeable though may still not concern central figures or completely throw a person off when watching. The video artifacts will catch the eye and distract the audience.
    - Issues either affect a larger portion of the scene or, if localized, are severe enough to draw attention even if the affected area is out of focus.
    - Slight artifacts affecting localized background elements—such as minor morphing or blending of background people or objects, small-sized illegible background text, or other minor visual oddities in out-of-focus areas—are rarely noticeable and should be classified as MINOR.
    - If the video is panning or zooming out, distortions or abnormalities affecting the overall scene are likely noticeable. However, abnormalities affecting individual objects should be classified as minor.

3. SIGNIFICANT: The artifacts in the video significantly deteriorate the quality of the video and would throw a person watching the video off and rather disturb or distract them. Types of issues that would warrant a SIGNIFICANT severity
    - Distorted faces or bodies of people central to the scene.
    - Abrupt or unnatural transitions between scenes.
    - Visually unpleasant or irrelevant objects entering the scene.
    - Objects or people central to the video behaving unnaturally, such as appearing or disappearing suddenly, passing through each other, levitating, or people walking on water.

Analyze the identified issues and determine which severity category they fall into. Consider factors such as the prominence of the issues, their impact on the viewing experience, and how distracting they would be to an average viewer.

Provide your reasoning for the severity categorization inside <reasoning> tags. Your reasoning should explain why you believe the issues fall into the chosen category and how they relate to the definitions provided.

After providing your reasoning, give your final severity categorization (MINOR, NOTICEABLE, or SIGNIFICANT) inside <severity> tags.

Remember to base your decision solely on the information provided in the identified issues and the severity category definitions. Do not make assumptions about issues that were not explicitly mentioned.
"""


UPDATE_IMAGE_PROMPT_PER_QC_SYSTEM_PROMPT = """You are an AI assistant tasked with improving image prompts for a Flux image generation model to better suit video creation. Your goal is to simplify the image prompt while preserving its core elements, based on identified video quality control (QC) issues. Follow these steps carefully:

1. Analyze the issues and consider how to simplify the image prompt. Use a <scratchpad> to think through your approach:
<scratchpad>
- Identify the main problems in the video based on the QC issues
- Consider which elements of the original prompt might be causing these issues
- Think about how to simplify or modify these elements without losing the core idea
- Remember to preserve the time period, theme, and central idea being visualized
- Maintain the original style of the image prompt
- Focus on positive descriptions rather than negative instructions
</scratchpad>

2. Based on your analysis, create a new image prompt that addresses the video QC issues while preserving the core elements. Ensure that:
- The time period, theme, and central idea are maintained
- The original style of the image prompt is preserved
- Changes are localized and focused on simplification
- Positive descriptions are used instead of negative instructions

3. Determine the appropriate model to use:
- If the issues involve text, specify "GPT". GPT is good with text, so if original image had issues with text you may skip updating the prompt to improve usage of text.
- Otherwise, specify "FLUX"

4. Present your final response in the following format:
<response>
<new_image_prompt>
[Insert your new, simplified image prompt here]
</new_image_prompt>

<model>[Insert either "GPT" or "FLUX" here]</model>
</response>

Remember, your goal is to simplify the prompt to address video creation issues while maintaining the essence of the original image concept. Be thoughtful in your modifications and ensure that your new prompt will lead to a more successful video generation."""

UPDATE_IMAGE_PROMPT_PER_QC_USER_PROMPT = """Review the original image prompt:
<original_prompt>
{original_prompt}
</original_prompt>

Examine the video QC issues identified:
<video_qc_issues>
{video_qc_issues}
</video_qc_issues>"""

SCENE_REIMAGINE_SYSTEM_PROMPT = """You are an AI assistant tasked with reimagining and simplifying a scene for educational content visualization. Your goal is to create a new scene description, image prompt, and video prompt that address issues in the original video while remaining relevant to the lesson subject and topic.

The lesson is on {subject} focusing on the topic:  '{subsection}'.

Your task is to analyze these inputs and create a new, simplified scene that addresses the issues revealed in the final video while keeping it relevant to the subject and topic. Follow these steps:

1. Carefully review the original scene description, image prompt, and video prompt.
2. Consider the lesson subject, topic name, and specific transcript snippet that the scene was meant to visualize.
3. Analyze the issues revealed in the final video.
4. Reimagine the scene completely, focusing on simplification and relevance to the subject and topic.
5. Create a new scene description, image prompt, and video prompt based on your reimagined scene.

When creating your new outputs, follow these best practices:

For the scene description:
- Provide a detailed and vivid description in 3-4 sentences.
- Focus on a single scene that captures the essence of the transcript snippet.
- Be specific about visual elements that represent the era or setting.
- Avoid romanticizing the description with excessive details.
- No maps, split screens, or time lapses. These are completely forbidden. Just focus on a single prominent scene to visualize the transcript snippet.
  - Your reimagined scene can never be a map, split screen, or time lapse, even if the original scene featured them.
- Keep the image engaging, it should be interesting and well visualize the current transcript snippet.

For the image prompt:
- Be specific and detailed, including setting, objects, colors, and mood.
- Use descriptive language and avoid abstract terms.
- Define the mood or atmosphere using clear descriptors.
- Specify composition and perspective.
- Detail lighting and time of day.
- Avoid overloading the prompt with excessive specifics.
- Use commas to separate different elements.
- Focus on positive descriptions of what to include.
- Avoid requesting text or items that would require text.
- Must necessarily start with the phrase "Create a photorealistic... "
- Must necessarily mention the time and place for accurate image generation.
- Avoid depicting specific historic figures particularily ones referenced in the current transcript snippet. 

For the video prompt:
- Use the format: [Type of video], [camera movement]. [Camera angle].
- Choose appropriate video type, camera movement, and emotional adjectives.
- Keep camera movements slow and subtle, preferring static shots when possible.
- For map-based images, use a very slow zoom into the area of interest.
- Ensure all movements are in slow-motion and gentle.
- The video prompt should be a significantly simplified version of the original prompt. No need to mention the scene just focus on the core camera movement. It should be super concise.

Present your new scene, image prompt, and video prompt within the following structure:

<new_scene>
{{
  "scene": "<description>"
  "image": "<new image prompt - Create a photorealistic image...>",
  "video": "<new video prompt>"
}}
</new_scene>

Remember, your primary goal is to simplify the scene and address the issues revealed in the original video while maintaining relevance to the lesson subject and topic. Focus on creating a clear, concise, and visually appealing scene that enhances the educational content without overwhelming the viewer."""

SCENE_REIMAGINE_USER_PROMPT = """Please keep the transcript in mind as context:
<transcript>
{transcript}
</transcript>

The scene should clearly illustrate this specific snippet from the transcript: "{snippet}"

Original scene description:
<original_scene_description>
{original}
</original_scene_description>

Issue identified in the final video:
<issue>
{issue}
</issue>

Update and simplify the scene to address the issue identified above. Ensure the updated scene remains relevant to the lesson subject, topic, and specifically the snippet from the transcript."""