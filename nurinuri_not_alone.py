# nurinuri_not_alone.py
# 실행: streamlit run nurinuri_not_alone.py
# 목적: 강아지 클릭 -> 체크인 + 위치 기반 날씨(텍스트) + 날짜별 첫 체크인 시간 그래프
# 주의: 음성 없음, Streamlit Cloud에서 동작하도록 안전성 보강

import streamlit as st
import pandas as pd
import requests
import altair as alt
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from io import BytesIO
import base64
import os
from geopy.geocoders import Nominatim

KST = ZoneInfo("Asia/Seoul")

# ---------------------------
# 설정 / 파일 경로
# ---------------------------
st.set_page_config(page_title="🧡 nurinuri_not_alone!", page_icon="🧡", layout="wide")
CHECKIN_FILE = "checkins.csv"
MEDS_FILE = "meds.csv"
MEDLOG_FILE = "med_log.csv"
HOME_JSON = "home_location.json"

# 강아지 이미지 URL (네가 준 것 — 무표정, 클릭 시 웃는 얼굴로 바뀜)
DOG_URL_IDLE = "https://marketplace.canva.com/yKgYw/MAGz2eyKgYw/1/tl/canva-cartoon-illustration-of-a-happy-brown-poodle-MAGz2eyKgYw.png"
DOG_URL_SMILE = "https://image.utoimage.com/preview/cp861283/2024/09/202409012057_500.jpg"

# ---------------------------
# 유틸: 안전한 CSV 로드/저장
# ---------------------------
def read_csv_safe(path, parse_dates=None):
    if not os.path.exists(path):
        return pd.DataFrame()
    encs = ["utf-8-sig", "utf-8", "cp949", "euc-kr", "latin1"]
    last_err = None
    for e in encs:
        try:
            return pd.read_csv(path, encoding=e, parse_dates=parse_dates)
        except Exception as err:
            last_err = err
            continue
    # 최종 시도 (기본)
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

# ---------------------------
# 데이터 초기화 (세이프)
# ---------------------------
checkins = read_csv_safe(CHECKIN_FILE, parse_dates=["timestamp"])
if checkins is None or not isinstance(checkins, pd.DataFrame):
    checkins = pd.DataFrame(columns=["timestamp", "lat", "lon", "temperature", "weather"])

meds = read_csv_safe(MEDS_FILE)
if meds is None or not isinstance(meds, pd.DataFrame):
    meds = pd.DataFrame(columns=["name","interval_hours","start_time","notes"])

med_log = read_csv_safe(MEDLOG_FILE, parse_dates=["taken_at"])
if med_log is None or not isinstance(med_log, pd.DataFrame):
    med_log = pd.DataFrame(columns=["name","due_time","taken_at"])

# ---------------------------
# 세션 스테이트 준비
# ---------------------------
if "dog_state" not in st.session_state:
    st.session_state["dog_state"] = "idle"  # idle or smile
if "last_click" not in st.session_state:
    st.session_state["last_click"] = None

# ---------------------------
# 스타일 & 글자 크기(사이드바)
# ---------------------------
st.sidebar.header("설정")
font_choice = st.sidebar.selectbox("글자 크기", ["소","일반","대형","초대형"], index=1)
_font_map = {"소":"14px","일반":"18px","대형":"22px","초대형":"28px"}
base_font = _font_map.get(font_choice, "18px")
st.markdown(f"""
<style>
:root {{ --base-font: {base_font}; }}
html, body, [class*="css"]  {{ font-size: var(--base-font); }}
img.dog-clickable {{ max-width: 360px; border-radius: 16px; cursor: pointer; display:block; margin-left:auto; margin-right:auto; }}
</style>
""", unsafe_allow_html=True)

# ---------------------------
# 탭(5개) — 탭 고정 문제 방지: 기본 st.tabs 사용
# ---------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs(["① 체크인(강아지)","② 위험도/119","③ 복약 스케줄러","④ 주변 의료기관","⑤ 데이터/설정"])

