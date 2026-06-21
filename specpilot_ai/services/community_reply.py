from datetime import UTC, datetime

from specpilot_ai.core.models import (
    CheckStatus,
    CommunityEvidenceRequest,
    CommunityReplyCard,
    CommunityReplyKitRequest,
    PublicCommunityReplyKit,
    PurchaseJourneyKitRequest,
    PurchaseQuestionTriageRequest,
)

RISK_TERMS = ["리퍼", "전시", "중고", "해외", "병행", "반품 불가", "반품불가", "AS 불가", "as 불가"]
SPEC_TERMS = ["rtx", "radeon", "ryzen", "core", "ram", "ssd", "tgp", "프리도스", "freedos"]
REVIEW_TERMS = ["발열", "소음", "팬", "불량", "꺼짐", "빛샘", "배터리", "AS", "as"]


def build_public_community_reply_kit(
    request: CommunityReplyKitRequest,
    generated_at: datetime | None = None,
) -> PublicCommunityReplyKit:
    generated_at = generated_at or datetime.now(UTC)
    title = _title(request)
    text = " ".join(
        [
            request.buyer_question,
            request.product_title,
            request.candidate_summary,
            request.usage_context,
            " ".join(request.risk_notes),
            " ".join(request.missing_evidence),
        ]
    )
    risk_flags = _risk_flags(request, text)
    evidence_requests = _evidence_requests(request, text)
    status = _status(risk_flags, evidence_requests)
    score = _score(risk_flags, evidence_requests, request)
    reply_cards = _reply_cards(request, status, score, risk_flags, evidence_requests)
    primary_reply = reply_cards[0].copy_text

    return PublicCommunityReplyKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        community_channel=_channel(request),
        product_title=title,
        seller_name=_seller(request),
        reply_status=status,
        reply_score=score,
        headline=_headline(title, status),
        summary=_summary(request, score, risk_flags, evidence_requests),
        primary_reply=primary_reply,
        reply_cards=reply_cards,
        risk_flags=risk_flags,
        evidence_requests=evidence_requests,
        posting_rules=_posting_rules(),
        triage_prefill=_triage_prefill(request, title),
        journey_prefill=_journey_prefill(request, title, risk_flags),
        analysis_prefill=_analysis_prefill(request, score, risk_flags, evidence_requests),
        share_copy=_share_copy(request, status, score),
        next_actions=_next_actions(status),
    )


def _title(request: CommunityReplyKitRequest) -> str:
    return request.product_title.strip() or "구매 후보"


def _seller(request: CommunityReplyKitRequest) -> str:
    return request.seller_name.strip() or "판매자"


def _channel(request: CommunityReplyKitRequest) -> str:
    return request.community_channel.strip() or "community"


def _lines(items: list[str], limit: int = 10) -> list[str]:
    return [item.strip() for item in items if item.strip()][:limit]


def _risk_flags(request: CommunityReplyKitRequest, text: str) -> list[str]:
    flags = [item for item in _lines(request.risk_notes) if item]
    flags.extend(term for term in RISK_TERMS if term.lower() in text.lower())
    if request.final_price_krw is not None and request.final_price_krw > request.budget_krw * 1.08:
        flags.append("최종가가 예산보다 8% 이상 높습니다.")
    elif request.final_price_krw is not None and request.final_price_krw > request.budget_krw:
        flags.append("최종가가 예산을 초과합니다.")
    review_hits = [term for term in REVIEW_TERMS if term in text]
    if review_hits:
        flags.append(f"후기 리스크 문구 확인 필요: {', '.join(review_hits[:4])}")
    return list(dict.fromkeys(flags))[:8]


