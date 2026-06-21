from datetime import UTC, datetime

from specpilot_ai.core.models import (
    ApprovalCopyVariant,
    Category,
    CheckStatus,
    DecisionDefenseComparison,
    DecisionDefenseObjection,
    DecisionDefenseRequest,
    PublicDecisionDefenseKit,
)


def build_public_decision_defense_kit(
    request: DecisionDefenseRequest,
    generated_at: datetime | None = None,
) -> PublicDecisionDefenseKit:
    generated_at = generated_at or datetime.now(UTC)
    title = _title(request)
    decision = _decision(request.decision)
    evidence = _clean(request.evidence_ready)[:8]
    watchouts = _clean(request.watchouts)[:8]
    reasons = _reasons(request)
    defense_score = _defense_score(request, decision, evidence, watchouts)
    defense_status = _defense_status(decision, defense_score, watchouts)
    objections = _objections(request, reasons, watchouts, evidence, defense_status)
    comparisons = _comparisons(request, reasons, watchouts)
    reviewer_brief = _reviewer_brief(
        request=request,
        title=title,
        decision=decision,
        status=defense_status,
        reasons=reasons,
        watchouts=watchouts,
    )
    return PublicDecisionDefenseKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        product_title=title,
        seller_name=request.seller_name.strip() or "판매자 미입력",
        decision=decision,
        audience=_audience_label(request.audience),
        defense_status=defense_status,
        defense_score=defense_score,
        headline=_headline(title, defense_status),
        summary=_summary(request, defense_status, defense_score, watchouts),
        reviewer_brief=reviewer_brief,
        objections=objections,
        comparisons=comparisons,
        proof_checklist=_proof_checklist(request, evidence, watchouts),
        reviewer_questions=_reviewer_questions(request, objections),
        copy_variants=_copy_variants(request, title, reviewer_brief, defense_status),
        analysis_prefill=_analysis_prefill(request, decision, defense_status, objections),
        share_copy=_share_copy(request, title, defense_status, reviewer_brief),
        next_actions=_next_actions(defense_status, watchouts),
    )


def _title(request: DecisionDefenseRequest) -> str:
    return request.product_title.strip() or _category_label(request.category)


def _category_label(category: Category) -> str:
    return "노트북" if category == Category.laptop else "데스크톱 PC"


def _money(value: int | None) -> str:
    return f"{value:,}원" if value is not None else "미입력"


def _decision(value: str) -> str:
    normalized = value.strip().lower()
    return normalized if normalized in {"ready", "verify", "hold"} else "verify"


def _clean(values: list[str]) -> list[str]:
    return [value.strip() for value in values if value.strip()]


def _audience_label(audience: str) -> str:
    labels = {
        "family": "가족/지인",
        "team": "팀 승인자",
        "community": "커뮤니티 검토자",
        "self": "본인",
    }
    return labels.get(audience.strip().lower(), "검토자")


def _reasons(request: DecisionDefenseRequest) -> list[str]:
    reasons = _clean(request.key_reasons)
    if reasons:
        return reasons[:6]
    category = _category_label(request.category)
    return [
        f"{category} 목적 {request.purpose} 기준으로 예산과 핵심 사양의 균형이 가장 좋습니다.",
        "가격만 낮은 후보보다 결제 전 증거와 사용 목적 적합도를 함께 봤습니다.",
        "남은 리스크는 결제 전 캡처와 판매자 답변으로 닫을 수 있습니다.",
    ]


def _defense_score(
    request: DecisionDefenseRequest,
    decision: str,
    evidence: list[str],
    watchouts: list[str],
) -> int:
    score = int(round(request.confidence_score))
    score += min(12, len(evidence) * 3)
    score -= min(24, len(watchouts) * 6)
    if decision == "ready":
        score += 8
    elif decision == "hold":
        score -= 22
    if request.final_price_krw is None:
        score -= 8
    elif request.final_price_krw > request.budget_krw:
        over_ratio = (request.final_price_krw - request.budget_krw) / max(1, request.budget_krw)
        score -= 18 if over_ratio >= 0.05 else 10
    elif request.final_price_krw <= int(request.budget_krw * 0.95):
        score += 6
    if any(_hard_watchout(item) for item in watchouts):
        score -= 18
    return max(0, min(100, score))


