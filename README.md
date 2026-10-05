<div align="center">

# WordPress Agent

**Viết và đăng sản phẩm lên nhiều website WordPress / WooCommerce bằng AI, chạy ngay trên máy của bạn.**

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![WooCommerce](https://img.shields.io/badge/WordPress-WooCommerce-21759B?logo=wordpress&logoColor=white)
![Gradio](https://img.shields.io/badge/UI-Gradio-F97316)
![Platform](https://img.shields.io/badge/Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

<!-- ẢNH BÌA: dán ảnh chụp giao diện chính (khuyến nghị 1600x900, PNG) vào docs/images/hero.png -->
<img src="docs/images/hero.png" alt="WordPress Agent" width="880">

</div>

---

## Giới thiệu

Nhập tên sản phẩm, AI viết bài chuẩn SEO, bạn xem trước và chỉnh sửa, rồi đăng ngay hoặc hẹn giờ lên một hay nhiều website. Mỗi website nhận một phiên bản nội dung riêng để tránh trùng lặp.

Dữ liệu và khoá API nằm trên máy của bạn, không qua máy chủ trung gian nào ngoài Gemini và website của bạn.

## Tính năng nổi bật

| | |
|---|---|
| **AI viết bài chuẩn SEO** | Bảng thông số, ưu điểm, mô tả ngắn theo ghi chú của bạn. Có điểm SEO tham khảo, không chặn đăng. |
| **Đa website** | Đăng nhiều website cùng lúc, mỗi site một bản nội dung khác nhau. |
| **Hẹn giờ linh hoạt** | Cùng một giờ hoặc mỗi website một giờ. Hàng loạt có thể giãn cách giữa các bài và các website. |
| **Tạo hàng loạt** | Nhập CSV / Excel, tạo nhiều bài, rồi chọn bài nào đăng, bài nào hẹn giờ. |
| **Kho bài viết** | Lưu nháp, sửa, đăng lại, cập nhật đúng bài đã đăng, chọn nhiều bài để đăng / hẹn giờ / xoá. |
| **Danh mục và tag** | AI gợi ý danh mục có thật trên website, sửa tay được ở mọi bước. |
| **Xử lý ảnh** | Nén WebP, đóng watermark logo, tách nền (tuỳ chọn). Bật hoặc tắt riêng cho từng lần đăng. |
| **Chống đăng trùng** | Kiểm tra bài trùng trên website trước khi đăng, liên kết với bài WordPress có sẵn. |
| **Dashboard** | Số bài theo trạng thái, biểu đồ 30 ngày, tình trạng kết nối từng website. |
| **Không cần terminal** | Cửa sổ khởi động tự cài đặt, khởi động, dừng và sao lưu. |

## Ảnh giao diện

<!-- Dán ảnh chụp vào docs/images/ với đúng tên file bên dưới. Ảnh nào chưa có có thể xoá dòng tương ứng. -->

<table>
  <tr>
    <td width="50%"><img src="docs/images/create.png" alt="Tạo bài"><br><sub><b>Tạo bài:</b> nhập sản phẩm, xem trước từng website, đăng hoặc hẹn giờ.</sub></td>
    <td width="50%"><img src="docs/images/bulk.png" alt="Tạo hàng loạt"><br><sub><b>Tạo hàng loạt:</b> nhập file, chọn bài để đăng hoặc hẹn giờ.</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/images/store.png" alt="Kho bài viết"><br><sub><b>Kho bài viết:</b> sửa, đăng, cập nhật, thao tác nhiều bài.</sub></td>
    <td width="50%"><img src="docs/images/schedule.png" alt="Lịch đăng"><br><sub><b>Lịch đăng:</b> theo dõi, huỷ, xoá, sửa danh mục của lịch chờ.</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/images/dashboard.png" alt="Dashboard"><br><sub><b>Dashboard:</b> tổng quan và tình trạng website.</sub></td>
    <td width="50%"><img src="docs/images/launcher.png" alt="Cửa sổ khởi động"><br><sub><b>Cửa sổ khởi động:</b> cài đặt, chạy, dừng, sao lưu.</sub></td>
  </tr>
</table>

<!-- VIDEO DEMO (tuỳ chọn): dán liên kết YouTube hoặc ảnh GIF vào đây -->

---

## Cài đặt và chạy

**Yêu cầu:** Python **3.11 trở lên** ([tải tại python.org](https://www.python.org/downloads/), trên Windows nhớ tick **Add python.exe to PATH**) và kết nối Internet.

1. Giải nén `wordpress-agent-x.y.z.zip` vào một thư mục cố định, ví dụ `C:\WordPressAgent`.
2. **Bấm đúp `WordPressAgent.pyw`**. Nếu máy không mở được, bấm đúp `Mo-ung-dung.bat`.
3. Cửa sổ khởi động tự làm các việc sau:
   - Lần đầu: cài thư viện (vài phút, có thanh tiến trình, không có cửa sổ đen).
   - Hỏi **khoá Gemini API** và tự ghi vào `.env`. Đổi khoá bất cứ lúc nào bằng nút **Khoá API**.
   - Khởi động ứng dụng và mở trình duyệt tại <http://127.0.0.1:7860>.
4. Lần đầu khởi động có thể mất 1 đến 3 phút. Cửa sổ hiện tiến độ, vui lòng không tắt.

Các nút trong cửa sổ: **Mở trình duyệt**, **Dừng ứng dụng**, **Khởi động lại**, **Khoá API**, **Sao lưu**, **Nhật ký**. Thu nhỏ cửa sổ khi đang dùng, đừng đóng. Muốn tắt, bấm **Dừng ứng dụng** hoặc nút **Tắt ứng dụng** ở đầu trang web (chỉ hoạt động từ chính máy chạy ứng dụng).

> Cách chạy bằng dòng lệnh vẫn dùng được: `install.bat` và `run.bat` (Windows), `./install.sh` và `./run.sh` (macOS / Linux). Trên macOS / Linux có thể mở cửa sổ khởi động bằng `python3 WordPressAgent.pyw`.

### Cấu hình `.env`

File `.env` được tạo tự động, thường không cần sửa tay.

| Biến | Ý nghĩa |
|---|---|
| `GEMINI_API_KEY` | Khoá AI (bắt buộc) |
| `GEMINI_BASE_URL`, `GEMINI_MODEL` | Địa chỉ và mô hình AI (đã đặt sẵn) |
| `SERP_API_KEY` | Tuỳ chọn: tự tìm tài liệu sản phẩm trên Google. Để trống thì nhập URL tham khảo bằng tay |
| `ENCRYPTION_KEY` | Tự sinh, **không sửa hoặc xoá** (xem phần Sao lưu) |
| `PORT` | Cổng chạy, mặc định 7860 |
| `APP_USER`, `APP_PASSWORD` | Tuỳ chọn: tên đăng nhập và mật khẩu cho giao diện |

> Mặc định ứng dụng chỉ truy cập được từ chính máy bạn. Muốn dùng từ máy khác trong mạng, đặt `HOST=0.0.0.0` **và** `APP_USER` / `APP_PASSWORD`.

## Kết nối website

Vào tab **Website**, chọn **Thêm website mới** và điền:

| Ô | Lấy ở đâu |
|---|---|
| **URL** | Địa chỉ website, ví dụ `https://example.com` |
| **Client Key / Client Secret** (`ck_…` / `cs_…`) | WordPress admin: **WooCommerce → Cài đặt → Nâng cao → REST API → Thêm khoá**, quyền **Đọc/Ghi** |
| **WP Username + Application Password** | WordPress admin: **Người dùng → Hồ sơ → Application Passwords**, đặt tên, bấm *Add*, sao chép mật khẩu. **Bắt buộc để tải ảnh lên** |

Bấm **Kiểm tra kết nối** rồi **Lưu**. Mật khẩu và khoá được mã hoá trước khi lưu.

> Một số hosting chặn header `Authorization` nên Application Password đúng vẫn báo lỗi 401. Khi đó nhờ nhà cung cấp hosting mở header này.

---

## Hướng dẫn sử dụng

### Tạo bài

1. Nhập **tên sản phẩm**, thêm ảnh, chọn website và mẫu prompt.
2. **Ghi chú mô tả ngắn** (tuỳ chọn): bảo AI viết mô tả ngắn thế nào. Để trống thì lấy bảng thông số trong bài.
3. Bấm **Tạo bài viết**, xem trước từng website, sửa tiêu đề, danh mục, tag, giá.
4. Chọn **Lưu vào kho**, **Đăng lên các website** (mặc định *draft* để duyệt trước) hoặc **Hẹn giờ đăng**. Hẹn giờ có hai chế độ: cùng một giờ, hoặc mỗi website một giờ.

Sau khi đăng, kết quả báo riêng từng website. Website thiếu ảnh hoặc lỗi WordPress profile được cảnh báo rõ kèm lý do.

### Tạo hàng loạt

1. Tải file `.csv` hoặc `.xlsx` với các cột: `product_name` (bắt buộc), `ref_urls`, `notes`, `regular_price`, `sale_price`. File mẫu nằm trong `samples/`.
2. Bấm **Tạo bài**: toàn bộ bài được lưu vào kho, chưa đăng.
3. Ở mục **Xử lý bài đã tạo**, chọn các bài rồi **Đăng ngay** hoặc **Hẹn giờ** (giờ bắt đầu, khoảng cách giữa các sản phẩm và giữa các website).

### Kho bài viết

- Sửa nội dung, giá, ảnh, rồi **Đăng lên website** hoặc **Cập nhật bài WP** (ghi đè đúng bài đã đăng, không tạo bản trùng).
- **Chọn nhiều bài**: đăng, hẹn giờ hoặc xoá hàng loạt (xoá cần tick xác nhận).
- **Đồng bộ với WordPress**: kiểm tra trùng, liên kết với bài có sẵn, làm mới trạng thái, chuyển bài vào thùng rác WordPress (khôi phục được trong wp-admin, không xoá vĩnh viễn).
- **Xoá** chỉ xoá bản ghi trong ứng dụng, không động tới website.

### Lịch đăng

Theo dõi các lịch hẹn, sửa danh mục và tag của lịch còn chờ. **Huỷ lịch** dừng lịch nhưng giữ bản ghi để xem lại. **Xoá khỏi danh sách** dừng lịch và xoá hẳn bản ghi. Có thể chọn nhiều lịch để huỷ hoặc xoá cùng lúc.

> **Lịch hẹn chỉ chạy khi ứng dụng đang mở.** Tắt máy hoặc tắt ứng dụng đúng giờ hẹn thì bài sẽ không được đăng.

### Các tab khác

- **Dashboard:** tổng quan, biểu đồ, kiểm tra kết nối website.
- **Trên WordPress:** xem sản phẩm đang có trên website (chỉ đọc), lấy WP ID để liên kết.
- **Template:** quản lý mẫu prompt theo ngành hàng.
- **Website:** thêm, sửa, xoá, kiểm tra website; cấu hình logo watermark.

---

## Sao lưu và khôi phục

Dữ liệu của bạn nằm ở thư mục `data/` và file `.env`. **Mất `ENCRYPTION_KEY` trong `.env` đồng nghĩa không giải mã lại được mật khẩu các website đã lưu.**

- **Tự động:** mỗi lần mở app, nếu đã quá 20 giờ từ bản trước thì tự chụp cơ sở dữ liệu vào `data/backups/` (giữ 7 bản).
- **Sao lưu đầy đủ** (nên làm định kỳ và trước khi cập nhật): bấm nút **Sao lưu** trong cửa sổ khởi động, hoặc `backup.bat` (Windows) / `./backup.sh` (macOS, Linux). Kết quả là file `backups/wordpress-agent-backup-….zip` gồm cơ sở dữ liệu, `.env` và logo. File này chứa khoá mã hoá và API key, hãy cất ở nơi riêng tư, đừng gửi công khai.
- **Khôi phục:** tắt ứng dụng rồi chạy `.venv\Scripts\python tools\backup.py restore file.zip` (Windows) hoặc `.venv/bin/python tools/backup.py restore file.zip` (macOS, Linux). Dữ liệu hiện tại được lưu thành bản an toàn trước khi ghi đè.

## Cập nhật phiên bản mới

1. Sao lưu đầy đủ như trên.
2. Tắt ứng dụng, giải nén gói mới **đè lên thư mục cũ**. Gói không chứa `data/` và `.env` nên dữ liệu không bị ghi đè.
3. Bấm đúp lại `WordPressAgent.pyw`. Ứng dụng tự cập nhật thư viện và nâng cấp cấu trúc dữ liệu (có sao lưu trước khi nâng cấp).

---

## Lưu ý

- Chỉ chạy **một cửa sổ ứng dụng** tại một thời điểm. Chạy hai bản cùng dữ liệu sẽ làm lịch hẹn bị trùng.
- Mọi thời gian trong ứng dụng theo **giờ Việt Nam (GMT+7)**.
- Nội dung do AI viết cần được xem lại trước khi công khai. Điểm SEO chỉ mang tính tham khảo.
- Bài đăng mặc định ở trạng thái **bản nháp** để bạn duyệt trước.

## Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| Không có Python, cửa sổ khởi động không mở | Cài Python 3.11+ (tick *Add to PATH* trên Windows) rồi bấm đúp lại `WordPressAgent.pyw`. Lỗi ghi ở `logs/launcher.log` |
| Khởi động lần đầu lâu | Bình thường, có thể 1 đến 3 phút. Theo dõi tiến độ trong khung nhật ký của cửa sổ |
| Báo chưa cấu hình `GEMINI_API_KEY` | Bấm **Khoá API** trong cửa sổ khởi động, điền khoá rồi khởi động lại |
| Kiểm tra kết nối báo lỗi WC / WP | Kiểm tra URL (có `https://`), quyền Đọc/Ghi của khoá WooCommerce, Application Password; website phải bật REST API |
| Không tải được ảnh | Cần điền **WP Username + Application Password**. Thông báo trên màn hình ghi rõ mã lỗi (401, 403, 413…) |
| Cổng 7860 đang được dùng | Bấm **Mở trình duyệt** nếu đó là ứng dụng này, hoặc đặt `PORT=7861` trong `.env` |
| Cần hỗ trợ | Gửi file `logs/app.log` và `logs/launcher.log` (nút **Nhật ký** trong cửa sổ khởi động). **Đừng** gửi file `.env` |

## Bảo mật

- Khoá và mật khẩu website được mã hoá (Fernet) trước khi lưu vào `data/wordpress_agent.db`. Khoá mã hoá nằm trong `.env`.
- `.env` và `data/` không nằm trong gói phát hành và không nên chia sẻ.
- Mặc định ứng dụng chỉ lắng nghe trên `127.0.0.1`, chỉ máy bạn truy cập được.

---

## Dành cho nhà phát triển

```bash
pip install -r requirements.lock      # hoặc requirements.txt
pip install -r requirements-dev.txt   # pytest, pyflakes
python -m pytest -q                   # chạy toàn bộ test
python tools/make_release.py          # đóng gói dist/wordpress-agent-<VERSION>.zip (chỉ file đã commit)
```

Kiến trúc phân lớp `ui/ → services/ → core/ → db/` có test bảo vệ, xem [ARCHITECTURE.md](ARCHITECTURE.md).
