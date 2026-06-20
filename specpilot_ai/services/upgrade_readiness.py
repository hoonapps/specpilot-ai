from datetime import UTC, datetime

from specpilot_ai.core.models import (
    Category,
    CheckStatus,
    PublicUpgradeReadinessKit,
    UpgradePathOption,
    UpgradeReadinessItem,
    UpgradeReadinessRequest,
)


def build_public_upgrade_readiness_kit(
    request: UpgradeReadinessRequest,
    generated_at: datetime | None = None,
) -> PublicUpgradeReadinessKit:
    generated_at = generated_at or datetime.now(UTC)
    items = _readiness_items(request)
    score = _score(request, items)
    priority = _priority(score, items)
    horizon_months = _horizon_months(request, score)
    paths = _upgrade_paths(request, items)
    return PublicUpgradeReadinessKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        product_title=_title(request),
        priority=priority,
        readiness_score=score,
        horizon_months=horizon_months,
        headline=_headline(request, priority, horizon_months),
        summary=_summary(request, priority, score, horizon_months),
        readiness_items=items,
        upgrade_paths=paths,
        lifecycle_risks=_lifecycle_risks(request, items),
        seller_questions=_seller_questions(request, items),
        analysis_prefill=_analysis_prefill(request, priority, score, horizon_months),
        share_copy=_share_copy(request, priority, score, horizon_months),
        next_actions=_next_actions(priority, items),
    )


def _title(request: UpgradeReadinessRequest) -> str:
    return request.product_title.strip() or ("노트북 구매 후보" if request.category == Category.laptop else "컴퓨터 구매 후보")


def _readiness_items(request: UpgradeReadinessRequest) -> list[UpgradeReadinessItem]:
    items = [
        _memory_item(request),
        _storage_item(request),
        _platform_item(request),
    ]
    if request.category == Category.desktop_pc:
        items.extend([_power_item(request), _case_item(request)])
    else:
        items.extend([_laptop_memory_item(request), _laptop_storage_item(request)])
    return items


def _memory_item(request: UpgradeReadinessRequest) -> UpgradeReadinessItem:
    free_slots = max(0, request.ram_slots_total - request.ram_slots_used)
    if request.ram_gb < 16:
        status = CheckStatus.blocker
        finding = f"RAM {request.ram_gb}GB는 장기 사용 기준 부족합니다."
        recommendation = "구매 전 16GB 이상, 크리에이터/게임은 32GB 이상으로 올리세요."
    elif request.ram_gb < 32 and free_slots == 0:
        status = CheckStatus.warning
        finding = f"RAM {request.ram_gb}GB이고 빈 슬롯이 없어 업그레이드 비용이 커질 수 있습니다."
        recommendation = "32GB 구성 또는 빈 슬롯이 있는 옵션을 확인하세요."
    elif free_slots > 0:
        status = CheckStatus.ok
        finding = f"RAM {request.ram_gb}GB, 빈 슬롯 {free_slots}개로 확장 여지가 있습니다."
        recommendation = "같은 규격의 듀얼 채널 확장 가능 여부만 판매자에게 확인하세요."
    else:
        status = CheckStatus.warning
        finding = f"RAM {request.ram_gb}GB지만 슬롯이 모두 사용 중입니다."
        recommendation = "장기 사용 목적이면 초기 구매 시 필요한 용량까지 올리는 편이 안전합니다."
    return UpgradeReadinessItem(
        item_id="memory",
        label="RAM 확장",
        status=status,
        finding=finding,
        recommendation=recommendation,
    )


