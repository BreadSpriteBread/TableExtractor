import { Chip } from '@mui/material'

const COLORS = {
  success: 'success',
  partial: 'warning',
  failed: 'error',
  cached: 'success',
  running: 'info',
  queued: 'default',
  cancelled: 'default',
}

const LABELS = {
  cached: 'Done (cached)',
  success: 'Done',
}

export default function StatusChip({ status }) {
  if (!status) return <Chip label="Not extracted" size="small" variant="outlined" />
  return (
    <Chip
      label={LABELS[status] ?? status}
      color={COLORS[status] ?? 'default'}
      size="small"
      data-status={status}
    />
  )
}
