from datetime import UTC, datetime
from typing import TypedDict
from uuid import uuid4

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph

from specpilot_ai.core.models import (
    AgentStep,
    AnalyzeRequest,
    AnalyzeResponse,
    Category,
    ExcludedProduct,
    PriceSnapshot,
    ProductCandidate,
    PurchaseCriteria,
    PurchaseReport,
    Recommendation,
    ReviewInsight,
    ScoreCard,
)


class PurchaseState(TypedDict, total=False):
    request: AnalyzeRequest
    criteria: PurchaseCriteria
    search_plan: list[str]
    candidates: list[ProductCandidate]
    normalized_products: list[ProductCandidate]
    compatibility_notes: list[str]
    price_snapshots: list[PriceSnapshot]
    review_insights: list[ReviewInsight]
    scorecards: list[ScoreCard]
    citations: list[str]
    verification_flags: list[str]
    report: PurchaseReport
    steps: list[AgentStep]
    graph_trace_id: str


def _record(state: PurchaseState, step: AgentStep) -> None:
    state.setdefault("steps", []).append(step)


def intent_parser(state: PurchaseState) -> PurchaseState:
    _record(state, AgentStep.intent_parser)
    request = state["request"]
    state["criteria"] = PurchaseCriteria(
        category=request.category,
        budget_krw=request.budget_krw,
        purpose=request.purpose,
        must_haves=request.must_haves,
        exclusions=request.exclusions,
        purchase_timing=request.purchase_timing,
        channels=request.channels,
    )
    state["graph_trace_id"] = f"trace_{uuid4().hex[:12]}"
    return state


def clarifier(state: PurchaseState) -> PurchaseState:
    _record(state, AgentStep.clarifier)
    criteria = state["criteria"]
    flags = []
    if criteria.budget_krw is None:
        flags.append("예산이 없어 가격 점수는 기본 200만원 기준으로 계산했습니다.")
    if criteria.category == Category.desktop_pc and not criteria.must_haves:
        flags.append(
            "데스크톱 견적의 필수 부품/해상도 조건이 없어 "
            "범용 게이밍 기준을 적용했습니다."
        )
    state["verification_flags"] = flags
    return state


def query_planner(state: PurchaseState) -> PurchaseState:
    _record(state, AgentStep.query_planner)
    criteria = state["criteria"]
    channel_list = criteria.channels or ["price_compare", "open_market"]
    state["search_plan"] = [
        f"{criteria.category.value} {criteria.purpose}",
        "cpu gpu motherboard ram ssd psu case compatibility",
        *[f"{condition} {criteria.category.value}" for condition in criteria.must_haves],
        *[f"source:{channel}" for channel in channel_list],
    ]
    return state


def product_collector(state: PurchaseState) -> PurchaseState:
    _record(state, AgentStep.product_collector)
    criteria = state["criteria"]
    state["candidates"] = (
        _desktop_build_candidates(criteria)
        if criteria.category == Category.desktop_pc
        else _laptop_candidates(criteria)
    )
    return state


def deduplicator(state: PurchaseState) -> PurchaseState:
    _record(state, AgentStep.deduplicator)
    seen: set[str] = set()
    normalized: list[ProductCandidate] = []
    for candidate in state["candidates"]:
        if candidate.normalized_model in seen:
            continue
        normalized.append(candidate)
        seen.add(candidate.normalized_model)
    state["normalized_products"] = normalized
    return state


def compatibility_checker(state: PurchaseState) -> PurchaseState:
    _record(state, AgentStep.compatibility_checker)
    notes = []
    for product in state["normalized_products"]:
        if product.category == Category.desktop_pc:
            notes.append(
                f"{product.model_name}: {product.specs['cpu_socket']} CPU와 "
                f"{product.specs['motherboard_socket']} 보드 소켓 확인, "
                f"권장 파워 {product.specs['psu_watt']}W"
            )
        else:
            notes.append(
                f"{product.model_name}: RAM {product.specs['ram_gb']}GB, "
                f"무게 {product.specs['weight_kg']}kg, 외장 GPU 여부 확인"
            )
    state["compatibility_notes"] = notes
    return state


