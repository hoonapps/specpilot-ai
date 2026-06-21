from datetime import UTC, datetime

from specpilot_ai.core.models import (
    BenchmarkValidationCheck,
    BenchmarkValidationMessage,
    BenchmarkValidationRequest,
    Category,
    CheckStatus,
    PublicBenchmarkValidationKit,
)


def build_public_benchmark_validation_kit(
    request: BenchmarkValidationRequest,
    generated_at: datetime | None = None,
) -> PublicBenchmarkValidationKit:
    generated_at = generated_at or datetime.now(UTC)
    title = _title(request)
    crashes = _clean(request.crashes, 5)
    checks = _checks(request, crashes)
    status = _status(checks, request, crashes)
    score = _score(checks, request, crashes)
    bottleneck_summary = _bottleneck_summary(checks, request)
    seller_message = _seller_message(request, title, status, checks, crashes)
    return PublicBenchmarkValidationKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        product_title=title,
        performance_status=status,
        performance_score=score,
        bottleneck_summary=bottleneck_summary,
        headline=_headline(title, status),
        summary=_summary(request, status, score, bottleneck_summary),
        checks=checks,
        evidence_checklist=_evidence_checklist(request),
        issue_triage=_issue_triage(request, status, checks, crashes),
        seller_message=seller_message,
        messages=_messages(request, title, status, seller_message),
        analysis_prefill=_analysis_prefill(request, title, status, score, bottleneck_summary),
        share_copy=_share_copy(request, title, status, score, bottleneck_summary),
        next_actions=_next_actions(status, checks, crashes),
    )


def _title(request: BenchmarkValidationRequest) -> str:
    fallback = "노트북 벤치마크" if request.category == Category.laptop else "컴퓨터 벤치마크"
    return request.product_title.strip() or fallback


def _clean(values: list[str], limit: int) -> list[str]:
    return [value.strip() for value in values if value.strip()][:limit]


def _checks(
    request: BenchmarkValidationRequest,
    crashes: list[str],
) -> list[BenchmarkValidationCheck]:
    checks = [
        _ratio_check(
            check_id="cpu_score",
            label="CPU 점수",
            observed_value=request.observed_cpu_score,
            expected_value=request.expected_cpu_score,
            unit="점",
            action="CPU 전원 제한, 쿨러 장착, BIOS 전력 설정, 칩셋 드라이버를 확인하세요.",
            evidence="벤치마크 결과 화면과 CPU 모델/전력 모드 캡처",
        ),
        _ratio_check(
            check_id="gpu_score",
            label="GPU 점수",
            observed_value=request.observed_gpu_score,
            expected_value=request.expected_gpu_score,
            unit="점",
            action="그래픽 드라이버, 전원 케이블, 성능 모드, 모니터 연결 포트를 확인하세요.",
            evidence="벤치마크 결과 화면과 GPU 드라이버 버전 캡처",
        ),
        _ratio_check(
            check_id="ssd_read",
            label="SSD 읽기 속도",
            observed_value=request.observed_ssd_read_mbps,
            expected_value=request.expected_ssd_read_mbps,
            unit="MB/s",
            action="SSD 슬롯, 방열판, PCIe 세대, 저장장치 드라이버와 여유 공간을 확인하세요.",
            evidence="스토리지 벤치마크와 디스크 모델명 캡처",
        ),
        _temperature_check(
            check_id="cpu_temp",
            label="CPU 최고 온도",
            observed_value=request.max_cpu_temp_c,
            warning_limit=92 if request.category == Category.desktop_pc else 96,
            blocker_limit=100 if request.category == Category.desktop_pc else 105,
            action="쿨러 장착, 써멀, 팬 커브, 노트북 성능 모드와 흡기 공간을 확인하세요.",
            evidence="15분 부하 중 온도 그래프 캡처",
        ),
        _temperature_check(
            check_id="gpu_temp",
            label="GPU 최고 온도",
            observed_value=request.max_gpu_temp_c,
            warning_limit=86,
            blocker_limit=94,
            action="케이스 airflow, GPU 팬, 전원 제한, 노트북 dGPU 모드를 확인하세요.",
            evidence="15분 부하 중 GPU 온도/클럭 그래프 캡처",
        ),
        BenchmarkValidationCheck(
            check_id="driver_versions",
            label="드라이버 확인",
            status=CheckStatus.ok if request.driver_versions_checked else CheckStatus.warning,
            observed="확인 완료" if request.driver_versions_checked else "미확인",
            expected="칩셋/GPU/스토리지 드라이버 버전 확인",
            action="제조사 또는 GPU 공식 드라이버 버전을 설치하고 같은 벤치마크를 다시 실행하세요.",
            evidence="장치 관리자, GPU 제어판, 제조사 유틸리티 버전 캡처",
        ),
    ]
    if request.throttling_observed:
        checks.append(
            BenchmarkValidationCheck(
                check_id="throttling",
                label="스로틀링",
                status=CheckStatus.blocker,
                observed="관찰됨",
                expected="지속 부하 중 클럭 급락 없음",
                action="온도, 전력 제한, 충전기/전원 케이블, BIOS/성능 모드를 즉시 확인하세요.",
                evidence="클럭/온도/전력 그래프와 증상 영상",
            )
        )
    if crashes:
        checks.append(
            BenchmarkValidationCheck(
                check_id="crash_stability",
                label="꺼짐/오류",
                status=CheckStatus.blocker,
                observed=", ".join(crashes[:3]),
                expected="벤치마크와 실사용 중 꺼짐, 블루스크린, 앱 종료 없음",
                action="반품 마감 전 판매자와 제조사에 동시에 접수하고 같은 조건 재현 영상을 남기세요.",
                evidence="오류 화면, 이벤트 로그, 재현 영상",
            )
        )
    if request.fan_noise_note.strip():
        checks.append(
            BenchmarkValidationCheck(
                check_id="fan_noise",
                label="팬/소음",
                status=CheckStatus.warning if _noisy(request.fan_noise_note) else CheckStatus.ok,
                observed=request.fan_noise_note.strip(),
                expected="부하 상태에 맞는 정상 팬 소음, 고주파/갈림음 없음",
                action="소음이 반복되면 거리와 부하 조건을 고정해 짧은 영상으로 남기세요.",
                evidence="소음 영상과 실행 중인 앱/온도 화면",
            )
        )
    return checks


