import React, { useEffect, useMemo, useState } from 'react'
import { api, fmtBytes } from './api.js'

const NAV = [
  ['dashboard', '🏠', 'Dashboard'],
  ['disks', '💽', 'Disks'],
  ['scan', '🔎', 'Examine'],
  ['analytics', '🦊', 'Analytics'],
  ['storage', '🧠', 'Storage Brain'],
  ['files', '🐻', 'Files'],
  ['vault', '🔐', 'Vault'],
  ['lab', '🧪', 'Storage Lab'],
]

function Card({ title, children, className = '' }) {
  return <section className={`card ${className}`}><h3>{title}</h3>{children}</section>
}

function Safety({ health }) {
  const s = health?.safety || {}
  return (
    <div className="safety">
      <strong>Safety gates</strong>
      <span className={s.file_writes ? 'on' : 'off'}>Files {s.file_writes ? 'ON' : 'LOCKED'}</span>
      <span className={s.vault_writes ? 'on' : 'off'}>Vault {s.vault_writes ? 'ON' : 'LOCKED'}</span>
      <span className={s.disk_writes ? 'danger' : 'off'}>Disk writes {s.disk_writes ? 'ON' : 'LOCKED'}</span>
      <span className={s.extent_moves ? 'danger' : 'off'}>Extent moves {s.extent_moves ? 'ON' : 'LOCKED'}</span>
    </div>
  )
}

export default function App() {
  const [page, setPage] = useState('dashboard')
  const [health, setHealth] = useState(null)
  const [scanId, setScanId] = useState(localStorage.getItem('scanId') || '')
  const [error, setError] = useState('')

  useEffect(() => { api('/api/health').then(setHealth).catch(e => setError(e.message)) }, [])
  useEffect(() => { if (scanId) localStorage.setItem('scanId', scanId) }, [scanId])

  const context = useMemo(() => ({ scanId, setScanId, setError }), [scanId])
  const pages = {
    dashboard: <Dashboard health={health} scanId={scanId} />,
    disks: <Disks />,
    scan: <Scan {...context} />,
    analytics: <Analytics {...context} />,
    storage: <StorageBrain {...context} />,
    files: <Files />,
    vault: <Vault />,
    lab: <StorageLab {...context} />,
  }

  return (
    <div className="app">
      <aside>
        <div className="brand"><div className="shell">🐚</div><div><b>DiskShell</b><small>Storage brain</small></div></div>
        <nav>{NAV.map(([id, icon, label]) => (
          <button key={id} className={page === id ? 'active' : ''} onClick={() => setPage(id)}>
            <span>{icon}</span>{label}
          </button>
        ))}</nav>
        <Safety health={health} />
      </aside>
      <main>
        <header><div><h1>{NAV.find(n => n[0] === page)?.[2]}</h1><p>Python-only local storage workspace</p></div><div className="scan-chip">Scan: {scanId || '—'}</div></header>
        {error && <div className="error" onClick={() => setError('')}>{error}</div>}
        {pages[page]}
      </main>
    </div>
  )
}

function Dashboard({ health, scanId }) {
  return <div className="grid">
    <Card title="DiskShell 0.3"><div className="hero"><div className="mascot">🐙</div><div><h2>Storage, not shell commands</h2><p>DiskShell understands content, storage classes, capacity reserve and placement plans. Windows commands live only inside adapters.</p></div></div></Card>
    <Card title="Current mode"><p>Version: <b>{health?.version || '...'}</b></p><p>Active scan: <b>{scanId || 'not selected'}</b></p><p>Local-only backend by default.</p></Card>
    <Card title="Workflow"><ol><li>Examine a disk or folder</li><li>Review Analytics</li><li>Build a Storage Plan</li><li>Enable writes only when you want to apply it</li></ol></Card>
  </div>
}

function Disks() {
  const [data, setData] = useState(null)
  useEffect(() => { api('/api/disks').then(setData).catch(() => setData({ disks: [] })) }, [])
  return <div className="stack">{(data?.disks || []).map(d => <Card key={d.number} title={`${d.friendly_name} · Disk ${d.number}`}>
    <div className="metrics"><Metric label="Size" value={fmtBytes(d.size)} /><Metric label="Bus" value={d.bus_type} /><Metric label="Style" value={d.partition_style} /><Metric label="Health" value={d.health_status} /></div>
    <p className={d.protected ? 'protected' : 'muted'}>{d.protected ? `Protected: ${d.protection_reasons.join(', ')}` : 'Not a system/app disk; write gate is still locked by default.'}</p>
    <div className="partitions">{d.partitions?.map(p => <div key={p.partition_number}><b>{p.drive_letter || '—'}</b><span>{p.filesystem || 'unformatted'}</span><span>{fmtBytes(p.size)}</span></div>)}</div>
  </Card>)}</div>
}

function Scan({ scanId, setScanId, setError }) {
  const [path, setPath] = useState('F:\\')
  const [job, setJob] = useState(null)
  async function start() {
    try {
      const j = await api('/api/scans', { method: 'POST', body: JSON.stringify({ path }) })
      setJob(j)
      const timer = setInterval(async () => {
        try {
          const next = await api(`/api/scans/${j.id}`)
          setJob(next)
          if (next.status === 'completed' || next.status === 'failed') {
            clearInterval(timer)
            if (next.scan_id) setScanId(String(next.scan_id))
          }
        } catch (e) { clearInterval(timer); setError(e.message) }
      }, 500)
    } catch (e) { setError(e.message) }
  }
  return <Card title="Read-only examination"><div className="hero"><div className="mascot">🔎</div><div className="grow"><label>Folder / volume root</label><input value={path} onChange={e => setPath(e.target.value)} /><button className="primary" onClick={start}>Start scan</button></div></div>
    {job && <div className="metrics"><Metric label="Status" value={job.status} /><Metric label="Files" value={job.files} /><Metric label="Folders" value={job.directories} /><Metric label="Indexed" value={fmtBytes(job.bytes)} /></div>}
    {job?.current_path && <p className="path">{job.current_path}</p>}
    {scanId && <p>Current Analytics scan id: <b>{scanId}</b></p>}
  </Card>
}