def _hard_watchout(value: str) -> bool:
    lowered = value.lower()
    terms = ["반품 불가", "as 불가", "a/s 불가", "해외", "리퍼", "전시", "예산 초과"]
    return any(term in lowered for term in terms)


def _defense_status(decision: str, score: int, watchouts: list[str]) -> CheckStatus:
    if decision == "hold" or score < 55 or any(_hard_watchout(item) for item in watchouts):
        return CheckStatus.blocker
    if decision == "verify" or score < 82 or watchouts:
        return CheckStatus.warning
    return CheckStatus.ok


def _objections(
    request: DecisionDefenseRequest,
    reasons: list[str],
    watchouts: list[str],
    evidence: list[str],
    status: CheckStatus,
) -> list[DecisionDefenseObjection]:
    focus = set(_clean(request.objection_focus))
    objections = [
        _price_objection(request, evidence, status),
        _cheaper_alternative_objection(request, reasons),
        _purpose_fit_objection(request, reasons),
        _risk_objection(watchouts, status),
        _timing_objection(request, watchouts),
        _trust_objection(evidence),
    ]
    if focus:
        focused = [
            item
            for item in objections
            if item.objection_id in focus
            or any(token in item.question for token in focus)
            or any(token in item.answer for token in focus)
        ]
        if focused:
            return focused[:6]
    return objections[:6]


def _price_objection(
    request: DecisionDefenseRequest,
    evidence: list[str],
    status: CheckStatus,
) -> DecisionDefenseObjection:
    price = request.final_price_krw
    budget = request.budget_krw
    if price is None:
        answer = "최종 결제 금액이 없으면 방어가 약합니다. 총액 캡처 전에는 승인하지 않는 편이 맞습니다."
        objection_status = CheckStatus.warning
        condition = "최종 결제 금액 캡처가 없으면 결제 보류"
    elif price > budget:
        answer = f"최종가가 예산을 {price - budget:,}원 초과합니다. 승인자가 명시적으로 예산 초과를 허용해야 합니다."
        objection_status = CheckStatus.blocker
        condition = "예산 초과 승인 없으면 결제 보류"
    else:
        answer = f"최종가 {_money(price)}가 예산 {_money(budget)} 안에 있고, 가격 증거를 캡처하면 방어 가능합니다."
        objection_status = status if status == CheckStatus.blocker else CheckStatus.ok
        condition = "배송비/쿠폰/카드 할인 반영 후에도 예산 안이면 통과"
    return DecisionDefenseObjection(
        objection_id="price",
        question="이 가격이 정말 납득 가능한가요?",
        status=objection_status,
        answer=answer,
        proof_points=evidence[:2] or ["최종 결제 금액 캡처", "배송비와 쿠폰 조건"],
        counter_condition=condition,
    )


def _cheaper_alternative_objection(
    request: DecisionDefenseRequest,
    reasons: list[str],
) -> DecisionDefenseObjection:
    alternatives = [alt for alt in request.alternatives if alt.title.strip()]
    if alternatives:
        lines = [
            f"{alt.title}: {alt.reason_not_selected or '목적 적합도 또는 구매 안정성이 낮음'}"
            for alt in alternatives[:3]
        ]
        answer = "더 싼 후보는 봤지만 " + " / ".join(lines)
        proof = lines
    else:
        answer = "더 싼 후보가 있다면 가격뿐 아니라 RAM/SSD/GPU, AS, 반품, 배송 증거까지 같은 기준으로 비교해야 합니다."
        proof = reasons[:2]
    return DecisionDefenseObjection(
        objection_id="cheaper_alternative",
        question="더 싼 후보를 사면 안 되나요?",
        status=CheckStatus.warning if alternatives else CheckStatus.ok,
        answer=answer,
        proof_points=proof,
        counter_condition="더 싼 후보가 필수 사양과 AS/반품 조건까지 같으면 재비교",
    )