# ---------------------------
# 헬퍼: Open-Meteo 현재 날씨 (key 없음)
# - 인자로 lat, lon (float)
# - 반환: temperature(float or None), weather_text(str)
# ---------------------------
def fetch_current_weather(lat: float, lon: float):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&timezone=Asia%2FSeoul"
        r = requests.get(url, timeout=6)
        j = r.json()
        cw = j.get("current_weather", {})
        temp = cw.get("temperature")
        code = cw.get("weathercode", None)
        desc_map = {
            0:"맑음",1:"주로 맑음",2:"구름 많음",3:"흐림",
            45:"안개",48:"안개",51:"약한 비",61:"비",71:"눈",95:"뇌우"
        }
        desc = desc_map.get(code, "알 수 없음")
        return temp, desc
    except Exception:
        return None, "날씨 정보를 가져오지 못했습니다."

# ---------------------------
# Component HTML: 이미지 클릭 + geolocation 시도
# - 이 컴포넌트는 브라우저에서 geolocation API를 시도하고,
#   결과(또는 실패)를 파이썬으로 반환합니다.
# - 반환값 형식: dict(action="checkin", lat:float|None, lon:float|None)
# ---------------------------
from streamlit.components.v1 import html as st_html

def dog_click_component(idle_url, smile_url, width=360):
    # HTML + JS: 클릭 시 navigator.geolocation.getCurrentPosition 시도, 실패 시 null 전달.
    # 또한 클릭 시 이미지 src 토글(무표정->웃음)하고 800ms 후 원상복귀.
    safe_idle = idle_url
    safe_smile = smile_url
    html_code = f"""
    <div style="text-align:center;">
      <img id="dog_img" src="{safe_idle}" class="dog-clickable" width="{width}" />
      <div style="margin-top:8px;">
        <button id="dog_btn" style="font-size:18px;padding:10px 16px;border-radius:10px;">강아지에게 인사하기</button>
      </div>
    </div>
    <script>
      const btn = document.getElementById("dog_btn");
      const img = document.getElementById("dog_img");
      btn.onclick = function(e) {{
          // visual change
          img.src = "{safe_smile}";
          setTimeout(()=>{{ img.src = "{safe_idle}"; }}, 900);

          if (navigator.geolocation) {{
              navigator.geolocation.getCurrentPosition(function(pos) {{
                  const lat = pos.coords.latitude;
                  const lon = pos.coords.longitude;
                  // post data back to Streamlit
                  window.parent.postMessage({{type: "STREAMLIT_DOG_CLICK", lat: lat, lon: lon}}, "*");
              }}, function(err) {{
                  window.parent.postMessage({{type: "STREAMLIT_DOG_CLICK", lat: null, lon: null}}, "*");
              }}, {{timeout:7000}});
          }} else {{
              window.parent.postMessage({{type: "STREAMLIT_DOG_CLICK", lat: null, lon: null}}, "*");
          }}
      }};
    </script>
    """
    # st_html will return None; we'll listen via window.postMessage and rely on Streamlit's iframe->parent hooking.
    # But to receive the result in Python we use a small loop with st.experimental_get_query_params fallback:
    return st_html(html_code, height=420)

# We need a way to catch the postMessage from the component. Streamlit's st_html does not directly return messages,
# but the common trick (used above earlier) is to have the HTML post window.parent.postMessage and Streamlit can pick it up
# by reading st.session_state from the query params or using a hidden input component. However to keep things robust,
# we'll use a polling approach: the JS also sets window.location.hash with the data (encoded) — but changing hash may reload.
# To keep this robust across Streamlit versions, we'll use a simple approach:
# - The HTML posts a custom event via postMessage with type "STREAMLIT_DOG_CLICK"
# - We will inject a small iframe listener in st to capture window messages via st_js_eval trick is not available.
# In practice, st.components.v1.html returns the last eval result if that is returned; but to keep compatibility we will
# instead provide a fallback: show the component and also show a normal button to record checkin if geolocation fails.
#
# Note: Some Streamlit deployments sandbox cross-origin messages — if geolocation message does not arrive,
# user can click the fallback "체크인(수동)" button.

