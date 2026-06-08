from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse

from config.email_ai_agent_models import (
    CreateEmailAiAgentRequest,
    GetEmailAiAgentRequest,
    GetEmailThreadRequest,
    ListTeamEmailAiAgentsRequest,
    ListTeamEmailThreadsRequest,
    SendThreadAiDraftRequest,
    TriggerAgentSyncRequest,
    UpdateEmailAiAgentRequest,
)
from logging_config import get_logger
from services.email_agent_services.email_agent_sync_services import (
    run_agent_inbox_sync,
    start_agent_inbox_sync,
)
from services.email_agent_services.email_ai_agent_services import (
    create_email_ai_agent,
    get_email_ai_agent_detail,
    list_team_email_ai_agents,
    update_email_ai_agent,
)
from services.email_agent_services.email_thread_services import (
    get_email_thread_detail,
    list_team_email_threads,
    send_thread_ai_draft,
)

logger = get_logger()


def _unauthorized_response(user_data: dict) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "success": False,
            "message": user_data.get("message", "Unauthorized"),
        },
    )


def _forbidden_response(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "success": False,
            "message": message,
        },
    )


def _get_authenticated_email_user(user_data: dict) -> dict | JSONResponse:
    if not user_data or user_data.get("success") is False:
        return _unauthorized_response(user_data)

    user_id = user_data.get("user_id")
    team_id = user_data.get("team_id")
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={"success": False, "message": "Invalid token: user_id missing."},
        )
    if not team_id:
        return JSONResponse(
            status_code=401,
            content={"success": False, "message": "Invalid token: team_id missing."},
        )

    return {
        "user_id": user_id,
        "team_id": team_id,
        "department_id": user_data.get("department_id", ""),
        "role": user_data.get("role", "member"),
    }


async def create_email_ai_agent_controller(
    request_data: CreateEmailAiAgentRequest,
    user_data: dict,
):
    try:
        if not user_data or user_data.get("success") is False:
            return _unauthorized_response(user_data)

        user_id = user_data.get("user_id")
        team_id = user_data.get("team_id")
        if not user_id:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid token: user_id missing."},
            )
        if not team_id:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid token: team_id missing."},
            )

        result = await create_email_ai_agent(
            user_id=user_id,
            team_id=team_id,
            name=request_data.name,
            gmail_account_id=request_data.gmail_account_id,
            system_prompt=request_data.system_prompt,
            knowledge_id=request_data.knowledge_id,
            tool_ids=request_data.tool_ids,
            llm_model=request_data.llm_model,
            reply_action=request_data.reply_action.model_dump(),
            routing_rule_ids=request_data.routing_rule_ids,
            recipient_rule_ids=request_data.recipient_rule_ids,
            email_format_template=request_data.email_format_template,
            flow_id=request_data.flow_id,
        )

        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            body = {
                "success": False,
                "message": result.get("message", "Failed to create email AI agent."),
            }
            if result.get("data") is not None:
                body["data"] = result.get("data")
            return JSONResponse(status_code=status_code, content=body)

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "agent": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in create_email_ai_agent_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while creating the email AI agent.",
            },
        )


async def get_email_ai_agent_controller(request_data: GetEmailAiAgentRequest):
    try:
        result = await get_email_ai_agent_detail(agent_id=request_data.agent_id)
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch email AI agent."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "agent": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in get_email_ai_agent_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while fetching the email AI agent.",
            },
        )


async def update_email_ai_agent_controller(
    request_data: UpdateEmailAiAgentRequest,
    user_data: dict,
):
    try:
        if not user_data or user_data.get("success") is False:
            return _unauthorized_response(user_data)

        team_id = user_data.get("team_id")
        if not team_id:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid token: team_id missing."},
            )

        result = await update_email_ai_agent(
            team_id=team_id,
            agent_id=request_data.agent_id,
            name=request_data.name,
            gmail_account_id=request_data.gmail_account_id,
            system_prompt=request_data.system_prompt,
            knowledge_id=request_data.knowledge_id,
            tool_ids=request_data.tool_ids,
            llm_model=request_data.llm_model,
            reply_action=request_data.reply_action.model_dump(),
            routing_rule_ids=request_data.routing_rule_ids,
            recipient_rule_ids=request_data.recipient_rule_ids,
            email_format_template=request_data.email_format_template,
            flow_id=request_data.flow_id,
        )

        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            body = {
                "success": False,
                "message": result.get("message", "Failed to update email AI agent."),
            }
            if result.get("data") is not None:
                body["data"] = result.get("data")
            return JSONResponse(status_code=status_code, content=body)

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "agent": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in update_email_ai_agent_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while updating the email AI agent.",
            },
        )