def _purpose_fit_objection(
    request: DecisionDefenseRequest,
    reasons: list[str],
) -> DecisionDefenseObjection:
    return DecisionDefenseObjection(
        objection_id="purpose_fit",
        question="내 용도에 과하거나 부족하지 않나요?",
        status=CheckStatus.ok,
        answer=(
            f"목적 {request.purpose} 기준으로 고른 이유는 "
            f"{' / '.join(reasons[:3])}입니다."
        ),
        proof_points=reasons[:3],
        counter_condition="실제 사용 목적이 바뀌면 예산/성능 우선순위를 다시 입력",
    )


def _risk_objection(
    watchouts: list[str],
    status: CheckStatus,
) -> DecisionDefenseObjection:
    if watchouts:
        answer = f"남은 리스크는 {', '.join(watchouts[:4])}입니다. 이 항목을 캡처나 판매자 답변으로 닫아야 합니다."
        proof = watchouts[:4]
    else:
        answer = "현재 공유할 치명 리스크는 없습니다. 그래도 결제 직전 옵션명과 AS/반품 조건은 다시 캡처해야 합니다."
        proof = ["옵션명", "AS/반품", "배송/재고"]
    return DecisionDefenseObjection(
        objection_id="risk",
        question="나중에 후회할 리스크는 없나요?",
        status=status if watchouts else CheckStatus.ok,
        answer=answer,
        proof_points=proof,
        counter_condition="리퍼/해외/반품 불가/AS 불가가 남으면 결제 보류",
    )


def _timing_objection(
    request: DecisionDefenseRequest,
    watchouts: list[str],
) -> DecisionDefenseObjection:
    wait_signal = any("가격" in item or "쿠폰" in item or "재고" in item for item in watchouts)
    return DecisionDefenseObjection(
        objection_id="timing",
        question="지금 사지 말고 기다려야 하지 않나요?",
        status=CheckStatus.warning if wait_signal else CheckStatus.ok,
        answer=(
            "가격/쿠폰/재고가 흔들리는 신호가 있어 목표가 감시 후 재검토가 낫습니다."
            if wait_signal
            else "예산 안이고 사양/보호 조건이 닫혀 있다면 기다림보다 결제 전 잠금 검수가 더 중요합니다."
        ),
        proof_points=watchouts[:3] or ["예산 안", "목적 적합", "결제 전 잠금 검수"],
        counter_condition="목표가와 현재가 차이가 크거나 쿠폰 조건이 불안하면 가격 대기",
    )


def _trust_objection(evidence: list[str]) -> DecisionDefenseObjection:
    ready = len(evidence) >= 3
    return DecisionDefenseObjection(
        objection_id="trust",
        question="근거가 충분하고 추천이 편향되지 않았나요?",
        status=CheckStatus.ok if ready else CheckStatus.warning,
        answer=(
            f"확보 증거는 {', '.join(evidence[:5])}입니다."
            if evidence
            else "아직 증거가 부족합니다. 추천 순위보다 결제 화면 캡처와 판매자 답변을 먼저 확보하세요."
        ),
        proof_points=evidence[:5] or ["최종가", "옵션명", "AS/반품 조건"],
        counter_condition="제휴 여부와 추천 근거를 분리하고 가격은 결제 전 다시 확인",
    )


