import pytest
import json
from app.agents.writer.agent import WriterAgent

class FakeWriterLLMProvider:
    def __init__(self, success: bool = True, target_format: str = "html"):
        self.success = success
        self.target_format = target_format

    async def generate(self, prompt: str) -> str:
        if not self.success:
            raise ValueError("Formatting engine timed out")
            
        if self.target_format == "html":
            content = "<div class='glass-panel dark-mode'><h2>Financial Analytics Summary</h2><p>Revenue increased by 15%.</p></div>"
        else:
            content = "# Financial Analytics Summary\nRevenue increased by 15%."
            
        mock_response = {
            "formatted_content": content,
            "content_type": self.target_format,
            "word_count": 6
        }
        return json.dumps(mock_response)

@pytest.mark.asyncio
async def test_writer_html_success():
    llm = FakeWriterLLMProvider(success=True, target_format="html")
    agent = WriterAgent(llm_provider=llm)
    
    # Mocking a financial analytics payload
    output, logs = await agent.execute(
        "Draft quarterly financial overview", 
        {"metrics": {"Q1": 500, "Q2": 575}}, 
        "html"
    )
    
    assert "glass-panel" in output.formatted_content
    assert output.content_type == "html"
    assert output.word_count == 6
    
    assert logs[0].event_type == "agent_invoked"
    assert logs[-1].event_type == "agent_response_received"

@pytest.mark.asyncio
async def test_writer_graceful_failure():
    agent = WriterAgent(llm_provider=FakeWriterLLMProvider(success=False))
    output, logs = await agent.execute("Draft report", {}, "markdown")
    
    assert "Formatting failed" in output.formatted_content
    assert output.content_type == "error"
    
    error_logs = [log for log in logs if log.event_type == "error"]
    assert len(error_logs) == 1