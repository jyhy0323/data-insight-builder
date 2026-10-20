import re
import pandas as pd
import numpy as np

# 집계 행(통계 왜곡 유발) 탐지용 키워드
AGGREGATE_KEYWORDS = [
    "world", "oecd members", "euro area", "european union",
    "high income", "low income", "middle income", "upper middle income",
    "lower middle income", "income", "area", "total", "sub-saharan",
    "latin america", "east asia", "north america", "south asia",
    "middle east", "fragile and conflict"
]

def clean_for_json(data):
    """
    NaN, Infinity, -Infinity 값을 JSON 직렬화가 가능한 None / 0 으로 안전하게 변환합니다.
    """
    if isinstance(data, dict):
        return {k: clean_for_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_for_json(v) for v in data]
    elif isinstance(data, float):
        if np.isnan(data) or np.isinf(data):
            return None
        return round(data, 4)
    elif pd.isna(data):
        return None
    return data

def find_year_columns(df):
    """4자리 연도(1900~2099) 형태의 열 목록을 추출하고 정렬하여 반환합니다."""
    year_pattern = re.compile(r"^(19\d\d|20\d\d)$")
    year_cols = [str(c).strip() for c in df.columns if year_pattern.match(str(c).strip())]
    return sorted(year_cols, key=lambda x: int(x))

def find_label_column(df, explicit_col=None):
    """항목명/국가명으로 사용할 텍스트 열을 찾습니다."""
    if explicit_col and explicit_col in df.columns:
        return explicit_col
    for c in df.columns:
        if not str(c).startswith("Unnamed:") and pd.api.types.is_object_dtype(df[c]):
            return c
    return df.columns[0]

def filter_aggregates(df, label_col):
    """집계 행 키워드가 포함된 행을 필터링하고 마스크를 반환합니다."""
    is_agg = df[label_col].astype(str).str.lower().apply(
        lambda val: any(kw in val for kw in AGGREGATE_KEYWORDS)
    )
    return is_agg

# -------------------------------------------------------------
# 도구 1: reshape_wide_to_long (연도 열을 행으로 접기)
# -------------------------------------------------------------
def reshape_wide_to_long(df, params=None):
    params = params or {}
    year_cols = params.get("year_columns") or find_year_columns(df)
    
    if not year_cols:
        raise ValueError("변환할 연도 열을 찾을 수 없습니다.")

    id_vars = params.get("id_vars")
    if not id_vars:
        id_vars = [c for c in df.columns if c not in year_cols and not str(c).startswith("Unnamed:")]

    total_rows = len(df)
    melted = pd.melt(
        df,
        id_vars=id_vars,
        value_vars=year_cols,
        var_name="Year",
        value_name="Value"
    )

    melted["Value"] = pd.to_numeric(melted["Value"], errors="coerce")
    valid_melted = melted.dropna(subset=["Value"])
    excluded_count = len(melted) - len(valid_melted)

    sample_records = valid_melted.head(15).to_dict(orient="records")

    return {
        "tool": "reshape_wide_to_long",
        "title": "연도 열 행 변환 (Wide to Long)",
        "summary": f"{len(year_cols)}개 연도 열을 세로 행으로 변환하여 총 {len(valid_melted):,}개의 시계열 레코드를 생성했습니다.",
        "table": clean_for_json(sample_records),
        "total_generated_rows": len(valid_melted),
        "reference_period": f"{year_cols[0]}~{year_cols[-1]} (전체 연도)",
        "used_rows": total_rows,
        "excluded_rows": excluded_count,
        "exclusion_reason": f"해당 연도에 측정값(Value)이 없는 결측 셀 {excluded_count:,}건을 제외했습니다.",
        "used_columns": id_vars + ["Year", "Value"],
        "unit": "행 (Records)",
        "caution": "원본 1개 행이 연도 개수만큼 복제되므로, 단순 합계나 평균 시 중복 집계에 주의해야 합니다."
    }

# -------------------------------------------------------------
# 도구 2: quality_report (결측·중복·타입·이상한 열 이름 진단)
# -------------------------------------------------------------
def quality_report(df, params=None):
    total_rows = len(df)
    total_cols = len(df.columns)
    
    report_rows = []
    unnamed_count = 0
    empty_cols_count = 0

    for col in df.columns:
        c_str = str(col).strip()
        dtype_str = str(df[col].dtype)
        null_cnt = int(df[col].isna().sum())
        null_pct = round((null_cnt / total_rows * 100), 2) if total_rows > 0 else 0.0
        
        is_unnamed = c_str.startswith("Unnamed:") or c_str == ""
        is_empty = (null_cnt == total_rows)
        if is_unnamed:
            unnamed_count += 1
        if is_empty:
            empty_cols_count += 1

        report_rows.append({
            "column": c_str,
            "data_type": dtype_str,
            "missing_count": null_cnt,
            "missing_ratio_pct": null_pct,
            "is_unnamed": is_unnamed,
            "is_empty": is_empty
        })

    duplicates = int(df.duplicated().sum())

    return {
        "tool": "quality_report",
        "title": "데이터 품질 종합 보고서",
        "summary": f"총 {total_rows}행 {total_cols}열 점검 결과, 중복 행 {duplicates}건, 이름 없는 열 {unnamed_count}개, 완전 빈 열 {empty_cols_count}개가 확인되었습니다.",
        "table": clean_for_json(report_rows),
        "reference_period": "전체 시점",
        "used_rows": total_rows,
        "excluded_rows": 0,
        "exclusion_reason": "전체 행과 열의 구조적 무결성을 평가하기 위해 제외된 행이 없습니다.",
        "used_columns": list(df.columns),
        "unit": "개수 및 비율(%)",
        "caution": "결측률이 50%를 초과하는 열은 분석 시 편향이 발생할 수 있으므로 주의가 필요합니다."
    }

