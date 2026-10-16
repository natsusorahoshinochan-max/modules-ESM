import { test, expect } from '@playwright/test'

const appUrl = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5199'

test('an imported sequence opens through its module viewer after reopening the project', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Sequence reading' } })
  expect(created.status()).toBe(201)
  const { id } = await created.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const uploaded = await request.post(`${base}/inputs`, { data: { filename: 'sequence.fasta', content_base64: Buffer.from('>example\nACDEFG\n').toString('base64') } })
  expect(uploaded.status()).toBe(201)
  const { project_input_ref } = await uploaded.json()
  const committed = await request.post(`${base}/workflow:commit`, { data: { workflow: {
    schema_version: '2.1.0', workflow_id: id,
    nodes: [{ node_id: 'import', node_type_id: 'protein_io.import_sequence', binding_id: 'protein_io.import_sequence.direct', node_parameters: { project_input_ref }, binding_parameters: {} }], edges: [],
  } } })
  expect(committed.status()).toBe(200)
  const receipt = await request.post(`${base}/runs`, { data: { workflow_commit_id: (await committed.json()).workflow_commit_id, client_request_id: 'sequence-reading' } })
  expect(receipt.status()).toBe(202)
  const { run_id } = await receipt.json()
  const runUrl = `${base}/runs/${run_id}`
  await expect.poll(async () => (await (await request.get(runUrl)).json()).status).toBe('succeeded')
  const rawUrl = `${runUrl}/outputs/import/sequence/values/0`
  const original = await (await request.get(rawUrl)).text()
  for (let opened = 0; opened < 2; opened++) {
    await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
    await page.getByRole('button', { name: '查看结果', exact: true }).click()
    await page.getByText('全部已发布类型值与附件', { exact: true }).click()
    await page.getByRole('button', { name: 'import / sequence protein.sequence · 1 个值', exact: true }).click()
    await page.getByRole('button', { name: '加载此值', exact: true }).click()
    await expect(page.getByLabel('结果查看器')).toHaveValue('protein_io.sequence')
    await expect(page.getByLabel('已发布序列')).toContainText('ACDEFG')
    await expect(page.getByLabel('已发布序列')).toContainText('6 个序列位置')
  }
  expect(await (await request.get(rawUrl)).text()).toBe(original)
})

test('a published Prompt retains masks, absent tracks and residue paging in its module viewer after reopen', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Prompt reading' } })
  const { id } = await created.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const committed = await request.post(`${base}/workflow:commit`, { data: { workflow: {
    schema_version: '2.1.0', workflow_id: id,
    nodes: [{ node_id: 'prompt', node_type_id: 'prompt_authoring.author', binding_id: 'prompt_authoring.author.direct', node_parameters: { document: { chains: [{ chain_id: 'A', length: 101 }] } }, binding_parameters: {} }], edges: [],
  } } })
  expect(committed.status()).toBe(200)
  const receipt = await request.post(`${base}/runs`, { data: { workflow_commit_id: (await committed.json()).workflow_commit_id, client_request_id: 'prompt-reading' } })
  expect(receipt.status()).toBe(202)
  const { run_id } = await receipt.json()
  const runUrl = `${base}/runs/${run_id}`
  await expect.poll(async () => (await (await request.get(runUrl)).json()).status).toBe('succeeded')
  for (let opened = 0; opened < 2; opened++) {
    await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
    await page.getByRole('button', { name: '查看结果', exact: true }).click()
    await page.getByText('全部已发布类型值与附件', { exact: true }).click()
    await page.getByRole('button', { name: /prompt \/ protein_prompt/ }).click()
    await page.getByRole('button', { name: '加载此值', exact: true }).click()
    await expect(page.getByLabel('结果查看器')).toHaveValue('prompt_authoring.prompt')
    const prompt = page.getByLabel('已发布 Prompt')
    await expect(prompt.getByRole('row')).toHaveCount(101)
    await expect(prompt.getByRole('row').nth(1)).toContainText('Mask')
    await expect(prompt.getByRole('row').nth(1)).toContainText('未提供整条轨道')
    await prompt.getByRole('button', { name: '下一页' }).click()
    await expect(prompt.getByRole('row')).toHaveCount(2)
    await expect(prompt.getByRole('row').nth(1)).toContainText('A:101')
    await expect(prompt).toContainText('没有功能注释。')
  }
})

