import { useState, type ReactNode } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import './interaction.css'

/** Shared modal focus boundary. The caller owns unsaved-work and busy decisions. */
export function InteractionDialog({ title, children, className, onClose, busy = false, onRestoreFocus }: {
  title: string
  children: ReactNode
  className?: string
  onClose: () => void
  busy?: boolean
  onRestoreFocus?: () => void
}) {
  const [returnFocus] = useState(() => document.activeElement instanceof HTMLElement ? document.activeElement : null)
  return <Dialog.Root open onOpenChange={open => { if (!open && !busy) onClose() }}>
    <Dialog.Portal>
      <Dialog.Overlay className="interaction-overlay" />
      <Dialog.Content className={`interaction-dialog ${className ?? ''}`} aria-describedby={undefined}
        onPointerDownOutside={event => event.preventDefault()}
        onEscapeKeyDown={event => event.preventDefault()}
        onCloseAutoFocus={event => { event.preventDefault(); if (onRestoreFocus) onRestoreFocus(); else if (returnFocus?.isConnected) returnFocus.focus() }}
        onKeyDown={event => {
          event.stopPropagation()
          // Handle Escape at the focused dialog, not document capture: nested
          // dialogs must not dismiss their parent during layer registration.
          if (event.key === 'Escape' && !busy && !event.nativeEvent.isComposing) {
            event.preventDefault()
            onClose()
          }
        }}>
        <Dialog.Title asChild><span className="interaction-visually-hidden">{title}</span></Dialog.Title>
        {children}
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
}
