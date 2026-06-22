from pathlib import Path
import unittest


class VectorIndexMigrationTests(unittest.TestCase):
    def test_3072_hnsw_indexes_use_halfvec_expression(self) -> None:
        root = Path(__file__).resolve().parents[1] / "alembic" / "versions"
        migration_sql = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                root / "007_longform_memory_v2.py",
                root / "008_story_summary_nodes.py",
            )
        )

        self.assertNotIn("USING hnsw (embedding vector_cosine_ops)", migration_sql)
        self.assertIn("embedding::halfvec(3072)", migration_sql)
        self.assertIn("halfvec_cosine_ops", migration_sql)


if __name__ == "__main__":
    unittest.main()
