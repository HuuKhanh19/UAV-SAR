# Cơ chế biến đổi theo quyết định và hướng phát triển thuật toán

Đọc cùng [giao thức thí nghiệm](baseline-study-protocol.md). Tài liệu này tách **prototype đã triển khai** khỏi **thiết kế thích nghi chưa triển khai**, để kết quả thử nghiệm không bị diễn giải thành một tuyên bố tính mới chưa được kiểm chứng.

## 1. Điểm yếu cần khắc phục

Trong mô hình hiện tại, một cá thể gồm chọn ô, phân công UAV và thứ tự. Không gian random keys biểu diễn được kế hoạch khả thi; trở ngại là phép biến đổi số thực không luôn tạo ra thay đổi có ích trên ba nhóm quyết định này.

Gọi N là số ô, S là số ô có khóa chọn `<0,5`. Khi cố định quyết định chọn/bỏ, khóa phân công và thứ tự của N−S ô không được chọn không ảnh hưởng hành trình. Với PM có xác suất theo gene `1/(3N)`, số khóa phân công/thứ tự của **tập ô đang được chọn** được tác động kỳ vọng không vượt `2S/(3N)` mỗi cá thể. Khi S/N nhỏ, phần ngân sách mutation này bị phân tán vào các tọa độ không hoạt động.

Đây là nhận xét về các tọa độ với tập chọn cố định, không phải cận trên cho mọi thay đổi phenotype khi nhiều gene cùng đổi. Gene chọn ô còn phải vượt ngưỡng 0,5; những tương tác đồng thời và decoder repair có thể thay đổi hiệu ứng.

Một vấn đề khác là recombination: thay đổi nhiều khóa có thể giữ lại ô có ích nhưng làm xáo thứ tự/phân công vốn giúp chúng vừa tài nguyên. Vì thế cần xem **cặp crossover–mutation**, thay vì suy ra chất lượng chỉ từ tỷ lệ gene đổi hoặc tỷ lệ phenotype đổi.

## 2. Prototype đã triển khai

Hai thành phần cùng dùng được với NSGA-II và MOEA/D:

1. **Sinh biến đổi trực tiếp trên quyết định:** thêm/bỏ ô, chuyển UAV/vị trí, swap và reverse. Loại quyết định được chọn trước; số gene của instance không trực tiếp làm giảm xác suất chọn loại quyết định đó.
2. **Giữ cấu trúc khi tái tổ hợp:** kế thừa prefix hành trình từ một cha, nối các ô còn lại theo thứ tự của cha kia, bảo đảm mỗi ô chỉ có một UAV phụ trách trước khi qua decoder.

Kế hoạch con được mã hóa lại vào chính 3N keys để tái sử dụng hai bộ chọn lọc EA, evaluator và ràng buộc hiện có. Với một kế hoạch khả thi R, mã hóa rồi giải mã cho lại R. Việc mã hóa lại không tự tối ưu mục tiêu; nó có thể thay đổi động học của các phép biến đổi tiếp theo, nên thí nghiệm có đối chứng `_canonical` riêng.

Không dùng 2-opt đến cực trị hoặc chèn mọi ô còn trống bên trong một offspring. Mỗi mutation đề xuất một biến đổi; số vị trí chèn được xét và thời gian được báo cáo riêng.

Mã: [route_operators.py](../uav_sar/route_operators.py). Đây là cơ chế mẫu để kiểm tra giả thuyết, không phải một tên thuật toán mới được xác lập.

## 3. Vì sao xét vị trí chèn rẻ nhất phù hợp với mô hình

Giữ cố định ô j và UAV k. Nếu chèn j giữa u và v, tăng quãng đường là:

```math
\Delta D_{kj}(u,v)=d_{uj}+d_{jv}-d_{uv}.
```

Các mức tăng mục tiêu/tài nguyên tương ứng là:

```math
\Delta P=\pi_j q_{kj},\qquad
\Delta T_k=\frac{\Delta D}{v_k}+\tau,\qquad
\Delta E_k=\frac{P_k^{fly}\Delta D/v_k+P_k^{obs}\tau}{3600}.
```

Trong mô hình này, tăng P không phụ thuộc vị trí chèn. Vị trí có ΔD nhỏ nhất đồng thời có tăng thời gian và năng lượng nhỏ nhất. Vì vậy, **với cùng cặp ô/UAV và cùng các hành trình còn lại**, các vị trí đắt hơn không tạo thêm một lựa chọn Pareto tốt hơn về P/E hay tính khả thi. Có thể nén các lựa chọn vị trí thành một đại diện rẻ nhất, rồi chỉ tính fitness đầy đủ cho kế hoạch đại diện.

Điều này không bảo đảm lựa chọn ô/UAV tối ưu, cũng không bảo đảm nghiệm toàn cục. Trong prototype, ô và UAV vẫn được chọn ngẫu nhiên; áp lực chọn lọc/acceptance quyết định hướng tiến triển.

