import { create } from 'zustand';

interface Task {
  task_id: string;
  status: string;
  priority: number;
  retries: number;
  dependencies: string[];
}

interface WorkflowState {
  workflowId: string | null;
  status: string;
  tasks: Task[];
  setWorkflowData: (workflowId: string, status: string, tasks: Task[]) => void;
  updateTaskStatus: (taskId: string, status: string) => void;
}

export const useWorkflowStore = create<WorkflowState>((set) => ({
  workflowId: null,
  status: 'PENDING',
  tasks: [],
  setWorkflowData: (workflowId, status, tasks) => set({ workflowId, status, tasks }),
  updateTaskStatus: (taskId, status) => set((state) => ({
    tasks: state.tasks.map(t => t.task_id === taskId ? { ...t, status } : t)
  })),
}));
