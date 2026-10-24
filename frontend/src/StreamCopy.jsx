import React, { useEffect, useMemo, useState } from 'react'
import { api, eventStreamUrl, fmtBytes } from './api.js'
import './StreamCopy.css'

const MEDIA = [
  ['hdd', 'HDD · механический'],
  ['ssd', 'SSD / NVMe'],
  ['flash', 'USB flash / карта'],
]

const ENDPOINT = [
  ['local', 'Local volume'],
  ['remote', 'SFTP'],
]

const TRANSPORT = [
  ['network', 'Network / SFTP'],
  ['usb3', 'USB 3.x'],
  ['usb2', 'USB 2.0'],
  ['usb4', 'USB4 / Thunderbolt'],
  ['internal', 'Internal SATA/NVMe'],
  ['unknown', 'Неизвестно'],
]

const TOPOLOGY = [
  ['unknown', 'Неизвестно'],
  ['separate', 'Разные USB paths / контроллеры'],
  ['shared', 'Общий hub / controller'],
]

const ORDERING = [
  ['manifest', 'Manifest / directory order'],
  ['ntfs_locality', 'NTFS first-LCN locality · EXP'],
]

const TERMINAL = new Set(['completed', 'completed_with_warnings', 'failed', 'cancelled'])

function saved(key, fallback) {
  return localStorage.getItem(`streamcopy:${key}`) || fallback
}

function Band({ role, title, children, tone = '' }) {
  return <section className={`stream-band ${tone}`}>
    <div className="stream-band-title">
      <small>{role}</small>
      <b>{title}</b>
    </div>
    <div className="stream-band-body">{children}</div>
  </section>
}

function SelectField({ label, value, onChange, options, disabled = false }) {
  return <label>
    <span>{label}</span>
    <select value={value} onChange={e => onChange(e.target.value)} disabled={disabled}>
      {options.map(([key, title]) => <option key={key} value={key}>{title}</option>)}
    </select>
  </label>
}

