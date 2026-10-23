import React, { useEffect, useMemo, useState } from 'react'
import { api, fmtBytes } from './api.js'
import './StreamCopy.css'

const MEDIA = [
  ['hdd', 'HDD · механический'],
  ['ssd', 'SSD / NVMe'],
  ['flash', 'USB flash / карта'],
]

const TRANSPORT = [
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

const TERMINAL = new Set(['completed', 'completed_with_warnings', 'failed', 'cancelled'])

function saved(key, fallback) {
  return localStorage.getItem(\`streamcopy:\${key}\`) || fallback
}

function Band({ role, title, children, tone = '' }) {
  return <section className={\`stream-band \${tone}\`}>
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
  const [sourcePath, setSourcePath] = useState(() => saved('sourcePath', 'H:\\\\'))
  const [destinationPath, setDestinationPath] = useState(() => saved('destinationPath', 'W:\\\\'))
  const [sourceMedia, setSourceMedia] = useState(() => saved('sourceMedia', 'hdd'))
  const [destinationMedia, setDestinationMedia] = useState(() => saved('destinationMedia', 'hdd'))
  const [sourceTransport, setSourceTransport] = useState(() => saved('sourceTransport', 'usb3'))
  const [destinationTransport, setDestinationTransport] = useState(() => saved('destinationTransport', 'usb3'))
  const [usbTopology, setUsbTopology] = useState(() => saved('usbTopology', 'unknown'))
  const [sourceCacheMiB, setSourceCacheMiB] = useState(() => saved('sourceCacheMiB', '32'))
  const [destinationCacheMiB, setDestinationCacheMiB] = useState(() => saved('destinationCacheMiB', '128'))
  const [profile, setProfile] = useState(null)
  const [job, setJob] = useState(null)
  const [busy, setBusy] = useState(false)
  const running = job && !TERMINAL.has(job.status)

  const payload = useMemo(() => ({
    source_media: sourceMedia,
    destination_media: destinationMedia,
    source_transport: sourceTransport,
    destination_transport: destinationTransport,
    usb_topology: usbTopology,
    source_cache_mib: Number(sourceCacheMiB || 0),
    destination_cache_mib: Number(destinationCacheMiB || 0),
  }), [
    sourceMedia,
    destinationMedia,
    sourceTransport,
    destinationTransport,
    usbTopology,
    sourceCacheMiB,
    destinationCacheMiB,
  ])

  useEffect(() => {
    for (const [key, value] of Object.entries({
      sourcePath,
      destinationPath,
      sourceMedia,
      destinationMedia,
      sourceTransport,
      destinationTransport,
      usbTopology,
      sourceCacheMiB,
      destinationCacheMiB,
    })) localStorage.setItem(\`streamcopy:\${key}\`, String(value))
  }, [
    sourcePath,
    destinationPath,
    sourceMedia,
    destinationMedia,
    sourceTransport,
    destinationTransport,
    usbTopology,
    sourceCacheMiB,
    destinationCacheMiB,
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
    const poll = async () => {
      try {
        const next = await api(\`/api/streamcopy/jobs/\${job.id}\`)
        if (!stopped) setJob(next)
      } catch (e) {
        if (!stopped) setError(e.message)
      }
    }
    const timer = setInterval(poll, 400)
    poll()
    return () => {
      stopped = true
      clearInterval(timer)
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
          ...payload,
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
      setJob(await api(\`/api/streamcopy/jobs/\${job.id}/cancel\`, {
        method: 'POST',
        body: '{}',
      }))
    } catch (e) { setError(e.message) }
  }

  const percent = Number(job?.progress_percent || 0)
  const bothUsbHdd = sourceMedia === 'hdd'
    && destinationMedia === 'hdd'
    && sourceTransport === 'usb3'
    && destinationTransport === 'usb3'

  return <div className="streamcopy-page">
    <div className="streamcopy-hero">
      <div>
        <span className="streamcopy-kicker">EXPERIMENTAL · LOCAL COPY ENGINE</span>
        <h2>StreamCopy</h2>
        <p>
          Папка рассматривается как один логический поток: один manifest, один producer,
          один consumer и ограниченный RAM ring buffer. Обычный Commander не изменяется.
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
          <label className="grow">
            <span>Главная папка или файл</span>
            <input value={sourcePath} onChange={e => setSourcePath(e.target.value)} disabled={running} />
          </label>
          <SelectField label="Тип носителя" value={sourceMedia} onChange={setSourceMedia} options={MEDIA} disabled={running} />
          <SelectField label="Подключение" value={sourceTransport} onChange={setSourceTransport} options={TRANSPORT} disabled={running} />
          <label>
            <span>Drive cache, MiB</span>
            <input type="number" min="0" max="1024" value={sourceCacheMiB} onChange={e => setSourceCacheMiB(e.target.value)} disabled={running} />
          </label>
        </div>
      </Band>

      <Band role="02 · STREAM" title="Профиль потока" tone="stream">
        <div className="stream-profile-strip">
          <div><small>Strategy</small><b>{profile?.strategy || '…'}</b></div>
          <div><small>Chunk</small><b>{profile ? \`\${profile.chunk_mib} MiB\` : '…'}</b></div>
          <div><small>Queue</small><b>{profile ? \`\${profile.queue_depth} buffers\` : '…'}</b></div>
          <div><small>RAM ring</small><b>{profile ? \`\${profile.max_buffer_mib} MiB max\` : '…'}</b></div>
          <div className="grow"><small>Ordering</small><b>{profile?.ordering || '…'}</b></div>
        </div>
        <div className="streamcopy-row topology-row">
          <SelectField label="Если оба через USB: topology" value={usbTopology} onChange={setUsbTopology} options={TOPOLOGY} disabled={running} />
          <p>{profile?.transport_note}</p>
          <p>{profile?.cache_note}</p>
        </div>
        {bothUsbHdd && <div className="streamcopy-note">
          USB 3.x — только транспорт. Для пары HDD→HDD StreamCopy не переключает тип носителя:
          остаётся последовательный HDD-профиль. Если оба порта сидят на одном hub/controller,
          выбери «Общий hub / controller».
        </div>}
      </Band>

      <Band role="03 · DESTINATION" title="Диск 2 / приёмник" tone="destination">
        <div className="streamcopy-row path-row">
          <label className="grow">
            <span>Папка-приёмник</span>
            <input value={destinationPath} onChange={e => setDestinationPath(e.target.value)} disabled={running} />
          </label>
          <SelectField label="Тип носителя" value={destinationMedia} onChange={setDestinationMedia} options={MEDIA} disabled={running} />
          <SelectField label="Подключение" value={destinationTransport} onChange={setDestinationTransport} options={TRANSPORT} disabled={running} />
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
            <b>{job ? \`\${Number(job.average_mib_s || 0).toFixed(1)} MiB/s\` : '—'}</b>
          </div>
          <div>
            <small>Bytes</small>
            <b>{job ? \`\${fmtBytes(job.bytes)} / \${fmtBytes(job.total_bytes)}\` : '—'}</b>
          </div>
          <div>
            <small>Files</small>
            <b>{job ? \`\${job.files} / \${job.total_files}\` : '—'}</b>
          </div>
          <div>
            <small>Skipped</small>
            <b>{job?.skipped ?? '—'}</b>
          </div>
        </div>
        <div className="stream-progress">
          <i style={{ width: \`\${Math.max(0, Math.min(100, percent))}%\` }} />
        </div>
        {job?.current_path && <p className="stream-current">{job.current_path}</p>}
        {job?.error && <p className="warning">{job.error}</p>}
        <div className="stream-actions">
          <button
            className="primary"
            disabled={busy || running || !health?.safety?.file_writes || !sourcePath || !destinationPath}
            onClick={start}
          >
            🌊 Start StreamCopy
          </button>
          <button className="stop-button" disabled={!running} onClick={cancel}>Stop</button>
          <span>Destination conflicts пока не перезаписываются: existing target → warning/skip.</span>
        </div>
        {job?.warnings?.length > 0 && <details className="stream-warnings">
          <summary>Warnings / skipped: {job.warnings.length}</summary>
          {job.warnings.slice(-40).map((item, index) => <div key={\`\${item.path}-\${index}\`}>
            <b>{item.path}</b><span>{item.message}</span>
          </div>)}
        </details>}
      </Band>
    </div>
  </div>
}
