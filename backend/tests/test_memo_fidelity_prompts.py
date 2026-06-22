import unittest

from app.services import scene_planner
from app.services.context_builder import format_global_context_pin
from app.services.prompts import expand_draft_system, expand_draft_user


class MemoFidelityPromptTests(unittest.IsolatedAsyncioTestCase):
    def test_expand_prompt_prioritizes_raw_memo_over_context(self) -> None:
        system = expand_draft_system(
            pin="세계관: 다른 장르의 배경",
            genre="현대 성장",
            writer_role="소설가",
            style_guide="담백하게",
            language="KO",
        )
        user = expand_draft_user(
            synopsis="",
            bible_block="캐나다가 아닌 가상의 도시",
            graph_block="",
            memory_block="",
            prev_summary="",
            sliding_context="",
            raw_memory="11월의 캐나다, Hina, 어학원 첫날, 화장실 앞 인사.",
        )

        self.assertIn("[사용자 메모(원석)]가 가장 높은 우선순위", system)
        self.assertIn("바이블/RAG/그래프가 원석과 충돌하면 원석을 따릅니다", system)
        self.assertIn("[메모 충실도 계약]", user)
        self.assertIn("전체 소설을 끝내려 하지 말고", user)
        self.assertIn("나는/내가/난", user)
        self.assertIn("11월의 캐나다", user)
        self.assertIn("Hina", user)

    def test_global_context_pin_is_constraint_not_current_plot(self) -> None:
        pin = format_global_context_pin(
            {
                "title": "캐나다 어학연수",
                "genre": "성장",
                "world_setting": "주인공은 낯선 환경에서 성장한다.",
                "global_rules": {},
                "style_guide": "1인칭 담백한 회고",
                "language": "KO",
            }
        )

        self.assertIn("작품의 장기 제약", pin)
        self.assertIn("작가 메모가 결정", pin)
        self.assertIn("기승전결 완결 지시로 해석하지 말고", pin)

    async def test_stitch_llm_receives_source_memo_as_fact_baseline(self) -> None:
        seen: dict[str, str] = {}
        old_complete = scene_planner.llm.complete_chat

        async def fake_complete(system: str, user: str, temperature: float = 0.25) -> str:
            seen["system"] = system
            seen["user"] = user
            seen["temperature"] = str(temperature)
            return "수정된 본문"

        scene_planner.llm.complete_chat = fake_complete
        try:
            out = await scene_planner.stitch_with_llm(
                ["첫 세그먼트", "둘째 세그먼트"],
                {"pin": ""},
                source_memo="11월의 캐나다에서 Hina가 화장실 앞에서 인사한다.",
            )
        finally:
            scene_planner.llm.complete_chat = old_complete

        self.assertEqual(out, "수정된 본문")
        self.assertIn("[원본 작가 메모]", seen["user"])
        self.assertIn("11월의 캐나다", seen["user"])
        self.assertIn("최종 사실 기준", seen["system"])
        self.assertIn("기승전결", seen["system"])
        self.assertIn("나는/내가/난", seen["user"])


if __name__ == "__main__":
    unittest.main()
