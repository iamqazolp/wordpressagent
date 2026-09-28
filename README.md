# WordPress Agent - AI Viết & Đăng Bài Đa Nền Tảng (WordPress / WooCommerce)

Hệ thống Agent tự động hóa quy trình nghiên cứu, tạo bài viết chuẩn SEO và đăng bài đồng thời lên nhiều website WordPress / WooCommerce với tính năng **chống trùng lặp nội dung (Randomize)**.

---

## ✨ Tính Năng Nổi Bật

- 🤖 **AI Content chuẩn SEO & Kỹ thuật:** Tạo bài viết giàu thành phần (Bảng thông số HTML chuẩn, phân tích cấu tạo chi tiết, ưu điểm, slideshow ảnh sản phẩm), không văn mẫu sáo rỗng (*anti-slop*), không bịa thông tin liên hệ.
- 🌐 **Đăng đồng thời nhiều Website:** Chọn một hoặc nhiều website cùng lúc chỉ bằng các ô tích chọn (*Checkbox*).
- 🎲 **Tính năng Randomize độc bản:** Khi chọn nhiều website, AI tự động thay đổi văn phong, góc nhìn trọng tâm và cấu trúc câu để mỗi website sở hữu một bài viết **duy nhất**, tránh thuật toán phạt trùng lặp nội dung (*Duplicate Content*) của Google nhưng vẫn bảo toàn 100% bảng thông số kỹ thuật.
- ⚙️ **Quản lý Website trực quan:** Thêm, chỉnh sửa, xóa và kiểm tra kết nối (*Test Connection*) các website trực tiếp trên giao diện UI mà không cần can thiệp code hay khởi động lại server.
- 📝 **Tùy chỉnh gợi ý viết bài:** Cho phép người dùng nhập yêu cầu riêng, phong cách mong muốn hoặc lưu ý kỹ thuật để AI bám sát khi tạo bài.
- 🖼️ **Xem trước (Preview) theo từng trang:** Kiểm tra nội dung, tiêu đề và hình ảnh của từng website trước khi quyết định bấm đăng hàng loạt.
- 📦 **Linh hoạt hình thức đăng:** Hỗ trợ đăng dưới dạng **Sản phẩm WooCommerce** (đầy đủ giá, ảnh đại diện, gallery, mô tả ngắn & chi tiết) hoặc **Bài viết Blog WordPress**.

---

## 🛠️ Yêu Cầu Hệ Thống

- **Python:** 3.10 trở lên
- **Hệ điều hành:** macOS, Linux hoặc Windows

---

## 🚀 Hướng Dẫn Cài Đặt

### 1. Tạo môi trường ảo & Cài đặt thư viện

```bash
# Tạo virtual environment
python3 -m venv .venv

# Kích hoạt virtual environment
# Trên macOS / Linux:
source .venv/bin/activate
# Trên Windows:
# .venv\Scripts\activate

# Cài đặt các thư viện cần thiết
pip install -r requirements.txt
```

### 2. Cấu hình file `.env`

Tạo hoặc cập nhật file `.env` ở thư mục gốc:

```env
# Gemini API Key (Bắt buộc)
# Có thể dùng API key trực tiếp từ Google AI Studio hoặc qua ShopAIKey
GEMINI_API_KEY=your_gemini_api_key

# SerpAPI Key (Tùy chọn - Dùng để tự động tìm kiếm tài liệu sản phẩm trên Google)
SERP_API_KEY=your_serpapi_key
```

> [!NOTE]
> Thông tin kết nối các website WordPress/WooCommerce hiện tại đã được chuyển sang quản lý trực quan tại giao diện tab **"⚙️ Quản Lý Website"** và lưu trữ an toàn trong file `config/sites.json` (file này đã được đưa vào `.gitignore` để đảm bảo bảo mật tuyệt đối).

### 3. Khởi động ứng dụng

```bash
python app.py
```

