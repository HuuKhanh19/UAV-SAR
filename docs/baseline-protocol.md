# Giao thức triển khai baseline pilot

Đọc cùng [baitoan.md](baitoan.md). Đây là cấu hình triển khai để chạy được pipeline thực nghiệm, không biến các câu hỏi còn mở trong bản thảo thành quyết định nghiên cứu cuối cùng.

**Đã chốt:** chuẩn hóa miền nhiệm vụ lên 100% (`condition_on_crop`), với giả định nạn nhân nằm trong miền đó. Instance hiện tại là `data/instance_mission.json`; `data/instance_pilot.json` giữ nguyên dữ liệu pilot cũ dùng `preserve_mass`.

## Đối chiếu slide

- Chương 1–2: mã hóa phải thể hiện chọn ô, UAV và thứ tự. Dùng 3N random keys: N khóa chọn/bỏ, N khóa phân công UAV, N khóa sắp thứ tự. Bất kỳ tập hành trình khả thi nào của mô hình 2D hiện tại đều có thể biểu diễn.
- Chương 10: NSGA-II dùng non-dominated sorting và crowding distance; MOEA/D dùng trọng số đều trên simplex hai chiều, hàng xóm Euclid và Tchebycheff. Dùng triển khai pymoo đã cố định phiên bản.
- Chương 6: nhiều UAV là nhiều tác nhân trong một bài toán đa mục tiêu; không phải nhiều nhiệm vụ tối ưu độc lập của MFEA.
- Các slide hiện có là Markdown trong `docs/`; không tìm thấy PDF “Đề xuất bài toán UAV cứu hộ.pdf” hoặc `research-energy-deadline.md` được nhắc trong bản thảo.

## Nguồn dữ liệu

