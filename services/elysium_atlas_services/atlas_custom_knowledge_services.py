from typing import List, Dict, Any
from datetime import datetime, timezone

from logging_config import get_logger

from services.elysium_atlas_services.atlas_qdrant_services import index_custom_texts_in_knowledge_base,index_qa_pairs_in_knowledge_base
from services.mongo_services import get_collection
from services.elysium_atlas_services.agent_db_operations import update_agent_current_task
from services.qdrant_api_services import delete_qdrant_points_by_filter
from services.elysium_atlas_services.qdrant_collection_helpers import AGENT_KNOWLEDGE_BASE_COLLECTION_NAME

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

async def remove_custom_data(agent_id: str, custom_texts: list[str] = None, qa_pairs: list[str] = None) -> dict:
    """
    Remove specific custom texts and/or QA pairs from an agent's knowledge base (MongoDB and Qdrant).
    
    Args:
        agent_id: The ID of the agent
        custom_texts: List of custom_text_alias values to remove (optional)
        qa_pairs: List of qna_alias values to remove (optional)
    
    Returns:
        dict: Result with success status and errors
    """
    try:
        errors = []
        mongodb_custom_texts_deleted = 0
        mongodb_qa_pairs_deleted = 0
        qdrant_custom_texts_deleted = 0
        qdrant_qa_pairs_deleted = 0
        
        # Remove custom texts from MongoDB
        if custom_texts:
            try:
                custom_texts_collection = get_collection("atlas_custom_texts")
                mongo_result = await custom_texts_collection.delete_many({
                    "agent_id": agent_id,
                    "custom_text_alias": {"$in": custom_texts}
                })
                mongodb_custom_texts_deleted = mongo_result.deleted_count
                logger.info(f"Deleted {mongodb_custom_texts_deleted} custom texts from MongoDB for agent_id {agent_id}")
            except Exception as e:
                error_msg = f"MongoDB custom texts deletion error: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
            
            # Remove custom texts from Qdrant
            qdrant_filters = {
                "must": [
                    {"key": "agent_id", "match": {"value": agent_id}},
                    {"key": "knowledge_source", "match": {"any": custom_texts}},
                    {"key": "knowledge_type", "match": {"value": "custom_text"}}
                ]
            }
            
            try:
                qdrant_result = await delete_qdrant_points_by_filter(
                    collection_name=AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
                    filters=qdrant_filters
                )
                if qdrant_result.get("success"):
                    qdrant_count = qdrant_result.get("result", {}).get("deleted", 0) if isinstance(qdrant_result.get("result"), dict) else 0
                    qdrant_custom_texts_deleted = qdrant_count
                    logger.info(f"Deleted {qdrant_count} custom text points from {AGENT_KNOWLEDGE_BASE_COLLECTION_NAME} for agent_id {agent_id}")
                else:
                    errors.append(f"Qdrant custom texts deletion: {qdrant_result.get('message')}")
            except Exception as e:
                error_msg = f"Qdrant custom texts deletion error: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        # Remove QA pairs from MongoDB
        if qa_pairs:
            try:
                qa_pairs_collection = get_collection("atlas_qa_pairs")
                mongo_result = await qa_pairs_collection.delete_many({
                    "agent_id": agent_id,
                    "qna_alias": {"$in": qa_pairs}
                })
                mongodb_qa_pairs_deleted = mongo_result.deleted_count
                logger.info(f"Deleted {mongodb_qa_pairs_deleted} QA pairs from MongoDB for agent_id {agent_id}")
            except Exception as e:
                error_msg = f"MongoDB QA pairs deletion error: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
            
            # Remove QA pairs from Qdrant
            qdrant_filters = {
                "must": [
                    {"key": "agent_id", "match": {"value": agent_id}},
                    {"key": "knowledge_source", "match": {"any": qa_pairs}},
                    {"key": "knowledge_type", "match": {"value": "custom_qa"}}
                ]
            }
            
            try:
                qdrant_result = await delete_qdrant_points_by_filter(
                    collection_name=AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
                    filters=qdrant_filters
                )
                if qdrant_result.get("success"):
                    qdrant_count = qdrant_result.get("result", {}).get("deleted", 0) if isinstance(qdrant_result.get("result"), dict) else 0
                    qdrant_qa_pairs_deleted = qdrant_count
                    logger.info(f"Deleted {qdrant_count} QA pair points from {AGENT_KNOWLEDGE_BASE_COLLECTION_NAME} for agent_id {agent_id}")
                else:
                    errors.append(f"Qdrant QA pairs deletion: {qdrant_result.get('message')}")
            except Exception as e:
                error_msg = f"Qdrant QA pairs deletion error: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        logger.info(f"Removed custom data for agent_id {agent_id}: "
                   f"MongoDB custom_texts={mongodb_custom_texts_deleted}, "
                   f"MongoDB qa_pairs={mongodb_qa_pairs_deleted}, "
                   f"Qdrant custom_texts={qdrant_custom_texts_deleted}, "
                   f"Qdrant qa_pairs={qdrant_qa_pairs_deleted}, "
                   f"Errors={len(errors)}")
        
        return {
            "success": True,
            "errors": errors
        }

    except Exception as e:
        logger.error(f"Error removing custom data: {e}")
        return {
            "success": False,
            "errors": [str(e)]
        }

