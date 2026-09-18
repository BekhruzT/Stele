from typing import List, Dict, Tuple
from core.helpers import split_transcript, get_topics_list
from concurrent.futures import ThreadPoolExecutor
from core.types import TranscriptTiming
from core.clients.s3 import load_json_from_s3, does_file_exist, list_files_in_directory
from core.context import APVideoContext as Context, prep_content_gen_input
import json
from tqdm import tqdm
import matplotlib.pyplot as plt


def get_time_stats(transcript_json: dict, avatar_json: dict, text_overlays_json: dict) -> dict:
    transcript_timings = TranscriptTiming(timings=avatar_json['lesson_timings'])
    transcript_intro = transcript_json['lesson_transcript_sections']['introduction']
    transcript_main = transcript_json['lesson_transcript_sections']['main']
    transcript_conclusion = transcript_json['lesson_transcript_sections']['conclusion']

    transcript_split_intro = split_transcript(transcript_intro)
    transcript_split_main = split_transcript(transcript_main)
    transcript_split_conclusion = split_transcript(transcript_conclusion)

    start_index_intro = transcript_split_intro[0]['word_count_range'][0]
    end_index_intro = transcript_split_intro[-1]['word_count_range'][1] - 1
    start_index_main = transcript_split_main[0]['word_count_range'][0] + end_index_intro + 1
    end_index_main = transcript_split_main[-1]['word_count_range'][1] + end_index_intro
    start_index_conclusion = transcript_split_conclusion[0]['word_count_range'][0] + end_index_main + 1
    end_index_conclusion = transcript_split_conclusion[-1]['word_count_range'][1] + end_index_main

    # print(f"INTRO")
    # print(f"Start word: {transcript_timings.timings[start_index_intro].text }, index: {start_index_intro}")
    # print(f"End word: {transcript_timings.timings[end_index_intro].text}, index: {end_index_intro}  ")
    # print(f"MAIN")
    # print(f"Start word: {transcript_timings.timings[start_index_main].text}, index: {start_index_main}")
    # print(f"End word: {transcript_timings.timings[end_index_main].text}, index: {end_index_main}")
    # print(f"CONCLUSION")
    # print(f"Start word: {transcript_timings.timings[start_index_conclusion].text}, index: {start_index_conclusion}")
    # print(f"End word: {transcript_timings.timings[end_index_conclusion].text}, index: {end_index_conclusion}")

    start_time_intro = transcript_timings.timings[start_index_intro].start_time
    end_time_intro = transcript_timings.timings[end_index_intro].end_time
    start_time_main = transcript_timings.timings[start_index_main].start_time
    end_time_main = transcript_timings.timings[end_index_main].end_time
    start_time_conclusion = transcript_timings.timings[start_index_conclusion].start_time
    end_time_conclusion = transcript_timings.timings[end_index_conclusion].end_time

    # print("\n--------------------------------\n")
    # print(f"INTRO:")
    # print(f"Start time: {start_time_intro}, end time: {end_time_intro}")
    # print(f"MAIN:")
    # print(f"Start time: {start_time_main}, end time: {end_time_main}")
    # print(f"CONCLUSION:")
    # print(f"Start time: {start_time_conclusion}, end time: {end_time_conclusion}")

    key_phrase_time = 0
    for key_phrase in text_overlays_json['key_phrases']:
        key_phrase_time += key_phrase['end_time'] - key_phrase['start_time']

    # print("\n--------------------------------\n")
    # print(f"Key phrase overlay time: {key_phrase_overlay_time}")

    intro_time = end_time_intro - start_time_intro
    main_time = end_time_main - start_time_main
    conclusion_time = end_time_conclusion - start_time_conclusion
    total_time = end_time_conclusion - start_time_intro
    intro_percentage = intro_time / total_time
    main_percentage = main_time / total_time
    conclusion_percentage = conclusion_time / total_time
    key_phrase_percentage = key_phrase_time / main_time

    return {
        "intro_time": intro_time,
        "main_time": main_time,
        "conclusion_time": conclusion_time,
        "total_time": total_time,
        "key_phrase_time": key_phrase_time,
        "intro_percentage": intro_percentage,
        "main_percentage": main_percentage,
        "conclusion_percentage": conclusion_percentage,
        "key_phrase_percentage": key_phrase_percentage
    }


def get_layer_path(layer_type: str, key: str):
    base = f"{execution_input['curriculum']}/{execution_input['course']}/{execution_input['subject']}/contents/subsection/{layer_type}/"
    if does_file_exist(base + f"{key}-edited.json"):
        return base + f"{key}-edited.json"
    elif does_file_exist(base + f"{key}.json"):
        return base + f"{key}.json"
    else:
        return None


