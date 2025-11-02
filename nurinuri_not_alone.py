# nurinuri_not_alone.py  — Part 1/3
# (이 파일을 통째로 붙여넣기 하세요; Part2/3, Part3/3 이어서 붙입니다)

import streamlit as st
import pandas as pd
import requests
import altair as alt
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
import os
from io import BytesIO
import base64

KST = ZoneInfo("Asia/Seoul")

st.set_page_config(page_title="🧡 nurinuri_not_alone!", page_icon="🧡", layout="wide")

# -------------------------
# 파일 안전 로드/저장 유틸
# -------------------------
def read_csv_safe(path, parse_dates=None):
    """여러 인코딩 시도 후 DataFrame 반환. 실패 시 빈 DF."""
    if not os.path.exists(path):
        return pd.DataFrame()
    encs = ["utf-8-sig","utf-8","cp949","euc-kr","latin1"]
    last_exc = None
    for e in encs:
        try:
            return pd.read_csv(path, encoding=e, parse_dates=parse_dates)
        except Exception as ex:
            last_exc = ex
    # 마지막 시도
    try:
        return pd.read_csv(path, parse_dates=parse_dates)
    except Exception:
        return pd.DataFrame()

def save_csv_safe(df, path):
    try:
        df.to_csv(path, index=False, encoding="utf-8")
    except Exception:
        try:
            df.to_csv(path, index=False)
        except Exception:
            pass

# -------------------------
# 데이터 파일 경로
# -------------------------
CHECKIN_FILE = "checkins.csv"
MEDS_FILE = "meds.csv"
MEDLOG_FILE = "med_log.csv"
INSTITUTIONS_FILE = "institutions.csv"

# -------------------------
# 데이터 초기화
# -------------------------
checkins = read_csv_safe(CHECKIN_FILE, parse_dates=["timestamp"])
if checkins is None or not isinstance(checkins, pd.DataFrame):
    checkins = pd.DataFrame(columns=["timestamp","lat","lon","temperature","weather"])

meds = read_csv_safe(MEDS_FILE)
if meds is None or not isinstance(meds, pd.DataFrame):
    meds = pd.DataFrame(columns=["name","interval_hours","start_time","notes"])

med_log = read_csv_safe(MEDLOG_FILE, parse_dates=["taken_at"])
if med_log is None or not isinstance(med_log, pd.DataFrame):
    med_log = pd.DataFrame(columns=["name","due_time","taken_at"])

# -------------------------
# 세션 상태 초기값
# -------------------------
if "last_checkin" not in st.session_state:
    st.session_state["last_checkin"] = None
if "font_size" not in st.session_state:
    st.session_state["font_size"] = "일반"

# -------------------------
# 사이드바: 글자 크기
# -------------------------
st.sidebar.header("설정")
st.session_state["font_size"] = st.sidebar.selectbox("글자 크기", ["소","일반","대형","초대형"], index=1)
_font_map = {"소":"14px","일반":"18px","대형":"22px","초대형":"28px"}
_base_font = _font_map.get(st.session_state["font_size"], "18px")

st.markdown(f"""
<style>
html, body, [class*="css"] {{
  font-size: {_base_font} !important;
}}
.img-dog {{ max-width: 420px; border-radius: 12px; display:block; margin-left:auto; margin-right:auto; cursor: pointer; }}
.small-muted {{ color: #666; font-size: 0.9em; }}
</style>
""", unsafe_allow_html=True)

# -------------------------
# 탭 생성
# -------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "① 체크인(강아지)", "② 위험도/119", "③ 복약 스케줄러",
    "④ 주변 의료기관", "⑤ 데이터/설정"
])

# -------------------------
# 강아지 클릭용 HTML (JS로 geolocation 시도 -> query params로 전달)
# (브라우저가 위치 허용 시 ?dog_click=1&lat=...&lon=... 로 리로드됨)
# -------------------------
DOG_IDLE_URL = "https://marketplace.canva.com/yKgYw/MAGz2eyKgYw/1/tl/canva-cartoon-illustration-of-a-happy-brown-poodle-MAGz2eyKgYw.png"
DOG_SMILE_URL = "https://image.utoimage.com/preview/cp861283/2024/09/202409012057_500.jpg"

def render_dog_click_component(idle_url: str, smile_url: str, width:int=360):
    """이미지 + 버튼을 보여주고, 클릭 시 geolocation을 시도해서 query params로 리로드."""
    html = f"""
    <div style="text-align:center;">
      <img id="dog_img" src="{idle_url}" class="img-dog" width="{width}" />
      <div style="margin-top:8px;">
        <button id="dog_btn" style="font-size:16px;padding:10px 14px;border-radius:10px;">강아지에게 인사하기</button>
      </div>
      <p class="small-muted">강아지를 누르면 위치를 허용하라는 창이 뜹니다. 허용하면 위치 기반 날씨가 기록됩니다. (허용 안함 → 기본 서울)</p>
    </div>
    <script>
      const btn = document.getElementById("dog_btn");
      const img = document.getElementById("dog_img");
      btn.onclick = function(e) {{
          // Toggle smile briefly
          img.src = "{smile_url}";
          setTimeout(()=>{{ img.src = "{idle_url}"; }},900);
          // try geolocation
          if (navigator.geolocation) {{
              navigator.geolocation.getCurrentPosition(function(pos) {{
                  const lat = pos.coords.latitude;
                  const lon = pos.coords.longitude;
                  // set location in query string to pass to Streamlit
                  const url = new URL(window.location.href);
                  url.searchParams.set("dog_click","1");
                  url.searchParams.set("dog_lat", lat);
                  url.searchParams.set("dog_lon", lon);
                  window.location.href = url.toString();
              }}, function(err) {{
                  const url = new URL(window.location.href);
                  url.searchParams.set("dog_click","1");
                  // no lat/lon => leave blank params
                  window.location.href = url.toString();
              }}, {{timeout:7000}});
          }} else {{
              const url = new URL(window.location.href);
              url.searchParams.set("dog_click","1");
              window.location.href = url.toString();
          }}
      }};
    </script>
    """
    st.components.v1.html(html, height=360)

