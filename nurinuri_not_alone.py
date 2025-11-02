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
import os, json, re, base64

KST = ZoneInfo("Asia/Seoul")

# ------------------------
# 파일/상수
# ------------------------
CHECKIN_CSV = "checkins.csv"
MEDS_CSV = "meds.csv"
MEDLOG_CSV = "med_log.csv"
INSTITUTIONS_CSV = "institutions.csv"
REGIONAL_CSV = "regional_factors.csv"
HOME_JSON = "home_location.json"
CONTACTS_JSON = "contacts.json"

# ------------------------
# 내장 알람 오디오 (WAV bytes)
# ------------------------
def make_alarm_wav(seconds=1.2, freq=880, sr=16000):
    import wave, struct
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

# ------------------------
# Base64 내장 강아지(작은 PNG)
# (작게 압축된 아이콘용 base64 - 필요하면 대체해줄게)
# ------------------------
DOG_IMAGE_BASE64 = (
"iVBORw0KGgoAAAANSUhEUgAAAMgAAADICAMAAACahl6sAAAABlBMVEX///8AAABVwtN+AAABsElEQVR4nO3VMQ0AMAwAsXv/p4y"
"YpQqk8m2M2gI8d2gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPgO6gAAANg+1mEAAACAG9gEAAABgBvYBAAAYAa9gEAAAA"
"YAb2AQAAAGAG9gEAAABgBvYBAAAYAa9gEAAAA..."
)  # truncated short sample; fine for placeholder

# helper to produce img tag
def dog_img_html(width=220):
    return f'<img src="data:image/png;base64,{DOG_IMAGE_BASE64}" style="width:{width}px;height:{width}px;border-radius:12px;cursor:pointer;" id="nuri_dog">'

# ------------------------
# 유틸 함수
# ------------------------
def now_kst():
    return datetime.now(KST)

def ensure_csv(path, cols):
    if not os.path.exists(path):
        pd.DataFrame(columns=cols).to_csv(path, index=False)

def save_csv(df, path):
    try:
        df.to_csv(path, index=False)
    except Exception:
        pass

