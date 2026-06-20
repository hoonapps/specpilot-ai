from datetime import UTC, datetime

from specpilot_ai.core.models import (
    Category,
    CheckStatus,
    FirstBootMessage,
    FirstBootSetupRequest,
    FirstBootSetupTask,
    PublicFirstBootSetupKit,
)


def build_public_first_boot_setup_kit(
    request: FirstBootSetupRequest,
    generated_at: datetime | None = None,
) -> PublicFirstBootSetupKit:
    generated_at = generated_at or datetime.now(UTC)
    issues = _clean(request.observed_issues)
    missing_drivers = _clean(request.missing_drivers)
    score = _setup_score(request, issues, missing_drivers)
    priority = _priority(score, issues, missing_drivers)
    boot_tasks = _first_boot_tasks(request, issues)
    driver_tasks = _driver_tasks(request, missing_drivers)
    return PublicFirstBootSetupKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        product_title=_title(request),
        priority=priority,
        setup_score=score,
        headline=_headline(request, priority),
        summary=_summary(request, priority, score, issues, missing_drivers),
        first_boot_checklist=boot_tasks,
        driver_checklist=driver_tasks,
        benchmark_plan=_benchmark_plan(request),
        issue_triage=_issue_triage(issues),
        warranty_actions=_warranty_actions(request),
        messages=_messages(request, priority),
        analysis_prefill=_analysis_prefill(request, priority, score, issues, missing_drivers),
        share_copy=_share_copy(request, priority, score),
        next_actions=_next_actions(priority, issues, missing_drivers),
    )


def _title(request: FirstBootSetupRequest) -> str:
    return request.product_title.strip() or ("새 노트북" if request.category == Category.laptop else "새 컴퓨터")


def _clean(values: list[str]) -> list[str]:
    return [value.strip() for value in values if value.strip()][:8]


def _setup_score(
    request: FirstBootSetupRequest,
    issues: list[str],
    missing_drivers: list[str],
) -> int:
    score = 100
    score -= min(len(issues) * 18, 54)
    score -= min(len(missing_drivers) * 10, 30)
    if not request.warranty_registered:
        score -= 8
    if not request.bios_updated and request.category == Category.desktop_pc:
        score -= 6
    if request.category == Category.laptop and not request.connection_type:
        score -= 4
    return max(0, min(100, score))


def _priority(score: int, issues: list[str], missing_drivers: list[str]) -> CheckStatus:
    if any(_severe_issue(issue) for issue in issues):
        return CheckStatus.blocker
    if score < 60:
        return CheckStatus.blocker
    if issues or missing_drivers or score < 82:
        return CheckStatus.warning
    return CheckStatus.ok


def _severe_issue(issue: str) -> bool:
    lowered = issue.lower()
    severe_terms = (
        "부팅",
        "전원",
        "화면 안",
        "블루스크린",
        "꺼짐",
        "고주파",
        "불량",
        "파손",
        "인식 안",
        "dead",
        "crash",
        "bsod",
        "broken",
    )
    return any(term in lowered for term in severe_terms)


def _first_boot_tasks(
    request: FirstBootSetupRequest,
    issues: list[str],
) -> list[FirstBootSetupTask]:
    tasks = [
        FirstBootSetupTask(
            task_id="power_display",
            label="전원/화면/포트",
            status=CheckStatus.blocker if any(_severe_issue(issue) for issue in issues) else CheckStatus.ok,
            instruction="전원 버튼, 화면 출력, 충전/전원 케이블, USB/HDMI/DP 포트 인식을 순서대로 확인하세요.",
            evidence="전원 LED, 화면 출력, 포트별 장치 인식 사진 또는 짧은 영상",
        ),
        FirstBootSetupTask(
            task_id="os_activation",
            label="OS 활성화",
            status=CheckStatus.warning if "FreeDOS" in request.os_name or "미설치" in request.os_name else CheckStatus.ok,
            instruction=f"{request.os_name or 'OS'} 설치/활성화 상태와 계정 로그인, 업데이트 대기 항목을 확인하세요.",
            evidence="설정 > 시스템 > 정품 인증 또는 OS 설치 완료 화면",
        ),
        FirstBootSetupTask(
            task_id="display_profile",
            label="디스플레이 설정",
            status=CheckStatus.warning if not request.monitor_resolution else CheckStatus.ok,
            instruction="해상도, 주사율, HDR/색 프로필, 노트북 외부 모니터 연결 방식을 실제 사용 환경으로 맞추세요.",
            evidence=f"디스플레이 설정 캡처: {request.monitor_resolution or '해상도 미입력'}",
        ),
    ]
    if request.category == Category.laptop:
        tasks.append(
            FirstBootSetupTask(
                task_id="battery_thermal",
                label="배터리/발열",
                status=CheckStatus.warning if any("발열" in issue or "팬" in issue for issue in issues) else CheckStatus.ok,
                instruction="배터리 충전, 절전 모드, 팬 소음, 키보드/터치패드, 웹캠/마이크를 확인하세요.",
                evidence="배터리 상태와 팬 소음/온도 확인 캡처",
            )
        )
    else:
        tasks.append(
            FirstBootSetupTask(
                task_id="bios_memory_storage",
                label="BIOS/RAM/SSD",
                status=CheckStatus.ok if request.bios_updated else CheckStatus.warning,
                instruction="BIOS 버전, RAM 용량/클럭, SSD 용량, XMP/EXPO 적용 여부를 확인하세요.",
                evidence="BIOS 또는 시스템 정보 화면",
            )
        )
    return tasks


