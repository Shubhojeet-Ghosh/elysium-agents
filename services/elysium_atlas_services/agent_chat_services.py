from logging_config import get_logger
from typing import Any, Dict
from services.elysium_atlas_services.atlas_query_qdrant_services import search_and_merge_agent_knowledge
from services.elysium_atlas_services.agent_db_operations import get_agent_by_id
from services.socket_emit_services import emit_atlas_response_chunk
from services.elysium_atlas_services.atlas_chat_session_services import (
    create_and_store_chat_messages,
    get_chat_session_data,
    coerce_utc_datetime,
    format_utc_datetime_for_client,
    serialize_chat_message_for_client,
)

from config.llm_models_config import resolve_model_handler, DEFAULT_MODEL
from config.retrieval_strategy_config import DEFAULT_RETRIEVAL_STRATEGY

import asyncio
import time
import uuid
import datetime

logger = get_logger()


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _resolve_user_message_created_at(additional_params: dict) -> datetime.datetime:
    """Server-side receive time only; frontend created_at is ignored for storage."""
    received_timestamp = additional_params.get("_message_received_at")
    if received_timestamp is not None:
        return coerce_utc_datetime(received_timestamp)
    return _utc_now()


def _build_agent_message_from_stored(
    stored_messages: list | None,
    agent_message_id: str,
    response_text: str,
    agent_message_created_at: datetime.datetime,
) -> Dict[str, Any] | None:
    """Serialize the stored AI agent message for socket/API payloads."""
    agent_stored = next(
        (doc for doc in (stored_messages or []) if doc.get("role") == "agent"),
        None,
    )
    if agent_stored:
        return serialize_chat_message_for_client(agent_stored)

    if not response_text:
        return None

    return serialize_chat_message_for_client(
        {
            "message_id": agent_message_id,
            "role": "agent",
            "content": response_text,
            "created_at": agent_message_created_at,
        }
    )


def format_knowledge_base_string(final_results: list) -> str:
    """
    Format the final_results list into a knowledge base string for LLM consumption.
    
    Args:
        final_results (list): List of knowledge source objects with metadata and content
    
    Returns:
        str: Formatted knowledge base string
    """
    knowledge_sections = []
    
    for result in final_results:
        # Build metadata line with only non-falsy values
        metadata_parts = []
        
        # Add knowledge_source only if page_type exists and knowledge_source is present
        knowledge_source = result.get("knowledge_source", "")
        if result.get("page_type") and knowledge_source:
            metadata_parts.append(f"[knowledge_source: {knowledge_source}]")
        
        # Add optional fields only if they have non-falsy values
        if result.get("summary"):
            metadata_parts.append(f'summary: "{result["summary"]}"')
        
        if result.get("product_name"):
            metadata_parts.append(f'product_name: "{result["product_name"]}"')
        
        if result.get("product_id"):
            metadata_parts.append(f'product_id: "{result["product_id"]}"')
        
        if result.get("category"):
            metadata_parts.append(f'category: "{result["category"]}"')
        
        if result.get("price") is not None:  # Check explicitly for None since 0 could be valid
            metadata_parts.append(f'price: {result["price"]}')
        
        if result.get("currency"):
            metadata_parts.append(f'currency: "{result["currency"]}"')
        
        if result.get("is_available") is not None:  # Check explicitly for None
            metadata_parts.append(f'is_available: {result["is_available"]}')
        
        # Join metadata parts with space
        metadata_line = " ".join(metadata_parts)
        
        # Add text_content if available
        text_content = result.get("text_content", "")
        if text_content:
            section = f"{metadata_line}\n\n{text_content}"
        else:
            section = metadata_line
        
        knowledge_sections.append(section)
    
    # Join all sections with separator
    return "\n\n###\n\n".join(knowledge_sections)