def _comparisons(
    request: DecisionDefenseRequest,
    reasons: list[str],
    watchouts: list[str],
) -> list[DecisionDefenseComparison]:
    alternative = request.alternatives[0] if request.alternatives else None
    alt_text = (
        f"{alternative.title} {_money(alternative.price_krw)}"
        if alternative
        else "대체 후보 미입력"
    )
    return [
        DecisionDefenseComparison(
            criterion="가격",
            selected_choice=f"{_title(request)} {_money(request.final_price_krw)}",
            alternative_view=alt_text,
            reviewer_takeaway="최저가만 같아도 배송비, 쿠폰, AS 조건이 다르면 같은 선택이 아닙니다.",
        ),
        DecisionDefenseComparison(
            criterion="용도 적합도",
            selected_choice=reasons[0],
            alternative_view=(
                alternative.reason_not_selected
                if alternative and alternative.reason_not_selected
                else "대체 후보는 같은 목적 기준으로 다시 확인 필요"
            ),
            reviewer_takeaway="실제 용도 기준을 바꾸면 추천도 바뀌므로 용도를 먼저 합의합니다.",
        ),
        DecisionDefenseComparison(
            criterion="리스크",
            selected_choice=", ".join(watchouts[:3]) if watchouts else "치명 리스크 없음",
            alternative_view="더 싼 후보일수록 반품/AS/리퍼/해외 조건을 먼저 확인",
            reviewer_takeaway="남은 리스크가 결제 전 캡처로 닫히지 않으면 승인하지 않습니다.",
        ),
    ]


def _proof_checklist(
    request: DecisionDefenseRequest,
    evidence: list[str],
    watchouts: list[str],
) -> list[str]:
    base = [
        "최종 결제 금액과 배송비/쿠폰/카드 할인 화면",
        "상품명, 옵션명, CPU/GPU/RAM/SSD/OS 선택 상태",
        "판매자명, 재고, 배송 예정일",
        "AS 주체, 보증 기간, 반품/교환 조건",
    ]
    if request.alternatives:
        base.append("비교한 대체 후보의 제외 이유")
    return list(dict.fromkeys(evidence + watchouts + base))[:10]


def _reviewer_questions(
    request: DecisionDefenseRequest,
    objections: list[DecisionDefenseObjection],
) -> list[str]:
    questions = [
        f"{_title(request)}를 이 예산과 용도 기준으로 사면 반대할 이유가 있나요?",
        "더 싼 후보가 같은 사양, 같은 AS/반품 조건, 같은 최종가 기준으로 더 낫나요?",
        "결제 전 캡처해야 할 증거 중 빠진 것이 있나요?",
    ]
    questions.extend(item.question for item in objections if item.status != CheckStatus.ok)
    return list(dict.fromkeys(questions))[:6]


def _copy_variants(
    request: DecisionDefenseRequest,
    title: str,
    reviewer_brief: str,
    status: CheckStatus,
) -> list[ApprovalCopyVariant]:
    status_label = "승인 가능" if status == CheckStatus.ok else "조건부 검토" if status == CheckStatus.warning else "보류 검토"
    return [
        ApprovalCopyVariant(
            channel="kakao",
            label="지인 공유",
            copy_text=f"{title} 구매 검토 부탁해.\n{reviewer_brief}\n반대할 이유 있으면 결제 전에 알려줘.",
            cta_label="지인 검토 요청",
        ),
        ApprovalCopyVariant(
            channel="team",
            label="팀 승인",
            copy_text=(
                f"[{status_label}] {title}\n"
                f"예산 {_money(request.budget_krw)}, 최종가 {_money(request.final_price_krw)}\n"
                f"{reviewer_brief}\n승인/보류 의견 부탁드립니다."
            ),
            cta_label="팀 승인 요청",
        ),
        ApprovalCopyVariant(
            channel="community",
            label="커뮤니티 검토",
            copy_text=(
                f"{title} 구매 직전 검토 요청\n"
                f"용도: {request.purpose}\n"
                f"예산/최종가: {_money(request.budget_krw)} / {_money(request.final_price_krw)}\n"
                "더 나은 대체 후보나 놓친 리스크가 있을까요?"
            ),
            cta_label="커뮤니티 검토 요청",
        ),
    ]


