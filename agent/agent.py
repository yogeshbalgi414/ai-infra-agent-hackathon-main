"""
agent/agent.py — LangChain agent init, tool registration, chat loop.
Owner: Person 3
Status: IMPLEMENTED (Epic 7)

LLM selection is driven by environment variables (priority order):
  1. AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT → AzureChatOpenAI (primary)
  2. GROQ_API_KEY                                 → ChatGroq (fallback)
  Neither set                                     → EnvironmentError
"""

import os
import logging

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from agent.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Maximum number of recent messages to include in each LLM call
CHAT_HISTORY_WINDOW = 6


def _build_llm():
    """
    Select and return the LLM based on available environment variables.

    Priority order:
      1. AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT → AzureChatOpenAI (primary)
      2. GROQ_API_KEY                                 → ChatGroq (fallback)
      Neither set                                     → EnvironmentError
    """
    azure_key = os.environ.get("AZURE_OPENAI_API_KEY")
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")

    if azure_key and azure_endpoint:
        try:
            from langchain_openai import AzureChatOpenAI
            logger.info("Using Azure OpenAI (gpt-5.3-chat) as primary LLM")
            return AzureChatOpenAI(
                azure_deployment="gpt-5.3-chat",
                azure_endpoint=azure_endpoint,
                api_key=azure_key,
                api_version="2024-05-01-preview",
                model_kwargs={"max_completion_tokens": 4096},
                temperature=1,
            )
        except ImportError:
            raise EnvironmentError(
                "AZURE_OPENAI_API_KEY is set but langchain-openai is not installed. "
                "Install it with: pip install langchain-openai"
            )

    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        try:
            from langchain_groq import ChatGroq
            logger.info("Using Groq LLM as fallback (AZURE_OPENAI_API_KEY not set)")
            return ChatGroq(
                model="llama-3.3-70b-versatile",
                api_key=groq_key,
                max_tokens=2048,
            )
        except ImportError:
            raise EnvironmentError(
                "GROQ_API_KEY is set but langchain-groq is not installed. "
                "Install it with: pip install langchain-groq"
            )

    raise EnvironmentError(
        "No LLM API key found. Set AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT (preferred) "
        "or GROQ_API_KEY (fallback)."
    )


