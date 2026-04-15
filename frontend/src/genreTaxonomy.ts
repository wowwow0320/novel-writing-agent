/** 3단계 장르 분류: 대분류 → 중분류(세부 분류) → 최종 소재/유형 */

export type GenreMid = {
  id: string
  label: string
  items: string[]
}

export type GenreMajor = {
  id: string
  label: string
  mids: GenreMid[]
}

export const GENRE_TAXONOMY: GenreMajor[] = [
  {
    id: 'traditional',
    label: '1. 정통 문학 및 주요 장르',
    mids: [
      {
        id: 'pure-lit',
        label: '(1) 순수 문학',
        items: ['사실주의', '자연주의', '모더니즘', '포스트모더니즘'],
      },
      {
        id: 'romance',
        label: '(2) 로맨스',
        items: ['현대 로맨스', '시대물', '하이틴', '오피스물'],
      },
      {
        id: 'fantasy',
        label: '(3) 판타지',
        items: ['하이 판타지', '로우 판타지', '다크 판타지', '어반 판타지'],
      },
      {
        id: 'sf',
        label: '(4) SF (공상과학)',
        items: ['스페이스 오퍼라', '사이버펑크', '디스토피아', '포스트 아포칼립스'],
      },
      {
        id: 'mystery',
        label: '(5) 추리/미스터리',
        items: ['본격 추리', '사회파 추리', '코지 미스터리', '하드보일드'],
      },
      {
        id: 'thriller-horror',
        label: '(6) 스릴러/공포',
        items: ['서스펜스', '오컬트', '슬래셔', '심리 스릴러'],
      },
      {
        id: 'muhyeop',
        label: '(7) 무협',
        items: ['구무협', '신무협', '환환무협', '선협(수선물)'],
      },
      {
        id: 'historical',
        label: '(8) 역사/시대극',
        items: ['정통 사극', '팩션', '가상 역사물'],
      },
    ],
  },
  {
    id: 'webnovel',
    label: '2. 현대 웹소설 특화 장르',
    mids: [
      {
        id: 'hoebinghwan',
        label: '(1) 회빙환 (주요 소재)',
        items: ['회귀물', '빙의물', '환생물'],
      },
      {
        id: 'modern-fantasy',
        label: '(2) 현대 판타지',
        items: ['전문가물', '재벌물', '헌터물', '성좌물', '이능력물'],
      },
      {
        id: 'romance-fantasy',
        label: '(3) 로맨스 판타지',
        items: ['악녀물', '육아물', '계약결혼물', '구원물'],
      },
      {
        id: 'game-sports',
        label: '(4) 게임/스포츠',
        items: ['게임 판타지', '레이드물', '축구/야구/골프물'],
      },
      {
        id: 'subculture',
        label: '(5) 서브컬처 및 기타',
        items: ['라이트 노벨', 'BL', 'GL', 'TS(성전환)물'],
      },
    ],
  },
  {
    id: 'by-nature',
    label: '3. 내용 및 성격에 따른 분류',
    mids: [
      {
        id: 'structure',
        label: '(1) 전개 방식',
        items: ['성장 소설', '피카레스크', '옴니버스', '액자식 구성'],
      },
      {
        id: 'satire',
        label: '(2) 사회/풍자',
        items: ['풍자 소설', '해학 소설', '사회 비판 소설'],
      },
      {
        id: 'special',
        label: '(3) 기타 특수 장르',
        items: ['대체 역사물', '군상극', '밀리터리물'],
      },
    ],
  },
]

export function buildGenrePath(majorId: string, midId: string, leaf: string): string {
  const major = GENRE_TAXONOMY.find((m) => m.id === majorId)
  const mid = major?.mids.find((x) => x.id === midId)
  if (!major || !mid || !leaf || !mid.items.includes(leaf)) return ''
  return `${major.label} › ${mid.label} › ${leaf}`
}
