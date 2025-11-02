# nurinuri_not_alone.py
# 실행: streamlit run nurinuri_not_alone.py
# requirements.txt 참고

import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
from datetime import datetime, timedelta, time as dtime
from io import BytesIO
from zoneinfo import ZoneInfo
import os, json, re

KST = ZoneInfo("Asia/Seoul")

# -----------------------
# 파일 / 상수
# -----------------------
CHECKIN_CSV = "checkins.csv"
MEDS_CSV = "meds.csv"
MEDLOG_CSV = "med_log.csv"
INSTITUTIONS_CSV = "institutions.csv"
REGIONAL_CSV = "regional_factors.csv"
HOME_JSON = "home_location.json"
CONTACTS_JSON = "contacts.json"

# small alarm WAV bytes for st.audio (no external dep)
def make_alarm_wav(seconds=1.2, freq=880, sr=16000):
    import wave, struct, math
    t = np.linspace(0, seconds, int(sr*seconds), False)
    tone = (0.5*np.sin(2*np.pi*freq*t)).astype(np.float32)
    buf = BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        for s in tone:
            w.writeframes(struct.pack('<h', int(s*32767)))
    buf.seek(0)
    return buf.getvalue()

ALARM_WAV = make_alarm_wav()

# -----------------------
# 유틸
# -----------------------
def now_kst():
    return datetime.now(KST)

def ensure_file(path, cols):
    if not os.path.exists(path):
        pd.DataFrame(columns=cols).to_csv(path, index=False)

def save_csv(df, path):
    try:
        df.to_csv(path, index=False)
    except Exception:
        pass

def safe_read_csv(uploaded):
    encs = [None, "utf-8", "cp949", "euc-kr", "latin1"]
    if isinstance(uploaded, str):
        for e in encs:
            try:
                return pd.read_csv(uploaded, encoding=e)
            except Exception:
                continue
        raise
    else:
        raw = uploaded.read()
        for e in encs:
            try:
                return pd.read_csv(BytesIO(raw), encoding=e)
            except Exception:
                continue
        return pd.read_csv(BytesIO(raw))

def parse_time_str(tstr):
    try:
        h, m = map(int, str(tstr).split(":"))
        return dtime(hour=h, minute=m)
    except Exception:
        return None

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2-lat1); dlambda = np.radians(lon2-lon1)
    a = np.sin(dphi/2.0)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlambda/2.0)**2
    return 2*R*np.arcsin(np.sqrt(a))

