from datetime import UTC, datetime

from specpilot_ai.core.models import (
    CheckStatus,
    PublicReviewerQuickCardKit,
    ReviewerQuickCardRequest,
    ReviewerRiskCheck,
    ReviewerVoteOption,
)


def build_public_reviewer_quick_card_kit(
    request: ReviewerQuickCardRequest,
    generated_at: datetime | None = None,
) -> PublicReviewerQuickCardKit:
    generated_at = generated_at or datetime.now(UTC)
    title = _title(request)
    status = _review_status(request)
    score = _review_score(request, status)
    return PublicReviewerQuickCardKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        product_title=title,
        review_status=status,
        review_score=score,
        headline=_headline(title, status, score),
        buyer_summary=_buyer_summary(request),
        reviewer_instruction=_reviewer_instruction(request, status),
        vote_options=_vote_options(request, status),
        risk_checks=_risk_checks(request),
        reviewer_questions=_reviewer_questions(request),
        required_evidence=_required_evidence(request),
        reply_templates=_reply_templates(request, status),
        analysis_prefill=_analysis_prefill(request, status),
        share_copy=_share_copy(request, status, score),
        next_actions=_next_actions(status),
    )


def _title(request: ReviewerQuickCardRequest) -> str:
    return request.product_title.strip() or "구매 후보"


def _review_status(request: ReviewerQuickCardRequest) -> CheckStatus:
    if request.blocker_count > 0 or request.confidence_percent < 55:
        return CheckStatus.blocker
    if request.warning_count > 0 or request.missing_evidence or request.confidence_percent < 80:
        return CheckStatus.warning
    return CheckStatus.ok


def _review_score(request: ReviewerQuickCardRequest, status: CheckStatus) -> int:
    score = request.confidence_percent
    score -= request.blocker_count * 18
    score -= request.warning_count * 6
    score -= len(request.missing_evidence[:4]) * 5
    if request.final_price_krw is not None and request.budget_krw is not None:
        if request.final_price_krw <= request.budget_krw:
            score += 8
        else:
            score -= 14
    if request.key_reasons:
        score += min(8, len(request.key_reasons) * 3)
    if status == CheckStatus.blocker:
        score = min(score, 54)
    return max(0, min(100, score))


def _buyer_summary(request: ReviewerQuickCardRequest) -> str:
    price = "미입력" if request.final_price_krw is None else f"{request.final_price_krw:,}원"
    budget = "미입력" if request.budget_krw is None else f"{request.budget_krw:,}원"
    reasons = ", ".join(request.key_reasons[:3]) if request.key_reasons else "핵심 근거 미입력"
    return (
        f"구매자는 {_title(request)}를 {price}에 검토 중입니다. "
        f"예산은 {budget}, 확신도는 {request.confidence_percent}%이며 근거는 {reasons}입니다."
    )


def _headline(title: str, status: CheckStatus, score: int) -> str:
    if status == CheckStatus.blocker:
        return f"{title} 검토 카드는 {score}점, 반대 또는 보류 응답이 먼저 필요합니다."
    if status == CheckStatus.warning:
        return f"{title} 검토 카드는 {score}점, 증거 요청 후 승인하는 흐름이 안전합니다."
    return f"{title} 검토 카드는 {score}점, 빠른 승인 응답으로 넘길 수 있습니다."


def _reviewer_instruction(request: ReviewerQuickCardRequest, status: CheckStatus) -> str:
    if status == CheckStatus.blocker:
        return f"{request.review_deadline}까지 반대 이유나 보류 조건을 하나만 명확히 남겨 주세요."
    if status == CheckStatus.warning:
        return f"{request.review_deadline}까지 누락 증거가 닫히면 승인한다는 조건부 응답을 남겨 주세요."
    return f"{request.review_deadline}까지 예산과 용도만 맞는지 확인하고 승인 응답을 남겨 주세요."


