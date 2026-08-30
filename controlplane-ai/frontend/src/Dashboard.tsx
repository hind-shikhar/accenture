import { useEffect, useState } from 'react';
import { Activity, ChevronRight, Lock, Bot, ActivitySquare, BrainCircuit, XCircle, CheckCircle, RefreshCw } from 'lucide-react';
import { XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, Area, AreaChart, RadarChart, PolarGrid, PolarAngleAxis, Radar, BarChart, Bar, LineChart, Line, Legend } from 'recharts';
import { SectionLabel, Panel, Button, StatusBadge, DECISION_HEX, IndexNo, MetricCard, LatticeFrame, EmptyState, ChartStatusPill } from './ui';

const TIER_LABELS: Record<string, string> = {
  realtime: 'REALTIME',
  standard: 'STANDARD',
  batch: 'BATCH',
};

const TOOLTIP_STYLE = {
  backgroundColor: '#f4ece1',
  border: '1px solid #dcd4c4',
  borderRadius: 0,
  color: '#141414',
  fontSize: 12,
  fontFamily: 'IBM Plex Mono, monospace',
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
      subject: d.toUpperCase(),
      value: count > 0 ? +(((totals[d] || 0) / count) * 100).toFixed(1) : 0,
    }));
  })();

  const latencyData = (() => {
    const latest = logs[0];
    if (!latest?.detector_latencies) return [];
    return Object.entries(latest.detector_latencies).map(([name, ms]) => ({
      name: name.replace(/_/g, ' ').toUpperCase(),
      ms: +(ms as number).toFixed(1),
    }));
  })();

  const decisionData = (() => {
    const dist = metrics.decision_distribution;
    return Object.entries(dist).map(([k, v]) => ({
      name: k,
      value: +(v * 100).toFixed(1),
      color: DECISION_HEX[k] ?? '#54524d',
    }));
  })();

  const sessionRiskData = [...logs]
    .reverse()
    .slice(0, 20)
    .map((log, idx) => ({
      turn: idx + 1,
      risk: +(log.cumulative_session_risk || 0).toFixed(1),
      trust: +(log.trust_score || 0).toFixed(1),
    }));

  const detectorCostData = (() => {
    const agg = fullMetrics?.avg_detector_cost_usd || {};
    return Object.entries(agg)
      .map(([name, cost]) => ({ name: name.replace(/_/g, ' ').toUpperCase(), usd: cost as number }))
      .sort((a, b) => b.usd - a.usd);
  })();

  const useCaseCostRows = Object.entries(fullMetrics?.per_use_case || {}) as [string, any][];

  // ── Sub-components ────────────────────────────────────────────────────────────
  const TrustGauge = ({ score }: { score: number }) => {
    const r = 36, c = 2 * Math.PI * r;
    const color = score > 80 ? '#3f5b44' : score > 60 ? '#b84318' : '#8c2f12';
    return (
      <div className="relative inline-flex items-center justify-center">
        <svg className="w-24 h-24 -rotate-90">
          <circle cx="48" cy="48" r={r} stroke="#dcd4c4" strokeWidth="6" fill="transparent" />
          <circle cx="48" cy="48" r={r} stroke={color} strokeWidth="6" fill="transparent"
            strokeDasharray={c} strokeDashoffset={c - (score / 100) * c}
            className="transition-all duration-1000" />
        </svg>
        <div className="absolute flex flex-col items-center">
          <span className="font-serif text-2xl text-ink">{Math.round(score)}</span>
        </div>
      </div>
    );
  };

  const LogTrace = ({ log }: { log: any }) => {
    const isBlocked = log.decision === 'BLOCK';
    const isSanitized = log.decision === 'SANITIZE';
    const isEscalated = log.human_review_required;
    const rv = log.composite_risk?.risk_vectors || {};

    const steps = [
      {
        icon: isBlocked ? XCircle : Lock,
        title: 'Security & Policy Gate',
        tag: isBlocked ? '[BLOCKED]' : isSanitized ? '[SANITIZED]' : null,
        body: (
          <>
            PII: {log.security_result?.pii_detected ? <span className="text-rust">MASKED [{log.security_result?.pii_types?.join(', ')}]</span> : <span className="text-forest">CLEAN</span>}
            &nbsp;· Injection: <span className="font-mono">{(log.security_result?.prompt_injection_score || 0).toFixed(2)}</span>
          </>
        ),
      },
      {
        icon: Bot,
        title: 'Semantic Router',
        body: <>Model: <span className="font-mono text-ink">{log.selected_model}</span> · <span className="font-mono">{log.latency_ms?.toFixed(0)}ms</span></>,
      },
      {
        icon: ActivitySquare,
        title: 'Parallel Evidence Fusion (6 detectors)',
        body: (
          <>
            Primary risk: <span className="text-rust font-mono">{log.primary_risk_category || 'NONE'}</span>
            &nbsp;· Verification: <span className={`font-mono ${log.verification_status === 'VERIFIED' ? 'text-forest' : log.verification_status === 'CONTRADICTED' ? 'text-sienna' : 'text-charcoal'}`}>{log.verification_status}</span>
          </>
        ),
      },
    ];

    return (
      <div className="mt-4 space-y-4">
        {Object.keys(rv).length > 0 && (
          <div className="border border-hairline p-4">
            <p className="font-mono text-[10px] uppercase tracking-widest text-charcoal mb-3">Evidence Fusion — Risk Vectors</p>
            <div className="grid grid-cols-2 gap-3">
              {Object.entries(rv).map(([dim, val]: [string, any]) => (
                <div key={dim}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-charcoal capitalize">{dim}</span>
                    <span className="text-ink font-mono">{(val * 100).toFixed(0)}%</span>
                  </div>
                  <div className="h-1 bg-hairline">
                    <div
                      className="h-full"
                      style={{
                        width: `${val * 100}%`,
                        backgroundColor: val > 0.6 ? '#8c2f12' : val > 0.3 ? '#b84318' : '#3f5b44'
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="pl-5 border-l border-hairline space-y-5">
          {steps.map((s, i) => {
            const Icon = s.icon;
            return (
              <div className="relative" key={i}>
                <div className="absolute -left-[27px] w-5 h-5 bg-ink border border-ink flex items-center justify-center">
                  <Icon size={10} className="text-parchment" />
                </div>
                <div className="border border-hairline p-3 text-xs">
                  <p className="font-semibold text-ink mb-1 flex items-center gap-2 font-mono uppercase tracking-wide text-[11px]">
                    {s.title}
                    {s.tag && <span className="text-sienna">{s.tag}</span>}
                  </p>
                  <p className="text-charcoal">{s.body}</p>
                </div>
              </div>
            );
          })}

          <div className="relative">
            <div className="absolute -left-[27px] w-5 h-5 bg-rust border border-rust flex items-center justify-center">
              <BrainCircuit size={10} className="text-parchment" />
            </div>
            <div className="border border-hairline p-3 text-xs">
              <div className="flex justify-between items-center">
                <span className="font-semibold text-ink font-mono uppercase tracking-wide text-[11px] flex items-center gap-2">
                  Governance Decision <StatusBadge decision={log.decision} />
                </span>
                <span className="font-serif text-lg text-ink">
                  {log.trust_score?.toFixed(1)}<span className="text-xs text-charcoal">/100</span>
                </span>
              </div>
              {(log.cost_usd !== undefined || log.latency_tier) && (
                <div className="flex items-center gap-3 mt-2 pt-2 border-t border-hairline text-[11px] text-charcoal font-mono">
                  {log.latency_tier && (
                    <span className="px-1.5 py-0.5 border border-hairline uppercase tracking-wide">
                      {TIER_LABELS[log.latency_tier] ?? log.latency_tier}
                    </span>
                  )}
                  <span>${(log.cost_usd ?? 0).toFixed(6)}</span>
                  {log.latency_budget_ms > 0 && (
                    <span className={log.latency_budget_met === false ? 'text-sienna' : ''}>
                      {log.latency_ms?.toFixed(0)}ms / {log.latency_budget_ms}ms budget
                    </span>
                  )}
                  {isEscalated && <span className="text-rust">ESCALATED</span>}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  };

  if (loading && !metrics.total_requests) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center font-mono text-xs uppercase tracking-[0.2em] text-charcoal">
        Loading ControlPlane…
      </div>
    );
  }

  const kpis = [
    { label: 'Total Requests', value: metrics.total_requests, unit: 'COUNT', footnote: 'Total requests ingested this session' },
    { label: 'Avg Trust Score', value: metrics.average_trust_score, unit: '/ 100', footnote: 'Composite trust score across all evaluated requests' },
    { label: 'Auto-Approved', value: metrics.approved_responses, unit: 'COUNT', footnote: 'Requests cleared without human intervention' },
    { label: 'HITL Escalations', value: metrics.escalated_requests, unit: 'COUNT', footnote: 'Requests routed to human-in-the-loop review' },
  ];

  return (
    <div className="max-w-[1400px] mx-auto px-6 py-10">

      {/* Page header */}
      <div className="flex justify-between items-end mb-10 pb-6 border-b border-hairline">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-rust mb-2">Vol. I — Governance Overview</p>
          <h1 className="font-serif text-4xl text-ink">
            System <span className="font-serif-italic text-rust">Monitor</span>
          </h1>
          <p className="text-charcoal mt-2 text-sm max-w-lg">Round 2 · Enterprise AI Governance &amp; Policy Orchestration, observed in real time.</p>
        </div>
        <div className="flex flex-col items-end gap-3">
          {modelStatus && (
            <div className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-wider text-charcoal border border-hairline px-3 py-1.5">
              <span className={modelStatus.presidio_pii === 'loaded' ? 'text-forest' : 'text-rust'}>Presidio · {modelStatus.presidio_pii === 'loaded' ? 'OK' : 'BOOT'}</span>
              <span className="text-hairline">|</span>
              <span className={modelStatus.distilbert_safety === 'loaded' ? 'text-forest' : 'text-rust'}>DistilBERT · {modelStatus.distilbert_safety === 'loaded' ? 'OK' : 'BOOT'}</span>
              <span className="text-hairline">|</span>
              <span className={modelStatus.bart_bias === 'loaded' ? 'text-forest' : 'text-rust'}>BART · {modelStatus.bart_bias === 'loaded' ? 'OK' : 'BOOT'}</span>
            </div>
          )}
          <div className="flex items-center gap-2">
            <Button variant="ghost" arrow={false} onClick={handleExport} className="px-4 py-2">Export CSV</Button>
            <Button variant="secondary" arrow={false} onClick={fetchData} className="px-4 py-2 group">
              <Activity size={13} className="text-forest" />
              System Active
              <span className="text-charcoal">·</span>
              <RefreshCw size={11} className="group-hover:rotate-180 transition-transform duration-500" />
              <span className="text-charcoal font-mono text-[10px] normal-case tracking-normal">
                {elapsedSinceUpdate !== null ? `${elapsedSinceUpdate}s ago` : ''}
              </span>
            </Button>
          </div>
        </div>
      </div>

      {/* § 01 — KPI shelf */}
      <div className="mb-12">
        <SectionLabel index={1} title="Key Metrics" />
        <LatticeFrame>
          <div className="grid grid-cols-2 md:grid-cols-4 border-t border-l border-hairline">
            {kpis.map((kpi, i) => (
              <MetricCard key={kpi.label} index={i + 1} label={kpi.label} value={kpi.value} unit={kpi.unit} footnote={kpi.footnote} className="border-r border-b border-hairline" />
            ))}
          </div>
        </LatticeFrame>
      </div>

      {/* § 02 — Signal analysis */}
      <div className="mb-12">
        <SectionLabel index={2} title="Signal Analysis" />
        <LatticeFrame>
          <div className="grid grid-cols-1 lg:grid-cols-3 border-t border-l border-hairline">
            <Panel className="border-t-0 border-l-0 border-r border-b p-5">
              <h2 className="font-mono text-xs uppercase tracking-widest text-ink mb-4">Trust Score Trend</h2>
              <div className="h-[180px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={trustTrendData}>
                    <defs>
                      <linearGradient id="cScore" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#b84318" stopOpacity={0.25} />
                        <stop offset="95%" stopColor="#b84318" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="2 3" stroke="#dcd4c4" vertical={false} />
                    <XAxis dataKey="time" stroke="#54524d" fontSize={10} fontFamily="IBM Plex Mono, monospace" tickLine={false} />
                    <YAxis stroke="#54524d" fontSize={10} fontFamily="IBM Plex Mono, monospace" domain={[0, 100]} width={28} tickLine={false} />
                    <RechartsTooltip contentStyle={TOOLTIP_STYLE} />
                    <Area type="monotone" dataKey="score" stroke="#b84318" strokeWidth={2} fillOpacity={1} fill="url(#cScore)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel className="border-t-0 border-l-0 border-r border-b p-5">
              <h2 className="font-mono text-xs uppercase tracking-widest text-ink mb-4">Avg Risk Vectors</h2>
              <div className="h-[180px]">
                {logs.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <RadarChart data={riskVectorData}>
                      <PolarGrid stroke="#dcd4c4" />
                      <PolarAngleAxis
                        dataKey="subject"
                        tick={{ fill: '#54524d', fontSize: 10, fontFamily: 'IBM Plex Mono, monospace' }}
                      />
                      <Radar name="Risk" dataKey="value" stroke="#b84318" fill="#b84318" fillOpacity={0.12} />
                    </RadarChart>
                  </ResponsiveContainer>
                ) : (
                  <EmptyState />
                )}
              </div>
            </Panel>

            <Panel className="border-t-0 border-l-0 border-r border-b p-5">
              <div className="flex items-center justify-between mb-4">
                <h2 className="font-mono text-xs uppercase tracking-widest text-ink">Detector Latency (latest)</h2>
                <ChartStatusPill>200ms Target</ChartStatusPill>
              </div>
              <div className="h-[180px]">
                {latencyData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={latencyData} layout="vertical">
                      <CartesianGrid strokeDasharray="2 3" stroke="#dcd4c4" horizontal={false} />
                      <XAxis type="number" stroke="#54524d" fontSize={10} fontFamily="IBM Plex Mono, monospace" tickFormatter={v => `${v}ms`} tickLine={false} />
                      <YAxis type="category" dataKey="name" stroke="#54524d" fontSize={9} fontFamily="IBM Plex Mono, monospace" width={65} tickLine={false} />
                      <RechartsTooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => [`${v}ms`, 'Latency']} />
                      <Bar dataKey="ms" fill="#141414" />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <EmptyState />
                )}
              </div>
            </Panel>
          </div>
        </LatticeFrame>
      </div>

      {/* § 03 — Decision distribution */}
      <div className="mb-12">
        <SectionLabel index={3} title="Decision Distribution" />
        <LatticeFrame>
          <div className="grid grid-cols-1 lg:grid-cols-4 border-t border-l border-hairline">
            <Panel className="lg:col-span-3 border-t-0 border-l-0 border-r border-b p-5">
              <div className="flex items-center gap-8">
                {decisionData.map(d => (
                  <div key={d.name} className="flex-1">
                    <div className="flex justify-between text-xs mb-1.5 font-mono uppercase tracking-wide">
                      <span className="text-charcoal">{d.name}</span>
                      <span className="text-ink">{d.value}%</span>
                    </div>
                    <div className="h-2 bg-hairline">
                      <div className="h-full" style={{ width: `${d.value}%`, backgroundColor: d.color }} />
                    </div>
                  </div>
                ))}
                {decisionData.length === 0 && <p className="text-charcoal text-sm">No data yet</p>}
              </div>
            </Panel>
            <Panel className="border-t-0 border-l-0 border-r border-b p-5 flex flex-col items-center justify-center">
              <p className="font-mono text-[10px] uppercase tracking-widest text-charcoal mb-3">System Health</p>
              <TrustGauge score={metrics.average_trust_score} />
            </Panel>
          </div>
        </LatticeFrame>
      </div>

      {/* § 04 — Session risk timeline */}
      <div className="mb-12">
        <SectionLabel index={4} title="Session Risk Timeline" trailing="Cumulative risk across requests" />
        <Panel className="p-5">
          <div className="h-52">
            {sessionRiskData.length > 1 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={sessionRiskData} margin={{ top: 5, right: 20, left: -20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="2 3" stroke="#dcd4c4" />
                  <XAxis dataKey="turn" tick={{ fill: '#54524d', fontSize: 11, fontFamily: 'IBM Plex Mono, monospace' }} label={{ value: 'REQUEST #', position: 'insideBottom', offset: -2, fill: '#54524d', fontSize: 10, fontFamily: 'IBM Plex Mono, monospace' }} tickLine={false} />
                  <YAxis tick={{ fill: '#54524d', fontSize: 11, fontFamily: 'IBM Plex Mono, monospace' }} tickLine={false} />
                  <RechartsTooltip contentStyle={TOOLTIP_STYLE} />
                  <Legend wrapperStyle={{ fontSize: 11, color: '#54524d', fontFamily: 'IBM Plex Mono, monospace' }} />
                  <Line type="monotone" dataKey="risk" stroke="#8c2f12" strokeWidth={2} dot={false} name="Session Risk" />
                  <Line type="monotone" dataKey="trust" stroke="#3f5b44" strokeWidth={2} dot={false} name="Trust Score" />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState message="Awaiting Telemetry · Send Requests to Begin" />
            )}
          </div>
        </Panel>
      </div>

      {/* § 05 — Cost & latency governance */}
      <div className="mb-12">
        <SectionLabel index={5} title="Cost & Latency Governance" trailing="See backend/app/costs/pricing.py" />

        <LatticeFrame className="mb-6">
          <div className="grid grid-cols-2 md:grid-cols-4 border-t border-l border-hairline">
            {[
              { label: 'Total Cost (Session)', value: `$${(fullMetrics?.total_cost_usd ?? 0).toFixed(4)}`, unit: 'USD', footnote: 'Cumulative inference spend for this session' },
              { label: 'Avg Cost / Request', value: `$${(fullMetrics?.avg_cost_per_request_usd ?? 0).toFixed(6)}`, unit: 'USD', footnote: 'Mean spend per governed request' },
              {
                label: `Weekly Cost @ ${((fullMetrics?.reference_weekly_volume ?? 40000) / 1000).toFixed(0)}k req`,
                value: `$${(fullMetrics?.projected_weekly_cost_usd ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
                unit: 'USD',
                footnote: 'Projected spend at reference weekly volume',
              },
              {
                label: 'Latency Budget Compliance',
                value: `${(((fullMetrics?.latency_budget_compliance_rate ?? 1) * 100)).toFixed(1)}%`,
                unit: 'PCT',
                footnote: 'Share of requests completed within their latency budget',
              },
            ].map((kpi, i) => (
              <MetricCard key={kpi.label} index={i + 1} label={kpi.label} value={kpi.value} unit={kpi.unit} footnote={kpi.footnote} className="border-r border-b border-hairline" />
            ))}
          </div>
        </LatticeFrame>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 border border-hairline">
          <div className="p-5 border-b lg:border-b-0 lg:border-r border-hairline">
            <h3 className="font-mono text-xs uppercase tracking-widest text-ink mb-4">Avg Cost per Detector</h3>
            <div className="h-[200px]">
              {detectorCostData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={detectorCostData} layout="vertical">
                    <CartesianGrid strokeDasharray="2 3" stroke="#dcd4c4" horizontal={false} />
                    <XAxis type="number" stroke="#54524d" fontSize={10} fontFamily="IBM Plex Mono, monospace" tickFormatter={v => `$${v}`} tickLine={false} />
                    <YAxis type="category" dataKey="name" stroke="#54524d" fontSize={9} fontFamily="IBM Plex Mono, monospace" width={75} tickLine={false} />
                    <RechartsTooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => [`$${(v as number).toFixed(6)}`, 'Avg Cost']} />
                    <Bar dataKey="usd" fill="#b84318" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <EmptyState message="Awaiting Telemetry · No Cost Data" />
              )}
            </div>
          </div>

          <div className="p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-mono text-xs uppercase tracking-widest text-ink">Latency Budget by Use Case</h3>
              <ChartStatusPill>Target Budget</ChartStatusPill>
            </div>
            <div className="space-y-3">
              {useCaseCostRows.length === 0 && <EmptyState message="Awaiting Telemetry · No Use-Case Data" className="min-h-[100px]" />}
              {useCaseCostRows.map(([uc, stats]) => {
                const compliance = (stats.latency_budget_compliance_rate ?? 1) * 100;
                return (
                  <div key={uc} className="border border-hairline p-3">
                    <div className="flex justify-between items-center mb-2">
                      <span className="text-xs font-mono uppercase tracking-wide text-ink">{uc.replace('_', ' ')}</span>
                      <span className="text-xs font-mono text-charcoal">
                        p50 {stats.p50_latency_ms?.toFixed(0)}ms / {stats.latency_budget_ms}ms · ${stats.avg_cost_usd?.toFixed(6)}/req
                      </span>
                    </div>
                    <div className="h-1.5 bg-hairline">
                      <div
                        className="h-full transition-all duration-700"
                        style={{ width: `${compliance}%`, backgroundColor: compliance >= 95 ? '#3f5b44' : compliance >= 80 ? '#b84318' : '#8c2f12' }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* § 06 / 07 / 08 — Audit + HITL + Threshold tuner */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">

        <div>
          <SectionLabel index={6} title="Global Audit Log" trailing="Click a row to inspect the trace" />
          <div className="border border-hairline flex flex-col h-[700px] overflow-hidden">
            <div className="overflow-y-auto flex-grow custom-scrollbar">
              {logs.map((log, i) => (
                <div
                  key={log.id}
                  className={`border-b border-hairline transition-colors cursor-pointer ${selectedLog?.id === log.id ? 'bg-parchment-2' : 'hover:bg-parchment-2/60'}`}
                  onClick={() => setSelectedLog(selectedLog?.id === log.id ? null : log)}
                >
                  <div className="p-3 flex justify-between items-center gap-3">
                    <IndexNo n={i + 1} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <StatusBadge decision={log.decision} />
                        <span className="text-[10px] text-charcoal font-mono">{new Date(log.timestamp).toLocaleTimeString()}</span>
                      </div>
                      <p className="text-charcoal text-xs truncate">{log.prompt}</p>
                    </div>
                    <ChevronRight className={`text-charcoal transition-transform flex-shrink-0 ${selectedLog?.id === log.id ? 'rotate-90' : ''}`} size={15} />
                  </div>
                  {selectedLog?.id === log.id && (
                    <div className="px-4 pb-4 border-t border-hairline">
                      <LogTrace log={log} />
                    </div>
                  )}
                </div>
              ))}
              {logs.length === 0 && <EmptyState message="Awaiting Telemetry · Run the Tester to Begin" className="h-full" />}
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-8">
          <div>
            <SectionLabel index={7} title="Human Review Queue" trailing={reviews.length > 0 ? `${reviews.length} PENDING` : 'CLEAR'} />
            <div className="border border-hairline flex flex-col h-[340px] overflow-hidden">
              <div className="overflow-y-auto flex-grow custom-scrollbar">
                {reviews.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-charcoal gap-2">
                    <CheckCircle size={26} />
                    <p className="text-sm">Queue empty — all clear</p>
                  </div>
                ) : (
                  <div>
                    {reviews.map((rev, i) => (
                      <div key={rev.id} className="p-4 border-b border-hairline">
                        <div className="flex items-start gap-2 mb-1">
                          <IndexNo n={i + 1} />
                          <p className="text-xs text-charcoal truncate flex-1" title={rev.prompt}>{rev.prompt}</p>
                        </div>
                        <div className="flex items-center gap-3 mb-3 font-mono">
                          <span className="text-xs text-rust">Trust: {rev.trust_score?.toFixed(1)}</span>
                          <span className="text-xs text-hairline">·</span>
                          <span className="text-xs text-charcoal">{rev.use_case} / {rev.geography}</span>
                        </div>

                        {editingId === rev.id ? (
                          <div className="space-y-2">
                            <p className="text-xs text-ink font-mono uppercase tracking-wide">Edit response before approving:</p>
                            <textarea
                              className="w-full bg-transparent border border-hairline focus:border-ink p-2 text-xs text-ink resize-y font-mono focus:outline-none"
                              rows={4}
                              value={editTexts[rev.id] ?? rev.response_text ?? ''}
                              onChange={e => setEditTexts(prev => ({ ...prev, [rev.id]: e.target.value }))}
                            />
                            <div className="flex gap-2">
                              <Button arrow={false} onClick={() => handleReviewAction(rev.id, 'edit', editTexts[rev.id] ?? rev.response_text)} className="flex-1 py-1.5">Submit Edit</Button>
                              <Button variant="ghost" arrow={false} onClick={() => setEditingId(null)} className="px-3 py-1.5">Cancel</Button>
                            </div>
                          </div>
                        ) : (
                          <div className="flex gap-2">
                            <Button arrow={false} onClick={() => handleReviewAction(rev.id, 'approved')} className="flex-1 py-1.5">Approve</Button>
                            <Button
                              variant="secondary"
                              arrow={false}
                              onClick={() => { setEditingId(rev.id); setEditTexts(prev => ({ ...prev, [rev.id]: rev.response_text ?? '' })); }}
                              className="flex-1 py-1.5"
                            >Edit</Button>
                            <Button variant="danger" arrow={false} onClick={() => handleReviewAction(rev.id, 'rejected')} className="flex-1 py-1.5">Reject</Button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          <div>
            <SectionLabel index={8} title="Auto-Tuner Recommendations" trailing="FP/FN threshold analysis" />
            <div className="border border-hairline flex flex-col h-[340px] overflow-hidden">
              <div className="overflow-y-auto flex-grow custom-scrollbar">
                {recommendations.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-charcoal gap-2">
                    <CheckCircle size={26} />
                    <p className="text-sm">No pending recommendations</p>
                  </div>
                ) : (
                  <div>
                    {recommendations.map((rec, i) => (
                      <div key={rec.recommendation_id} className="p-4 border-b border-hairline">
                        <div className="flex items-start gap-2 mb-1">
                          <IndexNo n={i + 1} />
                          <p className="text-xs text-rust font-mono uppercase tracking-wide">{rec.use_case}</p>
                        </div>
                        <p className="text-sm text-ink mb-2">{rec.reason}</p>
                        <p className="text-xs font-mono text-charcoal mb-3">
                          Threshold: <span className="line-through">{rec.current_threshold}</span> → <span className="text-ink font-semibold">{rec.recommended_threshold}</span>
                        </p>
                        <div className="flex gap-2">
                          <Button arrow={false} onClick={() => handleRecAction(rec.recommendation_id, 'approve')} className="flex-1 py-1.5">Apply</Button>
                          <Button variant="ghost" arrow={false} onClick={() => handleRecAction(rec.recommendation_id, 'reject')} className="flex-1 py-1.5">Dismiss</Button>
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
