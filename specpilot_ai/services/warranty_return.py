from datetime import UTC, datetime

from specpilot_ai.core.models import (
    Category,
    CheckStatus,
    PublicWarrantyReturnKit,
    WarrantyReturnCheck,
    WarrantyReturnCostLine,
    WarrantyReturnRequest,
)


def build_public_warranty_return_kit(
    request: WarrantyReturnRequest,
    generated_at: datetime | None = None,
) -> PublicWarrantyReturnKit:
    generated_at = generated_at or datetime.now(UTC)
    checks = _policy_checks(request)
    estimated_return_cost = _estimated_return_cost(request)
    score = _score(request, checks, estimated_return_cost)
    priority = _priority(score, checks)
    return PublicWarrantyReturnKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        product_title=_title(request),
        seller_name=_seller(request),
        priority=priority,
        protection_score=score,
        estimated_return_cost_krw=estimated_return_cost,
        headline=_headline(request, priority),
        summary=_summary(request, priority, score, estimated_return_cost),
        policy_checks=checks,
        cost_lines=_cost_lines(request, estimated_return_cost),
        seller_questions=_seller_questions(request, checks),
        evidence_checklist=_evidence_checklist(request),
        buyer_message=_buyer_message(request, priority, estimated_return_cost),
        analysis_prefill=_analysis_prefill(request, priority, score, estimated_return_cost),
        share_copy=_share_copy(request, priority, score, estimated_return_cost),
        next_actions=_next_actions(priority, checks),
    )


def _title(request: WarrantyReturnRequest) -> str:
    return request.product_title.strip() or ("노트북 구매 후보" if request.category == Category.laptop else "컴퓨터 구매 후보")


def _seller(request: WarrantyReturnRequest) -> str:
    return request.seller_name.strip() or "판매자"


def _policy_text(request: WarrantyReturnRequest) -> str:
    return " ".join([request.policy_text, *request.risk_terms]).lower()


def _has_risk_term(request: WarrantyReturnRequest, terms: tuple[str, ...]) -> bool:
    text = _policy_text(request)
    return any(term.lower() in text for term in terms)


