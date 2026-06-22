import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Story } from '../api'
import { buildGenrePath, GENRE_TAXONOMY } from '../genreTaxonomy'
import { IntakeModal } from '../components/IntakeModal'

export function Dashboard() {
  const [stories, setStories] = useState<Story[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [worldSetting, setWorldSetting] = useState('')
  const [majorId, setMajorId] = useState('')
  const [midId, setMidId] = useState('')
  const [leaf, setLeaf] = useState('')
  const [intake, setIntake] = useState<{
    storyId: string
    storyInput: string
    genre: string
    language: string
  } | null>(null)
  const [infoMsg, setInfoMsg] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const major = useMemo(
    () => GENRE_TAXONOMY.find((m) => m.id === majorId),
    [majorId],
  )
  const mid = useMemo(
    () => major?.mids.find((x) => x.id === midId),
    [major, midId],
  )

  const genre = useMemo(
    () => buildGenrePath(majorId, midId, leaf),
    [majorId, midId, leaf],
  )
  const genreReadyCount = useMemo(
    () => stories.filter((story) => story.genre).length,
    [stories],
  )

  const load = () => {
    api.stories
      .list()
      .then(setStories)
      .catch((e) => setErr(String(e.message)))
  }

  useEffect(() => {
    load()
  }, [])

  const create = async () => {
    if (!title.trim() || creating) return
    setErr(null)
    setInfoMsg(null)
    setCreating(true)
    try {
      const ws = worldSetting.trim()
      const created = await api.stories.create({
        title: title.trim(),
        genre,
        world_setting: ws || undefined,
      })
      setTitle('')
      setWorldSetting('')
      setMajorId('')
      setMidId('')
      setLeaf('')
      await load()
      if (ws) {
        setIntake({
          storyId: created.id,
          storyInput: ws,
          genre,
          language: 'KO',
        })
      } else {
        setInfoMsg('새 프로젝트가 생성되었습니다.')
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="dash-shell">
      <div className="dash-inner">
        <header className="dash-hero">
          <div className="dash-hero-content">
            <p className="dash-eyebrow">Writer Studio</p>
            <h1 className="dash-title">소설 집필 에이전트</h1>
            <p className="dash-lead">
              긴 호흡의 작품을 만들고, 각 작품의 원고와 기억을 같은 작업실에서 관리합니다.
            </p>
          </div>
        </header>

        {err && <div className="dash-alert">{err}</div>}
        {infoMsg && (
          <div className="dash-alert" style={{ background: 'rgba(47, 143, 90, 0.12)', color: '#2f8f5a' }}>
            {infoMsg}
          </div>
        )}

        <div className="dash-layout">
          <section className="dash-card" aria-labelledby="dash-new-label">
            <h2 id="dash-new-label" className="dash-card-title">
              새 프로젝트
            </h2>
            <div className="dash-form-row">
              <label>
                <span className="dash-label">소설 제목</span>
                <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="예: 서울역의 지수" />
              </label>
              <button type="button" className="primary" onClick={create} disabled={creating || !title.trim()}>
                {creating ? '만드는 중…' : '만들기'}
              </button>
            </div>
            <label style={{ display: 'block', marginTop: '0.75rem' }}>
              <span className="dash-label">
                세계관·배경 (선택 — 입력이 있으면 만들기 직후 배경 진단 모달이 열립니다)
              </span>
              <textarea
                value={worldSetting}
                onChange={(e) => setWorldSetting(e.target.value)}
                placeholder="인물 관계, 세계의 규칙, 핵심 갈등… 짧게 적어도 됩니다."
                rows={3}
                style={{ width: '100%', marginTop: 6, resize: 'vertical' }}
              />
            </label>
            <p className="dash-label" style={{ margin: '0 0 0.5rem' }}>
              장르 (3단계, 선택)
            </p>
            <div className="dash-genre-grid">
              <label>
                <span className="dash-label">대분류</span>
                <select
                  value={majorId}
                  onChange={(e) => {
                    setMajorId(e.target.value)
                    setMidId('')
                    setLeaf('')
                  }}
                >
                  <option value="">선택</option>
                  {GENRE_TAXONOMY.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="dash-label">분류 (중분류)</span>
                <select
                  value={midId}
                  onChange={(e) => {
                    setMidId(e.target.value)
                    setLeaf('')
                  }}
                  disabled={!major}
                >
                  <option value="">{major ? '선택' : '먼저 대분류'}</option>
                  {major?.mids.map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="dash-label">세부 장르</span>
                <select value={leaf} onChange={(e) => setLeaf(e.target.value)} disabled={!mid}>
                  <option value="">{mid ? '선택' : '먼저 분류'}</option>
                  {mid?.items.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {genre ? (
              <p className="dash-hint" style={{ marginTop: '0.65rem' }}>
                저장될 장르 표기: <span style={{ color: 'var(--text)' }}>{genre}</span>
              </p>
            ) : (
              <p className="dash-hint" style={{ marginTop: '0.65rem' }}>
                세 단계를 모두 고르면 장르가 지정됩니다. 건너뛰려면 비워 두세요.
              </p>
            )}
          </section>

          <aside className="dash-aside-card dash-metrics-card">
            <h3>라이브러리</h3>
            <div className="dash-metric-list" aria-label="작품 현황">
              <div>
                <span>전체 작품</span>
                <strong>{stories.length}편</strong>
              </div>
              <div>
                <span>장르 지정</span>
                <strong>{genreReadyCount}편</strong>
              </div>
              <div>
                <span>새 작업</span>
                <strong>{title.trim() ? '작성 중' : '대기'}</strong>
              </div>
            </div>
          </aside>
        </div>

        <div className="dash-section-head">
          <h2 id="dash-board">내 작품</h2>
          <span className="dash-count">{stories.length}편</span>
        </div>
        <ul className="dash-story-grid" aria-labelledby="dash-board">
          {stories.length === 0 && (
            <li className="dash-empty">
              <strong>아직 작품이 없습니다</strong>
              위에서 제목을 입력하고 프로젝트를 만들면 여기에 카드가 쌓입니다.
            </li>
          )}
          {stories.map((s) => (
            <li key={s.id}>
              <Link to={`/story/${s.id}`} className="dash-story-card">
                <span className="dash-story-card-title">{s.title}</span>
                {s.genre ? <span className="dash-story-card-genre">{s.genre}</span> : null}
                {!s.genre ? (
                  <span className="dash-story-card-genre" style={{ opacity: 0.55 }}>
                    장르 미지정 · 클릭하여 집필 공간으로
                  </span>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
      </div>

      {intake && (
        <IntakeModal
          mode="create"
          initialStoryInput={intake.storyInput}
          storyId={intake.storyId}
          genre={intake.genre}
          language={intake.language}
          onClose={() => {
            setIntake(null)
            void load()
          }}
          onFinalized={(r) => {
            setIntake(null)
            const entities = Number(r.foundation_sync?.entities ?? 0)
            const summaries = Number(r.foundation_sync?.summary_nodes ?? 0)
            setInfoMsg(
              `배경 진단 완료 — 설정 노트 ${r.applied_bible}건 · 기억 ${entities}건 · 요약트리 ${summaries}건`,
            )
            void load()
          }}
        />
      )}
    </div>
  )
}