# -------------------------------------------------------------
# 도구 3: year_coverage (연도별 값 개수와 권장 기준연도)
# -------------------------------------------------------------
def year_coverage(df, params=None):
    year_cols = find_year_columns(df)
    if not year_cols:
        raise ValueError("연도 열이 존재하지 않아 연도 충실도를 계산할 수 없습니다.")

    total_rows = len(df)
    coverage_list = []
    labels = []
    counts = []

    for yr in year_cols:
        valid_cnt = int(df[yr].notna().sum())
        ratio_pct = round((valid_cnt / total_rows * 100), 2) if total_rows > 0 else 0.0
        labels.append(yr)
        counts.append(valid_cnt)
        coverage_list.append({
            "year": yr,
            "valid_count": valid_cnt,
            "coverage_pct": ratio_pct
        })

    max_count = max(counts) if counts else 0
    recommended_year = year_cols[-1]
    if max_count > 0:
        candidates = [yr for yr, cnt in zip(labels, counts) if cnt >= max_count * 0.85]
        if candidates:
            recommended_year = candidates[-1]

    return {
        "tool": "year_coverage",
        "title": "연도별 데이터 충실도 및 권장 기준연도",
        "summary": f"연도별 데이터 수집율을 분석한 결과, 가장 최근이면서 데이터가 충실한 권장 기준연도는 '{recommended_year}'년입니다.",
        "table": clean_for_json(coverage_list),
        "recommended_reference_year": recommended_year,
        "chart_data": {
            "type": "bar",
            "labels": labels,
            "datasets": [
                {
                    "label": "유효 데이터 보유 항목 수",
                    "data": counts
                }
            ]
        },
        "reference_period": f"{labels[0]}~{labels[-1]}",
        "used_rows": total_rows,
        "excluded_rows": 0,
        "exclusion_reason": "전체 연도 충실도 분석을 위해 모든 행을 대상으로 유효성 검사를 수행했습니다.",
        "used_columns": year_cols,
        "unit": "개수(건)",
        "caution": "초기 연도는 통계 집계가 되지 않아 결측치가 많으므로 시계열 비교 시 시작점에 유의해야 합니다."
    }

# -------------------------------------------------------------
# 도구 4: detect_aggregates (집계 행 후보 탐지)
# -------------------------------------------------------------
def detect_aggregates(df, params=None):
    params = params or {}
    total_rows = len(df)
    label_col = find_label_column(df, params.get("label_column"))

    detected = []
    seen_indices = set()

    for idx, val in df[label_col].dropna().items():
        val_str = str(val).strip()
        val_lower = val_str.lower()
        matched = [kw for kw in AGGREGATE_KEYWORDS if kw in val_lower]
        if matched and idx not in seen_indices:
            seen_indices.add(idx)
            detected.append({
                "row_index": int(idx),
                "name": val_str,
                "matched_keyword": matched[0]
            })

    return {
        "tool": "detect_aggregates",
        "title": "집계 및 그룹 행(Aggregate Rows) 탐지",
        "summary": f"개별 국가가 아닌 지역·소득 그룹·전 세계 합산으로 추정되는 집계 행 {len(detected)}개를 탐지했습니다.",
        "table": clean_for_json(detected),
        "aggregate_count": len(detected),
        "reference_period": "전체 시점",
        "used_rows": total_rows,
        "excluded_rows": 0,
        "exclusion_reason": "데이터셋 전체에서 집계 행을 식별하기 위해 모든 행을 검사했습니다.",
        "used_columns": [label_col],
        "unit": "건",
        "caution": "순위 분석이나 통계 계산 시 집계 행을 포함하면 심각한 왜곡이 발생하므로 제외하는 것을 권장합니다."
    }

