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
    return [{
      key: 'raw',
      kind: 'free',
      size,
      offset: 0,
      end: size,
      label: 'RAW / Unallocated',
      partition: null,
    }]
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
        offset: cursor,
        end: offset,
        label: 'Unallocated',
        partition: null,
      })
    }
    const partitionSize = Number(partition.size || 0)
    result.push({
      key: `partition-${partition.partition_number}`,
      kind: 'partition',
      size: partitionSize,
      offset,
      end: offset + partitionSize,
      label: `${partition.drive_letter || `#${partition.partition_number}`} · ${partition.filesystem || 'RAW volume'}`,
      partition,
    })
    cursor = Math.max(cursor, offset + partitionSize)
  }
  if (cursor < size) {
    result.push({
      key: `free-${cursor}`,
      kind: 'free',
      size: size - cursor,
      offset: cursor,
      end: size,
      label: 'Unallocated',
      partition: null,
    })
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
          title={`${segment.label}\nStart ${fmtBytes(segment.offset)}\nEnd ${fmtBytes(segment.end)}\nSize ${fmtBytes(segment.size)}\n${(segment.size * 100 / total).toFixed(2)}%`}
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
    <div className="disk-descriptor-map">
      <div className="descriptor-head">
        <span>Descriptor</span><span>Start</span><span>End</span><span>Size</span><span>Details</span>
      </div>
      {segments.map(segment => <div key={`descriptor-${segment.key}`} className={segment.kind}>
        <b>{segment.partition ? `Partition #${segment.partition.partition_number}` : 'Free gap'}</b>
        <span>{fmtBytes(segment.offset)}</span>
        <span>{fmtBytes(segment.end)}</span>
        <span>{fmtBytes(segment.size)}</span>
        <span>
          {segment.partition
            ? `${segment.partition.drive_letter || '—'} · ${segment.partition.filesystem || 'unformatted'} · ${segment.partition.label || 'no label'}`
            : 'Unallocated'}
        </span>
      </div>)}
    </div>
  </div>
}

function gibToBytes(value) {
  if (value === '' || value === null || value === undefined) return null
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) throw new Error('Размер тома должен быть положительным числом GiB')
  return Math.floor(number * 1024 ** 3)
}

function gibOffsetToBytes(value) {
  if (value === '' || value === null || value === undefined) return null
  const number = Number(value)
  if (!Number.isFinite(number) || number < 0) throw new Error('Offset должен быть неотрицательным числом GiB')
  return Math.floor(number * 1024 ** 3)
}

const TERMINAL_SCAN = new Set(['completed', 'failed', 'cancelled'])
const TERMINAL_PLAN = new Set(['completed', 'partial', 'failed', 'blocked', 'cancelled'])

