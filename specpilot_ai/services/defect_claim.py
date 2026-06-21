from datetime import UTC, date, datetime, timedelta

from specpilot_ai.core.models import (
    Category,
    CheckStatus,
    DefectClaimMessage,
    DefectClaimRequest,
    DefectClaimTimelineItem,
    PublicDefectClaimKit,
)


def build_public_defect_claim_kit(
    request: DefectClaimRequest,
    generated_at: datetime | None = None,
) -> PublicDefectClaimKit:
    generated_at = generated_at or datetime.now(UTC)
    today = generated_at.date()
    title = request.product_title.strip() or _fallback_title(request.category)
    seller = request.seller_name.strip() or "판매자"
    maker = request.manufacturer_name.strip() or "제조사"
    issues = _clean(request.observed_issues, 6)
    failed_checks = _clean(request.failed_checks, 6)
    evidence = _clean(request.evidence_items, 8)
    responses = _clean(request.seller_responses, 4)
    purchase_date = _parse_date(request.purchase_date)
    delivered_date = _parse_date(request.delivered_date) or purchase_date or today
    return_deadline = _parse_date(request.return_deadline) or delivered_date + timedelta(days=7)
    warranty_deadline = _parse_date(request.warranty_deadline) or delivered_date + timedelta(days=365)
    evidence_gaps = _evidence_gaps(request, issues, failed_checks, evidence, responses)
    status = _status(request, today, return_deadline, issues, failed_checks, evidence_gaps)
    score = _score(request, today, return_deadline, issues, evidence, responses, evidence_gaps)
    seller_message = _seller_message(request, title, seller, issues, failed_checks, evidence)
    manufacturer_message = _manufacturer_message(request, title, maker, issues, failed_checks, evidence)
    return PublicDefectClaimKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        product_title=title,
        seller_name=seller,
        manufacturer_name=maker,
        claim_status=status,
        claim_score=score,
        urgency_label=_urgency_label(status, today, return_deadline),
        headline=_headline(title, status),
        summary=_summary(request, status, score, return_deadline, warranty_deadline),
        timeline=_timeline(today, return_deadline, warranty_deadline, responses),
        evidence_checklist=_evidence_checklist(request),
        evidence_gaps=evidence_gaps,
        claim_steps=_claim_steps(status, evidence_gaps),
        seller_message=seller_message,
        manufacturer_message=manufacturer_message,
        messages=_messages(seller_message, manufacturer_message, title, status, evidence_gaps),
        analysis_prefill=_analysis_prefill(request, title, status, score, issues, failed_checks),
        share_copy=_share_copy(title, status, score, return_deadline, evidence_gaps),
        next_actions=_next_actions(status, evidence_gaps),
    )


def _fallback_title(category: Category) -> str:
    return "노트북 초기 불량" if category == Category.laptop else "컴퓨터 초기 불량"


