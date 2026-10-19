export const runtime = { react: 19 }
export function register() {
  return { viewers: [{ id: 'z.broken', name: 'Unavailable view', formats: ['other'], component() { throw new Error('Viewer unavailable') } }] }
}
