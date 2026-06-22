import unittest

from app.services.memory_retrieval import (
    MemoryBundle,
    MemoryEntityHit,
    MemoryEventHit,
    MemoryExcerptHit,
    MemoryRelationshipHit,
    MemorySummaryNodeHit,
    format_memory_bundle_for_prompt,
    memory_trace_from_bundle,
    normalize_entity_name,
)


class MemoryRetrievalFormattingTests(unittest.TestCase):
    def test_normalize_entity_name_collapses_spacing_and_case(self) -> None:
        self.assertEqual(normalize_entity_name("  Alice   KIM  "), "alice kim")
        self.assertEqual(normalize_entity_name("김   하윤"), "김 하윤")

    def test_format_bundle_groups_hits_for_writer_prompt(self) -> None:
        bundle = MemoryBundle(
            query="김하윤 배신",
            entities=[
                MemoryEntityHit(
                    id="ent-1",
                    name="김하윤",
                    entity_type="CHAR",
                    description="주인공. 왕실 첩자.",
                    importance=5,
                )
            ],
            relationships=[
                MemoryRelationshipHit(
                    id="rel-1",
                    source="김하윤",
                    target="서도윤",
                    relation_type="ENEMY_OF",
                    current_state="betrayed",
                    evidence="8화에서 서도윤이 하윤을 함정에 빠뜨림.",
                    confidence=0.82,
                )
            ],
            events=[
                MemoryEventHit(
                    id="ev-1",
                    title="서도윤의 배신",
                    summary="서도윤이 하윤의 정보를 적에게 넘긴 사건.",
                    chapter_num=8,
                    importance=5,
                )
            ],
            excerpts=[
                MemoryExcerptHit(
                    source="episode",
                    snippet="하윤은 서도윤의 손등에 남은 인장을 보고 말을 잃었다.",
                    chapter_num=8,
                    score=0.91,
                )
            ],
            summary_nodes=[
                MemorySummaryNodeHit(
                    id="sum-1",
                    node_key="arc:1-8",
                    level="arc",
                    summary="1~8화는 김하윤과 서도윤의 신뢰가 배신으로 무너지는 흐름이다.",
                    chapter_start=1,
                    chapter_end=8,
                    score=0.88,
                )
            ],
            graph_context="- 김하윤 -[ENEMY_OF]-> 서도윤",
            warnings=["관계 상태가 최근 회차에서 적대로 바뀜"],
        )

        text = format_memory_bundle_for_prompt(bundle)

        self.assertIn("[자동 검색된 장기 기억]", text)
        self.assertIn("[관련 인물/설정]", text)
        self.assertIn("김하윤", text)
        self.assertIn("ENEMY_OF", text)
        self.assertIn("서도윤의 배신", text)
        self.assertIn("[요약 트리 기억]", text)
        self.assertIn("arc:1-8", text)
        self.assertIn("관계 상태", text)

    def test_memory_trace_is_compact_and_identifier_oriented(self) -> None:
        bundle = MemoryBundle(
            query="하윤",
            entities=[
                MemoryEntityHit(
                    id="ent-1",
                    name="김하윤",
                    entity_type="CHAR",
                    description="긴 설명",
                    importance=4,
                )
            ],
            relationships=[],
            events=[],
            excerpts=[
                MemoryExcerptHit(
                    source="episode",
                    snippet="x" * 500,
                    chapter_num=2,
                    score=0.7,
                )
            ],
            summary_nodes=[
                MemorySummaryNodeHit(
                    id="sum-1",
                    node_key="chapter:2",
                    level="chapter",
                    summary="x" * 500,
                    chapter_start=2,
                    chapter_end=2,
                    score=0.75,
                )
            ],
        )

        trace = memory_trace_from_bundle(bundle)

        self.assertEqual(trace["query"], "하윤")
        self.assertEqual(trace["entities"][0]["id"], "ent-1")
        self.assertEqual(trace["summary_nodes"][0]["node_key"], "chapter:2")
        self.assertLessEqual(len(trace["summary_nodes"][0]["summary"]), 220)
        self.assertLessEqual(len(trace["excerpts"][0]["snippet"]), 180)


if __name__ == "__main__":
    unittest.main()
