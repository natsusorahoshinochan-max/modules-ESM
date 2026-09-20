declare module '3dmol' {
  export type Position = { x: number; y: number; z: number }
  export type Atom = Position & { chain: string; resi: number; atom: string }
  export type GLModel = {
    selectedAtoms: (selection: object) => Atom[]
  }
  export type GLViewer = {
    addModel: (data: string, format: string) => GLModel
    setStyle: (selection: object, style: object) => void
    addStyle: (selection: object, style: object) => void
    setClickable: (selection: object, enabled: boolean, callback: (atom: Atom, viewer: GLViewer, event: MouseEvent) => void) => void
    removeAllShapes: () => void
    removeAllLabels: () => void
    addSphere: (options: { center: Position; radius: number; color: string; opacity?: number }) => void
    addLabel: (text: string, options: { position: Position; fontSize?: number; backgroundOpacity?: number }) => void
    zoomTo: (selection?: object) => void
    render: () => void
    clear: () => void
  }

  export function createViewer(
    element: HTMLElement,
    options: { backgroundColor: string; antialias?: boolean },
  ): GLViewer
}
