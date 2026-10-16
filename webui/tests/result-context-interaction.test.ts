import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import test from 'node:test'
import { build } from 'esbuild'
import { chromium } from 'playwright'

test('discarding context edits restores the displayed choice and the applied result parameters', async () => {
  const browserCode = await build({
    stdin: { resolveDir: process.cwd(), loader: 'tsx', contents: `
      import { useState } from 'react'
      import { createRoot } from 'react-dom/client'
      import { ResultObservationEditor } from '../modules/protein_io/ui/ResultFilter'
      import { resultSelection } from '../modules/protein_io/ui/result-filter'
      const subject = { candidate_id: 'subject', data_type_id: 'protein.sequence', content_digest: 'sha256:subject' }
      const reference = { candidate_id: 'reference', data_type_id: 'protein.structure', content_digest: 'sha256:reference' }
      const source = { node_id: 'scores', output_port: 'scores', value_index: 0 }
      const profile = { kind: 'pairwise', subject_role: 'subject', reference_role: 'reference', pairing_mode: 'fixed_reference', normalization: 'reference-length' }
      const context = { kind: 'pairwise', subject: { role: 'subject', candidate: subject }, reference: { role: 'reference', candidate: reference }, pairing_mode: 'fixed_reference', normalization: 'reference-length', subject_region: ['A:1'], reference_region: ['B:4'] }
      const exact = { id: 'measurement', scoreInput: JSON.stringify(['scores', 'scores', 0]), scoreSource: source, metricId: 'measurement', methodId: 'method', partition: 'raw', context: profile, transformId: '', transformParameters: {}, exactContexts: [{ subject, context, residue_axis: null }] }
      const observations = [{ subject, metric: { contract_kind: 'metric', contract_id: 'measurement' }, method: { contract_kind: 'method', contract_id: 'method' }, source_partition: 'raw', context_profile: profile, context, residue_axis: null, value: 0.7, source }]
      function View() {
        const [applied, setApplied] = useState(exact)
        const [draft, setDraft] = useState(exact)
        return <><ResultObservationEditor value={draft} observations={observations} candidates={[subject]} catalog={{ contracts: [], availability: [] }} onChange={setDraft} />
          <button onClick={() => setDraft(applied)}>放弃修改</button>
          <button onClick={() => setApplied(draft)}>应用</button>
          <output aria-label="已应用参数">{JSON.stringify(resultSelection(applied))}</output></>
      }
      createRoot(document.getElementById('root')).render(<View />)
    ` },
    bundle: true, format: 'esm', platform: 'browser', jsx: 'automatic', write: false,
    nodePaths: [process.cwd() + '/node_modules'],
  })
  const server = createServer((request, response) => {
    if (request.url === '/view.js') {
      response.writeHead(200, { 'Content-Type': 'text/javascript' })
      response.end(browserCode.outputFiles![0].text)
    } else {
      response.writeHead(200, { 'Content-Type': 'text/html' })
      response.end('<div id="root"></div><script type="module" src="/view.js"></script>')
    }
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage()
    await page.goto(`http://127.0.0.1:${(server.address() as { port: number }).port}`)
    const mode = page.getByLabel('评价上下文选择方式')
    await mode.selectOption('unique')
    await page.getByRole('button', { name: '放弃修改', exact: true }).click()
    assert.equal(await mode.inputValue(), 'exact')
    assert.equal(await page.getByLabel('候选 subject 的评价上下文').count(), 1)
    await page.getByRole('button', { name: '应用', exact: true }).click()
    assert.equal(JSON.parse((await page.getByLabel('已应用参数').textContent())!).exact_contexts.length, 1)

    await mode.selectOption('unique')
    await page.getByRole('button', { name: '应用', exact: true }).click()
    await mode.selectOption('exact')
    await page.getByRole('button', { name: '放弃修改', exact: true }).click()
    assert.equal(await mode.inputValue(), 'unique')
    assert.equal(await page.getByLabel('候选 subject 的评价上下文').count(), 0)
    await page.getByRole('button', { name: '应用', exact: true }).click()
    assert.equal(Object.hasOwn(JSON.parse((await page.getByLabel('已应用参数').textContent())!), 'exact_contexts'), false)
  } finally {
    await browser.close()
    await new Promise<void>(resolve => server.close(() => resolve()))
  }
})
