import React, { useEffect, useState } from 'react';
import {
  Box, Card, CardContent, Grid, Typography, CircularProgress, Alert,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
} from '@mui/material';
import AttachMoneyIcon from '@mui/icons-material/AttachMoney';
import AssignmentIcon from '@mui/icons-material/Assignment';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import PendingIcon from '@mui/icons-material/Pending';
import { fetchDashboardStats, getApiErrorMessage } from '../services/api';
import { DashboardStats, STATUS_COLORS } from '../types';
import StatusChip from '../components/StatusChip';
import { formatCurrency } from '../utils/format';

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchDashboardStats()
      .then(setStats)
      .catch((e) => setError(getApiErrorMessage(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Box display="flex" justifyContent="center" mt={8}><CircularProgress /></Box>;
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!stats) return null;

  const summaryCards = [
    { label: 'Total Claims', value: stats.total_claims, icon: <AssignmentIcon />, color: '#1976d2' },
    { label: 'Estimated Cost', value: formatCurrency(stats.total_estimated_cost), icon: <AttachMoneyIcon />, color: '#ed6c02' },
    { label: 'Approved Amount', value: formatCurrency(stats.total_approved_amount), icon: <CheckCircleIcon />, color: '#2e7d32' },
    { label: 'Pending Review', value: stats.by_status['submitted'] || 0, icon: <PendingIcon />, color: '#9c27b0' },
  ];

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>
        Recovery Dashboard
      </Typography>
      <Typography variant="body1" color="text.secondary" mb={3}>
        Real-time overview of Public Assistance claims and FEMA reimbursement tracking.
      </Typography>

      <Grid container spacing={3} mb={4}>
        {summaryCards.map((card) => (
          <Grid size={{ xs: 12, sm: 6, md: 3 }} key={card.label}>
            <Card elevation={2}>
              <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <Box sx={{ backgroundColor: card.color, borderRadius: 2, p: 1.5, color: '#fff', display: 'flex' }}>
                  {card.icon}
                </Box>
                <Box>
                  <Typography variant="body2" color="text.secondary">{card.label}</Typography>
                  <Typography variant="h5" fontWeight={700}>{card.value}</Typography>
                </Box>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 5 }}>
          <Card elevation={2}>
            <CardContent>
              <Typography variant="h6" fontWeight={600} mb={2}>Claims by Status</Typography>
              {Object.entries(stats.by_status).length === 0 ? (
                <Typography color="text.secondary">No claims yet</Typography>
              ) : (
                <Box>
                  {Object.entries(stats.by_status).map(([status, count]) => (
                    <Box key={status} display="flex" alignItems="center" justifyContent="space-between" mb={1.5}>
                      <StatusChip status={status} />
                      <Box sx={{ flexGrow: 1, mx: 2, height: 8, bgcolor: 'divider', borderRadius: 4 }}>
                        <Box
                          sx={{
                            width: `${Math.min((count / Math.max(stats.total_claims, 1)) * 100, 100)}%`,
                            height: '100%',
                            backgroundColor: STATUS_COLORS[status] || '#999',
                            borderRadius: 4,
                          }}
                        />
                      </Box>
                      <Typography fontWeight={600}>{count}</Typography>
                    </Box>
                  ))}
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 7 }}>
          <Card elevation={2}>
            <CardContent>
              <Typography variant="h6" fontWeight={600} mb={2}>Claims by FEMA Category</Typography>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell><strong>Category</strong></TableCell>
                      <TableCell><strong>Name</strong></TableCell>
                      <TableCell align="right"><strong>Claims</strong></TableCell>
                      <TableCell align="right"><strong>Total Cost</strong></TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {stats.by_category.map((cat) => (
                      <TableRow key={cat.code}>
                        <TableCell>
                          <Typography fontWeight={700} color="primary">Cat {cat.code}</Typography>
                        </TableCell>
                        <TableCell>{cat.name}</TableCell>
                        <TableCell align="right">{cat.count}</TableCell>
                        <TableCell align="right">{formatCurrency(cat.total_cost)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </CardContent>
          </Card>
        </Grid>

        {stats.by_county.length > 0 && (
          <Grid size={12}>
            <Card elevation={2}>
              <CardContent>
                <Typography variant="h6" fontWeight={600} mb={2}>Top Counties by Claims</Typography>
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell><strong>County</strong></TableCell>
                        <TableCell align="right"><strong>Claims</strong></TableCell>
                        <TableCell align="right"><strong>Total Estimated Cost</strong></TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {stats.by_county.map((c) => (
                        <TableRow key={c.county}>
                          <TableCell>{c.county}</TableCell>
                          <TableCell align="right">{c.count}</TableCell>
                          <TableCell align="right">{formatCurrency(c.total_cost)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </CardContent>
            </Card>
          </Grid>
        )}
      </Grid>
    </Box>
  );
}
