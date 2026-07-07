// Thin fetch helpers — every call funnels through here so errors are uniform.

async function handle(resp) {
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (body?.error) detail = body.error
    } catch { /* non-JSON error body */ }
    const err = new Error(detail)
    err.status = resp.status
    throw err
  }
  return resp.json()
}

export const getJSON = (path) => fetch(path).then(handle)

export const postJSON = (path, body) =>
  fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  }).then(handle)

export function uploadFiles(files) {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  return fetch('/api/documents/upload', { method: 'POST', body: form }).then(handle)
}

export function downloadAsJSON(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
