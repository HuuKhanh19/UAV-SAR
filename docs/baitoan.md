# Tài liệu dự án: Multi-UAV Search and Rescue với xác suất phát hiện

> Cập nhật: 05/11/2026. Đây là tài liệu làm việc cho nghiên cứu hướng tới GECCO 2027.
> **Đã chốt** là lựa chọn được xác nhận trong trao đổi. **Đề xuất / Chờ xác nhận** chưa phải cấu hình chính thức.

## 1. Mục tiêu và phát biểu bài toán

**Tên đề xuất:** *Multi-Objective Probabilistic Search Path Planning for Heterogeneous UAVs with Imperfect Detection*.

Cho một đội UAV có đặc tính di chuyển, ngân sách năng lượng và hiệu quả phát hiện khác nhau, tìm kiếm một nạn nhân chưa biết vị trí trong khu vực có phân bố xác suất hiện diện không đồng nhất. **Đã chốt: nạn nhân nằm trong miền nhiệm vụ đã xác định; tổng xác suất các ô trong miền bằng 1.** Cần chọn các ô quan sát, phân công UAV và xác định thứ tự di chuyển để đồng thời:

1. **Tối đa hóa xác suất phát hiện nạn nhân** trong thời hạn nhiệm vụ.
2. **Tối thiểu hóa tổng năng lượng toàn hành trình** của đội UAV, bao gồm đường về căn cứ.

Mọi UAV tham gia phải trở về căn cứ trước hoặc đúng thời hạn $T$, không vượt ngân sách năng lượng và tuân thủ các ràng buộc đường bay được mô hình hóa. Đầu ra là một tập phương án không trội để thể hiện đánh đổi giữa hai mục tiêu.

Mô hình hiện tại mô tả phần **tìm kiếm và phát hiện** trong SAR. Chưa có mô hình vận chuyển nạn nhân, thả vật tư hoặc điều phối lực lượng cứu hộ sau phát hiện.

**Lộ trình đã chốt:** hiểu rõ bài toán → chạy baseline → nghiên cứu cải tiến thuật toán → so sánh với các phương pháp SOTA phù hợp → hoàn thiện paper để có thể submit GECCO 2027.

## 2. Phạm vi phiên bản đầu

| Thành phần | Lựa chọn | Trạng thái |
| --- | --- | --- |
| Mục tiêu | Hai mục tiêu: xác suất phát hiện và tổng năng lượng | Đã chốt |
| Đội UAV | Không đồng nhất; mức khác biệt cụ thể còn cần thiết kế | Đã chốt khung |
| Nạn nhân | Một nạn nhân, đứng yên trong nhiệm vụ | Đã chốt |
| Miền xác suất | Nạn nhân nằm trong miền nhiệm vụ; chuẩn hóa tổng xác suất các ô về 1 | Đã chốt |
| Quan sát | Mỗi ô tối đa một lượt trên toàn đội; thời lượng cố định $\tau_0$ | Đã chốt |
| Lập kế hoạch | Offline, tập trung; không lập kế hoạch lại trong quá trình bay | Đã chốt |
| Hành trình | Mỗi UAV xuất phát và trở về căn cứ của mình | Đã chốt |
| Năng lượng | Tính toàn bộ hành trình đã lập, gồm di chuyển, quan sát và quay về | Đã chốt |
| Deadline | $T$ là thời hạn toàn nhiệm vụ; mọi UAV phải về trước hoặc đúng $T$ | Đã chốt |
| Xác suất phát hiện | Ước lượng từ detector trên POP ngay từ giai đoạn baseline | Đã chốt |
| Mục tiêu thứ ba | Chưa đưa CVaR hoặc thời gian phát hiện kỳ vọng vào phiên bản đầu | Theo lựa chọn hai mục tiêu |

Quy định mỗi UAV về căn cứ của mình chưa xác định đội dùng **chung một căn cứ hay nhiều căn cứ**. Một lượt quan sát kéo dài $\tau_0$ cũng chưa đồng nghĩa với một ảnh đầu vào detector.

## 3. Mô hình toán học

### 3.1. Ký hiệu

