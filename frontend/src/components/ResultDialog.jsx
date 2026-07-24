// Modal that lazy-loads and shows the cached extraction for one document, with
// a toggle between the raw extracted tables and the derived company financials.
import {
  Button, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress,
  Alert, ToggleButton, ToggleButtonGroup,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { getJSON, downloadAsJSON } from '../api'
import TablesViewer from './TablesViewer'
import FinancialsView from './FinancialsView'

export default function ResultDialog({ documentId, onClose }) {
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [view, setView] = useState('tables')

  useEffect(() => {
    if (!documentId) return
    setResult(null)
    setError('')
    setView('tables')
    getJSON(`/api/extractions/${documentId}`)
      .then(setResult)
      .catch((e) => setError(e.message))
  }, [documentId])

  return (
    <Dialog open={!!documentId} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle>Extraction result</DialogTitle>
      <DialogContent dividers>
        {!result && !error && <LinearProgress />}
        {error && <Alert severity="error">{error}</Alert>}
        {result && (
          <>
            <ToggleButtonGroup size="small" exclusive value={view}
              onChange={(_, v) => v && setView(v)} sx={{ mb: 2 }}>
              <ToggleButton value="tables">Tables</ToggleButton>
              <ToggleButton value="financials">Financials</ToggleButton>
            </ToggleButtonGroup>
            {view === 'tables'
              ? <TablesViewer result={result} />
              : <FinancialsView documentId={documentId} />}
          </>
        )}
      </DialogContent>
      <DialogActions>
        {result && (
          <Button onClick={() => downloadAsJSON(result, `${result.filename}.extraction.json`)}>
            Download JSON
          </Button>
        )}
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  )
}
