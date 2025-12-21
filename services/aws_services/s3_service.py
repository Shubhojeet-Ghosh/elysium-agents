import boto3
from fastapi import HTTPException
from config.settings import settings
from config.elysium_atlas_s3_config import ELYSIUM_CDN_BASE_URL
import urllib.parse

def generate_presigned_upload_url(
    bucket_name: str,
    folder_path: str,       # e.g. "images/user/"
    filename: str,          # e.g. "chat_icon3.png"
    filetype: str,          # e.g. "image/png"
    expires_in: int = 600,  # 10 mins default
    visibility: str = None  # Optional: "public" or None
):
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION
    )
    # S3 object key (path inside the bucket)
    # Normalize folder_path: remove leading/trailing slashes and handle double slashes
    normalized_folder = folder_path.strip('/')
    # Split by '/' and filter out empty parts to handle double slashes
    path_parts = [part for part in normalized_folder.split('/') if part] if normalized_folder else []
    path_parts.append(filename)
    s3_key = '/'.join(path_parts)

    try:
        params = {
            "Bucket": bucket_name,
            "Key": s3_key,
            "ContentType": filetype,
        }
        url = s3_client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=expires_in,
            HttpMethod="PUT"
        )
        encoded_key = urllib.parse.quote(s3_key)
        s3_url = f"https://{bucket_name}.s3.{settings.AWS_REGION}.amazonaws.com/{encoded_key}"
        
        result = {
            "status": True,
            "upload_url": url,
            "s3_key": s3_key,
            "s3_object_url": s3_url,
            "visibility": "private"
        }
        
        # Generate CDN URL if visibility is "public"
        if visibility == "public":
            # Use the same normalized s3_key path for CDN URL
            # Ensure CDN base URL doesn't have trailing slash
            cdn_base = ELYSIUM_CDN_BASE_URL.rstrip('/')
            cdn_url = f"{cdn_base}/{s3_key}"
            result["cdn_url"] = cdn_url
            result["visibility"] = "public"
        
        return result
    except Exception as e:
        return {
            "status": False,
            "message": str(e)
        }

def construct_s3_object_url(
    bucket_name: str,
    file_key: str,
    region_name: str = settings.AWS_REGION
) -> str:
    """
    Constructs a public S3 object URL, ensuring the file_key is URL-safe.
    """
    encoded_key = urllib.parse.quote(file_key)
    return f"https://{bucket_name}.s3.{region_name}.amazonaws.com/{encoded_key}"