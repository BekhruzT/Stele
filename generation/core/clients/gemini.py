import os
import time
import datetime
from typing import List, Union
from core.clients.openai import user_message, LLM, log_llm_message
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=7, max=90))
def gemini_media_analysis(prompt: Union[List[str], str], media_path: str, model: LLM=LLM.GEMINI_2_5):
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel(model)

    uploaded_file = genai.upload_file(media_path)
    messages = ([prompt] if isinstance(prompt, str) else prompt) + [uploaded_file]

    chat = model.start_chat()
    attempt = 0
    response = None
    while attempt < 7:
        time.sleep(4)
        try:
            response = chat.send_message(messages).text
            break
        except Exception as e:
            # print(e)
            attempt += 1

    log_llm_message([user_message(message) for message in messages], response, 'gemini_video_analysis')

    return chat, response

def delete_old_gemini_files():
    files = list(genai.list_files())
    current_time = datetime.datetime.now(datetime.timezone.utc)

    if not files:
        print("No files found in storage.")
    else:
        print(f"Found {len(files)} files. Deleting...")
        for file in files:
            if current_time - file.update_time > datetime.timedelta(minutes=30):
                # print(f"Deleting file: {file.name}")
                try:
                    genai.delete_file(name=file.name)
                except:
                    continue
            else:
                print(f"File recently creating, not deleting: {file.update_time}")

        print("All files deleted.")