/**
 * Normalize FastAPI / axios-style errors for user-facing messages.
 * Kept axios-free so Jest can import it without ESM transform issues.
 */
export function getApiErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const ax = error as { response?: { data?: { detail?: unknown } }; message?: string };
    const detail = ax.response?.data?.detail;
    if (detail !== undefined) {
      if (typeof detail === 'string') return detail;
      if (Array.isArray(detail)) {
        return detail
          .map((item: { msg?: string }) =>
            typeof item === 'object' && item && 'msg' in item ? String(item.msg) : JSON.stringify(item)
          )
          .join('; ');
      }
    }
    if (ax.message) return ax.message;
  }
  if (error instanceof Error) return error.message;
  return 'An unexpected error occurred';
}
