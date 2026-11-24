<div align="center">

# ⚡ Code Mode Antigravity

**Trang bị cho AI một phiên Python sống (REPL) — gộp 10+ lượt gọi tool thành 1.**

[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-3776AB?logo=python&logoColor=white)](#cài-đặt)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-zero-2ea44f)](#tại-sao-nên-dùng)
[![MCP Stdio](https://img.shields.io/badge/MCP-stdio%20JSON--RPC%202.0-6e5494)](#cài-đặt)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[English](README.md) · [Tiếng Việt](README.vi.md)

</div>

---

Khi phải đọc từng file một, tìm kiếm lặp đi lặp lại rồi đổ toàn bộ nội dung thô vào khung chat, AI sẽ ngốn rất nhiều token, chậm chạp và nhanh đầy bộ nhớ ngữ cảnh.

**Code Mode Antigravity** giải quyết triệt để việc đó bằng một máy chủ MCP siêu nhẹ (**không cần thư viện ngoài**), cung cấp phiên Python sống (`py_exec` + `py_reset`). AI chỉ cần viết 1 đoạn Python ngắn để tự đọc, lọc, tính toán trên máy và **chỉ in ra đúng phần tóm tắt cần thiết** — đồng thời giữ nguyên biến và thư viện đã nạp cho các bước sau.

## 💰 Ước tính mức tiết kiệm Token & Chi phí

> *Ví dụ minh họa: kiểm tra và tổng hợp dữ liệu từ 10 file log/JSON (~5.000 token/file) trong một phiên chat đang có sẵn 50K token.*

| Tiêu chí | Không dùng Code Mode | Có Code Mode (`py_exec`) | Mức tiết kiệm ước tính |
|---|---|---|---|
| **Số lượt AI phải chạy** | 10–12 lượt rời rạc | **1–2 lượt** | **Giảm ~80–90% số vòng gọi** |
| **Dữ liệu thô đẩy vào ngữ cảnh** | ~50.000 token (đổ cả nội dung file) | **~500–1.500 token** (chỉ lấy tóm tắt) | **Giảm ~95%+ phình ngữ cảnh** |
| **Token mới & chi phí phát sinh** | Tốn thêm ở mỗi lượt và bị tính lại ở các lượt sau | **Chỉ tính 1 lần** cho kết quả gọn | **Tiết kiệm ~60–85% token & chi phí*** |
| **Độ trễ nhận diện tool** | Phải đọc hướng dẫn (schema) trước | Nạp sớm (`eager: true`) ngay từ lượt 1 | **Vào việc ngay lập tức** |

<sub>*Mức tiết kiệm thực tế tùy thuộc vào độ phức tạp của tác vụ và kích thước file; hiệu quả rõ rệt nhất khi đọc/lọc nhiều file, truy vấn JSON/CSV/SQLite, kiểm tra log hoặc đối chiếu hàng loạt.*</sub>

## 🚀 Cài đặt

Yêu cầu máy đã có **Python 3.8+** và **Git**. Mở Terminal / PowerShell và chạy:

```bash
git clone https://github.com/kninrin-droid/code-mode-antigravity.git
cd code-mode-antigravity
python install_antigravity.py --write
```

*(Nếu báo không tìm thấy `python`, thử thay bằng `py` trên Windows hoặc `python3` trên macOS/Linux. Sau đó **mở lại Antigravity** là dùng được ngay.)*

> [!TIP]
> Trình cài đặt tự động bật **`eager: true`** cho `py_exec` và cài sẵn bộ quy tắc **`plugin/rules/AGENTS.md`** để AI ưu tiên gộp lệnh vào `py_exec` ngay từ đầu thay vì chạy nhiều lệnh shell rời rạc.

## 🔄 Cập nhật

Mở Terminal trong thư mục `code-mode-antigravity` đã tải về trước đó và chạy:

```bash
git pull
python install_antigravity.py --write
```

*(Sau đó **mở lại Antigravity**. Nếu bản cập nhật không đổi `plugin/` hay cấu hình MCP, chỉ cần `git pull` rồi mở lại Antigravity là đủ.)*

## ✨ Tại sao nên dùng?

* **Không cần cài thư viện ngoài** — chỉ dùng thư viện chuẩn có sẵn của Python.
* **Giữ trạng thái xuyên suốt phiên** — biến, module đã `import`, hàm tự định nghĩa và thư mục làm việc (`cwd`) được giữ nguyên giữa các lần gọi.
* **Chống tràn ngữ cảnh thông minh** — tự động cắt output ở ngưỡng ~`50.000` ký tự (giữ phần đầu và cuối) nếu code vô tình in quá dài.
* **Bảo vệ chống treo** — hỗ trợ `timeout` từ `1–600` giây (mặc định `60` giây), tự dừng tiến trình bị kẹt an toàn.
* **Hỗ trợ sẵn UTF-8 trên Windows** — tự bật `PYTHONUTF8=1` để đọc/in tiếng Việt không lỗi font.
* **Đa nền tảng** — tối ưu cho **Antigravity**, dùng được cả cho **Claude Code**, **Cursor** và mọi MCP client hỗ trợ stdio.

## 🧩 Thành phần trong gói

| Thành phần | Vai trò |
|---|---|
| `server.py` | Máy chủ MCP stdio JSON-RPC 2.0 (`py_exec`, `py_reset`) |
| `worker.py` | Tiến trình Python chạy ngầm giữ biến (`STATE`) |
| `install_antigravity.py` | Script cài tự động (luôn sao lưu `.bak-*` trước khi sửa) |
| `plugin/` | Bộ quy tắc `AGENTS.md` giúp AI dùng `py_exec` hiệu quả |
| `test_client.py` | Bộ kiểm thử tự động qua giao thức MCP |

<details>
<summary>⚙️ Nâng cao: xem trước khi cài, cấu hình thủ công, Claude Code / Cursor &amp; kiểm thử</summary>

### Xem trước cấu hình (không ghi file)
```bash
python install_antigravity.py
```

### Chỉ cài máy chủ MCP (bỏ qua bộ quy tắc `plugin/`)
```bash
python install_antigravity.py --write --no-plugin
```

### Chạy kiểm thử nhanh
```bash
python -u test_client.py
```

### Cấu hình thủ công (Antigravity)
Thêm vào `~/.gemini/config/mcp_config.json` (hoặc **Settings > MCP**):
```json
{
  "mcpServers": {
    "code-mode": {
      "command": "python",
      "args": ["-u", "/duong/dan/day/du/toi/code-mode-antigravity/server.py"],
      "tools": {
        "py_exec": {
          "eager": true
        }
      }
    }
  }
}
```

### Dùng cho Claude Code, Cursor hoặc MCP client khác
```json
{
  "mcpServers": {
    "code-mode": {
      "command": "python",
      "args": ["-u", "/duong/dan/day/du/toi/code-mode-antigravity/server.py"]
    }
  }
}
```

### Lưu ý bảo mật
`py_exec` chạy Python với quyền người dùng hiện tại trên máy (không phải sandbox cách ly). Chỉ sử dụng trong môi trường tin cậy.

</details>

## 📄 Giấy phép

MIT — xem [LICENSE](LICENSE).
