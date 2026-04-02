/**
 * CIC Daily Report — Auto Setup (tạo 9 tab + header + định dạng)
 *
 * Idempotent: chạy lại nhiều lần an toàn — chỉ tạo tab/cột thiếu,
 * không xóa dữ liệu cũ.
 *
 * Schema khớp 100% với Python sheets_client.py TABS constant.
 */

// ========== SHEET SCHEMA ==========

var SHEET_CONFIGS = [
  {
    name: "TIN_TUC_THO",
    description: "Tin tức thô — thu thập từ RSS, CryptoPanic, Telegram",
    headers: [
      "ID", "Tiêu đề", "URL", "Nguồn tin", "Ngày thu thập",
      "Ngôn ngữ", "Tóm tắt", "Loại sự kiện", "Mã coin",
      "Điểm sentiment", "Phân loại hành động"
    ],
    columnWidths: {
      "Tiêu đề": 300,
      "URL": 250,
      "Tóm tắt": 400,
      "Phân loại hành động": 150
    },
    numberFormats: {
      "Điểm sentiment": "0.00"
    }
  },
  {
    name: "DU_LIEU_THI_TRUONG",
    description: "Dữ liệu thị trường — giá, khối lượng, vốn hóa",
    headers: [
      "ID", "Ngày", "Mã tài sản", "Giá", "Thay đổi 24h %",
      "Vốn hóa", "Khối lượng 24h", "Loại", "Nguồn"
    ],
    numberFormats: {
      "Giá": "#,##0.00",
      "Thay đổi 24h %": "#,##0.00\"%\"",
      "Vốn hóa": "#,##0",
      "Khối lượng 24h": "#,##0"
    }
  },
  {
    name: "DU_LIEU_ONCHAIN",
    description: "Dữ liệu on-chain — MVRV, Funding Rate, macro",
    headers: [
      "ID", "Ngày", "Chỉ số", "Giá trị", "Nguồn", "Ghi chú"
    ],
    numberFormats: {
      "Giá trị": "#,##0.0000"
    }
  },
  {
    name: "NOI_DUNG_DA_TAO",
    description: "Nội dung đã tạo — bài viết AI sinh ra",
    headers: [
      "ID", "Ngày tạo", "Loại nội dung", "Cấp tier",
      "Nội dung", "LLM sử dụng", "Trạng thái gửi", "Ghi chú"
    ],
    columnWidths: {
      "Nội dung": 500
    }
  },
  {
    name: "NHAT_KY_PIPELINE",
    description: "Nhật ký pipeline — log mỗi lần chạy",
    headers: [
      "ID", "Thời gian bắt đầu", "Thời gian kết thúc",
      "Thời lượng (giây)", "Trạng thái", "LLM sử dụng", "Lỗi", "Ghi chú"
    ],
    columnWidths: {
      "Lỗi": 400,
      "Ghi chú": 300
    },
    numberFormats: {
      "Thời lượng (giây)": "#,##0"
    }
  },
  {
    name: "MAU_BAI_VIET",
    description: "Mẫu bài viết — template cho từng tier",
    headers: [
      "Cấp tier", "Tên phần", "Bật/Tắt", "Thứ tự",
      "Prompt mẫu", "Số từ tối đa"
    ],
    columnWidths: {
      "Prompt mẫu": 500
    },
    numberFormats: {
      "Thứ tự": "0",
      "Số từ tối đa": "#,##0"
    },
    defaultData: [
      // L1: Beginner — BTC/ETH only, simple language (3 sections)
      ["L1", "Tổng quan thị trường", "BẬT", "1",
       "Viết tổng quan thị trường tài sản mã hóa hôm nay. Tập trung BTC và ETH: giá hiện tại, biến động 24h, vốn hóa, và chỉ số Fear & Greed. Bắt đầu bằng TL;DR 2-3 câu ngắn gọn cho người mới. Sau đó phân tích chi tiết với số liệu cụ thể. Trích nguồn: 'Theo CoinGecko...', 'Dữ liệu CoinLore...'. Viết bằng tiếng Việt, khách quan, không khuyến nghị mua/bán.", "300"],
      ["L1", "Tin nổi bật", "BẬT", "2",
       "Chọn 3-5 tin tức tài sản mã hóa quan trọng nhất hôm nay. Với MỖI tin: (1) Nêu tiêu đề và nguồn, (2) Giải thích ngắn gọn TẠI SAO tin này quan trọng — ảnh hưởng gì đến BTC/ETH hoặc thị trường chung, (3) Nếu có số liệu liên quan (giá, volume, %) thì đề cập. KHÔNG chỉ liệt kê tiêu đề — phải PHÂN TÍCH ý nghĩa. Viết bằng tiếng Việt, dễ hiểu, dùng bullet points (-).", "250"],
      ["L1", "Kết luận & Sự kiện sắp tới", "BẬT", "3",
       "Viết kết luận ngắn gọn 2-3 câu về tình hình thị trường hôm nay (tích cực/tiêu cực/trung tính). Sau đó PHẢI xem phần LỊCH SỰ KIỆN KINH TẾ VĨ MÔ ở trên và liệt kê CỤ THỂ: tên sự kiện, ngày giờ, dự báo (forecast) nếu có. Ví dụ: 'Ngày 18/03: Fed công bố lãi suất (dự báo 4.50%, trước đó 4.75%)'. KHÔNG viết chung chung 'có sự kiện kinh tế' — phải nêu TÊN và SỐ LIỆU cụ thể. Nếu không có sự kiện thì ghi rõ 'Tuần này không có sự kiện vĩ mô quan trọng'. Viết đơn giản.", "200"],

      // L2: Intermediate — TA focus, altcoin coverage (3 sections)
      ["L2", "Phân tích kỹ thuật", "BẬT", "1",
       "Phân tích kỹ thuật các coin chính dựa trên dữ liệu giá và khối lượng. Bắt đầu bằng TL;DR tóm tắt xu hướng chung. Sau đó phân tích chi tiết: mức hỗ trợ/kháng cự quan trọng, xu hướng volume, tín hiệu ngắn hạn. Trích nguồn dữ liệu. Viết bằng tiếng Việt, khách quan, không khuyến nghị mua/bán.", "400"],
      ["L2", "Altcoin đáng chú ý", "BẬT", "2",
       "Liệt kê altcoin có biến động giá lớn (>5%) trong 24h qua. Bắt đầu bằng TL;DR nêu altcoin nổi bật nhất. Sau đó mỗi coin nêu: % biến động, volume thay đổi, nguyên nhân nếu có tin liên quan. Ghi rõ nguồn. Viết bằng tiếng Việt.", "300"],
      ["L2", "Xu hướng & Sự kiện vĩ mô", "BẬT", "3",
       "Tóm tắt xu hướng thị trường ngắn hạn (momentum, sentiment). Nếu có sự kiện kinh tế vĩ mô quan trọng trong tuần (họp Fed, công bố CPI/PPI, NFP...), giải thích ngắn gọn: sự kiện gì, dự báo ra sao, và có thể ảnh hưởng thế nào đến thị trường crypto. Bắt đầu bằng TL;DR 2 câu. Viết dễ hiểu, trích nguồn.", "250"],

      // L3: Advanced — on-chain + macro + derivatives (4 sections)
      ["L3", "Phân tích on-chain", "BẬT", "1",
       "Phân tích dữ liệu on-chain: Funding Rate, dòng tiền vào/ra sàn, MVRV, và các chỉ số blockchain. Bắt đầu bằng TL;DR tóm tắt tín hiệu on-chain chính (tích cực/tiêu cực/trung tính). Sau đó giải thích ý nghĩa từng chỉ số, so sánh với trung bình lịch sử. Trích nguồn: 'Dữ liệu Glassnode...', 'Theo CryptoQuant...'. Viết bằng tiếng Việt.", "350"],
      ["L3", "Vĩ mô & Lịch sự kiện kinh tế", "BẬT", "2",
       "Phân tích tác động yếu tố vĩ mô lên crypto: DXY, giá vàng, lãi suất trái phiếu. Phân tích CHI TIẾT các sự kiện kinh tế hôm nay và sắp tới trong tuần: Fed quyết định lãi suất, CPI, PPI, FOMC, NFP... Với mỗi sự kiện: nêu dự báo (forecast) vs giá trị trước đó (previous), phân tích kịch bản tác động lên BTC/crypto. Bắt đầu bằng TL;DR. Trích nguồn. Viết bằng tiếng Việt.", "350"],
      ["L3", "Tín hiệu Derivatives", "BẬT", "3",
       "Phân tích tín hiệu từ thị trường phái sinh: Funding Rate các coin chính, Open Interest, Long/Short Ratio, Taker Buy/Sell. Bắt đầu bằng TL;DR: thị trường phái sinh đang nghiêng về bulls hay bears. Sau đó chi tiết từng chỉ số, nêu bất thường nếu có. Trích nguồn. Viết bằng tiếng Việt.", "250"],
      ["L3", "Tổng hợp & Triển vọng", "BẬT", "4",
       "Tổng hợp tất cả tín hiệu (on-chain + macro + derivatives + tin tức) thành bức tranh toàn cảnh. Bắt đầu bằng TL;DR 3 câu. Các tín hiệu đang đồng thuận hay mâu thuẫn? Thị trường đang ở giai đoạn nào? Chỉ phân tích, không khuyến nghị. Viết bằng tiếng Việt.", "250"],

      // L4: Expert — sector + risk + sentiment + macro events (4 sections)
      ["L4", "Phân tích rủi ro theo sector", "BẬT", "1",
       "Phân tích rủi ro thị trường theo sector: Layer 1, DeFi, Layer 2, AI tokens, Meme. Bắt đầu bằng TL;DR đánh giá mức rủi ro chung. Sau đó so sánh hiệu suất giữa các sector, xác định sector outperform/underperform, đánh giá rủi ro tập trung. CHỈ PHÂN TÍCH rủi ro — TUYỆT ĐỐI KHÔNG đưa tỷ lệ phân bổ (%) hoặc khuyến nghị mua/bán. Trích nguồn dữ liệu. Viết bằng tiếng Việt.", "350"],
      ["L4", "Sentiment & Derivatives", "BẬT", "2",
       "Phân tích sentiment thị trường: Fear & Greed Index, Altcoin Season Index, funding rate tổng hợp, liquidation data, Long/Short ratio. Bắt đầu bằng TL;DR: sentiment chung đang ở mức nào. Sau đó phân tích chi tiết các chỉ số, so sánh với mức trung bình và cực đoan lịch sử. Trích nguồn. Viết bằng tiếng Việt.", "300"],
      ["L4", "Sự kiện vĩ mô & Tác động", "BẬT", "3",
       "Phân tích CHUYÊN SÂU các sự kiện kinh tế vĩ mô hôm nay và tuần này. Với mỗi sự kiện quan trọng (Fed, CPI, PPI, FOMC, NFP...): (1) Nêu forecast vs previous, (2) Phân tích 2 kịch bản (tốt hơn/xấu hơn dự báo), (3) Tác động lên DXY → BTC → altcoins. Liên kết với dữ liệu FRED (lãi suất, CPI, Fed Balance Sheet). Bắt đầu bằng TL;DR. Viết chuyên sâu bằng tiếng Việt.", "300"],
      ["L4", "Tín hiệu cảnh báo", "BẬT", "4",
       "Tổng hợp tín hiệu cảnh báo đáng chú ý: funding rate bất thường, Fear & Greed cực đoan, volume đột biến, liquidation lớn. Bắt đầu bằng TL;DR: có hay không tín hiệu cảnh báo nghiêm trọng. Sau đó phân tích chi tiết từng tín hiệu, giải thích ý nghĩa lịch sử. Chỉ nêu THÔNG TIN, không khuyến nghị hành động. Trích nguồn. Viết bằng tiếng Việt.", "250"],

      // L5: Master — comprehensive 6-section analysis
      ["L5", "Executive Summary", "BẬT", "1",
       "Viết Executive Summary (TL;DR) 5-7 câu tổng hợp toàn bộ tình hình: giá BTC/ETH, sentiment, on-chain, macro, sự kiện kinh tế sắp tới. Mỗi câu chứa 1 insight quan trọng nhất. Viết ngắn gọn, ai đọc cũng hiểu, không thuật ngữ phức tạp. Đây là phần QUAN TRỌNG NHẤT — người bận chỉ đọc phần này.", "200"],
      ["L5", "Macro & Sự kiện kinh tế", "BẬT", "2",
       "Phân tích TOÀN DIỆN yếu tố vĩ mô và lịch sự kiện: DXY, Gold, Oil, VIX, S&P 500, US 10Y Treasury. Phân tích CHUYÊN SÂU mỗi sự kiện kinh tế quan trọng (Fed Rate Decision, CPI, PPI, FOMC, NFP...): forecast vs previous, 2 kịch bản, tác động dây chuyền lên crypto. Liên kết FRED data (Fed Balance Sheet, CPI trend, Treasury Yield curve). So sánh correlation BTC-DXY, BTC-Gold hiện tại vs trung bình. Trích nguồn cụ thể.", "400"],
      ["L5", "On-chain deep dive", "BẬT", "3",
       "Phân tích chuyên sâu on-chain: MVRV Z-Score, SOPR, Exchange Reserves trend, Funding Rate by exchange, Open Interest, Taker Buy/Sell Volume. So sánh mỗi chỉ số với historical average và extreme zones. Phân tích dòng tiền: BTC/ETH đang chảy vào hay ra khỏi sàn? Whale activity? Trích nguồn Glassnode/CryptoQuant. Bắt đầu bằng TL;DR 3 câu.", "400"],
      ["L5", "Sector rotation & Performance", "BẬT", "4",
       "Phân tích sector rotation: Layer 1, DeFi, Layer 2, AI tokens, Meme, Stablecoins. Xác định dòng tiền đang dịch chuyển từ sector nào sang sector nào. So sánh hiệu suất 24h và 7d giữa các sector. Phân tích nguyên nhân rotation (tin tức, narrative, technical). Bắt đầu bằng TL;DR. CHỈ PHÂN TÍCH, không khuyến nghị. Trích nguồn.", "350"],
      ["L5", "Phân tích liên thị trường", "BẬT", "5",
       "Phân tích mối tương quan crypto vs tài chính truyền thống: BTC-DXY correlation, BTC-Gold correlation, crypto-equity correlation. Derivatives insight: funding rate disparity giữa các sàn, OI concentration, basis spread. Bắt đầu bằng TL;DR. Phân tích cross-market signals: các thị trường đang gửi tín hiệu gì? Đồng thuận hay mâu thuẫn? Trích nguồn.", "350"],
      ["L5", "Risk flags & Kết luận", "BẬT", "6",
       "Tổng hợp tất cả risk flags: (1) On-chain anomalies, (2) Derivatives extremes, (3) Macro risks từ sự kiện kinh tế, (4) Sentiment extremes. Đánh giá mức rủi ro tổng thể (thấp/trung bình/cao) với dẫn chứng cụ thể. Kết luận: các yếu tố đang hỗ trợ hay cản trở thị trường? Bức tranh toàn cảnh. Chỉ phân tích, không khuyến nghị hành động. Trích nguồn.", "300"]
    ]
  },
  {
    name: "DANH_SACH_COIN",
    description: "Danh sách coin — phân tier L1-L5",
    headers: [
      "Mã coin", "Tên đầy đủ", "Cấp tier", "Bật/Tắt", "Ghi chú"
    ],
    defaultData: [
      ["BTC", "Bitcoin", "L1", "BẬT", "Tài sản số lớn nhất"],
      ["ETH", "Ethereum", "L1", "BẬT", "Nền tảng smart contract lớn nhất"],
      ["SOL", "Solana", "L2", "BẬT", "Layer 1 hiệu suất cao"],
      ["BNB", "BNB", "L2", "BẬT", "Hệ sinh thái Binance"],
      ["XRP", "XRP", "L2", "BẬT", "Thanh toán xuyên biên giới"],
      ["ADA", "Cardano", "L3", "BẬT", "Layer 1 proof-of-stake"],
      ["DOGE", "Dogecoin", "L3", "BẬT", "Memecoin lớn nhất"],
      ["AVAX", "Avalanche", "L3", "BẬT", "Layer 1 subnet"],
      ["TRX", "TRON", "L3", "BẬT", "Mạng stablecoin lớn"],
      ["DOT", "Polkadot", "L4", "BẬT", "Parachain ecosystem"],
      ["LINK", "Chainlink", "L4", "BẬT", "Oracle hàng đầu"],
      ["UNI", "Uniswap", "L4", "BẬT", "DEX lớn nhất"],
      ["MATIC", "Polygon", "L4", "BẬT", "Layer 2 Ethereum"],
      ["AAVE", "Aave", "L5", "BẬT", "DeFi lending lớn nhất"],
      ["ARB", "Arbitrum", "L5", "BẬT", "Layer 2 Ethereum"],
      ["OP", "Optimism", "L5", "BẬT", "Layer 2 Ethereum"],
      ["INJ", "Injective", "L5", "BẬT", "DeFi Layer 1"],
      ["SUI", "Sui", "L5", "BẬT", "Move-based Layer 1"]
    ]
  },
  {
    name: "CAU_HINH",
    description: "Cấu hình hệ thống — key/value settings",
    headers: [
      "Khóa", "Giá trị", "Mô tả"
    ],
    columnWidths: {
      "Khóa": 200,
      "Giá trị": 250,
      "Mô tả": 400
    },
    defaultData: [
      ["panic_threshold", "70", "Ngưỡng điểm panic để phát hiện tin nóng (0-100)"],
      ["night_mode_start", "23", "Giờ bắt đầu chế độ đêm (VN timezone, 0-23)"],
      ["night_mode_end", "7", "Giờ kết thúc chế độ đêm (VN timezone, 0-23)"],
      ["cooldown_hours", "4", "Thời gian chờ trước khi gửi lại tin cùng chủ đề (giờ)"],
      ["max_rows_per_tab", "5000", "Số dòng tối đa mỗi tab (auto-cleanup khi vượt)"],
      ["retention_days", "30", "Số ngày giữ dữ liệu cũ trước khi dọn dẹp"],
      ["llm_primary", "groq", "LLM chính (groq/gemini)"],
      // v2.0 Đợt 2: Updated display names to match current model IDs
      ["llm_fallback_1", "gemini-2.5-flash", "LLM dự phòng 1"],
      ["llm_fallback_2", "gemini-2.5-flash-lite", "LLM dự phòng 2"]
    ]
  },
  {
    name: "BREAKING_LOG",
    description: "Breaking news log — dedup + trạng thái gửi",
    headers: [
      "ID", "Thời gian", "Tiêu đề", "Hash", "Nguồn",
      "Mức độ", "Trạng thái gửi"
    ],
    columnWidths: {
      "Tiêu đề": 300,
      "Hash": 180
    }
  }
];

