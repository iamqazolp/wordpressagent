# WordPress Agent — AI viết & đăng bài đa website (WordPress / WooCommerce)

Công cụ chạy ngay trên máy của bạn: nhập tên sản phẩm → AI viết bài chuẩn SEO → xem trước, chỉnh sửa → đăng (hoặc hẹn giờ đăng) lên một hoặc nhiều website WordPress / WooCommerce. Mỗi website nhận một phiên bản nội dung khác nhau để tránh trùng lặp.

---

## ✨ Tính năng

- 🤖 **AI viết bài chuẩn SEO:** bảng thông số, ưu điểm, mô tả ngắn; có thể nhập gợi ý riêng cho AI. Có thanh điểm SEO tham khảo (không chặn đăng).
- 🌐 **Đăng nhiều website cùng lúc**, mỗi site một bản nội dung khác nhau (Randomize).
- 🏷️ **Danh mục & Tag thông minh:** AI gợi ý danh mục có thật trên website + tag; sửa tay được ở mọi bước (kể cả bài đã lưu và bài đã hẹn giờ).
- 🖼️ **Xử lý ảnh:** nén/đổi kích thước, chèn logo watermark, tách nền (tuỳ chọn).
- 📦 **Hàng loạt từ CSV / Excel.**
- 📅 **Hẹn giờ đăng tự động** (giờ Việt Nam, GMT+7).
- 📚 **Kho bài viết:** lưu nháp, sửa, đăng lại, **cập nhật bài đã đăng** (không đăng trùng), liên kết bài WordPress có sẵn.
- 🔍 **Phát hiện bài trùng** trên website trước khi đăng.
- 🌐 **Xem sản phẩm/bài đang có trên WordPress** (chỉ đọc) và làm mới trạng thái bài đã đăng.
- 📊 **Dashboard:** số bài theo trạng thái, biểu đồ 30 ngày, bài gần đây, tình trạng kết nối website.

---

## 🚀 Cài đặt (làm một lần)

**Cần:** Python **3.11 trở lên** (khuyến nghị 3.12) — tải tại <https://www.python.org/downloads/> (trên Windows nhớ tick **"Add python.exe to PATH"**) và kết nối Internet.

1. Giải nén gói `wordpress-agent-x.y.z.zip` vào một thư mục cố định (ví dụ `C:\WordPressAgent` hoặc `~/WordPressAgent`).
2. Chạy file cài đặt:
   - **Windows:** bấm đúp `install.bat`
   - **macOS / Linux:** mở Terminal trong thư mục đó, chạy `./install.sh`
3. Khi cài xong, file `.env` được tạo sẵn (Windows tự mở bằng Notepad). Điền **`GEMINI_API_KEY`** (bắt buộc) rồi lưu lại. Các mục khác có thể để nguyên:

   | Biến | Ý nghĩa |
   |---|---|
   | `GEMINI_API_KEY` | Khoá AI (bắt buộc) |
   | `GEMINI_BASE_URL`, `GEMINI_MODEL` | Địa chỉ/mô hình AI (mặc định đã đặt sẵn) |
   | `SERP_API_KEY` | Tuỳ chọn: tự tìm tài liệu sản phẩm trên Google. Để trống thì nhập URL tham khảo bằng tay |
   | `ENCRYPTION_KEY` | **Tự sinh, đừng sửa/xoá** — xem phần Sao lưu |
   | `APP_USER`, `APP_PASSWORD` | Tuỳ chọn: đặt tên đăng nhập + mật khẩu cho giao diện |

4. Chạy ứng dụng: **Windows** bấm đúp `run.bat` · **macOS/Linux** `./run.sh`. Trình duyệt tự mở tại <http://127.0.0.1:7860>.

> Mặc định ứng dụng **chỉ truy cập được từ chính máy bạn**. Nếu muốn dùng từ máy khác trong mạng, đặt `HOST=0.0.0.0` **và** `APP_USER`/`APP_PASSWORD` trong `.env`.

---

## 🔌 Kết nối website WordPress / WooCommerce

