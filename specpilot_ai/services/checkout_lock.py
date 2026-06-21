import re
from datetime import UTC, datetime

from specpilot_ai.core.models import (
    CheckoutLockCheck,
    CheckoutLockRequest,
    CheckStatus,
    PublicCheckoutLockKit,
    PurchaseExecutionKitRequest,
)


def build_public_checkout_lock_kit(
    request: CheckoutLockRequest,
    generated_at: datetime | None = None,
) -> PublicCheckoutLockKit:
    generated_at = generated_at or datetime.now(UTC)
    title = _checkout_title(request)
    combined_text = " ".join(
        [
            title,
            request.checkout_option_text.strip(),
            request.evidence_text.strip(),
        ]
    )
    checks = _checks(request, title, combined_text)
    blockers = sum(1 for check in checks if check.status == CheckStatus.blocker)
    warnings = sum(1 for check in checks if check.status == CheckStatus.warning)
    evidence_gaps = _evidence_gap_count(checks)
    price_delta = _price_delta(request)
    lock_score = _lock_score(
        blockers=blockers,
        warnings=warnings,
        evidence_gaps=evidence_gaps,
        price_delta=price_delta,
        locked_price=request.locked_candidate.locked_price_krw,
    )
    lock_status = _lock_status(blockers, warnings, lock_score)
    missing_evidence = _missing_evidence(checks)
    execution_prefill = _execution_prefill(
        request=request,
        title=title,
        lock_status=lock_status,
        blockers=blockers,
        warnings=warnings,
        missing_evidence=missing_evidence,
    )

    return PublicCheckoutLockKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        product_title=title,
        candidate_id=request.locked_candidate.candidate_id,
        lock_status=lock_status,
        lock_score=lock_score,
        price_delta_krw=price_delta,
        mismatch_count=blockers + warnings,
        evidence_gap_count=evidence_gaps,
        headline=_headline(title, lock_status),
        summary=_summary(request, lock_status, lock_score, blockers, warnings, price_delta),
        checks=checks,
        locked_fields=_locked_fields(request),
        seller_questions=_seller_questions(request, checks),
        capture_checklist=_capture_checklist(lock_status, missing_evidence),
        stop_conditions=_stop_conditions(request, checks, lock_status),
        execution_prefill=execution_prefill,
        analysis_prefill=_analysis_prefill(request, lock_status, checks),
        share_copy=_share_copy(request, title, lock_status, lock_score, price_delta),
        next_actions=_next_actions(lock_status, title),
    )


def _checkout_title(request: CheckoutLockRequest) -> str:
    return request.checkout_title.strip() or request.locked_candidate.title.strip()


def _money(value: int | None) -> str:
    return f"{value:,}원" if value is not None else "미입력"


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", text.lower())


def _contains(haystack: str, needle: str) -> bool:
    normalized_haystack = _norm(haystack)
    normalized_needle = _norm(needle)
    return bool(normalized_needle) and normalized_needle in normalized_haystack


def _price_delta(request: CheckoutLockRequest) -> int | None:
    if request.checkout_total_krw is None:
        return None
    return request.checkout_total_krw - request.locked_candidate.locked_price_krw


def _check(
    *,
    check_id: str,
    label: str,
    status: CheckStatus,
    locked: str,
    observed: str,
    recommendation: str,
) -> CheckoutLockCheck:
    return CheckoutLockCheck(
        check_id=check_id,
        label=label,
        status=status,
        locked=locked,
        observed=observed,
        recommendation=recommendation,
    )


