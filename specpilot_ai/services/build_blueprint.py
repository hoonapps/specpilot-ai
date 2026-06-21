from datetime import UTC, datetime

from specpilot_ai.core.models import (
    BuildBlueprintComponent,
    BuildBlueprintRequest,
    BuildBlueprintSearchQuery,
    Category,
    CheckStatus,
    PublicBuildBlueprintKit,
    SetupCompatibilityRequest,
)


def build_public_build_blueprint_kit(
    request: BuildBlueprintRequest,
    generated_at: datetime | None = None,
) -> PublicBuildBlueprintKit:
    generated_at = generated_at or datetime.now(UTC)
    components = _components(request)
    avoid_conditions = _avoid_conditions(request, components)
    status = _blueprint_status(request, components, avoid_conditions)
    score = _blueprint_score(request, components, avoid_conditions, status)
    target_profile = _target_profile(request)
    setup_prefill = _setup_prefill(request)
    return PublicBuildBlueprintKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        blueprint_status=status,
        blueprint_score=score,
        headline=_headline(request, status, score),
        summary=_summary(request, components, status),
        budget_krw=request.budget_krw,
        target_profile=target_profile,
        component_budget_total_krw=sum(component.budget_max_krw for component in components),
        components=components,
        search_queries=_search_queries(request, components, avoid_conditions),
        compatibility_rules=_compatibility_rules(request),
        avoid_conditions=avoid_conditions,
        cart_text_template=_cart_text_template(components),
        setup_prefill=setup_prefill,
        analysis_prefill=_analysis_prefill(request, components, avoid_conditions),
        share_copy=_share_copy(request, status, score, components, avoid_conditions),
        next_actions=_next_actions(status),
    )


def _components(request: BuildBlueprintRequest) -> list[BuildBlueprintComponent]:
    if request.category == Category.laptop:
        return _laptop_components(request)
    return _desktop_components(request)


def _desktop_components(request: BuildBlueprintRequest) -> list[BuildBlueprintComponent]:
    budget = request.budget_krw
    mode = request.priority_mode.casefold()
    gpu_ratio = 0.42 if _gaming(request) else 0.34
    cpu_ratio = 0.18 if _gaming(request) else 0.21
    if "budget" in mode or "가성비" in mode:
        gpu_ratio -= 0.04
        cpu_ratio -= 0.01
    if "performance" in mode or "성능" in mode:
        gpu_ratio += 0.04
    parts = [
        _component(
            "gpu",
            "그래픽카드",
            _gpu_target(request),
            budget,
            gpu_ratio,
            CheckStatus.ok if budget >= 1_400_000 else CheckStatus.warning,
            "게임, 영상 편집, QHD 모니터 체감 성능을 가장 크게 좌우합니다.",
            ["RTX 4070 SUPER", "RTX 4070", "RX 7800 XT"],
            ["채굴", "리퍼", "AS 불명"],
        ),
        _component(
            "cpu",
            "CPU",
            _cpu_target(request),
            budget,
            cpu_ratio,
            CheckStatus.ok,
            "프레임 유지, 인코딩, 장기 업그레이드 여지를 결정합니다.",
            ["Ryzen 7 7800X3D", "Ryzen 7 7700", "Core i5 14600"],
            ["벌크 쿨러 누락", "구형 플랫폼"],
        ),
        _component(
            "memory",
            "메모리",
            _ram_target(request),
            budget,
            0.07,
            CheckStatus.ok,
            "게임과 편집 작업의 동시 실행, 브라우저 탭, 캐시 작업 안정성을 좌우합니다.",
            ["DDR5 32GB", "16GBx2", "5600MHz"],
            ["단일 16GB", "온보드"],
        ),
        _component(
            "storage",
            "SSD",
            _storage_target(request),
            budget,
            0.06,
            CheckStatus.ok,
            "OS, 게임, 원본 영상 파일을 동시에 두면 1TB 미만은 빨리 부족해집니다.",
            ["NVMe 1TB", "PCIe 4.0", "TLC"],
            ["QLC 단독", "512GB 단독"],
        ),
        _component(
            "mainboard",
            "메인보드",
            _board_target(request),
            budget,
            0.09,
            CheckStatus.warning,
            "CPU 세대, RAM 규격, SSD 슬롯, 전원부와 업그레이드 경로를 고정합니다.",
            ["B650", "DDR5", "M.2 2슬롯"],
            ["A620 저가형", "BIOS 미확인"],
        ),
        _component(
            "power_case",
            "파워/케이스",
            _power_case_target(request),
            budget,
            0.10,
            CheckStatus.warning,
            "GPU 길이, 발열, 소음, 전력 여유가 부족하면 좋은 부품도 제 성능을 못 냅니다.",
            ["750W", "80PLUS Gold", "ATX mesh"],
            ["정격 불명", "전면 폐쇄형"],
        ),
        _component(
            "os_assembly",
            "OS/조립/배송",
            "Windows 포함 여부와 조립비, 배송비를 최종가에 반드시 포함",
            budget,
            0.08,
            CheckStatus.warning,
            "FreeDOS, 조립비, 배송비를 빼고 비교하면 실제 결제 금액이 흔들립니다.",
            ["Windows 11", "조립 포함", "국내 AS"],
            ["FreeDOS 미고지", "반품 불가"],
        ),
    ]
    return _fit_budget(parts, budget)