Vào tab **⚙️ Quản Lý Website → ➕ Thêm website mới** và điền:

| Ô | Lấy ở đâu |
|---|---|
| **URL** | Địa chỉ website, ví dụ `https://example.com` |
| **Client Key / Client Secret** (`ck_…` / `cs_…`) | WordPress admin → **WooCommerce → Cài đặt → Nâng cao → REST API → Thêm khoá** (quyền **Đọc/Ghi**) |
| **WP Username + Application Password** | WordPress admin → **Người dùng → Hồ sơ** → mục **Application Passwords** → đặt tên, bấm *Add*, sao chép mật khẩu. Cần để **tải ảnh lên** và **đăng Blog Post** |

Bấm **🔌 Kiểm tra kết nối** (kiểm tra cả WordPress và WooCommerce) rồi **💾 Lưu**. Mật khẩu/khoá được **mã hoá** trước khi lưu.

---

## 📖 Cách dùng

### 📊 Dashboard
Tổng quan số bài, biểu đồ, bài gần đây. Bấm **🩺 Kiểm tra kết nối** để xem website nào đang lỗi (không tự chạy khi mở trang).

### ✍️ Tạo & Đăng Bài
1. Chọn website, template, nhập tên sản phẩm (+ gợi ý cho AI, ảnh, URL tham khảo nếu có) → **🚀 Bắt đầu tạo bài viết**.
2. Xem trước từng website, sửa tiêu đề/HTML/danh mục/tag/giá.
3. **🔍 Kiểm tra bài trùng** (khuyến nghị), rồi chọn:
   - **💾 Lưu vào hệ thống** (chưa đăng), hoặc
   - **📤 Đăng lên các website đã chọn** (mặc định ở trạng thái *draft* để duyệt trước), hoặc
   - **⏰ Hẹn giờ đăng** (chọn mốc nhanh hoặc ngày giờ cụ thể).

### 📦 Tạo Hàng Loạt
Tải file `.csv`/`.xlsx` với các cột (tiếng Việt hoặc Anh đều được): `product_name`/`Tên sản phẩm` *(bắt buộc)*, `ref_urls`, `notes`, `regular_price`/`Giá gốc`, `sale_price`/`Giá khuyến mại`. Có file mẫu trong `samples/`. Chọn **chỉ lưu nháp** hoặc **tạo & đăng ngay**.

### 📅 Lịch Đăng Bài
Theo dõi/hủy/xóa các lịch hẹn; sửa danh mục & tag của lịch còn *chờ*.

> ⚠️ **Lịch hẹn chỉ chạy khi ứng dụng đang mở.** Nếu tắt máy/tắt ứng dụng đúng giờ hẹn, bài sẽ không được đăng.

### 📚 Kho Bài Viết & Lịch Sử
- Sửa nội dung/giá/ảnh, **🚀 Đăng ngay**, hoặc **⬆️ Cập nhật bài WP đã có** (ghi đè đúng bài đã đăng, không tạo bản trùng; ảnh được tải lại).
- Mục **🔄 Đồng bộ với WordPress**: kiểm tra bài trùng · liên kết với bài WordPress có sẵn (nhập ID bài) · làm mới trạng thái (nháp → đã đăng, thùng rác…) · **chuyển bài vào thùng rác WordPress** (phải tick ô xác nhận; khôi phục được trong wp-admin, **không xóa vĩnh viễn**).
- **🗑️ Xóa bài này** chỉ xóa bản ghi trong ứng dụng, không đụng website.

### 🌐 Trên WordPress
Xem danh sách sản phẩm/bài đang có trên website (chỉ đọc), tìm theo tên, lấy **WP ID** để liên kết.

### 📝 Quản Lý Template · ⚙️ Quản Lý Website
Quản lý mẫu prompt theo ngành hàng; thêm/sửa/xóa/kiểm tra website, logo watermark.

---

## 💾 Sao lưu & khôi phục (quan trọng)

