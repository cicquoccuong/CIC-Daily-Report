# Hướng Dẫn Cài Đặt Hệ Thống CIC Daily Report

> Thời gian ước tính: 15-20 phút. Không cần biết lập trình.

## Tổng Quan

Hệ thống CIC Daily Report tự động thu thập tin tức crypto, tạo báo cáo bằng AI, và gửi qua Telegram Bot mỗi ngày.

**Bạn cần:**
- Tài khoản GitHub (miễn phí)
- Tài khoản Google (cho Google Sheets)
- Tài khoản Telegram

---

## Bước 1: Fork Repository

1. Vào trang GitHub của dự án
2. Nhấn nút **"Fork"** (góc trên bên phải)
3. Chờ GitHub tạo bản sao vào tài khoản của bạn

> Fork (bản sao) = tạo một phiên bản riêng của dự án trên tài khoản bạn.

---

## Bước 2: Tạo Google Cloud Service Account

1. Vào [Google Cloud Console](https://console.cloud.google.com/)
2. Tạo dự án mới (New Project): đặt tên "CIC Daily Report"
3. Bật **Google Sheets API**:
   - Vào "APIs & Services" → "Library"
   - Tìm "Google Sheets API" → nhấn **Enable**
4. Tạo Service Account:
   - Vào "APIs & Services" → "Credentials"
   - Nhấn **"Create Credentials"** → chọn "Service Account"
   - Đặt tên: `cic-daily-report`
   - Nhấn **"Done"**
5. Tạo Key JSON:
   - Nhấn vào Service Account vừa tạo
   - Tab **"Keys"** → "Add Key" → "Create new key"
   - Chọn **JSON** → nhấn "Create"
   - File JSON sẽ tự tải về — **giữ file này cẩn thận!**

> Service Account = tài khoản "robot" để hệ thống truy cập Google Sheets tự động.

---

## Bước 3: Tạo Google Sheets

1. Vào [Google Sheets](https://sheets.google.com/) → tạo bảng tính mới
2. Đặt tên: `CIC Daily Report Data`
3. Chia sẻ (Share) bảng tính cho Service Account:
   - Nhấn nút **"Share"**
   - Paste email của Service Account (có dạng `cic-daily-report@xxx.iam.gserviceaccount.com`)
   - Chọn quyền **"Editor"**
4. Lấy **Spreadsheet ID**: từ URL của bảng tính
   - URL: `https://docs.google.com/spreadsheets/d/ABC123XYZ/edit`
   - ID là phần giữa `/d/` và `/edit`: `ABC123XYZ`

> Hệ thống sẽ tự tạo các tab (sheet) cần thiết khi chạy lần đầu.

### 3b: Cài Google Apps Script (Menu tự động — khuyến nghị)

1. Trong spreadsheet, vào **Extensions** (Tiện ích mở rộng) > **Apps Script**
2. Xóa nội dung `Code.gs` mặc định
3. Copy toàn bộ nội dung file `gas/AutoSetup.gs` vào
4. Tạo file mới (nhấn **+** > **Script**), đặt tên `Menu`
5. Copy toàn bộ nội dung file `gas/Menu.gs` vào
6. Nhấn **Ctrl+S** để lưu
7. Đóng tab Apps Script, **tải lại (F5)** Google Sheets
8. Menu **📊 CIC Daily Report** sẽ xuất hiện
9. Vào **⚙️ Thiết Lập** > **🚀 Thiết Lập Tự Động** — tạo 9 tab + header + định dạng

> Menu giúp tạo sẵn 9 tab với header tiếng Việt, định dạng số, và đóng băng hàng tiêu đề.
> Dữ liệu ghi vào sẽ đẹp và dễ đọc ngay từ đầu.

---

## Bước 4: Tạo Telegram Bot

1. Mở Telegram, tìm **@BotFather**
2. Gửi lệnh `/newbot`
3. Đặt tên bot (ví dụ: "CIC Daily Report Bot")
4. Đặt username (ví dụ: `cic_daily_report_bot`)
5. BotFather sẽ trả về **Bot Token** — lưu lại!
   - Dạng: `7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`
6. Lấy **Chat ID**:
   - Gửi tin nhắn bất kỳ cho bot
   - Mở link: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Tìm `"chat":{"id":123456789}` — số đó là Chat ID

---

## Bước 5: Lấy API Keys

| Tên | Bắt buộc | Nơi lấy | Ví dụ |
|-----|----------|---------|-------|
| `GOOGLE_SHEETS_CREDENTIALS` | ✅ | File JSON từ Bước 2 **encode Base64** (xem bên dưới) | `eyJ0eXBlIjoi...` |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | ✅ | URL Sheets từ Bước 3 | `1BxiMVs0XRA5...` |
| `TELEGRAM_BOT_TOKEN` | ✅ | BotFather từ Bước 4 | `7123456789:AAH...` |
| `TELEGRAM_CHAT_ID` | ✅ | getUpdates từ Bước 4 | `123456789` |
| `GROQ_API_KEY` | ✅ | [console.groq.com](https://console.groq.com/) → API Keys | `gsk_abc...xyz` |
| `GEMINI_API_KEY` | ⬜ | [aistudio.google.com](https://aistudio.google.com/) → API Key | `AIza...` |
| `CRYPTOPANIC_API_KEY` | ✅ | [cryptopanic.com/developers](https://cryptopanic.com/developers/api/) | `abc123...` |
| `FRED_API_KEY` | ⬜ | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) | `abc123...` |
| `SMTP_HOST` | ⬜ | Email backup (Gmail: `smtp.gmail.com`) | `smtp.gmail.com` |
| `SMTP_PORT` | ⬜ | Email backup (Gmail: `587`) | `587` |
| `SMTP_USER` | ⬜ | Email gửi | `you@gmail.com` |
| `SMTP_PASSWORD` | ⬜ | App Password (Gmail) | `xxxx xxxx xxxx xxxx` |
| `SMTP_FROM` | ⬜ | Cùng email | `you@gmail.com` |
| `SMTP_TO` | ⬜ | Email nhận backup | `backup@gmail.com` |

> ✅ = Bắt buộc | ⬜ = Tùy chọn (hệ thống vẫn chạy mà không cần)

### Encode file JSON thành Base64

**Windows (PowerShell):**
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("path\to\key.json"))
```

**Mac/Linux:**
```bash
base64 -w 0 path/to/key.json
```

Kết quả (chuỗi dài) = giá trị cho `GOOGLE_SHEETS_CREDENTIALS`.

---

## Bước 6: Cấu Hình GitHub Secrets

1. Vào repository trên GitHub → **Settings** → **Secrets and variables** → **Actions**
2. Nhấn **"New repository secret"** cho mỗi key ở Bước 5
3. Paste đúng tên và giá trị

> GitHub Secrets = nơi lưu trữ an toàn các mật khẩu/key, không ai có thể xem lại giá trị.

---

## Bước 7: Bật GitHub Actions

1. Vào tab **"Actions"** trên repository
2. Nếu thấy thông báo "Workflows aren't being run on this forked repository" → nhấn **"I understand my workflows, go ahead and enable them"**
3. Kiểm tra 3 workflows đã bật:
   - **Daily Pipeline** — chạy 08:00 VN mỗi ngày
   - **Breaking News** — chạy mỗi giờ
   - **Test** — chạy khi push code

---

## Bước 8: Chạy Test Xác Nhận

1. Vào tab **"Actions"** → chọn **"Daily Pipeline"**
2. Nhấn **"Run workflow"** → **"Run workflow"** (nút xanh)
3. Chờ workflow hoàn thành (2-5 phút)
4. Kiểm tra Telegram — bạn sẽ nhận tin nhắn `[TEST]` xác nhận

**Nếu thành công:** ✅ Hệ thống đã sẵn sàng!

**Nếu thất bại:** Kiểm tra:
- Logs trong GitHub Actions → xem lỗi cụ thể
- Các secret đã đúng chưa (tên viết hoa, không có khoảng trắng thừa)
- Bot Token và Chat ID đúng chưa
- Service Account đã được share Sheets chưa

---

## Hỗ Trợ

Nếu gặp vấn đề, tạo Issue trên GitHub repository kèm:
- Ảnh chụp lỗi (che các thông tin nhạy cảm)
- Bước nào bị lỗi
- Hệ điều hành đang dùng
