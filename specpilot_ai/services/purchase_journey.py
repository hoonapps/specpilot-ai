from datetime import UTC, datetime

from specpilot_ai.core.models import (
    CheckStatus,
    FinalDecisionKitRequest,
    PublicPurchaseJourneyKit,
    PurchaseJourneyKitRequest,
    PurchaseJourneyRouteCard,
    PurchaseJourneyStep,
    PurchaseQuestionTriageRequest,
    ReviewRiskRequest,
)

RISK_TERMS = [
    "리퍼",
    "전시",
    "중고",
    "해외",
    "병행",
    "반품 불가",
    "반품불가",
    "as 불가",
    "AS 불가",
]
SPEC_TERMS = ["rtx", "radeon", "core", "ryzen", "ram", "ssd", "프리도스", "freedos", "tgp"]
REVIEW_TERMS = ["발열", "소음", "팬", "불량", "꺼짐", "빛샘", "as", "AS", "배터리"]


def build_public_purchase_journey_kit(
    request: PurchaseJourneyKitRequest,
    generated_at: datetime | None = None,
) -> PublicPurchaseJourneyKit:
    generated_at = generated_at or datetime.now(UTC)
    title = _title(request)
    combined_text = " ".join(
        [request.buyer_question, request.product_title, request.listing_text, " ".join(request.review_snippets)]
    )
    required_inputs = _required_inputs(request, combined_text)
    blockers = _blockers(request, combined_text)
    warnings = _warnings(request, combined_text, required_inputs)
    status = _status(blockers, warnings)
    score = _score(blockers, warnings, required_inputs, request)
    triage_prefill = _triage_prefill(request, title)
    review_prefill = _review_prefill(request, title)
    final_prefill = _final_decision_prefill(request, title, status, blockers, warnings)
    steps = _steps(request, status, required_inputs, blockers, warnings)

    return PublicPurchaseJourneyKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        product_title=title,
        seller_name=_seller(request),
        journey_status=status,
        journey_score=score,
        current_stage=_current_stage(request, required_inputs, blockers, warnings),
        headline=_headline(title, status),
        summary=_summary(request, score, blockers, warnings, required_inputs),
        primary_action=_primary_action(status, steps),
        steps=steps,
        route_cards=_route_cards(steps),
        required_inputs=required_inputs,
        safety_rules=_safety_rules(status),
        triage_prefill=triage_prefill,
        review_risk_prefill=review_prefill,
        final_decision_prefill=final_prefill,
        analysis_prefill=_analysis_prefill(request, score, blockers, warnings),
        share_copy=_share_copy(request, status, score, steps),
        next_actions=_next_actions(status),
    )


def _title(request: PurchaseJourneyKitRequest) -> str:
    return request.product_title.strip() or "구매 후보"


def _seller(request: PurchaseJourneyKitRequest) -> str:
    return request.seller_name.strip() or "판매자"


def _lines(items: list[str], limit: int = 10) -> list[str]:
    return [item.strip() for item in items if item.strip()][:limit]


def _required_inputs(request: PurchaseJourneyKitRequest, text: str) -> list[str]:
    required: list[str] = []
    if len(request.buyer_question.strip()) < 8:
        required.append("무엇을 결정하려는지 담긴 자연어 구매 질문")
    if len(request.listing_text.strip()) < 40:
        required.append("판매 페이지 상품명, 옵션명, 보증/반품 문구")
    if request.final_price_krw is None:
        required.append("배송비, 쿠폰, 카드 할인이 반영된 최종 결제 금액")
    if not request.review_snippets:
        required.append("반복 불만을 확인할 후기 문구 3개 이상")
    if not any(term.lower() in text.lower() for term in SPEC_TERMS):
        required.append("CPU/GPU/RAM/SSD 또는 노트북 핵심 사양")
    if not any(term in text for term in ["반품", "교환", "보증", "AS", "as"]):
        required.append("반품, 교환, 국내 AS, 보증 기간 문구")
    return list(dict.fromkeys(required))[:8]


def _blockers(request: PurchaseJourneyKitRequest, text: str) -> list[str]:
    blockers = [item for item in _lines(request.missing_evidence) if "반품 불가" in item or "AS 불가" in item]
    blockers.extend(term for term in RISK_TERMS if term.lower() in text.lower())
    if request.final_price_krw is not None and request.final_price_krw > request.budget_krw * 1.08:
        blockers.append("최종가가 예산보다 8% 이상 높습니다.")
    return list(dict.fromkeys(blockers))[:8]