export default function StreamCopy({ health, setError, refreshHealth }) {
  const [sourcePath, setSourcePath] = useState(() => saved('sourcePath', 'H:\\'))
  const [destinationPath, setDestinationPath] = useState(() => saved('destinationPath', 'W:\\'))
  const [sourceKind, setSourceKind] = useState(() => saved('sourceKind', 'local'))
  const [destinationKind, setDestinationKind] = useState(() => saved('destinationKind', 'local'))
  const [sourceConnectionId, setSourceConnectionId] = useState(() => saved('sourceConnectionId', ''))
  const [destinationConnectionId, setDestinationConnectionId] = useState(() => saved('destinationConnectionId', ''))
  const [connections, setConnections] = useState([])
  const [sourceMedia, setSourceMedia] = useState(() => saved('sourceMedia', 'hdd'))
  const [destinationMedia, setDestinationMedia] = useState(() => saved('destinationMedia', 'hdd'))
  const [sourceTransport, setSourceTransport] = useState(() => saved('sourceTransport', 'usb3'))
  const [destinationTransport, setDestinationTransport] = useState(() => saved('destinationTransport', 'usb3'))
  const [usbTopology, setUsbTopology] = useState(() => saved('usbTopology', 'unknown'))
  const [sourceCacheMiB, setSourceCacheMiB] = useState(() => saved('sourceCacheMiB', '32'))
  const [destinationCacheMiB, setDestinationCacheMiB] = useState(() => saved('destinationCacheMiB', '128'))
  const [orderingMode, setOrderingMode] = useState(() => saved('orderingMode', 'manifest'))
  const [verifyMode, setVerifyMode] = useState(() => saved('verifyMode', 'size'))
  const [deleteSourceAfterVerify, setDeleteSourceAfterVerify] = useState(
    () => saved('deleteSourceAfterVerify', 'false') === 'true',
  )
  const [profile, setProfile] = useState(null)
  const [job, setJob] = useState(null)
  const [busy, setBusy] = useState(false)
  const [restoringJob, setRestoringJob] = useState(true)
  const running = job && !TERMINAL.has(job.status)

  const effectiveSourceTransport = sourceKind === 'remote' ? 'network' : sourceTransport
  const effectiveDestinationTransport = destinationKind === 'remote' ? 'network' : destinationTransport
  const localityEligible = sourceKind === 'local' && sourceMedia === 'hdd'
  const effectiveOrderingMode = localityEligible ? orderingMode : 'manifest'

  const payload = useMemo(() => ({
    source_media: sourceMedia,
    destination_media: destinationMedia,
    source_transport: effectiveSourceTransport,
    destination_transport: effectiveDestinationTransport,
    usb_topology: usbTopology,
    source_cache_mib: Number(sourceCacheMiB || 0),
    destination_cache_mib: Number(destinationCacheMiB || 0),
    ordering_mode: effectiveOrderingMode,
  }), [
    sourceMedia,
    destinationMedia,
    effectiveSourceTransport,
    effectiveDestinationTransport,
    usbTopology,
    sourceCacheMiB,
    destinationCacheMiB,
    effectiveOrderingMode,
    verifyMode,
    deleteSourceAfterVerify,
  ])

  useEffect(() => {
    let stopped = false

    const adopt = next => {
      if (!next || stopped) return
      setJob(next)
      setSourcePath(next.source_path || sourcePath)
      setDestinationPath(next.destination_path || destinationPath)
      setSourceKind(next.source_kind || 'local')
      setDestinationKind(next.destination_kind || 'local')
      const nextProfile = next.profile || {}
      if (nextProfile.source_media) setSourceMedia(nextProfile.source_media)
      if (nextProfile.destination_media) setDestinationMedia(nextProfile.destination_media)
      if (nextProfile.source_transport) setSourceTransport(nextProfile.source_transport)
      if (nextProfile.destination_transport) setDestinationTransport(nextProfile.destination_transport)
      if (nextProfile.usb_topology) setUsbTopology(nextProfile.usb_topology)
      if (nextProfile.source_cache_mib != null) setSourceCacheMiB(String(nextProfile.source_cache_mib))
      if (nextProfile.destination_cache_mib != null) setDestinationCacheMiB(String(nextProfile.destination_cache_mib))
      if (nextProfile.ordering_requested || nextProfile.ordering_mode) {
        setOrderingMode(nextProfile.ordering_requested || nextProfile.ordering_mode)
      }
      if (next.verify_mode) setVerifyMode(next.verify_mode)
      setDeleteSourceAfterVerify(Boolean(next.delete_source_after_verify))
    }

    const restore = async () => {
      let recovered = null
      const activeJobId = localStorage.getItem('streamcopy:activeJobId')

      if (activeJobId) {
        try {
          const candidate = await api(`/api/streamcopy/jobs/${activeJobId}`)
          if (!TERMINAL.has(candidate.status)) recovered = candidate
        } catch (e) {
          if (e.status !== 404 && !stopped) setError(e.message)
        }
      }

      if (!recovered) {
        try {
          const value = await api('/api/streamcopy/jobs?active=1&limit=1')
          recovered = Array.isArray(value.jobs) ? value.jobs[0] : null
        } catch (e) {
          if (!stopped) setError(e.message)
        }
      }

      if (recovered) {
        localStorage.setItem('streamcopy:activeJobId', recovered.id)
        localStorage.setItem('streamcopy:lastJobId', recovered.id)
        adopt(recovered)
      } else {
        localStorage.removeItem('streamcopy:activeJobId')
        const lastJobId = localStorage.getItem('streamcopy:lastJobId')
        if (lastJobId) {
          try {
            recovered = await api(`/api/streamcopy/jobs/${lastJobId}`)
          } catch (e) {
            if (e.status === 404) localStorage.removeItem('streamcopy:lastJobId')
            else if (!stopped) setError(e.message)
          }
        }

        if (!recovered) {
          try {
            const value = await api('/api/streamcopy/jobs?limit=1')
            recovered = Array.isArray(value.jobs) ? value.jobs[0] : null
          } catch (e) {
            if (!stopped) setError(e.message)
          }
        }

        if (recovered) {
          localStorage.setItem('streamcopy:lastJobId', recovered.id)
          adopt(recovered)
        }
      }

      if (!stopped) setRestoringJob(false)
    }

    restore()
    return () => { stopped = true }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const refreshConnections = async () => {
    try {
      const value = await api('/api/commander/connections')
      const next = (value.connections || []).filter(item => item.protocol === 'sftp')
      setConnections(next)
      setSourceConnectionId(current => next.some(item => item.id === current) ? current : '')
      setDestinationConnectionId(current => next.some(item => item.id === current) ? current : '')
    } catch {
      setConnections([])
    }
  }

  useEffect(() => {
    refreshConnections()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (job?.source_remote_identity) {
      const match = connections.find(item => item.identity === job.source_remote_identity)
      if (match) setSourceConnectionId(match.id)
    }
    if (job?.destination_remote_identity) {
      const match = connections.find(item => item.identity === job.destination_remote_identity)
      if (match) setDestinationConnectionId(match.id)
    }
  }, [connections, job?.source_remote_identity, job?.destination_remote_identity])

  useEffect(() => {
    if (!job?.id) return
    localStorage.setItem('streamcopy:lastJobId', job.id)
    if (TERMINAL.has(job.status)) {
      if (localStorage.getItem('streamcopy:activeJobId') === job.id) {
        localStorage.removeItem('streamcopy:activeJobId')
      }
    } else {
      localStorage.setItem('streamcopy:activeJobId', job.id)
    }
  }, [job?.id, job?.status])

  useEffect(() => {
    for (const [key, value] of Object.entries({
      sourcePath,
      destinationPath,
      sourceKind,
      destinationKind,
      sourceConnectionId,
      destinationConnectionId,
      sourceMedia,
      destinationMedia,
      sourceTransport,
      destinationTransport,
      usbTopology,
      sourceCacheMiB,
      destinationCacheMiB,
      orderingMode,
      verifyMode,
      deleteSourceAfterVerify,
    })) localStorage.setItem(`streamcopy:${key}`, String(value))
  }, [
    sourcePath,
    destinationPath,
    sourceKind,
    destinationKind,
    sourceConnectionId,
    destinationConnectionId,
    sourceMedia,
    destinationMedia,
    sourceTransport,
    destinationTransport,
    usbTopology,
    sourceCacheMiB,
    destinationCacheMiB,
    orderingMode,
    verifyMode,
    deleteSourceAfterVerify,
  ])

  useEffect(() => {
    let stale = false
    api('/api/streamcopy/profile', {
      method: 'POST',
      body: JSON.stringify(payload),
    }).then(value => {
      if (!stale) setProfile(value)
    }).catch(e => {
      if (!stale) setError(e.message)
    })
    return () => { stale = true }
  }, [payload, setError])

  useEffect(() => {
    if (!job?.id || TERMINAL.has(job.status)) return undefined
    let stopped = false
    const jobId = job.id

    const reconcile = async () => {
      try {
        const nextJob = await api(`/api/streamcopy/jobs/${jobId}`)
        if (!stopped) setJob(nextJob)
      } catch (e) {
        if (!stopped && e.status === 404) {
          if (localStorage.getItem('streamcopy:activeJobId') === jobId) {
            localStorage.removeItem('streamcopy:activeJobId')
          }
          setJob(null)
          setError('StreamCopy journal не нашёл задачу. Проверь data/diskshell.db и backend log.')
        } else if (!stopped) {
          setError(e.message)
        }
      }
    }

    const source = typeof EventSource === 'undefined'
      ? null
      : new EventSource(eventStreamUrl())

    const applyEvent = event => {
      let payload
      try { payload = JSON.parse(event.data)?.payload || {} } catch { return }
      if (payload.job_id !== jobId || stopped) return
      setJob(current => current ? { ...current, ...payload } : current)
      if (payload.status && TERMINAL.has(payload.status)) reconcile()
    }

    source?.addEventListener('streamcopy.changed', applyEvent)
    source?.addEventListener('streamcopy.progress', applyEvent)
    reconcile()
    const timer = setInterval(reconcile, 10000)

    return () => {
      stopped = true
      clearInterval(timer)
      source?.close()
    }
  }, [job?.id, job?.status, setError])

  async function toggleWrites() {
    try {
      await api('/api/files/write-access', {
        method: 'POST',
        body: JSON.stringify({ enabled: !health?.safety?.file_writes }),
      })
      await refreshHealth()
    } catch (e) { setError(e.message) }
  }

  async function start() {
    setBusy(true)
    try {
      const next = await api('/api/streamcopy/jobs', {
        method: 'POST',
        body: JSON.stringify({
          source_path: sourcePath,
          destination_path: destinationPath,
          source_kind: sourceKind,
          destination_kind: destinationKind,
          source_connection_id: sourceKind === 'remote' ? sourceConnectionId : null,
          destination_connection_id: destinationKind === 'remote' ? destinationConnectionId : null,
          ...payload,
          verify_mode: deleteSourceAfterVerify ? 'sha256' : verifyMode,
          delete_source_after_verify: deleteSourceAfterVerify,
        }),
      })
      setJob(next)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function cancel() {
    if (!job?.id) return
    try {
      setJob(await api(`/api/streamcopy/jobs/${job.id}/cancel`, {
        method: 'POST',
        body: '{}',
      }))
    } catch (e) { setError(e.message) }
  }

  const percent = Number(job?.progress_percent || 0)
  const bothUsbHdd = sourceKind === 'local'
    && destinationKind === 'local'
    && sourceMedia === 'hdd'
    && destinationMedia === 'hdd'
    && sourceTransport === 'usb3'
    && destinationTransport === 'usb3'

  return <div className="streamcopy-page">
    <div className="streamcopy-hero">
      <div>
        <span className="streamcopy-kicker">V3 EXPERIMENTAL · LOCAL + SFTP RIVER</span>
        <h2>StreamCopy Remote River</h2>
        <p>
          Папка рассматривается как один логический поток. Маленькие файлы объединяются
          producer’ом в RAM frames локально, а крупные идут River Keeper path.
          Для SFTP используется тот же persistent journal и SHA-256 checkpoints; credentials
          остаются только в RAM connection profile.
        </p>
      </div>
      <div className="streamcopy-lock">
        <b>{health?.safety?.file_writes ? 'FILE WRITE ENABLED' : 'FILE WRITE LOCKED'}</b>
        <button onClick={toggleWrites}>
          {health?.safety?.file_writes ? 'Выключить WRITE' : 'Включить WRITE'}
        </button>
      </div>
    </div>

    <div className="streamcopy-bands">
      <Band role="01 · SOURCE" title="Диск 1 / источник" tone="source">
        <div className="streamcopy-row path-row">
          <SelectField label="Endpoint" value={sourceKind} onChange={setSourceKind} options={ENDPOINT} disabled={running} />
          {sourceKind === 'remote' && <label>
            <span>SFTP profile</span>
            <select value={sourceConnectionId} onChange={e => setSourceConnectionId(e.target.value)} disabled={running}>
              <option value="">Выбрать SFTP…</option>
              {connections.map(item => <option key={item.id} value={item.id}>
                {item.username}@{item.host}:{item.port} · {item.root}
              </option>)}
            </select>
          </label>}
          <label className="grow">
            <span>{sourceKind === 'remote' ? 'Remote file / directory' : 'Главная папка или файл'}</span>
            <input value={sourcePath} onChange={e => setSourcePath(e.target.value)} disabled={running} />
          </label>
          <SelectField label="Тип носителя" value={sourceMedia} onChange={setSourceMedia} options={MEDIA} disabled={running} />
          <SelectField
            label="Подключение"
            value={effectiveSourceTransport}
            onChange={setSourceTransport}
            options={TRANSPORT}
            disabled={running || sourceKind === 'remote'}
          />
          <label>
            <span>Drive cache, MiB</span>
            <input type="number" min="0" max="1024" value={sourceCacheMiB} onChange={e => setSourceCacheMiB(e.target.value)} disabled={running} />
          </label>
        </div>
      </Band>

      <Band role="02 · STREAM" title="Профиль потока" tone="stream">
        <div className="stream-profile-strip">
          <div><small>Strategy</small><b>{profile?.strategy || '…'}</b></div>
          <div><small>Chunk</small><b>{profile ? `${profile.chunk_mib} MiB` : '…'}</b></div>
          <div><small>Queue</small><b>{profile ? `${profile.queue_depth} buffers` : '…'}</b></div>
          <div><small>RAM ring</small><b>{profile ? `${profile.max_buffer_mib} MiB max` : '…'}</b></div>
          <div>
            <small>Microfiles</small>
            <b>{profile ? (profile.microfile_batching ? `≤ ${profile.microfile_max_mib} MiB` : 'off for SFTP') : '…'}</b>
          </div>
          <div>
            <small>Micro frame</small>
            <b>{profile ? (profile.microfile_batching ? `${profile.micro_frame_mib} MiB` : 'local only') : '…'}</b>
          </div>
          <div><small>River keeper</small><b>{profile ? `${profile.checkpoint_mib} MiB checkpoint` : '…'}</b></div>
          <div className="grow"><small>Ordering</small><b>{profile?.ordering || '…'}</b></div>
        </div>
        <div className="streamcopy-row topology-row">
          <SelectField label="Если оба через USB: topology" value={usbTopology} onChange={setUsbTopology} options={TOPOLOGY} disabled={running} />
          <SelectField
            label="Source ordering"
            value={effectiveOrderingMode}
            onChange={setOrderingMode}
            options={ORDERING}
            disabled={running || !localityEligible}
          />
          <p>{profile?.transport_note}</p>
          <p>{profile?.cache_note}</p>
          <button onClick={refreshConnections} disabled={running}>↻ SFTP profiles</button>
        </div>
        {orderingMode === 'ntfs_locality' && !localityEligible && <div className="streamcopy-note">
          NTFS locality доступен только для Local HDD source. Для SSD/Flash/SFTP применяется стабильный manifest order.
        </div>}
        {profile?.locality_scheduler?.enabled && <div className="streamcopy-note">
          NTFS first-LCN locality · EXP: scheduler только читает allocation map и меняет порядок manifest.
          Он не двигает extents и не включает DS_ALLOW_EXTENT_MOVES. Unknown LCN остаются в исходном порядке в конце.
          Режим opt-in — сравни итоговое время с обычным manifest order на том же наборе.
        </div>
        {profile?.remote_note && <div className="streamcopy-note">{profile.remote_note}</div>}
        <div className="streamcopy-row topology-row">
          <SelectField
            label="Проверка"
            value={deleteSourceAfterVerify ? 'sha256' : verifyMode}
            onChange={setVerifyMode}
            options={[['size', 'Размер'], ['sha256', 'SHA-256']]}
            disabled={running || deleteSourceAfterVerify}
          />
          <label>
            <span>Завершение</span>
            <select
              value={deleteSourceAfterVerify ? 'copy-delete' : 'copy'}
              onChange={e => setDeleteSourceAfterVerify(e.target.value === 'copy-delete')}
              disabled={running}
            >
              <option value="copy">COPY · источник оставить</option>
              <option value="copy-delete">COPY → SHA-256 → DELETE source</option>
            </select>
          </label>
          <p>
            StreamCopy не делает Move как отдельную операцию. Удаление source возможно только
            после опубликованной копии и сильного SHA-256 сравнения.
          </p>
        </div>
        {bothUsbHdd && <div className="streamcopy-note">
          USB 3.x — только транспорт. Для пары HDD→HDD StreamCopy не переключает тип носителя:
          остаётся последовательный HDD-профиль. Если оба порта сидят на одном hub/controller,
          выбери «Общий hub / controller».
        </div>}
      </Band>

      <Band role="03 · DESTINATION" title="Диск 2 / приёмник" tone="destination">
        <div className="streamcopy-row path-row">
          <SelectField label="Endpoint" value={destinationKind} onChange={setDestinationKind} options={ENDPOINT} disabled={running} />
          {destinationKind === 'remote' && <label>
            <span>SFTP profile</span>
            <select value={destinationConnectionId} onChange={e => setDestinationConnectionId(e.target.value)} disabled={running}>
              <option value="">Выбрать SFTP…</option>
              {connections.map(item => <option key={item.id} value={item.id}>
                {item.username}@{item.host}:{item.port} · {item.root}
              </option>)}
            </select>
          </label>}
          <label className="grow">
            <span>{destinationKind === 'remote' ? 'Remote destination directory' : 'Папка-приёмник'}</span>
            <input value={destinationPath} onChange={e => setDestinationPath(e.target.value)} disabled={running} />
          </label>
          <SelectField label="Тип носителя" value={destinationMedia} onChange={setDestinationMedia} options={MEDIA} disabled={running} />
          <SelectField
            label="Подключение"
            value={effectiveDestinationTransport}
            onChange={setDestinationTransport}
            options={TRANSPORT}
            disabled={running || destinationKind === 'remote'}
          />
          <label>
            <span>Drive cache, MiB</span>
            <input type="number" min="0" max="1024" value={destinationCacheMiB} onChange={e => setDestinationCacheMiB(e.target.value)} disabled={running} />
          </label>
        </div>
      </Band>

      <Band role="04 · RUN" title="Поток и телеметрия" tone="run">
        <div className="stream-run-grid">
          <div>
            <small>Status</small>
            <b>{job?.status || 'ready'}</b>
          </div>
          <div>
            <small>Average</small>
            <b>{job ? `${Number(job.average_mib_s || 0).toFixed(1)} MiB/s` : '—'}</b>
          </div>
          <div>
            <small>Bytes</small>
            <b>{job ? `${fmtBytes(job.bytes)} / ${fmtBytes(job.total_bytes)}` : '—'}</b>
          </div>
          <div>
            <small>Files</small>
            <b>{job ? `${job.files} / ${job.total_files}` : '—'}</b>
          </div>
          <div>
            <small>Skipped</small>
            <b>{job?.skipped ?? '—'}</b>
          </div>
        </div>
        <div className="stream-progress">
          <i style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} />
        </div>
        {job?.current_path && <p className="stream-current">{job.current_path}</p>}
        {job?.error && <p className="warning">{job.error}</p>}
        <div className="stream-actions">
          <button
            className="primary"
            disabled={
              busy
              || restoringJob
              || running
              || !health?.safety?.file_writes
              || !sourcePath
              || !destinationPath
              || (sourceKind === 'remote' && !sourceConnectionId)
              || (destinationKind === 'remote' && !destinationConnectionId)
            }
            onClick={start}
          >
            🌊 Start StreamCopy
          </button>
          <button className="stop-button" disabled={!running} onClick={cancel}>Stop</button>
          <span>
            {restoringJob
              ? 'Подключаюсь к backend job…'
              : 'Job хранится в backend journal: браузер можно закрыть, а после restart backend задача восстанавливается из checkpoint.'}
          </span>
          <span>
            При обрыве диска StreamCopy ждёт тот же Volume ID; после возврата проверяет последний
            checkpoint и откатывает непроверенный хвост на шаг назад.
          </span>
          <span>Destination conflicts не перезаписываются: existing target → warning/skip.</span>
        </div>
        {job?.warnings?.length > 0 && <details className="stream-warnings">
          <summary>Warnings / skipped: {job.warnings.length}</summary>
          {job.warnings.slice(-40).map((item, index) => <div key={`${item.path}-${index}`}>
            <b>{item.path}</b><span>{item.message}</span>
          </div>)}
        </details>}
      </Band>
    </div>
  </div>
}