if __name__ == "__main__":
    execution_input = {
        "curriculum": "college_board",
        "course": "AP World History: Video Lessons",
        "grade": "Grade 11",
        "subject": "AP World History - Unit 2",
        "category": "High School: AP World History: Modern"
    }
        

    # ====================================== FETCHING GENERATED LESSONS ======================================
    print("Fetching generated lessons...")
    context_mappings = {}
    generated_lessons = []

    lesson_datas = []
    curriculum_data = get_topics_list(execution_input)
    units = list(curriculum_data["Units"].keys())
    for unit in units:
        chapters = list(curriculum_data["Units"][unit]["Chapters"].keys())
        for chapter in chapters:
            sections = list(curriculum_data["Units"][unit]["Chapters"][chapter]["Sections"].keys())
            for section in sections:
                subsections = curriculum_data["Units"][unit]["Chapters"][chapter]["Sections"][section]
                for subsection in subsections:
                    input_dict = {
                        "unit": unit,
                        "chapter": chapter,
                        "section": section,
                        "subsection": subsection
                    }
                    data = {
                        "ExecutionInput": execution_input,
                        "Input": input_dict
                    }
                    lesson_datas.append(data)
    print(f" - Curriculum data for all {len(lesson_datas)} lessons fetched.")

    def process_lesson_data(lesson_data):
        context = Context(**prep_content_gen_input(lesson_data))
        context_mappings[context.key] = context
        transcript_path = get_layer_path("Video Transcript", context.key)
        avatar_path = get_layer_path("Avatar Clips", context.key)
        text_overlays_path = get_layer_path("Text Overlays", context.key)
        render_path = get_layer_path("Local Render", context.key)
        if transcript_path and avatar_path and text_overlays_path and render_path:
            return {
                "key": context.key,
                "transcript_path": transcript_path,
                "avatar_path": avatar_path,
                "text_overlays_path": text_overlays_path,
                "render_path": render_path
            }
        return None
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(tqdm(
            executor.map(process_lesson_data, lesson_datas),
            total=len(lesson_datas),
            desc=" - Filtering generated lessons"
        ))
    generated_lessons = [result for result in results if result is not None]
    print(f" - {len(generated_lessons)} generated lessons filtered")


    # ====================================== GETTING TIME STATS ======================================
    print("Getting time stats...")
    def process_lesson_stats(lesson):
        stats = get_time_stats(
            load_json_from_s3(lesson["transcript_path"]), 
            load_json_from_s3(lesson["avatar_path"]), 
            load_json_from_s3(lesson["text_overlays_path"])
        )
        return {
            "key": lesson["key"],
            "stats": stats
        }
    with ThreadPoolExecutor(max_workers=10) as executor:
        lesson_stats = list(tqdm(
            executor.map(process_lesson_stats, generated_lessons),
            total=len(generated_lessons),
            desc=" - Calculating stats"
        ))
    print(f" - Finished getting time stats for {len(lesson_stats)} lessons")


    # ====================================== SAVING STATS ======================================
    with open("time_stats.json", "w") as file:
        file.write(json.dumps(lesson_stats, indent=4))
    print("\nStats saved to time_stats.json")


    # ====================================== PRINTING STATS ======================================
    def format_time(seconds):
        minutes = int(seconds // 60)
        remaining_seconds = seconds % 60
        return f"{minutes}:{remaining_seconds:02.0f}"

    def print_and_write(file, string):
        print(string)
        file.write(string + "\n")


    average_intro_time = sum([stat["stats"]["intro_time"] for stat in lesson_stats]) / len(lesson_stats)
    average_main_time = sum([stat["stats"]["main_time"] for stat in lesson_stats]) / len(lesson_stats)
    average_conclusion_time = sum([stat["stats"]["conclusion_time"] for stat in lesson_stats]) / len(lesson_stats)
    average_total_time = sum([stat["stats"]["total_time"] for stat in lesson_stats]) / len(lesson_stats)
    average_key_phrase_time = sum([stat["stats"]["key_phrase_time"] for stat in lesson_stats]) / len(lesson_stats)
    average_key_phrase_percentage = sum([stat["stats"]["key_phrase_percentage"] for stat in lesson_stats]) / len(lesson_stats)
    average_intro_percentage = sum([stat["stats"]["intro_percentage"] for stat in lesson_stats]) / len(lesson_stats)
    average_main_percentage = sum([stat["stats"]["main_percentage"] for stat in lesson_stats]) / len(lesson_stats)
    average_conclusion_percentage = sum([stat["stats"]["conclusion_percentage"] for stat in lesson_stats]) / len(lesson_stats)
    with open('time_stats.txt', 'w') as file:
        print_and_write(file, f"PRIMARY STATS: ({len(lesson_stats)} lessons)\n")
        print_and_write(file, f" - Average total time: {format_time(average_total_time)}")
        print_and_write(file, f" - Average intro time: {format_time(average_intro_time)} | [{average_intro_percentage:.2%} of total]")
        print_and_write(file, f" - Average main time: {format_time(average_main_time)} | [{average_main_percentage:.2%} of total]")
        print_and_write(file, f" - Average conclusion time: {format_time(average_conclusion_time)} | [{average_conclusion_percentage:.2%} of total]")
        print_and_write(file, f" - Average key phrase time: {format_time(average_key_phrase_time)} | [{average_key_phrase_percentage:.2%} of main part]")
    print("\nPrimary stats saved to time_stats.txt")

    # ====================================== PLOTTING STATS =======================================
    # Create a figure with 6 subplots in a 3x2 grid
    fig, axes = plt.subplots(3, 2, figsize=(15, 20))

    # Row 1: Total Times & Key Phrase Percentage
    axes[0,0].hist([stat["stats"]["total_time"] for stat in lesson_stats], bins=20, edgecolor='black')
    axes[0,0].set_xlabel('Total Time (min:sec)')
    axes[0,0].set_ylabel('Frequency')
    axes[0,0].set_title('Distribution of Total Times')
    ticks = axes[0,0].get_xticks()
    axes[0,0].set_xticks(ticks)  # Set the tick positions explicitly
    axes[0,0].set_xticklabels([format_time(t) for t in ticks])

    axes[0,1].hist([stat["stats"]["key_phrase_percentage"] for stat in lesson_stats], bins=20, edgecolor='black', color='orange')
    axes[0,1].set_xlabel('Key Phrase Percentage (against main time)')
    axes[0,1].set_ylabel('Frequency')
    axes[0,1].set_title('Distribution of Key Phrase Percentage')
    ticks = axes[0,1].get_xticks()
    axes[0,1].set_xticks(ticks)  # Set the tick positions explicitly
    axes[0,1].set_xticklabels([f'{x:.1%}' for x in ticks])

    # Row 2: Intro Times & Percentages
    axes[1,0].hist([stat["stats"]["intro_time"] for stat in lesson_stats], bins=20, edgecolor='black')
    axes[1,0].set_xlabel('Intro Time (min:sec)')
    axes[1,0].set_ylabel('Frequency')
    axes[1,0].set_title('Distribution of Intro Times')
    ticks = axes[1,0].get_xticks()
    axes[1,0].set_xticks(ticks)  # Set the tick positions explicitly
    axes[1,0].set_xticklabels([format_time(t) for t in ticks])

    axes[1,1].hist([stat["stats"]["intro_percentage"] for stat in lesson_stats], bins=20, edgecolor='black', color='orange')
    axes[1,1].set_xlabel('Intro Time Percentage (against total time)')
    axes[1,1].set_ylabel('Frequency')
    axes[1,1].set_title('Distribution of Intro Time Percentage')
    ticks = axes[1,1].get_xticks()
    axes[1,1].set_xticks(ticks)  # Set the tick positions explicitly
    axes[1,1].set_xticklabels([f'{x:.1%}' for x in ticks])

    # Row 3: Conclusion Times & Percentages
    axes[2,0].hist([stat["stats"]["conclusion_time"] for stat in lesson_stats], bins=20, edgecolor='black')
    axes[2,0].set_xlabel('Conclusion Time (min:sec)')
    axes[2,0].set_ylabel('Frequency')
    axes[2,0].set_title('Distribution of Conclusion Times')
    ticks = axes[2,0].get_xticks()
    axes[2,0].set_xticks(ticks)  # Set the tick positions explicitly
    axes[2,0].set_xticklabels([format_time(t) for t in ticks])

    axes[2,1].hist([stat["stats"]["conclusion_percentage"] for stat in lesson_stats], bins=20, edgecolor='black', color='orange')
    axes[2,1].set_xlabel('Conclusion Time Percentage (against total time)')
    axes[2,1].set_ylabel('Frequency')
    axes[2,1].set_title('Distribution of Conclusion Time Percentage')
    ticks = axes[2,1].get_xticks()
    axes[2,1].set_xticks(ticks)  # Set the tick positions explicitly
    axes[2,1].set_xticklabels([f'{x:.1%}' for x in ticks])

    # Adjust layout to prevent overlap
    plt.tight_layout()
    plt.savefig('time_stats.png',
        dpi=300,
        bbox_inches='tight',
        format='png'
    )
    plt.show()
    print("\nTime stats plot saved to time_stats.png")

    # ====================================== GETTING EXTREMES ======================================

    file = open('time_stats.txt', 'a+')
    print_and_write(file, "\n\nEXTREMES:")

    # shortest and longest lessons
    sorted_lessons = sorted(lesson_stats, key=lambda x: x["stats"]["total_time"])
    print_and_write(file, "\n\nShortest 3 lessons:")
    for i in range(3):
        total_time = sorted_lessons[i]['stats']['total_time']
        context = context_mappings[sorted_lessons[i]['key']]
        print_and_write(file, f"{i+1}) [{format_time(total_time)}] - {context.subsection.strip('.')}")
        print_and_write(file, f"   [{context.unit}] [{context.chapter}] [{context.section}]")
    print_and_write(file, "\nLongest 3 lessons:")
    for i in range(1, 4):
        total_time = sorted_lessons[-i]['stats']['total_time']
        context = context_mappings[sorted_lessons[-i]['key']]
        print_and_write(file, f"{i+1}) [{format_time(total_time)}] - {context.subsection.strip('.')}")
        print_and_write(file, f"   [{context.unit}] [{context.chapter}] [{context.section}]")

    # shortest and longest intro times
    sorted_lessons = sorted(lesson_stats, key=lambda x: x["stats"]["intro_time"])
    print_and_write(file, "\n\nShortest 3 intro times:")
    for i in range(3):
        intro_time = sorted_lessons[i]['stats']['intro_time']
        context = context_mappings[sorted_lessons[i]['key']]
        print_and_write(file, f"{i+1}) [{format_time(intro_time)}] - {context.subsection.strip('.')}")
        print_and_write(file, f"   [{context.unit}] [{context.chapter}] [{context.section}]")
    print_and_write(file, "\nLongest 3 intro times:")
    for i in range(1, 4):
        intro_time = sorted_lessons[-i]['stats']['intro_time']
        context = context_mappings[sorted_lessons[-i]['key']]
        print_and_write(file, f"{i+1}) [{format_time(intro_time)}] - {context.subsection.strip('.')}")
        print_and_write(file, f"   [{context.unit}] [{context.chapter}] [{context.section}]")

        # shortest and longest conclusion percentages
    sorted_lessons = sorted(lesson_stats, key=lambda x: x["stats"]["conclusion_percentage"])
    print_and_write(file, "\n\nShortest 3 conclusion percentages:")
    for i in range(3):
        conclusion_percentage = sorted_lessons[i]['stats']['conclusion_percentage']
        context = context_mappings[sorted_lessons[i]['key']]
        print_and_write(file, f"{i+1}) [{conclusion_percentage:.2%}] - {context.subsection.strip('.')}")
        print_and_write(file, f"   [{context.unit}] [{context.chapter}] [{context.section}]")
    print_and_write(file, "\nLongest 3 conclusion percentages:")
    for i in range(1, 4):
        conclusion_percentage = sorted_lessons[-i]['stats']['conclusion_percentage']
        context = context_mappings[sorted_lessons[-i]['key']]
        print_and_write(file, f"{i+1}) [{conclusion_percentage:.2%}] - {context.subsection.strip('.')}")
        print_and_write(file, f"   [{context.unit}] [{context.chapter}] [{context.section}]")

    # highest and lowest key phrase percentages
    sorted_lessons = sorted(lesson_stats, key=lambda x: x["stats"]["key_phrase_percentage"])
    print_and_write(file, "\n\nLowest 3 key phrase percentages:")
    for i in range(3):
        key_phrase_percentage = sorted_lessons[i]['stats']['key_phrase_percentage']
        context = context_mappings[sorted_lessons[i]['key']]
        print_and_write(file, f"{i+1}) [{key_phrase_percentage:.2%}] - {context.subsection.strip('.')}")
        print_and_write(file, f"   [{context.unit}] [{context.chapter}] [{context.section}]")
    print_and_write(file, "\nHighest 3 key phrase percentages:")
    for i in range(1, 4):
        key_phrase_percentage = sorted_lessons[-i]['stats']['key_phrase_percentage']
        context = context_mappings[sorted_lessons[-i]['key']]
        print_and_write(file, f"{i+1}) [{key_phrase_percentage:.2%}] - {context.subsection.strip('.')}")
        print_and_write(file, f"   [{context.unit}] [{context.chapter}] [{context.section}]")

    file.close()
    print("\nExtremes saved to time_stats.txt")