1. [SAREnv chính thức](https://github.com/namurproject/SAREnv), commit `0f2d344d17c0b9c18cec2176dd9b171beba727d6`, clone ở `D:/UAV-SAR/datasets/SAREnv`. Dùng scenario `1`, `heatmap.npy` và `features.geojson` thực. GeoJSON được tải qua Git LFS; các scenario chưa dùng có thể vẫn là LFS pointer. Không cần tải mọi GeoJSON để chạy scenario 1.
2. [Bài báo POP](https://pmc.ncbi.nlm.nih.gov/articles/PMC11840078/) dẫn tới [OSF KMCVA](https://osf.io/kmcva/), DOI `10.17605/OSF.IO/KMCVA`. File `POP.zip`: 643.136.554 byte, SHA-256 `14e7c4ddffe6555de1da9033217a7d95981fa1bc63f9cd6a514c348e593741cf`. Đây là dữ liệu tải từ OSF, không phải Git repository.
3. `D:/UAV-SAR/datasets/sources.json` lưu URL, commit, metadata OSF và checksum. Giữ nguyên dữ liệu gốc, nhãn chuyển đổi ở `D:/UAV-SAR/datasets/pop_yolo`.

## Detector và q

Detector: YOLOv8n, khởi tạo bằng checkpoint COCO chính thức, fine-tune trên POP. Triển khai qua [Ultralytics train](https://docs.ultralytics.com/modes/train/) và [predict](https://docs.ultralytics.com/modes/predict/). Checkpoint, seed, epoch, split, phiên bản và SHA-256 được lưu.

Chia tập theo scene ID:

| Vai trò | Cảnh | Ảnh | Nhãn người |
| --- | --- | ---: | ---: |
| Train | F1–F10 | 4.721 | 16.082 |
| Chọn checkpoint | F11–F12 | 827 | 2.343 |
| Ước lượng q | F13–F16 | 2.320 | 6.546 |
| Test giữ lại | T1–T3 | 900 | 1.840 |

Đây là tách thêm hai cảnh từ train chính thức để không dùng validation chính thức vừa chọn checkpoint vừa đo q. Có kiểm tra scene không giao nhau và SHA-256 ảnh không trùng giữa các tập; chưa xác minh trùng gần hoặc trùng người giữa các cảnh. Nhãn COCO thực tế có trường `area` không phản ánh diện tích bbox, nên dùng tọa độ bbox, không dùng trường `area`.

Mỗi UAV dùng cùng checkpoint nhưng `imgsz` lần lượt 320, 480, 640. Đây là khác biệt cấu hình xử lý ảnh, **không phải bằng chứng về ba loại cảm biến vật lý**. Confidence = 0,25, NMS IoU = 0,7, IoU ghép nhãn = 0,5. Ghép prediction theo confidence giảm dần, một prediction–một GT; prediction trùng được tính FP, không đếm người hai lần.

`q_k = số GT được phát hiện đúng / tổng GT`. Tổng số mẫu dùng làm mẫu số là số người được gán nhãn, không phải số ảnh. Lưu prediction thô, TP/GT/FP theo ảnh, độ cao và cảnh trong thư mục `*_evidence`. Confidence và mAP không được dùng làm q. FP được báo cáo nhưng không làm dừng/thay đổi hành trình trong mô hình hiện tại.

Ánh xạ pilot: `q_kj = q_k` cho mọi ô j, nghĩa là giả định các ô có cùng hỗn hợp điều kiện quan sát như tập calibration POP. Mỗi ô là một lượt treo 5 giây, dùng **một frame đại diện**. Không nhân độc lập nhiều frame. Chưa ghép mức che khuất/độ cao/địa hình POP với từng ô SAREnv, chưa mô hình hóa footprint. Việc chuyển miền này phải được kiểm tra trước khi diễn giải xác suất như hiệu năng SAR ngoài thực địa.

Độ bất định: lưu Wilson 95% (xấp xỉ nếu các lần thử độc lập) và bootstrap theo cảnh (2.000 lần, seed 2026). POP có frame tương quan và calibration chỉ có 4 cảnh; không diễn giải các khoảng này như bảo đảm độ chính xác cao. Nhãn POP chỉ gồm mục tiêu nhận diện được theo quy trình của tác giả; q không bao gồm mọi người bị che kín hoàn toàn/không có nhãn.

## Bản đồ và mô hình vật lý pilot

- Scenario 1 là bản đồ flat/temperate, độ phân giải danh nghĩa 30 m/pixel. Cắt 32×32 pixel quanh tâm xuất phát từ metadata UTM, gộp tổng xác suất thành 16×16 ô. Tọa độ lấy từ `bounds` và kích thước thực của heatmap, không giả định hai trục có cùng bước pixel. Với scenario 1, kích thước ô thực là khoảng 60×60,091047 m (`cell_size_xy_m`); `cell_size_m=60` chỉ là kích thước danh nghĩa. Gộp bằng tổng, không resize ảnh heatmap bằng nội suy.
- Mặc định `condition_on_crop`: đặt `pi_j = raw_pi_j / raw_crop_mass`, nên `sum(pi)=1`. Mục tiêu là xác suất phát hiện có điều kiện nạn nhân nằm trong miền nhiệm vụ. `raw_crop_mass≈0,042474` và `raw_outside_probability≈0,957526` lưu phân bố của heatmap gốc; `outside_probability=0` trong mô hình có điều kiện. Với một hành trình, xác suất theo heatmap gốc bằng `p_detect * raw_crop_mass`. Chế độ `preserve_mass` vẫn được hỗ trợ để đối chiếu.
- Vùng 16×16 ô hiện là quy mô pilot; chuẩn hóa tổng xác suất không tự chứng minh vùng này là miền tìm kiếm tối ưu. Việc lựa chọn miền nhiệm vụ cho thí nghiệm chính thức còn cần thiết kế.
- Ba UAV dùng chung căn cứ tại tâm SAREnv, xuất phát t=0, không bắt buộc tất cả bay. Cho phép nghiệm rỗng; không có ngưỡng phát hiện tối thiểu.
- Bay 2D, đường thẳng Euclid. Không tính phát hiện khi đi qua ô; chỉ cộng tại ô được chọn quan sát. Chưa có địa hình cao, no-fly zone, tránh va chạm hoặc ràng buộc liên lạc.
- Deadline 600 s, quan sát 5 s/ô. Tốc độ lần lượt 8/10/12 m/s; công suất bay 180/220/260 W; công suất quan sát tổng 200/240/280 W; ngân sách 30/38/46 Wh. Các giá trị là **tham số mô phỏng thử nghiệm**, chưa được hiệu chỉnh theo UAV thương mại.
- Năng lượng = `(P_fly * distance/speed + P_obs * n_obs * tau)/3600`, có chặng về căn cứ. Hai pha không tính trùng. Chưa thêm cất/hạ cánh, đổi hướng, chờ, gió, dự trữ pin hoặc năng lượng phụ thuộc độ phân giải xử lý.
- Cả hai mục tiêu đánh giá toàn kế hoạch; không dừng sớm khi tìm thấy nạn nhân.

## Hai baseline và so sánh

Mã giải mã dùng chung: chọn ô bằng khóa `<0,5`, phân công bằng khoảng đều cho K UAV, duyệt các ô theo khóa thứ tự. Chỉ nối ô vào cuối hành trình nếu sau khi quan sát và trở về căn cứ còn thỏa T và B. Không phù hợp thì bỏ ô đó và tiếp tục duyệt các ô khác. Không đổi UAV để sửa. Mọi phép tính đầu ra được tính lại độc lập từ tọa độ để kiểm tra.

Đây là cách xử lý tính khả thi bằng decoder; do đó pymoo thấy một bài toán liên tục không có ràng buộc tường minh. Không bỏ ràng buộc của bài toán khi dùng MOEA/D. Sau giải mã, tỷ lệ khả thi phải là 100%; `repair_fraction` cho biết bao nhiêu cá thể cần bỏ ít nhất một ô vì tài nguyên.

NSGA-II: population N, binary tournament, rank/crowding, SBX p=0,9 eta=15; polynomial mutation p(cá thể)=1 và p(gene)=1/(3*số ô), eta=20; tắt loại genotype trùng để giữ đúng ngân sách.

MOEA/D: N vector trọng số đều từ (0,1) tới (1,0), Tchebycheff, 20 hàng xóm hoặc nhỏ hơn nếu N<20, xác suất chọn cha mẹ trong hàng xóm 0,9; cùng SBX/mutation. Hành vi thay hàng xóm và hệ số biên theo pymoo 0.6.1.5. Xem [NSGA-II](https://pymoo.org/algorithms/moo/nsga2.html) và [MOEA/D](https://pymoo.org/algorithms/moo/moead.html).

Quần thể đầu cùng seed giống nhau cho hai thuật toán, gồm mật độ chọn ô từ 0 đến 1 và nghiệm rỗng. Không thêm greedy/local search riêng cho thuật toán nào. 200 thế hệ gồm khởi tạo và 199 thế hệ sinh con: N×200 lần đánh giá cho mỗi thuật toán/seed; kiểm tra con số này lúc kết thúc.

Hai mục tiêu nội bộ chuẩn hóa cố định:

```
U = sum_j pi_j * max_k q_kj
F1 = 1 - P_detect / U
F2 = energy_wh / sum_k B_k
```

U là cận trên bỏ qua thời gian/pin, không phải xác suất tối ưu đạt được. Phép đổi tỉ lệ dương giữ nguyên Pareto dominance và tránh để xác suất nhỏ của crop bị năng lượng lấn át trong phân rã. Khi chỉ chuẩn hóa cùng miền cố định, P và U cùng chia cho `raw_crop_mass`, nên F1 không đổi; đây là đổi điều kiện của xác suất báo cáo, không phải cải tiến thuật toán. Đầu ra CSV dùng xác suất có điều kiện trong [0,1] (nhân 100 để đổi sang %) và Wh.

Lượt chạy miền nhiệm vụ 100% cũng sửa tọa độ raster, nên hành trình và chỉ số sau khi chạy lại có thể khác pilot cũ; không quy mọi thay đổi đó cho phép chuẩn hóa. Xem [báo cáo mới](mission-results.md).

Archive được cập nhật từ **mọi nghiệm được đánh giá** cho cả hai thuật toán, kể cả offspring không được giữ trong quần thể. Bỏ các điểm trùng mục tiêu, giữ một hành trình đại diện. HV dùng cùng điểm tham chiếu `r=(1.1, 1.1)` trong không gian chuẩn hóa. IGD+ dùng front không trội gộp từ toàn bộ archive của các lượt hoàn tất trong cùng thư mục; tập này phụ thuộc các lần chạy được gộp, không phải front tối ưu thật. Xem [định nghĩa chỉ số pymoo](https://pymoo.org/misc/indicators.html).

Không kết luận hơn/kém từ lượt smoke test hoặc một seed. Cần thêm detector được huấn luyện đủ, nhiều scenario, nhiều seed, phân tích thống kê, nhạy cảm theo q và mô hình năng lượng trước khi dùng kết quả cho paper.

## Chẩn đoán mở rộng trên scenario hiện tại

Xem [baseline-diagnostics.md](baseline-diagnostics.md) và lệnh `run.py diagnose`. Phân tích dùng instance đã đóng băng, đối chiếu 20.000/100.000 đánh giá, đối chứng tìm kiếm ngẫu nhiên, đa dạng quần thể, đột biến PM và các phép thử 2-opt/chèn ô ngoại tuyến. So ngân sách phải tái lập phần lịch sử chung; không so trực tiếp IGD+ lấy từ hai tập tham chiếu gộp khác nhau. Các phép thử ngoại tuyến không được tính như thuật toán thắng baseline ở cùng ngân sách.

## Bốn baseline và cơ chế hành trình

[baseline-study-protocol.md](baseline-study-protocol.md) mở rộng bằng MOSA/Pareto ILS, ablation mutation/crossover/projection cho cả hai EA, và kiểm chứng tham số cố định trên scenario 2/3, miền rộng hơn và tài nguyên chặt hơn. Kết quả phải được đọc theo cùng instance và cùng ngân sách; các giá trị IGD+ trong lượt study dùng tập tham chiếu chung mới của từng instance.
