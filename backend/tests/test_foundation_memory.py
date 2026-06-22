import unittest

from app.services.foundation_memory import foundation_summary_text, foundation_to_event_payloads


class FoundationMemoryUnitTests(unittest.TestCase):
    def test_foundation_summary_text_preserves_world_premise_and_entities(self) -> None:
        foundation = {
            "premise": "도시는 기억을 세금처럼 징수한다.",
            "entities": {
                "characters": [{"name": "서윤", "traits": ["기록 관리자"], "goals": ["진실 복원"]}],
                "backgrounds": [{"place": "지하 보관소", "era": "근미래", "mood": "습하고 조용함"}],
                "events": [{"title": "봉인 사건", "cause": "기록 조작", "outcome": "사람들이 사라짐"}],
            },
        }

        text = foundation_summary_text(foundation)

        self.assertIn("도시는 기억을 세금처럼 징수한다", text)
        self.assertIn("서윤", text)
        self.assertIn("지하 보관소", text)
        self.assertIn("봉인 사건", text)

    def test_foundation_to_event_payloads_maps_initial_events(self) -> None:
        foundation = {
            "entities": {
                "events": [
                    {
                        "title": "봉인 사건",
                        "cause": "기록 조작",
                        "outcome": "증거가 사라짐",
                        "stakes": "도시 전체의 기억이 흔들림",
                    }
                ]
            }
        }

        events = foundation_to_event_payloads(foundation)

        self.assertEqual(events[0]["title"], "봉인 사건")
        self.assertEqual(events[0]["cause"], "기록 조작")
        self.assertEqual(events[0]["effect"], "증거가 사라짐")
        self.assertEqual(events[0]["importance"], 4)
        self.assertEqual(events[0]["metadata"]["source"], "world_setting")


if __name__ == "__main__":
    unittest.main()
