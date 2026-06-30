from langchain_google_genai import ChatGoogleGenerativeAI
from app.schemas.planner import PlannerOutput, TaskDefinition, DependencyDefinition
from app.agents.universal.agent import llm_invoke_with_retry
import os
import json
import logging

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = """You are the master Planner Agent for an Enterprise AI Orchestration Platform.
You decompose user queries into the MINIMUM number of necessary tasks (1–4).

AVAILABLE AGENT CAPABILITIES (choose the most specific one per task):
- "answer"          → Direct Q&A, quick facts, definitions
- "web_search"      → Research, in-depth information gathering
- "data_analysis"   → Data analysis, comparisons, statistics, trends
- "text_generation" → Writing, reports, summaries, synthesis
- "code_execution"  → Writing code, debugging, algorithms
- "reasoning"       → Math, logic, step-by-step problem solving
- "planning"        → Strategy, roadmaps, project planning
- "creative"        → Creative writing, brainstorming, ideation

RULES:
- Simple fact/math/definition → 1 task with ["answer"] or ["reasoning"]
- Research question → ["web_search"] then ["text_generation"]
- Data question → ["web_search"] then ["data_analysis"] then ["text_generation"]
- Code request → 1 task with ["code_execution"] (or add ["reasoning"] first if complex)
- Creative request → 1 task with ["creative"]
- Complex/multi-part → up to 4 tasks, each building on prior outputs
- task_id: snake_case, descriptive (e.g. "research_climate_change", "write_final_report")
- description: precise instructions telling the agent EXACTLY what to produce

Return ONLY this JSON (no markdown, no extra text):
{
  "workflow_id": "<workflow_id>",
  "tasks": [
    {"task_id": "...", "name": "...", "description": "...", "required_capabilities": ["..."]}
  ],
  "dependencies": [
    {"task_id": "...", "depends_on": ["..."]}
  ]
}"""


class PlannerAgent:
    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.1,
            google_api_key=os.getenv("GEMINI_API_KEY", "")
        )

    def _parse(self, content: str) -> dict:
        content = content.strip()
        # Strip markdown fences if present
        if "```" in content:
            parts = content.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    content = part
                    break
        return json.loads(content)

    def generate_plan(self, query: str, workflow_id: str, log_cb=None) -> PlannerOutput:
        prompt = f"""{PLANNER_SYSTEM}

User Query: {query}
Workflow ID: {workflow_id}

JSON Plan:"""
        try:
            content = llm_invoke_with_retry(prompt, temperature=0.1, log_cb=log_cb)
            data = self._parse(content)
            tasks = [TaskDefinition(**t) for t in data.get("tasks", [])]
            deps = [DependencyDefinition(**d) for d in data.get("dependencies", [])]
            if not tasks:
                raise ValueError("Empty task list returned")
            logger.info(f"[{workflow_id}] Plan: {[t.task_id for t in tasks]}")
            return PlannerOutput(workflow_id=workflow_id, tasks=tasks, dependencies=deps)
        except Exception as e:
            logger.error(f"[{workflow_id}] Planner failed: {e}. Using smart fallback.")
            return self._smart_fallback(query, workflow_id)

    def _smart_fallback(self, query: str, workflow_id: str) -> PlannerOutput:
        """Generates a reasonable plan without LLM based on query heuristics."""
        q = query.lower()
        if any(k in q for k in ["code", "implement", "write a function", "python", "javascript", "script", "debug"]):
            tasks = [TaskDefinition(task_id="code_task", name="Code Solution",
                                   description=f"Write code to: {query}", required_capabilities=["code_execution"])]
            deps = []
        elif any(k in q for k in ["calculate", "compute", "math", "solve", "equation", "proof"]):
            tasks = [TaskDefinition(task_id="compute_task", name="Compute Answer",
                                   description=f"Solve mathematically: {query}", required_capabilities=["reasoning"])]
            deps = []
        elif any(k in q for k in ["brainstorm", "creative", "story", "poem", "imagine", "invent"]):
            tasks = [TaskDefinition(task_id="creative_task", name="Creative Output",
                                   description=f"Create: {query}", required_capabilities=["creative"])]
            deps = []
        elif any(k in q for k in ["plan", "strategy", "roadmap", "how to build", "project"]):
            tasks = [TaskDefinition(task_id="plan_task", name="Strategic Plan",
                                   description=f"Create a detailed plan for: {query}", required_capabilities=["planning"])]
            deps = []
        else:
            # Default: research then write
            tasks = [
                TaskDefinition(task_id="research_task", name="Research",
                               description=f"Research thoroughly: {query}", required_capabilities=["web_search"]),
                TaskDefinition(task_id="write_report", name="Write Report",
                               description=f"Synthesize research into a comprehensive answer for: {query}", required_capabilities=["text_generation"]),
            ]
            deps = [DependencyDefinition(task_id="write_report", depends_on=["research_task"])]
        return PlannerOutput(workflow_id=workflow_id, tasks=tasks, dependencies=deps)
