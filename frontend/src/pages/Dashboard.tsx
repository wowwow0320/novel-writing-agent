import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Story } from '../api'
import { buildGenrePath, GENRE_TAXONOMY } from '../genreTaxonomy'

export function Dashboard() {
  const [stories, setStories] = useState<Story[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [majorId, setMajorId] = useState('')
  const [midId, setMidId] = useState('')
  const [leaf, setLeaf] = useState('')

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

  const load = () => {
    api.stories
      .list()
      .then(setStories)
      .catch((e) => setErr(String(e.message)))
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    setMidId('')
    setLeaf('')
  }, [majorId])

  useEffect(() => {
    setLeaf('')
  }, [midId])

  const create = async () => {
    if (!title.trim()) return
    setErr(null)
    try {
      await api.stories.create({ title: title.trim(), genre })
      setTitle('')
      setMajorId('')
      setMidId('')
      setLeaf('')
      load()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="dash-shell">
      <div className="dash-inner">
        <header className="dash-hero">
          <div className="dash-hero-content">
            <p className="dash-eyebrow">Novel workspace</p>
            <h1 className="dash-title">소설 집필 에이전트</h1>
            <p className="dash-lead">
              작품마다 메모와 원고를 나란히 쓰고, 설정 노트와 검색으로 긴 호흡을 이어 갑니다. 프로젝트를 만들고 바로 집필
              공간으로 들어가 보세요.
            </p>
          </div>
          <ul className="dash-features">
            <li>
              <strong>메모 ↔ 원고</strong>
              작가 메모를 바탕으로 AI 초안과 문체 변환을 돕습니다.
            </li>
            <li>
              <strong>설정 노트</strong>
              인물·사건을 모아 두고 저장 시 자동으로 갱신할 수 있습니다.
            </li>
            <li>
              <strong>검색·이어쓰기</strong>
              과거 장면을 찾고, 직전 화와 자연스럽게 잇는 제안을 받습니다.
            </li>
          </ul>
        </header>

        {err && <div className="dash-alert">{err}</div>}

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
              <button type="button" className="primary" onClick={create}>
                만들기
              </button>
            </div>
            <p className="dash-label" style={{ margin: '0 0 0.5rem' }}>
              장르 (3단계, 선택)
            </p>
            <div className="dash-genre-grid">
              <label>
                <span className="dash-label">대분류</span>
                <select value={majorId} onChange={(e) => setMajorId(e.target.value)}>
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
                <select value={midId} onChange={(e) => setMidId(e.target.value)} disabled={!major}>
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

          <aside className="dash-aside-card">
            <h3>처음 오셨나요?</h3>
            <p>
              목록에서 작품을 고르면 챕터별 에디터로 이동합니다. 좁은 화면에서는 상단의 <strong>도구</strong> 버튼으로 AI
              도움말 패널을 열 수 있습니다.
            </p>
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
    </div>
  )
}
