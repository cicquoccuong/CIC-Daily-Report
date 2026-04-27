# PRD — Wave 3: Delivery Redesign (CIC Daily Report v2.0 Phase 2)

> **Author**: John (PM) — 2026-04-26
> **Updated**: 2026-04-27 — Decisions Resolved (Q1/Q3/Q4 answered by Anh Cường)
> **Status**: DRAFT — chờ Anh Cường review (Q2/Q5 còn open)
> **Reference**: `docs/specs/SPEC-v2.0-phase2-quality-overhaul.md` §4.2 + §5 (Wave 3 tasks P2.22–P2.27)
> **Prerequisite**: Wave 0/1/2/4 đã ship (alpha.16). Đây là phần CUỐI cùng còn thiếu của Phase 2 v2.0.

---

## 1. Goal & Why

**Goal (đo được)**: Giảm số message Telegram CIC Daily Report gửi cho member từ **~9 msg/ngày** xuống **3-5 msg/ngày** mà KHÔNG mất nội dung quan trọng. Đo bằng đếm message thực tế trong 7 ngày soak sau deploy.

**Why (bài học Phase 1)**: Wave 0-2 đã làm content tốt hơn (ít sai số liệu, ít trùng), nhưng member vẫn cảm giác **spam** vì sáng nhận 4 tin (L2+L3+L4+Summary), trưa 2 tin L5, tối 3 tin Research, cộng breaking 25 cái rải rác = quá tải. Member chỉ đọc tin đầu rồi mute nhóm. Quality tăng vô nghĩa nếu không ai đọc.

**Insight chính**: Người đọc cần **1 lần mở app = 1 cái nhìn tổng quan**, không phải 4 lần nhận tin tức rời rạc. Wave 3 = gom thay vì cắt — content giữ nguyên (đã được Wave 1-2 làm sạch), chỉ thay đổi **kênh phân phối**.

---

## 2. Non-goals (KHÔNG làm trong Wave 3)

- ❌ KHÔNG đổi cron schedule của workflow GitHub Actions (giữ daily 01:05 UTC + breaking 4 runs/ngày). Wave 3 chỉ thay đổi **cách compose message**, không đụng scheduler.
- ❌ KHÔNG refactor LLM chain hay prompt engineering (Wave 1-2 đã làm).
- ❌ KHÔNG đụng vào logic detect breaking news (`event_detector.py`, `severity_classifier.py`, `dedup_manager.py`). Chỉ thay đổi **lúc nào gửi và gộp ra sao**.
- ❌ KHÔNG personalize per-user (defer v1.1).
- ❌ KHÔNG A/B test format (defer v1.1).
- ❌ KHÔNG đổi schema Google Sheets (giữ BREAKING_LOG, NHAT_KY_PIPELINE như cũ).
- ❌ KHÔNG đổi disclaimer / NQ05 filter (Wave 0 đã làm).

---

## 3. User Stories

**US1 — Operator (Anh Cường) copy-paste sáng**
> *Là Anh Cường, tôi muốn buổi sáng chỉ nhận 1 message Morning Digest đã gộp đủ summary + breaking đêm + consensus, để tôi copy-paste 1 lần vào BIC Chat thay vì 4 lần như hiện tại.*

**US2 — BIC member đọc sáng**
> *Là member BIC, tôi muốn 8h15 mở Telegram chỉ thấy 1 tin tổng quan đầy đủ thay vì cuộn qua 4 tin lặp lại, để tôi nắm tình hình đêm qua trong dưới 2 phút.*

**US3 — BIC member nhận breaking khẩn**
> *Là member, tôi chỉ muốn nhận thông báo riêng khi có sự kiện THẬT SỰ critical (BTC sập >10%, hack lớn, lệnh cấm), tối đa 5 lần trong 24h sliding window — sự kiện trung bình thì gộp vào Breaking Digest 17h.*

**US4 — Operator tránh spam ngày yên ắng**
> *Là Anh Cường, ngày không có tin nóng tôi không muốn pipeline gửi Breaking Digest rỗng (kiểu "hôm nay không có gì") — phải skip hẳn message đó.*

