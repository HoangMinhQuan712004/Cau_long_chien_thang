# Giao thức làm việc nhóm – 6 session Claude

Áp dụng cho mọi session. Prompt vai của bạn (`.claude/agents/<vai>.md`) nói **bạn làm gì**;
file này nói **phối hợp thế nào**. Nếu hai file mâu thuẫn, hỏi ARCHITECT.

## 1. Các vai

| Vai | Model | Worktree | Nhánh | Sở hữu (được sửa) |
|---|---|---|---|---|
| ARCHITECT | opus | `E:\caulong-team\architect` (chỉ đọc code) | detached `origin/main` | `board/BOARD.md`, `board/tasks/`, `board/decisions/` |
| BACKEND | opus | `E:\caulong-team\backend` | `be/T-xxx-slug` | `backend/**` (trừ `tests/test_qa_*.py`), `frontend/src/lib/api/schema.d.ts` (chỉ sinh lại) |
| FRONTEND | sonnet | `E:\caulong-team\frontend` | `fe/T-xxx-slug` | `frontend/**` |
| QA | sonnet | `E:\caulong-team\qa` | `qa/T-xxx-slug` | `backend/tests/test_qa_*.py`, `frontend/e2e/**`, `board/qa/` |
| DOCS-STEWARD | sonnet | `E:\caulong-team\docs` | `docs/T-xxx-slug` | `README.md`, `CHANGELOG.md`, `docs/**`, `CLAUDE.md`, `.claude/agents/**`, `.claude/team/**` |
| RELEASE-INTEGRATION | sonnet | `E:\project_caulong` (repo chính) | `main`, `int/T-xxx-slug` | `.github/**`, `deploy/**`, `docker-compose.yml`, `*/Dockerfile`, `.gitignore`, `.gitattributes`, `board/releases/`; merge vào `main`; production |

Cần sửa file không thuộc vai mình → gửi `request` cho chủ sở hữu, không tự sửa.
Thay đổi `CLAUDE.md`, `.claude/agents/**`, `.claude/team/**` cần ARCHITECT đồng ý trước.

## 2. Bảng điều phối – `E:\caulong-team\board\` (ngoài git, mọi session thấy ngay)

```
board/
├── BOARD.md                 # bảng công việc – CHỈ ARCHITECT sửa
├── tasks/T-012-dat-co-dinh.md   # spec từng việc – CHỈ ARCHITECT sửa
├── decisions/ADR-003-....md # quyết định kiến trúc – ARCHITECT
├── messages/                # tin nhắn, mỗi tin một file, KHÔNG sửa/xóa sau khi tạo
├── state/<VAI>.md           # mỗi vai tự ghi: đang làm gì, tin nhắn cuối đã đọc
├── qa/                      # báo cáo kiểm thử – QA
└── releases/                # nhật ký phát hành – RELEASE-INTEGRATION
```

Quy tắc: **chỉ ghi vào file của mình**. Không bao giờ hai vai cùng sửa một file → không mất dữ liệu.

## 3. Tin nhắn

Tên file: `messages/<YYYYMMDD-HHMMSS>-<FROM>-to-<TO>-<T-xxx>-<slug>.md`
(`TO` = một vai hoặc `ALL`; lấy giờ bằng `Get-Date -Format yyyyMMdd-HHmmss`).

```markdown
---
type: request | handoff | question | answer | report | blocker
task: T-012
from: BACKEND
to: FRONTEND
reply_to: 20261023-101500-FRONTEND-to-BACKEND-T-012-hoi-api.md   # nếu là trả lời
---
## Tóm tắt
Một câu: cần gì / đã xong gì.

## Chi tiết
Nhánh, commit, endpoint, file, lệnh chạy để kiểm tra, bằng chứng (output test).

## Cần người nhận làm
- [ ] Việc cụ thể, có tiêu chí xong.
```

| type | Khi nào | Người nhận phải |
|---|---|---|
| `request` | Nhờ vai khác làm việc thuộc quyền họ | Làm hoặc trả lời lý do không làm |
| `handoff` | Xong phần mình, chuyển tiếp | Nhận việc, cập nhật `state/` |
| `question` / `answer` | Thiếu thông tin | Trả lời bằng `answer` có `reply_to` |
| `report` | Kết quả QA / phát hành | Đọc, hành động nếu FAIL |
| `blocker` | Kẹt, không tự gỡ được | ARCHITECT xử lý ưu tiên |

