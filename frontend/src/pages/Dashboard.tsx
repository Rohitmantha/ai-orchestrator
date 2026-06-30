import React, { useState } from 'react';
import { createWorkflow } from '../api/client';
import { useWorkflowStore } from '../store/useWorkflowStore';
import { useWorkflowPoller } from '../hooks/useWorkflowPoller';
import { ExecutionGraph } from '../graph/ExecutionGraph';
import TaskCard from '../components/TaskCard';
import { Send, RotateCcw, Loader2, CheckCircle, XCircle, Clock, Zap, Terminal } from 'lucide-react';

const Dashboard: React.FC = () => {
  const [inputQuery, setInputQuery] = useState('');
  const [submitError, setSubmitError] = useState<string | null>(null);

  const {
    workflowId, status, tasks, result, logs, errorMessage, createdAt,
    setQuery, setSubmitting, setWorkflowId, setError, reset,
  } = useWorkflowStore();

  useWorkflowPoller();

  const isActive = status === 'running' || status === 'pending' || status === 'submitting';

  const handleSubmit = async () => {
    if (!inputQuery.trim() || isActive) return;
    setSubmitError(null);
    setQuery(inputQuery.trim());
    setSubmitting();

    try {
      const res = await createWorkflow(inputQuery.trim());
      setWorkflowId(res.workflow_id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to submit workflow';
      setError(msg);
      setSubmitError(msg);
    }
  };

  const handleReset = () => {
    reset();
    setInputQuery('');
    setSubmitError(null);
  };

  const completedCount = tasks.filter(t => t.status === 'completed').length;
  const runningCount   = tasks.filter(t => t.status === 'running').length;
  const failedCount    = tasks.filter(t => t.status === 'failed').length;

  const statusLabel: Record<string, string> = {
    idle: 'Ready', submitting: 'Submitting', pending: 'Pending',
    planning: 'Planning', scheduled: 'Scheduled',
    running: 'Running', completed: 'Completed',
    degraded: 'Degraded', failed: 'Failed', cancelled: 'Cancelled',
  };

  const statusDot: Record<string, string> = {
    idle: 'bg-slate-500',
    submitting: 'bg-blue-400 animate-pulse',
    pending: 'bg-yellow-400 animate-pulse',
    planning: 'bg-purple-400 animate-pulse',
    scheduled: 'bg-cyan-400 animate-pulse',
    running: 'bg-blue-400 animate-pulse',
    completed: 'bg-emerald-400',
    degraded: 'bg-yellow-400',
    failed: 'bg-red-400',
    cancelled: 'bg-slate-400',
  };

  return (
    <div className="min-h-screen bg-[#0a0f1e] text-slate-100 flex flex-col">

      {/* Top bar */}
      <header className="border-b border-slate-800 bg-[#0d1526]/80 backdrop-blur px-6 py-3 flex items-center justify-between sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center">
            <Zap size={14} className="text-white" />
          </div>
          <div>
            <span className="font-semibold text-white text-sm tracking-tight">AI Orchestrator</span>
            <span className="ml-2 text-xs text-slate-500">Multi-Agent Platform</span>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className={`w-1.5 h-1.5 rounded-full ${statusDot[status] ?? 'bg-slate-500'}`} />
          <span className="text-slate-400">{statusLabel[status] ?? status}</span>
          {workflowId && (
            <span className="text-slate-600 font-mono ml-2">{workflowId.slice(0, 8)}…</span>
          )}
        </div>
      </header>

      <main className="flex-1 max-w-5xl mx-auto w-full px-6 py-8 space-y-6">

        {/* Query box */}
        <div className="bg-[#111827] border border-slate-700/60 rounded-2xl p-5 shadow-xl">
          <label className="block text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">
            Query
          </label>
          <textarea
            className="w-full bg-[#0a0f1e] border border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-100 placeholder-slate-600 resize-none focus:outline-none focus:border-blue-500/70 focus:ring-1 focus:ring-blue-500/30 transition-all disabled:opacity-50"
            rows={3}
            placeholder="What do you want the agents to figure out?"
            value={inputQuery}
            onChange={e => setInputQuery(e.target.value)}
            disabled={isActive}
            onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) handleSubmit(); }}
          />
          {submitError && (
            <p className="mt-2 text-xs text-red-400">{submitError}</p>
          )}
          <div className="flex items-center justify-between mt-3">
            <span className="text-xs text-slate-600">Ctrl+Enter to submit</span>
            <div className="flex gap-2">
              <button
                onClick={handleReset}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 text-xs transition-colors"
              >
                <RotateCcw size={13} /> Reset
              </button>
              <button
                onClick={handleSubmit}
                disabled={!inputQuery.trim() || isActive}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-xs font-semibold transition-colors"
              >
                {isActive
                  ? <><Loader2 size={13} className="animate-spin" /> Running…</>
                  : <><Send size={13} /> Submit</>
                }
              </button>
            </div>
          </div>
        </div>

        {/* Stats */}
        {workflowId && (
          <div className="grid grid-cols-4 gap-3">
            {[
              { label: 'Total',     value: tasks.length,    icon: <Clock size={14} />,     color: 'text-slate-300',  border: 'border-slate-700/60' },
              { label: 'Completed', value: completedCount,  icon: <CheckCircle size={14} />, color: 'text-emerald-400', border: 'border-emerald-500/20' },
              { label: 'Running',   value: runningCount,    icon: <Loader2 size={14} className={runningCount > 0 ? 'animate-spin' : ''} />, color: 'text-blue-400', border: 'border-blue-500/20' },
              { label: 'Failed',    value: failedCount,     icon: <XCircle size={14} />,   color: 'text-red-400',    border: 'border-red-500/20' },
            ].map(s => (
              <div key={s.label} className={`bg-[#111827] border ${s.border} rounded-xl p-4`}>
                <div className={`flex items-center gap-1.5 text-xs mb-2 ${s.color}`}>
                  {s.icon} {s.label}
                </div>
                <div className="text-2xl font-bold text-white tabular-nums">{s.value}</div>
              </div>
            ))}
          </div>
        )}

        {/* Graph */}
        {workflowId && tasks.length > 0 && (
          <div className="bg-[#111827] border border-slate-700/60 rounded-2xl p-5">
            <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-4">
              Task Execution Graph
            </h2>
            <ExecutionGraph />
          </div>
        )}

        {/* Loading state while pending with no tasks yet */}
        {workflowId && tasks.length === 0 && isActive && (
          <div className="bg-[#111827] border border-slate-700/60 rounded-2xl p-8 flex flex-col items-center gap-3">
            <Loader2 size={32} className="animate-spin text-blue-400" />
            <p className="text-slate-400 text-sm">Planning workflow with AI agents…</p>
          </div>
        )}

        {/* Task cards */}
        {tasks.length > 0 && (
          <div className="bg-[#111827] border border-slate-700/60 rounded-2xl p-5">
            <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-4">
              Tasks · {tasks.length}
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {tasks.map(task => <TaskCard key={task.task_id} task={task} />)}
            </div>
          </div>
        )}

        {/* Result */}
        {result && (
          <div className="bg-[#0d1f14] border border-emerald-500/25 rounded-2xl p-5">
            <h2 className="text-xs font-semibold text-emerald-400 uppercase tracking-widest mb-3 flex items-center gap-2">
              <CheckCircle size={14} /> Result
            </h2>
            <p className="text-sm text-slate-200 whitespace-pre-wrap leading-relaxed">{result}</p>
          </div>
        )}

        {/* Error */}
        {errorMessage && status === 'failed' && (
          <div className="bg-[#1f0d0d] border border-red-500/25 rounded-2xl p-5">
            <h2 className="text-xs font-semibold text-red-400 uppercase tracking-widest mb-2 flex items-center gap-2">
              <XCircle size={14} /> Workflow Failed
            </h2>
            <p className="text-sm text-red-300">{errorMessage}</p>
          </div>
        )}

        {/* Live Logs */}
        {workflowId && logs && logs.length > 0 && (
          <div className="bg-[#080b13] border border-slate-800 rounded-2xl p-5">
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-4 flex items-center gap-2">
              <Terminal size={14} /> Activity Log
            </h2>
            <div className="font-mono text-[11px] leading-relaxed space-y-1.5 h-64 overflow-y-auto pr-2 custom-scrollbar">
              {logs.map((log, i) => (
                <div key={i} className={`flex gap-3 ${log.level === 'ERROR' ? 'text-red-400' : log.level === 'WARNING' ? 'text-yellow-400' : 'text-slate-400'}`}>
                  <span className="shrink-0 opacity-50">{new Date().toISOString().split('T')[1].slice(0,8)}</span>
                  <span className="shrink-0 w-12 font-bold opacity-75">[{log.level}]</span>
                  <span className="break-all">{log.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Footer */}
        {workflowId && createdAt && (
          <p className="text-center text-xs text-slate-700 pb-4">
            {workflowId} · started {new Date(createdAt).toLocaleTimeString()}
          </p>
        )}

      </main>
    </div>
  );
};

export default Dashboard;