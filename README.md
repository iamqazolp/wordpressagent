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
2. **Bật/Tắt tính năng Randomize:** 
   - *Bật (Mặc định):* Mỗi trang web sẽ nhận được một phiên bản bài viết độc bản, phong cách hành văn và góc nhìn khác nhau.
   - *Tắt:* Tất cả các website được chọn sẽ dùng chung một nội dung bài viết.
3. **Nhập thông tin sản phẩm:**
   - **Tên sản phẩm:** (Ví dụ: `Pa lăng cáp điện 1T x 12M`)
   - **Gợi ý viết bài (Tùy chọn):** Nhập yêu cầu riêng (ví dụ: *"Nhấn mạnh động cơ 100% dây đồng và chuẩn kháng nước IP54"*).
   - **Hình ảnh sản phẩm:** Tải lên một hoặc nhiều hình ảnh thực tế.
   - **Nguồn tham khảo (Tùy chọn):** Nhập URL bài viết mẫu hoặc để trống để AI tự động tìm kiếm.
4. **Tạo bài viết:** Nhấn nút **"🚀 Bắt đầu tạo bài viết"** và chờ AI xử lý.
5. **Xem trước (Preview):** 
   - Dùng ô chọn website để kiểm tra nội dung và tiêu đề bài viết tạo cho từng trang.
   - Có thể chỉnh sửa trực tiếp nội dung hoặc tiêu đề tại ô xem trước.
6. **Đăng bài:** Chọn hình thức đăng (*Sản phẩm WooCommerce* hoặc *Bài viết Blog*) rồi nhấn **"📤 Đăng lên tất cả website đã chọn"**.

---

### Tab 2: ⚙️ Quản Lý Website

1. **Xem danh sách website:** Bảng thống kê hiển thị tên website, đường dẫn URL, và trạng thái cấu hình.
2. **Thêm website mới:**
   - Trong dropdown chọn: `➕ Thêm website mới`.
   - Nhập **Tên hiển thị**, **URL**, **WooCommerce Client Key (`ck_...`)**, **Client Secret (`cs_...`)**.
   - Nhấn **"🔍 Kiểm tra kết nối"** để đảm bảo API key hoạt động chính xác.
   - Nhấn **"💾 Lưu cấu hình website"**.
3. **Chỉnh sửa / Xóa:**
   - Chọn website cần sửa trong danh sách để cập nhật thông tin hoặc bấm **"🗑️ Xóa website này"**.

---

## 🔒 Bảo Mật & Lưu Trữ Dữ Liệu

- **Bảo mật API Key:** Toàn bộ thông tin nhạy cảm (API Key, Secret Key, mật khẩu ứng dụng) được lưu trong `.env` và `config/sites.json`. Cả hai file đều nằm trong `.gitignore` và không bao giờ bị lộ lên GitHub.
- **Trạng thái bài đăng:** Mặc định các bài đăng sẽ được đưa lên website ở trạng thái **Bản nháp (Draft)** để quản trị viên có thể xem xét và phê duyệt trước khi xuất bản chính thức.