def price_tracker(state: PurchaseState) -> PurchaseState:
    _record(state, AgentStep.price_tracker)
    now = datetime.now(UTC).isoformat()
    prices = [1_920_000, 1_740_000, 2_180_000, 1_560_000, 2_390_000]
    sellers = ["Price Compare", "Open Market", "Official Store", "PC Builder", "Marketplace"]
    state["price_snapshots"] = [
        PriceSnapshot(
            product_id=product.id,
            seller=sellers[index],
            price_krw=prices[index],
            shipping_fee_krw=0 if index < 3 else 5000,
            coupon_krw=70000 if index in {0, 1} else 0,
            captured_at=now,
            url=product.source_url,
        )
        for index, product in enumerate(state["normalized_products"])
    ]
    return state


def review_analyzer(state: PurchaseState) -> PurchaseState:
    _record(state, AgentStep.review_analyzer)
    state["review_insights"] = [
        ReviewInsight(
            product_id=product.id,
            pros=_pros_for(product),
            cons=_cons_for(product),
            repeated_complaints=_complaints_for(product),
            risk_signals=_risk_signals_for(index),
            trust_score=max(0.58, 0.9 - index * 0.07),
        )
        for index, product in enumerate(state["normalized_products"])
    ]
    state["citations"] = [product.source_url for product in state["normalized_products"]]
    return state


def scoring_engine(state: PurchaseState) -> PurchaseState:
    _record(state, AgentStep.scoring_engine)
    prices = {price.product_id: price for price in state["price_snapshots"]}
    reviews = {review.product_id: review for review in state["review_insights"]}
    budget = state["criteria"].budget_krw or 2_000_000
    cards: list[ScoreCard] = []

    for product in state["normalized_products"]:
        price = prices[product.id]
        review = reviews[product.id]
        purpose_fit = _purpose_fit(product, state["criteria"])
        price_score = min(100, max(30, 100 - ((price.effective_price_krw - budget) / budget) * 100))
        review_score = review.trust_score * 100
        stability = 90 if price.seller in {"Price Compare", "Official Store"} else 78
        preference = 78 + min(12, len(state["criteria"].must_haves) * 3)
        compatibility = _compatibility_score(product)
        total = (
            purpose_fit * 0.35
            + price_score * 0.22
            + review_score * 0.15
            + stability * 0.1
            + preference * 0.08
            + compatibility * 0.1
        )
        cards.append(
            ScoreCard(
                product_id=product.id,
                purpose_fit=round(purpose_fit, 1),
                price_competitiveness=round(price_score, 1),
                review_trust=round(review_score, 1),
                purchase_stability=round(stability, 1),
                personal_preference=round(preference, 1),
                compatibility=round(compatibility, 1),
                total_score=round(total, 1),
                rationale=(
                    "목적 적합도, 가격, 리뷰 신뢰도, 구매 안정성, "
                    "호환성을 가중 평균했습니다."
                ),
            )
        )
    state["scorecards"] = cards
    return state


def verifier(state: PurchaseState) -> PurchaseState:
    _record(state, AgentStep.verifier)
    flags = state.get("verification_flags", [])
    if len(state["citations"]) < len(state["normalized_products"]):
        flags.append("일부 후보의 출처 링크가 부족합니다.")
    if not state.get("compatibility_notes"):
        flags.append("호환성 검증 결과가 없습니다.")
    state["verification_flags"] = flags or [
        "데모 데이터 기준 가격/출처/호환성 검증을 통과했습니다."
    ]
    return state