def _policy_checks(request: WarrantyReturnRequest) -> list[WarrantyReturnCheck]:
    checks: list[WarrantyReturnCheck] = []

    if request.return_window_days <= 0 or _has_risk_term(request, ("반품 불가", "환불 불가", "no return", "no refund")):
        checks.append(
            WarrantyReturnCheck(
                check_id="return_window",
                label="반품 가능 기간",
                status=CheckStatus.blocker,
                finding="반품 가능 기간이 없거나 반품 불가 조건이 감지되었습니다.",
                recommendation="단순 변심과 사양 불일치 반품 가능 여부를 결제 전 서면으로 확인하세요.",
            )
        )
    elif request.return_window_days < 7:
        checks.append(
            WarrantyReturnCheck(
                check_id="return_window",
                label="반품 가능 기간",
                status=CheckStatus.warning,
                finding=f"반품 가능 기간이 {request.return_window_days}일로 짧습니다.",
                recommendation="배송 지연과 초기 테스트 시간을 고려해 최소 7일 이상인지 확인하세요.",
            )
        )
    else:
        checks.append(
            WarrantyReturnCheck(
                check_id="return_window",
                label="반품 가능 기간",
                status=CheckStatus.ok,
                finding=f"반품 가능 기간 {request.return_window_days}일이 입력되었습니다.",
                recommendation="마감일 전 첫 부팅과 사양 검수를 완료하세요.",
            )
        )

    if request.dead_on_arrival_days <= 0:
        status = CheckStatus.blocker
        finding = "초기 불량 교환 기간이 확인되지 않았습니다."
    elif request.dead_on_arrival_days < 7:
        status = CheckStatus.warning
        finding = f"초기 불량 교환 기간이 {request.dead_on_arrival_days}일로 짧습니다."
    else:
        status = CheckStatus.ok
        finding = f"초기 불량 교환 기간 {request.dead_on_arrival_days}일이 입력되었습니다."
    checks.append(
        WarrantyReturnCheck(
            check_id="dead_on_arrival",
            label="초기 불량 교환",
            status=status,
            finding=finding,
            recommendation="전원, 화면, 포트, 소음, 벤치마크 기준값을 수령 첫날 캡처하세요.",
        )
    )

    if request.opened_box_return_allowed is False or _has_risk_term(request, ("개봉 후 반품 불가", "개봉시 반품 불가", "opened box no return")):
        checks.append(
            WarrantyReturnCheck(
                check_id="opened_box",
                label="개봉 후 반품",
                status=CheckStatus.warning,
                finding="개봉 후 반품 제한 조건이 있습니다.",
                recommendation="사양 불일치, 초기 불량, 배송 파손은 예외 반품인지 판매자 답변을 캡처하세요.",
            )
        )
    elif request.opened_box_return_allowed is True:
        checks.append(
            WarrantyReturnCheck(
                check_id="opened_box",
                label="개봉 후 반품",
                status=CheckStatus.ok,
                finding="개봉 후에도 조건부 반품 가능으로 입력되었습니다.",
                recommendation="포장 훼손 범위와 구성품 누락 기준을 함께 확인하세요.",
            )
        )
    else:
        checks.append(
            WarrantyReturnCheck(
                check_id="opened_box",
                label="개봉 후 반품",
                status=CheckStatus.warning,
                finding="개봉 후 반품 가능 여부가 불명확합니다.",
                recommendation="초기 테스트를 위해 개봉해야 하는 컴퓨터/노트북 특성을 설명하고 예외 기준을 확인하세요.",
            )
        )

    provider = request.warranty_provider.lower()
    if any(term in provider for term in ("unknown", "seller", "importer", "병행", "해외")) or _has_risk_term(
        request,
        ("해외 as", "병행", "판매자 as", "as 불가", "보증 없음"),
    ):
        status = CheckStatus.blocker if _has_risk_term(request, ("as 불가", "보증 없음")) else CheckStatus.warning
        finding = f"보증 주체가 '{request.warranty_provider}'로 공식 제조사 보증인지 불명확합니다."
    elif request.warranty_months < 12:
        status = CheckStatus.warning
        finding = f"보증 기간이 {request.warranty_months}개월로 짧습니다."
    else:
        status = CheckStatus.ok
        finding = f"보증 기간 {request.warranty_months}개월과 보증 주체가 입력되었습니다."
    checks.append(
        WarrantyReturnCheck(
            check_id="warranty_provider",
            label="보증 주체",
            status=status,
            finding=finding,
            recommendation="제조사 시리얼 조회, 국내 AS 접수처, 영수증 양도 가능 여부를 확인하세요.",
        )
    )

    if request.warranty_transferable is False:
        checks.append(
            WarrantyReturnCheck(
                check_id="warranty_transfer",
                label="보증 승계",
                status=CheckStatus.warning,
                finding="보증 승계가 불가한 조건입니다.",
                recommendation="재판매 가치와 팀 장비 인수인계에 불리하므로 총소유비용에 반영하세요.",
            )
        )
    elif request.warranty_transferable is True:
        checks.append(
            WarrantyReturnCheck(
                check_id="warranty_transfer",
                label="보증 승계",
                status=CheckStatus.ok,
                finding="보증 승계 가능으로 입력되었습니다.",
                recommendation="양도 시 필요한 영수증과 시리얼 증거를 보관하세요.",
            )
        )
    else:
        checks.append(
            WarrantyReturnCheck(
                check_id="warranty_transfer",
                label="보증 승계",
                status=CheckStatus.warning,
                finding="보증 승계 가능 여부가 미확인입니다.",
                recommendation="중고 판매나 팀 내 재배정 가능성이 있으면 승계 기준을 확인하세요.",
            )
        )

    if request.return_shipping_fee_krw > 80_000 or request.restocking_fee_percent >= 10:
        checks.append(
            WarrantyReturnCheck(
                check_id="return_cost",
                label="반품 비용",
                status=CheckStatus.warning,
                finding="반품 배송비나 재입고 수수료가 큽니다.",
                recommendation="사양 불일치와 초기 불량일 때 구매자 부담 비용이 면제되는지 확인하세요.",
            )
        )
    else:
        checks.append(
            WarrantyReturnCheck(
                check_id="return_cost",
                label="반품 비용",
                status=CheckStatus.ok,
                finding="반품 비용이 공개 기준 안에 있습니다.",
                recommendation="왕복 배송비 부담 주체와 환불 처리 기한을 캡처하세요.",
            )
        )

    return checks


