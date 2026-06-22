import unittest

from app.database import Base
from app.models import (
    Episode,
    GenerationRun,
    StorySummaryNode,
    StoryEntity,
    StoryEvent,
    StoryRelationship,
    StoryRelationshipEvidence,
)


class MemoryModelMetadataTests(unittest.TestCase):
    def test_memory_tables_are_registered(self) -> None:
        for table_name in (
            "story_entities",
            "story_events",
            "story_relationships",
            "story_relationship_evidence",
            "generation_runs",
            "story_summary_nodes",
        ):
            self.assertIn(table_name, Base.metadata.tables)

    def test_entity_unique_constraint_uses_story_type_and_normalized_name(self) -> None:
        names = {constraint.name for constraint in StoryEntity.__table__.constraints}
        self.assertIn("uq_story_entities_story_type_normalized", names)

    def test_relationship_evidence_points_to_relationship_and_episode(self) -> None:
        cols = StoryRelationshipEvidence.__table__.columns
        self.assertIn("relationship_id", cols)
        self.assertIn("episode_id", cols)
        self.assertIn("paragraph_index", cols)

    def test_generation_run_keeps_memory_trace_and_revision_payload(self) -> None:
        cols = GenerationRun.__table__.columns
        self.assertIn("memory_trace", cols)
        self.assertIn("revision_payload", cols)

    def test_relationship_has_canonical_endpoint_columns(self) -> None:
        cols = StoryRelationship.__table__.columns
        self.assertIn("source_entity_id", cols)
        self.assertIn("target_entity_id", cols)

    def test_event_has_source_anchor_columns(self) -> None:
        cols = StoryEvent.__table__.columns
        self.assertIn("source_body_id", cols)
        self.assertIn("source_chunk_id", cols)

    def test_episode_chapter_is_unique_per_story(self) -> None:
        names = {constraint.name for constraint in Episode.__table__.constraints}
        self.assertIn("uq_episodes_story_chapter_num", names)

    def test_summary_node_keeps_searchable_tree_and_source_columns(self) -> None:
        cols = StorySummaryNode.__table__.columns
        for name in (
            "node_key",
            "level",
            "parent_id",
            "root_id",
            "path",
            "source_body_ids",
            "source_episode_ids",
            "entity_ids",
            "event_ids",
            "relationship_ids",
            "summary",
            "embedding",
            "token_count",
            "coverage_score",
            "stale",
        ):
            self.assertIn(name, cols)

    def test_summary_node_is_idempotent_per_story_and_node_key(self) -> None:
        names = {constraint.name for constraint in StorySummaryNode.__table__.constraints}
        self.assertIn("uq_story_summary_nodes_story_node_key", names)


if __name__ == "__main__":
    unittest.main()
