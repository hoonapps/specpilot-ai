from fastapi import FastAPI

from specpilot_ai.core.config import get_settings
from specpilot_ai.core.models import AnalyzeRequest, AnalyzeResponse, Category, ProductBrief
from specpilot_ai.graph.neo4j_client import Neo4jRepository
from specpilot_ai.graph.product_graph import pc_purchase_graph_schema
from specpilot_ai.workflows.purchase_agent import run_analysis

app = FastAPI(
    title="SpecPilot AI API",
    version="0.1.0",
    description="AI PC and laptop purchase decision agent with LangGraph and LangChain.",
)


@app.get("/health")
def health() -> dict[str, str | bool]:
    settings = get_settings()
    repo = Neo4jRepository(settings)
    try:
        neo4j_ready = repo.ping()
    finally:
        repo.close()
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "neo4j_ready": neo4j_ready,
    }


@app.get("/product/brief", response_model=ProductBrief)
def product_brief() -> ProductBrief:
    return ProductBrief(
        name="SpecPilot AI",
        one_liner=(
            "A PC and laptop buying assistant that compares specs, compatibility, "
            "prices, reviews and upgrade paths."
        ),
        target_users=[
            "컴퓨터 견적을 처음 맞추는 개인 소비자",
            "작업용 장비를 예산 안에서 고르는 프리랜서와 크리에이터",
            "게임/영상편집/개발용 PC 또는 노트북을 고르는 사용자",
            "사무용 PC와 노트북 구매안을 만드는 소규모 사업자",
        ],
        core_workflows=[
            "Intent Parser",
            "Product Collector",
            "Compatibility Checker",
            "Review Analyzer",
            "Price Tracker",
            "Scoring Engine",
            "Verifier",
            "Report Writer",
        ],
        mvp_categories=[Category.desktop_pc, Category.laptop],
        stack=["FastAPI", "LangGraph", "LangChain LCEL", "Neo4j", "LangSmith-ready traces"],
    )


@app.get("/categories")
def categories() -> dict[str, list[str]]:
    return {"mvp_categories": [category.value for category in Category]}


@app.get("/graph/schema")
def graph_schema() -> dict[str, object]:
    settings = get_settings()
    schema = pc_purchase_graph_schema()
    repo = Neo4jRepository(settings)
    try:
        preview = repo.graph_schema_preview(schema)
    finally:
        repo.close()
    return {"schema": schema.model_dump(), "preview": preview}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    return run_analysis(request)
