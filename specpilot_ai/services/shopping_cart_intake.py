import re
from collections import Counter
from datetime import UTC, datetime

from specpilot_ai.core.models import (
    Category,
    CheckStatus,
    PublicShoppingCartIntakeKit,
    PurchaseApprovalBriefRequest,
    ShoppingCartIntakeRequest,
    ShoppingCartItemInput,
    ShoppingCartLine,
    SpecRiskScannerRequest,
)


def build_public_shopping_cart_intake_kit(
    request: ShoppingCartIntakeRequest,
    generated_at: datetime | None = None,
) -> PublicShoppingCartIntakeKit:
    generated_at = generated_at or datetime.now(UTC)
    items = _items_from_request(request)
    lines = [_line_from_item(index, item) for index, item in enumerate(items, start=1)]
    detected_slots = sorted({line.normalized_role for line in lines if line.normalized_role != "unknown"})
    missing_slots = _missing_slots(request.category, detected_slots, _cart_blob(items))
    duplicate_warnings = _duplicate_warnings(lines)
    cart_total = _cart_total(items)
    blocker_count = _blocker_count(request, cart_total, lines, missing_slots)
    warning_count = _warning_count(lines, missing_slots, duplicate_warnings)
    readiness_score = _readiness_score(blocker_count, warning_count)
    verdict = _verdict(blocker_count, warning_count)
    scanner_prefill = _scanner_prefill(request, items, cart_total)
    approval_prefill = _approval_prefill(
        request=request,
        cart_total=cart_total,
        verdict=verdict,
        blocker_count=blocker_count,
        warning_count=warning_count,
        missing_slots=missing_slots,
        duplicate_warnings=duplicate_warnings,
    )
    return PublicShoppingCartIntakeKit(
        generated_at=generated_at.isoformat(),
        category=request.category,
        item_count=sum(item.quantity for item in items),
        cart_total_krw=cart_total,
        budget_delta_krw=(cart_total - request.budget_krw) if cart_total is not None else None,
        readiness_score=readiness_score,
        verdict=verdict,
        headline=_headline(request, verdict, missing_slots),
        summary=_summary(request, cart_total, blocker_count, warning_count),
        blocker_count=blocker_count,
        warning_count=warning_count,
        lines=lines,
        detected_slots=detected_slots,
        missing_slots=missing_slots,
        duplicate_warnings=duplicate_warnings,
        seller_questions=_seller_questions(request, missing_slots, lines),
        scanner_prefill=scanner_prefill,
        approval_prefill=approval_prefill,
        analysis_prefill=_analysis_prefill(request, items, cart_total, missing_slots, verdict),
        share_copy=_share_copy(request, cart_total, verdict, missing_slots),
        next_actions=_next_actions(verdict, missing_slots, duplicate_warnings),
    )


def _items_from_request(request: ShoppingCartIntakeRequest) -> list[ShoppingCartItemInput]:
    if request.items:
        return request.items[:20]
    parsed: list[ShoppingCartItemInput] = []
    for line in request.cart_text.splitlines():
        text = line.strip()
        if not text:
            continue
        price = _price_from_text(text)
        title = _strip_price(text)
        if title:
            parsed.append(ShoppingCartItemInput(title=title[:180], price_krw=price))
    if parsed:
        return parsed[:20]
    fallback = request.cart_text.strip() or "장바구니 텍스트 미입력"
    return [ShoppingCartItemInput(title=fallback[:180])]


def _price_from_text(text: str) -> int | None:
    candidates = re.findall(r"([0-9][0-9,]{3,})\s*원?", text)
    if not candidates:
        return None
    values = [int(candidate.replace(",", "")) for candidate in candidates]
    return max(values) if values else None


def _strip_price(text: str) -> str:
    stripped = re.sub(r"[0-9][0-9,]{3,}\s*원?", "", text)
    stripped = re.sub(r"\s{2,}", " ", stripped)
    return stripped.strip(" -·|")


def _line_from_item(index: int, item: ShoppingCartItemInput) -> ShoppingCartLine:
    blob = f"{item.title} {item.option_text}".strip()
    role = _role(blob)
    status = _line_status(item, blob, role)
    return ShoppingCartLine(
        line_id=f"cart_line_{index}",
        title=item.title.strip() or f"장바구니 항목 {index}",
        normalized_role=role,
        quantity=item.quantity,
        price_krw=item.price_krw,
        status=status,
        evidence=_line_evidence(item, role),
        recommendation=_line_recommendation(item, blob, role, status),
    )


