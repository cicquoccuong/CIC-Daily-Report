"""NQ05 disclaimer constants. Single source of truth.

WHY tách module (Wave C+.1, 2026-05-01):
    - Helper `append_nq05_disclaimer` ở `adapters/llm_adapter.py` cần import
      DISCLAIMER + DISCLAIMER_SHORT. Trước đây dùng lazy import từ
      `generators/article_generator.py` để tránh import-time cycle vì
      article_generator.py import từ adapters/llm_adapter.py (lấy
      `LLMAdapter`, `LLMResponse`, `append_nq05_disclaimer`).
    - Lazy import giải quyết cycle nhưng để rò rỉ phụ thuộc khó test
      (helper depends on generators package). Tách module hằng số riêng,
      cả hai cùng import từ `nq05_constants` → KHÔNG còn cycle, helper
      có thể import top-level (deterministic).

WHY 2 markers (Wave C+.1 fix #1+#2, hardened Wave C+.2 2026-05-01):
    - Helper cũ dùng `disclaimer.strip()[:200]` làm signature → tail-only
      check 1500 chars. Vấn đề:
        * Cross-contamination: signature 200 chars của FULL có thể match
          một phần của SHORT (cùng prefix "⚠️ *Tuyên bố miễn trừ trách
          nhiệm:") → caller chuyển từ FULL sang SHORT (hoặc ngược lại) bị
          skip nhầm → NQ05 leak.
        * Tail-only: research article ~15K chars, nếu LLM hallucinate
          disclaimer ở giữa (vị trí 8K-13K) → tail 1500 sẽ miss → double
          append.
    - Wave C+.1 đã sửa nhưng marker quá ngắn ("Nội dung trên" 5 chars,
      "Không phải lời khuyên đầu tư. Rủi ro cao. DYOR" 45 chars) → REGRESSION:
      LLM viết article bình thường có thể chứa cụm này:
        * "Nội dung trên Twitter cho thấy..." → false positive skip → NQ05 leak
        * Quote từ source: "Không phải lời khuyên đầu tư. Rủi ro cao. DYOR..."
          (Binance/exchanges hay dùng cụm này) → false positive skip
    - Wave C+.2 hardening: marker dài hơn + bao gồm emoji ⚠️ + markdown
      asterisk format `*Tuyên bố` — kết hợp 3 đặc trưng KHÔNG THỂ xuất hiện
      ngẫu nhiên trong văn bản LLM bình thường:
        * `DISCLAIMER_MARKER_FULL = "⚠️ *Tuyên bố miễn trừ trách nhiệm:* "
          "Nội dung trên chỉ mang tính"` (~60 chars). Có emoji + asterisk
          markdown + cụm Vietnamese đặc thù NQ05 → unique 100%.
        * `DISCLAIMER_MARKER_SHORT = "⚠️ *Tuyên bố miễn trừ trách nhiệm: "
          "Không phải lời khuyên"` (~52 chars). Tương tự, emoji + asterisk +
          dấu hai chấm + space (KHÔNG có `*` trước `Không` — chỉ SHORT có
          dạng này, FULL có `*` đóng sau `nhiệm:`).
    - Cả 2 marker là EXACT substring của constant tương ứng (verified bằng
      test `test_full_marker_present_in_full` + `test_short_marker_present_in_short`).
    - Cross-uniqueness: FULL có `:* Nội dung` (asterisk đóng), SHORT có `:
      Không` (no asterisk đóng) → marker FULL KHÔNG match được SHORT body
      và ngược lại → giữ nguyên cross-contamination guard từ C+.1.
    - Idempotent rule: nếu BẤT KỲ marker nào đã có TRONG text (any
      position) → skip append. Caller mix FULL/SHORT cũng safe.
"""

from __future__ import annotations

# FR17: NQ05-compliant disclaimer (Vietnamese). Full variant for daily/tier
# articles + research where character budget allows ~250 chars overhead.
DISCLAIMER = (
    "\n\n---\n"
    "⚠️ *Tuyên bố miễn trừ trách nhiệm:* "
    "Nội dung trên chỉ mang tính chất thông tin và phân tích, "
    "KHÔNG phải lời khuyên đầu tư. Tài sản mã hóa có rủi ro cao. "
    "Hãy tự nghiên cứu (DYOR) trước khi đưa ra quyết định đầu tư."
)

# QO.07 (VD-36): Short disclaimer for breaking news — full disclaimer takes 15-20%
# of a 300-400 word breaking message. This 1-line version preserves NQ05 compliance
# while reducing overhead to ~3-5% of content.
# WHY "trách nhiệm": nq05_filter.py checks for "Tuyên bố miễn trừ trách nhiệm"
# — short disclaimer must contain this substring to pass the check.
# WHY "Rủi ro cao": NQ05 requires explicit risk warning in all user-facing content.
DISCLAIMER_SHORT = (
    "\n\n⚠️ *Tuyên bố miễn trừ trách nhiệm: Không phải lời khuyên đầu tư. Rủi ro cao. DYOR.*"
)

# Idempotent markers — UNIQUE per variant. Scan entire text (not tail) to catch
# LLM hallucinated disclaimer in middle of long research articles.
#
# WHY include emoji ⚠️ + markdown `*Tuyên bố`: Wave C+.2 hardening — short
# markers ("Nội dung trên" 5 chars, "Không phải lời khuyên..." 45 chars)
# trigger false positive skip on common Vietnamese phrases (e.g. "Nội dung
# trên Twitter cho thấy...", quote từ Binance "Không phải lời khuyên đầu
# tư..."). Combining emoji + markdown asterisk format + Vietnamese NQ05
# wording = signature LLM article body KHÔNG thể tạo ngẫu nhiên.
#
# WHY exact substring of constant: must be lifted verbatim from DISCLAIMER /
# DISCLAIMER_SHORT so that `MARKER in DISCLAIMER` always holds (locked by
# test_full/short_marker_present_in_full/short).
# only in FULL (asterisk-closed `:*` distinguishes from SHORT `:` + space)
DISCLAIMER_MARKER_FULL = "⚠️ *Tuyên bố miễn trừ trách nhiệm:* Nội dung trên chỉ mang tính"
# only in SHORT (no asterisk close after `:` — FULL has `:*`)
DISCLAIMER_MARKER_SHORT = "⚠️ *Tuyên bố miễn trừ trách nhiệm: Không phải lời khuyên"
