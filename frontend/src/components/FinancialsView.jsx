// Derived company financials for one document: three statements laid out as
// line-item rows × reporting-period columns. Figures come from the deterministic
// parser; an optional "Enhance with AI" pass fills gaps the parser missed.
import {
  Alert, Box, Button, Chip, LinearProgress, Paper, Stack, Table, TableBody,
  TableCell, TableHead, TableRow, Tooltip, Typography,
} from '@mui/material'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import { useEffect, useState } from 'react'
import { getJSON } from '../api'

const SECTIONS = [
  ['balance_sheet', 'Balance Sheet'],
  ['income_statement', 'Statement of Income'],
  ['cash_flow', 'Cash Flows'],
]

function fmt(v) {
  if (v === null || v === undefined) return '—'
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function StatementTable({ title, block, periods }) {
  if (!block) return null
  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>{title}</Typography>
      <Paper variant="outlined" sx={{ overflowX: 'auto' }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 700 }}>Line item</TableCell>
              {periods.map((p) => (
                <TableCell key={p} align="right" sx={{ fontWeight: 700 }}>{p}</TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {Object.entries(block).map(([key, cell]) => {
              const found = cell.values.some((v) => v !== null && v !== undefined)
              return (
                <TableRow key={key} hover>
                  <TableCell sx={{ color: found ? 'text.primary' : 'text.disabled' }}>
                    {cell.label}
                  </TableCell>
                  {periods.map((p, i) => (
                    <TableCell key={p} align="right"
                      sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {fmt(cell.values[i])}
                    </TableCell>
                  ))}
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </Paper>
    </Box>
  )
}

export default function FinancialsView({ documentId }) {
  const [fin, setFin] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [llmAvailable, setLlmAvailable] = useState(false)

  const load = (opts = {}) => {
    setError('')
    setBusy(true)
    const params = new URLSearchParams()
    if (opts.force) params.set('force', '1')
    if (opts.useLlm) params.set('use_llm', '1')
    const qs = params.toString()
    getJSON(`/api/financials/${documentId}${qs ? `?${qs}` : ''}`)
      .then(setFin)
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false))
  }

  useEffect(() => {
    if (!documentId) return
    setFin(null)
    load()
    getJSON('/api/financials/llm-status')
      .then((s) => setLlmAvailable(!!s.available))
      .catch(() => setLlmAvailable(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId])

  if (error) return <Alert severity="error">{error}</Alert>
  if (!fin) return <LinearProgress />

  const periods = fin.periods.length ? fin.periods : ['Value']

  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center"
        sx={{ mb: 2, flexWrap: 'wrap' }}>
        <Chip size="small" color="primary"
          label={`${fin.found_fields}/${fin.total_fields} fields`} />
        {fin.scale && <Chip size="small" label={`Figures in ${fin.scale}`} />}
        <Tooltip title="deterministic = parsed directly from the tables; hybrid = gaps filled by the LLM">
          <Chip size="small" variant="outlined" label={fin.method} />
        </Tooltip>
        <Box sx={{ flexGrow: 1 }} />
        {llmAvailable && (
          <Button size="small" variant="outlined" startIcon={<AutoAwesomeIcon />}
            disabled={busy} onClick={() => load({ force: true, useLlm: true })}>
            Enhance with AI
          </Button>
        )}
      </Stack>

      {busy && <LinearProgress sx={{ mb: 2 }} />}

      {fin.warnings?.map((w, i) => (
        <Alert key={i} severity="warning" sx={{ mb: 2 }}>{w}</Alert>
      ))}

      {SECTIONS.map(([key, title]) => (
        <StatementTable key={key} title={title}
          block={fin.statements[key]} periods={periods} />
      ))}
    </Box>
  )
}
