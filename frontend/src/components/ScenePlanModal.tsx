import { useEffect, useMemo, useState } from 'react'
import { api, type ScenePlanItem, type StyleAxes } from '../api'

const BEAT_OPTIONS = ['기', '승', '전', '결', '보조', '회상', '에필로그'] as const
const TENSION_OPTIONS: Array<{ id: ScenePlanItem['tension']; label: string }> = [
  { id: 'low', label: '낮음' },
  { id: 'mid', label: '중간' },
  { id: 'high', label: '높음' },
  { id: 'climax', label: '절정' },
]
const POV_OPTIONS = ['1st', '3rd_limited', '3rd_omniscient', '2nd', 'mixed'] as const

export type ScenePlanModalResult = {
  scenes: ScenePlanItem[]
  regenerateIds: string[]
  styleAxes: StyleAxes
  mode: 'replace-current-block' | 'split-into-blocks'
}

export type ScenePlanModalProps = {
  episodeId: string
  rawMemory: string
  initialStyleAxes?: StyleAxes
  onClose: () => void
  onRun: (result: ScenePlanModalResult) => Promise<void> | void
  existingSceneContents?: Record<string, string>
  initialScenes?: ScenePlanItem[]
}

export function ScenePlanModal({
  episodeId,
  rawMemory,
  initialStyleAxes,
  initialScenes,
  existingSceneContents,
  onClose,
  onRun,
}: ScenePlanModalProps) {
  const [scenes, setScenes] = useState<ScenePlanItem[]>(initialScenes ?? [])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [maxScenes, setMaxScenes] = useState(6)
  const [regen, setRegen] = useState<Record<string, boolean>>({})
  const [mode, setMode] = useState<ScenePlanModalResult['mode']>('split-into-blocks')
  const [axes, setAxes] = useState<StyleAxes>(initialStyleAxes ?? {})

  const hasExisting = !!existingSceneContents && Object.keys(existingSceneContents).length > 0

  const planOnce = async () => {
    setLoading(true)
    setErr(null)
    try {
      const r = await api.agent.planScenes({
        episode_id: episodeId,
        raw_memory: rawMemory,
        max_scenes: maxScenes,
        style_axes: axes,
      })
      setScenes(r.scenes)
      const init: Record<string, boolean> = {}
      for (const s of r.scenes) init[s.id] = !hasExisting
      setRegen(init)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (initialScenes && initialScenes.length > 0) {
      const init: Record<string, boolean> = {}
      for (const s of initialScenes) init[s.id] = !hasExisting
      setRegen(init)
      return
    }
    void planOnce()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const selectedIds = useMemo(() => scenes.filter((s) => regen[s.id]).map((s) => s.id), [scenes, regen])

  const run = async () => {
    if (scenes.length === 0) return
    setLoading(true)
    setErr(null)
    try {
      await onRun({
        scenes,
        regenerateIds: selectedIds,
        styleAxes: axes,
        mode,
      })
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const updateScene = (idx: number, patch: Partial<ScenePlanItem>) => {
    setScenes((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)))
  }

  return (
    <div className="intake-backdrop" role="dialog" aria-modal="true" aria-label="씬 플랜">
      <div className="intake-modal" style={{ width: 'min(1080px, 100%)' }}>
        <header className="intake-head">
          <h2>씬 플랜 · 부분 재생성</h2>
          <button type="button" className="intake-close" onClick={onClose} aria-label="닫기">
            ×
          </button>
        </header>
        {err && <div className="intake-alert">{err}</div>}

        <div className="scene-toolbar">
          <label>
            <span>최대 씬 수</span>
            <input
              type="number"
              min={1}
              max={12}
              value={maxScenes}
              onChange={(e) => setMaxScenes(Math.max(1, Math.min(12, Number(e.target.value) || 6)))}
              style={{ width: 56 }}
              disabled={loading}
            />
          </label>
          <label>
            <span>길이</span>
            <select
              value={axes.length ?? ''}
              onChange={(e) => setAxes((a) => ({ ...a, length: (e.target.value || undefined) as StyleAxes['length'] }))}
              disabled={loading}
            >
              <option value="">기본</option>
              <option value="short">짧게</option>
              <option value="mid">보통</option>
              <option value="long">길게</option>
            </select>
          </label>
          <label>
            <span>레지스터</span>
            <select
              value={axes.register ?? ''}
              onChange={(e) =>
                setAxes((a) => ({ ...a, register: (e.target.value || undefined) as StyleAxes['register'] }))
              }
              disabled={loading}
            >
              <option value="">기본</option>
              <option value="colloquial">구어체</option>
              <option value="literary">문어체</option>
            </select>
          </label>
          <label>
            <span>리듬</span>
            <select
              value={axes.rhythm ?? ''}
              onChange={(e) => setAxes((a) => ({ ...a, rhythm: (e.target.value || undefined) as StyleAxes['rhythm'] }))}
              disabled={loading}
            >
              <option value="">기본</option>
              <option value="staccato">끊어짐</option>
              <option value="flowing">흐르듯</option>
            </select>
          </label>
          <button type="button" className="ghost" onClick={planOnce} disabled={loading}>
            {scenes.length > 0 ? '다시 설계' : '씬 설계'}
          </button>
        </div>

        <div className="scene-grid">
          {loading && scenes.length === 0 ? (
            <p className="intake-hint">씬을 설계 중…</p>
          ) : scenes.length === 0 ? (
            <p className="intake-hint">아직 씬이 없습니다. 위에서 "씬 설계"를 누르세요.</p>
          ) : (
            scenes.map((s, idx) => {
              const existing = existingSceneContents?.[s.id] ?? ''
              return (
                <article key={s.id} className="scene-card">
                  <header className="scene-card-head">
                    <label className="scene-regen">
                      <input
                        type="checkbox"
                        checked={!!regen[s.id]}
                        onChange={(e) => setRegen((r) => ({ ...r, [s.id]: e.target.checked }))}
                        disabled={loading}
                      />
                      <span>
                        {hasExisting ? (regen[s.id] ? '이 씬만 재생성' : '기존 본문 유지') : '생성'}
                      </span>
                    </label>
                    <div className="scene-id">{s.id}</div>
                  </header>
                  <div className="scene-card-meta">
                    <select value={s.beat} onChange={(e) => updateScene(idx, { beat: e.target.value })} disabled={loading}>
                      {BEAT_OPTIONS.map((b) => (
                        <option key={b} value={b}>
                          {b}
                        </option>
                      ))}
                    </select>
                    <select
                      value={s.tension}
                      onChange={(e) => updateScene(idx, { tension: e.target.value })}
                      disabled={loading}
                    >
                      {TENSION_OPTIONS.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                    <select value={s.pov} onChange={(e) => updateScene(idx, { pov: e.target.value })} disabled={loading}>
                      {POV_OPTIONS.map((p) => (
                        <option key={p} value={p}>
                          {p}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      value={s.approx_chars}
                      min={200}
                      max={2000}
                      step={50}
                      onChange={(e) => updateScene(idx, { approx_chars: Number(e.target.value) || 600 })}
                      style={{ width: 80 }}
                      disabled={loading}
                      title="approx_chars"
                    />
                  </div>
                  <label className="scene-field">
                    <span>goal</span>
                    <textarea
                      rows={2}
                      value={s.goal}
                      onChange={(e) => updateScene(idx, { goal: e.target.value })}
                      disabled={loading}
                    />
                  </label>
                  <label className="scene-field">
                    <span>hint</span>
                    <textarea
                      rows={2}
                      value={s.hint}
                      onChange={(e) => updateScene(idx, { hint: e.target.value })}
                      disabled={loading}
                    />
                  </label>
                  {existing && (
                    <details className="scene-existing">
                      <summary>기존 본문 미리보기 ({existing.length}자)</summary>
                      <pre>
                        {existing.slice(0, 600)}
                        {existing.length > 600 ? '…' : ''}
                      </pre>
                    </details>
                  )}
                </article>
              )
            })
          )}
        </div>

        <footer className="scene-footer">
          <div className="scene-mode">
            <label>
              <input
                type="radio"
                name="scene-mode"
                checked={mode === 'split-into-blocks'}
                onChange={() => setMode('split-into-blocks')}
                disabled={loading}
              />
              씬마다 블록으로 나누기
            </label>
            <label>
              <input
                type="radio"
                name="scene-mode"
                checked={mode === 'replace-current-block'}
                onChange={() => setMode('replace-current-block')}
                disabled={loading}
              />
              전체 본문으로 현재 블록에 넣기
            </label>
          </div>
          <div className="scene-actions">
            <button type="button" className="ghost" onClick={onClose} disabled={loading}>
              취소
            </button>
            <button
              type="button"
              className="primary"
              onClick={run}
              disabled={loading || scenes.length === 0 || selectedIds.length === 0}
              title={selectedIds.length === 0 ? '재생성할 씬을 하나 이상 체크하세요' : undefined}
            >
              {hasExisting ? `선택한 ${selectedIds.length}개 씬 재생성` : `이 플랜으로 ${scenes.length}개 씬 생성`}
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}
