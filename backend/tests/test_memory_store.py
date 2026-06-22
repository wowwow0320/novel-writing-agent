import unittest

from app.services.memory_store import bible_entry_to_entity_payload, graph_entity_to_payload


class MemoryStorePayloadTests(unittest.TestCase):
    def test_bible_entry_payload_uses_category_as_entity_type_and_normalized_name(self) -> None:
        payload = bible_entry_to_entity_payload(
            {
                "category": "CHAR",
                "name": "  Alice   KIM ",
                "description": "왕실 첩자",
                "metadata": {"aliases": ["앨리스"], "importance": 5, "status": "alive"},
            }
        )

        self.assertEqual(payload["entity_type"], "CHAR")
        self.assertEqual(payload["name"], "Alice   KIM")
        self.assertEqual(payload["normalized_name"], "alice kim")
        self.assertEqual(payload["aliases"], ["앨리스"])
        self.assertEqual(payload["importance"], 5)
        self.assertEqual(payload["status"], "alive")

    def test_graph_entity_payload_keeps_supported_type_and_origin_hint(self) -> None:
        payload = graph_entity_to_payload(
            {
                "name": "검은 항구",
                "type": "LOC",
                "origin_hint": "12화 밀수 현장",
                "importance": 4,
            }
        )

        self.assertEqual(payload["entity_type"], "LOC")
        self.assertEqual(payload["description"], "12화 밀수 현장")
        self.assertEqual(payload["normalized_name"], "검은 항구")


if __name__ == "__main__":
    unittest.main()
