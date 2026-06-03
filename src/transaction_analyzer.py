from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Tuple

from log_parser import LogRecord, group_by_transaction


class SiteState(str, Enum):
    """
    Trạng thái của một transaction tại một site.

    NOT_FOUND:
        Site không có log của transaction này.

    ACTIVE:
        Transaction đã START hoặc UPDATE, nhưng chưa PREPARE.

    READY:
        Transaction đã PREPARE nhưng chưa COMMIT/ABORT.
        Đây là trạng thái blocking/uncertain trong 2PC.

    COMMITTED:
        Site đã ghi COMMIT.

    ABORTED:
        Site đã ghi ABORT.

    INVALID:
        Log tại site bị lỗi, ví dụ vừa có COMMIT vừa có ABORT.
    """

    NOT_FOUND = "NOT_FOUND"
    ACTIVE = "ACTIVE"
    READY = "READY"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"
    INVALID = "INVALID"


class GlobalDecision(str, Enum):
    """
    Quyết định phục hồi toàn cục cho một transaction.

    KEEP:
        Transaction đã COMMIT đầy đủ ở tất cả site tham gia.
        Đây là case hoàn hảo, không cần sửa database/log.

    REDO:
        Transaction đã có global COMMIT nhưng một số site/log còn thiếu COMMIT.
        Cần hoàn tất commit và bảo toàn after_value.

    UNDO:
        Transaction bị ABORT, chưa hoàn tất hoặc bị conflict.
        Cần rollback bằng before_value.

    UNCERTAIN:
        Transaction chưa có quyết định rõ ràng.
        Chỉ dùng khi uncertain_policy = keep_uncertain.
    """

    KEEP = "KEEP"
    REDO = "REDO"
    UNDO = "UNDO"
    UNCERTAIN = "UNCERTAIN"


@dataclass
class TransactionAnalysis:
    """
    Kết quả phân tích của một transaction.

    transaction_id:
        Mã transaction, ví dụ T1, T2, T3.

    site_states:
        Trạng thái của transaction tại từng site.
        Ví dụ: {"SITE1": COMMITTED, "SITE2": READY, "SITE3": READY}

    decision:
        Quyết định cuối cùng: KEEP, REDO, UNDO hoặc UNCERTAIN.

    reason:
        Lý do chương trình đưa ra quyết định này.

    textbook_rule:
        Liên hệ với lý thuyết 2PC/recovery.

    repaired_sites:
        Những site cần bổ sung/sửa log trong clean_logs.
        Ví dụ: {"SITE3": "COMMIT"}
    """

    transaction_id: str
    site_states: Dict[str, SiteState]
    decision: GlobalDecision
    reason: str
    textbook_rule: str
    repaired_sites: Dict[str, str]


