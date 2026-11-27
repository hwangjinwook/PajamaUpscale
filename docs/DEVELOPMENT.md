# 🔍 파자마업스케일 (PajamaUpscale) — 개발 설명서

사용자용 안내는 저장소 첫 화면([README.md](../README.md))에 있어요. 이 문서는 파일 구성·빌드·시험·자세한 동작 설명이에요.

이미지를 **AI 로 2·3·4배 고화질 확대**하는 윈도우 프로그램이에요.
단순히 늘리는 게 아니라, AI(Real-ESRGAN)가 흐릿한 선과 질감을 새로 그려서 선명하게 키워요.
그래픽카드(Vulkan)로 돌아가서 빠르고, 인터넷이나 파이썬 없이 이 컴퓨터 안에서만 처리해요.

## 실행

- 빌드한 뒤 `dist\파자마업스케일\파자마업스케일.exe` 를 두 번 누르세요.
- 다른 컴퓨터로 옮길 때는 `dist\파자마업스케일\` 폴더를 **통째로** 옮기세요(`engine\` 폴더가 꼭 같이 있어야 해요).
- 파이썬으로 바로 켜려면: `pythonw PajamaUpscale.pyw` (Pillow·tkinterdnd2 필요)

## 사용법

1. 이미지나 폴더를 창에 **끌어다 놓거나** 「＋ 이미지 추가」·「📁 폴더 추가」(하위 폴더 포함)를 눌러요.
2. 아래에서 고르기
   | 칸 | 선택지 |
   |---|---|
   | 이미지 종류 | **사진·실사**(가장 선명·자연스러움) / **그림·애니·일러스트**(선이 또렷한 그림) / **빠르게**(많은 장을 빨리, 그림용) |
   | 배율 | 2배 · 3배 · 4배 (사진·그림 모델은 4배로 키운 뒤 고품질로 줄여서 2·3배를 만들어요) |
   | 형식 | PNG(투명 유지) · JPG(품질 95, 투명은 흰 바탕) · WebP |
   | 저장 위치 | 원본 옆 「업스케일」 폴더(기본) · 원본과 같은 폴더 · 직접 고르기 |
3. 「✨ 업스케일 시작」. 진행률이 장마다 보이고, 「■ 멈추기」로 언제든 멈출 수 있어요.
4. 끝나면
   - 결과를 **두 번 누르면** 열려요.
   - **오른쪽 클릭 → 「🔍 원본과 비교하기」**: 가운데 선을 끌어 원본(왼쪽)과 결과(오른쪽)를 비교해요. 휠로 확대, 오른쪽 버튼으로 끌어 이동.
   - 「📂 결과 폴더 열기」로 마지막 결과를 탐색기에서 보여 줘요.

### 알아 두면 좋은 것
- 결과 이름은 `원래이름_x4.png` 처럼 붙고, 같은 이름이 있으면 `(2)`, `(3)` 을 붙여 **원본이나 이전 결과를 덮어쓰지 않아요.**
- 휴대폰 사진의 회전 정보(EXIF)를 바로잡아 확대하고, 색 정보(ICC)·DPI 는 결과에 그대로 남겨요.
- 투명 배경 PNG 는 투명을 유지해요. 움직이는 GIF·WebP 는 첫 장만 확대해요.
- 결과가 약 4억 화소(예: 20000×20000)를 넘으면 메모리가 모자랄 수 있어 미리 막아요 — 배율을 낮춰 주세요.
- 그래픽카드 오류가 나면 「그래픽카드 대신 CPU 로」를 켜 보세요(많이 느려요).
- 설정은 exe 옆 `settings.json` 에 저장돼요.

## 구조

| 파일 | 하는 일 |
|---|---|
| `PajamaUpscale.pyw` | 화면(tkinter, 핑크 테마). 확대는 작업 스레드에서, 화면 갱신은 큐로만(끌어 놓기 콜백도 큐로) |
| `upscale_core.py` | 처리: 원본 → 회전 바로잡은 영어 이름 임시 PNG → AI 엔진 → 배율 맞춤·형식 저장. 진행률 읽기·취소 |
| `engine\` | Real-ESRGAN ncnn-vulkan 단독 실행판(`realesrgan-ncnn-vulkan.exe`, `vcomp140.dll`)과 모델 3종 |
| `tests\` | `test_core.py`(15개) + `fake_engine.py`(진짜 엔진 대신 단순 확대하는 시험용 엔진) |
| `build.cmd` | exe 만들기 → `dist\파자마업스케일\`(exe + engine 복사) |
| `make-icon.py` | 핑크 돋보기 아이콘(`icon.ico`, `icon.png`) 만들기 |

- 시험: `python -m unittest discover -s tests -v`
- 엔진에는 한글 경로를 넘기지 않아요(임시 폴더의 `in.png`/`out.png` 만) — 한글·특수문자 파일 이름도 안전해요.

### AI 엔진 넣기(engine 폴더가 없을 때)
1. https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.5.0 에서 `realesrgan-ncnn-vulkan-20220424-windows.zip`(45,474,481바이트) 받기
2. 압축 안의 `realesrgan-ncnn-vulkan.exe`, `vcomp140.dll`, `models\` 를 `engine\` 에 넣기

### 사용한 것과 라이선스
- **Real-ESRGAN** (xinntao) — BSD 3-Clause. ncnn-vulkan 판은 Tencent **ncnn**(BSD 3-Clause)과 nihui 의 realsr-ncnn-vulkan(MIT) 기반.
- **Pillow**(MIT-CMU), **tkinterdnd2**(MIT, tkdnd BSD), **PyInstaller**(GPL + 예외 — 만든 exe 배포는 자유).
- 라이선스 원문은 [THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt) 에 모았어요. 배포 zip 에도 같은 파일을 넣어요.
- `engine\` 폴더(실행 파일·모델, 약 51MB)는 저장소에 넣지 않아요(`.gitignore`). 위 「AI 엔진 넣기」대로 받거나, 배포 zip 의 `engine` 폴더를 쓰세요.

### 배포
1. `build.cmd` 로 `dist\파자마업스케일\` 를 만들어요.
2. 그 폴더에서 `settings.json` 을 뺀 `파자마업스케일.exe`·`engine\` 에 `README_사용설명서.txt`·`THIRD_PARTY_LICENSES.txt` 를 더해 `파자마업스케일\` 폴더째 `PajamaUpscale_vX.Y.Z.zip` 으로 묶어요.
3. `gh release create vX.Y.Z PajamaUpscale_vX.Y.Z.zip` 으로 올리고, README 와 노션 「버전 기록」 표를 같이 고쳐요.

## 버전 기록

| 버전 | 배포일 | 내용 |
|---|---|---|
| 1.0.0 | 2026-11-21 | 첫 버전. AI 확대(사진·그림·빠르게) 2·3·4배, 여러 장·폴더·끌어 놓기, PNG·JPG·WebP, 저장 위치, 진행률·멈추기, 원본 비교 창, 회전·ICC·투명 유지, exe 빌드 |