def _storage_item(request: UpgradeReadinessRequest) -> UpgradeReadinessItem:
    free_slots = max(0, request.storage_slots_total - request.storage_slots_used)
    if request.storage_slots_total == 0:
        status = CheckStatus.blocker
        finding = "저장장치 슬롯 정보가 없어 확장 가능성을 확인할 수 없습니다."
        recommendation = "M.2/SATA 슬롯 수와 사용 중인 슬롯을 판매자에게 확인하세요."
    elif free_slots == 0:
        status = CheckStatus.warning
        finding = "빈 저장장치 슬롯이 없어 교체 업그레이드만 가능합니다."
        recommendation = "영상/게임 목적이면 빈 M.2 슬롯이 있는 구성을 우선하세요."
    else:
        status = CheckStatus.ok
        finding = f"빈 저장장치 슬롯 {free_slots}개로 SSD 추가 여지가 있습니다."
        recommendation = "지원 규격과 방열판 간섭 여부를 확인하세요."
    return UpgradeReadinessItem(
        item_id="storage",
        label="SSD 확장",
        status=status,
        finding=finding,
        recommendation=recommendation,
    )


def _platform_item(request: UpgradeReadinessRequest) -> UpgradeReadinessItem:
    platform = request.cpu_platform.strip() or "플랫폼 미입력"
    lowered = platform.lower()
    if any(token in lowered for token in ("am5", "lga1851", "ultra", "intel core ultra")):
        status = CheckStatus.ok
        finding = f"{platform} 플랫폼은 비교적 장기 사용 여지를 기대할 수 있습니다."
        recommendation = "BIOS 지원 범위와 차세대 CPU 호환 여부를 확인하세요."
    elif any(token in lowered for token in ("am4", "lga1700", "ddr4")):
        status = CheckStatus.warning
        finding = f"{platform} 플랫폼은 가격은 좋지만 장기 CPU 업그레이드 폭이 제한될 수 있습니다."
        recommendation = "현재 성능이 충분한지, CPU 교체보다 전체 교체가 나은 시점을 정하세요."
    else:
        status = CheckStatus.warning
        finding = "CPU 플랫폼 정보가 부족해 장기 호환성을 판단하기 어렵습니다."
        recommendation = "소켓, 칩셋, 메모리 규격, BIOS 업데이트 정책을 확인하세요."
    return UpgradeReadinessItem(
        item_id="platform",
        label="플랫폼 수명",
        status=status,
        finding=finding,
        recommendation=recommendation,
    )


def _power_item(request: UpgradeReadinessRequest) -> UpgradeReadinessItem:
    planned_gpu = any("gpu" in item.lower() or "그래픽" in item for item in request.planned_upgrades)
    if request.psu_watt is None or request.psu_watt <= 0:
        status = CheckStatus.warning
        finding = "파워 용량 정보가 없어 GPU 업그레이드 여유를 판단하기 어렵습니다."
        recommendation = "정격 출력, 제조사, 80PLUS 등급, 보증 기간을 캡처하세요."
    elif request.psu_watt < 650 and planned_gpu:
        status = CheckStatus.blocker
        finding = f"{request.psu_watt}W 파워는 향후 GPU 업그레이드에 부족할 수 있습니다."
        recommendation = "GPU 업그레이드 계획이 있으면 750W 이상 정격 파워 구성을 확인하세요."
    elif request.psu_watt < 650:
        status = CheckStatus.warning
        finding = f"{request.psu_watt}W 파워는 고성능 GPU 교체 여지가 제한됩니다."
        recommendation = "현재 GPU로 충분한지와 파워 교체 비용을 같이 계산하세요."
    else:
        status = CheckStatus.ok
        finding = f"{request.psu_watt}W 파워로 일반적인 GPU 업그레이드 여유가 있습니다."
        recommendation = "보조 전원 커넥터 수와 케이블 규격을 확인하세요."
    return UpgradeReadinessItem(
        item_id="power",
        label="파워 여유",
        status=status,
        finding=finding,
        recommendation=recommendation,
    )