def _role(text: str) -> str:
    lowered = text.lower()
    patterns = [
        ("laptop", ("노트북", "laptop", "notebook", "그램", "맥북")),
        ("desktop_build", ("조립pc", "조립 pc", "데스크탑", "데스크톱", "본체", "완본체")),
        ("cpu", ("ryzen", "라이젠", "core i", "인텔", "cpu", "7800x3d", "14700", "ultra")),
        ("gpu", ("rtx", "radeon", "geforce", "그래픽", "gpu", "4070", "4060", "4080")),
        ("ram", ("ram", "ddr", "메모리", "32gb", "16gb")),
        ("storage", ("ssd", "nvme", "저장", "1tb", "2tb", "512gb")),
        ("motherboard", ("메인보드", "b650", "b760", "x670", "z790")),
        ("psu", ("파워", "psu", "750w", "850w", "600w")),
        ("case", ("케이스", "case", "tower", "타워")),
        ("cooler", ("쿨러", "cooler", "수랭", "공랭")),
        ("monitor", ("모니터", "qhd", "uhd", "fhd", "144hz", "165hz")),
        ("os", ("windows", "윈도우", "freedos", "free dos", "운영체제")),
    ]
    for role, needles in patterns:
        if any(needle in lowered for needle in needles):
            return role
    return "unknown"


def _line_status(item: ShoppingCartItemInput, text: str, role: str) -> CheckStatus:
    lowered = text.lower()
    risky_terms = ("리퍼", "전시", "중고", "해외", "병행", "freedos", "free dos", "미개봉")
    if any(term in lowered for term in risky_terms):
        return CheckStatus.warning
    if item.price_krw is None:
        return CheckStatus.warning
    if role == "unknown":
        return CheckStatus.warning
    return CheckStatus.ok


def _line_evidence(item: ShoppingCartItemInput, role: str) -> str:
    price = f"{item.price_krw:,}원" if item.price_krw is not None else "가격 미입력"
    seller = item.seller.strip() or "판매자 미입력"
    return f"{role} · {price} · 수량 {item.quantity} · {seller}"


def _line_recommendation(
    item: ShoppingCartItemInput,
    text: str,
    role: str,
    status: CheckStatus,
) -> str:
    lowered = text.lower()
    if status == CheckStatus.ok:
        return "역할과 가격이 확인됩니다. 최종 결제 화면에서 같은 항목인지 캡처하세요."
    if item.price_krw is None:
        return "가격을 함께 붙여 넣어 총액과 예산 초과 여부를 확인하세요."
    if role == "unknown":
        return "CPU/GPU/RAM/SSD/모니터/OS 중 어떤 항목인지 옵션명을 보강하세요."
    if any(term in lowered for term in ("리퍼", "전시", "중고", "해외", "병행")):
        return "리퍼·전시·중고·해외 조건은 반품과 AS 답변을 받은 뒤 승인하세요."
    if "freedos" in lowered or "free dos" in lowered:
        return "FreeDOS면 Windows 라이선스와 설치 비용을 총액에 더하세요."
    return "판매 페이지 모델명, 옵션명, 배송/반품 조건을 함께 캡처하세요."


def _cart_blob(items: list[ShoppingCartItemInput]) -> str:
    return " ".join(f"{item.title} {item.option_text}" for item in items)


def _missing_slots(category: Category, slots: list[str], blob: str) -> list[str]:
    slot_set = set(slots)
    if category == Category.laptop or "노트북" in blob.lower() or "laptop" in blob.lower():
        required = ["laptop", "ram", "storage", "os"]
    else:
        required = ["cpu", "gpu", "ram", "storage", "motherboard", "psu", "case"]
        if "windows" in blob.lower() or "윈도우" in blob.lower() or "freedos" in blob.lower():
            required.append("os")
    return [slot for slot in required if slot not in slot_set]


def _duplicate_warnings(lines: list[ShoppingCartLine]) -> list[str]:
    counts = Counter(line.normalized_role for line in lines if line.normalized_role != "unknown")
    return [f"{role} 항목이 {count}개입니다. 중복 구매인지 확인하세요." for role, count in counts.items() if count > 1]


def _cart_total(items: list[ShoppingCartItemInput]) -> int | None:
    priced = [item for item in items if item.price_krw is not None]
    if not priced:
        return None
    return sum((item.price_krw or 0) * item.quantity for item in priced)


