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

WHY unified disclaimer (Wave 0.8.7.1, 2026-05-02 — anh Cường mandate):
    - Trước: FULL + SHORT có wording KHÁC NHAU (FULL dài, SHORT có "Rủi
      ro cao. DYOR." viết tắt). Inconsistent text → confusing cho user khi
      thấy 2 variant trong cùng 1 ngày (daily article vs breaking news).
    - Sau: cả FULL + SHORT dùng CÙNG 1 wording đầy đủ. FULL có thêm `---`
      separator + double newline cho article body, SHORT chỉ thiếu separator
      và bỏ `\\n\\n` mở đầu để tiết kiệm chars trong breaking news.
    - Plain text (KHÔNG asterisk markdown `*Tuyên bố...*`): Telegram
      Markdown V1 đôi khi render asterisk thành italic không nhất quán giữa
      Telegram Desktop, Web, iOS, Android — đặc biệt khi text chứa dấu `:`
      hoặc emoji. Plain text render ổn định 100%.

WHY single marker (Wave 0.8.7.1):
    - FULL và SHORT giờ có CÙNG wording → marker FULL == marker SHORT.
    - Helper `append_nq05_disclaimer` check 1 marker thôi (DISCLAIMER_MARKER_FULL),
      idempotent vẫn work vì caller mix FULL/SHORT trên cùng text → marker
      vẫn match → skip.
    - Cross-contamination guard không còn cần (cùng marker thì không thể
      cross-contaminate). Giữ DISCLAIMER_MARKER_SHORT = DISCLAIMER_MARKER_FULL
      để backward-compat với code/test đang import 2 tên riêng.

WHY marker uniqueness (Wave 0.8.7.1):
    - Marker = `"⚠️ Tuyên bố miễn trừ trách nhiệm: Nội dung trên chỉ mang
      tính chất thông tin và phân tích"` (~95 chars). Có emoji + cụm
      Vietnamese NQ05 đặc thù DÀI → KHÔNG xuất hiện ngẫu nhiên trong văn
      bản LLM bình thường.
    - "thông tin và phân tích" đặt sau "chỉ mang tính chất" tạo signature
      4-word phrase HIẾM trong context không phải disclaimer.
    - Verified bằng test_nq05_marker_false_positive.py (corpus phổ thông VN
      KHÔNG match marker mới).
"""

from __future__ import annotations

# FR17: NQ05-compliant disclaimer (Vietnamese). Wave 0.8.7.1: unified plain text
# version theo anh Cường mandate. FULL variant dùng cho daily/tier articles +
# research — có `---` separator + double newline mở đầu.
DISCLAIMER = (
    "\n\n---\n"
    "⚠️ Tuyên bố miễn trừ trách nhiệm: "
    "Nội dung trên chỉ mang tính chất thông tin và phân tích, "
    "KHÔNG phải lời khuyên đầu tư. Tài sản mã hóa có rủi ro cao. "
    "Hãy tự nghiên cứu (DYOR) trước khi đưa ra quyết định đầu tư."
)

# Wave 0.8.7.1: SHORT variant dùng CÙNG wording với FULL (anh Cường mandate
# unified disclaimer) — chỉ KHÁC ở:
#   * KHÔNG có `---` separator (breaking news budget hẹp)
#   * Single newline mở đầu (thay vì `\n\n` của FULL)
# WHY "trách nhiệm": nq05_filter.py checks for "Tuyên bố miễn trừ trách nhiệm"
# — short disclaimer phải chứa substring này để pass check.
DISCLAIMER_SHORT = (
    "\n"
    "⚠️ Tuyên bố miễn trừ trách nhiệm: "
    "Nội dung trên chỉ mang tính chất thông tin và phân tích, "
    "KHÔNG phải lời khuyên đầu tư. Tài sản mã hóa có rủi ro cao. "
    "Hãy tự nghiên cứu (DYOR) trước khi đưa ra quyết định đầu tư."
)

# Idempotent marker — UNIFIED giữa FULL/SHORT (Wave 0.8.7.1 anh Cường mandate).
# Cụm "thông tin và phân tích" sau "Nội dung trên chỉ mang tính chất" là signature
# NQ05-specific dài ~95 chars (kể cả emoji ⚠️) → KHÔNG thể tạo ngẫu nhiên trong
# văn bản LLM bình thường. Verified false-positive guard trong
# test_nq05_marker_false_positive.py (corpus phổ thông VN không match).
#
# WHY scan toàn text (không chỉ tail): research article ~15K chars; LLM có thể
# hallucinate disclaimer ở giữa (vị trí 8K-13K) → tail-only check sẽ miss →
# double append. Marker đủ unique nên scan toàn text zero false-positive.
DISCLAIMER_MARKER_FULL = (
    "⚠️ Tuyên bố miễn trừ trách nhiệm: Nội dung trên chỉ mang tính chất thông tin và phân tích"
)

# Wave 0.8.7.1: FULL và SHORT cùng wording → marker SHORT alias FULL.
# Giữ tên này để backward-compat với import sites đã hardcode tên cũ.
DISCLAIMER_MARKER_SHORT = DISCLAIMER_MARKER_FULL