def _driver_tasks(
    request: FirstBootSetupRequest,
    missing_drivers: list[str],
) -> list[FirstBootSetupTask]:
    base = [
        ("chipset", "칩셋/메인보드", "제조사 페이지에서 칩셋, 네트워크, 오디오 드라이버를 설치하세요."),
        ("graphics", "그래픽", "GPU 드라이버를 설치하고 해상도/주사율이 정상 노출되는지 확인하세요."),
        ("network", "네트워크", "유선/무선 네트워크 속도와 블루투스 주변기기 연결을 확인하세요."),
    ]
    if request.category == Category.laptop:
        base.append(("vendor_utility", "제조사 유틸리티", "배터리 보호, 성능 모드, 펌웨어 업데이트 유틸리티를 확인하세요."))
    labels = {item.lower() for item in missing_drivers}
    return [
        FirstBootSetupTask(
            task_id=task_id,
            label=label,
            status=CheckStatus.warning if any(token in label.lower() or token in task_id for token in labels) else CheckStatus.ok,
            instruction=instruction,
            evidence=f"{label} 드라이버 버전 또는 장치 관리자 정상 인식 화면",
        )
        for task_id, label, instruction in base
    ]


def _benchmark_plan(request: FirstBootSetupRequest) -> list[str]:
    purpose = request.primary_purpose.strip() or "실사용"
    plan = [
        f"{purpose} 기준으로 부팅 시간과 앱 첫 실행 시간을 기록하세요.",
        "CPU/GPU/RAM/SSD가 주문 사양과 같은지 시스템 정보와 벤치마크 도구로 확인하세요.",
        "15분 이상 실제 작업을 실행해 소음, 발열, 꺼짐, 화면 깜빡임을 확인하세요.",
    ]
    if request.category == Category.laptop:
        plan.append("충전기 연결/배터리 사용 양쪽에서 성능 모드와 발열 차이를 기록하세요.")
    else:
        plan.append("모니터 해상도/주사율과 GPU 로드 상태를 함께 캡처하세요.")
    return plan


def _issue_triage(issues: list[str]) -> list[str]:
    if not issues:
        return [
            "초기 불량이 없어도 첫날 기준값을 캡처해 나중의 성능 저하와 비교하세요.",
            "드라이버 설치 전후로 문제가 달라지는지 한 번 더 확인하세요.",
        ]
    actions = [f"관찰 이슈: {issue}" for issue in issues]
    if any(_severe_issue(issue) for issue in issues):
        actions.insert(0, "전원/부팅/화면/인식 문제는 반품 마감 전 판매자와 제조사에 동시에 접수하세요.")
    else:
        actions.insert(0, "증상이 반복되는 조건과 시간을 기록하고 영상으로 남기세요.")
    return actions[:8]


def _warranty_actions(request: FirstBootSetupRequest) -> list[str]:
    actions = [
        "영수증, 주문번호 마스킹값, 시리얼 번호, 박스 라벨을 같은 폴더에 저장하세요.",
        "제조사 보증 등록 화면과 AS 정책을 캡처하세요.",
    ]
    if request.warranty_registered:
        actions.append("보증 등록 완료 화면을 구매 결과 기록에 첨부하세요.")
    else:
        actions.insert(0, "보증 등록이 아직이면 오늘 제조사 계정에 제품을 등록하세요.")
    return actions