def _evidence_requests(request: CommunityReplyKitRequest, text: str) -> list[CommunityEvidenceRequest]:
    requests: list[CommunityEvidenceRequest] = []
    missing = _lines(request.missing_evidence)
    for index, item in enumerate(missing[:4], start=1):
        requests.append(
            CommunityEvidenceRequest(
                evidence_id=f"missing_{index}",
                label=item,
                status=CheckStatus.warning,
                reason="답변자가 결제 가능 여부를 판단하기 전에 확인해야 하는 누락 증거입니다.",
                request_text=f"{item} 캡처나 판매자 답변을 추가해 주세요.",
            )
        )
    if request.final_price_krw is None:
        requests.append(
            CommunityEvidenceRequest(
                evidence_id="final_price",
                label="최종 결제 금액",
                status=CheckStatus.warning,
                reason="배송비, 쿠폰, 카드 할인을 반영한 금액이 없으면 가격 판단이 흔들립니다.",
                request_text="장바구니 또는 결제 직전 최종가를 알려 주세요.",
            )
        )
    if not any(term.lower() in text.lower() for term in SPEC_TERMS):
        requests.append(
            CommunityEvidenceRequest(
                evidence_id="core_specs",
                label="핵심 사양",
                status=CheckStatus.warning,
                reason="CPU/GPU/RAM/SSD 또는 노트북 TGP/패널 조건이 필요합니다.",
                request_text="상품명과 옵션명에 적힌 CPU, GPU, RAM, SSD, OS 조건을 붙여 주세요.",
            )
        )
    if not any(term in text for term in ["반품", "교환", "보증", "AS", "as"]):
        requests.append(
            CommunityEvidenceRequest(
                evidence_id="policy",
                label="반품/AS 조건",
                status=CheckStatus.warning,
                reason="커뮤니티 답글에서 가장 자주 놓치는 결제 후 보호 조건입니다.",
                request_text="반품 가능 기간, 초기 불량 교환, 국내 AS 주체를 확인해 주세요.",
            )
        )
    return requests[:8]


def _status(
    risk_flags: list[str],
    evidence_requests: list[CommunityEvidenceRequest],
) -> CheckStatus:
    if any("반품 불가" in flag or "AS 불가" in flag or "예산보다 8%" in flag for flag in risk_flags):
        return CheckStatus.blocker
    if risk_flags or evidence_requests:
        return CheckStatus.warning
    return CheckStatus.ok


def _score(
    risk_flags: list[str],
    evidence_requests: list[CommunityEvidenceRequest],
    request: CommunityReplyKitRequest,
) -> int:
    score = 94
    score -= len(risk_flags) * 9
    score -= len(evidence_requests) * 6
    score += min(10, len(_lines(request.ready_evidence)) * 2)
    if any("반품 불가" in flag or "AS 불가" in flag for flag in risk_flags):
        score = min(score, 52)
    elif risk_flags or evidence_requests:
        score = min(score, 84)
    return max(0, min(100, score))


def _reply_cards(
    request: CommunityReplyKitRequest,
    status: CheckStatus,
    score: int,
    risk_flags: list[str],
    evidence_requests: list[CommunityEvidenceRequest],
) -> list[CommunityReplyCard]:
    label = "구매 가능" if status == CheckStatus.ok else "확인 후 판단" if status == CheckStatus.warning else "구매 보류"
    risks = ", ".join(risk_flags[:3]) if risk_flags else "큰 blocker는 아직 보이지 않습니다."
    evidence = ", ".join(item.label for item in evidence_requests[:3]) if evidence_requests else "최종가/옵션/AS 증거"
    primary = (
        f"제 기준으론 {label} 쪽입니다. SpecPilot 기준 점수는 {score}점이고, "
        f"먼저 볼 리스크는 {risks}입니다. 결제 전에는 {evidence}를 캡처해 두세요."
    )
    if status == CheckStatus.blocker:
        primary = (
            f"저라면 지금은 결제 보류합니다. {risks}가 남아 있어서 가격보다 반품/AS와 "
            f"최종 옵션 증거를 먼저 닫아야 합니다. {evidence} 확인 전에는 결제하지 마세요."
        )
    short = f"{_title(request)}: {label} ({score}점). 리스크: {risks}. 추가 증거: {evidence}."
    checklist = "\n".join(
        [
            "결제 전 체크:",
            "1. 최종가와 옵션명을 같은 화면에서 캡처",
            "2. 반품/교환/AS 주체 확인",
            "3. 반복 후기 리스크가 내 사용 목적과 충돌하는지 확인",
        ]
    )
    return [
        CommunityReplyCard(
            card_id="primary_comment",
            label="커뮤니티 답글",
            status=status,
            copy_text=primary,
            use_when="견적 질문 글에 공개 댓글로 바로 답할 때",
        ),
        CommunityReplyCard(
            card_id="short_reply",
            label="짧은 답글",
            status=status,
            copy_text=short,
            use_when="카톡, 댓글, DM에서 한 줄로 판단만 남길 때",
        ),
        CommunityReplyCard(
            card_id="checklist_reply",
            label="체크리스트 답글",
            status=CheckStatus.warning if status != CheckStatus.blocker else CheckStatus.blocker,
            copy_text=checklist,
            use_when="상대가 아직 상품 페이지/장바구니 캡처를 안 올렸을 때",
        ),
    ]


def _posting_rules() -> list[str]:
    return [
        "단정적인 구매 강요 대신 확인해야 할 증거와 중단 조건을 같이 씁니다.",
        "제휴 링크나 판매처 유도 문구를 넣지 않고 판단 기준만 공유합니다.",
        "주문번호, 연락처, 결제 카드 같은 개인정보는 올리지 않게 안내합니다.",
    ]


