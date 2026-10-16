import { expect, test } from '@playwright/test'
import { copyMatrix, emptyMatrixSelection, matrixTracks, parseMatrixValue, pasteMatrix, selectMatrixCell, type MatrixCell, type MatrixSelection } from '../../src/residue-matrix'

const handles = ['first', 'second', 'third', 'fourth']
const cell = (handle: string): MatrixCell => ({ handle, track: 'sequence' })
const selected = (cells: MatrixCell[]): MatrixSelection => ({ active: cells[0], anchor: cells[0], cells })

test('Shift keeps its original anchor and Ctrl toggles only the requested cell', () => {
  const one = selectMatrixCell(emptyMatrixSelection, cell('first'), handles, matrixTracks, { shift: false, toggle: false })
  const two = selectMatrixCell(one, cell('third'), handles, matrixTracks, { shift: true, toggle: false })
  const three = selectMatrixCell(two, cell('fourth'), handles, matrixTracks, { shift: true, toggle: false })
  expect(three.cells.map(item => item.handle)).toEqual(handles)
  expect(three.anchor).toEqual(cell('first'))
  const toggled = selectMatrixCell(three, cell('second'), handles, matrixTracks, { shift: false, toggle: true })
  expect(toggled.cells.map(item => item.handle)).toEqual(['first', 'third', 'fourth'])
})

test('noncontiguous copy and paste use visible residue order, not click order', () => {
  const selection = selected([cell('third'), cell('first')])
  expect(copyMatrix(selection, handles, item => item.handle)).toBe('first\tthird')
  expect(pasteMatrix('W\tG', selection, handles)).toEqual([{ ...cell('first'), value: 'W' }, { ...cell('third'), value: 'G' }])
  expect(pasteMatrix('Y', selection, handles).map(item => item.value)).toEqual(['Y', 'Y'])
})

test('paste validates the whole selection and rejects mismatched or specialized cells', () => {
  const selection = selected([cell('first'), cell('third')])
  expect(() => pasteMatrix('W\t!', selection, handles)).toThrow('氨基酸')
  expect(() => pasteMatrix('W\tG\tL', selection, handles)).toThrow('范围不匹配')
  expect(() => pasteMatrix('2\n3', selected([{ handle: 'first', track: 'sasa' }]), handles)).toThrow('Function')
  expect(() => pasteMatrix('W\tG', selected([cell('fourth')]), handles)).toThrow('超出')
})

test('sequence accepts the current full alphabet and SS8 keeps explicit input normalization with the owner', () => {
  for (const value of 'ACDEFGHIKLMNPQRSTVWYBXZJUO') expect(parseMatrixValue('sequence', value)).toBe(value)
  expect(parseMatrixValue('secondary_structure', '-')).toBe('-')
  expect(() => parseMatrixValue('secondary_structure', 'P')).toThrow('SS8')
  expect(() => parseMatrixValue('secondary_structure', '_')).toThrow('SS8')
  expect(parseMatrixValue('sasa', '12.5')).toBe(12.5)
  expect(() => parseMatrixValue('sasa', 'Infinity')).toThrow('有限')
  expect(parseMatrixValue('sequence', 'Mask')).toBeNull()
})
