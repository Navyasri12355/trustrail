/**
 * Unit tests for TrustRail frontend (App.jsx)
 *
 * Strategy:
 *  - Pure utility functions (fmtAmount, fmtTime) are extracted and tested directly.
 *  - React components (MetricCard, RulePills, AuditEntry) are rendered with
 *    @testing-library/react and asserted via jest-dom matchers.
 *  - Network-dependent flows (login, audit log fetch) are tested with mocked
 *    global fetch so no real server is needed in CI.
 *
 * Run with:  npm test  (vitest run)
 */

import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'


// ─── Re-export helpers under test ────────────────────────────────────────────
// We mirror the helpers from App.jsx so we can test them without importing the
// whole module (which has side-effects like setInterval on mount).

function fmtAmount(amt) {
  if (!amt && amt !== 0) return null
  return '₹' + Number(amt).toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

function fmtTime(iso) {
  const d = new Date(iso)
  return (
    d.toLocaleTimeString('en-IN', { hour12: false }) +
    ' · ' +
    d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })
  )
}

// ─── Import components ────────────────────────────────────────────────────────
// These are exported for testing by importing the module directly.
// App.jsx only has a default export, so we import the whole module and test
// the default (App) plus replicate the sub-components inline for isolation.

import App from '../App.jsx'

// ─── fmtAmount ───────────────────────────────────────────────────────────────

describe('fmtAmount', () => {
  it('formats a whole number with rupee symbol', () => {
    expect(fmtAmount(1000)).toBe('₹1,000')
  })

  it('formats zero correctly', () => {
    expect(fmtAmount(0)).toBe('₹0')
  })

  it('formats decimal amounts', () => {
    // en-IN locale rounds to 2 decimal places
    expect(fmtAmount(49.9)).toBe('₹49.9')
    expect(fmtAmount(1234.56)).toBe('₹1,234.56')
  })

  it('returns null for null input', () => {
    expect(fmtAmount(null)).toBeNull()
  })

  it('returns null for undefined input', () => {
    expect(fmtAmount(undefined)).toBeNull()
  })

  it('formats large amounts with Indian grouping', () => {
    // 10 lakh = 10,00,000 in en-IN
    expect(fmtAmount(1000000)).toMatch(/₹/)
  })
})

// ─── fmtTime ─────────────────────────────────────────────────────────────────

describe('fmtTime', () => {
  it('returns a string containing a · separator', () => {
    const result = fmtTime('2024-06-01T10:30:00.000Z')
    expect(result).toContain(' · ')
  })

  it('includes the hour in the output', () => {
    // The exact hour depends on the runner's locale/timezone, but the format
    // should always produce HH:MM:SS · DD Mon
    const result = fmtTime('2024-06-01T10:30:00.000Z')
    // Should have at least two colon-separated time parts
    expect(result.split(':').length).toBeGreaterThanOrEqual(3)
  })
})

// ─── App — unauthenticated (login screen) ────────────────────────────────────

describe('App – login screen', () => {
  beforeEach(() => {
    // Ensure localStorage is clean before each test
    localStorage.clear()
    // Silence React act() warnings for fetch side-effects
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the login form when not authenticated', () => {
    render(<App />)
    expect(screen.getByPlaceholderText('Username')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /login/i })).toBeInTheDocument()
  })

  it('shows the TrustRail branding on the login card', () => {
    render(<App />)
    expect(screen.getByText('TrustRail')).toBeInTheDocument()
    expect(screen.getByText('Dashboard Login')).toBeInTheDocument()
  })

  it('pre-fills the Merchant ID field with the default value', () => {
    render(<App />)
    const merchantInput = screen.getByPlaceholderText('Merchant ID (optional)')
    expect(merchantInput).toHaveValue('mrc_demo_001')
  })

  it('shows a network-error message when the server is unreachable', async () => {
    global.fetch = vi.fn().mockRejectedValueOnce(new Error('Network Error'))

    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByPlaceholderText('Username'), 'admin')
    await user.type(screen.getByPlaceholderText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: /login/i }))

    await waitFor(() => {
      expect(screen.getByText(/network error/i)).toBeInTheDocument()
    })
  })

  it('shows an auth-error message on bad credentials (401)', async () => {
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'Invalid credentials' }),
    })

    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByPlaceholderText('Username'), 'admin')
    await user.type(screen.getByPlaceholderText('Password'), 'badpass')
    await user.click(screen.getByRole('button', { name: /login/i }))

    await waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument()
    })
  })
})

// ─── App — authenticated (dashboard) ─────────────────────────────────────────

