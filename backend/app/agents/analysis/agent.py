import json
from typing import Any, Optional
from app.agents.analysis.tools import MathCalculationTool, DataProcessingTool
from app.llm_providers.llm_provider import LLMProvider


class AnalysisAgent:
    def __init__(
        self,
        llm_provider: LLMProvider,
        math_tool: Optional[MathCalculationTool] = None,
        data_tool: Optional[DataProcessingTool] = None,
    ):
        self.llm = llm_provider
        self.math_tool = math_tool
        self.data_tool = data_tool

    async def execute(self, task_id: str, task_input: dict[str, Any]) -> dict[str, Any]:
        task_instruction = task_input.get("description", str(task_input))

        prompt = (
            f"Perform a comprehensive analysis for this task: '{task_instruction}'.\n\n"
            "Respond ONLY with a valid JSON object, no markdown fences.\n"
            '{"reasoning": "your analysis here", "key_findings": [], "conclusion": "string"}'
        )

        try:
            response_text = await self.llm.generate(prompt)
            clean = response_text.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean)
            return {"result": parsed.get("reasoning", clean), "status": "completed", "data": parsed}
        except Exception as e:
            return {"result": f"Analysis failed: {e}", "status": "failed", "error": str(e)}