# Meerkat 🦦 — แผนพัฒนา (meerkat-posture)

> แอปเตือนท่านั่งแบบออฟไลน์ ใช้กล้องโน้ตบุ๊กหรือกล้อง USB จับท่าทาง แล้วเตือนเมื่อก้ม เงย หัน เอียง ค้างนานเกินไป หรือนั่งนานเกิน
> ทุกอย่างประมวลผลบนเครื่อง ไม่เก็บภาพ ไม่ส่งข้อมูลออกนอกเครื่อง

---

## 0. วิธีใช้ไฟล์นี้กับ Claude Code

1. สร้างโฟลเดอร์ `meerkat-posture/` แล้ววางไฟล์นี้ไว้ที่ root
2. เปิดโฟลเดอร์ใน VS Code แล้วเปิด Claude Code
3. เริ่มด้วย prompt นี้:

```
อ่าน PLAN.md ให้ครบ แล้วทำ Phase 0 และ Phase 1 ตามแผน
ทำทีละ task, ติ๊ก checkbox ใน PLAN.md เมื่อเสร็จ
ห้ามละเมิดหัวข้อ "กฎเหล็ก" ในข้อ 2 เด็ดขาด
หยุดถามฉันก่อนถ้าต้องเปลี่ยน stack หรือโครงสร้างโฟลเดอร์
```

4. จบแต่ละ phase ให้รันเองและลองใช้จริง ก่อนสั่งทำ phase ถัดไป

---

## 1. เป้าหมาย

### ต้องทำได้ (MVP)
- ตรวจ **ก้ม / เงย / หันซ้ายขวา / เอียงคอ** ค้างนานเกินกำหนดแล้วเตือน
- รองรับ **สองจอ**: หันไปจอที่สองไม่นับว่าผิด ถ้าอยู่ในโซนที่ calibrate ไว้
- ตรวจ **ไหล่เอียง / ตัวบิด / โน้มตัวเข้าหาจอ** (คอยื่น)
- **นับเวลานั่ง** แล้วเตือนให้ลุกทุก 30 นาที ถ้าไม่เห็นคนในกล้องนานพอให้ถือว่าลุกแล้ว และรีเซ็ตตัวนับ
- อยู่ใน **system tray** ไอคอนเปลี่ยนสีตามสถานะ คลิกขวามีเมนู

### ยังไม่ทำ (Non-goals ช่วงแรก)
- ไม่มีระบบบัญชีผู้ใช้ ไม่มี cloud ไม่มี analytics
- ไม่วินิจฉัยโรค (เป็นตัวช่วยเตือนเท่านั้น)
- ไม่ทำแอปมือถือ

---

## 2. กฎเหล็ก (Privacy) — ห้ามละเมิด

1. **ห้ามบันทึกภาพหรือวิดีโอลงดิสก์** ประมวลผลเฟรมแล้วทิ้งทันที
2. **ห้ามมี network call ใด ๆ ตอนรันแอป** (ไม่มี telemetry ไม่มี update check ไม่มีการโหลดโมเดลตอนรัน)
3. **ไฟล์โมเดล `.task` ต้องอยู่ในโฟลเดอร์ `models/`** ของโปรเจกต์ (โหลดครั้งเดียวตอน dev ด้วย script แยก)
4. เก็บแค่ **ตัวเลข** (มุม สถานะ เวลา) ลง SQLite ในโฟลเดอร์ข้อมูลของผู้ใช้
5. มีปุ่ม **Pause** ที่ปิดกล้องจริง (release device) ไม่ใช่แค่หยุดประมวลผล
6. หน้าต่าง debug ที่แสดงภาพจากกล้อง เปิดได้เฉพาะตอนผู้ใช้กดเองเท่านั้น

---

## 3. Tech stack