def _warnings(
    request: PurchaseJourneyKitRequest,
    text: str,
    required_inputs: list[str],
) -> list[str]:
    warnings = [f"누락 입력: {item}" for item in required_inputs]
    warnings.extend(f"누락 증거: {item}" for item in _lines(request.missing_evidence))
    if request.final_price_krw is not None and request.final_price_krw > request.budget_krw:
        warnings.append("최종가가 예산을 초과합니다.")
    review_hits = [term for term in REVIEW_TERMS if term in text]
    if review_hits:
        warnings.append(f"후기 리스크 문구 확인 필요: {', '.join(review_hits[:4])}")
    if len(_lines(request.ready_evidence)) < 3:
        warnings.append("결제 전 증거 캡처가 3개 미만입니다.")
    return list(dict.fromkeys(warnings))[:10]


def _status(blockers: list[str], warnings: list[str]) -> CheckStatus:
    if blockers:
        return CheckStatus.blocker
    if warnings:
        return CheckStatus.warning
    return CheckStatus.ok


def _score(
    blockers: list[str],
    warnings: list[str],
    required_inputs: list[str],
    request: PurchaseJourneyKitRequest,
) -> int:
    score = 100
    score -= len(blockers) * 18
    score -= len(warnings) * 7
    score -= len(required_inputs) * 4
    score += min(12, len(_lines(request.ready_evidence)) * 3)
    if blockers:
        score = min(score, 54)
    elif warnings or required_inputs:
        score = min(score, 86)
    return max(0, min(100, score))


def _current_stage(
    request: PurchaseJourneyKitRequest,
    required_inputs: list[str],
    blockers: list[str],
    warnings: list[str],
) -> str:
    stage = request.purchase_stage.strip().lower()
    if blockers:
        return "blocked_risk_review"
    if required_inputs:
        return "evidence_collection"
    if stage in {"checkout", "cart"} or warnings:
        return "final_decision"
    return "ready_to_execute"


def _step(
    order: int,
    step_id: str,
    label: str,
    status: CheckStatus,
    kit_path: str,
    why_now: str,
    required_input: str,
    success_rule: str,
    next_action: str,
) -> PurchaseJourneyStep:
    return PurchaseJourneyStep(
        step_id=step_id,
        label=label,
        status=status,
        order=order,
        kit_path=kit_path,
        why_now=why_now,
        required_input=required_input,
        success_rule=success_rule,
        next_action=next_action,
    )


def _steps(
    request: PurchaseJourneyKitRequest,
    status: CheckStatus,
    required_inputs: list[str],
    blockers: list[str],
    warnings: list[str],
) -> list[PurchaseJourneyStep]:
    evidence_status = CheckStatus.warning if required_inputs else CheckStatus.ok
    risk_status = CheckStatus.blocker if blockers else CheckStatus.warning if warnings else CheckStatus.ok
    final_status = CheckStatus.blocker if blockers else CheckStatus.warning if warnings else CheckStatus.ok
    execution_status = CheckStatus.ok if status == CheckStatus.ok else CheckStatus.warning
    return [
        _step(
            1,
            "question_triage",
            "질문 라우팅",
            CheckStatus.ok,
            "/public/purchase-question-triage-kit",
            "처음 온 사용자의 질문을 가격, 사양, 보증, 결제 전 검수 흐름으로 분류합니다.",
            "자연어 구매 질문",
            "다음 실행 키트가 2개 이상 제안되어야 합니다.",
            "질문을 정리하고 상품명/장바구니 문구를 붙여 넣으세요.",
        ),
        _step(
            2,
            "listing_and_cart",
            "상품명/장바구니 증거 확보",
            evidence_status,
            "/public/listing-decoder-kit",
            "모델명, 옵션명, CPU/GPU/RAM/SSD, 리퍼/해외 조건을 먼저 구조화합니다.",
            required_inputs[0] if required_inputs else "상품명, 옵션명, 최종가, 보증/반품 문구",
            "최종가와 핵심 사양, 보증/반품 문구가 캡처되어야 합니다.",
            "상품 페이지 근거와 장바구니 인테이크로 증거를 보강하세요.",
        ),
        _step(
            3,
            "review_and_policy",
            "후기/보증 리스크 검수",
            risk_status,
            "/public/review-risk-kit",
            "반복 불만과 보증/반품 조건이 결제 후 만족도와 환불 가능성을 좌우합니다.",
            "후기 문구, 반품/교환, 국내 AS, 보증 주체",
            "blocker성 후기/정책 문구가 판매자 답변으로 닫혀야 합니다.",
            "리뷰 리스크와 보증/반품 검수를 실행하세요.",
        ),
        _step(
            4,
            "final_decision",
            "최종 구매 판정",
            final_status,
            "/public/final-decision-kit",
            "가격, 체크아웃, 호환성, 리뷰, 보증, 증거를 go/verify/hold로 압축합니다.",
            "최종가, 준비 증거, 누락 증거, 판매자 질문",
            "go 또는 blocker 0개 verify 상태가 되어야 합니다.",
            "최종 판정으로 실행 여부를 결정하세요.",
        ),
        _step(
            5,
            "execution_and_review",
            "구매 실행/공유 검토",
            execution_status,
            "/public/purchase-execution-kit",
            "결제 버튼 직전에는 실행 순서와 가족/팀/커뮤니티 검토 루프가 필요합니다.",
            "결정 마감, 공유 대상, 판매자 답변",
            "중단 조건과 증거 게이트가 공유 문구에 포함되어야 합니다.",
            "구매 실행 패키지와 30초 검토 카드로 넘기세요.",
        ),
    ]


