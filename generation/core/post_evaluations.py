import json
import os
import re
import csv
import random
import uuid
import re
import nltk
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from collections import Counter
from fuzzywuzzy import fuzz
from typing import List, Dict, Optional, Tuple, Any, Union
from core.types import TranscriptOutput, TranscriptSupplements, OverlaysData, TranscriptTiming, VideoPlan, MCQ, Concept
from core.clients.sheets import save_dicts_to_csv, upload_csv_to_gsheet
from core.clients.gsheet import GoogleSheetsClient
from core.helpers import print_json
from stages.transcript import format_concept, qc_llm_call, generate_questions_per_concept

from stages.text_overlays import identify_question_timings
from core.clients.s3 import does_file_exist, download, delete_file_from_s3, load_json_from_s3, S3_BUCKET, get_s3_client, upload_file_to_s3, save_json_to_s3
from core.clients.sheets import upload_csv_to_gsheet
from core.context import APVideoContext as Context, prep_content_gen_input, get_lesson_context
from core.clients.sheets import write_to_cell
from core.helpers import (
    exception_handler, extract_tag_content, llm_call, print_json,
    replace_spaces, retrieve_markdown_element)
from core.clients.openai import LLM
generations_sheet_id = "16UfbuX-mfce8fzLh6MpRb7SShWMc6jMLJu1djrD1zsI"
generations_sheet_name = "AP World History - Dump2"


FIND_VISUAL_OBJECTS_SYSTEM_PROMPT = """You are tasked with evaluating an AP History lesson to identify objects that would significantly benefit from visual representation. Your goal is to determine which objects mentioned in the lesson are critical for students to visualize to better understand the content.

Carefully read the lesson and select objects based on these criteria:

1. The object is highly visual and tangible.
   - Only physical objects qualify. Abstract concepts or non-tangible items should be excluded.

2. Understanding the object is essential to grasping the lesson content.
   - For example, generic mentions of ships do not require visualization. However, if the lesson specifically discusses historic ships (e.g., Chinese Junk Ships), visualizing them would help students better understand the lesson.

3. An image of the object can likely be found online.

4. Seeing the object would significantly improve students' comprehension of the historical concept.
   - The lesson should actively explain what the object is, how it was used, or its historical importance. Brief mentions for context alone do not qualify.

Acceptable visualizations include:
- Images of historical inventions, artifacts, landmarks, or other physical items.
- Examples: Magnetic Compass, Printing Press, Parthenon, Roman Aqueduct, Spinning Jenny, Cotton Gin, Great Wall of China, Steam Engine.

Do NOT include visualizations of:
- Historical scenes or events.
- People.
- Maps, documents, charts, or literary works.
- Complex images that would require attentive analysis to understand as opposed to being a quick visual e.g. systems (irrigation systems), transportation routes, etc.
- Examples to exclude: Medieval Castle (too generic), Map of a region, Terracotta Army, Battle of Gettysburg, Civil Rights March, Medieval Society, Aztec Empire.

As you analyze the lesson, focus only on objects that are critical to understanding historical events, innovations, or concepts. Not every object mentioned needs visualization—only those that provide substantial educational value.

For each object meeting the criteria, create a JSON entry with these fields:
1. "object": A brief (1-2 word) name of the object.
2. "visualization": A short description of the ideal image.
3. "justification": A clear explanation of why visualizing this object is critical for understanding the lesson.
4. "usage": The ID of the concept that requires visualization of the object, along with the exact substring from the concept statement mentioning the object. This substring should explain clearly what the object is, how it was used, and why it is important. Copy the substring exactly as it appears.

Your final output should be a JSON list formatted exactly as follows:

<output>
[
  {
    "object": "Object name",
    "visualization": "Description of ideal image",
    "justification": "Explanation of why this visual is critical",
    "usage": "How concept is mentioned and explained in the concept"
  },
  ...
]
</output>

If no suitable objects are found for visualization, your output should list only the names of up to 5 objects that were considered but ultimately excluded:

<output>
["<object name 1>", ...]
</output>

Prioritize quality over quantity. Include only the most critical objects. Provide only the JSON list within the <output> tags, without additional commentary or explanation."""

FIND_VISUAL_OBJECTS_USER_PROMPT = """Here is the AP History lesson content:

<lesson_content>
{content}
</lesson_content>"""


EVALUATION_TEMPLATE_SYSTEM_PROMPT = """You are a quality assurance specialist for educational content. Your task is to evaluate content from an AP World History video lesson against specific quality criteria. You will be provided with quality criteria and content to evaluate. Your job is to compare the content against the criteria and determine whether the content meets the defined requirements.

Here are the quality criteria you will use to evaluate the content:

<quality_criteria>
{quality_criteria}
</quality_criteria>

First, thoroughly assess the content against each criterion in the quality criteria. Use a scratchpad to organize your thoughts and evaluations. In your scratchpad, for each criterion:

1. Assess: Provide a balanced, objective assessment of whether the content meets the criterion.
2. Evaluate: Determine whether the content passes or fails the criterion.
3. Suggest: If the content fails the criterion, suggest an improvement to address the issue.

Use direct and straightforward language in your assessment. Be concise but specific, pointing out exact issues and quoting relevant substrings when necessary. Avoid vagueness or generalities.

<scratchpad>
[Your thorough assessment, evaluation, and suggestions go here]
</scratchpad>

After completing your assessment in the scratchpad, provide your final output in the following format:

<eval>
{{
    "[criterion name]": {{
        "pass": [boolean value: true if content passes the given criterion, false otherwise],
        "reasoning": "[single sentence specific justification of why the content passes or fails]"
    }},
    ...
}}
</eval>

Your final output should only include the eval section with the results for each criterion. Do not include the scratchpad or any other text in your final response."""