// ========== HEADER STYLE ==========

var HEADER_STYLE = {
  background: "#1a73e8",  // Google Blue
  fontColor: "#ffffff",
  fontWeight: "bold",
  fontSize: 10
};

// ========== CORE FUNCTIONS ==========

/**
 * Tạo tất cả 9 tab với header + định dạng.
 * Idempotent — chạy lại an toàn.
 * @returns {Object} Kết quả {success, created, synced, skipped, formatted, errors}
 */
function createAllSheets() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var results = {
    created: [],
    synced: [],
    skipped: [],
    formatted: [],
    errors: []
  };

  for (var i = 0; i < SHEET_CONFIGS.length; i++) {
    var config = SHEET_CONFIGS[i];
    try {
      var sheet = ss.getSheetByName(config.name);

      if (sheet) {
        // Sheet đã tồn tại — kiểm tra + sync cột thiếu
        var syncResult = syncMissingColumns_(sheet, config);
        if (syncResult.added.length > 0) {
          results.synced.push(config.name + ": +" + syncResult.added.join(", "));
        } else {
          results.skipped.push(config.name);
        }
        // Luôn format lại header cho đẹp
        formatHeader_(sheet, config.headers.length);
        results.formatted.push(config.name);
      } else {
        // Tạo sheet mới
        sheet = ss.insertSheet(config.name);

        // Ghi header
        sheet.getRange(1, 1, 1, config.headers.length)
          .setValues([config.headers]);

        // Format header
        formatHeader_(sheet, config.headers.length);

        // Đóng băng hàng đầu
        sheet.setFrozenRows(1);

        // Áp dụng number format
        if (config.numberFormats) {
          applyNumberFormats_(sheet, config);
        }

        // Áp dụng column width
        if (config.columnWidths) {
          applyColumnWidths_(sheet, config);
        } else {
          // Auto-resize
          for (var c = 1; c <= config.headers.length; c++) {
            sheet.autoResizeColumn(c);
          }
        }

        // Ghi default data (nếu có, vd: CAU_HINH)
        if (config.defaultData && config.defaultData.length > 0) {
          sheet.getRange(2, 1, config.defaultData.length, config.defaultData[0].length)
            .setValues(config.defaultData);
        }

        results.created.push(config.name);
      }
    } catch (e) {
      results.errors.push(config.name + ": " + e.message);
    }
  }

  // Xóa sheet mặc định "Sheet1" nếu có
  deleteDefaultSheet_(ss);

  return {
    success: results.errors.length === 0,
    created: results.created,
    synced: results.synced,
    skipped: results.skipped,
    formatted: results.formatted,
    errors: results.errors,
    total: SHEET_CONFIGS.length
  };
}