def _checks(
    request: CheckoutLockRequest,
    title: str,
    combined_text: str,
) -> list[CheckoutLockCheck]:
    locked = request.locked_candidate
    checks = [
        _title_check(request, title, combined_text),
        _seller_check(request),
        _quantity_check(request),
        _price_check(request),
    ]
    for check_id, label, expected in [
        ("cpu", "CPU", locked.cpu),
        ("gpu", "GPU", locked.gpu),
        ("os", "OS", locked.os_name),
    ]:
        if expected.strip():
            checks.append(
                _text_match_check(
                    check_id=check_id,
                    label=label,
                    expected=expected,
                    combined_text=combined_text,
                )
            )
    for check_id, label, expected, unit in [
        ("ram", "RAM", locked.ram_gb, "GB"),
        ("storage", "저장장치", locked.storage_gb, "GB"),
    ]:
        if expected is not None:
            checks.append(
                _capacity_check(
                    check_id=check_id,
                    label=label,
                    expected=expected,
                    unit=unit,
                    combined_text=combined_text,
                )
            )
    checks.extend(_evidence_checks(request, combined_text))
    return checks


def _title_check(
    request: CheckoutLockRequest,
    title: str,
    combined_text: str,
) -> CheckoutLockCheck:
    locked_title = request.locked_candidate.title.strip()
    if _contains(combined_text, locked_title) or _title_overlap_score(locked_title, combined_text) >= 0.45:
        return _check(
            check_id="title",
            label="상품명 잠금",
            status=CheckStatus.ok,
            locked=locked_title,
            observed=title,
            recommendation="후보 비교에서 고른 상품명과 결제 화면 상품명이 충분히 일치합니다.",
        )
    return _check(
        check_id="title",
        label="상품명 잠금",
        status=CheckStatus.blocker,
        locked=locked_title,
        observed=title or "결제 화면 상품명 없음",
        recommendation="후보 비교 결과와 다른 상품일 수 있으니 결제하지 말고 상품명/옵션명을 다시 확인하세요.",
    )


def _title_overlap_score(locked_title: str, observed: str) -> float:
    locked_tokens = {
        token
        for token in re.split(r"[^0-9a-zA-Z가-힣]+", locked_title.lower())
        if len(token) >= 3
    }
    if not locked_tokens:
        return 0
    observed_norm = _norm(observed)
    matched = sum(1 for token in locked_tokens if _norm(token) in observed_norm)
    return matched / len(locked_tokens)


def _seller_check(request: CheckoutLockRequest) -> CheckoutLockCheck:
    locked_seller = request.locked_candidate.seller_name.strip()
    observed = request.checkout_seller_name.strip()
    if not locked_seller:
        return _check(
            check_id="seller",
            label="판매자 잠금",
            status=CheckStatus.warning,
            locked="후보 비교 시 판매자 미입력",
            observed=observed or "결제 화면 판매자 없음",
            recommendation="판매자명이 빠져 있으면 AS/반품 조건을 비교하기 어렵습니다.",
        )
    if not observed:
        return _check(
            check_id="seller",
            label="판매자 잠금",
            status=CheckStatus.warning,
            locked=locked_seller,
            observed="결제 화면 판매자 없음",
            recommendation="최종 결제 화면의 판매자명을 캡처하세요.",
        )
    if _contains(observed, locked_seller) or _contains(locked_seller, observed):
        return _check(
            check_id="seller",
            label="판매자 잠금",
            status=CheckStatus.ok,
            locked=locked_seller,
            observed=observed,
            recommendation="후보 비교 때의 판매자와 결제 화면 판매자가 일치합니다.",
        )
    return _check(
        check_id="seller",
        label="판매자 잠금",
        status=CheckStatus.warning,
        locked=locked_seller,
        observed=observed,
        recommendation="판매자가 바뀌면 배송, 반품, AS 조건도 달라질 수 있어 답변을 다시 받아야 합니다.",
    )


def _quantity_check(request: CheckoutLockRequest) -> CheckoutLockCheck:
    if request.checkout_quantity == 1:
        return _check(
            check_id="quantity",
            label="수량 잠금",
            status=CheckStatus.ok,
            locked="1개",
            observed="1개",
            recommendation="수량이 1개로 유지되어 예산 비교가 가능합니다.",
        )
    return _check(
        check_id="quantity",
        label="수량 잠금",
        status=CheckStatus.blocker,
        locked="1개",
        observed=f"{request.checkout_quantity}개",
        recommendation="수량이 바뀌면 총액과 승인 기준이 달라지므로 다시 후보 비교부터 진행하세요.",
    )