def _case_item(request: UpgradeReadinessRequest) -> UpgradeReadinessItem:
    form = request.case_form_factor.strip() or "케이스 정보 미입력"
    lowered = form.lower()
    if any(token in lowered for token in ("mini", "itx", "slim", "sff")):
        status = CheckStatus.warning
        finding = f"{form} 폼팩터는 GPU 길이, 쿨러 높이, 저장장치 확장에 제한이 있을 수 있습니다."
        recommendation = "GPU 장착 길이, CPU 쿨러 높이, 추가 팬/SSD 공간을 확인하세요."
    elif form == "케이스 정보 미입력":
        status = CheckStatus.warning
        finding = "케이스 폼팩터가 없어 물리 확장 여지를 판단하기 어렵습니다."
        recommendation = "케이스 모델명과 GPU 장착 길이를 판매자에게 확인하세요."
    else:
        status = CheckStatus.ok
        finding = f"{form} 폼팩터는 일반적인 부품 교체 여지를 기대할 수 있습니다."
        recommendation = "실제 케이스 모델의 장착 길이와 팬 구성을 확인하세요."
    return UpgradeReadinessItem(
        item_id="case",
        label="케이스 확장",
        status=status,
        finding=finding,
        recommendation=recommendation,
    )


def _laptop_memory_item(request: UpgradeReadinessRequest) -> UpgradeReadinessItem:
    if request.laptop_ram_upgradeable is True:
        status = CheckStatus.ok
        finding = "노트북 RAM 업그레이드가 가능한 조건입니다."
        recommendation = "온보드+슬롯 조합, 최대 지원 용량, 보증 영향 여부를 확인하세요."
    elif request.laptop_ram_upgradeable is False:
        status = CheckStatus.warning if request.ram_gb >= 32 else CheckStatus.blocker
        finding = "RAM 온보드 또는 업그레이드 불가 조건입니다."
        recommendation = "장기 사용이면 처음부터 32GB 이상 옵션을 우선하세요."
    else:
        status = CheckStatus.warning
        finding = "노트북 RAM 업그레이드 가능 여부가 불명확합니다."
        recommendation = "온보드 여부와 빈 슬롯 유무를 판매자에게 확인하세요."
    return UpgradeReadinessItem(
        item_id="laptop_memory",
        label="노트북 RAM",
        status=status,
        finding=finding,
        recommendation=recommendation,
    )


def _laptop_storage_item(request: UpgradeReadinessRequest) -> UpgradeReadinessItem:
    if request.laptop_storage_upgradeable is True:
        status = CheckStatus.ok
        finding = "노트북 SSD 교체 또는 추가 장착 여지가 있습니다."
        recommendation = "M.2 규격, 빈 슬롯, 보증 봉인 여부를 확인하세요."
    elif request.laptop_storage_upgradeable is False:
        status = CheckStatus.warning
        finding = "저장장치 교체 또는 추가 장착이 제한될 수 있습니다."
        recommendation = "구매 전 충분한 SSD 용량 옵션을 선택하세요."
    else:
        status = CheckStatus.warning
        finding = "노트북 저장장치 확장 가능 여부가 불명확합니다."
        recommendation = "M.2 슬롯 수와 교체 가능 여부를 판매자에게 확인하세요."
    return UpgradeReadinessItem(
        item_id="laptop_storage",
        label="노트북 SSD",
        status=status,
        finding=finding,
        recommendation=recommendation,
    )


def _score(request: UpgradeReadinessRequest, items: list[UpgradeReadinessItem]) -> int:
    score = 100
    score -= sum(24 for item in items if item.status == CheckStatus.blocker)
    score -= sum(10 for item in items if item.status == CheckStatus.warning)
    if request.target_years >= 4:
        score -= 6
    if len(request.planned_upgrades) >= 3:
        score -= 4
    return max(0, min(100, score))


def _priority(score: int, items: list[UpgradeReadinessItem]) -> CheckStatus:
    if any(item.status == CheckStatus.blocker for item in items) or score < 55:
        return CheckStatus.blocker
    if any(item.status == CheckStatus.warning for item in items) or score < 82:
        return CheckStatus.warning
    return CheckStatus.ok


def _horizon_months(request: UpgradeReadinessRequest, score: int) -> int:
    requested = request.target_years * 12
    if score >= 88:
        return requested
    if score >= 70:
        return max(12, requested - 6)
    if score >= 55:
        return max(12, requested - 12)
    return max(6, requested - 18)


