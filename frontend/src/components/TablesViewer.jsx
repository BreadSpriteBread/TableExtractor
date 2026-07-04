// Renders one extracted document result: status, errors, and each table
// with its metadata flags (pages, method, confidence, rotated/nested/spans).
import {
  Alert, Box, Chip, Paper, Stack, Table, TableBody, TableCell,
  TableHead, TableRow, Typography,
} from '@mui/material'
import StatusChip from './StatusChip'

function TableMeta({ t }) {
  return (
    <Stack direction="row" spacing={1} sx={{ mb: 1, flexWrap: 'wrap' }}>
      <Chip size="small" label={`pages ${t.pages.join(', ')}`} />
      <Chip size="small" label={t.extraction_method} color={t.extraction_method === 'docling_full' ? 'warning' : 'default'} />
      <Chip size="small" label={`confidence ${(t.confidence * 100).toFixed(0)}%`} />
      {t.spans_pages && <Chip size="small" color="info" label="multi-page" />}
      {t.rotated && <Chip size="small" color="info" label="rotated" />}
      {t.nested && <Chip size="small" color="info" label="nested (flattened)" />}
    </Stack>
  )
}

export default function TablesViewer({ result }) {
  if (!result) return null
  return (
    <Box>
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
        <StatusChip status={result.status} />
        <Typography variant="body2" color="text.secondary">
          {result.filename} — {result.page_count} page(s), {result.tables.length} table(s)
        </Typography>
      </Stack>

      {result.errors?.length > 0 && (
        <Alert severity={result.status === 'failed' ? 'error' : 'warning'} sx={{ mb: 2 }}>
          {result.errors.map((e, i) => <div key={i}>{e}</div>)}
        </Alert>
      )}

      {result.tables.map((t) => (
        <Box key={t.table_id} sx={{ mb: 3 }}>
          <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Table {t.table_id}</Typography>
          <TableMeta t={t} />
          <Paper variant="outlined" sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  {t.headers.map((h, i) => (
                    <TableCell key={i} sx={{ fontWeight: 700 }}>{h}</TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {t.rows.map((row, ri) => (
                  <TableRow key={ri}>
                    {row.map((cell, ci) => <TableCell key={ci}>{cell}</TableCell>)}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Paper>
        </Box>
      ))}
    </Box>
  )
}
