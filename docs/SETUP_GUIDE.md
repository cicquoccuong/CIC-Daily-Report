# Hướng Dẫn Cài Đặt Hệ Thống CIC Daily Report

> Thời gian: 30-45 phút. **Không cần biết lập trình.**
> Hướng dẫn này viết cho người **chưa biết kỹ thuật** — mọi thuật ngữ đều được giải thích bằng tiếng Việt dễ hiểu.

### Hướng Dẫn Chụp Screenshot (FR51)

Tài liệu có **8 vị trí** đánh dấu `[SCREENSHOT X]` — đây là nơi cần chèn ảnh chụp màn hình.

**Cách chụp (Windows):** Nhấn `Windows + Shift + S` → kéo chọn vùng cần chụp → ảnh tự copy → paste vào file Word/Google Docs.

**Cách chèn:** Sau khi chụp xong 8 ảnh, đặt tên file `screenshot-1.png` đến `screenshot-8.png`, lưu vào thư mục `docs/screenshots/`, rồi thay `[SCREENSHOT X]` bằng `![Mô tả](screenshots/screenshot-X.png)`.

| # | Bước | Chụp gì | Che gì |
|---|------|---------|--------|
| 1 | Fork repo | Trang repo sau Fork | Không |
| 2 | Bật API | Google Sheets API Enabled | Không |
| 3 | Service Account | Email robot trong Credentials | Che email cá nhân |
| 4 | Share Sheets | Hộp thoại Share với robot | Che email cá nhân |
| 5 | GAS Menu | 9 tab + menu CIC Daily Report | Không |
| 6 | BotFather | Tin nhắn tạo bot | **CHE Bot Token** |
| 7 | GitHub Secrets | Danh sách 6 secrets | Không (tự ẩn) |
| 8 | Chạy thử | Actions ✅ + Telegram nhận tin | Không |

---

## Hệ Thống Này Làm Gì?

Hình dung như một **nhân viên ảo** làm việc 24/7:
- **Mỗi sáng 8h:** Tự động thu thập tin tức crypto → viết báo cáo bằng AI → gửi lên Telegram cho bạn
- **Mỗi giờ:** Kiểm tra có tin nóng (ví dụ: BTC tăng/giảm mạnh) → gửi cảnh báo ngay

Bạn chỉ cần **cài đặt 1 lần**, sau đó hệ thống tự chạy mãi mãi (miễn phí).

---

## Bạn Cần Chuẩn Bị

