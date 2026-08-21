const DOMAIN_TITLES = Object.freeze({
  FALL: '跌倒风险事件',
  MENTAL: '心理趋势事件',
  FRAUD: '高风险交互事件',
  SYSTEM: '系统状态事件',
})

const METRIC_META = Object.freeze({
  rise_duration: { label: '起身时长', unit: '秒' },
  trunk_sway: { label: '躯干摇晃', unit: '度' },
  gait_stability: { label: '步态稳定性', unit: '' },
  relative_gait_speed: { label: '相对步速', unit: '画面高度/秒' },
  stable_trunk_angle_deg: { label: '稳定躯干角度', unit: '度' },
  activity_range: { label: '活动范围', unit: '个区域' },
  circadian: { label: '作息中点', unit: '时' },
})

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function traceBelongsToEvent(trace, event) {
  return trace?.event_id === event.event_id
    || (trace?.evidence_id && asArray(event.evidence_ids).includes(trace.evidence_id))
}

export function deriveEventTitle(event) {
  if (event?.title) return event.title
  const explanation = asArray(event?.evidence_summary).find((item) => item?.explanation)?.explanation
  return explanation || DOMAIN_TITLES[event?.primary_domain] || '风险事件'
}

function transitionDetail(trace) {
  const previous = trace.previous_status || trace.previous_state || '未知状态'
  const next = trace.next_status || trace.next_state || previous
  return previous === next ? `状态保持 ${next}` : `${previous} → ${next}`
}

function timelineFrom(event, traces) {
  const traceItems = traces.map((trace) => ({
    time: trace.evaluated_at,
    title: `${trace.matched_rule || '规则评估'} · ${trace.next_status || trace.next_state || '已评估'}`,
    detail: transitionDetail(trace),
    status: trace.next_status || trace.next_state || trace.matched_rule || '已评估',
    kind: 'RULE',
  }))
  const interventionItems = asArray(event.interventions).map((result) => ({
    time: result.completed_at || result.started_at,
    title: `${result.tool_name} · ${result.delivery_status}`,
    detail: result.family_feedback
      ? `家属反馈：${result.family_feedback}`
      : (result.resolution_reason || result.resident_response || '工具结果已回写'),
    status: result.delivery_status,
    kind: 'INTERVENTION',
  }))
  return [...traceItems, ...interventionItems]
    .filter((item) => item.time)
    .sort((left, right) => new Date(left.time) - new Date(right.time))
}

function observationSeconds(traces) {
  const observing = traces.find((trace) => trace.next_status === 'OBSERVING')
  const resolved = [...traces].reverse().find((trace) => trace.next_status === 'RESOLVED')
  if (!observing?.evaluated_at || !resolved?.evaluated_at) return null
  const seconds = Math.round((new Date(resolved.evaluated_at) - new Date(observing.evaluated_at)) / 1000)
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null
}

export function normalizeEvent(event) {
  const traces = asArray(event?.rule_traces).filter((trace) => traceBelongsToEvent(trace, event))
  return {
    ...event,
    title: deriveEventTitle(event),
    evidences: asArray(event?.evidences),
    observations: asArray(event?.observations),
    interventions: asArray(event?.interventions),
    rule_traces: traces,
    timeline: asArray(event?.timeline).length ? event.timeline : timelineFrom(event, traces),
    risk_history: asArray(event?.risk_history),
    observation_seconds: event?.observation_seconds ?? observationSeconds(traces),
  }
}

export function normalizeDevice(device = {}) {
  return {
    ...device,
    online: typeof device.online === 'boolean' ? device.online : null,
    name: device.name || device.device_alias || '未命名设备',
    adapter: device.adapter || device.adapter_mode || '未提供',
    last_seen: device.last_seen || null,
    data_quality: typeof device.data_quality === 'number' ? device.data_quality : null,
    source_mode: device.source_mode || 'MOCK',
    simulated: device.simulated ?? true,
  }
}

export function normalizeDashboard({ events = [], device = {}, baseline = {}, residentId }) {
  const normalizedEvents = asArray(events).map(normalizeEvent)
  const latest = normalizedEvents[0] || null
  return {
    resident: { resident_id: residentId },
    current_risk: latest ? {
      risk_level: latest.risk_level,
      risk_score: latest.risk_score,
      status: latest.status,
      summary: latest.evidence_summary?.[0]?.explanation || latest.title,
      recommended_action: latest.recommended_action,
      updated_at: latest.updated_at,
    } : null,
    today: {
      activity_minutes: baseline?.today?.activity_minutes ?? null,
      room_transitions: baseline?.today?.room_transitions ?? null,
      events: normalizedEvents.length,
      care_status: baseline?.today?.care_status ?? null,
    },
    device: normalizeDevice(device),
    risk_trend: asArray(baseline?.risk_trend),
    pre_fall_summary: baseline?.pre_fall_summary || null,
    recent_events: normalizedEvents,
  }
}

export function normalizeWeeklyReport(report = {}) {
  return {
    ...report,
    trend: asArray(report.trend),
    evidence: asArray(report.evidence),
    recommendations: asArray(report.recommendations),
    care: {
      event_id: report.care?.event_id || null,
      status: report.care?.status || 'PENDING',
      last_contact: report.care?.last_contact || null,
      options: asArray(report.care?.options),
    },
    visitor_case: report.visitor_case || null,
  }
}

export function normalizeBaseline(baseline = {}) {
  const metrics = Object.entries(baseline.baselines || {}).map(([key, value]) => ({
    key,
    label: METRIC_META[key]?.label || key,
    unit: METRIC_META[key]?.unit || '',
    median: value?.median ?? null,
    mad: value?.mad ?? null,
    sample_count: value?.sample_count ?? 0,
    distinct_days: value?.distinct_days ?? 0,
    status: value?.status || 'INSUFFICIENT',
  }))
  const observedDays = metrics.reduce((maximum, metric) => Math.max(maximum, metric.distinct_days), 0)
  return {
    ...baseline,
    metrics,
    trend: asArray(baseline.trend),
    activity_heatmap: baseline.activity_heatmap || null,
    overall_status: baseline.overall_status || (metrics.length
      ? metrics.reduce((status, metric) => {
        const order = { INSUFFICIENT: 0, PROVISIONAL: 1, STABLE: 2 }
        return order[metric.status] < order[status] ? metric.status : status
      }, 'STABLE')
      : 'INSUFFICIENT'),
    baseline_progress: baseline.baseline_progress || {
      observed_days: observedDays, provisional_target_days: 3, stable_target_days: 7,
    },
    provenance: baseline.provenance || null,
  }
}

export { METRIC_META }
