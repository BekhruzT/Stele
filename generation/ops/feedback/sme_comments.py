from concurrent.futures import ThreadPoolExecutor
import csv
import json
from core.google_api_utils import get_gspread_sheet, initialize_gspread_client, get_drive_service
from core.clients.openai import LLM, ensure_json, llm_complete
import logging
from core.logger import Logger
logger = Logger(__name__, logging.DEBUG)

from typing import Dict, List, Tuple


def fetch_comments_and_cell_text(sheet_id: str, cutoff_date: str, sme_name: str) -> List[Tuple[str, str]]:
    drive_service = get_drive_service()
    comments = []
    page_token = None
    while True:
        response = drive_service.comments().list(
            fileId=sheet_id,
            fields='*',
            includeDeleted=False,
            pageToken=page_token
        ).execute()

        comments.extend(response.get('comments', []))

        page_token = response.get('nextPageToken')
        if not page_token:
            break

    filtered_comments = []

    for comment in comments:
        # Check if comment matches criteria:
        # 1. Author is Jane Kelley
        # 2. Not resolved
        # 3. Created after cutoff date
        if (comment.get('author', {}).get('displayName') == sme_name and
            not comment.get('resolved', True) and
            comment.get('createdTime', '') > cutoff_date):

            content = comment.get('content', '')
            quoted_text = comment.get('quotedFileContent', {}).get('value', '')

            if content and quoted_text:
                filtered_comments.append((content, quoted_text))

    return filtered_comments


def process_comment_batch(batch):
    # Format all comments in batch into a single prompt
    comments_text = "\n\n".join([
        f"Comment {i+1}:\nComment: {comment}\nQuoted Text: {quoted_text}"
        for i, (comment, quoted_text) in enumerate(batch)
    ])

    prompt = [{
        "role": "system",
        "content": """Analyze each comment and categorize the issue as either:
        1. 'context' - suggesting adding/removing details to better comply with requirements
        2. 'mislocation' - content should be covered elsewhere
        3. other category if neither above applies
        
        For each comment, return a JSON object with fields: category, reasoning"""
    }, {
        "role": "user",
        "content": f"""Analyze these curriculum review comments:\n\n{comments_text}\n\n
        Return an array of analysis objects in this exact format:
        [
            {{
                "category": "context|mislocation|other",
                "reasoning": "Explanation of why this category was chosen",
                "comment": "Original comment text",
                "quoted_text": "Text that was quoted"
            }},
            ...etc for all {len(batch)} comments
        ]"""
    }]

    response = llm_complete(messages=prompt, model=LLM.GPT_4_O)
    analyses = ensure_json(response) # type: ignore

    return analyses


def categorize_comments(spreadsheet_id, analyse_comments_since, sme_name: str):
    comments_and_quoted_text = fetch_comments_and_cell_text(spreadsheet_id, analyse_comments_since, sme_name)
    # Split comments into batches of 20
    batch_size = 20
    batches = [comments_and_quoted_text[i:i + batch_size] for i in range(0, len(comments_and_quoted_text), batch_size)]

    # Process batches concurrently with 5 workers
    from concurrent.futures import ThreadPoolExecutor

    all_results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        batch_results = list(executor.map(process_comment_batch, batches))
        for results in batch_results:
            all_results.extend(results)

    # Group by category
    categorized = {}
    for result in all_results:
        category = result['category']
        if category not in categorized:
            categorized[category] = []
        categorized[category].append(result)

    # Print category counts
    print("\nCategory Counts:")
    for category, items in categorized.items():
        print(f"{category}: {len(items)}")

    # Save results
    with open('comment_analysis.json', 'w') as f:
        json.dump(categorized, f, indent=2)
    return categorized


def filter_and_enrich_with_l1(categorized_comments: Dict[str, List[dict]], sheet_id: str, sheet_name: str, l1_standard_column: int) -> List[dict]:
    """
    Process 'context' category comments to identify their L1 standards from column K

    Args:
        categorized_comments: Dictionary with comment categories as keys
        sheet: gspread worksheet object

    Returns:
        List of comments with L1 standard information added
    """
    logger.log_info("Starting to identify L1 standards for context comments")

    # Only process 'context' category
    if 'context' not in categorized_comments:
        logger.log_info("No context comments found")
        return []

    context_comments = categorized_comments['context']

    # Get all values from sheet
    client = initialize_gspread_client()
    sheet = get_gspread_sheet(client, sheet_id, sheet_name)
    all_values = sheet.get_all_values()

    processed_comments = []
    dropped_comments = []

    for comment in context_comments:
        quoted_text = comment.get('quoted_text', '')
        found = False

        # Search for quoted text in all values
        for row_idx, row in enumerate(all_values):
            # Join the row values to handle cases where text might span multiple columns
            row_text = ' '.join(str(cell) for cell in row)

            if quoted_text and quoted_text in row_text:
                # Get L1 standard from column K (index 10)
                l1_standard = row[l1_standard_column] if len(row) > l1_standard_column else ''

                if l1_standard:
                    comment['l1_standard'] = l1_standard
                    processed_comments.append(comment)
                    found = True
                    break

        if not found:
            dropped_comments.append(comment)
            logger.log_info(f"Could not find quoted text in sheet: {quoted_text}")


    logger.log_info(f"Processed {len(processed_comments)} comments")
    logger.log_info(f"Dropped {len(dropped_comments)} comments")

    return processed_comments


