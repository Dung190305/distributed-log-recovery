from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from log_parser import LogRecord, LogParser, group_by_transaction
from transaction_analyzer import GlobalDecision, SiteState, TransactionAnalysis, TransactionAnalyzer


class RecoveryManager:
    def __init__(
        self,
        logs_dir: str | Path,
        dirty_db_path: str | Path,
        output_dir: str | Path,
        coordinator_site: str = "SITE1",
        uncertain_policy: str = "abort",
    ) -> None:
        self.logs_dir = Path(logs_dir)
        self.dirty_db_path = Path(dirty_db_path)
        self.output_dir = Path(output_dir)
        self.clean_logs_dir = self.output_dir / "clean_logs"
        self.parser = LogParser()
        self.analyzer = TransactionAnalyzer(
            coordinator_site=coordinator_site,
            uncertain_policy=uncertain_policy,
        )

    def run(self) -> Dict[str, object]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.clean_logs_dir.mkdir(parents=True, exist_ok=True)

        site_logs = self.parser.parse_directory(self.logs_dir)
        analyses = self.analyzer.analyze(site_logs)
        dirty_db = self._load_db(self.dirty_db_path)
        clean_db = self._recover_database(dirty_db, site_logs, analyses)

        clean_db_path = self.output_dir / "clean_db.json"
        report_path = self.output_dir / "recovery_report.txt"

        self._write_json(clean_db_path, clean_db)
        self._write_clean_logs(site_logs, analyses)
        self._write_report(report_path, site_logs, analyses, dirty_db, clean_db)

        return {
            "transactions": len(analyses),
            "redo": [a.transaction_id for a in analyses if a.decision == GlobalDecision.REDO],
            "undo": [a.transaction_id for a in analyses if a.decision == GlobalDecision.UNDO],
            "uncertain": [a.transaction_id for a in analyses if a.decision == GlobalDecision.UNCERTAIN],
            "clean_db_path": str(clean_db_path),
            "report_path": str(report_path),
            "clean_logs_dir": str(self.clean_logs_dir),
        }

    def _load_db(self, path: Path) -> Dict[str, int]:
        if not path.exists():
            raise FileNotFoundError(f"Không tìm thấy file database: {path}")
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Database JSON must be an object, e.g. {\"A\": 100}")
        return {str(k): int(v) for k, v in data.items()}

    def _write_json(self, path: Path, data: Dict[str, int]) -> None:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)

    def _recover_database(
        self,
        dirty_db: Dict[str, int],
        site_logs: Dict[str, List[LogRecord]],
        analyses: List[TransactionAnalysis],
    ) -> Dict[str, int]:
        db = dict(dirty_db)
        grouped = group_by_transaction(site_logs)
        decision_by_tx = {a.transaction_id: a.decision for a in analyses}

        # Redo in chronological order, undo in reverse chronological order.
        redo_records: List[LogRecord] = []
        undo_records: List[LogRecord] = []

        for tx_id, site_records in grouped.items():
            updates = [r for records in site_records.values() for r in records if r.is_update]
            if decision_by_tx[tx_id] == GlobalDecision.REDO:
                redo_records.extend(updates)
            elif decision_by_tx[tx_id] == GlobalDecision.UNDO:
                undo_records.extend(updates)

        for record in sorted(redo_records, key=lambda r: r.timestamp):
            if record.item is not None and record.after_value is not None:
                db[record.item] = record.after_value

        for record in sorted(undo_records, key=lambda r: r.timestamp, reverse=True):
            if record.item is not None and record.before_value is not None:
                db[record.item] = record.before_value

        return db


    def _build_operation_trace(
        self,
        site_logs: Dict[str, List[LogRecord]],
        analyses: List[TransactionAnalysis],
    ) -> Dict[str, Dict[str, List[str]]]:
        """Build a human-readable REDO/UNDO trace for the recovery report.

        REDO uses after_value and is shown in chronological order.
        UNDO uses before_value and is shown in reverse chronological order,
        which is important when one transaction updates the same item multiple times.
        """
        grouped = group_by_transaction(site_logs)
        decision_by_tx = {a.transaction_id: a.decision for a in analyses}

        trace: Dict[str, Dict[str, List[str]]] = {"REDO": {}, "UNDO": {}}

        for tx_id in sorted(grouped.keys()):
            site_records = grouped[tx_id]
            updates = [
                r
                for records in site_records.values()
                for r in records
                if r.is_update
            ]

            decision = decision_by_tx.get(tx_id)
            if decision == GlobalDecision.REDO:
                ordered_updates = sorted(updates, key=lambda r: r.timestamp)
                trace["REDO"][tx_id] = [
                    f"{r.site_id} {r.item}: {r.before_value} -> {r.after_value} "
                    f"(áp dụng after_value, timestamp={r.timestamp})"
                    for r in ordered_updates
                    if r.item is not None
                ]
            elif decision == GlobalDecision.UNDO:
                ordered_updates = sorted(updates, key=lambda r: r.timestamp, reverse=True)
                trace["UNDO"][tx_id] = [
                    f"{r.site_id} {r.item}: rollback {r.after_value} -> {r.before_value} "
                    f"(khôi phục before_value, timestamp={r.timestamp})"
                    for r in ordered_updates
                    if r.item is not None
                ]

        return trace

    def _write_clean_logs(self,
    site_logs: Dict[str, List[LogRecord]],
    analyses: List[TransactionAnalysis],
) -> None:
        max_timestamp = max(
            (r.timestamp for records in site_logs.values() for r in records),
            default=0,
        )
        next_timestamp = max_timestamp + 1

        for site_id, records in site_logs.items():
            clean_records = list(records)
            tx_ids_in_site = {r.transaction_id for r in records}

            for analysis in analyses:
                if analysis.transaction_id not in tx_ids_in_site:
                    continue

                states = set(analysis.site_states.values())
                is_global_conflict = (
                    SiteState.COMMITTED in states
                    and SiteState.ABORTED in states
                    and analysis.decision == GlobalDecision.UNDO
                )

                repair_op = analysis.repaired_sites.get(site_id)

                # Nếu là conflict COMMIT/ABORT và site hiện tại từng ghi COMMIT,
                # clean log cần bỏ COMMIT cũ để chuẩn hóa về ABORT.
                if is_global_conflict and repair_op == "ABORT":
                    clean_records = [
                        r for r in clean_records
                        if not (
                            r.transaction_id == analysis.transaction_id
                            and r.operation == "COMMIT"
                        )
                    ]

                if repair_op:
                    clean_records.append(
                        LogRecord(
                            timestamp=next_timestamp,
                            site_id=site_id,
                            transaction_id=analysis.transaction_id,
                            operation=repair_op,
                        )
                    )
                    next_timestamp += 1

            clean_records.sort(key=lambda r: r.timestamp)
            output_file = self.clean_logs_dir / f"{site_id.lower()}_clean.log"

            with output_file.open("w", encoding="utf-8") as f:
                for record in clean_records:
                    f.write(record.to_log_line() + "\n")
    def _write_report(
        self,
        report_path: Path,
        site_logs: Dict[str, List[LogRecord]],
        analyses: List[TransactionAnalysis],
        dirty_db: Dict[str, int],
        clean_db: Dict[str, int],
    ) -> None:
        redo = [a.transaction_id for a in analyses if a.decision == GlobalDecision.REDO]
        undo = [a.transaction_id for a in analyses if a.decision == GlobalDecision.UNDO]
        uncertain = [a.transaction_id for a in analyses if a.decision == GlobalDecision.UNCERTAIN]

        with report_path.open("w", encoding="utf-8") as f:
            f.write("BÁO CÁO PHỤC HỒI LOG PHÂN TÁN\n")
            f.write("================================\n\n")
            f.write("Dự án: Distributed Log Recovery Manager - Phân tích sau crash\n")
            f.write("Giao thức nền tảng: Phục hồi dựa trên Two-Phase Commit (2PC)\n")
            f.write("Giả định coordinator: SITE1\n\n")

            f.write("1. Các site đầu vào\n")
            for site_id in sorted(site_logs.keys()):
                f.write(f"- {site_id}: {len(site_logs[site_id])} bản ghi log\n")
            f.write("\n")

            f.write("2. Phân tích trạng thái transaction\n")
            f.write("-----------------------------\n")
            for a in analyses:
                f.write(f"\nTransaction {a.transaction_id}\n")
                for site_id, state in sorted(a.site_states.items()):
                    f.write(f"  {site_id}: {state.value}\n")
                f.write(f"  Quyết định: {a.decision.value}\n")
                f.write(f"  Lý do: {a.reason}\n")
                f.write(f"  Liên hệ lý thuyết 2PC: {a.textbook_rule}\n")
                if a.repaired_sites:
                    f.write("  Sửa clean log:\n")
                    for site_id, op in sorted(a.repaired_sites.items()):
                        f.write(f"    - {site_id}: bổ sung {op}\n")

            f.write("\n\n3. Tóm tắt phục hồi\n")
            f.write("-------------------\n")
            f.write(f"DANH SÁCH REDO: {', '.join(redo) if redo else 'Không có'}\n")
            f.write(f"DANH SÁCH UNDO: {', '.join(undo) if undo else 'Không có'}\n")
            f.write(f"DANH SÁCH UNCERTAIN: {', '.join(uncertain) if uncertain else 'Không có'}\n")

            f.write("\n4. Database trước phục hồi (Dirty DB)\n")
            f.write(json.dumps(dirty_db, indent=2, ensure_ascii=False, sort_keys=True))
            f.write("\n\n5. Database sau phục hồi (Clean DB)\n")
            f.write(json.dumps(clean_db, indent=2, ensure_ascii=False, sort_keys=True))
            f.write("\n\n6. Trace thao tác REDO/UNDO\n")
            f.write("----------------------------\n")
            operation_trace = self._build_operation_trace(site_logs, analyses)

            f.write("\nTHAO TÁC REDO:\n")
            if not any(operation_trace["REDO"].values()):
                f.write("- Không có\n")
            else:
                for tx_id, lines in operation_trace["REDO"].items():
                    if not lines:
                        f.write(f"{tx_id}: không có bản ghi UPDATE; quyết định là REDO nhưng giá trị database không thay đổi.\n")
                        continue
                    f.write(f"{tx_id}:\n")
                    for line in lines:
                        f.write(f"- {line}\n")

            f.write("\nTHAO TÁC UNDO:\n")
            if not any(operation_trace["UNDO"].values()):
                f.write("- Không có\n")
            else:
                for tx_id, lines in operation_trace["UNDO"].items():
                    if not lines:
                        f.write(f"{tx_id}: không có bản ghi UPDATE; quyết định là UNDO nhưng giá trị database không thay đổi.\n")
                        continue
                    f.write(f"{tx_id}:\n")
                    for line in lines:
                        f.write(f"- {line}\n")

            f.write("\nGiải thích trace:\n")
            f.write("- REDO áp dụng after_value theo thứ tự timestamp tăng dần.\n")
            f.write("- UNDO khôi phục before_value theo thứ tự timestamp giảm dần.\n")
            f.write("- Phần này chứng minh chương trình phục hồi dữ liệu thật, không chỉ phân loại transaction.\n")

            f.write("\n7. Các file được tạo\n")
            f.write("- output/clean_db.json\n")
            f.write("- output/recovery_report.txt\n")
            f.write("- output/clean_logs/\n")
            if (self.output_dir / "crash_simulation_report.txt").exists():
                f.write("- output/crash_simulation_report.txt\n")
