import os
import json
from typing import Dict, List
from core.google_api_utils import initialize_gspread_client
from core.google_api_utils import get_gspread_sheet
from core.clients.openai import llm_complete, ensure_json, LLM
import logging
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import FAISS
# Set up logging
from core.logger import Logger
logger = Logger(__name__, logging.DEBUG)

def gather_unit_level_los(sheet, start_row):
    logger.log_info(f"Gathering unit level learning objectives starting from row {start_row}")
    all_values = sheet.get_all_values()[start_row-1:]  # -1 because gspread is 1-indexed
    unit_los: Dict[str, Dict] = {}

    skipped_count = 0
    processed_count = 0

    for row in all_values:
        unit = row[6]  # Column G (0-indexed)
        l1 = row[9]    # Column J
        l3 = row[14]   # Column O
        l4 = row[16]   # Column Q
        lo = row[34]   # Column AI
        remove_l4 = row[47]  # Column AV
        frq_only = row[51]   # Column AZ

        if not unit or not lo:
            skipped_count += 1
            continue

        if remove_l4.strip() or frq_only.strip():
            skipped_count += 1
            continue

        # Initialize nested structure if needed
        if unit not in unit_los:
            unit_los[unit] = {}
        if l1 not in unit_los[unit]:
            unit_los[unit][l1] = {}
        if l3 not in unit_los[unit][l1]:
            unit_los[unit][l1][l3] = {}
        if l4 not in unit_los[unit][l1][l3]:
            unit_los[unit][l1][l3][l4] = []

        # Add learning objective
        unit_los[unit][l1][l3][l4].append(lo)
        processed_count += 1

    logger.log_info(f"Processed {processed_count} learning objectives, skipped {skipped_count} rows")

    # Print count of LOs in each unit
    for unit, unit_data in unit_los.items():
        lo_count = sum(
            len(los) 
            for l1_data in unit_data.values()
            for l3_data in l1_data.values()
            for los in l3_data.values()
        )
        logger.log_info(f"Unit {unit}: {lo_count} learning objectives")

    return unit_los

def cluster_learning_objectives(unit_data: Dict) -> List[List[str]]:
    logger.log_info("Clustering learning objectives")
    embeddings = OpenAIEmbeddings()

    # Flatten the nested structure into a list of learning objectives with metadata
    los = []
    metadatas = []
    for l1, l1_data in unit_data.items():
        for l3_data in l1_data.values():
            for l4_los in l3_data.values():
                for lo in l4_los:
                    los.append(lo)
                    metadatas.append({"l1": l1})

    # Create in-memory FAISS index
    try:
        vectorstore = FAISS.from_texts(
            texts=los,
            embedding=embeddings,
            metadatas=metadatas
        )
        logger.log_info(f"Successfully created FAISS index with {len(los)} learning objectives")
    except Exception as e:
        logger.log_error(f"Error creating FAISS index: {e}")
        raise e

    # Fetch clusters of similar documents using similarity search
    logger.log_info("Finding clusters of similar learning objectives")
    clusters = []
    processed = set()
    
    for i, lo in enumerate(los):
        if i in processed:
            continue
            
        # Find similar documents for this learning objective
        similar_docs = vectorstore.similarity_search_with_score(lo, k=5)
        
        # Filter for documents with high similarity (low distance)
        similarity_threshold = 0.15
        cluster = []
        for doc, score in similar_docs:
            if score < similarity_threshold:
                # Get original index of this document
                doc_idx = los.index(doc.page_content)
                cluster.append(doc_idx)
                processed.add(doc_idx)
                
        if len(cluster) > 1:  # Only keep clusters with multiple documents
            clusters.append([los[idx] for idx in cluster])
            
    logger.log_info(f"Found {len(clusters)} clusters of similar learning objectives")
    return clusters

def group_similar_los(unit_los: Dict[str, Dict]) -> Dict[str, List[List[str]]]:
    grouped_los = {}
    for unit, unit_data in unit_los.items():
        logger.log_info(f"Processing clusters for Unit {unit}")
        grouped_los[unit] = cluster_learning_objectives(unit_data)
        # break  # Only process the first unit for now
    return grouped_los