def _price_check(request: CheckoutLockRequest) -> CheckoutLockCheck:
    locked_price = request.locked_candidate.locked_price_krw
    total = request.checkout_total_krw
    if total is None:
        return _check(
            check_id="price",
            label="최종가 잠금",
            status=CheckStatus.warning,
            locked=_money(locked_price),
            observed="최종 결제 금액 없음",
            recommendation="배송비, 쿠폰, 카드 할인 반영 후 최종 결제 금액을 입력하세요.",
        )
    delta = total - locked_price
    if total > request.budget_krw:
        return _check(
            check_id="price",
            label="최종가 잠금",
            status=CheckStatus.blocker,
            locked=_money(locked_price),
            observed=f"{_money(total)} · 예산 대비 {total - request.budget_krw:+,}원",
            recommendation="예산을 넘었으므로 결제하지 말고 승인 또는 대체 후보 비교가 먼저입니다.",
        )
    if delta > max(70_000, int(locked_price * 0.035)):
        return _check(
            check_id="price",
            label="최종가 잠금",
            status=CheckStatus.warning,
            locked=_money(locked_price),
            observed=f"{_money(total)} · 잠금가 대비 {delta:+,}원",
            recommendation="후보 비교 때보다 가격이 올랐습니다. 쿠폰/배송비/카드 조건을 다시 캡처하세요.",
        )
    return _check(
        check_id="price",
        label="최종가 잠금",
        status=CheckStatus.ok,
        locked=_money(locked_price),
        observed=f"{_money(total)} · 잠금가 대비 {delta:+,}원",
        recommendation="잠금가와 예산 안에 있습니다. 결제 화면 총액 캡처만 남기세요.",
    )


def _text_match_check(
    *,
    check_id: str,
    label: str,
    expected: str,
    combined_text: str,
) -> CheckoutLockCheck:
    if _contains(combined_text, expected):
        return _check(
            check_id=check_id,
            label=f"{label} 잠금",
            status=CheckStatus.ok,
            locked=expected,
            observed=expected,
            recommendation=f"{label}이 후보 비교 기준과 일치합니다.",
        )
    return _check(
        check_id=check_id,
        label=f"{label} 잠금",
        status=CheckStatus.blocker,
        locked=expected,
        observed="결제 화면 문구에서 확인 안 됨",
        recommendation=f"{label} 옵션이 다르거나 빠졌을 수 있으니 결제하지 말고 옵션명을 다시 캡처하세요.",
    )


def _capacity_check(
    *,
    check_id: str,
    label: str,
    expected: int,
    unit: str,
    combined_text: str,
) -> CheckoutLockCheck:
    patterns = [
        rf"{expected}\s*{unit}",
        rf"{expected // 1024}\s*TB" if expected >= 1024 and expected % 1024 == 0 else "",
        rf"{round(expected / 1000)}\s*TB" if unit == "GB" and expected >= 900 else "",
    ]
    if any(pattern and re.search(pattern, combined_text, re.IGNORECASE) for pattern in patterns):
        return _check(
            check_id=check_id,
            label=f"{label} 잠금",
            status=CheckStatus.ok,
            locked=f"{expected}{unit}",
            observed=f"{expected}{unit}",
            recommendation=f"{label} 용량이 후보 비교 기준과 일치합니다.",
        )
    return _check(
        check_id=check_id,
        label=f"{label} 잠금",
        status=CheckStatus.blocker,
        locked=f"{expected}{unit}",
        observed="결제 화면 문구에서 확인 안 됨",
        recommendation=f"{label} 용량이 빠지거나 달라질 수 있어 옵션명을 다시 확인하세요.",
    )


