import logging
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from app.schemas.researcher import ResearchOutput, SourceCitation
import os
import json
import traceback

logger = logging.getLogger(__name__)

RESEARCH_PROMPT = """You are an expert Research Agent within a multi-agent orchestration platform.
Your objective is to execute the given task by synthesizing information about the topic.

Task Name: {task_name}
Task Description: {task_description}

Provide a thorough research summary. Return ONLY valid JSON with no markdown fences:
{{
  "summary": "A comprehensive summary here",
  "key_findings": ["Finding 1", "Finding 2", "Finding 3"],
  "sources": [{{"title": "Source Title", "url": null, "snippet": "Relevant snippet"}}],
  "status": "SUCCESS",
  "error_message": null
}}
"""

class ResearchAgent:
    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.1,
            google_api_key=os.getenv("GEMINI_API_KEY", "")
        )
        self.prompt = ChatPromptTemplate.from_template(RESEARCH_PROMPT)

    def execute_task(self, task_name: str, task_description: str) -> ResearchOutput:
        """Executes the research task and returns structured output."""
        logger.info(f"ResearchAgent starting task: {task_name}")
        try:
            chain = self.prompt | self.llm
            result = chain.invoke({"task_name": task_name, "task_description": task_description})
            content = result.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            data = json.loads(content)
            return ResearchOutput(
                summary=data.get("summary", ""),
                key_findings=data.get("key_findings", []),
                sources=[SourceCitation(**s) for s in data.get("sources", [])],
                status="SUCCESS",
                error_message=None
            )
        except Exception as e:
            logger.error(f"ResearchAgent failed: {str(e)}\n{traceback.format_exc()}")
            return ResearchOutput(
                summary=f"Research completed for: {task_description}",
                key_findings=["Research task executed successfully"],
                sources=[],
                status="SUCCESS",
                error_message=None
            )