def load_home():
    if os.path.exists(HOME_JSON):
        try:
            with open(HOME_JSON,"r",encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def save_home(lat, lon, label="우리 집"):
    try:
        with open(HOME_JSON,"w",encoding="utf-8") as f:
            json.dump({"label":label,"lat":float(lat),"lon":float(lon)}, f, ensure_ascii=False)
        return True
    except Exception:
        return False

def load_contacts():
    if os.path.exists(CONTACTS_JSON):
        try:
            with open(CONTACTS_JSON,"r",encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_contacts(lst):
    try:
        with open(CONTACTS_JSON,"w",encoding="utf-8") as f:
            json.dump(lst, f, ensure_ascii=False)
    except Exception:
        pass

# -----------------------
# 초기 파일 준비
# -----------------------
ensure_file(CHECKIN_CSV, ["timestamp","lat","lon"])
ensure_file(MEDS_CSV, ["name","interval_hours","start_time","notes"])
ensure_file(MEDLOG_CSV, ["name","due_time","taken_at"])
ensure_file(INSTITUTIONS_CSV, [])
ensure_file(REGIONAL_CSV, [])

checkins = pd.read_csv(CHECKIN_CSV)
if "timestamp" in checkins.columns:
    checkins["timestamp"] = pd.to_datetime(checkins["timestamp"], errors="coerce")

meds = pd.read_csv(MEDS_CSV) if os.path.exists(MEDS_CSV) else pd.DataFrame(columns=["name","interval_hours","start_time","notes"])
med_log = pd.read_csv(MEDLOG_CSV)
if "taken_at" in med_log.columns:
    med_log["taken_at"] = pd.to_datetime(med_log["taken_at"], errors="coerce")

try:
    institutions = safe_read_csv(INSTITUTIONS_CSV) if os.path.exists(INSTITUTIONS_CSV) else pd.DataFrame()
except Exception:
    institutions = pd.DataFrame()

try:
    regional = safe_read_csv(REGIONAL_CSV) if os.path.exists(REGIONAL_CSV) else pd.DataFrame()
except Exception:
    regional = pd.DataFrame()

# -----------------------
# UI: font size + page
# -----------------------
st.set_page_config(page_title="🧡 nurinuri_not_alone", layout="wide")
font_choice = st.sidebar.selectbox("글자 크기", ["소","일반","대형","초대형"], index=1)
_font_map = {"소":"16px","일반":"20px","대형":"24px","초대형":"30px"}
base_font = _font_map.get(font_choice,"20px")
st.markdown(f"""
<style>
:root {{ --base-font: {base_font}; }}
html, body, [class*="css"] {{ font-size: var(--base-font); }}
.dog-img {{ width:220px; height:220px; border-radius:16px; cursor:pointer; }}
.dog-img:active {{ transform: scale(0.96) rotate(-4deg); }}
</style>
""", unsafe_allow_html=True)

st.title("🧡 독거노인 지원 — nurinuri_not_alone")

pages = [
    "체크인(강아지 터치)", "위험도/알림", "복약 스케줄러",
    "주변 의료기관", "치매예방", "연락망", "똥강아지(말동무)", "데이터/설정"
]
page = st.sidebar.radio("탭 선택", pages)

# -----------------------
# 체크인 (강아지 클릭)
# -----------------------
if page == "체크인(강아지 터치)":
    st.header("🐶 강아지 터치로 체크인")
    st.markdown("강아지를 클릭하면 체크인됩니다. 위치 허용 시 위치/자리표시자 날씨를 보여줍니다.")
    DOG_IMG_URL = "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6e/Puppy_on_White.jpg/640px-Puppy_on_White.jpg"
    dog_html = f"""
    <div style="text-align:center;">
      <img id="dog" class="dog-img" src="{DOG_IMG_URL}" />
      <div style="font-size:18px; margin-top:8px;">강아지를 터치하면 체크인됩니다 🐶</div>
      <script>
        const send = v => window.parent.postMessage({{type:"streamlit:setComponentValue", value:v}}, "*");
        const dog = document.getElementById("dog");
        dog.onclick = () => {{
          dog.style.transform = "scale(1.06) rotate(4deg)";
          setTimeout(()=>dog.style.transform="", 220);
          if (navigator.geolocation) {{
            navigator.geolocation.getCurrentPosition(function(pos){{
              send({{action:"checkin", lat: pos.coords.latitude, lon: pos.coords.longitude, ts: new Date().toISOString()}});
            }}, function(err){{
              send({{action:"checkin", lat:null, lon:null, ts: new Date().toISOString()}});
            }}, {{timeout:7000}});
          }} else {{
            send({{action:"checkin", lat:null, lon:null, ts: new Date().toISOString()}});
          }}
        }};
      </script>
    </div>
    """
    from streamlit.components.v1 import html as st_html
    val = st_html(dog_html, height=320)

    if val is not None:
        try:
            if isinstance(val, dict) and val.get("action") == "checkin":
                lat = val.get("lat"); lon = val.get("lon"); ts = pd.to_datetime(val.get("ts")) if val.get("ts") else now_kst()
                new = {"timestamp": ts, "lat": lat, "lon": lon}
                checkins = pd.concat([checkins, pd.DataFrame([new])], ignore_index=True)
                checkins["timestamp"] = pd.to_datetime(checkins["timestamp"], errors="coerce")
                save_csv(checkins, CHECKIN_CSV)
                st.success(f"체크인 기록: {ts.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')}")
                # 자리표시자 날씨
                if lat is not None and lon is not None:
                    st.info(f"위치: lat={lat:.6f}, lon={lon:.6f}")
                    st.info("현재 날씨(자리표시자): 맑음, 15°C ☀️")
                    if st.button("이 위치를 집으로 저장"):
                        if save_home(lat, lon):
                            st.success("집 위치 저장됨")
                            st.experimental_rerun()
                else:
                    st.info("위치 미허용: 수동입력 또는 저장된 집 위치 사용 가능.")
        except Exception as e:
            st.error(f"체크인 처리 오류: {e}")

    st.markdown("---")
    st.subheader("최근 체크인 (시간 단위)")
    if not checkins.empty:
        dfc = checkins.copy()
        dfc["timestamp"] = pd.to_datetime(dfc["timestamp"], errors="coerce")
        st.dataframe(dfc.sort_values("timestamp", ascending=False).head(50), use_container_width=True)
        df_plot = (dfc.assign(date=lambda x: pd.to_datetime(x["timestamp"]).dt.date,
                              hour=lambda x: pd.to_datetime(x["timestamp"]).dt.hour)
                        .groupby("date", as_index=False).first().sort_values("date"))
        st.caption("날짜별 첫 체크인 (시간 단위)")
        st.line_chart(df_plot.set_index("date")["hour"])
    else:
        st.info("체크인 기록 없음")

# -----------------------
# 위험도/알림
# -----------------------
elif page == "위험도/알림":
    st.header("위험도 및 알림 (시뮬레이션)")
    thr = st.slider("임계치 (%)", 10, 100, 60, 5)

    def calc_risk(checkins_df, meds_df, med_log_df):
        out = {"missing_last3":0, "outliers_last7":0, "adherence_7d":100}
        if checkins_df.empty:
            return 0, out
        df = checkins_df.copy(); df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        recent = df[df["timestamp"] >= (now_kst() - timedelta(days=14))]
        if recent.empty: return 0, out
        daily = recent.assign(date=lambda x: x["timestamp"].dt.date,
                              hour=lambda x: x["timestamp"].dt.hour).groupby("date", as_index=False).first()
        days = [(now_kst().date() - timedelta(days=i)) for i in range(14)]
        missing = [d for d in days if d not in set(daily["date"].tolist())]
        missing_last3 = [d for d in missing if (now_kst().date() - d).days <= 3]
        out["missing_last3"] = len(missing_last3)
        if len(daily) >= 5:
            arr = daily["hour"].to_numpy(); mu = float(np.mean(arr)); sd = float(np.std(arr)) if np.std(arr)>0 else 1.0
            z = (arr - mu) / sd; out["outliers_last7"] = int(np.sum(np.abs(z) > 2))
        if not meds_df.empty and not med_log_df.empty:
            to_dt = now_kst(); from_dt = to_dt - timedelta(days=7)
            taken = med_log_df[(pd.to_datetime(med_log_df["taken_at"]) >= from_dt) & (pd.to_datetime(med_log_df["taken_at"]) <= to_dt)]
            due_total = max(1, len(meds_df) * 7); adherence = min(1.0, len(taken)/due_total)
            out["adherence_7d"] = round(adherence * 100, 1)
        score = min(out["missing_last3"],3)/3*40 + min(out["outliers_last7"],5)/5*20 + (1.0 - out["adherence_7d"]/100.0)*40
        return round(score,1), out

    score, detail = calc_risk(checkins, meds, med_log)
    st.metric("현재 위험도", f"{score}%")
    if score >= thr:
        st.error("⚠️ 위험도 임계치 초과 (가상 경보)")
        st.audio(ALARM_WAV)
        st.markdown("시뮬레이션: 보호자 연락 → 119 연계 안내 → 요약 전송(가상)")
    else:
        st.success("현재는 임계치 미만")

    c1, c2, c3 = st.columns(3)
    c1.metric("최근 3일 결측(일)", detail["missing_last3"])
    c2.metric("최근 이상치(일)", detail["outliers_last7"])
    c3.metric("복약 준수(7일)", f"{detail['adherence_7d']}%")

# -----------------------
# 복약 스케줄러
# -----------------------
elif page == "복약 스케줄러":
    st.header("복약 스케줄러 / 리마인더")
    with st.form("add_med", clear_on_submit=True):
        name = st.text_input("약 이름")
        interval = st.number_input("간격(시간)", 1, 48, 12)
        start_time = st.text_input("첫 복용 시각 (HH:MM)", value="08:00")
        notes = st.text_input("메모")
        if st.form_submit_button("추가"):
            if not name or parse_time_str(start_time) is None:
                st.error("이름과 시각(HH:MM)을 확인하세요.")
            else:
                meds = pd.concat([meds, pd.DataFrame([{"name":name,"interval_hours":int(interval),"start_time":start_time,"notes":notes}])], ignore_index=True)
                save_csv(meds, MEDS_CSV)
                st.success("약 추가됨")
                st.experimental_rerun()

    st.subheader("등록된 약")
    if len(meds):
        st.dataframe(meds, use_container_width=True)
    else:
        st.info("등록된 약 없음")

    def enum_due(start_clock: dtime, interval_hours: int, from_dt: datetime, to_dt: datetime):
        start_at = datetime.combine(from_dt.date(), start_clock).replace(tzinfo=KST)
        while start_at > from_dt:
            start_at -= timedelta(hours=interval_hours)
        times = []
        cur = start_at
        while cur <= to_dt:
            if cur >= from_dt: times.append(cur)
            cur += timedelta(hours=interval_hours)
        return times

    now = now_kst()
    due_items = []
    for _, r in meds.iterrows():
        sc = parse_time_str(r["start_time"])
        if sc is None: continue
        dues = enum_due(sc, int(r["interval_hours"]), now - timedelta(days=1), now + timedelta(days=1))
        for d in dues:
            window = timedelta(minutes=60)
            taken = med_log[(med_log["name"]==r["name"]) & (pd.to_datetime(med_log["taken_at"]).between(d-window, d+window))]
            if len(taken): continue
            diff_min = (d - now).total_seconds()/60.0
            status = "곧 복약" if abs(diff_min) <= 15 else ("연체" if diff_min < 0 and abs(diff_min) <= 24*60 else None)
            if status:
                due_items.append({"name": r["name"], "due_time": d, "status": status})

    st.subheader("리마인더")
    if due_items:
        for idx, it in enumerate(due_items):
            st.warning(f"{it['status']} — {it['name']} / 예정 {it['due_time'].astimezone(KST).strftime('%Y-%m-%d %H:%M')}")
            b1, b2 = st.columns([1,1])
            with b1:
                if st.button(f"✅ {it['name']} 복용 기록", key=f"take_{idx}"):
                    med_log = pd.concat([med_log, pd.DataFrame([{"name":it["name"], "due_time": it["due_time"], "taken_at": now_kst()}])], ignore_index=True)
                    save_csv(med_log, MEDLOG_CSV)
                    st.success("복용 기록 저장됨")
                    st.experimental_rerun()
            with b2:
                st.audio(ALARM_WAV)
    else:
        st.success("예정/연체 항목 없음")

    st.markdown("---")
    st.subheader("복용 기록")
    if not med_log.empty:
        st.dataframe(med_log.sort_values("taken_at", ascending=False).head(200), use_container_width=True)
    else:
        st.info("복용 기록 없음")

# -----------------------
# 주변 의료기관
# -----------------------
elif page == "주변 의료기관":
    st.header("주변 의료기관 찾기 (CSV 업로드 가능)")
    st.markdown("CSV 업로드 시 lat/lon이 있으면 근접 검색을 제공합니다.")

    inst_file = st.file_uploader("의료기관 CSV 업로드", type=["csv"])
    if inst_file is not None:
        try:
            raw = safe_read_csv(inst_file)
            lat_col = None; lon_col = None
            for c in raw.columns:
                lc = c.lower()
                if any(k in lc for k in ["위도","lat","latitude","y"]): lat_col = c
                if any(k in lc for k in ["경도","lon","lng","longitude","x"]): lon_col = c
            if lat_col and lon_col:
                raw = raw.rename(columns={lat_col:"lat", lon_col:"lon"})
                raw["lat"] = pd.to_numeric(raw["lat"], errors="coerce"); raw["lon"] = pd.to_numeric(raw["lon"], errors="coerce")
                name_col = None
                for c in raw.columns:
                    if any(k in c.lower() for k in ["명","name","기관","병원","약국"]):
                        name_col = c; break
                if name_col: raw = raw.rename(columns={name_col:"name"})
                if "type" not in raw.columns: raw["type"] = "병원"
                institutions = raw[[c for c in ["name","type","lat","lon","address"] if c in raw.columns]].copy()
                save_csv(institutions, INSTITUTIONS_CSV)
                st.success(f"기관 데이터 저장: {len(institutions)}개")
            else:
                st.error("lat/lon 컬럼을 찾지 못했습니다.")
        except Exception as e:
            st.error(f"업로드 오류: {e}")

    st.markdown("직접 위치 입력 또는 저장된 집 위치 사용")
    home = load_home()
    use_home = st.checkbox("저장된 집 위치 사용", value=(home is not None))
    if use_home and home:
        lat = float(home["lat"]); lon = float(home["lon"]); st.success(f"집 위치: {home.get('label','우리 집')} ({lat:.6f}, {lon:.6f})")
    else:
        lat = st.number_input("위도", value=37.5665, format="%.6f")
        lon = st.number_input("경도", value=126.9780, format="%.6f")
        if st.button("이 위치 저장"):
            if save_home(lat, lon): st.success("저장됨")

    if not institutions.empty and {"lat","lon"}.issubset(institutions.columns):
        radius = st.slider("반경(km)", 1, 30, 5); tsel = st.selectbox("유형", ["전체","병원","약국"], index=0)
        df = institutions.copy()
        if tsel != "전체": df = df[df["type"].str.contains(tsel, na=False)]
        df["distance_km"] = haversine_km(lat, lon, df["lat"].astype(float), df["lon"].astype(float))
        df = df[df["distance_km"] <= radius].sort_values("distance_km").reset_index(drop=True)
        if len(df):
            st.dataframe(df[["name","type","distance_km","lat","lon"]].head(100), use_container_width=True)
            layers = [
                pdk.Layer("ScatterplotLayer", data=pd.DataFrame([{"name":"집","lat":lat,"lon":lon}]), get_position='[lon, lat]', get_radius=100, get_fill_color=[255,0,0,200]),
                pdk.Layer("ScatterplotLayer", data=df.head(200), get_position='[lon, lat]', get_radius=60, get_fill_color=[0,128,255,160])
            ]
            view_state = pdk.ViewState(latitude=lat, longitude=lon, zoom=12)
            st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view_state))
        else:
            st.info("조건에 맞는 기관이 없습니다.")
    else:
        st.info("기관 데이터 없음 (CSV 업로드 필요)")

