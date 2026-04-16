import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box, Typography, Card, CardContent, TextField, MenuItem, Button,
  Grid, Alert, CircularProgress, Stack, Dialog, DialogTitle,
  DialogContent, DialogActions,
} from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import ImageOutlinedIcon from '@mui/icons-material/ImageOutlined';
import { createClaim, fetchCategories, fetchCurrentUser, getApiErrorMessage, previewDamageDescription, refineDescription } from '../services/api';
import { FemaCategory } from '../types';

export default function NewClaim() {
  const navigate = useNavigate();
  const [categories, setCategories] = useState<FemaCategory[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [categoriesError, setCategoriesError] = useState('');
  const [imageUrl, setImageUrl] = useState('');
  const [extractingDamage, setExtractingDamage] = useState(false);
  const [extractError, setExtractError] = useState('');
  const [selectedImageName, setSelectedImageName] = useState('');
  const [previewStoragePath, setPreviewStoragePath] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Refine description state
  const [refining, setRefining] = useState(false);
  const [refineDialog, setRefineDialog] = useState(false);
  const [refinedText, setRefinedText] = useState('');
  const [refineError, setRefineError] = useState('');

  const [form, setForm] = useState({
    incident_name: '',
    county: '',
    applicant_name: '',
    description: '',
    estimated_cost: '',
    submitted_by: '',
    fema_category_id: '',
  });

  useEffect(() => {
    fetchCurrentUser()
      .then(({ email }) => {
        setForm((prev) => prev.submitted_by ? prev : { ...prev, submitted_by: email });
      })
      .catch(() => {});

    setCategoriesError('');
    fetchCategories()
      .then(setCategories)
      .catch((e) => {
        setCategories([]);
        setCategoriesError(getApiErrorMessage(e));
      });
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleFillDescriptionFromImage = async () => {
    setExtractError('');
    const file = fileInputRef.current?.files?.[0] ?? null;
    const url = imageUrl.trim();
    if (file && url) {
      setExtractError('Use either an uploaded image or an image URL — not both. Clear one of them.');
      return;
    }
    if (!file && !url) {
      setExtractError('Choose an image file or paste an image URL, then try again.');
      return;
    }
    setExtractingDamage(true);
    try {
      const { description, preview_storage_path } = await previewDamageDescription(file, url || null);
      setForm((prev) => ({ ...prev, description: description || prev.description }));
      setPreviewStoragePath(preview_storage_path ?? null);
    } catch (e: unknown) {
      setExtractError(getApiErrorMessage(e));
    } finally {
      setExtractingDamage(false);
    }
  };

  const handleRefineDescription = async () => {
    if (!form.description.trim()) return;
    setRefining(true);
    setRefineError('');
    try {
      const { refined } = await refineDescription(form.description);
      setRefinedText(refined);
      setRefineDialog(true);
    } catch (e: unknown) {
      setRefineError(getApiErrorMessage(e));
    } finally {
      setRefining(false);
    }
  };

  const handleAcceptRefined = () => {
    setForm((prev) => ({ ...prev, description: refinedText }));
    setRefineDialog(false);
    setRefinedText('');
  };

  const handleRejectRefined = () => {
    setRefineDialog(false);
    setRefinedText('');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const formData = new FormData();
      formData.append('incident_name', form.incident_name);
      formData.append('county', form.county);
      formData.append('applicant_name', form.applicant_name);
      formData.append('description', form.description);
      formData.append('estimated_cost', form.estimated_cost || '0');
      formData.append('submitted_by', form.submitted_by);
      if (form.fema_category_id) {
        formData.append('fema_category_id', form.fema_category_id);
      }
      if (previewStoragePath) {
        formData.append('preview_storage_path', previewStoragePath);
      }
      const claim = await createClaim(formData);
      navigate(`/claims/${claim.id}`);
    } catch (e: unknown) {
      setError(getApiErrorMessage(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box maxWidth={800} mx="auto">
      <Typography variant="h4" fontWeight={700} gutterBottom>
        Submit New Claim
      </Typography>
      <Typography variant="body1" color="text.secondary" mb={3}>
        Submit a new Public Assistance claim for FEMA reimbursement. Upload supporting documents after submission.
      </Typography>

      {categoriesError && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Could not load FEMA categories. You can still submit; AI may suggest a category. ({categoriesError})
        </Alert>
      )}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Card elevation={2}>
        <CardContent>
          <form onSubmit={handleSubmit}>
            <Grid container spacing={3}>
              <Grid size={12}>
                <TextField
                  fullWidth required
                  label="Incident Name"
                  name="incident_name"
                  value={form.incident_name}
                  onChange={handleChange}
                  placeholder="e.g., Hurricane Milton 2025"
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth required
                  label="County"
                  name="county"
                  value={form.county}
                  onChange={handleChange}
                  placeholder="e.g., Miami-Dade County"
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth required
                  label="Applicant Name"
                  name="applicant_name"
                  value={form.applicant_name}
                  onChange={handleChange}
                  placeholder="e.g., City of Homestead"
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  select
                  label="FEMA Category (optional - AI can suggest)"
                  name="fema_category_id"
                  value={form.fema_category_id}
                  onChange={handleChange}
                >
                  <MenuItem value="">Let AI Suggest</MenuItem>
                  {categories.map((cat) => (
                    <MenuItem key={cat.id} value={cat.id}>
                      Cat {cat.code} - {cat.name}
                    </MenuItem>
                  ))}
                </TextField>
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Estimated Cost ($)"
                  name="estimated_cost"
                  type="number"
                  value={form.estimated_cost}
                  onChange={handleChange}
                  placeholder="0.00"
                />
              </Grid>
              <Grid size={12}>
                <Typography variant="subtitle2" fontWeight={600} gutterBottom>
                  Describe damage from a photo (optional)
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                  Upload an image or provide a direct link to an image. The file is stored like claim documents, and AI will draft a damage description you can edit below.
                </Typography>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'flex-start' }} sx={{ mb: 1 }}>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    hidden
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      setSelectedImageName(f?.name ?? '');
                      setImageUrl('');
                      setPreviewStoragePath(null);
                      setExtractError('');
                    }}
                  />
                  <Button
                    variant="outlined"
                    startIcon={<ImageOutlinedIcon />}
                    onClick={() => fileInputRef.current?.click()}
                    disabled={extractingDamage}
                  >
                    {selectedImageName || 'Choose image file'}
                  </Button>
                  <TextField
                    fullWidth
                    label="Or image URL"
                    value={imageUrl}
                    placeholder="https://example.com/damage-photo.jpg"
                    onChange={(e) => {
                      setImageUrl(e.target.value);
                      if (fileInputRef.current) fileInputRef.current.value = '';
                      setSelectedImageName('');
                      setPreviewStoragePath(null);
                      setExtractError('');
                    }}
                    disabled={extractingDamage}
                  />
                  <Button
                    variant="contained"
                    onClick={handleFillDescriptionFromImage}
                    disabled={extractingDamage}
                    sx={{ flexShrink: 0 }}
                  >
                    {extractingDamage ? <CircularProgress size={22} color="inherit" /> : 'Fill description from image'}
                  </Button>
                </Stack>
                {extractError && (
                  <Alert severity="error" sx={{ mb: 2 }} onClose={() => setExtractError('')}>
                    {extractError}
                  </Alert>
                )}
              </Grid>
              <Grid size={12}>
                <TextField
                  fullWidth multiline rows={4}
                  label="Description of Damage / Work Needed"
                  name="description"
                  value={form.description}
                  onChange={handleChange}
                  placeholder="Describe the damage, location, and scope of work..."
                />
                <Box display="flex" alignItems="center" gap={1} mt={1}>
                  <Button
                    variant="outlined"
                    size="small"
                    startIcon={refining ? <CircularProgress size={16} color="inherit" /> : <AutoFixHighIcon />}
                    onClick={handleRefineDescription}
                    disabled={refining || !form.description.trim()}
                  >
                    {refining ? 'Refining...' : 'Refine with AI'}
                  </Button>
                  <Typography variant="caption" color="text.secondary">
                    AI will clean up grammar and formatting for FEMA compliance
                  </Typography>
                </Box>
                {refineError && (
                  <Alert severity="error" sx={{ mt: 1 }} onClose={() => setRefineError('')}>
                    {refineError}
                  </Alert>
                )}
              </Grid>
              <Grid size={12}>
                <TextField
                  fullWidth
                  label="Your Name / Email"
                  name="submitted_by"
                  value={form.submitted_by}
                  onChange={handleChange}
                  placeholder="county.official@county.gov"
                />
              </Grid>
              <Grid size={12}>
                <Button
                  type="submit"
                  variant="contained"
                  size="large"
                  endIcon={loading ? <CircularProgress size={20} color="inherit" /> : <SendIcon />}
                  disabled={loading}
                  sx={{ px: 4 }}
                >
                  {loading ? 'Submitting...' : 'Submit Claim'}
                </Button>
              </Grid>
            </Grid>
          </form>
        </CardContent>
      </Card>

      {/* Refine Description Dialog */}
      <Dialog open={refineDialog} onClose={handleRejectRefined} maxWidth="md" fullWidth>
        <DialogTitle>Review Refined Description</DialogTitle>
        <DialogContent>
          <Typography variant="subtitle2" color="text.secondary" gutterBottom>
            Your original
          </Typography>
          <Box sx={{ p: 2, mb: 2, borderRadius: 1, bgcolor: 'action.hover' }}>
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{form.description}</Typography>
          </Box>
          <Typography variant="subtitle2" color="primary" gutterBottom>
            AI-refined version
          </Typography>
          <Box sx={{ p: 2, borderRadius: 1, border: 2, borderColor: 'primary.main', bgcolor: 'action.hover' }}>
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{refinedText}</Typography>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleRejectRefined}>Keep Original</Button>
          <Button variant="contained" onClick={handleAcceptRefined}>
            Use Refined Version
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