def _make_region_bound_tools(region: str, session_id: str = None) -> list:
    """
    Return tool wrappers with DB-backed TTL caching.
    session_id is used as the cache key — reads/writes go to the chat_sessions
    scan_cache column, which works from any thread with no Streamlit dependency.
    Falls back to fetching fresh from AWS if DB is unavailable or cache is stale.
    """
    from langchain_core.tools import tool as lc_tool
    from cache.redis_cache import get_scan_cache, write_scan_cache

    EC2_RDS_TTL = 10      # minutes
    SECURITY_TTL = 10     # minutes

    @lc_tool
    def analyze_ec2_instances(region: str = region) -> dict:
        """
        Fetch and analyze all EC2 instances in the given AWS region.
        Returns classification, confidence score, cost estimates, and right-sizing
        recommendations for each instance.

        Use this tool when the user asks about EC2 instances, idle resources,
        overprovisioned compute, stopped instances, or EC2 cost savings.
        """
        cached = get_scan_cache(session_id, region, ttl_minutes=EC2_RDS_TTL)
        if cached and "ec2" in cached:
            logger.info("EC2: returning DB-cached result (session=%s)", session_id)
            return cached["ec2"]
        from agent.tools.ec2_tools import analyze_ec2_instances as _tool
        result = _tool.func(region)
        existing = get_scan_cache(session_id, region, ttl_minutes=EC2_RDS_TTL * 9999) or {}
        existing["ec2"] = result
        write_scan_cache(session_id, region, existing)
        return result

    @lc_tool
    def analyze_rds_instances(region: str = region) -> dict:
        """
        Fetch and analyze all RDS instances in the given AWS region.
        Returns classification, confidence score, cost estimates, and additional findings per instance.
        """
        cached = get_scan_cache(session_id, region, ttl_minutes=EC2_RDS_TTL)
        if cached and "rds" in cached:
            logger.info("RDS: returning DB-cached result (session=%s)", session_id)
            return cached["rds"]
        from agent.tools.rds_tools import analyze_rds_instances as _tool
        result = _tool.func(region)
        existing = get_scan_cache(session_id, region, ttl_minutes=EC2_RDS_TTL * 9999) or {}
        existing["rds"] = result
        write_scan_cache(session_id, region, existing)
        return result

    @lc_tool
    def analyze_security_groups(region: str = region) -> dict:
        """
        Fetch and analyze all Security Groups attached to running EC2 instances in the given region.
        Returns security findings with severity classification and specific remediation recommendations.
        Security findings are always higher priority than cost recommendations.

        Use this tool when the user asks about security risks, open ports, firewall rules,
        Security Groups, SSH exposure, RDP exposure, or database port exposure.
        """
        cached = get_scan_cache(session_id, region, ttl_minutes=SECURITY_TTL)
        if cached and "security" in cached:
            logger.info("Security: returning DB-cached result (session=%s)", session_id)
            return cached["security"]
        from agent.tools.security_tools import analyze_security_groups as _tool
        result = _tool.func(region)
        existing = get_scan_cache(session_id, region, ttl_minutes=SECURITY_TTL * 9999) or {}
        existing["security"] = result
        write_scan_cache(session_id, region, existing)
        return result

    @lc_tool
    def get_cost_summary(query: str) -> dict:
        """
        Fetch EC2 and RDS data (using cache if available) and return a cost summary.
        Returns total monthly spend, total waste, potential annual savings, and the
        top 3 recommended cost-saving actions ranked by impact.

        Use this tool when the user asks about total cost, cost savings,
        savings opportunities, or wants a cost summary across all resources.
        Pass any short string as query, e.g. "summary" — this tool fetches its own data internally.
        """
        from agent.tools.ec2_tools import analyze_ec2_instances as _ec2_tool
        from agent.tools.rds_tools import analyze_rds_instances as _rds_tool
        from analysis.cost_estimator import build_cost_summary

        cached = get_scan_cache(session_id, region, ttl_minutes=EC2_RDS_TTL * 9999) or {}

        if "ec2" in cached:
            ec2_results = cached["ec2"]
        else:
            ec2_results = _ec2_tool.func(region)
            cached["ec2"] = ec2_results
            write_scan_cache(session_id, region, cached)

        if "rds" in cached:
            rds_results = cached["rds"]
        else:
            rds_results = _rds_tool.func(region)
            cached["rds"] = rds_results
            write_scan_cache(session_id, region, cached)

        try:
            summary = build_cost_summary(ec2_results, rds_results)
            logger.info(
                "Cost summary: total=$%.2f/mo waste=$%.2f/mo annual_savings=$%.2f",
                summary.get("total_monthly_spend_usd", 0),
                summary.get("total_monthly_waste_usd", 0),
                summary.get("potential_annual_savings_usd", 0),
            )
            return summary
        except Exception as exc:
            logger.error("get_cost_summary failed: %s", exc)
            return {"error": str(exc)}

    @lc_tool
    def get_resource_overview(region: str = region) -> dict:
        """
        Fetch an overview of S3 buckets, Lambda functions, VPCs, unattached EBS volumes,
        and unattached Elastic IPs in the given AWS region.
        Returns counts, public access status for S3, and unused Lambda functions.

        Use this tool when the user asks about S3, Lambda, VPCs, EBS volumes,
        Elastic IPs, or wants a full resource inventory.
        """
        cached = get_scan_cache(session_id, region, ttl_minutes=EC2_RDS_TTL)
        if cached and "resource_overview" in cached:
            logger.info("Resource overview: returning DB-cached result (session=%s)", session_id)
            return cached["resource_overview"]
        from agent.tools.resource_tools import get_resource_overview as _tool
        result = _tool.func(region)
        existing = get_scan_cache(session_id, region, ttl_minutes=EC2_RDS_TTL * 9999) or {}
        existing["resource_overview"] = result
        write_scan_cache(session_id, region, existing)
        return result

    @lc_tool
    def get_actual_cost(months_back: int = 1) -> dict:
        """
        Fetch real billing data from AWS Cost Explorer for a specific calendar month.
        Returns actual spend broken down by service — reflects Reserved Instance
        discounts, Spot pricing, Savings Plans, and partial-month usage.
        This is your real AWS bill, not a theoretical on-demand estimate.

        months_back parameter:
          0 = current month to date (e.g. April 1 to today)
          1 = last full calendar month (e.g. all of March — 31 days)
          2 = two months ago (e.g. all of February — 28 days)
          3 = three months ago, etc.

        Use this tool when the user asks about their actual bill, real spend,
        what they are actually paying, Cost Explorer data, or a specific month's cost.
        Always use months_back=1 for "last month", months_back=0 for "this month".
        For "March" when current month is April, use months_back=1.
        For "February" when current month is April, use months_back=2.
        """
        from aws.cost_explorer_fetcher import fetch_actual_cost
        result = fetch_actual_cost(region, months_back=months_back)
        if result is None:
            return {
                "error": (
                    "Could not fetch Cost Explorer data. "
                    "Ensure ce:GetCostAndUsage IAM permission is granted."
                )
            }
        return result

    return [
        analyze_ec2_instances,
        analyze_rds_instances,
        analyze_security_groups,
        get_cost_summary,
        get_resource_overview,
        get_actual_cost,
    ]


