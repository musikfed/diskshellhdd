import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { api, eventStreamUrl, fmtBytes, joinPath, thumbnailUrl } from './api.js'
import { DiagnosticsAdmin, DisksAdmin, FilesAdmin, RecoveryAdmin, ScanAdmin, SecurityAdmin, StorageBrainAdmin } from './AdminPages.jsx'
import StreamCopy from './StreamCopy.jsx'
import SearchPage from './SearchPage.jsx'
import RelocationPage from './RelocationPage.jsx'

const NAV = [
  ['dashboard', '🐙', 'Обзор'],
  ['disks', '🐧', 'Диски'],
  ['scan', '🔎', 'Обследование'],
  ['analytics', '🦊', 'Аналитика'],
  ['storage', '🧠', 'Storage Brain'],
  ['files', '🐻', 'Файлы'],
  ['search', '⚡', 'Быстрый поиск'],
  ['relocation', '🧭', 'Relocation Planner'],
  ['streamcopy', '🌊', 'StreamCopy · EXP'],
  ['people', '🦉', 'Photos / People'],
  ['vault', '🔐', 'Vault'],
  ['recovery', '🧭', 'Recovery'],
  ['diagnostics', '🩺', 'Diagnostics'],
  ['security', '🛡️', 'Security'],
  ['lab', '🧪', 'Storage Lab'],
]

function Card({ title, children, className = '' }) {
  return <section className={`card ${className}`}><h3>{title}</h3>{children}</section>
}


class PageErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('DiskShell page render failed', error, info)
  }

  componentDidUpdate(prevProps) {
    if (
      (prevProps.page !== this.props.page || prevProps.resetKey !== this.props.resetKey)
      && this.state.error
    ) {
      this.setState({ error: null })
    }
  }

  render() {
    if (!this.state.error) return this.props.children
    return <div className="error page-crash">
      <b>Страница DiskShell упала при рендере.</b>
      <span>{String(this.state.error?.message || this.state.error)}</span>
      <small>Если endpoint только что отключили, DiskShell попробует восстановить страницу после следующего обновления inventory.</small>
      <button onClick={() => this.setState({ error: null })}>Retry render</button>
    </div>
  }
}

function Safety({ health }) {
  const s = health?.safety || {}
  return <div className="safety">
    <strong>Safety / admin mode</strong>
    <span className={s.file_writes ? 'danger' : 'off'}>Файлы: {s.file_writes ? 'WRITE ON' : 'LOCKED'}</span>
    <span className={s.vault_writes ? 'danger' : 'off'}>Vault: {s.vault_writes ? 'WRITE ON' : 'LOCKED'}</span>
    <span className="off">Диски: {s.selected_disk_unlocks ? 'PER-DISK WRITE' : 'LOCKED'}</span>
    <span className={s.extent_moves ? 'danger' : 'off'}>Extents: {s.extent_moves ? 'WRITE ON' : 'LOCKED'}</span>
  </div>
}

