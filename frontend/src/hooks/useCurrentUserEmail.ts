import { useEffect, useState } from 'react';
import { fetchCurrentUser } from '../services/api';

/**
 * Loads `/current-user` once on mount.
 *
 * @param initialValue - Shown until the request completes (e.g. `''` or `'Portal User'`).
 */
export function useCurrentUserEmail(initialValue = 'Portal User'): string {
  const [email, setEmail] = useState(initialValue);
  useEffect(() => {
    fetchCurrentUser()
      .then(({ email: e }) => setEmail(e))
      .catch(() => {});
  }, []);
  return email;
}
