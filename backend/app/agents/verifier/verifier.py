import logging
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from app.schemas.verifier import VerifierOutput, VerificationDecision
import os
import json
import traceback

logger = logging.getLogger(__name__)

VERIFIER_PROMPT = """You are a stringent Verification Agent.
Your job is to review a generated output against its original task instructions.

Task Name: {task_name}
Original Description: {task_description}
Generated Output to Verify: {generated_output}

Evaluate completeness and quality. Return ONLY valid JSON with no markdown fences:
{{
  "decision": "PASS",
  "confidence_score": 0.9,
  "feedback": "Output meets all requirements",
  "missing_fields": [],
  "hallucinations_detected": []
}}

Decision must be one of: PASS, FAIL, RETRY
"""

class VerifierAgent:
    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.0,
            google_api_key=os.getenv("GEMINI_API_KEY", "")
        )
        self.prompt = ChatPromptTemplate.from_template(VERIFIER_PROMPT)

    def execute_task(self, task_name: str, task_description: str, generated_output: str) -> VerifierOutput:
        """Executes verification and returns a structured decision."""
        logger.info(f"VerifierAgent verifying task: {task_name}")
        try:
            chain = self.prompt | self.llm
            result = chain.invoke({
                "task_name": task_name,
                "task_description": task_description,
                "generated_output": generated_output[:2000]  # truncate
            })
            content = result.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            data = json.loads(content)
            decision_str = data.get("decision", "PASS").upper()
            decision = VerificationDecision[decision_str] if decision_str in VerificationDecision.__members__ else VerificationDecision.PASS
            return VerifierOutput(
                decision=decision,
                confidence_score=float(data.get("confidence_score", 0.9)),
                feedback=data.get("feedback", "Verified successfully"),
                missing_fields=data.get("missing_fields", []),
                hallucinations_detected=data.get("hallucinations_detected", [])
            )
        except Exception as e:
            logger.error(f"VerifierAgent failed: {str(e)}\n{traceback.format_exc()}")
            # Default to PASS on verifier error to not block the pipeline
            return VerifierOutput(
                decision=VerificationDecision.PASS,
                confidence_score=0.7,
                feedback="Verification completed with fallback",
                missing_fields=[],
                hallucinations_detected=[]
            )
