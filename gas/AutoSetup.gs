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
      ["L1", "Tổng quan thị trường", "BẬT", "1",
       "Viết tổng quan ngắn gọn thị trường crypto hôm nay dựa trên dữ liệu bên dưới. Tập trung vào BTC và ETH. Nêu xu hướng chính, mức giá quan trọng, và tâm lý thị trường (Fear & Greed). Viết bằng tiếng Việt, khách quan, không khuyến nghị mua/bán. Ghi rõ: Đây là thông tin tham khảo, không phải lời khuyên đầu tư.", "300"],
      ["L1", "Tin nổi bật", "BẬT", "2",
       "Tóm tắt 3-5 tin tức crypto nổi bật nhất hôm nay từ danh sách tin bên dưới. Mỗi tin 1-2 câu. Ưu tiên tin ảnh hưởng lớn đến thị trường. Viết bằng tiếng Việt.", "200"],
      ["L2", "Phân tích kỹ thuật", "BẬT", "1",
       "Phân tích kỹ thuật các coin trong danh sách dựa trên dữ liệu giá và khối lượng. Nêu mức hỗ trợ/kháng cự quan trọng, xu hướng ngắn hạn. Viết bằng tiếng Việt, khách quan. Không khuyến nghị mua/bán.", "400"],
      ["L2", "Altcoin đáng chú ý", "BẬT", "2",
       "Liệt kê các altcoin có biến động giá lớn (>5%) trong 24h qua. Giải thích ngắn gọn nguyên nhân nếu có tin liên quan. Viết bằng tiếng Việt.", "300"],
      ["L3", "Phân tích on-chain", "BẬT", "1",
       "Phân tích dữ liệu on-chain: Funding Rate, dòng tiền vào/ra sàn, và các chỉ số blockchain quan trọng. Giải thích ý nghĩa từng chỉ số cho người đọc. Viết bằng tiếng Việt.", "400"],
      ["L3", "Phân tích vĩ mô", "BẬT", "2",
       "Phân tích tác động của yếu tố vĩ mô lên thị trường crypto: chỉ số DXY, giá vàng, chính sách Fed, CPI. Liên hệ với diễn biến crypto. Viết bằng tiếng Việt.", "300"],
      ["L4", "Chiến lược phân bổ", "BẬT", "1",
       "Phân tích cơ cấu danh mục gợi ý dựa trên tình hình thị trường hiện tại. Nêu tỷ trọng BTC/ETH/Altcoin/Stablecoin phù hợp. GHI RÕ: Đây chỉ là phân tích tham khảo theo Nghị định 05, không phải lời khuyên đầu tư. Mọi quyết định đầu tư là trách nhiệm của người đọc.", "500"],
      ["L5", "Báo cáo chuyên sâu", "BẬT", "1",
       "Viết báo cáo chuyên sâu toàn diện bao gồm: phân tích kỹ thuật chi tiết, on-chain, vĩ mô, sentiment, và đánh giá rủi ro. Đây là báo cáo cao cấp nhất. GHI RÕ disclaimer NQ05: Thông tin chỉ mang tính tham khảo.", "800"]
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
      ["llm_fallback_1", "gemini-flash", "LLM dự phòng 1"],
      ["llm_fallback_2", "gemini-flash-lite", "LLM dự phòng 2"]
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