def _blocker_count(
    request: ShoppingCartIntakeRequest,
    cart_total: int | None,
    lines: list[ShoppingCartLine],
    missing_slots: list[str],
) -> int:
    count = 0
    if cart_total is not None and cart_total > request.budget_krw:
        count += 1
    if request.category == Category.desktop_pc and {"cpu", "gpu"} & set(missing_slots):
        count += 1
    if not lines or all(line.status == CheckStatus.warning for line in lines):
        count += 1
    return count


def _warning_count(
    lines: list[ShoppingCartLine],
    missing_slots: list[str],
    duplicate_warnings: list[str],
) -> int:
    line_warnings = sum(1 for line in lines if line.status == CheckStatus.warning)
    return line_warnings + len(missing_slots) + len(duplicate_warnings)


def _readiness_score(blocker_count: int, warning_count: int) -> float:
    return max(0.0, min(100.0, 100 - blocker_count * 28 - warning_count * 7))


def _verdict(blocker_count: int, warning_count: int) -> str:
    if blocker_count:
        return "hold"
    if warning_count:
        return "verify"
    return "ready"


def _headline(
    request: ShoppingCartIntakeRequest,
    verdict: str,
    missing_slots: list[str],
) -> str:
    label = "노트북" if request.category == Category.laptop else "컴퓨터 세팅"
    if verdict == "hold":
        return f"{label} 장바구니는 결제 전 핵심 누락을 먼저 닫아야 합니다."
    if missing_slots:
        return f"{label} 장바구니는 {len(missing_slots)}개 항목 확인 후 승인하세요."
    return f"{label} 장바구니를 바로 검수/승인 흐름으로 넘길 수 있습니다."


def _summary(
    request: ShoppingCartIntakeRequest,
    cart_total: int | None,
    blocker_count: int,
    warning_count: int,
) -> str:
    total = f"{cart_total:,}원" if cart_total is not None else "총액 미입력"
    return (
        f"예산 {request.budget_krw:,}원, 장바구니 {total} 기준 "
        f"blocker {blocker_count}개, warning {warning_count}개를 찾았습니다. "
        "붙여 넣은 항목을 옵션/사양 검수와 구매 승인 브리프로 바로 넘길 수 있습니다."
    )


def _scanner_prefill(
    request: ShoppingCartIntakeRequest,
    items: list[ShoppingCartItemInput],
    cart_total: int | None,
) -> SpecRiskScannerRequest:
    text = "\n".join(_item_text(item) for item in items)
    return SpecRiskScannerRequest(
        category=request.category,
        product_title=_product_title(request),
        option_text=text,
        cart_total_krw=cart_total,
        budget_krw=request.budget_krw,
        expected_cpu=_first_match(text, r"(Ryzen\s?[0-9][A-Za-z0-9\s]*|Core\s?i[3579][A-Za-z0-9\s-]*)"),
        expected_gpu=_first_match(text, r"(RTX\s?[0-9]{4}\s?(?:SUPER|Ti)?|RX\s?[0-9]{4})"),
        expected_ram_gb=_capacity(text, "ram"),
        expected_storage_gb=_capacity(text, "storage"),
        expected_os="Windows 11" if re.search(r"windows\s?11|윈도우\s?11", text, re.I) else "",
        evidence_text="장바구니 항목과 가격은 인테이크에서 확인, 배송/반품/AS는 추가 캡처 필요",
        source="shopping_cart_intake",
    )


def _approval_prefill(
    request: ShoppingCartIntakeRequest,
    cart_total: int | None,
    verdict: str,
    blocker_count: int,
    warning_count: int,
    missing_slots: list[str],
    duplicate_warnings: list[str],
) -> PurchaseApprovalBriefRequest:
    reasons = [
        f"장바구니 총액 {cart_total:,}원" if cart_total is not None else "장바구니 총액 미입력",
        f"누락 슬롯 {len(missing_slots)}개",
    ]
    if duplicate_warnings:
        reasons.append("중복 항목 확인 필요")
    return PurchaseApprovalBriefRequest(
        category=request.category,
        product_title=_product_title(request),
        verdict=verdict,
        budget_krw=request.budget_krw,
        cart_total_krw=cart_total,
        blocker_count=blocker_count,
        warning_count=warning_count,
        key_reasons=reasons,
        missing_evidence=_missing_evidence(missing_slots),
        audience="family",
        decision_deadline="결제 전",
        source="shopping_cart_intake",
    )