/**
 * Kiểm tra hệ thống — tab nào đã có, tab nào thiếu.
 * @returns {Object} {totalSheets, existing, missing}
 */
function checkSystemStatus() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var existing = [];
  var missing = [];

  for (var i = 0; i < SHEET_CONFIGS.length; i++) {
    var config = SHEET_CONFIGS[i];
    var sheet = ss.getSheetByName(config.name);
    if (sheet) {
      var rowCount = Math.max(sheet.getLastRow() - 1, 0);
      existing.push({name: config.name, rows: rowCount, description: config.description});
    } else {
      missing.push({name: config.name, description: config.description});
    }
  }

  return {
    totalSheets: SHEET_CONFIGS.length,
    existing: existing,
    missing: missing
  };
}

/**
 * Format lại toàn bộ 9 tab (header + number formats + column widths).
 * Dùng khi dữ liệu bị lộn xộn.
 */
function reformatAllSheets() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var formatted = [];
  var errors = [];

  for (var i = 0; i < SHEET_CONFIGS.length; i++) {
    var config = SHEET_CONFIGS[i];
    try {
      var sheet = ss.getSheetByName(config.name);
      if (!sheet) continue;

      formatHeader_(sheet, config.headers.length);
      sheet.setFrozenRows(1);

      if (config.numberFormats) {
        applyNumberFormats_(sheet, config);
      }

      if (config.columnWidths) {
        applyColumnWidths_(sheet, config);
      }

      formatted.push(config.name);
    } catch (e) {
      errors.push(config.name + ": " + e.message);
    }
  }

  return {success: errors.length === 0, formatted: formatted, errors: errors};
}

