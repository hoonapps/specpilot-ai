from datetime import UTC, datetime

from specpilot_ai.core.models import (
    Category,
    CheckStatus,
    OutcomeProofMetric,
    OutcomeShareCardRequest,
    OutcomeShareVariant,
    PublicOutcomeShareCardKit,
    PurchaseOutcomeStatus,
)


def build_public_outcome_share_card_kit(
    request: OutcomeShareCardRequest,
    generated_at: datetime | None = None,
) -> PublicOutcomeShareCardKit:
    generated_at = generated_at or datetime.now(UTC)
    title = _title(request)
    issues = _clean(request.issues, 6)
    saved_reasons = _clean(request.saved_reasons, 6)
    regrets = _clean(request.regrets, 6)
    price_delta = _price_delta(request)
    proof_status = _proof_status(request, issues, regrets, price_delta)
    proof_score = _proof_score(request, issues, saved_reasons, regrets, price_delta)
    proof_points = _proof_points(request, saved_reasons, price_delta)
    caution_notes = _caution_notes(request, issues, regrets, price_delta)
    return PublicOutcomeShareCardKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        product_title=title,
        outcome_status=request.outcome_status,
        proof_status=proof_status,
        proof_score=proof_score,
        price_delta_krw=price_delta,
        headline=_headline(request, title, proof_status),
        summary=_summary(request, title, proof_score, price_delta),
        proof_metrics=_proof_metrics(request, proof_status, price_delta),
        proof_points=proof_points,
        caution_notes=caution_notes,
        share_variants=_share_variants(request, title, proof_status, proof_score, price_delta),
        learning_signals=_learning_signals(request, issues, saved_reasons, regrets, price_delta),
        analysis_prefill=_analysis_prefill(request, title, proof_status, proof_score, price_delta),
        share_copy=_share_copy(request, title, proof_status, proof_score, price_delta),
        next_actions=_next_actions(request, proof_status, issues, regrets),
    )


def _title(request: OutcomeShareCardRequest) -> str:
    fallback = "노트북 구매 결과" if request.category == Category.laptop else "컴퓨터 구매 결과"
    return request.product_title.strip() or fallback


def _clean(values: list[str], limit: int) -> list[str]:
    return [value.strip() for value in values if value.strip()][:limit]


def _price_delta(request: OutcomeShareCardRequest) -> int | None:
    if request.final_paid_price_krw is None:
        return None
    baseline = request.planned_price_krw
    if baseline is None:
        baseline = request.budget_krw
    if baseline is None:
        return None
    return request.final_paid_price_krw - baseline


def _proof_status(
    request: OutcomeShareCardRequest,
    issues: list[str],
    regrets: list[str],
    price_delta: int | None,
) -> CheckStatus:
    if request.outcome_status == PurchaseOutcomeStatus.returned:
        return CheckStatus.blocker
    if request.satisfaction_score <= 4 or any(_severe_issue(issue) for issue in issues):
        return CheckStatus.blocker
    if request.outcome_status in {PurchaseOutcomeStatus.abandoned, PurchaseOutcomeStatus.delayed}:
        return CheckStatus.warning
    if request.satisfaction_score <= 7 or issues or regrets:
        return CheckStatus.warning
    if price_delta is not None and price_delta > 100_000:
        return CheckStatus.warning
    return CheckStatus.ok


def _severe_issue(value: str) -> bool:
    lowered = value.lower()
    severe_terms = (
        "불량",
        "반품 불가",
        "환불 불가",
        "파손",
        "오배송",
        "사양 상이",
        "부팅 안",
        "as 불가",
        "defect",
        "broken",
        "dead",
    )
    return any(term in lowered for term in severe_terms)


def _proof_score(
    request: OutcomeShareCardRequest,
    issues: list[str],
    saved_reasons: list[str],
    regrets: list[str],
    price_delta: int | None,
) -> int:
    score = request.satisfaction_score * 10
    if request.outcome_status == PurchaseOutcomeStatus.purchased:
        score += 8
    elif request.outcome_status == PurchaseOutcomeStatus.delayed:
        score -= 8
    elif request.outcome_status == PurchaseOutcomeStatus.abandoned:
        score -= 12
    else:
        score -= 28
    score += min(len(saved_reasons) * 4, 12)
    score -= min(len(issues) * 8, 24)
    score -= min(len(regrets) * 6, 18)
    if price_delta is not None:
        if price_delta <= 0:
            score += 7
        elif price_delta <= 50_000:
            score -= 2
        else:
            score -= 8
    if any(_severe_issue(issue) for issue in issues):
        score -= 18
    return max(0, min(100, score))


