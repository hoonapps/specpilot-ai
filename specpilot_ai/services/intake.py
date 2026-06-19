from specpilot_ai.core.models import (
    AnalyzeRequest,
    Category,
    CheckStatus,
    IntakeDiagnosisRequest,
    IntakeDiagnosisResponse,
    IntakeSlotDiagnosis,
)

GENERIC_PURPOSES = {"", "pc setup purchase", "computer purchase", "컴퓨터 구매"}
DEFAULT_CHANNELS = ["price_compare", "open_market", "official_store"]


def diagnose_intake(request: IntakeDiagnosisRequest) -> IntakeDiagnosisResponse:
    query = request.query.strip()
    combined_text = " ".join(
        [
            query,
            request.purpose,
            " ".join(request.must_haves),
            " ".join(request.exclusions),
        ]
    ).lower()
    suggested_must_haves = _suggest_must_haves(request, combined_text)
    suggested_exclusions = _suggest_exclusions(request)
    normalized_purpose = _normalized_purpose(request, combined_text)
    normalized_must_haves = _merge_unique(request.must_haves, suggested_must_haves)
    normalized_exclusions = _merge_unique(request.exclusions, suggested_exclusions)
    normalized_channels = request.channels or DEFAULT_CHANNELS

    slot_diagnostics = [
        _query_slot(query),
        _budget_slot(request),
        _purpose_slot(request, normalized_purpose),
        _must_have_slot(request, suggested_must_haves),
        _exclusion_slot(request, suggested_exclusions),
        _category_specific_slot(request, combined_text),
    ]
    missing_slots = [
        item.slot for item in slot_diagnostics if item.status == CheckStatus.blocker
    ]
    warnings = [
        item.message for item in slot_diagnostics if item.status == CheckStatus.warning
    ]
    clarifying_questions = _clarifying_questions(request, slot_diagnostics, combined_text)
    readiness_score = _readiness_score(slot_diagnostics)
    readiness_label = _readiness_label(readiness_score, missing_slots)
    next_action = _next_action(readiness_score, missing_slots)

    normalized_request = AnalyzeRequest(
        query=query or "컴퓨터 구매 조건을 더 구체화해 주세요.",
        category=request.category,
        budget_krw=request.budget_krw if request.budget_krw and request.budget_krw > 0 else None,
        purpose=normalized_purpose,
        must_haves=normalized_must_haves,
        exclusions=normalized_exclusions,
        purchase_timing=request.purchase_timing,
        channels=normalized_channels,
    )
    return IntakeDiagnosisResponse(
        readiness_score=readiness_score,
        readiness_label=readiness_label,
        next_action=next_action,
        missing_slots=missing_slots,
        clarifying_questions=clarifying_questions,
        suggested_must_haves=suggested_must_haves,
        suggested_exclusions=suggested_exclusions,
        slot_diagnostics=slot_diagnostics,
        normalized_request=normalized_request,
        warnings=warnings,
    )


def _query_slot(query: str) -> IntakeSlotDiagnosis:
    if len(query) < 8:
        return IntakeSlotDiagnosis(
            slot="query",
            label="구매 요청",
            status=CheckStatus.blocker,
            message="구매 요청이 너무 짧아 목적과 우선순위를 추론하기 어렵습니다.",
            recommendation="용도, 예산, 화면 해상도 또는 휴대성 조건을 한 문장으로 적어 주세요.",
        )
    return IntakeSlotDiagnosis(
        slot="query",
        label="구매 요청",
        status=CheckStatus.ok,
        message="분석 가능한 자연어 요청입니다.",
        recommendation="현재 요청으로 후보 수집과 점수화를 시작할 수 있습니다.",
    )