export default function App() {
  const urlParams = new URLSearchParams(window.location.search)
  const requestedView = urlParams.get('view') || ''
  const detached = urlParams.get('detached') === '1' && NAV.some(([id]) => id === requestedView)
  const [page, setPage] = useState(detached ? requestedView : 'dashboard')
  const [workspaceReady, setWorkspaceReady] = useState(false)
  const [restoreNotice, setRestoreNotice] = useState('')
  const [activeStreamJob, setActiveStreamJob] = useState(null)
  const [health, setHealth] = useState(null)
  const [roots, setRoots] = useState([])
  const [activeVolume, setActiveVolume] = useState('')
  const [scanId, setScanId] = useState('')
  const [workspaceViewState, setWorkspaceViewState] = useState({})
  const [error, setError] = useState('')
  const refreshHealth = async () => {
    try {
      const value = await api('/api/health')
      setHealth(value)
      return value
    } catch (e) {
      setError(e.message)
      return null
    }
  }
  useEffect(() => {
    let stopped = false
    let timer = null

    const restoreWorkspace = async () => {
      try {
        const state = await api('/api/ui-state')
        if (stopped) return
        const nextPage = detached
          ? requestedView
          : NAV.some(([id]) => id === state.active_page)
            ? state.active_page
            : 'dashboard'
        setPage(nextPage)
        setActiveVolume(String(state.active_volume || ''))
        setScanId(String(state.scan_id || ''))
        setWorkspaceViewState(state.view_state || {})
        setRestoreNotice(`↩ Восстановлено: ${NAV.find(item => item[0] === nextPage)?.[2] || nextPage}`)
        timer = setTimeout(() => {
          if (!stopped) setRestoreNotice('')
        }, 5000)
      } catch {
        if (stopped) return
        const cachedPage = localStorage.getItem('activePage')
        setPage(detached
          ? requestedView
          : NAV.some(([id]) => id === cachedPage) ? cachedPage : 'dashboard')
        setActiveVolume(localStorage.getItem('activeVolume') || '')
        setScanId(localStorage.getItem('scanId') || '')
      } finally {
        if (!stopped) setWorkspaceReady(true)
      }
    }

    restoreWorkspace()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
    }
  }, [])

  useEffect(() => { refreshHealth() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    let stopped = false
    const refreshRoots = async () => {
      try {
        const value = await api('/api/files/roots')
        if (stopped) return
        const nextRoots = Array.isArray(value.roots) ? value.roots : []
        setRoots(nextRoots)
        setActiveVolume(current => {
          if (current) return current
          return nextRoots.find(item => item.available !== false)?.path || nextRoots[0]?.path || ''
        })
      } catch {
        // A transient storage inventory error must not take down the UI.
      }
    }
    refreshRoots()
    const timer = setInterval(refreshRoots, 3000)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [])
  useEffect(() => {
    if (!workspaceReady || detached) return
    localStorage.setItem('activePage', page)
    setError('')
    api('/api/ui-state', {
      method: 'PATCH',
      body: JSON.stringify({ active_page: page }),
    }).catch(() => {
      // Browser storage remains only a fallback cache; backend state is authoritative.
    })
  }, [page, workspaceReady, detached])
  const patchViewState = useCallback((patch) => {
    setWorkspaceViewState(current => ({ ...current, ...patch }))
    if (!workspaceReady) return
    api('/api/ui-state', {
      method: 'PATCH',
      body: JSON.stringify({ view_state: patch }),
    }).catch(() => {})
  }, [workspaceReady])

  useEffect(() => {
    const key = `pageScroll:${page}`
    const fallback = Number(localStorage.getItem(key) || 0)
    const saved = Number(workspaceViewState[key] ?? fallback)
    const restore = requestAnimationFrame(() => {
      window.scrollTo(0, Number.isFinite(saved) ? saved : 0)
    })
    const save = () => {
      const value = Math.round(window.scrollY)
      localStorage.setItem(key, String(value))
      patchViewState({ [key]: value })
    }
    return () => {
      cancelAnimationFrame(restore)
      save()
    }
  }, [page]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!workspaceReady) return
    if (activeVolume) localStorage.setItem('activeVolume', activeVolume)
    else localStorage.removeItem('activeVolume')
    api('/api/ui-state', {
      method: 'PATCH',
      body: JSON.stringify({ active_volume: activeVolume }),
    }).catch(() => {})
  }, [activeVolume, workspaceReady])
  useEffect(() => {
    if (!workspaceReady) return
    if (scanId) localStorage.setItem('scanId', scanId)
    else localStorage.removeItem('scanId')
    api('/api/ui-state', {
      method: 'PATCH',
      body: JSON.stringify({ scan_id: scanId }),
    }).catch(() => {})
  }, [scanId, workspaceReady])
  useEffect(() => {
    if (!workspaceReady) return
    if (page === 'streamcopy') {
      setActiveStreamJob(null)
      return
    }
    let stopped = false
    api('/api/streamcopy/jobs?active=1&limit=1')
      .then(value => {
        if (!stopped) {
          const jobs = Array.isArray(value.jobs) ? value.jobs : []
          setActiveStreamJob(jobs[0] || null)
        }
      })
      .catch(() => {
        if (!stopped) setActiveStreamJob(null)
      })
    return () => { stopped = true }
  }, [page, workspaceReady])

  useEffect(() => {
    if (!workspaceReady || typeof EventSource === 'undefined') return undefined
    const source = new EventSource(eventStreamUrl())

    const parse = event => {
      try { return JSON.parse(event.data)?.payload || {} } catch { return {} }
    }

    const workspaceChanged = event => {
      const payload = parse(event)
      if (payload.active_volume !== undefined) setActiveVolume(String(payload.active_volume || ''))
      if (payload.scan_id !== undefined) setScanId(String(payload.scan_id || ''))
      if (payload.view_state && typeof payload.view_state === 'object') {
        setWorkspaceViewState(payload.view_state)
      }
      if (!detached && NAV.some(([id]) => id === payload.active_page)) {
        setPage(payload.active_page)
      }
    }
    const scanCompleted = event => {
      const payload = parse(event)
      if (payload.scan_id != null) setScanId(String(payload.scan_id))
    }
    const streamChanged = event => {
      if (page === 'streamcopy') return
      const payload = parse(event)
      if (!payload.job_id) return
      setActiveStreamJob(current => ({
        ...(current || {}),
        id: payload.job_id,
        status: payload.status || current?.status || 'running',
      }))
    }

    source.addEventListener('workspace.changed', workspaceChanged)
    source.addEventListener('scan.completed', scanCompleted)
    source.addEventListener('streamcopy.changed', streamChanged)
    return () => source.close()
  }, [workspaceReady, detached, page])

  const context = useMemo(
    () => ({
      scanId,
      setScanId,
      setError,
      health,
      refreshHealth,
      roots,
      activeVolume,
      setActiveVolume,
      workspaceViewState,
      patchViewState,
    }),
    [scanId, health, roots, activeVolume, workspaceViewState, patchViewState],
  )
  const activeRoot = roots.find(item => item.path === activeVolume)
  const activeVolumeOffline = Boolean(activeVolume && (!activeRoot || activeRoot.available === false))
  const pages = {
    dashboard: <Dashboard {...context} setPage={setPage} />,
    disks: <DisksAdmin {...context} />,
    scan: <ScanAdmin {...context} />,
    analytics: <Analytics {...context} />,
    storage: <StorageBrainAdmin {...context} />,
    files: <FilesAdmin {...context} />,
    search: <SearchPage {...context} />,
    relocation: <RelocationPage {...context} />,
    streamcopy: <StreamCopy {...context} />,
    people: <People {...context} />,
    vault: <Vault {...context} />,
    recovery: <RecoveryAdmin {...context} />,
    diagnostics: <DiagnosticsAdmin {...context} />,
    security: <SecurityAdmin {...context} />,
    lab: <StorageLab {...context} />,
  }
  if (!workspaceReady) {
    return <div className="workspace-restore-screen">
      <div className="workspace-restore-card">
        <b>↩ DiskShell workspace</b>
        <span>Восстанавливаю актуальную вкладку из backend…</span>
      </div>
    </div>
  }

  return <div className="app">
    <aside>
      <div className="brand"><div className="shell">🐚</div><div><b>DiskShell</b><small>Storage Brain</small></div></div>
      <nav>{NAV.map(([id, icon, label]) => <button key={id} className={page === id ? 'active' : ''} onClick={() => setPage(id)}><span>{icon}</span>{label}</button>)}</nav>
      <Safety health={health} />
    </aside>
    <main>
      <header>
        <div><h1>{NAV.find(n => n[0] === page)?.[2]}</h1><p>Admin storage workbench · React + Python</p></div>
        <div className="header-context">
          <label className="active-volume-select">
            <span>Active volume</span>
            <select value={activeVolume} onChange={e => setActiveVolume(e.target.value)}>
              <option value="">—</option>
              {activeVolumeOffline && <option value={activeVolume}>
                {activeVolume} · OFFLINE / waiting for reconnect
              </option>}
              {roots.map(item => <option key={item.path} value={item.path} disabled={item.available === false}>
                {item.path} · {item.available === false ? 'OFFLINE' : (item.filesystem || 'FS')} · {item.free != null ? fmtBytes(item.free) + ' free' : '—'}
              </option>)}
            </select>
          </label>
          {restoreNotice && <div className="workspace-restore-chip">{restoreNotice}</div>}
          {detached && <div className="workspace-restore-chip">DETACHED VIEW</div>}
          <button
            className="workspace-process-chip"
            onClick={() => {
              const target = new URL(window.location.href)
              target.search = ''
              target.searchParams.set('view', page)
              target.searchParams.set('detached', '1')
              window.open(target.toString(), '_blank', 'noopener,noreferrer')
            }}
            title="Открыть текущий view в отдельном окне/на другом мониторе"
          >
            ↗ Open view
          </button>
          {activeStreamJob && <button
            className="workspace-process-chip"
            onClick={() => setPage('streamcopy')}
            title="Вернуться к активной backend-задаче StreamCopy"
          >
            ↩ StreamCopy · {activeStreamJob.status}
          </button>}
          <div className="scan-chip">Scan: {scanId || '—'}</div>
          {activeVolumeOffline && <div className="scan-chip">Volume offline · auto-detecting return</div>}
        </div>
      </header>
      {error && <div className="error" onClick={() => setError('')}>{error}</div>}
      <PageErrorBoundary
        page={page}
        resetKey={`${page}:${activeVolume}:${roots.map(item => `${item.path}:${item.available !== false ? '1' : '0'}`).join('|')}`}
      >
        {pages[page]}
      </PageErrorBoundary>
    </main>
  </div>
}

