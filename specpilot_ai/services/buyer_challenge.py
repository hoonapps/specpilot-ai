from datetime import UTC, datetime
from urllib.parse import urlencode

from specpilot_ai.core.models import (
    BuyerChallengeShareVariant,
    BuyerChallengeStep,
    Category,
    PublicBuyerChallengeKit,
)


def build_public_buyer_challenge_kit(
    *,
    category: Category | None = None,
    budget_krw: int | None = None,
    persona: str = "creator_gamer",
    generated_at: datetime | None = None,
) -> PublicBuyerChallengeKit:
    generated_at = generated_at or datetime.now(UTC)
    target_category = category or Category.desktop_pc
    target_budget = _normalize_budget(target_category, budget_krw)
    target_persona = persona.strip() or "creator_gamer"
    label = _category_label(target_category)
    persona_label = _persona_label(target_persona)
    checklist_path = _path(
        "/public/buyer-checklist",
        category=target_category.value,
        budget_krw=str(target_budget),
        persona=target_persona,
    )
    mistake_cost_path = _path(
        "/public/mistake-cost-calculator/result",
        category=target_category.value,
        budget_krw=str(target_budget),
        quantity="1",
        urgency=_urgency_for_persona(target_persona),
    )
    analysis_prefill = _analysis_prefill(target_category, target_budget, target_persona)
    challenge_title = f"{label} {target_budget:,}원 구매 실패 방지 챌린지"
    return PublicBuyerChallengeKit(
        generated_at=generated_at.isoformat(),
        category=target_category,
        budget_krw=target_budget,
        persona=target_persona,
        headline=f"{challenge_title}를 공유하고 결제 전 검수를 받으세요.",
        summary=(
            f"{persona_label} 상황에 맞춰 성향 진단, 실패 비용 계산, 결제 전 체크리스트를 "
            "하나의 공유 문구로 묶었습니다. 리포트를 만들기 전에도 지인·팀·커뮤니티에서 "
            "조건 검토를 시작할 수 있습니다."
        ),
        challenge_title=challenge_title,
        challenge_steps=_challenge_steps(target_category, target_persona),
        analysis_prefill=analysis_prefill,
        checklist_path=checklist_path,
        mistake_cost_path=mistake_cost_path,
        hashtags=_hashtags(target_category, target_persona),
        proof_points=_proof_points(target_category, target_persona),
        share_variants=_share_variants(
            category=target_category,
            budget_krw=target_budget,
            persona=target_persona,
            challenge_title=challenge_title,
            analysis_prefill=analysis_prefill,
            checklist_path=checklist_path,
        ),
        next_actions=[
            "가장 가까운 채널 문구를 복사해 주변 검토를 먼저 받으세요.",
            "반응이 온 조건을 analysis prefill에 합쳐 첫 리포트를 생성하세요.",
            "공유 후에도 결제 전에는 옵션명, 최종가, 판매자 답변을 캡처하세요.",
        ],
    )


def _normalize_budget(category: Category, budget_krw: int | None) -> int:
    if budget_krw and budget_krw > 0:
        return min(30_000_000, max(300_000, budget_krw))
    if category == Category.laptop:
        return 2_000_000
    return 2_200_000


def _path(base: str, **params: str) -> str:
    return f"{base}?{urlencode(params)}"


def _category_label(category: Category) -> str:
    return "노트북" if category == Category.laptop else "데스크톱 PC"


def _persona_label(persona: str) -> str:
    labels = {
        "creator_gamer": "성능 검수형 구매자",
        "portable_creator": "휴대 리스크 방어형 구매자",
        "team_buyer": "팀 장비 승인형 구매 담당자",
        "budget_guard": "예산 방어형 구매자",
        "first_pc_buyer": "첫 PC 구매자",
    }
    return labels.get(persona, persona.replace("_", " "))


def _urgency_for_persona(persona: str) -> str:
    if "team" in persona:
        return "team_rollout"
    if "budget" in persona:
        return "low"
    return "normal"


def _analysis_prefill(category: Category, budget_krw: int, persona: str) -> str:
    label = _category_label(category)
    if "team" in persona:
        return (
            f"팀에 지급할 {label}을 1대당 {budget_krw:,}원 안에서 추천해줘. "
            "승인자 공유 리포트, 납기, AS, 옵션명 검수, 구매 실패 비용까지 같이 봐줘."
        )
    if category == Category.laptop or "portable" in persona:
        return (
            f"{label}을 {budget_krw:,}원 안에서 추천해줘. 무게, 발열, 배터리, "
            "RAM/SSD 옵션명, AS와 가격 타이밍을 결제 전 체크리스트로 같이 봐줘."
        )
    return (
        f"{label}를 {budget_krw:,}원 안에서 추천해줘. QHD 게임, 영상 편집, "
        "32GB RAM, GPU/파워/케이스 호환성, 가격 타이밍, 결제 전 검수까지 같이 봐줘."
    )


