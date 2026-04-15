import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  api,
  type BibleEntry,
  type BodySegmentLink,
  type Episode,
  type Story,
} from '../api'

type LocalBody = {
  title: string
  content: string
  link_to_previous: BodySegmentLink | null
}

function combineLocalBodies(blocks: LocalBody[]): string {
  const parts: string[] = []
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i]
    const text = (b.content || '').trim()
    if (i > 0) {
      parts.push(b.link_to_previous === 'omnibus' ? '\n\n* * *\n\n' : '\n\n')
    }
    parts.push(text)
  }
  return parts.join('')
}

/** 이어쓰기 도움: 이전 화 요약 + 직전 본문 끝(같은 챕터면 이전 블록, 아니면 이전 화 마지막 블록) */
function buildBridgeAnchor(
  episodes: Episode[],
  selected: Episode,
  bodies: LocalBody[],
  activeIdx: number,
): { summaryA: string; anchorExcerpt: string } {
  const sorted = [...episodes].sort((a, b) => a.chapter_num - b.chapter_num)
  const prevEp = [...sorted].filter((e) => e.chapter_num < selected.chapter_num).pop()
  const summaryA = prevEp?.summary?.trim() || '(이전 화 요약이 없습니다. 요약·인덱싱을 한 번 실행해 두면 더 정확해집니다.)'

  let anchor = ''
  if (activeIdx > 0) {
    const prevBlock = (bodies[activeIdx - 1]?.content || '').trim()
    anchor = prevBlock.length > 700 ? prevBlock.slice(-700) : prevBlock
  } else if (prevEp?.bodies?.length) {
    const pb = [...prevEp.bodies].sort((a, b) => a.segment_index - b.segment_index)
    const last = (pb[pb.length - 1]?.content || '').trim()
    anchor = last.length > 700 ? last.slice(-700) : last
  }
  return { summaryA, anchorExcerpt: anchor }
}

