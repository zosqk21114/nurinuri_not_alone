import streamlit as st
import pandas as pd
import plotly.express as px
import requests, io, re
from sklearn.neighbors import BallTree
import numpy as np

st.set_page_config(page_title="독거노인 대비 의료 접근성 분석", layout="wide")
st.title("🏥 독거노인 인구 대비 의료 접근성 분석 (보로노이 기반)")

st.markdown("""
이 앱은 **시군구 단위**로 독거노인 비율 대비 **의료 접근성**을  
보로노이 계산식(거리 기반 가중치)을 이용해 시각화합니다.

- 🟥 **의료기관 접근성 낮음**  
- 🟩 **의료기관 접근성 높음**
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

    # 컬럼명 정규화
    df_elder.columns = [re.sub(r"[\s\(\)%]+", "", c) for c in df_elder.columns]
    df_facility.columns = [re.sub(r"[\s\(\)%]+", "", c) for c in df_facility.columns]

    # 🔹 지역 컬럼 찾기
    region_cols = [c for c in df_elder.columns if any(k in c for k in ["시도", "시군", "구", "행정"])]
    if len(region_cols) >= 2:
        df_elder["지역"] = df_elder[region_cols[0]].astype(str) + " " + df_elder[region_cols[1]].astype(str)
    else:
        df_elder["지역"] = df_elder[region_cols[0]].astype(str)

    # 🔹 독거노인 관련 컬럼
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

    # -----------------------------
    # 🧭 지역 정규화
    # -----------------------------
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

    df_elder["지역"] = df_elder["지역"].apply(normalize_region)
    df_facility["지역"] = df_facility["지역"].apply(normalize_region)

    # -----------------------------
    # 📍 병원 접근성 계산 (보로노이 대체)
    # -----------------------------
    # 위경도 대체용 행정구 중심 데이터 불러오기
    geo_url = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2013/json/skorea_municipalities_geo_simple.json"
    geojson = requests.get(geo_url).json()

    centers = []
    for feat in geojson["features"]:
        name = feat["properties"]["name"]
        coords = np.mean(np.array(feat["geometry"]["coordinates"][0][0]), axis=0)
        centers.append([name, coords[0], coords[1]])
    df_centers = pd.DataFrame(centers, columns=["지역", "lon", "lat"])

    # 병원 지역별 중심 좌표
    df_facility_geo = pd.merge(df_facility, df_centers, on="지역", how="left").dropna(subset=["lat"])
    df_elder_geo = pd.merge(df_elder, df_centers, on="지역", how="left").dropna(subset=["lat"])

    # 거리 기반 접근성 점수 (보로노이 근사)
    tree = BallTree(np.radians(df_facility_geo[["lat", "lon"]]), metric="haversine")
    dist, _ = tree.query(np.radians(df_elder_geo[["lat", "lon"]]), k=5)  # 가까운 병원 5개

    # 접근성 점수 = 1 / 평균거리
    df_elder_geo["접근성점수"] = 1 / (dist.mean(axis=1) + 1e-6)
    df_elder_geo["의료기관접근성지수"] = df_elder_geo["접근성점수"] / (df_elder_geo[target_col] + 1e-6)

    # -----------------------------
    # 🗺️ 지도 시각화
    # -----------------------------
    fig = px.choropleth(
        df_elder_geo,
        geojson=geojson,
        locations="지역",
        featureidkey="properties.name",
        color="의료기관접근성지수",
        color_continuous_scale="RdYlGn",
        title="시군구별 독거노인 대비 의료 접근성 (보로노이 기반)"
    )

    fig.update_geos(fitbounds="locations", visible=False, bgcolor="#f5f5f5")
    st.plotly_chart(fig, use_container_width=True)

    st.caption("※ 거리 기반 보로노이 근사 계산: 시군구 중심점 간 거리로 접근성 점수를 계산함")

else:
    st.info("👆 사이드바에서 두 개의 파일을 업로드해주세요.")
