import { useEffect, useRef, useState } from 'react'
import { api, type IntakeState } from '../api'

type Mode = 'create' | 'edit'

export type IntakeModalResult = {
  applied_bible: number
  world_setting_chars: number
  foundation_sync?: Record<string, unknown> | null
  state: IntakeState
}

export type IntakeModalProps = {
  mode: Mode
  initialStoryInput: string
  storyId: string
  genre?: string
  language?: string
  onClose: () => void
  onFinalized: (result: IntakeModalResult) => void
}

const SEVERITY_LABEL: Record<string, string> = {
  who: '인물/주체',
  where: '공간/배경',
  what: '행동/사건',
}

export function IntakeModal({
  mode,
  initialStoryInput,
  storyId,
  genre,
  language,
  onClose,
  onFinalized,
}: IntakeModalProps) {
  const [state, setState] = useState<IntakeState | null>(null)
  const [missing, setMissing] = useState<string[]>([])
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([])
  const [currentQ, setCurrentQ] = useState('')
  const [answerDraft, setAnswerDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const firstFocusRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    let cancelled = false
    async function boot() {
      setLoading(true)
      setErr(null)
      try {
        const r = await api.agent.intakeStart({
          story_input: initialStoryInput,
          genre,
          language,
        })
        if (cancelled) return
        setState(r.state)
        setMissing(r.missing)
        setSuggestedQuestions(r.suggested_questions)
        setCurrentQ(r.suggested_questions[0] ?? '')
      } catch (e: unknown) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void boot()
    return () => {
      cancelled = true
    }
  }, [initialStoryInput, genre, language])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const submitAnswer = async () => {
    if (!state) return
    const q = currentQ.trim() || '(자유 보강)'
    const a = answerDraft.trim()
    if (!a) return
    setLoading(true)
    setErr(null)
    try {
      const r = await api.agent.intakeAnswer(state, q, a)
      setState(r.state)
      setMissing(r.missing)
      setSuggestedQuestions(r.suggested_questions)
      setCurrentQ(r.suggested_questions[0] ?? '')
      setAnswerDraft('')
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const finalize = async () => {
    if (!state) return
    setLoading(true)
    setErr(null)
    try {
      const r = await api.agent.intakeFinalize(state, storyId, true)
      onFinalized({
        applied_bible: r.applied_bible,
        world_setting_chars: r.world_setting_chars,
        foundation_sync: r.foundation_sync,
        state,
      })
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const extracted = state?.extracted as
    | {
        premise?: string
        keywords?: string[]
        entities?: {
          characters?: { name?: string }[]
          backgrounds?: { place?: string; era?: string; mood?: string }[]
          events?: { title?: string }[]
        }
      }
    | undefined

  const canFinalize = !!state && missing.length === 0

  return (
    <div className="intake-backdrop" role="dialog" aria-modal="true" aria-label="배경 진단">
      <div className="intake-modal">
        <header className="intake-head">
          <h2>{mode === 'create' ? '배경 진단 — 새 작품' : '배경 진단 — 설정 수정'}</h2>
          <button type="button" className="intake-close" onClick={onClose} aria-label="닫기">
            ×
          </button>
        </header>

        {err && <div className="intake-alert">{err}</div>}

        <div className="intake-body">
          <section className="intake-summary">
            <h3>지금까지의 세계관 요약</h3>
            {!state ? (
              <p className="intake-hint">분석 중…</p>
            ) : (
              <ul className="intake-summary-list">
                {extracted?.premise && (
                  <li>
                    <strong>대전제</strong>
                    <p>{extracted.premise}</p>
                  </li>
                )}
                {!!extracted?.keywords?.length && (
                  <li>
                    <strong>키워드</strong>
                    <p>{extracted.keywords.slice(0, 10).join(' · ')}</p>
                  </li>
                )}
                {!!extracted?.entities?.characters?.length && (
                  <li>
                    <strong>인물</strong>
                    <p>
                      {extracted.entities.characters
                        .map((c) => (c.name || '').trim())
                        .filter(Boolean)
                        .slice(0, 8)
                        .join(', ')}
                    </p>
                  </li>
                )}
                {!!extracted?.entities?.backgrounds?.length && (
                  <li>
                    <strong>배경</strong>
                    <p>
                      {extracted.entities.backgrounds
                        .map((b) => [b.place, b.era, b.mood].filter(Boolean).join(' · '))
                        .filter(Boolean)
                        .slice(0, 6)
                        .join(' / ')}
                    </p>
                  </li>
                )}
                {!!extracted?.entities?.events?.length && (
                  <li>
                    <strong>사건 씨앗</strong>
                    <p>
                      {extracted.entities.events
                        .map((e) => (e.title || '').trim())
                        .filter(Boolean)
                        .slice(0, 6)
                        .join(' / ')}
                    </p>
                  </li>
                )}
              </ul>
            )}

            <div className="intake-missing">
              <strong>아직 비어 있는 항목</strong>
              {missing.length === 0 ? (
                <p style={{ color: '#2f8f5a' }}>모두 확인됨 — 확정 가능</p>
              ) : (
                <ul>
                  {missing.map((m) => (
                    <li key={m}>{SEVERITY_LABEL[m] ?? m}</li>
                  ))}
                </ul>
              )}
            </div>

            {state?.answers && state.answers.length > 0 && (
              <details className="intake-answers">
                <summary>내가 답한 것 ({state.answers.length})</summary>
                <ul>
                  {state.answers.map((row, i) => (
                    <li key={i}>
                      <em>Q.</em> {row.q}
                      <br />
                      <strong>A.</strong> {row.a}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </section>

          <section className="intake-qa">
            <h3>AI 편집자의 질문</h3>
            <label className="intake-label">
              <span>질문 (필요하면 직접 수정)</span>
              <textarea
                ref={firstFocusRef}
                value={currentQ}
                onChange={(e) => setCurrentQ(e.target.value)}
                rows={2}
                placeholder="예: 주인공이 어떤 도시에 살고 있나요?"
                disabled={loading}
              />
            </label>

            {suggestedQuestions.length > 1 && (
              <div className="intake-suggest">
                <span className="intake-hint">다른 제안</span>
                <ul>
                  {suggestedQuestions.slice(1).map((q, i) => (
                    <li key={i}>
                      <button type="button" className="ghost" onClick={() => setCurrentQ(q)} disabled={loading}>
                        {q}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <label className="intake-label">
              <span>답</span>
              <textarea
                value={answerDraft}
                onChange={(e) => setAnswerDraft(e.target.value)}
                rows={4}
                placeholder="한두 문장이어도 됩니다. 확정 전 여러 번 보강할 수 있어요."
                disabled={loading}
              />
            </label>

            <div className="intake-actions">
              <button
                type="button"
                className="primary"
                onClick={submitAnswer}
                disabled={loading || !answerDraft.trim()}
              >
                답 반영 · 다시 분석
              </button>
              <button
                type="button"
                className={canFinalize ? 'primary accent' : 'ghost'}
                onClick={finalize}
                disabled={loading || !state}
                title={
                  canFinalize ? '지금 상태로 저장' : '필수 항목이 남아 있어도 강제 확정할 수 있습니다'
                }
              >
                {canFinalize ? '이 상태로 확정' : '강제 확정'}
              </button>
              <button type="button" className="ghost" onClick={onClose} disabled={loading}>
                취소
              </button>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
