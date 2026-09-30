import logging
import os
from typing import Optional

import boto3
import requests
from core.log import \
    CloudWatchHandler
from core.clients.s3 import get_folder_link

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
    def __init__(self, directory: str, contexts: dict, thread_id: Optional[str] = None):
        self.directory = directory
        self.contexts = contexts
        self.thread_id = thread_id


    def send_initial_message(self):
        log_link = get_cloudwatch_stream() or "No log stream available"
        folder_link = get_folder_link(next(iter(self.contexts.values())).root)

        lesson_list = []
        for key, context in self.contexts.items():
            lesson_log_link = log_link + f'?filterPattern={{$.metadata.lesson_id={key}}}'
            lesson_list.append(f"[<{lesson_log_link}|{key}>] {context.title[:50]}{'...' if len(context.title) > 50 else ''}")

        initial_message = (
            f"🎬 Starting video generation for the {len(lesson_list)} videos:\n"
            f"\n* " + "\n* ".join(lesson_list) + "\n\n"
            f"🗂️ Folder: <{folder_link}|{self.directory}>\n"
            f"🔍 Progress can be tracked at: <{log_link}|Log Stream>"
        )
        if self.thread_id:
            send_gchat_message(initial_message, thread_id=self.thread_id)
        else:
            self.thread_id = send_gchat_message(initial_message)
        logger.info(f"Initial message sent to Google Chat. Thread ID: {self.thread_id}")


    def send_success_message(self, key):
        context = self.contexts[key]
        success_message = (
            f"✅ Video generated successfully! ({key})\n"
            f"<{get_folder_link(context.base_path)}|{context.title}>"
        )
        send_gchat_message(success_message, thread_id=self.thread_id)


    def send_error_message(self, key, error_message, error_traceback):
        # Send error message in thread
        error_message = (
            f"❌ Error generating video ({key})\n"
            f"⚠️ {self.contexts[key].title}\n\n"
            f"```\nError: {error_message}\n"
            f"{error_traceback}\n```"
        )
        send_gchat_message(error_message, thread_id=self.thread_id)