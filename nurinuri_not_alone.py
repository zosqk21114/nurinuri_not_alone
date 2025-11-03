import streamlit as st
import pandas as pd
import plotly.express as px
import io
import requests
import numpy as np
import re

st.set_page_config(page_title="독거노인 대비 의료 접근성 분석", layout="wide")
st.title("🏥 시·군·구 단위 독거노인 대비 의료 접근성 분석 (보로노이 개념 기반)")

st.markdown("""
이 앱은 **독거노인 관련 인구 데이터**와 **의료기관 분포 데이터**를 결합하여  
보로노이 개념을 기반으로 한 **의료 접근성 점수**를 시군구 단위로 시각화합니다.  

- 🟥 **빨간색**: 의료 접근성이 낮음 (의료기관 부족)  
- 🟩 **초록색**: 의료 접근성이 높음 (의료기관이 충분함)
""")

# -----------------------------
# 📂 파일 업로드
# -----------------------------
st.sidebar.header("📁 데이터 업로드")
elder_file = st.sidebar.file_uploader("독거노인 인구 파일 (CSV 또는 XLSX)", type=["csv", "xlsx"])
facility_file = st.sidebar.file_uploader("의료기관 데이터 파일 (CSV 또는 XLSX)", type=["csv", "xlsx"])

# -----------------------------
# 🔍 파일 읽기 함수
# -----------------------------
def read_any(file):
    if file is None:
        return None
    try:
        if file.name.endswith(".csv"):
            raw = file.read()
            try:
                return pd.read_csv(io.BytesIO(raw), encoding="utf-8")
            except UnicodeDecodeError:
                return pd.read_csv(io.BytesIO(raw), encoding="cp949")
        elif file.name.endswith(".xlsx"):
            return pd.read_excel(file)
    except Exception as e:
        st.error(f"파일 읽기 오류: {e}")
        return None

# -----------------------------
# 📊 파일 로드
# -----------------------------
df_elder = read_any(elder_file)
df_facility = read_any(facility_file)

if df_elder is not None and df_facility is not None:
    st.success("✅ 두 파일 모두 업로드 완료!")

    # -----------------------------
    # 🔠 지역명 정제 함수
    # -----------------------------
    def clean_region_name(name):
        """시군구 매칭을 위한 정제"""
        name = str(name)
        name = re.sub(r'\(.*?\)', '', name)
        name = re.sub(r'[^가-힣\s]', '', name)
        name = name.replace(" ", "")
        return name.strip()

    # -----------------------------
    # 👵 독거노인 데이터 전처리
    # -----------------------------
    region_cols = [c for c in df_elder.columns if any(k in c for k in ["시도", "시군구", "행정", "지역"])]
    region_col = region_cols[-1] if region_cols else st.selectbox("독거노인 지역 컬럼 선택", df_elder.columns)

    df_elder["지역"] = df_elder[region_col].astype(str).apply(clean_region_name)

    # 독거노인 관련 컬럼 탐색 (지역 컬럼 제외)
    elder_candidates = [
        c for c in df_elder.columns
        if any(k in c for k in ["독거", "1인가구", "노인", "고령", "65세", "비율", "인구"])
        and not any(k in c for k in ["시도", "시군구", "지역"])
    ]

    if elder_candidates:
        target_col = st.selectbox("📊 독거노인 관련 인구(또는 비율) 컬럼 선택", elder_candidates)
    else:
        st.warning("🔍 자동 탐색 실패 — 직접 선택해주세요.")
        target_col = st.selectbox("📊 독거노인 관련 인구 컬럼 (직접 선택)", [c for c in df_elder.columns if c not in ["지역"]])

    df_elder[target_col] = pd.to_numeric(df_elder[target_col], errors="coerce").fillna(0)

    # -----------------------------
    # 🏥 의료기관 데이터 전처리
    # -----------------------------
    fac_region_cols = [c for c in df_facility.columns if any(k in c for k in ["주소", "지역", "시도", "시군구"])]
    fac_region_col = fac_region_cols[0] if fac_region_cols else st.selectbox("의료기관 지역 컬럼 선택", df_facility.columns)

    df_facility["지역"] = df_facility[fac_region_col].astype(str).apply(clean_region_name)

    # -----------------------------
    # 🧮 시군구 단위로 그룹화
    # -----------------------------
    df_facility_grouped = df_facility.groupby("지역").size().reset_index(name="의료기관_수")

    # -----------------------------
    # 🔗 병합
    # -----------------------------
    df = pd.merge(df_elder, df_facility_grouped, on="지역", how="inner")

    # -----------------------------
    # 📏 보로노이 개념 기반 접근성 점수 계산
    # -----------------------------
    df["의료기관_비율"] = df["의료기관_수"] / (df[target_col].replace(0, 1))
    df["의료_접근성_점수"] = np.log1p(df["의료기관_비율"]) * 100

    st.subheader("📈 분석 결과 (시·군·구 단위)")
    st.dataframe(df[["지역", target_col, "의료기관_수", "의료_접근성_점수"]])

    # -----------------------------
    # 🗺️ 지도 시각화
    # -----------------------------
    geojson_url = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2013/json/skorea_municipalities_geo_simple.json"
    geojson = requests.get(geojson_url).json()

    # geojson의 지역명 정리
    geo_names = [re.sub(r'[^가-힣]', '', g["properties"]["name"]) for g in geojson["features"]]

    # 데이터 매칭 보정
    df["지역_매칭"] = df["지역"].apply(
        lambda x: next((g for g in geo_names if g in x or x in g), None)
    )

    df_map = df.dropna(subset=["지역_매칭"])

    fig = px.choropleth(
        df_map,
        geojson=geojson,
        locations="지역_매칭",
        featureidkey="properties.name",
        color="의료_접근성_점수",
        color_continuous_scale="RdYlGn",
        title="시·군·구별 독거노인 대비 의료 접근성 점수 (보로노이 개념 기반)",
        range_color=(df_map["의료_접근성_점수"].min(), df_map["의료_접근성_점수"].max())
    )

    fig.update_geos(fitbounds="locations", visible=False, bgcolor="#f5f5f5")
    st.plotly_chart(fig, use_container_width=True)

else:
    st.info("👆 사이드바에서 두 개의 파일을 모두 업로드해주세요.")
