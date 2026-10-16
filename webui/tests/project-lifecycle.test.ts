import assert from 'node:assert/strict'
import { createServer, type ServerResponse } from 'node:http'
import test from 'node:test'
import { build } from 'esbuild'
import { chromium } from 'playwright'

test('creating the first project waits for execution status before saving and preserves an actual run lock', { timeout: 30_000 }, async () => {
  const code = await build({
    stdin: { resolveDir: process.cwd(), loader: 'tsx', contents: `
      import { createRoot } from 'react-dom/client'
      import App from './src/App'
      createRoot(document.getElementById('root')).render(<App />)
    ` },
    bundle: true, format: 'esm', platform: 'browser', jsx: 'automatic', write: false,
    loader: { '.css': 'empty' }, nodePaths: [process.cwd() + '/node_modules'],
  })
  const project = { id: 'fresh', name: 'Fresh project', seed: false, project_kind: 'personal', latest_run_id: null, reference_results_project_id: null }
  let created = false
  let running = false
  let executionReply: ServerResponse | undefined
  let workspace: Record<string, unknown> = { project_id: 'fresh', workspace_revision: 0, draft: null, ui_state_revision: 0, ui_state: {}, return_workspace_revision: null }
  const saves: Record<string, unknown>[] = []
  const reply = (response: ServerResponse, body: unknown) => { response.writeHead(200, { 'Content-Type': 'application/json' }); response.end(JSON.stringify(body)) }
  const server = createServer(async (request, response) => {
    const path = request.url!
    if (path === '/app.js') { response.writeHead(200, { 'Content-Type': 'text/javascript' }); response.end(code.outputFiles![0].text); return }
    if (!path.startsWith('/api/')) { response.writeHead(200, { 'Content-Type': 'text/html' }); response.end('<div id="root" style="height:100vh"></div><script type="module" src="/app.js"></script>'); return }
    if (path.endsWith('/catalog')) return reply(response, { contracts: [], availability: [] })
    if (path.endsWith('/authoring-capabilities')) return reply(response, { node_roles: [] })
    if (path.endsWith('/module-ui')) return reply(response, { extensions: [], readers: [], authoring_actions: [] })
    if (path === '/api/v2/projects') {
      if (request.method === 'POST') { created = true; return reply(response, project) }
      return reply(response, { projects: created ? [project] : [] })
    }
    if (path.endsWith('/execution')) {
      if (running) return reply(response, { project_id: 'fresh', active_run_ids: [], reserved: true })
      executionReply = response
      return
    }
    if (path.endsWith('/runs')) return reply(response, { runs: [] })
    if (path.endsWith('/inputs')) return reply(response, { inputs: [] })
    if (path.endsWith('/workspace')) {
      if (request.method === 'PUT') {
        let body = ''
        for await (const chunk of request) body += chunk
        const saved = JSON.parse(body)
        saves.push(saved)
        workspace = { ...workspace, workspace_revision: 1, ui_state_revision: 1, ui_state: saved.ui_state, draft: { project_id: 'fresh', draft_revision: 1, workflow: saved.workflow } }
      }
      return reply(response, workspace)
    }
    response.writeHead(404); response.end(path)
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage()
    await page.goto(`http://127.0.0.1:${(server.address() as { port: number }).port}`)
    await page.getByRole('button', { name: '创建项目', exact: true }).click()
    await page.getByText('正在读取项目执行状态…', { exact: true }).waitFor()
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
    assert.equal(await page.getByRole('alert').count(), 0)
    assert.equal(await page.getByRole('button', { name: '保存项目', exact: true }).isDisabled(), true)
    assert.equal(saves.length, 0)
    reply(executionReply!, { project_id: 'fresh', active_run_ids: [], reserved: false })
    await page.getByRole('button', { name: '保存项目', exact: true }).click()
    await page.waitForFunction(() => document.querySelector('[aria-label="流程保存状态"]')?.textContent === '已保存')
    assert.equal(saves.length, 1)
    assert.deepEqual(saves[0].workflow, { schema_version: '2.1.0', workflow_id: 'fresh', nodes: [], edges: [] })

    running = true
    await page.reload()
    await page.getByRole('button', { name: '运行中', exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: '保存项目', exact: true }).isDisabled(), true)
    assert.equal(saves.length, 1)
  } finally {
    executionReply?.end()
    await browser.close()
    await new Promise<void>(resolve => server.close(() => resolve()))
  }
})
