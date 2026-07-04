// Extract Results tab: run extraction over cart documents, watch per-doc and
// batch progress, view results, export selected as a single JSON file.
import {
  Alert, Box, Button, Checkbox, CircularProgress, FormControlLabel,
  LinearProgress, Paper, Switch, Table, TableBody, TableCell, TableHead,
  TableRow, Typography,
} from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import CancelIcon from '@mui/icons-material/Cancel'
import DownloadIcon from '@mui/icons-material/Download'
import { useMemo, useState } from 'react'
import { downloadAsJSON, postJSON } from '../api'
import { useCart } from '../cart/CartContext'
import useJobPolling from '../hooks/useJobPolling'
import ResultDialog from '../components/ResultDialog'
import SourceChip from '../components/SourceChip'
import StatusChip from '../components/StatusChip'

const DONE = new Set(['success', 'partial', 'failed', 'cached'])

export default function ExtractTab() {
  const cart = useCart()
  const [selected, setSelected] = useState(new Set())
  const [force, setForce] = useState(false)
  const [jobId, setJobId] = useState(null)
  const [submitError, setSubmitError] = useState('')
  const [viewDoc, setViewDoc] = useState(null)
  const [exporting, setExporting] = useState(false)
  const { snapshot, error: pollError, isRunning } = useJobPolling(jobId)

  // job state per document_id, layered over cart rows
  const docState = useMemo(() => {
    const map = new Map()
    for (const d of snapshot?.documents ?? []) map.set(d.document_id, d)
    return map
  }, [snapshot])

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }
  const allSelected = cart.count > 0 && selected.size === cart.count

  const runExtraction = async () => {
    const ids = selected.size ? [...selected] : cart.items.map((i) => i.document_id)
    setSubmitError('')
    try {
      const resp = await postJSON('/api/extract', { document_ids: ids, force })
      setJobId(resp.job_id)
    } catch (e) {
      setSubmitError(e.message)
    }
  }

  const cancelJob = () => postJSON(`/api/jobs/${jobId}/cancel`).catch(() => {})

  const exportSelected = async () => {
    const ids = selected.size ? [...selected] : cart.items.map((i) => i.document_id)
    setExporting(true)
    setSubmitError('')
    try {
      const bundle = await postJSON('/api/extractions/export', { document_ids: ids })
      if (!bundle.documents.length) {
        setSubmitError('No cached extractions for the selected documents — run extraction first.')
      } else {
        downloadAsJSON(bundle, 'extractions.json')
      }
    } catch (e) {
      setSubmitError(e.message)
    } finally {
      setExporting(false)
    }
  }

  const fmtTime = (ms) => (ms == null ? '—' : ms === 0 ? 'cached' : `${(ms / 1000).toFixed(1)}s`)

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>Extract Results</Typography>

      {cart.count === 0 && (
        <Alert severity="info">
          The cart is empty. Select documents in Query Reports or upload files
          in Acquire Reports first.
        </Alert>
      )}

      {cart.count > 0 && (
        <>
          <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
            <Button
              variant="contained"
              startIcon={isRunning ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
              disabled={isRunning}
              onClick={runExtraction}
            >
              Extract {selected.size || 'all'} document(s)
            </Button>
            <FormControlLabel
              control={<Switch checked={force} onChange={(e) => setForce(e.target.checked)} />}
              label="Re-extract (overwrite cache)"
            />
            {isRunning && (
              <Button color="error" startIcon={<CancelIcon />} onClick={cancelJob}>
                Cancel
              </Button>
            )}
            <Box sx={{ flexGrow: 1 }} />
            <Button
              variant="outlined"
              startIcon={<DownloadIcon />}
              disabled={exporting || isRunning}
              onClick={exportSelected}
            >
              Export JSON
            </Button>
          </Box>

          {snapshot && (
            <Box sx={{ mb: 2 }} data-testid="batch-progress">
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                Batch: {snapshot.done}/{snapshot.total} ({snapshot.state})
              </Typography>
              <LinearProgress
                variant="determinate"
                value={snapshot.progress * 100}
                sx={{ height: 8, borderRadius: 4 }}
              />
            </Box>
          )}
          {(submitError || pollError) && (
            <Alert severity="error" sx={{ mb: 2 }}>{submitError || pollError}</Alert>
          )}

          <Paper variant="outlined" sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell padding="checkbox">
                    <Checkbox
                      checked={allSelected}
                      indeterminate={selected.size > 0 && !allSelected}
                      onChange={() =>
                        setSelected(allSelected
                          ? new Set()
                          : new Set(cart.items.map((i) => i.document_id)))}
                      inputProps={{ 'aria-label': 'select all cart documents' }}
                    />
                  </TableCell>
                  <TableCell>Filename</TableCell>
                  <TableCell>Source</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell align="right">Tables</TableCell>
                  <TableCell align="right">Time</TableCell>
                  <TableCell />
                </TableRow>
              </TableHead>
              <TableBody>
                {cart.items.map((item) => {
                  const st = docState.get(item.document_id)
                  return (
                    <TableRow key={item.document_id} hover>
                      <TableCell padding="checkbox">
                        <Checkbox
                          checked={selected.has(item.document_id)}
                          onChange={() => toggle(item.document_id)}
                        />
                      </TableCell>
                      <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>
                        {item.filename}
                      </TableCell>
                      <TableCell><SourceChip source={item.source} /></TableCell>
                      <TableCell><StatusChip status={st?.status} /></TableCell>
                      <TableCell align="right">{st?.table_count ?? '—'}</TableCell>
                      <TableCell align="right">{fmtTime(st?.duration_ms)}</TableCell>
                      <TableCell>
                        {st && DONE.has(st.status) && st.status !== 'failed' && (
                          <Button size="small" onClick={() => setViewDoc(item.document_id)}>
                            View
                          </Button>
                        )}
                        {st?.status === 'failed' && (
                          <Typography variant="caption" color="error">
                            {st.error}
                          </Typography>
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </Paper>
        </>
      )}

      <ResultDialog documentId={viewDoc} onClose={() => setViewDoc(null)} />
    </Box>
  )
}