// ========== HELPER FUNCTIONS ==========

/**
 * Format header row (hàng 1) cho đẹp.
 * @private
 */
function formatHeader_(sheet, numCols) {
  var headerRange = sheet.getRange(1, 1, 1, numCols);
  headerRange
    .setBackground(HEADER_STYLE.background)
    .setFontColor(HEADER_STYLE.fontColor)
    .setFontWeight(HEADER_STYLE.fontWeight)
    .setFontSize(HEADER_STYLE.fontSize)
    .setHorizontalAlignment("center")
    .setWrapStrategy(SpreadsheetApp.WrapStrategy.CLIP);

  // Border dưới header
  headerRange.setBorder(
    false, false, true, false, false, false,
    "#0d47a1", SpreadsheetApp.BorderStyle.SOLID_MEDIUM
  );
}

/**
 * Sync cột thiếu vào sheet đã tồn tại.
 * @private
 */
function syncMissingColumns_(sheet, config) {
  var existingHeaders = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  var added = [];

  for (var i = 0; i < config.headers.length; i++) {
    var header = config.headers[i];
    if (existingHeaders.indexOf(header) === -1) {
      var newCol = sheet.getLastColumn() + 1;
      sheet.getRange(1, newCol).setValue(header);
      added.push(header);
    }
  }

  return {added: added};
}

