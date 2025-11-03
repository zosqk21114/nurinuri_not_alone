import streamlit as st
import pandas as pd
import plotly.express as px
import io
import requests

# -----------------------------
# 설정 및 제목
# -----------------------------
st.set_page_config(page_title="독거노인 대비 의료기관 분포 분석", layout="wide")
st.title("🧓 지역별 독거노인 인구 대비 의료기관 분포 분석")

st.markdown("""
이 앱은 **지역별 독거노인 인구수**와 **의료기관 수**를 비교하여
얼마나 고르게 분포되어 있는지를 지도 위에서 시각화합니다.

- 🟥 **빨간색**: 의료기관이 부족한 지역  
- 🟩 **초록색**: 의료기관이 충분한 지역
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
    # 1. 독거노인 데이터 전처리
    # -----------------------------
    target_col = None

    # 헤더 병합 로직 (KOSIS 구조 대응)
    if '행정구역별' in df_elder.columns and '2024' in df_elder.columns:
        df_elder.columns = df_elder.iloc[0]
        df_elder = df_elder[1:].reset_index(drop=True)
        df_elder.columns = [col.strip() for col in df_elder.columns]

    # 지역 컬럼 찾기
    elder_region_col_candidates = [c for c in df_elder.columns if "시도" in c or "지역" in c or "행정구역" in c]
    if elder_region_col_candidates:
        df_elder = df_elder.rename(columns={elder_region_col_candidates[0]: '지역'})
    else:
        st.warning("⚠️ 독거노인 지역 컬럼을 자동으로 찾을 수 없습니다.")
        elder_region = st.selectbox("독거노인 지역 컬럼 선택", df_elder.columns, key="elder_region_sel")
        df_elder = df_elder.rename(columns={elder_region: '지역'})

    # 인구 컬럼 자동/수동 선택
    target_col_candidates = [c for c in df_elder.columns if '1인가구' in c and '65세이상' in c]
    if target_col_candidates:
        target_col = target_col_candidates[0]
    else:
        st.warning("⚠️ 독거노인 인구 컬럼을 자동으로 찾을 수 없습니다.")
        target_col = st.selectbox("독거노인 인구 컬럼 선택", df_elder.columns, key="target_col_sel")

    df_elder = df_elder[df_elder['지역'].astype(str) != '전국'].dropna(subset=['지역'])

    # -----------------------------
    # 2. 의료기관 데이터 전처리
    # -----------------------------
    facility_region_col_candidates = [c for c in df_facility.columns if "시도" in c or "주소" in c or "지역" in c or "소재지전체주소" in c]
    facility_region = facility_region_col_candidates[0] if facility_region_col_candidates else st.selectbox("의료기관 지역 컬럼 선택", df_facility.columns, key="facility_region_sel")
    df_facility["지역"] = df_facility[facility_region].astype(str).str[:2]

    # -----------------------------
    # 3. 지역명 표준화
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
        for key, val in mapping.items():
            if name.startswith(key):
                return val
        return name

    df_elder["지역"] = df_elder["지역"].apply(normalize_region)
    df_facility["지역"] = df_facility["지역"].apply(normalize_region)

    # -----------------------------
    # 4. 병합 및 비율 계산
    # -----------------------------
    df_facility_grouped = df_facility.groupby("지역").size().reset_index(name="의료기관_수")
    df_elder[target_col] = pd.to_numeric(df_elder[target_col], errors='coerce').fillna(0)
    df = pd.merge(df_elder, df_facility_grouped, on="지역", how="inner")
    df["독거노인_1000명당_의료기관_수"] = (df["의료기관_수"] / (df[target_col].replace(0, 1))) * 1000

    # -----------------------------
    # 색상 기준 설정 (사용자 선택)
    # -----------------------------
    st.sidebar.header("🎨 색상 기준 설정")
    mode = st.sidebar.radio(
        "색상 기준을 선택하세요:",
        ["이상치 제외 평균", "절대 기준값 설정"],
        help="전국 평균 대신 50~100 같은 절대값으로도 설정 가능"
    )

    if mode == "이상치 제외 평균":
        lower = df["독거노인_1000명당_의료기관_수"].quantile(0.1)
        upper = df["독거노인_1000명당_의료기관_수"].quantile(0.9)
        trimmed = df[(df["독거노인_1000명당_의료기관_수"] >= lower) &
                     (df["독거노인_1000명당_의료기관_수"] <= upper)]
        mean_ratio = trimmed["독거노인_1000명당_의료기관_수"].mean()
        st.sidebar.info(f"상하위 10% 제외 평균: {mean_ratio:.2f}")
    else:
        mean_ratio = st.sidebar.number_input("절대 기준값 입력 (예: 100)", value=100.0, step=10.0)

    # -----------------------------
    # 지도 시각화
    # -----------------------------
    geojson_url = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2013/json/skorea_provinces_geo_simple.json"
    geojson = requests.get(geojson_url).json()

    for feature in geojson['features']:
        if feature['properties']['name'] == '강원도':
            feature['properties']['name'] = '강원특별자치도'
        if feature['properties']['name'] == '전라북도':
            feature['properties']['name'] = '전북특별자치도'

    fig = px.choropleth(
        df,
        geojson=geojson,
        locations="지역",
        featureidkey="properties.name",
        color="독거노인_1000명당_의료기관_수",
        color_continuous_scale="RdYlGn",
        color_continuous_midpoint=mean_ratio,
        title=f"시도별 독거노인 1000명당 의료기관 분포 (기준: {mean_ratio:.2f})",
        range_color=(df["독거노인_1000명당_의료기관_수"].min(), df["독거노인_1000명당_의료기관_수"].max()),
        hover_data={
            "지역": True,
            target_col: True,
            "의료기관_수": True,
            "독거노인_1000명당_의료기관_수": ':.2f'
        }
    )

    fig.update_geos(fitbounds="locations", visible=False, bgcolor="#f5f5f5")
    st.plotly_chart(fig, use_container_width=True)

else:
    st.info("📥 사이드바에서 두 개의 파일을 모두 업로드해주세요.")