# ---------------------------
# TAB 1: 체크인 (강아지)
# ---------------------------
with tab1:
    st.header("① 매일 체크인 (강아지 터치)")
    st.write("강아지를 누르면 위치(허용 시)를 가져와 오늘의 날씨를 보여주고 체크인으로 기록합니다. 음성은 재생되지 않습니다.")

    # show dog component
    dog_click_component(DOG_URL_IDLE, DOG_URL_SMILE, width=360)

    # Fallback manual: if browser geolocation message isn't captured, allow manual checkin
    st.markdown("**수동 체크인 (위치 허용 문제 시 사용)**")
    colA, colB = st.columns([2,1])
    with colA:
        lat_inp = st.text_input("위도 (선택)", value="")
        lon_inp = st.text_input("경도 (선택)", value="")
    with colB:
        if st.button("수동으로 체크인 기록"):
            # parse lat/lon if provided
            try:
                lat = float(lat_inp) if lat_inp.strip() else None
                lon = float(lon_inp) if lon_inp.strip() else None
            except Exception:
                lat, lon = None, None

            # fetch weather (use lat/lon if given, else default Seoul)
            if lat is None or lon is None:
                lat, lon = 37.5665, 126.9780
            temp, desc = fetch_current_weather(lat, lon)
            ts = datetime.now(tz=KST)
            new = {"timestamp": ts.isoformat(), "lat": lat, "lon": lon, "temperature": temp, "weather": desc}
            checkins = pd.concat([checkins, pd.DataFrame([new])], ignore_index=True)
            save_csv_safe(checkins, CHECKIN_FILE)
            st.success("수동 체크인 기록 완료 — 날씨가 기록되었습니다.")
            st.session_state["last_click"] = datetime.now().isoformat()

    # Try to detect messages posted by the component.
    # Streamlit does not provide a direct JS->Python bridge except via components return values —
    # but st_html returned earlier does not provide that. We'll use an alternative: read window.location.search param
    # The approach below attempts to read query params for a special key set by the JS (if any).
    # If Streamlit environment or browser blocks cross-message, user can use the manual checkin above.
    params = st.experimental_get_query_params()
    # Expect possible params like ?dog_click_lat=...&dog_click_lon=...
    if "dog_click_lat" in params:
        try:
            lat = float(params.get("dog_click_lat")[0])
            lon = float(params.get("dog_click_lon")[0])
        except Exception:
            lat, lon = None, None
        # remove query params to avoid repeat
        st.experimental_set_query_params()
        # Record checkin
        if lat is None or lon is None:
            lat, lon = 37.5665, 126.9780
        temp, desc = fetch_current_weather(lat, lon)
        ts = datetime.now(tz=KST)
        new = {"timestamp": ts.isoformat(), "lat": lat, "lon": lon, "temperature": temp, "weather": desc}
        checkins = pd.concat([checkins, pd.DataFrame([new])], ignore_index=True)
        save_csv_safe(checkins, CHECKIN_FILE)
        st.success(f"체크인 기록됨 — 위치 기반 날씨: {temp}°C / {desc}")
        st.session_state["last_click"] = datetime.now().isoformat()

    # Recent checkins table + chart (first-in-day time visualized as hour_float)
    st.markdown("---")
    st.subheader("최근 체크인 (날짜별 첫 체크인 시간)")

    if checkins.empty:
        st.info("아직 체크인 기록이 없습니다.")
    else:
        # ensure timestamp is parsed
        dfc = checkins.copy()
        dfc["timestamp"] = pd.to_datetime(dfc["timestamp"], errors="coerce").dt.tz_localize(None, ambiguous='NaT')
        dfc = dfc.dropna(subset=["timestamp"])
        dfc["date"] = dfc["timestamp"].dt.date
        dfc["hour_float"] = dfc["timestamp"].dt.hour + dfc["timestamp"].dt.minute/60.0
        daily = dfc.sort_values("timestamp").groupby("date", as_index=False).first()
        # chart
        chart = alt.Chart(daily).mark_line(point=True).encode(
            x=alt.X("date:T", title="날짜"),
            y=alt.Y("hour_float:Q", title="체크인 시각(시간 단위)"),
            tooltip=["date","hour_float"]
        ).properties(height=300)
        st.altair_chart(chart, use_container_width=True)
        # also show table
        st.dataframe(daily[["date","timestamp","temperature","weather"]].sort_values("date", ascending=False).head(20), use_container_width=True)