# -------------------------------------------------------------
# 도구 5: describe_numeric (개수·평균·중앙값·최소·최대·표준편차)
# -------------------------------------------------------------
def describe_numeric(df, params=None):
    params = params or {}
    col = params.get("column") or params.get("reference_period")
    
    if not col or col not in df.columns:
        year_cols = find_year_columns(df)
        col = year_cols[-1] if year_cols else None
        if not col or col not in df.columns:
            raise ValueError("분석할 숫자형 열 또는 기준 연도를 지정해야 합니다.")

    label_col = find_label_column(df, params.get("label_column"))
    exclude_aggs = params.get("exclude_aggregates", True)

    sub_df = df.copy()
    excluded_aggs_count = 0
    if exclude_aggs and label_col in sub_df.columns:
        agg_mask = filter_aggregates(sub_df, label_col)
        excluded_aggs_count = int(agg_mask.sum())
        sub_df = sub_df[~agg_mask]

    series = pd.to_numeric(sub_df[col], errors="coerce")
    valid_series = series.dropna()
    
    missing_count = int(series.isna().sum())
    total_excluded = excluded_aggs_count + missing_count
    used_rows = len(valid_series)

    if used_rows == 0:
        raise ValueError(f"선택한 열 '{col}'에 유효한 숫자 데이터가 없습니다.")

    stats_data = [
        {"metric": "유효 데이터 수 (Count)", "value": used_rows},
        {"metric": "평균 (Mean)", "value": round(float(valid_series.mean()), 4)},
        {"metric": "표준편차 (Std Dev)", "value": round(float(valid_series.std()), 4)},
        {"metric": "중앙값 (Median)", "value": round(float(valid_series.median()), 4)},
        {"metric": "최솟값 (Min)", "value": round(float(valid_series.min()), 4)},
        {"metric": "25% 백분위수 (Q1)", "value": round(float(valid_series.quantile(0.25)), 4)},
        {"metric": "75% 백분위수 (Q3)", "value": round(float(valid_series.quantile(0.75)), 4)},
        {"metric": "최댓값 (Max)", "value": round(float(valid_series.max()), 4)},
    ]

    reasons = []
    if excluded_aggs_count > 0:
        reasons.append(f"집계 행 {excluded_aggs_count}건 제외")
    if missing_count > 0:
        reasons.append(f"결측치 {missing_count}건 제외")
    exclusion_reason_str = ", ".join(reasons) if reasons else "제외된 행 없음"

    return {
        "tool": "describe_numeric",
        "title": f"'{col}' 기술 통계 요약",
        "summary": f"'{col}' 기준 {used_rows}개 항목의 평균은 {valid_series.mean():.2f}, 중앙값은 {valid_series.median():.2f}입니다.",
        "table": clean_for_json(stats_data),
        "reference_period": str(col),
        "used_rows": used_rows,
        "excluded_rows": total_excluded,
        "exclusion_reason": exclusion_reason_str,
        "used_columns": [col],
        "unit": "수치 (지표 단위)",
        "caution": "극단적 이상치가 존재하는 경우 평균이 크게 왜곡될 수 있으므로 중앙값도 함께 확인해야 합니다."
    }

# -------------------------------------------------------------
# 도구 6: trend_line (선택 항목들의 연도별 추이 - 선 차트)
# -------------------------------------------------------------
def trend_line(df, params=None):
    params = params or {}
    total_rows = len(df)
    label_col = find_label_column(df, params.get("label_column"))
    year_cols = find_year_columns(df)
    
    if not year_cols:
        raise ValueError("시계열 추이를 분석할 연도 열을 찾을 수 없습니다.")

    start_year = params.get("start_year", year_cols[0])
    end_year = params.get("end_year", year_cols[-1])
    selected_years = [y for y in year_cols if str(start_year) <= y <= str(end_year)]

    target_items = params.get("items")
    if not target_items:
        available_names = df[label_col].dropna().astype(str).tolist()
        priority_keywords = ["Korea, Rep.", "United States", "Japan", "Germany", "World"]
        target_items = [p for p in priority_keywords if p in available_names]
        if not target_items:
            target_items = available_names[:5]

    sub_df = df[df[label_col].isin(target_items)].copy()
    used_rows = len(sub_df)
    excluded_rows = total_rows - used_rows

    datasets = []
    table_rows = []

    for _, row in sub_df.iterrows():
        item_name = str(row[label_col])
        values = []
        for yr in selected_years:
            val = pd.to_numeric(row[yr], errors="coerce")
            values.append(None if pd.isna(val) else round(float(val), 2))
            table_rows.append({
                "item": item_name,
                "year": yr,
                "value": None if pd.isna(val) else round(float(val), 2)
            })
        datasets.append({
            "label": item_name,
            "data": values
        })

    return {
        "tool": "trend_line",
        "title": f"선택 항목 연도별 시계열 추이 ({selected_years[0]}~{selected_years[-1]})",
        "summary": f"{', '.join(target_items)} 등 {len(target_items)}개 항목의 {len(selected_years)}개년 추이를 분석했습니다.",
        "table": clean_for_json(table_rows[:30]),
        "chart_data": {
            "type": "line",
            "labels": selected_years,
            "datasets": datasets
        },
        "reference_period": f"{selected_years[0]}~{selected_years[-1]}",
        "used_rows": used_rows,
        "excluded_rows": excluded_rows,
        "exclusion_reason": f"선택된 {len(target_items)}개 분석 대상 외 다른 {excluded_rows}개 행은 제외되었습니다.",
        "used_columns": [label_col] + selected_years,
        "unit": "수치 (지표 단위)",
        "caution": "특정 연도의 결측치로 인해 선 차트의 연결선이 끊기거나 왜곡되어 보일 수 있습니다."
    }

