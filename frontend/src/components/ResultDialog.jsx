// Modal that lazy-loads and shows the cached extraction for one document.
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress, Alert } from '@mui/material'
import { useEffect, useState } from 'react'
import { getJSON, downloadAsJSON } from '../api'
import TablesViewer from './TablesViewer'

export default function ResultDialog({ documentId, onClose }) {
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!documentId) return
    setResult(null)
    setError('')
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
        {result && <TablesViewer result={result} />}
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
