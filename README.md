# University Unified Portal (UUP)

A compact Flask MVP portal for **students, professors, and admins**, designed to run locally and deploy on Vercel.

## What is implemented

- Role hierarchy: `admin > professor > student`
- Login with University ID or Email
- Demo seeded users so the portal never looks empty
- Notes & materials
  - Professors/admin can upload notes with optional PDF
  - Students can browse/download notes
  - Students can follow professors and receive updates
- Profile photos
  - Professors/students can upload profile photos (or use photo URL)
- Question papers
  - Upload with optional PDF + important questions list
  - Students can download and practice
- Announcements
  - Class/university/general announcement types
  - In-app notifications + optional email broadcast
- Attendance tracker
  - Subject-wise tracking and overall percentage
  - Shortage warning (`< 75%`)
  - Manual shortage email alert to student
- Timetables
  - Admin uploads timetable files (PDF/image)
  - Hardcoded professional PDF timetables are seeded for CSE, ECE, EEE, ME, CE, IT, BCA, BBA
  - Students/professors can view/download by branch
- Faculty directory with openable profiles and follow/unfollow actions
- Exam-ready question generation from notes/syllabus text
- Right-side toggle panel for quick actions and recent notifications
- Admin user management includes role change + delete student/professor account

## Demo credentials

- Admin: `ADM001` / `admin123`
- Professor: `PRO001` / `prof123`
- Professor: `PRO002` / `prof123`
- Student: `STU2024001` / `student123`
- Additional seeded users: `PRO003`-`PRO007`, `STU2024002`-`STU2024008` (all use `prof123` or `student123`)

You can also sign in using each account's email.

## Where data is stored

- Local development: `portal.db` in project root.
- Vercel serverless runtime: `/tmp/portal.db`.

Important for Vercel: `/tmp` is **ephemeral**. Data can reset between deployments or cold starts.
For production persistence, switch from SQLite to an external database/storage.

## Run locally

```bash
pip install -r requirements.txt
pip install torch
python app.py
```

Open: [http://localhost:5050](http://localhost:5050)

## AI PDF summary model

- The app loads a local summarizer model from `my_exam_summarizer/` once at server startup.
- Summary flow: upload PDF -> text extraction (native + OCR fallback) -> model inference -> human-readable summary output.
- If summary is unavailable, install missing dependencies (`transformers`, `pypdf`, `torch`) and restart.
- If you see a protobuf/tokenizer load error, also install `protobuf` and `sentencepiece`.
- OCR for scanned PDFs uses `pytesseract` + `pypdfium2` + `Pillow`; install the system Tesseract binary too.
- If Tesseract is installed in a custom location, set `TESSERACT_CMD` (for example `/opt/homebrew/bin/tesseract`).
- Current app upload limit is set to `100 MB` per file.
- Large local models and `torch` may not fit typical Vercel serverless limits; local runtime or external inference service is recommended for this feature.

## Optional email setup (for announcements/attendance alerts)

Set environment variables:

- `SMTP_HOST`
- `SMTP_PORT` (default `587`)
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`

Without these, email actions will gracefully fail with a clear message and the app still works.

## Deploy to Vercel

1. Push project to GitHub.
2. Import repo into Vercel.
3. Ensure `vercel.json` is present (already included).
4. Set `SECRET_KEY` (and SMTP vars if needed) in Vercel project environment variables.

## GitHub push (quick)

```bash
git init
git add .
git commit -m "UUP MVP with attendance, announcements, timetables, and PDF notes"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```