def _item_text(item: ShoppingCartItemInput) -> str:
    price = f"{item.price_krw:,}원" if item.price_krw is not None else "가격 미입력"
    return f"{item.title} {item.option_text} {price}".strip()


def _product_title(request: ShoppingCartIntakeRequest) -> str:
    return "노트북 장바구니" if request.category == Category.laptop else "컴퓨터 세팅 장바구니"


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.I)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def _capacity(text: str, kind: str) -> int | None:
    if kind == "ram":
        match = re.search(r"(?:ram|메모리|ddr[45]?)\D{0,12}([0-9]{1,3})\s*gb", text, re.I)
    else:
        match = re.search(r"(?:ssd|nvme|저장장치?)\D{0,12}([0-9](?:\.[0-9])?)\s*tb", text, re.I)
        if match:
            return int(float(match.group(1)) * 1000)
        match = re.search(r"(?:ssd|nvme|저장장치?)\D{0,12}([0-9]{3,5})\s*gb", text, re.I)
    if match:
        return int(float(match.group(1)))
    return None


def _missing_evidence(missing_slots: list[str]) -> list[str]:
    evidence = [f"{slot} 옵션명" for slot in missing_slots[:5]]
    evidence.extend(["배송 예정일", "반품 조건", "AS 조건"])
    return evidence[:7]


def _seller_questions(
    request: ShoppingCartIntakeRequest,
    missing_slots: list[str],
    lines: list[ShoppingCartLine],
) -> list[str]:
    questions = [
        "최종 출고 사양이 장바구니 옵션명과 동일한가요?",
        "배송 예정일, 반품 가능 기간, 제조사/판매자 AS 기준을 알려주세요.",
    ]
    if missing_slots:
        questions.insert(0, f"누락된 항목을 실제 출고 사양으로 확인해주세요: {', '.join(missing_slots)}")
    if any(line.status == CheckStatus.warning for line in lines):
        questions.append("리퍼/전시/해외/FreeDOS 조건이 있다면 추가 비용과 보증 예외를 알려주세요.")
    if request.category == Category.desktop_pc:
        questions.append("파워 용량, 케이스 호환, BIOS 업데이트 여부를 확인해주세요.")
    return questions[:5]


def _analysis_prefill(
    request: ShoppingCartIntakeRequest,
    items: list[ShoppingCartItemInput],
    cart_total: int | None,
    missing_slots: list[str],
    verdict: str,
) -> str:
    total = f"{cart_total:,}원" if cart_total is not None else "총액 미입력"
    item_lines = " / ".join(item.title for item in items[:8])
    return (
        f"{_product_title(request)}를 분석해줘. 예산 {request.budget_krw:,}원, "
        f"장바구니 총액 {total}, 판정 {verdict}. 항목: {item_lines}. "
        f"누락 슬롯: {', '.join(missing_slots) if missing_slots else '없음'}. "
        f"목적: {request.purpose}."
    )


def _share_copy(
    request: ShoppingCartIntakeRequest,
    cart_total: int | None,
    verdict: str,
    missing_slots: list[str],
) -> str:
    total = f"{cart_total:,}원" if cart_total is not None else "총액 미입력"
    return (
        "SpecPilot AI 장바구니 인테이크\n"
        f"카테고리: {_product_title(request)}\n"
        f"총액/예산: {total} / {request.budget_krw:,}원\n"
        f"판정: {verdict}\n"
        f"누락 확인: {', '.join(missing_slots) if missing_slots else '없음'}"
    )


def _next_actions(
    verdict: str,
    missing_slots: list[str],
    duplicate_warnings: list[str],
) -> list[str]:
    if verdict == "hold":
        return [
            "예산 초과나 CPU/GPU 핵심 누락을 먼저 닫기 전에는 결제하지 마세요.",
            "장바구니 텍스트를 옵션/사양 빠른 검수로 넘겨 blocker를 줄이세요.",
            "대체 후보 rescue로 같은 예산의 다른 구성을 비교하세요.",
        ]
    actions = [
        "옵션/사양 빠른 검수 prefill로 결제 전 증거를 보강하세요.",
        "구매 승인 브리프로 가족/팀/커뮤니티에 찬성/반대 질문을 공유하세요.",
    ]
    if missing_slots:
        actions.insert(0, f"누락 슬롯을 먼저 확인하세요: {', '.join(missing_slots[:4])}")
    if duplicate_warnings:
        actions.append("중복 항목이 실제 추가 구매인지 확인하고 총액을 다시 계산하세요.")
    return actions[:5]