def _triage_prefill(
    request: CommunityReplyKitRequest,
    title: str,
) -> PurchaseQuestionTriageRequest:
    return PurchaseQuestionTriageRequest(
        category=request.category,
        buyer_question=request.buyer_question,
        product_title=title,
        listing_text=request.candidate_summary,
        cart_total_krw=request.final_price_krw,
        budget_krw=request.budget_krw,
        purchase_stage="community_reply",
        source="community_reply",
    )


def _journey_prefill(
    request: CommunityReplyKitRequest,
    title: str,
    risk_flags: list[str],
) -> PurchaseJourneyKitRequest:
    return PurchaseJourneyKitRequest(
        category=request.category,
        buyer_question=request.buyer_question,
        product_title=title,
        seller_name=_seller(request),
        listing_text=request.candidate_summary,
        review_snippets=_lines(request.risk_notes),
        budget_krw=request.budget_krw,
        final_price_krw=request.final_price_krw,
        purchase_stage="community_reply",
        ready_evidence=request.ready_evidence,
        missing_evidence=request.missing_evidence or risk_flags[:3],
        urgency="커뮤니티 답변 후 결제 전",
        share_audience=_channel(request),
        source="community_reply",
    )


def _headline(title: str, status: CheckStatus) -> str:
    if status == CheckStatus.blocker:
        return f"{title} 답글은 구매 보류 기준으로 써야 합니다."
    if status == CheckStatus.warning:
        return f"{title} 답글은 확인 요청과 조건부 판단을 같이 써야 합니다."
    return f"{title} 답글은 결제 전 캡처만 고정하면 됩니다."


def _summary(
    request: CommunityReplyKitRequest,
    score: int,
    risk_flags: list[str],
    evidence_requests: list[CommunityEvidenceRequest],
) -> str:
    price = f"{request.final_price_krw:,}원" if request.final_price_krw is not None else "최종가 미입력"
    return (
        f"{_channel(request)} 답변용 점수 {score}점, 최종가 {price}, "
        f"리스크 {len(risk_flags)}개, 추가 증거 {len(evidence_requests)}개입니다. "
        "공개 댓글, 짧은 답장, 체크리스트 문구를 함께 제공합니다."
    )


def _analysis_prefill(
    request: CommunityReplyKitRequest,
    score: int,
    risk_flags: list[str],
    evidence_requests: list[CommunityEvidenceRequest],
) -> str:
    return (
        f"{_title(request)} 커뮤니티 구매 질문에 답할 기준을 분석해줘. "
        f"질문={request.buyer_question}, 예산={request.budget_krw:,}원, "
        f"최종가={request.final_price_krw or '미입력'}, 용도={request.usage_context}, "
        f"답변 점수={score}, 리스크={risk_flags[:4]}, "
        f"추가 증거={[item.label for item in evidence_requests[:4]]}. "
        "커뮤니티에 올릴 답글과 결제 전 중단 조건을 같이 정리해줘."
    )


def _share_copy(request: CommunityReplyKitRequest, status: CheckStatus, score: int) -> str:
    label = "구매 가능" if status == CheckStatus.ok else "확인 필요" if status == CheckStatus.warning else "구매 보류"
    return "\n".join(
        [
            "SpecPilot AI 커뮤니티 구매 답변",
            f"- 후보: {_title(request)}",
            f"- 답변 기준: {label} ({score}점)",
            f"- 채널: {_channel(request)}",
            "결제 전 최종가, 옵션명, 반품/AS 조건 캡처를 먼저 확인하세요.",
        ]
    )


def _next_actions(status: CheckStatus) -> list[str]:
    if status == CheckStatus.blocker:
        return [
            "구매 보류 답글을 먼저 복사하고 반품/AS 또는 예산 초과 증거를 요청하세요.",
            "판매자 답변을 받은 뒤 구매 여정 오케스트레이터로 다시 판정하세요.",
        ]
    if status == CheckStatus.warning:
        return [
            "조건부 답글을 복사하고 누락 증거를 받은 뒤 최종 구매 판정을 실행하세요.",
            "리뷰 리스크 또는 보증/반품 검수 키트로 위험 문구를 닫으세요.",
        ]
    return [
        "공개 답글을 복사하고 결제 전 최종가/옵션/AS 캡처를 고정하세요.",
        "구매 후 케어 키트로 반품/교환 마감과 첫 부팅 검수를 이어가세요.",
    ]
