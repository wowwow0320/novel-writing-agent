type ClientActionPayload = {
  action: string
  label?: string
  path?: string
  tag?: string
  detail?: Record<string, unknown>
}

function cleanText(value: string | null | undefined, limit = 160): string {
  const text = (value || '').replace(/\s+/g, ' ').trim()
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text
}

function sendClientLog(payload: ClientActionPayload) {
  const body = JSON.stringify({
    path: window.location.pathname,
    ...payload,
  })
  try {
    if (navigator.sendBeacon) {
      const blob = new Blob([body], { type: 'application/json' })
      if (navigator.sendBeacon('/api/client-log', blob)) return
    }
  } catch {
    // fall through to fetch
  }
  void fetch('/api/client-log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    keepalive: true,
  }).catch(() => {
    // Logging must never break user actions.
  })
}

function describeElement(el: HTMLElement): ClientActionPayload {
  const explicit =
    el.getAttribute('aria-label') ||
    el.getAttribute('title') ||
    el.getAttribute('data-log-label')
  const label = cleanText(explicit || el.innerText || el.textContent || el.getAttribute('value') || el.id || el.className)
  return {
    action: 'click',
    label: label || '(unlabeled)',
    tag: el.tagName.toLowerCase(),
    detail: {
      id: el.id || undefined,
      className: typeof el.className === 'string' ? cleanText(el.className, 120) : undefined,
      disabled: 'disabled' in el ? Boolean((el as HTMLButtonElement).disabled) : undefined,
    },
  }
}

export function installClientActionLogger() {
  const onClick = (event: MouseEvent) => {
    const target = event.target
    if (!(target instanceof Element)) return
    const el = target.closest(
      'button,a,summary,[role="button"],input[type="button"],input[type="submit"],input[type="checkbox"]',
    )
    if (!(el instanceof HTMLElement)) return
    sendClientLog(describeElement(el))
  }

  const onSubmit = (event: SubmitEvent) => {
    const target = event.target
    if (!(target instanceof HTMLFormElement)) return
    sendClientLog({
      action: 'submit',
      label: cleanText(target.getAttribute('aria-label') || target.id || target.className || 'form'),
      tag: 'form',
    })
  }

  document.addEventListener('click', onClick, true)
  document.addEventListener('submit', onSubmit, true)
  return () => {
    document.removeEventListener('click', onClick, true)
    document.removeEventListener('submit', onSubmit, true)
  }
}

export function logClientAction(action: string, detail?: Record<string, unknown>) {
  sendClientLog({ action, detail })
}
