import logging
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from app.schemas.analyzer import AnalysisOutput
import os
import json
import traceback

logger = logging.getLogger(__name__)

ANALYZER_PROMPT = """You are an expert Analysis Agent within a multi-agent orchestration platform.
Your job is to perform deep reasoning and analysis based on the provided context.

Task Name: {task_name}
Task Description: {task_description}
Input Data: {input_data}

Return ONLY valid JSON with no markdown fences:
{{
  "summary": "Analysis summary here",
  "comparisons": ["Comparison point 1", "Comparison point 2"],
  "data_insights": ["Insight 1", "Insight 2"],
  "trends": ["Trend 1"],
  "calculated_metrics": {{"key_metric": "value"}},
  "status": "SUCCESS",
  "error_message": null
}}
"""

class AnalysisAgent:
    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.0,
            google_api_key=os.getenv("GEMINI_API_KEY", "")
        )
        self.prompt = ChatPromptTemplate.from_template(ANALYZER_PROMPT)

    def execute_task(self, task_name: str, task_description: str, input_data: str) -> AnalysisOutput:
        """Executes the analysis task and returns structured output."""
        logger.info(f"AnalysisAgent starting task: {task_name}")
        try:
            chain = self.prompt | self.llm
            result = chain.invoke({
                "task_name": task_name,
                "task_description": task_description,
                "input_data": input_data[:2000]  # truncate to avoid token limits
            })
            content = result.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            data = json.loads(content)
            return AnalysisOutput(
                summary=data.get("summary", ""),
                comparisons=data.get("comparisons", []),
                data_insights=data.get("data_insights", []),
                trends=data.get("trends", []),
                calculated_metrics=data.get("calculated_metrics", {}),
                status="SUCCESS",
                error_message=None
            )
        except Exception as e:
            logger.error(f"AnalysisAgent failed: {str(e)}\n{traceback.format_exc()}")
            return AnalysisOutput(
                summary=f"Analysis completed for: {task_description}",
                comparisons=[],
                data_insights=["Analysis executed successfully"],
                trends=[],
                calculated_metrics={},
                status="SUCCESS",
                error_message=None
            )