**US5 — Operator đọc deep analysis cuối tuần**
> *Là Anh Cường, tôi muốn Research chỉ đến vào T2/T4/T6 (không daily), trong 1 message rút gọn, để member paid không cảm thấy bị dội research mỗi tối.*

---

## 4. Functional Requirements

### FR-W3.1 — Morning Digest (08:15 VN)
- **Input**: Master Analysis output (Summary section) + `breaking_today.json` events từ 17:00 hôm trước → 08:00 hôm nay + Consensus snapshot.
- **Compose**: 1 message Telegram HTML, format:
  ```
  📅 [Date] — TỔNG QUAN BUỔI SÁNG
  [Summary section ~1500 chars]
  --- TIN NÓNG ĐÊM QUA ---
  [Top 3 breaking, mỗi cái 2-3 dòng]
  --- ĐỒNG THUẬN THỊ TRƯỜNG ---
  [Consensus snapshot ~500 chars]
  [Disclaimer 1 dòng]
  ```
- **Limit**: ≤ 4000 chars (Telegram message hard cap 4096). Nếu vượt → truncate breaking từ 3 → 2 → 1.
- **Channels**: BIC Chat + BIC Group (cả hai).
- **Replaces**: L2 + L3 + L4 + Summary (4 messages → 1).

### FR-W3.2 — L5 Standalone (13:00 VN)
- **Input**: L5 article đã rút ngắn ở Wave 2 (target_words 1500-2500).
- **Compose**: 1 message duy nhất (không split Part1/Part2).
- **Limit**: ≤ 4000 chars. Nếu dài hơn → split tại `## ` heading nhưng PHẢI báo cảnh trong log.
- **Channels**: BIC Group only (paid).
- **Replaces**: L5 Part1 + L5 Part2 (2 → 1).

### FR-W3.3 — Breaking Digest (17:00 VN)
- **Trigger**: Cron run breaking_pipeline lúc 17:00 VN (đã có schedule 17:00 trong daily-pipeline.yml hoặc tạo job riêng — Architect quyết).
- **Input**: BREAKING_LOG events có `created_at` trong khoảng `[08:00 VN, 17:00 VN)` AND status ∈ {`sent`, `deferred_to_daily`}.
- **Compose**: 1 message gộp các event, mỗi event 2-3 dòng + nguồn.
- **Skip rule (FR-W3.7)**: Nếu < 2 events → skip toàn bộ message (không gửi "không có gì").
- **Channels**: BIC Chat + BIC Group.
- **Replaces**: Individual breaking messages buổi chiều.

### FR-W3.4 — Research Weekly (20:00 VN, T2/T4/T6)
- **Trigger**: Workflow check `datetime.utcnow().isoweekday() in [1, 3, 5]` (Mon/Wed/Fri). Nếu không phải → skip toàn bộ research generation.
- **Compose**: 1 message ≤ 4000 chars.
- **Channels**: BIC Group only.
- **Replaces**: Research P1+P2+P3 daily (3 → 1, 7 ngày → 3 ngày).

### FR-W3.5 — CRITICAL Breaking (anytime)
- **Trigger condition**: Event có `severity == "critical"` AND `panic_score >= 85`. Cả hai phải đạt — KHÔNG OR.
- **Sliding window cap**: MAX 5 CRITICAL trong bất kỳ 24h liên tục (sliding window, KHÔNG reset lúc 0h). Đếm theo `BREAKING_LOG` timestamp. Vượt cap → defer vào Breaking Digest 17h hoặc Morning Digest hôm sau.
- **Compose**: 1 message riêng, gửi NGAY khi detect.
- **Channels**: BIC Chat + BIC Group.