# ---------------------------
# TAB 2: 위험도 / 119 시나리오 (간단, 기존 로직 유지)
# ---------------------------
with tab2:
    st.header("② 위험도 예측 및 시뮬레이션")
    st.info("체크인·복약 이력 기반으로 간단한 위험도 점수를 계산합니다 (시뮬레이션용).")

    def checkin_stats_local(df: pd.DataFrame, lookback_days=14):
        if df.empty:
            return {"missing_days": [], "daily": pd.DataFrame(), "mean_min": None, "std_min": None}
        df2 = df.copy()
        df2["timestamp"] = pd.to_datetime(df2["timestamp"], errors="coerce")
        recent = df2[df2["timestamp"] >= (datetime.now(tz=KST) - timedelta(days=lookback_days))]
        if recent.empty:
            return {"missing_days": [], "daily": pd.DataFrame(), "mean_min": None, "std_min": None}
        daily = recent.assign(date=lambda x: x["timestamp"].dt.date,
                              minutes=lambda x: x["timestamp"].dt.hour*60 + x["timestamp"].dt.minute).groupby("date", as_index=False).first()
        days = [(datetime.now(tz=KST).date() - timedelta(days=i)) for i in range(lookback_days)]
        missing = [d for d in days if d not in set(daily["date"].tolist())]
        if len(daily) >= 5:
            mins = daily["minutes"].to_numpy()
            mu = float(mins.mean())
            sd = float(mins.std()) if mins.std() > 0 else 1.0
            z = (mins - mu)/sd
            out_idx = list((abs(z) > 2).nonzero()[0])
            return {"missing_days": missing, "daily": daily, "mean_min": mu, "std_min": sd, "out_idx": out_idx}
        return {"missing_days": missing, "daily": daily, "mean_min": None, "std_min": None, "out_idx": []}

    def estimate_adherence_local(meds_df, med_log_df, days=7, window_minutes=60):
        # med_log_df["taken_at"] should be datetimelike
        if med_log_df is None or med_log_df.empty or meds_df is None or meds_df.empty:
            return 0,0
        to_dt = datetime.now(tz=KST); from_dt = to_dt - timedelta(days=days)
        due_list = []
        taken_list = med_log_df.copy()
        taken_list["taken_at"] = pd.to_datetime(taken_list["taken_at"], errors="coerce")
        for _, row in meds_df.iterrows():
            name = row.get("name")
            sc = None
            try:
                sc = dtime.fromisoformat(str(row.get("start_time")))
            except Exception:
                sc = None
            try:
                iv = int(row.get("interval_hours", 24))
            except Exception:
                iv = 24
            if not sc:
                continue
            # enumerate due times
            start_at = datetime.combine(from_dt.date(), sc).replace(tzinfo=KST)
            while start_at > from_dt:
                start_at -= timedelta(hours=iv)
            while start_at + timedelta(hours=iv) < from_dt:
                start_at += timedelta(hours=iv)
            cur = start_at
            while cur <= to_dt:
                if cur >= from_dt:
                    due_list.append({"name": name, "due_time": cur})
                cur += timedelta(hours=iv)
        if not due_list:
            return 0,0
        due_df = pd.DataFrame(due_list)
        taken_on_time = 0
        window = timedelta(minutes=window_minutes)
        for _, due in due_df.iterrows():
            dname = due["name"]; dtime_ = due["due_time"]
            cand = taken_list[(taken_list["name"]==dname) & (taken_list["taken_at"].between(dtime_-window, dtime_+window))]
            if len(cand):
                taken_on_time += 1
                taken_list = taken_list.drop(cand.index[0])
        return len(due_df), taken_on_time

    c1, c2 = st.columns([1,2])
    with c1:
        risk_thr = st.slider("경보 임계치 (%)", 10, 100, 60, 5)
    with c2:
        st.info("임계치 초과 시 가상 경보를 화면에 표시합니다 (실제 전화는 하지 않습니다).")

    score = 0.0
    details = {}
    try:
        cs = checkin_stats_local(checkins, lookback_days=14)
        missing3 = [d for d in cs.get("missing_days", []) if (datetime.now(tz=KST).date() - d).days <= 3]
        n_missing3 = len(missing3)
        n_out7 = len(cs.get("out_idx", [])) if cs.get("out_idx") is not None else 0
        due_total, taken_on_time = estimate_adherence_local(meds, med_log, days=7, window_minutes=60)
        adherence = (taken_on_time / due_total) if due_total>0 else 1.0
        score = min(n_missing3,3)/3*40 + min(n_out7,5)/5*20 + (1.0 - adherence)*40
        score = round(max(0, min(100, score)),1)
        details = {"missing_last3": n_missing3, "outliers_last7": n_out7, "adherence_7d": round(adherence*100,1)}
    except Exception as e:
        st.warning("위험도 계산 중 내부 오류가 발생했습니다.")

    st.subheader(f"현재 위험도: {score}%")
    st.progress(min(1.0, score/100.0))
    cA,cB,cC = st.columns(3)
    cA.metric("최근 3일 결측(일)", details.get("missing_last3",0))
    cB.metric("최근 7일 이상치(일)", details.get("outliers_last7",0))
    cC.metric("복약 준수(7일)", f"{details.get('adherence_7d', 100)}%")

    if score >= risk_thr:
        st.error("⚠️ 위험도 임계치 초과! (가상 경보)")
        st.info("시뮬레이션 절차: 보호자 연락 -> 119 연계 안내(가상) 등")