async def get_custom_text_from_qdrant(agent_id: str, custom_text_alias: str) -> dict:
    """
    Retrieve and reconstruct custom text from Qdrant chunks.
    
    Args:
        agent_id: The ID of the agent
        custom_text_alias: The alias of the custom text to retrieve
    
    Returns:
        dict: Result with success status, reconstructed text, and errors
    """
    try:
        from services.qdrant_services import get_qdrant_client_instance
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        # Get Qdrant client
        client = get_qdrant_client_instance()
        
        # Create filter to retrieve all chunks for this custom text
        qdrant_filter = Filter(
            must=[
                FieldCondition(key="agent_id", match=MatchValue(value=agent_id)),
                FieldCondition(key="knowledge_source", match=MatchValue(value=custom_text_alias)),
                FieldCondition(key="knowledge_type", match=MatchValue(value="custom_text"))
            ]
        )
        
        # Query Qdrant to get all matching points
        # Using scroll to retrieve all points (not using vector search, just filtering)
        try:
            scroll_result = await client.scroll(
                collection_name=AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
                scroll_filter=qdrant_filter,
                limit=1000,  # Large limit to get all chunks at once
                with_payload=True,
                with_vectors=False  # Don't need vectors, just payload
            )
            
            points = scroll_result[0] if scroll_result else []
            
            if not points:
                logger.info(f"No chunks found for agent_id: {agent_id}, custom_text_alias: {custom_text_alias}")
                return {
                    "success": True,
                    "text_content": "",
                    "chunks_count": 0,
                    "message": "No content found for this custom text alias"
                }
            
            # Extract chunks with their text_index
            chunks_data = []
            for point in points:
                payload = point.payload
                chunks_data.append({
                    "text_index": payload.get("text_index", 0),
                    "text_content": payload.get("text_content", "")
                })
            
            # Sort chunks by text_index
            chunks_data.sort(key=lambda x: x["text_index"])
            
            # Reconstruct text by joining chunks
            # Simple concatenation - overlap will create some duplication but preserves full content
            reconstructed_text = " ".join([chunk["text_content"] for chunk in chunks_data])
            
            logger.info(f"Reconstructed custom text for agent_id: {agent_id}, "
                       f"custom_text_alias: {custom_text_alias}, "
                       f"chunks: {len(chunks_data)}, "
                       f"length: {len(reconstructed_text)} chars")
            
            return {
                "success": True,
                "text_content": reconstructed_text,
                "chunks_count": len(chunks_data)
            }
            
        except Exception as e:
            error_msg = f"Qdrant query error: {str(e)}"
            logger.error(error_msg)
            return {
                "success": False,
                "text_content": "",
                "chunks_count": 0,
                "errors": [error_msg]
            }
    
    except Exception as e:
        logger.error(f"Error retrieving custom text from Qdrant: {e}")
        return {
            "success": False,
            "text_content": "",
            "chunks_count": 0,
            "errors": [str(e)]
        }

async def get_qa_pair_from_qdrant(agent_id: str, qna_alias: str) -> dict:
    """
    Retrieve QA pair from Qdrant.
    Since QA pairs are not chunked, this retrieves a single point.
    
    Args:
        agent_id: The ID of the agent
        qna_alias: The alias of the QA pair to retrieve
    
    Returns:
        dict: Result with success status, question, answer, and errors
    """
    try:
        from services.qdrant_services import get_qdrant_client_instance
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        # Get Qdrant client
        client = get_qdrant_client_instance()
        
        # Create filter to retrieve the QA pair
        qdrant_filter = Filter(
            must=[
                FieldCondition(key="agent_id", match=MatchValue(value=agent_id)),
                FieldCondition(key="knowledge_source", match=MatchValue(value=qna_alias)),
                FieldCondition(key="knowledge_type", match=MatchValue(value="custom_qa"))
            ]
        )
        
        # Query Qdrant to get the QA pair point
        try:
            scroll_result = await client.scroll(
                collection_name=AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
                scroll_filter=qdrant_filter,
                limit=1,  # Only one point expected for QA pairs
                with_payload=True,
                with_vectors=False
            )
            
            points = scroll_result[0] if scroll_result else []
            
            if not points:
                logger.info(f"No QA pair found for agent_id: {agent_id}, qna_alias: {qna_alias}")
                return {
                    "success": True,
                    "text_content": "",
                    "question": "",
                    "answer": "",
                    "message": "No QA pair found for this alias"
                }
            
            # Extract the QA pair content
            point = points[0]
            payload = point.payload
            text_content = payload.get("text_content", "")
            
            # Parse question and answer from text_content
            # Format is "Question: {question} Answer: {answer}"
            question = ""
            answer = ""
            
            if text_content.startswith("Question: "):
                parts = text_content.split(" Answer: ", 1)
                if len(parts) == 2:
                    question = parts[0].replace("Question: ", "").strip()
                    answer = parts[1].strip()
                else:
                    # Fallback: just return the text_content
                    question = text_content
            
            logger.info(f"Retrieved QA pair for agent_id: {agent_id}, qna_alias: {qna_alias}")
            
            return {
                "success": True,
                "text_content": text_content,
                "question": question,
                "answer": answer
            }
            
        except Exception as e:
            error_msg = f"Qdrant query error: {str(e)}"
            logger.error(error_msg)
            return {
                "success": False,
                "text_content": "",
                "question": "",
                "answer": "",
                "errors": [error_msg]
            }
    
    except Exception as e:
        logger.error(f"Error retrieving QA pair from Qdrant: {e}")
        return {
            "success": False,
            "text_content": "",
            "question": "",
            "answer": "",
            "errors": [str(e)]
        }