class TransactionAnalyzer:
    """
    Phân tích transaction log của nhiều site theo quy tắc Two-Phase Commit.

    Nhiệm vụ chính:
    1. Gom log theo transaction.
    2. Xác định trạng thái transaction tại từng site.
    3. Đưa ra quyết định KEEP / REDO / UNDO / UNCERTAIN.
    4. Xác định clean log cần bổ sung COMMIT hoặc ABORT ở site nào.
    """

    def __init__(
        self,
        coordinator_site: str = "SITE1",
        uncertain_policy: str = "abort",
    ) -> None:
        """
        Khởi tạo analyzer.

        coordinator_site:
            Site đóng vai trò coordinator giả lập. Trong project này thường là SITE1.

        uncertain_policy:
            Cách xử lý transaction READY nhưng thiếu global decision.

            "abort":
                Nếu không tìm thấy COMMIT/ABORT toàn cục thì UNDO.
                Đây là timeout abort policy để tạo clean database.

            "keep_uncertain":
                Giữ transaction ở trạng thái UNCERTAIN, không tự ý sửa database/log.
        """

        self.coordinator_site = coordinator_site.upper()
        self.uncertain_policy = uncertain_policy

    def analyze(
        self,
        site_logs: Dict[str, List[LogRecord]],
    ) -> List[TransactionAnalysis]:
        """
        Phân tích toàn bộ transaction trong log của các site.

        Input:
            site_logs:
                Dictionary chứa log của từng site.
                Ví dụ:
                {
                    "SITE1": [LogRecord, LogRecord],
                    "SITE2": [LogRecord, LogRecord],
                    "SITE3": [LogRecord, LogRecord],
                }

        Output:
            Danh sách TransactionAnalysis.
        """

        transaction_logs = group_by_transaction(site_logs)
        all_sites = sorted(site_logs.keys())

        analyses: List[TransactionAnalysis] = []

        for transaction_id in sorted(transaction_logs.keys()):
            records_by_site = transaction_logs[transaction_id]

            states: Dict[str, SiteState] = {}

            for site_id in all_sites:
                records = records_by_site.get(site_id, [])
                states[site_id] = self._state_for_site(records)

            decision, reason, textbook_rule = self._global_decision(states)

            repaired_sites = self._find_repairs(states, decision)

            analyses.append(
                TransactionAnalysis(
                    transaction_id=transaction_id,
                    site_states=states,
                    decision=decision,
                    reason=reason,
                    textbook_rule=textbook_rule,
                    repaired_sites=repaired_sites,
                )
            )

        return analyses

    def _state_for_site(
        self,
        records: List[LogRecord],
    ) -> SiteState:
        """
        Xác định trạng thái của một transaction tại một site.

        Quy tắc:
        - Không có log            => NOT_FOUND
        - Có cả COMMIT và ABORT   => INVALID
        - Có COMMIT               => COMMITTED
        - Có ABORT                => ABORTED
        - Có PREPARE              => READY
        - Có START/UPDATE         => ACTIVE
        """

        if not records:
            return SiteState.NOT_FOUND

        operations = {
            record.operation.upper()
            for record in records
        }

        has_commit = "COMMIT" in operations
        has_abort = "ABORT" in operations
        has_prepare = "PREPARE" in operations
        has_start_or_update = (
            "START" in operations
            or "UPDATE" in operations
        )

        if has_commit and has_abort:
            return SiteState.INVALID

        if has_commit:
            return SiteState.COMMITTED

        if has_abort:
            return SiteState.ABORTED

        if has_prepare:
            return SiteState.READY

        if has_start_or_update:
            return SiteState.ACTIVE

        return SiteState.NOT_FOUND

    def _global_decision(
        self,
        states: Dict[str, SiteState],
    ) -> Tuple[GlobalDecision, str, str]:
        """
        Dựa vào trạng thái của transaction ở các site để quyết định KEEP/REDO/UNDO.

        Đây là hàm ánh xạ lý thuyết 2PC vào code.
        """

        state_values = list(states.values())

        has_invalid = SiteState.INVALID in state_values
        has_commit = SiteState.COMMITTED in state_values
        has_abort = SiteState.ABORTED in state_values
        has_ready = SiteState.READY in state_values
        has_active = SiteState.ACTIVE in state_values

        participated_states = [
            state
            for state in state_values
            if state != SiteState.NOT_FOUND
        ]

        # 1. Log lỗi tại một site.
        if has_invalid:
            return (
                GlobalDecision.UNDO,
                "Có site có log INVALID, ví dụ vừa COMMIT vừa ABORT trong cùng một transaction. Chọn UNDO để an toàn.",
                "Log không nhất quán không được tiếp tục commit vì có thể phá vỡ tính atomicity.",
            )

        # 2. Global conflict: site này COMMIT, site khác ABORT.
        if has_commit and has_abort:
            return (
                GlobalDecision.UNDO,
                "Phát hiện global conflict: một số site COMMIT nhưng site khác ABORT. Chọn UNDO an toàn.",
                "Theo 2PC, atomic commitment yêu cầu một transaction phân tán chỉ có một quyết định toàn cục: COMMIT toàn bộ hoặc ABORT toàn bộ.",
            )

        # 3. Có ABORT ở bất kỳ site nào.
        if has_abort:
            return (
                GlobalDecision.UNDO,
                "Có ít nhất một site ghi ABORT, nên toàn bộ transaction phải UNDO.",
                "Theo 2PC, chỉ cần một participant abort thì global decision phải là ABORT.",
            )

        # 4. Tất cả site tham gia đều COMMITTED.
        # Đây là case hoàn hảo. Không gọi là REDO nữa, mà là KEEP.
        if participated_states and all(
            state == SiteState.COMMITTED
            for state in participated_states
        ):
            return (
                GlobalDecision.KEEP,
                "Tất cả site tham gia transaction đều đã COMMIT. Đây là trường hợp hoàn chỉnh, giữ nguyên kết quả.",
                "Transaction đã commit đầy đủ nên không cần rollback, không cần sửa clean log. Kết quả đã commit được bảo toàn.",
            )

        # 5. Có COMMIT nhưng chưa đầy đủ ở mọi site.
        # Ví dụ SITE1/SITE2 COMMIT, SITE3 READY.
        if has_commit:
            return (
                GlobalDecision.REDO,
                "Đã có global COMMIT nhưng một số site chưa ghi COMMIT đầy đủ. Cần REDO/hoàn tất commit.",
                "Theo recovery sau 2PC, khi đã có quyết định COMMIT, hệ thống phải đảm bảo các thay đổi đã commit được bảo toàn ở các participant.",
            )

        # 6. READY nhưng thiếu global decision.
        if has_ready and not has_active:
            if self.uncertain_policy == "keep_uncertain":
                return (
                    GlobalDecision.UNCERTAIN,
                    "Transaction ở trạng thái READY nhưng không có COMMIT/ABORT. Giữ UNCERTAIN theo cấu hình.",
                    "Trong 2PC, participant ở READY có thể bị blocking nếu chưa nhận global decision.",
                )

            return (
                GlobalDecision.UNDO,
                "Transaction READY nhưng không tìm thấy global decision. Project áp dụng timeout abort policy nên UNDO.",
                "READY không đồng nghĩa với COMMIT. Nếu sau crash không tìm thấy quyết định toàn cục, project chọn ABORT để tạo clean database.",
            )

        # 7. Transaction mới ACTIVE hoặc chưa đủ điều kiện commit.
        if has_active:
            return (
                GlobalDecision.UNDO,
                "Transaction mới ACTIVE hoặc chưa PREPARE đầy đủ, nên UNDO.",
                "Transaction chưa đạt trạng thái commit an toàn thì không được để lại ảnh hưởng trong database.",
            )

        # 8. Fallback an toàn.
        return (
            GlobalDecision.UNDO,
            "Không tìm thấy bằng chứng COMMIT an toàn. Chọn UNDO để bảo toàn dữ liệu.",
            "Trong recovery, nếu không có quyết định commit rõ ràng thì không nên giữ thay đổi của transaction.",
        )

    def _find_repairs(
        self,
        states: Dict[str, SiteState],
        decision: GlobalDecision,
    ) -> Dict[str, str]:
        """
        Xác định những site cần sửa/bổ sung log trong clean_logs.

        KEEP:
            Transaction đã COMMIT đầy đủ ở tất cả site tham gia.
            Không cần sửa clean log.

        REDO:
            Transaction đã có global COMMIT nhưng một số site chưa ghi COMMIT.
            Site READY/ACTIVE cần bổ sung COMMIT.

        UNDO:
            Transaction bị ABORT, chưa hoàn tất hoặc conflict.
            Site READY/ACTIVE cần bổ sung ABORT.

        GLOBAL CONFLICT:
            Nếu cùng transaction có cả COMMIT và ABORT ở các site khác nhau,
            site từng COMMIT cũng cần chuẩn hóa về ABORT vì project chọn UNDO an toàn.
        """

        repairs: Dict[str, str] = {}

        # KEEP: case hoàn hảo, không sửa log.
        if decision == GlobalDecision.KEEP:
            return repairs

        # UNCERTAIN: nếu giữ uncertain thì không tự ý thêm COMMIT/ABORT.
        if decision == GlobalDecision.UNCERTAIN:
            return repairs

        state_values = set(states.values())

        has_commit = SiteState.COMMITTED in state_values
        has_abort = SiteState.ABORTED in state_values

        is_global_conflict = (
            decision == GlobalDecision.UNDO
            and has_commit
            and has_abort
        )

        # REDO: bổ sung COMMIT cho site còn thiếu.
        if decision == GlobalDecision.REDO:
            for site, state in states.items():
                if state in {
                    SiteState.READY,
                    SiteState.ACTIVE,
                }:
                    repairs[site] = "COMMIT"

            return repairs

        # UNDO: bổ sung ABORT cho site còn thiếu.
        if decision == GlobalDecision.UNDO:
            for site, state in states.items():

                # Conflict như T13:
                # SITE1 COMMIT, SITE2 ABORT, SITE3 READY.
                # Vì quyết định là UNDO an toàn, site COMMIT cũng chuẩn hóa ABORT.
                if is_global_conflict:
                    if state in {
                        SiteState.COMMITTED,
                        SiteState.READY,
                        SiteState.ACTIVE,
                        SiteState.INVALID,
                    }:
                        repairs[site] = "ABORT"

                # UNDO bình thường.
                else:
                    if state in {
                        SiteState.READY,
                        SiteState.ACTIVE,
                        SiteState.INVALID,
                    }:
                        repairs[site] = "ABORT"

            return repairs

        return repairs