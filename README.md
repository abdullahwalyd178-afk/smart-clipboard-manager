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
- **تنظيف تلقائي بعد ٣ أيام** — أي عنصر عدّى ٣ أيام بيتحذف لوحده.
  Unpinned items older than 3 days are deleted automatically (on startup and every hour while running).
- **Pin 📌** — العناصر المثبتة **مبتتحذفش أبدًا** مع التنظيف.
  Pinned items never expire.
- **تحكم من الـ Tray** — إيقاف مؤقت للتسجيل (Pause)، استرجاع أي عنصر، Pin/Unpin، حذف، أو مسح كل العناصر غير المثبتة.
  Tray menu: pause capture, copy items back, pin/unpin, delete, clear unpinned.
- **نافذة سجل مستقلة (جديد في v0.2)** — بحث فوري في كل السجل، فلترة (نصوص/صور/مفضلة)، Pin، مفضلة ★، تصنيفات (Tags)، حذف، إعادة OCR، ونسخ رجوع بالـ Enter. بتتفتح من قائمة الـ Tray، أو بـ `python -m clipboard_manager ui`، أو بالاختصار العام **Ctrl+Shift+V** (ويندوز) من غير ما تسيب البرنامج اللي شغال عليه.
  Standalone history window (new in v0.2): instant full-history search, filters, pin/favorite/tags/delete, OCR retry, Enter to copy back. Opens from the tray, the CLI, or the global Ctrl+Shift+V hotkey (Windows) without leaving the app you're working in. Arabic text is pre-shaped with `arabic_reshaper` + `python-bidi` (optional, in requirements) so it displays correctly despite Tk's lack of RTL shaping.

## الخصوصية وحماية البيانات الحساسة · Privacy & sensitive-data protection

- السجل محلي بالكامل؛ الكود ده مفيهوش أي شبكة أو Telemetry.
  The history is fully local; this app has no networking or telemetry of any kind.
- **حماية فعلية، مش مجرد تحذير (جديد في v0.2):** الأداة بتمنع تسجيل المحتوى الحساس قبل ما يوصل لقاعدة البيانات أصلًا:
  Actual filtering, not just a warning (new in v0.2) - sensitive content is dropped before it ever reaches the database:
  - **استثناء تطبيقات** (ويندوز فقط): لو النافذة النشطة لتطبيق موجود في `excluded_apps` (زي مدير كلمات السر بتاعك)، مفيش أي التقاط طالما هو في المقدمة. وكمان `excluded_window_keywords` بيوقف الالتقاط لو عنوان النافذة فيه كلمة معينة (زي "bank").
    App exclusions (Windows only): nothing is captured while an excluded app is in front, or while the window title contains an excluded keyword.
  - **اكتشاف النصوص الشبيهة بكلمات السر** (كل الأنظمة): أي نص منسوخ شكله بيانات اعتماد — تعيين password/token، JWT، مفاتيح AWS/GitHub، أرقام بطاقات (بفحص Luhn)، أو توكن عشوائي طويل — **مبيتخزنش**. اتحكم فيه بـ `skip_suspected_secrets` (شغال افتراضيًا).
    Suspected-secret detection (all platforms): text that looks like a credential is not stored. Heuristics are a seatbelt, not a guarantee - **Pause capture** remains the certain way to keep a copy out of the history.
- حدود صريحة: اكتشاف التطبيق النشط ويندوز فقط (مفيش طريقة موثوقة في المكتبة القياسية على لينكس/ماك)، والاكتشاف التلقائي مش بيمسك كل الأنواع.
  Honest limits: foreground detection is Windows-only, and heuristics cannot catch every secret.

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
| `excluded_apps` | `[]` | أسماء عمليات (.exe) ممنوع التسجيل وهي في المقدمة (ويندوز) |
| `excluded_window_keywords` | `[]` | كلمات في عنوان النافذة توقف التسجيل (ويندوز) |
| `skip_suspected_secrets` | `true` | منع تخزين النصوص الشبيهة بكلمات السر/التوكنات |
| `ocr_timeout_seconds` | `60` | مهلة قصوى لكل عملية OCR |
| `ocr_preprocess` | `false` | تحسين الصورة (تكبير/تباين) قبل Tesseract — يساعد العربي والنصوص الصغيرة |
| `quick_search_hotkey` | `"ctrl+shift+v"` | اختصار عام لفتح نافذة البحث (ويندوز؛ فاضي = معطل) |

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