def _budget_slot(request: IntakeDiagnosisRequest) -> IntakeSlotDiagnosis:
    if request.budget_krw is None or request.budget_krw <= 0:
        return IntakeSlotDiagnosis(
            slot="budget_krw",
            label="예산",
            status=CheckStatus.blocker,
            message="예산이 없어 가격 경쟁력과 구매 타이밍 판단이 약해집니다.",
            recommendation="최대 예산 또는 희망 가격대를 원 단위로 입력해 주세요.",
        )
    if request.category == Category.desktop_pc and request.budget_krw < 900_000:
        return IntakeSlotDiagnosis(
            slot="budget_krw",
            label="예산",
            status=CheckStatus.warning,
            message="데스크톱 작업/게임용 견적으로는 예산이 낮아 옵션 타협이 필요할 수 있습니다.",
            recommendation="중고 제외 여부, GPU 성능 목표, 업그레이드 가능성을 다시 정하세요.",
        )
    if request.category == Category.laptop and request.budget_krw < 800_000:
        return IntakeSlotDiagnosis(
            slot="budget_krw",
            label="예산",
            status=CheckStatus.warning,
            message="노트북 예산이 낮아 디스플레이, RAM, 무게 중 우선순위가 필요합니다.",
            recommendation="휴대성, 성능, 배터리 중 포기할 수 없는 조건을 하나 고르세요.",
        )
    return IntakeSlotDiagnosis(
        slot="budget_krw",
        label="예산",
        status=CheckStatus.ok,
        message="가격 비교와 목표가 계산에 사용할 수 있는 예산입니다.",
        recommendation="분석 후 목표가 알림과 적정가 밴드를 함께 확인하세요.",
    )


def _purpose_slot(
    request: IntakeDiagnosisRequest,
    normalized_purpose: str,
) -> IntakeSlotDiagnosis:
    if (
        request.purpose.strip().lower() in GENERIC_PURPOSES
        and normalized_purpose.strip().lower() in GENERIC_PURPOSES
    ):
        return IntakeSlotDiagnosis(
            slot="purpose",
            label="사용 목적",
            status=CheckStatus.blocker,
            message="사용 목적이 없어 CPU/GPU/RAM 가중치를 정하기 어렵습니다.",
            recommendation="게임, 영상 편집, 개발, 사무, AI 실험처럼 실제 작업을 적어 주세요.",
        )
    if request.purpose.strip().lower() in GENERIC_PURPOSES:
        return IntakeSlotDiagnosis(
            slot="purpose",
            label="사용 목적",
            status=CheckStatus.warning,
            message=f"요청 문장에서 '{normalized_purpose}' 목적을 추론했습니다.",
            recommendation="정확도를 높이려면 사용하는 앱이나 게임, 해상도를 추가하세요.",
        )
    return IntakeSlotDiagnosis(
        slot="purpose",
        label="사용 목적",
        status=CheckStatus.ok,
        message="목적별 가중치를 계산할 수 있습니다.",
        recommendation="분석 결과에서 목적 적합도와 병목 근거를 확인하세요.",
    )


def _must_have_slot(
    request: IntakeDiagnosisRequest,
    suggested_must_haves: list[str],
) -> IntakeSlotDiagnosis:
    if not request.must_haves and not suggested_must_haves:
        return IntakeSlotDiagnosis(
            slot="must_haves",
            label="필수 조건",
            status=CheckStatus.warning,
            message="필수 조건이 없어 범용 추천으로 넓게 분석합니다.",
            recommendation="RAM, GPU, 해상도, 무게, 업그레이드 여지 중 중요한 조건을 추가하세요.",
        )
    if not request.must_haves and suggested_must_haves:
        return IntakeSlotDiagnosis(
            slot="must_haves",
            label="필수 조건",
            status=CheckStatus.warning,
            message="요청 문장에서 필수 조건 후보를 추론했습니다.",
            recommendation=", ".join(suggested_must_haves),
        )
    return IntakeSlotDiagnosis(
        slot="must_haves",
        label="필수 조건",
        status=CheckStatus.ok,
        message="조건 충족 매트릭스를 계산할 수 있습니다.",
        recommendation="분석 결과에서 충족, 경고, 차단 항목을 비교하세요.",
    )


