from collections import Counter

from specpilot_ai.core.models import (
    BenchmarkEvidence,
    PriceSnapshot,
    ReviewInsight,
    SourceKind,
    SourceTrustAssessment,
    TrustGrade,
    TrustPolicySummary,
)

SOURCE_POLICIES = {
    "official_store": {
        "name": "공식 스토어",
        "kind": SourceKind.official,
        "confidence": 0.92,
        "freshness_minutes": 60,
        "cache_ttl_minutes": 180,
        "notes": ["옵션명과 보증 조건 검증에 우선 사용합니다."],
    },
    "price_compare": {
        "name": "가격 비교 소스",
        "kind": SourceKind.price,
        "confidence": 0.88,
        "freshness_minutes": 15,
        "cache_ttl_minutes": 60,
        "notes": ["최저가가 아니라 배송비, 쿠폰, 카드 할인을 반영한 실구매가를 사용합니다."],
    },
    "pc_builder": {
        "name": "조립 PC 견적 소스",
        "kind": SourceKind.price,
        "confidence": 0.84,
        "freshness_minutes": 30,
        "cache_ttl_minutes": 90,
        "notes": ["조립비와 OS 포함 여부를 별도 항목으로 분리합니다."],
    },
    "open_market": {
        "name": "오픈마켓",
        "kind": SourceKind.price,
        "confidence": 0.78,
        "freshness_minutes": 20,
        "cache_ttl_minutes": 45,
        "notes": ["판매자, 재고, 쿠폰 조건 변동이 커서 구매 직전 재확인이 필요합니다."],
    },
    "review_signal": {
        "name": "리뷰 리스크 신호",
        "kind": SourceKind.review,
        "confidence": 0.82,
        "freshness_minutes": 240,
        "cache_ttl_minutes": 720,
        "notes": ["확정 표현 대신 반복 불만과 근거 수만 표시합니다."],
    },
    "benchmark": {
        "name": "벤치마크 근거",
        "kind": SourceKind.benchmark,
        "confidence": 0.8,
        "freshness_minutes": 1440,
        "cache_ttl_minutes": 4320,
        "notes": ["목적별 성능 판단에 쓰되 가격 순위보다 우선하지 않습니다."],
    },
}


def build_source_trust(
    prices: list[PriceSnapshot],
    reviews: list[ReviewInsight],
    benchmarks: list[BenchmarkEvidence],
) -> list[SourceTrustAssessment]:
    counts = Counter(price.source_type for price in prices)
    if reviews:
        counts["review_signal"] = sum(review.evidence_count for review in reviews)
    if benchmarks:
        counts["benchmark"] = len(benchmarks)

    assessments = [
        _assessment(source_type, evidence_count)
        for source_type, evidence_count in sorted(counts.items())
    ]
    return sorted(assessments, key=lambda item: (item.kind.value, item.source_type))


def build_trust_policy(
    assessments: list[SourceTrustAssessment] | None = None,
) -> TrustPolicySummary:
    return TrustPolicySummary(
        cache_policy=(
            "가격 소스는 45-180분 캐시하고, 리뷰/벤치마크 근거는 12-72시간 캐시합니다."
        ),
        stale_price_action=(
            "캐시 만료 또는 재고 불명확 가격은 추천 점수에 패널티를 주고 "
            "구매 직전 재확인을 요구합니다."
        ),
        affiliate_disclosure=(
            "제휴 링크가 붙더라도 추천 순위는 목적 적합도, 실구매가, "
            "호환성, 리뷰 신뢰도 기준으로 계산합니다."
        ),
        fairness_rules=[
            "제휴 판매처만 단독 추천하지 않고 비제휴 대안 후보를 함께 비교합니다.",
            "출처 없는 가격과 스펙은 추천 근거나 점수 계산에 사용하지 않습니다.",
            "호환성 차단 이슈가 있으면 가격이 낮아도 TOP 추천에서 밀려납니다.",
        ],
        review_rules=[
            "리뷰는 단정 문장이 아니라 반복 불만, 리스크 신호, 근거 수로 표시합니다.",
            "신뢰도 0.8 미만 또는 리스크 플래그가 있는 근거는 관리자 검수 큐에 넣습니다.",
        ],
        source_assessments=assessments or [_assessment(source, 0) for source in SOURCE_POLICIES],
    )


def _assessment(source_type: str, evidence_count: int) -> SourceTrustAssessment:
    policy = SOURCE_POLICIES.get(
        source_type,
        {
            "name": source_type,
            "kind": SourceKind.price,
            "confidence": 0.7,
            "freshness_minutes": 60,
            "cache_ttl_minutes": 60,
            "notes": ["알 수 없는 소스 유형이라 운영자 검수가 필요합니다."],
        },
    )
    confidence = float(policy["confidence"])
    return SourceTrustAssessment(
        source_type=source_type,
        source_name=str(policy["name"]),
        kind=policy["kind"],
        trust_grade=_grade(confidence),
        confidence=confidence,
        freshness_minutes=int(policy["freshness_minutes"]),
        cache_ttl_minutes=int(policy["cache_ttl_minutes"]),
        evidence_count=evidence_count,
        requires_human_review=confidence < 0.8,
        policy_notes=list(policy["notes"]),
    )


def _grade(confidence: float) -> TrustGrade:
    if confidence >= 0.85:
        return TrustGrade.high
    if confidence >= 0.8:
        return TrustGrade.medium
    return TrustGrade.review_required