export function StoryWorkspace() {
  const { storyId } = useParams<{ storyId: string }>()
  const sid = storyId!

  const [story, setStory] = useState<Story | null>(null)
  const [episodes, setEpisodes] = useState<Episode[]>([])
  const [bible, setBible] = useState<BibleEntry[]>([])
  const [epId, setEpId] = useState<string | null>(null)
  const [raw, setRaw] = useState('')
  const [bodies, setBodies] = useState<LocalBody[]>([{ title: '', content: '', link_to_previous: null }])
  const [activeBodyIdx, setActiveBodyIdx] = useState(0)
  const [busy, setBusy] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [exportOpen, setExportOpen] = useState(false)
  const exportRef = useRef<HTMLDivElement>(null)
  const [bibleDrawerOpen, setBibleDrawerOpen] = useState(false)
  const [bridgeMemo, setBridgeMemo] = useState('')
  const [bridgeOut, setBridgeOut] = useState('')
  const [ragQ, setRagQ] = useState('')
  const [ragOut, setRagOut] = useState<string | null>(null)
  const [consistency, setConsistency] = useState<string | null>(null)
  const [consistencyScope, setConsistencyScope] = useState<'chapter' | 'story'>('chapter')
  const [styleTarget, setStyleTarget] = useState('김영하')
  const [styleOpen, setStyleOpen] = useState(false)
  const [bibleDraft, setBibleDraft] = useState<Record<string, unknown>[] | null>(null)
  const [autoSettingNoteOnSave, setAutoSettingNoteOnSave] = useState(true)
  const [toolsOpen, setToolsOpen] = useState(false)

  const selected = useMemo(() => episodes.find((e) => e.id === epId), [episodes, epId])

  const refresh = useCallback(async () => {
    const [st, eps, bi] = await Promise.all([
      api.stories.get(sid),
      api.episodes.list(sid),
      api.bible.list(sid),
    ])
    setStory(st)
    setEpisodes(eps)
    setBible(bi)
    setEpId((prev) => (prev && eps.some((e) => e.id === prev) ? prev : eps[0]?.id ?? null))
  }, [sid])

  useEffect(() => {
    refresh().catch(() => setToast('불러오기 실패 — API·DB를 확인하세요.'))
  }, [refresh])

  useEffect(() => {
    if (!selected) return
    setRaw(selected.raw_memory || '')
    setActiveBodyIdx(0)
    const sorted = [...(selected.bodies ?? [])].sort((a, b) => a.segment_index - b.segment_index)
    if (sorted.length === 0) {
      setBodies([{ title: '', content: selected.ai_content || '', link_to_previous: null }])
      return
    }
    setBodies(
      sorted.map((b, i) => ({
        title: b.title ?? '',
        content: b.content ?? '',
        link_to_previous: i === 0 ? null : (b.link_to_previous ?? 'continuous'),
      })),
    )
  }, [selected?.id])

  useEffect(() => {
    setBibleDraft(null)
  }, [selected?.id])

  useEffect(() => {
    if (!exportOpen) return
    const close = (e: MouseEvent) => {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) setExportOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [exportOpen])

  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)')
    const onChange = () => {
      if (mq.matches) setToolsOpen(false)
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  const saveEpisode = async (opts?: { skipAutoBible?: boolean; silent?: boolean }) => {
    if (!selected) return
    if (!opts?.silent) setBusy('저장')
    try {
      const payload = bodies.map((b, i) => ({
        title: b.title.trim() ? b.title.trim() : null,
        content: b.content,
        link_to_previous: i === 0 ? null : (b.link_to_previous ?? 'continuous'),
      }))
      await api.episodes.replaceBodies(sid, selected.id, payload)
      const p = await api.episodes.patch(sid, selected.id, { raw_memory: raw })
      setEpisodes((prev) => prev.map((e) => (e.id === p.id ? p : e)))

      const combined = combineLocalBodies(bodies).trim()
      if (autoSettingNoteOnSave && combined && !opts?.skipAutoBible) {
        try {
          const br = await api.agent.bibleApply(selected.id)
          await refresh()
          setToast(`저장 완료 · 설정 노트에 ${br.applied}건 반영(자동)`)
        } catch {
          setToast('저장은 되었으나 설정 노트 자동 추출에 실패했습니다.')
          await refresh()
        }
      } else {
        await refresh()
        if (!opts?.skipAutoBible) setToast('저장 완료')
      }
    } catch (e) {
      setToast(String(e))
    } finally {
      if (!opts?.silent) setBusy(null)
    }
  }

  const newChapter = async () => {
    const n = episodes.length ? Math.max(...episodes.map((e) => e.chapter_num)) + 1 : 1
    setBusy('챕터 추가')
    try {
      const e = await api.episodes.create(sid, { chapter_num: n, raw_memory: '' })
      await refresh()
      setEpId(e.id)
      setToast(`챕터 ${n} 생성`)
    } catch (err) {
      setToast(String(err))
    } finally {
      setBusy(null)
    }
  }

  const runExpand = async () => {
    if (!selected) {
      setToast('챕터를 선택한 뒤 사용하세요.')
      return
    }
    setBusy('AI 초안')
    try {
      const r = await api.agent.expand(selected.id, raw || undefined, story?.genre || undefined)
      setBodies((prev) => {
        const next = [...prev]
        const idx = Math.min(Math.max(activeBodyIdx, 0), next.length - 1)
        next[idx] = { ...next[idx], content: r.ai_content }
        return next
      })
      setToast('초안이 에디터에 들어갔습니다. 확인 후 저장하세요.')
    } catch (e) {
      setToast(String(e))
    } finally {
      setBusy(null)
    }
  }

  const runFinalize = async () => {
    if (!selected) return
    setBusy('요약·인덱싱')
    try {
      await saveEpisode({ skipAutoBible: true, silent: true })
      await api.agent.finalize(selected.id)
      const combined = combineLocalBodies(bodies).trim()
      if (autoSettingNoteOnSave && combined) {
        try {
          const br = await api.agent.bibleApply(selected.id)
          await refresh()
          setToast(`요약·인덱스 완료 · 설정 노트 ${br.applied}건 반영`)
        } catch {
          await refresh()
          setToast('요약·인덱스는 되었으나 설정 노트 자동 추출에 실패했습니다.')
        }
      } else {
        await refresh()
        setToast('이 화 요약과 검색용 조각(청크)이 갱신되었습니다.')
      }
    } catch (e) {
      setToast(String(e))
    } finally {
      setBusy(null)
    }
  }

  const runBiblePreview = async () => {
    if (!selected) {
      setToast('챕터를 선택하세요.')
      return
    }
    const combined = combineLocalBodies(bodies).trim()
    if (!combined) {
      setToast('본문이 비어 있습니다.')
      return
    }
    setBusy('설정 추출')
    try {
      const r = await api.agent.bibleExtract(selected.id, combined)
      setBibleDraft(r.entries)
      if (r.entries.length === 0) {
        setToast('추출된 항목이 없습니다.')
      } else {
        setToast(`미리보기 ${r.entries.length}건 — 확인 후 아래에서 확정 저장하세요.`)
      }
    } catch (e) {
      setToast(String(e))
    } finally {
      setBusy(null)
    }
  }

  const runBibleCommit = async () => {
    if (!selected) return
    if (!bibleDraft?.length) {
      setToast('먼저 「미리보기만」으로 추출하세요.')
      return
    }
    setBusy('설정 노트 저장')
    try {
      const r = await api.agent.bibleCommit(selected.id, bibleDraft)
      setBibleDraft(null)
      await refresh()
      setToast(`설정 노트에 ${r.applied}건 저장했습니다.`)
    } catch (e) {
      setToast(String(e))
    } finally {
      setBusy(null)
    }
  }

  const runBridge = async () => {
    if (!selected) return
    const { summaryA, anchorExcerpt } = buildBridgeAnchor(episodes, selected, bodies, activeBodyIdx)
    setBusy('이어쓰기')
    try {
      const r = await api.agent.bridge(summaryA, bridgeMemo, sid, anchorExcerpt || null)
      setBridgeOut(r.suggestions)
    } catch (e) {
      setToast(String(e))
    } finally {
      setBusy(null)
    }
  }

  const runRag = async () => {
    if (!ragQ.trim()) return
    setBusy('검색')
    try {
      const rows = await api.agent.rag(sid, ragQ.trim())
      setRagOut(
        rows.length
          ? rows
              .map((r) => {
                const head =
                  r.source_type === 'bible' ? '[설정 노트]' : `챕터 ${r.chapter_num}`
                const score =
                  r.score != null ? `${(r.score * 100).toFixed(1)}%` : '키워드·유사도'
                return `${head} (관련도 ${score})\n${r.snippet}\n`
              })
              .join('\n---\n')
          : '결과가 없습니다. 다른 단어로 시도해 보세요.',
      )
    } catch (e) {
      setToast(String(e))
    } finally {
      setBusy(null)
    }
  }

  const runConsistency = async () => {
    setBusy('맞춤 검토')
    try {
      const focus =
        consistencyScope === 'chapter' && selected ? selected.id : undefined
      const r = await api.agent.consistency(sid, focus ?? null)
      setConsistency(r.report)
    } catch (e) {
      setToast(String(e))
    } finally {
      setBusy(null)
    }
  }

  const runStyle = async () => {
    const cur = bodies[activeBodyIdx]?.content?.trim()
    if (!cur) return
    setBusy('문체')
    try {
      const r = await api.agent.style(cur, styleTarget)
      setBodies((prev) => {
        const next = [...prev]
        if (next[activeBodyIdx]) next[activeBodyIdx] = { ...next[activeBodyIdx], content: r.text }
        return next
      })
      setStyleOpen(false)
      setToast('문체를 바꾼 텍스트를 에디터에 넣었습니다. 저장을 잊지 마세요.')
    } catch (e) {
      setToast(String(e))
    } finally {
      setBusy(null)
    }
  }

  const download = async (format: 'txt' | 'pdf' | 'epub') => {
    setBusy('추출')
    try {
      const blob = await api.agent.export(sid, format)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${story?.title || 'novel'}.${format}`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setToast(String(e))
    } finally {
      setBusy(null)
    }
  }

  if (!story) {
    return (
      <div className="ws-loading">
        <div className="ws-loading-spinner" aria-hidden />
        <p style={{ margin: 0, fontSize: '0.9rem' }}>작품을 불러오는 중…</p>
        <Link className="ws-back-link" to="/">
          ← 대시보드로
        </Link>
      </div>
    )
  }

  return (
    <div className="workspace-shell">
      {toolsOpen && (
        <div
          className="ws-tools-scrim"
          role="presentation"
          aria-hidden
          onClick={() => setToolsOpen(false)}
        />
      )}
      {bibleDrawerOpen && (
        <div
          className="ws-drawer-scrim"
          role="presentation"
          aria-hidden
          onClick={() => setBibleDrawerOpen(false)}
        />
      )}
      <aside className={`ws-bible-drawer ${bibleDrawerOpen ? 'open' : ''}`} aria-label="설정 노트 패널">
        <div className="ws-bible-drawer-head">
          <div>
            <h2>설정 노트</h2>
            <p style={{ margin: '0.35rem 0 0', fontSize: '0.72rem', color: 'var(--text-muted)', lineHeight: 1.45 }}>
              인물·장소·소품·사건을 한곳에 모아 둔 메모입니다. AI 초안과 검토에 참고됩니다.
            </p>
          </div>
          <button type="button" className="ghost" onClick={() => setBibleDrawerOpen(false)}>
            닫기
          </button>
        </div>
        {bible.length === 0 && (
          <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>아직 항목이 없습니다. 저장 시 자동으로 채울 수 있습니다.</p>
        )}
        <ul className="ws-bible-list">
          {bible.map((b) => (
            <li key={b.id}>
              <strong style={{ color: 'var(--accent)' }}>
                [{b.category}] {b.name}
              </strong>
              <div style={{ marginTop: 6, color: 'var(--text-muted)' }}>{b.description}</div>
            </li>
          ))}
        </ul>
      </aside>

      <header className="ws-topbar">
        <Link className="ws-back-link" to="/">
          ← 목록
        </Link>
        <button
          type="button"
          className="ghost"
          onClick={() => {
            setBibleDrawerOpen(true)
            setToolsOpen(false)
          }}
          aria-expanded={bibleDrawerOpen}
        >
          설정 노트
        </button>
        <button type="button" className="ghost ws-tools-toggle" onClick={() => setToolsOpen((v) => !v)} aria-expanded={toolsOpen}>
          도구 {toolsOpen ? '▴' : '▾'}
        </button>
        <div className="ws-topbar-title-wrap">
          <h1 title={story.title}>{story.title}</h1>
          {story.genre ? <span className="ws-pill">{story.genre}</span> : null}
        </div>
        <div ref={exportRef} className="ws-topbar-export">
          <button type="button" onClick={() => setExportOpen((v) => !v)}>
           보내기 {exportOpen ? '▴' : '▾'}
          </button>
          {exportOpen && (
            <div className="export-dropdown-panel">
              <div className="export-dropdown-hint">원고를 파일로 받습니다.</div>
              <button
                type="button"
                disabled={!!busy}
                onClick={() => {
                  setExportOpen(false)
                  void download('txt')
                }}
              >
                텍스트 (.txt)
              </button>
              <button
                type="button"
                disabled={!!busy}
                onClick={() => {
                  setExportOpen(false)
                  void download('epub')
                }}
              >
                EPUB
              </button>
              <div className="export-dropdown-hint">PDF는 한글 폰트 환경에 따라 달라질 수 있습니다.</div>
              <button
                type="button"
                disabled={!!busy}
                onClick={() => {
                  setExportOpen(false)
                  void download('pdf')
                }}
              >
                PDF
              </button>
            </div>
          )}
        </div>
      </header>

      {toast && (
        <div className="ws-toast-bar">
          <span>{toast}</span>
          <button type="button" className="ghost" onClick={() => setToast(null)}>
            닫기
          </button>
        </div>
      )}

      <div className="ws-layout">
        <div className="ws-main workspace-main" style={{ paddingBottom: '2rem' }}>
          <section className="ws-chapter-bar">
            <div className="ws-chapter-bar-head">
              <span>챕터</span>
              <button type="button" className="primary" onClick={newChapter} disabled={!!busy}>
                + 새 화
              </button>
            </div>
            <div className="ws-chapter-rail">
              {episodes.map((e) => (
                <button
                  key={e.id}
                  type="button"
                  className={`ws-timeline-btn${e.id === epId ? ' active' : ''}`}
                  onClick={() => setEpId(e.id)}
                >
                  <div style={{ fontWeight: 650 }}>{e.chapter_num}화</div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', maxHeight: 34, overflow: 'hidden' }}>
                    {e.summary || '요약 없음'}
                  </div>
                </button>
              ))}
            </div>
          </section>

          <div className="ws-editor-grid">
            <div className="ws-editor-panel">
              <h2>작가 메모</h2>
              <p className="ws-panel-hint">
                사실·감정·복선을 거칠게 적는 공간입니다. AI 초안은 이 내용을 참고합니다.
              </p>
              <textarea className="ws-textarea-memo" value={raw} onChange={(ev) => setRaw(ev.target.value)} />
            </div>
            <div className="ws-editor-panel">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                <h2 style={{ marginBottom: 0 }}>원고 블록</h2>
                <button
                  type="button"
                  disabled={!!busy}
                  onClick={() =>
                    setBodies((p) => [...p, { title: '', content: '', link_to_previous: 'continuous' }])
                  }
                >
                  + 블록 추가
                </button>
              </div>
              <p className="ws-panel-hint">
                장면마다 블록을 나눌 수 있습니다. 활성 블록에 AI 초안·문체 변환이 들어갑니다.
              </p>
              <div className="ws-body-stack">
                {bodies.map((blk, i) => (
                  <div
                    key={i}
                    role="presentation"
                    className={`ws-body-block${i === activeBodyIdx ? ' active' : ''}`}
                    onClick={() => setActiveBodyIdx(i)}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>블록 {i + 1}</span>
                      {i === activeBodyIdx && (
                        <span style={{ fontSize: '0.7rem', color: 'var(--accent)' }}>← 편집 중</span>
                      )}
                      {i > 0 && (
                        <label style={{ fontSize: '0.74rem', display: 'flex', alignItems: 'center', gap: 6 }}>
                          이전과 연결:
                          <select
                            value={blk.link_to_previous ?? 'continuous'}
                            onChange={(ev) => {
                              const v = ev.target.value as BodySegmentLink
                              setBodies((prev) => {
                                const n = [...prev]
                                n[i] = { ...n[i], link_to_previous: v }
                                return n
                              })
                            }}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <option value="continuous">한 흐름으로 이어짐</option>
                            <option value="omnibus">쉼 표시 (＊ ＊ ＊)</option>
                          </select>
                        </label>
                      )}
                      {bodies.length > 1 && (
                        <button
                          type="button"
                          style={{ marginLeft: 'auto', fontSize: '0.7rem' }}
                          onClick={(e) => {
                            e.stopPropagation()
                            const del = i
                            setBodies((prev) => prev.filter((_, j) => j !== del))
                            setActiveBodyIdx((a) => {
                              const nextLen = bodies.length - 1
                              if (a === del) return Math.max(0, Math.min(del, nextLen - 1))
                              if (a > del) return a - 1
                              return a
                            })
                          }}
                        >
                          삭제
                        </button>
                      )}
                    </div>
                    <input
                      style={{ width: '100%', marginBottom: 6, fontSize: '0.85rem' }}
                      placeholder="소제목 (선택)"
                      value={blk.title}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(ev) => {
                        const v = ev.target.value
                        setBodies((prev) => {
                          const n = [...prev]
                          n[i] = { ...n[i], title: v }
                          return n
                        })
                      }}
                    />
                    <textarea
                      style={{ width: '100%', minHeight: 140, fontSize: '0.88rem' }}
                      value={blk.content}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(ev) => {
                        const v = ev.target.value
                        setBodies((prev) => {
                          const n = [...prev]
                          n[i] = { ...n[i], content: v }
                          return n
                        })
                      }}
                    />
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="ws-action-bar">
            <button type="button" className="primary" disabled={!!busy} onClick={runExpand}>
              AI 초안 생성
            </button>
            <button type="button" disabled={!!busy} onClick={() => void saveEpisode()}>
              저장
            </button>
            <label>
              <input
                type="checkbox"
                checked={autoSettingNoteOnSave}
                onChange={(e) => setAutoSettingNoteOnSave(e.target.checked)}
              />
              저장 시 설정 노트 자동 갱신
            </label>
            <button type="button" disabled={!!busy} onClick={runFinalize}>
              이 화 요약 · 검색 인덱스
            </button>
            <button type="button" disabled={!!busy} onClick={runBiblePreview}>
              설정 미리보기만
            </button>
            <button type="button" disabled={!!busy || !bibleDraft?.length} onClick={runBibleCommit}>
              미리보기 확정 저장
            </button>
            {busy && <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>{busy}…</span>}
          </div>

          {bibleDraft && bibleDraft.length > 0 && (
            <section
              style={{
                margin: '0 1rem 1rem',
                padding: '0.75rem 1rem',
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border)',
                borderRadius: 10,
                maxHeight: 200,
                overflow: 'auto',
              }}
            >
              <div style={{ fontWeight: 650, fontSize: '0.85rem', marginBottom: 8 }}>설정 노트 미리보기 (아직 DB에 안 씀)</div>
              <ul style={{ listStyle: 'none', padding: 0, margin: 0, fontSize: '0.8rem' }}>
                {bibleDraft.map((row, i) => (
                  <li key={i} style={{ marginBottom: 8, paddingBottom: 8, borderBottom: '1px solid var(--border)' }}>
                    <strong>
                      [{String(row.category ?? 'CHAR')}] {String(row.name ?? '')}
                    </strong>
                    <div style={{ marginTop: 4, color: 'var(--text-muted)' }}>{String(row.description ?? '')}</div>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <aside className={`ws-tools${toolsOpen ? ' ws-tools-open' : ''}`} aria-label="AI·검색 도구">
          <div className="ws-tools-head-mobile">
            <h2>도구</h2>
            <button type="button" className="ghost" onClick={() => setToolsOpen(false)}>
              닫기
            </button>
          </div>
          <div className="ws-tool-block">
            <h3>이어쓰기 도움</h3>
            <p className="ws-tool-hint">
              직전 화 요약과 방금까지 쓴 끝부분을 바탕으로, 지금 메모와 자연스럽게 잇는 장면 아이디어를 받습니다.
            </p>
            <textarea
              style={{ width: '100%', minHeight: 72, marginBottom: 8 }}
              value={bridgeMemo}
              onChange={(e) => setBridgeMemo(e.target.value)}
              placeholder="이어서 쓰고 싶은 흐름·대사·갈등을 짧게…"
            />
            <button type="button" className="primary" disabled={!!busy} onClick={runBridge}>
              제안 받기
            </button>
            {bridgeOut && (
              <pre
                style={{
                  marginTop: 10,
                  whiteSpace: 'pre-wrap',
                  fontSize: '0.8rem',
                  maxHeight: 200,
                  overflow: 'auto',
                  color: 'var(--text-muted)',
                  lineHeight: 1.5,
                }}
              >
                {bridgeOut}
              </pre>
            )}
          </div>

          <div className="ws-tool-block">
            <h3>설정·본문 맞춤 점검</h3>
            <p className="ws-tool-hint">
              설정 노트와 본문이 어긋난 곳이 있는지 봅니다. 지금 편집 중인 화만 보면 헛갈림이 줄어듭니다.
            </p>
            <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
              <label style={{ fontSize: '0.78rem', display: 'flex', alignItems: 'center', gap: 6 }}>
                <input
                  type="radio"
                  name="cscope"
                  checked={consistencyScope === 'chapter'}
                  onChange={() => setConsistencyScope('chapter')}
                />
                지금 이 화만
              </label>
              <label style={{ fontSize: '0.78rem', display: 'flex', alignItems: 'center', gap: 6 }}>
                <input
                  type="radio"
                  name="cscope"
                  checked={consistencyScope === 'story'}
                  onChange={() => setConsistencyScope('story')}
                />
                최근 여러 화
              </label>
            </div>
            <button type="button" disabled={!!busy} onClick={runConsistency}>
              점검 실행
            </button>
            {consistency && (
              <pre
                style={{
                  marginTop: 10,
                  whiteSpace: 'pre-wrap',
                  fontSize: '0.78rem',
                  maxHeight: 220,
                  overflow: 'auto',
                  lineHeight: 1.5,
                }}
              >
                {consistency}
              </pre>
            )}
            {consistency && (
              <button type="button" className="ghost" style={{ marginTop: 8 }} onClick={() => setConsistency(null)}>
                결과 지우기
              </button>
            )}
          </div>

          <div className="ws-tool-block">
            <h3>과거 장면 되짚기</h3>
            <p className="ws-tool-hint">
              비슷한 표현·인물·장소가 나온 구절을 찾습니다. 임베딩을 켜면 의미가 비슷한 문장도 잡히고, 꺼 두면 글자
              유사도와 키워드로도 넓게 찾습니다.
            </p>
            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
              <input
                style={{ flex: 1, minWidth: 0 }}
                value={ragQ}
                onChange={(e) => setRagQ(e.target.value)}
                placeholder="단어·느낌·장면 (예: 지하철, 후회)"
              />
              <button type="button" onClick={runRag} disabled={!!busy}>
                찾기
              </button>
            </div>
            {ragOut && (
              <pre
                style={{
                  marginTop: 10,
                  padding: 10,
                  background: 'var(--bg-input)',
                  borderRadius: 8,
                  fontSize: '0.78rem',
                  whiteSpace: 'pre-wrap',
                  maxHeight: 200,
                  overflow: 'auto',
                  lineHeight: 1.45,
                }}
              >
                {ragOut}
              </pre>
            )}
          </div>

          <div className="ws-tool-block">
            <h3>문체 바꾸기</h3>
            <p className="ws-tool-hint">활성 블록만, 참고 작가 톤에 가깝게 고칩니다.</p>
            <button type="button" disabled={!!busy} onClick={() => setStyleOpen(true)}>
              문체 선택…
            </button>
          </div>
        </aside>
      </div>

      {styleOpen && (
        <div className="ws-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="style-modal-title">
          <div className="ws-modal">
            <h3 id="style-modal-title" style={{ marginTop: 0, color: 'var(--accent)' }}>
              문체 변환
            </h3>
            <input
              style={{ width: '100%', marginBottom: 10 }}
              value={styleTarget}
              onChange={(e) => setStyleTarget(e.target.value)}
              placeholder="예: 김영하, 무라카미 하루키"
            />
            <button type="button" className="primary" onClick={runStyle} disabled={!!busy}>
              활성 블록에 적용
            </button>
            <button type="button" style={{ marginLeft: 8 }} onClick={() => setStyleOpen(false)}>
              취소
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