def build_messages_list(agent_data: dict, message: str, knowledge_base_string: str, chat_history: list = None) -> list:
    """
    Build an OpenAI-style messages list with system prompt, chat history, knowledge base, and user message.
    """
    messages = []

    # --- Agent identity and core instructions ---
    agent_name = agent_data.get("agent_name") if agent_data else None
    agent_identity = f"You are a virtual assistant named **{agent_name}**.\n\n" if agent_name else ""

    messages.append({
        "role": "system",
        "content": (
            f"{agent_identity}"
            "Your task is to generate a clear, accurate, and helpful response that sounds natural and conversational.\n\n"
            "FORMATTING RULES:\n"
            "- Format the responses in clear, proper Markdown\n"
            "- Use **bold** for important terms and emphasis\n"
            "- Use **descriptive Markdown headings** (`##` for main sections, `###` for subsections) **wherever they improve readability and scannability**\n"
            "- Use bullet points (-) or numbered lists (1.) for multiple items\n"
            "- Use `code formatting` for technical terms, IDs, or specific values\n"
            "- Use > blockquotes for important notes or warnings\n"
            "- For code blocks: Use ```language syntax and keep lines reasonably short (max 80 chars) for better readability\n"
            "- For tables: Keep columns concise and use | alignment for clean formatting\n"
            "- For wide content: Break into smaller, more digestible chunks rather than creating overly wide tables or code blocks\n"
            "- Keep responses concise, well-structured, user-friendly and most important *natural*.\n"
        )
    })

    # --- Agent-specific system prompt ---
    system_prompt = agent_data.get("system_prompt") if agent_data else None
    if system_prompt:
        messages.append({
            "role": "system",
            "content": system_prompt
        })

    # --- Chat History ---
    VALID_ROLES = {"system", "assistant", "user", "function", "tool", "developer"}
    if chat_history:
        for hist_msg in chat_history:
            raw_role = hist_msg.get("role", "user")
            if raw_role in ("agent", "human"):
                role = "assistant"
            elif raw_role in VALID_ROLES:
                role = raw_role
            else:
                role = "system"
            messages.append({
                "role": role,
                "content": hist_msg.get("content", "")
            })

    # --- Knowledge Base (RAG context) ---
    if knowledge_base_string:
        messages.append({
            "role": "user",
            "content": (
                "The following information is provided as a Knowledge Base that may "
                "help you answer the user's question.\n\n"
                "Guidelines:\n"
                "- Use this Knowledge Base when it is relevant or helpful\n"
                "- If the Knowledge Base contains useful information, incorporate it "
                "naturally into your response\n\n"
                "Knowledge Base:\n\n"
                f"{knowledge_base_string}"
            )
        })

    # --- User message (ALWAYS LAST) ---
    messages.append({
        "role": "user",
        "content": message
    })

    return messages