def _ratio_check(
    check_id: str,
    label: str,
    observed_value: int | None,
    expected_value: int | None,
    unit: str,
    action: str,
    evidence: str,
) -> BenchmarkValidationCheck:
    if observed_value is None or expected_value is None or expected_value == 0:
        return BenchmarkValidationCheck(
            check_id=check_id,
            label=label,
            status=CheckStatus.warning,
            observed="미입력",
            expected="기대값과 실제값 필요",
            action="주문 사양 기준 기대 범위와 실제 벤치마크 결과를 함께 입력하세요.",
            evidence=evidence,
        )
    ratio = observed_value / expected_value
    status = CheckStatus.ok
    if ratio < 0.76:
        status = CheckStatus.blocker
    elif ratio < 0.9:
        status = CheckStatus.warning
    return BenchmarkValidationCheck(
        check_id=check_id,
        label=label,
        status=status,
        observed=f"{observed_value:,}{unit} ({ratio:.0%})",
        expected=f"{expected_value:,}{unit}",
        action=action if status != CheckStatus.ok else "첫날 정상 기준값으로 저장하세요.",
        evidence=evidence,
    )


def _temperature_check(
    check_id: str,
    label: str,
    observed_value: int | None,
    warning_limit: int,
    blocker_limit: int,
    action: str,
    evidence: str,
) -> BenchmarkValidationCheck:
    if observed_value is None:
        return BenchmarkValidationCheck(
            check_id=check_id,
            label=label,
            status=CheckStatus.warning,
            observed="미입력",
            expected=f"주의 {warning_limit}도 미만, 차단 {blocker_limit}도 미만",
            action="15분 부하 테스트 중 최고 온도를 기록하세요.",
            evidence=evidence,
        )
    status = CheckStatus.ok
    if observed_value >= blocker_limit:
        status = CheckStatus.blocker
    elif observed_value >= warning_limit:
        status = CheckStatus.warning
    return BenchmarkValidationCheck(
        check_id=check_id,
        label=label,
        status=status,
        observed=f"{observed_value}도",
        expected=f"주의 {warning_limit}도 미만, 차단 {blocker_limit}도 미만",
        action=action if status != CheckStatus.ok else "온도 그래프를 첫날 기준값으로 저장하세요.",
        evidence=evidence,
    )


def _noisy(note: str) -> bool:
    lowered = note.lower()
    return any(term in lowered for term in ("고주파", "갈림", "덜덜", "비정상", "coil", "whine", "rattle"))


def _status(
    checks: list[BenchmarkValidationCheck],
    request: BenchmarkValidationRequest,
    crashes: list[str],
) -> CheckStatus:
    if crashes or request.throttling_observed:
        return CheckStatus.blocker
    if any(check.status == CheckStatus.blocker for check in checks):
        return CheckStatus.blocker
    if any(check.status == CheckStatus.warning for check in checks):
        return CheckStatus.warning
    return CheckStatus.ok