# -------------------------
# Open-Meteo 날씨 조회 (lat/lon 사용)
# -------------------------
def fetch_weather(lat: float, lon: float):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&timezone=Asia%2FSeoul"
        r = requests.get(url, timeout=6)
        j = r.json()
        cw = j.get("current_weather", {})
        temp = cw.get("temperature")
        code = cw.get("weathercode")
        desc_map = {0:"맑음",1:"주로맑음",2:"구름많음",3:"흐림",45:"안개",48:"안개",51:"약한비",61:"비",71:"눈",95:"뇌우"}
        desc = desc_map.get(code, "알 수 없음")
        return temp, desc
    except Exception:
        return None, "날씨 정보를 가져오지 못했습니다."

# -------------------------
# TAB1: 체크인 구현
# -------------------------
with tab1:
    st.header("① 매일 체크인 (강아지 터치)")
    st.write("강아지를 눌러 체크인하세요. 위치 허용 시 해당 위치의 현재 날씨(텍스트)가 기록됩니다. 음성은 재생되지 않습니다.")

    # 렌더 강아지 클릭 컴포넌트
    render_dog_click_component(DOG_IDLE_URL, DOG_SMILE_URL, width=380)

    # 수동 체크인(위치 허용 실패 시 대체)
    st.markdown("**수동 체크인 (위치 허용 실패 시)**")
    col1, col2 = st.columns([2,1])
    with col1:
        lat_inp = st.text_input("위도 입력 (선택)", value="")
        lon_inp = st.text_input("경도 입력 (선택)", value="")
    with col2:
        if st.button("수동 체크인 기록"):
            try:
                lat = float(lat_inp) if lat_inp.strip() else None
                lon = float(lon_inp) if lon_inp.strip() else None
            except:
                lat, lon = None, None
            if lat is None or lon is None:
                lat, lon = 37.5665, 126.9780  # Seoul as fallback
            temp, desc = fetch_weather(lat, lon)
            ts = datetime.now(tz=KST)
            new = {"timestamp": ts.isoformat(), "lat": lat, "lon": lon, "temperature": temp, "weather": desc}
            checkins = pd.concat([checkins, pd.DataFrame([new])], ignore_index=True)
            save_csv_safe(checkins, CHECKIN_FILE)
            st.success("수동 체크인 저장 완료")

    # 처리: query params에 dog_click이 있으면 체크인 처리
    params = st.experimental_get_query_params()
    if params.get("dog_click", [None])[0] == "1":
        # pull lat/lon if present; otherwise fallback to Seoul
        try:
            lats = params.get("dog_lat", [None])[0]
            lons = params.get("dog_lon", [None])[0]
            lat = float(lats) if lats not in (None, "", "None") else None
            lon = float(lons) if lons not in (None, "", "None") else None
        except Exception:
            lat, lon = None, None
        # clear params so reloading doesn't record twice
        st.experimental_set_query_params()
        if lat is None or lon is None:
            lat, lon = 37.5665, 126.9780
        temp, desc = fetch_weather(lat, lon)
        ts = datetime.now(tz=KST)
        new = {"timestamp": ts.isoformat(), "lat": lat, "lon": lon, "temperature": temp, "weather": desc}
        checkins = pd.concat([checkins, pd.DataFrame([new])], ignore_index=True)
        save_csv_safe(checkins, CHECKIN_FILE)
        st.success(f"체크인 완료 — {temp}°C / {desc}")
        st.session_state["last_checkin"] = ts.isoformat()

    # 최근 체크인 & 날짜별 첫 체크인 시각 차트
    st.markdown("---")
    st.subheader("최근 체크인 및 날짜별 첫 체크인 시각 (시간 단위)")
    if checkins.empty:
        st.info("아직 체크인 기록이 없습니다. 강아지를 눌러보세요!")
    else:
        dfc = checkins.copy()
        # parse timestamps safely
        dfc["timestamp"] = pd.to_datetime(dfc["timestamp"], errors="coerce")
        dfc = dfc.dropna(subset=["timestamp"])
        dfc["date"] = dfc["timestamp"].dt.date
        dfc["hour_float"] = dfc["timestamp"].dt.hour + dfc["timestamp"].dt.minute/60.0
        daily_first = dfc.sort_values("timestamp").groupby("date", as_index=False).first()
        # line chart (시간 단위)
        chart = alt.Chart(daily_first).mark_line(point=True).encode(
            x=alt.X("date:T", title="날짜"),
            y=alt.Y("hour_float:Q", title="체크인 시각(시간 단위)"),
            tooltip=["date","hour_float","temperature","weather"]
        ).properties(height=320)
        st.altair_chart(chart, use_container_width=True)
        st.dataframe(daily_first[["date","timestamp","temperature","weather"]].sort_values("date",ascending=False).head(20), use_container_width=True)

# Part1 끝 — Part2/3 이어서 붙여넣으세요.
