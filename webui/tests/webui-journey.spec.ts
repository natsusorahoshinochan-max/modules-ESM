import { expect, test } from '@playwright/test'
import { unzipSync } from 'fflate'

test('default 3GB1 workflow remains connected from authoring through export', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '3GB1 Local Redesign Example' })).toBeVisible()
  await expect(page.getByText(/35 MATERIALIZED NODES/)).toBeVisible()
  await expect(page.getByText('只读示例')).toBeVisible()
  await expect(page.getByText(/A37–A41.*7 → 4 → 4 → 2 → 6 → 6 → 3/)).toBeVisible()

  await page.getByRole('button', { name: /Results 3/ }).click()
  await expect(page.getByRole('heading', { name: /最终候选/ })).toBeVisible()
  await expect(page.getByText('per_subject_direct_ancestor', { exact: true })).toBeVisible()
  await expect(page.getByText('Mean-residue pLDDT').first()).toBeVisible()
  await expect(page.getByText('Template modelling score').first()).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: /导出所选/ }).click()
  const path = await (await download).path()
  const archive = unzipSync(await import('node:fs').then(({ readFileSync }) => readFileSync(path!)))
  expect(Object.keys(archive)).toEqual(expect.arrayContaining(['candidates.fasta', 'scores.csv', 'manifest.json']))
  expect(Object.keys(archive).filter((name) => name.endsWith('.pdb'))).toHaveLength(1)

  await page.getByRole('button', { name: '返回 Workflow' }).click()
  await page.getByLabel('编辑参数').first().click()
  const seed = page.getByLabel('有效种子').first()
  await seed.fill('1604')
  await seed.press('Tab')
  await expect(page.getByText('已自动保存')).toBeVisible()
  await expect(page.getByText('personal', { exact: true })).toBeVisible()
  await expect(page.getByText('来自修改前的流程')).toBeVisible()

  await page.getByRole('group', { name: 'Edge from generate-paired to take-top-four' }).click()
  await page.keyboard.press('Delete')
  await expect(page.getByText('画布连接已修改')).toBeVisible()
  await page.getByRole('button', { name: '撤销画布修改' }).click()
  await expect(page.getByText('已撤销画布修改')).toBeVisible()

  await page.getByRole('button', { name: /打开 Prompt Studio/ }).click()
  await expect(page.getByRole('heading', { name: '3GB1 局部环区重设计' })).toBeVisible()
  await expect(page.getByText('57 residues')).toBeVisible()
  await page.getByRole('button', { name: '状态图例' }).click()
  await expect(page.locator('.ps-state-legend').getByText('pending-delete', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '保存 ProteinPrompt' }).click()
  await expect(page.getByRole('heading', { name: '确认写回 Workflow' })).toBeVisible()
  await expect(page.getByText('Preview digest')).toBeVisible()
  await page.getByRole('button', { name: '确认并写回 Workflow' }).click()
  await expect(page.getByText('Prompt 已保存')).toBeVisible()

  await page.getByRole('button', { name: '运行完整流程' }).click()
  await expect(page.getByRole('heading', { name: '确认运行完整流程' })).toBeVisible()
  await expect(page.getByText('35 个 materialized Node Instances')).toBeVisible()
  await expect(page.getByText('7 → 4 → 4 → 2 → 6 → 6 → 3', { exact: true })).toBeVisible()
})

test('Prompt Studio edits the backend projection and shows every prompt track', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '打开 Prompt Studio' }).click()

  await expect(page.getByRole('navigation', { name: 'Prompt Studio 模式' })).toBeVisible()
  await expect(page.getByRole('button', { name: '条件' })).toHaveClass(/active/)
  await expect(page.getByRole('rowheader', { name: 'Residue axis chain / locator' })).toBeVisible()
  await expect(page.getByRole('rowheader', { name: 'Sequence amino acid' })).toBeVisible()
  await expect(page.getByRole('rowheader', { name: 'Coordinates named atoms' })).toBeVisible()
  await expect(page.getByRole('rowheader', { name: 'Secondary structure SS8' })).toBeVisible()
  await expect(page.getByRole('rowheader', { name: 'SASA Å²' })).toBeVisible()
  await expect(page.getByRole('rowheader', { name: 'Function annotations tuple interval' })).toBeVisible()
  expect((await page.locator('.ps-residue-column > button:first-child').allTextContents()).join(' ')).not.toMatch(/insert-[0-9a-f]|inserted\./)

  await page.getByRole('button', { name: /A30 Sequence/ }).click()
  await page.getByRole('button', { name: 'Preserve', exact: true }).click()
  await expect(page.getByRole('button', { name: /A30 Sequence .* current/ })).toBeVisible()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: 'Mask', exact: true }).click()
  await expect(page.getByRole('button', { name: 'A30 Sequence Mask cleared' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /即时预览 · Sequence · mask/ })).toBeVisible()
  await expect(page.getByRole('button', { name: '保存 ProteinPrompt' })).toBeDisabled()

  await page.getByRole('button', { name: '应用操作' }).click()
  await expect(page.getByRole('heading', { name: /即时预览/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '撤销' })).toBeEnabled()

  const a31 = page.getByRole('button', { name: /A31 Sequence/ })
  await a31.click()
  await a31.press('Q')
  await expect(page.getByRole('button', { name: 'A31 Sequence Q changed' })).toBeVisible()
  await a31.press('Enter')
  await expect(page.getByRole('heading', { name: /即时预览/ })).toHaveCount(0)

  const currentBeforeInsert = await page.locator('.ps-residue-column:not(.tombstone)').count()
  await page.getByRole('button', { name: 'Insert after focus' }).click()
  await expect(page.getByRole('button', { name: 'A31+1 Sequence Mask inserted' })).toBeVisible()
  const insertedColumn = page.locator('.ps-residue-column').filter({ has: page.locator('.state-inserted') }).first()
  await expect(insertedColumn).not.toHaveClass(/tombstone/)
  await expect(insertedColumn.locator('button').first()).toBeEnabled()
  await page.getByRole('button', { name: '应用操作' }).click()
  await expect(page.locator('.ps-residue-column:not(.tombstone)')).toHaveCount(currentBeforeInsert + 1)
  await page.getByRole('button', { name: '撤销' }).click()
  await expect(page.locator('.ps-residue-column:not(.tombstone)')).toHaveCount(currentBeforeInsert)
  await page.getByRole('button', { name: 'Insert after focus' }).click()
  await page.getByRole('button', { name: '取消', exact: true }).click()

  await page.getByRole('button', { name: '保存 ProteinPrompt' }).click()
  await expect(page.getByRole('dialog')).toContainText('Preview digest')
  await expect(page.getByRole('dialog')).toContainText('changed')
})

