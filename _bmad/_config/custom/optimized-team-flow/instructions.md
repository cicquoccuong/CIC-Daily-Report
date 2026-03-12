# Quy Trình Phối Hợp Team Tối Ưu

Workflow này giúp Anh Cường và team BMAD phối hợp hiệu quả hơn bằng cách phân loại task đúng track và đảm bảo mọi agent liên quan đều tham gia.

## Bước 1: Phân Loại Task (BMad Master)

Hỏi Anh Cường mô tả task cần làm, sau đó phân loại vào 1 trong 3 track:

### Track A — Quick Fix (< 30 phút)
**Khi nào:** Bug nhỏ, typo, config change, hotfix đơn giản
**Agent:** Barry (quick-flow-solo-dev) hoặc Amelia (dev)
**Quy trình rút gọn:**
1. Barry/Amelia đọc context → code → verify
2. Quinn chạy test nhanh (nếu có test suite)
3. Paige ghi 1-2 dòng vào CHANGELOG
4. Done

**Checklist Quick Fix:**
- [ ] Đọc CLAUDE.md + file liên quan
- [ ] Code fix
- [ ] Chạy test/verify
- [ ] Update CHANGELOG (1-2 dòng)

---

### Track B — Feature (1-3 session)
**Khi nào:** Tính năng mới, thay đổi logic nghiệp vụ, UI mới
**Agent:** Cả team, theo chuỗi
**Quy trình đầy đủ (9 bước rút gọn):**

#### B1. Brief & Phân tích (Party Mode — 15-20 phút)
Gọi Party Mode với brief từ Anh Cường. Thứ tự phát biểu:
1. **Mary** (Analyst): Frame vấn đề, phân tích business rules, edge cases
2. **Winston** (Architect): Đánh giá khả thi kỹ thuật, impact lên kiến trúc hiện tại
3. **Sally** (UX): User journey, UX considerations (nếu có UI)
4. **John** (PM): Scope MVP, priority, acceptance criteria
5. **Quinn** (QA): Test scenarios, rủi ro cần cover
6. **Bob** (SM): Estimate effort, plan sprint

#### B2. Tóm tắt & Duyệt
- Bob tóm tắt DỄ HIỂU cho Anh Cường
- CHỜ Anh Cường approve trước khi tiếp

#### B3. Thiết kế (nếu cần — 10-15 phút)
- Winston: kiến trúc/thiết kế kỹ thuật
- Sally: UX mockup/wireframe (nếu có UI)
- Quinn: test plan song song

#### B4. Implement
- Amelia code theo thiết kế đã duyệt
- Quinn viết test song song (KHÔNG CHỜ code xong)
- Nếu spec mơ hồ → Amelia HỎI LẠI, không đoán

#### B5. Verify (MANDATORY GATE)
- Mary review code
- Quinn/Murat chạy test suite
- Cross-file grep verify
- KHÔNG báo "done" trước khi verify xong

#### B6. Document & Report
- Paige ghi lại thay đổi (CHANGELOG + docs liên quan)
- Bob báo cáo kết quả cho Anh Cường (kèm kết quả verify)

---

### Track C — Epic (nhiều session)
**Khi nào:** Module mới, thiết kế lại hệ thống, feature phức tạp
**Agent:** Cả team + deep planning
**Quy trình:**

#### C1. Discovery (1 session)
- John: tạo PRD hoặc product brief
- Mary: competitive analysis, domain research
- Sally: user research, persona definition

#### C2. Solution Design (1 session)
- Winston: architecture design
- Sally: UX design đầy đủ
- Quinn: test architecture
- Bob: epic breakdown, sprint planning

#### C3. Implementation (nhiều session)
- Chạy Track B cho từng story trong epic
- Bob track velocity và progress
- Retrospective sau mỗi sprint

---

## Bước 2: Chạy Track Đã Chọn

Sau khi phân loại, chạy track tương ứng. Tại mỗi bước:
- Agent phụ trách PHẢI phát biểu
- Kết quả được ghi vào output chung (agents đọc từ đây, không qua Anh Cường relay)
- Bob track tiến độ

## Bước 3: Wrap Up

Cuối task (bất kể track nào):
1. Quinn confirm test PASS
2. Paige ghi lại thay đổi
3. Bob tóm tắt session cho Anh Cường
4. Update SESSION_HANDOFF (nếu có) cho session sau

---

## Quy Tắc Vàng

1. **Brief trước, code sau** — Feature mới → Party Mode hoặc ít nhất Mary + John + Sally trước
2. **Quinn song song Amelia** — Test plan viết cùng lúc với code
3. **Paige 5 phút cuối** — Ghi lại "cái gì thay đổi, tại sao"
4. **Đọc context đầu session** — CLAUDE.md + SYSTEM_STATE.md
5. **Agents chủ động** — Không chờ gọi, tự lên tiếng khi thấy cần
6. **Kết quả chảy giữa agents** — Output chung, không relay qua Anh Cường
