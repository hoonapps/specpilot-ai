from collections import Counter
from datetime import UTC, datetime

from specpilot_ai.core.models import (
    BenchmarkEvidence,
    CheckStatus,
    PriceSnapshot,
    PrivacyDataCategory,
    PrivacyPolicySummary,
    ReviewInsight,
    SourceKind,
    SourceTrustAssessment,
    TrustCenterDashboard,
    TrustCenterGate,
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


def build_privacy_policy() -> PrivacyPolicySummary:
    return PrivacyPolicySummary(
        headline=(
            "구매 판단에 필요한 최소 데이터만 저장하고 연락처 원문은 "
            "공개 표면에 노출하지 않습니다."
        ),
        data_minimization=(
            "분석 요청, 저장 리포트, 공개 공유 토큰, 알림/발송 운영 이벤트, "
            "피드백과 베타 리드는 구매 의사결정 개선에 필요한 필드만 분리해 저장합니다."
        ),
        public_report_policy=(
            "공개 리포트는 공유 토큰이 발급된 단일 리포트만 조회하며 워크스페이스 내부 "
            "목록, 연락처, 운영 메모, 결제 검수 이력은 노출하지 않습니다."
        ),
        contact_policy=(
            "피드백, 베타 리드, 구독 의향, 완료 리포트, 알림 발송 이벤트의 연락처는 "
            "마스킹된 값으로 운영 표면에 표시합니다."
        ),
        retention_policy=(
            "분석/리포트 근거는 180일, 발송/알림 이벤트는 90일, 피드백/리드는 365일 "
            "기준으로 보존하고 운영 대시보드에서 보존 초과 항목을 점검합니다."
        ),
        user_controls=[
            "공유 리포트는 워크스페이스 소유자가 언제든 공유 해제할 수 있습니다.",
            "구매 결과의 주문번호는 원문 대신 마스킹된 값만 저장합니다.",
            "베타/요금제 연락은 동의가 있는 경우에만 접수합니다.",
            "운영자는 데이터 거버넌스 대시보드에서 보존 초과와 원문 연락처 표면을 점검합니다.",
        ],
        prohibited_data=[
            "주민등록번호, 카드번호, 계좌번호 등 결제 민감정보",
            "사이트 로그인 비밀번호 또는 판매처 계정 정보",
            "업무상 비밀 문서 원문이나 제3자의 동의 없는 연락처",
        ],
        data_categories=[
            PrivacyDataCategory(
                category="analysis",
                label="분석 요청과 추천 리포트",
                stored_fields=["구매 조건", "후보 비교", "출처 근거", "품질 감사", "trace span"],
                masking="연락처 없음. 공개 리포트는 share token 단위로만 접근",
                retention="기본 180일 보존 후 운영 대시보드에서 정리 대상 표시",
                user_control="저장 리포트 공유 생성/해제",
            ),
            PrivacyDataCategory(
                category="contact",
                label="피드백/베타/요금제 연락처",
                stored_fields=["마스킹된 이메일 또는 연락처", "동의 여부", "사용 목적"],
                masking="예: bu***@example.com",
                retention="기본 365일 보존",
                user_control="동의 없는 리드는 접수하지 않음",
            ),
            PrivacyDataCategory(
                category="delivery",
                label="알림과 완료 리포트 발송 이벤트",
                stored_fields=["마스킹된 대상", "발송 상태", "열람/클릭/반송 이벤트"],
                masking="운영 콘솔에는 마스킹된 대상만 표시",
                retention="기본 90일 보존",
                user_control="unsubscribe 제외 정책과 채널 비활성화",
            ),
        ],
    )


def build_trust_center() -> TrustCenterDashboard:
    trust_policy = build_trust_policy()
    privacy_policy = build_privacy_policy()
    gates = [
        TrustCenterGate(
            area="recommendation_fairness",
            label="추천 공정성",
            status=CheckStatus.ok,
            public_message="제휴 여부와 클릭 수는 추천 순위 계산에 직접 반영하지 않습니다.",
            evidence=[
                "추천 순위 기준은 목적 적합도, 실구매가, 호환성, 리뷰 신뢰도입니다.",
                "제휴 링크가 있으면 비제휴 대안을 함께 비교하도록 정책 경고를 냅니다.",
            ],
            buyer_impact="사용자는 광고성 단일 링크가 아니라 대안과 근거를 함께 확인합니다.",
            next_action=(
                "공개 리포트의 구매 링크 영역에 제휴 고지와 "
                "비제휴 대안 여부를 계속 표시합니다."
            ),
        ),
        TrustCenterGate(
            area="source_verification",
            label="출처 검수",
            status=CheckStatus.warning,
            public_message=(
                "낮은 신뢰도, 만료 가격, 리스크 플래그가 있는 근거는 "
                "관리자 검수 대상으로 분리합니다."
            ),
            evidence=[
                "가격 캐시 만료 시 구매 직전 재확인을 요구합니다.",
                "신뢰도 0.8 미만 소스와 unknown provider는 검수 큐로 이동합니다.",
            ],
            buyer_impact="실제 결제 화면과 추천 리포트의 가격/옵션 차이를 줄입니다.",
            next_action=(
                "live fetch provider 정책과 검수 큐 승인 이력을 "
                "공개 운영 증거로 더 세분화합니다."
            ),
        ),
        TrustCenterGate(
            area="privacy",
            label="개인정보 최소화",
            status=CheckStatus.ok,
            public_message=(
                "공개 표면에는 연락처 원문, 주문번호 원문, "
                "내부 운영 메모를 노출하지 않습니다."
            ),
            evidence=[
                "피드백, 베타 리드, 구독 의향, 발송 대상은 마스킹 값으로 표시합니다.",
                "공개 리포트는 단일 share token으로만 조회합니다.",
            ],
            buyer_impact=(
                "공유 리포트를 열어도 워크스페이스 내부 데이터와 "
                "연락처가 노출되지 않습니다."
            ),
            next_action=(
                "보존 초과 항목과 원문 연락처 표면은 데이터 거버넌스 "
                "대시보드에서 계속 차단합니다."
            ),
        ),
        TrustCenterGate(
            area="human_review",
            label="사람 검수",
            status=CheckStatus.warning,
            public_message="추천 근거가 불확실하면 자동 추천보다 검수 후 구매 판정을 우선합니다.",
            evidence=[
                "구매 판정은 점수, 목표가, 예산 초과, 호환성 차단, 출처 검수 신호를 함께 봅니다.",
                "결제 전 검수는 최종 결제 금액, 옵션/사양, 판매자 답변, 리스크 승인을 기록합니다.",
            ],
            buyer_impact="조건이 불확실한 추천은 즉시 구매가 아니라 확인 필요 상태로 보입니다.",
            next_action="검수 승인/반려 사유를 공개 리포트의 신뢰 배지와 연결합니다.",
        ),
    ]
    return TrustCenterDashboard(
        generated_at=datetime.now(UTC).isoformat(),
        headline="추천보다 먼저 신뢰 기준을 공개합니다",
        public_summary=(
            "SpecPilot AI는 PC/노트북 구매 추천에서 가격, 제휴, 개인정보, "
            "출처 검수 기준을 분리해 공개합니다."
        ),
        overall_status=CheckStatus.warning,
        trust_policy=trust_policy,
        privacy_policy=privacy_policy,
        public_commitments=[
            "최저가 단일 링크가 아니라 실구매가, 배송비, 쿠폰, 카드 할인, 재고를 함께 봅니다.",
            "제휴 링크는 고지하고 비제휴 대안과 함께 노출합니다.",
            "출처 없는 가격, 스펙, 리뷰는 추천 근거나 점수 계산에 사용하지 않습니다.",
            "공개 공유 리포트는 토큰이 발급된 단일 리포트만 보여줍니다.",
            "사용자가 결제 전 확인할 질문과 보류 사유를 추천 결과보다 먼저 보여줍니다.",
        ],
        buyer_rights=[
            "공개 리포트에서 제휴 여부와 비제휴 대안 여부를 확인할 권리",
            "가격 캐시 만료와 검수 필요 여부를 결제 전에 확인할 권리",
            "공유 리포트 접근을 워크스페이스 소유자가 해제할 권리",
            "연락 동의 없이 베타/요금제 후속 연락을 받지 않을 권리",
        ],
        operational_gates=gates,
        risk_disclosures=[
            "오픈마켓 가격과 쿠폰은 짧은 시간 안에 변동될 수 있습니다.",
            "벤치마크는 목적별 참고 근거이며 실제 체감 성능을 보장하지 않습니다.",
            "제휴 수익은 추천 순위에 직접 반영하지 않지만 링크 영역에는 명확히 고지됩니다.",
            "중대한 호환성 차단 또는 출처 검수 신호가 있으면 결제 전 검수를 권장합니다.",
        ],
        escalation_paths=[
            "가격/옵션 불일치: 결제 전 검수 또는 상품 페이지 근거 검수 큐로 전환",
            "제휴 고지 누락: 구매 링크 거버넌스 blocker로 공개 전 보류",
            "개인정보 노출 우려: 데이터 거버넌스 대시보드에서 원문 표면 차단",
            "추천 품질 하락: 품질 회귀 모니터와 launch gate에서 공개 확대 보류",
        ],
        next_actions=[
            "Trust Center를 공개 리포트와 메인 구매 화면에 연결하세요.",
            "검수 승인/반려 이력을 신뢰 배지로 노출하세요.",
            "제휴 링크 클릭 전 비제휴 대안 확인 UX를 강화하세요.",
        ],
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