Ứng dụng sẽ khởi chạy tại: **[http://localhost:7860](http://localhost:7860)**

---

## 📖 Hướng Dẫn Sử Dụng

### Tab 1: ✍️ Tạo & Đăng Bài Viết

1. **Chọn website cần đăng:** Tích chọn 1 hoặc nhiều website trong danh sách.
2. **Chọn Prompt Template:** Chọn mẫu prompt viết bài phù hợp theo từng ngành hàng.
3. **Bật/Tắt tính năng Randomize:** 
   - *Bật (Mặc định):* Mỗi trang web sẽ nhận được một phiên bản bài viết độc bản, phong cách hành văn và góc nhìn khác nhau.
   - *Tắt:* Tất cả các website được chọn sẽ dùng chung một nội dung bài viết.
4. **Nhập thông tin sản phẩm:**
   - **Tên sản phẩm:** (Ví dụ: `Pa lăng cáp điện 1T x 12M`)
   - **Gợi ý viết bài (Tùy chọn):** Nhập yêu cầu riêng (ví dụ: *"Nhấn mạnh động cơ 100% dây đồng và chuẩn kháng nước IP54"*).
   - **Hình ảnh sản phẩm:** Tải lên một hoặc nhiều hình ảnh thực tế.
   - **Nguồn tham khảo (Tùy chọn):** Nhập URL bài viết mẫu hoặc để trống để AI tự động tìm kiếm.
5. **Tạo bài viết:** Nhấn nút **"🚀 Bắt đầu tạo bài viết"** và chờ AI xử lý.
6. **Xem trước & Chỉnh sửa trực tiếp:** 
   - Dùng ô chọn website để kiểm tra nội dung và tiêu đề bài viết tạo cho từng trang.
   - Chỉnh sửa nhanh tiêu đề ngay trên ô text.
   - Bấm **"🔄 Chuyển đổi chế độ (Xem / Chỉnh sửa HTML)"** để mở trình sửa mã HTML trực tiếp, sau đó bấm **"💾 Lưu mã HTML đã sửa"**.
7. **Đăng bài:** Chọn hình thức đăng (*Sản phẩm WooCommerce* hoặc *Bài viết Blog*) rồi nhấn **"📤 Đăng lên tất cả website đã chọn"**.

---

### Tab 2: 📦 Tạo & Đăng Hàng Loạt (CSV / Excel)

1. **Hỗ trợ định dạng:** Tải lên file `.csv` hoặc bảng tính Excel (`.xlsx`, `.xls`).
2. **Cấu trúc cột linh hoạt (tiếng Việt hoặc tiếng Anh):**
   - `product_name` hoặc `Tên sản phẩm` *(bắt buộc)*
   - `ref_urls` hoặc `URL tham khảo` *(tùy chọn)*
   - `notes` hoặc `Ghi chú AI` *(tùy chọn)*
   - `regular_price` hoặc `Giá gốc` *(tùy chọn)*
   - `sale_price` hoặc `Giá khuyến mại` *(tùy chọn)*
3. **Thao tác hàng loạt:**
   - **Tùy chọn 1:** Chỉ tạo bài hàng loạt để kiểm tra kết quả trước.
   - **Tùy chọn 2:** Tự động tạo bài và đăng trực tiếp lên tất cả website được chọn.

---

### Tab 3: 📅 Lịch Đăng Bài (Scheduler)

1. **Lên lịch đăng bài tự động:** Chọn ngày giờ cụ thể để hệ thống tự động xuất bản bài viết lên các website mà không cần thao tác thủ công.
2. **Quản lý tác vụ:** Theo dõi danh sách công việc đang chờ chạy, hủy hoặc chỉnh sửa lịch trình dễ dàng.

---

### Tab 4: 🕒 Lịch Sử Đăng Bài

1. **Xem danh sách bài đăng:** Bảng thống kê chi tiết toàn bộ các bài viết và sản phẩm đã tạo và đăng qua hệ thống.
2. **Lọc theo website:** Dễ dàng lọc bài theo từng website cụ thể hoặc xem tất cả.
3. **Tra cứu nhanh:** Hiển thị trực tiếp trạng thái đăng, ngày giờ, ID và link mở thẳng bài viết trên WordPress/WooCommerce.

---

### Tab 5: 📝 Quản Lý Template

1. **Quản lý mẫu prompt:** Tạo, xem, chỉnh sửa hoặc xóa các mẫu prompt viết bài theo từng ngành hàng cụ thể.
2. **Mẫu mặc định tối ưu:** Tích hợp sẵn mẫu prompt chuẩn kỹ thuật, tự động giảm thiểu lặp từ và tối ưu bảng thông số.

---

### Tab 6: ⚙️ Quản Lý Website

1. **Xem danh sách website:** Bảng thống kê hiển thị tên website, đường dẫn URL, và trạng thái cấu hình.
2. **Thêm website mới:**
   - Trong dropdown chọn: `➕ Thêm website mới`.
   - Nhập **Tên hiển thị**, **URL**, **WooCommerce Client Key (`ck_...`)**, **Client Secret (`cs_...`)**.
   - Nhấn **"🔌 Kiểm tra kết nối"** để hệ thống kiểm tra cả WordPress REST API và WooCommerce API.
   - Nhấn **"💾 Lưu cấu hình website"**.
3. **Chỉnh sửa / Xóa:**
   - Chọn website cần sửa trong danh sách để cập nhật thông tin hoặc bấm **"🗑️ Xóa website này"**.

---

## 🔒 Bảo Mật & Lưu Trữ Dữ Liệu

- **Cơ sở dữ liệu SQLite & Mã hóa Fernet:** Toàn bộ thông tin nhạy cảm (WooCommerce Client Key, Secret Key, WordPress Application Password) được mã hóa bằng thuật toán `Fernet` (khóa mã hóa sinh ngẫu nhiên lưu trong `.env`) và lưu trữ trong CSDL SQLite (`data/wordpress_agent.db`).
- **An toàn mã nguồn:** Các file nhạy cảm (`.env`, `data/`, `config/sites.json*`) đều nằm trong `.gitignore` và không bao giờ bị đẩy lên kho mã nguồn.
- **Trạng thái bài đăng an toàn:** Mặc định các bài đăng sẽ được đưa lên website ở trạng thái **Bản nháp (Draft)** để quản trị viên có thể xem xét và phê duyệt trước khi xuất bản chính thức.
