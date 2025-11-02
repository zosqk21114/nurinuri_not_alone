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
# -------------------------
# Part 2/3: 복약 스케줄러, 리마인더, 병원 추천
# (Part1 바로 아래에 붙여넣기)
# -------------------------

# -------------------------
# 유틸: 거리 계산 (haversine)
# -------------------------
import math
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1 = math.radians(lat1); phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1); dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2.0)**2
    return 2 * R * math.asin(math.sqrt(a))

# -------------------------
# TAB3: 복약 스케줄러 / 리마인더
# -------------------------
with tab3:
    st.header("③ 복약 스케줄러 / 리마인더")
    st.info("앱이 열려 있을 때만 리마인더가 표시됩니다. (프로토타입)")

    # --- 약 추가 폼 ---
    with st.form("add_med_form", clear_on_submit=True):
        mcol1, mcol2, mcol3 = st.columns([3,2,2])
        with mcol1:
            med_name = st.text_input("약 이름", placeholder="예: 고혈압약")
        with mcol2:
            interval = st.number_input("간격(시간)", min_value=1, max_value=48, value=24, step=1)
        with mcol3:
            start_time = st.text_input("첫 복용 시각 (HH:MM)", value="08:00")
        notes = st.text_input("메모 (선택)")
        submitted = st.form_submit_button("약 등록")

    if submitted:
        if not med_name or not start_time:
            st.error("이름과 시작 시각을 확인하세요.")
        else:
            try:
                # append safely
                meds = pd.concat([meds, pd.DataFrame([{"name":med_name,"interval_hours":int(interval),"start_time":start_time,"notes":notes}])], ignore_index=True)
                save_csv_safe(meds, MEDS_FILE)
                st.success(f"약 등록 완료: {med_name}")
            except Exception as e:
                st.error(f"등록 실패: {e}")

    # --- 등록된 약 표시 및 삭제 버튼 ---
    if not meds.empty:
        st.subheader("등록된 약")
        st.dataframe(meds.reset_index(drop=True), use_container_width=True)
        # 삭제 UI
        to_delete = st.selectbox("삭제할 약 선택", options=["(선택안함)"] + meds["name"].astype(str).tolist(), index=0)
        if to_delete != "(선택안함)":
            if st.button("선택한 약 삭제"):
                meds = meds[meds["name"] != to_delete].reset_index(drop=True)
                save_csv_safe(meds, MEDS_FILE)
                st.success(f"삭제됨: {to_delete}")

    else:
        st.info("등록된 약이 없습니다. 약을 추가해보세요.")

    st.markdown("---")
    st.subheader("⚠️ 약물 상호작용 (간단 예시)")
    # 간단 데모 DB: 실제 서비스용 아님
    interaction_db = {
        "타이레놀": ["술", "이부프로펜"],
        "아스피린": ["이부프로펜", "와파린"],
        "이부프로펜": ["술", "아스피린"],
        "항생제": ["유제품"],
        "혈압약": ["자몽"]
    }

    if not meds.empty:
        for _, r in meds.iterrows():
            name = str(r.get("name",""))
            warnings = interaction_db.get(name, [])
            if warnings:
                st.warning(f"❗ {name} 복용 시 주의: {', '.join(warnings)}")
            else:
                st.info(f"ℹ️ {name} : 등록된 주의사항 없음")

    st.markdown("---")
    st.subheader("⏰ 리마인더 (지금 열려있을 때만)")

    # 리마인더 계산 함수
    def due_now_list(meds_df, within_minutes=15, overdue_minutes=90):
        now = datetime.now(tz=KST)
        due_items = []
        if meds_df is None or meds_df.empty:
            return due_items
        for _, row in meds_df.iterrows():
            name = row.get("name")
            try:
                iv = int(row.get("interval_hours", 24))
            except:
                iv = 24
            # parse start_time safely
            try:
                hh, mm = map(int, str(row.get("start_time","08:00")).split(":"))
                start_clock = dtime(hh, mm)
            except:
                continue
            # enumerate due times within last 2 days ~ next 1 day
            start_at = datetime.combine((now - timedelta(days=2)).date(), start_clock, tzinfo=KST)
            dues = []
            cur = start_at
            while cur <= (now + timedelta(days=1)):
                dues.append(cur)
                cur += timedelta(hours=iv)
            if not dues:
                continue
            closest = min(dues, key=lambda d: abs((d - now).total_seconds()))
            diff_min = (closest - now).total_seconds()/60.0
            status = None
            if abs(diff_min) <= within_minutes:
                status = "due"
            elif diff_min < 0 and abs(diff_min) <= overdue_minutes:
                status = "overdue"
            if status:
                # check med_log to see if already taken near this due
                taken = False
                if not med_log.empty:
                    try:
                        med_log["taken_at_dt"] = pd.to_datetime(med_log["taken_at"], errors="coerce")
                        cand = med_log[(med_log["name"]==name) & (med_log["taken_at_dt"].between(closest - timedelta(minutes=60), closest + timedelta(minutes=60)))]
                        if len(cand):
                            taken = True
                    except Exception:
                        taken = False
                if not taken:
                    due_items.append({"name": name, "due_time": closest, "status": status})
        return due_items

    due_items = due_now_list(meds)
    if due_items:
        for idx, it in enumerate(due_items):
            status = "🕒 예정" if it["status"]=="due" else "⏰ 연체"
            st.warning(f"{status}: {it['name']} / 예정시각: {it['due_time'].astimezone(KST).strftime('%Y-%m-%d %H:%M')}")
            c1, c2 = st.columns([1,1])
            with c1:
                if st.button(f"✅ 복용 기록 ({idx})", key=f"take_{idx}"):
                    # 기록 추가
                    newr = {"name": it["name"], "due_time": it["due_time"].isoformat(), "taken_at": datetime.now(tz=KST).isoformat()}
                    med_log = pd.concat([med_log, pd.DataFrame([newr])], ignore_index=True)
                    save_csv_safe(med_log, MEDLOG_FILE)
                    st.success(f"{it['name']} 복용 기록 완료")
            with c2:
                st.write("")  # placeholder for layout
    else:
        st.success("현재 예정/연체 항목 없음")

    # 최근 복용 기록 테이블
    if not med_log.empty:
        st.markdown("#### 최근 복용 기록")
        st.dataframe(med_log.sort_values("taken_at", ascending=False).head(100), use_container_width=True)