| Ký hiệu | Ý nghĩa |
| --- | --- |
| $K$, $N$ | Số UAV sẵn có và số ô tìm kiếm |
| $\mathcal V=\{1,\ldots,N\}$ | Tập ô tìm kiếm |
| $b_k$ | Căn cứ của UAV $k$ |
| $\pi_j$ | Xác suất nạn nhân hiện diện tại ô $j$ trước nhiệm vụ, có điều kiện nạn nhân nằm trong miền nhiệm vụ |
| $q_{kj}$ | Xác suất phát hiện đúng trong một lượt quan sát, với điều kiện nạn nhân ở ô $j$ và UAV $k$ quan sát ô đó |
| $d_{ij}$, $t_{ij}^{k}$ | Khoảng cách và thời gian di chuyển từ $i$ đến $j$ của UAV $k$ |
| $B_k$ | Ngân sách năng lượng được phép sử dụng của UAV $k$ |
| $T$, $\tau_0$ | Thời hạn toàn nhiệm vụ và thời gian quan sát mỗi ô |
| $R_k$ | Hành trình có thứ tự của UAV $k$ |
| $\mathcal R=(R_1,\ldots,R_K)$ | Phương án của toàn đội |
| $x_{kj}\in\{0,1\}$ | Bằng 1 khi UAV $k$ thực hiện lượt quan sát tại ô $j$ |
| $n_k=\sum_j x_{kj}$ | Số lượt quan sát của UAV $k$ |
| $T_k(\mathcal R)$ | Thời điểm UAV $k$ về căn cứ, tính từ mốc bắt đầu nhiệm vụ |
| $E_k(R_k)$ | Năng lượng toàn hành trình của UAV $k$ |

Cần có $0\leq q_{kj}\leq1$, $\pi_j\geq0$ và **$\sum_j\pi_j=1$**. Đã chốt mô hình có điều kiện nạn nhân nằm trong miền nhiệm vụ $R$. Với trọng số heatmap gốc $w_j$, đặt $m_R=\sum_{j\in R}w_j$ và $\pi_j=w_j/m_R$. Phép chuẩn hóa giữ nguyên tỷ lệ giữa các ô, không biến heatmap thành phân bố đều.

Xác suất phát hiện được báo cáo là $P(\mathrm{detect}\mid X\in R)$. Giữ $m_R$ trong metadata (`raw_crop_mass`) để có thể báo cáo bổ sung $P_{\mathrm{source}}=m_R P(\mathrm{detect}\mid X\in R)$ theo heatmap gốc. Pilot cũ dùng `preserve_mass` được lưu riêng; không trộn trực tiếp hai cách diễn giải. Việc chọn kích thước miền $R$ cho thí nghiệm chính thức vẫn cần được thiết kế.

### 3.2. Biểu diễn lời giải

Với UAV thực hiện $n_k$ lượt quan sát:

$$
R_k=(b_k,j_{k,1},\ldots,j_{k,n_k},b_k).
$$

Các ô quan sát trong hành trình không lặp. $x_{kj}=1$ khi và chỉ khi $j$ xuất hiện trong danh sách ô quan sát của $R_k$. Vì vậy, ma trận $x$ chỉ biểu diễn việc phân công; cần thêm thứ tự trong $R_k$ để tính thời gian và năng lượng.

Các chặng nối phải có đường di chuyển hợp lệ. Đi ngang qua một ô có được tính là quan sát hay không còn phụ thuộc mô hình cảm biến cần chốt; không được tự cộng thêm xác suất phát hiện chỉ vì đường bay đi qua ô đó.

### 3.3. Mục tiêu 1: Xác suất phát hiện

$$
\max f_1(\mathcal R)=\sum_{j=1}^{N}\pi_j\sum_{k=1}^{K}x_{kj}q_{kj}.
$$

Công thức sử dụng xác suất toàn phần theo vị trí của **một nạn nhân**, cùng điều kiện mỗi ô chỉ được quan sát tối đa một lần trên toàn đội. Với các điều kiện trên, $0\leq f_1\leq1$. Không cần giả định độc lập giữa các ô để cộng các trường hợp vị trí loại trừ nhau này.

Ví dụ minh họa: $\pi_j=0.2$ và $q_{kj}=0.7$ thì việc giao ô $j$ cho UAV $k$ đóng góp $0.14$ vào xác suất phát hiện toàn nhiệm vụ. Đây là số liệu giải thích công thức, không phải kết quả thực nghiệm.

