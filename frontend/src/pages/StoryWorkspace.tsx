import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  api,
  type BibleEntry,
  type BodySegmentLink,
  type Episode,
  type EpisodeBodyItem,
  type EpisodeMetaTags,
  type EpisodeReview,
  type RAGSearchHit,
  type ScenePlanItem,
  type Story,
  type StyleAxes,
  type MemoQaAnswerItem,
  type MemoQaSurveyResponse,
  type MemoSurveySnapshot,
} from '../api'
import { IntakeModal } from '../components/IntakeModal'
import { MemoQaModal, type MemoQaModalResult } from '../components/MemoQaModal'
import { ReviewPanel } from '../components/ReviewPanel'
import { ScenePlanModal, type ScenePlanModalResult } from '../components/ScenePlanModal'
import GraphView3D from '../components/GraphView3D'

const STYLE_AXES_STORAGE_KEY = 'novel-agent:style-axes'

function loadStyleAxes(): StyleAxes {
  try {
    const raw = localStorage.getItem(STYLE_AXES_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as StyleAxes
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function saveStyleAxes(axes: StyleAxes) {
  try {
    localStorage.setItem(STYLE_AXES_STORAGE_KEY, JSON.stringify(axes))
  } catch {
    /* noop */
  }
}

function formatGraphFinalizeHint(
  graphSync:
    | { enabled?: boolean; entities?: number; relations?: number; error?: string }
    | undefined,
): string {
  if (!graphSync) return ''
  const err = typeof graphSync.error === 'string' ? graphSync.error.trim() : ''
  if (err) {
    const short = err.slice(0, 140)
    return ` · Neo4j 기록 실패: ${short}${err.length > 140 ? '…' : ''}`
  }
  const ent = graphSync.entities ?? 0
  const rel = graphSync.relations ?? 0
  const on = graphSync.enabled === true || ent > 0 || rel > 0
  if (!on) {
    return ' · 그래프 기능 OFF — backend/.env 의 GRAPH_ENABLED=true + Neo4j HTTP(7474) 설정 후 백엔드 재시작'
  }
  return ` · 그래프 반영: 엔티티 ${ent}, 관계 ${rel}${rel === 0 ? ' (관계 0이면 3D는 빈 화면)' : ''}`
}

type LocalBody = {
  title: string
  content: string
  body_summary: string
  link_to_previous: BodySegmentLink | null
  meta_tags: Record<string, unknown> | null
}

type PendingScenePlan = {
  scenes: ScenePlanItem[]
  /** 현재 챕터에 로드된 씬별 본문. scene_id → content. 부분 재생성 머지용. */
  contents: Record<string, string>
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

function toEpisodeBodyPayload(blocks: LocalBody[]): EpisodeBodyItem[] {
  return blocks.map((b, i) => ({
    title: b.title.trim() ? b.title.trim() : null,
    content: b.content,
    body_summary: b.body_summary.trim() ? b.body_summary.trim() : null,
    link_to_previous: i === 0 ? null : (b.link_to_previous ?? 'continuous'),
    meta_tags: b.meta_tags && Object.keys(b.meta_tags).length > 0 ? b.meta_tags : null,
  }))
}

const FLOW_LOG_MAX = 24

function flowEntryId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

type FlowLogEntry = {
  id: string
  at: string
  title: string
  route: string
  inputLines: string[]
  outputLines: string[]
  persisted?: string
}

type WriterContextPreview = Awaited<ReturnType<typeof api.agent.contextPreview>>

/** 이어쓰기 도움: 이전 챕터 요약 + 직전 본문 끝(같은 챕터면 이전 블록, 아니면 이전 챕터 마지막 블록) */
function buildBridgeAnchor(
  episodes: Episode[],
  selected: Episode,
  bodies: LocalBody[],
  activeIdx: number,
): { summaryA: string; anchorExcerpt: string } {
  const sorted = [...episodes].sort((a, b) => a.chapter_num - b.chapter_num)
  const prevEp = [...sorted].filter((e) => e.chapter_num < selected.chapter_num).pop()
  const summaryA = prevEp?.summary?.trim() || '(이전 챕터 요약이 없습니다. 요약·인덱싱을 한 번 실행해 두면 더 정확해집니다.)'

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
  const [bodies, setBodies] = useState<LocalBody[]>([
    { title: '', content: '', body_summary: '', link_to_previous: null, meta_tags: null },
  ])
  const [activeBodyIdx, setActiveBodyIdx] = useState(0)
  const [busy, setBusy] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [exportOpen, setExportOpen] = useState(false)
  const exportRef = useRef<HTMLDivElement>(null)
  const autoCreatedFirstChapterRef = useRef(false)
  const [bibleDrawerOpen, setBibleDrawerOpen] = useState(false)
  const [bridgeMemo, setBridgeMemo] = useState('')
  const [bridgeOut, setBridgeOut] = useState('')
  const [ragQ, setRagQ] = useState('')
  const [ragHits, setRagHits] = useState<RAGSearchHit[] | null>(null)
  const [worldDraft, setWorldDraft] = useState('')
  const [consistency, setConsistency] = useState<string | null>(null)
  const [consistencyScope, setConsistencyScope] = useState<'chapter' | 'story'>('chapter')
  const [styleTarget, setStyleTarget] = useState('김영하')
  const [styleOpen, setStyleOpen] = useState(false)
  const [bibleDraft, setBibleDraft] = useState<Record<string, unknown>[] | null>(null)
  const [autoSettingNoteOnSave, setAutoSettingNoteOnSave] = useState(true)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [flowOpen, setFlowOpen] = useState(false)
  const [flowLog, setFlowLog] = useState<FlowLogEntry[]>([])
  const [contextPreview, setContextPreview] = useState<WriterContextPreview | null>(null)
  const [contextPreviewErr, setContextPreviewErr] = useState<string | null>(null)
  const [memoryTrace, setMemoryTrace] = useState<Record<string, unknown>[] | null>(null)
  const [intakeOpen, setIntakeOpen] = useState(false)
  const [graph3dOpen, setGraph3dOpen] = useState(false)
  const [styleAxes, setStyleAxes] = useState<StyleAxes>(() => loadStyleAxes())
  const [scenePlanOpen, setScenePlanOpen] = useState(false)
  const [pendingPlan, setPendingPlan] = useState<PendingScenePlan | null>(null)
  const [memoQaOpen, setMemoQaOpen] = useState(false)
  const [memoQaSurvey, setMemoQaSurvey] = useState<MemoQaSurveyResponse | null>(null)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [review, setReview] = useState<EpisodeReview | null>(null)
  const [reviewErr, setReviewErr] = useState<string | null>(null)
  const [reviewLoading, setReviewLoading] = useState(false)
  const [chapterMeta, setChapterMeta] = useState<EpisodeMetaTags>({})

  const selected = useMemo(() => episodes.find((e) => e.id === epId), [episodes, epId])

  const pushFlowLog = useCallback((entry: Omit<FlowLogEntry, 'id' | 'at'>) => {
    setFlowLog((prev) =>
      [{ ...entry, id: flowEntryId(), at: new Date().toLocaleTimeString('ko-KR') }, ...prev].slice(
        0,
        FLOW_LOG_MAX,
      ),
    )
  }, [])

  const refresh = useCallback(async () => {
    const [st, eps, bi] = await Promise.all([
      api.stories.get(sid),
      api.episodes.list(sid),
      api.bible.list(sid),
    ])
    setStory(st)
    setWorldDraft(st.world_setting ?? '')
    let nextEpisodes = eps
    if (nextEpisodes.length === 0 && !autoCreatedFirstChapterRef.current) {
      autoCreatedFirstChapterRef.current = true
      try {
        const created = await api.episodes.create(sid, { chapter_num: 1, raw_memory: '' })
        nextEpisodes = [created]
        setToast('챕터 1을 자동으로 준비했습니다.')
      } catch (e) {
        autoCreatedFirstChapterRef.current = false
        setToast(`첫 챕터 자동 생성 실패: ${String(e)}`)
      }
    }
    setEpisodes(nextEpisodes)
    setBible(bi)
    setEpId((prev) => (prev && nextEpisodes.some((e) => e.id === prev) ? prev : nextEpisodes[0]?.id ?? null))
  }, [sid])

  useEffect(() => {
    autoCreatedFirstChapterRef.current = false
  }, [sid])

  useEffect(() => {
    refresh().catch(() => setToast('불러오기 실패 — API·DB를 확인하세요.'))
  }, [refresh])

  useEffect(() => {
    if (!selected) return
    setRaw(selected.raw_memory || '')
    setActiveBodyIdx(0)
    setMemoryTrace(null)
    const sorted = [...(selected.bodies ?? [])].sort((a, b) => a.segment_index - b.segment_index)
    if (sorted.length === 0) {
      setBodies([
        {
          title: '',
          content: selected.ai_content || '',
          body_summary: '',
          link_to_previous: null,
          meta_tags: null,
        },
      ])
      setPendingPlan(null)
      return
    }
    const mapped = sorted.map((b, i) => ({
      title: b.title ?? '',
      content: b.content ?? '',
      body_summary: b.body_summary ?? '',
      link_to_previous: i === 0 ? null : (b.link_to_previous ?? 'continuous'),
      meta_tags: b.meta_tags ?? null,
    }))
    setBodies(mapped)
    // 블록 meta_tags.scene_plan_id 가 있으면 이전 씬 플랜 상태를 복구해 부분 재생성이 가능하게 한다.
    const recoveredContents: Record<string, string> = {}
    const recoveredScenes: ScenePlanItem[] = []
    for (const b of mapped) {
      const sid = b.meta_tags && typeof b.meta_tags.scene_plan_id === 'string' ? b.meta_tags.scene_plan_id : ''
      if (!sid) continue
      recoveredContents[sid] = b.content
      recoveredScenes.push({
        id: sid,
        beat: typeof b.meta_tags?.beat === 'string' ? b.meta_tags.beat : '기',
        pov: typeof b.meta_tags?.pov === 'string' ? b.meta_tags.pov : '3rd_limited',
        goal: '',
        tension: typeof b.meta_tags?.tension === 'string' ? b.meta_tags.tension : 'mid',
        hint: '',
        approx_chars: Math.max(200, (b.content || '').length),
      })
    }
    setPendingPlan(recoveredScenes.length > 0 ? { scenes: recoveredScenes, contents: recoveredContents } : null)
  }, [selected?.id])

  useEffect(() => {
    setBibleDraft(null)
  }, [selected?.id])

  useEffect(() => {
    setContextPreview(null)
    setContextPreviewErr(null)
  }, [selected?.id])

  useEffect(() => {
    // 챕터 전환 시 검수 결과·챕터 태그 재수화.
    setReview(null)
    setReviewErr(null)
    setReviewOpen(false)
    setChapterMeta((selected?.meta_tags as EpisodeMetaTags) ?? {})
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

  const saveEpisode = async (opts?: {
    skipAutoBible?: boolean
    silent?: boolean
    flowLabel?: string
  }) => {
    if (!selected) return
    const shouldLogFlow = !opts?.silent || !!opts?.flowLabel
    if (!opts?.silent) setBusy('저장')
    let bibleApplied: number | undefined
    try {
      const payload = toEpisodeBodyPayload(bodies)
      const combined = combineLocalBodies(bodies).trim()
      await api.episodes.replaceBodies(sid, selected.id, payload)
      const p = await api.episodes.patch(sid, selected.id, { raw_memory: raw })
      setEpisodes((prev) => prev.map((e) => (e.id === p.id ? p : e)))

      if (autoSettingNoteOnSave && combined && !opts?.skipAutoBible) {
        try {
          const br = await api.agent.bibleApply(selected.id)
          bibleApplied = br.applied
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

      if (shouldLogFlow) {
        const routes = [
          `PUT /api/stories/${sid}/episodes/${selected.id}/bodies`,
          `PATCH /api/stories/${sid}/episodes/${selected.id}`,
        ]
        if (bibleApplied != null) routes.push(`POST /api/agent/bible-apply/${selected.id}`)
        const outSecond =
          bibleApplied != null
            ? `설정 노트 자동: ${bibleApplied}건 반영`
            : opts?.skipAutoBible
              ? '설정 자동(bible-apply) 생략'
              : !autoSettingNoteOnSave
                ? '토글 꺼짐 — bible-apply 없음'
                : !combined
                  ? '본문 비어 있음 — bible-apply 없음'
                  : 'bible-apply 없음'
        pushFlowLog({
          title: opts?.flowLabel ?? '저장',
          route: routes.join('\n'),
          inputLines: [
            `블록 ${payload.length}개`,
            `합본 ${combined.length}자`,
            `작가 메모 ${(raw || '').length}자`,
          ],
          outputLines: ['챕터 상태 갱신(목록 재조회)', outSecond],
          persisted:
            bibleApplied != null
              ? 'DB: episode_bodies, episodes.raw_memory · story_bible(+임베딩) · (서버 설정 시) Neo4j'
              : 'DB: episode_bodies, episodes.raw_memory',
        })
      }
    } catch (e) {
      setToast(String(e))
    } finally {
      if (!opts?.silent) setBusy(null)
    }
  }

  const persistGeneratedDraft = async (nextBodies: LocalBody[], nextRaw: string, sourceLabel: string) => {
    if (!selected) return
    const payload = toEpisodeBodyPayload(nextBodies)
    const combined = combineLocalBodies(nextBodies).trim()
    const routes = [
      `PUT /api/stories/${sid}/episodes/${selected.id}/bodies`,
      `PATCH /api/stories/${sid}/episodes/${selected.id}`,
      `POST /api/agent/finalize-episode/${selected.id}`,
    ]
    const syncTrace: string[] = []
    let fin: Awaited<ReturnType<typeof api.agent.finalize>> | null = null
    let bibleN: number | undefined
    setBusy('초안 저장·RAG·그래프 동기화')
    try {
      await api.episodes.replaceBodies(sid, selected.id, payload)
      syncTrace.push(`replaceBodies: ${payload.length}개`)
      const patched = await api.episodes.patch(sid, selected.id, { raw_memory: nextRaw })
      setEpisodes((prev) => prev.map((e) => (e.id === patched.id ? patched : e)))
      syncTrace.push(`raw_memory: ${nextRaw.length}자`)
      fin = await api.agent.finalize(selected.id)
      syncTrace.push(
        `finalize: 청크 ${fin.chunks_indexed ? 'OK' : 'NO'} · 기억 사건 ${fin.memory_sync?.events ?? 0} · 엔티티 ${
          fin.memory_sync?.entities ?? 0
        } · 관계 ${fin.memory_sync?.relationships ?? 0} · 요약트리 ${fin.summary_tree_sync?.nodes ?? 0}`,
      )

      if (autoSettingNoteOnSave && combined) {
        routes.push(`POST /api/agent/bible-apply/${selected.id}`)
        try {
          const br = await api.agent.bibleApply(selected.id)
          bibleN = br.applied
          syncTrace.push(`bible-apply: ${br.applied}건`)
        } catch (e) {
          syncTrace.push(`bible-apply 실패: ${String(e).slice(0, 160)}`)
        }
      } else {
        syncTrace.push(autoSettingNoteOnSave ? 'bible-apply: 본문 없음' : 'bible-apply: 토글 꺼짐')
      }

      await refresh()
      setToast(
        bibleN != null
          ? `초안 저장·검색 인덱싱 완료 · 설정 ${bibleN}건 반영${formatGraphFinalizeHint(fin.graph_sync)}`
          : `초안 저장·검색 인덱싱 완료${formatGraphFinalizeHint(fin.graph_sync)}`,
      )
      pushFlowLog({
        title: `${sourceLabel} 저장·동기화`,
        route: routes.join('\n'),
        inputLines: [
          `블록 ${payload.length}개`,
          `합본 ${combined.length}자`,
          `작가 메모 ${nextRaw.length}자`,
        ],
        outputLines: [
          ...syncTrace,
          `블록 요약 갱신: ${fin.block_summaries_updated}개`,
          `chapter_events: ${fin.chapter_events?.length ?? 0}건`,
          fin.graph_sync?.error
            ? `Neo4j: 실패 — ${String(fin.graph_sync.error).slice(0, 160)}`
            : fin.graph_sync?.enabled === true ||
                (fin.graph_sync?.entities ?? 0) > 0 ||
                (fin.graph_sync?.relations ?? 0) > 0
              ? `Neo4j: 엔티티 ${fin.graph_sync?.entities ?? 0} · 관계 ${fin.graph_sync?.relations ?? 0}`
              : 'Neo4j: OFF 또는 투영 없음',
        ],
        persisted:
          'DB: episode_bodies, episodes.raw_memory, episode_chunks, canonical memory, generation_runs.revision_payload.sync_trace · (옵션) Neo4j/story_bible',
      })
    } catch (e) {
      setToast(`초안은 생성되었지만 저장·동기화 실패: ${String(e)}`)
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
      pushFlowLog({
        title: '새 챕터 추가',
        route: `POST /api/stories/${sid}/episodes`,
        inputLines: [`chapter_num: ${n}`, 'raw_memory: (빈 문자열)'],
        outputLines: [`새 episode id: ${e.id.slice(0, 8)}…`],
        persisted: 'DB: episodes (초안)',
      })
    } catch (err) {
      setToast(String(err))
    } finally {
      setBusy(null)
    }
  }

  const runExpandWithPayload = async (opts: {
    memo_survey?: MemoSurveySnapshot
    memo_qa_answers?: Record<string, MemoQaAnswerItem>
    logTitle?: string
  }) => {
    if (!selected) return
    setBusy(
      opts.memo_qa_answers
        ? 'AI 초안 생성 중 — /api/agent/expand-draft (Q-A 보감)'
        : 'AI 초안 생성 중 — /api/agent/expand-draft',
    )
    try {
      const r = await api.agent.expand({
        episodeId: selected.id,
        raw_memory: raw || undefined,
        genre_override: story?.genre || undefined,
        style_axes: Object.keys(styleAxes).length ? styleAxes : undefined,
        memory_mode: 'auto',
        memo_survey: opts.memo_survey,
        memo_qa_answers: opts.memo_qa_answers,
      })
      const traceRaw = (r.context_used as { memory_trace?: unknown }).memory_trace
      const trace = Array.isArray(traceRaw)
        ? traceRaw.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object' && !Array.isArray(item))
        : []
      setMemoryTrace(trace)
      const exScenes = r.scenes ?? []
      const qa = !!opts.memo_qa_answers
      const sourceLabel = qa ? 'Q-A 보강 초안' : opts.memo_survey ? '자동 분할 초안' : 'AI 초안'
      let nextBodies: LocalBody[]
      if (exScenes.length > 1) {
        nextBodies = exScenes.map((s, i) => ({
          title: '',
          content: s.content,
          body_summary: '',
          link_to_previous: i === 0 ? null : 'continuous',
          meta_tags: {
            memo_orchestrated: true,
            memo_qa: qa,
            memo_segment_id: s.scene_id,
            memo_segment_label: s.label ?? null,
            memo_segment_order: s.order ?? i + 1,
            source: 'memo_survey',
          },
        }))
        setBodies(nextBodies)
        setActiveBodyIdx(0)
      } else {
        const base =
          bodies.length > 0
            ? [...bodies]
            : [{ title: '', content: '', body_summary: '', link_to_previous: null, meta_tags: null }]
        const idx = Math.min(Math.max(activeBodyIdx, 0), base.length - 1)
        const onlyScene = exScenes[0]
        base[idx] = {
          ...base[idx],
          content: r.ai_content,
          meta_tags: {
            ...(base[idx].meta_tags ?? {}),
            memo_orchestrated: !!opts.memo_survey,
            memo_qa: qa,
            ...(onlyScene
              ? {
                  memo_segment_id: onlyScene.scene_id,
                  memo_segment_label: onlyScene.label ?? null,
                  memo_segment_order: onlyScene.order ?? 1,
                }
              : {}),
            source: opts.memo_survey ? 'memo_survey' : 'expand',
          },
        }
        nextBodies = base
        setBodies(nextBodies)
      }
      const ctxKeys = r.context_used && typeof r.context_used === 'object' ? Object.keys(r.context_used) : []
      const mode = r.context_used && typeof r.context_used === 'object' ? (r.context_used as { generation_mode?: string }).generation_mode : undefined
      const generationRunId =
        r.context_used && typeof r.context_used === 'object'
          ? (r.context_used as { generation_run_id?: string }).generation_run_id
          : undefined
      const segmentCount =
        r.context_used && typeof r.context_used === 'object'
          ? (r.context_used as { segment_count?: number }).segment_count
          : undefined
      pushFlowLog({
        title: opts.logTitle ?? 'AI 초안 생성',
        route: 'POST /api/agent/expand-draft' + (qa ? ' (memo_survey + memo_qa_answers)' : ''),
        inputLines: [
          `episode_id: ${selected.id}`,
          `raw_memory: ${(raw || '').length}자`,
          `genre_override: ${story?.genre || '(스토리 장르 그대로)'}`,
          Object.keys(styleAxes).length ? `style_axes: ${JSON.stringify(styleAxes)}` : 'style_axes: (없음)',
          qa ? 'memo_survey+memo_qa_answers' : 'memo_survey: (없음)',
        ],
        outputLines: [
          mode ? `generation_mode: ${mode}` : 'generation_mode: (없음)',
          `자동 기억 검색: ${trace.length}회`,
          generationRunId ? `generation_run_id: ${generationRunId.slice(0, 8)}…` : 'generation_run_id: (없음)',
          segmentCount ? `segment_count: ${segmentCount}` : 'segment_count: (없음)',
          exScenes.length > 1
            ? `다블록 ${exScenes.length}개${qa ? ' · Q-A 보감' : ''} → meta_tags`
            : `ai_content: ${r.ai_content.length}자 → 활성 블록 ${exScenes.length <= 1 ? activeBodyIdx + 1 : 1}에 반영`,
          ...exScenes.map((s) => `  · ${s.label ?? s.scene_id}: ${s.approx_chars}자`),
          ctxKeys.length ? `context_used 키: ${ctxKeys.join(', ')}` : 'context_used: (없음)',
        ],
        persisted: 'DB: generation_runs에 memory_trace 저장 · 다음 단계에서 episode_bodies/finalize 동기화',
      })
      await persistGeneratedDraft(nextBodies, raw || '', sourceLabel)
    } catch (e) {
      setToast(String(e))
    } finally {
      setBusy(null)
    }
  }

  const runExpand = async () => {
    if (!selected) {
      setToast('챕터를 선택한 뒤 사용하세요.')
      return
    }
    if (!(raw || '').trim()) {
      setToast('작가 메모를 입력한 뒤 사용하세요.')
      return
    }
    setBusy('질의·블록 설계 — /api/agent/memo-qa-survey')
    let surveyForExpand: MemoQaSurveyResponse | null = null
    try {
      const survey = await api.agent.memoQaSurvey({
        episodeId: selected.id,
        raw_memory: raw || undefined,
        style_axes: Object.keys(styleAxes).length ? styleAxes : undefined,
      })
      const needsQuestions = survey.questions.length > 0 && (survey.readiness?.needs_questions ?? true)
      pushFlowLog({
        title: '초안 전 분할·부족도 판단',
        route: 'POST /api/agent/memo-qa-survey',
        inputLines: [
          `episode_id: ${selected.id}`,
          `raw_memory: ${(raw || '').length}자`,
          Object.keys(styleAxes).length ? `style_axes: ${JSON.stringify(styleAxes)}` : 'style_axes: (없음)',
        ],
        outputLines: [
          `readiness: ${Math.round((survey.readiness?.score ?? 0) * 100)}점 · 질문 ${
            survey.readiness?.needs_questions ? '필요' : '불필요'
          }`,
          `segments: ${survey.estimated_work?.segments ?? survey.segments.length}`,
          `draft_calls: ${survey.estimated_work?.draft_calls ?? survey.segments.length}`,
          `memory_searches: ${survey.estimated_work?.memory_searches ?? survey.segments.length}`,
          `stitch_calls: ${survey.estimated_work?.stitch_calls ?? (survey.segments.length > 1 ? 1 : 0)}`,
          ...(survey.readiness?.reasons ?? []).map((r) => `· ${r}`),
        ],
        persisted: 'DB 저장 없음 — 설문 결과는 expand-draft에 그대로 재사용',
      })
      if (needsQuestions) {
        setMemoQaSurvey(survey)
        setMemoQaOpen(true)
        return
      }
      surveyForExpand = { ...survey, questions: needsQuestions ? survey.questions : [] }
    } catch (e) {
      setToast(`설문 단계 생략: ${String(e)}`)
    } finally {
      setBusy(null)
    }
    void runExpandWithPayload(
      surveyForExpand
        ? {
            memo_survey: { segments: surveyForExpand.segments, questions: surveyForExpand.questions },
            logTitle: '자동 분할 후 AI 초안',
          }
        : {},
    )
  }

  const runMemoQaConfirm = async (result: MemoQaModalResult) => {
    try {
      await runExpandWithPayload({
        memo_survey: result.survey,
        memo_qa_answers: result.answers,
        logTitle: 'Q-A 보감 후 AI 초안',
      })
    } finally {
      setMemoQaOpen(false)
      setMemoQaSurvey(null)
    }
  }

  const runMemoQaSkip = async () => {
    try {
      await runExpandWithPayload(
        memoQaSurvey ? { memo_survey: { segments: memoQaSurvey.segments, questions: [] }, logTitle: 'Q-A 건너뛰고 AI 초안' } : {},
      )
    } finally {
      setMemoQaOpen(false)
      setMemoQaSurvey(null)
    }
  }

  const openScenePlan = () => {
    if (!selected) {
      setToast('챕터를 선택한 뒤 사용하세요.')
      return
    }
    if (!(raw || '').trim()) {
      setToast('작가 메모가 비어 있어 씬 플랜을 설계할 수 없습니다.')
      return
    }
    setScenePlanOpen(true)
  }

  const runScenePlan = async (res: ScenePlanModalResult) => {
    if (!selected) return
    setBusy('씬별 생성')
    try {
      const r = await api.agent.expand({
        episodeId: selected.id,
        raw_memory: raw || undefined,
        genre_override: story?.genre || undefined,
        use_scene_plan: true,
        scene_plan: res.scenes,
        regenerate_scene_ids: res.regenerateIds.length > 0 ? res.regenerateIds : undefined,
        style_axes: Object.keys(res.styleAxes).length ? res.styleAxes : undefined,
        memory_mode: 'auto',
      })
      const traceRaw = (r.context_used as { memory_trace?: unknown }).memory_trace
      const trace = Array.isArray(traceRaw)
        ? traceRaw.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object' && !Array.isArray(item))
        : []
      setMemoryTrace(trace)

      const scenes = r.scenes ?? []
      const plan = r.scene_plan ?? res.scenes
      // 이미 유지된 씬 본문을 pendingPlan 에서 머지(서버는 stateless).
      const existing = pendingPlan?.contents ?? {}
      const mergedContents: Record<string, string> = { ...existing }
      for (const sc of scenes) {
        if (sc.content && sc.content.trim()) mergedContents[sc.scene_id] = sc.content
      }
      setPendingPlan({ scenes: plan, contents: mergedContents })

      if (res.mode === 'split-into-blocks' && plan.length > 0) {
        const nextBodies: LocalBody[] = plan.map((s, i) => {
          const content = mergedContents[s.id] ?? ''
          return {
            title: '',
            content,
            body_summary: '',
            link_to_previous: i === 0 ? null : 'continuous',
            meta_tags: {
              scene_plan_id: s.id,
              beat: s.beat,
              pov: s.pov,
              tension: s.tension,
            },
          }
        })
        setBodies(nextBodies)
        setActiveBodyIdx(0)
      } else {
        // 현재 블록 교체 (통합 본문)
        setBodies((prev) => {
          const next = [...prev]
          const idx = Math.min(Math.max(activeBodyIdx, 0), next.length - 1)
          next[idx] = { ...next[idx], content: r.ai_content }
          return next
        })
      }

      setStyleAxes(res.styleAxes)
      saveStyleAxes(res.styleAxes)
      setScenePlanOpen(false)

      const regen = res.regenerateIds.length > 0 ? res.regenerateIds.join(', ') : '(전체)'
      pushFlowLog({
        title: '씬별 생성',
        route: 'POST /api/agent/expand-draft (use_scene_plan=true)',
        inputLines: [
          `episode_id: ${selected.id}`,
          `scenes: ${res.scenes.length}개`,
          `재생성 대상: ${regen}`,
          Object.keys(res.styleAxes).length ? `style_axes: ${JSON.stringify(res.styleAxes)}` : 'style_axes: (없음)',
        ],
        outputLines: [
          `ai_content(stitched): ${r.ai_content.length}자`,
          `자동 기억 검색: ${trace.length}회`,
          ...scenes.map((s) => `  · ${s.scene_id}: ${s.approx_chars}자`),
          `블록 모드: ${res.mode}`,
        ],
        persisted: 'DB: generation_runs에 memory_trace 저장 · 본문은 「저장」 시 episode_bodies(meta_tags.scene_plan_id) 반영',
      })
      setToast(`씬 ${scenes.length}개 생성 완료. 확인 후 저장하세요.`)
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
      await saveEpisode({ skipAutoBible: true, silent: true, flowLabel: '서버 동기화 (요약·인덱스 직전)' })
      const fin = await api.agent.finalize(selected.id)
      const combined = combineLocalBodies(bodies).trim()
      let bibleN: number | undefined
      if (autoSettingNoteOnSave && combined) {
        try {
          const br = await api.agent.bibleApply(selected.id)
          bibleN = br.applied
          await refresh()
          setToast(`요약·인덱스 완료 · 설정 노트 ${br.applied}건 반영${formatGraphFinalizeHint(fin.graph_sync)}`)
        } catch {
          await refresh()
          setToast(
            `요약·인덱스는 되었으나 설정 노트 자동 추출에 실패했습니다.${formatGraphFinalizeHint(fin.graph_sync)}`,
          )
        }
      } else {
        await refresh()
        setToast(`이 챕터 요약과 검색용 조각(청크)이 갱신되었습니다.${formatGraphFinalizeHint(fin.graph_sync)}`)
      }
      const routes = [
        `POST /api/agent/finalize-episode/${selected.id}`,
        ...(bibleN != null ? [`POST /api/agent/bible-apply/${selected.id}`] : []),
      ]
      pushFlowLog({
        title: '이 챕터 요약 · 검색 인덱스',
        route: routes.join('\n'),
        inputLines: ['(직전 단계에서 서버에 저장된 본문 기준)'],
        outputLines: [
          `요약 길이: ${(fin.summary || '').length}자`,
          `chapter_events: ${fin.chapter_events?.length ?? 0}건`,
          `블록 요약 갱신: ${fin.block_summaries_updated}개`,
          `청크 인덱싱: ${fin.chunks_indexed ? '예' : '아니오'}`,
          fin.memory_sync?.error
            ? `장편 기억: 실패 — ${String(fin.memory_sync.error).slice(0, 200)}`
            : `장편 기억: 사건 ${fin.memory_sync?.events ?? 0}개 · 엔티티 ${fin.memory_sync?.entities ?? 0}개 · 관계 ${
                fin.memory_sync?.relationships ?? 0
              }개`,
          fin.graph_sync?.error
            ? `그래프: 실패 — ${String(fin.graph_sync.error).slice(0, 200)}`
            : fin.graph_sync?.enabled === true ||
                (fin.graph_sync?.entities ?? 0) > 0 ||
                (fin.graph_sync?.relations ?? 0) > 0
              ? `그래프 동기화: 엔티티 ${fin.graph_sync?.entities ?? 0}개 · 관계 ${fin.graph_sync?.relations ?? 0}개`
              : '그래프 기능 OFF(GRAPH_ENABLED=false 등)',
          bibleN != null ? `설정 자동: ${bibleN}건` : '설정 자동: 생략 또는 실패',
        ],
        persisted:
          'DB: EpisodeBody 요약, episodes 요약·사건, episode_chunks, canonical memory, stories.work_summary · (옵션) Neo4j · (옵션) story_bible',
      })
    } catch (e) {
      setToast(String(e))
    } finally {
      setBusy(null)
    }
  }

  const runReviewEpisode = useCallback(async () => {
    if (!selected) {
      setToast('챕터를 선택한 뒤 사용하세요.')
      return
    }
    const combined = combineLocalBodies(bodies).trim()
    if (!combined) {
      setToast('본문이 비어 있습니다. 저장·생성 후 검수하세요.')
      return
    }
    setReviewOpen(true)
    setReviewLoading(true)
    setReviewErr(null)
    try {
      await saveEpisode({
        skipAutoBible: true,
        silent: true,
        flowLabel: '서버 동기화 (검수 직전)',
      })
      const r = await api.agent.reviewEpisode(selected.id, {
        top_k: 6,
        include_pov: true,
        include_critic: true,
      })
      setReview(r)
      setChapterMeta((r.meta_tags as EpisodeMetaTags) ?? {})
      pushFlowLog({
        title: '이 챕터 검수 (수동)',
        route: `POST /api/agent/review/episode/${selected.id}`,
        inputLines: [
          `본문 합본 ${combined.length}자`,
          `top_k=6 · include_pov=true · include_critic=true`,
        ],
        outputLines: [
          `이슈 ${r.issues.length}건 (우회 ${r.issues.filter((i) => i.bypassed).length}건)`,
          r.pov
            ? `POV: ${r.pov.pov} · 시제: ${r.pov.tense} · 신뢰도 ${(r.pov.confidence * 100).toFixed(0)}%`
            : 'POV: (미수행)',
          `Top-K: ${r.top_k_hits.length}개`,
          r.chapter_flow_note ? `흐름 메모: ${r.chapter_flow_note.slice(0, 80)}…` : '흐름 메모: (없음)',
        ],
        persisted: 'DB 저장 없음 — bypass/tag 는 저장 눌러야 반영',
      })
    } catch (e) {
      setReviewErr(String(e))
      setToast(`검수 실패: ${e}`)
    } finally {
      setReviewLoading(false)
    }
  }, [selected, bodies, pushFlowLog])

  const toggleIssueBypass = useCallback((issueId: string, nextBypassed: boolean) => {
    setReview((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        issues: prev.issues.map((it) =>
          it.id === issueId
            ? {
                ...it,
                bypassed: nextBypassed,
                bypass_reason: nextBypassed
                  ? it.bypass_reason ?? '사용자가 의도된 전환으로 표시'
                  : null,
              }
            : it,
        ),
      }
    })
  }, [])

  const saveChapterMeta = useCallback(
    async (nextMeta: EpisodeMetaTags) => {
      setChapterMeta(nextMeta)
      if (!selected) return
      try {
        const cleaned: EpisodeMetaTags = {}
        for (const [k, v] of Object.entries(nextMeta)) {
          if (v === undefined || v === null || v === false || v === '') continue
          cleaned[k] = v
        }
        const p = await api.episodes.patch(sid, selected.id, {
          meta_tags: Object.keys(cleaned).length ? cleaned : null,
        })
        setEpisodes((prev) => prev.map((e) => (e.id === p.id ? p : e)))
        pushFlowLog({
          title: '챕터 태그 저장 (meta_tags)',
          route: `PATCH /api/stories/${sid}/episodes/${selected.id}`,
          inputLines: [`meta_tags: ${JSON.stringify(cleaned)}`],
          outputLines: ['episodes.meta_tags 갱신'],
          persisted: 'DB: episodes.meta_tags',
        })
      } catch (e) {
        setToast(`챕터 태그 저장 실패: ${e}`)
      }
    },
    [selected, sid, pushFlowLog],
  )

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
      pushFlowLog({
        title: '설정 미리보기만',
        route: 'POST /api/agent/bible-extract',
        inputLines: [
          `episode_id: ${selected.id}`,
          `ai_content(로컬 합본): ${combined.length}자`,
        ],
        outputLines: [`entries: ${r.entries.length}건 (화면 미리보기)`],
        persisted: 'DB 저장 없음 — 「미리보기 확정 저장」 시 bible-commit',
      })
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
      pushFlowLog({
        title: '미리보기 확정 저장',
        route: `POST /api/agent/bible-commit/${selected.id}`,
        inputLines: [`entries: ${bibleDraft.length}건 (클라이언트가 보낸 JSON 그대로)`],
        outputLines: [`applied: ${r.applied}건`],
        persisted: 'DB: story_bible (+임베딩) — 그래프 동기화는 이 경로에서 생략',
      })
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
      pushFlowLog({
        title: '이어쓰기 도움',
        route: 'POST /api/agent/bridge',
        inputLines: [
          `summary_a: ${summaryA.length}자`,
          `raw_memory_b(메모): ${bridgeMemo.length}자`,
          `story_id: ${sid}`,
          `anchor_excerpt: ${(anchorExcerpt || '').length}자`,
        ],
        outputLines: [`suggestions: ${r.suggestions.length}자`],
        persisted: 'DB 저장 없음 — 우측 패널에만 표시',
      })
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
      setRagHits(rows)
      pushFlowLog({
        title: 'RAG 검색',
        route: 'POST /api/agent/rag-search',
        inputLines: [`story_id: ${sid}`, `query: ${ragQ.trim().length}자`],
        outputLines: [`히트: ${rows.length}건`],
        persisted: 'DB 읽기만 (episode_chunks, story_bible 등)',
      })
    } catch (e) {
      setToast(String(e))
    } finally {
      setBusy(null)
    }
  }

  /**
   * RAG 결과 클릭 시 해당 챕터·블록·단락 위치로 이동한다.
   * paragraph 는 빈 줄(`\n{2,}`) 기준으로 나눠 문자 offset 을 계산해 textarea 선택 범위로 강조한다.
   */
  const jumpToParagraph = (
    episodeId: string,
    segIdx: number | null | undefined,
    paraIdx: number | null | undefined,
  ) => {
    if (!episodeId) return
    setEpId(episodeId)
    if (typeof segIdx === 'number' && segIdx >= 0) {
      setActiveBodyIdx(segIdx)
    }
    // 챕터·블록 전환 후 DOM 반영을 기다린 뒤 단락 offset 계산.
    window.setTimeout(() => {
      try {
        const idx = typeof segIdx === 'number' && segIdx >= 0 ? segIdx : 0
        const area = document.querySelector<HTMLTextAreaElement>(
          `textarea[data-block-idx="${idx}"]`,
        )
        if (!area) return
        area.scrollIntoView({ behavior: 'smooth', block: 'center' })
        area.focus({ preventScroll: true })
        const text = area.value || ''
        if (typeof paraIdx !== 'number' || paraIdx < 0) return
        // split by blank-line boundaries while preserving start positions
        const boundaries: number[] = [0]
        const re = /\n{2,}/g
        let m: RegExpExecArray | null
        while ((m = re.exec(text)) !== null) {
          boundaries.push(m.index + m[0].length)
        }
        if (paraIdx >= boundaries.length) return
        const start = boundaries[paraIdx]
        const nextStart = paraIdx + 1 < boundaries.length ? boundaries[paraIdx + 1] : text.length
        const end = Math.max(start, Math.min(text.length, nextStart))
        try {
          area.setSelectionRange(start, end)
        } catch {
          /* noop */
        }
      } catch {
        /* noop */
      }
    }, 80)
  }

  const runConsistency = async () => {
    setBusy('맞춤 검토')
    try {
      const focus =
        consistencyScope === 'chapter' && selected ? selected.id : undefined
      const r = await api.agent.consistency(sid, focus ?? null)
      setConsistency(r.report)
      pushFlowLog({
        title: '맞춤 점검',
        route: 'POST /api/agent/consistency',
        inputLines: [
          `story_id: ${sid}`,
          `focus_episode_id: ${focus ?? '(없음 — 최근 여러 챕터 모드)'}`,
        ],
        outputLines: [`report: ${r.report.length}자`],
        persisted: 'DB 저장 없음',
      })
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
      pushFlowLog({
        title: '문체 변환',
        route: 'POST /api/agent/style-transfer',
        inputLines: [
          `text: ${cur.length}자 (활성 블록)`,
          `target_style: ${styleTarget}`,
        ],
        outputLines: [`text: ${r.text.length}자 → 에디터 반영`],
        persisted: 'DB 저장 없음 — 저장 시 episode_bodies',
      })
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
      pushFlowLog({
        title: '보내기(파일)',
        route: 'POST /api/agent/export',
        inputLines: [`story_id: ${sid}`, `format: ${format}`],
        outputLines: ['응답: 바이너리 파일(blob)'],
        persisted: '로컬 다운로드만 — DB 변경 없음',
      })
    } catch (e) {
      setToast(String(e))
    } finally {
      setBusy(null)
    }
  }

  const loadWriterContext = useCallback(async () => {
    if (!selected) {
      setToast('챕터를 선택하세요.')
      return
    }
    setBusy('컨텍스트')
    setContextPreviewErr(null)
    try {
      const ctx = await api.agent.contextPreview(sid, selected.chapter_num)
      setContextPreview(ctx)
      pushFlowLog({
        title: '집필 컨텍스트(API)',
        route: `GET /api/agent/context-preview/${sid}?chapter_num=${selected.chapter_num}`,
        inputLines: ['서버가 Story·Episodes·StoryBible을 읽어 조립한 값'],
        outputLines: [
          `synopsis: ${ctx.synopsis.length}자`,
          `bible_block: ${ctx.bible_block.length}자`,
          `graph_block: ${ctx.graph_block.length}자`,
          `prev_summary: ${ctx.prev_summary.length}자`,
          `sliding(합성 프롬프트용): ${ctx.sliding.combined_for_prompt.length}자`,
        ],
        persisted: 'DB 저장 없음 (읽기 전용 미리보기)',
      })
    } catch (e) {
      setContextPreview(null)
      setContextPreviewErr(String(e))
    } finally {
      setBusy(null)
    }
  }, [selected, sid, pushFlowLog])

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
        <div className="ws-topbar-title-wrap">
          <h1 title={story.title}>{story.title}</h1>
          {selected ? <span className="ws-pill">챕터 {selected.chapter_num}</span> : null}
          {story.genre ? <span className="ws-pill">{story.genre}</span> : null}
        </div>
        <span className="ws-auto-chip">자동 기억 사용 중</span>
        <button
          type="button"
          className="ghost"
          onClick={() => {
            setBibleDrawerOpen(true)
            setToolsOpen(false)
          }}
          aria-expanded={bibleDrawerOpen}
        >
          설정
        </button>
        <button type="button" className="ghost ws-tools-toggle" onClick={() => setToolsOpen((v) => !v)} aria-expanded={toolsOpen}>
          명령
        </button>
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

      <details className="ws-pin-card ws-context-dock">
        <summary>
          <span>작품 기억</span>
          <strong>{story?.world_setting?.trim() ? '배경 자동 참조 중' : '배경 미설정'}</strong>
        </summary>
        <div className="ws-pin-card-main" style={{ minWidth: 0, flex: 1 }}>
          <h3>세계관·배경</h3>
          <p>
            {story?.world_setting?.trim()
              ? story.world_setting.length > 360
                ? `${story.world_setting.slice(0, 360)}…`
                : story.world_setting
              : '(아직 저장된 세계관이 없습니다. 배경 진단으로 대전제·핵심 인물·규칙을 정리해 주세요.)'}
          </p>
          <div className="ws-pin-card-meta">
            {story?.global_rules && Object.keys(story.global_rules).length > 0 ? (
              <span>
                전역 규칙 키: {Object.keys(story.global_rules).slice(0, 6).join(' · ')}
              </span>
            ) : (
              <span>전역 규칙: (없음)</span>
            )}
          </div>
          <details style={{ marginTop: '0.5rem' }}>
            <summary style={{ cursor: 'pointer', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              편집
            </summary>
            <textarea
              className="ws-textarea-memo"
              style={{ minHeight: 100, marginTop: 8 }}
              value={worldDraft}
              onChange={(e) => setWorldDraft(e.target.value)}
              placeholder="인물 관계, 세계관 규칙, 핵심 갈등…"
            />
            <button
              type="button"
              className="ghost"
              style={{ marginTop: 8 }}
              disabled={!!busy}
              onClick={async () => {
                setBusy('배경 저장')
                try {
                  const u = await api.stories.patch(sid, {
                    world_setting: worldDraft.trim() || null,
                  })
                  setStory(u)
                  setToast('세계관·배경을 텍스트만 덮어썼습니다.')
                } catch (e) {
                  setToast(String(e))
                } finally {
                  setBusy(null)
                }
              }}
            >
              텍스트만 저장
            </button>
          </details>
        </div>
        <div className="ws-pin-card-actions">
          <button
            type="button"
            className="primary"
            disabled={!!busy}
            onClick={() => setIntakeOpen(true)}
          >
            배경 진단
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => setGraph3dOpen(true)}
            title="엔티티·관계를 3차원으로 탐색"
          >
            3D 지식 그래프
          </button>
        </div>
      </details>

      <div className="ws-layout">
        <div className="ws-main workspace-main" style={{ paddingBottom: '2rem' }}>
          {busy ? (
            <div className="ws-busy-strip" role="status" aria-live="polite" aria-busy="true">
              <span className="ws-busy-pulse" aria-hidden />
              <span>{busy}</span>
            </div>
          ) : null}
          <section className="ws-chapter-bar">
            <div className="ws-chapter-bar-head">
              <span>챕터</span>
              <button type="button" className="primary" onClick={newChapter} disabled={!!busy}>
                + 새 챕터
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
                  <div style={{ fontWeight: 650 }}>챕터 {e.chapter_num}</div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', maxHeight: 34, overflow: 'hidden' }}>
                    {e.summary || '요약 없음'}
                  </div>
                </button>
              ))}
            </div>
          </section>

          <div className="ws-editor-grid ws-studio-grid">
            <div className="ws-editor-panel ws-memo-panel">
              <div className="ws-panel-kicker">Source Notes</div>
              <h2>작가 메모</h2>
              <textarea
                className="ws-textarea-memo ws-memo-textarea"
                value={raw}
                onChange={(ev) => setRaw(ev.target.value)}
                placeholder="이번 챕터에 꼭 들어가야 하는 사건, 감정, 대사, 복선을 적어 주세요."
              />
            </div>
            <div className="ws-editor-panel ws-manuscript-panel">
              <div className="ws-manuscript-head">
                <div>
                  <div className="ws-panel-kicker">Manuscript</div>
                  <h2>원고</h2>
                </div>
                <div className="ws-manuscript-stats">
                  <span>{combineLocalBodies(bodies).trim().length.toLocaleString('ko-KR')}자</span>
                  <span>{bodies.length}블록</span>
                </div>
                <button
                  type="button"
                  className="ghost"
                  disabled={!!busy}
                  onClick={() =>
                    setBodies((p) => [
                      ...p,
                      {
                        title: '',
                        content: '',
                        body_summary: '',
                        link_to_previous: 'continuous',
                        meta_tags: null,
                      },
                    ])
                  }
                >
                  블록 추가
                </button>
              </div>
              <div className="ws-body-stack">
                {bodies.map((blk, i) => (
                  <article
                    key={i}
                    role="presentation"
                    className={`ws-body-block ws-manuscript-sheet${i === activeBodyIdx ? ' active' : ''}`}
                    onClick={() => setActiveBodyIdx(i)}
                  >
                    <div className="ws-block-topline">
                      <span>Block {i + 1}</span>
                      {i === activeBodyIdx && <span className="ws-editing-dot">편집 중</span>}
                      <span>{(blk.content || '').trim().length.toLocaleString('ko-KR')}자</span>
                    </div>
                    <div className="ws-block-mainbar">
                      <input
                        className="ws-block-title-input"
                        placeholder="소제목"
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
                      {bodies.length > 1 && (
                        <button
                          type="button"
                          className="ghost ws-block-delete"
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
                    <details className="ws-block-settings">
                      <summary>블록 설정</summary>
                      <div className="ws-block-settings-grid">
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
                      {i > 0 && (
                        <label
                          style={{ fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: 6 }}
                          title="브릿지·연속성 검사 시 의도적 단절로 처리"
                        >
                          <input
                            type="checkbox"
                            checked={!!blk.meta_tags?.allow_discontinuity}
                            onChange={(ev) => {
                              const checked = ev.target.checked
                              setBodies((prev) => {
                                const n = [...prev]
                                const mt = { ...(n[i].meta_tags || {}) }
                                if (checked) mt.allow_discontinuity = true
                                else delete mt.allow_discontinuity
                                n[i] = {
                                  ...n[i],
                                  meta_tags: Object.keys(mt).length ? mt : null,
                                }
                                return n
                              })
                            }}
                            onClick={(e) => e.stopPropagation()}
                          />
                          의도적 단절
                        </label>
                      )}
                      <label className="block-meta-tag" title="이 블록의 서술 시점">
                        <span>시점</span>
                        <select
                          value={(blk.meta_tags?.pov as string) ?? ''}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(ev) => {
                            const v = ev.target.value
                            setBodies((prev) => {
                              const n = [...prev]
                              const mt = { ...(n[i].meta_tags || {}) }
                              if (v) mt.pov = v
                              else delete mt.pov
                              n[i] = { ...n[i], meta_tags: Object.keys(mt).length ? mt : null }
                              return n
                            })
                          }}
                        >
                          <option value="">(자동)</option>
                          <option value="1st">1인칭</option>
                          <option value="3rd_limited">3인칭 한정</option>
                          <option value="3rd_omniscient">3인칭 전지</option>
                          <option value="2nd">2인칭</option>
                          <option value="mixed">혼합</option>
                        </select>
                      </label>
                      <label className="block-meta-tag" title="이 블록의 시제">
                        <span>시제</span>
                        <select
                          value={(blk.meta_tags?.tense as string) ?? ''}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(ev) => {
                            const v = ev.target.value
                            setBodies((prev) => {
                              const n = [...prev]
                              const mt = { ...(n[i].meta_tags || {}) }
                              if (v) mt.tense = v
                              else delete mt.tense
                              n[i] = { ...n[i], meta_tags: Object.keys(mt).length ? mt : null }
                              return n
                            })
                          }}
                        >
                          <option value="">(자동)</option>
                          <option value="past">과거</option>
                          <option value="present">현재</option>
                          <option value="mixed">혼합</option>
                        </select>
                      </label>
                      <label
                        className="block-meta-tag"
                        title="시간 도약(챕터 흐름 검사 자동 우회)"
                      >
                        <input
                          type="checkbox"
                          checked={!!blk.meta_tags?.time_jump}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(ev) => {
                            const checked = ev.target.checked
                            setBodies((prev) => {
                              const n = [...prev]
                              const mt = { ...(n[i].meta_tags || {}) }
                              if (checked) mt.time_jump = true
                              else delete mt.time_jump
                              n[i] = { ...n[i], meta_tags: Object.keys(mt).length ? mt : null }
                              return n
                            })
                          }}
                        />
                        <span>시간 도약</span>
                      </label>
                      </div>
                    </details>
                    <textarea
                      data-block-idx={i}
                      className="ws-manuscript-textarea"
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
                  </article>
                ))}
              </div>
            </div>
          </div>

          <div className="ws-action-bar ws-command-bar">
            <div className="ws-command-left">
              <button type="button" className="primary" disabled={!!busy} onClick={runExpand}>
                AI 초안 생성
              </button>
              <button type="button" disabled={!!busy} onClick={() => void saveEpisode()}>
                저장
              </button>
              <button
                type="button"
                className={reviewOpen ? 'primary' : ''}
                disabled={reviewLoading}
                onClick={() => void runReviewEpisode()}
                title="Critic + Top-K + 챕터 흐름 + 시점 감지"
              >
                검수
              </button>
            </div>
            <span className="ws-auto-status">RAG · 관계 · 사건은 자동 조회</span>
            <details className="ws-command-more">
              <summary>더 보기</summary>
              <div className="ws-command-popover">
                <button type="button" disabled={!!busy} onClick={newChapter}>
                  새 챕터 만들기
                </button>
                <button
                  type="button"
                  disabled={!!busy}
                  onClick={openScenePlan}
                  title="씬 단위로 쪼개 설계 → 부분 재생성 가능"
                >
                  씬 플랜
                </button>
                <button type="button" disabled={!!busy} onClick={runFinalize}>
                  요약 · 인덱스
                </button>
                <button type="button" disabled={!!busy} onClick={runBiblePreview}>
                  설정 미리보기
                </button>
                <button type="button" disabled={!!busy || !bibleDraft?.length} onClick={runBibleCommit}>
                  미리보기 저장
                </button>
                <label>
                  <input
                    type="checkbox"
                    checked={autoSettingNoteOnSave}
                    onChange={(e) => setAutoSettingNoteOnSave(e.target.checked)}
                  />
                  저장 시 설정 노트 갱신
                </label>
              </div>
            </details>
            {busy && (
              <span className="ws-busy-inline" title="다른 작업은 잠시 비활성">
                {busy}
              </span>
            )}
          </div>

          <section className="ws-data-flow" aria-label="API 및 저장 흐름">
            <button
              type="button"
              className="ws-data-flow-toggle"
              onClick={() => setFlowOpen((o) => !o)}
              aria-expanded={flowOpen}
            >
              <span>코드·데이터 흐름 (인풋 / 아웃풋 / 저장)</span>
              <span style={{ color: 'var(--text-muted)', fontWeight: 500 }}>{flowOpen ? '접기' : '펼치기'}</span>
            </button>
            {flowOpen && (
              <div className="ws-data-flow-body">
                <ol className="ws-data-flow-ol">
                  <li>
                    <strong>로드</strong> — <code style={{ fontSize: '0.68rem' }}>GET /stories/:id</code>,{' '}
                    <code style={{ fontSize: '0.68rem' }}>GET …/episodes</code>,{' '}
                    <code style={{ fontSize: '0.68rem' }}>GET …/bible</code> 로 화면 상태를 채웁니다.
                  </li>
                  <li>
                    <strong>저장</strong> — 본문은{' '}
                    <code style={{ fontSize: '0.68rem' }}>PUT …/episodes/:eid/bodies</code>, 메모는{' '}
                    <code style={{ fontSize: '0.68rem' }}>PATCH …/episodes/:eid</code> 로 DB에 들어갑니다. 토글이 켜져
                    있으면 이어서 <code style={{ fontSize: '0.68rem' }}>POST /agent/bible-apply/:eid</code> 로 설정
                    노트가 갱신됩니다.
                  </li>
                  <li>
                    <strong>AI 초안</strong> — <code style={{ fontSize: '0.68rem' }}>POST /agent/expand-draft</code>
                    가 집필 컨텍스트·메모를 넣고 초안 문자열만 돌려줍니다. DB에는 안 쓰이고, 저장 버튼을 눌러야
                    블록이 서버에 반영됩니다.
                  </li>
                  <li>
                    <strong>요약·인덱스</strong> — 먼저 저장과 동일하게 서버 본문을 맞춘 뒤{' '}
                    <code style={{ fontSize: '0.68rem' }}>POST /agent/finalize-episode/:eid</code> 로 블록 요약·챕터
                    요약·사건 JSON·RAG 청크·작품 요약 롤업이 갱신됩니다.
                  </li>
                </ol>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', alignItems: 'center' }}>
                  <button type="button" disabled={!!busy || !selected} onClick={() => void loadWriterContext()}>
                    집필 컨텍스트 실제 값 불러오기
                  </button>
                  <button
                    type="button"
                    className="ghost"
                    style={{ fontSize: '0.74rem' }}
                    disabled={flowLog.length === 0}
                    onClick={() => setFlowLog([])}
                  >
                    작업 로그 비우기
                  </button>
                </div>
                {contextPreviewErr && (
                  <p style={{ color: '#c98a8a', fontSize: '0.74rem', margin: '0.5rem 0 0' }}>{contextPreviewErr}</p>
                )}
                {contextPreview && (
                  <div className="ws-context-preview">
                    <p style={{ margin: '0.45rem 0 0', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                      아래는 <strong>AI 초안</strong>에 들어가는 것과 같은 종류의 컨텍스트입니다. 길면 접어 두었습니다.
                    </p>
                    {contextPreview.pin && (
                      <details open>
                        <summary>Global Context Pin (시스템 프롬프트 최상단)</summary>
                        <pre className="ws-flow-kv" style={{ whiteSpace: 'pre-wrap' }}>
                          {contextPreview.pin}
                        </pre>
                      </details>
                    )}
                    <details>
                      <summary>시놉시스 · 장르 · 문체 지침 · 배경</summary>
                      <pre className="ws-flow-kv">
                        {JSON.stringify(
                          {
                            genre: contextPreview.genre,
                            language: contextPreview.language,
                            synopsis: contextPreview.synopsis,
                            world_setting: contextPreview.world_setting,
                            global_rules: contextPreview.global_rules,
                            style_guide: contextPreview.style_guide,
                          },
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                    <details>
                      <summary>설정 노트 블록 (bible_block)</summary>
                      <pre className="ws-flow-kv">
                        {(contextPreview.bible_block || '(비어 있음)').slice(0, 4000)}
                        {(contextPreview.bible_block || '').length > 4000 ? '\n… (생략)' : ''}
                      </pre>
                    </details>
                    <details>
                      <summary>그래프 요약 (graph_block)</summary>
                      <pre className="ws-flow-kv">
                        {(contextPreview.graph_block || '(비활성 또는 비어 있음)').slice(0, 4000)}
                        {(contextPreview.graph_block || '').length > 4000 ? '\n… (생략)' : ''}
                      </pre>
                    </details>
                    <details>
                      <summary>직전 챕터 요약 (prev_summary)</summary>
                      <pre className="ws-flow-kv">{contextPreview.prev_summary || '(없음)'}</pre>
                    </details>
                    <details>
                      <summary>슬라이딩 윈도 (이전 챕터들 텍스트·요약)</summary>
                      <pre className="ws-flow-kv">
                        {(contextPreview.sliding?.combined_for_prompt || '').slice(0, 6000)}
                        {(contextPreview.sliding?.combined_for_prompt || '').length > 6000 ? '\n… (생략)' : ''}
                      </pre>
                    </details>
                  </div>
                )}
                {memoryTrace?.length ? (
                  <details className="ws-context-preview" open>
                    <summary>자동 사용된 기억 (memory_trace)</summary>
                    <pre className="ws-flow-kv">
                      {JSON.stringify(memoryTrace, null, 2).slice(0, 8000)}
                      {JSON.stringify(memoryTrace, null, 2).length > 8000 ? '\n… (생략)' : ''}
                    </pre>
                  </details>
                ) : null}
                <h3 style={{ margin: '0.75rem 0 0.35rem', fontSize: '0.82rem', color: 'var(--accent)' }}>
                  최근 작업 로그
                </h3>
                {flowLog.length === 0 ? (
                  <p style={{ margin: 0, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                    저장·AI 초안·요약·도구를 실행하면 여기에 요청 경로, 넣은 값의 크기, 나온 결과, DB 반영 여부가
                    쌓입니다.
                  </p>
                ) : (
                  <ul className="ws-flow-log">
                    {flowLog.map((row) => (
                      <li key={row.id}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem' }}>
                          <strong style={{ fontSize: '0.78rem' }}>{row.title}</strong>
                          <time>{row.at}</time>
                        </div>
                        <div className="route">{row.route}</div>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                          <span style={{ color: 'var(--accent)' }}>인풋</span>
                          <pre className="ws-flow-kv" style={{ marginTop: 4 }}>
                            {row.inputLines.join('\n')}
                          </pre>
                          <span style={{ color: 'var(--accent)' }}>아웃풋</span>
                          <pre className="ws-flow-kv" style={{ marginTop: 4 }}>
                            {row.outputLines.join('\n')}
                          </pre>
                          {row.persisted ? (
                            <>
                              <span style={{ color: 'var(--accent)' }}>저장·반영</span>
                              <pre className="ws-flow-kv" style={{ marginTop: 4 }}>
                                {row.persisted}
                              </pre>
                            </>
                          ) : null}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </section>

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
              직전 챕터 요약과 방금까지 쓴 끝부분을 바탕으로, 지금 메모와 자연스럽게 잇는 장면 아이디어를 받습니다.
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
              설정 노트와 본문이 어긋난 곳이 있는지 봅니다. 지금 편집 중인 챕터만 보면 헛갈림이 줄어듭니다.
            </p>
            <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
              <label style={{ fontSize: '0.78rem', display: 'flex', alignItems: 'center', gap: 6 }}>
                <input
                  type="radio"
                  name="cscope"
                  checked={consistencyScope === 'chapter'}
                  onChange={() => setConsistencyScope('chapter')}
                />
                지금 이 챕터만
              </label>
              <label style={{ fontSize: '0.78rem', display: 'flex', alignItems: 'center', gap: 6 }}>
                <input
                  type="radio"
                  name="cscope"
                  checked={consistencyScope === 'story'}
                  onChange={() => setConsistencyScope('story')}
                />
                최근 여러 챕터
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
            {ragHits && ragHits.length > 0 && (
              <>
                <div
                  className="rag-heatmap"
                  role="group"
                  aria-label="검색 결과 히트맵 — 진할수록 유사도가 높습니다"
                >
                  {ragHits.map((r, idx) => {
                    const bucket = Math.max(1, Math.min(5, r.heatmap_bucket ?? 1))
                    const color = r.color_tag || '#64748b'
                    const scoreText =
                      r.score != null ? `${(r.score * 100).toFixed(1)}%` : '키워드·유사도'
                    const headLabel =
                      r.source_type === 'bible'
                        ? '[설정 노트]'
                        : r.source_type === 'summary'
                          ? `[요약 트리] ${r.summary_level ?? ''}`
                        : `챕터 ${r.chapter_num}`
                    const short = (r.snippet || '').replace(/\s+/g, ' ').slice(0, 80)
                    return (
                      <button
                        type="button"
                        key={`hm-${r.chunk_id ?? r.bible_entry_id ?? r.summary_node_id ?? idx}`}
                        className={`rag-heatmap-cell rag-heatmap-bucket-${bucket}`}
                        style={{ background: color }}
                        title={`${headLabel}${r.parent_event_title ? ` · ${r.parent_event_title}` : ''}\n관련도 ${scoreText}\n${short}…`}
                        onClick={() => {
                          if (r.source_type === 'episode' && r.episode_id) {
                            jumpToParagraph(r.episode_id, r.segment_index, r.paragraph_index)
                          }
                        }}
                        aria-label={`${headLabel} 결과 · 관련도 ${scoreText}`}
                      >
                        <span>{bucket}</span>
                      </button>
                    )
                  })}
                </div>
                <ul className="rag-hit-list">
                  {ragHits.map((r, idx) => {
                    const head =
                      r.source_type === 'bible'
                        ? '[설정 노트]'
                        : r.source_type === 'summary'
                          ? `[요약 트리] ${r.summary_level ?? r.summary_node_key ?? ''}`
                        : `챕터 ${r.chapter_num}`
                    const score =
                      r.score != null ? `${(r.score * 100).toFixed(1)}%` : '키워드·유사도'
                    const border = r.color_tag || '#64748b'
                    const bucket = Math.max(1, Math.min(5, r.heatmap_bucket ?? 1))
                    return (
                      <li
                        key={`${r.chunk_id ?? r.bible_entry_id ?? r.summary_node_id ?? idx}`}
                        className={`rag-hit-item rag-heatmap-bucket-${bucket}`}
                        style={{ borderLeftColor: border }}
                      >
                        <div className="rag-hit-head">
                          <span>{head}</span>
                          {r.category && <span> · {r.category}</span>}
                          {r.summary_node_key && <span> · {r.summary_node_key}</span>}
                          {r.parent_event_title && (
                            <span className="rag-hit-event"> · 사건: {r.parent_event_title}</span>
                          )}
                          <span className="rag-hit-score">관련도 {score}</span>
                        </div>
                        <div className="rag-hit-snippet">{r.snippet}</div>
                        {r.source_type === 'episode' && r.episode_id && (
                          <button
                            type="button"
                            className="ghost rag-hit-jump"
                            onClick={() =>
                              jumpToParagraph(
                                r.episode_id!,
                                r.segment_index,
                                r.paragraph_index,
                              )
                            }
                          >
                            이 단락으로 이동
                          </button>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </>
            )}
            {ragHits && ragHits.length === 0 && (
              <p style={{ marginTop: 10, fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                결과가 없습니다. 다른 단어로 시도해 보세요.
              </p>
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

      {scenePlanOpen && selected && (
        <ScenePlanModal
          episodeId={selected.id}
          rawMemory={raw || ''}
          initialStyleAxes={styleAxes}
          initialScenes={pendingPlan?.scenes}
          existingSceneContents={pendingPlan?.contents}
          onClose={() => setScenePlanOpen(false)}
          onRun={runScenePlan}
        />
      )}

      {memoQaOpen && memoQaSurvey && (
        <MemoQaModal
          survey={memoQaSurvey}
          onClose={() => {
            setMemoQaOpen(false)
            setMemoQaSurvey(null)
          }}
          onRun={runMemoQaConfirm}
          onSkip={() => void runMemoQaSkip()}
        />
      )}

      {reviewOpen && selected && (
        <ReviewPanel
          review={review}
          loading={reviewLoading}
          error={reviewErr}
          metaTags={chapterMeta}
          onClose={() => setReviewOpen(false)}
          onRerun={() => void runReviewEpisode()}
          onToggleBypass={toggleIssueBypass}
          onMetaChange={(next) => void saveChapterMeta(next)}
          onJumpToChapter={(_episodeId, chapterNum) => {
            const target = episodes.find((e) => e.chapter_num === chapterNum)
            if (target) setEpId(target.id)
          }}
        />
      )}

      {graph3dOpen && <GraphView3D storyId={sid} onClose={() => setGraph3dOpen(false)} />}

      {intakeOpen && story && (
        <IntakeModal
          mode="edit"
          storyId={sid}
          initialStoryInput={story.world_setting || story.title || ''}
          genre={story.genre || ''}
          language={story.language || 'KO'}
          onClose={() => setIntakeOpen(false)}
          onFinalized={async (r) => {
            setIntakeOpen(false)
            const entities = Number(r.foundation_sync?.entities ?? 0)
            const summaries = Number(r.foundation_sync?.summary_nodes ?? 0)
            setToast(
              `배경 진단 완료 — 설정 ${r.applied_bible}건 · 기억 ${entities}건 · 요약트리 ${summaries}건`,
            )
            try {
              const u = await api.stories.get(sid)
              setStory(u)
              setWorldDraft(u.world_setting ?? '')
              setContextPreview(null)
            } catch {
              /* 무시 */
            }
          }}
        />
      )}
    </div>
  )
}
