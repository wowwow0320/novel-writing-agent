import { useMemo } from 'react'

import type {
  EpisodeMetaTags,
  EpisodeReview,
  POVKind,
  ReviewCategory,
  ReviewIssue,
  ReviewSeverity,
  TenseKind,
} from '../api'

type Props = {
  review: EpisodeReview | null
  loading: boolean
  error: string | null
  metaTags: EpisodeMetaTags
  onClose: () => void
  onRerun: () => void
  onToggleBypass: (issueId: string, nextBypassed: boolean) => void
  onMetaChange: (patch: EpisodeMetaTags) => void
  onJumpToChapter?: (episodeId: string, chapterNum: number) => void
}

const SEVERITY_LABEL: Record<ReviewSeverity, string> = {
  info: '정보',
  warn: '주의',
  error: '심각',
}

const CATEGORY_LABEL: Record<ReviewCategory, string> = {
  continuity: '연속성',
  pov: '시점·시제',
  logic: '설정 충돌',
  bible: '바이블 모순',
  chapter_flow: '챕터 흐름',
  style: '문체',
}

const POV_OPTIONS: { value: POVKind; label: string }[] = [
  { value: 'unknown', label: '(지정 안 함)' },
  { value: '1st', label: '1인칭' },
  { value: '3rd_limited', label: '3인칭 한정' },
  { value: '3rd_omniscient', label: '3인칭 전지' },
  { value: '2nd', label: '2인칭' },
  { value: 'mixed', label: '혼합' },
]

const TENSE_OPTIONS: { value: TenseKind; label: string }[] = [
  { value: 'unknown', label: '(지정 안 함)' },
  { value: 'past', label: '과거' },
  { value: 'present', label: '현재' },
  { value: 'mixed', label: '혼합' },
]

