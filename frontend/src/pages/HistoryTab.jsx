// Extracted Tables history: search cached extractions (filename, status,
// date range, full-text), view, bulk download JSON, bulk delete.
import {
  Alert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent,
  DialogTitle, FormControl, InputLabel, LinearProgress, MenuItem, Paper,
  Select, Table, TableBody, TableCell, TableHead, TableRow, TextField,
  Typography,
} from '@mui/material'
import SearchIcon from '@mui/icons-material/Search'
import DownloadIcon from '@mui/icons-material/Download'
import DeleteIcon from '@mui/icons-material/Delete'
import { useEffect, useState } from 'react'
import { downloadAsJSON, getJSON, postJSON } from '../api'
import ResultDialog from '../components/ResultDialog'
import SourceChip from '../components/SourceChip'
import StatusChip from '../components/StatusChip'

export default function HistoryTab() {
  const [q, setQ] = useState('')
  const [filename, setFilename] = useState('')
  const [status, setStatus] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(new Set())
  const [viewDoc, setViewDoc] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [busy, setBusy] = useState(false)

  const fetchRows = async () => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams()
      if (q) params.set('q', q)
      if (filename) params.set('filename', filename)
      if (status) params.set('status', status)
      if (dateFrom) params.set('date_from', dateFrom)
      if (dateTo) params.set('date_to', dateTo)
      const data = await getJSON(`/api/extractions?${params}`)
      setRows(data.results)
      setSelected(new Set())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchRows() }, [])  // initial load, unfiltered

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }
  const allSelected = rows.length > 0 && selected.size === rows.length

  const bulkDownload = async () => {
    setBusy(true)
    setError('')
    try {
      const bundle = await postJSON('/api/extractions/export', {
        document_ids: [...selected],
      })
      downloadAsJSON(bundle, 'extractions.json')
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const bulkDelete = async () => {
    setBusy(true)
    setError('')
    try {
      await postJSON('/api/extractions/delete', { document_ids: [...selected] })
      setConfirmDelete(false)
      await fetchRows()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>Extracted Tables</Typography>

      <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
        <TextField size="small" label="Full-text (headers & cells)" value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && fetchRows()} sx={{ minWidth: 220 }} />
        <TextField size="small" label="Filename contains" value={filename}
          onChange={(e) => setFilename(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && fetchRows()} />
        <FormControl size="small" sx={{ minWidth: 130 }}>
          <InputLabel>Status</InputLabel>
          <Select value={status} label="Status" onChange={(e) => setStatus(e.target.value)}>
            <MenuItem value="">Any</MenuItem>
            <MenuItem value="success">success</MenuItem>
            <MenuItem value="partial">partial</MenuItem>
            <MenuItem value="failed">failed</MenuItem>
          </Select>
        </FormControl>
        <TextField size="small" label="From" type="date" value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)} InputLabelProps={{ shrink: true }} />
        <TextField size="small" label="To" type="date" value={dateTo}
          onChange={(e) => setDateTo(e.target.value)} InputLabelProps={{ shrink: true }} />
        <Button variant="contained" startIcon={<SearchIcon />} onClick={fetchRows}>
          Search
        </Button>
      </Box>

      <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
        <Button variant="outlined" startIcon={<DownloadIcon />}
          disabled={selected.size === 0 || busy} onClick={bulkDownload}>
          Download {selected.size || ''} as JSON
        </Button>
        <Button variant="outlined" color="error" startIcon={<DeleteIcon />}
          disabled={selected.size === 0 || busy} onClick={() => setConfirmDelete(true)}>
          Delete {selected.size || ''}
        </Button>
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {loading && <LinearProgress sx={{ mb: 2 }} />}

      {!loading && rows.length === 0 && (
        <Alert severity="info">No cached extractions match.</Alert>
      )}

      {rows.length > 0 && (
        <Paper variant="outlined" sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell padding="checkbox">
                  <Checkbox
                    checked={allSelected}
                    indeterminate={selected.size > 0 && !allSelected}
                    onChange={() =>
                      setSelected(allSelected ? new Set() : new Set(rows.map((r) => r.document_id)))}
                    inputProps={{ 'aria-label': 'select all extractions' }}
                  />
                </TableCell>
                <TableCell>Filename</TableCell>
                <TableCell>Source</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Tables</TableCell>
                <TableCell>Extracted at</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.document_id} hover>
                  <TableCell padding="checkbox">
                    <Checkbox checked={selected.has(r.document_id)}
                      onChange={() => toggle(r.document_id)} />
                  </TableCell>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>{r.filename}</TableCell>
                  <TableCell><SourceChip source={r.source} /></TableCell>
                  <TableCell><StatusChip status={r.status} /></TableCell>
                  <TableCell align="right">{r.table_count}</TableCell>
                  <TableCell>{r.extracted_at}</TableCell>
                  <TableCell>
                    <Button size="small" onClick={() => setViewDoc(r.document_id)}>View</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      <ResultDialog documentId={viewDoc} onClose={() => setViewDoc(null)} />

      <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)}>
        <DialogTitle>Delete {selected.size} cached extraction(s)?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            This removes the cached results and their search index entries.
            The source PDFs are not deleted.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmDelete(false)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={bulkDelete} disabled={busy}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
