import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from specpilot_ai.core.config import Settings
from specpilot_ai.core.models import (
    AlertSubscription,
    AnalyzeResponse,
    OperationsMetrics,
    ReviewDecision,
    ReviewQueueItem,
    ReviewStatus,
    SavedReportDetail,
    SavedReportSummary,
    SourceCandidate,
)


class SpecPilotStore:
    def __init__(self, settings: Settings) -> None:
        self.db_path = Path(settings.storage_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def save_analysis(self, response: AnalyzeResponse) -> None:
        self.save_analysis_for_workspace("demo", response)

    def save_analysis_for_workspace(self, workspace_id: str, response: AnalyzeResponse) -> None:
        now = _now()
        payload = response.model_dump_json()
        final_pick = response.report.final_pick_id
        top = (
            response.report.top_recommendations[0]
            if response.report.top_recommendations
            else None
        )
        top_model = top.product.model_name if top else None
        top_score = top.score.total_score if top else 0
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO analysis_runs (
                    trace_id, workspace_id, category, purpose, budget_krw, final_pick_id,
                    top_model_name, top_score, response_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET
                    workspace_id=excluded.workspace_id,
                    category=excluded.category,
                    purpose=excluded.purpose,
                    budget_krw=excluded.budget_krw,
                    final_pick_id=excluded.final_pick_id,
                    top_model_name=excluded.top_model_name,
                    top_score=excluded.top_score,
                    response_json=excluded.response_json,
                    updated_at=excluded.updated_at
                """,
                (
                    response.graph_trace_id,
                    workspace_id,
                    response.criteria.category.value,
                    response.criteria.purpose,
                    response.criteria.budget_krw,
                    final_pick,
                    top_model,
                    top_score,
                    payload,
                    now,
                    now,
                ),
            )

    def get_analysis(self, trace_id: str) -> AnalyzeResponse | None:
        return self.get_analysis_for_workspace("demo", trace_id)

    def get_analysis_for_workspace(
        self,
        workspace_id: str,
        trace_id: str,
    ) -> AnalyzeResponse | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT response_json
                FROM analysis_runs
                WHERE trace_id = ? AND workspace_id = ?
                """,
                (trace_id, workspace_id),
            ).fetchone()
        if row is None:
            return None
        return AnalyzeResponse.model_validate_json(row["response_json"])

    def save_report(
        self,
        response: AnalyzeResponse,
        *,
        title: str,
        owner_label: str,
        notes: str,
    ) -> SavedReportSummary:
        return self.save_report_for_workspace(
            "demo",
            response,
            title=title,
            owner_label=owner_label,
            notes=notes,
        )

    def save_report_for_workspace(
        self,
        workspace_id: str,
        response: AnalyzeResponse,
        *,
        title: str,
        owner_label: str,
        notes: str,
    ) -> SavedReportSummary:
        self.save_analysis_for_workspace(workspace_id, response)
        now = _now()
        report_id = f"report_{uuid4().hex[:12]}"
        top = (
            response.report.top_recommendations[0]
            if response.report.top_recommendations
            else None
        )
        top_model = top.product.model_name if top else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO saved_reports (
                    report_id, trace_id, workspace_id, title, owner_label, notes,
                    final_pick_id, top_model_name, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    response.graph_trace_id,
                    workspace_id,
                    title,
                    owner_label,
                    notes,
                    response.report.final_pick_id,
                    top_model,
                    now,
                    now,
                ),
            )
        return SavedReportSummary(
            report_id=report_id,
            trace_id=response.graph_trace_id,
            workspace_id=workspace_id,
            title=title,
            owner_label=owner_label,
            final_pick_id=response.report.final_pick_id,
            top_model_name=top_model,
            created_at=now,
            updated_at=now,
        )

    def list_reports(self, limit: int = 20) -> list[SavedReportSummary]:
        return self.list_reports_for_workspace("demo", limit=limit)

    def list_reports_for_workspace(
        self,
        workspace_id: str,
        limit: int = 20,
    ) -> list[SavedReportSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT report_id, trace_id, workspace_id, title, owner_label, final_pick_id,
                       top_model_name, created_at, updated_at
                FROM saved_reports
                WHERE workspace_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (workspace_id, limit),
            ).fetchall()
        return [SavedReportSummary(**dict(row)) for row in rows]

    def get_report(self, report_id: str) -> SavedReportDetail | None:
        return self.get_report_for_workspace("demo", report_id)

    def get_report_for_workspace(
        self,
        workspace_id: str,
        report_id: str,
    ) -> SavedReportDetail | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT sr.*, ar.response_json
                FROM saved_reports sr
                JOIN analysis_runs ar ON ar.trace_id = sr.trace_id
                WHERE sr.report_id = ? AND sr.workspace_id = ?
                """,
                (report_id, workspace_id),
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        response = AnalyzeResponse.model_validate_json(data.pop("response_json"))
        return SavedReportDetail(
            report_id=data["report_id"],
            trace_id=data["trace_id"],
            workspace_id=data["workspace_id"],
            title=data["title"],
            owner_label=data["owner_label"],
            notes=data["notes"],
            final_pick_id=data["final_pick_id"],
            top_model_name=data["top_model_name"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            response=response,
        )

    def create_alert_subscription(
        self,
        response: AnalyzeResponse,
        *,
        product_id: str,
        target_price_krw: int,
        channels: list[str],
        contact: str,
        owner_label: str,
    ) -> AlertSubscription:
        return self.create_alert_subscription_for_workspace(
            "demo",
            response,
            product_id=product_id,
            target_price_krw=target_price_krw,
            channels=channels,
            contact=contact,
            owner_label=owner_label,
        )

    def create_alert_subscription_for_workspace(
        self,
        workspace_id: str,
        response: AnalyzeResponse,
        *,
        product_id: str,
        target_price_krw: int,
        channels: list[str],
        contact: str,
        owner_label: str,
    ) -> AlertSubscription:
        self.save_analysis_for_workspace(workspace_id, response)
        prices = {
            item.product_id: item.current_price_krw
            for item in response.report.price_alerts
        }
        current_price = prices.get(product_id)
        if current_price is None:
            for row in response.report.comparison_table:
                if row.product_id == product_id:
                    current_price = row.effective_price_krw
                    break
        if current_price is None:
            raise ValueError(f"Unknown product_id for alert: {product_id}")

        now = _now()
        subscription = AlertSubscription(
            subscription_id=f"alert_{uuid4().hex[:12]}",
            trace_id=response.graph_trace_id,
            product_id=product_id,
            workspace_id=workspace_id,
            target_price_krw=target_price_krw,
            current_price_krw=current_price,
            channels=channels,
            contact=contact,
            owner_label=owner_label,
            status="active",
            created_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_subscriptions (
                    subscription_id, trace_id, product_id, workspace_id, target_price_krw,
                    current_price_krw, channels_json, contact, owner_label,
                    status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription.subscription_id,
                    subscription.trace_id,
                    subscription.product_id,
                    subscription.workspace_id,
                    subscription.target_price_krw,
                    subscription.current_price_krw,
                    json.dumps(subscription.channels, ensure_ascii=False),
                    subscription.contact,
                    subscription.owner_label,
                    subscription.status,
                    subscription.created_at,
                ),
            )
        return subscription

    def list_alert_subscriptions(self, limit: int = 50) -> list[AlertSubscription]:
        return self.list_alert_subscriptions_for_workspace("demo", limit=limit)

    def list_alert_subscriptions_for_workspace(
        self,
        workspace_id: str,
        limit: int = 50,
    ) -> list[AlertSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM alert_subscriptions
                WHERE workspace_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (workspace_id, limit),
            ).fetchall()
        return [_alert_from_row(row) for row in rows]

    def add_review_items(self, items: list[ReviewQueueItem]) -> list[ReviewQueueItem]:
        with self._connect() as conn:
            for item in items:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO source_review_queue (
                        review_id, source_id, source_json, status, reason,
                        created_at, resolved_at, reviewer, note
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.review_id,
                        item.source.source_id,
                        item.source.model_dump_json(),
                        item.status.value,
                        item.reason,
                        item.created_at,
                        item.resolved_at,
                        item.reviewer,
                        "",
                    ),
                )
        return items

    def list_review_items(
        self,
        *,
        status: ReviewStatus | None = ReviewStatus.pending,
        limit: int = 50,
    ) -> list[ReviewQueueItem]:
        query = """
            SELECT *
            FROM source_review_queue
        """
        params: list[str | int] = []
        if status is not None:
            query += " WHERE status = ?"
            params.append(status.value)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_review_item_from_row(row) for row in rows]

    def decide_review(
        self,
        review_id: str,
        *,
        status: ReviewStatus,
        reviewer: str,
        note: str,
    ) -> ReviewDecision | None:
        now = _now()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT review_id FROM source_review_queue WHERE review_id = ?",
                (review_id,),
            ).fetchone()
            if existing is None:
                return None
            conn.execute(
                """
                UPDATE source_review_queue
                SET status = ?, reviewer = ?, note = ?, resolved_at = ?
                WHERE review_id = ?
                """,
                (status.value, reviewer, note, now, review_id),
            )
        return ReviewDecision(
            review_id=review_id,
            status=status,
            reviewer=reviewer,
            note=note,
            resolved_at=now,
        )

    def metrics(self) -> OperationsMetrics:
        return self.metrics_for_workspace(None)

    def metrics_for_workspace(self, workspace_id: str | None) -> OperationsMetrics:
        with self._connect() as conn:
            where = " WHERE workspace_id = ?" if workspace_id else ""
            params = (workspace_id,) if workspace_id else ()
            analysis_runs = conn.execute(
                f"SELECT COUNT(*) FROM analysis_runs{where}",
                params,
            ).fetchone()[0]
            saved_reports = conn.execute(
                f"SELECT COUNT(*) FROM saved_reports{where}",
                params,
            ).fetchone()[0]
            alert_subscriptions = conn.execute(
                f"SELECT COUNT(*) FROM alert_subscriptions{where}",
                params,
            ).fetchone()[0]
            latest = conn.execute(
                f"SELECT trace_id FROM analysis_runs{where} ORDER BY created_at DESC LIMIT 1",
                params,
            ).fetchone()
            score_where = (
                " WHERE top_score > 0 AND workspace_id = ?"
                if workspace_id
                else " WHERE top_score > 0"
            )
            score_row = conn.execute(
                f"SELECT AVG(top_score) FROM analysis_runs{score_where}",
                params,
            ).fetchone()
            ready_row = conn.execute(
                f"""
                SELECT AVG(CASE WHEN final_pick_id IS NOT NULL THEN 1.0 ELSE 0.0 END)
                FROM analysis_runs{where}
                """,
                params,
            ).fetchone()
        return OperationsMetrics(
            workspace_id=workspace_id,
            analysis_runs=analysis_runs,
            saved_reports=saved_reports,
            alert_subscriptions=alert_subscriptions,
            latest_trace_id=latest["trace_id"] if latest else None,
            average_top_score=round(float(score_row[0] or 0), 2),
            conversion_ready_rate=round(float(ready_row[0] or 0), 4),
        )

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    trace_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL DEFAULT 'demo',
                    category TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    budget_krw INTEGER,
                    final_pick_id TEXT,
                    top_model_name TEXT,
                    top_score REAL NOT NULL DEFAULT 0,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS saved_reports (
                    report_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'demo',
                    title TEXT NOT NULL,
                    owner_label TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    final_pick_id TEXT,
                    top_model_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(trace_id) REFERENCES analysis_runs(trace_id)
                );

                CREATE TABLE IF NOT EXISTS alert_subscriptions (
                    subscription_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'demo',
                    target_price_krw INTEGER NOT NULL,
                    current_price_krw INTEGER NOT NULL,
                    channels_json TEXT NOT NULL,
                    contact TEXT NOT NULL,
                    owner_label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(trace_id) REFERENCES analysis_runs(trace_id)
                );

                CREATE TABLE IF NOT EXISTS source_review_queue (
                    review_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    reviewer TEXT,
                    note TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_saved_reports_trace
                    ON saved_reports(trace_id);
                CREATE INDEX IF NOT EXISTS idx_alerts_trace
                    ON alert_subscriptions(trace_id);
                CREATE INDEX IF NOT EXISTS idx_source_review_status
                    ON source_review_queue(status);
                """
            )
            _ensure_column(conn, "analysis_runs", "workspace_id", "TEXT NOT NULL DEFAULT 'demo'")
            _ensure_column(conn, "saved_reports", "workspace_id", "TEXT NOT NULL DEFAULT 'demo'")
            _ensure_column(
                conn,
                "alert_subscriptions",
                "workspace_id",
                "TEXT NOT NULL DEFAULT 'demo'",
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_saved_reports_workspace
                ON saved_reports(workspace_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_alerts_workspace
                ON alert_subscriptions(workspace_id)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _alert_from_row(row: sqlite3.Row) -> AlertSubscription:
    data = dict(row)
    return AlertSubscription(
        subscription_id=data["subscription_id"],
        trace_id=data["trace_id"],
        product_id=data["product_id"],
        workspace_id=data["workspace_id"],
        target_price_krw=data["target_price_krw"],
        current_price_krw=data["current_price_krw"],
        channels=json.loads(data["channels_json"]),
        contact=data["contact"],
        owner_label=data["owner_label"],
        status=data["status"],
        created_at=data["created_at"],
    )


def _review_item_from_row(row: sqlite3.Row) -> ReviewQueueItem:
    data = dict(row)
    return ReviewQueueItem(
        review_id=data["review_id"],
        source=SourceCandidate.model_validate_json(data["source_json"]),
        status=ReviewStatus(data["status"]),
        reason=data["reason"],
        created_at=data["created_at"],
        resolved_at=data["resolved_at"],
        reviewer=data["reviewer"],
    )


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _now() -> str:
    return datetime.now(UTC).isoformat()
