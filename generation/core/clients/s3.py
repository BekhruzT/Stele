import botocore
import json
import os
import re
import boto3
import logging
from core.constants import S3_BUCKET, AWS_REGION
from core.local import list_files
from core.aws import get_session
from core.misc import detect_content_type
from typing import Optional

logger = logging.getLogger(__name__)


def is_local() -> bool:
    """Whether artifacts live on disk rather than in S3. The single source of truth for the
    mode, used both by the rebinding at the bottom of this file and by the handful of stages
    that must skip a vendor call rather than just redirect a read or a write."""
    return os.getenv("STORAGE", "s3").strip().lower() == "local"


def get_s3_resource():
    session = get_session()
    s3 = session.resource('s3')
    return s3


def get_s3_client():
    session = get_session()
    return session.client('s3', config=botocore.config.Config(signature_version='s3v4'))

def get_last_modified_time(key: str):
    s3_client = get_s3_client()
    response = s3_client.head_object(Bucket=S3_BUCKET, Key=key)
    return response['LastModified']

def list_files_in_directory(directory, return_type: str = 'full_path'):
    s3 = boto3.client('s3')
    paginator = s3.get_paginator('list_objects_v2')
    file_list = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=directory):
        for obj in page['Contents']:
            if return_type == 'full_path':
                file_list.append(obj['Key'])
            else:
                file_list.append(os.path.basename(obj['Key']))
    return file_list


def create_presigned_url(key, bucket = 'gen-ai-textbooks-dev', expiration=3600, url_style='path'):
    from urllib.parse import urlparse, urlunparse
    s3_client = get_s3_client()
    try:
        response = s3_client.generate_presigned_url('get_object',
                                                    Params={'Bucket': bucket,
                                                            'Key': key},
                                                    ExpiresIn=expiration)
    except botocore.exceptions.ClientError as e:
        logging.error(e)
        return None

    if url_style == 'path':
        return response
    
    # Convert the "path-style" URL to a "virtual-hosted–style" URL
    url_parts = urlparse(response)
    bucket = url_parts.netloc.split('.')[0]
    new_netloc = url_parts.netloc.replace(f'{bucket}.', '')
    new_path = url_parts.path.replace(f'/{bucket}', '')
    new_url = urlunparse((url_parts.scheme, new_netloc, new_path,
                         url_parts.params, url_parts.query, url_parts.fragment))

    return new_url


def download_directory(s3_directory, local_directory):
    s3_resource = get_s3_resource()
    bucket = s3_resource.Bucket(S3_BUCKET)
    for obj in bucket.objects.filter(Prefix=s3_directory):
        file_name = obj.key.split('/')[-1]
        local_file_key = f"{local_directory}/{file_name}"
        bucket.download_file(obj.key, local_file_key)


def download(s3_path, local_path, bucket='gen-ai-textbooks-dev'):
    try:
        s3_resource = get_s3_resource()
        bucket = s3_resource.Bucket(bucket)
        bucket.download_file(s3_path, local_path)
    except Exception as e:
        logger.error(f"Failed to download: {s3_path}, to {local_path}. {e}")
        raise e


def does_path_exist(prefix):
    s3_resource = get_s3_resource()
    bucket = s3_resource.Bucket(S3_BUCKET)
    for obj in bucket.objects.filter(Prefix=prefix):
        return True
    return False


def does_file_exist(file_path):
    s3 = get_s3_resource()
    try:
        s3.Object(S3_BUCKET, file_path).load()
    except botocore.exceptions.ClientError as error:
        if error.response['Error']['Code'] == "404":
            return False
        elif error.response['Error']['Code'] == "400":
            return False
        else:
            # Something else has gone wrong.
            raise error
    else:
        # The object does exist.
        return True


def save_file_to_s3(content, file_path, s3_bucket=S3_BUCKET, detect_mimetype=False):
    s3 = get_s3_resource()
    if detect_mimetype:
        content_type = detect_content_type(file_path)
        s3.Object(s3_bucket, file_path).put(
            Body=content,
            ContentType=content_type
        )
    else:
        s3.Object(s3_bucket, file_path).put(
            Body=content
        )


def upload_file_to_s3(local_file_path, s3_file_path, s3_bucket=S3_BUCKET, detect_mimetype=False):
    client = get_s3_client()
    
    if detect_mimetype:
        content_type = detect_content_type(local_file_path)
        extra_args = {
            'ContentType': content_type,
            'CacheControl': 'max-age=86400',
            'ContentDisposition': 'inline'
        }
    else:
        # Determine content type based on file extension
        file_extension = local_file_path.split('.')[-1].lower()
        
        # Image content types
        image_types = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'svg': 'image/svg+xml',
            'bmp': 'image/bmp',
            'tiff': 'image/tiff',
            'tif': 'image/tiff'
        }
        
        # Video content types
        video_types = {
            'mp4': 'video/mp4',
            'mov': 'video/quicktime',
            'avi': 'video/x-msvideo',
            'webm': 'video/webm',
            'mkv': 'video/x-matroska'
        }
        
        if file_extension in image_types:
            content_type = image_types[file_extension]
        elif file_extension in video_types:
            content_type = video_types[file_extension]
        else:
            # Default to video/mp4 as in the original function
            content_type = 'video/mp4'
        
        extra_args = {
            'ContentType': content_type,
            'CacheControl': 'max-age=86400',
            'ContentDisposition': 'inline'
        }
    
    client.upload_file(local_file_path, s3_bucket, s3_file_path, ExtraArgs=extra_args)
    return f"https://{s3_bucket}.s3.{AWS_REGION}.amazonaws.com/{s3_file_path}"