/**
 * Áp dụng number format cho các cột số.
 * @private
 */
function applyNumberFormats_(sheet, config) {
  var lastRow = Math.max(sheet.getLastRow(), 100);

  for (var colName in config.numberFormats) {
    var colIndex = config.headers.indexOf(colName);
    if (colIndex !== -1) {
      sheet.getRange(2, colIndex + 1, lastRow - 1, 1)
        .setNumberFormat(config.numberFormats[colName]);
    }
  }
}

/**
 * Áp dụng custom column widths.
 * @private
 */
function applyColumnWidths_(sheet, config) {
  // Áp dụng custom widths
  for (var colName in config.columnWidths) {
    var colIndex = config.headers.indexOf(colName);
    if (colIndex !== -1) {
      sheet.setColumnWidth(colIndex + 1, config.columnWidths[colName]);
    }
  }

  // Auto-resize các cột không có custom width
  for (var i = 0; i < config.headers.length; i++) {
    if (!config.columnWidths || !config.columnWidths[config.headers[i]]) {
      sheet.setColumnWidth(i + 1, 120);  // default width
    }
  }
}

/**
 * Cập nhật lại toàn bộ template trong MAU_BAI_VIET.
 * Xóa dữ liệu cũ (giữ header) và ghi lại template mới từ defaultData.
 *
 * Dùng khi cần áp dụng template cải tiến mà không cần xóa/tạo lại sheet.
 * @returns {Object} {success, rowsCleared, rowsWritten}
 */
