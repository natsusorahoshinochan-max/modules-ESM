import type { PromptRigidTransform } from './protocol/client'

export type Vec3 = [number, number, number]
export type ViewportPoint = { x: number; y: number }
export type TransformMode = 'translate' | 'rotate'
export type WorldAxis = 'x' | 'y' | 'z'
export const worldAxes: Record<WorldAxis, Vec3> = { x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] }
export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
export const scale = (a: Vec3, n: number): Vec3 => [a[0] * n, a[1] * n, a[2] * n]
export const length = (a: Vec3) => Math.hypot(...a)
export const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
export const unit = (a: Vec3): Vec3 => scale(a, 1 / length(a))

/** The viewer quaternion maps model coordinates to the fixed camera frame. */
export function viewBasis(view: readonly number[]) {
  const q: Vec3 = [-view[4], -view[5], -view[6]]
  const rotate = (v: Vec3) => add(v, add(scale(cross(q, v), 2 * view[7]), scale(cross(q, cross(q, v)), 2)))
  return { right: rotate([1, 0, 0]), up: rotate([0, 1, 0]), normal: rotate([0, 0, 1]) }
}

export function rigidTransform(mode: TransformMode, origin: Vec3, direction: Vec3, amount: number, residueIds: string[]): PromptRigidTransform {
  const rotation: PromptRigidTransform['rotation_matrix'] = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
  if (mode === 'translate') return { rotation_matrix: rotation, origin, translation: scale(direction, amount), residue_ids: [...residueIds] }
  const [x, y, z] = unit(direction)
  const angle = amount * Math.PI / 180, c = Math.cos(angle), s = Math.sin(angle), t = 1 - c
  return { rotation_matrix: [[t*x*x+c, t*x*y-s*z, t*x*z+s*y], [t*x*y+s*z, t*y*y+c, t*y*z-s*x], [t*x*z-s*y, t*y*z+s*x, t*z*z+c]], origin, translation: [0, 0, 0], residue_ids: [...residueIds] }
}

export function planeDisplacement(delta: ViewportPoint, origin: Vec3, right: Vec3, up: Vec3, project: (point: Vec3) => ViewportPoint): Vec3 | undefined {
  const p = project(origin), r = project(add(origin, right)), u = project(add(origin, up))
  const rx = r.x - p.x, ry = r.y - p.y, ux = u.x - p.x, uy = u.y - p.y
  const det = rx * uy - ry * ux
  if (Math.abs(det) < 1e-8) return undefined
  return add(scale(right, (delta.x * uy - delta.y * ux) / det), scale(up, (rx * delta.y - ry * delta.x) / det))
}

export function axisDisplacement(delta: ViewportPoint, origin: Vec3, axis: Vec3, project: (point: Vec3) => ViewportPoint): number | undefined {
  const p = project(origin), a = project(add(origin, axis))
  const dx = a.x - p.x, dy = a.y - p.y, size = dx * dx + dy * dy
  if (size < 0.01) return undefined
  return (delta.x * dx + delta.y * dy) / size
}

export function rotationAmount(start: ViewportPoint, current: ViewportPoint, origin: Vec3, axis: Vec3, project: (point: Vec3) => ViewportPoint): number | undefined {
  const reference: Vec3 = Math.abs(axis[0]) < 0.8 ? [1, 0, 0] : [0, 1, 0]
  const right = unit(cross(axis, reference)), up = cross(axis, right), center = project(origin)
  const a = planeDisplacement({ x: start.x - center.x, y: start.y - center.y }, origin, right, up, project)
  const b = planeDisplacement({ x: current.x - center.x, y: current.y - center.y }, origin, right, up, project)
  if (!a || !b || length(a) < 1e-8 || length(b) < 1e-8) return undefined
  const dot = (v: Vec3, w: Vec3) => v[0]*w[0] + v[1]*w[1] + v[2]*w[2]
  return Math.atan2(dot(axis, cross(a, b)), dot(a, b)) * 180 / Math.PI
}

export function numericValue(text: string): number | undefined {
  if (!/^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text)) return undefined
  const number = Number(text)
  return Number.isFinite(number) ? number : undefined
}

export type ResidueMarker = { chain: string; resi: number; point: Vec3 }
export function residueMarkers(atoms: Array<{ chain: string; resi: number; atom: string; x: number; y: number; z: number }>): ResidueMarker[] {
  const residues = new Map<string, typeof atoms>()
  for (const atom of atoms) {
    const key = `${atom.chain}:${atom.resi}`
    const group = residues.get(key)
    if (group) group.push(atom); else residues.set(key, [atom])
  }
  return [...residues.values()].map(group => {
    const ca = group.find(atom => atom.atom === 'CA')
    const point: Vec3 = ca ? [ca.x, ca.y, ca.z] : scale(group.reduce<Vec3>((sum, atom) => add(sum, [atom.x, atom.y, atom.z]), [0, 0, 0]), 1 / group.length)
    return { chain: group[0].chain, resi: group[0].resi, point }
  })
}
