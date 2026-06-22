import { useEffect, useMemo, useState } from 'react'
import type { MemoQaAnswerItem, MemoQaQuestionItem, MemoQaSurveyResponse, MemoSurveySnapshot } from '../api'

export type MemoQaModalResult = {
  survey: MemoSurveySnapshot
  answers: Record<string, MemoQaAnswerItem>
}

type Props = {
  survey: MemoQaSurveyResponse
  onClose: () => void
  onRun: (result: MemoQaModalResult) => Promise<void> | void
  onSkip: () => void
}

function initAnswers(questions: MemoQaQuestionItem[]) {
  const a: Record<string, MemoQaAnswerItem> = {}
  for (const q of questions) {
    a[q.id] = { selected_index: 0, freeform: '' }
  }
  return a
}

export function MemoQaModal({ survey, onClose, onRun, onSkip }: Props) {
  const [answers, setAnswers] = useState<Record<string, MemoQaAnswerItem>>(() => initAnswers(survey.questions))
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const snapshot: MemoSurveySnapshot = useMemo(
    () => ({ segments: survey.segments, questions: survey.questions }),
    [survey.segments, survey.questions],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const run = async () => {
    setLoading(true)
    setErr(null)
    try {
      await onRun({ survey: snapshot, answers })
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="intake-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="메모 Q-A"
      onMouseDown={() => {
        if (!loading) onClose()
      }}
    >
      <div className="intake-modal memo-qa-panel" style={{ width: 'min(720px, 100%)' }} onMouseDown={(e) => e.stopPropagation()}>
        {loading && (
          <div className="memo-qa-loading" role="status" aria-live="assertive" aria-busy="true">
            <div className="memo-qa-loading-box">
              <p className="memo-qa-loading-title">AI 초안 생성 중</p>
              <p className="memo-qa-loading-api">
                백엔드: <code>POST /api/agent/expand-draft</code>
              </p>
              <p className="memo-qa-loading-hint">memo_survey + memo_qa_answers 로 요청이 전송됩니다. 잠시만 기다려 주세요.</p>
            </div>
          </div>
        )}
        <header className="intake-head">
          <h2>초안 질의</h2>
          <button type="button" className="intake-close" onClick={onClose} disabled={!!loading} aria-label="닫기">
            ×
          </button>
        </header>
        <p className="memo-qa-hint">
          준비도 {Math.round((survey.readiness?.score ?? 0) * 100)}점 · 블록{' '}
          {survey.estimated_work?.segments ?? survey.segments.length}개 · 예상 생성{' '}
          {survey.estimated_work?.draft_calls ?? survey.segments.length}회 · 기억 검색{' '}
          {survey.estimated_work?.memory_searches ?? survey.segments.length}회
        </p>
        {survey.readiness?.reasons?.length > 0 && (
          <p className="memo-qa-reasons">{survey.readiness.reasons.slice(0, 2).join(' ')}</p>
        )}
        {err && <div className="intake-alert">{err}</div>}

        <div className={loading ? 'memo-qa-list memo-qa-list-locked' : 'memo-qa-list'}>
          {survey.questions.map((q) => (
            <div key={q.id} className="memo-qa-block">
              <p className="memo-qa-q">
                {q.segment_id == null || q.segment_id === '' ? (
                  <span className="memo-qa-badge">챕터/연속</span>
                ) : (
                  <span className="memo-qa-badge">{q.segment_id}</span>
                )}{' '}
                {q.question}
              </p>
              <ul className="memo-qa-options">
                {q.options.map((opt, idx) => (
                  <li key={idx}>
                    <label>
                      <input
                        type="radio"
                        name={q.id}
                        checked={answers[q.id].selected_index === idx}
                        onChange={() => setAnswers((p) => ({ ...p, [q.id]: { ...p[q.id], selected_index: idx } }))}
                      />{' '}
                      {opt}
                    </label>
                  </li>
                ))}
              </ul>
              <div className="memo-qa-free">
                <label>
                  {q.freeform_hint || '추가로 쓰고 싶은 내용'}
                  <textarea
                    className="mono"
                    maxLength={2000}
                    rows={3}
                    value={answers[q.id].freeform}
                    onChange={(e) =>
                      setAnswers((p) => ({ ...p, [q.id]: { ...p[q.id], freeform: e.target.value } }))
                    }
                  />
                </label>
              </div>
            </div>
          ))}
        </div>

        <footer>
          <div className="scene-actions">
            <button type="button" className="ghost" onClick={onClose} disabled={!!loading}>
              취소
            </button>
            <button
              type="button"
              className="ghost"
              onClick={onSkip}
              disabled={!!loading}
              title="설문 없이 이전과 같이 AI 초안"
            >
              설문 생략
            </button>
            <button type="button" className="primary" onClick={run} disabled={!!loading}>
              {loading ? '생성 중…' : '이 내용으로 AI 초안'}
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}
