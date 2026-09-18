# Kang AI-AutoCut

**Local-first Agentic AI Video Production System**

**Sistem Produksi Video AI Agentic yang Mengutamakan Lokal**

**Languages:** [English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | Bahasa Indonesia | [Deutsch](README.de.md) | [Español](README.es.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3-3776AB)](README.md#installation)
[![FFmpeg](https://img.shields.io/badge/ffmpeg-required-007808)](README.md#installation)
[![Local-first](https://img.shields.io/badge/local--first-yes-4c1)](docs/decisions/ADR-0007-local-first.md)
[![Agent-oriented](https://img.shields.io/badge/agent--oriented-yes-8957e5)](README.md#use-with-an-ai-agent)
[![Tests](https://img.shields.io/badge/tests-1062%20passing-brightgreen)](README.md#installation)
[![macOS](https://img.shields.io/badge/macOS-tested-000000)](README.md#installation)
[![Baseline](https://img.shields.io/badge/baseline-pre--third--SKU-orange)](README.md#frozen-baseline)

*Badge ini bersifat statis dan menggambarkan baseline beku. Repositori ini tidak
menjalankan workflow CI, dan angka pada badge bukan status langsung.*

Kang AI-AutoCut adalah sistem produksi video yang berorientasi Agent, bukan skrip
penyambungan FFmpeg. Sistem ini menerima rekaman mentah yang diotorisasi dan tujuan
kreatif yang dinyatakan, lalu menjalankan pekerjaan melalui **delapan tahap
produksi** — pemahaman materi, kecerdasan penyuntingan, perencanaan naratif,
konstruksi timeline, penyelesaian gambar, tipografi, audio, mastering, review dan
perbaikan — dengan **persetujuan manusia sebagai gerbang yang eksplisit**.

Sistem ini berjalan di komputer Anda sendiri. Jalur kendali produksi dan pemrosesan
media mengutamakan lokal (local-first); penyedia AI eksternal hanya boleh menerima
input yang secara eksplisit diperlukan untuk tugas kecerdasan atau generasi yang
telah disetujui. Setiap keputusan kreatif dicatat, dan sistem menolak melaporkan
keberhasilan yang tidak dapat diukurnya.

> **Mengutamakan komersial, dapat diperluas sejak desain.** Iklan komersial adalah
> workflow pertama yang tervalidasi produksi. Arsitekturnya dibangun untuk
> berkembang ke workflow kreator dan media yang lebih luas.

```
Raw Footage
    ↓
Understand  →  Plan  →  Edit
    ↓
Picture  ·  Typography  ·  Audio
    ↓
Assemble & Master
    ↓
Review  →  Repair  →  Human Approval
    ↓
Final Video
```

---

## Mengapa Kang AI-AutoCut

Sebagian besar alat video AI menghasilkan **satu video, sekali saja**, di dalam
jendela chat. Menjalankannya ulang akan memberi Anda video yang berbeda, dan tidak
ada bagian dari prosesnya yang dapat diperiksa.

Kang AI-AutoCut memperlakukan produksi video sebagai **pipeline rekayasa**:

| Output video AI biasa | Kang AI-AutoCut |
|---|---|
| Hasil sekali pakai, sulit diulang | Workflow yang dapat dipakai ulang dan dijalankan kembali |
| Keputusan hanya hidup di log chat | Setiap keputusan menjadi artefak yang tercatat |
| Kegagalan berarti mulai dari awal | Job dilanjutkan dari tahap tempat proses berhenti |
| "Sepertinya sudah selesai" adalah satu-satunya pemeriksaan | Output diukur: jumlah frame, black frame, freeze, loudness, true peak, hash master |
| Model dapat melewati sebuah langkah tanpa terdeteksi | Sebuah tahap **tidak dapat lulus tanpa menyebutkan kapabilitas yang dijalankannya** |
| Penilaian manusia tidak terlihat | Input manusia terjadi pada gerbang yang bernama, dan dicatat |
| Rekaman Anda diunggah ke penyedia | Pemrosesan mengutamakan lokal; penyedia hanya menerima input yang dibutuhkan sebuah tugas |

---

## Apa yang Dapat Anda Bangun

**Saat ini tervalidasi produksi:**

- **Iklan komersial dan video produk e-commerce** — workflow pertama yang
  dijalankan dari awal sampai akhir, termasuk verifikasi delivery master.
- **Konten produk pendek untuk media sosial** — editan komersial vertikal
  berdurasi pendek, menggunakan delapan tahap yang sama.

**Arah yang dirancang untuk diperluas oleh arsitektur ini** — *belum tervalidasi
produksi*:

- video kreator dan self-media
- konten demonstrasi produk dan explainer
- konten brand dan kampanye
- workflow produksi video terstruktur lainnya

Saat ini sistem ini mengutamakan komersial. Tidak ada klaim di sini bahwa semua
kategori video sudah didukung, dan belum ada kerangka content-mode.

---

## Cara Kerjanya

### Yang Anda lakukan

1. **Tambahkan rekaman mentah** — arahkan sistem ke sebuah direktori video sumber.
2. **Nyatakan tujuannya** — produk, platform, bahasa, durasi target, serta apa yang
   boleh dan tidak boleh diklaim oleh video.
3. **Biarkan Agent menjalankan pipeline** — Agent menelusuri tahap demi tahap dan
   berhenti ketika membutuhkan Anda.
4. **Jawab gerbang-gerbangnya** — setujui copy, sediakan artefak yang belum ada,
   atau ambil keputusan kreatif.
5. **Setujui video akhir** — manusia yang disebutkan namanya melepas master. Pelepasan
   itu adalah keputusan yang terpisah dari review, dan menyebutkan master persis yang
   disetujuinya.

### Yang dilakukan sistem

Jalur kendali produksi menjalankan **delapan tahap semantik**:

| # | Tahap | Apa yang terjadi |
|---|---|---|
| 1 | **PREPARE** | Inventaris sumber dengan digest per file yang tidak dapat diubah |
| 2 | **UNDERSTAND SHOTS** | Media dianalisis; timestamp hasil pengukuran dipetakan ke grid analisis CFR untuk menemukan segmen visual yang nyata |
| 3 | **PLAN THE EDIT** | Rentang timeline divalidasi terhadap aksi yang dapat diamati — potongan yang melewatkan onset atau hasilnya akan ditolak |
| 4 | **FINISH THE PICTURE** | Rentang sumber diekstraksi melalui invariant timebase, diukur, lalu keputusan KEEP / REVIEW / CORRECT diambil per shot |
| 5 | **PLAN THE WORDS** | Cakupan narasi diperiksa **sebelum** pekerjaan voice berbayar apa pun; setelah itu copy layar dirender |
| 6 | **BUILD THE AUDIO** | FIT / SYNC / RHYTHM dinilai secara terpisah; lalu mix dibangun dan **diukur** |
| 7 | **ASSEMBLE & MASTER** | Delivery master dihasilkan, lalu diverifikasi terhadap file itu sendiri |
| 8 | **REVIEW & REPAIR** | Seluruh dimensi review dinilai; verdict diturunkan; gerbang rilis manusia |

### Bagaimana kedua tampilan ini dipetakan

```
USER VIEW                          SYSTEM VIEW (8 stages)
─────────────────────────────      ──────────────────────────────────────
1  add raw footage            →    PREPARE
2  state the goal             →    (job manifest + brief)
3  understand the material    →    UNDERSTAND SHOTS
4  build the editing strategy →    PLAN THE EDIT
5  construct the timeline     →    PLAN THE EDIT
6  finish the picture         →    FINISH THE PICTURE
7  titles / copy / typography →    PLAN THE WORDS
8  voice / music / audio      →    BUILD THE AUDIO
9  assemble and master        →    ASSEMBLE & MASTER
10 review and repair          →    REVIEW & REPAIR
11 human approval             →    REVIEW & REPAIR (human release gate)
12 final video                →    delivered master
```

### Tahap berhenti dengan sengaja

Ketika input yang dibutuhkan tidak ada, proses **berhenti dan menyebutkan siapa yang
harus bertindak**:

```
   Stage ──▶ [ PRODUCER GATE ] ──▶ Stage
                 │
                 ├─ which artifact is missing
                 ├─ which producer is responsible (AUTO / CODEX / HUMAN / ADAPTER)
                 ├─ the input and output contract
                 ├─ the procedure to follow
                 ├─ the evidence required
                 └─ what must become true to resume
```

**Sebuah gerbang bukanlah kegagalan.** Gerbang adalah sistem yang menolak mengarang
keputusan kreatif, atau mengklaim pekerjaan yang tidak dilakukannya. Sebagian tahap
bersifat otomatis; sebagian lain memang memerlukan Agent, adapter penyedia, atau
manusia. Frasa "generate or prepare" ("hasilkan atau siapkan"), "Agent supplies"
("Agent menyediakan"), dan "job-authored when required" ("ditulis per job saat
diperlukan") digunakan secara sengaja di seluruh README ini.

---

## Kapabilitas Saat Ini

### Tersedia dan terverifikasi saat ini

| Kapabilitas | Catatan |
|---|---|
| Ingesti sumber dan inventaris yang tidak dapat diubah | SHA-256 per file, diverifikasi ulang sebelum digunakan |
| Pemahaman media yang aman terhadap VFR | timestamp hasil pengukuran dipetakan ke grid analisis CFR |
| Segmentasi visual | berjalan pada grid yang benar-benar didekode oleh engine |
| Validasi rentang timeline | menolak potongan yang melewatkan aksi yang dapat diamati |
| Ekstraksi rentang sumber | setiap rentang diturunkan dari timestamp yang diukur |
| Eksekusi gambar | menghasilkan artefak video nyata, diukur ulang setelahnya |
| Cakupan narasi | berjalan sebelum generasi voice berbayar apa pun |
| Rendering tipografi | output nyata dari layout dan font milik job itu sendiri |
| Mixing dan mastering audio | mix nyata, dengan loudness, true peak, dan clipping yang terukur |
| Pengemasan dan master akhir | `final/master.mp4` plus QA teknis yang terukur |
| Kontrak review dan verdict rilis | setiap dimensi dinilai satu kali; verdict diturunkan, bukan diklaim |
| Perencanaan perbaikan yang tertarget | cakupannya terkunci pada layer yang terdampak |
| Gerbang rilis manusia | keputusan tersendiri yang menyebutkan master yang disetujuinya |
| Intervention ledger | ditulis otomatis setiap kali sebuah gerbang menghentikan proses |
| Resume dan invalidasi | dilanjutkan pada tahap pertama yang belum selesai; invalidasi sebuah tahap membuka kembali seluruh tahap hilir |
| Validasi integritas master | digest dihitung ulang; master yang dihapus atau diubah akan gagal verifikasi |

### Bergerbang / ditulis per job

Kapabilitas ini berjalan, tetapi artefak yang dikonsumsinya disediakan per job —
oleh Agent, adapter, atau manusia:

| Kapabilitas | Apa yang masih harus disediakan |
|---|---|
| Pengukuran gambar hanya-baca | tidak ada alat pengukuran yang disertakan di repositori ini |
| Perlindungan keaslian produk | sama; pemeriksaan toleransinya belum pernah dijalankan pada data nyata |
| Keputusan KEEP / REVIEW / CORRECT | keputusannya berjalan; tidak ada apa pun di sini yang menindaklanjuti sebuah `CORRECT` |
| Verifikasi program audio (FIT / SYNC / RHYTHM) | penempatan voice yang dikonsumsinya |
| Generasi voice / musik | disediakan oleh adapter penyedia; **tidak dibangun di dalam sistem** |

### Direncanakan / dapat diperluas

Belum diimplementasikan, dan tidak diklaim: reviewer komersial otomatis, compiler
backend generik, registry artefak, antrean job, runner satu perintah tanpa
pengawasan, dan workflow content-mode yang lebih luas.

---

## Penggunaan dengan AI Agent

Kang AI-AutoCut dirancang untuk **dioperasikan dengan Agent** — model yang dapat
bertindak pada filesystem dan shell Anda, bukan model yang hanya bisa chat.

Sistem ini **tidak terikat pada satu produk Agent tertentu**. Kompatibilitasnya
berbasis kapabilitas:

| Agent perlu mampu… | Alasan |
|---|---|
| membaca file repositori | mengikuti `README.md`, `PROJECT_IDENTITY.md`, `AGENTS.md` |
| menjalankan perintah shell | FFmpeg, FFprobe, Python, test suite |
| membaca dan menulis file lokal | state job, artefak, staging media |
| menjalankan workflow Python dan FFmpeg | setiap tahap bersifat lokal dan deterministik |
| memahami artefak JSON terstruktur | job, review, evidence, manifest |
| **berhenti pada Producer Gate** (gerbang produser: sistem sengaja berhenti sampai produser yang dideklarasikan menyediakan atau menyetujui sebuah artefak) | dan bertanya kepada Anda, bukan menebak |
| menghormati batas-batas repositori | media di luar Git, tanpa secret, tanpa path yang terikat pada mesin |

Contoh Agent yang mumpuni antara lain Codex, DeepSeek Harness, Claude Code, dan
Agent coding atau computer-use lainnya. **Semuanya adalah contoh, bukan persyaratan
dan bukan integrasi yang secara resmi dianjurkan.**

**Model yang hanya bisa chat tidak dapat mengoperasikan sistem ini.** Tanpa akses
filesystem dan shell, model tersebut tidak dapat menjalankan pipeline; ia hanya bisa
membicarakannya.

### Tata kelola internal vs kompatibilitas publik

Keduanya adalah hal yang berbeda, dan keduanya benar:

- **Secara internal**, workflow produksi yang tervalidasi menggunakan **Codex
  sebagai Supervisor tingkat teratas.** Otoritas kreatif berada di sana, dan sistem
  dibangun agar tidak ada komponen deterministik yang memutuskan apa yang harus
  disampaikan sebuah video.
- **Secara publik**, repositori ini berupaya tetap **netral terhadap Agent
  (Agent-agnostic)** sejauh arsitekturnya memungkinkan. Tidak ada bagian di jalur
  kendali yang terkunci mati pada Agent milik satu vendor tertentu.

---

## Mulai Cepat dengan Agent

Berikan URL repositori dan prompt seperti berikut kepada Agent coding yang mumpuni:

```text
Instal Kang AI-AutoCut di komputer ini menggunakan instruksi di repositori.

Repositori: https://github.com/KanG-ciyuan/AI-AutoCut

Sebelum mengubah apa pun:
1. Baca README.md, PROJECT_IDENTITY.md dan AGENTS.md.
2. Periksa lingkungan: Python, FFmpeg/FFprobe, dan paket Python yang benar-benar
   diimpor oleh kode.
3. Laporkan apa yang belum ada. Jangan memasang apa pun yang belum saya setujui.

Selanjutnya:
4. Konfigurasikan workspace lokal dan media root hanya menggunakan peran logis dan
   environment variable. Simpan media di luar Git.
5. Jangan pernah menulis API key, token, atau kredensial ke file yang dilacak, log,
   atau commit mana pun.
6. Jalankan self-test repositori sebelum membuat job video pertama saya.

Saat kita memulai sebuah job:
7. Jalankan jalur kendali produksi dan berhenti di setiap Producer Gate.
8. Tanyakan kepada saya ketika sebuah gerbang memerlukan keputusan manusia atau
   persetujuan kreatif.
9. Jangan mengarang copy, arahan seni, atau klaim atas nama saya.
```

**Apa yang masih harus dilakukan Agent secara manual.** Instalasi *tidak*
sepenuhnya otomatis saat ini: tidak ada installer, tidak ada manifest pengemasan,
dan tidak ada lockfile dependensi yang dideklarasikan. Agent harus memeriksa
lingkungan, memasang prasyarat yang Anda setujui, dan mengonfigurasi path lokal.
README di bawah ini mencantumkan secara persis apa yang terverifikasi, dan repositori
ini tidak memuat `pyproject.toml` atau `requirements.txt` — itu adalah celah
dokumentasi yang diketahui, bukan langkah tersembunyi.

---

## Instalasi

### Prasyarat yang terverifikasi

| Kebutuhan | Status |
|---|---|
| **Python 3** | terverifikasi pada 3.11.15. Repositori ini tidak mendeklarasikan versi minimum — anggap itu sebagai celah. |
| **FFmpeg dan FFprobe** | wajib. Terverifikasi pada ffmpeg/ffprobe 9.0.1. |
| **`numpy`** | dibutuhkan oleh modul pemahaman media |
| **`Pillow`** | dibutuhkan oleh adapter eksekusi tipografi |
| **macOS** | terverifikasi pada macOS arm64. Windows dan Linux **tidak** terverifikasi. |

Tidak ada `pyproject.toml`, `setup.py`, atau `requirements.txt`, sehingga tidak ada
pin versi yang diklaim di sini. Bacalah bagian import alih-alih mempercayai lockfile
yang tidak ada.

### Penyiapan

```sh
git clone https://github.com/KanG-ciyuan/AI-AutoCut.git
cd AI-AutoCut

# Local configuration: resolves environment variables, never machine paths
cp config/examples/autocut.env.example .env.local
# edit .env.local: set AUTOCUT_MEDIA_ROOT and AUTOCUT_WORKSPACE
```

### Verifikasi instalasi

```sh
# Full offline regression — no network, no media required
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests

# End-to-end execution proof — builds its own media, produces a real master
python3 scripts/run_pre_exam_proof.py --job-root /tmp/pre-exam-proof
```

Proof ini sengaja dibuat dua fase: ia berhenti di gerbang rilis manusia, menulis
rilis yang menyebutkan master yang **terverifikasi**, lalu dilanjutkan sampai
selesai. Proof akan gagal jika master dihapus atau diubah.

### Job pertama Anda

```sh
# 1. Initialize a job (generic: any product, any source count)
python3 -m src.ai_autocut.job_foundation \
    --job-id my-first-job \
    --product-name 'My Product' \
    --source-root /path/to/footage \
    --workspace /path/to/job-workspace

# 2. Run the production control path
python3 -m src.ai_autocut.fast_path --job-root /path/to/job-workspace
```

Sistem akan berhenti pada Producer Gate pertama dan memberi tahu Anda apa yang
dibutuhkan selanjutnya.

Instruksi lengkap: [`docs/audit/execution-runbook.md`](docs/audit/execution-runbook.md).

---

## Kompatibilitas Agent & LLM

Ada empat lapisan berbeda yang mudah tertukar. Sistem ini sengaja memisahkannya:

| Lapisan | Apa itu | Dalam proyek ini |
|---|---|---|
| **LLM** | model penalaran | dapat ditukar, pada bagian yang memang menggunakan model |
| **Agent** | model **plus tools** yang dapat bertindak pada repositori ini | wajib untuk mengoperasikan sistem |
| **Provider** | layanan eksternal opsional untuk generasi atau kecerdasan | dapat dipasang (pluggable); **tidak dibangun di dalam sistem** |
| **Execution engine** | pipeline Python/FFmpeg lokal yang deterministik | satu-satunya yang dipercaya untuk melaporkan bahwa sebuah langkah berhasil |

**Tidak ada vendor lock-in sejak desainnya.** Jalur kendali memanggil modul lokal
yang deterministik. Ketika sebuah model atau penyedia terlibat, ia adalah produser
yang menyediakan artefak melalui kontrak yang dideklarasikan — sehingga mengganti
model atau penyedia tidak mengubah pipeline.

**Namun kompatibilitas adalah pertanyaan tentang kapabilitas, bukan pertanyaan
tentang merek.** Model yang tidak dapat membaca dan menulis file, menjalankan
perintah shell, atau menghormati sebuah gerbang tidak dapat mengoperasikan sistem
ini, seberapa pun mumpuninya kemampuan bernalarnya.

---

## Arsitektur Audio & Penyedia AI

Repositori saat ini melakukan **mixing dan mastering lokal** atas aset audio yang
disediakan oleh job. Sistem ini sengaja **tidak** memanggil penyedia voice, musik,
atau sound effect. Sintesis audio tidak diimplementasikan di sini.

```
External Audio Provider   (future Adapter layer — NOT built in)
        ↓
  generated VO / BGM / SFX assets
        ↓
  job-local audio assets
        ↓
  Audio Program  →  local Mix  →  local Master
                     (measured: loudness, true peak, clipping)
```

**Yang ada saat ini:** tahap `BUILD THE AUDIO` mengonsumsi aset audio lokal milik
job, memadukannya dengan FFmpeg terhadap target milik job itu sendiri, dan mengukur
hasilnya. Sistem menolak mix yang sample peak-nya mencapai full scale.

**Yang tidak ada:** integrasi penyedia apa pun yang dibangun di dalam sistem. Tidak
ada pembuatan voice sekali klik, dan repositori ini tidak memuat provider client.

**Konteks historis, dengan label yang akurat.** Voice-over pernah dihasilkan melalui
**MiniMax `speech-2.8-hd`** pada pekerjaan produksi tervalidasi sebelumnya, dan
sebuah manifest job pendahulu mencatat **Doubao Seed Audio 1.0**. Keduanya adalah
**eksperimen yang dievaluasi secara historis**, yang terdokumentasi di
[`docs/providers/audio-provider.md`](docs/providers/audio-provider.md) — bukan
integrasi produksi yang dibangun di dalam sistem saat ini. Temuan keduanya membentuk
kebijakan audio; client keduanya bukan bagian dari repositori ini.

Tidak ada nilai key, token, atau kredensial yang muncul di mana pun dalam repositori
ini. Kredensial hanya dirujuk melalui nama environment variable.

---

## Nilai Komersial & Produksi

Nilainya terletak pada arsitekturnya, bukan pada janji tentang hasil akhir:

- **Workflow yang dapat dipakai ulang, bukan output sekali pakai.** Jalankan proses
  produksi yang sama untuk produk berikutnya alih-alih memulai percakapan baru.
- **Produksi yang dapat diulang.** Tahap, kontrak, dan gerbang yang sama berlaku
  untuk setiap job, sehingga pengetahuan proses terakumulasi alih-alih menguap.
- **Keputusan kreatif yang dapat diaudit.** Setiap pilihan adalah artefak dengan
  evidence, sehingga sebuah review dapat menanyakan *mengapa*, bukan hanya *apa*.
- **Job yang dapat dilanjutkan.** Job yang berhenti karena sebuah gerbang atau
  kegagalan dilanjutkan dari tahap tempat ia berhenti, bukan dari awal.
- **Eksekusi yang deterministik.** Rendering, ekstraksi, dan pengukuran bersifat
  lokal dan dapat direproduksi; klaim sebuah model tidak pernah menjadi evidence.
- **Materi sumber dapat dipakai ulang.** Rekaman yang kuat dapat melayani beberapa
  varian tanpa pengambilan gambar ulang.
- **Review dan perbaikan yang terstruktur.** Perbaikan diarahkan pada layer yang
  terdampak, bukan regenerasi penuh — sehingga hasil editan yang sudah disetujui
  tidak diganti secara diam-diam.
- **Validasi output yang terukur.** Jumlah frame, black frame, frozen frame,
  loudness, true peak, dan digest master diukur dari filenya.
- **Intervensi manusia terlihat.** Sistem mencatat kapan sebuah gerbang terbuka,
  siapa yang bertindak, dan kapan gerbang itu selesai.
- **Kepemilikan media tetap lokal.** Media sumber tidak otomatis diunggah ke
  pipeline cloud; jalur kendali dan pemrosesan media tetap di komputer Anda, dan
  penyedia eksternal yang disetujui hanya menerima input yang secara eksplisit
  dibutuhkan oleh sebuah tugas.
- **Fleksibilitas penyedia.** Generasi berada di balik sebuah batas, sehingga
  pilihan penyedia dapat diganti.

Yang **tidak** diklaim oleh hal di atas: kualitas yang terjamin, hasil konversi atau
pendapatan yang terjamin, atau pengurangan waktu penyuntingan yang terjamin. Semua
itu tidak dibuktikan oleh apa pun di repositori ini.

---

## Arsitektur

| Dokumen | Isi |
|---|---|
| [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md) | model interaksi, jalur kendali produksi, kematangan |
| [`docs/architecture/supervisor-authority.md`](docs/architecture/supervisor-authority.md) | batas kewenangan Codex Supervisor |
| [`docs/architecture/backend-neutral-timeline.md`](docs/architecture/backend-neutral-timeline.md) | satu timeline, tiga backend |
| [`docs/architecture/operations.md`](docs/architecture/operations.md) | peran path, staging ASCII, aturan verifikasi |
| [`docs/contracts/`](docs/contracts/) | kontrak yang dibekukan |
| [`docs/policies/`](docs/policies/) | kebijakan penyuntingan, shot, tipografi, audio, dan review |
| [`docs/decisions/`](docs/decisions/) | architecture decision record |
| [`docs/audit/production-chain-manifest.md`](docs/audit/production-chain-manifest.md) | pengkabelan dan kesiapan per kapabilitas |
| [`docs/audit/execution-runbook.md`](docs/audit/execution-runbook.md) | cara menjalankan setiap batas |
| [`docs/audit/gate-g0-history.md`](docs/audit/gate-g0-history.md) | bagaimana baseline beku ini dicapai |

### Tata letak repositori

```
src/ai_autocut/          production code
  fast_path.py             the eight-stage control path
  producer_registry.py     every required artifact and its producer
  execution_contracts.py   the four execution boundaries
  execution_adapters.py    job-scoped picture / typography / audio / packaging
  timebase_adapter.py      the source-timestamp invariant
  media_probe.py           measured facts about a real media file
  ...                      contracts, policies, validators

tests/                   offline regression suite
schemas/                 frozen contracts and the Gold manifest
docs/                    architecture, contracts, policies, decisions, audits
scripts/                 the execution proof and the local-env wrapper
examples/                example job shape
config/examples/         configuration template
```

---

## Desain yang Mengutamakan Lokal

Mengutamakan lokal (local-first) adalah persyaratan, bukan keadaan sementara. Jalur
kendali produksi dan seluruh pemrosesan media berjalan di mesin lokal, menggunakan
Python, FFmpeg/FFprobe dan filesystem lokal, dengan orkestrasi yang deterministik.
API AI eksternal yang disetujui boleh digunakan untuk tugas kecerdasan atau generasi
tertentu; API tersebut tidak pernah menjadi jalur kendali. Infrastruktur cloud —
object storage, platform server, worker terdistribusi, dashboard, akun pengguna —
sengaja tidak ada. Lihat
[ADR-0007](docs/decisions/ADR-0007-local-first.md).

Tidak ada absolute path yang terikat pada mesin tertentu di dalam repositori ini.
Setiap lokasi runtime adalah peran logis yang diselesaikan dari sebuah environment
variable; lihat [`docs/architecture/operations.md`](docs/architecture/operations.md)
dan [`config/examples/autocut.env.example`](config/examples/autocut.env.example).

---

## Status Saat Ini

| | |
|---|---|
| Baseline beku | `pre-third-sku-blind-v1` → `b65a73b53040bd1ff5defe25e624a28f623b6847` |
| Status pembekuan | `CLOSED_AND_FROZEN` |
| Validitas ujian | `PASS_WITH_EXPLICIT_PRODUCER_GATES` |
| Fase produksi berikutnya yang direncanakan | Uji blind Third-SKU — **belum dimulai** |

Sebuah **jalur kendali produksi bergerbang** yang berfungsi sudah ada dan telah
menghasilkan delivery master yang nyata dan diverifikasi secara independen. Sistem
ini bukan editor sekali klik tanpa pengawasan, dan tidak mengklaim demikian.

---

## Batasan yang Diketahui

- **Bukan editor satu perintah tanpa pengawasan.** Producer Gate menghentikan proses
  secara sengaja, dan sebagian memerlukan manusia atau Agent.
- **Tidak ada reviewer komersial otomatis.** Kontrak review mencatat sebuah
  penilaian; kontrak itu tidak menghasilkan penilaian tersebut.
- **Pengukuran gambar dan perlindungan produk ditulis per job.** Tidak ada alat
  pengukuran yang disertakan di sini, dan pemeriksaan toleransi perlindungan belum
  pernah dijalankan pada data nyata — gerbangnya telah terbukti menolak, bukan
  mengevaluasi.
- **Cabang gambar `CORRECT` belum pernah aktif** dalam sebuah proses produksi.
- **Tidak ada penyedia audio yang dibangun di dalam sistem.** Sintesis tidak
  diimplementasikan; pipeline mengonsumsi aset lokal milik job.
- **Tipografi membuktikan eksekusi, bukan arahan seni.** Tidak ada perencana
  hierarki copy layar dan tidak ada validasi penghalangan produk; sebuah job
  menyediakan layout-nya sendiri.
- **Proof eksekusi menggunakan audio lokal yang dihasilkan.** Proof itu membuktikan
  jalur mixing dan mastering, bukan penampilan voice yang nyata.
- **Tidak ada registry artefak dan tidak ada antrean job.** Data staging berukuran
  besar dibersihkan secara manual.
- **Tidak ada compiler backend generik.** `compile_for_backend` memunculkan exception
  untuk setiap backend; eksekusi terjadi melalui adapter yang berskop job sebagai
  gantinya.
- **Tidak ada manifest dependensi yang dideklarasikan.** Tidak ada `pyproject.toml`
  atau lockfile.
- **Terverifikasi hanya di macOS.** Windows dan Linux belum diuji.
- **Terlacak, belum terselesaikan:** segmentasi visual yang sadar run (run-aware)
  (C-01) dan verifikasi rentang terpilih secara otomatis ("needs vision").

---

## Peta Jalan

1. **Jalankan uji blind Third-SKU terhadap `pre-third-sku-blind-v1`.**
2. Ukur kualitas akhir, frekuensi Producer Gate, dan intervensi manusia.
3. Gunakan evidence dari blind run untuk menentukan kapabilitas job-authored mana
   yang tersisa dan layak diotomatiskan berikutnya.

Baseline beku ini dimaksudkan untuk diperiksa **dalam keadaan beku**: tidak ada
pekerjaan otomatisasi pra-ujian yang dijadwalkan sebelum blind run, sehingga ujian
mengukur sistem yang telah diterima, bukan sistem yang masih bergerak di bawahnya.

---

## Baseline Beku

```
tag             pre-third-sku-blind-v1
target commit   b65a73b53040bd1ff5defe25e624a28f623b6847
```

**Apa arti "beku" di sini:** tersedia baseline pra-ujian yang dapat direproduksi.
Commit yang diberi tag adalah sistem persis yang telah diaudit dan diterima, sehingga
uji berikutnya dapat dibandingkan dengan keadaan yang diketahui, bukan dengan ingatan
tentang keadaan itu.

**Apa yang tidak dimaksudkan:** bahwa produknya sudah selesai, bahwa setiap
kapabilitas sudah otomatis, atau bahwa sistemnya sudah lengkap untuk produksi.
Commit dokumentasi dapat masuk ke `main` setelah tag dibuat; tag itu sendiri tidak
berpindah.

---

## Lisensi

**Apache-2.0.** Teks lisensi lengkap ada di [LICENSE](LICENSE). Rasionalnya,
keputusan tanpa `NOTICE`, dan hal-hal yang masih terbuka untuk tahap berikutnya
tercatat di [LICENSE_DECISION_PENDING.md](LICENSE_DECISION_PENDING.md).

---

## Identitas Kanonik

- ID proyek: `ai-autocut`
- Branch default: `main`
- Root data runtime: peran logis `AUTOCUT_WORKSPACE`
- Media root: peran logis `AUTOCUT_MEDIA_ROOT`

Catatan identitas yang dapat dibaca mesin ada di
[PROJECT_IDENTITY.md](PROJECT_IDENTITY.md). Aturan masuk untuk Agent ada di
[AGENTS.md](AGENTS.md).
