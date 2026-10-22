import React, { useEffect, useMemo, useState } from 'react'
import { api, fmtBytes, joinPath } from './api.js'

function Panel({ title, children, className = '' }) {
  return <section className={`card admin-panel ${className}`}><h3>{title}</h3>{children}</section>
}

function Metric({ label, value }) {
  return <div><small>{label}</small><b>{value}</b></div>
}

function StatusPill({ children, tone = 'neutral' }) {
  return <span className={`status-pill ${tone}`}>{children}</span>
}

const TERMINAL_SCAN = new Set(['completed', 'failed', 'cancelled'])
const TERMINAL_PLAN = new Set(['completed', 'partial', 'failed', 'blocked', 'cancelled'])

export function DisksAdmin({ setError }) {
  const [data, setData] = useState(null)
  const [unlockPlan, setUnlockPlan] = useState(null)
  const [unlockConfirm, setUnlockConfirm] = useState('')
  const [formatPlan, setFormatPlan] = useState(null)
  const [formatConfirm, setFormatConfirm] = useState('')
  const [fs, setFs] = useState('NTFS')
  const [cluster, setCluster] = useState(16384)
  const [label, setLabel] = useState('Storage')
  const [partitionDraft, setPartitionDraft] = useState(null)
  const [partitionPlan, setPartitionPlan] = useState(null)
  const [partitionConfirm, setPartitionConfirm] = useState('')
  const [initializePlan, setInitializePlan] = useState(null)
  const [initializeConfirm, setInitializeConfirm] = useState('')
  const [letterDraft, setLetterDraft] = useState(null)
  const [letterConfirm, setLetterConfirm] = useState('')

  const reload = () => api('/api/disks').then(setData).catch(e => setError(e.message))
  useEffect(reload, []) // eslint-disable-line react-hooks/exhaustive-deps

  const diskByNumber = number => (data?.disks || []).find(d => d.number === number)

  async function prepareUnlock(disk) {
    try {
      const value = await api(`/api/disks/${disk.number}/unlock-plan`, { method: 'POST', body: '{}' })
      setUnlockPlan(value)
      setUnlockConfirm('')
    } catch (e) { setError(e.message) }
  }

  async function unlock() {
    try {
      await api(`/api/disks/${unlockPlan.disk.number}/unlock`, {
        method: 'POST',
        body: JSON.stringify({ confirmation: unlockConfirm }),
      })
      setUnlockPlan(null)
      setUnlockConfirm('')
      await reload()
    } catch (e) { setError(e.message) }
  }

  async function lock(number) {
    try {
      await api(`/api/disks/${number}/lock`, { method: 'POST', body: '{}' })
      await reload()
    } catch (e) { setError(e.message) }
  }

  async function prepareFormat(number) {
    try {
      const value = await api(`/api/disks/${number}/format-plan`, {
        method: 'POST',
        body: JSON.stringify({ filesystem: fs, label, allocation_unit: cluster }),
      })
      setFormatPlan(value)
      setFormatConfirm('')
    } catch (e) { setError(e.message) }
  }

  async function executeFormat() {
    try {
      await api(`/api/disks/${formatPlan.disk.number}/format`, {
        method: 'POST',
        body: JSON.stringify({
          filesystem: fs,
          label,
          allocation_unit: cluster,
          confirmation: formatConfirm,
        }),
      })
      setFormatPlan(null)
      await reload()
    } catch (e) { setError(e.message) }
  }

  async function prepareInitialize(number) {
    try {
      const value = await api(`/api/disks/${number}/initialize-plan`, {
        method: 'POST',
        body: JSON.stringify({ partition_style: 'GPT' }),
      })
      setInitializePlan(value)
      setInitializeConfirm('')
    } catch (e) { setError(e.message) }
  }

  async function executeInitialize() {
    try {
      await api(`/api/disks/${initializePlan.disk.number}/initialize`, {
        method: 'POST',
        body: JSON.stringify({ partition_style: 'GPT', confirmation: initializeConfirm }),
      })
      setInitializePlan(null)
      await reload()
    } catch (e) { setError(e.message) }
  }

  function newPartition(disk) {
    setPartitionDraft({
      diskNumber: disk.number,
      sizeGiB: '',
      filesystem: 'NTFS',
      allocationUnit: 16384,
      label: 'Data',
      driveLetter: '',
    })
    setPartitionPlan(null)
    setPartitionConfirm('')
  }

  async function preparePartition() {
    const sizeBytes = partitionDraft.sizeGiB
      ? Math.floor(Number(partitionDraft.sizeGiB) * 1024 ** 3)
      : null
    try {
      const value = await api(`/api/disks/${partitionDraft.diskNumber}/partitions/create-plan`, {
        method: 'POST',
        body: JSON.stringify({
          size_bytes: sizeBytes,
          filesystem: partitionDraft.filesystem,
          label: partitionDraft.label,
          allocation_unit: partitionDraft.allocationUnit,
          drive_letter: partitionDraft.driveLetter || null,
        }),
      })
      setPartitionPlan(value)
      setPartitionConfirm('')
    } catch (e) { setError(e.message) }
  }

  async function executePartition() {
    try {
      await api(`/api/disks/${partitionDraft.diskNumber}/partitions`, {
        method: 'POST',
        body: JSON.stringify({
          size_bytes: partitionPlan.use_maximum ? null : partitionPlan.size_bytes,
          filesystem: partitionDraft.filesystem,
          label: partitionDraft.label,
          allocation_unit: partitionDraft.allocationUnit,
          drive_letter: partitionDraft.driveLetter || null,
          confirmation: partitionConfirm,
        }),
      })
      setPartitionDraft(null)
      setPartitionPlan(null)
      await reload()
    } catch (e) { setError(e.message) }
  }

  function prepareLetter(disk, partition) {
    setLetterDraft({
      diskNumber: disk.number,
      partitionNumber: partition.partition_number,
      driveLetter: partition.drive_letter?.replace(':', '') || '',
    })
    setLetterConfirm('')
  }

  async function executeLetter() {
    const letter = letterDraft.driveLetter.trim().toUpperCase().replace(':', '')
    const expected = `ASSIGN ${letter}: DISK ${letterDraft.diskNumber} PARTITION ${letterDraft.partitionNumber}`
    try {
      await api(
        `/api/disks/${letterDraft.diskNumber}/partitions/${letterDraft.partitionNumber}/drive-letter`,
        {
          method: 'POST',
          body: JSON.stringify({ drive_letter: letter, confirmation: letterConfirm }),
        },
      )
      setLetterDraft(null)
      await reload()
    } catch (e) { setError(e.message) }
    return expected
  }

  return <div className="stack admin-workbench">
    <div className="admin-banner">
      <div className="admin-icon">⚠</div>
      <div>
        <b>Administrator / storage engineer mode</b>
        <p>Операции разметки могут необратимо уничтожить данные. Оператор должен понимать разницу между физическим диском, таблицей разделов, разделом, томом, файловой системой и буквой диска. Использование — на свой риск; сначала проверяй identity и резервные копии.</p>
      </div>
    </div>

    {(data?.disks || []).map(d => {
      const write = d.write_access || {}
      return <Panel key={d.number} title={`Disk ${d.number} · ${d.friendly_name}`} className="disk-card">
        <div className="disk-head">
          <div className="metrics">
            <Metric label="Размер" value={fmtBytes(d.size)} />
            <Metric label="Bus" value={d.bus_type} />
            <Metric label="Partition style" value={d.partition_style} />
            <Metric label="Health" value={d.health_status} />
          </div>
          <StatusPill tone={d.protected ? 'warning' : write.allowed ? 'danger' : 'good'}>
            {d.protected ? 'PROTECTED' : write.allowed ? 'WRITE UNLOCKED' : 'WRITE LOCKED'}
          </StatusPill>
        </div>

        <div className="disk-identity">
          <span>Serial: <b>{d.serial_number || '—'}</b></span>
          <span>UniqueId: <b>{d.unique_id || '—'}</b></span>
          <span>Free extent: <b>{fmtBytes(d.largest_free_extent)}</b></span>
        </div>

        {d.protected
          ? <p className="protected">🔒 {d.protection_reasons.join(', ')}</p>
          : <div className="actions">
              {!write.allowed && <button className="unlock-button" onClick={() => prepareUnlock(d)}>Разблокировать только этот диск</button>}
              {write.allowed && <button onClick={() => lock(d.number)}>🔒 Заблокировать запись</button>}
              {String(d.partition_style).toUpperCase() === 'RAW' && <button onClick={() => prepareInitialize(d.number)}>Инициализировать GPT</button>}
              {Number(d.largest_free_extent || 0) > 0 && String(d.partition_style).toUpperCase() !== 'RAW' && <button onClick={() => newPartition(d)}>+ Раздел / том</button>}
              <button className="danger-outline" onClick={() => prepareFormat(d.number)}>Очистить + один том</button>
            </div>}

        <div className="partition-table">
          <div className="partition-header"><span>Part</span><span>Letter</span><span>FS</span><span>Size</span><span>Free</span><span>Label</span><span /></div>
          {(d.partitions || []).map(p => <div key={p.partition_number}>
            <span>#{p.partition_number}</span>
            <b>{p.drive_letter || '—'}</b>
            <span>{p.filesystem || 'unformatted'}</span>
            <span>{fmtBytes(p.size)}</span>
            <span>{p.size_remaining == null ? '—' : fmtBytes(p.size_remaining)}</span>
            <span>{p.label || '—'}</span>
            <button disabled={d.protected || !write.allowed} onClick={() => prepareLetter(d, p)}>Буква</button>
          </div>)}
        </div>
      </Panel>
    })}

    {unlockPlan && <Panel title="Разблокировка выбранного физического диска" className="danger-card">
      <p className="warning">{unlockPlan.warning}</p>
      <div className="metrics">
        <Metric label="Disk" value={unlockPlan.disk.number} />
        <Metric label="Model" value={unlockPlan.disk.friendly_name} />
        <Metric label="Serial" value={unlockPlan.disk.serial_number || '—'} />
        <Metric label="Размер" value={fmtBytes(unlockPlan.disk.size)} />
      </div>
      <label>Для временной разблокировки введи точно: <b>{unlockPlan.confirmation}</b></label>
      <input value={unlockConfirm} onChange={e => setUnlockConfirm(e.target.value)} />
      <div className="actions">
        <button className="danger-button" disabled={unlockConfirm !== unlockPlan.confirmation} onClick={unlock}>Разблокировать на 15 минут</button>
        <button onClick={() => setUnlockPlan(null)}>Отмена</button>
      </div>
    </Panel>}

    {initializePlan && <Panel title="Initialize disk" className="danger-card">
      <p className="warning">{initializePlan.warning}</p>
      <label>Введи: <b>{initializePlan.confirmation}</b></label>
      <input value={initializeConfirm} onChange={e => setInitializeConfirm(e.target.value)} />
      <button className="danger-button" disabled={initializeConfirm !== initializePlan.confirmation || !diskByNumber(initializePlan.disk.number)?.write_access?.allowed} onClick={executeInitialize}>Initialize GPT</button>
    </Panel>}

    {formatPlan && <Panel title="Очистить диск и создать один том" className="danger-card">
      <p className="warning">⚠ {formatPlan.warning}</p>
      <div className="form-row">
        <select value={fs} onChange={e => setFs(e.target.value)}><option>NTFS</option><option>EXFAT</option></select>
        <select value={cluster} onChange={e => setCluster(Number(e.target.value))}>
          {[4096, 8192, 16384, 32768, 65536].map(x => <option key={x} value={x}>{x / 1024} KiB</option>)}
        </select>
        <input value={label} onChange={e => setLabel(e.target.value)} />
      </div>
      <div className="preset-hint"><b>4K</b> universal · <b>16K</b> mixed large storage · <b>64K</b> mostly huge sequential files</div>
      <label>Для выполнения введи: <b>{formatPlan.confirmation}</b></label>
      <input value={formatConfirm} onChange={e => setFormatConfirm(e.target.value)} />
      <button className="danger-button" disabled={formatConfirm !== formatPlan.confirmation || !diskByNumber(formatPlan.disk.number)?.write_access?.allowed} onClick={executeFormat}>Очистить и форматировать</button>
    </Panel>}

    {partitionDraft && <Panel title={`Создать раздел / том на Disk ${partitionDraft.diskNumber}`}>
      <div className="grid two">
        <div>
          <label>Размер, GiB (пусто = всё максимальное свободное место)</label>
          <input value={partitionDraft.sizeGiB} onChange={e => setPartitionDraft(x => ({ ...x, sizeGiB: e.target.value }))} />
        </div>
        <div>
          <label>Буква (пусто = Windows назначит автоматически)</label>
          <input maxLength={2} value={partitionDraft.driveLetter} onChange={e => setPartitionDraft(x => ({ ...x, driveLetter: e.target.value }))} />
        </div>
      </div>
      <div className="form-row">
        <select value={partitionDraft.filesystem} onChange={e => setPartitionDraft(x => ({ ...x, filesystem: e.target.value }))}><option>NTFS</option><option>EXFAT</option></select>
        <select value={partitionDraft.allocationUnit} onChange={e => setPartitionDraft(x => ({ ...x, allocationUnit: Number(e.target.value) }))}>
          {[4096, 8192, 16384, 32768, 65536].map(x => <option key={x} value={x}>{x / 1024} KiB</option>)}
        </select>
        <input value={partitionDraft.label} onChange={e => setPartitionDraft(x => ({ ...x, label: e.target.value }))} />
      </div>
      <div className="actions"><button className="primary" onClick={preparePartition}>Проверить план</button><button onClick={() => setPartitionDraft(null)}>Закрыть</button></div>
      {partitionPlan && <>
        <div className="metrics">
          <Metric label="Размер нового раздела" value={fmtBytes(partitionPlan.size_bytes)} />
          <Metric label="FS" value={partitionPlan.filesystem} />
          <Metric label="Cluster" value={`${partitionPlan.allocation_unit / 1024} KiB`} />
          <Metric label="Drive" value={partitionPlan.drive_letter ? `${partitionPlan.drive_letter}:` : 'auto'} />
        </div>
        <p className="warning">{partitionPlan.warning}</p>
        <label>Введи: <b>{partitionPlan.confirmation}</b></label>
        <input value={partitionConfirm} onChange={e => setPartitionConfirm(e.target.value)} />
        <button className="danger-button" disabled={partitionConfirm !== partitionPlan.confirmation || !diskByNumber(partitionDraft.diskNumber)?.write_access?.allowed} onClick={executePartition}>Создать и форматировать том</button>
      </>}
    </Panel>}

    {letterDraft && <Panel title="Назначить / изменить букву тома">
      <input maxLength={2} value={letterDraft.driveLetter} onChange={e => { const value = e.target.value.toUpperCase().replace(':', ''); setLetterDraft(x => ({ ...x, driveLetter: value })); setLetterConfirm('') }} />
      {letterDraft.driveLetter && <>
        <label>Введи: <b>{`ASSIGN ${letterDraft.driveLetter}: DISK ${letterDraft.diskNumber} PARTITION ${letterDraft.partitionNumber}`}</b></label>
        <input value={letterConfirm} onChange={e => setLetterConfirm(e.target.value)} />
        <button className="danger-button" disabled={letterConfirm !== `ASSIGN ${letterDraft.driveLetter}: DISK ${letterDraft.diskNumber} PARTITION ${letterDraft.partitionNumber}`} onClick={executeLetter}>Назначить букву</button>
      </>}
    </Panel>}
  </div>
}