def _upgrade_paths(
    request: UpgradeReadinessRequest,
    items: list[UpgradeReadinessItem],
) -> list[UpgradePathOption]:
    item_status = {item.item_id: item.status for item in items}
    paths = [
        UpgradePathOption(
            path_id="memory_32gb",
            label="RAM 32GB 이상 확보",
            priority=CheckStatus.warning if item_status.get("memory") != CheckStatus.ok else CheckStatus.ok,
            timing="구매 전 또는 첫 3개월",
            estimated_cost_krw=120_000,
            expected_gain="영상 편집, 게임, 멀티태스킹에서 체감 병목을 줄입니다.",
            evidence_to_confirm=["RAM 슬롯 수", "최대 지원 용량", "듀얼 채널 구성"],
        ),
        UpgradePathOption(
            path_id="storage_2tb",
            label="SSD 2TB 또는 추가 M.2 확보",
            priority=CheckStatus.warning if item_status.get("storage") != CheckStatus.ok else CheckStatus.ok,
            timing="구매 전 또는 저장공간 70% 도달 전",
            estimated_cost_krw=180_000,
            expected_gain="작업 파일, 게임, 캐시 용량 부족으로 인한 재구매 압박을 줄입니다.",
            evidence_to_confirm=["M.2 슬롯 수", "방열판 간섭", "보증 봉인 여부"],
        ),
    ]
    if request.category == Category.desktop_pc:
        paths.append(
            UpgradePathOption(
                path_id="gpu_power_headroom",
                label="GPU 교체 전 파워/케이스 여유 확인",
                priority=CheckStatus.warning
                if item_status.get("power") != CheckStatus.ok or item_status.get("case") != CheckStatus.ok
                else CheckStatus.ok,
                timing="GPU 교체 1개월 전",
                estimated_cost_krw=250_000,
                expected_gain="그래픽 성능 업그레이드 때 파워와 케이스를 동시에 갈아엎는 비용을 줄입니다.",
                evidence_to_confirm=["정격 파워", "보조 전원 커넥터", "GPU 장착 길이"],
            )
        )
    else:
        paths.append(
            UpgradePathOption(
                path_id="laptop_initial_option",
                label="노트북은 초기 옵션 상향 우선",
                priority=CheckStatus.warning,
                timing="구매 전",
                estimated_cost_krw=300_000,
                expected_gain="온보드 RAM/SSD 제약으로 인한 조기 교체 가능성을 낮춥니다.",
                evidence_to_confirm=["RAM 온보드 여부", "SSD 교체 가능 여부", "제조사 보증 조건"],
            )
        )
    return paths


def _lifecycle_risks(
    request: UpgradeReadinessRequest,
    items: list[UpgradeReadinessItem],
) -> list[str]:
    risks = [item.finding for item in items if item.status != CheckStatus.ok]
    if request.constraints:
        risks.append(f"제약 조건: {', '.join(request.constraints[:4])}")
    if not risks:
        risks.append("현재 입력 기준 장기 사용을 막는 핵심 업그레이드 리스크는 크지 않습니다.")
    return risks[:8]


def _seller_questions(
    request: UpgradeReadinessRequest,
    items: list[UpgradeReadinessItem],
) -> list[str]:
    questions = [
        "RAM 슬롯 수, 사용 중인 슬롯 수, 최대 지원 용량을 확인해 주세요.",
        "M.2/SATA 저장장치 슬롯 수와 빈 슬롯 여부를 확인해 주세요.",
    ]
    if request.category == Category.desktop_pc:
        questions.extend(
            [
                "파워 정격 출력, 제조사, 보증 기간, 보조 전원 커넥터 수를 알려주세요.",
                "케이스 모델명, GPU 장착 가능 길이, CPU 쿨러 높이 제한을 알려주세요.",
            ]
        )
    else:
        questions.extend(
            [
                "RAM이 온보드인지, 교체/추가 슬롯이 있는지 확인해 주세요.",
                "SSD 교체나 추가 장착이 가능한지, 보증 봉인 영향이 있는지 알려주세요.",
            ]
        )
    blockers = [item.label for item in items if item.status == CheckStatus.blocker]
    if blockers:
        questions.insert(0, f"{', '.join(blockers)} 항목이 구매 후 교체 비용으로 이어질 수 있는지 확인해 주세요.")
    return questions[:6]


