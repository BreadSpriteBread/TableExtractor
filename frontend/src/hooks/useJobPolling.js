// Polls /api/jobs/<id> until the job reaches a terminal state.
import { useEffect, useRef, useState } from 'react'
import { getJSON } from '../api'

export const TERMINAL_STATES = ['completed', 'cancelled']

export default function useJobPolling(jobId, intervalMs = 1000) {
  const [snapshot, setSnapshot] = useState(null)
  const [error, setError] = useState('')
  const timer = useRef(null)

  useEffect(() => {
    setSnapshot(null)
    setError('')
    if (!jobId) return undefined

    let stopped = false
    const tick = async () => {
      try {
        const snap = await getJSON(`/api/jobs/${jobId}`)
        if (stopped) return
        setSnapshot(snap)
        if (!TERMINAL_STATES.includes(snap.state)) {
          timer.current = setTimeout(tick, intervalMs)
        }
      } catch (e) {
        if (!stopped) setError(e.message)
      }
    }
    tick()
    return () => {
      stopped = true
      clearTimeout(timer.current)
    }
  }, [jobId, intervalMs])

  return { snapshot, error, isRunning: !!snapshot && !TERMINAL_STATES.includes(snapshot.state) }
}