| ส่วน | เลือกใช้ | License | หมายเหตุ |
|---|---|---|---|
| ภาษา | Python 3.11+ | — | |
| จัดการ env | `uv` | MIT/Apache | `uv init`, `uv add ...` |
| จับท่าทาง | `mediapipe` (Tasks API) | Apache 2.0 | ใช้ `FaceLandmarker` + `PoseLandmarker` (lite) |
| กล้อง | `opencv-contrib-python` | Apache 2.0 | มากับ mediapipe อยู่แล้ว ห้ามลง `opencv-python` ซ้อน (ชน `cv2`) |
| Tray | `pystray` + `Pillow` | LGPL / HPND | import ใช้ได้ ไม่บังคับเปิดซอร์ส |
| แจ้งเตือน | `desktop-notifier` | MIT | native notification ทั้ง Win/mac/Linux |
| Config | TOML (`tomllib` + `tomli-w`) | — | |
| เก็บข้อมูล | `sqlite3` (stdlib) | — | |
| ทดสอบ / lint | `pytest`, `ruff` | MIT | |
| แพ็กแอป (Phase 4) | `pyinstaller` | GPL + exception | ใช้แพ็กได้ ไม่กระทบ license ของเรา |

> ❌ ห้ามใช้ `PyQt6` (GPL) ถ้าอนาคตต้องการ UI เต็มรูปแบบให้ใช้ `PySide6` (LGPL)
> ❌ ห้ามก๊อปโค้ดจาก repo ที่เป็น AGPL/GPL หรือไม่มีไฟล์ LICENSE

License ของโปรเจกต์: **MIT**

---

## 4. โครงสร้างโปรเจกต์

```
meerkat-posture/
├── PLAN.md
├── README.md
├── LICENSE                     # MIT
├── THIRD_PARTY_NOTICES.md
├── pyproject.toml
├── models/                     # face_landmarker.task, pose_landmarker_lite.task
├── scripts/
│   └── download_models.py      # รันครั้งเดียวตอน dev
├── src/meerkat/
│   ├── __main__.py             # entry: python -m meerkat
│   ├── app.py                  # ประกอบทุกส่วน, main loop / threads
│   ├── camera.py               # เปิด/ปิดกล้อง, เลือก device, sample rate
│   ├── detector.py             # เรียก MediaPipe → คืน Landmarks (ไม่มี logic ท่าทาง)
│   ├── metrics.py              # pure functions: landmarks → PostureMetrics
│   ├── calibration.py          # บันทึก/โหลด baseline หลายโซน
│   ├── rules.py                # pure: metrics + เวลา → สถานะ + events (state machine)
│   ├── sitting.py              # ตัวนับเวลานั่ง / ตรวจการลุก
│   ├── notifier.py             # แจ้งเตือน + cooldown
│   ├── tray.py                 # ไอคอน + เมนู
│   ├── storage.py              # SQLite: เก็บ metrics สรุป, events
│   ├── config.py               # โหลด/บันทึก config.toml + ค่า default
│   └── debug_view.py           # หน้าต่าง OpenCV แสดงจุด+ตัวเลข (เปิดเมื่อสั่งเท่านั้น)
├── assets/icons/               # meerkat_green/yellow/red/sleep.png
└── tests/
    ├── test_metrics.py
    ├── test_rules.py
    ├── test_sitting.py
    └── fixtures/               # landmark ปลอม (ตัวเลข) ไว้ทดสอบ
```

**หลักการ:** `metrics.py`, `rules.py`, `sitting.py` เป็น **pure function ไม่แตะกล้องหรือ UI** เพื่อให้เขียน unit test ด้วยตัวเลขปลอมได้

---

## 5. สถาปัตยกรรม

```
[Camera thread] --frame--> [Detector] --landmarks--> [Metrics]
                                                         |
                                                         v
[Calibration baselines] ------------------------> [Rules engine] --events--> [Notifier]
                                                         |                    [Tray icon]
                                                         v
                                                     [Storage]
```

- ประมวลผล **2–5 fps** ก็พอ (ไม่ต้อง 30 fps เพื่อประหยัด CPU/แบต) ตั้งค่าได้ใน config
- ใช้ **ค่าเฉลี่ยเคลื่อนที่ (smoothing) 1–2 วินาที** ก่อนส่งเข้า rules เพื่อกันสัญญาณกระตุก
- Tray ต้องรันใน main thread (ข้อจำกัดของ macOS) กล้องและ detector อยู่ใน worker thread

