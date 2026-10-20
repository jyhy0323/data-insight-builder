import io
import re
import csv
import json
import os
import logging
import pandas as pd
import numpy as np
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from google import genai
from google.genai import types

# tools 모듈의 12개 도구 카탈로그 및 JSON 정제 함수 임포트
from tools import TOOL_CATALOG, clean_for_json

# .env 환경변수 로드
load_dotenv()

# 로깅 설정 (print 대신 logging 사용)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.json.ensure_ascii = False  # 한글 깨짐 방지

# 업로드 최대 용량 설정
max_mb = int(os.getenv("MAX_UPLOAD_MB", 10))
app.config["MAX_CONTENT_LENGTH"] = max_mb * 1024 * 1024

# 메모리에 보관할 단일 데이터셋 저장소 (디스크 영구 저장 금지 규칙)
CURRENT_DATASET = {}

# 집계 행 식별용 키워드
AGGREGATE_KEYWORDS = [
    "world", "oecd members", "euro area", "european union",
    "high income", "low income", "middle income", "upper middle income",
    "lower middle income", "income", "area", "total", "sub-saharan",
    "latin america", "east asia", "north america", "south asia",
    "middle east", "fragile and conflict"
]

# 12개 도구 명세 (Gemini 가이드용)
TOOL_METADATA_FOR_AI = {
    "reshape_wide_to_long": "가로로 나열된 연도 열들을 세로(Long) 행으로 접어 시계열 레코드로 변환 (params: id_vars)",
    "quality_report": "결측률, 중복 행, 열별 타입 및 구조적 무결성 점검 보고서",
    "year_coverage": "연도별 데이터 충실도 계산 및 가장 데이터가 풍부한 권장 기준연도 확인 (막대 차트)",
    "detect_aggregates": "World, OECD, 소득 그룹 등 국가 간 통계 왜곡을 일으키는 집계 행 감지",
    "describe_numeric": "평균, 중앙값, 표준편차, 최솟값, 최댓값, 사분위수 계산 (params: reference_period, exclude_aggregates)",
    "trend_line": "주요 국가/항목의 연도별 시계열 추이 분석 (선 차트, params: items, start_year, end_year)",
    "top_bottom_n": "특정 기준연도 기준 상위 N개 및 하위 N개 순위 비교 (수평 막대 차트, params: reference_period, n, exclude_aggregates, include_items: 특정 비교 대상 국가 리스트 (예: ['Korea, Rep.']))",
    "group_summary": "그룹별 평균, 합계, 개수 집계 (막대 차트, params: reference_period, group_column, exclude_aggregates)",
    "change_rate": "두 시점 간 절대 변화량 및 성장률(%) 분석 (막대 차트, params: reference_period, start_period, exclude_aggregates)",
    "distribution": "수치 지표의 구간별 빈도수 분포 분석 (히스토그램 막대 차트, params: reference_period, bins, exclude_aggregates)",
    "correlation_scatter": "두 시점/변수 간 피어슨 상관계수 및 산점도 분석 (params: reference_period, compare_column, exclude_aggregates)",
    "compare_one_vs_all": "특정 1개 국가/항목 vs 전체 평균 및 중앙값 비교 (강조 막대 차트, params: reference_period, target_item, exclude_aggregates)"
}

def detect_encoding_and_read(file_bytes):
    encodings = ["utf-8-sig", "utf-8", "cp949", "euc-kr"]
    for enc in encodings:
        try:
            text = file_bytes.decode(enc)
            logger.info(f"[ENCODING] {enc} 디코딩 성공")
            return text, enc
        except UnicodeDecodeError:
            logger.info(f"[ENCODING] {enc} 시도 실패 (다음 인코딩 시도)")
            continue
    return None, None

def detect_header_skip_rows(text_content, max_check_lines=25):
    lines = text_content.splitlines()
    if not lines:
        return 0

    check_lines = lines[:max_check_lines]
    row_lengths = []
    
    for line in check_lines:
        if not line.strip():
            row_lengths.append(0)
            continue
        try:
            reader = list(csv.reader([line]))
            row_lengths.append(len(reader[0]) if reader else 0)
        except Exception:
            row_lengths.append(0)

    max_cols = max(row_lengths) if row_lengths else 0
    if max_cols <= 1:
        return 0

    threshold = max(2, int(max_cols * 0.7))
    for idx, count in enumerate(row_lengths):
        if count >= threshold:
            logger.info(f"[HEADER] 헤더 줄 감지 완료: {idx}번째 행 (건너뛴 줄 수={idx}, 열 수={count})")
            return idx

    return 0