async def list_team_email_ai_agents_controller(request_data: ListTeamEmailAiAgentsRequest):
    try:
        result = await list_team_email_ai_agents(team_id=request_data.team_id)
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch email AI agents."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "team_id": result["data"]["team_id"],
                "count": result["data"]["count"],
                "agents": result["data"]["agents"],
            },
        )

    except Exception as e:
        logger.error(f"Error in list_team_email_ai_agents_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while fetching email AI agents.",
            },
        )


async def trigger_agent_sync_controller(
    request_data: TriggerAgentSyncRequest,
    user_data: dict,
    background_tasks: BackgroundTasks,
):
    try:
        if not user_data or user_data.get("success") is False:
            return _unauthorized_response(user_data)

        user_id = user_data.get("user_id")
        team_id = user_data.get("team_id")
        if not user_id:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid token: user_id missing."},
            )
        if not team_id:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid token: team_id missing."},
            )

        result = await start_agent_inbox_sync(
            agent_id=request_data.agent_id,
            user_id=user_id,
            team_id=team_id,
        )
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to start inbox sync."),
                },
            )

        background_tasks.add_task(run_agent_inbox_sync, request_data.agent_id)

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "agent_id": result["data"]["agent_id"],
                "sync_status": result["data"]["sync_status"],
            },
        )

    except Exception as e:
        logger.error(f"Error in trigger_agent_sync_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while starting inbox sync.",
            },
        )


async def list_team_email_threads_controller(
    request_data: ListTeamEmailThreadsRequest,
    user_data: dict,
):
    try:
        auth_user = _get_authenticated_email_user(user_data)
        if isinstance(auth_user, JSONResponse):
            return auth_user

        if request_data.team_id.strip() != auth_user["team_id"].strip():
            return _forbidden_response("team_id does not match authenticated user.")

        result = await list_team_email_threads(
            team_id=request_data.team_id,
            page=request_data.page,
            limit=request_data.limit,
            role=auth_user["role"],
            user_id=auth_user["user_id"],
            user_department_id=auth_user["department_id"],
        )
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch email threads."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "team_id": result["data"]["team_id"],
                "count": result["data"]["count"],
                "threads": result["data"]["threads"],
                "pagination": result["data"]["pagination"],
            },
        )

    except Exception as e:
        logger.error(f"Error in list_team_email_threads_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while fetching email threads.",
            },
        )


async def get_email_thread_controller(
    request_data: GetEmailThreadRequest,
    user_data: dict,
):
    try:
        auth_user = _get_authenticated_email_user(user_data)
        if isinstance(auth_user, JSONResponse):
            return auth_user

        if request_data.team_id.strip() != auth_user["team_id"].strip():
            return _forbidden_response("team_id does not match authenticated user.")

        result = await get_email_thread_detail(
            team_id=request_data.team_id,
            thread_id=request_data.thread_id,
            page=request_data.page,
            limit=request_data.limit,
            role=auth_user["role"],
            user_id=auth_user["user_id"],
            user_department_id=auth_user["department_id"],
        )
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch email thread."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "thread": result["data"]["thread"],
                "count": result["data"]["count"],
                "messages": result["data"]["messages"],
                "pagination": result["data"]["pagination"],
            },
        )

    except Exception as e:
        logger.error(f"Error in get_email_thread_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while fetching the email thread.",
            },
        )


async def send_thread_ai_draft_controller(
    request_data: SendThreadAiDraftRequest,
    user_data: dict,
):
    try:
        auth_user = _get_authenticated_email_user(user_data)
        if isinstance(auth_user, JSONResponse):
            return auth_user

        if request_data.team_id.strip() != auth_user["team_id"].strip():
            return _forbidden_response("team_id does not match authenticated user.")

        result = await send_thread_ai_draft(
            team_id=request_data.team_id,
            thread_id=request_data.thread_id,
            role=auth_user["role"],
            user_id=auth_user["user_id"],
            user_department_id=auth_user["department_id"],
        )
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to send AI draft."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "data": result["data"],
            },
        )

    except Exception as e:
        logger.error(f"Error in send_thread_ai_draft_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while sending the AI draft.",
            },
        )