def _exclusion_slot(
    request: IntakeDiagnosisRequest,
    suggested_exclusions: list[str],
) -> IntakeSlotDiagnosis:
    if not request.exclusions:
        return IntakeSlotDiagnosis(
            slot="exclusions",
            label="제외 조건",
            status=CheckStatus.warning,
            message="제외 조건이 없어 리퍼, 중고, 출처 없는 가격이 후보에 섞일 수 있습니다.",
            recommendation=", ".join(suggested_exclusions),
        )
    return IntakeSlotDiagnosis(
        slot="exclusions",
        label="제외 조건",
        status=CheckStatus.ok,
        message="구매 차단 조건을 비교표에 반영할 수 있습니다.",
        recommendation="최종 결제 전 제외 조건이 판매 페이지와 일치하는지 확인하세요.",
    )


def _category_specific_slot(
    request: IntakeDiagnosisRequest,
    combined_text: str,
) -> IntakeSlotDiagnosis:
    if request.category == Category.desktop_pc:
        desktop_signals = ["qhd", "4k", "144", "rtx", "gpu", "업그레이드", "파워", "케이스"]
        if not any(signal in combined_text for signal in desktop_signals):
            return IntakeSlotDiagnosis(
                slot="desktop_context",
                label="데스크톱 맥락",
                status=CheckStatus.warning,
                message="모니터 해상도, GPU 목표, 업그레이드 조건이 부족합니다.",
                recommendation="QHD/4K, 목표 FPS, GPU 등급, 케이스/파워 재사용 여부를 알려 주세요.",
            )
    else:
        laptop_signals = ["무게", "휴대", "배터리", "외장", "gpu", "oled", "디스플레이"]
        if not any(signal in combined_text for signal in laptop_signals):
            return IntakeSlotDiagnosis(
                slot="laptop_context",
                label="노트북 맥락",
                status=CheckStatus.warning,
                message="노트북은 무게, 배터리, 디스플레이, GPU 옵션 우선순위가 필요합니다.",
                recommendation="최대 무게, 배터리 기대치, 외장 GPU 필요 여부를 알려 주세요.",
            )
    return IntakeSlotDiagnosis(
        slot="category_context",
        label="카테고리 맥락",
        status=CheckStatus.ok,
        message="카테고리별 핵심 판단 조건이 충분합니다.",
        recommendation="분석 결과에서 호환성과 옵션 검수표를 확인하세요.",
    )


def _suggest_must_haves(
    request: IntakeDiagnosisRequest,
    combined_text: str,
) -> list[str]:
    suggestions: list[str] = []
    if any(keyword in combined_text for keyword in ["영상", "편집", "premiere", "davinci"]):
        suggestions.extend(["32GB RAM", "1TB SSD"])
        if request.category == Category.laptop:
            suggestions.append("외장 GPU")
    if any(keyword in combined_text for keyword in ["qhd", "144"]):
        suggestions.append("QHD 144Hz")
    if "4k" in combined_text:
        suggestions.append("4K 작업 대응")
    if any(keyword in combined_text for keyword in ["개발", "docker", "ai 실험", "llm"]):
        suggestions.extend(["32GB RAM", "8코어 이상 CPU"])
    if request.category == Category.desktop_pc and "업그레이드" in combined_text:
        suggestions.append("업그레이드 여지")
    if request.category == Category.laptop and any(
        keyword in combined_text for keyword in ["휴대", "이동", "출장"]
    ):
        suggestions.extend(["1.8kg 이하", "배터리 8시간 이상"])
    return [item for item in _merge_unique([], suggestions) if item not in request.must_haves]