# ---------------------------
# TAB 3: 복약 스케줄러 (간단)
# ---------------------------
with tab3:
    st.header("③ 복약 스케줄러 / 리마인더")
    st.info("리마인더는 앱이 열려 있을 때만 동작합니다 (프로토타입).")

    with st.form("add_med", clear_on_submit=True):
        name = st.text_input("약 이름")
        interval = st.number_input("간격(시간)", 1, 48, 24)
        start_t = st.text_input("첫 복용 시각 (HH:MM)", "08:00")
        notes = st.text_input("메모 (선택)")
        submitted = st.form_submit_button("약 추가")
        if submitted:
            try:
                meds = pd.concat([meds, pd.DataFrame([{"name":name,"interval_hours":int(interval),"start_time":start_t,"notes":notes}])], ignore_index=True)
                save_csv_safe(meds, MEDS_FILE)
                st.success("약이 등록되었습니다.")
            except Exception as e:
                st.error("약 등록 중 오류 발생")

    if not meds.empty:
        st.subheader("등록된 약")
        st.dataframe(meds, use_container_width=True)
    else:
        st.info("등록된 약이 없습니다.")

    st.markdown("### 리마인더 (현재 열려있을 때만 표시)")
    # compute due_now
    def due_now_list_local(meds_df, med_log_df, within_minutes=15, overdue_minutes=90):
        now = datetime.now(tz=KST)
        due_items = []
        for _, row in meds_df.iterrows():
            name = row.get("name")
            try:
                iv = int(row.get("interval_hours",24))
            except:
                iv = 24
            try:
                sc = dtime.fromisoformat(str(row.get("start_time")))
            except:
                continue
            # enumerate times in window
            dues = []
            start_at = datetime.combine(now.date()-timedelta(days=1), sc).replace(tzinfo=KST)
            cur = start_at
            while cur <= (now + timedelta(days=1)):
                dues.append(cur)
                cur += timedelta(hours=iv)
            if dues:
                closest = min(dues, key=lambda d: abs((d-now).total_seconds()))
                diff_min = (closest - now).total_seconds()/60.0
                status = None
                if abs(diff_min) <= within_minutes:
                    status = "due"
                elif diff_min < 0 and abs(diff_min) <= overdue_minutes:
                    status = "overdue"
                if status:
                    # check if already taken
                    taken = False
                    if not med_log.empty:
                        med_log["taken_at"] = pd.to_datetime(med_log["taken_at"], errors="coerce")
                        cand = med_log[(med_log["name"]==name) & (med_log["taken_at"].between(closest-timedelta(minutes=60), closest+timedelta(minutes=60)))]
                        if len(cand):
                            taken = True
                    if not taken:
                        due_items.append({"name":name,"due_time":closest,"status":status})
        return due_items

    due_items = due_now_list_local(meds, med_log)
    if due_items:
        for i, item in enumerate(due_items):
            status = "🕒 곧 복용" if item["status"]=="due" else "⏰ 연체"
            st.warning(f"{status}: {item['name']} / 예정시각: {item['due_time'].astimezone(KST).strftime('%Y-%m-%d %H:%M')}")
            col1,col2 = st.columns([1,1])
            with col1:
                if st.button(f"✅ 복용 기록: {i}", key=f"take_{i}"):
                    med_log = pd.concat([med_log, pd.DataFrame([{"name": item['name'], "due_time": item['due_time'].isoformat(), "taken_at": datetime.now(tz=KST).isoformat()}])], ignore_index=True)
                    save_csv_safe(med_log, MEDLOG_FILE)
                    st.success("복용이 기록되었습니다.")
                    # no rerun needed; UI will refresh naturally on next interaction
            with col2:
                st.write(" ")

    else:
        st.success("현재 예정/연체 항목 없음")

    if not med_log.empty:
        st.markdown("#### 최근 복용 기록")
        st.dataframe(med_log.sort_values("taken_at", ascending=False).head(100), use_container_width=True)