async def chat_with_agent_v1(agent_id, message, sid=None, chat_session_id=None, additional_params: dict = {}):
    chat_log = f"[chat agent_id={agent_id}]"
    try:
        logger.info(f"{chat_log} Processing visitor message")

        user_message_id = str(uuid.uuid4())
        agent_message_id = str(uuid.uuid4())
        user_message_created_at = _resolve_user_message_created_at(additional_params)

        logger.info(f"{chat_log} Loading chat session and agent config")
        chat_session_data, agent_data = await asyncio.gather(
            get_chat_session_data({
                "agent_id": agent_id,
                "chat_session_id": chat_session_id,
                "limit": 10
            }),
            get_agent_by_id(agent_id),
        )
        chat_history = chat_session_data.get("messages", []) if chat_session_data else []
        # logger.info(
        #     f"{chat_log} load_session_and_agent done in "
        #     f"{(time.perf_counter() - step_start) * 1000:.0f}ms "
        #     f"(history_messages={len(chat_history)})"
        # )

        agent_name = chat_session_data.get("agent_name") if chat_session_data else None

        retrieval_strategy = (agent_data or {}).get("retrieval_strategy") or DEFAULT_RETRIEVAL_STRATEGY
        logger.info(f"{chat_log} Retrieving knowledge (strategy={retrieval_strategy})")
        final_results = await search_and_merge_agent_knowledge(
            agent_id, message, retrieval_strategy
        )
        # logger.info(
        #     f"{chat_log} knowledge_retrieval done in "
        #     f"{(time.perf_counter() - step_start) * 1000:.0f}ms "
        #     f"(strategy={retrieval_strategy}, sources={len(final_results)})"
        # )
        
        if(agent_name):
            agent_data["agent_name"] = agent_name

        logger.info(f"{chat_log} Building LLM prompt with knowledge and chat history")
        knowledge_base_string = format_knowledge_base_string(final_results)
        messages = build_messages_list(agent_data, message, knowledge_base_string, chat_history)
        # logger.info(
        #     f"{chat_log} prepare_llm_messages done in "
        #     f"{(time.perf_counter() - step_start) * 1000:.0f}ms"
        # )
        
        model = agent_data.get("llm_model") or DEFAULT_MODEL
        handler, config = resolve_model_handler(model)
        
        chat_payload = {
            "model": model,
            "messages": messages,
        }

        if "temperature" in agent_data:
            chat_payload["temperature"] = agent_data.get("temperature",0.5)
        
        stream = False

        if(sid):
            stream = True
            chat_payload["stream"] = stream

        if additional_params.get("stream"):
            stream = bool(additional_params["stream"])
            chat_payload["stream"] = stream

        logger.info(f"{chat_log} Generating agent response (model={model}, stream={stream})")
        response_obj = await handler(chat_payload)

        response_text = ""
        agent_message_created_at = _utc_now()
        stored_messages = None
        if stream and hasattr(response_obj, "__aiter__"):
            first_chunk_emitted = False
            request_started_at = additional_params.get("_request_started_at")
            async for chunk in response_obj:
                response_text += chunk
                if sid:
                    if not first_chunk_emitted:
                        first_chunk_emitted = True
                        if request_started_at is not None:
                            ttft_ms = (time.perf_counter() - request_started_at) * 1000
                            logger.info(f"{chat_log} Time to first token: {ttft_ms:.0f}ms")
                    await emit_atlas_response_chunk(chunk, done=False, sid=sid)

            agent_mongo_id = None
            if chat_session_id:
                stored_messages = await create_and_store_chat_messages(
                    chat_session_id=chat_session_id,
                    agent_id=agent_id,
                    user_message_payload={
                        "message_id": user_message_id,
                        "role": "user",
                        "content": message,
                        "created_at": user_message_created_at,
                    },
                    agent_message_payload={
                        "message_id": agent_message_id,
                        "role": "agent",
                        "content": response_text,
                        "created_at": agent_message_created_at,
                    },
                )
                for stored in stored_messages:
                    if stored.get("role") == "agent":
                        agent_mongo_id = stored.get("_id")
                        break
                logger.info(f"{chat_log} Stored chat messages before final stream emit")

            if sid:
                await emit_atlas_response_chunk(
                    "",
                    done=True,
                    sid=sid,
                    full_response=response_text,
                    message_id=agent_message_id,
                    mongo_id=agent_mongo_id,
                    created_at=format_utc_datetime_for_client(agent_message_created_at),
                    role="agent",
                )
            
            # logger.info(
            #     f"{chat_log} llm_streaming done in "
            #     f"{(time.perf_counter() - step_start) * 1000:.0f}ms "
            #     f"(chars={len(response_text)})"
            # )
        else:
            response_text = response_obj

        if chat_session_id and not (stream and sid):
            stored_messages = await create_and_store_chat_messages(
                chat_session_id=chat_session_id,
                agent_id=agent_id,
                user_message_payload={
                    "message_id": user_message_id,
                    "role": "user",
                    "content": message,
                    "created_at": user_message_created_at,
                },
                agent_message_payload={
                    "message_id": agent_message_id,
                    "role": "agent",
                    "content": response_text,
                    "created_at": agent_message_created_at,
                },
            )
            logger.info(f"{chat_log} Stored chat messages")

        agent_message = None
        if chat_session_id:
            agent_message = _build_agent_message_from_stored(
                stored_messages,
                agent_message_id,
                response_text,
                agent_message_created_at,
            )

        logger.info(f"{chat_log} Visitor message processed successfully")

        return {
            "success": True,  
            "results": final_results,
            "knowledge_base": knowledge_base_string,
            "messages": messages,
            "message": "Search completed successfully.",
            "agent_data": agent_data,
            "response_text": response_text,
            "chat_history": chat_history,
            "agent_message": agent_message,
        }
    
    except Exception as e:
        logger.error(f"Error in chat_with_agent_v1: {e}")
        return {"success": False, "message": "An error occurred while processing the chat."}