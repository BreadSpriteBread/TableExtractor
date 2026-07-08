// Acquire documents: upload PDFs, or trigger the Saudi Exchange scraper.
import {
  Alert, Box, Button, Card, CardContent, Checkbox, Chip, CircularProgress,
  Divider, LinearProgress, List, ListItem, ListItemButton, ListItemIcon,
  ListItemText, Stack, TextField, Typography,
} from '@mui/material'
import UploadFileIcon from '@mui/icons-material/UploadFile'
import CloudDownloadIcon from '@mui/icons-material/CloudDownload'
import AddShoppingCartIcon from '@mui/icons-material/AddShoppingCart'
import { useEffect, useRef, useState } from 'react'
import { getJSON, postJSON, uploadFiles } from '../api'
import { useCart } from '../cart/CartContext'
import SourceChip from '../components/SourceChip'

export default function AcquireTab() {
  const cart = useCart()
  const fileInput = useRef(null)
  const [uploading, setUploading] = useState(false)
  const [uploaded, setUploaded] = useState([])   // document dicts
  const [uploadErrors, setUploadErrors] = useState([])
  const [scrapeStatus, setScrapeStatus] = useState(null)
  const [scrapeBusy, setScrapeBusy] = useState(false)
  const [companies, setCompanies] = useState([])
  const [selected, setSelected] = useState(() => new Set())
  const [filter, setFilter] = useState('')
  const wasRunning = useRef(false)

  const loadCompanies = async () => {
    try {
      const { companies } = await getJSON('/api/scrape/companies')
      setCompanies(companies)
    } catch { /* backend gone */ }
  }

  const pollScrape = async () => {
    try {
      const status = await getJSON('/api/scrape/status')
      setScrapeStatus(status)
      if (status.state === 'running') {
        wasRunning.current = true
        setTimeout(pollScrape, 1500)
      } else if (wasRunning.current) {
        wasRunning.current = false
        loadCompanies()  // refresh scraped markers when a run finishes
      }
    } catch { /* backend gone; stop polling */ }
  }

  useEffect(() => { pollScrape(); loadCompanies() }, [])  // initial state

  const visible = companies.filter((c) => {
    const q = filter.trim().toLowerCase()
    if (!q) return true
    return c.code.toLowerCase().includes(q)
      || c.name.toLowerCase().includes(q)
      || (c.sector || '').toLowerCase().includes(q)
  })

  const toggle = (code) => setSelected((prev) => {
    const next = new Set(prev)
    next.has(code) ? next.delete(code) : next.add(code)
    return next
  })

  const allVisibleSelected = visible.length > 0 && visible.every((c) => selected.has(c.code))
  const toggleAllVisible = () => setSelected((prev) => {
    const next = new Set(prev)
    if (allVisibleSelected) visible.forEach((c) => next.delete(c.code))
    else visible.forEach((c) => next.add(c.code))
    return next
  })

  const onFiles = async (fileList) => {
    const files = [...fileList]
    if (!files.length) return
    setUploading(true)
    setUploadErrors([])
    try {
      const { results } = await uploadFiles(files)
      const docs = results.filter((r) => r.document).map((r) => r.document)
      setUploaded((prev) => {
        const known = new Set(prev.map((d) => d.document_id))
        return [...prev, ...docs.filter((d) => !known.has(d.document_id))]
      })
      setUploadErrors(results.filter((r) => r.error))
    } catch (e) {
      setUploadErrors([{ filename: '', error: e.message }])
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const startScrape = async () => {
    if (selected.size === 0) return
    setScrapeBusy(true)
    try {
      await postJSON('/api/scrape', { codes: [...selected] })
    } catch { /* 409 = already running; status poll shows it */ }
    setScrapeBusy(false)
    pollScrape()
  }

  return (
    <Box sx={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
      <Card variant="outlined" sx={{ flex: '1 1 420px' }}>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 1 }}>Upload PDFs</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Uploaded files are content-addressed (SHA-256); re-uploading the same
            file maps to the same document.
          </Typography>
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf"
            multiple
            hidden
            data-testid="upload-input"
            onChange={(e) => onFiles(e.target.files)}
          />
          <Button
            variant="contained"
            startIcon={uploading ? <CircularProgress size={16} color="inherit" /> : <UploadFileIcon />}
            disabled={uploading}
            onClick={() => fileInput.current?.click()}
          >
            Choose PDF files
          </Button>

          {uploadErrors.map((e, i) => (
            <Alert key={i} severity="error" sx={{ mt: 2 }}>
              {e.filename ? `${e.filename}: ` : ''}{e.error}
            </Alert>
          ))}

          {uploaded.length > 0 && (
            <>
              <Typography variant="subtitle2" sx={{ mt: 2 }}>
                Uploaded this session
              </Typography>
              <List dense>
                {uploaded.map((d) => (
                  <ListItem
                    key={d.document_id}
                    secondaryAction={
                      cart.has(d.document_id)
                        ? <Chip size="small" label="In cart" color="success" />
                        : (
                          <Button
                            size="small"
                            startIcon={<AddShoppingCartIcon />}
                            onClick={() => cart.add(d)}
                          >
                            Add to cart
                          </Button>
                        )
                    }
                  >
                    <ListItemText
                      primary={d.filename}
                      primaryTypographyProps={{ fontFamily: 'monospace', fontSize: 12 }}
                      secondary={<SourceChip source={d.source} />}
                    />
                  </ListItem>
                ))}
              </List>
            </>
          )}
        </CardContent>
      </Card>

      <Card variant="outlined" sx={{ flex: '1 1 480px' }}>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 1 }}>Download from Saudi Exchange</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Pick the companies to scrape financial reports for. Files land in
            <code> saudi_exchange_pdfs/&lt;code&gt;_&lt;name&gt;</code> and appear under
            Query Reports when the run finishes. Already-scraped companies are
            marked but can be re-scraped.
          </Typography>

          <TextField
            size="small"
            fullWidth
            placeholder="Filter by code, name, or sector"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            sx={{ mb: 1 }}
            inputProps={{ 'data-testid': 'company-filter' }}
          />

          <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 0.5 }}>
            <Button size="small" onClick={toggleAllVisible} disabled={visible.length === 0}>
              {allVisibleSelected ? 'Clear' : 'Select'} shown ({visible.length})
            </Button>
            <Typography variant="caption" color="text.secondary">
              {selected.size} selected
            </Typography>
          </Stack>

          <Box sx={{ maxHeight: 320, overflow: 'auto', border: 1, borderColor: 'divider', borderRadius: 1 }}>
            <List dense disablePadding>
              {visible.map((c) => (
                <ListItem key={c.code} disablePadding
                  secondaryAction={c.scraped
                    ? <Chip size="small" color="success" variant="outlined"
                        label={`scraped · ${c.pdf_count}`} />
                    : null}
                >
                  <ListItemButton onClick={() => toggle(c.code)} dense>
                    <ListItemIcon sx={{ minWidth: 36 }}>
                      <Checkbox edge="start" size="small" tabIndex={-1} disableRipple
                        checked={selected.has(c.code)} />
                    </ListItemIcon>
                    <ListItemText
                      primary={`${c.code} — ${c.name}`}
                      secondary={c.sector}
                      primaryTypographyProps={{ fontSize: 14 }}
                    />
                  </ListItemButton>
                </ListItem>
              ))}
              {visible.length === 0 && (
                <ListItem><ListItemText secondary="No companies match the filter." /></ListItem>
              )}
            </List>
          </Box>

          <Divider sx={{ my: 2 }} />

          <Button
            variant="contained"
            startIcon={scrapeStatus?.state === 'running'
              ? <CircularProgress size={16} color="inherit" />
              : <CloudDownloadIcon />}
            disabled={scrapeBusy || scrapeStatus?.state === 'running' || selected.size === 0}
            onClick={startScrape}
          >
            {scrapeStatus?.state === 'running'
              ? 'Scraping…'
              : `Scrape ${selected.size || ''} selected`}
          </Button>

          {scrapeStatus?.state === 'running' && <LinearProgress sx={{ mt: 2 }} />}
          {scrapeStatus && scrapeStatus.state !== 'idle' && (
            <Alert
              severity={scrapeStatus.state === 'error' ? 'error' : 'info'}
              sx={{ mt: 2 }}
            >
              {scrapeStatus.state}: {scrapeStatus.message || '—'}
              {scrapeStatus.downloaded > 0 && ` (${scrapeStatus.downloaded} downloaded, ${scrapeStatus.failed} failed)`}
            </Alert>
          )}
        </CardContent>
      </Card>
    </Box>
  )
}
