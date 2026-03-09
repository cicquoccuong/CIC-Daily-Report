/**
 * CIC Daily Report — Menu (Google Apps Script)
 *
 * Menu xuất hiện trên thanh công cụ Google Sheets.
 * Tất cả function names phải unique trong GAS global namespace.
 */

// ========== MENU ENTRY POINT ==========

/**
 * Tự động chạy khi mở Spreadsheet.
 */
function onOpen() {
  createDailyReportMenu();
}

/**
 * Tạo menu CIC Daily Report.
 */
function createDailyReportMenu() {
  var ui = SpreadsheetApp.getUi();

  ui.createMenu("📊 CIC Daily Report")
    .addSubMenu(
      ui.createMenu("⚙️ Thiết Lập")
        .addItem("🚀 Thiết Lập Tự Động (tạo 9 tab)", "menuRunAutoSetup")
        .addSeparator()
        .addItem("🔄 Đồng Bộ Cột Thiếu", "menuSyncColumns")
        .addItem("🎨 Định Dạng Lại Toàn Bộ", "menuReformatAll")
    )
    .addSeparator()
    .addSubMenu(
      ui.createMenu("📋 Kiểm Tra")
        .addItem("📊 Trạng Thái Hệ Thống", "menuCheckStatus")
        .addItem("📏 Đếm Dữ Liệu Các Tab", "menuCountData")
    )
    .addSeparator()
    .addSubMenu(
      ui.createMenu("🧹 Công Cụ")
        .addItem("🗑️ Dọn Dẹp Dữ Liệu Cũ (>30 ngày)", "menuCleanupOldData")
    )
    .addSeparator()
    .addItem("❓ Hướng Dẫn", "menuShowHelp")
    .addItem("ℹ️ Phiên Bản", "menuShowAbout")
    .addToUi();
}

// ========== MENU HANDLERS ==========

/**
 * 🚀 Thiết Lập Tự Động — tạo 9 tab + header + định dạng.
 */
function menuRunAutoSetup() {
  var ui = SpreadsheetApp.getUi();
  var response = ui.alert(
    "🚀 Thiết Lập Tự Động",
    "Hệ thống sẽ:\n" +
    "• Tạo 9 tab dữ liệu (nếu chưa có)\n" +
    "• Ghi header tiếng Việt cho mỗi tab\n" +
    "• Định dạng cột số, phần trăm, ngày tháng\n" +
    "• Đóng băng hàng tiêu đề\n" +
    "• Ghi cấu hình mặc định\n\n" +
    "Dữ liệu cũ KHÔNG bị xóa. Tiếp tục?",
    ui.ButtonSet.YES_NO
  );

  if (response !== ui.Button.YES) return;

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.toast("Đang thiết lập...", "📊 CIC Daily Report", -1);

  try {
    var result = createAllSheets();

    var msg = [];
    msg.push("=== KẾT QUẢ THIẾT LẬP ===\n");

    if (result.created.length > 0) {
      msg.push("✅ Đã tạo " + result.created.length + " tab mới:");
      for (var i = 0; i < result.created.length; i++) {
        msg.push("   • " + result.created[i]);
      }
    }

    if (result.synced.length > 0) {
      msg.push("\n🔄 Đã đồng bộ cột:");
      for (var i = 0; i < result.synced.length; i++) {
        msg.push("   • " + result.synced[i]);
      }
    }

    if (result.skipped.length > 0) {
      msg.push("\n⏭️ Đã có sẵn: " + result.skipped.length + " tab");
    }

    if (result.formatted.length > 0) {
      msg.push("\n🎨 Đã định dạng: " + result.formatted.length + " tab");
    }

    if (result.errors.length > 0) {
      msg.push("\n❌ Lỗi:");
      for (var i = 0; i < result.errors.length; i++) {
        msg.push("   • " + result.errors[i]);
      }
    }

    msg.push("\n📊 Tổng: " + result.total + " tab");

    ui.alert(
      result.success ? "✅ Thiết Lập Hoàn Tất" : "⚠️ Thiết Lập Có Lỗi",
      msg.join("\n"),
      ui.ButtonSet.OK
    );
  } catch (e) {
    ui.alert("❌ Lỗi", "Thiết lập thất bại:\n" + e.message, ui.ButtonSet.OK);
  } finally {
    ss.toast("", "", 1);
  }
}

/**
 * 🔄 Đồng Bộ Cột Thiếu — thêm cột mới mà không xóa dữ liệu.
 */
function menuSyncColumns() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.toast("Đang đồng bộ...", "📊 CIC Daily Report", -1);

  try {
    var result = createAllSheets();

    if (result.synced.length > 0) {
      ui.alert(
        "🔄 Đồng Bộ Hoàn Tất",
        "Đã thêm cột mới:\n" + result.synced.join("\n"),
        ui.ButtonSet.OK
      );
    } else {
      ui.alert(
        "✅ Đã Đồng Bộ",
        "Tất cả các tab đã có đủ cột. Không cần thay đổi.",
        ui.ButtonSet.OK
      );
    }
  } catch (e) {
    ui.alert("❌ Lỗi", e.message, ui.ButtonSet.OK);
  } finally {
    ss.toast("", "", 1);
  }
}

