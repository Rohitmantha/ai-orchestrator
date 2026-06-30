import pytest
import json
from app.agents.verifier.agent import VerificationAgent
from app.agents.verifier.models import VerificationStatus

class FakeVerifierLLMProvider:
    def __init__(self, behavior: str = "pass"):
        self.behavior = behavior

    async def generate(self, prompt: str) -> str:
        if self.behavior == "timeout":
            raise ValueError("Verification API Timeout")
            
        if self.behavior == "bad_json":
            return "This is a great output, I give it a PASS!" # Not JSON
            
        if self.behavior == "pass":
            return json.dumps({"status": "PASS", "reason": "Output meets all requirements."})
            
        if self.behavior == "fail_hallucination":
            return json.dumps({"status": "FAIL", "reason": "Agent hallucinated a fake company."})
            
        if self.behavior == "retry_incomplete":
            return json.dumps({"status": "RETRY", "reason": "Output is missing the second paragraph."})

@pytest.mark.asyncio
async def test_verifier_deterministic_missing_fields():
    """Fails fast on missing required fields without calling the LLM."""
    agent = VerificationAgent(llm_provider=FakeVerifierLLMProvider())
    output, logs = await agent.execute(
        task_instruction="Extract data", 
        agent_output={"title": "Report"}, 
        required_fields=["title", "author", "date"]
    )
    
    assert output.status == VerificationStatus.RETRY
    assert "author" in output.missing_fields
    assert "date" in output.missing_fields
    
    # Verify the LLM was never called to save money/time
    assert not any(log.event_type == "llm_call_started" for log in logs)

@pytest.mark.asyncio
async def test_verifier_deterministic_low_confidence():
    """Fails fast if the output provides a confidence score below the threshold."""
    agent = VerificationAgent(llm_provider=FakeVerifierLLMProvider())
    output, logs = await agent.execute(
        task_instruction="Analyze sentiment", 
        agent_output={"sentiment": "positive", "confidence_score": 0.65}, 
        min_confidence=0.85
    )
    
    assert output.status == VerificationStatus.RETRY
    assert "0.65" in output.reason
    assert not any(log.event_type == "llm_call_started" for log in logs)

@pytest.mark.asyncio
async def test_verifier_llm_pass():
    """Tests a perfect validation run."""
    agent = VerificationAgent(llm_provider=FakeVerifierLLMProvider(behavior="pass"))
    output, logs = await agent.execute("Write summary", {"text": "Good summary"}, ["text"])
    
    assert output.status == VerificationStatus.PASS
    assert any(log.event_type == "llm_call_started" for log in logs)

@pytest.mark.asyncio
async def test_verifier_llm_hallucination_fail():
    """Tests that the LLM correctly categorizes a hallucination as a hard FAIL."""
    agent = VerificationAgent(llm_provider=FakeVerifierLLMProvider(behavior="fail_hallucination"))
    output, _ = await agent.execute("Summarize facts", {"text": "Fake facts"})
    
    assert output.status == VerificationStatus.FAIL
    assert "hallucinated" in output.reason

@pytest.mark.asyncio
async def test_verifier_llm_incomplete_retry():
    """Tests that the LLM correctly categorizes incomplete work as a RETRY."""
    agent = VerificationAgent(llm_provider=FakeVerifierLLMProvider(behavior="retry_incomplete"))
    output, _ = await agent.execute("Write 2 paragraphs", {"text": "Only 1 paragraph."})
    
    assert output.status == VerificationStatus.RETRY
    assert "missing" in output.reason

@pytest.mark.asyncio
async def test_verifier_catches_network_timeouts():
    """If the verifier crashes, it safely returns RETRY to prevent bad data from passing."""
    agent = VerificationAgent(llm_provider=FakeVerifierLLMProvider(behavior="timeout"))
    output, logs = await agent.execute("Write summary", {"text": "text"})
    
    assert output.status == VerificationStatus.RETRY
    assert "Verification engine encountered an error" in output.reason
    assert any(log.event_type == "error" for log in logs)

@pytest.mark.asyncio
async def test_verifier_catches_malformed_json():
    """If the LLM responds conversationally instead of JSON, fail safely."""
    agent = VerificationAgent(llm_provider=FakeVerifierLLMProvider(behavior="bad_json"))
    output, _ = await agent.execute("Write summary", {"text": "text"})
    
    assert output.status == VerificationStatus.RETRY
    assert "error" in output.reason.lower()