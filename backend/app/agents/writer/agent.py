from typing import Any
from app.llm_providers.llm_provider import LLMProvider, LLMProviderError

_WRITER_SCHEMA = {
    "type": "object",
    "properties": {
        "formatted_content": {"type": "string"},
        "content_type": {"type": "string"},
        "word_count": {"type": "integer"}
    },
    "required": ["formatted_content", "content_type", "word_count"],
    "additionalProperties": False,
}

class WriterAgent:
    def __init__(self, llm_provider: LLMProvider):
        self.llm = llm_provider

    async def execute(self, task_id: str, task_input: dict[str, Any]) -> dict[str, Any]:
        task_instruction = task_input.get("description", str(task_input))
        target_format = task_input.get("format", "markdown")

        user_prompt = (
            f"Task: {task_instruction}\n"
            f"Target Format: {target_format}\n"
        )

        try:
            parsed = await self.llm.generate_structured(
                system_prompt="You are an expert technical writer.",
                user_prompt=user_prompt,
                json_schema=_WRITER_SCHEMA,
                schema_name="writer_output"
            )
            
            return {
                "result": parsed.get("formatted_content", ""), 
                "status": "completed",
                "content_type": parsed.get("content_type", target_format),
                "word_count": parsed.get("word_count", 0)
            }
        except LLMProviderError as e:
            return {
                "result": f"Writer failed: {e}", 
                "status": "failed", 
                "error": str(e)
            }