function Dashboard({ health, scanId, setPage }) {
  return <div className="stack">
    <Card title="DiskShell 0.8 · Persistent Workspace Foundation"><div className="hero"><div className="mascot huge">🐙</div><div><h2>Не оболочка команд. Storage workspace.</h2><p>DiskShell обследует накопитель, понимает типы данных, контролирует резерв, предлагает правильное размещение и только после твоего решения применяет безопасный план.</p><div className="actions"><button className="primary" onClick={() => setPage('scan')}>Обследовать диск</button><button onClick={() => setPage('storage')}>Storage Brain</button></div></div></div></Card>
    <div className="grid three">
      <Card title="Сейчас"><Metric label="Версия" value={health?.version || '...'} /><Metric label="Активный scan" value={scanId || 'нет'} /><Metric label="Режим" value="localhost / local-first" /></Card>
      <Card title="Правильный цикл"><ol><li>Обследовать</li><li>Понять Analytics</li><li>Построить placement plan</li><li>Сохранить резерв</li><li>Применить только нужное</li></ol></Card>
      <Card title="Защита"><p>System / Boot / Application disk блокируются независимо от UI.</p><p>System/Boot/Application диски блокируются всегда. Для остальных physical disk WRITE включается отдельным identity-bound тумблером до ручного выключения или restart backend.</p></Card>
    </div>
  </div>
}

function Disks({ health, setError }) {
  const [data, setData] = useState(null)
  const [plan, setPlan] = useState(null)
  const [confirm, setConfirm] = useState('')
  const [fs, setFs] = useState('NTFS')
  const [cluster, setCluster] = useState(4096)
  const [label, setLabel] = useState('Storage')
  const reload = () => api('/api/disks').then(setData).catch(e => setError(e.message))
  useEffect(reload, []) // eslint-disable-line react-hooks/exhaustive-deps
  async function planFormat(number) {
    try { setPlan(await api(`/api/disks/${number}/format-plan`, { method: 'POST', body: JSON.stringify({ filesystem: fs, label, allocation_unit: cluster }) })); setConfirm('') } catch (e) { setError(e.message) }
  }
  async function executeFormat() {
    if (!plan) return
    try { await api(`/api/disks/${plan.disk.number}/format`, { method: 'POST', body: JSON.stringify({ filesystem: fs, label, allocation_unit: cluster, confirmation: confirm }) }); setPlan(null); reload() } catch (e) { setError(e.message) }
  }
  return <div className="stack">
    {(data?.disks || []).map(d => <Card key={d.number} title={`${d.friendly_name} · Disk ${d.number}`}>
      <div className="metrics"><Metric label="Размер" value={fmtBytes(d.size)} /><Metric label="Bus" value={d.bus_type} /><Metric label="Стиль" value={d.partition_style} /><Metric label="Health" value={d.health_status} /></div>
      {d.reliability?.temperature_c != null && <div className="submetrics"><span>🌡 {d.reliability.temperature_c} °C</span><span>⏱ {d.reliability.power_on_hours ?? '—'} h</span><span>Read errors: {d.reliability.read_errors_total ?? '—'}</span></div>}
      <p className={d.protected ? 'protected' : 'muted'}>{d.protected ? `🔒 Protected: ${d.protection_reasons.join(', ')}` : 'Не system/app disk. Но disk-write gate всё равно закрыт.'}</p>
      <div className="partitions">{d.partitions?.map(p => <div key={p.partition_number}><b>{p.drive_letter || '—'}</b><span>{p.filesystem || 'unformatted'}</span><span>{fmtBytes(p.size)}</span><span>{p.label || ''}</span></div>)}</div>
      {!d.protected && <button onClick={() => planFormat(d.number)}>Partition Magic · подготовить план</button>}
    </Card>)}
    {plan && <Card title="Partition Magic · destructive plan" className="danger-card"><p className="warning">⚠ {plan.warning}</p><div className="metrics"><Metric label="Disk" value={`${plan.disk.number} · ${plan.disk.friendly_name}`} /><Metric label="Размер" value={fmtBytes(plan.disk.size)} /><Metric label="FS" value={fs} /><Metric label="Cluster" value={`${cluster} B`} /></div>
      <div className="form-row"><select value={fs} onChange={e => setFs(e.target.value)}><option>NTFS</option><option>EXFAT</option></select><select value={cluster} onChange={e => setCluster(Number(e.target.value))}>{[4096,8192,16384,32768,65536].map(x => <option key={x} value={x}>{x} B</option>)}</select><input value={label} onChange={e => setLabel(e.target.value)} /></div>
      <label>Для выполнения введи: <b>{plan.confirmation}</b></label><input value={confirm} onChange={e => setConfirm(e.target.value)} />
      <button className="danger-button" disabled={!health?.safety?.disk_writes || confirm !== plan.confirmation} onClick={executeFormat}>Форматировать выбранный диск</button>
      {!health?.safety?.disk_writes && <p className="muted">DS_ALLOW_DISK_WRITES=0 — выполнение физически заблокировано backend.</p>}
    </Card>}
  </div>
}

function Scan({ scanId, setScanId, setError }) {
  const [path, setPath] = useState('F:\\')
  const [job, setJob] = useState(null)
  async function start() {
    try {
      const j = await api('/api/scans', { method: 'POST', body: JSON.stringify({ path }) }); setJob(j)
      const timer = setInterval(async () => {
        try { const next = await api(`/api/scans/${j.id}`); setJob(next); if (['completed','failed'].includes(next.status)) { clearInterval(timer); if (next.scan_id) setScanId(String(next.scan_id)) } }
        catch (e) { clearInterval(timer); setError(e.message) }
      }, 500)
    } catch (e) { setError(e.message) }
  }
  return <Card title="Read-only обследование"><div className="hero"><div className="mascot">🔎</div><div className="grow"><label>Папка или корень тома</label><input value={path} onChange={e => setPath(e.target.value)} /><button className="primary" onClick={start}>Начать Quick Index</button></div></div>{job && <div className="metrics"><Metric label="Status" value={job.status} /><Metric label="Файлы" value={job.files} /><Metric label="Папки" value={job.directories} /><Metric label="Объём" value={fmtBytes(job.bytes)} /></div>}{job?.current_path && <p className="path">{job.current_path}</p>}{scanId && <p>Текущий индекс: <b>scan {scanId}</b></p>}</Card>
}

