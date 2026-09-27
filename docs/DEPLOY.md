# تركيب البوت عشان يفضل شغال على طول

الفكرة: جهاز المحل يبعت نسخة من الداتا كل نص ساعة وهو مفتوح، والبوت نفسه شغال على سيرفر
مجاني (PythonAnywhere) طول الوقت، فيرد في أي وقت من آخر نسخة وصلته.

```
جهاز المحل (الياسر)  --كل نص ساعة-->  PythonAnywhere (البوت)  <-->  تليجرام (إنت ووالدك)
   قراءة بس                               شغال 24 ساعة
                                               ^
                              cron-job.org يخبّط عليه كل ربع ساعة: "فيه تقرير معاده جه؟"
```

محتاج: الـ token بتاع البوت، وحساب PythonAnywhere مجاني، وحساب cron-job.org مجاني (الاتنين
من غير فيزا)، وجهاز المحل.

---

## الجزء الأول: السيرفر على PythonAnywhere (مرة واحدة، من المتصفح)

### 1. الحساب
- ادخل https://www.pythonanywhere.com واعمل حساب **Beginner** (المجاني).
- اسم المستخدم هيبقى جزء من عنوان البوت: لو اخترت `elbaraga` العنوان هيبقى
  `https://elbaraga.pythonanywhere.com`. في الخطوات الجاية حط اسمك مكان `USER`.

### 2. تنزيل الكود
من فوق: **Consoles** ← **Bash**. هيفتح شباك أسود. اكتب:
```
git clone https://github.com/AbdoAhmed666/car-bot.git
```
لو الريبو **Private** هيسألك على Username (اكتب `AbdoAhmed666`) وPassword: هنا **مش** باسورد
GitHub، ده token بتعمله من GitHub: Settings ← Developer settings ← Personal access tokens ←
Fine-grained tokens ← Generate: اختار الريبو ده بس، وصلاحية **Contents: Read-only**.

وبعدين:
```
cd car-bot
python3.12 -m venv ~/.virtualenvs/carbot
~/.virtualenvs/carbot/bin/pip install -r requirements-server.txt
cp .env.example .env
```

### 3. الإعدادات
اعمل رقمين سريين طوال (هتحتاجهم دلوقتي وفي جهاز المحل):
```
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```
افتح الإعدادات: من فوق **Files** ← `car-bot` ← `.env`، واملا:
```
TELEGRAM_TOKEN=الـ token بتاع البوت
ALLOWED_USERS=رقمك_على_تليجرام
WEBHOOK_SECRET=الرقم السري الأول
UPLOAD_TOKEN=الرقم السري التاني
AS_OF=
```
مهم: `AS_OF` لازم يبقى **فاضي** هنا. واعمل **Save**.

### 4. تشغيل البوت كموقع
- من فوق: **Web** ← **Add a new web app** ← Next ← **Manual configuration** ← **Python 3.12** ← Next.
- في نفس الصفحة، قسم **Virtualenv**: اكتب `/home/USER/.virtualenvs/carbot`.
- قسم **Code**: دوس على لينك **WSGI configuration file**، امسح كل اللي فيه وحط:
  ```python
  import sys
  sys.path.insert(0, "/home/USER/car-bot")
  from src.webapp import create_app
  application = create_app()
  ```
  واعمل **Save**.
- ارجع لصفحة **Web** ودوس الزرار الأخضر **Reload**.
- افتح `https://USER.pythonanywhere.com` في المتصفح: المفروض يكتب `car-bot is up`.

### 5. توصيل تليجرام بالسيرفر
**الأول اقفل البوت اللي شغال على اللابتوب (Ctrl+C)**: مينفعش الاتنين يشتغلوا بنفس الـ token.
في الـ Bash console:
```
cd ~/car-bot
~/.virtualenvs/carbot/bin/python -m src.webhook set https://USER.pythonanywhere.com
```
المفروض يكتب `webhook set`. ابعت `/start` للبوت: هيرد، بس هيقولك مفيش داتا لسه (لحد ما جهاز
المحل أو اللابتوب يبعت أول نسخة).

### 6. المنبّه: cron-job.org (مجاني)
الحسابات المجانية الجديدة على PythonAnywhere ملهاش مهام بمواعيد، فالسيرفر بيبعت كل تقرير لما
"حد يخبّط عليه" بعد معاده: نسخة من المحل، أو رسالة في البوت، أو المنبّه ده.
- ادخل https://cron-job.org واعمل حساب مجاني (Sign up) بالإيميل.
- **Create cronjob**:
  - Title: `car-bot`
  - URL: `https://USER.pythonanywhere.com/tick`
  - Execution schedule: **Every 15 minutes**
- **Create**.
- تجربة: افتح `https://USER.pythonanywhere.com/tick` في المتصفح: المفروض يكتب `{"sent":[]}`
  (يعني مفيش تقرير معاده جه دلوقتي).

