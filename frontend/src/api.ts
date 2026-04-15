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
  style_guide: string | null
  language: string
  created_at: string
}

export type BodySegmentLink = 'continuous' | 'omnibus'

export type EpisodeBody = {
  id: string
  segment_index: number
  title: string | null
  content: string
  link_to_previous: BodySegmentLink | null
}

export type EpisodeBodyItem = {
  title?: string | null
  content: string
  link_to_previous?: BodySegmentLink | null
}

export type Episode = {
  id: string
  story_id: string
  chapter_num: number
  raw_memory: string | null
  ai_content: string | null
  summary: string | null
  status: string
  bodies: EpisodeBody[]
}

export type RAGSearchHit = {
  source_type: string
  chunk_id?: string | null
  bible_entry_id?: string | null
  episode_id?: string | null
  chapter_num: number
  snippet: string
  score: number | null
}

export type BibleEntry = {
  id: string
  story_id: string
  category: string
  name: string
  description: string | null
  metadata?: Record<string, unknown> | null
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
    expand: (episodeId: string, raw_memory?: string, genre_override?: string) =>
      req<{ ai_content: string; context_used: Record<string, unknown> }>(
        '/agent/expand-draft',
        {
          method: 'POST',
          body: JSON.stringify({ episode_id: episodeId, raw_memory, genre_override }),
        },
      ),
    finalize: (episodeId: string) =>
      req<{ summary: string }>(`/agent/finalize-episode/${episodeId}`, { method: 'POST' }),
    bibleExtract: (episodeId: string, ai_content: string) =>
      req<{ entries: Record<string, unknown>[] }>('/agent/bible-extract', {
        method: 'POST',
        body: JSON.stringify({ episode_id: episodeId, ai_content }),
      }),
    /** DB 저장된 본문으로 LLM 추출 후 저장 (미리보기 없이 한 번에). */
    bibleApply: (episodeId: string) =>
      req<{ applied: number }>(`/agent/bible-apply/${episodeId}`, { method: 'POST' }),
    /** 미리보기(extract) 결과를 그대로 저장. LLM 재호출 없음. */
    bibleCommit: (episodeId: string, entries: Record<string, unknown>[]) =>
      req<{ applied: number }>(`/agent/bible-commit/${episodeId}`, {
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
    consistency: (storyId: string, focus_episode_id?: string | null) =>
      req<{ report: string }>('/agent/consistency', {
        method: 'POST',
        body: JSON.stringify({
          story_id: storyId,
          focus_episode_id: focus_episode_id || undefined,
        }),
      }),
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