def _proof_metrics(
    request: OutcomeShareCardRequest,
    proof_status: CheckStatus,
    price_delta: int | None,
) -> list[OutcomeProofMetric]:
    return [
        OutcomeProofMetric(
            metric_id="outcome",
            label="구매 결과",
            value=_status_label(request.outcome_status),
            detail=_status_detail(request.outcome_status),
            status=proof_status,
        ),
        OutcomeProofMetric(
            metric_id="price_delta",
            label="계획가 대비",
            value="미입력" if price_delta is None else f"{price_delta:+,}원",
            detail="최종 결제 금액과 계획가 또는 예산을 비교했습니다.",
            status=CheckStatus.ok if price_delta is not None and price_delta <= 0 else CheckStatus.warning,
        ),
        OutcomeProofMetric(
            metric_id="satisfaction",
            label="만족도",
            value=f"{request.satisfaction_score}/10",
            detail="실제 사용 후 체감 만족도입니다.",
            status=(
                CheckStatus.ok
                if request.satisfaction_score >= 8
                else CheckStatus.warning
                if request.satisfaction_score >= 5
                else CheckStatus.blocker
            ),
        ),
        OutcomeProofMetric(
            metric_id="decision_time",
            label="결정 시간",
            value="미입력" if request.time_to_decide_hours is None else f"{request.time_to_decide_hours}시간",
            detail="처음 후보 검토부터 최종 결정까지 걸린 시간입니다.",
            status=CheckStatus.ok,
        ),
    ]


def _proof_points(
    request: OutcomeShareCardRequest,
    saved_reasons: list[str],
    price_delta: int | None,
) -> list[str]:
    points = [f"상태: {_status_label(request.outcome_status)}"]
    if price_delta is not None:
        points.append(f"계획가 대비 {price_delta:+,}원으로 마감")
    if saved_reasons:
        points.extend(f"확인 근거: {reason}" for reason in saved_reasons[:4])
    else:
        points.append("최종 결제 화면, 옵션명, 반품/AS 조건 캡처가 다음 공유 신뢰도를 높입니다.")
    return points[:6]


def _caution_notes(
    request: OutcomeShareCardRequest,
    issues: list[str],
    regrets: list[str],
    price_delta: int | None,
) -> list[str]:
    notes = []
    if request.outcome_status == PurchaseOutcomeStatus.returned:
        notes.append("반품/취소 결과는 원인과 판매자 응답 캡처를 함께 남겨야 다음 추천에서 같은 위험을 제외할 수 있습니다.")
    if price_delta is not None and price_delta > 0:
        notes.append(f"계획보다 {price_delta:,}원 더 지불했습니다. 쿠폰, 배송비, 조립비, OS 비용 누락 여부를 확인하세요.")
    notes.extend(f"이슈: {issue}" for issue in issues[:3])
    notes.extend(f"아쉬움: {regret}" for regret in regrets[:3])
    if not notes:
        notes.append("개인정보, 주문번호 원문, 카드 정보는 공유 카드에서 제외하세요.")
    return notes[:6]


def _share_variants(
    request: OutcomeShareCardRequest,
    title: str,
    proof_status: CheckStatus,
    proof_score: int,
    price_delta: int | None,
) -> list[OutcomeShareVariant]:
    delta = "가격 차이 미입력" if price_delta is None else f"계획가 대비 {price_delta:+,}원"
    base = (
        f"{title} 구매 결과: {_status_label(request.outcome_status)} · "
        f"proof {proof_score}/100 · {delta}"
    )
    audience = request.share_audience.strip() or "community"
    return [
        OutcomeShareVariant(
            channel="community",
            label="커뮤니티 공유",
            copy_text=f"{base}\n확인 근거와 이슈를 개인정보 없이 정리했습니다. 다음 구매자는 같은 조건을 먼저 확인하세요.",
            cta_label="커뮤니티에 붙여넣기",
        ),
        OutcomeShareVariant(
            channel="kakao",
            label="카카오톡",
            copy_text=f"{base}\nSpecPilot AI로 결제 전후 체크를 닫았습니다.",
            cta_label="카톡 공유",
        ),
        OutcomeShareVariant(
            channel="team",
            label="팀 구매 기록",
            copy_text=(
                f"[구매 결과] {title} · 대상 {audience} · 상태 {request.outcome_status.value} · "
                f"proof {proof_status.value}/{proof_score}"
            ),
            cta_label="팀 기록에 저장",
        ),
        OutcomeShareVariant(
            channel="email",
            label="이메일",
            copy_text=f"{base}\n다음 추천에는 만족도, 최종가 차이, 이슈를 학습 신호로 반영합니다.",
            cta_label="메일 초안 복사",
        ),
    ]


def _learning_signals(
    request: OutcomeShareCardRequest,
    issues: list[str],
    saved_reasons: list[str],
    regrets: list[str],
    price_delta: int | None,
) -> list[str]:
    signals = [
        f"outcome_status={request.outcome_status.value}",
        f"satisfaction_score={request.satisfaction_score}",
    ]
    if price_delta is not None:
        signals.append(f"price_delta_krw={price_delta}")
    if request.time_to_decide_hours is not None:
        signals.append(f"time_to_decide_hours={request.time_to_decide_hours}")
    if saved_reasons:
        signals.append(f"evidence_ready={', '.join(saved_reasons[:3])}")
    if issues:
        signals.append(f"issue_themes={', '.join(issues[:3])}")
    if regrets:
        signals.append(f"regret_themes={', '.join(regrets[:3])}")
    return signals