def _vote_options(
    request: ReviewerQuickCardRequest,
    status: CheckStatus,
) -> list[ReviewerVoteOption]:
    title = _title(request)
    return [
        ReviewerVoteOption(
            vote_id="approve",
            label="승인",
            status=CheckStatus.ok if status == CheckStatus.ok else CheckStatus.warning,
            description="예산, 용도, 증거가 충분하면 바로 결제 검수로 넘깁니다.",
            reply_text=f"{title} 구매 승인. 최종 결제 금액과 옵션명만 다시 캡처하고 진행해.",
        ),
        ReviewerVoteOption(
            vote_id="ask_evidence",
            label="증거 요청",
            status=CheckStatus.warning,
            description="가격, 사양, 보증/반품, 판매자 답변 중 빠진 증거를 요청합니다.",
            reply_text=(
                f"{title}는 조건부 승인. "
                f"{', '.join(_required_evidence(request)[:3])} 캡처를 먼저 보내줘."
            ),
        ),
        ReviewerVoteOption(
            vote_id="reject_or_hold",
            label="반대/보류",
            status=CheckStatus.blocker,
            description="예산 초과, blocker, 증거 누락이 크면 결제를 멈춥니다.",
            reply_text=f"{title}는 지금 결제 반대. 누락 증거와 대체 후보를 먼저 비교하자.",
        ),
    ]


def _risk_checks(request: ReviewerQuickCardRequest) -> list[ReviewerRiskCheck]:
    checks = [
        ReviewerRiskCheck(
            check_id="budget",
            label="예산",
            status=_budget_status(request),
            evidence=_budget_evidence(request),
            reviewer_action="최종 결제 금액이 예산 안인지 확인하세요.",
        ),
        ReviewerRiskCheck(
            check_id="evidence",
            label="증거",
            status=CheckStatus.warning if request.missing_evidence else CheckStatus.ok,
            evidence=(
                f"누락 증거: {', '.join(request.missing_evidence[:4])}"
                if request.missing_evidence
                else "필수 증거가 입력되어 있습니다."
            ),
            reviewer_action="상품명, 옵션명, 총액, 보증/반품 캡처를 확인하세요.",
        ),
        ReviewerRiskCheck(
            check_id="risk",
            label="리스크",
            status=CheckStatus.blocker if request.blocker_count else CheckStatus.warning if request.warning_count else CheckStatus.ok,
            evidence=f"blocker {request.blocker_count}개, warning {request.warning_count}개",
            reviewer_action="blocker가 있으면 승인 대신 보류 응답을 남기세요.",
        ),
    ]
    if request.watchouts:
        checks.append(
            ReviewerRiskCheck(
                check_id="watchouts",
                label="남은 확인점",
                status=CheckStatus.warning,
                evidence=", ".join(request.watchouts[:4]),
                reviewer_action="구매자가 설명하지 못하는 watchout은 승인 조건에 넣으세요.",
            )
        )
    return checks


def _budget_status(request: ReviewerQuickCardRequest) -> CheckStatus:
    if request.final_price_krw is None or request.budget_krw is None:
        return CheckStatus.warning
    return CheckStatus.ok if request.final_price_krw <= request.budget_krw else CheckStatus.blocker


def _budget_evidence(request: ReviewerQuickCardRequest) -> str:
    if request.final_price_krw is None or request.budget_krw is None:
        return "가격 또는 예산이 빠져 있습니다."
    delta = request.final_price_krw - request.budget_krw
    if delta <= 0:
        return f"예산보다 {abs(delta):,}원 낮거나 같습니다."
    return f"예산보다 {delta:,}원 높습니다."


def _reviewer_questions(request: ReviewerQuickCardRequest) -> list[str]:
    questions = [
        "최종 결제 화면에서 상품명, 옵션명, 판매자, 총액이 같은가요?",
        "보증 기간, 국내 AS 주체, 반품 가능 기간을 캡처했나요?",
        "이 가격이 예산과 사용 목적을 동시에 만족하나요?",
    ]
    for item in request.watchouts[:3]:
        questions.append(f"{item} 리스크는 어떻게 닫았나요?")
    if request.missing_evidence:
        questions.append(f"{request.missing_evidence[0]} 증거를 먼저 보내줄 수 있나요?")
    return questions[:6]


