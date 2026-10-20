# 📊 AI Data Insight Builder
> **공식 통계 데이터 정밀 진단 및 Pandas 계산 기반 지능형 데이터 인사이트 시스템**  
> *Empirical Statistical Analysis Engine with Google Gemini API & Progressive Web App*

[![Live Demo](https://img.shields.io/badge/Demo-Live%20Service-brightgreen?style=for-the-badge&logo=vercel)](https://data-insight-builder-one.vercel.app/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0+-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Pandas](https://img.shields.io/badge/Pandas-2.0+-150458?style=for-the-badge&logo=pandas&logoColor=white)](https://pandas.pydata.org/)
[![Gemini API](https://img.shields.io/badge/Google%20Gemini-3.5%20Flash%20Lite-8E75C2?style=for-the-badge&logo=googlegemini&logoColor=white)](https://ai.google.dev/)
[![PWA](https://img.shields.io/badge/PWA-Mobile%20Ready-5A0FC8?style=for-the-badge&logo=pwa&logoColor=white)](https://data-insight-builder-one.vercel.app/)

---

## 🌐 라이브 서비스 체험

- **배포 주소:** [https://data-insight-builder-one.vercel.app/](https://data-insight-builder-one.vercel.app/)
- **접속 비밀번호:** `1234`
- **모바일 지원:** 스마트폰 브라우저 접속 후 **[홈 화면에 추가]** 또는 **[앱 설치]** 지원 (PWA)

---

## 📌 프로젝트 기획 배경 및 철학

기존의 생성형 AI(LLM)는 겉보기에 유창하지만 **"수치 계산과 통계 분석에서 심각한 할루시네이션(수치 날조 및 왜곡)"**을 일으킵니다.  
**AI Data Insight Builder**는 이 문제를 해결하기 위해 다음의 **엄격한 데이터 사이언스 원칙**을 기반으로 설계되었습니다:

1. **계산과 추론의 완벽한 분리 (Separation of Concerns)**
   - 모든 통계 수치 계산은 **순수 Pandas 엔진**만이 수행합니다.
   - LLM은 수치를 직접 계산하지 않고, Pandas가 산출한 **검증된 계산 표(Table)만을 해석**합니다.
2. **원천 데이터 보안 (Data Privacy)**
   - 수십 메가바이트의 원본 CSV를 외부에 전송하지 않습니다.
   - 데이터는 서버 메모리에만 임시 상주하며, AI에게는 최소한의 진단 요약만 전달됩니다.
3. **통계적 정직성과 왜곡 방지 (Statistical Integrity)**
   - 결측치(NaN) 처리 사유, 집계 행(World, OECD 등) 제외 내역, 기준 시점을 명확히 공시하여 통계적 왜곡을 원천 차단합니다.

---

## 🔬 핵심 통계 분석 엔진 (12 Tools Catalog)

Pandas를 통해 정밀하게 구현된 12가지 공식 통계 전용 분석 도구를 탑재하고 있습니다:

| 도구명 | 분석 기법 | 시각화 형태 | 통계적 목적 |
| :--- | :--- | :---: | :--- |
| **`reshape_wide_to_long`** | 데이터 구조 재형태화 | - | 와이드(Wide) 연도 열들을 표준 시계열 롱(Long) 포맷으로 변환 |
| **`quality_report`** | 데이터 무결성 감사 | - | 결측률, 중복 행, 열별 타입 및 구조적 결함 정밀 보고 |
| **`year_coverage`** | 연도별 충실도 분석 | Bar Chart | 결측치가 가장 적고 신뢰도가 높은 **최적 권장 기준연도 자동 도출** |
| **`detect_aggregates`** | 왜곡 요인(집계 행) 감지 | Table | World, OECD, 소득 그룹 등 국가 간 통계 왜곡을 유발하는 29개 이상 그룹 행 식별 |
| **`describe_numeric`** | 기초 기술통계량 | Table | 평균, 중앙값, 표준편차, 최솟값, 최댓값, 사분위수(IQR) 산출 |
| **`top_bottom_n`** | 최상위/최하위 순위 분석 | Horiz Bar | 상·하위 순위 비교 및 **특정 국가(한국 등) 자동 탐지 하이라이트** |
| **`trend_line`** | 시계열 다중 추세 분석 | Line Chart | 주요 국가들의 장기 시계열 변화 궤적 및 성장 추세 비교 |
| **`distribution`** | 구간별 빈도수 분석 | Histogram | 데이터의 왜도(Skewness), 양극화, 정규분포 적합성 검증 |
| **`change_rate`** | 기간별 변화량 및 성장률 | Bar Chart | 두 시점 간 절대 증감량 및 상대 성장률(%) 정밀 측정 |
| **`correlation_scatter`** | 피어슨 상관분석 | Scatter Plot | 두 변수/연도 간 상관계수($r$) 및 산점도 추세 도출 |
| **`compare_one_vs_all`** | 개별 항목 vs 전체 집단 비교 | Bar Chart | 특정 1개국 vs 전체 집단 평균 및 중앙값 격차 분석 |
| **`group_summary`** | 대륙·소득 그룹별 집계 | Bar Chart | 카테고리별 기술통계 요약 및 그룹 간 격차 비교 |

---

## 🧠 이중 해석 비교 시스템 (Mode A vs Mode B)

사용자가 **"통계 수치에 기반하지 않은 AI의 위험성"**을 직관적으로 배울 수 있도록 2가지 해석 모드를 제공합니다:

```
[Mode A: 허술한 추정 보고서]
 진단 요약만 보고 AI가 마음대로 상상하여 작성
 ➔ 존재하지 않는 수치 날조, 상관관계를 인과관계로 단정, 모호한 환각 발생

[Mode B: 정밀 통계 보고서 (Senior Standard)]
 Pandas의 정밀 계산 결과(표, 제외 행 수, 사유)만을 엄격한 7단계 프롬프트로 해석
 1. 무엇을 보았는가
 2. 데이터 출처와 지표 정의
 3. 기준 시점과 제외된 항목 (신뢰도 공시)
 4. 계산 결과 (수치 왜곡 제로)
 5. 읽어낼 수 있는 통계적 함의
 6. 이 데이터로는 알 수 없는 한계점
 7. 다음에 확인해 볼 후속 검증 과제
```

---

## 💬 대화형 자연어 분석 & 심층 질의응답 (Interactive Q&A)

- **자연어 차트 생성 (Smart NL Router)**:  
  *"2024년 상위 10개국이랑 한국 비교해줘"* ➔ AI가 의도를 파악하여 적절한 도구 매핑 및 한국(13위, 97.90%) 자동 하이라이트 렌더링.
- **백그라운드 순위 재계산 기반 질의응답**:  
  목록에 없는 국가 순위를 물어보더라도, Pandas가 전체 데이터셋에서 실시간으로 실제 순위를 역추적하여 오차 없는 팩트만을 답변합니다.

---

## 📱 PWA & 모바일 최적화 아키텍처

- **Web App Manifest & Service Worker**: 스마트폰에서 브라우저 주소창 없이 네이티브 앱처럼 풀스크린 실행 가능.
- **Vercel Serverless 무중단 데이터 자동 복원**: 서버리스 인스턴스가 요청마다 초기화되더라도 클라이언트-서버 간 데이터 동기화(`SERVERLESS_DATA_CACHE`)로 데이터 유실 방지.
- **iOS Safari & 터치 최적화**: 44px 이상 터치 타겟, 자동 확대 방지(16px 규칙), 부드러운 테이블 가로 스와이프 지원.

---

## 🔒 보안 및 프라이버시

- **Password Gate**: 외부 무단 접속 방지를 위한 비밀번호 세션 잠금 (`APP_PASSWORD=1234`).
- **Zero API Key Leakage**: 프론트엔드 코드나 브라우저 콘솔, Git 커밋에 API Key가 절대 노출되지 않도록 환경변수 및 백엔드 프록시 격리.

---

## 💻 로컬 개발 환경 실행

```bash
# 1. 저장소 클론
git clone https://github.com/jyhy0323/data-insight-builder.git
cd data-insight-builder

# 2. 가상환경 생성 및 의존성 설치
python -m venv .venv
.\.venv\Scripts\activate  # Windows
pip install -r requirements.txt

# 3. 환경변수 설정 (.env 파일 생성)
cp .env.example .env
# .env 파일에 GEMINI_API_KEY 입력

# 4. Flask 서버 실행
python app.py
# 브라우저에서 http://127.0.0.1:5000 접속 (비밀번호: 1234)
```

---

### 📄 License & Academic Note
본 프로젝트는 **실증적 통계 분석(Empirical Data Science)과 인공지능(AI)의 안전한 결합**을 탐구하기 위한 교육 및 학술 연구 목적으로 제작되었습니다.
