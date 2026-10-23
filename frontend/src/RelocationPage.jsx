import React, { useEffect, useState } from 'react'
import { api, fmtBytes } from './api.js'


export default function RelocationPage({ scanId, setError }) {
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)

  async function load() {
    if (!scanId) return
    setBusy(true)
    try {
      setPlan(await api(`/api/storage/relocation-plan?scan_id=${encodeURIComponent(scanId)}&limit=100`))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    setPlan(null)
  }, [scanId])

  return <div className="stack relocation-page">
    <section className="card">
      <h3>🧭 Relocation Planner · read-only</h3>
      <p>
        Анализирует тяжёлые каталоги из Quick Index и только советует, что оставить,
        что переносить штатно, где допустим junction и что похоже на архив.
      </p>
      <p className="warning">
        Windows / Program Files / ProgramData целиком через junction не переносятся.
        Будущий executor должен работать только COPY → VERIFY → SWITCH → DELETE OLD.
      </p>
      <button className="primary" disabled={!scanId || busy} onClick={load}>
        {busy ? 'Анализ…' : `Построить рекомендации из scan ${scanId || '—'}`}
      </button>
    </section>

    {plan && <section className="card">
      <h3>Кандидаты</h3>
      <div className="relocation-list">
        {(plan.items || []).map(item => <div key={item.path} className={`relocation-${item.action}`}>
          <div>
            <b>{item.path}</b>
            <small>{item.classification} · {item.total_files} files</small>
          </div>
          <strong>{item.action}</strong>
          <span>{fmtBytes(item.total_size)}</span>
          <p>{item.reason}</p>
        </div>)}
      </div>
    </section>}
  </div>
}
