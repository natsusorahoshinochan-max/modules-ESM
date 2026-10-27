import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './host.css'
import { lazy, Suspense } from 'react'

const App = lazy(() => import('./App'))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Suspense fallback={null}><App /></Suspense>
  </StrictMode>,
)
