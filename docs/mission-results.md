# Baseline với miền nhiệm vụ chuẩn hóa 100%

Thực hiện ngày 05/11/2026 trên SAREnv scenario 1, 256 ô, 3 UAV, deadline 600 s. Giả định đã chốt: một nạn nhân đứng yên nằm trong miền nhiệm vụ; tổng xác suất các ô trong miền bằng 1.

## Đầu vào và ý nghĩa xác suất

- Instance mới: [instance_mission.json](../data/instance_mission.json).
- Cấu hình: [pilot.json](../configs/pilot.json), `prior_mode=condition_on_crop`.
- Calibration POP giữ nguyên: [calibration_pilot_streamed.json](../data/calibration_pilot_streamed.json). Checkpoint thực tế huấn luyện **3 epoch**, q của ba cấu hình lần lượt 0,676138 / 0,786129 / 0,819126; cấu hình huấn luyện mặc định 30 epoch chưa được chạy trong lượt này.
- Giữ cùng vùng 32×32 pixel gốc, gộp thành 16×16 ô. Xác suất vùng theo heatmap gốc (`raw_crop_mass`) là **0,04247411339742076**, phần ngoài vùng (`raw_outside_probability`) là **0,9575258866025792**.
- Đặt `pi_j = raw_pi_j / raw_crop_mass`; tổng pi bằng **1**, `outside_probability=0` trong mô hình có điều kiện. `p_detect` trong CSV là xác suất dạng số trong [0,1], với điều kiện nạn nhân nằm trong miền nhiệm vụ; nhân 100 để đổi sang phần trăm.
- Với một kế hoạch, xác suất theo heatmap gốc bằng `p_detect * raw_crop_mass`. Không trộn trực tiếp các xác suất này với cột `p_detect` của pilot cũ.

## Sửa tọa độ raster

Tọa độ được tính từ `bounds` và kích thước thực của heatmap thay cho bước pixel danh nghĩa 30 m áp cho cả hai trục. Scenario 1 có kích thước pixel thực **30 × 30,0455235205 m**, tương ứng ô tìm kiếm **60 × 60,0910470410 m** (`cell_size_xy_m`). Trường `cell_size_m=60` giữ kích thước danh nghĩa để tương thích dữ liệu trước.

Chỉ chuẩn hóa xác suất trên cùng một hình học sẽ giữ nguyên mục tiêu `1-P/U`, vì P và U cùng chia cho xác suất vùng. Lượt chạy này còn sửa hình học nên kết quả hành trình, HV và IGD+ có thể khác pilot cũ. Đây không phải cải tiến NSGA-II/MOEA/D.

## Kết quả chạy lại

Population 100, 200 thế hệ gồm khởi tạo, seed 1–5. Cả hai thuật toán dùng cùng instance, quần thể đầu theo seed, decoder, toán tử và thang chuẩn hóa. Mỗi thuật toán/seed hoàn tất 20.000 đánh giá; tổng 200.000 đánh giá.

| Thuật toán | Trung bình P lớn nhất mỗi seed ± độ lệch chuẩn | HV trung bình ± độ lệch chuẩn | IGD+ trung bình ± độ lệch chuẩn |
| --- | ---: | ---: | ---: |
| NSGA-II | **17,9952% ± 0,7670 điểm phần trăm** | 0,284047 ± 0,006822 | 0,008296 ± 0,004848 |
| MOEA/D | **14,9943% ± 0,7271 điểm phần trăm** | 0,255765 ± 0,007416 | 0,021542 ± 0,004372 |

Xác suất cao nhất trong tất cả seed là 18,8262% cho NSGA-II và 15,8890% cho MOEA/D. Đây là cực đại xác suất trong archive, không phải xác suất của mọi phương án Pareto. HV dùng điểm tham chiếu (1,1; 1,1) trong không gian mục tiêu chuẩn hóa; IGD+ dùng tập tham chiếu không trội gộp thực nghiệm, không phải biên tối ưu thật.

- [CSV của 10 lượt](../results/baseline_mission_100pct/summary.csv).
- [Đồ thị Pareto và hội tụ](../results/baseline_mission_100pct/comparison.png).
- [Manifest và ý nghĩa xác suất thực tế](../results/baseline_mission_100pct/manifest.json).
- [Kiểm tra độc lập](../results/baseline_mission_100pct/audit.json).

## Kiểm tra

**14 kiểm thử qua**, gồm hồi quy cho tọa độ raster có bước X/Y khác nhau, chuẩn hóa xác suất, giữ xác suất heatmap gốc trong metadata, bảo vệ instance đã đóng băng và tính bất biến của mục tiêu chuẩn hóa khi chỉ đổi thang pi.

Đã kiểm tra độc lập **1.418 nghiệm** trong 10 archive: tính lại xác suất từ các khối pixel heatmap gốc, tính tọa độ từ bounds, tính quãng đường/thời gian/Wh từ hình học và đối chiếu JSON, CSV, NPZ. Mọi nghiệm thỏa pin, deadline và không trùng ô. Sai khác xác suất tối đa khoảng 2,78×10^-17, thời gian khoảng 2,28×10^-13 s, năng lượng khoảng 2,85×10^-14 Wh. Đã kiểm tra lại HV, IGD+, quan hệ không trội và chỉ số khởi tạo giống nhau của hai thuật toán theo seed.

Instance pilot cũ và các tệp kết quả đối chiếu trong `results/run_20261105_015625/`, `results/baseline_pilot_5seeds/` được giữ nguyên; checksum được ghi trong audit. [Báo cáo pilot cũ](pilot-results.md) lưu các xác suất theo heatmap gốc và hình học cũ.

Miền 16×16 ô vẫn là quy mô pilot. Cần thiết kế thêm miền nhiệm vụ, nhiều scenario/seed và huấn luyện detector đầy đủ trước khi suy rộng kết luận cho paper.
