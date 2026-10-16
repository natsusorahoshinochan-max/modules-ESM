import { test, expect } from '@playwright/test'
const appUrl = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5207'

test('select real discontinuous residue locations, cancel or apply, then manually save and reopen', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Regional comparison' } })
  expect(created.status()).toBe(201)
  const { id } = await created.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const workflow = { schema_version: '2.1.0', workflow_id: id, nodes: [{
    node_id: 'align', node_type_id: 'structure_comparison.align_pairs',
    binding_id: 'structure_comparison.align_pairs.sequence_primary_affine', node_parameters: {}, binding_parameters: {},
  }], edges: [] }
  expect((await request.put(`${base}/workspace`, { data: { workflow, ui_state: {} } })).status()).toBe(200)
  await page.goto(`${appUrl}/?project=${id}`)
  await page.getByRole('button', { name: '选择比较区域', exact: true }).click()
  const subject = page.getByRole('group', { name: '主体区域', exact: true })
  for (const [index, number, insertion] of [[0, '10', ''], [1, '12', 'A']] as const) {
    await subject.getByRole('button', { name: '添加残基', exact: true }).click()
    await subject.getByLabel(`链 ${index + 1}`, { exact: true }).fill('A')
    await subject.getByLabel(`作者编号 ${index + 1}`, { exact: true }).fill(number)
    await subject.getByLabel(`插入码 ${index + 1}`, { exact: true }).fill(insertion)
  }
  await page.getByRole('button', { name: '采用区域选择', exact: true }).click()
  // Accepting editor changes must not save the project.
  const beforeSave = await (await request.get(`${base}/workspace`)).json()
  expect(JSON.stringify(beforeSave)).not.toContain('subject_region')
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.getByLabel('布局保存状态')).not.toContainText('未保存')
  await page.reload()
  await page.getByRole('button', { name: '选择比较区域', exact: true }).click()
  await expect(subject.getByLabel('作者编号 1', { exact: true })).toHaveValue('10')
  await expect(subject.getByLabel('作者编号 2', { exact: true })).toHaveValue('12')
  await expect(subject.getByLabel('插入码 2', { exact: true })).toHaveValue('A')
  await subject.getByLabel('作者编号 1', { exact: true }).fill('999')
  await page.getByRole('button', { name: '取消区域编辑', exact: true }).click()
  await page.getByRole('button', { name: '选择比较区域', exact: true }).click()
  await expect(subject.getByLabel('作者编号 1', { exact: true })).toHaveValue('10')
})

test('regional statistics exposes the original metric and explicit missing-value rule', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Regional statistics' } })
  const { id } = await created.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const workflow = { schema_version: '2.1.0', workflow_id: id, nodes: [{
    node_id: 'statistics', node_type_id: 'structure_comparison.region_statistics',
    binding_id: 'structure_comparison.region_statistics.direct', node_parameters: {}, binding_parameters: {},
  }], edges: [] }
  expect((await request.put(`${base}/workspace`, { data: { workflow, ui_state: {} } })).status()).toBe(200)
  await page.goto(`${appUrl}/?project=${id}`)
  await page.getByRole('button', { name: '选择统计区域', exact: true }).click()
  await page.getByLabel('原始逐残基指标', { exact: true }).selectOption('structure.plddt.per_residue')
  await page.getByLabel('区域缺值处理', { exact: true }).selectOption('require_all')
  await page.getByRole('button', { name: '采用区域选择', exact: true }).click()
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.getByLabel('布局保存状态')).not.toContainText('未保存')
  await page.reload()
  await page.getByRole('button', { name: '选择统计区域', exact: true }).click()
  await expect(page.getByLabel('原始逐残基指标', { exact: true })).toHaveValue('structure.plddt.per_residue')
  await expect(page.getByLabel('区域缺值处理', { exact: true })).toHaveValue('require_all')
})

