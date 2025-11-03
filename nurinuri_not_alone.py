import streamlit as st
import pandas as pd
import plotly.express as px
import io
import requests
import re

# -----------------------------
# 설정 및 제목
# -----------------------------
st.set_page_config(page_title="독거노인 대비 의료기관 분포 분석", layout="wide")
st.title("🧓 지역별 독거노인 인구 대비 의료기관 분포 분석")

st.markdown("""
이 앱은 **지역별 독거노인 인구수**와 **의료기관 수**를 비교하여
얼마나 고르게 분포되어 있는지를 지도 위에서 시각화합니다.

- **빨간색**: 독거노인 인구 대비 의료기관이 **부족한 지역**
- **초록색**: 독거노인 인구 대비 의료기관이 **많은 지역**
""")

# -----------------------------
# 파일 업로드
# -----------------------------
st.sidebar.header("📂 데이터 업로드")
elder_file = st.sidebar.file_uploader("독거노인 인구 파일 (CSV 또는 XLSX)", type=["csv", "xlsx"])
facility_file = st.sidebar.file_uploader("의료기관 데이터 파일 (CSV 또는 XLSX)", type=["csv", "xlsx"])

# -----------------------------
# 파일 읽기 함수
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
# 파일 로드
# -----------------------------
df_elder = read_any(elder_file)
df_facility = read_any(facility_file)

# -----------------------------
# 데이터 처리
# -----------------------------
if df_elder is not None and df_facility is not None:
    st.success("✅ 두 파일 모두 업로드 완료!")

    # -----------------------------
    # 1️⃣ 독거노인 데이터 전처리
    # -----------------------------
    elder_region_col_candidates = [c for c in df_elder.columns if any(k in c for k in ["시도", "행정구역", "지역", "자치단체"])]
    if elder_region_col_candidates:
        df_elder = df_elder.rename(columns={elder_region_col_candidates[0]: "지역"})
    else:
        st.warning("⚠️ 지역 컬럼을 자동으로 찾지 못했습니다. 직접 선택하세요.")
        selected = st.selectbox("독거노인 데이터 지역 컬럼 선택", df_elder.columns, key="elder_region")
        df_elder = df_elder.rename(columns={selected: "지역"})

    # 독거노인 수 컬럼 탐색
    elder_val_candidates = [c for c in df_elder.columns if any(k in c for k in ["65세", "1인가구", "노인", "고령"]) and "지역" not in c]
    if elder_val_candidates:
        target_col = elder_val_candidates[0]
    else:
        st.warning("⚠️ 독거노인 관련 인구 컬럼을 자동으로 찾지 못했습니다. 직접 선택하세요.")
        target_col = st.selectbox("독거노인 인구 컬럼 선택", [c for c in df_elder.columns if c != "지역"], key="elder_val")

    df_elder = df_elder.dropna(subset=["지역"])
    df_elder = df_elder[df_elder["지역"].astype(str) != "전국"]

    # -----------------------------
    # 2️⃣ 의료기관 데이터 전처리
    # -----------------------------
    facility_region_col_candidates = [c for c in df_facility.columns if any(k in c for k in ["주소", "소재지", "지역", "시도"])]
    if facility_region_col_candidates:
        facility_region = facility_region_col_candidates[0]
    else:
        st.warning("⚠️ 의료기관 지역 컬럼을 자동으로 찾지 못했습니다. 직접 선택하세요.")
        facility_region = st.selectbox("의료기관 지역 컬럼 선택", df_facility.columns, key="facility_region")

    # 주소에서 시도 추출 (예: "서울특별시 강남구 ..." → "서울특별시")
    def extract_province(addr):
        if pd.isna(addr):
            return None
        addr = str(addr)
        match = re.match(r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)", addr)
        if match:
            return match.group(1)
        return None

    df_facility["지역"] = df_facility[facility_region].apply(extract_province)

    # -----------------------------
    # 3️⃣ 지역명 정규화 (두 데이터셋 일치)
    # -----------------------------
    def normalize_region(name):
        mapping = {
            "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
            "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
            "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
            "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도", "경남": "경상남도",
            "제주": "제주특별자치도"
        }
        name = str(name).strip()
        for k, v in mapping.items():
            if name.startswith(k):
                return v
        return name

    df_elder["지역"] = df_elder["지역"].apply(normalize_region)
    df_facility["지역"] = df_facility["지역"].apply(normalize_region)

    # -----------------------------
    # 4️⃣ 병합 및 계산
    # -----------------------------
    df_facility_grouped = df_facility.groupby("지역").size().reset_index(name="의료기관_수")
    df_elder[target_col] = pd.to_numeric(df_elder[target_col], errors="coerce").fillna(0)
    df = pd.merge(df_elder, df_facility_grouped, on="지역", how="inner")

    if df.empty:
        st.error("❌ 병합 결과가 비어 있습니다. 지역명이 일치하지 않습니다.")
        st.write("🔍 독거노인 데이터 지역 목록:", df_elder["지역"].unique())
        st.write("🏥 의료기관 데이터 지역 목록:", df_facility["지역"].unique())
        st.stop()

    df["독거노인_1000명당_의료기관_수"] = (
        df["의료기관_수"] / (df[target_col].replace(0, 1) + 1e-9)
    ) * 1000

    # -----------------------------
    # 5️⃣ 지도 시각화
    # -----------------------------
    geojson_url = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2013/json/skorea_provinces_geo_simple.json"
    geojson = requests.get(geojson_url).json()
    for feature in geojson["features"]:
        if feature["properties"]["name"] == "강원도":
            feature["properties"]["name"] = "강원특별자치도"
        if feature["properties"]["name"] == "전라북도":
            feature["properties"]["name"] = "전북특별자치도"

    mean_ratio = df["독거노인_1000명당_의료기관_수"].mean()

    fig = px.choropleth(
        df,
        geojson=geojson,
        locations="지역",
        featureidkey="properties.name",
        color="독거노인_1000명당_의료기관_수",
        color_continuous_scale="RdYlGn",
        color_continuous_midpoint=mean_ratio,
        title=f"시도별 독거노인 1000명당 의료기관 분포 (전국 평균: {mean_ratio:.2f})",
        hover_data={"지역": True, target_col: True, "의료기관_수": True,
                    "독거노인_1000명당_의료기관_수": ':.2f'}
    )
    fig.update_geos(fitbounds="locations", visible=False, bgcolor="#f5f5f5")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("📊 병합 결과 데이터")
    st.dataframe(df[["지역", target_col, "의료기관_수", "독거노인_1000명당_의료기관_수"]])

else:
    st.info("📥 사이드바에서 두 개의 파일을 모두 업로드해주세요.")
