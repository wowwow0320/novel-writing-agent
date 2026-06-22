const base = '/api'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  })
  if (!r.ok) {
    const t = await r.text()
    try {
      const j = JSON.parse(t) as { detail?: string | Array<{ msg?: string }> }
      if (j?.detail != null) {
        const d = j.detail
        const msg =
          typeof d === 'string'
            ? d
            : Array.isArray(d)
              ? d
                  .map((x) =>
                    typeof x === 'object' && x && 'msg' in x ? String(x.msg) : JSON.stringify(x),
                  )
                  .join('; ')
              : t
        throw new Error(msg || r.statusText)
      }
    } catch (e) {
      if (e instanceof Error && e.name !== 'SyntaxError') throw e
    }
    throw new Error(t || r.statusText)
  }
  if (r.status === 204) return undefined as T
  const ct = r.headers.get('content-type')
  if (ct?.includes('application/json')) return r.json() as Promise<T>
  return (await r.text()) as T
}

export type Story = {
  id: string
  title: string
  genre: string
  synopsis: string | null
  world_setting?: string | null
  global_rules?: Record<string, unknown> | null
  style_guide: string | null
  language: string
  work_summary?: string | null
  created_at: string
}

export type BodySegmentLink = 'continuous' | 'omnibus'

export type EpisodeBody = {
  id: string
  segment_index: number
  title: string | null
  content: string
  body_summary?: string | null
  link_to_previous: BodySegmentLink | null
  parent_id?: string | null
  meta_tags?: Record<string, unknown> | null
}

export type EpisodeBodyItem = {
  title?: string | null
  content: string
  body_summary?: string | null
  link_to_previous?: BodySegmentLink | null
  meta_tags?: Record<string, unknown> | null
}

export type Episode = {
  id: string
  story_id: string
  chapter_num: number
  raw_memory: string | null
  ai_content: string | null
  summary: string | null
  chapter_events?: Record<string, unknown>[] | null
  status: string
  meta_tags?: EpisodeMetaTags | null
  bodies: EpisodeBody[]
}

export type POVKind = '1st' | '3rd_limited' | '3rd_omniscient' | '2nd' | 'mixed' | 'unknown'
export type TenseKind = 'past' | 'present' | 'mixed' | 'unknown'

export type EpisodeMetaTags = {
  pov?: POVKind
  tense?: TenseKind
  omnibus?: boolean
  time_jump?: boolean
  allow_discontinuity?: boolean
  [key: string]: unknown
}

export type ReviewSeverity = 'info' | 'warn' | 'error'
export type ReviewCategory =
  | 'continuity'
  | 'pov'
  | 'logic'
  | 'bible'
  | 'chapter_flow'
  | 'style'

export type ReviewIssue = {
  id: string
  severity: ReviewSeverity
  category: ReviewCategory
  message: string
  suggestion?: string | null
  evidence?: string | null
  block_id?: string | null
  bypassed?: boolean
  bypass_reason?: string | null
}

export type POVDetection = {
  pov: POVKind
  tense: TenseKind
  confidence: number
  rationale: string
}

export type EpisodeReview = {
  episode_id: string
  issues: ReviewIssue[]
  pov?: POVDetection | null
  logic: Record<string, unknown>
  top_k_hits: Record<string, unknown>[]
  chapter_flow_note?: string | null
  allowed_bypasses: string[]
  meta_tags: EpisodeMetaTags
}

export type RAGSearchHit = {
  source_type: string
  chunk_id?: string | null
  bible_entry_id?: string | null
  summary_node_id?: string | null
  summary_node_key?: string | null
  summary_level?: string | null
  episode_id?: string | null
  chapter_num: number
  snippet: string
  score: number | null
  category?: string | null
  color_tag?: string | null
  segment_index?: number | null
  paragraph_index?: number | null
  heatmap_bucket?: number
  parent_event_id?: string | null
  parent_event_title?: string | null
}

export type EventMapChunkRef = {
  chunk_id: string
  segment_index?: number | null
  paragraph_index?: number | null
  snippet: string
  category?: string | null
  color_tag?: string | null
}

export type EventMapEntry = {
  event_id: string
  title: string
  cause?: string
  outcome?: string
  turning_point?: string
  stakes?: string
  ref_count: number
  refs: EventMapChunkRef[]
}

export type EventMap = {
  episode_id: string
  chapter_num: number
  events: EventMapEntry[]
  orphan_chunks: EventMapChunkRef[]
}

export type GraphNodeType =
  | 'CHAR'
  | 'LOC'
  | 'EVENT'
  | 'ITEM'
  | 'ORG'
  | 'SITUATION'
  | 'SUMMARY'
  | 'UNKNOWN'