def report_writer(state: PurchaseState) -> PurchaseState:
    _record(state, AgentStep.report_writer)
    products = {product.id: product for product in state["normalized_products"]}
    prices = {price.product_id: price for price in state["price_snapshots"]}
    reviews = {review.product_id: review for review in state["review_insights"]}
    ranked = sorted(state["scorecards"], key=lambda card: card.total_score, reverse=True)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "Write concise Korean PC purchase recommendations."),
            ("human", "Purpose: {purpose}\nCategory: {category}\nTop option: {top_product}"),
        ]
    )
    writer = RunnableLambda(
        lambda _: (
            f"{state['criteria'].purpose} 목적에는 예산, 부품 호환성, 성능 병목, "
            "업그레이드 여지를 함께 본 TOP 3 비교가 적합합니다."
        )
    )
    summary_chain = prompt | writer

    recommendations = [
        Recommendation(
            rank=index + 1,
            product=products[card.product_id],
            price=prices[card.product_id],
            review=reviews[card.product_id],
            score=card,
            fit_summary=_fit_summary(products[card.product_id], card),
            before_buy_checklist=[
                "CPU 소켓, 메인보드 칩셋, RAM 규격, 파워 용량을 확인하세요.",
                "모니터 해상도와 주사율 기준으로 GPU가 과하거나 부족하지 않은지 확인하세요.",
                "최종 결제 화면의 배송비, 조립비, 윈도우 포함 여부를 다시 확인하세요.",
            ],
        )
        for index, card in enumerate(ranked[:3])
    ]
    excluded = [
        ExcludedProduct(
            product=products[card.product_id],
            reason="예산 대비 성능, 호환성 또는 업그레이드 여지가 TOP 3보다 낮습니다.",
        )
        for card in ranked[3:5]
    ]
    state["report"] = PurchaseReport(
        summary=summary_chain.invoke(
            {
                "purpose": state["criteria"].purpose,
                "category": state["criteria"].category.value,
                "top_product": recommendations[0].product.model_name,
            }
        ),
        top_recommendations=recommendations,
        excluded_products=excluded,
        purchase_timing=(
            "부품 가격 합계가 목표 예산보다 3-5% 낮아질 때 구매, "
            "급하지 않으면 7일 단위 재조회"
        ),
        compatibility_notes=state["compatibility_notes"],
        citations=state["citations"],
        verification_flags=state["verification_flags"],
    )
    return state


def build_graph():
    workflow = StateGraph(PurchaseState)
    for step, fn in [
        (AgentStep.intent_parser, intent_parser),
        (AgentStep.clarifier, clarifier),
        (AgentStep.query_planner, query_planner),
        (AgentStep.product_collector, product_collector),
        (AgentStep.deduplicator, deduplicator),
        (AgentStep.compatibility_checker, compatibility_checker),
        (AgentStep.price_tracker, price_tracker),
        (AgentStep.review_analyzer, review_analyzer),
        (AgentStep.scoring_engine, scoring_engine),
        (AgentStep.verifier, verifier),
        (AgentStep.report_writer, report_writer),
    ]:
        workflow.add_node(step.value, fn)

    workflow.set_entry_point(AgentStep.intent_parser.value)
    ordered = [
        AgentStep.intent_parser,
        AgentStep.clarifier,
        AgentStep.query_planner,
        AgentStep.product_collector,
        AgentStep.deduplicator,
        AgentStep.compatibility_checker,
        AgentStep.price_tracker,
        AgentStep.review_analyzer,
        AgentStep.scoring_engine,
        AgentStep.verifier,
        AgentStep.report_writer,
    ]
    for before, after in zip(ordered, ordered[1:], strict=False):
        workflow.add_edge(before.value, after.value)
    workflow.add_edge(AgentStep.report_writer.value, END)
    return workflow.compile()


def run_analysis(request: AnalyzeRequest) -> AnalyzeResponse:
    state = build_graph().invoke({"request": request})
    return AnalyzeResponse(
        criteria=state["criteria"],
        steps=state["steps"],
        report=state["report"],
        graph_trace_id=state["graph_trace_id"],
    )


