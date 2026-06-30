import axios from "axios";

const BASE_URL = window.location.port === "5173" ? "http://localhost:8000/api/v1" : "/api/v1";

const api = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
  timeout: 60000,
});

export interface CreateWorkflowResponse {
  workflow_id: string;
  status: string;
  message: string;
}

export interface Task {
  task_id: string;
  name: string;
  task_type: string;
  status: string;
  result: string | null;
  error_message: string | null;
  agent_name: string | null;
  execution_order: number;
  dependencies: string[];
}

export interface WorkflowStatus {
  workflow_id: string;
  status: string;
  tasks: Array<{ task_id: string; status: string }>;
  result: string | null;
  logs: Array<{ message: string; level: string }>;
}

export interface WorkflowDetail {
  workflow_id: string;
  status: string;
  tasks: Task[];
  result: string | null;
  error_message: string | null;
  created_at: string | null;
}

export const createWorkflow = async (query: string): Promise<CreateWorkflowResponse> => {
  const res = await api.post("/workflow", { intent: query });
  return res.data;
};

export const getWorkflowStatus = async (workflowId: string): Promise<WorkflowStatus> => {
  const res = await api.get(`/workflow/${workflowId}`);
  return res.data;
};

export const getWorkflowTasks = async (workflowId: string): Promise<Task[]> => {
  const res = await api.get(`/workflow/${workflowId}/tasks`);
  return res.data.tasks;
};

export default api;