export function DisksAdmin({ setError }) {
  const [data, setData] = useState(null)
  const [capabilities, setCapabilities] = useState({ filesystems: [], process_elevated: null })
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
  const [boundaryDraft, setBoundaryDraft] = useState(null)
  const [boundaryPlan, setBoundaryPlan] = useState(null)
  const [boundaryConfirm, setBoundaryConfirm] = useState('')
  const [diskBusy, setDiskBusy] = useState(null)
  const [diskNotice, setDiskNotice] = useState('')
  const [inventoryError, setInventoryError] = useState('')

  const reload = async () => {
    try {
      const next = await api('/api/disks')
      setData(next)
      setInventoryError('')
    } catch (e) {
      setInventoryError(e.message)
    }
  }
  useEffect(() => {
    let stopped = false
    const refresh = async () => {
      const [diskResult, capabilityResult] = await Promise.allSettled([
        api('/api/disks'),
        api('/api/disks/capabilities'),
      ])
      if (stopped) return
      if (diskResult.status === 'fulfilled') {
        setData(diskResult.value)
        setInventoryError('')
      } else {
        setInventoryError(diskResult.reason?.message || 'Disk inventory temporarily unavailable')
      }
      if (capabilityResult.status === 'fulfilled') setCapabilities(capabilityResult.value)
    }
    const onDiskEvent = event => {
      if (stopped) return
      const disks = event.detail?.disks
      if (Array.isArray(disks)) {
        setData(current => ({ ...(current || {}), disks }))
        setInventoryError('')
      } else {
        refresh()
      }
    }
    window.addEventListener('diskshell:disks-changed', onDiskEvent)
    refresh()
    const timer = setInterval(refresh, 30000)
    return () => {
      stopped = true
      clearInterval(timer)
      window.removeEventListener('diskshell:disks-changed', onDiskEvent)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const filesystemList = Array.isArray(capabilities.filesystems) ? capabilities.filesystems : []
  const filesystemProfile = key => filesystemList.find(item => item.key === key)
  const elevated = capabilities.process_elevated === true
  const diskByNumber = number => (data?.disks || []).find(d => d.number === number)

  async function toggleWrite(disk) {
    try {
      const endpoint = disk.write_access?.allowed
        ? `/api/disks/${disk.number}/lock`
        : `/api/disks/${disk.number}/unlock`
      await api(endpoint, { method: 'POST', body: '{}' })
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

  function prepareBoundary(disk, partition) {
    setBoundaryDraft({
      diskNumber: disk.number,
      partitionNumber: partition.partition_number,
      boundary: 'end',
      targetGiB: (Number(partition.size || 0) / 1024 ** 3).toFixed(3),
      startGiB: (Number(partition.offset || 0) / 1024 ** 3).toFixed(3),
    })
    setBoundaryPlan(null)
    setBoundaryConfirm('')
  }

  async function checkBoundaryPlan() {
    try {
      const payload = boundaryDraft.boundary === 'end'
        ? {
            boundary: 'end',
            target_size_bytes: gibToBytes(boundaryDraft.targetGiB),
          }
        : {
            boundary: 'start',
            target_start_offset: gibOffsetToBytes(boundaryDraft.startGiB),
          }
      const value = await api(
        `/api/disks/${boundaryDraft.diskNumber}/partitions/${boundaryDraft.partitionNumber}/boundary-plan`,
        { method: 'POST', body: JSON.stringify(payload) },
      )
      setBoundaryPlan(value)
      setBoundaryConfirm('')
    } catch (e) { setError(e.message) }
  }

  async function executeBoundaryResize() {
    if (!boundaryPlan?.execution_supported || boundaryPlan.boundary !== 'end') return
    setDiskBusy({
      diskNumber: boundaryDraft.diskNumber,
      phase: 'resize',
      label: 'Windows изменяет конечную границу раздела. Не отключай питание или диск.',
    })
    try {
      await api(
        `/api/disks/${boundaryDraft.diskNumber}/partitions/${boundaryDraft.partitionNumber}/resize-end`,
        {
          method: 'POST',
          body: JSON.stringify({
            target_size_bytes: boundaryPlan.target_size,
            confirmation: boundaryConfirm,
          }),
        },
      )
      setBoundaryDraft(null)
      setBoundaryPlan(null)
      setBoundaryConfirm('')
      setDiskNotice(`Disk ${boundaryDraft.diskNumber}: граница раздела обновлена.`)
      await reload()
    } catch (e) { setError(e.message) }
    finally { setDiskBusy(null) }
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
    {inventoryError && <div className="warning">
      <b>Disk inventory temporarily unavailable.</b> {inventoryError}
      <span>Hot-unplug не должен ронять DiskShell: destructive controls остаются закрыты до следующего успешного inventory.</span>
      <button onClick={reload}>Retry inventory</button>
    </div>}
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

    {(Array.isArray(data?.disks) ? data.disks : []).map(d => {
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
            {d.protected ? 'PROTECTED' : write.allowed ? 'WRITE ENABLED' : 'WRITE LOCKED'}
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
            <b>1</b><span><strong>Разрешить запись</strong><small>{write.allowed ? 'WRITE ENABLED до ручного выключения / restart backend' : 'Включи тумблер только для выбранного диска'}</small></span>
          </div>
          <div className={String(d.partition_style).toUpperCase() !== 'RAW' ? 'done' : (write.allowed ? 'current' : '')}>
            <b>2</b><span><strong>Initialize GPT</strong><small>{String(d.partition_style).toUpperCase() !== 'RAW' ? 'GPT создан' : 'Создать только таблицу разделов'}</small></span>
          </div>
          <div className={(d.partitions || []).length > 0 ? 'done' : (String(d.partition_style).toUpperCase() !== 'RAW' ? 'current' : '')}>
            <b>3</b><span><strong>Раздел + файловая система</strong><small>{(d.partitions || []).length > 0 ? 'Том создан' : 'Выбрать размер, NTFS и cluster size'}</small></span>
          </div>
        </div>}

        {d.protected
          ? <p className="protected">🔒 {(Array.isArray(d.protection_reasons) ? d.protection_reasons : []).join(', ') || 'protected'}</p>
          : <div className="actions disk-write-actions">
              <label className={`disk-write-toggle ${write.allowed ? 'enabled' : 'locked'}`}>
                <input
                  type="checkbox"
                  checked={Boolean(write.allowed)}
                  disabled={Boolean(diskBusy) || Boolean(write.global_override)}
                  onChange={() => toggleWrite(d)}
                />
                <span className="toggle-track"><i /></span>
                <span className="toggle-copy">
                  <b>{write.allowed ? 'WRITE ENABLED' : 'WRITE LOCKED'}</b>
                  <small>{write.global_override ? 'DS_ALLOW_DISK_WRITES=1' : 'ручной per-disk переключатель'}</small>
                </span>
              </label>
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
            <div className="partition-row-actions">
              <button onClick={() => prepareBoundary(d, p)}>Граница</button>
              <button disabled={d.protected || !write.allowed} onClick={() => prepareLetter(d, p)}>Буква</button>
            </div>
          </div>)}
        </div>
      </Panel>
    })}

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
            {filesystemList.map(item => <option key={item.key} value={item.key}>{item.title}</option>)}
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

    {boundaryDraft && <Panel title={`Граница Disk ${boundaryDraft.diskNumber} · Partition ${boundaryDraft.partitionNumber}`}>
      <p className="muted">
        End boundary можно grow/shrink через Windows Resize-Partition. Start boundary DiskShell
        только планирует: её перемещение означает реальную relocation/recreate/offline операцию.
      </p>
      <div className="grid two">
        <div>
          <label>Какая граница</label>
          <select
            value={boundaryDraft.boundary}
            onChange={e => {
              setBoundaryDraft(x => ({ ...x, boundary: e.target.value }))
              setBoundaryPlan(null)
              setBoundaryConfirm('')
            }}
          >
            <option value="end">End · изменить размер раздела</option>
            <option value="start">Start · relocation plan only</option>
          </select>
        </div>
        <div>
          {boundaryDraft.boundary === 'end'
            ? <>
                <label>Новый размер раздела, GiB</label>
                <input value={boundaryDraft.targetGiB} onChange={e => {
                  setBoundaryDraft(x => ({ ...x, targetGiB: e.target.value }))
                  setBoundaryPlan(null)
                }} />
              </>
            : <>
                <label>Новый start offset от начала диска, GiB</label>
                <input value={boundaryDraft.startGiB} onChange={e => {
                  setBoundaryDraft(x => ({ ...x, startGiB: e.target.value }))
                  setBoundaryPlan(null)
                }} />
              </>}
        </div>
      </div>
      <div className="actions">
        <button className="primary" onClick={checkBoundaryPlan}>Проверить границу</button>
        <button onClick={() => { setBoundaryDraft(null); setBoundaryPlan(null) }}>Закрыть</button>
      </div>
      {boundaryPlan && <>
        <div className="metrics">
          <Metric label="Direction" value={boundaryPlan.direction || '—'} />
          <Metric label="Current" value={fmtBytes(boundaryPlan.current_size)} />
          <Metric label="Target" value={fmtBytes(boundaryPlan.target_size)} />
          <Metric label="Free before / after" value={`${fmtBytes(boundaryPlan.free_before)} / ${fmtBytes(boundaryPlan.free_after)}`} />
        </div>
        <p className={boundaryPlan.execution_supported ? 'success' : 'warning'}>
          {boundaryPlan.strategy} · {boundaryPlan.execution_supported ? 'execution available' : 'plan only'}
        </p>
        {(boundaryPlan.warnings || []).map(item => <p className="muted" key={item}>• {item}</p>)}
        {boundaryPlan.supported_size_min != null && <p className="muted">
          Windows supported size: {fmtBytes(boundaryPlan.supported_size_min)} – {fmtBytes(boundaryPlan.supported_size_max)}
        </p>}
        {boundaryPlan.execution_supported && <>
          <label>Для resize введи: <b>{boundaryPlan.confirmation}</b></label>
          <input value={boundaryConfirm} onChange={e => setBoundaryConfirm(e.target.value)} />
          <button
            className="danger-button"
            disabled={
              Boolean(diskBusy)
              || !elevated
              || boundaryConfirm !== boundaryPlan.confirmation
              || !diskByNumber(boundaryDraft.diskNumber)?.write_access?.allowed
            }
            onClick={executeBoundaryResize}
          >
            Изменить end boundary
          </button>
        </>}
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

export function ScanAdmin({ scanId, setScanId, setError, workspaceViewState = {}, patchViewState }) {
  const [path, setPath] = useState(workspaceViewState.scanPath || localStorage.getItem('scanPath') || 'F:\\')
  const [roots, setRoots] = useState([])
  const [jobId, setJobId] = useState(localStorage.getItem('scanJobId') || '')
  const [job, setJob] = useState(null)

  useEffect(() => {
    localStorage.setItem('scanPath', path)
    patchViewState?.({ scanPath: path })
  }, [path, patchViewState])
  useEffect(() => {
    api('/api/files/roots').then(x => setRoots(x.roots || [])).catch(() => {})
  }, [])
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
          <label>Том / диск для обследования</label>
          <select value={roots.some(item => item.path === path) ? path : ''} onChange={e => e.target.value && setPath(e.target.value)}>
            <option value="">Выбрать локальный том…</option>
            {roots.map(item => <option key={item.path} value={item.path}>{item.path} · {item.filesystem || 'FS'} · {item.free != null ? fmtBytes(item.free) + ' free' : '—'}</option>)}
          </select>
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

export function StorageBrainAdmin({ scanId, setError, refreshHealth, workspaceViewState = {}, patchViewState }) {
  const [root, setRoot] = useState(workspaceViewState.storageRoot || localStorage.getItem('storageRoot') || 'F:\\Storage')
  const [roots, setRoots] = useState([])
  const [classes, setClasses] = useState([])
  const [plan, setPlan] = useState(null)
  const [planId, setPlanId] = useState(workspaceViewState.placementPlanId || localStorage.getItem('placementPlanId') || '')
  const [confirmation, setConfirmation] = useState('')
  const [verify, setVerify] = useState('size')
  const [jobId, setJobId] = useState(localStorage.getItem('placementJobId') || '')
  const [job, setJob] = useState(null)
  const [sourceScope, setSourceScope] = useState(workspaceViewState.storageSourceScope || localStorage.getItem('storageSourceScope') || '')
  const [excludeScope, setExcludeScope] = useState(workspaceViewState.storageExcludeScope || localStorage.getItem('storageExcludeScope') || '')
  const [fileWrite, setFileWrite] = useState(null)
  const [planQuery, setPlanQuery] = useState('')
  const [pageOffset, setPageOffset] = useState(0)
  const pageLimit = 250

  useEffect(() => {
    localStorage.setItem('storageRoot', root)
    patchViewState?.({ storageRoot: root })
  }, [root, patchViewState])
  useEffect(() => {
    localStorage.setItem('storageSourceScope', sourceScope)
    patchViewState?.({ storageSourceScope: sourceScope })
  }, [sourceScope, patchViewState])
  useEffect(() => {
    localStorage.setItem('storageExcludeScope', excludeScope)
    patchViewState?.({ storageExcludeScope: excludeScope })
  }, [excludeScope, patchViewState])
  useEffect(() => {
    if (planId) patchViewState?.({ placementPlanId: planId })
  }, [planId, patchViewState])

  useEffect(() => {
    Promise.all([
      api('/api/storage/classes'),
      api('/api/files/roots'),
      api('/api/files/write-access'),
    ])
      .then(([classData, rootData, writeData]) => {
        setClasses(classData.classes || [])
        setRoots(rootData.roots || [])
        setFileWrite(writeData)
      })
      .catch(e => setError(e.message))
  }, [setError])

  function planUrl(id, offset = pageOffset, query = planQuery) {
    const params = new URLSearchParams({
      limit: String(pageLimit),
      offset: String(Math.max(0, offset)),
    })
    if (query.trim()) params.set('q', query.trim())
    return `/api/storage/plans/${id}?${params.toString()}`
  }

  async function reloadPlan(offset = pageOffset, query = planQuery) {
    if (!planId) return
    const value = await api(planUrl(planId, offset, query))
    setPlan(value)
    setPageOffset(value.page?.offset || 0)
  }

  useEffect(() => {
    let active = true
    async function restore() {
      try {
        let value
        if (planId) value = await api(planUrl(planId, 0, ''))
        else if (scanId) value = await api(`/api/storage/plans/latest?scan_id=${scanId}&limit=${pageLimit}`)
        else return
        if (!active) return
        setPlan(value)
        setPlanId(String(value.id))
        setPageOffset(0)
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
  }, [planId, scanId]) // eslint-disable-line react-hooks/exhaustive-deps

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
          if (planId) await reloadPlan()
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
  }, [jobId, planId, setError]) // eslint-disable-line react-hooks/exhaustive-deps

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
      setPageOffset(0)
      setPlanQuery('')
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

  async function toggleFileWrites() {
    try {
      const next = await api('/api/files/write-access', {
        method: 'POST',
        body: JSON.stringify({ enabled: !fileWrite?.allowed }),
      })
      setFileWrite(next)
      if (refreshHealth) await refreshHealth()
    } catch (e) { setError(e.message) }
  }

  async function changeSelection(selected, itemIds = [], allItems = false) {
    if (!plan) return
    try {
      const value = await api(`/api/storage/plans/${plan.id}/selection`, {
        method: 'POST',
        body: JSON.stringify({
          selected,
          item_ids: itemIds,
          all_items: allItems,
          query: allItems ? planQuery : '',
        }),
      })
      setPlan(value)
      setPageOffset(value.page?.offset || 0)
    } catch (e) { setError(e.message) }
  }

  async function searchPlan() {
    try {
      setPageOffset(0)
      await reloadPlan(0, planQuery)
    } catch (e) { setError(e.message) }
  }

  function chooseVolume(path, target = 'storage') {
    if (!path) return
    if (target === 'storage') setRoot(joinPath(path, 'Storage'))
    else {
      const current = sourceScope.trim()
      setSourceScope(current ? `${current}\n${path}` : path)
    }
  }

  const running = job && !TERMINAL_PLAN.has(job.status)
  const selectedVolume = roots.find(item => root.toLowerCase().startsWith(item.path.toLowerCase()))?.path || ''
  const fileWritesAllowed = Boolean(fileWrite?.allowed)
  const page = plan?.page || { offset: 0, limit: pageLimit, filtered: plan?.items?.length || 0, total: plan?.total_items || 0 }
  const hasPrev = page.offset > 0
  const hasNext = page.offset + page.returned < page.filtered

  return <div className="stack admin-workbench">
    <Panel title="Storage policy classes">
      <div className="class-grid">{classes.map(item => <div key={item.key}><b>{item.title}</b><small>{item.relative_root}</small><p>{item.description}</p></div>)}</div>
    </Panel>

    <Panel title="Managed Import / Placement Planner">
      <div className="managed-import-grid">
        <div>
          <label>Целевой HDD / том</label>
          <select value={selectedVolume} onChange={e => chooseVolume(e.target.value, 'storage')}>
            <option value="">Выбрать локальный том…</option>
            {roots.map(item => <option key={item.path} value={item.path}>
              {item.path} · {item.filesystem || 'FS'} · {item.free != null ? fmtBytes(item.free) + ' free' : '—'}
            </option>)}
          </select>
          <label>Managed root</label>
          <input value={root} onChange={e => setRoot(e.target.value)} placeholder="W:\\Storage" />
          <small>Выбираешь том, DiskShell предлагает его Storage-root. Путь можно поправить вручную.</small>
        </div>
        <div>
          <label>Source scope на SSD · по одному пути в строке</label>
          <div className="inline-picker">
            <select defaultValue="" onChange={e => { chooseVolume(e.target.value, 'source'); e.target.value = '' }}>
              <option value="">+ добавить том в Source scope…</option>
              {roots.map(item => <option key={item.path} value={item.path}>{item.path} · {item.filesystem || 'FS'}</option>)}
            </select>
          </div>
          <textarea value={sourceScope} onChange={e => setSourceScope(e.target.value)} placeholder={'F:\\fromDisk\nF:\\inst'} />
          <small>Пусто = весь scan. Для большого scan лучше явно выбрать папки/том, которые переносим.</small>
        </div>
        <div>
          <label>Exclude scope · по одному пути в строке</label>
          <textarea value={excludeScope} onChange={e => setExcludeScope(e.target.value)} placeholder={'F:\\work\nF:\\VM-active'} />
          <small>Project/data-dir и target Storage backend исключает автоматически.</small>
        </div>
      </div>

      <div className="actions placement-primary-actions">
        <button className="primary" disabled={!scanId || running || !root.trim()} onClick={build}>Построить Managed Import из scan {scanId || '—'}</button>
        <label className={`disk-write-toggle ${fileWritesAllowed ? 'enabled' : 'locked'}`}>
          <input type="checkbox" checked={fileWritesAllowed} onChange={toggleFileWrites} />
          <span className="toggle-track"><i /></span>
          <span className="toggle-copy">
            <b>{fileWritesAllowed ? 'FILE WRITE ENABLED' : 'FILE WRITE LOCKED'}</b>
            <small>{fileWrite?.global_override ? 'DS_ALLOW_FILE_WRITES=1' : 'RAM toggle · until backend restart'}</small>
          </span>
        </label>
      </div>

      <p className="muted">Plan классифицирует данные и готовит перенос в HDD-папки. Cross-volume: chunked copy → integrity verify → publish; исходник сохраняется. После publish DiskShell read-only проверяет фактические NTFS extents относительно macro-band policy.</p>

      {plan && <>
        <div className="metrics">
          <Metric label="Plan" value={`#${plan.id} · ${plan.status}`} />
          <Metric label="Всего items" value={plan.total_items} />
          <Metric label="Выбрано" value={plan.selected_items ?? 0} />
          <Metric label="Выбрано данных" value={fmtBytes(plan.selected_bytes || 0)} />
          <Metric label="SSD → HDD выбрано" value={plan.selected_cross_volume_items ?? 0} />
          <Metric label="Нужно на HDD" value={fmtBytes(plan.selected_additional_target_bytes || 0)} />
          <Metric label="Layout OK" value={plan.layout_checks?.conforming ?? 0} />
          <Metric label="Layout drift" value={plan.layout_checks?.drift ?? 0} />
        </div>

        {plan.scope && <div className="scope-summary">
          <span>В scope: <b>{plan.scope.selected_files}</b></span>
          <span>Вне scope: <b>{plan.scope.skipped_outside_scope}</b></span>
          <span>Excluded: <b>{plan.scope.skipped_excluded}</b></span>
        </div>}

        {plan.warnings?.map(w => <p className="warning" key={w}>{w} <small>(warning построен для полного draft; выбранный batch повторно проверяется перед execution)</small></p>)}

        <div className="plan-toolbar">
          <input
            value={planQuery}
            onChange={e => setPlanQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') searchPlan() }}
            placeholder="Фильтр по source / target / class"
          />
          <button onClick={searchPlan}>Найти</button>
          <button disabled={running} onClick={() => changeSelection(true, [], true)}>☑ Выбрать все {planQuery ? 'в фильтре' : ''}</button>
          <button disabled={running} onClick={() => changeSelection(false, [], true)}>☐ Снять все {planQuery ? 'в фильтре' : ''}</button>
          <span>{page.filtered} matches · {page.offset + 1}-{Math.min(page.offset + page.returned, page.filtered)}</span>
          <button disabled={!hasPrev} onClick={() => reloadPlan(Math.max(0, page.offset - page.limit), planQuery)}>←</button>
          <button disabled={!hasNext} onClick={() => reloadPlan(page.offset + page.limit, planQuery)}>→</button>
        </div>

        <div className="plan managed-plan selectable-plan">
          {(plan.items || []).map(item => {
            const layout = item.layout_verification
            const layoutText = layout
              ? layout.status === 'conforming'
                ? `layout OK · ${layout.actual_extents}/~${layout.expected_extents} extents`
                : layout.status === 'drift'
                  ? `DRIFT · ${layout.actual_extents}/~${layout.expected_extents} extents`
                  : `layout ${layout.status}`
              : 'layout not checked'
            return <div key={item.id} className={`${item.status} ${item.selected ? 'selected-plan-item' : 'unselected-plan-item'}`}>
              <label className="plan-check">
                <input
                  type="checkbox"
                  checked={Boolean(item.selected)}
                  disabled={running}
                  onChange={e => changeSelection(e.target.checked, [item.id], false)}
                />
              </label>
              <span title={item.source_path}>{item.source_path}</span>
              <b>→ {item.target_class}</b>
              <span title="Planned macro-band policy; not physical platter geometry">{item.layout_lane || '—'} · {item.target_band_bytes ? fmtBytes(item.target_band_bytes) : '—'}</span>
              <span>{item.action}</span>
              <span>{fmtBytes(item.size)}</span>
              <span className={layout?.status === 'drift' ? 'layout-drift' : layout?.status === 'conforming' ? 'layout-ok' : 'muted'}>{layoutText}</span>
              <span>{item.verification || ''}</span>
            </div>
          })}
        </div>

        <div className="apply-box">
          <p><b>Integrity:</b> выбирается Size или SHA-256. <b>Layout:</b> после успешного publish Windows/NTFS extent map сравнивается с ожидаемым macro-band count. Это логические NTFS extents, не скрытая геометрия пластин.</p>
          <select value={verify} onChange={e => setVerify(e.target.value)}>
            <option value="size">Integrity: Verify size</option>
            <option value="sha256">Integrity: Verify SHA-256</option>
          </select>
          <label>Для применения выбранного batch введи: <b>{plan.confirmation}</b></label>
          <input value={confirmation} onChange={e => setConfirmation(e.target.value)} />
          <div className="actions">
            <button className="primary" disabled={!fileWritesAllowed || !plan.selected_items || confirmation !== plan.confirmation || running} onClick={apply}>
              Применить выбранные {plan.selected_items || 0} items
            </button>
            <button className="stop-button" disabled={!running || !jobId} onClick={stop}>■ Stop</button>
          </div>
          {!fileWritesAllowed && <small>FILE WRITE LOCKED — план строится, но execution выключен. Включи RAM-тумблер выше.</small>}
        </div>
      </>}

      {job && <>
        <JobProgress
          percent={job.progress_percent}
          running={running}
          label={job.total_bytes ? `${fmtBytes(job.processed_bytes || 0)} / ${fmtBytes(job.total_bytes)}` : 'Подготовка выбранного batch'}
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


export function DiagnosticsAdmin({ setError, workspaceViewState = {}, patchViewState }) {
  const [disks, setDisks] = useState([])
  const [elevated, setElevated] = useState(null)
  const [diskNumber, setDiskNumber] = useState(workspaceViewState.diagnosticDisk || localStorage.getItem('diagnosticDisk') || '')
  const [mode, setMode] = useState(workspaceViewState.diagnosticMode || localStorage.getItem('diagnosticMode') || 'quick')
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
  useEffect(() => {
    if (diskNumber !== '') {
      localStorage.setItem('diagnosticDisk', diskNumber)
      patchViewState?.({ diagnosticDisk: diskNumber })
    }
  }, [diskNumber, patchViewState])
  useEffect(() => {
    localStorage.setItem('diagnosticMode', mode)
    patchViewState?.({ diagnosticMode: mode })
  }, [mode, patchViewState])

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

export function SecurityAdmin({ setError, workspaceViewState = {}, patchViewState }) {
  const [engines, setEngines] = useState([])
  const [engine, setEngine] = useState('auto')
  const [path, setPath] = useState(workspaceViewState.securityPath || localStorage.getItem('securityPath') || 'F:\\')
  const [roots, setRoots] = useState([])
  const [jobId, setJobId] = useState(localStorage.getItem('securityJobId') || '')
  const [job, setJob] = useState(null)
  const [results, setResults] = useState([])

  const terminal = useMemo(() => new Set(['clean', 'threats_found', 'error', 'cancelled']), [])

  const refresh = async () => {
    const [caps, history, rootData] = await Promise.all([
      api('/api/security/engines'),
      api('/api/security/results'),
      api('/api/files/roots'),
    ])
    setEngines(caps.engines || [])
    setResults(history.results || [])
    setRoots(rootData.roots || [])
  }

  useEffect(() => { refresh().catch(e => setError(e.message)) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    localStorage.setItem('securityPath', path)
    patchViewState?.({ securityPath: path })
  }, [path, patchViewState])

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
      <label>Локальный том</label>
      <select value={roots.some(item => item.path === path) ? path : ''} onChange={e => e.target.value && setPath(e.target.value)}>
        <option value="">Выбрать том…</option>
        {roots.map(item => <option key={item.path} value={item.path}>{item.path} · {item.filesystem || 'FS'}</option>)}
      </select>
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

function paneSelectedItems(pane) {
  const items = pane.data?.items || []
  const paths = new Set(pane.selectedPaths || [])
  if (paths.size) return items.filter(item => paths.has(item.path))
  return pane.selected ? [pane.selected] : []
}

function selectedItemsBytes(items) {
  return items.reduce((total, item) => {
    if (item.is_dir && !item.size_known) return total
    return total + Number(item.size || 0)
  }, 0)
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
  selectAll,
  clearSelection,
  connectRemote,
  disconnectRemote,
}) {
  const remote = state.sourceType !== 'local'
  const profile = connections.find(item => item.id === state.connectionId)
  const form = state.remoteForm || {}
  const selectedItems = paneSelectedItems(state)
  const selectedPaths = new Set(state.selectedPaths || [])
  const selectedBytes = selectedItemsBytes(selectedItems)
  const unknownDirectorySizes = selectedItems.filter(
    item => item.is_dir && !item.size_known,
  ).length

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
            selectedPaths: [],
            anchorPath: null,
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
        {roots.map(root => <option key={root.path} value={root.path} disabled={root.available === false}>
          {root.path} · {root.available === false ? 'OFFLINE' : (root.filesystem || 'FS')} · {root.free != null ? fmtBytes(root.free) + ' free' : '—'}
        </option>)}
      </select>}

      {remote && profile && <div className="remote-session-chip">
        <b>{profile.protocol.toUpperCase()}</b>
        <span>{profile.username}@{profile.host}:{profile.port}</span>
        <button disabled={busy} onClick={() => disconnectRemote(side, state)}>Disconnect</button>
      </div>}
    </div>

    {!remote && state.endpointStatus?.state === 'offline' && <div className="warning">
      <b>Local volume offline.</b> {state.endpointStatus.root || state.endpointStatus.path}
      {' '}— панель сохранит путь; после подключения диска нажми ↻. Активный transfer job продолжится автоматически.
    </div>}

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

    <div className="commander-selection-toolbar">
      <div>
        <button disabled={busy || !(state.data?.items?.length)} onClick={() => selectAll(side)}>☑ Select all</button>
        <button disabled={busy || selectedItems.length === 0} onClick={() => clearSelection(side)}>☐ Clear</button>
      </div>
      <span>
        {selectedItems.length} selected · {fmtBytes(selectedBytes)}
        {unknownDirectorySizes ? ` + ${unknownDirectorySizes} folder(s) without indexed size` : ''}
      </span>
      <small>Ctrl+Click · Shift+Click · Ctrl+A</small>
    </div>

    <div className="commander-columns"><span>Sel</span><span>Name</span><span>Size</span><span>Modified</span></div>
    <div className="file-list commander-list">
      {(state.data?.items || []).slice(0, 4000).map(item => {
        const checked = selectedPaths.has(item.path)
        return <button
          key={item.path}
          className={checked ? 'selected' : ''}
          onClick={event => choose(side, item, event)}
          onDoubleClick={() => item.is_dir && !busy && load(side, item.path)}
        >
          <span
            className="commander-select-mark"
            title={checked ? 'Убрать из выделения' : 'Добавить к выделению'}
            onClick={event => {
              event.stopPropagation()
              choose(side, item, { ctrlKey: true })
            }}
          >{checked ? '☑' : '☐'}</span>
          <span title={item.path}>{item.is_dir ? '📁' : '📄'} {item.name}</span>
          <span title={item.is_dir && item.size_known ? `indexed by scan ${item.indexed_scan_id}` : ''}>
            {item.is_dir ? (item.size_known ? fmtBytes(item.size) : '—') : fmtBytes(item.size)}
          </span>
          <span>{item.modified_ns ? new Date(item.modified_ns / 1e6).toLocaleString() : ''}</span>
        </button>
      })}
    </div>
    <div className="pane-status">
      <span>{state.data?.items?.length || 0} items</span>
      <span>{selectedItems.length
        ? `${selectedItems.length} selected · ${fmtBytes(selectedBytes)}${unknownDirectorySizes ? ' + unknown folder sizes' : ''}`
        : 'nothing selected'}</span>
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

export function FilesAdmin({ health, scanId, setError, refreshHealth, workspaceViewState = {}, patchViewState }) {
  const makePane = (side) => ({
    sourceType: 'local',
    path: workspaceViewState[`file${side}Path`] || localStorage.getItem(`file${side}Path`) || 'F:\\',
    data: null,
    selected: null,
    selectedPaths: [],
    anchorPath: null,
    connectionId: '',
    endpointStatus: null,
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
  const [activeSide, setActiveSide] = useState(
    () => (workspaceViewState.commanderActiveSide || localStorage.getItem('commanderActiveSide')) === 'right' ? 'right' : 'left',
  )
  const [roots, setRoots] = useState([])
  const [connections, setConnections] = useState([])
  const [jobId, setJobId] = useState(localStorage.getItem('commanderJobId') || '')
  const [job, setJob] = useState(null)
  const [smartTransfer, setSmartTransfer] = useState(
    () => workspaceViewState.commanderSmartFolders != null
      ? Boolean(workspaceViewState.commanderSmartFolders)
      : localStorage.getItem('commanderSmartFolders') === '1',
  )
  const [smartHint, setSmartHint] = useState(null)
  const [preview, setPreview] = useState(null)
  const [archive, setArchive] = useState(null)
  const [remoteOrigin, setRemoteOrigin] = useState('')
  const [archiveFormat, setArchiveFormat] = useState(
    () => workspaceViewState.commanderArchiveFormat || localStorage.getItem('commanderArchiveFormat') || 'zip',
  )
  const [fileWrite, setFileWrite] = useState(null)
  const [pendingConflict, setPendingConflict] = useState(null)

  const terminal = useMemo(() => new Set(['completed', 'failed', 'cancelled']), [])
  const activePane = activeSide === 'left' ? left : right
  const passivePane = activeSide === 'left' ? right : left

  async function refreshMeta() {
    try {
      const [rootData, connectionData, writeData] = await Promise.all([
        api('/api/files/roots'),
        api('/api/commander/connections'),
        api('/api/files/write-access'),
      ])
      setRoots(rootData.roots || [])
      setConnections(connectionData.connections || [])
      setFileWrite(writeData)
    } catch (e) { setError(e.message) }
  }


  async function toggleFileWrites() {
    try {
      const next = await api('/api/files/write-access', {
        method: 'POST',
        body: JSON.stringify({ enabled: !fileWrite?.allowed }),
      })
      setFileWrite(next)
      if (refreshHealth) await refreshHealth()
    } catch (e) {
      setError(e.message)
    }
  }

  async function load(side, path, forcedPane = null) {
    const pane = forcedPane || (side === 'left' ? left : right)
    try {
      const scanQuery = scanId ? `&scan_id=${encodeURIComponent(scanId)}` : ''
      const data = pane.sourceType === 'local'
        ? await api(`/api/files?path=${encodeURIComponent(path)}${scanQuery}`)
        : await api(`/api/commander/remote?connection_id=${encodeURIComponent(pane.connectionId)}&path=${encodeURIComponent(path)}`)
      const next = {
        ...pane,
        path: data.path,
        data,
        selected: null,
        selectedPaths: [],
        anchorPath: null,
        endpointStatus: null,
      }
      if (side === 'left') {
        setLeft(next)
        if (next.sourceType === 'local') {
          localStorage.setItem('fileLeftPath', data.path)
          patchViewState?.({ fileLeftPath: data.path })
        }
      } else {
        setRight(next)
        if (next.sourceType === 'local') {
          localStorage.setItem('fileRightPath', data.path)
          patchViewState?.({ fileRightPath: data.path })
        }
      }
    } catch (e) {
      if (e.status === 409 && e.payload?.error === 'endpoint_unavailable') {
        const setter = side === 'left' ? setLeft : setRight
        setter(current => ({
          ...current,
          data: null,
          selected: null,
          selectedPaths: [],
          anchorPath: null,
          endpointStatus: {
            state: 'offline',
            path,
            root: e.payload?.root || '',
            message: e.message,
          },
        }))
        return
      }
      setError(e.message)
    }
  }

  function choose(side, item, event = null) {
    const ctrl = Boolean(event?.ctrlKey || event?.metaKey)
    const shift = Boolean(event?.shiftKey)
    setActiveSide(side)
    setPreview(null)
    setArchive(null)
    setRemoteOrigin('')

    const setter = side === 'left' ? setLeft : setRight
    setter(current => {
      const items = current.data?.items || []
      const existing = new Set(current.selectedPaths || [])
      let nextPaths = []
      let anchorPath = current.anchorPath

      if (shift && anchorPath) {
        const anchorIndex = items.findIndex(row => row.path === anchorPath)
        const currentIndex = items.findIndex(row => row.path === item.path)
        if (anchorIndex >= 0 && currentIndex >= 0) {
          const [from, to] = anchorIndex <= currentIndex
            ? [anchorIndex, currentIndex]
            : [currentIndex, anchorIndex]
          const range = items.slice(from, to + 1).map(row => row.path)
          nextPaths = ctrl
            ? Array.from(new Set([...existing, ...range]))
            : range
        } else {
          nextPaths = [item.path]
          anchorPath = item.path
        }
      } else if (ctrl) {
        if (existing.has(item.path)) existing.delete(item.path)
        else existing.add(item.path)
        nextPaths = Array.from(existing)
        anchorPath = item.path
      } else {
        nextPaths = [item.path]
        anchorPath = item.path
      }

      const nextSelected = nextPaths.includes(item.path)
        ? item
        : items.find(row => nextPaths.includes(row.path)) || null

      return {
        ...current,
        selected: nextSelected,
        selectedPaths: nextPaths,
        anchorPath,
      }
    })
  }

  function selectAll(side) {
    setActiveSide(side)
    const setter = side === 'left' ? setLeft : setRight
    setter(current => {
      const items = current.data?.items || []
      return {
        ...current,
        selected: items[0] || null,
        selectedPaths: items.map(item => item.path),
        anchorPath: items[0]?.path || null,
      }
    })
  }

  function clearSelection(side) {
    const setter = side === 'left' ? setLeft : setRight
    setter(current => ({
      ...current,
      selected: null,
      selectedPaths: [],
      anchorPath: null,
    }))
  }

  useEffect(() => {
    refreshMeta()
    load('left', left.path)
    load('right', right.path)
    const timer = setInterval(refreshMeta, 3000)
    return () => clearInterval(timer)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const revive = (side, pane) => {
      if (pane.sourceType !== 'local' || pane.endpointStatus?.state !== 'offline') return
      const root = pane.endpointStatus.root
      if (root && roots.some(item => item.path === root && item.available !== false)) {
        load(side, pane.path, pane)
      }
    }
    revive('left', left)
    revive('right', right)
  }, [roots]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    localStorage.setItem('commanderActiveSide', activeSide)
    patchViewState?.({ commanderActiveSide: activeSide })
  }, [activeSide, patchViewState])
  useEffect(() => {
    localStorage.setItem('commanderSmartFolders', smartTransfer ? '1' : '0')
    patchViewState?.({ commanderSmartFolders: smartTransfer })
  }, [smartTransfer, patchViewState])
  useEffect(() => {
    localStorage.setItem('commanderArchiveFormat', archiveFormat)
    patchViewState?.({ commanderArchiveFormat: archiveFormat })
  }, [archiveFormat, patchViewState])

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
        selectedPaths: [],
        anchorPath: null,
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
      const next = {
        ...pane,
        connectionId: '',
        data: null,
        selected: null,
        selectedPaths: [],
        anchorPath: null,
        path: '/',
      }
      if (side === 'left') setLeft(next)
      else setRight(next)
    } catch (e) { setError(e.message) }
  }

  async function submitTransferRequest(request, conflictPolicy = 'ask') {
    try {
      const value = await api('/api/commander/jobs', {
        method: 'POST',
        body: JSON.stringify({ ...request, conflict_policy: conflictPolicy }),
      })
      setPendingConflict(null)
      setJob(value)
      setJobId(value.id)
      return value
    } catch (e) {
      if (e.status === 409 && e.payload?.error === 'commander_conflict') {
        setPendingConflict({
          request,
          conflicts: e.payload.conflicts || [],
        })
        return null
      }
      throw e
    }
  }

  async function resolveConflict(policy) {
    if (!pendingConflict) return
    try {
      await submitTransferRequest(pendingConflict.request, policy)
    } catch (e) {
      setError(e.message)
    }
  }

  async function retryPartial() {
    if (!job?.transfers?.length) return
    const request = {
      operation: job.operation,
      transfers: job.transfers.map(item => ({
        source: item.source,
        destination: item.destination,
      })),
    }
    try {
      await submitTransferRequest(request, 'resume')
    } catch (e) {
      setError(e.message)
    }
  }

  async function transfer(operation, sourceSide = activeSide) {
    const sourcePane = sourceSide === 'left' ? left : right
    const destinationPane = sourceSide === 'left' ? right : left
    const selectedItems = paneSelectedItems(sourcePane)
    if (!selectedItems.length || !fileWrite?.allowed) return

    try {
      const smartBySource = new Map()
      if (smartTransfer && destinationPane.sourceType === 'local') {
        const files = selectedItems.filter(item => !item.is_dir)
        if (files.length) {
          const batch = await api('/api/files/smart-destinations', {
            method: 'POST',
            body: JSON.stringify({
              storage_root: destinationPane.path,
              items: files.map(item => ({
                name: item.name,
                source_path: item.path,
                size: item.size,
                modified_ns: item.modified_ns,
              })),
            }),
          })
          for (const hint of batch.items || []) {
            smartBySource.set(hint.source_path, hint)
          }
          const firstHint = batch.items?.[0] || null
          setSmartHint(firstHint ? {
            ...firstHint,
            batch_count: batch.items.length,
          } : null)
        } else {
          setSmartHint(null)
        }
      } else {
        setSmartHint(null)
      }

      const transfers = selectedItems.map(item => {
        const hint = smartBySource.get(item.path)
        const destinationPath = hint?.destination || (
          destinationPane.sourceType === 'local'
            ? joinPath(destinationPane.path, item.name)
            : remoteJoin(destinationPane.path, item.name)
        )
        const destination = destinationPane.sourceType === 'local'
          ? { kind: 'local', path: destinationPath }
          : {
              kind: 'remote',
              connection_id: destinationPane.connectionId,
              path: destinationPath,
            }
        return {
          source: paneTarget(sourcePane, item),
          destination,
        }
      })

      await submitTransferRequest({ operation, transfers }, 'ask')
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
    const selectedItems = paneSelectedItems(pane)
    if (selectedItems.length !== 1) return
    const selected = selectedItems[0]
    const name = window.prompt('Rename to', selected.name)
    if (!name || name === selected.name) return
    try {
      const destination = pane.sourceType === 'local'
        ? joinPath(pane.path, name)
        : remoteJoin(pane.path, name)
      if (pane.sourceType === 'local') {
        await api('/api/files/rename', {
          method: 'POST',
          body: JSON.stringify({ source: selected.path, destination }),
        })
      } else {
        await api('/api/commander/remote/rename', {
          method: 'POST',
          body: JSON.stringify({
            connection_id: pane.connectionId,
            source: selected.path,
            destination,
          }),
        })
      }
      await load(activeSide, pane.path)
    } catch (e) { setError(e.message) }
  }

  async function deleteSelected() {
    const pane = activePane
    const selectedItems = paneSelectedItems(pane)
    if (!selectedItems.length) return
    const remote = pane.sourceType !== 'local'
    const message = remote
      ? `DELETE ${selectedItems.length} remote item(s)? Remote delete has no Recycle Bin.`
      : `Move ${selectedItems.length} selected item(s) to Recycle Bin?`
    if (!window.confirm(message)) return

    try {
      for (const selected of selectedItems) {
        if (!remote) {
          await api('/api/files/trash', {
            method: 'POST',
            body: JSON.stringify({ path: selected.path }),
          })
        } else {
          await api('/api/commander/remote/delete', {
            method: 'POST',
            body: JSON.stringify({
              connection_id: pane.connectionId,
              path: selected.path,
              recursive: Boolean(selected.is_dir),
            }),
          })
        }
      }
      await load(activeSide, pane.path)
    } catch (e) { setError(e.message) }
  }

  async function inspectSelected() {
    const pane = activePane
    const selectedItems = paneSelectedItems(pane)
    if (selectedItems.length !== 1) return
    const selected = selectedItems[0]
    if (selected.is_dir) return
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
    const selectedItems = paneSelectedItems(pane)
    if (!selectedItems.length || pane.sourceType !== 'local') {
      setError('Archive creation requires one or more local selected sources')
      return
    }
    const extension = archiveExtension(archiveFormat)
    const base = selectedItems.length === 1
      ? selectedItems[0].name.replace(/\.[^.]+$/, '')
      : `selection-${selectedItems.length}-items`
    const name = window.prompt('Archive file name', `${base}${extension}`)
    if (!name) return
    try {
      await api('/api/content/archive/create', {
        method: 'POST',
        body: JSON.stringify({
          sources: selectedItems.map(item => item.path),
          destination: joinPath(pane.path, name),
          format: archiveFormat,
        }),
      })
      await load(activeSide, pane.path)
    } catch (e) { setError(e.message) }
  }

  async function extractArchive() {
    const pane = activePane
    const selectedItems = paneSelectedItems(pane)
    const destinationPane = passivePane
    if (selectedItems.length !== 1 || pane.sourceType !== 'local' || destinationPane.sourceType !== 'local') {
      setError('Extract requires exactly one local archive and a local destination pane')
      return
    }
    const selected = selectedItems[0]
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
  const fileWritesAllowed = Boolean(fileWrite?.allowed)
  const leftSelection = paneSelectedItems(left)
  const rightSelection = paneSelectedItems(right)
  const activeSelection = activeSide === 'left' ? leftSelection : rightSelection
  const directTarget = (sourceSide) => {
    const sourcePane = sourceSide === 'left' ? left : right
    const targetPane = sourceSide === 'left' ? right : left
    const selectedItems = sourceSide === 'left' ? leftSelection : rightSelection
    if (!selectedItems.length) return 'выбери файл/папку'
    if (selectedItems.length > 1) {
      return `${selectedItems.length} items → ${targetPane.path}`
    }
    const selected = selectedItems[0]
    const target = targetPane.sourceType === 'local'
      ? joinPath(targetPane.path, selected.name)
      : remoteJoin(targetPane.path, selected.name)
    return `${selected.path} → ${target}`
  }

  useEffect(() => {
    const handler = event => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
        event.preventDefault()
        selectAll(activeSide)
      } else if (event.key === 'Tab') {
        event.preventDefault()
        setActiveSide(side => side === 'left' ? 'right' : 'left')
      } else if (event.key === 'F2') {
        event.preventDefault(); renameSelected()
      } else if (event.key === 'F3') {
        event.preventDefault(); inspectSelected()
      } else if (event.key === 'F5') {
        event.preventDefault(); transfer('copy', activeSide)
      } else if (event.key === 'F6') {
        event.preventDefault(); transfer('move', activeSide)
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
      <label className={`disk-write-toggle ${fileWritesAllowed ? 'enabled' : 'locked'}`}>
        <input type="checkbox" checked={fileWritesAllowed} onChange={toggleFileWrites} />
        <span className="toggle-track"><i /></span>
        <span className="toggle-copy">
          <b>{fileWritesAllowed ? 'FILE WRITE ENABLED' : 'FILE WRITE LOCKED'}</b>
          <small>{fileWrite?.global_override ? 'DS_ALLOW_FILE_WRITES=1' : 'RAM toggle · until backend restart'}</small>
        </span>
      </label>
      <label className="smart-transfer-toggle">
        <input
          type="checkbox"
          checked={smartTransfer}
          onChange={e => setSmartTransfer(e.target.checked)}
        />
        <span><b>Smart folders</b><small>OFF = exact destination · ON = classify into HDD folders; no forced extent layout</small></span>
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
          selectAll={selectAll}
          clearSelection={clearSelection}
          connectRemote={connectRemote}
          disconnectRemote={disconnectRemote}
        />
      </div>

      <div className="file-actions commander-actions">
        <button disabled={activeSelection.length !== 1 || activeSelection[0]?.is_dir || busy} onClick={inspectSelected}>F3 View</button>
        <small className="transfer-direction" title={directTarget('left')}>{directTarget('left')}</small>
        <button disabled={!fileWritesAllowed || leftSelection.length === 0 || busy} onClick={() => transfer('copy', 'left')}>F5 Copy →</button>
        <button disabled={!fileWritesAllowed || leftSelection.length === 0 || busy} onClick={() => transfer('move', 'left')}>F6 Move →</button>
        <small className="transfer-direction" title={directTarget('right')}>{directTarget('right')}</small>
        <button disabled={!fileWritesAllowed || rightSelection.length === 0 || busy} onClick={() => transfer('copy', 'right')}>← Copy</button>
        <button disabled={!fileWritesAllowed || rightSelection.length === 0 || busy} onClick={() => transfer('move', 'right')}>← Move</button>
        <button disabled={!fileWritesAllowed || busy} onClick={makeDirectory}>F7 MkDir</button>
        <button disabled={!fileWritesAllowed || activeSelection.length !== 1 || busy} onClick={renameSelected}>F2 Rename</button>
        <button className="trash" disabled={!fileWritesAllowed || activeSelection.length === 0 || busy} onClick={deleteSelected}>F8 Trash/Delete</button>
        <button disabled={!fileWritesAllowed || activeSelection.length === 0 || activePane.sourceType !== 'local' || busy} onClick={createArchive}>F9 Archive</button>
        <button disabled={!fileWritesAllowed || activeSelection.length !== 1 || activePane.sourceType !== 'local' || passivePane.sourceType !== 'local' || busy} onClick={extractArchive}>Extract → other</button>
        <button className="stop-button" disabled={!busy || !jobId} onClick={stop}>■ Stop / keep partial</button>
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
          selectAll={selectAll}
          clearSelection={clearSelection}
          connectRemote={connectRemote}
          disconnectRemote={disconnectRemote}
        />
      </div>
    </div>

    {pendingConflict && <Panel title="Destination conflict" className="danger-card">
      <p className="warning">
        Найдено совпадений: <b>{pendingConflict.conflicts.length}</b>. Автоматической перезаписи нет — выбери действие.
      </p>
      <div className="archive-list">
        {pendingConflict.conflicts.slice(0, 12).map((item, index) => <div key={`${item.destination?.path || 'conflict'}-${index}`}>
          <span>
            {item.destination?.path}
            {item.can_resume ? ' · partial/size resume available' : ''}
            {item.same_as_source ? ' · source = destination' : ''}
          </span>
          <span>{item.destination_size == null ? '' : fmtBytes(item.destination_size)}</span>
        </div>)}
      </div>
      {pendingConflict.conflicts.length > 12 && <p className="muted">
        Ещё {pendingConflict.conflicts.length - 12} конфликтов. Выбранная политика применяется ко всему batch.
      </p>}
      <div className="actions">
        <button
          className="primary"
          disabled={!pendingConflict.conflicts.length || pendingConflict.conflicts.some(item => !item.can_resume)}
          onClick={() => resolveConflict('resume')}
        >
          Continue partial
        </button>
        <button
          className="danger-button"
          disabled={pendingConflict.conflicts.some(item => item.same_as_source)}
          onClick={() => resolveConflict('replace')}
        >
          Replace all
        </button>
        <button onClick={() => resolveConflict('keep_both')}>
          Keep both · add (1)
        </button>
        <button onClick={() => resolveConflict('skip')}>
          Skip conflicts
        </button>
        <button onClick={() => setPendingConflict(null)}>Cancel</button>
      </div>
      <p className="muted">
        Continue использует фактический размер уже существующего target. Keep both создаёт следующий свободный индекс: name (1), name (2), …
      </p>
    </Panel>}

    {smartTransfer && <Panel title="Smart transfer policy">
      <p><b>Smart folders не означает шахматную фрагментацию.</b> Этот режим меняет только папку назначения по Storage Class. Direct transfer всегда остаётся доступным. Фактическую NTFS-нарезку проверяет Storage Brain / Storage Lab после managed transfer.</p>
      {smartHint && <div className="metrics">
        <Metric label="Class" value={smartHint.target_class} />
        <Metric label="Category" value={smartHint.category} />
        <Metric label="Lane" value={smartHint.layout_lane} />
        <Metric label="Target band" value={fmtBytes(smartHint.target_band_bytes)} />
        <Metric label="Batch classified" value={smartHint.batch_count || 1} />
      </div>}
      {smartHint && <p className="path">{smartHint.destination}</p>}
      <p className="muted">Принудительный extent-placement пока выключен. Проверка фактических NTFS extents уже read-only; writer/rebalancer будет отдельным следующим этапом.</p>
    </Panel>}

    <Panel title="Commander transfer job">
      {!job && <p className="muted">F5/F6 use one batch background job for all selected local/SFTP/FTP items. Stop keeps the incomplete target so it can be continued later; already completed batch items remain complete.</p>}
      {job && <>
        <div className="metrics">
          <Metric label="Operation" value={job.operation} />
          <Metric label="Status" value={job.status} />
          <Metric label="Items" value={`${job.items || 0}/${job.total_items || 1}`} />
          <Metric label="Files" value={`${job.files || 0}/${job.total_files || 0}`} />
          <Metric label="Transferred" value={fmtBytes(job.bytes || 0)} />
          <Metric label="Reconnects" value={job.retries || 0} />
          <Metric label="Auto resumes" value={job.auto_resumes || 0} />
          <Metric label="Missing" value={job.missing || 0} />
          <Metric label="Skipped" value={job.skipped || 0} />
        </div>
        <JobProgress
          percent={job.progress_percent}
          running={busy}
          label={`${fmtBytes(job.bytes || 0)} / ${fmtBytes(job.total_bytes || 0)}`}
        />
        <p className="path">{job.current_path}</p>
        {job.waiting_endpoint && <div className="warning">
          <b>Transfer paused · waiting for endpoint.</b>
          {(job.waiting_for || []).map((item, index) => <div key={`${item.role}-${item.path}-${index}`}>
            {item.role}: {item.path} · {item.reason}
            {item.reason === 'volume_identity_mismatch' ? ' · другой носитель с этой буквой не будет использован' : ''}
          </div>)}
          <small>Backend проверяет endpoint каждые несколько секунд и продолжит с фактического partial offset. Stop оставит partial.</small>
        </div>}
        {job.retrying && <p className="warning">
          Connection interrupted — reconnect {job.retry_attempt}/{job.retry_limit}.
          Resume from approximately {fmtBytes(job.resume_offset || 0)}; completed bytes are not restarted.
          {job.last_retry_error ? ` Last error: ${job.last_retry_error}` : ''}
        </p>}
        {job.partial_retained && <div className="actions">
          <button className="primary" disabled={busy} onClick={retryPartial}>
            Continue partial
          </button>
          <small>Partial target сохранён: {job.partial_path}</small>
        </div>}
        {(job.warnings || []).slice(-8).map((item, index) => <p className="muted" key={`${item}-${index}`}>• {item}</p>)}
        {job.error && <p className="warning">{job.error}</p>}
      </>}
      {!fileWritesAllowed && <small>FILE WRITE LOCKED — Copy/Move/MkDir/Rename/Delete/Archive отключены. Включи тумблер сверху.</small>}
    </Panel>

    <CommanderInspector preview={preview} archive={archive} remoteOrigin={remoteOrigin} />
  </div>
}
