import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './host.css'
import { lazy, Suspense } from 'react'

// Throwaway canvas study; available only in the development server.
const App = import.meta.env.DEV && new URLSearchParams(location.search).get('prototype') === 'canvas'
  ? lazy(() => import('./canvas-prototype/CanvasPrototype'))
  : lazy(() => import('./App'))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Suspense fallback={null}><App /></Suspense>
  </StrictMode>,
)
