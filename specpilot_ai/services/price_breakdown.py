from datetime import UTC, datetime

from specpilot_ai.core.models import (
    CheckStatus,
    PriceBreakdownLine,
    PriceBreakdownRequest,
    PublicPriceBreakdownKit,
)


def build_public_price_breakdown_kit(
    request: PriceBreakdownRequest,
    generated_at: datetime | None = None,
) -> PublicPriceBreakdownKit:
    generated_at = generated_at or datetime.now(UTC)
    subtotal = request.listed_price_krw * request.quantity
    additions = request.shipping_fee_krw + request.assembly_fee_krw + request.os_fee_krw
    discounts = request.coupon_discount_krw + request.card_discount_krw + request.point_rebate_krw
    effective_price = max(0, subtotal + additions - discounts)
    per_unit_price = round(effective_price / request.quantity)
    budget_delta = effective_price - request.budget_krw if request.budget_krw is not None else None
    report_delta = (
        effective_price - request.expected_report_price_krw
        if request.expected_report_price_krw is not None
        else None
    )
    risk_flags = _risk_flags(request, effective_price, budget_delta, report_delta)
    score = _score(request, risk_flags, budget_delta, report_delta)
    priority = _priority(score, risk_flags, budget_delta)
    return PublicPriceBreakdownKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        product_title=_title(request),
        seller_name=_seller(request),
        priority=priority,
        price_score=score,
        subtotal_krw=subtotal,
        effective_price_krw=effective_price,
        per_unit_price_krw=per_unit_price,
        budget_delta_krw=budget_delta,
        report_price_delta_krw=report_delta,
        headline=_headline(request, priority, effective_price),
        summary=_summary(request, priority, effective_price, budget_delta, report_delta),
        price_lines=_price_lines(request, subtotal, effective_price),
        risk_flags=risk_flags,
        seller_questions=_seller_questions(request, risk_flags),
        evidence_checklist=_evidence_checklist(request),
        analysis_prefill=_analysis_prefill(request, priority, effective_price, budget_delta, report_delta),
        share_copy=_share_copy(request, priority, effective_price, budget_delta, report_delta),
        next_actions=_next_actions(priority, risk_flags),
    )


def _title(request: PriceBreakdownRequest) -> str:
    return request.product_title.strip() or "구매 후보"


def _seller(request: PriceBreakdownRequest) -> str:
    return request.seller_name.strip() or "판매자"


def _risk_text(request: PriceBreakdownRequest) -> str:
    return " ".join(request.risk_terms).lower()


def _risk_flags(
    request: PriceBreakdownRequest,
    effective_price: int,
    budget_delta: int | None,
    report_delta: int | None,
) -> list[str]:
    flags: list[str] = []
    if budget_delta is not None and budget_delta > 0:
        flags.append(f"최종 실구매가가 예산보다 {budget_delta:,}원 높습니다.")
    if report_delta is not None and report_delta > 50_000:
        flags.append(f"리포트 예상가보다 최종 결제 금액이 {report_delta:,}원 높습니다.")
    if request.shipping_fee_krw > 50_000:
        flags.append("배송비가 높아 표시가와 실구매가 차이가 큽니다.")
    if request.assembly_fee_krw + request.os_fee_krw > 120_000:
        flags.append("조립비 또는 OS 비용이 총액에 크게 반영됩니다.")
    if request.coupon_discount_krw + request.card_discount_krw > effective_price * 0.08:
        flags.append("쿠폰/카드 할인 의존도가 높아 결제 단계에서 가격이 바뀔 수 있습니다.")
    if request.discount_expires_hours is not None and request.discount_expires_hours <= 24:
        flags.append("할인 만료가 24시간 이내입니다.")
    if request.stock_count is not None and request.stock_count <= 3:
        flags.append("재고가 적어 판매자/옵션 변경 가능성이 있습니다.")
    text = _risk_text(request)
    if any(term in text for term in ("청구 할인", "조건부", "앱전용", "회원전용", "타임딜", "선착순")):
        flags.append("조건부 할인 문구가 있어 결제 화면 캡처가 필요합니다.")
    if not flags:
        flags.append("현재 입력 기준 표시가와 최종 실구매가 차이는 관리 가능한 수준입니다.")
    return flags[:8]