EVALUATION_TEMPLATE_USER_PROMPT = """Here is the content you will evaluate:

<content>
{content}
</content>"""

def find_json_keys(unit_folder_names: List[str], layer: str = "Video Transcript") -> List[str]:
    client = get_s3_client()
    all_json_keys = []
    
    for unit_folder in unit_folder_names:
        course = "AP World History: Video Lessons 2" if "AP World History" in unit_folder else "AP US History: Video Lessons"
        base_path = f"college_board/{course}"
        transcript_path = f"{base_path}/{unit_folder}/contents/subsection/{layer}/"
        print(transcript_path)
        paginator = client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=S3_BUCKET, Prefix=transcript_path)
        
        for page in pages:
            if 'Contents' not in page:
                print(f"No files found in {transcript_path}")
                continue
                
            for obj in page['Contents']:
                key = obj['Key']
                if key.endswith('.json'):
                    all_json_keys.append(key)
    
    print(f"Found {len(all_json_keys)} JSON files to process")
    return all_json_keys


def generic_llm_evaluation(eval_content: str, **kwargs: dict) -> Dict[str, str]:
    system_prompt = kwargs.get("system_prompt", EVALUATION_TEMPLATE_SYSTEM_PROMPT.format(quality_criteria=eval_criteria))
    user_prompt = kwargs.get("user_prompt", EVALUATION_TEMPLATE_USER_PROMPT)
    history, evaluation = llm_call(
        system_prompt=system_prompt,
        user_prompt=user_prompt.format(content=eval_content),
        model=kwargs.get("model", LLM.CLAUDE_3_7_SONNET),
        tag=kwargs.get("tag", "eval"),
        is_json=True
    )

    if kwargs.get("system_prompt") is None:
        evaluation = {f"{key.capitalize()} - {subkey.capitalize()}": value for key, inner_dict in evaluation.items() for subkey, value in inner_dict.items()}
    else:
        processor = kwargs.get("processor")
        evaluation = processor(evaluation)
    return evaluation

def evaluate_transcript(key: str, **kwargs) -> Union[str, List[str], Dict]:
    transcript = load_json_from_s3(key)['lesson_transcript']

    evaluation = generic_llm_evaluation(transcript, **kwargs)

    return evaluation

def evaluate_syllabus(key: str, **kwargs) -> Union[str, List[str], Dict]:
    kg = load_json_from_s3(key)
    kg = LessonKnowledgeGraph(**load_json_from_s3(key.replace('Video Transcript', 'Knowledge Graph')))
    concepts = f"{kg.format_lo_nodes()[0]}\n\n{kg.format_xu_facts()}\n\n{kg.format_lo_nodes()[1]}"

    evaluation = generic_llm_evaluation(concepts, **kwargs)

    return evaluation

def tokenized_word_counts(key: str, **kwargs) -> List[str]:
    """Standardizations:
    - Removing transcript annotations - Eliminating text patterns like "[...]:"
    - Lowercasing - Converting all tokens to lowercase
    - Filtering non-alphanumeric tokens - Removing tokens with special characters
    - Removing single-character tokens - Eliminating tokens with length ≤ 1
    - Removing stopwords - Filtering out common English words (articles, pronouns, etc.)
    - Part-of-speech filtering - Keeping only nouns, verbs, and adjectives based on POS tags
    - Lemmatization - Reducing words to their base forms according to their part of speech
    Output: Frequency thresholding - Including only words that appear at least 10 times and limiting to 10 words max
    """
    transcript = load_json_from_s3(key)['lesson_transcript']
    transcript = re.sub(r'\[[^\]]*\]:', '', transcript)

    try:
        nltk.data.find('tokenizers/punkt')
        nltk.data.find('tokenizers/punkt_tab')
        nltk.data.find('corpora/stopwords')
        nltk.data.find('corpora/wordnet')
        nltk.data.find('taggers/averaged_perceptron_tagger')
        nltk.data.find('taggers/averaged_perceptron_tagger_eng')
    except LookupError:
        nltk.download('punkt')
        nltk.download('punkt_tab')
        nltk.download('stopwords')
        nltk.download('wordnet')
        nltk.download('averaged_perceptron_tagger')
        nltk.download('averaged_perceptron_tagger_eng')
    
    # Tokenize and lowercase => Filter out non-alphanumeric tokens and single characters
    tokens = word_tokenize(transcript.lower())
    tokens = [token for token in tokens if token.isalnum() and len(token) > 1]
    
    # Get English stopwords (articles, common pronouns, etc.)
    stop_words = set(stopwords.words('english'))
    
    # Get POS tags to focus on nouns, verbs, adjectives
    pos_tags = nltk.pos_tag(tokens)
    
    # Filter and lemmatize tokens
    lemmatizer = WordNetLemmatizer()
    
    processed_tokens = []
    for token, pos in pos_tags:
        # Skip stopwords
        if token in stop_words:
            continue
        
        # Focus on nouns, verbs, and adjectives
        if pos.startswith('N'):  # Nouns
            lemma = lemmatizer.lemmatize(token, pos='n')
            processed_tokens.append(lemma)
        elif pos.startswith('V'):  # Verbs
            lemma = lemmatizer.lemmatize(token, pos='v')
            processed_tokens.append(lemma)
        elif pos.startswith('J'):  # Adjectives
            lemma = lemmatizer.lemmatize(token, pos='a')
            processed_tokens.append(lemma)
    
    # Count tokens
    word_counts = Counter(processed_tokens)
    
    # Determine which words to include based on criteria
    sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
    result = {}
    for i, (word, count) in enumerate(sorted_words[:10]):
        if count >= 10:
            result[f"Word {i+1}"] = f"Word: {word}\nCount: {count}"
        else:
            result[f"Word {i+1}"] = ""
    
    return result