def _route_cards(steps: list[PurchaseJourneyStep]) -> list[PurchaseJourneyRouteCard]:
    return [
        PurchaseJourneyRouteCard(
            route_id=step.step_id,
            label=step.label,
            status=step.status,
            cta_label=f"{step.label} 실행",
            cta_path=step.kit_path,
            prefill_hint=step.required_input,
        )
        for step in steps
    ]


def _triage_prefill(
    request: PurchaseJourneyKitRequest,
    title: str,
) -> PurchaseQuestionTriageRequest:
    return PurchaseQuestionTriageRequest(
        category=request.category,
        buyer_question=request.buyer_question,
        product_title=title,
        listing_text=request.listing_text,
        cart_total_krw=request.final_price_krw,
        budget_krw=request.budget_krw,
        purchase_stage=request.purchase_stage,
        source="purchase_journey",
    )


def _review_prefill(request: PurchaseJourneyKitRequest, title: str) -> ReviewRiskRequest:
    return ReviewRiskRequest(
        category=request.category,
        product_title=title,
        review_snippets=request.review_snippets,
        budget_krw=request.budget_krw,
        usage_context="journey_review",
        source="purchase_journey",
    )


def _final_decision_prefill(
    request: PurchaseJourneyKitRequest,
    title: str,
    status: CheckStatus,
    blockers: list[str],
    warnings: list[str],
) -> FinalDecisionKitRequest:
    evidence_status = CheckStatus.warning if request.missing_evidence or warnings else CheckStatus.ok
    review_text = " ".join(request.review_snippets)
    review_status = (
        CheckStatus.warning
        if not request.review_snippets or any(term in review_text for term in REVIEW_TERMS)
        else CheckStatus.ok
    )
    return FinalDecisionKitRequest(
        category=request.category,
        product_title=title,
        seller_name=_seller(request),
        budget_krw=request.budget_krw,
        final_price_krw=request.final_price_krw,
        selected_reason=request.buyer_question,
        price_status=CheckStatus.warning
        if request.final_price_krw is None or (request.final_price_krw > request.budget_krw)
        else CheckStatus.ok,
        compatibility_status=CheckStatus.warning if "사양" in " ".join(warnings) else CheckStatus.ok,
        review_status=review_status,
        warranty_status=CheckStatus.blocker if blockers else CheckStatus.warning,
        checkout_status=status,
        evidence_status=evidence_status,
        price_score=76 if request.final_price_krw is not None else 58,
        compatibility_score=74,
        review_score=68 if request.review_snippets else 52,
        warranty_score=45 if blockers else 70,
        checkout_score=55 if status == CheckStatus.blocker else 72 if status == CheckStatus.warning else 88,
        ready_evidence=request.ready_evidence,
        missing_evidence=request.missing_evidence or warnings[:4],
        blocker_reasons=blockers,
        warning_reasons=warnings,
        seller_questions=[
            "최종 출고 사양이 장바구니 옵션명과 동일한가요?",
            "초기 불량이면 개봉 후에도 교환 또는 반품이 가능한가요?",
            "국내 AS 주체와 보증 기간을 주문서에 명시할 수 있나요?",
        ],
        decision_deadline=request.urgency,
        share_audience=request.share_audience,
        source="purchase_journey",
    )