def _suggest_exclusions(request: IntakeDiagnosisRequest) -> list[str]:
    base = ["중고", "리퍼", "출처 없는 가격"]
    existing = {item.strip().lower() for item in request.exclusions}
    return [item for item in base if item.lower() not in existing]


def _normalized_purpose(
    request: IntakeDiagnosisRequest,
    combined_text: str,
) -> str:
    purpose = request.purpose.strip()
    if purpose and purpose.lower() not in GENERIC_PURPOSES:
        return purpose
    inferred: list[str] = []
    if any(keyword in combined_text for keyword in ["영상", "편집", "premiere", "davinci"]):
        inferred.append("video editing")
    if any(keyword in combined_text for keyword in ["게임", "gaming", "qhd", "144", "4k"]):
        inferred.append("gaming")
    if any(keyword in combined_text for keyword in ["개발", "docker", "ai 실험", "llm"]):
        inferred.append("development")
    if any(keyword in combined_text for keyword in ["사무", "사업자", "office"]):
        inferred.append("office productivity")
    if request.category == Category.laptop and any(
        keyword in combined_text for keyword in ["휴대", "출장", "이동"]
    ):
        inferred.append("portable work")
    return ", ".join(_merge_unique([], inferred)) or "pc setup purchase"


def _clarifying_questions(
    request: IntakeDiagnosisRequest,
    slot_diagnostics: list[IntakeSlotDiagnosis],
    combined_text: str,
) -> list[str]:
    questions: list[str] = []
    for item in slot_diagnostics:
        if item.status == CheckStatus.ok:
            continue
        if item.slot == "budget_krw":
            questions.append("최대 예산과 초과 가능한 범위는 얼마인가요?")
        elif item.slot == "purpose":
            questions.append("가장 중요한 작업은 게임, 영상 편집, 개발, 사무 중 무엇인가요?")
        elif item.slot == "must_haves":
            questions.append("반드시 필요한 조건은 RAM, GPU, 해상도, 무게 중 무엇인가요?")
        elif item.slot == "exclusions":
            questions.append("중고, 리퍼, 출처 없는 가격을 제외할까요?")
        elif item.slot == "desktop_context":
            questions.append("사용할 모니터 해상도와 목표 주사율은 무엇인가요?")
            if "업그레이드" not in combined_text:
                questions.append("업그레이드 여지를 우선할까요, 현재 성능을 우선할까요?")
        elif item.slot == "laptop_context":
            questions.append("최대 허용 무게와 배터리 기대 시간은 어느 정도인가요?")
            questions.append("외장 GPU가 꼭 필요한가요?")
        elif item.slot == "query":
            questions.append("어떤 용도와 예산으로 컴퓨터 또는 노트북을 구매하려고 하나요?")
    return _merge_unique([], questions)[:5]


def _readiness_score(slot_diagnostics: list[IntakeSlotDiagnosis]) -> float:
    score = 100.0
    for item in slot_diagnostics:
        if item.status == CheckStatus.blocker:
            score -= 22.0
        elif item.status == CheckStatus.warning:
            score -= 9.0
    return max(0.0, min(100.0, round(score, 1)))


def _readiness_label(score: float, missing_slots: list[str]) -> str:
    if missing_slots:
        return "분석 전 질문 필요"
    if score >= 78:
        return "바로 분석 가능"
    if score >= 55:
        return "추가 질문 권장"
    return "분석 전 보강 필요"


def _next_action(score: float, missing_slots: list[str]) -> str:
    if missing_slots:
        return "누락 조건을 먼저 채운 뒤 분석하세요."
    if score >= 78:
        return "현재 조건으로 분석을 실행하고, 결과에서 가격 타이밍과 옵션 검수표를 확인하세요."
    return "추천 질문에 답하면 목적 적합도와 조건 충족 매트릭스 정확도가 올라갑니다."


def _merge_unique(existing: list[str], additions: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*existing, *additions]:
        normalized = item.strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
    return merged
