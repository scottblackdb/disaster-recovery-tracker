import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import {
  Box, Typography, Card, CardContent, Grid, Chip, Button,
  CircularProgress, Alert, TextField, MenuItem, Dialog, DialogTitle,
  DialogContent, DialogActions, LinearProgress, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Paper, Stack,
  ToggleButtonGroup, ToggleButton, IconButton, Tooltip,
} from '@mui/material';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import LinkIcon from '@mui/icons-material/Link';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import HistoryIcon from '@mui/icons-material/History';
import DescriptionIcon from '@mui/icons-material/Description';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import { fetchClaim, fetchCurrentUser, uploadDocument, uploadDocumentFromUrl, updateClaimStatus, deleteClaimDocument, getApiErrorMessage } from '../services/api';
import { Claim, Document, STATUS_LABELS } from '../types';
import StatusChip from '../components/StatusChip';
import { formatCurrency } from '../utils/format';

export default function ClaimDetail() {
  const { id } = useParams<{ id: string }>();
  const claimId = useMemo(() => {
    if (!id) return null;
    const n = Number.parseInt(id, 10);
    return Number.isNaN(n) ? null : n;
  }, [id]);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadNotice, setUploadNotice] = useState<{ severity: 'success' | 'error'; message: string } | null>(null);
  const [uploadMode, setUploadMode] = useState<'file' | 'url'>('file');
  const [urlInput, setUrlInput] = useState('');
  const [currentUserEmail, setCurrentUserEmail] = useState('Portal User');
  const [statusDialog, setStatusDialog] = useState(false);
  const [newStatus, setNewStatus] = useState('');
  const [statusNotes, setStatusNotes] = useState('');
  const [approvedAmountInput, setApprovedAmountInput] = useState('');
  const [statusFormError, setStatusFormError] = useState('');
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [deleteConfirmDoc, setDeleteConfirmDoc] = useState<Document | null>(null);
  const [deletingDocId, setDeletingDocId] = useState<number | null>(null);

  const resetStatusDialog = () => {
    setStatusDialog(false);
    setNewStatus('');
    setStatusNotes('');
    setApprovedAmountInput('');
    setStatusFormError('');
  };

  const loadClaim = useCallback(() => {
    if (claimId === null) {
      if (id) {
        setError('Invalid claim ID');
        setLoading(false);
      }
      return;
    }
    setLoading(true);
    fetchClaim(claimId)
      .then(setClaim)
      .catch((e) => setError(getApiErrorMessage(e)))
      .finally(() => setLoading(false));
  }, [claimId, id]);

  useEffect(() => { loadClaim(); }, [loadClaim]);

  useEffect(() => {
    fetchCurrentUser()
      .then(({ email }) => setCurrentUserEmail(email))
      .catch(() => {});
  }, []);

  const showUploadSuccess = (doc: any) => {
    setUploadNotice({
      severity: 'success',
      message:
        doc.ai_summary
          ? `AI extracted: ${doc.ai_extracted_vendor || 'Unknown vendor'}, ${formatCurrency(doc.ai_extracted_cost)}, Category ${doc.ai_extracted_category || '?'}`
          : 'Document uploaded and processed.',
    });
    loadClaim();
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || claimId === null) return;
    setUploading(true);
    setUploadNotice(null);
    try {
      const doc = await uploadDocument(claimId, file);
      showUploadSuccess(doc);
    } catch (e: unknown) {
      setUploadNotice({ severity: 'error', message: getApiErrorMessage(e) });
    } finally {
      setUploading(false);
    }
  };

  const handleUrlUpload = async () => {
    const trimmed = urlInput.trim();
    if (!trimmed || claimId === null) return;
    setUploading(true);
    setUploadNotice(null);
    try {
      const doc = await uploadDocumentFromUrl(claimId, trimmed);
      showUploadSuccess(doc);
      setUrlInput('');
    } catch (e: unknown) {
      setUploadNotice({ severity: 'error', message: getApiErrorMessage(e) });
    } finally {
      setUploading(false);
    }
  };

  const handleConfirmDeleteDocument = async () => {
    if (claimId === null || !deleteConfirmDoc) return;
    setDeletingDocId(deleteConfirmDoc.id);
    setUploadNotice(null);
    try {
      await deleteClaimDocument(claimId, deleteConfirmDoc.id);
      setDeleteConfirmDoc(null);
      loadClaim();
      setUploadNotice({ severity: 'success', message: 'Document removed from the claim and storage.' });
    } catch (e: unknown) {
      setUploadNotice({ severity: 'error', message: getApiErrorMessage(e) });
    } finally {
      setDeletingDocId(null);
    }
  };

  const handleStatusUpdate = async () => {
    if (claimId === null || !newStatus) return;
    setStatusFormError('');
    let approvedAmount: number | undefined;
    if (newStatus === 'approved') {
      const trimmed = approvedAmountInput.trim();
      if (trimmed === '') {
        setStatusFormError('Approved amount is required.');
        return;
      }
      const parsed = parseFloat(trimmed);
      if (Number.isNaN(parsed) || parsed < 0) {
        setStatusFormError('Enter a valid approved amount (zero or greater).');
        return;
      }
      approvedAmount = parsed;
    }
    setUpdatingStatus(true);
    try {
      await updateClaimStatus(claimId, newStatus, currentUserEmail, statusNotes, approvedAmount);
      resetStatusDialog();
      loadClaim();
    } catch (e: unknown) {
      setError(getApiErrorMessage(e));
    } finally {
      setUpdatingStatus(false);
    }
  };

  if (loading) return <Box display="flex" justifyContent="center" mt={8}><CircularProgress /></Box>;
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!claim) return null;

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box>
          <Typography variant="h4" fontWeight={700}>
            Claim #{claim.id}
          </Typography>
          <Typography variant="body1" color="text.secondary">
            {claim.incident_name} &mdash; {claim.county}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1}>
          <StatusChip status={claim.status} size="medium" />
          <Button
            variant="outlined"
            size="small"
            onClick={() => {
              setStatusFormError('');
              setNewStatus('');
              setStatusNotes('');
              setApprovedAmountInput('');
              setStatusDialog(true);
            }}
          >
            Update Status
          </Button>
        </Stack>
      </Box>

      <Grid container spacing={3}>
        {/* Claim Info */}
        <Grid size={{ xs: 12, md: 8 }}>
          <Card elevation={2}>
            <CardContent>
              <Typography variant="h6" fontWeight={600} mb={2}>Claim Details</Typography>
              <Grid container spacing={2}>
                <Grid size={6}><Typography variant="body2" color="text.secondary">Applicant</Typography>
                  <Typography fontWeight={600}>{claim.applicant_name}</Typography></Grid>
                <Grid size={6}><Typography variant="body2" color="text.secondary">County</Typography>
                  <Typography fontWeight={600}>{claim.county}</Typography></Grid>
                <Grid size={6}><Typography variant="body2" color="text.secondary">FEMA Category</Typography>
                  <Typography fontWeight={600}>
                    {claim.fema_code ? `Cat ${claim.fema_code} - ${claim.fema_category_name}` : 'Pending AI Classification'}
                  </Typography></Grid>
                <Grid size={6}><Typography variant="body2" color="text.secondary">Estimated Cost</Typography>
                  <Typography fontWeight={600} color="primary">{formatCurrency(claim.estimated_cost)}</Typography></Grid>
                <Grid size={6}><Typography variant="body2" color="text.secondary">Approved Amount</Typography>
                  <Typography fontWeight={600} color="success.main">{formatCurrency(claim.approved_amount)}</Typography></Grid>
                <Grid size={6}><Typography variant="body2" color="text.secondary">Submitted</Typography>
                  <Typography>{new Date(claim.submitted_at).toLocaleString()}</Typography></Grid>
                <Grid size={12}><Typography variant="body2" color="text.secondary">Description</Typography>
                  <Typography>{claim.description || 'No description provided'}</Typography></Grid>
              </Grid>
            </CardContent>
          </Card>
        </Grid>

        {/* AI Insights */}
        <Grid size={{ xs: 12, md: 4 }}>
          <Card elevation={2} sx={(t) => ({ borderLeft: `4px solid ${t.palette.secondary.main}` })}>
            <CardContent>
              <Box display="flex" alignItems="center" gap={1} mb={2}>
                <SmartToyIcon color="secondary" />
                <Typography variant="h6" fontWeight={600}>AI Insights</Typography>
              </Box>
              {claim.ai_confidence_score != null ? (
                <>
                  <Typography variant="body2" color="text.secondary" mb={0.5}>Confidence Score</Typography>
                  <Box display="flex" alignItems="center" gap={1} mb={2}>
                    <LinearProgress
                      variant="determinate"
                      value={claim.ai_confidence_score}
                      sx={{ flexGrow: 1, height: 8, borderRadius: 4 }}
                      color={claim.ai_confidence_score > 70 ? 'success' : claim.ai_confidence_score > 40 ? 'warning' : 'error'}
                    />
                    <Typography fontWeight={600}>{claim.ai_confidence_score}%</Typography>
                  </Box>
                  {claim.ai_flags && (
                    <>
                      <Typography variant="body2" color="text.secondary" mb={0.5}>Flags</Typography>
                      <Alert severity="warning" sx={{ mb: 1 }}>{claim.ai_flags}</Alert>
                    </>
                  )}
                </>
              ) : (
                <Typography color="text.secondary">Upload documents to trigger AI analysis</Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Document Upload */}
        <Grid size={12}>
          <Card elevation={2}>
            <CardContent>
              <Box display="flex" alignItems="center" gap={1} mb={2}>
                <DescriptionIcon color="primary" />
                <Typography variant="h6" fontWeight={600}>
                  Documents ({claim.documents?.length || 0})
                </Typography>
              </Box>

              <Box sx={{ mb: 2, p: 2, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                <ToggleButtonGroup
                  value={uploadMode}
                  exclusive
                  onChange={(_, v) => { if (v) setUploadMode(v); }}
                  size="small"
                  sx={{ mb: 2 }}
                >
                  <ToggleButton value="file"><CloudUploadIcon sx={{ mr: 0.5 }} fontSize="small" />Local File</ToggleButton>
                  <ToggleButton value="url"><LinkIcon sx={{ mr: 0.5 }} fontSize="small" />From URL</ToggleButton>
                </ToggleButtonGroup>

                {uploadMode === 'file' ? (
                  <Box>
                    <Button
                      variant="contained"
                      component="label"
                      startIcon={uploading ? <CircularProgress size={20} color="inherit" /> : <CloudUploadIcon />}
                      disabled={uploading}
                    >
                      {uploading ? 'Processing with AI...' : 'Choose File'}
                      <input type="file" hidden onChange={handleFileUpload} accept=".pdf,.png,.jpg,.jpeg,.txt,.csv" />
                    </Button>
                    <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                      PDF, images, text, or CSV
                    </Typography>
                  </Box>
                ) : (
                  <Stack direction="row" spacing={1} alignItems="flex-start">
                    <TextField
                      fullWidth
                      size="small"
                      label="Image or document URL"
                      placeholder="https://example.com/invoice.png"
                      value={urlInput}
                      onChange={(e) => setUrlInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleUrlUpload()}
                      disabled={uploading}
                    />
                    <Button
                      variant="contained"
                      onClick={handleUrlUpload}
                      disabled={uploading || !urlInput.trim()}
                      startIcon={uploading ? <CircularProgress size={20} color="inherit" /> : <LinkIcon />}
                      sx={{ whiteSpace: 'nowrap' }}
                    >
                      {uploading ? 'Processing...' : 'Fetch & Analyze'}
                    </Button>
                  </Stack>
                )}
              </Box>

              {uploading && (
                <Alert severity="info" icon={<SmartToyIcon />} sx={{ mb: 2 }}>
                  AI is analyzing your document... extracting vendor, cost, date, and recommending FEMA category.
                </Alert>
              )}

              {uploadNotice && (
                <Alert severity={uploadNotice.severity} sx={{ mb: 2 }}>{uploadNotice.message}</Alert>
              )}

              {claim.documents && claim.documents.length > 0 ? (
                <Stack spacing={2}>
                  {claim.documents.map((doc) => (
                    <Paper key={doc.id} variant="outlined" sx={{ p: 2 }}>
                      <Box display="flex" alignItems="center" justifyContent="space-between" mb={1}>
                        <Box display="flex" alignItems="center" gap={1}>
                          <DescriptionIcon fontSize="small" color="action" />
                          <Typography fontWeight={600}>{doc.file_name}</Typography>
                          <Chip
                            label={doc.processing_status}
                            size="small"
                            color={doc.processing_status === 'completed' ? 'success' : 'default'}
                          />
                        </Box>
                        <Stack direction="row" spacing={1} alignItems="center">
                          {doc.ai_extracted_category && (
                            <Chip label={`Cat ${doc.ai_extracted_category}`} size="small" color="secondary" />
                          )}
                          {doc.storage_path && (
                            <Button
                              size="small"
                              variant="outlined"
                              startIcon={<OpenInNewIcon />}
                              href={`/api/documents/${doc.id}/file`}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              View File
                            </Button>
                          )}
                          <Tooltip title="Delete from claim and Unity Catalog volume">
                            <span>
                              <IconButton
                                size="small"
                                color="error"
                                aria-label={`Delete ${doc.file_name}`}
                                disabled={deletingDocId !== null}
                                onClick={() => setDeleteConfirmDoc(doc)}
                              >
                                {deletingDocId === doc.id ? (
                                  <CircularProgress size={20} />
                                ) : (
                                  <DeleteOutlineIcon fontSize="small" />
                                )}
                              </IconButton>
                            </span>
                          </Tooltip>
                        </Stack>
                      </Box>
                      <Grid container spacing={2} sx={{ mb: doc.ai_damage_description || doc.ai_summary ? 1.5 : 0 }}>
                        <Grid size={{ xs: 6, sm: 3 }}>
                          <Typography variant="caption" color="text.secondary">Vendor</Typography>
                          <Typography variant="body2">{doc.ai_extracted_vendor || '—'}</Typography>
                        </Grid>
                        <Grid size={{ xs: 6, sm: 3 }}>
                          <Typography variant="caption" color="text.secondary">Cost</Typography>
                          <Typography variant="body2">{formatCurrency(doc.ai_extracted_cost)}</Typography>
                        </Grid>
                        <Grid size={{ xs: 6, sm: 3 }}>
                          <Typography variant="caption" color="text.secondary">Date</Typography>
                          <Typography variant="body2">{doc.ai_extracted_date || '—'}</Typography>
                        </Grid>
                        <Grid size={{ xs: 6, sm: 3 }}>
                          <Typography variant="caption" color="text.secondary">Category</Typography>
                          <Typography variant="body2">{doc.ai_extracted_category ? `Cat ${doc.ai_extracted_category}` : '—'}</Typography>
                        </Grid>
                      </Grid>
                      {doc.ai_summary && (
                        <Box mb={1}>
                          <Typography variant="caption" color="text.secondary">Summary</Typography>
                          <Typography variant="body2">{doc.ai_summary}</Typography>
                        </Box>
                      )}
                      {doc.ai_damage_description && (
                        <Box sx={{ p: 1.5, borderRadius: 1, bgcolor: 'action.hover' }}>
                          <Typography variant="caption" color="text.secondary">Damage Description</Typography>
                          <Typography variant="body2">{doc.ai_damage_description}</Typography>
                        </Box>
                      )}
                    </Paper>
                  ))}
                </Stack>
              ) : (
                <Typography color="text.secondary" textAlign="center" py={3}>
                  No documents uploaded yet. Upload contractor estimates, invoices, or photos for AI analysis.
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Status History */}
        {claim.status_history && claim.status_history.length > 0 && (
          <Grid size={12}>
            <Card elevation={2}>
              <CardContent>
                <Box display="flex" alignItems="center" gap={1} mb={2}>
                  <HistoryIcon color="action" />
                  <Typography variant="h6" fontWeight={600}>Status History</Typography>
                </Box>
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow sx={(t) => ({ bgcolor: t.palette.mode === 'dark' ? 'grey.800' : 'grey.100' })}>
                        <TableCell><strong>Date</strong></TableCell>
                        <TableCell><strong>From</strong></TableCell>
                        <TableCell><strong>To</strong></TableCell>
                        <TableCell><strong>Changed By</strong></TableCell>
                        <TableCell><strong>Notes</strong></TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {claim.status_history.map((h) => (
                        <TableRow key={h.id}>
                          <TableCell>{new Date(h.changed_at).toLocaleString()}</TableCell>
                          <TableCell>{h.old_status ? <StatusChip status={h.old_status} /> : '—'}</TableCell>
                          <TableCell><StatusChip status={h.new_status} /></TableCell>
                          <TableCell>{h.changed_by}</TableCell>
                          <TableCell>{h.notes || '—'}</TableCell>
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

      {/* Status Update Dialog */}
      <Dialog open={statusDialog} onClose={resetStatusDialog} maxWidth="sm" fullWidth>
        <DialogTitle>Update Claim Status</DialogTitle>
        <DialogContent>
          <TextField
            select fullWidth
            label="New Status"
            value={newStatus}
            onChange={(e) => {
              const v = e.target.value;
              setNewStatus(v);
              if (v === 'approved' && claim) {
                setApprovedAmountInput(
                  claim.approved_amount != null
                    ? String(claim.approved_amount)
                    : String(claim.estimated_cost ?? '')
                );
              } else {
                setApprovedAmountInput('');
              }
              setStatusFormError('');
            }}
            sx={{ mt: 1, mb: 2 }}
          >
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <MenuItem key={value} value={value}>{label}</MenuItem>
            ))}
          </TextField>
          {newStatus === 'approved' && (
            <TextField
              fullWidth
              required
              type="number"
              label="Approved amount ($)"
              value={approvedAmountInput}
              onChange={(e) => {
                setApprovedAmountInput(e.target.value);
                setStatusFormError('');
              }}
              inputProps={{ min: 0, step: '0.01' }}
              sx={{ mb: 2 }}
              helperText="Required when approving this claim."
            />
          )}
          {statusFormError && (
            <Alert severity="error" sx={{ mb: 2 }}>{statusFormError}</Alert>
          )}
          <TextField
            fullWidth multiline rows={3}
            label="Notes"
            value={statusNotes}
            onChange={(e) => setStatusNotes(e.target.value)}
            placeholder="Reason for status change..."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={resetStatusDialog}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleStatusUpdate}
            disabled={
              !newStatus
              || updatingStatus
              || (newStatus === 'approved' && approvedAmountInput.trim() === '')
            }
          >
            {updatingStatus ? 'Updating...' : 'Update'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={deleteConfirmDoc !== null}
        onClose={() => { if (deletingDocId === null) setDeleteConfirmDoc(null); }}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>Delete document?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            Remove <strong>{deleteConfirmDoc?.file_name}</strong> from this claim and delete the file from the Unity Catalog volume. This cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirmDoc(null)} disabled={deletingDocId !== null}>
            Cancel
          </Button>
          <Button
            color="error"
            variant="contained"
            onClick={handleConfirmDeleteDocument}
            disabled={deletingDocId !== null}
          >
            {deletingDocId !== null ? 'Deleting…' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