def _headline(
    request: UpgradeReadinessRequest,
    priority: CheckStatus,
    horizon_months: int,
) -> str:
    if priority == CheckStatus.blocker:
        return f"{_title(request)}는 업그레이드 여지 때문에 구매 전 재확인이 필요합니다."
    if priority == CheckStatus.warning:
        return f"{_title(request)}는 {horizon_months}개월 사용 전제의 업그레이드 조건을 확인해야 합니다."
    return f"{_title(request)}는 {horizon_months}개월 장기 사용 여지가 충분합니다."


def _summary(
    request: UpgradeReadinessRequest,
    priority: CheckStatus,
    score: int,
    horizon_months: int,
) -> str:
    planned = ", ".join(request.planned_upgrades[:4]) if request.planned_upgrades else "RAM/SSD/GPU 여유"
    return (
        f"업그레이드 readiness {score}점, 상태 {priority.value}. "
        f"{request.target_years}년 목표 중 {horizon_months}개월 보유를 기준으로 {planned}를 점검합니다."
    )


def _analysis_prefill(
    request: UpgradeReadinessRequest,
    priority: CheckStatus,
    score: int,
    horizon_months: int,
) -> str:
    return (
        f"{_category_label(request.category)} '{_title(request)}' 업그레이드 여지를 분석해줘. "
        f"플랫폼 {request.cpu_platform or '미입력'}, GPU {request.gpu_name or '미입력'}, "
        f"RAM {request.ram_gb}GB, 저장 슬롯 {request.storage_slots_used}/{request.storage_slots_total}, "
        f"목표 {request.target_years}년, readiness {score}, 상태 {priority.value}, 보유 가능 {horizon_months}개월."
    )


def _category_label(category: Category) -> str:
    return "노트북" if category == Category.laptop else "컴퓨터"


def _share_copy(
    request: UpgradeReadinessRequest,
    priority: CheckStatus,
    score: int,
    horizon_months: int,
) -> str:
    return (
        "SpecPilot AI 업그레이드 수명 검수\n"
        f"제품: {_title(request)}\n"
        f"상태: {priority.value}\n"
        f"readiness: {score}점\n"
        f"예상 보유: {horizon_months}개월"
    )


def _next_actions(priority: CheckStatus, items: list[UpgradeReadinessItem]) -> list[str]:
    blockers = [item for item in items if item.status == CheckStatus.blocker]
    warnings = [item for item in items if item.status == CheckStatus.warning]
    if priority == CheckStatus.blocker:
        return [
            f"{blockers[0].label} 조건을 판매자 답변으로 확인하기 전에는 결제를 보류하세요.",
            "초기 옵션 상향 비용과 1년 내 교체 비용을 비교하세요.",
            "업그레이드가 막힌 후보는 대체 후보 rescue로 넘기세요.",
        ]
    if warnings:
        return [
            f"{warnings[0].label} 항목의 증거를 먼저 캡처하세요.",
            "RAM/SSD/파워/보증 조건을 판매자 질문에 포함하세요.",
            "목표 보유 기간을 기준으로 초기 옵션 상향 여부를 결정하세요.",
        ]
    return [
        "장기 사용 기준으로 RAM/SSD 증설 시점만 캘린더에 남기세요.",
        "판매자 답변과 부품 확장 증거를 구매 승인 브리프에 첨부하세요.",
        "첫 부팅 세팅 검수 때 실제 슬롯과 드라이버 상태를 다시 확인하세요.",
    ]