def generate_notes_for_context_pack(batch: List[Dict], subject: str) -> List[Dict]:
    prompt = [
        {
            "role": "system",
            "content": f"""
You are an expert in {subject} curriculum development. Analyze each comment to understand the SME's intent and provide enriching context.
The comment has been made in context of the quoted text. It can be very brief and make sense only along with the quoted text.
Your goal is to interpret and provide enriching context specific to the topics in the quoted text so that the next time we generate key-phrases for this l1 standard, we can provide better quality key-phrases.
Keep the enriching context brief and to the point without fluffy language. The context should be relevant to the quoted text and the L1 standard.
Some examples of enriching context can be : include x (as example/point etc) for <something>. define y. explain z. exclude a. Do <something> for <some_historic_term>. Do not do <something>. For <some_concept>, also explain <something_else> etc.
            """
        },
        {
            "role": "user",
            "content": f"""For each of the following {len(batch)} comments, provide the L1 standard and enriching context based on the SME's intent. 
            Return the results as a JSON array in the following format:
            [
                {{
                    "l1_standard": "The L1 standard",
                    "enriching_context": "The enriching context based on SME's intent",
                    "comment": "Original comment text",
                    "quoted_text": "Text that was quoted for the comment"
                }},
                ...
            ]

            Comments:
            """ + "\n\n".join([f"Comment {j+1}:\nComment: {comment['comment']}\nQuoted Text: {comment['quoted_text']}\nL1 Standard: {comment.get('l1_standard', 'Not provided')}"
                               for j, comment in enumerate(batch)])
        }
    ]

    response = llm_complete(messages=prompt, model=LLM.GPT_4_O)
    try:
        enriched_batch = ensure_json(response) # type: ignore
        if not isinstance(enriched_batch, list):
            raise ValueError("LLM response is not a list")
        return enriched_batch
    except (json.JSONDecodeError, ValueError) as e:
        logger.log_error(f"Failed to parse LLM response: {e}")
        return []


def process_comments_for_context_pack(processed_comments: List[Dict], subject: str, batch_size: int = 5) -> List[Dict]:
    logger.log_info(f"Processing {len(processed_comments)} comments for context enrichment")

    # Split comments into batches
    batches = [processed_comments[i:i+batch_size] for i in range(0, len(processed_comments), batch_size)]

    # Process batches concurrently with 10 workers
    with ThreadPoolExecutor(max_workers=10) as executor:
        enriched_batches = list(executor.map(lambda batch: generate_notes_for_context_pack(batch, subject), batches))

    # Combine results without modifying original processed_comments
    combined_enriched_comments = []
    for enriched_batch in enriched_batches:
        combined_enriched_comments.extend(enriched_batch)

    logger.log_info(f"Finished processing {len(combined_enriched_comments)} comments for context enrichment")
    return combined_enriched_comments


if __name__ == "__main__":
    # Categorize human comments and enrich with L1 standard after filtering
    spreadsheet_id = '1ZEO3A2CPyCS1dblkxEzInorfX9aWRS1ALTpW_iOF38g'
    metadata_sheet_name = 'metadata - v2'
    l1_standard_column_in_metadata = 6 # Column G (0-indexed)
    analyse_comments_since = '2024-10-24T00:00:00+00:00'
    sme_name = 'Jane Kelley'
    subject = 'AP World History'

    logger.log_info(f"Analyzing comments since {analyse_comments_since}")
    categorized_comments = categorize_comments(spreadsheet_id, analyse_comments_since, sme_name)
    logger.log_info(f"Filtering and enriching comments with L1 standard")
    processed_comments = filter_and_enrich_with_l1(categorized_comments, spreadsheet_id, metadata_sheet_name, l1_standard_column_in_metadata)

    # Process the comments to get notes for adding in context pack
    logger.log_info("Processing comments to generate context pack notes")
    context_pack_notes = process_comments_for_context_pack(processed_comments, subject)

    # Save enriched comments to a CSV file
    csv_filename = 'enriched_comments.csv'
    logger.log_info(f"Writing {len(context_pack_notes)} enriched comments to {csv_filename}")
    with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['l1_standard', 'enriching_context', 'comment', 'quoted_text']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for comment in context_pack_notes:
            writer.writerow(comment)

    logger.log_info(f"Saved {len(context_pack_notes)} enriched comments to '{csv_filename}'")

    # Manually review and edit the notes and update the context pack via append_feedback file