def upload_data_to_gsheet(
    data: List[Dict[str, Union[str, Dict, List[str]]]],
    sheet_id: str = '1b1m-zpLGf8YFt-AGo_SlYOtEW4puPaBa8sAMAPxTtwU',
    sheet_name: Optional[str] = None
):
    processed_data = []
    for row in data:
        processed_row = {}
        for k, v in row.items():
            if isinstance(v, (dict, list)):
                processed_row[k] = json.dumps(v, ensure_ascii=False)
            else:
                processed_row[k] = v
        processed_data.append(processed_row)

    # Save to CSV
    tmp_csv = '/tmp/tmp.csv'
    save_dicts_to_csv(processed_data, tmp_csv)

    # Default to 'Sheet1' if no sheet_name provided
    if sheet_name is None:
        sheet_name = uuid.uuid4()

    client = GoogleSheetsClient(sheet_id)
    print(sheet_name)
    client.get_sheet_id(sheet_name, create_if_missing=True)
    upload_csv_to_gsheet(tmp_csv, sheet_id, sheet_name)

    return "SUCCESS"


def orchestrator(subjects, eval_type, **kwargs):
    evaluate_function = evaluation_types[eval_type]["evaluator"]
    layer = evaluation_types[eval_type]["layer"]

    keys = find_json_keys(subjects, layer= layer)
    final_output = {}
    for key in keys:

        unit = key.split('History - ')[1].split('/')[0]
        final_output.setdefault(unit, {})

        evaluation_output = evaluate_function(key, **kwargs)
        final_output[unit][os.path.splitext(os.path.basename(key))[0]] = evaluation_output

    # print_json(final_output)
    upload_data_to_gsheet([{"Unit": unit_name, "Lesson ID": lesson_id, **evaluation} 
                        for unit_name, unit in final_output.items() for lesson_id, evaluation in unit.items()], 
                        sheet_name=kwargs.get('sheet_name', None))
    return final_output

evaluation_types = {
    "LLM Transcript": {
        "evaluator": evaluate_transcript,
        "layer": "Video Transcript"
    },
    "Word Overuse": {
        "evaluator": tokenized_word_counts,
        "layer": "Video Transcript"     
    }
}

if __name__=="__main__":
    folders = [
        # "AP US History - vUnit_1", 
        # "AP US History - vUnit_2_new", 
        # "AP US History - vUnit_3_new", 
        # "AP US History - vUnit_4_new", 
        # "AP US History - vUnit_5_new", 
        # "AP US History - vUnit_6_new", 
        # "AP US History - vUnit_7_new", 
        # "AP US History - vUnit_8_new", 
        # "AP US History - vUnit_9_new", 

        "AP World History - vUnit_1", 
        "AP World History - vUnit_2_new", 
        "AP World History - vUnit_3_new", 
        "AP World History - vUnit_4_new", 
        "AP World History - vUnit_5_new",
        "AP World History - vUnit_6_new", 
        "AP World History - vUnit_7_new", 
        "AP World History - vUnit_8_new", 
        "AP World History - vUnit_9_new", 
    ]
    eval_criteria = """"""
    # orchestrator(folders, eval_type="Generic Transcript", eval_criteria=eval_criteria, sheet_name="Transcript Eval")
    output = orchestrator(folders, eval_type="LLM Transcript",
                 system_prompt=FIND_VISUAL_OBJECTS_SYSTEM_PROMPT, 
                 user_prompt=FIND_VISUAL_OBJECTS_USER_PROMPT, 
                 model=LLM.CLAUDE_3_7_SONNET_THINKING,
                 tag='output',
                 processor=lambda x: {"visuals": x}
                 )
    json.dump(output, open('./APW.json', 'w'), indent=2)
