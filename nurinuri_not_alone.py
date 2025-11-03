import streamlit as st
import pandas as pd
import plotly.express as px
import json
import requests

st.set_page_config(page_title="지역별 복지시설 지도 분석", layout="wide")
st.title("지역별 독거노인 대비 복지시설·병원 지도 분석")
st.markdown("""
두 개의 CSV 파일을 업로드하면, 지역별 독거노인 인구 대비 병원/약국/복지시설 분포를 지도 위 색상으로 확인할 수 있습니다.
""")

# 파일 업로드
st.sidebar.header("CSV 파일 업로드")
elder_file = st.sidebar.file_uploader("독거노인 인구 CSV 파일 선택", type=["csv"])
facility_file = st.sidebar.file_uploader("의료기관/복지시설 CSV 파일 선택", type=["csv"])

if elder_file is not None and facility_file is not None:
    try:
        df_elder = pd.read_csv(elder_file)
        df_facility = pd.read_csv(facility_file)
        st.success("두 파일 모두 업로드 성공!")
        
        st.subheader("독거노인 데이터 미리보기")
        st.dataframe(df_elder.head())
        st.subheader("의료기관/복지시설 데이터 미리보기")
        st.dataframe(df_facility.head())

        # 컬럼 확인
        expected_elder = ["지역", "독거노인_인구수"]
        expected_facility = ["지역", "병원_수", "약국_수", "복지시설_수"]

        if not all(col in df_elder.columns for col in expected_elder):
            st.error(f"독거노인 CSV에는 다음 컬럼이 필요합니다: {expected_elder}")
        elif not all(col in df_facility.columns for col in expected_facility):
            st.error(f"시설 CSV에는 다음 컬럼이 필요합니다: {expected_facility}")
        else:
            # 두 파일 병합
            df = pd.merge(df_elder, df_facility, on="지역")
            
            # 시설 대비 독거노인 비율 계산
            df["병원_비율"] = df["병원_수"] / df["독거노인_인구수"]
            df["약국_비율"] = df["약국_수"] / df["독거노인_인구수"]
            df["복지시설_비율"] = df["복지시설_수"] / df["독거노인_인구수"]

            st.subheader("병합 후 데이터 확인")
            st.dataframe(df[["지역", "독거노인_인구수", "병원_수", "약국_수", "복지시설_수",
                             "병원_비율", "약국_비율", "복지시설_비율"]])

            # 시설 선택
            facility_option = st.selectbox("시각화할 시설 선택", ["병원_비율", "약국_비율", "복지시설_비율"])

            # 한국 시군구 GeoJSON 로드
            geojson_url = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2013/json/skorea_municipalities_geo_simple.json"
            geojson = requests.get(geojson_url).json()

            # Choropleth 지도 생성
            fig = px.choropleth(
                df,
                geojson=geojson,
                locations="지역",
                featureidkey="properties.name",  # GeoJSON에서 지역 이름 key
                color=facility_option,
                color_continuous_scale="YlOrRd",
                labels={facility_option: "시설 대비 독거노인 비율"},
                title=f"지역별 {facility_option} 분포"
            )
            fig.update_geos(fitbounds="locations", visible=False)
            st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"파일 처리 중 오류 발생: {e}")
else:
    st.info("두 개의 CSV 파일을 모두 업로드해야 분석을 시작할 수 있습니다.")
