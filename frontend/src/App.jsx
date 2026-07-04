import { createTheme, ThemeProvider, CssBaseline } from '@mui/material'
import { AppBar, Box, Card, CardContent, Tab, Tabs, Toolbar, Typography } from '@mui/material'
import { useState } from 'react'
import { CartProvider } from './cart/CartContext'
import CartDrawer from './components/CartDrawer'
import QueryReportsTab from './pages/QueryReportsTab'
import AcquireTab from './pages/AcquireTab'
import ExtractTab from './pages/ExtractTab'
import HistoryTab from './pages/HistoryTab'

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#6366f1', light: '#818cf8', dark: '#4f46e5' },
    background: { default: '#f1f5f9', paper: '#ffffff' },
    text: { primary: '#0f172a', secondary: '#64748b' },
  },
  typography: { fontFamily: '"DM Sans", sans-serif' },
  shape: { borderRadius: 12 },
})

const TABS = [
  { label: 'Query Reports', component: QueryReportsTab },
  { label: 'Acquire Reports', component: AcquireTab },
  { label: 'Extract Results', component: ExtractTab },
  { label: 'Extracted Tables', component: HistoryTab },
]

export default function App() {
  const [tab, setTab] = useState(0)
  const Active = TABS[tab].component

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <CartProvider>
        <AppBar position="sticky">
          <Toolbar>
            <Typography variant="h6" sx={{ flexGrow: 1 }}>
              Saudi Exchange — Table Extraction
            </Typography>
            <CartDrawer onGoToExtract={() => setTab(2)} />
          </Toolbar>
        </AppBar>

        <Box sx={{ minHeight: '100vh', px: { xs: 2, md: 6 }, py: 3 }}>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 3 }}>
            {TABS.map((t) => <Tab key={t.label} label={t.label} />)}
          </Tabs>

          <Card>
            <CardContent sx={{ p: { xs: 2, md: 4 } }}>
              <Active />
            </CardContent>
          </Card>
        </Box>
      </CartProvider>
    </ThemeProvider>
  )
}