export function ScanAdmin({ scanId, setScanId, setError }) {
  const [path, setPath] = useState(localStorage.getItem('scanPath') || 'F:\\')
  const [jobId, setJobId] = useState(localStorage.getItem('scanJobId') || '')
  const [job, setJob] = useState(null)

  useEffect(() => { localStorage.setItem('scanPath', path) }, [path])
  useEffect(() => {
    if (!jobId) return undefined
    localStorage.setItem('scanJobId', jobId)
    let stopped = false
    const poll = async () => {
      try {
        const next = await api(`/api/scans/${jobId}`)
        if (stopped) return
        setJob(next)
        if (TERMINAL_SCAN.has(next.status)) {
          if (next.scan_id) setScanId(String(next.scan_id))
          localStorage.removeItem('scanJobId')
          setJobId('')
        }
      } catch (e) {
        if (!stopped) {
          localStorage.removeItem('scanJobId')
          setJobId('')
          setError(e.message)
        }
      }
    }
    poll()
    const timer = setInterval(poll, 700)
    return () => { stopped = true; clearInterval(timer) }
  }, [jobId, setError, setScanId])

  async function start() {
    try {
      const value = await api('/api/scans', { method: 'POST', body: JSON.stringify({ path }) })
      setJob(value)
      setJobId(value.id)
    } catch (e) { setError(e.message) }
  }

  async function stop() {
    try {
      const value = await api(`/api/scans/${jobId}/cancel`, { method: 'POST', body: '{}' })
      setJob(value)
    } catch (e) { setError(e.message) }
  }

  const running = job && !TERMINAL_SCAN.has(job.status)
  return <div className="stack admin-workbench">
    <Panel title="Read-only Quick Index">
      <div className="workbench-hero">
        <div className="hero-symbol">⌕</div>
        <div className="grow">
          <label>Папка или корень тома</label>
          <input value={path} onChange={e => setPath(e.target.value)} />
          <div className="actions">
            <button className="primary" disabled={running} onClick={start}>Начать обследование</button>
            <button className="stop-button" disabled={!running || !jobId} onClick={stop}>■ Stop</button>
          </div>
        </div>
      </div>
      {job && <>
        <div className="metrics">
          <Metric label="Status" value={job.status} />
          <Metric label="Файлы" value={job.files} />
          <Metric label="Папки" value={job.directories} />
          <Metric label="Объём" value={fmtBytes(job.bytes)} />
        </div>
        <div className="progress-line"><i className={running ? 'running' : ''} /></div>
        {job.current_path && <p className="path">{job.current_path}</p>}
      </>}
      {scanId && <p>Активный индекс: <b>scan {scanId}</b>. Он сохраняется после refresh.</p>}
    </Panel>
  </div>
}