def _evidence_checks(request: CheckoutLockRequest, combined_text: str) -> list[CheckoutLockCheck]:
    checks: list[CheckoutLockCheck] = []
    locked = request.locked_candidate
    if locked.warranty_months is not None and locked.warranty_months > 0:
        checks.append(
            _keyword_evidence_check(
                check_id="warranty",
                label="AS/보증 증거",
                locked=f"{locked.warranty_months}개월",
                combined_text=combined_text,
                keywords=["as", "a/s", "보증", "무상", "서비스"],
                recommendation="AS 기간과 주체가 보이는 결제 화면 또는 판매자 답변을 캡처하세요.",
            )
        )
    if locked.return_window_days is not None and locked.return_window_days > 0:
        checks.append(
            _keyword_evidence_check(
                check_id="return",
                label="반품/교환 증거",
                locked=f"{locked.return_window_days}일",
                combined_text=combined_text,
                keywords=["반품", "교환", "초기불량", "취소"],
                recommendation="반품/교환 기간과 개봉 후 예외 조건을 캡처하세요.",
            )
        )
    checks.append(
        _keyword_evidence_check(
            check_id="delivery_stock",
            label="배송/재고 증거",
            locked="결제 전 재고와 배송일 확인",
            combined_text=combined_text,
            keywords=["재고", "배송", "출고", "도착", "예약"],
            recommendation="재고, 배송 예정일, 출고 지연 조건을 결제 전 캡처하세요.",
        )
    )
    return checks


def _keyword_evidence_check(
    *,
    check_id: str,
    label: str,
    locked: str,
    combined_text: str,
    keywords: list[str],
    recommendation: str,
) -> CheckoutLockCheck:
    if any(keyword in combined_text.lower() for keyword in keywords):
        return _check(
            check_id=check_id,
            label=label,
            status=CheckStatus.ok,
            locked=locked,
            observed="증거 문구 있음",
            recommendation="증거 문구를 캡처해 구매 후 분쟁 대비 자료로 보관하세요.",
        )
    return _check(
        check_id=check_id,
        label=label,
        status=CheckStatus.warning,
        locked=locked,
        observed="증거 문구 없음",
        recommendation=recommendation,
    )


def _evidence_gap_count(checks: list[CheckoutLockCheck]) -> int:
    evidence_ids = {"warranty", "return", "delivery_stock"}
    return sum(
        1
        for check in checks
        if check.check_id in evidence_ids and check.status != CheckStatus.ok
    )


def _lock_score(
    *,
    blockers: int,
    warnings: int,
    evidence_gaps: int,
    price_delta: int | None,
    locked_price: int,
) -> int:
    score = 100 - blockers * 24 - warnings * 8 - evidence_gaps * 4
    if price_delta is None:
        score -= 6
    elif price_delta > 0:
        score -= min(14, int(price_delta / max(1, locked_price) * 100))
    return max(0, min(100, score))


def _lock_status(blockers: int, warnings: int, lock_score: int) -> str:
    if blockers:
        return "blocked"
    if warnings or lock_score < 88:
        return "verify"
    return "locked"


def _missing_evidence(checks: list[CheckoutLockCheck]) -> list[str]:
    return [
        check.label
        for check in checks
        if check.status != CheckStatus.ok
        and check.check_id in {"price", "seller", "warranty", "return", "delivery_stock"}
    ][:8]


def _locked_fields(request: CheckoutLockRequest) -> list[str]:
    locked = request.locked_candidate
    fields = [
        f"상품명: {locked.title}",
        f"잠금가: {_money(locked.locked_price_krw)}",
    ]
    if locked.seller_name:
        fields.append(f"판매자: {locked.seller_name}")
    if locked.cpu:
        fields.append(f"CPU: {locked.cpu}")
    if locked.gpu:
        fields.append(f"GPU: {locked.gpu}")
    if locked.ram_gb is not None:
        fields.append(f"RAM: {locked.ram_gb}GB")
    if locked.storage_gb is not None:
        fields.append(f"저장장치: {locked.storage_gb}GB")
    if locked.os_name:
        fields.append(f"OS: {locked.os_name}")
    return fields


