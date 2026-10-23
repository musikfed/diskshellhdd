import React, { useEffect, useMemo, useState } from 'react'
import { api, fmtBytes } from './api.js'


export default function SearchPage({ roots = [], setError }) {
  const [query, setQuery] = useState('')
  const [root, setRoot] = useState('')
  const [category, setCategory] = useState('')
  const [extension, setExtension] = useState('')
  const [result, setResult] = useState({ files: [], fts: false })
  const [status, setStatus] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api('/api/search/status').then(setStatus).catch(() => {})
  }, [])

  const url = useMemo(() => {
    const params = new URLSearchParams({ limit: '250' })
    if (query.trim()) params.set('q', query.trim())
    if (root) params.set('root', root)
    if (category) params.set('category', category)
    if (extension.trim()) params.set('extension', extension.trim())
    return `/api/search/files?${params.toString()}`
  }, [query, root, category, extension])

  useEffect(() => {
    let stopped = false
    const timer = setTimeout(async () => {
      setBusy(true)
      try {
        const value = await api(url)
        if (!stopped) setResult(value)
      } catch (e) {
        if (!stopped) setError(e.message)
      } finally {
        if (!stopped) setBusy(false)
      }
    }, 180)
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [url, setError])

  return <div className="stack search-page">
    <section className="card">
      <h3>⚡ Fast file catalog</h3>
      <p className="muted">
        Поиск идёт по SQLite mini-database, которую Quick Index обновляет пакетами во время scan.
        Файловая система не обходится заново для каждого запроса.
      </p>
      <div className="search-controls">
        <label className="grow">
          <span>Имя / путь</span>
          <input
            autoFocus
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="например: invoice 2026, .iso, project"
          />
        </label>
        <label>
          <span>Root</span>
          <select value={root} onChange={e => setRoot(e.target.value)}>
            <option value="">Все индексированные roots</option>
            {roots.map(item => <option key={item.path} value={item.path}>{item.path}</option>)}
          </select>
        </label>
        <label>
          <span>Category</span>
          <select value={category} onChange={e => setCategory(e.target.value)}>
            <option value="">Все</option>
            {['photo','video','audio','document','archive','code','disk_image','other'].map(item =>
              <option value={item} key={item}>{item}</option>
            )}
          </select>
        </label>
        <label>
          <span>Extension</span>
          <input value={extension} onChange={e => setExtension(e.target.value)} placeholder=".pdf" />
        </label>
      </div>
      <div className="search-status">
        <span>{busy ? 'searching…' : `${result.files?.length || 0} shown`}</span>
        <span>{result.fts ? 'FTS5' : 'indexed fallback'}</span>
        <span>catalog: {status?.files ?? '—'} files</span>
      </div>
    </section>

    <section className="card">
      <h3>Результаты</h3>
      <div className="search-results">
        {(result.files || []).map(file => <div key={file.path}>
          <div className="search-file-main">
            <b>{file.name}</b>
            <span>{file.path}</span>
          </div>
          <span>{file.category}</span>
          <span>{file.extension || '—'}</span>
          <b>{fmtBytes(file.size)}</b>
        </div>)}
        {!busy && !(result.files || []).length && <p className="muted">
          В каталоге ничего не найдено. Сначала выполни Quick Index нужного root.
        </p>}
      </div>
    </section>

    <section className="card">
      <h3>Catalog freshness</h3>
      <div className="snapshot-list">
        {(status?.roots || []).map(item => <div key={item.root_path}>
          <b>{item.root_path}</b>
          <span>{item.status}</span>
          <span>scan {item.last_scan_id ?? '—'}</span>
          <span>{item.files_count} files</span>
        </div>)}
      </div>
    </section>
  </div>
}
