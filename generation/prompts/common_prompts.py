ENSURE_JSON_SYSTEM_PROMPT = '''The user will provide a broken JSON response that GPT provided earlier.
1. You will respond only with the corrected format of that same exact JSON Object.
2. Ensure that python json.loads() will accept this JSON string as a dict.
3. If the JSON is already in corrected format then respond with that corrected JSON, never respond in any other format other than JSON.'''


general_subject_references = {
    "figure": {
        "history": "historical figure",
        "science": "scientist",
    },
    "focus_area": {
        "history": "period",
        "science": "concepts/processes"
    },
    "field": {
        "history": "History",
        "science": "Science"
    }
}

def get_subject_specific_general_prompt_entries(subject: str):
    return {
        k: v[[kk for kk in v.keys() if kk in subject.lower()][0]] for k,v in general_subject_references.items()
    }


ssi_history_main_scenes_breakdown = """Therefore, any visual requests should be relevant to that time and place, unless there are specific modern elements mentioned in the segment that require visualization.
   - Include the objects or characters involved, the setting (time and place), and any relevant visual elements that help identify the time and place.
   - Be sure to specify relevant and appropriate visual setting elements for the requested visuals. These may include time and place, ethnicity, cultural elements, etc.
      - For example, 'Medieval Europe', or 'Chinese royals in traditional attire characteristic to the Song Dynasty rule'.
      - Note that neither example explicitly states the period, but it is implied. Similarly, the place is implied in the second example. Try not to explicitly state period dates, but rather imply them, provided the necessary context is given."""

ssi_biology_main_scenes_breakdown = """
- Match the appropriate scale and perspective:
  * Clearly indicate if the view should be microscopic, cellular, anatomical, or ecosystem-level
  * Specify if cross-sections, cutaways, or transparent views are needed
  * Note when transitions between scales would enhance understanding (e.g., zooming from organ to cellular level)
  * Indicate when fluorescent marking or staining would help highlight specific structures
- Avoid complex scences requiring time lapses; text, arrows, or other annotations; side-by-side comparisons.
- For structural elements: specify whether realistic or schematic representation should be used and what should be highlighted.
- Remember to prioritize clarity over visual complexity, and ensure the visualization directly supports the learning objective of the segment.
"""

subject_specific_clips_instructions = {

    # DEFINE_TRANSCRIPT_CLIPS
    "ssi_custom_clip_specifications": {
        "history": ssi_history_main_scenes_breakdown,
        "science": ssi_biology_main_scenes_breakdown
    },

    # IMAGE_GEN_SYSTEM_PROMPT
    "ssi_enhance_image_prompt_examples": {
        "history": '1. **Sunset Beach Scene**:\n   - "Create a photorealistic image of a serene beach at sunset, with soft golden light reflecting on calm waters. Include a silhouette of a lone person walking along the shore, the sky painted with hues of orange and pink. Use a wide shot to capture the expansive horizon."\n\n2. **Futuristic Cityscape**:\n   - "Generate a high-resolution image of a bustling cyberpunk cityscape at night. The scene should feature towering skyscrapers with neon lights, flying cars weaving between buildings, and pedestrians in futuristic attire. Emphasize the vibrant blues and pinks of the neon signs and include a rainy atmosphere to enhance the mood."\n\n3. **Portrait in Van Gogh\'s Style**:\n   - "Create an impressionist portrait of a young woman, styled in the manner of Van Gogh. She should have expressive blue eyes and curly red hair, wearing a green vintage dress. The background should be a swirl of vibrant colors that evoke a sense of movement, with a focus on brushstroke textures."\n\n4. **Wildlife Photography - Majestic Lion**:\n   - "Produce a photorealistic image of a majestic lion standing on a rocky outcrop during the golden hour. The lighting should highlight the intricate details of the lion\'s mane and the intense gaze in its eyes. Include a savannah landscape in the background with acacia trees and a soft-focus effect to emphasize the subject."\n\n5. **Medieval Knight Scene**:\n   - "Illustrate a dramatic scene featuring a medieval knight in shiny armor, holding a sword, standing in a misty forest. The image should capture the early morning light filtering through the trees, creating a play of light and shadow. Use a low angle to give a heroic feel to the knight, and include detailed textures on the armor and sword.',
        "science": '1. **Red Blood Cell**. Create a photorealistic microscopic view of a human red blood cell membrane at 10,000x magnification. Show the phospholipid bilayer with embedded proteins, capturing the fluid mosaic model in stunning detail. Use subtle blues and purples to enhance cellular structures.\n2. **Plant Cell in Metaphase**. Generate a high-resolution electron microscope image of a dividing plant cell in metaphase, showing clear chromosomes aligned at the metaphase plate. Include visible spindle fibers and a sharp contrast between cellular structures, using grayscale tones typical of electron microscopy.\n3. **Venus Flytrap Feasting**. Produce a photorealistic close-up of a Venus flytrap capturing prey, showing the intricate trigger hairs and digestive enzymes glistening on the trap\'s surface. Capture the moment just as the lobes begin to close, with dramatic lighting highlighting the red interior.\n4. **Coral Reef Ecosystem**. Create a wide-angle shot of a coral reef ecosystem during daylight, showing the symbiotic relationship between clownfish and sea anemones. Include clear, turquoise water and natural sunlight streaming through, highlighting the vibrant colors of marine life."'
    },
    "ssi_enhance_image_description": {
      "history": " - When deciding between different options for mood, composition, perspective, and time of day in AI-generated images, consider the narrative purpose, emotional impact, and visual aesthetics you aim to achieve. Evaluate how each element aligns with the overall theme and message of the image.\n  - These images are to be presented as part of a history class, so it is critical that the prompt requests authentic elements appropriate to the time at hand. It shouldn't include modern elements unless specifically requested in the description.",
      "science": "- When depicting biological processes or structures, maintain proper scale relationships and include standard scientific reference points (e.g., scale bars for microscopic images, size comparisons for anatomical features).\n- For microscopic images, specify the type of microscopy (light, electron, fluorescence) and magnification level to achieve appropriate detail and perspective.\n- When showing organisms or ecosystems, request natural behaviors and authentic environmental contexts, avoiding anthropomorphized or stylized representations unless specifically needed for educational purposes.\n- For processes or cycles, choose the most representative moment or stage that best illustrates the biological concept being taught, ensuring all visible elements contribute to understanding.\n - When depicting comparative biology (e.g., different species or variations), ensure consistent scale and perspective across subjects to facilitate accurate comparison."
    }
}


def get_subject_specific_clips_prompt_entries(subject: str):
    arguments = {**general_subject_references, **subject_specific_clips_instructions}
    return {
        k: v[[kk for kk in v.keys() if kk in subject.lower()][0]] for k,v in arguments.items()
    }