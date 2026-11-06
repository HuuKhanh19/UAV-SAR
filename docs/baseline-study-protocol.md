# Bốn baseline và kiểm chứng cơ chế biến đổi hành trình

Giao thức ngày 06/11/2026, nối tiếp [chẩn đoán scenario 1](baseline-diagnostics.md). Mục tiêu là kiểm tra điểm yếu chung của **hai triển khai EA hiện tại**, thiết kế cơ chế khắc phục và kiểm chứng khi đổi điều kiện bài toán.

Hai baseline bổ sung được chọn là **MOSA** và **Pareto Iterated Local Search (PILS)**. Đây là các bản thích nghi cho mô hình SAR của dự án; tên thuật toán không hàm ý đã tái lập từng chi tiết của một công bố cụ thể.

## 1. Bốn baseline

| Tên CLI | Trạng thái tìm kiếm | Cách sinh kế hoạch | Cách chấp nhận |
| --- | --- | --- | --- |
| `nsga2` | Quần thể 100 random keys | SBX + PM, decoder chung | Pareto rank và crowding |
| `moead` | 100 bài toán con/random keys | SBX + PM, decoder chung | Tchebycheff, cập nhật hàng xóm |
| `mosa` | 21 chuỗi annealing theo trọng số | Một biến đổi trực tiếp trên hành trình | Cải thiện scalar hoặc chấp nhận theo nhiệt độ |
| `pils` | Archive Pareto và nghiệm đang khai thác | Năm lân cận, sau đó perturbation | Đi theo nghiệm trội; lưu cả các trade-off vào archive |

Cả bốn dùng cùng 100 kế hoạch khởi tạo theo seed, evaluator, mô hình P/E, pin/deadline, chuẩn hóa và chính sách archive mọi nghiệm khả thi đã đánh giá. Với MOSA/PILS, 100 là **số kế hoạch khởi tạo**, không phải kích thước quần thể EA trong quá trình chạy.

Một kế hoạch thử tương ứng một đánh giá. Kế hoạch vi phạm tài nguyên của MOSA/PILS vẫn tiêu tốn ngân sách rồi bị loại; EA xử lý bằng decoder như giao thức gốc. Không thử lại miễn phí cho đến khi sinh được nghiệm khả thi.

### MOSA-TCH trong code

- Trọng số 21 điểm đều từ (0,1) đến (1,0). Mỗi chuỗi bắt đầu bằng kế hoạch tốt nhất theo trọng số đó trong 100 kế hoạch chung.
- Scalar là `g_w(F)=max(w_1*F_1, w_2*F_2)`, với điểm lý tưởng **cố định (0,0)**.
- Cập nhật các chuỗi lần lượt. Chấp nhận nếu `delta_g<=0`, nếu kém hơn thì chấp nhận với xác suất `exp(-delta_g/T)`.
- Nhiệt độ giảm hình học từ 0,02 xuống 0,0002 theo phần ngân sách đã sử dụng.
- Archive không dùng để thay đổi quy tắc chấp nhận. Đây **không phải AMOSA** với các trường hợp dominance và clustering archive của thuật toán đó.

### PILS lấy mẫu trong code

- Chọn một nghiệm trong archive và xét năm lân cận theo thứ tự hoán vị ngẫu nhiên.
- Lấy mẫu 8 ứng viên/lân cận. Nếu ứng viên trội nghiệm hiện tại thì chuyển sang nó và bắt đầu lại chuỗi lân cận.
- Mọi ứng viên khả thi đều được xét cập nhật archive, kể cả ứng viên không được chọn làm trạng thái hiện tại.
- Khi đã lấy mẫu hết các lân cận, chuyển sang nghiệm archive chưa được khai thác. Nếu không còn, perturb một nghiệm archive bằng 5 biến đổi với vị trí chèn ngẫu nhiên, mỗi bước đều tính ngân sách.
- Đây là tìm kiếm trên lân cận lấy mẫu; **không chứng nhận cực trị cục bộ trên toàn bộ lân cận**.

## 2. Bộ biến đổi hành trình

MOSA, PILS và mutation cải tiến của EA dùng chung các quyết định:

1. **Insert:** chọn đều một ô chưa quan sát và một UAV, chèn tại vị trí có tăng quãng đường nhỏ nhất.
2. **Delete:** bỏ một ô đang quan sát.
3. **Relocate:** chuyển một ô sang UAV/vị trí khác; UAV đích được chọn đều, vị trí chèn rẻ nhất.
4. **Swap:** đổi chỗ hai ô đã chọn, có thể thuộc hai UAV khác nhau.
5. **Reverse:** đảo một đoạn trong hành trình.

