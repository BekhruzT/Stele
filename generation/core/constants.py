import os
from pathlib import Path

from dotenv import load_dotenv

# Every name below is read at import time, so .env has to be loaded before them. run.py
# already does this and load_dotenv does not override what is set, so this is a no-op for a
# normal run. It exists for entry points such as the tools/ checks and a module's own
# __main__, which have no chance to load anything before importing this module.
for _env in (Path(__file__).resolve().parent.parent / ".env",
             Path(__file__).resolve().parents[2] / ".env"):
    if _env.is_file():
        load_dotenv(_env)
        break


# Openai. Images, speech and transcription only; chat completions go to the gateway below.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ORGANIZATION_ID = os.getenv("OPENAI_ORGANIZATION_ID")

# TrueFoundry gateway
TFY_API_KEY = os.getenv("TFY_API_KEY")
TFY_BASE_URL = os.getenv("TFY_BASE_URL")

# aws resources
S3_BUCKET = os.getenv("S3_BUCKET")

# Image Gen
MIDJOURNEY_LAMBDA_URL = "https://42g2uywyyy5qgxzx7vjcfdpdum0zdrvw.lambda-url.us-east-1.on.aws/"
MERMAID_LAMBDA_NAME = 'tiktok-api-prod-render-diagram'


TIKTOK_AWS_ACCESS_KEY_ID = os.getenv("TIKTOK_AWS_ACCESS_KEY_ID")
TIKTOK_AWS_SECRET_ACCESS_KEY = os.getenv("TIKTOK_AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

# GCP
GCP_API_KEY = os.getenv("GCP_API_KEY")
GCP_SEARCH_CXID = os.getenv("GCP_SEARCH_CXID")

# D-ID
DID_API_KEY = os.getenv("DID_API_KEY")

# Elevenlabs
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
