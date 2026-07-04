// Browse the Saudi Exchange corpus, multi-select reports, add them to the cart.
import {
  Alert, Box, Button, Checkbox, Chip, CircularProgress, FormControl,
  InputLabel, LinearProgress, MenuItem, Paper, Select, Table, TableBody,
  TableCell, TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import AddShoppingCartIcon from '@mui/icons-material/AddShoppingCart'
import { useEffect, useState } from 'react'
import { getJSON, postJSON } from '../api'
import { useCart } from '../cart/CartContext'

export default function QueryReportsTab() {
  const cart = useCart()
  const [companies, setCompanies] = useState([])
  const [company, setCompany] = useState('')
  const [search, setSearch] = useState('')
  const [reports, setReports] = useState([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(new Set())
  const [adding, setAdding] = useState(false)
  const [notice, setNotice] = useState(null) // {severity, text}

  useEffect(() => {
    getJSON('/api/companies').then(setCompanies).catch(() => {})
  }, [])

  const fetchReports = async () => {
    setLoading(true)
    setNotice(null)
    try {
      const params = new URLSearchParams({ downloaded_only: 'true' })
      if (company) params.set('company_code', company)
      if (search) params.set('search', search)
      setReports(await getJSON(`/api/reports?${params}`))
      setSelected(new Set())
    } catch (e) {
      setNotice({ severity: 'error', text: e.message })
    } finally {
      setLoading(false)
    }
  }

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const allSelected = reports.length > 0 && selected.size === reports.length

  const addToCart = async () => {
    setAdding(true)
    setNotice(null)
    try {
      const { results } = await postJSON('/api/documents/register', {
        report_ids: [...selected],
      })
      const docs = results.filter((r) => r.document).map((r) => r.document)
      const failures = results.filter((r) => r.error)
      cart.add(docs)
      setNotice({
        severity: failures.length ? 'warning' : 'success',
        text: `${docs.length} document(s) added to cart`
          + (failures.length ? `; ${failures.length} failed (${failures[0].error})` : ''),
      })
      setSelected(new Set())
    } catch (e) {
      setNotice({ severity: 'error', text: e.message })
    } finally {
      setAdding(false)
    }
  }

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>Query Reports</Typography>

      <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
        <FormControl sx={{ minWidth: 240 }} size="small">
          <InputLabel>Company</InputLabel>
          <Select value={company} label="Company" onChange={(e) => setCompany(e.target.value)}>
            <MenuItem value="">All companies</MenuItem>
            {companies.map((c) => (
              <MenuItem key={c.company_code} value={c.company_code}>
                {c.company_name} ({c.company_code})
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <TextField
          size="small"
          label="Search filename / company / date"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && fetchReports()}
          sx={{ flexGrow: 1, minWidth: 220 }}
        />
        <Button variant="contained" onClick={fetchReports}>Fetch reports</Button>
        <Button
          variant="outlined"
          startIcon={adding ? <CircularProgress size={16} /> : <AddShoppingCartIcon />}
          disabled={selected.size === 0 || adding}
          onClick={addToCart}
        >
          Add {selected.size || ''} to cart
        </Button>
      </Box>

      {notice && <Alert severity={notice.severity} sx={{ mb: 2 }}>{notice.text}</Alert>}
      {loading && <LinearProgress sx={{ mb: 2 }} />}

      {reports.length > 0 && (
        <Paper variant="outlined" sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell padding="checkbox">
                  <Checkbox
                    checked={allSelected}
                    indeterminate={selected.size > 0 && !allSelected}
                    onChange={() =>
                      setSelected(allSelected ? new Set() : new Set(reports.map((r) => r.id)))}
                    inputProps={{ 'aria-label': 'select all reports' }}
                  />
                </TableCell>
                <TableCell>Company</TableCell>
                <TableCell>Filename</TableCell>
                <TableCell>Date</TableCell>
                <TableCell>PDF</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {reports.map((r) => (
                <TableRow key={r.id} hover onClick={() => toggle(r.id)} sx={{ cursor: 'pointer' }}>
                  <TableCell padding="checkbox">
                    <Checkbox checked={selected.has(r.id)} />
                  </TableCell>
                  <TableCell><Chip label={r.company_name} size="small" variant="outlined" /></TableCell>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>{r.filename}</TableCell>
                  <TableCell>{r.published_date ?? '—'}</TableCell>
                  <TableCell>
                    <Button size="small" href={`/api/pdf/${r.id}`} target="_blank"
                      rel="noopener" onClick={(e) => e.stopPropagation()}>
                      Open
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}
    </Box>
  )
}
