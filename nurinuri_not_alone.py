import streamlit as st
import pandas as pd
import plotly.express as px
import io
import requests
import numpy as np
import re

st.set_page_config(page_title="독거노인 대비 의료기관 분포 분석", layout="wide")
st.title("🏥 지역별 독거노인 인구 대비 의료기관 분포 분석 (보로노이 개념 기반)")

st.markdown("""
이 앱은 **독거노인 인구수**와 **의료기관 수**를 비교하여  
보로노이 개념 기반의 **의료 접근성 점수**를 계산합니다.

- 🟥 **빨간색**: 의료 접근성이 낮음 (독거노인 대비 의료기관 부족)  
- 🟩 **초록색**: 의료 접근성이 높음 (의료기관이 충분하거나 집중 분포)
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
    def normalize_region(name):
        name = str(name)
        name = re.sub(r'\(.*?\)', '', name)  # 괄호 제거
        name = re.sub(r'[^가-힣]', '', name)  # 한글 외 문자 제거
        mapping = {
            "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시",
            "인천": "인천광역시", "광주": "광주광역시", "대전": "대전광역시",
            "울산": "울산광역시", "세종": "세종특별자치시", "경기": "경기도",
            "강원": "강원도", "충북": "충청북도", "충청북": "충청북도",
            "충남": "충청남도", "충청남": "충청남도", "전북": "전라북도",
            "전남": "전라남도", "경북": "경상북도", "경상북": "경상북도",
            "경남": "경상남도", "경상남": "경상남도", "제주": "제주특별자치도"
        }
        for key, val in mapping.items():
            if name.startswith(key):
                return val
        # 예: "충청북도청주시" → "충청북도"
        for key, val in mapping.items():
            if key in name:
                return val
        return name

    # -----------------------------
    # 🧭 독거노인 지역 추출
    # -----------------------------
    elder_region_col = [c for c in df_elder.columns if "지역" in c or "시도" in c or "행정구역" in c]
    if elder_region_col:
        elder_region = elder_region_col[0]
    else:
        elder_region = st.selectbox("독거노인 지역 컬럼 선택", df_elder.columns)

    df_elder["지역"] = df_elder[elder_region].astype(str).apply(normalize_region)

    # 독거노인 관련 컬럼 찾기
    elder_candidates = [c for c in df_elder.columns if "독거" in c or "인구" in c or "가구비율" in c]
    elder_candidates = [c for c in elder_candidates if "지역" not in c]

    if elder_candidates:
        target_col = st.selectbox("독거노인 인구 컬럼 선택", elder_candidates)
    else:
        st.error("❌ 독거노인 인구 관련 컬럼을 찾을 수 없습니다.")
        st.stop()

    df_elder[target_col] = pd.to_numeric(df_elder[target_col], errors="coerce").fillna(0)

    # -----------------------------
    # 🏥 의료기관 지역 추출
    # -----------------------------
    fac_region_col = [c for c in df_facility.columns if "주소" in c or "지역" in c or "시도" in c]
    if fac_region_col:
        fac_region = fac_region_col[0]
    else:
        fac_region = st.selectbox("의료기관 지역 컬럼 선택", df_facility.columns)

    df_facility["지역"] = df_facility[fac_region].astype(str).apply(normalize_region)

    # -----------------------------
    # 🧮 지역별 의료기관 수
    # -----------------------------
    df_facility_grouped = df_facility.groupby("지역").size().reset_index(name="의료기관_수")

    # -----------------------------
    # 🔗 병합
    # -----------------------------
    df = pd.merge(df_elder, df_facility_grouped, on="지역", how="inner")

    # -----------------------------
    # 📏 보로노이 개념 접근성 점수 계산
    # -----------------------------
    df["의료기관_비율"] = df["의료기관_수"] / (df[target_col].replace(0, 1))
    df["의료_접근성_점수"] = np.log1p(df["의료기관_비율"]) * 100

    st.subheader("📈 병합 및 접근성 결과")
    st.dataframe(df[["지역", target_col, "의료기관_수", "의료_접근성_점수"]])

    # -----------------------------
    # 🗺️ 지도 시각화
    # -----------------------------
    geojson_url = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2013/json/skorea_provinces_geo_simple.json"
    geojson = requests.get(geojson_url).json()

    fig = px.choropleth(
        df,
        geojson=geojson,
        locations="지역",
        featureidkey="properties.name",
        color="의료_접근성_점수",
        color_continuous_scale="RdYlGn",
        title="시도별 독거노인 대비 의료 접근성 점수 (보로노이 개념 기반)",
        range_color=(df["의료_접근성_점수"].min(), df["의료_접근성_점수"].max())
    )

    fig.update_geos(fitbounds="locations", visible=False, bgcolor="#f5f5f5")
    st.plotly_chart(fig, use_container_width=True)

else:
    st.info("👆 사이드바에서 두 개의 파일을 모두 업로드해주세요.")
