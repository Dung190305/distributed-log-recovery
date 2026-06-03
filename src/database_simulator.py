from __future__ import annotations

import json
from pathlib import Path


class DatabaseSimulator:

    #khởi tạo đường dẫn làm việc
    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root)
        self.logs_dir = self.root / "logs"
        self.data_dir = self.root / "data"
        self.output_dir = self.root / "output"

    def create_demo_dataset(self) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "clean_logs").mkdir(parents=True, exist_ok=True)

        # Initial database before transactions started.
        initial_db = {
            "A": 100,
            "B": 200,
            "C": 300,
            "D": 400,
            "E": 500,
            "F": 600,
            "G": 700,
            "H": 800,
            "I": 900,
            "J": 1000,
            "K": 1100,
            "L": 1200,
            "M": 1300,
            "N": 1400,
            "O": 1500,
            "P": 1600,
            "Q": 1700,
            "R": 1800,
            "S": 1900,
            "T": 2000,
            "U": 2100,
            "V": 2200,
        }

       
        dirty_db = {
            "A": 150,  
            "B": 250,   
            "C": 350,   
            "D": 450,   
            "E": 550,   
            "F": 650,   
            "G": 750,   
            "H": 999,   
            "I": 950,   
            "J": 1050,  
            "K": 1150, 
            "L": 1250,  
            "M": 1350,  
            "N": 1450,  
            "O": 1550,  
            "P": 1650,  
            "Q": 1750,  
            "R": 1880,  
            "S": 1950,  
            "T": 2300,  
            "U": 2150,  
            "V": 2250,  
        }

        self._write_json(self.data_dir / "initial_db.json", initial_db)
        self._write_json(self.data_dir / "dirty_db.json", dirty_db)

        
        site1_log = """001 SITE1 T1 START -
002 SITE1 T1 UPDATE A 100 150
003 SITE1 T1 PREPARE -
004 SITE1 T1 COMMIT -

013 SITE1 T2 START -
014 SITE1 T2 UPDATE D 400 450
015 SITE1 T2 PREPARE -

023 SITE1 T3 START -
024 SITE1 T3 UPDATE F 600 650
025 SITE1 T3 PREPARE -

033 SITE1 T4 START -
034 SITE1 T4 PREPARE -
035 SITE1 T4 COMMIT -

043 SITE1 T5 START -
044 SITE1 T5 UPDATE H 800 999

050 SITE1 T6 START -
051 SITE1 T6 UPDATE I 900 950
052 SITE1 T6 PREPARE -
053 SITE1 T6 COMMIT -

063 SITE1 T7 START -
064 SITE1 T7 UPDATE K 1100 1150
065 SITE1 T7 PREPARE -

073 SITE1 T8 START -
074 SITE1 T8 UPDATE M 1300 1350
075 SITE1 T8 PREPARE -
076 SITE1 T8 COMMIT -

086 SITE1 T9 START -
087 SITE1 T9 UPDATE P 1600 1650
088 SITE1 T9 PREPARE -
089 SITE1 T9 ABORT -

098 SITE1 T10 START -
099 SITE1 T10 PREPARE -
100 SITE1 T10 COMMIT -

107 SITE1 T11 START -
108 SITE1 T11 UPDATE R 1800 1850
109 SITE1 T11 PREPARE -
110 SITE1 T11 COMMIT -

120 SITE1 T12 START -
121 SITE1 T12 UPDATE T 2000 2100
122 SITE1 T12 PREPARE -

130 SITE1 T13 START -
131 SITE1 T13 UPDATE U 2100 2150
132 SITE1 T13 PREPARE -
133 SITE1 T13 COMMIT -
"""

        site2_log = """005 SITE2 T1 START -
006 SITE2 T1 UPDATE B 200 250
007 SITE2 T1 PREPARE -
008 SITE2 T1 COMMIT -

016 SITE2 T2 START -
017 SITE2 T2 UPDATE E 500 550
018 SITE2 T2 PREPARE -
019 SITE2 T2 ABORT -

026 SITE2 T3 START -
027 SITE2 T3 PREPARE -

036 SITE2 T4 START -
037 SITE2 T4 PREPARE -
038 SITE2 T4 COMMIT -

045 SITE2 T5 START -

054 SITE2 T6 START -
055 SITE2 T6 UPDATE J 1000 1050
056 SITE2 T6 PREPARE -

066 SITE2 T7 START -
067 SITE2 T7 ABORT -

077 SITE2 T8 START -
078 SITE2 T8 UPDATE N 1400 1450
079 SITE2 T8 PREPARE -

090 SITE2 T9 START -
091 SITE2 T9 UPDATE Q 1700 1750

101 SITE2 T10 START -
102 SITE2 T10 PREPARE -
103 SITE2 T10 COMMIT -

111 SITE2 T11 START -
112 SITE2 T11 UPDATE S 1900 1950
113 SITE2 T11 PREPARE -
114 SITE2 T11 COMMIT -

123 SITE2 T12 START -
124 SITE2 T12 UPDATE T 2100 2200
125 SITE2 T12 PREPARE -

134 SITE2 T13 START -
135 SITE2 T13 UPDATE V 2200 2250
136 SITE2 T13 PREPARE -
137 SITE2 T13 ABORT -
"""

        site3_log = """009 SITE3 T1 START -
010 SITE3 T1 UPDATE C 300 350
011 SITE3 T1 PREPARE -
012 SITE3 T1 COMMIT -

020 SITE3 T2 START -
021 SITE3 T2 PREPARE -

028 SITE3 T3 START -
029 SITE3 T3 PREPARE -

039 SITE3 T4 START -
040 SITE3 T4 UPDATE G 700 750
041 SITE3 T4 PREPARE -

046 SITE3 T5 START -

057 SITE3 T6 START -
058 SITE3 T6 PREPARE -

068 SITE3 T7 START -
069 SITE3 T7 UPDATE L 1200 1250
070 SITE3 T7 PREPARE -

080 SITE3 T8 START -
081 SITE3 T8 UPDATE O 1500 1550
082 SITE3 T8 PREPARE -

092 SITE3 T9 START -
093 SITE3 T9 PREPARE -

104 SITE3 T10 START -
105 SITE3 T10 PREPARE -
106 SITE3 T10 COMMIT -

115 SITE3 T11 START -
116 SITE3 T11 UPDATE R 1850 1880
117 SITE3 T11 PREPARE -
118 SITE3 T11 COMMIT -

126 SITE3 T12 START -
127 SITE3 T12 UPDATE T 2200 2300
128 SITE3 T12 PREPARE -
129 SITE3 T12 ABORT -

138 SITE3 T13 START -
139 SITE3 T13 PREPARE -
"""

        (self.logs_dir / "site1.log").write_text(site1_log, encoding="utf-8")
        (self.logs_dir / "site2.log").write_text(site2_log, encoding="utf-8")
        (self.logs_dir / "site3.log").write_text(site3_log, encoding="utf-8")


    def simulate_crash(self) -> Path:
        """Run a runtime-style crash simulation for presentation.

        This method intentionally creates the same rich dirty dataset as the demo,
        but it also writes a separate crash_simulation_report.txt explaining the
        simulated execution timeline: transactions run, site logs are written,
        crash points occur, and recovery will later analyze the incomplete logs.

        The simulator follows a STEAL-like assumption for demonstration: some
        uncommitted updates may already appear in dirty_db.json when the crash
        happens, therefore UNDO must restore before_value values.
        """
        self.create_demo_dataset()
        initial_db_path = self.data_dir / "initial_db.json"
        dirty_db_path = self.data_dir / "dirty_db.json"
        with initial_db_path.open("r", encoding="utf-8") as f:
            dirty_db = json.load(f)

        update_events = []
        for log_file in sorted(self.logs_dir.glob("*.log")):
            for raw_line in log_file.read_text(encoding="utf-8").splitlines():
                parts = raw_line.split()
                if len(parts) == 7 and parts[3].upper() == "UPDATE":
                    timestamp = int(parts[0])
                    item = parts[4]
                    after_value = int(parts[6])
                    update_events.append((timestamp, item, after_value))

        for _timestamp, item, after_value in sorted(update_events):
            dirty_db[item] = after_value
        self._write_json(dirty_db_path, dirty_db)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.output_dir / "crash_simulation_report.txt"

        scenarios = [
            (
                "T1",
                "Transaction phân tán thành công bình thường",
                "Cả ba participant ghi START, UPDATE, PREPARE và COMMIT trước khi crash.",
                "Kết quả mong đợi: REDO vì mọi site đã đạt COMMIT.",
            ),
            (
                "T2",
                "Một participant ABORT sau PREPARE",
                "SITE2 ghi ABORT sau PREPARE, còn SITE1 và SITE3 chưa có quyết định kết thúc vì crash làm gián đoạn quá trình lan truyền quyết định.",
                "Kết quả mong đợi: UNDO vì một quyết định/vote abort sẽ ngăn global commit trong 2PC.",
            ),
            (
                "T3",
                "Trường hợp blocking kinh điển của 2PC",
                "Tất cả site đã PREPARE/READY, nhưng crash xảy ra trước khi có bản ghi COMMIT hoặc ABORT toàn cục.",
                "Kết quả mong đợi: trong 2PC thuần là UNCERTAIN; project này dùng timeout-abort policy nên áp dụng UNDO để tạo trạng thái sạch.",
            ),
            (
                "T4",
                "Participant mất bản ghi COMMIT cuối",
                "SITE1 và SITE2 đã ghi COMMIT, nhưng SITE3 crash ngay sau PREPARE nên bị thiếu thông điệp/bản ghi COMMIT cuối.",
                "Kết quả mong đợi: REDO và bổ sung COMMIT vào clean log của SITE3.",
            ),
            (
                "T5",
                "Crash trước PREPARE",
                "Transaction đã START và cập nhật một phần dữ liệu, nhưng chưa participant nào đạt PREPARE.",
                "Kết quả mong đợi: UNDO vì transaction chưa bao giờ sẵn sàng commit.",
            ),
            (
                "T6",
                "Coordinator đã commit trong khi participant vẫn READY",
                "SITE1 ghi COMMIT, sau đó SITE2 và SITE3 crash khi vẫn ở trạng thái READY.",
                "Kết quả mong đợi: REDO và bổ sung COMMIT vào clean log của các participant.",
            ),
            (
                "T7",
                "Participant ABORT sớm",
                "SITE2 ghi ABORT trước PREPARE; các site khác có công việc đang dở hoặc READY.",
                "Kết quả mong đợi: UNDO vì một vote/quyết định abort sẽ chặn global commit.",
            ),
            (
                "T8",
                "Đã biết global commit nhưng hai participant thiếu COMMIT",
                "SITE1 ghi COMMIT, trong khi SITE2 và SITE3 crash sau PREPARE trước khi nhận/ghi COMMIT.",
                "Kết quả mong đợi: REDO và bổ sung COMMIT vào clean log của SITE2 và SITE3.",
            ),
            (
                "T9",
                "Trạng thái hỗn hợp ABORT-ACTIVE-READY",
                "SITE1 ghi ABORT, SITE2 chỉ ACTIVE, và SITE3 READY khi crash xảy ra.",
                "Kết quả mong đợi: UNDO và sửa các log chưa hoàn chỉnh bằng ABORT.",
            ),
            (
                "T10",
                "Transaction chỉ đọc/không có UPDATE",
                "Tất cả site commit, nhưng không có bản ghi UPDATE.",
                "Kết quả mong đợi: quyết định REDO nhưng giá trị database không thay đổi.",
            ),
            (
                "T11",
                "Transaction commit có nhiều UPDATE",
                "Nhiều site cập nhật dữ liệu và tất cả site commit trước crash.",
                "Kết quả mong đợi: REDO theo thứ tự timestamp tăng dần.",
            ),
            (
                "T12",
                "Chuỗi UPDATE bị ABORT",
                "Cùng một item được cập nhật nhiều lần qua các site, sau đó SITE3 ghi ABORT còn các site khác vẫn READY.",
                "Kết quả mong đợi: UNDO theo thứ tự timestamp giảm dần để khôi phục giá trị ban đầu.",
            ),
            (
                "T13",
                "Tình huống xung đột toàn cục không hợp lệ",
                "SITE1 ghi COMMIT trong khi SITE2 ghi ABORT cho cùng transaction; đây là lỗi cố ý để kiểm thử phát hiện vi phạm atomicity của 2PC.",
                "Kết quả mong đợi: đánh dấu xung đột toàn cục, chọn UNDO an toàn và báo cáo vi phạm.",
            ),
        ]

        with report_path.open("w", encoding="utf-8") as f:
            f.write("BÁO CÁO MÔ PHỎNG CRASH\n")
            f.write("=======================\n\n")
            f.write("Lệnh chạy: python src/main.py --simulate-crash\n")
            f.write("Mục đích: tạo dirty logs và dirty database giống như hệ thống phân tán bị crash trong quá trình chạy 2PC.\n\n")
            f.write("Mô hình mô phỏng\n")
            f.write("----------------\n")
            f.write("1. Bắt đầu từ data/initial_db.json.\n")
            f.write("2. Mô phỏng các transaction phân tán trên SITE1, SITE2 và SITE3.\n")
            f.write("3. Ghi các bản ghi START, UPDATE, PREPARE, COMMIT và ABORT vào log của từng site.\n")
            f.write("4. Cố tình dừng một số transaction trước bản ghi kết thúc để mô phỏng dirty log sau crash.\n")
            f.write("5. Replay các bản ghi UPDATE vào data/dirty_db.json để mô phỏng dirty pages sau crash.\n")
            f.write("6. Recovery manager đọc các file này và tạo output/clean_db.json, output/recovery_report.txt và output/clean_logs/.\n\n")
            f.write("Các tình huống crash được tạo\n")
            f.write("---------------------\n")
            for tx_id, title, crash_point, expected in scenarios:
                f.write(f"\n{tx_id} - {title}\n")
                f.write(f"  Điểm crash: {crash_point}\n")
                f.write(f"  {expected}\n")

            f.write("\nCác file được tạo\n")
            f.write("---------------\n")
            f.write("- logs/site1.log\n")
            f.write("- logs/site2.log\n")
            f.write("- logs/site3.log\n")
            f.write("- data/initial_db.json\n")
            f.write("- data/dirty_db.json\n")
            f.write("\nBáo cáo mô phỏng riêng này chứng minh dirty dataset không phải tạo ngẫu nhiên; mỗi log thiếu kết thúc đều gắn với một tình huống crash có chủ đích.\n")

        return report_path

    def _write_json(self, path: Path, data: dict) -> None:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