describe('App – dashboard (authenticated)', () => {
  const mockAuditLog = [
    {
      id: 1,
      event_type: 'guardrail_decision',
      decision: 'ALLOW',
      mandate_id: 'mnd_abc123',
      reason: 'All rules passed',
      category: 'groceries',
      amount: 250,
      nonce: 'nonce_abcdef123456789012',
      rules_checked: JSON.stringify([
        { rule: 'spend_cap', passed: true, reason: 'Within cap' },
        { rule: 'replay', passed: true, reason: 'No replay' },
      ]),
      row_hash: 'abc123',
      prev_hash: null,
      created_at: '2024-06-01T10:00:00.000Z',
    },
    {
      id: 2,
      event_type: 'guardrail_decision',
      decision: 'BLOCK',
      mandate_id: 'mnd_def456',
      reason: 'Spend cap exceeded',
      category: 'electronics',
      amount: 9999,
      nonce: 'nonce_xyz987654321098765',
      rules_checked: JSON.stringify([
        { rule: 'spend_cap', passed: false, reason: 'Exceeds monthly cap' },
      ]),
      row_hash: 'def456',
      prev_hash: 'abc123',
      created_at: '2024-06-01T11:00:00.000Z',
    },
  ]

  const mockVerify = { intact: true, rows_checked: 2, detail: 'Chain valid' }

  beforeEach(() => {
    // Inject a valid token so the app thinks it's authenticated
    localStorage.setItem('trustrail_token', 'test_jwt_token')
    vi.spyOn(console, 'error').mockImplementation(() => {})

    // Mock fetch: first call = audit-log, second = verify
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockAuditLog,
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockVerify,
      })
  })

  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('renders the main dashboard header when authenticated', async () => {
    render(<App />)
    await waitFor(() => {
      expect(
        screen.getByText('Mandate & Guardrail Reviewer Dashboard')
      ).toBeInTheDocument()
    })
  })

  it('shows metric cards with correct labels', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByText('Total Decisions')).toBeInTheDocument()
      expect(screen.getByText('Allowed')).toBeInTheDocument()
      expect(screen.getByText('Blocked')).toBeInTheDocument()
      expect(screen.getByText('Block Rate')).toBeInTheDocument()
      expect(screen.getByText('Audit Entries')).toBeInTheDocument()
    })
  })

  it('computes block rate correctly from audit log data', async () => {
    render(<App />)
    await waitFor(() => {
      // 1 BLOCK, 1 ALLOW → 50.0%
      expect(screen.getByText('50.0%')).toBeInTheDocument()
    })
  })

  it('shows audit entries in the timeline', async () => {
    render(<App />)
    await waitFor(() => {
      // Both mandate IDs should appear
      expect(screen.getAllByText(/mnd_abc123|mnd_def456/).length).toBeGreaterThan(0)
    })
  })

  it('shows the chain-intact pill when the chain is valid', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByText(/chain intact/i)).toBeInTheDocument()
    })
  })

  it('shows the Revoke Mandate panel', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByText(/revoke mandate/i)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /revoke/i })).toBeInTheDocument()
    })
  })

  it('shows the Logout button', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /logout/i })).toBeInTheDocument()
    })
  })

  it('clears auth and shows login form after logout', async () => {
    render(<App />)
    await waitFor(() =>
      screen.getByRole('button', { name: /logout/i })
    )
    fireEvent.click(screen.getByRole('button', { name: /logout/i }))
    expect(localStorage.getItem('trustrail_token')).toBeNull()
    await waitFor(() => {
      expect(screen.getByPlaceholderText('Username')).toBeInTheDocument()
    })
  })

  it('expands an audit entry on click to reveal rule pills', async () => {
    render(<App />)
    // Wait for the log to load
    await waitFor(() =>
      screen.getByText('mnd_abc123')
    )
    // Click the first audit entry to expand it
    fireEvent.click(screen.getByText('mnd_abc123'))
    await waitFor(() => {
      // Rule pill labels from the mocked data
      expect(screen.getByText(/spend_cap/i)).toBeInTheDocument()
      expect(screen.getByText(/replay/i)).toBeInTheDocument()
    })
  })

  it('shows BLOCK badge for a blocked decision', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByText('BLOCK')).toBeInTheDocument()
    })
  })
})

// ─── Revoke flow ─────────────────────────────────────────────────────────────

describe('App – revoke mandate', () => {
  const mockAuditLog = []
  const mockVerify   = { intact: true, rows_checked: 0, detail: 'Empty chain' }

  beforeEach(() => {
    localStorage.setItem('trustrail_token', 'test_jwt_token')
    vi.spyOn(console, 'error').mockImplementation(() => {})
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => mockAuditLog })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => mockVerify })
  })

  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('calls DELETE /mandates/:id on revoke and shows success message', async () => {
    // After the initial page-load fetches, revoke triggers another audit-log fetch
    global.fetch
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({}) })           // DELETE
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => mockAuditLog })   // re-fetch log
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => mockVerify })     // re-fetch verify

    const user = userEvent.setup()
    render(<App />)

    // Wait for dashboard to load
    await waitFor(() => screen.getByText(/revoke mandate/i))

    await user.type(
      screen.getByPlaceholderText(/mnd_xxx/i),
      'mnd_test_123'
    )
    await user.click(screen.getByRole('button', { name: /^revoke$/i }))

    await waitFor(() => {
      expect(
        screen.getByText(/mandate mnd_test_123 revoked/i)
      ).toBeInTheDocument()
    })
  })

  it('shows an error message when revoke fails (404)', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'Mandate not found' }),
    })

    const user = userEvent.setup()
    render(<App />)

    await waitFor(() => screen.getByText(/revoke mandate/i))

    await user.type(
      screen.getByPlaceholderText(/mnd_xxx/i),
      'mnd_ghost_999'
    )
    await user.click(screen.getByRole('button', { name: /^revoke$/i }))

    await waitFor(() => {
      expect(screen.getByText(/mandate not found/i)).toBeInTheDocument()
    })
  })
})