---

## 6. ค่าที่วัด (metrics.py)

| Metric | ได้จาก | ใช้ตรวจ |
|---|---|---|
| `head_yaw` | Face Landmarker → `facial_transformation_matrixes` → แปลงเป็น Euler | หันซ้าย/ขวา |
| `head_pitch` | เหมือนข้างบน | ก้ม/เงย |
| `head_roll` | เหมือนข้างบน | เอียงคอ |
| `face_scale` | ระยะระหว่างหางตาซ้าย-ขวา (normalized) | โน้มตัวเข้าหาจอ / คอยื่น (หน้าใหญ่ขึ้น) |
| `shoulder_tilt` | มุมเส้นไหล่ซ้าย-ขวา เทียบแนวนอน (Pose 11,12) | ไหล่เอียง / นั่งเอียง |
| `shoulder_width` | ระยะไหล่ซ้าย-ขวา เทียบ baseline | ตัวบิด (ไหล่แคบลงเมื่อบิด) |
| `neck_drop` | ระยะแนวตั้ง หู→ไหล่ เทียบ baseline | ห่อไหล่ / หลังค่อม / ไหลลงเก้าอี้ |
| `present` | เจอหน้าหรือไม่ | ตรวจว่าลุกไปแล้ว |

> ทุกค่าเปรียบเทียบกับ **baseline ที่ calibrate** ไม่ใช้ค่าดิบ เพราะตำแหน่งกล้องแต่ละคนไม่เหมือนกัน

---

## 7. Calibration หลายโซน

- ตอนเปิดครั้งแรก (หรือเลือกเมนู "Calibrate ใหม่"):
  1. "นั่งท่าดี มองจอหลัก" → เก็บค่าเฉลี่ย 3 วินาที → โซน `main`
  2. "มองจอที่สอง" → โซน `second` (ข้ามได้ถ้ามีจอเดียว)
  3. (ตัวเลือก) เพิ่มโซนอื่น เช่น `laptop` หรือ `notebook`
- ตอนรัน: หาโซนที่ **yaw/pitch ใกล้ที่สุด** แล้วคำนวณ delta จากโซนนั้น
- ถ้า delta อยู่ในระยะของโซนใดโซนหนึ่ง ถือว่าอยู่ในท่าปกติ

---

## 8. กฎการเตือน (rules.py) — ค่า default (แก้ได้ใน config)

อ้างอิงแนวคิดจาก ISO 11226: ประเมินท่าที่ค้างเกิน 4 วินาที โดยดูทั้งมุมและเวลา (ก้มหัว 0–25° ถือว่าดี, 25–85° ค้างได้แค่ช่วงสั้น, เกิน 85° ควรหลีกเลี่ยง)

| กฎ | เงื่อนไข (เทียบ baseline โซนใกล้สุด) | ค้างนานเกิน | สถานะ |
|---|---|---|---|
| ก้มหัว | pitch ลง > 15° | 30 วิ | 🟡 → 🔴 |
| เงยหัว | pitch ขึ้น > 10° | 30 วิ | 🟡 → 🔴 |
| หันนอกโซน | \|yaw\| > 15° จากทุกโซน | 20 วิ | 🟡 → 🔴 |
| เอียงคอ | \|roll\| > 10° | 30 วิ | 🟡 → 🔴 |
| โน้มเข้าจอ | face_scale > 1.15× | 45 วิ | 🟡 → 🔴 |
| ไหล่เอียง | \|shoulder_tilt\| > 7° | 60 วิ | 🟡 → 🔴 |
| ตัวบิด | shoulder_width < 0.85× | 60 วิ | 🟡 → 🔴 |
| ไหลลงเก้าอี้/ค่อม | neck_drop < 0.85× | 60 วิ | 🟡 → 🔴 |

**State machine ต่อกฎ:** `OK` → (เกินมุม) → `WARN` (เริ่มจับเวลา, ไอคอนเหลือง) → (ครบเวลา) → `ALERT` (แจ้งเตือน, ไอคอนแดง) → (กลับท่าดีต่อเนื่อง 3 วิ) → `OK`