def _laptop_components(request: BuildBlueprintRequest) -> list[BuildBlueprintComponent]:
    budget = request.budget_krw
    portable = request.portability.casefold()
    high_portability = any(term in portable for term in ["portable", "light", "휴대", "가벼"])
    gpu_status = CheckStatus.warning if high_portability and _gaming(request) else CheckStatus.ok
    parts = [
        _component(
            "cpu_gpu",
            "CPU/GPU",
            _laptop_cpu_gpu_target(request),
            budget,
            0.43,
            gpu_status,
            "노트북은 CPU/GPU가 납땜 구조라 구매 후 교체가 사실상 어렵습니다.",
            ["RTX 4060 노트북", "Core Ultra 7", "Ryzen AI 9"],
            ["저전력 GPU TGP 미표기", "내장그래픽 단독"],
        ),
        _component(
            "memory",
            "메모리",
            _ram_target(request),
            budget,
            0.07,
            CheckStatus.warning,
            "온보드 RAM은 증설이 안 될 수 있어 16GB/32GB 선택을 구매 전에 끝내야 합니다.",
            ["RAM 32GB", "LPDDR5X", "확장 슬롯"],
            ["8GB", "온보드 16GB 고정"],
        ),
        _component(
            "storage",
            "SSD",
            _storage_target(request),
            budget,
            0.06,
            CheckStatus.ok,
            "노트북 SSD 슬롯 수와 보증 유지 조건을 함께 확인해야 합니다.",
            ["SSD 1TB", "M.2 추가 슬롯"],
            ["512GB 단독", "분해 시 보증 제외"],
        ),
        _component(
            "display",
            "디스플레이",
            _display_target(request),
            budget,
            0.14,
            CheckStatus.ok,
            "해상도, 색역, 밝기, 주사율은 체감 품질과 작업 피로도를 바로 바꿉니다.",
            ["QHD 120Hz", "sRGB 100%", "400nit"],
            ["45% NTSC", "250nit"],
        ),
        _component(
            "mobility",
            "무게/배터리",
            _mobility_target(request),
            budget,
            0.10,
            CheckStatus.warning if high_portability else CheckStatus.ok,
            "휴대성이 중요하면 성능보다 무게, 어댑터, 배터리 Wh를 먼저 고정해야 합니다.",
            ["1.5kg 이하", "70Wh 이상", "USB-C 충전"],
            ["무게 미표기", "소형 배터리"],
        ),
        _component(
            "warranty",
            "AS/반품/OS",
            "국내 AS, 초기 불량 교환, Windows 포함 여부 확인",
            budget,
            0.10,
            CheckStatus.warning,
            "노트북은 초기 불량과 AS 동선이 비용 차이를 크게 만듭니다.",
            ["국내 정품", "Windows 11", "반품 7일"],
            ["해외 병행", "리퍼", "반품 불가"],
        ),
    ]
    return _fit_budget(parts, budget)


