import streamlit as st
import pandas as pd
import plotly.express as px
import io
import requests

# -----------------------------
# 설정 및 제목
# -----------------------------
st.set_page_config(page_title="독거노인 대비 의료기관 분포 분석", layout="wide")
st.title("🏥 지역별 독거노인 인구 대비 의료기관 분포 분석")

st.markdown("""
이 앱은 **지역별 독거노인 인구수**와 **의료기관 수**를 비교하여  
얼마나 고르게 분포되어 있는지를 지도 위에서 시각화합니다.

- 🟥 **빨간색**: 독거노인 인구 대비 의료기관이 **부족한 지역**  
- 🟩 **초록색**: 독거노인 인구 대비 의료기관이 **많은 지역**
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
        st.error(f"❌ 파일 읽기 오류: {e}")
        return None


# -----------------------------
# 데이터 로드
# -----------------------------
df_elder = read_any(elder_file)
df_facility = read_any(facility_file)

# -----------------------------
# 데이터 전처리 시작
# -----------------------------
if df_elder is not None and df_facility is not None:
    st.success("✅ 두 파일 모두 업로드 완료!")

    # -----------------------------
    # 1️⃣ 독거노인 데이터 전처리
    # -----------------------------
    # 헤더 병합 구조 대응
    if "행정구역별" in df_elder.columns and "2024" in df_elder.columns:
        df_elder.columns = df_elder.iloc[0]
        df_elder = df_elder[1:].reset_index(drop=True)
        df_elder.columns = [str(c).strip() for c in df_elder.columns]

    # 지역 컬럼 자동 탐색
    elder_region_candidates = [
        c for c in df_elder.columns if any(k in c for k in ["시도", "지역", "행정구역"])
    ]
    if elder_region_candidates:
        elder_region = elder_region_candidates[0]
    else:
        st.error("❌ 독거노인 데이터에서 지역 컬럼을 찾을 수 없습니다.")
        st.stop()

    df_elder = df_elder.rename(columns={elder_region: "지역"})
    df_elder = df_elder[df_elder["지역"].astype(str) != "전국"]
    df_elder = df_elder.dropna(subset=["지역"])

    # 독거노인 관련 컬럼 탐색
    target_col_candidates = [
        c for c in df_elder.columns if "1인가구" in c and "65세" in c
    ]
    if target_col_candidates:
        target_col = target_col_candidates[0]
    else:
        # 자동 탐색 실패 시, 지역 컬럼 제외 후 선택
        selectable_cols = [c for c in df_elder.columns if c != "지역"]
        target_col = st.selectbox("📊 독거노인 인구 컬럼 선택", selectable_cols)

    df_elder[target_col] = pd.to_numeric(df_elder[target_col], errors="coerce").fillna(0)

    # -----------------------------
    # 2️⃣ 의료기관 데이터 전처리
    # -----------------------------
    facility_region_candidates = [
        c for c in df_facility.columns
        if any(k in c for k in ["주소", "소재지", "시도", "지역"])
    ]
    if facility_region_candidates:
        facility_region = facility_region_candidates[0]
    else:
        st.error("❌ 의료기관 데이터에서 주소 관련 컬럼을 찾을 수 없습니다.")
        st.stop()

    # 주소에서 시/도만 추출 (앞 2글자)
    df_facility["지역"] = df_facility[facility_region].astype(str).str[:2]

    # -----------------------------
    # 3️⃣ 지역명 표준화
    # -----------------------------
    def normalize_region(name):
        name = str(name).strip()
        mapping = {
            "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
            "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
            "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
            "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도", "경남": "경상남도",
            "제주": "제주특별자치도"
        }
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

    df = pd.merge(df_elder, df_facility_grouped, on="지역", how="inner")
    if df.empty:
        st.error("⚠️ 병합 결과가 비어 있습니다. 지역명이 일치하지 않습니다.")
        st.stop()

    df["의료기관_비율"] = (df["의료기관_수"] / (df[target_col].replace(0, 1))) * 1000
    df = df.rename(columns={"의료기관_비율": "독거노인_1000명당_의료기관_수"})

    st.subheader("📊 병합 결과 데이터")
    st.dataframe(df[["지역", target_col, "의료기관_수", "독거노인_1000명당_의료기관_수"]])

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
        title=f"시도별 독거노인 1,000명당 의료기관 분포 (전국 평균: {mean_ratio:.2f})",
        hover_data={
            "지역": True,
            target_col: True,
            "의료기관_수": True,
            "독거노인_1000명당_의료기관_수": ':.2f'
        }
    )

    fig.update_geos(fitbounds="locations", visible=False, bgcolor="#f8f8f8")
    st.plotly_chart(fig, use_container_width=True)

else:
    st.info("👆 사이드바에서 두 개의 파일을 모두 업로드해주세요.")
