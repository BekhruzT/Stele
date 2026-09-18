import os
from pathlib import Path

from dotenv import load_dotenv

# Every name below is read at import time, so .env has to be loaded before them. run.py
# already does this and load_dotenv does not override what is set, so this is a no-op for a
# normal run. It exists for the other two entry points -- a stage's own __main__ and the
# scripts under ops/ -- which have no chance to load anything before importing this module.
for _env in (Path(__file__).resolve().parent.parent / ".env",
             Path(__file__).resolve().parents[2] / ".env"):
    if _env.is_file():
        load_dotenv(_env)
        break


CONST_STRING_LENGTH = 128
CONST_TOKEN_LENGTH = 2048
CONST_PARAGRAPH_LENGTH = 4096

# Openai. Images, speech and transcription only; chat completions go to the gateway below.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ORGANIZATION_ID = os.getenv("OPENAI_ORGANIZATION_ID")

# TrueFoundry gateway
TFY_API_KEY = os.getenv("TFY_API_KEY")
TFY_BASE_URL = os.getenv("TFY_BASE_URL")

# aws resources
S3_BUCKET = os.getenv("S3_BUCKET")
S3_PATH = "teaching_content_path"
S3_BUCKET_UI = os.getenv("S3_BUCKET_UI")
S3_WEB_BASE_URL = f"http://{S3_BUCKET_UI}.s3-website-us-east-1.amazonaws.com"
# Publicly readable bucket for presenter portraits and character bundles. Separate from
# S3_BUCKET because the delivery platform fetches these by URL, so they cannot be private.
S3_MEDIA_BUCKET = os.getenv("S3_MEDIA_BUCKET")

# JSON request/response fields
GRADE = "grade"
SUBJECT = "subject"
CURRICULUM = "curriculum"
CLUSTER_ID = "cluster_id"
GUIDELINES = "guidelines"
TEACHING_PLAN = "teaching_plan"
TEACHING_CONTENT = "teaching_content"
REVIEW = "review"
S3_PATH = "s3_content_path"
TEACHING_CONTENT_JSON = "teaching_content_json"
SUMMARY = "summary"
ASSESSMENT = "assessment"

# Google Search API
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")

NGSS = "NGSS"
COMMON_CORE = "Common Core"

# Image Gen
MIDJOURNEY_LAMBDA_URL = "https://42g2uywyyy5qgxzx7vjcfdpdum0zdrvw.lambda-url.us-east-1.on.aws/"
MERMAID_LAMBDA_NAME = 'tiktok-api-prod-render-diagram'


TIKTOK_AWS_ACCESS_KEY_ID = os.getenv("TIKTOK_AWS_ACCESS_KEY_ID")
TIKTOK_AWS_SECRET_ACCESS_KEY = os.getenv("TIKTOK_AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

# Subjects
MATH = "math"
SCIENCE = "science"

GUIDELINES_PATH = os.getenv("GUIDELINES_PATH")
GUIDELINES_API_URL = os.getenv("GUIDELINES_API_URL")

# GCP
GCP_API_KEY = os.getenv("GCP_API_KEY")
GCP_SEARCH_CXID = os.getenv("GCP_SEARCH_CXID")

# Content Analysis
METRICS_RESULT_EXPORTER_URL = os.getenv("METRICS_RESULT_EXPORTER_URL")

# Fixer SQS
FIXER_SQS_URL = os.getenv("FIXER_SQS_URL")

# DDB Table Name
DDB_TABLE_NAME = os.getenv("DDB_TABLE_NAME")

# PDF
PAGE_HEIGHT = 1056  # 11in
PIXEL_SIZE = 96
PAGE_BODY_PADDING_BOTTOM = 20
PAGE_BODY_PADDING_TOP = 20

# D-ID
DID_API_KEY = os.getenv("DID_API_KEY")
FAL_KEY = os.getenv("FAL_KEY")

# Elevenlabs
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
