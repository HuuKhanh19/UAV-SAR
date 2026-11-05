# Multi-UAV SAR: NSGA-II và MOEA/D

Baseline cho [bài toán](docs/baitoan.md): tối đa xác suất phát hiện một nạn nhân đứng yên **với điều kiện nạn nhân nằm trong miền nhiệm vụ**, tối thiểu năng lượng toàn kế hoạch; mỗi ô quan sát tối đa một lần, mọi UAV về căn cứ trong deadline và ngân sách pin. Tổng xác suất các ô trong miền bằng 1 (`condition_on_crop`).

**`q_kj` bắt buộc được đo bằng detector chạy trên POP.** Không có chế độ thay bằng số ngẫu nhiên, confidence hay mAP. Các lựa chọn còn mở trong bài toán được ghi rõ trong [giao thức pilot](docs/baseline-protocol.md) và [cấu hình](configs/pilot.json).

Kết quả dùng miền nhiệm vụ 100% và tọa độ raster đã sửa: [báo cáo](docs/mission-results.md), [CSV](results/baseline_mission_100pct/summary.csv), [đồ thị](results/baseline_mission_100pct/comparison.png). Cấu hình: 2 baseline × 5 seed × 20.000 đánh giá, cùng detector POP 3 epoch.

Kết quả pilot cũ dùng `preserve_mass` được giữ để đối chiếu tại [báo cáo cũ](docs/pilot-results.md); các xác suất của hai chế độ có ý nghĩa khác nhau.

## Chạy ngay từ terminal `(base)`

Toàn bộ dự án ở `D:\UAV-SAR`: mã tại thư mục gốc, dataset và detector trong `datasets/`, môi trường chạy tại `.venv/`. Không cần activate môi trường, không cài thêm vào `(base)`.

```powershell
cd D:\UAV-SAR
$py = 'D:\UAV-SAR\.venv\Scripts\python.exe'

# Dùng instance mới: tổng pi = 1, tọa độ theo bounds và kích thước heatmap.
& $py -u run.py run --instance data/instance_mission.json
```

Mặc định chạy **NSGA-II và MOEA/D, 5 seed, population 100, 200 thế hệ**: đúng 20.000 lần đánh giá cho mỗi thuật toán/seed, tính cả quần thể đầu. Đây là cấu hình pilot, chưa phải giao thức paper. Hai thuật toán chạy tuần tự, cùng instance, cùng quần thể đầu theo seed và cùng decoder.

```powershell
# Chạy nhanh để xem log và định dạng kết quả.
& $py -u run.py run --instance data/instance_mission.json --population 40 --generations 30 --seeds 1

# Chỉ chạy một baseline; chọn seed và ngân sách.
& $py -u run.py run --instance data/instance_mission.json --algorithms nsga2 --seeds 1 2 3
& $py -u run.py run --instance data/instance_mission.json --algorithms moead --seeds 1 2 3
```

Mỗi lần chạy tạo thư mục mới trong `results/`; không ghi đè kết quả cũ. Terminal in `gen`, `eval`, `archive`, `Pmax`, `HV`, thời gian. `Pmax` là xác suất cao nhất trong archive, không phải giá trị của mọi nghiệm. Nghiệm có năng lượng nhỏ nhất là toàn đội nghỉ; xem toàn bộ Pareto để chọn phương án.

`run.py run` mặc định nạp `data/instance_mission.json`. Để tạo lại từ calibration POP hiện có, chọn tên mới vì instance đã đóng băng không được ghi đè:

```powershell
& $py -u run.py instance --calibration data/calibration_pilot_streamed.json --output data/instance_mission_v2.json
```

CSV lưu xác suất dạng số trong [0,1]: `0.2` tương ứng 20%. Với instance mới, đó là xác suất có điều kiện nạn nhân trong miền nhiệm vụ. `metadata.raw_crop_mass` giữ xác suất miền trên heatmap gốc; nhân `p_detect` với giá trị này để quy về heatmap gốc. Tọa độ mới dùng kích thước pixel thực theo từng trục, được lưu trong `cell_size_xy_m`.

## Chạy lại đầy đủ từ detector

```powershell
# Tải/kiểm tra nguồn; chuyển nhãn COCO thành YOLO với split theo cảnh.
& $py -u run.py download
& $py -u run.py prepare

# Huấn luyện mới (GPU 0), không dùng tập calibration để chọn checkpoint.
& $py -u run.py train --epochs 30 --device 0

# Đo q trên toàn bộ 2.320 ảnh calibration; không dùng mAP thay q.
& $py -u run.py calibrate --output data/calibration_30epochs.json --device 0

# Đóng băng pi, q, bản đồ và thông số UAV.
& $py -u run.py instance --calibration data/calibration_30epochs.json --output data/instance_30epochs.json

# Chạy cả hai baseline.
& $py -u run.py run --instance data/instance_30epochs.json
```

Lệnh `calibrate` mặc định dùng detector vừa huấn luyện; để chọn checkpoint cũ, truyền `--weights D:/UAV-SAR/datasets/detector_runs/<run>/weights/best.pt`. File `training_manifest.json` tương ứng phải tồn tại. Chọn tên output mới nếu chạy lại calibration.

Hoặc thực hiện toàn bộ bằng một lệnh:

```powershell
& $py -u run.py pipeline --epochs 30 --device 0
```