export function StorageBrainAdmin({ scanId, setError, health }) {
  const [root, setRoot] = useState(localStorage.getItem('storageRoot') || 'F:\\Storage')
  const [classes, setClasses] = useState([])
  const [plan, setPlan] = useState(null)
  const [planId, setPlanId] = useState(localStorage.getItem('placementPlanId') || '')
  const [confirmation, setConfirmation] = useState('')
  const [verify, setVerify] = useState('size')
  const [jobId, setJobId] = useState(localStorage.getItem('placementJobId') || '')
  const [job, setJob] = useState(null)

  useEffect(() => { localStorage.setItem('storageRoot', root) }, [root])
  useEffect(() => {
    api('/api/storage/classes').then(x => setClasses(x.classes || [])).catch(e => setError(e.message))
  }, [setError])

  useEffect(() => {
    let active = true
    async function restore() {
      try {
        let value
        if (planId) value = await api(`/api/storage/plans/${planId}`)
        else if (scanId) value = await api(`/api/storage/plans/latest?scan_id=${scanId}`)
        else return
        if (!active) return
        setPlan(value)
        setPlanId(String(value.id))
        localStorage.setItem('placementPlanId', String(value.id))
      } catch {
        if (active && planId) {
          setPlanId('')
          localStorage.removeItem('placementPlanId')
        }
      }
    }
    restore()
    return () => { active = false }
  }, [planId, scanId])

  useEffect(() => {
    if (!jobId) return undefined
    localStorage.setItem('placementJobId', jobId)
    let stopped = false
    const poll = async () => {
      try {
        const next = await api(`/api/storage/jobs/${jobId}`)
        if (stopped) return
        setJob(next)
        if (TERMINAL_PLAN.has(next.status)) {
          localStorage.removeItem('placementJobId')
          setJobId('')
          if (planId) setPlan(await api(`/api/storage/plans/${planId}`))
        }
      } catch (e) {
        if (!stopped) {
          localStorage.removeItem('placementJobId')
          setJobId('')
          setError(e.message)
        }
      }
    }
    poll()
    const timer = setInterval(poll, 700)
    return () => { stopped = true; clearInterval(timer) }
  }, [jobId, planId, setError])

  async function build() {
    try {
      const value = await api('/api/storage/plans', {
        method: 'POST',
        body: JSON.stringify({ scan_id: Number(scanId), storage_root: root }),
      })
      setPlan(value)
      setPlanId(String(value.id))
      localStorage.setItem('placementPlanId', String(value.id))
      setConfirmation('')
    } catch (e) { setError(e.message) }
  }

  async function apply() {
    try {
      const value = await api(`/api/storage/plans/${plan.id}/apply-job`, {
        method: 'POST',
        body: JSON.stringify({ confirmation, verify }),
      })
      setJob(value)
      setJobId(value.id)
    } catch (e) { setError(e.message) }
  }

  async function stop() {
    try {
      setJob(await api(`/api/storage/jobs/${jobId}/cancel`, { method: 'POST', body: '{}' }))
    } catch (e) { setError(e.message) }
  }

  const running = job && !TERMINAL_PLAN.has(job.status)
  return <div className="stack admin-workbench">
    <Panel title="Storage policy classes">
      <div className="class-grid">{classes.map(c => <div key={c.key}><b>{c.title}</b><small>{c.relative_root}</small><p>{c.description}</p></div>)}</div>
    </Panel>
    <Panel title="Placement Planner">
      <div className="planner-toolbar">
        <div className="grow"><label>Корень управляемого хранилища</label><input value={root} onChange={e => setRoot(e.target.value)} /></div>
        <button className="primary" disabled={!scanId || running} onClick={build}>Построить план из scan {scanId || '—'}</button>
      </div>
      <p className="muted">Scan = снимок фактов о файлах. Placement Plan = сохранённое в SQLite предложение, куда эти файлы должны попасть. Последний plan автоматически восстанавливается после refresh.</p>
      {plan && <>
        <div className="metrics">
          <Metric label="Plan" value={`#${plan.id} · ${plan.status}`} />
          <Metric label="Items" value={plan.total_items} />
          <Metric label="Данные" value={fmtBytes(plan.total_bytes)} />
          <Metric label="Рабочий резерв" value={fmtBytes(plan.reserve_bytes)} />
        </div>
        {plan.warnings?.map(w => <p className="warning" key={w}>{w}</p>)}
        <div className="plan">{plan.items?.slice(0, 120).map(i => <div key={i.id} className={i.status}><span title={i.source_path}>{i.source_path}</span><b>→ {i.target_class}</b><span>{i.action}</span><span>{fmtBytes(i.size)}</span></div>)}</div>
        <div className="apply-box">
          <p><b>Same-volume:</b> atomic move + journal. <b>Cross-volume:</b> chunked copy → verify → publish; исходник сохраняется.</p>
          <select value={verify} onChange={e => setVerify(e.target.value)}><option value="size">Verify size</option><option value="sha256">Verify SHA-256</option></select>
          <label>Для применения введи: <b>{plan.confirmation}</b></label>
          <input value={confirmation} onChange={e => setConfirmation(e.target.value)} />
          <div className="actions">
            <button className="primary" disabled={!health?.safety?.file_writes || confirmation !== plan.confirmation || running} onClick={apply}>Запустить применение</button>
            <button className="stop-button" disabled={!running || !jobId} onClick={stop}>■ Stop</button>
          </div>
          {!health?.safety?.file_writes && <small>DS_ALLOW_FILE_WRITES=0 — file execution заблокирован; построение плана работает.</small>}
        </div>
      </>}
      {job && <div className="job-strip">
        <StatusPill tone={job.status === 'completed' ? 'good' : job.status === 'failed' ? 'danger' : 'neutral'}>{job.status}</StatusPill>
        <span>{job.completed || 0}/{job.total || 0} completed</span>
        <span>{job.failed || 0} failed</span>
        <span>{job.copied || 0} copied</span>
        <span>{job.moved || 0} moved</span>
      </div>}
    </Panel>
  </div>
}