def _score(
    checks: list[BenchmarkValidationCheck],
    request: BenchmarkValidationRequest,
    crashes: list[str],
) -> int:
    score = 100
    score -= sum(18 for check in checks if check.status == CheckStatus.blocker)
    score -= sum(7 for check in checks if check.status == CheckStatus.warning)
    if request.throttling_observed:
        score -= 12
    score -= min(len(crashes) * 12, 30)
    if not request.evidence_links:
        score -= 4
    return max(0, min(100, score))


def _bottleneck_summary(
    checks: list[BenchmarkValidationCheck],
    request: BenchmarkValidationRequest,
) -> str:
    failed = [check.label for check in checks if check.status == CheckStatus.blocker]
    warned = [check.label for check in checks if check.status == CheckStatus.warning]
    if failed:
        return f"차단 항목: {', '.join(failed[:3])}"
    if warned:
        return f"주의 항목: {', '.join(warned[:3])}"
    names = ", ".join(part for part in (request.cpu_name, request.gpu_name) if part.strip())
    return f"{names or '주요 부품'} 기준 성능이 기대 범위 안입니다."


def _headline(title: str, status: CheckStatus) -> str:
    if status == CheckStatus.blocker:
        return f"{title} 벤치마크는 반품/AS 증거를 먼저 확보해야 합니다."
    if status == CheckStatus.warning:
        return f"{title} 성능은 사용 가능하지만 재측정과 드라이버 확인이 필요합니다."
    return f"{title} 성능 기준값을 정상 proof로 저장할 수 있습니다."


def _summary(
    request: BenchmarkValidationRequest,
    status: CheckStatus,
    score: int,
    bottleneck_summary: str,
) -> str:
    purpose = request.primary_purpose.strip() or "실사용"
    return (
        f"{purpose} 기준 성능 점수 {score}점, 상태 {status.value}. "
        f"{bottleneck_summary.rstrip('.')}. 첫날 벤치마크 결과를 반품/AS 증거와 다음 추천 기준으로 정리합니다."
    )


def _evidence_checklist(request: BenchmarkValidationRequest) -> list[str]:
    checklist = [
        "벤치마크 결과 화면 원본 캡처",
        "CPU/GPU/RAM/SSD 모델명과 주문 옵션명 캡처",
        "15분 부하 중 온도, 클럭, 전력 그래프",
        "드라이버 버전과 BIOS/펌웨어 버전",
        "반복 오류가 있으면 재현 영상과 이벤트 로그",
    ]
    if request.category == Category.laptop:
        checklist.append("충전기 연결 상태, 성능 모드, 배터리 모드 구분 캡처")
    else:
        checklist.append("파워 케이블, 모니터 연결 포트, 케이스 팬 구성을 함께 촬영")
    if request.evidence_links:
        checklist.insert(0, f"첨부 증거 {len(request.evidence_links)}개 링크 원문")
    return checklist


def _issue_triage(
    request: BenchmarkValidationRequest,
    status: CheckStatus,
    checks: list[BenchmarkValidationCheck],
    crashes: list[str],
) -> list[str]:
    if status == CheckStatus.blocker:
        actions = [
            "반품/교환 마감 전 판매자와 제조사에 동시에 접수하세요.",
            "드라이버 재설치 전후 결과를 나눠서 캡처해 하드웨어 의심 여부를 분리하세요.",
        ]
    elif status == CheckStatus.warning:
        actions = [
            "전원 모드, 드라이버, BIOS/펌웨어를 확인한 뒤 같은 벤치마크를 다시 실행하세요.",
            "주의 항목이 두 번 반복되면 판매자 문의 문구와 증거를 함께 보내세요.",
        ]
    else:
        actions = [
            "정상 기준값을 구매 결과 공유 카드와 보증 기록에 저장하세요.",
            "한 달 뒤 같은 벤치마크를 다시 실행해 성능 저하를 비교하세요.",
        ]
    actions.extend(f"차단/주의: {check.label} - {check.action}" for check in checks if check.status != CheckStatus.ok)
    actions.extend(f"오류 기록: {crash}" for crash in crashes)
    if request.throttling_observed:
        actions.append("스로틀링이 관찰됐으니 온도/클럭 그래프를 판매자 문의에 반드시 첨부하세요.")
    return actions[:8]


