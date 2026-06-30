from typing import Any
from app.llm_providers.llm_provider import LLMProvider, LLMProviderError

_VERIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["PASS", "FAIL", "RETRY"]},
        "reason": {"type": "string"},
        "missing_fields": {
            "type": "array", 
            "items": {"type": "string"}
        }
    },
    "required": ["status", "reason", "missing_fields"],
    "additionalProperties": False,
}

class VerificationAgent:
    def __init__(self, llm_provider: LLMProvider):
        self.llm = llm_provider

    async def execute(self, task_id: str, task_input: dict[str, Any]) -> dict[str, Any]:
        task_instruction = task_input.get("description", str(task_input))

        user_prompt = (
            f"Task to verify: '{task_instruction}'\n\n"
            "Evaluate whether this task description is complete and coherent."
        )

        try:
            parsed = await self.llm.generate_structured(
                system_prompt="You are a strict quality assurance Verification Agent.",
                user_prompt=user_prompt,
                json_schema=_VERIFICATION_SCHEMA,
                schema_name="verification_output"
            )
            
            status = parsed.get("status", "FAIL").upper()
            
            return {
                "result": parsed.get("reason", "Verification completed"),
                "status": "completed" if status == "PASS" else "failed",
                "verification_status": status,
                "missing_fields": parsed.get("missing_fields", [])
            }
        except LLMProviderError as e:
            return {
                "result": f"Verification error: {e}", 
                "status": "failed", 
                "verification_status": "FAIL",
                "missing_fields": []
            }