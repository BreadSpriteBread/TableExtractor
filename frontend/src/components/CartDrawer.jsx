// Cart button (with badge) + slide-out drawer, mounted in the app bar so the
// cart is visible and editable from every tab.
import {
  Badge, Box, Button, Divider, Drawer, IconButton, List, ListItem,
  ListItemText, Tooltip, Typography,
} from '@mui/material'
import ShoppingCartIcon from '@mui/icons-material/ShoppingCart'
import DeleteIcon from '@mui/icons-material/Delete'
import { useState } from 'react'
import { useCart } from '../cart/CartContext'
import SourceChip from './SourceChip'

export default function CartDrawer({ onGoToExtract }) {
  const cart = useCart()
  const [open, setOpen] = useState(false)

  return (
    <>
      <Tooltip title="Extraction cart">
        <IconButton color="inherit" onClick={() => setOpen(true)} aria-label="open cart">
          <Badge badgeContent={cart.count} color="secondary" data-testid="cart-badge">
            <ShoppingCartIcon />
          </Badge>
        </IconButton>
      </Tooltip>

      <Drawer anchor="right" open={open} onClose={() => setOpen(false)}>
        <Box sx={{ width: 380, p: 2, display: 'flex', flexDirection: 'column', height: '100%' }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Cart ({cart.count})
          </Typography>
          <Divider />
          <List dense sx={{ flexGrow: 1, overflowY: 'auto' }}>
            {cart.items.length === 0 && (
              <Typography color="text.secondary" sx={{ mt: 2 }}>
                Cart is empty. Add documents from Query Reports or Acquire Reports.
              </Typography>
            )}
            {cart.items.map((item) => (
              <ListItem
                key={item.document_id}
                secondaryAction={
                  <IconButton
                    edge="end"
                    size="small"
                    aria-label={`remove ${item.filename}`}
                    onClick={() => cart.remove(item.document_id)}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                }
              >
                <ListItemText
                  primary={item.filename}
                  primaryTypographyProps={{ fontFamily: 'monospace', fontSize: 12, noWrap: true }}
                  secondary={<SourceChip source={item.source} />}
                />
              </ListItem>
            ))}
          </List>
          <Divider sx={{ mb: 1 }} />
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              fullWidth
              variant="outlined"
              color="error"
              disabled={cart.count === 0}
              onClick={cart.clear}
            >
              Clear all
            </Button>
            <Button
              fullWidth
              variant="contained"
              disabled={cart.count === 0}
              onClick={() => { setOpen(false); onGoToExtract?.() }}
            >
              Extract
            </Button>
          </Box>
        </Box>
      </Drawer>
    </>
  )
}
