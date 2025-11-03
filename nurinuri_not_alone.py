import streamlit as st
import pandas as pd
import plotly.express as px
import requests, io, re

st.set_page_config(page_title="독거노인 대비 의료 접근성 분석", layout="wide")
st.title("🏥 독거노인 인구 대비 의료 접근성 분석")

st.markdown("""
이 앱은 **시군구 단위**로 독거노인 비율 대비 의료기관 수를 비교하여  
접근성을 시각적으로 보여줍니다.

- 🟥 **의료기관 부족 지역**  
- 🟩 **의료기관 풍부 지역**
""")

# -----------------------------
# 📁 파일 업로드
# -----------------------------
st.sidebar.header("📂 데이터 업로드")
elder_file = st.sidebar.file_uploader("독거노인 인구 파일", type=["csv", "xlsx"])
facility_file = st.sidebar.file_uploader("의료기관 데이터 파일", type=["csv", "xlsx"])

# -----------------------------
# 🔍 안전한 파일 읽기 함수
# -----------------------------
def read_any(file):
    if file is None:
        return None
    try:
        if file.name.lower().endswith(".csv") or file.name.lower().endswith(".csv.csv"):
            try:
                return pd.read_csv(file, encoding="utf-8")
            except:
                return pd.read_csv(file, encoding="cp949")
        elif file.name.lower().endswith(".xlsx") or file.name.lower().endswith(".xlsx.xlsx"):
            return pd.read_excel(file)
    except Exception as e:
        st.error(f"파일 읽기 오류: {e}")
        return None

df_elder = read_any(elder_file)
df_facility = read_any(facility_file)

# -----------------------------
# 데이터 전처리
# -----------------------------
if df_elder is not None and df_facility is not None:
    st.success("✅ 두 파일 모두 업로드 완료!")

    # 🔹 컬럼명 전처리 (괄호, 공백 제거)
    df_elder.columns = [re.sub(r"[\s\(\)%]+", "", c) for c in df_elder.columns]
    df_facility.columns = [re.sub(r"[\s\(\)%]+", "", c) for c in df_facility.columns]

    # 🔹 독거노인 지역 컬럼 탐색
    region_cols = [c for c in df_elder.columns if any(k in c for k in ["시도", "시군", "구", "행정"])]
    if len(region_cols) >= 2:
        df_elder["지역"] = df_elder[region_cols[0]].astype(str) + " " + df_elder[region_cols[1]].astype(str)
    else:
        df_elder["지역"] = df_elder[region_cols[0]].astype(str)

    # 🔹 독거노인 관련 컬럼 탐색 (없으면 사용자에게 선택)
    elder_val_cols = [c for c in df_elder.columns if any(k in c for k in ["독거", "노인", "가구비율", "65세", "1인가구", "인구", "비율"])]
    if len(elder_val_cols) == 0:
        st.warning("⚠️ 독거노인 관련 컬럼을 자동으로 찾지 못했습니다. 직접 선택해주세요.")
        target_col = st.selectbox("📊 독거노인 관련 컬럼 선택", df_elder.columns)
    else:
        target_col = elder_val_cols[0]
        st.success(f"✅ 자동으로 '{target_col}' 컬럼이 선택되었습니다.")

    df_elder[target_col] = pd.to_numeric(df_elder[target_col], errors="coerce").fillna(0)

    # 🔹 의료기관 데이터
    addr_col = [c for c in df_facility.columns if any(k in c for k in ["주소", "소재지", "시도명", "시군구명", "지역"])]
    addr_col = addr_col[0]

    def extract_region(addr):
        addr = str(addr)
        addr = re.sub(r"\(.*?\)", "", addr)
        addr = re.sub(r"[^가-힣\s]", "", addr)
        parts = addr.split()
        if len(parts) >= 2:
            return parts[0] + " " + parts[1]
        return parts[0] if parts else None

    df_facility["지역"] = df_facility[addr_col].apply(extract_region)

    # 🔹 의료기관 수 계산
    df_facility_grouped = df_facility.groupby("지역").size().reset_index(name="의료기관수")

    # 🔹 병합
    df = pd.merge(df_elder[["지역", target_col]], df_facility_grouped, on="지역", how="left").fillna(0)

    # 접근성 점수 계산
    df["의료기관비율"] = df["의료기관수"] / (df[target_col] + 1e-6)

    # 🔹 지역 정제 (충북 누락 방지)
    def normalize_region(name):
        name = str(name)
        mapping = {
            "충북": "충청북도", "충남": "충청남도",
            "경북": "경상북도", "경남": "경상남도",
            "전북": "전라북도", "전남": "전라남도",
            "서울": "서울특별시", "부산": "부산광역시", "대전": "대전광역시",
            "대구": "대구광역시", "광주": "광주광역시", "인천": "인천광역시",
            "울산": "울산광역시", "세종": "세종특별자치시", "제주": "제주특별자치도",
        }
        for k, v in mapping.items():
            if name.startswith(k):
                return name.replace(k, v)
        return name

    df["지역"] = df["지역"].apply(normalize_region)

    st.subheader("📈 병합 결과")
    st.dataframe(df.head())

    # -----------------------------
    # 🗺️ 지도 시각화
    # -----------------------------
    geo_url = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2013/json/skorea_municipalities_geo_simple.json"
    geojson = requests.get(geo_url).json()

    geo_names = [g["properties"]["name"] for g in geojson["features"]]
    df["지역_매칭"] = df["지역"].apply(lambda x: next((n for n in geo_names if n in x), None))

    fig = px.choropleth(
        df.dropna(subset=["지역_매칭"]),
        geojson=geojson,
        locations="지역_매칭",
        featureidkey="properties.name",
        color="의료기관비율",
        color_continuous_scale="RdYlGn",
        title="시군구별 독거노인 대비 의료기관 접근성",
    )

    fig.update_geos(fitbounds="locations", visible=False, bgcolor="#f5f5f5")
    st.plotly_chart(fig, use_container_width=True)

else:
    st.info("👆 사이드바에서 두 개의 파일을 업로드해주세요.")