export type GraphNode = {
  id: string
  node_type: GraphNodeType | string
  importance: number
  status: string
  origin_hint?: string
  degree?: number
}

export type GraphLink = {
  source: string | GraphNode
  target: string | GraphNode
  relation: string
  context?: string
  confidence?: number | null
  relationship_id?: string | null
}

export type GraphSubgraphResponse = {
  nodes: GraphNode[]
  links: GraphLink[]
  depth: number
  ontology?: {
    node_types: string[]
    relation_types: string[]
  } | null
  /** 없으면 neo4j 로 간주(구버전 API). disabled 는 GRAPH_ENABLED=false */
  graph_source?: 'disabled' | 'neo4j'
}

export type BibleEntry = {
  id: string
  story_id: string
  category: string
  name: string
  description: string | null
  metadata?: Record<string, unknown> | null
}

export type IntakeAnswerEntry = { q: string; a: string; ts?: string }

export type IntakeState = {
  story_input: string
  extracted: Record<string, unknown>
  question_check: Record<string, unknown>
  answers: IntakeAnswerEntry[]
  iteration: number
}

export type IntakeResponse = {
  state: IntakeState
  missing: string[]
  suggested_questions: string[]
}

export type IntakeFinalizeResponse = {
  applied_bible: number
  story: Story
  world_setting_chars: number
  foundation_sync?: Record<string, unknown> | null
}

export type ScenePlanItem = {
  id: string
  beat: string
  pov: string
  goal: string
  tension: string
  hint: string
  approx_chars: number
}

export type ExpandedScene = {
  scene_id: string
  content: string
  approx_chars: number
  label?: string | null
  order?: number | null
}

export type StyleAxes = {
  length?: 'short' | 'mid' | 'long'
  register?: 'colloquial' | 'literary'
  rhythm?: 'staccato' | 'flowing'
}

export type MemoSegmentItem = {
  id: string
  order: number
  label: string
  writer_memo: string
}

export type MemoQaQuestionItem = {
  id: string
  segment_id?: string | null
  question: string
  options: string[]
  freeform_hint?: string | null
}

export type MemoQaAnswerItem = {
  selected_index: number
  freeform: string
}

export type MemoSurveySnapshot = {
  segments: MemoSegmentItem[]
  questions: MemoQaQuestionItem[]
}

export type MemoReadiness = {
  score: number
  needs_questions: boolean
  reasons: string[]
}

export type MemoEstimatedWork = {
  segments: number
  draft_calls: number
  memory_searches: number
  stitch_calls: number
}

export type MemoQaSurveyResponse = {
  decision: Record<string, unknown>
  segments: MemoSegmentItem[]
  questions: MemoQaQuestionItem[]
  readiness: MemoReadiness
  estimated_work: MemoEstimatedWork
}

export type ExpandParams = {
  episodeId: string
  raw_memory?: string
  genre_override?: string
  multi_step?: boolean | null
  use_scene_plan?: boolean
  scene_plan?: ScenePlanItem[]
  regenerate_scene_ids?: string[]
  style_axes?: StyleAxes
  memory_mode?: 'auto' | 'off'
  memo_survey?: MemoSurveySnapshot
  memo_qa_answers?: Record<string, MemoQaAnswerItem>
}

export type ExpandResponse = {
  ai_content: string
  context_used: Record<string, unknown>
  scenes?: ExpandedScene[]
  scene_plan?: ScenePlanItem[]
}

export type MemoryPreviewResponse = {
  bundle: Record<string, unknown>
  prompt_block: string
}

