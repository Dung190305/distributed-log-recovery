import argparse
from pathlib import Path

from database_simulator import DatabaseSimulator
from recovery_manager import RecoveryManager
from transaction_analyzer import GlobalDecision


def build_parser() -> argparse.ArgumentParser:
    """
    Tạo bộ đọc tham số dòng lệnh.

    Các chế độ chạy:
    --init-demo:
        Tạo dataset mẫu rồi chạy recovery.

    --simulate-crash:
        Mô phỏng trạng thái sau crash bằng dirty logs,
        sau đó chạy recovery.

    --recover:
        Chỉ chạy recovery trên logs/data hiện có.
    """

    parser = argparse.ArgumentParser(
        description="Distributed Log Recovery Manager - Post-Crash Analysis"
    )

    parser.add_argument(
        "--init-demo",
        action="store_true",
        help="Tạo dataset demo rồi chạy recovery.",
    )

    parser.add_argument(
        "--simulate-crash",
        action="store_true",
        help="Mô phỏng crash bằng dirty logs rồi chạy recovery.",
    )

    parser.add_argument(
        "--recover",
        action="store_true",
        help="Chạy recovery trên logs và dirty_db hiện có.",
    )

    parser.add_argument(
        "--uncertain-policy",
        choices=["abort", "keep_uncertain"],
        default="abort",
        help="Cách xử lý transaction READY nhưng thiếu global decision.",
    )

    return parser


def print_recovery_summary(result) -> None:
    """
    In tóm tắt kết quả recovery ra console.

    result là RecoveryResult object, không phải dictionary.
    Vì vậy phải dùng result.analyses, result.clean_db_path...
    """

    keep_list = sorted(
        analysis.transaction_id
        for analysis in result.analyses
        if analysis.decision == GlobalDecision.KEEP
    )

    redo_list = sorted(
        analysis.transaction_id
        for analysis in result.analyses
        if analysis.decision == GlobalDecision.REDO
    )

    undo_list = sorted(
        analysis.transaction_id
        for analysis in result.analyses
        if analysis.decision == GlobalDecision.UNDO
    )

    uncertain_list = sorted(
        analysis.transaction_id
        for analysis in result.analyses
        if analysis.decision == GlobalDecision.UNCERTAIN
    )

    def format_list(items):
        if not items:
            return "Không có"
        return ", ".join(items)

    print()
    print("Phục hồi hoàn tất thành công.")
    print(f"Số transaction đã phân tích: {len(result.analyses)}")
    print(f"KEEP: {format_list(keep_list)}")
    print(f"REDO: {format_list(redo_list)}")
    print(f"UNDO: {format_list(undo_list)}")
    print(f"UNCERTAIN: {format_list(uncertain_list)}")
    print(f"Database sạch: {result.clean_db_path}")
    print(f"Báo cáo phục hồi: {result.report_path}")
    print(f"Clean logs: {result.clean_logs_dir}")


def main() -> None:
    """
    Hàm chạy chính của chương trình.

    Luồng xử lý:
    1. Đọc tham số dòng lệnh.
    2. Nếu cần thì tạo/mô phỏng dataset crash.
    3. Gọi RecoveryManager để phục hồi.
    4. In tóm tắt kết quả.
    """

    parser = build_parser()
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent

    logs_dir = project_root / "logs"
    data_dir = project_root / "data"
    output_dir = project_root / "output"
    dirty_db_path = data_dir / "dirty_db.json"

    simulator = DatabaseSimulator(project_root)

    if args.init_demo:
        simulator.create_demo_dataset()
        print("Đã tạo dataset demo.")

    elif args.simulate_crash:
        crash_report_path = simulator.simulate_crash()
        print(f"Đã mô phỏng crash xong. Báo cáo: {crash_report_path}")

    elif not args.recover:
        print("Bạn chưa chọn chế độ chạy.")
        print("Gợi ý:")
        print("  python src/main.py --simulate-crash")
        print("  python src/main.py --init-demo")
        print("  python src/main.py --recover")
        return

    manager = RecoveryManager(
        logs_dir=logs_dir,
        dirty_db_path=dirty_db_path,
        output_dir=output_dir,
        coordinator_site="SITE1",
        uncertain_policy=args.uncertain_policy,
    )

    result = manager.run()

    print_recovery_summary(result)


if __name__ == "__main__":
    main()