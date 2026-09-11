"""
売上ダッシュボード用のローカルサーバー。

このフォルダにある「売上データ.csv」と同じ列構成のCSVファイルを自動で見つけ、
ブラウザ側のダッシュボード(売上ダッシュボード.html)から選択・切り替え・
複数ファイルの合算表示ができるようにするための最小限のAPIを提供します。

外部ライブラリは使わず、Python標準ライブラリだけで動作します。

使い方:
    python dashboard_server.py
    表示されたURL (既定では http://127.0.0.1:8765/) をブラウザで開いてください。
"""

import csv
import http.server
import json
import os
import urllib.parse

HOST = "127.0.0.1"
PORT = 8765

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_HTML = os.path.join(BASE_DIR, "売上ダッシュボード.html")

EXPECTED_HEADER = ["日付", "商品名", "カテゴリ", "地域", "数量", "単価", "売上金額"]


def discover_csv_files():
    """フォルダ内のCSVのうち、想定した列構成に一致するものだけを対象にする。"""
    found = []
    for name in sorted(os.listdir(BASE_DIR)):
        if not name.lower().endswith(".csv"):
            continue
        path = os.path.join(BASE_DIR, name)
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header != EXPECTED_HEADER:
                    continue
                dates = [row[0] for row in reader if row]
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
        if not dates:
            continue
        found.append({
            "filename": name,
            "rows": len(dates),
            "date_min": min(dates),
            "date_max": max(dates),
        })
    return found


def read_csv_rows(name):
    path = os.path.join(BASE_DIR, name)
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header != EXPECTED_HEADER:
            raise ValueError("unexpected header in " + name)
        for line in reader:
            if len(line) < 7:
                continue
            d, p, c, r, q, u, a = line[:7]
            try:
                rows.append({
                    "d": d, "p": p, "c": c, "r": r,
                    "q": int(q), "u": int(u), "a": int(a),
                })
            except ValueError:
                continue
    return rows


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "SalesDashboard/1.0"

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, path):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self._send_json({"error": "dashboard html not found: " + path}, status=404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path in ("/", "/index.html"):
            self._send_html(DASHBOARD_HTML)
            return

        if parsed.path == "/api/files":
            self._send_json(discover_csv_files())
            return

        if parsed.path == "/api/data":
            qs = urllib.parse.parse_qs(parsed.query)
            requested = qs.get("files", [""])[0]
            valid_names = {f["filename"] for f in discover_csv_files()}
            names = [n for n in requested.split(",") if n]
            names = [n for n in names if n in valid_names]  # exact match only -> no path traversal
            if not names:
                self._send_json([])
                return
            rows = []
            for n in names:
                try:
                    rows.extend(read_csv_rows(n))
                except (OSError, ValueError) as e:
                    self._send_json({"error": "failed to read %s: %s" % (n, e)}, status=500)
                    return
            self._send_json(rows)
            return

        self._send_json({"error": "not found: " + parsed.path}, status=404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/upload":
            raw_name = self.headers.get("X-Filename", "")
            name = os.path.basename(urllib.parse.unquote(raw_name)).strip()
            if not name or not name.lower().endswith(".csv") or name in (".", ".."):
                self._send_json({"error": "ファイル名が不正です(.csvファイルのみ対応)"}, status=400)
                return

            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                length = 0
            if length <= 0 or length > 20 * 1024 * 1024:  # 20MB upper bound, plenty for this dataset shape
                self._send_json({"error": "ファイルサイズが不正です"}, status=400)
                return
            raw = self.rfile.read(length)

            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                self._send_json({"error": "UTF-8として読み込めませんでした"}, status=400)
                return

            first_line = text.splitlines()[0] if text.strip() else ""
            header_cells = next(csv.reader([first_line]), [])
            if header_cells != EXPECTED_HEADER:
                self._send_json({
                    "error": "列構成が一致しません。想定するヘッダー: " + ",".join(EXPECTED_HEADER)
                }, status=400)
                return

            path = os.path.join(BASE_DIR, name)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)

            self._send_json({"ok": True, "filename": name})
            return

        self._send_json({"error": "not found: " + parsed.path}, status=404)


def main():
    with http.server.ThreadingHTTPServer((HOST, PORT), Handler) as httpd:
        url = "http://%s:%d/" % (HOST, PORT)
        print("売上ダッシュボードを起動しました: %s" % url)
        print("対象フォルダ: %s" % BASE_DIR)
        csvs = discover_csv_files()
        if csvs:
            print("検出したCSV:")
            for f in csvs:
                print("  - %s (%d件, %s〜%s)" % (f["filename"], f["rows"], f["date_min"], f["date_max"]))
        else:
            print("警告: 想定した列構成のCSVが見つかりませんでした。")
        print("終了するには Ctrl+C を押してください。")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nサーバーを停止しました。")


if __name__ == "__main__":
    main()
