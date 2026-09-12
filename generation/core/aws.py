import boto3

def get_session():
    # Honours AWS_PROFILE (set to codenation-prod in .env) and falls back to the
    # "default" profile, so it no longer pins local runs to one hardcoded profile.
    return boto3.Session()