def _headline(title: str, status: CheckStatus) -> str:
    if status == CheckStatus.blocker:
        return f"{title} 구매 여정은 차단 리스크부터 닫아야 합니다."
    if status == CheckStatus.warning:
        return f"{title} 구매 여정은 증거 보강 후 최종 판정으로 넘어가야 합니다."
    return f"{title} 구매 여정은 실행 직전 단계까지 준비됐습니다."


def _summary(
    request: PurchaseJourneyKitRequest,
    score: int,
    blockers: list[str],
    warnings: list[str],
    required_inputs: list[str],
) -> str:
    price = f"{request.final_price_krw:,}원" if request.final_price_krw is not None else "최종가 미입력"
    return (
        f"여정 점수 {score}점, 최종가 {price}, blocker {len(blockers)}개, "
        f"warning {len(warnings)}개, 누락 입력 {len(required_inputs)}개입니다. "
        "질문 라우팅부터 최종 판정과 공유 검토까지 한 번에 이어집니다."
    )


def _primary_action(status: CheckStatus, steps: list[PurchaseJourneyStep]) -> str:
    if status == CheckStatus.blocker:
        return "차단 리스크가 있는 단계부터 실행하고 결제를 보류하세요."
    if status == CheckStatus.warning:
        warning_step = next((step for step in steps if step.status == CheckStatus.warning), steps[0])
        return f"{warning_step.label}부터 보강한 뒤 최종 구매 판정으로 넘어가세요."
    return "최종 구매 판정과 구매 실행 패키지로 결제 직전 증거를 고정하세요."


def _safety_rules(status: CheckStatus) -> list[str]:
    rules = [
        "최종가, 옵션명, 반품/AS 조건이 캡처되지 않으면 바로 결제하지 않습니다.",
        "리퍼, 전시, 해외, 반품 불가, AS 불가 문구가 있으면 판매자 답변 전까지 hold입니다.",
        "후기 반복 불만이 목적 사용과 직접 충돌하면 가격보다 보증/반품 조건을 우선합니다.",
    ]
    if status == CheckStatus.ok:
        rules.append("go 상태여도 결제 후 구매 후 케어와 첫 부팅 검수로 결과를 닫습니다.")
    return rules


def _analysis_prefill(
    request: PurchaseJourneyKitRequest,
    score: int,
    blockers: list[str],
    warnings: list[str],
) -> str:
    return (
        f"{_title(request)} 구매 여정을 점검해줘. 질문={request.buyer_question}, "
        f"예산={request.budget_krw:,}원, 최종가={request.final_price_krw or '미입력'}, "
        f"여정 점수={score}, blocker={blockers[:3]}, warning={warnings[:3]}. "
        "상품명/장바구니, 리뷰, 보증/반품, 최종 판정, 구매 실행 순서로 다음 행동을 정리해줘."
    )


def _share_copy(
    request: PurchaseJourneyKitRequest,
    status: CheckStatus,
    score: int,
    steps: list[PurchaseJourneyStep],
) -> str:
    label = "진행 가능" if status == CheckStatus.ok else "확인 필요" if status == CheckStatus.warning else "구매 보류"
    risky_steps = [step.label for step in steps if step.status != CheckStatus.ok]
    lines = [
        "SpecPilot AI 구매 여정",
        f"- 후보: {_title(request)}",
        f"- 상태: {label} ({score}점)",
        f"- 다음 단계: {', '.join(risky_steps[:3]) if risky_steps else '최종 판정과 실행'}",
        "결제 전 빠진 증거나 반대할 이유가 있으면 알려주세요.",
    ]
    return "\n".join(lines)


def _next_actions(status: CheckStatus) -> list[str]:
    if status == CheckStatus.blocker:
        return [
            "차단 리스크 단계의 판매자 질문을 먼저 복사하세요.",
            "보증/반품 또는 상품명 해석 결과가 닫히기 전까지 결제하지 마세요.",
            "대체 후보 비교로 같은 예산의 안전 후보를 확인하세요.",
        ]
    if status == CheckStatus.warning:
        return [
            "누락 입력을 채운 뒤 리뷰 리스크와 최종 판정을 실행하세요.",
            "결정 마감 전 30초 검토 카드로 반대 의견을 받으세요.",
            "최종가가 바뀌면 가격 신뢰 키트를 다시 실행하세요.",
        ]
    return [
        "최종 판정 결과를 구매 실행 패키지로 넘기세요.",
        "결제 화면 캡처 후 구매 후 케어를 예약하세요.",
        "실제 구매 결과를 공유 카드로 남기세요.",
    ]