def _component(
    component_id: str,
    label: str,
    target_spec: str,
    budget: int,
    ratio: float,
    priority: CheckStatus,
    why_it_matters: str,
    search_terms: list[str],
    avoid_terms: list[str],
) -> BuildBlueprintComponent:
    center = int(budget * ratio)
    low = max(30_000, int(center * 0.82))
    high = max(low + 10_000, int(center * 1.18))
    return BuildBlueprintComponent(
        component_id=component_id,
        label=label,
        target_spec=target_spec,
        budget_min_krw=low,
        budget_max_krw=high,
        priority=priority,
        why_it_matters=why_it_matters,
        search_terms=search_terms,
        avoid_terms=avoid_terms,
    )


def _fit_budget(
    components: list[BuildBlueprintComponent],
    budget: int,
) -> list[BuildBlueprintComponent]:
    total = sum(component.budget_max_krw for component in components)
    if total <= budget:
        return components
    scale = budget / total
    fitted: list[BuildBlueprintComponent] = []
    for component in components:
        fitted.append(
            component.model_copy(
                update={
                    "budget_min_krw": int(component.budget_min_krw * scale),
                    "budget_max_krw": int(component.budget_max_krw * scale),
                }
            )
        )
    return fitted


def _gaming(request: BuildBlueprintRequest) -> bool:
    text = " ".join([request.purpose, *request.must_haves]).casefold()
    return any(term in text for term in ["game", "gaming", "qhd", "4k", "게임", "게이밍"])


def _creator(request: BuildBlueprintRequest) -> bool:
    text = " ".join([request.purpose, *request.must_haves]).casefold()
    return any(term in text for term in ["edit", "creator", "video", "영상", "편집", "디자인"])


def _gpu_target(request: BuildBlueprintRequest) -> str:
    if request.budget_krw >= 3_000_000:
        return "RTX 4080급까지 비교하되 총액과 파워/케이스 여유를 함께 확인"
    if request.budget_krw >= 2_000_000:
        return "RTX 4070 SUPER급 GPU, QHD 고주사율과 영상 편집 균형"
    if request.budget_krw >= 1_400_000:
        return "RTX 4060 Ti~RTX 4070급, FHD/QHD 옵션 타협 기준"
    return "내장그래픽 또는 RTX 4060급 특가, 게임 옵션 타협 전제"


def _cpu_target(request: BuildBlueprintRequest) -> str:
    if _gaming(request):
        return "Ryzen 7 7800X3D 또는 동급 게임 성능 CPU"
    if _creator(request):
        return "8코어 이상 CPU, 인코딩과 멀티태스킹 균형"
    return "최신 6~8코어 CPU, 장기 업그레이드 가능한 플랫폼"


def _ram_target(request: BuildBlueprintRequest) -> str:
    if request.budget_krw >= 1_500_000 or _creator(request):
        return "RAM 32GB, 가능하면 16GBx2 구성"
    return "RAM 16GB 이상, 추후 32GB 업그레이드 여지 확보"


def _storage_target(request: BuildBlueprintRequest) -> str:
    if _creator(request) or request.budget_krw >= 1_500_000:
        return "NVMe SSD 1TB 이상, 영상/게임 라이브러리 여유 확보"
    return "NVMe SSD 512GB 이상, 추가 슬롯 확인"


def _board_target(request: BuildBlueprintRequest) -> str:
    if request.budget_krw >= 1_800_000:
        return "B650/B760급 이상, DDR5, M.2 2개 이상, BIOS 업데이트 확인"
    return "CPU와 호환되는 보급형 보드, RAM/SSD 확장 슬롯 확인"