Pipeline lưu calibration và instance trong `results/pipeline_<timestamp>_inputs/`, kết quả tối ưu trong thư mục cùng tên không có `_inputs`.

## Đọc kết quả

### Chẩn đoán để thiết kế thuật toán

Lệnh `diagnose` phân tích archive, quần thể đầu/cuối và lịch sử của một lượt baseline đã hoàn tất; đầu ra nằm trong thư mục mới. Nó kiểm tra đa dạng hành trình, hiệu lực đột biến PM, sử dụng pin/thời gian, tiết kiệm từ 2-opt và khả năng chèn thêm ô trong mức năng lượng của kế hoạch gốc. Có đối chứng tìm kiếm ngẫu nhiên với cùng ngân sách đánh giá và khởi tạo theo seed.

```powershell
# Phân tích 5 seed hiện có.
& $py -u run.py diagnose --results results/baseline_mission_100pct --output results/diagnostics_new

# Thử ngân sách gấp 5, rồi đối chiếu. Chọn tên output mới nếu đã chạy.
& $py -u run.py run --instance results/baseline_mission_100pct/instance.json --generations 1000 --seeds 1 2 3 4 5 --output results/baseline_budget_new
& $py -u run.py diagnose --results results/baseline_mission_100pct --extended-results results/baseline_budget_new --output results/diagnostics_budget_new
```

Khi so ngân sách, công cụ yêu cầu cùng instance, cặp thuật toán/seed và cấu hình; chỉ tăng số thế hệ. Lịch sử HV và xác suất tại ngân sách cũ phải được tái lập. `--mutation-repeats` mặc định 4 lần/cá thể cuối; `--probe-seed` mặc định 2026; `--skip-random` bỏ đối chứng ngẫu nhiên.

Đọc [chẩn đoán scenario hiện tại và hướng thí nghiệm tiếp theo](docs/baseline-diagnostics.md). **2-opt, chèn ô và greedy là phép thử ngoại tuyến có thêm tính toán**; kết quả của chúng giúp tìm điểm nghẽn, chưa chứng minh một thuật toán mới tốt hơn với cùng ngân sách.

Trong mỗi thư mục chạy:

| File | Nội dung |
| --- | --- |
| `summary.csv` | Mỗi thuật toán/seed: HV, IGD+ tham chiếu gộp, xác suất lớn nhất, thời gian, số đánh giá |
| `comparison.png` | Tập nghiệm hai baseline và đường hội tụ HV |
| `manifest.json`, `instance.json`, `pip-freeze.txt` | Nguồn, checksum, cấu hình thực tế, môi trường, instance đóng băng |
| `<algorithm>/seed_<n>/history.csv` | Tiến độ từng thế hệ; cập nhật ngay khi đang chạy |
| `<algorithm>/seed_<n>/pareto.csv` | Xác suất phát hiện và Wh từng nghiệm không trội đã tìm được |
| `<algorithm>/seed_<n>/routes.json` | Ô được giao, thứ tự, năng lượng, thời gian quay về của từng UAV cho từng nghiệm |
| `<algorithm>/seed_<n>/pareto.png`, `routes.png` | Pareto và một phương án gần điểm lý tưởng trong không gian đã chuẩn hóa |
| `<algorithm>/seed_<n>/archive.npz`, `final_population.npz` | Archive tất cả nghiệm đã đánh giá và quần thể cuối |
| `empirical_reference.csv` | Tập tham chiếu gộp dùng tính IGD+, **không phải Pareto front thật** |

Để xem log trong terminal thứ hai:

```powershell
Get-Content .\results\<run>\nsga2\seed_1\history.csv -Wait
```

`Ctrl+C` trong bước tối ưu lưu archive hiện có và các seed đã hoàn tất. `checkpoint_archive.npz` được lưu định kỳ, nhưng **chưa hỗ trợ resume chính xác trạng thái thuật toán**; chạy lại seed sẽ bắt đầu từ đầu. Ngắt huấn luyện tuân theo hành vi của Ultralytics, không dùng checkpoint chưa có manifest để tạo q.

## Môi trường và kiểm thử

Môi trường hiện tại được thiết lập với Python 3.13, PyTorch `2.7.1+cu128`, torchvision `0.22.1+cu128`, pymoo `0.6.1.5`, Ultralytics `8.3.228`, NumPy `2.2.6`. NumPy được cố định vì pymoo này còn dùng `row_stack`, đã bị loại khỏi NumPy mới trong `(base)`.

```powershell
# Cài lại trên máy này nếu cần; không cần chạy lại khi môi trường đã có.
powershell -ExecutionPolicy Bypass -File .\setup.ps1

& $py -m pytest -q tests
```

Môi trường dùng `--system-site-packages` để tận dụng các thư viện sẵn có, với các phiên bản cần tương thích được cài riêng trên D:. Mỗi lượt tối ưu lưu `pip-freeze.txt`. Script hỗ trợ CPU bằng `--device cpu` ở các bước detector, nhưng sẽ chậm hơn.

Nguồn gốc và giới hạn thực nghiệm: xem [baseline-protocol.md](docs/baseline-protocol.md). Lượt kiểm tra 3 epoch không thay thế huấn luyện detector hội tụ hay thí nghiệm nhiều scenario/nhiều seed để kết luận thuật toán nào tốt hơn.