def _score(
    request: PriceBreakdownRequest,
    risk_flags: list[str],
    budget_delta: int | None,
    report_delta: int | None,
) -> int:
    score = 100
    if budget_delta is not None and budget_delta > 0:
        score -= 24 if budget_delta > max(50_000, request.listed_price_krw * 0.04) else 12
    if report_delta is not None and report_delta > 0:
        score -= 16 if report_delta > max(70_000, request.listed_price_krw * 0.04) else 8
    if request.shipping_fee_krw > 50_000:
        score -= 8
    if request.assembly_fee_krw + request.os_fee_krw > 120_000:
        score -= 8
    if request.discount_expires_hours is not None and request.discount_expires_hours <= 24:
        score -= 8
    if request.stock_count is not None and request.stock_count <= 3:
        score -= 8
    if any("조건부" in flag or "의존도" in flag for flag in risk_flags):
        score -= 8
    return max(0, min(100, score))


def _priority(score: int, risk_flags: list[str], budget_delta: int | None) -> CheckStatus:
    if score < 60 or (budget_delta is not None and budget_delta > 150_000):
        return CheckStatus.blocker
    if score < 84 or any("높" in flag or "만료" in flag or "조건부" in flag for flag in risk_flags):
        return CheckStatus.warning
    return CheckStatus.ok


def _price_lines(
    request: PriceBreakdownRequest,
    subtotal: int,
    effective_price: int,
) -> list[PriceBreakdownLine]:
    return [
        PriceBreakdownLine(
            line_id="listed_subtotal",
            label="표시가 합계",
            amount_krw=subtotal,
            kind="base",
            explanation=f"표시가 {request.listed_price_krw:,}원 x {request.quantity}개입니다.",
        ),
        PriceBreakdownLine(
            line_id="shipping_fee",
            label="배송비",
            amount_krw=request.shipping_fee_krw,
            kind="add",
            explanation="최종 결제 화면에 더해지는 배송비입니다.",
        ),
        PriceBreakdownLine(
            line_id="assembly_os_fee",
            label="조립/OS 비용",
            amount_krw=request.assembly_fee_krw + request.os_fee_krw,
            kind="add",
            explanation="조립비와 OS 포함 비용입니다.",
        ),
        PriceBreakdownLine(
            line_id="coupon_card_discount",
            label="쿠폰/카드 할인",
            amount_krw=-(request.coupon_discount_krw + request.card_discount_krw),
            kind="discount",
            explanation="즉시 할인, 쿠폰, 카드 청구 할인 합계입니다.",
        ),
        PriceBreakdownLine(
            line_id="point_rebate",
            label="포인트 환급",
            amount_krw=-request.point_rebate_krw,
            kind="discount",
            explanation="구매 후 돌려받는 포인트나 적립금입니다.",
        ),
        PriceBreakdownLine(
            line_id="effective_price",
            label="최종 실구매가",
            amount_krw=effective_price,
            kind="total",
            explanation="표시가, 추가 비용, 할인, 포인트를 반영한 결제 판단 금액입니다.",
        ),
    ]


def _seller_questions(request: PriceBreakdownRequest, risk_flags: list[str]) -> list[str]:
    questions = [
        "최종 결제 화면에서 배송비, 조립비, OS 비용, 쿠폰, 카드 할인이 모두 반영된 금액이 맞나요?",
        "쿠폰/카드 할인이 특정 카드, 앱, 회원 등급, 청구 할인 조건에 묶여 있나요?",
        "결제 직전 옵션이나 판매자가 바뀌면 같은 가격과 같은 사양이 유지되나요?",
        "할인 만료 시각과 남은 재고 수량을 확인할 수 있나요?",
    ]
    if any("예산" in flag or "리포트" in flag for flag in risk_flags):
        questions.append("리포트 예상가보다 높아진 항목이 배송비, 옵션, 할인 종료 중 무엇인지 설명해 주세요.")
    return questions