def _required_evidence(request: ReviewerQuickCardRequest) -> list[str]:
    evidence = [
        "최종 결제 금액",
        "상품명/옵션명/판매자명",
        "보증/반품 조건",
        "배송 예정일",
    ]
    for item in request.missing_evidence:
        if item not in evidence:
            evidence.insert(0, item)
    return evidence[:6]


def _reply_templates(
    request: ReviewerQuickCardRequest,
    status: CheckStatus,
) -> list[str]:
    title = _title(request)
    if status == CheckStatus.blocker:
        return [
            f"{title}는 지금 결제하지 말자. blocker와 누락 증거가 닫히면 다시 볼게.",
            "예산/보증/반품 조건 중 하나라도 불명확하면 보류가 맞아.",
            "대체 후보 2개만 더 비교해서 다시 공유해줘.",
        ]
    if status == CheckStatus.warning:
        return [
            f"{title}는 조건부 승인. 최종 금액과 보증/반품 캡처를 먼저 보내줘.",
            "확인 증거가 오면 오늘 안에 승인할 수 있어.",
            "가격은 괜찮아 보여도 옵션명과 판매자명이 바뀌면 다시 검토하자.",
        ]
    return [
        f"{title} 구매 승인. 결제 직전 금액과 옵션명만 다시 확인해.",
        "예산과 용도에 맞아 보여. 구매 후 보증 등록까지 기록해줘.",
        "증거 캡처 남기고 진행해도 될 것 같아.",
    ]


def _analysis_prefill(
    request: ReviewerQuickCardRequest,
    status: CheckStatus,
) -> str:
    return (
        "SpecPilot AI 30초 검토 카드 기준으로 구매 결정을 점검해줘.\n"
        f"- 제품: {_title(request)}\n"
        f"- 구매자 판단: {request.buyer_decision}\n"
        f"- 최종가: {request.final_price_krw if request.final_price_krw is not None else '미입력'}\n"
        f"- 예산: {request.budget_krw if request.budget_krw is not None else '미입력'}\n"
        f"- 상태: {status.value}\n"
        f"- 누락 증거: {', '.join(request.missing_evidence) or '없음'}"
    )


def _share_copy(
    request: ReviewerQuickCardRequest,
    status: CheckStatus,
    score: int,
) -> str:
    return (
        "SpecPilot AI 30초 검토 카드\n"
        f"- 제품: {_title(request)}\n"
        f"- 상태/점수: {status.value} / {score}점\n"
        f"- 확인 기한: {request.review_deadline}\n"
        f"- 빠른 응답: 승인 / 증거 요청 / 반대 중 하나로 답해주세요."
    )


def _next_actions(status: CheckStatus) -> list[str]:
    if status == CheckStatus.blocker:
        return [
            "반대/보류 응답을 받은 뒤 대체 후보 rescue로 넘어갑니다.",
            "blocker 증거가 닫히면 구매 결정 방어 브리프를 다시 만듭니다.",
            "예산 초과라면 예산/조건 스트레스 테스트를 먼저 실행합니다.",
        ]
    if status == CheckStatus.warning:
        return [
            "증거 요청 템플릿을 구매자에게 보냅니다.",
            "누락 증거가 도착하면 체크아웃 잠금으로 최종 확인합니다.",
            "조건부 승인 문구를 가족/팀 채널에 고정합니다.",
        ]
    return [
        "승인 응답을 구매 실행 패키지의 reviewer gate에 붙입니다.",
        "결제 직전 최종 금액과 옵션명을 다시 캡처합니다.",
        "구매 후 첫 부팅/보증 등록 체크로 넘어갑니다.",
    ]
