import logging
import os
from functools import wraps
from typing import Optional

import boto3
import requests
from core.log import \
    CloudWatchHandler
from core.clients.s3 import load_json_from_s3, get_folder_link

logger = logging.getLogger(__name__)

def send_email(subject, body):
    RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')
    ses_client = boto3.client('ses', region_name='us-east-1')

    ses_client.send_email(
        Source=os.getenv('SENDER_EMAIL'),
        Destination={'ToAddresses': [RECIPIENT_EMAIL]},
        Message={
            'Subject': {'Data': subject},
            'Body': {'Text': {'Data': body}}
        }
    )

GOOGLE_CHAT_WEBHOOK_URL = os.getenv('GOOGLE_CHAT_WEBHOOK_URL') or ''
REGION = os.getenv('AWS_REGION')

def send_gchat_message(message: str, thread_id: Optional[str] = None) -> str:
    """
    Send a message to Google Chat.
    
    Args:
        message: The message to send
        thread_id: Optional thread ID to send message in
        
    Returns:
        str: The thread ID of the sent message
    """
    WEBHOOK_URL = GOOGLE_CHAT_WEBHOOK_URL
    headers = {"Content-Type": "application/json; charset=UTF-8"}
    payload = {'text': message}   
    if thread_id:
        payload['thread'] = {'name': thread_id}
        WEBHOOK_URL += "&messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
    
    response = requests.post(WEBHOOK_URL, json=payload, headers=headers)
    response.raise_for_status()
    
    # Extract thread ID from response
    response_data = response.json()
    thread_name = response_data.get('thread', {}).get('name')
    
    return thread_name

def get_cloudwatch_stream():
    """Get the CloudWatch log stream URL if available"""
    root_logger = logging.getLogger()
    cloudwatch_handler = next((handler for handler in root_logger.handlers 
                            if isinstance(handler, CloudWatchHandler)), None)
    
    if cloudwatch_handler:
        return (f"https://{REGION}.console.aws.amazon.com/cloudwatch/home?region={REGION}#logsV2:log-groups/"
                f"log-group/{cloudwatch_handler.log_group_name}/"
                f"log-events/{cloudwatch_handler.log_stream_name}")
    return None


class NotificationSystem:
    def __init__(self, event, keys, thread_id: Optional[str] = None):
        self.event = event
        self.keys = keys
        self.thread_id = thread_id


    def send_initial_message(self):
        log_link = get_cloudwatch_stream() or "No log stream available"
        exec_input = self.event['ExecutionInput']
        folder_link = get_folder_link(f"{exec_input['curriculum']}/{exec_input['course']}/{exec_input['subject']}")
        
        lesson_list = []
        for key, item in self.keys.items():
            lesson_log_link = log_link + f'?filterPattern={{$.metadata.lesson_id={key}}}'
            lesson_list.append(f"[<{lesson_log_link}|{key}>] {item['subsection'][:50]}{'...' if len(item['subsection']) > 50 else ''}")
        
        initial_message = (
            f"🎬 Starting video generation for the {len(lesson_list)} lessons:\n"
            f"\n* " + "\n* ".join(lesson_list) + "\n\n"
            f"🗂️ Folder: <{folder_link}|{exec_input['subject']}>\n"
            f"🔍 Progress can be tracked at: <{log_link}|Log Stream>"
        )
        if self.thread_id:
            send_gchat_message(initial_message, thread_id=self.thread_id)
        else:
            self.thread_id = send_gchat_message(initial_message)
        logger.info(f"Initial message sent to Google Chat. Thread ID: {self.thread_id}")


    def send_success_message(self, key):
        # Get video URL for the completed subsection
        video_json = load_json_from_s3(
            f"{self.event['ExecutionInput']['curriculum']}/{self.event['ExecutionInput']['course']}/"
            f"{self.event['ExecutionInput']['subject']}/contents/subsection/ShotStack/{key}.json"
        )
        video_url = video_json['lesson_video']['output_data'].get('url', None)
        sheet_link = video_json['lesson_video']['output_data'].get('sheet_link', None)
        
        # Send success message in thread
        success_message = (
            f"✅ Video generated successfully! ({key})"+
            (f" <{sheet_link}|Sheet Link>" if sheet_link else "")+
            (f"\n<{video_url.replace(' ', '%20')}|{self.keys[key]['subsection']}>" if video_url else "🚫 Video URL not found")
        )
        send_gchat_message(success_message, thread_id=self.thread_id)


    def send_error_message(self, key, error_message, error_traceback):
        # Send error message in thread
        error_message = (
            f"❌ Error generating video ({key})\n"
            f"⚠️ {self.keys[key]['subsection']}\n\n"
            f"```\nError: {error_message}\n"
            f"{error_traceback}\n```"
        )
        send_gchat_message(error_message, thread_id=self.thread_id)