def _create_trimmed_memory(window: int):
    """
    Create a ConversationBufferMemory whose load_memory_variables trims
    chat_history to the last `window` messages.
    Uses a subclass so AgentExecutor's BaseMemory type check passes.
    """
    from langchain.memory import ConversationBufferMemory

    class TrimmedConversationMemory(ConversationBufferMemory):
        _window: int = window

        def load_memory_variables(self, inputs):
            result = super().load_memory_variables(inputs)
            if result and "chat_history" in result:
                history = result["chat_history"]
                if isinstance(history, list) and len(history) > self._window:
                    result["chat_history"] = history[-self._window:]
            return result

    return TrimmedConversationMemory(
        memory_key="chat_history",
        return_messages=True,
    )


def create_agent(region: str, session_id: str = None, db_available: bool = False) -> AgentExecutor:
    """
    Initialize and return a LangChain AgentExecutor for the given AWS region.

    When db_available=True and session_id is provided, uses PostgresChatMessageHistory
    for persistent memory. Falls back to TrimmedConversationMemory otherwise.

    Args:
        region:       AWS region string, e.g. 'us-east-1'
        session_id:   UUID string for the current chat session (Epic 14)
        db_available: Whether PostgreSQL is reachable (Epic 14)

    Returns:
        Configured AgentExecutor ready to invoke
    """
    if not region:
        raise ValueError("region must be a non-empty string")

    llm = _build_llm()
    tools = _make_region_bound_tools(region, session_id=session_id)

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt)

    if db_available and session_id:
        try:
            from langchain_community.chat_message_histories import PostgresChatMessageHistory
            from langchain.memory import ConversationBufferMemory
            db_url = os.environ.get("CHAT_DB_URL", "postgresql://localhost:5432/ai_advisor")
            memory = ConversationBufferMemory(
                chat_memory=PostgresChatMessageHistory(
                    session_id=session_id,
                    connection_string=db_url,
                ),
                memory_key="chat_history",
                return_messages=True,
            )
            logger.info("Using PostgresChatMessageHistory for session %s", session_id)
        except Exception as exc:
            logger.warning("Failed to init PostgresChatMessageHistory: %s — falling back", exc)
            memory = _create_trimmed_memory(CHAT_HISTORY_WINDOW)
    else:
        memory = _create_trimmed_memory(CHAT_HISTORY_WINDOW)

    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        memory=memory,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=5,
    )

    logger.info("Agent created for region: %s", region)
    return executor