# -------------------------------------------------------------
# 도구 7: top_bottom_n (기준연도 기준 상위·하위 N - 수평 막대)
# -------------------------------------------------------------
def top_bottom_n(df, params=None):
    params = params or {}
    
    ref_period = params.get("reference_period")
    if not ref_period:
        raise ValueError("[오류] top_bottom_n 도구는 'reference_period'(기준 시점)가 필수 파라미터입니다.")

    val_col = str(ref_period).strip()
    if val_col not in df.columns:
        raise ValueError(f"[오류] 데이터에 기준 시점 열 '{val_col}'이 존재하지 않습니다.")

    label_col = find_label_column(df, params.get("label_column"))
    n = int(params.get("n", 10))
    exclude_aggs = params.get("exclude_aggregates", True)

    sub_df = df[[label_col, val_col]].copy()
    sub_df[val_col] = pd.to_numeric(sub_df[val_col], errors="coerce")

    excluded_aggs_cnt = 0
    if exclude_aggs:
        agg_mask = filter_aggregates(sub_df, label_col)
        excluded_aggs_cnt = int(agg_mask.sum())
        sub_df = sub_df[~agg_mask]

    initial_valid_cnt = len(sub_df)
    sub_df = sub_df.dropna(subset=[val_col])
    missing_cnt = initial_valid_cnt - len(sub_df)
    
    used_rows = len(sub_df)
    total_excluded = excluded_aggs_cnt + missing_cnt

    if used_rows == 0:
        raise ValueError(f"기준 시점 '{ref_period}'에 유효한 값이 있는 행이 없습니다.")

    sorted_df = sub_df.sort_values(by=val_col, ascending=False)
    top_df = sorted_df.head(n).copy()
    bottom_df = sorted_df.tail(n).copy()

    table_records = []
    for rank, (_, row) in enumerate(top_df.iterrows(), 1):
        table_records.append({
            "group": f"상위 {n}",
            "rank": rank,
            "name": str(row[label_col]),
            "value": round(float(row[val_col]), 2)
        })

    # [핵심 기능] 사용자가 비교를 원하는 특정 항목(예: 한국)이 상위 N개 밖에 있더라도 표와 차트에 특별 포함
    include_items = params.get("include_items") or []
    if isinstance(include_items, str):
        include_items = [include_items]

    chart_labels = [str(r[label_col]) for _, r in top_df.iterrows()]
    chart_data_values = [round(float(r[val_col]), 2) for _, r in top_df.iterrows()]
    highlighted_summaries = []

    if include_items:
        sorted_full = sub_df.sort_values(by=val_col, ascending=False).reset_index(drop=True)
        sorted_full["Actual_Rank"] = sorted_full.index + 1

        for item_key in include_items:
            match = sorted_full[sorted_full[label_col].str.contains(item_key.split(",")[0].strip(), case=False, na=False)]
            if not match.empty:
                m_row = match.iloc[0]
                m_name = str(m_row[label_col])
                m_rank = int(m_row["Actual_Rank"])
                m_val = round(float(m_row[val_col]), 2)

                # 상위 N개에 이미 없으면 추가 행 및 차트 라벨 삽입
                if m_name not in top_df[label_col].values:
                    table_records.append({
                        "group": f"비교 대상 (전체 {m_rank}위)",
                        "rank": m_rank,
                        "name": f"★ {m_name} (비교)",
                        "value": m_val
                    })
                    chart_labels.append(f"★ {m_name} ({m_rank}위)")
                    chart_data_values.append(m_val)
                    highlighted_summaries.append(f"비교 대상인 '{m_name}'은(는) 전체 {m_rank}위({m_val:.2f})")

    for rank, (_, row) in enumerate(bottom_df.iterrows(), 1):
        table_records.append({
            "group": f"하위 {n}",
            "rank": rank,
            "name": str(row[label_col]),
            "value": round(float(row[val_col]), 2)
        })

    reasons = []
    if excluded_aggs_cnt > 0:
        reasons.append(f"집계 행 {excluded_aggs_cnt}건 제외")
    if missing_cnt > 0:
        reasons.append(f"기준연도({ref_period}) 결측치 {missing_cnt}건 제외")
    exclusion_reason_str = ", ".join(reasons) if reasons else "제외된 행 없음"

    summary_text = f"{ref_period}년 기준 1위는 '{top_df.iloc[0][label_col]}'({top_df.iloc[0][val_col]:.2f})이며, 하위 1위는 '{bottom_df.iloc[-1][label_col]}'({bottom_df.iloc[-1][val_col]:.2f})입니다."
    if highlighted_summaries:
        summary_text = f"{ref_period}년 기준 1위는 '{top_df.iloc[0][label_col]}'({top_df.iloc[0][val_col]:.2f})이며, {', '.join(highlighted_summaries)}입니다."

    return {
        "tool": "top_bottom_n",
        "title": f"{ref_period}년 기준 상위 {n}위 및 비교 분석",
        "summary": summary_text,
        "table": clean_for_json(table_records),
        "chart_data": {
            "type": "bar",
            "indexAxis": "y",
            "labels": chart_labels,
            "datasets": [
                {
                    "label": f"{ref_period}년 수치",
                    "data": chart_data_values
                }
            ]
        },
        "reference_period": str(ref_period),
        "used_rows": used_rows,
        "excluded_rows": total_excluded,
        "exclusion_reason": exclusion_reason_str,
        "used_columns": [label_col, val_col],
        "unit": "수치 (지표 단위)",
        "caution": "특정 소국이나 표본 수가 적은 항목이 최상위/최하위에 포진될 수 있으므로 맥락 확인이 필요합니다."
    }

