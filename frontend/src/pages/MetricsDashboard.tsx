import React, { useEffect, useState } from 'react';

// Mock data representing the PostgreSQL execution metrics
const MOCK_METRICS = [
  { agent: 'Planner', avg_time: '1.2s', avg_tokens: 850, success_rate: '99%' },
  { agent: 'Researcher', avg_time: '5.4s', avg_tokens: 3200, success_rate: '92%' },
  { agent: 'Analyzer', avg_time: '4.1s', avg_tokens: 4100, success_rate: '95%' },
  { agent: 'Writer', avg_time: '3.8s', avg_tokens: 2800, success_rate: '98%' },
];

export const MetricsDashboard: React.FC = () => {
  const [metrics] = useState(MOCK_METRICS);

  useEffect(() => {
    // In a real implementation, we would query:
    // GET /api/v1/metrics/agents
    // This connects to the PostgreSQL ExecutionLogs table.
  }, []);

  return (
    <div className="p-6 max-w-7xl mx-auto min-h-screen bg-gray-50">
      <div className="flex justify-between items-center mb-6 bg-white p-4 rounded-lg shadow-sm border border-gray-100">
        <h1 className="text-3xl font-extrabold text-gray-900 tracking-tight">System Observability Dashboard</h1>
        <div className="px-6 py-2 bg-green-100 text-green-800 rounded-full font-bold shadow-inner">
          System Status: HEALTHY
        </div>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <div className="bg-white p-6 rounded-xl shadow-md border border-gray-200">
          <h3 className="text-gray-500 text-sm font-semibold uppercase">Total Workflows</h3>
          <p className="text-3xl font-bold text-gray-900 mt-2">1,284</p>
        </div>
        <div className="bg-white p-6 rounded-xl shadow-md border border-gray-200">
          <h3 className="text-gray-500 text-sm font-semibold uppercase">Avg Workflow Duration</h3>
          <p className="text-3xl font-bold text-blue-600 mt-2">14.5s</p>
        </div>
        <div className="bg-white p-6 rounded-xl shadow-md border border-gray-200">
          <h3 className="text-gray-500 text-sm font-semibold uppercase">Total LLM Tokens</h3>
          <p className="text-3xl font-bold text-purple-600 mt-2">4.2M</p>
        </div>
        <div className="bg-white p-6 rounded-xl shadow-md border border-gray-200">
          <h3 className="text-gray-500 text-sm font-semibold uppercase">Global Retry Rate</h3>
          <p className="text-3xl font-bold text-red-500 mt-2">3.2%</p>
        </div>
      </div>
      
      <div className="bg-white p-6 rounded-xl shadow-md border border-gray-200">
        <h2 className="text-2xl font-bold mb-4 text-gray-800 border-b pb-2">Agent Performance Metrics</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Agent Type</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Avg Execution Time</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Avg Token Usage</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Success Rate</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {metrics.map((row, idx) => (
                <tr key={idx}>
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{row.agent}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{row.avg_time}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{row.avg_tokens}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{row.success_rate}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