Việc chọn ô/UAV không dùng chỉ số ô cố định, vị trí hotspot được biết trước hoặc hằng số riêng của scenario 1. Các vị trí chèn được tính từ ma trận khoảng cách của instance; số vị trí xét được ghi lại. Không có 2-opt đến cực trị hay greedy refill không giới hạn ẩn trong một lượt đánh giá.

## 3. Cơ chế mẫu cho EA và ablation

Random keys hiện tại biểu diễn được mọi kế hoạch khả thi của mô hình. Giả thuyết cần kiểm tra là **cách di chuyển trên random keys không khớp tốt với cấu trúc quyết định**, gồm hai phần: PM thường không đổi phenotype và SBX có thể làm mất cấu trúc đường bay.

Cơ chế mẫu có hai thành phần:

- **Mutation theo hành trình:** giải mã, thực hiện một biến đổi trong bộ trên, mã hóa lại thành 3N keys. Nếu đề xuất vượt tài nguyên, decoder chung tiếp tục xử lý khi đánh giá.
- **Crossover giữ đoạn đầu hành trình:** giữ ngẫu nhiên một prefix cho từng UAV từ cha A; nối các ô còn lại theo thứ tự và UAV của cha B, bỏ ô trùng trên toàn đội. Tạo con thứ hai bằng đổi vai hai cha. Decoder chung vẫn xử lý tính khả thi.

Mã hóa lại đặt khóa chọn ở 0,25/0,75, khóa UAV ở giữa khoảng phân công, khóa thứ tự theo vị trí trong các hành trình. Với một kế hoạch khả thi, giải mã lại khôi phục đúng kế hoạch đó. Vì bước chiếu/mã hóa lại cũng thay đổi động học tìm kiếm, cần một đối chứng riêng.

| Hậu tố EA | Crossover | Mutation | Mục đích |
| --- | --- | --- | --- |
| Không có | SBX | PM | Baseline gốc |
| `_canonical` | SBX | PM rồi chiếu về phenotype khả thi | Tách hiệu ứng mã hóa lại |
| `_route_mutation` | SBX | Theo hành trình | Đổi riêng mutation |
| `_route_crossover` | Giữ prefix | PM | Đổi riêng crossover |
| `_route` | Giữ prefix | Theo hành trình | Kiểm tra kết hợp |

Chạy cả năm cấu hình cho **NSGA-II và MOEA/D** trên tập phát triển. Điều này giúp kiểm tra một cơ chế chung có hoạt động với hai cách chọn lọc khác nhau hay không; không mặc định rằng mọi EA đều có cùng nhược điểm.

## 4. Phát triển và kiểm chứng

Thông số được đóng băng tại [baseline-study.json](../configs/baseline-study.json), trước khi đọc kết quả kiểm chứng.

| Vai trò | Instance | N | Deadline | Pin (Wh) | Seed |
| --- | --- | ---: | ---: | --- | --- |
| Phát triển | Scenario 1 hiện tại | 256 | 600 s | 30 / 38 / 46 | 1–5 |
| Kiểm chứng bản đồ | Scenario 2 | 256 | 600 s | 30 / 38 / 46 | 11–15 |
| Kiểm chứng bản đồ | Scenario 3 | 256 | 600 s | 30 / 38 / 46 | 11–15 |
| Kiểm chứng miền rộng hơn | Scenario 1, crop 24×24 ô | 576 | 600 s | 30 / 38 / 46 | 11–15 |
| Kiểm chứng tài nguyên | Scenario 1, tài nguyên ×0,7 | 256 | 420 s | 21 / 26,6 / 32,2 | 11–15 |

Tập phát triển có 12 phương pháp: bốn baseline và tám biến thể EA. Mỗi trường hợp kiểm chứng có sáu phương pháp: bốn baseline và hai EA với cơ chế kết hợp `_route`. Không chọn lại tham số từ kết quả kiểm chứng.

Mỗi phương pháp/seed có **20.000 đánh giá**, tính cả 100 kế hoạch đầu. Toàn bộ gồm **180 lượt, 3.600.000 đánh giá**. Detector giữ calibration POP 3 epoch đã dùng; mọi q vẫn là giá trị đo trên POP, không tạo q ngẫu nhiên.

Miền 576 ô đồng thời tăng số biến và diện tích nhiệm vụ; không diễn giải nó như thí nghiệm chỉ thay N. Trường hợp tài nguyên thay cả deadline lẫn pin; không diễn giải nó như ablation riêng pin.

## 5. Đo chất lượng và cơ chế