# -------------------------------------------------------------
# 도구 8: group_summary (그룹별 평균·합계·개수 - 막대 차트)
# -------------------------------------------------------------
def group_summary(df, params=None):
    params = params or {}
    
    ref_period = params.get("reference_period")
    if not ref_period:
        raise ValueError("[오류] group_summary 도구는 'reference_period'(기준 시점)가 필수 파라미터입니다.")

    val_col = str(ref_period).strip()
    if val_col not in df.columns:
        raise ValueError(f"[오류] 데이터에 기준 시점 열 '{val_col}'이 존재하지 않습니다.")

    label_col = find_label_column(df, params.get("label_column"))
    exclude_aggs = params.get("exclude_aggregates", True)

    group_col = params.get("group_column")
    if not group_col or group_col not in df.columns:
        for c in df.columns:
            c_low = str(c).lower()
            if any(k in c_low for k in ["region", "income", "group", "continent", "type"]):
                group_col = c
                break
    
    sub_df = df.copy()
    excluded_aggs_cnt = 0
    if exclude_aggs and label_col in sub_df.columns:
        agg_mask = filter_aggregates(sub_df, label_col)
        excluded_aggs_cnt = int(agg_mask.sum())
        sub_df = sub_df[~agg_mask]

    if not group_col or group_col not in sub_df.columns:
        code_col = "Country Code" if "Country Code" in sub_df.columns else label_col
        sub_df["_AutoGroup"] = sub_df[code_col].astype(str).str[0].str.upper()
        group_col = "_AutoGroup"

    sub_df[val_col] = pd.to_numeric(sub_df[val_col], errors="coerce")
    initial_count = len(sub_df)
    sub_df = sub_df.dropna(subset=[val_col])
    missing_cnt = initial_count - len(sub_df)

    used_rows = len(sub_df)
    total_excluded = excluded_aggs_cnt + missing_cnt

    if used_rows == 0:
        raise ValueError(f"기준 시점 '{ref_period}'에 유효한 값이 없습니다.")

    grouped = sub_df.groupby(group_col)[val_col].agg(["mean", "sum", "count"]).reset_index()
    grouped = grouped.sort_values(by="mean", ascending=False)

    table_records = []
    labels = []
    means = []
    for _, r in grouped.iterrows():
        g_name = str(r[group_col])
        m_val = round(float(r["mean"]), 2)
        s_val = round(float(r["sum"]), 2)
        c_val = int(r["count"])
        labels.append(g_name)
        means.append(m_val)
        table_records.append({
            "group": g_name,
            "mean": m_val,
            "sum": s_val,
            "count": c_val
        })

    reasons = []
    if excluded_aggs_cnt > 0:
        reasons.append(f"집계 행 {excluded_aggs_cnt}건 제외")
    if missing_cnt > 0:
        reasons.append(f"결측치 {missing_cnt}건 제외")
    exclusion_reason_str = ", ".join(reasons) if reasons else "제외된 행 없음"

    return {
        "tool": "group_summary",
        "title": f"'{group_col}' 그룹별 {ref_period}년 지표 집계",
        "summary": f"총 {len(grouped)}개 그룹 중 '{grouped.iloc[0][group_col]}' 그룹의 평균이 {grouped.iloc[0]['mean']:.2f}로 가장 높습니다.",
        "table": clean_for_json(table_records),
        "chart_data": {
            "type": "bar",
            "labels": labels,
            "datasets": [
                {
                    "label": f"{ref_period}년 그룹별 평균",
                    "data": means
                }
            ]
        },
        "reference_period": str(ref_period),
        "used_rows": used_rows,
        "excluded_rows": total_excluded,
        "exclusion_reason": exclusion_reason_str,
        "used_columns": [group_col, val_col],
        "unit": "수치 (지표 단위)",
        "caution": "그룹 간 표본 수(count) 차이가 클 경우 소수 표본 그룹의 평균이 과대평가될 수 있습니다."
    }

# -------------------------------------------------------------
# 도구 9: change_rate (두 시점 사이 변화량·변화율 - 막대 차트)
# -------------------------------------------------------------
def change_rate(df, params=None):
    """
    기준 시점과 비교 시작 시점을 받아 항목별 절대 변화량 및 백분율 변화율을 계산합니다.
    """
    params = params or {}
    ref_period = params.get("reference_period")
    if not ref_period:
        raise ValueError("[오류] change_rate 도구는 'reference_period'(기준 시점)가 필수 파라미터입니다.")

    year_cols = find_year_columns(df)
    start_period = params.get("start_period")
    if not start_period:
        # 기준 시점보다 5년 또는 10년 전, 혹은 첫 번째 유효 연도 자동 지정
        idx = year_cols.index(str(ref_period)) if str(ref_period) in year_cols else len(year_cols) - 1
        start_idx = max(0, idx - 5)
        start_period = year_cols[start_idx]

    start_col, end_col = str(start_period), str(ref_period)
    if start_col not in df.columns or end_col not in df.columns:
        raise ValueError(f"[오류] 데이터에 비교할 시점 열('{start_col}' 또는 '{end_col}')이 없습니다.")

    label_col = find_label_column(df, params.get("label_column"))
    exclude_aggs = params.get("exclude_aggregates", True)

    sub_df = df[[label_col, start_col, end_col]].copy()
    sub_df[start_col] = pd.to_numeric(sub_df[start_col], errors="coerce")
    sub_df[end_col] = pd.to_numeric(sub_df[end_col], errors="coerce")

    excluded_aggs_cnt = 0
    if exclude_aggs:
        agg_mask = filter_aggregates(sub_df, label_col)
        excluded_aggs_cnt = int(agg_mask.sum())
        sub_df = sub_df[~agg_mask]

    # 두 시점 모두 값이 있는 행만 계산 (하나라도 결측이면 제외)
    init_cnt = len(sub_df)
    valid_df = sub_df.dropna(subset=[start_col, end_col]).copy()
    missing_cnt = init_cnt - len(valid_df)

    used_rows = len(valid_df)
    total_excluded = excluded_aggs_cnt + missing_cnt

    if used_rows == 0:
        raise ValueError(f"두 시점({start_col}, {end_col})에 동시에 값이 존재하는 행이 없습니다.")

    # 변화량(diff)과 변화율(pct)
    valid_df["diff"] = valid_df[end_col] - valid_df[start_col]
    valid_df["pct_change"] = np.where(
        valid_df[start_col] != 0,
        ((valid_df[end_col] - valid_df[start_col]) / valid_df[start_col]) * 100,
        np.nan
    )

    # 변화량 기준 상위 10개 정렬
    sorted_df = valid_df.sort_values(by="diff", ascending=False)
    top_change = sorted_df.head(10)

    table_records = []
    for _, r in sorted_df.head(20).iterrows():
        table_records.append({
            "name": str(r[label_col]),
            "start_value": round(float(r[start_col]), 2),
            "end_value": round(float(r[end_col]), 2),
            "change_diff": round(float(r["diff"]), 2),
            "change_rate_pct": None if pd.isna(r["pct_change"]) else round(float(r["pct_change"]), 2)
        })

    chart_labels = [str(r[label_col]) for _, r in top_change.iterrows()]
    chart_data_diff = [round(float(r["diff"]), 2) for _, r in top_change.iterrows()]

    reasons = []
    if excluded_aggs_cnt > 0:
        reasons.append(f"집계 행 {excluded_aggs_cnt}건 제외")
    if missing_cnt > 0:
        reasons.append(f"두 시점 중 한 곳 이상 결측인 행 {missing_cnt}건 제외")
    exclusion_reason_str = ", ".join(reasons) if reasons else "제외된 행 없음"

    return {
        "tool": "change_rate",
        "title": f"{start_col}년 대비 {end_col}년 변화량 및 변화율 분석",
        "summary": f"{start_col}년 대비 {end_col}년 기준 {used_rows}개 항목 중 '{top_change.iloc[0][label_col]}'이(가) +{top_change.iloc[0]['diff']:.2f}p로 가장 큰 폭의 성장을 기록했습니다.",
        "table": clean_for_json(table_records),
        "chart_data": {
            "type": "bar",
            "labels": chart_labels,
            "datasets": [
                {
                    "label": f"{start_col}→{end_col} 변화량(p)",
                    "data": chart_data_diff
                }
            ]
        },
        "reference_period": f"{start_col} vs {end_col}",
        "used_rows": used_rows,
        "excluded_rows": total_excluded,
        "exclusion_reason": exclusion_reason_str,
        "used_columns": [label_col, start_col, end_col],
        "unit": "수치 차이(포인트/%)",
        "caution": "시작 시점 수치가 매우 작은 경우 백분율 변화율이 비정상적으로 높게 산출될 수 있으므로 절대 변화량도 반드시 함께 고려해야 합니다."
    }

