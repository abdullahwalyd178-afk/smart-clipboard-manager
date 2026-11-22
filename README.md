# Smart Clipboard Manager · مدير الحافظة الذكي

أداة محلية بتشتغل من الـ System Tray، بتحفظ تاريخ كل نص أو صورة بتعملها Copy، ولو أخدت Screenshot بتستخرج النص منه تلقائيًا (OCR) وتخليه جاهز للـ Paste.

A local, Windows-first system tray app that keeps a history of everything you copy (text **and** images), runs OCR on screenshots automatically, and leaves the extracted text ready to paste.

---

## المميزات · Features

- **سجل محلي 100%** — كل حاجة بتتخزن على جهازك بس (SQLite + ملفات PNG). مفيش أي حاجة بتترفع لأي سيرفر.
  Everything stays on your machine: one SQLite database plus PNG files. Nothing is uploaded anywhere.
- **نصوص وصور** — أي Copy جديد بيتسجل، مع منع التكرار تلقائيًا.
  Text and image clips, with automatic deduplication.
- **OCR تلقائي للصور** — أول ما تعمل Screenshot، النص بيتستخرج وبيتنسخ جاهز للـ Paste.
  Screenshots are OCR'd automatically and the text is placed on the clipboard, ready to paste.
- **يفضل بعد إعادة التشغيل** — السجل محفوظ في قاعدة بيانات، مش بيضيع لو قفلت الجهاز.
  History survives restarts (SQLite persistence).
- **تنظيف تلقائي بعد ٣ أيام** — أي عنصر عدّى ٣ أيام بيتحذف لوحده.
  Unpinned items older than 3 days are deleted automatically (on startup and every hour while running).
- **Pin 📌** — العناصر المثبتة **مبتتحذفش أبدًا** مع التنظيف.
  Pinned items never expire.
- **تحكم من الـ Tray** — إيقاف مؤقت للتسجيل (Pause)، استرجاع أي عنصر، Pin/Unpin، حذف، أو مسح كل العناصر غير المثبتة.
  Tray menu: pause capture, copy items back, pin/unpin, delete, clear unpinned.

## الخصوصية · Privacy

- السجل محلي بالكامل؛ الكود ده مفيهوش أي شبكة أو Telemetry.
  The history is fully local; this app has no networking or telemetry of any kind.
- انتبه: أي حاجة بتعملها Copy — بما فيها كلمات السر — بتتسجل لمدة ٣ أيام. لو بتنسخ حاجة حساسة كتير، استخدم **Pause capture** من قائمة الـ Tray قبلها، ومتعملش Pin لحاجة حساسة (المثبّت مش بيتحذف أبدًا).
  Anything you copy — including passwords — is recorded for up to 3 days. Use **Pause capture** before copying secrets, and don't pin sensitive items (pinned items never expire).

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
| `max_items` | `500` | حد أقصى للعناصر (الأقدم غير المثبّت بيتحذف أولًا) |

## الاختبارات · Tests

```powershell
pip install pytest
pytest
```

الاختبارات بتغطي: التخزين ومنع التكرار، الـ Pin وقاعدة الـ ٣ أيام، الاستمرار بعد إعادة التشغيل، مراقبة الحافظة، إن نتيجة الـ OCR مبتتسجلش كعنصر جديد ومبتكتبش فوق نص نسخته بعدها، واختبار OCR حقيقي على صورة مولّدة (بيتخطى تلقائيًا لو Tesseract مش متثبت).

Tests cover: storage/dedup, pin + 3-day retention, restart persistence, clipboard watching, OCR auto-copy safety (no self-recapture, never overwrites a newer user copy), and a real Tesseract OCR run on a generated image (auto-skipped if Tesseract isn't installed).

## التقنيات · Stack

pyperclip · Pillow · pystray · SQLite · Tesseract (default OCR) · optional EasyOCR / pix2tex

## حدود معروفة · Known limitations

- ويندوز هو الهدف الأساسي (اتبني واتختبر عليه). لينكس شغال لمراقبة الحافظة بس الـ Tray محتاج AppIndicator.
  Windows-first; Linux clipboard watching works but the tray needs AppIndicator.
- المعادلات الرياضية محتاجة محرك pix2tex الاختياري (شوف الأعلى).
- الصور اللي مفيهاش نص واضح ممكن تطلع OCR فاضي أو غلط — ده طبيعي.
