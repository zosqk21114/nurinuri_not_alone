import streamlit as st
import pandas as pd
import plotly.express as px
import io
import requests

# 페이지 설정
st.set_page_config(page_title="독거노인 대비 의료기관 분포 분석", layout="wide")
st.title("🏥 지역별 독거노인 인구 대비 의료기관 분포 분석")

st.markdown("""
이 앱은 **지역별 독거노인 인구수**와 **의료기관 수**를 비교하여  
**독거노인 1,000명당 의료기관 수**를 계산하고 그 분포를 표와 지도 위에서 시각화합니다.
""")

# -----------------------------
# 📂 파일 업로드
# -----------------------------
st.sidebar.header("📁 데이터 업로드")
# 파일 업로드를 Streamlit에 의해 관리되도록 단순화
elder_file = st.sidebar.file_uploader("독거노인 인구 파일 (CSV 또는 XLSX)", type=["csv", "xlsx"], key="elder_upload")
facility_file = st.sidebar.file_uploader("의료기관 데이터 파일 (CSV 또는 XLSX)", type=["csv", "xlsx"], key="facility_upload")

# -----------------------------
# 🔍 파일 읽기 함수 (데이터 클렌징 로직 추가)
# -----------------------------
def read_any(file, is_elder_file=False):
    """CSV 또는 XLSX 파일을 읽어 DataFrame으로 반환하고, 독거노인 파일에 대해서는 헤더 처리를 수행합니다."""
    if file is None:
        return None
    try:
        if file.name.endswith(".csv"):
            raw = file.read()
            # KOSIS 파일 특성상 header=1 (두 번째 행) 사용
            read_kwargs = {'header': 1} if is_elder_file else {}
            try:
                # UTF-8로 시도
                df = pd.read_csv(io.BytesIO(raw), encoding="utf-8", **read_kwargs)
            except UnicodeDecodeError:
                # CP949로 재시도
                df = pd.read_csv(io.BytesIO(raw), encoding="cp949", **read_kwargs)
        elif file.name.endswith(".xlsx"):
            # XLSX 파일은 header=1 옵션으로 읽기
            df = pd.read_excel(file, header=1) if is_elder_file else pd.read_excel(file)
            
        return df
    except Exception as e:
        st.error(f"파일 읽기 오류가 발생했습니다: {e}")
        return None

# -----------------------------
# 📊 파일 로드 및 메인 로직
# -----------------------------
# 독거노인 파일은 header=1 옵션으로 로드하도록 지정
df_elder = read_any(elder_file, is_elder_file=True)
df_facility = read_any(facility_file, is_elder_file=False)