test('dragging an edge endpoint to empty canvas disconnects the edge', async ({ page }) => {
  await page.goto('/')
  const edge = page.getByRole('group', { name: 'Edge from generate-paired to take-top-four' })
  await edge.click()

  const endpoint = edge.locator('.react-flow__edgeupdater-target')
  await expect(endpoint).toBeVisible()
  const endpointBox = await endpoint.boundingBox()
  const paneBox = await page.locator('.react-flow__pane').boundingBox()
  expect(endpointBox).not.toBeNull()
  expect(paneBox).not.toBeNull()

  await page.mouse.move(endpointBox!.x + endpointBox!.width / 2, endpointBox!.y + endpointBox!.height / 2)
  await page.mouse.down()
  await page.mouse.move(paneBox!.x + 80, paneBox!.y + 180, { steps: 8 })
  await page.mouse.up()

  await expect(edge).toHaveCount(0)
  await expect(page.getByText('画布连接已修改')).toBeVisible()
})

test('a started workflow reports its live status and current stage', async ({ page }) => {
  await page.routeWebSocket(/\/runs\/run-ui-progress\/events/, (webSocket) => {
    setTimeout(() => {
      webSocket.send(JSON.stringify({
        schema_namespace: 'protein-workbench-public/v2',
        project_id: 'project-ui-progress',
        run_id: 'run-ui-progress',
        sequence: 2,
        cursor: 'cursor-node-started',
        emitted_at: '2026-09-01T00:00:00Z',
        event: {
          type: 'node_attempt_started',
          node_id: 'generate-paired',
          node_attempt_id: 'attempt-generate-paired',
        },
      }))
    }, 100)
    setTimeout(() => {
      webSocket.send(JSON.stringify({
        schema_namespace: 'protein-workbench-public/v2',
        project_id: 'project-ui-progress',
        run_id: 'run-ui-progress',
        sequence: 3,
        cursor: 'cursor-node-failed',
        emitted_at: '2026-09-01T00:00:01Z',
        event: {
          type: 'node_disposition',
          disposition: {
            node_id: 'generate-paired',
            outcome: 'failed',
            blocked_by: [],
            terminal_sequence: 3,
          },
        },
      }))
      webSocket.send(JSON.stringify({
        schema_namespace: 'protein-workbench-public/v2',
        project_id: 'project-ui-progress',
        run_id: 'run-ui-progress',
        sequence: 4,
        cursor: 'cursor-run-failed',
        emitted_at: '2026-09-01T00:00:02Z',
        event: { type: 'run_terminal', status: 'failed' },
      }))
    }, 1000)
  })
  await page.route('**/api/v2/projects/*/runs', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({ json: {
        project_id: 'project-ui-progress',
        run_id: 'run-ui-progress',
        workflow_commit_id: 'commit-ui-progress',
        admitted_sequence: 1,
        event_cursor: 'cursor-admitted',
      } })
      return
    }
    await route.continue()
  })
  await page.route('**/api/v2/projects/*/runs/run-ui-progress', async (route) => {
    await route.fulfill({
      json: {
        project_id: 'project-ui-progress',
        run_id: 'run-ui-progress',
        workflow_commit_id: 'commit-ui-progress',
        status: 'failed',
        ledger_cursor: '0',
        node_dispositions: [],
        outputs: [],
        artifact_index: [],
      },
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '运行完整流程' }).click()
  await page.getByRole('button', { name: '开始运行' }).click()

  await expect(page.getByRole('status')).toContainText('正在运行')
  await expect(page.getByRole('status')).toContainText('当前阶段')
  await expect(page.getByRole('status')).toContainText('generate-paired')
  await expect(page.getByRole('status')).toContainText('运行失败')
  await expect(page.getByRole('status')).toContainText('1 / 35 Nodes')
})
