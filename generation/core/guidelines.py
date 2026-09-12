import re
from typing import List, Dict

from core.path import get_full_guidelines_path
from core.clients.s3 import load_json_from_s3, upload_file_to_s3


HIERARCHY_LEVELS = [
    'Standards Organization',
    'Course',
    'Category',
    'Domain',
    'Cluster',
    'Standard Description (L1)',
    'Standard Description (L2)',
    'Standard Description (L3)',
    'Standard Description Plus',
    'Standard Description',
    "Concept"
]


def extract_by_key(data, pattern):
    values = []
    for key in data.keys():
        if re.search(pattern, key) and data[key]:
            values.append(data[key])
    return list(set(values))


def extract_concepts(data):
    return extract_by_key(data, r"Key Concept \d+")


def extract_skills(data):
    return extract_by_key(data, r"Skill \d+ Description")


def fetch_guidelines(course, curriculum, subject):
    guidelines_path = get_full_guidelines_path()
    if 'Video' in course:
        guidelines_path = f'{curriculum}/{course}/{subject}/guidelines.json'
    guidelines = load_json_from_s3(guidelines_path)
    response = [guideline for guideline in guidelines if guideline.get("Course") == course and guideline.get("Standards Organization") == curriculum and guideline.get("Subject") == subject]
    if not response and guidelines:
        return guidelines  # assumes the guidelines are filtered and for this input only
    else:
        return response


def transform_into_hierarchial_data(rows):
    hierarchial_data = {}
    for index, row in enumerate(rows, start=1):
        current = hierarchial_data
        for level in HIERARCHY_LEVELS:
            if row.get(level):
                current.setdefault(row[level], {})
                current = current[row[level]]
        current["ConceptId"] = index
    return hierarchial_data


def flatten_concepts(guidelines: List[Dict]):
    concepts = []
    for guideline in guidelines:
        key_concepts = extract_concepts(guideline)
        for key_concept in key_concepts:
            row = {key: value for key, value in guideline.items() if key in HIERARCHY_LEVELS}
            row["Concept"] = key_concept
            concepts.append(row)
    return concepts

# these functions are to be manually run to come up with guidelines.json and placed in the bucket.
# This because we do not generate key-concepts as evident from config due to missing "key-concepts" field.
# the output structure of guidelines is determined by what lesson plan processors expect, which we will make config based now in videos project.

import csv
import json

def combine_headers(header_rows):
    combined_header = []
    for header_row in header_rows:
        for i, header in enumerate(header_row):
            if len(combined_header) <= i:
                combined_header.append(header)
            else:
                combined_header[i] += header
    return combined_header

def parse_csv_with_combined_header(csv_file_path, json_file_path):
    with open(csv_file_path, mode='r', encoding='utf-8-sig') as csv_file:
        csv_reader = csv.reader(csv_file)
        
        # Read the first three rows to combine into a single header
        header_rows = [next(csv_reader) for _ in range(4)]
        # Drop the first row
        header_rows = header_rows[1:]
        
        combined_header = []
        for col in zip(*header_rows):
            header = ' | '.join(filter(None, col))
            combined_header.append(header)
        
        # Read the remaining rows as data
        data = []
        for row in csv_reader:
            if any(row):  # Skip empty rows
                data.append(dict(zip(combined_header, row)))
    
    # Write the data to a JSON file
    with open(json_file_path, 'w', encoding='utf-8') as json_file:
        json.dump(data, json_file, indent=4, ensure_ascii=False)

    # Process the data into a new structure
    def process_data(data):
        processed_data = {}
        for item in data:
            
            if item.get("Remove L4 | Remove L4", ""):
                print(f'Skipping for remove l4: {item.get("Learning Objectives")}')
                continue
            if item.get("FRQ Only | FRQ Only",""):
                print(f'Skipping for FRQ only: {item.get("Learning Objectives")}')
                continue
            if item.get("llm-blacklist-decision", ""):
                print(f'Skipping for llm-blacklist-decision: {item.get("Learning Objectives")}')
                continue
            if item.get("human-blacklist-decision", ""):
                print(f'Skipping for human-blacklist-decision: {item.get("Learning Objectives")}')
                continue
            chapter = item.get("Domain")
            unit = item.get("Subject")
            
            filtered_item = {
                "Cluster": item.get("Cluster", ""),
                "Standard Description (L1)": item.get("Standard Description (L1)", ""),
                "Standard Description (L2)": item.get("Standard Description (L2)", ""),
                "Standard Description (L3)": item.get("Standard Description (L3)", ""),
                "Standard Description Plus": item.get("Standard Description Plus", ""),
                "Concept": item.get("Learning Objectives", ""),
                "Common Misconception 1": item.get("Common Misconceptions | Common Misconception 1", ""),
                "Common Misconception 2": item.get("Common Misconception 2", ""),
                "Common Misconception 3": item.get("Common Misconception 3", ""),
                "Common Misconception 4": item.get("Common Misconception 4", ""),
                "BoundaryNotes": item.get("Assessment Boundaries", ""),
                "DomainId": item.get("Domain Id", ""),
                "ClusterId": item.get("Cluster Id", ""),
                "StandardId": item.get("Standard Id (L1)", ""),
            }
            if not any(filtered_item.values()) or not (chapter or unit):
                continue

            if (chapter, unit) not in processed_data:
                processed_data[(chapter, unit)] = {
                    "chapter": chapter,
                    "unit": unit,
                    "concepts": []
                }
            processed_data[(chapter, unit)]["concepts"].append(filtered_item)
        
        # Convert the dictionary to a list
        return list(processed_data.values())

    # Write the processed data to a new JSON file
    def write_processed_data(processed_data, output_file_path):
        with open(output_file_path, 'w', encoding='utf-8') as json_file:
            json.dump(processed_data, json_file, indent=4, ensure_ascii=False)

    # Process the data and write to a new file
    processed_data = process_data(data)
    processed_json_file_path = './processed_guidelines.json'
    write_processed_data(processed_data, processed_json_file_path)

    print(f"Processed data has been written to {processed_json_file_path}")
    return processed_json_file_path
    
    



if __name__ == "__main__":
    # Example usage
    csv_file_path = './Curriculum Data Model Generator - AP Biology - Data Model.csv'
    json_file_path = './guidelines.json'

    course = "AP Biology: Video Lessons"
    subject = "AP Biology"

    guidelines_path = parse_csv_with_combined_header(csv_file_path, json_file_path)
    upload_file_to_s3(
        guidelines_path,
        f'college_board/{course}/{subject}/guidelines.json'
    )
