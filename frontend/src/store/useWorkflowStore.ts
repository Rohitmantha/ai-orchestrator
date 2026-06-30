import { create } from 'zustand';
import type { Task } from '../api/client';

type WorkflowStatus = 'idle' | 'submitting' | 'pending' | 'running' | 'completed' | 'failed' | 'planning' | 'scheduled' | 'degraded' | 'cancelled';

interface WorkflowStore {
  workflowId: string | null;
  status: WorkflowStatus;
  query: string;
  tasks: Task[];
  result: string | null;
  errorMessage: string | null;
  createdAt: string | null;
  logs: Array<{ message: string; level: string }>;

  setQuery: (q: string) => void;
  setSubmitting: () => void;
  setWorkflowId: (id: string) => void;
  setWorkflowStatus: (status: string, result?: string | null) => void;
  setTasks: (tasks: Task[]) => void;
  setLogs: (logs: Array<{ message: string; level: string }>) => void;
  setError: (msg: string) => void;
  reset: () => void;
}

const initialState = {
  workflowId: null,
  status: 'idle' as WorkflowStatus,
  query: '',
  tasks: [],
  result: null,
  errorMessage: null,
  createdAt: null,
  logs: [],
};

export const useWorkflowStore = create<WorkflowStore>((set) => ({
  ...initialState,

  setQuery: (q) => set({ query: q }),

  setSubmitting: () => set({ status: 'submitting', errorMessage: null, result: null, tasks: [], logs: [] }),

  setWorkflowId: (id) => set({ workflowId: id, status: 'pending', createdAt: new Date().toISOString(), logs: [] }),

  setWorkflowStatus: (status, result) =>
    set((state) => ({
      status: status as WorkflowStatus,
      result: result ?? state.result,
    })),

  setTasks: (tasks) => set({ tasks }),
  
  setLogs: (logs) => set({ logs }),

  setError: (msg) => set({ status: 'failed', errorMessage: msg }),

  reset: () => set(initialState),
}));