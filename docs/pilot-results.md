# Kết quả baseline pilot đã chạy

> Báo cáo lịch sử: dùng `preserve_mass` và tọa độ danh nghĩa của instance cũ. Cấu hình hiện tại đã chuyển sang [miền nhiệm vụ 100% và tọa độ raster đã sửa](mission-results.md). Không đọc trực tiếp xác suất trong hai báo cáo theo cùng một điều kiện.

Thực hiện ngày 05/11/2026. Đầu vào thực: SAREnv scenario 1 và POP từ OSF. Xem [giao thức](baseline-protocol.md) để biết giả định mô hình và nguồn dữ liệu; xem [README](../README.md) để chạy terminal.

## Detector và q thực nghiệm

YOLOv8n được fine-tune **3 epoch** trên 4.721 ảnh POP thuộc F1–F10; checkpoint chọn trên F11–F12. Đo q riêng trên toàn bộ F13–F16: 2.320 ảnh, 6.546 nhãn người. Test T1–T3 chưa dùng đo hiệu năng.

| Cấu hình UAV | Độ phân giải đầu vào | Phát hiện đúng / GT | q |
| --- | ---: | ---: | ---: |
| UAV 1 | 320 | 4.426 / 6.546 | 0,676138 |
| UAV 2 | 480 | 5.146 / 6.546 | 0,786129 |
| UAV 3 | 640 | 5.362 / 6.546 | 0,819126 |

Confidence 0,25; IoU ghép nhãn 0,5; NMS IoU 0,7. Đây là recall thực đo, không phải mAP hay confidence trung bình. Ánh xạ pilot dùng q không đổi theo ô, khác nhau giữa các cấu hình xử lý của UAV.

- [Calibration và nguồn checkpoint](../data/calibration_pilot_streamed.json).
- [Instance đã đóng băng](../data/instance_pilot.json).
- Checkpoint: `D:/UAV-SAR/datasets/detector_runs/pilot_3epochs/weights/best.pt`.
- SHA-256 checkpoint: `ab0cfeb7dcff2b259cc7bc312f53ad93fe991df8a9f08f7c6fdbbcca860e08e4`.
- Training arguments và metrics: `D:/UAV-SAR/datasets/detector_runs/pilot_3epochs/args.yaml`, `results.csv`.

Khoảng bootstrap theo cảnh khá rộng: xấp xỉ [0,461; 0,815], [0,577; 0,924], [0,615; 0,950] lần lượt cho ba cấu hình. Có tương quan giữa các frame và chỉ 4 cảnh calibration; chưa dùng độ bất định này trong tối ưu.

## Kết quả tối ưu

Instance gồm 256 ô, 3 UAV, deadline 600 s. Crop giữ tổng xác suất ban đầu khoảng **0,042474**, phần còn lại vẫn nằm ngoài vùng tìm kiếm. Vì vậy xác suất nhiệm vụ nhỏ hơn nhiều so với q của detector; không đọc `P_detect = 0.008` thành 80% hoặc 8% (đó là 0,8%).

Population 100, 200 thế hệ, seed 1–5. Mỗi thuật toán/seed dùng đúng 20.000 lần đánh giá; tổng cộng **200.000** lần. Cùng instance, mã hóa, decoder, toán tử, khởi tạo theo seed và thang chuẩn hóa.

| Thuật toán | HV trung bình ± độ lệch chuẩn | IGD+ gộp trung bình ± độ lệch chuẩn | P lớn nhất mỗi seed, trung bình |
| --- | ---: | ---: | ---: |
| NSGA-II | 0,285261 ± 0,011975 | 0,014955 ± 0,008438 | 0,007948 |
| MOEA/D | 0,256789 ± 0,008553 | 0,025191 ± 0,004543 | 0,006463 |

HV lớn hơn và IGD+ nhỏ hơn là tốt hơn trong cùng chuẩn hóa và tập tham chiếu đã lưu. Bảng mô tả kết quả của pilot này; chưa có kiểm định để suy rộng rằng thuật toán nào tốt hơn nói chung. IGD+ tham chiếu front gộp thực nghiệm, không phải front tối ưu thật. Các tập Pareto chứa nhiều mức năng lượng; cột P lớn nhất không mô tả điểm cân bằng duy nhất.

- [CSV đầy đủ 10 lượt](../results/baseline_pilot_5seeds/summary.csv).
- [Đồ thị Pareto và hội tụ](../results/baseline_pilot_5seeds/comparison.png).
- [Ví dụ hành trình NSGA-II, seed 1](../results/baseline_pilot_5seeds/nsga2/seed_1/routes.png).
- [Manifest và cấu hình thực tế](../results/baseline_pilot_5seeds/manifest.json).
- [Kết quả kiểm tra độc lập](../results/baseline_pilot_5seeds/audit.json).

## Kiểm tra đã hoàn tất

11 kiểm thử qua: năng lượng Wh, chặng về, deadline, pin, nghiệm rỗng, không trùng ô giữa UAV, xác suất phân công, matching một–một, skyline, ngân sách và tái lập của cả hai thuật toán trên instance nhỏ.

Kiểm tra độc lập từ JSON đầu ra đã tính lại **1.427 nghiệm** trong 10 archive: mọi mục tiêu và thời gian/năng lượng khớp; mọi nghiệm khả thi theo mô hình; không trùng ô. Các seed của hai thuật toán có chỉ số khởi tạo giống nhau, HV archive không giảm, mọi lượt đạt đúng ngân sách. Đã đối chiếu tổng TP/GT từ CSV calibration, checksum bằng chứng detector và checksum mã nguồn của lượt chạy.

Đây là pilot với detector 3 epoch, một scenario và các giả định vật lý chưa hiệu chỉnh. Lệnh huấn luyện 30 epoch và chạy lại toàn chuỗi được cung cấp trong README; cần thí nghiệm thêm trước khi dùng làm kết luận cho paper.
