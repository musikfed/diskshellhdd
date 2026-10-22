const base = import.meta.env.VITE_API_BASE || ''

export async function api(path, options = {}) {
  const response = await fetch(`${base}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(payload.message || payload.error || `HTTP ${response.status}`)
  }
  return payload
}

export const fmtBytes = (value = 0) => {
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let v = Number(value) || 0
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1 }
  return `${v.toFixed(i > 1 ? 2 : 0)} ${units[i]}`
}
