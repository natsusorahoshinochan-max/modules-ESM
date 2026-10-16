import { expect, test, type Locator, type Page } from '@playwright/test'
import type { ProjectWorkspace } from '../../src/project-workspace'
import type { ProjectMetadata } from '../../src/protocol/client'

function stageButton(page: Page, order: number) {
  return page.getByRole('navigation', { name: '流程阶段', exact: true }).getByRole('button', { name: new RegExp(`^阶段 ${order} `) })
}

function stageCard(page: Page, label: string) {
  return page.locator('.react-flow__node').filter({ has: page.getByRole('button', { name: `进入组 ${label}`, exact: true }) })
}

async function zoom(page: Page) {
  return page.locator('.react-flow__viewport').evaluate(element => new DOMMatrixReadOnly(getComputedStyle(element).transform).a)
}

async function expectInsideCanvas(page: Page, target: Locator) {
  await expect.poll(async () => {
    const [button, canvas] = await Promise.all([target.boundingBox(), page.locator('.flow-canvas > .react-flow').boundingBox()])
    if (!button || !canvas) return Infinity
    return Math.max(0, canvas.x - button.x, canvas.y - button.y, button.x + button.width - canvas.x - canvas.width, button.y + button.height - canvas.y - canvas.height)
  }, { message: 'The stage action must be reachable inside the canvas without shrinking its text' }).toBeLessThanOrEqual(1)
}

async function expectPortsInsideCanvas(page: Page, card: Locator) {
  await expect(card.locator('.workflow-port[open]')).toHaveCount(0)
  const handles = card.locator('.react-flow__handle')
  expect(await handles.count()).toBeGreaterThan(0)
  await expect.poll(async () => {
    const canvas = await page.locator('.flow-canvas > .react-flow').boundingBox()
    if (!canvas) return ['canvas missing']
    return handles.evaluateAll((elements, visible) => elements.flatMap(element => {
      const bounds = element.getBoundingClientRect()
      const overflow = Math.max(0, visible.x - bounds.x, visible.y - bounds.y, bounds.right - visible.x - visible.width, bounds.bottom - visible.y - visible.height)
      const hit = document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
      if (hit !== element && !element.contains(hit)) return [`${element.getAttribute('aria-label')}: covered by ${hit?.className}`]
      return bounds.width === 0 || bounds.height === 0 || overflow > 1 ? [`${element.getAttribute('aria-label')}: overflow ${overflow}px`] : []
    }), canvas)
  }, { message: 'Every closed stage port must remain visible within the canvas, allowing one pixel of rounding' }).toEqual([])
}

async function defaultWorkspace(page: Page) {
  const listed = await (await page.request.get('/api/v2/projects')).json() as { projects: ProjectMetadata[] }
  const project = listed.projects.find(item => item.project_kind === 'default_example')!
  expect(project).toBeDefined()
  const response = await page.request.get(`/api/v2/projects/${project.id}/workspace`)
  expect(response.ok()).toBe(true)
  return { project, workspace: await response.json() as ProjectWorkspace }
}

