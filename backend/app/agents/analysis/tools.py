from abc import ABC, abstractmethod
from typing import Dict, Any

class MathCalculationTool(ABC):
    @abstractmethod
    async def calculate(self, expression: str) -> float:
        pass

class DataProcessingTool(ABC):
    @abstractmethod
    async def process(self, raw_data: Any) -> Dict[str, Any]:
        pass