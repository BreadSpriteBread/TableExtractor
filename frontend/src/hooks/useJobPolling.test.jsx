// Progress state transitions: running snapshots keep polling, terminal
// snapshots stop, and per-doc statuses flow through.
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import useJobPolling from './useJobPolling'

function Harness({ jobId }) {
  const { snapshot, isRunning, notFound } = useJobPolling(jobId, 50)
  if (notFound) return <div data-testid="state">not-found</div>
  if (!snapshot) return <div data-testid="state">loading</div>
  return (
    <div>
      <div data-testid="state">{snapshot.state}</div>
      <div data-testid="running">{String(isRunning)}</div>
      <div data-testid="progress">{snapshot.progress}</div>
      <div data-testid="doc-status">{snapshot.documents[0].status}</div>
    </div>
  )
}

const snap = (state, docStatus, progress) => ({
  job_id: 'j1', state, progress,
  total: 1, done: state === 'completed' ? 1 : 0,
  documents: [{ document_id: 'sha256:x', status: docStatus, table_count: null }],
})

describe('useJobPolling', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })

  it('transitions queued -> running -> completed and stops polling', async () => {
    const responses = [
      snap('running', 'queued', 0),
      snap('running', 'running', 0),
      snap('completed', 'success', 1),
    ]
    let calls = 0
    vi.stubGlobal('fetch', vi.fn(() => {
      const body = responses[Math.min(calls, responses.length - 1)]
      calls += 1
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) })
    }))

    render(<Harness jobId="j1" />)

    await act(async () => { await vi.advanceTimersByTimeAsync(10) })
    expect(screen.getByTestId('doc-status')).toHaveTextContent('queued')
    expect(screen.getByTestId('running')).toHaveTextContent('true')

    await act(async () => { await vi.advanceTimersByTimeAsync(60) })
    expect(screen.getByTestId('doc-status')).toHaveTextContent('running')

    await act(async () => { await vi.advanceTimersByTimeAsync(60) })
    expect(screen.getByTestId('state')).toHaveTextContent('completed')
    expect(screen.getByTestId('doc-status')).toHaveTextContent('success')
    expect(screen.getByTestId('running')).toHaveTextContent('false')
    expect(screen.getByTestId('progress')).toHaveTextContent('1')

    const after = calls
    await act(async () => { await vi.advanceTimersByTimeAsync(500) })
    expect(calls).toBe(after) // no polling after terminal state
  })

  it('reports notFound on 404 and stops polling', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: false, status: 404, json: () => Promise.resolve({ error: 'job not found' }),
    })))

    render(<Harness jobId="stale" />)
    await act(async () => { await vi.advanceTimersByTimeAsync(10) })
    expect(screen.getByTestId('state')).toHaveTextContent('not-found')

    const calls = fetch.mock.calls.length
    await act(async () => { await vi.advanceTimersByTimeAsync(500) })
    expect(fetch.mock.calls.length).toBe(calls)
  })

  it('does nothing without a job id', () => {
    const spy = vi.stubGlobal('fetch', vi.fn())
    render(<Harness jobId={null} />)
    expect(screen.getByTestId('state')).toHaveTextContent('loading')
    expect(fetch).not.toHaveBeenCalled()
  })
})
