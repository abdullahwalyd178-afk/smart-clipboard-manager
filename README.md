# Smart Clipboard Manager · مدير الحافظة الذكي

أداة محلية بتشتغل من الـ System Tray، بتحفظ تاريخ كل نص أو صورة بتعملها Copy، ولو أخدت Screenshot بتستخرج النص منه تلقائيًا (OCR) وتخليه جاهز للـ Paste.

A local, Windows-first system tray app that keeps a history of everything you copy (text **and** images), runs OCR on screenshots automatically, and leaves the extracted text ready to paste.

---

## المميزات · Features

- **سجل محلي 100%** — كل حاجة بتتخزن على جهازك بس (SQLite + ملفات PNG). مفيش أي حاجة بتترفع لأي سيرفر.
  Everything stays on your machine: one SQLite database plus PNG files. Nothing is uploaded anywhere.
- **نصوص وصور** — أي Copy جديد بيتسجل، مع منع التكرار تلقائيًا.
  Text and image clips, with automatic deduplication.
- **OCR تلقائي للصور** — أول ما تعمل Screenshot، النص بيتستخرج وبيتنسخ جاهز للـ Paste. الالتقاط بيتم بأدوات ويندوز العادية (Win+Shift+S لجزء من الشاشة، أو Print Screen) — الصورة بتوصل للحافظة والأداة بتستخرج النص منها تلقائيًا. مفيش زرار التقاط مدمج في الأداة.
  Screenshots are OCR'd automatically and the text is placed on the clipboard, ready to paste. Capture with the normal Windows tools (Win+Shift+S for a region, or Print Screen) - the image lands on the clipboard and the app OCRs it. There is no built-in capture hotkey; the OS does the capturing.
- **يفضل بعد إعادة التشغيل** — السجل محفوظ في قاعدة بيانات، مش بيضيع لو قفلت الجهاز.
  History survives restarts (SQLite persistence).
- **تنظيف تلقائي بعد ٣ أيام** — أي عنصر غير مثبت عدّى ٣ أيام بيتحذف عند التشغيل وكل ساعة أثناء العمل.
  Unpinned items older than 3 days are deleted on startup and every hour while running.
- **حد أقصى للسجل** — آخر ٥٠٠ عنصر غير مثبت افتراضيًا؛ الحد بيتطبق مع كل عملية نسخ جديدة، والعناصر المثبتة بتفضل محفوظة بالإضافة إليه.
  The 500-item default cap is enforced on every new capture; pinned items are retained in addition.
- **Pin 📌** — العناصر المثبتة **مبتتحذفش أبدًا** مع التنظيف.
  Pinned items never expire.
- **تحكم من الـ Tray** — إيقاف مؤقت للتسجيل (Pause)، استرجاع أي عنصر، Pin/Unpin، حذف، أو مسح كل العناصر غير المثبتة.
  Tray menu: pause capture, copy items back, pin/unpin, delete, clear unpinned.

## الخصوصية · Privacy

- السجل محلي بالكامل؛ الكود ده مفيهوش أي شبكة أو Telemetry.
  The history is fully local; this app has no networking or telemetry of any kind.
- انتبه: أي حاجة بتعملها Copy — بما فيها كلمات السر والبيانات الشخصية — ممكن تتخزن محليًا. استخدم **Pause capture** قبل نسخ البيانات الحساسة، ومتعملش Pin لأي سر. قاعدة SQLite غير مشفرة؛ متستخدمش البرنامج كمدير كلمات مرور.
  Anything you copy — including passwords and personal data — may be stored locally. Pause capture before copying sensitive data and never pin secrets. The SQLite history is not encrypted; do not use this app as a password manager.

## عن المعادلات الرياضية · About math equations

بصراحة: Tesseract و EasyOCR بيقروا النصوص المطبوعة كويس جدًا، لكنهم **مش بيفهموا الرموز الرياضية** — صورة معادلة زي ∫x² dx هتطلع حروف مش مظبوطة، مش LaTeX.

Honestly: Tesseract and EasyOCR read printed text well, but they do **not** parse math notation. For real equations this project supports an optional local engine: [pix2tex](https://github.com/lukas-blecher/LaTeX-OCR), which is built exactly for turning equation images into LaTeX. Enable it in `config.json`:

```json
{ "ocr_engine": "pix2tex" }
```

## التثبيت · Installation (Windows)

```powershell
pip install -r requirements.txt
winget install UB-Mannheim.TesseractOCR
```

لو عايز OCR بالعربي كمان، ثبّت حزمة اللغة العربية (ara) من نفس مثبّت Tesseract، وعدّل `ocr_language` إلى `"eng+ara"` في الإعدادات.

For Arabic OCR, install the `ara` traineddata in the Tesseract installer and set `"ocr_language": "eng+ara"`.

## التشغيل · Usage

```powershell
python -m clipboard_manager            # تشغيل أيقونة الـ Tray
python -m clipboard_manager history    # عرض آخر العناصر
python -m clipboard_manager clear      # مسح كل العناصر غير المثبتة
```

## الإعدادات · Configuration

`config.json` في مجلد البيانات (`%APPDATA%\SmartClipboard` على ويندوز):

| Key | Default | Meaning |
| --- | --- | --- |
| `retention_days` | `3` | أيام الاحتفاظ قبل الحذف التلقائي (المثبّت مُستثنى) |
| `poll_interval_seconds` | `0.5` | كل قد إيه يتفحص الحافظة |
| `ocr_engine` | `"tesseract"` | `tesseract` / `easyocr` / `pix2tex` |
| `ocr_language` | `"eng"` | لغات Tesseract |
| `copy_ocr_result_to_clipboard` | `true` | نسخ نتيجة الـ OCR تلقائيًا جاهزة للـ Paste |
| `max_items` | `500` | حد أقصى للعناصر غير المثبتة (الأقدم يُحذف أولًا؛ `0` = بلا حد) |

## الاختبارات · Tests

```powershell
pip install pytest
pytest
```

الاختبارات بتغطي: التخزين ومنع التكرار، الـ Pin وقاعدة الـ ٣ أيام، الاستمرار بعد إعادة التشغيل، مراقبة الحافظة، حد العناصر وتنظيف الصور، التحقق من الإعدادات، وإيقاف آمن أثناء عمليات OCR، واختبار OCR حقيقي على صورة مولّدة (بيتخطى تلقائيًا لو Tesseract مش متثبت).

Tests cover: storage/dedup, pin + retention, restart persistence, clipboard watching, immediate item caps and image cleanup, config validation, safe shutdown during a blocked capture, OCR auto-copy safety, and a real Tesseract OCR run on a generated image (auto-skipped if Tesseract isn't installed).

## التقنيات · Stack

pyperclip · Pillow · pystray · SQLite · Tesseract (default OCR) · optional EasyOCR / pix2tex

## حدود معروفة · Known limitations

- ويندوز هو الهدف الأساسي (اتبني واتختبر عليه). لينكس شغال لمراقبة الحافظة بس الـ Tray محتاج AppIndicator.
  Windows-first; Linux clipboard watching works but the tray needs AppIndicator.
- المعادلات الرياضية محتاجة محرك pix2tex الاختياري (شوف الأعلى).
- الصور اللي مفيهاش نص واضح ممكن تطلع OCR فاضي أو غلط — ده طبيعي.