التقارير:
- تحديث العصر: بعد 4:30، لو جهاز المحل بعت حاجة النهارده.
- آخر اليوم: بعد 11:30 بالليل (وليه لحد 6 الصبح)، لو جهاز المحل بعت حاجة النهارده. يوم الجمعة
  والمحل مقفول مش هيبعت حاجة.
- الأسبوع: الخميس مع تقرير آخر اليوم.
- عايز تغيّر المواعيد؟ في `.env` على السيرفر: `DAILY_UPDATE` و`END_OF_DAY` و`WEEKLY_DAY`،
  وبعدين **Reload**. لو المحل بيقفل بعد نص الليل، ينفع `END_OF_DAY=00:30`.

### 7. التجديد
الحساب المجاني بيوقف الموقع لو متجددش (مرة كل شهر للحسابات الجديدة). PythonAnywhere هيبعتلك
إيميل قبلها: ادخل صفحة **Web** ودوس الزرار **Run until ... from today**. لو نسيت، البوت يقف
لحد ما تدوس، ومفيش حاجة بتضيع.

### 8. تجربة من اللابتوب قبل ما تروح المحل
على اللابتوب في `.env` زوّد:
```
SERVER_URL=https://USER.pythonanywhere.com
UPLOAD_TOKEN=نفس الرقم السري التاني
```
وبعدين:
```
.venv\Scripts\python -m src.sync
```
المفروض آخر سطر يبدأ بـ `sent:`. دلوقتي البوت على السيرفر بيرد بداتا النسخة اللي على اللابتوب
(لحد يوم 26/9). جرّب الزراير والأسئلة وإنت فاصل اللابتوب خالص.

---

## الجزء التاني: جهاز المحل (مرة واحدة)

### 0. قبل أي حاجة: نسخة الويندوز
دوس **Win + R** واكتب `winver` وEnter. لو **Windows 10 أو 11** كمّل. لو **Windows 7 أو 8**
وقّف وابعتلي صورة: Python الجديد مش بيشتغل عليهم.

### 1. Python
نزّل **Python 3.12** (64-bit) من https://www.python.org/downloads/windows/ ووإنت بتسطّب
**علّم على Add python.exe to PATH**.

### 2. الكود
نزّل الريبو على `C:\car-bot` (بـ `git clone` أو Download ZIP من GitHub وفكه).
افتح PowerShell جوه الفولدر ده واكتب:
```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-shop.txt
copy .env.example .env
notepad .env
```
(الـ `copy` هنا بس، على جهاز المحل، ومرة واحدة.) واملا:
```
DB_SERVER=shop
DB_NAME=auto
SERVER_URL=https://USER.pythonanywhere.com
UPLOAD_TOKEN=نفس الرقم السري التاني اللي في السيرفر
AS_OF=
```

### 3. تجربة
**افتح برنامج الياسر** وبعدين:
```
.venv\Scripts\python -m src.sync
```
المفروض آخر سطر يبدأ بـ `sent:`. ابعت للبوت "📊 النهارده": هيرد بداتا النهارده.
أول مرة بتاخد وقت أطول شوية (بيحسب التوقع)، وبعد كده مرة واحدة في اليوم.
لو طلع خطأ، صوّره وابعته.

### 4. التشغيل التلقائي كل نص ساعة
```
powershell -ExecutionPolicy Bypass -File tools\install_sync.ps1
```
من هنا ورايح: أول ما الجهاز يفتح وكل نص ساعة، بيبعت نسخة جديدة من غير أي شباك.
لو عايز تتأكد: افتح `data\sync.log`.

---

## الجزء التالت: والدك
- والدك يفتح البوت في تليجرام من موبايله ويدوس **Start**: البوت هيرد برقمه.
- حط الرقم في `.env` على السيرفر: `ALLOWED_USERS=رقمك,رقم_والدك` واعمل **Reload** من صفحة Web.
- خلاص: يسأل في أي وقت، والتقارير توصله لوحدها.

## لو حاجة مشتغلتش
| اللي حصل | السبب الغالب |
|---|---|
| البوت بيقول "مفيش داتا من البرنامج لسه" | جهاز المحل لسه مبعتش: جرّب `python -m src.sync` هناك وبص على `data\sync.log` |
| `sync.log` فيه "ELYASSER is not open" | برنامج الياسر مقفول: هيحاول تاني بعد نص ساعة |
| البوت مش بيرد خالص | صفحة Web على PythonAnywhere: اتأكد إن الموقع شغال (Reload)، و`python -m src.webhook info` |
| "آخر تحديث من المحل" قديم | جهاز المحل مقفول، أو مفيش نت، أو الياسر مقفول |
| تقرير آخر اليوم مجاش | cron-job.org: افتح الـ job وشوف History. وجرّب `https://USER.pythonanywhere.com/tick` |
| `git pull` قال `unable to stat just-written file` | برنامج الحماية (Antivirus) مسك ملف `.ps1` لحظة. شغّل `git status`: لو الملفات موجودة، كمّل |
| `install_sync.ps1` اختفى أو اتمنع | برنامج الحماية: اسمحله (Allow)، أو ابعتلي صورة الرسالة |
