import { useState, useEffect, useCallback } from 'react'

const API = 'http://localhost:8000'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtTime(iso) {
  const d = new Date(iso)
  return d.toLocaleTimeString('en-IN', { hour12: false }) +
    ' · ' + d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })
}

function fmtAmount(amt) {
  if (!amt && amt !== 0) return null
  return '₹' + Number(amt).toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

// ── Metric Card ───────────────────────────────────────────────────────────────

function MetricCard({ label, value, sub, variant }) {
  return (
    <div className={`card ${variant}`}>
      <div className="card-label">{label}</div>
      <div className="card-value">{value}</div>
      {sub && <div className="card-sub">{sub}</div>}
    </div>
  )
}

// ── Rule Pills ────────────────────────────────────────────────────────────────

function RulePills({ rulesJson }) {
  if (!rulesJson) return null
  let rules
  try { rules = JSON.parse(rulesJson) } catch { return null }
  return (
    <div className="rules-row">
      {rules.map(r => (
        <span
          key={r.rule}
          className={`rule-pill ${r.passed ? 'rule-pass' : 'rule-fail'}`}
          title={r.reason || ''}
        >
          {r.passed ? '✓' : '✗'} {r.rule}
        </span>
      ))}
    </div>
  )
}

// ── Audit Entry ───────────────────────────────────────────────────────────────

function AuditEntry({ entry }) {
  const [expanded, setExpanded] = useState(false)
  const isAllow  = entry.decision === 'ALLOW'
  const isBlock  = entry.decision === 'BLOCK'
  const isEvent  = !entry.decision

  const rowClass = isAllow ? 'allow' : isBlock ? 'block' : 'event'
  const badgeClass = isAllow ? 'badge-allow' : isBlock ? 'badge-block' : 'badge-event'
  const badgeText  = isAllow ? 'ALLOW' : isBlock ? 'BLOCK' : entry.event_type.replace('_', ' ').toUpperCase()

  return (
    <div className={`entry ${rowClass}`} onClick={() => setExpanded(e => !e)} style={{ cursor: 'pointer' }}>
      <span className={`entry-badge ${badgeClass}`}>{badgeText}</span>

      <div className="entry-body">
        <div className="entry-mandate">{entry.mandate_id || '—'}</div>
        <div className="entry-reason">
          {entry.reason || entry.event_type}
        </div>
        <div className="entry-meta">
          {entry.category && <span>📦 {entry.category}</span>}
          {entry.amount   && <span>{fmtAmount(entry.amount)}</span>}
          {entry.nonce    && <span>🔑 {entry.nonce?.slice(0, 18)}…</span>}
        </div>

        {expanded && (
          <>
            <RulePills rulesJson={entry.rules_checked} />
            <div className="hash-row">
              <div className="hash-text">
                <span style={{ color: 'var(--accent)' }}>hash </span>
                {entry.row_hash}
              </div>
              <div className="hash-text">
                <span style={{ color: 'var(--text-muted)' }}>prev </span>
                {entry.prev_hash || '(genesis)'}
              </div>
            </div>
          </>
        )}
      </div>

      <div className="entry-time">{fmtTime(entry.created_at)}</div>
    </div>
  )
}

// ── Main App ──────────────────────────────────────────────────────────────────

export default function App() {
  const [log,      setLog]      = useState([])
  const [loading,  setLoading]  = useState(true)
  const [revokeId, setRevokeId] = useState('')
  const [revokeMsg, setRevokeMsg] = useState(null)  // { text, ok }

  const fetchLog = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch(`${API}/audit-log`)
      const data = await r.json()
      setLog([...data].reverse())   // newest first
    } catch {
      setLog([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchLog() }, [fetchLog])

  // Auto-refresh every 10s
  useEffect(() => {
    const id = setInterval(fetchLog, 10_000)
    return () => clearInterval(id)
  }, [fetchLog])

  // ── Metrics ─────────────────────────────────────────────────────────────────
  const decisions = log.filter(e => e.event_type === 'guardrail_decision')
  const allowed   = decisions.filter(e => e.decision === 'ALLOW').length
  const blocked   = decisions.filter(e => e.decision === 'BLOCK').length
  const total     = decisions.length
  const blockRate = total ? ((blocked / total) * 100).toFixed(1) + '%' : '—'

  // ── Revoke ──────────────────────────────────────────────────────────────────
  const handleRevoke = async () => {
    if (!revokeId.trim()) return
    try {
      const r = await fetch(`${API}/mandates/${revokeId.trim()}`, { method: 'DELETE' })
      if (r.ok) {
        setRevokeMsg({ text: `Mandate ${revokeId.trim()} revoked`, ok: true })
        setRevokeId('')
        fetchLog()
      } else {
        const d = await r.json()
        setRevokeMsg({ text: d.detail || 'Revocation failed', ok: false })
      }
    } catch {
      setRevokeMsg({ text: 'Network error', ok: false })
    }
    setTimeout(() => setRevokeMsg(null), 4000)
  }

  return (
    <div className="app">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="header">
        <div className="header-brand">
          <div className="header-logo">T</div>
          <div>
            <div className="header-title">TrustRail</div>
            <div className="header-sub">Mandate & Guardrail Reviewer Dashboard</div>
          </div>
        </div>
        <div className="header-badge">Razorpay AI Buildathon · Track 01</div>
      </header>

      <main className="main">

        {/* ── Metrics ──────────────────────────────────────────────────────── */}
        <div className="metrics">
          <MetricCard label="Total Decisions"  value={total}     sub="guardrail runs"        variant="total" />
          <MetricCard label="Allowed"          value={allowed}   sub="reached Razorpay"      variant="allow" />
          <MetricCard label="Blocked"          value={blocked}   sub="caught by guardrail"   variant="block" />
          <MetricCard label="Block Rate"       value={blockRate} sub="blocked / total"        variant="rate"  />
          <MetricCard label="Audit Entries"    value={log.length} sub="total log rows"        variant="total" />
        </div>

        {/* ── Revoke panel ─────────────────────────────────────────────────── */}
        <div className="revoke-panel">
          <h3>🔒 Revoke Mandate</h3>
          <input
            id="revoke-mandate-input"
            className="revoke-input"
            placeholder="mnd_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            value={revokeId}
            onChange={e => setRevokeId(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleRevoke()}
          />
          <button id="revoke-btn" className="btn btn-danger" onClick={handleRevoke}>
            Revoke
          </button>
          <button id="refresh-btn" className="btn btn-refresh" onClick={fetchLog}>
            ↻ Refresh
          </button>
          {revokeMsg && (
            <span className={`revoke-msg ${revokeMsg.ok ? 'ok' : 'err'}`}>
              {revokeMsg.text}
            </span>
          )}
        </div>

        {/* ── Audit timeline ────────────────────────────────────────────────── */}
        <div className="section-header">
          <span className="section-title">Audit Trail</span>
          <span className="section-count">{log.length} entries · newest first · click to expand</span>
        </div>

        {loading ? (
          <div className="spinner" />
        ) : log.length === 0 ? (
          <div className="empty">
            No audit entries yet.<br />
            Run the agent harness or make a payment request to see data here.
          </div>
        ) : (
          <div className="timeline">
            {log.map(entry => (
              <AuditEntry key={entry.id} entry={entry} />
            ))}
          </div>
        )}

      </main>
    </div>
  )
}
