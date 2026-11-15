# LUNA NAV AI: طريقة التشغيل

مشروعنا لتحدي NASA Space Apps 2026 (Lunar Landing Site Navigator). يختار موقع هبوط في القطب الجنوبي للقمر باستخدام بيانات ناسا الحقيقية:

- **LOLA:** تضاريس القمر.
- **Horizons:** موقع الشمس والأرض.

بعد ما يختار الموقع، يتحقق من سلامة المهمة.

> **مهم:** لا تكتبين مفتاح Gemini في أي ملف، ولا ترسلينه لأحد. ينحط في نافذة PowerShell بس.

---

## قبل التشغيل (مرة وحدة بس)

### 1. البرامج المطلوبة
- **Python 3.13** من https://www.python.org/downloads/ (فعّلي خيار "Add Python to PATH" وقت التثبيت).
- **Node.js + pnpm:** اختياري، تحتاجينه بس لو تبين خدمة المسارات (Person 3).

### 2. تثبيت المكتبات
افتحي PowerShell **داخل مجلد المشروع**، يعني المجلد اللي فيه `README_AR.md`، والصقي:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -r original_modules\person1\requirements.txt
.venv\Scripts\python.exe -m pip install -r original_modules\person2\member2\requirements.txt
```

إذا انقطع النت وقت التثبيت، أعيدي نفس السطر.

### 3. بيانات ناسا
إذا ملف `original_modules\person2\member2\data\lola\ldem_75s_240m.img` **مو موجود**، حمّليه:

```powershell
.venv\Scripts\python.exe scripts\get_nasa_lola.py
.venv\Scripts\python.exe scripts\build_lola_terrain.py
```

ولاختبار الدقة، حمّلي بعد خريطة الميل الرسمية من ناسا. بدونها فحص الميل يطلع SKIP:

```powershell
.venv\Scripts\python.exe scripts\get_nasa_lola.py --product ldsm_75s_240m
```

### 4. مفتاح Gemini (اختياري)
1. ادخلي https://aistudio.google.com/apikey وسوي مفتاح بحسابك.
2. شغّلي هذا الأمر في نفس النافذة عشان تتأكدين إن المفتاح شغّال:

```powershell
$env:GEMINI_API_KEY = "مفتاحك الحقيقي هنا"
.venv\Scripts\python.exe scripts\check_gemini.py
```

لازم يطلع `OK: Gemini is ready`.

بدون مفتاح، النظام يشتغل عادي، بس ما يطلع مربع "AI summary".

---

## التشغيل (كل مرة)

تحتاجين **نافذتين PowerShell مفتوحة مع بعض**.

### النافذة 1: الباك إند
افتحيها داخل مجلد المشروع، والصقي:

```powershell
$env:GEMINI_API_KEY = "مفتاحك الحقيقي هنا"
powershell -ExecutionPolicy Bypass -File scripts\start_real_nasa.ps1
```

انتظري لين يطلع `Uvicorn running on http://127.0.0.1:8000`. **خليها مفتوحة ولا تكتبين فيها شي.**

### النافذة 2: الواجهة
افتحي نافذة جديدة، والصقي:

```powershell
cd frontend
py -m http.server 5173
```

### المتصفح
1. افتحي **http://localhost:5173** (المنفذ 5173، مو 8000).
2. اضغطي START MISSION، واختاري نوع المهمة والتاريخ.
3. اضغطي **Launch mission analysis**، وانتظري من دقيقة إلى 4 دقايق. النظام يسحب بيانات ناسا مباشرة.

**للعرض أسرع:** افتحي Advanced settings وخلّي **Days to evaluate = 1**.

---

## اختبار الدقة
خلّي النافذة 1 شغّالة، وافتحي نافذة ثالثة داخل مجلد المشروع:

```powershell
.venv\Scripts\python.exe scripts\accuracy_check.py
```

لازم كل النتائج تطلع **PASS**، وتنحفظ في `accuracy_report.md`.

---

## مشاكل شائعة

| المشكلة | الحل |
| --- | --- |
| `The module '.venv' could not be loaded` | أنتِ داخل مجلد `frontend`. اكتبي `cd ..` |
| `only one usage of each socket address` (منفذ 8000 مشغول) | الصقي السطر اللي تحت الجدول، وبعدين شغّلي النافذة 1 من جديد |
| الصفحة تطلع `{"detail":"Not Found"}` | فتحتي 8000 بالغلط. افتحي http://localhost:5173 |
| `Planner unreachable` | النافذة 1 مقفولة أو وقفت. شغّليها من جديد |
| `Gemini: OFF (... not a real key)` | حطيتي كلمة بدل المفتاح. الصقي المفتاح الحقيقي |
| Gemini يقول `503` أو `timeout` | سيرفرات Google مضغوطة، والنظام يكمل بدونه. جربي بعدين |
| تحذير `Person 3 dependencies missing` | طبيعي. المسارات في الواجهة تشتغل من بيانات LOLA. لو تبين خدمة Person 3: `cd original_modules\person3\moon_navigation; pnpm install; cd ..\..\..` |

سطر تسكير المنافذ 8000 و8001 و8002:

```powershell
foreach ($p in 8000,8001,8002) { Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } }
```

---

## وش نقول للحكام
- **البيانات:** من ناسا، تضاريس LOLA وHorizons، ومقارنة بمناطق Artemis III.
- **الدقة:** النظام **مُتحقَّق منه (validated)** مقابل قيم ناسا المنشورة، **مو مُدرَّب (trained)**. شوفي `accuracy_report.md`: الميل يرتبط بخريطة ناسا الرسمية بنسبة 0.94، وعمق فوهة Shackleton طلع 4.10 كم مقابل 4.1 كم.
- **ملخص Gemini:** يكتب الشرح بس. أي رقم فيه لازم يكون من البيانات، وإلا ينرفض.
- **الحسابات:** ما فيها ذكاء اصطناعي. كلها حسابات ثابتة على بيانات ناسا.
