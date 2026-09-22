# WordPress Agent - Kho Đèn Trang Trí

Ứng dụng tự động viết và đăng bài lên WordPress/WooCommerce.

## Yêu Cầu

- Python 3.10 trở lên
- Kết nối internet

## Cài Đặt Lần Đầu

### 1. Cài thư viện Python

```bash
pip install -r requirements.txt
```

### 2. Cấu hình API Keys

Mở file `.env` và thêm vào:

```env
# WooCommerce (đã có sẵn)
client_key=ck_xxx
client_secret=cs_xxx
url=khodentrangtri.com

# Thêm mới - bắt buộc để viết bài
GEMINI_API_KEY=your_gemini_key

# Thêm mới - bắt buộc để ĐĂNG bài lên WordPress
WP_USER=ten_dang_nhap_wordpress
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx

# Thêm mới - tùy chọn (để tìm kiếm tự động)
SERP_API_KEY=your_serpapi_key
```

**Lấy Gemini API Key (miễn phí):**
→ Vào https://aistudio.google.com/app/apikey → Nhấn "Create API key"

**Tạo WordPress Application Password (để đăng bài):**
1. Đăng nhập vào `khodentrangtri.com/wp-admin`
2. Vào **Users → Profile** (hoặc Your Profile)
3. Kéo xuống phần **Application Passwords**
4. Nhập tên bất kỳ (VD: "WordPress Agent") → Nhấn **Add New Application Password**
5. Copy mật khẩu được tạo ra → dán vào `WP_APP_PASSWORD=` trong file `.env`
6. `WP_USER` = tên đăng nhập WordPress của bạn (thường là `admin`)

**Lấy SerpAPI Key (miễn phí 100 lần/tháng):**
→ Vào https://serpapi.com → Đăng ký → Lấy API key

### 3. Khởi động ứng dụng

```bash
python app.py
```

Trình duyệt sẽ tự mở tại http://localhost:7860

## Cách Sử Dụng

1. **Nhập tên sản phẩm** - VD: "đèn chùm pha lê K9"
2. **Upload ảnh** - Kéo và thả ảnh sản phẩm vào ô Upload
3. **(Tùy chọn)** Dán thêm URL bài tham khảo
4. Nhấn **"Tạo bài viết"** → Chờ AI viết (30-60 giây)
5. Xem preview, chỉnh sửa tiêu đề nếu cần
6. Nhấn **"Đăng bài lên WordPress"**

## Thêm Website Mới

Thêm vào file `.env`:

```env
SITE2_NAME=ten-hien-thi
SITE2_URL=https://website2.com
SITE2_CLIENT_KEY=ck_xxx
SITE2_CLIENT_SECRET=cs_xxx
```

Khởi động lại app để áp dụng.

## Ghi Chú

- Bài sẽ được đăng ở trạng thái **Nháp** theo mặc định → vào WordPress Admin để kiểm tra rồi mới đăng công khai
- Nếu không cấu hình SERP_API_KEY, cần nhập URL tham khảo thủ công
