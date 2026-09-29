import { createRoot } from 'react-dom/client'
import { PublishedOutputs } from '../../src/PublishedOutputs'
import { PublishedResults } from '../../src/published-results'
import { PublicV2Client, type RunProjection } from '../../src/protocol/client'

let run: RunProjection
class FixtureClient extends PublicV2Client {
  override async runProjection() { return run }
  override runEvents() { return { close() {} } as WebSocket }
  override async workflowCommit() {
    return { project_id: run.project_id, workflow_commit_id: run.workflow_commit_id, source_draft_revision: 1, workflow: { schema_version: '2.1.0', workflow_id: 'fixture', nodes: [], edges: [], observation_selectors: [], selection_objectives: [] }, scientific_definitions: [], scientific_identity: {} }
  }
}
const results = new PublishedResults(new FixtureClient())
const root = createRoot(document.getElementById('root')!)
window.addEventListener('render-output-fixture', event => {
  run = (event as CustomEvent<RunProjection>).detail
  results.openRun(run)
  root.render(<PublishedOutputs run={run} results={results} />)
})
document.documentElement.dataset.fixtureReady = 'true'