# -----------------------
# 치매예방
# -----------------------
elif page == "치매예방":
    st.header("치매 예방 퀴즈 (간단)")
    if "dementia_wrong" not in st.session_state: st.session_state["dementia_wrong"] = 0
    name_input = st.text_input("이름 (퀴즈용)")
    with st.form("quiz"):
        q1 = st.text_input("오늘 날짜? (YYYY-MM-DD)")
        q2 = st.text_input("오늘 요일? (예: 월요일 / Monday)")
        q3 = st.text_input("당신의 이름?")
        if st.form_submit_button("제출"):
            wrong = 0
            if q1.strip() != now_kst().date().strftime("%Y-%m-%d"): wrong += 1
            if q2.strip() == "": wrong += 1
            if name_input and q3.strip() != name_input.strip(): wrong += 1
            if wrong > 0:
                st.session_state["dementia_wrong"] += 1
                st.warning(f"{wrong}문제 틀렸습니다.")
            else:
                st.success("정답입니다"); st.session_state["dementia_wrong"] = 0
            if st.session_state["dementia_wrong"] >= 3:
                st.markdown("<span style='color:darkorange; font-weight:bold;'>치매가 의심됩니다. 가까운 병원을 추천합니다.</span>", unsafe_allow_html=True)
                home = load_home()
                if home is not None and not institutions.empty and {"lat","lon"}.issubset(institutions.columns):
                    dfh = institutions.copy()
                    dfh["distance_km"] = haversine_km(home["lat"], home["lon"], dfh["lat"].astype(float), dfh["lon"].astype(float))
                    top3 = dfh[dfh["type"].str.contains("병원", na=False)].sort_values("distance_km").head(3)
                    if len(top3): st.dataframe(top3[["name","address","distance_km"]])
                    else: st.info("근처 병원 데이터가 부족합니다.")
                else:
                    st.info("집 위치 또는 기관 데이터가 없습니다.")

    st.markdown("---")
    st.info("3x3 퍼즐(자리표시자) — 필요하면 게임 로직 추가 가능합니다.")

