from typing import List
from datetime import datetime, timezone
import boto3
import asyncio

from config.elysium_atlas_s3_config import *
from config.settings import settings
from services.aws_services.s3_service import extract_text_from_pdf
from services.text_extraction_services import extract_text_from_word_document

from logging_config import get_logger
logger = get_logger()

async def index_agent_files(agent_id, files):
    try:
        logger.info(f"Indexing files for agent_id: {agent_id} with files : {files}")
        
        files_data = await get_texts_from_files(agent_id,files)
        logger.info(f"Extracted files data for agent_id {agent_id}: {files_data}")
        
        return True

    except Exception as e:
        logger.error(f"Error indexing agent files: {e}")
        return False

async def get_texts_from_files(agent_id, files):
    try:
        files_data = []
        
        for file_dict in files:
            if file_dict['file_name'].lower().endswith('.pdf'):
                text = await extract_text_from_pdf(ELYSIUM_ATLAS_BUCKET_NAME, file_dict['file_key'])
                file_dict['text'] = text
            elif file_dict['file_name'].lower().endswith(('.doc', '.docx')):
                text = await extract_text_from_word_document(ELYSIUM_ATLAS_BUCKET_NAME, file_dict['file_key'], file_dict['file_name'])
                file_dict['text'] = text
            else:
                file_dict['text'] = ''  # For other files, set empty text
            files_data.append(file_dict)
        
        # logger.info(f"Extracted texts from files for agent_id {agent_id}: {files_data}")
        return files_data

    except Exception as e:
        logger.error(f"Error extracting texts from files: {e}")
        return []
