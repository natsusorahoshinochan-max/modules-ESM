export const runtime = { react: 19 }
export function register({ React }) {
  return { viewers: [
    { id: 'z.detail', name: 'Detailed view', formats: ['other'], component: ({ package: pkg }) => React.createElement('p', { 'data-testid': 'viewer' }, `Detailed ${pkg.id}`) },
    { id: 'a.basic', name: 'Basic view', formats: ['other'], component: ({ package: pkg }) => React.createElement('p', { 'data-testid': 'viewer' }, `Basic ${pkg.id}`) },
  ] }
}