def _seller_questions(
    request: CheckoutLockRequest,
    checks: list[CheckoutLockCheck],
) -> list[str]:
    questions = [
        "결제 화면의 상품명과 옵션명 그대로 출고되는 사양이 맞나요?",
        "최종 결제 금액에 배송비, 쿠폰, 카드 할인, 조립비, OS 비용이 모두 반영됐나요?",
        "AS 주체, 무상 보증 기간, 초기 불량 교환 기준을 결제 후에도 동일하게 적용하나요?",
    ]
    if any(check.check_id == "seller" and check.status != CheckStatus.ok for check in checks):
        questions.insert(0, "후보 비교 때의 판매자와 현재 결제 화면 판매자가 같은 판매자인가요?")
    if request.checkout_total_krw is None:
        questions.insert(0, "현재 화면에서 실제 결제될 최종 총액은 얼마인가요?")
    return questions[:5]


def _capture_checklist(lock_status: str, missing_evidence: list[str]) -> list[str]:
    checklist = [
        "최종 결제 금액, 배송비, 쿠폰/카드 할인 적용 화면",
        "상품명, 옵션명, CPU/GPU/RAM/SSD/OS 선택 상태",
        "판매자명, 배송 예정일, 재고/출고 조건",
        "AS/보증 주체, 반품/교환 기간, 초기 불량 예외",
    ]
    if missing_evidence:
        checklist.append(f"누락 증거: {', '.join(missing_evidence)}")
    if lock_status == "blocked":
        checklist.append("차단 항목을 수정한 뒤 같은 요청으로 다시 잠금 검수")
    return checklist


def _stop_conditions(
    request: CheckoutLockRequest,
    checks: list[CheckoutLockCheck],
    lock_status: str,
) -> list[str]:
    conditions = [
        "상품명 또는 옵션명이 후보 비교 기준과 다르면 결제하지 않습니다.",
        "최종 결제 금액이 예산을 넘으면 결제하지 않습니다.",
        "수량, 판매자, AS/반품 조건이 바뀌면 판매자 답변 없이 결제하지 않습니다.",
    ]
    if lock_status == "verify":
        conditions.append("warning 증거가 캡처되지 않으면 구매 실행 패키지로 넘기지 않습니다.")
    if request.checkout_total_krw is not None and request.checkout_total_krw < request.budget_krw:
        conditions.append("가격이 내려갔더라도 사양과 보증 조건이 같을 때만 결제합니다.")
    failed = [check.label for check in checks if check.status == CheckStatus.blocker]
    if failed:
        conditions.insert(0, f"현재 차단 항목: {', '.join(failed[:4])}")
    return conditions[:6]


def _execution_prefill(
    *,
    request: CheckoutLockRequest,
    title: str,
    lock_status: str,
    blockers: int,
    warnings: int,
    missing_evidence: list[str],
) -> PurchaseExecutionKitRequest:
    verdict = "ready" if lock_status == "locked" else "hold" if lock_status == "blocked" else "verify"
    return PurchaseExecutionKitRequest(
        category=request.category,
        product_title=title,
        seller_name=request.checkout_seller_name
        or request.locked_candidate.seller_name
        or "판매자",
        verdict=verdict,
        final_price_krw=request.checkout_total_krw,
        budget_krw=request.budget_krw,
        blocker_count=blockers,
        warning_count=warnings,
        missing_evidence=missing_evidence,
        seller_questions=_seller_questions(request, []),
        evidence_ready=[
            "상품명/옵션명",
            "최종 결제 금액",
            "판매자명",
        ],
        decision_deadline="결제 버튼 클릭 전",
        payment_method=request.payment_method,
        share_audience="self",
        source="checkout_lock",
    )


