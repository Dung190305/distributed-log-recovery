# Distributed Log Recovery Manager - Phân tích sau crash

Project này mô phỏng và xử lý bài toán **phục hồi log giao dịch phân tán sau khi hệ thống bị crash**. Chương trình đọc log của 3 site, phân tích trạng thái transaction theo luật **Two-Phase Commit (2PC)**, sau đó quyết định transaction nào cần **REDO**, transaction nào cần **UNDO**, và tạo ra database sạch sau recovery.

## 1. Mục tiêu của project

Project đáp ứng các yêu cầu chính của đề tài:

- Đọc dirty transaction log của 3 site: `SITE1`, `SITE2`, `SITE3`.
- Log có các bản ghi: `START`, `UPDATE`, `PREPARE`, `COMMIT`, `ABORT`.
- Phân tích trạng thái từng transaction sau crash.
- Quyết định `REDO`, `UNDO`, hoặc `UNCERTAIN` theo 2PC.
- Tạo `output/clean_db.json` là trạng thái database sạch sau phục hồi.
- Tạo `output/recovery_report.txt` bằng tiếng Việt để giải thích toàn bộ quá trình.
- Tạo `output/clean_logs/` để bổ sung các bản ghi `COMMIT` hoặc `ABORT` còn thiếu.
- Có chức năng mô phỏng crash riêng bằng lệnh `--simulate-crash`.

## 2. Cấu trúc thư mục

```txt
distributed-log-recovery/
│
├── logs/
│   ├── site1.log
│   ├── site2.log
│   └── site3.log
│
├── data/
│   ├── initial_db.json
│   └── dirty_db.json
│
├── output/
│   ├── recovery_report.txt
│   ├── crash_simulation_report.txt
│   ├── clean_db.json
│   └── clean_logs/
│       ├── site1_clean.log
│       ├── site2_clean.log
│       └── site3_clean.log
│
├── src/
│   ├── main.py
│   ├── log_parser.py
│   ├── transaction_analyzer.py
│   ├── recovery_manager.py
│   └── database_simulator.py
│
├── TEST_CASES.md
├── STATE_MACHINE.md
├── CRASH_SIMULATION.md
└── README.md
```

## 3. Cách chạy project

### Chạy mô phỏng crash và recovery

Đây là lệnh nên dùng khi demo:

```bash
python src/main.py --simulate-crash
```

Lệnh này sẽ:

1. Tạo database ban đầu `data/initial_db.json`.
2. Mô phỏng transaction chạy trên 3 site.
3. Cố tình tạo dirty log bị thiếu `COMMIT/ABORT`.
4. Tạo dirty database `data/dirty_db.json`.
5. Tạo `output/crash_simulation_report.txt`.
6. Chạy recovery.
7. Tạo `output/recovery_report.txt`, `output/clean_db.json`, `output/clean_logs/`.

### Chạy demo dataset có sẵn

```bash
python src/main.py --init-demo
```

### Chạy recovery từ log hiện tại

```bash
python src/main.py
```

Hoặc:

```bash
python src/main.py --logs logs --db data/dirty_db.json --output output
```

## 4. Format log

Mỗi dòng log có dạng:

```txt
timestamp site_id transaction_id operation details
```

Ví dụ:

```txt
001 SITE1 T1 START -
002 SITE1 T1 UPDATE A 100 150
003 SITE1 T1 PREPARE -
004 SITE1 T1 COMMIT -
```

Ý nghĩa:

- `START`: transaction bắt đầu.
- `UPDATE item before after`: cập nhật dữ liệu, có giá trị trước và sau.
- `PREPARE`: site đã sẵn sàng commit.
- `COMMIT`: transaction được commit.
- `ABORT`: transaction bị hủy.

## 5. State machine

Mỗi transaction tại mỗi site được phân loại thành một trong các trạng thái:

| State | Ý nghĩa |
|---|---|
| `NOT_FOUND` | Site không có log của transaction đó |
| `ACTIVE` | Có `START/UPDATE` nhưng chưa `PREPARE` |
| `READY` | Có `PREPARE` nhưng chưa có `COMMIT/ABORT` |
| `COMMITTED` | Có bản ghi `COMMIT` |
| `ABORTED` | Có bản ghi `ABORT` |
| `INVALID` | Một site có cả `COMMIT` và `ABORT` cho cùng transaction |

Sơ đồ:

```txt
NOT_FOUND
   |
   | START / UPDATE
   v
ACTIVE
   |
   | PREPARE
   v
READY
   |--------------------|
   |                    |
   | COMMIT             | ABORT
   v                    v
COMMITTED             ABORTED
```

## 6. Luật quyết định REDO/UNDO

| Tình huống | Quyết định |
|---|---|
| Có `COMMIT` và không có xung đột `ABORT` | `REDO` |
| Có ít nhất một site `ABORT` | `UNDO` |
| Có cả `COMMIT` và `ABORT` ở các site khác nhau | `UNDO` an toàn + báo cáo global conflict |
| Tất cả site `READY` nhưng không có quyết định cuối | `UNCERTAIN` trong 2PC thuần; project dùng timeout-abort nên `UNDO` |
| Transaction chỉ `ACTIVE`, chưa `PREPARE` | `UNDO` |
| Log cục bộ `INVALID` | `UNDO` an toàn |

## 7. REDO và UNDO hoạt động như thế nào?

Với log:

```txt
UPDATE A 100 150
```

- `REDO`: áp dụng `after_value`, tức là `A = 150`.
- `UNDO`: khôi phục `before_value`, tức là `A = 100`.

Nếu transaction có nhiều update, chương trình xử lý:

- `REDO`: theo thứ tự timestamp tăng dần.
- `UNDO`: theo thứ tự timestamp giảm dần.

Phần này được chứng minh trong `output/recovery_report.txt`, mục **Trace thao tác REDO/UNDO**.

## 8. Dataset kiểm thử

Project có 13 transaction để bao phủ nhiều tình huống:

| Transaction | Tình huống | Kết quả |
|---|---|---|
| `T1` | Cả 3 site commit đầy đủ | `REDO` |
| `T2` | Một site ABORT sau PREPARE | `UNDO` |
| `T3` | Tất cả READY nhưng thiếu quyết định cuối | `UNDO` theo timeout-abort |
| `T4` | Một site thiếu COMMIT sau global commit | `REDO` + sửa clean log |
| `T5` | Crash trước PREPARE | `UNDO` |
| `T6` | Coordinator COMMIT, participant READY | `REDO` + sửa clean log |
| `T7` | Participant ABORT sớm | `UNDO` |
| `T8` | Global commit nhưng hai site thiếu COMMIT | `REDO` + sửa clean log |
| `T9` | Trạng thái hỗn hợp ABORT/ACTIVE/READY | `UNDO` |
| `T10` | Transaction không có UPDATE | `REDO`, không đổi DB |
| `T11` | Commit với nhiều UPDATE | `REDO` |
| `T12` | ABORT với chuỗi UPDATE | `UNDO` ngược thứ tự |
| `T13` | Xung đột COMMIT/ABORT toàn cục | `UNDO` an toàn |

## 9. File output quan trọng

| File | Vai trò |
|---|---|
| `output/recovery_report.txt` | Báo cáo phục hồi chính bằng tiếng Việt |
| `output/crash_simulation_report.txt` | Báo cáo mô phỏng crash |
| `output/clean_db.json` | Database sạch sau recovery |
| `output/clean_logs/*.log` | Log sạch sau khi bổ sung COMMIT/ABORT còn thiếu |

## 10. Liên hệ lý thuyết 2PC

Project bám theo tư tưởng 2PC:

- Participant ghi `PREPARE` nghĩa là đã vào trạng thái `READY`.
- Nếu có global `COMMIT`, recovery phải `REDO` và đảm bảo các site cùng commit.
- Nếu có `ABORT`, transaction phải bị `UNDO` để tránh dữ liệu dở dang.
- Nếu tất cả site `READY` nhưng không có quyết định cuối, đây là trường hợp blocking của 2PC. Project dùng chính sách timeout-abort để tạo clean database.
- Một transaction phân tán không được vừa `COMMIT` ở site này vừa `ABORT` ở site khác. Nếu phát hiện, chương trình đánh dấu global conflict và chọn `UNDO` an toàn.

## 11. Kết quả mong đợi

Khi chạy:

```bash
python src/main.py --simulate-crash
```

Kết quả console sẽ có dạng:

```txt
Phục hồi hoàn tất thành công.
Số transaction đã phân tích: 13
REDO: T1, T10, T11, T4, T6, T8
UNDO: T12, T13, T2, T3, T5, T7, T9
UNCERTAIN: Không có
```

