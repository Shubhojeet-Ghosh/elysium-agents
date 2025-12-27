from typing import List, Dict, Any
from datetime import datetime, timezone

from logging_config import get_logger

from services.elysium_atlas_services.atlas_qdrant_services import index_custom_texts_in_knowledge_base,index_qa_pairs_in_knowledge_base
from services.mongo_services import get_collection
from services.elysium_atlas_services.agent_db_operations import update_agent_current_task

logger = get_logger()

async def index_custom_knowledge_for_agent(agent_id, custom_texts, qa_pairs):
    try:
        await update_agent_current_task(agent_id, "Indexing Custom Knowledge")
        if(custom_texts):
            custom_text_index_result = await index_custom_texts_in_knowledge_base(agent_id, custom_texts)
            logger.info(f"Custom texts index result for agent_id {agent_id}: {custom_text_index_result}")
            
            # Store custom texts in MongoDB
            try:
                collection = get_collection("atlas_custom_texts")
                current_time = datetime.now(timezone.utc)
                
                for custom_text in custom_texts:
                    if custom_text and custom_text.get("custom_text_alias") and custom_text.get("custom_text"):
                        filter_doc = {
                            "agent_id": agent_id,
                            "custom_text_alias": custom_text["custom_text_alias"]
                        }
                        update_doc = {
                            "$set": {
                                "updated_at": current_time,
                                "status": "active"
                            },
                            "$setOnInsert": {
                                "created_at": current_time
                            }
                        }
                        await collection.update_one(filter_doc, update_doc, upsert=True)
                        logger.debug(f"Upserted custom text '{custom_text['custom_text_alias']}' for agent_id {agent_id} in MongoDB")
                
                logger.info(f"Upserted {len(custom_texts)} custom texts in MongoDB for agent_id {agent_id}")
            except Exception as e:
                logger.error(f"Error upserting custom texts in MongoDB for agent_id {agent_id}: {e}")

        if(qa_pairs):
            qa_pairs_index_result = await index_qa_pairs_in_knowledge_base(agent_id, qa_pairs)
            logger.info(f"QA pairs index result for agent_id {agent_id}: {qa_pairs_index_result}")
            
            # Store QA pairs in MongoDB
            try:
                collection = get_collection("atlas_qa_pairs")
                current_time = datetime.now(timezone.utc)
                
                for qa_pair in qa_pairs:
                    if qa_pair and qa_pair.get("qna_alias") and qa_pair.get("question") and qa_pair.get("answer"):
                        filter_doc = {
                            "agent_id": agent_id,
                            "qna_alias": qa_pair["qna_alias"]
                        }
                        update_doc = {
                            "$set": {
                                "updated_at": current_time,
                                "status": "active"
                            },
                            "$setOnInsert": {
                                "created_at": current_time
                            }
                        }
                        await collection.update_one(filter_doc, update_doc, upsert=True)
                        logger.debug(f"Upserted QA pair '{qa_pair['qna_alias']}' for agent_id {agent_id} in MongoDB")
                
                logger.info(f"Upserted {len(qa_pairs)} QA pairs in MongoDB for agent_id {agent_id}")
            except Exception as e:
                logger.error(f"Error upserting QA pairs in MongoDB for agent_id {agent_id}: {e}")
        
        await update_agent_current_task(agent_id, "Custom Knowledge Indexed")
        return True

    except  Exception as e:
        logger.error(f"Error indexing custom knowledge for agent {agent_id}: {e}")
        return False