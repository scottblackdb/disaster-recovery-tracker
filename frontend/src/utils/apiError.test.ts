import { getApiErrorMessage } from './apiError';

describe('getApiErrorMessage', () => {
  it('returns FastAPI string detail', () => {
    expect(
      getApiErrorMessage({
        message: 'Request failed',
        response: { data: { detail: 'Claim not found' } },
      })
    ).toBe('Claim not found');
  });

  it('joins validation error messages', () => {
    expect(
      getApiErrorMessage({
        message: 'Bad Request',
        response: {
          data: {
            detail: [{ msg: 'field required' }, { msg: 'invalid value' }],
          },
        },
      })
    ).toBe('field required; invalid value');
  });

  it('falls back to Error.message', () => {
    expect(getApiErrorMessage(new Error('Network down'))).toBe('Network down');
  });

  it('handles unknown errors', () => {
    expect(getApiErrorMessage(null)).toBe('An unexpected error occurred');
  });
});
