import unittest

from app.schemas import MemoQaAnswerItem, MemoQaQuestionItem, MemoSegmentItem, MemoSurveySnapshot
from app.services.memo_orchestrator import (
    MemoSegment,
    apply_memo_qa_answers,
    assess_memo_readiness,
    estimate_memo_work,
)


class MemoQaWorkflowTests(unittest.TestCase):
    def test_readiness_requires_questions_for_underspecified_multi_segment_memo(self) -> None:
        segments = [
            MemoSegment(id="m1", order=1, label="단서 발견", writer_memo="서윤이 파손된 카드를 발견한다."),
            MemoSegment(id="m2", order=2, label="하준 대립", writer_memo="하준이 숨긴 과거를 말하려다 멈춘다."),
            MemoSegment(id="m3", order=3, label="추적 시작", writer_memo="두 사람이 지하 기록실을 떠난다."),
        ]
        questions = [
            MemoQaQuestionItem(
                id="q1",
                segment_id="m1",
                question="카드가 왜 중요한가요?",
                options=["실종자 목록과 연결된다", "도시 권력의 비밀 장부다"],
            ),
            MemoQaQuestionItem(
                id="q2",
                segment_id="m2",
                question="하준이 침묵하는 이유는?",
                options=["죄책감", "서윤을 보호하려는 계산"],
            ),
        ]

        readiness = assess_memo_readiness(
            "서윤, 하준, 지민, 봉인 사건이 얽힌 긴 회차 메모",
            segments,
            questions,
            {"mode": "multi_step"},
        )
        estimate = estimate_memo_work(segments)

        self.assertTrue(readiness["needs_questions"])
        self.assertLess(readiness["score"], 0.82)
        self.assertGreaterEqual(len(readiness["reasons"]), 2)
        self.assertEqual(estimate["segments"], 3)
        self.assertEqual(estimate["draft_calls"], 3)
        self.assertEqual(estimate["memory_searches"], 3)
        self.assertEqual(estimate["stitch_calls"], 1)

    def test_readiness_skips_modal_when_survey_has_no_questions(self) -> None:
        segments = [
            MemoSegment(
                id="m1",
                order=1,
                label="연속 본문",
                writer_memo=(
                    "서윤은 지하 보관소에서 하준과 마주하고, 이미 드러난 카드의 의미를 바탕으로 "
                    "직전 대화의 감정선을 이어가며 다음 단서를 확인한다."
                ),
            )
        ]

        readiness = assess_memo_readiness(
            "충분히 구체적인 회차 메모",
            segments,
            [],
            {"mode": "single_pass"},
        )
        estimate = estimate_memo_work(segments)

        self.assertFalse(readiness["needs_questions"])
        self.assertGreaterEqual(readiness["score"], 0.82)
        self.assertEqual(readiness["reasons"], ["입력 메모가 바로 생성 가능한 수준입니다."])
        self.assertEqual(estimate["stitch_calls"], 0)

    def test_apply_answers_reuses_survey_segments_without_resegmenting(self) -> None:
        survey = MemoSurveySnapshot(
            segments=[
                MemoSegmentItem(
                    id="m1",
                    order=1,
                    label="카드 발견",
                    writer_memo="서윤이 파손된 인덱스 카드를 발견한다.",
                ),
                MemoSegmentItem(
                    id="m2",
                    order=2,
                    label="하준의 침묵",
                    writer_memo="하준이 카드의 의미를 알고도 말하지 않는다.",
                ),
            ],
            questions=[
                MemoQaQuestionItem(
                    id="q1",
                    segment_id="m2",
                    question="하준이 숨기는 감정은?",
                    options=["죄책감", "분노", "공포"],
                )
            ],
        )

        merged = apply_memo_qa_answers(
            survey,
            {"q1": MemoQaAnswerItem(selected_index=2, freeform="서윤이 다칠까 봐 말을 삼킨다.")},
        )

        self.assertEqual([s.id for s in merged], ["m1", "m2"])
        self.assertEqual([s.order for s in merged], [1, 2])
        self.assertIn("공포", merged[1].writer_memo)
        self.assertIn("서윤이 다칠까 봐", merged[1].writer_memo)


if __name__ == "__main__":
    unittest.main()
