import { expect, test } from '@playwright/test'
import { axisDisplacement, numericValue, planeDisplacement, residueMarkers, rigidTransform, rotationAmount, viewBasis, type Vec3 } from '../src/viewport-transform'

const project = ([x, y]: Vec3) => ({ x: 200 + x * 20, y: 180 - y * 20 })

test('view-plane translation follows screen direction with exact world units', () => {
  const basis = viewBasis([0, 0, 0, 0, 0, 0, 0, 1])
  expect(planeDisplacement({ x: 40, y: -60 }, [0, 0, 0], basis.right, basis.up, project)).toEqual([2, 3, 0])
  const transform = rigidTransform('translate', [5, 6, 7], [1, 0, 0], -2.5, ['residue-17'])
  expect(transform.translation).toEqual([-2.5, -0, -0])
  expect(transform.origin).toEqual([5, 6, 7])
  expect(transform.residue_ids).toEqual(['residue-17'])
})

test('arbitrary rotation axis preserves lengths and leaves the pivot fixed', () => {
  const transform = rigidTransform('rotate', [5, 6, 7], [1, 1, 1], 73, ['r1', 'r8'])
  const matrix = transform.rotation_matrix
  const dot = (a: number[], b: number[]) => a.reduce((sum, value, i) => sum + value * b[i], 0)
  for (let row = 0; row < 3; row++) {
    expect(dot(matrix[row], matrix[row])).toBeCloseTo(1, 12)
    expect(dot(matrix[row], matrix[(row + 1) % 3])).toBeCloseTo(0, 12)
  }
  expect(transform.translation).toEqual([0, 0, 0])
  expect(transform.origin).toEqual([5, 6, 7])
})

test('world-axis mouse projection refuses an axis parallel to the view', () => {
  expect(axisDisplacement({ x: 30, y: 50 }, [0, 0, 0], [0, 0, 1], project)).toBeUndefined()
  expect(axisDisplacement({ x: -50, y: 80 }, [0, 0, 0], [1, 0, 0], project)).toBe(-2.5)
  expect(rotationAmount({ x: 220, y: 180 }, { x: 200, y: 160 }, [0, 0, 0], [0, 0, 1], project)).toBeCloseTo(90)
})

test('numeric entry distinguishes partial input from a confirmed zero', () => {
  for (const text of ['', '-', '.', '-.', '1.2.3', 'Infinity']) expect(numericValue(text)).toBeUndefined()
  expect(numericValue('0')).toBe(0)
  expect(numericValue('-.5')).toBe(-0.5)
  expect(numericValue('12.')).toBe(12)
})

test('through-box marker is CA or the all-atom centroid, independently for each residue', () => {
  expect(residueMarkers([
    { chain: 'A', resi: 1, atom: 'N', x: 1, y: 2, z: 3 },
    { chain: 'A', resi: 1, atom: 'CA', x: 9, y: 8, z: 7 },
    { chain: 'A', resi: 2, atom: 'N', x: 0, y: 2, z: 4 },
    { chain: 'A', resi: 2, atom: 'C', x: 4, y: 6, z: 8 },
  ])).toEqual([{ chain: 'A', resi: 1, point: [9, 8, 7] }, { chain: 'A', resi: 2, point: [2, 4, 6] }])
})
