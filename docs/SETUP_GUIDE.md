# Hướng Dẫn Cài Đặt Hệ Thống CIC Daily Report

> Thời gian ước tính: 30-45 phút. Không cần biết lập trình.
> Tài liệu này viết cho người **chưa biết kỹ thuật** — từng bước có hình minh họa và giải thích.

## Tổng Quan

Hệ thống CIC Daily Report tự động:
1. Thu thập tin tức crypto từ nhiều nguồn (RSS, CryptoPanic)
2. Phân tích bằng AI (Groq/Gemini)
3. Tạo báo cáo theo 5 cấp độ thành viên
4. Gửi qua Telegram Bot mỗi ngày lúc 08:00 VN
5. Kiểm tra tin nóng (Breaking News) mỗi giờ

**Bạn cần chuẩn bị:**
- Tài khoản GitHub (miễn phí) — [github.com](https://github.com/)
- Tài khoản Google (cho Google Sheets + Google Cloud)
- Tài khoản Telegram
- Máy tính có trình duyệt web

---

## Bước 1: Fork Repository

**Fork là gì?** Tạo một bản sao của dự án trên tài khoản GitHub của bạn.

1. Đăng nhập GitHub
2. Vào trang repository gốc của CIC Daily Report
3. Nhấn nút **"Fork"** (góc trên bên phải)
4. Chờ GitHub tạo bản sao → bạn sẽ thấy repo mới dạng `tên-bạn/CIC-Daily-Report`

---

## Bước 2: Tạo Google Cloud Service Account

**Service Account là gì?** Tài khoản "robot" để hệ thống tự động đọc/ghi Google Sheets mà không cần bạn đăng nhập.

### 2a. Tạo Project

1. Vào [Google Cloud Console](https://console.cloud.google.com/)
2. Nhấn vào tên project ở thanh trên cùng → **"New Project"**
3. Đặt tên: `CIC Daily Report` → nhấn **"Create"**
4. Chờ tạo xong → chọn project vừa tạo

### 2b. Bật Google Sheets API

> **QUAN TRỌNG:** Phải bật API **trên đúng project** chứa Service Account. Nếu bạn có nhiều project, kiểm tra thanh trên cùng hiển thị đúng tên project.

1. Vào menu ☰ → **"APIs & Services"** → **"Library"**
2. Trong ô tìm kiếm, gõ **"Google Sheets API"**
3. Nhấn vào kết quả **"Google Sheets API"** (biểu tượng bảng tính xanh)
4. Nhấn nút **"Enable"** (nếu đã bật thì hiện "API Enabled" ✅)

### 2c. Tạo Service Account

1. Vào menu ☰ → **"APIs & Services"** → **"Credentials"**
2. Nhấn **"+ Create Credentials"** (nút trên cùng) → chọn **"Service Account"**
3. Đặt tên: `cic-daily-report`
4. Nhấn **"Create and Continue"**
5. Bỏ qua phần "Grant access" → nhấn **"Continue"**
6. Bỏ qua phần "Grant users access" → nhấn **"Done"**

### 2d. Tạo Key JSON

1. Trong trang Credentials, tìm phần **"Service Accounts"**
2. Nhấn vào email service account vừa tạo (dạng `cic-daily-report@xxx.iam.gserviceaccount.com`)
3. Chuyển sang tab **"Keys"**
4. Nhấn **"Add Key"** → **"Create new key"**
5. Chọn **JSON** → nhấn **"Create"**
6. File JSON sẽ tự tải về máy

> ⚠️ **BẢO MẬT:** File JSON này chứa private key — **KHÔNG chia sẻ**, **KHÔNG paste lên chat/forum**. Nếu lỡ lộ → xóa key cũ và tạo key mới ngay (xem phần Xử Lý Sự Cố).

### 2e. Encode file JSON thành Base64

**Base64 là gì?** Chuyển file thành chuỗi ký tự để lưu vào GitHub Secrets (vì Secrets chỉ nhận text, không nhận file).

**Windows (PowerShell):**
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\Users\TEN-BAN\Downloads\ten-file.json'))
```

> ⚠️ **Lưu ý Windows:**
> - Dùng **dấu nháy đơn** `'...'` cho đường dẫn file
> - Thay `TEN-BAN` bằng tên user Windows của bạn
> - Thay `ten-file.json` bằng tên file JSON đã tải
> - Nếu lỗi "Missing ')'" → kiểm tra dấu nháy, không dùng dấu nháy kép lồng nhau

**Mac/Linux:**
```bash
base64 -w 0 ~/Downloads/ten-file.json
```

**Kết quả:** Chuỗi dài bắt đầu bằng `ewog` hoặc `eyJ` → copy **toàn bộ** chuỗi này (bao gồm cả `==` ở cuối nếu có).

> 💡 **Kiểm tra nhanh:** Chuỗi Base64 hợp lệ phải bắt đầu bằng `ew` hoặc `ey` (vì JSON bắt đầu bằng `{`). Nếu bắt đầu bằng ký tự khác → sai file hoặc sai lệnh.

---

## Bước 3: Tạo Google Sheets

### 3a. Tạo bảng tính

1. Vào [Google Sheets](https://sheets.google.com/) → tạo bảng tính mới (Blank spreadsheet)
2. Đặt tên: `CIC Daily Report Data`

### 3b. Share cho Service Account

> **QUAN TRỌNG:** Bước này bắt buộc — nếu không share thì hệ thống không đọc/ghi được Sheets.

1. Nhấn nút **"Share"** (góc trên bên phải)
2. Trong ô "Add people", paste email Service Account:
   - Email có dạng: `cic-daily-report@tên-project.iam.gserviceaccount.com`
   - Tìm email này trong Google Cloud Console → IAM & Admin → Service Accounts
3. Chọn quyền **"Editor"** (không phải Viewer)
4. Bỏ tick "Notify people" (không cần gửi email thông báo)
5. Nhấn **"Share"**

> 💡 **Xác nhận:** Trong phần "People with access", bạn phải thấy email service account với quyền **Editor**.

### 3c. Lấy Spreadsheet ID

Từ URL của bảng tính:
```
https://docs.google.com/spreadsheets/d/ABC123XYZ/edit
                                       ^^^^^^^^^^
                                       Đây là Spreadsheet ID
```

Phần giữa `/d/` và `/edit` = **Spreadsheet ID**. Copy chuỗi này.

### 3d. Cài Google Apps Script (Menu tự động — khuyến nghị)

**GAS Menu là gì?** Menu tùy chỉnh trên Google Sheets giúp tạo 9 tab dữ liệu với header tiếng Việt và định dạng đẹp — chỉ cần bấm nút.

1. Trong spreadsheet, vào **Extensions** (Tiện ích mở rộng) > **Apps Script**
2. Một tab mới mở ra với file `Code.gs` mặc định
3. **Xóa** toàn bộ nội dung `Code.gs`
4. Mở file `gas/AutoSetup.gs` trong repository → **copy toàn bộ** nội dung → paste vào
5. Nhấn nút **+** (bên cạnh Files) > chọn **Script** → đặt tên `Menu`
6. Mở file `gas/Menu.gs` trong repository → **copy toàn bộ** nội dung → paste vào
7. Nhấn **Ctrl+S** để lưu
8. Đóng tab Apps Script
9. **Tải lại (F5)** Google Sheets
10. Chờ vài giây → menu **📊 CIC Daily Report** xuất hiện trên thanh menu
11. Vào **⚙️ Thiết Lập** > **🚀 Thiết Lập Tự Động**
12. Cấp quyền khi được hỏi (chỉ lần đầu)
13. Hệ thống tạo 9 tab + header + định dạng

**9 tab được tạo:**

| Tab | Mô tả |
|-----|-------|
| TIN_TUC_THO | Tin tức thô từ RSS, CryptoPanic |
| DU_LIEU_THI_TRUONG | Giá, khối lượng, vốn hóa |
| DU_LIEU_ONCHAIN | Dữ liệu on-chain (MVRV, Funding Rate) |
| NOI_DUNG_DA_TAO | Bài viết AI tạo ra |
| NHAT_KY_PIPELINE | Log mỗi lần pipeline chạy |
| MAU_BAI_VIET | Template bài viết theo cấp độ |
| DANH_SACH_COIN | Danh sách coin theo cấp độ |
| CAU_HINH | Cấu hình hệ thống |
| BREAKING_LOG | Log tin nóng + dedup |

---

## Bước 4: Tạo Telegram Bot

1. Mở Telegram, tìm **@BotFather**
2. Gửi lệnh `/newbot`
3. Đặt tên bot: `CIC Daily Report Bot`
4. Đặt username: `cic_dailyreport_bot` (hoặc tên khác chưa ai dùng)
5. BotFather trả về **Bot Token** — lưu lại!
   - Dạng: `7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

> 💡 **Gợi ý đặt tên:** Nếu bạn có nhiều bot (ví dụ CIC Sentinel), đặt tên rõ ràng để phân biệt:
> - Bot Sentinel: `CIC_Sentinel_bot`
> - Bot Daily Report: `CIC_DailyReport_bot`

### Lấy Chat ID

Có 2 cách:

**Cách 1 — Bot cá nhân:**
1. Gửi tin nhắn bất kỳ cho bot
2. Mở trình duyệt, vào: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   (thay `<TOKEN>` bằng Bot Token thật)
3. Tìm `"chat":{"id":123456789}` — số đó là Chat ID

**Cách 2 — Channel/Group:**
1. Tạo Channel hoặc Group trên Telegram
2. Thêm bot vào Channel/Group với quyền Admin
3. Gửi tin nhắn trong Channel/Group
4. Mở `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Chat ID của channel thường có dấu trừ: `-1001234567890`

---

## Bước 5: Lấy API Keys

| Tên Secret | Bắt buộc | Nơi lấy | Giá trị mẫu |
|------------|----------|---------|-------------|
| `GOOGLE_SHEETS_CREDENTIALS` | ✅ | Chuỗi **Base64** từ Bước 2e | `ewogICJ0eXBl...` |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | ✅ | Spreadsheet ID từ Bước 3c | `15R4xkltKM60...` |
| `TELEGRAM_BOT_TOKEN` | ✅ | BotFather từ Bước 4 | `7123456789:AAH...` |
| `TELEGRAM_CHAT_ID` | ✅ | getUpdates từ Bước 4 | `123456789` |
| `GROQ_API_KEY` | ✅ | [console.groq.com](https://console.groq.com/) → API Keys | `gsk_abc...xyz` |
| `CRYPTOPANIC_API_KEY` | ✅ | [cryptopanic.com/developers](https://cryptopanic.com/developers/api/) | `abc123...` |
| `GEMINI_API_KEY` | ⬜ | [aistudio.google.com](https://aistudio.google.com/) → API Key | `AIza...` |
| `FRED_API_KEY` | ⬜ | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) | `abc123...` |

> ✅ = Bắt buộc (hệ thống không chạy nếu thiếu)
> ⬜ = Tùy chọn (hệ thống vẫn chạy, một số tính năng bị tắt)

### Cách lấy từng key:

**Groq API Key (AI miễn phí):**
1. Vào [console.groq.com](https://console.groq.com/)
2. Đăng ký/đăng nhập
3. Vào **API Keys** → **Create API Key**
4. Copy key (bắt đầu bằng `gsk_`)

**CryptoPanic API Key (tin tức crypto):**
1. Vào [cryptopanic.com](https://cryptopanic.com/) → đăng ký tài khoản
2. Vào [cryptopanic.com/developers/api/](https://cryptopanic.com/developers/api/)
3. Copy **Auth Token** ở trang API

---

## Bước 6: Cấu Hình GitHub Secrets

> ⚠️ **HAY NHẦM NHẤT:** Nhầm giá trị giữa `GOOGLE_SHEETS_CREDENTIALS` và `GOOGLE_SHEETS_SPREADSHEET_ID`.
> - `CREDENTIALS` = chuỗi Base64 **rất dài** (bắt đầu `ewog...`)
> - `SPREADSHEET_ID` = chuỗi ngắn từ URL Sheets (ví dụ `15R4xkltKM6088...`)
>
> **KHÔNG** nhầm 2 cái này!

1. Vào repository trên GitHub → **Settings** (tab cuối cùng)
2. Menu bên trái: **Secrets and variables** → **Actions**
3. Nhấn **"New repository secret"**
4. Thêm **6 secrets bắt buộc** (từng cái một):

| Name (gõ chính xác) | Value |
|---------------------|-------|
| `GOOGLE_SHEETS_CREDENTIALS` | Chuỗi Base64 dài |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | ID ngắn từ URL |
| `TELEGRAM_BOT_TOKEN` | Token từ BotFather |
| `TELEGRAM_CHAT_ID` | Số Chat ID |
| `GROQ_API_KEY` | Key từ Groq |
| `CRYPTOPANIC_API_KEY` | Token từ CryptoPanic |

> 💡 **Mẹo:** Khi paste giá trị, đảm bảo:
> - Không có **khoảng trắng** ở đầu hoặc cuối
> - Không có **xuống dòng** trong chuỗi
> - Tên secret phải **viết hoa** đúng (GOOGLE_SHEETS_CREDENTIALS, không phải google_sheets_credentials)

---

## Bước 7: Bật GitHub Actions

1. Vào tab **"Actions"** trên repository
2. Nếu thấy thông báo "Workflows aren't being run on this forked repository":
   → Nhấn **"I understand my workflows, go ahead and enable them"**
3. Bên trái sẽ thấy 3 workflows:
   - **Daily Pipeline** — chạy 08:00 VN mỗi ngày
   - **Breaking News** — chạy mỗi giờ
   - **Tests** — chạy khi push code

> 💡 **Nếu chỉ thấy "Tests":** Daily Pipeline và Breaking News chưa chạy lần nào nên GitHub chưa hiện. Bạn cần push 1 commit bất kỳ (ví dụ sửa README) để kích hoạt, hoặc chờ schedule tự chạy.

---

## Bước 8: Chạy Test Xác Nhận

1. Vào tab **"Actions"** → bên trái chọn **"Daily Pipeline"**
2. Nhấn **"Run workflow"** → chọn branch `master` → nhấn nút xanh **"Run workflow"**
3. Chờ workflow hoàn thành (1-3 phút)
4. Kiểm tra Telegram:

**Nếu thành công:** Nhận tin nhắn:
```
[TEST MODE] Pipeline hoàn tất
Trạng thái: running
Lỗi: 0
```
→ ✅ Hệ thống đã sẵn sàng!

**Nếu có lỗi:** Xem phần Xử Lý Sự Cố bên dưới.

---

## Xử Lý Sự Cố (Troubleshooting)

### Lỗi: "Failed to connect" (Google Sheets)

**Nguyên nhân phổ biến:**

| Nguyên nhân | Cách kiểm tra | Cách sửa |
|------------|--------------|----------|
| Nhầm giá trị Credentials và Spreadsheet ID | Credentials phải rất dài, ID phải ngắn | Sửa lại đúng secret |
| Google Sheets API chưa bật | Google Cloud → APIs & Services → kiểm tra | Bật Google Sheets API |
| API bật sai project | So sánh project ID trong Cloud Console vs email Service Account | Bật API trên đúng project |
| Service Account chưa được share Sheets | Mở Sheets → Share → kiểm tra | Thêm email SA với quyền Editor |
| Key JSON đã bị xóa/hết hạn | Google Cloud → Service Account → Keys | Tạo key mới + encode Base64 lại |

### Lỗi: "Missing required secrets"

Workflow báo thiếu secret → vào Settings → Secrets → kiểm tra tên secret viết hoa đúng chưa.

### Lỗi: PowerShell Base64 encoding

- Lỗi "Missing ')'" → dùng dấu nháy đơn `'...'` thay vì nháy kép `"..."`
- Lỗi "file not found" → kiểm tra đường dẫn file JSON

### Key bị lộ (KHẨN CẤP)

Nếu lỡ paste private key lên nơi công khai (chat, forum, email):

1. **Ngay lập tức:** Google Cloud → Service Account → Keys → **Xóa key cũ**
2. Tạo key mới: Add Key → Create new key → JSON
3. Encode Base64 file mới
4. Cập nhật secret `GOOGLE_SHEETS_CREDENTIALS` trên GitHub
5. Chạy lại workflow để xác nhận

---

## Sau Khi Cài Đặt

### Hệ thống tự động chạy:
- **08:00 VN mỗi ngày:** Báo cáo daily (thu thập tin, phân tích AI, gửi Telegram)
- **Mỗi giờ:** Kiểm tra tin nóng (Breaking News)

### Chạy thủ công:
- Vào GitHub → Actions → chọn workflow → Run workflow

### Google Sheets Menu:
| Menu | Chức năng |
|------|-----------|
| ⚙️ Thiết Lập > 🚀 Thiết Lập Tự Động | Tạo 9 tab + header + định dạng |
| ⚙️ Thiết Lập > 🔄 Đồng Bộ Cột Thiếu | Thêm cột mới nếu schema thay đổi |
| ⚙️ Thiết Lập > 🎨 Định Dạng Lại | Sửa format bị lộn xộn |
| 📋 Kiểm Tra > 📊 Trạng Thái | Xem tab nào có, tab nào thiếu |
| 📋 Kiểm Tra > 📏 Đếm Dữ Liệu | Số dòng trong mỗi tab |
| 🧹 Công Cụ > 🗑️ Dọn Dẹp | Xóa dữ liệu quá 30 ngày |
| ❓ Hướng Dẫn | Hướng dẫn sử dụng |

---

## Checklist Tổng Kết

Trước khi chạy workflow, xác nhận:

- [ ] Fork repository về tài khoản GitHub
- [ ] Tạo Google Cloud Project + bật Google Sheets API
- [ ] Tạo Service Account + tải Key JSON
- [ ] Tạo Google Sheets + share cho Service Account (Editor)
- [ ] Cài GAS Menu + chạy Thiết Lập Tự Động (9 tab)
- [ ] Tạo Telegram Bot + lấy Token và Chat ID
- [ ] Lấy Groq API Key + CryptoPanic API Key
- [ ] Thêm 6 secrets vào GitHub (kiểm tra tên viết hoa, giá trị đúng)
- [ ] Bật GitHub Actions
- [ ] Chạy Daily Pipeline thủ công → Telegram nhận tin "Lỗi: 0"

---

## Hỗ Trợ

Nếu gặp vấn đề, tạo Issue trên GitHub repository kèm:
- Ảnh chụp lỗi (**che các thông tin nhạy cảm** như key, token, email)
- Bước nào bị lỗi
- Hệ điều hành đang dùng
