from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set

from log_parser import LogRecord, group_by_transaction


class SiteState(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    ACTIVE = "ACTIVE"
    READY = "READY"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"
    INVALID = "INVALID"


class GlobalDecision(str, Enum):
    REDO = "REDO"
    UNDO = "UNDO"
    UNCERTAIN = "UNCERTAIN"


@dataclass
class TransactionAnalysis:
    transaction_id: str
    site_states: Dict[str, SiteState]
    decision: GlobalDecision
    reason: str
    textbook_rule: str
    repaired_sites: Dict[str, str] = field(default_factory=dict)


class TransactionAnalyzer:
    """Analyze distributed transaction logs using 2PC-inspired state rules.

    Assumption for this project:
    - SITE1 is the default coordinator.
    - If COMMIT and ABORT both appear for the same transaction across sites,
      the distributed log violates 2PC atomicity and is reported as a global conflict.
    - If any site has ABORT and no COMMIT conflict exists, global abort wins,
      because one negative vote is enough.
    - If any site has COMMIT and no ABORT conflict exists, it represents a known global commit decision.
    - READY without global decision is the classic 2PC blocked/uncertain case.
      For producing a clean database, the recovery manager may convert UNCERTAIN to UNDO.
    """

    def __init__(self, coordinator_site: str = "SITE1", uncertain_policy: str = "abort") -> None:
        self.coordinator_site = coordinator_site.upper()
        self.uncertain_policy = uncertain_policy.lower()
        if self.uncertain_policy not in {"abort", "keep_uncertain"}:
            raise ValueError("uncertain_policy phải là 'abort' hoặc 'keep_uncertain'")

    def analyze(self, site_logs: Dict[str, List[LogRecord]]) -> List[TransactionAnalysis]:
        grouped = group_by_transaction(site_logs)
        all_sites: Set[str] = set(site_logs.keys())
        analyses: List[TransactionAnalysis] = []

        for tx_id in sorted(grouped.keys()):
            site_records = grouped[tx_id]
            states = {
                site_id: self._state_for_site(site_records.get(site_id, []))
                for site_id in sorted(all_sites)
            }
            decision, reason, textbook_rule = self._global_decision(states)
            repaired_sites = self._find_repairs(states, decision)
            analyses.append(
                TransactionAnalysis(
                    transaction_id=tx_id,
                    site_states=states,
                    decision=decision,
                    reason=reason,
                    textbook_rule=textbook_rule,
                    repaired_sites=repaired_sites,
                )
            )
        return analyses

    def _state_for_site(self, records: List[LogRecord]) -> SiteState:
        if not records:
            return SiteState.NOT_FOUND

        operations = [r.operation for r in records]

        # A well-formed 2PC log must not contain both terminal decisions.
        if "COMMIT" in operations and "ABORT" in operations:
            return SiteState.INVALID

        if "COMMIT" in operations:
            return SiteState.COMMITTED
        if "ABORT" in operations:
            return SiteState.ABORTED
        if "PREPARE" in operations:
            return SiteState.READY
        if "START" in operations or "UPDATE" in operations:
            return SiteState.ACTIVE
        return SiteState.NOT_FOUND

    def _global_decision(self, states: Dict[str, SiteState]) -> tuple[GlobalDecision, str, str]:
        state_values = set(states.values())

        if SiteState.INVALID in state_values:
            return (
                GlobalDecision.UNDO,
                "Phát hiện log cục bộ không hợp lệ: một site có cả COMMIT và ABORT cho cùng một transaction. Cách phục hồi an toàn nhất là UNDO và ghi nhận xung đột trong báo cáo.",
                "Quy tắc nhất quán log của 2PC: một transaction tại một site chỉ được có một quyết định kết thúc duy nhất.",
            )

        if SiteState.COMMITTED in state_values and SiteState.ABORTED in state_values:
            return (
                GlobalDecision.UNDO,
                "Phát hiện xung đột toàn cục: có site ghi COMMIT nhưng site khác ghi ABORT cho cùng một transaction. Điều này vi phạm tính atomic commitment của 2PC. Cách xử lý an toàn là UNDO và báo cáo lỗi xung đột.",
                "Quy tắc atomicity của 2PC: một transaction phân tán chỉ được có một quyết định toàn cục, hoặc COMMIT ở tất cả site, hoặc ABORT ở tất cả site.",
            )

        if SiteState.ABORTED in state_values:
            return (
                GlobalDecision.UNDO,
                "Có ít nhất một site ghi ABORT và không có xung đột COMMIT. Trong 2PC, chỉ cần một site/vote abort thì toàn bộ transaction phải global abort.",
                "Quy tắc 2PC: nếu một participant vote abort, coordinator phải quyết định global abort.",
            )

        if SiteState.COMMITTED in state_values:
            return (
                GlobalDecision.REDO,
                "Tồn tại bản ghi COMMIT, nên quyết định toàn cục được xác định là commit. Các site thiếu COMMIT sẽ được sửa trong clean log.",
                "Bản ghi quyết định của 2PC: khi global commit đã được ghi log, các participant phải commit khi phục hồi.",
            )

        if all(s == SiteState.READY for s in state_values):
            if self.uncertain_policy == "abort":
                return (
                    GlobalDecision.UNDO,
                    "Tất cả site đều ở trạng thái READY nhưng không có COMMIT/ABORT toàn cục. Chính sách timeout-abort được áp dụng để tạo trạng thái database sạch.",
                    "Trường hợp blocking của 2PC: participant ở READY không thể tự commit nếu chưa có quyết định toàn cục; cần timeout/termination policy.",
                )
            return (
                GlobalDecision.UNCERTAIN,
                "Tất cả site đều READY nhưng chưa có quyết định toàn cục. Transaction được giữ ở trạng thái bị chặn/chưa chắc chắn.",
                "Trường hợp blocking của 2PC: participant READY phải chờ quyết định từ coordinator/toàn cục.",
            )

        return (
            GlobalDecision.UNDO,
            "Transaction chưa đạt global commit một cách an toàn, nên phải UNDO để bảo toàn tính nguyên tử.",
            "Quy tắc atomicity: transaction chưa hoàn tất không được để lại tác động dang dở sau crash.",
        )

    def _find_repairs(self, states: Dict[str, SiteState], decision: GlobalDecision) -> Dict[str, str]:
        repairs: Dict[str, str] = {}
        if decision == GlobalDecision.REDO:
            for site, state in states.items():
                if state in {SiteState.ACTIVE, SiteState.READY, SiteState.NOT_FOUND}:
                    repairs[site] = "COMMIT"
        elif decision == GlobalDecision.UNDO:
            for site, state in states.items():
                if state in {SiteState.ACTIVE, SiteState.READY, SiteState.NOT_FOUND}:
                    repairs[site] = "ABORT"
        return repairs