export function RecoveryAdmin({ setError }) {
  const [inventory, setInventory] = useState([])
  const [snapshots, setSnapshots] = useState([])
  const [probe, setProbe] = useState(null)

  const refresh = async () => {
    const [inv, history] = await Promise.all([
      api('/api/recovery/inventory'),
      api('/api/recovery/snapshots'),
    ])
    setInventory(inv.disks || [])
    setSnapshots(history.snapshots || [])
  }

  useEffect(() => { refresh().catch(e => setError(e.message)) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function snapshot() {
    try { await api('/api/recovery/snapshots', { method: 'POST', body: '{}' }); await refresh() }
    catch (e) { setError(e.message) }
  }

  async function signatures(number) {
    try { setProbe(await api(`/api/recovery/disks/${number}/signatures`)) }
    catch (e) { setError(e.message) }
  }

  return <div className="stack admin-workbench">
    <Panel title="Recovery / Forensics · read-only">
      <p>Этот раздел ничего не восстанавливает и ничего не записывает. Он сохраняет снимки topology и читает MBR/GPT + boot-sector signatures — основу для будущего recovery workflow.</p>
      <div className="actions"><button className="primary" onClick={snapshot}>Сохранить snapshot дисков/разделов/томов</button></div>
      <div className="snapshot-list">{snapshots.map(s => <div key={s.id}><b>Snapshot #{s.id}</b><span>{s.created_at}</span><span>{s.disk_count} disks</span></div>)}</div>
    </Panel>
    {inventory.map(d => <Panel key={d.number} title={`Disk ${d.number} · ${d.friendly_name}`}>
      <div className="metrics"><Metric label="Style" value={d.partition_style} /><Metric label="Size" value={fmtBytes(d.size)} /><Metric label="Allocated" value={fmtBytes(d.allocated_size)} /><Metric label="Largest free extent" value={fmtBytes(d.largest_free_extent)} /></div>
      <div className="actions"><button onClick={() => signatures(d.number)}>Read raw signatures</button></div>
      <div className="partition-table">{(d.partitions || []).map(p => <div key={p.partition_number}><span>#{p.partition_number}</span><b>{p.drive_letter || '—'}</b><span>{p.filesystem || 'unknown'}</span><span>{fmtBytes(p.size)}</span><span>{p.gpt_type || p.mbr_type || p.type}</span></div>)}</div>
    </Panel>)}
    {probe && <Panel title={`Signature probe · Disk ${probe.disk_number}`}>
      {probe.error && <p className="warning">{probe.error}</p>}
      <div className="metrics"><Metric label="Raw readable" value={probe.readable ? 'yes' : 'no'} /><Metric label="MBR 55AA" value={probe.mbr_signature ? 'present' : 'not seen'} /><Metric label="GPT header" value={probe.gpt_header ? 'EFI PART' : 'not seen'} /><Metric label="Partitions" value={probe.partitions?.length || 0} /></div>
      <div className="snapshot-list">{probe.partitions?.map(p => <div key={p.partition_number}><b>#{p.partition_number}</b><span>reported: {p.reported_filesystem || '—'}</span><span>signature: {p.signature_filesystem || '—'}</span></div>)}</div>
    </Panel>}
  </div>
}

export function SecurityAdmin({ setError }) {
  const [engines, setEngines] = useState([])
  const [engine, setEngine] = useState('auto')
  const [path, setPath] = useState(localStorage.getItem('securityPath') || 'F:\\')
  const [jobId, setJobId] = useState(localStorage.getItem('securityJobId') || '')
  const [job, setJob] = useState(null)
  const [results, setResults] = useState([])

  const terminal = useMemo(() => new Set(['clean', 'threats_found', 'error', 'cancelled']), [])

  const refresh = async () => {
    const [caps, history] = await Promise.all([api('/api/security/engines'), api('/api/security/results')])
    setEngines(caps.engines || [])
    setResults(history.results || [])
  }

  useEffect(() => { refresh().catch(e => setError(e.message)) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { localStorage.setItem('securityPath', path) }, [path])

  useEffect(() => {
    if (!jobId) return undefined
    localStorage.setItem('securityJobId', jobId)
    let stopped = false
    const poll = async () => {
      try {
        const next = await api(`/api/security/scans/${jobId}`)
        if (stopped) return
        setJob(next)
        if (terminal.has(next.status)) {
          localStorage.removeItem('securityJobId')
          setJobId('')
          refresh().catch(() => {})
        }
      } catch (e) {
        if (!stopped) {
          localStorage.removeItem('securityJobId')
          setJobId('')
          setError(e.message)
        }
      }
    }
    poll()
    const timer = setInterval(poll, 800)
    return () => { stopped = true; clearInterval(timer) }
  }, [jobId, setError, terminal])

  async function start() {
    try {
      const value = await api('/api/security/scans', { method: 'POST', body: JSON.stringify({ path, engine }) })
      setJob(value)
      setJobId(value.id)
    } catch (e) { setError(e.message) }
  }

  async function stop() {
    try { setJob(await api(`/api/security/scans/${jobId}/cancel`, { method: 'POST', body: '{}' })) }
    catch (e) { setError(e.message) }
  }

  const running = job && !terminal.has(job.status)
  return <div className="stack admin-workbench">
    <Panel title="Local malware scan · no remediation">
      <p>DiskShell использует установленный Microsoft Defender или ClamAV. Облако не требуется; этот раздел только сканирует и не удаляет найденные файлы.</p>
      <div className="engine-grid">{engines.map(e => <div key={e.id} className={e.available ? 'available' : 'unavailable'}><b>{e.title}</b><span>{e.available ? 'available' : 'not installed'}</span><small>{e.path || '—'}</small></div>)}</div>
      <label>Файл или каталог</label>
      <input value={path} onChange={e => setPath(e.target.value)} />
      <select value={engine} onChange={e => setEngine(e.target.value)}>
        <option value="auto">Auto</option>
        {engines.filter(e => e.available).map(e => <option key={e.id} value={e.id}>{e.title}</option>)}
      </select>
      <div className="actions"><button className="primary" disabled={running} onClick={start}>Scan</button><button className="stop-button" disabled={!running || !jobId} onClick={stop}>■ Stop</button></div>
      {job && <>
        <div className="metrics"><Metric label="Engine" value={job.engine_title} /><Metric label="Status" value={job.status} /><Metric label="Threats" value={job.threats ?? '—'} /><Metric label="Exit" value={job.exit_code ?? '—'} /></div>
        {job.output && <pre className="security-output">{job.output}</pre>}
      </>}
    </Panel>
    <Panel title="Последние результаты">
      <div className="snapshot-list">{results.map(r => <div key={r.id}><b>{r.status}</b><span>{r.engine}</span><span title={r.path}>{r.path}</span><span>{r.threats ?? '—'} threats</span></div>)}</div>
    </Panel>
  </div>
}


function AdminFilePane({ title, side, state, setState, load, choose, busy }) {
  return <Panel title={title} className="pane">
    <div className="file-toolbar">
      <button disabled={!state.data?.parent || busy} onClick={() => state.data?.parent && load(side, state.data.parent)}>↑</button>
      <input value={state.path} onChange={e => setState(x => ({ ...x, path: e.target.value }))} />
      <button disabled={busy} onClick={() => load(side, state.path)}>Open</button>
    </div>
    <div className="file-list">
      {state.data?.items?.slice(0, 1500).map(item => <button
        key={item.path}
        className={state.selected?.path === item.path ? 'selected' : ''}
        onClick={() => choose(side, item)}
        onDoubleClick={() => item.is_dir && !busy && load(side, item.path)}
      >
        <span>{item.is_dir ? '📁' : '📄'} {item.name}</span>
        <span>{item.is_dir ? '' : fmtBytes(item.size)}</span>
      </button>)}
    </div>
  </Panel>
}

export function FilesAdmin({ health, setError }) {
  const [left, setLeft] = useState({
    path: localStorage.getItem('fileLeftPath') || 'F:\\',
    data: null,
    selected: null,
  })
  const [right, setRight] = useState({
    path: localStorage.getItem('fileRightPath') || 'F:\\',
    data: null,
    selected: null,
  })
  const [jobId, setJobId] = useState(localStorage.getItem('fileJobId') || '')
  const [job, setJob] = useState(null)

  async function load(side, path) {
    try {
      const data = await api(`/api/files?path=${encodeURIComponent(path)}`)
      const next = { path: data.path, data, selected: null }
      if (side === 'left') {
        setLeft(next)
        localStorage.setItem('fileLeftPath', data.path)
      } else {
        setRight(next)
        localStorage.setItem('fileRightPath', data.path)
      }
    } catch (e) { setError(e.message) }
  }

  function choose(side, item) {
    if (side === 'left') setLeft(x => ({ ...x, selected: item }))
    else setRight(x => ({ ...x, selected: item }))
  }

  useEffect(() => {
    load('left', left.path)
    load('right', right.path)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!jobId) return undefined
    localStorage.setItem('fileJobId', jobId)
    let stopped = false
    const poll = async () => {
      try {
        const next = await api(`/api/files/jobs/${jobId}`)
        if (stopped) return
        setJob(next)
        if (['completed', 'failed', 'cancelled'].includes(next.status)) {
          localStorage.removeItem('fileJobId')
          setJobId('')
          await Promise.all([load('left', left.path), load('right', right.path)])
        }
      } catch (e) {
        if (!stopped) {
          localStorage.removeItem('fileJobId')
          setJobId('')
          setError(e.message)
        }
      }
    }
    poll()
    const timer = setInterval(poll, 650)
    return () => { stopped = true; clearInterval(timer) }
  }, [jobId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function transfer(operation, sourcePane, destinationPane) {
    if (!sourcePane.selected) return
    const destination = joinPath(destinationPane.path, sourcePane.selected.name)
    try {
      const value = await api('/api/files/jobs', {
        method: 'POST',
        body: JSON.stringify({
          operation,
          source: sourcePane.selected.path,
          destination,
        }),
      })
      setJob(value)
      setJobId(value.id)
    } catch (e) { setError(e.message) }
  }

  async function stop() {
    try {
      setJob(await api(`/api/files/jobs/${jobId}/cancel`, { method: 'POST', body: '{}' }))
    } catch (e) { setError(e.message) }
  }

  async function trash(side, sideName) {
    if (!side.selected) return
    try {
      await api('/api/files/trash', {
        method: 'POST',
        body: JSON.stringify({ path: side.selected.path }),
      })
      await load(sideName, side.path)
    } catch (e) { setError(e.message) }
  }

  const busy = Boolean(jobId && job && !['completed', 'failed', 'cancelled'].includes(job.status))
  return <div className="stack admin-workbench">
    <div className="file-manager">
      <AdminFilePane title="LEFT" side="left" state={left} setState={setLeft} load={load} choose={choose} busy={busy} />
      <div className="file-actions">
        <button disabled={!health?.safety?.file_writes || !left.selected || busy} onClick={() => transfer('copy', left, right)}>Copy →</button>
        <button disabled={!health?.safety?.file_writes || !left.selected || busy} onClick={() => transfer('move', left, right)}>Move →</button>
        <button disabled={!health?.safety?.file_writes || !right.selected || busy} onClick={() => transfer('copy', right, left)}>← Copy</button>
        <button disabled={!health?.safety?.file_writes || !right.selected || busy} onClick={() => transfer('move', right, left)}>← Move</button>
        <button className="stop-button" disabled={!busy || !jobId} onClick={stop}>■ Stop</button>
        <button className="trash" disabled={!health?.safety?.file_writes || busy || (!left.selected && !right.selected)} onClick={() => left.selected ? trash(left, 'left') : trash(right, 'right')}>Trash</button>
      </div>
      <AdminFilePane title="RIGHT" side="right" state={right} setState={setRight} load={load} choose={choose} busy={busy} />
    </div>

    <Panel title="File operation job">
      {!job && <p className="muted">Copy/Move запускаются в background job. Для больших операций доступен Stop.</p>}
      {job && <>
        <div className="metrics">
          <Metric label="Operation" value={job.operation} />
          <Metric label="Status" value={job.status} />
          <Metric label="Files" value={job.files} />
          <Metric label="Copied" value={fmtBytes(job.bytes)} />
        </div>
        <div className="progress-line"><i className={busy ? 'running' : ''} /></div>
        <p className="path">{job.current_path}</p>
        {job.error && <p className="warning">{job.error}</p>}
        {job.status === 'cancelled' && <p className="muted">Операция остановлена; временный/новый target очищен. Исходник сохранён.</p>}
      </>}
      {!health?.safety?.file_writes && <small>DS_ALLOW_FILE_WRITES=0 — Copy/Move/Trash заблокированы.</small>}
    </Panel>
  </div>
}
