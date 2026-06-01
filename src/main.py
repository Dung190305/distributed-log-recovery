from __future__ import annotations

import argparse
from pathlib import Path

from database_simulator import DatabaseSimulator
from recovery_manager import RecoveryManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Distributed Log Recovery Manager - Phân tích sau crash"
    )
    parser.add_argument(
        "--init-demo",
        action="store_true",
        help="Tạo log demo và database demo trước khi chạy recovery.",
    )
    parser.add_argument(
        "--simulate-crash",
        action="store_true",
        help="Chạy mô phỏng crash, tạo dirty logs/DB, ghi crash_simulation_report.txt, rồi chạy recovery.",
    )
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Thư mục gốc của project. Mặc định là thư mục cha của src/.",
    )
    parser.add_argument("--logs", default=None, help="Đường dẫn tới thư mục logs.")
    parser.add_argument("--db", default=None, help="Đường dẫn tới file dirty_db.json.")
    parser.add_argument("--output", default=None, help="Đường dẫn tới thư mục output.")
    parser.add_argument(
        "--coordinator",
        default="SITE1",
        help="Mã site coordinator. Mặc định: SITE1.",
    )
    parser.add_argument(
        "--uncertain-policy",
        choices=["abort", "keep_uncertain"],
        default="abort",
        help="Cách xử lý transaction tất cả READY nhưng chưa có quyết định toàn cục. Mặc định: abort.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = Path(args.root).resolve()

    simulator = DatabaseSimulator(root)

    if args.simulate_crash:
        crash_report_path = simulator.simulate_crash()
        print(f"Đã mô phỏng crash xong. Báo cáo: {crash_report_path}")
    elif args.init_demo:
        simulator.create_demo_dataset()
        print(f"Đã tạo dataset demo tại: {root}")

    logs_dir = Path(args.logs).resolve() if args.logs else root / "logs"
    dirty_db_path = Path(args.db).resolve() if args.db else root / "data" / "dirty_db.json"
    output_dir = Path(args.output).resolve() if args.output else root / "output"

    manager = RecoveryManager(
        logs_dir=logs_dir,
        dirty_db_path=dirty_db_path,
        output_dir=output_dir,
        coordinator_site=args.coordinator,
        uncertain_policy=args.uncertain_policy,
    )
    result = manager.run()

    print("\nPhục hồi hoàn tất thành công.")
    print(f"Số transaction đã phân tích: {result['transactions']}")
    print(f"REDO: {', '.join(result['redo']) if result['redo'] else 'Không có'}")
    print(f"UNDO: {', '.join(result['undo']) if result['undo'] else 'Không có'}")
    print(f"UNCERTAIN: {', '.join(result['uncertain']) if result['uncertain'] else 'Không có'}")
    print(f"Database sạch: {result['clean_db_path']}")
    print(f"Báo cáo phục hồi: {result['report_path']}")
    print(f"Clean logs: {result['clean_logs_dir']}")


if __name__ == "__main__":
    main()
