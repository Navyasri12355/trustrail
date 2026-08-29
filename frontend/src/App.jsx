import React, { useState, useEffect, useCallback } from 'react'

const API = 'http://localhost:8000'

// ── Auth helpers ───────────────────────────────────────────────────────────────

function getAuthToken() {
  return localStorage.getItem('trustrail_token')
}

function setAuthToken(token) {
  localStorage.setItem('trustrail_token', token)
}

function clearAuthToken() {
  localStorage.removeItem('trustrail_token')
}

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
  const [authenticated, setAuthenticated] = useState(false)
  const [authError, setAuthError] = useState(null)
  const [loginForm, setLoginForm] = useState({ username: '', password: '' })
  const [merchantId, setMerchantId] = useState('mrc_demo_001')
  const [chainStatus, setChainStatus] = useState(null)  // { intact, rows_checked, detail }

  const fetchLog = useCallback(async () => {
    const token = getAuthToken()
    
    if (!token) {
      setAuthenticated(false)
      return
    }

    setLoading(true)
    try {
      const r = await fetch(`${API}/audit-log`, {
        headers: { 
          'Authorization': `Bearer ${token}`,
          'X-Merchant-ID': merchantId
        }
      })
      if (r.status === 401) {
        clearAuthToken()
        setAuthenticated(false)
        setLog([])
        setChainStatus(null)
        return
      }
      if (!r.ok) {
        setLog([])
        setChainStatus(null)
        return
      }
      const data = await r.json()
      setLog(Array.isArray(data) ? [...data].reverse() : [])

      const vr = await fetch(`${API}/audit-log/verify`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'X-Merchant-ID': merchantId
        }
      })
      if (vr.ok) {
        setChainStatus(await vr.json())
      } else {
        setChainStatus(null)
      }
    } catch {
      setLog([])
    } finally {
      setLoading(false)
    }
  }, [merchantId])

  useEffect(() => { fetchLog() }, [fetchLog])

  // Check authentication on mount
  useEffect(() => {
    const token = getAuthToken()
    if (token) {
      setAuthenticated(true)
    }
  }, [])

  // Auto-refresh every 10s (only if authenticated)
  useEffect(() => {
    if (!authenticated) return
    const id = setInterval(fetchLog, 10_000)
    return () => clearInterval(id)
  }, [fetchLog, authenticated])

  // ── Auth handlers ─────────────────────────────────────────────────────────────
  const handleLogin = async (e) => {
    e.preventDefault()
    setAuthError(null)
    
    try {
      const r = await fetch(`${API}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(loginForm)
      })
      const data = await r.json()
      
      if (r.ok) {
        setAuthToken(data.access_token)
        setAuthenticated(true)
        setLoginForm({ username: '', password: '' })
        fetchLog()
      } else {
        setAuthError(data.detail || 'Login failed')
      }
    } catch {
      setAuthError('Network error')
    }
  }

  const handleLogout = () => {
    clearAuthToken()
    setAuthenticated(false)
    setLog([])
  }

  // ── Metrics ─────────────────────────────────────────────────────────────────
  const decisions = log.filter(e => e.event_type === 'guardrail_decision')
  const allowed   = decisions.filter(e => e.decision === 'ALLOW').length
  const blocked   = decisions.filter(e => e.decision === 'BLOCK').length
  const total     = decisions.length
  const blockRate = total ? ((blocked / total) * 100).toFixed(1) + '%' : '—'

  // ── Revoke ──────────────────────────────────────────────────────────────────
  const handleRevoke = async () => {
    if (!revokeId.trim()) return
    const token = getAuthToken()
    if (!token) return

    try {
      const r = await fetch(`${API}/mandates/${revokeId.trim()}`, { 
        method: 'DELETE',
        headers: { 
          'Authorization': `Bearer ${token}`,
          'X-Merchant-ID': merchantId
        }
      })
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

  // ── Login form ─────────────────────────────────────────────────────────────
  if (!authenticated) {
    return (
      <div className="app">
        <div className="login-container">
          <div className="login-card">
            <div className="login-header">
              <div className="header-logo">T</div>
              <div>
                <div className="header-title">TrustRail</div>
                <div className="header-sub">Dashboard Login</div>
              </div>
            </div>
            <form onSubmit={handleLogin} className="login-form">
              <input
                type="text"
                placeholder="Username"
                value={loginForm.username}
                onChange={e => setLoginForm({...loginForm, username: e.target.value})}
                className="login-input"
                autoFocus
              />
              <input
                type="password"
                placeholder="Password"
                value={loginForm.password}
                onChange={e => setLoginForm({...loginForm, password: e.target.value})}
                className="login-input"
              />
              <input
                type="text"
                placeholder="Merchant ID (optional)"
                value={merchantId}
                onChange={e => setMerchantId(e.target.value)}
                className="login-input"
              />
              {authError && <div className="login-error">{authError}</div>}
              <button type="submit" className="btn btn-primary btn-full">
                Login
              </button>
            </form>
            <div className="login-footer">
              <p>Use DASHBOARD_ADMIN_USERNAME and DASHBOARD_ADMIN_PASSWORD from your .env</p>
              <p>Default merchant header: mrc_demo_001</p>
            </div>
          </div>
        </div>
      </div>
    )
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
        <div className="header-right">
          {chainStatus && (
            <div
              className={`chain-pill ${chainStatus.intact ? 'intact' : 'broken'}`}
              title={chainStatus.detail}
            >
              {chainStatus.intact
                ? `chain intact · ${chainStatus.rows_checked}`
                : `chain broken · ${chainStatus.detail}`}
            </div>
          )}
          <div className="header-badge">Razorpay AI Buildathon · Track 01</div>
          <button onClick={handleLogout} className="btn btn-logout">
            Logout
          </button>
        </div>
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
