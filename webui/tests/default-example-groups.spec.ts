import { expect, test, type Locator, type Page } from '@playwright/test'
import type { CanvasState } from '../src/canvas-groups'
import type { ProjectWorkspace } from '../src/project-workspace'
import type { ProjectMetadata } from '../src/protocol/client'

const expectedSizes = [4, 7, 11, 2, 11]

function stageButton(page: Page, order: number) {
  return page.getByRole('navigation', { name: '流程阶段', exact: true }).getByRole('button', { name: new RegExp(`^阶段 ${order} `) })
}

function stageCard(page: Page, label: string) {
  return page.locator('.react-flow__node').filter({ has: page.getByRole('button', { name: `进入组 ${label}`, exact: true }) })
}

async function zoom(page: Page) {
  return page.locator('.react-flow__viewport').evaluate(element => new DOMMatrixReadOnly(getComputedStyle(element).transform).a)
}

async function viewport(page: Page) {
  return page.locator('.react-flow__viewport').evaluate(element => {
    const transform = new DOMMatrixReadOnly(getComputedStyle(element).transform)
    return { x: transform.e, y: transform.f, zoom: transform.a }
  })
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

function canvasOf(workspace: ProjectWorkspace) {
  return workspace.ui_state.canvas as CanvasState
}

async function openProject(page: Page, name: string) {
  const errors: string[] = []
  const recordError = (error: Error) => errors.push(error.message)
  page.on('pageerror', recordError)
  try {
    await page.getByRole('button', { name: '项目', exact: true }).click()
    const manager = page.getByRole('dialog', { name: '项目与版本', exact: true })
    await manager.getByRole('button').filter({ has: page.getByText(name, { exact: true }) }).click()
    await manager.getByRole('button', { name: '打开项目', exact: true }).click()
    expect(errors, 'Switching grouped projects must preserve a valid canvas').toEqual([])
    await expect(manager).not.toBeVisible()
    await expect(page.locator('.project-identity strong')).toHaveText(name)
    expect(errors).toEqual([])
  } finally {
    page.off('pageerror', recordError)
  }
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

test('editing a real stage parameter copies all presentation state, persists it, and supports undo and group navigation', async ({ page }) => {
  await page.setViewportSize({ width: 1288, height: 989 })
  await page.goto('/')
  await expect(stageButton(page, 2)).toBeVisible()
  const original = await defaultWorkspace(page)
  await stageButton(page, 2).click()
  const count = page.getByLabel('生成数量', { exact: true })
  await expect(count).toHaveValue('7')
  await count.fill('8')
  const saving = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow?.nodes.some((node: { node_id: string; node_parameters: { num_samples?: number } }) => node.node_id === 'generate-paired' && node.node_parameters.num_samples === 8))
  await count.blur()
  const response = await saving
  expect(response.ok()).toBe(true)
  const saved = await response.json() as ProjectWorkspace
  expect(saved.project_id).not.toBe(original.project.id)
  expect(saved.draft!.workflow.nodes).toHaveLength(36)
  expect(saved.draft!.workflow.edges).toEqual(original.workspace.draft!.workflow.edges)
  const canvas = canvasOf(saved)
  const groups = [...canvas.groups!].sort((left, right) => left.stage!.order - right.stage!.order)
  expect(groups.map(group => group.nodeIds.length)).toEqual(expectedSizes)
  expect(new Set(groups.flatMap(group => group.nodeIds)).size).toBe(35)
  expect(groups.every(group => group.parentId === null)).toBe(true)
  expect(groups.flatMap(group => group.nodeIds)).not.toContain('export-final')
  expect(groups.flatMap(group => group.stage!.controls).filter(control => control.kind === 'parameter').map(control => `${control.nodeId}.${control.key}`)).toEqual(expect.arrayContaining(['generate-paired.num_samples', 'take-top-four.k', 'take-top-two.k', 'design-children.num_sequences', 'take-top-three.k']))
  await expect(page.getByText('personal', { exact: true })).toBeVisible()
  await page.locator('.flow-canvas').focus()
  const undoing = page.waitForResponse(candidate => candidate.request().method() === 'PUT' && candidate.url() === response.url() && candidate.request().postDataJSON().workflow?.nodes.some((node: { node_id: string; node_parameters: { num_samples?: number } }) => node.node_id === 'generate-paired' && node.node_parameters.num_samples === 7))
  await page.keyboard.press('Control+z')
  const undone = await (await undoing).json() as ProjectWorkspace
  await expect(count).toHaveValue('7')
  expect(canvasOf(undone).groups).toEqual(canvas.groups)
  expect((await defaultWorkspace(page)).workspace.draft).toEqual(original.workspace.draft)
  const name = `Grouped example ${crypto.randomUUID()}`
  expect((await page.request.patch(`/api/v2/projects/${saved.project_id}`, { data: { name } })).ok()).toBe(true)
  await page.reload()
  await openProject(page, name)
  await stageButton(page, 2).click()
  await expect(count).toHaveValue('7')
  const group = groups[1]
  const card = stageCard(page, group.label)
  await card.getByRole('button', { name: `进入组 ${group.label}`, exact: true }).click()
  await expect(page.getByRole('navigation', { name: '节点组路径', exact: true })).toContainText(group.label)
  await expect(page.getByTestId('rf__node-generate-paired')).toBeVisible()
  await expect(page.getByTestId('rf__node-export-final')).toHaveCount(0)
  await page.getByRole('button', { name: '返回上层 · Tab', exact: true }).click()
  await expect(card).toBeVisible()
  await expect.poll(() => zoom(page)).toBeCloseTo(1, 5)
  await expect(page.locator('.react-flow__edge')).toHaveCount(14)
  await page.locator('.react-flow__controls-zoomout').click()
  await expect.poll(() => zoom(page)).toBeLessThan(1)
  const userZoom = await zoom(page)
  await stageButton(page, 5).click()
  await expectInsideCanvas(page, stageCard(page, groups[4].label).getByRole('button', { name: `进入组 ${groups[4].label}`, exact: true }))
  await expect.poll(() => zoom(page)).toBeCloseTo(userZoom, 5)
  const focusedView = await viewport(page)
  await openProject(page, original.project.name)
  await openProject(page, name)
  await expect.poll(() => viewport(page)).toEqual(focusedView)
  await page.getByRole('button', { name: '100% 实际大小', exact: true }).click()
  await expect.poll(() => zoom(page)).toBeCloseTo(1, 5)
  await openProject(page, original.project.name)
  await openProject(page, name)
  await expect.poll(() => zoom(page)).toBeCloseTo(1, 5)
  const reopened = await (await page.request.get(response.url())).json() as ProjectWorkspace
  expect(canvasOf(reopened).groups).toEqual(canvas.groups)
  expect(reopened.draft).toEqual(undone.draft)
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
