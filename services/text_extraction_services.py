import os
import subprocess
import tempfile
import boto3
import asyncio
import docx2txt
import shutil

from config.settings import settings
from logging_config import get_logger

logger = get_logger()

def get_soffice_path() -> str:
    """
    Resolve LibreOffice 'soffice' executable path.
    Safe for systemd environments.
    """
    # 1. Try PATH (works in dev shells)
    soffice = shutil.which("soffice")
    if soffice:
        return soffice

    # 2. Linux default
    linux_path = "/usr/bin/soffice"
    if os.path.exists(linux_path):
        return linux_path

    # 3. Windows fallbacks
    windows_paths = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for path in windows_paths:
        if os.path.exists(path):
            return path

    raise RuntimeError(
        "LibreOffice 'soffice' executable not found. "
        "Ensure LibreOffice is installed."
    )

async def extract_text_from_word_document(
    bucket_name: str,
    file_key: str,
    file_name: str
) -> str:
    """
    Extracts text from .doc or .docx files.
    - .docx → docx2txt (Python)
    - .doc  → LibreOffice headless (Windows-safe)
    """

    temp_path = None

    try:
        SOFFICE_PATH = "/usr/bin/soffice"

        # 1️⃣ Create S3 client
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION
        )

        # 2️⃣ Download file to temp location
        suffix = os.path.splitext(file_name)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = temp_file.name

        s3_client.download_file(bucket_name, file_key, temp_path)

        # 3️⃣ Extract text
        ext = file_name.lower().split(".")[-1]

        # --- DOCX ---
        if ext == "docx":
            text = await asyncio.to_thread(docx2txt.process, temp_path)

        # --- DOC (LibreOffice) ---
        elif ext == "doc":
            out_dir = os.path.dirname(temp_path)

            await asyncio.to_thread(
                subprocess.run,
                [
                    SOFFICE_PATH,
                    "--headless",
                    "--nologo",
                    "--nodefault",
                    "--nolockcheck",
                    "--norestore",
                    "--convert-to",
                    "txt:Text",
                    "--outdir",
                    out_dir,
                    temp_path,
                ]
                ,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )

            txt_candidates = [
                f for f in os.listdir(out_dir)
                if f.lower().endswith(".txt")
            ]

            if not txt_candidates:
                raise RuntimeError("LibreOffice conversion failed: no TXT output found")

            txt_path = os.path.join(out_dir, txt_candidates[0])

            with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()


        else:
            logger.warning(f"Unsupported file type: {file_name}")
            return ""

        logger.info(f"Successfully extracted text from {file_name}")
        return text.strip()

    except Exception as e:
        logger.error(f"Error extracting text from {file_name}: {e}")
        return ""

    finally:
        # 4️⃣ Cleanup temp files
        for path in [temp_path, temp_path.replace(".doc", ".txt") if temp_path else None]:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception as e:
                    logger.warning(f"Failed to delete temp file {path}: {e}")
