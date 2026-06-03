from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

VALID_OPERATIONS = {"START", "UPDATE", "PREPARE", "COMMIT", "ABORT"}
TERMINAL_OPERATIONS = {"COMMIT", "ABORT"}


@dataclass(frozen=True)
class LogRecord:
    """One parsed line from a site log.

    Expected formats:
      001 SITE1 T1 START -
      002 SITE1 T1 UPDATE A 100 150
      003 SITE1 T1 PREPARE -
      004 SITE1 T1 COMMIT -
    """

    timestamp: int
    site_id: str
    transaction_id: str
    operation: str
    item: Optional[str] = None
    before_value: Optional[int] = None
    after_value: Optional[int] = None
    raw_line: str = ""

    #tìm các UPDATE
    @property
    def is_update(self) -> bool:
        return self.operation == "UPDATE"

    def to_log_line(self) -> str:
        if self.operation == "UPDATE":
            return (
                f"{self.timestamp:03d} {self.site_id} {self.transaction_id} UPDATE "
                f"{self.item} {self.before_value} {self.after_value}"
            )
        return f"{self.timestamp:03d} {self.site_id} {self.transaction_id} {self.operation} -"


class LogFormatError(ValueError):
    pass


class LogParser:
    #Đọc toàn bộ thư mục logs. Mỗi file log tương ứng với một site. Trả về dict: site_id -> list of LogRecord.
    def parse_directory(self, logs_dir: str | Path) -> Dict[str, List[LogRecord]]:
        logs_path = Path(logs_dir)
        if not logs_path.exists():
            raise FileNotFoundError(f"Logs directory not found: {logs_path}")

        site_logs: Dict[str, List[LogRecord]] = {}
        #Duyệt từng file
        for log_file in sorted(logs_path.glob("*.log")):
            records = self.parse_file(log_file)
            if not records:
                continue
            site_id = records[0].site_id
            site_logs[site_id] = records

        if not site_logs:
            raise FileNotFoundError(f"No .log files found in: {logs_path}")

        return site_logs

    #Đọc một file log, trả về list of LogRecord đã được sắp xếp theo timestamp.
    def parse_file(self, log_file: str | Path) -> List[LogRecord]:
        path = Path(log_file)
        if not path.exists():
            raise FileNotFoundError(f"Log file not found: {path}")

        records: List[LogRecord] = []
        with path.open("r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                records.append(self.parse_line(stripped, path.name, line_number))

        records.sort(key=lambda r: r.timestamp)
        return records

    #Phân tích một dòng log, trả về LogRecord. Nếu định dạng không hợp lệ, raise LogFormatError với thông tin chi tiết.
    def parse_line(self, line: str, filename: str = "<memory>", line_number: int = 0) -> LogRecord:
        parts = line.split()
        if len(parts) < 5:
            raise LogFormatError(
                f"Invalid log line at {filename}:{line_number}. Expected at least 5 columns: {line}"
            )

        try:
            timestamp = int(parts[0])
        except ValueError as exc:
            raise LogFormatError(
                f"Invalid timestamp at {filename}:{line_number}: {parts[0]}"
            ) from exc

        site_id = parts[1].upper()
        transaction_id = parts[2].upper()
        operation = parts[3].upper()

        if operation not in VALID_OPERATIONS:
            raise LogFormatError(
                f"Invalid operation at {filename}:{line_number}: {operation}. "
                f"Valid operations: {sorted(VALID_OPERATIONS)}"
            )

        if operation == "UPDATE":
            if len(parts) != 7:
                raise LogFormatError(
                    f"UPDATE line must have 7 columns at {filename}:{line_number}: {line}"
                )
            item = parts[4]
            try:
                before_value = int(parts[5])
                after_value = int(parts[6])
            except ValueError as exc:
                raise LogFormatError(
                    f"UPDATE before/after values must be integers at {filename}:{line_number}: {line}"
                ) from exc
            return LogRecord(
                timestamp=timestamp,
                site_id=site_id,
                transaction_id=transaction_id,
                operation=operation,
                item=item,
                before_value=before_value,
                after_value=after_value,
                raw_line=line,
            )

        return LogRecord(
            timestamp=timestamp,
            site_id=site_id,
            transaction_id=transaction_id,
            operation=operation,
            raw_line=line,
        )


def group_by_transaction(site_logs: Dict[str, List[LogRecord]]) -> Dict[str, Dict[str, List[LogRecord]]]:
    """Return: transaction_id -> site_id -> records."""
    grouped: Dict[str, Dict[str, List[LogRecord]]] = {}
    for site_id, records in site_logs.items():
        for record in records:
            grouped.setdefault(record.transaction_id, {}).setdefault(site_id, []).append(record)

    for site_map in grouped.values():
        for records in site_map.values():
            records.sort(key=lambda r: r.timestamp)
    return grouped
