from datetime import UTC, datetime

from specpilot_ai.core.models import (
    CheckStatus,
    FinalDecisionGate,
    FinalDecisionKitRequest,
    FinalDecisionSignal,
    PublicFinalDecisionKit,
    PurchaseExecutionKitRequest,
    ReviewerQuickCardRequest,
)

SIGNAL_WEIGHTS = {
    "price": 20,
    "checkout": 20,
    "compatibility": 18,
    "review": 16,
    "warranty": 14,
    "evidence": 12,
}


def build_public_final_decision_kit(
    request: FinalDecisionKitRequest,
    generated_at: datetime | None = None,
) -> PublicFinalDecisionKit:
    generated_at = generated_at or datetime.now(UTC)
    signals = _signals(request)
    blockers = _blocker_reasons(request, signals)
    warnings = _warning_reasons(request, signals)
    score = _decision_score(signals, blockers, warnings)
    status = _decision_status(score, blockers, warnings)
    decision = _decision(status, score, blockers)
    title = _title(request)
    delta = (
        request.final_price_krw - request.budget_krw
        if request.final_price_krw is not None
        else None
    )
    evidence = _evidence_checklist(request, status)
    questions = _seller_questions(request, status)

    return PublicFinalDecisionKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        product_title=title,
        seller_name=_seller(request),
        final_decision=decision,
        decision_status=status,
        decision_score=score,
        headline=_headline(title, status),
        summary=_summary(request, status, score, delta, blockers, warnings),
        primary_action=_primary_action(status, blockers, warnings),
        price_delta_krw=delta,
        signals=signals,
        decision_gates=_decision_gates(request, status, evidence),
        blocker_reasons=blockers,
        warning_reasons=warnings,
        evidence_checklist=evidence,
        seller_questions=questions,
        execution_prefill=_execution_prefill(request, decision, blockers, warnings, evidence, questions),
        reviewer_prefill=_reviewer_prefill(request, decision, score, blockers, warnings, evidence),
        analysis_prefill=_analysis_prefill(request, decision, score, blockers, warnings),
        share_copy=_share_copy(request, decision, score, blockers, warnings),
        next_actions=_next_actions(status),
    )


def _title(request: FinalDecisionKitRequest) -> str:
    return request.product_title.strip() or "구매 후보"


def _seller(request: FinalDecisionKitRequest) -> str:
    return request.seller_name.strip() or "판매자"


def _money(value: int | None) -> str:
    return f"{value:,}원" if value is not None else "미입력"


def _signals(request: FinalDecisionKitRequest) -> list[FinalDecisionSignal]:
    return [
        _signal(
            "price",
            "최종가/가격 신뢰",
            request.price_status,
            request.price_score,
            f"예산 {_money(request.budget_krw)}, 최종가 {_money(request.final_price_krw)}",
            "배송비, 쿠폰, 카드 할인 포함 총액을 다시 캡처하세요.",
        ),
        _signal(
            "checkout",
            "체크아웃 잠금",
            request.checkout_status,
            request.checkout_score,
            "장바구니 옵션명과 최종 결제 화면 일치 여부",
            "상품명, 옵션명, 수량, 판매자, 총액이 잠금 기준과 같은지 확인하세요.",
        ),
        _signal(
            "compatibility",
            "목적/호환성",
            request.compatibility_status,
            request.compatibility_score,
            request.selected_reason.strip() or "목적 적합 근거 미입력",
            "CPU/GPU/RAM/SSD/파워/디스플레이 병목을 결제 전 한 번 더 봅니다.",
        ),
        _signal(
            "review",
            "리뷰 반복 리스크",
            request.review_status,
            request.review_score,
            "발열, 팬 소음, 초기 불량, AS 반복 불만 상태",
            "반복 불만이 목적 사용에 치명적인지 후기 원문과 판매자 답변으로 확인하세요.",
        ),
        _signal(
            "warranty",
            "보증/반품 보호",
            request.warranty_status,
            request.warranty_score,
            "반품 기간, 초기 불량 예외, 보증 주체 확인 상태",
            "개봉 후 반품, 초기 불량 교환, 국내 AS 주체를 문의로 닫으세요.",
        ),
        _signal(
            "evidence",
            "증거 캡처 완성도",
            request.evidence_status,
            _evidence_score(request),
            f"준비 {len(_ready(request))}개, 누락 {len(_missing(request))}개",
            "결제 전 증거가 부족하면 사후 반품/AS 대응력이 약해집니다.",
        ),
    ]


