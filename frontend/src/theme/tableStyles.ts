import type { SxProps, Theme } from '@mui/material/styles';

/** Muted header row for data tables (matches Claims list / status history). */
export const tableHeadRowSx: SxProps<Theme> = (theme) => ({
  bgcolor: theme.palette.mode === 'dark' ? 'grey.800' : 'grey.100',
});