function resetTemplates() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName("MAU_BAI_VIET");

  if (!sheet) {
    return {success: false, error: "Tab MAU_BAI_VIET chưa tồn tại. Chạy Thiết Lập Tự Động trước."};
  }

  // Find the MAU_BAI_VIET config to get defaultData
  var templateConfig = null;
  for (var i = 0; i < SHEET_CONFIGS.length; i++) {
    if (SHEET_CONFIGS[i].name === "MAU_BAI_VIET") {
      templateConfig = SHEET_CONFIGS[i];
      break;
    }
  }

  if (!templateConfig || !templateConfig.defaultData) {
    return {success: false, error: "Không tìm thấy defaultData cho MAU_BAI_VIET."};
  }

  // Clear existing data (keep header row 1)
  var lastRow = sheet.getLastRow();
  var rowsCleared = 0;
  if (lastRow > 1) {
    rowsCleared = lastRow - 1;
    sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).clearContent();
  }

  // Write new template data
  var data = templateConfig.defaultData;
  sheet.getRange(2, 1, data.length, data[0].length).setValues(data);

  // Re-format
  formatHeader_(sheet, templateConfig.headers.length);

  return {
    success: true,
    rowsCleared: rowsCleared,
    rowsWritten: data.length
  };
}


/**
 * Xóa sheet mặc định "Sheet1" nếu có (và không phải sheet duy nhất).
 * @private
 */
function deleteDefaultSheet_(ss) {
  var defaultNames = ["Sheet1", "Trang tính1", "Trang tính 1"];
  var sheets = ss.getSheets();

  if (sheets.length <= 1) return;  // không xóa sheet cuối cùng

  for (var i = 0; i < defaultNames.length; i++) {
    var defaultSheet = ss.getSheetByName(defaultNames[i]);
    if (defaultSheet) {
      ss.deleteSheet(defaultSheet);
    }
  }
}