def _challenge_steps(category: Category, persona: str) -> list[BuyerChallengeStep]:
    label = _category_label(category)
    team_proof = (
        "승인자, 실사용자, 구매 담당자가 같은 근거를 볼 수 있습니다."
        if "team" in persona
        else "가족·동료·커뮤니티가 같은 조건을 보고 반대 의견을 줄 수 있습니다."
    )
    return [
        BuyerChallengeStep(
            step_id="persona",
            title="구매 성향을 먼저 고정",
            action="30초 진단으로 성능·휴대성·팀 승인·예산 방어 중 우선순위를 정합니다.",
            proof="추천 후보보다 먼저 평가 기준을 고정해 흔들리는 특가 판단을 줄입니다.",
        ),
        BuyerChallengeStep(
            step_id="cost",
            title="잘못 샀을 때 비용을 숫자로 보기",
            action=(
                f"{label} 예산과 구매 긴급도로 성능 부족, 옵션 불일치, "
                "반품 지연 비용을 계산합니다."
            ),
            proof="예상 손실이 예산의 20%를 넘으면 즉시 구매보다 검수 리포트가 우선입니다.",
        ),
        BuyerChallengeStep(
            step_id="review",
            title="공유 문구로 결제 전 검토 받기",
            action="채널별 문구를 복사해 구매 조건과 우려 사항을 먼저 공유합니다.",
            proof=team_proof,
        ),
    ]


def _proof_points(category: Category, persona: str) -> list[str]:
    label = _category_label(category)
    points = [
        f"{label} 후보를 추천하기 전 예산, 목적, 제외 조건을 먼저 고정합니다.",
        "실구매가, 배송비, 쿠폰, 옵션명 변경을 결제 직전 대조합니다.",
        "공유 리포트로 추천 이유와 제외 이유를 함께 검토합니다.",
    ]
    if "team" in persona:
        points.append("팀 구매는 납기, 재고, AS, 승인자 브리프를 같은 패키지로 봅니다.")
    return points


def _hashtags(category: Category, persona: str) -> list[str]:
    base = ["#SpecPilotAI", "#컴퓨터구매", "#구매실패방지"]
    if category == Category.laptop:
        base.append("#노트북추천")
    else:
        base.append("#PC견적")
    if "team" in persona:
        base.append("#팀장비구매")
    elif "budget" in persona:
        base.append("#예산방어")
    return base


def _share_variants(
    *,
    category: Category,
    budget_krw: int,
    persona: str,
    challenge_title: str,
    analysis_prefill: str,
    checklist_path: str,
) -> list[BuyerChallengeShareVariant]:
    label = _category_label(category)
    persona_label = _persona_label(persona)
    budget_text = f"{budget_krw:,}원"
    common = (
        f"{challenge_title}\n"
        f"- 상황: {persona_label}\n"
        f"- 예산: {budget_text}\n"
        f"- 분석 요청: {analysis_prefill}\n"
        f"- 체크리스트: {checklist_path}\n"
        "SpecPilot AI로 결제 전 가격·옵션·리스크를 먼저 검수하려고 합니다."
    )
    return [
        BuyerChallengeShareVariant(
            channel="kakao",
            label="카카오톡·가족 채팅",
            headline=f"{label} 사기 전에 이 조건 괜찮은지 봐줘",
            body="가족이나 지인에게 예산, 용도, 걱정되는 리스크를 짧게 공유합니다.",
            cta="의견 받기",
            copy_text=(
                f"{label} 구매 전에 조건 검토 좀 부탁해.\n"
                f"예산은 {budget_text}, 유형은 {persona_label}.\n"
                f"{analysis_prefill}\nSpecPilot AI 체크리스트로 먼저 확인해보려고 해."
            ),
        ),
        BuyerChallengeShareVariant(
            channel="community",
            label="커뮤니티·카페",
            headline=f"{budget_text} {label} 구매 실패 방지 챌린지",
            body="커뮤니티에서 반대 의견, 빠진 조건, 특가 착시를 빠르게 받는 문구입니다.",
            cta="피드백 받기",
            copy_text=(
                f"{common}\n"
                "빠진 조건이나 결제 전 확인해야 할 위험 신호가 있으면 알려주세요."
            ),
        ),
        BuyerChallengeShareVariant(
            channel="team",
            label="팀 슬랙·승인 채널",
            headline=f"{label} 구매 승인 전 검토 요청",
            body="팀 구매 담당자가 승인자와 실사용자에게 같은 근거를 공유하는 문구입니다.",
            cta="승인 근거 공유",
            copy_text=(
                f"구매 승인 전 조건 검토 요청입니다.\n{common}\n"
                "확인할 항목: 납기, AS, 옵션명, 총액, 대체 후보, 반품 조건."
            ),
        ),
    ]