# -------------------------
# TAB4: 주변 의료기관 찾기 (사용자 위치 or 업로드된 CSV)
# -------------------------
with tab4:
    st.header("④ 주변 의료기관 찾기")
    st.markdown("위치(시/구)를 입력하거나, 전국 의료기관 CSV를 업로드하면 반경 내 기관을 추천합니다.")

    user_loc = st.text_input("내 위치 입력 (예: 서울특별시 강남구)", value="")
    radius_km = st.slider("검색 반경 (km)", 1, 20, 3)

    inst_file = st.file_uploader("전국 의료기관 CSV 업로드 (선택)", type=["csv"])
    institutions = pd.DataFrame()
    if inst_file is not None:
        try:
            raw = inst_file.read()
            for enc in ("utf-8-sig","utf-8","cp949","euc-kr","latin1"):
                try:
                    institutions = pd.read_csv(BytesIO(raw), encoding=enc)
                    break
                except Exception:
                    continue
            if institutions.empty:
                st.error("CSV 읽기 실패. 다른 인코딩으로 저장되었을 수 있습니다.")
        except Exception as e:
            st.error(f"업로드 오류: {e}")
    else:
        # try load cached
        if os.path.exists("institutions.csv"):
            institutions = read_csv_safe("institutions.csv")

    # If user entered location, geocode to lat/lon
    user_lat, user_lon = None, None
    if user_loc:
        try:
            geolocator = Nominatim(user_agent="nurinuri_not_alone_app")
            loc = geolocator.geocode(user_loc, timeout=10)
            if loc:
                user_lat, user_lon = loc.latitude, loc.longitude
                st.success(f"검색 위치: {user_loc} ({user_lat:.3f}, {user_lon:.3f})")
            else:
                st.error("위치를 찾을 수 없습니다. 입력을 확인하세요.")
        except Exception as e:
            st.error(f"위치 조회 실패: {e}")

    # If institutions provided, try find nearby
    if not institutions.empty and (user_lat is not None and user_lon is not None):
        # try normalize lat/lon cols
        lat_col = None; lon_col = None
        for c in institutions.columns:
            lc = c.lower()
            if lc in ("lat","latitude","위도","y","coord_y"): lat_col = c
            if lc in ("lon","lng","longitude","경도","x","coord_x"): lon_col = c
        if lat_col and lon_col:
            institutions["lat_num"] = pd.to_numeric(institutions[lat_col], errors="coerce")
            institutions["lon_num"] = pd.to_numeric(institutions[lon_col], errors="coerce")
            institutions = institutions.dropna(subset=["lat_num","lon_num"])
            institutions["distance_km"] = institutions.apply(lambda r: haversine_km(user_lat, user_lon, r["lat_num"], r["lon_num"]), axis=1)
            near = institutions[institutions["distance_km"]<=radius_km].sort_values("distance_km").head(50)
            if not near.empty:
                st.markdown("### 반경 내 기관 (거리순)")
                show_cols = [c for c in ("name","기관명","의료기관명","address","주소") if c in near.columns]
                # fallback show a few columns
                if not show_cols:
                    show_cols = list(near.columns[:min(6,len(near.columns))])
                st.dataframe(near[show_cols + ["distance_km"]].head(50), use_container_width=True)
            else:
                st.info("반경 내 기관이 없습니다.")
        else:
            st.warning("업로드된 CSV에 위도/경도 컬럼이 필요합니다. (lat/lon 등)")
    elif user_lat is not None and user_lon is not None:
        # No institutions file: use Nominatim to search hospitals near the place
        try:
            query = f"hospital near {user_loc}"
            geolocator = Nominatim(user_agent="nurinuri_not_alone_app")
            results = geolocator.geocode(query, exactly_one=False, limit=8, timeout=10)
            if results:
                hlist = []
                for r in results:
                    hlist.append({"name": r.address, "lat": r.latitude, "lon": r.longitude, "distance_km": haversine_km(user_lat, user_lon, r.latitude, r.longitude)})
                hdf = pd.DataFrame(hlist).sort_values("distance_km")
                st.dataframe(hdf.head(20), use_container_width=True)
            else:
                st.info("검색된 병원이 없습니다.")
        except Exception as e:
            st.error(f"병원 검색 실패: {e}")
    else:
        st.info("위치를 입력하면 병원을 추천합니다 (또는 CSV 업로드).")

# Part2 끝 — Part3/3 이어서 붙여넣으세요.
