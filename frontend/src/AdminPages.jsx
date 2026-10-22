import React, { useEffect, useMemo, useState } from 'react'
import { api, fmtBytes, joinPath, thumbnailUrl } from './api.js'

function Panel({ title, children, className = '' }) {
  return <section className={`card admin-panel ${className}`}><h3>{title}</h3>{children}</section>
}

function Metric({ label, value }) {
  return <div><small>{label}</small><b>{value}</b></div>
}

function StatusPill({ children, tone = 'neutral' }) {
  return <span className={`status-pill ${tone}`}>{children}</span>
}

function JobProgress({ percent = null, running = false, label = '' }) {
  const known = percent !== null && percent !== undefined && Number.isFinite(Number(percent))
  const value = known ? Math.max(0, Math.min(100, Number(percent))) : null
  return <div className="job-progress">
    <div className={`progress-track ${known ? 'determinate' : 'indeterminate'}`}>
      <i
        className={running ? 'running' : ''}
        style={known ? { width: `${value}%` } : undefined}
      />
    </div>
    <div className="progress-caption">
      <span>{label}</span>
      <b>{known ? `${value.toFixed(value < 10 ? 1 : 0)}%` : (running ? 'процент неизвестен' : '')}</b>
    </div>
  </div>
}

function diskSegments(disk) {
  const size = Number(disk?.size || 0)
  if (!size) return []
  if (String(disk.partition_style).toUpperCase() === 'RAW') {
    return [{ key: 'raw', kind: 'free', size, label: 'RAW / Unallocated' }]
  }

  const partitions = [...(disk.partitions || [])]
    .filter(item => Number(item.size || 0) > 0)
    .sort((a, b) => Number(a.offset || 0) - Number(b.offset || 0))

  const result = []
  let cursor = 0
  for (const partition of partitions) {
    const offset = Math.max(0, Number(partition.offset || 0))
    if (offset > cursor) {
      result.push({
        key: `free-${cursor}`,
        kind: 'free',
        size: offset - cursor,
        label: 'Unallocated',
      })
    }
    result.push({
      key: `partition-${partition.partition_number}`,
      kind: 'partition',
      size: Number(partition.size || 0),
      label: `${partition.drive_letter || `#${partition.partition_number}`} · ${partition.filesystem || 'RAW volume'}`,
    })
    cursor = Math.max(cursor, offset + Number(partition.size || 0))
  }
  if (cursor < size) {
    result.push({ key: `free-${cursor}`, kind: 'free', size: size - cursor, label: 'Unallocated' })
  }
  return result
}

function DiskLayoutBar({ disk }) {
  const segments = diskSegments(disk)
  const total = Number(disk?.size || 1)
  return <div className="disk-layout">
    <div className="disk-layout-bar">
      {segments.map(segment => {
        const percent = Math.max(0.15, segment.size * 100 / total)
        return <div
          key={segment.key}
          className={`disk-segment ${segment.kind}`}
          style={{ flexBasis: `${percent}%` }}
          title={`${segment.label} · ${fmtBytes(segment.size)} · ${(segment.size * 100 / total).toFixed(2)}%`}
        >
          {percent >= 8 && <span>{segment.label}</span>}
        </div>
      })}
    </div>
    <div className="disk-layout-legend">
      {segments.filter(segment => segment.size / total >= 0.001).map(segment => <span key={`legend-${segment.key}`}>
        <i className={segment.kind} /> {segment.label}: <b>{fmtBytes(segment.size)}</b>
      </span>)}
    </div>
  </div>
}

function gibToBytes(value) {
  if (value === '' || value === null || value === undefined) return null
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) throw new Error('Размер тома должен быть положительным числом GiB')
  return Math.floor(number * 1024 ** 3)
}

const TERMINAL_SCAN = new Set(['completed', 'failed', 'cancelled'])
const TERMINAL_PLAN = new Set(['completed', 'partial', 'failed', 'blocked', 'cancelled'])