Dữ liệu của bạn nằm ở: thư mục `data/` (cơ sở dữ liệu, logo) và file `.env`. **Mất `ENCRYPTION_KEY` trong `.env` = không giải mã lại được mật khẩu các website đã lưu.**

- **Tự động:** mỗi lần mở app, nếu đã quá 20 giờ kể từ bản trước thì tự chụp cơ sở dữ liệu vào `data/backups/` (giữ 7 bản).
- **Sao lưu đầy đủ (nên làm định kỳ và trước khi cập nhật):** Windows bấm đúp `backup.bat` · macOS/Linux `./backup.sh`. Tạo file `backups/wordpress-agent-backup-….zip` gồm cơ sở dữ liệu + `.env` + logo. **Hãy chép file này ra ổ ngoài/nơi riêng tư** — nó chứa khoá mã hoá và API key, đừng gửi công khai.
- **Khôi phục:** tắt ứng dụng, rồi chạy `python tools/backup.py restore <file.zip>` (trong môi trường `.venv`: Windows `.venv\Scripts\python tools\backup.py restore file.zip`, macOS/Linux `.venv/bin/python tools/backup.py restore file.zip`). Dữ liệu hiện tại được lưu thành bản an toàn trước khi ghi đè.

## ⬆️ Cập nhật phiên bản mới

1. **Sao lưu đầy đủ** như trên.
2. Tắt ứng dụng, giải nén gói mới **đè lên thư mục cũ** (gói không chứa `data/` và `.env` nên dữ liệu của bạn không bị ghi đè).
3. Chạy lại `install.bat` / `./install.sh` (cập nhật thư viện), rồi `run.bat` / `./run.sh`. Cấu trúc dữ liệu tự nâng cấp và tự chụp bản sao lưu trước khi nâng cấp.

---

## ⚠️ Lưu ý

- Chạy **một cửa sổ ứng dụng** tại một thời điểm (chạy hai bản cùng dữ liệu sẽ làm lịch hẹn đăng bị trùng).
- Mọi thời gian trong ứng dụng đều theo **giờ Việt Nam (GMT+7)**.
- Nội dung do AI viết: luôn xem lại trước khi công khai. Điểm SEO chỉ mang tính tham khảo.
- Mặc định bài đăng ở trạng thái **Bản nháp** để bạn duyệt trước khi xuất bản.

## 🛟 Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| `install` báo không có Python | Cài Python 3.11+ (tick *Add to PATH* trên Windows) rồi chạy lại |
| Mở app báo chưa cấu hình `GEMINI_API_KEY` | Điền khoá vào `.env`, tắt và chạy lại |
| Kiểm tra kết nối báo lỗi WC/WP | Kiểm tra URL (có `https://`), khoá WooCommerce quyền Đọc/Ghi, Application Password; website phải bật REST API |
| Không tải được ảnh | Cần điền **WP Username + Application Password** của website |
| Cổng 7860 đang được dùng | Đặt `PORT=7861` trong `.env` |
| Cần hỗ trợ | Chụp màn hình cửa sổ đen (log) khi lỗi và gửi cho người hỗ trợ — **đừng** gửi file `.env` |

## 🔒 Bảo mật

- Khoá/mật khẩu website được mã hoá (Fernet) trước khi lưu vào `data/wordpress_agent.db`; khoá mã hoá nằm trong `.env`.
- `.env`, `data/` không nằm trong gói phát hành và không nên chia sẻ.
- Ứng dụng mặc định chỉ lắng nghe trên `127.0.0.1` (chỉ máy bạn truy cập được).

---

## 🧑‍💻 Dành cho nhà phát triển

```bash
pip install -r requirements.lock      # hoặc requirements.txt
pip install -r requirements-dev.txt   # pytest, pyflakes
python -m pytest -q                   # chạy toàn bộ test
python tools/make_release.py          # đóng gói dist/wordpress-agent-<VERSION>.zip (chỉ file đã commit)
```

Kiến trúc phân lớp `ui/ → services/ → core/ → db/` (có test bảo vệ) — xem [ARCHITECTURE.md](ARCHITECTURE.md).
