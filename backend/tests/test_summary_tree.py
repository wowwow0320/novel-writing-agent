import unittest

from app.services.summary_tree import (
    choose_summary_hits,
    group_bodies_for_summary,
    level_boost,
    summary_node_rank,
)


class SummaryTreeUnitTests(unittest.TestCase):
    def test_group_bodies_for_summary_uses_four_body_default(self) -> None:
        bodies = [object() for _ in range(9)]

        groups = group_bodies_for_summary(bodies)

        self.assertEqual([len(g) for g in groups], [4, 4, 1])

    def test_summary_rank_prefers_covering_ancestor_when_score_is_strong(self) -> None:
        parent = {
            "id": "arc-1",
            "level": "arc",
            "summary": "서윤과 하준이 지하 보관소에서 봉인 사건의 원인을 추적한다.",
            "semantic_score": 0.83,
            "entity_overlap": 1.0,
            "event_overlap": 0.8,
            "relationship_overlap": 0.5,
            "chapter_proximity": 0.7,
            "stale": False,
        }
        child = {
            "id": "chunk-1",
            "level": "body_group",
            "summary": "서윤이 지하 보관소에서 파손된 카드를 발견한다.",
            "semantic_score": 0.80,
            "entity_overlap": 1.0,
            "event_overlap": 0.7,
            "relationship_overlap": 0.4,
            "chapter_proximity": 0.8,
            "stale": False,
            "ancestor_ids": ["arc-1"],
        }

        ordered = choose_summary_hits([child, parent], query="서윤 하준 봉인 사건")

        self.assertEqual(ordered[0]["id"], "arc-1")

    def test_summary_rank_allows_specific_child_to_beat_weak_parent(self) -> None:
        parent = {
            "id": "arc-1",
            "level": "arc",
            "summary": "도시의 기록청에서 여러 사건이 이어진다.",
            "semantic_score": 0.61,
            "entity_overlap": 0.2,
            "event_overlap": 0.1,
            "relationship_overlap": 0.0,
            "chapter_proximity": 0.5,
            "stale": False,
        }
        child = {
            "id": "body-1",
            "level": "body_group",
            "summary": "서윤이 지민의 이름이 적힌 파손된 인덱스 카드를 발견한다.",
            "semantic_score": 0.84,
            "entity_overlap": 1.0,
            "event_overlap": 0.7,
            "relationship_overlap": 0.1,
            "chapter_proximity": 1.0,
            "stale": False,
            "ancestor_ids": ["arc-1"],
        }

        ordered = choose_summary_hits([parent, child], query="지민 파손된 인덱스 카드")

        self.assertEqual(ordered[0]["id"], "body-1")

    def test_level_boost_gives_upper_nodes_small_advantage(self) -> None:
        self.assertGreater(level_boost("work"), level_boost("body_group"))
        self.assertGreater(level_boost("arc"), level_boost("chapter"))

    def test_stale_nodes_are_penalized(self) -> None:
        fresh = summary_node_rank({"semantic_score": 0.7, "level": "chapter", "stale": False})
        stale = summary_node_rank({"semantic_score": 0.7, "level": "chapter", "stale": True})

        self.assertGreater(fresh, stale)


if __name__ == "__main__":
    unittest.main()