export function DisksAdmin({ setError }) {
  const [data, setData] = useState(null)
  const [capabilities, setCapabilities] = useState({ filesystems: [], process_elevated: null })
  const [unlockPlan, setUnlockPlan] = useState(null)
  const [unlockConfirm, setUnlockConfirm] = useState('')
  const [formatPlan, setFormatPlan] = useState(null)
  const [formatDirty, setFormatDirty] = useState(false)
  const [formatConfirm, setFormatConfirm] = useState('')
  const [fs, setFs] = useState('NTFS')
  const [cluster, setCluster] = useState(16384)
  const [label, setLabel] = useState('Storage')
  const [formatSizeGiB, setFormatSizeGiB] = useState('')
  const [formatDriveLetter, setFormatDriveLetter] = useState('')
  const [partitionDraft, setPartitionDraft] = useState(null)
  const [partitionPlan, setPartitionPlan] = useState(null)
  const [partitionConfirm, setPartitionConfirm] = useState('')
  const [initializePlan, setInitializePlan] = useState(null)
  const [initializeConfirm, setInitializeConfirm] = useState('')
  const [letterDraft, setLetterDraft] = useState(null)
  const [letterConfirm, setLetterConfirm] = useState('')
  const [diskBusy, setDiskBusy] = useState(null)
  const [diskNotice, setDiskNotice] = useState('')

  const reload = () => api('/api/disks').then(setData).catch(e => setError(e.message))
  useEffect(() => {
    Promise.all([api('/api/disks'), api('/api/disks/capabilities')])
      .then(([disks, caps]) => { setData(disks); setCapabilities(caps) })
      .catch(e => setError(e.message))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const filesystemProfile = key => capabilities.filesystems?.find(item => item.key === key)
  const elevated = capabilities.process_elevated === true
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
      const sizeBytes = gibToBytes(formatSizeGiB)
      const value = await api(`/api/disks/${number}/format-plan`, {
        method: 'POST',
        body: JSON.stringify({
          filesystem: fs,
          label,
          allocation_unit: cluster,
          size_bytes: sizeBytes,
          drive_letter: formatDriveLetter || null,
        }),
      })
      setFormatPlan(value)
      setFormatDirty(false)
      setFormatConfirm('')
    } catch (e) { setError(e.message) }
  }

  async function executeFormat() {
    setDiskBusy({ diskNumber: formatPlan.disk.number, phase: 'format', label: 'Форматирование тома. Не отключай диск.' })
    try {
      await api(`/api/disks/${formatPlan.disk.number}/format`, {
        method: 'POST',
        body: JSON.stringify({
          filesystem: fs,
          label,
          allocation_unit: cluster,
          size_bytes: formatPlan.use_maximum ? null : formatPlan.size_bytes,
          drive_letter: formatDriveLetter || null,
          confirmation: formatConfirm,
        }),
      })
      setFormatPlan(null)
      setFormatDirty(false)
      setDiskNotice(`Disk ${formatPlan.disk.number}: том создан и отформатирован.`)
      await reload()
    } catch (e) { setError(e.message) }
    finally { setDiskBusy(null) }
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
    setDiskBusy({ diskNumber: initializePlan.disk.number, phase: 'initialize', label: 'Windows создаёт таблицу разделов GPT. Не отключай диск.' })
    try {
      await api(`/api/disks/${initializePlan.disk.number}/initialize`, {
        method: 'POST',
        body: JSON.stringify({ partition_style: 'GPT', confirmation: initializeConfirm }),
      })
      const diskNumber = initializePlan.disk.number
      setInitializePlan(null)
      setFormatPlan(null)
      setPartitionPlan(null)
      setDiskNotice(`Disk ${diskNumber}: GPT создан. Теперь создай раздел / том.`)
      await reload()
    } catch (e) { setError(e.message) }
    finally { setDiskBusy(null) }
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
    try {
      const sizeBytes = gibToBytes(partitionDraft.sizeGiB)
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
    setDiskBusy({ diskNumber: partitionDraft.diskNumber, phase: 'partition', label: 'Windows создаёт раздел и форматирует том. Не отключай диск.' })
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
      const diskNumber = partitionDraft.diskNumber
      setPartitionDraft(null)
      setPartitionPlan(null)
      setDiskNotice(`Disk ${diskNumber}: раздел и файловая система созданы.`)
      await reload()
    } catch (e) { setError(e.message) }
    finally { setDiskBusy(null) }
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
    setDiskBusy({ diskNumber: letterDraft.diskNumber, phase: 'letter', label: 'Windows назначает букву тома.' })
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
    finally { setDiskBusy(null) }
    return expected
  }

  return <div className="stack admin-workbench">
    {capabilities.process_elevated === false && <div className="elevation-warning">
      <b>Backend запущен без Administrator privileges.</b>
      <span>Просмотр работает, но Initialize / partition / format Windows заблокирует. Перезапусти PowerShell/Terminal «Запуск от имени администратора» и снова запусти backend.</span>
    </div>}
    {diskNotice && <div className="disk-success-toast">
      <span>{diskNotice}</span><button onClick={() => setDiskNotice('')}>×</button>
    </div>}
    {diskBusy && <div className="disk-operation-toast">
      <b>Disk {diskBusy.diskNumber} · storage operation</b>
      <JobProgress running label={diskBusy.label} />
      <small>Внутренний процент Windows не сообщает. Не отключай диск и не закрывай backend до завершения этапа.</small>
    </div>}
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
          <span>Largest free extent: <b>{String(d.partition_style).toUpperCase() === 'RAW' ? 'после Initialize' : fmtBytes(d.largest_free_extent)}</b></span>
        </div>
        <DiskLayoutBar disk={d} />
        {!d.protected && <div className="raw-stepper">
          <div className={write.allowed ? 'done' : 'current'}>
            <b>1</b><span><strong>Разблокировать запись</strong><small>{write.allowed ? 'Готово' : 'Нужно временно разблокировать выбранный диск'}</small></span>
          </div>
          <div className={String(d.partition_style).toUpperCase() !== 'RAW' ? 'done' : (write.allowed ? 'current' : '')}>
            <b>2</b><span><strong>Initialize GPT</strong><small>{String(d.partition_style).toUpperCase() !== 'RAW' ? 'GPT создан' : 'Создать только таблицу разделов'}</small></span>
          </div>
          <div className={(d.partitions || []).length > 0 ? 'done' : (String(d.partition_style).toUpperCase() !== 'RAW' ? 'current' : '')}>
            <b>3</b><span><strong>Раздел + файловая система</strong><small>{(d.partitions || []).length > 0 ? 'Том создан' : 'Выбрать размер, NTFS и cluster size'}</small></span>
          </div>
        </div>}

        {d.protected
          ? <p className="protected">🔒 {d.protection_reasons.join(', ')}</p>
          : <div className="actions">
              {!write.allowed && <button className="unlock-button" disabled={Boolean(diskBusy)} onClick={() => prepareUnlock(d)}>Разблокировать только этот диск</button>}
              {write.allowed && <button disabled={Boolean(diskBusy)} onClick={() => lock(d.number)}>🔒 Заблокировать запись</button>}
              {String(d.partition_style).toUpperCase() === 'RAW' && <button disabled={Boolean(diskBusy) || !elevated} title={!elevated ? 'Backend должен быть запущен от администратора' : ''} onClick={() => prepareInitialize(d.number)}>Инициализировать GPT</button>}
              {Number(d.largest_free_extent || 0) > 0 && String(d.partition_style).toUpperCase() !== 'RAW' && <button disabled={Boolean(diskBusy) || !elevated} title={!elevated ? 'Backend должен быть запущен от администратора' : ''} onClick={() => newPartition(d)}>+ Раздел / том</button>}
              {String(d.partition_style).toUpperCase() !== 'RAW' && <button className="danger-outline" disabled={Boolean(diskBusy) || !elevated} title={!elevated ? 'Backend должен быть запущен от администратора' : ''} onClick={() => prepareFormat(d.number)}>
                Очистить + первый том
              </button>}
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

    {initializePlan && <Panel title="Инициализировать таблицу разделов" className="danger-card">
      <p className="warning">{initializePlan.warning}</p>
      <p className="muted">Эта операция создаёт GPT, но не создаёт том. После неё DiskShell покажет реальное нераспределённое пространство и кнопку «+ Раздел / том», где выбирается размер.</p>
      <label>Введи: <b>{initializePlan.confirmation}</b></label>
      <input value={initializeConfirm} onChange={e => setInitializeConfirm(e.target.value)} />
      <button className="danger-button" disabled={Boolean(diskBusy) || !elevated || initializeConfirm !== initializePlan.confirmation || !diskByNumber(initializePlan.disk.number)?.write_access?.allowed} onClick={executeInitialize}>Initialize GPT</button>
    </Panel>}

    {formatPlan && String(formatPlan.disk.partition_style).toUpperCase() !== 'RAW' && <Panel
      title="Очистить диск → GPT → создать первый том"
      className="danger-card"
    >
      <p className="warning">⚠ {formatPlan.warning}</p>
      <div className="wizard-grid">
        <div>
          <label>Файловая система</label>
          <select value={fs} onChange={e => {
            const next = e.target.value
            setFs(next)
            const profile = filesystemProfile(next)
            if (profile?.recommended_cluster) setCluster(profile.recommended_cluster)
            setFormatDirty(true)
          }}>
            {(capabilities.filesystems || []).map(item => <option key={item.key} value={item.key}>{item.title}</option>)}
          </select>
        </div>
        <div>
          <label>Cluster / allocation unit</label>
          <select value={cluster} onChange={e => { setCluster(Number(e.target.value)); setFormatDirty(true) }}>
            {(filesystemProfile(fs)?.clusters || [4096, 16384, 65536]).map(x => <option key={x} value={x}>{x < 1024 ** 2 ? `${x / 1024} KiB` : `${x / 1024 ** 2} MiB`}</option>)}
          </select>
        </div>
        <div>
          <label>Метка тома</label>
          <input value={label} onChange={e => { setLabel(e.target.value); setFormatDirty(true) }} />
        </div>
        <div>
          <label>Размер первого тома, GiB</label>
          <input placeholder="пусто = максимум" value={formatSizeGiB} onChange={e => { setFormatSizeGiB(e.target.value); setFormatDirty(true) }} />
        </div>
        <div>
          <label>Буква</label>
          <input maxLength={2} placeholder="auto" value={formatDriveLetter} onChange={e => { setFormatDriveLetter(e.target.value.toUpperCase().replace(':', '')); setFormatDirty(true) }} />
        </div>
      </div>
      <div className="preset-hint">
        <b>{filesystemProfile(fs)?.title || fs}</b> · {filesystemProfile(fs)?.warning || 'Windows проверит поддержку перед форматированием.'}
      </div>
      {formatDirty && <div className="plan-stale">
        <span>Параметры изменены. Перед destructive execution пересчитай план.</span>
        <button disabled={Boolean(diskBusy)} onClick={() => prepareFormat(formatPlan.disk.number)}>Пересчитать план</button>
      </div>}
      <div className="metrics">
        <Metric label="Первый том" value={formatPlan.use_maximum ? 'максимальный доступный' : fmtBytes(formatPlan.size_bytes)} />
        <Metric label="Остаток" value={formatPlan.use_maximum ? '0 / служебный GPT резерв' : 'останется Unallocated'} />
        <Metric label="FS" value={formatPlan.filesystem} />
        <Metric label="Cluster" value={formatPlan.allocation_unit < 1024 ** 2 ? `${formatPlan.allocation_unit / 1024} KiB` : `${formatPlan.allocation_unit / 1024 ** 2} MiB`} />
      </div>
      {(formatPlan.warnings || []).slice(1).map(item => <p className="muted" key={item}>• {item}</p>)}
      <label>Для выполнения введи: <b>{formatPlan.confirmation}</b></label>
      <input value={formatConfirm} onChange={e => setFormatConfirm(e.target.value)} />
      <button className="danger-button" disabled={Boolean(diskBusy) || !elevated || formatDirty || formatConfirm !== formatPlan.confirmation || !diskByNumber(formatPlan.disk.number)?.write_access?.allowed} onClick={executeFormat}>Очистить и создать том</button>
    </Panel>}

    {partitionDraft && <Panel title={`Создать раздел / том на Disk ${partitionDraft.diskNumber}`}>
      <div className="grid two">
        <div>
          <label>Размер, GiB (пусто = всё максимальное свободное место)</label>
          <input value={partitionDraft.sizeGiB} onChange={e => { setPartitionDraft(x => ({ ...x, sizeGiB: e.target.value })); setPartitionPlan(null) }} />
        </div>
        <div>
          <label>Буква (пусто = Windows назначит автоматически)</label>
          <input maxLength={2} value={partitionDraft.driveLetter} onChange={e => { setPartitionDraft(x => ({ ...x, driveLetter: e.target.value })); setPartitionPlan(null) }} />
        </div>
      </div>
      <div className="form-row">
        <select value={partitionDraft.filesystem} onChange={e => {
          const next = e.target.value
          const profile = filesystemProfile(next)
          setPartitionDraft(x => ({
            ...x,
            filesystem: next,
            allocationUnit: profile?.recommended_cluster || x.allocationUnit,
          }))
          setPartitionPlan(null)
        }}>
          {(capabilities.filesystems || []).map(item => <option key={item.key} value={item.key}>{item.title}</option>)}
        </select>
        <select value={partitionDraft.allocationUnit} onChange={e => { setPartitionDraft(x => ({ ...x, allocationUnit: Number(e.target.value) })); setPartitionPlan(null) }}>
          {(filesystemProfile(partitionDraft.filesystem)?.clusters || [4096, 16384, 65536]).map(x => <option key={x} value={x}>{x < 1024 ** 2 ? `${x / 1024} KiB` : `${x / 1024 ** 2} MiB`}</option>)}
        </select>
        <input value={partitionDraft.label} onChange={e => { setPartitionDraft(x => ({ ...x, label: e.target.value })); setPartitionPlan(null) }} />
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
        <button className="danger-button" disabled={Boolean(diskBusy) || !elevated || partitionConfirm !== partitionPlan.confirmation || !diskByNumber(partitionDraft.diskNumber)?.write_access?.allowed} onClick={executePartition}>Создать и форматировать том</button>
      </>}
    </Panel>}

    {letterDraft && <Panel title="Назначить / изменить букву тома">
      <input maxLength={2} value={letterDraft.driveLetter} onChange={e => { const value = e.target.value.toUpperCase().replace(':', ''); setLetterDraft(x => ({ ...x, driveLetter: value })); setLetterConfirm('') }} />
      {letterDraft.driveLetter && <>
        <label>Введи: <b>{`ASSIGN ${letterDraft.driveLetter}: DISK ${letterDraft.diskNumber} PARTITION ${letterDraft.partitionNumber}`}</b></label>
        <input value={letterConfirm} onChange={e => setLetterConfirm(e.target.value)} />
        <button className="danger-button" disabled={Boolean(diskBusy) || letterConfirm !== `ASSIGN ${letterDraft.driveLetter}: DISK ${letterDraft.diskNumber} PARTITION ${letterDraft.partitionNumber}`} onClick={executeLetter}>Назначить букву</button>
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
        <JobProgress running={running} label="Идёт обход файловой системы; заранее неизвестно, сколько объектов встретится." />
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
  const [sourceScope, setSourceScope] = useState(localStorage.getItem('storageSourceScope') || '')
  const [excludeScope, setExcludeScope] = useState(localStorage.getItem('storageExcludeScope') || '')

  useEffect(() => { localStorage.setItem('storageRoot', root) }, [root])
  useEffect(() => { localStorage.setItem('storageSourceScope', sourceScope) }, [sourceScope])
  useEffect(() => { localStorage.setItem('storageExcludeScope', excludeScope) }, [excludeScope])
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
    const splitPaths = value => value
      .split(/\r?\n|;/)
      .map(item => item.trim())
      .filter(Boolean)
    try {
      const value = await api('/api/storage/plans', {
        method: 'POST',
        body: JSON.stringify({
          scan_id: Number(scanId),
          storage_root: root,
          source_roots: splitPaths(sourceScope),
          exclude_roots: splitPaths(excludeScope),
        }),
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
    <Panel title="Managed Import / Placement Planner">
      <div className="managed-import-grid">
        <div>
          <label>Целевой HDD root</label>
          <input value={root} onChange={e => setRoot(e.target.value)} placeholder="G:\\Storage" />
          <small>Сюда DiskShell создаст Media / Photos / Archive / Documents / ...</small>
        </div>
        <div>
          <label>Source scope на SSD · по одному пути в строке</label>
          <textarea value={sourceScope} onChange={e => setSourceScope(e.target.value)} placeholder={'F:\\fromDisk\nF:\\inst'} />
          <small>Пусто = весь scan. Лучше явно выбрать только тот хаос, который переносим.</small>
        </div>
        <div>
          <label>Exclude scope · по одному пути в строке</label>
          <textarea value={excludeScope} onChange={e => setExcludeScope(e.target.value)} placeholder={'F:\\work\nF:\\VM-active'} />
          <small>DiskShell и target Storage backend исключает автоматически.</small>
        </div>
      </div>
      <div className="actions">
        <button className="primary" disabled={!scanId || running || !root.trim()} onClick={build}>Построить Managed Import из scan {scanId || '—'}</button>
      </div>
      <p className="muted">Scan остаётся общим снимком SSD. Этот plan берёт только Source scope, классифицирует данные и готовит перенос в HDD-папки. Cross-volume сейчас безопасно copy → verify → publish, исходник на SSD сохраняется до ручной проверки.</p>
      {plan && <>
        <div className="metrics">
          <Metric label="Plan" value={`#${plan.id} · ${plan.status}`} />
          <Metric label="Items" value={plan.total_items} />
          <Metric label="Данные" value={fmtBytes(plan.total_bytes)} />
          <Metric label="Рабочий резерв" value={fmtBytes(plan.reserve_bytes)} />
          <Metric label="SSD → HDD" value={plan.cross_volume_items ?? 0} />
          <Metric label="Внутри тома" value={plan.same_volume_items ?? 0} />
          <Metric label="Нужно на HDD" value={fmtBytes(plan.additional_target_bytes || 0)} />
        </div>
        {plan.scope && <div className="scope-summary">
          <span>В scope: <b>{plan.scope.selected_files}</b></span>
          <span>Вне scope: <b>{plan.scope.skipped_outside_scope}</b></span>
          <span>Excluded: <b>{plan.scope.skipped_excluded}</b></span>
        </div>}
        {plan.warnings?.map(w => <p className="warning" key={w}>{w}</p>)}
        <div className="plan managed-plan">{plan.items?.slice(0, 120).map(i => <div key={i.id} className={i.status}>
          <span title={i.source_path}>{i.source_path}</span>
          <b>→ {i.target_class}</b>
          <span>{i.layout_lane || '—'} · {i.target_band_bytes ? fmtBytes(i.target_band_bytes) : '—'}</span>
          <span>{i.action}</span>
          <span>{fmtBytes(i.size)}</span>
        </div>)}</div>
        <div className="apply-box">
          <p><b>Same-volume:</b> atomic move + journal. <b>SSD → HDD:</b> chunked copy → verify → publish; исходник пока сохраняется. Колонка lane/band показывает будущий Adaptive Macro Interleave профиль записи на HDD; реальное принудительное extent-placement всё ещё выключено.</p>
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
      {job && <>
        <JobProgress
          percent={job.progress_percent}
          running={running}
          label={job.total_bytes ? `${fmtBytes(job.processed_bytes || 0)} / ${fmtBytes(job.total_bytes)}` : 'Подготовка плана выполнения'}
        />
        <div className="job-strip">
        <StatusPill tone={job.status === 'completed' ? 'good' : job.status === 'failed' ? 'danger' : 'neutral'}>{job.status}</StatusPill>
        <span>{job.completed || 0}/{job.total || 0} completed</span>
        <span>{job.failed || 0} failed</span>
        <span>{job.copied || 0} copied</span>
        <span>{job.moved || 0} moved</span>
      </div>
      </>}
    </Panel>
  </div>
}

export function DiagnosticsAdmin({ setError }) {
  const [disks, setDisks] = useState([])
  const [elevated, setElevated] = useState(null)
  const [diskNumber, setDiskNumber] = useState(localStorage.getItem('diagnosticDisk') || '')
  const [mode, setMode] = useState(localStorage.getItem('diagnosticMode') || 'quick')
  const [jobId, setJobId] = useState(localStorage.getItem('diagnosticJobId') || '')
  const [job, setJob] = useState(null)
  const [history, setHistory] = useState([])

  const terminal = useMemo(() => new Set(['completed', 'failed', 'cancelled']), [])

  async function refreshBase() {
    const inventory = await api('/api/disks')
    const availableDisks = inventory.disks || []
    setDisks(availableDisks)

    if (!diskNumber && availableDisks.length) {
      const preferred = availableDisks.find(item => !item.protected) || availableDisks[0]
      setDiskNumber(String(preferred.number))
    }

    try {
      const caps = await api('/api/disks/capabilities')
      setElevated(caps.process_elevated)
    } catch {
      setElevated(null)
    }

    try {
      const previous = await api('/api/diagnostics/history?limit=8')
      setHistory(previous.runs || [])
    } catch {
      setHistory([])
    }
  }

  useEffect(() => { refreshBase().catch(e => setError(e.message)) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (diskNumber !== '') localStorage.setItem('diagnosticDisk', diskNumber) }, [diskNumber])
  useEffect(() => { localStorage.setItem('diagnosticMode', mode) }, [mode])

  useEffect(() => {
    if (!jobId) return undefined
    localStorage.setItem('diagnosticJobId', jobId)
    let stopped = false
    const poll = async () => {
      try {
        const next = await api(`/api/diagnostics/surface/${jobId}`)
        if (stopped) return
        setJob(next)
        if (terminal.has(next.status)) {
          localStorage.removeItem('diagnosticJobId')
          setJobId('')
          api('/api/diagnostics/history?limit=8').then(x => setHistory(x.runs || [])).catch(() => {})
        }
      } catch (e) {
        if (!stopped) {
          localStorage.removeItem('diagnosticJobId')
          setJobId('')
          setError(e.message)
        }
      }
    }
    poll()
    const timer = setInterval(poll, 600)
    return () => { stopped = true; clearInterval(timer) }
  }, [jobId, setError, terminal])

  async function start() {
    try {
      const value = await api('/api/diagnostics/surface', {
        method: 'POST',
        body: JSON.stringify({ disk_number: Number(diskNumber), mode }),
      })
      setJob(value)
      setJobId(value.id)
    } catch (e) { setError(e.message) }
  }

  async function stop() {
    try {
      setJob(await api(`/api/diagnostics/surface/${jobId}/cancel`, { method: 'POST', body: '{}' }))
    } catch (e) { setError(e.message) }
  }

  const running = job && !terminal.has(job.status)
  const selected = disks.find(item => String(item.number) === String(diskNumber))
  const tone = job?.rating === 'Excellent' || job?.rating === 'Good'
    ? 'good'
    : job?.rating === 'Warning'
      ? 'warning'
      : job?.rating === 'Bad'
        ? 'danger'
        : 'neutral'

  return <div className="stack admin-workbench diagnostics-page">
    <Panel title="Surface Diagnostics · read-only">
      <p>Проверка читает physical disk и ничего на него не записывает. Quick/Standard равномерно семплируют всю ёмкость; Full читает весь диск последовательно. Для raw physical access backend должен быть запущен от Administrator.</p>
      {elevated === false && <p className="warning">Backend не elevated — raw surface scan не запустится.</p>}
      <div className="diagnostic-controls">
        <div>
          <label>Physical disk · найдено {disks.length}</label>
          <select value={diskNumber} onChange={e => setDiskNumber(e.target.value)} disabled={running || disks.length === 0}>
            {disks.length === 0 && <option value="">Нет доступных дисков</option>}
            {disks.map(d => <option key={d.number} value={d.number}>Disk {d.number} · {d.friendly_name} · {fmtBytes(d.size)} · {d.bus_type}</option>)}
          </select>
          <button disabled={running} onClick={() => refreshBase().catch(e => setError(e.message))}>↻ Обновить список дисков</button>
          {disks.length === 0 && <small className="warning-inline">/api/disks не вернул физические диски. Проверь страницу «Диски» и backend console.</small>}
        </div>
        <div>
          <label>Глубина</label>
          <select value={mode} onChange={e => setMode(e.target.value)} disabled={running}>
            <option value="quick">Quick · ~384 MiB samples</option>
            <option value="standard">Standard · ~4 GiB samples</option>
            <option value="full">Full read · вся ёмкость</option>
          </select>
        </div>
        <div className="diagnostic-buttons">
          <button className="primary" disabled={!selected || running || elevated === false} onClick={start}>▶ Проверить поверхность</button>
          <button className="stop-button" disabled={!running || !jobId} onClick={stop}>■ Stop</button>
        </div>
      </div>
      {mode === 'full' && <p className="warning">Full read на 4-TB HDD может идти много часов. Он read-only, но создаёт длительную нагрузку на диск.</p>}

      {job && <>
        <div className="metrics">
          <Metric label="Status" value={job.status} />
          <Metric label="Оценка" value={job.rating || 'идёт проверка'} />
          <Metric label="Median" value={job.median_mib_s != null ? `${job.median_mib_s} MiB/s` : '—'} />
          <Metric label="Read errors" value={job.read_errors ?? 0} />
          <Metric label="Slow cells" value={job.slow_cells ?? 0} />
          <Metric label="Прочитано" value={fmtBytes(job.sampled_bytes || 0)} />
        </div>
        <JobProgress percent={job.progress_percent} running={running} label={`${job.completed_cells || 0} / ${job.total_cells || 0} regions`} />
        <div className="surface-head">
          <StatusPill tone={tone}>{job.rating || job.status}</StatusPill>
          <span>Windows: <b>{job.health_status || 'Unknown'}</b></span>
          <span>🌡 <b>{job.reliability?.temperature_c ?? '—'} °C</b></span>
          <span>⏱ <b>{job.reliability?.power_on_hours ?? '—'} h</b></span>
        </div>
        <div className="surface-grid">
          {(job.cells || []).map(cell => <i
            key={cell.index}
            className={cell.status}
            title={`Region ${cell.index + 1}/${job.total_cells}\nOffset ${fmtBytes(cell.start)} – ${fmtBytes(cell.end)}\nRead ${fmtBytes(cell.sample_bytes || 0)}\n${cell.mib_s != null ? `${cell.mib_s} MiB/s` : cell.status}\n${cell.error || ''}`}
          />)}
        </div>
        <div className="surface-legend">
          <span><i className="good" /> normal</span>
          <span><i className="warn" /> slower</span>
          <span><i className="slow" /> very slow</span>
          <span><i className="bad" /> read error</span>
          <span><i className="pending" /> not checked</span>
        </div>
        {job.error && <p className="warning">{job.error}</p>}
        <p className="muted">{job.note}</p>
      </>}
    </Panel>

    <Panel title="Как читается оценка">
      <div className="health-scale">
        <div className="excellent"><b>Excellent</b><span>Windows Healthy + чистая сетка + доступны reliability counters.</span></div>
        <div className="good"><b>Good</b><span>Ошибок чтения нет; SMART/reliability может быть недоступен через USB bridge.</span></div>
        <div className="warning"><b>Warning</b><span>Есть заметно медленные области, lifetime error counters или Windows Warning.</span></div>
        <div className="bad"><b>Bad</b><span>Есть raw read errors или Windows сообщает Unhealthy.</span></div>
      </div>
    </Panel>

    <Panel title="Последние проверки">
      <div className="snapshot-list">{history.map(run => <div key={run.id}>
        <b>Disk {run.disk_number} · {run.rating || run.status}</b>
        <span>{run.mode}</span>
        <span>{run.started_at}</span>
        <span>{run.read_errors} errors</span>
      </div>)}</div>
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
        <JobProgress running={running} label="Движок Defender/ClamAV не сообщает DiskShell надёжный общий объём работы." />
        {job.output && <pre className="security-output">{job.output}</pre>}
      </>}
    </Panel>
    <Panel title="Последние результаты">
      <div className="snapshot-list">{results.map(r => <div key={r.id}><b>{r.status}</b><span>{r.engine}</span><span title={r.path}>{r.path}</span><span>{r.threats ?? '—'} threats</span></div>)}</div>
    </Panel>
  </div>
}


function remoteJoin(root, name) {
  return `${String(root || '/').replace(/\/$/, '')}/${name}`.replace(/\/+/g, '/')
}

function paneTarget(pane, item = null) {
  const path = item?.path || pane.path
  if (pane.sourceType === 'local') return { kind: 'local', path }
  return { kind: 'remote', connection_id: pane.connectionId, path }
}

function isArchiveName(name = '') {
  return /\.(zip|7z|rar|tar|tgz|gz|bz2|xz|cab|iso|wim)$/i.test(name)
}

function archiveExtension(format) {
  return ({ zip: '.zip', tar: '.tar', 'tar.gz': '.tar.gz', '7z': '.7z' })[format] || '.zip'
}

function CommanderPane({
  title,
  side,
  state,
  setState,
  roots,
  connections,
  active,
  busy,
  load,
  choose,
  connectRemote,
  disconnectRemote,
}) {
  const remote = state.sourceType !== 'local'
  const profile = connections.find(item => item.id === state.connectionId)
  const form = state.remoteForm || {}

  function patchForm(values) {
    setState(current => ({
      ...current,
      remoteForm: { ...(current.remoteForm || {}), ...values },
    }))
  }

  return <Panel title={title} className={`pane commander-pane ${active ? 'active-pane' : ''}`}>
    <div className="pane-source-bar">
      <select
        value={state.sourceType}
        disabled={busy}
        onChange={e => {
          const sourceType = e.target.value
          setState(current => ({
            ...current,
            sourceType,
            connectionId: sourceType === 'local' ? '' : current.connectionId,
            data: null,
            selected: null,
            path: sourceType === 'local' ? (roots[0]?.path || current.path || 'C:\\') : '/',
            remoteForm: {
              ...(current.remoteForm || {}),
              protocol: sourceType === 'local' ? 'sftp' : sourceType,
              port: sourceType === 'sftp' ? '22' : '21',
            },
          }))
        }}
      >
        <option value="local">Local</option>
        <option value="sftp">SFTP / SSH</option>
        <option value="ftp">FTP</option>
        <option value="ftps">FTPS</option>
      </select>

      {!remote && <select
        className="drive-select"
        value={roots.some(item => item.path === state.path) ? state.path : ''}
        disabled={busy}
        onChange={e => e.target.value && load(side, e.target.value, { ...state, path: e.target.value })}
      >
        <option value="">Drives…</option>
        {roots.map(root => <option key={root.path} value={root.path}>
          {root.path} · {root.filesystem || 'FS'} · {root.free != null ? fmtBytes(root.free) + ' free' : '—'}
        </option>)}
      </select>}

      {remote && profile && <div className="remote-session-chip">
        <b>{profile.protocol.toUpperCase()}</b>
        <span>{profile.username}@{profile.host}:{profile.port}</span>
        <button disabled={busy} onClick={() => disconnectRemote(side, state)}>Disconnect</button>
      </div>}
    </div>

    {remote && !profile && <div className="remote-connect-box">
      <input placeholder="host / IP" value={form.host || ''} onChange={e => patchForm({ host: e.target.value })} />
      <input className="port-input" placeholder="port" value={form.port || (state.sourceType === 'sftp' ? '22' : '21')} onChange={e => patchForm({ port: e.target.value })} />
      <input placeholder="username" value={form.username || ''} onChange={e => patchForm({ username: e.target.value })} />
      <input type="password" placeholder="password · RAM only" value={form.password || ''} onChange={e => patchForm({ password: e.target.value })} />
      {state.sourceType === 'sftp' && <input placeholder="private key path (optional)" value={form.privateKeyPath || ''} onChange={e => patchForm({ privateKeyPath: e.target.value })} />}
      <input placeholder="remote root" value={form.root || '/'} onChange={e => patchForm({ root: e.target.value })} />
      {state.sourceType === 'sftp' && <label className="mini-check"><input type="checkbox" checked={Boolean(form.acceptUnknownHost)} onChange={e => patchForm({ acceptUnknownHost: e.target.checked })} /> accept unknown host key</label>}
      {(state.sourceType === 'ftp' || state.sourceType === 'ftps') && <label className="mini-check"><input type="checkbox" checked={form.passive !== false} onChange={e => patchForm({ passive: e.target.checked })} /> passive mode</label>}
      <button className="primary" disabled={busy || !form.host || !form.username} onClick={() => connectRemote(side, state)}>Connect</button>
    </div>}

    <div className="file-toolbar">
      <button disabled={!state.data?.parent || busy} onClick={() => state.data?.parent && load(side, state.data.parent)}>↑</button>
      <input value={state.path} onChange={e => setState(current => ({ ...current, path: e.target.value }))} />
      <button disabled={busy || (remote && !state.connectionId)} onClick={() => load(side, state.path)}>Open</button>
      <button disabled={busy || (remote && !state.connectionId)} onClick={() => load(side, state.path)}>↻</button>
    </div>

    <div className="commander-columns"><span>Name</span><span>Size</span><span>Modified</span></div>
    <div className="file-list commander-list">
      {(state.data?.items || []).slice(0, 4000).map(item => <button
        key={item.path}
        className={state.selected?.path === item.path ? 'selected' : ''}
        onClick={() => choose(side, item)}
        onDoubleClick={() => item.is_dir && !busy && load(side, item.path)}
      >
        <span title={item.path}>{item.is_dir ? '📁' : '📄'} {item.name}</span>
        <span>{item.is_dir ? '<DIR>' : fmtBytes(item.size)}</span>
        <span>{item.modified_ns ? new Date(item.modified_ns / 1e6).toLocaleString() : ''}</span>
      </button>)}
    </div>
    <div className="pane-status">
      <span>{state.data?.items?.length || 0} items</span>
      <span>{state.selected ? `${state.selected.name} · ${state.selected.is_dir ? '<DIR>' : fmtBytes(state.selected.size)}` : 'nothing selected'}</span>
    </div>
  </Panel>
}

function CommanderInspector({ preview, archive, remoteOrigin }) {
  if (!preview && !archive) return <Panel title="F3 View / Archive browser"><p className="muted">Выбери файл и нажми F3 View. Архивы и ISO откроются здесь же — отдельная вкладка больше не нужна.</p></Panel>
  const visual = preview && ['image', 'pdf'].includes(preview.provider)
  const previewPath = preview?.preview_path || preview?.path
  return <Panel title={archive ? `Archive · ${archive.path}` : `Preview · ${preview?.name || ''}`}>
    {remoteOrigin && <p className="muted">Remote source: {remoteOrigin}. Для просмотра создан ограниченный temporary cache на backend.</p>}
    {preview && <div className="preview-grid">
      {visual && previewPath && <img className="preview-image" src={thumbnailUrl(previewPath, 800)} alt={preview.name} />}
      <div>
        <div className="metrics">
          <Metric label="Provider" value={preview.provider} />
          <Metric label="Size" value={fmtBytes(preview.size)} />
          <Metric label="Type" value={preview.mime} />
          <Metric label="Geometry" value={preview.width ? `${preview.width}×${preview.height}` : preview.pages ? `${preview.pages} pages` : '—'} />
        </div>
        {preview.text && <pre className="text-preview">{preview.text.slice(0, 50000)}</pre>}
        {preview.ffprobe && <pre className="text-preview">{JSON.stringify(preview.ffprobe, null, 2).slice(0, 30000)}</pre>}
      </div>
    </div>}
    {archive && <div className="archive-list">
      {(archive.entries || []).slice(0, 4000).map((item, index) => <div key={`${item.name}-${index}`}>
        <span>{item.is_dir ? '📁' : '📄'} {item.name}</span>
        <span>{item.size == null ? '' : fmtBytes(item.size)}</span>
      </div>)}
    </div>}
  </Panel>
}

export function FilesAdmin({ health, setError }) {
  const makePane = (side) => ({
    sourceType: 'local',
    path: localStorage.getItem(`file${side}Path`) || 'F:\\',
    data: null,
    selected: null,
    connectionId: '',
    remoteForm: {
      protocol: 'sftp',
      host: '',
      port: '22',
      username: '',
      password: '',
      privateKeyPath: '',
      root: '/',
      acceptUnknownHost: false,
      passive: true,
    },
  })

  const [left, setLeft] = useState(() => makePane('Left'))
  const [right, setRight] = useState(() => makePane('Right'))
  const [activeSide, setActiveSide] = useState('left')
  const [roots, setRoots] = useState([])
  const [connections, setConnections] = useState([])
  const [jobId, setJobId] = useState(localStorage.getItem('commanderJobId') || '')
  const [job, setJob] = useState(null)
  const [smartTransfer, setSmartTransfer] = useState(false)
  const [smartHint, setSmartHint] = useState(null)
  const [preview, setPreview] = useState(null)
  const [archive, setArchive] = useState(null)
  const [remoteOrigin, setRemoteOrigin] = useState('')
  const [archiveFormat, setArchiveFormat] = useState('zip')

  const terminal = useMemo(() => new Set(['completed', 'failed', 'cancelled']), [])
  const activePane = activeSide === 'left' ? left : right
  const passivePane = activeSide === 'left' ? right : left

  async function refreshMeta() {
    try {
      const [rootData, connectionData] = await Promise.all([
        api('/api/files/roots'),
        api('/api/commander/connections'),
      ])
      setRoots(rootData.roots || [])
      setConnections(connectionData.connections || [])
    } catch (e) { setError(e.message) }
  }

  async function load(side, path, forcedPane = null) {
    const pane = forcedPane || (side === 'left' ? left : right)
    try {
      const data = pane.sourceType === 'local'
        ? await api(`/api/files?path=${encodeURIComponent(path)}`)
        : await api(`/api/commander/remote?connection_id=${encodeURIComponent(pane.connectionId)}&path=${encodeURIComponent(path)}`)
      const next = { ...pane, path: data.path, data, selected: null }
      if (side === 'left') {
        setLeft(next)
        if (next.sourceType === 'local') localStorage.setItem('fileLeftPath', data.path)
      } else {
        setRight(next)
        if (next.sourceType === 'local') localStorage.setItem('fileRightPath', data.path)
      }
    } catch (e) { setError(e.message) }
  }

  function choose(side, item) {
    setActiveSide(side)
    setPreview(null)
    setArchive(null)
    setRemoteOrigin('')
    if (side === 'left') setLeft(current => ({ ...current, selected: item }))
    else setRight(current => ({ ...current, selected: item }))
  }

  useEffect(() => {
    refreshMeta()
    load('left', left.path)
    load('right', right.path)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!jobId) return undefined
    localStorage.setItem('commanderJobId', jobId)
    let stopped = false
    const poll = async () => {
      try {
        const next = await api(`/api/commander/jobs/${jobId}`)
        if (stopped) return
        setJob(next)
        if (terminal.has(next.status)) {
          localStorage.removeItem('commanderJobId')
          setJobId('')
          await Promise.all([load('left', left.path), load('right', right.path)])
        }
      } catch (e) {
        if (!stopped) {
          localStorage.removeItem('commanderJobId')
          setJobId('')
          setError(e.message)
        }
      }
    }
    poll()
    const timer = setInterval(poll, 650)
    return () => { stopped = true; clearInterval(timer) }
  }, [jobId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function connectRemote(side, pane) {
    const form = pane.remoteForm || {}
    try {
      const profile = await api('/api/commander/connections', {
        method: 'POST',
        body: JSON.stringify({
          protocol: pane.sourceType,
          host: form.host,
          port: form.port || undefined,
          username: form.username,
          password: form.password || '',
          private_key_path: form.privateKeyPath || '',
          accept_unknown_host: Boolean(form.acceptUnknownHost),
          passive: form.passive !== false,
          root: form.root || '/',
        }),
      })
      setConnections(current => [...current.filter(item => item.id !== profile.id), profile])
      const next = {
        ...pane,
        connectionId: profile.id,
        path: profile.root || '/',
        data: null,
        selected: null,
        remoteForm: { ...form, password: '' },
      }
      if (side === 'left') setLeft(next)
      else setRight(next)
      await load(side, next.path, next)
    } catch (e) { setError(e.message) }
  }

  async function disconnectRemote(side, pane) {
    try {
      if (pane.connectionId) await api(`/api/commander/connections/${pane.connectionId}`, { method: 'DELETE' })
      setConnections(current => current.filter(item => item.id !== pane.connectionId))
      const next = { ...pane, connectionId: '', data: null, selected: null, path: '/' }
      if (side === 'left') setLeft(next)
      else setRight(next)
    } catch (e) { setError(e.message) }
  }

  async function transfer(operation) {
    const sourcePane = activePane
    const destinationPane = passivePane
    const selected = sourcePane.selected
    if (!selected || !health?.safety?.file_writes) return

    try {
      let destinationPath = destinationPane.sourceType === 'local'
        ? joinPath(destinationPane.path, selected.name)
        : remoteJoin(destinationPane.path, selected.name)
      let hint = null

      if (smartTransfer && !selected.is_dir && destinationPane.sourceType === 'local') {
        hint = await api('/api/files/smart-destination', {
          method: 'POST',
          body: JSON.stringify({
            name: selected.name,
            source_path: selected.path,
            size: selected.size,
            modified_ns: selected.modified_ns,
            storage_root: destinationPane.path,
          }),
        })
        destinationPath = hint.destination
        setSmartHint(hint)
      } else {
        setSmartHint(null)
      }

      const destination = destinationPane.sourceType === 'local'
        ? { kind: 'local', path: destinationPath }
        : { kind: 'remote', connection_id: destinationPane.connectionId, path: destinationPath }

      const value = await api('/api/commander/jobs', {
        method: 'POST',
        body: JSON.stringify({
          operation,
          source: paneTarget(sourcePane, selected),
          destination,
        }),
      })
      setJob(value)
      setJobId(value.id)
    } catch (e) { setError(e.message) }
  }

  async function stop() {
    if (!jobId) return
    try {
      setJob(await api(`/api/commander/jobs/${jobId}/cancel`, { method: 'POST', body: '{}' }))
    } catch (e) { setError(e.message) }
  }

  async function makeDirectory() {
    const name = window.prompt('New directory name')
    if (!name) return
    const pane = activePane
    try {
      if (pane.sourceType === 'local') {
        await api('/api/files/mkdir', {
          method: 'POST',
          body: JSON.stringify({ path: joinPath(pane.path, name) }),
        })
      } else {
        await api('/api/commander/remote/mkdir', {
          method: 'POST',
          body: JSON.stringify({
            connection_id: pane.connectionId,
            path: remoteJoin(pane.path, name),
          }),
        })
      }
      await load(activeSide, pane.path)
    } catch (e) { setError(e.message) }
  }

  async function renameSelected() {
    const pane = activePane
    if (!pane.selected) return
    const name = window.prompt('Rename to', pane.selected.name)
    if (!name || name === pane.selected.name) return
    try {
      const destination = pane.sourceType === 'local'
        ? joinPath(pane.path, name)
        : remoteJoin(pane.path, name)
      if (pane.sourceType === 'local') {
        await api('/api/files/rename', {
          method: 'POST',
          body: JSON.stringify({ source: pane.selected.path, destination }),
        })
      } else {
        await api('/api/commander/remote/rename', {
          method: 'POST',
          body: JSON.stringify({
            connection_id: pane.connectionId,
            source: pane.selected.path,
            destination,
          }),
        })
      }
      await load(activeSide, pane.path)
    } catch (e) { setError(e.message) }
  }

  async function deleteSelected() {
    const pane = activePane
    if (!pane.selected) return
    const remote = pane.sourceType !== 'local'
    const message = remote
      ? `DELETE remote ${pane.selected.path}? Remote delete has no Recycle Bin.`
      : `Move ${pane.selected.path} to Recycle Bin?`
    if (!window.confirm(message)) return
    try {
      if (!remote) {
        await api('/api/files/trash', {
          method: 'POST',
          body: JSON.stringify({ path: pane.selected.path }),
        })
      } else {
        await api('/api/commander/remote/delete', {
          method: 'POST',
          body: JSON.stringify({
            connection_id: pane.connectionId,
            path: pane.selected.path,
            recursive: Boolean(pane.selected.is_dir),
          }),
        })
      }
      await load(activeSide, pane.path)
    } catch (e) { setError(e.message) }
  }

  async function inspectSelected() {
    const pane = activePane
    const selected = pane.selected
    if (!selected || selected.is_dir) return
    try {
      let localPath = selected.path
      let origin = ''
      if (pane.sourceType !== 'local') {
        const cached = await api('/api/commander/remote/cache', {
          method: 'POST',
          body: JSON.stringify({
            connection_id: pane.connectionId,
            path: selected.path,
            max_bytes: 256 * 1024 ** 2,
          }),
        })
        localPath = cached.local_path
        origin = selected.path
      }

      const value = await api(`/api/content/preview?path=${encodeURIComponent(localPath)}`)
      setPreview({ ...value, preview_path: localPath })
      setRemoteOrigin(origin)
      if (isArchiveName(selected.name)) {
        try {
          setArchive(await api(`/api/content/archive?path=${encodeURIComponent(localPath)}`))
        } catch {
          setArchive(null)
        }
      } else {
        setArchive(null)
      }
    } catch (e) { setError(e.message) }
  }

  async function createArchive() {
    const pane = activePane
    const selected = pane.selected
    if (!selected || pane.sourceType !== 'local') {
      setError('Archive creation currently requires a local selected source')
      return
    }
    const extension = archiveExtension(archiveFormat)
    const base = selected.name.replace(/\.[^.]+$/, '')
    const name = window.prompt('Archive file name', `${base}${extension}`)
    if (!name) return
    try {
      await api('/api/content/archive/create', {
        method: 'POST',
        body: JSON.stringify({
          sources: [selected.path],
          destination: joinPath(pane.path, name),
          format: archiveFormat,
        }),
      })
      await load(activeSide, pane.path)
    } catch (e) { setError(e.message) }
  }

  async function extractArchive() {
    const pane = activePane
    const selected = pane.selected
    const destinationPane = passivePane
    if (!selected || pane.sourceType !== 'local' || destinationPane.sourceType !== 'local') {
      setError('Extract currently requires a local archive and a local destination pane')
      return
    }
    try {
      await api('/api/content/archive/extract', {
        method: 'POST',
        body: JSON.stringify({
          path: selected.path,
          destination: destinationPane.path,
        }),
      })
      await load(activeSide === 'left' ? 'right' : 'left', destinationPane.path)
    } catch (e) { setError(e.message) }
  }

  const busy = Boolean(jobId && job && !terminal.has(job.status))

  useEffect(() => {
    const handler = event => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return
      if (event.key === 'Tab') {
        event.preventDefault()
        setActiveSide(side => side === 'left' ? 'right' : 'left')
      } else if (event.key === 'F2') {
        event.preventDefault(); renameSelected()
      } else if (event.key === 'F3') {
        event.preventDefault(); inspectSelected()
      } else if (event.key === 'F5') {
        event.preventDefault(); transfer('copy')
      } else if (event.key === 'F6') {
        event.preventDefault(); transfer('move')
      } else if (event.key === 'F7') {
        event.preventDefault(); makeDirectory()
      } else if (event.key === 'F8') {
        event.preventDefault(); deleteSelected()
      } else if (event.key === 'F9') {
        event.preventDefault(); createArchive()
      } else if (event.key === 'Escape' && busy) {
        event.preventDefault(); stop()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }) // current active pane is intentionally captured each render

  return <div className="stack admin-workbench commander-workbench">
    <div className="commander-topline">
      <div>
        <b>DiskShell Commander</b>
        <span>Local · SFTP/SSH · FTP/FTPS · Preview · Archives</span>
      </div>
      <label className="smart-transfer-toggle">
        <input
          type="checkbox"
          checked={smartTransfer}
          onChange={e => setSmartTransfer(e.target.checked)}
        />
        <span><b>Smart placement</b><small>OFF = direct path · ON = classify into HDD storage classes</small></span>
      </label>
      <select value={archiveFormat} onChange={e => setArchiveFormat(e.target.value)}>
        <option value="zip">ZIP</option>
        <option value="7z">7Z</option>
        <option value="tar">TAR</option>
        <option value="tar.gz">TAR.GZ</option>
      </select>
    </div>

    <div className="file-manager commander-manager">
      <div onMouseDown={() => setActiveSide('left')}>
        <CommanderPane
          title="LEFT"
          side="left"
          state={left}
          setState={setLeft}
          roots={roots}
          connections={connections}
          active={activeSide === 'left'}
          busy={busy}
          load={load}
          choose={choose}
          connectRemote={connectRemote}
          disconnectRemote={disconnectRemote}
        />
      </div>

      <div className="file-actions commander-actions">
        <button disabled={!activePane.selected || busy} onClick={inspectSelected}>F3 View</button>
        <button disabled={!health?.safety?.file_writes || !activePane.selected || busy} onClick={() => transfer('copy')}>
          {activeSide === 'left' ? 'F5 Copy →' : '← F5 Copy'}
        </button>
        <button disabled={!health?.safety?.file_writes || !activePane.selected || busy} onClick={() => transfer('move')}>
          {activeSide === 'left' ? 'F6 Move →' : '← F6 Move'}
        </button>
        <button disabled={!health?.safety?.file_writes || busy} onClick={makeDirectory}>F7 MkDir</button>
        <button disabled={!health?.safety?.file_writes || !activePane.selected || busy} onClick={renameSelected}>F2 Rename</button>
        <button className="trash" disabled={!health?.safety?.file_writes || !activePane.selected || busy} onClick={deleteSelected}>F8 Trash/Delete</button>
        <button disabled={!health?.safety?.file_writes || !activePane.selected || busy} onClick={createArchive}>F9 Archive</button>
        <button disabled={!health?.safety?.file_writes || !activePane.selected || busy} onClick={extractArchive}>Extract → other</button>
        <button className="stop-button" disabled={!busy || !jobId} onClick={stop}>■ Stop / Esc</button>
      </div>

      <div onMouseDown={() => setActiveSide('right')}>
        <CommanderPane
          title="RIGHT"
          side="right"
          state={right}
          setState={setRight}
          roots={roots}
          connections={connections}
          active={activeSide === 'right'}
          busy={busy}
          load={load}
          choose={choose}
          connectRemote={connectRemote}
          disconnectRemote={disconnectRemote}
        />
      </div>
    </div>

    {smartTransfer && <Panel title="Smart transfer policy">
      <p><b>Direct transfer remains available.</b> Smart mode changes only the destination path for a file going into a local managed-storage root. The byte transfer is still the same verified Commander job.</p>
      {smartHint && <div className="metrics">
        <Metric label="Class" value={smartHint.target_class} />
        <Metric label="Category" value={smartHint.category} />
        <Metric label="Lane" value={smartHint.layout_lane} />
        <Metric label="Target band" value={fmtBytes(smartHint.target_band_bytes)} />
      </div>}
      {smartHint && <p className="path">{smartHint.destination}</p>}
      <p className="muted">Smart fragmentation / extent-layout verification remains read-only/experimental until Storage Lab can compare actual NTFS extents against this lane/band policy.</p>
    </Panel>}

    <Panel title="Commander transfer job">
      {!job && <p className="muted">F5/F6 use one background job for local, SFTP and FTP endpoints. Stop cleans the incomplete target and preserves the source.</p>}
      {job && <>
        <div className="metrics">
          <Metric label="Operation" value={job.operation} />
          <Metric label="Status" value={job.status} />
          <Metric label="Files" value={`${job.files || 0}/${job.total_files || 0}`} />
          <Metric label="Transferred" value={fmtBytes(job.bytes || 0)} />
        </div>
        <JobProgress
          percent={job.progress_percent}
          running={busy}
          label={`${fmtBytes(job.bytes || 0)} / ${fmtBytes(job.total_bytes || 0)}`}
        />
        <p className="path">{job.current_path}</p>
        {job.error && <p className="warning">{job.error}</p>}
      </>}
      {!health?.safety?.file_writes && <small>DS_ALLOW_FILE_WRITES=0 — write operations are locked.</small>}
    </Panel>

    <CommanderInspector preview={preview} archive={archive} remoteOrigin={remoteOrigin} />
  </div>
}
