import { useEffect, useRef } from 'react';
import { getWorkflowStatus, getWorkflowTasks } from '../api/client';
import { useWorkflowStore } from '../store/useWorkflowStore';

const TERMINAL_STATES = new Set(['completed', 'failed', 'cancelled']);
const POLL_INTERVAL_MS = 3000;

export const useWorkflowPoller = () => {
  const { workflowId, status, setWorkflowStatus, setTasks, setLogs, setError } = useWorkflowStore();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Stop polling if no workflow or already in a terminal state
    if (!workflowId || TERMINAL_STATES.has(status)) {
      if (intervalRef.current) clearInterval(intervalRef.current);
      return;
    }

    const poll = async () => {
      try {
        const [workflowStatus, tasks] = await Promise.all([
          getWorkflowStatus(workflowId),
          getWorkflowTasks(workflowId),
        ]);

        setWorkflowStatus(workflowStatus.status, workflowStatus.result);
        setTasks(tasks);
        if (workflowStatus.logs) {
          setLogs(workflowStatus.logs);
        }

        if (TERMINAL_STATES.has(workflowStatus.status)) {
          if (intervalRef.current) clearInterval(intervalRef.current);
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Polling failed';
        // Don't immediately fail — network blip could cause 1 bad poll
        console.warn('Polling error:', msg);
      }
    };

    poll();
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [workflowId, status, setWorkflowStatus, setTasks, setError]);
};