**กันความน่ารำคาญ:**
- Cooldown ต่อกฎ: 5 นาที (กฎเดียวกันจะไม่เตือนซ้ำภายใน 5 นาที)
- Global cooldown: 60 วิ (ระหว่างการเตือนใด ๆ)
- Hysteresis: ต้องกลับมาต่ำกว่าเกณฑ์ 80% จึงนับว่ากลับท่าดี

**สรุปรายชั่วโมง (Phase 3):** ถ้าอยู่โซนข้าง (เช่น `second`) เกิน 60% ของชั่วโมง → แนะนำให้ย้ายจอหลัก

---

## 9. ตัวนับเวลานั่ง (sitting.py)

- เริ่มนับเมื่อ `present = true`
- ไม่เห็นหน้าต่อเนื่อง **≥ 60 วิ** ให้ถือว่าลุกแล้ว และรีเซ็ตตัวนับ
- ครบ **30 นาที** ให้เตือน "ลุกขึ้นยืน/เดิน 2–3 นาที" ถ้ายังไม่ลุก เตือนซ้ำทุก 10 นาที
- ปุ่ม "Snooze 10 นาที" ในแจ้งเตือน/เมนู (สำหรับช่วงประชุม)

---

## 10. Tray (tray.py)

ไอคอน: 🟢 ท่าดี / 🟡 เริ่มผิด / 🔴 ค้างผิดนาน / 💤 หยุดชั่วคราว (กล้องปิด)

เมนูคลิกขวา:
- สถานะ: "นั่งมาแล้ว 18 นาที"
- ⏸ หยุด 15 นาที / 30 นาที / 1 ชั่วโมง / จนกว่าจะกดเปิด
- 🎯 Calibrate ใหม่
- 🐞 เปิดหน้าต่าง debug
- 📊 สถิติวันนี้ (Phase 3)
- ⚙️ เปิดไฟล์ config
- ❌ ออก

---

## 11. แผนงานเป็น Phase

### Phase 0 — ตั้งโปรเจกต์ (½ วัน)
- [x] `uv init`, ตั้ง `pyproject.toml`, `src/` layout, entry `python -m meerkat`
- [x] เพิ่ม dependencies ตามข้อ 3
- [x] `scripts/download_models.py` โหลด `face_landmarker.task` และ `pose_landmarker_lite.task` ลง `models/`
- [x] `LICENSE` (MIT), `.gitignore`, `ruff` config, `pytest` รันได้
- [x] `git init` + commit แรก

### Phase 1 — ต้นแบบ: เห็นตัวเลข (1–2 วัน)
- [x] `camera.py`: เปิดกล้องตาม index ใน config, อ่านเฟรมตาม fps ที่กำหนด
- [x] `detector.py`: เรียก Face + Pose Landmarker (โหมด VIDEO)
- [x] `metrics.py`: คำนวณค่าทั้งหมดในข้อ 6 + smoothing
- [x] `debug_view.py`: หน้าต่างแสดงภาพ + จุด + ตัวเลข yaw/pitch/roll/tilt/scale แบบ real-time
- [x] `tests/test_metrics.py`: ทดสอบด้วย landmark ปลอม (เช่น หันขวา 30° ต้องได้ yaw ≈ 30)
- ✅ **เสร็จเมื่อ:** รัน `python -m meerkat --debug` แล้วขยับหัวเห็นตัวเลขเปลี่ยนตามจริง