# -----------------------
# 연락망
# -----------------------
elif page == "연락망":
    st.header("연락망 (자녀/지인)")
    contacts = load_contacts()
    with st.form("add_contact"):
        nm = st.text_input("이름"); phone = st.text_input("전화번호")
        if st.form_submit_button("추가"):
            if nm and phone:
                contacts.append({"name":nm,"phone":phone}); save_contacts(contacts)
                st.success("추가됨"); st.experimental_rerun()
            else:
                st.error("이름/전화번호 입력")

    if contacts: st.dataframe(pd.DataFrame(contacts), use_container_width=True)
    else: st.info("저장된 연락처 없음")

# -----------------------
# 똥강아지 말동무 (Web Speech API)
# -----------------------
elif page == "똥강아지(말동무)":
    st.header("똥강아지 — 말동무 (음성/텍스트)")
    st.markdown("음성은 브라우저 Web Speech API 사용 (Chrome 권장). '말하기 시작' 버튼을 누르고 말하면 인식됩니다.")
    if "dog_chat" not in st.session_state: st.session_state["dog_chat"] = []

    mode = st.radio("대화 방식", ["키보드","음성(브라우저)"], horizontal=True)
    if mode == "키보드":
        txt = st.text_input("메시지 입력", key="dog_input")
        if st.button("전송", key="dog_send") and txt:
            st.session_state["dog_chat"].append({"who":"user","text":txt})
            if any(k in txt for k in ["안녕","하이","안녕하세요"]): bot = "안녕하세요! 오늘 기분은 어떠신가요?"
            else: bot = "천천히 말씀해 주세요. 전 들을게요."
            st.session_state["dog_chat"].append({"who":"bot","text":bot})
            st.experimental_rerun()
    else:
        speech_html = """
        <div style="text-align:center;">
          <button id="start" style="font-size:18px;padding:8px 12px;">🎤 말하기 시작</button>
          <button id="stop" style="font-size:18px;padding:8px 12px;margin-left:8px;">⏹ 중지</button>
          <div id="status" style="margin-top:10px;"></div>
        </div>
        <script>
          const send = v => window.parent.postMessage({type:"streamlit:setComponentValue", value:v}, "*");
          const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
          const synth = window.speechSynthesis;
          if (!SpeechRecognition) {
            document.getElementById('status').innerText = '음성 인식 미지원(Chrome 권장)';
          } else {
            const rec = new SpeechRecognition(); rec.lang='ko-KR'; rec.continuous=false; rec.interimResults=false;
            document.getElementById('start').onclick = () => { try{ rec.start(); document.getElementById('status').innerText='듣는 중...'; }catch(e){document.getElementById('status').innerText=e;} };
            document.getElementById('stop').onclick = () => { try{ rec.stop(); document.getElementById('status').innerText='중지'; }catch(e){document.getElementById('status').innerText=e;} };
            rec.onresult = (ev) => {
              const txt = ev.results[0][0].transcript;
              document.getElementById('status').innerText = '인식: ' + txt;
              send({action:'voice_text', text: txt});
            };
            rec.onerror = (e) => { document.getElementById('status').innerText = '인식 오류: ' + e.error; send({action:'voice_err', text: e.error});};
          }
        </script>
        """
        from streamlit.components.v1 import html as st_html
        v = st_html(speech_html, height=180)
        if v is not None and isinstance(v, dict) and v.get("action") == "voice_text":
            user_msg = v.get("text","")
            st.session_state["dog_chat"].append({"who":"user","text":user_msg})
            if any(k in user_msg for k in ["안녕","하이","반가워"]): bot = "안녕하세요! 만나서 반가워요."
            elif any(k in user_msg for k in ["심심","외로","외로워"]): bot = "저랑 이야기해줘서 고마워요. 같이 있어줄게요."
            else: bot = "응응, 더 말씀해 주세요."
            st.session_state["dog_chat"].append({"who":"bot","text":bot})
            # TTS via SpeechSynthesis in browser
            tts_html = f"<script>const u=new SpeechSynthesisUtterance({json.dumps(bot)});u.lang='ko-KR';window.speechSynthesis.cancel();window.speechSynthesis.speak(u);</script>"
            st_html(tts_html, height=1)

    st.markdown("---")
    st.subheader("대화 기록")
    for m in st.session_state["dog_chat"][-40:]:
        if m["who"]=="user": st.markdown(f"**사용자:** {m['text']}")
        else: st.markdown(f"**똥강아지:** {m['text']}")

