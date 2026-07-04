import { Chip } from '@mui/material'

export default function SourceChip({ source }) {
  return (
    <Chip
      label={source === 'upload' ? 'Upload' : 'Saudi Exchange'}
      size="small"
      variant="outlined"
      color={source === 'upload' ? 'info' : 'primary'}
      component="span"
    />
  )
}
