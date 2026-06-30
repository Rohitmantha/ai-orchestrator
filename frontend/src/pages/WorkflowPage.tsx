import React, { useEffect } from 'react';
import { ExecutionGraph } from '../graph/ExecutionGraph';
import { useWorkflowStore } from '../store/workflowStore';

export const WorkflowPage: React.FC<{ workflowId: string }> = ({ workflowId }) => {
  const { status, setWorkflowData } = useWorkflowStore();

  useEffect(() => {
    // Simulated API Call to our FastAPI backend endpoints
    const fetchWorkflow = async () => {
      // Real API implementation would be:
      // const response = await fetch(`/api/v1/workflow/${workflowId}/tasks`);
      // const data = await response.json();
      
      // Mock data representing a workflow DAG
      const mockTasks = [
        { task_id: "task_1_search", status: "COMPLETED", priority: 1, retries: 0, dependencies: [] },
        { task_id: "task_2_search", status: "RUNNING", priority: 1, retries: 1, dependencies: [] },
        { task_id: "task_3_analyze", status: "PENDING", priority: 2, retries: 0, dependencies: ["task_1_search", "task_2_search"] },
        { task_id: "task_4_write", status: "PENDING", priority: 3, retries: 0, dependencies: ["task_3_analyze"] }
      ];
      
      setWorkflowData(workflowId, "RUNNING", mockTasks);
    };

    fetchWorkflow();
    
    // In a real application, we would set up a polling interval or WebSocket here
    // const interval = setInterval(fetchWorkflow, 3000);
    // return () => clearInterval(interval);
  }, [workflowId, setWorkflowData]);

  return (
    <div className="p-6 max-w-7xl mx-auto min-h-screen bg-gray-50">
      <div className="flex justify-between items-center mb-6 bg-white p-4 rounded-lg shadow-sm border border-gray-100">
        <h1 className="text-3xl font-extrabold text-gray-900 tracking-tight">Workflow Orchestration</h1>
        <div className="px-6 py-2 bg-blue-100 text-blue-800 rounded-full font-bold shadow-inner">
          Status: {status}
        </div>
      </div>
      
      <div className="mb-8 bg-white p-6 rounded-xl shadow-md border border-gray-200">
        <h2 className="text-2xl font-bold mb-4 text-gray-800 border-b pb-2">Task Dependency Graph (DAG)</h2>
        <ExecutionGraph />
      </div>
      
      <div className="bg-white p-6 rounded-xl shadow-md border border-gray-200">
        <h2 className="text-2xl font-bold mb-4 text-gray-800 border-b pb-2">Execution Logs</h2>
        <div className="bg-gray-900 text-green-400 p-5 rounded-lg font-mono text-sm h-64 overflow-y-auto shadow-inner space-y-2">
          <div><span className="text-blue-400">[14:00:01] [INFO]</span> Workflow {workflowId} initialized.</div>
          <div><span className="text-blue-400">[14:00:02] [INFO]</span> task_1_search dispatched to ResearchAgent_A.</div>
          <div><span className="text-blue-400">[14:00:02] [INFO]</span> task_2_search dispatched to ResearchAgent_B.</div>
          <div><span className="text-green-400">[14:00:08] [SUCCESS]</span> task_1_search completed validation.</div>
          <div><span className="text-yellow-400">[14:00:15] [WARN]</span> task_2_search timeout. RETRYING (1/3).</div>
          <div><span className="text-gray-400">... waiting for pending tasks ...</span></div>
        </div>
      </div>
    </div>
  );
};