export const api = {
  health: () => req<{ status: string }>('/health'),
  stories: {
    list: () => req<Story[]>('/stories'),
    get: (id: string) => req<Story>(`/stories/${id}`),
    create: (body: Partial<Story> & { title: string }) =>
      req<Story>('/stories', { method: 'POST', body: JSON.stringify(body) }),
    patch: (id: string, body: Partial<Story>) =>
      req<Story>(`/stories/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  },
  episodes: {
    list: (storyId: string) => req<Episode[]>(`/stories/${storyId}/episodes`),
    create: (storyId: string, body: { chapter_num: number; raw_memory?: string }) =>
      req<Episode>(`/stories/${storyId}/episodes`, {
        method: 'POST',
        body: JSON.stringify({ ...body, status: 'draft' }),
      }),
    patch: (storyId: string, epId: string, body: Partial<Episode>) =>
      req<Episode>(`/stories/${storyId}/episodes/${epId}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),
    /** 챕터 본문 블록 전체 교체(순서 = 배열 순서). 첫 블록의 link_to_previous는 서버에서 무시됨. */
    replaceBodies: (storyId: string, epId: string, bodies: EpisodeBodyItem[]) =>
      req<Episode>(`/stories/${storyId}/episodes/${epId}/bodies`, {
        method: 'PUT',
        body: JSON.stringify({ bodies }),
      }),
  },
  bible: {
    list: (storyId: string) => req<BibleEntry[]>(`/stories/${storyId}/bible`),
  },
  agent: {
    /** 집필 프롬프트에 쓰이는 컨텍스트(시놉·바이블·슬라이딩 윈도 등). DB 쓰기 없음. */
    contextPreview: (storyId: string, chapterNum: number) =>
      req<{
        title?: string
        synopsis: string
        world_setting?: string
        global_rules?: Record<string, unknown> | null
        genre: string
        style_guide: string
        language: string
        bible_block: string
        graph_block: string
        prev_summary: string
        pin?: string
        sliding: { older_summaries: string; recent_full: string; combined_for_prompt: string }
      }>(
        `/agent/context-preview/${storyId}?${new URLSearchParams({
          chapter_num: String(chapterNum),
        })}`,
      ),
    intakeStart: (body: { story_input: string; genre?: string; language?: string }) =>
      req<IntakeResponse>('/agent/intake/start', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    intakeAnswer: (state: IntakeState, q: string, a: string) =>
      req<IntakeResponse>('/agent/intake/answer', {
        method: 'POST',
        body: JSON.stringify({ state, q, a }),
      }),
    intakeFinalize: (state: IntakeState, storyId: string, mergeGlobalRules = true) =>
      req<IntakeFinalizeResponse>('/agent/intake/finalize', {
        method: 'POST',
        body: JSON.stringify({
          state,
          story_id: storyId,
          merge_global_rules: mergeGlobalRules,
        }),
      }),
    expand: (params: ExpandParams) =>
      req<ExpandResponse>('/agent/expand-draft', {
        method: 'POST',
        body: JSON.stringify({
          episode_id: params.episodeId,
          raw_memory: params.raw_memory,
          genre_override: params.genre_override,
          multi_step: params.multi_step ?? undefined,
          use_scene_plan: params.use_scene_plan ?? undefined,
          scene_plan: params.scene_plan ?? undefined,
          regenerate_scene_ids: params.regenerate_scene_ids ?? undefined,
          style_axes: params.style_axes ?? undefined,
          memory_mode: params.memory_mode ?? 'auto',
          memo_survey: params.memo_survey ?? undefined,
          memo_qa_answers: params.memo_qa_answers ?? undefined,
        }),
      }),
    memoryPreview: (body: {
      episode_id: string
      segment_memo: string
      previous_text?: string
      scene_hint?: string
      chapter_state?: Record<string, unknown>
      limit?: number
    }) =>
      req<MemoryPreviewResponse>('/agent/memory-preview', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    memoQaSurvey: (p: { episodeId: string; raw_memory?: string; style_axes?: StyleAxes }) =>
      req<MemoQaSurveyResponse>('/agent/memo-qa-survey', {
        method: 'POST',
        body: JSON.stringify({
          episode_id: p.episodeId,
          raw_memory: p.raw_memory,
          style_axes: p.style_axes ?? undefined,
        }),
      }),
    planScenes: (body: {
      episode_id: string
      raw_memory?: string
      max_scenes?: number
      style_axes?: StyleAxes
    }) =>
      req<{ scenes: ScenePlanItem[]; decision: Record<string, unknown> }>(
        '/agent/plan-scenes',
        { method: 'POST', body: JSON.stringify(body) },
      ),
    reviewEpisode: (
      episodeId: string,
      opts: {
        top_k?: number
        allow_discontinuity?: boolean | null
        include_pov?: boolean
        include_critic?: boolean
      } = {},
    ) =>
      req<EpisodeReview>(`/agent/review/episode/${episodeId}`, {
        method: 'POST',
        body: JSON.stringify({
          episode_id: episodeId,
          top_k: opts.top_k ?? 6,
          allow_discontinuity: opts.allow_discontinuity ?? null,
          include_pov: opts.include_pov ?? true,
          include_critic: opts.include_critic ?? true,
        }),
      }),
    bridgeVerify: (body: {
      story_id: string
      previous_text: string
      current_text: string
      episode_id?: string | null
      chapter_summary?: string | null
      chapter_events_json?: string | null
      allow_discontinuity?: boolean
      top_k?: number
    }) =>
      req<{
        logic: Record<string, unknown>
        top_k_hits: Record<string, unknown>[]
        chapter_flow_note: string | null
      }>('/agent/harness/bridge-verify', { method: 'POST', body: JSON.stringify(body) }),
    semanticRoute: (message: string) =>
      req<{ intent: string; confidence: number; rationale: string }>(
        '/agent/harness/semantic-route',
        { method: 'POST', body: JSON.stringify({ message }) },
      ),
    finalize: (episodeId: string) =>
      req<{
        summary: string | null
        chapter_events: Record<string, unknown>[] | null
        chunks_indexed: boolean
        block_summaries_updated: number
        summary_tree_sync?: {
          nodes?: number
          stale_cleared?: number
          embedded?: number
          error?: string
        }
        memory_sync?: {
          events?: number
          entities?: number
          relationships?: number
          error?: string
        }
        graph_sync?: {
          enabled?: boolean
          entities?: number
          relations?: number
          summaries?: number
          error?: string
        }
      }>(`/agent/finalize-episode/${episodeId}`, { method: 'POST' }),
    bibleExtract: (episodeId: string, ai_content: string) =>
      req<{ entries: Record<string, unknown>[] }>('/agent/bible-extract', {
        method: 'POST',
        body: JSON.stringify({ episode_id: episodeId, ai_content }),
      }),
    /** DB 저장된 본문으로 LLM 추출 후 저장 (미리보기 없이 한 번에). */
    bibleApply: (episodeId: string) =>
      req<{
        applied: number
        memory_entities?: number
        graph_sync?: { enabled?: boolean; entities?: number; relations?: number; error?: string }
      }>(`/agent/bible-apply/${episodeId}`, { method: 'POST' }),
    /** 미리보기(extract) 결과를 그대로 저장. LLM 재호출 없음. */
    bibleCommit: (episodeId: string, entries: Record<string, unknown>[]) =>
      req<{
        applied: number
        memory_entities?: number
        graph_sync?: { enabled?: boolean; entities?: number; relations?: number; error?: string }
      }>(`/agent/bible-commit/${episodeId}`, {
        method: 'POST',
        body: JSON.stringify({ entries }),
      }),
    bridge: (
      summary_a: string,
      raw_memory_b: string,
      story_id?: string,
      anchor_excerpt?: string | null,
    ) =>
      req<{ suggestions: string }>('/agent/bridge', {
        method: 'POST',
        body: JSON.stringify({
          summary_a,
          raw_memory_b,
          story_id,
          anchor_excerpt: anchor_excerpt?.trim() || undefined,
        }),
      }),
    rag: (storyId: string, query: string) =>
      req<RAGSearchHit[]>('/agent/rag-search', {
        method: 'POST',
        body: JSON.stringify({ story_id: storyId, query, limit: 8 }),
      }),
    eventMap: (episodeId: string) =>
      req<EventMap>(`/agent/event-map/${episodeId}`),
    consistency: (storyId: string, focus_episode_id?: string | null) =>
      req<{ report: string }>('/agent/consistency', {
        method: 'POST',
        body: JSON.stringify({
          story_id: storyId,
          focus_episode_id: focus_episode_id || undefined,
        }),
      }),
    graphOntology: () =>
      req<{ node_types: string[]; relation_types: string[] }>('/agent/graph/ontology'),
    graphSubgraph: (
      storyId: string,
      opts: {
        center?: string
        depth?: number
        limit?: number
        node_types?: string[]
      } = {},
    ) => {
      const params: Record<string, string> = {
        depth: String(opts.depth ?? 2),
        limit: String(opts.limit ?? 120),
      }
      if (opts.center) params.center = opts.center
      if (opts.node_types && opts.node_types.length) {
        params.node_types = opts.node_types.join(',')
      }
      return req<GraphSubgraphResponse>(
        `/agent/graph/subgraph/${storyId}?${new URLSearchParams(params).toString()}`,
      )
    },
    graphSyncEpisode: (episodeId: string) =>
      req<{ enabled: boolean; entities: number; relations: number }>(
        `/agent/graph-sync/${episodeId}`,
        { method: 'POST' },
      ),
    graphSyncCheck: (storyId: string) =>
      req<{
        postgres: { bible_entries: number; episodes: number }
        graph: { nodes: number; edges: number }
        balanced_hint: boolean
      }>(`/agent/graph/sync-check/${storyId}`),
    style: (text: string, target_style: string) =>
      req<{ text: string }>('/agent/style-transfer', {
        method: 'POST',
        body: JSON.stringify({ text, target_style }),
      }),
    export: async (storyId: string, format: 'txt' | 'pdf' | 'epub') => {
      const r = await fetch(`${base}/agent/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ story_id: storyId, format }),
      })
      if (!r.ok) throw new Error(await r.text())
      return r.blob()
    },
  },
}