def safe_read_csv(uploaded_or_path):
    encs = [None, "utf-8", "cp949", "euc-kr", "latin1"]
    if isinstance(uploaded_or_path, str):
        for e in encs:
            try:
                return pd.read_csv(uploaded_or_path, encoding=e)
            except Exception:
                continue
        raise
    else:
        raw = uploaded_or_path.read()
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
            with open(HOME_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def save_home(lat, lon, label="우리 집"):
    try:
        with open(HOME_JSON, "w", encoding="utf-8") as f:
            json.dump({"label": label, "lat": float(lat), "lon": float(lon)}, f, ensure_ascii=False)
        return True
    except Exception:
        return False

def load_contacts():
    if os.path.exists(CONTACTS_JSON):
        try:
            with open(CONTACTS_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_contacts(lst):
    try:
        with open(CONTACTS_JSON, "w", encoding="utf-8") as f:
            json.dump(lst, f, ensure_ascii=False)
    except Exception:
        pass

# ------------------------
# 초기화: 안전하게 파일 만들기 및 로드
# ------------------------
ensure_csv(CHECKIN_CSV, ["timestamp","lat","lon"])
ensure_csv(MEDS_CSV, ["name","interval_hours","start_time","notes"])
ensure_csv(MEDLOG_CSV, ["name","due_time","taken_at"])
ensure_csv(INSTITUTIONS_CSV, [])
ensure_csv(REGIONAL_CSV, [])

# load
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

# ------------------------
# UI 기본: 폰트 크기
# ------------------------
st.set_page_config(page_title="🧡 nurinuri_not_alone", layout="wide")
font_choice = st.sidebar.selectbox("글자 크기", ["소","일반","대형","초대형"], index=1)
_font_map = {"소":"16px","일반":"20px","대형":"24px","초대형":"30px"}
base_font = _font_map.get(font_choice, "20px")
st.markdown(f"""
<style>
:root {{ --base-font: {base_font}; }}
html, body, [class*="css"] {{ font-size: var(--base-font); }}
</style>
""", unsafe_allow_html=True)

st.title("🧡 독거노인 지원 — nurinuri_not_alone")

# ------------------------
# 탭/페이지 리스트
# ------------------------
pages = [
    "① 체크인(강아지 터치)", "② 위험도/119 시나리오", "③ 복약 스케줄러",
    "④ 주변 의료기관", "⑤ 치매예방", "⑥ 연락망", "⑦ 똥강아지(말동무)", "⑧ 데이터/설정"
]
page = st.sidebar.radio("탭 선택", pages)

# ------------------------
# ① 체크인 (강아지 터치) — 이미지는 Base64 내장, 클릭시 위치 시도, 체크인 기록 추가
# ------------------------
if page == pages[0]:
    st.header("① 매일 체크인 (강아지 터치)")
    st.markdown("강아지를 클릭하면 체크인됩니다. 위치 허용 시 위치/자리표시자 날씨를 알려줍니다.")

    # HTML+JS: 클릭하면 geolocation 시도하고 postMessage로 전달
    dog_html = f"""
    <div style="text-align:center;">
      {dog_img_html(220)}
      <div style="font-size:16px;margin-top:8px;">강아지를 터치하면 체크인됩니다 🐶</div>
      <script>
        const send = v => window.parent.postMessage({{type:"streamlit:setComponentValue", value:v}}, "*");
        const dog = document.getElementById("nuri_dog");
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
    res = st_html(dog_html, height=360)

    # res is the posted value dict when JS runs
    if res is not None:
        try:
            if isinstance(res, dict) and res.get("action") == "checkin":
                lat = res.get("lat"); lon = res.get("lon")
                ts = pd.to_datetime(res.get("ts")) if res.get("ts") else now_kst()
                # ensure timestamp column is datetime
                new = {"timestamp": ts, "lat": lat, "lon": lon}
                checkins = pd.concat([checkins, pd.DataFrame([new])], ignore_index=True)
                checkins["timestamp"] = pd.to_datetime(checkins["timestamp"], errors="coerce")
                save_csv(checkins, CHECKIN_CSV)
                st.success(f"체크인 완료: {ts.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')}")
                # 자리표시자 날씨 & play short audio to ensure user gesture used
                if lat is not None and lon is not None:
                    st.info(f"위치: lat={lat:.6f}, lon={lon:.6f}")
                    st.info("현재 날씨(자리표시자): 맑음, 15°C ☀️")
                    # try to play audio (may be blocked unless user gesture)
                    st.audio(ALARM_WAV)
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
        # 날짜별 첫 체크인 -> 시간(hour) 단위로 그룹
        df_plot = (dfc.assign(date=lambda x: pd.to_datetime(x["timestamp"]).dt.date,
                              hour=lambda x: pd.to_datetime(x["timestamp"]).dt.hour)
                        .sort_values("timestamp")
                        .groupby("date", as_index=False).first()
                        .sort_values("date"))
        st.caption("날짜별 첫 체크인 시각 (시간 단위)")
        if not df_plot.empty:
            st.line_chart(df_plot.set_index("date")["hour"])
    else:
        st.info("체크인 기록이 없습니다.")

# ------------------------
# ② 위험도/119 시나리오
# ------------------------
elif page == pages[1]:
    st.header("② 위험도 예측 및 자동 알림(시뮬레이션)")
    thr = st.slider("119/보호자 연락(가상) 발동 기준(%)", 10, 100, 60, 5)
    # reuse simplified risk calc
    def checkin_stats(df: pd.DataFrame, lookback_days=30):
        if df.empty:
            return {"missing_days": [], "daily": pd.DataFrame(), "mean_hour": None, "std_hour": None}
        df_recent = df[df["timestamp"] >= (now_kst() - timedelta(days=lookback_days))]
        if df_recent.empty:
            return {"missing_days": [], "daily": pd.DataFrame(), "mean_hour": None, "std_hour": None}
        daily = (df_recent.assign(date=lambda x: x["timestamp"].dt.date,
                                  hour=lambda x: x["timestamp"].dt.hour)
                       .sort_values("timestamp")
                       .groupby("date", as_index=False).first())
        days = [(now_kst().date() - timedelta(days=i)) for i in range(lookback_days)]
        missing = [d for d in days if d not in set(daily["date"].tolist())]
        if len(daily) >= 5:
            arr = daily["hour"].to_numpy()
            mu = float(np.mean(arr)); sd = float(np.std(arr)) if np.std(arr)>0 else 1.0
            return {"missing_days": missing, "daily": daily, "mean_hour": mu, "std_hour": sd}
        return {"missing_days": missing, "daily": daily, "mean_hour": None, "std_hour": None}

    cs = checkin_stats(checkins, lookback_days=30)
    missing_last3 = [d for d in cs.get("missing_days", []) if (now_kst().date() - d).days <= 3]
    n_missing3 = len(missing_last3)
    n_out7 = 0
    if "daily" in cs and len(cs["daily"])>0 and cs.get("mean_hour") is not None:
        last7 = cs["daily"][cs["daily"]["date"] >= (now_kst().date()-timedelta(days=7))]
        if len(last7) >= 5:
            arr = last7["hour"].to_numpy()
            z = (arr - cs["mean_hour"]) / (cs["std_hour"] if cs["std_hour"] else 1.0)
            n_out7 = int(np.sum(np.abs(z)>2))
    # adherence
    adherence = 1.0
    if not meds.empty:
        # estimate adherence simplistic
        to_dt = now_kst(); from_dt = to_dt - timedelta(days=7)
        taken = med_log[(pd.to_datetime(med_log["taken_at"])>=from_dt) & (pd.to_datetime(med_log["taken_at"])<=to_dt)]
        due_total = max(1, len(meds)*7)
        adherence = min(1.0, len(taken)/due_total)
    score = min(n_missing3,3)/3*40 + min(n_out7,5)/5*20 + (1.0 - adherence)*40
    score = round(max(0, min(100, score)),1)
    st.subheader(f"현재 위험도: {score}%")
    st.progress(min(1.0, score/100.0))
    c1, c2, c3 = st.columns(3)
    c1.metric("최근 3일 결측(일)", n_missing3)
    c2.metric("최근 7일 이상치(일)", n_out7)
    c3.metric("복약 준수(7일)", f"{round(adherence*100,1)}%")

    if score >= thr:
        st.error("⚠️ 위험도 임계치 초과! (가상 경보/연락 시나리오)")
        # try playing audio (user gesture usually required)
        st.audio(ALARM_WAV)
        st.markdown("""
**시뮬레이션: 자동 연락 절차**
1) 보호자 1차 연락 시도  
2) 미응답 시 119 연계 안내 음성 송출  
3) 위치/최근 체크인/복약정보 요약 전송(가상)
""")
    else:
        st.success("현재는 임계치 미만입니다.")

# ------------------------
# ③ 복약 스케줄러 / 리마인더
# ------------------------
elif page == pages[2]:
    st.header("③ 복약 스케줄러 / 리마인더")
    st.caption("앱이 열려 있을 때에만 리마인더가 화면에 표시됩니다 (프로토타입 한계).")

    with st.form("add_med", clear_on_submit=True):
        name = st.text_input("약 이름")
        interval = st.number_input("복용 간격(시간)", 1, 48, 12, 1)
        start_t = st.text_input("첫 복용 시각(HH:MM)", "08:00")
        notes = st.text_input("메모(선택)", "")
        if st.form_submit_button("추가"):
            if name and parse_time_str(start_t):
                meds = pd.concat([meds, pd.DataFrame([{
                    "name": name, "interval_hours": int(interval), "start_time": start_t, "notes": notes
                }])], ignore_index=True)
                save_csv(meds, MEDS_CSV)
                st.success(f"추가됨: {name}")
                st.experimental_rerun()
            else:
                st.error("입력 확인 (약 이름, 시각 HH:MM 필요)")

    if len(meds):
        st.subheader("등록된 약")
        st.dataframe(meds, use_container_width=True)
    else:
        st.info("등록된 약이 없습니다.")

    # enumerate due times (same as earlier)
    def enumerate_due_times(start_clock: dtime, interval_hours: int, from_dt: datetime, to_dt: datetime):
        start_at = datetime.combine(from_dt.date(), start_clock, tzinfo=KST)
        while start_at > from_dt:
            start_at -= timedelta(hours=interval_hours)
        while start_at + timedelta(hours=interval_hours) < from_dt:
            start_at += timedelta(hours=interval_hours)
        times, cur = [], start_at
        while cur <= to_dt:
            if cur >= from_dt: times.append(cur)
            cur += timedelta(hours=interval_hours)
        return times

    now = now_kst()
    due_items = []
    for _, row in meds.iterrows():
        sc = parse_time_str(str(row["start_time"]))
        if not sc: continue
        for d in enumerate_due_times(sc, int(row["interval_hours"]), now - timedelta(days=2), now + timedelta(days=1)):
            # check if already taken
            taken = med_log[(med_log["name"]==row["name"]) & (pd.to_datetime(med_log["taken_at"]).between(d - timedelta(minutes=60), d + timedelta(minutes=60)))]
            if len(taken): continue
            diff_min = (d - now).total_seconds()/60.0
            status = "🕒 곧 복약" if abs(diff_min) <= 15 else ("⏰ 연체" if diff_min < 0 and abs(diff_min) <= 24*60 else None)
            if status:
                due_items.append({"name": row["name"], "due_time": d, "status": status})

    st.subheader("리마인더")
    if due_items:
        for idx, item in enumerate(due_items):
            nm = item["name"]; due = item["due_time"].astimezone(KST).strftime("%Y-%m-%d %H:%M")
            status = item["status"]
            st.warning(f"{status}: {nm} / 예정시각 {due}")
            b1, b2, _ = st.columns([1,1,3])
            with b1:
                if st.button(f"✅ {nm} 복용 기록", key=f"take_{idx}"):
                    med_log = pd.concat([med_log, pd.DataFrame([{
                        "name": nm, "due_time": item["due_time"], "taken_at": now_kst()
                    }])], ignore_index=True)
                    save_csv(med_log, MEDLOG_CSV)
                    st.success(f"{nm} 복용 기록 완료")
                    st.experimental_rerun()
            with b2:
                # try audio alert (works more reliably after user gesture)
                st.audio(ALARM_WAV)
    else:
        st.success("현재 15분 이내 예정/연체 항목 없음")

    st.markdown("---")
    st.subheader("복용 기록")
    if not med_log.empty:
        st.dataframe(med_log.sort_values("taken_at", ascending=False).head(200), use_container_width=True)
    else:
        st.info("복용 기록 없음")

# ------------------------
# ④ 주변 의료기관 (CSV 업로드) + 반경 추천
# ------------------------
elif page == pages[3]:
    st.header("④ 주변 약국/병원 찾기 및 추천")
    st.caption("CSV 업로드(위도/경도 포함) -> 반경 내 추천. 집 위치 저장 가능.")

    inst_file = st.file_uploader("전국 의료기관 표준데이터 CSV 업로드", type=["csv"])
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
                raw["lat"] = pd.to_numeric(raw["lat"], errors="coerce")
                raw["lon"] = pd.to_numeric(raw["lon"], errors="coerce")
                # choose name col
                name_col = None
                for c in raw.columns:
                    if any(k in c.lower() for k in ["명","name","기관","병원","약국"]):
                        name_col = c; break
                if name_col: raw = raw.rename(columns={name_col:"name"})
                if "type" not in raw.columns:
                    raw["type"] = "병원"
                institutions = raw[[c for c in ["name","type","lat","lon","address"] if c in raw.columns]].copy()
                save_csv(institutions, INSTITUTIONS_CSV)
                st.success(f"업로드 완료: {len(institutions)}개 기관 저장")
            else:
                st.error("CSV에서 위도(lat)/경도(lon) 컬럼을 찾을 수 없습니다.")
        except Exception as e:
            st.error(f"파일 읽기 오류: {e}")

    # home location usage
    home = load_home()
    use_home = st.checkbox("저장된 집 위치 사용", value=(home is not None))
    if use_home and home is not None:
        lat = float(home["lat"]); lon = float(home["lon"])
        st.success(f"집 위치: {home['label']} ({lat:.6f}, {lon:.6f})")
        if st.button("집 위치 삭제"):
            try:
                os.remove(HOME_JSON)
            except Exception:
                pass
            st.experimental_rerun()
    else:
        lat = st.number_input("위도(lat)", value=37.5665, format="%.6f")
        lon = st.number_input("경도(lon)", value=126.9780, format="%.6f")
        if st.button("이 위치를 집으로 저장"):
            if save_home(lat, lon, "우리 집"):
                st.success("집 위치 저장됨")
                st.experimental_rerun()

    if not institutions.empty and {"lat","lon"}.issubset(institutions.columns):
        radius_km = st.slider("검색 반경(km)", 1, 30, 5)
        tsel = st.selectbox("기관 유형", ["전체","병원","약국"], index=0)
        df = institutions.copy()
        if tsel != "전체":
            df = df[df["type"].str.contains(tsel, na=False)]
        df["distance_km"] = haversine_km(lat, lon, df["lat"].astype(float), df["lon"].astype(float))
        df = df[df["distance_km"] <= radius_km].sort_values("distance_km").reset_index(drop=True)
        if len(df):
            df["rec_score"] = 1.0 - (df["distance_km"]/(radius_km+1e-9))
            st.subheader("추천 리스트 (가까운 순)")
            show_cols = [c for c in ["name","type","address","distance_km","rec_score"] if c in df.columns]
            st.dataframe(df[show_cols].head(100), use_container_width=True)
            # map display
            layers = [
                pdk.Layer("ScatterplotLayer", data=pd.DataFrame([{"name":"집","lat":lat,"lon":lon}]), get_position='[lon, lat]', get_radius=120, get_fill_color=[255,0,0,200]),
                pdk.Layer("ScatterplotLayer", data=df.head(200), get_position='[lon, lat]', get_radius=60, get_fill_color=[0,128,255,160])
            ]
            view_state = pdk.ViewState(latitude=lat, longitude=lon, zoom=12)
            st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view_state))
        else:
            st.info("반경 내 결과 없음.")
    else:
        st.info("의료기관 데이터가 없습니다. ⑤ 데이터/설정 탭에서 CSV 업로드하세요.")

# ------------------------
# ⑤ 치매예방 퀴즈
# ------------------------
elif page == pages[4]:
    st.header("⑤ 치매 예방 간단 퀴즈")
    if "dementia_wrong" not in st.session_state: st.session_state["dementia_wrong"] = 0

    name_input = st.text_input("이름 (퀴즈용)")
    with st.form("quiz", clear_on_submit=False):
        q1 = st.text_input("오늘 날짜는? (YYYY-MM-DD)")
        q2 = st.text_input("오늘 요일은? (예: 월요일)")
        q3 = st.text_input("당신의 성함은?")
        if st.form_submit_button("제출"):
            wrong = 0
            if q1.strip() != now_kst().date().strftime("%Y-%m-%d"): wrong += 1
            if q2.strip() == "" or q2.strip() not in ["월요일","화요일","수요일","목요일","금요일","토요일","일요일"]:
                # accept only Korean weekdays for now
                wrong += 1
            if name_input and q3.strip() != name_input.strip(): wrong += 1
            if wrong > 0:
                st.session_state["dementia_wrong"] += 1
                st.warning(f"{wrong}문제 틀렸습니다.")
            else:
                st.success("모두 정답입니다!")
                st.session_state["dementia_wrong"] = 0
            if st.session_state["dementia_wrong"] >= 3:
                st.markdown("<span style='color:darkorange;font-weight:bold;'>치매가 의심됩니다. 가까운 병원을 추천해드릴게요.</span>", unsafe_allow_html=True)
                # show nearby hospitals if possible
                home = load_home()
                if home is not None and not institutions.empty and {"lat","lon"}.issubset(institutions.columns):
                    dfh = institutions.copy()
                    dfh["distance_km"] = haversine_km(home["lat"], home["lon"], dfh["lat"].astype(float), dfh["lon"].astype(float))
                    top3 = dfh[dfh["type"].str.contains("병원", na=False)].sort_values("distance_km").head(3)
                    if len(top3):
                        st.dataframe(top3[["name","address","distance_km"]])
                    else:
                        st.info("근처 병원 데이터가 부족합니다.")
                else:
                    st.info("집 위치 또는 기관 데이터가 없어 추천을 제공할 수 없습니다.")

    st.markdown("---")
    st.subheader("간단 퍼즐 (자리표시자)")
    st.info("3x3 퍼즐/게임은 자리표시자입니다. 원하면 실제 게임 로직 추가해 드릴게요.")

# ------------------------
# ⑥ 연락망
# ------------------------
elif page == pages[5]:
    st.header("⑥ 자녀 및 지인 연락망")
    contacts = load_contacts()
    with st.form("add_contact", clear_on_submit=True):
        nm = st.text_input("이름")
        phone = st.text_input("전화번호")
        if st.form_submit_button("추가"):
            if nm and phone:
                contacts.append({"name": nm, "phone": phone})
                save_contacts(contacts)
                st.success("연락처 추가됨")
                st.experimental_rerun()
            else:
                st.error("이름/전화번호 입력하세요.")
    if contacts:
        st.dataframe(pd.DataFrame(contacts), use_container_width=True)
    else:
        st.info("저장된 연락처가 없습니다.")

# ------------------------
# ⑦ 똥강아지 말동무 (Web Speech API)
# ------------------------
elif page == pages[6]:
    st.header("⑦ 똥강아지 — 말동무 (음성/텍스트)")
    st.markdown("음성은 브라우저 Web Speech API를 사용합니다. Chrome 권장. '말하기 시작' 버튼을 눌러주세요.")

    if "dog_chat" not in st.session_state:
        st.session_state["dog_chat"] = []

    mode = st.radio("대화 방식", ["키보드(텍스트)","음성(브라우저)"], horizontal=True)

    if mode.startswith("키보드"):
        txt = st.text_input("메시지를 입력하세요", key="dog_input")
        if st.button("전송", key="dog_send"):
            if txt:
                st.session_state["dog_chat"].append({"who":"user","text":txt})
                # simple rule-based reply
                if any(k in txt for k in ["안녕","하이","안녕하세요","반가워"]):
                    reply = "안녕하세요! 오늘 기분은 어떠신가요?"
                elif any(k in txt for k in ["심심","외로","힘들"]):
                    reply = "제가 이야기 상대가 되어드릴게요. 어떤 얘기부터 할까요?"
                else:
                    reply = "그런 말은 처음이네요. 더 말씀해 주세요."
                st.session_state["dog_chat"].append({"who":"bot","text":reply})
                st.experimental_rerun()
    else:
        # JS component for SpeechRecognition + TTS via SpeechSynthesis
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
            document.getElementById('status').innerText = '음성 인식을 지원하지 않는 브라우저입니다. (Chrome 권장)';
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
        v = st_html(speech_html, height=200)
        if v is not None and isinstance(v, dict) and v.get("action") == "voice_text":
            user_msg = v.get("text","")
            st.session_state["dog_chat"].append({"who":"user","text":user_msg})
            if any(k in user_msg for k in ["안녕","하이","반가워"]):
                bot = "안녕하세요! 만나서 반가워요."
            elif any(k in user_msg for k in ["심심","외로","외로워"]):
                bot = "저랑 이야기해주셔서 고마워요. 같이 있어줄게요."
            else:
                bot = "응응, 더 말씀해 주세요."
            st.session_state["dog_chat"].append({"who":"bot","text":bot})
            # use browser TTS to speak reply
            tts_html = f"<script>const u=new SpeechSynthesisUtterance({json.dumps(bot)});u.lang='ko-KR';window.speechSynthesis.cancel();window.speechSynthesis.speak(u);</script>"
            st_html(tts_html, height=1)

    st.markdown("---")
    st.subheader("대화 기록")
    for m in st.session_state["dog_chat"][-60:]:
        if m["who"] == "user":
            st.markdown(f"**사용자:** {m['text']}")
        else:
            st.markdown(f"**똥강아지:** {m['text']}")

# ------------------------
# ⑧ 데이터 / 설정
# ------------------------
elif page == pages[7]:
    st.header("⑧ 데이터/설정 (자료 관리)")
    st.markdown("CSV 업로드/다운로드 및 앱 상태 확인")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.download_button("체크인 CSV", data=checkins.to_csv(index=False).encode("utf-8"), file_name="checkins.csv")
    with c2:
        st.download_button("약 목록 CSV", data=meds.to_csv(index=False).encode("utf-8"), file_name="meds.csv")
    with c3:
        st.download_button("복약 기록 CSV", data=med_log.to_csv(index=False).encode("utf-8"), file_name="med_log.csv")
    with c4:
        if not institutions.empty:
            st.download_button("의료기관 CSV", data=institutions.to_csv(index=False).encode("utf-8"), file_name="institutions.csv")
        else:
            st.write("의료기관 CSV: (없음)")

    st.markdown("---")
    st.markdown("의료기관/지역 데이터 업로드 (옵션)")
    inst_up = st.file_uploader("의료기관 CSV 업로드", type=["csv"])
    if inst_up is not None:
        try:
            df_inst = safe_read_csv(inst_up)
            df_inst.to_csv(INSTITUTIONS_CSV, index=False)
            st.success("업로드/저장 완료")
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
    if not institutions.empty:
        st.dataframe(institutions.head(5))
    else:
        st.info("의료기관 데이터 없음")

# ------------------------
# 종료 시 상태 저장
# ------------------------
try:
    save_csv(checkins, CHECKIN_CSV)
    save_csv(meds, MEDS_CSV)
    save_csv(med_log, MEDLOG_CSV)
    if not institutions.empty: save_csv(institutions, INSTITUTIONS_CSV)
    if not regional.empty: save_csv(regional, REGIONAL_CSV)
except Exception:
    pass
