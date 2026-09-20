import { createRoot } from 'react-dom/client'
import { PublishedOutputs } from '../../src/PublishedOutputs'
import type { RunProjection } from '../../src/protocol/client'

const root = createRoot(document.getElementById('root')!)
window.addEventListener('render-output-fixture', (event) => root.render(<PublishedOutputs run={(event as CustomEvent<RunProjection>).detail} />))
document.documentElement.dataset.fixtureReady = 'true'
