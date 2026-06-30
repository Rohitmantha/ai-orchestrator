import pytest
import json
from app.agents.analysis.agent import AnalysisAgent
from app.agents.analysis.tools import MathCalculationTool

class FakeAnalysisLLMProvider:
    async def generate(self, prompt: str) -> str:
        mock_response = {
            "comparison": "Option A is 20% faster than Option B.",
            "reasoning": "Based on the provided latency metrics, Option A consistently outperforms.",
            "data_analysis": {"avg_latency_A": 45, "avg_latency_B": 58},
            "mathematical_results": {"speedup_percentage": 22.4},
            "trend_analysis": "Latency for B is increasing over time."
        }
        return json.dumps(mock_response)

class FakeMathTool(MathCalculationTool):
    async def calculate(self, expression: str) -> float:
        return 22.4

@pytest.mark.asyncio
async def test_analysis_agent_success():
    llm = FakeAnalysisLLMProvider()
    math_tool = FakeMathTool()
    agent = AnalysisAgent(llm_provider=llm, math_tool=math_tool)
    
    output, logs = await agent.execute("Compare latency trends", {"raw_metrics": [45, 58]})
    
    assert output.comparison == "Option A is 20% faster than Option B."
    assert "consistently outperforms" in output.reasoning
    assert output.mathematical_results["speedup_percentage"] == 22.4
    assert "increasing over time" in output.trend_analysis
    
    assert logs[0].event_type == "agent_invoked"
    assert logs[-1].event_type == "agent_response_received"

@pytest.mark.asyncio
async def test_analysis_agent_graceful_failure():
    class FailingLLM:
        async def generate(self, prompt: str) -> str:
            raise ValueError("Context window exceeded")
            
    agent = AnalysisAgent(llm_provider=FailingLLM())
    output, logs = await agent.execute("Analyze this", {})
    
    assert "Analysis failed" in output.reasoning
    assert "Context window exceeded" in output.reasoning
    assert output.mathematical_results == {}
    
    error_logs = [log for log in logs if log.event_type == "error"]
    assert len(error_logs) == 1