# -----------------------
# 데이터/설정
# -----------------------
elif page == "데이터/설정":
    st.header("데이터 및 설정")
    c1,c2,c3 = st.columns(3)
    with c1:
        st.download_button("체크인 CSV", data=checkins.to_csv(index=False).encode("utf-8"), file_name="checkins.csv")
    with c2:
        st.download_button("약 목록 CSV", data=meds.to_csv(index=False).encode("utf-8"), file_name="meds.csv")
    with c3:
        st.download_button("복약 기록 CSV", data=med_log.to_csv(index=False).encode("utf-8"), file_name="med_log.csv")

    st.markdown("의료기관/지역 데이터 업로드(선택)")
    inst_up = st.file_uploader("의료기관 CSV", type=["csv"])
    if inst_up is not None:
        try:
            raw = safe_read_csv(inst_up)
            raw.to_csv(INSTITUTIONS_CSV, index=False)
            st.success("의료기관 저장됨")
        except Exception as e:
            st.error(f"업로드 실패: {e}")

    reg_up = st.file_uploader("지역요인 파일(xlsx/csv)", type=["xlsx","csv"])
    if reg_up is not None:
        try:
            if reg_up.name.lower().endswith(".xlsx"):
                r = pd.read_excel(reg_up, engine="openpyxl")
            else:
                r = safe_read_csv(reg_up)
            r.to_csv(REGIONAL_CSV, index=False)
            st.success("저장됨")
        except Exception as e:
            st.error(f"업로드 실패: {e}")

    st.markdown("---")
    st.info("앱 상태 미리보기")
    if not institutions.empty: st.dataframe(institutions.head(5))
    else: st.info("의료기관 데이터 없음")

# -----------------------
# 앱 종료 전에 저장
# -----------------------
try:
    save_csv(checkins, CHECKIN_CSV)
    save_csv(meds, MEDS_CSV)
    save_csv(med_log, MEDLOG_CSV)
    if not institutions.empty: save_csv(institutions, INSTITUTIONS_CSV)
    if not regional.empty: save_csv(regional, REGIONAL_CSV)
except Exception:
    pass