def determine_lo_clusters_via_embeddings(sheet, cluster_output_file, start_row):
    if os.path.exists(cluster_output_file):
        logger.log_info(f"Loading existing grouped learning objectives from {cluster_output_file}")
        with open(cluster_output_file, 'r') as f:
            grouped_los = json.load(f) 
    else:    
        logger.log_info("No existing grouped learning objectives found. Processing from sheet...")
        
        unit_los = gather_unit_level_los(sheet, start_row)
        # Group similar learning objectives
        logger.log_info("Starting to group similar learning objectives")
        grouped_los = group_similar_los(unit_los)
        
        with open(cluster_output_file, 'w') as f:
            json.dump(grouped_los, f, indent=2)

        logger.log_info(f"Successfully saved grouped unit-level learning objectives to '{cluster_output_file}'")
    return grouped_los


def update_sheet_with_clusters(sheet, grouped_los, start_row, subject):
    all_values = sheet.get_all_values()[start_row-1:]
    lo_to_row = {f"{row[34]}": idx for idx, row in enumerate(all_values) if row[34]}

    for unit, clusters in grouped_los.items():
        for cluster_idx, cluster in enumerate(clusters):
            # Group LOs by L1 standard
            l1_groups = {}
            for lo in cluster:
                if lo in lo_to_row:
                    row = lo_to_row[lo]
                    l1_standard = all_values[row][10]  # Column K
                    if l1_standard not in l1_groups:
                        l1_groups[l1_standard] = []
                    l1_groups[l1_standard].append(lo)
                else:
                    logger.log_info(f"Learning objective '{lo}' not found in sheet")
                    continue

            # If LOs belong to different L1 standards
            if len(l1_groups) > 1:
                logger.log_info(f"Cluster contains LOs from multiple L1 standards, sending to LLM for decision")
                # Prepare message for LLM
                messages = [
                    {"role": "system", "content": f"You are an expert in {subject} and helping analyzing learning objectives and determining redundancy."},
                    {"role": "user", "content": f"I have identified potentially redundant learning objectives grouped by their L1 standards:\n\n{json.dumps(l1_groups, indent=2)}\n\nAre these learning objectives truly redundant? If yes, which group should be kept based on which is more suitable home based on the scope of l1 standard and assuming student is going through the course in order of l1 standard prescribed by the college board? Please respond in JSON format with two fields: 'are_redundant' (boolean) and 'keep_group' (L1 standard key to keep). Return only the json and nothing else"}
                ]
                
                response = llm_complete(messages, model=LLM.GPT_5)
                try:
                    llm_decision = ensure_json(response) # type: ignore
                    if llm_decision['are_redundant']: # type: ignore
                        cluster_id = f"{unit}.{cluster_idx + 1}"
                        # Update sheet for all LOs, marking only those not in the kept group for blacklist
                        for l1_standard, los in l1_groups.items():
                            for lo in los:
                                row = lo_to_row[lo]
                                if l1_standard != llm_decision['keep_group']: # type: ignore
                                    sheet.update_cell(row + start_row, 54, 'blacklist')  # Column BB
                                sheet.update_cell(row + start_row, 55, cluster_id)   # Column BC
                        logger.log_info(f"LLM determined LOs are redundant, marked cluster {cluster_id} for blacklist")
                    else:
                        logger.log_info(f"LLM determined LOs are not actually redundant, skipping cluster")
                        for lo in cluster:
                            print(lo)
                        print('---')
                except json.JSONDecodeError:
                    logger.log_error(f"Failed to parse LLM response: {response}")
            else:
                # All LOs belong to same L1 standard, proceed with original logic
                cluster_id = f"{unit}.{cluster_idx + 1}"
                print(f"Cluster belongs to same l1: {cluster_id}")
                for lo in cluster:
                    print(lo)
                print('---')
            
        
def identify_and_blacklist_lo(spreadsheet_id, sheet_name, start_row, subject):
    client = initialize_gspread_client()
    sheet = get_gspread_sheet(client, spreadsheet_id, sheet_name)
    cluster_output_file = 'unit_level_los_grouped.json'
    # Check if output file already exists
    clustered_los = determine_lo_clusters_via_embeddings(sheet, cluster_output_file, start_row)
    update_sheet_with_clusters(sheet, clustered_los, start_row, subject)

def main():
    logger.log_info("Starting learning objectives gathering process")
    spreadsheet_id = '1ZEO3A2CPyCS1dblkxEzInorfX9aWRS1ALTpW_iOF38g'
    los_sheet_name = 'obscured objectives'  # copy the data model to your own sheet and update the sheet name here
    start_row = 5  # The row where the data starts in the sheet
    # Gather learning objectives and cluster them on similarity, then update the sheet by marking redundant LOs
    subject = 'AP World History'
    identify_and_blacklist_lo(spreadsheet_id, los_sheet_name, start_row, subject)

    

if __name__ == "__main__":
    main()