for (const width of [1611, 1288, 1024]) {
  test(`the default example keeps five readable horizontal stages and fourteen real crossing edges at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 989 })
    await page.goto('/')
    await expect(page.getByRole('heading', { name: '3GB1 Local Redesign Example', exact: true })).toBeVisible()
    const { workspace } = await defaultWorkspace(page)
    expect(workspace.draft!.workflow.nodes).toHaveLength(36)
    expect(workspace.draft!.workflow.edges).toHaveLength(61)
    await expect(page.getByRole('button', { name: /^进入组 / })).toHaveCount(5)
    await expect(page.locator('.react-flow__node')).toHaveCount(6)
    await expect(page.getByTestId('rf__node-export-final')).toBeAttached()
    await expect(page.locator('.react-flow__edge')).toHaveCount(14)
    await expect.poll(() => zoom(page)).toBeCloseTo(1, 5)
    const cards = page.locator('.react-flow__node').filter({ has: page.getByRole('button', { name: /^进入组 / }) })
    const positions = await cards.evaluateAll(elements => elements.map(element => {
      const bounds = element.getBoundingClientRect()
      return { x: bounds.x, y: bounds.y, width: bounds.width }
    }).sort((left, right) => left.x - right.x))
    expect(Math.max(...positions.map(position => position.y)) - Math.min(...positions.map(position => position.y))).toBeLessThanOrEqual(1)
    for (let index = 1; index < positions.length; index += 1) expect(positions[index].x).toBeGreaterThanOrEqual(positions[index - 1].x + positions[index - 1].width)
    for (let order = 1; order <= 5; order += 1) {
      const navigation = stageButton(page, order)
      const label = (await navigation.getAttribute('aria-label'))!.replace(/^阶段\s+\d+\s+/, '').trim()
      await navigation.click()
      await expect.poll(() => zoom(page)).toBeCloseTo(1, 5)
      const card = stageCard(page, label)
      const enter = card.getByRole('button', { name: `进入组 ${label}`, exact: true })
      await expectInsideCanvas(page, enter)
      await expectPortsInsideCanvas(page, card)
      await expect(page.locator('.react-flow__edge')).toHaveCount(14)
      const parameter = [undefined, ['生成数量', '7'], ['骨架保留数量', '2'], ['每个骨架设计数量', '3'], ['最终保留数量', '3']][order - 1]
      if (parameter) {
        const input = stageCard(page, label).getByLabel(parameter[0], { exact: true })
        await expect(input).toHaveValue(parameter[1])
        await expectInsideCanvas(page, input)
      }
    }
    await page.screenshot({ path: info.outputPath(`default-stages-${width}x989.png`), fullPage: true })
    const after = await defaultWorkspace(page)
    expect(after.workspace.draft).toEqual(workspace.draft)
  })
}

test('teaching stage edits and undo preserve groups locally without copying or saving', async ({ page }) => {
  await page.goto('/')
  const original = await defaultWorkspace(page)
  const writes: string[] = []
  page.on('request', request => {
    if ((request.method() === 'POST' && request.url().endsWith(':copy')) || (request.method() === 'PUT' && request.url().endsWith('/workspace'))) writes.push(request.url())
  })
  await stageButton(page, 2).click()
  const count = page.getByLabel('生成数量', { exact: true })
  await count.fill('8')
  await count.blur()
  await expect(count).toHaveValue('8')
  await page.locator('.flow-canvas').focus()
  await page.keyboard.press('ControlOrMeta+z')
  await expect(count).toHaveValue('7')
  await expect(stageButton(page, 2)).toBeVisible()
  expect(writes).toEqual([])
  expect((await defaultWorkspace(page)).workspace).toEqual(original.workspace)
})

test('stage Prompt and ranking editors open the referenced internal node and return keyboard focus to their stage action', async ({ page }) => {
  await page.setViewportSize({ width: 1288, height: 989 })
  await page.goto('/')
  await stageButton(page, 1).click()
  const promptAction = page.getByRole('button', { name: '编辑 ProteinPrompt', exact: true })
  const openingPrompt = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open') && response.request().postDataJSON().node_id === 'prompt-composition-webui-3gb1.source.author')
  await promptAction.click()
  expect((await openingPrompt).ok()).toBe(true)
  await expect(page.getByRole('heading', { name: 'ProteinPrompt 编辑', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '返回 Workflow', exact: true }).click()
  await expect(promptAction).toBeFocused()
  await expect(page.getByRole('button', { name: /^进入组 / })).toHaveCount(5)
  await expect.poll(() => zoom(page)).toBeCloseTo(1, 5)
  await stageButton(page, 3).click()
  const rankingAction = page.getByRole('button', { name: '回折筛选规则', exact: true })
  await rankingAction.click()
  const ranking = page.getByRole('dialog', { name: '编辑流程筛选', exact: true })
  await expect(ranking).toBeVisible()
  await expect(ranking.getByLabel('Candidate Collection 来源')).toHaveValue(JSON.stringify(['fold-stage-one', 'structure_candidates']))
  await expect(ranking.getByLabel('Score Collection 来源').first()).toHaveValue(JSON.stringify(['scores-stage-one', 'scores']))
  await page.keyboard.press('Escape')
  await expect(ranking).not.toBeVisible()
  await expect(rankingAction).toBeFocused()
  await expect(page.locator('.react-flow__edge')).toHaveCount(14)
})