export function ReviewPanel({
  review,
  loading,
  error,
  metaTags,
  onClose,
  onRerun,
  onToggleBypass,
  onMetaChange,
  onJumpToChapter,
}: Props) {
  const issues: ReviewIssue[] = useMemo(() => review?.issues ?? [], [review])
  const counts = useMemo(() => {
    const c = { info: 0, warn: 0, error: 0, bypassed: 0 }
    for (const it of issues) {
      if (it.bypassed) c.bypassed += 1
      c[it.severity] += 1
    }
    return c
  }, [issues])

  return (
    <aside className="review-panel">
      <div className="review-panel-head">
        <div>
          <strong>이 챕터 검수</strong>
          <span className="review-panel-sub">
            {review ? (
              <>
                총 {issues.length}건 · 심각 {counts.error} / 주의 {counts.warn} / 정보 {counts.info}
                {counts.bypassed ? ` · 우회 ${counts.bypassed}` : ''}
              </>
            ) : loading ? (
              '검수 실행 중…'
            ) : (
              '수동 트리거 전'
            )}
          </span>
        </div>
        <div className="review-panel-head-actions">
          <button className="btn-ghost" onClick={onRerun} disabled={loading}>
            다시 검수
          </button>
          <button className="btn-ghost" onClick={onClose}>
            닫기
          </button>
        </div>
      </div>

      <section className="review-section">
        <h4>챕터 검수 태그 (meta_tags)</h4>
        <div className="review-meta-grid">
          <label>
            <span>시점</span>
            <select
              value={(metaTags.pov as POVKind) ?? 'unknown'}
              onChange={(e) =>
                onMetaChange({
                  ...metaTags,
                  pov: (e.target.value as POVKind) === 'unknown' ? undefined : (e.target.value as POVKind),
                })
              }
            >
              {POV_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>시제</span>
            <select
              value={(metaTags.tense as TenseKind) ?? 'unknown'}
              onChange={(e) =>
                onMetaChange({
                  ...metaTags,
                  tense: (e.target.value as TenseKind) === 'unknown' ? undefined : (e.target.value as TenseKind),
                })
              }
            >
              {TENSE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="review-meta-check">
            <input
              type="checkbox"
              checked={!!metaTags.omnibus}
              onChange={(e) => onMetaChange({ ...metaTags, omnibus: e.target.checked || undefined })}
            />
            <span>옴니버스 (연속성 우회)</span>
          </label>
          <label className="review-meta-check">
            <input
              type="checkbox"
              checked={!!metaTags.time_jump}
              onChange={(e) => onMetaChange({ ...metaTags, time_jump: e.target.checked || undefined })}
            />
            <span>시간 도약 (챕터 흐름 우회)</span>
          </label>
          <label className="review-meta-check">
            <input
              type="checkbox"
              checked={!!metaTags.allow_discontinuity}
              onChange={(e) =>
                onMetaChange({ ...metaTags, allow_discontinuity: e.target.checked || undefined })
              }
            />
            <span>의도된 단절 (continuity 이슈 자동 우회)</span>
          </label>
        </div>
        {review?.allowed_bypasses?.length ? (
          <div className="review-bypass-hint">
            자동 우회 중인 카테고리: {review.allowed_bypasses.join(', ')}
          </div>
        ) : null}
      </section>

      {error && <div className="review-error">{error}</div>}

      {review?.pov && (
        <section className="review-section">
          <h4>시점·시제 판정 (Agent)</h4>
          <div className="review-pov-row">
            <span className="review-chip">POV: {review.pov.pov}</span>
            <span className="review-chip">시제: {review.pov.tense}</span>
            <span className="review-chip subtle">
              신뢰도: {(review.pov.confidence * 100).toFixed(0)}%
            </span>
          </div>
          {review.pov.rationale && <p className="review-pov-note">{review.pov.rationale}</p>}
        </section>
      )}

      <section className="review-section">
        <h4>이슈 카드</h4>
        {!review ? (
          <p className="review-muted">
            우측 상단 「이 챕터 검수」로 트리거하세요. 검수는 **AI 초안 직후 자동 실행되지 않습니다**.
          </p>
        ) : issues.length === 0 ? (
          <p className="review-muted">모순·연속성 문제가 감지되지 않았습니다.</p>
        ) : (
          <ul className="review-issue-list">
            {issues.map((it) => (
              <li
                key={it.id}
                className={`review-issue sev-${it.severity} ${it.bypassed ? 'bypassed' : ''}`}
              >
                <div className="review-issue-head">
                  <span className={`review-badge sev-${it.severity}`}>
                    {SEVERITY_LABEL[it.severity]}
                  </span>
                  <span className="review-badge cat">{CATEGORY_LABEL[it.category]}</span>
                  <label className="review-bypass-toggle" title="이 이슈를 의도된 전환으로 표시">
                    <input
                      type="checkbox"
                      checked={!!it.bypassed}
                      onChange={(e) => onToggleBypass(it.id, e.target.checked)}
                    />
                    <span>의도된 전환</span>
                  </label>
                </div>
                <p className="review-issue-msg">{it.message}</p>
                {it.evidence && (
                  <blockquote className="review-issue-evidence">{it.evidence}</blockquote>
                )}
                {it.suggestion && (
                  <div className="review-issue-suggest">
                    <strong>제안.</strong> {it.suggestion}
                  </div>
                )}
                {it.bypassed && it.bypass_reason && (
                  <div className="review-issue-bypass-reason">{it.bypass_reason}</div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {review?.chapter_flow_note && (
        <section className="review-section">
          <h4>챕터 흐름 메모</h4>
          <p className="review-flow-note">{review.chapter_flow_note}</p>
        </section>
      )}

      {review?.top_k_hits?.length ? (
        <section className="review-section">
          <h4>Top-K 유사 장면</h4>
          <ul className="review-hit-list">
            {review.top_k_hits.map((h, i) => {
              const eid = String(h.episode_id ?? '')
              const ch = Number(h.chapter_num ?? 0)
              const snippet = String(h.snippet ?? '').slice(0, 320)
              const score = typeof h.score === 'number' ? h.score.toFixed(3) : ''
              return (
                <li key={`${eid}-${i}`}>
                  <div className="review-hit-meta">
                    <span className="review-chip">ch {ch}</span>
                    {score && <span className="review-chip subtle">score {score}</span>}
                    {h.color_tag ? (
                      <span className="review-chip subtle">tag {String(h.color_tag)}</span>
                    ) : null}
                    {onJumpToChapter && eid && ch ? (
                      <button className="btn-link" onClick={() => onJumpToChapter(eid, ch)}>
                        해당 챕터로 이동
                      </button>
                    ) : null}
                  </div>
                  <p className="review-hit-snippet">{snippet}</p>
                </li>
              )
            })}
          </ul>
        </section>
      ) : null}

      {review?.logic && (
        <section className="review-section">
          <h4>규칙 기반 지표</h4>
          <dl className="review-logic">
            <dt>코사인 유사도</dt>
            <dd>{String(review.logic.cosine_similarity ?? '-')}</dd>
            <dt>전이 점수</dt>
            <dd>{String(review.logic.transition_score ?? '-')}</dd>
            <dt>사용자 확인 필요</dt>
            <dd>{review.logic.needs_user_decision ? '예' : '아니오'}</dd>
          </dl>
        </section>
      )}
    </aside>
  )
}