# -------------------------------------------------------------
# 도구 10: distribution (구간별 분포 - 히스토그램)
# -------------------------------------------------------------
def distribution(df, params=None):
    """
    기준 시점을 필수로 받아 수치 데이터의 구간별 빈도(히스토그램)를 생성합니다.
    """
    params = params or {}
    ref_period = params.get("reference_period")
    if not ref_period:
        raise ValueError("[오류] distribution 도구는 'reference_period'(기준 시점)가 필수 파라미터입니다.")

    val_col = str(ref_period).strip()
    if val_col not in df.columns:
        raise ValueError(f"[오류] 데이터에 기준 시점 열 '{val_col}'이 존재하지 않습니다.")

    label_col = find_label_column(df, params.get("label_column"))
    exclude_aggs = params.get("exclude_aggregates", True)
    bins_count = int(params.get("bins", 8))

    sub_df = df[[label_col, val_col]].copy()
    sub_df[val_col] = pd.to_numeric(sub_df[val_col], errors="coerce")

    excluded_aggs_cnt = 0
    if exclude_aggs:
        agg_mask = filter_aggregates(sub_df, label_col)
        excluded_aggs_cnt = int(agg_mask.sum())
        sub_df = sub_df[~agg_mask]

    init_cnt = len(sub_df)
    sub_df = sub_df.dropna(subset=[val_col])
    missing_cnt = init_cnt - len(sub_df)

    used_rows = len(sub_df)
    total_excluded = excluded_aggs_cnt + missing_cnt

    if used_rows == 0:
        raise ValueError(f"기준 시점 '{ref_period}'에 유효한 값이 없습니다.")

    min_val = float(sub_df[val_col].min())
    max_val = float(sub_df[val_col].max())

    # 동일 값만 있는 경우 방어
    if min_val == max_val:
        bins = [min_val - 1, min_val + 1]
    else:
        bins = np.linspace(min_val, max_val, bins_count + 1)

    cut_series = pd.cut(sub_df[val_col], bins=bins, include_lowest=True)
    counts = cut_series.value_counts(sort=False)

    table_records = []
    labels = []
    data_counts = []

    for interval, count in counts.items():
        interval_label = f"{interval.left:.1f} ~ {interval.right:.1f}"
        pct = round((count / used_rows * 100), 2)
        labels.append(interval_label)
        data_counts.append(int(count))
        table_records.append({
            "bin_range": interval_label,
            "frequency_count": int(count),
            "ratio_pct": pct
        })

    reasons = []
    if excluded_aggs_cnt > 0:
        reasons.append(f"집계 행 {excluded_aggs_cnt}건 제외")
    if missing_cnt > 0:
        reasons.append(f"기준연도({ref_period}) 결측치 {missing_cnt}건 제외")
    exclusion_reason_str = ", ".join(reasons) if reasons else "제외된 행 없음"

    return {
        "tool": "distribution",
        "title": f"{ref_period}년 지표 수치 분포 (히스토그램)",
        "summary": f"{used_rows}개 항목의 수치는 {min_val:.1f}부터 {max_val:.1f} 범위에 걸쳐 있으며, 가장 많은 항목이 몰린 구간은 '{counts.idxmax().left:.1f} ~ {counts.idxmax().right:.1f}'({counts.max()}개 항목)입니다.",
        "table": clean_for_json(table_records),
        "chart_data": {
            "type": "bar",
            "labels": labels,
            "datasets": [
                {
                    "label": f"{ref_period}년 항목 수(빈도)",
                    "data": data_counts
                }
            ]
        },
        "reference_period": str(ref_period),
        "used_rows": used_rows,
        "excluded_rows": total_excluded,
        "exclusion_reason": exclusion_reason_str,
        "used_columns": [val_col],
        "unit": "개수(빈도)",
        "caution": "구간 수(bins)의 크기에 따라 분포 형태가 달라질 수 있으므로 치우침(Skewness) 여부를 함께 파악해야 합니다."
    }