def _evidence_checklist(request: PriceBreakdownRequest) -> list[str]:
    return [
        "최종 결제 화면의 총액 캡처",
        "배송비, 조립비, OS 포함 여부 캡처",
        "쿠폰/카드 할인 적용 조건과 만료 시각 캡처",
        "판매자명, 옵션명, 수량, 재고 상태 캡처",
        "리포트 예상가와 최종 결제 금액 차이 메모",
    ]


def _headline(request: PriceBreakdownRequest, priority: CheckStatus, effective_price: int) -> str:
    if priority == CheckStatus.blocker:
        return f"{_title(request)}는 최종 실구매가 {effective_price:,}원 기준으로 결제를 멈춰야 합니다."
    if priority == CheckStatus.warning:
        return f"{_title(request)}는 최종 실구매가 {effective_price:,}원과 할인 조건을 재확인하세요."
    return f"{_title(request)}는 최종 실구매가 기준으로도 예산 방어가 가능합니다."


def _summary(
    request: PriceBreakdownRequest,
    priority: CheckStatus,
    effective_price: int,
    budget_delta: int | None,
    report_delta: int | None,
) -> str:
    budget = "예산 미입력" if budget_delta is None else f"예산 대비 {budget_delta:+,}원"
    report = "리포트 예상가 미입력" if report_delta is None else f"리포트 예상가 대비 {report_delta:+,}원"
    return f"{_seller(request)} 기준 최종 실구매가 {effective_price:,}원, {budget}, {report}. 상태 {priority.value}."


def _analysis_prefill(
    request: PriceBreakdownRequest,
    priority: CheckStatus,
    effective_price: int,
    budget_delta: int | None,
    report_delta: int | None,
) -> str:
    return (
        f"'{_title(request)}'의 최종 실구매가를 기준으로 구매해도 되는지 분석해줘. "
        f"판매자 {_seller(request)}, 표시가 {request.listed_price_krw}, 수량 {request.quantity}, "
        f"배송비 {request.shipping_fee_krw}, 조립/OS {request.assembly_fee_krw + request.os_fee_krw}, "
        f"쿠폰/카드/포인트 할인 {request.coupon_discount_krw + request.card_discount_krw + request.point_rebate_krw}, "
        f"최종 실구매가 {effective_price}, 예산 차이 {budget_delta}, 리포트 가격 차이 {report_delta}, 상태 {priority.value}."
    )


def _share_copy(
    request: PriceBreakdownRequest,
    priority: CheckStatus,
    effective_price: int,
    budget_delta: int | None,
    report_delta: int | None,
) -> str:
    budget = "미입력" if budget_delta is None else f"{budget_delta:+,}원"
    report = "미입력" if report_delta is None else f"{report_delta:+,}원"
    return (
        "SpecPilot AI 실구매가 분해\n"
        f"제품: {_title(request)}\n"
        f"판매자: {_seller(request)}\n"
        f"상태: {priority.value}\n"
        f"최종 실구매가: {effective_price:,}원\n"
        f"예산 차이: {budget}\n"
        f"리포트 예상가 차이: {report}"
    )


def _next_actions(priority: CheckStatus, risk_flags: list[str]) -> list[str]:
    if priority == CheckStatus.blocker:
        return [
            "예산 초과나 리포트 예상가 대비 상승 원인을 확인하기 전 결제를 보류하세요.",
            "배송비, 조립비, OS 비용, 쿠폰 종료, 카드 조건 중 가격을 올린 항목을 캡처하세요.",
            "대체 후보 rescue 또는 후보 비교 스냅샷에서 같은 예산의 대안을 확인하세요.",
        ]
    if priority == CheckStatus.warning:
        return [
            risk_flags[0],
            "쿠폰/카드 할인 조건과 최종 결제 화면을 같은 캡처에 남기세요.",
            "목표가 감시 키트에 최종 실구매가 기준을 업데이트하세요.",
        ]
    return [
        "최종 실구매가 캡처를 구매 승인 브리프에 붙이세요.",
        "결제 전 옵션/사양 빠른 검수에서 같은 총액인지 다시 대조하세요.",
        "구매 후 케어에서 실제 결제 금액을 저장해 추천 품질에 반영하세요.",
    ]