function Analytics({ scanId, setError }) {
  const [data, setData] = useState(null)
  const [duplicates, setDuplicates] = useState(null)
  useEffect(() => { if (scanId) api(`/api/analytics/${scanId}`).then(setData).catch(e => setError(e.message)) }, [scanId, setError])
  async function exact() { try { setDuplicates(await api(`/api/analytics/${scanId}/duplicates`, { method: 'POST', body: JSON.stringify({ min_size: 1024 * 1024, max_files: 4000 }) })) } catch (e) { setError(e.message) } }
  if (!scanId) return <Card title="Аналитика"><p>Сначала запусти Обследование.</p></Card>
  return <div className="stack">
    <Card title="Что занимает диск"><div className="bars">{data?.categories?.map(c => <Bar key={c.category} label={c.category} value={c.bytes} max={data.categories[0]?.bytes || 1} count={c.files} />)}</div></Card>
    <div className="grid two"><Card title="Самые тяжёлые папки">{data?.top_directories?.slice(0,15).map(x => <Row key={x.path} name={x.path} value={fmtBytes(x.total_size)} />)}</Card><Card title="Самые тяжёлые файлы">{data?.top_files?.slice(0,15).map(x => <Row key={x.path} name={x.path} value={fmtBytes(x.size)} />)}</Card></div>
    <Card title="Exact duplicates"><p>Быстрая оценка потенциальных повторов по размеру: <b>{fmtBytes(data?.duplicate_candidate_bytes)}</b>. Полная проверка SHA-256 запускается только вручную.</p><button onClick={exact}>Проверить точные дубликаты SHA-256</button>{duplicates && <><p>Потенциально освободить: <b>{fmtBytes(duplicates.potential_savings)}</b></p>{duplicates.groups.slice(0,20).map(g => <div className="duplicate" key={g.digest}><b>{fmtBytes(g.size)} × {g.count}</b>{g.files.map(f => <span key={f.path}>{f.path}</span>)}</div>)}</>}</Card>
  </div>
}

function StorageBrain({ scanId, setError, health }) {
  const [root, setRoot] = useState('F:\\Storage')
  const [classes, setClasses] = useState([])
  const [plan, setPlan] = useState(null)
  const [confirmation, setConfirmation] = useState('')
  const [verify, setVerify] = useState('size')
  const [result, setResult] = useState(null)
  useEffect(() => { api('/api/storage/classes').then(x => setClasses(x.classes || [])).catch(e => setError(e.message)) }, [setError])
  async function build() { try { const p = await api('/api/storage/plans', { method: 'POST', body: JSON.stringify({ scan_id: Number(scanId), storage_root: root }) }); setPlan(p); setConfirmation(''); setResult(null) } catch (e) { setError(e.message) } }
  async function apply() { try { const r = await api(`/api/storage/plans/${plan.id}/apply`, { method: 'POST', body: JSON.stringify({ confirmation, verify }) }); setResult(r); setPlan(await api(`/api/storage/plans/${plan.id}`)) } catch (e) { setError(e.message) } }
  return <div className="stack"><Card title="Storage classes"><div className="class-grid">{classes.map(c => <div key={c.key}><b>{c.title}</b><small>{c.relative_root}</small><p>{c.description}</p></div>)}</div></Card>
    <Card title="Placement Planner"><label>Корень управляемого хранилища</label><input value={root} onChange={e => setRoot(e.target.value)} /><button className="primary" disabled={!scanId} onClick={build}>Построить план из scan {scanId || '—'}</button>
      {plan && <><div className="metrics"><Metric label="Items" value={plan.total_items} /><Metric label="Данные" value={fmtBytes(plan.total_bytes)} /><Metric label="Рабочий резерв" value={fmtBytes(plan.reserve_bytes)} /><Metric label="После плана свободно" value={fmtBytes(plan.projected_free_bytes)} /></div>{plan.warnings?.map(w => <p className="warning" key={w}>{w}</p>)}<div className="plan">{plan.items?.slice(0,80).map(i => <div key={i.id} className={i.status}><span title={i.source_path}>{i.source_path}</span><b>→ {i.target_class}</b><span>{i.action}</span><span>{fmtBytes(i.size)}</span></div>)}</div>
        <div className="apply-box"><p><b>Same-volume</b>: atomic move + rollback journal. <b>Cross-volume</b>: copy→verify, исходник сохраняется.</p><select value={verify} onChange={e => setVerify(e.target.value)}><option value="size">Verify size</option><option value="sha256">Verify SHA-256</option></select><label>Введи <b>{plan.confirmation}</b></label><input value={confirmation} onChange={e => setConfirmation(e.target.value)} /><button className="primary" disabled={!health?.safety?.file_writes || confirmation !== plan.confirmation} onClick={apply}>Применить план</button>{!health?.safety?.file_writes && <small>DS_ALLOW_FILE_WRITES=0 — применение заблокировано.</small>}</div></>}
      {result && <p className="success">{result.status}: moved {result.same_volume_moves}, copied+verified {result.verified_cross_volume_copies}, failed {result.failed}</p>}
    </Card></div>
}