# -------------------------------------------------------------
# 도구 11: correlation_scatter (두 숫자 열 상관계수 - 산점도)
# -------------------------------------------------------------
def correlation_scatter(df, params=None):
    """
    기준 시점과 비교 시점(또는 두 숫자 열) 간의 피어슨 상관계수를 계산하고 산점도 차트 데이터를 생성합니다.
    """
    params = params or {}
    ref_period = params.get("reference_period")
    if not ref_period:
        raise ValueError("[오류] correlation_scatter 도구는 'reference_period'(기준 시점)가 필수 파라미터입니다.")

    col1 = str(ref_period).strip()
    col2 = params.get("compare_column")
    
    # compare_column이 지정되지 않은 경우 기준 시점 5년 또는 10년 전 시점 자동 선정
    if not col2:
        year_cols = find_year_columns(df)
        if col1 in year_cols:
            idx = year_cols.index(col1)
            prev_idx = max(0, idx - 5)
            col2 = year_cols[prev_idx]
        else:
            numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != col1]
            if numeric_cols:
                col2 = numeric_cols[0]
            else:
                raise ValueError("비교할 두 번째 숫자 열을 찾을 수 없습니다.")

    col2 = str(col2).strip()
    if col1 not in df.columns or col2 not in df.columns:
        raise ValueError(f"[오류] 데이터에 비교 대상 열('{col1}', '{col2}')이 존재하지 않습니다.")

    label_col = find_label_column(df, params.get("label_column"))
    exclude_aggs = params.get("exclude_aggregates", True)

    sub_df = df[[label_col, col1, col2]].copy()
    sub_df[col1] = pd.to_numeric(sub_df[col1], errors="coerce")
    sub_df[col2] = pd.to_numeric(sub_df[col2], errors="coerce")

    excluded_aggs_cnt = 0
    if exclude_aggs:
        agg_mask = filter_aggregates(sub_df, label_col)
        excluded_aggs_cnt = int(agg_mask.sum())
        sub_df = sub_df[~agg_mask]

    init_cnt = len(sub_df)
    valid_df = sub_df.dropna(subset=[col1, col2])
    missing_cnt = init_cnt - len(valid_df)

    used_rows = len(valid_df)
    total_excluded = excluded_aggs_cnt + missing_cnt

    if used_rows < 3:
        raise ValueError("상관계수를 계산하기 위한 유효한 데이터 쌍이 최소 3개 이상 필요합니다.")

    # 피어슨 상관계수
    corr_coef = float(valid_df[col1].corr(valid_df[col2]))

    # 상관 강도 해석 텍스트
    abs_corr = abs(corr_coef)
    if abs_corr >= 0.8:
        strength = "매우 강한 상관관계"
    elif abs_corr >= 0.6:
        strength = "강한 상관관계"
    elif abs_corr >= 0.4:
        strength = "보통의 상관관계"
    else:
        strength = "약하거나 거의 없는 상관관계"

    direction = "양(+)" if corr_coef >= 0 else "음(-)"

    # 산점도 차트 데이터 (x: col2, y: col1)
    scatter_points = []
    for _, r in valid_df.iterrows():
        scatter_points.append({
            "x": round(float(r[col2]), 2),
            "y": round(float(r[col1]), 2),
            "label": str(r[label_col])
        })

    summary_table = [
        {"metric": "분석 대상 X축 열", "value": col2},
        {"metric": "분석 대상 Y축 열", "value": col1},
        {"metric": "유효 데이터 쌍(건수)", "value": used_rows},
        {"metric": "피어슨 상관계수 (r)", "value": round(corr_coef, 4)},
        {"metric": "상관관계 평가", "value": f"{direction}의 {strength}"}
    ]

    reasons = []
    if excluded_aggs_cnt > 0:
        reasons.append(f"집계 행 {excluded_aggs_cnt}건 제외")
    if missing_cnt > 0:
        reasons.append(f"두 변수 중 결측치 보유 행 {missing_cnt}건 제외")
    exclusion_reason_str = ", ".join(reasons) if reasons else "제외된 행 없음"

    return {
        "tool": "correlation_scatter",
        "title": f"'{col2}'와 '{col1}' 상관계수 및 산점도",
        "summary": f"'{col2}'와 '{col1}'의 상관계수(r)는 {corr_coef:.4f}로 {direction}의 {strength}를 나타냅니다.",
        "table": clean_for_json(summary_table),
        "correlation_coefficient": round(corr_coef, 4),
        "chart_data": {
            "type": "scatter",
            "datasets": [
                {
                    "label": f"{col2} vs {col1}",
                    "data": scatter_points
                }
            ]
        },
        "reference_period": f"{col2} & {col1}",
        "used_rows": used_rows,
        "excluded_rows": total_excluded,
        "exclusion_reason": exclusion_reason_str,
        "used_columns": [col2, col1],
        "unit": "상관계수(-1.0 ~ +1.0)",
        # [절대 규칙 필수 포함 문구]
        "caution": "※ 반드시 주의: 상관관계는 인과관계가 아닙니다. 두 변수가 같은 방향으로 변한다고 해서 한쪽이 다른 쪽의 원인이 됨을 의미하지 않습니다."
    }