def _signal(
    signal_id: str,
    label: str,
    status: CheckStatus,
    score: int,
    evidence: str,
    action: str,
) -> FinalDecisionSignal:
    return FinalDecisionSignal(
        signal_id=signal_id,
        label=label,
        status=status,
        score=max(0, min(100, score)),
        weight=SIGNAL_WEIGHTS[signal_id],
        evidence=evidence,
        action=action,
    )


def _ready(request: FinalDecisionKitRequest) -> list[str]:
    return [item.strip() for item in request.ready_evidence if item.strip()][:10]


def _missing(request: FinalDecisionKitRequest) -> list[str]:
    return [item.strip() for item in request.missing_evidence if item.strip()][:10]


def _evidence_score(request: FinalDecisionKitRequest) -> int:
    ready = len(_ready(request))
    missing = len(_missing(request))
    base = request.checkout_score if request.checkout_score else 70
    return max(0, min(100, base + ready * 4 - missing * 12))


def _decision_score(
    signals: list[FinalDecisionSignal],
    blockers: list[str],
    warnings: list[str],
) -> int:
    weighted = sum(signal.score * signal.weight for signal in signals)
    total_weight = sum(signal.weight for signal in signals)
    score = round(weighted / total_weight) if total_weight else 70
    score -= len(blockers) * 13
    score -= len(warnings) * 4
    return max(0, min(100, score))


def _blocker_reasons(
    request: FinalDecisionKitRequest,
    signals: list[FinalDecisionSignal],
) -> list[str]:
    reasons = [item.strip() for item in request.blocker_reasons if item.strip()]
    reasons.extend(
        f"{signal.label} blocker: {signal.evidence}"
        for signal in signals
        if signal.status == CheckStatus.blocker
    )
    if request.final_price_krw is not None and request.final_price_krw > request.budget_krw * 1.08:
        reasons.append("최종가가 예산보다 8% 이상 높습니다.")
    return list(dict.fromkeys(reasons))[:8]


def _warning_reasons(
    request: FinalDecisionKitRequest,
    signals: list[FinalDecisionSignal],
) -> list[str]:
    reasons = [item.strip() for item in request.warning_reasons if item.strip()]
    reasons.extend(
        f"{signal.label} 확인 필요: {signal.action}"
        for signal in signals
        if signal.status == CheckStatus.warning
    )
    reasons.extend(f"누락 증거: {item}" for item in _missing(request))
    if request.final_price_krw is not None and request.final_price_krw > request.budget_krw:
        reasons.append("최종가가 예산을 초과합니다.")
    return list(dict.fromkeys(reasons))[:10]


def _decision_status(score: int, blockers: list[str], warnings: list[str]) -> CheckStatus:
    if blockers or score < 45:
        return CheckStatus.blocker
    if warnings or score < 82:
        return CheckStatus.warning
    return CheckStatus.ok


def _decision(status: CheckStatus, score: int, blockers: list[str]) -> str:
    if status == CheckStatus.blocker:
        return "hold"
    if status == CheckStatus.warning:
        return "verify"
    return "go" if score >= 82 and not blockers else "verify"


def _headline(title: str, status: CheckStatus) -> str:
    if status == CheckStatus.blocker:
        return f"{title}는 지금 결제하지 말고 차단 사유를 먼저 닫아야 합니다."
    if status == CheckStatus.warning:
        return f"{title}는 마지막 증거 확인 후 조건부로만 결제하세요."
    return f"{title}는 결제 전 증거 캡처 후 구매해도 됩니다."