def _seller_message(
    request: BenchmarkValidationRequest,
    title: str,
    status: CheckStatus,
    checks: list[BenchmarkValidationCheck],
    crashes: list[str],
) -> str:
    issue_lines = []
    if crashes:
        issue_lines.append(f"- 꺼짐/오류: {', '.join(crashes)}")
    issue_lines.extend(
        f"- {check.label}: {check.observed} / 기대 {check.expected}"
        for check in checks
        if check.status != CheckStatus.ok
    )
    if not issue_lines:
        issue_lines.append("- 현재 벤치마크는 기대 범위 안입니다.")
    return (
        f"{title} 수령 후 벤치마크 검수 결과 상태가 {status.value}입니다.\n"
        + "\n".join(issue_lines[:6])
        + "\n동일 조건 재측정 방법, 교환/AS 접수 기준, 필요한 추가 증거를 안내해주세요."
    )


def _messages(
    request: BenchmarkValidationRequest,
    title: str,
    status: CheckStatus,
    seller_message: str,
) -> list[BenchmarkValidationMessage]:
    return [
        BenchmarkValidationMessage(
            channel="seller",
            label="판매자/제조사 문의",
            copy_text=seller_message,
            cta_label="문의 문구 복사",
        ),
        BenchmarkValidationMessage(
            channel="self",
            label="내 기준값",
            copy_text=(
                f"{title} 벤치마크 기준값\n"
                f"- 상태: {status.value}\n"
                f"- CPU: {request.observed_cpu_score or '미입력'} / 기대 {request.expected_cpu_score or '미입력'}\n"
                f"- GPU: {request.observed_gpu_score or '미입력'} / 기대 {request.expected_gpu_score or '미입력'}"
            ),
            cta_label="기준값 저장",
        ),
        BenchmarkValidationMessage(
            channel="community",
            label="커뮤니티 질문",
            copy_text=(
                f"{title} 벤치마크 결과가 {status.value}입니다. "
                "주문 사양, 드라이버 버전, 온도 그래프를 기준으로 정상 범위인지 검토 부탁드립니다."
            ),
            cta_label="질문 복사",
        ),
    ]


def _analysis_prefill(
    request: BenchmarkValidationRequest,
    title: str,
    status: CheckStatus,
    score: int,
    bottleneck_summary: str,
) -> str:
    return (
        f"{_category_label(request.category)} '{title}' 벤치마크 결과를 검수해줘. "
        f"목적 {request.primary_purpose or '실사용'}, CPU {request.cpu_name or '미입력'} "
        f"{request.observed_cpu_score or '미입력'}/{request.expected_cpu_score or '미입력'}, "
        f"GPU {request.gpu_name or '미입력'} {request.observed_gpu_score or '미입력'}/"
        f"{request.expected_gpu_score or '미입력'}, 온도 CPU {request.max_cpu_temp_c or '미입력'}도, "
        f"GPU {request.max_gpu_temp_c or '미입력'}도, 상태 {status.value}, 점수 {score}. "
        f"{bottleneck_summary}"
    )


def _share_copy(
    request: BenchmarkValidationRequest,
    title: str,
    status: CheckStatus,
    score: int,
    bottleneck_summary: str,
) -> str:
    return (
        "SpecPilot AI 성능 벤치마크 검수\n"
        f"제품: {title}\n"
        f"상태: {status.value}\n"
        f"성능 점수: {score}점\n"
        f"{bottleneck_summary}"
    )


def _next_actions(
    status: CheckStatus,
    checks: list[BenchmarkValidationCheck],
    crashes: list[str],
) -> list[str]:
    if status == CheckStatus.blocker:
        return [
            "반품/교환 마감 전 벤치마크, 온도 그래프, 오류 영상을 한 폴더에 모으세요.",
            "판매자 문의 문구를 보내고 접수 번호를 구매 후 케어 기록에 저장하세요.",
            "같은 사양 후보를 다시 추천받을 때 차단 항목을 제외 조건으로 넣으세요.",
        ]
    if status == CheckStatus.warning:
        return [
            "드라이버/BIOS/성능 모드를 정리한 뒤 같은 테스트를 한 번 더 실행하세요.",
            "주의 항목이 반복되면 판매자 문의 문구와 캡처 증거를 보내세요.",
            "정상으로 회복되면 첫날 기준값을 구매 결과 공유 카드에 첨부하세요.",
        ]
    return [
        "정상 벤치마크 기준값을 보증 기록과 구매 결과 공유 카드에 저장하세요.",
        "주요 벤치마크 캡처에서 개인정보와 주문번호 원문을 제거한 뒤 공유하세요.",
        "성능 저하가 의심될 때 오늘 기준값과 같은 조건으로 재측정하세요.",
    ]


def _category_label(category: Category) -> str:
    return "노트북" if category == Category.laptop else "컴퓨터"