def diagnose_dataframe(df):
    rows, cols = df.shape
    col_names = [str(c).strip() for c in df.columns]
    warnings = []

    unnamed_cols = [c for c in col_names if c.startswith("Unnamed:") or c == ""]
    if unnamed_cols:
        warnings.append(f"이름이 없는(Unnamed) 열이 {len(unnamed_cols)}개 있습니다: {', '.join(unnamed_cols[:3])}")

    empty_cols = [c for c in df.columns if df[c].isna().all()]
    if empty_cols:
        warnings.append(f"전체 행이 완전히 비어 있는 열이 {len(empty_cols)}개 있습니다: {', '.join(map(str, empty_cols[:3]))}")

    dtypes = {}
    missing_stats = {}
    for col in df.columns:
        col_str = str(col).strip()
        dtypes[col_str] = str(df[col].dtype)
        null_count = int(df[col].isna().sum())
        null_ratio = round((null_count / rows * 100), 2) if rows > 0 else 0.0
        missing_stats[col_str] = {
            "count": null_count,
            "ratio": null_ratio
        }

    duplicate_rows = int(df.duplicated().sum())
    if duplicate_rows > 0:
        warnings.append(f"완전히 동일한 중복 행이 {duplicate_rows}개 있습니다.")

    year_pattern = re.compile(r"^(19\d\d|20\d\d)$")
    year_candidate_cols = [c for c in col_names if year_pattern.match(c)]
    
    numeric_cols = []
    text_cols = []
    for col in df.columns:
        col_str = str(col).strip()
        if pd.api.types.is_numeric_dtype(df[col]):
            numeric_cols.append(col_str)
        else:
            non_nulls = df[col].dropna()
            if len(non_nulls) > 0 and pd.to_numeric(non_nulls.head(20), errors="coerce").notna().all():
                numeric_cols.append(col_str)
            else:
                text_cols.append(col_str)

    year_coverage = {}
    recommended_year = None
    if year_candidate_cols:
        sorted_years = sorted(year_candidate_cols, key=lambda x: int(x))
        for yr in sorted_years:
            val_count = int(df[yr].notna().sum())
            year_coverage[yr] = val_count

        if year_coverage:
            max_val = max(year_coverage.values())
            if max_val > 0:
                candidates = [yr for yr in sorted_years if year_coverage[yr] >= max_val * 0.85]
                recommended_year = candidates[-1] if candidates else sorted_years[-1]
            else:
                recommended_year = sorted_years[-1]

    aggregate_rows = []
    for t_col in text_cols[:3]:
        if t_col in df.columns:
            for idx, val in df[t_col].dropna().items():
                val_str = str(val).strip()
                val_lower = val_str.lower()
                matched = [kw for kw in AGGREGATE_KEYWORDS if kw in val_lower]
                if matched:
                    aggregate_rows.append({
                        "row_index": int(idx),
                        "column": t_col,
                        "value": val_str,
                        "matched_keyword": matched[0]
                    })
    
    seen_indices = set()
    unique_aggregate_rows = []
    for agg in aggregate_rows:
        if agg["row_index"] not in seen_indices:
            seen_indices.add(agg["row_index"])
            unique_aggregate_rows.append(agg)

    if unique_aggregate_rows:
        warnings.append(f"전체 통계 왜곡을 일으킬 수 있는 집계 행 후보가 {len(unique_aggregate_rows)}개 감지되었습니다. (예: World, OECD 등)")

    preview_df = df.head(10).replace([np.inf, -np.inf], np.nan)
    preview_records = preview_df.where(pd.notnull(preview_df), None).to_dict(orient="records")

    logger.info(f"[DIAGNOSE] 진단 완료 warnings={len(warnings)}")

    raw_result = {
        "rows": rows,
        "columns": cols,
        "column_names": col_names,
        "dtypes": dtypes,
        "numeric_columns": numeric_cols,
        "text_columns": text_cols,
        "year_candidate_columns": year_candidate_cols,
        "missing_statistics": missing_stats,
        "duplicate_rows": duplicate_rows,
        "unnamed_columns": unnamed_cols,
        "empty_columns": [str(c) for c in empty_cols],
        "year_coverage": year_coverage,
        "recommended_reference_year": recommended_year,
        "aggregate_row_candidates": unique_aggregate_rows[:30],
        "aggregate_row_count": len(unique_aggregate_rows),
        "preview_10_rows": preview_records,
        "warnings": warnings
    }

    # 브라우저 JSON 파싱 에러(Unexpected token 'N', NaN)를 방지하기 위해 모든 NaN을 안전한 null로 변환
    return clean_for_json(raw_result)

@app.route("/", methods=["GET"])
def index():
    """메인 대시보드 화면 반환"""
    return render_template("index.html")

@app.route("/health", methods=["GET"])
def health():
    logger.info("[REQUEST] GET /health")
    api_key = os.getenv("GEMINI_API_KEY", "")
    is_key_configured = bool(api_key and api_key.strip() and not api_key.startswith("사용자_"))
    
    return jsonify({
        "status": "ok",
        "api_key_configured": is_key_configured,
        "model": os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    })

