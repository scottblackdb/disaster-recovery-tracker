import React from 'react';
import { Chip } from '@mui/material';
import { STATUS_COLORS, STATUS_LABELS } from '../types';

interface Props {
  status: string;
  size?: 'small' | 'medium';
}

export default function StatusChip({ status, size = 'small' }: Props) {
  return (
    <Chip
      label={STATUS_LABELS[status] || status}
      size={size}
      sx={{
        backgroundColor: STATUS_COLORS[status] || '#999',
        color: '#fff',
        fontWeight: 600,
      }}
    />
  );
}