**Hệ quả của mô hình:** khi mọi lượt quan sát đều hoàn tất trước $T$ và $q_{kj}$ cố định, đổi thứ tự ghé thăm mà giữ nguyên phân công không làm đổi $f_1$. Thứ tự vẫn ảnh hưởng chi phí và tính khả thi. Mô hình này chưa thưởng riêng việc phát hiện sớm hơn trong khoảng thời gian cho phép.

Chính sách xử lý báo động giả chưa được xác định. Nếu báo động giả làm dừng hoặc thay đổi nhiệm vụ, cần sửa mô hình đánh giá; công thức trên chưa mô tả tác động đó.

### 3.4. Mục tiêu 2: Năng lượng toàn hành trình

$$
\min f_2(\mathcal R)=\sum_{k=1}^{K}E_k(R_k).
$$

$E_k$ được tính cho toàn bộ kế hoạch, kể cả trường hợp không phát hiện được nạn nhân. Đây là **năng lượng của hành trình đã lập**, không phải kỳ vọng năng lượng khi dừng sớm sau phát hiện. Chính sách thực thi sau phát hiện là một lựa chọn riêng.

Mô hình phân pha trong bản thảo là một **đề xuất triển khai**, chưa chốt các tham số vật lý:

$$
E_k(R_k)=P_k^{\mathrm{fly}}t_k^{\mathrm{fly}}+P_k^{\mathrm{obs}}n_k\tau_0.
$$

$t_k^{\mathrm{fly}}$ phải bao gồm chặng đi từ căn cứ, các chặng giữa ô và chặng quay về. $P_k^{\mathrm{obs}}$ phải đại diện cho tổng công suất trong pha quan sát, gồm duy trì bay/treo và thiết bị liên quan, thay vì chỉ tính công suất camera. Hai pha cần được định nghĩa để tránh tính trùng.

Nếu công suất dùng W và thời gian dùng giây thì biểu thức trên cho năng lượng bằng J; chia cho $3600$ để đổi sang Wh. $E_k$ và $B_k$ phải cùng đơn vị. Chi phí cất/hạ cánh, chuyển hướng, chờ và dự trữ pin còn cần xác nhận cách xử lý.

Căn cứ và giới hạn của lựa chọn năng lượng được tổng hợp trong [ghi chú nghiên cứu](research-energy-deadline.md).

### 3.5. Thời gian và các ràng buộc

$$
\begin{aligned}
T_k(\mathcal R)&\leq T &&\forall k,\\
E_k(R_k)&\leq B_k &&\forall k,\\
\sum_{k=1}^{K}x_{kj}&\leq1 &&\forall j,\\
x_{kj}&\in\{0,1\} &&\forall k,j.
\end{aligned}
$$

$T_k$ là thời điểm **về căn cứ**, nên phải tính thời gian đi, quan sát, quay về và các khoảng thời gian khác nếu mô hình có xét. Nếu các UAV cùng xuất phát tại thời điểm 0, chỉ có hai pha di chuyển và quan sát, thì:

$$
T_k=t_k^{\mathrm{fly}}+n_k\tau_0.
$$

Với $t_k^{\mathrm{last}}$ là thời điểm kết thúc quan sát cuối và $t_k^{\mathrm{return}}$ là thời gian từ đó đến khi về căn cứ:

$$
t_k^{\mathrm{last}}+t_k^{\mathrm{return}}=T_k\leq T.
$$

Ví dụ: với $T=30$ phút, kết thúc quan sát ở phút 27 và cần 5 phút quay về thì hành trình **không khả thi**. Các con số chỉ dùng minh họa.

Các ràng buộc trên cần đi cùng tính liên thông của hành trình, liên kết giữa $x$ và $R_k$, và quy tắc cạnh hợp lệ. Chúng chưa tạo thành một mô hình MILP đầy đủ. Điều kiện không quan sát trùng ô cũng **không tự bảo đảm tránh va chạm** giữa các đường bay.

### 3.6. Đánh đổi Pareto

| Phương án minh họa | Xác suất phát hiện | Tổng năng lượng |
| --- | --- | --- |
| A | 63% | 40 Wh |
| B | 78% | 57 Wh |
| C | 85% | 76 Wh |

