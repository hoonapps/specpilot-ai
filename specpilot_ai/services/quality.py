from specpilot_ai.core.models import (
    AnalysisQualityAudit,
    AnalyzeResponse,
    CheckStatus,
    TrustGrade,
)


def build_quality_audit(response: AnalyzeResponse) -> AnalysisQualityAudit:
    warning_count = sum(event.status == CheckStatus.warning for event in response.trace_events)
    blocker_count = sum(event.status == CheckStatus.blocker for event in response.trace_events)
    citation_count = len(response.report.citations)
    review_required_sources = sum(
        source.trust_grade == TrustGrade.review_required or source.requires_human_review
        for source in response.report.source_trust
    )
    estimated_source_calls = _estimated_source_calls(response)
    estimated_llm_tokens = _estimated_llm_tokens(response)
    estimated_cost_krw = round(
        estimated_source_calls * 8.0 + (estimated_llm_tokens / 1000) * 3.5,
        2,
    )
    launch_blockers = _launch_blockers(
        response,
        warning_count=warning_count,
        blocker_count=blocker_count,
        review_required_sources=review_required_sources,
    )
    quality_score = _quality_score(
        response,
        warning_count=warning_count,
        blocker_count=blocker_count,
        review_required_sources=review_required_sources,
        launch_blockers=len(launch_blockers),
    )
    return AnalysisQualityAudit(
        trace_id=response.graph_trace_id,
        quality_score=quality_score,
        estimated_source_calls=estimated_source_calls,
        estimated_llm_tokens=estimated_llm_tokens,
        estimated_cost_krw=estimated_cost_krw,
        warning_count=warning_count,
        blocker_count=blocker_count,
        citation_count=citation_count,
        review_required_sources=review_required_sources,
        launch_blockers=launch_blockers,
        operator_notes=_operator_notes(response),
    )


def _estimated_source_calls(response: AnalyzeResponse) -> int:
    product_count = len(response.report.comparison_table)
    source_kinds = max(1, len(response.report.source_trust))
    return product_count * source_kinds


def _estimated_llm_tokens(response: AnalyzeResponse) -> int:
    text_size = len(response.report.summary)
    text_size += sum(len(flag) for flag in response.report.verification_flags)
    text_size += sum(len(event.detail) for event in response.trace_events)
    return max(900, int(text_size * 1.8) + len(response.trace_events) * 120)


def _launch_blockers(
    response: AnalyzeResponse,
    *,
    warning_count: int,
    blocker_count: int,
    review_required_sources: int,
) -> list[str]:
    blockers: list[str] = []
    if not response.report.top_recommendations:
        blockers.append("추천 후보가 없습니다.")
    if len(response.report.top_recommendations) < 3:
        blockers.append("TOP 3 추천이 부족합니다.")
    if len(response.report.excluded_products) < 2:
        blockers.append("제외 후보 2개가 부족합니다.")
    if not response.report.price_alerts:
        blockers.append("가격 알림 계획이 없습니다.")
    if not response.report.source_trust:
        blockers.append("출처 신뢰 평가가 없습니다.")
    if blocker_count > 0:
        blockers.append("차단 상태 trace 이벤트가 있습니다.")
    if warning_count >= 4:
        blockers.append("경고 이벤트가 많아 공개 전 검수가 필요합니다.")
    if review_required_sources >= 3:
        blockers.append("검수 필요 출처가 많아 공개 추천에 부적합합니다.")
    return blockers


def _quality_score(
    response: AnalyzeResponse,
    *,
    warning_count: int,
    blocker_count: int,
    review_required_sources: int,
    launch_blockers: int,
) -> float:
    score = 100.0
    score -= warning_count * 4.0
    score -= blocker_count * 18.0
    score -= review_required_sources * 3.0
    score -= launch_blockers * 10.0
    if len(response.report.citations) < len(response.report.comparison_table):
        score -= 8.0
    if response.report.final_pick_id is None:
        score -= 20.0
    return round(max(0.0, min(100.0, score)), 1)


def _operator_notes(response: AnalyzeResponse) -> list[str]:
    notes = [
        f"trace {response.graph_trace_id}는 {len(response.steps)}개 에이전트 단계를 실행했습니다.",
        (
            f"추천 {len(response.report.top_recommendations)}개, "
            f"제외 {len(response.report.excluded_products)}개, "
            f"비교표 {len(response.report.comparison_table)}개를 생성했습니다."
        ),
    ]
    if response.report.source_trust:
        notes.append(
            f"출처 신뢰 평가 {len(response.report.source_trust)}개와 "
            f"citation {len(response.report.citations)}개를 연결했습니다."
        )
    return notes