### Phase 2 — MVP ใช้เองได้ (1–2 สัปดาห์)
- [x] `config.py`: ค่า default ทั้งหมดในข้อ 8–9, บันทึก/โหลด TOML
- [x] `calibration.py`: flow ข้อ 7 + เก็บลง config
- [x] `rules.py`: state machine + cooldown + hysteresis ตามข้อ 8
- [x] `tests/test_rules.py`: จำลอง timeline (ก้ม 31 วิ → ต้องเตือน 1 ครั้ง, ก้ม 29 วิ → ไม่เตือน, หันไปจอสอง 5 นาที → ไม่เตือน)
- [x] `sitting.py` + tests
- [x] `notifier.py`: แจ้งเตือน native + ข้อความมีบุคลิก Meerkat
- [x] `tray.py`: ไอคอน 4 สถานะ + เมนูข้อ 10 (ยกเว้นสถิติ)
- [x] Pause = release กล้องจริง
- [x] `app.py`: ประกอบทุกส่วน, ปิดแอปแล้วปล่อยกล้องเรียบร้อย
- ✅ **เสร็จเมื่อ:** เปิดทิ้งไว้ทำงานได้ทั้งวัน เตือนถูก ไม่รบกวนจนอยากปิด

### Phase 3 — จูนจากการใช้จริง (1–2 สัปดาห์, ทำคู่กับการใช้)
- [ ] `storage.py`: บันทึก metrics สรุปทุก 10 วิ + events ลง SQLite
- [ ] โหมด "บันทึก session เป็นตัวเลข" เพื่อ replay ในการทดสอบ (ไม่มีภาพ)
- [ ] สถิติวันนี้: เวลานั่งรวม, จำนวนครั้งที่ลุก, จำนวนเตือนแยกตามกฎ, % เวลาต่อโซน
- [ ] ปรับเกณฑ์ default จากข้อมูลจริง
- [ ] รองรับกล้องหลายตัว / เลือกกล้องจากเมนู
- [ ] รับมือแสงน้อย / หน้าไม่ชัด (ไม่เตือนถ้าความมั่นใจต่ำ)
- [ ] (ตัวเลือก) กล้องด้านข้างตัวที่สอง สำหรับวัดคอยื่นแบบ CVA

### Phase 4 — พร้อมแจกบน GitHub (1–3 สัปดาห์)
- [ ] README: ภาพหน้าจอ, วิธีติดตั้ง, **หัวข้อ Privacy อธิบายข้อ 2 ชัด ๆ**
- [ ] `THIRD_PARTY_NOTICES.md`: MediaPipe, OpenCV, pystray, desktop-notifier, โมเดล
- [ ] หน้าตั้งค่าแบบ GUI (พิจารณา PySide6)
- [ ] เริ่มอัตโนมัติตอนเปิดเครื่อง (ตัวเลือก)
- [ ] แพ็กด้วย PyInstaller: Windows `.exe`, macOS `.app`
- [ ] GitHub Actions: lint + test + build
- [ ] เช็กชื่อ `meerkat-posture` บน GitHub / PyPI ก่อน publish

---

## 12. ความเสี่ยงที่รู้อยู่แล้ว

| ความเสี่ยง | วิธีรับมือ |
|---|---|
| เตือนบ่อยจนน่ารำคาญ | cooldown + hysteresis + ปรับเกณฑ์จาก Phase 3 |
| กล้องหน้าวัดคอยื่นได้ไม่แม่น | ใช้ face_scale + neck_drop แทน, กล้องข้างเป็นตัวเลือก |
| แสงน้อย / ใส่แว่น / หน้าหลุดเฟรม | ข้ามเฟรมที่ confidence ต่ำ ไม่นับเป็นท่าผิด |
| กินแบต / CPU | 2–5 fps, ใช้ pose model ตัว lite |
| macOS ขอสิทธิ์กล้อง / tray ต้องอยู่ main thread | ออกแบบ thread ตามข้อ 5 ตั้งแต่แรก |
| ไฟล์แพ็กใหญ่ / ปัญหาต่าง OS | ทิ้งไว้ Phase 4, ใช้เองจาก source ก่อน |

---

## 13. หมายเหตุ

- ระบบนี้เป็นตัวช่วยเตือน ไม่ใช่เครื่องมือแพทย์ ถ้าปวดเรื้อรังควรพบนักกายภาพบำบัด
- ศึกษาไอเดียจากโปรเจกต์อื่นได้ (เช่น BatesPosture เวอร์ชัน MIT) แต่ให้เขียนโค้ดเอง ถ้าก๊อปส่วนใดมาต้องใส่เครดิตใน `THIRD_PARTY_NOTICES.md`