def _parse_date(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _clean(values: list[str], limit: int) -> list[str]:
    return [value.strip() for value in values if value.strip()][:limit]


def _severe(issues: list[str], failed_checks: list[str]) -> bool:
    text = " ".join([*issues, *failed_checks]).lower()
    terms = (
        "꺼짐",
        "부팅",
        "화면 안",
        "불량",
        "파손",
        "오배송",
        "사양 상이",
        "고주파",
        "과열",
        "스로틀링",
        "dead",
        "broken",
        "defect",
        "crash",
        "bsod",
    )
    return any(term in text for term in terms)


def _status(
    request: DefectClaimRequest,
    today: date,
    return_deadline: date,
    issues: list[str],
    failed_checks: list[str],
    evidence_gaps: list[str],
) -> CheckStatus:
    days_left = (return_deadline - today).days
    if (
        request.benchmark_status == CheckStatus.blocker
        or _severe(issues, failed_checks)
        or (days_left < 0 and issues)
    ):
        return CheckStatus.blocker
    if issues or failed_checks or evidence_gaps or days_left <= 3:
        return CheckStatus.warning
    return CheckStatus.ok


def _score(
    request: DefectClaimRequest,
    today: date,
    return_deadline: date,
    issues: list[str],
    evidence: list[str],
    responses: list[str],
    evidence_gaps: list[str],
) -> int:
    score = 62
    score += min(len(evidence) * 6, 24)
    score += min(len(responses) * 4, 12)
    if request.order_reference_masked.strip():
        score += 6
    if request.final_paid_price_krw is not None:
        score += 4
    if request.policy_text.strip():
        score += 5
    if return_deadline >= today:
        score += 6
    score -= min(len(evidence_gaps) * 8, 36)
    if _severe(issues, request.failed_checks):
        score -= 7
    if return_deadline < today:
        score -= 12
    if request.benchmark_status == CheckStatus.blocker:
        score -= 8
    return max(0, min(100, score))


def _evidence_checklist(request: DefectClaimRequest) -> list[str]:
    checklist = [
        "최종 결제 영수증과 주문번호 마스킹 캡처",
        "상품명, 옵션명, 제품 시리얼/박스 라벨 사진",
        "문제 재현 영상 또는 사진 원본",
        "벤치마크 결과, 온도/클럭 그래프, 오류 로그",
        "판매자와 제조사 답변, 접수 번호, 통화 메모",
        "반품/교환/AS 정책 화면과 마감일 캡처",
    ]
    if request.category == Category.laptop:
        checklist.append("충전기 연결, 성능 모드, 배터리 모드가 보이는 캡처")
    else:
        checklist.append("전원 케이블, 내부 장착 상태, 모니터 연결 포트 사진")
    return checklist


def _evidence_gaps(
    request: DefectClaimRequest,
    issues: list[str],
    failed_checks: list[str],
    evidence: list[str],
    responses: list[str],
) -> list[str]:
    text = " ".join(evidence).lower()
    gaps: list[str] = []
    if not any(term in text for term in ("영수", "결제", "order", "주문")):
        gaps.append("최종 결제 영수증 또는 주문번호 마스킹 캡처가 필요합니다.")
    if not any(term in text for term in ("영상", "사진", "캡처", "photo", "video")):
        gaps.append("문제 재현 영상 또는 사진 증거가 필요합니다.")
    if not any(term in text for term in ("시리얼", "serial", "박스", "라벨")):
        gaps.append("제품 시리얼/박스 라벨 사진이 필요합니다.")
    if (failed_checks or request.benchmark_status != CheckStatus.ok) and not any(
        term in text for term in ("벤치", "온도", "클럭", "로그", "benchmark")
    ):
        gaps.append("벤치마크, 온도 그래프, 오류 로그 증거가 필요합니다.")
    if not responses:
        gaps.append("판매자 또는 제조사 1차 문의 답변을 저장해야 합니다.")
    if request.policy_text.strip() == "":
        gaps.append("반품/교환/AS 정책 화면 캡처가 필요합니다.")
    if not issues and not failed_checks:
        gaps.append("관찰 증상과 실패한 점검 항목을 구체적으로 적어야 합니다.")
    return gaps[:6]


def _timeline(
    today: date,
    return_deadline: date,
    warranty_deadline: date,
    responses: list[str],
) -> list[DefectClaimTimelineItem]:
    return [
        DefectClaimTimelineItem(
            item_id="evidence_freeze",
            label="증거 원본 고정",
            status=CheckStatus.blocker if return_deadline <= today else CheckStatus.warning,
            due_date=today.isoformat(),
            action="영상, 캡처, 로그 원본을 수정하지 않고 한 폴더에 모으세요.",
        ),
        DefectClaimTimelineItem(
            item_id="return_deadline",
            label="반품/교환 마감",
            status=_deadline_status(today, return_deadline),
            due_date=return_deadline.isoformat(),
            action="마감 전 판매자 접수 번호를 확보하고 추가 증거 요청을 기록하세요.",
        ),
        DefectClaimTimelineItem(
            item_id="seller_response",
            label="판매자/제조사 답변",
            status=CheckStatus.ok if responses else CheckStatus.warning,
            due_date=(today + timedelta(days=1)).isoformat(),
            action="답변, 접수 번호, 담당자 안내를 그대로 저장하세요.",
        ),
        DefectClaimTimelineItem(
            item_id="warranty_deadline",
            label="보증 만료",
            status=_deadline_status(today, warranty_deadline, warning_days=30),
            due_date=warranty_deadline.isoformat(),
            action="제조사 AS 접수 가능 기간과 필요한 서류를 확인하세요.",
        ),
    ]


def _deadline_status(today: date, deadline: date, warning_days: int = 3) -> CheckStatus:
    days_left = (deadline - today).days
    if days_left < 0:
        return CheckStatus.blocker
    if days_left <= warning_days:
        return CheckStatus.warning
    return CheckStatus.ok


def _resolution_label(value: str) -> str:
    labels = {
        "exchange": "교환",
        "refund": "환불",
        "repair": "수리",
        "guidance": "접수 기준 안내",
    }
    return labels.get(value.strip().lower(), value.strip() or "교환")


def _seller_message(
    request: DefectClaimRequest,
    title: str,
    seller: str,
    issues: list[str],
    failed_checks: list[str],
    evidence: list[str],
) -> str:
    return (
        f"{seller} 담당자님, {title} 수령 후 아래 증상이 반복되어 {_resolution_label(request.preferred_resolution)} 기준을 문의드립니다.\n"
        f"- 주문번호: {request.order_reference_masked or '마스킹 후 첨부 예정'}\n"
        f"- 구매/수령일: {request.purchase_date or '미입력'} / {request.delivered_date or '미입력'}\n"
        f"- 증상: {', '.join(issues) if issues else request.issue_summary or '상세 증상 첨부 예정'}\n"
        f"- 실패 점검: {', '.join(failed_checks) if failed_checks else '추가 점검 예정'}\n"
        f"- 첨부 증거: {', '.join(evidence) if evidence else '증거 정리 중'}\n"
        f"- 정책 메모: {request.policy_text.strip()[:160] or '정책 화면 캡처 예정'}\n"
        "접수 절차, 필요한 추가 증거, 교환/환불/수리 판단 기준을 안내 부탁드립니다."
    )


def _manufacturer_message(
    request: DefectClaimRequest,
    title: str,
    maker: str,
    issues: list[str],
    failed_checks: list[str],
    evidence: list[str],
) -> str:
    return (
        f"{maker} AS 담당자님, {title} 초기 점검 중 하드웨어 이상 가능성이 있어 AS 접수 가능 여부를 확인합니다.\n"
        f"- 주문/수령 정보: {request.order_reference_masked or '마스킹 후 첨부 예정'}, {request.delivered_date or '수령일 미입력'}\n"
        f"- 관찰 증상: {', '.join(issues) if issues else request.issue_summary or '상세 증상 첨부 예정'}\n"
        f"- 벤치마크/점검: {', '.join(failed_checks) if failed_checks else '추가 점검 예정'}\n"
        f"- 보유 증거: {', '.join(evidence) if evidence else '증거 정리 중'}\n"
        "동일 조건 재현 방법, 접수 전 필요한 로그, 판매자 교환과 제조사 AS 중 우선 절차를 안내해주세요."
    )


def _messages(
    seller_message: str,
    manufacturer_message: str,
    title: str,
    status: CheckStatus,
    evidence_gaps: list[str],
) -> list[DefectClaimMessage]:
    return [
        DefectClaimMessage(
            channel="seller",
            label="판매자 접수",
            copy_text=seller_message,
            cta_label="판매자 문구 복사",
        ),
        DefectClaimMessage(
            channel="manufacturer",
            label="제조사 AS",
            copy_text=manufacturer_message,
            cta_label="AS 문구 복사",
        ),
        DefectClaimMessage(
            channel="self",
            label="내 증거 패킷",
            copy_text=(
                f"{title} 반품/AS 증거 패킷\n"
                f"- 상태: {status.value}\n"
                f"- 보강 필요: {', '.join(evidence_gaps[:3]) if evidence_gaps else '없음'}"
            ),
            cta_label="패킷 요약 복사",
        ),
    ]


def _urgency_label(status: CheckStatus, today: date, return_deadline: date) -> str:
    days_left = (return_deadline - today).days
    if status == CheckStatus.blocker or days_left <= 0:
        return "오늘 접수"
    if days_left <= 3:
        return "마감 임박"
    if status == CheckStatus.warning:
        return "증거 보강"
    return "기록 보관"


def _headline(title: str, status: CheckStatus) -> str:
    if status == CheckStatus.blocker:
        return f"{title}은 오늘 증거를 고정하고 판매자/제조사 접수를 열어야 합니다."
    if status == CheckStatus.warning:
        return f"{title}은 접수 전에 빠진 증거를 보강해야 합니다."
    return f"{title}은 반품·AS 기록을 보관할 수 있는 상태입니다."


def _summary(
    request: DefectClaimRequest,
    status: CheckStatus,
    score: int,
    return_deadline: date,
    warranty_deadline: date,
) -> str:
    return (
        f"증거 준비 점수 {score}점, 상태 {status.value}. "
        f"반품/교환 마감 {return_deadline.isoformat()}, 보증 마감 {warranty_deadline.isoformat()} 기준으로 "
        f"{_resolution_label(request.preferred_resolution)} 접수 문구와 보강 증거를 정리했습니다."
    )


def _claim_steps(status: CheckStatus, evidence_gaps: list[str]) -> list[str]:
    if status == CheckStatus.blocker:
        steps = [
            "증거 원본을 수정하지 않고 한 폴더에 고정합니다.",
            "판매자와 제조사에 같은 증상, 같은 증거로 동시에 접수합니다.",
            "접수 번호, 답변 시간, 추가 요청 증거를 구매 후 케어 기록에 저장합니다.",
        ]
    elif status == CheckStatus.warning:
        steps = [
            "빠진 증거를 먼저 채운 뒤 같은 문구로 접수합니다.",
            "증상이 반복되는 조건을 1분 이내 영상으로 남깁니다.",
            "정상 사용 가능 여부가 애매하면 벤치마크를 같은 조건으로 재측정합니다.",
        ]
    else:
        steps = [
            "현재 증거 패킷을 보증 기록에 저장합니다.",
            "한 달 뒤 같은 조건으로 성능과 소음을 비교합니다.",
            "새 증상이 생기면 오늘 패킷을 기준값으로 사용합니다.",
        ]
    steps.extend(f"보강: {gap}" for gap in evidence_gaps[:3])
    return steps[:6]


def _analysis_prefill(
    request: DefectClaimRequest,
    title: str,
    status: CheckStatus,
    score: int,
    issues: list[str],
    failed_checks: list[str],
) -> str:
    return (
        f"{'노트북' if request.category == Category.laptop else '컴퓨터'} '{title}' 반품/AS 접수 증거를 검수해줘. "
        f"상태 {status.value}, 증거 점수 {score}점, 희망 해결 {_resolution_label(request.preferred_resolution)}. "
        f"증상 {', '.join(issues) if issues else request.issue_summary or '미입력'}, "
        f"실패 점검 {', '.join(failed_checks) if failed_checks else '미입력'}."
    )


def _share_copy(
    title: str,
    status: CheckStatus,
    score: int,
    return_deadline: date,
    evidence_gaps: list[str],
) -> str:
    return (
        "SpecPilot AI 반품·AS 증거 패킷\n"
        f"제품: {title}\n"
        f"상태: {status.value}\n"
        f"증거 점수: {score}점\n"
        f"반품/교환 마감: {return_deadline.isoformat()}\n"
        f"보강 필요: {', '.join(evidence_gaps[:3]) if evidence_gaps else '없음'}"
    )


def _next_actions(status: CheckStatus, evidence_gaps: list[str]) -> list[str]:
    if status == CheckStatus.blocker:
        return [
            "오늘 안에 재현 영상, 온도/오류 로그, 주문 증거를 한 폴더에 모으세요.",
            "판매자 접수와 제조사 AS 문의를 동시에 열고 접수 번호를 저장하세요.",
            "추가 실험 전 원본 증거를 먼저 백업하세요.",
        ]
    if status == CheckStatus.warning:
        return [
            "보강 필요 증거를 채운 뒤 접수 문구를 보내세요.",
            "반품/교환 마감 전까지 답변이 없으면 접수 기록을 다시 남기세요.",
            "증상이 사라지면 정상 기준값과 오늘 증거를 함께 보관하세요.",
        ]
    return [
        "증거 패킷을 구매 후 케어 기록에 저장하세요.",
        "보증 만료 전 정기 점검 날짜를 캘린더에 남기세요.",
        "공유할 때 주문번호와 시리얼 원문은 반드시 가리세요.",
    ]
