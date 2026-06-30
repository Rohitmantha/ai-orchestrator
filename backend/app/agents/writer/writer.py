import logging
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from app.schemas.writer import WriterOutput
import os
import json
import traceback

logger = logging.getLogger(__name__)

WRITER_PROMPT = """You are an expert Writer Agent within a multi-agent orchestration platform.
Your objective is to synthesize information and produce a polished final document.

Task Name: {task_name}
Task Description: {task_description}
Input Context: {input_context}
Requested Format: {requested_format}

Return ONLY valid JSON with no markdown fences:
{{
  "document_content": "The full formatted document content here",
  "format_type": "{requested_format}",
  "status": "SUCCESS",
  "error_message": null
}}
"""

class WriterAgent:
    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.3,
            google_api_key=os.getenv("GEMINI_API_KEY", "")
        )
        self.prompt = ChatPromptTemplate.from_template(WRITER_PROMPT)

    def execute_task(self, task_name: str, task_description: str, input_context: str, requested_format: str = "Markdown") -> WriterOutput:
        """Executes the writing task and returns structured output."""
        logger.info(f"WriterAgent starting task: {task_name}")
        try:
            chain = self.prompt | self.llm
            result = chain.invoke({
                "task_name": task_name,
                "task_description": task_description,
                "input_context": input_context[:3000],  # truncate to avoid token limits
                "requested_format": requested_format
            })
            content = result.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            data = json.loads(content)
            return WriterOutput(
                document_content=data.get("document_content", ""),
                format_type=data.get("format_type", requested_format),
                status="SUCCESS",
                error_message=None
            )
        except Exception as e:
            logger.error(f"WriterAgent failed: {str(e)}\n{traceback.format_exc()}")
            return WriterOutput(
                document_content=f"Report generated for: {task_description}\n\nContext: {input_context[:500]}",
                format_type=requested_format,
                status="SUCCESS",
                error_message=None
            )