def _headline(title: str, lock_status: str) -> str:
    if lock_status == "blocked":
        return f"{title} 결제 화면이 후보 비교 기준과 달라 결제를 멈춰야 합니다."
    if lock_status == "verify":
        return f"{title}는 잠금 기준과 대체로 맞지만 증거 확인이 남았습니다."
    return f"{title}는 후보 비교 기준과 결제 화면이 잠겼습니다."


def _summary(
    request: CheckoutLockRequest,
    lock_status: str,
    score: int,
    blockers: int,
    warnings: int,
    price_delta: int | None,
) -> str:
    delta_text = "최종가 미입력" if price_delta is None else f"잠금가 대비 {price_delta:+,}원"
    if lock_status == "blocked":
        return (
            f"잠금 점수 {score}점, blocker {blockers}개, warning {warnings}개, {delta_text}. "
            "결제 버튼을 누르기 전에 상품명, 옵션, 예산 초과 항목을 다시 닫아야 합니다."
        )
    if lock_status == "verify":
        return (
            f"잠금 점수 {score}점, blocker {blockers}개, warning {warnings}개, {delta_text}. "
            "사양은 유지됐더라도 판매자/배송/AS 증거를 캡처해야 구매 실행으로 넘어갈 수 있습니다."
        )
    return (
        f"잠금 점수 {score}점, {delta_text}. "
        "후보 비교 기준과 결제 화면 조건이 일치하므로 캡처 후 구매 실행 패키지로 넘길 수 있습니다."
    )


def _analysis_prefill(
    request: CheckoutLockRequest,
    lock_status: str,
    checks: list[CheckoutLockCheck],
) -> str:
    failed = "; ".join(
        f"{check.label}: {check.status} ({check.observed})"
        for check in checks
        if check.status != CheckStatus.ok
    )
    return (
        f"{request.locked_candidate.title} 결제 화면 잠금 검수 결과 lock_status={lock_status}. "
        f"예산 {request.budget_krw:,}원, 잠금가 {request.locked_candidate.locked_price_krw:,}원, "
        f"최종가 {_money(request.checkout_total_krw)}. "
        f"남은 이슈: {failed or '없음'}. 지금 결제해도 되는지 최종 판단해줘."
    )


def _share_copy(
    request: CheckoutLockRequest,
    title: str,
    lock_status: str,
    score: int,
    price_delta: int | None,
) -> str:
    delta_text = "최종가 미입력" if price_delta is None else f"잠금가 대비 {price_delta:+,}원"
    return (
        "SpecPilot AI 체크아웃 잠금 검수\n"
        f"- 후보: {title}\n"
        f"- 상태: {lock_status} · {score}점\n"
        f"- 예산: {request.budget_krw:,}원\n"
        f"- {delta_text}\n"
        "상품명, 옵션명, 판매자, 최종 결제 금액, AS/반품 조건이 같은지 검토 부탁드립니다."
    )


def _next_actions(lock_status: str, title: str) -> list[str]:
    if lock_status == "blocked":
        return [
            "결제하지 말고 차단 항목을 수정하거나 커스텀 후보 비교로 대체 후보를 다시 고르세요.",
            "판매자에게 실제 출고 사양과 최종 결제 금액을 확인받은 뒤 다시 잠금 검수하세요.",
            "예산 초과 또는 사양 불일치가 남으면 대체 후보 rescue로 넘기세요.",
        ]
    if lock_status == "verify":
        return [
            f"{title}의 최종가, 옵션명, 판매자, AS/반품 증거를 캡처하세요.",
            "warning이 사라지면 구매 실행 패키지로 결제 순서와 중단 조건을 고정하세요.",
            "판매자 답변이 늦으면 가격 타이밍/목표가 감시로 전환하세요.",
        ]
    return [
        "결제 화면 캡처를 저장하고 구매 실행 패키지로 마지막 순서를 확인하세요.",
        "구매 후 케어 키트로 반품/보증 마감일과 초기 불량 체크를 예약하세요.",
        "구매 결과를 기록해 다음 추천 품질 학습에 반영하세요.",
    ]
