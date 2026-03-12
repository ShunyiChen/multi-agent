import operator
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Annotated, List

from dotenv import load_dotenv
from pydantic import BaseModel

from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import tool, InjectedToolCallId

from langgraph.graph import StateGraph, add_messages, END
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

from fastmcp import Client
from langchain_nvidia_ai_endpoints import ChatNVIDIA
import os

load_dotenv()

# =========================
# Config
# =========================

# MCP Server URL
DBHUB_MCP_URL = f"http://{os.getenv('IP_ADDRESS', 'localhost')}/mcp"

BASE_DIR = Path(__file__).parent
PROMPT_FILE = BASE_DIR / "prompts/dbhub.md"


# =========================
# Load Prompt
# =========================

def load_prompt():
    return PROMPT_FILE.read_text(encoding="utf-8")

dbhub_prompt = load_prompt()


# =========================
# MCP Client
# =========================

config = {
    "mcpServers": {
        "dbhub": {
            "url": DBHUB_MCP_URL,
            "transport": "http",
        }
    }
}

mcp_client = Client(config)

async def call_mcp(tool_name: str, arguments: dict):
    try:
        async with mcp_client:
            response = await mcp_client.call_tool(
                name=tool_name,
                arguments=arguments
            )
            if not response:
                return "No response from MCP server"
            
            # Convert response content to string if it's a list (common in MCP)
            if isinstance(response.content, list):
                return "\n".join([str(c.text) if hasattr(c, 'text') else str(c) for c in response.content])
            return str(response.content)
    except Exception as e:
        error_msg = str(e).lower()
        if "permission" in error_msg or "account" in error_msg or "forbidden" in error_msg or "unauthorized" in error_msg or "403" in error_msg or "401" in error_msg:
            return "权限不足"
        print(f"Error calling MCP tool {tool_name}: {e}")
        return f"Error calling {tool_name}: {e}"

# =========================
# Tools
# =========================

@tool
async def search_database_objects(object_type: str, keyword: str = "%"):
    """
    Search and list database structure/metadata ONLY (e.g., schemas, tables, columns, procedures, indexes).
    DO NOT use this tool to query or fetch actual table data/rows.
    object_type: MUST be one of 'schema', 'table', 'column', 'procedure', or 'index'.
    keyword: Supports SQL LIKE patterns for object names (default: '%' for all).
    """
    return await call_mcp("search_objects", {"object_type": object_type, "keyword": keyword})


@tool
async def execute_sql_query(sql: str):
    """
    Execute raw SQL queries (e.g., SELECT, UPDATE, DELETE) against the 'default' mysql database.
    ALWAYS use this tool when you need to fetch actual data records, run analytical queries, or look at the contents of a table.
    """
    return await call_mcp("execute_sql", {"sql": sql})


# =========================
# Output Model
# =========================

class DatabaseInsight(BaseModel):
    summary: str


@tool
async def generate_database_insight(
    summary: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
):
    """
    Generate analysis insight from database query results
    """

    insight = DatabaseInsight(summary=summary)

    return Command(
        update={
            "database_insights": [insight],
            "messages": [
                ToolMessage(
                    name="generate_database_insight",
                    content=insight.model_dump_json(),
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


# =========================
# State
# =========================

class DBHubState(BaseModel):

    messages: Annotated[List, add_messages] = []

    database_insights: Annotated[List[DatabaseInsight], operator.add] = []


# =========================
# Tools Registry
# =========================

tools = [
    search_database_objects,
    execute_sql_query,
    generate_database_insight,
]


# =========================
# LLM
# =========================

llm = init_chat_model("deepseek-chat")

# llm = ChatNVIDIA(
#   model="qwen/qwen3.5-397b-a17b",
#   api_key=os.getenv("NVIDIA_API_KEY"),
#   temperature=0.6,
#   top_p=0.95,
#   max_completion_tokens=64000,
# )

llm_with_tools = llm.bind_tools(tools)


# =========================
# Agent Node
# =========================

async def dbhub_agent(state: DBHubState):

    messages = [
        SystemMessage(
            # content=dbhub_prompt.format(
            #     current_datetime=datetime.now()
            # )
            content=dbhub_prompt
        ),
        *state.messages
    ]

    response = await llm_with_tools.ainvoke(messages)

    return {
        "messages": [response]
    }


# =========================
# Router
# =========================

def router(state: DBHubState):

    last_msg = state.messages[-1]

    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"

    return END


# =========================
# Graph
# =========================

builder = StateGraph(DBHubState)

builder.add_node("dbhub_agent", dbhub_agent)

builder.add_node("tools", ToolNode(tools))

builder.set_entry_point("dbhub_agent")

builder.add_edge("tools", "dbhub_agent")

builder.add_conditional_edges(
    "dbhub_agent",
    router,
    {
        "tools": "tools",
        END: END,
    },
)

graph = builder.compile(
    checkpointer=MemorySaver()
)