import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box, Typography, Card, CardContent, TextField, MenuItem, Button,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Paper, CircularProgress, Alert, Chip, InputAdornment, Stack
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import AddCircleIcon from '@mui/icons-material/AddCircle';
import DescriptionIcon from '@mui/icons-material/Description';
import { fetchClaims, getApiErrorMessage } from '../services/api';
import { Claim, STATUS_LABELS } from '../types';
import StatusChip from '../components/StatusChip';
import { tableHeadRowSx } from '../theme/tableStyles';
import { formatCurrency } from '../utils/format';

const statusOptions = [
  { value: '', label: 'All Statuses' },
  ...Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label })),
];

export default function ClaimsList() {
  const navigate = useNavigate();
  const [claims, setClaims] = useState<Claim[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [countyFilter, setCountyFilter] = useState('');

  const loadClaims = () => {
    setLoading(true);
    fetchClaims({
      status: statusFilter || undefined,
      county: countyFilter || undefined,
    })
      .then(setClaims)
      .catch((e) => setError(getApiErrorMessage(e)))
      .finally(() => setLoading(false));
  };

  // Refetch when status filter changes. County uses explicit Search / Enter (not in deps).
  useEffect(() => {
    loadClaims();
  }, [statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight={700}>Claims</Typography>
        <Button
          variant="contained"
          startIcon={<AddCircleIcon />}
          onClick={() => navigate('/claims/new')}
        >
          Submit New Claim
        </Button>
      </Box>

      <Card elevation={2} sx={{ mb: 3 }}>
        <CardContent>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems="center">
            <TextField
              select
              label="Status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              size="small"
              sx={{ minWidth: 180 }}
            >
              {statusOptions.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>
              ))}
            </TextField>
            <TextField
              label="Search County"
              value={countyFilter}
              onChange={(e) => setCountyFilter(e.target.value)}
              size="small"
              InputProps={{
                startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment>,
              }}
              onKeyDown={(e) => e.key === 'Enter' && loadClaims()}
            />
            <Button variant="outlined" onClick={loadClaims}>Search</Button>
          </Stack>
        </CardContent>
      </Card>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {loading ? (
        <Box display="flex" justifyContent="center" mt={4}><CircularProgress /></Box>
      ) : (
        <TableContainer component={Paper} elevation={2}>
          <Table>
            <TableHead>
              <TableRow sx={tableHeadRowSx}>
                <TableCell><strong>ID</strong></TableCell>
                <TableCell><strong>Incident</strong></TableCell>
                <TableCell><strong>County</strong></TableCell>
                <TableCell><strong>Applicant</strong></TableCell>
                <TableCell><strong>FEMA Cat.</strong></TableCell>
                <TableCell align="right"><strong>Est. Cost</strong></TableCell>
                <TableCell><strong>Status</strong></TableCell>
                <TableCell align="center"><strong>Docs</strong></TableCell>
                <TableCell><strong>Submitted</strong></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {claims.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} align="center" sx={{ py: 4 }}>
                    <Typography color="text.secondary">No claims found. Submit your first claim to get started.</Typography>
                  </TableCell>
                </TableRow>
              ) : (
                claims.map((claim) => (
                  <TableRow
                    key={claim.id}
                    hover
                    sx={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/claims/${claim.id}`)}
                  >
                    <TableCell>#{claim.id}</TableCell>
                    <TableCell><strong>{claim.incident_name}</strong></TableCell>
                    <TableCell>{claim.county}</TableCell>
                    <TableCell>{claim.applicant_name}</TableCell>
                    <TableCell>
                      {claim.fema_code ? (
                        <Chip label={`Cat ${claim.fema_code}`} size="small" color="primary" variant="outlined" />
                      ) : '—'}
                    </TableCell>
                    <TableCell align="right">{formatCurrency(claim.estimated_cost)}</TableCell>
                    <TableCell><StatusChip status={claim.status} /></TableCell>
                    <TableCell align="center">
                      <Chip
                        icon={<DescriptionIcon />}
                        label={claim.document_count || 0}
                        size="small"
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell>{new Date(claim.submitted_at).toLocaleDateString()}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  );
}
