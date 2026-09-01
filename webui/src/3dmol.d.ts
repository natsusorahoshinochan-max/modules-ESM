declare module '3dmol' {
  export type GLViewer = {
    addModel: (data: string, format: string) => void
    setStyle: (selection: object, style: object) => void
    addStyle: (selection: object, style: object) => void
    zoomTo: (selection?: object) => void
    render: () => void
    clear: () => void
  }

  export function createViewer(
    element: HTMLElement,
    options: { backgroundColor: string; antialias?: boolean },
  ): GLViewer
}