Ba phương án không trội lẫn nhau. Đây chỉ là tập điểm minh họa, chưa chứng minh chúng thuộc biên Pareto tối ưu của một instance cụ thể.

Để dùng thuật toán yêu cầu mọi mục tiêu đều cực tiểu, có thể biểu diễn tương đương $\min(1-f_1,f_2)$. Nếu cho phép toàn đội không xuất phát, nghiệm có xác suất phát hiện và năng lượng đều bằng 0 có thể là một điểm cực biên. Có cho phép nghiệm này hoặc áp ngưỡng phát hiện tối thiểu hay không còn chờ xác nhận.

## 4. Dữ liệu và ước lượng xác suất phát hiện

| Nguồn | Vai trò trong dự án | Công việc cần làm |
| --- | --- | --- |
| SAREnv | Bản đồ và thông tin phân bố vị trí nạn nhân, kế thừa lựa chọn trong bản thảo | Chọn scenario, cách chia ô, cách xây dựng $\pi_j$ và vùng hợp lệ |
| POP | Dữ liệu thực nghiệm để ước lượng $q_{kj}$ ngay từ baseline | Chọn detector, tập dữ liệu, tiêu chí phát hiện và điều kiện quan sát |
| Thông số UAV | Tốc độ, công suất, pin và các đặc tính không đồng nhất | Chọn nguồn tham số, đơn vị và phạm vi hiệu chỉnh |

