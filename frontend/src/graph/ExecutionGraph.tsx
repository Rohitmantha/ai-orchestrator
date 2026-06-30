import React, { useEffect } from 'react';
import ReactFlow, {
  type Node,
  type Edge,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  MarkerType,
  BackgroundVariant,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useWorkflowStore } from '../store/useWorkflowStore';

const statusStyle = (status: string): React.CSSProperties => {
  const styles: Record<string, React.CSSProperties> = {
    completed: { background: '#0d2b1a', border: '2px solid #10b981', color: '#34d399' },
    running:   { background: '#0d1f3c', border: '2px solid #3b82f6', color: '#60a5fa' },
    failed:    { background: '#2b0d0d', border: '2px solid #ef4444', color: '#f87171' },
    retrying:  { background: '#2b1a00', border: '2px solid #f59e0b', color: '#fbbf24' },
    pending:   { background: '#1a1f2e', border: '2px solid #475569', color: '#94a3b8' },
  };
  return styles[status] ?? styles['pending'];
};

const statusLabel: Record<string, string> = {
  completed: '✓ Completed',
  running:   '⟳ Running',
  failed:    '✗ Failed',
  retrying:  '↺ Retrying',
  pending:   '○ Pending',
};

export const ExecutionGraph: React.FC = () => {
  const { tasks } = useWorkflowStore();
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  useEffect(() => {
    if (!tasks || tasks.length === 0) return;

    // Layout: spread tasks horizontally with vertical offset for dependent tasks
    const depthMap: Record<string, number> = {};
    const getDepth = (taskId: string): number => {
      if (depthMap[taskId] !== undefined) return depthMap[taskId];
      const task = tasks.find(t => t.task_id === taskId);
      if (!task || task.dependencies.length === 0) {
        depthMap[taskId] = 0;
        return 0;
      }
      const maxParentDepth = Math.max(...task.dependencies.map(d => getDepth(d)));
      depthMap[taskId] = maxParentDepth + 1;
      return depthMap[taskId];
    };
    tasks.forEach(t => getDepth(t.task_id));

    // Group by depth for x-positioning
    const depthGroups: Record<number, string[]> = {};
    tasks.forEach(t => {
      const d = depthMap[t.task_id] ?? 0;
      if (!depthGroups[d]) depthGroups[d] = [];
      depthGroups[d].push(t.task_id);
    });

    const newNodes: Node[] = tasks.map((task) => {
      const depth = depthMap[task.task_id] ?? 0;
      const siblings = depthGroups[depth] ?? [task.task_id];
      const sibIdx = siblings.indexOf(task.task_id);
      const style = statusStyle(task.status);

      return {
        id: task.task_id,
        position: {
          x: depth * 280,
          y: sibIdx * 130,
        },
        data: {
          label: (
            <div style={{ fontFamily: 'sans-serif' }}>
              <div style={{ fontWeight: 700, fontSize: 13, color: style.color, marginBottom: 4 }}>
                {task.name || task.task_id}
              </div>
              <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 2 }}>
                {task.task_type}
              </div>
              <div style={{ fontSize: 11, fontWeight: 600, color: style.color }}>
                {statusLabel[task.status] ?? task.status}
              </div>
            </div>
          )
        },
        style: {
          ...style,
          borderRadius: 10,
          padding: '10px 14px',
          width: 200,
          boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
        },
      };
    });

    const newEdges: Edge[] = [];
    tasks.forEach(task => {
      task.dependencies.forEach(dep => {
        const isRunning = task.status === 'running' || task.status === 'pending';
        newEdges.push({
          id: `e-${dep}-${task.task_id}`,
          source: dep,
          target: task.task_id,
          animated: isRunning,
          markerEnd: { type: MarkerType.ArrowClosed, color: '#475569' },
          style: { stroke: '#475569', strokeWidth: 2 },
        });
      });
    });

    setNodes(newNodes);
    setEdges(newEdges);
  }, [tasks, setNodes, setEdges]);

  return (
    <div style={{ height: 340, width: '100%', borderRadius: 12, overflow: 'hidden', background: '#0a0f1e' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        attributionPosition="bottom-right"
      >
        <Background variant={BackgroundVariant.Dots} color="#1e293b" gap={20} />
        <Controls style={{ background: '#111827', border: '1px solid #1e293b' }} />
      </ReactFlow>
    </div>
  );
};