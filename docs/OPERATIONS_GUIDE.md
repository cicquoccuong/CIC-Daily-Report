# Hướng Dẫn Vận Hành CIC Daily Report

> Dành cho operator (người vận hành). Không cần biết lập trình.

---

## 1. Quy Trình Hàng Ngày

### Mỗi sáng (khoảng 08:00 VN)

Bạn sẽ nhận **6 tin nhắn** trên Telegram:
1. **[L1]** — Báo cáo cho thành viên Level 1 (BTC, ETH)
2. **[L2]** — Báo cáo Level 2 (thêm SOL, BNB...)
3. **[L3]** — Báo cáo Level 3
4. **[L4]** — Báo cáo Level 4
5. **[L5]** — Báo cáo Level 5 (đầy đủ nhất)
6. **[Summary]** — Tóm tắt cho BIC Chat

**Việc cần làm:** Đọc nhanh → copy-paste vào BIC Group/Chat tương ứng.

### Tin nóng (Breaking News)

Pipeline chạy mỗi giờ. Khi có tin nóng, bạn nhận tin nhắn với icon:
- 🔴 **Critical** — Tin cực quan trọng (hack, sập sàn...). Gửi MỌI LÚC, kể cả ban đêm.
- 🟠 **Important** — Tin quan trọng. Ban đêm (23h-7h) sẽ dồn lại gửi lúc 7h sáng.
- 🟡 **Notable** — Tin đáng chú ý. Ban đêm sẽ gom vào báo cáo ngày hôm sau.

---

## 2. Quản Lý Danh Sách Coin

### Thêm/Xóa coin (tab DANH_SACH_COIN)

1. Mở Google Sheets → tab **DANH_SACH_COIN**
2. Mỗi hàng = 1 coin, mỗi cột = 1 tier (L1, L2, L3, L4, L5)
3. **Thêm coin:** Thêm symbol vào cột tier tương ứng
4. **Xóa coin:** Xóa symbol khỏi cột

> Coin ở tier thấp tự động xuất hiện ở tất cả tier cao hơn (tích lũy).
> Thời gian: ≤2 phút. Có hiệu lực từ lần pipeline chạy tiếp theo.

---

## 3. Chỉnh Sửa Mẫu Bài Viết

### Tab MAU_BAI_VIET

Mỗi hàng = 1 section trong bài viết:

| Cột | Ý nghĩa |
|-----|---------|
| tier | L1/L2/L3/L4/L5 |
| section_name | Tên phần (Overview, Analysis...) |
| enabled | TRUE/FALSE — bật/tắt section |
| order | Thứ tự hiển thị (1, 2, 3...) |
| prompt_template | Hướng dẫn cho AI viết phần này |
| max_words | Giới hạn số từ |

**Chỉnh sửa:**
- Tắt section: đổi `enabled` thành `FALSE`
- Đổi thứ tự: thay số ở cột `order`
- Đổi prompt: sửa nội dung cột `prompt_template`

> Thời gian: ≤5 phút. Có hiệu lực từ lần pipeline chạy tiếp theo.

---

## 4. Cấu Hình Hệ Thống

### Tab CAU_HINH

Các thiết lập quan trọng:

| Key | Ý nghĩa | Giá trị mặc định |
|-----|---------|-------------------|
| panic_threshold | Ngưỡng tin nóng | 70 |
| keyword_triggers | Từ khóa kích hoạt tin nóng | hack,exploit,SEC,ban,crash |
| banned_keywords | Từ cấm (NQ05) | nên mua,nên bán,khuyến nghị... |
| night_mode_start | Giờ bắt đầu chế độ đêm (VN) | 23 |
| night_mode_end | Giờ kết thúc chế độ đêm (VN) | 7 |

---

## 5. Đọc Health Dashboard

Mở link GitHub Pages (URL trong README). Dashboard hiển thị:

- **Pipeline Status** — Lần chạy gần nhất (xanh = OK, vàng = một phần, đỏ = lỗi)
- **LLM Provider** — AI nào đang dùng (Groq, Gemini...)
- **Tier Delivery** — Trạng thái gửi từng tier (✅/❌)
- **Data Freshness** — Dữ liệu mới cập nhật chưa
- **Error History** — Lỗi 7 ngày gần nhất

> Dashboard tự cập nhật mỗi 5 phút.

---

## 6. Xử Lý Lỗi

### Khi nhận thông báo lỗi trên Telegram

| Lỗi | Nguyên nhân | Cách xử lý |
|-----|-------------|------------|
| `COLLECTOR_ERROR` | Không lấy được dữ liệu | Kiểm tra API key, thử lại sau |
| `LLM_ERROR` | AI không phản hồi | Tự phục hồi qua fallback. Nếu liên tục → kiểm tra GROQ_API_KEY |
| `DELIVERY_ERROR` | Không gửi được Telegram | Kiểm tra BOT_TOKEN và CHAT_ID |
| `STORAGE_ERROR` | Lỗi Google Sheets | Kiểm tra credentials, quyền share |
| `CONFIG_ERROR` | Cấu hình sai | Kiểm tra tab CAU_HINH |
| `QUOTA_EXCEEDED` | Hết quota API | Chờ reset (thường 1 phút hoặc 1 ngày) |

### FAQ

**Q: Pipeline không chạy?**
A: Vào GitHub → Actions → kiểm tra workflow có bật chưa. Xem logs lần chạy gần nhất.

**Q: Không nhận tin trên Telegram?**
A: Kiểm tra Bot Token và Chat ID trong GitHub Secrets. Gửi `/start` cho bot.

**Q: Nội dung sai/thiếu coin?**
A: Kiểm tra tab DANH_SACH_COIN — coin đã có trong đúng tier chưa.

**Q: Lỗi "quota exceeded"?**
A: API miễn phí có giới hạn. Groq: 30 requests/phút. Chờ 1 phút rồi thử lại.

---

## 7. Chạy Pipeline Thủ Công

Khi cần chạy ngay (không chờ lịch tự động):

1. Vào GitHub → tab **Actions**
2. Chọn workflow:
   - **Daily Pipeline** — báo cáo ngày
   - **Breaking News** — kiểm tra tin nóng
3. Nhấn **"Run workflow"** → **"Run workflow"**
4. Chờ 2-5 phút → kiểm tra Telegram

> Chạy thủ công không ảnh hưởng lịch tự động.