### FR-W3.6 — Remove Individual Tier Messages (L2/L3/L4)
- `daily_pipeline.py` KHÔNG còn gọi `bot.deliver_all()` cho tier articles L2/L3/L4 riêng lẻ.
- Tier articles vẫn được generate (cho Sheet `NOI_DUNG_DA_TAO` + dashboard) nhưng KHÔNG send Telegram riêng.
- L1 (Telegram-only summary) vẫn giữ nếu là input cho Morning Digest, nhưng KHÔNG gửi tách riêng.

### FR-W3.7 — Skip Rules
| Tình huống | Hành động |
|------------|-----------|
| Breaking Digest có 0-1 event | Skip message hoàn toàn (không gửi placeholder) |
| Morning Digest có 0 breaking đêm qua | Vẫn gửi, chỉ bỏ section "TIN NÓNG ĐÊM QUA" |
| Morning Digest LLM fail | Fallback gửi Summary thuần (không có breaking + consensus) + log error |
| Research weekly trùng holiday VN | Vẫn gửi (không skip — operator có thể tự delete) |
| L5 generation fail | Skip L5 13:00, log error, alert admin |
| CRITICAL vượt cap 5/24h sliding window | Defer vào Breaking Digest gần nhất |

### FR-W3.8 — Feature Flag `WAVE3_ENABLED`
- Thêm key `WAVE3_ENABLED` vào tab `CAU_HINH` Google Sheet, default `false`.
- Khi `false` → pipeline chạy như alpha.16 (gửi 9 msg như cũ).
- Khi `true` → pipeline áp dụng FR-W3.1 → FR-W3.7.
- Toggle qua Sheet, KHÔNG cần redeploy code.

---

## 5. Acceptance Criteria

- **AC1**: Trong 1 ngày bình thường (0-1 critical breaking), tổng số message gửi tới mỗi channel = 3-5. Đo bằng count rows `NHAT_KY_PIPELINE` cột `delivery_method` trong 24h.
- **AC2**: Trong 1 ngày breaking (≥2 critical events), tổng message ≤ 10 (3-5 standard + max 5 critical trong 24h sliding window). KHÔNG vượt 10 trong bất kỳ trường hợp nào.
- **AC3**: Morning Digest có đủ 3 section (Summary / TIN NÓNG ĐÊM QUA / ĐỒNG THUẬN), tổng < 4000 chars, parse Telegram HTML không lỗi.
- **AC4**: Breaking Digest 17:00 chỉ gửi khi ≥ 2 events. Test: mock 0 events → KHÔNG có Telegram call. Mock 1 event → KHÔNG có call. Mock 2+ events → có 1 call.
- **AC5**: Research chỉ chạy thứ 2/4/6 (UTC weekday 0/2/4 hoặc VN weekday 1/3/5). Test: mock thứ 3 → research_generator KHÔNG được invoke.
- **AC6**: CRITICAL breaking ≤ 5 trong 24h sliding window. Test: mock 7 critical events trong 24h → chỉ 5 cái được gửi riêng, 2 còn lại defer. Test sliding window: mock 3 events lúc 23:00 + 3 events lúc 01:00 → window check đúng (không reset 0h).
- **AC7**: L2/L3/L4 KHÔNG còn gọi `bot.send_message()` riêng. Test: grep call sites trong `daily_pipeline.py`.
- **AC8**: Feature flag `WAVE3_ENABLED=false` → behavior identical alpha.16 (regression test).
- **AC9**: Morning Digest LLM fail → fallback message vẫn được gửi (không silent drop).
- **AC10**: Soak test 7 ngày trên production → average 3-5 msg/ngày, 0 missed critical event.

---

## 6. Edge Cases & Skip Rules

| Edge case | Xử lý |
|-----------|-------|
| Pipeline chạy lúc 08:15 nhưng `breaking_today.json` chưa có (file race) | Morning Digest gửi không có section breaking, log warning |
| 5 CRITICAL trong vòng 1 giờ | Gửi cả 5 riêng (đạt cap sliding window 24h), event #6 defer |
| LLM gen Morning Digest > 4000 chars sau truncate | Hard cut tại 3950 chars + "..." |
| Holiday VN (Tết) — operator không cần report | Defer config — manual disable qua Sheet `CAU_HINH` (out of scope code) |
| L5 fail nhưng Morning Digest đã gửi | Không rollback Morning Digest. Log L5 error, gửi admin alert |
| Breaking Digest có 5+ events buổi chiều | Gửi 1 digest gộp tất cả (không split) |
| Telegram API rate limit (429) | Retry 3 lần exponential, sau đó email backup (đã có infra) |