| Thứ cần có | Giải thích | Nơi đăng ký |
|-----------|-----------|------------|
| Tài khoản **GitHub** | Nơi lưu trữ code của hệ thống (giống Google Drive cho code) | [github.com](https://github.com/) |
| Tài khoản **Google** | Dùng Google Sheets làm "kho dữ liệu" của hệ thống | Bạn đã có nếu dùng Gmail |
| Tài khoản **Telegram** | Nơi nhận báo cáo hàng ngày | Ứng dụng Telegram trên điện thoại/máy tính |
| Máy tính có trình duyệt | Chỉ cần khi cài đặt, sau đó hệ thống tự chạy | — |

---

## Bước 1: Tạo Bản Sao Dự Án (Fork)

**Fork là gì?** Giống như bạn photocopy một quyển sách về nhà — bản gốc vẫn còn, bạn có bản riêng để dùng.

1. Đăng nhập GitHub
2. Vào trang dự án CIC Daily Report
3. Nhấn nút **"Fork"** (góc trên bên phải, biểu tượng nhánh cây)
4. Chờ vài giây → GitHub tạo bản sao trên tài khoản của bạn
5. Bạn sẽ thấy trang mới có địa chỉ: `github.com/tên-bạn/CIC-Daily-Report`

> [SCREENSHOT 1] **Chụp gì:** Trang repo sau khi Fork xong — thấy tên bạn/CIC-Daily-Report ở góc trên trái.
> **Cách chụp:** Nhấn Windows+Shift+S → kéo chọn vùng → paste vào đây.

> Sau bước này, bạn có **bản sao riêng** của dự án trên tài khoản GitHub.

---

## Bước 2: Tạo "Tài Khoản Robot" Cho Google (Service Account)

**Service Account là gì?** Giống như bạn tạo một tài khoản nhân viên ảo để hệ thống tự đăng nhập vào Google Sheets đọc/ghi dữ liệu — bạn không cần phải ngồi đăng nhập mỗi ngày.

### 2a. Tạo "Dự Án" trên Google Cloud

**Google Cloud là gì?** Trang quản lý các dịch vụ Google dành cho máy tính/hệ thống. Miễn phí cho mức sử dụng của chúng ta.

1. Vào [console.cloud.google.com](https://console.cloud.google.com/)
2. Đăng nhập bằng tài khoản Google của bạn
3. Nhấn vào tên dự án ở **thanh trên cùng** (bên cạnh logo Google Cloud)
4. Một bảng hiện ra → nhấn **"New Project"** (góc trên bên phải của bảng)
5. Ô "Project name": gõ `CIC Daily Report`
6. Nhấn **"Create"**
7. Chờ vài giây → nhấn lại vào thanh trên cùng → chọn dự án **"CIC Daily Report"** vừa tạo

### 2b. Bật Tính Năng Đọc/Ghi Google Sheets (Google Sheets API)

**API là gì?** "Cửa ngõ" cho phép hệ thống bên ngoài giao tiếp với Google Sheets. Mặc định cửa này đóng, bạn cần mở nó.

> ⚠️ **Quan trọng:** Kiểm tra thanh trên cùng đang hiển thị **đúng tên dự án** "CIC Daily Report". Nếu bạn có nhiều dự án, dễ bật nhầm dự án khác.

1. Nhấn biểu tượng **☰** (3 gạch ngang, góc trên bên trái)
2. Chọn **"APIs & Services"** → **"Library"**
3. Trong ô tìm kiếm, gõ: `Google Sheets API`
4. Nhấn vào kết quả có **biểu tượng bảng tính màu xanh**
5. Nhấn nút **"Enable"** (Bật)
6. Nếu thấy dòng **"API Enabled" ✅** thì đã bật thành công

> [SCREENSHOT 2] **Chụp gì:** Trang Google Sheets API đã bật — thấy nút "Manage" (thay vì "Enable") và dòng "API Enabled".
> **Lưu ý khi chụp:** Kiểm tra tên dự án đúng trên thanh trên cùng.

### 2c. Tạo Tài Khoản Robot (Service Account)

1. Nhấn **☰** → **"APIs & Services"** → **"Credentials"** (Thông tin xác thực)
2. Nhấn nút **"+ Create Credentials"** (trên cùng) → chọn **"Service Account"**
3. Ô "Service account name": gõ `cic-daily-report`
4. Nhấn **"Create and Continue"**
5. Trang tiếp theo hỏi "Grant access" → **bỏ qua**, nhấn **"Continue"**
6. Trang tiếp theo hỏi "Grant users access" → **bỏ qua**, nhấn **"Done"**

> Sau bước này bạn đã có tài khoản robot. Email của nó có dạng:
> `cic-daily-report@tên-dự-án.iam.gserviceaccount.com`
> **Ghi lại email này** — sẽ dùng ở Bước 3.

> [SCREENSHOT 3] **Chụp gì:** Trang Credentials — thấy email robot trong phần "Service Accounts".
> **Lưu ý khi chụp:** **CHE** phần đầu email nếu đăng lên đâu đó (giữ lại @...iam.gserviceaccount.com để thấy dạng đúng).

### 2d. Tạo "Chìa Khóa" Cho Robot (Key JSON)

**Key JSON là gì?** File "chìa khóa" để robot chứng minh danh tính khi đăng nhập. Giống như thẻ nhân viên — ai có thẻ thì vào được.

1. Trong trang Credentials, kéo xuống phần **"Service Accounts"**
2. Nhấn vào **email** robot vừa tạo
3. Chuyển sang tab **"Keys"** (Khóa)
4. Nhấn **"Add Key"** → **"Create new key"**
5. Chọn **"JSON"** → nhấn **"Create"**
6. File JSON tự tải về máy tính của bạn (thường ở thư mục Downloads)

> ⚠️ **CỰC KỲ QUAN TRỌNG — BẢO MẬT:**
> - File JSON này là **chìa khóa** vào hệ thống. Ai có file này có thể đọc/ghi Sheets của bạn.
> - **KHÔNG** gửi file này qua chat, email, hoặc đăng lên bất kỳ đâu.
> - **KHÔNG** paste nội dung file lên forum hoặc nhờ người khác xem.
> - Nếu lỡ để lộ → xem phần **"Key Bị Lộ"** ở cuối tài liệu để xử lý khẩn cấp.

### 2e. Chuyển File Chìa Khóa Thành Chuỗi Ký Tự (Encode Base64)

**Base64 là gì?** Cách "mã hóa nhẹ" để chuyển file thành một chuỗi chữ dài. GitHub Secrets chỉ nhận chữ (không nhận file), nên bạn cần chuyển đổi.

**Trên Windows (mở PowerShell — nhấn phím Windows, gõ "PowerShell", Enter):**

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\Users\TEN-BAN\Downloads\ten-file.json'))
```

Thay thế:
- `TEN-BAN` = tên đăng nhập Windows của bạn (ví dụ: `admin`, `NguyenVanA`)
- `ten-file.json` = tên file JSON đã tải ở bước 2d

> ⚠️ **Hay bị lỗi:**
> - Dùng **dấu nháy đơn** `'...'` (không phải nháy kép `"..."`)
> - Nếu lỗi "Missing ')'" hoặc "Unexpected token" → kiểm tra lại dấu nháy
> - Nếu lỗi "file not found" → mở thư mục Downloads kiểm tra tên file chính xác

**Trên Mac/Linux (mở Terminal):**
```bash
base64 -w 0 ~/Downloads/ten-file.json
```

**Kết quả:** Một chuỗi chữ rất dài hiện ra. Ví dụ:
```
ewogICJ0eXBlIjogInNlcnZpY2VfYWNjb3VudCIsC...rất dài...Cn0K
```

**Cách kiểm tra đúng/sai:**
- ✅ Đúng: Chuỗi bắt đầu bằng `ew` hoặc `ey`
- ❌ Sai: Chuỗi bắt đầu bằng ký tự khác → chạy lại lệnh hoặc kiểm tra file

**Copy toàn bộ chuỗi này** (bao gồm cả `==` ở cuối nếu có) — sẽ dùng ở Bước 6.

---

## Bước 3: Tạo "Kho Dữ Liệu" Trên Google Sheets

**Google Sheets dùng làm gì?** Hệ thống lưu tất cả dữ liệu vào đây: tin tức thô, dữ liệu thị trường, bài viết AI tạo ra, log hoạt động... Mỗi loại dữ liệu nằm trong 1 tab riêng (tổng 9 tab).

### 3a. Tạo bảng tính mới

1. Vào [sheets.google.com](https://sheets.google.com/)
2. Nhấn **"Blank spreadsheet"** (Bảng tính trống) hoặc dấu **+**
3. Đặt tên: `CIC Daily Report Data` (nhấn vào chữ "Untitled spreadsheet" góc trên trái để đổi tên)

### 3b. Chia sẻ cho Robot (BẮT BUỘC)

> **Nếu bỏ qua bước này**, robot không vào được Sheets → hệ thống báo lỗi "Failed to connect".

1. Nhấn nút **"Share"** (Chia sẻ — nút xanh góc trên bên phải)
2. Trong ô "Add people and groups", **paste email robot** từ Bước 2c
   - Ví dụ: `cic-daily-report@cic-daily-report.iam.gserviceaccount.com`
3. Ô bên phải email → chọn quyền **"Editor"** (Biên tập viên — cho phép đọc VÀ ghi)
4. Bỏ tick **"Notify people"** (không cần gửi email thông báo cho robot)
5. Nhấn **"Share"**

**Xác nhận thành công:** Trong mục "People with access", bạn thấy:
- Tên bạn — Owner
- Email robot — **Editor** ✅

> [SCREENSHOT 4] **Chụp gì:** Hộp thoại Share — thấy email robot có quyền "Editor".
> **Lưu ý khi chụp:** **CHE** email cá nhân, chỉ để lộ email robot.

### 3c. Lấy Mã Định Danh Bảng Tính (Spreadsheet ID)

**Spreadsheet ID là gì?** Mã số riêng của bảng tính, giống như số CMND. Hệ thống dùng mã này để tìm đúng bảng tính của bạn.

Nhìn vào thanh địa chỉ trình duyệt:
```
https://docs.google.com/spreadsheets/d/ABC123XYZ/edit?gid=0
                                       ─────────
                                       Phần này là Spreadsheet ID
```

**Copy phần giữa `/d/` và `/edit`** — đó là Spreadsheet ID. Ví dụ: `15R4xkltKM6088YR3D8Fkj6aPfypneSsTm67-1fqjkEE`

> 💡 Spreadsheet ID là chuỗi **ngắn** (khoảng 40-50 ký tự). Nếu bạn thấy chuỗi **rất dài** (hàng trăm ký tự) → đó là Base64, không phải ID.

### 3d. Cài Menu Tự Động trên Google Sheets (Khuyến nghị)

**Menu này làm gì?** Thêm một menu đặc biệt vào Google Sheets, cho phép bạn tạo 9 tab dữ liệu với tiêu đề tiếng Việt và định dạng đẹp — chỉ cần bấm nút.

1. Trong bảng tính, vào menu **Extensions** (Tiện ích mở rộng) → **Apps Script**
2. Một tab mới mở ra — đây là nơi gắn code vào Sheets
3. Bạn thấy file `Code.gs` có sẵn → **xóa hết** nội dung trong đó
4. Vào GitHub repo của bạn → mở thư mục `gas` → mở file `AutoSetup.gs`
5. **Copy toàn bộ** nội dung → quay lại tab Apps Script → **paste vào** ô Code.gs
6. Bên trái, nhấn dấu **+** (cạnh chữ "Files") → chọn **Script** → đặt tên `Menu`
7. Vào GitHub → mở file `gas/Menu.gs` → **copy toàn bộ** → **paste vào** file Menu
8. Nhấn **Ctrl+S** (hoặc biểu tượng đĩa mềm) để lưu
9. **Đóng** tab Apps Script
10. Quay lại tab Google Sheets → nhấn **F5** (tải lại trang)
11. Chờ 3-5 giây → trên thanh menu xuất hiện **📊 CIC Daily Report**
12. Nhấn **📊 CIC Daily Report** → **⚙️ Thiết Lập** → **🚀 Thiết Lập Tự Động**
13. Lần đầu Google sẽ hỏi cấp quyền → nhấn **"Continue"** → chọn tài khoản → **"Allow"**
14. Hệ thống tự tạo **9 tab** với tiêu đề và định dạng sẵn

> [SCREENSHOT 5] **Chụp gì:** Google Sheets sau khi chạy Thiết Lập Tự Động — thấy 9 tab ở dưới cùng + menu 📊 CIC Daily Report trên thanh menu.

**9 tab được tạo:**

| Tab | Lưu gì? |
|-----|---------|
| TIN_TUC_THO | Tin tức thô thu thập từ các nguồn |
| DU_LIEU_THI_TRUONG | Giá coin, khối lượng giao dịch, vốn hóa |
| DU_LIEU_ONCHAIN | Dữ liệu kỹ thuật blockchain |
| NOI_DUNG_DA_TAO | Bài viết do AI tạo ra |
| NHAT_KY_PIPELINE | Nhật ký mỗi lần hệ thống chạy |
| MAU_BAI_VIET | Mẫu bài viết theo cấp độ thành viên |
| DANH_SACH_COIN | Danh sách coin theo cấp độ |
| CAU_HINH | Các thiết lập của hệ thống |
| BREAKING_LOG | Lịch sử tin nóng đã gửi |

---

## Bước 4: Tạo Bot Telegram (Người Đưa Tin)

**Bot Telegram là gì?** Tài khoản tự động trên Telegram — hệ thống gửi báo cáo qua bot này, bạn nhận trên Telegram như nhận tin nhắn bình thường.

### 4a. Tạo Bot

1. Mở Telegram → tìm **@BotFather** (bot chính thức của Telegram để tạo bot)
2. Nhấn **Start** → gửi lệnh: `/newbot`
3. BotFather hỏi tên bot → gõ: `CIC Daily Report Bot`
4. BotFather hỏi username → gõ: `CIC_DailyReport_bot` (hoặc tên khác, phải kết thúc bằng `_bot`)
5. BotFather gửi lại **Bot Token** — đây là "mật khẩu" của bot
   - Dạng: `7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`
   - **Lưu lại chuỗi này!**

> [SCREENSHOT 6] **Chụp gì:** Cuộc trò chuyện với BotFather — thấy tin nhắn chứa Bot Token.
> **Lưu ý khi chụp:** **CHE** toàn bộ Bot Token (vì ai có token có thể điều khiển bot).

> 💡 **Đặt tên dễ phân biệt:** Nếu bạn có nhiều bot (ví dụ CIC Sentinel cũng có bot riêng):
> - Bot báo cáo hàng ngày: `CIC_DailyReport_bot`
> - Bot hệ thống Sentinel: `CIC_Sentinel_bot`

### 4b. Lấy Chat ID (Địa chỉ nhận tin)

**Chat ID là gì?** Số định danh của cuộc trò chuyện — giống số nhà. Hệ thống cần biết "gửi tin nhắn đến đâu".

**Nếu gửi cho bạn (cá nhân):**
1. Mở Telegram → gửi tin nhắn bất kỳ cho bot vừa tạo (ví dụ gõ "hello")
2. Mở trình duyệt, vào địa chỉ (thay `TOKEN` bằng Bot Token thật):
   ```
   https://api.telegram.org/botTOKEN/getUpdates
   ```
3. Trang hiện ra một đoạn text → tìm dòng có `"chat":{"id":123456789}`
4. Số `123456789` đó là **Chat ID** của bạn

**Nếu gửi cho Channel/Group:**
1. Tạo Channel (hoặc Group) trên Telegram
2. Vào Settings của Channel → **Add Administrator** → thêm bot vào
3. Gửi 1 tin nhắn bất kỳ trong Channel
4. Vào link `getUpdates` như trên → Chat ID của channel thường có dạng `-1001234567890` (có dấu trừ)

---

## Bước 5: Lấy "Chìa Khóa" Các Dịch Vụ (API Keys)

**API Key là gì?** "Thẻ ra vào" để hệ thống truy cập các dịch vụ bên ngoài. Mỗi dịch vụ cần 1 thẻ riêng.

### 6 thẻ bắt buộc:

| Tên | Lấy ở đâu | Dạng giá trị |
|-----|-----------|-------------|
| `GOOGLE_SHEETS_CREDENTIALS` | Chuỗi Base64 từ Bước 2e | Rất dài, bắt đầu `ewog...` |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | ID từ URL Sheets ở Bước 3c | Ngắn, ~40-50 ký tự |
| `TELEGRAM_BOT_TOKEN` | BotFather ở Bước 4a | `7123456789:AAH...` |
| `TELEGRAM_CHAT_ID` | getUpdates ở Bước 4b | Số, ví dụ `123456789` |
| `GROQ_API_KEY` | Đăng ký tại [console.groq.com](https://console.groq.com/) | Bắt đầu `gsk_` |
| `CRYPTOPANIC_API_KEY` | Đăng ký tại [cryptopanic.com/developers/api](https://cryptopanic.com/developers/api/) | Chuỗi chữ số |

### Cách lấy Groq API Key (AI viết báo cáo — miễn phí):
1. Vào [console.groq.com](https://console.groq.com/) → đăng ký bằng Google/GitHub
2. Nhấn **"API Keys"** (menu bên trái)
3. Nhấn **"Create API Key"** → đặt tên bất kỳ → **"Create"**
4. Copy key (bắt đầu bằng `gsk_`) — **chỉ hiện 1 lần**, nếu mất phải tạo lại

### Cách lấy CryptoPanic API Key (nguồn tin tức crypto — miễn phí):
1. Vào [cryptopanic.com](https://cryptopanic.com/) → đăng ký tài khoản
2. Vào [cryptopanic.com/developers/api/](https://cryptopanic.com/developers/api/)
3. Kéo xuống tìm **"Your Auth Token"** → copy

### 2 thẻ tùy chọn (không bắt buộc):

| Tên | Làm gì | Nơi lấy |
|-----|--------|---------|
| `GEMINI_API_KEY` | AI dự phòng khi Groq lỗi | [aistudio.google.com](https://aistudio.google.com/) |
| `FRED_API_KEY` | Dữ liệu kinh tế vĩ mô (lãi suất, CPI) | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) |

---

## Bước 6: Lưu Chìa Khóa Vào GitHub (GitHub Secrets)

**GitHub Secrets là gì?** "Két sắt" trên GitHub để lưu mật khẩu/key một cách an toàn. Sau khi lưu vào, **không ai xem lại được** (kể cả bạn) — chỉ hệ thống mới đọc được khi chạy.

> ⚠️ **LỖI PHỔ BIẾN NHẤT — ĐỌC KỸ:**
>
> Hay bị **nhầm** giữa 2 cái này:
> - `GOOGLE_SHEETS_CREDENTIALS` = chuỗi Base64 **RẤT DÀI** (hàng trăm ký tự, bắt đầu `ewog...`)
> - `GOOGLE_SHEETS_SPREADSHEET_ID` = chuỗi **NGẮN** (~40-50 ký tự, lấy từ URL)
>
> Nếu nhầm → hệ thống báo "Failed to connect". **Kiểm tra kỹ trước khi lưu!**

### Cách thêm Secret:

1. Vào GitHub → vào repo `tên-bạn/CIC-Daily-Report`
2. Nhấn tab **Settings** (Cài đặt — tab cuối cùng)
3. Menu bên trái → kéo xuống **"Secrets and variables"** → nhấn **"Actions"**
4. Nhấn nút **"New repository secret"**
5. Ô **"Name"**: gõ tên chính xác (PHẢI VIẾT HOA, ví dụ: `GROQ_API_KEY`)
6. Ô **"Secret"**: paste giá trị
7. Nhấn **"Add secret"**
8. Lặp lại cho **6 secrets bắt buộc**

> [SCREENSHOT 7] **Chụp gì:** Trang GitHub Secrets sau khi thêm đủ 6 secrets — thấy danh sách 6 tên (giá trị bị ẩn là đúng).
> **Không cần che gì** — GitHub tự ẩn giá trị, chỉ hiện tên.

**Thêm 6 secrets theo thứ tự:**

| Lần | Name (gõ chính xác) | Value (paste gì vào) |
|-----|---------------------|---------------------|
| 1 | `GOOGLE_SHEETS_CREDENTIALS` | Chuỗi Base64 dài từ Bước 2e |
| 2 | `GOOGLE_SHEETS_SPREADSHEET_ID` | ID ngắn từ URL Sheets (Bước 3c) |
| 3 | `TELEGRAM_BOT_TOKEN` | Token từ BotFather (Bước 4a) |
| 4 | `TELEGRAM_CHAT_ID` | Số Chat ID (Bước 4b) |
| 5 | `GROQ_API_KEY` | Key bắt đầu `gsk_` (Bước 5) |
| 6 | `CRYPTOPANIC_API_KEY` | Token từ CryptoPanic (Bước 5) |

> 💡 **Mẹo khi paste:**
> - Không có **khoảng trắng** ở đầu hoặc cuối chuỗi
> - Không có **xuống dòng** (phải là 1 dòng liên tục)
> - Tên PHẢI viết hoa đúng: `GROQ_API_KEY` ✅, `groq_api_key` ❌

---

## Bước 7: Bật "Máy Chạy Tự Động" (GitHub Actions)

**GitHub Actions là gì?** Dịch vụ miễn phí của GitHub — tự động chạy code theo lịch trình (giống đặt báo thức cho máy tính). Bạn không cần bật máy tính — GitHub chạy trên server của họ.

1. Vào repo trên GitHub → nhấn tab **"Actions"** (trên thanh menu)
2. Nếu thấy dòng "Workflows aren't being run on this forked repository":
   → Nhấn **"I understand my workflows, go ahead and enable them"**
3. Bên trái sẽ thấy **3 máy chạy tự động** (workflows):
   - **Daily Pipeline** — chạy 08:00 sáng VN mỗi ngày
   - **Breaking News** — chạy mỗi giờ, kiểm tra tin nóng
   - **Tests** — chạy khi có thay đổi code (dành cho kỹ thuật)

> 💡 **Nếu bên trái chỉ thấy "Tests":** 2 cái kia chưa hiện vì chưa chạy lần nào. Bạn cần tạo 1 thay đổi nhỏ (ví dụ sửa README) rồi push lên — sau đó tất cả sẽ hiện ra. Hoặc chờ đến giờ lịch trình tự chạy.

---

## Bước 8: Chạy Thử Lần Đầu

1. Vào tab **"Actions"** → bên trái nhấn **"Daily Pipeline"**
2. Bên phải hiện nút **"Run workflow"** → nhấn vào
3. Chọn branch **"master"** → nhấn nút xanh **"Run workflow"**
4. Chờ 1-3 phút (biểu tượng 🟡 vàng xoay = đang chạy)
5. Mở Telegram → kiểm tra tin nhắn từ bot

**Nếu thành công ✅:** Bạn nhận tin nhắn:
```
[TEST MODE] Pipeline hoàn tất
Trạng thái: running
Lỗi: 0
```

> [SCREENSHOT 8] **Chụp gì:** 2 ảnh: (a) GitHub Actions thấy dấu ✅ xanh, (b) Telegram nhận tin nhắn từ bot.
> **Không cần che gì** trên ảnh GitHub Actions. Trên Telegram chỉ cần thấy tin nhắn thành công.

**Xong! Hệ thống đã sẵn sàng.** Từ mai 8h sáng bạn sẽ nhận báo cáo đầu tiên.

**Nếu có lỗi ❌:** Đọc phần Xử Lý Sự Cố bên dưới.

---

## Xử Lý Sự Cố

### Lỗi: "Failed to connect" (Không kết nối được Google Sheets)

Đây là lỗi phổ biến nhất. Kiểm tra theo thứ tự:

| Thứ tự | Kiểm tra | Cách sửa |
|--------|---------|----------|
| 1 | **Nhầm Credentials và Spreadsheet ID** — Credentials phải rất dài, ID phải ngắn | Vào GitHub Settings → Secrets → sửa lại đúng |
| 2 | **Chưa bật Google Sheets API** | Google Cloud → APIs & Services → Library → bật |
| 3 | **Bật API sai dự án** — API và Service Account phải cùng 1 dự án | Kiểm tra tên dự án trên thanh trên cùng |
| 4 | **Chưa share Sheets cho robot** | Mở Sheets → Share → thêm email robot với quyền Editor |
| 5 | **Key JSON đã bị xóa** | Google Cloud → Service Account → Keys → tạo key mới |

### Lỗi: "Missing required secrets"

Workflow báo thiếu secret → kiểm tra:
- Tên viết hoa đúng chưa? (`GROQ_API_KEY` không phải `groq_api_key`)
- Đã thêm đủ 6 secrets chưa?

### Lỗi: PowerShell không chạy được lệnh Base64

- **"Missing ')'"** → dùng dấu nháy đơn `'...'`, không dùng nháy kép
- **"file not found"** → mở thư mục Downloads, xem tên file JSON chính xác
- **Chuỗi rỗng** → đường dẫn file sai

### Key Bị Lộ (Gửi nhầm lên chat/forum) — XỬ LÝ KHẨN CẤP

Nếu bạn lỡ gửi nội dung file JSON hoặc chuỗi Base64 lên nơi công khai:

1. **Ngay lập tức:** Vào Google Cloud → Service Account → tab Keys → **xóa key cũ** (biểu tượng thùng rác)
2. Nhấn **"Add Key"** → **"Create new key"** → **JSON** → tải file mới
3. Chạy lại lệnh Base64 encode với file mới
4. Vào GitHub → Settings → Secrets → cập nhật `GOOGLE_SHEETS_CREDENTIALS` bằng chuỗi Base64 mới
5. Chạy lại workflow để xác nhận

> Sau khi xóa key cũ, kẻ xấu không thể dùng key đã lộ nữa.

---

## Sau Khi Cài Đặt Xong

### Hệ thống tự chạy hàng ngày:
- **08:00 sáng VN:** Thu thập tin → AI viết báo cáo → gửi Telegram
- **Mỗi giờ:** Kiểm tra tin nóng → gửi cảnh báo nếu có

### Bạn không cần làm gì thêm. Nếu muốn chạy thủ công:
- GitHub → Actions → chọn workflow → **Run workflow**

### Menu trên Google Sheets (nếu đã cài ở Bước 3d):

| Nhấn vào đây | Để làm gì |
|-------------|----------|
| ⚙️ Thiết Lập → 🚀 Thiết Lập Tự Động | Tạo lại 9 tab (nếu lỡ xóa tab nào) |
| ⚙️ Thiết Lập → 🔄 Đồng Bộ Cột Thiếu | Thêm cột mới nếu hệ thống nâng cấp |
| ⚙️ Thiết Lập → 🎨 Định Dạng Lại | Sửa format nếu bị lộn xộn |
| 📋 Kiểm Tra → 📊 Trạng Thái | Xem tab nào đã có, tab nào thiếu |
| 📋 Kiểm Tra → 📏 Đếm Dữ Liệu | Xem mỗi tab có bao nhiêu dòng dữ liệu |
| 🧹 Công Cụ → 🗑️ Dọn Dẹp | Xóa dữ liệu cũ hơn 30 ngày (giảm dung lượng) |
| ❓ Hướng Dẫn | Mở hướng dẫn sử dụng |

---

## Checklist Tổng Kết

In trang này ra và đánh dấu từng bước đã làm:

- [ ] Bước 1: Tạo bản sao (Fork) repo trên GitHub
- [ ] Bước 2a: Tạo dự án trên Google Cloud
- [ ] Bước 2b: Bật Google Sheets API (đúng dự án)
- [ ] Bước 2c: Tạo Service Account → ghi lại email robot
- [ ] Bước 2d: Tạo Key JSON → tải file về máy
- [ ] Bước 2e: Encode Base64 → copy chuỗi dài
- [ ] Bước 3a: Tạo Google Sheets mới
- [ ] Bước 3b: Share Sheets cho email robot (quyền Editor)
- [ ] Bước 3c: Copy Spreadsheet ID từ URL
- [ ] Bước 3d: Cài GAS Menu → chạy Thiết Lập Tự Động (9 tab)
- [ ] Bước 4a: Tạo Telegram Bot → lưu Bot Token
- [ ] Bước 4b: Lấy Chat ID
- [ ] Bước 5: Lấy Groq API Key + CryptoPanic API Key
- [ ] Bước 6: Thêm 6 secrets vào GitHub (kiểm tra tên viết hoa + giá trị đúng)
- [ ] Bước 7: Bật GitHub Actions
- [ ] Bước 8: Chạy Daily Pipeline → Telegram nhận tin "Lỗi: 0" ✅

---

## Hỗ Trợ

Nếu gặp vấn đề, tạo Issue trên GitHub repository kèm:
- Ảnh chụp màn hình lỗi (**che** key, token, email trước khi chụp)
- Ghi rõ đang ở **bước mấy**
- Hệ điều hành: Windows / Mac / Linux
