from logging_config import get_logger
from services.elysium_atlas_services.atlas_query_qdrant_services import search_and_merge_agent_knowledge
from services.elysium_atlas_services.agent_db_operations import get_agent_by_id
from services.socket_emit_services import emit_atlas_response_chunk
from services.elysium_atlas_services.atlas_chat_session_services import create_and_store_chat_messages, get_chat_messages_for_session, enhance_user_message, get_chat_session_data

from config.llm_models_config import resolve_model_handler, DEFAULT_MODEL

import asyncio
import uuid
import datetime

logger = get_logger()


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
            "You will receive:\n"
            "1. A user message (the question or request)\n"
            "2. A Knowledge Base containing relevant information\n\n"
            "Your task is to generate a clear, accurate, and helpful response by:\n"
            "- Understanding the user's message\n"
            "- Using the Knowledge Base as the primary source of truth\n"
            "- Combining information only when it is relevant and consistent\n\n"
            "CONTENT RULES:\n"
            "- If the Knowledge Base contains the answer, use it\n"
            "- If the Knowledge Base partially contains the answer, respond using only what is available\n"
            "- If the Knowledge Base does not contain the answer, clearly state that the information is not available\n"
            "- Do not invent facts or make assumptions beyond the provided Knowledge Base\n\n"
            "FORMATTING RULES:\n"
            "- Format all responses in clear, proper Markdown\n"
            "- Use **bold** for important terms and emphasis\n"
            "- Use headers (## or ###) to structure longer responses\n"
            "- Use bullet points (-) or numbered lists (1.) for multiple items\n"
            "- Use `code formatting` for technical terms, IDs, or specific values\n"
            "- Use > blockquotes for important notes or warnings\n"
            "- For code blocks: Use ```language syntax and keep lines reasonably short (max 80 chars) for better readability\n"
            "- For tables: Keep columns concise and use | alignment for clean formatting\n"
            "- For wide content: Break into smaller, more digestible chunks rather than creating overly wide tables or code blocks\n"
            "- Keep responses concise, well-structured, and user-friendly"
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
    if chat_history:
        for hist_msg in chat_history:
            role = "assistant" if hist_msg.get("role") == "agent" else hist_msg.get("role", "user")
            messages.append({
                "role": role,
                "content": hist_msg.get("content", "")
            })

    # --- Knowledge Base (RAG context) ---
    if knowledge_base_string:
        messages.append({
            "role": "user",
            "content": (
                "The following is the Knowledge Base provided to you.\n\n"
                "Guidelines:\n"
                "- Treat this Knowledge Base as the authoritative source\n"
                "- Do not use external knowledge\n"
                "- Do not invent or assume missing details\n\n"
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
    try:
        user_message_id = str(uuid.uuid4())
        agent_message_id = str(uuid.uuid4())
        user_message_created_at = additional_params.get("created_at") or datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        
        chat_session_data = await get_chat_session_data({
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "limit": 10
        })
        
        chat_history = chat_session_data.get("messages", []) if chat_session_data else []

        agent_name = chat_session_data.get("agent_name") if chat_session_data else None

        # Enhance the user message with chat history
        enhanced_message = await enhance_user_message(message, chat_history)
        logger.info(f"Enhanced message: {enhanced_message}")

        # Run agent data retrieval and knowledge search in parallel
        agent_data, final_results = await asyncio.gather(
            get_agent_by_id(agent_id),
            search_and_merge_agent_knowledge(agent_id, enhanced_message)
        )
        
        if(agent_name):
            agent_data["agent_name"] = agent_name

        # Format knowledge base string for LLM
        knowledge_base_string = format_knowledge_base_string(final_results)
            

        # Build messages list with system prompt and knowledge base
        messages = build_messages_list(agent_data, enhanced_message, knowledge_base_string, chat_history)
        
        model = agent_data.get("llm_model") or DEFAULT_MODEL

        # Resolve handler from registry (defaults if unknown model)
        handler, config = resolve_model_handler(model)
        
        # Build payload; allow passthrough for optional params like temperature, top_p, etc.
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
        
        logger.info(f"Resolved model '{model}' with handler '{handler.__name__}'")    

        # Call model-specific handler
        response_obj = await handler(chat_payload)

        # If streaming, iterate over async generator and emit chunks
        response_text = ""
        agent_message_created_at = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        if stream and hasattr(response_obj, "__aiter__"):
            async for chunk in response_obj:
                response_text += chunk
                if sid:
                    await emit_atlas_response_chunk(chunk, done=False, sid=sid)
            
            # Send final "done" signal
            if sid:
                await emit_atlas_response_chunk("", done=True, sid=sid, full_response=response_text, message_id=agent_message_id, created_at=agent_message_created_at, role="agent")
            
            logger.info(f"Streaming completed for model '{model}'")
        else:
            response_text = response_obj

        # Store user and agent messages if chat_session_id is provided
        if chat_session_id:
            user_payload = {
                "message_id": user_message_id,
                "role": "user",
                "content": message,
                "created_at": user_message_created_at,
                "enhanced_message": enhanced_message
            }
            agent_payload = {
                "message_id": agent_message_id,
                "role": "agent",
                "content": response_text,
                "created_at": agent_message_created_at
            }
            asyncio.create_task(create_and_store_chat_messages(
                chat_session_id=chat_session_id,
                agent_id=agent_id,
                user_message_payload=user_payload,
                agent_message_payload=agent_payload
            ))

        return {
            "success": True,  
            "results": final_results,
            "knowledge_base": knowledge_base_string,
            "messages": messages,
            "message": "Search completed successfully.",
            "agent_data": agent_data,
            "response_text": response_text,
            "chat_history": chat_history,
            "enhanced_message": enhanced_message
        }
    
    except Exception as e:
        logger.error(f"Error in chat_with_agent_v1: {e}")
        return {"success": False, "message": "An error occurred while processing the chat."}