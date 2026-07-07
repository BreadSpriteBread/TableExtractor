// Polls /api/jobs/<id> until the job reaches a terminal state.
import { useEffect, useRef, useState } from 'react'
import { getJSON } from '../api'

export const TERMINAL_STATES = ['completed', 'cancelled']

export default function useJobPolling(jobId, intervalMs = 1000) {
  const [snapshot, setSnapshot] = useState(null)
  const [error, setError] = useState('')
  const [notFound, setNotFound] = useState(false)
  const timer = useRef(null)

  useEffect(() => {
    setSnapshot(null)
    setError('')
    setNotFound(false)
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
        if (stopped) return
        if (e.status === 404) setNotFound(true)
        else setError(e.message)
      }
    }
    tick()
    return () => {
      stopped = true
      clearTimeout(timer.current)
    }
  }, [jobId, intervalMs])

  return {
    snapshot,
    error,
    notFound,
    isRunning: !!snapshot && !TERMINAL_STATES.includes(snapshot.state),
  }
}