# -------------------------------------------------------------
# 도구 12: compare_one_vs_all (특정 항목 vs 전체 평균·중앙값 - 강조 막대)
# -------------------------------------------------------------
def compare_one_vs_all(df, params=None):
    """
    기준 시점을 필수로 받아, 특정 항목 1개의 값과 전체 평균 및 중앙값을 비교합니다.
    """
    params = params or {}
    ref_period = params.get("reference_period")
    if not ref_period:
        raise ValueError("[오류] compare_one_vs_all 도구는 'reference_period'(기준 시점)가 필수 파라미터입니다.")

    val_col = str(ref_period).strip()
    if val_col not in df.columns:
        raise ValueError(f"[오류] 데이터에 기준 시점 열 '{val_col}'이 존재하지 않습니다.")

    label_col = find_label_column(df, params.get("label_column"))
    exclude_aggs = params.get("exclude_aggregates", True)

    sub_df = df[[label_col, val_col]].copy()
    sub_df[val_col] = pd.to_numeric(sub_df[val_col], errors="coerce")

    excluded_aggs_cnt = 0
    if exclude_aggs:
        agg_mask = filter_aggregates(sub_df, label_col)
        excluded_aggs_cnt = int(agg_mask.sum())
        sub_df = sub_df[~agg_mask]

    init_cnt = len(sub_df)
    sub_df = sub_df.dropna(subset=[val_col])
    missing_cnt = init_cnt - len(sub_df)

    used_rows = len(sub_df)
    total_excluded = excluded_aggs_cnt + missing_cnt

    if used_rows == 0:
        raise ValueError(f"기준 시점 '{ref_period}'에 유효한 값이 없습니다.")

    # 특정 비교 대상 항목 결정 (기본: Korea, Rep. 또는 첫 번째 항목)
    target_item = params.get("target_item")
    if not target_item:
        if "Korea, Rep." in sub_df[label_col].values:
            target_item = "Korea, Rep."
        else:
            target_item = str(sub_df.iloc[0][label_col])

    target_match = sub_df[sub_df[label_col] == target_item]
    if target_match.empty:
        raise ValueError(f"선택한 항목 '{target_item}'을(를) 데이터에서 찾을 수 없습니다.")

    target_val = float(target_match.iloc[0][val_col])
    mean_val = float(sub_df[val_col].mean())
    median_val = float(sub_df[val_col].median())

    diff_from_mean = target_val - mean_val
    diff_from_median = target_val - median_val

    # 백분위 순위 (Percentile)
    percentile_rank = (sub_df[val_col] < target_val).mean() * 100

    table_records = [
        {"comparison_target": f"선택 항목: {target_item}", "value": round(target_val, 2), "difference": 0.0},
        {"comparison_target": "전체 평균 (Mean)", "value": round(mean_val, 2), "difference": round(diff_from_mean, 2)},
        {"comparison_target": "전체 중앙값 (Median)", "value": round(median_val, 2), "difference": round(diff_from_median, 2)},
        {"comparison_target": "상대적 백분위 순위", "value": round(percentile_rank, 1), "difference": None}
    ]

    chart_labels = [target_item, "전체 평균", "전체 중앙값"]
    chart_values = [round(target_val, 2), round(mean_val, 2), round(median_val, 2)]

    reasons = []
    if excluded_aggs_cnt > 0:
        reasons.append(f"집계 행 {excluded_aggs_cnt}건 제외")
    if missing_cnt > 0:
        reasons.append(f"결측치 {missing_cnt}건 제외")
    exclusion_reason_str = ", ".join(reasons) if reasons else "제외된 행 없음"

    return {
        "tool": "compare_one_vs_all",
        "title": f"'{target_item}' vs 전체 평균·중앙값 비교 ({ref_period}년)",
        "summary": f"{ref_period}년 기준 '{target_item}'의 수치는 {target_val:.2f}로 전체 평균({mean_val:.2f})보다 {abs(diff_from_mean):.2f}p {'높으며' if diff_from_mean >= 0 else '낮으며'}, 상위 {100 - percentile_rank:.1f}%에 위치합니다.",
        "table": clean_for_json(table_records),
        "chart_data": {
            "type": "bar",
            "labels": chart_labels,
            "datasets": [
                {
                    "label": f"{ref_period}년 수치 비교",
                    "data": chart_values
                }
            ]
        },
        "reference_period": str(ref_period),
        "used_rows": used_rows,
        "excluded_rows": total_excluded,
        "exclusion_reason": exclusion_reason_str,
        "used_columns": [label_col, val_col],
        "unit": "수치 (지표 단위)",
        "caution": "전체 분포가 비대칭일 경우 평균보다는 중앙값과의 차이를 기준으로 해석하는 것이 왜곡을 줄입니다."
    }

# -------------------------------------------------------------
# 12개 도구 전체 카탈로그 매핑 (tools 레지스트리)
# -------------------------------------------------------------
TOOL_CATALOG = {
    "reshape_wide_to_long": reshape_wide_to_long,
    "quality_report": quality_report,
    "year_coverage": year_coverage,
    "detect_aggregates": detect_aggregates,
    "describe_numeric": describe_numeric,
    "trend_line": trend_line,
    "top_bottom_n": top_bottom_n,
    "group_summary": group_summary,
    "change_rate": change_rate,
    "distribution": distribution,
    "correlation_scatter": correlation_scatter,
    "compare_one_vs_all": compare_one_vs_all,
}