def _messages(request: FirstBootSetupRequest, priority: CheckStatus) -> list[FirstBootMessage]:
    return [
        FirstBootMessage(
            channel="self",
            label="내 세팅 기록",
            copy_text=(
                f"{_title(request)} 첫 부팅 점검\n"
                f"- 우선순위: {priority.value}\n"
                f"- OS: {request.os_name or '미입력'}\n"
                f"- 목적: {request.primary_purpose or '미입력'}"
            ),
            cta_label="내 기록에 저장",
        ),
        FirstBootMessage(
            channel="seller",
            label="판매자/제조사 문의",
            copy_text=(
                f"{_title(request)} 초기 세팅 중 확인이 필요합니다. "
                "전원/화면/드라이버/보증 등록 기준으로 조치 방법과 접수 절차를 안내해주세요."
            ),
            cta_label="문의 보내기",
        ),
        FirstBootMessage(
            channel="team",
            label="공유 점검표",
            copy_text=f"[첫 부팅 점검] {_title(request)} · 상태 {priority.value} · OS {request.os_name or '미입력'}",
            cta_label="팀/가족 공유",
        ),
    ]


def _headline(request: FirstBootSetupRequest, priority: CheckStatus) -> str:
    if priority == CheckStatus.blocker:
        return f"{_title(request)} 첫 부팅에서 교환/AS 검토가 필요합니다."
    if priority == CheckStatus.warning:
        return f"{_title(request)} 세팅은 가능하지만 드라이버와 증거를 더 닫아야 합니다."
    return f"{_title(request)} 첫 부팅 세팅 기준값을 저장할 수 있습니다."


def _summary(
    request: FirstBootSetupRequest,
    priority: CheckStatus,
    score: int,
    issues: list[str],
    missing_drivers: list[str],
) -> str:
    return (
        f"세팅 점수 {score}점, 상태 {priority.value}. "
        f"이슈 {len(issues)}개, 미확인 드라이버 {len(missing_drivers)}개를 기준으로 "
        f"{request.primary_purpose or '실사용'} 환경의 첫날 기준값을 정리합니다."
    )


def _analysis_prefill(
    request: FirstBootSetupRequest,
    priority: CheckStatus,
    score: int,
    issues: list[str],
    missing_drivers: list[str],
) -> str:
    return (
        f"{_category_label(request.category)} '{_title(request)}' 첫 부팅 세팅을 점검해줘. "
        f"OS {request.os_name or '미입력'}, 목적 {request.primary_purpose or '미입력'}, "
        f"세팅 점수 {score}, 상태 {priority.value}, "
        f"미확인 드라이버 {', '.join(missing_drivers) if missing_drivers else '없음'}, "
        f"관찰 이슈 {', '.join(issues) if issues else '없음'}."
    )


def _category_label(category: Category) -> str:
    return "노트북" if category == Category.laptop else "컴퓨터"


def _share_copy(request: FirstBootSetupRequest, priority: CheckStatus, score: int) -> str:
    return (
        "SpecPilot AI 첫 부팅 세팅 검수\n"
        f"제품: {_title(request)}\n"
        f"상태: {priority.value}\n"
        f"세팅 점수: {score}점\n"
        f"OS: {request.os_name or '미입력'}"
    )


def _next_actions(
    priority: CheckStatus,
    issues: list[str],
    missing_drivers: list[str],
) -> list[str]:
    if priority == CheckStatus.blocker:
        return [
            "전원/화면/부팅/인식 문제 증거를 영상으로 남기고 반품 또는 AS 접수를 먼저 진행하세요.",
            "드라이버 설치로 해결되는 문제와 하드웨어 의심 문제를 분리해 기록하세요.",
            "구매 후 케어 키트의 반품 마감 전에 판매자 답변을 받아두세요.",
        ]
    if issues or missing_drivers:
        return [
            "미확인 드라이버를 설치한 뒤 같은 점검표를 한 번 더 실행하세요.",
            "반복되는 증상은 시간, 앱, 연결 장치를 함께 기록하세요.",
            "세팅 완료 후 벤치마크 기준값을 구매 결과에 저장하세요.",
        ]
    return [
        "첫날 기준 성능 캡처를 저장하세요.",
        "보증 등록과 시리얼 번호 저장을 완료하세요.",
        "사용 목적별 필수 앱과 주변기기 연결 상태를 마지막으로 확인하세요.",
    ]