def _analysis_prefill(
    request: OutcomeShareCardRequest,
    title: str,
    proof_status: CheckStatus,
    proof_score: int,
    price_delta: int | None,
) -> str:
    delta = "미입력" if price_delta is None else f"{price_delta:+,}원"
    return (
        f"{_category_label(request.category)} '{title}' 구매 결과를 분석해줘. "
        f"상태 {request.outcome_status.value}, 만족도 {request.satisfaction_score}/10, "
        f"계획가 대비 {delta}, proof 상태 {proof_status.value}, proof 점수 {proof_score}. "
        f"다음 추천 기준은 '{request.next_recommendation.strip() or '구매 전 증거 캡처'}'."
    )


def _share_copy(
    request: OutcomeShareCardRequest,
    title: str,
    proof_status: CheckStatus,
    proof_score: int,
    price_delta: int | None,
) -> str:
    delta = "가격 차이 미입력" if price_delta is None else f"계획가 대비 {price_delta:+,}원"
    return (
        "SpecPilot AI 구매 결과 공유\n"
        f"제품: {title}\n"
        f"결과: {_status_label(request.outcome_status)}\n"
        f"Proof: {proof_status.value} / {proof_score}점\n"
        f"{delta}"
    )


def _headline(
    request: OutcomeShareCardRequest,
    title: str,
    proof_status: CheckStatus,
) -> str:
    if proof_status == CheckStatus.blocker:
        return f"{title} 결과는 공유보다 원인 기록과 반품/AS 대응이 먼저입니다."
    if proof_status == CheckStatus.warning:
        return f"{title} 결과는 주의 조건을 함께 공개해야 신뢰도가 올라갑니다."
    if request.outcome_status == PurchaseOutcomeStatus.purchased:
        return f"{title} 구매 결과를 공개 proof 카드로 공유할 수 있습니다."
    return f"{title} 구매 판단 결과를 다음 후보 비교 근거로 남길 수 있습니다."


def _summary(
    request: OutcomeShareCardRequest,
    title: str,
    proof_score: int,
    price_delta: int | None,
) -> str:
    delta = "최종가 차이는 아직 입력되지 않았습니다." if price_delta is None else f"계획가 대비 {price_delta:+,}원입니다."
    return (
        f"{title}의 실제 결과, 만족도 {request.satisfaction_score}/10, {delta} "
        f"공개 공유용 proof 점수는 {proof_score}점이며 개인정보 없이 근거와 주의점을 분리했습니다."
    )


def _next_actions(
    request: OutcomeShareCardRequest,
    proof_status: CheckStatus,
    issues: list[str],
    regrets: list[str],
) -> list[str]:
    if proof_status == CheckStatus.blocker:
        return [
            "반품/교환/AS 접수 번호와 판매자 답변을 먼저 캡처하세요.",
            "구매 결과를 returned 상태로 저장하고 같은 위험어를 다음 후보 제외 조건에 넣으세요.",
            "공유 카드는 원인과 해결 상태를 마스킹한 뒤 공개하세요.",
        ]
    if proof_status == CheckStatus.warning:
        action = request.next_recommendation.strip() or "누락 증거를 보완한 뒤 다시 검토"
        return [
            f"다음 추천 기준으로 '{action}'을 추가하세요.",
            "최종 결제 화면, 옵션명, 반품/AS 조건 중 빠진 증거를 보완하세요.",
            "커뮤니티 공유에는 이슈와 아쉬움을 함께 적어 과장된 후기로 보이지 않게 하세요.",
        ]
    return [
        "구매 결과를 purchased 상태로 저장해 추천 품질 학습에 반영하세요.",
        "공개 공유 카드에서 주문번호와 개인정보를 제거한 뒤 커뮤니티 proof로 활용하세요.",
        "만족도가 높았던 근거를 다음 구매자의 체크리스트로 재사용하세요.",
    ]


def _status_label(status: PurchaseOutcomeStatus) -> str:
    return {
        PurchaseOutcomeStatus.purchased: "구매 완료",
        PurchaseOutcomeStatus.abandoned: "구매 이탈",
        PurchaseOutcomeStatus.delayed: "구매 지연",
        PurchaseOutcomeStatus.returned: "반품/취소",
    }[status]


def _status_detail(status: PurchaseOutcomeStatus) -> str:
    return {
        PurchaseOutcomeStatus.purchased: "최종 결제와 사용 만족도를 확인했습니다.",
        PurchaseOutcomeStatus.abandoned: "구매를 중단한 이유가 다음 추천의 제외 조건이 됩니다.",
        PurchaseOutcomeStatus.delayed: "목표가 대기나 증거 부족으로 결정을 미뤘습니다.",
        PurchaseOutcomeStatus.returned: "초기 불량, 사양 불일치, 정책 문제를 우선 기록해야 합니다.",
    }[status]


def _category_label(category: Category) -> str:
    return "노트북" if category == Category.laptop else "컴퓨터"