def _estimated_return_cost(request: WarrantyReturnRequest) -> int:
    restocking = round(request.purchase_price_krw * request.restocking_fee_percent / 100)
    return request.return_shipping_fee_krw + restocking


def _score(
    request: WarrantyReturnRequest,
    checks: list[WarrantyReturnCheck],
    estimated_return_cost: int,
) -> int:
    score = 100
    score -= sum(24 for check in checks if check.status == CheckStatus.blocker)
    score -= sum(10 for check in checks if check.status == CheckStatus.warning)
    if estimated_return_cost > request.purchase_price_krw * 0.05:
        score -= 10
    if request.return_window_days >= 14:
        score += 4
    if request.warranty_months >= 24:
        score += 4
    return max(0, min(100, score))


def _priority(score: int, checks: list[WarrantyReturnCheck]) -> CheckStatus:
    if score < 60 or any(check.status == CheckStatus.blocker for check in checks):
        return CheckStatus.blocker
    if score < 84 or any(check.status == CheckStatus.warning for check in checks):
        return CheckStatus.warning
    return CheckStatus.ok


def _cost_lines(request: WarrantyReturnRequest, estimated_return_cost: int) -> list[WarrantyReturnCostLine]:
    restocking = round(request.purchase_price_krw * request.restocking_fee_percent / 100)
    return [
        WarrantyReturnCostLine(
            line_id="return_shipping",
            label="반품 배송비",
            amount_krw=request.return_shipping_fee_krw,
            explanation="구매자가 부담할 수 있는 반품/교환 배송비입니다.",
        ),
        WarrantyReturnCostLine(
            line_id="restocking_fee",
            label="재입고 수수료",
            amount_krw=restocking,
            explanation=f"구매가의 {request.restocking_fee_percent}%로 계산한 수수료입니다.",
        ),
        WarrantyReturnCostLine(
            line_id="estimated_return_cost",
            label="최대 반품 비용",
            amount_krw=estimated_return_cost,
            explanation="배송비와 재입고 수수료를 합친 구매자 부담 가능 비용입니다.",
        ),
    ]


def _seller_questions(request: WarrantyReturnRequest, checks: list[WarrantyReturnCheck]) -> list[str]:
    questions = [
        "수령 후 단순 변심, 사양 불일치, 초기 불량 각각의 반품/교환 가능 기간을 알려주세요.",
        "개봉 후 전원 테스트와 벤치마크를 진행해도 초기 불량 반품 예외가 유지되나요?",
        "제조사 공식 AS인지, 국내 접수처와 시리얼 조회 방법을 알려주세요.",
        "초기 불량 또는 오배송이면 왕복 배송비와 재입고 수수료가 면제되나요?",
    ]
    if request.category == Category.laptop:
        questions.append("배터리/디스플레이 불량 판정 기준과 픽셀 불량 교환 기준을 알려주세요.")
    if any(check.check_id == "warranty_transfer" and check.status != CheckStatus.ok for check in checks):
        questions.append("영수증 양도나 소유자 변경 후에도 보증이 승계되나요?")
    return questions


def _evidence_checklist(request: WarrantyReturnRequest) -> list[str]:
    return [
        "판매 페이지의 반품/교환/환불 조건 캡처",
        "판매자 답변 원문과 답변 시각 캡처",
        "최종 결제 금액, 배송비, 쿠폰, 카드 할인 캡처",
        "제조사 보증 기간, 시리얼 조회 페이지, AS 접수처 캡처",
        "수령 첫날 박스 외관, 구성품, 전원/화면/포트/소음 테스트 캡처",
    ]