function Analytics({ scanId, setError }) {
  const [data, setData] = useState(null)
  useEffect(() => { if (scanId) api(`/api/analytics/${scanId}`).then(setData).catch(e => setError(e.message)) }, [scanId, setError])
  if (!scanId) return <Card title="Analytics"><p>Run Examine first.</p></Card>
  return <div className="stack">
    <Card title="Categories"><div className="bars">{data?.categories?.map(c => <Bar key={c.category} label={c.category} value={c.bytes} max={data.categories[0]?.bytes || 1} count={c.files} />)}</div></Card>
    <div className="grid two"><Card title="Top folders">{data?.top_directories?.slice(0, 12).map(x => <Row key={x.path} name={x.path} value={fmtBytes(x.total_size)} />)}</Card><Card title="Top files">{data?.top_files?.slice(0, 12).map(x => <Row key={x.path} name={x.name} value={fmtBytes(x.size)} />)}</Card></div>
  </div>
}

function StorageBrain({ scanId, setError }) {
  const [root, setRoot] = useState('F:\\Storage')
  const [classes, setClasses] = useState([])
  const [plan, setPlan] = useState(null)
  useEffect(() => { api('/api/storage/classes').then(x => setClasses(x.classes || [])).catch(e => setError(e.message)) }, [setError])
  async function build() {
    try { setPlan(await api('/api/storage/plans', { method: 'POST', body: JSON.stringify({ scan_id: Number(scanId), storage_root: root }) })) } catch (e) { setError(e.message) }
  }
  return <div className="stack"><Card title="Storage classes"><div className="class-grid">{classes.map(c => <div key={c.key}><b>{c.title}</b><small>{c.relative_root}</small><p>{c.description}</p></div>)}</div></Card>
    <Card title="Placement planner"><label>Managed storage root</label><input value={root} onChange={e => setRoot(e.target.value)} /><button className="primary" disabled={!scanId} onClick={build}>Build plan from scan {scanId || '—'}</button>
      {plan && <><div className="metrics"><Metric label="Items" value={plan.total_items} /><Metric label="Data" value={fmtBytes(plan.total_bytes)} /><Metric label="Reserve" value={fmtBytes(plan.reserve_bytes)} /><Metric label="Free" value={fmtBytes(plan.projected_free_bytes)} /></div>{plan.warnings?.map(w => <p className="warning" key={w}>{w}</p>)}<div className="plan">{plan.items?.slice(0, 30).map(i => <div key={i.id}><span>{i.source_path}</span><b>→ {i.target_class}</b><span>{fmtBytes(i.size)}</span></div>)}</div></>}
    </Card></div>
}

function Files() {
  const [path, setPath] = useState('F:\\')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  async function open(p = path) { try { const d = await api(`/api/files?path=${encodeURIComponent(p)}`); setData(d); setPath(d.path); setError('') } catch (e) { setError(e.message) } }
  useEffect(() => { open(path) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return <Card title="Two-pane foundation"><div className="file-toolbar"><input value={path} onChange={e => setPath(e.target.value)} /><button onClick={() => open()}>Open</button></div>{error && <p className="warning">{error}</p>}<div className="file-list">{data?.items?.slice(0, 500).map(i => <button key={i.path} onDoubleClick={() => i.is_dir && open(i.path)}><span>{i.is_dir ? '📁' : '📄'} {i.name}</span><span>{i.is_dir ? '' : fmtBytes(i.size)}</span></button>)}</div><p className="muted">Copy / move / trash endpoints exist, but remain locked until DS_ALLOW_FILE_WRITES=1.</p></Card>
}

function Vault() {
  return <Card title="Encrypted Vault"><div className="hero"><div className="mascot">🔐</div><div><h2>Envelope encryption</h2><p>Argon2id derives a key from identity + secret; a random master key encrypts catalog and objects with AES-GCM. Recovery key is independent. Vault writes are locked by default.</p><p className="muted">Use the API after explicitly enabling DS_ALLOW_VAULT_WRITES=1. Browser token handling will be hardened before remote access is enabled.</p></div></div></Card>
}

function StorageLab({ scanId, setError }) {
  const [data, setData] = useState(null)
  async function run() { try { setData(await api(`/api/storage-lab/simulate/${scanId}`)) } catch (e) { setError(e.message) } }
  return <Card title="Managed Interleave Simulator"><div className="hero"><div className="mascot">🧪</div><div className="grow"><p>Models logical placement classes without pretending we control platter geometry hidden by HDD firmware.</p><button className="primary" disabled={!scanId} onClick={run}>Simulate scan {scanId || '—'}</button></div></div>{data && <><p>Lanes: {data.lanes?.join(' · ')}</p><div className="extent-strip">{data.extents?.slice(0, 180).map((x, idx) => <i key={idx} title={`${x.lane}\n${x.path}`} className={`lane-${x.lane[0]}`} />)}</div><p>{data.note}</p></>}</Card>
}

function Metric({ label, value }) { return <div><small>{label}</small><b>{value}</b></div> }
function Row({ name, value }) { return <div className="row"><span title={name}>{name}</span><b>{value}</b></div> }
function Bar({ label, value, max, count }) { return <div className="bar"><div><b>{label}</b><span>{fmtBytes(value)} · {count} files</span></div><em><i style={{ width: `${Math.max(2, value / max * 100)}%` }} /></em></div> }
