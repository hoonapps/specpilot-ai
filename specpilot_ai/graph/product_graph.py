from pydantic import BaseModel


class GraphNode(BaseModel):
    label: str
    key_property: str
    description: str


class GraphRelationship(BaseModel):
    type: str
    source: str
    target: str
    description: str


class ProductGraphSchema(BaseModel):
    nodes: list[GraphNode]
    relationships: list[GraphRelationship]
    constraints: list[str]


def pc_purchase_graph_schema() -> ProductGraphSchema:
    return ProductGraphSchema(
        nodes=[
            GraphNode(label="Build", key_property="normalized_model", description="PC 견적 조합"),
            GraphNode(label="Laptop", key_property="normalized_model", description="노트북 완제품"),
            GraphNode(
                label="Component",
                key_property="part_no",
                description="CPU, GPU, RAM 등 부품",
            ),
            GraphNode(label="Offer", key_property="offer_id", description="가격/배송/조립 조건"),
            GraphNode(
                label="Seller",
                key_property="name",
                description="판매처 또는 가격 비교 출처",
            ),
            GraphNode(label="Review", key_property="review_id", description="사용자/전문 리뷰"),
            GraphNode(label="Benchmark", key_property="benchmark_id", description="성능 근거"),
            GraphNode(label="CompatibilitySignal", key_property="name", description="호환성 신호"),
            GraphNode(label="PriceAlert", key_property="alert_id", description="목표가 알림 조건"),
            GraphNode(
                label="AnalysisTrace",
                key_property="trace_id",
                description="Agent 실행 추적",
            ),
        ],
        relationships=[
            GraphRelationship(
                type="USES",
                source="Build",
                target="Component",
                description="견적이 특정 부품을 사용한다.",
            ),
            GraphRelationship(
                type="SOLD_AS",
                source="Build",
                target="Offer",
                description="견적 조합의 판매 조건을 연결한다.",
            ),
            GraphRelationship(
                type="SOLD_AS",
                source="Laptop",
                target="Offer",
                description="노트북 완제품의 판매 조건을 연결한다.",
            ),
            GraphRelationship(
                type="OFFERED_BY",
                source="Offer",
                target="Seller",
                description="오퍼의 판매처를 연결한다.",
            ),
            GraphRelationship(
                type="HAS_REVIEW",
                source="Build",
                target="Review",
                description="견적 또는 부품 후기를 연결한다.",
            ),
            GraphRelationship(
                type="HAS_REVIEW",
                source="Laptop",
                target="Review",
                description="노트북 후기를 연결한다.",
            ),
            GraphRelationship(
                type="HAS_BENCHMARK",
                source="Component",
                target="Benchmark",
                description="부품 성능 근거를 연결한다.",
            ),
            GraphRelationship(
                type="CHECKED_BY",
                source="Build",
                target="CompatibilitySignal",
                description="소켓, 파워, 케이스 간섭 같은 호환성 검증 신호를 연결한다.",
            ),
            GraphRelationship(
                type="CHECKED_BY",
                source="Laptop",
                target="CompatibilitySignal",
                description="RAM, GPU, 무게, 배터리 같은 노트북 검증 신호를 연결한다.",
            ),
            GraphRelationship(
                type="WATCHED_BY",
                source="Offer",
                target="PriceAlert",
                description="가격 조건이 목표가 알림으로 추적된다.",
            ),
            GraphRelationship(
                type="PRODUCED",
                source="AnalysisTrace",
                target="Offer",
                description="분석 실행이 비교 대상 오퍼를 생성하거나 조회했다.",
            ),
            GraphRelationship(
                type="PRODUCED",
                source="AnalysisTrace",
                target="CompatibilitySignal",
                description="분석 실행이 호환성 검증 신호를 생성했다.",
            ),
        ],
        constraints=[
            "Build.normalized_model must be unique",
            "Laptop.normalized_model must be unique",
            "Component.part_no must be unique",
            "Offer.offer_id must be unique",
            "Review.review_id must be unique",
            "PriceAlert.alert_id must be unique",
            "AnalysisTrace.trace_id must be unique",
        ],
    )