def _headline(request: WarrantyReturnRequest, priority: CheckStatus) -> str:
    if priority == CheckStatus.blocker:
        return f"{_title(request)}는 반품/AS 조건 확인 전 결제를 보류하세요."
    if priority == CheckStatus.warning:
        return f"{_title(request)}는 보증·반품 예외 조건을 먼저 캡처해야 합니다."
    return f"{_title(request)}는 보증·반품 정책 기준으로도 결제 방어가 가능합니다."


def _summary(
    request: WarrantyReturnRequest,
    priority: CheckStatus,
    score: int,
    estimated_return_cost: int,
) -> str:
    return (
        f"{_seller(request)} 기준 반품 {request.return_window_days}일, 교환 {request.exchange_window_days}일, "
        f"보증 {request.warranty_months}개월, 예상 반품 비용 {estimated_return_cost:,}원. "
        f"보호 점수 {score}점, 상태 {priority.value}."
    )


def _buyer_message(
    request: WarrantyReturnRequest,
    priority: CheckStatus,
    estimated_return_cost: int,
) -> str:
    return (
        f"{_seller(request)}에 확인 요청: {_title(request)} 구매 전 반품/교환/AS 조건을 확인하고 싶습니다. "
        f"개봉 후 초기 테스트, 사양 불일치, 초기 불량일 때 반품 가능 기간과 구매자 부담 비용"
        f"({estimated_return_cost:,}원 예상)이 어떻게 되는지 답변 부탁드립니다."
    )


def _analysis_prefill(
    request: WarrantyReturnRequest,
    priority: CheckStatus,
    score: int,
    estimated_return_cost: int,
) -> str:
    category_label = "노트북" if request.category == Category.laptop else "컴퓨터"
    return (
        f"{category_label} '{_title(request)}'의 보증/반품 정책을 포함해서 구매해도 되는지 분석해줘. "
        f"판매자 {_seller(request)}, 반품 {request.return_window_days}일, 초기 불량 {request.dead_on_arrival_days}일, "
        f"보증 {request.warranty_months}개월, 예상 반품 비용 {estimated_return_cost}, 보호 점수 {score}, 상태 {priority.value}."
    )


def _share_copy(
    request: WarrantyReturnRequest,
    priority: CheckStatus,
    score: int,
    estimated_return_cost: int,
) -> str:
    return (
        "SpecPilot AI 보증/반품 검수\n"
        f"제품: {_title(request)}\n"
        f"판매자: {_seller(request)}\n"
        f"상태: {priority.value}\n"
        f"보호 점수: {score}점\n"
        f"예상 반품 비용: {estimated_return_cost:,}원"
    )


def _next_actions(priority: CheckStatus, checks: list[WarrantyReturnCheck]) -> list[str]:
    if priority == CheckStatus.blocker:
        return [
            "반품 불가, 보증 없음, AS 불가 조건은 판매자 답변을 받기 전 결제를 보류하세요.",
            "대체 후보의 공식 스토어/제조사 보증 조건과 비교하세요.",
            "구매 승인 브리프에 차단 사유와 필요한 답변을 그대로 붙이세요.",
        ]
    if priority == CheckStatus.warning:
        first_warning = next((check.recommendation for check in checks if check.status == CheckStatus.warning), "")
        return [
            first_warning or "보증/반품 예외 조건을 판매자에게 확인하세요.",
            "반품 비용과 개봉 후 초기 테스트 예외를 캡처하세요.",
            "첫 부팅 세팅 검수로 초기 불량 증거를 수령 당일 남기세요.",
        ]
    return [
        "반품/보증 캡처를 구매 승인 브리프와 함께 저장하세요.",
        "수령 첫날 첫 부팅 세팅 검수로 증거를 이어가세요.",
        "총소유비용 검수에 보증 승계 여부를 반영하세요.",
    ]