test('persisted regional alignment and statistics display their selected locations and original sources', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Published regions' } })
  expect(created.status()).toBe(201)
  const { id } = await created.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const pdb = 'ATOM      1  CA  ALA A  10       0.000   0.000   0.000  1.00 20.00           C  \nATOM      2  CA  ALA A  11       1.000   0.000   0.000  1.00 20.00           C  \nATOM      3  CA  ALA A  12       0.000   1.000   0.000  1.00 20.00           C  \nATOM      4  CA  ALA A  15       0.000   0.000   1.000  1.00 20.00           C  \nEND\n'
  const uploaded = await request.post(`${base}/inputs`, { data: { filename: 'region.pdb', content_base64: Buffer.from(pdb).toString('base64') } })
  expect(uploaded.status()).toBe(201)
  const { project_input_ref } = await uploaded.json()
  const region = ['10', '11', '12'].map(residue_number => ({ chain_id: 'A', residue_number, insertion_code: '' }))
  const node = (node_id: string, node_type_id: string, node_parameters = {}, binding_id = node_type_id + '.direct') => ({ node_id, node_type_id, node_parameters, binding_parameters: {}, binding_id })
  const edge = (source_node_id: string, source_port: string, target_node_id: string, target_port: string) => ({ source_node_id, source_port, target_node_id, target_port })
  const workflow = { schema_version: '2.1.0', workflow_id: id, nodes: [
    node('input', 'protein_io.import_structure', { project_input_ref }),
    node('axis', 'structure_transform.resolve_candidate_residue_axes'),
    node('measured', 'region_observations.source'),
    node('statistics', 'structure_comparison.region_statistics', { metric_id: 'structure.plddt.per_residue', region }),
    node('relation', 'collection_ops.relate_to_single_reference'),
    node('align', 'structure_comparison.align_pairs', { subject_region: region, reference_region: region }, 'structure_comparison.align_pairs.sequence_primary_affine'),
  ], edges: [
    edge('input', 'structure_candidates', 'axis', 'structure_candidates'),
    edge('input', 'structure_candidates', 'measured', 'structures'),
    edge('axis', 'residue_axes', 'measured', 'axes'), edge('measured', 'scores', 'statistics', 'scores'),
    edge('input', 'structure_candidates', 'relation', 'subjects'), edge('input', 'structure_candidates', 'relation', 'references'),
    edge('axis', 'residue_axes', 'align', 'subject_residue_axes'), edge('axis', 'residue_axes', 'align', 'reference_residue_axes'),
    edge('relation', 'relation', 'align', 'relation'),
  ] }
  const committed = await request.post(`${base}/workflow:commit`, { data: { workflow } })
  expect(committed.status()).toBe(200)
  const started = await request.post(`${base}/runs`, { data: { workflow_commit_id: (await committed.json()).workflow_commit_id, client_request_id: crypto.randomUUID() } })
  expect(started.status()).toBe(202)
  const { run_id } = await started.json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${run_id}`)).json()).status).toBe('succeeded')
  for (let reopen = 0; reopen < 2; reopen++) {
    await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
    await page.getByRole('button', { name: '查看结果', exact: true }).click()
    await page.getByText('全部已发布类型值与附件', { exact: true }).click()
    await page.getByRole('button', { name: /statistics \/ statistics structure_comparison.region_statistics/ }).click()
    await page.getByRole('button', { name: '加载此值', exact: true }).click()
    await expect(page.getByLabel('区域统计结果')).toContainText('均值：50；有效数量：2 / 所选数量：3')
    await expect(page.getByLabel('区域统计结果')).toContainText('region_observations.measured')
    await page.getByRole('button', { name: /align \/ alignments structure_comparison.alignment_evidence/ }).click()
    await page.getByRole('button', { name: '加载此值', exact: true }).click()
    await expect(page.getByLabel('结构区域比较结果')).toContainText('主体区域：A:10、A:11、A:12')
    await expect(page.getByLabel('结构区域比较结果')).toContainText('参考区域：A:10、A:11、A:12')
  }
})