Lập luận còn áp dụng khi q thay đổi theo ô, miễn q không phụ thuộc thứ tự/thời điểm và tài nguyên vẫn tăng đơn điệu theo quãng đường cho UAV cố định. Nếu thêm gió, chi phí quay đầu, thời gian di chuyển phụ thuộc thời điểm hoặc q giảm theo thời gian, một vị trí có thể tốt về năng lượng nhưng kém về thời gian/phát hiện; khi đó phải giữ tập vị trí Pareto thay vì chỉ vị trí ngắn nhất.

## 4. Điều kiện tổng quát hóa của prototype

- Bộ toán tử dùng N, K, tập ô được chọn và ma trận khoảng cách; không gắn với lưới 16×16 hoặc chỉ số hotspot cụ thể.
- Thử nghiệm trên hai bộ chọn lọc EA giúp kiểm tra khả năng dùng lại cơ chế, thay vì gắn vào riêng một thuật toán.
- Scenario, miền nhiệm vụ và tài nguyên được thay đổi với tham số đã đóng băng. Đây là kiểm chứng thực nghiệm trong lớp mô hình hiện tại.
- Unit test có hai UAV và q khác nhau theo ô; điều đó kiểm tra tính đúng của mã, chưa chứng minh hiệu năng trên mọi cấu hình q/fleet.
- Chưa có cơ sở suy rộng ưu thế sang các mô hình vật lý/quan sát khác hoặc toàn bộ họ EA.

## 5. Thiết kế tiếp theo: thích nghi theo cặp toán tử

Phần này **chưa được triển khai hoặc kiểm chứng** trong lượt thí nghiệm hiện tại.

Ablation có thể cho thấy hai thành phần yếu khi dùng riêng nhưng mạnh khi kết hợp. Một bộ chọn toán tử thích nghi đánh giá từng thành phần riêng lẻ có nguy cơ loại bỏ sớm một thành phần cần thiết cho tổ hợp tốt. Hướng cần kiểm chứng là gán credit cho **cặp**:

| Nhánh | Crossover | Mutation |
| --- | --- | --- |
| A | SBX | PM |
| B | SBX | Theo hành trình |
| C | Giữ cấu trúc | PM |
| D | Giữ cấu trúc | Theo hành trình |

Thiết kế đề xuất:

1. **Khởi động:** phân bổ một số lượt ghép cha cố định cho cả bốn cặp; tính tất cả ứng viên vào ngân sách.
2. **Theo dõi hiệu ứng:** tỷ lệ đổi tập ô/phân công/thứ tự, giữ cạnh, số ô bị decoder loại, đóng góp vào archive và chi phí tính toán.
3. **Gán credit chung:** cập nhật mức tăng HV/chi phí cho cả cặp, có cửa sổ gần để phản ánh giai đoạn tìm kiếm. Không cộng độc lập credit của crossover và mutation.
4. **Chọn có khám phá:** dùng chính sách bandit hoặc phân bổ xác suất có sàn khám phá, nhằm không khóa vào một cặp chỉ do may mắn đầu lượt chạy.
5. **Kiểm soát chi phí:** không sinh thêm ứng viên để chọn tốt nhất mà bỏ khỏi ngân sách; so cả chất lượng theo đánh giá và chất lượng theo thời gian.

Mức tăng HV phụ thuộc archive hiện có và thứ tự đánh giá; đó không phải một reward tĩnh. Một thiết kế credit đáng tin cần đối chiếu trên cùng cha, hoặc ít nhất phân bổ cha/ngân sách ghép cặp, rồi kiểm tra độ nhạy với cửa sổ và chính sách khám phá.

Giả thuyết có thể bác bỏ: **thích nghi theo cặp tạo front tốt hơn hoặc cùng chất lượng với chi phí thấp hơn chọn độc lập, đặc biệt khi loại quyết định hữu ích thay đổi theo giai đoạn và mức chặt tài nguyên**. Nếu không vượt được cơ chế cố định D và các baseline trực tiếp trên hành trình, chưa có lý do giữ phần thích nghi phức tạp hơn.

## 6. Kiểm chứng cần có trước khi coi là thuật toán mới

- Đối chứng với cả bốn baseline, cơ chế cố định D và bộ chọn crossover/mutation **độc lập**.
- Ablation reward theo HV, reward theo loại quyết định, credit chung/riêng, có/không điều chỉnh theo chi phí.
- Giữ lại scenario/seed chưa dùng để thiết kế bộ thích nghi; các trường hợp đã xem trong lượt hiện tại không còn là kiểm chứng mới cho một thiết kế được sửa từ kết quả đó.
- Tăng số seed và số instance độc lập; tách hiệu ứng thay tham số PM/SBX khỏi hiệu ứng cấu trúc của cơ chế.
- Đối chiếu tài liệu về memetic routing, adaptive operator selection và joint credit assignment. Tổ hợp các kỹ thuật quen thuộc hoặc thắng vài baseline chưa tự xác lập tính mới.

Đóng góp có thể hướng tới là một **nguyên tắc điều phối biến đổi theo quyết định, sự tương tác và chi phí**, với bằng chứng qua nhiều mô hình/tập kiểm chứng, thay vì chỉ thêm một heuristic vào NSGA-II rồi đặt tên mới.