def _desktop_build_candidates(category: PurchaseCriteria) -> list[ProductCandidate]:
    return [
        ProductCandidate(
            id="build-001",
            brand="SpecPilot",
            model_name="Creator RTX 4070 Build",
            normalized_model="creator-rtx4070-7800x3d-b650",
            category=category.category,
            form_factor="desktop_build",
            specs={
                "cpu": "Ryzen 7 7800X3D",
                "gpu": "RTX 4070 SUPER",
                "motherboard": "B650",
                "cpu_socket": "AM5",
                "motherboard_socket": "AM5",
                "ram_gb": 32,
                "ssd_tb": 1,
                "psu_watt": 750,
            },
            source_url="https://example.com/pc-builds/creator-rtx4070",
        ),
        ProductCandidate(
            id="build-002",
            brand="SpecPilot",
            model_name="Balanced RTX 4060 Ti Build",
            normalized_model="balanced-rtx4060ti-7500f-b650",
            category=category.category,
            form_factor="desktop_build",
            specs={
                "cpu": "Ryzen 5 7500F",
                "gpu": "RTX 4060 Ti",
                "motherboard": "B650",
                "cpu_socket": "AM5",
                "motherboard_socket": "AM5",
                "ram_gb": 32,
                "ssd_tb": 1,
                "psu_watt": 650,
            },
            source_url="https://example.com/pc-builds/balanced-rtx4060ti",
        ),
        ProductCandidate(
            id="build-003",
            brand="SpecPilot",
            model_name="Intel Creator RTX 4070 Build",
            normalized_model="intel-creator-rtx4070-14700-b760",
            category=category.category,
            form_factor="desktop_build",
            specs={
                "cpu": "Core i7-14700",
                "gpu": "RTX 4070",
                "motherboard": "B760",
                "cpu_socket": "LGA1700",
                "motherboard_socket": "LGA1700",
                "ram_gb": 32,
                "ssd_tb": 2,
                "psu_watt": 750,
            },
            source_url="https://example.com/pc-builds/intel-creator-rtx4070",
        ),
        ProductCandidate(
            id="build-004",
            brand="SpecPilot",
            model_name="Budget RX 7600 Build",
            normalized_model="budget-rx7600-5600-b550",
            category=category.category,
            form_factor="desktop_build",
            specs={
                "cpu": "Ryzen 5 5600",
                "gpu": "RX 7600",
                "motherboard": "B550",
                "cpu_socket": "AM4",
                "motherboard_socket": "AM4",
                "ram_gb": 16,
                "ssd_tb": 1,
                "psu_watt": 600,
            },
            source_url="https://example.com/pc-builds/budget-rx7600",
        ),
        ProductCandidate(
            id="build-005",
            brand="SpecPilot",
            model_name="High-End RTX 4080 Build",
            normalized_model="highend-rtx4080-7900x-b650e",
            category=category.category,
            form_factor="desktop_build",
            specs={
                "cpu": "Ryzen 9 7900X",
                "gpu": "RTX 4080 SUPER",
                "motherboard": "B650E",
                "cpu_socket": "AM5",
                "motherboard_socket": "AM5",
                "ram_gb": 64,
                "ssd_tb": 2,
                "psu_watt": 850,
            },
            source_url="https://example.com/pc-builds/highend-rtx4080",
        ),
    ]


def _laptop_candidates(criteria: PurchaseCriteria) -> list[ProductCandidate]:
    return [
        ProductCandidate(
            id="laptop-001",
            brand="ASUS",
            model_name="ProArt P16",
            normalized_model="asus-proart-p16-32gb",
            category=criteria.category,
            form_factor="laptop",
            specs={"cpu": "Ryzen AI 9", "ram_gb": 32, "gpu": "RTX 4060", "weight_kg": 1.85},
            source_url="https://example.com/laptops/asus-proart-p16",
        ),
        ProductCandidate(
            id="laptop-002",
            brand="Lenovo",
            model_name="Yoga Pro 7",
            normalized_model="lenovo-yoga-pro-7-32gb",
            category=criteria.category,
            form_factor="laptop",
            specs={"cpu": "Ryzen 7", "ram_gb": 32, "gpu": "RTX 4050", "weight_kg": 1.59},
            source_url="https://example.com/laptops/lenovo-yoga-pro-7",
        ),
        ProductCandidate(
            id="laptop-003",
            brand="Apple",
            model_name="MacBook Pro 14",
            normalized_model="apple-macbook-pro-14-m4",
            category=criteria.category,
            form_factor="laptop",
            specs={"cpu": "M4", "ram_gb": 16, "gpu": "integrated", "weight_kg": 1.55},
            source_url="https://example.com/laptops/macbook-pro-14",
        ),
        ProductCandidate(
            id="laptop-004",
            brand="LG",
            model_name="gram Pro 16",
            normalized_model="lg-gram-pro-16",
            category=criteria.category,
            form_factor="laptop",
            specs={"cpu": "Core Ultra 7", "ram_gb": 16, "gpu": "Arc", "weight_kg": 1.19},
            source_url="https://example.com/laptops/lg-gram-pro-16",
        ),
        ProductCandidate(
            id="laptop-005",
            brand="Dell",
            model_name="XPS 15",
            normalized_model="dell-xps-15",
            category=criteria.category,
            form_factor="laptop",
            specs={"cpu": "Core Ultra 7", "ram_gb": 32, "gpu": "RTX 4050", "weight_kg": 1.86},
            source_url="https://example.com/laptops/dell-xps-15",
        ),
    ]