def _summary(
    request: FinalDecisionKitRequest,
    status: CheckStatus,
    score: int,
    delta: int | None,
    blockers: list[str],
    warnings: list[str],
) -> str:
    delta_text = "최종가 미입력" if delta is None else f"예산 대비 {delta:+,}원"
    if status == CheckStatus.blocker:
        return (
            f"최종 판정 점수 {score}점, {delta_text}. blocker {len(blockers)}개가 있어 "
            "가격이 좋아도 결제보다 판매자 답변, 대체 후보, 증거 보강이 먼저입니다."
        )
    if status == CheckStatus.warning:
        return (
            f"최종 판정 점수 {score}점, {delta_text}. warning {len(warnings)}개를 "
            "캡처와 판매자 답변으로 닫으면 제한 승인할 수 있습니다."
        )
    return f"최종 판정 점수 {score}점, {delta_text}. 가격, 옵션, 보증 증거를 저장하고 결제하세요."


def _primary_action(
    status: CheckStatus,
    blockers: list[str],
    warnings: list[str],
) -> str:
    if status == CheckStatus.blocker:
        return blockers[0] if blockers else "결제를 보류하고 차단 사유를 먼저 해결하세요."
    if status == CheckStatus.warning:
        return warnings[0] if warnings else "누락 증거를 캡처한 뒤 같은 조건일 때만 결제하세요."
    return "최종 결제 화면과 옵션명을 캡처한 뒤 구매 후 케어로 이어가세요."


def _evidence_checklist(
    request: FinalDecisionKitRequest,
    status: CheckStatus,
) -> list[str]:
    required = [
        "최종 결제 화면 총액",
        "상품명과 옵션명 전체",
        "CPU/GPU/RAM/SSD/OS 사양",
        "배송 예정일과 재고 상태",
        "반품/교환 기간과 초기 불량 예외",
        "보증 주체와 AS 기간",
        "반복 불만 후기 원문",
    ]
    items = [*required, *_ready(request), *_missing(request)]
    if status != CheckStatus.ok:
        items.insert(0, "판매자 문의 답변 캡처")
    return list(dict.fromkeys(item for item in items if item))[:12]


def _seller_questions(
    request: FinalDecisionKitRequest,
    status: CheckStatus,
) -> list[str]:
    questions = [item.strip() for item in request.seller_questions if item.strip()]
    questions.extend(
        [
            "최종 출고 사양이 장바구니 옵션명과 동일한가요?",
            "초기 불량이면 개봉 후에도 교환 또는 반품이 가능한가요?",
            "국내 AS 주체와 보증 기간을 주문서에 명시할 수 있나요?",
            "배송 지연 또는 품절 시 같은 가격으로 취소/변경할 수 있나요?",
        ],
    )
    if status == CheckStatus.blocker:
        questions.insert(0, "현재 blocker 사유가 해결되지 않으면 결제하지 않는 것이 맞나요?")
    return list(dict.fromkeys(questions))[:8]


def _decision_gates(
    request: FinalDecisionKitRequest,
    status: CheckStatus,
    evidence: list[str],
) -> list[FinalDecisionGate]:
    return [
        FinalDecisionGate(
            gate_id="blocker_zero",
            label="차단 사유 0개",
            status=CheckStatus.blocker if status == CheckStatus.blocker else CheckStatus.ok,
            pass_rule="blocker_reasons가 비어 있어야 합니다.",
            fail_rule="blocker가 남으면 가격이 좋아도 결제하지 않습니다.",
        ),
        FinalDecisionGate(
            gate_id="evidence_closed",
            label="증거 캡처 완료",
            status=CheckStatus.warning if _missing(request) else CheckStatus.ok,
            pass_rule=f"{', '.join(evidence[:4])} 캡처가 있어야 합니다.",
            fail_rule="최종가, 옵션명, 반품/AS 증거가 없으면 verify로 낮춥니다.",
        ),
        FinalDecisionGate(
            gate_id="deadline",
            label="결정 마감",
            status=CheckStatus.warning if status == CheckStatus.warning else status,
            pass_rule=f"{request.decision_deadline.strip() or '결제 전'}까지 같은 조건이면 진행합니다.",
            fail_rule="마감 전에 가격/옵션/재고가 바뀌면 다시 판정합니다.",
        ),
    ]


