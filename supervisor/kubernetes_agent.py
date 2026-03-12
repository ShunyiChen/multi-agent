import operator
import httpx
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Annotated

from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.graph import StateGraph, add_messages, END
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

from langchain.chat_models import init_chat_model
from datetime import datetime
from pathlib import Path
from fastmcp import Client
from langchain_nvidia_ai_endpoints import ChatNVIDIA
import os

load_dotenv()

# =========================
# Config
# =========================

# MCP Server URL
K8S_MCP_URL = f"http://{os.getenv('IP_ADDRESS', 'localhost')}/mcp"

BASE_DIR = Path(__file__).parent
PROMPT_FILE = BASE_DIR / "prompts/kubernetes.md"

# =========================
# Load Prompt
# =========================

def load_prompt():
    return PROMPT_FILE.read_text(encoding="utf-8")

kubernetes_prompt = load_prompt()

# =========================
# MCP HTTP Client
# =========================

config = {
    "mcpServers": {
        "dbhub": {
            "url": K8S_MCP_URL,
            "transport": "http",
        }
    }
}

mcp_client = Client(config)

import asyncio

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
        raise e


# =========================
# Tools
# =========================

@tool
async def list_namespaces():
    """List all Kubernetes namespaces"""
    return await call_mcp("namespaces_list", {})

@tool
async def list_events(namespace: str | None = None):
    """
    List Kubernetes cluster events
    """
    return await call_mcp(
        "events_list",
        {
            "namespace": namespace
        }
    )

@tool
async def list_pods(
    fieldSelector: str | None = None,
    labelSelector: str | None = None,
):
    """
    List all pods in cluster
    """
    return await call_mcp(
        "pods_list",
        {
            "fieldSelector": fieldSelector,
            "labelSelector": labelSelector
        }
    )

@tool
async def list_pods_in_namespace(
    namespace: str,
    fieldSelector: str | None = None,
    labelSelector: str | None = None
):
    """
    List pods in namespace
    """

    return await call_mcp(
        "pods_list_in_namespace",
        {
            "namespace": namespace,
            "fieldSelector": fieldSelector,
            "labelSelector": labelSelector
        }
    )

@tool
async def get_pod(
    name: str,
    namespace: str | None = None
):
    """
    Get pod details
    """

    return await call_mcp(
        "pods_get",
        {
            "name": name,
            "namespace": namespace
        }
    )

@tool
async def delete_pod(
    name: str,
    namespace: str | None = None
):
    """
    Delete pod
    """

    return await call_mcp(
        "pods_delete",
        {
            "name": name,
            "namespace": namespace
        }
    )

@tool
async def get_pod_logs(
    name: str,
    namespace: str | None = None,
    container: str | None = None,
    tail: int = 100
):
    """
    Get pod logs
    """

    return await call_mcp(
        "pods_log",
        {
            "name": name,
            "namespace": namespace,
            "container": container,
            "tail": tail
        }
    )

@tool
async def exec_pod(
    name: str,
    command: list[str],
    namespace: str | None = None,
    container: str | None = None
):
    """
    Execute command in pod
    """

    return await call_mcp(
        "pods_exec",
        {
            "name": name,
            "namespace": namespace,
            "container": container,
            "command": command
        }
    )

@tool
async def run_pod(
    image: str,
    name: str | None = None,
    namespace: str | None = None,
    port: int | None = None
):
    """
    Run a new pod
    """

    return await call_mcp(
        "pods_run",
        {
            "image": image,
            "name": name,
            "namespace": namespace,
            "port": port
        }
    )

@tool
async def nodes_top(
    name: str | None = None,
    label_selector: str | None = None
):
    """
    Get node resource usage
    """

    return await call_mcp(
        "nodes_top",
        {
            "name": name,
            "label_selector": label_selector
        }
    )

@tool
async def node_stats(
    name: str
):
    """
    Get node detailed metrics
    """

    return await call_mcp(
        "nodes_stats_summary",
        {
            "name": name
        }
    )