---

## 7. Affected Files (estimate LOC delta)

| File | Change | LOC Δ |
|------|--------|-------|
| `src/cic_daily_report/delivery/telegram_bot.py` | Thêm method `send_morning_digest()`, `send_breaking_digest()`. Refactor `deliver_all()` để skip tier riêng khi flag on | +120 / -20 |
| `src/cic_daily_report/delivery/delivery_manager.py` | Add digest composer logic | +80 |
| `src/cic_daily_report/daily_pipeline.py` | Branch logic theo `WAVE3_ENABLED`. Skip individual tier delivery. Compose digest input | +60 / -15 |
| `src/cic_daily_report/breaking_pipeline.py` | Thêm digest mode cho run 17:00 VN. CRITICAL cap enforce | +50 |
| `src/cic_daily_report/storage/config_loader.py` | Read `WAVE3_ENABLED` từ CAU_HINH | +10 |
| `src/cic_daily_report/generators/master_analysis.py` | Expose summary section riêng để Morning Digest dùng | +20 |
| `tests/test_delivery/test_morning_digest.py` (new) | Unit tests | +150 |
| `tests/test_delivery/test_breaking_digest.py` (new) | Unit tests | +120 |
| `tests/test_pipeline/test_wave3_integration.py` (new) | Integration | +200 |
| `.github/workflows/daily-pipeline.yml` | Thêm cron 17:00 VN cho Breaking Digest (nếu chưa có) | +5 |
| `CHANGELOG.md` + `__init__.py` | version bump alpha.17 | +10 |
| **Total** | | **~+800 / -35** |

---

## 8. Test Plan (Quinn implement)

**Unit tests:**
- `test_morning_digest_compose()` — đầy đủ 3 section, đúng order, < 4000 chars
- `test_morning_digest_truncate()` — input quá dài → cắt breaking 3→2→1
- `test_morning_digest_no_breaking()` — không có breaking → bỏ section, vẫn gửi
- `test_morning_digest_llm_fallback()` — LLM fail → fallback summary thuần
- `test_breaking_digest_skip_zero()` — 0 events → không call Telegram
- `test_breaking_digest_skip_one()` — 1 event → không call (< threshold 2)
- `test_breaking_digest_compose()` — N events → 1 message gộp
- `test_critical_cap()` — 7 critical trong 24h → chỉ 5 gửi riêng, 2 defer; test sliding window không reset 0h
- `test_research_weekday_filter()` — Tue/Thu/Sat/Sun → skip; Mon/Wed/Fri → run
- `test_feature_flag_off()` — `WAVE3_ENABLED=false` → behavior alpha.16

**Integration tests:**
- `test_daily_pipeline_wave3_normal_day()` — full run, đếm `bot.send_message()` calls = 3-5
- `test_daily_pipeline_wave3_breaking_day()` — mock 2 critical → đếm calls ≤ 8
- `test_breaking_pipeline_17h_run()` — mock events buổi chiều → đếm calls = 1 digest
- `test_regression_flag_off()` — flag off → identical với baseline alpha.16

**E2E (manual + soak):**
- Deploy alpha.17 với flag OFF → verify regression
- Toggle flag ON → soak 7 ngày → daily count msg, verify AC10
- Mock 1 critical event → verify gửi riêng, log đúng cap

---

## 9. Rollback Plan

**Mechanism**: Feature flag `WAVE3_ENABLED` trong Google Sheet `CAU_HINH`.

