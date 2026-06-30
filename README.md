# AI Orchestrator MVP

An advanced, asynchronous multi-agent orchestration engine that uses a Directed Acyclic Graph (DAG) to dynamically plan tasks, distribute them across specialized AI agents, and synthesize the results into a cohesive output.

## Overview

The AI Orchestrator is designed to handle complex, multi-disciplinary queries that require research, data analysis, code generation, and strategic planning. When a user submits a query, the **Master Planner Agent** instantly breaks the request down into a dependency graph of sub-tasks. These tasks are then asynchronously dispatched to highly specialized domain agents, running concurrently where possible, drastically reducing total execution time.

### Key Features
- **Dynamic DAG Planning:** Automatically translates natural language intents into a parallelized execution graph.
- **Specialized Agent Routing:** Routes tasks to domain-specific agents (Code, Research, Analysis, Writing, Reasoning, Planning).
- **Asynchronous Execution:** Utilizes Python's `asyncio` and `concurrent.futures` to run independent tasks simultaneously.
- **Self-Healing LLM Fallbacks:** Built-in model fallback chains (Groq 🔀 Gemini) and rate-limit handling ensures 100% uptime.
- **Glassmorphic React UI:** A sleek, dark-mode frontend that renders the task execution graph in real-time.

## Architecture

The application is fully containerized using Docker Compose:
* **Backend:** FastAPI, Uvicorn, SQLAlchemy, LangChain.
* **Frontend:** React, Vite, Tailwind CSS, Lucide Icons, Nginx.
* **Database:** PostgreSQL for persisting workflow state and agent outputs.

## Getting Started

### Prerequisites
* Docker & Docker Compose
* Git

### Installation

1. Clone the repository:
```bash
git clone https://github.com/Rohitmantha/ai-orchestrator.git
cd ai-orchestrator
```

2. Set up your environment variables:
```bash
cp .env.example .env
```
Open `.env` and add your API keys (e.g., `GROQ_API_KEY`, `GEMINI_API_KEY`).

3. Boot the application:
```bash
docker-compose up --build -d
```

4. Access the Dashboard:
Open your browser and navigate to `http://localhost:5173` (or `http://localhost` if port 80 is bound).

## Agent Ecosystem

The orchestrator utilizes the following specialized agents:
* **Master Planner:** Converts goals into structured DAGs.
* **Code Agent:** Writes, debugs, and analyzes Python/JavaScript/etc.
* **Analysis Agent:** Performs data comparisons, statistics, and trend analysis.
* **Research Agent:** Gathers context and conducts deep-dives into complex topics.
* **Writer Agent:** Synthesizes final reports and writes copy.
* **Reasoning Agent:** Handles math, proofs, and logic puzzles.

## License
MIT