/**
 * 🎨 Định Dạng Lại Toàn Bộ — sửa format bị lộn.
 */
function menuReformatAll() {
  var ui = SpreadsheetApp.getUi();
  var response = ui.alert(
    "🎨 Định Dạng Lại",
    "Sẽ áp dụng lại toàn bộ:\n" +
    "• Header: chữ đậm, nền xanh, chữ trắng\n" +
    "• Đóng băng hàng tiêu đề\n" +
    "• Định dạng số, phần trăm\n" +
    "• Chiều rộng cột\n\n" +
    "Dữ liệu KHÔNG bị thay đổi. Tiếp tục?",
    ui.ButtonSet.YES_NO
  );

  if (response !== ui.Button.YES) return;

  try {
    var result = reformatAllSheets();
    ui.alert(
      result.success ? "✅ Hoàn Tất" : "⚠️ Có Lỗi",
      "Đã định dạng: " + result.formatted.join(", ") +
      (result.errors.length > 0 ? "\nLỗi: " + result.errors.join(", ") : ""),
      ui.ButtonSet.OK
    );
  } catch (e) {
    ui.alert("❌ Lỗi", e.message, ui.ButtonSet.OK);
  }
}

/**
 * 📊 Trạng Thái Hệ Thống — kiểm tra tab nào có, tab nào thiếu.
 */
function menuCheckStatus() {
  var ui = SpreadsheetApp.getUi();

  try {
    var status = checkSystemStatus();
    var msg = [];
    msg.push("=== TRẠNG THÁI HỆ THỐNG ===\n");
    msg.push("Tổng tab cần thiết: " + status.totalSheets);
    msg.push("Đã có: " + status.existing.length);
    msg.push("Thiếu: " + status.missing.length);

    if (status.existing.length > 0) {
      msg.push("\n✅ Tab đã có:");
      for (var i = 0; i < status.existing.length; i++) {
        var t = status.existing[i];
        msg.push("   • " + t.name + " (" + t.rows + " dòng) — " + t.description);
      }
    }

    if (status.missing.length > 0) {
      msg.push("\n❌ Tab thiếu:");
      for (var i = 0; i < status.missing.length; i++) {
        var t = status.missing[i];
        msg.push("   • " + t.name + " — " + t.description);
      }
      msg.push("\n→ Chạy '⚙️ Thiết Lập > 🚀 Thiết Lập Tự Động' để tạo.");
    }

    ui.alert("📊 Trạng Thái", msg.join("\n"), ui.ButtonSet.OK);
  } catch (e) {
    ui.alert("❌ Lỗi", e.message, ui.ButtonSet.OK);
  }
}

/**
 * 📏 Đếm Dữ Liệu — số dòng trong mỗi tab.
 */
function menuCountData() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActiveSpreadsheet();

  try {
    var msg = ["=== SỐ DÒNG DỮ LIỆU ===\n"];
    var totalRows = 0;

    for (var i = 0; i < SHEET_CONFIGS.length; i++) {
      var sheet = ss.getSheetByName(SHEET_CONFIGS[i].name);
      if (sheet) {
        var rows = Math.max(sheet.getLastRow() - 1, 0);
        totalRows += rows;
        var icon = rows > 0 ? "📊" : "📭";
        msg.push(icon + " " + SHEET_CONFIGS[i].name + ": " + rows + " dòng");
      } else {
        msg.push("❌ " + SHEET_CONFIGS[i].name + ": chưa tạo");
      }
    }

    msg.push("\n📈 Tổng: " + totalRows + " dòng dữ liệu");
    ui.alert("📏 Đếm Dữ Liệu", msg.join("\n"), ui.ButtonSet.OK);
  } catch (e) {
    ui.alert("❌ Lỗi", e.message, ui.ButtonSet.OK);
  }
}

/**
 * 🗑️ Dọn Dẹp Dữ Liệu Cũ — xóa dòng quá 30 ngày.
 * Chỉ áp dụng cho tab có cột ngày.
 */