**Rollback steps** (nếu phát hiện vấn đề trong soak):
1. Vào Sheet `CAU_HINH`, đổi `WAVE3_ENABLED` từ `true` → `false`. Effect: pipeline run kế tiếp dùng behavior alpha.16.
2. KHÔNG cần redeploy code, KHÔNG cần git revert.
3. Verify: pipeline run kế tiếp gửi đủ 9 msg như cũ.

**Soak plan**:
- Tuần 1: deploy alpha.17 với flag OFF → verify regression test pass.
- Tuần 2: bật flag → soak. Anh Cường đánh giá hàng ngày.
- Tuần 3: nếu OK → giữ ON, plan v1.1. Nếu vấn đề → flag OFF + retro.

---

## 10. Out of Scope (defer to v1.1+)

- **Personalization**: Mỗi user chọn nhận message nào (Morning only, breaking only, …). Yêu cầu user DB → phức tạp.
- **A/B test format**: Thử nghiệm 2 phiên bản Morning Digest format → cần analytics infra.
- **Click tracking**: Đo % member open Telegram message → cần tracking links + storage.
- **Adaptive cap**: Tự điều chỉnh CRITICAL cap theo market regime (bull/bear/crash).
- **Multi-channel**: Push tới Discord/Twitter song song Telegram.
- **Real-time digest re-compose**: Nếu breaking xảy ra giữa 2 digest, re-compose Morning Digest sắp tới.

---

## 11. Effort Estimate

| Story | Description | ETA |
|-------|-------------|-----|
| S1 | Morning Digest composer + tests | 1-1.5 ngày |
| S2 | Breaking Digest composer + 17h scheduler + tests | 1 ngày |
| S3 | L5 standalone shorten + Research weekly filter + tests | 0.5 ngày |
| S4 | CRITICAL cap + remove individual tiers + feature flag | 1 ngày |
| S5 | Integration tests + regression suite + soak prep | 1 ngày |
| **Total** | | **4.5-5 ngày dev** + **7 ngày soak** |

Story count: **5 stories**, sequential (S1 → S2 song song S3 → S4 → S5).

---

## 12. Open Questions for Anh Cường

1. **17:00 VN Breaking Digest channel**: Gửi cả BIC Chat + BIC Group, hay chỉ Group? Spec gốc nói "Both" — confirm?
2. **Holiday VN (Tết, lễ lớn)**: Có muốn auto-skip pipeline không, hay vẫn gửi và Anh Cường tự bỏ qua? Hiện PRD không tự skip.
3. **Morning Digest truncate priority**: Khi vượt 4000 chars, ưu tiên giữ section nào? Đề xuất: Summary (giữ full) > Consensus > Breaking (cắt từ 3→1). Confirm?
4. **CRITICAL cap = 3/ngày — quá ít hay đủ?**: Trong 30 ngày qua, có ngày nào có 4-5 critical thật sự không thể defer? Nếu có → cân nhắc raise cap hoặc đổi sang sliding window 12h.
5. **Feature flag default**: Deploy với `WAVE3_ENABLED=false` (cần Anh Cường bật thủ công) hay `=true` (live ngay)? Đề xuất: default false, soak 1 tuần regression, sau đó bật.

---

---

## Decisions Resolved (2026-04-27)

Anh Cường đã trả lời 3 open questions:

1. **Breaking Digest 17h** → gửi cả BIC Chat + BIC Group (cả 2 channel).
2. **Morning Digest khi vượt 4096 chars** → ưu tiên giữ Summary, cắt Breaking section trước.
3. **CRITICAL Breaking cap** → tăng từ 3 → **5 messages**, dùng cơ chế **24h sliding window** (bất kỳ 24h liên tục tối đa 5 messages, KHÔNG reset 0h).

---

> **Done when**:
> - Anh Cường review + confirm 12 open questions
> - Spec approved → Amelia code 5 stories
> - Quinn pass tất cả AC1-AC10
> - Soak 7 ngày production: avg 3-5 msg/ngày, 0 missed critical, 0 LLM fail không có fallback
> - Paige ghi CHANGELOG alpha.17 + sync Wiki `decisions/cdr-phase2-quality-overhaul.md`
