import React from 'react';
import { render, screen } from '@testing-library/react';

jest.mock('axios', () => ({
  __esModule: true,
  default: {
    create: jest.fn(() => ({
      get: jest.fn(() => Promise.resolve({ data: {} })),
      post: jest.fn(() => Promise.resolve({ data: {} })),
      patch: jest.fn(() => Promise.resolve({ data: {} })),
    })),
  },
}));

jest.mock('./pages/Dashboard', () => ({
  __esModule: true,
  default: function MockDashboard() {
    return <div>Recovery Dashboard</div>;
  },
}));

import App from './App';

test('renders app shell with dashboard and navigation chrome', () => {
  render(<App />);
  expect(screen.getByText(/AI-Assisted Public Assistance Grant Portal/i)).toBeInTheDocument();
  expect(screen.getByText('Recovery Dashboard')).toBeInTheDocument();
});