test('the module candidate panel preserves paging, export selection and comparison when reopening results', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Candidate panel' } })
  const { id } = await created.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const fasta = Array.from({ length: 51 }, (_, i) => `>sequence-${i + 1}\nACDEFG\n`).join('')
  const uploaded = await request.post(`${base}/inputs`, { data: { filename: 'sequences.fasta', content_base64: Buffer.from(fasta).toString('base64') } })
  const committed = await request.post(`${base}/workflow:commit`, { data: { workflow: {
    schema_version: '2.1.0', workflow_id: id,
    nodes: [{ node_id: 'import', node_type_id: 'protein_io.import_sequences', binding_id: 'protein_io.import_sequences.direct', node_parameters: { project_input_ref: (await uploaded.json()).project_input_ref }, binding_parameters: {} }], edges: [],
  } } })
  expect(committed.status()).toBe(200)
  const receipt = await request.post(`${base}/runs`, { data: { workflow_commit_id: (await committed.json()).workflow_commit_id, client_request_id: 'candidate-panel' } })
  const { run_id } = await receipt.json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${run_id}`)).json()).status).toBe('succeeded')
  await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
  await page.getByRole('button', { name: '查看结果', exact: true }).click()
  await expect(page.getByLabel('结果面板')).toHaveValue('protein_io.candidates')
  const list = page.getByLabel('候选列表', { exact: true })
  await expect(list.getByRole('checkbox')).toHaveCount(50)
  await list.getByRole('checkbox').first().check()
  await list.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(list.getByRole('checkbox')).toHaveCount(1)
  await expect(page.getByRole('button', { name: '查看已选 (1)', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '并排比较 (0)', exact: true }).click()
  await expect(page.getByLabel('比较位置', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '查看已选 (1)', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '返回 Workflow', exact: true }).click()
  await page.getByRole('button', { name: /Results/ }).click()
  await expect(list.getByRole('checkbox')).toHaveCount(1)
  await expect(page.getByRole('button', { name: '查看已选 (1)', exact: true })).toBeVisible()
})

test('the module panel shows persisted scores and alignment roles without changing either structure', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Aligned candidates' } })
  const { id } = await created.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  let serial = 0
  const pdb = [[0, 0, 0], [3, 1, 0], [6, 0, 1]].flatMap(([x, y, z], residue) => ['N', 'CA', 'C', 'O'].map((atom, offset) =>
    `ATOM  ${String(++serial).padStart(5)} ${atom.padStart(4)} GLY A${String(residue + 1).padStart(4)}    ${(x + offset * .2).toFixed(3).padStart(8)}${y.toFixed(3).padStart(8)}${z.toFixed(3).padStart(8)}  1.00 20.00          ${atom[0].padStart(2)}  `
  )).join('\n') + '\nEND\n'
  const uploaded = await request.post(`${base}/inputs`, { data: { filename: 'three.pdb', content_base64: Buffer.from(pdb).toString('base64') } })
  const { project_input_ref } = await uploaded.json()
  const referencePdb = pdb.split('\n').map(line => line.startsWith('ATOM') ? line.slice(0, 30) + (Number(line.slice(30, 38)) + 10).toFixed(3).padStart(8) + line.slice(38) : line).join('\n')
  const referenceUpload = await request.post(`${base}/inputs`, { data: { filename: 'reference.pdb', content_base64: Buffer.from(referencePdb).toString('base64') } })
  const referenceInput = (await referenceUpload.json()).project_input_ref
  const node = (node_id: string, type: string, binding = 'direct', node_parameters = {}) => ({ node_id, node_type_id: type, binding_id: `${type}.${binding}`, node_parameters, binding_parameters: {} })
  const edge = (source_node_id: string, source_port: string, target_node_id: string, target_port: string) => ({ source_node_id, source_port, target_node_id, target_port })
  const committed = await request.post(`${base}/workflow:commit`, { data: { workflow: {
    schema_version: '2.1.0', workflow_id: id,
    nodes: [node('subject', 'protein_io.import_structure', 'direct', { project_input_ref }), node('reference', 'protein_io.import_structure', 'direct', { project_input_ref: referenceInput }), node('subject_axis', 'structure_transform.resolve_candidate_residue_axes'), node('reference_axis', 'structure_transform.resolve_candidate_residue_axes'), node('relation', 'collection_ops.relate_to_single_reference'), node('align', 'structure_comparison.align_pairs', 'sequence_primary_affine'), node('rmsd', 'structure_comparison.rmsd_from_alignments', 'from_alignment_evidence')],
    edges: [edge('subject', 'structure_candidates', 'subject_axis', 'structure_candidates'), edge('reference', 'structure_candidates', 'reference_axis', 'structure_candidates'), edge('subject', 'structure_candidates', 'relation', 'subjects'), edge('reference', 'structure_candidates', 'relation', 'references'), edge('subject_axis', 'residue_axes', 'align', 'subject_residue_axes'), edge('reference_axis', 'residue_axes', 'align', 'reference_residue_axes'), edge('relation', 'relation', 'align', 'relation'), edge('align', 'alignments', 'rmsd', 'alignments'), edge('subject', 'structure_candidates', 'rmsd', 'subjects'), edge('reference', 'structure_candidates', 'rmsd', 'references'), edge('relation', 'relation', 'rmsd', 'relation')],
  } } })
  expect(committed.status(), await committed.text()).toBe(200)
  const receipt = await request.post(`${base}/runs`, { data: { workflow_commit_id: (await committed.json()).workflow_commit_id, client_request_id: 'alignment-viewing' } })
  const { run_id } = await receipt.json()
  const runUrl = `${base}/runs/${run_id}`
  await expect.poll(async () => (await (await request.get(runUrl)).json()).status).toBe('succeeded')
  const rawUrl = `${runUrl}/outputs/subject/structure/values/0`
  const original = await (await request.get(rawUrl)).text()
  for (let opened = 0; opened < 2; opened++) {
    await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
    await page.getByRole('button', { name: '查看结果', exact: true }).click()
    await expect(page.getByLabel('结果面板')).toHaveValue('protein_io.candidates')
    await page.getByRole('button', { name: '并排比较 (0)', exact: true }).click()
    await page.getByLabel('比较位置 1', { exact: true }).selectOption({ index: 1 })
    await page.getByLabel('比较位置 2', { exact: true }).selectOption({ index: 2 })
    await expect(page.locator('.result-observation')).toContainText('structure_comparison.rmsd · angstrom')
    await expect(page.locator('.alignment-comparison')).toContainText('coverage 1.000')
    await page.getByText('精确角色、变换与来源', { exact: true }).click()
    await expect(page.locator('.alignment-comparison pre')).toContainText('"row_vector_rotation"')
    await expect(page.locator('.alignment-comparison pre')).toContainText('"node_id": "align"')
  }
  expect(await (await request.get(rawUrl)).text()).toBe(original)
})