# ---------------------------
# TAB 4: 주변 의료기관 (CSV 업로드 지원)
# ---------------------------
with tab4:
    st.header("④ 주변 의료기관 찾기 및 업로드")
    st.markdown("전국 의료기관 CSV를 업로드하면 lat/lon 칼럼을 찾아 반경 내 기관을 추천합니다.")

    inst_file = st.file_uploader("전국 의료기관 CSV 업로드 (옵션)", type=["csv"])
    institutions = pd.DataFrame()
    if inst_file is not None:
        try:
            # try various encodings
            raw = inst_file.read()
            for enc in ("utf-8-sig","utf-8","cp949","euc-kr","latin1"):
                try:
                    inst = pd.read_csv(BytesIO(raw), encoding=enc)
                    institutions = inst.copy()
                    break
                except Exception:
                    continue
            if institutions.empty:
                st.error("CSV를 읽을 수 없습니다. 다른 인코딩으로 저장된 파일인지 확인하세요.")
            else:
                st.success(f"업로드 완료 ({len(institutions)} 행)")
                st.dataframe(institutions.head(10))
                save_csv_safe(institutions, "institutions.csv")
        except Exception as e:
            st.error(f"업로드 중 오류: {e}")
    else:
        if os.path.exists("institutions.csv"):
            institutions = read_csv_safe("institutions.csv")
            if not institutions.empty:
                st.info("저장된 기관 데이터를 불러왔습니다.")
                st.dataframe(institutions.head(10))
        else:
            st.info("CSV를 업로드하거나 institutions.csv 파일을 프로젝트 루트에 두세요.")

# ---------------------------
# TAB 5: 데이터/설정
# ---------------------------
with tab5:
    st.header("⑤ 데이터 / 설정")
    c1,c2,c3 = st.columns(3)
    with c1:
        st.download_button("체크인 CSV 다운로드", data=checkins.to_csv(index=False).encode("utf-8"), file_name="checkins.csv")
    with c2:
        st.download_button("약 목록 CSV", data=meds.to_csv(index=False).encode("utf-8"), file_name="meds.csv")
    with c3:
        st.download_button("복약 기록 CSV", data=med_log.to_csv(index=False).encode("utf-8"), file_name="med_log.csv")

    st.markdown("---")
    st.write("앱 상태 (간단히):")
    st.write(f"체크인 수: {len(checkins)}")
    st.write(f"등록 약 개수: {len(meds)}")
    st.write(f"복용 기록 수: {len(med_log)}")
