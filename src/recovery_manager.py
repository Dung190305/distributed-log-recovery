import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from log_parser import LogParser, LogRecord
from transaction_analyzer import (
    GlobalDecision,
    SiteState,
    TransactionAnalysis,
    TransactionAnalyzer,
)


@dataclass
class RecoveryResult:
    """
    Kết quả sau khi chạy recovery.

    analyses:
        Danh sách kết quả phân tích từng transaction.

    clean_db_path:
        Đường dẫn file clean_db.json.

    report_path:
        Đường dẫn file recovery_report.txt.

    clean_logs_dir:
        Đường dẫn thư mục clean_logs.
    """

    analyses: List[TransactionAnalysis]
    clean_db_path: Path
    report_path: Path
    clean_logs_dir: Path


class RecoveryManager:
    """
    Quản lý toàn bộ quá trình phục hồi sau crash.

    Luồng xử lý:
    1. Đọc dirty logs của 3 site.
    2. Phân tích transaction theo Two-Phase Commit.
    3. Đọc dirty_db.json.
    4. Tạo clean_db.json bằng KEEP/REDO/UNDO.
    5. Tạo clean logs.
    6. Tạo recovery_report.txt.
    """

    def __init__(
        self,
        logs_dir: str | Path,
        dirty_db_path: str | Path,
        output_dir: str | Path,
        coordinator_site: str = "SITE1",
        uncertain_policy: str = "abort",
    ) -> None:
        """
        Khởi tạo RecoveryManager.

        logs_dir:
            Thư mục chứa site1.log, site2.log, site3.log.

        dirty_db_path:
            File database bẩn sau crash.

        output_dir:
            Thư mục ghi output sau recovery.

        coordinator_site:
            Site coordinator giả lập, mặc định SITE1.

        uncertain_policy:
            Cách xử lý READY nhưng thiếu global decision.
            - abort: đưa về UNDO.
            - keep_uncertain: giữ UNCERTAIN.
        """

        self.logs_dir = Path(logs_dir)
        self.dirty_db_path = Path(dirty_db_path)
        self.output_dir = Path(output_dir)

        self.clean_db_path = self.output_dir / "clean_db.json"
        self.report_path = self.output_dir / "recovery_report.txt"
        self.clean_logs_dir = self.output_dir / "clean_logs"

        self.parser = LogParser()
        self.analyzer = TransactionAnalyzer(
            coordinator_site=coordinator_site,
            uncertain_policy=uncertain_policy,
        )

    def run(self) -> RecoveryResult:
        """
        Chạy toàn bộ quá trình recovery.

        Đây là hàm chính của RecoveryManager.
        """

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.clean_logs_dir.mkdir(parents=True, exist_ok=True)

        # 1. Đọc dirty logs của các site.
        site_logs = self.parser.parse_directory(self.logs_dir)

        # 2. Phân tích transaction để lấy decision: KEEP/REDO/UNDO/UNCERTAIN.
        analyses = self.analyzer.analyze(site_logs)

        # 3. Đọc dirty database.
        dirty_db = self._load_db(self.dirty_db_path)

        # 4. Tạo clean database bằng thuật toán recovery.
        clean_db = self._recover_database(
            dirty_db=dirty_db,
            site_logs=site_logs,
            analyses=analyses,
        )

        # 5. Ghi clean database.
        self._write_json(self.clean_db_path, clean_db)

        # 6. Ghi clean logs.
        self._write_clean_logs(
            site_logs=site_logs,
            analyses=analyses,
        )

        # 7. Ghi recovery report.
        self._write_report(
            report_path=self.report_path,
            site_logs=site_logs,
            analyses=analyses,
            dirty_db=dirty_db,
            clean_db=clean_db,
        )

        return RecoveryResult(
            analyses=analyses,
            clean_db_path=self.clean_db_path,
            report_path=self.report_path,
            clean_logs_dir=self.clean_logs_dir,
        )

    def _load_db(self, path: Path) -> Dict[str, int]:
        """
        Đọc database JSON từ file.

        Ví dụ:
        data/dirty_db.json
        """

        if not path.exists():
            raise FileNotFoundError(f"Không tìm thấy file database: {path}")

        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return data

    def _write_json(self, path: Path, data: Dict[str, int]) -> None:
        """
        Ghi dictionary Python ra file JSON.
        """

        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )

    def _collect_updates_by_transaction(
        self,
        site_logs: Dict[str, List[LogRecord]],
    ) -> Dict[str, List[LogRecord]]:
        """
        Gom tất cả dòng UPDATE theo transaction_id.

        Ví dụ:
        {
            "T1": [UPDATE A 100 150, UPDATE B 200 250],
            "T2": [UPDATE D 400 450]
        }
        """

        updates_by_transaction: Dict[str, List[LogRecord]] = {}

        for records in site_logs.values():
            for record in records:
                if record.operation.upper() == "UPDATE":
                    updates_by_transaction.setdefault(
                        record.transaction_id,
                        [],
                    ).append(record)

        return updates_by_transaction

    def _recover_database(
        self,
        dirty_db: Dict[str, int],
        site_logs: Dict[str, List[LogRecord]],
        analyses: List[TransactionAnalysis],
    ) -> Dict[str, int]:
        """
        Tạo clean database từ dirty database dựa trên kết quả phân tích.

        KEEP:
            Transaction đã COMMIT đầy đủ ở tất cả site.
            Đây là case hoàn hảo, không sửa database.

        REDO:
            Transaction đã có global COMMIT nhưng còn site thiếu COMMIT.
            Áp dụng after_value để đảm bảo dữ liệu commit được giữ.

        UNDO:
            Transaction ABORT, chưa hoàn tất hoặc conflict.
            Khôi phục before_value để xóa ảnh hưởng của transaction.

        UNCERTAIN:
            Chưa có quyết định rõ ràng.
            Không tự ý sửa database.
        """

        clean_db = dict(dirty_db)

        updates_by_transaction = self._collect_updates_by_transaction(site_logs)

        for analysis in analyses:
            transaction_id = analysis.transaction_id
            decision = analysis.decision
            update_records = updates_by_transaction.get(transaction_id, [])

            # 1. KEEP: transaction hoàn hảo, giữ nguyên database.
            if decision == GlobalDecision.KEEP:
                continue

            # 2. REDO: dùng after_value, chạy theo timestamp tăng dần.
            if decision == GlobalDecision.REDO:
                redo_records = sorted(
                    update_records,
                    key=lambda record: record.timestamp,
                )

                for record in redo_records:
                    if record.item is None or record.after_value is None:
                        continue

                    clean_db[record.item] = record.after_value

            # 3. UNDO: dùng before_value, chạy ngược timestamp.
            elif decision == GlobalDecision.UNDO:
                undo_records = sorted(
                    update_records,
                    key=lambda record: record.timestamp,
                    reverse=True,
                )

                for record in undo_records:
                    if record.item is None or record.before_value is None:
                        continue

                    clean_db[record.item] = record.before_value

            # 4. UNCERTAIN: không tự sửa database.
            elif decision == GlobalDecision.UNCERTAIN:
                continue

        return clean_db

    def _write_clean_logs(
        self,
        site_logs: Dict[str, List[LogRecord]],
        analyses: List[TransactionAnalysis],
    ) -> None:
        """
        Tạo clean logs sau recovery.

        KEEP:
            Transaction đã COMMIT đầy đủ, không sửa log.

        REDO:
            Site nào thiếu COMMIT sẽ được bổ sung COMMIT.

        UNDO:
            Site nào thiếu ABORT sẽ được bổ sung ABORT.

        GLOBAL CONFLICT:
            Nếu một transaction vừa có COMMIT vừa có ABORT ở các site khác nhau,
            clean log sẽ chuẩn hóa về ABORT.
        """

        self.clean_logs_dir.mkdir(parents=True, exist_ok=True)

        max_timestamp = max(
            (
                record.timestamp
                for records in site_logs.values()
                for record in records
            ),
            default=0,
        )
        next_timestamp = max_timestamp + 1

        for site_id, records in site_logs.items():
            clean_records = list(records)

            tx_ids_in_site = {
                record.transaction_id
                for record in records
            }

            for analysis in analyses:
                transaction_id = analysis.transaction_id
                decision = analysis.decision

                if transaction_id not in tx_ids_in_site:
                    continue

                # KEEP: log đã hoàn chỉnh, không cần sửa.
                if decision == GlobalDecision.KEEP:
                    continue

                # UNCERTAIN: không tự ý bổ sung COMMIT/ABORT.
                if decision == GlobalDecision.UNCERTAIN:
                    continue

                state_values = set(analysis.site_states.values())

                is_global_conflict = (
                    SiteState.COMMITTED in state_values
                    and SiteState.ABORTED in state_values
                    and decision == GlobalDecision.UNDO
                )

                repair_op = analysis.repaired_sites.get(site_id)

                # Conflict, ví dụ T13:
                # SITE1 COMMIT, SITE2 ABORT, SITE3 READY.
                # Vì quyết định là UNDO an toàn, loại bỏ COMMIT lỗi
                # rồi ghi ABORT để clean log nhất quán.
                if is_global_conflict:
                    clean_records = [
                        record
                        for record in clean_records
                        if not (
                            record.transaction_id == transaction_id
                            and record.operation.upper() == "COMMIT"
                        )
                    ]

                    has_abort = any(
                        record.transaction_id == transaction_id
                        and record.operation.upper() == "ABORT"
                        for record in clean_records
                    )

                    if not has_abort:
                        clean_records.append(
                            LogRecord(
                                timestamp=next_timestamp,
                                site_id=site_id,
                                transaction_id=transaction_id,
                                operation="ABORT",
                            )
                        )
                        next_timestamp += 1

                    continue

                # Case bình thường: bổ sung COMMIT hoặc ABORT nếu cần.
                if repair_op:
                    already_has_repair = any(
                        record.transaction_id == transaction_id
                        and record.operation.upper() == repair_op
                        for record in clean_records
                    )

                    if not already_has_repair:
                        clean_records.append(
                            LogRecord(
                                timestamp=next_timestamp,
                                site_id=site_id,
                                transaction_id=transaction_id,
                                operation=repair_op,
                            )
                        )
                        next_timestamp += 1

            clean_records.sort(key=lambda record: record.timestamp)

            output_file = self.clean_logs_dir / f"{site_id.lower()}_clean.log"

            with output_file.open("w", encoding="utf-8") as file:
                for record in clean_records:
                    file.write(record.to_log_line() + "\n")

    def _write_report(
        self,
        report_path: Path,
        site_logs: Dict[str, List[LogRecord]],
        analyses: List[TransactionAnalysis],
        dirty_db: Dict[str, int],
        clean_db: Dict[str, int],
    ) -> None:
        """
        Ghi recovery_report.txt.

        Report này dùng để chứng minh:
        - Hệ thống đọc log của 3 site.
        - Transaction được phân tích state rõ ràng.
        - Có phân biệt KEEP, REDO, UNDO, UNCERTAIN.
        - Có lý do và liên hệ 2PC.
        - Có trace REDO/UNDO.
        - Có dirty DB trước recovery và clean DB sau recovery.
        """

        report_path.parent.mkdir(parents=True, exist_ok=True)

        keep_list = [
            analysis.transaction_id
            for analysis in analyses
            if analysis.decision == GlobalDecision.KEEP
        ]

        redo_list = [
            analysis.transaction_id
            for analysis in analyses
            if analysis.decision == GlobalDecision.REDO
        ]

        undo_list = [
            analysis.transaction_id
            for analysis in analyses
            if analysis.decision == GlobalDecision.UNDO
        ]

        uncertain_list = [
            analysis.transaction_id
            for analysis in analyses
            if analysis.decision == GlobalDecision.UNCERTAIN
        ]

        updates_by_transaction = self._collect_updates_by_transaction(site_logs)

        def format_list(items: List[str]) -> str:
            if not items:
                return "Không có"
            return ", ".join(sorted(items))

        with report_path.open("w", encoding="utf-8") as file:
            file.write("BÁO CÁO PHỤC HỒI LOG PHÂN TÁN\n")
            file.write("====================================\n\n")

            file.write("1. MỤC TIÊU BÁO CÁO\n")
            file.write("------------------------------------\n")
            file.write(
                "Báo cáo này mô tả quá trình phục hồi cơ sở dữ liệu phân tán "
                "sau crash. Chương trình đọc dirty logs của 3 site, phân tích "
                "trạng thái transaction theo Two-Phase Commit, sau đó quyết định "
                "KEEP, REDO, UNDO hoặc UNCERTAIN.\n\n"
            )
            file.write(
                "KEEP nghĩa là transaction đã COMMIT đầy đủ ở các site tham gia, "
                "nên giữ nguyên kết quả.\n"
            )
            file.write(
                "REDO nghĩa là transaction đã có global COMMIT nhưng còn site/log "
                "thiếu COMMIT, nên cần hoàn tất bằng after_value.\n"
            )
            file.write(
                "UNDO nghĩa là transaction bị ABORT, chưa hoàn tất hoặc conflict, "
                "nên phải khôi phục before_value.\n\n"
            )

            file.write("2. INPUT SITES\n")
            file.write("------------------------------------\n")
            for site_id, records in sorted(site_logs.items()):
                file.write(f"- {site_id}: {len(records)} dòng log\n")
            file.write("\n")

            file.write("3. TÓM TẮT KẾT QUẢ PHỤC HỒI\n")
            file.write("------------------------------------\n")
            file.write(f"Số transaction đã phân tích: {len(analyses)}\n")
            file.write(
                f"KEEP  - Giữ nguyên transaction hoàn chỉnh: "
                f"{format_list(keep_list)}\n"
            )
            file.write(
                f"REDO  - Hoàn tất transaction có global COMMIT: "
                f"{format_list(redo_list)}\n"
            )
            file.write(
                f"UNDO  - Rollback transaction lỗi/chưa hoàn tất: "
                f"{format_list(undo_list)}\n"
            )
            file.write(
                f"UNCERTAIN - Chưa có quyết định rõ: "
                f"{format_list(uncertain_list)}\n\n"
            )

            file.write("4. PHÂN TÍCH STATE TỪNG TRANSACTION\n")
            file.write("------------------------------------\n")

            for analysis in sorted(analyses, key=lambda item: item.transaction_id):
                file.write(f"\nTransaction {analysis.transaction_id}\n")
                file.write("~" * (12 + len(analysis.transaction_id)) + "\n")

                file.write("Trạng thái tại từng site:\n")
                for site_id, state in sorted(analysis.site_states.items()):
                    file.write(f"  - {site_id}: {state.value}\n")

                file.write(f"Quyết định: {analysis.decision.value}\n")
                file.write(f"Lý do: {analysis.reason}\n")
                file.write(f"Liên hệ lý thuyết: {analysis.textbook_rule}\n")

                if analysis.repaired_sites:
                    file.write("Sửa clean log:\n")
                    for site_id, operation in sorted(
                        analysis.repaired_sites.items()
                    ):
                        file.write(
                            f"  - {site_id}: bổ sung/chuẩn hóa {operation}\n"
                        )
                else:
                    file.write("Sửa clean log: Không cần sửa\n")

            file.write("\n\n5. DIRTY DATABASE TRƯỚC RECOVERY\n")
            file.write("------------------------------------\n")
            for key, value in sorted(dirty_db.items()):
                file.write(f"{key}: {value}\n")

            file.write("\n6. CLEAN DATABASE SAU RECOVERY\n")
            file.write("------------------------------------\n")
            for key, value in sorted(clean_db.items()):
                file.write(f"{key}: {value}\n")

            file.write("\n7. THAY ĐỔI DATABASE SAU RECOVERY\n")
            file.write("------------------------------------\n")

            changed_items = []
            all_items = sorted(set(dirty_db.keys()) | set(clean_db.keys()))

            for item in all_items:
                old_value = dirty_db.get(item)
                new_value = clean_db.get(item)

                if old_value != new_value:
                    changed_items.append(item)
                    file.write(f"- {item}: {old_value} -> {new_value}\n")

            if not changed_items:
                file.write("Không có thay đổi giá trị database.\n")

            file.write("\n8. REDO/UNDO OPERATION TRACE\n")
            file.write("------------------------------------\n")

            file.write("8.1. KEEP OPERATIONS\n")
            file.write("....................................\n")
            if keep_list:
                for tx_id in sorted(keep_list):
                    file.write(
                        f"{tx_id}: transaction đã COMMIT đầy đủ, "
                        "giữ nguyên kết quả, không cần thao tác phục hồi.\n"
                    )
            else:
                file.write("Không có transaction KEEP.\n")

            file.write("\n8.2. REDO OPERATIONS\n")
            file.write("....................................\n")
            if redo_list:
                for tx_id in sorted(redo_list):
                    file.write(f"{tx_id}:\n")

                    redo_records = sorted(
                        updates_by_transaction.get(tx_id, []),
                        key=lambda record: record.timestamp,
                    )

                    if not redo_records:
                        file.write("  - Không có UPDATE để REDO.\n")

                    for record in redo_records:
                        file.write(
                            f"  - {record.site_id} {record.item}: "
                            f"{record.before_value} -> {record.after_value} "
                            f"(áp dụng after_value, ts={record.timestamp})\n"
                        )
            else:
                file.write("Không có transaction REDO.\n")

            file.write("\n8.3. UNDO OPERATIONS\n")
            file.write("....................................\n")
            if undo_list:
                for tx_id in sorted(undo_list):
                    file.write(f"{tx_id}:\n")

                    undo_records = sorted(
                        updates_by_transaction.get(tx_id, []),
                        key=lambda record: record.timestamp,
                        reverse=True,
                    )

                    if not undo_records:
                        file.write("  - Không có UPDATE để UNDO.\n")

                    for record in undo_records:
                        file.write(
                            f"  - {record.site_id} {record.item}: rollback "
                            f"{record.after_value} -> {record.before_value} "
                            f"(khôi phục before_value, ts={record.timestamp})\n"
                        )
            else:
                file.write("Không có transaction UNDO.\n")

            file.write("\n8.4. UNCERTAIN OPERATIONS\n")
            file.write("....................................\n")
            if uncertain_list:
                for tx_id in sorted(uncertain_list):
                    file.write(
                        f"{tx_id}: transaction chưa có quyết định rõ ràng, "
                        "không tự ý sửa database trong chế độ keep_uncertain.\n"
                    )
            else:
                file.write("Không có transaction UNCERTAIN.\n")

            file.write("\n9. FILE OUTPUT ĐƯỢC TẠO\n")
            file.write("------------------------------------\n")
            file.write("- output/recovery_report.txt: báo cáo phục hồi này\n")
            file.write("- output/clean_db.json: database sạch sau recovery\n")
            file.write("- output/clean_logs/site1_clean.log: clean log của SITE1\n")
            file.write("- output/clean_logs/site2_clean.log: clean log của SITE2\n")
            file.write("- output/clean_logs/site3_clean.log: clean log của SITE3\n")

            file.write("\n10. KẾT LUẬN\n")
            file.write("------------------------------------\n")
            file.write(
                "Chương trình đã thực hiện post-crash log analysis bằng cách đọc "
                "dirty logs của 3 site, phân tích state theo Two-Phase Commit, "
                "tách rõ KEEP/REDO/UNDO/UNCERTAIN, phục hồi database và tạo "
                "clean logs sau recovery.\n"
            )