def _purpose_fit(product: ProductCandidate, criteria: PurchaseCriteria) -> float:
    score = 70.0
    purpose = criteria.purpose.lower()
    ram = float(product.specs.get("ram_gb", 0))
    gpu = str(product.specs.get("gpu", "")).lower()
    if "game" in purpose or "게임" in purpose:
        score += 14 if "4070" in gpu or "4080" in gpu else 8
    if "video" in purpose or "편집" in purpose or "premiere" in purpose:
        score += 12 if ram >= 32 else 3
        score += 10 if "rtx" in gpu or "m4" in gpu else 2
    if product.category == Category.laptop and float(product.specs.get("weight_kg", 9)) <= 1.8:
        score += 6
    if product.category == Category.desktop_pc and float(product.specs.get("psu_watt", 0)) >= 650:
        score += 5
    return min(100, score)


def _compatibility_score(product: ProductCandidate) -> float:
    if product.category == Category.laptop:
        return 92.0
    socket_match = product.specs.get("cpu_socket") == product.specs.get("motherboard_socket")
    psu = float(product.specs.get("psu_watt", 0))
    gpu = str(product.specs.get("gpu", ""))
    required = 850 if "4080" in gpu else 750 if "4070" in gpu else 650 if "4060" in gpu else 550
    return 96.0 if socket_match and psu >= required else 68.0


def _pros_for(product: ProductCandidate) -> list[str]:
    if product.category == Category.desktop_pc:
        return ["부품 교체와 업그레이드가 쉬움", "예산 대비 그래픽 성능을 조정하기 좋음"]
    return ["완제품이라 구매와 이동이 편함", "작업 환경 이동이 잦은 사용자에게 적합"]


def _cons_for(product: ProductCandidate) -> list[str]:
    if product.category == Category.desktop_pc:
        return [
            "조립비, 윈도우 포함 여부, 케이스 호환성 확인 필요",
            "부품별 AS 정책이 다를 수 있음",
        ]
    return ["고성능 작업 시 발열과 팬 소음 확인 필요", "RAM/SSD 업그레이드 제한 가능성"]


def _complaints_for(product: ProductCandidate) -> list[str]:
    if product.category == Category.desktop_pc:
        return ["파워 용량", "케이스 크기", "쿨러 간섭", "조립비"]
    return ["팬 소음", "발열", "충전기 무게", "옵션별 가격 차이"]


def _risk_signals_for(index: int) -> list[str]:
    signals = [
        "동일한 문구의 후기 또는 견적 댓글이 반복됨",
        "가격 정보의 수집 시점이 오래되었을 수 있음",
        "벤치마크와 실사용 후기가 다르게 나타남",
    ]
    return signals[: max(1, 3 - index % 3)]


def _fit_summary(product: ProductCandidate, card: ScoreCard) -> str:
    return (
        f"{product.model_name}은 총점 {card.total_score}점으로 목적 적합도, "
        "가격, 호환성의 균형이 좋은 후보입니다."
    )