def _headline(title: str, status: CheckStatus) -> str:
    if status == CheckStatus.blocker:
        return f"{title}는 공유 전에 반대 사유를 먼저 닫아야 합니다."
    if status == CheckStatus.warning:
        return f"{title}는 조건부로 방어 가능한 구매 결정입니다."
    return f"{title}는 공유받은 검토자에게 방어 가능한 선택입니다."


def _summary(
    request: DecisionDefenseRequest,
    status: CheckStatus,
    score: int,
    watchouts: list[str],
) -> str:
    status_text = "blocker" if status == CheckStatus.blocker else "warning" if status == CheckStatus.warning else "ok"
    return (
        f"방어 점수 {score}점, 상태 {status_text}. "
        f"예산 {_money(request.budget_krw)}, 최종가 {_money(request.final_price_krw)}, "
        f"남은 리스크 {len(watchouts)}개 기준으로 검토자 질문과 답변을 정리했습니다."
    )


def _reviewer_brief(
    *,
    request: DecisionDefenseRequest,
    title: str,
    decision: str,
    status: CheckStatus,
    reasons: list[str],
    watchouts: list[str],
) -> str:
    decision_label = "구매 가능" if decision == "ready" else "확인 후 구매" if decision == "verify" else "구매 보류"
    status_label = "방어 가능" if status == CheckStatus.ok else "조건부 방어" if status == CheckStatus.warning else "방어 약함"
    return (
        f"{title}: {decision_label}, {status_label}. "
        f"선택 이유는 {' / '.join(reasons[:3])}. "
        f"남은 확인은 {', '.join(watchouts[:3]) if watchouts else '결제 전 최종가와 옵션명 캡처'}입니다."
    )


def _analysis_prefill(
    request: DecisionDefenseRequest,
    decision: str,
    status: CheckStatus,
    objections: list[DecisionDefenseObjection],
) -> str:
    objection_text = "; ".join(
        f"{item.question} -> {item.status}: {item.counter_condition}"
        for item in objections[:4]
    )
    return (
        f"{_title(request)} 구매 결정 방어 브리프를 검토해줘. "
        f"decision={decision}, defense_status={status}, 예산 {_money(request.budget_krw)}, "
        f"최종가 {_money(request.final_price_krw)}, 목적 {request.purpose}. "
        f"반대 질문: {objection_text}"
    )


def _share_copy(
    request: DecisionDefenseRequest,
    title: str,
    status: CheckStatus,
    reviewer_brief: str,
) -> str:
    return (
        "SpecPilot AI 구매 결정 방어 브리프\n"
        f"- 후보: {title}\n"
        f"- 상태: {status}\n"
        f"- 예산/최종가: {_money(request.budget_krw)} / {_money(request.final_price_krw)}\n"
        f"- 요약: {reviewer_brief}\n"
        "반대할 이유, 더 나은 대체 후보, 빠진 증거가 있으면 결제 전에 알려주세요."
    )


def _next_actions(status: CheckStatus, watchouts: list[str]) -> list[str]:
    if status == CheckStatus.blocker:
        return [
            "공유하기 전에 blocker성 watchout을 판매자 답변이나 대체 후보 비교로 닫으세요.",
            "검토자에게는 결제 보류 전제로 반대 사유를 먼저 물어보세요.",
            "대체 후보 rescue 또는 체크아웃 잠금 검수로 다시 연결하세요.",
        ]
    if status == CheckStatus.warning:
        return [
            "공유 문구를 가족/팀/커뮤니티에 보내고 반대 의견을 결제 전까지 받으세요.",
            "watchout이 남아 있으면 증거 캡처 후 구매 실행 패키지로 넘기세요.",
            "가격/재고 리스크가 나오면 목표가 감시로 전환하세요.",
        ]
    return [
        "공유 브리프로 마지막 반대 의견을 받은 뒤 체크아웃 잠금 검수로 결제 화면을 확인하세요.",
        "결제 후 구매 후 케어와 첫 부팅 세팅 검수로 결과를 닫으세요.",
        "구매 결과를 기록해 다음 추천 품질에 반영하세요.",
    ]