def _power_case_target(request: BuildBlueprintRequest) -> str:
    if request.budget_krw >= 2_000_000:
        return "정격 750W 이상, 80PLUS Gold 권장, GPU 길이와 통풍 확인"
    return "정격 650W 이상, 전면 mesh 케이스, GPU 길이 확인"


def _laptop_cpu_gpu_target(request: BuildBlueprintRequest) -> str:
    if _gaming(request) and request.budget_krw >= 1_700_000:
        return "RTX 4060~4070 노트북 GPU, TGP 표기와 발열 리뷰 확인"
    if _creator(request):
        return "최신 Core Ultra/Ryzen 7급, 내장 NPU보다 RAM/디스플레이 우선"
    return "최신 6~8코어 저전력 CPU, 내장그래픽은 목적이 가벼울 때만 선택"


def _display_target(request: BuildBlueprintRequest) -> str:
    resolution = request.monitor_resolution.upper()
    if _creator(request):
        return f"{resolution}급, sRGB 100% 이상, 400nit 내외 밝기"
    if _gaming(request):
        return f"{resolution}급, 120Hz 이상, 응답속도와 밝기 확인"
    return "FHD 이상, 눈부심 방지와 밝기 300nit 이상"


def _mobility_target(request: BuildBlueprintRequest) -> str:
    portable = request.portability.casefold()
    if any(term in portable for term in ["portable", "light", "휴대", "가벼"]):
        return "1.5kg 이하, 70Wh 이상, USB-C 충전 지원"
    if _gaming(request):
        return "2.3kg 이하 가능하면 우선, 어댑터 무게와 소음 리뷰 확인"
    return "1.8kg 이하, 배터리 60Wh 이상, 포트 구성 확인"


def _target_profile(request: BuildBlueprintRequest) -> str:
    label = "노트북" if request.category == Category.laptop else "데스크톱 PC"
    return f"{label} / {request.purpose} / 예산 {request.budget_krw:,}원 / {request.priority_mode}"


def _avoid_conditions(
    request: BuildBlueprintRequest,
    components: list[BuildBlueprintComponent],
) -> list[str]:
    avoid = [
        "최종 결제 금액에 배송비, 조립비, OS 비용이 빠진 견적",
        "상품명과 옵션명에서 RAM/SSD/GPU 용량이 다른 후보",
        "반품 불가, 해외 리퍼, AS 주체 불명 조건",
    ]
    for component in components:
        avoid.extend(component.avoid_terms[:2])
    avoid.extend(request.exclusions)
    if request.owned_parts:
        avoid.append("보유 부품과 호환성 확인 없이 세트 상품을 바로 결제")
    return list(dict.fromkeys(item for item in avoid if item))[:10]


def _blueprint_status(
    request: BuildBlueprintRequest,
    components: list[BuildBlueprintComponent],
    avoid_conditions: list[str],
) -> CheckStatus:
    if request.budget_krw < 800_000 and (_gaming(request) or _creator(request)):
        return CheckStatus.blocker
    if any("리퍼" in condition or "반품 불가" in condition for condition in request.exclusions):
        return CheckStatus.warning
    if any(component.priority == CheckStatus.warning for component in components):
        return CheckStatus.warning
    if len(avoid_conditions) >= 7:
        return CheckStatus.warning
    return CheckStatus.ok


