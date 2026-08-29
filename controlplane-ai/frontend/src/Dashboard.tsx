import { useEffect, useState } from 'react';
import { Shield, Activity, Users, AlertTriangle, CheckCircle, ChevronRight, Lock, Bot, ActivitySquare, BrainCircuit, XCircle, FileText, Settings, Zap, Download, TrendingUp, DollarSign, Gauge, RefreshCw } from 'lucide-react';
import { XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, Area, AreaChart, RadarChart, PolarGrid, PolarAngleAxis, Radar, BarChart, Bar, LineChart, Line, Legend } from 'recharts';

const TIER_COLORS: Record<string, string> = {
  realtime: 'text-sky-400 bg-sky-500/10 border-sky-500/20',
  standard: 'text-violet-400 bg-violet-500/10 border-violet-500/20',
  batch: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
};

function useElapsedSeconds(since: number | null) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(id);
  }, []);
  if (!since) return null;
  return Math.max(0, Math.round((Date.now() - since) / 1000));
}

export default function Dashboard() {
  const [metrics, setMetrics] = useState({
    total_requests: 0,
    escalated_requests: 0,
    approved_responses: 0,
    average_trust_score: 0,
    sanitized_responses: 0,
    blocked_responses: 0,
    decision_distribution: {} as Record<string, number>
  });

  const [logs, setLogs] = useState<any[]>([]);
  const [reviews, setReviews] = useState<any[]>([]);
  const [recommendations, setRecommendations] = useState<any[]>([]);
  const [selectedLog, setSelectedLog] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTexts, setEditTexts] = useState<Record<string, string>>({});
  const [modelStatus, setModelStatus] = useState<{presidio_pii: string, distilbert_safety: string, bart_bias: string} | null>(null);
  const [fullMetrics, setFullMetrics] = useState<any>(null);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const elapsedSinceUpdate = useElapsedSeconds(lastUpdated);

  const fetchData = () => {
    Promise.all([
      fetch('http://localhost:8000/api/v1/metrics').then(r => r.json()),
      fetch('http://localhost:8000/api/v1/audit').then(r => r.json()),
      fetch('http://localhost:8000/api/v1/reviews').then(r => r.json()),
      fetch('http://localhost:8000/api/v1/thresholds/recommendations').then(r => r.json()),
      fetch('http://localhost:8000/api/v1/models/status').then(r => r.json()),
      fetch('http://localhost:8000/api/v1/analytics/full').then(r => r.json())
    ]).then(([metricsData, logsData, reviewsData, recsData, statusData, fullMetricsData]) => {
      setMetrics(metricsData);
      setLogs(logsData);
      setReviews(reviewsData);
      setRecommendations(recsData);
      setModelStatus(statusData);
      setFullMetrics(fullMetricsData);
      setLoading(false);
      setLastUpdated(Date.now());
    }).catch(() => setLoading(false));
  };

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 5000);
    return () => clearInterval(id);
  }, []);

  const handleReviewAction = (logId: string, action: string, editedText?: string) => {
    let url = `http://localhost:8000/api/v1/review/${logId}?action=${action}`;
    if (action === 'edit') {
      const text = editedText || editTexts[logId];
      if (!text) return;
      url += `&edited_text=${encodeURIComponent(text)}`;
    }
    fetch(url, { 
      method: 'POST',
      headers: { 'X-User-Role': 'Admin' } // RBAC Auth
    })
      .then(() => {
        if (action === 'edit') setEditingId(null);
        fetchData();
      })
      .catch(console.error);
  };

  const handleRecAction = (recId: string, action: string) => {
    fetch(`http://localhost:8000/api/v1/thresholds/${recId}/${action}`, { 
      method: 'POST',
      headers: { 'X-User-Role': 'Admin' } // RBAC Auth
    })
      .then(fetchData)
      .catch(console.error);
  };

  const handleExport = () => {
    window.open('http://localhost:8000/api/v1/audit/export', '_blank');
  };

  // ── Chart data ────────────────────────────────────────────────────────────────
  const trustTrendData = [...logs].reverse().map(log => ({
    time: new Date(log.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    score: log.trust_score || 0,
  }));

  // Aggregate risk vector averages across all logs
  const riskVectorData = (() => {
    const dims = ['pii', 'injection', 'hallucination', 'bias', 'retrieval', 'ai_judge', 'session'];
    const totals: Record<string, number> = {};
    let count = 0;
    logs.forEach(log => {
      const rv = log.composite_risk?.risk_vectors;
      if (!rv) return;
      count++;
      dims.forEach(d => { totals[d] = (totals[d] || 0) + (rv[d] || 0); });
    });
    return dims.map(d => ({
      subject: d.charAt(0).toUpperCase() + d.slice(1),
      value: count > 0 ? +(((totals[d] || 0) / count) * 100).toFixed(1) : 0,
    }));
  })();

  // Detector latency bar chart from latest log
  const latencyData = (() => {
    const latest = logs[0];
    if (!latest?.detector_latencies) return [];
    return Object.entries(latest.detector_latencies).map(([name, ms]) => ({
      name: name.replace('_', ' '),
      ms: +(ms as number).toFixed(1),
    }));
  })();

  // Decision distribution
  const decisionData = (() => {
    const dist = metrics.decision_distribution;
    const colors: Record<string, string> = {
      ALLOW: '#10b981',
      SANITIZE: '#3b82f6',
      REVIEW: '#f59e0b',
      BLOCK: '#ef4444',
    };
    return Object.entries(dist).map(([k, v]) => ({
      name: k,
      value: +(v * 100).toFixed(1),
      color: colors[k] ?? '#6b7280',
    }));
  })();

  // Session risk timeline — cumulative risk across turns
  const sessionRiskData = [...logs]
    .reverse()
    .slice(0, 20)
    .map((log, idx) => ({
      turn: idx + 1,
      risk: +(log.cumulative_session_risk || 0).toFixed(1),
      trust: +(log.trust_score || 0).toFixed(1),
    }));

  // Cost per detector — where the governance "tax" actually goes
  const detectorCostData = (() => {
    const agg = fullMetrics?.avg_detector_cost_usd || {};
    return Object.entries(agg)
      .map(([name, cost]) => ({ name: name.replace('_', ' '), usd: cost as number }))
      .sort((a, b) => b.usd - a.usd);
  })();

  // Per-use-case cost & latency budget compliance table
  const useCaseCostRows = Object.entries(fullMetrics?.per_use_case || {}) as [string, any][];

  // ── Sub-components ────────────────────────────────────────────────────────────
  const TrustGauge = ({ score }: { score: number }) => {
    const r = 36, c = 2 * Math.PI * r;
    const color = score > 80 ? 'text-emerald-500' : score > 60 ? 'text-amber-500' : 'text-rose-500';
    return (
      <div className="relative inline-flex items-center justify-center">
        <svg className="w-24 h-24 -rotate-90">
          <circle cx="48" cy="48" r={r} stroke="currentColor" strokeWidth="8" fill="transparent" className="text-gray-700" />
          <circle cx="48" cy="48" r={r} stroke="currentColor" strokeWidth="8" fill="transparent"
            strokeDasharray={c} strokeDashoffset={c - (score / 100) * c}
            strokeLinecap="round" className={`${color} transition-all duration-1000`} />
        </svg>
        <div className="absolute flex flex-col items-center">
          <span className="text-2xl font-bold">{Math.round(score)}</span>
        </div>
      </div>
    );
  };

  const DecisionBadge = ({ d }: { d: string }) => {
    const cfg: Record<string, string> = {
      ALLOW: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
      SANITIZE: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
      REVIEW: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
      BLOCK: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
    };
    return (
      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${cfg[d] ?? 'bg-gray-700 text-gray-300 border-gray-600'}`}>
        {d}
      </span>
    );
  };

  const LogTrace = ({ log }: { log: any }) => {
    const isBlocked = log.decision === 'BLOCK';
    const isSanitized = log.decision === 'SANITIZE';
    const isEscalated = log.human_review_required;
    const rv = log.composite_risk?.risk_vectors || {};

    return (
      <div className="mt-4 space-y-4">
        {/* Risk vector mini bars */}
        {Object.keys(rv).length > 0 && (
          <div className="bg-gray-900/60 rounded-lg p-4 border border-gray-700/50">
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-3 font-bold">Evidence Fusion — Risk Vectors</p>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(rv).map(([dim, val]: [string, any]) => (
                <div key={dim}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-gray-400 capitalize">{dim}</span>
                    <span className="text-gray-300 font-mono">{(val * 100).toFixed(0)}%</span>
                  </div>
                  <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${val * 100}%`,
                        backgroundColor: val > 0.6 ? '#ef4444' : val > 0.3 ? '#f59e0b' : '#10b981'
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Pipeline steps */}
        <div className="pl-4 border-l-2 border-gray-700 space-y-6">
          {/* Security */}
          <div className="relative">
            <div className={`absolute -left-[25px] w-5 h-5 rounded-full flex items-center justify-center ${isBlocked ? 'bg-rose-500' : 'bg-emerald-500'} ring-4 ${isBlocked ? 'ring-rose-500/20' : 'ring-emerald-500/20'}`}>
              {isBlocked ? <XCircle size={10} className="text-white" /> : <Lock size={10} className="text-white" />}
            </div>
            <div className="bg-gray-800/80 p-3 rounded-lg border border-gray-700 text-xs">
              <p className="font-semibold text-gray-200 mb-1 flex items-center gap-2">
                Security & Policy Gate
                {isBlocked && <span className="text-rose-400">[BLOCKED]</span>}
                {isSanitized && <span className="text-blue-400">[SANITIZED]</span>}
              </p>
              <p className="text-gray-400">
                PII: {log.security_result?.pii_detected ? <span className="text-amber-400">MASKED [{log.security_result?.pii_types?.join(', ')}]</span> : <span className="text-emerald-400">CLEAN</span>}
                &nbsp;· Injection: <span className="font-mono">{(log.security_result?.prompt_injection_score || 0).toFixed(2)}</span>
              </p>
            </div>
          </div>

          {/* Router */}
          <div className="relative">
            <div className="absolute -left-[25px] w-5 h-5 bg-indigo-500 ring-4 ring-indigo-500/20 rounded-full flex items-center justify-center">
              <Bot size={10} className="text-white" />
            </div>
            <div className="bg-gray-800/80 p-3 rounded-lg border border-gray-700 text-xs">
              <p className="font-semibold text-gray-200 mb-1">Semantic Router</p>
              <p className="text-gray-400">Model: <span className="font-mono text-indigo-400">{log.selected_model}</span> · <span className="font-mono">{log.latency_ms?.toFixed(0)}ms</span></p>
            </div>
          </div>

          {/* Evaluation */}
          <div className="relative">
            <div className="absolute -left-[25px] w-5 h-5 bg-violet-500 ring-4 ring-violet-500/20 rounded-full flex items-center justify-center">
              <ActivitySquare size={10} className="text-white" />
            </div>
            <div className="bg-gray-800/80 p-3 rounded-lg border border-gray-700 text-xs">
              <p className="font-semibold text-gray-200 mb-1">Parallel Evidence Fusion (6 detectors)</p>
              <p className="text-gray-400">
                Primary risk: <span className="text-amber-400 font-mono">{log.primary_risk_category || 'NONE'}</span>
                &nbsp;· Verification: <span className={`font-mono ${log.verification_status === 'VERIFIED' ? 'text-emerald-400' : log.verification_status === 'CONTRADICTED' ? 'text-rose-400' : 'text-gray-300'}`}>{log.verification_status}</span>
              </p>
            </div>
          </div>

          {/* Decision */}
          <div className="relative">
            <div className={`absolute -left-[25px] w-5 h-5 rounded-full flex items-center justify-center ring-4 ${isEscalated ? 'bg-amber-500 ring-amber-500/20' : isBlocked ? 'bg-rose-500 ring-rose-500/20' : 'bg-emerald-500 ring-emerald-500/20'}`}>
              <BrainCircuit size={10} className="text-white" />
            </div>
            <div className={`p-3 rounded-lg border text-xs ${isEscalated ? 'bg-amber-500/5 border-amber-500/20' : isBlocked ? 'bg-rose-500/5 border-rose-500/20' : 'bg-emerald-500/5 border-emerald-500/20'}`}>
              <div className="flex justify-between">
                <span className="font-semibold text-gray-200">Governance Decision: <DecisionBadge d={log.decision} /></span>
                <span className={`text-lg font-black ${isEscalated ? 'text-amber-400' : isBlocked ? 'text-rose-400' : 'text-emerald-400'}`}>
                  {log.trust_score?.toFixed(1)}<span className="text-xs text-gray-500">/100</span>
                </span>
              </div>
              {(log.cost_usd !== undefined || log.latency_tier) && (
                <div className="flex items-center gap-3 mt-2 pt-2 border-t border-gray-700/50 text-[11px] text-gray-400">
                  {log.latency_tier && (
                    <span className={`px-1.5 py-0.5 rounded border ${TIER_COLORS[log.latency_tier] ?? 'text-gray-400 bg-gray-800 border-gray-700'}`}>
                      {log.latency_tier}
                    </span>
                  )}
                  <span className="font-mono">${(log.cost_usd ?? 0).toFixed(6)}</span>
                  {log.latency_budget_ms > 0 && (
                    <span className={`font-mono ${log.latency_budget_met === false ? 'text-rose-400' : ''}`}>
                      {log.latency_ms?.toFixed(0)}ms / {log.latency_budget_ms}ms budget
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  };

  if (loading && !metrics.total_requests) {
    return <div className="min-h-screen bg-[#0A0E17] flex items-center justify-center text-blue-400">Loading ControlPlane...</div>;
  }

  return (
    <div className="min-h-screen bg-[#0A0E17] text-gray-200 p-8 font-sans">
      <div className="max-w-[1400px] mx-auto">

        {/* Header */}
        <header className="flex justify-between items-end mb-8 border-b border-gray-800 pb-6">
          <div>
            <h1 className="text-3xl font-bold flex items-center gap-3 text-white">
              <div className="p-2 bg-blue-500/10 rounded-lg border border-blue-500/20">
                <Shield className="text-blue-500" size={32} />
              </div>
              ControlPlane.ai
            </h1>
            <p className="text-gray-500 mt-1 text-sm">Round 2 · Enterprise AI Governance & Policy Orchestration</p>
          </div>
          <div className="flex items-center gap-3">
            {modelStatus && (
              <div className="flex items-center gap-3 text-xs bg-gray-900 border border-gray-800 px-3 py-1.5 rounded-md text-gray-400 font-mono">
                <span className={modelStatus.presidio_pii === 'loaded' ? 'text-emerald-400' : 'text-amber-400'}>
                  Presidio {modelStatus.presidio_pii === 'loaded' ? '✅' : '🔄'}
                </span>
                <span className="text-gray-700">|</span>
                <span className={modelStatus.distilbert_safety === 'loaded' ? 'text-emerald-400' : 'text-amber-400'}>
                  DistilBERT {modelStatus.distilbert_safety === 'loaded' ? '✅' : '🔄'}
                </span>
                <span className="text-gray-700">|</span>
                <span className={modelStatus.bart_bias === 'loaded' ? 'text-emerald-400' : 'text-amber-400'}>
                  BART {modelStatus.bart_bias === 'loaded' ? '✅' : '🔄'}
                </span>
              </div>
            )}
            <button
              onClick={handleExport}
              className="flex items-center gap-2 text-sm bg-gray-800 border border-gray-700 px-3 py-1.5 rounded-md text-gray-400 hover:text-white hover:border-gray-500 transition-colors"
            >
              <Download size={14} /> Export CSV
            </button>
            <button
              onClick={fetchData}
              className="flex items-center gap-2 text-sm bg-gray-800 border border-gray-700 px-3 py-1.5 rounded-md text-gray-400 hover:text-white hover:border-gray-500 transition-colors group"
              title="Refresh now"
            >
              <Activity className="text-emerald-400 animate-pulse" size={16} />
              System Active
              <span className="text-gray-600">·</span>
              <RefreshCw size={12} className="text-gray-600 group-hover:text-gray-300 group-hover:rotate-180 transition-all duration-500" />
              <span className="text-gray-600 font-mono text-xs">
                {elapsedSinceUpdate !== null ? `${elapsedSinceUpdate}s ago` : ''}
              </span>
            </button>
          </div>
        </header>

        {/* KPI Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          {[
            { label: 'Total Requests', value: metrics.total_requests, icon: <Activity size={40} />, color: 'text-white' },
            { label: 'Avg Trust Score', value: `${metrics.average_trust_score} / 100`, icon: <Shield size={40} />, color: 'text-white' },
            { label: 'Auto-Approved', value: metrics.approved_responses, icon: <CheckCircle size={40} />, color: 'text-emerald-400' },
            { label: 'HITL Escalations', value: metrics.escalated_requests, icon: <Users size={40} />, color: 'text-amber-400' },
          ].map(kpi => (
            <div key={kpi.label} className="hover-lift bg-[#111827] p-5 rounded-xl border border-gray-800 relative overflow-hidden">
              <div className="absolute top-0 right-0 p-4 opacity-10">{kpi.icon}</div>
              <p className="text-gray-500 text-xs uppercase tracking-wider font-bold mb-1">{kpi.label}</p>
              <p className={`text-3xl font-black ${kpi.color}`}>{kpi.value}</p>
            </div>
          ))}
        </div>

        {/* Charts Row */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">

          {/* Trust trend */}
          <div className="lg:col-span-1 bg-[#111827] rounded-xl border border-gray-800 p-5">
            <h2 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
              <ActivitySquare className="text-blue-500" size={16} /> Trust Score Trend
            </h2>
            <div className="h-[180px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trustTrendData}>
                  <defs>
                    <linearGradient id="cScore" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
                  <XAxis dataKey="time" stroke="#4b5563" fontSize={10} />
                  <YAxis stroke="#4b5563" fontSize={10} domain={[0, 100]} width={28} />
                  <RechartsTooltip contentStyle={{ backgroundColor: '#1f2937', borderColor: '#374151', color: '#fff', borderRadius: '8px', fontSize: 12 }} />
                  <Area type="monotone" dataKey="score" stroke="#3b82f6" strokeWidth={2} fillOpacity={1} fill="url(#cScore)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Risk vector radar */}
          <div className="bg-[#111827] rounded-xl border border-gray-800 p-5">
            <h2 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
              <AlertTriangle className="text-amber-500" size={16} /> Avg Risk Vectors
            </h2>
            <div className="h-[180px]">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={riskVectorData}>
                  <PolarGrid stroke="#374151" />
                  <PolarAngleAxis dataKey="subject" tick={{ fill: '#6b7280', fontSize: 10 }} />
                  <Radar name="Risk" dataKey="value" stroke="#f59e0b" fill="#f59e0b" fillOpacity={0.2} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Detector latency bar */}
          <div className="bg-[#111827] rounded-xl border border-gray-800 p-5">
            <h2 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
              <Zap className="text-violet-400" size={16} /> Detector Latency (latest)
            </h2>
            <div className="h-[180px]">
              {latencyData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={latencyData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" horizontal={false} />
                    <XAxis type="number" stroke="#4b5563" fontSize={10} tickFormatter={v => `${v}ms`} />
                    <YAxis type="category" dataKey="name" stroke="#4b5563" fontSize={9} width={65} />
                    <RechartsTooltip
                      contentStyle={{ backgroundColor: '#1f2937', borderColor: '#374151', color: '#fff', borderRadius: '8px', fontSize: 12 }}
                      formatter={(v: any) => [`${v}ms`, 'Latency']}
                    />
                    <Bar dataKey="ms" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-gray-600 text-sm">No requests yet</div>
              )}
            </div>
          </div>
        </div>

        {/* Decision distribution + gauge */}
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 mb-8">
          <div className="lg:col-span-3 bg-[#111827] rounded-xl border border-gray-800 p-5">
            <h2 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
              <BrainCircuit className="text-blue-500" size={16} /> Decision Distribution
            </h2>
            <div className="flex items-center gap-6">
              {decisionData.map(d => (
                <div key={d.name} className="flex-1">
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-gray-400 font-bold">{d.name}</span>
                    <span className="text-gray-300 font-mono">{d.value}%</span>
                  </div>
                  <div className="h-3 bg-gray-700 rounded-full overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${d.value}%`, backgroundColor: d.color }} />
                  </div>
                </div>
              ))}
              {decisionData.length === 0 && <p className="text-gray-600 text-sm">No data yet</p>}
            </div>
          </div>
          <div className="bg-[#111827] rounded-xl border border-gray-800 p-5 flex flex-col items-center justify-center">
            <p className="text-xs text-gray-500 uppercase tracking-wider font-bold mb-3">System Health</p>
            <TrustGauge score={metrics.average_trust_score} />
          </div>
        </div>

        {/* Session Risk Timeline */}
        <div className="bg-[#111827] rounded-xl border border-gray-800 p-5 mb-8">
          <h2 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
            <TrendingUp className="text-rose-400" size={16} /> Session Risk Timeline
            <span className="ml-auto text-xs text-gray-500 font-normal">Cumulative risk accumulation across requests</span>
          </h2>
          <div className="h-52">
            {sessionRiskData.length > 1 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={sessionRiskData} margin={{ top: 5, right: 20, left: -20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="turn" tick={{ fill: '#6b7280', fontSize: 11 }} label={{ value: 'Request #', position: 'insideBottom', offset: -2, fill: '#6b7280', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} />
                  <RechartsTooltip
                    contentStyle={{ backgroundColor: '#1f2937', borderColor: '#374151', color: '#fff', borderRadius: '8px', fontSize: 12 }}
                  />
                  <Legend wrapperStyle={{ fontSize: 11, color: '#9ca3af' }} />
                  <Line type="monotone" dataKey="risk" stroke="#f87171" strokeWidth={2} dot={false} name="Session Risk" />
                  <Line type="monotone" dataKey="trust" stroke="#34d399" strokeWidth={2} dot={false} name="Trust Score" />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-gray-600 text-sm">
                Send a few requests to see the risk timeline
              </div>
            )}
          </div>
        </div>

        {/* Cost & Latency Governance */}
        <div className="mb-8">
          <h2 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
            <DollarSign className="text-emerald-400" size={16} /> Cost &amp; Latency Governance
            <span className="ml-auto text-xs text-gray-500 font-normal">Illustrative unit economics — see backend/app/costs/pricing.py</span>
          </h2>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            {[
              { label: 'Total Cost (Session)', value: `$${(fullMetrics?.total_cost_usd ?? 0).toFixed(4)}`, icon: <DollarSign size={32} />, color: 'text-emerald-400' },
              { label: 'Avg Cost / Request', value: `$${(fullMetrics?.avg_cost_per_request_usd ?? 0).toFixed(6)}`, icon: <DollarSign size={32} />, color: 'text-white' },
              {
                label: `Projected Weekly Cost @ ${((fullMetrics?.reference_weekly_volume ?? 40000) / 1000).toFixed(0)}k req`,
                value: `$${(fullMetrics?.projected_weekly_cost_usd ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
                icon: <TrendingUp size={32} />, color: 'text-blue-400'
              },
              {
                label: 'Latency Budget Compliance',
                value: `${(((fullMetrics?.latency_budget_compliance_rate ?? 1) * 100)).toFixed(1)}%`,
                icon: <Gauge size={32} />,
                color: (fullMetrics?.latency_budget_compliance_rate ?? 1) >= 0.95 ? 'text-emerald-400' : 'text-amber-400'
              },
            ].map(kpi => (
              <div key={kpi.label} className="hover-lift bg-[#111827] p-5 rounded-xl border border-gray-800 relative overflow-hidden">
                <div className="absolute top-0 right-0 p-4 opacity-10">{kpi.icon}</div>
                <p className="text-gray-500 text-xs uppercase tracking-wider font-bold mb-1">{kpi.label}</p>
                <p className={`text-2xl font-black ${kpi.color}`}>{kpi.value}</p>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Cost by detector */}
            <div className="bg-[#111827] rounded-xl border border-gray-800 p-5">
              <h3 className="text-sm font-bold text-white mb-1 flex items-center gap-2">
                <Zap className="text-violet-400" size={16} /> Avg Cost per Detector
              </h3>
              <p className="text-xs text-gray-500 mb-4">Where the governance "tax" goes — ML-heavy detectors (bias, hallucination) cost more than heuristic/regex ones.</p>
              <div className="h-[200px]">
                {detectorCostData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={detectorCostData} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" horizontal={false} />
                      <XAxis type="number" stroke="#4b5563" fontSize={10} tickFormatter={v => `$${v}`} />
                      <YAxis type="category" dataKey="name" stroke="#4b5563" fontSize={9} width={75} />
                      <RechartsTooltip
                        contentStyle={{ backgroundColor: '#1f2937', borderColor: '#374151', color: '#fff', borderRadius: '8px', fontSize: 12 }}
                        formatter={(v: any) => [`$${(v as number).toFixed(6)}`, 'Avg Cost']}
                      />
                      <Bar dataKey="usd" fill="#10b981" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-gray-600 text-sm">No cost data yet</div>
                )}
              </div>
            </div>

            {/* Per use-case latency budget compliance */}
            <div className="bg-[#111827] rounded-xl border border-gray-800 p-5">
              <h3 className="text-sm font-bold text-white mb-1 flex items-center gap-2">
                <Gauge className="text-blue-400" size={16} /> Latency Budget by Use Case
              </h3>
              <p className="text-xs text-gray-500 mb-4">Each use case gets its own SLA and detector tier — realtime skips the slowest ML detector, batch never does.</p>
              <div className="space-y-3">
                {useCaseCostRows.length === 0 && <p className="text-gray-600 text-sm">No data yet</p>}
                {useCaseCostRows.map(([uc, stats]) => {
                  const compliance = (stats.latency_budget_compliance_rate ?? 1) * 100;
                  return (
                    <div key={uc} className="bg-gray-900/60 rounded-lg p-3 border border-gray-800">
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-xs font-bold text-gray-300 capitalize">{uc.replace('_', ' ')}</span>
                        <span className="text-xs font-mono text-gray-500">
                          p50 {stats.p50_latency_ms?.toFixed(0)}ms / {stats.latency_budget_ms}ms budget · ${stats.avg_cost_usd?.toFixed(6)}/req
                        </span>
                      </div>
                      <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all duration-700"
                          style={{ width: `${compliance}%`, backgroundColor: compliance >= 95 ? '#10b981' : compliance >= 80 ? '#f59e0b' : '#ef4444' }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>

        {/* Main content: Audit log + HITL + Threshold tuner */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Audit Log */}
          <div className="bg-[#111827] rounded-xl border border-gray-800 flex flex-col h-[700px] overflow-hidden">
            <div className="p-5 border-b border-gray-800 shrink-0">
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <FileText className="text-blue-500" size={18} /> Global Audit Log
              </h2>
              <p className="text-xs text-gray-500 mt-1">Click a row to inspect the full governance trace</p>
            </div>
            <div className="overflow-y-auto flex-grow p-4 space-y-2 custom-scrollbar bg-[#0A0E17]">
              {logs.map(log => (
                <div
                  key={log.id}
                  className={`bg-[#111827] rounded-lg border transition-all cursor-pointer overflow-hidden hover:-translate-y-0.5 ${selectedLog?.id === log.id ? 'border-blue-500/50' : 'border-gray-800 hover:border-gray-600'}`}
                  onClick={() => setSelectedLog(selectedLog?.id === log.id ? null : log)}
                >
                  <div className="p-3 flex justify-between items-center">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <DecisionBadge d={log.decision} />
                        <span className="text-xs text-gray-500 font-mono">{new Date(log.timestamp).toLocaleTimeString()}</span>
                      </div>
                      <p className="text-gray-400 text-xs truncate">{log.prompt}</p>
                    </div>
                    <ChevronRight className={`text-gray-500 transition-transform flex-shrink-0 ml-2 ${selectedLog?.id === log.id ? 'rotate-90' : ''}`} size={16} />
                  </div>
                  {selectedLog?.id === log.id && (
                    <div className="px-4 pb-4 border-t border-gray-800 bg-[#0A0E17]/40">
                      <LogTrace log={log} />
                    </div>
                  )}
                </div>
              ))}
              {logs.length === 0 && <p className="text-center text-gray-600 text-sm mt-10">No requests yet. Run the demo or use the Tester page.</p>}
            </div>
          </div>

          {/* Right column: HITL + Threshold Tuner */}
          <div className="flex flex-col gap-6">
            {/* HITL Queue */}
            <div className="bg-[#111827] rounded-xl border border-gray-800 flex flex-col h-[340px] overflow-hidden">
              <div className="p-5 border-b border-gray-800 shrink-0">
                <h2 className="text-base font-bold text-white flex items-center gap-2">
                  <Users className={reviews.length > 0 ? 'text-amber-500' : 'text-gray-500'} size={18} />
                  Human-in-the-Loop Queue
                  {reviews.length > 0 && <span className="bg-amber-500 text-amber-950 text-xs font-bold px-2 py-0.5 rounded-full">{reviews.length}</span>}
                </h2>
              </div>
              <div className="overflow-y-auto flex-grow p-4 bg-[#0A0E17] custom-scrollbar">
                {reviews.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-gray-600 gap-2">
                    <CheckCircle size={28} />
                    <p className="text-sm">Queue empty — all clear</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {reviews.map(rev => (
                      <div key={rev.id} className="bg-[#111827] p-4 rounded-lg border border-amber-900/30">
                        <p className="text-xs text-gray-400 mb-1 truncate" title={rev.prompt}>{rev.prompt}</p>
                        <div className="flex items-center gap-3 mb-3">
                          <span className="text-xs text-amber-400 font-mono">Trust: {rev.trust_score?.toFixed(1)}</span>
                          <span className="text-xs text-gray-600">·</span>
                          <span className="text-xs text-gray-500">{rev.use_case} / {rev.geography}</span>
                        </div>

                        {editingId === rev.id ? (
                          <div className="space-y-2">
                            <p className="text-xs text-blue-400 font-semibold">Edit response before approving:</p>
                            <textarea
                              className="w-full bg-gray-900 border border-blue-700 rounded p-2 text-xs text-gray-200 resize-y font-mono"
                              rows={4}
                              value={editTexts[rev.id] ?? rev.response_text ?? ''}
                              onChange={e => setEditTexts(prev => ({ ...prev, [rev.id]: e.target.value }))}
                            />
                            <div className="flex gap-2">
                              <button
                                onClick={() => handleReviewAction(rev.id, 'edit', editTexts[rev.id] ?? rev.response_text)}
                                className="flex-1 bg-blue-600 hover:bg-blue-500 text-white py-1.5 rounded text-xs font-bold"
                              >Submit Edit</button>
                              <button
                                onClick={() => setEditingId(null)}
                                className="px-3 bg-gray-800 text-gray-400 hover:text-white py-1.5 rounded text-xs"
                              >Cancel</button>
                            </div>
                          </div>
                        ) : (
                          <div className="flex gap-2">
                            <button
                              onClick={() => handleReviewAction(rev.id, 'approved')}
                              className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white py-1.5 rounded text-xs font-bold"
                            >Approve</button>
                            <button
                              onClick={() => {
                                setEditingId(rev.id);
                                setEditTexts(prev => ({ ...prev, [rev.id]: rev.response_text ?? '' }));
                              }}
                              className="flex-1 bg-blue-700 hover:bg-blue-600 text-white py-1.5 rounded text-xs font-bold"
                            >Edit</button>
                            <button
                              onClick={() => handleReviewAction(rev.id, 'rejected')}
                              className="flex-1 bg-gray-800 hover:bg-rose-600 text-rose-400 hover:text-white py-1.5 rounded text-xs font-bold border border-gray-700"
                            >Reject</button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Threshold Tuner */}
            <div className="bg-[#111827] rounded-xl border border-gray-800 flex flex-col h-[340px] overflow-hidden">
              <div className="p-5 border-b border-gray-800 shrink-0">
                <h2 className="text-base font-bold text-white flex items-center gap-2">
                  <Settings className="text-blue-500" size={18} /> Auto-Tuner Recommendations
                </h2>
                <p className="text-xs text-gray-500 mt-1">AI-suggested policy threshold adjustments based on FP/FN analysis</p>
              </div>
              <div className="overflow-y-auto flex-grow p-4 bg-[#0A0E17] custom-scrollbar">
                {recommendations.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-gray-600 gap-2">
                    <CheckCircle size={28} />
                    <p className="text-sm">No pending recommendations</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {recommendations.map(rec => (
                      <div key={rec.recommendation_id} className="bg-blue-900/10 border border-blue-900/30 rounded-lg p-4">
                        <p className="text-xs text-blue-400 font-bold mb-1">{rec.use_case}</p>
                        <p className="text-sm text-gray-300 mb-2">{rec.reason}</p>
                        <p className="text-xs font-mono text-gray-400 mb-3">
                          Threshold: <span className="text-gray-400 line-through">{rec.current_threshold}</span> → <span className="text-white font-bold">{rec.recommended_threshold}</span>
                        </p>
                        <div className="flex gap-2">
                          <button onClick={() => handleRecAction(rec.recommendation_id, 'approve')} className="flex-1 bg-blue-600 hover:bg-blue-500 text-white py-1.5 rounded text-xs font-bold">Apply</button>
                          <button onClick={() => handleRecAction(rec.recommendation_id, 'reject')} className="flex-1 bg-gray-800 text-gray-400 hover:text-white py-1.5 rounded text-xs font-bold">Dismiss</button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