[SAREnv](https://github.com/namurproject/SAREnv) cung cấp môi trường địa lý, heatmap và công cụ đánh giá SAR. [POP](https://pmc.ncbi.nlm.nih.gov/articles/PMC11840078/) là bộ ảnh nhiệt phát hiện người, gồm cả người bị che khuất, thu bằng DJI Matrice 30T. Hai nguồn không cung cấp sẵn một ma trận $q_{kj}$ kết hợp cho dự án.

**Quy trình cần thiết kế trước khi chạy baseline:**

1. Kiểm tra dữ liệu và metadata POP thực tế: cảnh, độ cao, mức che khuất, nhóm ảnh có liên quan và khả năng chia tập tránh rò rỉ dữ liệu.
2. Chọn detector/cấu hình UAV và cố định tiêu chí phát hiện đúng, gồm ngưỡng confidence, quy tắc ghép nhãn và IoU.
3. Ước lượng tần suất phát hiện có điều kiện trên dữ liệu giữ lại; báo cáo số mẫu và độ bất định của ước lượng. AP/mAP hoặc confidence của một dự đoán không tự bằng $q_{kj}$.
4. Định nghĩa cách chuyển kết quả ở mức ảnh/người sang **một lượt quan sát dài $\tau_0$**. Nếu dùng nhiều ảnh, không mặc định các lần phát hiện độc lập.
5. Xác định ánh xạ điều kiện quan sát từ POP sang từng ô SAREnv. Phần ánh xạ là giả định của dự án, cần được công bố và kiểm tra độ nhạy.
6. Đóng băng ma trận $q$, bản đồ $\pi$ và cấu hình instance để mọi thuật toán dùng cùng đầu vào.

POP chưa tự cung cấp bằng chứng cho nhiều loại cảm biến UAV khác nhau. Cách tạo khác biệt giữa các hàng $q_{kj}$ cần xác nhận: khác detector, độ cao/cấu hình quan sát, hay nguồn dữ liệu bổ sung. Chưa chọn thay người nghiên cứu.

## 5. Cơ sở thuật toán và baseline

[Chương 1](<1. IntroEC.md>) và [Chương 2](<2. Genetic Algorithm.md>) cung cấp nền tảng biểu diễn, giải mã và toán tử tiến hóa. [Chương 10](<10. MOO.md>) là cơ sở cho Pareto, NSGA-II và MOEA/D. [Chương 6](<6. MFEA.md>) phân biệt tối ưu đa nhiệm với đa mục tiêu: nhiều UAV không tự biến bài toán này thành bài toán MFEA.

| Phương pháp trong bản thảo | Vai trò dự kiến | Điểm cần xác định |
| --- | --- | --- |
| NSGA-II | Baseline tiến hóa đa mục tiêu ban đầu | Mã hóa hành trình, toán tử và xử lý nghiệm không khả thi |
| MOEA/D | Baseline theo phân rã | Hàm phân rã, chuẩn hóa, trọng số và hàng xóm |
| Weighted-sum GA | Baseline bổ sung với nhiều mức ưu tiên | Chuẩn hóa hai mục tiêu và phân bổ ngân sách giữa các lần chạy |
| Greedy tạo nhiều phương án | Mốc so sánh dễ giải thích | Quy tắc chọn ô/UAV, chèn đường đi và mức ưu tiên |

NSGA-II và MOEA/D là hai baseline ưu tiên **theo bản thảo**. Cấu hình cụ thể chưa chốt. Các baseline này chưa thay thế cho việc khảo sát và lựa chọn SOTA gần bài toán để so sánh trong paper.

Một lời giải phải mã hóa đồng thời tập ô được chọn, UAV được giao và thứ tự quan sát. Mã hóa hoán vị cho TSP trong slide cần điều chỉnh vì dự án không bắt buộc thăm mọi ô và có nhiều hành trình.

## 6. Câu hỏi nghiên cứu và thiết kế đánh giá

Các câu hỏi dưới đây là **đề xuất để thảo luận**, chưa phải tuyên bố đóng góp mới:

- Hiệu quả phát hiện không hoàn hảo và tính không đồng nhất của đội UAV làm thay đổi phân công, hành trình và đánh đổi Pareto như thế nào?
- Một cải tiến dựa trên cấu trúc bài toán có nâng chất lượng tập nghiệm ở cùng ngân sách tính toán không?
- Kết luận có ổn định khi thay đổi scenario, giới hạn tài nguyên và sai số ước lượng $q_{kj}$ không?

| Chỉ số | Mục đích và điều kiện sử dụng |
| --- | --- |
| $f_1$, $f_2$ | Báo cáo trực tiếp xác suất phát hiện và năng lượng của các phương án |
| Hypervolume, HV | Đánh giá tập nghiệm; cần thống nhất chiều tối ưu, chuẩn hóa và điểm tham chiếu |
| IGD+ | Cần tập tham chiếu công bố rõ; nếu dùng tập gộp thực nghiệm, không gọi đó là biên Pareto thật |
| Thời gian tính toán, số lần đánh giá | So sánh chi phí tính toán và tiến trình hội tụ |
| Tỷ lệ nghiệm khả thi | Kiểm tra tuân thủ deadline, pin và các ràng buộc đã chọn |

Định nghĩa HV và IGD+ có thể đối chiếu trong [tài liệu chỉ số của pymoo](https://pymoo.org/misc/indicators.html); việc dẫn nguồn này chưa quyết định thư viện triển khai.

Thực nghiệm cần dùng chung instance và quy tắc đánh giá, nhiều lần chạy độc lập, lưu seed và tham số. Phải tách dữ liệu/tập cấu hình dùng hiệu chỉnh khỏi phần đánh giá cuối. Số lần chạy, ngân sách, chuẩn hóa và phương pháp thống kê còn chờ chốt.

Khi có cải tiến thuật toán, cần ablation để kiểm tra tác dụng từng thành phần. Với các phương pháp SOTA khác giả định, phải mô tả phần thích nghi vào bài toán chung; không so trực tiếp các con số lấy từ paper khác.

## 7. Lộ trình và sản phẩm

| Giai đoạn | Sản phẩm cần có trước khi chuyển bước |
| --- | --- |
| Hiểu và hoàn thiện bài toán | Đặc tả nhất quán, các lựa chọn mô hình được xác nhận, instance nhỏ tính tay được |
| Chuẩn bị dữ liệu và evaluator | Pipeline POP tạo $q$, dữ liệu SAREnv đã xử lý, kiểm tra tính khả thi và hai mục tiêu |
| Chạy baseline | Tập nghiệm, log, cấu hình tái lập và biểu đồ Pareto cho các baseline đã chọn |
| Nghiên cứu cải tiến | Phân tích hạn chế baseline, giả thuyết cải tiến, cài đặt và ablation |
| So sánh SOTA | Bảng related work, tập phương pháp phù hợp, thực nghiệm công bằng và phân tích thống kê |
| Hoàn thiện paper | Bản thảo, hình/bảng có nguồn gốc, mã và cấu hình tái lập kết quả |

Việc đọc related work cần bắt đầu ngay ở giai đoạn hiểu bài toán và cập nhật trong quá trình nghiên cứu. Điểm mới chỉ có thể kết luận sau khi đối chiếu với công trình liên quan.

Mục tiêu hội nghị đã chốt là **GECCO 2027**. Theo [lịch chính thức](https://gecco-2027.sigevo.org/Important%2BDates), hạn abstract cho full paper là **18/01/2027**, hạn full paper là **25/01/2027**; kiểm tra ngày 05/11/2026. Track, loại bài và lịch nội bộ chưa chốt. [Call for Papers](https://gecco-2027.sigevo.org/Call%2Bfor%2BPapers) nêu giới hạn full paper 8 trang, không tính tài liệu tham khảo, và phản biện hai chiều ẩn danh.

## 8. Các lựa chọn còn cần xác nhận

| Mã | Câu hỏi cần quyết định | Ảnh hưởng |
| --- | --- | --- |
| Q1 | Bản đồ 2D hay xét địa hình/độ cao? Ô vuông và kích thước ô thế nào? | Khoảng cách, khả thi và ánh xạ cảm biến |
| Q2 | Dùng chung hay nhiều căn cứ? Các UAV cùng xuất phát tại thời điểm 0 không? | Cấu trúc hành trình và thời điểm về |
| Q3 | Có bắt buộc mọi UAV xuất phát? Có ngưỡng xác suất phát hiện tối thiểu không? | Không gian nghiệm và cực biên năng lượng thấp |
| Q4 — đã chốt | Nạn nhân nằm trong miền nhiệm vụ; chuẩn hóa $\sum_j\pi_j=1$ (`condition_on_crop`) | Xác suất phát hiện có điều kiện; giữ xác suất miền trên heatmap gốc trong metadata |
| Q5 | Quan sát khi bay treo hay khi di chuyển? Một lượt dùng một ảnh hay một chuỗi ảnh? | $\tau_0$, năng lượng, footprint và $q_{kj}$ |
| Q6 | Detector nào, chia tập POP thế nào, tạo không đồng nhất về phát hiện bằng cách nào? | Giá trị thực nghiệm và khả năng tái lập $q$ |
| Q7 | Dùng mô hình công suất nào? Có xét cất/hạ cánh, chuyển hướng, chờ, pin dự trữ không? | Độ chính xác của $E_k$ và $B_k$ |
| Q8 | Có xét vùng cấm bay, tránh va chạm và ràng buộc liên lạc trong phiên bản đầu không? | Định nghĩa đường bay khả thi |
| Q9 | Sau phát hiện đúng hoặc báo động giả, UAV xử lý thế nào? | Mô phỏng thực thi; không đổi quy ước năng lượng toàn kế hoạch đã chốt |
| Q10 | Quy mô instance, ngân sách tính toán, số lần chạy và nền tảng triển khai? | Khả năng hoàn thành thực nghiệm và so sánh |

Các mục ngoài Q4 còn mở; cấu hình pilot chưa thay thế thiết kế thí nghiệm chính thức.

## 9. Nguồn và trạng thái hiện tại

- Đã đọc các bản Markdown slide chương 1–10 trong `docs/` và bản thảo bài toán ban đầu.
- Bản thảo từng nhắc “Đề xuất bài toán UAV cứu hộ.pdf”; chưa tìm thấy file này trong workspace nên chưa đối chiếu được nội dung gốc.
- [Ghi chú nghiên cứu năng lượng và deadline](research-energy-deadline.md) lưu nguồn paper, phạm vi áp dụng và lý do của hai quyết định đã chốt.
- Workspace đã có baseline NSGA-II/MOEA/D, kết quả pilot cũ và [kết quả miền nhiệm vụ 100%](mission-results.md). Các bảng phương án minh họa trong phần mô hình không phải kết quả thực nghiệm.

**Bổ sung triển khai:** mã baseline pilot và pipeline SAREnv → POP detector → ma trận q → NSGA-II/MOEA/D được mô tả trong [giao thức baseline](baseline-protocol.md), với hướng dẫn terminal ở [README](../README.md). Chuẩn hóa miền nhiệm vụ theo Q4 đã được xác nhận; các giả định pilot khác vẫn cần được kiểm chứng.