def _execution_prefill(
    request: FinalDecisionKitRequest,
    decision: str,
    blockers: list[str],
    warnings: list[str],
    evidence: list[str],
    questions: list[str],
) -> PurchaseExecutionKitRequest:
    return PurchaseExecutionKitRequest(
        category=request.category,
        product_title=_title(request),
        seller_name=_seller(request),
        verdict="hold" if decision == "hold" else "ready" if decision == "go" else "verify",
        final_price_krw=request.final_price_krw,
        budget_krw=request.budget_krw,
        blocker_count=len(blockers),
        warning_count=len(warnings),
        missing_evidence=_missing(request),
        seller_questions=questions,
        evidence_ready=evidence[:8],
        decision_deadline=request.decision_deadline,
        share_audience=request.share_audience,
        source="final_decision_kit",
    )


def _reviewer_prefill(
    request: FinalDecisionKitRequest,
    decision: str,
    score: int,
    blockers: list[str],
    warnings: list[str],
    evidence: list[str],
) -> ReviewerQuickCardRequest:
    return ReviewerQuickCardRequest(
        category=request.category,
        product_title=_title(request),
        buyer_decision="hold" if decision == "hold" else "ready" if decision == "go" else "verify",
        final_price_krw=request.final_price_krw,
        budget_krw=request.budget_krw,
        confidence_percent=score,
        blocker_count=len(blockers),
        warning_count=len(warnings),
        key_reasons=[request.selected_reason.strip() or "목적과 예산 기준 1순위 후보"],
        watchouts=[*blockers, *warnings][:6],
        missing_evidence=_missing(request) or evidence[:3],
        reviewer_role=request.share_audience,
        review_deadline=request.decision_deadline,
        source="final_decision_kit",
    )


def _analysis_prefill(
    request: FinalDecisionKitRequest,
    decision: str,
    score: int,
    blockers: list[str],
    warnings: list[str],
) -> str:
    return (
        f"{_title(request)}를 최종 결제해도 되는지 봐줘. 판정={decision}, 점수={score}, "
        f"예산={request.budget_krw:,}원, 최종가={_money(request.final_price_krw)}, "
        f"blocker={blockers[:3]}, warning={warnings[:3]}. "
        "가격, 옵션, 리뷰, 보증, 증거 캡처 기준으로 go/verify/hold를 다시 판단해줘."
    )


def _share_copy(
    request: FinalDecisionKitRequest,
    decision: str,
    score: int,
    blockers: list[str],
    warnings: list[str],
) -> str:
    status_label = {"go": "구매 가능", "verify": "확인 후 구매", "hold": "구매 보류"}[decision]
    lines = [
        "SpecPilot AI 최종 구매 판정",
        f"- 후보: {_title(request)}",
        f"- 판정: {status_label} ({score}점)",
        f"- 예산/최종가: {request.budget_krw:,}원 / {_money(request.final_price_krw)}",
    ]
    if blockers:
        lines.append(f"- 차단: {', '.join(blockers[:3])}")
    if warnings:
        lines.append(f"- 확인: {', '.join(warnings[:3])}")
    lines.append("반대할 이유나 빠진 증거가 있으면 결제 전에 알려주세요.")
    return "\n".join(lines)


def _next_actions(status: CheckStatus) -> list[str]:
    if status == CheckStatus.blocker:
        return [
            "blocker를 판매자 답변 또는 대체 후보 비교로 닫으세요.",
            "구매 실행 패키지로 중단 조건을 공유하세요.",
            "최종가가 바뀌면 가격 신뢰 키트부터 다시 실행하세요.",
        ]
    if status == CheckStatus.warning:
        return [
            "누락 증거를 캡처한 뒤 구매 실행 패키지로 넘기세요.",
            "30초 검토 카드로 가족/팀/커뮤니티 반대 의견을 받으세요.",
            "결제 화면이 바뀌면 체크아웃 잠금 검수를 다시 실행하세요.",
        ]
    return [
        "최종 결제 화면을 캡처하고 결제하세요.",
        "구매 후 케어 키트로 반품/보증 마감과 첫 점검을 기록하세요.",
        "구매 결과 공유 카드로 실제 결과를 남기세요.",
    ]