if df_elder is not None and df_facility is not None:
    st.success("✅ 두 파일 모두 업로드 완료!")

    # -----------------------------
    # 🎯 데이터프레임 컬럼 선택 UI 및 자동 선택 로직
    # -----------------------------
    
    st.subheader("🎯 분석을 위한 컬럼 선택")
    elder_cols = df_elder.columns.tolist()
    facility_cols = df_facility.columns.tolist()
    
    # --- 자동 선택 로직 ---
    # 독거노인 데이터 지역 컬럼 (KOSIS 파일 기준 '행정구역별')
    elder_region_col_default = next((c for c in elder_cols if "행정구역" in c), elder_cols[0])
    
    # 의료기관 데이터 지역 컬럼 (표준데이터 기준 '소재지전체주소' 또는 '도로명전체주소')
    facility_region_col_default = next((c for c in facility_cols if "도로명전체주소" in c), 
                                        next((c for c in facility_cols if "소재지전체주소" in c), 
                                            facility_cols[0]))
    
    # 독거노인 인구수 컬럼 (KOSIS 파일 기준 '65세이상 1인가구(A) (가구)')
    target_col_default = next((c for c in elder_cols if "1인가구(A)" in c and df_elder[c].dtype != 'object'), 
                                next((c for c in elder_cols if "독거" in c and df_elder[c].dtype != 'object'), 
                                    elder_cols[1] if len(elder_cols) > 1 else elder_cols[0]))
    
    col1, col2, col3 = st.columns(3)
    
    # Helper for getting default index safely
    def get_default_index(cols, default_col):
        try:
            return cols.index(default_col)
        except ValueError:
            return 0
            
    with col1:
        elder_region = st.selectbox(
            "독거노인 데이터의 지역/주소 컬럼", 
            elder_cols, 
            index=get_default_index(elder_cols, elder_region_col_default),
            key="elder_region_select"
        )
    with col2:
        facility_region = st.selectbox(
            "의료기관 데이터의 지역/주소 컬럼", 
            facility_cols, 
            index=get_default_index(facility_cols, facility_region_col_default),
            key="facility_region_select"
        )
    with col3:
        # '지역' 컬럼을 제외한 리스트를 제공
        non_region_cols = [c for c in elder_cols if c != elder_region]
        target_col = st.selectbox(
            "**[필수] 독거노인 인구/비율 컬럼 (숫자)**", 
            non_region_cols, 
            index=get_default_index(non_region_cols, target_col_default),
            key="population_select"
        )
    
    # -----------------------------
    # 🧹 데이터 전처리 (시/도 레벨로 통일 및 클렌징)
    # -----------------------------
    
    # 1. 독거노인 데이터 클렌징
    try:
        # 시/도 레벨 통일을 위해 앞 2글자만 추출
        df_elder["지역"] = df_elder[elder_region].astype(str).str[:2]
        # '전국'과 같은 요약 행 및 NaN 값 제거
        df_elder = df_elder[df_elder["지역"].isin(["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"])].copy()
        
        # 인구 컬럼을 강제로 숫자 변환 및 NaN은 0으로 처리 (오류 방지 핵심)
        df_elder['POP_NUMERIC'] = pd.to_numeric(df_elder[target_col], errors='coerce').fillna(0)
        
        # 시/도('지역')별로 독거노인 인구수 총합을 계산
        df_elder_grouped = df_elder.groupby("지역")['POP_NUMERIC'].sum().reset_index(name="독거노인_총인구")
        
    except Exception as e:
        st.error(f"**[독거노인 데이터 처리 오류]** 지역/인구 컬럼 선택을 확인해주세요. 오류: {e}")
        st.stop()
        
    # 2. 의료기관 데이터 클렌징 및 집계
    try:
        # 시/도 레벨 통일을 위해 앞 2글자만 추출
        df_facility["지역"] = df_facility[facility_region].astype(str).str[:2]
        
        # '지역' 기준으로 의료기관 수 집계
        df_facility_grouped = df_facility.groupby("지역").size().reset_index(name="의료기관_수")
    except Exception as e:
        st.error(f"**[의료기관 데이터 처리 오류]** 주소 컬럼 선택을 확인해주세요. 오류: {e}")
        st.stop()
        
    # -----------------------------
    # 4. 데이터 병합 및 비율 계산
    # -----------------------------
    # 집계된 두 데이터프레임을 '지역' 기준으로 병합
    df = pd.merge(df_elder_grouped, df_facility_grouped, on="지역", how="inner")
    
    if df.empty:
        st.error("데이터 병합 결과가 비어있습니다. 두 파일의 지역 값이 일치하지 않아 병합에 실패했습니다. 올바른 지역 컬럼을 선택하고, 값이 앞 2글자로 일치하는지 확인해주세요.")
        st.stop()
        
    # 독거노인 1000명당 의료기관 수 계산
    safe_population = df["독거노인_총인구"]
    
    # 0으로 나누는 오류 방지 및 1000명 기준으로 비율 조정
    df["의료기관_비율"] = (df["의료기관_수"] / (safe_population + 1e-9)) * 1000
    
    # 최종 결과 데이터프레임 컬럼 이름 정리
    df_result = df.rename(columns={"독거노인_총인구": f"독거노인_총인구(선택: {target_col})"})

    # -----------------------------
    # 📊 테이블 출력
    # -----------------------------
    st.subheader("📊 시도별 독거노인 인구 및 의료기관 분포 현황")
    st.markdown("---")
    st.dataframe(
        df_result.sort_values(by="의료기관_비율", ascending=False).set_index("지역"),
        column_order=["의료기관_비율", f"독거노인_총인구(선택: {target_col})", "의료기관_수"],
        column_config={
            "의료기관_비율": st.column_config.NumberColumn("1,000명당 의료기관 수", format="%.2f개"),
            f"독거노인_총인구(선택: {target_col})": st.column_config.NumberColumn("독거노인 총인구", format="%,d명"),
            "의료기관_수": st.column_config.NumberColumn("의료기관 총수", format="%,d개")
        },
        use_container_width=True
    )
    st.markdown("---")
    
    # -----------------------------
    # 🗺️ 지도 시각화
    # -----------------------------
    st.subheader("🗺️ 시도별 독거노인 인구 대비 의료기관 분포 지도")
    
    # 시도 경계 지오제이슨 파일 로드 (대한민국 시도 경계)
    geojson_url = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2013/json/skorea_provinces_geo_simple.json"
    geojson = requests.get(geojson_url).json()

    # Plotly Choropleth 지도 생성
    fig = px.choropleth(
        df_result,
        geojson=geojson,
        locations="지역",
        featureidkey="properties.name", # 지도 데이터의 지역 이름 컬럼과 병합
        color="의료기관_비율",
        color_continuous_scale="YlOrRd", # 노란색-주황색-빨간색 스케일
        title="시도별 독거노인 인구 1,000명당 의료기관 분포",
        hover_name="지역",
        hover_data={
            f"독거노인_총인구(선택: {target_col})": ':,.0f', 
            "의료기관_수": True, 
            "의료기관_비율": ':.2f',
            "지역": False
        } 
    )
    
    # 지도 영역을 대한민국 시도 경계에 맞게 조정
    fig.update_geos(
        fitbounds="locations", 
        visible=False,
        scope='asia',
        center={"lat": 36, "lon": 127.8} 
    )
    # 레이아웃 업데이트 (제목 중앙 정렬)
    fig.update_layout(
        margin={"r":0,"t":50,"l":0,"b":0},
        title_x=0.5
    )
    
    st.plotly_chart(fig, use_container_width=True)

else:
    st.info("👆 사이드바에서 두 개의 파일을 모두 업로드해주세요.")