@app.route("/inspect", methods=["POST"])
def inspect_file():
    logger.info("[REQUEST] POST /inspect")

    if "file" not in request.files:
        logger.warning("[ERROR] 파일 미선택")
        return jsonify({"error": "업로드할 CSV 파일을 선택해 주세요."}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        logger.warning("[ERROR] 파일명이 비어 있습니다.")
        return jsonify({"error": "선택된 파일이 없습니다."}), 400

    if not file.filename.lower().endswith(".csv"):
        logger.warning(f"[ERROR] CSV 아님: {file.filename}")
        return jsonify({"error": "CSV 파일(.csv)만 업로드할 수 있습니다."}), 400

    file_bytes = file.read()
    file_size = len(file_bytes)
    logger.info(f"[FILE] name={file.filename} size={file_size} bytes")

    if file_size == 0:
        logger.warning("[ERROR] 빈 파일")
        return jsonify({"error": "업로드된 파일이 비어 있습니다."}), 400

    text_content, detected_encoding = detect_encoding_and_read(file_bytes)
    if not text_content:
        logger.error("[ERROR] 인코딩 전부 실패")
        return jsonify({"error": "지원하는 인코딩(UTF-8, CP949 등)으로 파일을 읽을 수 없습니다."}), 400

    skip_rows = detect_header_skip_rows(text_content)

    try:
        df = pd.read_csv(io.StringIO(text_content), skiprows=skip_rows)
    except Exception as e:
        logger.error(f"[ERROR] CSV 파싱 실패: {str(e)}", exc_info=True)
        return jsonify({"error": f"CSV 파일 분석 중 오류가 발생했습니다: {str(e)}"}), 400

    rows, cols = df.shape
    logger.info(f"[CSV] parsing 완료 rows={rows} columns={cols}")

    diagnostics = diagnose_dataframe(df)

    CURRENT_DATASET.clear()
    CURRENT_DATASET["filename"] = file.filename
    CURRENT_DATASET["file_size"] = file_size
    CURRENT_DATASET["encoding"] = detected_encoding
    CURRENT_DATASET["skipped_rows"] = skip_rows
    CURRENT_DATASET["df"] = df
    CURRENT_DATASET["diagnostics"] = diagnostics

    return jsonify({
        "filename": file.filename,
        "file_size": file_size,
        "encoding": detected_encoding,
        "skipped_rows": skip_rows,
        "diagnostics": diagnostics,
        "memory_notice": "파일은 서버 메모리에만 임시 보관되며, 서버를 재시작하면 초기화됩니다."
    })

@app.route("/suggest", methods=["POST"])
def suggest_analyses():
    logger.info("[REQUEST] POST /suggest")

    if "df" not in CURRENT_DATASET or "diagnostics" not in CURRENT_DATASET:
        logger.warning("[ERROR] 진단 데이터 없음 (/inspect 미실행)")
        return jsonify({"error": "분석할 데이터가 메모리에 없습니다. 먼저 CSV 파일을 업로드하고 진단을 완료해 주세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key.startswith("사용자_"):
        logger.error("[ERROR] API Key 미설정")
        return jsonify({"error": "Gemini API Key가 올바르게 설정되지 않았습니다. .env 파일을 확인해 주세요."}), 500

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    diag = CURRENT_DATASET["diagnostics"]

    diag_summary = {
        "filename": CURRENT_DATASET.get("filename"),
        "rows": diag.get("rows"),
        "columns": diag.get("columns"),
        "text_columns": diag.get("text_columns"),
        "year_candidate_columns_range": f"{diag.get('year_candidate_columns', [''])[0]} ~ {diag.get('year_candidate_columns', [''])[-1]}" if diag.get('year_candidate_columns') else "없음",
        "recommended_reference_year": diag.get("recommended_reference_year"),
        "aggregate_row_count": diag.get("aggregate_row_count"),
        "warnings": diag.get("warnings")
    }

    prompt = f"""
당신은 공식 통계 데이터를 가장 효과적으로 분석할 수 있는 도구를 추천하는 시니어 데이터 분석가입니다.

아래는 사용자가 업로드한 CSV 파일의 **진단 요약 정보**입니다:
{json.dumps(diag_summary, ensure_ascii=False, indent=2)}

다음은 시스템에서 실제로 실행할 수 있는 **도구 카탈로그(12개)**입니다:
{json.dumps(TOOL_METADATA_FOR_AI, ensure_ascii=False, indent=2)}

[엄격한 제약 규칙]
1. 반드시 위 도구 카탈로그에 명시된 12개 도구명(tool) 중에서만 3~5개를 엄선하여 제안하세요. (카탈로그에 없는 도구 제안 절대 금지)
2. 데이터에 없는 가상의 열 이름을 제안하지 마세요. (연도 분석 시에는 recommended_reference_year인 '{diag.get("recommended_reference_year")}'년을 적극 활용하세요.)
3. 7~12번 도구를 제안할 때는 params와 reference_period에 반드시 구체적인 기준 시점(예: '{diag.get("recommended_reference_year")}')을 포함하세요.
4. 집계 행(World, OECD 등)이 감지되었으므로 국가 순위/분포/상관 분석 시 exclude_aggregates는 true로 권장하세요.
5. 오직 아래 JSON 형식으로만 순수하게 출력하세요. 다른 안내 문구나 마크다운 백틱(```)은 포함하지 마세요.

출력 JSON 형식:
{{
  "suggestions": [
    {{
      "tool": "top_bottom_n",
      "params": {{
        "reference_period": "{diag.get('recommended_reference_year')}",
        "n": 10,
        "exclude_aggregates": true
      }},
      "reference_period": "{diag.get('recommended_reference_year')}",
      "why": "이 분석이 이 데이터에서 의미 있는 이유 설명",
      "caution": "해석할 때 주의할 점"
    }}
  ]
}}
"""

    logger.info(f"[AI] suggest 요청 시작 (model={model_name})")
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        logger.info("[AI] suggest 응답 수신 완료")
    except Exception as e:
        logger.error(f"[ERROR] Gemini API 호출 실패: {str(e)}", exc_info=True)
        return jsonify({"error": f"Gemini API 호출 중 오류가 발생했습니다: {str(e)}"}), 502

    try:
        parsed_json = json.loads(response.text)
        raw_suggestions = parsed_json.get("suggestions", [])
        
        valid_suggestions = []
        for sug in raw_suggestions:
            tool_name = sug.get("tool")
            if tool_name in TOOL_CATALOG:
                valid_suggestions.append(sug)
            else:
                logger.warning(f"[AI] 카탈로그에 없는 도구 필터링됨: {tool_name}")

        logger.info(f"[AI] JSON 파싱 결과: 총 {len(valid_suggestions)}개 유효 제안 확보")
    except Exception as e:
        logger.error(f"[ERROR] JSON 파싱 실패: {str(e)}, 원본 텍스트: {response.text}")
        return jsonify({"error": "Gemini 응답을 JSON으로 변환하는 데 실패했습니다."}), 500

    return jsonify({
        "status": "success",
        "recommended_reference_year": diag.get("recommended_reference_year"),
        "suggestions": valid_suggestions
    })

@app.route("/run", methods=["POST"])
def run_tool():
    logger.info("[REQUEST] POST /run")

    if "df" not in CURRENT_DATASET:
        logger.warning("[ERROR] 데이터셋 부재 (/run 호출 실패)")
        return jsonify({"error": "분석할 데이터가 메모리에 없습니다. 먼저 CSV 파일을 업로드해 주세요."}), 400

    req_data = request.get_json(silent=True) or {}
    tool_name = req_data.get("tool")
    params = req_data.get("params") or {}

    if not tool_name:
        logger.warning("[ERROR] 도구명 미지정")
        return jsonify({"error": "실행할 도구 이름(tool)이 지정되지 않았습니다."}), 400

    if tool_name not in TOOL_CATALOG:
        logger.warning(f"[ERROR] 도구 카탈로그에 없는 도구 요청: {tool_name}")
        return jsonify({"error": f"'{tool_name}'은(는) 지원되지 않는 도구입니다. 카탈로그에 있는 도구를 선택해 주세요."}), 400

    df = CURRENT_DATASET["df"]
    tool_func = TOOL_CATALOG[tool_name]

    try:
        result = tool_func(df, params)
    except ValueError as ve:
        logger.warning(f"[ERROR] 도구 파라미터 유효성 검증 실패: {str(ve)}")
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        logger.error(f"[ERROR] 도구 실행 실패 ({tool_name}): {str(e)}", exc_info=True)
        return jsonify({"error": f"도구 실행 중 오류가 발생했습니다: {str(e)}"}), 500

    used_rows = result.get("used_rows", 0)
    excluded_rows = result.get("excluded_rows", 0)
    logger.info(f"[TOOL] 도구명={tool_name}, 파라미터={params}, 사용 행 수={used_rows}, 제외 행 수={excluded_rows}")

    CURRENT_DATASET["last_run_result"] = result

    return jsonify({
        "status": "success",
        "result": result
    })

@app.route("/explain", methods=["POST"])
def explain_result():
    """
    POST /explain:
    /run의 계산 결과 또는 진단 요약만 Gemini에 전달하여 해석 보고서를 수신합니다.
    (모드 A: 진단만 전달하여 의도적으로 허술하게 추정 vs 모드 B: Pandas 계산 결과만 전달하여 정밀 해석)
    """
    logger.info("[REQUEST] POST /explain")

    if "df" not in CURRENT_DATASET:
        logger.warning("[ERROR] 데이터셋 부재 (/explain 호출 실패)")
        return jsonify({"error": "분석할 데이터가 메모리에 없습니다. 먼저 CSV 파일을 업로드해 주세요."}), 400

    req_data = request.get_json(silent=True) or {}
    mode = req_data.get("mode", "B").upper()

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key.startswith("사용자_"):
        logger.error("[ERROR] API Key 미설정")
        return jsonify({"error": "Gemini API Key가 올바르게 설정되지 않았습니다. .env 파일을 확인해 주세요."}), 500

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    diag = CURRENT_DATASET.get("diagnostics", {})

    logger.info(f"[AI] explain 요청 시작 (mode={mode})")

    if mode == "A":
        # 모드 A (비교용, 의도적으로 허술하게):
        # 진단 요약만 전달하고 "이 데이터를 분석해서 보고서를 써줘"라고 요청. Pandas 계산 결과를 일절 주지 않음.
        diag_summary = {
            "filename": CURRENT_DATASET.get("filename"),
            "rows": diag.get("rows"),
            "columns": diag.get("columns"),
            "column_names_sample": diag.get("column_names", [])[:10],
            "recommended_reference_year": diag.get("recommended_reference_year")
        }
        prompt = f"""
당신은 데이터 분석가입니다. 아래는 업로드된 데이터의 기본 진단 정보입니다:
{json.dumps(diag_summary, ensure_ascii=False, indent=2)}

이 데이터를 분석해서 보고서를 써줘.
"""
    else:
        # 모드 B (정식, 정밀 규칙 준수):
        # /run의 Pandas 계산 결과(표, 기준시점, 제외 행 수)만 전달하고 엄격한 원칙으로 해석
        run_result = req_data.get("result") or CURRENT_DATASET.get("last_run_result")
        if not run_result:
            logger.warning("[ERROR] 실행 결과 없음 (먼저 /run 실행 필요)")
            return jsonify({"error": "해석할 분석 결과가 없습니다. 먼저 도구를 실행(/run)해 주세요."}), 400

        result_payload = {
            "title": run_result.get("title"),
            "summary": run_result.get("summary"),
            "reference_period": run_result.get("reference_period"),
            "used_rows": run_result.get("used_rows"),
            "excluded_rows": run_result.get("excluded_rows"),
            "exclusion_reason": run_result.get("exclusion_reason"),
            "used_columns": run_result.get("used_columns"),
            "unit": run_result.get("unit"),
            "caution": run_result.get("caution"),
            "table_data": run_result.get("table")
        }

        prompt = f"""
당신은 신뢰할 수 있는 데이터 사이언티스트입니다.
아래 제공된 **Pandas의 정밀 계산 결과**만을 바탕으로 해석 보고서를 작성하세요.

[계산 결과 데이터]
{json.dumps(result_payload, ensure_ascii=False, indent=2)}

[작성 절대 원칙]
1. 제공된 계산 결과에 있는 숫자만 사용하세요. 직접 계산하거나 추측하여 수치를 만들지 마세요.
2. 데이터에 없는 국가·연도·열을 절대 언급하지 마세요 (할루시네이션 방지).
3. 기준 시점과 제외된 행 수, 제외 사유를 본문에서 반드시 명시하세요.
4. 상관관계를 인과관계로 표현하지 마세요. (원인과 결과를 단정하지 말 것)
5. 지표의 정의와 출처({CURRENT_DATASET.get('filename')})를 보고서 앞부분에 표기하세요.
6. 확인할 수 없는 것은 솔직하게 "이 데이터로는 확인할 수 없다"라고 쓰세요.
7. 중학생도 이해할 수 있게 명확하고 알기 쉽게 쓰되, 통계적 정확성을 절대 희생하지 마세요.

반드시 아래 마크다운 헤더 형식을 정확하게 지켜 작성하세요:
## 무엇을 봤는가
## 데이터 출처와 정의
## 기준 시점과 제외된 항목
## 계산 결과
## 읽어낼 수 있는 것
## 이 데이터로는 알 수 없는 것
## 다음에 확인해볼 것
"""

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        logger.info(f"[AI] explain 응답 수신 (mode={mode})")
    except Exception as e:
        logger.error(f"[ERROR] Gemini API explain 호출 실패: {str(e)}", exc_info=True)
        return jsonify({"error": f"Gemini API 호출 중 오류가 발생했습니다: {str(e)}"}), 502

    logger.info("[RESPONSE] status=200")
    return jsonify({
        "status": "success",
        "mode": mode,
        "explanation": response.text
    })

def fallback_rule_mapper(user_prompt, rec_year):
    """
    외부 AI API 일시 지연(503) 시 사용자를 기다리게 하거나 에러를 내지 않고,
    키워드 규칙 기반으로 도구와 파라미터를 즉시 매핑하는 고가용성 안전망 함수입니다.
    """
    p = user_prompt.lower()
    
    # 4자리 연도 추출 (예: 2024, 2015 등)
    years = re.findall(r"\b(19\d\d|20\d\d)\b", p)
    ref_year = years[0] if years else str(rec_year)

    # 특정 비교 대상 국가 탐지
    detected_countries = []
    if any(k in p for k in ["한국", "우리나라", "대한민국", "korea"]):
        detected_countries.append("Korea, Rep.")
    if any(k in p for k in ["미국", "united states", "usa"]):
        detected_countries.append("United States")
    if any(k in p for k in ["일본", "japan"]):
        detected_countries.append("Japan")
    if any(k in p for k in ["독일", "germany"]):
        detected_countries.append("Germany")

    if any(k in p for k in ["히스토그램", "분포", "구간", "빈도"]):
        return "distribution", {"reference_period": ref_year, "exclude_aggregates": True}, "키워드(히스토그램/분포) 기반 안전망 자동 매핑"
    elif any(k in p for k in ["순위", "상위", "하위", "탑", "top", "가장 높은", "가장 낮은", "1등", "랭킹", "비교"]):
        n_match = re.search(r"(\d+)\s*(개|위|등|명)", p)
        n_val = int(n_match.group(1)) if n_match else 10
        params = {"reference_period": ref_year, "n": n_val, "exclude_aggregates": True}
        if detected_countries:
            params["include_items"] = detected_countries
            return "top_bottom_n", params, f"키워드(상위 {n_val}개국 및 {', '.join(detected_countries)} 비교) 기반 안전망 자동 매핑"
        return "top_bottom_n", params, f"키워드(순위 상위/하위 {n_val}) 기반 안전망 자동 매핑"
    elif any(k in p for k in ["추이", "추세", "시계열", "선", "꺾은선", "변화선"]):
        trend_targets = detected_countries if detected_countries else ["Korea, Rep.", "United States", "Japan", "Germany"]
        return "trend_line", {"items": trend_targets}, "키워드(시계열 추이선) 기반 안전망 자동 매핑"
    elif any(k in p for k in ["성장", "변화량", "변화율", "성장률", "증가"]):
        start_year = years[1] if len(years) > 1 else "2015"
        return "change_rate", {"reference_period": ref_year, "start_period": start_year, "exclude_aggregates": True}, "키워드(변화량/성장률) 기반 안전망 자동 매핑"
    elif any(k in p for k in ["상관", "산점도", "관계", "scatter"]):
        comp_year = years[1] if len(years) > 1 else "2015"
        return "correlation_scatter", {"reference_period": ref_year, "compare_column": comp_year, "exclude_aggregates": True}, "키워드(상관계수 산점도) 기반 안전망 자동 매핑"
    elif any(k in p for k in ["평균과", "내 위치"]):
        target = detected_countries[0] if detected_countries else "Korea, Rep."
        return "compare_one_vs_all", {"reference_period": ref_year, "target_item": target, "exclude_aggregates": True}, "키워드(평균 비교) 기반 안전망 자동 매핑"
    else:
        params = {"reference_period": ref_year, "n": 10, "exclude_aggregates": True}
        if detected_countries:
            params["include_items"] = detected_countries
        return "top_bottom_n", params, "기본 순위 분석 도구 자동 매핑"

@app.route("/query", methods=["POST"])
def query_analysis_by_text():
    """
    POST /query:
    사용자의 자연어 요청(예: "2024년 히스토그램 그려줘", "상위 10개국이랑 한국 비교해줘")을 받아,
    Gemini가 도구 카탈로그 중 최적의 도구와 파라미터를 매핑하고 Pandas가 즉시 실행하여 차트를 생성합니다.
    (외부 AI 503 지연 시 지능형 규칙 폴백 안전망으로 자동 전환)
    """
    logger.info("[REQUEST] POST /query")

    if "df" not in CURRENT_DATASET:
        return jsonify({"error": "분석할 데이터가 메모리에 없습니다. 먼저 CSV 파일을 업로드해 주세요."}), 400

    req_data = request.get_json(silent=True) or {}
    user_prompt = req_data.get("prompt", "").strip()

    if not user_prompt:
        return jsonify({"error": "원하시는 분석이나 그래프 요청을 자연어로 입력해 주세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key.startswith("사용자_"):
        return jsonify({"error": "Gemini API Key가 올바르게 설정되지 않았습니다."}), 500

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    diag = CURRENT_DATASET.get("diagnostics", {})
    rec_year = diag.get("recommended_reference_year", "2024")

    # 자연어 의도 파악용 프롬프트
    router_prompt = f"""
당신은 사용자의 자연어 요청을 데이터 분석 도구 실행 명령으로 변환하는 라우터 AI입니다.

[사용자 자연어 요청]
"{user_prompt}"

[현재 데이터셋 정보]
- 사용 가능한 열 목록: {json.dumps(diag.get("column_names", [])[:15], ensure_ascii=False)} 등
- 감지된 연도 범위: {diag.get("year_candidate_columns", [""])[0]} ~ {diag.get("year_candidate_columns", [""])[-1]}
- 권장 기준연도: {rec_year}

[사용 가능한 12개 도구 카탈로그]
{json.dumps(TOOL_METADATA_FOR_AI, ensure_ascii=False, indent=2)}

[도구 매핑 가이드]
- "히스토그램", "분포", "구간" -> "distribution"
- "순위", "상위", "하위", "탑", "top", "가장 높은", "가장 낮은", "1등" -> "top_bottom_n"
  ※ 중요: 사용자가 상위/하위 N개와 함께 한국이나 특정 국가의 비교를 요구하는 경우 (예: "상위 10개국이랑 한국 비교", "top 10과 우리나라"), 
    도구는 반드시 "top_bottom_n"을 선택하고, params에 "include_items": ["Korea, Rep."]를 반드시 포함하세요.
- "추이", "변화선", "추세", "꺾은선", "선그래프", "시간 흐름" -> "trend_line"
- "성장률", "변화량", "증가량", "증가율", "얼마나 늘었나" -> "change_rate"
- "상관", "상관계수", "산점도", "관계", "점 찍기" -> "correlation_scatter"
- "평균과 비교", "중앙값과 비교", "내 위치" -> "compare_one_vs_all"
- "통계량", "평균", "표준편차" -> "describe_numeric"
- "그룹", "대륙별", "소득별" -> "group_summary"
- "연도 충실도", "데이터 개수" -> "year_coverage"
- 국가명 영문 표준 변환: 한국/대한민국/우리나라 -> "Korea, Rep.", 미국 -> "United States", 일본 -> "Japan", 중국 -> "China"
- 기준 시점이 특정되지 않은 경우 가급적 권장 기준연도인 '{rec_year}'를 reference_period로 지정하세요.
- exclude_aggregates는 기본적으로 true로 설정하세요.

반드시 아래 순수 JSON 형식으로만 응답하세요:
{{
  "tool": "선택한_도구명",
  "params": {{
    "reference_period": "{rec_year}",
    "n": 10,
    "include_items": ["Korea, Rep."],
    "exclude_aggregates": true
  }},
  "reason": "사용자의 요청 의도 분석 요약"
}}
"""

    tool_name = None
    params = {}
    reason = ""

    # 1차 시도: Gemini AI 라우터 호출
    try:
        logger.info(f"[AI] query 자연어 도구 매핑 시작: '{user_prompt}'")
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=router_prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        mapping_data = json.loads(response.text)
        tool_name = mapping_data.get("tool")
        params = mapping_data.get("params", {})
        reason = mapping_data.get("reason", "")
        logger.info(f"[AI] 매핑 성공: tool={tool_name}, params={params}")
    except Exception as e:
        # 외부 AI 503 또는 통신 오류 감지 시 즉시 지능형 안전망 가동!
        logger.warning(f"[AI] Gemini 호출 지연/실패 ({str(e)}) -> 지능형 규칙 폴백 안전망 가동")
        tool_name, params, reason = fallback_rule_mapper(user_prompt, rec_year)
        reason += " (※ AI 서버 일시 지연으로 고가용성 규칙 안전망으로 분석 완료)"

    if not tool_name or tool_name not in TOOL_CATALOG:
        tool_name, params, reason = fallback_rule_mapper(user_prompt, rec_year)

    # [핵심 보정 안전망] 사용자 요청에 한국/우리나라가 포함되어 있는데 top_bottom_n에 include_items가 누락된 경우 자동 주입
    p_lower = user_prompt.lower()
    if tool_name == "top_bottom_n":
        if any(k in p_lower for k in ["한국", "우리나라", "대한민국", "korea"]):
            cur_items = params.get("include_items", [])
            if not isinstance(cur_items, list):
                cur_items = [str(cur_items)]
            if not any("korea" in str(x).lower() for x in cur_items):
                cur_items.append("Korea, Rep.")
            params["include_items"] = cur_items
            logger.info(f"[ROUTER] 한국 비교 요청 감지 -> params.include_items에 'Korea, Rep.' 보정 삽입: {cur_items}")

    # 매핑된 도구를 Pandas로 즉시 실행!
    try:
        df = CURRENT_DATASET["df"]
        result = TOOL_CATALOG[tool_name](df, params)
        CURRENT_DATASET["last_run_result"] = result
        logger.info(f"[TOOL] 자연어 실행 완료: 도구명={tool_name}, 사용행={result.get('used_rows')}")
    except Exception as e:
        logger.error(f"[ERROR] 자연어 매핑 도구 실행 실패: {str(e)}", exc_info=True)
        return jsonify({"error": f"도구 실행 중 오류가 발생했습니다: {str(e)}"}), 500

    return jsonify({
        "status": "success",
        "user_prompt": user_prompt,
        "matched_tool": tool_name,
        "matched_params": params,
        "reason": reason,
        "result": result
    })

@app.route("/ask", methods=["POST"])
def ask_question():
    """
    POST /ask:
    방금 도출된 계산 결과(표, 기준 시점, 사용/제외 행 수 등)를 바탕으로 사용자의 후속 질문에 답변합니다.
    (절대 규칙: 계산된 수치 표에 기반해서만 답변, 데이터에 없는 내용은 '확인 불가' 명시)
    """
    logger.info("[REQUEST] POST /ask")

    if "df" not in CURRENT_DATASET:
        return jsonify({"error": "분석할 데이터가 메모리에 없습니다. 먼저 CSV 파일을 업로드해 주세요."}), 400

    last_run = CURRENT_DATASET.get("last_run_result")
    if not last_run:
        return jsonify({"error": "먼저 분석 도구를 실행(/run)하여 계산 결과를 만들어 주세요."}), 400

    req_data = request.get_json(silent=True) or {}
    user_question = req_data.get("question", "").strip()

    if not user_question:
        return jsonify({"error": "질문 내용을 입력해 주세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key.startswith("사용자_"):
        return jsonify({"error": "Gemini API Key가 올바르게 설정되지 않았습니다."}), 500

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

    # 계산 결과 컨텍스트 구성
    context_payload = {
        "title": last_run.get("title"),
        "summary": last_run.get("summary"),
        "reference_period": last_run.get("reference_period"),
        "used_rows": last_run.get("used_rows"),
        "excluded_rows": last_run.get("excluded_rows"),
        "exclusion_reason": last_run.get("exclusion_reason"),
        "caution": last_run.get("caution"),
        "table_data": last_run.get("table")
    }

    # [핵심 개선] 상위/하위 목록 외 국가(한국 등) 질문 시, Pandas가 전체 데이터에서 실제 순위와 수치를 백그라운드로 즉시 계산
    extra_country_facts = []
    ref_period = last_run.get("reference_period")
    if ref_period and str(ref_period) in CURRENT_DATASET["df"].columns:
        df_full = CURRENT_DATASET["df"].copy()
        val_col = str(ref_period)
        
        # 라벨 열 찾기
        label_col = "Country Name" if "Country Name" in df_full.columns else df_full.columns[0]
        
        # 집계 행 필터링 및 숫자 변환
        agg_mask = df_full[label_col].astype(str).str.lower().apply(
            lambda val: any(kw in val for kw in AGGREGATE_KEYWORDS)
        )
        clean_df = df_full[~agg_mask][[label_col, val_col]].copy()
        clean_df[val_col] = pd.to_numeric(clean_df[val_col], errors="coerce")
        valid_rank_df = clean_df.dropna(subset=[val_col]).sort_values(by=val_col, ascending=False).reset_index(drop=True)
        valid_rank_df["Rank"] = valid_rank_df.index + 1

        # 한국(Korea) 정보는 기본 산출
        korea_match = valid_rank_df[valid_rank_df[label_col].str.contains("Korea, Rep.", case=False, na=False)]
        if not korea_match.empty:
            k_row = korea_match.iloc[0]
            extra_country_facts.append({
                "country": k_row[label_col],
                "rank": int(k_row["Rank"]),
                "total_countries": len(valid_rank_df),
                "value": round(float(k_row[val_col]), 2),
                "period": val_col
            })

        # 질문에 다른 주요 국가명이 포함되어 있다면 해당 국가 순위도 자동 산출
        q_lower = user_question.lower()
        for _, r in valid_rank_df.iterrows():
            c_name = str(r[label_col])
            c_low = c_name.lower()
            if (c_low in q_lower or (c_low.split(",")[0] in q_lower and len(c_low.split(",")[0]) > 3)) and c_name != "Korea, Rep.":
                extra_country_facts.append({
                    "country": c_name,
                    "rank": int(r["Rank"]),
                    "total_countries": len(valid_rank_df),
                    "value": round(float(r[val_col]), 2),
                    "period": val_col
                })
                if len(extra_country_facts) >= 5:
                    break

    prompt = f"""
당신은 신뢰할 수 있는 데이터 전문 어시스턴트입니다.
사용자가 현재 화면에 표시된 **Pandas 분석 계산 결과**에 대해 다음과 같은 후속 질문을 했습니다:

[사용자 후속 질문]
"{user_question}"

[현재 계산된 분석 결과 데이터 (상위/하위 요약)]
{json.dumps(context_payload, ensure_ascii=False, indent=2)}

[Pandas가 전체 데이터셋에서 직접 조회한 추가 팩트 데이터]
{json.dumps(extra_country_facts, ensure_ascii=False, indent=2)}

[답변 원칙]
1. 사용자가 우리나라(한국)나 특정 국가의 순위를 물어본 경우, 위 [추가 팩트 데이터]에 있는 정확한 순위(예: 한국 Korea, Rep.의 실제 순위와 수치)를 바탕으로 명확하게 답변해 주세요.
2. 위 제공된 계산 데이터와 팩트 데이터에 있는 사실만을 근거로 답변하세요.
3. 데이터에서 확인할 수 없는 질문인 경우, 솔직하게 "제공된 분석 데이터로는 확인할 수 없습니다"라고 분명히 밝히세요.
4. 친절하고 명확하게 마크다운 형식으로 답변하세요.
"""

    logger.info(f"[AI] ask 후속 질문 요청 시작 (model={model_name})")
    try:
        client = genai.Client(api_key=api_key)
        fast_config = types.GenerateContentConfig(
            max_output_tokens=600,
            temperature=0.3
        )
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=fast_config
        )
        logger.info("[AI] ask 후속 질문 응답 수신 완료")
    except Exception as e:
        logger.warning(f"[AI] {model_name} 지연 감지 ({str(e)}) -> 백업 고속 모델로 즉시 전환")
        try:
            # 2차 초고속 백업 모델 호출
            backup_model = "gemini-flash-lite-latest"
            response = client.models.generate_content(
                model=backup_model,
                contents=prompt,
                config=fast_config
            )
            logger.info(f"[AI] 백업 모델({backup_model}) 응답 수신 완료")
        except Exception as e2:
            logger.error(f"[ERROR] Gemini API ask 호출 최종 실패: {str(e2)}", exc_info=True)
            return jsonify({"error": f"답변 생성 중 오류가 발생했습니다: {str(e2)}"}), 502

    logger.info("[RESPONSE] status=200")
    return jsonify({
        "status": "success",
        "question": user_question,
        "answer": response.text
    })

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    logger.info(f"Starting Flask server (debug={debug_mode})...")
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