**Đọc hộp thư:** khi bắt đầu, sau mỗi bước lớn, và khi người dùng nói "check inbox":
liệt kê `messages/*-to-<VAI>-*` và `*-to-ALL-*` mới hơn dòng `last_read` trong `state/<VAI>.md`, xử lý, rồi cập nhật `last_read`.
Có thể bật tự kiểm tra: `/loop 10m check inbox theo PROTOCOL`.

Nếu session có tool `SendMessage`/`ListAgents` (Claude Code nhận diện các session cục bộ),
sau khi tạo file tin nhắn được phép gửi **một dòng nhắc** tới session tên tương ứng (`-n`), ví dụ
`"Có tin mới cho bạn: messages/2026...-T-012-api-xong.md"`. Nội dung đầy đủ luôn nằm trong file.

## 4. Vòng đời một việc (task)

```
Người dùng → ARCHITECT: spec tasks/T-xxx + BOARD (todo) + request cho từng vai
  → BACKEND (be/T-xxx) ─ handoff ─┐
  → FRONTEND (fe/T-xxx, merge be/T-xxx khi cần type mới) ─ handoff ─┤
  → DOCS-STEWARD (docs/T-xxx) ─ handoff ─┤
                                         ├→ QA kiểm trên nhánh tích hợp → report PASS/FAIL
                                         └→ RELEASE: int/T-xxx → PR → CI xanh → merge main → CD → kiểm production → report ALL
ARCHITECT cập nhật BOARD theo các report (in_progress → review → released).
```

Trạng thái trên BOARD: `todo` · `in_progress` · `review` (chờ QA) · `ready` (QA PASS, chờ phát hành) · `released` · `blocked`.

**Một spec (tasks/T-xxx) luôn có:** mục tiêu (1–2 câu), tiêu chí chấp nhận đánh số (QA test theo đúng các mục này),
thay đổi API (method, path, request/response, mã lỗi), thay đổi DB (bảng/cột/constraint, migration),
phân việc theo vai, thứ tự phụ thuộc, ngoài phạm vi.

## 5. Git

- Mỗi vai tạo nhánh từ `origin/main` mới nhất: `git fetch; git switch -c be/T-012-dat-co-dinh origin/main`.
- Commit trên nhánh của mình, `git push -u origin <nhánh>`. **Không push `main`, không force-push nhánh người khác.**
- FRONTEND cần API mới chưa lên `main`: `git merge origin/be/T-012-...` vào nhánh `fe/...`.
- Xong việc = nhánh đã push + CI của nhánh xanh (mở PR nháp nếu cần CI: `gh pr create --draft`).
- Chỉ RELEASE-INTEGRATION merge vào `main`. Mọi push `main` = **deploy production** (CI → CD).

## 6. Môi trường mỗi vai (không đụng nhau)

| Vai | DB dev / DB test | Cổng API | Cổng web |
|---|---|---|---|
| BACKEND | `caulong_be` / `caulong_be_test` | 8101 | – |
| FRONTEND | `caulong_fe` / `caulong_fe_test` | 8102 | 3102 |
| QA | `caulong_qa` / `caulong_qa_test` | 8103 | 3103 |
| RELEASE | `caulong` / `caulong_test` | 8001 | 3007 |

Tất cả dùng chung container Postgres/Redis của repo chính (`docker compose up -d db redis` tại `E:\project_caulong`,
cổng 5437/6381). Script `.claude/team/setup-team.ps1` tạo sẵn worktree, DB, file env, venv, node_modules.

## 7. Definition of Done (chung)

- [ ] Đáp ứng mọi tiêu chí chấp nhận trong spec.
- [ ] Lint + test của phần mình xanh trên máy; không giảm test hiện có.
- [ ] Không sửa file ngoài quyền sở hữu (hoặc đã có `request` được đồng ý).
- [ ] Nhánh đã push; tin nhắn `handoff` ghi rõ nhánh, commit, cách kiểm tra.
- [ ] `state/<VAI>.md` đã cập nhật.

## 8. Khi có xung đột hoặc nghi ngờ

- Hai vai bất đồng → mỗi bên gửi `question` cho ARCHITECT kèm lý do; ARCHITECT quyết, ghi `decisions/ADR-xxx`.
- Spec không rõ → hỏi ARCHITECT, **không đoán** nghiệp vụ.
- Việc có rủi ro không đảo ngược được (xóa dữ liệu, đổi schema phá vỡ, đụng production) → dừng, gửi `blocker`, chờ người dùng.
