# CIC Daily Report — Google Apps Script

Code Google Apps Script để gắn vào Google Sheets, tự động tạo và định dạng 9 tab dữ liệu.

## Cài Đặt Lần Đầu (Thủ Công)

### Bước 1: Mở Google Sheets
Mở file Google Sheets mà bạn muốn dùng làm database cho CIC Daily Report.

### Bước 2: Mở Apps Script Editor
- Vào menu **Extensions** (Tiện ích mở rộng) > **Apps Script**
- Một tab mới sẽ mở ra

### Bước 3: Copy Code
1. Xóa nội dung file `Code.gs` mặc định
2. Copy toàn bộ nội dung file `AutoSetup.gs` vào
3. Tạo file mới (nhấn **+** > **Script**), đặt tên `Menu`
4. Copy toàn bộ nội dung file `Menu.gs` vào
5. Nhấn **Ctrl+S** để lưu

### Bước 4: Chạy Lần Đầu
1. Đóng tab Apps Script
2. **Tải lại (Refresh)** Google Sheets
3. Chờ vài giây — menu **📊 CIC Daily Report** sẽ xuất hiện
4. Vào menu **⚙️ Thiết Lập** > **🚀 Thiết Lập Tự Động**
5. Cấp quyền khi được hỏi (chỉ lần đầu)
6. Hệ thống tạo 9 tab + header + định dạng + dữ liệu mẫu

## Deploy Tự Động (clasp)

Sau khi cài lần đầu, dùng `clasp` để deploy code từ máy tính:

### Cài đặt 1 lần:
```powershell
# 1. Cài clasp
npm install -g @google/clasp

# 2. Đăng nhập Google
clasp login

# 3. Setup (nhập Script ID từ Apps Script > Project Settings)
cd gas
.\deploy.ps1 setup
```

### Deploy code:
```powershell
cd gas
.\deploy.ps1 deploy
```

### Xem trạng thái:
```powershell
.\deploy.ps1 status
```

## Menu

| Menu | Chức năng |
|------|-----------|
| ⚙️ Thiết Lập > 🚀 Thiết Lập Tự Động | Tạo 9 tab + header + định dạng |
| ⚙️ Thiết Lập > 🔄 Đồng Bộ Cột Thiếu | Thêm cột mới nếu schema thay đổi |
| ⚙️ Thiết Lập > 🎨 Định Dạng Lại | Sửa format bị lộn xộn |
| 📋 Kiểm Tra > 📊 Trạng Thái | Xem tab nào có, tab nào thiếu |
| 📋 Kiểm Tra > 📏 Đếm Dữ Liệu | Số dòng trong mỗi tab |
| 🧹 Công Cụ > 🗑️ Dọn Dẹp | Xóa dữ liệu quá 30 ngày |
| ❓ Hướng Dẫn | Hướng dẫn sử dụng |
| ℹ️ Phiên Bản | Thông tin phiên bản |

## 9 Tab Dữ Liệu

| Tab | Mô tả |
|-----|-------|
| TIN_TUC_THO | Tin tức thô từ RSS, CryptoPanic |
| DU_LIEU_THI_TRUONG | Giá, khối lượng, vốn hóa |
| DU_LIEU_ONCHAIN | Dữ liệu on-chain (MVRV, Funding Rate) |
| NOI_DUNG_DA_TAO | Bài viết AI tạo ra |
| NHAT_KY_PIPELINE | Log mỗi lần pipeline chạy |
| MAU_BAI_VIET | Template bài viết theo tier |
| DANH_SACH_COIN | Danh sách coin theo tier |
| CAU_HINH | Cấu hình hệ thống |
| BREAKING_LOG | Log tin nóng + dedup |