function menuCleanupOldData() {
  var ui = SpreadsheetApp.getUi();
  var response = ui.alert(
    "🗑️ Dọn Dẹp Dữ Liệu Cũ",
    "Sẽ xóa dữ liệu quá 30 ngày trong các tab:\n" +
    "• TIN_TUC_THO\n" +
    "• DU_LIEU_THI_TRUONG\n" +
    "• DU_LIEU_ONCHAIN\n" +
    "• NHAT_KY_PIPELINE\n" +
    "• BREAKING_LOG\n\n" +
    "KHÔNG thể hoàn tác. Tiếp tục?",
    ui.ButtonSet.YES_NO
  );

  if (response !== ui.Button.YES) return;

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.toast("Đang dọn dẹp...", "📊 CIC Daily Report", -1);

  try {
    var cleanupTabs = [
      {name: "TIN_TUC_THO", dateCol: 5},         // "Ngày thu thập" = column E
      {name: "DU_LIEU_THI_TRUONG", dateCol: 2},   // "Ngày" = column B
      {name: "DU_LIEU_ONCHAIN", dateCol: 2},       // "Ngày" = column B
      {name: "NHAT_KY_PIPELINE", dateCol: 2},      // "Thời gian bắt đầu" = column B
      {name: "BREAKING_LOG", dateCol: 2}           // "Thời gian" = column B
    ];

    var cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 30);
    var totalDeleted = 0;
    var details = [];

    for (var i = 0; i < cleanupTabs.length; i++) {
      var tab = cleanupTabs[i];
      var sheet = ss.getSheetByName(tab.name);
      if (!sheet || sheet.getLastRow() <= 1) continue;

      var data = sheet.getDataRange().getValues();
      var rowsToDelete = [];

      // Duyệt từ dưới lên để xóa không bị lệch index
      for (var r = data.length - 1; r >= 1; r--) {
        var dateVal = data[r][tab.dateCol - 1];
        if (!dateVal) continue;

        var rowDate;
        if (dateVal instanceof Date) {
          rowDate = dateVal;
        } else {
          rowDate = new Date(String(dateVal));
        }

        if (!isNaN(rowDate.getTime()) && rowDate < cutoff) {
          rowsToDelete.push(r + 1);  // 1-based
        }
      }

      // Xóa từ dưới lên
      for (var j = 0; j < rowsToDelete.length; j++) {
        sheet.deleteRow(rowsToDelete[j]);
      }

      if (rowsToDelete.length > 0) {
        totalDeleted += rowsToDelete.length;
        details.push(tab.name + ": " + rowsToDelete.length + " dòng");
      }
    }

    var msg = totalDeleted > 0
      ? "Đã xóa " + totalDeleted + " dòng cũ:\n" + details.join("\n")
      : "Không có dữ liệu nào quá 30 ngày.";

    ui.alert("🗑️ Dọn Dẹp Hoàn Tất", msg, ui.ButtonSet.OK);
  } catch (e) {
    ui.alert("❌ Lỗi", e.message, ui.ButtonSet.OK);
  } finally {
    ss.toast("", "", 1);
  }
}

/**
 * ❓ Hướng Dẫn Sử Dụng.
 */
function menuShowHelp() {
  var ui = SpreadsheetApp.getUi();
  var msg = [
    "=== HƯỚNG DẪN SỬ DỤNG ===",
    "",
    "📊 CIC Daily Report tự động thu thập tin tức crypto,",
    "phân tích thị trường, và tạo báo cáo mỗi ngày.",
    "",
    "🚀 LẦN ĐẦU SỬ DỤNG:",
    "1. Vào menu ⚙️ Thiết Lập > 🚀 Thiết Lập Tự Động",
    "2. Hệ thống tạo 9 tab với header + định dạng",
    "3. Kiểm tra tab CAU_HINH — chỉnh cấu hình nếu cần",
    "4. Dữ liệu sẽ được ghi tự động bởi GitHub Actions",
    "",
    "📋 KIỂM TRA:",
    "• Trạng Thái Hệ Thống — xem tab nào có, tab nào thiếu",
    "• Đếm Dữ Liệu — xem số dòng trong mỗi tab",
    "",
    "🧹 BẢO TRÌ:",
    "• Dọn Dẹp Dữ Liệu Cũ — xóa dữ liệu quá 30 ngày",
    "• Định Dạng Lại — sửa khi header/cột bị lộn",
    "",
    "💡 DỮ LIỆU KHÔNG BAO GIỜ BỊ XÓA khi chạy Thiết Lập.",
    "Chỉ có 'Dọn Dẹp Dữ Liệu Cũ' mới xóa dữ liệu."
  ];
  ui.alert("❓ Hướng Dẫn", msg.join("\n"), ui.ButtonSet.OK);
}

/**
 * ℹ️ Thông Tin Phiên Bản.
 */
function menuShowAbout() {
  var ui = SpreadsheetApp.getUi();
  ui.alert(
    "ℹ️ CIC Daily Report",
    "Phiên bản: 0.12.0\n" +
    "Nền tảng: Google Sheets + GitHub Actions\n" +
    "AI: Groq Llama 3.3 → Gemini Flash → Flash Lite\n" +
    "Giao hàng: Telegram Bot + Email backup\n\n" +
    "Được phát triển bởi CIC Team\n" +
    "Hệ thống tự động — dữ liệu được cập nhật bởi pipeline",
    ui.ButtonSet.OK
  );
}
