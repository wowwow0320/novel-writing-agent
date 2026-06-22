import unittest

from app.services import draft_guard
from app.services.draft_guard import find_draft_drift_issues, revise_draft_if_needed


SOURCE_MEMO = """
11월의 캐나다는 생각보다 춥지 않았다. 두꺼운 패딩만 챙겨가 조금 더웠다.
다음날 바로 어학원으로 갔다. 영어 발음이 쪽팔려 긴장했다.
화장실 앞에서 일본인 친구 Hina가 "Hi! I am Hina"라고 인사했고, 나는 "Hello!"라고 답했다.
차갑게 생긴 여자애가 나와 Hina의 팔짱을 끼고 나를 위아래로 훑어 보았다.
"""


BAD_DRAFT = """
11월의 캐나다는 생각보다 춥지 않았다. 예원은 활발하게 수업에 참여하고 있었다.
수업이 끝난 후 일본인 친구가 "잘하고 있어!"라고 말했다.
도서관에서 함께 시간을 보내기로 약속하며, 관계가 우정에서 사랑으로 발전할 가능성을 품었다.
“정민아, 괜찮아?” 예원이 내 곁에 다가왔다.
"""


class DraftGuardTests(unittest.IsolatedAsyncioTestCase):
    def test_detects_unmentioned_names_dialogue_and_plot_beats(self) -> None:
        issues = find_draft_drift_issues(SOURCE_MEMO, BAD_DRAFT)
        kinds = {i["kind"] for i in issues}
        values = {str(i["value"]) for i in issues}

        self.assertIn("unmentioned_name", kinds)
        self.assertIn("unmentioned_dialogue", kinds)
        self.assertIn("unmentioned_plot_beat", kinds)
        self.assertIn("예원", values)
        self.assertIn("정민", values)
        self.assertIn("도서관", values)
        self.assertIn("잘하고 있어!", values)

    async def test_revision_runs_only_when_drift_is_detected(self) -> None:
        seen: dict[str, str] = {}
        old_complete = draft_guard.llm.complete_chat

        async def fake_complete(system: str, user: str, temperature: float = 0.2) -> str:
            seen["system"] = system
            seen["user"] = user
            seen["temperature"] = str(temperature)
            return "11월의 캐나다는 생각보다 춥지 않았다. 화장실 앞에서 Hina가 인사했다."

        draft_guard.llm.complete_chat = fake_complete
        try:
            revised, trace = await revise_draft_if_needed(SOURCE_MEMO, BAD_DRAFT)
        finally:
            draft_guard.llm.complete_chat = old_complete

        self.assertEqual(trace["revision"], "llm")
        self.assertIn("예원", seen["user"])
        self.assertIn("도서관", seen["user"])
        self.assertIn("원문에 없는 이름", seen["system"])
        self.assertIn("Hina", revised)

    async def test_revision_falls_back_to_source_when_llm_keeps_major_drift(self) -> None:
        old_complete = draft_guard.llm.complete_chat

        async def fake_complete(system: str, user: str, temperature: float = 0.2) -> str:
            return BAD_DRAFT

        draft_guard.llm.complete_chat = fake_complete
        try:
            revised, trace = await revise_draft_if_needed(SOURCE_MEMO, BAD_DRAFT)
        finally:
            draft_guard.llm.complete_chat = old_complete

        self.assertEqual(trace["revision"], "fallback_source_memo")
        self.assertIn("11월의 캐나다", revised)
        self.assertIn("Hina", revised)
        self.assertNotIn("예원", revised)
        self.assertNotIn("도서관", revised)

    async def test_segment_fallback_uses_segment_memo_not_full_raw_memory(self) -> None:
        old_complete = draft_guard.llm.complete_chat
        segment_source = """
전체 원문 첫 사건: 캐나다 날씨와 어학원 첫 수업을 길게 설명한다.

[세그먼트 메모]
화장실 앞에서 일본인 친구 Hina가 "Hi! I am Hina"라고 먼저 인사한다.
차갑게 생긴 친구가 Hina의 팔짱을 끼고 나를 위아래로 훑어본다.
"""

        async def fake_complete(system: str, user: str, temperature: float = 0.2) -> str:
            return BAD_DRAFT

        draft_guard.llm.complete_chat = fake_complete
        try:
            revised, trace = await revise_draft_if_needed(segment_source, BAD_DRAFT)
        finally:
            draft_guard.llm.complete_chat = old_complete

        self.assertEqual(trace["revision"], "fallback_source_memo")
        self.assertIn("화장실 앞에서 일본인 친구 Hina", revised)
        self.assertIn("위아래로 훑어본다", revised)
        self.assertNotIn("전체 원문 첫 사건", revised)
        self.assertNotIn("캐나다 날씨와 어학원 첫 수업", revised)

    async def test_revision_skips_clean_draft(self) -> None:
        clean = "11월의 캐나다는 생각보다 따뜻했다. 화장실 앞에서 Hina가 인사했고, 나는 Hello라고 답했다."

        revised, trace = await revise_draft_if_needed(SOURCE_MEMO, clean)

        self.assertEqual(revised, clean)
        self.assertEqual(trace["revision"], "skipped")
        self.assertEqual(trace["issues"], [])


if __name__ == "__main__":
    unittest.main()