def _blueprint_score(
    request: BuildBlueprintRequest,
    components: list[BuildBlueprintComponent],
    avoid_conditions: list[str],
    status: CheckStatus,
) -> int:
    score = 88
    if request.must_haves:
        score += min(6, len(request.must_haves) * 2)
    if request.owned_parts:
        score -= 4
    score -= sum(4 for component in components if component.priority == CheckStatus.warning)
    score -= min(8, len(avoid_conditions) // 2)
    if status == CheckStatus.blocker:
        score -= 25
    return max(0, min(100, score))


def _search_queries(
    request: BuildBlueprintRequest,
    components: list[BuildBlueprintComponent],
    avoid_conditions: list[str],
) -> list[BuildBlueprintSearchQuery]:
    must_include = _must_include(request, components)
    must_exclude = avoid_conditions[:5]
    label = "노트북" if request.category == Category.laptop else "조립 PC"
    return [
        BuildBlueprintSearchQuery(
            channel="price_compare",
            query=f"{label} {request.purpose} {request.budget_krw:,}원 {' '.join(must_include[:3])}",
            intent="가격비교 사이트에서 후보군을 넓게 찾기",
            must_include=must_include[:5],
            must_exclude=must_exclude,
        ),
        BuildBlueprintSearchQuery(
            channel="open_market",
            query=f"{label} {' '.join(must_include[:4])} 국내 AS 반품",
            intent="실제 판매 페이지에서 옵션명과 배송/반품 조건 확인",
            must_include=["국내 AS", "반품 조건", *must_include[:3]],
            must_exclude=must_exclude,
        ),
        BuildBlueprintSearchQuery(
            channel="community",
            query=f"{request.purpose} {label} 견적 검토 {request.budget_krw // 10_000}만원",
            intent="커뮤니티에 빠진 조건과 과투자 여부 검토 요청",
            must_include=["예산", "용도", "제외 조건", *must_include[:2]],
            must_exclude=must_exclude[:3],
        ),
    ]


def _must_include(
    request: BuildBlueprintRequest,
    components: list[BuildBlueprintComponent],
) -> list[str]:
    terms = [term for component in components for term in component.search_terms[:1]]
    terms.extend(request.must_haves)
    return list(dict.fromkeys(term for term in terms if term))[:8]


def _compatibility_rules(request: BuildBlueprintRequest) -> list[str]:
    if request.category == Category.laptop:
        return [
            "RAM이 온보드인지, 추가 슬롯이 있는지 구매 전에 확인합니다.",
            "GPU가 있으면 TGP, 발열, 팬 소음 리뷰를 같이 봅니다.",
            "무게는 본체와 어댑터를 따로 확인합니다.",
            "Windows 포함 여부와 국내 AS 주체를 최종가 비교에 포함합니다.",
        ]
    return [
        "CPU 소켓, 메인보드 칩셋, RAM 규격을 같은 세대로 맞춥니다.",
        "GPU 길이, 케이스 내부 공간, 파워 정격 용량을 동시에 확인합니다.",
        "SSD 슬롯 수와 방열판 유무를 확인합니다.",
        "OS, 조립비, 배송비를 최종 실구매가에 넣습니다.",
    ]


def _setup_prefill(request: BuildBlueprintRequest) -> SetupCompatibilityRequest:
    if request.category == Category.laptop:
        return SetupCompatibilityRequest(
            category=request.category,
            cpu="Core Ultra 7 또는 Ryzen 7급",
            gpu="RTX 4060 Laptop" if _gaming(request) else "내장그래픽 또는 RTX 4050",
            ram_gb=32 if request.budget_krw >= 1_400_000 or _creator(request) else 16,
            storage_gb=1000 if request.budget_krw >= 1_200_000 else 512,
            monitor_resolution=request.monitor_resolution,
            weight_kg=1.5 if "portable" in request.portability.casefold() else 1.9,
            battery_wh=70,
            budget_krw=request.budget_krw,
            purpose=request.purpose,
            source="build_blueprint",
        )
    return SetupCompatibilityRequest(
        category=request.category,
        cpu="Ryzen 7 7800X3D" if _gaming(request) else "Ryzen 7 7700",
        gpu="RTX 4070 SUPER" if request.budget_krw >= 2_000_000 else "RTX 4060 Ti",
        ram_gb=32 if request.budget_krw >= 1_500_000 or _creator(request) else 16,
        storage_gb=1000 if request.budget_krw >= 1_400_000 else 512,
        monitor_resolution=request.monitor_resolution,
        psu_watt=750 if request.budget_krw >= 1_800_000 else 650,
        form_factor="ATX tower",
        budget_krw=request.budget_krw,
        purpose=request.purpose,
        source="build_blueprint",
    )


def _cart_text_template(components: list[BuildBlueprintComponent]) -> str:
    return "\n".join(
        f"{component.label}: {component.target_spec} / 예산 {component.budget_min_krw:,}~{component.budget_max_krw:,}원"
        for component in components
    )


def _analysis_prefill(
    request: BuildBlueprintRequest,
    components: list[BuildBlueprintComponent],
    avoid_conditions: list[str],
) -> str:
    must = ", ".join(_must_include(request, components))
    avoid = ", ".join(avoid_conditions[:5])
    return (
        "SpecPilot AI 구매 설계도 기반으로 후보를 추천해줘.\n"
        f"- 카테고리: {'노트북' if request.category == Category.laptop else '데스크톱 PC'}\n"
        f"- 예산: {request.budget_krw:,}원\n"
        f"- 목적: {request.purpose}\n"
        f"- 필수 포함: {must or '미입력'}\n"
        f"- 제외 조건: {avoid or '미입력'}\n"
        f"- 구매 시점: {request.purchase_timing}"
    )


def _headline(
    request: BuildBlueprintRequest,
    status: CheckStatus,
    score: int,
) -> str:
    label = "노트북" if request.category == Category.laptop else "데스크톱 PC"
    if status == CheckStatus.blocker:
        return f"{label} 예산 {request.budget_krw:,}원 설계도는 목표를 낮추거나 예산을 조정해야 합니다."
    if status == CheckStatus.warning:
        return f"{label} 설계도 {score}점, 검색 전에 위험 조건을 제외하고 시작하세요."
    return f"{label} 설계도 {score}점, 이 조건으로 후보를 좁혀도 됩니다."


def _summary(
    request: BuildBlueprintRequest,
    components: list[BuildBlueprintComponent],
    status: CheckStatus,
) -> str:
    status_text = "분석 가능" if status == CheckStatus.ok else "조건 확인 필요"
    lead = components[0].target_spec if components else request.purpose
    return (
        f"{request.budget_krw:,}원 예산을 {len(components)}개 구매 축으로 나누고 "
        f"첫 기준을 '{lead}'로 잡았습니다. 현재 상태는 {status_text}입니다."
    )


def _share_copy(
    request: BuildBlueprintRequest,
    status: CheckStatus,
    score: int,
    components: list[BuildBlueprintComponent],
    avoid_conditions: list[str],
) -> str:
    component_lines = "\n".join(
        f"- {component.label}: {component.target_spec}"
        for component in components[:5]
    )
    return (
        "SpecPilot AI 구매 설계도\n"
        f"- 예산: {request.budget_krw:,}원\n"
        f"- 목적: {request.purpose}\n"
        f"- 점수: {score}점 / {status.value}\n"
        f"{component_lines}\n"
        f"- 제외: {', '.join(avoid_conditions[:4])}"
    )


def _next_actions(status: CheckStatus) -> list[str]:
    if status == CheckStatus.blocker:
        return [
            "예산을 올리거나 QHD/게임/편집 목표 중 하나를 낮춥니다.",
            "설계도를 다시 만든 뒤 후보 비교와 호환성 검수로 넘어갑니다.",
            "반품 불가, 해외 리퍼, AS 불명 조건은 후보에서 제외합니다.",
        ]
    if status == CheckStatus.warning:
        return [
            "검색어로 후보를 찾기 전에 제외 조건을 가격비교 필터와 메모에 고정합니다.",
            "설계도 prefill로 세팅 호환성 검수를 먼저 돌립니다.",
            "후보 2~6개가 모이면 커스텀 후보 비교로 바로 좁힙니다.",
        ]
    return [
        "가격비교 검색어로 후보를 모읍니다.",
        "장바구니 텍스트를 붙여 넣어 실구매가와 누락 슬롯을 확인합니다.",
        "최종 후보는 체크아웃 잠금과 결정 방어 브리프로 공유합니다.",
    ]