function Files({ health, setError }) {
  const [left, setLeft] = useState({ path: 'F:\\', data: null, selected: null })
  const [right, setRight] = useState({ path: 'F:\\', data: null, selected: null })
  const [preview, setPreview] = useState(null)
  async function load(side, path) { try { const data = await api(`/api/files?path=${encodeURIComponent(path)}`); const update = { path: data.path, data, selected: null }; side === 'left' ? setLeft(update) : setRight(update) } catch (e) { setError(e.message) } }
  useEffect(() => { load('left', left.path); load('right', right.path) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  async function choose(side, item) { side === 'left' ? setLeft(x => ({ ...x, selected: item })) : setRight(x => ({ ...x, selected: item })); if (!item.is_dir) { try { setPreview(await api(`/api/content/preview?path=${encodeURIComponent(item.path)}`)) } catch { setPreview(null) } } }
  async function transfer(kind, from, to, fromSide) { if (!from.selected) return; const destination = joinPath(to.path, from.selected.name); try { await api(`/api/files/${kind}`, { method: 'POST', body: JSON.stringify({ source: from.selected.path, destination }) }); await load(fromSide, from.path); await load(fromSide === 'left' ? 'right' : 'left', to.path) } catch (e) { setError(e.message) } }
  async function trash(side, name) { if (!side.selected) return; try { await api('/api/files/trash', { method: 'POST', body: JSON.stringify({ path: side.selected.path }) }); await load(name, side.path) } catch (e) { setError(e.message) } }
  return <div className="stack"><div className="file-manager"><FilePane title="LEFT" side="left" state={left} setState={setLeft} load={load} choose={choose} /><div className="file-actions"><button disabled={!health?.safety?.file_writes || !left.selected} onClick={() => transfer('copy', left, right, 'left')}>Copy →</button><button disabled={!health?.safety?.file_writes || !left.selected} onClick={() => transfer('move', left, right, 'left')}>Move →</button><button disabled={!health?.safety?.file_writes || !right.selected} onClick={() => transfer('copy', right, left, 'right')}>← Copy</button><button disabled={!health?.safety?.file_writes || !right.selected} onClick={() => transfer('move', right, left, 'right')}>← Move</button><button className="trash" disabled={!health?.safety?.file_writes || (!left.selected && !right.selected)} onClick={() => left.selected ? trash(left,'left') : trash(right,'right')}>Trash</button></div><FilePane title="RIGHT" side="right" state={right} setState={setRight} load={load} choose={choose} /></div>
    {preview && <PreviewCard preview={preview} />}</div>
}

function FilePane({ title, side, state, setState, load, choose }) {
  return <Card title={title} className="pane"><div className="file-toolbar"><button disabled={!state.data?.parent} onClick={() => state.data?.parent && load(side, state.data.parent)}>↑</button><input value={state.path} onChange={e => setState(x => ({ ...x, path: e.target.value }))} /><button onClick={() => load(side, state.path)}>Open</button></div><div className="file-list">{state.data?.items?.slice(0,1000).map(i => <button key={i.path} className={state.selected?.path === i.path ? 'selected' : ''} onClick={() => choose(side,i)} onDoubleClick={() => i.is_dir && load(side,i.path)}><span>{i.is_dir ? '📁' : '📄'} {i.name}</span><span>{i.is_dir ? '' : fmtBytes(i.size)}</span></button>)}</div></Card>
}

function Content({ health, setError }) {
  const [path, setPath] = useState('')
  const [preview, setPreview] = useState(null)
  const [archive, setArchive] = useState(null)
  const [destination, setDestination] = useState('')
  async function inspect() { setArchive(null); try { setPreview(await api(`/api/content/preview?path=${encodeURIComponent(path)}`)) } catch (e) { setError(e.message) } }
  async function browseArchive() { try { setArchive(await api(`/api/content/archive?path=${encodeURIComponent(path)}`)) } catch (e) { setError(e.message) } }
  async function extract() { try { await api('/api/content/archive/extract', { method:'POST', body:JSON.stringify({ path, destination }) }) } catch (e) { setError(e.message) } }
  return <div className="stack"><Card title="Preview Provider"><input placeholder="Полный путь к файлу" value={path} onChange={e => setPath(e.target.value)} /><div className="actions"><button className="primary" onClick={inspect}>Preview</button><button onClick={browseArchive}>Browse archive / ISO</button></div></Card>{preview && <PreviewCard preview={preview} />}{archive && <Card title={`${archive.provider.toUpperCase()} · ${archive.path}`}><div className="archive-list">{archive.entries.slice(0,1000).map((x,i) => <div key={`${x.name}-${i}`}><span>{x.is_dir ? '📁' : '📄'} {x.name}</span><span>{x.size == null ? '' : fmtBytes(x.size)}</span></div>)}</div><label>Extract destination (ZIP/TAR only)</label><input value={destination} onChange={e => setDestination(e.target.value)} /><button disabled={!health?.safety?.file_writes || !destination} onClick={extract}>Safe extract</button></Card>}</div>
}

function PreviewCard({ preview }) {
  const visual = ['image','pdf'].includes(preview.provider)
  return <Card title={`Preview · ${preview.name}`}><div className="preview-grid">{visual && <img className="preview-image" src={thumbnailUrl(preview.path, 800)} alt={preview.name} />}<div><div className="metrics"><Metric label="Provider" value={preview.provider} /><Metric label="Size" value={fmtBytes(preview.size)} /><Metric label="Type" value={preview.mime} /><Metric label="Geometry" value={preview.width ? `${preview.width}×${preview.height}` : preview.pages ? `${preview.pages} pages` : '—'} /></div>{preview.text && <pre className="text-preview">{preview.text.slice(0,50000)}</pre>}</div></div></Card>
}

function People({ scanId, setError }) {
  const [caps, setCaps] = useState(null)
  const [people, setPeople] = useState([])
  const [selected, setSelected] = useState(null)
  const [photos, setPhotos] = useState([])
  const [mode, setMode] = useState('all')
  const [similar, setSimilar] = useState([])
  const refresh = async () => { if (!scanId) return; const x = await api(`/api/people?scan_id=${scanId}`); setPeople(x.people || []) }
  useEffect(() => { api('/api/people/capabilities').then(setCaps).catch(e => setError(e.message)); refresh().catch(()=>{}) }, [scanId]) // eslint-disable-line react-hooks/exhaustive-deps
  async function analyze() { try { await api(`/api/people/analyze/${scanId}`, { method:'POST', body:'{}' }); await refresh() } catch (e) { setError(e.message) } }
  async function openPerson(p, nextMode = mode) {
    setSelected(p)
    setMode(nextMode)
    setSimilar([])
    try {
      const x = await api(`/api/people/${p.id}/photos?mode=${nextMode}`)
      setPhotos(x.photos || [])
    } catch (e) { setError(e.message) }
  }
  async function findSimilar() {
    if (!selected?.cover_face_id) return
    try {
      const x = await api(`/api/people/faces/${selected.cover_face_id}/similar?limit=80&min_score=0.35`)
      setSimilar(x.matches || [])
    } catch (e) { setError(e.message) }
  }
  return <div className="stack"><Card title="Local Face Engine"><div className="hero"><div className="mascot">🦉</div><div><p>OpenCV YuNet + SFace, только локально. Облако: <b>нет</b>.</p><p>Detector: {caps?.detector_ready ? 'ready' : 'model not configured'} · Recognizer: {caps?.recognizer_ready ? 'ready' : 'model not configured'}</p><button className="primary" disabled={!scanId || !caps?.ready} onClick={analyze}>Проанализировать фото из scan {scanId || '—'}</button></div></div></Card>
    <div className="people-grid">{people.map(p => <button key={p.id} className="person" onClick={() => openPerson(p)}>{p.cover_face_id ? <img src={`/api/people/faces/${p.cover_face_id}/thumbnail`} /> : <div className="face-placeholder">👤</div>}<b>{p.name}</b><small>{p.photos} photos · {p.faces} faces</small></button>)}</div>
    {selected && <Card title={selected.name}>
      <div className="tabs">
        {['all','alone','with_others'].map(x => <button className={mode===x?'active':''} key={x} onClick={() => openPerson(selected,x)}>{x}</button>)}
        <button disabled={!selected.cover_face_id || !caps?.recognizer_ready} onClick={findSimilar}>≈ похожие лица</button>
      </div>
      {similar.length > 0 && <div className="face-similarity-grid">
        {similar.map(item => <div key={item.face_id}>
          <img src={`/api/people/faces/${item.face_id}/thumbnail`} alt="" />
          <b>{item.person_name || `face #${item.face_id}`}</b>
          <small>similarity {(Number(item.score) * 100).toFixed(1)}%</small>
          <span title={item.path}>{item.path}</span>
        </div>)}
      </div>}
      <div className="photo-grid">{photos.map(p => <div key={p.id}><img src={thumbnailUrl(p.path,320)} /><small>{p.faces_count === 1 ? 'alone' : `${p.faces_count} faces`}</small></div>)}</div>
    </Card>}</div>
}


function VaultPathBrowser({
  title,
  roots,
  activeVolume,
  setActiveVolume,
  selectedPath,
  onSelect,
  allowFiles,
}) {
  const [path, setPath] = useState(activeVolume || roots[0]?.path || '')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  async function load(nextPath) {
    if (!nextPath) return
    setLoading(true)
    try {
      const value = await api(`/api/files?path=${encodeURIComponent(nextPath)}`)
      setData(value)
      setPath(value.path)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!path && (activeVolume || roots[0]?.path)) {
      load(activeVolume || roots[0]?.path)
      return
    }
    if (path) load(path)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function chooseVolume(value) {
    if (!value) return
    setActiveVolume(value)
    load(value)
  }

  return <div className="vault-browser">
    <div className="vault-browser-head">
      <div>
        <b>{title}</b>
        <small>{allowFiles ? 'Выбери файл или текущую папку целиком' : 'Выбери каталог назначения'}</small>
      </div>
      <select value={roots.find(item => path.startsWith(item.path))?.path || activeVolume || ''} onChange={e => chooseVolume(e.target.value)}>
        <option value="">Выбрать логический том…</option>
        {roots.map(item => <option key={item.path} value={item.path}>
          {item.path} · {item.filesystem || 'FS'} · {item.free != null ? fmtBytes(item.free) + ' free' : '—'}
        </option>)}
      </select>
    </div>

    <div className="vault-browser-toolbar">
      <button disabled={!data?.parent} onClick={() => data?.parent && load(data.parent)}>↑</button>
      <input value={path} onChange={e => setPath(e.target.value)} />
      <button onClick={() => load(path)}>Open</button>
      <button className="primary" disabled={!data?.path} onClick={() => onSelect(data.path)}>
        {allowFiles ? 'Выбрать эту папку' : 'Использовать эту папку'}
      </button>
    </div>

    <div className="vault-browser-list">
      {loading && <div className="muted">Загрузка…</div>}
      {!loading && data?.items?.map(item => {
        if (!item.is_dir && !allowFiles) return null
        return <button
          key={item.path}
          className={selectedPath === item.path ? 'selected' : ''}
          onClick={() => item.is_dir ? undefined : onSelect(item.path)}
          onDoubleClick={() => item.is_dir && load(item.path)}
        >
          <span>{item.is_dir ? '📁' : '📄'} {item.name}</span>
          <span>{item.is_dir ? (item.size_known ? fmtBytes(item.size) : 'folder') : fmtBytes(item.size)}</span>
        </button>
      })}
    </div>

    <div className="vault-browser-selected">
      <small>Выбрано</small>
      <code>{selectedPath || '—'}</code>
    </div>
  </div>
}

function Vault({ setError, roots, activeVolume, setActiveVolume, refreshHealth }) {
  const [status, setStatus] = useState(null)
  const [identity, setIdentity] = useState('')
  const [secret, setSecret] = useState('')
  const [recovery, setRecovery] = useState('')
  const [recoveryShown, setRecoveryShown] = useState('')
  const [unlocked, setUnlocked] = useState(false)
  const [items, setItems] = useState([])
  const [vaultVolume, setVaultVolume] = useState(() => activeVolume || '')
  const [vaultFolder, setVaultFolder] = useState('DiskShellVault')
  const [source, setSource] = useState(() => localStorage.getItem('vaultSourcePath') || activeVolume || '')
  const [destination, setDestination] = useState(() => localStorage.getItem('vaultDestinationPath') || activeVolume || '')
  const refreshStatus = () => api('/api/vault/status').then(setStatus).catch(e => setError(e.message))

  useEffect(refreshStatus, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!vaultVolume && (activeVolume || roots[0]?.path)) {
      setVaultVolume(activeVolume || roots[0]?.path || '')
    }
  }, [activeVolume, roots, vaultVolume])
  useEffect(() => {
    if (source) localStorage.setItem('vaultSourcePath', source)
  }, [source])
  useEffect(() => {
    if (destination) localStorage.setItem('vaultDestinationPath', destination)
  }, [destination])

  const locationEditable = status?.location_editable !== false
  const folderName = vaultFolder.trim().replace(/^[\\/]+/, '')
  const createRoot = locationEditable
    ? (vaultVolume && folderName ? joinPath(vaultVolume, folderName) : '')
    : (status?.root || '')
  const createBlockers = [
    !status ? 'Проверяю состояние Vault WRITE…' : '',
    status && !status.writes_allowed
      ? 'VAULT WRITE LOCKED — включи RAM-тумблер ниже.'
      : '',
    !createRoot ? 'Выбери том и папку Vault.' : '',
    !identity.trim() ? 'Заполни идентификатор.' : '',
    secret.length < 8 ? 'Секретная фраза должна содержать минимум 8 символов.' : '',
  ].filter(Boolean)

  async function toggleVaultWrites() {
    try {
      const next = await api('/api/vault/write-access', {
        method: 'POST',
        body: JSON.stringify({ enabled: !status?.writes_allowed }),
      })
      setStatus(current => current ? {
        ...current,
        writes_allowed: next.allowed,
        writes_runtime: next.runtime_enabled,
        writes_global_override: next.global_override,
      } : current)
      if (refreshHealth) await refreshHealth()
    } catch (e) {
      setError(e.message)
    }
  }

  async function loadItems() {
    try {
      const x = await api('/api/vault/items')
      setItems(x.items || [])
      setUnlocked(true)
    } catch {
      setUnlocked(false)
    }
  }

  async function create() {
    try {
      const x = await api('/api/vault/create', {
        method: 'POST',
        body: JSON.stringify({ identity, secret, root: createRoot }),
      })
      setRecoveryShown(x.recovery_key)
      await refreshStatus()
    } catch (e) {
      setError(e.message)
    }
  }

  async function unlock() {
    try {
      await api('/api/vault/unlock', {
        method: 'POST',
        body: JSON.stringify({ identity, secret }),
      })
      await loadItems()
    } catch (e) {
      setError(e.message)
    }
  }

  async function unlockRecovery() {
    try {
      await api('/api/vault/unlock-recovery', {
        method: 'POST',
        body: JSON.stringify({ recovery_key: recovery }),
      })
      await loadItems()
    } catch (e) {
      setError(e.message)
    }
  }

  async function lock() {
    await api('/api/vault/lock', { method: 'POST', body: '{}' })
    setUnlocked(false)
    setItems([])
  }

  async function importItem() {
    try {
      await api('/api/vault/import', {
        method: 'POST',
        body: JSON.stringify({ source }),
      })
      await loadItems()
    } catch (e) {
      setError(e.message)
    }
  }

  async function exportItem(item) {
    try {
      await api('/api/vault/export', {
        method: 'POST',
        body: JSON.stringify({ object_id: item.id, destination }),
      })
    } catch (e) {
      setError(e.message)
    }
  }

  return <div className="stack">
    <Card title="Encrypted Vault">
      <div className="hero">
        <div className="mascot">🔐</div>
        <div>
          <h2>Argon2id + AES-256-GCM</h2>
          <p>Chunked encryption для больших файлов. Unlock key остаётся в RAM backend; браузер получает HttpOnly SameSite cookie.</p>
          <p className="path">{status?.root}</p>
          <small>
            {status?.initialized
              ? 'Это фактическое постоянное местоположение Vault.'
              : status?.location_mode === 'environment'
                ? 'Путь зафиксирован через DS_VAULT_ROOT.'
                : 'До первого создания это только путь по умолчанию; место можно выбрать ниже.'}
          </small>
        </div>
      </div>
      <label className={`disk-write-toggle ${status?.writes_allowed ? 'enabled' : 'locked'}`}>
        <input
          type="checkbox"
          checked={Boolean(status?.writes_allowed)}
          disabled={Boolean(status?.writes_global_override)}
          onChange={toggleVaultWrites}
        />
        <span className="toggle-track"><i /></span>
        <span className="toggle-copy">
          <b>{status?.writes_allowed ? 'VAULT WRITE ENABLED' : 'VAULT WRITE LOCKED'}</b>
          <small>
            {status?.writes_global_override
              ? 'DS_ALLOW_VAULT_WRITES=1 · environment override'
              : 'RAM toggle · сбросится после restart backend'}
          </small>
        </span>
      </label>
    </Card>

    {!status?.initialized && <Card title="Создать Vault">
      <label>Том для зашифрованного Vault</label>
      <select
        value={vaultVolume}
        disabled={!locationEditable}
        onChange={e => {
          const value = e.target.value
          setVaultVolume(value)
          if (value) setActiveVolume(value)
        }}
      >
        <option value="">Выбрать логический том…</option>
        {roots.map(item => <option key={item.path} value={item.path}>
          {item.path} · {item.filesystem || 'FS'} · {item.free != null ? fmtBytes(item.free) + ' free' : '—'}
        </option>)}
      </select>

      <label>Папка Vault на выбранном томе</label>
      <input
        disabled={!locationEditable}
        placeholder="DiskShellVault"
        value={vaultFolder}
        onChange={e => setVaultFolder(e.target.value)}
      />

      <div className="vault-browser-selected">
        <small>Будет создано</small>
        <code>{createRoot || 'Выбери том и папку'}</code>
      </div>
      <p className="muted">
        DiskShell создаст внутри этой папки <code>vault.json</code>, <code>catalog.bin</code> и <code>objects\</code>.
        Корень тома вроде <code>W:\</code> использовать нельзя.
      </p>
      {status?.location_mode === 'environment' && <p className="muted">
        Место хранения задано через <code>DS_VAULT_ROOT</code>; выбор в UI заблокирован до изменения .env и перезапуска backend.
      </p>}


      <label>Идентификатор</label>
      <input
        placeholder="Например СНИЛС, логин или свой идентификатор"
        value={identity}
        onChange={e => setIdentity(e.target.value)}
      />
      <label>Секретная фраза</label>
      <input
        type="password"
        placeholder="Минимум 8 символов"
        value={secret}
        onChange={e => setSecret(e.target.value)}
      />

      {createBlockers.length > 0 && <div className="warning">
        <b>Почему кнопка пока недоступна:</b>
        <ul>
          {createBlockers.map(reason => <li key={reason}>{reason}</li>)}
        </ul>
      </div>}

      <button
        disabled={createBlockers.length > 0}
        title={createBlockers.join(' ')}
        onClick={create}
      >
        Создать Vault
      </button>
    </Card>}

    {recoveryShown && <Card title="Recovery key · сохранить сейчас" className="danger-card">
      <p className="warning">
        Это резервный ключ доступа к Vault. Сохрани его отдельно от диска с Vault. После закрытия этого блока DiskShell больше не сможет показать его из сохранённых данных.
      </p>
      <code className="recovery">{recoveryShown}</code>
      <div className="actions">
        <button onClick={() => setRecoveryShown('')}>Я сохранил recovery key</button>
      </div>
    </Card>}

    {status?.initialized && !unlocked && <div className="grid two">
      <Card title="Unlock">
        <input placeholder="Идентификатор" value={identity} onChange={e=>setIdentity(e.target.value)} />
        <input type="password" placeholder="Секретная фраза" value={secret} onChange={e=>setSecret(e.target.value)} />
        <button className="primary" onClick={unlock}>Unlock</button>
      </Card>
      <Card title="Recovery">
        <input placeholder="Recovery key" value={recovery} onChange={e=>setRecovery(e.target.value)} />
        <button onClick={unlockRecovery}>Unlock recovery</button>
      </Card>
    </div>}

    {unlocked && <Card title="Vault objects">
      <div className="vault-path-grid">
        <VaultPathBrowser
          title="Что шифровать"
          roots={roots}
          activeVolume={activeVolume}
          setActiveVolume={setActiveVolume}
          selectedPath={source}
          onSelect={setSource}
          allowFiles
        />
        <VaultPathBrowser
          title="Куда восстанавливать"
          roots={roots}
          activeVolume={activeVolume}
          setActiveVolume={setActiveVolume}
          selectedPath={destination}
          onSelect={setDestination}
          allowFiles={false}
        />
      </div>
      <div className="actions">
        <button onClick={lock}>Lock now</button>
        <button disabled={!status?.writes_allowed || !source} onClick={importItem}>
          Encrypt file / folder
        </button>
      </div>
      <p className="muted">
        Если выбрана папка, Vault шифрует все файлы рекурсивно и сохраняет относительные пути.
        При экспорте структура каталогов восстанавливается внутри выбранной папки назначения.
      </p>
      <div className="vault-list">{items.map(i => <div key={i.id}>
        <span>🔒 {i.relative_path || i.name}</span>
        <span>{fmtBytes(i.size)}</span>
        <button disabled={!status?.writes_allowed || !destination} onClick={() => exportItem(i)}>Export</button>
      </div>)}</div>
    </Card>}
  </div>
}

function StorageLab({ scanId, setError, activeVolume, setActiveVolume }) {
  const [data, setData] = useState(null)
  const [path, setPath] = useState('')
  const [roots, setRoots] = useState([])
  const [extents, setExtents] = useState(null)
  const [bench, setBench] = useState(null)
  const [seqMiB, setSeqMiB] = useState(150)
  const [seekMs, setSeekMs] = useState(10)
  const [seekBudgetPct, setSeekBudgetPct] = useState(2)

  useEffect(() => {
    api('/api/files/roots').then(x => setRoots(x.roots || [])).catch(() => {})
  }, [])

  async function run() {
    try {
      const query = new URLSearchParams({
        sequential_mib_s: String(seqMiB),
        seek_ms: String(seekMs),
        target_seek_overhead: String(Number(seekBudgetPct) / 100),
      })
      setData(await api(`/api/storage-lab/simulate/${scanId}?${query.toString()}`))
    } catch (e) { setError(e.message) }
  }

  async function queryExtents() {
    try { setExtents(await api(`/api/storage-lab/extents?path=${encodeURIComponent(path)}`)) }
    catch (e) { setError(e.message) }
  }

  async function benchmark() {
    try {
      const value = await api('/api/storage-lab/benchmark', {
        method:'POST',
        body:JSON.stringify({ path, block_size:4*1024*1024, samples:48 }),
      })
      setBench(value)
      setSeqMiB(Number(value.sequential.mib_per_second.toFixed(1)))
      setSeekMs(Number(value.random.latency_ms_median.toFixed(1)))
    } catch (e) { setError(e.message) }
  }

  return <div className="stack storage-lab">
    <Card title="Adaptive Managed Interleave Simulator">
      <div className="hero">
        <div className="mascot">🧪</div>
        <div className="grow">
          <p>
            Не случайная мелкая фрагментация, а bounded macro-interleave:
            длинные полосы для sequential-классов, более короткие — для interactive,
            с ограничением размера extent и числа extents на файл.
          </p>
          <div className="lab-controls">
            <label>Sequential MiB/s<input type="number" min="10" max="1000" value={seqMiB} onChange={e=>setSeqMiB(Number(e.target.value))} /></label>
            <label>Seek, ms<input type="number" min="0.1" max="100" step="0.1" value={seekMs} onChange={e=>setSeekMs(Number(e.target.value))} /></label>
            <label>Seek budget, %<input type="number" min="0.5" max="20" step="0.5" value={seekBudgetPct} onChange={e=>setSeekBudgetPct(Number(e.target.value))} /></label>
            <button className="primary" disabled={!scanId} onClick={run}>Simulate scan {scanId || '—'}</button>
          </div>
          <small>
            Формула поднимает минимальную полосу, если на этом HDD seek слишком дорог
            относительно времени последовательного чтения. Значения ограничены policy
            каждого класса, чтобы полосы не стали бесконечно длинными.
          </small>
        </div>
      </div>

      {data && <>
        <div className="metrics">
          <Metric label="Bands" value={data.metrics?.bands ?? '—'} />
          <Metric label="Extents" value={data.metrics?.extents ?? '—'} />
          <Metric label="Split files" value={data.metrics?.fragmented_files ?? '—'} />
          <Metric label="Max extents / file" value={data.metrics?.max_extents_per_file ?? '—'} />
          <Metric label="Median extent" value={fmtBytes(data.metrics?.median_extent_bytes || 0)} />
          <Metric label="Smallest split extent" value={fmtBytes(data.metrics?.smallest_split_extent_bytes || 0)} />
          <Metric label="Tiny split extents" value={data.metrics?.tiny_split_extents ?? '—'} />
          <Metric label="Layout quality" value={data.metrics?.quality ?? '—'} />
        </div>

        <div className="lane-policy-grid">
          {Object.entries(data.lane_stats || {}).map(([lane, stat]) => <div key={lane}>
            <b>{lane}</b>
            <span>min {fmtBytes(stat.min_band)}</span>
            <span>target {fmtBytes(stat.target_band)}</span>
            <span>max {fmtBytes(stat.max_band)}</span>
            <span>bands {stat.bands} · extents {stat.extents}</span>
            <span>seek ≈ {(Number(stat.estimated_seek_overhead || 0) * 100).toFixed(2)}%</span>
            <small>{stat.description}</small>
          </div>)}
        </div>

        <div className="band-strip">
          {data.bands?.slice(0, 500).map((band, idx) => {
            const total = data.bands.reduce((sum, x) => sum + Number(x.length || 0), 0) || 1
            const pct = Math.max(0.35, Number(band.length || 0) * 100 / total)
            return <i
              key={idx}
              className={`lane-${band.lane[0]}`}
              style={{ flexBasis: `${pct}%` }}
              title={`${band.lane}\n${fmtBytes(band.length)}\n${band.extent_count} extents · ${band.file_count} files`}
            />
          })}
        </div>
        <p>
          Это карта <b>полос</b>, а не каждого мелкого file extent. Полоса может содержать
          несколько маленьких файлов одного класса или один сегмент большого файла.
        </p>
        <p>{data.note}</p>
      </>}
    </Card>

    <Card title="NTFS Extents + read benchmark">
      <label>Локальный том</label>
      <select
        value={roots.some(item => path.startsWith(item.path)) ? roots.find(item => path.startsWith(item.path))?.path || activeVolume : activeVolume}
        onChange={e => {
          const value = e.target.value
          if (!value) return
          setActiveVolume(value)
          setPath(value)
        }}
      >
        <option value="">Выбрать том / корень…</option>
        {roots.map(item => <option key={item.path} value={item.path}>{item.path} · {item.filesystem || 'FS'} · {item.free != null ? fmtBytes(item.free) + ' free' : '—'}</option>)}
      </select>
      <label>Большой тестовый файл на выбранном томе</label>
      <input placeholder="Полный путь к большому тестовому файлу" value={path} onChange={e=>setPath(e.target.value)} />
      <div className="actions">
        <button onClick={queryExtents}>Query extents</button>
        <button onClick={benchmark}>Read benchmark → подставить в simulator</button>
      </div>
      {extents && <p>Extents: <b>{extents.extent_count ?? '—'}</b> · {extents.supported ? 'NTFS mapping available' : extents.reason}</p>}
      {bench && <div className="metrics">
        <Metric label="Sequential" value={`${bench.sequential.mib_per_second.toFixed(1)} MiB/s`} />
        <Metric label="Seq p95" value={`${bench.sequential.latency_ms_p95.toFixed(1)} ms`} />
        <Metric label="Random" value={`${bench.random.mib_per_second.toFixed(1)} MiB/s`} />
        <Metric label="Random median" value={`${bench.random.latency_ms_median.toFixed(1)} ms`} />
      </div>}
    </Card>
  </div>
}

function Metric({ label, value }) { return <div><small>{label}</small><b>{value}</b></div> }
function Row({ name, value }) { return <div className="row"><span title={name}>{name}</span><b>{value}</b></div> }
function Bar({ label, value, max, count }) { return <div className="bar"><div><b>{label}</b><span>{fmtBytes(value)} · {count} files</span></div><em><i style={{ width:`${Math.max(2,value/max*100)}%` }} /></em></div> }