- **HV**, Pmax, P dưới các trần năng lượng 20/40/60/80/100% tổng pin; xem toàn front thay vì chỉ một điểm.
- **IGD+** dùng một tập tham chiếu thực nghiệm chung cho tất cả phương pháp/seed **trong cùng instance**. Không gộp trực tiếp IGD+ hay thứ hạng tuyệt đối giữa các instance.
- **Đối chiếu cùng thời gian:** trong từng instance, dùng thời gian tìm kiếm hoàn tất nhỏ nhất trong các lượt làm mốc chung; lấy checkpoint cuối trước mốc đó cho từng lượt. Checkpoint cách nhau 100 đánh giá, không nội suy.
- **Chi phí nội bộ:** số vị trí chèn xét và thời gian tìm kiếm. Một lượt gọi evaluator không phản ánh toàn bộ chi phí của một phép tìm vị trí chèn.
- **Probe trên cùng cha:** thử riêng PM, PM + projection, mutation hành trình; đo tỷ lệ đổi phenotype. Thử SBX và crossover hành trình trên cùng cặp cha; đo tỷ lệ cạnh con được thừa hưởng từ hợp các cạnh cha và tỷ lệ cạnh chung được giữ.
- **Khoảng trống hình học:** dùng 2-opt ngoại tuyến trên nghiệm Pmax để đo năng lượng còn có thể tiết kiệm, giữ nguyên phân công/ô. Phép thử này không được tính là kết quả online của phương pháp.
- **Hiệu ứng ghép cặp:** so biến thể với baseline cùng instance/seed; báo cáo từng trường hợp kiểm chứng. Năm seed không đủ để đưa ra bảo đảm thống kê rộng.

Probe là phép thử riêng trên quần thể cuối của hai EA gốc. Nó không đại diện cho mọi offspring trong toàn bộ lịch sử tiến hóa.

## 6. Chạy và đọc dữ liệu

```powershell
$py = '.venv/Scripts/python.exe'

# Bốn baseline trên instance hiện tại.
& $py -u run.py run --instance artifacts/diagnostics_mission/instance.json --algorithms nsga2 moead mosa pils --seeds 1 2 3 4 5 --output results/baseline_four_methods

# Ablation, trường hợp kiểm chứng, probe và audit.
& $py -u run.py study --baseline-results results/baseline_four_methods --output results/baseline_mechanism_study
```

Cần có SAREnv scenario 2/3 với `features.geojson` thực từ Git LFS, `heatmap.npy`, `datasets/sources.json`; bước tạo validation instance dùng cùng calibration đã nhúng trong instance phát triển. Không cần huấn luyện lại detector.

`study` chỉ tái sử dụng những lượt đã hoàn tất khi protocol, source, instance và settings khớp. Chưa resume trạng thái bên trong một lượt bị ngắt. Khi đổi source/thiết kế, dùng thư mục output mới.

Các file chính: `protocol.json`, `manifest.json`, `runs.csv`, `summary.csv`, `summary.json`, `paired_effects.csv`, `variation_probes.csv`, `attainment.csv`, `reference_<case>.csv`, `audit.json`, `study.png`. Mỗi cohort vẫn có `routes.json`, `archive.npz`, `history.csv`, settings và checksum để kiểm tra độc lập.

## 7. Quan hệ với tài liệu và phạm vi đóng góp

[MOSA của Ulungu và cộng sự](https://onlinelibrary.wiley.com/doi/10.1002/%28SICI%291099-1360%28199907%298%3A4%3C221%3A%3AAID-MCDA247%3E3.0.CO%3B2-O) là nguồn về họ SA đa mục tiêu; bản trong dự án dùng chuỗi Tchebycheff được mô tả đầy đủ ở trên. [PILS của Geiger](https://arxiv.org/abs/0809.0406) kết hợp khai thác nhiều lân cận, archive và perturbation; dự án thích nghi bằng lấy mẫu lân cận routing có ngân sách hữu hạn.

EA với crossover và tìm kiếm cục bộ theo cấu trúc orienteering đã có tiền lệ, chẳng hạn [Mei, Salim và Li, EJOR 2016](https://homepages.ecs.vuw.ac.nz/~yimei/papers/EJOR2016-MeiSalimLi.pdf); [EA phân rã kết hợp constraint programming cho MOTOPTW](https://www.sciencedirect.com/science/article/pii/S1568494618304861) cũng là hướng liên quan cần đối chiếu.

Vì vậy, cơ chế `_route` hiện là **prototype có đối chứng để kiểm tra giả thuyết**, chưa được gọi là thuật toán có tính mới học thuật. Mức tổng quát hóa được đánh giá trong mô hình 2D, q theo UAV cố định và các trường hợp nêu trên; chưa suy rộng sang vật cản, gió, che khuất, mục tiêu di động hay SAR thực địa.