@tool
async def node_logs(
    name: str,
    query: str,
    tailLines: int = 100
):
    """
    Get node logs
    """

    return await call_mcp(
        "nodes_log",
        {
            "name": name,
            "query": query,
            "tailLines": tailLines
        }
    )

@tool
async def list_resources(
    apiVersion: str,
    kind: str,
    namespace: str | None = None,
    labelSelector: str | None = None,
):
    """
    List kubernetes resources
    """

    return await call_mcp(
        "resources_list",
        {
            "apiVersion": apiVersion,
            "kind": kind,
            "namespace": namespace,
            "labelSelector": labelSelector
        }
    )

@tool
async def get_resource(
    apiVersion: str,
    kind: str,
    name: str,
    namespace: str | None = None
):
    """
    Get kubernetes resource
    """

    return await call_mcp(
        "resources_get",
        {
            "apiVersion": apiVersion,
            "kind": kind,
            "name": name,
            "namespace": namespace
        }
    )

@tool
async def apply_resource(
    resource: str
):
    """
    Apply Kubernetes resource YAML or JSON
    """

    return await call_mcp(
        "resources_create_or_update",
        {
            "resource": resource
        }
    )


@tool
async def delete_resource(
    apiVersion: str,
    kind: str,
    name: str,
    namespace: str | None = None
):
    """
    Delete kubernetes resource
    """

    return await call_mcp(
        "resources_delete",
        {
            "apiVersion": apiVersion,
            "kind": kind,
            "name": name,
            "namespace": namespace
        }
    )

@tool
async def scale_resource(
    apiVersion: str,
    kind: str,
    name: str,
    namespace: str | None = None,
    scale: int | None = None
):
    """
    Get or update scale
    """

    return await call_mcp(
        "resources_scale",
        {
            "apiVersion": apiVersion,
            "kind": kind,
            "name": name,
            "namespace": namespace,
            "scale": scale
        }
    )

# =========================
# Output Model
# =========================

class K8sInsight(BaseModel):
    summary: str


@tool
async def generate_k8s_report(
    summary: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
):
    """
    Generate Kubernetes analysis report.
    """

    report = K8sInsight.model_validate({
        "summary": summary
    })

    return Command(
        update={
            "k8s_reports": [report],
            "messages": [
                ToolMessage(
                    name="generate_k8s_report",
                    content=report.model_dump_json(),
                    tool_call_id=tool_call_id
                )
            ]
        }
    )


# =========================
# State
# =========================

class KubernetesState(BaseModel):

    messages: Annotated[list, add_messages] = []

    k8s_reports: Annotated[list, operator.add] = []


# =========================
# Tools
# =========================

tools = [

    # cluster
    list_namespaces,
    list_events,

    # pods
    list_pods,
    list_pods_in_namespace,
    get_pod,
    delete_pod,
    get_pod_logs,
    exec_pod,
    run_pod,

    # nodes
    nodes_top,
    node_stats,
    node_logs,

    # resources
    list_resources,
    get_resource,
    apply_resource,
    delete_resource,
    scale_resource,

    # report
    generate_k8s_report
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
# Agent
# =========================

async def kubernetes_agent(state: KubernetesState):

    messages = [
        SystemMessage(
            # content=kubernetes_prompt.format(
            #     current_datetime=datetime.now()
            # )
            content=kubernetes_prompt
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

async def router(state: KubernetesState):

    if state.messages[-1].tool_calls:
        return "tools"

    return END


# =========================
# Graph
# =========================

builder = StateGraph(KubernetesState)

builder.add_node("kubernetes_agent", kubernetes_agent)

builder.add_node("tools", ToolNode(tools))

builder.set_entry_point("kubernetes_agent")

builder.add_edge("tools", "kubernetes_agent")

builder.add_conditional_edges(
    "kubernetes_agent",
    router,
    {
        "tools": "tools",
        END: END
    }
)

graph = builder.compile(checkpointer=MemorySaver())