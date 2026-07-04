// Acquire documents: upload PDFs, or trigger the Saudi Exchange scraper.
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress,
  LinearProgress, List, ListItem, ListItemText, Typography,
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

  const pollScrape = async () => {
    try {
      const status = await getJSON('/api/scrape/status')
      setScrapeStatus(status)
      if (status.state === 'running') setTimeout(pollScrape, 1500)
    } catch { /* backend gone; stop polling */ }
  }

  useEffect(() => { pollScrape() }, [])  // show current state on mount

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
    setScrapeBusy(true)
    try {
      await postJSON('/api/scrape', {})
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

      <Card variant="outlined" sx={{ flex: '1 1 420px' }}>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 1 }}>Download from Saudi Exchange</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Scrapes financial reports for the top listed companies with a
            headful browser. Runs in the background; new files appear under
            Query Reports when it finishes.
          </Typography>
          <Button
            variant="contained"
            startIcon={<CloudDownloadIcon />}
            disabled={scrapeBusy || scrapeStatus?.state === 'running'}
            onClick={startScrape}
          >
            {scrapeStatus?.state === 'running' ? 'Scraping…' : 'Start scrape'}
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
