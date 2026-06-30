from typing import List, Dict, Optional
from app.schemas.agent import AgentRegistration, AgentHealthStatus
import logging

logger = logging.getLogger(__name__)

class AgentRegistry:
    """
    In-memory or Redis-backed registry for tracking available agents.
    For this implementation, we use an in-memory dictionary.
    """
    def __init__(self):
        self._agents: Dict[str, AgentRegistration] = {}

    def register_agent(self, agent: AgentRegistration):
        """Registers a new agent or updates an existing one."""
        self._agents[agent.id] = agent
        logger.info(f"Agent registered: {agent.name} (ID: {agent.id})")

    def unregister_agent(self, agent_id: str):
        if agent_id in self._agents:
            del self._agents[agent_id]
            logger.info(f"Agent unregistered: {agent_id}")

    def update_agent_status(self, agent_id: str, load: Optional[int] = None, health: Optional[AgentHealthStatus] = None):
        """Heartbeat / status update for an agent."""
        if agent_id in self._agents:
            if load is not None:
                self._agents[agent_id].current_load = load
            if health is not None:
                self._agents[agent_id].health_status = health

    def find_best_agent(self, required_capabilities: List[str], task_type: Optional[str] = None) -> Optional[AgentRegistration]:
        """
        Dynamically select the best agent without hardcoded if-else logic.
        Scoring algorithm:
        1. Must match required capabilities and task type.
        2. Must be HEALTHY.
        3. Must have current_load < max_load.
        4. Score = (Priority weight) - (Load penalty)
        """
        candidate_agents = []

        for agent in self._agents.values():
            # 1. Health check
            if agent.health_status != AgentHealthStatus.HEALTHY:
                continue
            
            # 2. Capacity check
            if agent.current_load >= agent.max_load:
                continue

            # 3. Capabilities match
            has_capabilities = all(cap in agent.capabilities for cap in required_capabilities)
            if not has_capabilities:
                continue

            # 4. Task type match (if specified)
            if task_type and task_type not in agent.supported_task_types:
                continue

            # Calculate a score: Higher priority is better, lower load is better.
            load_penalty = agent.current_load / agent.max_load
            score = agent.priority - load_penalty
            
            candidate_agents.append((score, agent))

        if not candidate_agents:
            return None

        # Sort by score descending
        candidate_agents.sort(key=lambda x: x[0], reverse=True)
        
        # Return the agent with the highest score
        best_agent = candidate_agents[0][1]
        return best_agent