def copy_s3_object(source_path: str, destination_path: str, s3_bucket: str = S3_BUCKET, s3_destination_bucket: Optional[str] = None) -> str:
    s3_destination_bucket = s3_bucket if s3_destination_bucket is None else s3_destination_bucket

    client = get_s3_client()
    copy_source = {
        'Bucket': s3_bucket,
        'Key': source_path
    }
    
    # Check if the file is a video
    is_video = destination_path.lower().endswith(('.mp4', '.webm', '.mov', '.avi', '.mkv'))
    
    # Set the appropriate metadata for the copied object
    extra_args = {}
    
    if is_video:
        extra_args = {
            'MetadataDirective': 'REPLACE',
            'ContentType': 'video/mp4',  
            'CacheControl': 'max-age=86400',
            'ContentDisposition': 'inline'
        }
    
    client.copy(
        copy_source, 
        s3_destination_bucket, 
        destination_path, 
        ExtraArgs=extra_args if extra_args else None
    )

    # Return the URL for the copied object
    url = f"https://{s3_destination_bucket}.s3.{AWS_REGION}.amazonaws.com/{destination_path}"
    
    return url

def save_json_to_s3(content, file_path, save = False):
    s3 = get_s3_client()
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=file_path,
        Body=json.dumps(content, indent=2),
    )

    if save:
        with open('./functions/fixers/'+os.path.basename(file_path), 'w') as f:
            json.dump(content, f)

def filter_s3_files(key, file_name, regex=r'Retry(\d+)'):
    s3 = get_s3_client()
    retry_files = {}
    max_retry_count = -1
    max_retry_file = None

    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=key):
        for obj in page['Contents']:
            if obj['Key'].endswith(file_name):
                match = re.search(regex, obj['Key'])
                if match:
                    retry_count = int(match.group(1))
                    retry_files["Retry" + match.group(1)] = obj['Key']
                    if retry_count > max_retry_count:
                        max_retry_count = retry_count
                        max_retry_file = obj['Key']
    return max_retry_file, retry_files


def read_content_from_s3(file_name):
    try: 
        s3 = get_s3_client()
        obj = s3.get_object(Bucket=S3_BUCKET, Key=file_name)
        data = obj['Body'].read()
        return data
    except Exception as e:
        raise Exception(f"{e}. On file {file_name}")

def read_file_from_s3(file_name):
    data = read_content_from_s3(file_name)
    return data.decode('utf-8')


def filter_dict_keys(input_list, input_dict, depth=1):
    filtered_dict = {}
    for key, value in input_dict.items():
        if key in input_list:
            if isinstance(value, dict) and depth < 3:
                filtered_dict[key] = filter_dict_keys(input_list, value, depth + 1)
            else:
                filtered_dict[key] = value
    return filtered_dict


def load_json_from_s3(path):
    try:
        data = read_file_from_s3(path)
        return json.loads(data)
    except Exception as e:
        logger.error(f"ERROR. When loading file {path}. {e}")
        raise e


def delete_file_from_s3(path, s3_bucket=S3_BUCKET):
    s3 = get_s3_resource()
    s3.Object(s3_bucket, path).delete()


def upload_dir(local_dir, s3_prefix, s3_bucket=S3_BUCKET, detect_mimetype=False):
    for local_file_path in list_files(local_dir):
        s3_file_path = os.path.join(s3_prefix, os.path.relpath(local_file_path, local_dir))
        upload_file_to_s3(local_file_path, s3_file_path, s3_bucket, detect_mimetype)


def rename_s3_file(old_key, new_key):
    s3 = get_s3_resource()

    copy_source = {
        'Bucket': S3_BUCKET,
        'Key': old_key
    }

    s3.Object(S3_BUCKET, new_key).copy(copy_source)

    # now delete the old object
    s3.Object(S3_BUCKET, old_key).delete()


def save_content_to_s3(bytes_stream, file_path):
    s3 = get_s3_client()
    s3.put_object(Body=bytes_stream, Bucket=S3_BUCKET, Key=file_path)


def copy_s3_folder(current_dir, new_dir):
    s3_client = boto3.client('s3')
    paginator = s3_client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=S3_BUCKET, Prefix=current_dir)

    for page in pages:
        if 'Contents' in page:
            for obj in page['Contents']:
                old_key = obj['Key']
                new_key = old_key.replace(current_dir, new_dir, 1)
                s3_client.copy_object(
                    Bucket=S3_BUCKET,
                    CopySource={'Bucket': S3_BUCKET, 'Key': old_key},
                    Key=new_key
                )


def check_folder_exists(folder_key):
    s3 = boto3.client('s3')
    response = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=folder_key, MaxKeys=1)
    return 'Contents' in response

def get_folder_link(folder_path: str, s3_bucket: str = S3_BUCKET) -> str:

    if not folder_path.endswith('/'):
        folder_path += '/'
    folder_path = folder_path.replace(' ', '%20')
    
    # return f"https://{s3_bucket}.s3.{AWS_REGION}.amazonaws.com/{folder_path}"
    return f"https://{AWS_REGION}.console.aws.amazon.com/s3/buckets/{s3_bucket}?prefix={folder_path}"


# STORAGE=local swaps every storage call in the pipeline for the local filesystem. All 25
# callers spell it `from core.clients.s3 import <name>`, which binds whatever this module
# holds at import time, so rebinding here reaches all of them and none of them change.
#
# ponytail: the switch is read once at import, so the backend is fixed for the process.
# That is all run.py needs, since it sets STORAGE before the first core import. Making it
# per-call would mean a dispatch wrapper around all 22 names for no current benefit.
if is_local():
    from core.clients import local_store as _local_store

    for _name in _local_store.OVERRIDES:
        globals()[_name] = getattr(_local_store, _name)
    logger.info(f"STORAGE=local: artifacts under {_local_store.storage_root()}")