from typing import List
from datetime import datetime, timezone

from services.text_extraction_services import extract_texts_from_files
from services.elysium_atlas_services.atlas_qdrant_services import index_files_in_knowledge_base
from services.mongo_services import get_collection
from pymongo import UpdateOne

from logging_config import get_logger
logger = get_logger()

async def index_agent_files(agent_id, files):
    try:
        logger.info(f"Indexing files for agent_id: {agent_id} with files : {files}")
        
        # files format - [{"file_name": "example.pdf", "file_key": "s3 path/to/example.pdf"}, ...]
        # files_data format - [{"file_name": "example.pdf","file_key": "s3 path/to/example.pdf", "text": "extracted text from pdf"}, ...]
        files_data = await extract_texts_from_files(files)
        logger.info(f"Extracted files data for agent_id {agent_id}: {len(files_data)} files processed")
        
        qdrant_index_result = await index_files_in_knowledge_base(agent_id, files_data)
        logger.info(f"Qdrant index result for agent_id {agent_id}: {qdrant_index_result}")

        if qdrant_index_result.get("total_processed", 0) > 0:
            # Store file metadata in MongoDB atlas_agent_files collection
            current_time = datetime.now(timezone.utc)
            collection = get_collection("atlas_agent_files")
            bulk_operations = []
            
            for file_dict in files_data:
                # Prepare update document
                update_doc = {
                    "$set": {
                        "updated_at": current_time,
                        "status": "indexed",
                        "file_key": file_dict["file_key"]  # Update file_key in case it changed
                    },
                    "$setOnInsert": {
                        "agent_id": agent_id,
                        "file_name": file_dict["file_name"],
                        "created_at": current_time
                    }
                }
                
                # Create UpdateOne operation for bulk write (upsert will insert if not exists, update if exists)
                bulk_operations.append(
                    UpdateOne(
                        {"agent_id": agent_id, "file_name": file_dict["file_name"]},
                        update_doc,
                        upsert=True
                    )
                )
            
            if bulk_operations:
                bulk_result = await collection.bulk_write(bulk_operations, ordered=False)
                logger.info(f"MongoDB bulk write: {bulk_result.upserted_count} inserted, {bulk_result.modified_count} updated in atlas_agent_files collection for agent_id {agent_id}")
        
        return True

    except Exception as e:
        logger.error(f"Error indexing agent files: {e}")
        return False