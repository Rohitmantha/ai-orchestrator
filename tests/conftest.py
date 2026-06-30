import sys
from pathlib import Path

# This dynamically finds the C:\projects\ai-orchestrator\backend folder 
# and adds it to Python's path so 'from app...' works everywhere.
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))