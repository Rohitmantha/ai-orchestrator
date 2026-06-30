import React, { useState } from 'react';
import type { Task } from '../api/client';
import { CheckCircle, XCircle, Clock, Loader2, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';

const statusConfig: Record<string, { icon: React.ReactNode; color: string; bg: string; border: string }> = {
  pending:   { icon: <Clock size={12} />,    color: 'text-yellow-400', bg: 'bg-yellow-400/5',  border: 'border-yellow-400/20' },
  running:   { icon: <Loader2 size={12} className="animate-spin" />, color: 'text-blue-400', bg: 'bg-blue-400/5', border: 'border-blue-400/20' },
  completed: { icon: <CheckCircle size={12} />, color: 'text-emerald-400', bg: 'bg-emerald-400/5', border: 'border-emerald-400/20' },
  verified:  { icon: <CheckCircle size={12} />, color: 'text-emerald-400', bg: 'bg-emerald-400/5', border: 'border-emerald-400/20' },
  failed:    { icon: <XCircle size={12} />,  color: 'text-red-400',    bg: 'bg-red-400/5',    border: 'border-red-400/20' },
  skipped:   { icon: <AlertCircle size={12} />, color: 'text-slate-500', bg: 'bg-slate-400/5', border: 'border-slate-600/20' },
};

const typeColor = (taskType?: string): string => {
  if (!taskType) return 'bg-slate-500/10 text-slate-400';
  const t = taskType.toLowerCase();
  if (t.includes('research') || t.includes('web_search')) return 'bg-violet-500/10 text-violet-400';
  if (t.includes('analys') || t.includes('data')) return 'bg-cyan-500/10 text-cyan-400';
  if (t.includes('writ') || t.includes('text_gen') || t.includes('synth')) return 'bg-amber-500/10 text-amber-400';
  if (t.includes('code') || t.includes('program') || t.includes('debug')) return 'bg-pink-500/10 text-pink-400';
  if (t.includes('reason') || t.includes('logic') || t.includes('math')) return 'bg-orange-500/10 text-orange-400';
  if (t.includes('plan') || t.includes('strateg')) return 'bg-blue-500/10 text-blue-400';
  if (t.includes('creat') || t.includes('brain')) return 'bg-rose-500/10 text-rose-400';
  if (t.includes('answer') || t.includes('qa')) return 'bg-green-500/10 text-green-400';
  return 'bg-slate-500/10 text-slate-400';
};

const TaskCard: React.FC<{ task: Task }> = ({ task }) => {
  const [expanded, setExpanded] = useState(false);
  const cfg = statusConfig[task.status] ?? statusConfig['pending'];
  const hasResult = !!task.result;

  return (
    <div className={`border ${cfg.border} ${cfg.bg} rounded-xl p-3 transition-all duration-200`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="text-xs font-semibold text-slate-200 leading-snug flex-1">{task.name}</span>
        <span className={`flex items-center gap-1 text-xs font-medium ${cfg.color} shrink-0`}>
          {cfg.icon} {task.status}
        </span>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-md ${typeColor(task.task_type)}`}>
          {task.task_type}
        </span>
        {task.agent_name && (
          <span className="text-[10px] text-slate-600">→ {task.agent_name}</span>
        )}
      </div>

      {task.error_message && (
        <p className="mt-2 text-[11px] text-red-400 leading-snug">{task.error_message}</p>
      )}

      {hasResult && (
        <div className="mt-2">
          <button
            onClick={() => setExpanded(e => !e)}
            className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
          >
            {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            {expanded ? 'Hide output' : 'Show output'}
          </button>
          {expanded && (
            <p className="mt-1.5 text-[11px] text-slate-400 leading-relaxed whitespace-pre-wrap max-h-32 overflow-y-auto pr-1">
              {task.result}
            </p>
          )}
        </div>
      )}
    </div>
  );
};

export default TaskCard;